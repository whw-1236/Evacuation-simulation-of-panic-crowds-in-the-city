# -*- coding: utf-8 -*-
"""T16: metrics (betweenness) ↔ 仿真观测 (cum_occupancy) Pearson 相关性。

Pipeline:
  1. 读 road_graph_cache/厦门市_思明区.graphml (已 snap 过的图)
  2. 重新算 node betweenness (与 metrics.json 内部一致, k=200)
  3. 读 trace_output/t15_graph_on/edge_observations.csv (仿真观测)
  4. 给每个 node 算 observed_load = sum(incoming edges' cum_occupancy)
  5. Pearson correlation between betweenness vs observed_load
  6. 画散点图 + 标 top-10 betweenness 节点

输出:
  - trace_output/t16_correlation.png
  - trace_output/t16_correlation.json
"""
import os
import sys
import csv
import json

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
from scipy import stats as scipy_stats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAPHML = os.path.join(ROOT, 'road_graph_cache', '厦门市_思明区.graphml')
EDGE_CSV = os.path.join(ROOT, 'trace_output', 't15_graph_on', 'edge_observations.csv')
OUT_PNG = os.path.join(ROOT, 'trace_output', 't16_correlation.png')
OUT_JSON = os.path.join(ROOT, 'trace_output', 't16_correlation.json')


def main():
    print(f'[1/4] load graph {GRAPHML}')
    G = ox.io.load_graphml(GRAPHML)
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

    print(f'[3/4] read sim edge observations {EDGE_CSV}')
    edge_obs = {}
    with open(EDGE_CSV, 'r', encoding='utf-8') as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            u = row['u']
            v = row['v']
            cum = float(row['cum_occupancy'])
            edge_obs[(u, v)] = edge_obs.get((u, v), 0.0) + cum

    nonzero = sum(1 for v in edge_obs.values() if v > 0)
    print(f'  edges with cum > 0: {nonzero} / {len(edge_obs)}')

    print(f'[4/4] correlate node betweenness vs observed in-edge load')
    # 把 OSM id 字符串化 (graphml 加载后是 int, csv 是 str)
    node_load = {}
    for n in UG_main.nodes:
        n_str = str(n)
        # 统计所有指向 n 的边的 cum_occupancy
        load = 0.0
        for u in G.predecessors(n) if G.is_directed() else G.neighbors(n):
            load += edge_obs.get((str(u), n_str), 0.0)
        node_load[n] = load

    pairs = [(bc[n], node_load[n]) for n in UG_main.nodes if n in bc]
    bc_arr = np.array([p[0] for p in pairs])
    load_arr = np.array([p[1] for p in pairs])

    # 全集 Pearson
    if load_arr.std() < 1e-12 or bc_arr.std() < 1e-12:
        r_all, p_all = float('nan'), float('nan')
    else:
        r_all, p_all = scipy_stats.pearsonr(bc_arr, load_arr)
    print(f'  Pearson r (all nodes)         = {r_all:.4f}  (p={p_all:.2e})')

    # 仅看有非零 load 的 (噪声节点会掩盖信号)
    mask_nz = load_arr > 0
    if mask_nz.sum() >= 3 and load_arr[mask_nz].std() > 1e-12:
        r_nz, p_nz = scipy_stats.pearsonr(bc_arr[mask_nz], load_arr[mask_nz])
        print(f'  Pearson r (load>0, n={int(mask_nz.sum())}) = {r_nz:.4f}  (p={p_nz:.2e})')
    else:
        r_nz, p_nz = float('nan'), float('nan')

    # Spearman (rank-based, 抗重尾)
    if load_arr.std() > 1e-12 and bc_arr.std() > 1e-12:
        rho_all, sp_p_all = scipy_stats.spearmanr(bc_arr, load_arr)
        print(f'  Spearman ρ (all)              = {rho_all:.4f}  (p={sp_p_all:.2e})')
    else:
        rho_all, sp_p_all = float('nan'), float('nan')

    # 画散点
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
    fig.savefig(OUT_PNG, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'\n[plot] saved {OUT_PNG}')

    # JSON 摘要
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
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f'[summary] saved {OUT_JSON}')

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
