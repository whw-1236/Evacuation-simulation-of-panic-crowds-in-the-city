# -*- coding: utf-8 -*-
"""
================================================================================
城市路网指标计算模块（跨城市对比实验核心）
================================================================================
四组指标（评审会问的四类问题各一组）：
    1. topology    基础拓扑：路网总长、节点/边密度、平均路段长、平均度
    2. geometry    几何形态：方位熵（网格化 vs 不规则）+ circuity
    3. evacuation  疏散相关：betweenness、直径、连通分量、最大组规模
    4. coupling    人口耦合：人均路网长、人均路口数（需 population 参数）

输出：
    {ROAD_GRAPH_CACHE_DIR}/{city}_{district}/
        ├── metrics.json
        ├── orientation_rose.png
        └── betweenness_heatmap.png

设计原则：
    - 一次性预计算 + 缓存 JSON，不参与每步仿真
    - 论文 Methodology 章节 Table 直接抄 JSON 字段
    - 跨城市对比时所有城市用同一计算流程，保证 fair comparison
================================================================================
"""
import os
import json
import math

import numpy as np
import networkx as nx
import osmnx as ox
import matplotlib
matplotlib.use('Agg')  # 防止后台无显示器卡住
import matplotlib.pyplot as plt
import matplotlib.cm as cm

# 中文字体支持（Windows 优先 Microsoft YaHei，无则 fallback）。
# 没装中文字体时不会报错，只会把中文显示成方块。
matplotlib.rcParams['font.sans-serif'] = [
    'Microsoft YaHei', 'SimHei', 'PingFang SC', 'Arial Unicode MS', 'DejaVu Sans',
]
matplotlib.rcParams['axes.unicode_minus'] = False

from .road_graph import ROAD_GRAPH_CACHE_DIR


# =============================================================================
# 内部工具
# =============================================================================
def _output_dir(city, district):
    safe = f"{city}_{district or 'all'}".replace('/', '_').replace('\\', '_')
    d = os.path.join(ROAD_GRAPH_CACHE_DIR, safe)
    os.makedirs(d, exist_ok=True)
    return d


def _make_jsonable(obj):
    """递归转成 json 可序列化对象。"""
    if isinstance(obj, dict):
        return {str(k): _make_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_jsonable(v) for v in obj]
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (int, float, str, type(None), bool)):
        return obj
    return str(obj)


def _bbox_area_km2(G):
    """从节点 bounding box 估算覆盖面积 (km²)。粗估，作为 polygon area 不可达时的 fallback。

    注意: 对于沿海/多山的城市 (如厦门), bbox 会把大块海域+山地算进去,
    导致密度被严重低估。优先用 fetch_polygon_area_km2()。
    """
    nodes_df = ox.convert.graph_to_gdfs(G, nodes=True, edges=False)
    minx, miny, maxx, maxy = nodes_df.total_bounds
    lat_mid = (miny + maxy) / 2.0
    km_per_deg_lat = 111.0
    km_per_deg_lon = 111.0 * math.cos(math.radians(lat_mid))
    return float((maxx - minx) * km_per_deg_lon * (maxy - miny) * km_per_deg_lat)


def fetch_polygon_area_km2(place_query):
    """通过 osmnx.geocoder 抓取真实行政边界 polygon, 投影到 UTM 算面积 (km²)。

    优势: 排除海域/山地, 反映真实建成区/行政区面积
    Args:
        place_query: 'Siming, Xiamen, Fujian, China' 或 '厦门市思明区'
    Returns:
        float | None: 面积 km², 失败时返回 None (调用方应 fallback 到 bbox)
    """
    try:
        gdf = ox.geocoder.geocode_to_gdf(place_query)
        gdf_proj = ox.projection.project_gdf(gdf)
        area_m2 = float(gdf_proj.geometry.area.sum())
        return area_m2 / 1_000_000.0
    except Exception as ex:
        print(f"[city_metrics] WARN: 取 polygon area 失败 for '{place_query}': "
              f"{type(ex).__name__}: {ex}")
        return None


