# -*- coding: utf-8 -*-
"""
================================================================================
配置模块 - 项目所有配置参数集中管理
================================================================================
功能：
    1. 文件路径配置（GeoJSON、CSV等）
    2. 仿真参数配置
    3. 可视化参数配置
    4. 模型参数配置

使用方法：
    from config.config import Config
    config = Config()
================================================================================
"""

import os
import sys

# 项目根目录 = 论文仿真系统/
CONFIG_BASE_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PathConfig:
    """文件路径配置 - 从环境变量或runtime_control.json加载"""

    def __init__(self):
        self._project_dir = CONFIG_BASE_PATH
        self._control_file = os.path.join(self._project_dir, "runtime_control.json")

        # 尝试从控制文件读取城市配置
        city_config = self._load_city_config()

        if city_config and city_config.get("geojson_paths"):
            self.DISTRICT_NAME = city_config.get("city", "默认城市")
            self.COMMUNITY_PATHS = city_config["geojson_paths"]
            self.BASE_DIR = os.path.dirname(os.path.dirname(self.COMMUNITY_PATHS[0])) if self.COMMUNITY_PATHS else ""
            print(f"[PathConfig] 使用城市配置: {self.DISTRICT_NAME}")
        else:
            # 回退：从环境变量或默认地图数据路径读取
            default_data = os.environ.get(
                "BLACKOUT_DATA_DIR",
                os.path.join(self._project_dir, "地图数据")
            )
            self.BASE_DIR = default_data
            self.DISTRICT_NAME = os.environ.get("BLACKOUT_CITY", "默认城市")
            # 子目录由city_manager动态发现
            self.COMMUNITY_PATHS = []
            print(f"[PathConfig] 使用默认配置: {self.DISTRICT_NAME} (数据目录: {self.BASE_DIR})")

        # 【兼容旧代码】保留SUB_AREA_PATHS别名
        self.SUB_AREA_PATHS = self.COMMUNITY_PATHS

        # 【废弃】轮廓文件不再使用，设为空列表
        self.CONTOUR_PATHS = []

        # CSV点位文件路径 - 动态加载对应城市/区县的真实设施数据
        self.CSV_PATHS = self._build_csv_paths()

    def _build_csv_paths(self):
        """
        动态构建CSV路径 —— 优先从 地图数据/各地区的设施机构经纬度/ 加载真实设施数据，
        回退到旧的 BASE_DIR/各类型节点经纬度/ 路径。

        返回 dict: {category: path_or_list_of_paths}
          - 单区县时值为 str（向后兼容）
          - 多区县时值为 list[str]
        """
        csv_filename_map = {
            'government': '政府.csv',
            'hospital': '医院.csv',
            'industry': '工业.csv',
            'emergency': '应急.csv',
            'school': '学校.csv',
            'community': '社区卫生院.csv',
        }

        # 【新】优先尝试两种数据结构：
        #   旧结构: 地图数据/各地区的设施机构经纬度/{城市}/{区县}/医院.csv ...
        #   新结构: 地图数据/{城市}/{区县}/医院.csv ...
        candidate_bases = [
            os.path.join(self._project_dir, "地图数据", "各地区的设施机构经纬度"),
            os.path.join(self._project_dir, "地图数据"),
        ]
        collected = {cat: [] for cat in csv_filename_map}

        city_districts = self._extract_city_districts()
        for facility_base in candidate_bases:
            if not os.path.exists(facility_base):
                continue
            for city, district in city_districts:
                district_csv_dir = os.path.join(facility_base, city, district)
                if not os.path.exists(district_csv_dir):
                    continue
                for category, filename in csv_filename_map.items():
                    csv_file = os.path.join(district_csv_dir, filename)
                    if os.path.exists(csv_file) and csv_file not in collected[category]:
                        collected[category].append(csv_file)
            # 一旦从某个 base 找到了文件就停止 (避免重复)
            if any(collected[cat] for cat in collected):
                break

        found_any = any(collected[cat] for cat in collected)

        if found_any:
            result = {}
            for cat, paths in collected.items():
                if not paths:
                    continue
                result[cat] = paths[0] if len(paths) == 1 else paths
            if result:
                total = sum(len(v) if isinstance(v, list) else 1 for v in result.values())
                print(f"[PathConfig] 从 各地区的设施机构经纬度 加载CSV: {total} 个文件")
            return result

        # 回退到旧路径
        if os.path.exists(self.BASE_DIR):
            old_dir = os.path.join(self.BASE_DIR, "各类型节点经纬度")
            if os.path.exists(old_dir):
                result = {}
                for category, filename in csv_filename_map.items():
                    old_path = os.path.join(old_dir, filename)
                    if os.path.exists(old_path):
                        result[category] = old_path
                if result:
                    print(f"[PathConfig] 从旧路径加载CSV: {len(result)} 个文件")
                return result

        print("[PathConfig] 未找到CSV设施数据")
        return {}

    def _extract_city_districts(self):
        """从 COMMUNITY_PATHS 中提取 (城市, 区县) 列表"""
        city_districts = []
        seen = set()

        for path in self.COMMUNITY_PATHS:
            parts = path.replace('\\', '/').split('/')
            if '地图数据' in parts:
                idx = parts.index('地图数据')
                if len(parts) > idx + 2:
                    city = parts[idx + 1]
                    district = parts[idx + 2]
                    if city == '各地区的设施机构经纬度':
                        continue
                    key = (city, district)
                    if key not in seen:
                        seen.add(key)
                        city_districts.append(key)

        if not city_districts:
            facility_base = os.path.join(self._project_dir, "地图数据", "各地区的设施机构经纬度")
            if os.path.exists(facility_base) and hasattr(self, 'DISTRICT_NAME'):
                for city_dir in os.listdir(facility_base):
                    city_path = os.path.join(facility_base, city_dir)
                    if not os.path.isdir(city_path):
                        continue
                    for district_dir in os.listdir(city_path):
                        if self.DISTRICT_NAME == district_dir:
                            city_districts.append((city_dir, district_dir))

        return city_districts

    def _load_city_config(self):
        """从控制文件加载城市配置"""
        try:
            if os.path.exists(self._control_file):
                import json
                with open(self._control_file, 'r', encoding='utf-8') as f:
                    control = json.load(f)
                    city_config = control.get("城市配置", {})

                    # 智能路径处理：如果原始路径不存在，尝试在程序目录下查找
                    if city_config and city_config.get("geojson_paths"):
                        fixed_paths = []
                        for path in city_config["geojson_paths"]:
                            if os.path.exists(path):
                                # 原始路径存在，直接使用
                                fixed_paths.append(path)
                            else:
                                # 尝试从路径中提取城市和区县名，在本地查找
                                # 路径格式: .../地图数据/城市名/区县名/xxx.geojson
                                path_parts = path.replace('\\', '/').split('/')
                                if '地图数据' in path_parts:
                                    idx = path_parts.index('地图数据')
                                    # 构建相对路径
                                    relative_parts = path_parts[idx:]
                                    local_path = os.path.join(self._project_dir, *relative_parts)
                                    if os.path.exists(local_path):
                                        print(f"[PathConfig] 路径重定向: {os.path.basename(path)} -> 本地")
                                        fixed_paths.append(local_path)
                                    else:
                                        # 尝试匹配文件名（可能文件名格式不同）
                                        found = self._find_geojson_by_district(path_parts, idx)
                                        if found:
                                            fixed_paths.append(found)
                                        else:
                                            print(f"[PathConfig] ⚠️ 找不到: {path}")
                                else:
                                    print(f"[PathConfig] ⚠️ 无法解析路径: {path}")

                        if fixed_paths:
                            city_config["geojson_paths"] = fixed_paths

                    return city_config
        except Exception as e:
            print(f"[PathConfig] 加载城市配置失败: {e}")
        return None

    def _find_geojson_by_district(self, path_parts, map_data_idx):
        """根据城市和区县名在本地地图数据文件夹中查找geojson文件"""
        try:
            # 获取城市和区县名
            if len(path_parts) > map_data_idx + 2:
                city = path_parts[map_data_idx + 1]
                district = path_parts[map_data_idx + 2]

                # 在本地地图数据文件夹中查找
                local_map_dir = os.path.join(self._project_dir, "地图数据", city, district)
                if os.path.exists(local_map_dir):
                    # 查找无山水版本的geojson
                    for f in os.listdir(local_map_dir):
                        if f.endswith('.geojson') and '无山水' in f:
                            return os.path.join(local_map_dir, f)
                    # 如果没有无山水版本，返回任意geojson
                    for f in os.listdir(local_map_dir):
                        if f.endswith('.geojson'):
                            return os.path.join(local_map_dir, f)
        except Exception as e:
            pass
        return None


