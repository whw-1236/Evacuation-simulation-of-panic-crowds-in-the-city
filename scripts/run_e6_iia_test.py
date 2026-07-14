# -*- coding: utf-8 -*-
"""E6.1b — Direct IIA test for §5.1.3 (revision-package A, step 1).

Design (matches manuscript §5.1.3 / Table 5.1b):
  - graph-on only; flee stays AVAILABLE throughout (VIS=1 wherever a routed
    shelter path exists). We never remove flee from the choice set.
  - Sweep the flee alternative-specific constant alpha_flee (SwitchParams
    field `mml_asc_flee`) over {-7,-6,-5,-4,-3}; all other coefficients at
    Table-2 defaults.
  - For each (city, alpha, seed): run the standard M4 protocol (N=800,
    120 steps, outage @16, seeds 42–51) and record, over the final
    --tail-steps steps, population-mean choice shares P_k from
    agent._goal_shares on the sub-population for which ALL FOUR
    alternatives are simultaneously available (Eq. 10a availability:
    hoard -> _target_store set; herd -> current_leader set;
    flee -> nearest_shelter_node set).
  - Odds ratios (Eq. 27): O_home,hoard / O_home,herd / O_hoard,herd.
    Primary estimator = ratio of tail-mean shares (package spec);
    secondary = tail-mean of individual ln-odds (per-agent IIA object).
  - Per seed: OLS slope of ln O vs alpha_flee. Across seeds: mean ± 95% CI
    (t-based). H0: slope = 0. Also reports the avg_stress-vs-alpha slope as
    the feedback diagnostic (distinguishes choice-kernel drift from
    sigma-distribution drift).

Outputs (under
trace_output/IJDRR_v7_strict_formal/E6_IIA_alpha_flee_n10/
psychology_<semantics>/):
  <city>_<district>/asc{a}_seed{s}/tail_shares.json     per-run capture
  iia_odds_long.csv                                     tidy odds table
  iia_slopes.csv                                        Table 5.1b source
  iia_lnO_vs_alpha.png                                  3-city figure
  verdict.txt                                           版本1/版本2 suggestion

Usage:
    python scripts/run_e6_iia_test.py                       # full 3×5×10
    python scripts/run_e6_iia_test.py --seeds 42 43 44      # quick pass
    python scripts/run_e6_iia_test.py --alphas -6 -5 -4 --tail-steps 10
    python scripts/run_e6_iia_test.py --output-base E6_IIA_strict_v1
    python scripts/run_e6_iia_test.py --aggregate-only      # re-aggregate

Resume-friendly: compatible runs whose tail_shares.json already exists are
skipped unless --force is given.  Missing or stale provenance fields cause a
hard refusal rather than silent reuse.
"""
import os
import sys
import csv
import json
import time
import math
import argparse
import random
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

from scipy import stats as sstats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config.city_manager import CityManager
from config.config import Config
from simulation.simulation import BlackoutSimulation
from scripts.run_ablation import (
    METRIC_SCHEMA_VERSION,
    MODEL_CONTRACT_VERSION,
    _apply_switch_overrides,
    _config_sha256,
    _git_info,
)

TRACE_ROOT = os.path.join(ROOT, 'trace_output')
MAP_DIR = os.path.join(ROOT, 'simulation map data')
DEFAULT_OUTPUT_BASE = os.path.join(
    'IJDRR_v7_strict_formal', 'E6_IIA_alpha_flee_n10'
)
CACHE_SCHEMA_VERSION = 2

CITIES = [
    ('厦门市', '思明区'),
    ('沈阳市', '沈河区'),
    ('北京市', '东城区'),
]
PAIRS = [('home', 'hoard'), ('home', 'herd'), ('hoard', 'herd')]
ACTIONS = ('home', 'hoard', 'herd', 'flee')


def _run_config(city, district, alpha_flee, seed, args):
    """Canonical model configuration used for cache identity checks."""
    return {
        'city': city,
        'district': district,
        'alpha_flee': float(alpha_flee),
        'seed': int(seed),
        'psychology_semantics': str(args.psychology_semantics),
        'n_residents': int(args.n_residents),
        'n_enterprises': int(args.n_enterprises),
        'total_steps': int(args.total_steps),
        'dt_hours': float(getattr(Config().simulation, 'DT', 0.25)),
        'outage_step': int(args.outage_step),
        'outage_mode': 'full',
        'outage_cause': str(args.outage_cause),
        'damage_level': (
            None if args.damage_level is None else float(args.damage_level)
        ),
        'outage_api': 'trigger_district_outage',
        'tail_steps': int(args.tail_steps),
        'use_road_graph': True,
        'use_mml': True,
        'mml_overrides': {
            'use_mml': True,
            'mml_asc_flee': float(alpha_flee),
        },
        'availability_subsample': 'all_four_alternatives_available',
    }


