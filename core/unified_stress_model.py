"""
================================================================================
统一心理压力模型 - 基于Lazarus应激-评估-应对理论
================================================================================

【学术基础】
1. Lazarus应激-认知评估理论 (Lazarus & Folkman, 1984)
   - 初级评估：威胁感知（Threat Appraisal）
   - 次级评估：应对资源评估（Coping Resources）
   - 应激反应 = 威胁感知 / 应对资源

2. 社会传染理论 (Hatfield et al., 1994)
   - 情绪在群体中传播
   - 传播速度与社交接触频率相关

3. 恐慌传播的SIR模型 (灾害心理学)
   - 易感者(S) → 恐慌者(I) → 恢复者(R)
   - 传播率β，恢复率γ

【统一模型公式】
dσ/dt = α·T·(1-σ) - β·C·σ + γ·(σ̄-σ) + Σ(事件影响)

其中：
- σ: 心理压力值 (Stress Level) ∈ [0, 1]
- T: 威胁感知 (Threat Perception) ∈ [0, 1]
- C: 应对资源 (Coping Resources) ∈ [0, 1]
- σ̄: 邻居平均压力（社会传染）
- α: 威胁敏感度（个体差异）
- β: 恢复能力（个体差异）
- γ: 社会传染系数

【行为触发阈值】
- σ < 0.2: 正常状态
- 0.2 ≤ σ < 0.4: 轻度焦虑（可能开始关注信息）
- 0.4 ≤ σ < 0.6: 中度焦虑（可能囤积物资、请求供电）
- 0.6 ≤ σ < 0.8: 高度恐慌（情绪爆发、非理性行为）
- σ ≥ 0.8: 极度恐慌（失控状态）

================================================================================
"""

import numpy as np
import random

# P2 行为示范阈值修正（来自 behavior_switching）。失败回退到无修正。
try:
    from .behavior_switching import adjust_effective_thresholds as _adjust_eff_thr
except ImportError:
    try:
        from behavior_switching import adjust_effective_thresholds as _adjust_eff_thr
    except ImportError:
        _adjust_eff_thr = None