class SimulationConfig:
    """仿真参数配置"""

    # ==================== 时间参数 ====================
    # 【重要】每步代表现实世界15分钟
    TOTAL_STEPS = 1000  # 总仿真步数（1000步 × 0.25小时 = 250小时 ≈ 10.4天）
    DT = 0.25  # 每步时间间隔（小时），0.25 = 15分钟

    # 时间换算参考：
    # - 1小时 = 4步
    # - 1天 = 96步
    # - 3天 = 288步
    # - 7天 = 672步
    # - 14天 = 1344步

    # ==================== Agent数量参数 ====================
    N_RESIDENTS = 1000  # 居民数量（建议>=1000，确保每区域10+人以体现差异）
    N_ENTERPRISES = 10  # 企业数量
    N_HOSPITALS = 1  # 医院数量
    N_PUMPS = 1  # 泵站数量

    # ==================== SEIR初始比例 ====================
    SEIR_RATIOS = {
        'S': 0.7,  # 易感者（未知者）
        'E': 0.1,  # 潜伏者
        'I': 0.1,  # 传播者（分享者）
        'R': 0.1,  # 抵制者
    }

    # ==================== 应急响应参数 ====================
    EMERGENCY_RESPONSE_DELAY = 5  # 应急响应延迟步数（前N步禁止恢复）
    INITIAL_OUTAGE_RATIO = 0.5  # 初始停电区域比例（50%）


