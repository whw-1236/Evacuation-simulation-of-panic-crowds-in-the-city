# -*- coding: utf-8 -*-
"""
================================================================================
事件记录器模块 - 停电应急仿真事件记录与导出
================================================================================
功能：
    1. 记录仿真过程中发生的所有事件
    2. 跟踪事件的开始和结束时间
    3. 导出事件记录到CSV文件

输出CSV格式：
    - event_id: 事件类型ID
    - zone_id: 发生区域ID
    - start_time: 事件开始时间
    - end_time: 事件结束时间
================================================================================
"""

import os
import csv
from collections import defaultdict
from .event_types import (
    EVENT_METADATA, get_event_name,
    GOV_EMERGENCY_WARNING, GOV_RESOURCE_TO_GRID, GOV_RESOURCE_TO_ENTERPRISE,
    GOV_RESOURCE_TO_RESIDENT, GOV_PUBLIC_OPINION,
    GRID_BLACKOUT, GRID_TEMP_STATION, GRID_REPAIR, GRID_RESTORE,
    ENT_REQUEST_RESOURCE, ENT_CRISIS, ENT_SHUTDOWN, ENT_RESUME,
    RES_HOARDING, RES_GATHERING, RES_POWER_REQUEST, RES_EMOTION_BURST, RES_SELF_HELP
)


class Event:
    """单个事件对象"""

    def __init__(self, event_id, zone_id, start_time, end_time=None):
        """
        初始化事件

        参数:
            event_id: 事件类型ID
            zone_id: 发生区域ID
            start_time: 事件开始时间步
            end_time: 事件结束时间步（None表示进行中）
        """
        self.event_id = event_id
        self.zone_id = zone_id
        self.start_time = start_time
        self.end_time = end_time

    def close(self, end_time):
        """关闭事件"""
        self.end_time = end_time

    def is_active(self):
        """事件是否仍在进行"""
        return self.end_time is None

    def __repr__(self):
        name = get_event_name(self.event_id)
        return f"Event({name}, zone={self.zone_id}, {self.start_time}-{self.end_time})"


