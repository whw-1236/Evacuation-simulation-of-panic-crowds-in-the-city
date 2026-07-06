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

Outputs (under trace_output/E6_IIA_alpha_flee/):
  <city>_<district>/asc{a}_seed{s}/tail_shares.json     per-run capture
  iia_odds_long.csv                                     tidy odds table
  iia_slopes.csv                                        Table 5.1b source
  iia_lnO_vs_alpha.png                                  3-city figure
  verdict.txt                                           版本1/版本2 suggestion

Usage:
    python scripts/run_e6_iia_test.py                       # full 3×5×10
    python scripts/run_e6_iia_test.py --seeds 42 43 44      # quick pass
    python scripts/run_e6_iia_test.py --alphas -6 -5 -4 --tail-steps 10
    python scripts/run_e6_iia_test.py --aggregate-only      # re-aggregate

Resume-friendly: runs whose tail_shares.json already exists are skipped
unless --force is given.
"""
import os
import sys
import csv
import json
import time
import math
import argparse
import random
from types import SimpleNamespace

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
from scripts.run_ablation import _apply_switch_overrides  # reuse audit-aware setter

TRACE_ROOT = os.path.join(ROOT, 'trace_output')
MAP_DIR = os.path.join(ROOT, 'simulation map data')
BASE_DIR = os.path.join(TRACE_ROOT, 'E6_IIA_alpha_flee')

CITIES = [
    ('厦门市', '思明区'),
    ('沈阳市', '沈河区'),
    ('北京市', '东城区'),
]
PAIRS = [('home', 'hoard'), ('home', 'herd'), ('hoard', 'herd')]
ACTIONS = ('home', 'hoard', 'herd', 'flee')


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

    sim = BlackoutSimulation(config=cfg, city_config=city_config)

    # E6.1b intervention: only the flee ASC moves; use_mml stays at default True.
    _apply_switch_overrides(sim, {'mml_asc_flee': float(alpha_flee)}, 'E6.1b')

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
                sim.trigger_outage(mode='full', cause='equipment_failure')
                triggered = True
            except Exception as ex:
                print(f'[outage] WARN: {ex}')
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


def aggregate(records, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    # ---- tidy long table ----
    long_path = os.path.join(out_dir, 'iia_odds_long.csv')
    with open(long_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['city', 'district', 'alpha_flee', 'seed', 'estimator',
                    'pair', 'lnO', 'avg_stress_tail', 'n_sub_agentsteps',
                    'sub_fraction_mean', 'P_flee_sub'])
        for r in records:
            for est_key, est in (('lnO_ratio_of_means', 'ratio_of_means'),
                                 ('lnO_mean_log_odds', 'mean_log_odds')):
                for pa, pb in PAIRS:
                    w.writerow([r['city'], r['district'], r['alpha_flee'],
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
    verdicts = []
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
                rows.append([city, district, est, f'{pa}/{pb}',
                             n, f'{m:.5f}', f'{lo:.5f}', f'{hi:.5f}',
                             'yes' if sig else 'no'])
                if est == 'ratio_of_means':
                    verdicts.append(((city, f'{pa}/{pb}'), m, lo, hi, sig))
        # feedback diagnostic: avg_stress slope
        s_slopes = []
        for s in seeds:
            runs = sorted(by[(city, district, s)], key=lambda r: r['alpha_flee'])
            s_slopes.append(_slope([r['alpha_flee'] for r in runs],
                                   [r['avg_stress_tail'] for r in runs]))
        m, lo, hi, n = _mean_ci(s_slopes)
        rows.append([city, district, 'ratio_of_means', 'avg_stress',
                     n, f'{m:.5f}', f'{lo:.5f}', f'{hi:.5f}',
                     'yes' if (np.isfinite(lo) and (lo > 0 or hi < 0)) else 'no'])

    slope_path = os.path.join(out_dir, 'iia_slopes.csv')
    with open(slope_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['city', 'district', 'estimator', 'pair', 'n_seeds',
                    'slope_mean', 'ci95_lo', 'ci95_hi', 'ci_excludes_zero'])
        w.writerows(rows)
    print(f'[agg] {slope_path}')

    # ---- verdict ----
    n_sig = sum(1 for _, _, _, _, sig in verdicts if sig)
    lines = ['E6.1b verdict (primary estimator = ratio_of_means, odds pairs only)',
             f'  city×pair cells with CI excluding zero: {n_sig} / {len(verdicts)}']
    if n_sig == 0:
        lines.append('  → 建议采用 §5.1.3 版本 1(odds ratios invariant; IIA holds)。')
    else:
        lines.append('  → 建议采用 §5.1.3 版本 2(odds ratios drift; '
                     'shared-normalisation substitution with σ-driven heterogeneity)。')
        for (city, pair), m, lo, hi, sig in verdicts:
            if sig:
                lines.append(f'    drift: {city} {pair}: slope={m:.4f} '
                             f'[{lo:.4f}, {hi:.4f}]')
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
    os.makedirs(BASE_DIR, exist_ok=True)

    records = []
    todo = [(c, d, a, s) for (c, d) in cities
            for a in args.alphas for s in args.seeds]
    print(f'[plan] {len(todo)} runs '
          f'({len(cities)} cities × {len(args.alphas)} alphas × '
          f'{len(args.seeds)} seeds), tail={args.tail_steps} steps')

    for i, (city, district, a, s) in enumerate(todo, 1):
        run_dir = os.path.join(BASE_DIR, f'{city}_{district}',
                               f'asc{a:g}_seed{s}')
        jpath = os.path.join(run_dir, 'tail_shares.json')
        if os.path.exists(jpath) and not args.force:
            with open(jpath, encoding='utf-8') as f:
                records.append(json.load(f))
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
        print('[agg] no records found — run the sweep first.')
        return
    aggregate(records, BASE_DIR)


if __name__ == '__main__':
    main()
