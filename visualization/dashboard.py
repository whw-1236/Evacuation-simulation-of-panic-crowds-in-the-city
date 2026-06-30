# -*- coding: utf-8 -*-
"""
==============================================================================
仿真可视化面板 (SimulationDashboard) — 2026-06-13
==============================================================================
对应《仿真可视化面板-修改大纲.md》第 1~7 项优化点：

  1. 多 Run 对比                  -> 历史曲线虚线 + 加载 step_history.json
  2. 热力图/密度图/流向箭头        -> RadioButton 图层切换
  3. 按区县分解指标                -> 三选项卡 (全局 / 分区 / SEIR)
  4. 散点堆叠遮挡                  -> alpha + rasterized, 大规模自动降点大小
  5. 动画导出 GIF                  -> [导出GIF] 按钮 (PillowWriter)
  6. 事后图增强                    -> 通过 visualization.trace_plotter 调用
  7. 空间可视化增强                -> 流向箭头 + 密度等高线 + 设施六类着色

外挂式调用：
    - 仅通过 sim.step() / sim.residents / sim.zone_status / sim.region_manager
      等公开接口工作；不修改任何 core / simulation / config。
==============================================================================
"""
from __future__ import annotations

import os
import csv
import json
import time
import math
import datetime
from collections import defaultdict
from typing import Callable, Optional

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from matplotlib.widgets import Button, Slider, RadioButtons, CheckButtons
from matplotlib.patches import Polygon as MplPolygon, Patch
from matplotlib.collections import PatchCollection

try:
    from scipy.ndimage import gaussian_filter as _gaussian_filter
except ImportError:
    _gaussian_filter = None

