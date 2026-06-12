# -*- coding: utf-8 -*-
"""调试观察工具 (matplotlib)

仅在调试时使用，平台对接模式下不应加载此模块。
"""
from .small_area_viewer import SmallAreaViewer
from .trace_plotter import plot_traces

__all__ = ['SmallAreaViewer', 'plot_traces']
