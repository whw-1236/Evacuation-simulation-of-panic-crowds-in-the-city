# -*- coding: utf-8 -*-
"""T26 smoke checks: flee behavior and shelter target routing."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core.agents import ResidentAgent
from core.behavior_switching import SwitchParams, compute_goal_direction, init_store_state


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


def run_checks():
    p = SwitchParams()
    stores = [{"id": "s0", "x": 118.11, "y": 24.48,
               "capacity": 2, "occupancy": 0, "node_id": "STORE_0"}]

    # ---- Scenario 1: low stress + shelter -> home ----
    a = _make(stress=0.3)
    init_store_state(a, stores, p)
    d = compute_goal_direction(a, stores, a.neighbors, p)
    print(f"S1 stress=0.3 (low)        : dom={a._dom_action}  target={a.target_node}")
    assert a._dom_action == "home", f"low stress should choose home, got {a._dom_action}"

    # ---- Scenario 2: MNL boundary check, not a hard theta trigger ----
    a = _make(stress=0.6)
    init_store_state(a, stores, p)
    d = compute_goal_direction(a, stores, a.neighbors, p)
    print(f"S2 stress=0.60 (MNL)       : dom={a._dom_action}  target={a.target_node}")
    assert a._dom_action == "flee", f"MNL dominant action should be flee, got {a._dom_action}"
    assert a.target_node == "SHELTER_A", f"target should be SHELTER_A, got {a.target_node}"

    # ---- Scenario 3: very high stress + shelter -> flee ----
    a = _make(stress=0.85)
    init_store_state(a, stores, p)
    d = compute_goal_direction(a, stores, a.neighbors, p)
    print(f"S3 stress=0.85 (high) + shelter : dom={a._dom_action}  target={a.target_node}  dir≈({d[0]:.2f},{d[1]:.2f})")
    assert a._dom_action == "flee", f"high stress+shelter should choose flee, got {a._dom_action}"
    assert a.target_node == "SHELTER_A", f"target should be SHELTER_A, got {a.target_node}"
    assert d[0] > 0 and d[1] > 0, f"direction should point northeast, got {d}"

    # ---- Scenario 4: very high stress but no shelter -> no flee ----
    a = _make(stress=0.85, has_shelter=False)
    init_store_state(a, stores, p)
    d = compute_goal_direction(a, stores, a.neighbors, p)
    print(f"S4 stress=0.85, no shelter : dom={a._dom_action}  target={a.target_node}")
    assert a._dom_action != "flee", "without shelter, flee should be unavailable"

    # ---- Scenario 5: flee switch off -> no flee even at high stress ----
    p_off = SwitchParams(enable_flee_behavior=False)
    a = _make(stress=0.85)
    init_store_state(a, stores, p_off)
    d = compute_goal_direction(a, stores, a.neighbors, p_off)
    print(f"S5 switch OFF stress=0.85 : dom={a._dom_action}  target={a.target_node}")
    assert a._dom_action != "flee", "when switch is off, flee should be unavailable"

    print("\n[OK] T26 flee behavior smoke checks passed")


if __name__ == "__main__":
    run_checks()
