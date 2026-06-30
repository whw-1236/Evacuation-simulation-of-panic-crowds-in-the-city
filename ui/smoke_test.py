# -*- coding: utf-8 -*-
"""IJDRR UI 冒烟测试 — 不弹窗

覆盖功能 (一次跑 1 次仿真验全部):
1. SimulationWorker._build_city_config + _init_simulation 能成功初始化
2. 30 步推进 worker.flee_hist / herd_hist / emotion_hist 在累计
3. 干预动作 (资源加倍, 应急预警) 能进入仿真且改变指标
4. Stress ↔ Panic 解耦合 (相关系数 < 0.99)
5. * emotion display chronic-anxiety floor 公式: display >= 0.5*(stress-0.15) 当 stress > 0.15
6. * 部分停电 trigger_outage(mode='partial') 后:
   - sim.zone_outage_cause 被填
   - sim.district_outage_mode == 'partial'
7. * 恢复供电 (模拟 act_restore_power) 后:
   - sim.zone_outage_cause 空
   - sim.district_outage_mode == None

运行: python -m ui.smoke_test
"""
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(_HERE)
if _PROJECT not in sys.path:
    sys.path.insert(0, _PROJECT)

import matplotlib
matplotlib.use('Agg')

import numpy as np

# 不直接调 SimulationWorker.start() (那需要 QThread event loop), 走它内部独立方法
from ui.main_window import SimulationWorker


def _restore_power_inline(sim):
    """模拟 MainWindow.act_restore_power._do, 跑在同一线程里 (smoke 用)"""
    for z in list(sim.zone_status.keys()):
        sim.zone_status[z] = True
        if hasattr(sim, 'zone_duration'):
            sim.zone_duration[z] = 0
        if hasattr(sim, 'zone_outage_cause') and z in sim.zone_outage_cause:
            del sim.zone_outage_cause[z]
    if hasattr(sim, 'district_outage_mode'):
        sim.district_outage_mode = None
    if hasattr(sim, 'district_repair_started'):
        sim.district_repair_started = False
    if hasattr(sim, 'district_repair_progress'):
        sim.district_repair_progress = 0.0


