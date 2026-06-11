"""
================================================================================
区域管理模块 - GeoJSON边界处理与点位管理
================================================================================
功能：
    1. 加载GeoJSON边界文件
    2. 生成备用网格（文件缺失时）
    3. 区域邻接关系计算
    4. CSV点位加载
    5. 居民点位随机生成

基于: 顾松宇-江猛-多主体11.27.py
================================================================================
"""

import json
import os
import random
import csv
from shapely.geometry import Point, shape, MultiPolygon, Polygon, box
from shapely.ops import unary_union
from shapely.prepared import prep
import numpy as np


class GeoJSONRegionManager:
    """
    GeoJSON区域管理器

    负责：
    - 加载社区GeoJSON边界文件
    - 管理区域邻接关系
    - 为Agent分配区域

    【区域ID说明】
    - 使用GeoJSON中的XZQDM字段作为区域ID（如"350203010028"）
    - 如果XZQDM不存在，则使用OBJECTID或自动生成
    - 区域名称使用XZQMC字段（如"何厝社区"）

    【输出数据】用于画图
    - regions: 区域字典 {zone_id: {...}} → 地图绘制
    - region_centroids: 区域中心点 → 标注位置
    - region_neighbors: 邻接关系 → 故障传播
    """

    def __init__(self, contour_paths=None, sub_area_paths=None, community_paths=None):
        """
        初始化区域管理器

        参数:
            contour_paths: 【废弃】轮廓文件路径列表，不再使用，保留兼容性
            sub_area_paths: 社区文件路径列表（兼容旧参数名）
            community_paths: 社区文件路径列表（新参数名，优先使用）

        抛出:
            FileNotFoundError: 文件不存在
            RuntimeError: 加载失败
            ValueError: 文件格式错误
        """
        # 优先使用community_paths，其次sub_area_paths
        self.community_paths = community_paths or sub_area_paths or []

        if not self.community_paths:
            raise ValueError("[错误] 必须提供社区文件路径（community_paths或sub_area_paths）！")

        # 保留兼容属性
        self.contour_paths = contour_paths or []
        self.sub_area_paths = self.community_paths

        # 区域数据 - 使用XZQDM作为key
        self.regions = {}  # {zone_id(XZQDM): {'name', 'geometry', 'centroid', 'bounds', 'area', ...}}
        self.region_centroids = {}  # {zone_id: centroid_point}
        self.region_neighbors = {}  # {zone_id: [neighbor_zone_ids]}

        # 区域ID映射（用于兼容旧代码）
        self.zone_id_to_name = {}  # {zone_id: zone_name}
        self.zone_name_to_id = {}  # {zone_name: zone_id}
        self.all_zone_ids = []  # 所有区域ID列表

        # 合并边界（用于验证点位）
        self.outer_boundary = None  # 合并后的外边界
        self.outer_boundaries = []  # 【兼容】保留此属性
        self.contour_names = []  # 【兼容】保留此属性

        # 地图范围
        self.bounds = (0, 0, 1, 1)  # (minx, miny, maxx, maxy)

        # GeoJSON模式标志
        self.using_fallback = False

        # 加载数据
        self._load_regions()

    def _load_regions(self):
        """加载区域数据"""

        # 验证路径
        self._validate_paths()

        # 加载社区GeoJSON
        if not self._load_community_regions():
            raise RuntimeError("[错误] 社区GeoJSON加载失败！请检查文件路径和格式。")

        # 计算邻接关系
        self._calculate_neighbors()

        # 计算地图范围
        self._calculate_bounds()

        # 创建合并边界
        self._create_merged_boundary()

        print(f"[OK] 区域加载完成: {len(self.regions)} 个社区")

    def _validate_paths(self):
        """验证社区文件路径"""
        print("\n[验证] 社区GeoJSON文件路径...")

        all_valid = True

        print("  社区文件:")
        for path in self.community_paths:
            exists = os.path.exists(path)
            status = "[OK]" if exists else "[MISSING]"
            print(f"    {status} {path}")
            if not exists:
                all_valid = False

        if not all_valid:
            raise FileNotFoundError("[错误] 部分社区GeoJSON文件不存在！请检查config/config.py中的路径配置。")

    def _load_community_regions(self):
        """加载社区GeoJSON区域文件，使用XZQDM作为区域ID"""
        print("\n[加载] 社区GeoJSON数据...")

        fallback_id_counter = 0

        for path in self.community_paths:
            try:
                file_name = os.path.splitext(os.path.basename(path))[0]

                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                feature_count = 0
                for feature in data['features']:
                    geometry = shape(feature['geometry'])
                    props = feature.get('properties', {})

                    # 【关键】使用XZQDM作为区域ID
                    zone_id = props.get('XZQDM')
                    if not zone_id:
                        # 如果没有XZQDM，尝试使用OBJECTID
                        object_id = props.get('OBJECTID')
                        if object_id:
                            zone_id = f"zone_{int(object_id)}"
                        else:
                            # 最后使用自动生成的ID
                            zone_id = f"auto_{fallback_id_counter}"
                            fallback_id_counter += 1

                    # 区域名称使用XZQMC
                    zone_name = props.get('XZQMC') or props.get('name') or f'{file_name}-{zone_id}'

                    # 保存原始GeoJSON geometry
                    original_geometry = feature.get('geometry', {})

                    self.regions[zone_id] = {
                        'zone_id': zone_id,  # 区域ID (XZQDM)
                        'name': zone_name,  # 区域名称 (XZQMC)
                        'geometry': geometry,
                        'centroid': geometry.centroid,
                        'bounds': geometry.bounds,
                        'area': geometry.area,
                        'file_name': file_name,
                        'source_file': path,  # 源文件路径（用于确定区县）
                        # 保存原始GeoJSON数据
                        'original_geometry': original_geometry,
                        'original_properties': props,
                        # 额外属性
                        'OBJECTID': props.get('OBJECTID'),
                        'KZMJ': props.get('KZMJ'),  # 控制面积
                        'JSMJ': props.get('JSMJ'),  # 建设面积
                    }

                    self.region_centroids[zone_id] = geometry.centroid
                    self.zone_id_to_name[zone_id] = zone_name
                    self.zone_name_to_id[zone_name] = zone_id
                    self.all_zone_ids.append(zone_id)
                    feature_count += 1

                print(f"    [OK] {file_name}: {feature_count} 个社区")

            except json.JSONDecodeError as e:
                raise ValueError(f"[ERROR] 无法解析GeoJSON文件 {path}: {e}")
            except Exception as e:
                raise RuntimeError(f"[ERROR] 加载社区文件失败 {path}: {e}")

        if not self.regions:
            raise RuntimeError("[ERROR] 没有成功加载任何社区！")

        print(f"  [统计] 总计加载: {len(self.regions)} 个社区")
        return True

    def _create_merged_boundary(self):
        """创建合并后的外边界（用于点位验证）"""
        all_geoms = [r['geometry'] for r in self.regions.values()]
        if all_geoms:
            self.outer_boundary = unary_union(all_geoms)
            # 【兼容】填充outer_boundaries
            self.outer_boundaries = [self.outer_boundary]
            self.contour_names = ["合并边界"]

    def _calculate_neighbors(self):
        """计算区域邻接关系（基于几何相交判断）"""
        print("  计算区域邻接关系...")
        for zone_id, region_data in self.regions.items():
            neighbors = []
            for other_id, other_data in self.regions.items():
                if zone_id != other_id:
                    if (region_data['geometry'].touches(other_data['geometry']) or
                            region_data['geometry'].intersects(other_data['geometry'])):
                        neighbors.append(other_id)
            self.region_neighbors[zone_id] = neighbors

        # 打印邻接统计
        neighbor_counts = [len(n) for n in self.region_neighbors.values()]
        if neighbor_counts:
            avg_neighbors = sum(neighbor_counts) / len(neighbor_counts)
            print(f"  邻接统计: 平均每社区 {avg_neighbors:.1f} 个邻居")

    def _calculate_bounds(self):
        """计算地图范围"""
        if not self.regions:
            self.bounds = (0, 0, 1, 1)
            return

        all_bounds = [r['bounds'] for r in self.regions.values()]
        minx = min(b[0] for b in all_bounds)
        miny = min(b[1] for b in all_bounds)
        maxx = max(b[2] for b in all_bounds)
        maxy = max(b[3] for b in all_bounds)

        # 添加边距
        margin_x = (maxx - minx) * 0.02
        margin_y = (maxy - miny) * 0.02
        self.bounds = (minx - margin_x, miny - margin_y,
                       maxx + margin_x, maxy + margin_y)

    def get_random_point_in_region(self, region_id, max_attempts=1000):
        """
        在区域内随机生成一个点

        返回:
            (x, y): 点坐标，如果失败返回区域中心点
        """
        region_data = self.regions.get(region_id)
        if not region_data:
            return 0.5, 0.5

        geometry = region_data['geometry']
        minx, miny, maxx, maxy = region_data['bounds']

        for _ in range(max_attempts):
            x = random.uniform(minx, maxx)
            y = random.uniform(miny, maxy)
            point = Point(x, y)
            if geometry.contains(point):
                return x, y

        # 回退到中心点
        return region_data['centroid'].x, region_data['centroid'].y

    def get_region_for_point(self, x, y):
        """获取点所在的区域"""
        point = Point(x, y)
        for region_id, region_data in self.regions.items():
            if region_data['geometry'].contains(point):
                return region_id
        return None

    def point_in_any_boundary(self, x, y):
        """检查点是否在合并边界内"""
        point = Point(x, y)
        if self.outer_boundary and self.outer_boundary.contains(point):
            return True
        # 【兼容】如果outer_boundary为空，检查outer_boundaries
        for boundary in self.outer_boundaries:
            if boundary.contains(point):
                return True
        return False

    def get_zone_name(self, zone_id):
        """根据区域ID获取区域名称"""
        return self.zone_id_to_name.get(zone_id, str(zone_id))

    def get_zone_id_by_name(self, zone_name):
        """根据区域名称获取区域ID"""
        return self.zone_name_to_id.get(zone_name)

    def get_all_zone_ids(self):
        """获取所有区域ID列表"""
        return self.all_zone_ids.copy()

    def get_region_panic_level(self, residents, region_id, panic_threshold=0.7):
        """
        计算区域恐慌水平

        返回:
            panic_level: 0-1之间的恐慌水平
        """
        region_residents = [r for r in residents if r.zone == region_id]
        if not region_residents:
            return 0.0

        avg_emotion = np.mean([r.emotion for r in region_residents])
        panic_ratio = sum(1 for r in region_residents if r.emotion > panic_threshold) / len(region_residents)

        return avg_emotion * 0.7 + panic_ratio * 0.3


