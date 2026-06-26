# -*- coding: utf-8 -*-
"""从 graph_off/graph_on 的 global_metrics.csv 重新生成 comparison.png。

背景: subprocess 模式下 run_ablation.py 的 plot_compare 在 Crowds_sim env
       matplotlib 会 0xC00000FF crash, summary.json 已通过 summary-first
       落盘但 comparison.png 丢失。本脚本用 Python 3.12 (matplotlib OK)
       从 csv 重画。

⚠️ 用 Python 3.12 跑 (Crowds_sim env 的 matplotlib 当前损坏):
    "C:/Program Files/Python312/python.exe" analysis/replot_from_csv.py [output-base]

调用:
    python analysis/replot_from_csv.py M4_F4_multi_seed
    python analysis/replot_from_csv.py M4_F7_N_scan
    python analysis/replot_from_csv.py M4_F2_home_dist
"""
import os
import sys
import csv
import json
import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False
import matplotlib.pyplot as plt


METRICS = [
    ('avg_stress',          '平均 σ (stress)'),
    ('max_stress',          '最大个体 σ'),
    ('pct_stress_gt_06',    '高压人群比例 (σ>0.6)'),
    ('herd_ratio',          'herd ratio'),
    ('flee_ratio',          'flee ratio'),
    ('avg_edge_congestion', '平均 edge congestion'),
]


def read_csv(path):
    with open(path, 'r', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def plot_one(run_dir):
    off_csv = os.path.join(run_dir, 'graph_off', 'global_metrics.csv')
    on_csv  = os.path.join(run_dir, 'graph_on',  'global_metrics.csv')
    if not (os.path.exists(off_csv) and os.path.exists(on_csv)):
        return False

    h_off = read_csv(off_csv)
    h_on  = read_csv(on_csv)
    if not h_off or not h_on:
        return False

    # 读 summary.json 拿 title 上下文
    summary_path = os.path.join(run_dir, 'summary.json')
    title_extra = ''
    if os.path.exists(summary_path):
        try:
            with open(summary_path, 'r', encoding='utf-8') as f:
                summary = json.load(f)
            cfg = summary.get('config', {})
            title_extra = (f"{cfg.get('city','?')}/{cfg.get('district','?')} | "
                           f"N={cfg.get('n_residents','?')} seed={cfg.get('seed','?')}"
                           + (f" | {cfg.get('tag')}" if cfg.get('tag') else ''))
        except Exception:
            pass

    steps = [int(r['step']) for r in h_off]
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    for ax, (k, lab) in zip(axes.flat, METRICS):
        off = [float(r.get(k, 0)) for r in h_off]
        on  = [float(r.get(k, 0)) for r in h_on]
        ax.plot(steps, off, label='graph-off', color='#888', linewidth=1.5)
        ax.plot(steps, on,  label='graph-on',  color='#d62728', linewidth=1.5)
        ax.set_title(lab, fontsize=11)
        ax.set_xlabel('step')
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=9)
    fig.suptitle(f'T15 重画: {title_extra}', fontsize=12)
    plt.tight_layout()
    out = os.path.join(run_dir, 'comparison.png')
    fig.savefig(out, dpi=120, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return True


def main():
    output_base = sys.argv[1] if len(sys.argv) > 1 else 'M4_F4_multi_seed'
    base_dir = os.path.join(ROOT, 'trace_output', output_base)
    if not os.path.exists(base_dir):
        raise SystemExit(f'目录不存在: {base_dir}')

    dirs = sorted(glob.glob(os.path.join(base_dir, 't15_*')))
    print(f'找到 {len(dirs)} 个 run_dir')
    done = skipped = 0
    for d in dirs:
        # 如果 comparison.png 已存在跳过
        if os.path.exists(os.path.join(d, 'comparison.png')):
            skipped += 1
            continue
        if plot_one(d):
            done += 1
            print(f'  [ok] {os.path.basename(d)}')
        else:
            print(f'  [skip] {os.path.basename(d)}: csv 缺失')

    print(f'\n重画 {done} 个, skip 已存在 {skipped} 个')


if __name__ == '__main__':
    main()
