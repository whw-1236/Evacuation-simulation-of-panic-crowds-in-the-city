# -*- coding: utf-8 -*-
"""调试观察工具 (matplotlib)

仅在调试时使用，平台对接模式下不应加载此模块。

模块导出:
    - SmallAreaViewer     轻量级实时观察器 (保留兼容)
    - SimulationDashboard 主可视化面板 (Dashboard, 2026-06-13 新增)
    - plot_traces         事后绘图 - 全局四指标 (向后兼容)
    - plot_district_traces 事后绘图 - 分区曲线
    - plot_seir_areas     事后绘图 - SEIR 堆叠面积
    - plot_comparison     事后绘图 - 多 run 对比
    - plot_overview       事后绘图 - 三联综合图
"""
from .small_area_viewer import SmallAreaViewer
from .trace_plotter import (
    plot_traces,
    plot_district_traces,
    plot_seir_areas,
    plot_comparison,
    plot_overview,
    shade_phases,
    mark_events,
)
from .dashboard import SimulationDashboard

__all__ = [
    'SmallAreaViewer',
    'SimulationDashboard',
    'plot_traces',
    'plot_district_traces',
    'plot_seir_areas',
    'plot_comparison',
    'plot_overview',
    'shade_phases',
    'mark_events',
]
