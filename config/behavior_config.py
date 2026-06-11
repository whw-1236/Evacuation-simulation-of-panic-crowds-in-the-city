# -*- coding: utf-8 -*-
"""
================================================================================
主体行为参数配置 - 外部可设置的行为参数
================================================================================

【核心概念】
行为参数（外部可设置）→ 状态演化（内部计算）→ 事件触发（输出结果）

行为参数是用户可以调节的"旋钮"，通过调整这些参数，
可以模拟不同场景下各主体的行为模式，观察事件的触发情况。

================================================================================
"""


class GovernmentBehaviorConfig:
    """
    政府行为参数配置

    【行为参数说明】
    这些参数控制政府的决策行为，外部可调

    【参数→状态→事件的关系】
    - initiative(积极性) → 资源下发量 → 触发"分配资源"事件
    - response(响应效率) → 响应速度 → 影响预警/舆情管理时机
    - warning_threshold → 预警触发阈值 → 触发"发布应急预警"事件
    - resource_allocation_strategy → 资源分配比例 → 影响各类分配事件
    """

    # ==================== 核心行为参数（外部可调）====================

    # 积极性：影响政府主动干预的意愿
    # 0.0=消极被动，0.5=正常，1.0=非常积极
    INITIATIVE = 0.5

    # 响应效率：影响政府响应速度和决策效率
    # 0.1=低效，1.0=正常，2.0=高效
    RESPONSE = 1.0

    # 资源储备：政府可用资源总量
    RESOURCE_CAPACITY = 100.0

    # ==================== 事件触发阈值（外部可调）====================

    # 发布应急预警的停电比例阈值
    WARNING_OUTAGE_THRESHOLD = 0.1  # 停电比例>10%触发预警

    # 启动舆情管理的舆情压力阈值
    OPINION_MANAGE_THRESHOLD = 0.4  # 舆情压力>0.4启动管理

    # 向电网分配资源的停电比例阈值
    RESOURCE_TO_GRID_THRESHOLD = 0.05  # 停电比例>5%开始支援电网

    # 向企业分配资源的企业求助强度阈值
    RESOURCE_TO_ENTERPRISE_THRESHOLD = 0.3  # 企业平均求助>0.3开始补偿

    # 向居民分配资源的居民情绪阈值
    RESOURCE_TO_RESIDENT_THRESHOLD = 0.5  # 居民平均情绪>0.5开始安抚

    # ==================== 资源分配策略（外部可调）====================

    # 资源分配比例（总和=1.0）
    ALLOCATION_RATIO_GRID = 0.5  # 分配给电网的比例
    ALLOCATION_RATIO_ENTERPRISE = 0.3  # 分配给企业的比例
    ALLOCATION_RATIO_RESIDENT = 0.2  # 分配给居民的比例

    # 紧急情况下的资源倍增系数
    EMERGENCY_RESOURCE_MULTIPLIER = 1.5

    @classmethod
    def get_behavior_description(cls):
        """获取行为参数描述"""
        return {
            'initiative': {
                'name': '积极性',
                'range': [0.0, 1.0],
                'default': cls.INITIATIVE,
                'effect': '影响政府主动干预的意愿和资源下发量',
            },
            'response': {
                'name': '响应效率',
                'range': [0.1, 2.0],
                'default': cls.RESPONSE,
                'effect': '影响政府响应速度和决策效率',
            },
            'warning_threshold': {
                'name': '预警阈值',
                'range': [0.0, 0.5],
                'default': cls.WARNING_OUTAGE_THRESHOLD,
                'effect': '触发发布应急预警的停电比例阈值',
            },
            'allocation_ratio': {
                'name': '资源分配比例',
                'default': {
                    'grid': cls.ALLOCATION_RATIO_GRID,
                    'enterprise': cls.ALLOCATION_RATIO_ENTERPRISE,
                    'resident': cls.ALLOCATION_RATIO_RESIDENT,
                },
                'effect': '控制资源在电网/企业/居民之间的分配',
            },
        }


