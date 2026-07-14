# -*- coding: utf-8 -*-
"""F4 多 seed 后处理: 三城每组指标的 mean ± 95% CI 表 + error-bar 曲线。

输入: trace_output/IJDRR_v7_strict_formal/F4_multi_seed_n10/psychology_<semantics>/t15_*/summary.json
输出:
  - <input>/aggregate_ci.csv (machine-readable)
  - <input>/aggregate_ci.json
  - <input>/errorbar.png (三城 × 4 指标 对照图)
  - terminal print 人类可读 CI 表

调用:
    python analysis/f4_aggregate.py
"""
import argparse
import os
import sys
import glob
import json
import csv
import math
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import numpy as np
from scipy.stats import t as student_t
import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False
import matplotlib.pyplot as plt


_USE_MML = os.environ.get('BLACKOUT_USE_MML', '1') != '0'   # MML default since 2026-06-28; set '0' for sigmoid legacy supplementary
F4_BASE = os.path.join(
    ROOT,
    'trace_output',
    'IJDRR_v7_strict_formal',
    'F4_multi_seed_n10' if _USE_MML else 'F4_multi_seed_n10_sigmoid',
)
EXPECTED_MODEL_CONTRACT_VERSION = 'ijdrr_strict_v1'
MIN_METRIC_SCHEMA_VERSION = 4

# 关注的指标: 论文里要进 §5.1 cascade 主表的
METRICS = [
    ('herd_ratio',       'herd ratio'),
    ('flee_ratio',       'flee ratio'),
    ('pct_stress_gt_06', 'high-stress share (sigma>0.6)'),
    ('avg_stress',       'mean stress'),
]

CITY_LABELS = {
    '北京市': 'Beijing',
    '厦门市': 'Xiamen',
    '沈阳市': 'Shenyang',
}

DISTRICT_LABELS = {
    '东城区': 'Dongcheng',
    '思明区': 'Siming',
    '沈河区': 'Shenhe',
}


def place_label(city, district, n_seeds):
    city_label = CITY_LABELS.get(city, city)
    district_label = DISTRICT_LABELS.get(district, district)
    return f"{city_label}\n{district_label}\n(n={n_seeds})"


def semantics_dir(base, semantics):
    leaf = f'psychology_{semantics}'
    return base if os.path.basename(os.path.normpath(base)) == leaf else os.path.join(base, leaf)


def validate_summary_semantics(summary, expected, path):
    if summary.get('model_contract_version') != EXPECTED_MODEL_CONTRACT_VERSION:
        raise ValueError(f'summary model_contract_version mismatch: {path}')
    try:
        schema_version = int(summary.get('metric_schema_version'))
    except (TypeError, ValueError):
        schema_version = -1
    if schema_version < MIN_METRIC_SCHEMA_VERSION:
        raise ValueError(f'summary metric_schema_version is too old: {path}')
    actual = summary.get('config', {}).get('psychology_semantics')
    if actual != expected:
        raise ValueError(
            f'summary psychology_semantics mismatch: expected={expected!r}, '
            f'actual={actual!r}, path={path}'
        )
    manifests = summary.get('manifest')
    if not isinstance(manifests, dict):
        raise ValueError(f'summary manifest missing: {path}')
    for graph_mode in ('off', 'on'):
        manifest = manifests.get(graph_mode)
        actual = manifest.get('psychology_semantics') if isinstance(manifest, dict) else None
        if actual != expected:
            raise ValueError(
                f'{graph_mode} manifest psychology_semantics mismatch: '
                f'expected={expected!r}, actual={actual!r}, path={path}'
            )
        if manifest.get('model_contract_version') != EXPECTED_MODEL_CONTRACT_VERSION:
            raise ValueError(
                f'{graph_mode} manifest model_contract_version mismatch: {path}'
            )
        try:
            manifest_schema = int(manifest.get('metric_schema_version'))
        except (TypeError, ValueError):
            manifest_schema = -1
        if manifest_schema < MIN_METRIC_SCHEMA_VERSION:
            raise ValueError(
                f'{graph_mode} manifest metric_schema_version is too old: {path}'
            )


def load_summaries(f4_dir, psychology_semantics='strict'):
    """读所有 t15_*/summary.json -> records list."""
    records = []
    for path in sorted(glob.glob(os.path.join(f4_dir, 't15_*', 'summary.json'))):
        with open(path, 'r', encoding='utf-8') as f:
            summary = json.load(f)
        validate_summary_semantics(summary, psychology_semantics, path)
        cfg = summary.get('config', {})
        final = summary.get('final', {})
        rec = {
            'city':         cfg.get('city'),
            'district':     cfg.get('district'),
            'seed':         cfg.get('seed'),
            'home_distribution': cfg.get('home_distribution', 'poi'),
            'psychology_semantics': psychology_semantics,
        }
        for k, _ in METRICS:
            rec[f'{k}_off'] = final.get(k, {}).get('off')
            rec[f'{k}_on']  = final.get(k, {}).get('on')
        records.append(rec)
    return records