def _sweep_config(args, cities):
    return {
        'psychology_semantics': str(args.psychology_semantics),
        'cities': [
            {'city': city, 'district': district} for city, district in cities
        ],
        'alphas': [float(value) for value in args.alphas],
        'seeds': [int(value) for value in args.seeds],
        'n_residents': int(args.n_residents),
        'n_enterprises': int(args.n_enterprises),
        'total_steps': int(args.total_steps),
        'dt_hours': float(getattr(Config().simulation, 'DT', 0.25)),
        'outage_step': int(args.outage_step),
        'outage_mode': 'full',
        'outage_cause': str(args.outage_cause),
        'damage_level': (
            None if args.damage_level is None else float(args.damage_level)
        ),
        'outage_api': 'trigger_district_outage',
        'tail_steps': int(args.tail_steps),
        'use_road_graph': True,
        'use_mml': True,
        'swept_parameter': 'mml_asc_flee',
        'availability_subsample': 'all_four_alternatives_available',
    }


def _metadata_mismatches(expected, observed, prefix=''):
    """List missing or unequal expected fields recursively."""
    if isinstance(expected, dict):
        if not isinstance(observed, dict):
            return [f'{prefix or "<root>"}: expected mapping']
        mismatches = []
        for key, value in expected.items():
            path = f'{prefix}.{key}' if prefix else str(key)
            if key not in observed:
                mismatches.append(f'{path}: missing')
            else:
                mismatches.extend(
                    _metadata_mismatches(value, observed[key], path)
                )
        return mismatches
    if observed != expected:
        return [f'{prefix}: cached={observed!r}, requested={expected!r}']
    return []


def _validate_cached_record(record, expected_config, expected_git):
    """Reject stale/legacy caches instead of silently pooling them."""
    expected = {
        'cache_schema_version': CACHE_SCHEMA_VERSION,
        'model_contract_version': MODEL_CONTRACT_VERSION,
        'metric_schema_version': METRIC_SCHEMA_VERSION,
        'psychology_semantics': expected_config['psychology_semantics'],
        'run_config': expected_config,
        'run_config_sha256': _config_sha256(expected_config),
        'switch_override_audit': {
            'label': 'E6.1b',
            'requested_overrides': {
                'use_mml': True,
                'mml_asc_flee': expected_config['alpha_flee']
            },
        },
        'git': expected_git,
        'city': expected_config['city'],
        'district': expected_config['district'],
        'alpha_flee': expected_config['alpha_flee'],
        'seed': expected_config['seed'],
    }
    mismatches = _metadata_mismatches(expected, record)
    if mismatches:
        detail = '; '.join(mismatches[:12])
        if len(mismatches) > 12:
            detail += f'; ... {len(mismatches) - 12} more'
        raise ValueError(
            'Refusing incompatible IIA cache; rerun with --force. ' + detail
        )


def _validate_sweep_request(cities, seeds, alphas):
    if not cities:
        raise ValueError('No supported cities selected.')
    if len(seeds) < 2:
        raise ValueError('At least two unique seeds are required for inference.')
    if len(seeds) != len(set(int(value) for value in seeds)):
        raise ValueError('Seeds must be unique.')
    numeric_alphas = [float(value) for value in alphas]
    if not all(np.isfinite(value) for value in numeric_alphas):
        raise ValueError('Alpha values must be finite.')
    if len(numeric_alphas) < 2:
        raise ValueError('At least two alpha values are required for a slope.')
    if len(numeric_alphas) != len(set(numeric_alphas)):
        raise ValueError('Alpha values must be unique.')