class GridBehaviorConfig:
    """
    电网行为参数配置

    【行为参数说明】
    这些参数控制电网的修复行为，外部可调

    【参数→状态→事件的关系】
    - initiative(积极性) → 并行修复数 → 影响"抢修"事件
    - response(响应效率) → 修复速度 → 影响"恢复供电"事件时机
    - fault_propagation_rate → 故障扩散 → 影响"断电"事件扩散
    - temp_station_threshold → 临时供电站阈值 → 触发"增设临时供电站"事件
    """

    # ==================== 核心行为参数（外部可调）====================

    # 积极性：影响电网主动修复的意愿
    INITIATIVE = 0.5

    # 响应效率：影响修复速度
    RESPONSE = 1.0

    # 资源储备
    RESOURCE_CAPACITY = 50.0

    # 故障传播率：影响故障向邻近区域扩散的概率
    # 0.0=不扩散，0.1=低概率，0.5=高概率
    FAULT_PROPAGATION_RATE = 0.1

    # ==================== 事件触发阈值（外部可调）====================

    # 开始抢修的故障发现延迟（小时）
    REPAIR_START_DELAY = 0.5

    # 增设临时供电站的条件
    TEMP_STATION_OUTAGE_THRESHOLD = 0.3  # 停电比例>30%
    TEMP_STATION_DURATION_THRESHOLD = 4.0  # 且停电时长>4小时

    # ==================== 修复能力参数（外部可调）====================

    # 基础修复能力
    BASE_REPAIR_CAPACITY = 10.0

    # 最大并行修复数（基础值，会根据积极性增加）
    MAX_CONCURRENT_REPAIRS_BASE = 2
    MAX_CONCURRENT_REPAIRS_MAX = 8

    @classmethod
    def get_behavior_description(cls):
        """获取行为参数描述"""
        return {
            'initiative': {
                'name': '积极性',
                'range': [0.0, 1.0],
                'default': cls.INITIATIVE,
                'effect': '影响并行修复数量和修复优先级',
            },
            'response': {
                'name': '响应效率',
                'range': [0.1, 2.0],
                'default': cls.RESPONSE,
                'effect': '影响每步修复进度',
            },
            'fault_propagation_rate': {
                'name': '故障传播率',
                'range': [0.0, 0.5],
                'default': cls.FAULT_PROPAGATION_RATE,
                'effect': '故障向邻近区域扩散的概率',
            },
        }


class EnterpriseBehaviorConfig:
    """
    企业行为参数配置

    【行为参数说明】
    这些参数控制企业的应对行为，外部可调

    【参数→状态→事件的关系】
    - initiative(积极性) → 求助强度 → 触发"企业请求资源"事件
    - crisis_threshold → 危机判定 → 触发"企业经营危机"事件
    - shutdown_threshold → 停工判定 → 触发"企业停工"事件
    """

    # ==================== 核心行为参数（外部可调）====================

    # 积极性：影响企业求助的积极程度
    INITIATIVE = 0.5

    # 响应效率：影响企业应对停电的效率
    RESPONSE = 1.0

    # ==================== 事件触发阈值（外部可调）====================

    # 触发"企业请求资源"的绝望程度阈值
    REQUEST_DESPERATION_THRESHOLD = 0.3

    # 触发"企业经营危机"的停电时长阈值（小时）
    CRISIS_DURATION_SMALL = 4  # 小型企业
    CRISIS_DURATION_MEDIUM = 8  # 中型企业
    CRISIS_DURATION_LARGE = 12  # 大型企业

    # 触发"企业停工"的条件（停电且无备用电源即停工）

    # ==================== 损失参数（外部可调）====================

    # 停电损失率（每小时）
    LOSS_RATE_SMALL = 0.15  # 小型企业
    LOSS_RATE_MEDIUM = 0.10  # 中型企业
    LOSS_RATE_LARGE = 0.08  # 大型企业

    # 备用电源持续时间（小时）
    BACKUP_POWER_DURATION = 0  # 默认无备用电源

    @classmethod
    def get_behavior_description(cls):
        """获取行为参数描述"""
        return {
            'initiative': {
                'name': '积极性',
                'range': [0.0, 1.0],
                'default': cls.INITIATIVE,
                'effect': '影响企业求助的积极程度',
            },
            'crisis_threshold': {
                'name': '危机阈值',
                'default': {
                    'small': cls.CRISIS_DURATION_SMALL,
                    'medium': cls.CRISIS_DURATION_MEDIUM,
                    'large': cls.CRISIS_DURATION_LARGE,
                },
                'effect': '触发经营危机的停电时长',
            },
            'loss_rate': {
                'name': '损失率',
                'default': {
                    'small': cls.LOSS_RATE_SMALL,
                    'medium': cls.LOSS_RATE_MEDIUM,
                    'large': cls.LOSS_RATE_LARGE,
                },
                'effect': '停电期间每小时的损失比例',
            },
        }


