# -*- coding: utf-8 -*-
"""
================================================================================
路网图构建与缓存模块 (osmnx 接入)
================================================================================
功能：
    1. 从 OpenStreetMap 下载城市/区路网（osmnx.graph_from_place）
    2. 按 OSM highway 类型标注 edge 属性：
       - capacity_per_step    每仿真步可通过的 agent 数（dt=15min 默认）
       - free_flow_speed       自由流步行速度 (m/s)
       - effective_width_m     有效行走宽度 (m)
       - occupancy             运行时占用计数（初始 0）
    3. 缓存为 graphml，下次离线复用
    4. load_or_build() 一站式入口

用法：
    from core.road_graph import load_or_build
    G = load_or_build('厦门市', '思明区')        # 首次联网下载，之后离线
    G = load_or_build('沈阳市', '沈河区')        # 切换城市零代码改动

缓存位置：
    {project_root}/road_graph_cache/{city}_{district}.graphml
================================================================================
"""
import os
import networkx as nx
import osmnx as ox

# 项目根目录 (core/ 的父目录)
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
ROAD_GRAPH_CACHE_DIR = os.path.join(_PROJECT_ROOT, 'road_graph_cache')


# =============================================================================
# OSM highway 类型 → edge 属性映射
# -----------------------------------------------------------------------------
# capacity_per_step 单位 = "agent / step" (假设 step = 15 min)
# 基础参考：HCM 2010 步行流通行能力 ~1.3 ped/(m·s)
#   宽 3 m 街道: 1.3 × 3 × 900 s ≈ 3500 / 15min
# 这里取一个保守缩放 (约 1/10)，便于在 N≈1200 的仿真规模下能看到拥堵现象。
# 后期论文里可在 config 里覆盖具体数值。
# =============================================================================
HIGHWAY_PROFILES = {
    'motorway':      {'capacity_per_step': 600, 'free_flow_speed': 1.4, 'effective_width_m': 4.0},
    'trunk':         {'capacity_per_step': 600, 'free_flow_speed': 1.4, 'effective_width_m': 4.0},
    'primary':       {'capacity_per_step': 550, 'free_flow_speed': 1.4, 'effective_width_m': 4.0},
    'secondary':     {'capacity_per_step': 450, 'free_flow_speed': 1.3, 'effective_width_m': 3.0},
    'tertiary':      {'capacity_per_step': 400, 'free_flow_speed': 1.3, 'effective_width_m': 3.0},
    'residential':   {'capacity_per_step': 300, 'free_flow_speed': 1.2, 'effective_width_m': 2.5},
    'living_street': {'capacity_per_step': 250, 'free_flow_speed': 1.2, 'effective_width_m': 2.5},
    'pedestrian':    {'capacity_per_step': 450, 'free_flow_speed': 1.3, 'effective_width_m': 3.0},
    'footway':       {'capacity_per_step': 300, 'free_flow_speed': 1.2, 'effective_width_m': 2.0},
    'path':          {'capacity_per_step': 200, 'free_flow_speed': 1.2, 'effective_width_m': 1.5},
    'service':       {'capacity_per_step': 200, 'free_flow_speed': 1.2, 'effective_width_m': 2.0},
    'unclassified':  {'capacity_per_step': 300, 'free_flow_speed': 1.2, 'effective_width_m': 2.5},
    'track':         {'capacity_per_step': 150, 'free_flow_speed': 1.0, 'effective_width_m': 1.5},
    'cycleway':      {'capacity_per_step': 250, 'free_flow_speed': 1.3, 'effective_width_m': 2.0},
    'steps':         {'capacity_per_step': 100, 'free_flow_speed': 0.6, 'effective_width_m': 1.2},
}
DEFAULT_PROFILE = {'capacity_per_step': 300, 'free_flow_speed': 1.2, 'effective_width_m': 2.5}

# graphml 反序列化时需要还原成数值的字段
_NUMERIC_EDGE_FIELDS = (
    'capacity_per_step', 'free_flow_speed', 'effective_width_m',
    'length', 'occupancy',
)


# =============================================================================
# 内部工具
# =============================================================================
def _cache_filename(city, district):
    safe = f"{city}_{district or 'all'}".replace('/', '_').replace('\\', '_')
    return os.path.join(ROAD_GRAPH_CACHE_DIR, f"{safe}.graphml")


def _normalize_highway(hw):
    """OSM 的 highway 字段可能是 str，也可能是 list（多类型路段）。统一成 str。"""
    if isinstance(hw, list):
        return hw[0] if hw else 'unclassified'
    return hw or 'unclassified'