def _validate_complete_alpha_grid(records, cities, seeds, alphas):
    """Require exactly one observation for every city x seed x alpha cell."""
    expected = {
        (city, district, int(seed), float(alpha))
        for city, district in cities
        for seed in seeds
        for alpha in alphas
    }
    counts = {}
    for record in records:
        try:
            key = (
                record['city'], record['district'], int(record['seed']),
                float(record['alpha_flee']),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('IIA record lacks a valid city/seed/alpha identity.') from exc
        counts[key] = counts.get(key, 0) + 1
    duplicates = sorted(key for key, count in counts.items() if count != 1)
    observed = set(counts)
    missing = sorted(expected - observed)
    extras = sorted(observed - expected)
    if missing or duplicates or extras:
        raise ValueError(
            'Incomplete or non-unique city x seed x alpha grid: '
            f'missing={missing[:8]!r}, duplicates={duplicates[:8]!r}, '
            f'extras={extras[:8]!r}'
        )


def _write_sweep_manifest(out_dir, args, cities, git_info, status, record_count):
    config = _sweep_config(args, cities)
    manifest = {
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'status': status,
        'model_contract_version': MODEL_CONTRACT_VERSION,
        'metric_schema_version': METRIC_SCHEMA_VERSION,
        'cache_schema_version': CACHE_SCHEMA_VERSION,
        'psychology_semantics': str(args.psychology_semantics),
        'configuration': config,
        'expected_run_count': (
            len(cities) * len(args.alphas) * len(args.seeds)
        ),
        'observed_run_count': int(record_count),
        'git': git_info,
    }
    manifest['config_sha256'] = _config_sha256(config)
    path = os.path.join(out_dir, 'manifest.json')
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    print(f'[manifest] {path} ({status})')
    return manifest


def _guard_sweep_manifest(out_dir, args, cities, git_info):
    path = os.path.join(out_dir, 'manifest.json')
    if not os.path.exists(path) or args.force:
        return
    try:
        with open(path, encoding='utf-8') as handle:
            observed = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f'Refusing unreadable IIA manifest {path}; use --force to replace it.'
        ) from exc
    config = _sweep_config(args, cities)
    expected = {
        'model_contract_version': MODEL_CONTRACT_VERSION,
        'metric_schema_version': METRIC_SCHEMA_VERSION,
        'cache_schema_version': CACHE_SCHEMA_VERSION,
        'psychology_semantics': str(args.psychology_semantics),
        'configuration': config,
        'config_sha256': _config_sha256(config),
        'git': git_info,
    }
    mismatches = _metadata_mismatches(expected, observed)
    if mismatches:
        raise ValueError(
            'Refusing to overwrite an incompatible IIA manifest; use a new '
            f'--output-base or --force. {"; ".join(mismatches[:12])}'
        )


