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

---------------------------------------------------------------------
I1 EXTENSIONS (2026-06-13) — four enhancements vs. I1 优化建议.md
---------------------------------------------------------------------
P1.A behavior-switch hysteresis band   (delta_hoard / delta_herd)
       hoarding 进入 σ≥θ₁ / 退出 σ<θ₁-δ_hoard
       herding  进入 σ≥θ₂ / 退出 σ<θ₂-δ_herd
       通过 agent._hoard_active / agent._herd_active 状态记忆实现。

P1.B outcome-feedback to σ            (apply_outcome_feedback)
       囤积成功 → σ -= delta_succ        囤积失败 → σ += delta_fail
       leader 成功疏散 → σ 轻度负脉冲    leader 陷入拥堵 → σ 正脉冲
       对应 Lazarus 应激-评估理论中的 secondary appraisal (再评估)。

P2  behavioral demonstration on θ      (adjust_effective_thresholds)
       θ₁_eff = θ₁ × mult - η × ratio_hoarding_neighbors
       θ₂_eff = θ₂ × mult - η × ratio_herding_neighbors
       η 由 OCEAN 宜人性 (Agreeableness) 调节。

P3  inquiry / information-seeking态     (w_inquire)
       σ ∈ [θ_mild, θ₁) 且 SEIR ∈ {S, E} 时激活；
       目标为最近信息节点 (广播站/邻居/聚集点)，否则小幅随机游走。

All four optimizations are gated by ablation switches on SwitchParams,
enable independent ablation in E2.x experiments.
=====================================================================
"""

import math
import random
from dataclasses import dataclass, field

try:
    import numpy as np
except Exception:  # numpy optional; tuples are used everywhere internally
    np = None


# =============================================================================
# Parameters
# =============================================================================
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

    # ---------------------------------------------------------------
    # P1.A — behavior switch hysteresis (NEW)
    # ---------------------------------------------------------------
    delta_hoard: float = 0.08    # σ < θ₁ - δ_hoard 才退出囤积态
    delta_herd: float = 0.10     # σ < θ₂ - δ_herd 才退出从众态
    enable_hysteresis: bool = True

    # ---------------------------------------------------------------
    # P1.B — outcome feedback on σ (NEW)
    # ---------------------------------------------------------------
    feedback_hoard_success: float = -0.07   # 囤积成功 -> σ 下降脉冲
    feedback_hoard_failure: float = +0.11   # 囤积失败 -> σ 上升脉冲
    feedback_herd_smooth:   float = -0.04   # 跟随Leader成功疏散 -> 轻度下降
    feedback_herd_jam:      float = +0.06   # 跟随Leader陷入拥堵 -> 上升
    feedback_failure_amplify_repeat: float = 0.2  # 连续失败累乘加成 (每次 +20%)
    enable_outcome_feedback: bool = True

    # ---------------------------------------------------------------
    # P2 — behavioral demonstration (θ pull-down by neighbour ratio)
    # ---------------------------------------------------------------
    eta_demo_hoard: float = 0.12   # θ₁_eff = θ₁ × mult - η · ratio_hoard_neighbors
    eta_demo_herd:  float = 0.15
    enable_behavior_demo: bool = True

    # ---------------------------------------------------------------
    # P3 — inquiry / information-seeking fourth state
    # ---------------------------------------------------------------
    theta_mild:        float = 0.2    # σ 进入 inquiry 态的下边界
    k5:                float = 10.0   # inquire sigmoid 陡度
    inquire_radius:    float = 0.01   # 默认信息搜寻半径 (~1 km)
    enable_inquire:    bool = False   # 默认关闭，避免破坏既有 baseline

    eps: float = 1e-9


# =============================================================================
# helpers
# =============================================================================
def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-max(-50.0, min(50.0, x))))


def _unit(vx, vy):
    n = math.hypot(vx, vy)
    if n < 1e-12:
        return (0.0, 0.0)
    return (vx / n, vy / n)


def _dist(ax, ay, bx, by):
    return math.hypot(ax - bx, ay - by)


# =============================================================================
# I2 — acquaintance-network store selection
# =============================================================================
def init_store_state(agent, stores, p):
    """初始化 familiarity + perceived_occupancy + 行为状态记忆。"""
    home = getattr(agent, 'home_position', (agent.x, agent.y))
    agent.familiarity = {}
    agent.perceived_occupancy = {}
    for s in stores:
        d = _dist(home[0], home[1], s['x'], s['y'])
        agent.familiarity[s['id']] = math.exp(-d / max(p.fam_scale, 1e-9))
        agent.perceived_occupancy[s['id']] = 0.0
    # P1.A: behavior state memory for hysteresis
    if not hasattr(agent, '_hoard_active'):
        agent._hoard_active = False
    if not hasattr(agent, '_herd_active'):
        agent._herd_active = False
    if not hasattr(agent, '_inquire_active'):
        agent._inquire_active = False


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
    """Eq. (14): gossip over familiar neighbours who are currently AT a store."""
    neighbors = getattr(agent, 'neighbors', [])
    for s in stores:
        observers = [n for n in neighbors
                     if getattr(n, '_at_store_id', None) == s['id']]
        if not observers:
            continue
        observed = _real_occupancy_norm(s)
        prev = agent.perceived_occupancy.get(s['id'], 0.0)
        agent.perceived_occupancy[s['id']] = (1.0 - p.gamma) * prev + p.gamma * observed


def attempt_acquire(agent, store):
    """容量约束抢购 (替代 random())。

    Returns True if success. Sets just_hoarded/hoarding_success/hoarding_failures
    so that downstream outcome_feedback can act on the bool.
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


