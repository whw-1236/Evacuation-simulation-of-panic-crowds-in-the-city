# -*- coding: utf-8 -*-
"""仿真结束后的事后绘图工具"""
import os
import numpy as np
import matplotlib.pyplot as plt

plt.rcParams['font.family'] = ['Microsoft YaHei', 'SimHei', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False


def plot_traces(history_list, labels=None, out_path='output/traces.png',
                title='仿真演化对比'):
    """绘制多次仿真的对比曲线

    参数:
        history_list: list of dict, 每个 dict 含
            'step', 'avg_stress', 'avg_emotion', 'avg_panic', 'outage_ratio'
        labels: list of str, 与 history_list 对应的标签
        out_path: 保存路径
    """
    if labels is None:
        labels = [f'run_{i}' for i in range(len(history_list))]

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    metrics = [
        ('avg_stress', '平均压力', axes[0, 0]),
        ('avg_emotion', '平均情绪', axes[0, 1]),
        ('avg_panic', '平均恐慌', axes[1, 0]),
        ('outage_ratio', '停电区域比例', axes[1, 1]),
    ]

    for key, name, ax in metrics:
        for hist, lbl in zip(history_list, labels):
            if key in hist and hist[key]:
                ax.plot(hist['step'], hist[key], label=lbl, linewidth=1.5)
        ax.set_xlabel('Step')
        ax.set_ylabel(name)
        ax.set_title(name)
        ax.set_ylim(0, 1)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=9)

    fig.suptitle(title, fontsize=14, fontweight='bold')
    fig.tight_layout()

    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    fig.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close(fig)
    return out_path