# =============================================================================
# 各类主体属性配置 - 来自顾松宇-江猛-多主体11.27.py
# =============================================================================
class NodeAttributeConfig:
    """
    各类主体（节点）属性配置接口类

    支持的主体类型：
    - government: 政府机构
    - hospital: 医院
    - industry: 工业企业
    - emergency: 应急机构
    - school: 学校
    - community: 社区卫生院

    【功能说明】
    - 定义各类主体的可视化属性（颜色、标记、大小）
    - 定义各类主体的行为属性（可扩展）
    - 提供扩展接口，可动态添加新主体类型或属性

    【使用示例】
    config = NodeAttributeConfig()

    # 获取某类主体配置
    gov_config = config.get_category_config('government')

    # 添加新主体类型
    config.add_category(
        category='power_station',
        visual={'color': 'yellow', 'marker': 'H', 'label': '发电站', 'size': 130},
        behavior={'priority': 'high', 'backup_power': True}
    )
    """

    def __init__(self):
        # =================================================================
        # 各类主体的可视化配置（用于地图绘制）
        # =================================================================
        self.visual_config = {
            'government': {
                'color': 'darkblue',  # 颜色
                'marker': 's',  # 标记形状 (s=方块)
                'label': '政府机构',  # 图例标签
                'size': 100,  # 标记大小
                'alpha': 0.8,  # 透明度
                'edgecolor': 'black',  # 边框颜色
                'linewidth': 1.0,  # 边框线宽
            },
            'hospital': {
                'color': 'red',
                'marker': 'P',  # P=加号
                'label': '医院',
                'size': 110,
                'alpha': 0.9,
                'edgecolor': 'darkred',
                'linewidth': 1.5,
            },
            'industry': {
                'color': 'orange',
                'marker': 'D',  # D=菱形
                'label': '工业企业',
                'size': 90,
                'alpha': 0.8,
                'edgecolor': 'brown',
                'linewidth': 1.0,
            },
            'emergency': {
                'color': 'purple',
                'marker': '^',  # ^=上三角
                'label': '应急机构',
                'size': 100,
                'alpha': 0.85,
                'edgecolor': 'indigo',
                'linewidth': 1.2,
            },
            'school': {
                'color': 'green',
                'marker': '*',  # *=星形
                'label': '学校',
                'size': 120,
                'alpha': 0.8,
                'edgecolor': 'darkgreen',
                'linewidth': 1.0,
            },
            'community': {
                'color': 'cyan',
                'marker': 'o',  # o=圆形
                'label': '社区卫生院',
                'size': 80,
                'alpha': 0.8,
                'edgecolor': 'teal',
                'linewidth': 1.0,
            },
        }

        # =================================================================
        # 各类主体的行为属性配置（用于仿真逻辑）
        # =================================================================
        self.behavior_config = {
            'government': {
                'priority': 'critical',  # 优先级
                'backup_power': True,  # 是否有备用电源
                'backup_duration': 48,  # 备用电源持续时间（小时）
                'influence_radius': 0.02,  # 影响半径（经纬度）
                'resource_capacity': 100,  # 资源容量
                'response_speed': 1.2,  # 响应速度系数
            },
            'hospital': {
                'priority': 'critical',
                'backup_power': True,
                'backup_duration': 72,  # 医院备用电源更持久
                'influence_radius': 0.015,
                'patient_capacity': 500,  # 患者容量
                'emergency_level': 'high',  # 紧急程度
                'vulnerable_population': 0.3,  # 脆弱人群比例
            },
            'industry': {
                'priority': 'high',
                'backup_power': False,
                'backup_duration': 0,
                'influence_radius': 0.01,
                'economic_impact': 1.0,  # 经济影响系数
                'employee_count': 100,  # 员工数量（可按实际调整）
                'production_loss_rate': 0.1,  # 停电生产损失率（/小时）
            },
            'emergency': {
                'priority': 'critical',
                'backup_power': True,
                'backup_duration': 96,  # 应急机构备用电源最持久
                'influence_radius': 0.025,
                'response_capability': 1.5,  # 响应能力系数
                'resource_deployment': 2.0,  # 资源调配能力
            },
            'school': {
                'priority': 'medium',
                'backup_power': False,
                'backup_duration': 0,
                'influence_radius': 0.008,
                'student_count': 500,  # 学生数量
                'vulnerable_ratio': 0.8,  # 脆弱人群比例（学生）
                'evacuation_priority': 'high',  # 疏散优先级
            },
            'community': {
                'priority': 'high',
                'backup_power': True,
                'backup_duration': 24,
                'influence_radius': 0.012,
                'service_capacity': 100,  # 服务能力
                'medical_supply': 0.5,  # 医疗物资储备
            },
        }

        # =================================================================
        # 各类主体的停电影响配置
        # =================================================================
        self.outage_impact_config = {
            'government': {
                'function_loss_rate': 0.3,  # 功能损失率（有备用电源）
                'recovery_priority': 1,  # 恢复优先级（1最高）
                'public_impact': 0.8,  # 对公众影响
            },
            'hospital': {
                'function_loss_rate': 0.2,
                'recovery_priority': 1,
                'public_impact': 1.0,  # 医院影响最大
                'life_safety_risk': 0.9,  # 生命安全风险
            },
            'industry': {
                'function_loss_rate': 1.0,  # 无备用电源，完全损失
                'recovery_priority': 3,
                'public_impact': 0.4,
                'economic_loss_rate': 0.15,  # 每小时经济损失率
            },
            'emergency': {
                'function_loss_rate': 0.1,
                'recovery_priority': 1,
                'public_impact': 0.7,
            },
            'school': {
                'function_loss_rate': 0.8,
                'recovery_priority': 4,
                'public_impact': 0.5,
                'class_disruption': 1.0,  # 教学中断
            },
            'community': {
                'function_loss_rate': 0.5,
                'recovery_priority': 2,
                'public_impact': 0.6,
            },
        }

    def get_category_config(self, category):
        """获取某类主体的完整配置"""
        return {
            'visual': self.visual_config.get(category, {}),
            'behavior': self.behavior_config.get(category, {}),
            'outage_impact': self.outage_impact_config.get(category, {}),
        }

    def get_visual_config(self, category):
        """获取可视化配置"""
        return self.visual_config.get(category, {
            'color': 'gray', 'marker': 'o', 'label': category, 'size': 50
        })

    def get_behavior_config(self, category):
        """获取行为配置"""
        return self.behavior_config.get(category, {})

    def add_category(self, category, visual=None, behavior=None, outage_impact=None):
        """
        添加新的主体类型（扩展接口）

        参数:
            category: 主体类型名称
            visual: 可视化配置字典
            behavior: 行为配置字典
            outage_impact: 停电影响配置字典
        """
        if visual:
            self.visual_config[category] = visual
        if behavior:
            self.behavior_config[category] = behavior
        if outage_impact:
            self.outage_impact_config[category] = outage_impact
        print(f"[OK] 成功添加主体类型: {category}")

    def update_visual_config(self, category, **kwargs):
        """更新某类主体的可视化配置"""
        if category in self.visual_config:
            self.visual_config[category].update(kwargs)

    def update_behavior_config(self, category, **kwargs):
        """更新某类主体的行为配置"""
        if category in self.behavior_config:
            self.behavior_config[category].update(kwargs)

    def get_all_categories(self):
        """获取所有主体类型"""
        return list(self.visual_config.keys())

    def print_config_summary(self):
        """打印配置摘要"""
        print("\n📋 各类主体配置摘要：")
        for category in self.get_all_categories():
            visual = self.visual_config[category]
            behavior = self.behavior_config.get(category, {})
            print(f"  [{category}] {visual['label']}")
            print(f"    可视化: 颜色={visual['color']}, 标记={visual['marker']}, 大小={visual['size']}")
            if behavior:
                print(f"    行为: 优先级={behavior.get('priority', 'N/A')}, "
                      f"备用电源={behavior.get('backup_power', False)}")


