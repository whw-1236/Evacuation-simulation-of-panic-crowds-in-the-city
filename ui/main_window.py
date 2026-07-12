# -*- coding: utf-8 -*-
"""IJDRR Crowds_sim — 论文 §5 figure 互动 UI 主面板

基于 v3 (blackout_sim_v3_origin) 的 PyQt5 UI 移植, 适配 IJDRR 项目特性:
- MML (Mixed Multinomial Logit) 主形式 — 默认开 (§5.1 IIA substitution 主叙事)
- 3 城可选: 厦门思明 / 沈阳沈河 / 北京东城
- use_road_graph 开关 — graph-on 激活 flee 通道 (§5.1)
- 第 5 图改为 flee_ratio + herd_ratio 双线 (展示 §5.1 IIA substitution)

运行方式: python -m ui.main_window

输出:
- 💾 保存图表 → output_png/charts_*.png + map_*.png
- 🎬 录制 GIF → output_gif/sim_*.gif
- 📊 录制数据 → trace_output_ui/trace_*.csv
"""
import os
import sys
import csv
import io
import json
import math
import random
import traceback
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime

# 项目根目录加入 sys.path
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_PKG_DIR)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

# 设置 matplotlib 后端（必须早于 pyplot 导入）
import matplotlib
matplotlib.use('Qt5Agg')
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial Unicode MS']
matplotlib.rcParams['axes.unicode_minus'] = False

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.collections import PatchCollection, LineCollection
from matplotlib.lines import Line2D

from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSpinBox, QGroupBox, QSplitter, QStatusBar,
    QSlider, QComboBox, QCheckBox
)

from config.config import Config
from config.city_manager import CityManager
from simulation.simulation import BlackoutSimulation


# ============================================================
# 输出目录（不存在自动创建）
# ============================================================
OUT_PNG_DIR = os.path.join(_PROJECT_DIR, 'output_png')
OUT_GIF_DIR = os.path.join(_PROJECT_DIR, 'output_gif')
OUT_TRACE_DIR = os.path.join(_PROJECT_DIR, 'trace_output_ui')
ALL_GOV_DISTRICTS = '__all__'
ALL_CITY_DISTRICTS = '__city_all__'


def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def _load_outage_causes():
    """Read outage causes for UI dropdowns; keep a small fallback for startup robustness."""
    try:
        return Config().load_priority.OUTAGE_CAUSES
    except Exception:
        return {'equipment_failure': {'name': '设备故障'}}