class EventRecorder:
    """
    事件记录器

    记录持续性事件的开始和结束时间
    """

    def __init__(self):
        self.completed_events = []  # 已完成事件
        self.active_events = {}  # 进行中事件 {(event_id, zone_id): Event}
        self.event_counts = defaultdict(int)
        self.current_step = 0

    def set_step(self, step):
        """设置当前时间步"""
        self.current_step = step

    def record_instant_event(self, event_id, zone_id):
        """记录瞬时事件（开始=结束）"""
        event = Event(event_id, zone_id, self.current_step, self.current_step)
        self.completed_events.append(event)
        self.event_counts[event_id] += 1

    def start_event(self, event_id, zone_id):
        """开始一个持续性事件"""
        key = (event_id, zone_id)
        if key in self.active_events:
            return False

        event = Event(event_id, zone_id, self.current_step)
        self.active_events[key] = event
        self.event_counts[event_id] += 1
        return True

    def end_event(self, event_id, zone_id):
        """结束一个持续性事件"""
        key = (event_id, zone_id)
        if key not in self.active_events:
            return False

        event = self.active_events.pop(key)
        event.close(self.current_step)
        self.completed_events.append(event)
        return True

    def is_event_active(self, event_id, zone_id):
        """检查事件是否正在进行"""
        return (event_id, zone_id) in self.active_events

    def close_all_active_events(self):
        """关闭所有仍在进行的事件"""
        for key, event in list(self.active_events.items()):
            event.close(self.current_step)
            self.completed_events.append(event)
        self.active_events.clear()

    def get_all_events(self, merge_continuous=True):
        """
        获取所有事件

        参数:
            merge_continuous: 是否合并连续事件（默认True）
                              连续事件：同一event_id+zone_id，end_time+1 == 下一个start_time

        【改进】正确处理活跃事件（end_time=None）：
        - 活跃事件可以与之前的已完成事件合并
        - 当前事件end_time=None时，也应该尝试合并后续同类型事件
        """
        all_events = list(self.completed_events)
        for event in self.active_events.values():
            all_events.append(event)

        # 按 (event_id, zone_id, start_time) 排序
        all_events = sorted(all_events, key=lambda e: (e.event_id, e.zone_id or '', e.start_time))

        if not merge_continuous or len(all_events) < 2:
            return sorted(all_events, key=lambda e: (e.start_time, e.event_id, e.zone_id or ''))

        # 【合并连续事件】
        # 如果两个事件的 event_id 和 zone_id 相同，且时间连续或重叠
        # 则合并为一个事件
        merged = []
        current = None

        for event in all_events:
            if current is None:
                current = Event(event.event_id, event.zone_id, event.start_time, event.end_time)
            elif current.event_id == event.event_id and current.zone_id == event.zone_id:
                # 同类型同区域事件，检查是否可以合并
                can_merge = False

                if current.end_time is None:
                    # 当前事件还在进行中（活跃事件）
                    # 如果新事件的start_time在current的start_time之后，说明可能是同一个事件
                    # 由于current还没结束，它肯定覆盖到新事件
                    can_merge = True
                elif event.start_time is not None and event.start_time <= current.end_time + 1:
                    # 当前事件已结束，但新事件紧跟其后或重叠
                    can_merge = True

                if can_merge:
                    # 合并：扩展结束时间
                    if event.end_time is None:
                        current.end_time = None  # 新事件还在进行，合并后也未结束
                    elif current.end_time is not None:
                        current.end_time = max(current.end_time, event.end_time)
                    # 如果current.end_time已经是None，保持None
                else:
                    # 不连续，保存当前事件，开始新事件
                    merged.append(current)
                    current = Event(event.event_id, event.zone_id, event.start_time, event.end_time)
            else:
                # 不同类型或不同区域，保存当前事件，开始新事件
                merged.append(current)
                current = Event(event.event_id, event.zone_id, event.start_time, event.end_time)

        if current is not None:
            merged.append(current)

        return sorted(merged, key=lambda e: (e.start_time, e.event_id, e.zone_id or ''))

    def export_to_csv(self, filepath):
        """
        导出事件到CSV（唯一的导出方法）

        格式: event_id, zone_id, start_time, end_time
        """
        dir_path = os.path.dirname(filepath)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        all_events = self.get_all_events()

        with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['event_id', 'zone_id', 'start_time', 'end_time'])
            for event in all_events:
                writer.writerow([
                    event.event_id,
                    event.zone_id if event.zone_id is not None else '',
                    event.start_time,
                    event.end_time if event.end_time is not None else ''
                ])

        return len(all_events)

    def export_to_csv_with_names(self, filepath):
        """导出事件到CSV（带事件名称）"""
        dir_path = os.path.dirname(filepath)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        all_events = self.get_all_events()

        with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['event_id', 'event_name', 'zone_id', 'start_time', 'end_time'])
            for event in all_events:
                writer.writerow([
                    event.event_id,
                    get_event_name(event.event_id),
                    event.zone_id if event.zone_id is not None else '',
                    event.start_time,
                    event.end_time if event.end_time is not None else ''
                ])

        return len(all_events)

    def get_statistics(self):
        """获取统计信息"""
        return {
            'total_events': len(self.completed_events) + len(self.active_events),
            'completed_events': len(self.completed_events),
            'active_events': len(self.active_events),
            'by_type': dict(self.event_counts)
        }

    def print_summary(self):
        """打印统计摘要"""
        stats = self.get_statistics()
        print(f"\n事件统计: 总{stats['total_events']}个, "
              f"完成{stats['completed_events']}个, "
              f"进行中{stats['active_events']}个")


