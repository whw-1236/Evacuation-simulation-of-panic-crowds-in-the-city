# -*- coding: utf-8 -*-
"""
================================================================================
路径规划模块 — congestion-aware Dijkstra + 动态重路由
================================================================================
功能：
    1. plan_path(G, src, tgt)     congestion-aware Dijkstra
    2. should_replan(agent, ...)  判定 agent 是否需要重路由
    3. replan(agent, G)           执行重路由，写回 agent.current_path
    4. next_node(agent)           取路径上的下一节点（给 movement layer 用）

权重设计（congestion-aware）:
    w(edge) = length × (1 + α · congestion_ratio)
    congestion_ratio = min(1.0, occupancy / capacity_per_step)

动态重路由触发条件（4 选 1）:
    - force=True (外部强制)
    - agent.current_path 为空
    - agent.target_node ≠ agent._last_target_node (语义目标变了)
    - distance 上次 replan 已 ≥ REPLAN_EVERY_STEPS 步

接口约定:
    - 不直接动 graph 的 occupancy（那是 movement_layer 的事）
    - 不直接读 SwitchParams / σ；I1 提前写好 target_node 后调本模块
================================================================================
"""
import networkx as nx

# 调整阈值放这里方便集中调
REPLAN_EVERY_STEPS = 25          # 动态重路由间隔（步）
CONGESTION_WEIGHT_ALPHA = 2.0    # w = length × (1 + α·congestion_ratio)
_EFFECTIVE_WEIGHT_KEY = 'effective_weight'


# =============================================================================
# 内部：把当前 graph occupancy 折算到 effective_weight
# =============================================================================
def annotate_effective_weights(G, alpha=CONGESTION_WEIGHT_ALPHA):
    """把每条 edge 当前的拥堵折算到 effective_weight 字段。

    设计选择：一次 O(E) 标注，再用字符串 weight 调 shortest_path。
    比 weight=callable 在 MultiDiGraph 上更可控。
    """
    for _, _, _, d in G.edges(keys=True, data=True):
        length = float(d.get('length', 1.0))
        occ = float(d.get('occupancy', 0))
        cap = float(d.get('capacity_per_step', 1))
        cong = min(1.0, occ / cap) if cap > 0 else 0.0
        d[_EFFECTIVE_WEIGHT_KEY] = length * (1.0 + alpha * cong)


# =============================================================================
# Public: 路径规划
# =============================================================================
def plan_path(G, source, target, alpha=CONGESTION_WEIGHT_ALPHA):
    """congestion-aware Dijkstra: source -> target。

    Args:
        G: networkx.MultiDiGraph (road_graph)
        source, target: OSM node id
        alpha: 拥堵权重系数

    Returns:
        list[int] | None: 节点序列；不可达返回 None；source==target 返回 [source]
    """
    if source is None or target is None:
        return None
    if source == target:
        return [source]
    try:
        annotate_effective_weights(G, alpha=alpha)
        return list(nx.shortest_path(
            G, source=source, target=target,
            weight=_EFFECTIVE_WEIGHT_KEY,
        ))
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None


# =============================================================================
# Public: 动态重路由判定 + 执行
# =============================================================================
def should_replan(agent, force=False, every=REPLAN_EVERY_STEPS):
    """4 选 1：是否触发重路由。"""
    if force:
        return True
    path = getattr(agent, 'current_path', None) or []
    if not path:
        return True
    if getattr(agent, 'target_node', None) != getattr(agent, '_last_target_node', None):
        return True
    if getattr(agent, '_steps_since_replan', 0) >= every:
        return True
    return False


def replan(agent, G, alpha=CONGESTION_WEIGHT_ALPHA):
    """重路由：调 plan_path，写回 agent.current_path/path_progress/_steps_since_replan。

    Returns:
        list[int]: 新的 path (可能只含一个节点 = 留在原地)
    """
    src = getattr(agent, 'current_node', None)
    tgt = getattr(agent, 'target_node', None)

    if src is None:
        agent.current_path = []
        agent.path_progress = 0
    elif tgt is None or src == tgt:
        agent.current_path = [src]
        agent.path_progress = 0
    else:
        path = plan_path(G, src, tgt, alpha=alpha)
        agent.current_path = path if path else [src]
        agent.path_progress = 0

    agent._steps_since_replan = 0
    agent._last_target_node = tgt
    return agent.current_path


# =============================================================================
# Public: 取路径上的下一节点
# =============================================================================
def next_node(agent):
    """agent 当前应该前往的节点 (path[path_progress + 1])，到尾返回终点。"""
    path = getattr(agent, 'current_path', None) or []
    if not path:
        return None
    idx = getattr(agent, 'path_progress', 0)
    nxt = idx + 1
    if nxt < len(path):
        return path[nxt]
    return path[-1]