def ci95(values):
    """95% CI 用 t-distribution. n=10 时 t_{0.025, 9} ≈ 2.262."""
    arr = np.array([v for v in values if v is not None], dtype=float)
    if len(arr) < 2:
        return (float(arr.mean()) if len(arr) else 0.0, 0.0, 0.0, 0.0)
    mean = arr.mean()
    std  = arr.std(ddof=1)
    # Formal n=10 evidence uses the exact two-sided Student-t critical value.
    tval = float(student_t.ppf(0.975, len(arr) - 1))
    half = tval * std / math.sqrt(len(arr))
    return mean, std, mean - half, mean + half


def build_paired_seed_records(records):
    """Return one auditable graph-on/off pair per seed and metric."""
    paired = []
    seen = set()
    for rec in sorted(
        records,
        key=lambda item: (str(item['city']), str(item['district']), int(item['seed'])),
    ):
        pair_key = (rec['city'], rec['district'], int(rec['seed']))
        if pair_key in seen:
            raise ValueError(
                f'duplicate seed pair for {rec["city"]}/{rec["district"]}: '
                f'{rec["seed"]}'
            )
        seen.add(pair_key)
        for metric, _label in METRICS:
            off = rec.get(f'{metric}_off')
            on = rec.get(f'{metric}_on')
            if off is None or on is None:
                raise ValueError(
                    f'incomplete graph pair for {pair_key}, metric={metric}: '
                    f'off={off!r}, on={on!r}'
                )
            off = float(off)
            on = float(on)
            if not np.isfinite(off) or not np.isfinite(on):
                raise ValueError(
                    f'non-finite graph pair for {pair_key}, metric={metric}: '
                    f'off={off!r}, on={on!r}'
                )
            paired.append({
                'city': rec['city'],
                'district': rec['district'],
                'seed': int(rec['seed']),
                'home_distribution': rec.get('home_distribution', 'poi'),
                'psychology_semantics': rec['psychology_semantics'],
                'metric': metric,
                'graph_off': off,
                'graph_on': on,
                'paired_delta_on_minus_off': on - off,
                'seedwise_delta_pct': (
                    100.0 * (on - off) / off if abs(off) > 1e-9 else None
                ),
            })
    return paired


def aggregate(records):
    """group by (city, district) -> 每组 4 指标 × {off, on} 的 CI."""
    groups = defaultdict(list)
    for r in records:
        groups[(r['city'], r['district'])].append(r)

    table = []
    for (city, district), recs in sorted(groups.items()):
        seeds = [int(rec['seed']) for rec in recs]
        if len(seeds) != len(set(seeds)):
            raise ValueError(f'duplicate seeds for {city}/{district}: {seeds}')
        semantics = {rec.get('psychology_semantics') for rec in recs}
        if len(semantics) != 1:
            raise ValueError(
                f'mixed psychology semantics for {city}/{district}: {sorted(semantics)}'
            )
        n = len(seeds)
        row = {
            'city': city,
            'district': district,
            'n_seeds': n,
            'psychology_semantics': recs[0]['psychology_semantics'],
        }
        for k, _ in METRICS:
            for rec in recs:
                for mode in ('off', 'on'):
                    value = rec.get(f'{k}_{mode}')
                    if value is None or not np.isfinite(float(value)):
                        raise ValueError(
                            f'incomplete/non-finite graph pair for {city}/{district}, '
                            f'seed={rec["seed"]}, metric={k}, mode={mode}: {value!r}'
                        )
            for mode in ('off', 'on'):
                vals = [float(r[f'{k}_{mode}']) for r in recs]
                mean, std, lo, hi = ci95(vals)
                row[f'{k}_{mode}_mean'] = mean
                row[f'{k}_{mode}_std']  = std
                row[f'{k}_{mode}_lo95'] = lo
                row[f'{k}_{mode}_hi95'] = hi
            # delta%
            off_mean = row[f'{k}_off_mean']
            on_mean  = row[f'{k}_on_mean']
            if abs(off_mean) > 1e-9:
                row[f'{k}_delta_pct'] = (on_mean - off_mean) / off_mean * 100
            elif abs(on_mean) > 1e-9:
                row[f'{k}_delta_pct'] = None
            else:
                row[f'{k}_delta_pct'] = 0.0
            paired_delta = [
                float(rec[f'{k}_on']) - float(rec[f'{k}_off'])
                for rec in recs
            ]
            d_mean, d_std, d_lo, d_hi = ci95(paired_delta)
            row[f'{k}_paired_delta_mean'] = d_mean
            row[f'{k}_paired_delta_std'] = d_std
            row[f'{k}_paired_delta_lo95'] = d_lo
            row[f'{k}_paired_delta_hi95'] = d_hi
            row[f'{k}_paired_delta_n'] = len(paired_delta)
            row[f'{k}_paired_delta_ci_excludes_zero'] = bool(
                d_lo > 0.0 or d_hi < 0.0
            ) if len(paired_delta) >= 2 else False
            paired_relative = [
                100.0
                * (float(rec[f'{k}_on']) - float(rec[f'{k}_off']))
                / float(rec[f'{k}_off'])
                for rec in recs
                if abs(float(rec[f'{k}_off'])) > 1e-9
            ]
            if paired_relative:
                q_mean, q_std, q_lo, q_hi = ci95(paired_relative)
                row[f'{k}_seedwise_delta_pct_mean'] = q_mean
                row[f'{k}_seedwise_delta_pct_std'] = q_std
                row[f'{k}_seedwise_delta_pct_lo95'] = q_lo
                row[f'{k}_seedwise_delta_pct_hi95'] = q_hi
                row[f'{k}_seedwise_delta_pct_n'] = len(paired_relative)
            else:
                row[f'{k}_seedwise_delta_pct_mean'] = None
                row[f'{k}_seedwise_delta_pct_std'] = None
                row[f'{k}_seedwise_delta_pct_lo95'] = None
                row[f'{k}_seedwise_delta_pct_hi95'] = None
                row[f'{k}_seedwise_delta_pct_n'] = 0
        table.append(row)
    return table


