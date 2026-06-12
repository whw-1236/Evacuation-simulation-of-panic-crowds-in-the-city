# -*- coding: utf-8 -*-
"""效用函数 - 决策器评估动作好坏的统一标准

按用户要求采用"多目标加权效用":
    U = -0.40·stress_avg - 0.20·panic_avg - 0.15·SEIR_I_ratio
        - 0.10·(1-PC) - 0.10·loss_norm - 0.05·intervention_cost

权重可调 (对应不同决策风格: 保民生 / 保经济 / 保稳定)。

提供两种评估接口:
    compute_utility(sim, weights) - 单点状态效用 (即时)
    forward_evaluate(sim, action, horizon, weights) - 前向仿真评估
"""
import numpy as np
from collections import Counter


def default_utility_weights(style='balanced'):
    """三档预设权重

    Args:
        style: 'balanced'  - 默认平衡
               'pro_people' - 偏保民生 (压力/恐慌权重高)
               'pro_economy'- 偏保经济 (企业损失权重高)
               'pro_stable' - 偏保稳定 (PC 权重高)
    """
    if style == 'pro_people':
        return {
            'stress': 0.50, 'panic': 0.25, 'seir_I': 0.15,
            'PC_inv': 0.05, 'loss': 0.03, 'cost': 0.02,
        }
    elif style == 'pro_economy':
        return {
            'stress': 0.20, 'panic': 0.10, 'seir_I': 0.10,
            'PC_inv': 0.10, 'loss': 0.45, 'cost': 0.05,
        }
    elif style == 'pro_stable':
        return {
            'stress': 0.30, 'panic': 0.15, 'seir_I': 0.15,
            'PC_inv': 0.30, 'loss': 0.05, 'cost': 0.05,
        }
    else:  # balanced
        return {
            'stress': 0.40, 'panic': 0.20, 'seir_I': 0.15,
            'PC_inv': 0.10, 'loss': 0.10, 'cost': 0.05,
        }


def compute_utility(sim, weights=None, intervention_cost=0.0,
                    target_district=None):
    """计算当前仿真状态的效用值 (越大越好, 通常 ∈ [-1, 1])

    Args:
        sim: BlackoutSimulation
        weights: 权重字典 (None 时用 balanced)
        intervention_cost: 干预成本 [0, 1] (由决策器自己估算)
        target_district: 仅在该区县内统计 (None 时全市)

    Returns:
        float: 效用值
    """
    if weights is None:
        weights = default_utility_weights('balanced')

    # 1. 提取居民群体
    if target_district and target_district in sim.district_to_zones:
        target_zones = set(sim.district_to_zones[target_district])
        residents = [r for r in sim.residents if r.zone in target_zones]
    else:
        residents = sim.residents

    if not residents:
        return 0.0

    n = len(residents)
    stress_avg = sum(r.stress_level for r in residents) / n
    panic_avg = sum(r.panic_value for r in residents) / n
    seir = Counter(r.state for r in residents)
    seir_I_ratio = seir.get('I', 0) / n

    # 2. PC (公众配合度) - 取目标区政府
    if target_district and target_district in sim.gov_agents:
        PC = sim.gov_agents[target_district].PC
    else:
        # 全市政府平均
        PC = np.mean([g.PC for g in sim.gov_agents.values()]) if sim.gov_agents else 1.0

    # 3. 企业损失 (归一化到 [0, 1])
    if sim.enterprises:
        avg_loss = np.mean([getattr(e, 'loss', 0) for e in sim.enterprises])
        loss_norm = min(1.0, avg_loss / 50.0)  # 经验上限 50
    else:
        loss_norm = 0.0

    # 4. 加权 (注意符号: 这些都是"越大越坏"的指标, 取负作为效用)
    utility = (
        - weights['stress'] * stress_avg
        - weights['panic'] * panic_avg
        - weights['seir_I'] * seir_I_ratio
        - weights['PC_inv'] * (1.0 - PC)
        - weights['loss'] * loss_norm
        - weights['cost'] * intervention_cost
    )
    return float(utility)


def forward_evaluate(sim, action, horizon=24, weights=None,
                     save_restore=True, _save=None, _load=None):
    """对动作做前向仿真评估

    Args:
        sim: 仿真
        action: Action 对象 (None 表示不施加任何干预)
        horizon: 前向步数 (默认 24 步 = 6h)
        weights: 效用权重
        save_restore: 是否在评估完后恢复仿真状态 (默认 True)
        _save, _load: 注入的 save/load 函数, 默认从 platform_io 导入

    Returns:
        dict: {
            'final_utility', 'utility_trace', 'forward_steps',
            'final_stress', 'final_panic', 'final_PC', 'seir_final',
        }
    """
    if save_restore:
        if _save is None or _load is None:
            from platform_io import save_snapshot, load_snapshot
            _save = save_snapshot
            _load = load_snapshot
        snap = _save(sim)

    # 应用动作
    if action is not None:
        action.apply_to_sim(sim)

    # 估算干预成本 (有动作就有成本, 越多事件越高)
    intervention_cost = 0.0
    if action is not None:
        n_events = sum(1 for v in action.gov_events.values() if v) + \
                   sum(1 for v in action.grid_events.values() if v)
        intervention_cost = min(1.0, n_events / 7.0 * 0.5 +
                                (action.gov_initiative + action.grid_initiative) / 4.0)

    target_district = action.district if action else None

    # 前向仿真
    utility_trace = []
    for _ in range(horizon):
        sim.step()
        u = compute_utility(sim, weights, intervention_cost, target_district)
        utility_trace.append(u)

    # 终态指标
    target_residents = sim.residents
    if target_district and target_district in sim.district_to_zones:
        target_zones = set(sim.district_to_zones[target_district])
        target_residents = [r for r in sim.residents if r.zone in target_zones]
    n = max(1, len(target_residents))
    final_stress = sum(r.stress_level for r in target_residents) / n
    final_panic = sum(r.panic_value for r in target_residents) / n
    seir = Counter(r.state for r in target_residents)
    PC = (sim.gov_agents[target_district].PC
          if target_district and target_district in sim.gov_agents
          else (np.mean([g.PC for g in sim.gov_agents.values()]) if sim.gov_agents else 1.0))

    result = {
        'final_utility': float(np.mean(utility_trace)),  # 取 horizon 内平均
        'utility_trace': [float(u) for u in utility_trace],
        'forward_steps': horizon,
        'final_stress': float(final_stress),
        'final_panic': float(final_panic),
        'final_PC': float(PC),
        'seir_final': {k: int(seir.get(k, 0)) for k in 'SEIR'},
    }

    if save_restore:
        _load(sim, snap)

    return result