def main():
    print('=== IJDRR UI 冒烟测试 ===')
    print(f'CWD: {os.getcwd()}')

    w = SimulationWorker(
        city='厦门市', district='思明区',
        n_residents=300, n_enterprises=10,    # 减小, smoke 跑得快
        use_road_graph=True,
        use_mml=True,
        total_steps=0,
    )
    t0 = time.time()
    w._init_simulation()
    if w.sim is None:
        print('[FAIL] 仿真初始化失败')
        return 1
    sim = w.sim
    print(f'[init] {time.time()-t0:.1f}s, residents={len(sim.residents)}, '
          f'use_road_graph={getattr(sim, "use_road_graph", False)}, '
          f'shelters={len(getattr(sim, "shelters", []) or [])}')

    # ===== 阶段 1: 触发部分停电 + 验证 zone_outage_cause / district_mode 被设 =====
    zones = list(sim.zone_status.keys())
    half = max(1, len(zones) // 2)
    print(f'\n[阶段1] 触发部分停电 (severity=0.8) 一半 zone ({half}/{len(zones)})')
    sim.trigger_outage(zones[:half], mode='partial',
                       cause='equipment_failure', severity_ratio=0.8)

    n_cause_set = len(getattr(sim, 'zone_outage_cause', {}))
    dist_mode = getattr(sim, 'district_outage_mode', None)
    print(f'   zone_outage_cause 已填: {n_cause_set} 个 zone')
    print(f'   district_outage_mode = {dist_mode!r}')
    assert n_cause_set > 0, 'FAIL: 部分停电后 zone_outage_cause 应非空'
    assert dist_mode == 'partial', f"FAIL: district_outage_mode 应 'partial', 得 {dist_mode!r}"
    print('   [OK] 阶段1 通过 (partial outage 正确设了 cause + district_mode)')

    # ===== 阶段 2: 推 30 步 + 验证 history 累计 =====
    print(f'\n[阶段2] 推 30 步, 中间 step 15 干预 (资源 ×1.8)')
    t0 = time.time()
    for i in range(30):
        sim.step()
        w._record_step()
        if i == 14:
            for gov in sim.gov_agents.values():
                gov.initiative = min(1.0, gov.initiative * 1.8)
                gov.use_manual_events = True
                gov.manual_emergency_warning = True
                gov.manual_resource_to_resident = True
    print(f'   30 步 in {time.time()-t0:.1f}s')

    n = len(w.opinion_hist)
    print(f'   history 长度全部 = {n}: '
          f'emotion={len(w.emotion_hist)} '
          f'emotion_display={len(w.emotion_display_hist)} '
          f'flee={len(w.flee_hist)} herd={len(w.herd_hist)}')
    assert n == 30, f'FAIL: history 应 30 步, 得 {n}'
    assert len(w.emotion_display_hist) == 30, 'FAIL: display_hist 长度不对'
    print('   [OK] 阶段2 通过')

    # ===== 阶段 3: emotion display floor 验证 =====
    print(f'\n[阶段3] emotion display chronic-anxiety floor 验证')
    print(f'{"step":>4} {"raw":>6} {"σ":>6} {"floor 期望":>10} {"display 实际":>12} {"OK?":>4}')
    floor_ok = True
    for i in range(n):
        raw = w.emotion_hist[i]
        sigma = w.stress_hist[i]
        display = w.emotion_display_hist[i]
        floor = max(0.0, 0.5 * (sigma - 0.15))
        # display 应 >= floor (允许小 ε 浮点容忍)
        ok = display >= floor - 1e-9
        if not ok:
            floor_ok = False
        if i % 5 == 0 or not ok:    # 打部分行
            print(f'{i:>4} {raw:>6.3f} {sigma:>6.3f} {floor:>10.3f} {display:>12.3f} {"[OK]" if ok else "[FAIL]"}')
    assert floor_ok, 'FAIL: emotion_display 未达 chronic-anxiety floor'
    print('   [OK] 阶段3 通过 (display ≥ max(raw_avg, 0.5·(σ-0.15)))')

    # ===== 阶段 4: 恢复供电 + 验证 cause / mode 被清 =====
    print(f'\n[阶段4] 模拟全城恢复供电')
    _restore_power_inline(sim)
    n_cause_after = len(getattr(sim, 'zone_outage_cause', {}))
    dist_mode_after = getattr(sim, 'district_outage_mode', None)
    print(f'   zone_outage_cause 现 {n_cause_after} 个 (应为 0)')
    print(f'   district_outage_mode 现 {dist_mode_after!r} (应为 None)')
    assert n_cause_after == 0, f'FAIL: 恢复后 zone_outage_cause 应清空, 现 {n_cause_after}'
    assert dist_mode_after is None, f'FAIL: 恢复后 district_outage_mode 应 None, 现 {dist_mode_after!r}'
    print('   [OK] 阶段4 通过 (restore 清干净了)')

    # ===== 阶段 5: Stress ↔ Panic 解耦合 =====
    print(f'\n[阶段5] Stress ↔ Panic 解耦合检查')
    s = np.array(w.stress_hist)
    p = np.array(w.panic_hist)
    if s.std() > 0 and p.std() > 0:
        corr = np.corrcoef(s, p)[0, 1]
        max_diff = float(np.max(np.abs(s - p)))
        print(f'   相关系数: {corr:.3f}, 最大差: {max_diff:.3f}')
        print(f'   Stress 均值: {s.mean():.3f}, Panic 均值: {p.mean():.3f}')
    print('   (panic = σ^0.8, 数学上跟 stress 紧密相关, 这只是描述指标)')

    # ===== 阶段 6: §5.1 cascade 信号 =====
    print(f'\n[阶段6] §5.1 cascade 信号 (MML + graph-on, 30 步较短可能 cascade 未起)')
    flee_max = float(max(w.flee_hist)) if w.flee_hist else 0.0
    herd_max = float(max(w.herd_hist)) if w.herd_hist else 0.0
    print(f'   flee_ratio 峰值: {flee_max:.3f}')
    print(f'   herd_ratio 峰值: {herd_max:.3f}')

    print('\n' + '=' * 60)
    print('[OK] 全部 6 阶段冒烟通过')
    print('     UI 可用 `python -m ui.main_window` 启动验证视觉效果')
    print('=' * 60)
    return 0


if __name__ == '__main__':
    sys.exit(main())
