# -*- coding: utf-8 -*-
"""决策器统一接口"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ============================================================
# 决策粒度 - 用户指定: 停电区域 + 停电相关事件
# ============================================================
GOV_EVENTS = [
    'emergency_warning',       # 应急预警
    'public_opinion',          # 舆情管理
    'resource_to_grid',        # 给电网拨资源
    'resource_to_enterprise',  # 给企业拨资源
    'resource_to_resident',    # 给居民拨资源
]

GRID_EVENTS = [
    'temp_station',            # 临时供电站
    'accelerated_repair',      # 加速修复
]


@dataclass
class Action:
    """决策动作 - 决策器可以调整的所有杠杆

    针对单个停电区县:
        - 政府参数 (initiative, response)
        - 政府事件触发 (5 个 0/1)
        - 电网参数 (initiative, response)
        - 电网事件触发 (2 个 0/1)
    """
    district: str = ''
    gov_initiative: float = 0.5     # [0.1, 1.0]
    gov_response: float = 1.0       # [0.3, 2.0]
    grid_initiative: float = 0.5    # [0.1, 1.0]
    grid_response: float = 1.0      # [0.3, 2.0]
    gov_events: Dict[str, bool] = field(default_factory=dict)   # {event_name: bool}
    grid_events: Dict[str, bool] = field(default_factory=dict)

    def to_dict(self):
        return {
            'district': self.district,
            'gov_initiative': float(self.gov_initiative),
            'gov_response': float(self.gov_response),
            'grid_initiative': float(self.grid_initiative),
            'grid_response': float(self.grid_response),
            'gov_events': {k: bool(v) for k, v in self.gov_events.items()},
            'grid_events': {k: bool(v) for k, v in self.grid_events.items()},
        }

    def apply_to_sim(self, sim):
        """把动作应用到仿真"""
        if self.district in sim.gov_agents:
            gov = sim.gov_agents[self.district]
            gov.initiative = self.gov_initiative
            gov.response = self.gov_response
            gov.use_manual_events = True
            for ev in GOV_EVENTS:
                if ev in self.gov_events:
                    setattr(gov, f'manual_{ev}', bool(self.gov_events[ev]))
                    if ev == 'emergency_warning':
                        gov.manual_emergency_warning = bool(self.gov_events[ev])
                    elif ev == 'public_opinion':
                        gov.manual_public_opinion = bool(self.gov_events[ev])
                    elif ev == 'resource_to_grid':
                        gov.manual_resource_to_grid = bool(self.gov_events[ev])
                    elif ev == 'resource_to_enterprise':
                        gov.manual_resource_to_enterprise = bool(self.gov_events[ev])
                    elif ev == 'resource_to_resident':
                        gov.manual_resource_to_resident = bool(self.gov_events[ev])

        sim.grid.initiative = self.grid_initiative
        sim.grid.response = self.grid_response
        if self.grid_events.get('temp_station'):
            sim.grid.is_setting_temp_power = True
        if self.grid_events.get('accelerated_repair'):
            sim.grid.is_repairing = True


@dataclass
class AdviceResult:
    """决策建议结果 - 4 种决策器的统一返回类型"""
    method: str                       # 决策方法名 (rule_based / game_theory / bayesian / active_inference)
    target_district: str              # 目标区县
    action: Action                    # 推荐动作
    expected_utility: float = 0.0     # 预期效用 (越大越好)
    expected_outcome: Dict = field(default_factory=dict)
        # 包含 stress_avg_24h, panic_avg_24h, recovery_24h 等
    compute_time_ms: float = 0.0      # 决策耗时 (毫秒)
    forward_steps: int = 0            # 前向仿真累计步数
    confidence: float = 0.5           # 决策置信度 [0, 1]
    explanation: str = ''             # 人类可读解释
    candidate_solutions: List[Dict] = field(default_factory=list)
        # 备选方案列表 (前 N 个)

    def to_dict(self):
        return {
            'method': self.method,
            'target_district': self.target_district,
            'action': self.action.to_dict(),
            'expected_utility': float(self.expected_utility),
            'expected_outcome': self.expected_outcome,
            'compute_time_ms': float(self.compute_time_ms),
            'forward_steps': int(self.forward_steps),
            'confidence': float(self.confidence),
            'explanation': self.explanation,
            'candidate_solutions': self.candidate_solutions[:5],  # 限制大小
        }


class BaseAdvisor:
    """决策器基类"""

    method_name = 'base'

    def __init__(self, name=None, **kwargs):
        if name is not None:
            self.method_name = name

    def advise(self, sim, target_district: str, **kwargs) -> AdviceResult:
        """给出决策建议

        参数:
            sim: BlackoutSimulation 实例 (当前状态)
            target_district: 目标停电区县
            **kwargs: 决策器特定的参数
                forecast_steps: 前向仿真步数 (用于评估动作)
                budget: 评估预算 (贝叶斯优化评估次数)

        返回:
            AdviceResult
        """
        raise NotImplementedError

    def __repr__(self):
        return f"<{self.__class__.__name__} method='{self.method_name}'>"
