# -*- coding: utf-8 -*-
"""T16b: Shelter-aware betweenness vs 仿真观测 — 验证"标准 betweenness 失效"假说。

假说: 标准 betweenness (任意两节点均匀流通) 不能预测仿真观测,
因为仿真是 "home → 最近 shelter" 的有向流。
应该用 shelter-aware betweenness (节点作为"home → shelter 路径"的中转点频率)
才能预测瓶颈。

做法:
  1. 读 graph + shelters (从 应急.csv)
  2. 对每个非 shelter 节点 n: 算 shortest_path(n, nearest_shelter)
  3. 统计每个 node 作为这些路径中转点的次数 → shelter_aware_bc[n]
  4. 重做 Pearson 相关: shelter_aware_bc vs observed_load
  5. 比较 r_standard vs r_shelter_aware
"""
import os
import sys
import csv
import json
import time

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

from core.road_graph import snap_to_nodes_batch
from core.shelter_loader import load_shelters

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAPHML  = os.path.join(ROOT, 'road_graph_cache', '厦门市_思明区.graphml')
MAP_DIR  = os.path.join(ROOT, 'simulation map data')
EDGE_CSV = os.path.join(ROOT, 'trace_output', 't15_graph_on', 'edge_observations.csv')
OUT_PNG  = os.path.join(ROOT, 'trace_output', 't16b_shelter_aware.png')
OUT_JSON = os.path.join(ROOT, 'trace_output', 't16b_shelter_aware.json')

SAMPLE_SOURCES = 600   # 随机抽 N 个源节点算 shelter_aware_bc (全量太慢)


