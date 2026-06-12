# -*- coding: utf-8 -*-
"""
================================================================================
事件类型定义模块 - 停电应急仿真事件系统
================================================================================
功能：
    定义所有仿真中可能发生的事件类型，包括：
    - 政府事件（5种）
    - 电网事件（4种）
    - 企业事件（4种）
    - 居民事件（5种）

每个事件包含：
    - event_id: 事件唯一ID
    - event_name: 事件名称
    - subject: 主体类型（政府/电网/企业/居民）
================================================================================
"""

# =============================================================================
# 事件类型定义
# =============================================================================

# 政府事件 (1-5)
GOV_EMERGENCY_WARNING = 1  # 发布应急预警
GOV_RESOURCE_TO_GRID = 2  # 政府分配资源给电网
GOV_RESOURCE_TO_ENTERPRISE = 3  # 政府分配资源给企业
GOV_RESOURCE_TO_RESIDENT = 4  # 政府分配资源给居民
GOV_PUBLIC_OPINION = 5  # 实施舆情管理

# 电网事件 (6-9)
GRID_BLACKOUT = 6  # 区域断电
GRID_TEMP_STATION = 7  # 增设临时供电站
GRID_REPAIR = 8  # 电网实施抢修
GRID_RESTORE = 9  # 区域恢复供电

# 企业事件 (10-13)
ENT_REQUEST_RESOURCE = 10  # 企业请求资源
ENT_CRISIS = 11  # 企业经营危机
ENT_SHUTDOWN = 12  # 企业停工
ENT_RESUME = 13  # 恢复生产

# 居民事件 (14-18)
RES_HOARDING = 14  # 居民囤积物资
RES_GATHERING = 15  # 居民聚集与信息传播
RES_POWER_REQUEST = 16  # 恢复供电请求
RES_EMOTION_BURST = 17  # 居民情绪爆发
RES_SELF_HELP = 18  # 居民自救与互助

# 控制事件 (19-23) - 运行时参数变更
CTRL_GOV_PARAM_CHANGE = 19  # 政府参数变更
CTRL_GRID_PARAM_CHANGE = 20  # 电网参数变更
CTRL_RESIDENT_PARAM_CHANGE = 21  # 居民参数变更
CTRL_TRIGGER_OUTAGE = 22  # 触发停电指令
CTRL_FORCE_RESTORE = 23  # 强制恢复供电指令

# =============================================================================
# 事件类型元数据
# =============================================================================

EVENT_METADATA = {
    # 政府事件
    GOV_EMERGENCY_WARNING: {
        'name': '发布应急预警',
        'subject': '政府',
        'description': '政府发布停电应急预警通知'
    },
    GOV_RESOURCE_TO_GRID: {
        'name': '政府分配资源给电网',
        'subject': '政府',
        'description': '政府向电网公司调配资源支持修复'
    },
    GOV_RESOURCE_TO_ENTERPRISE: {
        'name': '政府分配资源给企业',
        'subject': '政府',
        'description': '政府向受影响企业提供补偿或支持'
    },
    GOV_RESOURCE_TO_RESIDENT: {
        'name': '政府分配资源给居民',
        'subject': '政府',
        'description': '政府向居民分发应急物资或提供安抚'
    },
    GOV_PUBLIC_OPINION: {
        'name': '实施舆情管理',
        'subject': '政府',
        'description': '政府发布官方信息管理舆情'
    },

    # 电网事件
    GRID_BLACKOUT: {
        'name': '区域断电',
        'subject': '电网',
        'description': '某区域发生停电故障'
    },
    GRID_TEMP_STATION: {
        'name': '增设临时供电站',
        'subject': '电网',
        'description': '电网公司设置临时供电设施'
    },
    GRID_REPAIR: {
        'name': '电网实施抢修',
        'subject': '电网',
        'description': '电网公司开始对故障区域进行抢修'
    },
    GRID_RESTORE: {
        'name': '区域恢复供电',
        'subject': '电网',
        'description': '故障区域修复完成，恢复供电'
    },

    # 企业事件
    ENT_REQUEST_RESOURCE: {
        'name': '企业请求资源',
        'subject': '企业',
        'description': '企业向政府或电网请求支援'
    },
    ENT_CRISIS: {
        'name': '企业经营危机',
        'subject': '企业',
        'description': '企业因停电面临经营困难'
    },
    ENT_SHUTDOWN: {
        'name': '企业停工',
        'subject': '企业',
        'description': '企业因停电被迫停止生产'
    },
    ENT_RESUME: {
        'name': '恢复生产',
        'subject': '企业',
        'description': '企业恢复正常生产经营'
    },

    # 居民事件
    RES_HOARDING: {
        'name': '居民囤积物资',
        'subject': '居民',
        'description': '居民因恐慌开始囤积生活物资'
    },
    RES_GATHERING: {
        'name': '居民聚集与信息传播',
        'subject': '居民',
        'description': '居民聚集交流，传播信息（SEIR传播）'
    },
    RES_POWER_REQUEST: {
        'name': '恢复供电请求',
        'subject': '居民',
        'description': '居民向相关部门请求尽快恢复供电'
    },
    RES_EMOTION_BURST: {
        'name': '居民情绪爆发',
        'subject': '居民',
        'description': '居民情绪达到高峰，产生强烈反应'
    },
    RES_SELF_HELP: {
        'name': '居民自救与互助',
        'subject': '居民',
        'description': '居民开展自救行动或邻里互助'
    },

    # 控制事件
    CTRL_GOV_PARAM_CHANGE: {
        'name': '政府参数变更',
        'subject': '控制',
        'description': '运行时调整政府行为参数'
    },
    CTRL_GRID_PARAM_CHANGE: {
        'name': '电网参数变更',
        'subject': '控制',
        'description': '运行时调整电网行为参数'
    },
    CTRL_RESIDENT_PARAM_CHANGE: {
        'name': '居民参数变更',
        'subject': '控制',
        'description': '运行时调整居民行为参数'
    },
    CTRL_TRIGGER_OUTAGE: {
        'name': '触发停电指令',
        'subject': '控制',
        'description': '外部指令触发停电'
    },
    CTRL_FORCE_RESTORE: {
        'name': '强制恢复供电',
        'subject': '控制',
        'description': '外部指令强制恢复供电'
    },
}


def get_event_name(event_id):
    """获取事件名称"""
    meta = EVENT_METADATA.get(event_id)
    return meta['name'] if meta else f'未知事件({event_id})'


def get_event_subject(event_id):
    """获取事件主体"""
    meta = EVENT_METADATA.get(event_id)
    return meta['subject'] if meta else '未知'


def get_all_event_ids():
    """获取所有事件ID列表"""
    return list(EVENT_METADATA.keys())


def get_events_by_subject(subject):
    """按主体类型获取事件ID列表"""
    return [eid for eid, meta in EVENT_METADATA.items() if meta['subject'] == subject]

