# -*- coding: utf-8 -*-
"""
behavior_switching.py
=====================================================================
Paper innovations I1 / I2 / I3 for the blackout crowd model.
Maps directly to Methodology Eqs. (10)-(16).

  I1  compute_goal_direction       Eqs. (10)-(12)  sigmoid soft-switch home/hoard/herd
  I2  store_utility / choose_store  Eq.  (13)       familiarity-aware selection
      update_perceived_occupancy    Eq.  (14)       acquaintance-network gossip
      attempt_acquire                              capacity-based runs (replaces random())
  I3  leader_score / update_leader  Eqs. (15)-(16)  inertial leader + in-group bias

This module is pure logic; it reads attributes that already exist on your
ResidentAgent (x, y, emotion, pts_status, personal_supply, home_position,
neighbors) plus three new per-agent dicts you initialise once (see step 6).

---------------------------------------------------------------------
INTEGRATION GUIDE (7 steps) — search your code for the marked spots
---------------------------------------------------------------------
1. STORES. Load your existing shop data as a list of dicts:
       stores = [{'id': 's0', 'x': lon, 'y': lat, 'capacity': 50, 'occupancy': 0}, ...]
   Keep it on the SocialForceModel (self.stores = stores) and/or the agent.
   (Your CSV nodes already use lon/lat + capacity fields, so reuse that loader.)

2. DRIVING FORCE (I1). In SocialForceModel.calculate_driving_force, REPLACE the
   heuristic "wander target" block with the goal direction:
       e_i0 = compute_goal_direction(agent, self.stores, agent.neighbors, self.sw)
       if e_i0 == (0.0, 0.0):           # calm + supplied + no leader -> idle near home
           e_i0 = _unit(home[0]-agent.x, home[1]-agent.y)
       desired_velocity = desired_speed * np.array(e_i0)
       driving_force = mass * (desired_velocity - current_velocity) / self.tau
   Drop the ad-hoc *5.0 / *2.0 gains and recalibrate desired_speed instead.

3. PERCEIVED OCCUPANCY (I2). Once per step, before direction is computed
   (e.g. top of IntegratedForceCalculator.update's per-agent loop):
       update_perceived_occupancy(agent, stores, agent.sw)

4. HERDING (I3). The herd goal is now INSIDE compute_goal_direction (toward the
   leader). Remove or strongly down-weight _calculate_cluster_force so herding is
   not double-counted (keep at most a small personal-space repulsion).

5. ACQUISITION. In ResidentAgent.step, REPLACE
       self.hoarding_success = random.random() < rate
   with capacity-based acquisition when the agent has reached its target store:
       if agent_reached_store:
           attempt_acquire(self, target_store)   # sets hoarding_success, just_hoarded

6. INIT (once per agent, after stores exist):
       init_store_state(agent, stores, agent.sw)   # familiarity + perceived_occupancy
       agent.current_leader = None
   Also give each agent a params handle: agent.sw = SwitchParams() (shared is fine).

7. METRICS (for the experiment matrix):
       share_home/hoard/herd  <- agent._goal_shares   (set inside compute_goal_direction)
       leader_switch_rate     <- count changes of agent.current_leader
       Gini_occ               <- from stores' occupancy
   Ablation knobs (one per E2 row):
       hard-switch (E2.2): sw.k1=k2=k3=k4 = 50  (large => hard threshold)
       no info-net (E2.3): skip step 3 AND set sw.lambda_c = 0.0
       no inertia  (E2.4): sw.mu = 1.0
=====================================================================
"""

import math
from dataclasses import dataclass

try:
    import numpy as np
except Exception:  # numpy optional; tuples are used everywhere internally
    np = None


