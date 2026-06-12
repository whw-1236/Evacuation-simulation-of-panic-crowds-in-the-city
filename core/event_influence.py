# -*- coding: utf-8 -*-
"""
================================================================================
事件影响关系模块 - 各主体事件之间的相互影响
================================================================================
功能：
    1. 定义18种事件之间的影响关系
    2. 提供可信的计算公式
    3. 应用事件影响到仿真状态

================================================================================
【事件详细说明及触发条件】
================================================================================

【政府事件】
  1. 发布应急预警
     - 作用: 降低居民和企业恐慌程度，提高知情率
     - 触发: 停电比例 > 10%
     - 影响: 居民恐慌↓, 知情率↑, 企业恐慌↓

  2. 政府分配资源给电网
     - 作用: 增加电网修复能力，加快修复速度
     - 触发: 停电发生 且 有可用资源
     - 影响: 电网资源↑, 修复能力↑

  3. 政府分配资源给企业
     - 作用: 缓解企业经营危机，降低企业求助强度
     - 触发: 企业求助强度 > 阈值
     - 影响: 企业绝望程度↓, 经济损失↓, 舆情压力↓

  4. 政府分配资源给居民
     - 作用: 降低居民情绪，减少囤积行为
     - 触发: 居民情绪高 或 有囤积行为
     - 影响: 居民情绪↓, 囤积行为↓, 恐慌↓

  5. 实施舆情管理
     - 作用: 降低居民恐慌传播速度，抑制负面情绪扩散
     - 触发: 舆情压力 > 阈值
     - 影响: SEIR传播速度↓, 情绪传播↓

【电网事件】
  6. 区域断电
     - 作用: 触发居民情绪上升、企业停工、恐慌传播
     - 触发: 外部输入停电指令 或 故障传播
     - 影响: 居民情绪↑, 企业停工, 恐慌↑, 关键设施求助↑

  7. 增设临时供电站
     - 作用: 保障关键设施（医院等）供电
     - 触发: 停电区域有一级负荷 且 停电时间长
     - 影响: 关键设施求助↓, 一级负荷恢复供电

  8. 电网实施抢修
     - 作用: 修复进度推进，消耗电网资源
     - 触发: 故障发现 且 资源充足
     - 影响: 修复进度↑, 电网资源↓

  9. 区域恢复供电
     - 作用: 企业恢复生产、居民情绪下降、恐慌缓解
     - 触发: 抢修完成
     - 影响: 企业恢复生产, 居民情绪↓, 恐慌↓, 经济损失停止

【企业事件】
  10. 企业请求资源
      - 作用: 经营危机达到某一程度，请求政府下放资源
      - 触发: 绝望程度 > 0.3 且 停电中
      - 影响: 政府压力↑, 触发政府资源分配

  11. 企业经营危机
      - 作用: 持续停电导致经营危机，增加舆情压力
      - 触发: 停电时长 > 阈值（小型企业4h，中型8h，大型12h）
      - 影响: 舆情压力↑, 政府压力↑, 企业绝望程度↑

  12. 企业停工
      - 作用: 经济损失累积，增加舆情压力
      - 触发: 停电 且 无备用电源
      - 影响: 经济损失累积, 舆情压力↑, 员工情绪↑

  13. 恢复生产
      - 作用: 减少经济损失，降低舆情压力
      - 触发: 恢复供电
      - 影响: 经济损失停止, 舆情压力↓, 企业信心↑

【居民事件】
  14. 居民囤积物资
      - 作用: 造成物资紧缺，需要政府发放资源，加剧恐慌
      - 触发: 恐慌值 > 0.6
      - 影响: 物资紧缺↑, 恐慌传播↑, 政府压力↑

  15. 居民聚集与信息传播
      - 作用: 加快居民群体信息传播速度（SEIR传播）
      - 触发: I状态（传播者）居民 > 阈值
      - 影响: S→E转化加速, 情绪传播↑

  16. 恢复供电请求
      - 作用: 增加政府/电网压力，推动资源调配
      - 触发: 停电 且 情绪 > 0.4
      - 影响: 政府压力↑, 电网压力↑

  17. 居民情绪爆发
      - 作用: 大幅增加舆情压力，可能触发政府紧急响应
      - 触发: 情绪 > 0.7
      - 影响: 舆情压力↑↑, 恐慌传播↑, 政府紧急响应

  18. 居民自救与互助
      - 作用: 缓解局部恐慌，提高社区韧性，减轻政府负担
      - 触发: R状态（恢复者）居民多 或 政府资源下发后
      - 影响: 局部恐慌↓, 情绪↓, E→R转化加速

================================================================================
【事件因果链】
================================================================================

【停电触发链】
  区域断电(6)
    → 企业停工(12) → 企业经营危机(11) → 企业请求资源(10)
    → 居民情绪上升 → 居民情绪爆发(17) → 恢复供电请求(16)
    → 居民恐慌上升 → 居民囤积物资(14) → 居民聚集传播(15)

【政府响应链】
  企业请求资源(10) + 恢复供电请求(16) + 舆情压力
    → 发布应急预警(1)
    → 政府分配资源给电网(2) → 电网抢修(8) → 区域恢复供电(9)
    → 政府分配资源给企业(3) → 缓解经营危机
    → 政府分配资源给居民(4) → 减少囤积行为
    → 实施舆情管理(5) → 降低情绪传播

【恢复链】
  电网抢修(8) → 区域恢复供电(9)
    → 企业恢复生产(13) → 舆情缓解
    → 居民情绪下降 → 居民自救互助(18) → 社区恢复

================================================================================
【主体状态关系】
================================================================================

【政府状态】
  - 压力指数 P_gov = f(企业求助, 居民请求, 舆情压力, 停电比例)
  - 资源水平 R_gov（消耗/补充）
  - 响应状态: 正常/预警/紧急

【电网状态】
  - 资源水平 R_grid
  - 修复能力 = f(资源, 积极程度, 响应效率)
  - 修复进度（各区域）
  - 故障区域列表

【企业状态】
  - 供电状态: 有电/停电/部分停电
  - 绝望程度 D = f(停电时长, 企业类型, 政府补偿)
  - 经济损失（累积）
  - 运营状态: 正常/危机/停工

【居民状态】
  - 供电状态: 有电/停电
  - 情绪值 E ∈ [0,1]
  - 恐慌值 P ∈ [0,1]
  - SEIR状态: S(易感)/E(潜伏)/I(传播)/R(恢复)
  - 行为状态: 正常/囤积/聚集/自救

================================================================================
"""

import math
import random


