# -*- coding: utf-8 -*-
"""T15 对照实验 harness: graph-on vs graph-off 头比较 (headless, 不开 GUI)。

设计:
  - 同样的 seed / N_RESIDENTS / 停电步, 仅 use_road_graph 不同
  - 跑 100 步 (DT=0.25 → 25 仿真小时)
  - 第 20 步触发整区停电
  - 收集 per-step 全局指标 + end-of-run edge 观测
  - 输出 trace_output/t15_graph_{on,off}/ 各一套 CSV
  - 并排画 stress / herd_ratio / 拥堵曲线

调用:
    cmd /c "call D:\\EnvironmentAnaconda\\Scripts\\activate.bat Crowds_sim && python _t15_harness.py"
"""
import os
import sys
import csv
import json
import time
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

from config.city_manager import CityManager
from config.config import Config
from simulation.simulation import BlackoutSimulation


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACE_ROOT = os.path.join(ROOT, 'trace_output')
os.makedirs(TRACE_ROOT, exist_ok=True)


# =============================================================================
# 实验配置
# =============================================================================
N_RESIDENTS  = 800      # 居民数 (压力放大, 让 cascade 显现)
N_ENT        = 30
TOTAL_STEPS  = 120      # 120 步 × DT=0.25h = 30 仿真小时
OUTAGE_STEP  = 16       # 早点触发, 留更多时间形成 cascade
SEED         = 42


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
def run_one(label, use_road_graph):
    print(f'\n{"="*70}\n  Run "{label}" (use_road_graph={use_road_graph})\n{"="*70}')
    random.seed(SEED)
    np.random.seed(SEED)

    # 用 glob 兜底, 应对子目录重组 (e.g. 思明区/思明区map/)
    import glob
    base = os.path.join(ROOT, 'simulation map data', '厦门市', '思明区')
    cands = (
        glob.glob(os.path.join(base, '**', '思明区无山水.geojson'), recursive=True)
        or glob.glob(os.path.join(base, '**', '厦门市_思明区.geojson'), recursive=True)
    )
    if not cands:
        raise RuntimeError(f'未找到思明区 GeoJSON, 搜索基目录 {base}')
    sm_path = cands[0]
    siming_paths = [sm_path]
    print(f'  [city] using {sm_path}')

    city_config = {
        'city': '厦门市',
        'geojson_paths': siming_paths,
        'districts': ['思明区'],
        'use_road_graph': use_road_graph,
    }
    cfg = Config()
    cfg.simulation.N_RESIDENTS = N_RESIDENTS
    cfg.simulation.N_ENTERPRISES = N_ENT
    cfg.simulation.TOTAL_STEPS = TOTAL_STEPS

    t0 = time.time()
    sim = BlackoutSimulation(config=cfg, city_config=city_config)
    print(f'[init] {time.time()-t0:.1f}s, use_road_graph={sim.use_road_graph}')

    history = []
    triggered = False
    t_start = time.time()
    for step in range(TOTAL_STEPS):
        sim.step()
        sim.step_count = step + 1
        if step == OUTAGE_STEP and not triggered:
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
    print(f'[run] {TOTAL_STEPS} steps in {sim_secs:.1f}s ({sim_secs*1000/TOTAL_STEPS:.0f}ms/step)')

    out_dir = os.path.join(TRACE_ROOT, f't15_graph_{label}')
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
def plot_compare(h_off, h_on):
    steps = [r['step'] for r in h_off]
    metrics_to_plot = [
        ('avg_stress', '平均 σ (stress)'),
        ('max_stress', '最大个体 σ'),
        ('pct_stress_gt_06', '高压人群比例 (σ>0.6)'),
        ('herd_ratio', 'herd ratio'),
        ('flee_ratio', 'flee ratio (向 shelter 逃)'),
        ('avg_edge_congestion', '平均 edge congestion'),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    for ax, (k, lab) in zip(axes.flat, metrics_to_plot):
        off = [r[k] for r in h_off]
        on  = [r[k] for r in h_on]
        ax.plot(steps, off, label='graph-off', color='#888', linewidth=1.5)
        ax.plot(steps, on,  label='graph-on',  color='#d62728', linewidth=1.5)
        ax.axvline(OUTAGE_STEP, color='#666', linestyle=':', alpha=0.5)
        ax.set_title(lab, fontsize=11)
        ax.set_xlabel('step')
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=9)
    plt.tight_layout()
    out = os.path.join(TRACE_ROOT, 't15_comparison.png')
    fig.savefig(out, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'\n[plot] saved {out}')

    summary = {
        'config': {
            'n_residents': N_RESIDENTS, 'n_enterprises': N_ENT,
            'total_steps': TOTAL_STEPS, 'outage_step': OUTAGE_STEP, 'seed': SEED,
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
    out_json = os.path.join(TRACE_ROOT, 't15_summary.json')
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f'[summary] saved {out_json}')
    return summary


# =============================================================================
# main
# =============================================================================
def main():
    h_off, sim_off = run_one('off', use_road_graph=False)
    h_on,  sim_on  = run_one('on',  use_road_graph=True)
    summary = plot_compare(h_off, h_on)

    print('\n' + '=' * 70)
    print('  T15 对照实验摘要')
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
    # peak max_stress
    pk_off = max(r['max_stress'] for r in h_off)
    pk_on  = max(r['max_stress'] for r in h_on)
    print(f'  peak max_stress         {pk_off:>14.4f} {pk_on:>14.4f}')
    pk_off = max(r['flee_ratio'] for r in h_off)
    pk_on  = max(r['flee_ratio'] for r in h_on)
    print(f'  peak flee_ratio         {pk_off:>14.4f} {pk_on:>14.4f}')


if __name__ == '__main__':
    main()
