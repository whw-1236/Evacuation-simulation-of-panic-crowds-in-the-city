# -*- coding: utf-8 -*-
"""
================================================================================
路网运动层 — edge occupancy + Greenshields 速度衰减 + node 软队列
================================================================================
功能：
    1. 跟踪 edge 当前 occupancy（每 agent 占用一份）
    2. 计算 edge 拥堵率 = occupancy / capacity_per_step
    3. Greenshields 速度衰减：v = v0 × (1 - ρ/ρ_jam)  软约束（不卡死）
    4. node 软排队负载估算（给 social_force / σ 反馈用）
    5. 每步综合更新：先衰减再按 agent 当前 edge 累加

接口给上层用：
    - get_edge_congestion(G, u, v, k)        edge 拥堵率 ∈ [0, 1]
    - speed_factor(congestion)               速度倍数 ∈ [0.1, 1.0]
    - get_node_load(G, node_id)              节点负载 ∈ [0, 1]
    - occupancy_update_step(G, agents)       每步调用

设计原则：
    - 软约束：congestion=1 时速度 → 10%（不归零，防死锁）
    - occupancy 每步指数衰减（默认 0.5），防止单调累积
    - agent.current_edge = (u, v, k) tuple 或 None，由 social_force 维护
================================================================================
"""

# Greenshields 拥堵率到 v→0 的临界值
DEFAULT_JAM_RATIO = 0.9
# 每步 occupancy 衰减系数（保留多少给下步）
DEFAULT_OCC_DECAY = 0.5
# 最低速度倍数（防止死锁）
MIN_SPEED_FACTOR = 0.10


# =============================================================================
# Edge 级查询
# =============================================================================
def _first_edge_data(G, u, v, k=None):
    """取 u-v 之间的 edge 数据 (MultiDiGraph 可能多重边)。"""
    if not G.has_edge(u, v):
        return None
    edge_dict = G[u][v]
    if k is not None and k in edge_dict:
        return edge_dict[k]
    return next(iter(edge_dict.values())) if edge_dict else None


def get_edge_congestion(G, u, v, k=None):
    """edge 拥堵率 = occupancy / capacity_per_step, clamp [0, 1]."""
    d = _first_edge_data(G, u, v, k)
    if not d:
        return 0.0
    cap = float(d.get('capacity_per_step', 1))
    occ = float(d.get('occupancy', 0))
    return min(1.0, occ / cap) if cap > 0 else 0.0


# =============================================================================
# Greenshields 速度衰减（软约束）
# =============================================================================
def speed_factor(congestion_ratio, jam_ratio=DEFAULT_JAM_RATIO,
                 min_factor=MIN_SPEED_FACTOR):
    """Greenshields: v = v0 × (1 - ρ/ρ_jam), clamp [min_factor, 1.0]。

    congestion_ratio ∈ [0,1]
    jam_ratio = 拥堵率达到该值时速度衰减最严重
    返回速度倍数 ∈ [min_factor, 1.0]，永不归零（防止死锁）
    """
    if congestion_ratio <= 0:
        return 1.0
    factor = 1.0 - congestion_ratio / jam_ratio
    return max(min_factor, min(1.0, factor))


def edge_speed_factor(G, u, v, k=None, jam_ratio=DEFAULT_JAM_RATIO):
    """语法糖: 直接拿 edge 的 (拥堵, 速度倍数)。"""
    cong = get_edge_congestion(G, u, v, k)
    return cong, speed_factor(cong, jam_ratio=jam_ratio)