class UnifiedStressModel:
    """
    统一心理压力模型

    整合原有的panic_value和emotion，使用单一的stress_level指标
    """

    # 行为触发阈值
    THRESHOLD_MILD_ANXIETY = 0.2  # 轻度焦虑
    THRESHOLD_MODERATE_ANXIETY = 0.4  # 中度焦虑（囤积、请求供电）
    THRESHOLD_HIGH_PANIC = 0.6  # 高度恐慌（情绪爆发）
    THRESHOLD_EXTREME_PANIC = 0.8   # 极度恐慌（PTS 进入阈值）
    THRESHOLD_PTS_EXIT      = 0.5   # PTS 迟滞退出阈值（进入0.8 / 退出0.5，迟滞带0.3）

    # ====== Fig.5 钟形曲线匹配参数 (2026-06-13) ======
    # 旧默认值导致政府事件 σ 缓解过强 (sum≈-0.034/步)，把 stimulation 完全抵消，
    # σ 永远涨不起来。这组默认值把缓解缩放到 ~0.3 倍，让"激发-平台-平复"曲线
    # 能在 t∈[0, T_outage] 内呈现。如要强政府响应可把该常数调回 1.0。
    GOV_EVENT_SOFTNESS = 0.3
    # 恢复供电后 outage_threat 的指数衰减时间常数 (h)；越小衰减越快。
    OUTAGE_THREAT_DECAY_TAU = 6.0

    def __init__(self):
        """初始化模型参数"""
        # 威胁感知权重
        self.threat_weights = {
            'outage_duration': 0.30,  # 停电时长
            'supply_shortage': 0.20,  # 物资短缺
            'neighbor_panic': 0.25,  # 邻居恐慌
            'information_gap': 0.15,  # 信息缺失
            'health_vulnerability': 0.10,  # 健康脆弱性
        }

        # 应对资源权重
        self.coping_weights = {
            'government_support': 0.30,  # 政府支持
            'personal_resilience': 0.25,  # 个人韧性
            'social_support': 0.20,  # 社会支持
            'information_access': 0.15,  # 信息获取
            'material_reserve': 0.10,  # 物资储备
        }

    def calculate_threat_perception(self, resident, zone_data, dt):
        """
        计算威胁感知 T ∈ [0, 1]

        【公式】
        T = Σ(wi × ti)

        其中ti为各威胁因素的归一化值
        """
        threat = 0.0

        # 1. 停电时长威胁（对数增长，体现边际递减）
        # 0h→0, 2h→0.28, 6h→0.55, 12h→0.78, 24h→1.00(封顶), 48h→1.00(封顶)
        # 【2026-06-13】恢复供电后按 exp(-t/τ) 衰减，让 σ 钟形曲线能回落
        # （对应 Fig.5 的"平复"段；τ 默认 6h）。
        t_outage = getattr(resident, 't_outage', 0)
        if t_outage > 0:
            outage_threat = min(1.0, 0.4 * np.log1p(t_outage / 2.0))
            if getattr(resident, 'powered', True):
                # 恢复后衰减：用 time_since_recovery 作为衰减计时
                t_since = float(getattr(resident, 'time_since_recovery', 0.0))
                tau = max(0.5, self.OUTAGE_THREAT_DECAY_TAU)
                outage_threat *= float(np.exp(-t_since / tau))
            threat += self.threat_weights['outage_duration'] * outage_threat

        # 2. 物资短缺威胁
        personal_supply = getattr(resident, 'personal_supply', 1.0)
        if personal_supply < 0.5:
            supply_threat = (0.5 - personal_supply) * 2  # 0.5→0, 0→1
            threat += self.threat_weights['supply_shortage'] * supply_threat

        # 3. 邻居恐慌传染
        neighbors = getattr(resident, 'neighbors', [])
        if neighbors:
            avg_neighbor_stress = np.mean([
                getattr(n, 'stress_level', 0) for n in neighbors
            ])
            # 非线性传染：邻居恐慌越高，传染效果越强
            neighbor_threat = avg_neighbor_stress ** 1.5
            threat += self.threat_weights['neighbor_panic'] * neighbor_threat

        # 4. 信息缺失威胁
        # 【Lazarus 应激-评估原则】
        # "信息缺失"只在居民正处于应激状态时才作为威胁源：
        #   - 当前停电中 (not powered)
        #   - 处于恢复期 (recovery_phase)
        # 退出恢复期后（was_affected 也重置），此项归零，stress 可自由下降。
        is_under_stress = (not getattr(resident, 'powered', True)) \
                          or getattr(resident, 'recovery_phase', False)
        if is_under_stress:
            official_info = getattr(resident, 'info_received', {}).get('official', 0)
            rumor_belief = getattr(resident, 'rumor_belief', 0)
            info_threat = (1 - official_info) * 0.5 + rumor_belief * 0.5
            threat += self.threat_weights['information_gap'] * info_threat

        # 5. 健康脆弱性
        health_vulnerability = {
            '健康': 0.0,
            '亚健康': 0.2,
            '轻微疾病': 0.4,
            '严重疾病': 0.8,
            '残疾': 0.6,
        }
        health_status = getattr(resident, 'health_status', '健康')
        health_threat = health_vulnerability.get(health_status, 0)
        # 老年人更脆弱
        age = getattr(resident, 'age', 40)
        if age > 60:
            health_threat += (age - 60) * 0.01  # 每年+1%
        health_threat = min(1.0, health_threat)
        threat += self.threat_weights['health_vulnerability'] * health_threat

        return min(1.0, threat)

    def calculate_coping_resources(self, resident, gov_resource, zone_data):
        """
        计算应对资源 C ∈ [0, 1]

        【公式】
        C = Σ(wi × ci)

        其中ci为各应对资源的归一化值
        """
        coping = 0.0

        # 1. 政府支持
        gov_support = min(1.0, gov_resource / 2.0)  # gov_resource通常0-2
        coping += self.coping_weights['government_support'] * gov_support

        # 2. 个人韧性（基于性格和抗压能力）
        stress_resistance = getattr(resident, 'stress_resistance', 0.5)
        personality_resilience = {
            '理性型': 0.9,
            '稳定型': 0.7,
            '普通型': 0.5,
            '敏感型': 0.3,
            '焦虑型': 0.1,
        }
        personality = getattr(resident, 'personality', '普通型')
        personal_res = personality_resilience.get(personality, 0.5) * 0.5 + stress_resistance * 0.5
        coping += self.coping_weights['personal_resilience'] * personal_res

        # 3. 社会支持（基于邻居中的R状态和自救者）
        neighbors = getattr(resident, 'neighbors', [])
        if neighbors:
            r_neighbors = sum(1 for n in neighbors if getattr(n, 'state', 'S') == 'R')
            helping_neighbors = sum(1 for n in neighbors if getattr(n, 'is_self_helping', False))
            social_support = min(1.0, (r_neighbors + helping_neighbors) / max(1, len(neighbors)))
        else:
            social_support = 0.3  # 没有邻居时的基础社会支持
        coping += self.coping_weights['social_support'] * social_support

        # 4. 信息获取
        official_info = getattr(resident, 'info_received', {}).get('official', 0)
        coping += self.coping_weights['information_access'] * official_info

        # 5. 物资储备
        personal_supply = getattr(resident, 'personal_supply', 1.0)
        coping += self.coping_weights['material_reserve'] * personal_supply

        return min(1.0, max(0.1, coping))  # 最低0.1，避免除零

    def calculate_stress_change(self, resident, gov_resource, zone_data, dt):
        """
        计算心理压力变化

        【核心公式】
        dσ/dt = α·T·(1-σ) - β·C·σ + γ·(σ̄-σ) + Σ(事件影响)

        【延迟机制】
        - 内部压力从t=0开始累积
        - 只有当内部压力 > 个人耐受阈值时，外显压力才开始增长
        - 不同属性的人耐受阈值不同，所以反应时间不同

        返回:
            stress_change: 压力变化值
            components: 各分量的详细信息（用于调试）
        """
        σ = getattr(resident, 'stress_level', 0)

        # 计算威胁感知和应对资源
        T = self.calculate_threat_perception(resident, zone_data, dt)
        C = self.calculate_coping_resources(resident, gov_resource, zone_data)

        # ============================================================
        # 【延迟机制】内部压力 vs 耐受阈值
        # ============================================================
        #
        # 【核心理念】
        # 1. 内部压力（internal_stress）从停电开始就在累积
        # 2. 但只有超过个人耐受阈值（tolerance）后，外显压力才开始增长
        # 3. 不同人的tolerance不同，所以开始反应的时间不同
        # 4. 这就是"延迟"效果的体现
        #
        t_outage = getattr(resident, 't_outage', 0)
        personality = getattr(resident, 'personality', '普通型')
        stress_resistance = getattr(resident, 'stress_resistance', 0.5)
        age = getattr(resident, 'age', 40)
        health_status = getattr(resident, 'health_status', '健康')

        # 【第一步】计算内部压力（从停电开始就在累积）
        #
        # powered 默认值: True (有电)。
        # 注意: ResidentAgent 构造函数 self.powered=True, 所以 getattr 不会走默认分支。
        # 此处默认 True 是为了保证在 powered 属性缺失时行为安全（不误判为停电）。
        #
        is_powered = getattr(resident, 'powered', True)

        if not is_powered and t_outage > 0:
            # 内部压力 = 基础压力 + 环境因素
            # 使用平方根增长，初期快后期慢
            base_internal = 0.08 + 0.22 * np.sqrt(t_outage / 2.0)  # 0h→0.08, 2h→0.24, 6h→0.46, 12h→0.62, 24h→0.84

            # 环境因素增加内部压力
            neighbors = getattr(resident, 'neighbors', [])
            if neighbors:
                high_stress_neighbors = sum(1 for n in neighbors if getattr(n, 'stress_level', 0) > 0.3)
                env_stress = min(0.20, high_stress_neighbors * 0.03)
            else:
                env_stress = 0

            internal_stress = min(1.0, base_internal + env_stress)
        elif not is_powered:
            # 刚停电，t_outage可能还是0
            internal_stress = 0.05  # 最低基础压力
        else:
            internal_stress = 0.0

        # 【第二步】计算个人耐受阈值
        personality_tolerance = {
            '焦虑型': 0.12,  # 很快就开始反应
            '敏感型': 0.20,
            '普通型': 0.30,
            '稳定型': 0.45,
            '理性型': 0.60,  # 需要很久才开始反应
        }

        # 年龄影响：老年人和小孩更敏感
        if age < 18 or age > 65:
            age_adj = -0.08
        elif age > 55:
            age_adj = -0.04
        else:
            age_adj = 0.05

        # 健康影响：病人更敏感
        health_adj = {
            '健康': 0.05,
            '亚健康': 0.0,
            '轻微疾病': -0.05,
            '严重疾病': -0.15,
            '残疾': -0.10,
        }.get(health_status, 0)

        # 抗压能力影响
        resistance_adj = stress_resistance * 0.15

        tolerance = personality_tolerance.get(personality, 0.30) + age_adj + health_adj + resistance_adj
        tolerance = max(0.08, min(0.70, tolerance))  # 限制范围

        # 存储用于调试和事件触发
        resident._internal_stress = internal_stress
        resident._tolerance = tolerance

        # 【第三步】判断是否超过耐受，计算外显压力增长
        #
        # 【关键逻辑】
        # - 内部压力 < 耐受：外显压力几乎不变（潜伏期）
        # - 内部压力 > 耐受：外显压力开始增长（反应期）
        # - 超出越多，增长越快
        #
        if internal_stress > tolerance:
            # 超出耐受，开始反应
            excess = internal_stress - tolerance
            reaction_factor = 1.0 + excess * 2.0  # 超出越多，反应越强
        else:
            # 未超出耐受，潜伏期（仍有轻微反应，但大幅减弱）
            reaction_factor = 0.5  # 潜伏期反应系数，原0.1导致 stress 几乎冻结

        # ============================================================
        # 【核心公式计算】
        # ============================================================

        # 个体敏感度α（SEIR状态和性格影响）
        # 原值 S=0.06 偏保守，导致 stress 增长速度远低于实际体感；按比例×2.33
        seir_alpha = {'I': 0.23, 'E': 0.19, 'S': 0.14, 'R': 0.09}
        personality_alpha = {'焦虑型': 1.3, '敏感型': 1.15, '普通型': 1.0, '稳定型': 0.85, '理性型': 0.7}

        state = getattr(resident, 'state', 'S')
        α = seir_alpha.get(state, 0.14) * personality_alpha.get(personality, 1.0)

        # 【关键】α乘以反应因子，实现延迟效果
        α *= reaction_factor

        # 恢复能力β
        β = 0.04 + stress_resistance * 0.04  # 0.04 ~ 0.08

        # 社会传染系数γ
        social_activity = getattr(resident, 'social_activity', 0.5)
        γ = 0.015 * social_activity

        # 邻居平均压力
        # 【改进3】优先使用距离加权的邻居压力（若已由 ResidentAgent.step 预计算）
        # sigma_bar_weighted 基于 sigmoid 距离核 w(L)=1-1/(1+exp(-L/σ))
        # 和 SEIR 源权重（I:1.0, E:0.3, S/R:0）做加权平均。
        # 当属性不存在时 fallback 到原有简单平均，保持向后兼容。
        if hasattr(resident, 'sigma_bar_weighted'):
            σ_bar = resident.sigma_bar_weighted
        else:
            neighbors = getattr(resident, 'neighbors', [])
            if neighbors:
                σ_bar = np.mean([getattr(n, 'stress_level', 0) for n in neighbors])
            else:
                σ_bar = σ

        # ========== 核心公式 ==========
        # 威胁刺激项（天花板效应）
        stimulation = α * T * (1 - σ) * dt

        # 应对恢复项
        recovery = -β * C * σ * dt

        # 社会传染项（只在反应期才有效）
        if internal_stress > tolerance:
            contagion = γ * (σ_bar - σ) * dt
        else:
            contagion = 0  # 潜伏期不受传染

        # ============================================================
        # 【事件影响】包括政府决策和居民行为
        # ============================================================
        event_effect = 0.0

        # ---------- 政府决策影响（缓解压力）----------
        # 所有事件强度统一乘 GOV_EVENT_SOFTNESS（默认 0.3），让 σ 能在停电期间
        # 上升到峰值，对应论文 Fig.5 的"激发-平台-平复"钟形曲线。
        gov_events = getattr(resident, '_gov_events', {})
        gov_softness = self.GOV_EVENT_SOFTNESS

        # 事件1: 发布停电通知 → 降低信息焦虑
        if gov_events.get('outage_notice', False):
            event_effect -= 0.02 * gov_softness * dt

        # 事件2: 启动应急响应 → 增加安全感
        if gov_events.get('emergency_response', False):
            event_effect -= 0.025 * gov_softness * dt

        # 事件3: 发放应急物资 → 降低物资焦虑
        if gov_events.get('supply_distribution', False):
            event_effect -= 0.03 * gov_softness * dt

        # 事件4: 疏散安置 → 降低危险感（如果在安全区）
        if gov_events.get('evacuation', False):
            event_effect -= 0.04 * gov_softness * dt

        # 事件5: 心理疏导/安抚 → 直接降低压力
        if gov_events.get('psychological_comfort', False):
            # 安抚效果因人而异
            comfort_effectiveness = {
                '焦虑型': 0.8,  # 很需要安抚
                '敏感型': 0.9,
                '普通型': 1.0,
                '稳定型': 0.6,  # 不太需要
                '理性型': 0.4,
            }.get(personality, 1.0)
            event_effect -= 0.035 * comfort_effectiveness * gov_softness * dt

        # ---------- 电网决策影响 ----------
        grid_events = getattr(resident, '_grid_events', {})

        # 事件7: 临时供电站 → 部分缓解
        if grid_events.get('temp_station', False):
            event_effect -= 0.02 * dt

        # 事件8: 加速修复 → 增加希望（如果知道的话）
        if grid_events.get('accelerated_repair', False):
            official_info = getattr(resident, 'info_received', {}).get('official', 0)
            event_effect -= 0.015 * official_info * dt  # 知道才有效

        # ---------- 居民行为影响 ----------

        # 囤积行为影响
        if getattr(resident, 'is_hoarding', False):
            if getattr(resident, 'hoarding_success', True):
                event_effect -= 0.025 * dt  # 成功缓解压力
            else:
                failure_count = getattr(resident, 'hoarding_failures', 1)
                event_effect += 0.03 * min(2.0, 1 + failure_count * 0.2) * dt  # 失败增加压力

        # 自救行为影响
        if getattr(resident, 'is_self_helping', False):
            initiative = getattr(resident, 'initiative', 0.5)
            event_effect -= 0.03 * initiative * dt  # 自救降低压力（主动应对）

        # 聚集行为影响（双刃剑）
        neighbors = getattr(resident, 'neighbors', [])
        if getattr(resident, 'is_gathering', False) and neighbors:
            gathering_neighbors = [n for n in neighbors if getattr(n, 'is_gathering', False)]
            if gathering_neighbors:
                avg_stress = np.mean([getattr(n, 'stress_level', 0.5) for n in gathering_neighbors])
                if avg_stress < 0.3:
                    event_effect -= 0.02 * dt  # 与平静者聚集：安慰
                elif avg_stress > 0.6:
                    event_effect += 0.025 * (avg_stress - 0.5) * dt  # 与恐慌者聚集：传染

        # 请求供电影响（发泄情绪）
        if getattr(resident, 'is_requesting_power', False):
            # 请求本身是一种发泄，稍微缓解压力
            event_effect -= 0.01 * dt

        # ---------- 供电恢复影响（长尾效应）----------
        if getattr(resident, 'powered', True) and getattr(resident, 'total_outage_hours', 0) > 0:
            # 恢复供电后的长尾恢复效应
            peak_stress = getattr(resident, 'peak_stress', 0.5)
            total_outage = getattr(resident, 'total_outage_hours', 0)

            # 恢复阻力 = f(峰值压力, 停电时长)
            # 经历越痛苦，恢复越慢
            resistance = 1.0 + peak_stress * 0.5 + min(1.0, total_outage / 24) * 0.3
            powered_recovery = -0.015 / resistance * σ * dt
            event_effect += powered_recovery

        # ========== 综合变化 ==========
        stress_change = stimulation + recovery + contagion + event_effect

        # 返回详细分量（用于调试和分析）
        components = {
            'threat': T,
            'coping': C,
            'alpha': α,
            'beta': β,
            'stimulation': stimulation,
            'recovery': recovery,
            'contagion': contagion,
            'event_effect': event_effect,
            'total_change': stress_change
        }

        return stress_change, components

    def update_resident_stress(self, resident, gov_resource, zone_data, dt):
        """
        更新居民的心理压力值

        同时更新行为状态（基于压力阈值）
        """
        # 计算压力变化
        stress_change, components = self.calculate_stress_change(
            resident, gov_resource, zone_data, dt
        )

        # 更新压力值
        old_stress = getattr(resident, 'stress_level', 0)
        new_stress = max(0, min(1.0, old_stress + stress_change))
        resident.stress_level = new_stress

        # 记录峰值压力（用于长尾效应）
        if new_stress > getattr(resident, 'peak_stress', 0):
            resident.peak_stress = new_stress

        # 更新行为状态（基于阈值）
        self._update_behavior_states(resident, new_stress)

        # 返回分量信息（可选，用于调试）
        return components

    def _update_behavior_states(self, resident, stress):
        """
        基于压力值更新行为状态

        【阈值逻辑】
        - 不同性格的人有不同的阈值
        - 阈值 = 基础阈值 × 性格系数
        - P2 行为示范：邻域内 hoarding/herding 比例压低 θ₁/θ₂
          (Cialdini 社会证明 + 行为传染，独立于情绪传染通道)
        """
        # 性格对阈值的影响
        personality_threshold_mult = {
            '焦虑型': 0.7,  # 更低的阈值，更容易触发
            '敏感型': 0.85,
            '普通型': 1.0,
            '稳定型': 1.15,
            '理性型': 1.3,  # 更高的阈值，不容易触发
        }
        personality = getattr(resident, 'personality', '普通型')
        mult = personality_threshold_mult.get(personality, 1.0)

        # 调整后的阈值（性格基线）
        mild_threshold = self.THRESHOLD_MILD_ANXIETY * mult
        moderate_threshold = self.THRESHOLD_MODERATE_ANXIETY * mult
        high_threshold = self.THRESHOLD_HIGH_PANIC * mult
        extreme_threshold = self.THRESHOLD_EXTREME_PANIC * mult

        # ============================================================
        # P2: 行为示范对 θ₁/θ₂ 的压低（独立于情绪传染 γ·(σ̄-σ)）
        # ============================================================
        sw = getattr(resident, 'sw', None)
        if sw is not None and getattr(sw, 'enable_behavior_demo', False) \
                and _adjust_eff_thr is not None:
            mod_eff, high_eff = _adjust_eff_thr(
                resident, moderate_threshold, high_threshold, sw,
            )
            moderate_threshold = mod_eff
            high_threshold = high_eff
            # extreme 阈值同步在 high 之上做温和上移，保持迟滞带形态
            extreme_threshold = max(extreme_threshold, high_eff + 0.18 * mult)
        else:
            # 即使禁用 P2，也将基线阈值写到 _theta1_eff/_theta2_eff，
            # 供 compute_goal_direction 统一读取，避免分支。
            resident._theta1_eff = moderate_threshold
            resident._theta2_eff = high_threshold

        # 更新PTS状态（极度恐慌 + 迟滞带：进入0.8×mult，退出0.5×mult）
        pts_enter = min(0.95, extreme_threshold)      # extreme_threshold 即 0.8×mult；封顶0.95
        pts_exit  = self.THRESHOLD_PTS_EXIT * mult    # 0.5×mult
        if resident.pts_status:
            resident.pts_status = stress >= pts_exit  # 已在PTS：σ跌破退出阈值才解除
        else:
            resident.pts_status = stress >= pts_enter # 未在PTS：σ达到进入阈值才触发

        # 情绪爆发：仍用高度恐慌阈值（0.6×mult），与PTS解耦
        resident.is_emotion_burst = stress >= high_threshold

        # 请求供电状态
        resident.is_requesting_power = (
                not getattr(resident, 'powered', True) and
                stress >= moderate_threshold
        )

        # 注意：囤积和自救的触发逻辑更复杂，保留在原有代码中
        # 这里只设置基础状态
        resident._stress_based_anxiety_level = (
            'none' if stress < mild_threshold else
            'mild' if stress < moderate_threshold else
            'moderate' if stress < high_threshold else
            'high' if stress < extreme_threshold else
            'extreme'
        )

    def get_stress_statistics(self, residents):
        """
        获取群体压力统计
        """
        stress_values = [getattr(r, 'stress_level', 0) for r in residents]

        return {
            'mean': np.mean(stress_values),
            'std': np.std(stress_values),
            'max': np.max(stress_values),
            'min': np.min(stress_values),
            'count_mild': sum(
                1 for s in stress_values if self.THRESHOLD_MILD_ANXIETY <= s < self.THRESHOLD_MODERATE_ANXIETY),
            'count_moderate': sum(
                1 for s in stress_values if self.THRESHOLD_MODERATE_ANXIETY <= s < self.THRESHOLD_HIGH_PANIC),
            'count_high': sum(
                1 for s in stress_values if self.THRESHOLD_HIGH_PANIC <= s < self.THRESHOLD_EXTREME_PANIC),
            'count_extreme': sum(1 for s in stress_values if s >= self.THRESHOLD_EXTREME_PANIC),
        }


# 创建全局实例
unified_stress_model = UnifiedStressModel()


def migrate_to_unified_model(resident):
    """
    迁移函数：将旧的panic_value和emotion合并到stress_level

    【迁移公式】
    stress_level = 0.6 × panic_value + 0.4 × emotion
    """
    panic = getattr(resident, 'panic_value', 0)
    emotion = getattr(resident, 'emotion', 0)

    # 加权平均，恐慌权重略高
    resident.stress_level = 0.6 * panic + 0.4 * emotion
    resident.peak_stress = max(
        getattr(resident, 'peak_panic', 0),
        getattr(resident, 'max_emotion_during_outage', 0)
    )

    return resident.stress_level