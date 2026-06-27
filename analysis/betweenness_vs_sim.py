# -*- coding: utf-8 -*-
"""T16: metrics (betweenness) ↔ 仿真观测 (cum_occupancy) Pearson 相关性。

Pipeline:
  1. 读 road_graph_cache/{城}_{区}.graphml (已 snap 过的图)
  2. 重新算 node betweenness (与 metrics.json 内部一致, k=200)
  3. 读 trace_output/M4_F1_cross_city/{城}_{区}/graph_on/edge_observations.csv
  4. 给每个 node 算 observed_load = sum(incoming edges' cum_occupancy)
  5. Pearson correlation between betweenness vs observed_load
  6. 画散点图 + 标 top-10 betweenness 节点

用法:
    # 默认 厦门思明
    python analysis/betweenness_vs_sim.py

    # 三城外推 (F1 已有 edge_observations.csv)
    python analysis/betweenness_vs_sim.py --city 沈阳市 --district 沈河区
    python analysis/betweenness_vs_sim.py --city 北京市 --district 东城区

输出:
  - trace_output/M4_T16_cross_city/{城}_{区}/correlation.{png,json}
"""
import os
import sys
import csv
import json
import argparse

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import numpy as np
import networkx as nx
import osmnx as ox
import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False
import matplotlib.pyplot as plt
from scipy.stats import pearsonr as _scipy_pearsonr, spearmanr as _scipy_spearmanr


def _pearson_r_p(x, y):
    """Pearson r + 2-tail p。n<3 或 σ=0 返回 (nan, nan)。"""
    x_arr = np.asarray(x, dtype=np.float64)
    y_arr = np.asarray(y, dtype=np.float64)
    if len(x_arr) < 3 or x_arr.std() <= 1e-12 or y_arr.std() <= 1e-12:
        return float('nan'), float('nan')
    r, p = _scipy_pearsonr(x_arr, y_arr)
    return float(r), float(p)


def _spearman_rho_p(x, y):
    """Spearman ρ + 2-tail p。"""
    x_arr = np.asarray(x, dtype=np.float64)
    y_arr = np.asarray(y, dtype=np.float64)
    if len(x_arr) < 3 or x_arr.std() <= 1e-12 or y_arr.std() <= 1e-12:
        return float('nan'), float('nan')
    rho, p = _scipy_spearmanr(x_arr, y_arr)
    return float(rho), float(p)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _parse_args():
    p = argparse.ArgumentParser(description='T16: betweenness vs sim cum_occupancy')
    p.add_argument('--city',     default='厦门市')
    p.add_argument('--district', default='思明区')
    p.add_argument('--edge-csv', default=None, dest='edge_csv',
                   help='默认从 M4_F1_cross_city/{city}_{district}/graph_on/ 读')
    p.add_argument('--out-dir',  default=None, dest='out_dir',
                   help='默认输出到 M4_T16_cross_city/{city}_{district}/')
    return p.parse_args()