class AgentConfig:
    """Agent参数配置"""

    # ==================== 政府Agent参数 ====================
    GOV_INITIATIVE = 0.5  # 政府积极性（0-1）【可调参数】
    GOV_RESPONSE = 1.0  # 政府响应效率（0.1-2.0）【可调参数】
    GOV_RESOURCE_CAPACITY = 100.0  # 政府资源储备

    # ==================== 电网Agent参数 ====================
    GRID_INITIATIVE = 0.5  # 电网积极性（0-1）【可调参数】
    GRID_RESPONSE = 1.0  # 电网响应效率（0.1-2.0）【可调参数】
    GRID_RESTORE_RATE = 4  # 恢复速率
    GRID_LAMBDA_PROP = 0.1  # 故障传播率（0-1）【可调参数】

    # ==================== 企业Agent参数 ====================
    ENTERPRISE_INITIATIVE = 0.5  # 企业积极性（0-1）【可调参数】
    ENTERPRISE_RESPONSE = 1.0  # 企业响应效率（0.1-2.0）【可调参数】

    # ==================== 居民Agent参数 ====================
    RESIDENT_ALPHA = 0.1  # 情绪增长系数
    RESIDENT_BETA = 0.15  # 情绪传播系数
    RESIDENT_DELTA = 0.02  # 积极性调整步长


