# -*- coding: utf-8 -*-
"""
core模块 - 停电恐慌行为仿真核心引擎

包含：
    - 多主体Agent（政府/电网/企业/居民/关键基础设施）
    - 社会力模型（驱动力/社会心理力/身体接触力）
    - 恐慌传播模型（静态场/危险场/PTS传染）
    - 统一心理压力模型（Lazarus应激-评估-应对理论）
    - 行为切换模型（I1目标方向/I2商店选择/I3领导者跟随）
    - 事件系统（18种事件+5种控制事件）
    - 区域管理（GeoJSON边界/点位生成/邻接关系）
"""

# =============================================================================
# Agent模块
# =============================================================================
from .agents import (
    ResidentAttributeConfig,
    GovernmentAgent,
    PowerGridAgent,
    EnterpriseAgent,
    ResidentAgent,
    CriticalInfraAgent,
)

# =============================================================================
# 社会力与恐慌模型
# =============================================================================
from .social_force import (
    SocialForceModel,
    PanicModel,
    IntegratedForceCalculator,
)

# =============================================================================
# 统一心理压力模型
# =============================================================================
from .unified_stress_model import (
    UnifiedStressModel,
    migrate_to_unified_model,
)

# =============================================================================
# 行为切换模型（论文创新点 I1/I2/I3）
# =============================================================================
from .behavior_switching import (
    SwitchParams,
    compute_goal_direction,
    update_perceived_occupancy,
    attempt_acquire,
    init_store_state,
    choose_store,
    store_utility,
    leader_score,
    update_leader,
)

# =============================================================================
# 事件系统
# =============================================================================
from .event_types import (
    # 政府事件
    GOV_EMERGENCY_WARNING,
    GOV_RESOURCE_TO_GRID,
    GOV_RESOURCE_TO_ENTERPRISE,
    GOV_RESOURCE_TO_RESIDENT,
    GOV_PUBLIC_OPINION,
    # 电网事件
    GRID_BLACKOUT,
    GRID_TEMP_STATION,
    GRID_REPAIR,
    GRID_RESTORE,
    # 企业事件
    ENT_REQUEST_RESOURCE,
    ENT_CRISIS,
    ENT_SHUTDOWN,
    ENT_RESUME,
    # 居民事件
    RES_HOARDING,
    RES_GATHERING,
    RES_POWER_REQUEST,
    RES_EMOTION_BURST,
    RES_SELF_HELP,
    # 控制事件
    CTRL_GOV_PARAM_CHANGE,
    CTRL_GRID_PARAM_CHANGE,
    CTRL_RESIDENT_PARAM_CHANGE,
    CTRL_TRIGGER_OUTAGE,
    CTRL_FORCE_RESTORE,
    # 元数据与工具函数
    EVENT_METADATA,
    get_event_name,
    get_event_subject,
    get_all_event_ids,
    get_events_by_subject,
)

from .event_recorder import (
    Event,
    EventRecorder,
    EventDetector,
)

from .event_influence import (
    EventInfluenceCalculator,
    create_event_influence_calculator,
    get_event_relationship,
    print_event_network,
)

# =============================================================================
# 区域管理
# =============================================================================
from .region_manager import (
    GeoJSONRegionManager,
    NodeAttributeConfig,
    CSVPointLoader,
    ResidentDistributor,
)

# =============================================================================
# 公开API列表
# =============================================================================
__all__ = [
    # Agent
    'ResidentAttributeConfig',
    'GovernmentAgent',
    'PowerGridAgent',
    'EnterpriseAgent',
    'ResidentAgent',
    'CriticalInfraAgent',
    # 社会力与恐慌
    'SocialForceModel',
    'PanicModel',
    'IntegratedForceCalculator',
    # 心理压力
    'UnifiedStressModel',
    'migrate_to_unified_model',
    # 行为切换
    'SwitchParams',
    'compute_goal_direction',
    'update_perceived_occupancy',
    'attempt_acquire',
    'init_store_state',
    'choose_store',
    'store_utility',
    'leader_score',
    'update_leader',
    # 事件类型常量
    'GOV_EMERGENCY_WARNING',
    'GOV_RESOURCE_TO_GRID',
    'GOV_RESOURCE_TO_ENTERPRISE',
    'GOV_RESOURCE_TO_RESIDENT',
    'GOV_PUBLIC_OPINION',
    'GRID_BLACKOUT',
    'GRID_TEMP_STATION',
    'GRID_REPAIR',
    'GRID_RESTORE',
    'ENT_REQUEST_RESOURCE',
    'ENT_CRISIS',
    'ENT_SHUTDOWN',
    'ENT_RESUME',
    'RES_HOARDING',
    'RES_GATHERING',
    'RES_POWER_REQUEST',
    'RES_EMOTION_BURST',
    'RES_SELF_HELP',
    'CTRL_GOV_PARAM_CHANGE',
    'CTRL_GRID_PARAM_CHANGE',
    'CTRL_RESIDENT_PARAM_CHANGE',
    'CTRL_TRIGGER_OUTAGE',
    'CTRL_FORCE_RESTORE',
    # 事件元数据与工具
    'EVENT_METADATA',
    'get_event_name',
    'get_event_subject',
    'get_all_event_ids',
    'get_events_by_subject',
    # 事件记录
    'Event',
    'EventRecorder',
    'EventDetector',
    # 事件影响
    'EventInfluenceCalculator',
    'create_event_influence_calculator',
    'get_event_relationship',
    'print_event_network',
    # 区域管理
    'GeoJSONRegionManager',
    'NodeAttributeConfig',
    'CSVPointLoader',
    'ResidentDistributor',
]