def main():
    args = _parse_args()
    graphml = os.path.join(ROOT, 'road_graph_cache', f'{args.city}_{args.district}.graphml')
    edge_csv = args.edge_csv or os.path.join(
        ROOT, 'trace_output', 'M4_F1_cross_city',
        f'{args.city}_{args.district}', 'graph_on', 'edge_observations.csv')
    out_dir = args.out_dir or os.path.join(
        ROOT, 'trace_output', 'M4_T16_cross_city',
        f'{args.city}_{args.district}')
    os.makedirs(out_dir, exist_ok=True)
    out_png = os.path.join(out_dir, 'correlation.png')
    out_json = os.path.join(out_dir, 'correlation.json')

    print(f'[city] {args.city}/{args.district}')
    print(f'[1/4] load graph {graphml}')
    G = ox.io.load_graphml(graphml)
    print(f'  nodes={len(G.nodes)} edges={len(G.edges)}')

    print(f'[2/4] compute node betweenness (k=200, weight=length)')
    UG = nx.Graph(G)
    # 取最大连通分量, 与 city_metrics 一致
    largest = max(nx.connected_components(UG), key=len)
    UG_main = UG.subgraph(largest).copy()
    bc = nx.betweenness_centrality(
        UG_main, k=min(200, UG_main.number_of_nodes()),
        weight='length', seed=42,
    )
    print(f'  bc max={max(bc.values()):.4f}, mean={np.mean(list(bc.values())):.5f}')

    print(f'[3/4] read sim edge observations {edge_csv}')
    edge_obs = {}
    with open(edge_csv, 'r', encoding='utf-8') as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            u = row['u']
            v = row['v']
            cum = float(row['cum_occupancy'])
            edge_obs[(u, v)] = edge_obs.get((u, v), 0.0) + cum

    nonzero = sum(1 for v in edge_obs.values() if v > 0)
    print(f'  edges with cum > 0: {nonzero} / {len(edge_obs)}')

    print(f'[4/4] correlate node betweenness vs observed in-edge load', flush=True)
    # 把 OSM id 字符串化 (graphml 加载后是 int, csv 是 str)
    node_load = {}
    for n in UG_main.nodes:
        n_str = str(n)
        # 统计所有指向 n 的边的 cum_occupancy
        load = 0.0
        for u in G.predecessors(n) if G.is_directed() else G.neighbors(n):
            load += edge_obs.get((str(u), n_str), 0.0)
        node_load[n] = load
    print(f'  [4.1] node_load built ({len(node_load)} nodes)', flush=True)

    pairs = [(bc[n], node_load[n]) for n in UG_main.nodes if n in bc]
    bc_arr = np.array([p[0] for p in pairs])
    load_arr = np.array([p[1] for p in pairs])
    print(f'  [4.2] bc_arr/load_arr built (len={len(bc_arr)})', flush=True)

    # 全集 Pearson
    print(f'  [4.3a] calling std()', flush=True)
    s_load = float(load_arr.std())
    s_bc = float(bc_arr.std())
    print(f'  [4.3b] std OK: load={s_load:.6f} bc={s_bc:.6f}', flush=True)
    if s_load < 1e-12 or s_bc < 1e-12:
        r_all, p_all = float('nan'), float('nan')
    else:
        r_all, p_all = _pearson_r_p(bc_arr, load_arr)
    print(f'  Pearson r (all nodes)         = {r_all:.4f}  (p={p_all:.2e})', flush=True)

    # 仅看有非零 load 的 (噪声节点会掩盖信号)
    mask_nz = load_arr > 0
    if mask_nz.sum() >= 3 and load_arr[mask_nz].std() > 1e-12:
        r_nz, p_nz = _pearson_r_p(bc_arr[mask_nz], load_arr[mask_nz])
        print(f'  Pearson r (load>0, n={int(mask_nz.sum())}) = {r_nz:.4f}  (p={p_nz:.2e})')
    else:
        r_nz, p_nz = float('nan'), float('nan')

    # Spearman (rank-based, 抗重尾)
    if load_arr.std() > 1e-12 and bc_arr.std() > 1e-12:
        rho_all, sp_p_all = _spearman_rho_p(bc_arr, load_arr)
        print(f'  Spearman ρ (all)              = {rho_all:.4f}  (p={sp_p_all:.2e})')
    else:
        rho_all, sp_p_all = float('nan'), float('nan')

    # 关键路径: 先写 json (Crowds_sim env 的 matplotlib 易 crash, json 必须先落盘)
    summary = {
        'n_nodes': int(len(bc_arr)),
        'n_nodes_with_observed_load': int(mask_nz.sum()),
        'pearson_r_all': float(r_all) if not np.isnan(r_all) else None,
        'pearson_p_all': float(p_all) if not np.isnan(p_all) else None,
        'pearson_r_nonzero': float(r_nz) if not np.isnan(r_nz) else None,
        'pearson_p_nonzero': float(p_nz) if not np.isnan(p_nz) else None,
        'spearman_rho_all': float(rho_all) if not np.isnan(rho_all) else None,
        'spearman_p_all': float(sp_p_all) if not np.isnan(sp_p_all) else None,
        'interpretation': (
            'r > 0.5: 模型自洽, betweenness 能预测仿真观测; '
            'r ≈ 0: cascade 未充分触发或路径分布与拓扑无关'
        ),
    }
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f'[summary] saved {out_json}')

    # 易碎: 画散点 (Crowds_sim matplotlib 在 fig.savefig 时可能 0xC00000FF
    # 进程级 crash, try/except 不一定能救; json 在上面已落盘, plot 缺失也无碍)
    try:
        fig, axes = plt.subplots(1, 2, figsize=(13, 5))
        ax = axes[0]
        ax.scatter(bc_arr, load_arr, alpha=0.3, s=8, color='#3b82f6')
        # 标 top-10 betweenness 节点
        top10_idx = np.argsort(-bc_arr)[:10]
        ax.scatter(bc_arr[top10_idx], load_arr[top10_idx],
                   color='#dc2626', s=40, label='top-10 betweenness', zorder=5)
        ax.set_xlabel('node betweenness (metrics 预测)')
        ax.set_ylabel('observed in-edge load (cum_occupancy)')
        ax.set_title(f'全节点散点 (Pearson r={r_all:.3f})')
        ax.legend()
        ax.grid(True, alpha=0.3)

        ax = axes[1]
        if mask_nz.sum() > 0:
            ax.scatter(bc_arr[mask_nz], load_arr[mask_nz],
                       alpha=0.5, s=12, color='#10b981')
            ax.set_xlabel('node betweenness (metrics 预测)')
            ax.set_ylabel('observed in-edge load')
            ax.set_title(f'非零 load 节点 (n={int(mask_nz.sum())}, Pearson r={r_nz:.3f})')
            ax.grid(True, alpha=0.3)
        else:
            ax.text(0.5, 0.5, '所有 load=0 (cascade 未触发)',
                    ha='center', va='center', transform=ax.transAxes)

        plt.tight_layout()
        fig.savefig(out_png, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close(fig)
        print(f'\n[plot] saved {out_png}')
    except Exception as ex:
        print(f'[plot] WARN: {type(ex).__name__}: {ex} (json 已落盘, 不影响数据)')

    print(f'\n=== T16 结论 ===')
    if not np.isnan(r_all):
        if r_all > 0.5:
            verdict = '✅ 强正相关, 模型自洽'
        elif r_all > 0.2:
            verdict = '🟡 弱正相关, cascade 部分触发'
        else:
            verdict = '⚠️ 弱相关, cascade 未充分触发 (建议加大 N_RESIDENTS)'
        print(f'  Pearson r (all)      = {r_all:.4f}    → {verdict}')
    if not np.isnan(r_nz):
        print(f'  Pearson r (non-zero) = {r_nz:.4f}')
    if not np.isnan(rho_all):
        print(f'  Spearman ρ (all)     = {rho_all:.4f}')


if __name__ == '__main__':
    main()