def print_table(table):
    """人类可读的 CI 表 to terminal."""
    print('\n' + '=' * 90)
    print('F4 多 seed 95% CI 汇总')
    print('=' * 90)
    for row in table:
        print(f"\n{row['city']}/{row['district']} (n_seeds={row['n_seeds']})")
        print(
            f"  {'指标':<22} {'graph-off':>22}  {'graph-on':>22} "
            f"{'paired delta [95% CI]':>40}"
        )
        for k, lab in METRICS:
            off_m = row[f'{k}_off_mean']
            off_lo, off_hi = row[f'{k}_off_lo95'], row[f'{k}_off_hi95']
            on_m  = row[f'{k}_on_mean']
            on_lo, on_hi   = row[f'{k}_on_lo95'], row[f'{k}_on_hi95']
            d_mean = row[f'{k}_paired_delta_mean']
            d_lo = row[f'{k}_paired_delta_lo95']
            d_hi = row[f'{k}_paired_delta_hi95']
            evidence = (
                'different'
                if row[f'{k}_paired_delta_ci_excludes_zero']
                else 'inconclusive'
            )
            print(f"  {lab:<22} "
                  f"{off_m:>8.4f}±({off_lo:.4f},{off_hi:.4f}) "
                  f"{on_m:>8.4f}±({on_lo:.4f},{on_hi:.4f}) "
                  f"{d_mean:+.4f} [{d_lo:+.4f}, {d_hi:+.4f}] {evidence}")


def save_csv(table, out_path):
    """落 CSV 给后续脚本/Excel 用."""
    if not table:
        return
    fields = list(table[0].keys())
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(table)
    print(f'\n[csv] saved {out_path}')


def save_json(table, out_path):
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(table, f, ensure_ascii=False, indent=2)
    print(f'[json] saved {out_path}')


