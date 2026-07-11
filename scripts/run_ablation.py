# -*- coding: utf-8 -*-
"""T15 对照实验 harness: graph-on vs graph-off 头比较 (headless, 不开 GUI)。

设计:
  - 同样的 seed / N_RESIDENTS / 停电步, 仅 use_road_graph 不同
  - 跑 TOTAL_STEPS 步 (DT=0.25 → 默认 30 仿真小时)
  - 第 OUTAGE_STEP 步触发整区停电
  - 收集 per-step 全局指标 + end-of-run edge 观测
  - 输出 trace_output/t15_{城市}_{区}[_{tag}]/graph_{on,off}/ 各一套 CSV

调用:
    # 默认 (厦门思明区) → trace_output/t15_厦门市_思明区/
    python scripts/run_ablation.py

    # F1 三城对照 → trace_output/M4_F1_cross_city/t15_<城>_<区>/
    python scripts/run_ablation.py --city 沈阳市 --district 沈河区 \
        --output-base M4_F1_cross_city

    # F4 多 seed → trace_output/M4_F4_multi_seed/t15_..._seed03/
    python scripts/run_ablation.py --seed 3 --tag seed03 \
        --output-base M4_F4_multi_seed

    # F7 N 扫描 → trace_output/M4_F7_N_scan/t15_..._N500/
    python scripts/run_ablation.py --n-residents 500 --tag N500 \
        --output-base M4_F7_N_scan
"""
import os
import sys
import csv
import json
import time
import argparse
import random
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
import numpy as np

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False
import matplotlib.pyplot as plt

# 直接 `python scripts/run_ablation.py` 时 sys.path[0] 是 scripts/, 加入项目根
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config.city_manager import CityManager
from config.config import Config
from simulation.simulation import BlackoutSimulation
from core.unified_stress_model import unified_stress_model


TRACE_ROOT = os.path.join(ROOT, 'trace_output')
MAP_DIR = os.path.join(ROOT, 'simulation map data')
os.makedirs(TRACE_ROOT, exist_ok=True)


# =============================================================================
# 默认实验参数（可通过 CLI 覆盖）
# =============================================================================
DEFAULT_CITY        = '厦门市'
DEFAULT_DISTRICT    = '思明区'
DEFAULT_N_RESIDENTS = 800      # 居民数 (压力放大, 让 cascade 显现)
DEFAULT_N_ENT       = 30
DEFAULT_TOTAL_STEPS = 120      # 120 步 × DT=0.25h = 30 仿真小时
DEFAULT_OUTAGE_STEP = 16       # 早点触发, 留更多时间形成 cascade
DEFAULT_SEED        = 42

GLOBAL_METRIC_FIELDS = [
    'step', 't_hour',
    'avg_stress', 'max_stress', 'pct_stress_gt_06',
    'avg_emotion', 'avg_panic',
    'hoard_ratio', 'herd_ratio', 'flee_ratio', 'outage_ratio',
    'avg_edge_congestion', 'pct_on_path',
    'opinion_pressure', 'total_opinion_pressure', 'public_opinion_active',
    'opinion_active_district_count', 'opinion_active_district_ratio',
    'opinion_active_resident_count', 'opinion_active_resident_ratio',
    'opinion_trigger_pressure', 'opinion_threshold_margin',
    'opinion_effect_nonzero',
    'seir_S', 'seir_E', 'seir_I', 'seir_R',
    'seir_infection_reduction', 'rumor_suppress_rate',
]


