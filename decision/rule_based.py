# -*- coding: utf-8 -*-
"""规则专家系统 - 基线决策器

特点:
    - 毫秒级响应 (无需前向仿真, 直接读当前 sim 状态)
    - 完全可解释 (每条规则都有依据)
    - 用作其他决策器的基线对照

规则来源:
    - 灾害应急管理理论 (启动应急响应的判定阈值)
    - V2 仿真观察的有效干预模式
    - 学生 game_theory_analyzer 总结的"危机/稳定/过渡"分类
"""
import time
from .base import Action, AdviceResult, BaseAdvisor, GOV_EVENTS, GRID_EVENTS
from .utility import compute_utility, default_utility_weights


class RuleBasedAdvisor(BaseAdvisor):
    """规则专家系统决策器"""

    method_name = 'rule_based'

    def __init__(self, weights_style='balanced', verbose=False):
        self.weights = default_utility_weights(weights_style)
        self.verbose = verbose

    def advise(self, sim, target_district: str, **kwargs) -> AdviceResult:
        t0 = time.time()

        # 1. 读取目标区当前状态
        state = self._read_state(sim, target_district)

        # 2. 分类情境
        context = self._classify(state)

        # 3. 按情境生成动作
        action, rules_fired = self._generate_action(target_district, state, context)

        # 4. 估算预期效用 (基于规则置信度, 不做前向仿真)
        confidence, exp_utility = self._estimate_confidence(state, context, rules_fired)

        explanation = self._explain(state, context, rules_fired)

        elapsed = (time.time() - t0) * 1000
        return AdviceResult(
            method=self.method_name,
            target_district=target_district,
            action=action,
            expected_utility=exp_utility,
            expected_outcome={
                'stress_avg_now': state['stress_avg'],
                'panic_avg_now': state['panic_avg'],
                'PC_now': state['PC'],
                'context': context,
            },
            compute_time_ms=elapsed,
            forward_steps=0,
            confidence=confidence,
            explanation=explanation,
        )

    def _read_state(self, sim, district):
        """提取目标区的关键状态"""
        zones = sim.district_to_zones.get(district, [])
        residents = [r for r in sim.residents if r.zone in set(zones)]

        if not residents:
            return {
                'stress_avg': 0, 'panic_avg': 0, 'emotion_avg': 0,
                'pts_count': 0, 'pts_ratio': 0,
                'outage_ratio': 0, 'PC': 1.0, 'ECR': 1.0,
                'enterprise_loss': 0, 'enterprise_request': 0,
                'seir_I_ratio': 0, 'seir_R_ratio': 0,
                'has_gov': False, 'n_residents': 0,
            }

        n = len(residents)
        stress_avg = sum(r.stress_level for r in residents) / n
        panic_avg = sum(r.panic_value for r in residents) / n
        emotion_avg = sum(r.emotion for r in residents) / n
        pts_count = sum(1 for r in residents if getattr(r, 'pts_status', False))
        seir_I = sum(1 for r in residents if r.state == 'I')
        seir_R = sum(1 for r in residents if r.state == 'R')

        n_outage_zones = sum(1 for z in zones if not sim.zone_status.get(z, True))
        outage_ratio = n_outage_zones / max(1, len(zones))

        gov = sim.gov_agents.get(district)
        PC = gov.PC if gov else 1.0
        ECR = gov.ECR if gov else 1.0

        # 该区企业
        ent_in_district = [e for e in sim.enterprises
                           if sim.zone_to_district.get(e.zone) == district]
        enterprise_loss = (sum(getattr(e, 'loss', 0) for e in ent_in_district)
                           / max(1, len(ent_in_district)) if ent_in_district else 0)
        enterprise_request = (sum(e.request() for e in ent_in_district)
                              / max(1, len(ent_in_district)) if ent_in_district else 0)

        return {
            'stress_avg': stress_avg,
            'panic_avg': panic_avg,
            'emotion_avg': emotion_avg,
            'pts_count': pts_count,
            'pts_ratio': pts_count / n,
            'outage_ratio': outage_ratio,
            'PC': PC,
            'ECR': ECR,
            'enterprise_loss': enterprise_loss,
            'enterprise_request': enterprise_request,
            'seir_I_ratio': seir_I / n,
            'seir_R_ratio': seir_R / n,
            'has_gov': gov is not None,
            'n_residents': n,
        }

    def _classify(self, state):
        """情境分类: critical / serious / moderate / mild / stable"""
        s = state['stress_avg']
        o = state['outage_ratio']
        pc = state['PC']
        if s > 0.7 or pc < 0.3:
            return 'critical'   # 危机
        elif s > 0.5 or o > 0.7 or pc < 0.5:
            return 'serious'    # 严重
        elif s > 0.3 or o > 0.3:
            return 'moderate'   # 中等
        elif s > 0.15 or o > 0:
            return 'mild'       # 轻度
        else:
            return 'stable'     # 稳定

    def _generate_action(self, district, state, context):
        """根据情境生成动作 + 触发的规则列表"""
        rules = []
        gov_events = {}
        grid_events = {}

        # === 政府积极性 / 响应效率 ===
        if context == 'critical':
            gov_init, gov_resp = 0.95, 1.7
            rules.append("R1: 危机状态 → 政府全力以赴 (init=0.95, resp=1.7)")
        elif context == 'serious':
            gov_init, gov_resp = 0.85, 1.5
            rules.append("R1': 严重状态 → 政府高积极性 (init=0.85, resp=1.5)")
        elif context == 'moderate':
            gov_init, gov_resp = 0.65, 1.2
            rules.append("R1'': 中等 → 政府中等响应 (init=0.65, resp=1.2)")
        else:
            gov_init, gov_resp = 0.45, 1.0
            rules.append("R1''': 平稳 → 政府保持基线 (init=0.45, resp=1.0)")

        # === 政府事件 ===
        # R2: 应急预警 (停电比例 > 0.3 或 stress > 0.4 时启动)
        if state['outage_ratio'] > 0.3 or state['stress_avg'] > 0.4:
            gov_events['emergency_warning'] = True
            rules.append("R2: 启动应急预警 (停电>30% 或 stress>0.4)")

        # R3: 舆情管理 (panic > 0.4 或 PC < 0.5)
        if state['panic_avg'] > 0.4 or state['PC'] < 0.5:
            gov_events['public_opinion'] = True
            rules.append("R3: 启动舆情管理 (panic>0.4 或 PC<0.5)")

        # R4: 拨资源给电网 (停电比例 > 0.2)
        if state['outage_ratio'] > 0.2:
            gov_events['resource_to_grid'] = True
            rules.append("R4: 拨资源给电网 (停电>20%)")

        # R5: 拨资源给居民 (stress > 0.5 或 PTS > 5%)
        if state['stress_avg'] > 0.5 or state['pts_ratio'] > 0.05:
            gov_events['resource_to_resident'] = True
            rules.append(f"R5: 拨资源给居民 (stress>0.5 或 PTS>5%)")

        # R6: 拨资源给企业 (企业损失 > 5 或 enterprise_request > 0.4)
        if state['enterprise_loss'] > 5 or state['enterprise_request'] > 0.4:
            gov_events['resource_to_enterprise'] = True
            rules.append("R6: 拨资源给企业 (企业损失高 / 求助强)")

        # === 电网参数 ===
        if state['outage_ratio'] > 0.5:
            grid_init, grid_resp = 0.95, 1.8
            rules.append("R7: 大面积停电 → 电网全力修复 (init=0.95, resp=1.8)")
        elif state['outage_ratio'] > 0.2:
            grid_init, grid_resp = 0.80, 1.4
            rules.append("R7': 中等停电 → 电网高响应 (init=0.80, resp=1.4)")
        else:
            grid_init, grid_resp = 0.50, 1.0
            rules.append("R7'': 小面积/无停电 → 电网保持基线")

        # === 电网事件 ===
        # R8: 临时供电 (关键设施紧急或停电>50%)
        if state['outage_ratio'] > 0.5:
            grid_events['temp_station'] = True
            rules.append("R8: 启用临时供电站 (停电>50%)")

        # R9: 加速修复 (始终在停电时启用)
        if state['outage_ratio'] > 0:
            grid_events['accelerated_repair'] = True
            rules.append("R9: 加速修复 (有停电)")

        action = Action(
            district=district,
            gov_initiative=gov_init,
            gov_response=gov_resp,
            grid_initiative=grid_init,
            grid_response=grid_resp,
            gov_events=gov_events,
            grid_events=grid_events,
        )
        return action, rules

    def _estimate_confidence(self, state, context, rules):
        """估算决策置信度 + 预期效用 (不做前向仿真)"""
        # 启发式: 规则覆盖度高 + 状态接近规则边界 → 置信度高
        base_conf = {'critical': 0.85, 'serious': 0.80, 'moderate': 0.70,
                     'mild': 0.60, 'stable': 0.55}.get(context, 0.5)
        # 规则触发数 (越多干预越激进, 高负载下置信度也高)
        n_events = sum(1 for r in rules if 'R' in r and r[1].isdigit())
        confidence = min(0.95, base_conf + 0.02 * n_events)

        # 预期效用 (粗估: 干预后状态会改善)
        # critical 状态干预后预期 stress 降到 0.4 左右, mild 状态保持
        target_stress = {'critical': 0.45, 'serious': 0.35, 'moderate': 0.25,
                         'mild': 0.15, 'stable': 0.10}.get(context, 0.3)
        target_panic = target_stress * 0.6
        # 用 utility 公式直接估
        u = -self.weights['stress'] * target_stress \
            -self.weights['panic'] * target_panic \
            -self.weights['cost'] * 0.3   # 干预成本约 0.3
        return confidence, u

    def _explain(self, state, context, rules):
        lines = [
            f"情境分类: 【{context}】 (基于 stress={state['stress_avg']:.2f}, "
            f"outage={state['outage_ratio']:.0%}, PC={state['PC']:.2f})",
            "",
            "触发的规则:",
        ]
        for r in rules:
            lines.append(f"  • {r}")
        return '\n'.join(lines)