class ResidentBehaviorConfig:
    """
    居民行为参数配置

    【行为参数说明】
    这些参数控制居民的情绪和行为反应，外部可调

    【参数→状态→事件的关系】
    - emotion_sensitivity → 情绪上升速度 → 影响"情绪爆发"事件
    - panic_sensitivity → 恐慌上升速度 → 影响"囤积物资"事件
    - seir_transmission_rate → SEIR传播 → 影响"聚集传播"事件
    - self_help_tendency → 自救倾向 → 影响"自救互助"事件
    """

    # ==================== 核心行为参数（外部可调）====================

    # 情绪敏感度：影响情绪上升速度
    # α系数，越高情绪上升越快
    EMOTION_SENSITIVITY = 0.1

    # 情绪传播系数：影响情绪在人群中传播的速度
    # β系数
    EMOTION_SPREAD_RATE = 0.15

    # 恐慌敏感度：影响恐慌上升速度
    PANIC_SENSITIVITY = 0.08

    # 恐慌传播半径（经纬度）
    PANIC_SPREAD_RADIUS = 0.002

    # ==================== 事件触发阈值（外部可调）====================

    # 触发"居民囤积物资"的恐慌阈值
    HOARDING_PANIC_THRESHOLD = 0.6

    # 触发"恢复供电请求"的情绪阈值
    POWER_REQUEST_EMOTION_THRESHOLD = 0.4

    # 触发"居民情绪爆发"的情绪阈值
    EMOTION_BURST_THRESHOLD = 0.7

    # 触发"居民自救互助"的条件（R状态或低情绪状态）
    SELF_HELP_EMOTION_THRESHOLD = 0.3

    # ==================== SEIR传播参数（外部可调）====================

    # S→E 感染概率（接触I状态邻居时）
    SEIR_INFECTION_RATE = 0.15

    # E→I 潜伏期时长（步数）
    SEIR_INCUBATION_PERIOD = 4

    # I→R 恢复条件（步数+情绪阈值）
    SEIR_RECOVERY_PERIOD = 24
    SEIR_RECOVERY_EMOTION_THRESHOLD = 0.2

    # R→E 复发概率（停电+高情绪时）
    SEIR_RELAPSE_RATE = 0.06

    # ==================== 移动参数（外部可调）====================

    # 最大移动速度（经纬度/步）
    MAX_SPEED = 0.0003

    # 期望移动速度
    DESIRED_SPEED = 0.0001

    @classmethod
    def get_behavior_description(cls):
        """获取行为参数描述"""
        return {
            'emotion_sensitivity': {
                'name': '情绪敏感度',
                'range': [0.01, 0.3],
                'default': cls.EMOTION_SENSITIVITY,
                'effect': '影响停电时情绪上升速度',
            },
            'panic_sensitivity': {
                'name': '恐慌敏感度',
                'range': [0.01, 0.2],
                'default': cls.PANIC_SENSITIVITY,
                'effect': '影响恐慌值上升速度',
            },
            'hoarding_threshold': {
                'name': '囤积阈值',
                'range': [0.3, 0.9],
                'default': cls.HOARDING_PANIC_THRESHOLD,
                'effect': '触发囤积行为的恐慌阈值',
            },
            'emotion_burst_threshold': {
                'name': '情绪爆发阈值',
                'range': [0.5, 0.9],
                'default': cls.EMOTION_BURST_THRESHOLD,
                'effect': '触发情绪爆发的阈值',
            },
            'seir_infection_rate': {
                'name': 'SEIR感染率',
                'range': [0.05, 0.3],
                'default': cls.SEIR_INFECTION_RATE,
                'effect': 'S状态接触I状态后被感染的概率',
            },
        }


# =============================================================================
# 行为参数→状态演化→事件触发 的完整映射
# =============================================================================