def advance_progress(agent):
    """agent 抵达 next_node 时调用：path_progress += 1。"""
    path = getattr(agent, 'current_path', None) or []
    if not path:
        return
    if agent.path_progress < len(path) - 1:
        agent.path_progress += 1


# =============================================================================
# 路径追踪：每步给 agent 更新 _next_node_xy / current_edge
# =============================================================================
def path_follow_step(agent, G, arrival_threshold_deg=0.0002):
    """每步路径追踪 (给 social_force 提供方向 + 给 movement_layer 提供 edge)。

    步骤:
      1. 检查 agent 是否到达 path[path_progress+1]: 经纬度距离 < 阈值
         -> path_progress += 1, current_node = next
      2. 重新取下下个节点作为新的 next_node
      3. 缓存 agent._next_node_xy = (lon, lat) 用于 social_force.driving_force
      4. 缓存 agent.current_edge = (current_node, next_node, k) 用于 occupancy

    阈值 ~0.0002° 约 22m, 是步行 ~15s 路程。
    """
    import math
    from core.road_graph import node_xy

    path = getattr(agent, 'current_path', None) or []
    if not path:
        agent._next_node_xy = None
        agent.current_edge = None
        return

    nxt_idx = agent.path_progress + 1

    # 1. 到达判定
    if nxt_idx < len(path):
        nxt = path[nxt_idx]
        try:
            nxt_x, nxt_y = node_xy(G, nxt)
        except KeyError:
            agent._next_node_xy = None
            agent.current_edge = None
            return
        if math.hypot(agent.x - nxt_x, agent.y - nxt_y) < arrival_threshold_deg:
            agent.path_progress = nxt_idx
            agent.current_node = nxt
            nxt_idx += 1

    # 2. 重新取 next
    if nxt_idx < len(path):
        nxt = path[nxt_idx]
        try:
            nxt_x, nxt_y = node_xy(G, nxt)
        except KeyError:
            agent._next_node_xy = None
            agent.current_edge = None
            return
        agent._next_node_xy = (nxt_x, nxt_y)
        # current_edge: MultiDiGraph 取第一个 key
        try:
            ed = G[agent.current_node][nxt]
            k = next(iter(ed.keys()))
            agent.current_edge = (agent.current_node, nxt, k)
        except (KeyError, StopIteration):
            agent.current_edge = None
    else:
        # 已到终点
        agent._next_node_xy = None
        agent.current_edge = None


# =============================================================================
# 自测
# =============================================================================
if __name__ == '__main__':
    # 用 networkx 构造一个简单方格图测试
    G = nx.MultiDiGraph()
    for i in range(4):
        for j in range(4):
            G.add_node((i, j), x=float(i), y=float(j))
    for i in range(4):
        for j in range(4):
            if i + 1 < 4:
                G.add_edge((i, j), (i + 1, j),
                           length=100.0, capacity_per_step=10, occupancy=0)
                G.add_edge((i + 1, j), (i, j),
                           length=100.0, capacity_per_step=10, occupancy=0)
            if j + 1 < 4:
                G.add_edge((i, j), (i, j + 1),
                           length=100.0, capacity_per_step=10, occupancy=0)
                G.add_edge((i, j + 1), (i, j),
                           length=100.0, capacity_per_step=10, occupancy=0)

    print('Test 1: 从 (0,0) 到 (3,3) 自由流')
    path = plan_path(G, (0, 0), (3, 3))
    print(f'  path 长度 = {len(path)}, 头尾 = {path[0]} -> {path[-1]}')

    print('Test 2: (1,0)-(2,0) 堵满 + α=8，从 (0,0) 到 (3,0) 应绕路')
    for u, v, k, d in G.edges(keys=True, data=True):
        if u == (1, 0) and v == (2, 0):
            d['occupancy'] = 10  # 满
    path2 = plan_path(G, (0, 0), (3, 0), alpha=8.0)
    print(f'  路径 = {path2}')
    assert (1, 0) not in path2 or (2, 0) not in path2 or \
           ((1, 0) in path2 and (2, 0) in path2
            and path2.index((1, 0)) + 1 != path2.index((2, 0))), \
        '应当绕开拥堵段'
    print('  [OK] 算法成功绕开拥堵段')

    print('Test 3: should_replan + replan')
    class A:
        current_node = (0, 0)
        target_node = (3, 3)
        current_path = []
        _last_target_node = None
        _steps_since_replan = 0
        path_progress = 0
    a = A()
    print(f'  初始 should_replan={should_replan(a)}')
    replan(a, G)
    print(f'  replan 后 path 长度={len(a.current_path)}')
    print(f'  next_node={next_node(a)}')