# =============================================================================
# 重尾分布扩展指标：Gini / top-k 份额 / std
# =============================================================================
def _gini_coefficient(values):
    """Gini ∈ [0, 1]: 0=完全平均, 1=极度集中。

    重尾分布 (如 betweenness centrality) 必须用此而非 mean。
    """
    if values is None:
        return 0.0
    arr = np.asarray(values, dtype=float)
    arr = arr[arr >= 0]  # 负值视为无效
    if arr.size == 0:
        return 0.0
    arr = np.sort(arr)
    n = arr.size
    total = arr.sum()
    if total <= 0:
        return 0.0
    cum = np.arange(1, n + 1) * arr
    return float((2.0 * cum.sum()) / (n * total) - (n + 1.0) / n)


def _top_share(values, top_pct=1.0):
    """top-k% 节点占总量的份额 ∈ [0, 1]。

    top_pct=1.0 → top 1% 的份额 (典型重尾指标)
    """
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return 0.0
    total = arr.sum()
    if total <= 0:
        return 0.0
    k = max(1, int(np.ceil(arr.size * top_pct / 100.0)))
    arr_desc = np.sort(arr)[::-1]
    return float(arr_desc[:k].sum() / total)


# =============================================================================
# 1. 基础拓扑
# =============================================================================
def compute_topology(G, area_km2=None, area_source='bbox'):
    """拓扑指标。area_source ∈ {'polygon', 'bbox'} 用于标注论文里别人能复现。"""
    if area_km2 is None:
        area_km2 = _bbox_area_km2(G)
        area_source = 'bbox'
    edge_lengths = [d.get('length', 0.0) for _, _, _, d in G.edges(keys=True, data=True)]
    total_len_m = float(sum(edge_lengths))
    stats = ox.basic_stats(G)
    return {
        'n_nodes': int(G.number_of_nodes()),
        'n_edges': int(G.number_of_edges()),
        'area_km2': area_km2,
        'area_source': area_source,    # 'polygon' (准确) | 'bbox' (粗估, fallback)
        'edge_length_total_km': total_len_m / 1000.0,
        'intersection_density_per_km2': (G.number_of_nodes() / area_km2) if area_km2 > 0 else 0.0,
        'edge_density_per_km2': (G.number_of_edges() / area_km2) if area_km2 > 0 else 0.0,
        'street_length_avg_m': float(np.mean(edge_lengths)) if edge_lengths else 0.0,
        'streets_per_node_avg': float(stats.get('streets_per_node_avg', 0.0)),
    }


# =============================================================================
# 2. 几何形态（方位熵 + circuity）
# =============================================================================
def compute_geometry(G, num_bins=36):
    """方位熵: 越接近 0 = 越棋盘格化 (如沈阳)；越接近 ln(36) ≈ 3.58 = 越不规则 (如厦门)。
    同时把 bearing 分布直方图存下来，后续 plot 失败时仍能离线重画。
    """
    Gp = ox.bearing.add_edge_bearings(ox.convert.to_undirected(G))
    orient_entropy = float(ox.bearing.orientation_entropy(Gp, num_bins=num_bins))

    # 提取所有 bearing 算 histogram (raw data, for offline replot)
    bearings = []
    for _, _, _, d in Gp.edges(keys=True, data=True):
        b = d.get('bearing')
        if b is not None and not (isinstance(b, float) and math.isnan(b)):
            bearings.append(float(b))
    hist_counts, hist_edges = (None, None)
    if bearings:
        counts, edges = np.histogram(bearings, bins=num_bins, range=(0, 360))
        hist_counts = counts.tolist()
        hist_edges = edges.tolist()

    stats = ox.basic_stats(G)
    circuity = stats.get('circuity_avg', None)
    if circuity is not None and not (isinstance(circuity, float) and math.isnan(circuity)):
        circuity = float(circuity)
    else:
        circuity = None

    return {
        'orientation_entropy': orient_entropy,
        'orientation_entropy_max': float(math.log(num_bins)),  # 完全均匀时的熵
        'orientation_entropy_norm': orient_entropy / math.log(num_bins),  # 0~1 归一化
        'circuity_avg': circuity,
        'bearing_histogram_counts': hist_counts,    # 36 bins，用于离线重画玫瑰图
        'bearing_histogram_edges_deg': hist_edges,
    }