# =============================================================================
# 收集每步全局指标 (replicate dashboard._update_history 的关键部分)
# =============================================================================
def _collect_step_metrics(sim):
    residents = sim.residents
    n = max(1, len(residents))
    event_effects = getattr(sim, 'last_event_effects', {}) or {}
    event_summary = getattr(sim, 'last_event_summary', None)
    if event_summary is None:
        hist = getattr(sim, 'event_effects_hist', [])
        event_summary = hist[-1] if hist else {}
    opinion_effect = (
        event_effects.get('government', {})
        .get('opinion_manage', {})
    )
    gov_agents = list(getattr(sim, 'gov_agents', {}).values())
    active_district_count = sum(
        1 for gov in gov_agents
        if bool(getattr(gov, 'public_opinion_active', False))
    )
    public_opinion_active = any(
        bool(getattr(gov, 'public_opinion_active', False))
        for gov in gov_agents
    )
    active_resident_count = sum(
        1 for r in residents
        if bool(getattr(r, '_opinion_management_active', False))
    )
    opinion_trigger_pressure = max(
        (float(getattr(gov, 'last_opinion_pressure', 0.0)) for gov in gov_agents),
        default=0.0,
    )
    opinion_threshold_margin = max(
        (float(getattr(gov, 'last_opinion_threshold_margin', 0.0)) for gov in gov_agents),
        default=0.0,
    )
    opinion_effect_values = [
        float(opinion_effect.get('official_info_boost', 0.0)),
        float(opinion_effect.get('rumor_suppress_rate', 0.0)),
        float(opinion_effect.get('seir_infection_reduction', 0.0)),
        float(opinion_effect.get('panic_spread_reduction', 0.0)),
    ]
    opinion_effect_nonzero = any(abs(v) > 1e-12 for v in opinion_effect_values)
    seir_counts = Counter(getattr(r, 'state', 'S') for r in residents)
    stress_arr = np.fromiter(
        (float(getattr(r, 'stress_level', 0.0)) for r in residents), dtype=np.float64, count=n)
    emotion_arr = np.fromiter(
        (float(getattr(r, 'emotion', 0.0)) for r in residents), dtype=np.float64, count=n)
    panic_arr = np.fromiter(
        (float(getattr(r, 'panic_value', 0.0)) for r in residents), dtype=np.float64, count=n)
    hoard_arr = np.fromiter(
        (1 if getattr(r, 'is_hoarding', False) else 0 for r in residents), dtype=np.int8, count=n)
    herd_arr = np.fromiter(
        (1 if getattr(r, '_herd_active', False) else 0 for r in residents), dtype=np.int8, count=n)
    cong_arr = np.fromiter(
        (float(getattr(r, '_edge_congestion', 0.0)) for r in residents), dtype=np.float64, count=n)
    on_path_arr = np.fromiter(
        (1 if getattr(r, 'current_edge', None) is not None else 0 for r in residents),
        dtype=np.int8, count=n)
    n_off = sum(1 for p in sim.zone_status.values() if not p)
    outage_ratio = n_off / max(1, len(sim.zone_status))
    flee_arr = np.fromiter(
        (1 if getattr(r, '_dom_action', None) == 'flee' else 0 for r in residents),
        dtype=np.int8, count=n)
    return {
        'avg_stress':           float(stress_arr.mean()),
        'max_stress':           float(stress_arr.max()) if n else 0.0,
        'pct_stress_gt_06':     float((stress_arr > 0.6).mean()),
        'avg_emotion':          float(emotion_arr.mean()),
        'avg_panic':            float(panic_arr.mean()),
        'hoard_ratio':          float(hoard_arr.mean()),
        'herd_ratio':           float(herd_arr.mean()),
        'flee_ratio':           float(flee_arr.mean()),
        'outage_ratio':         outage_ratio,
        'avg_edge_congestion':  float(cong_arr.mean()),
        'pct_on_path':          float(on_path_arr.mean()),
        'opinion_pressure':     float(getattr(getattr(sim, 'event_influence', None), 'opinion_pressure', 0.0)),
        'total_opinion_pressure': float(event_summary.get('total_opinion_pressure', 0.0)),
        'public_opinion_active': float(public_opinion_active),
        'opinion_active_district_count': float(active_district_count),
        'opinion_active_district_ratio': float(active_district_count / len(gov_agents)) if gov_agents else 0.0,
        'opinion_active_resident_count': float(active_resident_count),
        'opinion_active_resident_ratio': float(active_resident_count / n),
        'opinion_trigger_pressure': float(opinion_trigger_pressure),
        'opinion_threshold_margin': float(opinion_threshold_margin),
        'opinion_effect_nonzero': float(opinion_effect_nonzero),
        'seir_S':               float(seir_counts.get('S', 0) / n),
        'seir_E':               float(seir_counts.get('E', 0) / n),
        'seir_I':               float(seir_counts.get('I', 0) / n),
        'seir_R':               float(seir_counts.get('R', 0) / n),
        'seir_infection_reduction': float(opinion_effect.get('seir_infection_reduction', 0.0)),
        'rumor_suppress_rate':  float(opinion_effect.get('rumor_suppress_rate', 0.0)),
    }


SWITCH_ABLATION_OVERRIDES = {
    'none': {},
    'hard_switch': {'use_mml': False, 'k1': 50.0, 'k2': 50.0, 'k3': 50.0, 'k4': 50.0},
    'soft_switch': {'use_mml': False, 'k1': 1.0, 'k2': 1.0, 'k3': 1.0, 'k4': 1.0},
    'no_info_network': {'lambda_c': 0.0, 'gamma': 0.0},
    'distance_only_store': {'lambda_f': 0.0, 'lambda_c': 0.0, 'gamma': 0.0},
    'no_inertia': {'mu': 1.0},
    'no_hysteresis': {'enable_hysteresis': False},
    'no_outcome_feedback': {'enable_outcome_feedback': False},
    'no_behavior_demo': {'enable_behavior_demo': False},
    'i1_minimal': {
        'enable_hysteresis': False,
        'enable_outcome_feedback': False,
        'enable_behavior_demo': False,
        'enable_inquire': False,
    },
    'no_flee': {'enable_flee_behavior': False},
}

SWITCH_AUDIT_FIELDS = sorted({
    name
    for overrides in SWITCH_ABLATION_OVERRIDES.values()
    for name in overrides.keys()
} | {
    'lambda_d',
    'lambda_f',
    'eta_demo_hoard',
    'eta_demo_herd',
    'enable_congestion_feedback',
})


