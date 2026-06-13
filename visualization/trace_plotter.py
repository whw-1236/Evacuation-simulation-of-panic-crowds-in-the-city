# -*- coding: utf-8 -*-
"""仿真结束后的事后绘图工具（增强版 2026-06-13）

新增功能（来自《仿真可视化面板-修改大纲.md》第 1 / 3 / 6 / 7 优化点）：
    - plot_district_traces:  按区县分解的多曲线图
    - plot_comparison:       多 run 对比叠加 + 阶段背景着色 + 事件竖线
    - plot_seir_areas:       SEIR 比例堆叠面积图
    - shade_phases:          为 axis 着色三段（基线/停电/恢复）
    - mark_events:           在 axis 上画事件竖线

向后兼容：原 plot_traces(history_list, labels, out_path, title) 接口保留。
"""
import os
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgba

plt.rcParams['font.family'] = ['Microsoft YaHei', 'SimHei', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False


# =============================================================================
# 颜色 / 风格
# =============================================================================
METRIC_COLORS = {
    'avg_stress':   '#F44336',
    'avg_emotion':  '#FFC107',
    'avg_panic':    '#9C27B0',
    'outage_ratio': '#2196F3',
}
METRIC_NAMES_CN = {
    'avg_stress':   '平均压力',
    'avg_emotion':  '平均情绪',
    'avg_panic':    '平均恐慌',
    'outage_ratio': '停电区域比例',
}
PHASE_COLORS = {
    'baseline': '#E8F5E9',   # 浅绿
    'outage':   '#FFEBEE',   # 浅红
    'recovery': '#E3F2FD',   # 浅蓝
}
SEIR_COLORS_FILL = {
    'S': '#A5D6A7', 'E': '#FFE082',
    'I': '#EF9A9A', 'R': '#90CAF9',
}


# =============================================================================
# 辅助函数：阶段着色 / 事件竖线
# =============================================================================
def shade_phases(ax, baseline_end=None, outage_end=None, total_steps=None):
    """对 axis 加三段背景：基线 / 停电 / 恢复。

    任意端为 None 时该段不绘制。
    """
    if total_steps is None:
        xlim = ax.get_xlim()
        total_steps = xlim[1] if xlim[1] > 0 else 1
    if baseline_end is not None and baseline_end > 0:
        ax.axvspan(0, baseline_end, color=PHASE_COLORS['baseline'], alpha=0.45, zorder=0)
    if baseline_end is not None and outage_end is not None and outage_end > baseline_end:
        ax.axvspan(baseline_end, outage_end, color=PHASE_COLORS['outage'], alpha=0.45, zorder=0)
    if outage_end is not None and outage_end < total_steps:
        ax.axvspan(outage_end, total_steps, color=PHASE_COLORS['recovery'], alpha=0.45, zorder=0)


def mark_events(ax, events, ymax=1.0):
    """events: list of dict {'step': int, 'label': str, 'color': '#xxx'}"""
    if not events:
        return
    for ev in events:
        step = ev.get('step')
        if step is None:
            continue
        c = ev.get('color', '#D32F2F')
        ax.axvline(step, linestyle='--', color=c, linewidth=1.0, alpha=0.85)
        if ev.get('label'):
            ax.text(step, ymax * 0.96, ev['label'],
                    rotation=90, fontsize=8, color=c,
                    ha='right', va='top',
                    bbox=dict(boxstyle='round,pad=0.15',
                              facecolor='white', alpha=0.65, edgecolor='none'))


# =============================================================================
# 1. 全局四指标 (向后兼容入口)
# =============================================================================
def plot_traces(history_list, labels=None, out_path='output/traces.png',
                title='仿真演化对比', events=None,
                baseline_end=None, outage_end=None):
    """绘制多次仿真的全局四指标对比曲线。

    参数:
        history_list: list of dict, 每个 dict 含 step + avg_stress + avg_emotion
                      + avg_panic + outage_ratio
        labels:       与 history_list 对应的标签
        out_path:     保存路径
        events:       可选事件列表 (画竖线)
        baseline_end / outage_end: 可选阶段背景着色边界 (step)
    """
    if not history_list:
        return None
    if labels is None:
        labels = [f'run_{i}' for i in range(len(history_list))]

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    metric_axes = [
        ('avg_stress',   axes[0, 0]),
        ('avg_emotion',  axes[0, 1]),
        ('avg_panic',    axes[1, 0]),
        ('outage_ratio', axes[1, 1]),
    ]
    last_step = max(
        (max(h.get('step', [0])) for h in history_list if h.get('step')),
        default=0,
    )

    for key, ax in metric_axes:
        for i, (hist, lbl) in enumerate(zip(history_list, labels)):
            xs = hist.get('step', [])
            ys = hist.get(key, [])
            if not xs or not ys:
                continue
            ls = '-' if i == 0 else '--'
            color = METRIC_COLORS.get(key, None)
            ax.plot(xs, ys, ls,
                    color=color, alpha=0.95 if i == 0 else 0.6,
                    label=lbl, linewidth=1.5)
        ax.set_xlabel('Step')
        ax.set_ylabel(METRIC_NAMES_CN.get(key, key))
        ax.set_title(METRIC_NAMES_CN.get(key, key))
        ax.set_ylim(0, 1)
        ax.grid(True, alpha=0.3)
        shade_phases(ax, baseline_end, outage_end, last_step)
        mark_events(ax, events, ymax=1.0)
        ax.legend(fontsize=9)

    fig.suptitle(title, fontsize=14, fontweight='bold')
    fig.tight_layout()

    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    fig.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close(fig)
    return out_path


# =============================================================================
# 2. 分区曲线
# =============================================================================
def plot_district_traces(district_history, out_path='output/district_traces.png',
                         metric='avg_stress', title=None,
                         events=None, baseline_end=None, outage_end=None,
                         top_n=None):
    """绘制按区县分解的指标曲线。

    参数:
        district_history: dict[district_name -> dict('step', metric, ...)]
        metric: 'avg_stress' / 'avg_emotion' / 'avg_panic' / 'outage_ratio'
        top_n:  仅画 metric 峰值最高的前 N 个区县（用于压差对比）
    """
    if not district_history:
        return None
    if title is None:
        title = f'分区{METRIC_NAMES_CN.get(metric, metric)}演化'

    items = list(district_history.items())
    if top_n is not None and len(items) > top_n:
        items.sort(
            key=lambda kv: max(kv[1].get(metric, [0]) or [0]),
            reverse=True,
        )
        items = items[:top_n]

    cmap = plt.get_cmap('tab20', max(len(items), 4))
    last_step = max(
        (max(h.get('step', [0])) for _, h in items if h.get('step')),
        default=0,
    )

    fig, ax = plt.subplots(figsize=(11, 6))
    for i, (dname, hist) in enumerate(items):
        xs = hist.get('step', [])
        ys = hist.get(metric, [])
        if not xs or not ys:
            continue
        ax.plot(xs, ys, '-', color=cmap(i), label=dname,
                linewidth=1.6, alpha=0.92)

    ax.set_xlabel('Step')
    ax.set_ylabel(METRIC_NAMES_CN.get(metric, metric))
    ax.set_ylim(0, 1)
    ax.grid(True, alpha=0.3)
    shade_phases(ax, baseline_end, outage_end, last_step)
    mark_events(ax, events, ymax=1.0)
    ax.legend(fontsize=9, ncol=2, loc='upper right')
    ax.set_title(title, fontsize=13, fontweight='bold')
    fig.tight_layout()

    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    fig.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close(fig)
    return out_path


# =============================================================================
# 3. SEIR 堆叠面积图
# =============================================================================
def plot_seir_areas(seir_history, out_path='output/seir_areas.png',
                    events=None, baseline_end=None, outage_end=None,
                    title='SEIR 比例演化'):
    """seir_history: dict('step', 'S', 'E', 'I', 'R')，每个键映射时间序列。"""
    xs = seir_history.get('step', [])
    if not xs:
        return None

    fig, ax = plt.subplots(figsize=(11, 5))
    series = []
    keys = []
    for k in ('S', 'E', 'I', 'R'):
        if k in seir_history and len(seir_history[k]) == len(xs):
            series.append(seir_history[k])
            keys.append(k)
    if not series:
        plt.close(fig)
        return None
    arr = np.array(series, dtype=float)
    total = arr.sum(axis=0)
    total[total == 0] = 1.0
    arr = arr / total  # 转比例

    ax.stackplot(xs, arr,
                 labels=keys,
                 colors=[SEIR_COLORS_FILL[k] for k in keys],
                 alpha=0.85)
    ax.set_xlabel('Step')
    ax.set_ylabel('比例')
    ax.set_ylim(0, 1)
    ax.set_xlim(xs[0], xs[-1])
    ax.legend(loc='upper right', fontsize=10)
    shade_phases(ax, baseline_end, outage_end, xs[-1])
    mark_events(ax, events, ymax=1.0)
    ax.set_title(title, fontsize=13, fontweight='bold')
    fig.tight_layout()

    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    fig.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close(fig)
    return out_path


# =============================================================================
# 4. 多 run 对比 (含阶段着色 + 事件竖线)
# =============================================================================
def plot_comparison(history_list, labels=None,
                    out_path='output/comparison.png',
                    metrics=('avg_stress', 'avg_emotion', 'outage_ratio'),
                    title='多 run 对比',
                    events=None, baseline_end=None, outage_end=None,
                    linestyles=None):
    """对多 run 在选定指标上做叠加对比（每个指标一张子图）。"""
    if not history_list:
        return None
    if labels is None:
        labels = [f'run_{i}' for i in range(len(history_list))]
    if linestyles is None:
        linestyles = ['-', '--', '-.', ':'] * 3

    nrows = len(metrics)
    fig, axes = plt.subplots(nrows, 1, figsize=(11, 3.4 * nrows), sharex=True)
    if nrows == 1:
        axes = [axes]

    last_step = max(
        (max(h.get('step', [0])) for h in history_list if h.get('step')),
        default=0,
    )

    for ax, metric in zip(axes, metrics):
        for i, (hist, lbl) in enumerate(zip(history_list, labels)):
            xs = hist.get('step', [])
            ys = hist.get(metric, [])
            if not xs or not ys:
                continue
            ls = linestyles[i % len(linestyles)]
            color = METRIC_COLORS.get(metric, None)
            ax.plot(xs, ys, ls, color=color, alpha=0.7 + 0.3 * (i == 0),
                    label=f'{lbl} · {METRIC_NAMES_CN.get(metric, metric)}',
                    linewidth=1.6)
        ax.set_ylabel(METRIC_NAMES_CN.get(metric, metric))
        ax.set_ylim(0, 1)
        ax.grid(True, alpha=0.3)
        shade_phases(ax, baseline_end, outage_end, last_step)
        mark_events(ax, events, ymax=1.0)
        ax.legend(fontsize=9, loc='upper right', ncol=2)

    axes[-1].set_xlabel('Step')
    fig.suptitle(title, fontsize=14, fontweight='bold')
    fig.tight_layout()

    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    fig.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close(fig)
    return out_path


# =============================================================================
# 5. 综合图：三联（全局 / 分区 / SEIR）
# =============================================================================
def plot_overview(history, district_history=None, seir_history=None,
                  out_path='output/overview.png',
                  events=None, baseline_end=None, outage_end=None,
                  district_metric='avg_stress',
                  title='仿真演化总览'):
    """单 run 三联综合图（顶部全局 + 中部分区 + 底部 SEIR）。"""
    has_district = bool(district_history)
    has_seir = bool(seir_history and seir_history.get('step'))
    n_rows = 1 + int(has_district) + int(has_seir)
    fig, axes = plt.subplots(n_rows, 1,
                             figsize=(11, 3.4 * n_rows), sharex=True)
    if n_rows == 1:
        axes = [axes]

    last_step = max(history.get('step', [0]) or [0])

    # ---- 顶部：全局四指标 ----
    ax0 = axes[0]
    for key in ('avg_stress', 'avg_emotion', 'avg_panic', 'outage_ratio'):
        xs = history.get('step', [])
        ys = history.get(key, [])
        if not xs or not ys:
            continue
        ax0.plot(xs, ys, '-', color=METRIC_COLORS.get(key),
                 label=METRIC_NAMES_CN.get(key, key), linewidth=1.6)
    ax0.set_ylabel('值'); ax0.set_ylim(0, 1); ax0.grid(True, alpha=0.3)
    shade_phases(ax0, baseline_end, outage_end, last_step)
    mark_events(ax0, events, ymax=1.0)
    ax0.legend(fontsize=9, loc='upper right')
    ax0.set_title('全局指标', fontsize=12, fontweight='bold')

    next_ax = 1

    # ---- 中部：分区 ----
    if has_district:
        ax1 = axes[next_ax]; next_ax += 1
        cmap = plt.get_cmap('tab20', max(len(district_history), 4))
        for i, (dname, hist) in enumerate(district_history.items()):
            xs = hist.get('step', [])
            ys = hist.get(district_metric, [])
            if xs and ys:
                ax1.plot(xs, ys, color=cmap(i), label=dname,
                         linewidth=1.4, alpha=0.9)
        ax1.set_ylabel(METRIC_NAMES_CN.get(district_metric, district_metric))
        ax1.set_ylim(0, 1); ax1.grid(True, alpha=0.3)
        shade_phases(ax1, baseline_end, outage_end, last_step)
        mark_events(ax1, events, ymax=1.0)
        ax1.legend(fontsize=8, loc='upper right', ncol=2)
        ax1.set_title('分区指标', fontsize=12, fontweight='bold')

    # ---- 底部：SEIR ----
    if has_seir:
        ax2 = axes[next_ax]
        keys = [k for k in 'SEIR' if k in seir_history
                and len(seir_history[k]) == len(seir_history['step'])]
        if keys:
            arr = np.array([seir_history[k] for k in keys], dtype=float)
            total = arr.sum(axis=0); total[total == 0] = 1.0
            ax2.stackplot(seir_history['step'], arr / total,
                          labels=keys,
                          colors=[SEIR_COLORS_FILL[k] for k in keys],
                          alpha=0.85)
        ax2.set_ylabel('SEIR 比例'); ax2.set_ylim(0, 1)
        shade_phases(ax2, baseline_end, outage_end, last_step)
        mark_events(ax2, events, ymax=1.0)
        ax2.legend(fontsize=9, loc='upper right')
        ax2.set_title('SEIR 比例', fontsize=12, fontweight='bold')

    axes[-1].set_xlabel('Step')
    fig.suptitle(title, fontsize=14, fontweight='bold')
    fig.tight_layout()

    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    fig.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close(fig)
    return out_path