# 全局主体属性配置实例
NODE_ATTR_CONFIG = NodeAttributeConfig()


class CSVPointLoader:
    """
    CSV点位加载器 - 加载各类设施点位

    【功能说明】
    - 读取6类CSV点位（政府/医院/工业/应急/学校/社区）
    - 验证点位是否在边界内
    - 为每个点位附加属性配置

    【输出数据】用于画图
    - csv_nodes: CSV点位列表 → 地图上的设施标记
    """

    def __init__(self, region_manager, csv_paths=None, attr_config=None):
        """
        初始化CSV加载器

        参数:
            region_manager: GeoJSONRegionManager实例
            csv_paths: CSV文件路径字典
            attr_config: NodeAttributeConfig实例
        """
        self.region_manager = region_manager
        self.csv_paths = csv_paths or {}

        # 使用属性配置
        self.attr_config = attr_config or NODE_ATTR_CONFIG

        self.csv_nodes = []  # 加载的CSV点位

        # 分类配置（从属性配置中获取）
        self.category_config = {
            cat: self.attr_config.get_visual_config(cat)
            for cat in self.attr_config.get_all_categories()
        }

    def load_all(self):
        """
        加载所有CSV点位

        支持 csv_paths 的值为单路径(str)或多路径(list[str])。
        多路径时将所有文件合并加载。
        """
        print("\n" + "=" * 60)
        print("[加载] CSV点位数据（政府/医院/工业/应急/学校/社区）")
        print("=" * 60)

        if not self.csv_paths:
            print("[WARN] 未配置CSV路径")
            return False

        out_of_bound = 0

        for category, path_or_paths in self.csv_paths.items():
            if category not in self.category_config:
                print(f"[WARN] 未知的主体类型: {category}")
                continue

            # 获取完整配置
            visual_config = self.attr_config.get_visual_config(category)
            behavior_config = self.attr_config.get_behavior_config(category)
            outage_config = self.attr_config.outage_impact_config.get(category, {})

            # 兼容单路径(str)和多路径(list)
            if isinstance(path_or_paths, str):
                paths = [path_or_paths] if path_or_paths else []
            elif isinstance(path_or_paths, list):
                paths = path_or_paths
            else:
                continue

            for path in paths:
                if not os.path.exists(path):
                    print(f"[WARN] CSV文件不存在: {path}")
                    continue

                try:
                    with open(path, 'r', encoding='utf-8-sig') as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            lon = float(row['lon'])
                            lat = float(row['lat'])

                            # 验证点位是否在边界内
                            if self.region_manager.point_in_any_boundary(lon, lat):
                                # 创建完整的节点对象，包含所有属性
                                node = {
                                    # === 基础信息 ===
                                    'id': int(row.get('id', random.randint(1000, 9999))),
                                    'name': row.get('name', f"{visual_config['label']}-{len(self.csv_nodes) + 1}"),
                                    'lon': lon,
                                    'lat': lat,
                                    'category': category,

                                    # === 可视化属性 ===
                                    'color': visual_config.get('color', 'gray'),
                                    'marker': visual_config.get('marker', 'o'),
                                    'size': visual_config.get('size', 50),
                                    'label': visual_config.get('label', category),
                                    'alpha': visual_config.get('alpha', 0.8),
                                    'edgecolor': visual_config.get('edgecolor', 'black'),
                                    'linewidth': visual_config.get('linewidth', 1.0),

                                    # === 行为属性 ===
                                    'priority': behavior_config.get('priority', 'medium'),
                                    'backup_power': behavior_config.get('backup_power', False),
                                    'backup_duration': behavior_config.get('backup_duration', 0),
                                    'influence_radius': behavior_config.get('influence_radius', 0.01),

                                    # === 停电影响属性 ===
                                    'function_loss_rate': outage_config.get('function_loss_rate', 1.0),
                                    'recovery_priority': outage_config.get('recovery_priority', 5),
                                    'public_impact': outage_config.get('public_impact', 0.5),

                                    # === 状态属性（仿真中更新） ===
                                    'powered': True,
                                    'outage_duration': 0.0,
                                    'zone': None,
                                }

                                # 附加类别特有属性
                                if category == 'hospital':
                                    node['patient_capacity'] = behavior_config.get('patient_capacity', 500)
                                    node['emergency_level'] = behavior_config.get('emergency_level', 'high')
                                    node['life_safety_risk'] = outage_config.get('life_safety_risk', 0.9)
                                elif category == 'industry':
                                    node['employee_count'] = behavior_config.get('employee_count', 100)
                                    node['production_loss_rate'] = behavior_config.get('production_loss_rate', 0.1)
                                    node['economic_loss_rate'] = outage_config.get('economic_loss_rate', 0.15)
                                elif category == 'school':
                                    node['student_count'] = behavior_config.get('student_count', 500)
                                    node['evacuation_priority'] = behavior_config.get('evacuation_priority', 'high')
                                elif category == 'government':
                                    node['resource_capacity'] = behavior_config.get('resource_capacity', 100)
                                    node['response_speed'] = behavior_config.get('response_speed', 1.2)
                                elif category == 'emergency':
                                    node['response_capability'] = behavior_config.get('response_capability', 1.5)
                                    node['resource_deployment'] = behavior_config.get('resource_deployment', 2.0)
                                elif category == 'community':
                                    node['service_capacity'] = behavior_config.get('service_capacity', 100)
                                    node['medical_supply'] = behavior_config.get('medical_supply', 0.5)

                                self.csv_nodes.append(node)
                            else:
                                out_of_bound += 1

                except Exception as e:
                    print(f"[ERROR] 读取CSV失败 {category} ({os.path.basename(path)}): {e}")

            count = len([n for n in self.csv_nodes if n['category'] == category])
            if count > 0:
                src = f"{len(paths)}个文件" if len(paths) > 1 else os.path.basename(paths[0])
                print(f"[OK] {visual_config['label']}：{count}个有效点位（来源：{src}）")

        print(f"\n[统计] CSV点位加载完成：")
        print(f"   总有效点位：{len(self.csv_nodes)} 个")
        print(f"   超出轮廓范围点位：{out_of_bound} 个（已跳过）")

        # 按分类统计
        for category in self.attr_config.get_all_categories():
            count = len([n for n in self.csv_nodes if n['category'] == category])
            if count > 0:
                config = self.category_config[category]
                print(f"   {config['label']}：{count} 个")

        return len(self.csv_nodes) > 0

    def get_nodes_by_category(self, category):
        """获取指定类别的所有节点"""
        return [n for n in self.csv_nodes if n['category'] == category]

    def get_critical_nodes(self):
        """获取关键基础设施节点（医院、应急、政府）"""
        critical_categories = ['hospital', 'emergency', 'government']
        return [n for n in self.csv_nodes if n['category'] in critical_categories]

    def update_node_power_status(self, zone_status):
        """
        根据区域供电状态更新节点供电状态

        参数:
            zone_status: {zone_id: bool} 区域供电状态
        """
        for node in self.csv_nodes:
            if node['zone'] is not None:
                node['powered'] = zone_status.get(node['zone'], True)
                if not node['powered']:
                    node['outage_duration'] += 1
                else:
                    node['outage_duration'] = 0