def main():
    print(f'[1] load graph')
    G_full = ox.io.load_graphml(GRAPHML)
    UG = nx.Graph(G_full)
    largest = max(nx.connected_components(UG), key=len)
    UG = UG.subgraph(largest).copy()
    nodes_main = list(UG.nodes)
    n_nodes = len(nodes_main)
    print(f'  largest cc: {n_nodes} nodes')

    print(f'[2] load shelters + snap')
    shelters = load_shelters(MAP_DIR, '厦门市', '思明区')
    xs = [s['lon'] for s in shelters]
    ys = [s['lat'] for s in shelters]
    shelter_node_ids = snap_to_nodes_batch(G_full, xs, ys)
    shelter_nodes_set = set()
    for nid in shelter_node_ids:
        # graphml 读出来 nodes 是 str
        nid_str = str(nid)
        if nid_str in UG:
            shelter_nodes_set.add(nid_str)
        elif int(nid) in UG:
            shelter_nodes_set.add(int(nid))
    shelter_nodes = list(shelter_nodes_set)
    print(f'  {len(shelter_nodes)} shelter nodes in main cc')

    print(f'[3] 标准 betweenness (作为对照)')
    t = time.time()
    bc_std = nx.betweenness_centrality(
        UG, k=min(200, n_nodes), weight='length', seed=42)
    print(f'  done {time.time()-t:.1f}s, max={max(bc_std.values()):.4f}')

    print(f'[4] shelter-aware betweenness: 每个源节点 → 最近 shelter 最短路, 计数中转点')
    bc_shelter = {n: 0 for n in nodes_main}
    rng = np.random.default_rng(42)
    sample = list(rng.choice(nodes_main, size=min(SAMPLE_SOURCES, n_nodes), replace=False))
    t = time.time()
    for i, src in enumerate(sample):
        if src in shelter_nodes_set:
            continue
        # 找最近 shelter (按 length 最短路)
        best_path = None
        best_len = float('inf')
        for sh in shelter_nodes:
            try:
                L = nx.shortest_path_length(UG, src, sh, weight='length')
                if L < best_len:
                    best_len = L
                    best_path = nx.shortest_path(UG, src, sh, weight='length')
            except nx.NetworkXNoPath:
                continue
        if best_path:
            for nd in best_path[1:-1]:  # 不计端点
                bc_shelter[nd] += 1
        if (i + 1) % 100 == 0:
            print(f'  {i+1}/{len(sample)} sources processed ({time.time()-t:.1f}s)')
    # normalize 到 [0, 1]
    max_bc_sh = max(bc_shelter.values())
    if max_bc_sh > 0:
        for n in bc_shelter:
            bc_shelter[n] = bc_shelter[n] / max_bc_sh
    print(f'  done {time.time()-t:.1f}s, max_count={max_bc_sh}')

    print(f'[5] 读仿真 edge 观测, 算 node observed load')
    edge_obs = {}
    with open(EDGE_CSV, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            edge_obs[(row['u'], row['v'])] = float(row['cum_occupancy'])

    node_load = {}
    for n in nodes_main:
        n_str = str(n)
        load = 0.0
        for nb in (G_full.predecessors(n) if G_full.is_directed() else G_full.neighbors(n)):
            load += edge_obs.get((str(nb), n_str), 0.0)
        node_load[n] = load
    nonzero = sum(1 for v in node_load.values() if v > 0)
    print(f'  nodes with load>0: {nonzero} / {n_nodes}')

    print(f'[6] 相关性对照')
    arr_std = np.array([bc_std[n] for n in nodes_main])
    arr_sh  = np.array([bc_shelter[n] for n in nodes_main])
    arr_load = np.array([node_load[n] for n in nodes_main])

    r_std, p_std = scipy_stats.pearsonr(arr_std, arr_load)
    r_sh,  p_sh  = scipy_stats.pearsonr(arr_sh,  arr_load)
    rho_std, _ = scipy_stats.spearmanr(arr_std, arr_load)
    rho_sh,  _ = scipy_stats.spearmanr(arr_sh,  arr_load)

    mask_nz = arr_load > 0
    if mask_nz.sum() >= 3:
        r_sh_nz, p_sh_nz = scipy_stats.pearsonr(arr_sh[mask_nz], arr_load[mask_nz])
    else:
        r_sh_nz, p_sh_nz = float('nan'), float('nan')

    print('\n  =================== 对照表 ===================')
    print(f'  {"指标":<26} {"r (Pearson)":>12} {"ρ (Spearman)":>14}')
    print(f'  {"标准 betweenness":<25}{r_std:>12.4f} {rho_std:>14.4f}')
    print(f'  {"shelter-aware bc":<25}{r_sh:>12.4f} {rho_sh:>14.4f}')
    if not np.isnan(r_sh_nz):
        print(f'  {"shelter-aware (load>0)":<25}{r_sh_nz:>12.4f}')
    print('  ==============================================')
    print(f'  改善: r_shelter / r_std = {(r_sh/r_std if abs(r_std)>1e-9 else float("inf")):.1f}x')

    # 画散点对照
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    ax = axes[0]
    ax.scatter(arr_std, arr_load, alpha=0.3, s=8, color='#3b82f6')
    ax.set_xlabel('标准 betweenness (任意两点均匀流)')
    ax.set_ylabel('observed in-edge load')
    ax.set_title(f'标准 BC vs 观测  (Pearson r={r_std:.3f})')
    ax.grid(True, alpha=0.3)

    ax = axes[1]
    ax.scatter(arr_sh, arr_load, alpha=0.3, s=8, color='#10b981')
    ax.set_xlabel('shelter-aware betweenness\n(home→nearest shelter 路径中转频率)')
    ax.set_ylabel('observed in-edge load')
    ax.set_title(f'Shelter-aware BC vs 观测  (Pearson r={r_sh:.3f})')
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    fig.savefig(OUT_PNG, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'\n[plot] saved {OUT_PNG}')

    out = {
        'standard_betweenness_pearson_r': float(r_std),
        'standard_betweenness_spearman_rho': float(rho_std),
        'shelter_aware_betweenness_pearson_r': float(r_sh),
        'shelter_aware_betweenness_spearman_rho': float(rho_sh),
        'shelter_aware_pearson_r_nonzero': float(r_sh_nz) if not np.isnan(r_sh_nz) else None,
        'improvement_ratio_r_shelter_over_standard': (
            float(r_sh / r_std) if abs(r_std) > 1e-9 else None),
        'n_shelters': len(shelter_nodes),
        'n_sample_sources': len(sample),
        'interpretation': (
            'r 显著提升 -> 仿真观测由"home→shelter"驱动, '
            '标准 BC 失效, 应当使用 shelter-aware BC 作为新指标。'
        ),
    }
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f'[summary] saved {OUT_JSON}')


if __name__ == '__main__':
    main()
