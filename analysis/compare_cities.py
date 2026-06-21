# -*- coding: utf-8 -*-
"""3 城市对比：厦门思明 vs 沈阳沈河 vs 北京东城。

V3 优化:
  - polygon area (排除海域/山地, 修密度分母)
  - Gini + std + top-1% share (重尾分布扩展)
  - 加北京东城作为"纯棋盘格"对照

调用:
    cmd /c "call D:\\EnvironmentAnaconda\\Scripts\\activate.bat Crowds_sim && python _compare_cities.py"
"""
import os
import sys
import json
import time

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

import osmnx as ox
from config.city_manager import CityManager
from core.city_metrics import compute_all


# (city, district, population, polygon_query_priority_list)
CITIES = [
    ('厦门市', '思明区', 1_010_000,
        ['Siming, Xiamen, Fujian, China', '厦门市思明区']),
    ('沈阳市', '沈河区', 660_000,
        ['Shenhe, Shenyang, Liaoning, China', '沈阳市沈河区']),
    ('北京市', '东城区', 720_000,
        ['Dongcheng, Beijing, China', '北京市东城区']),
]


def _try_polygon_query(queries):
    """依次试多个 Nominatim 查询，返回第一个成功的 (query, area_km2)。"""
    from core.city_metrics import fetch_polygon_area_km2
    for q in queries:
        a = fetch_polygon_area_km2(q)
        if a is not None and a > 0:
            return q, a
    return queries[0], None


cm = CityManager()
all_metrics = {}

for city, district, pop, queries in CITIES:
    print('\n' + '=' * 76)
    print(f'  {city} {district}  (population={pop:,})')
    print('=' * 76)

    t0 = time.time()
    G = cm.load_road_graph(city, district)
    print(f'[graph] nodes={len(G.nodes)} edges={len(G.edges)} '
          f'({time.time()-t0:.1f}s)')

    # 优先 polygon area
    used_q, area = _try_polygon_query(queries)
    print(f"[polygon] used '{used_q}' -> area={area}")

    t1 = time.time()
    m = compute_all(
        G, city=city, district=district,
        population=pop, k_sample=200, plot=True,
        place_query=used_q,
        area_km2_override=area,
    )
    print(f'[metrics] {time.time()-t1:.1f}s')

    # 顺手抓沈河/东城 polygon 存到 simulation map data (思明 已有)
    if city in ('沈阳市', '北京市'):
        polygon_dir = os.path.join('simulation map data', city, district)
        os.makedirs(polygon_dir, exist_ok=True)
        polygon_path = os.path.join(polygon_dir, f'{city}_{district}.geojson')
        if not os.path.exists(polygon_path):
            try:
                gdf = ox.geocoder.geocode_to_gdf(used_q)
                gdf.to_file(polygon_path, driver='GeoJSON')
                print(f'[polygon] saved -> {polygon_path}')
            except Exception as ex:
                print(f'[polygon] WARN: {ex}')

    all_metrics[f'{city}_{district}'] = m


# ============ 三城并排对比表 ============
print('\n' + '=' * 100)
print(f"{'指标':<26} {'厦门思明区':>22} {'沈阳沈河区':>22} {'北京东城区':>22}")
print('=' * 100)

def row(label, accessor, fmt='{}'):
    cells = []
    for k, m in all_metrics.items():
        v = accessor(m)
        try:
            cells.append(fmt.format(v))
        except (ValueError, TypeError):
            cells.append(str(v))
    print(f"  {label:<24} {cells[0]:>22} {cells[1]:>22} {cells[2]:>22}")


# topology
row('节点数',          lambda m: m['topology']['n_nodes'])
row('边数',            lambda m: m['topology']['n_edges'])
row('路网总长 (km)',   lambda m: m['topology']['edge_length_total_km'], '{:.1f}')
row('面积 (km²)',      lambda m: m['topology']['area_km2'], '{:.2f}')
row('面积来源',        lambda m: m['topology']['area_source'])
row('节点密度 /km²',   lambda m: m['topology']['intersection_density_per_km2'], '{:.1f}')
row('平均路段长 (m)',  lambda m: m['topology']['street_length_avg_m'], '{:.1f}')
row('平均节点度',      lambda m: m['topology']['streets_per_node_avg'], '{:.2f}')

print('-' * 100)
row('方位熵',         lambda m: m['geometry']['orientation_entropy'], '{:.3f}')
row('方位熵 (归一化)', lambda m: m['geometry']['orientation_entropy_norm'], '{:.3f}')
row('circuity_avg',  lambda m: m['geometry']['circuity_avg'], '{:.3f}')

print('-' * 100)
row('连通分量数',    lambda m: m['evacuation']['n_components'])
row('最大组节点',    lambda m: m['evacuation']['largest_component_nodes'])
row('betweenness max',  lambda m: m['evacuation']['betweenness_max'], '{:.4f}')
row('betweenness mean', lambda m: m['evacuation']['betweenness_mean'], '{:.5f}')
row('betweenness std',  lambda m: m['evacuation']['betweenness_std'], '{:.5f}')
row('betweenness Gini', lambda m: m['evacuation']['betweenness_gini'], '{:.3f}')
row('top-1% 份额',      lambda m: m['evacuation']['betweenness_top1pct_share'], '{:.3f}')

print('-' * 100)
row('人口',          lambda m: m['coupling']['population'])
row('人均路网 m/人',  lambda m: m['coupling']['edge_length_per_capita_m'], '{:.2f}')
row('intersections/1k人', lambda m: m['coupling']['intersection_per_1k_capita'], '{:.2f}')

print('=' * 100)

# 写汇总 JSON
out = {
    'cities': [
        {'city': c, 'district': d, 'population': p}
        for (c, d, p, _) in CITIES
    ],
    'metrics': all_metrics,
}
with open('road_graph_cache/_3city_summary.json', 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2,
              default=lambda o: float(o) if hasattr(o, 'item') else str(o))
print('[summary] saved -> road_graph_cache/_3city_summary.json')