BEHAVIOR_EVENT_MAPPING = {
    '政府': {
        '行为参数': {
            'initiative': '积极性(0-1)',
            'response': '响应效率(0.1-2.0)',
            'warning_threshold': '预警阈值',
            'allocation_ratio': '资源分配比例',
        },
        '状态变量': {
            'pressure': '政府压力指数',
            'resource_level': '当前资源量',
            'response_state': '响应状态(正常/预警/紧急)',
        },
        '触发事件': {
            1: '发布应急预警 ← 停电比例 > warning_threshold',
            2: '分配资源给电网 ← 停电发生 且 有资源',
            3: '分配资源给企业 ← 企业求助强度 > threshold',
            4: '分配资源给居民 ← 居民情绪 > threshold',
            5: '实施舆情管理 ← 舆情压力 > threshold',
        },
    },
    '电网': {
        '行为参数': {
            'initiative': '积极性(0-1)',
            'response': '响应效率(0.1-2.0)',
            'fault_propagation_rate': '故障传播率(0-0.5)',
            'repair_capacity': '修复能力',
        },
        '状态变量': {
            'resource_level': '当前资源量',
            'ongoing_repairs': '正在修复的区域',
            'repair_progress': '修复进度',
        },
        '触发事件': {
            6: '区域断电 ← 外部指令 或 故障传播',
            7: '增设临时供电站 ← 停电比例>30% 且 时长>4h',
            8: '电网实施抢修 ← 故障发现 且 资源充足',
            9: '区域恢复供电 ← 修复进度 >= 100%',
        },
    },
    '企业': {
        '行为参数': {
            'initiative': '积极性(0-1)',
            'response': '响应效率(0.1-2.0)',
            'crisis_threshold': '危机阈值(小/中/大)',
            'loss_rate': '损失率',
        },
        '状态变量': {
            'powered': '供电状态',
            'outage_duration': '停电时长',
            'desperation_level': '绝望程度',
            'loss': '累计损失',
        },
        '触发事件': {
            10: '企业请求资源 ← 绝望程度 > 0.3 且 停电中',
            11: '企业经营危机 ← 停电时长 > crisis_threshold',
            12: '企业停工 ← 停电 且 无备用电源',
            13: '恢复生产 ← 恢复供电',
        },
    },
    '居民': {
        '行为参数': {
            'emotion_sensitivity': '情绪敏感度(0.01-0.3)',
            'panic_sensitivity': '恐慌敏感度(0.01-0.2)',
            'seir_infection_rate': 'SEIR感染率(0.05-0.3)',
            'hoarding_threshold': '囤积阈值(0.3-0.9)',
            'emotion_burst_threshold': '情绪爆发阈值(0.5-0.9)',
        },
        '状态变量': {
            'emotion': '情绪值(0-1)',
            'panic_value': '恐慌值(0-1)',
            'state': 'SEIR状态(S/E/I/R)',
            'informed': '是否知情',
        },
        '触发事件': {
            14: '居民囤积物资 ← 恐慌值 > hoarding_threshold',
            15: '居民聚集与信息传播 ← I状态居民多',
            16: '恢复供电请求 ← 停电 且 情绪 > 0.4',
            17: '居民情绪爆发 ← 情绪 > emotion_burst_threshold',
            18: '居民自救与互助 ← R状态 或 低情绪状态',
        },
    },
}


def print_behavior_event_mapping():
    """打印行为参数→事件映射关系"""
    print("\n" + "=" * 70)
    print("行为参数 → 状态演化 → 事件触发 映射关系")
    print("=" * 70)

    for subject, info in BEHAVIOR_EVENT_MAPPING.items():
        print(f"\n【{subject}】")

        print("  行为参数（外部可调）:")
        for key, desc in info['行为参数'].items():
            print(f"    - {key}: {desc}")

        print("  状态变量（内部演化）:")
        for key, desc in info['状态变量'].items():
            print(f"    - {key}: {desc}")

        print("  触发事件（输出结果）:")
        for event_id, condition in info['触发事件'].items():
            print(f"    - 事件{event_id}: {condition}")

    print("\n" + "=" * 70)


def get_all_behavior_parameters():
    """获取所有可调行为参数"""
    return {
        'government': GovernmentBehaviorConfig.get_behavior_description(),
        'grid': GridBehaviorConfig.get_behavior_description(),
        'enterprise': EnterpriseBehaviorConfig.get_behavior_description(),
        'resident': ResidentBehaviorConfig.get_behavior_description(),
    }
