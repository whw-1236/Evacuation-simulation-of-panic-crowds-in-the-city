# -*- coding: utf-8 -*-
"""F4 多 seed 后处理: 三城每组指标的 mean ± 95% CI 表 + error-bar 曲线。

输入: trace_output/M4_F4_multi_seed/t15_*/summary.json
输出:
  - trace_output/M4_F4_multi_seed/aggregate_ci.csv (machine-readable)
  - trace_output/M4_F4_multi_seed/aggregate_ci.json
  - trace_output/M4_F4_multi_seed/errorbar.png (三城 × 4 指标 对照图)
  - terminal print 人类可读 CI 表

调用:
    python analysis/f4_aggregate.py
"""
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
import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False
import matplotlib.pyplot as plt


_USE_MML = os.environ.get('BLACKOUT_USE_MML', '0') == '1'
F4_DIR = os.path.join(ROOT, 'trace_output',
                      'M4_MML_F4_multi_seed' if _USE_MML else 'M4_F4_multi_seed')

# 关注的指标: 论文里要进 §5.1 cascade 主表的
METRICS = [
    ('herd_ratio',       'herd ratio'),
    ('flee_ratio',       'flee ratio'),
    ('pct_stress_gt_06', '高压人群比例 (σ>0.6)'),
    ('avg_stress',       '平均 σ'),
]


def load_summaries(f4_dir):
    """读所有 t15_*/summary.json -> records list."""
    records = []
    for path in sorted(glob.glob(os.path.join(f4_dir, 't15_*', 'summary.json'))):
        with open(path, 'r', encoding='utf-8') as f:
            summary = json.load(f)
        cfg = summary.get('config', {})
        final = summary.get('final', {})
        rec = {
            'city':         cfg.get('city'),
            'district':     cfg.get('district'),
            'seed':         cfg.get('seed'),
            'home_distribution': cfg.get('home_distribution', 'poi'),
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
    # 用 1.96 近似 (n=10 时 t=2.262, 区间会窄一点; 报告里标注)
    # 这里改用 t-dist 更严谨
    try:
        from scipy.stats import t as student_t
        tval = student_t.ppf(0.975, len(arr) - 1)
    except ImportError:
        tval = 1.96
    half = tval * std / math.sqrt(len(arr))
    return mean, std, mean - half, mean + half


def aggregate(records):
    """group by (city, district) -> 每组 4 指标 × {off, on} 的 CI."""
    groups = defaultdict(list)
    for r in records:
        groups[(r['city'], r['district'])].append(r)

    table = []
    for (city, district), recs in sorted(groups.items()):
        n = len(recs)
        row = {'city': city, 'district': district, 'n_seeds': n}
        for k, _ in METRICS:
            for mode in ('off', 'on'):
                vals = [r[f'{k}_{mode}'] for r in recs]
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
            else:
                row[f'{k}_delta_pct'] = 0.0
        table.append(row)
    return table


def print_table(table):
    """人类可读的 CI 表 to terminal."""
    print('\n' + '=' * 90)
    print('F4 多 seed 95% CI 汇总')
    print('=' * 90)
    for row in table:
        print(f"\n{row['city']}/{row['district']} (n_seeds={row['n_seeds']})")
        print(f"  {'指标':<22} {'graph-off':>22}  {'graph-on':>22}   Δ%")
        for k, lab in METRICS:
            off_m = row[f'{k}_off_mean']
            off_lo, off_hi = row[f'{k}_off_lo95'], row[f'{k}_off_hi95']
            on_m  = row[f'{k}_on_mean']
            on_lo, on_hi   = row[f'{k}_on_lo95'], row[f'{k}_on_hi95']
            dp = row[f'{k}_delta_pct']
            print(f"  {lab:<22} "
                  f"{off_m:>8.4f}±({off_lo:.4f},{off_hi:.4f}) "
                  f"{on_m:>8.4f}±({on_lo:.4f},{on_hi:.4f}) "
                  f"{dp:>+7.1f}%")


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
    cities = [f"{r['city']}\n{r['district']}\n(n={r['n_seeds']})" for r in table]
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
        for i, r in enumerate(table):
            dp = r[f'{k}_delta_pct']
            ax.text(x[i], max(off_m[i], on_m[i]) * 1.05,
                    f'{dp:+.1f}%', ha='center', fontsize=9,
                    color='#d62728' if dp > 0 else '#1f77b4')
        ax.set_xticks(x)
        ax.set_xticklabels(cities, fontsize=9)
        ax.set_title(lab, fontsize=11)
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3, axis='y')

    fig.suptitle('F4: 三城 × 多 seed 95% CI (graph-off vs graph-on)', fontsize=13)
    plt.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'[plot] saved {out_path}')


def main():
    if not os.path.exists(F4_DIR):
        raise SystemExit(f'F4 目录不存在: {F4_DIR}')

    records = load_summaries(F4_DIR)
    print(f'[load] {len(records)} summary.json from {F4_DIR}')
    if not records:
        raise SystemExit('未发现任何 summary.json, 是否 F4 还没跑?')

    table = aggregate(records)
    print_table(table)

    save_csv(table, os.path.join(F4_DIR, 'aggregate_ci.csv'))
    save_json(table, os.path.join(F4_DIR, 'aggregate_ci.json'))
    plot_errorbar(table, os.path.join(F4_DIR, 'errorbar.png'))

    # 给论文 §5.1 直接用的总结句
    print('\n' + '=' * 90)
    print('[paper §5.1 一句话总结]')
    for row in table:
        k = 'herd_ratio'
        off_m, on_m = row[f'{k}_off_mean'], row[f'{k}_on_mean']
        off_lo, off_hi = row[f'{k}_off_lo95'], row[f'{k}_off_hi95']
        on_lo, on_hi = row[f'{k}_on_lo95'], row[f'{k}_on_hi95']
        dp = row[f'{k}_delta_pct']
        print(f"  {row['city']}/{row['district']}: herd_ratio "
              f"{off_m:.3f} [{off_lo:.3f}, {off_hi:.3f}] → "
              f"{on_m:.3f} [{on_lo:.3f}, {on_hi:.3f}] "
              f"({dp:+.1f}%, n={row['n_seeds']})")
    print('=' * 90)


if __name__ == '__main__':
    main()
