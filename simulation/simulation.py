# -*- coding: utf-8 -*-
"""
================================================================================
仿真主类模块 - 停电应急仿真核心
================================================================================
功能：
    1. 整合所有Agent和模型
    2. 管理仿真时间步
    3. 记录历史数据用于可视化
    4. 提供数据接口

【重要】历史数据说明（用于画图）：
    详见 data_interface.py 中的完整说明
================================================================================
"""

import numpy as np
import random
import sys
import os

# 项目根目录 = 论文仿真系统/
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.agents import (GovernmentAgent, PowerGridAgent, EnterpriseAgent,
                         ResidentAgent, CriticalInfraAgent)
from core.region_manager import (GeoJSONRegionManager, ResidentDistributor,
                                 CSVPointLoader, NODE_ATTR_CONFIG)
from core.social_force import IntegratedForceCalculator
from core.event_recorder import EventRecorder, EventDetector
from core.event_influence import EventInfluenceCalculator


class BlackoutSimulation:
    """
    停电应急仿真主类

    整合GeoJSON区域、多主体Agent、社会力模型、恐慌传播

    【停电模式】
    - 外部指定停电区域（通过 trigger_outage 方法）
    - 两种停电形式：
      1. 全部停电（行政区内所有区域）
      2. 部分停电（多端供电，按负荷等级切负荷）
    - 停电时间由电网维修资源决定
    """

    def __init__(self, config=None, outage_config=None, city_config=None):
        """
        初始化仿真

        参数:
            config: Config配置对象，如果为None则使用默认配置
            outage_config: 停电配置字典，可选，格式：
                {
                    'zones': [zone_id1, zone_id2, ...],  # 指定停电区域
                    'mode': 'full' | 'partial',          # 停电模式
                    'cause': 'equipment_failure' | 'overload' | ...,  # 停电原因
                    'severity_ratio': 0.5,               # 部分停电时的负荷缺口比例
                }
            city_config: 城市配置字典（0128新增，用于多城市支持）
                {
                    'city': '厦门市',
                    'geojson_paths': [...],
                    'districts': ['思明区', '湖里区', ...],
                }
        """
        # 加载配置
        if config is None:
            try:
                from config.config import Config
            except ImportError:
                from ..config.config import Config
            config = Config()
        self.config = config

        # 保存城市配置
        self.city_config = city_config

        # ==================== 基础参数 ====================
        self.T = config.simulation.TOTAL_STEPS
        self.dt = config.simulation.DT
        self.step_count = 0

        self.N_residents = config.simulation.N_RESIDENTS
        self.N_enterprises = config.simulation.N_ENTERPRISES
        self.seir_ratios = config.simulation.SEIR_RATIOS.copy()

        # ==================== 停电配置 ====================
        self.outage_config = outage_config  # 外部传入的停电配置
        self.use_external_outage = outage_config is not None  # 是否使用外部停电配置

        # ==================== 初始化区域管理器（加载社区GeoJSON） ====================
        print("[*] 初始化区域管理器...")

        # 【0128新增】优先使用city_config的GeoJSON路径
        if city_config and city_config.get('geojson_paths'):
            community_paths = city_config['geojson_paths']
            self.district_name = city_config.get('city', '默认城市')
            self.city_districts = city_config.get('districts', [])
            print(f"   使用城市配置: {self.district_name} ({len(community_paths)}个区县)")
        else:
            # 回退到旧配置
            community_paths = getattr(config.paths, 'COMMUNITY_PATHS', None) or config.paths.SUB_AREA_PATHS
            self.district_name = getattr(config.paths, 'DISTRICT_NAME', '默认行政区')
            self.city_districts = []

        self.region_manager = GeoJSONRegionManager(
            community_paths=community_paths,
            contour_paths=config.paths.CONTOUR_PATHS if config.paths.CONTOUR_PATHS else None,
            sub_area_paths=community_paths
        )

        # 【0128新增】建立区县到区域的映射
        self._build_district_zone_mapping()

        # ==================== 初始化力计算器 ====================
        self.force_calculator = IntegratedForceCalculator(
            social_force_config=config.social_force,
            panic_config=config.panic
        )

        # ==================== 初始化Agent ====================
        print("[Agent] 初始化多主体Agent...")
        self._init_agents()

        # ==================== 初始化负荷等级系统 ====================
        self._init_load_priority_system()

        # ==================== 初始化区域状态 ====================
        self._init_zone_status()

        # ==================== 初始化历史记录 ====================
        self._init_history()

        # ==================== 初始化事件记录系统 ====================
        self._init_event_system()

        # ==================== 【新增】初始化时间系统（昼夜差异）====================
        self._init_time_system()

        print(f"[OK] 仿真初始化完成: {len(self.residents)}居民, "
              f"{len(self.enterprises)}企业, {len(self.region_manager.regions)}区域")

    def _init_agents(self):
        """初始化所有Agent"""
        config = self.config

        # 政府Agent —— 每个区县独立一个政府
        self.gov_agents = {}
        behavior_cfg = getattr(config, 'gov_behavior', None)
        for district in self.district_to_zones:
            self.gov_agents[district] = GovernmentAgent(
                initiative=config.agent.GOV_INITIATIVE,
                response=config.agent.GOV_RESPONSE,
                behavior_config=behavior_cfg
            )
        # 向后兼容：self.gov 指向第一个区的政府
        self._gov_districts = list(self.gov_agents.keys())
        self.gov = self.gov_agents[self._gov_districts[0]] if self._gov_districts else GovernmentAgent()
        print(f"[Agent] 创建 {len(self.gov_agents)} 个区政府Agent: {', '.join(self._gov_districts)}")

        # 电网Agent
        self.grid = PowerGridAgent(
            initiative=config.agent.GRID_INITIATIVE,
            response=config.agent.GRID_RESPONSE,
            lambda_prop=config.agent.GRID_LAMBDA_PROP
        )

        # 企业Agent
        self.enterprises = []
        for _ in range(self.N_enterprises):
            e = EnterpriseAgent(
                initiative=config.agent.ENTERPRISE_INITIATIVE,
                response=config.agent.ENTERPRISE_RESPONSE
            )
            self.enterprises.append(e)

        # 居民Agent（按SEIR比例创建）
        self.residents = []
        seir_types = ['S', 'E', 'I', 'R']
        for stype in seir_types:
            count = int(self.N_residents * self.seir_ratios[stype])
            for _ in range(count):
                r = ResidentAgent(
                    alpha=config.agent.RESIDENT_ALPHA,
                    beta=config.agent.RESIDENT_BETA,
                    delta=config.agent.RESIDENT_DELTA,
                    seir_type=stype
                )
                self.residents.append(r)

        # 补齐总数
        while len(self.residents) < self.N_residents:
            self.residents.append(ResidentAgent(seir_type='S'))

        # 关键基础设施Agent
        n_hospitals = config.simulation.N_HOSPITALS
        n_pumps = config.simulation.N_PUMPS
        self.criticals = [CriticalInfraAgent() for _ in range(n_hospitals + n_pumps)]

        # ============================================================
        # 【POI绑定改造】调整初始化顺序:
        #   原: 先撒居民(按区域面积) → 再加载CSV
        #   新: 先加载CSV+分配zone → 再以POI为锚撒居民(0.002°圆内)
        # 移动机制(_update_position 的 max_range=0.002 圆形约束)无需改动,
        # 因为 set_position 会把 home_position 设到 POI 圆内的随机点上。
        # ============================================================

        # 1) 先加载CSV主体（政府、医院、工业、应急、学校、社区卫生院）
        print("[*] 加载CSV主体点位...")
        self.csv_loader = CSVPointLoader(
            region_manager=self.region_manager,
            csv_paths=self.config.paths.CSV_PATHS,
            attr_config=NODE_ATTR_CONFIG
        )
        self.csv_loader.load_all()

        # 保存CSV节点引用，供可视化使用
        self.csv_nodes = self.csv_loader.csv_nodes

        # 为CSV节点分配区域 (POI绑定时居民会从此继承zone)
        self._assign_csv_zones()

        # 2) 分配Agent到区域 - 居民走POI绑定, 企业仍走原方法
        distributor = ResidentDistributor(self.region_manager)
        bound_by_poi = distributor.distribute_residents_by_poi(
            self.residents, self.csv_nodes,
            poi_radius=0.002,  # ~222m, 与 agent._update_position 的 max_range 一致
        )
        if not bound_by_poi:
            # 回退到原方法 (CSV为空时)
            print("[警告] POI绑定失败, 回退到按区域面积分配")
            distributor.distribute_residents(self.residents)
        distributor.distribute_enterprises(self.enterprises)

        # 建立社交网络
        self._build_social_network()

        # 【改进3】预计算每个居民的邻居距离权重
        # 基于固定的社交圈(self.neighbors)和居民经纬度位置(self.x, self.y)
        # σ 参数从 ResidentAttributeConfig.DISTANCE_KERNEL_SIGMA 读取
        # 对比实验切换σ时,修改该常量后重新初始化 simulation 即可
        for r in self.residents:
            r.precompute_neighbor_weights()

    def _init_load_priority_system(self):
        """
        初始化负荷等级系统

        为每个区域分配负荷等级，基于区域内设施类型
        """
        load_config = self.config.load_priority

        # 区域负荷等级 {zone_id: load_level}
        self.zone_load_levels = {}

        # 区域内各等级负荷数量统计
        self.zone_load_stats = {}

        for zone_id in self.region_manager.regions.keys():
            # 统计区域内各类设施
            zone_facilities = [n for n in self.csv_nodes if n.get('zone') == zone_id]
            zone_residents = [r for r in self.residents if r.zone == zone_id]
            zone_enterprises = [e for e in self.enterprises if e.zone == zone_id]

            # 计算区域负荷等级统计
            level_counts = {1: 0, 2: 0, 3: 0}

            # 设施等级
            for node in zone_facilities:
                category = node.get('category', 'industry')
                level = load_config.FACILITY_LOAD_LEVELS.get(category, 3)
                level_counts[level] += 1

            # 企业默认为三级负荷
            level_counts[3] += len(zone_enterprises)

            # 居民默认为三级负荷
            level_counts[3] += len(zone_residents)

            self.zone_load_stats[zone_id] = level_counts

            # 区域整体等级取决于最高等级设施
            if level_counts[1] > 0:
                self.zone_load_levels[zone_id] = 1
            elif level_counts[2] > 0:
                self.zone_load_levels[zone_id] = 2
            else:
                self.zone_load_levels[zone_id] = 3

        # 停电原因追踪
        self.zone_outage_cause = {}  # {zone_id: cause}

        # 部分停电状态（切负荷后哪些设施/居民停电）
        self.partial_outage_entities = {}  # {zone_id: {'residents': [...], 'enterprises': [...], 'nodes': [...]}}

        # 打印负荷等级统计
        level_zone_counts = {1: 0, 2: 0, 3: 0}
        for level in self.zone_load_levels.values():
            level_zone_counts[level] += 1
        print(f"[电] 负荷等级分配完成: 一级={level_zone_counts[1]}区, "
              f"二级={level_zone_counts[2]}区, 三级={level_zone_counts[3]}区")

    def _assign_csv_zones(self):
        """为CSV节点分配所在区域"""
        for node in self.csv_nodes:
            zone = self.region_manager.get_region_for_point(node['lon'], node['lat'])
            node['zone'] = zone

        # 统计各区域设施数量
        zone_counts = {}
        for node in self.csv_nodes:
            z = node['zone']
            if z is not None:
                zone_counts[z] = zone_counts.get(z, 0) + 1

        if zone_counts:
            print(f"[统计] CSV节点区域分配完成: {len(self.csv_nodes)} 个节点分配到 {len(zone_counts)} 个区域")

    def _update_csv_power_status(self):
        """根据区域供电状态更新CSV节点供电状态（支持部分停电）"""
        for node in self.csv_nodes:
            zone = node.get('zone')
            if zone is not None:
                # 首先检查区域整体供电状态
                zone_powered = self.zone_status.get(zone, True)

                if not zone_powered:
                    # 区域全部停电
                    powered = False
                else:
                    # 检查是否在部分停电列表中
                    partial = self.partial_outage_entities.get(zone, {})
                    cut_nodes = partial.get('nodes', [])
                    powered = node not in cut_nodes

                # 检查备用电源
                if not powered and node.get('backup_power', False):
                    duration = node.get('outage_duration', 0)
                    backup_duration = node.get('backup_duration', 0)
                    # 备用电源时间内仍视为有电
                    if duration < backup_duration:
                        powered = True

                node['powered'] = powered

                # 更新停电时长
                if not powered:
                    node['outage_duration'] = node.get('outage_duration', 0) + self.dt
                else:
                    node['outage_duration'] = 0

    def _is_entity_powered(self, entity, zone):
        """
        检查实体是否有电（支持部分停电）

        参数:
            entity: 居民或企业实体
            zone: 所在区域ID

        返回:
            bool: 是否有电
        """
        # 检查区域整体供电（全部停电模式）
        if not self.zone_status.get(zone, True):
            return False

        # 【修复】直接检查实体的切负荷标记
        # 这个标记在 _trigger_district_partial_outage 中设置
        if hasattr(entity, '_is_load_shed') and entity._is_load_shed:
            return False

        return True

    def _build_social_network(self):
        """建立居民社交网络"""
        for resident in self.residents:
            # 优先选择同区域或邻近区域的居民
            candidates = []
            my_zone = resident.zone
            neighbor_zones = self.region_manager.region_neighbors.get(my_zone, [])

            for other in self.residents:
                if other is not resident:
                    if other.zone == my_zone or other.zone in neighbor_zones:
                        candidates.append(other)

            # 随机选择3-5个邻居
            if candidates:
                num_neighbors = min(random.randint(3, 5), len(candidates))
                resident.neighbors = random.sample(candidates, num_neighbors)
            else:
                # 如果没有候选，从全体中随机选
                others = [r for r in self.residents if r is not resident]
                if others:
                    resident.neighbors = random.sample(others, min(3, len(others)))

    def _build_district_zone_mapping(self):
        """
        【0128新增】建立区县到区域ID的映射

        用于支持按区县选择停电，将区县名映射到其包含的所有区域ID

        【核心逻辑】从每个区域的source_file路径中提取区县名
        例如：.../地图数据/厦门市/思明区/思明区无山水.geojson -> 思明区
        """
        self.district_to_zones = {}  # {区县名: [zone_id1, zone_id2, ...]}
        self.zone_to_district = {}  # {zone_id: 区县名}

        # 从region_manager的每个区域的source_file中提取区县名
        for zone_id, region_data in self.region_manager.regions.items():
            source_file = region_data.get('source_file', '')

            # 从路径中提取区县名
            # 路径格式：.../地图数据/城市/区县/xxx.geojson
            path_parts = source_file.replace('\\', '/').split('/')

            district_name = None
            for part in path_parts:
                # 找到以"区"、"县"结尾的目录名（排除文件名）
                if (part.endswith('区') or part.endswith('县')) and not part.endswith('.geojson'):
                    district_name = part
                    break

            if district_name:
                if district_name not in self.district_to_zones:
                    self.district_to_zones[district_name] = []
                self.district_to_zones[district_name].append(zone_id)
                self.zone_to_district[zone_id] = district_name

        # 如果没有找到任何映射，使用默认行政区
        if not self.district_to_zones:
            default_district = getattr(self, 'district_name', '默认行政区')
            self.district_to_zones[default_district] = list(self.region_manager.regions.keys())
            for zone_id in self.region_manager.regions.keys():
                self.zone_to_district[zone_id] = default_district

        # 打印映射结果
        print(f"[统计] 区县映射: {len(self.district_to_zones)}个区县, {len(self.zone_to_district)}个区域")
        for district, zones in self.district_to_zones.items():
            print(f"   - {district}: {len(zones)}个区域")

    def get_gov_for_zone(self, zone_id):
        """获取 zone 所在区县的政府Agent"""
        district = self.zone_to_district.get(zone_id)
        if district and district in self.gov_agents:
            return self.gov_agents[district]
        return self.gov

    def trigger_district_outage_by_names(self, district_names, mode='full', cause='equipment_failure',
                                         severity_ratio=0.5):
        """
        【0128新增】按区县名称触发停电

        参数:
            district_names: 区县名称列表，如 ['思明区', '湖里区']
            mode: 停电模式 'full' 或 'partial'
            cause: 停电原因
            severity_ratio: 部分停电时的切负荷比例
        """
        zones_to_outage = []
        for d_name in district_names:
            zones = self.district_to_zones.get(d_name, [])
            zones_to_outage.extend(zones)

        if not zones_to_outage:
            print(f"[警告] 未找到区县 {district_names} 对应的区域")
            return

        print(f"[停电] 触发 {district_names} 停电: {len(zones_to_outage)}个区域, 模式={mode}")

        if mode == 'full':
            self.trigger_district_outage(mode='full', cause=cause)
        else:
            self.trigger_district_outage(mode='partial', cause=cause, severity_ratio=severity_ratio)

    def trigger_independent_district_outages(self, district_configs):
        """
        【0128新增】按行政区独立配置触发停电

        每个行政区有独立的：停电模式、停电原因、切负荷比例
        各行政区的仿真独立运行，互不干扰

        参数:
            district_configs: {
                '思明区': {
                    'enabled': True,
                    'mode': 'partial',
                    'cause': 'typhoon',
                    'severity_ratio': 0.5,
                    'gov_events': {...},
                    'grid_events': {...},
                    'use_all_zones': True,       # 是否使用全部区域
                    'selected_zones': [...]       # 如果use_all_zones=False，使用这些区域
                },
                '湖里区': {...}
            }
        """
        import random

        print("[独立配置] 按行政区独立触发停电...")

        # 保存行政区独立配置到实例
        self.district_independent_configs = district_configs

        for district_name, cfg in district_configs.items():
            if not cfg.get('enabled', False):
                print(f"   [{district_name}] 未启用停电")
                continue

            if district_name not in self.district_to_zones:
                print(f"   [{district_name}] 未找到该行政区")
                continue

            mode = cfg.get('mode', 'partial')
            cause = cfg.get('cause', 'equipment_failure')
            severity_ratio = cfg.get('severity_ratio', 0.5)

            # 【新增】支持选择具体区域
            use_all_zones = cfg.get('use_all_zones', True)
            selected_zones = cfg.get('selected_zones', [])

            # 获取该行政区的区域
            all_district_zones = self.district_to_zones[district_name]

            if use_all_zones or not selected_zones:
                # 使用该行政区的所有区域
                district_zones = all_district_zones
            else:
                # 仅使用选定的区域（需要验证这些区域确实属于该行政区）
                district_zones = [z for z in selected_zones if z in all_district_zones]
                if not district_zones:
                    print(f"   [{district_name}] 选定的区域无效，使用全部区域")
                    district_zones = all_district_zones
                else:
                    print(f"   [{district_name}] 使用选定的 {len(district_zones)}/{len(all_district_zones)} 个区域")

            if mode == 'full' or severity_ratio >= 1.0:
                # 全部停电
                outage_zones = district_zones
                print(f"   [{district_name}] 全部停电: {len(outage_zones)}个区域, 原因={cause}")
            else:
                # 部分停电：按负荷等级切负荷
                zone_by_level = {1: [], 2: [], 3: []}
                for zone_id in district_zones:
                    level = self.zone_load_levels.get(zone_id, 3)
                    zone_by_level[level].append(zone_id)

                total_zones = len(district_zones)
                target_cut = max(1, int(total_zones * severity_ratio))

                outage_zones = []
                for level in [3, 2, 1]:
                    if len(outage_zones) >= target_cut:
                        break
                    available = zone_by_level[level].copy()
                    random.shuffle(available)
                    for zone_id in available:
                        if len(outage_zones) >= target_cut:
                            break
                        outage_zones.append(zone_id)

                print(
                    f"   [{district_name}] 部分停电: {len(outage_zones)}/{total_zones}个区域 ({severity_ratio * 100:.0f}%), 原因={cause}")

            # 设置区域停电状态
            for zone_id in outage_zones:
                self.zone_status[zone_id] = False
                self.zone_duration[zone_id] = 0
                self.zone_outage_cause[zone_id] = cause

            # 更新该行政区的居民和企业状态
            for r in self.residents:
                if r.zone in outage_zones:
                    r.powered = False
                    r._is_load_shed = (mode == 'partial')

            for e in self.enterprises:
                if hasattr(e, 'zone') and e.zone in outage_zones:
                    e.powered = False
                    e._is_load_shed = (mode == 'partial')

        print("[独立配置] 停电触发完成")

    def _init_zone_status(self):
        """
        初始化区域状态

        【架构说明】
        - 行政区级别（如"思明区"）：停电/恢复由外部指令控制
        - 社区级别（如"何厝社区"）：事件发生在此级别

        停电模式由外部指令决定：
        - 全部停电：整个行政区停电
        - 部分停电：按负荷等级切负荷
        """
        config = self.config

        # ==================== 行政区级别状态 ====================
        # 整个行政区的供电状态（外部指令控制）
        self.district_powered = True  # 行政区是否有电
        self.district_outage_mode = None  # 停电模式: 'full' / 'partial' / None
        self.district_outage_cause = None  # 停电原因
        self.district_outage_duration = 0  # 停电时长（小时）
        self.district_repair_progress = 0.0  # 大电网修复进度 (0-1)
        self.district_repair_started = False  # 是否开始修复
        self.district_recovered = False  # 是否已恢复

        # ==================== 社区级别状态（用于事件记录） ====================
        # 各社区的供电状态（由行政区状态决定）
        self.zone_status = {rid: True for rid in self.region_manager.regions.keys()}

        # 社区停电时长（用于事件检测）
        self.zone_duration = {rid: 0 for rid in self.zone_status}

        # 【兼容旧代码】已恢复区域集合
        self.recovered_zones = set()
        self.allow_re_failure = False

        # ==================== 区域物资库存系统 ====================
        # 【核心理念】社会本身有物资（超市、便利店、药店等）
        # 停电后居民恐慌囤积 → 物资减少 → 后来的人抢不到 → 情绪更差
        # 政府发放物资 → 补充库存 → 缓解恐慌

        # 区域物资水平 [0, 1]，1表示充足，0表示耗尽
        self.zone_supply_levels = {rid: 1.0 for rid in self.region_manager.regions.keys()}

        # 区域物资消耗速率（每个囤积居民每小时消耗的物资比例）
        self.supply_consumption_rate = 0.002  # 每人每小时消耗0.2%

        # 物资短缺阈值
        self.supply_shortage_threshold = 0.3  # 低于30%视为短缺
        self.supply_critical_threshold = 0.1  # 低于10%视为严重短缺

        # 政府物资补充效率
        self.gov_supply_replenish_rate = 0.05  # 政府每单位资源补充5%物资

        # 故障系统（行政区级别）
        self.fault_severity = {}
        self.fault_detection_time = {}
        self.fault_ready_for_repair = {}
        self.severity_types = config.fault.SEVERITY_TYPES.copy()

        # 应急响应
        self.emergency_response_delay = config.simulation.EMERGENCY_RESPONSE_DELAY
        self.recovery_allowed = False

        # 根据是否有外部停电配置，选择初始化方式
        if self.use_external_outage and self.outage_config:
            # 使用外部指定的停电配置
            self._apply_external_outage_config()
        else:
            # 默认：行政区有电，不触发停电
            # （等待外部指令触发停电）
            print(f"[电] 行政区 {self.district_name} 初始状态：正常供电")
            print(f"   等待外部指令触发停电...")

    def _apply_external_outage_config(self):
        """
        应用外部停电配置

        【行政区级别停电】
        外部指令控制整个行政区（如"思明区"）的停电状态：
        1. full - 全部停电：整个行政区停电
        2. partial - 部分停电：按负荷等级切负荷

        事件仍在社区级别记录。
        """
        oc = self.outage_config
        mode = oc.get('mode', 'full')
        cause = oc.get('cause', 'equipment_failure')
        severity_ratio = oc.get('severity_ratio', 0.5)  # 负荷缺口比例

        load_config = self.config.load_priority
        cause_config = load_config.OUTAGE_CAUSES.get(cause, load_config.OUTAGE_CAUSES['equipment_failure'])

        # 设置行政区级别停电状态
        self.district_outage_mode = mode
        self.district_outage_cause = cause
        self.district_outage_duration = 0

        print(f"[电] 行政区 {self.district_name} 停电")
        print(f"   停电模式: {mode}")
        print(f"   停电原因: {cause_config['name']}")

        if mode == 'full':
            # 全部停电：整个行政区停电
            self.district_powered = False
            self._trigger_district_full_outage(cause)
            print(f"   影响范围: 全部 {len(self.zone_status)} 个社区")
        elif mode == 'partial':
            # 部分停电：按负荷等级切负荷
            self.district_powered = True  # 行政区部分有电
            self._trigger_district_partial_outage(cause, severity_ratio)
            print(f"   切负荷比例: {severity_ratio * 100:.1f}%")

        # 设置故障检测时间（行政区级别）
        self.district_fault_detection_time = cause_config.get('detection_delay', 0.5)
        self.district_fault_ready = False

    def _trigger_district_full_outage(self, cause='equipment_failure'):
        """
        触发整个行政区全部停电

        参数:
            cause: 停电原因
        """
        # 所有社区停电
        for zone_id in self.zone_status:
            self.zone_status[zone_id] = False
            self.zone_duration[zone_id] = 0
            self.zone_outage_cause[zone_id] = cause

        # 设置故障配置
        load_config = self.config.load_priority
        cause_config = load_config.OUTAGE_CAUSES.get(cause, load_config.OUTAGE_CAUSES['equipment_failure'])

        # 计算大电网修复工作量
        # 如果有自定义损坏程度，使用自定义值
        if hasattr(self, '_custom_damage_level') and self._custom_damage_level is not None:
            base_damage = self._custom_damage_level
            del self._custom_damage_level  # 使用后清除
        else:
            base_damage = cause_config.get('base_damage', 50)

        repair_difficulty = cause_config.get('repair_difficulty', 1.0)
        grid_repair_config = self.config.grid_repair

        # 总工作量 = 损坏程度 × 系数 + 修复难度 × 系数
        self.district_total_work = (
                base_damage * grid_repair_config.DAMAGE_WORK_MULTIPLIER +
                repair_difficulty * grid_repair_config.DIFFICULTY_WORK_MULTIPLIER
        )
        self.district_repair_progress = 0.0

        print(f"   大电网损坏程度: {base_damage}%, 修复难度: {repair_difficulty}")
        print(f"   总修复工作量: {self.district_total_work:.1f}")

    def _trigger_district_partial_outage(self, cause, severity_ratio):
        """
        触发整个行政区部分停电（切负荷）

        【正确的切负荷逻辑】
        按区域数量比例切负荷：
        - severity_ratio = 0.35 表示切除约35%的区域
        - 按负荷等级优先级：三级→二级→一级
        - 选中的区域整体停电

        参数:
            cause: 停电原因
            severity_ratio: 切负荷比例 (0-1)，表示要切除的区域比例
        """
        import random
        load_config = self.config.load_priority

        # ============ 1. 使用预先计算的负荷等级分类区域 ============
        # 【重要】使用初始化时计算的 zone_load_levels，保持一致性
        zone_by_level = {1: [], 2: [], 3: []}  # {level: [zone_id, ...]}
        zone_info = {}  # {zone_id: {'residents': [...], 'enterprises': [...]}}

        for zone_id in self.zone_status:
            zone_residents = [r for r in self.residents if r.zone == zone_id]
            zone_enterprises = [e for e in self.enterprises if e.zone == zone_id]

            # 【修复】使用预先计算的负荷等级，而不是重新计算
            zone_level = self.zone_load_levels.get(zone_id, 3)

            zone_by_level[zone_level].append(zone_id)
            zone_info[zone_id] = {
                'level': zone_level,
                'residents': zone_residents,
                'enterprises': zone_enterprises
            }

        # ============ 2. 计算需要切除的区域数量 ============
        total_zones = len(self.zone_status)
        target_cut_zones = int(total_zones * severity_ratio)

        if target_cut_zones <= 0:
            print(f"   切负荷比例过小，无区域停电")
            return

        # ============ 3. 按优先级选择区域停电 ============
        cut_zones = []

        for target_level in [3, 2, 1]:
            if len(cut_zones) >= target_cut_zones:
                break

            # 该等级的可切区域，随机打乱顺序
            available = zone_by_level[target_level].copy()
            random.shuffle(available)

            for zone_id in available:
                if len(cut_zones) >= target_cut_zones:
                    break

                cut_zones.append(zone_id)
                info = zone_info[zone_id]

                # 记录停电
                partial_entities = {
                    'residents': info['residents'],
                    'enterprises': info['enterprises'],
                    'nodes': []
                }

                # 设置停电状态和切负荷标记
                for r in info['residents']:
                    r.powered = False
                    r._is_load_shed = True  # 【新增】切负荷标记
                for e in info['enterprises']:
                    e.powered = False
                    e._is_load_shed = True  # 【新增】切负荷标记

                self.partial_outage_entities[zone_id] = partial_entities
                self.zone_outage_cause[zone_id] = cause

        # ============ 4. 设置故障信息 ============
        # 【重要】部分停电（切负荷）的修复工作量计算
        # 切负荷是为了在故障修复期间保持电网稳定，故障本身的修复工作量不变
        # 但考虑到部分停电影响范围较小，可以适当减少
        cause_config = load_config.OUTAGE_CAUSES.get(cause, load_config.OUTAGE_CAUSES['equipment_failure'])
        base_damage = cause_config.get('base_damage', 50)
        repair_difficulty = cause_config.get('repair_difficulty', 1.0)
        grid_repair_config = self.config.grid_repair

        # 部分停电工作量 = 基础工作量 × (0.5 + 0.5 × severity_ratio)
        # 例如：50%切负荷 → 75%工作量（不是50%）
        partial_factor = 0.5 + 0.5 * severity_ratio

        self.district_total_work = (
                                           base_damage * grid_repair_config.DAMAGE_WORK_MULTIPLIER +
                                           repair_difficulty * grid_repair_config.DIFFICULTY_WORK_MULTIPLIER
                                   ) * partial_factor
        self.district_repair_progress = 0.0

        # ============ 5. 输出统计信息 ============
        level_stats = {1: 0, 2: 0, 3: 0}
        level_cut_zones = {1: [], 2: [], 3: []}
        for zid in cut_zones:
            lvl = zone_info[zid]['level']
            level_stats[lvl] += 1
            level_cut_zones[lvl].append(zid)

        total_cut_residents = sum(len(p.get('residents', [])) for p in self.partial_outage_entities.values())
        total_cut_enterprises = sum(len(p.get('enterprises', [])) for p in self.partial_outage_entities.values())

        print(
            f"   区域统计: 三级={len(zone_by_level[3])}个, 二级={len(zone_by_level[2])}个, 一级={len(zone_by_level[1])}个")
        print(f"   停电区域: 三级={level_stats[3]}个, 二级={level_stats[2]}个, 一级={level_stats[1]}个")
        print(
            f"   停电总计: {len(cut_zones)}/{total_zones}个区域 ({len(cut_zones) / total_zones * 100:.1f}%), {total_cut_residents}居民, {total_cut_enterprises}企业")

        # 显示停电区域列表
        for lvl in [3, 2, 1]:
            if level_cut_zones[lvl]:
                zones_to_show = level_cut_zones[lvl][:8]
                more = f"...等{len(level_cut_zones[lvl])}个" if len(level_cut_zones[lvl]) > 8 else ""
                short_ids = [zid[-4:] if len(zid) > 4 else zid for zid in zones_to_show]
                print(f"   {lvl}级停电: {', '.join(short_ids)}{more}")

        # 【调试】验证切负荷标记是否正确设置
        load_shed_count = sum(1 for r in self.residents if getattr(r, '_is_load_shed', False))
        unpowered_count = sum(1 for r in self.residents if not r.powered)
        print(f"   【验证】居民切负荷标记: {load_shed_count}人, 实际无电: {unpowered_count}人")

    def _cut_zone_load_level(self, zone_id, level, cut_ratio, partial_entities):
        """
        切除指定区域指定等级的负荷

        【中国电力负荷分级标准】

        参数:
            zone_id: 区域ID
            level: 负荷等级 (1/2/3)
            cut_ratio: 切除比例 (0-1)
            partial_entities: 存储被切负荷实体的字典

        负荷等级说明（按中国标准）:
            - 三级负荷(level=3): 普通居民用电、小型商业（优先切除）
            - 二级负荷(level=2): 工厂、商场、办公楼、学校、中小型企业
            - 一级负荷(level=1): 医院、政府、通信枢纽、交通指挥、大型数据中心（最后切除）

        注意：普通居民全部属于三级负荷，与健康状态无关！
        """
        import random

        # 获取该区域的所有居民和企业
        zone_residents = [r for r in self.residents if r.zone == zone_id]
        zone_enterprises = [e for e in self.enterprises if e.zone == zone_id]

        # ============ 按中国负荷分级标准分类 ============

        # 一级负荷行业（关键设施，最后切）
        # 医院、政府、通信、交通枢纽、大型数据中心
        critical_industries = ['医疗健康', '公共服务', 'IT科技']

        # 二级负荷行业（较重要）
        # 工厂、商场、办公楼、学校
        important_industries = ['制造业', '金融服务', '教育培训']

        # 三级负荷行业（一般负荷，优先切）
        # 普通商业、餐饮、娱乐
        normal_industries = ['零售商业', '餐饮住宿', '文化娱乐', '其他']

        # 分类
        if level == 3:
            # 三级负荷：【所有普通居民】+ 小型企业 + 普通商业行业
            # 普通居民都是三级负荷，与健康状态无关！
            level_residents = zone_residents  # 所有居民都是三级负荷
            level_enterprises = [e for e in zone_enterprises
                                 if e.enterprise_type == '小型' or
                                 getattr(e, 'industry', '') in normal_industries]
        elif level == 2:
            # 二级负荷：中型企业 + 工厂/商场/学校
            # 居民不属于二级负荷
            level_residents = []
            level_enterprises = [e for e in zone_enterprises
                                 if e.enterprise_type == '中型' or
                                 getattr(e, 'industry', '') in important_industries]
        else:  # level == 1
            # 一级负荷：大型企业 + 医院/政府/通信
            # 居民不属于一级负荷（除非有特殊医疗设备依赖，但一般不考虑）
            level_residents = []
            level_enterprises = [e for e in zone_enterprises
                                 if e.enterprise_type == '大型' or
                                 getattr(e, 'industry', '') in critical_industries]

        # 按比例切除居民
        if level_residents and cut_ratio > 0:
            num_to_cut = max(1, int(len(level_residents) * cut_ratio))
            cut_residents = random.sample(level_residents, min(num_to_cut, len(level_residents)))
            partial_entities['residents'].extend(cut_residents)
            for r in cut_residents:
                r.powered = False

        # 按比例切除企业
        if level_enterprises and cut_ratio > 0:
            num_to_cut = max(1, int(len(level_enterprises) * cut_ratio))
            cut_enterprises = random.sample(level_enterprises, min(num_to_cut, len(level_enterprises)))
            partial_entities['enterprises'].extend(cut_enterprises)
            for e in cut_enterprises:
                e.powered = False

    def _trigger_full_outage(self, zone_id, cause='equipment_failure'):
        """
        触发区域全部停电

        参数:
            zone_id: 区域ID
            cause: 停电原因
        """
        self.zone_status[zone_id] = False
        self.zone_duration[zone_id] = 0
        self.zone_outage_cause[zone_id] = cause

        # 根据原因获取故障配置
        load_config = self.config.load_priority
        cause_config = load_config.OUTAGE_CAUSES.get(cause, load_config.OUTAGE_CAUSES['equipment_failure'])

        # 设置故障发现延迟
        self.fault_detection_time[zone_id] = cause_config['detection_delay']
        self.fault_ready_for_repair[zone_id] = False

        # 根据修复难度确定故障严重程度
        difficulty = cause_config.get('repair_difficulty', 1.0)
        if difficulty <= 0:
            self.fault_severity[zone_id] = 'planned'  # 计划停电
        elif difficulty <= 1.0:
            self.fault_severity[zone_id] = 'simple'
        elif difficulty <= 2.0:
            self.fault_severity[zone_id] = 'complex'
        else:
            self.fault_severity[zone_id] = 'disaster'

        # 清空部分停电状态
        if zone_id in self.partial_outage_entities:
            del self.partial_outage_entities[zone_id]

        print(f"   [电] 区域 {zone_id} 全部停电: 原因={cause_config['name']}, "
              f"损坏程度={cause_config.get('base_damage', 50)}")

    def _trigger_partial_outage(self, zone_id, cause='overload', severity_ratio=0.5):
        """
        触发区域部分停电（切负荷）

        【切负荷逻辑】
        外部给一个切负荷比例（severity_ratio）
        按负荷等级从低到高依次切除：三级→二级→一级
        如果三级负荷切完还不够，继续切二级；二级不够切一级

        参数:
            zone_id: 区域ID
            cause: 停电原因
            severity_ratio: 需要切除的负荷比例 (0-1)，如0.3表示切30%负荷
        """
        load_config = self.config.load_priority

        # 获取区域内各类实体
        zone_residents = [r for r in self.residents if r.zone == zone_id]
        zone_enterprises = [e for e in self.enterprises if e.zone == zone_id]
        zone_nodes = [n for n in self.csv_nodes if n.get('zone') == zone_id]

        # 分类设施到各负荷等级
        level_3_entities = {
            'residents': zone_residents,
            'enterprises': zone_enterprises,
            'nodes': [n for n in zone_nodes
                      if load_config.FACILITY_LOAD_LEVELS.get(n.get('category'), 3) == 3]
        }
        level_2_entities = {
            'residents': [],
            'enterprises': [],
            'nodes': [n for n in zone_nodes
                      if load_config.FACILITY_LOAD_LEVELS.get(n.get('category'), 3) == 2]
        }
        level_1_entities = {
            'residents': [],
            'enterprises': [],
            'nodes': [n for n in zone_nodes
                      if load_config.FACILITY_LOAD_LEVELS.get(n.get('category'), 3) == 1]
        }

        # 计算各等级的负荷量（按权重）
        load_weights = load_config.LOAD_WEIGHTS

        def count_load(entities, weight):
            """计算实体的负荷总量"""
            count = (len(entities.get('residents', [])) +
                     len(entities.get('enterprises', [])) +
                     len(entities.get('nodes', [])))
            return count * weight

        load_3 = count_load(level_3_entities, load_weights[3])
        load_2 = count_load(level_2_entities, load_weights[2])
        load_1 = count_load(level_1_entities, load_weights[1])
        total_load = load_3 + load_2 + load_1

        if total_load == 0:
            print(f"   [警告] 区域 {zone_id} 无负荷，跳过切负荷")
            return

        # 需要切除的负荷量
        target_cut_load = total_load * severity_ratio

        # 初始化部分停电实体列表
        partial_entities = {
            'residents': [],
            'enterprises': [],
            'nodes': []
        }

        current_cut_load = 0.0

        # 【第一步】先切三级负荷
        if current_cut_load < target_cut_load and load_3 > 0:
            remaining_to_cut = target_cut_load - current_cut_load
            cut_ratio_3 = min(1.0, remaining_to_cut / load_3)

            # 切除三级负荷中的居民
            num_cut_res = int(len(level_3_entities['residents']) * cut_ratio_3)
            if num_cut_res > 0:
                cut_res = random.sample(level_3_entities['residents'],
                                        min(num_cut_res, len(level_3_entities['residents'])))
                partial_entities['residents'].extend(cut_res)
                current_cut_load += len(cut_res) * load_weights[3]

            # 切除三级负荷中的企业
            num_cut_ent = int(len(level_3_entities['enterprises']) * cut_ratio_3)
            if num_cut_ent > 0:
                cut_ent = random.sample(level_3_entities['enterprises'],
                                        min(num_cut_ent, len(level_3_entities['enterprises'])))
                partial_entities['enterprises'].extend(cut_ent)
                current_cut_load += len(cut_ent) * load_weights[3]

            # 切除三级负荷中的节点
            num_cut_node = int(len(level_3_entities['nodes']) * cut_ratio_3)
            if num_cut_node > 0:
                cut_nodes = random.sample(level_3_entities['nodes'],
                                          min(num_cut_node, len(level_3_entities['nodes'])))
                partial_entities['nodes'].extend(cut_nodes)
                current_cut_load += len(cut_nodes) * load_weights[3]

        # 【第二步】三级不够，切二级负荷
        if current_cut_load < target_cut_load and load_2 > 0:
            remaining_to_cut = target_cut_load - current_cut_load
            cut_ratio_2 = min(1.0, remaining_to_cut / load_2)

            # 切除二级负荷中的节点（学校、社区等）
            num_cut_node = int(len(level_2_entities['nodes']) * cut_ratio_2)
            if num_cut_node > 0:
                cut_nodes = random.sample(level_2_entities['nodes'],
                                          min(num_cut_node, len(level_2_entities['nodes'])))
                partial_entities['nodes'].extend(cut_nodes)
                current_cut_load += len(cut_nodes) * load_weights[2]

        # 【第三步】二级不够，切一级负荷（最后手段）
        if current_cut_load < target_cut_load and load_1 > 0:
            remaining_to_cut = target_cut_load - current_cut_load
            cut_ratio_1 = min(1.0, remaining_to_cut / load_1)

            # 切除一级负荷中的节点（医院、政府等）
            num_cut_node = int(len(level_1_entities['nodes']) * cut_ratio_1)
            if num_cut_node > 0:
                cut_nodes = random.sample(level_1_entities['nodes'],
                                          min(num_cut_node, len(level_1_entities['nodes'])))
                partial_entities['nodes'].extend(cut_nodes)
                current_cut_load += len(cut_nodes) * load_weights[1]

        # 保存部分停电状态
        self.partial_outage_entities[zone_id] = partial_entities

        # 区域整体仍标记为有电（部分停电）
        self.zone_status[zone_id] = True
        self.zone_outage_cause[zone_id] = cause

        # 设置故障信息
        cause_config = load_config.OUTAGE_CAUSES.get(cause, load_config.OUTAGE_CAUSES['overload'])
        self.fault_detection_time[zone_id] = cause_config['detection_delay']
        self.fault_severity[zone_id] = 'simple'  # 部分停电一般是简单故障
        self.fault_ready_for_repair[zone_id] = False

        # 计算实际切除比例
        actual_cut_ratio = current_cut_load / total_load if total_load > 0 else 0

        total_cut = (len(partial_entities['residents']) +
                     len(partial_entities['enterprises']) +
                     len(partial_entities['nodes']))

        print(f"   [电] 区域 {zone_id} 部分停电: 目标切{severity_ratio * 100:.0f}%, "
              f"实际切{actual_cut_ratio * 100:.1f}%, 受影响={total_cut}实体")

    def trigger_district_outage(self, mode='full', cause='equipment_failure',
                                severity_ratio=0.5, damage_level=None):
        """
        【主要接口】外部触发行政区停电

        参数:
            mode: 停电模式
                - 'full': 全部停电（整个行政区停电）
                - 'partial': 部分停电（按负荷等级切负荷）

            cause: 停电原因，影响修复难度
                - 'equipment_failure': 设备故障（默认，中等难度）
                - 'overload': 过载跳闸（较快修复）
                - 'external_damage': 外力破坏（较慢修复）
                - 'natural_disaster': 自然灾害（最慢修复）
                - 'planned_outage': 计划停电（无需修复）

            severity_ratio: 部分停电时的负荷缺口比例 (0-1)
                - 0.3 = 切30%负荷
                - 0.5 = 切50%负荷
                - 0.8 = 切80%负荷

            damage_level: 损坏程度 (0-100)，可选
                - 如果提供，会覆盖cause的默认损坏程度
                - 数值越高，修复时间越长

        示例:
            sim.trigger_district_outage(mode='full', cause='natural_disaster')
            sim.trigger_district_outage(mode='partial', severity_ratio=0.4)
            sim.trigger_district_outage(mode='full', damage_level=80)  # 自定义损坏程度
        """
        if self.district_outage_mode is not None:
            print(f"[警告] 行政区 {self.district_name} 已处于停电状态")
            return

        # 构建停电配置
        self.outage_config = {
            'mode': mode,
            'cause': cause,
            'severity_ratio': severity_ratio,
        }

        # 如果提供了自定义损坏程度
        if damage_level is not None:
            self._custom_damage_level = damage_level

        # 应用停电配置
        self._apply_external_outage_config()

        # 计算预估修复时间
        estimated_hours, repair_info = self._estimate_repair_time()
        days = estimated_hours / 24
        steps = estimated_hours / self.dt

        if days >= 1:
            print(f"   预估修复时间: {estimated_hours:.1f} 小时（约 {days:.1f} 天）")
        else:
            print(f"   预估修复时间: {estimated_hours:.1f} 小时")
        print(f"   预估修复步数: {steps:.0f} 步")
        print(f"   当前修复能力: {repair_info['capacity']:.2f} 单位/小时")

    def _estimate_repair_time(self):
        """
        估算修复时间

        返回: (预估小时数, 修复信息字典)
        """
        total_work = getattr(self, 'district_total_work', 100)

        # 使用当前资源估算
        R = getattr(self.grid, 'current_resource_level', 50)
        grid_config = self.config.grid_repair

        # 资源效率
        resource_efficiency = (
                grid_config.RESOURCE_EFFICIENCY_BASE +
                (grid_config.RESOURCE_EFFICIENCY_MAX - grid_config.RESOURCE_EFFICIENCY_BASE) *
                R / (R + grid_config.RESOURCE_HALF_POINT)
        )

        # 积极程度系数
        initiative_factor = (
                grid_config.INITIATIVE_BASE +
                self.grid.initiative * grid_config.INITIATIVE_MULTIPLIER
        )

        # 响应效率系数
        response_factor = (
                grid_config.RESPONSE_BASE +
                self.grid.response * grid_config.RESPONSE_MULTIPLIER
        )

        # 修复能力
        repair_capacity = (
                grid_config.BASE_REPAIR_CAPACITY *
                resource_efficiency *
                initiative_factor *
                response_factor
        )

        repair_info = {
            'capacity': repair_capacity,
            'resource_efficiency': resource_efficiency,
            'initiative_factor': initiative_factor,
            'response_factor': response_factor,
            'total_work': total_work
        }

        # 预估时间 = 总工作量 / 修复能力
        if repair_capacity > 0:
            estimated_hours = total_work / repair_capacity
            return estimated_hours, repair_info
        return float('inf'), repair_info

    # 【兼容旧代码】保留原有方法名
    def trigger_outage(self, zone_ids=None, mode='full', cause='equipment_failure', severity_ratio=0.5):
        """
        【兼容旧代码】触发停电

        新代码请使用 trigger_district_outage()
        """
        # 直接调用新接口
        self.trigger_district_outage(mode=mode, cause=cause, severity_ratio=severity_ratio)

    def restore_zone(self, zone_id):
        """
        【废弃】外部触发区域恢复供电

        在新架构中，恢复供电是行政区级别的，由电网修复完成后自动触发。
        此方法保留兼容性。
        """
        # 清空部分停电状态
        if zone_id in self.partial_outage_entities:
            del self.partial_outage_entities[zone_id]

        # 清空故障信息
        if zone_id in self.fault_severity:
            del self.fault_severity[zone_id]
        if zone_id in self.zone_outage_cause:
            del self.zone_outage_cause[zone_id]

    def _init_history(self):
        """初始化历史记录"""
        # 主要指标历史
        self.Q_hist = []  # 企业平均求助强度
        self.C_hist = []  # 关键设施求助
        self.R_hist = []  # 政府资源下发量
        self.P_hist = []  # 综合舆情指数

        # 系统状态历史
        self.emotion_hist = []  # 平均情绪
        self.emotion_std_hist = []  # 情绪标准差
        self.recovery_hist = []  # 供电恢复率
        self.blackout_hist = []  # 区域停电率
        self.informed_hist = []  # 居民知情率
        self.outage_count_hist = []  # 停电区域数

        # SEIR状态历史
        self.seir_hist = {'S': [], 'E': [], 'I': [], 'R': []}

        # 恐慌相关历史
        self.region_panic_hist = {}
        self.panic_stats_hist = []

        # 当前时间步
        self.t = 0

    def _init_event_system(self):
        """初始化事件记录系统和事件影响计算器"""
        self.event_recorder = EventRecorder()
        self.event_detector = EventDetector(self.event_recorder)
        self.event_influence = EventInfluenceCalculator(self.config)
        print("[事件] 事件记录系统已初始化")
        print("[事件] 事件影响计算器已初始化")

    def _init_time_system(self):
        """
        初始化时间系统 - 支持昼夜差异

        【时间参数】
        - 每步 = 0.25小时 = 15分钟
        - 1天 = 96步

        【昼夜影响】
        - 夜间(22:00-6:00)：照明需求高，安全担忧增加，情绪敏感度+30%
        - 傍晚(18:00-22:00)：用电高峰，影响最大
        - 白天(6:00-18:00)：相对正常

        【默认开始时间】
        - 假设仿真从上午8:00开始
        """
        # 仿真开始的小时数（24小时制）
        self.start_hour = 8.0  # 默认早上8点开始

        # 当前仿真时间（小时）
        self.current_hour = self.start_hour

        # 当前是第几天
        self.current_day = 1

        # 时间段定义（小时区间）
        self.time_periods = {
            'night': (22, 6),  # 深夜
            'morning': (6, 9),  # 早晨
            'daytime': (9, 18),  # 白天
            'evening': (18, 22),  # 傍晚/用电高峰
        }

        # 各时段对情绪/恐慌的影响系数
        self.time_impact_factors = {
            'night': {
                'emotion_sensitivity': 1.3,  # 夜间情绪敏感度+30%
                'panic_sensitivity': 1.4,  # 夜间恐慌敏感度+40%
                'gathering_tendency': 0.5,  # 夜间聚集倾向降低
                'description': '深夜',
            },
            'morning': {
                'emotion_sensitivity': 1.0,
                'panic_sensitivity': 1.0,
                'gathering_tendency': 0.8,
                'description': '早晨',
            },
            'daytime': {
                'emotion_sensitivity': 0.9,  # 白天情绪稳定
                'panic_sensitivity': 0.85,
                'gathering_tendency': 1.2,  # 白天更容易聚集
                'description': '白天',
            },
            'evening': {
                'emotion_sensitivity': 1.2,  # 傍晚下班后情绪敏感
                'panic_sensitivity': 1.15,
                'gathering_tendency': 1.3,  # 傍晚最容易聚集
                'description': '傍晚',
            },
        }

        print(f"[时间] 时间系统已初始化 (开始时间: {int(self.start_hour)}:00)")

    def _update_time(self):
        """更新仿真时间"""
        self.current_hour += self.dt
        if self.current_hour >= 24:
            self.current_hour -= 24
            self.current_day += 1

    def get_current_time_period(self):
        """获取当前时间段"""
        hour = self.current_hour

        # 检查是否在深夜（跨越午夜）
        night_start, night_end = self.time_periods['night']
        if hour >= night_start or hour < night_end:
            return 'night'

        for period, (start, end) in self.time_periods.items():
            if period != 'night' and start <= hour < end:
                return period

        return 'daytime'  # 默认

    def get_time_impact_factor(self, factor_name='emotion_sensitivity'):
        """获取当前时间的影响因子"""
        period = self.get_current_time_period()
        return self.time_impact_factors[period].get(factor_name, 1.0)

    def _assign_fault_severity(self, zone):
        """为区域分配故障严重程度"""
        rand = random.random()
        cumulative = 0
        for severity, sconfig in self.severity_types.items():
            cumulative += sconfig['probability']
            if rand <= cumulative:
                self.fault_severity[zone] = severity
                self.fault_detection_time[zone] = sconfig['detection_delay']
                self.fault_ready_for_repair[zone] = False
                return
        # 默认
        self.fault_severity[zone] = 'simple'
        self.fault_detection_time[zone] = self.severity_types['simple']['detection_delay']
        self.fault_ready_for_repair[zone] = False

    def _update_fault_detection(self):
        """更新故障发现状态"""
        for zone in list(self.fault_detection_time.keys()):
            if not self.zone_status[zone] and not self.fault_ready_for_repair.get(zone, False):
                self.fault_detection_time[zone] -= self.dt
                if self.fault_detection_time[zone] <= 0:
                    self.fault_ready_for_repair[zone] = True

    def _simulate_emergency_blackouts(self):
        """
        【废弃】模拟应急停电扩散

        在新架构中，停电由外部指令控制（行政区级别），
        不需要自动扩散。此方法保留兼容性但不执行操作。
        """
        # 行政区级别停电，由外部指令控制
        pass

    def _old_simulate_emergency_blackouts(self):
        """【旧代码备份】模拟应急停电扩散"""
        total_zones = len(self.zone_status)
        target_outages = int(total_zones * self.config.simulation.INITIAL_OUTAGE_RATIO)
        current_outages = sum(1 for st in self.zone_status.values() if not st)

        steps_remaining = self.emergency_response_delay - self.step_count
        if steps_remaining > 0 and current_outages < target_outages:
            needed = target_outages - current_outages
            outages_this_step = min(needed, (needed + steps_remaining - 1) // steps_remaining)

            if self.step_count < 3:
                outages_this_step = int(outages_this_step * 1.3)

            powered_zones = [z for z, st in self.zone_status.items() if st]
            outage_zones = [z for z, st in self.zone_status.items() if not st]

            if powered_zones and outages_this_step > 0:
                # 按邻近性加权选择
                zone_weights = []
                for zone in powered_zones:
                    if outage_zones:
                        neighbors = self.region_manager.region_neighbors.get(zone, [])
                        neighbor_outages = sum(1 for n in neighbors if n in outage_zones)
                        weight = max(1, neighbor_outages * 3 + 1)
                    else:
                        weight = 1
                    zone_weights.append(weight)

                # 加权随机选择
                for _ in range(min(outages_this_step, len(powered_zones))):
                    if not powered_zones:
                        break

                    total_weight = sum(zone_weights)
                    if total_weight > 0:
                        rand_val = random.random() * total_weight
                        cumulative = 0
                        for i, weight in enumerate(zone_weights):
                            cumulative += weight
                            if rand_val <= cumulative:
                                zone = powered_zones.pop(i)
                                zone_weights.pop(i)
                                self.zone_status[zone] = False
                                self.zone_duration[zone] = 0
                                self._assign_fault_severity(zone)
                                break

    def zone_recover(self, R):
        """
        行政区级别大电网修复逻辑

        【修复逻辑】
        1. 电网修的是整个行政区的大电网，不是每个社区分别修
        2. 修复能力 = f(资源量, 积极程度, 响应效率)
        3. 修复进度 = 累计修复量 / 总需修复量
        4. 修好了整个行政区恢复供电（所有社区同时恢复）

        【修复能力公式】
        修复能力 = 基础修复能力 × 资源效率 × 积极程度系数 × 响应效率系数
        """
        if not self.recovery_allowed:
            return

        # 如果行政区已恢复，无需修复
        if self.district_recovered:
            return

        # 如果没有停电，无需修复
        if self.district_outage_mode is None:
            return

        # 检查故障是否已发现（故障检测延迟）
        if hasattr(self, 'district_fault_detection_time') and self.district_fault_detection_time > 0:
            self.district_fault_detection_time -= self.dt
            if self.district_fault_detection_time <= 0:
                self.district_fault_ready = True
                print(f"   [发现] {self.district_name} 故障已发现，准备开始修复")
            return

        if not getattr(self, 'district_fault_ready', False):
            return

        # 开始修复（如果还没开始）
        if not self.district_repair_started:
            self.district_repair_started = True
            print(f"   [修复] 开始修复 {self.district_name} 大电网")
            print(f"      总工作量: {getattr(self, 'district_total_work', 100):.1f}")

            # 【修复】同步更新 grid.ongoing_repairs，使事件8（电网抢修）能被检测
            # 原问题：zone_recover 和 grid.ongoing_repairs 两套系统不同步
            # 导致事件检测器永远检测不到事件8
            for zone_id in self.zone_status:
                if not self.zone_status[zone_id]:  # 停电区域
                    self.grid.ongoing_repairs[zone_id] = {
                        'damage_level': getattr(self, 'district_damage_level', 50),
                        'repair_difficulty': getattr(self, 'district_repair_difficulty', 1.0),
                        'start_step': self.step_count,
                        'progress': 0.0,
                        'resources_needed': 10.0  # 标准资源需求
                    }
            self.grid.is_repairing = True

        # 计算修复能力
        grid_config = self.config.grid_repair

        # 资源效率 = 0.3 + 0.7 × R/(R+50)
        resource_efficiency = (
                grid_config.RESOURCE_EFFICIENCY_BASE +
                (grid_config.RESOURCE_EFFICIENCY_MAX - grid_config.RESOURCE_EFFICIENCY_BASE) *
                R / (R + grid_config.RESOURCE_HALF_POINT)
        )

        # 积极程度系数 = 0.5 + initiative × 2.0
        initiative_factor = (
                grid_config.INITIATIVE_BASE +
                self.grid.initiative * grid_config.INITIATIVE_MULTIPLIER
        )

        # 响应效率系数 = 0.3 + response × 1.5
        response_factor = (
                grid_config.RESPONSE_BASE +
                self.grid.response * grid_config.RESPONSE_MULTIPLIER
        )

        # 修复能力 = 基础能力 × 各系数
        repair_capacity = (
                grid_config.BASE_REPAIR_CAPACITY *
                resource_efficiency *
                initiative_factor *
                response_factor
        )

        # 更新修复进度
        total_work = getattr(self, 'district_total_work', 100)
        repair_amount = repair_capacity * self.dt
        self.district_repair_progress += repair_amount / total_work

        # 检查是否修复完成
        if self.district_repair_progress >= 1.0:
            self._restore_district_power()
        else:
            # 输出修复进度（每10%输出一次）
            progress_pct = int(self.district_repair_progress * 100)
            if progress_pct % 10 == 0 and progress_pct > 0:
                if not hasattr(self, '_last_progress_print') or self._last_progress_print != progress_pct:
                    self._last_progress_print = progress_pct
                    # 只在整10%时输出
                    if progress_pct in [10, 20, 30, 40, 50, 60, 70, 80, 90]:
                        print(f"   [修复] {self.district_name} 修复进度: {progress_pct}%")

    def _restore_district_power(self):
        """
        恢复整个行政区供电

        修复完成后，所有社区同时恢复供电
        """
        print(f"\n{'=' * 60}")
        print(f"   [OK] {self.district_name} 大电网修复完成，恢复供电！")
        print(f"{'=' * 60}\n")

        # 恢复行政区状态
        self.district_powered = True
        self.district_recovered = True
        self.district_outage_mode = None
        self.district_outage_cause = None
        self.district_repair_started = False

        # 【修复】同步清理 grid.ongoing_repairs
        self.grid.ongoing_repairs.clear()
        self.grid.is_repairing = False

        # 恢复所有社区供电
        for zone_id in self.zone_status:
            self.zone_status[zone_id] = True
            self.zone_duration[zone_id] = 0
            self.recovered_zones.add(zone_id)

            # 清空故障信息
            if zone_id in self.zone_outage_cause:
                del self.zone_outage_cause[zone_id]
            if zone_id in self.fault_severity:
                del self.fault_severity[zone_id]

        # 清空所有部分停电状态，并恢复所有居民/企业的供电
        # 先恢复被切负荷的居民和企业
        for zone_id, partial in self.partial_outage_entities.items():
            for r in partial.get('residents', []):
                r.powered = True
                r._is_load_shed = False  # 【新增】清除切负荷标记
            for e in partial.get('enterprises', []):
                e.powered = True
                e._is_load_shed = False  # 【新增】清除切负荷标记
        self.partial_outage_entities.clear()

        # 确保所有居民和企业都有电，清除切负荷标记
        for r in self.residents:
            r.powered = True
            r._is_load_shed = False
        for e in self.enterprises:
            e.powered = True
            e._is_load_shed = False

    def _has_partial_outage(self, zone_id):
        """检查区域是否有部分停电"""
        partial = self.partial_outage_entities.get(zone_id, {})
        return (len(partial.get('residents', [])) > 0 or
                len(partial.get('enterprises', [])) > 0 or
                len(partial.get('nodes', [])) > 0)

    def _recover_partial_outages(self):
        """
        【废弃】此方法在新架构中不再使用
        部分停电的恢复统一由 _restore_district_power 处理
        """
        pass

    def zone_propagate(self):
        """
        【废弃】故障传播

        在新架构中，停电是行政区级别的（由外部指令控制），
        不存在社区之间的故障传播。此方法保留兼容性但不执行操作。
        """
        # 行政区级别停电，不需要社区间传播
        pass

    def calculate_region_panic_levels(self):
        """计算所有区域恐慌水平"""
        levels = {}
        for region_id in self.region_manager.regions.keys():
            level = self.region_manager.get_region_panic_level(self.residents, region_id)
            levels[region_id] = level

            if region_id not in self.region_panic_hist:
                self.region_panic_hist[region_id] = []
            self.region_panic_hist[region_id].append(level)

        return levels

    def step(self):
        """
        执行一个仿真步

        这是仿真的核心方法，每一步：
        1. 更新区域时长和故障发现
        2. 模拟停电扩散（前几步）
        3. 计算区域恐慌水平
        4. 计算社会力
        5. 收集指标
        6. 政府/电网决策
        7. 更新所有Agent
        8. 记录历史数据
        """
        # 0. 【新增】更新仿真时间（昼夜差异）
        self._update_time()

        # 1. 区域时长累积
        for z, st in self.zone_status.items():
            if not st:
                self.zone_duration[z] += self.dt

        self._update_fault_detection()

        # 更新CSV主体供电状态
        self._update_csv_power_status()

        # 2. 前几步模拟大规模停电
        if self.step_count < self.emergency_response_delay:
            self._simulate_emergency_blackouts()

        if self.step_count >= self.emergency_response_delay:
            self.recovery_allowed = True

        # 3. 计算区域恐慌水平
        region_panic_levels = self.calculate_region_panic_levels()

        # 4. 计算社会力
        social_forces = {}
        for r in self.residents:
            force = self.force_calculator.calculate_force(r, r.neighbors)
            social_forces[r] = force

        # 获取停电区域作为危险源
        hazard_positions = []
        for z, st in self.zone_status.items():
            if not st:
                centroid = self.region_manager.region_centroids.get(z)
                if centroid:
                    hazard_positions.append((centroid.x, centroid.y))

        # 收集区域几何（用于居民移动边界约束）
        region_geometries = {}
        for region_id, region_data in self.region_manager.regions.items():
            region_geometries[region_id] = region_data['geometry']

        # ============================================================
        # 更新恐慌模型 + 社会力 + 居民位置（完整版）
        # 这里会调用完整的社会力和恐慌模型，让居民真正移动起来
        # 居民会向有电区域移动，形成集群
        # ============================================================

        # 【新增】传递当前时间给所有居民（用于24小时作息规律）
        for r in self.residents:
            r._current_hour = self.current_hour
            r._current_day = self.current_day
            r._time_period = self.get_current_time_period()

        self.force_calculator.panic_model.set_hazards(hazard_positions)
        self.force_calculator.update(
            agents=self.residents,
            dt=self.dt,
            hazard_positions=hazard_positions,
            region_geometries=region_geometries,
            zone_status=self.zone_status,  # 供电状态
            region_centroids=self.region_manager.region_centroids  # 区域中心
        )

        # 5. 收集企业指标（支持部分停电）
        enterprise_requests = []
        for e in self.enterprises:
            # 使用新的供电状态检查方法
            e.powered = self._is_entity_powered(e, e.zone)
            e.step(e.powered, self.dt)
            enterprise_requests.append(e.request())

        # 计算统计指标
        avg_emo = np.mean([r.emotion for r in self.residents])
        emotion_std = np.std([r.emotion for r in self.residents])
        emotion_factor = max(0, avg_emo - 0.3) * 2

        Q_total = sum(enterprise_requests)
        Q_avg = Q_total / len(self.enterprises) if self.enterprises else 0.0

        powered_residents = sum(1 for r in self.residents if self.zone_status.get(r.zone, True))
        powered_ratio = powered_residents / len(self.residents) if self.residents else 1.0
        outage_ratio = 1 - powered_ratio

        C_total = sum(c.request(outage_ratio, emotion_factor) for c in self.criticals)

        # 综合舆情指数
        emotion_component = min(1.0, emotion_factor)
        enterprise_component = min(1.0, Q_avg)
        critical_component = min(1.0, C_total / (len(self.criticals) + 1e-6))
        P = 0.4 * emotion_component + 0.3 * enterprise_component + 0.3 * critical_component
        P = min(1.0, P)

        # 6. 各区政府独立决策
        # 预计算按区分组
        district_residents = {d: [] for d in self.district_to_zones}
        for r in self.residents:
            d = self.zone_to_district.get(r.zone)
            if d and d in district_residents:
                district_residents[d].append(r)

        district_enterprises = {d: [] for d in self.district_to_zones}
        for e in self.enterprises:
            d = self.zone_to_district.get(getattr(e, 'zone', None))
            if d and d in district_enterprises:
                district_enterprises[d].append(e)

        district_gov_influence = {}
        total_gov_influence = 0
        n_districts = len(self.gov_agents)

        for district, gov in self.gov_agents.items():
            d_zones = self.district_to_zones.get(district, [])
            d_res = district_residents.get(district, [])
            d_ent = district_enterprises.get(district, [])

            d_avg_emo = np.mean([r.emotion for r in d_res]) if d_res else 0
            d_outage_count = sum(1 for z in d_zones if not self.zone_status.get(z, True))
            d_outage_ratio = d_outage_count / len(d_zones) if d_zones else 0
            d_Q = sum(e.request() for e in d_ent)
            d_loss = sum(e.loss for e in d_ent)
            d_panic = {z: region_panic_levels.get(z, 0) for z in d_zones}
            d_C = C_total / n_districts if n_districts > 0 else 0

            inf = gov.decide(d_loss, d_avg_emo, d_Q, d_C, d_panic, d_outage_ratio)
            district_gov_influence[district] = inf
            total_gov_influence += inf

        # 电网决策（电网仍是全局共享资源）
        R = self.grid.decide_recovery(total_gov_influence, outage_ratio, P, region_panic_levels)

        # 执行恢复和传播
        self.zone_recover(R)
        self.zone_propagate()

        # 更新资源
        self.grid.update_resources(R)

        # 各区政府按贡献比例分配资源
        for district, gov in self.gov_agents.items():
            d_res = district_residents.get(district, [])
            d_ent = district_enterprises.get(district, [])
            d_zones = self.district_to_zones.get(district, [])
            d_panic = {z: region_panic_levels.get(z, 0) for z in d_zones}

            if total_gov_influence > 0:
                R_district = R * (district_gov_influence[district] / total_gov_influence)
            else:
                R_district = R / n_districts if n_districts > 0 else 0
            gov.allocate_resources(d_ent, R_district, d_panic, d_res)

        # ============ 区域物资系统更新 ============
        # 【核心流程】
        # 1. 统计各区域囤积居民数量 → 消耗物资
        # 2. 政府发放物资 → 补充库存
        # 3. 将物资状态传递给居民（影响情绪）

        # 1. 统计各区域囤积居民数量
        zone_hoarding_counts = {}
        for r in self.residents:
            if r.is_hoarding:
                zone_hoarding_counts[r.zone] = zone_hoarding_counts.get(r.zone, 0) + 1

        # 2. 消耗区域物资（囤积行为消耗物资）
        for zone_id, hoarding_count in zone_hoarding_counts.items():
            if zone_id in self.zone_supply_levels:
                # 消耗量 = 囤积人数 × 消耗速率 × 时间步长(小时)
                consumption = hoarding_count * self.supply_consumption_rate * self.dt
                self.zone_supply_levels[zone_id] = max(0, self.zone_supply_levels[zone_id] - consumption)

        # 3. 各区政府发放物资时补充库存
        if R > 0:
            for district, gov in self.gov_agents.items():
                zone_allocation = getattr(gov, 'zone_resource_allocation', {})
                if total_gov_influence > 0:
                    R_d = R * (district_gov_influence.get(district, 0) / total_gov_influence)
                else:
                    R_d = R / n_districts if n_districts > 0 else 0
                for zone_id, allocation_ratio in zone_allocation.items():
                    if zone_id in self.zone_supply_levels:
                        replenish = R_d * allocation_ratio * self.gov_supply_replenish_rate
                        self.zone_supply_levels[zone_id] = min(1.0, self.zone_supply_levels[zone_id] + replenish)

        # 7. 更新居民状态（支持部分停电，位置已在force_calculator.update中更新）

        # ============ 【新增】计算邻近区域恐慌水平 ============
        # 这是修复"临近未停电区域居民情绪传播"的关键！
        # 对于有电区域的居民，如果相邻区域有停电且恐慌，也应该产生担忧情绪
        zone_adjacent_panic = {}  # {zone_id: max_adjacent_panic}
        for zone_id in self.region_manager.regions.keys():
            # 获取邻近区域列表
            neighbor_zones = self.region_manager.region_neighbors.get(zone_id, [])
            if neighbor_zones:
                # 取邻近区域中的最大恐慌值
                adjacent_panics = [region_panic_levels.get(nz, 0) for nz in neighbor_zones]
                zone_adjacent_panic[zone_id] = max(adjacent_panics) if adjacent_panics else 0
            else:
                zone_adjacent_panic[zone_id] = 0

        for r in self.residents:
            # 使用新的供电状态检查方法
            r.powered = self._is_entity_powered(r, r.zone)
            region_panic = region_panic_levels.get(r.zone, 0)

            # 【新增】设置邻近区域恐慌水平 - 修复临近区域情绪传播
            # 即使自己有电，看到隔壁小区停电恐慌，也会产生担忧
            r.adjacent_zone_panic = zone_adjacent_panic.get(r.zone, 0)

            # 【新增】获取区域物资水平
            zone_supply = self.zone_supply_levels.get(r.zone, 1.0)
            r.zone_supply_level = zone_supply  # 传递给居民

            # 【新增】物资短缺判定
            r.supply_shortage = zone_supply < self.supply_shortage_threshold
            r.supply_critical = zone_supply < self.supply_critical_threshold

            # ============ 【改造】传递所在区政府事件状态给居民 ============
            district_gov = self.get_gov_for_zone(r.zone)

            # 【事件1：发布应急预警】提升居民承担能力
            r._gov_warning_received = getattr(district_gov, 'emergency_warning_issued', False)

            # 【事件4：分配资源给居民】只有开启时才传递资源量
            resource_to_resident = getattr(district_gov, 'resource_to_resident', False)
            if resource_to_resident:
                district = self.zone_to_district.get(r.zone)
                if total_gov_influence > 0 and district:
                    R_d = R * (district_gov_influence.get(district, 0) / total_gov_influence)
                else:
                    R_d = R / n_districts if n_districts > 0 else 0
                gov_resource_for_resident = R_d
            else:
                gov_resource_for_resident = 0

            # 设置政府资源分配标志（用于抑制聚集行为，取消后聚集恢复）
            r._gov_resource_received = resource_to_resident

            # 【事件5：舆情管理】短期压制+长期反扑+减少假信息
            r._opinion_management_active = getattr(district_gov, 'public_opinion_active', False)

            # 注意：位置更新已在force_calculator.update()中完成
            # 这里只更新情绪、SEIR状态等
            r.step(self.dt, None, gov_resource_for_resident, region_panic, hazard_positions)

        # Agent调整 —— 各区政府独立调整
        for district, gov in self.gov_agents.items():
            d_zones = self.district_to_zones.get(district, [])
            d_outage_count = sum(1 for z in d_zones if not self.zone_status.get(z, True))
            d_outage_ratio = d_outage_count / len(d_zones) if d_zones else 0
            gov.adjust(P, d_outage_ratio)
        self.grid.adjust(outage_ratio, P)
        for c in self.criticals:
            c.adjust(outage_ratio)

        # 8. 记录历史
        self.step_count += 1
        self.Q_hist.append(Q_avg)
        self.C_hist.append(C_total)
        self.R_hist.append(R)
        self.P_hist.append(P)

        self.emotion_hist.append(avg_emo)
        self.emotion_std_hist.append(emotion_std)
        self.recovery_hist.append(powered_ratio)
        self.blackout_hist.append(outage_ratio)
        self.informed_hist.append(np.mean([r.informed for r in self.residents]))
        self.outage_count_hist.append(sum(1 for st in self.zone_status.values() if not st))

        # SEIR统计
        for state in ['S', 'E', 'I', 'R']:
            count = sum(1 for r in self.residents if r.state == state)
            self.seir_hist[state].append(count / len(self.residents))

        # 恐慌统计
        panic_stats = self.force_calculator.get_statistics(self.residents)
        self.panic_stats_hist.append(panic_stats)

        # 区域恐慌水平（用于地图颜色）
        for region_id, panic_level in region_panic_levels.items():
            if region_id not in self.region_panic_hist:
                self.region_panic_hist[region_id] = []
            self.region_panic_hist[region_id].append(panic_level)

        # 当前时间步（用于外部获取）
        self.t = self.step_count

        # 9. 检测并记录事件
        self.event_detector.detect_events(self, self.step_count)

        # 10. 计算并应用事件影响
        event_effects = self.event_influence.calculate_all_effects(self, self.dt)
        self.event_influence.apply_effects(self, event_effects, self.dt)

        # 保存事件影响统计（可选，用于分析）
        if not hasattr(self, 'event_effects_hist'):
            self.event_effects_hist = []
        self.event_effects_hist.append(event_effects.get('summary', {}))

    def reset(self, N_residents=None, seir_ratios=None):
        """重置仿真"""
        if N_residents is not None:
            self.config.simulation.N_RESIDENTS = int(N_residents)
        if seir_ratios is not None:
            self.config.simulation.SEIR_RATIOS = seir_ratios.copy()

        self.__init__(self.config)

    def get_current_state(self):
        """获取当前仿真状态"""
        return {
            'step': self.step_count,
            'zone_status': self.zone_status.copy(),
            'zone_duration': self.zone_duration.copy(),
            'ongoing_repairs': list(self.grid.ongoing_repairs.keys()),
            'residents': self.residents,
            'enterprises': self.enterprises,
            'emotion_avg': self.emotion_hist[-1] if self.emotion_hist else 0,
            'recovery_rate': self.recovery_hist[-1] if self.recovery_hist else 1,
            'outage_count': self.outage_count_hist[-1] if self.outage_count_hist else 0,
        }

    def finalize_events(self):
        """
        完成事件记录
        在仿真结束时调用，关闭所有活跃事件
        【重要】只在仿真完全结束时调用一次！
        """
        self.event_detector.finalize()

    def export_events_to_csv(self, filepath, finalize=True):
        """
        导出事件记录到CSV文件

        参数:
            filepath: CSV文件路径
            finalize: 是否关闭活跃事件（默认True，中间保存时应设为False）

        返回:
            int: 导出的事件数量

        CSV格式（4列）:
            event_id: 事件ID号
            zone_id: 发生事件的位置区域ID号
            start_time: 事件起始时间
            end_time: 事件结束时间

        【注意】中间保存时设置 finalize=False，避免关闭正在进行的事件！
        """
        if finalize:
            self.finalize_events()
        # 导出CSV
        count = self.event_recorder.export_to_csv(filepath)
        return count

    def export_events_to_csv_with_names(self, filepath, finalize=True):
        """
        导出事件记录到CSV文件（包含事件名称）

        参数:
            filepath: CSV文件路径
            finalize: 是否关闭活跃事件（默认True，中间保存时应设为False）

        返回:
            int: 导出的事件数量

        【注意】中间保存时设置 finalize=False，避免关闭正在进行的事件！
        """
        if finalize:
            self.finalize_events()
        count = self.event_recorder.export_to_csv_with_names(filepath)
        return count

    def get_event_statistics(self):
        """获取事件统计信息"""
        return self.event_recorder.get_statistics()

    def print_event_summary(self):
        """打印事件统计摘要"""
        self.event_recorder.print_summary()

    # ==================================================================
    # CausalNET 因果分析数据导出
    # ==================================================================

    def export_for_causal_analysis(self, output_dir=None, finalize=True):
        """
        导出 CausalNET 因果分析所需的数据文件。

        生成文件:
            alarm.csv          — 事件序列（alarm_id, device_id, start_timestamp, end_timestamp）
            topology.npy       — 区县级邻接矩阵
            event_type_mapping.csv — alarm_id → 事件名
            device_mapping.csv     — device_id → 区县名

        参数:
            output_dir: 输出目录，默认 output_data/causal/
            finalize:   是否先关闭活跃事件
        """
        import csv as csv_mod

        if output_dir is None:
            output_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'output_data', 'causal'
            )
        os.makedirs(output_dir, exist_ok=True)

        if finalize:
            self.finalize_events()

        # ---------- 映射表 ----------
        # 保留的事件: 原event_id → alarm_id
        EVENT_ID_TO_ALARM = {
            1: 0,  # 发布应急预警
            2: 1,  # 政府分配资源给电网
            4: 2,  # 政府分配资源给居民
            5: 3,  # 实施舆情管理
            6: 4,  # 区域断电
            8: 5,  # 电网实施抢修
            9: 6,  # 区域恢复供电
            11: 7,  # 企业经营危机
            12: 8,  # 企业停工
            14: 9,  # 居民囤积物资
            15: 10,  # 居民聚集与信息传播
            17: 11,  # 居民情绪爆发
            18: 12,  # 居民自救与互助
        }

        ALARM_NAMES = {
            0: '发布应急预警',
            1: '政府分配资源给电网',
            2: '政府分配资源给居民',
            3: '实施舆情管理',
            4: '区域断电',
            5: '电网实施抢修',
            6: '区域恢复供电',
            7: '企业经营危机',
            8: '企业停工',
            9: '居民囤积物资',
            10: '居民聚集与信息传播',
            11: '居民情绪爆发',
            12: '居民自救与互助',
        }

        # 区县 → device_id（整数）
        district_list = sorted(self.district_to_zones.keys())
        district_to_device = {d: i for i, d in enumerate(district_list)}

        # ---------- 1. 构建 alarm.csv ----------
        all_events = self.event_recorder.get_all_events()

        rows = []
        for event in all_events:
            alarm_id = EVENT_ID_TO_ALARM.get(event.event_id)
            if alarm_id is None:
                continue

            # zone_id → district → device_id
            zone_id = event.zone_id
            if zone_id in district_to_device:
                device_id = district_to_device[zone_id]
            elif zone_id in self.zone_to_district:
                district = self.zone_to_district[zone_id]
                device_id = district_to_device.get(district)
                if device_id is None:
                    continue
            else:
                continue

            ts_start = int(event.start_time * 900)
            ts_end = int((event.end_time if event.end_time is not None else event.start_time) * 900)
            rows.append((alarm_id, device_id, ts_start, ts_end))

        # ---------- 电网事件去重 ----------
        # 断电/抢修/恢复 是区县级事件，同一(alarm_id, device_id, timestamp)只保留一条
        # 居民/企业/政府事件保留原始粒度（多zone触发=该区恐慌蔓延的信号）
        GRID_ALARM_IDS = {4, 5, 6}  # 断电 / 抢修 / 恢复
        grid_rows = set()
        other_rows = []
        for r in rows:
            if r[0] in GRID_ALARM_IDS:
                grid_rows.add(r)
            else:
                other_rows.append(r)
        rows = sorted(list(grid_rows) + other_rows, key=lambda r: (r[2], r[0], r[1]))

        alarm_path = os.path.join(output_dir, 'alarm.csv')
        with open(alarm_path, 'w', newline='', encoding='utf-8') as f:
            w = csv_mod.writer(f)
            w.writerow(['alarm_id', 'device_id', 'start_timestamp', 'end_timestamp'])
            w.writerows(rows)

        # ---------- 2. 构建 topology.npy ----------
        n_devices = len(district_list)
        topology = np.zeros((n_devices, n_devices), dtype=np.float64)

        for d_i, dist_i in enumerate(district_list):
            zones_i = set(self.district_to_zones.get(dist_i, []))
            for d_j, dist_j in enumerate(district_list):
                if d_i == d_j:
                    continue
                zones_j = set(self.district_to_zones.get(dist_j, []))
                connected = False
                for z_i in zones_i:
                    neighbors = self.region_manager.region_neighbors.get(z_i, [])
                    if zones_j.intersection(neighbors):
                        connected = True
                        break
                if connected:
                    topology[d_i, d_j] = 1.0
                    topology[d_j, d_i] = 1.0

        topo_path = os.path.join(output_dir, 'topology.npy')
        np.save(topo_path, topology)

        # ---------- 3. event_type_mapping.csv ----------
        map_path = os.path.join(output_dir, 'event_type_mapping.csv')
        with open(map_path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv_mod.writer(f)
            w.writerow(['alarm_id', 'event_name'])
            for aid in sorted(ALARM_NAMES.keys()):
                w.writerow([aid, ALARM_NAMES[aid]])

        # ---------- 4. device_mapping.csv ----------
        dev_path = os.path.join(output_dir, 'device_mapping.csv')
        with open(dev_path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv_mod.writer(f)
            w.writerow(['device_id', 'district_name', 'zone_count'])
            for d_name in district_list:
                d_id = district_to_device[d_name]
                z_count = len(self.district_to_zones.get(d_name, []))
                w.writerow([d_id, d_name, z_count])

        # ---------- 打印摘要 ----------
        n_types = len(set(r[0] for r in rows))
        print(f"\n{'=' * 60}")
        print(f"[CausalNET] 因果分析数据导出完成")
        print(f"{'=' * 60}")
        print(f"  事件总数: {len(rows)}")
        print(f"  事件类型: {n_types} 种 (alarm_id 0-{max(r[0] for r in rows) if rows else 0})")
        print(f"  拓扑节点: {n_devices} 个区县")
        print(f"  邻接边数: {int(topology.sum()) // 2}")
        print(f"  时间范围: {min(r[2] for r in rows) if rows else 0} ~ {max(r[2] for r in rows) if rows else 0} 秒")
        print(f"  输出目录: {output_dir}")
        print(f"  文件列表:")
        print(f"    - alarm.csv ({len(rows)} 行)")
        print(f"    - topology.npy ({n_devices}x{n_devices})")
        print(f"    - event_type_mapping.csv")
        print(f"    - device_mapping.csv")
        print(f"{'=' * 60}")

        return {
            'alarm_csv': alarm_path,
            'topology_npy': topo_path,
            'event_count': len(rows),
            'type_count': n_types,
            'device_count': n_devices,
        }