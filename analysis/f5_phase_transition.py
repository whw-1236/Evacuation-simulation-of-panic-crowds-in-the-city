# -*- coding: utf-8 -*-
"""F5 后处理: cascade 指标 vs θ_flee 阈值 (phase transition 曲线)。

输入: trace_output/M4_F5_theta_flee/t15_<城>_<区>_theta{X}/summary.json
输出:
  - trace_output/M4_F5_theta_flee/theta_curve.csv
  - trace_output/M4_F5_theta_flee/theta_curve.png  (三城 × 4 指标 vs θ)

判读:
  - 预期 flee_ratio_on 应随 θ 增大单调下降 (门槛变高 → 触发的 agent 变少)
  - herd_ratio 应随 θ 增大略增 (本应 flee 的 agent 留在 herd 态)
  - pct_stress_gt_06 几乎不变 (θ 只切换行为不改 stress 演化)

调用:
    python analysis/f5_phase_transition.py
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


F5_DIR = os.path.join(ROOT, 'trace_output', 'M4_F5_theta_flee')

METRICS = [
    ('flee_ratio',       'flee ratio (向 shelter 逃)'),
    ('herd_ratio',       'herd ratio'),
    ('pct_stress_gt_06', '高压人群% (σ>0.6)'),
    ('avg_stress',       '平均 σ'),
]


def parse_theta_from_tag(tag):
    """tag = 'theta0.6' -> 0.6"""
    m = re.match(r'theta([\d.]+)', tag or '')
    return float(m.group(1)) if m else None


def load_summaries(f5_dir):
    """读所有 t15_*/summary.json -> {(city, district): [{theta, off, on, delta} ...]}."""
    by_city = defaultdict(list)
    for path in sorted(glob.glob(os.path.join(f5_dir, 't15_*', 'summary.json'))):
        with open(path, 'r', encoding='utf-8') as f:
            summary = json.load(f)
        cfg = summary.get('config', {})
        final = summary.get('final', {})
        theta = (cfg.get('flee_threshold')
                 if cfg.get('flee_threshold') is not None
                 else parse_theta_from_tag(cfg.get('tag')))
        if theta is None:
            continue
        city = cfg.get('city')
        district = cfg.get('district')
        rec = {'theta': float(theta)}
        for k, _ in METRICS:
            off = final.get(k, {}).get('off')
            on = final.get(k, {}).get('on')
            rec[f'{k}_off'] = off
            rec[f'{k}_on'] = on
            rec[f'{k}_delta'] = (on - off) if (off is not None and on is not None) else None
            rec[f'{k}_delta_pct'] = (
                (on - off) / off * 100 if (off is not None and on is not None and abs(off) > 1e-9)
                else 0.0
            )
        by_city[(city, district)].append(rec)
    for key in by_city:
        by_city[key].sort(key=lambda r: r['theta'])
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
    """2x2 子图, 每个 metric 三城三条曲线 (off 虚线 / on 实线)."""
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    colors = {'厦门市': '#d62728', '沈阳市': '#1f77b4', '北京市': '#2ca02c'}

    for ax, (k, lab) in zip(axes.flat, METRICS):
        for (city, district), recs in by_city.items():
            th_arr = np.array([r['theta'] for r in recs])
            on_arr = np.array([r.get(f'{k}_on') or 0.0 for r in recs])
            off_arr = np.array([r.get(f'{k}_off') or 0.0 for r in recs])
            color = colors.get(city, '#888')
            ax.plot(th_arr, on_arr, '-o', color=color,
                    label=f'{city}{district} (on)',
                    linewidth=1.8, markersize=7)
            ax.plot(th_arr, off_arr, '--s', color=color, alpha=0.45,
                    label=f'{city}{district} (off)',
                    linewidth=1.2, markersize=5)
        ax.axvline(0.6, color='gray', linestyle=':', alpha=0.5,
                   label='default θ=0.6' if ax is axes.flat[0] else None)
        ax.set_xlabel('θ_flee (flee 触发阈值)')
        ax.set_ylabel(lab)
        ax.set_title(f'{lab} vs θ_flee')
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8, loc='best')

    fig.suptitle('F5: phase transition — cascade 指标 vs θ_flee (三城对照, seed=42, N=800)',
                 fontsize=13)
    plt.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'[plot] saved {out_path}')


def main():
    if not os.path.exists(F5_DIR):
        raise SystemExit(f'F5 目录不存在: {F5_DIR}')

    by_city = load_summaries(F5_DIR)
    n_files = sum(len(v) for v in by_city.values())
    print(f'[load] {n_files} summary.json from {F5_DIR}')
    if not by_city:
        raise SystemExit('未发现任何 summary.json, 是否 F5 还没跑?')

    save_csv(by_city, os.path.join(F5_DIR, 'theta_curve.csv'))
    plot_curves(by_city, os.path.join(F5_DIR, 'theta_curve.png'))

    # phase transition 检视: flee_on 随 θ 变化的单调性
    print('\n[phase transition flee_on(θ)]')
    for (city, district), recs in by_city.items():
        print(f'  {city}{district}:')
        flee_seq = [(r['theta'], r.get('flee_ratio_on') or 0.0) for r in recs]
        for th, v in flee_seq:
            print(f'    θ={th:.2f}: flee_on={v:.3f}')
        # 简单单调性判定
        vals = [v for _, v in flee_seq]
        mono_dec = all(vals[i] >= vals[i+1] - 1e-6 for i in range(len(vals)-1))
        print(f'    单调下降? {mono_dec}')


if __name__ == '__main__':
    main()