def _safe_float(value, default=0.0):
    """Convert UI/export values without letting an optional v2 field break a run."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _latest_value(source, fallback=0.0):
    """Read either a scalar or the latest element of a simulation history."""
    if isinstance(source, (list, tuple, np.ndarray)):
        return _safe_float(source[-1], fallback) if len(source) else _safe_float(fallback)
    return _safe_float(source, fallback)


def _outage_state_to_audit(state, district=''):
    """Normalize a v2 outage dataclass/dict and tolerate the pre-v2 fields."""
    if state is None:
        return {}
    try:
        audit = state.to_audit_dict() if callable(getattr(state, 'to_audit_dict', None)) else state
    except Exception:
        audit = state
    if isinstance(audit, Mapping):
        data = dict(audit)
    else:
        fields = (
            'event_id', 'district', 'status', 'mode', 'cause', 'damage_level',
            'requested_shed_ratio', 'realized_shed_ratio', 'seed',
            'affected_zone_ids', 'affected_loads', 'affected_zone_count',
            'affected_load_count', 'detection_remaining_hours',
            'mobilization_remaining_hours', 'scheduled_remaining_hours',
            'total_work', 'work_done', 'remaining_work', 'current_capacity',
            'progress', 'eta_hours', 'start_step', 'repair_started_step',
            'restored_step',
        )
        data = {name: getattr(audit, name) for name in fields if hasattr(audit, name)}
    if district and not data.get('district'):
        data['district'] = district
    if 'affected_zone_count' not in data:
        data['affected_zone_count'] = len(data.get('affected_zone_ids') or [])
    if 'affected_load_count' not in data:
        data['affected_load_count'] = len(data.get('affected_loads') or [])
    total_work = _safe_float(data.get('total_work', 0.0))
    work_done = _safe_float(data.get('work_done', 0.0))
    if 'remaining_work' not in data:
        data['remaining_work'] = max(0.0, total_work - work_done)
    if 'progress' not in data:
        data['progress'] = (work_done / total_work) if total_work > 0 else 0.0
    return data


def _get_outage_state_audits(sim):
    """Return current per-district outage state records, including a legacy fallback."""
    raw_states = None
    for attr in ('district_outage_states', 'outage_states'):
        candidate = getattr(sim, attr, None)
        if candidate:
            raw_states = candidate
            break

    audits = []
    if isinstance(raw_states, Mapping):
        for district, state in raw_states.items():
            data = _outage_state_to_audit(state, str(district))
            if data:
                audits.append(data)
    elif isinstance(raw_states, (list, tuple)):
        audits = [_outage_state_to_audit(state) for state in raw_states]
        audits = [item for item in audits if item]

    if not audits:
        getter = getattr(sim, 'get_outage_state', None)
        districts = list((getattr(sim, 'district_to_zones', {}) or {}).keys())
        if callable(getter) and districts:
            for district in districts:
                try:
                    data = _outage_state_to_audit(getter(district), district)
                except Exception:
                    data = {}
                if data:
                    audits.append(data)

    # Pre-v2 compatibility: the UI can still describe the old single-district state.
    if not audits and getattr(sim, 'district_outage_mode', None):
        total_work = _safe_float(getattr(sim, 'district_total_work', 0.0))
        progress = _safe_float(getattr(sim, 'district_repair_progress', 0.0))
        audits.append({
            'district': getattr(sim, 'district_name', ''),
            'status': 'repairing' if getattr(sim, 'district_repair_started', False) else 'detecting',
            'mode': getattr(sim, 'district_outage_mode', ''),
            'cause': getattr(sim, 'district_outage_cause', ''),
            'requested_shed_ratio': 1.0 if getattr(sim, 'district_outage_mode', '') == 'full' else 0.0,
            'realized_shed_ratio': 0.0,
            'total_work': total_work,
            'work_done': total_work * progress,
            'remaining_work': total_work * max(0.0, 1.0 - progress),
            'progress': progress,
            'current_capacity': 0.0,
            'affected_zone_count': sum(
                1 for powered in (getattr(sim, 'zone_status', {}) or {}).values() if not powered),
            'affected_load_count': 0,
        })
    return audits


def _outage_metrics_snapshot(sim):
    """Aggregate active v2 incidents into a compact, CSV-safe UI snapshot."""
    audits = _get_outage_state_audits(sim)
    inactive = {'', 'inactive', 'normal', 'restored', 'completed', 'cancelled', 'none'}
    active = [
        state for state in audits
        if str(state.get('status', '')).lower() not in inactive
    ]
    if not active:
        return {
            'active': False, 'state_count': 0, 'event_id': '', 'phase': '正常供电',
            'mode': '', 'cause': '', 'seed': '', 'requested_shed_ratio': 0.0,
            'realized_shed_ratio': 0.0, 'affected_zone_count': 0,
            'affected_load_count': 0, 'detection_remaining_hours': 0.0,
            'mobilization_remaining_hours': 0.0, 'total_work': 0.0,
            'work_done': 0.0, 'remaining_work': 0.0, 'current_capacity': 0.0,
            'progress': 0.0, 'eta_hours': 0.0, 'estimated_recovery_step': None,
        }

    total_work = sum(_safe_float(item.get('total_work', 0.0)) for item in active)
    work_done = sum(_safe_float(item.get('work_done', 0.0)) for item in active)
    remaining_work = sum(_safe_float(item.get('remaining_work', 0.0)) for item in active)
    capacity = sum(_safe_float(item.get('current_capacity', 0.0)) for item in active)
    affected_loads = sum(int(_safe_float(item.get('affected_load_count', 0))) for item in active)
    affected_zones = sum(int(_safe_float(item.get('affected_zone_count', 0))) for item in active)
    weights = [max(1, int(_safe_float(item.get('affected_load_count', 0)))) for item in active]
    weight_total = sum(weights)
    requested = sum(
        _safe_float(item.get('requested_shed_ratio', 0.0)) * weight
        for item, weight in zip(active, weights)
    ) / weight_total
    realized = sum(
        _safe_float(item.get('realized_shed_ratio', 0.0)) * weight
        for item, weight in zip(active, weights)
    ) / weight_total
    eta_values = []
    for item in active:
        scheduled = item.get('scheduled_remaining_hours')
        if scheduled is not None:
            eta_values.append(max(0.0, _safe_float(scheduled)))
            continue
        repair_eta = item.get('eta_hours')
        if repair_eta is None:
            item_capacity = _safe_float(item.get('current_capacity', 0.0))
            repair_eta = (_safe_float(item.get('remaining_work', 0.0)) / item_capacity
                          if item_capacity > 0 else float('inf'))
        eta_values.append(
            max(0.0, _safe_float(item.get('detection_remaining_hours', 0.0))) +
            max(0.0, _safe_float(item.get('mobilization_remaining_hours', 0.0))) +
            _safe_float(repair_eta, float('inf'))
        )
    eta_hours = max(eta_values) if eta_values else float('inf')
    dt = _safe_float(getattr(sim, 'dt', 0.0))
    estimated_step = None
    if math.isfinite(eta_hours) and dt > 0:
        estimated_step = int(getattr(sim, 'step_count', 0) + math.ceil(eta_hours / dt))
    phases = sorted({str(item.get('status', '') or 'active') for item in active})
    modes = sorted({str(item.get('mode', '') or '') for item in active})
    causes = sorted({str(item.get('cause', '') or '') for item in active})
    event_ids = [str(item.get('event_id', '')) for item in active if item.get('event_id')]
    seeds = [str(item.get('seed', '')) for item in active if item.get('seed') is not None]
    return {
        'active': True,
        'state_count': len(active),
        'event_id': ','.join(event_ids),
        'phase': '/'.join(phases),
        'mode': '/'.join(modes),
        'cause': '/'.join(causes),
        'seed': ','.join(seeds),
        'requested_shed_ratio': requested,
        'realized_shed_ratio': realized,
        'affected_zone_count': affected_zones,
        'affected_load_count': affected_loads,
        'detection_remaining_hours': max(
            (_safe_float(item.get('detection_remaining_hours', 0.0)) for item in active), default=0.0),
        'mobilization_remaining_hours': max(
            (_safe_float(item.get('mobilization_remaining_hours', 0.0)) for item in active), default=0.0),
        'total_work': total_work,
        'work_done': work_done,
        'remaining_work': remaining_work,
        'current_capacity': capacity,
        'progress': (work_done / total_work) if total_work > 0 else 0.0,
        'eta_hours': eta_hours,
        'estimated_recovery_step': estimated_step,
    }


def _csv_number(value, digits=4):
    """Format numbers consistently, keeping unavailable/infinite repair ETA explicit."""
    if value is None:
        return ''
    number = _safe_float(value, float('nan'))
    if math.isnan(number):
        return ''
    if math.isinf(number):
        return 'inf' if number > 0 else '-inf'
    return f'{number:.{digits}f}'


def _system_help_components(sim, raw_emotion):
    """Expose Eq.23 components when core supplies them; derive only for legacy UI CSV."""
    components = getattr(sim, 'opinion_components', {}) or {}
    if isinstance(components, Mapping):
        def _component(*names):
            for name in names:
                if name in components:
                    return _safe_float(components[name])
            return None

        emotion = _component('emotion', 'emotion_component', 'emotion_pressure')
        enterprise = _component('enterprise', 'enterprise_component', 'q_component')
        critical = _component('critical', 'critical_component', 'c_component')
        if emotion is not None and enterprise is not None and critical is not None:
            return {
                'emotion': emotion,
                'enterprise': enterprise,
                'critical': critical,
                'source': 'core',
            }

    # Exact legacy Eq.23 fallback.  It keeps old runs interpretable but is not
    # treated as a second authoritative opinion state.
    q_value = _latest_value(getattr(sim, 'Q_hist', []), 0.0)
    c_value = _latest_value(getattr(sim, 'C_hist', []), 0.0)
    return {
        'emotion': 0.4 * min(1.0, max(0.0, 2.0 * (raw_emotion - 0.3))),
        'enterprise': 0.3 * min(1.0, max(0.0, q_value)),
        'critical': 0.3 * min(1.0, max(0.0, c_value)),
        'source': 'legacy_derived',
    }


# ============================================================
# 6 类 CSV POI 可视化样式 (跟 v3 + 属性说明.md 一致)
# ============================================================
POI_STYLE = {
    'hospital':   {'marker': 'P', 'color': '#E91E63', 'size': 70, 'label': '医院'},
    'emergency':  {'marker': '*', 'color': '#673AB7', 'size': 90, 'label': '应急机构'},
    'government': {'marker': '^', 'color': '#1565C0', 'size': 70, 'label': '政府机构'},
    'school':     {'marker': 's', 'color': '#8BC34A', 'size': 45, 'label': '学校'},
    'industry':   {'marker': 'o', 'color': '#FF9800', 'size': 30, 'label': '工业企业'},
}


# ============================================================
# 居民可视化: σ 4 级填色 (属性说明 §1.7) + SEIR marker 形状 (属性说明 §1.6)
# ============================================================
# σ 4 级 (跟论文 §3.2.2 行为阈值一致):
#   <0.2 平静绿 / <0.4 轻度焦虑琥珀 / <0.6 中度焦虑橙 / ≥0.6 高度恐慌红
# SEIR 用 marker 形状区分信息扩散态:
#   S 圆 / E 方 / I 三角 / R 菱形
# 两个维度组合 → 一眼看出"情绪恢复 (色) + 信息传播 (形状) 双动态"
SIGMA_LEVELS = [
    (0.2, '#4CAF50'),   # 平静 绿
    (0.4, '#FFC107'),   # 轻度焦虑 琥珀
    (0.6, '#FF9800'),   # 中度焦虑 橙 (hoard 起点)
    (1.01, '#F44336'),  # 高度恐慌 红 (herd/flee 起点)
]
SEIR_MARKER = {'S': 'o', 'E': 's', 'I': '^', 'R': 'D'}
SEIR_LABEL_CN = {'S': '未知S', 'E': '潜伏E', 'I': '传播I', 'R': '恢复R'}


def sigma_color(sigma):
    """σ → 4 级填色 (属性说明 §1.7)"""
    for threshold, color in SIGMA_LEVELS:
        if sigma < threshold:
            return color
    return SIGMA_LEVELS[-1][1]


# ============================================================
# 3 城选择 (跟论文 §5 主表三城一致)
# ============================================================
CITY_OPTIONS = [
    ('厦门市', '思明区'),
    ('沈阳市', '沈河区'),
    ('北京市', '东城区'),
]


def _resolve_map_dir():
    """定位 simulation map data/ 目录 (跟 scripts/run_ablation.py 一致)"""
    candidate = os.path.join(_PROJECT_DIR, 'simulation map data')
    return candidate if os.path.isdir(candidate) else _PROJECT_DIR


# ============================================================
# Worker — 在后台线程里跑仿真
# ============================================================
class SimulationWorker(QThread):
    """后台 QThread, 跑 BlackoutSimulation 每步, 通过 signal 推指标给 UI."""
    step_done = pyqtSignal(dict)
    init_done = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, city, district, n_residents, n_enterprises,
                 use_road_graph, use_mml, total_steps=0):
        super().__init__()
        self.city = city
        self.district = district
        self.n_residents = int(n_residents)
        self.n_enterprises = int(n_enterprises)
        self.use_road_graph = bool(use_road_graph)
        self.use_mml = bool(use_mml)
        self.total_steps = int(total_steps)   # 0 = 无限跑 (旧行为, 兜底)
        self.sim = None
        self._running = False
        self._paused = False
        self._pending_actions = []
        self._step_interval_ms = 30

        # worker 自己维护的历史 (避免改 simulation.py)
        # `opinion_hist` remains the legacy Eq.23 composite, now labelled
        # "系统综合求助压力" in the UI.  The authoritative dynamic public-opinion
        # state is kept separately so the two quantities cannot be confused.
        self.opinion_hist = []
        self.public_opinion_hist = []
        self.emotion_hist = []           # raw, 严格按论文 §3.2.4 Eq.5 (sim 算的)
        self.emotion_display_hist = []   # UI-only: raw + chronic-anxiety floor + trailing avg
        self.stress_hist = []
        self.panic_hist = []
        self.flee_hist = []
        self.herd_hist = []
        self.recovery_hist = []
        self.blackout_hist = []
        self.R_hist = []
        self.seir_hist = {'S': [], 'E': [], 'I': [], 'R': []}

    def queue_action(self, fn):
        self._pending_actions.append(fn)

    def _build_city_config(self):
        cm = CityManager(map_data_dir=_resolve_map_dir())
        try:
            sm_path = cm.get_district_geojson(
                self.city, self.district, use_no_mountain=True)
        except Exception:
            sm_path = None
        if not sm_path:
            raise RuntimeError(
                f'未找到 {self.city}/{self.district} GeoJSON. '
                f'请确认 simulation map data/ 目录结构正确')
        return {
            'city': self.city,
            'geojson_paths': [sm_path],
            'districts': [self.district],
            'use_road_graph': self.use_road_graph,
        }

    def _init_simulation(self):
        try:
            cfg = Config()
            cfg.simulation.N_RESIDENTS = self.n_residents
            cfg.simulation.N_ENTERPRISES = self.n_enterprises
            city_config = self._build_city_config()
            self.sim = BlackoutSimulation(config=cfg, city_config=city_config)

            # MML 默认开 (2026-06-28 起 SwitchParams.use_mml=True);
            # 关掉走 sigmoid legacy fallback (论文 §5 supplementary)
            if not self.use_mml:
                fc = getattr(self.sim, 'force_calculator', None)
                if fc is not None:
                    if hasattr(fc, 'sw'):
                        fc.sw.use_mml = False
                    sfm = getattr(fc, 'social_force_model', None)
                    if sfm is not None and hasattr(sfm, 'sw'):
                        sfm.sw.use_mml = False
                for r in self.sim.residents:
                    if getattr(r, 'sw', None) is not None:
                        r.sw.use_mml = False
                print('[UI] use_mml = False (sigmoid legacy fallback)')
            else:
                print('[UI] use_mml = True (MML 主形式, §5 默认)')

            self.init_done.emit(self.sim)
        except Exception as e:
            traceback.print_exc()
            self.error.emit(f'初始化失败: {e}')

    def run(self):
        self._init_simulation()
        if self.sim is None:
            return
        self._running = True
        while self._running:
            if self._paused:
                self.msleep(40)
                continue
            while self._pending_actions:
                act = self._pending_actions.pop(0)
                try:
                    act(self.sim)
                except Exception as e:
                    print(f'[action error] {e}')
                    traceback.print_exc()
            try:
                self.sim.step()
                self._record_step()
                self.step_done.emit(self._collect_metrics())
            except Exception as e:
                traceback.print_exc()
                self.error.emit(f'仿真步出错: {e}')
                break
            # 到点自动停 (total_steps=0 时无限跑, 兜底兼容)
            if self.total_steps > 0 and self.sim.step_count >= self.total_steps:
                print(f'[worker] 已达预设总步数 {self.total_steps}, 自动停止')
                self._running = False
                break
            self.msleep(self._step_interval_ms)

    def _record_step(self):
        """从 residents 直接算每步指标 (跟 scripts/run_ablation.py 一致)"""
        sim = self.sim
        residents = sim.residents
        n = max(1, len(residents))

        # 从 sim.X_hist 拿 (这些 IJDRR 本来就有)
        self.opinion_hist.append(sim.P_hist[-1] if sim.P_hist else 0.0)
        public_hist = getattr(sim, 'public_opinion_hist', None)
        if isinstance(public_hist, (list, tuple, np.ndarray)) and len(public_hist):
            public_pressure = _latest_value(public_hist, self.opinion_hist[-1])
        else:
            event_influence = getattr(sim, 'event_influence', None)
            public_pressure = _safe_float(
                getattr(sim, 'public_opinion_pressure',
                        getattr(event_influence, 'public_opinion_pressure',
                                getattr(event_influence, 'opinion_pressure', self.opinion_hist[-1]))),
                self.opinion_hist[-1],
            )
        self.public_opinion_hist.append(public_pressure)
        self.emotion_hist.append(sim.emotion_hist[-1] if sim.emotion_hist else 0.0)
        self.recovery_hist.append(sim.recovery_hist[-1] if sim.recovery_hist else 1.0)
        self.blackout_hist.append(sim.blackout_hist[-1] if sim.blackout_hist else 0.0)
        self.R_hist.append(sim.R_hist[-1] if sim.R_hist else 0.0)
        for st in 'SEIR':
            arr = sim.seir_hist.get(st, [])
            self.seir_hist[st].append(arr[-1] if arr else 0.0)

        # stress/panic/flee/herd — 从 residents 直接算
        stress_sum = 0.0
        panic_sum = 0.0
        flee_count = 0
        herd_count = 0
        for r in residents:
            stress_sum += float(getattr(r, 'stress_level', 0.0))
            panic_sum += float(getattr(r, 'panic_value', 0.0))
            if getattr(r, '_dom_action', None) == 'flee':
                flee_count += 1
            if getattr(r, '_herd_active', False):
                herd_count += 1
        avg_stress = stress_sum / n
        self.stress_hist.append(avg_stress)
        self.panic_hist.append(panic_sum / n)
        self.flee_hist.append(flee_count / n)
        self.herd_hist.append(herd_count / n)

        # ===========================================================
        # UI-only emotion display: chronic-anxiety floor + trailing avg
        # ===========================================================
        # 动机: 论文 §3.2.4 Eq.5 `E = σ × min(Pe, Pc)` 在长仿真 (t > tc+te ≈ 14h)
        # 下 Pc → 0 → emotion → 0, 这是 PTSD-style 心理麻木的设计意图.
        # 但作为"群体观察指标", 长期归零损失可见性. 这里加 UI 渲染层 floor
        # **不修改 simulation core**, 论文公式严格保留.
        # raw_emotion 同时进 self.emotion_hist (写 CSV 用), display 仅给 ChartPanel.
        raw_emotion = self.emotion_hist[-1]
        # chronic-anxiety baseline: 高 stress 时给 emotion 一个底, stress<0.15 时无底
        chronic_floor = max(0.0, 0.5 * (avg_stress - 0.15))
        # trailing avg 平滑近 5 步, 避免单步抖动
        recent_n = min(5, len(self.emotion_hist))
        recent_avg = (sum(self.emotion_hist[-recent_n:]) / recent_n) if recent_n else raw_emotion
        display = max(recent_avg, chronic_floor)
        self.emotion_display_hist.append(display)

    def _collect_metrics(self):
        s = self.sim
        govs = list(getattr(s, 'gov_agents', {}).values())
        gov_events = {
            'warning': sum(1 for g in govs if getattr(g, 'emergency_warning_issued', False)),
            'resource_grid': sum(1 for g in govs if getattr(g, 'resource_to_grid', False)),
            'resource_enterprise': sum(1 for g in govs if getattr(g, 'resource_to_enterprise', False)),
            'resource_resident': sum(1 for g in govs if getattr(g, 'resource_to_resident', False)),
            'opinion': sum(1 for g in govs if getattr(g, 'public_opinion_active', False)),
            'district_total': len(govs),
        }
        try:
            raw_event_stats = s.get_event_statistics()
        except Exception:
            raw_event_stats = {}
        event_stats = {
            'total': int(raw_event_stats.get('total_events', 0) or 0),
            'active': int(raw_event_stats.get('active_events', 0) or 0),
            'completed': int(raw_event_stats.get('completed_events', 0) or 0),
        }
        cause_values = [
            value for value in (getattr(s, 'zone_outage_cause', {}) or {}).values()
            if value
        ]
        dominant_cause = ''
        if cause_values:
            dominant_cause = max(set(cause_values), key=cause_values.count)
        outage_command = getattr(s, 'last_ui_outage_command', {}) or {}
        outage = _outage_metrics_snapshot(s)
        outage_mode = outage.get('mode') or outage_command.get('mode') or getattr(s, 'district_outage_mode', '') or ''
        outage_cause = outage.get('cause') or outage_command.get('cause') or getattr(s, 'district_outage_cause', '') or dominant_cause
        help_components = _system_help_components(s, self.emotion_hist[-1])
        action_log = getattr(s, 'ui_action_log', []) or []
        last_action = action_log[-1] if isinstance(action_log, list) and action_log else {}
        return {
            'step': s.step_count,
            't_hour': getattr(s, 'current_hour', 0.0),
            # Backward-compatible `P`; do not label this as social opinion.
            'P': self.opinion_hist[-1],
            'system_help_pressure': self.opinion_hist[-1],
            'public_opinion_pressure': self.public_opinion_hist[-1],
            'system_help_emotion_component': help_components['emotion'],
            'system_help_enterprise_component': help_components['enterprise'],
            'system_help_critical_component': help_components['critical'],
            'system_help_component_source': help_components['source'],
            'emotion_raw': self.emotion_hist[-1],
            'emotion_display': self.emotion_display_hist[-1],
            'emotion': self.emotion_display_hist[-1],  # 兼容旧字段, 给 status bar 用
            'stress': self.stress_hist[-1],
            'panic': self.panic_hist[-1],
            'flee_ratio': self.flee_hist[-1],
            'herd_ratio': self.herd_hist[-1],
            'recovery': self.recovery_hist[-1],
            'blackout': self.blackout_hist[-1],
            'R': self.R_hist[-1],
            'seir': {st: self.seir_hist[st][-1] for st in 'SEIR'},
            'history_len': len(self.opinion_hist),
            'outage_mode': outage_mode,
            'outage_cause': outage_cause,
            'outage_severity': float(outage.get('requested_shed_ratio', outage_command.get('severity_ratio', 0.0)) or 0.0),
            'outage_scope': outage_command.get('scope', ''),
            'outage': outage,
            'outage_last_error': str(getattr(s, 'last_ui_outage_error', '') or ''),
            'outage_last_warning': str(getattr(s, 'last_ui_outage_warning', '') or ''),
            'ui_action_count': len(action_log) if isinstance(action_log, list) else 0,
            'ui_last_action': str(last_action.get('action', '')) if isinstance(last_action, Mapping) else '',
            'ui_last_action_step': int(_safe_float(last_action.get('step', 0))) if isinstance(last_action, Mapping) else 0,
            'gov_events': gov_events,
            'event_stats': event_stats,
            'event5_district_ratio': float(getattr(s, 'event5_active_district_ratio', 0.0)),
            'event5_resident_ratio': float(getattr(s, 'event5_active_resident_ratio', 0.0)),
            'last_event_summary': getattr(s, 'last_event_summary', {}) or {},
        }

    def stop(self):
        self._running = False
        self._paused = False


# ============================================================
# 右侧图表面板 — 6 个时间序列子图
# ============================================================
class ChartPanel(QWidget):
    """6 子图: 系统求助/动态舆情、情绪、压力、恐慌、cascade 与 SEIR。"""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        self.fig = Figure(figsize=(7, 10), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.fig)
        layout.addWidget(self.canvas)

        self.ax_opinion = self.fig.add_subplot(611)
        self.ax_emotion = self.fig.add_subplot(612)
        self.ax_stress = self.fig.add_subplot(613)
        self.ax_panic = self.fig.add_subplot(614)
        self.ax_cascade = self.fig.add_subplot(615)
        self.ax_seir = self.fig.add_subplot(616)

        for ax, title in [
            (self.ax_opinion, '系统综合求助压力（Eq.23）/ 权威舆情压力（动态）'),
            (self.ax_emotion, '平均情绪 Emotion (UI 显示: chronic-anxiety floor; raw 见 CSV)'),
            (self.ax_stress, '平均压力 σ (master stress)'),
            (self.ax_panic, '平均恐慌 P_i = σ^0.8'),
            (self.ax_cascade, '§5.1 cascade: flee_ratio (实线) vs herd_ratio (虚线)'),
            (self.ax_seir, 'SEIR 信息扩散'),
        ]:
            ax.set_title(title, fontsize=9)
            ax.set_ylim(0, 1)
            ax.grid(True, alpha=0.3)
            ax.tick_params(labelsize=7)

        self.line_opinion, = self.ax_opinion.plot(
            [], [], '-', color='#c0392b', lw=1.4, label='系统综合求助压力 (Eq.23)')
        self.line_public_opinion, = self.ax_opinion.plot(
            [], [], '--', color='#6c3483', lw=1.3, label='权威舆情压力 (dynamic)')
        self.ax_opinion.legend(loc='upper right', fontsize=6, ncol=2)
        # emotion: display 主线 (蓝实线) + raw 参考线 (灰虚线), 让 reviewer 同时看到原值
        self.line_emotion, = self.ax_emotion.plot([], [], '-', color='#3498db', lw=1.6,
                                                  label='UI display (floor)')
        self.line_emotion_raw, = self.ax_emotion.plot([], [], ':', color='#7f8c8d', lw=1.0,
                                                      label='raw (§3.2.4 Eq.5)')
        self.ax_emotion.legend(loc='upper right', fontsize=6, ncol=2)
        self.line_stress, = self.ax_stress.plot([], [], '-', color='#e67e22', lw=1.4)
        self.line_panic, = self.ax_panic.plot([], [], '-', color='#9b59b6', lw=1.4)
        self.line_flee, = self.ax_cascade.plot([], [], '-', color='#2980b9', lw=1.6, label='flee_ratio')
        self.line_herd, = self.ax_cascade.plot([], [], '--', color='#c0392b', lw=1.4, label='herd_ratio')
        self.ax_cascade.legend(loc='upper right', fontsize=7, ncol=2)

        self.seir_lines = {
            'S': self.ax_seir.plot([], [], '-', color='#27ae60', lw=1.2, label='S')[0],
            'E': self.ax_seir.plot([], [], '-', color='#f1c40f', lw=1.2, label='E')[0],
            'I': self.ax_seir.plot([], [], '-', color='#e74c3c', lw=1.2, label='I')[0],
            'R': self.ax_seir.plot([], [], '-', color='#2980b9', lw=1.2, label='R')[0],
        }
        self.ax_seir.legend(loc='upper right', fontsize=7, ncol=4)

        self._intervention_markers = []
        self._intervention_annotations = []

    def update_data(self, worker):
        n = len(worker.opinion_hist)
        if n == 0:
            return
        xs = np.arange(n)
        self.line_opinion.set_data(xs, worker.opinion_hist)
        self.line_public_opinion.set_data(xs, worker.public_opinion_hist)
        # emotion: 主线用 display (chronic-anxiety floor), 参考线显示 raw §3.2.4 公式值
        self.line_emotion.set_data(xs, worker.emotion_display_hist)
        self.line_emotion_raw.set_data(xs, worker.emotion_hist)
        self.line_stress.set_data(xs, worker.stress_hist)
        self.line_panic.set_data(xs, worker.panic_hist)
        self.line_flee.set_data(xs, worker.flee_hist)
        self.line_herd.set_data(xs, worker.herd_hist)
        for st in 'SEIR':
            self.seir_lines[st].set_data(xs, worker.seir_hist[st])
        for ax in [self.ax_opinion, self.ax_emotion, self.ax_stress,
                   self.ax_panic, self.ax_cascade, self.ax_seir]:
            ax.set_xlim(0, max(50, n))
        self.canvas.draw_idle()

    def mark_intervention(self, step, label=''):
        for ax in [self.ax_opinion, self.ax_emotion, self.ax_stress,
                   self.ax_panic, self.ax_cascade, self.ax_seir]:
            line = ax.axvline(step, color='#7f8c8d', lw=0.8, ls='--', alpha=0.5)
            self._intervention_markers.append(line)
        if label:
            # Existing marker lines were anonymous.  A compact label on the
            # top panel makes screenshots auditable without covering all six plots.
            annotation = self.ax_opinion.text(
                step, 0.98, str(label)[:32],
                transform=self.ax_opinion.get_xaxis_transform(), rotation=90,
                va='top', ha='right', fontsize=5.5, color='#566573',
                alpha=0.85, clip_on=True,
            )
            self._intervention_annotations.append(annotation)


# ============================================================
# 左侧地图面板 — 区域 + 6 类 POI + 居民 + (optional) shelter + road graph
# ============================================================
class MapPanel(QWidget):
    """地图层. use_road_graph=True 时叠加路网 + shelter 散点"""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        self.fig = Figure(figsize=(7, 10), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.fig)
        layout.addWidget(self.canvas)

        self.ax = self.fig.add_subplot(111)
        self.ax.set_aspect('equal')
        self.ax.set_title(
            '居民+POI+路网+避难所 | 区域: 绿=有电/琥珀=部分停电/红=全停 | '
            '居民形状: o S/s E/^ I/D R (SEIR), 填色: σ 绿→琥珀→橙→红',
            fontsize=8)
        self.ax.tick_params(labelsize=7)

        self.zone_collection = None
        self.zone_ids = []
        self.poi_scatters = {}
        self.poi_nodes_by_cat = {}
        self.resident_scatters = {}   # {SEIR_state: scatter}, 4 个 marker 形状区分 SEIR
        self.shelter_scatter = None
        self.road_graph_drawn = False
        self.initialized = False

    def init_map(self, sim):
        if self.initialized:
            return

        # 区域多边形
        patches = []
        self.zone_ids = []
        for zid, rdata in sim.region_manager.regions.items():
            geom = rdata.get('geometry')
            if geom is None:
                continue
            try:
                if hasattr(geom, 'exterior'):
                    coords = list(geom.exterior.coords)
                    patches.append(MplPolygon(coords, closed=True))
                    self.zone_ids.append(zid)
                elif hasattr(geom, 'geoms'):
                    biggest = max(geom.geoms, key=lambda g: g.area)
                    coords = list(biggest.exterior.coords)
                    patches.append(MplPolygon(coords, closed=True))
                    self.zone_ids.append(zid)
            except Exception:
                continue
        self.zone_collection = PatchCollection(
            patches, edgecolor='#bdc3c7', linewidths=0.2, zorder=1)
        self.zone_collection.set_facecolor('#81c784')
        self.ax.add_collection(self.zone_collection)

        # (optional) 路网灰色描底
        if getattr(sim, 'use_road_graph', False) and getattr(sim, 'road_graph', None) is not None:
            try:
                self._draw_road_graph(sim.road_graph)
                self.road_graph_drawn = True
            except Exception as e:
                print(f'[map] road graph draw skipped: {e}')

        # 6 类 POI 散点
        poi_groups = defaultdict(list)
        for node in getattr(sim, 'csv_nodes', []):
            cat = node.get('category')
            if cat in POI_STYLE:
                poi_groups[cat].append(node)
        for cat, style in POI_STYLE.items():
            nodes = poi_groups.get(cat, [])
            if not nodes:
                continue
            xs_p = [n['lon'] for n in nodes]
            ys_p = [n['lat'] for n in nodes]
            sc = self.ax.scatter(
                xs_p, ys_p,
                marker=style['marker'], c=style['color'], s=style['size'],
                edgecolors='black', linewidths=0.4, alpha=0.9,
                label=f"{style['label']} ({len(nodes)})",
                zorder=3,
            )
            self.poi_scatters[cat] = sc
            self.poi_nodes_by_cat[cat] = nodes

        # (optional) shelter 散点 (金色五角星, 突出)
        shelters = getattr(sim, 'shelters', None) or []
        if shelters:
            xs_s = [s['lon'] for s in shelters if 'lon' in s]
            ys_s = [s['lat'] for s in shelters if 'lat' in s]
            if xs_s:
                self.shelter_scatter = self.ax.scatter(
                    xs_s, ys_s, marker='*', c='#FFD700', s=180,
                    edgecolors='#8B4513', linewidths=1.0, alpha=0.95,
                    label=f'避难所 ({len(xs_s)})', zorder=4,
                )

        # 居民散点 — 4 个 scatter, marker 区分 SEIR (属性说明 §1.6), facecolor 区分 σ 4 级 (§1.7)
        # 先建 4 个空 scatter (含一个 dummy 点保证 legend 有 marker), update_map 再 set_offsets 填实
        n_total = len(sim.residents)
        for state in 'SEIR':
            sc = self.ax.scatter(
                [], [], marker=SEIR_MARKER[state], s=14,
                c='#9E9E9E', edgecolors='black', linewidths=0.3,
                alpha=0.88, zorder=5,
                label=f'居民·{SEIR_LABEL_CN[state]}',
            )
            self.resident_scatters[state] = sc
        self._update_resident_scatters(sim)

        # σ 色卡 proxy artists (legend 里显示 4 级填色含义)
        sigma_proxies = [
            Line2D([0], [0], marker='o', color='w', markersize=7,
                   markerfacecolor=SIGMA_LEVELS[0][1], markeredgecolor='gray',
                   label=f'σ<0.2 平静 ({n_total} total)'),
            Line2D([0], [0], marker='o', color='w', markersize=7,
                   markerfacecolor=SIGMA_LEVELS[1][1], markeredgecolor='gray',
                   label='σ 0.2-0.4 轻度'),
            Line2D([0], [0], marker='o', color='w', markersize=7,
                   markerfacecolor=SIGMA_LEVELS[2][1], markeredgecolor='gray',
                   label='σ 0.4-0.6 中度'),
            Line2D([0], [0], marker='o', color='w', markersize=7,
                   markerfacecolor=SIGMA_LEVELS[3][1], markeredgecolor='gray',
                   label='σ≥0.6 高度'),
        ]
        legend_handles, _ = self.ax.get_legend_handles_labels()
        self.ax.legend(handles=legend_handles + sigma_proxies,
                       loc='upper left', fontsize=6, framealpha=0.85,
                       ncol=1, labelspacing=0.25, handlelength=1.4,
                       borderpad=0.3, columnspacing=0.5)

        # 用 zone bounds 设视野
        all_x, all_y = [], []
        for zid, rdata in sim.region_manager.regions.items():
            geom = rdata.get('geometry')
            if geom is None:
                continue
            try:
                minx, miny, maxx, maxy = geom.bounds
                all_x.extend([minx, maxx])
                all_y.extend([miny, maxy])
            except Exception:
                continue
        if all_x and all_y:
            pad = 0.005
            self.ax.set_xlim(min(all_x) - pad, max(all_x) + pad)
            self.ax.set_ylim(min(all_y) - pad, max(all_y) + pad)
        elif xs and ys:
            pad = 0.005
            self.ax.set_xlim(min(xs) - pad, max(xs) + pad)
            self.ax.set_ylim(min(ys) - pad, max(ys) + pad)

        self.initialized = True
        self.canvas.draw_idle()

    def _draw_road_graph(self, G):
        """绘路网 edges (中灰底, 不交互). 显示全部 edge, 不截断"""
        segs = []
        for u, v, _data in G.edges(data=True):
            ux = G.nodes[u].get('x'); uy = G.nodes[u].get('y')
            vx = G.nodes[v].get('x'); vy = G.nodes[v].get('y')
            if ux is None or vx is None:
                continue
            segs.append(((ux, uy), (vx, vy)))
        if segs:
            # 颜色/线宽调亮: 在浅绿 zone 底上能清晰浮现, alpha 略高
            lc = LineCollection(segs, colors='#666666', linewidths=0.6,
                                alpha=0.75, zorder=2)
            self.ax.add_collection(lc)
            print(f'[map] road graph drawn: {len(segs)} edges')

    def update_map(self, sim):
        if not self.initialized:
            self.init_map(sim)
            return

        # 区域颜色权威来源是 v2 `zone_power_fraction`：0=红色全停，
        # (0,1)=琥珀色部分供电，1=绿色正常。旧引擎没有该字段时，再回退到
        # zone_status + zone_outage_cause，避免把历史结果误显示为全绿。
        outage_cause_dict = getattr(sim, 'zone_outage_cause', {}) or {}
        zone_fractions = getattr(sim, 'zone_power_fraction', {}) or {}
        if not isinstance(zone_fractions, Mapping):
            zone_fractions = {}
        zone_colors = []
        for zid in self.zone_ids:
            fraction = zone_fractions.get(zid)
            if fraction is not None:
                fraction = max(0.0, min(1.0, _safe_float(fraction, 1.0)))
                if fraction <= 1e-9:
                    zone_colors.append('#e57373')   # 全停 红
                elif fraction < 1.0 - 1e-9:
                    zone_colors.append('#FFC107')   # 部分供电 琥珀
                else:
                    zone_colors.append('#81c784')   # 正常供电 绿
                continue
            powered = sim.zone_status.get(zid, True)
            has_cause = bool(outage_cause_dict.get(zid))
            if not powered:
                zone_colors.append('#e57373')   # 全停 红
            elif has_cause:
                zone_colors.append('#FFC107')   # 部分停电 琥珀
            else:
                zone_colors.append('#81c784')   # 有电 绿
        self.zone_collection.set_facecolor(zone_colors)

        # POI 停电变灰
        OUTAGE_GRAY = '#757575'
        OUTAGE_EDGE = '#424242'
        for cat, sc in self.poi_scatters.items():
            style = POI_STYLE[cat]
            face_colors, edge_colors = [], []
            for n in self.poi_nodes_by_cat[cat]:
                if n.get('powered', True):
                    face_colors.append(style['color'])
                    edge_colors.append('black')
                else:
                    face_colors.append(OUTAGE_GRAY)
                    edge_colors.append(OUTAGE_EDGE)
            sc.set_facecolor(face_colors)
            sc.set_edgecolor(edge_colors)

        # 居民: 按 SEIR 分桶, 各 scatter 用 σ 4 级填色
        self._update_resident_scatters(sim)
        self.canvas.draw_idle()

    def _update_resident_scatters(self, sim):
        """按 SEIR state 分桶 4 组, 各 scatter 用 σ 4 级填色 (体现情绪恢复 + SEIR 同时)."""
        by_state = {'S': [], 'E': [], 'I': [], 'R': []}
        for r in sim.residents:
            state = getattr(r, 'state', 'S')
            if state in by_state:
                by_state[state].append(r)
            else:
                by_state['S'].append(r)   # 兜底
        for state, bucket in by_state.items():
            sc = self.resident_scatters.get(state)
            if sc is None:
                continue
            if not bucket:
                sc.set_offsets(np.empty((0, 2)))
                continue
            xs = np.array([r.x for r in bucket])
            ys = np.array([r.y for r in bucket])
            face_colors = [sigma_color(float(getattr(r, 'stress_level', 0.0)))
                           for r in bucket]
            sc.set_offsets(np.c_[xs, ys])
            sc.set_facecolor(face_colors)


# ============================================================
# 主窗口
# ============================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('IJDRR Crowds_sim — 论文 §5 figure 互动面板')
        self.resize(1600, 950)

        central = QWidget()
        root = QVBoxLayout(central)

        root.addLayout(self._build_top_bar())
        root.addLayout(self._build_decision_bar())

        splitter = QSplitter(Qt.Horizontal)
        self.map_panel = MapPanel()
        self.chart_panel = ChartPanel()
        splitter.addWidget(self.map_panel)
        splitter.addWidget(self.chart_panel)
        splitter.setSizes([800, 800])
        root.addWidget(splitter, stretch=1)

        self.setCentralWidget(central)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel('未启动 — 选好城市/区/MML/graph 后按 ▶ 启动')
        self.status_bar.addWidget(self.status_label)
        self.repair_status_label = QLabel('事故/修复: 未启动')
        self.repair_status_label.setToolTip('统一事故状态、修复工作量与预计恢复时间将在此显示')
        self.status_bar.addPermanentWidget(self.repair_status_label)
        self.event_status_label = QLabel('事件: 未启动')
        self.status_bar.addPermanentWidget(self.event_status_label)

        self.worker = None
        self.sim_ref = None
        self._step_count = 0

        # 录制状态
        self._recording_gif = False
        self._gif_frames = []
        self._gif_step_interval = 5
        self._gif_max_frames = 200
        self._recording_data = False
        self._data_records = []

    # ============== 顶栏 ==============
    def _build_top_bar(self):
        bar = QHBoxLayout()

        bar.addWidget(QLabel('城市/区:'))
        self.cb_city = QComboBox()
        for c, d in CITY_OPTIONS:
            self.cb_city.addItem(f'{c} {d}', (c, d))
        bar.addWidget(self.cb_city)

        bar.addWidget(QLabel('居民数:'))
        self.sb_residents = QSpinBox()
        self.sb_residents.setRange(100, 5000)
        self.sb_residents.setSingleStep(100)
        self.sb_residents.setValue(800)
        bar.addWidget(self.sb_residents)

        bar.addWidget(QLabel('总步数:'))
        self.sb_total_steps = QSpinBox()
        self.sb_total_steps.setRange(0, 10000)
        self.sb_total_steps.setSingleStep(50)
        self.sb_total_steps.setValue(500)
        self.sb_total_steps.setToolTip(
            '到点自动停 (0 = 无限跑, 手动按 ⏹ 才停). '
            '500 步 ≈ 125h, 覆盖论文 §5 cascade 完整窗口 (TOTAL_STEPS=120 是 batch 默认, '
            'UI demo 用 400-600 比较合适).')
        bar.addWidget(self.sb_total_steps)

        self.chk_mml = QCheckBox('MML (默认)')
        self.chk_mml.setChecked(True)
        self.chk_mml.setToolTip('默认开 = 论文 §5 主形式; 关 = sigmoid legacy fallback (supplementary)')
        bar.addWidget(self.chk_mml)

        self.chk_road_graph = QCheckBox('use_road_graph')
        self.chk_road_graph.setChecked(True)
        self.chk_road_graph.setToolTip('graph-on 激活 flee 通道 (§5.1 IIA substitution)')
        bar.addWidget(self.chk_road_graph)

        bar.addSpacing(15)
        self.btn_start = QPushButton('▶ 启动')
        self.btn_start.clicked.connect(self.start_sim)
        self.btn_pause = QPushButton('⏸ 暂停')
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_stop = QPushButton('⏹ 停止')
        self.btn_stop.clicked.connect(self.stop_sim)
        bar.addWidget(self.btn_start)
        bar.addWidget(self.btn_pause)
        bar.addWidget(self.btn_stop)
        bar.addStretch()

        self.btn_save_charts = QPushButton('💾 保存图表')
        self.btn_save_charts.setToolTip('保存所有 figure 到 output_png/')
        self.btn_save_charts.clicked.connect(self.act_save_charts)
        self.btn_record_gif = QPushButton('🎬 录制 GIF')
        self.btn_record_gif.setCheckable(True)
        self.btn_record_gif.setToolTip('点击开始, 再点结束并保存到 output_gif/')
        self.btn_record_gif.clicked.connect(self.act_toggle_record_gif)
        self.btn_record_data = QPushButton('📊 录制数据')
        self.btn_record_data.setCheckable(True)
        self.btn_record_data.setToolTip('点击开始录制每步数据, 再点结束保存 CSV 到 trace_output_ui/')
        self.btn_record_data.clicked.connect(self.act_toggle_record_data)
        self.btn_save_events = QPushButton('🧾 导出事件')
        self.btn_save_events.setToolTip('导出当前事件序列到 trace_output_ui/events_*.csv，不关闭进行中事件')
        self.btn_save_events.clicked.connect(self.act_export_events)
        bar.addWidget(self.btn_save_charts)
        bar.addWidget(self.btn_record_gif)
        bar.addWidget(self.btn_record_data)
        bar.addWidget(self.btn_save_events)
        return bar

    # ============== 决策栏 ==============
    def _build_decision_bar(self):
        bar = QHBoxLayout()

        def mkbtn(text, handler, checkable=False, tooltip=''):
            b = QPushButton(text)
            b.setCheckable(checkable)
            if tooltip:
                b.setToolTip(tooltip)
            b.clicked.connect(handler)
            return b

        def mkslider(label_text, smin, smax, sdefault, scale, on_change, on_release,
                     fmt='{:.2f}'):
            row = QHBoxLayout()
            lbl = QLabel(f'{label_text}: ' + fmt.format(sdefault))
            lbl.setMinimumWidth(140)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(smin, smax)
            sl.setValue(int(round(sdefault * scale)))
            sl.setMinimumWidth(140)
            sl.valueChanged.connect(lambda v: on_change(v, lbl, fmt))
            sl.sliderReleased.connect(on_release)
            row.addWidget(lbl)
            row.addWidget(sl)
            container = QWidget()
            container.setLayout(row)
            return container, lbl, sl

        self._gov_city_districts = self._scan_map_city_districts()
        self._district_to_city = {
            district: city
            for city, districts in self._gov_city_districts.items()
            for district in districts
        }

        # 政府 Agent
        gb_gov = QGroupBox('政府 Agent (按区独立/可选范围)')
        gov_layout = QVBoxLayout(gb_gov)

        gov_scope_row = QHBoxLayout()
        gov_scope_row.addWidget(QLabel('控制城市:'))
        self.combo_gov_city = QComboBox()
        self.combo_gov_city.setToolTip('选择政府干预作用城市；全部区县表示当前仿真已加载的全部区县')
        self.combo_gov_city.currentIndexChanged.connect(self._on_gov_city_changed)
        gov_scope_row.addWidget(self.combo_gov_city)
        gov_scope_row.addWidget(QLabel('区县:'))
        self.combo_gov_district = QComboBox()
        self.combo_gov_district.setToolTip('选择政府干预作用区县；城市全部区县表示该城市当前已加载的区县')
        self.combo_gov_district.currentIndexChanged.connect(self._refresh_gov_controls_from_selection)
        gov_scope_row.addWidget(self.combo_gov_district)
        gov_layout.addLayout(gov_scope_row)

        cont, self.lbl_resource, self.slider_resource = mkslider(
            '政府资源倍数', 0, 200, 1.00, 100,
            on_change=lambda v, lbl, fmt: lbl.setText('政府资源倍数: ' + fmt.format(v / 100.0) + 'x'),
            on_release=self.act_apply_resource_multiplier,
        )
        gov_layout.addWidget(cont)

        gov_btn_row = QHBoxLayout()
        self.btn_warning = mkbtn('🚨 应急预警', self.act_toggle_warning, checkable=True,
                                 tooltip='事件1：按下方模式选择器，将本事件独立设为 AUTO / ON / OFF')
        self.btn_res_grid = mkbtn('⚡ 资源→电网', self.act_toggle_resource_grid, checkable=True,
                                   tooltip='事件2：按下方模式选择器，将本事件独立设为 AUTO / ON / OFF')
        self.btn_res_enterprise = mkbtn('🏭 资源→企业', self.act_toggle_resource_enterprise, checkable=True,
                                         tooltip='事件3：按下方模式选择器，将本事件独立设为 AUTO / ON / OFF')
        self.btn_res_resident = mkbtn('🏘 资源→居民', self.act_toggle_resource_resident, checkable=True,
                                        tooltip='事件4：按下方模式选择器，将本事件独立设为 AUTO / ON / OFF')
        self.btn_info = mkbtn('📢 舆情管理', self.act_toggle_info, checkable=True,
                               tooltip='事件5：按下方模式选择器，将本事件独立设为 AUTO / ON / OFF')
        for b in [self.btn_warning, self.btn_res_grid, self.btn_res_enterprise,
                  self.btn_res_resident, self.btn_info]:
            gov_btn_row.addWidget(b)
        gov_layout.addLayout(gov_btn_row)

        gov_mode_row = QHBoxLayout()
        gov_mode_row.addWidget(QLabel('点击事件设置为:'))
        self.combo_gov_event_mode = QComboBox()
        self.combo_gov_event_mode.addItem('强制开启 (ON)', 'on')
        self.combo_gov_event_mode.addItem('自动判定 (AUTO)', 'auto')
        self.combo_gov_event_mode.addItem('强制关闭 (OFF)', 'off')
        self.combo_gov_event_mode.setToolTip(
            '选择本次点击某个事件按钮时写入的独立状态；AUTO 只释放该事件，'
            '不会改变同一政府 Agent 的其他事件。')
        gov_mode_row.addWidget(self.combo_gov_event_mode)
        gov_mode_row.addStretch()
        gov_layout.addLayout(gov_mode_row)
        self._gov_button_base_labels = {
            self.btn_warning: '🚨 应急预警',
            self.btn_res_grid: '⚡ 资源→电网',
            self.btn_res_enterprise: '🏭 资源→企业',
            self.btn_res_resident: '🏘 资源→居民',
            self.btn_info: '📢 舆情管理',
        }
        bar.addWidget(gb_gov, stretch=3)

        # 区县停电控制
        gb_district_outage = QGroupBox('区县停电控制')
        district_outage_layout = QVBoxLayout(gb_district_outage)

        outage_scope_row = QHBoxLayout()
        outage_scope_row.addWidget(QLabel('控制城市:'))
        self.combo_outage_city = QComboBox()
        self.combo_outage_city.setToolTip('选择停电影响城市；全部区县表示当前仿真已加载的全部区县')
        self.combo_outage_city.currentIndexChanged.connect(self._on_outage_city_changed)
        outage_scope_row.addWidget(self.combo_outage_city)
        outage_scope_row.addWidget(QLabel('区县:'))
        self.combo_outage_district = QComboBox()
        self.combo_outage_district.setToolTip('选择停电影响区县；城市全部区县表示该城市当前已加载的区县')
        outage_scope_row.addWidget(self.combo_outage_district)
        district_outage_layout.addLayout(outage_scope_row)

        district_mode_row = QHBoxLayout()
        district_mode_row.addWidget(QLabel('停电模式:'))
        self.combo_district_outage_mode = QComboBox()
        self.combo_district_outage_mode.addItem('全停', 'full')
        self.combo_district_outage_mode.addItem('部分停电（按实际负荷切除）', 'partial')
        self.combo_district_outage_mode.currentIndexChanged.connect(self._on_district_outage_mode_changed)
        district_mode_row.addWidget(self.combo_district_outage_mode)
        district_mode_row.addWidget(QLabel('原因:'))
        self.combo_district_outage_cause = QComboBox()
        self._add_outage_causes(self.combo_district_outage_cause)
        district_mode_row.addWidget(self.combo_district_outage_cause)
        district_mode_row.addWidget(QLabel('种子:'))
        self.sb_outage_seed = QSpinBox()
        self.sb_outage_seed.setRange(0, 2_147_483_647)
        self.sb_outage_seed.setValue(42)
        self.sb_outage_seed.setToolTip(
            '同一城市、参数和种子应得到相同的切负荷对象与恢复顺序；'
            '全局事件也使用此种子选择受影响区域。')
        district_mode_row.addWidget(self.sb_outage_seed)
        district_outage_layout.addLayout(district_mode_row)

        cont, self.lbl_district_severity, self.slider_district_severity = mkslider(
            '实际切负荷比例', 0, 100, 50, 1,
            on_change=lambda v, lbl, fmt: lbl.setText('实际切负荷比例: ' + fmt.format(v) + '%'),
            on_release=lambda: None,
            fmt='{:.0f}',
        )
        self.slider_district_severity.setEnabled(False)
        district_outage_layout.addWidget(cont)

        self.btn_district_outage = mkbtn(
            '⚡ 触发所选区县停电',
            self.act_trigger_selected_outage,
            tooltip='按所选区县触发统一事故状态机；部分停电按实际加权负荷切除，不是随机整区全停'
        )
        district_outage_layout.addWidget(self.btn_district_outage)
        bar.addWidget(gb_district_outage, stretch=3)

        # 电网 Agent
        gb_grid = QGroupBox('电网 Agent (全市1个)')
        grid_layout = QVBoxLayout(gb_grid)

        cont, self.lbl_grid_init, self.slider_grid_init = mkslider(
            '电网积极性倍数', 0, 200, 1.00, 100,
            on_change=lambda v, lbl, fmt: lbl.setText('电网积极性倍数: ' + fmt.format(v / 100.0) + 'x'),
            on_release=self.act_apply_grid_params,
        )
        grid_layout.addWidget(cont)

        cont, self.lbl_grid_resp, self.slider_grid_resp = mkslider(
            '电网响应倍数', 0, 200, 1.00, 100,
            on_change=lambda v, lbl, fmt: lbl.setText('电网响应倍数: ' + fmt.format(v / 100.0) + 'x'),
            on_release=self.act_apply_grid_params,
        )
        grid_layout.addWidget(cont)

        cont, self.lbl_grid_lambda, self.slider_grid_lambda = mkslider(
            '故障传播率λ', 0, 100, 0.10, 100,
            on_change=lambda v, lbl, fmt: lbl.setText('故障传播率λ: ' + fmt.format(v / 100.0)),
            on_release=self.act_apply_grid_params,
            fmt='{:.2f}',
        )
        grid_layout.addWidget(cont)

        cont, self.lbl_grid_cap, self.slider_grid_cap = mkslider(
            '电网资源容量', 0, 100, 50, 1,
            on_change=lambda v, lbl, fmt: lbl.setText('电网资源容量: ' + fmt.format(v)),
            on_release=self.act_apply_grid_params,
            fmt='{:.0f}',
        )
        grid_layout.addWidget(cont)

        grid_btn_row = QHBoxLayout()
        self.btn_temp_station = mkbtn('🔌 临时供电站', self.act_toggle_temp_station, checkable=True,
                                       tooltip='事件: 架设临时供电站, 部分恢复关键负荷')
        self.btn_repair = mkbtn('🔧 强化抢修', self.act_toggle_repair, checkable=True,
                                 tooltip='在基线自动抢修上强化修复能力（默认 1.5×）；关闭后仍保留基线修复')
        grid_btn_row.addWidget(self.btn_temp_station)
        grid_btn_row.addWidget(self.btn_repair)
        grid_btn_row.addStretch()
        grid_layout.addLayout(grid_btn_row)
        bar.addWidget(gb_grid, stretch=3)

        # 全局事件
        gb_global = QGroupBox('全局事件')
        glob_layout = QVBoxLayout(gb_global)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel('停电模式:'))
        self.btn_mode_full = mkbtn('全停', lambda: self._set_outage_mode('full'), checkable=True)
        self.btn_mode_partial = mkbtn('部分停电（实际负荷）', lambda: self._set_outage_mode('partial'), checkable=True)
        self.btn_mode_full.setChecked(True)
        self._outage_mode = 'full'
        mode_row.addWidget(self.btn_mode_full)
        mode_row.addWidget(self.btn_mode_partial)
        glob_layout.addLayout(mode_row)

        cause_row = QHBoxLayout()
        cause_row.addWidget(QLabel('停电原因:'))
        self.combo_outage_cause = QComboBox()
        self.combo_outage_cause.setToolTip('全局压力测试触发停电时写入模型的 outage cause')
        self._add_outage_causes(self.combo_outage_cause)
        cause_row.addWidget(self.combo_outage_cause)
        glob_layout.addLayout(cause_row)

        cont, self.lbl_global_impact, self.slider_global_impact = mkslider(
            '影响区域比例', 1, 100, 50, 1,
            on_change=lambda v, lbl, fmt: lbl.setText('影响区域比例: ' + fmt.format(v) + '%'),
            on_release=lambda: None,
            fmt='{:.0f}',
        )
        glob_layout.addWidget(cont)

        cont, self.lbl_severity, self.slider_severity = mkslider(
            '切负荷比例', 0, 100, 50, 1,
            on_change=lambda v, lbl, fmt: lbl.setText('切负荷比例: ' + fmt.format(v) + '%'),
            on_release=lambda: None,
            fmt='{:.0f}',
        )
        self.slider_severity.setEnabled(False)
        glob_layout.addWidget(cont)

        self.btn_outage = mkbtn('⚡ 触发全局停电', self.act_trigger_outage,
                                tooltip='按原因、影响区域比例、模式和切负荷比例触发快速压力测试')
        self.btn_restore = mkbtn('💡 全城恢复供电', self.act_restore_power,
                                 tooltip='强制所有区域恢复供电')
        glob_layout.addWidget(self.btn_outage)
        glob_layout.addWidget(self.btn_restore)
        glob_layout.addStretch()
        bar.addWidget(gb_global, stretch=1)
        self._populate_scope_controls()
        return bar

    def _set_outage_mode(self, mode):
        self._outage_mode = mode
        self.btn_mode_full.setChecked(mode == 'full')
        self.btn_mode_partial.setChecked(mode == 'partial')
        self.slider_severity.setEnabled(mode == 'partial')

    def _on_district_outage_mode_changed(self, *_):
        mode = self.combo_district_outage_mode.currentData() or 'full'
        self.slider_district_severity.setEnabled(mode == 'partial')

    def _add_outage_causes(self, combo):
        combo.clear()
        for cause_key, cause_cfg in _load_outage_causes().items():
            combo.addItem(cause_cfg.get('name', cause_key), cause_key)

    def _scan_map_city_districts(self):
        cm = CityManager(map_data_dir=_resolve_map_dir())
        city_map = {}
        for city in cm.get_available_cities():
            districts = cm.get_districts(city)
            if districts:
                city_map[city] = districts
        return city_map

    def _populate_scope_controls(self):
        current_gov_city = self.combo_gov_city.currentData()
        current_gov_district = self.combo_gov_district.currentData()
        current_outage_city = self.combo_outage_city.currentData()
        current_outage_district = self.combo_outage_district.currentData()

        self._gov_city_districts = self._scan_map_city_districts()
        self._district_to_city = {
            district: city
            for city, districts in self._gov_city_districts.items()
            for district in districts
        }

        self._populate_city_combo(self.combo_gov_city, current_gov_city)
        self._populate_district_combo_for_city(
            self.combo_gov_city, self.combo_gov_district, current_gov_district)
        self._populate_city_combo(self.combo_outage_city, current_outage_city)
        self._populate_district_combo_for_city(
            self.combo_outage_city, self.combo_outage_district, current_outage_district)
        self._refresh_gov_controls_from_selection()

    def _populate_city_combo(self, combo, preferred=None):
        combo.blockSignals(True)
        combo.clear()
        combo.addItem('全部区县', ALL_GOV_DISTRICTS)
        for city in self._gov_city_districts.keys():
            combo.addItem(city, city)
        idx = combo.findData(preferred)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def _populate_district_combo_for_city(self, city_combo, district_combo, preferred=None):
        city = city_combo.currentData() if city_combo is not None else ALL_GOV_DISTRICTS
        district_combo.blockSignals(True)
        district_combo.clear()
        if city in (None, ALL_GOV_DISTRICTS):
            district_combo.addItem('全部区县', ALL_GOV_DISTRICTS)
            district_combo.setEnabled(False)
        else:
            district_combo.addItem(f'{city}全部区县', ALL_CITY_DISTRICTS)
            for district in self._gov_city_districts.get(city, []):
                district_combo.addItem(district, district)
            district_combo.setEnabled(True)
        idx = district_combo.findData(preferred)
        district_combo.setCurrentIndex(idx if idx >= 0 else 0)
        district_combo.blockSignals(False)

    def _on_gov_city_changed(self, *_):
        self._populate_district_combo_for_city(self.combo_gov_city, self.combo_gov_district)
        self._refresh_gov_controls_from_selection()

    def _on_outage_city_changed(self, *_):
        self._populate_district_combo_for_city(self.combo_outage_city, self.combo_outage_district)

    def _selected_targets_for_scope(self, sim, city_combo, district_combo):
        if sim is None or not hasattr(sim, 'gov_agents'):
            return []
        city = city_combo.currentData() if city_combo is not None else ALL_GOV_DISTRICTS
        district = district_combo.currentData() if district_combo is not None else ALL_GOV_DISTRICTS
        if city in (None, ALL_GOV_DISTRICTS):
            return list(sim.gov_agents.keys())
        if district in (None, ALL_CITY_DISTRICTS):
            city_districts = set(self._gov_city_districts.get(city, []))
            return [d for d in sim.gov_agents.keys() if d in city_districts]
        return [district] if district in sim.gov_agents else []

    def _selected_gov_targets(self, sim=None):
        return self._selected_targets_for_scope(
            sim or getattr(self, 'sim_ref', None), self.combo_gov_city, self.combo_gov_district)

    def _selected_outage_targets(self, sim=None):
        return self._selected_targets_for_scope(
            sim or getattr(self, 'sim_ref', None), self.combo_outage_city, self.combo_outage_district)

    def _selected_scope_text(self, city_combo, district_combo):
        city_text = city_combo.currentText() if city_combo is not None else '全部区县'
        if district_combo is None or not district_combo.isEnabled():
            return city_text
        district_text = district_combo.currentText()
        if district_combo.currentData() == ALL_CITY_DISTRICTS:
            return district_text
        return f'{city_text}-{district_text}'

    def _selected_gov_scope_text(self):
        return self._selected_scope_text(self.combo_gov_city, self.combo_gov_district)

    def _selected_outage_scope_text(self):
        return self._selected_scope_text(self.combo_outage_city, self.combo_outage_district)

    def _refresh_gov_controls_from_selection(self, *_):
        sim = getattr(self, 'sim_ref', None)
        if sim is None or not hasattr(sim, 'gov_agents'):
            return
        targets = self._selected_gov_targets(sim)
        govs = [sim.gov_agents[d] for d in targets if d in sim.gov_agents]
        if not govs:
            return

        for event_key, attr, btn in [
            ('emergency_warning', 'manual_emergency_warning', self.btn_warning),
            ('resource_to_grid', 'manual_resource_to_grid', self.btn_res_grid),
            ('resource_to_enterprise', 'manual_resource_to_enterprise', self.btn_res_enterprise),
            ('resource_to_resident', 'manual_resource_to_resident', self.btn_res_resident),
            ('public_opinion', 'manual_public_opinion', self.btn_info),
        ]:
            modes = {self._gov_event_mode(g, event_key, attr) for g in govs}
            display_mode = next(iter(modes)) if len(modes) == 1 else 'mixed'
            self._set_gov_button_display(btn, display_mode)

        mults = []
        for district in targets:
            gov = sim.gov_agents.get(district)
            base = getattr(self, '_gov_base', {}).get(district, {})
            base_cap = float(base.get('base_resource_capacity', 100.0) or 100.0)
            if gov is not None and base_cap > 0:
                mults.append(float(getattr(gov, 'base_resource_capacity', base_cap)) / base_cap)
        if mults:
            mult = max(0.0, min(2.0, sum(mults) / len(mults)))
            self.slider_resource.blockSignals(True)
            self.slider_resource.setValue(int(round(mult * 100)))
            self.slider_resource.blockSignals(False)
            self.lbl_resource.setText(f'政府资源倍数: {mult:.2f}x')

    # ============== 仿真控制 ==============
    def start_sim(self):
        if self.worker is not None:
            return
        city_data = self.cb_city.currentData()
        if not city_data:
            self.status_label.setText('未选城市')
            return
        city, district = city_data
        self.worker = SimulationWorker(
            city=city, district=district,
            n_residents=self.sb_residents.value(),
            n_enterprises=30,
            use_road_graph=self.chk_road_graph.isChecked(),
            use_mml=self.chk_mml.isChecked(),
            total_steps=self.sb_total_steps.value(),
        )
        self.worker.step_done.connect(self.on_step_done)
        self.worker.init_done.connect(self.on_init_done)
        self.worker.error.connect(lambda msg: self.status_label.setText(f'错误: {msg}'))
        self.worker.start()
        self.status_label.setText(
            f'初始化中... {city}/{district} '
            f'MML={"on" if self.chk_mml.isChecked() else "off"} '
            f'graph={"on" if self.chk_road_graph.isChecked() else "off"}')

    def toggle_pause(self):
        if self.worker is None:
            return
        self.worker._paused = not self.worker._paused
        self.btn_pause.setText('▶ 继续' if self.worker._paused else '⏸ 暂停')

    def stop_sim(self):
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait(2000)
            self.worker = None
        self.status_label.setText('已停止')

    def on_init_done(self, sim):
        self.sim_ref = sim
        self._gov_base = {
            d: {
                'initiative': g.initiative,
                'response': g.response,
                'base_resource_capacity': getattr(g, 'base_resource_capacity', 100.0),
            }
            for d, g in sim.gov_agents.items()
        }
        self._grid_base = {
            'initiative': sim.grid.initiative,
            'response': sim.grid.response,
            'lambda_prop': getattr(sim.grid, 'lambda_prop', 0.1),
            'base_resource_capacity': getattr(sim.grid, 'base_resource_capacity', 50.0),
        }
        self._populate_scope_controls()
        self.map_panel.init_map(sim)
        self.status_label.setText('运行中')
        self.repair_status_label.setText('事故/修复: 正常供电')

    def _format_repair_status(self, outage, current_step, total_steps, last_error='', last_warning=''):
        """Keep repair-state semantics visible without relying on map colour alone."""
        if last_error and (not outage or not outage.get('active', False)):
            return f'事故预检失败: {last_error}', last_error
        if not outage or not outage.get('active', False):
            text = '事故/修复: 正常供电'
            detail = '当前没有活动的区县停电事故。'
            if last_warning:
                text += ' | 数据预警'
                detail += f' 数据预警={last_warning}'
            return text, detail

        eta_hours = _safe_float(outage.get('eta_hours', float('inf')), float('inf'))
        eta_text = f'{eta_hours:.1f}h' if math.isfinite(eta_hours) else '无可用容量'
        estimate_step = outage.get('estimated_recovery_step')
        estimate_text = f'步≈{estimate_step}' if estimate_step is not None else '步≈未知'
        if total_steps and estimate_step is not None and estimate_step > total_steps:
            estimate_text += '（超出本次窗口）'
        total_work = _safe_float(outage.get('total_work', 0.0))
        done_work = _safe_float(outage.get('work_done', 0.0))
        capacity = _safe_float(outage.get('current_capacity', 0.0))
        wait_hours = (_safe_float(outage.get('detection_remaining_hours', 0.0)) +
                      _safe_float(outage.get('mobilization_remaining_hours', 0.0)))
        compact = (
            f"事故={outage.get('phase', 'active')} | W={done_work:.1f}/{total_work:.1f} "
            f"({outage.get('progress', 0.0):.0%}) | C={capacity:.2f}/h | "
            f"剩余={eta_text}, {estimate_text} | 切负荷="
            f"{outage.get('requested_shed_ratio', 0.0):.0%}/"
            f"{outage.get('realized_shed_ratio', 0.0):.0%} | "
            f"区/负荷={outage.get('affected_zone_count', 0)}/"
            f"{outage.get('affected_load_count', 0)}"
        )
        detail = (
            f"{compact} | 等待={wait_hours:.1f}h | 请求/实际切负荷="
            f"{outage.get('requested_shed_ratio', 0.0):.0%}/"
            f"{outage.get('realized_shed_ratio', 0.0):.0%} | "
            f"影响区={outage.get('affected_zone_count', 0)}、负荷={outage.get('affected_load_count', 0)}"
        )
        if last_warning:
            compact += ' | 数据预警'
            detail += f' | 数据预警={last_warning}'
        return compact, detail

    def on_step_done(self, m):
        self._step_count = m['step']
        if self.worker is None or self.sim_ref is None:
            return
        if self._step_count % 2 == 0:
            self.chart_panel.update_data(self.worker)
        if self._step_count % 5 == 0:
            self.map_panel.update_map(self.sim_ref)

        if self._recording_data:
            self._data_records.append(m)

        if self._recording_gif and self._step_count % self._gif_step_interval == 0:
            if len(self._gif_frames) < self._gif_max_frames:
                frame = self._capture_frame()
                if frame is not None:
                    self._gif_frames.append(frame)

        seir = m.get('seir', {})
        seir_str = (f"S{seir.get('S',0):.0%}/E{seir.get('E',0):.0%}/"
                    f"I{seir.get('I',0):.0%}/R{seir.get('R',0):.0%}")
        rec_str = ''
        if self._recording_gif:
            rec_str += f' | 🎬{len(self._gif_frames)}帧'
        if self._recording_data:
            rec_str += f' | 📊{len(self._data_records)}行'
        total = self.worker.total_steps if self.worker is not None else 0
        step_label = f"{m['step']}/{total}" if total > 0 else str(m['step'])

        outage = m.get('outage', {}) or {}
        repair_text, repair_tooltip = self._format_repair_status(
            outage, m['step'], total, m.get('outage_last_error', ''),
            m.get('outage_last_warning', ''))
        self.repair_status_label.setText(repair_text)
        self.repair_status_label.setToolTip(repair_tooltip)

        self.status_label.setText(
            f"步={step_label} | t={m['t_hour']:.1f}h | "
            f"舆情={m.get('public_opinion_pressure', m['P']):.2f} | "
            f"系统求助={m.get('system_help_pressure', m['P']):.2f} | "
            f"σ={m['stress']:.2f} | 恐慌={m['panic']:.2f} | "
            f"flee={m['flee_ratio']:.2f} | herd={m['herd_ratio']:.2f} | "
            f"zone停电={m['blackout']:.0%} | {seir_str}{rec_str}"
        )
        gov = m.get('gov_events', {})
        ev = m.get('event_stats', {})
        summary = m.get('last_event_summary', {}) or {}
        denom = max(1, int(gov.get('district_total', 0) or 0))
        self.event_status_label.setText(
            f"政府事件: 预警{gov.get('warning', 0)}/{denom} "
            f"居民资源{gov.get('resource_resident', 0)}/{denom} "
            f"舆情{gov.get('opinion', 0)}/{denom} | "
            f"event5区={m.get('event5_district_ratio', 0.0):.0%} "
            f"居民={m.get('event5_resident_ratio', 0.0):.0%} | "
            f"事件 active/total={ev.get('active', 0)}/{ev.get('total', 0)} | "
            f"summary ΔE={summary.get('total_emotion_change', 0.0):+.2f} "
            f"Δpanic={summary.get('total_panic_change', 0.0):+.2f} "
            f"repair+={summary.get('total_repair_boost', 0.0):.2f}"
        )

    # ============== 保存 / 录制 ==============
    def _capture_frame(self):
        try:
            from PIL import Image
            chart_buf = io.BytesIO()
            map_buf = io.BytesIO()
            self.chart_panel.fig.savefig(chart_buf, format='png', dpi=60, bbox_inches='tight')
            self.map_panel.fig.savefig(map_buf, format='png', dpi=60, bbox_inches='tight')
            chart_buf.seek(0); map_buf.seek(0)
            img_chart = Image.open(chart_buf).convert('RGB')
            img_map = Image.open(map_buf).convert('RGB')
            h = max(img_chart.height, img_map.height)
            ratio_map = h / img_map.height
            ratio_chart = h / img_chart.height
            new_map = img_map.resize((int(img_map.width * ratio_map), h))
            new_chart = img_chart.resize((int(img_chart.width * ratio_chart), h))
            combined = Image.new('RGB', (new_map.width + new_chart.width, h), 'white')
            combined.paste(new_map, (0, 0))
            combined.paste(new_chart, (new_map.width, 0))
            return combined
        except Exception as e:
            print(f'[capture_frame error] {e}')
            return None

    def act_save_charts(self):
        if self.sim_ref is None:
            self.status_label.setText('未启动, 无图可保存')
            return
        _ensure_dir(OUT_PNG_DIR)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        step = self.sim_ref.step_count
        chart_path = os.path.join(OUT_PNG_DIR, f'charts_step{step:05d}_{ts}.png')
        map_path = os.path.join(OUT_PNG_DIR, f'map_step{step:05d}_{ts}.png')
        try:
            self.chart_panel.fig.savefig(chart_path, dpi=120, bbox_inches='tight')
            self.map_panel.fig.savefig(map_path, dpi=120, bbox_inches='tight')
            self.status_label.setText(f'图表已保存到 output_png/ step={step}')
            print(f'[save_charts] {chart_path}')
            print(f'[save_charts] {map_path}')
        except Exception as e:
            self.status_label.setText(f'保存失败: {e}')
            traceback.print_exc()

    def act_toggle_record_gif(self):
        if self.btn_record_gif.isChecked():
            self._recording_gif = True
            self._gif_frames = []
            self.btn_record_gif.setText('🎬 录制中 (再点结束)')
            self.status_label.setText('GIF 开始录制 (每 5 步一帧, 上限 200 帧)')
        else:
            self._recording_gif = False
            self.btn_record_gif.setText('🎬 录制 GIF')
            if not self._gif_frames:
                self.status_label.setText('未捕获任何帧')
                return
            _ensure_dir(OUT_GIF_DIR)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            gif_path = os.path.join(OUT_GIF_DIR, f'sim_{ts}.gif')
            try:
                imgs = self._gif_frames
                imgs[0].save(gif_path, save_all=True, append_images=imgs[1:],
                             duration=200, loop=0, optimize=True)
                self.status_label.setText(f'GIF 已保存({len(imgs)}帧) → {gif_path}')
                print(f'[save_gif] {gif_path} ({len(imgs)} 帧)')
            except Exception as e:
                self.status_label.setText(f'GIF 保存失败: {e}')
                traceback.print_exc()
            self._gif_frames = []

    def act_toggle_record_data(self):
        if self.btn_record_data.isChecked():
            self._recording_data = True
            self._data_records = []
            self.btn_record_data.setText('📊 录制中 (再点结束)')
            self.status_label.setText('数据开始录制 (每步)')
        else:
            self._recording_data = False
            self.btn_record_data.setText('📊 录制数据')
            if not self._data_records:
                self.status_label.setText('未录到任何数据')
                return
            _ensure_dir(OUT_TRACE_DIR)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            csv_path = os.path.join(OUT_TRACE_DIR, f'trace_{ts}.csv')
            try:
                with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
                    w = csv.writer(f)
                    # v2: P_hist 已明确命名为系统综合求助压力；动态舆情单独记录。
                    # emotion_display 是 UI floor，仅供演示，不应作为论文原始指标。
                    w.writerow([
                        'schema_version', 'step', 't_hour',
                        'system_help_pressure', 'public_opinion_pressure',
                        'system_help_emotion_component',
                        'system_help_enterprise_component',
                        'system_help_critical_component', 'system_help_component_source',
                        'emotion_raw', 'emotion_display', 'stress', 'panic',
                        'flee_ratio', 'herd_ratio', 'recovery_rate', 'blackout_ratio',
                        'gov_R_deploy', 'seir_S', 'seir_E', 'seir_I', 'seir_R',
                        'outage_event_id', 'outage_state', 'outage_mode', 'outage_cause',
                        'outage_seed', 'outage_active_districts',
                        'outage_requested_shed_ratio', 'outage_realized_shed_ratio',
                        'outage_affected_zone_count', 'outage_affected_load_count',
                        'outage_detection_remaining_hours',
                        'outage_mobilization_remaining_hours',
                        'outage_total_work', 'outage_work_done', 'outage_remaining_work',
                        'outage_current_capacity', 'outage_progress', 'outage_eta_hours',
                        'outage_estimated_recovery_step', 'outage_scope',
                        'gov_warning_active', 'gov_resource_grid_active',
                        'gov_resource_enterprise_active',
                        'gov_resource_resident_active', 'gov_opinion_active',
                        'event_total', 'event_active',
                        'event5_district_ratio', 'event5_resident_ratio',
                        'ui_action_count', 'ui_last_action', 'ui_last_action_step',
                    ])
                    for r in self._data_records:
                        seir = r.get('seir', {})
                        raw_e = r.get('emotion_raw', r.get('emotion', 0.0))
                        disp_e = r.get('emotion_display', r.get('emotion', 0.0))
                        gov = r.get('gov_events', {})
                        ev = r.get('event_stats', {})
                        outage = r.get('outage', {}) or {}
                        w.writerow([
                            'ui_trace_v2', r['step'], _csv_number(r['t_hour'], 2),
                            _csv_number(r.get('system_help_pressure', r.get('P', 0.0))),
                            _csv_number(r.get('public_opinion_pressure', r.get('P', 0.0))),
                            _csv_number(r.get('system_help_emotion_component', 0.0)),
                            _csv_number(r.get('system_help_enterprise_component', 0.0)),
                            _csv_number(r.get('system_help_critical_component', 0.0)),
                            r.get('system_help_component_source', ''),
                            _csv_number(raw_e), _csv_number(disp_e),
                            _csv_number(r['stress']), _csv_number(r['panic']),
                            _csv_number(r['flee_ratio']), _csv_number(r['herd_ratio']),
                            _csv_number(r['recovery']), _csv_number(r['blackout']),
                            _csv_number(r['R']),
                            _csv_number(seir.get('S', 0)), _csv_number(seir.get('E', 0)),
                            _csv_number(seir.get('I', 0)), _csv_number(seir.get('R', 0)),
                            outage.get('event_id', ''), outage.get('phase', ''),
                            outage.get('mode', r.get('outage_mode', '')),
                            outage.get('cause', r.get('outage_cause', '')),
                            outage.get('seed', ''), outage.get('state_count', 0),
                            _csv_number(outage.get('requested_shed_ratio', r.get('outage_severity', 0.0))),
                            _csv_number(outage.get('realized_shed_ratio', 0.0)),
                            outage.get('affected_zone_count', 0), outage.get('affected_load_count', 0),
                            _csv_number(outage.get('detection_remaining_hours', 0.0)),
                            _csv_number(outage.get('mobilization_remaining_hours', 0.0)),
                            _csv_number(outage.get('total_work', 0.0)),
                            _csv_number(outage.get('work_done', 0.0)),
                            _csv_number(outage.get('remaining_work', 0.0)),
                            _csv_number(outage.get('current_capacity', 0.0)),
                            _csv_number(outage.get('progress', 0.0)),
                            _csv_number(outage.get('eta_hours', 0.0)),
                            outage.get('estimated_recovery_step', ''),
                            r.get('outage_scope', ''),
                            gov.get('warning', 0), gov.get('resource_grid', 0),
                            gov.get('resource_enterprise', 0), gov.get('resource_resident', 0),
                            gov.get('opinion', 0), ev.get('total', 0), ev.get('active', 0),
                            _csv_number(r.get('event5_district_ratio', 0.0)),
                            _csv_number(r.get('event5_resident_ratio', 0.0)),
                            r.get('ui_action_count', 0), r.get('ui_last_action', ''),
                            r.get('ui_last_action_step', 0),
                        ])
                self._export_ui_action_log(ts)
                self.status_label.setText(f'数据已保存({len(self._data_records)}行) → {csv_path}')
                print(f'[save_data] {csv_path} ({len(self._data_records)} 行)')
            except Exception as e:
                self.status_label.setText(f'数据保存失败: {e}')
                traceback.print_exc()
            self._data_records = []

    def _export_ui_action_log(self, timestamp):
        """Persist UI commands separately from time-series rows for audit/replay."""
        action_log = getattr(self.sim_ref, 'ui_action_log', []) if self.sim_ref is not None else []
        if not isinstance(action_log, list) or not action_log:
            return None
        path = os.path.join(OUT_TRACE_DIR, f'ui_actions_{timestamp}.csv')
        base_fields = ['schema_version', 'step', 't_hour', 'action', 'scope']
        extra_fields = sorted({
            str(key) for record in action_log if isinstance(record, Mapping)
            for key in record.keys() if key not in base_fields
        })
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=base_fields + extra_fields)
            writer.writeheader()
            for record in action_log:
                if not isinstance(record, Mapping):
                    continue
                row = {}
                for key in base_fields + extra_fields:
                    value = record.get(key, '')
                    if isinstance(value, (dict, list, tuple, set)):
                        value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
                    row[key] = value
                writer.writerow(row)
        return path

    def act_export_events(self):
        if self.sim_ref is None:
            self.status_label.setText('未启动, 无事件可导出')
            return
        _ensure_dir(OUT_TRACE_DIR)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        step = getattr(self.sim_ref, 'step_count', 0)
        csv_path = os.path.join(OUT_TRACE_DIR, f'events_step{step:05d}_{ts}.csv')
        try:
            count = self.sim_ref.export_events_to_csv_with_names(csv_path, finalize=False)
            action_path = self._export_ui_action_log(ts)
            action_hint = f'；UI动作日志 → {action_path}' if action_path else ''
            self.status_label.setText(f'事件已导出({count}条) → {csv_path}{action_hint}')
            print(f'[save_events] {csv_path} ({count} 条)')
        except Exception as e:
            self.status_label.setText(f'事件导出失败: {e}')
            traceback.print_exc()

    # ============== 决策动作 ==============
    def _mark(self, label=''):
        if self.worker is not None:
            self.chart_panel.mark_intervention(len(self.worker.opinion_hist), label)

    def _append_ui_action_log(self, sim, action, scope='', **details):
        """Append an auditable UI command on the simulation thread."""
        action_log = getattr(sim, 'ui_action_log', None)
        if not isinstance(action_log, list):
            action_log = []
            sim.ui_action_log = action_log
        record = {
            'schema_version': 'ui_action_v2',
            'step': int(getattr(sim, 'step_count', 0)),
            't_hour': _safe_float(getattr(sim, 'current_hour', 0.0)),
            'action': action,
            'scope': scope,
        }
        record.update(details)
        action_log.append(record)
        sim.last_ui_action = record
        return record

    def _record_outage_command(self, sim, scope, mode, cause, shed_ratio, **extra):
        payload = {
            'scope': scope,
            'mode': mode,
            'cause': cause,
            # Keep the old field for reader compatibility, but make the v2
            # semantic explicit: this is a requested *load-shed* ratio.
            'severity_ratio': float(shed_ratio),
            'requested_shed_ratio': float(shed_ratio),
            'step': getattr(sim, 'step_count', 0),
        }
        payload.update(extra)
        sim.last_ui_outage_command = payload

    @staticmethod
    def _requested_shed_ratio(mode, slider_value):
        return 1.0 if mode == 'full' else max(0.0, min(1.0, _safe_float(slider_value)))

    def _trigger_outage_scenario(self, sim, district, mode, cause, shed_ratio,
                                 seed, scope_zone_ids=None):
        """Use the v2 public API; use legacy routing only for an older checkout."""
        preflight = getattr(sim, 'validate_outage_preflight', None)
        if callable(preflight):
            try:
                report = preflight(district)
                warnings = list((report or {}).get('warnings', []) or [])
                sim.last_ui_outage_warning = '; '.join(map(str, warnings))
            except Exception as exc:
                # The trigger remains the authoritative validator.  A UI-only
                # inspection error must not hide a valid simulation command.
                sim.last_ui_outage_warning = f'preflight display unavailable: {exc}'
        trigger = getattr(sim, 'trigger_outage_scenario', None)
        if callable(trigger):
            return trigger(
                district=district,
                mode=mode,
                cause=cause,
                shed_ratio=shed_ratio,
                damage_level=None,
                seed=seed,
                scope_zone_ids=scope_zone_ids,
            )

        legacy = getattr(sim, 'trigger_independent_district_outages', None)
        if not callable(legacy):
            raise RuntimeError('当前仿真缺少 trigger_outage_scenario() 统一停电接口')
        # Compatibility only: do not directly mutate zone_status in the UI.
        legacy({
            district: {
                'enabled': True,
                'mode': mode,
                'cause': cause,
                'severity_ratio': shed_ratio,
                'use_all_zones': scope_zone_ids is None,
                'selected_zones': list(scope_zone_ids or []),
            }
        })
        return {'compatibility_path': 'trigger_independent_district_outages'}

    def _force_restore_outage(self, sim, district=None):
        """Use the v2 public restore operation and retain a safe old-engine fallback."""
        restore = getattr(sim, 'force_restore_outage', None)
        if callable(restore):
            return restore(district=district)

        legacy_restore = getattr(sim, '_restore_district_power', None)
        if callable(legacy_restore):
            return legacy_restore()

        # Last-resort compatibility for a pre-v2 engine that has no public
        # restore method.  This branch is intentionally isolated from normal UI.
        for zone_id in list((getattr(sim, 'zone_status', {}) or {}).keys()):
            sim.zone_status[zone_id] = True
            if hasattr(sim, 'zone_duration'):
                sim.zone_duration[zone_id] = 0
        if hasattr(sim, 'zone_outage_cause'):
            sim.zone_outage_cause.clear()
        if hasattr(sim, 'partial_outage_entities'):
            sim.partial_outage_entities.clear()
        for resident in getattr(sim, 'residents', []):
            resident.powered = True
            resident._is_load_shed = False
        for enterprise in getattr(sim, 'enterprises', []):
            enterprise.powered = True
            enterprise._is_load_shed = False
        for node in getattr(sim, 'csv_nodes', []):
            node['powered'] = True
            node['outage_duration'] = 0
        if hasattr(sim, 'district_outage_mode'):
            sim.district_outage_mode = None
        if hasattr(sim, 'district_repair_started'):
            sim.district_repair_started = False
        if hasattr(sim, 'district_repair_progress'):
            sim.district_repair_progress = 0.0
        return {'compatibility_path': 'inline_restore'}

    def _group_zones_by_district(self, sim, zones):
        grouped = defaultdict(list)
        fallback = next(iter(getattr(sim, 'gov_agents', {}).keys()), None)
        for zone_id in zones:
            district = getattr(sim, 'zone_to_district', {}).get(zone_id) or fallback
            if district:
                grouped[district].append(zone_id)
        return grouped

    def act_trigger_selected_outage(self):
        if self.worker is None or self.sim_ref is None:
            return
        targets = self._selected_outage_targets(self.sim_ref)
        if not targets:
            self.status_label.setText('未选中当前仿真已加载的区县')
            return
        mode = self.combo_district_outage_mode.currentData() or 'full'
        cause = self.combo_district_outage_cause.currentData() or 'equipment_failure'
        shed_ratio = self._requested_shed_ratio(
            mode, self.slider_district_severity.value() / 100.0)
        if mode == 'partial' and shed_ratio <= 0.0:
            self.status_label.setText('实际切负荷比例为 0%，未创建停电事故')
            return
        if mode == 'partial' and shed_ratio >= 1.0:
            mode = 'full'
        scope = self._selected_outage_scope_text()
        seed = int(self.sb_outage_seed.value())

        def _do(sim):
            results = {}
            try:
                for district in targets:
                    results[district] = self._trigger_outage_scenario(
                        sim, district, mode, cause, shed_ratio, seed, scope_zone_ids=None)
            except Exception as exc:
                message = f'停电事故预检拒绝: {exc}'
                sim.last_ui_outage_error = message
                self._append_ui_action_log(
                    sim, 'trigger_outage_scenario', scope, districts=list(targets),
                    mode=mode, cause=cause, requested_shed_ratio=shed_ratio,
                    seed=seed, result='rejected', error=message)
                if self.worker is not None:
                    self.worker.error.emit(message)
                return
            sim.last_ui_outage_error = ''
            self._record_outage_command(
                sim, scope, mode, cause, shed_ratio,
                command='district_outage', targets=','.join(targets))
            self._append_ui_action_log(
                sim, 'trigger_outage_scenario', scope,
                districts=list(targets), mode=mode, cause=cause,
                requested_shed_ratio=shed_ratio, seed=seed,
                scope_zone_ids='all_district_zones', results=results,
                preflight_warning=str(getattr(sim, 'last_ui_outage_warning', '') or ''),
            )

        self.worker.queue_action(_do)
        cause_label = self.combo_district_outage_cause.currentText()
        tag = f'{scope} 停电 {mode}/{cause_label}'
        if mode == 'partial':
            tag += f' 实际负荷{int(shed_ratio * 100)}%'
        self._mark(tag)

    def act_trigger_outage(self):
        if self.worker is None:
            return
        mode = getattr(self, '_outage_mode', 'full')
        cause = self.combo_outage_cause.currentData() or 'equipment_failure'
        shed_ratio = self._requested_shed_ratio(mode, self.slider_severity.value() / 100.0)
        if mode == 'partial' and shed_ratio <= 0.0:
            self.status_label.setText('实际切负荷比例为 0%，未创建停电事故')
            return
        if mode == 'partial' and shed_ratio >= 1.0:
            mode = 'full'
        impact_ratio = self.slider_global_impact.value() / 100.0
        seed = int(self.sb_outage_seed.value())

        def _do(sim):
            try:
                partial_zones = set(getattr(sim, 'partial_outage_entities', {}).keys())
                caused_zones = {
                    zone_id for zone_id, zone_cause
                    in (getattr(sim, 'zone_outage_cause', {}) or {}).items()
                    if zone_cause
                }
                zone_fractions = getattr(sim, 'zone_power_fraction', {}) or {}
                if not isinstance(zone_fractions, Mapping):
                    zone_fractions = {}
                available_zones = [
                    z for z, powered in sim.zone_status.items()
                    if powered and z not in partial_zones and z not in caused_zones
                    and _safe_float(zone_fractions.get(z, 1.0), 1.0) >= 1.0 - 1e-9
                ]
                if not available_zones:
                    self._record_outage_command(
                        sim, 'global', mode, cause, shed_ratio,
                        command='global_outage', impact_ratio=impact_ratio, target_count=0)
                    self._append_ui_action_log(
                        sim, 'trigger_outage_scenario', 'global', mode=mode, cause=cause,
                        requested_shed_ratio=shed_ratio, impact_ratio=impact_ratio,
                        seed=seed, target_count=0, result='no_available_zones',
                    )
                    return
                target_count = max(1, int(np.ceil(len(available_zones) * impact_ratio)))
                target_count = min(target_count, len(available_zones))
                selected_zones = random.Random(seed).sample(
                    sorted(available_zones, key=str), target_count)
                grouped = self._group_zones_by_district(sim, selected_zones)
                results = {}
                for district in sorted(grouped):
                    results[district] = self._trigger_outage_scenario(
                        sim, district, mode, cause, shed_ratio, seed,
                        scope_zone_ids=grouped[district])
            except Exception as exc:
                message = f'停电事故预检拒绝: {exc}'
                sim.last_ui_outage_error = message
                self._append_ui_action_log(
                    sim, 'trigger_outage_scenario', 'global', mode=mode, cause=cause,
                    requested_shed_ratio=shed_ratio, impact_ratio=impact_ratio,
                    seed=seed, result='rejected', error=message)
                if self.worker is not None:
                    self.worker.error.emit(message)
                return
            sim.last_ui_outage_error = ''
            self._record_outage_command(
                sim, 'global', mode, cause, shed_ratio,
                command='global_outage',
                impact_ratio=impact_ratio,
                target_count=target_count,
                selected_zones=list(selected_zones))
            self._append_ui_action_log(
                sim, 'trigger_outage_scenario', 'global', districts=sorted(grouped),
                mode=mode, cause=cause, requested_shed_ratio=shed_ratio,
                impact_ratio=impact_ratio, seed=seed,
                scope_zone_ids=list(selected_zones), results=results,
                preflight_warning=str(getattr(sim, 'last_ui_outage_warning', '') or ''),
            )

        self.worker.queue_action(_do)
        cause_label = self.combo_outage_cause.currentText()
        tag = f'全局停电 {mode}/{cause_label} 影响{int(impact_ratio * 100)}%'
        if mode == 'partial':
            tag += f' 实际负荷{int(shed_ratio * 100)}%'
        self._mark(tag)

    def act_restore_power(self):
        if self.worker is None:
            return

        def _do(sim):
            result = self._force_restore_outage(sim)
            self._record_outage_command(
                sim, 'restore', 'restore', '', 0.0, command='restore_power')
            self._append_ui_action_log(
                sim, 'force_restore_outage', 'global', result=result)
        self.worker.queue_action(_do)
        self._mark('强制恢复供电')

    def act_apply_resource_multiplier(self):
        if self.worker is None or self.sim_ref is None:
            return
        mult = self.slider_resource.value() / 100.0
        gov_base = getattr(self, '_gov_base', {})
        targets = self._selected_gov_targets(self.sim_ref)
        if not targets:
            self.status_label.setText('未选中当前仿真已加载的政府 Agent')
            return
        scope = self._selected_gov_scope_text()

        def _do(sim):
            for d in targets:
                gov = sim.gov_agents.get(d)
                if gov is None:
                    continue
                base = gov_base.get(d, {
                    'initiative': 0.5,
                    'response': 1.0,
                    'base_resource_capacity': 100.0,
                })
                gov.initiative = max(0.0, min(1.0, base['initiative'] * mult))
                gov.response = max(0.0, min(2.0, base['response'] * mult))
                base_cap = float(base.get('base_resource_capacity', 100.0) or 100.0)
                gov.base_resource_capacity = max(0.0, min(200.0, base_cap * mult))
                gov.current_resource_level = gov.base_resource_capacity
            self._append_ui_action_log(
                sim, 'set_government_resource_multiplier', scope,
                districts=list(targets), multiplier=mult)
        self.worker.queue_action(_do)
        self._mark(f'{scope} 资源×{mult:.2f}')

    def act_toggle_info(self):
        if self.worker is None:
            return
        event_mode = self._selected_gov_event_mode()
        targets = self._selected_gov_targets(self.sim_ref)
        if not targets:
            self.status_label.setText('未选中当前仿真已加载的政府 Agent')
            return
        scope = self._selected_gov_scope_text()

        def _do(sim):
            for d in targets:
                gov = sim.gov_agents.get(d)
                if gov is None:
                    continue
                self._set_gov_event_mode(
                    gov, 'public_opinion', 'manual_public_opinion', event_mode)
            self._append_ui_action_log(
                sim, 'set_government_event_mode', scope,
                districts=list(targets), event='public_opinion', mode=event_mode)
        self.worker.queue_action(_do)
        self._set_gov_button_display(self.btn_info, event_mode)
        self._mark(f'{scope} 舆情管理 {event_mode.upper()}')

    def act_toggle_warning(self):
        if self.worker is None:
            return
        event_mode = self._selected_gov_event_mode()
        targets = self._selected_gov_targets(self.sim_ref)
        if not targets:
            self.status_label.setText('未选中当前仿真已加载的政府 Agent')
            return
        scope = self._selected_gov_scope_text()

        def _do(sim):
            for d in targets:
                gov = sim.gov_agents.get(d)
                if gov is None:
                    continue
                self._set_gov_event_mode(
                    gov, 'emergency_warning', 'manual_emergency_warning', event_mode)
            self._append_ui_action_log(
                sim, 'set_government_event_mode', scope,
                districts=list(targets), event='emergency_warning', mode=event_mode)
        self.worker.queue_action(_do)
        self._set_gov_button_display(self.btn_warning, event_mode)
        self._mark(f'{scope} 应急预警 {event_mode.upper()}')

    def _any_gov_manual_on(self, gov):
        """Legacy-only aggregate switch; v2 uses independent event modes."""
        return any([
            bool(getattr(gov, 'manual_emergency_warning', False)),
            bool(getattr(gov, 'manual_resource_to_grid', False)),
            bool(getattr(gov, 'manual_resource_to_enterprise', False)),
            bool(getattr(gov, 'manual_resource_to_resident', False)),
            bool(getattr(gov, 'manual_public_opinion', False)),
        ])

    def _gov_event_mode(self, gov, event_key, legacy_attr):
        getter = getattr(gov, 'get_event_mode', None)
        if callable(getter):
            try:
                mode = str(getter(event_key)).lower()
                if mode in {'auto', 'on', 'off'}:
                    return mode
            except Exception:
                pass
        for attr in ('event_modes', '_event_modes'):
            modes = getattr(gov, attr, None)
            if isinstance(modes, Mapping) and event_key in modes:
                mode = str(modes[event_key]).lower()
                if mode in {'auto', 'on', 'off'}:
                    return mode
        return 'on' if bool(getattr(gov, legacy_attr, False)) else 'auto'

    def _gov_event_is_forced_on(self, gov, event_key, legacy_attr):
        return self._gov_event_mode(gov, event_key, legacy_attr) == 'on'

    def _selected_gov_event_mode(self):
        mode = self.combo_gov_event_mode.currentData()
        return mode if mode in {'auto', 'on', 'off'} else 'on'

    def _set_gov_button_display(self, button, mode):
        base = getattr(self, '_gov_button_base_labels', {}).get(button, button.text())
        suffix = {'on': ' [ON]', 'off': ' [OFF]', 'mixed': ' [混合]'}.get(mode, '')
        button.blockSignals(True)
        button.setChecked(mode == 'on')
        button.blockSignals(False)
        button.setText(base + suffix)

    def _set_gov_event_mode(self, gov, event_key, legacy_attr, mode):
        """V2: each event is independently auto/on; old engine retains its bridge."""
        mode = str(mode).lower()
        if mode not in {'auto', 'on', 'off'}:
            raise ValueError(f'Unsupported government event mode: {mode!r}')
        setter = getattr(gov, 'set_event_mode', None)
        if callable(setter):
            setter(event_key, mode)
            return
        # Older agents only distinguish manually-on from automatic.  Preserve
        # the no-cross-event behavior for AUTO/ON; explicit OFF needs v2.
        setattr(gov, legacy_attr, mode == 'on')
        gov.use_manual_events = self._any_gov_manual_on(gov)

    def act_toggle_resource_grid(self):
        if self.worker is None:
            return
        event_mode = self._selected_gov_event_mode()
        targets = self._selected_gov_targets(self.sim_ref)
        if not targets:
            self.status_label.setText('未选中当前仿真已加载的政府 Agent')
            return
        scope = self._selected_gov_scope_text()

        def _do(sim):
            for d in targets:
                gov = sim.gov_agents.get(d)
                if gov is None:
                    continue
                self._set_gov_event_mode(
                    gov, 'resource_to_grid', 'manual_resource_to_grid', event_mode)
            self._append_ui_action_log(
                sim, 'set_government_event_mode', scope,
                districts=list(targets), event='resource_to_grid', mode=event_mode)
        self.worker.queue_action(_do)
        self._set_gov_button_display(self.btn_res_grid, event_mode)
        self._mark(f'{scope} 资源→电网 {event_mode.upper()}')

    def act_toggle_resource_enterprise(self):
        if self.worker is None:
            return
        event_mode = self._selected_gov_event_mode()
        targets = self._selected_gov_targets(self.sim_ref)
        if not targets:
            self.status_label.setText('未选中当前仿真已加载的政府 Agent')
            return
        scope = self._selected_gov_scope_text()

        def _do(sim):
            for d in targets:
                gov = sim.gov_agents.get(d)
                if gov is None:
                    continue
                self._set_gov_event_mode(
                    gov, 'resource_to_enterprise', 'manual_resource_to_enterprise', event_mode)
            self._append_ui_action_log(
                sim, 'set_government_event_mode', scope,
                districts=list(targets), event='resource_to_enterprise', mode=event_mode)
        self.worker.queue_action(_do)
        self._set_gov_button_display(self.btn_res_enterprise, event_mode)
        self._mark(f'{scope} 资源→企业 {event_mode.upper()}')

    def act_toggle_resource_resident(self):
        if self.worker is None:
            return
        event_mode = self._selected_gov_event_mode()
        targets = self._selected_gov_targets(self.sim_ref)
        if not targets:
            self.status_label.setText('未选中当前仿真已加载的政府 Agent')
            return
        scope = self._selected_gov_scope_text()

        def _do(sim):
            for d in targets:
                gov = sim.gov_agents.get(d)
                if gov is None:
                    continue
                self._set_gov_event_mode(
                    gov, 'resource_to_resident', 'manual_resource_to_resident', event_mode)
            self._append_ui_action_log(
                sim, 'set_government_event_mode', scope,
                districts=list(targets), event='resource_to_resident', mode=event_mode)
        self.worker.queue_action(_do)
        self._set_gov_button_display(self.btn_res_resident, event_mode)
        self._mark(f'{scope} 资源→居民 {event_mode.upper()}')

    def act_apply_grid_params(self):
        if self.worker is None or self.sim_ref is None:
            return
        init_mult = self.slider_grid_init.value() / 100.0
        resp_mult = self.slider_grid_resp.value() / 100.0
        lam = self.slider_grid_lambda.value() / 100.0
        cap = float(self.slider_grid_cap.value())
        base = getattr(self, '_grid_base', {
            'initiative': 0.5, 'response': 1.0,
            'lambda_prop': 0.1, 'base_resource_capacity': 50.0,
        })

        def _do(sim):
            sim.grid.initiative = max(0.0, min(1.0, base['initiative'] * init_mult))
            sim.grid.response = max(0.0, min(2.0, base['response'] * resp_mult))
            sim.grid.lambda_prop = max(0.0, min(1.0, lam))
            sim.grid.base_resource_capacity = max(0.0, min(100.0, cap))
            occupied = getattr(sim.grid, 'occupied_resources', 0.0)
            sim.grid.current_resource_level = max(
                0.0, sim.grid.base_resource_capacity - occupied
            )
            self._append_ui_action_log(
                sim, 'set_grid_parameters', 'global', initiative_multiplier=init_mult,
                response_multiplier=resp_mult, lambda_prop=lam, resource_capacity=cap)
        self.worker.queue_action(_do)
        self._mark(f'电网 i×{init_mult:.2f}/r×{resp_mult:.2f}/λ={lam:.2f}/cap={cap:.0f}')

    def _any_grid_manual_on(self, grid):
        return getattr(grid, 'manual_temp_station', False) or getattr(grid, 'manual_repair', False)

    def act_toggle_temp_station(self):
        if self.worker is None:
            return
        on = self.btn_temp_station.isChecked()

        def _do(sim):
            sim.grid.manual_temp_station = on
            if not callable(getattr(sim, 'trigger_outage_scenario', None)):
                sim.grid.use_manual_events = self._any_grid_manual_on(sim.grid)
            sim.grid.is_setting_temp_power = on
            self._append_ui_action_log(
                sim, 'set_grid_temp_station', 'global', mode='on' if on else 'auto')
        self.worker.queue_action(_do)
        self._mark('临时供电站 ON' if on else '临时供电站 AUTO')

    def act_toggle_repair(self):
        if self.worker is None:
            return
        on = self.btn_repair.isChecked()

        def _do(sim):
            sim.grid.manual_repair = on
            # V2 repair progress has its own state machine: button OFF means
            # baseline repair, not "stop all repair".  Preserve old behavior
            # only for a simulation that does not yet expose the v2 interface.
            sim.grid.enhanced_repair_enabled = on
            setter = getattr(sim.grid, 'set_enhanced_repair', None)
            if callable(setter):
                setter(on)
            if not callable(getattr(sim, 'trigger_outage_scenario', None)):
                sim.grid.use_manual_events = self._any_grid_manual_on(sim.grid)
                ongoing = getattr(sim.grid, 'ongoing_repairs', None) or {}
                sim.grid.is_repairing = on or len(ongoing) > 0
            self._append_ui_action_log(
                sim, 'set_enhanced_repair', 'global', mode='on' if on else 'baseline')
        self.worker.queue_action(_do)
        self._mark('强化抢修 ON' if on else '强化抢修 BASELINE')

    def closeEvent(self, event):
        self.stop_sim()
        event.accept()


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