def _coerce_numeric_fields(G):
    """graphml 反序列化后所有 attr 变成字符串，把已知数值字段转回 float。"""
    for _, _, _, data in G.edges(keys=True, data=True):
        for key in _NUMERIC_EDGE_FIELDS:
            if key in data and not isinstance(data[key], (int, float)):
                try:
                    data[key] = float(data[key])
                except (TypeError, ValueError):
                    pass
    return G


# =============================================================================
# 对外接口
# =============================================================================
def annotate_edges(G):
    """给每条 edge 加 capacity_per_step / free_flow_speed / effective_width_m / occupancy。
    已存在的字段不覆盖（兼容外部覆盖配置）。
    """
    for _, _, _, data in G.edges(keys=True, data=True):
        hw = _normalize_highway(data.get('highway'))
        profile = HIGHWAY_PROFILES.get(hw, DEFAULT_PROFILE)
        for key, val in profile.items():
            data.setdefault(key, val)
        data.setdefault('occupancy', 0)
    return G


def build_and_cache(city, district=None, network_type='walk', place_query=None):
    """从 OSM 下载、标注、缓存为 graphml。

    Args:
        city: e.g. '厦门市' / 'Xiamen'
        district: e.g. '思明区' / None (= 整个城市)
        network_type: osmnx 网络类型，默认 'walk' (适合疏散仿真)
        place_query: 自定义 Nominatim 查询字符串；默认 f"{city}{district}"

    Returns:
        networkx.MultiDiGraph
    """
    os.makedirs(ROAD_GRAPH_CACHE_DIR, exist_ok=True)
    if place_query is None:
        place_query = f"{city}{district}" if district else city

    print(f"[road_graph] Downloading OSM '{place_query}' (network_type={network_type})...")
    G = ox.graph_from_place(place_query, network_type=network_type)
    annotate_edges(G)

    cache_path = _cache_filename(city, district)
    print(f"[road_graph] Saving graphml -> {cache_path}")
    ox.io.save_graphml(G, cache_path)
    print(f"[road_graph] Done. nodes={len(G.nodes)}, edges={len(G.edges)}")
    return G


def load_or_build(city, district=None, network_type='walk',
                  place_query=None, force_rebuild=False):
    """优先读 cache 的 graphml；不存在或 force_rebuild=True 时调 osmnx 下载。

    返回的图 edge 属性中数值字段已统一成 float。
    """
    cache_path = _cache_filename(city, district)
    if not force_rebuild and os.path.exists(cache_path):
        print(f"[road_graph] Loading cached graph: {cache_path}")
        G = ox.io.load_graphml(cache_path)
        _coerce_numeric_fields(G)
        print(f"[road_graph] Loaded. nodes={len(G.nodes)}, edges={len(G.edges)}")
        return G
    return build_and_cache(city, district, network_type=network_type,
                           place_query=place_query)


# =============================================================================
# M2: agent ↔ graph 绑定辅助
# =============================================================================
def snap_to_node(G, x, y):
    """把经纬度坐标 (x=lon, y=lat) 落到最近的 graph node。

    薄包装 ox.distance.nearest_nodes，单点调用；批量场景请直接传 list 给 osmnx。

    Args:
        G: networkx.MultiDiGraph
        x: 经度 (lon)
        y: 纬度 (lat)

    Returns:
        int: 最近节点的 OSM id
    """
    return int(ox.distance.nearest_nodes(G, X=x, Y=y))


def snap_to_nodes_batch(G, xs, ys):
    """批量 snap (推荐用于初始化阶段一次性把所有 agent 落到节点上)。

    Args:
        G: networkx.MultiDiGraph
        xs: list/array of lon
        ys: list/array of lat

    Returns:
        list[int]: 每个点对应的最近节点 id
    """
    nids = ox.distance.nearest_nodes(G, X=list(xs), Y=list(ys))
    return [int(n) for n in nids]


def node_xy(G, node_id):
    """获取节点的 (lon, lat) 坐标"""
    nd = G.nodes[node_id]
    return float(nd['x']), float(nd['y'])


# =============================================================================
# 自测
# =============================================================================
if __name__ == '__main__':
    G = load_or_build('厦门市', '思明区')
    print(f"\n[smoke-test] nodes={len(G.nodes)}, edges={len(G.edges)}")
    # 抽样检查 edge 属性
    for u, v, k, data in list(G.edges(keys=True, data=True))[:3]:
        print(f"  edge {u}->{v}: hw={data.get('highway')}, "
              f"cap={data.get('capacity_per_step')}, "
              f"v0={data.get('free_flow_speed')}, "
              f"len={data.get('length'):.1f}m")