@dataclass
class SwitchParams:
    # --- I1: stage thresholds & sigmoid steepness (Eq. 11) ---
    theta1: float = 0.4          # home -> hoard breakpoint
    theta2: float = 0.6          # hoard -> herd breakpoint
    k1: float = 10.0
    k2: float = 10.0
    k3: float = 10.0
    k4: float = 10.0
    lambda_pts: float = 2.0      # PTS reinforcement of herd weight
    supply_threshold: float = 0.35   # H_i gate: personal_supply below this -> need resources

    # --- I2: store utility (Eq. 13) ---
    lambda_d: float = 0.5
    lambda_f: float = 0.3
    lambda_c: float = 0.4
    dist_scale: float = 0.01     # normalises lon/lat distance (~1 km) so terms are comparable
    gamma: float = 0.3           # perceived-occupancy learning rate (Eq. 14)
    fam_scale: float = 0.005     # familiarity decay length (~500 m) for initialisation
    arrival_radius: float = 0.0005   # within this distance the agent is "at" the store

    # --- I3: leader score & inertia (Eqs. 15-16) ---
    mu: float = 1.3              # hysteresis margin (>1). mu=1 -> re-select every step
    alpha_s: float = 0.5         # weight on emotional stability
    alpha_f: float = 0.3         # weight on in-group familiarity
    alpha_v: float = 0.2         # weight on visibility

    eps: float = 1e-9


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-max(-50.0, min(50.0, x))))


def _unit(vx, vy):
    n = math.hypot(vx, vy)
    if n < 1e-12:
        return (0.0, 0.0)
    return (vx / n, vy / n)


def _dist(ax, ay, bx, by):
    return math.hypot(ax - bx, ay - by)


# --------------------------------------------------------------------------
# I2 — acquaintance-network store selection
# --------------------------------------------------------------------------
def init_store_state(agent, stores, p):
    """Step 6: initialise familiarity (decays with home distance) and beliefs."""
    home = getattr(agent, 'home_position', (agent.x, agent.y))
    agent.familiarity = {}
    agent.perceived_occupancy = {}
    for s in stores:
        d = _dist(home[0], home[1], s['x'], s['y'])
        agent.familiarity[s['id']] = math.exp(-d / max(p.fam_scale, 1e-9))
        agent.perceived_occupancy[s['id']] = 0.0


def _real_occupancy_norm(s):
    cap = max(1.0, float(s.get('capacity', 1)))
    return min(1.0, float(s.get('occupancy', 0)) / cap)


def store_utility(agent, s, p):
    """Eq. (13): U_i(s) = -lambda_d * d_norm + lambda_f * f - lambda_c * o_hat."""
    d_norm = _dist(agent.x, agent.y, s['x'], s['y']) / max(p.dist_scale, 1e-9)
    f = agent.familiarity.get(s['id'], 0.0)
    o_hat = agent.perceived_occupancy.get(s['id'], 0.0)
    return -p.lambda_d * d_norm + p.lambda_f * f - p.lambda_c * o_hat


def choose_store(agent, stores, p):
    """s* = argmax_s U_i(s)."""
    if not stores:
        return None
    return max(stores, key=lambda s: store_utility(agent, s, p))


def update_perceived_occupancy(agent, stores, p):
    """Eq. (14): gossip over familiar neighbours who are currently AT a store.

    Requires that an agent at store s carries `agent._at_store_id = s['id']`
    (set in attempt_acquire / when it reaches a store), else None.
    """
    neighbors = getattr(agent, 'neighbors', [])
    for s in stores:
        observers = [n for n in neighbors
                     if getattr(n, '_at_store_id', None) == s['id']]
        if not observers:
            continue
        observed = _real_occupancy_norm(s)   # all observers report the same real value
        prev = agent.perceived_occupancy.get(s['id'], 0.0)
        agent.perceived_occupancy[s['id']] = (1.0 - p.gamma) * prev + p.gamma * observed


def attempt_acquire(agent, store):
    """Step 5: capacity-based acquisition (replaces hoarding_success = random()).

    Success iff the store is below capacity; occupancy increments so that
    crowding produces self-reinforcing runs.
    """
    agent._at_store_id = store['id']
    agent.hoarding_attempts = getattr(agent, 'hoarding_attempts', 0) + 1
    if store.get('occupancy', 0) < store.get('capacity', 1):
        store['occupancy'] = store.get('occupancy', 0) + 1
        agent.hoarding_success = True
        agent.just_hoarded = True
    else:
        agent.hoarding_failures = getattr(agent, 'hoarding_failures', 0) + 1
        agent.hoarding_success = False
        agent.just_hoarded = False
    return agent.hoarding_success


# --------------------------------------------------------------------------
# I3 — leader selection with inertia and in-group bias
# --------------------------------------------------------------------------
def _familiarity_between(agent, j):
    """In-group bias: members of the fixed social circle are 'familiar'."""
    return 1.0 if j in getattr(agent, 'neighbors', []) else 0.0