# ---------------------------------------------------------------------------
# single run with tail capture
# ---------------------------------------------------------------------------
def run_one_iia(city, district, alpha_flee, seed, args):
    random.seed(seed)
    np.random.seed(seed)

    cm = CityManager(map_data_dir=MAP_DIR)
    sm_path = cm.get_district_geojson(city, district, use_no_mountain=True)
    if not sm_path:
        raise RuntimeError(f'未找到 {city}/{district} GeoJSON (MAP_DIR={MAP_DIR})')

    city_config = {
        'city': city,
        'geojson_paths': [sm_path],
        'districts': [district],
        'use_road_graph': True,            # flee available throughout
    }
    cfg = Config()
    cfg.simulation.N_RESIDENTS = args.n_residents
    cfg.simulation.N_ENTERPRISES = args.n_enterprises
    cfg.simulation.TOTAL_STEPS = args.total_steps
    cfg.simulation.PSYCHOLOGY_SEMANTICS = args.psychology_semantics

    sim = BlackoutSimulation(config=cfg, city_config=city_config)
    run_config = _run_config(city, district, alpha_flee, seed, args)
    if str(getattr(sim, 'psychology_semantics', '')) != args.psychology_semantics:
        raise RuntimeError(
            'Simulation psychology semantics does not match the requested IIA mode.'
        )
    if not math.isclose(float(sim.dt), run_config['dt_hours'], rel_tol=0.0, abs_tol=1e-12):
        raise RuntimeError(
            f'Runtime dt={sim.dt!r} does not match recorded dt={run_config["dt_hours"]!r}.'
        )

    # E6.1b intervention: only the flee ASC moves; use_mml stays at default True.
    override_audit = _apply_switch_overrides(
        sim, {'use_mml': True, 'mml_asc_flee': float(alpha_flee)}, 'E6.1b'
    )
    holders = int(override_audit.get('holders', 0))
    applied_counts = override_audit.get('applied_counts', {})
    missing_counts = override_audit.get('missing_counts', {})
    incomplete = {
        name: {
            'applied': int(applied_counts.get(name, 0)),
            'missing': int(missing_counts.get(name, 0)),
        }
        for name in ('use_mml', 'mml_asc_flee')
        if (
            int(applied_counts.get(name, 0)) != holders
            or int(missing_counts.get(name, 0)) != 0
        )
    }
    if holders <= 0 or incomplete:
        raise RuntimeError(
            f'Incomplete IIA choice-model override: holders={holders}, '
            f'fields={incomplete!r}'
        )

    tail_from = args.total_steps - args.tail_steps
    # accumulators over (tail steps × agents)
    sum_P = {a: 0.0 for a in ACTIONS}          # all-four-available subsample
    sum_lnO = {p: 0.0 for p in PAIRS}          # per-agent ln odds, same subsample
    n_sub = 0
    sum_P_all = {a: 0.0 for a in ACTIONS}      # whole population (context)
    n_all = 0
    sum_sigma = 0.0
    n_sigma = 0
    sub_frac_steps = []

    triggered = False
    t0 = time.time()
    for step in range(args.total_steps):
        sim.step()
        sim.step_count = step + 1
        if step == args.outage_step and not triggered:
            try:
                sim.trigger_district_outage(
                    mode='full', cause=args.outage_cause,
                    damage_level=args.damage_level,
                )
                triggered = True
            except Exception as ex:
                raise RuntimeError(
                    f'Outage trigger failed for {city}/{district}, '
                    f'alpha={alpha_flee}, seed={seed}'
                ) from ex
        if step < tail_from:
            continue
        # ---- tail capture ----
        step_sub = 0
        for r in sim.residents:
            shares = getattr(r, '_goal_shares', None)
            if not shares or len(shares) != 4:
                continue
            Ph, Po, Pe, Pf = (float(x) for x in shares)
            n_all += 1
            for a, v in zip(ACTIONS, (Ph, Po, Pe, Pf)):
                sum_P_all[a] += v
            sum_sigma += float(getattr(r, 'stress_level', 0.0))
            n_sigma += 1
            # availability of ALL FOUR alternatives this step (Eq. 10a)
            if getattr(r, '_target_store', None) is None:
                continue
            if getattr(r, 'current_leader', None) is None:
                continue
            if getattr(r, 'nearest_shelter_node', None) is None:
                continue
            if min(Ph, Po, Pe) <= 0.0:
                continue
            n_sub += 1
            step_sub += 1
            P = {'home': Ph, 'hoard': Po, 'herd': Pe, 'flee': Pf}
            for a in ACTIONS:
                sum_P[a] += P[a]
            for pa, pb in PAIRS:
                sum_lnO[(pa, pb)] += math.log(P[pa] / P[pb])
        sub_frac_steps.append(step_sub / max(1, len(sim.residents)))
    secs = time.time() - t0

    if n_sub == 0:
        raise RuntimeError(
            f'{city}/{district} asc={alpha_flee} seed={seed}: '
            f'all-four-available subsample is empty in the tail window; '
            f'increase --tail-steps or inspect availability gates.')

    mean_P = {a: sum_P[a] / n_sub for a in ACTIONS}
    rec = {
        'cache_schema_version': CACHE_SCHEMA_VERSION,
        'model_contract_version': MODEL_CONTRACT_VERSION,
        'metric_schema_version': METRIC_SCHEMA_VERSION,
        'psychology_semantics': args.psychology_semantics,
        'run_config': run_config,
        'run_config_sha256': _config_sha256(run_config),
        'switch_override_audit': override_audit,
        'git': args._git_info,
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'city': city, 'district': district,
        'alpha_flee': float(alpha_flee), 'seed': int(seed),
        'tail_steps': int(args.tail_steps),
        'n_sub_agentsteps': int(n_sub),
        'n_all_agentsteps': int(n_all),
        'sub_fraction_mean': float(np.mean(sub_frac_steps)),
        'avg_stress_tail': sum_sigma / max(1, n_sigma),
        'mean_P_sub': mean_P,
        'mean_P_all': {a: sum_P_all[a] / max(1, n_all) for a in ACTIONS},
        # primary estimator: ln of ratio-of-means (package spec)
        'lnO_ratio_of_means': {
            f'{pa}_{pb}': math.log(mean_P[pa] / mean_P[pb]) for pa, pb in PAIRS
        },
        # secondary estimator: mean of per-agent ln odds
        'lnO_mean_log_odds': {
            f'{pa}_{pb}': sum_lnO[(pa, pb)] / n_sub for pa, pb in PAIRS
        },
        'sim_seconds': round(secs, 1),
    }
    return rec