class SocialForceConfig:
    """
    社会力模型参数配置 - 完整版

    基于论文: 人群力分析复现.py

    力的组成：
    1. 驱动力 f_i^0 = m * (v_0 * e - v) / tau
    2. 社会心理力 f_ij^soc = A * exp((r_ij - d_ij) / B) * n_ij
    3. 身体接触力 f_ij^ph = K * Θ * n_ij + k * Θ * Δv_t * t_ij
    """

    # ==================== 社会心理力参数（公式4） ====================
    A = 2000.0  # 社会心理力强度 [N]
    B = 0.08  # 社会心理力作用范围 [m]

    # ==================== 驱动力参数（公式1） ====================
    TAU = 0.5  # 适应时间 [s]

    # ==================== 身体接触力参数（公式7） ====================
    K = 1.2e5  # 身体压力常数 [kg/s^2]
    k = 2.4e5  # 滑动摩擦常数 [kg/(m·s)]

    # ==================== 各向异性参数 ====================
    # 影响前方/后方行人对自己的影响权重
    LAMBDA_VAL = 0.5  # 各向异性系数 (0~1), 越小后方影响越小

    # ==================== 运动参数（大幅增大使移动非常明显） ====================
    MAX_SPEED = 0.002  # 最大移动速度（经纬度/步）约200米/步【可调】
    DESIRED_SPEED = 0.001  # 期望移动速度（经纬度/步）约100米/步【可调】
    INTERACTION_RADIUS = 0.003  # 相互作用范围（经纬度，约300米）

    # ==================== 情绪传播参数 ====================
    ATTRACTION_STRENGTH = 0.1  # 情绪吸引力强度
    REPULSION_STRENGTH = 0.3  # 情绪排斥力强度
    EMOTION_INFLUENCE_RADIUS = 0.002  # 情绪影响半径（经纬度）
    PANIC_THRESHOLD = 0.7  # 恐慌阈值


class PanicConfig:
    """
    恐慌传播模型参数配置 - 完整版

    基于论文: 恐慌模拟复现.py

    核心公式：
    恐慌值 P = D * [(1 - exp(-α*l_c)) / (1 + exp(α*l_o)) + A_ij] * exp(-β*t)

    其中：
    - l_c: 到安全区/出口的距离
    - l_o: 到危险源的距离
    - A_ij: 周围PTS行人的恐慌传播项
    - D: 全局恐慌控制系数【关键参数】
    """

    # ==================== 核心恐慌参数 ====================
    D = 3  # 全局恐慌控制系数【关键可调参数】
    # D=0: 无恐慌效应
    # D=1-3: 正常恐慌
    # D>5: 强烈恐慌
    ALPHA = 0.05  # 距离-恐慌敏感系数
    BETA = 0.001  # 时间衰减系数（恐慌随时间缓解）

    # ==================== PTS状态参数 ====================
    PTS_THRESHOLD = 0.8  # PTS恐慌阈值（恐慌值>此值进入PTS状态）
    PANIC_TRANSMISSION_RADIUS = 0.002  # 恐慌传播半径（经纬度，约200米）
    N_P = 4.4835  # 归一化因子

    # ==================== 动态敏感系数（公式9-11） ====================
    # 恐慌值越高 → k_h增加（本能反应增强）
    # 恐慌值越低 → k_s增加（理性因素增强）
    K_SIN = 0.6  # 静态场初始敏感系数（理性因素）
    K_HIN = 0.4  # 危险场初始敏感系数（本能反应）
    A_SENSITIVITY = 0.5  # 动态敏感调节参数


class FaultConfig:
    """故障系统参数配置"""

    # ==================== 故障严重程度 ====================
    SEVERITY_TYPES = {
        'simple': {
            'detection_delay': 0.5,  # 发现延迟（小时）
            'repair_multiplier': 1.0,  # 修复难度倍数
            'probability': 0.6,  # 发生概率【可调参数】
        },
        'complex': {
            'detection_delay': 2.0,
            'repair_multiplier': 3.0,
            'probability': 0.3,  # 【可调参数】
        },
        'disaster': {
            'detection_delay': 4.0,
            'repair_multiplier': 8.0,
            'probability': 0.1,  # 【可调参数】自动计算
        },
    }