def _switch_param_target_records(sim):
    records = []
    fc = getattr(sim, 'force_calculator', None)
    if fc is not None:
        if hasattr(fc, 'sw'):
            records.append(('force_calculator.sw', fc.sw))
        sfm = getattr(fc, 'social_force_model', None)
        if sfm is not None and hasattr(sfm, 'sw'):
            records.append(('force_calculator.social_force_model.sw', sfm.sw))
    for idx, r in enumerate(getattr(sim, 'residents', [])):
        if getattr(r, 'sw', None) is not None:
            records.append((f'resident[{idx}].sw', r.sw))
    return records


def _switch_param_targets(sim):
    return [sw for _owner, sw in _switch_param_target_records(sim)]


def _jsonable(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _run_git(args):
    try:
        proc = subprocess.run(
            ['git', '-C', ROOT] + list(args),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=5,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout.strip()
    except Exception:
        return None


def _git_info():
    status = _run_git(['status', '--short'])
    return {
        'commit': _run_git(['rev-parse', 'HEAD']),
        'dirty': bool(status),
        'status_short': status or '',
    }


def _write_manifest(args, out_dir, label, use_road_graph, sim):
    manifest = {
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'city': args.city,
        'district': args.district,
        'seed': args.seed,
        'n_residents': args.n_residents,
        'n_enterprises': args.n_enterprises,
        'total_steps': args.total_steps,
        'outage_step': args.outage_step,
        'outage_cause': getattr(args, 'outage_cause', 'equipment_failure'),
        'tag': getattr(args, 'tag', ''),
        'graph_mode': label,
        'use_road_graph': bool(use_road_graph),
        'use_mml': not bool(getattr(args, 'no_mml', False)),
        'switch_ablation': getattr(args, 'switch_ablation', 'none') or 'none',
        'opinion_mode': getattr(args, 'opinion_mode', 'auto'),
        'outage_stress_profile': getattr(args, 'outage_stress_profile', 'sqrt'),
        'home_distribution': getattr(args, 'home_distribution', None) or 'poi',
        'output_dir': os.path.abspath(out_dir),
        'restores_in_window': getattr(sim, '_restores_in_window', None),
        'git': _git_info(),
    }
    path = os.path.join(out_dir, 'manifest.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f'[manifest] saved {path}')
    return manifest


def _desired_run_config(args):
    return {
        'city': args.city,
        'district': args.district,
        'n_residents': args.n_residents,
        'n_enterprises': args.n_enterprises,
        'total_steps': args.total_steps,
        'outage_step': args.outage_step,
        'outage_cause': getattr(args, 'outage_cause', 'equipment_failure'),
        'seed': args.seed,
        'tag': args.tag,
        'home_distribution': getattr(args, 'home_distribution', None) or 'poi',
        'flee_threshold': getattr(args, 'flee_threshold', None),
        'use_mml': not bool(getattr(args, 'no_mml', False)),
        'switch_ablation': getattr(args, 'switch_ablation', 'none') or 'none',
        'opinion_mode': getattr(args, 'opinion_mode', 'auto'),
        'outage_stress_profile': getattr(args, 'outage_stress_profile', 'sqrt'),
        'mml_overrides': {
            'mml_scale': getattr(args, 'mml_scale', None),
            'mml_asc_flee': getattr(args, 'mml_asc_flee', None),
            'mml_b_sigma_flee': getattr(args, 'mml_b_sigma_flee', None),
            'mml_b_vis': getattr(args, 'mml_b_vis', None),
        },
    }


def _load_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _existing_run_config(run_dir):
    summary = _load_json(os.path.join(run_dir, 'summary.json'))
    if isinstance(summary, dict) and isinstance(summary.get('config'), dict):
        return summary['config'], 'summary.json'

    config_keys = set(_desired_run_config_for_manifest_keys())
    for label in ('on', 'off'):
        manifest = _load_json(os.path.join(run_dir, f'graph_{label}', 'manifest.json'))
        if isinstance(manifest, dict):
            return {
                k: v for k, v in manifest.items()
                if k in config_keys
            }, f'graph_{label}/manifest.json'
    return None, None


def _desired_run_config_for_manifest_keys():
    return (
        'city',
        'district',
        'n_residents',
        'n_enterprises',
        'total_steps',
        'outage_step',
        'outage_cause',
        'seed',
        'tag',
        'home_distribution',
        'flee_threshold',
        'use_mml',
        'switch_ablation',
        'opinion_mode',
        'outage_stress_profile',
        'mml_overrides',
    )


def _guard_run_dir(run_dir, args):
    if not os.path.isdir(run_dir):
        return
    if getattr(args, 'allow_overwrite', False):
        print(f'[output] WARN: --allow-overwrite enabled for existing directory: {run_dir}')
        return

    existing, source = _existing_run_config(run_dir)
    if existing is None:
        raise SystemExit(
            '[output] ERROR: output directory already exists but has no readable '
            f'summary/manifest metadata:\n  {run_dir}\n'
            'Use a unique --tag, move the existing folder, or rerun with '
            '--allow-overwrite if overwriting is intentional.'
        )

    desired = _desired_run_config(args)
    mismatches = []
    for key, desired_value in desired.items():
        if key in existing and existing.get(key) != desired_value:
            mismatches.append((key, existing.get(key), desired_value))

    if mismatches:
        detail = '\n'.join(
            f'  - {key}: existing={old!r}, requested={new!r}'
            for key, old, new in mismatches[:12]
        )
        if len(mismatches) > 12:
            detail += f'\n  - ... {len(mismatches) - 12} more'
        raise SystemExit(
            '[output] ERROR: refusing to write into an existing run directory '
            'with different parameters.\n'
            f'  run_dir: {run_dir}\n'
            f'  metadata: {source}\n'
            f'{detail}\n'
            'Use a unique --tag that includes mode/profile/seed, move the '
            'existing folder, or pass --allow-overwrite intentionally.'
        )
    print(f'[output] existing run_dir matches requested config: {run_dir}')


def _first_crossing(history, key, threshold):
    for rec in history:
        if rec.get(key, 0.0) >= threshold:
            return {
                'step': rec.get('step'),
                't_hour': rec.get('t_hour'),
            }
    return None


def _first_positive(history, key, eps=1e-12):
    for rec in history:
        if rec.get(key, 0.0) > eps:
            return {
                'step': rec.get('step'),
                't_hour': rec.get('t_hour'),
            }
    return None


def _collect_switch_audit(sim):
    records = _switch_param_target_records(sim)
    target_types = Counter(owner.split('[', 1)[0] for owner, _sw in records)
    read_counts = Counter()
    values = defaultdict(Counter)
    for _owner, sw in records:
        for key, count in getattr(sw, '_audit_reads', {}).items():
            read_counts[key] += int(count)
        for field in SWITCH_AUDIT_FIELDS:
            if hasattr(sw, field):
                values[field][repr(getattr(sw, field))] += 1
    return {
        'holders': len(records),
        'target_types': dict(target_types),
        'read_counts': dict(sorted(read_counts.items())),
        'field_values': {
            field: dict(counter)
            for field, counter in sorted(values.items())
        },
    }


def _write_switch_audit(sim, out_dir, override_audits):
    audit = _collect_switch_audit(sim)
    audit['override_audits'] = override_audits
    path = os.path.join(out_dir, 'switch_audit.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    print(f'[audit] saved {path}')
    return audit


def _apply_switch_overrides(sim, overrides, label):
    overrides = {k: v for k, v in overrides.items() if v is not None}
    audit = {
        'label': label,
        'requested_overrides': {k: _jsonable(v) for k, v in overrides.items()},
        'holders': 0,
        'applied_counts': {},
        'missing_counts': {},
        'changed_counts': {},
    }
    if not overrides:
        return audit
    records = _switch_param_target_records(sim)
    audit['holders'] = len(records)
    applied = Counter()
    missing = Counter()
    changed = Counter()
    for _owner, sw in records:
        for name, value in overrides.items():
            if hasattr(sw, name):
                old = getattr(sw, name)
                setattr(sw, name, value)
                applied[name] += 1
                if old != value:
                    changed[name] += 1
            else:
                missing[name] += 1
    audit['applied_counts'] = dict(applied)
    audit['missing_counts'] = dict(missing)
    audit['changed_counts'] = dict(changed)
    print(f'[{label}] SwitchParams overrides -> {overrides} ({len(records)} holders)')
    return audit


# =============================================================================
# 跑一组实验
# =============================================================================
def run_one(label, use_road_graph, args, run_dir):
    print(f'\n{"="*70}\n  Run "{label}" (use_road_graph={use_road_graph})\n{"="*70}')
    random.seed(args.seed)
    np.random.seed(args.seed)

    cm = CityManager(map_data_dir=MAP_DIR)
    sm_path = cm.get_district_geojson(args.city, args.district, use_no_mountain=True)
    if not sm_path:
        raise RuntimeError(f'未找到 {args.city}/{args.district} GeoJSON (MAP_DIR={MAP_DIR})')
    print(f'  [city] {args.city}/{args.district} → {sm_path}')

    city_config = {
        'city': args.city,
        'geojson_paths': [sm_path],
        'districts': [args.district],
        'use_road_graph': use_road_graph,
    }
    cfg = Config()
    cfg.simulation.N_RESIDENTS = args.n_residents
    cfg.simulation.N_ENTERPRISES = args.n_enterprises
    cfg.simulation.TOTAL_STEPS = args.total_steps
    # F2 控制实验: home 分布策略 ('poi' 默认 / 'uniform' 去 POI bias)
    home_dist = getattr(args, 'home_distribution', None)
    if home_dist:
        cfg.simulation.HOME_DISTRIBUTION = home_dist

    t0 = time.time()
    sim = BlackoutSimulation(config=cfg, city_config=city_config)
    sim.set_opinion_mode(getattr(args, 'opinion_mode', 'auto'))
    unified_stress_model.set_outage_stress_profile(
        getattr(args, 'outage_stress_profile', 'sqrt')
    )
    print(f'[init] {time.time()-t0:.1f}s, use_road_graph={sim.use_road_graph}')
    print(f'[validation] opinion_mode={sim.opinion_mode}, '
          f'outage_stress_profile={unified_stress_model.OUTAGE_STRESS_PROFILE}')
    override_audits = []

    # F5 控制实验: flee_threshold 覆盖 (默认 0.6, 扫描 {0.4..0.8} 验证 phase transition)
    flee_th = getattr(args, 'flee_threshold', None)
    if flee_th is not None:
        override_audits.append(
            _apply_switch_overrides(sim, {'flee_threshold': float(flee_th)}, 'F5')
        )

    # F13: MML 默认开 (SwitchParams.use_mml=True 自 2026-06-28 起为默认).
    # --no-mml 显式切回 sigmoid legacy fallback; --use-mml 显式确认 (no-op)
    effective_use_mml = not bool(getattr(args, 'no_mml', False))
    if not effective_use_mml:
        override_audits.append(
            _apply_switch_overrides(sim, {'use_mml': False}, 'F13')
        )
    else:
        print(f'[F13] use_mml = True (MML default)')

    switch_ablation = getattr(args, 'switch_ablation', 'none') or 'none'
    if switch_ablation != 'none':
        override_audits.append(
            _apply_switch_overrides(
                sim,
                SWITCH_ABLATION_OVERRIDES.get(switch_ablation, {}),
                f'E2:{switch_ablation}',
            )
        )

    # F13 sensitivity hooks: allow one-knob MML coefficient sweeps without
    # editing SwitchParams defaults in core/behavior_switching.py.
    mml_overrides = {
        'mml_scale': getattr(args, 'mml_scale', None),
        'mml_asc_flee': getattr(args, 'mml_asc_flee', None),
        'mml_b_sigma_flee': getattr(args, 'mml_b_sigma_flee', None),
        'mml_b_vis': getattr(args, 'mml_b_vis', None),
    }
    mml_overrides = {k: v for k, v in mml_overrides.items() if v is not None}
    if mml_overrides:
        override_audits.append(
            _apply_switch_overrides(
                sim,
                {name: float(value) for name, value in mml_overrides.items()},
                'F13',
            )
        )

    history = []
    triggered = False
    t_start = time.time()
    for step in range(args.total_steps):
        sim.step()
        sim.step_count = step + 1
        if step == args.outage_step and not triggered:
            try:
                sim.trigger_district_outage(mode='full',
                                            cause=args.outage_cause,
                                            damage_level=args.damage_level)
                print(f'[outage] triggered at step {step} '
                      f'(cause={args.outage_cause})')
                triggered = True
                # 【护栏】预估复电点是否落在仿真窗口内。基线前提是"断电贯穿
                # 全程": equipment_failure 在满动员能力 2.40 units/h 下复电点
                # t≈31.6h, 距 30h 窗口仅 ~1.6h。任何调大修复能力 / 调小工作量
                # 的改动都可能悄悄破坏前提 — 让第一个 run 就把它喊出来。
                try:
                    _est_h, _ = sim._estimate_repair_time()
                    _t_out = args.outage_step * float(sim.dt)
                    _t_win = args.total_steps * float(sim.dt)
                    _det = float(getattr(sim, 'district_fault_detection_time', 0.0) or 0.0)
                    _t_restore = _t_out + _det + _est_h
                    sim._restores_in_window = bool(_t_restore <= _t_win)
                    _flag = ('WARN: 复电点在窗口内, "断电贯穿全程"前提被破坏!'
                             if sim._restores_in_window else '断电贯穿全程 OK')
                    print(f'[outage] 预估复电点 t≈{_t_restore:.1f}h / '
                          f'窗口 {_t_win:.0f}h — {_flag}')
                except Exception as _ex:
                    sim._restores_in_window = None
                    print(f'[outage] restore-estimate WARN: {_ex}')
            except Exception as ex:
                print(f'[outage] WARN: {ex}')
        rec = _collect_step_metrics(sim)
        rec['step'] = step
        rec['t_hour'] = round(step * float(sim.dt), 3)
        history.append(rec)
    sim_secs = time.time() - t_start
    print(f'[run] {args.total_steps} steps in {sim_secs:.1f}s '
          f'({sim_secs*1000/args.total_steps:.0f}ms/step)')

    out_dir = os.path.join(run_dir, f'graph_{label}')
    os.makedirs(out_dir, exist_ok=True)
    sim._manifest = _write_manifest(args, out_dir, label, use_road_graph, sim)
    csv_path = os.path.join(out_dir, 'global_metrics.csv')
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=GLOBAL_METRIC_FIELDS)
        w.writeheader()
        for rec in history:
            w.writerow({k: rec.get(k, 0) for k in GLOBAL_METRIC_FIELDS})
    print(f'[trace] saved {csv_path}')
    sim._switch_audit = _write_switch_audit(sim, out_dir, override_audits)

    if sim.use_road_graph:
        edge_path = os.path.join(out_dir, 'edge_observations.csv')
        sim.write_edge_observations(edge_path)
        print(f'[trace] saved {edge_path}')

    return history, sim


# =============================================================================
# 对比 + 画图
# =============================================================================
def plot_compare(h_off, h_on, args, run_dir, sim_off=None, sim_on=None):
    """先写 summary.json (机器可读, 关键路径), 再画图 (易碎, 兜底)。"""
    metrics_to_plot = [
        ('avg_stress', '平均 σ (stress)'),
        ('max_stress', '最大个体 σ'),
        ('pct_stress_gt_06', '高压人群比例 (σ>0.6)'),
        ('herd_ratio', 'herd ratio'),
        ('flee_ratio', 'flee ratio (向 shelter 逃)'),
        ('avg_edge_congestion', '平均 edge congestion'),
    ]
    summary_metrics = [
        k for k in GLOBAL_METRIC_FIELDS
        if k not in {'step', 't_hour'}
    ]
    peak_metrics = [
        'avg_stress', 'max_stress', 'avg_panic',
        'herd_ratio', 'flee_ratio',
        'opinion_pressure', 'opinion_trigger_pressure',
        'opinion_threshold_margin', 'opinion_active_resident_ratio',
        'seir_I',
    ]

    # ---- 1) 关键路径: 先写 summary.json (matplotlib 不参与, 不会 crash) ----
    summary = {
        'config': {
            'city':          args.city,
            'district':      args.district,
            'n_residents':   args.n_residents,
            'n_enterprises': args.n_enterprises,
            'total_steps':   args.total_steps,
            'outage_step':   args.outage_step,
            'outage_cause':  getattr(args, 'outage_cause', 'equipment_failure'),
            'restores_in_window': getattr(sim_on, '_restores_in_window', None),
            'seed':          args.seed,
            'tag':           args.tag,
            'home_distribution': getattr(args, 'home_distribution', None) or 'poi',
            'flee_threshold':    getattr(args, 'flee_threshold', None),
            'use_mml':           not bool(getattr(args, 'no_mml', False)),
            'switch_ablation':    getattr(args, 'switch_ablation', 'none') or 'none',
            'opinion_mode':       getattr(args, 'opinion_mode', 'auto'),
            'outage_stress_profile': getattr(args, 'outage_stress_profile', 'sqrt'),
            'mml_overrides': {
                'mml_scale': getattr(args, 'mml_scale', None),
                'mml_asc_flee': getattr(args, 'mml_asc_flee', None),
                'mml_b_sigma_flee': getattr(args, 'mml_b_sigma_flee', None),
                'mml_b_vis': getattr(args, 'mml_b_vis', None),
            },
        },
        'final': {
            k: {'off': h_off[-1][k], 'on': h_on[-1][k]}
            for k in summary_metrics
        },
        'peak': {
            k: {'off': max(r[k] for r in h_off), 'on': max(r[k] for r in h_on)}
            for k in peak_metrics
        },
        'peak_stress': {
            'off': max(r['avg_stress'] for r in h_off),
            'on':  max(r['avg_stress'] for r in h_on),
        },
        'peak_herd_ratio': {
            'off': max(r['herd_ratio'] for r in h_off),
            'on':  max(r['herd_ratio'] for r in h_on),
        },
        'avg_stress_threshold_crossings': {
            str(th): {
                'off': _first_crossing(h_off, 'avg_stress', th),
                'on': _first_crossing(h_on, 'avg_stress', th),
            }
            for th in (0.4, 0.6, 0.8)
        },
        'mechanism_checks': {
            'public_opinion_active_any': {
                'off': any(r.get('public_opinion_active', 0) >= 1 for r in h_off),
                'on': any(r.get('public_opinion_active', 0) >= 1 for r in h_on),
            },
            'opinion_active_steps': {
                'off': sum(1 for r in h_off if r.get('opinion_active_resident_ratio', 0.0) > 0),
                'on': sum(1 for r in h_on if r.get('opinion_active_resident_ratio', 0.0) > 0),
            },
            'first_opinion_active_step': {
                'off': _first_positive(h_off, 'opinion_active_resident_ratio'),
                'on': _first_positive(h_on, 'opinion_active_resident_ratio'),
            },
            'max_opinion_active_district_count': {
                'off': max(r.get('opinion_active_district_count', 0.0) for r in h_off),
                'on': max(r.get('opinion_active_district_count', 0.0) for r in h_on),
            },
            'max_opinion_active_resident_ratio': {
                'off': max(r.get('opinion_active_resident_ratio', 0.0) for r in h_off),
                'on': max(r.get('opinion_active_resident_ratio', 0.0) for r in h_on),
            },
            'max_opinion_trigger_pressure': {
                'off': max(r.get('opinion_trigger_pressure', 0.0) for r in h_off),
                'on': max(r.get('opinion_trigger_pressure', 0.0) for r in h_on),
            },
            'max_opinion_threshold_margin': {
                'off': max(r.get('opinion_threshold_margin', 0.0) for r in h_off),
                'on': max(r.get('opinion_threshold_margin', 0.0) for r in h_on),
            },
            'nonzero_opinion_effect_any': {
                'off': any(r.get('opinion_effect_nonzero', 0.0) > 0 for r in h_off),
                'on': any(r.get('opinion_effect_nonzero', 0.0) > 0 for r in h_on),
            },
            'max_seir_infection_reduction': {
                'off': max(r.get('seir_infection_reduction', 0.0) for r in h_off),
                'on': max(r.get('seir_infection_reduction', 0.0) for r in h_on),
            },
            'max_rumor_suppress_rate': {
                'off': max(r.get('rumor_suppress_rate', 0.0) for r in h_off),
                'on': max(r.get('rumor_suppress_rate', 0.0) for r in h_on),
            },
        },
        'switch_audit': {
            'off': getattr(sim_off, '_switch_audit', None),
            'on': getattr(sim_on, '_switch_audit', None),
        },
        'manifest': {
            'off': getattr(sim_off, '_manifest', None),
            'on': getattr(sim_on, '_manifest', None),
        },
    }
    out_json = os.path.join(run_dir, 'summary.json')
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f'[summary] saved {out_json}')

    # ---- 2) 易碎: matplotlib 画图 (subprocess 模式下偶有 0xC00000FF 类
    #         kernel-level crash, 包 try/except + 单独函数让进程独立挂掉
    #         也不影响 summary.json 落盘) ----
    try:
        steps = [r['step'] for r in h_off]
        fig, axes = plt.subplots(2, 3, figsize=(15, 8))
        for ax, (k, lab) in zip(axes.flat, metrics_to_plot):
            off = [r[k] for r in h_off]
            on  = [r[k] for r in h_on]
            ax.plot(steps, off, label='graph-off', color='#888', linewidth=1.5)
            ax.plot(steps, on,  label='graph-on',  color='#d62728', linewidth=1.5)
            ax.axvline(args.outage_step, color='#666', linestyle=':', alpha=0.5)
            ax.set_title(lab, fontsize=11)
            ax.set_xlabel('step')
            ax.grid(True, alpha=0.3)
            ax.legend(fontsize=9)
        fig.suptitle(
            f'T15: {args.city}/{args.district} | '
            f'N={args.n_residents} seed={args.seed}'
            + (f' | tag={args.tag}' if args.tag else ''),
            fontsize=12,
        )
        plt.tight_layout()
        out = os.path.join(run_dir, 'comparison.png')
        fig.savefig(out, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close(fig)
        print(f'\n[plot] saved {out}')
    except Exception as ex:
        print(f'[plot] WARN: {type(ex).__name__}: {ex} (summary.json 已落盘, 不影响数据)')

    return summary


# =============================================================================
# main
# =============================================================================
def _parse_args():
    p = argparse.ArgumentParser(
        description='T15 graph-on vs graph-off 对照实验 harness (M4 F1 跨城市用)')
    p.add_argument('--city',          default=DEFAULT_CITY,
                   help=f'城市名 (默认: {DEFAULT_CITY})')
    p.add_argument('--district',      default=DEFAULT_DISTRICT,
                   help=f'区县名 (默认: {DEFAULT_DISTRICT})')
    p.add_argument('--n-residents',   type=int, default=DEFAULT_N_RESIDENTS,
                   dest='n_residents',
                   help=f'居民数 (默认: {DEFAULT_N_RESIDENTS})')
    p.add_argument('--n-enterprises', type=int, default=DEFAULT_N_ENT,
                   dest='n_enterprises',
                   help=f'企业数 (默认: {DEFAULT_N_ENT})')
    p.add_argument('--total-steps',   type=int, default=DEFAULT_TOTAL_STEPS,
                   dest='total_steps',
                   help=f'仿真总步数 (默认: {DEFAULT_TOTAL_STEPS}, DT=0.25h)')
    p.add_argument('--outage-step',   type=int, default=DEFAULT_OUTAGE_STEP,
                   dest='outage_step',
                   help=f'停电触发步 (默认: {DEFAULT_OUTAGE_STEP})')
    p.add_argument('--outage-cause',  default='equipment_failure',
                   dest='outage_cause',
                   choices=['equipment_failure', 'overload', 'external_damage',
                            'natural_disaster', 'typhoon', 'missile_attack',
                            'war_damage', 'planned_outage'],
                   help='停电原因: 决定 base_damage/repair_difficulty/'
                        'detection_delay, 从而决定修复时长 '
                        '(config.LoadPriorityConfig.OUTAGE_CAUSES; '
                        '默认: equipment_failure = 原硬编码行为)')
    p.add_argument('--damage-level',  type=float, default=None,
                   dest='damage_level',
                   help='自定义损坏程度 0-100, 覆盖 cause 的 base_damage (可选)')
    p.add_argument('--seed',          type=int, default=DEFAULT_SEED,
                   help=f'随机种子 (默认: {DEFAULT_SEED})')
    p.add_argument('--tag',           default='',
                   help='实验标签, 会拼到输出目录末尾 (e.g. baseline, uniform_home)')
    p.add_argument('--output-base',   default=None, dest='output_base',
                   help='输出根目录, 默认 trace_output/。可指定 M4 子组如 '
                        'M4_F4_multi_seed 让结果直接落子文件夹, 省去手动 mv')
    p.add_argument('--allow-overwrite', action='store_true', dest='allow_overwrite',
                   help='允许写入已有 run_dir；默认参数不一致时拒绝覆盖，防止验证数据被静默改写')
    p.add_argument('--home-distribution', default=None, dest='home_distribution',
                   choices=['poi', 'uniform'],
                   help='F2: 居民 home 分布策略 (poi 默认 / uniform 去 POI bias)')
    p.add_argument('--flee-threshold', type=float, default=None, dest='flee_threshold',
                   help='F5: SwitchParams.flee_threshold 覆盖值 (默认 0.6, 扫 {0.4..0.8} 验证 phase transition)')
    p.add_argument('--use-mml', action='store_true', dest='use_mml',
                   help='F13: 显式确认 MML (2026-06-28 起 SwitchParams 默认就开, 此 flag 现为 no-op, 留作向后兼容)')
    p.add_argument('--no-mml',  action='store_true', dest='no_mml',
                   help='supplementary: 强制 sigmoid legacy fallback (use_mml=False), 用于复现 §5 supplementary Tables S1-S3')
    p.add_argument('--switch-ablation', default='none', dest='switch_ablation',
                   choices=sorted(SWITCH_ABLATION_OVERRIDES.keys()),
                   help='E2: SwitchParams 消融预设 (none/no_info_network/no_inertia/no_hysteresis/...)')
    p.add_argument('--opinion-mode', default='auto', dest='opinion_mode',
                   choices=['auto', 'on', 'off'],
                   help='文献验证: 仅控制事件5舆情管理(auto/on/off), 不启用 GovernmentAgent manual events')
    p.add_argument('--outage-stress-profile', default='sqrt', dest='outage_stress_profile',
                   choices=['sqrt', 'log', 'linear'],
                   help='文献验证: t_outage→internal stress 敏感性曲线, 默认 sqrt 保持基线')
    p.add_argument('--mml-scale', type=float, default=None, dest='mml_scale',
                   help='F13 sensitivity: override SwitchParams.mml_scale for this run')
    p.add_argument('--mml-asc-flee', type=float, default=None, dest='mml_asc_flee',
                   help='F13 sensitivity: override SwitchParams.mml_asc_flee for this run')
    p.add_argument('--mml-b-sigma-flee', type=float, default=None, dest='mml_b_sigma_flee',
                   help='F13 sensitivity: override SwitchParams.mml_b_sigma_flee for this run')
    p.add_argument('--mml-b-vis', type=float, default=None, dest='mml_b_vis',
                   help='F13 sensitivity: override SwitchParams.mml_b_vis for this run')
    return p.parse_args()


def main():
    args = _parse_args()

    suffix = f'_{args.tag}' if args.tag else ''
    # 输出基目录: 默认 TRACE_ROOT, --output-base 可指定到 M4_Fx_xxx/ 子组
    if args.output_base:
        base = (args.output_base if os.path.isabs(args.output_base)
                else os.path.join(TRACE_ROOT, args.output_base))
    else:
        base = TRACE_ROOT
    run_dir = os.path.join(base, f't15_{args.city}_{args.district}{suffix}')
    _guard_run_dir(run_dir, args)
    os.makedirs(run_dir, exist_ok=True)
    print(f'[output] → {run_dir}')

    h_off, sim_off = run_one('off', use_road_graph=False, args=args, run_dir=run_dir)
    h_on,  sim_on  = run_one('on',  use_road_graph=True,  args=args, run_dir=run_dir)
    summary = plot_compare(
        h_off, h_on, args=args, run_dir=run_dir,
        sim_off=sim_off, sim_on=sim_on,
    )

    print('\n' + '=' * 70)
    print(f'  T15 对照实验摘要: {args.city}/{args.district}'
          + (f' [tag={args.tag}]' if args.tag else ''))
    print(f'  opinion_mode={args.opinion_mode}, '
          f'outage_stress_profile={args.outage_stress_profile}')
    print('=' * 70)
    print(f'  {"指标":<24} {"graph-off":>14} {"graph-on":>14}  Δ%')
    keys = [
        'avg_stress', 'max_stress', 'pct_stress_gt_06',
        'herd_ratio', 'flee_ratio', 'avg_edge_congestion',
    ]
    for k in keys:
        off, on = h_off[-1][k], h_on[-1][k]
        d = ((on - off) / off * 100) if abs(off) > 1e-9 else 0.0
        print(f'  end {k:<20} {off:>14.4f} {on:>14.4f}  {d:+.1f}%')
    pk_off = max(r['max_stress'] for r in h_off)
    pk_on  = max(r['max_stress'] for r in h_on)
    print(f'  peak max_stress         {pk_off:>14.4f} {pk_on:>14.4f}')
    pk_off = max(r['flee_ratio'] for r in h_off)
    pk_on  = max(r['flee_ratio'] for r in h_on)
    print(f'  peak flee_ratio         {pk_off:>14.4f} {pk_on:>14.4f}')


if __name__ == '__main__':
    main()
