# -*- coding: utf-8 -*-
"""
================================================================================
避难所 (shelter) POI 加载模块
================================================================================
从 simulation map data/{城市}/{区}/{区}POI/应急.csv 加载真实避难所节点。

【格式】
    id, lon, lat, name

【过滤】
    思明区 13 个 POI 里只有 9 个是真避难所, 其余是应急管理机构。
    用 name 字段关键词过滤:
      ✅ 保留: '避难' / '避灾' / '紧急避'
      ❌ 排除: '管理局' / '指挥中心' / '管理协会'
      🟡 物资站 (含 '物资') 视情况, 默认包含 (停电时可作为应急集合点)

用法:
    from core.shelter_loader import load_shelters
    shelters = load_shelters(map_data_dir, '厦门市', '思明区')
    # → [{'id': 5, 'lon': 118.10, 'lat': 24.49, 'name': '应急避难场所'}, ...]
================================================================================
"""
import os
import csv
import glob


# 真正能作为避难所的关键词 (优先级匹配)
SHELTER_KEYWORDS = ('避难', '避灾', '紧急避')
# 排除关键词 (应急管理机构, 不是避难所)
EXCLUDE_KEYWORDS = ('管理局', '指挥中心', '管理协会')
# 边缘类 (物资站): 默认 True 视为辅助集合点
INCLUDE_MATERIAL_DEPOT = True


def _name_matches(name, keywords):
    if not name:
        return False
    return any(k in name for k in keywords)


def _classify(name):
    """返回 'shelter' / 'depot' / 'agency' / 'unknown'"""
    if not name:
        return 'unknown'
    if _name_matches(name, EXCLUDE_KEYWORDS):
        return 'agency'
    if _name_matches(name, SHELTER_KEYWORDS):
        return 'shelter'
    if '物资' in name:
        return 'depot'
    return 'unknown'


def _resolve_csv_path(map_data_dir, city, district):
    """
    应急.csv 可能位于:
      {city}/{district}/{district}POI/应急.csv     (新结构)
      {city}/{district}/应急.csv                  (旧结构)
    """
    base = os.path.join(map_data_dir, city, district)
    cands = (
        glob.glob(os.path.join(base, '*POI', '应急.csv'))
        + [os.path.join(base, '应急.csv')]
    )
    for p in cands:
        if os.path.exists(p):
            return p
    return None


def load_shelters(map_data_dir, city, district,
                  include_depot=INCLUDE_MATERIAL_DEPOT):
    """加载某区的所有真避难所。

    Args:
        map_data_dir: simulation map data 根目录
        city, district: 如 '厦门市', '思明区'
        include_depot: 是否把物资站也算作辅助避难所

    Returns:
        list[dict]: 每个 {'id', 'lon', 'lat', 'name', 'kind'}
        kind ∈ {'shelter', 'depot'}
    """
    csv_path = _resolve_csv_path(map_data_dir, city, district)
    if not csv_path:
        print(f"[shelter] 未找到 {city}{district} 的应急.csv")
        return []

    shelters = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            name = (row.get('name') or '').strip()
            kind = _classify(name)
            if kind == 'shelter' or (include_depot and kind == 'depot'):
                try:
                    shelters.append({
                        'id':   int(row['id']),
                        'lon':  float(row['lon']),
                        'lat':  float(row['lat']),
                        'name': name,
                        'kind': kind,
                    })
                except (ValueError, KeyError) as ex:
                    print(f"[shelter] 跳过损坏行 {row}: {ex}")
    n_shelter = sum(1 for s in shelters if s['kind'] == 'shelter')
    n_depot   = sum(1 for s in shelters if s['kind'] == 'depot')
    print(f"[shelter] {city}{district}: "
          f"{n_shelter} 避难所 + {n_depot} 物资站 = {len(shelters)} 节点 "
          f"(from {csv_path})")
    return shelters


# =============================================================================
# 自测
# =============================================================================
if __name__ == '__main__':
    here = os.path.abspath(os.path.dirname(__file__))
    root = os.path.dirname(here)
    map_data = os.path.join(root, 'simulation map data')
    sh = load_shelters(map_data, '厦门市', '思明区')
    print(f"\n=== {len(sh)} shelters loaded ===")
    for s in sh:
        print(f"  [{s['kind']:<8}] {s['name']} @ ({s['lon']:.4f},{s['lat']:.4f})")