class LoadPriorityConfig:
    """
    负荷等级配置 - 按重要程度分级

    负荷等级说明：
    - 一级负荷 (LEVEL_1): 最重要，优先保障供电，最后切负荷
      如：医院、应急机构、政府机关
    - 二级负荷 (LEVEL_2): 重要，次优先保障
      如：学校、社区卫生院、大型企业
    - 三级负荷 (LEVEL_3): 一般负荷，可优先切除
      如：普通居民区、小型企业、商业设施

    【切负荷逻辑】
    外部输入切负荷比例 → 依次从三级→二级→一级切除
    如果三级不够就切二级，二级不够切一级

    【电网修复逻辑】
    修的是大电网，修复能力由资源量+积极程度+响应效率计算
    修好后所有区域恢复供电
    """

    # 负荷等级定义
    LEVEL_1 = 1  # 一级负荷（最重要）
    LEVEL_2 = 2  # 二级负荷
    LEVEL_3 = 3  # 三级负荷（可优先切除）

    # 各类设施的默认负荷等级
    FACILITY_LOAD_LEVELS = {
        'hospital': LEVEL_1,  # 医院 - 一级负荷
        'emergency': LEVEL_1,  # 应急机构 - 一级负荷
        'government': LEVEL_1,  # 政府机关 - 一级负荷
        'school': LEVEL_2,  # 学校 - 二级负荷
        'community': LEVEL_2,  # 社区卫生院 - 二级负荷
        'industry': LEVEL_2,  # 工业企业 - 二级负荷（大型）
        'enterprise': LEVEL_3,  # 普通企业 - 三级负荷
        'resident': LEVEL_3,  # 居民区 - 三级负荷
    }

    # 各等级负荷的权重（用于计算切负荷比例）
    # 假设三级负荷数量最多，但单位负荷小；一级负荷少但单位负荷大
    LOAD_WEIGHTS = {
        LEVEL_1: 3.0,  # 一级负荷单位权重（关键设施）
        LEVEL_2: 2.0,  # 二级负荷单位权重
        LEVEL_3: 1.0,  # 三级负荷单位权重（居民/小企业）
    }

    # 停电原因及对应参数
    #
    # 【修复时间计算】（假设标准修复能力≈2.5单位/小时）
    # 总工作量 = base_damage × 1.0 + repair_difficulty × 30.0
    # 修复时间(小时) = 总工作量 / 修复能力
    #
    # 【各场景修复时间】
    # - 过载: 20×1 + 0.2×30 = 26 → 约10小时
    # - 设备故障: 50×1 + 0.5×30 = 65 → 约1天
    # - 外力破坏: 70×1 + 1.5×30 = 115 → 约2天
    # - 自然灾害: 90×1 + 3.0×30 = 180 → 约3天
    # - 台风: 85×1 + 5.0×30 = 235 → 约4天
    # - 导弹: 95×1 + 12.0×30 = 455 → 约8天
    # - 战争: 100×1 + 25.0×30 = 850 → 约14天
    #
    OUTAGE_CAUSES = {
        'equipment_failure': {  # 设备故障
            'name': '设备故障',
            'base_damage': 50,  # 基础损坏程度 (0-100)
            'repair_difficulty': 0.5,  # 修复难度系数 ← 调低
            'detection_delay': 0.5,  # 发现延迟（小时）
            'estimated_repair_days': '12-24小时',
        },
        'overload': {  # 过载跳闸
            'name': '过载跳闸',
            'base_damage': 20,  # 损坏程度较低
            'repair_difficulty': 0.2,  # 修复较快 ← 调低
            'detection_delay': 0.25,  # 15分钟发现
            'estimated_repair_days': '4-8小时',
        },
        'external_damage': {  # 外力破坏
            'name': '外力破坏',
            'base_damage': 70,  # 损坏程度较高
            'repair_difficulty': 1.5,  # 修复较慢
            'detection_delay': 1.0,
            'estimated_repair_days': '1-2天',
        },
        'natural_disaster': {  # 自然灾害（通用）
            'name': '自然灾害',
            'base_damage': 90,  # 损坏程度最高
            'repair_difficulty': 3.0,  # 修复最慢
            'detection_delay': 0.5,
            'estimated_repair_days': '2-4天',
        },
        'typhoon': {  # 【台风过境】
            'name': '台风过境',
            'base_damage': 85,  # 大面积线路损坏
            'repair_difficulty': 5.0,  # 需要等台风过境+大量线路修复 ← 调整
            'detection_delay': 2.0,  # 台风期间难以排查
            'description': '台风导致大电网线路损坏，需等待台风过境后修复',
            'estimated_repair_days': '3-7天',
        },
        'missile_attack': {  # 【导弹袭击】
            'name': '导弹袭击',
            'base_damage': 95,  # 圆形区域大面积损坏
            'repair_difficulty': 12.0,  # 设备损毁严重，需更换 ← 大幅调高
            'detection_delay': 0.25,  # 立即发现
            'description': '导弹导致圆形区域大电网设备损毁，需更换设备',
            'estimated_repair_days': '7-14天',
        },
        'war_damage': {  # 【战争破坏】（最严重）
            'name': '战争破坏',
            'base_damage': 100,  # 完全损毁
            'repair_difficulty': 25.0,  # 极难修复 ← 大幅调高
            'detection_delay': 0.5,
            'description': '大规模战争破坏，基础设施严重损毁',
            'estimated_repair_days': '14-30天',
        },
        'planned_outage': {  # 计划停电
            'name': '计划停电',
            'base_damage': 0,  # 无损坏
            'repair_difficulty': 0.0,  # 无需修复
            'detection_delay': 0.0,
            'estimated_repair_days': '无需修复',
        },
    }