class EventInfluenceCalculator:
    """
    事件影响计算器

    计算各事件对仿真状态的影响，使用可信的数学公式

    【核心状态变量】
    - 居民情绪 E ∈ [0,1]: 情绪越高越焦虑
    - 居民恐慌 P ∈ [0,1]: 恐慌越高行为越非理性
    - 企业绝望 D ∈ [0,1]: 绝望程度越高求助越强烈
    - 政府压力 G ∈ [0,1]: 压力越大响应越积极
    - 舆情压力 O ∈ [0,1]: 舆情压力越大影响越广
    """

    def __init__(self, config=None):
        """
        初始化事件影响计算器

        参数:
            config: 配置对象
        """
        self.config = config

        # =====================================================================
        # 影响系数配置（可通过config调整）
        # 所有系数经过调优，确保影响合理且稳定
        # =====================================================================
        self.coefficients = {
            # ============ 政府事件影响系数 ============
            # 事件1: 发布应急预警 → 降低居民和企业恐慌程度
            'warning_panic_reduction': 0.2,  # 预警每步降低恐慌传播速度 20%
            'warning_informed_boost': 0.3,  # 预警每步提高知情率 30%
            'warning_enterprise_calm': 0.15,  # 预警对企业恐慌的安抚

            # 事件2: 政府分配资源给电网 → 增加电网修复能力
            'resource_grid_capacity': 0.5,  # 资源转化为修复能力的效率
            'resource_grid_speed': 0.3,  # 资源对修复速度的加成

            # 事件3: 政府分配资源给企业 → 缓解企业经营危机
            'resource_enterprise_relief': 0.4,  # 资源缓解企业危机的效率
            'resource_enterprise_despair': 0.3,  # 资源降低企业绝望程度

            # 事件4: 政府分配资源给居民 → 降低居民情绪，减少囤积
            'resource_resident_emotion': 0.25,  # 资源降低居民情绪的效率
            'resource_resident_hoarding': 0.35,  # 资源减少囤积行为的效率
            'resource_resident_panic': 0.2,  # 资源降低居民恐慌的效率

            # 事件5: 实施舆情管理 → 降低居民恐慌传播速度
            'opinion_manage_spread': 0.25,  # 舆情管理抑制传播的效率
            'opinion_manage_seir': 0.2,  # 舆情管理降低SEIR传播速率

            # ============ 电网事件影响系数 ============
            # 事件6: 区域断电 → 触发居民情绪上升、企业停工
            'blackout_emotion_rate': 0.08,  # 断电每小时情绪上升率
            'blackout_panic_rate': 0.06,  # 断电每小时恐慌上升率
            'blackout_enterprise_crisis': 0.1,  # 断电对企业危机的触发率

            # 事件7: 增设临时供电站 → 保障关键设施供电
            'temp_power_critical': 0.7,  # 临时供电对关键设施的保障率
            'temp_power_panic_relief': 0.15,  # 临时供电对恐慌的缓解

            # 事件8: 电网实施抢修 → 消耗资源，推进修复
            'repair_resource_consume': 0.05,  # 抢修每步消耗资源比例

            # 事件9: 区域恢复供电 → 企业恢复生产、居民情绪下降
            'restore_emotion_drop': 0.4,  # 恢复供电后情绪下降速度
            'restore_panic_drop': 0.35,  # 恢复供电后恐慌下降速度
            'restore_confidence': 0.2,  # 恢复供电后信心恢复

            # ============ 企业事件影响系数 ============
            # 事件10: 企业请求资源 → 经营危机达到程度请求资源
            'request_gov_pressure': 0.25,  # 企业求助对政府压力的影响
            'request_threshold': 0.3,  # 触发求助的绝望程度阈值

            # 事件11: 企业经营危机 → 持续停电产生危机
            'crisis_opinion_impact': 0.2,  # 经营危机对舆情的影响
            'crisis_threshold_small': 4,  # 小型企业危机阈值（小时）
            'crisis_threshold_medium': 8,  # 中型企业危机阈值（小时）
            'crisis_threshold_large': 12,  # 大型企业危机阈值（小时）

            # 事件12: 企业停工 → 经济损失累积
            'shutdown_loss_rate': 0.15,  # 停工每小时损失率
            'shutdown_opinion_impact': 0.1,  # 停工对舆情的影响

            # 事件13: 恢复生产 → 减少损失，降低舆情
            'resume_opinion_relief': 0.25,  # 恢复生产对舆情的缓解
            'resume_confidence_boost': 0.15,  # 恢复生产对信心的提振

            # ============ 居民事件影响系数 ============
            # 事件14: 居民囤积物资 → 造成物资紧缺，加剧恐慌
            'hoarding_panic_spread': 0.12,  # 囤积加剧恐慌传播
            'hoarding_gov_pressure': 0.1,  # 囤积增加政府压力（需发放资源）
            'hoarding_threshold': 0.6,  # 触发囤积的恐慌阈值

            # 事件15: 居民聚集与信息传播 → 加快SEIR传播
            'gather_seir_boost': 0.2,  # 聚集加速SEIR传播
            'gather_emotion_spread': 0.15,  # 聚集加速情绪传播

            # 事件16: 恢复供电请求 → 增加政府/电网压力
            'power_request_gov': 0.15,  # 供电请求对政府压力
            'power_request_grid': 0.1,  # 供电请求对电网压力

            # 事件17: 居民情绪爆发 → 大幅增加舆情压力
            'emotion_burst_opinion': 0.35,  # 情绪爆发对舆情的影响
            'emotion_burst_panic': 0.2,  # 情绪爆发引发恐慌传播
            'emotion_burst_threshold': 0.7,  # 触发情绪爆发的阈值

            # 事件18: 居民自救与互助 → 缓解恐慌，加速恢复
            'self_help_panic_relief': 0.2,  # 自救互助缓解恐慌
            'self_help_emotion_relief': 0.15,  # 自救互助缓解情绪
            'self_help_recovery_boost': 0.1,  # 自救互助加速E→R转化

            # ============ 【公式关联】情绪抑制机制系数 ============
            # 这些系数用于事件之间的因果关系计算，不是直接降低

            # 【机制1】政府舆情管理 → 官方信息传播 → 抑制谣言 → 间接降低情绪
            'opinion_official_info_boost': 0.15,  # 舆情管理增加官方信息传播速度
            'opinion_rumor_suppress_rate': 0.12,  # 舆情管理对谣言的抑制系数
            'opinion_seir_infection_reduction': 0.10,  # 舆情管理降低SEIR感染率（通过信息澄清）

            # 【机制2】社区集体自救的区域效果
            'community_self_help_threshold': 0.25,  # 社区自救生效阈值（该区域25%居民自救）
            'community_emotion_suppression': 0.12,  # 社区自救对情绪的抑制
            'community_panic_suppression': 0.10,  # 社区自救对恐慌的抑制
            'community_neighbor_calm': 0.08,  # 社区自救让邻居也平静

            # 【机制3】物资发放点的效果
            'supply_point_emotion_relief': 0.15,  # 物资发放点降低情绪
            'supply_point_hoarding_reduction': 0.25,  # 物资发放点减少囤积
            'supply_point_panic_relief': 0.12,  # 物资发放点降低恐慌
            'supply_point_coverage': 0.6,  # 物资发放点覆盖率（影响多少居民）
        }

        # 状态追踪
        self.gov_pressure = 0.0  # 政府压力指数
        self.opinion_pressure = 0.0  # 舆情压力指数

    # =========================================================================
    # 政府事件影响计算
    # =========================================================================

    def calc_warning_effect(self, warning_active, residents, enterprises, dt):
        """
        事件1: 发布应急预警的影响

        【作用】降低居民和企业恐慌程度，提高知情率

        【公式】
        - 恐慌抑制 = k_panic × (1 - 平均恐慌) × dt
        - 知情率提升 = k_informed × (1 - 当前知情率) × dt
        - 企业安抚 = k_enterprise × 平均企业绝望程度 × dt

        参数:
            warning_active: 是否发布预警
            residents: 居民列表
            enterprises: 企业列表
            dt: 时间步长

        返回:
            dict: 影响结果
        """
        if not warning_active:
            return {
                'panic_reduction': 0,
                'informed_boost': 0,
                'enterprise_calm': 0
            }

        # 居民恐慌抑制
        panic_reduction = 0
        informed_boost = 0
        if residents:
            avg_panic = sum(r.panic_value for r in residents) / len(residents)
            informed_rate = sum(1 for r in residents if r.informed) / len(residents)

            # 恐慌抑制 = k × (1 - P_avg) × dt
            panic_reduction = self.coefficients['warning_panic_reduction'] * (1 - avg_panic) * dt

            # 知情率提升 = k × (1 - 知情率) × dt
            informed_boost = self.coefficients['warning_informed_boost'] * (1 - informed_rate) * dt

        # 企业安抚
        enterprise_calm = 0
        if enterprises:
            avg_desperation = sum(e.desperation_level for e in enterprises) / len(enterprises)
            enterprise_calm = self.coefficients['warning_enterprise_calm'] * avg_desperation * dt

        return {
            'panic_reduction': min(0.15, panic_reduction),
            'informed_boost': min(0.2, informed_boost),
            'enterprise_calm': min(0.1, enterprise_calm)
        }

    def calc_resource_to_grid_effect(self, resource_amount, grid_agent):
        """
        事件2: 政府分配资源给电网的影响

        【作用】增加电网修复能力，加快修复速度

        【公式】
        - 容量提升 = k_capacity × R × (1 - 当前效率)
        - 速度加成 = k_speed × R / (R + 10)  (Michaelis-Menten型)

        参数:
            resource_amount: 分配的资源量
            grid_agent: 电网Agent

        返回:
            dict: 影响结果
        """
        if resource_amount <= 0:
            return {'capacity_boost': 0, 'speed_boost': 0}

        # 当前资源效率
        current_efficiency = grid_agent.current_resource_level / max(1, grid_agent.base_resource_capacity)

        # 修复能力提升 = k × R × (1 - η)
        capacity_boost = (self.coefficients['resource_grid_capacity'] *
                          resource_amount * (1 - current_efficiency))

        # 修复速度加成 = k × R / (R + 10)，边际效益递减
        speed_boost = (self.coefficients['resource_grid_speed'] *
                       resource_amount / (resource_amount + 10))

        return {
            'capacity_boost': min(20, capacity_boost),
            'speed_boost': min(0.5, speed_boost)
        }

    def calc_resource_to_enterprise_effect(self, resource_amount, enterprises):
        """
        事件3: 政府分配资源给企业的影响

        【作用】缓解企业经营危机，降低企业求助强度

        【公式】
        - 危机缓解 = k_relief × R / (Σ求助强度 + 1)
        - 绝望降低 = k_despair × R × 平均绝望程度

        参数:
            resource_amount: 分配的资源量
            enterprises: 企业列表

        返回:
            dict: 影响结果
        """
        if resource_amount <= 0 or not enterprises:
            return {'crisis_relief': 0, 'desperation_reduction': 0}

        total_request = sum(e.request() for e in enterprises)
        avg_desperation = sum(e.desperation_level for e in enterprises) / len(enterprises)

        # 危机缓解度 = k × R / (Q + 1)
        crisis_relief = (self.coefficients['resource_enterprise_relief'] *
                         resource_amount / (total_request + 1))

        # 绝望程度降低 = k × R × D_avg
        desperation_reduction = (self.coefficients['resource_enterprise_despair'] *
                                 resource_amount * avg_desperation * 0.1)

        return {
            'crisis_relief': min(1.0, crisis_relief),
            'desperation_reduction': min(0.2, desperation_reduction)
        }

    def calc_resource_to_resident_effect(self, resource_amount, residents, dt):
        """
        事件4: 政府分配资源给居民的影响

        【作用】降低居民情绪，减少囤积行为

        【公式】
        - 情绪降低 = k_emotion × R × E_avg × dt
        - 囤积减少 = k_hoarding × (1 - e^(-R))
        - 恐慌降低 = k_panic × R × P_avg × dt

        参数:
            resource_amount: 分配的资源量
            residents: 居民列表
            dt: 时间步长

        返回:
            dict: 影响结果
        """
        if resource_amount <= 0 or not residents:
            return {'emotion_reduction': 0, 'hoarding_reduction': 0, 'panic_reduction': 0}

        avg_emotion = sum(r.emotion for r in residents) / len(residents)
        avg_panic = sum(r.panic_value for r in residents) / len(residents)
        hoarding_count = sum(1 for r in residents if r.is_hoarding)
        hoarding_ratio = hoarding_count / len(residents)

        # 情绪降低 = k × R × E_avg × dt
        emotion_reduction = (self.coefficients['resource_resident_emotion'] *
                             resource_amount * avg_emotion * dt)

        # 囤积减少 = k × (1 - e^(-R)) × 囤积比例
        hoarding_reduction = (self.coefficients['resource_resident_hoarding'] *
                              (1 - math.exp(-resource_amount)) * hoarding_ratio)

        # 恐慌降低 = k × R × P_avg × dt
        panic_reduction = (self.coefficients['resource_resident_panic'] *
                           resource_amount * avg_panic * dt)

        return {
            'emotion_reduction': min(0.25, emotion_reduction),
            'hoarding_reduction': min(0.3, hoarding_reduction),
            'panic_reduction': min(0.2, panic_reduction)
        }

    def calc_opinion_management_effect(self, active, residents, dt):
        """
        事件5: 实施舆情管理的影响 【公式关联版】

        【因果链】
        舆情管理 → 加速官方信息传播 → 抑制谣言相信度 → 减少恐慌增量 → 间接影响情绪

        【公式体系】
        1. 官方信息传播加速:
           d(info_official)/dt += k_boost × (1 - info_official) × dt

        2. 谣言抑制率提升:
           suppression_rate = k_suppress × info_official × rumor_belief

        3. SEIR感染率降低（通过信息澄清）:
           infection_reduction = k_seir × S比例 × I比例 × info_official × dt

        4. 恐慌传播系数降低:
           panic_spread_reduction = k_spread × avg_panic × info_official × dt

        参数:
            active: 是否启动舆情管理
            residents: 居民列表
            dt: 时间步长

        返回:
            dict: 影响结果（用于事件影响计算链）
        """
        if not active or not residents:
            return {
                'official_info_boost': 0,  # 官方信息传播加速量
                'rumor_suppress_rate': 0,  # 谣言抑制率
                'seir_infection_reduction': 0,  # SEIR感染率降低
                'panic_spread_reduction': 0,  # 恐慌传播降低
                'spread_reduction': 0  # 兼容旧接口
            }

        n = len(residents)
        avg_emotion = sum(r.emotion for r in residents) / n
        avg_panic = sum(r.panic_value for r in residents) / n
        avg_rumor = sum(getattr(r, 'rumor_belief', 0) for r in residents) / n
        avg_official = sum(r.info_received.get('official', 0) for r in residents) / n

        # SEIR状态统计
        s_ratio = sum(1 for r in residents if r.state == 'S') / n
        i_ratio = sum(1 for r in residents if r.state == 'I') / n

        # 【公式1】官方信息传播加速
        # 加速量与当前官方信息缺口成正比（越少越需要加速）
        k_boost = self.coefficients['opinion_official_info_boost']
        official_info_boost = k_boost * (1 - avg_official) * dt

        # 【公式2】谣言抑制率
        # 抑制率 = k × 官方信息量 × 当前谣言水平
        k_suppress = self.coefficients['opinion_rumor_suppress_rate']
        rumor_suppress_rate = k_suppress * avg_official * avg_rumor

        # 【公式3】SEIR感染率降低（通过信息澄清）
        # 降低量 = k × S比例 × I比例 × 官方信息量 × dt
        k_seir = self.coefficients['opinion_seir_infection_reduction']
        seir_infection_reduction = k_seir * s_ratio * i_ratio * avg_official * dt

        # 【公式4】恐慌传播降低
        # 降低量 = k_spread × avg_panic × 官方信息量 × dt
        k_spread = self.coefficients['opinion_manage_spread']
        panic_spread_reduction = k_spread * avg_panic * avg_official * dt

        return {
            'official_info_boost': min(0.15, official_info_boost),
            'rumor_suppress_rate': min(0.20, rumor_suppress_rate),
            'seir_infection_reduction': min(0.10, seir_infection_reduction),
            'panic_spread_reduction': min(0.15, panic_spread_reduction),
            'spread_reduction': min(0.15, panic_spread_reduction)  # 兼容旧接口
        }

    # =========================================================================
    # 电网事件影响计算
    # =========================================================================

    def calc_blackout_effect(self, zone_id, zone_status, zone_duration, residents, enterprises, dt):
        """
        事件6: 区域断电的影响

        【作用】触发居民情绪上升、企业停工、恐慌传播

        【公式】
        - 情绪上升 = k_emotion × (1 - E) × 停电时长因子 × dt
        - 恐慌上升 = k_panic × (1 - P) × 停电时长因子 × dt
        - 企业危机触发 = k_crisis × 停电时长 / 阈值

        其中：停电时长因子 = 1 + log(1 + 停电时长)

        参数:
            zone_id: 断电区域ID
            zone_status: 区域供电状态字典
            zone_duration: 区域停电时长字典
            residents: 居民列表
            enterprises: 企业列表
            dt: 时间步长

        返回:
            dict: 影响结果
        """
        if zone_status.get(zone_id, True):  # 有电，无影响
            return {
                'emotion_rise': 0,
                'panic_rise': 0,
                'enterprise_crisis': 0,
                'critical_help': 0
            }

        # 该区域的居民和企业
        zone_residents = [r for r in residents if r.zone == zone_id]
        zone_enterprises = [e for e in enterprises if e.zone == zone_id]

        # 停电时长因子 = 1 + log(1 + 时长)，时间越长影响越大但边际递减
        duration = zone_duration.get(zone_id, 0)
        duration_factor = 1 + math.log(1 + duration)

        # 计算平均情绪和恐慌
        if zone_residents:
            avg_emotion = sum(r.emotion for r in zone_residents) / len(zone_residents)
            avg_panic = sum(r.panic_value for r in zone_residents) / len(zone_residents)
        else:
            avg_emotion = 0
            avg_panic = 0

        # 情绪上升 = k × (1 - E) × 时长因子 × dt
        emotion_rise = (self.coefficients['blackout_emotion_rate'] *
                        (1 - avg_emotion) * duration_factor * dt)

        # 恐慌上升 = k × (1 - P) × 时长因子 × dt
        panic_rise = (self.coefficients['blackout_panic_rate'] *
                      (1 - avg_panic) * duration_factor * dt)

        # 企业危机触发 = k × 停电企业数 × 时长因子
        enterprise_crisis = (self.coefficients['blackout_enterprise_crisis'] *
                             len(zone_enterprises) * duration_factor)

        # 计算停电比例
        total_zones = len(zone_status)
        outage_zones = sum(1 for st in zone_status.values() if not st)
        outage_ratio = outage_zones / max(1, total_zones)

        # 关键设施求助 = 停电比例 × (1 + 情绪因子 + 恐慌因子)
        critical_help = outage_ratio * (1 + avg_emotion * 0.3 + avg_panic * 0.3)

        return {
            'emotion_rise': min(0.15, emotion_rise),
            'panic_rise': min(0.12, panic_rise),
            'enterprise_crisis': enterprise_crisis,
            'critical_help': min(1.0, critical_help)
        }

    def calc_temp_power_effect(self, active, critical_agents, zone_status):
        """
        事件7: 增设临时供电站的影响

        【作用】保障关键设施（医院等）供电，降低关键设施求助

        【公式】
        - 关键设施保障 = k_critical × 临时站数量 / 关键设施数量
        - 恐慌缓解 = k_panic × 停电比例

        参数:
            active: 是否设置临时供电站
            critical_agents: 关键设施Agent列表
            zone_status: 区域供电状态

        返回:
            dict: 影响结果
        """
        if not active:
            return {'critical_relief': 0, 'panic_relief': 0}

        n_criticals = len(critical_agents) if critical_agents else 1

        # 关键设施保障 = k × 1 / n_criticals
        critical_relief = self.coefficients['temp_power_critical'] / n_criticals

        # 停电比例
        outage_ratio = sum(1 for st in zone_status.values() if not st) / max(1, len(zone_status))

        # 恐慌缓解 = k × 停电比例（停电越多，临时供电站的缓解作用越明显）
        panic_relief = self.coefficients['temp_power_panic_relief'] * outage_ratio

        return {
            'critical_relief': min(0.8, critical_relief),
            'panic_relief': min(0.1, panic_relief)
        }

    def calc_repair_effect(self, ongoing_repairs, grid_agent, config=None):
        """
        事件8: 电网实施抢修的影响

        【作用】修复进度推进，消耗电网资源

        【公式】
        - 修复进度 = 修复能力 / 总修复难度
        - 资源消耗 = k × 正在修复区域数

        参数:
            ongoing_repairs: 正在修复的区域字典
            grid_agent: 电网Agent
            config: 配置对象

        返回:
            dict: 影响结果
        """
        if not ongoing_repairs:
            return {
                'repair_progress': 0,
                'zones_repairing': 0,
                'resource_consumed': 0
            }

        # 计算修复能力
        capacity = grid_agent.calculate_repair_capacity(config)

        # 平均修复难度
        total_difficulty = sum(info.get('repair_difficulty', 1.0)
                               for info in ongoing_repairs.values())
        avg_difficulty = total_difficulty / len(ongoing_repairs)

        # 修复进度 = 能力 / 总难度
        repair_progress = capacity / max(0.1, total_difficulty)

        # 资源消耗 = k × 修复区域数
        resource_consumed = self.coefficients['repair_resource_consume'] * len(ongoing_repairs)

        return {
            'repair_progress': repair_progress,
            'zones_repairing': len(ongoing_repairs),
            'resource_consumed': resource_consumed
        }

    def calc_restore_power_effect(self, restored_zones, residents, enterprises, dt):
        """
        事件9: 区域恢复供电的影响

        【作用】企业恢复生产、居民情绪下降、恐慌缓解

        【重要】长尾效应设计
        恢复供电只是开始，恐慌的实际恢复主要依靠：
        1. 居民自身的_update_panic()方法中的渐进式恢复
        2. 心理创伤机制（peak_panic, total_outage_hours）

        此方法只提供一个**小幅**即时缓解效果（心理上"看到希望"），
        真正的恢复需要时间。这符合现实中PTSD的长尾恢复特征。

        【公式】（已限制最大效果，防止瞬间恢复）
        - 情绪下降 = min(0.05, k_emotion × log(1+恢复区域数) × E_avg × dt)
        - 恐慌下降 = min(0.03, k_panic × log(1+恢复区域数) × P_avg × dt)
        - 信心恢复 = k_confidence × 恢复比例

        参数:
            restored_zones: 恢复供电的区域列表
            residents: 居民列表
            enterprises: 企业列表
            dt: 时间步长

        返回:
            dict: 影响结果
        """
        if not restored_zones:
            return {
                'emotion_drop': 0,
                'panic_drop': 0,
                'confidence_boost': 0,
                'production_recovery': 0
            }

        # 恢复区域内的居民和企业
        restored_residents = [r for r in residents if r.zone in restored_zones]
        restored_enterprises = [e for e in enterprises if e.zone in restored_zones]

        # 计算平均情绪和恐慌
        if restored_residents:
            avg_emotion = sum(r.emotion for r in restored_residents) / len(restored_residents)
            avg_panic = sum(r.panic_value for r in restored_residents) / len(restored_residents)
        else:
            avg_emotion = 0
            avg_panic = 0

        # 【长尾效应】使用对数函数，防止大量区域同时恢复时效果过大
        # 1个区域恢复 vs 100个区域恢复，效果差距不应该是100倍
        import math
        zone_factor = math.log(1 + len(restored_zones))  # 对数平滑

        # 情绪下降（即时缓解很小，主要靠后续自然恢复）
        emotion_drop = (self.coefficients['restore_emotion_drop'] * 0.1 *  # 系数缩小10倍
                        zone_factor * avg_emotion * dt)

        # 恐慌下降（即时效果更小，因为恐慌有长尾效应）
        # 看到恢复供电只是"看到希望"，不等于恐慌消失
        panic_drop = (self.coefficients['restore_panic_drop'] * 0.05 *  # 系数缩小20倍
                      zone_factor * avg_panic * dt)

        # 恢复比例
        total_residents = len(residents) if residents else 1
        restore_ratio = len(restored_residents) / total_residents

        # 信心恢复 = k × 恢复比例
        confidence_boost = self.coefficients['restore_confidence'] * restore_ratio

        # 生产恢复比例
        total_ent = len(enterprises) if enterprises else 1
        production_recovery = len(restored_enterprises) / total_ent

        # 【严格限制】即时效果上限，防止瞬间恢复
        return {
            'emotion_drop': min(0.05, emotion_drop),  # 最多降低5%
            'panic_drop': min(0.03, panic_drop),  # 最多降低3%（恐慌更顽固）
            'confidence_boost': min(0.2, confidence_boost),
            'production_recovery': production_recovery
        }

    # =========================================================================
    # 企业事件影响计算
    # =========================================================================

    def calc_enterprise_request_effect(self, enterprises):
        """
        事件10: 企业请求资源的影响

        【作用】经营危机达到某一程度，请求政府下放资源
        【触发条件】绝望程度 > 0.3 且 停电中

        【公式】
        - 政府压力增加 = k × Σ(求助强度_i × 绝望程度_i)
        - 触发政府资源分配

        参数:
            enterprises: 企业列表

        返回:
            dict: 影响结果
        """
        if not enterprises:
            return {'gov_pressure': 0, 'requesting_count': 0}

        # 筛选正在请求资源的企业（绝望程度 > 阈值）
        threshold = self.coefficients['request_threshold']
        requesting = [e for e in enterprises
                      if e.desperation_level > threshold and not e.powered]

        if not requesting:
            return {'gov_pressure': 0, 'requesting_count': 0}

        # 政府压力 = k × Σ(Q_i × D_i)
        total_pressure = sum(e.request() * e.desperation_level for e in requesting)
        gov_pressure = self.coefficients['request_gov_pressure'] * total_pressure

        return {
            'gov_pressure': min(1.0, gov_pressure),
            'requesting_count': len(requesting)
        }

    def calc_enterprise_crisis_effect(self, enterprises, dt):
        """
        事件11: 企业经营危机的影响

        【作用】持续停电多久产生经营危机，增加舆情压力
        【触发条件】停电时长 > 阈值（小型4h，中型8h，大型12h）

        【公式】
        - 舆情压力 = k × 危机企业比例 × 平均绝望程度²
        - 政府压力 = f(危机严重程度)

        参数:
            enterprises: 企业列表
            dt: 时间步长

        返回:
            dict: 影响结果
        """
        if not enterprises:
            return {'opinion_pressure': 0, 'gov_pressure': 0, 'crisis_count': 0}

        # 按企业类型判断是否达到危机阈值
        crisis_enterprises = []
        for e in enterprises:
            if not e.powered:
                hours = e.outage_duration / 2.0  # 假设dt=0.5小时
                threshold = {
                    '小型': self.coefficients['crisis_threshold_small'],
                    '中型': self.coefficients['crisis_threshold_medium'],
                    '大型': self.coefficients['crisis_threshold_large']
                }.get(e.enterprise_type, 8)

                if hours >= threshold:
                    crisis_enterprises.append(e)

        if not crisis_enterprises:
            return {'opinion_pressure': 0, 'gov_pressure': 0, 'crisis_count': 0}

        crisis_ratio = len(crisis_enterprises) / len(enterprises)
        avg_desperation = sum(e.desperation_level for e in crisis_enterprises) / len(crisis_enterprises)

        # 舆情压力 = k × 危机比例 × D²（非线性增长）
        opinion_pressure = (self.coefficients['crisis_opinion_impact'] *
                            crisis_ratio * avg_desperation ** 2)

        # 政府压力 = 舆情压力的一部分
        gov_pressure = opinion_pressure * 0.6

        return {
            'opinion_pressure': min(0.5, opinion_pressure),
            'gov_pressure': min(0.3, gov_pressure),
            'crisis_count': len(crisis_enterprises)
        }

    def calc_shutdown_effect(self, enterprises, dt):
        """
        事件12: 企业停工的影响

        【作用】经济损失累积，增加舆情压力
        【触发条件】停电 且 无备用电源

        【公式】
        - 经济损失 = k_loss × Σ(停工企业损失率) × dt
        - 舆情压力 = k_opinion × 停工比例² × (1 + 平均停工时长/24)

        参数:
            enterprises: 企业列表
            dt: 时间步长

        返回:
            dict: 影响结果
        """
        if not enterprises:
            return {'economic_loss': 0, 'opinion_pressure': 0, 'shutdown_count': 0}

        shutdown_enterprises = [e for e in enterprises if e.is_shutdown]

        if not shutdown_enterprises:
            return {'economic_loss': 0, 'opinion_pressure': 0, 'shutdown_count': 0}

        shutdown_ratio = len(shutdown_enterprises) / len(enterprises)

        # 经济损失 = k × Σ(损失率) × dt
        total_loss_rate = sum(e.cost_rate for e in shutdown_enterprises)
        economic_loss = self.coefficients['shutdown_loss_rate'] * total_loss_rate * dt

        # 平均停工时长
        avg_duration = sum(e.outage_duration for e in shutdown_enterprises) / len(shutdown_enterprises)

        # 舆情压力 = k × 比例² × (1 + 时长/24)
        duration_factor = 1 + avg_duration / 24.0
        opinion_pressure = (self.coefficients['shutdown_opinion_impact'] *
                            shutdown_ratio ** 2 * duration_factor)

        return {
            'economic_loss': economic_loss,
            'opinion_pressure': min(0.4, opinion_pressure),
            'shutdown_count': len(shutdown_enterprises)
        }

    def calc_resume_production_effect(self, enterprises):
        """
        事件13: 恢复生产的影响

        【作用】减少经济损失，降低舆情压力，提振信心
        【触发条件】恢复供电

        【公式】
        - 舆情缓解 = k_opinion × 恢复企业比例
        - 信心提振 = k_confidence × 恢复企业比例 × 平均之前绝望程度

        参数:
            enterprises: 企业列表

        返回:
            dict: 影响结果
        """
        if not enterprises:
            return {'opinion_relief': 0, 'confidence_boost': 0, 'resumed_count': 0}

        resumed_enterprises = [e for e in enterprises if e.just_resumed]

        if not resumed_enterprises:
            return {'opinion_relief': 0, 'confidence_boost': 0, 'resumed_count': 0}

        resume_ratio = len(resumed_enterprises) / len(enterprises)

        # 舆情缓解 = k × 恢复比例
        opinion_relief = self.coefficients['resume_opinion_relief'] * resume_ratio

        # 信心提振 = k × 恢复比例（恢复越多，市场信心提振越大）
        confidence_boost = self.coefficients['resume_confidence_boost'] * resume_ratio

        return {
            'opinion_relief': min(0.3, opinion_relief),
            'confidence_boost': min(0.2, confidence_boost),
            'resumed_count': len(resumed_enterprises)
        }

    # =========================================================================
    # 居民事件影响计算
    # =========================================================================

    def calc_hoarding_effect(self, residents, dt):
        """
        事件14: 居民囤积物资的影响

        【作用】造成物资紧缺，需要政府发放资源，加剧恐慌
        【触发条件】恐慌值 > 0.6

        【公式】
        - 恐慌传播 = k_panic × 囤积比例 × (1 + P_avg) × dt
        - 政府压力 = k_gov × 囤积比例（需要发放资源）

        参数:
            residents: 居民列表
            dt: 时间步长

        返回:
            dict: 影响结果
        """
        if not residents:
            return {'panic_spread': 0, 'gov_pressure': 0, 'hoarding_count': 0}

        # 筛选正在囤积的居民（恐慌 > 阈值）
        threshold = self.coefficients['hoarding_threshold']
        hoarding_residents = [r for r in residents if r.panic_value > threshold]
        hoarding_ratio = len(hoarding_residents) / len(residents)

        if hoarding_ratio == 0:
            return {'panic_spread': 0, 'gov_pressure': 0, 'hoarding_count': 0}

        avg_panic = sum(r.panic_value for r in residents) / len(residents)

        # 恐慌传播加速 = k × 囤积比例 × (1 + P_avg) × dt
        panic_spread = (self.coefficients['hoarding_panic_spread'] *
                        hoarding_ratio * (1 + avg_panic) * dt)

        # 政府压力增加 = k × 囤积比例（需要政府发放资源）
        gov_pressure = self.coefficients['hoarding_gov_pressure'] * hoarding_ratio

        return {
            'panic_spread': min(0.25, panic_spread),
            'gov_pressure': min(0.2, gov_pressure),
            'hoarding_count': len(hoarding_residents)
        }

    def calc_gather_spread_effect(self, residents, dt):
        """
        事件15: 居民聚集与信息传播的影响

        【作用】加快居民群体信息传播速度（SEIR传播）
        【触发条件】I状态（传播者）居民比例 > 阈值

        【公式】
        - SEIR加速 = k_seir × 聚集比例 × I比例 × dt
        - 情绪传播 = k_emotion × 聚集比例 × E_avg × dt

        参数:
            residents: 居民列表
            dt: 时间步长

        返回:
            dict: 影响结果
        """
        if not residents:
            return {'seir_boost': 0, 'emotion_spread': 0, 'gathering_count': 0}

        # 聚集的居民（I状态或E状态）
        gathering_residents = [r for r in residents if r.state in ['I', 'E']]
        gathering_ratio = len(gathering_residents) / len(residents)

        # I状态（传播者）比例
        i_ratio = sum(1 for r in residents if r.state == 'I') / len(residents)

        # 平均情绪
        avg_emotion = sum(r.emotion for r in residents) / len(residents)

        # SEIR传播加速 = k × 聚集比例 × I比例 × dt
        seir_boost = (self.coefficients['gather_seir_boost'] *
                      gathering_ratio * (i_ratio + 0.1) * dt)  # +0.1避免为0

        # 情绪传播加速 = k × 聚集比例 × E_avg × dt
        emotion_spread = (self.coefficients['gather_emotion_spread'] *
                          gathering_ratio * avg_emotion * dt)

        return {
            'seir_boost': min(0.15, seir_boost),
            'emotion_spread': min(0.12, emotion_spread),
            'gathering_count': len(gathering_residents)
        }

    def calc_power_request_effect(self, residents):
        """
        事件16: 恢复供电请求的影响

        【作用】增加政府/电网压力，推动资源调配
        【触发条件】停电 且 情绪 > 0.4

        【公式】
        - 政府压力 = k_gov × 请求比例 × E_avg
        - 电网压力 = k_grid × 请求比例 × (1 + 停电时长因子)

        参数:
            residents: 居民列表

        返回:
            dict: 影响结果
        """
        if not residents:
            return {'gov_pressure': 0, 'grid_pressure': 0, 'requesting_count': 0}

        # 筛选正在请求恢复供电的居民
        requesting_residents = [r for r in residents
                                if not r.powered and r.emotion > 0.4]
        request_ratio = len(requesting_residents) / len(residents)

        if request_ratio == 0:
            return {'gov_pressure': 0, 'grid_pressure': 0, 'requesting_count': 0}

        avg_emotion = sum(r.emotion for r in residents) / len(residents)

        # 平均停电时长因子
        outage_residents = [r for r in residents if not r.powered]
        if outage_residents:
            avg_outage = sum(r.t_outage for r in outage_residents) / len(outage_residents)
            duration_factor = 1 + math.log(1 + avg_outage)
        else:
            duration_factor = 1

        # 政府压力 = k × 请求比例 × E_avg
        gov_pressure = (self.coefficients['power_request_gov'] *
                        request_ratio * avg_emotion)

        # 电网压力 = k × 请求比例 × 时长因子
        grid_pressure = (self.coefficients['power_request_grid'] *
                         request_ratio * duration_factor)

        return {
            'gov_pressure': min(0.3, gov_pressure),
            'grid_pressure': min(0.2, grid_pressure),
            'requesting_count': len(requesting_residents)
        }

    def calc_emotion_burst_effect(self, residents, dt):
        """
        事件17: 居民情绪爆发的影响

        【作用】大幅增加舆情压力，可能触发政府紧急响应
        【触发条件】情绪 > 0.7

        【公式】
        - 舆情压力 = k_opinion × 爆发比例 × E_avg² × dt
        - 恐慌传播 = k_panic × 爆发比例 × (1 - P_avg) × dt
        - 触发政府紧急响应

        参数:
            residents: 居民列表
            dt: 时间步长

        返回:
            dict: 影响结果
        """
        if not residents:
            return {
                'opinion_pressure': 0,
                'panic_spread': 0,
                'trigger_emergency': False,
                'burst_count': 0
            }

        # 筛选情绪爆发的居民
        threshold = self.coefficients['emotion_burst_threshold']
        burst_residents = [r for r in residents if r.emotion > threshold]
        burst_ratio = len(burst_residents) / len(residents)

        if burst_ratio == 0:
            return {
                'opinion_pressure': 0,
                'panic_spread': 0,
                'trigger_emergency': False,
                'burst_count': 0
            }

        avg_emotion = sum(r.emotion for r in residents) / len(residents)
        avg_panic = sum(r.panic_value for r in residents) / len(residents)

        # 舆情压力 = k × 爆发比例 × E²（非线性增长）
        opinion_pressure = (self.coefficients['emotion_burst_opinion'] *
                            burst_ratio * avg_emotion ** 2)

        # 恐慌传播 = k × 爆发比例 × (1 - P_avg)
        panic_spread = (self.coefficients['emotion_burst_panic'] *
                        burst_ratio * (1 - avg_panic) * dt)

        # 是否触发政府紧急响应（爆发比例 > 30%）
        trigger_emergency = burst_ratio > 0.3

        return {
            'opinion_pressure': min(0.5, opinion_pressure),
            'panic_spread': min(0.25, panic_spread),
            'trigger_emergency': trigger_emergency,
            'burst_count': len(burst_residents)
        }

    def calc_self_help_effect(self, residents, dt):
        """
        事件18: 居民自救与互助的影响

        【作用】缓解局部恐慌，提高社区韧性，减轻政府负担
        【触发条件】R状态（恢复者）居民多 或 政府资源下发后

        【公式】
        - 恐慌缓解 = k_panic × 自救比例 × (1 - P_avg) × dt
        - 情绪缓解 = k_emotion × 自救比例 × E_avg × dt
        - E→R转化加速 = k_recovery × 自救比例

        参数:
            residents: 居民列表
            dt: 时间步长

        返回:
            dict: 影响结果
        """
        if not residents:
            return {
                'panic_relief': 0,
                'emotion_relief': 0,
                'recovery_boost': 0,
                'helping_count': 0
            }

        # 筛选在自救互助的居民（R状态或低情绪状态）
        helping_residents = [r for r in residents
                             if r.state == 'R' or (r.emotion < 0.3 and r.informed)]
        help_ratio = len(helping_residents) / len(residents)

        if help_ratio == 0:
            return {
                'panic_relief': 0,
                'emotion_relief': 0,
                'recovery_boost': 0,
                'helping_count': 0
            }

        avg_panic = sum(r.panic_value for r in residents) / len(residents)
        avg_emotion = sum(r.emotion for r in residents) / len(residents)

        # 恐慌缓解 = k × 自救比例 × (1 - P_avg) × dt
        panic_relief = (self.coefficients['self_help_panic_relief'] *
                        help_ratio * (1 - avg_panic) * dt)

        # 情绪缓解 = k × 自救比例 × E_avg × dt
        emotion_relief = (self.coefficients['self_help_emotion_relief'] *
                          help_ratio * avg_emotion * dt)

        # E→R转化加速 = k × 自救比例
        recovery_boost = self.coefficients['self_help_recovery_boost'] * help_ratio

        return {
            'panic_relief': min(0.15, panic_relief),
            'emotion_relief': min(0.12, emotion_relief),
            'recovery_boost': min(0.1, recovery_boost),
            'helping_count': len(helping_residents)
        }

    def calc_community_collective_self_help_effect(self, residents, dt):
        """
        【新增】社区级别集体自救的影响

        【作用】
        当一个社区（区域）内有足够多的居民参与自救时，
        会产生社区级别的情绪抑制效果，影响整个区域

        【触发条件】区域内自救比例 > 25%

        【公式】
        - 区域情绪抑制 = k_emotion × (自救比例 - 阈值) × E_avg × dt
        - 区域恐慌抑制 = k_panic × (自救比例 - 阈值) × P_avg × dt
        - 邻居安抚效应 = k_neighbor × 自救比例 × (高情绪邻居比例)

        参数:
            residents: 居民列表
            dt: 时间步长

        返回:
            dict: 按区域划分的影响结果
        """
        if not residents:
            return {'zone_effects': {}, 'total_suppression': 0}

        # 按区域分组居民
        zone_residents = {}
        for r in residents:
            zone = getattr(r, 'zone', 'unknown')
            if zone not in zone_residents:
                zone_residents[zone] = []
            zone_residents[zone].append(r)

        zone_effects = {}
        total_emotion_suppression = 0
        total_panic_suppression = 0
        threshold = self.coefficients['community_self_help_threshold']

        for zone, zone_res in zone_residents.items():
            n = len(zone_res)
            if n < 3:  # 区域人数太少，跳过
                continue

            # 计算该区域的自救比例
            helping_count = sum(1 for r in zone_res
                                if getattr(r, 'is_self_helping', False) or r.state == 'R')
            help_ratio = helping_count / n

            # 只有自救比例超过阈值时，才产生社区级别效果
            if help_ratio <= threshold:
                zone_effects[zone] = {'emotion_suppression': 0, 'panic_suppression': 0, 'active': False}
                continue

            # 超出阈值的部分产生效果
            effective_ratio = help_ratio - threshold

            # 区域平均情绪和恐慌
            avg_emotion = sum(r.emotion for r in zone_res) / n
            avg_panic = sum(r.panic_value for r in zone_res) / n

            # 高情绪居民比例
            high_emotion_ratio = sum(1 for r in zone_res if r.emotion > 0.5) / n

            # 区域情绪抑制 = k × 有效比例 × E_avg × dt
            emotion_suppression = (self.coefficients['community_emotion_suppression'] *
                                   effective_ratio * avg_emotion * dt)

            # 区域恐慌抑制 = k × 有效比例 × P_avg × dt
            panic_suppression = (self.coefficients['community_panic_suppression'] *
                                 effective_ratio * avg_panic * dt)

            # 邻居安抚效应 = k × 自救比例 × 高情绪比例
            # 高情绪的居民看到邻居在自救，会受到安抚
            neighbor_calm = (self.coefficients['community_neighbor_calm'] *
                             help_ratio * high_emotion_ratio * dt)

            zone_effects[zone] = {
                'emotion_suppression': min(0.15, emotion_suppression + neighbor_calm),
                'panic_suppression': min(0.12, panic_suppression),
                'help_ratio': help_ratio,
                'active': True
            }

            total_emotion_suppression += emotion_suppression + neighbor_calm
            total_panic_suppression += panic_suppression

        # 计算活跃社区数量
        active_communities = sum(1 for e in zone_effects.values() if e.get('active', False))

        return {
            'zone_effects': zone_effects,
            'total_emotion_suppression': min(0.25, total_emotion_suppression),
            'total_panic_suppression': min(0.2, total_panic_suppression),
            'active_communities': active_communities
        }

    def calc_supply_point_effect(self, gov_resource_active, residents, dt):
        """
        【新增】物资发放点的影响

        【作用】
        当政府分配资源给居民时，物资发放点会：
        1. 直接降低领取物资居民的情绪
        2. 减少囤积行为（有序领取代替恐慌囤积）
        3. 降低恐慌（"有人管、有物资"的安心感）

        【触发条件】政府分配资源给居民 且 有居民在囤积

        【公式】
        - 情绪降低 = k_emotion × 覆盖率 × E_avg × (囤积比例) × dt
        - 囤积减少 = k_hoarding × 覆盖率 × 囤积比例
        - 恐慌降低 = k_panic × 覆盖率 × P_avg × dt

        参数:
            gov_resource_active: 政府是否在分配资源给居民
            residents: 居民列表
            dt: 时间步长

        返回:
            dict: 影响结果
        """
        if not gov_resource_active or not residents:
            return {
                'emotion_relief': 0,
                'hoarding_reduction': 0,
                'panic_relief': 0,
                'residents_served': 0
            }

        n = len(residents)

        # 统计囤积的居民
        hoarding_residents = [r for r in residents if getattr(r, 'is_hoarding', False)]
        hoarding_ratio = len(hoarding_residents) / n

        if hoarding_ratio == 0:
            # 没人囤积，物资发放点效果减弱但仍有安抚作用
            avg_emotion = sum(r.emotion for r in residents) / n
            avg_panic = sum(r.panic_value for r in residents) / n
            coverage = self.coefficients['supply_point_coverage']

            # 即使没人囤积，物资发放点也有预防性安抚效果
            emotion_relief = (self.coefficients['supply_point_emotion_relief'] *
                              0.3 * coverage * avg_emotion * dt)
            panic_relief = (self.coefficients['supply_point_panic_relief'] *
                            0.3 * coverage * avg_panic * dt)

            return {
                'emotion_relief': min(0.05, emotion_relief),
                'hoarding_reduction': 0,
                'panic_relief': min(0.04, panic_relief),
                'residents_served': int(n * coverage * 0.3)
            }

        # 平均情绪和恐慌
        avg_emotion = sum(r.emotion for r in residents) / n
        avg_panic = sum(r.panic_value for r in residents) / n

        # 物资发放点覆盖率
        coverage = self.coefficients['supply_point_coverage']

        # 情绪降低 = k × 覆盖率 × E_avg × 囤积比例 × dt
        # 正在囤积的人去领取物资后，情绪会明显下降
        emotion_relief = (self.coefficients['supply_point_emotion_relief'] *
                          coverage * avg_emotion * hoarding_ratio * dt)

        # 囤积减少 = k × 覆盖率 × 囤积比例
        # "有序领取"代替"恐慌囤积"
        hoarding_reduction = (self.coefficients['supply_point_hoarding_reduction'] *
                              coverage * hoarding_ratio)

        # 恐慌降低 = k × 覆盖率 × P_avg × dt
        # "政府在管事"的安心感
        panic_relief = (self.coefficients['supply_point_panic_relief'] *
                        coverage * avg_panic * dt)

        # 预估服务的居民数量
        residents_served = int(n * coverage * (hoarding_ratio + 0.2))

        return {
            'emotion_relief': min(0.18, emotion_relief),
            'hoarding_reduction': min(0.3, hoarding_reduction),
            'panic_relief': min(0.15, panic_relief),
            'residents_served': residents_served
        }

    # =========================================================================
    # 综合影响计算
    # =========================================================================

    def calculate_all_effects(self, sim, dt):
        """
        计算所有事件的综合影响

        参数:
            sim: 仿真对象
            dt: 时间步长

        返回:
            dict: 所有事件的影响汇总
        """
        effects = {
            'government': {},
            'grid': {},
            'enterprise': {},
            'resident': {},
            'summary': {}
        }

        # ==================== 政府事件 ====================
        # 事件1: 发布应急预警
        effects['government']['warning'] = self.calc_warning_effect(
            sim.gov.emergency_warning_issued, sim.residents, sim.enterprises, dt)

        # 事件2: 政府分配资源给电网
        effects['government']['resource_grid'] = self.calc_resource_to_grid_effect(
            sim.gov.last_deployment * 0.5, sim.grid)

        # 事件3: 政府分配资源给企业
        effects['government']['resource_enterprise'] = self.calc_resource_to_enterprise_effect(
            sim.gov.last_deployment * 0.3, sim.enterprises)

        # 事件4: 政府分配资源给居民
        effects['government']['resource_resident'] = self.calc_resource_to_resident_effect(
            sim.gov.last_deployment * 0.2, sim.residents, dt)

        # 事件5: 实施舆情管理
        effects['government']['opinion_manage'] = self.calc_opinion_management_effect(
            sim.gov.public_opinion_active, sim.residents, dt)

        # ==================== 电网事件 ====================
        # 事件6: 区域断电
        for zone_id in sim.zone_status:
            if not sim.zone_status[zone_id]:
                effects['grid'][f'blackout_{zone_id}'] = self.calc_blackout_effect(
                    zone_id, sim.zone_status, sim.zone_duration,
                    sim.residents, sim.enterprises, dt)

        # 事件7: 增设临时供电站
        effects['grid']['temp_power'] = self.calc_temp_power_effect(
            sim.grid.is_setting_temp_power, sim.criticals, sim.zone_status)

        # 事件8: 电网实施抢修
        effects['grid']['repair'] = self.calc_repair_effect(
            sim.grid.ongoing_repairs, sim.grid, sim.config)

        # 事件9: 区域恢复供电
        restored_zones = getattr(sim, '_just_restored_zones', [])
        effects['grid']['restore'] = self.calc_restore_power_effect(
            restored_zones, sim.residents, sim.enterprises, dt)

        # ==================== 企业事件 ====================
        # 事件10: 企业请求资源
        effects['enterprise']['request'] = self.calc_enterprise_request_effect(sim.enterprises)

        # 事件11: 企业经营危机
        effects['enterprise']['crisis'] = self.calc_enterprise_crisis_effect(sim.enterprises, dt)

        # 事件12: 企业停工
        effects['enterprise']['shutdown'] = self.calc_shutdown_effect(sim.enterprises, dt)

        # 事件13: 恢复生产
        effects['enterprise']['resume'] = self.calc_resume_production_effect(sim.enterprises)

        # ==================== 居民事件 ====================
        # 事件14: 居民囤积物资
        effects['resident']['hoarding'] = self.calc_hoarding_effect(sim.residents, dt)

        # 事件15: 居民聚集与信息传播
        effects['resident']['gather_spread'] = self.calc_gather_spread_effect(sim.residents, dt)

        # 事件16: 恢复供电请求
        effects['resident']['power_request'] = self.calc_power_request_effect(sim.residents)

        # 事件17: 居民情绪爆发
        effects['resident']['emotion_burst'] = self.calc_emotion_burst_effect(sim.residents, dt)

        # 事件18: 居民自救与互助
        effects['resident']['self_help'] = self.calc_self_help_effect(sim.residents, dt)

        # ==================== 【新增】情绪抑制机制 ====================

        # 【机制2】社区集体自救
        effects['resident']['community_self_help'] = self.calc_community_collective_self_help_effect(
            sim.residents, dt)

        # 【机制3】物资发放点
        effects['resident']['supply_point'] = self.calc_supply_point_effect(
            sim.gov.resource_to_resident, sim.residents, dt)

        # ==================== 汇总关键指标 ====================
        effects['summary'] = self._summarize_effects(effects)

        # 更新压力指数
        self._update_pressure_indices(effects)

        return effects

    def _summarize_effects(self, effects):
        """汇总所有效果到关键指标"""
        summary = {
            'total_panic_change': 0.0,
            'total_emotion_change': 0.0,
            'total_opinion_pressure': 0.0,
            'total_gov_pressure': 0.0,
            'total_repair_boost': 0.0,
            # 【新增】情绪抑制统计
            'total_emotion_suppression': 0.0,
            'active_suppression_mechanisms': 0,
        }

        gov_effects = effects.get('government', {})
        grid_effects = effects.get('grid', {})
        ent_effects = effects.get('enterprise', {})
        res_effects = effects.get('resident', {})

        # ============ 恐慌变化汇总 ============
        # 降低恐慌的因素
        if 'warning' in gov_effects:
            summary['total_panic_change'] -= gov_effects['warning'].get('panic_reduction', 0)
        if 'resource_resident' in gov_effects:
            summary['total_panic_change'] -= gov_effects['resource_resident'].get('panic_reduction', 0)
        if 'temp_power' in grid_effects:
            summary['total_panic_change'] -= grid_effects['temp_power'].get('panic_relief', 0)
        if 'restore' in grid_effects:
            summary['total_panic_change'] -= grid_effects['restore'].get('panic_drop', 0)
        if 'self_help' in res_effects:
            summary['total_panic_change'] -= res_effects['self_help'].get('panic_relief', 0)

        # 【新增】社区集体自救降低恐慌
        if 'community_self_help' in res_effects:
            summary['total_panic_change'] -= res_effects['community_self_help'].get('total_panic_suppression', 0)

        # 【新增】物资发放点降低恐慌
        if 'supply_point' in res_effects:
            summary['total_panic_change'] -= res_effects['supply_point'].get('panic_relief', 0)

        # 增加恐慌的因素
        # 【修复】不再累加所有区域的panic_rise，而是取平均值
        blackout_effects_panic = [val for key, val in grid_effects.items() if key.startswith('blackout_')]
        if blackout_effects_panic:
            avg_panic_rise = sum(e.get('panic_rise', 0) for e in blackout_effects_panic) / len(blackout_effects_panic)
            summary['total_panic_change'] += avg_panic_rise
        if 'hoarding' in res_effects:
            summary['total_panic_change'] += res_effects['hoarding'].get('panic_spread', 0)
        if 'emotion_burst' in res_effects:
            summary['total_panic_change'] += res_effects['emotion_burst'].get('panic_spread', 0)

        # ============ 情绪变化汇总 ============
        # 降低情绪的因素
        if 'resource_resident' in gov_effects:
            summary['total_emotion_change'] -= gov_effects['resource_resident'].get('emotion_reduction', 0)
        if 'opinion_manage' in gov_effects:
            # 【公式关联】舆情管理通过官方信息→抑制谣言→间接降低情绪
            # 这里记录的是舆情管理的间接影响量（用于统计分析）
            opinion = gov_effects['opinion_manage']
            rumor_suppress = opinion.get('rumor_suppress_rate', 0)
            panic_reduction = opinion.get('panic_spread_reduction', 0)

            # 间接情绪影响 = 谣言抑制 × 谣言对情绪的影响系数
            indirect_emotion_effect = rumor_suppress * 0.3 + panic_reduction * 0.2
            summary['total_emotion_change'] -= indirect_emotion_effect
            summary['total_emotion_suppression'] += indirect_emotion_effect

            if opinion.get('official_info_boost', 0) > 0:
                summary['active_suppression_mechanisms'] += 1
        if 'restore' in grid_effects:
            summary['total_emotion_change'] -= grid_effects['restore'].get('emotion_drop', 0)
        if 'self_help' in res_effects:
            summary['total_emotion_change'] -= res_effects['self_help'].get('emotion_relief', 0)

        # 【新增】社区集体自救降低情绪
        if 'community_self_help' in res_effects:
            emotion_supp = res_effects['community_self_help'].get('total_emotion_suppression', 0)
            summary['total_emotion_change'] -= emotion_supp
            summary['total_emotion_suppression'] += emotion_supp
            if res_effects['community_self_help'].get('active_communities', 0) > 0:
                summary['active_suppression_mechanisms'] += 1

        # 【新增】物资发放点降低情绪
        if 'supply_point' in res_effects:
            emotion_relief = res_effects['supply_point'].get('emotion_relief', 0)
            summary['total_emotion_change'] -= emotion_relief
            summary['total_emotion_suppression'] += emotion_relief
            if res_effects['supply_point'].get('residents_served', 0) > 0:
                summary['active_suppression_mechanisms'] += 1

        # 增加情绪的因素
        # 【修复】不再累加所有区域的emotion_rise，而是取平均值
        # 因为每个区域都有blackout_效果，累加会导致情绪爆炸
        blackout_effects = [val for key, val in grid_effects.items() if key.startswith('blackout_')]
        if blackout_effects:
            avg_emotion_rise = sum(e.get('emotion_rise', 0) for e in blackout_effects) / len(blackout_effects)
            summary['total_emotion_change'] += avg_emotion_rise
        if 'gather_spread' in res_effects:
            summary['total_emotion_change'] += res_effects['gather_spread'].get('emotion_spread', 0)

        # ============ 舆情压力汇总 ============
        if 'crisis' in ent_effects:
            summary['total_opinion_pressure'] += ent_effects['crisis'].get('opinion_pressure', 0)
        if 'shutdown' in ent_effects:
            summary['total_opinion_pressure'] += ent_effects['shutdown'].get('opinion_pressure', 0)
        if 'resume' in ent_effects:
            summary['total_opinion_pressure'] -= ent_effects['resume'].get('opinion_relief', 0)
        if 'emotion_burst' in res_effects:
            summary['total_opinion_pressure'] += res_effects['emotion_burst'].get('opinion_pressure', 0)

        # ============ 政府压力汇总 ============
        if 'request' in ent_effects:
            summary['total_gov_pressure'] += ent_effects['request'].get('gov_pressure', 0)
        if 'crisis' in ent_effects:
            summary['total_gov_pressure'] += ent_effects['crisis'].get('gov_pressure', 0)
        if 'hoarding' in res_effects:
            summary['total_gov_pressure'] += res_effects['hoarding'].get('gov_pressure', 0)
        if 'power_request' in res_effects:
            summary['total_gov_pressure'] += res_effects['power_request'].get('gov_pressure', 0)

        # ============ 修复能力提升汇总 ============
        if 'resource_grid' in gov_effects:
            summary['total_repair_boost'] += gov_effects['resource_grid'].get('capacity_boost', 0)

        return summary

    def _update_pressure_indices(self, effects):
        """更新压力指数状态"""
        summary = effects.get('summary', {})

        # 政府压力指数（0-1）
        pressure_change = summary.get('total_gov_pressure', 0)
        self.gov_pressure = max(0, min(1, self.gov_pressure + pressure_change * 0.1))

        # 舆情压力指数（0-1）
        opinion_change = summary.get('total_opinion_pressure', 0)
        self.opinion_pressure = max(0, min(1, self.opinion_pressure + opinion_change * 0.1))

    def apply_effects(self, sim, effects, dt):
        """
        应用事件影响到仿真状态

        参数:
            sim: 仿真对象
            effects: 计算得到的效果字典
            dt: 时间步长
        """
        summary = effects.get('summary', {})
        gov_effects = effects.get('government', {})
        res_effects = effects.get('resident', {})

        # ============ 应用恐慌变化 ============
        panic_change = summary.get('total_panic_change', 0)
        if abs(panic_change) > 0.001:
            scale = 0.1  # 缩放因子，避免变化过大
            for r in sim.residents:
                new_panic = r.panic_value + panic_change * scale
                r.panic_value = max(0, min(1, new_panic))

        # ============ 应用情绪变化 ============
        emotion_change = summary.get('total_emotion_change', 0)
        if abs(emotion_change) > 0.001:
            scale = 0.1
            for r in sim.residents:
                new_emotion = r.emotion + emotion_change * scale
                r.emotion = max(0, min(1, new_emotion))

        # ============ 【公式关联】应用舆情管理的间接效果 ============
        # 舆情管理 → 官方信息传播 → 抑制谣言 → 减少恐慌增量 → 间接影响情绪
        if 'opinion_manage' in gov_effects:
            opinion_effect = gov_effects['opinion_manage']

            # 【公式关联1】增加官方信息传播
            official_boost = opinion_effect.get('official_info_boost', 0)
            if official_boost > 0:
                for r in sim.residents:
                    # 公式: info_official += boost × (1 - current_official)
                    # 官方信息越少的人，增量越大
                    current = r.info_received.get('official', 0)
                    increase = official_boost * (1 - current)
                    r.info_received['official'] = min(1.0, current + increase)

            # 【公式关联2】抑制谣言相信度
            rumor_suppress = opinion_effect.get('rumor_suppress_rate', 0)
            if rumor_suppress > 0:
                for r in sim.residents:
                    # 公式: rumor_belief -= k × official × rumor_belief
                    # 官方信息越多，谣言相信度越高的人，抑制效果越明显
                    official = r.info_received.get('official', 0)
                    suppression = rumor_suppress * official * r.rumor_belief
                    r.rumor_belief = max(0, r.rumor_belief - suppression)

            # 【公式关联3】SEIR感染率降低（通过信息澄清）
            seir_reduction = opinion_effect.get('seir_infection_reduction', 0)
            if seir_reduction > 0:
                for r in sim.residents:
                    if r.state == 'S':
                        # 高官方信息 + 低情绪的S状态居民，有概率变成R（理性抵制）
                        official = r.info_received.get('official', 0)
                        if official > 0.5 and r.emotion < 0.3:
                            if random.random() < seir_reduction * official:
                                r.state = 'R'

        # ============ 【新增】应用社区集体自救效果 ============
        if 'community_self_help' in res_effects:
            community_effect = res_effects['community_self_help']
            zone_effects = community_effect.get('zone_effects', {})

            for zone, effect in zone_effects.items():
                if not effect.get('active', False):
                    continue

                emotion_supp = effect.get('emotion_suppression', 0)
                panic_supp = effect.get('panic_suppression', 0)

                # 对该区域的居民应用抑制效果
                for r in sim.residents:
                    if getattr(r, 'zone', None) == zone:
                        if emotion_supp > 0:
                            r.emotion = max(0, r.emotion - emotion_supp)
                        if panic_supp > 0:
                            r.panic_value = max(0, r.panic_value - panic_supp)

        # ============ 【新增】应用物资发放点效果 ============
        if 'supply_point' in res_effects:
            supply_effect = res_effects['supply_point']

            emotion_relief = supply_effect.get('emotion_relief', 0)
            hoarding_reduction = supply_effect.get('hoarding_reduction', 0)
            panic_relief = supply_effect.get('panic_relief', 0)

            if emotion_relief > 0 or hoarding_reduction > 0 or panic_relief > 0:
                # 优先影响正在囤积的居民
                coverage = self.coefficients['supply_point_coverage']
                affected_count = 0
                max_affected = int(len(sim.residents) * coverage)

                # 首先处理囤积的居民
                hoarding_residents = [r for r in sim.residents
                                      if getattr(r, 'is_hoarding', False)]
                for r in hoarding_residents:
                    if affected_count >= max_affected:
                        break

                    # 降低情绪
                    r.emotion = max(0, r.emotion - emotion_relief * 1.5)
                    # 降低恐慌
                    r.panic_value = max(0, r.panic_value - panic_relief * 1.5)
                    # 有概率停止囤积
                    if random.random() < hoarding_reduction:
                        r.is_hoarding = False

                    affected_count += 1

                # 然后处理其他高情绪居民
                if affected_count < max_affected:
                    other_residents = [r for r in sim.residents
                                       if not getattr(r, 'is_hoarding', False) and r.emotion > 0.4]
                    for r in other_residents:
                        if affected_count >= max_affected:
                            break
                        r.emotion = max(0, r.emotion - emotion_relief)
                        r.panic_value = max(0, r.panic_value - panic_relief)
                        affected_count += 1

        # ============ 应用修复能力提升 ============
        repair_boost = summary.get('total_repair_boost', 0)
        if repair_boost > 0:
            sim.grid.current_resource_level = min(
                sim.grid.base_resource_capacity,
                sim.grid.current_resource_level + repair_boost
            )

        # ============ 应用SEIR传播加速 ============
        if 'gather_spread' in res_effects:
            seir_boost = res_effects['gather_spread'].get('seir_boost', 0)
            if seir_boost > 0:
                # 加速S→E转化
                for r in sim.residents:
                    if r.state == 'S' and r.neighbors:
                        i_neighbors = [n for n in r.neighbors if n.state == 'I']
                        if i_neighbors and random.random() < seir_boost:
                            r.state = 'E'

        # ============ 应用自救互助的E→R加速 ============
        if 'self_help' in res_effects:
            recovery_boost = res_effects['self_help'].get('recovery_boost', 0)
            if recovery_boost > 0:
                for r in sim.residents:
                    if r.state == 'E' and r.emotion < 0.3:
                        if random.random() < recovery_boost:
                            r.state = 'R'


