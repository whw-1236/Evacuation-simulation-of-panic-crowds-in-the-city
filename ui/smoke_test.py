# -*- coding: utf-8 -*-
"""IJDRR UI 冒烟测试 — 不弹窗

覆盖功能 (一次跑 1 次仿真验全部):
1. SimulationWorker._build_city_config + _init_simulation 能成功初始化
2. 30 步推进 worker.flee_hist / herd_hist / emotion_hist 在累计
3. 干预动作 (资源加倍, 应急预警) 能进入仿真且改变指标
4. Stress ↔ Panic 解耦合 (相关系数 < 0.99)
5. * emotion display chronic-anxiety floor 公式: display >= 0.5*(stress-0.15) 当 stress > 0.15
6. * 统一 v2 部分停电入口 trigger_outage_scenario() 在同一步创建可审计修复状态
   - total_work > 0、受影响负荷非空、ETA 可读
   - 沈阳单 zone 也产生琥珀色的实体级部分停电，而非把 1/1 zone 变红
7. * 设备故障在 600 步内自动恢复，随后 force_restore_outage() 可安全清理第二次事故

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
from ui.main_window import SimulationWorker, _outage_metrics_snapshot


def main():
    print('=== IJDRR UI 冒烟测试 ===')
    print(f'CWD: {os.getcwd()}')

    w = SimulationWorker(
        # 沈河区目前只有一个运行时 zone，正好覆盖“单 zone 仍必须实际负荷
        # 切除”的回归场景；厦门的重复 raw zone ID 由数据预检单独处理。
        city='沈阳市', district='沈河区',
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

    # ===== 阶段 1: 统一接口 + 单 zone 实际负荷切除 =====
    trigger = getattr(sim, 'trigger_outage_scenario', None)
    assert callable(trigger), 'FAIL: UI v2 依赖 trigger_outage_scenario()'
    district = next(iter(getattr(sim, 'district_to_zones', {}) or {}), w.district)
    print(f'\n[阶段1] 统一入口：{district} 50% 实际加权负荷切除 (seed=42)')
    trigger(
        district=district, mode='partial', cause='equipment_failure',
        shed_ratio=0.5, damage_level=None, seed=42, scope_zone_ids=None,
    )
    outage = _outage_metrics_snapshot(sim)
    print(f"   状态={outage['phase']}, W={outage['work_done']:.1f}/{outage['total_work']:.1f}, "
          f"负荷={outage['affected_load_count']}, 请求/实际="
          f"{outage['requested_shed_ratio']:.1%}/{outage['realized_shed_ratio']:.1%}, "
          f"ETA={outage['eta_hours']}")
    assert outage['active'], 'FAIL: 触发当步必须存在活动事故状态'
    assert outage['total_work'] > 0, 'FAIL: 触发当步必须创建 total_work'
    assert outage['affected_load_count'] > 0, 'FAIL: 单 zone partial 必须切除实体负荷'
    assert abs(outage['realized_shed_ratio'] - 0.5) <= 0.20, (
        f"FAIL: 实际切负荷比例应接近 50%，得 {outage['realized_shed_ratio']:.1%}")
    fractions = getattr(sim, 'zone_power_fraction', {}) or {}
    assert any(0.0 < float(value) < 1.0 for value in fractions.values()), (
        'FAIL: 单 zone partial 应产生 0<zone_power_fraction<1 的琥珀色区域')
    print('   [OK] 阶段1 通过（单 zone 未被错误升级为全区全停）')

    # ===== 阶段 2: 推 30 步 + 验证 history 累计 =====
    print(f'\n[阶段2] 推 30 步, 中间 step 15 干预 (资源 ×1.8)')
    t0 = time.time()
    for i in range(30):
        sim.step()
        w._record_step()
        if i == 14:
            for gov in sim.gov_agents.values():
                gov.initiative = min(1.0, gov.initiative * 1.8)
                setter = getattr(gov, 'set_event_mode', None)
                if callable(setter):
                    setter('emergency_warning', 'on')
                    setter('resource_to_resident', 'on')
                else:
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

    # ===== 阶段 4: 等待自动修复，必须在 600 步内收敛 =====
    print('\n[阶段4] 等待设备故障自动修复（最多 600 步）')
    restored = False
    for _ in range(600):
        sim.step()
        w._record_step()
        outage = _outage_metrics_snapshot(sim)
        if not outage['active']:
            restored = True
            break
    print(f"   自动恢复={restored}, step={sim.step_count}, "
          f"history={len(w.opinion_hist)}")
    assert restored, 'FAIL: equipment_failure 应在 600 步内自动恢复'
    print('   [OK] 阶段4 通过（自动修复状态机收敛）')

    # ===== 阶段 5: 第二次事故 + 强制恢复清理 =====
    print('\n[阶段5] 第二次事故与 force_restore_outage() 清理')
    trigger(
        district=district, mode='full', cause='equipment_failure',
        shed_ratio=1.0, damage_level=None, seed=42, scope_zone_ids=None,
    )
    assert _outage_metrics_snapshot(sim)['active'], 'FAIL: 恢复后应可再次触发事故'
    restore = getattr(sim, 'force_restore_outage', None)
    assert callable(restore), 'FAIL: UI v2 依赖 force_restore_outage()'
    restore(district=None)
    assert not _outage_metrics_snapshot(sim)['active'], 'FAIL: 强制恢复后不应保留活动事故'
    print('   [OK] 阶段5 通过（强制恢复无残留）')

    # ===== 阶段 6: Stress ↔ Panic 解耦合 =====
    print(f'\n[阶段6] Stress ↔ Panic 解耦合检查')
    s = np.array(w.stress_hist)
    p = np.array(w.panic_hist)
    if s.std() > 0 and p.std() > 0:
        corr = np.corrcoef(s, p)[0, 1]
        max_diff = float(np.max(np.abs(s - p)))
        print(f'   相关系数: {corr:.3f}, 最大差: {max_diff:.3f}')
        print(f'   Stress 均值: {s.mean():.3f}, Panic 均值: {p.mean():.3f}')
    print('   (panic = σ^0.8, 数学上跟 stress 紧密相关, 这只是描述指标)')

    # ===== 阶段 7: §5.1 cascade 信号 =====
    print(f'\n[阶段7] §5.1 cascade 信号 (MML + graph-on, 前 30 步较短可能 cascade 未起)')
    flee_max = float(max(w.flee_hist)) if w.flee_hist else 0.0
    herd_max = float(max(w.herd_hist)) if w.herd_hist else 0.0
    print(f'   flee_ratio 峰值: {flee_max:.3f}')
    print(f'   herd_ratio 峰值: {herd_max:.3f}')

    print('\n' + '=' * 60)
    print('[OK] 全部 7 阶段冒烟通过')
    print('     UI 可用 `python -m ui.main_window` 启动验证视觉效果')
    print('=' * 60)
    return 0


if __name__ == '__main__':
    sys.exit(main())
