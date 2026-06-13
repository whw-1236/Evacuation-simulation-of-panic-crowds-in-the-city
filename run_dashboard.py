# -*- coding: utf-8 -*-
"""一键启动可视化仪表盘.

用法:
    python run_dashboard.py
    python run_dashboard.py --n 800 --total-steps 240 --outage-step 24
    python run_dashboard.py --city 厦门市 --district 思明区

启动后通过左侧控制面板进行交互:
    [▶ 启动]/[⏸ 暂停]/[↺ 重置]: 仿真控制
    滑块: 居民数 / 停电步 / 总步数 (重置后生效)
    单选: 1x/2x/4x 速度, full/partial 停电模式, 散点/热力图/密度/流向 图层
    勾选: "对比模式" 保留历史 run 叠加; "录制GIF" 开启帧缓存
    按钮: 导出GIF / 保存图表 / 加载历史 run
"""
import argparse
import os
import sys
import matplotlib

# Tk 后端在 Windows 上对 matplotlib widgets 兼容性最佳
try:
    matplotlib.use('TkAgg')
except Exception:
    pass


def _project_root():
    here = os.path.abspath(os.path.dirname(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    return here


def _detect_map_data_dir(root):
    """优先 simulation map data/, 回退 地图数据/。"""
    cands = [
        os.path.join(root, 'simulation map data'),
        os.path.join(root, '地图数据'),
    ]
    for c in cands:
        if os.path.isdir(c):
            return c
    return None


def _resolve_city_config(root, city=None, district=None):
    """用 CityManager 解析 GeoJSON 路径 -> city_config dict.

    返回 None 时回退到 BlackoutSimulation 的默认配置流程。
    """
    map_dir = _detect_map_data_dir(root)
    if not map_dir:
        print('[!] 未找到 simulation map data/ 或 地图数据/ 目录')
        return None
    try:
        from config.city_manager import CityManager
        cm = CityManager(map_data_dir=map_dir)
    except Exception as e:
        print(f'[!] CityManager 初始化失败: {e}')
        return None

    cities = cm.get_available_cities()
    if not cities:
        print('[!] 未发现任何城市数据')
        return None

    if city is None:
        # 默认优先厦门市，其次取首个
        city = '厦门市' if '厦门市' in cities else cities[0]
    if city not in cities:
        print(f'[!] 城市 {city} 不可用; 可用列表: {cities[:5]}…')
        city = cities[0]
    print(f'[*] 选择城市: {city}')

    geojson_paths = cm.get_geojson_paths(city, use_no_mountain=True) or []
    if district:
        geojson_paths = [p for p in geojson_paths if district in p]
        if not geojson_paths:
            print(f'[!] 区县 {district} 没有对应 GeoJSON; 改用整个城市')
            geojson_paths = cm.get_geojson_paths(city, use_no_mountain=True) or []

    if not geojson_paths:
        print(f'[!] {city} 没有可用 GeoJSON 文件')
        return None

    districts = cm.get_districts(city) or []
    return {
        'city': city,
        'geojson_paths': geojson_paths,
        'districts': [district] if district else districts,
    }


def _make_sim_factory(city_config):
    """返回 sim_factory(n_residents, total_steps) -> BlackoutSimulation"""
    _project_root()
    from simulation.simulation import BlackoutSimulation
    try:
        from config.config import Config
    except ImportError:
        Config = None

    def factory(n_residents=None, total_steps=None):
        cfg = Config() if Config is not None else None
        if cfg is not None and n_residents is not None:
            try:
                cfg.simulation.N_RESIDENTS = int(n_residents)
            except Exception:
                pass
        if cfg is not None and total_steps is not None:
            try:
                cfg.simulation.TOTAL_STEPS = int(total_steps)
            except Exception:
                pass
        return BlackoutSimulation(config=cfg, city_config=city_config)

    return factory


def main():
    parser = argparse.ArgumentParser(description='Simulation Dashboard')
    parser.add_argument('--n', '--n-residents', dest='n_residents', type=int,
                        default=1200, help='默认居民数 (滑块初始值)')
    parser.add_argument('--total-steps', dest='total_steps', type=int,
                        default=240, help='默认总步数 (滑块初始值)')
    parser.add_argument('--outage-step', dest='outage_step', type=int,
                        default=20, help='默认停电触发步 (滑块初始值)')
    parser.add_argument('--mode', dest='outage_mode',
                        default='full', choices=['full', 'partial'],
                        help='默认停电模式')
    parser.add_argument('--output-dir', dest='output_dir',
                        default='output', help='输出目录')
    parser.add_argument('--city', dest='city', default=None,
                        help='指定城市 (e.g. 厦门市); 默认自动探测')
    parser.add_argument('--district', dest='district', default=None,
                        help='可选区县 (e.g. 思明区); 不传则用全部区县')
    parser.add_argument('--trace-output', dest='trace_output', default='trace_output',
                        help='trace CSV 总目录 (每次运行在其下新建子目录)')
    parser.add_argument('--trace-every', dest='trace_every', type=int, default=25,
                        help='每多少步把 trace 写一次 CSV (节流, 默认 25)')
    parser.add_argument('--tag', dest='experiment_tag', default=None,
                        help='实验标签 (e.g. baseline, no_hysteresis); '
                             '会拼到 trace_output/run_<时间戳>_<tag>/ 末尾')
    args = parser.parse_args()

    root = _project_root()
    city_config = _resolve_city_config(root, city=args.city, district=args.district)

    from visualization.dashboard import SimulationDashboard
    factory = _make_sim_factory(city_config)

    print('[*] 启动仪表盘 …  关闭窗口或按 Ctrl+C 退出。')
    dash = SimulationDashboard(
        sim_factory=factory,
        default_n_residents=args.n_residents,
        default_outage_step=args.outage_step,
        default_total_steps=args.total_steps,
        default_outage_mode=args.outage_mode,
        output_dir=args.output_dir,
        trace_output_dir=args.trace_output,
        trace_flush_every=args.trace_every,
        experiment_tag=args.experiment_tag,
    )
    dash.show()


if __name__ == '__main__':
    main()
