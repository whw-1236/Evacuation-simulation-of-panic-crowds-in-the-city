# -*- coding: utf-8 -*-
"""小区域实时观察器 - 受 0112 启发的极简版

设计目标:
    - 单个区县内观察居民移动 + SEIR 演化 + 区域停电状态
    - 性能轻量: 不影响仿真主循环 (用 set_offsets 增量更新, 不重画整图)
    - 无 PyQt 依赖, 纯 matplotlib

用法:
    viewer = SmallAreaViewer(sim, refresh_every=4)
    for step in range(N):
        sim.step()
        viewer.render(step)
    viewer.save_final('output/snapshot.png')
"""
import os
import numpy as np
import matplotlib

# 后端选择: 调试时用 TkAgg/Qt5Agg 实时弹窗, 服务器用 Agg 静默保存
if matplotlib.get_backend() == 'agg':
    pass  # 已被外部设置过 (如 run_xiamen_typhoon.py)
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.collections import PatchCollection

# 中文字体
plt.rcParams['font.family'] = ['Microsoft YaHei', 'SimHei', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False


SEIR_COLORS = {'S': '#4CAF50', 'E': '#FFC107', 'I': '#F44336', 'R': '#2196F3'}
SEIR_MARKERS = {'S': 'o', 'E': 's', 'I': '^', 'R': 'D'}


class SmallAreaViewer:
    """实时观察器 - 左图地图+居民散点, 右图时间序列"""

    def __init__(self, sim, refresh_every=4, figsize=(14, 6),
                 zoom_district=None, save_dir=None):
        """
        参数:
            sim: BlackoutSimulation 实例
            refresh_every: 每 N 步刷新一次 (1=每步, 4=每小时仿真时间)
            zoom_district: 仅显示某区县范围 (默认全图自适应)
            save_dir: 若设置, 每次刷新都保存 PNG 帧到此目录
        """
        self.sim = sim
        self.refresh_every = max(1, int(refresh_every))
        self.zoom_district = zoom_district
        self.save_dir = save_dir
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)

        # 历史轨迹 (用于右图)
        self.history = {
            'step': [], 'avg_stress': [], 'avg_emotion': [],
            'avg_panic': [], 'outage_ratio': [],
        }

        # 创建图形
        self.fig, (self.ax_map, self.ax_trace) = plt.subplots(
            1, 2, figsize=figsize, gridspec_kw={'width_ratios': [1.3, 1]}
        )
        self.fig.canvas.manager.set_window_title('V3 仿真观察器')

        self._init_map()
        self._init_trace()

        plt.ion()
        plt.show(block=False)

    def _init_map(self):
        """初始化地图: 画区域多边形 + 准备居民散点 collection"""
        ax = self.ax_map
        ax.set_aspect('equal')
        ax.set_xlabel('经度')
        ax.set_ylabel('纬度')
        ax.set_title(f'城市地图 (refresh every {self.refresh_every} steps)')

        # 区域多边形
        from shapely.geometry import Polygon, MultiPolygon
        patches = []
        zone_ids = []
        for zid, region_data in self.sim.region_manager.regions.items():
            geom = region_data.get('geometry')
            if geom is None:
                continue
            if isinstance(geom, MultiPolygon):
                for sub in geom.geoms:
                    patches.append(MplPolygon(np.array(sub.exterior.coords)))
                    zone_ids.append(zid)
            elif isinstance(geom, Polygon):
                patches.append(MplPolygon(np.array(geom.exterior.coords)))
                zone_ids.append(zid)
        self._zone_patch_ids = zone_ids
        self._zone_collection = PatchCollection(
            patches, edgecolor='gray', linewidth=0.3, alpha=0.5
        )
        ax.add_collection(self._zone_collection)

        # 居民散点 (一个 collection 一种 SEIR 状态)
        self._scatter_by_state = {}
        for state, color in SEIR_COLORS.items():
            sc = ax.scatter([], [], c=color, s=8, alpha=0.7,
                           marker=SEIR_MARKERS[state], label=state)
            self._scatter_by_state[state] = sc

        # 自适应/缩放视野
        if self.zoom_district and self.zoom_district in self.sim.district_to_zones:
            zones = self.sim.district_to_zones[self.zoom_district]
            xs, ys = [], []
            for zid in zones:
                geom = self.sim.region_manager.regions[zid].get('geometry')
                if geom:
                    minx, miny, maxx, maxy = geom.bounds
                    xs.extend([minx, maxx])
                    ys.extend([miny, maxy])
            if xs:
                pad = (max(xs) - min(xs)) * 0.05
                ax.set_xlim(min(xs) - pad, max(xs) + pad)
                ax.set_ylim(min(ys) - pad, max(ys) + pad)
        else:
            xs = [r.x for r in self.sim.residents]
            ys = [r.y for r in self.sim.residents]
            if xs:
                pad_x = (max(xs) - min(xs)) * 0.05 + 0.001
                pad_y = (max(ys) - min(ys)) * 0.05 + 0.001
                ax.set_xlim(min(xs) - pad_x, max(xs) + pad_x)
                ax.set_ylim(min(ys) - pad_y, max(ys) + pad_y)

        ax.legend(loc='upper right', fontsize=9, framealpha=0.8)
        self._step_text = ax.text(
            0.02, 0.98, '', transform=ax.transAxes,
            fontsize=10, verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='white', alpha=0.85)
        )

    def _init_trace(self):
        """初始化时间序列图"""
        ax = self.ax_trace
        ax.set_xlabel('Step')
        ax.set_ylabel('Value')
        ax.set_title('群体指标演化')
        ax.set_ylim(0, 1)
        ax.grid(True, alpha=0.3)

        self._line_stress, = ax.plot([], [], '-', color='#F44336', label='avg_stress')
        self._line_emotion, = ax.plot([], [], '-', color='#FFC107', label='avg_emotion')
        self._line_panic, = ax.plot([], [], '-', color='#9C27B0', label='avg_panic')
        self._line_outage, = ax.plot([], [], '-', color='#2196F3', label='outage_ratio')
        ax.legend(loc='upper left', fontsize=9, framealpha=0.8)

    def render(self, step=None):
        """更新一帧 (按 refresh_every 节流)"""
        if step is None:
            step = self.sim.step_count
        if step % self.refresh_every != 0:
            return

        self._update_zone_colors()
        self._update_residents()
        self._update_history()
        self._update_trace()

        avg_stress = self.history['avg_stress'][-1] if self.history['avg_stress'] else 0
        outage = self.history['outage_ratio'][-1] if self.history['outage_ratio'] else 0
        self._step_text.set_text(
            f"Step {step} | t={step*0.25:.1f}h\n"
            f"avg_stress={avg_stress:.3f}\n"
            f"outage={outage:.0%}"
        )

        try:
            self.fig.canvas.draw_idle()
            self.fig.canvas.flush_events()
        except Exception:
            pass  # 后端不支持交互模式时静默

        if self.save_dir:
            self.fig.savefig(os.path.join(self.save_dir, f'frame_{step:05d}.png'),
                            dpi=80, bbox_inches='tight')

    def _update_zone_colors(self):
        """根据停电状态更新区域颜色"""
        colors = []
        for zid in self._zone_patch_ids:
            powered = self.sim.zone_status.get(zid, True)
            colors.append('#C8E6C9' if powered else '#FFCDD2')  # 浅绿/浅红
        self._zone_collection.set_facecolors(colors)

    def _update_residents(self):
        """更新居民散点 (按 SEIR 分组)"""
        positions_by_state = {s: [] for s in 'SEIR'}
        for r in self.sim.residents:
            positions_by_state.get(r.state, positions_by_state['S']).append((r.x, r.y))
        for state, positions in positions_by_state.items():
            sc = self._scatter_by_state[state]
            if positions:
                sc.set_offsets(np.array(positions))
            else:
                sc.set_offsets(np.empty((0, 2)))

    def _update_history(self):
        residents = self.sim.residents
        n = max(1, len(residents))
        self.history['step'].append(self.sim.step_count)
        self.history['avg_stress'].append(
            sum(r.stress_level for r in residents) / n
        )
        self.history['avg_emotion'].append(
            sum(r.emotion for r in residents) / n
        )
        self.history['avg_panic'].append(
            sum(r.panic_value for r in residents) / n
        )
        n_off = sum(1 for p in self.sim.zone_status.values() if not p)
        self.history['outage_ratio'].append(n_off / max(1, len(self.sim.zone_status)))

    def _update_trace(self):
        s = self.history['step']
        self._line_stress.set_data(s, self.history['avg_stress'])
        self._line_emotion.set_data(s, self.history['avg_emotion'])
        self._line_panic.set_data(s, self.history['avg_panic'])
        self._line_outage.set_data(s, self.history['outage_ratio'])
        if s:
            self.ax_trace.set_xlim(0, max(10, s[-1]))

    def save_final(self, path):
        """保存最终一帧"""
        self.fig.savefig(path, dpi=120, bbox_inches='tight')
        return path

    def close(self):
        plt.close(self.fig)