# =============================================================================
# 3. 疏散相关（betweenness + 直径 + 连通性）
# =============================================================================
def compute_evacuation(G, k_sample=200, seed=42):
    """betweenness 用采样近似（k_sample 个源），完整版在 N>1000 时太慢。"""
    UG = nx.Graph(G)
    components = list(nx.connected_components(UG))
    n_components = len(components)

    if not components:
        return {
            'n_components': 0,
            'largest_component_nodes': 0,
            'betweenness_max': 0.0,
            'betweenness_mean': 0.0,
            'top10_betweenness_nodes': [],
            'diameter_m': None,
            '_full_betweenness': {},
        }

    largest = max(components, key=len)
    UG_main = UG.subgraph(largest).copy()

    k = min(UG_main.number_of_nodes(), k_sample)
    bc = nx.betweenness_centrality(UG_main, k=k, weight='length', seed=seed)
    top10 = sorted(bc.items(), key=lambda x: -x[1])[:10]

    diameter_m = None
    if UG_main.number_of_nodes() < 3000:
        try:
            diameter_m = float(nx.diameter(UG_main, weight='length'))
        except Exception:
            diameter_m = None

    # 【V3#5】重尾分布扩展指标: Gini + std + top-1% 份额
    bc_vals = list(bc.values()) if bc else []
    return {
        'n_components': int(n_components),
        'largest_component_nodes': int(UG_main.number_of_nodes()),
        'betweenness_max': float(max(bc_vals)) if bc_vals else 0.0,
        'betweenness_mean': float(np.mean(bc_vals)) if bc_vals else 0.0,
        'betweenness_std': float(np.std(bc_vals)) if bc_vals else 0.0,
        'betweenness_gini': _gini_coefficient(bc_vals),
        'betweenness_top1pct_share': _top_share(bc_vals, top_pct=1.0),
        'top10_betweenness_nodes': [(str(nid), float(b)) for nid, b in top10],
        'diameter_m': diameter_m,
        '_full_betweenness': bc,  # 内部用，不写 JSON
    }


# =============================================================================
# 4. 人口耦合（可选，需 population 参数）
# =============================================================================
def compute_coupling(topology, population=None):
    if not population or population <= 0:
        return {
            'population': None,
            'edge_length_per_capita_m': None,
            'intersection_per_1k_capita': None,
            'note': '未提供 population，跳过耦合指标',
        }
    pop = int(population)
    return {
        'population': pop,
        'edge_length_per_capita_m': topology['edge_length_total_km'] * 1000.0 / pop,
        'intersection_per_1k_capita': topology['n_nodes'] / (pop / 1000.0),
    }


# =============================================================================
# 画图：方位玫瑰
# =============================================================================
def plot_orientation_rose(G, out_path, title=None):
    """osmnx 2.x: plot_orientation 没有 show/close 参数，直接返回 (fig, ax)。
    title_font 显式指定中文字体，否则会用 DejaVu Sans 把 CJK 渲染成方块。
    """
    Gp = ox.bearing.add_edge_bearings(ox.convert.to_undirected(G))
    cjk_font = {'family': 'Microsoft YaHei', 'size': 14, 'weight': 'bold'}
    fig, ax = ox.plot.plot_orientation(
        Gp, num_bins=36, area=True, title=title or '',
        title_font=cjk_font,
    )
    fig.savefig(out_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)


# =============================================================================
# 画图：betweenness 热力
# =============================================================================
def plot_betweenness_heatmap(G, bc_dict, out_path, title=None, figsize=(14, 14)):
    bc_vals = [bc_dict.get(n, 0.0) for n in G.nodes]
    bc_max = max(bc_vals) if bc_vals else 1.0
    if bc_max <= 0:
        bc_max = 1.0
    norm_vals = [v / bc_max for v in bc_vals]
    node_colors = [cm.plasma(v) for v in norm_vals]

    fig, ax = ox.plot.plot_graph(
        G,
        node_color=node_colors, node_size=14,
        edge_color='#cccccc', edge_linewidth=0.45,
        bgcolor='white', figsize=figsize,
        show=False, close=False,
    )
    if title:
        ax.set_title(title, fontsize=13)
    fig.savefig(out_path, dpi=160, bbox_inches='tight', facecolor='white')
    plt.close(fig)