class GridRepairConfig:
    """
    电网修复配置 - 大电网修复能力计算

    【修复能力计算公式】
    修复能力 = 基础修复能力 × 资源效率 × 积极程度系数 × 响应效率系数

    【修复进度计算公式】
    每步修复量 = 修复能力 × DT
    修复进度 = 累计修复量 / 总工作量
    修复完成条件：修复进度 >= 1.0

    【时间换算】（DT=0.25小时=15分钟）
    - 1小时 = 4步
    - 1天 = 96步

    【修复时间示例】（假设标准修复能力≈2.5单位/小时）
    - 过载: 工作量≈26 → 约10小时
    - 设备故障: 工作量≈65 → 约1天
    - 外力破坏: 工作量≈115 → 约2天
    - 自然灾害: 工作量≈180 → 约3天
    - 台风: 工作量≈235 → 约4天
    - 导弹: 工作量≈455 → 约8天
    - 战争破坏: 工作量≈850 → 约14天

    注：实际修复时间会因资源、积极性、响应效率而变化
    """

    # 基础参数
    # 【重要调整】大幅降低基础修复能力，使大灾害需要更长修复时间
    BASE_REPAIR_CAPACITY = 1.5  # 基础修复能力（单位/小时）← 从5.0降到1.5

    # 资源效率计算参数
    RESOURCE_EFFICIENCY_BASE = 0.3  # 资源效率基础值
    RESOURCE_EFFICIENCY_MAX = 1.2  # 资源效率最大值（资源充足时可加速）
    RESOURCE_HALF_POINT = 80.0  # 资源量达到一半效率的点

    # 积极程度影响
    INITIATIVE_MULTIPLIER = 1.5  # 积极程度的影响倍数
    INITIATIVE_BASE = 0.5  # 积极程度的基础加成

    # 响应效率影响
    RESPONSE_MULTIPLIER = 1.2  # 响应效率的影响倍数
    RESPONSE_BASE = 0.4  # 响应效率的基础加成

    # 损坏程度对修复工作量的影响
    # 总工作量 = damage × DAMAGE_WORK_MULTIPLIER + difficulty × DIFFICULTY_WORK_MULTIPLIER
    DAMAGE_WORK_MULTIPLIER = 1.0  # 损坏程度转换为工作量的系数
    DIFFICULTY_WORK_MULTIPLIER = 30.0  # 修复难度转换为工作量的系数（调高）

    # 并行修复限制
    MAX_CONCURRENT_REPAIRS_BASE = 2  # 基础并行修复数
    MAX_CONCURRENT_REPAIRS_MAX = 8  # 最大并行修复数