# ---------------------------------------------------------------------------
# aggregation → slopes, CSVs, figure, verdict
# ---------------------------------------------------------------------------
def _slope(x, y):
    x = np.asarray(x, float); y = np.asarray(y, float)
    if len(x) < 2:
        return float('nan')
    return float(np.polyfit(x, y, 1)[0])


def _mean_ci(vals):
    v = np.asarray([x for x in vals if np.isfinite(x)], float)
    n = len(v)
    if n == 0:
        return (float('nan'),) * 4
    m = float(v.mean())
    if n == 1:
        return m, float('nan'), float('nan'), 1
    sd = float(v.std(ddof=1))
    half = float(sstats.t.ppf(0.975, n - 1) * sd / math.sqrt(n))
    return m, m - half, m + half, n


def _one_sample_slope_p(vals):
    values = np.asarray([value for value in vals if np.isfinite(value)], float)
    if len(values) < 2:
        return float('nan')
    if np.allclose(values, values[0], rtol=0.0, atol=1e-15):
        return 1.0 if abs(float(values[0])) <= 1e-15 else 0.0
    return float(sstats.ttest_1samp(values, popmean=0.0).pvalue)


def _holm_adjust(p_values):
    """Holm step-down adjusted p-values, preserving NaNs."""
    adjusted = [float('nan')] * len(p_values)
    finite = sorted(
        ((float(p), index) for index, p in enumerate(p_values) if np.isfinite(p)),
        key=lambda item: item[0],
    )
    family_size = len(finite)
    running_max = 0.0
    for rank, (p_value, index) in enumerate(finite):
        candidate = min(1.0, (family_size - rank) * p_value)
        running_max = max(running_max, candidate)
        adjusted[index] = running_max
    return adjusted