# =============================================================================
# I3 — leader selection with inertia and in-group bias
# =============================================================================
def _familiarity_between(agent, j):
    return 1.0 if j in getattr(agent, 'neighbors', []) else 0.0


def leader_score(agent, j, p, in_cone=True):
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


# =============================================================================
# P2 — behavioral demonstration: effective threshold pull-down
# =============================================================================
def _agreeableness_factor(agent):
    """OCEAN 宜人性 → η 调节因子，缺省 1.0。"""
    ocean = getattr(agent, 'ocean', None)
    if ocean is None:
        return 1.0
    try:
        a = float(ocean.get('A', ocean.get('agreeableness', 0.5)))
    except Exception:
        return 1.0
    # 宜人性 0.0→0.6（更难受影响），0.5→1.0，1.0→1.4（更易受影响）
    return max(0.4, min(1.6, 0.6 + 0.8 * a))


def adjust_effective_thresholds(agent, theta1_base, theta2_base, p):
    """计算邻居行为示范修正后的有效阈值。

    Args:
        agent: ResidentAgent
        theta1_base / theta2_base: 性格调整后的 θ₁/θ₂ (= 基准×mult)
        p: SwitchParams
    Returns:
        (theta1_eff, theta2_eff): 修正后阈值
    """
    if not p.enable_behavior_demo:
        agent._theta1_eff = theta1_base
        agent._theta2_eff = theta2_base
        return theta1_base, theta2_base
    neighbors = getattr(agent, 'neighbors', None) or []
    if not neighbors:
        agent._theta1_eff = theta1_base
        agent._theta2_eff = theta2_base
        return theta1_base, theta2_base
    n_total = float(len(neighbors))
    n_hoard = sum(1 for n in neighbors if getattr(n, 'is_hoarding', False))
    n_herd = sum(1 for n in neighbors
                 if getattr(n, '_herd_active', False)
                 or getattr(n, 'is_emotion_burst', False))
    ratio_h = n_hoard / n_total
    ratio_g = n_herd / n_total
    eta = _agreeableness_factor(agent)
    t1 = max(0.05, theta1_base - eta * p.eta_demo_hoard * ratio_h)
    t2 = max(t1 + 0.05, theta2_base - eta * p.eta_demo_herd * ratio_g)
    agent._theta1_eff = t1
    agent._theta2_eff = t2
    return t1, t2


# =============================================================================
# P3 — inquiry / information-seeking direction
# =============================================================================
def _nearest_info_node(agent, info_nodes, max_radius):
    if not info_nodes:
        return None
    best = None
    best_d = max_radius
    for nd in info_nodes:
        nx = nd.get('x') if isinstance(nd, dict) else getattr(nd, 'x', None)
        ny = nd.get('y') if isinstance(nd, dict) else getattr(nd, 'y', None)
        if nx is None or ny is None:
            continue
        d = _dist(agent.x, agent.y, nx, ny)
        if d <= best_d:
            best_d = d
            best = (nx, ny)
    return best


def compute_inquire_direction(agent, info_nodes, p):
    """信息搜寻态方向：最近信息节点；缺失时小幅随机游走。"""
    node = _nearest_info_node(agent, info_nodes, p.inquire_radius)
    if node is not None:
        return _unit(node[0] - agent.x, node[1] - agent.y)
    ang = random.random() * 2.0 * math.pi
    return (math.cos(ang), math.sin(ang))