class Config:
    """
    统一配置类 - 聚合所有配置

    使用方法：
        config = Config()
        print(config.simulation.TOTAL_STEPS)  # 访问仿真配置
        print(config.paths.CONTOUR_PATHS)     # 访问路径配置

    【行为参数】
        通过 config.behavior.xxx 访问各主体行为参数
        这些参数是外部可调的"旋钮"，控制仿真行为
    """

    def __init__(self):
        self.paths = PathConfig()
        self.simulation = SimulationConfig()
        self.agent = AgentConfig()
        self.social_force = SocialForceConfig()
        self.panic = PanicConfig()
        self.fault = FaultConfig()
        self.load_priority = LoadPriorityConfig()
        self.grid_repair = GridRepairConfig()

        # 导入行为配置
        try:
            from .behavior_config import (
                GovernmentBehaviorConfig,
                GridBehaviorConfig,
                EnterpriseBehaviorConfig,
                ResidentBehaviorConfig
            )
            self.gov_behavior = GovernmentBehaviorConfig()
            self.grid_behavior = GridBehaviorConfig()
            self.enterprise_behavior = EnterpriseBehaviorConfig()
            self.resident_behavior = ResidentBehaviorConfig()
        except ImportError:
            pass  # 兼容旧代码

    def validate_paths(self):
        """验证所有路径是否存在"""
        missing_files = []

        # 检查社区文件（主要数据来源）
        for path in self.paths.COMMUNITY_PATHS:
            if not os.path.exists(path):
                missing_files.append(path)

        if missing_files:
            print("⚠️ 以下社区文件不存在：")
            for f in missing_files[:5]:  # 只显示前5个
                print(f"   - {f}")
            return False
        return True


# ================================================================================
# 可调参数汇总（用于UI滑块）
# ================================================================================
"""
【用于UI滑块的可调参数】

1. 政府参数：
   - GOV_INITIATIVE: 政府积极性 (0-1)
   - GOV_RESPONSE: 政府响应效率 (0.1-2.0)

2. 电网参数：
   - GRID_INITIATIVE: 电网积极性 (0-1)
   - GRID_RESPONSE: 电网响应效率 (0.1-2.0)
   - GRID_LAMBDA_PROP: 故障传播率 (0-1)

3. 企业参数：
   - ENTERPRISE_INITIATIVE: 企业积极性 (0-1)
   - ENTERPRISE_RESPONSE: 企业响应效率 (0.1-2.0)

4. 人口与SEIR：
   - N_RESIDENTS: 居民总数 (50-500)
   - SEIR_RATIOS['S']: S-未知者比例 (0-1)
   - SEIR_RATIOS['E']: E-潜伏者比例 (0-1)
   - SEIR_RATIOS['I']: I-分享者比例 (0-1)
   - SEIR_RATIOS['R']: R-抵制者比例 (自动计算)

5. 故障参数：
   - simple/complex/disaster概率 (总和=1)

6. 恐慌参数：
   - D: 全局恐慌系数 (0-10)
"""