def plot_errorbar(table, out_path):
    """每个 metric 一个子图, x 轴三城, error-bar 标 95% CI, off vs on 对比."""
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    cities = [place_label(r['city'], r['district'], r['n_seeds']) for r in table]
    x = np.arange(len(cities))
    width = 0.35

    for ax, (k, lab) in zip(axes.flat, METRICS):
        off_m = np.array([r[f'{k}_off_mean'] for r in table])
        on_m  = np.array([r[f'{k}_on_mean']  for r in table])
        off_err = np.array([[r[f'{k}_off_mean'] - r[f'{k}_off_lo95'] for r in table],
                            [r[f'{k}_off_hi95'] - r[f'{k}_off_mean'] for r in table]])
        on_err  = np.array([[r[f'{k}_on_mean']  - r[f'{k}_on_lo95']  for r in table],
                            [r[f'{k}_on_hi95']  - r[f'{k}_on_mean']  for r in table]])
        ax.bar(x - width/2, off_m, width, yerr=off_err, label='graph-off',
               color='#888', capsize=4, error_kw={'lw': 1, 'capthick': 1})
        ax.bar(x + width/2, on_m,  width, yerr=on_err,  label='graph-on',
               color='#d62728', capsize=4, error_kw={'lw': 1, 'capthick': 1})

        zero_y = max(np.max(off_m), np.max(on_m), 1e-6) * 0.025
        for xpos, value in zip(x - width/2, off_m):
            if np.isclose(value, 0.0):
                ax.scatter([xpos], [0], marker='_', s=240, color='#666666',
                           linewidths=2.0, clip_on=False, zorder=5)
                ax.text(xpos, zero_y, '0', ha='center', va='bottom',
                        fontsize=8, color='#666666')
        for xpos, value in zip(x + width/2, on_m):
            if np.isclose(value, 0.0):
                ax.scatter([xpos], [0], marker='_', s=240, color='#d62728',
                           linewidths=2.0, clip_on=False, zorder=5)
                ax.text(xpos, zero_y, '0', ha='center', va='bottom',
                        fontsize=8, color='#d62728')
        for i, r in enumerate(table):
            dp = r[f'{k}_delta_pct']
            if abs(off_m[i]) <= 1e-9 and on_m[i] > 1e-9:
                label = f'0->{on_m[i]:.2f}'
                label_color = '#1f77b4'
            else:
                label = f'{dp:+.1f}%'
                label_color = '#d62728' if dp > 0 else '#1f77b4'
            ax.text(x[i], max(off_m[i], on_m[i]) * 1.05,
                    label, ha='center', fontsize=9, color=label_color)
        ax.set_xticks(x)
        ax.set_xticklabels(cities, fontsize=9)
        ax.set_title(lab, fontsize=11)
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3, axis='y')

    fig.suptitle('Three-city multi-seed 95% CI (graph-off vs graph-on)', fontsize=13)
    plt.tight_layout()
    fig.savefig(out_path, dpi=300, bbox_inches='tight', facecolor='white')
    base, _ = os.path.splitext(out_path)
    for ext in ('.pdf', '.svg'):
        fig.savefig(base + ext, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'[plot] saved {out_path}')


def parse_args():
    parser = argparse.ArgumentParser(description='Aggregate F4 multi-seed outputs.')
    parser.add_argument('--input-base', default=F4_BASE)
    parser.add_argument(
        '--psychology-semantics',
        choices=('strict', 'legacy'),
        default='strict',
        help='Only aggregate runs produced under this psychology contract.',
    )
    return parser.parse_args()


def main():
    args = parse_args()
    input_base = (
        args.input_base if os.path.isabs(args.input_base)
        else os.path.join(ROOT, 'trace_output', args.input_base)
    )
    f4_dir = semantics_dir(input_base, args.psychology_semantics)
    if not os.path.exists(f4_dir):
        raise SystemExit(f'F4 input directory does not exist: {f4_dir}')

    records = load_summaries(f4_dir, args.psychology_semantics)
    print(f'[load] {len(records)} summary.json from {f4_dir}')
    if not records:
        raise SystemExit('未发现任何 summary.json, 是否 F4 还没跑?')

    table = aggregate(records)
    print_table(table)

    save_csv(table, os.path.join(f4_dir, 'aggregate_ci.csv'))
    save_json(table, os.path.join(f4_dir, 'aggregate_ci.json'))
    paired_records = build_paired_seed_records(records)
    save_csv(paired_records, os.path.join(f4_dir, 'paired_seed_records.csv'))
    plot_errorbar(table, os.path.join(f4_dir, 'errorbar.png'))

    # 给论文 §5.1 直接用的总结句
    print('\n' + '=' * 90)
    print('[paper §5.1 一句话总结]')
    for row in table:
        k = 'herd_ratio'
        off_m, on_m = row[f'{k}_off_mean'], row[f'{k}_on_mean']
        off_lo, off_hi = row[f'{k}_off_lo95'], row[f'{k}_off_hi95']
        on_lo, on_hi = row[f'{k}_on_lo95'], row[f'{k}_on_hi95']
        d_mean = row[f'{k}_paired_delta_mean']
        d_lo = row[f'{k}_paired_delta_lo95']
        d_hi = row[f'{k}_paired_delta_hi95']
        evidence = (
            'CI excludes zero'
            if row[f'{k}_paired_delta_ci_excludes_zero']
            else 'CI includes zero; no directional effect claim'
        )
        print(f"  {row['city']}/{row['district']}: herd_ratio "
              f"{off_m:.3f} [{off_lo:.3f}, {off_hi:.3f}] → "
              f"{on_m:.3f} [{on_lo:.3f}, {on_hi:.3f}] "
              f"(paired on-off delta {d_mean:+.3f} "
              f"[{d_lo:+.3f}, {d_hi:+.3f}], {evidence}, "
              f"n={row['n_seeds']})")
    print('=' * 90)


if __name__ == '__main__':
    main()