# =============================================================================
# 主入口
# =============================================================================
def compute_all(G, city, district=None, population=None,
                save=True, k_sample=200, seed=42, plot=True,
                place_query=None, area_km2_override=None):
    """计算 4 组指标，可选择保存 metrics.json + 2 张 plot 到 cache 目录。

    Args:
        G: networkx 图（来自 road_graph.load_or_build）
        city, district: 城市/区名（用于命名输出）
        population: 区域人口（用于耦合指标，可选）
        k_sample: betweenness 采样源数量
        seed: 随机种子（保证可复现）
        plot: 是否生成 orientation_rose + betweenness_heatmap
        place_query: 给 fetch_polygon_area_km2 用 (优先级最高)，
                     默认拼 f"{city}{district}"
        area_km2_override: 直接指定面积值 (跳过 polygon 查询)

    Returns:
        dict: 4 组指标
    """
    # 【V3#1】先把面积算准: polygon > override > bbox 三级 fallback
    if area_km2_override is not None:
        area_km2 = float(area_km2_override)
        area_source = 'override'
    else:
        q = place_query or (f"{city}{district}" if district else city)
        print(f"[city_metrics] fetching polygon area for '{q}'...")
        area_km2 = fetch_polygon_area_km2(q)
        if area_km2 is not None and area_km2 > 0:
            area_source = 'polygon'
        else:
            area_km2 = _bbox_area_km2(G)
            area_source = 'bbox'
            print(f"[city_metrics] fallback to bbox area")
    print(f"[city_metrics] area = {area_km2:.1f} km² ({area_source})")

    print(f"[city_metrics] {city} {district or ''}: topology...")
    topo = compute_topology(G, area_km2=area_km2, area_source=area_source)

    print(f"[city_metrics] geometry (orientation entropy + circuity)...")
    geom = compute_geometry(G)

    print(f"[city_metrics] evacuation (betweenness k={k_sample}, diameter, Gini)...")
    evac = compute_evacuation(G, k_sample=k_sample, seed=seed)
    bc_full = evac.pop('_full_betweenness')

    print(f"[city_metrics] coupling (per-capita)...")
    coup = compute_coupling(topo, population)

    metrics = {
        'city': city,
        'district': district,
        'topology': topo,
        'geometry': geom,
        'evacuation': evac,
        'coupling': coup,
    }

    if save:
        out_dir = _output_dir(city, district)
        json_path = os.path.join(out_dir, 'metrics.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(_make_jsonable(metrics), f, ensure_ascii=False, indent=2)
        print(f"[city_metrics] saved -> {json_path}")

        if plot:
            # plot 容错：即使本机 matplotlib 有问题（如 Windows C 扩展 ABI），
            # 也不破坏整体流程；bearing_histogram 已存到 metrics.json，
            # 之后任何机器上都能离线重画。
            rose = os.path.join(out_dir, 'orientation_rose.png')
            try:
                plot_orientation_rose(G, rose, title=f"{city} {district or ''}".strip())
                print(f"[city_metrics] saved -> {rose}")
            except Exception as ex:
                print(f"[city_metrics] WARN: orientation_rose 绘图失败 ({type(ex).__name__}: {ex})")
                print(f"[city_metrics]       直方图原始数据已存入 metrics.json:bearing_histogram_counts")

            heat = os.path.join(out_dir, 'betweenness_heatmap.png')
            try:
                plot_betweenness_heatmap(G, bc_full, heat,
                                         title=f"{city} {district or ''} · Betweenness".strip())
                print(f"[city_metrics] saved -> {heat}")
            except Exception as ex:
                print(f"[city_metrics] WARN: betweenness_heatmap 绘图失败 ({type(ex).__name__}: {ex})")
                print(f"[city_metrics]       Top-10 节点已在 metrics.json:evacuation.top10_betweenness_nodes")

    return metrics


# =============================================================================
# 自测
# =============================================================================
if __name__ == '__main__':
    from .road_graph import load_or_build
    G = load_or_build('厦门市', '思明区')
    metrics = compute_all(G, city='厦门市', district='思明区', population=1_010_000)
    print("\n[summary]")
    print(f"  路网总长: {metrics['topology']['edge_length_total_km']:.1f} km")
    print(f"  节点密度: {metrics['topology']['intersection_density_per_km2']:.1f} /km²")
    print(f"  方位熵: {metrics['geometry']['orientation_entropy']:.3f}"
          f" (归一化 {metrics['geometry']['orientation_entropy_norm']:.2f})")
    print(f"  最大组节点数: {metrics['evacuation']['largest_component_nodes']}")