# =============================================================================
# Node 级负载（软队列）
# =============================================================================
def get_node_load(G, node_id):
    """节点负载 = 入边 occupancy 总和 / 入边 capacity 总和。

    软排队的核心：节点不真排队（不阻塞 agent），但负载高时下游 throughput
    自动降低（因为 incoming edges 的 occupancy 反映等待人数）。

    Returns: float ∈ [0, 1]
    """
    if not G.has_node(node_id):
        return 0.0
    # MultiDiGraph: in_edges (有向); MultiGraph: edges
    try:
        in_edges = list(G.in_edges(node_id, data=True, keys=True))
    except Exception:
        in_edges = [(u, v, k, d) for u, v, k, d in G.edges(node_id, data=True, keys=True)]
    if not in_edges:
        return 0.0
    total_occ = sum(float(d.get('occupancy', 0)) for *_, d in in_edges)
    total_cap = sum(float(d.get('capacity_per_step', 1)) for *_, d in in_edges)
    return min(1.0, total_occ / total_cap) if total_cap > 0 else 0.0


# =============================================================================
# Occupancy 更新（每步）
# =============================================================================
def decay_all_occupancy(G, decay_rate=DEFAULT_OCC_DECAY):
    """每步衰减所有 edge 的 occupancy（指数衰减，防止单调累积）。"""
    for _, _, _, d in G.edges(keys=True, data=True):
        d['occupancy'] = float(d.get('occupancy', 0)) * decay_rate


def _increment_edge(G, u, v, k=None, delta=1):
    d = _first_edge_data(G, u, v, k)
    if d is not None:
        d['occupancy'] = max(0.0, float(d.get('occupancy', 0)) + delta)


def occupancy_update_step(G, agents, decay_rate=DEFAULT_OCC_DECAY):
    """每步综合更新：先指数衰减，再按 agent.current_edge 累加 +1。

    agents: iterable, 每个 agent 期望有 .current_edge = (u,v,k) or None
    """
    decay_all_occupancy(G, decay_rate)
    for a in agents:
        ce = getattr(a, 'current_edge', None)
        if ce is None:
            continue
        try:
            if len(ce) == 3:
                u, v, k = ce
            elif len(ce) == 2:
                u, v = ce
                k = None
            else:
                continue
        except TypeError:
            continue
        _increment_edge(G, u, v, k, delta=1)


# =============================================================================
# 自测
# =============================================================================
if __name__ == '__main__':
    import networkx as nx

    G = nx.MultiDiGraph()
    G.add_node('A', x=0, y=0)
    G.add_node('B', x=1, y=0)
    G.add_node('C', x=2, y=0)
    G.add_edge('A', 'B', length=100, capacity_per_step=10, occupancy=0)
    G.add_edge('B', 'C', length=100, capacity_per_step=10, occupancy=0)

    print('Test 1: 自由流 (occ=0)')
    print(f'  congestion A->B = {get_edge_congestion(G, "A", "B"):.2f}')
    print(f'  speed_factor   = {speed_factor(0):.2f}  (应为 1.0)')

    print('Test 2: 半饱和 (occ=5/10)')
    next(iter(G["A"]["B"].values()))['occupancy'] = 5
    cong = get_edge_congestion(G, "A", "B")
    print(f'  congestion = {cong:.2f}')
    print(f'  speed_factor = {speed_factor(cong):.2f}  (应 ≈ 0.44)')

    print('Test 3: 严重拥堵 (occ=10/10)')
    next(iter(G["A"]["B"].values()))['occupancy'] = 10
    cong = get_edge_congestion(G, "A", "B")
    print(f'  congestion = {cong:.2f}')
    print(f'  speed_factor = {speed_factor(cong):.2f}  (应 ≈ 0.1 即 min)')

    print('Test 4: 节点负载 B = 入边 A->B occ / cap = 10/10 = 1.0')
    print(f'  get_node_load(B) = {get_node_load(G, "B"):.2f}')

    print('Test 5: occupancy_update_step (decay 0.5 + 1 agent on A->B)')
    class A:
        current_edge = ('A', 'B', 0)
    occupancy_update_step(G, [A()])
    occ = next(iter(G["A"]["B"].values()))['occupancy']
    print(f'  A->B occ after decay+inc: {occ:.2f}  (应 = 10*0.5 + 1 = 6.0)')