plt.rcParams['font.family'] = ['Microsoft YaHei', 'SimHei', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

# =============================================================================
# 颜色 / 形状方案 — 对照《属性说明.md》
# =============================================================================
EMOTION_LEVELS = [
    (0.2, '#4CAF50', '平静'),
    (0.4, '#FFC107', '轻度焦虑'),
    (0.6, '#FF9800', '中度焦虑'),
    (1.01, '#F44336', '高度恐慌'),
]
PTS_EDGE_COLOR = '#9C27B0'
SEIR_MARKERS = {'S': 'o', 'E': 's', 'I': '^', 'R': 'D'}

FACILITY_COLORS = {
    'hospital':   '#E91E63',
    'school':     '#8BC34A',
    'industry':   '#FF9800',
    'emergency':  '#673AB7',
    'government': '#1565C0',
}
FACILITY_OUTAGE_COLOR = '#757575'
FACILITY_LABELS_CN = {
    'hospital': '医院', 'school': '学校', 'industry': '工业',
    'emergency': '应急', 'government': '政府',
}

# 状态栏使用 monospace 字体（Windows 下 Consolas），不含 CJK 字形；
# 把 RadioButton 的中文 layer 名映射成英文 key 仅供状态栏显示。
LAYER_LABEL_TO_KEY = {
    '散点': 'scatter',
    '热力图': 'heatmap',
    '密度': 'density',
    '流向箭头': 'quiver',
}

ZONE_FILL_POWERED = '#81C784'
ZONE_FILL_OUTAGE  = '#E57373'

PHASE_FILL = {
    'baseline': '#E8F5E9',
    'outage':   '#FFEBEE',
    'recovery': '#E3F2FD',
}


# =============================================================================
# 工具函数
# =============================================================================
def _emotion_color(stress: float) -> str:
    for thr, c, _ in EMOTION_LEVELS:
        if stress < thr:
            return c
    return EMOTION_LEVELS[-1][1]


def _safe_zone_geom(region):
    """返回 region geom 的 exterior coords 列表 (Polygon / MultiPolygon)。"""
    try:
        from shapely.geometry import Polygon, MultiPolygon
    except ImportError:
        return []
    geom = region.get('geometry') if isinstance(region, dict) else getattr(region, 'geometry', None)
    if geom is None:
        return []
    out = []
    if isinstance(geom, MultiPolygon):
        for sub in geom.geoms:
            out.append(np.array(sub.exterior.coords))
    elif isinstance(geom, Polygon):
        out.append(np.array(geom.exterior.coords))
    return out


def _build_zone_patches(region_manager):
    patches, zids = [], []
    for zid, data in region_manager.regions.items():
        for arr in _safe_zone_geom(data):
            patches.append(MplPolygon(arr))
            zids.append(zid)
    return patches, zids


# =============================================================================
# Dashboard
# =============================================================================
class SimulationDashboard:
    """主可视化面板。

    使用：
        dash = SimulationDashboard(sim_factory=make_sim,
                                   default_outage_step=20,
                                   default_total_steps=240)
        dash.show()  # 阻塞，直到面板关闭
    """

    DEFAULT_FIGSIZE = (16, 9)

    def __init__(self,
                 sim_factory: Callable,
                 default_n_residents: int = 1200,
                 default_outage_step: int = 20,
                 default_total_steps: int = 240,
                 default_outage_mode: str = 'full',
                 default_speed: int = 1,
                 output_dir: str = 'output',
                 trace_output_dir: str = 'trace_output',
                 trace_flush_every: int = 25,
                 experiment_tag: Optional[str] = None,
                 figsize=DEFAULT_FIGSIZE,
                 ):
        """
        Args:
            sim_factory(n_residents, total_steps) -> BlackoutSimulation
            output_dir:        图表/动画输出目录
            trace_output_dir:  每步数据 CSV 总目录；每次重置/启动新仿真都会在其下
                               新建 run_YYYYMMDD_HHMMSS[_tag]/ 子目录，避免覆盖。
            trace_flush_every: 每多少步把 history 写一次 CSV (节流)
            experiment_tag:    可选实验标签 (e.g. "baseline", "no_hysteresis")，
                               会拼接到 run 子目录名末尾，方便筛选。
        """
        self.sim_factory = sim_factory
        self.default_n = default_n_residents
        self.default_outage_step = default_outage_step
        self.default_total_steps = default_total_steps
        self.default_outage_mode = default_outage_mode
        self.default_speed = default_speed
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        # ===== Trace 自动存档 =====
        self.trace_output_root = trace_output_dir
        self.trace_flush_every = max(1, int(trace_flush_every))
        self.experiment_tag = experiment_tag or ''
        os.makedirs(self.trace_output_root, exist_ok=True)
        self.trace_run_dir = None         # 由 _create_sim 时填充
        self._trace_last_flushed_step = -1
        self._trace_known_districts = []  # 缓存列名顺序，避免每次 flush 重排

        # ===== Run 序号 (output_N / trace_output_N 共用) =====
        # 每次 _create_sim 时通过扫盘取 max(N)+1 分配；output_run_dir
        # 在首次按"保存图表"/"导出 GIF"时才 lazily mkdir，避免空目录污染。
        self.current_run_index = None
        self.output_run_dir = None

        # --- 运行状态 ---
        self.sim = None
        self.running = False
        self.exited = False
        self.speed = default_speed
        self.outage_step = default_outage_step
        self.total_steps = default_total_steps
        self.outage_mode = default_outage_mode
        self.outage_triggered = False

        # --- 数据 ---
        self.history = self._empty_history()
        self.district_history = {}   # dict[district_name -> history-dict]
        self.seir_history = {'step': [], 'S': [], 'E': [], 'I': [], 'R': []}
        self.previous_runs = []   # list of dict(name, history, district_history, seir_history)
        self.compare_mode = False
        self.events = []          # list of {'step', 'label', 'color'}

        # --- 图层模式 ---
        self.layer_mode = '散点'

        # --- 帧缓存（用于 GIF）---
        self.frame_cache = []
        self.frame_dir = None
        self.recording_gif = False

        # --- 构建图形 ---
        self.fig = plt.figure(figsize=figsize)
        self.fig.canvas.manager.set_window_title('城市大停电人群行为动态仿真系统')
        self._build_layout()
        self._build_controls()
        self._build_map_axes()
        self._build_metric_axes()
        self._build_status_bar()
        self._refresh_after_init()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_layout(self):
        # 用 36 列细粒度网格，3 大块（控件 / 地图 / 三联指标）之间留出 hspace/wspace
        gs = GridSpec(21, 36, figure=self.fig,
                      left=0.025, right=0.99, top=0.965, bottom=0.045,
                      wspace=1.0, hspace=2.2)
        # 控制面板 (左侧 6 列，作为占位背景；具体控件用 add_axes 精确摆放)
        self.ax_control = self.fig.add_subplot(gs[0:18, 0:6]); self.ax_control.axis('off')
        # 地图视图 (中间 14 列；空 1 列做缓冲)
        self.ax_map = self.fig.add_subplot(gs[0:18, 7:21])
        # 指标面板 (右侧 14 列；空 1 列做缓冲；纵向分 3 段，每段 5 行 + 1 行间距)
        self.ax_metric0 = self.fig.add_subplot(gs[0:5,   22:36])
        self.ax_metric1 = self.fig.add_subplot(gs[6:11,  22:36])
        self.ax_metric2 = self.fig.add_subplot(gs[12:17, 22:36])
        # 状态栏（底部）
        self.ax_status = self.fig.add_subplot(gs[18:21, 0:36]); self.ax_status.axis('off')

    # ------------------------------------------------------------------
    # Controls
    # ------------------------------------------------------------------
    def _build_controls(self):
        """精细摆放所有交互控件。

        统一向左收紧到 x ∈ [0.020, 0.165] 范围内，滑块右侧的数字也不会超过
        x=0.18 —— 即不会延伸到地图视图 (x≥0.21) 之上。
        """
        self._control_widgets = {}
        # 设计参数
        X0 = 0.020     # 控件区左边
        XW = 0.135     # 控件区宽度（含滑块数字）
        SW = 0.090     # 滑块本体宽度
        SX = X0 + 0.020  # 滑块左边 (留 label 空间)

        # ---- 按钮：启动 / 暂停 / 重置 (顶部, y=0.92) ----
        bx_w = 0.040
        bx_gap = 0.005
        ax_btn_start = self.fig.add_axes([X0,                       0.920, bx_w, 0.035])
        ax_btn_pause = self.fig.add_axes([X0 + bx_w + bx_gap,       0.920, bx_w, 0.035])
        ax_btn_reset = self.fig.add_axes([X0 + 2*(bx_w + bx_gap),   0.920, bx_w, 0.035])
        self.btn_start = Button(ax_btn_start, '▶ 启动', color='#A5D6A7', hovercolor='#81C784')
        self.btn_pause = Button(ax_btn_pause, '⏸ 暂停', color='#FFE082', hovercolor='#FFCA28')
        self.btn_reset = Button(ax_btn_reset, '↺ 重置', color='#EF9A9A', hovercolor='#E57373')
        self.btn_start.on_clicked(self._on_start)
        self.btn_pause.on_clicked(self._on_pause)
        self.btn_reset.on_clicked(self._on_reset)

        # ---- 三个滑块 (居民数 / 停电步 / 总步数) ----
        # 留 label 在左，数字在右；都不延伸超过 X0+XW
        ax_sld_n = self.fig.add_axes([SX, 0.870, SW, 0.018])
        self.sld_n = Slider(ax_sld_n, '居民数', 100, 5000,
                            valinit=self.default_n, valstep=100, valfmt='%d')

        ax_sld_outage = self.fig.add_axes([SX, 0.835, SW, 0.018])
        self.sld_outage = Slider(ax_sld_outage, '停电步', 0, self.default_total_steps,
                                 valinit=self.default_outage_step, valstep=1, valfmt='%d')

        ax_sld_total = self.fig.add_axes([SX, 0.800, SW, 0.018])
        self.sld_total = Slider(ax_sld_total, '总步数', 60, 960,
                                valinit=self.default_total_steps, valstep=30, valfmt='%d')

        # 减小滑块字号，避免数字溢出
        for sld in (self.sld_n, self.sld_outage, self.sld_total):
            sld.label.set_fontsize(8)
            sld.valtext.set_fontsize(8)

        # ---- 速度 / 模式 (并排, 两个 RadioButtons) ----
        rb_w = 0.062
        ax_radio_speed = self.fig.add_axes([X0,             0.700, rb_w, 0.070])
        ax_radio_mode  = self.fig.add_axes([X0 + rb_w + 0.010, 0.700, rb_w, 0.070])
        self.radio_speed = RadioButtons(ax_radio_speed, ('1x', '2x', '4x'), active=0)
        self.radio_mode  = RadioButtons(ax_radio_mode,  ('full', 'partial'),
                                        active=0 if self.outage_mode == 'full' else 1)
        for rb in (self.radio_speed, self.radio_mode):
            for lbl in rb.labels:
                lbl.set_fontsize(8)
        self.radio_speed.on_clicked(self._on_speed_change)
        self.radio_mode.on_clicked(self._on_mode_change)

        # ---- 图层切换 ----
        ax_radio_layer = self.fig.add_axes([X0, 0.560, XW, 0.110])
        self.radio_layer = RadioButtons(ax_radio_layer,
                                        ('散点', '热力图', '密度', '流向箭头'),
                                        active=0)
        for lbl in self.radio_layer.labels:
            lbl.set_fontsize(8)
        self.radio_layer.on_clicked(self._on_layer_change)

        # ---- 对比模式 / 录制 GIF ----
        ax_chk = self.fig.add_axes([X0, 0.490, XW, 0.060])
        self.chk = CheckButtons(ax_chk, ('对比模式', '录制GIF'), (False, False))
        for lbl in self.chk.labels:
            lbl.set_fontsize(8)
        self.chk.on_clicked(self._on_check_change)

        # ---- 导出 GIF / 保存图表 (并排) ----
        half_w = (XW - 0.008) / 2
        ax_btn_export = self.fig.add_axes([X0,                  0.440, half_w, 0.032])
        ax_btn_save   = self.fig.add_axes([X0 + half_w + 0.008, 0.440, half_w, 0.032])
        self.btn_export_gif = Button(ax_btn_export, '导出GIF', color='#FFCDD2')
        self.btn_save       = Button(ax_btn_save,   '保存图表', color='#B3E5FC')
        self.btn_export_gif.on_clicked(self._on_export_gif)
        self.btn_save.on_clicked(self._on_save_charts)

        # ---- 加载历史 run ----
        ax_btn_load = self.fig.add_axes([X0, 0.398, XW, 0.032])
        self.btn_load = Button(ax_btn_load, '+加载历史 run', color='#E1BEE7')
        self.btn_load.on_clicked(self._on_load_history)

        # ---- trace 实验标签输入框（用按钮提示，实际通过命令行参数设置）----
        # 显示当前 trace 目录
        ax_info = self.fig.add_axes([X0, 0.330, XW, 0.060]); ax_info.axis('off')
        self._trace_info_text = ax_info.text(
            0.0, 0.95, '',
            transform=ax_info.transAxes,
            fontsize=7, family='monospace',
            verticalalignment='top',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='#FFF9C4',
                      edgecolor='#FBC02D', alpha=0.7),
        )

    # ------------------------------------------------------------------
    # Map axes
    # ------------------------------------------------------------------
    def _build_map_axes(self):
        ax = self.ax_map
        ax.set_aspect('equal')
        ax.set_xlabel('经度')
        ax.set_ylabel('纬度')
        ax.set_title('地图视图（散点 · 情绪色 + SEIR 形状 + PTS 紫描边）',
                     fontsize=11, fontweight='bold')

        # 散点占位：按 SEIR 状态分组（一组用一种 marker，颜色逐点设置）
        self._scatter_by_state = {}
        for state in 'SEIR':
            sc = ax.scatter([], [], c=[], s=8, alpha=0.55,
                            marker=SEIR_MARKERS[state],
                            label=f'SEIR-{state}',
                            edgecolors='none', rasterized=True)
            self._scatter_by_state[state] = sc

        # PTS 描边 collection
        self._pts_scatter = ax.scatter([], [], facecolors='none',
                                       edgecolors=PTS_EDGE_COLOR,
                                       s=40, linewidths=1.2, alpha=0.8,
                                       label='PTS')

        # 区域多边形
        self._zone_collection = None
        self._zone_patch_ids = []

        # 设施散点 (一类一 collection)
        self._facility_scatters = {}

        # 热力图占位
        self._heatmap_im = None
        self._density_contour = None
        self._quiver = None

        # 图例文本框
        self._step_text = ax.text(
            0.02, 0.98, '', transform=ax.transAxes,
            fontsize=10, verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='white', alpha=0.85)
        )

    # ------------------------------------------------------------------
    # Metric axes
    # ------------------------------------------------------------------
    def _build_metric_axes(self):
        # 全局四指标
        ax = self.ax_metric0
        ax.set_title('全局四指标', fontsize=10, fontweight='bold')
        ax.set_ylim(0, 1)
        ax.grid(True, alpha=0.3)
        self._line_stress, = ax.plot([], [], '-', color='#F44336', label='avg_stress', linewidth=1.5)
        self._line_emotion, = ax.plot([], [], '-', color='#FFC107', label='avg_emotion', linewidth=1.5)
        self._line_panic, = ax.plot([], [], '-', color='#9C27B0', label='avg_panic', linewidth=1.5)
        self._line_outage, = ax.plot([], [], '-', color='#2196F3', label='outage_ratio', linewidth=1.5)
        ax.legend(loc='upper right', fontsize=8, framealpha=0.7, ncol=2)
        self._prev_overlay_lines_global = []

        # 分区指标
        ax1 = self.ax_metric1
        ax1.set_title('分区平均压力（按区县）', fontsize=10, fontweight='bold')
        ax1.set_ylim(0, 1)
        ax1.grid(True, alpha=0.3)
        self._district_lines = {}     # district -> Line2D

        # SEIR
        ax2 = self.ax_metric2
        ax2.set_title('SEIR 比例 + 事件', fontsize=10, fontweight='bold')
        ax2.set_ylim(0, 1)
        self._seir_stack = None

    def _build_status_bar(self):
        self._status_text = self.ax_status.text(
            0.01, 0.5,
            'Step=0/?? | t=0.0h | Stress=0.000 | Outage=0%',
            fontsize=11, family='monospace',
            transform=self.ax_status.transAxes,
            verticalalignment='center',
            bbox=dict(boxstyle='round', facecolor='#FAFAFA', edgecolor='#BDBDBD'),
        )

    # ------------------------------------------------------------------
    # 初始化与重置
    # ------------------------------------------------------------------
    @staticmethod
    def _empty_history():
        return {
            'step': [], 'avg_stress': [], 'avg_emotion': [],
            'avg_panic': [], 'outage_ratio': [],
            'hoard_ratio': [], 'herd_ratio': [],
        }

    def _refresh_after_init(self):
        """构造一个仿真实例并把地图准备好。"""
        self._create_sim()
        self._draw_zone_patches()
        self._draw_facilities_static()
        self._auto_zoom_map()

    def _create_sim(self):
        n = int(self.sld_n.val) if hasattr(self, 'sld_n') else self.default_n
        total = int(self.sld_total.val) if hasattr(self, 'sld_total') else self.default_total_steps
        try:
            self.sim = self.sim_factory(n_residents=n, total_steps=total)
        except TypeError:
            # 兼容仅接受默认参数的 factory
            self.sim = self.sim_factory()
        self.total_steps = total
        self.outage_step = int(self.sld_outage.val) if hasattr(self, 'sld_outage') else self.default_outage_step
        self.outage_triggered = False
        self.history = self._empty_history()
        self.district_history = {
            d: self._empty_history()
            for d in getattr(self.sim, 'district_to_zones', {}).keys()
        }
        self.seir_history = {'step': [], 'S': [], 'E': [], 'I': [], 'R': []}
        self.events = []
        self._reset_frame_cache()

        # ===== 新建 trace_output 子目录 =====
        self._init_trace_run_dir()
        self._trace_last_flushed_step = -1
        self._trace_known_districts = list(self.district_history.keys())
        self._write_trace_meta()
        self._update_trace_info_text()

    # ------------------------------------------------------------------
    # Run index 分配 + 目录管理
    # ------------------------------------------------------------------
    @staticmethod
    def _scan_max_index(parent_dir: str, prefix: str) -> int:
        """扫描 parent_dir 下形如 prefix_<N>/ 的子目录，返回最大 N（无则 0）。"""
        if not os.path.isdir(parent_dir):
            return 0
        max_n = 0
        for name in os.listdir(parent_dir):
            if not name.startswith(prefix + '_'):
                continue
            full = os.path.join(parent_dir, name)
            if not os.path.isdir(full):
                continue
            tail = name[len(prefix) + 1:]
            if tail.isdigit():
                max_n = max(max_n, int(tail))
        return max_n

    def _allocate_run_index(self) -> int:
        """两边目录的 max(N) + 1，保证 trace_output_N / output_N 永远同步。"""
        n_trace = self._scan_max_index(self.trace_output_root, 'trace_output')
        n_output = self._scan_max_index(self.output_dir, 'output')
        return max(n_trace, n_output) + 1

    # ------------------------------------------------------------------
    # Trace output：每次运行新建独立子目录，自动存档
    # ------------------------------------------------------------------
    def _init_trace_run_dir(self):
        """新建 trace_output/trace_output_<N>/，N 取两边目录最大序号+1。

        output/output_<N>/ 不在这里创建——等首次按"保存图表"/"导出GIF"
        时再 lazily mkdir，避免空目录污染。
        """
        n = self._allocate_run_index()
        self.current_run_index = n
        candidate = os.path.join(self.trace_output_root, f'trace_output_{n}')
        # 极端情况（并发）撞名：自增到不撞为止
        while os.path.exists(candidate):
            n += 1
            candidate = os.path.join(self.trace_output_root, f'trace_output_{n}')
        os.makedirs(candidate, exist_ok=True)
        self.current_run_index = n
        self.trace_run_dir = candidate
        self.output_run_dir = None  # output_N 留到首次保存才建
        print(f'[Dashboard] Run #{n} → trace: {self.trace_run_dir}')

    def _ensure_output_run_dir(self) -> str:
        """首次需要写 output 时建 output/output_<N>/ 并返回路径。"""
        if self.output_run_dir and os.path.isdir(self.output_run_dir):
            return self.output_run_dir
        n = self.current_run_index or self._allocate_run_index()
        path = os.path.join(self.output_dir, f'output_{n}')
        os.makedirs(path, exist_ok=True)
        self.output_run_dir = path
        print(f'[Dashboard] Run #{n} → output: {path}')
        return path

    def _update_trace_info_text(self):
        if hasattr(self, '_trace_info_text') and self.trace_run_dir:
            short = os.path.relpath(self.trace_run_dir)
            tag_suffix = f' [{self.experiment_tag}]' if self.experiment_tag else ''
            self._trace_info_text.set_text(
                f'run #{self.current_run_index}{tag_suffix}\n'
                f'trace → {short}\n(每 {self.trace_flush_every} 步自动写盘)'
            )

    def _write_trace_meta(self):
        if not self.trace_run_dir:
            return
        meta = {
            'run_index': self.current_run_index,
            'run_dir': self.trace_run_dir,
            'created_at': datetime.datetime.now().isoformat(timespec='seconds'),
            'experiment_tag': self.experiment_tag,
            'n_residents': len(self.sim.residents) if self.sim else None,
            'total_steps': self.total_steps,
            'outage_step': self.outage_step,
            'outage_mode': self.outage_mode,
            'dt': getattr(self.sim, 'dt', None),
            'city': getattr(self.sim, 'district_name', None),
            'districts': self._trace_known_districts,
            'n_zones': len(getattr(self.sim, 'zone_status', {})),
        }
        try:
            with open(os.path.join(self.trace_run_dir, 'meta.json'), 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f'[Dashboard] meta.json 写入失败: {e}')

    def _flush_traces(self, force: bool = False):
        """把 self.history / district_history / seir_history 写到 CSV。

        节流：仅当离上次写盘已经过去 trace_flush_every 步以上才写（除非 force）。
        每个文件会从 0 步重写一次（保证数据一致），文件较小所以代价可接受。
        """
        if not self.trace_run_dir or not self.history.get('step'):
            return
        last_step = self.history['step'][-1]
        if not force and (last_step - self._trace_last_flushed_step) < self.trace_flush_every:
            return
        self._trace_last_flushed_step = last_step

        # ---- 全局四指标 + 行为分量 ----
        global_path = os.path.join(self.trace_run_dir, 'global_metrics.csv')
        try:
            with open(global_path, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(['step', 't_hour', 'avg_stress', 'avg_emotion',
                            'avg_panic', 'outage_ratio', 'hoard_ratio',
                            'herd_ratio',
                            # 【M3 T14】路网层指标
                            'avg_edge_congestion', 'pct_on_path',
                            'max_edge_occupancy'])
                dt = float(getattr(self.sim, 'dt', 0.25))
                steps = self.history['step']
                avg_cong = self.history.get('avg_edge_congestion', [])
                pct_path = self.history.get('pct_on_path', [])
                max_occ = self.history.get('max_edge_occupancy', [])
                for i, s in enumerate(steps):
                    w.writerow([
                        s, round(s * dt, 4),
                        round(self.history['avg_stress'][i], 6),
                        round(self.history['avg_emotion'][i], 6),
                        round(self.history['avg_panic'][i], 6),
                        round(self.history['outage_ratio'][i], 6),
                        round(self.history['hoard_ratio'][i], 6),
                        round(self.history['herd_ratio'][i], 6),
                        round(avg_cong[i], 6) if i < len(avg_cong) else 0.0,
                        round(pct_path[i], 6) if i < len(pct_path) else 0.0,
                        round(max_occ[i], 3) if i < len(max_occ) else 0.0,
                    ])
        except Exception as e:
            print(f'[Dashboard] global_metrics.csv 写入失败: {e}')

        # ---- 分区指标：4 张表，分别记录 stress/emotion/panic/outage ----
        districts = self._trace_known_districts or list(self.district_history.keys())
        for metric, fname in (
            ('avg_stress',   'district_stress.csv'),
            ('avg_emotion',  'district_emotion.csv'),
            ('avg_panic',    'district_panic.csv'),
            ('outage_ratio', 'district_outage.csv'),
        ):
            path = os.path.join(self.trace_run_dir, fname)
            try:
                with open(path, 'w', newline='', encoding='utf-8') as f:
                    w = csv.writer(f)
                    w.writerow(['step', 't_hour'] + districts)
                    dt = float(getattr(self.sim, 'dt', 0.25))
                    # 用全局 steps 作为时间轴；分区可能比全局少几步
                    for i, s in enumerate(self.history['step']):
                        row = [s, round(s * dt, 4)]
                        for d in districts:
                            h = self.district_history.get(d)
                            if h and i < len(h.get(metric, [])):
                                row.append(round(h[metric][i], 6))
                            else:
                                row.append('')
                        w.writerow(row)
            except Exception as e:
                print(f'[Dashboard] {fname} 写入失败: {e}')

        # ---- SEIR ----
        seir_path = os.path.join(self.trace_run_dir, 'seir.csv')
        try:
            with open(seir_path, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(['step', 't_hour', 'S', 'E', 'I', 'R'])
                dt = float(getattr(self.sim, 'dt', 0.25))
                for i, s in enumerate(self.seir_history.get('step', [])):
                    w.writerow([
                        s, round(s * dt, 4),
                        self.seir_history['S'][i],
                        self.seir_history['E'][i],
                        self.seir_history['I'][i],
                        self.seir_history['R'][i],
                    ])
        except Exception as e:
            print(f'[Dashboard] seir.csv 写入失败: {e}')

        # ---- 【M3 T14】edge_observations（仅当 use_road_graph）----
        try:
            if getattr(self.sim, 'use_road_graph', False):
                edge_path = os.path.join(self.trace_run_dir, 'edge_observations.csv')
                self.sim.write_edge_observations(edge_path)
        except Exception as e:
            print(f'[Dashboard] edge_observations.csv 写入失败: {e}')

        # ---- 事件 ----
        events_path = os.path.join(self.trace_run_dir, 'events.csv')
        try:
            with open(events_path, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(['step', 't_hour', 'label', 'kind', 'color'])
                dt = float(getattr(self.sim, 'dt', 0.25))
                for ev in self.events:
                    w.writerow([
                        ev.get('step'),
                        round(ev.get('step', 0) * dt, 4),
                        ev.get('label', ''),
                        ev.get('kind', ''),
                        ev.get('color', ''),
                    ])
        except Exception as e:
            print(f'[Dashboard] events.csv 写入失败: {e}')

    def _draw_zone_patches(self):
        if self._zone_collection is not None:
            try:
                self._zone_collection.remove()
            except Exception:
                pass
        patches, zids = _build_zone_patches(self.sim.region_manager)
        self._zone_patch_ids = zids
        self._zone_collection = PatchCollection(
            patches, edgecolor='#9E9E9E', linewidth=0.4, alpha=0.5,
        )
        self._zone_collection.set_facecolors([ZONE_FILL_POWERED] * len(patches))
        self.ax_map.add_collection(self._zone_collection)

    def _draw_facilities_static(self):
        # 移除旧的
        for sc in self._facility_scatters.values():
            try:
                sc.remove()
            except Exception:
                pass
        self._facility_scatters = {}
        infras = getattr(self.sim, 'critical_infras', None) or []
        groups = defaultdict(list)
        for f in infras:
            ftype = getattr(f, 'infra_type', None) or getattr(f, 'category', 'other')
            groups[ftype].append(f)
        for ftype, items in groups.items():
            xs = [getattr(it, 'x', None) for it in items]
            ys = [getattr(it, 'y', None) for it in items]
            xs = [x for x in xs if x is not None]
            ys = [y for y in ys if y is not None]
            color = FACILITY_COLORS.get(ftype, '#9E9E9E')
            sc = self.ax_map.scatter(xs, ys, marker='D', s=40,
                                     facecolor=color, edgecolor='black',
                                     linewidths=0.4, alpha=0.85,
                                     label=FACILITY_LABELS_CN.get(ftype, ftype))
            self._facility_scatters[ftype] = sc

    def _auto_zoom_map(self):
        xs = [r.x for r in self.sim.residents]
        ys = [r.y for r in self.sim.residents]
        if not xs:
            return
        pad_x = (max(xs) - min(xs)) * 0.06 + 0.001
        pad_y = (max(ys) - min(ys)) * 0.06 + 0.001
        self.ax_map.set_xlim(min(xs) - pad_x, max(xs) + pad_x)
        self.ax_map.set_ylim(min(ys) - pad_y, max(ys) + pad_y)

    # ------------------------------------------------------------------
    # 渲染（按图层）
    # ------------------------------------------------------------------
    def _clear_overlay_layers(self):
        if self._heatmap_im is not None:
            try:
                self._heatmap_im.remove()
            except Exception:
                pass
            self._heatmap_im = None
        if self._density_contour is not None:
            # matplotlib >=3.8: QuadContourSet.remove() 直接生效
            # matplotlib <3.8 : 退回到逐 collection 移除
            try:
                self._density_contour.remove()
            except (AttributeError, NotImplementedError):
                try:
                    for c in self._density_contour.collections:
                        c.remove()
                except Exception:
                    pass
            except Exception:
                pass
            self._density_contour = None
        if self._quiver is not None:
            try:
                self._quiver.remove()
            except Exception:
                pass
            self._quiver = None

    def _hide_scatter_layers(self):
        for sc in self._scatter_by_state.values():
            sc.set_visible(False)
        self._pts_scatter.set_visible(False)

    def _show_scatter_layers(self):
        for sc in self._scatter_by_state.values():
            sc.set_visible(True)
        self._pts_scatter.set_visible(True)

    def _render_layer(self):
        self._clear_overlay_layers()
        mode = self.layer_mode
        if mode == '散点':
            self._show_scatter_layers()
            self._render_scatter()
        elif mode == '热力图':
            self._hide_scatter_layers()
            self._render_heatmap()
        elif mode == '密度':
            self._show_scatter_layers()
            self._render_density_contour()
        elif mode == '流向箭头':
            self._show_scatter_layers()
            self._render_quiver()

    def _render_scatter(self):
        residents = self.sim.residents
        n = len(residents)
        if n == 0:
            return
        # 大规模自动降低点大小
        size = max(3, int(60 - 50 * min(1.0, n / 5000)))

        # 一次性向量化抽取所有需要的字段
        xs = np.fromiter((r.x for r in residents), dtype=np.float64, count=n)
        ys = np.fromiter((r.y for r in residents), dtype=np.float64, count=n)
        stress = np.fromiter(
            (getattr(r, 'stress_level', 0.0) for r in residents), dtype=np.float64, count=n)
        states = np.array([getattr(r, 'state', 'S') for r in residents])
        pts_mask = np.fromiter(
            (1 if getattr(r, 'pts_status', False) else 0 for r in residents), dtype=bool, count=n)

        # 用 stress 阈值一次性算颜色索引（4 级配色）
        thresholds = np.array([lv[0] for lv in EMOTION_LEVELS], dtype=np.float64)
        colors_pool = [lv[1] for lv in EMOTION_LEVELS]
        color_idx = np.searchsorted(thresholds, stress, side='right')
        color_idx = np.clip(color_idx, 0, len(colors_pool) - 1)
        color_arr = np.array(colors_pool, dtype=object)[color_idx]

        coords = np.column_stack([xs, ys])
        for st, sc in self._scatter_by_state.items():
            mask = states == st
            if mask.any():
                sc.set_offsets(coords[mask])
                sc.set_color(color_arr[mask].tolist())
                sc.set_sizes(np.full(int(mask.sum()), size))
            else:
                sc.set_offsets(np.empty((0, 2)))

        if pts_mask.any():
            self._pts_scatter.set_offsets(coords[pts_mask])
            self._pts_scatter.set_sizes(np.full(int(pts_mask.sum()), size * 4))
        else:
            self._pts_scatter.set_offsets(np.empty((0, 2)))

    def _render_heatmap(self):
        residents = self.sim.residents
        if not residents:
            return
        xs = np.array([r.x for r in residents])
        ys = np.array([r.y for r in residents])
        xlim = self.ax_map.get_xlim(); ylim = self.ax_map.get_ylim()
        H, xedges, yedges = np.histogram2d(
            xs, ys, bins=(60, 60),
            range=[[xlim[0], xlim[1]], [ylim[0], ylim[1]]],
        )
        # 用 stress 权重热度（人均压力越高越红）
        try:
            stress = np.array([getattr(r, 'stress_level', 0.0) for r in residents])
            Hs, _, _ = np.histogram2d(
                xs, ys, bins=(60, 60),
                range=[[xlim[0], xlim[1]], [ylim[0], ylim[1]]],
                weights=stress,
            )
            density = np.where(H > 0, Hs / np.maximum(H, 1), 0)
            display = 0.6 * (H / max(H.max(), 1)) + 0.4 * density
        except Exception:
            display = H / max(H.max(), 1)
        self._heatmap_im = self.ax_map.imshow(
            display.T, origin='lower', extent=[xlim[0], xlim[1], ylim[0], ylim[1]],
            cmap='hot', alpha=0.7, aspect='auto', interpolation='bilinear', zorder=1,
        )

    def _render_density_contour(self):
        residents = self.sim.residents
        if len(residents) < 30:
            return
        xs = np.array([r.x for r in residents])
        ys = np.array([r.y for r in residents])
        xlim = self.ax_map.get_xlim(); ylim = self.ax_map.get_ylim()
        H, xedges, yedges = np.histogram2d(
            xs, ys, bins=(40, 40),
            range=[[xlim[0], xlim[1]], [ylim[0], ylim[1]]],
        )
        # 简单的 box smooth（依赖 scipy；不可用时退化为原始 histogram）
        if _gaussian_filter is not None:
            try:
                H = _gaussian_filter(H, sigma=1.5)
            except Exception:
                pass
        X, Y = np.meshgrid(0.5 * (xedges[:-1] + xedges[1:]),
                           0.5 * (yedges[:-1] + yedges[1:]))
        try:
            self._density_contour = self.ax_map.contourf(
                X, Y, H.T, levels=8, cmap='Oranges',
                alpha=0.45, zorder=1,
            )
        except Exception:
            self._density_contour = None

    def _render_quiver(self):
        residents = self.sim.residents
        n = len(residents)
        if n == 0:
            return
        # 一次性向量化提取位置 + 速度
        xs = np.fromiter((r.x for r in residents), dtype=np.float64, count=n)
        ys = np.fromiter((r.y for r in residents), dtype=np.float64, count=n)
        vx = np.zeros(n, dtype=np.float64)
        vy = np.zeros(n, dtype=np.float64)
        for i, r in enumerate(residents):
            vel = getattr(r, 'velocity', None)
            if vel is not None and hasattr(vel, '__len__') and len(vel) >= 2:
                vx[i] = vel[0]; vy[i] = vel[1]

        xlim = self.ax_map.get_xlim(); ylim = self.ax_map.get_ylim()
        nx, ny = 12, 12
        xe = np.linspace(xlim[0], xlim[1], nx + 1)
        ye = np.linspace(ylim[0], ylim[1], ny + 1)
        ix = np.clip(np.digitize(xs, xe) - 1, 0, nx - 1)
        iy = np.clip(np.digitize(ys, ye) - 1, 0, ny - 1)

        # 用 np.add.at 矢量化累加，替代原来的 Python for 循环
        U = np.zeros((nx, ny), dtype=np.float64)
        V = np.zeros((nx, ny), dtype=np.float64)
        C = np.zeros((nx, ny), dtype=np.float64)
        np.add.at(U, (ix, iy), vx)
        np.add.at(V, (ix, iy), vy)
        np.add.at(C, (ix, iy), 1.0)
        mask = C > 0
        U[mask] /= C[mask]; V[mask] /= C[mask]

        Xc = 0.5 * (xe[:-1] + xe[1:])
        Yc = 0.5 * (ye[:-1] + ye[1:])
        Xm, Ym = np.meshgrid(Xc, Yc, indexing='ij')
        speed = np.hypot(U, V)

        # scale_units='xy' + scale=0.05 在经纬度坐标下箭头会爆长；
        # 改用 'inches' 让 quiver 自动按速度极值归一，箭头长度可读
        vmax = float(speed[mask].max()) if mask.any() else 1.0
        q_scale = max(vmax * 8.0, 1e-6)
        self._quiver = self.ax_map.quiver(
            Xm[mask], Ym[mask], U[mask], V[mask],
            speed[mask], cmap='cool',
            scale=q_scale, scale_units='inches',
            width=0.004, alpha=0.85, zorder=3,
        )

    def _update_zone_colors(self):
        if self._zone_collection is None:
            return
        colors = []
        for zid in self._zone_patch_ids:
            powered = self.sim.zone_status.get(zid, True)
            colors.append(ZONE_FILL_POWERED if powered else ZONE_FILL_OUTAGE)
        self._zone_collection.set_facecolors(colors)

    def _ensure_facility_cache(self):
        """infras 在 sim 生命周期内是静态的，分组 + zone 列表只算一次。

        缓存结构 _facility_cache:
            { ftype: { 'items': [...], 'zids': [zid,...], 'powered_color': hex } }
        """
        if getattr(self, '_facility_cache_sim', None) is self.sim:
            return
        infras = getattr(self.sim, 'critical_infras', None) or []
        cache = {}
        for f in infras:
            ftype = getattr(f, 'infra_type', None) or getattr(f, 'category', 'other')
            entry = cache.setdefault(ftype, {'items': [], 'zids': [],
                                            'powered_color': FACILITY_COLORS.get(ftype, '#9E9E9E')})
            entry['items'].append(f)
            entry['zids'].append(getattr(f, 'zone', getattr(f, 'zone_id', None)))
        self._facility_cache = cache
        self._facility_cache_sim = self.sim

    def _update_facility_colors(self):
        # 简化：根据所在区域的停电状态决定颜色（infras 静态，分组缓存）
        self._ensure_facility_cache()
        for ftype, entry in self._facility_cache.items():
            sc = self._facility_scatters.get(ftype)
            if sc is None:
                continue
            powered_color = entry['powered_color']
            colors = [
                powered_color if (zid is None or self.sim.zone_status.get(zid, True))
                else FACILITY_OUTAGE_COLOR
                for zid in entry['zids']
            ]
            sc.set_facecolors(colors)

    # ------------------------------------------------------------------
    # 指标面板更新
    # ------------------------------------------------------------------
    def _update_history(self):
        residents = self.sim.residents
        n = max(1, len(residents))
        s = self.sim.step_count
        self.history['step'].append(s)

        # 一次遍历提取所有居民标量，后续聚合全部用 numpy
        stress_arr = np.fromiter(
            (getattr(r, 'stress_level', 0.0) for r in residents), dtype=np.float64, count=len(residents))
        emotion_arr = np.fromiter(
            (getattr(r, 'emotion', 0.0) for r in residents), dtype=np.float64, count=len(residents))
        panic_arr = np.fromiter(
            (getattr(r, 'panic_value', 0.0) for r in residents), dtype=np.float64, count=len(residents))
        hoard_arr = np.fromiter(
            (1 if getattr(r, 'is_hoarding', False) else 0 for r in residents), dtype=np.int8, count=len(residents))
        herd_arr = np.fromiter(
            (1 if getattr(r, '_herd_active', False) else 0 for r in residents), dtype=np.int8, count=len(residents))
        zone_arr = [getattr(r, 'zone', getattr(r, 'zone_id', None)) for r in residents]

        self.history['avg_stress'].append(float(stress_arr.mean()) if len(residents) else 0.0)
        self.history['avg_emotion'].append(float(emotion_arr.mean()) if len(residents) else 0.0)
        self.history['avg_panic'].append(float(panic_arr.mean()) if len(residents) else 0.0)

        n_off = sum(1 for p in self.sim.zone_status.values() if not p)
        n_zone = max(1, len(self.sim.zone_status))
        self.history['outage_ratio'].append(n_off / n_zone)
        self.history['hoard_ratio'].append(float(hoard_arr.sum()) / n)
        self.history['herd_ratio'].append(float(herd_arr.sum()) / n)

        # 【M3 T14】路网层 graph 指标：congestion / 上路率 / 最大 edge occupancy
        # use_road_graph=False 时全部 0, 不影响旧分析
        cong_vals = np.fromiter(
            (float(getattr(r, '_edge_congestion', 0.0)) for r in residents),
            dtype=np.float64, count=len(residents),
        )
        on_path_arr = np.fromiter(
            (1 if getattr(r, 'current_edge', None) is not None else 0
             for r in residents),
            dtype=np.int8, count=len(residents),
        )
        self.history.setdefault('avg_edge_congestion', []).append(
            float(cong_vals.mean()) if len(residents) else 0.0)
        self.history.setdefault('pct_on_path', []).append(
            float(on_path_arr.mean()) if len(residents) else 0.0)
        G = getattr(self.sim, 'road_graph', None)
        if G is not None:
            try:
                max_occ = max(
                    (float(d.get('occupancy', 0))
                     for _, _, _, d in G.edges(keys=True, data=True)),
                    default=0.0,
                )
            except Exception:
                max_occ = 0.0
        else:
            max_occ = 0.0
        self.history.setdefault('max_edge_occupancy', []).append(max_occ)

        # 分区历史：用 zone→district 反向索引一次性分组
        d2z = getattr(self.sim, 'district_to_zones', {}) or {}
        if d2z:
            zone_to_district = {z: d for d, zs in d2z.items() for z in zs}
            district_arr = np.array([zone_to_district.get(z, None) for z in zone_arr], dtype=object)
            for d, zones in d2z.items():
                mask = district_arr == d
                if not mask.any():
                    continue
                h = self.district_history.setdefault(d, self._empty_history())
                h['step'].append(s)
                h['avg_stress'].append(float(stress_arr[mask].mean()))
                h['avg_emotion'].append(float(emotion_arr[mask].mean()))
                h['avg_panic'].append(float(panic_arr[mask].mean()))
                n_off_z = sum(1 for z in zones if not self.sim.zone_status.get(z, True))
                h['outage_ratio'].append(n_off_z / max(1, len(zones)))

        # SEIR 历史
        seir_count = {'S': 0, 'E': 0, 'I': 0, 'R': 0}
        for r in residents:
            st = getattr(r, 'state', 'S')
            seir_count[st] = seir_count.get(st, 0) + 1
        self.seir_history['step'].append(s)
        for k, v in seir_count.items():
            self.seir_history.setdefault(k, []).append(v)

    def _update_metric_panels(self):
        s = self.history['step']
        if not s:
            return
        # ---- 全局四指标 ----
        self._line_stress.set_data(s, self.history['avg_stress'])
        self._line_emotion.set_data(s, self.history['avg_emotion'])
        self._line_panic.set_data(s, self.history['avg_panic'])
        self._line_outage.set_data(s, self.history['outage_ratio'])
        self.ax_metric0.set_xlim(0, max(10, s[-1]))
        self._draw_phase_shade(self.ax_metric0)
        self._draw_event_lines(self.ax_metric0)

        # ---- 分区 ----
        d_keys = sorted(self.district_history.keys())
        cmap = plt.get_cmap('tab20', max(len(d_keys), 4))
        existing = set(self._district_lines.keys())
        for i, d in enumerate(d_keys):
            hist = self.district_history[d]
            if d not in self._district_lines:
                ln, = self.ax_metric1.plot(
                    hist['step'], hist['avg_stress'],
                    color=cmap(i), linewidth=1.3, label=d, alpha=0.9,
                )
                self._district_lines[d] = ln
            else:
                self._district_lines[d].set_data(hist['step'], hist['avg_stress'])
        if d_keys:
            self.ax_metric1.set_xlim(0, max(10, s[-1]))
            self.ax_metric1.legend(fontsize=7, loc='upper right', ncol=2)
        self._draw_phase_shade(self.ax_metric1)
        self._draw_event_lines(self.ax_metric1)

        # ---- SEIR ----
        ax2 = self.ax_metric2
        ax2.clear()
        ax2.set_title('SEIR 比例 + 事件', fontsize=10, fontweight='bold')
        ax2.set_ylim(0, 1)
        seir = self.seir_history
        xs = seir['step']
        if xs:
            arr = np.array([seir['S'], seir['E'], seir['I'], seir['R']], dtype=float)
            total = arr.sum(axis=0); total[total == 0] = 1.0
            ax2.stackplot(xs, arr / total,
                          labels=['S', 'E', 'I', 'R'],
                          colors=['#A5D6A7', '#FFE082', '#EF9A9A', '#90CAF9'],
                          alpha=0.85)
            ax2.set_xlim(xs[0], max(xs[-1], xs[0] + 1))
            ax2.legend(fontsize=8, loc='upper right')
            self._draw_phase_shade(ax2)
            self._draw_event_lines(ax2)

        # ---- 多 Run 对比叠加 ----
        if self.compare_mode and self.previous_runs:
            for i, prev in enumerate(self.previous_runs):
                ph = prev.get('history', {})
                xs_prev = ph.get('step', [])
                if not xs_prev:
                    continue
                for ax, key in (
                    (self.ax_metric0, 'avg_stress'),
                    (self.ax_metric0, 'avg_emotion'),
                ):
                    ys_prev = ph.get(key, [])
                    if ys_prev:
                        ax.plot(xs_prev, ys_prev, ':', color='#9E9E9E',
                                linewidth=1.0, alpha=0.6,
                                label=f"prev{i}-{key}" if i == 0 else None)

    def _draw_phase_shade(self, ax):
        if not self.history['step']:
            return
        last = self.history['step'][-1]
        outage_end = None
        # 找停电恢复事件
        for ev in self.events:
            if ev.get('kind') == 'recovery':
                outage_end = ev.get('step')
                break
        # 用 axvspan 添加，但要避免重复。简化：清掉再画。
        # 这里逻辑代价高，直接添加并接受叠加（颜色已透明）
        if self.outage_step is not None and self.outage_step > 0:
            ax.axvspan(0, min(self.outage_step, last),
                       color=PHASE_FILL['baseline'], alpha=0.18, zorder=0)
            end = outage_end if outage_end is not None else last
            ax.axvspan(self.outage_step, end,
                       color=PHASE_FILL['outage'], alpha=0.18, zorder=0)
            if outage_end is not None and outage_end < last:
                ax.axvspan(outage_end, last,
                           color=PHASE_FILL['recovery'], alpha=0.18, zorder=0)

    def _draw_event_lines(self, ax):
        for ev in self.events:
            ax.axvline(ev['step'], linestyle='--',
                       color=ev.get('color', '#D32F2F'),
                       linewidth=0.9, alpha=0.8)

    # ------------------------------------------------------------------
    # 状态栏
    # ------------------------------------------------------------------
    def _update_status_bar(self):
        s = self.sim.step_count if self.sim else 0
        t = s * getattr(self.sim, 'dt', 0.25) if self.sim else 0
        stress = self.history['avg_stress'][-1] if self.history['avg_stress'] else 0.0
        outage = self.history['outage_ratio'][-1] if self.history['outage_ratio'] else 0.0
        hoard = self.history['hoard_ratio'][-1] if self.history['hoard_ratio'] else 0.0
        herd = self.history['herd_ratio'][-1] if self.history['herd_ratio'] else 0.0
        layer_key = LAYER_LABEL_TO_KEY.get(self.layer_mode, self.layer_mode)
        self._status_text.set_text(
            f"Step={s}/{self.total_steps} | t={t:.1f}h "
            f"| Stress={stress:.3f} | Outage={outage:.0%} "
            f"| Hoard={hoard:.0%} | Herd={herd:.0%} "
            f"| Layer={layer_key} | Speed={self.speed}x | Mode={self.outage_mode}"
        )
        self._step_text.set_text(
            f"Step {s} | t={t:.1f}h\nσ̄={stress:.3f}\nOutage={outage:.0%}"
        )

    # ------------------------------------------------------------------
    # 单步 / 主循环
    # ------------------------------------------------------------------
    def _trigger_outage_if_needed(self):
        if self.outage_triggered:
            return
        if self.sim.step_count < self.outage_step:
            return
        # 选区：默认对全部 zone 触发；如有 outage_config 接口
        try:
            zones = list(self.sim.zone_status.keys())
            self.sim.trigger_outage(
                zone_ids=zones, mode=self.outage_mode,
                cause='equipment_failure',
                severity_ratio=0.5,
            )
            self.events.append({
                'step': self.sim.step_count,
                'label': '停电开始',
                'color': '#D32F2F',
                'kind': 'outage',
            })
        except Exception as e:
            print(f"[Dashboard] trigger_outage 失败: {e}")
        self.outage_triggered = True

    def _detect_recovery_event(self):
        """检测全部供电恢复时机，记录一次事件。"""
        if not self.outage_triggered:
            return
        if any(ev.get('kind') == 'recovery' for ev in self.events):
            return
        all_powered = all(p for p in self.sim.zone_status.values())
        if all_powered:
            self.events.append({
                'step': self.sim.step_count,
                'label': '电力恢复',
                'color': '#1976D2',
                'kind': 'recovery',
            })

    def step_once(self):
        if not self.sim or self.sim.step_count >= self.total_steps:
            self.running = False
            return False
        self._trigger_outage_if_needed()
        try:
            self.sim.step()
        except Exception as e:
            print(f"[Dashboard] sim.step() 异常: {e}")
            self.running = False
            return False
        self._detect_recovery_event()
        self._update_history()
        # 节流写 trace CSV（每 N 步一次）
        self._flush_traces(force=False)
        return True

    def _frame_draw(self):
        self._update_zone_colors()
        self._update_facility_colors()
        self._render_layer()
        self._update_metric_panels()
        self._update_status_bar()
        try:
            self.fig.canvas.draw_idle()
            self.fig.canvas.flush_events()
        except Exception:
            pass
        if self.recording_gif:
            self._capture_frame()

    def _reset_frame_cache(self):
        """清空帧缓存并删除对应的临时目录。"""
        old_dir = self.frame_dir
        self.frame_cache = []
        self.frame_dir = None
        if old_dir and os.path.isdir(old_dir):
            try:
                import shutil
                shutil.rmtree(old_dir, ignore_errors=True)
            except Exception:
                pass

    def _capture_frame(self):
        """流式落盘：每帧写到临时目录里，不全量保留在内存中。

        旧实现是把 PIL Image 全塞在 self.frame_cache 里，
        n 帧 × 16×9inch@70dpi RGB ≈ 几十 MB/帧，几百帧后就会爆几个 GB。
        现在改为：捕获时 savefig 到 self.frame_dir/frame_xxxxx.png，
        cache 只保留路径。bbox_inches='tight' 也去掉——
        否则每帧的实际像素尺寸会因文字长度变化，PIL 合 GIF 会报尺寸不一。
        """
        try:
            if self.frame_dir is None:
                import tempfile
                self.frame_dir = tempfile.mkdtemp(prefix='ccd_dashboard_frames_')
            idx = len(self.frame_cache)
            path = os.path.join(self.frame_dir, f'frame_{idx:06d}.png')
            # 关键：不要传 bbox_inches='tight'，否则各帧像素尺寸会漂移
            self.fig.savefig(path, format='png', dpi=70)
            self.frame_cache.append(path)
        except Exception as e:
            print(f"[Dashboard] capture_frame: {e}")

    # ------------------------------------------------------------------
    # 控件回调
    # ------------------------------------------------------------------
    def _on_start(self, event):
        self.running = True

    def _on_pause(self, event):
        self.running = False

    def _on_reset(self, event):
        self.running = False
        if self.compare_mode and self.history.get('step'):
            # 保留上一条历史到 previous_runs
            self.previous_runs.append({
                'name': f'run_{len(self.previous_runs) + 1}',
                'history': self.history.copy(),
                'district_history': {k: v.copy() for k, v in self.district_history.items()},
                'seir_history': self.seir_history.copy(),
            })
        # #10: 三个 metric 轴全部 cla()，清掉上一次 run 的 axvspan/axvline 残留，
        # 再用 _build_metric_axes 把 Line2D 引用重新建好
        self._district_lines = {}
        for ax in (self.ax_metric0, self.ax_metric1, self.ax_metric2):
            ax.cla()
        self._build_metric_axes()
        self._create_sim()
        self._draw_zone_patches()
        self._draw_facilities_static()
        self._auto_zoom_map()
        self._frame_draw()

    def _on_speed_change(self, label):
        self.speed = int(label.rstrip('x'))

    def _on_mode_change(self, label):
        self.outage_mode = label

    def _on_layer_change(self, label):
        self.layer_mode = label
        self._frame_draw()

    def _on_check_change(self, label):
        if label == '对比模式':
            self.compare_mode = not self.compare_mode
        elif label == '录制GIF':
            self.recording_gif = not self.recording_gif
            if self.recording_gif:
                # 新一轮录制：丢弃旧帧缓存与对应 tempdir
                self._reset_frame_cache()

    def _on_export_gif(self, event):
        if not self.frame_cache:
            print('[Dashboard] 暂无帧可导出 — 请先勾选"录制GIF"再运行仿真。')
            return
        out_dir = self._ensure_output_run_dir()
        path = os.path.join(out_dir, 'dashboard.gif')
        try:
            from PIL import Image
            # 流式打开第一帧、后续帧按路径懒加载，合成完立刻释放
            frames = self.frame_cache
            first = Image.open(frames[0]).convert('RGB')
            rest = (Image.open(p).convert('RGB') for p in frames[1:])
            first.save(
                path, save_all=True, append_images=list(rest),
                duration=120, loop=0, optimize=True,
            )
            print(f'[Dashboard] GIF 已导出: {path} ({len(frames)} 帧)')
        except Exception as e:
            print(f'[Dashboard] GIF 导出失败: {e}')

    def _on_save_charts(self, event):
        try:
            from .trace_plotter import plot_overview, plot_traces
        except ImportError:
            from trace_plotter import plot_overview, plot_traces
        out_dir = self._ensure_output_run_dir()
        baseline_end = self.outage_step
        outage_end = None
        for ev in self.events:
            if ev.get('kind') == 'recovery':
                outage_end = ev.get('step')
        events_for_plot = [{'step': ev['step'], 'label': ev.get('label'),
                            'color': ev.get('color')} for ev in self.events]
        overview_path = os.path.join(out_dir, 'overview.png')
        plot_overview(
            self.history, self.district_history, self.seir_history,
            out_path=overview_path,
            events=events_for_plot,
            baseline_end=baseline_end, outage_end=outage_end,
        )
        traces_path = os.path.join(out_dir, 'traces.png')
        plot_traces([self.history], labels=['current'],
                    out_path=traces_path,
                    events=events_for_plot,
                    baseline_end=baseline_end, outage_end=outage_end)
        # 保存 history.json
        json_path = os.path.join(out_dir, 'step_history.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump({
                'history': self.history,
                'district_history': self.district_history,
                'seir_history': self.seir_history,
                'events': self.events,
                'run_index': self.current_run_index,
            }, f, ensure_ascii=False, indent=2)
        # 强制把当前 trace 写入对应 run 子目录
        self._flush_traces(force=True)
        print(f'[Dashboard] Run #{self.current_run_index} 已保存:')
        print(f'  - {overview_path}')
        print(f'  - {traces_path}')
        print(f'  - {json_path}')
        if self.trace_run_dir:
            print(f'  - Trace CSV → {self.trace_run_dir}')

    def _on_load_history(self, event):
        """加载历史 run：优先取最新的 output/output_N/step_history.json，
        若不存在则回退到老路径 output/step_history.json（向后兼容）。"""
        path = None
        latest_n = self._scan_max_index(self.output_dir, 'output')
        # 从最大 N 倒着找第一个含 step_history.json 的目录
        for n in range(latest_n, 0, -1):
            cand = os.path.join(self.output_dir, f'output_{n}', 'step_history.json')
            if os.path.exists(cand):
                path = cand
                break
        if path is None:
            legacy = os.path.join(self.output_dir, 'step_history.json')
            if os.path.exists(legacy):
                path = legacy
        if path is None:
            print(f'[Dashboard] 未找到任何 step_history.json（已扫 output/output_*/）')
            return
        print(f'[Dashboard] 加载历史: {path}')
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.previous_runs.append({
                'name': f'load_{len(self.previous_runs) + 1}',
                'history': data.get('history', {}),
                'district_history': data.get('district_history', {}),
                'seir_history': data.get('seir_history', {}),
            })
            print(f'[Dashboard] 已加载 1 条历史 run，当前 previous_runs={len(self.previous_runs)}')
            self.compare_mode = True
            self._frame_draw()
        except Exception as e:
            print(f'[Dashboard] 加载历史失败: {e}')

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------
    def show(self, max_idle_seconds: float = 0.05):
        """阻塞循环。运行=on 时每帧推进 speed 步，否则空转保持交互响应。"""
        plt.ion()
        plt.show(block=False)
        self._frame_draw()
        while not self.exited:
            try:
                if not plt.fignum_exists(self.fig.number):
                    break
            except Exception:
                break
            if self.running:
                for _ in range(self.speed):
                    if not self.step_once():
                        break
                self._frame_draw()
            else:
                try:
                    self.fig.canvas.flush_events()
                except Exception:
                    pass
                time.sleep(max_idle_seconds)
        self.exited = True
        try:
            plt.close(self.fig)
        except Exception:
            pass

    def close(self):
        self.exited = True