# =============================================================================
# P1.B — outcome feedback on σ
# =============================================================================
def apply_outcome_feedback(agent, p):
    """根据 agent 上一帧的行为执行结果，对 stress_level 注入脉冲。

    设计要点（对应 Lazarus 再评估 secondary appraisal）：
    - 囤积成功：σ 下降 (应对资源 C ↑)
    - 囤积失败：σ 上升 (威胁感知 T ↑)；连续失败放大
    - 跟随 Leader 成功 (低密度 + 邻居情绪降)：σ 轻度下降
    - 跟随 Leader 拥堵 (高密度 + 速度低)：σ 上升

    调用约定：放在 ResidentAgent.step 末尾、stress_level 已被 unified 模型更新之后；
    本函数对最终 σ 做加法修正并返回总脉冲 δ。
    """
    if not p.enable_outcome_feedback:
        return 0.0
    delta = 0.0

    # --- 囤积反馈 ---
    if getattr(agent, 'is_hoarding', False):
        if getattr(agent, 'just_hoarded', False) and getattr(agent, 'hoarding_success', False):
            delta += p.feedback_hoard_success
        else:
            fails = getattr(agent, 'hoarding_failures', 0)
            amp = 1.0 + p.feedback_failure_amplify_repeat * max(0, fails - 1)
            # 仅在确实尝试过且失败时记一次脉冲
            if getattr(agent, '_last_hoarding_failed_recorded', -1) != fails and fails > 0:
                delta += p.feedback_hoard_failure * amp
                agent._last_hoarding_failed_recorded = fails

    # --- 跟随 Leader 反馈 ---
    if getattr(agent, '_herd_active', False) and getattr(agent, 'current_leader', None) is not None:
        # 用局部密度 / 自身速度作为"拥堵"代理
        v = getattr(agent, 'recent_movement', None)
        density = getattr(agent, 'gathering_density', 0.0)
        if v is not None and v < 5e-5 and density > 0.3:
            delta += p.feedback_herd_jam
        else:
            # 跟随中且未拥堵 → 视为顺利疏散
            delta += p.feedback_herd_smooth

    if abs(delta) > 0:
        old = getattr(agent, 'stress_level', 0.0)
        agent.stress_level = max(0.0, min(1.0, old + delta))
        agent._last_outcome_feedback = delta
    return delta


# =============================================================================
# I1 — emotion-driven multi-stage goal switching (with extensions)
# =============================================================================
def _hysteresis_active(prev_active, sigma, on, off, enabled):
    """返回新激活状态：上跨 on 进入；下跨 off 退出；否则保持。"""
    if not enabled:
        return sigma >= on
    if prev_active:
        return sigma >= off
    return sigma >= on