def create_event_influence_calculator(config=None):
    """创建事件影响计算器实例"""
    return EventInfluenceCalculator(config)


# =============================================================================
# 事件关系网络描述（用于文档和分析）
# =============================================================================
EVENT_RELATIONSHIPS = {
    # 政府事件
    1: {
        'name': '发布应急预警',
        'subject': '政府',
        'triggers': ['停电比例 > 10%'],
        'effects': ['降低居民恐慌', '提高知情率', '安抚企业'],
        'affects': ['居民恐慌↓', '知情率↑', '企业绝望↓'],
    },
    2: {
        'name': '政府分配资源给电网',
        'subject': '政府',
        'triggers': ['停电发生', '有可用资源'],
        'effects': ['增加电网修复能力', '加快修复速度'],
        'affects': ['电网资源↑', '修复能力↑'],
    },
    3: {
        'name': '政府分配资源给企业',
        'subject': '政府',
        'triggers': ['企业求助强度 > 阈值'],
        'effects': ['缓解企业经营危机', '降低企业求助强度'],
        'affects': ['企业绝望↓', '舆情压力↓'],
    },
    4: {
        'name': '政府分配资源给居民',
        'subject': '政府',
        'triggers': ['居民情绪高', '有囤积行为'],
        'effects': ['降低居民情绪', '减少囤积行为'],
        'affects': ['居民情绪↓', '囤积↓', '恐慌↓'],
    },
    5: {
        'name': '实施舆情管理',
        'subject': '政府',
        'triggers': ['舆情压力 > 阈值'],
        'effects': ['降低恐慌传播速度', '抑制负面情绪扩散'],
        'affects': ['SEIR传播↓', '情绪传播↓'],
    },

    # 电网事件
    6: {
        'name': '区域断电',
        'subject': '电网',
        'triggers': ['外部停电指令', '故障传播'],
        'effects': ['触发居民情绪上升', '触发企业停工', '引发恐慌'],
        'affects': ['居民情绪↑', '企业停工', '恐慌↑', '关键设施求助↑'],
    },
    7: {
        'name': '增设临时供电站',
        'subject': '电网',
        'triggers': ['停电区域有一级负荷', '停电时间长'],
        'effects': ['保障关键设施供电', '降低关键设施求助'],
        'affects': ['一级负荷恢复', '恐慌↓'],
    },
    8: {
        'name': '电网实施抢修',
        'subject': '电网',
        'triggers': ['故障发现', '资源充足'],
        'effects': ['修复进度推进', '消耗电网资源'],
        'affects': ['修复进度↑', '电网资源↓'],
    },
    9: {
        'name': '区域恢复供电',
        'subject': '电网',
        'triggers': ['抢修完成'],
        'effects': ['企业恢复生产', '居民情绪下降', '恐慌缓解'],
        'affects': ['企业恢复', '情绪↓', '恐慌↓'],
    },

    # 企业事件
    10: {
        'name': '企业请求资源',
        'subject': '企业',
        'triggers': ['绝望程度 > 0.3', '停电中'],
        'effects': ['请求政府下放资源', '增加政府压力'],
        'affects': ['政府压力↑', '触发政府资源分配'],
    },
    11: {
        'name': '企业经营危机',
        'subject': '企业',
        'triggers': ['停电时长 > 阈值（小型4h/中型8h/大型12h）'],
        'effects': ['经营困难', '增加舆情压力'],
        'affects': ['舆情压力↑', '政府压力↑'],
    },
    12: {
        'name': '企业停工',
        'subject': '企业',
        'triggers': ['停电', '无备用电源'],
        'effects': ['经济损失累积', '增加舆情压力'],
        'affects': ['经济损失↑', '舆情↑'],
    },
    13: {
        'name': '恢复生产',
        'subject': '企业',
        'triggers': ['恢复供电'],
        'effects': ['减少经济损失', '降低舆情压力', '提振信心'],
        'affects': ['经济损失停止', '舆情↓', '信心↑'],
    },

    # 居民事件
    14: {
        'name': '居民囤积物资',
        'subject': '居民',
        'triggers': ['恐慌值 > 0.6'],
        'effects': ['造成物资紧缺', '加剧恐慌传播'],
        'affects': ['恐慌传播↑', '政府压力↑（需发放资源）'],
    },
    15: {
        'name': '居民聚集与信息传播',
        'subject': '居民',
        'triggers': ['I状态居民多'],
        'effects': ['加快信息传播', '加速SEIR转化'],
        'affects': ['S→E加速', '情绪传播↑'],
    },
    16: {
        'name': '恢复供电请求',
        'subject': '居民',
        'triggers': ['停电', '情绪 > 0.4'],
        'effects': ['增加政府/电网压力', '推动资源调配'],
        'affects': ['政府压力↑', '电网压力↑'],
    },
    17: {
        'name': '居民情绪爆发',
        'subject': '居民',
        'triggers': ['情绪 > 0.7'],
        'effects': ['大幅增加舆情压力', '触发政府紧急响应'],
        'affects': ['舆情压力↑↑', '恐慌传播↑'],
    },
    18: {
        'name': '居民自救与互助',
        'subject': '居民',
        'triggers': ['R状态居民多', '政府资源下发后'],
        'effects': ['缓解局部恐慌', '提高社区韧性'],
        'affects': ['恐慌↓', '情绪↓', 'E→R加速'],
    },
}


def get_event_relationship(event_id):
    """获取事件关系描述"""
    return EVENT_RELATIONSHIPS.get(event_id, None)


def print_event_network():
    """打印事件关系网络"""
    print("\n" + "=" * 70)
    print("事件关系网络")
    print("=" * 70)

    for event_id, info in EVENT_RELATIONSHIPS.items():
        print(f"\n【事件{event_id}】{info['name']} ({info['subject']})")
        print(f"  触发条件: {', '.join(info['triggers'])}")
        print(f"  作用: {', '.join(info['effects'])}")
        print(f"  影响: {', '.join(info['affects'])}")

    print("\n" + "=" * 70)