def aggregate(records, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    semantics = {record.get('psychology_semantics') for record in records}
    contracts = {record.get('model_contract_version') for record in records}
    metric_schemas = {record.get('metric_schema_version') for record in records}
    git_fingerprints = {
        (record.get('git') or {}).get('worktree_fingerprint_sha256')
        for record in records
    }
    if semantics != {records[0]['psychology_semantics']} or len(semantics) != 1:
        raise ValueError(f'Mixed psychology semantics in IIA records: {semantics!r}')
    if contracts != {MODEL_CONTRACT_VERSION}:
        raise ValueError(f'Mixed or stale model contracts in IIA records: {contracts!r}')
    if metric_schemas != {METRIC_SCHEMA_VERSION}:
        raise ValueError(f'Mixed or stale metric schemas in IIA records: {metric_schemas!r}')
    if len(git_fingerprints) != 1 or None in git_fingerprints:
        raise ValueError('IIA records were produced from different or unknown worktrees.')
    evidence_git = records[0]['git']
    # ---- tidy long table ----
    long_path = os.path.join(out_dir, 'iia_odds_long.csv')
    with open(long_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['model_contract_version', 'metric_schema_version',
                    'psychology_semantics', 'run_config_sha256',
                    'git_commit', 'git_dirty',
                    'git_worktree_fingerprint_sha256', 'city', 'district',
                    'alpha_flee', 'seed', 'estimator',
                    'pair', 'lnO', 'avg_stress_tail', 'n_sub_agentsteps',
                    'sub_fraction_mean', 'P_flee_sub'])
        for r in records:
            for est_key, est in (('lnO_ratio_of_means', 'ratio_of_means'),
                                 ('lnO_mean_log_odds', 'mean_log_odds')):
                for pa, pb in PAIRS:
                    w.writerow([r['model_contract_version'],
                                r['metric_schema_version'],
                                r['psychology_semantics'],
                                r['run_config_sha256'],
                                r['git'].get('commit'),
                                r['git'].get('dirty'),
                                r['git'].get('worktree_fingerprint_sha256'),
                                r['city'], r['district'], r['alpha_flee'],
                                r['seed'], est, f'{pa}/{pb}',
                                f"{r[est_key][f'{pa}_{pb}']:.6f}",
                                f"{r['avg_stress_tail']:.4f}",
                                r['n_sub_agentsteps'],
                                f"{r['sub_fraction_mean']:.4f}",
                                f"{r['mean_P_sub']['flee']:.4f}"])
    print(f'[agg] {long_path}')

    # ---- per-seed slopes → mean ± 95% CI (Table 5.1b source) ----
    by = {}
    for r in records:
        by.setdefault((r['city'], r['district'], r['seed']), []).append(r)

    rows = []
    citykeys = sorted({(r['city'], r['district']) for r in records},
                      key=lambda cd: [c for c, _ in CITIES].index(cd[0])
                      if cd[0] in [c for c, _ in CITIES] else 99)
    for (city, district) in citykeys:
        seeds = sorted({s for (c, d, s) in by if (c, d) == (city, district)})
        for est_key, est in (('lnO_ratio_of_means', 'ratio_of_means'),
                             ('lnO_mean_log_odds', 'mean_log_odds')):
            for pa, pb in PAIRS:
                slopes = []
                for s in seeds:
                    runs = sorted(by[(city, district, s)],
                                  key=lambda r: r['alpha_flee'])
                    xs = [r['alpha_flee'] for r in runs]
                    ys = [r[est_key][f'{pa}_{pb}'] for r in runs]
                    slopes.append(_slope(xs, ys))
                m, lo, hi, n = _mean_ci(slopes)
                sig = np.isfinite(lo) and (lo > 0 or hi < 0)
                rows.append({
                    'model_contract_version': MODEL_CONTRACT_VERSION,
                    'metric_schema_version': METRIC_SCHEMA_VERSION,
                    'psychology_semantics': records[0]['psychology_semantics'],
                    'git_commit': evidence_git.get('commit'),
                    'git_dirty': evidence_git.get('dirty'),
                    'git_worktree_fingerprint_sha256': evidence_git.get(
                        'worktree_fingerprint_sha256'
                    ),
                    'city': city,
                    'district': district,
                    'estimator': est,
                    'pair': f'{pa}/{pb}',
                    'n_seeds': n,
                    'slope_mean': m,
                    'ci95_lo': lo,
                    'ci95_hi': hi,
                    'ci_excludes_zero': 'yes' if sig else 'no',
                    'p_value': _one_sample_slope_p(slopes),
                    'multiplicity_family': 'all_reported_slope_tests',
                })
        # feedback diagnostic: avg_stress slope
        s_slopes = []
        for s in seeds:
            runs = sorted(by[(city, district, s)], key=lambda r: r['alpha_flee'])
            s_slopes.append(_slope([r['alpha_flee'] for r in runs],
                                   [r['avg_stress_tail'] for r in runs]))
        m, lo, hi, n = _mean_ci(s_slopes)
        rows.append({
            'model_contract_version': MODEL_CONTRACT_VERSION,
            'metric_schema_version': METRIC_SCHEMA_VERSION,
            'psychology_semantics': records[0]['psychology_semantics'],
            'git_commit': evidence_git.get('commit'),
            'git_dirty': evidence_git.get('dirty'),
            'git_worktree_fingerprint_sha256': evidence_git.get(
                'worktree_fingerprint_sha256'
            ),
            'city': city,
            'district': district,
            'estimator': 'feedback_diagnostic',
            'pair': 'avg_stress',
            'n_seeds': n,
            'slope_mean': m,
            'ci95_lo': lo,
            'ci95_hi': hi,
            'ci_excludes_zero': (
                'yes' if (np.isfinite(lo) and (lo > 0 or hi < 0)) else 'no'
            ),
            'p_value': _one_sample_slope_p(s_slopes),
            'multiplicity_family': 'all_reported_slope_tests',
        })

    adjusted = _holm_adjust([row['p_value'] for row in rows])
    for row, adjusted_p in zip(rows, adjusted):
        row['p_holm'] = adjusted_p
        row['holm_reject_0_05'] = (
            'yes' if np.isfinite(adjusted_p) and adjusted_p < 0.05 else 'no'
        )

    slope_path = os.path.join(out_dir, 'iia_slopes.csv')
    with open(slope_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f'[agg] {slope_path}')

    # ---- verdict ----
    primary_rows = [
        row for row in rows if row['estimator'] == 'ratio_of_means'
    ]
    n_holm = sum(row['holm_reject_0_05'] == 'yes' for row in primary_rows)
    n_ci = sum(row['ci_excludes_zero'] == 'yes' for row in primary_rows)
    lines = ['E6.1b verdict (primary estimator = ratio_of_means, odds pairs only)',
             f'  city×pair cells with CI excluding zero: {n_ci} / {len(primary_rows)}']
    lines.append(
        f'  city x pair cells significant after Holm adjustment: '
        f'{n_holm} / {len(primary_rows)}'
    )
    if n_holm == 0:
        lines.append(
            '  The tested grid does not reject local odds-ratio invariance '
            'after Holm adjustment; this is not proof of global IIA.'
        )
    else:
        lines.append(
            '  Holm-adjusted evidence indicates odds-ratio drift; qualify '
            'the manuscript IIA claim and report the affected cells.'
        )
        for row in primary_rows:
            if row['holm_reject_0_05'] == 'yes':
                lines.append(
                    f"    drift: {row['city']} {row['pair']}: "
                    f"slope={row['slope_mean']:.4f} "
                    f"[{row['ci95_lo']:.4f}, {row['ci95_hi']:.4f}], "
                    f"Holm p={row['p_holm']:.4g}"
                )
    lines.append('  同步核对 Abstract / §5.5 / §6.2 / §7 的 IIA 措辞。')
    verdict = '\n'.join(lines)
    with open(os.path.join(out_dir, 'verdict.txt'), 'w', encoding='utf-8') as f:
        f.write(verdict + '\n')
    print('\n' + verdict + '\n')

    # ---- figure: lnO vs alpha, 3 pairs × 3 cities (primary estimator) ----
    fig, axes = plt.subplots(1, len(citykeys),
                             figsize=(4.2 * len(citykeys), 3.6),
                             sharey=True, squeeze=False)
    colors = {'home/hoard': 'tab:blue', 'home/herd': 'tab:orange',
              'hoard/herd': 'tab:green'}
    for ax, (city, district) in zip(axes[0], citykeys):
        seeds = sorted({s for (c, d, s) in by if (c, d) == (city, district)})
        for pa, pb in PAIRS:
            pair = f'{pa}/{pb}'
            alphas = sorted({r['alpha_flee'] for r in records
                             if (r['city'], r['district']) == (city, district)})
            means, los, his = [], [], []
            for a in alphas:
                vals = [r['lnO_ratio_of_means'][f'{pa}_{pb}']
                        for r in records
                        if (r['city'], r['district'], r['alpha_flee']) ==
                           (city, district, a)]
                m, lo, hi, _ = _mean_ci(vals)
                means.append(m); los.append(lo); his.append(hi)
            means = np.array(means); los = np.array(los); his = np.array(his)
            ax.plot(alphas, means, 'o-', color=colors[pair], label=pair, ms=4)
            if np.all(np.isfinite(los)):
                ax.fill_between(alphas, los, his, color=colors[pair], alpha=0.15)
        ax.axhline(0, color='grey', lw=0.6, ls=':')
        ax.set_title(f'{city} {district}\n(n={len(seeds)} seeds)', fontsize=10)
        ax.set_xlabel(r'$\alpha_{\mathrm{flee}}$')
    axes[0][0].set_ylabel(r'$\ln O$ (tail mean, all-four-available)')
    axes[0][0].legend(fontsize=8)
    fig.suptitle('E6.1b — pairwise odds among {home, hoard, herd} vs flee ASC',
                 fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig_path = os.path.join(out_dir, 'iia_lnO_vs_alpha.png')
    fig.savefig(fig_path, dpi=200)
    plt.close(fig)
    print(f'[agg] {fig_path}')


# ---------------------------------------------------------------------------
def _parse_args():
    p = argparse.ArgumentParser(description='E6.1b direct IIA test (§5.1.3)')
    p.add_argument('--alphas', type=float, nargs='+',
                   default=[-7, -6, -5, -4, -3])
    p.add_argument('--seeds', type=int, nargs='+', default=list(range(42, 52)))
    p.add_argument('--cities', nargs='+', default=None,
                   help="子集,如: --cities 厦门市 沈阳市")
    p.add_argument('--n-residents', type=int, default=800)
    p.add_argument('--n-enterprises', type=int, default=30)
    p.add_argument('--total-steps', type=int, default=120)
    p.add_argument('--outage-step', type=int, default=16)
    p.add_argument('--outage-cause', default='equipment_failure',
                   choices=['equipment_failure', 'overload', 'external_damage',
                            'natural_disaster', 'typhoon', 'missile_attack',
                            'war_damage', 'planned_outage'])
    p.add_argument('--damage-level', type=float, default=None)
    p.add_argument('--psychology-semantics', choices=['strict', 'legacy'],
                   default='strict')
    p.add_argument('--output-base', default=DEFAULT_OUTPUT_BASE,
                   help='Absolute path or a directory relative to trace_output.')
    p.add_argument('--tail-steps', type=int, default=10,
                   help='末尾统计窗口(步), 默认最后10步=2.5h')
    p.add_argument('--force', action='store_true', help='重跑已存在的 run')
    p.add_argument('--aggregate-only', action='store_true',
                   help='只从已有 tail_shares.json 重新聚合')
    return p.parse_args()


def main():
    args = _parse_args()
    cities = CITIES if not args.cities else [
        (c, d) for (c, d) in CITIES if c in set(args.cities)]
    _validate_sweep_request(cities, args.seeds, args.alphas)
    if args.tail_steps <= 0 or args.tail_steps > args.total_steps:
        raise ValueError('--tail-steps must be in [1, total_steps].')
    if args.outage_step < 0 or args.outage_step >= args.total_steps:
        raise ValueError('--outage-step must be in [0, total_steps).')

    output_root = (
        args.output_base if os.path.isabs(args.output_base)
        else os.path.join(TRACE_ROOT, args.output_base)
    )
    base_dir = os.path.join(
        output_root, f'psychology_{args.psychology_semantics}'
    )
    os.makedirs(base_dir, exist_ok=True)
    args._git_info = _git_info()
    if not args._git_info.get('commit') or not args._git_info.get(
        'worktree_fingerprint_sha256'
    ):
        raise RuntimeError('A readable git commit and worktree fingerprint are required.')
    _guard_sweep_manifest(base_dir, args, cities, args._git_info)
    _write_sweep_manifest(
        base_dir, args, cities, args._git_info, status='planned', record_count=0
    )

    records = []
    todo = [(c, d, a, s) for (c, d) in cities
            for a in args.alphas for s in args.seeds]
    print(f'[plan] {len(todo)} runs '
          f'({len(cities)} cities × {len(args.alphas)} alphas × '
          f'{len(args.seeds)} seeds), tail={args.tail_steps} steps')

    for i, (city, district, a, s) in enumerate(todo, 1):
        run_dir = os.path.join(base_dir, f'{city}_{district}',
                               f'asc{a:g}_seed{s}')
        jpath = os.path.join(run_dir, 'tail_shares.json')
        if os.path.exists(jpath) and not args.force:
            with open(jpath, encoding='utf-8') as f:
                cached = json.load(f)
            expected_config = _run_config(city, district, a, s, args)
            _validate_cached_record(cached, expected_config, args._git_info)
            records.append(cached)
            print(f'[{i}/{len(todo)}] skip (exists) {city}/{district} '
                  f'asc={a:g} seed={s}')
            continue
        if args.aggregate_only:
            continue
        print(f'\n[{i}/{len(todo)}] {city}/{district} asc={a:g} seed={s}')
        rec = run_one_iia(city, district, a, s, args)
        os.makedirs(run_dir, exist_ok=True)
        with open(jpath, 'w', encoding='utf-8') as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
        print(f'    lnO(h/hd)={rec["lnO_ratio_of_means"]["home_hoard"]:+.3f} '
              f'lnO(h/he)={rec["lnO_ratio_of_means"]["home_herd"]:+.3f} '
              f'lnO(hd/he)={rec["lnO_ratio_of_means"]["hoard_herd"]:+.3f} '
              f'P_flee={rec["mean_P_sub"]["flee"]:.3f} '
              f'σ̄={rec["avg_stress_tail"]:.3f} '
              f'({rec["sim_seconds"]}s)')
        records.append(rec)

    if not records:
        raise ValueError(
            'No compatible IIA records found; run the complete sweep first.'
        )
    _validate_complete_alpha_grid(records, cities, args.seeds, args.alphas)
    aggregate(records, base_dir)
    _write_sweep_manifest(
        base_dir, args, cities, args._git_info,
        status='complete', record_count=len(records),
    )


if __name__ == '__main__':
    main()