def compute_goal_direction(agent, stores, neighbors, p, info_nodes=None):
    """Eqs. (10)-(12): sigmoid-weighted blend of home / hoard / herd directions.

    Extended (2026-06-13):
      - P1.A 迟滞带：用 agent._hoard_active / _herd_active 记忆状态。
      - P2 行为示范：从 agent._theta1_eff / _theta2_eff 读取已经被
                     unified_stress_model 写入的有效阈值；缺省退回 SwitchParams。
      - P3 信息搜寻：σ∈[θ_mild, θ₁) 且 SEIR∈{S,E} 时启用 w_inquire。
    """
    E = float(getattr(agent, 'stress_level', 0.0))
    Z = 1.0 if getattr(agent, 'pts_status', False) else 0.0
    H = 1.0 if float(getattr(agent, 'personal_supply', 1.0)) < p.supply_threshold else 0.0

    # --- 有效阈值 (P2)：优先用 unified 模型写入的 eff，再回退到 SwitchParams ---
    theta1 = float(getattr(agent, '_theta1_eff', p.theta1))
    theta2 = float(getattr(agent, '_theta2_eff', p.theta2))
    if theta2 <= theta1:
        theta2 = theta1 + 0.05

    # --- candidate directions (Eq. 10) ---
    home = getattr(agent, 'home_position', (agent.x, agent.y))
    d_home = _unit(home[0] - agent.x, home[1] - agent.y)

    s_star = choose_store(agent, stores, p) if (stores and H > 0.0) else None
    agent._target_store = s_star
    d_hoard = _unit(s_star['x'] - agent.x, s_star['y'] - agent.y) if s_star else (0.0, 0.0)

    leader = update_leader(agent, neighbors, p)
    d_herd = _unit(leader.x - agent.x, leader.y - agent.y) if leader is not None else (0.0, 0.0)

    # --- P1.A: 迟滞带状态记忆 (硬开关 + 软权重并存) ---
    prev_h = bool(getattr(agent, '_hoard_active', False))
    prev_g = bool(getattr(agent, '_herd_active', False))
    hoard_active = _hysteresis_active(
        prev_h, E,
        on=theta1, off=theta1 - p.delta_hoard,
        enabled=p.enable_hysteresis,
    )
    herd_active = _hysteresis_active(
        prev_g, E,
        on=theta2, off=theta2 - p.delta_herd,
        enabled=p.enable_hysteresis,
    )
    agent._hoard_active = hoard_active
    agent._herd_active = herd_active

    # --- P3: 信息搜寻态 (可选) ---
    seir_state = getattr(agent, 'state', 'S')
    inquire_gate = (
        p.enable_inquire
        and (p.theta_mild <= E < theta1)
        and seir_state in ('S', 'E')
    )
    if inquire_gate:
        d_inquire = compute_inquire_direction(agent, info_nodes or [], p)
        w_inquire = _sigmoid(p.k5 * (E - p.theta_mild)) * _sigmoid(-p.k1 * (E - theta1))
        agent._inquire_active = True
    else:
        d_inquire = (0.0, 0.0)
        w_inquire = 0.0
        agent._inquire_active = False

    # --- sigmoid weights (Eq. 11) ---
    w_home = _sigmoid(-p.k1 * (E - theta1))
    w_hoard = H * _sigmoid(p.k2 * (E - theta1)) * _sigmoid(-p.k3 * (E - theta2))
    w_herd = _sigmoid(p.k4 * (E - theta2)) + p.lambda_pts * Z

    # 迟滞带：若状态记忆为 False，强制压低对应权重（行为承诺/退出粘性）
    if p.enable_hysteresis:
        if not hoard_active:
            w_hoard *= 0.15
        if not herd_active:
            w_herd *= 0.15

    # --- normalise & combine (Eq. 12) ---
    W = w_home + w_hoard + w_herd + w_inquire + p.eps
    dx = (w_home * d_home[0] + w_hoard * d_hoard[0]
          + w_herd * d_herd[0] + w_inquire * d_inquire[0]) / W
    dy = (w_home * d_home[1] + w_hoard * d_hoard[1]
          + w_herd * d_herd[1] + w_inquire * d_inquire[1]) / W

    if w_inquire > 0:
        agent._goal_shares = (
            w_home / W, w_hoard / W, w_herd / W, w_inquire / W,
        )
    else:
        agent._goal_shares = (w_home / W, w_hoard / W, w_herd / W)
    return _unit(dx, dy)


# =============================================================================
# tiny self-test (run `python behavior_switching.py`)
# =============================================================================
if __name__ == "__main__":
    class A:  # minimal stub agent
        pass

    p = SwitchParams(enable_inquire=True)
    stores = [{'id': 's0', 'x': 0.002, 'y': 0.0, 'capacity': 2, 'occupancy': 0},
              {'id': 's1', 'x': -0.003, 'y': 0.001, 'capacity': 2, 'occupancy': 0}]
    info = [{'x': 0.0001, 'y': 0.0001}]

    a = A(); a.x = a.y = 0.0; a.home_position = (0.0, 0.0)
    a.pts_status = False; a.personal_supply = 0.1; a.neighbors = []
    a.state = 'S'; a.ocean = {'A': 0.5}
    init_store_state(a, stores, p)

    for E in (0.1, 0.25, 0.45, 0.8):
        a.stress_level = E
        d = compute_goal_direction(a, stores, a.neighbors, p, info_nodes=info)
        shares = a._goal_shares
        print(f"E={E:.2f}  shares={['%.2f'%s for s in shares]}  dir={d[0]:+.2f},{d[1]:+.2f}")
    # Expect: E=0.10 home; 0.25 inquire-dominated; 0.45 hoard; 0.80 herd.

    # outcome feedback smoke-test
    a.is_hoarding = True
    a.just_hoarded = True
    a.hoarding_success = True
    a.stress_level = 0.5
    delta = apply_outcome_feedback(a, p)
    print(f"hoard success feedback δ={delta:+.3f}  σ={a.stress_level:.3f}")