class ResidentDistributor:
    """
    居民分布器 - 在区域内生成随机居民

    功能：
    - 按区域面积比例分配居民
    - 生成远离边界的点位
    - 分配居民属性
    - 【新增】支持按区县（行政区）分配居民
    """

    def __init__(self, region_manager, district_to_zones=None, boundary_buffer=0.0005):
        """
        初始化居民分布器

        参数:
            region_manager: GeoJSONRegionManager实例
            district_to_zones: 区县->区域ID列表的映射 (可选)
            boundary_buffer: 远离边界的距离（经纬度）
        """
        self.region_manager = region_manager
        self.district_to_zones = district_to_zones or {}
        self.boundary_buffer = boundary_buffer

        # 预计算安全区域
        self.safe_regions = self._generate_safe_regions()

    def _generate_safe_regions(self):
        """生成每个区域的内部安全区域"""
        safe_regions = {}

        for region_id, region_data in self.region_manager.regions.items():
            try:
                safe_geom = region_data['geometry'].buffer(-self.boundary_buffer)
                if isinstance(safe_geom, (Polygon, MultiPolygon)) and safe_geom.area > 0:
                    safe_regions[region_id] = safe_geom
            except:
                pass

        return safe_regions

    def distribute_residents(self, residents):
        """
        分配居民到各区域 - 支持按区县分配

        【核心改动】
        1. 如果居民有 _target_district 属性，则只分配到该区县的区域
        2. 否则使用原有的全局分配逻辑
        3. 区域"传播指数"：影响SEIR分布
        4. 区域"脆弱指数"：影响居民属性分布

        参数:
            residents: ResidentAgent列表
        """
        if not self.region_manager.regions:
            print("[WARN] 无可用区域，无法分配居民")
            return

        # 检查是否有按区县分配的需求
        has_district_target = any(hasattr(r, '_target_district') and r._target_district
                                  for r in residents)

        if has_district_target and self.district_to_zones:
            # 按区县分配
            self._distribute_by_district(residents)
            return

        # 原有的全局分配逻辑
        region_ids = list(self.region_manager.regions.keys())
        n_regions = len(region_ids)

        # =================================================================
        # 【增强】为每个区域生成特征指数
        # =================================================================

        # 1. 传播指数（0-1）：影响SEIR分布
        # 使用更极端的分布，让差异更明显
        region_spread_index = {}
        for i, rid in enumerate(region_ids):
            # 三分之一区域高传播，三分之一低传播，三分之一中等
            if i < n_regions // 3:
                region_spread_index[rid] = random.uniform(0.7, 1.0)  # 高传播
            elif i < 2 * n_regions // 3:
                region_spread_index[rid] = random.uniform(0.0, 0.3)  # 低传播
            else:
                region_spread_index[rid] = random.uniform(0.3, 0.7)  # 中等

        # 打乱顺序，让分布随机
        spread_values = list(region_spread_index.values())
        random.shuffle(spread_values)
        region_spread_index = dict(zip(region_ids, spread_values))

        # 2. 脆弱指数（0-1）：影响居民属性分布
        # 高脆弱区域：更多老人、病人、焦虑型性格
        region_vulnerability_index = {}
        for i, rid in enumerate(region_ids):
            # 20%区域高脆弱，20%低脆弱，60%中等
            rand = random.random()
            if rand < 0.2:
                region_vulnerability_index[rid] = random.uniform(0.75, 1.0)  # 高脆弱（养老社区等）
            elif rand < 0.4:
                region_vulnerability_index[rid] = random.uniform(0.0, 0.25)  # 低脆弱（年轻社区等）
            else:
                region_vulnerability_index[rid] = random.uniform(0.25, 0.75)

        # 按SEIR状态分组居民
        seir_groups = {'S': [], 'E': [], 'I': [], 'R': []}
        for r in residents:
            state = getattr(r, 'state', 'S')
            seir_groups[state].append(r)

        # 按区域面积计算基础权重
        total_area = sum(r['area'] for r in self.region_manager.regions.values())
        if total_area <= 0:
            region_weights = {rid: 1.0 / n_regions for rid in region_ids}
        else:
            region_weights = {rid: self.region_manager.regions[rid]['area'] / total_area
                              for rid in region_ids}

        # =================================================================
        # 【增强】根据区域特征调整分配权重
        # =================================================================

        def get_adjusted_weights(seir_state, resident=None):
            """
            根据SEIR状态和居民属性计算区域分配权重

            【策略】
            - I/E状态优先分配到高传播区域
            - 脆弱人群（老人、病人、焦虑型）优先分配到高脆弱区域
            """
            weights = {}

            for rid in region_ids:
                base = region_weights[rid]
                spread_idx = region_spread_index[rid]
                vuln_idx = region_vulnerability_index[rid]

                # 1. SEIR状态影响
                if seir_state == 'I':
                    # I状态：强烈偏好高传播区域
                    seir_mult = 0.3 + spread_idx * 1.4  # [0.3, 1.7]
                elif seir_state == 'E':
                    # E状态：偏好高传播区域
                    seir_mult = 0.5 + spread_idx * 1.0  # [0.5, 1.5]
                elif seir_state == 'R':
                    # R状态：偏好低传播区域
                    seir_mult = 1.5 - spread_idx * 1.0  # [0.5, 1.5]
                else:
                    seir_mult = 1.0

                # 2. 居民属性影响（如果提供了居民对象）
                attr_mult = 1.0
                if resident is not None:
                    # 年龄影响
                    age = getattr(resident, 'age', 40)
                    if age > 65 or age < 15:
                        # 老人和儿童偏好高脆弱区域
                        attr_mult *= (0.5 + vuln_idx)
                    elif age < 35:
                        # 年轻人偏好低脆弱区域
                        attr_mult *= (1.5 - vuln_idx * 0.8)

                    # 性格影响
                    personality = getattr(resident, 'personality', '普通型')
                    if personality in ['焦虑型', '敏感型']:
                        # 焦虑/敏感型偏好高脆弱区域（物以类聚）
                        attr_mult *= (0.6 + vuln_idx * 0.8)
                    elif personality == '理性型':
                        # 理性型分布更均匀
                        attr_mult *= (1.2 - vuln_idx * 0.4)

                    # 健康状态影响
                    health = getattr(resident, 'health_status', '健康')
                    if health in ['严重疾病', '残疾']:
                        attr_mult *= (0.4 + vuln_idx * 1.2)

                weights[rid] = base * seir_mult * attr_mult

            # 归一化
            total = sum(weights.values())
            if total > 0:
                return {k: v / total for k, v in weights.items()}
            return region_weights.copy()

        # =================================================================
        # 【增强】分配居民时考虑个体属性，并传递区域特征
        # =================================================================

        def assign_resident_to_region(resident, state):
            """分配居民到区域，并设置区域特征指数"""
            adjusted_weights = get_adjusted_weights(state, resident)
            weight_list = [adjusted_weights[rid] for rid in region_ids]
            region_id = random.choices(region_ids, weights=weight_list, k=1)[0]
            x, y = self._get_safe_point(region_id)
            resident.set_position(x, y, region_id)

            # 【新增】将区域特征指数传递给居民，影响其恐慌累积速度
            resident.zone_spread_index = region_spread_index.get(region_id, 0.5)
            resident.zone_vulnerability_index = region_vulnerability_index.get(region_id, 0.5)

        # 先分配I和E（少数状态），确保它们集中在高传播区域
        for state in ['I', 'E']:
            for resident in seir_groups[state]:
                assign_resident_to_region(resident, state)

        # 再分配R（理性者），确保它们分散在低传播区域
        for resident in seir_groups['R']:
            assign_resident_to_region(resident, 'R')

        # 最后分配S（大多数），按属性聚类
        for resident in seir_groups['S']:
            assign_resident_to_region(resident, 'S')

        # 保存区域特征指数（供后续分析）
        self.region_spread_index = region_spread_index
        self.region_vulnerability_index = region_vulnerability_index

        print(f"[OK] 已分配 {len(residents)} 个居民到 {n_regions} 个区域")
        print(f"   高传播区域: {sum(1 for v in region_spread_index.values() if v > 0.6)} 个")
        print(f"   高脆弱区域: {sum(1 for v in region_vulnerability_index.values() if v > 0.6)} 个")

        # 打印各区域SEIR分布统计
        self._print_region_seir_distribution(residents, region_ids)

        # 打印居民属性统计
        self._print_resident_statistics(residents)

    def _distribute_by_district(self, residents):
        """
        按区县分配居民 - 每个居民只分配到其目标区县的区域内

        【优势】
        - 居民的邻居关系仅限于同一区县
        - 支持每个区县独立配置居民数量
        - 区县之间有清晰的边界
        """
        print("[OK] 按区县分配居民...")

        # 按目标区县分组居民
        district_residents = {}
        for r in residents:
            district = getattr(r, '_target_district', None)
            if district and district in self.district_to_zones:
                if district not in district_residents:
                    district_residents[district] = []
                district_residents[district].append(r)

        # 为每个区县分配居民
        for district, d_residents in district_residents.items():
            district_zones = self.district_to_zones.get(district, [])
            if not district_zones:
                print(f"   [WARN] {district} 无可用区域，跳过")
                continue

            # 获取该区县的区域数据
            district_region_data = {
                zid: self.region_manager.regions[zid]
                for zid in district_zones
                if zid in self.region_manager.regions
            }

            if not district_region_data:
                print(f"   [WARN] {district} 区域数据无效，跳过")
                continue

            # 按面积分配权重
            total_area = sum(r['area'] for r in district_region_data.values())
            if total_area <= 0:
                zone_weights = {zid: 1.0 / len(district_zones) for zid in district_zones}
            else:
                zone_weights = {
                    zid: district_region_data[zid]['area'] / total_area
                    for zid in district_region_data.keys()
                }

            zone_ids = list(zone_weights.keys())
            weight_list = list(zone_weights.values())

            # 分配居民到区域
            for r in d_residents:
                zone_id = random.choices(zone_ids, weights=weight_list, k=1)[0]
                x, y = self._get_safe_point(zone_id)
                r.set_position(x, y, zone_id)
                r.zone_spread_index = 0.5  # 默认中等
                r.zone_vulnerability_index = 0.5

            print(f"      - {district}: {len(d_residents)} 居民 -> {len(district_zones)} 区域")

        print(f"[OK] 共分配 {len(residents)} 居民到 {len(district_residents)} 个区县")

    def _print_region_seir_distribution(self, residents, region_ids):
        """打印各区域SEIR分布统计"""
        # 统计每个区域的SEIR分布
        region_seir = {}
        for r in residents:
            zone = getattr(r, 'zone', None)
            state = getattr(r, 'state', 'S')
            if zone not in region_seir:
                region_seir[zone] = {'S': 0, 'E': 0, 'I': 0, 'R': 0, 'total': 0}
            region_seir[zone][state] += 1
            region_seir[zone]['total'] += 1

        # 找出I比例最高和最低的区域
        i_ratios = []
        for zone, counts in region_seir.items():
            if counts['total'] > 0:
                i_ratio = counts['I'] / counts['total']
                i_ratios.append((zone, i_ratio, counts))

        if i_ratios:
            i_ratios.sort(key=lambda x: x[1], reverse=True)
            print("\n[统计] 区域SEIR分布差异（I比例从高到低前5）：")
            for zone, ratio, counts in i_ratios[:5]:
                print(
                    f"   {zone}: I={ratio * 100:.1f}% (S:{counts['S']}/E:{counts['E']}/I:{counts['I']}/R:{counts['R']})")
            if len(i_ratios) > 5:
                zone, ratio, counts = i_ratios[-1]
                print(f"   ... 最低: {zone}: I={ratio * 100:.1f}%")

    def _print_resident_statistics(self, residents):
        """打印居民属性统计信息"""
        if not residents:
            return

        print("\n[统计] 居民属性统计：")

        # 年龄统计
        ages = [getattr(r, 'age', 0) for r in residents]
        if ages:
            avg_age = sum(ages) / len(ages)
            print(f"   年龄: 平均 {avg_age:.1f} 岁, 范围 {min(ages)}-{max(ages)} 岁")

        # 健康状态统计
        health_counts = {}
        for r in residents:
            status = getattr(r, 'health_status', '未知')
            health_counts[status] = health_counts.get(status, 0) + 1
        print(f"   健康状态: {health_counts}")

        # 其他属性统计（如果存在）
        if hasattr(residents[0], 'attributes'):
            for attr_name, value in residents[0].attributes.items():
                if attr_name in ['age', 'health_status']:
                    continue  # 已统计

                if isinstance(value, (int, float)):
                    # 数值类型：统计均值
                    values = [r.attributes.get(attr_name, 0) for r in residents]
                    print(f"   {attr_name}: 平均 {sum(values) / len(values):.2f}")
                else:
                    # 选项类型：统计分布
                    counts = {}
                    for r in residents:
                        v = r.attributes.get(attr_name, '未知')
                        counts[v] = counts.get(v, 0) + 1
                    print(f"   {attr_name}: {counts}")

    # ====================================================================
    # 【POI绑定】基于真实POI点位分配居民 (替代按区域面积撒点)
    # ====================================================================
    def distribute_residents_by_poi(self, residents, csv_nodes,
                                    poi_radius=0.002,
                                    poi_weights=None):
        """
        把居民绑定到 CSV POI 点位, 在每个POI周围 poi_radius 圆内随机生成位置

        【设计意图】
        每个居民选定一个常驻活动中心(home_poi), 后续移动被限制在该中心
        附近 0.002° (~222m) 圆内 - 与 ResidentAgent._update_position 中的
        max_range 硬约束保持一致, 不需要修改 agent 移动代码。

        【兼容性】
        通过原有 set_position(x, y, zone) 接口写入位置, 自动设置 home_position;
        额外附加 home_poi / home_poi_category 字段供后续分析使用。
        zone_spread_index / zone_vulnerability_index 仍然按区域生成并赋值,
        保证下游 unified_stress_model 正常工作。

        参数:
            residents: ResidentAgent列表
            csv_nodes: CSVPointLoader.csv_nodes (调用前需已 load_all + _assign_csv_zones)
            poi_radius: 活动半径 (经纬度度), 默认 0.002 = ~222m
            poi_weights: dict {category: weight}, 各类POI承载居民的权重比例
                         默认: industry/school 高, hospital/government/emergency 低

        返回:
            True 绑定成功; False POI数据为空, 调用方应回退到 distribute_residents
        """
        if not csv_nodes:
            print("[POI绑定] csv_nodes 为空, 跳过POI绑定")
            return False

        # 默认权重: 工厂/学校承载居民最多, 政府/医院/应急较少
        if poi_weights is None:
            poi_weights = {
                'industry': 0.40,  # 工厂 (大量职工)
                'school': 0.35,  # 学校 (学生+教职工+家长)
                'hospital': 0.10,  # 医院
                'government': 0.08,  # 政府
                'emergency': 0.07,  # 应急机构
                'community': 0.05,  # 社区卫生院 (兼容6类)
            }

        # 按 category 分组 POI
        pois_by_cat = {}
        for node in csv_nodes:
            cat = node.get('category')
            if cat is None:
                continue
            pois_by_cat.setdefault(cat, []).append(node)

        # 归一化权重 (排除空类别)
        active_w = {c: w for c, w in poi_weights.items() if pois_by_cat.get(c)}
        total_w = sum(active_w.values())
        if total_w <= 0:
            print("[POI绑定] 无可用POI类别, 跳过POI绑定")
            return False
        norm_w = {c: w / total_w for c, w in active_w.items()}
        cats = list(norm_w.keys())
        cat_weights = [norm_w[c] for c in cats]

        # 生成区域特征指数 (与 distribute_residents 中的语义一致)
        # 用于影响 stress_level 累积速度, 必须为每个居民赋值
        region_ids = list(self.region_manager.regions.keys())
        n_regions = len(region_ids) if region_ids else 1
        region_spread_index = {}
        region_vulnerability_index = {}
        for i, rid in enumerate(region_ids):
            if i < n_regions // 3:
                region_spread_index[rid] = random.uniform(0.7, 1.0)
            elif i < 2 * n_regions // 3:
                region_spread_index[rid] = random.uniform(0.0, 0.3)
            else:
                region_spread_index[rid] = random.uniform(0.3, 0.7)
            rand = random.random()
            if rand < 0.2:
                region_vulnerability_index[rid] = random.uniform(0.75, 1.0)
            elif rand < 0.4:
                region_vulnerability_index[rid] = random.uniform(0.0, 0.25)
            else:
                region_vulnerability_index[rid] = random.uniform(0.25, 0.75)

        # 逐个居民绑定
        counter = {c: 0 for c in cats}
        for r in residents:
            # 1) 按权重选 POI 类别
            cat = random.choices(cats, weights=cat_weights, k=1)[0]
            # 2) 该类别内均匀选一个 POI
            poi = random.choice(pois_by_cat[cat])
            # 3) POI 圆内面积均匀采样 (sqrt 防止中心过密)
            theta = random.uniform(0, 2 * np.pi)
            rho = poi_radius * np.sqrt(random.random())
            x = poi['lon'] + rho * np.cos(theta)
            y = poi['lat'] + rho * np.sin(theta)
            # 4) 通过原有 set_position 接口写入, 保证 home_position/zone 兼容
            zone = poi.get('zone')
            r.set_position(x, y, zone)
            # 5) 附加 POI 引用 (供后续分析/可视化)
            r.home_poi = poi
            r.home_poi_category = cat
            # 6) 写入区域特征指数 (下游 unified_stress_model 会读)
            r.zone_spread_index = region_spread_index.get(zone, 0.5)
            r.zone_vulnerability_index = region_vulnerability_index.get(zone, 0.5)
            counter[cat] += 1

        # 保存区域指数 (供后续分析)
        self.region_spread_index = region_spread_index
        self.region_vulnerability_index = region_vulnerability_index

        print(f"[POI绑定] {len(residents)} 居民已绑定到 {len(cats)} 类POI:")
        for c, n in counter.items():
            n_pois = len(pois_by_cat[c])
            avg = n / n_pois if n_pois > 0 else 0
            print(f"   {c}: {n}人 / {n_pois}个POI (平均{avg:.1f}人/POI)")
        return True

    def _get_safe_point(self, region_id, max_attempts=100):
        """在安全区域内生成点位"""
        safe_geom = self.safe_regions.get(region_id)

        if safe_geom:
            minx, miny, maxx, maxy = safe_geom.bounds
            for _ in range(max_attempts):
                x = random.uniform(minx, maxx)
                y = random.uniform(miny, maxy)
                if safe_geom.contains(Point(x, y)):
                    return x, y

        # 回退到普通方法
        return self.region_manager.get_random_point_in_region(region_id)

    def distribute_enterprises(self, enterprises):
        """分配企业到各区域"""
        if not self.region_manager.regions:
            return

        region_ids = list(self.region_manager.regions.keys())

        for enterprise in enterprises:
            region_id = random.choice(region_ids)
            x, y = self.region_manager.get_random_point_in_region(region_id)
            enterprise.x = x
            enterprise.y = y
            enterprise.zone = region_id

        print(f"[OK] 已分配 {len(enterprises)} 个企业")