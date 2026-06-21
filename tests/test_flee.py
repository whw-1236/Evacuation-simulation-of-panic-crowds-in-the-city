# -*- coding: utf-8 -*-
"""T26 验证：flee 行为正确触发, target_node 覆盖为最近 shelter。"""
import sys
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from core.agents import ResidentAgent
from core.behavior_switching import compute_goal_direction, SwitchParams, init_store_state


def _make(stress, has_shelter=True):
    a = ResidentAgent()
    a.x, a.y = 118.10, 24.48
    a.home_position = (118.10, 24.48)
    a.home_node = 'HOME_X'
    a.current_node = 'CUR'
    a.stress_level = stress
    a.personal_supply = 0.5
    a.pts_status = False
    a.neighbors = []
    a.state = 'S'
    if has_shelter:
        a.nearest_shelter_node = 'SHELTER_A'
        a.nearest_shelter_xy = (118.12, 24.49)
    return a


p = SwitchParams()
stores = [{'id': 's0', 'x': 118.11, 'y': 24.48,
           'capacity': 2, 'occupancy': 0, 'node_id': 'STORE_0'}]

# ---- Scenario 1: 低压力 + 有 shelter -> home (flee 不触发) ----
a = _make(stress=0.3)
init_store_state(a, stores, p)
d = compute_goal_direction(a, stores, a.neighbors, p)
print(f"S1 stress=0.3 (低)        : dom={a._dom_action}  target={a.target_node}")
assert a._dom_action == 'home', f'低压力应为 home, got {a._dom_action}'

# ---- Scenario 2: 高压力 (= flee 阈值 0.6) -> 边界 ----
a = _make(stress=0.6)
init_store_state(a, stores, p)
d = compute_goal_direction(a, stores, a.neighbors, p)
print(f"S2 stress=0.60 (=阈值)    : dom={a._dom_action}  target={a.target_node}")
# 0.60 不严格 > 0.6, 所以不触发 flee

# ---- Scenario 3: 极高压力 + 有 shelter -> flee ----
a = _make(stress=0.85)
init_store_state(a, stores, p)
d = compute_goal_direction(a, stores, a.neighbors, p)
print(f"S3 stress=0.85 (高) + shelter : dom={a._dom_action}  target={a.target_node}  dir≈({d[0]:.2f},{d[1]:.2f})")
assert a._dom_action == 'flee', f'高压力+shelter 应为 flee, got {a._dom_action}'
assert a.target_node == 'SHELTER_A', f'target 应为 SHELTER_A, got {a.target_node}'
# 方向应朝 shelter (从 118.10,24.48 → 118.12,24.49), dx>0 dy>0
assert d[0] > 0 and d[1] > 0, f'方向应朝东北, got {d}'

# ---- Scenario 4: 极高压力但无 shelter -> herd (fallback) ----
a = _make(stress=0.85, has_shelter=False)
init_store_state(a, stores, p)
d = compute_goal_direction(a, stores, a.neighbors, p)
print(f"S4 stress=0.85, 无 shelter : dom={a._dom_action}  target={a.target_node}")
assert a._dom_action != 'flee', '无 shelter 时不应 flee'

# ---- Scenario 5: 关闭 flee 开关 -> 即使高压力也不 flee ----
p_off = SwitchParams(enable_flee_behavior=False)
a = _make(stress=0.85)
init_store_state(a, stores, p_off)
d = compute_goal_direction(a, stores, a.neighbors, p_off)
print(f"S5 开关 OFF stress=0.85 : dom={a._dom_action}  target={a.target_node}")
assert a._dom_action != 'flee', '开关关闭后不应 flee'

print('\n[OK] T26 flee 行为全部通过')