class EventDetector:
    """
    事件检测器 - 根据仿真状态检测事件
    """

    def __init__(self, recorder):
        self.recorder = recorder

        # 状态缓存
        self.prev_zone_status = {}
        self.prev_enterprise_powered = {}
        self.prev_enterprise_crisis = {}
        self.prev_enterprise_request = {}
        self.prev_resident_emotion = {}
        self.prev_resident_state = {}
        self.prev_ongoing_repairs = set()
        self.prev_partial_zones = set()  # 部分停电区域缓存

        # 阈值
        self.emotion_burst_threshold = 0.7
        self.crisis_threshold = 0.5
        self.request_threshold = 0.3
        self.panic_threshold = 0.6

    def detect_events(self, sim, step):
        """检测当前步的所有事件"""
        self.recorder.set_step(step)

        self._detect_government_events(sim)
        self._detect_grid_events(sim)
        self._detect_enterprise_events(sim)
        self._detect_resident_events(sim)

        self._update_cache(sim)

    def _detect_government_events(self, sim):
        """检测各区政府事件 —— 每个区的政府独立检测"""
        for district, gov in sim.gov_agents.items():
            # 用区县名作为 zone_id 标识该区的政府事件

            # 1. 发布应急预警
            if gov.emergency_warning_issued:
                if not self.recorder.is_event_active(GOV_EMERGENCY_WARNING, district):
                    self.recorder.start_event(GOV_EMERGENCY_WARNING, district)
            else:
                if self.recorder.is_event_active(GOV_EMERGENCY_WARNING, district):
                    self.recorder.end_event(GOV_EMERGENCY_WARNING, district)

            # 2. 政府分配资源给电网
            if gov.resource_to_grid:
                if not self.recorder.is_event_active(GOV_RESOURCE_TO_GRID, district):
                    self.recorder.start_event(GOV_RESOURCE_TO_GRID, district)
            else:
                if self.recorder.is_event_active(GOV_RESOURCE_TO_GRID, district):
                    self.recorder.end_event(GOV_RESOURCE_TO_GRID, district)

            # 3. 政府分配资源给企业
            if gov.resource_to_enterprise:
                if not self.recorder.is_event_active(GOV_RESOURCE_TO_ENTERPRISE, district):
                    self.recorder.start_event(GOV_RESOURCE_TO_ENTERPRISE, district)
            else:
                if self.recorder.is_event_active(GOV_RESOURCE_TO_ENTERPRISE, district):
                    self.recorder.end_event(GOV_RESOURCE_TO_ENTERPRISE, district)

            # 4. 政府分配资源给居民
            if gov.resource_to_resident:
                if not self.recorder.is_event_active(GOV_RESOURCE_TO_RESIDENT, district):
                    self.recorder.start_event(GOV_RESOURCE_TO_RESIDENT, district)
            else:
                if self.recorder.is_event_active(GOV_RESOURCE_TO_RESIDENT, district):
                    self.recorder.end_event(GOV_RESOURCE_TO_RESIDENT, district)

            # 5. 实施舆情管理
            if gov.public_opinion_active:
                if not self.recorder.is_event_active(GOV_PUBLIC_OPINION, district):
                    self.recorder.start_event(GOV_PUBLIC_OPINION, district)
            else:
                if self.recorder.is_event_active(GOV_PUBLIC_OPINION, district):
                    self.recorder.end_event(GOV_PUBLIC_OPINION, district)

    def _detect_grid_events(self, sim):
        """检测电网事件"""
        current_zone_status = sim.zone_status.copy()

        # 6. 区域断电（包括完全停电和部分停电/切负荷）
        # 获取部分停电的区域
        partial_outage_zones = set(getattr(sim, 'partial_outage_entities', {}).keys())

        for zone, powered in current_zone_status.items():
            prev_powered = self.prev_zone_status.get(zone, True)
            prev_partial = zone in getattr(self, 'prev_partial_zones', set())
            curr_partial = zone in partial_outage_zones

            # 完全停电：zone_status 从 True 变为 False
            if prev_powered and not powered:
                self.recorder.start_event(GRID_BLACKOUT, zone)

            # 部分停电（切负荷）：加入 partial_outage_entities
            elif not prev_partial and curr_partial:
                self.recorder.start_event(GRID_BLACKOUT, zone)

        # 保存当前部分停电区域，供下一步检测
        self.prev_partial_zones = partial_outage_zones.copy()

        # 检查是否使用人为控制模式
        use_manual = getattr(sim.grid, 'use_manual_events', False)

        # 获取区域目标设置
        target_all = getattr(sim.grid, 'target_all_zones', True)
        target_zones = getattr(sim.grid, 'target_zones', [])

        # 7. 临时供电站
        # 【人为控制模式】由外部控制开始/结束（支持区域选择）
        # 【自动模式】基于备用电源状态（也支持区域过滤）
        if use_manual:
            manual_temp = getattr(sim.grid, 'manual_temp_station', False)

            # 人为控制模式：对目标停电区域操作
            for zone, powered in current_zone_status.items():
                if not powered:  # 只对停电区域操作
                    # 检查是否为目标区域
                    is_target = target_all or (str(zone) in [str(z) for z in target_zones])

                    if manual_temp and is_target:
                        if not self.recorder.is_event_active(GRID_TEMP_STATION, zone):
                            self.recorder.start_event(GRID_TEMP_STATION, zone)
                    else:
                        if self.recorder.is_event_active(GRID_TEMP_STATION, zone):
                            self.recorder.end_event(GRID_TEMP_STATION, zone)
        else:
            # 自动模式：基于备用电源状态（也应用区域过滤）
            zones_with_backup = set()
            for node in sim.csv_nodes:
                if node.get('backup_power'):
                    zone = node.get('zone')
                    if zone is not None and not current_zone_status.get(zone, True):
                        # 【区域过滤】检查是否为目标区域
                        is_target = target_all or (str(zone) in [str(z) for z in target_zones])
                        if not is_target:
                            continue  # 不是目标区域，跳过

                        backup_duration = node.get('backup_duration', 0)
                        zone_outage = sim.zone_duration.get(zone, 0)
                        if zone_outage < backup_duration:
                            zones_with_backup.add(zone)

            for zone in zones_with_backup:
                if not self.recorder.is_event_active(GRID_TEMP_STATION, zone):
                    self.recorder.start_event(GRID_TEMP_STATION, zone)

            for zone in list(current_zone_status.keys()):
                if self.recorder.is_event_active(GRID_TEMP_STATION, zone):
                    if zone not in zones_with_backup:
                        self.recorder.end_event(GRID_TEMP_STATION, zone)

        # 8. 电网抢修
        # 【人为控制模式】由外部控制开始/结束（支持区域选择）
        # 【自动模式】基于ongoing_repairs状态（也支持区域过滤）
        if use_manual:
            manual_repair = getattr(sim.grid, 'manual_repair', False)

            # 人为控制模式：对目标停电区域操作
            for zone, powered in current_zone_status.items():
                if not powered:  # 只对停电区域操作
                    # 检查是否为目标区域
                    is_target = target_all or (str(zone) in [str(z) for z in target_zones])

                    if manual_repair and is_target:
                        if not self.recorder.is_event_active(GRID_REPAIR, zone):
                            self.recorder.start_event(GRID_REPAIR, zone)
                    else:
                        if self.recorder.is_event_active(GRID_REPAIR, zone):
                            self.recorder.end_event(GRID_REPAIR, zone)
        else:
            # 自动模式：基于ongoing_repairs状态（也应用区域过滤）
            current_repairs = set(sim.grid.ongoing_repairs.keys())
            new_repairs = current_repairs - self.prev_ongoing_repairs
            for zone in new_repairs:
                # 【区域过滤】检查是否为目标区域
                is_target = target_all or (str(zone) in [str(z) for z in target_zones])
                if is_target:
                    self.recorder.start_event(GRID_REPAIR, zone)

        # 9. 恢复供电（包括完全恢复和部分停电区域恢复）
        partial_outage_zones = set(getattr(sim, 'partial_outage_entities', {}).keys())
        prev_partial_zones = getattr(self, 'prev_partial_zones', set())

        for zone, powered in current_zone_status.items():
            prev_powered = self.prev_zone_status.get(zone, True)
            was_partial = zone in prev_partial_zones
            is_partial = zone in partial_outage_zones

            # 完全停电恢复：zone_status 从 False 变为 True
            if not prev_powered and powered:
                self.recorder.end_event(GRID_BLACKOUT, zone)
                self.recorder.end_event(GRID_REPAIR, zone)
                self.recorder.record_instant_event(GRID_RESTORE, zone)

            # 部分停电恢复：从 partial_outage_entities 中移除
            elif was_partial and not is_partial:
                self.recorder.end_event(GRID_BLACKOUT, zone)
                self.recorder.end_event(GRID_REPAIR, zone)
                self.recorder.record_instant_event(GRID_RESTORE, zone)

    def _detect_enterprise_events(self, sim):
        """检测企业事件"""
        for i, e in enumerate(sim.enterprises):
            zone = getattr(e, 'zone', i)

            # 10. 企业请求资源
            is_requesting = getattr(e, 'is_requesting', False)
            prev_requesting = self.prev_enterprise_request.get(i, False)
            if is_requesting and not prev_requesting:
                self.recorder.start_event(ENT_REQUEST_RESOURCE, zone)
            elif not is_requesting and prev_requesting:
                self.recorder.end_event(ENT_REQUEST_RESOURCE, zone)

            # 11. 企业经营危机
            is_crisis = getattr(e, 'is_in_crisis', False)
            prev_crisis = self.prev_enterprise_crisis.get(i, False)
            if is_crisis and not prev_crisis:
                self.recorder.start_event(ENT_CRISIS, zone)
            elif not is_crisis and prev_crisis:
                self.recorder.end_event(ENT_CRISIS, zone)

            # 12. 企业停工
            is_shutdown = getattr(e, 'is_shutdown', False)
            prev_shutdown = self.prev_enterprise_powered.get(i, False)
            if is_shutdown and not prev_shutdown:
                self.recorder.start_event(ENT_SHUTDOWN, zone)

            # 13. 恢复生产
            just_resumed = getattr(e, 'just_resumed', False)
            if just_resumed:
                self.recorder.end_event(ENT_SHUTDOWN, zone)
                self.recorder.record_instant_event(ENT_RESUME, zone)

    def _detect_resident_events(self, sim):
        """
        检测居民事件 - 使用动态阈值和最小人数要求

        【核心改进】
        1. 动态阈值：小样本区域需要更高的绝对人数才能触发
        2. 最小触发人数：至少需要3人触发才能算作区域事件
        3. 差异化检测：不同区域可以在不同时间触发同类事件

        【触发条件】
        - 比例条件：触发比例 > 阈值
        - 绝对条件：触发人数 >= 最小人数
        - 两个条件必须同时满足
        """
        zone_residents = {}
        for r in sim.residents:
            zone = r.zone
            if zone not in zone_residents:
                zone_residents[zone] = []
            zone_residents[zone].append(r)

        # 【改进】计算全局居民统计，用于动态阈值
        total_residents = len(sim.residents)
        num_zones = len(zone_residents)
        avg_per_zone = total_residents / num_zones if num_zones > 0 else 10

        for zone, residents in zone_residents.items():
            if not residents:
                continue

            n = len(residents)

            # 【核心】动态计算最小触发人数
            # - 大区域（>=15人）：需要比例达标
            # - 中等区域（5-14人）：至少3人
            # - 小区域（<5人）：至少2人且比例>50%
            def check_threshold(count, base_ratio, min_count_large=None):
                """
                检查是否达到触发阈值

                参数:
                    count: 触发的人数
                    base_ratio: 基础比例阈值
                    min_count_large: 大区域的最小人数（默认根据比例计算）
                """
                ratio = count / n

                if n >= 15:
                    # 大区域：标准比例检测
                    min_needed = min_count_large or max(3, int(n * base_ratio))
                    return ratio >= base_ratio and count >= min_needed
                elif n >= 5:
                    # 中等区域：需要至少3人且比例较高
                    return count >= 3 and ratio >= base_ratio * 1.2
                else:
                    # 小区域：需要至少2人且比例>50%
                    return count >= 2 and ratio >= max(0.5, base_ratio * 1.5)

            def check_end_threshold(count, base_ratio):
                """
                检查是否应结束事件

                【改进】更合理的结束条件：
                - 大区域：比例降到开始阈值的40%以下
                - 中等区域：人数降到2人以下
                - 小区域：人数为0
                """
                ratio = count / n
                # 结束阈值设置得更低，使事件更容易结束
                end_ratio = base_ratio * 0.4  # 原来是0.5，改为0.4

                if n >= 15:
                    # 大区域：比例低于阈值
                    return ratio <= end_ratio
                elif n >= 5:
                    # 中等区域：人数<=2 或 比例很低
                    return count <= 2 or ratio <= end_ratio * 0.8
                else:
                    # 小区域：无人触发
                    return count == 0

            # 14. 居民囤积物资
            hoarding_count = sum(1 for r in residents if getattr(r, 'is_hoarding', False))
            if check_threshold(hoarding_count, 0.3):
                if not self.recorder.is_event_active(RES_HOARDING, zone):
                    self.recorder.start_event(RES_HOARDING, zone)
            elif check_end_threshold(hoarding_count, 0.3):
                if self.recorder.is_event_active(RES_HOARDING, zone):
                    self.recorder.end_event(RES_HOARDING, zone)

            # 15. 居民聚集与信息传播
            gathering_count = sum(1 for r in residents if getattr(r, 'is_gathering', False))
            if check_threshold(gathering_count, 0.2):
                if not self.recorder.is_event_active(RES_GATHERING, zone):
                    self.recorder.start_event(RES_GATHERING, zone)
            elif check_end_threshold(gathering_count, 0.2):
                if self.recorder.is_event_active(RES_GATHERING, zone):
                    self.recorder.end_event(RES_GATHERING, zone)

            # 16. 恢复供电请求
            requesting_count = sum(1 for r in residents if getattr(r, 'is_requesting_power', False))
            if check_threshold(requesting_count, 0.3):
                if not self.recorder.is_event_active(RES_POWER_REQUEST, zone):
                    self.recorder.start_event(RES_POWER_REQUEST, zone)
            elif check_end_threshold(requesting_count, 0.3):
                if self.recorder.is_event_active(RES_POWER_REQUEST, zone):
                    self.recorder.end_event(RES_POWER_REQUEST, zone)

            # 17. 居民情绪爆发
            burst_count = sum(1 for r in residents if getattr(r, 'is_emotion_burst', False))
            if check_threshold(burst_count, 0.3):
                if not self.recorder.is_event_active(RES_EMOTION_BURST, zone):
                    self.recorder.start_event(RES_EMOTION_BURST, zone)
            elif check_end_threshold(burst_count, 0.3):
                if self.recorder.is_event_active(RES_EMOTION_BURST, zone):
                    self.recorder.end_event(RES_EMOTION_BURST, zone)

            # 18. 居民自救与互助
            helping_count = sum(1 for r in residents if getattr(r, 'is_self_helping', False))
            if check_threshold(helping_count, 0.15):
                if not self.recorder.is_event_active(RES_SELF_HELP, zone):
                    self.recorder.start_event(RES_SELF_HELP, zone)
            elif check_end_threshold(helping_count, 0.15):
                if self.recorder.is_event_active(RES_SELF_HELP, zone):
                    self.recorder.end_event(RES_SELF_HELP, zone)

    def _update_cache(self, sim):
        """更新状态缓存"""
        self.prev_zone_status = sim.zone_status.copy()
        self.prev_ongoing_repairs = set(sim.grid.ongoing_repairs.keys())
        self.prev_partial_zones = set(getattr(sim, 'partial_outage_entities', {}).keys())

        for i, e in enumerate(sim.enterprises):
            self.prev_enterprise_powered[i] = getattr(e, 'is_shutdown', False)
            self.prev_enterprise_crisis[i] = getattr(e, 'is_in_crisis', False)
            self.prev_enterprise_request[i] = getattr(e, 'is_requesting', False)

        for i, r in enumerate(sim.residents):
            self.prev_resident_emotion[i] = r.emotion
            self.prev_resident_state[i] = r.state

    def finalize(self):
        """完成检测，关闭所有活跃事件"""
        self.recorder.close_all_active_events()