def leader_score(agent, j, p, in_cone=True):
    """Eq. (15)."""
    stability = 1.0 - getattr(j, 'emotion', 0.0)
    fam = _familiarity_between(agent, j)
    vis = 1.0 if in_cone else 0.0
    return p.alpha_s * stability + p.alpha_f * fam + p.alpha_v * vis


def update_leader(agent, neighbors, p):
    """Eq. (16): keep current leader unless a challenger beats it by margin mu."""
    candidates = [j for j in neighbors if j is not agent]
    if not candidates:
        return getattr(agent, 'current_leader', None)

    j_star = max(candidates, key=lambda j: leader_score(agent, j, p))
    best = leader_score(agent, j_star, p)

    cur = getattr(agent, 'current_leader', None)
    if cur is None or cur not in candidates:
        agent.current_leader = j_star
    else:
        if best > p.mu * leader_score(agent, cur, p):
            agent.current_leader = j_star
    return agent.current_leader


# --------------------------------------------------------------------------
# I1 — emotion-driven multi-stage goal switching
# --------------------------------------------------------------------------
def compute_goal_direction(agent, stores, neighbors, p):
    """Eqs. (10)-(12): sigmoid-weighted blend of home / hoard / herd directions.

    Reads the agent's existing scalar arousal `emotion` (E), `pts_status` (Z),
    and `personal_supply` (for the resource-need gate H). Returns a unit vector
    (dx, dy); also writes agent._goal_shares = (w_home, w_hoard, w_herd) for metrics.
    """
    E = float(getattr(agent, 'stress_level', 0.0))
    Z = 1.0 if getattr(agent, 'pts_status', False) else 0.0
    H = 1.0 if float(getattr(agent, 'personal_supply', 1.0)) < p.supply_threshold else 0.0

    # --- candidate directions (Eq. 10) ---
    home = getattr(agent, 'home_position', (agent.x, agent.y))
    d_home = _unit(home[0] - agent.x, home[1] - agent.y)

    s_star = choose_store(agent, stores, p) if (stores and H > 0.0) else None
    agent._target_store = s_star            # so step 5 knows where the agent is headed
    d_hoard = _unit(s_star['x'] - agent.x, s_star['y'] - agent.y) if s_star else (0.0, 0.0)

    leader = update_leader(agent, neighbors, p)
    d_herd = _unit(leader.x - agent.x, leader.y - agent.y) if leader is not None else (0.0, 0.0)

    # --- sigmoid weights (Eq. 11) ---
    w_home = _sigmoid(-p.k1 * (E - p.theta1))
    w_hoard = H * _sigmoid(p.k2 * (E - p.theta1)) * _sigmoid(-p.k3 * (E - p.theta2))
    w_herd = _sigmoid(p.k4 * (E - p.theta2)) + p.lambda_pts * Z

    # --- normalise & combine (Eq. 12) ---
    W = w_home + w_hoard + w_herd + p.eps
    dx = (w_home * d_home[0] + w_hoard * d_hoard[0] + w_herd * d_herd[0]) / W
    dy = (w_home * d_home[1] + w_hoard * d_hoard[1] + w_herd * d_herd[1]) / W

    agent._goal_shares = (w_home / W, w_hoard / W, w_herd / W)
    return _unit(dx, dy)


# --------------------------------------------------------------------------
# tiny self-test (run `python behavior_switching.py`)
# --------------------------------------------------------------------------
if __name__ == "__main__":
    class A:  # minimal stub agent
        pass

    p = SwitchParams()
    stores = [{'id': 's0', 'x': 0.002, 'y': 0.0, 'capacity': 2, 'occupancy': 0},
              {'id': 's1', 'x': -0.003, 'y': 0.001, 'capacity': 2, 'occupancy': 0}]

    a = A(); a.x = a.y = 0.0; a.home_position = (0.0, 0.0)
    a.pts_status = False; a.personal_supply = 0.1; a.neighbors = []
    init_store_state(a, stores, p)

    for E in (0.1, 0.45, 0.8):
        a.emotion = E
        d = compute_goal_direction(a, stores, a.neighbors, p)
        wh, wo, we = a._goal_shares
        print(f"E={E:.2f}  shares home/hoard/herd = "
              f"{wh:.2f}/{wo:.2f}/{we:.2f}  dir={d[0]:+.2f},{d[1]:+.2f}")
    # Expect: E=0.1 home-dominated; E=0.45 hoard-dominated; E=0.8 herd-dominated.
