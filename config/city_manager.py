# -*- coding: utf-8 -*-
"""
================================================================================
城市数据管理模块 - 支持多城市切换
================================================================================
功能：
    1. 扫描地图数据目录，获取可用城市列表
    2. 加载指定城市的区县GeoJSON数据
    3. 随机生成关键设施位置（如无数据）

使用方法：
    from config.city_manager import CityManager

    manager = CityManager()
    cities = manager.get_available_cities()  # ['厦门市', '福州市', ...]
    districts = manager.get_districts('厦门市')  # ['思明区', '湖里区', ...]
    paths = manager.get_geojson_paths('厦门市')  # [path1, path2, ...]
================================================================================
"""

import os
import sys
import glob
import json
import random
from shapely.geometry import shape, Point


# ==================== PyInstaller 兼容路径处理 ====================
def get_base_path():
    """获取程序基础路径（兼容打包和开发环境）"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后，使用 exe 所在目录
        return os.path.dirname(sys.executable)
    else:
        # 开发环境，config 在子目录，需要回到父目录
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


CITY_MGR_BASE_PATH = get_base_path()


# ================================================================


class CityManager:
    """城市数据管理器"""

    def __init__(self, map_data_dir=None):
        """
        初始化城市管理器

        Args:
            map_data_dir: 地图数据目录，默认为项目下的"地图数据"文件夹
        """
        if map_data_dir is None:
            # 默认路径：项目目录/地图数据（使用兼容路径）
            map_data_dir = os.path.join(CITY_MGR_BASE_PATH, "地图数据")

        self.map_data_dir = map_data_dir
        self._city_cache = {}  # 缓存城市数据

    def get_available_cities(self):
        """
        获取可用城市列表

        Returns:
            list: 城市名称列表，如 ['厦门市', '福州市', '泉州市', ...]
        """
        if not os.path.exists(self.map_data_dir):
            print(f"[警告] 地图数据目录不存在: {self.map_data_dir}")
            return []

        cities = []
        for item in os.listdir(self.map_data_dir):
            item_path = os.path.join(self.map_data_dir, item)
            if os.path.isdir(item_path) and item.endswith('市'):
                cities.append(item)

        return sorted(cities)

    def get_districts(self, city_name):
        """
        获取指定城市的区县列表

        Args:
            city_name: 城市名称，如 '厦门市'

        Returns:
            list: 区县名称列表，如 ['思明区', '湖里区', ...]
        """
        city_dir = os.path.join(self.map_data_dir, city_name)
        if not os.path.exists(city_dir):
            print(f"[警告] 城市目录不存在: {city_dir}")
            return []

        districts = []
        for item in os.listdir(city_dir):
            item_path = os.path.join(city_dir, item)
            if os.path.isdir(item_path):
                districts.append(item)

        return sorted(districts)

    def get_geojson_paths(self, city_name, use_no_mountain=True):
        """
        获取指定城市所有区县的GeoJSON文件路径

        Args:
            city_name: 城市名称
            use_no_mountain: 是否优先使用"无山水"版本（去除山区河流）

        Returns:
            list: GeoJSON文件路径列表
        """
        city_dir = os.path.join(self.map_data_dir, city_name)
        if not os.path.exists(city_dir):
            return []

        paths = []
        districts = self.get_districts(city_name)

        for district in districts:
            district_dir = os.path.join(city_dir, district)

            # 优先查找"无山水"版本
            if use_no_mountain:
                # 尝试多种命名格式
                patterns = [
                    os.path.join(district_dir, f"{district}无山水.geojson"),
                    os.path.join(district_dir, f"{district}-无山水.geojson"),
                    os.path.join(district_dir, f"*无山水*.geojson"),
                ]

                found = False
                for pattern in patterns:
                    if '*' in pattern:
                        matches = glob.glob(pattern)
                        if matches:
                            paths.append(matches[0])
                            found = True
                            break
                    elif os.path.exists(pattern):
                        paths.append(pattern)
                        found = True
                        break

                if found:
                    continue

            # 回退到普通版本
            fallback_patterns = [
                os.path.join(district_dir, f"{city_name}_{district}.geojson"),
                os.path.join(district_dir, f"{district}.geojson"),
                os.path.join(district_dir, "*.geojson"),
            ]

            for pattern in fallback_patterns:
                if '*' in pattern:
                    matches = glob.glob(pattern)
                    # 排除"无山水"版本（如果不想用的话）
                    matches = [m for m in matches if '无山水' not in m]
                    if matches:
                        paths.append(matches[0])
                        break
                elif os.path.exists(pattern):
                    paths.append(pattern)
                    break

        return paths

    def get_district_geojson(self, city_name, district_name, use_no_mountain=True):
        """
        获取指定区县的GeoJSON文件路径

        Args:
            city_name: 城市名称
            district_name: 区县名称
            use_no_mountain: 是否优先使用"无山水"版本

        Returns:
            str: GeoJSON文件路径，如果不存在返回None
        """
        district_dir = os.path.join(self.map_data_dir, city_name, district_name)
        if not os.path.exists(district_dir):
            return None

        # 优先查找"无山水"版本
        if use_no_mountain:
            patterns = [
                os.path.join(district_dir, f"{district_name}无山水.geojson"),
                os.path.join(district_dir, f"{district_name}-无山水.geojson"),
            ]
            for pattern in patterns:
                if os.path.exists(pattern):
                    return pattern

            # 通配符查找
            matches = glob.glob(os.path.join(district_dir, "*无山水*.geojson"))
            if matches:
                return matches[0]

        # 回退到普通版本
        fallback_patterns = [
            os.path.join(district_dir, f"{city_name}_{district_name}.geojson"),
            os.path.join(district_dir, f"{district_name}.geojson"),
        ]
        for pattern in fallback_patterns:
            if os.path.exists(pattern):
                return pattern

        # 最后尝试通配符
        matches = glob.glob(os.path.join(district_dir, "*.geojson"))
        matches = [m for m in matches if '无山水' not in m]
        if matches:
            return matches[0]

        return None

    def load_city_data(self, city_name):
        """
        加载城市数据（包含所有区县的几何信息）

        Args:
            city_name: 城市名称

        Returns:
            dict: {
                'city': 城市名称,
                'districts': {
                    '区县名': {
                        'geometry': shapely几何对象,
                        'bounds': (minx, miny, maxx, maxy),
                        'center': (cx, cy),
                        'area': 面积
                    },
                    ...
                },
                'bounds': 整体边界,
                'center': 整体中心
            }
        """
        if city_name in self._city_cache:
            return self._city_cache[city_name]

        geojson_paths = self.get_geojson_paths(city_name)
        if not geojson_paths:
            print(f"[警告] 城市 {city_name} 没有找到GeoJSON数据")
            return None

        districts = {}
        all_bounds = [float('inf'), float('inf'), float('-inf'), float('-inf')]

        for path in geojson_paths:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # 获取区县名称
                district_name = os.path.basename(os.path.dirname(path))

                # 解析几何
                features = data.get('features', [])
                if not features:
                    continue

                # 合并所有feature的几何
                from shapely.ops import unary_union
                geometries = []
                for feature in features:
                    geom = shape(feature['geometry'])
                    geometries.append(geom)

                if geometries:
                    merged_geom = unary_union(geometries)
                    bounds = merged_geom.bounds
                    centroid = merged_geom.centroid

                    districts[district_name] = {
                        'geometry': merged_geom,
                        'bounds': bounds,
                        'center': (centroid.x, centroid.y),
                        'area': merged_geom.area,
                        'geojson_path': path
                    }

                    # 更新整体边界
                    all_bounds[0] = min(all_bounds[0], bounds[0])
                    all_bounds[1] = min(all_bounds[1], bounds[1])
                    all_bounds[2] = max(all_bounds[2], bounds[2])
                    all_bounds[3] = max(all_bounds[3], bounds[3])

            except Exception as e:
                print(f"[警告] 加载 {path} 失败: {e}")
                continue

        if not districts:
            return None

        # 计算整体中心
        center_x = (all_bounds[0] + all_bounds[2]) / 2
        center_y = (all_bounds[1] + all_bounds[3]) / 2

        city_data = {
            'city': city_name,
            'districts': districts,
            'bounds': tuple(all_bounds),
            'center': (center_x, center_y)
        }

        self._city_cache[city_name] = city_data
        return city_data

    def generate_random_facilities(self, city_name, facility_counts=None):
        """
        在城市区域内随机生成设施位置

        Args:
            city_name: 城市名称
            facility_counts: 各类设施数量，如 {'hospital': 5, 'school': 10, ...}
                            默认值会根据城市大小自动计算

        Returns:
            dict: {
                'hospital': [(x1,y1), (x2,y2), ...],
                'school': [...],
                ...
            }
        """
        city_data = self.load_city_data(city_name)
        if not city_data:
            return {}

        # 默认设施数量
        n_districts = len(city_data['districts'])
        if facility_counts is None:
            facility_counts = {
                'government': max(1, n_districts // 2),
                'hospital': max(2, n_districts),
                'school': max(3, n_districts * 2),
                'emergency': max(1, n_districts // 2),
                'community': max(2, n_districts),
                'industry': max(2, n_districts),
            }

        facilities = {}

        # 收集所有区域的几何
        all_geometries = [d['geometry'] for d in city_data['districts'].values()]

        for facility_type, count in facility_counts.items():
            points = []
            attempts = 0
            max_attempts = count * 100

            while len(points) < count and attempts < max_attempts:
                attempts += 1

                # 随机选择一个区域
                district_data = random.choice(list(city_data['districts'].values()))
                bounds = district_data['bounds']
                geom = district_data['geometry']

                # 在边界内随机生成点
                x = random.uniform(bounds[0], bounds[2])
                y = random.uniform(bounds[1], bounds[3])
                point = Point(x, y)

                # 检查点是否在区域内
                if geom.contains(point):
                    points.append((x, y))

            facilities[facility_type] = points

        return facilities

    def get_city_config(self, city_name):
        """
        获取城市配置（用于替换PathConfig）

        Args:
            city_name: 城市名称

        Returns:
            dict: 配置字典，包含路径和设施位置
        """
        city_data = self.load_city_data(city_name)
        if not city_data:
            return None

        # 获取GeoJSON路径
        geojson_paths = self.get_geojson_paths(city_name)

        # 生成随机设施
        facilities = self.generate_random_facilities(city_name)

        return {
            'city_name': city_name,
            'district_name': city_name,  # 兼容旧代码
            'geojson_paths': geojson_paths,
            'facilities': facilities,
            'bounds': city_data['bounds'],
            'center': city_data['center'],
            'districts': list(city_data['districts'].keys())
        }


# 单例实例
_city_manager = None


def get_city_manager():
    """获取城市管理器单例"""
    global _city_manager
    if _city_manager is None:
        _city_manager = CityManager()
    return _city_manager


if __name__ == '__main__':
    # 测试代码
    manager = CityManager()

    print("=" * 60)
    print("  城市数据管理器测试")
    print("=" * 60)

    # 获取可用城市
    cities = manager.get_available_cities()
    print(f"\n可用城市 ({len(cities)}个):")
    for city in cities:
        districts = manager.get_districts(city)
        print(f"  - {city}: {len(districts)}个区县")

    # 测试加载厦门市数据
    if '厦门市' in cities:
        print("\n" + "-" * 40)
        print("加载厦门市数据:")
        city_data = manager.load_city_data('厦门市')
        if city_data:
            print(f"  区县数量: {len(city_data['districts'])}")
            print(f"  整体边界: {city_data['bounds']}")
            print(f"  区县列表:")
            for name, data in city_data['districts'].items():
                print(f"    - {name}: 中心{data['center']}")

        # 测试生成随机设施
        print("\n生成随机设施:")
        facilities = manager.generate_random_facilities('厦门市')
        for ftype, points in facilities.items():
            print(f"  - {ftype}: {len(points)}个")
