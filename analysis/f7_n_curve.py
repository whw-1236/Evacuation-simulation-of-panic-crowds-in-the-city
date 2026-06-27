# -*- coding: utf-8 -*-
"""F7 后处理: cascade 强度 vs N 居民数的 log-log 曲线。

输入: trace_output/M4_F7_N_scan/t15_<城>_<区>_N{N}/summary.json
输出:
  - trace_output/M4_F7_N_scan/n_curve.png (三城三条曲线, log-log)
  - trace_output/M4_F7_N_scan/n_curve.csv

调用:
    python analysis/f7_n_curve.py
"""
import os
import sys
import glob
import json
import re
import csv
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
F7_DIR = os.path.join(ROOT, 'trace_output',
                      'M4_MML_F7_N_scan' if _USE_MML else 'M4_F7_N_scan')

# 关注: cascade 强度 = (on - off) / off, 看 N 大时差距怎么放大
METRICS = [
    ('herd_ratio',       'herd ratio'),
    ('flee_ratio',       'flee ratio'),
    ('pct_stress_gt_06', '高压人群%'),
    ('avg_stress',       '平均 σ'),
]


def parse_N_from_tag(tag):
    """tag = 'N0800' -> 800"""
    m = re.match(r'N(\d+)', tag or '')
    return int(m.group(1)) if m else None


def load_summaries(f7_dir):
    """读所有 t15_*/summary.json -> {(city, district): [{N, off, on, delta} ...]}."""
    by_city = defaultdict(list)
    for path in sorted(glob.glob(os.path.join(f7_dir, 't15_*', 'summary.json'))):
        with open(path, 'r', encoding='utf-8') as f:
            summary = json.load(f)
        cfg = summary.get('config', {})
        final = summary.get('final', {})
        N = parse_N_from_tag(cfg.get('tag')) or cfg.get('n_residents')
        if N is None:
            continue
        city = cfg.get('city')
        district = cfg.get('district')
        rec = {'N': N}
        for k, _ in METRICS:
            off = final.get(k, {}).get('off')
            on  = final.get(k, {}).get('on')
            rec[f'{k}_off'] = off
            rec[f'{k}_on']  = on
            rec[f'{k}_delta'] = (on - off) if (off is not None and on is not None) else None
            rec[f'{k}_delta_pct'] = (
                (on - off) / off * 100 if (off is not None and on is not None and abs(off) > 1e-9)
                else 0.0
            )
        by_city[(city, district)].append(rec)
    for key in by_city:
        by_city[key].sort(key=lambda r: r['N'])
    return dict(by_city)


def save_csv(by_city, out_path):
    rows = []
    for (city, district), recs in by_city.items():
        for r in recs:
            row = {'city': city, 'district': district, **r}
            rows.append(row)
    if not rows:
        return
    fields = list(rows[0].keys())
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f'[csv] saved {out_path}')


def plot_curves(by_city, out_path):
    """4 子图, 每个 metric 三城三条曲线 (log-log)."""
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    colors = {'厦门市': '#d62728', '沈阳市': '#1f77b4', '北京市': '#2ca02c'}

    for ax, (k, lab) in zip(axes.flat, METRICS):
        for (city, district), recs in by_city.items():
            N_arr = np.array([r['N'] for r in recs])
            on_arr = np.array([r.get(f'{k}_on') or 0.0 for r in recs])
            off_arr = np.array([r.get(f'{k}_off') or 0.0 for r in recs])
            color = colors.get(city, '#888')
            ax.plot(N_arr, on_arr, '-o', color=color, label=f'{city}{district} (on)',
                    linewidth=1.5, markersize=6)
            ax.plot(N_arr, off_arr, '--s', color=color, alpha=0.5,
                    label=f'{city}{district} (off)', linewidth=1, markersize=4)
        ax.set_xscale('log')
        ax.set_xlabel('N (居民数, log)')
        ax.set_ylabel(lab)
        ax.set_title(f'{lab} vs N')
        ax.grid(True, alpha=0.3, which='both')
        ax.legend(fontsize=8, loc='best')

    fig.suptitle('F7: cascade 强度 vs N 居民数 (三城对照, seed=42)', fontsize=13)
    plt.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'[plot] saved {out_path}')


def main():
    if not os.path.exists(F7_DIR):
        raise SystemExit(f'F7 目录不存在: {F7_DIR}')

    by_city = load_summaries(F7_DIR)
    n_files = sum(len(v) for v in by_city.values())
    print(f'[load] {n_files} summary.json from {F7_DIR}')
    if not by_city:
        raise SystemExit('未发现任何 summary.json, 是否 F7 还没跑?')

    save_csv(by_city, os.path.join(F7_DIR, 'n_curve.csv'))
    plot_curves(by_city, os.path.join(F7_DIR, 'n_curve.png'))

    # 找 N* (cascade 开始可见的 N)
    print('\n[N* 临界点估算]')
    for (city, district), recs in by_city.items():
        print(f'  {city}{district}:')
        for r in recs:
            dp = r.get('herd_ratio_delta_pct', 0.0)
            mark = '⭐' if abs(dp) >= 5 else '  '
            print(f'    {mark} N={r["N"]:>5}: herd Δ% = {dp:+6.1f}%, '
                  f'off={r.get("herd_ratio_off") or 0:.3f} '
                  f'on={r.get("herd_ratio_on") or 0:.3f}')


if __name__ == '__main__':
    main()
