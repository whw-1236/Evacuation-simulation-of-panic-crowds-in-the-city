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


# =============================================================================
# 收集每步全局指标 (replicate dashboard._update_history 的关键部分)
# =============================================================================
def _collect_step_metrics(sim):
    residents = sim.residents
    n = max(1, len(residents))
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
    }


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
    print(f'[init] {time.time()-t0:.1f}s, use_road_graph={sim.use_road_graph}')

    history = []
    triggered = False
    t_start = time.time()
    for step in range(args.total_steps):
        sim.step()
        sim.step_count = step + 1
        if step == args.outage_step and not triggered:
            try:
                sim.trigger_outage(mode='full', cause='equipment_failure')
                print(f'[outage] triggered at step {step}')
                triggered = True
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
    csv_path = os.path.join(out_dir, 'global_metrics.csv')
    fields = ['step', 't_hour', 'avg_stress', 'max_stress', 'pct_stress_gt_06',
              'avg_emotion', 'avg_panic',
              'hoard_ratio', 'herd_ratio', 'flee_ratio', 'outage_ratio',
              'avg_edge_congestion', 'pct_on_path']
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for rec in history:
            w.writerow({k: rec.get(k, 0) for k in fields})
    print(f'[trace] saved {csv_path}')

    if sim.use_road_graph:
        edge_path = os.path.join(out_dir, 'edge_observations.csv')
        sim.write_edge_observations(edge_path)
        print(f'[trace] saved {edge_path}')

    return history, sim


# =============================================================================
# 对比 + 画图
# =============================================================================
def plot_compare(h_off, h_on, args, run_dir):
    """先写 summary.json (机器可读, 关键路径), 再画图 (易碎, 兜底)。"""
    metrics_to_plot = [
        ('avg_stress', '平均 σ (stress)'),
        ('max_stress', '最大个体 σ'),
        ('pct_stress_gt_06', '高压人群比例 (σ>0.6)'),
        ('herd_ratio', 'herd ratio'),
        ('flee_ratio', 'flee ratio (向 shelter 逃)'),
        ('avg_edge_congestion', '平均 edge congestion'),
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
            'seed':          args.seed,
            'tag':           args.tag,
            'home_distribution': getattr(args, 'home_distribution', None) or 'poi',
        },
        'final': {
            k: {'off': h_off[-1][k], 'on': h_on[-1][k]}
            for k, _ in metrics_to_plot
        },
        'peak_stress': {
            'off': max(r['avg_stress'] for r in h_off),
            'on':  max(r['avg_stress'] for r in h_on),
        },
        'peak_herd_ratio': {
            'off': max(r['herd_ratio'] for r in h_off),
            'on':  max(r['herd_ratio'] for r in h_on),
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
    p.add_argument('--seed',          type=int, default=DEFAULT_SEED,
                   help=f'随机种子 (默认: {DEFAULT_SEED})')
    p.add_argument('--tag',           default='',
                   help='实验标签, 会拼到输出目录末尾 (e.g. baseline, uniform_home)')
    p.add_argument('--output-base',   default=None, dest='output_base',
                   help='输出根目录, 默认 trace_output/。可指定 M4 子组如 '
                        'M4_F4_multi_seed 让结果直接落子文件夹, 省去手动 mv')
    p.add_argument('--home-distribution', default=None, dest='home_distribution',
                   choices=['poi', 'uniform'],
                   help='F2: 居民 home 分布策略 (poi 默认 / uniform 去 POI bias)')
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
    os.makedirs(run_dir, exist_ok=True)
    print(f'[output] → {run_dir}')

    h_off, sim_off = run_one('off', use_road_graph=False, args=args, run_dir=run_dir)
    h_on,  sim_on  = run_one('on',  use_road_graph=True,  args=args, run_dir=run_dir)
    summary = plot_compare(h_off, h_on, args=args, run_dir=run_dir)

    print('\n' + '=' * 70)
    print(f'  T15 对照实验摘要: {args.city}/{args.district}'
          + (f' [tag={args.tag}]' if args.tag else ''))
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
