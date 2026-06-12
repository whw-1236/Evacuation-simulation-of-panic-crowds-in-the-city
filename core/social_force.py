# -*- coding: utf-8 -*-
"""
================================================================================
社会力与恐慌模型模块 - 完整版
================================================================================
基于原始论文复现，不做简化

整合：
    1. SocialForceModel - 社会力模型（基于人群力分析复现.py）
       - 驱动力 f_i^0 = m_i * (v_i^0 * e_i^0 - v_i(t)) / tau_i
       - 社会心理力 f_ij^soc = A_i * exp((r_ij - d_ij) / B_i) * n_ij
       - 身体接触力 f_ij^ph = K * Θ(r_ij - d_ij) * n_ij + k * Δv_ij^t * t_ij

    2. PanicModel - 恐慌传播模型（基于恐慌模拟复现.py）
       - 静态场 S_ij（理性因素，引导向安全区）
       - 危险场 H_ij（本能反应，远离危险源）
       - 恐慌传播 A_ij（PTS状态传染）
       - 转移概率计算

【输出数据】用于画图
    - 社会力向量 → 更新居民位置
    - 区域恐慌水平 → 地图颜色渲染
    - PTS人数统计 → 可选图表
================================================================================
"""

import numpy as np
import math
import random
from .behavior_switching import SwitchParams, compute_goal_direction, update_perceived_occupancy


class SocialForceModel:
    """
    社会力模型 - 完整版

    基于: 人群力分析复现.py 和文献

    力的组成（公式完整实现）：
    1. 驱动力 - 朝向目标移动的力
       f_i^0 = m_i * (v_i^0 * e_i^0 - v_i(t)) / tau_i

    2. 社会心理力 - 避开他人的排斥力
       f_ij^soc = A_i * exp((r_ij - d_ij) / B_i) * n_ij * w(φ)

    3. 身体接触力 - 碰撞时的物理力
       f_ij^ph = K * Θ(r_ij - d_ij) * n_ij + k * Θ(r_ij - d_ij) * Δv_ij^t * t_ij

    【可调参数】位置: config/config.py → SocialForceConfig
    """

    def __init__(self, config=None):
        """
        初始化社会力模型

        参数:
            config: SocialForceConfig配置对象
        """
        # ==================== 社会力模型参数（来自文献） ====================
        self.A = 2000.0  # 社会心理力强度 [N]
        self.B = 0.08  # 社会心理力作用范围 [m]，转换为经纬度约0.000001
        self.tau = 0.5  # 适应时间 [s]
        self.K = 1.2e5  # 身体压力常数 [kg/s^2]
        self.k = 2.4e5  # 滑动摩擦常数 [kg/(m·s)]
        self.lambda_val = 0.5  # 各向异性系数 (0~1)

        # 速度参数（大幅增大使移动非常明显）
        self.max_speed = 0.002  # 最大速度（经纬度/步）约200米/步
        self.desired_speed = 0.001  # 期望速度 约100米/步

        # 相互作用范围（经纬度单位，约300米）
        self.interaction_radius = 0.003

        # 缩放因子（经纬度 → 力，大幅增大）
        self.scale_factor = 0.001

        self.sw = SwitchParams()  # I1/I2/I3 参数
        self.stores = []  # 商店列表，由 simulation 载入商店数据后赋值
        self.g_max = 1.37  # 唤起最大加速倍数（恐慌速度因子）

        # ==================== 情绪传播参数 ====================
        self.attraction_strength = 0.1  # 情绪吸引力强度
        self.repulsion_strength = 0.3  # 情绪排斥力强度
        self.emotion_influence_radius = 0.002  # 情绪影响半径
        self.panic_threshold = 0.7  # 恐慌阈值

        # 从config加载参数
        if config:
            self._load_config(config)

    def _load_config(self, config):
        """从配置加载参数"""
        param_map = {
            'A': 'A', 'B': 'B', 'TAU': 'tau', 'K': 'K', 'k': 'k',
            'LAMBDA_VAL': 'lambda_val', 'MAX_SPEED': 'max_speed',
            'DESIRED_SPEED': 'desired_speed', 'INTERACTION_RADIUS': 'interaction_radius'
        }
        for config_name, attr_name in param_map.items():
            if hasattr(config, config_name):
                setattr(self, attr_name, getattr(config, config_name))

    def calculate_driving_force(self, agent):
        """
        驱动力  f_i^0 = m * (v0 * e_i0 - v) / tau
        期望方向 e_i0 由 I1 多阶段目标切换给出（方法学 Eq.10-12）：
        随情绪 E 在 home / hoard / herd 之间 sigmoid 软切换。
        """
        mass = getattr(agent, 'mass', 1.0)
        velocity = getattr(agent, 'velocity', np.array([0.0, 0.0]))

        # ---- I1: 期望方向 ----
        stores = getattr(self, 'stores', None) or []
        neighbors = getattr(agent, 'neighbors', [])
        e_i0 = np.array(compute_goal_direction(agent, stores, neighbors, self.sw),
                        dtype=float)

        # 兜底：平静+物资足+无Leader 时方向为0 → 朝家（否则原地微动）
        if not np.any(e_i0):
            home = getattr(agent, 'home_position', (agent.x, agent.y))
            hv = np.array([home[0] - agent.x, home[1] - agent.y])
            n = np.linalg.norm(hv)
            e_i0 = hv / n if n > 1e-9 else np.array([0.0, 0.0])

        # ---- 期望速度：基础速度 × 唤起加速因子 g(E)（Eq.18）----
        E = float(getattr(agent, 'emotion', 0.0))
        base_speed = getattr(agent, 'desired_speed', self.desired_speed)
        g = 1.0 + (self.g_max - 1.0) * E  # 1.0 ~ g_max

        # 可选：保留你的昼夜速度调制（只改速度，不改方向）
        time_speed = 1.0
        if hasattr(self, '_get_time_factors'):
            try:
                _, time_speed, _ = self._get_time_factors(
                    getattr(agent, '_current_hour', 12.0))
            except Exception:
                time_speed = 1.0

        v0 = base_speed * g * time_speed
        # （可选）Greenshields 密度降速：算出局部密度 rho 后乘 (1 - rho/rho_jam)

        desired_velocity = v0 * e_i0
        driving_force = mass * (desired_velocity - velocity) / self.tau
        return driving_force

    def _get_time_factors(self, hour):
        """
        获取时间因素对移动的影响

        返回: (活动概率, 速度系数, 回家倾向)
        """
        # 深夜 22:00 - 6:00
        if hour >= 22 or hour < 6:
            activity = 0.15  # 只有15%的人会外出
            speed = 0.5  # 速度减半
            go_home = 0.8  # 80%概率想回家
        # 早晨 6:00 - 9:00
        elif 6 <= hour < 9:
            activity = 0.6  # 60%外出
            speed = 0.8  # 速度略低
            go_home = 0.2  # 20%想回家
        # 白天 9:00 - 18:00
        elif 9 <= hour < 18:
            activity = 0.9  # 90%活动
            speed = 1.0  # 正常速度
            go_home = 0.1  # 10%想回家
        # 傍晚 18:00 - 22:00
        else:  # 18 <= hour < 22
            # 随时间增加回家倾向
            progress = (hour - 18) / 4  # 0 -> 1
            activity = 0.7 - progress * 0.4  # 0.7 -> 0.3
            speed = 0.9 - progress * 0.3  # 0.9 -> 0.6
            go_home = 0.3 + progress * 0.5  # 0.3 -> 0.8

        return activity, speed, go_home

    def _get_mobility_factors(self, agent):
        """
        获取个人属性对移动能力的影响

        返回: (移动能力系数, 是否行动受限)
        """
        # 获取个人属性
        age = getattr(agent, 'age', 35)
        health_status = getattr(agent, 'health_status', '健康')

        mobility = 1.0
        is_limited = False

        # 年龄影响
        if age >= 75:
            mobility *= 0.3  # 高龄老人移动能力很低
            is_limited = True
        elif age >= 65:
            mobility *= 0.5  # 老年人移动能力降低
            is_limited = True
        elif age >= 55:
            mobility *= 0.7  # 中老年人略有下降
        elif age < 12:
            mobility *= 0.6  # 儿童移动范围受限
            is_limited = True

        # 健康状态影响
        if health_status == '残疾':
            mobility *= 0.2
            is_limited = True
        elif health_status == '严重疾病':
            mobility *= 0.3
            is_limited = True
        elif health_status == '轻微疾病':
            mobility *= 0.7
        elif health_status == '亚健康':
            mobility *= 0.85

        return mobility, is_limited

        # 期望方向向量
        direction = np.array([target[0] - agent.x, target[1] - agent.y])
        distance = np.linalg.norm(direction)

        if distance > 0.00005:  # 离目标有一定距离
            e_i0 = direction / distance
            # 应用状态速度倍数（增大）
            desired_speed *= speed_mult * 2.0  # 额外加倍
            # 恐慌状态下速度进一步增加
            if getattr(agent, 'pts_status', False):
                desired_speed *= (1.0 + getattr(agent, 'panic_value', 0) * 0.8)
        else:
            # 到达目标，重置游走目标以获取新目标
            agent._wander_timer = 0
            # 给一个随机方向的微小速度，保持移动
            angle = random.random() * 2 * math.pi
            e_i0 = np.array([math.cos(angle), math.sin(angle)])
            desired_speed *= 0.5

        # 期望速度向量
        desired_velocity = desired_speed * e_i0

        # 驱动力（增大系数）
        driving_force = mass * (desired_velocity - current_velocity) / self.tau * 5.0

        return driving_force

    def calculate_social_force(self, agent_i, agent_j):
        """
        计算行人j对行人i的社会心理力（公式4）
        f_ij^soc = A_i * exp((r_ij - d_ij) / B_i) * n_ij * w(φ)

        参数:
            agent_i: 目标行人
            agent_j: 其他行人

        返回:
            force: [fx, fy] 社会力向量
        """
        pos_i = np.array([agent_i.x, agent_i.y])
        pos_j = np.array([agent_j.x, agent_j.y])

        # 两人之间的距离
        d_ij = np.linalg.norm(pos_i - pos_j)

        # 两人半径之和
        r_i = getattr(agent_i, 'radius', 0.0001)
        r_j = getattr(agent_j, 'radius', 0.0001)
        r_ij = r_i + r_j

        if d_ij < 1e-10:  # 避免除零
            return np.array([0.0, 0.0])

        # 单位方向向量（从j指向i，排斥方向）
        n_ij = (pos_i - pos_j) / d_ij

        # ==================== 各向异性因子 w(φ) ====================
        velocity_i = getattr(agent_i, 'velocity', np.array([0.0, 0.0]))
        if np.linalg.norm(velocity_i) > 1e-8:
            e_i = velocity_i / np.linalg.norm(velocity_i)
            # 行人i视野方向与j方向的夹角余弦
            cos_phi = np.dot(e_i, -n_ij)  # j在i的视野内为正
            # 各向异性权重：前方影响大，后方影响小
            anisotropy = self.lambda_val + (1 - self.lambda_val) * (1 + cos_phi) / 2
        else:
            anisotropy = 1.0

        # ==================== 社会心理力计算 ====================
        force_magnitude = self.A * np.exp((r_ij - d_ij) / self.B)
        social_force = force_magnitude * n_ij * anisotropy

        return social_force

    def calculate_physical_force(self, agent_i, agent_j):
        """
        计算身体接触力（公式7）
        f_ij^ph = K * Θ(r_ij - d_ij) * n_ij + k * Θ(r_ij - d_ij) * Δv_ij^t * t_ij

        当两人接触时（d_ij < r_ij）产生的物理力

        参数:
            agent_i: 目标行人
            agent_j: 其他行人

        返回:
            force: [fx, fy] 物理力向量
        """
        pos_i = np.array([agent_i.x, agent_i.y])
        pos_j = np.array([agent_j.x, agent_j.y])

        d_ij = np.linalg.norm(pos_i - pos_j)
        r_i = getattr(agent_i, 'radius', 0.0001)
        r_j = getattr(agent_j, 'radius', 0.0001)
        r_ij = r_i + r_j

        if d_ij < 1e-10:
            return np.array([0.0, 0.0])

        # 法向量
        n_ij = (pos_i - pos_j) / d_ij

        # 切向量（垂直于法向量）
        t_ij = np.array([-n_ij[1], n_ij[0]])

        # Θ函数：当有身体接触时 (r_ij > d_ij)
        theta = max(r_ij - d_ij, 0)

        if theta <= 0:  # 没有接触
            return np.array([0.0, 0.0])

        # 速度差
        v_i = getattr(agent_i, 'velocity', np.array([0.0, 0.0]))
        v_j = getattr(agent_j, 'velocity', np.array([0.0, 0.0]))
        delta_v = v_j - v_i

        # 速度差在切线方向的分量
        delta_v_t = np.dot(delta_v, t_ij)

        # 身体压力（法向）
        body_force = self.K * theta * n_ij

        # 滑动摩擦力（切向）
        friction_force = self.k * theta * delta_v_t * t_ij

        return body_force + friction_force

    def calculate_emotion_force(self, agent_i, agent_j, dist, n_ij):
        """
        计算情绪传播产生的力

        - 对方情绪更高（更恐慌）→ 可能被"感染"（I状态时吸引）
        - 对方情绪更低（更平静）→ 安抚效应
        """
        if dist > self.emotion_influence_radius:
            return np.array([0.0, 0.0])

        agent_emotion = getattr(agent_i, 'emotion', 0)
        other_emotion = getattr(agent_j, 'emotion', 0)
        emotion_diff = other_emotion - agent_emotion

        # 距离权重
        weight = 1 - dist / self.emotion_influence_radius

        force = np.array([0.0, 0.0])
        if emotion_diff > 0:  # 对方更恐慌
            # 传播者(I状态)影响力更大
            if getattr(agent_j, 'state', 'S') == 'I':
                # 被"拉向"恐慌状态（模拟从众心理）
                force = self.attraction_strength * emotion_diff * weight * (-n_ij)
            else:
                force = self.attraction_strength * 0.3 * emotion_diff * weight * (-n_ij)
        else:  # 对方更平静
            # 平静的安抚效应
            force = self.repulsion_strength * abs(emotion_diff) * weight * n_ij * 0.5

        return force

    def calculate_total_force(self, agent, all_agents, neighbors=None):
        """
        计算agent受到的总力

        参数:
            agent: 目标居民Agent
            all_agents: 所有居民列表
            neighbors: 邻居列表（可选，用于优化）

        返回:
            force: [fx, fy] 总力向量（已缩放）
        """
        # 1. 驱动力
        driving_force = self.calculate_driving_force(agent)

        # 2. 与其他行人的相互作用力
        interaction_force = np.array([0.0, 0.0])

        # 使用邻居列表或所有agent
        agents_to_check = neighbors if neighbors else all_agents

        for other in agents_to_check:
            if other is agent:
                continue

            # 距离检查
            dist = math.sqrt((agent.x - other.x) ** 2 + (agent.y - other.y) ** 2)
            if dist > self.interaction_radius:
                continue

            # 社会心理力
            social_force = self.calculate_social_force(agent, other)

            # 身体接触力
            physical_force = self.calculate_physical_force(agent, other)

            # 情绪力
            if dist > 0:
                n_ij = np.array([agent.x - other.x, agent.y - other.y]) / dist
            else:
                n_ij = np.array([0.0, 0.0])
            emotion_force = self.calculate_emotion_force(agent, other, dist, n_ij)

            interaction_force += social_force + physical_force + emotion_force

        # 3. 从众已由 I1 的 herd 方向（朝 Leader）在 compute_goal_direction 中处理；
        #    旧的"朝质心"集群力已删除，避免与 I1/I3 重复计算。
        # 4. 总力
        total_force = (driving_force * self.scale_factor * 8.0 +  # 驱动力（含 I1 期望方向）
                       interaction_force * self.scale_factor * 0.01)  # 社会力+物理+情绪

        return total_force

    def _calculate_cluster_force(self, agent, neighbors):
        """
        计算集群吸引力（增强版 + 时间限制）

        恐慌/停电时，居民倾向于向其他居民聚集（寻求安全感）
        平静时，保持一定距离（个人空间）

        【时间规律】
        - 深夜(22:00-6:00)：聚集解散，回家休息
        - 白天/傍晚：正常聚集行为
        - 聚集有持续时间限制（不能一直聚集）
        """
        emotion = getattr(agent, 'emotion', 0)
        panic_value = getattr(agent, 'panic_value', 0)
        powered = getattr(agent, 'powered', True)
        is_gathering = getattr(agent, 'is_gathering', False)

        # ============ 时间因素 ============
        current_hour = getattr(agent, '_current_hour', 12.0)

        # 深夜(22:00-6:00) - 聚集应该解散
        is_night = (current_hour >= 22 or current_hour < 6)

        # 深夜时聚集力大幅降低，产生"回家力"
        if is_night:
            # 结束聚集状态
            agent.is_gathering = False

            # 只有极端恐慌(>0.7)才会深夜聚集
            if panic_value < 0.7 and emotion < 0.7:
                return np.array([0.0, 0.0])
            # 即使恐慌，深夜聚集力也大幅降低
            night_factor = 0.2
        else:
            night_factor = 1.0

        # ============ 聚集持续时间限制 ============
        # 聚集时间计数（防止一直聚集）
        gathering_duration = getattr(agent, '_gathering_duration', 0)
        max_gathering_duration = 20  # 最多聚集20步（约5小时）

        if is_gathering:
            gathering_duration += 1
            agent._gathering_duration = gathering_duration

            # 聚集太久了，疲劳，想散去
            if gathering_duration > max_gathering_duration:
                agent.is_gathering = False
                agent._gathering_duration = 0
                # 聚集疲劳，暂时不想再聚集
                agent._gathering_cooldown = 10  # 10步冷却时间
                return np.array([0.0, 0.0])
        else:
            agent._gathering_duration = 0

        # 聚集冷却期
        cooldown = getattr(agent, '_gathering_cooldown', 0)
        if cooldown > 0:
            agent._gathering_cooldown = cooldown - 1
            return np.array([0.0, 0.0])

        # ============ 基础条件检查 ============
        # 只有在恐慌或停电或已经在聚集时才有聚集倾向
        if emotion < 0.2 and panic_value < 0.2 and powered and not is_gathering:
            agent.is_gathering = False
            return np.array([0.0, 0.0])

        # 计算邻居的质心（扩大范围到500米）
        nearby = []
        nearby_gathering = 0  # 附近正在聚集的人数
        for other in neighbors:
            if other is agent:
                continue
            dist = math.sqrt((agent.x - other.x) ** 2 + (agent.y - other.y) ** 2)
            if dist < 0.005:  # 500米内的邻居
                nearby.append(other)
                if getattr(other, 'is_gathering', False):
                    nearby_gathering += 1

        if not nearby:
            agent.is_gathering = False
            return np.array([0.0, 0.0])

        # 【传染性】如果附近有很多人在聚集，更容易加入
        gathering_contagion = nearby_gathering / len(nearby) if nearby else 0

        # 计算质心
        cx = np.mean([n.x for n in nearby])
        cy = np.mean([n.y for n in nearby])

        # 指向质心的方向
        direction = np.array([cx - agent.x, cy - agent.y])
        dist_to_center = np.linalg.norm(direction)

        if dist_to_center < 0.0002:  # 已经在中心附近
            agent.is_gathering = True
            return np.array([0.0, 0.0])

        direction = direction / dist_to_center

        # ============ 集群力强度计算 ============
        base_strength = 0.5

        # 恐慌/情绪加成
        emotional_factor = 1.0 + emotion + panic_value  # 1.0 ~ 3.0

        # 停电加成
        power_factor = 2.0 if not powered else 1.0

        # 传染性加成
        contagion_factor = 1.0 + gathering_contagion * 2.0

        # 人数加成
        crowd_factor = min(2.0, 1.0 + len(nearby) / 10.0)

        # 距离因素
        distance_factor = min(2.0, dist_to_center / 0.001)

        # 应用时间因素
        cluster_strength = (base_strength * emotional_factor * power_factor *
                            contagion_factor * crowd_factor * distance_factor *
                            night_factor)  # 深夜降低

        # 标记为正在聚集
        if cluster_strength > 0.3:
            agent.is_gathering = True

        return direction * cluster_strength

    def update_agent_position(self, agent, force, dt, region_geometry=None,
                              all_region_geometries=None):
        """
        根据力更新agent的位置

        参数:
            agent: 居民Agent
            force: [fx, fy] 力向量
            dt: 时间步长
            region_geometry: 当前区域几何（用于边界约束）
            all_region_geometries: 所有区域几何字典（用于检测空白区域）
        """
        mass = getattr(agent, 'mass', 1.0)

        # 计算加速度
        acceleration = force / mass

        # 更新速度
        velocity = getattr(agent, 'velocity', np.array([0.0, 0.0]))
        new_velocity = velocity + acceleration * dt

        # 速度限制
        speed = np.linalg.norm(new_velocity)
        max_speed = getattr(agent, 'max_speed', self.max_speed)

        # 恐慌时速度增加
        if getattr(agent, 'pts_status', False):
            max_speed *= (1.0 + getattr(agent, 'panic_value', 0) * 0.5)

        if speed > max_speed:
            new_velocity = new_velocity / speed * max_speed

        # 如果速度太小，添加最小移动保证可见
        if speed < 0.0001:
            # 向游走目标方向添加最小速度
            target = getattr(agent, '_wander_target', None)
            if target:
                direction = np.array([target[0] - agent.x, target[1] - agent.y])
                dist = np.linalg.norm(direction)
                if dist > 0.0001:
                    direction = direction / dist
                    new_velocity = direction * 0.0005  # 最小速度

        # 更新位置（直接使用速度，不再乘以dt，因为速度已经是每步的位移）
        new_x = agent.x + new_velocity[0]
        new_y = agent.y + new_velocity[1]

        # ============ 空白区域检测（山/河/无效区域）============
        # 检查新位置是否在任何有效区域内
        is_in_valid_area = False
        if all_region_geometries:
            from shapely.geometry import Point
            point = Point(new_x, new_y)
            for geom in all_region_geometries.values():
                if geom and geom.contains(point):
                    is_in_valid_area = True
                    break

            if not is_in_valid_area:
                # 新位置在空白区域（山/河），阻止移动
                # 反弹回原位置
                new_x = agent.x
                new_y = agent.y
                new_velocity = new_velocity * (-0.3)  # 反向减速

                # 重置游走目标，选择新方向
                agent._wander_timer = 0

        # 边界约束（POI绑定方案B：以POI为锚, 极端状态允许走出一些）
        # 与 ResidentDistributor.distribute_residents_by_poi 的 poi_radius=0.002 协调:
        #   正常 = 1×POI (严格圈内)
        #   停电 = 1.4×POI (略超出, 找邻近资源)
        #   PTS  = 2×POI (恐慌时走到邻近POI边界)
        #   撤离 = 2.5×POI (跨POI流动)
        home = getattr(agent, 'home_position', None)
        if home:
            # 根据状态确定最大活动范围（与POI半径协调）
            moving_to_safety = getattr(agent, '_moving_to_safety', False)
            pts_status = getattr(agent, 'pts_status', False)
            powered = getattr(agent, 'powered', True)

            if moving_to_safety:
                max_range = 0.005  # 向安全区移动: ~555m  (2.5×POI)
            elif pts_status:
                max_range = 0.004  # PTS恐慌: ~444m       (2×POI)
            elif not powered:
                max_range = 0.003  # 停电区: ~333m        (1.4×POI)
            else:
                max_range = 0.002  # 正常: ~222m         (1×POI, 严格圈内)

            dx = new_x - home[0]
            dy = new_y - home[1]
            dist_from_home = math.sqrt(dx ** 2 + dy ** 2)

            if dist_from_home > max_range:
                # 拉回到范围内
                ratio = max_range / dist_from_home
                new_x = home[0] + dx * ratio
                new_y = home[1] + dy * ratio
                # 反弹速度
                new_velocity = new_velocity * (-0.5)

        # 应用更新
        agent.x = new_x
        agent.y = new_y
        agent.velocity = new_velocity
        agent.acceleration = acceleration

        # 记录位置变化用于调试
        agent._last_move_dist = math.sqrt((new_x - agent.x) ** 2 + (new_y - agent.y) ** 2) if hasattr(agent,
                                                                                                      '_prev_x') else 0
        agent._prev_x = new_x
        agent._prev_y = new_y

    def calculate_region_panic_level(self, agents, region_id):
        """
        计算区域恐慌水平

        返回:
            panic_level: 0-1之间 → 用于地图颜色渲染
        """
        region_agents = [a for a in agents if a.zone == region_id]
        if not region_agents:
            return 0.0

        avg_emotion = np.mean([a.emotion for a in region_agents])
        avg_panic = np.mean([getattr(a, 'panic_value', 0) for a in region_agents])
        pts_ratio = sum(1 for a in region_agents
                        if getattr(a, 'pts_status', False)) / len(region_agents)

        # 综合恐慌水平
        return avg_emotion * 0.4 + avg_panic * 0.4 + pts_ratio * 0.2


class PanicModel:
    """
    恐慌传播模型 - 完整版

    基于: 恐慌模拟复现.py 和文献

    核心机制：
    1. 静态场 S_ij（理性因素，引导向安全区）
    2. 危险场 H_ij（本能反应，远离危险源）
    3. 恐慌传播 A_ij（PTS状态的传染效应）
    4. 转移概率计算（公式7）

    【可调参数】位置: config/config.py → PanicConfig
    """

    def __init__(self, config=None):
        """初始化恐慌模型"""
        # ==================== 恐慌模型参数 ====================
        # 【核心调整】恐慌需要时间累积，不会立刻达到高值
        self.D = 0.5  # 全局恐慌控制系数【大幅降低】
        self.alpha = 0.015  # 距离-恐慌敏感系数【降低】
        self.beta = 0.02  # 时间衰减系数【增加，恢复更快】
        self.pts_threshold = 0.8  # PTS恐慌阈值

        # 传播参数
        self.panic_transmission_radius = 0.001  # 恐慌传播半径（约100米）
        self.N_p = 4.4835  # 归一化因子

        # 【新增】恐慌累积机制
        self.panic_accumulation = {}  # 每个agent的累积恐慌

        # ==================== 场敏感系数（公式9-11） ====================
        self.k_sin = 0.6  # 静态场初始敏感系数（理性）
        self.k_hin = 0.4  # 危险场初始敏感系数（本能）
        self.a = 0.5  # 动态敏感调节参数

        # 危险源和出口
        self.hazard_positions = []  # [(x, y), ...]
        self.exit_positions = []  # [(x, y), ...]

        # 时间步
        self.time_step = 0

        # 从config加载参数
        if config:
            self._load_config(config)

    def _load_config(self, config):
        """从配置加载参数"""
        param_map = {
            'D': 'D', 'ALPHA': 'alpha', 'BETA': 'beta',
            'PTS_THRESHOLD': 'pts_threshold',
            'K_SIN': 'k_sin', 'K_HIN': 'k_hin', 'A': 'a',
            'PANIC_TRANSMISSION_RADIUS': 'panic_transmission_radius'
        }
        for config_name, attr_name in param_map.items():
            if hasattr(config, config_name):
                setattr(self, attr_name, getattr(config, config_name))

    def set_hazards(self, positions):
        """设置危险源位置（停电区域中心等）"""
        self.hazard_positions = list(positions) if positions else []

    def add_hazard(self, x, y):
        """添加危险源"""
        self.hazard_positions.append((x, y))

    def set_exits(self, positions):
        """设置安全出口/目标位置"""
        self.exit_positions = list(positions) if positions else []

    def calculate_static_field(self, agent):
        """
        计算静态场值（理性因素）

        静态场引导行人向安全区/出口移动
        场值与到出口距离成反比
        """
        pos = (agent.x, agent.y)

        if not self.exit_positions:
            # 使用家的位置作为"安全区"
            home = getattr(agent, 'home_position', None)
            if home:
                dist = math.sqrt((pos[0] - home[0]) ** 2 + (pos[1] - home[1]) ** 2)
                max_dist = 0.01  # 假设最大活动范围
                return max(0, (max_dist - dist) / max_dist)
            return 0.5

        # 到最近出口的距离
        min_dist = min(math.sqrt((pos[0] - ex) ** 2 + (pos[1] - ey) ** 2)
                       for ex, ey in self.exit_positions)

        # 场值与距离成反比
        max_dist = 0.02  # 最大考虑距离
        return max(0, (max_dist - min_dist) / max_dist)

    def calculate_hazard_field(self, agent):
        """
        计算危险场值（本能反应）

        危险场引导行人远离危险源
        场值与到危险源距离成正比
        """
        pos = (agent.x, agent.y)

        # 停电状态本身就是"危险"
        base_hazard = 0.0
        if not getattr(agent, 'powered', True):
            t_outage = getattr(agent, 't_outage', 0)
            base_hazard = min(0.5, 0.1 + t_outage / 100.0)  # 停电越久危险感越强

        if not self.hazard_positions:
            return base_hazard

        # 到最近危险源的距离
        min_dist = min(math.sqrt((pos[0] - hx) ** 2 + (pos[1] - hy) ** 2)
                       for hx, hy in self.hazard_positions)

        # 场值与距离成正比（离危险源越远越安全）
        max_dist = 0.01
        hazard_value = min_dist / max_dist if min_dist < max_dist else 1.0

        return max(base_hazard, 1 - hazard_value)  # 越近危险值越高

    def calculate_panic_transmission(self, agent, all_agents):
        """
        计算恐慌传播项 A_ij（公式中的传播项）

        在传播范围R内搜索PTS行人，计算恐慌传播贡献：
        A_ij = Σ [exp(-L_k) / (1 + L_k)] / N_p

        其中L_k是到PTS行人的距离
        """
        A_ij = 0.0
        R = self.panic_transmission_radius
        pts_count = 0

        for other in all_agents:
            if other is agent:
                continue

            # 只有PTS状态的人才能传播恐慌
            if not getattr(other, 'pts_status', False):
                continue

            # 计算距离
            dx = agent.x - other.x
            dy = agent.y - other.y
            L_k = math.sqrt(dx ** 2 + dy ** 2)

            if L_k <= R and L_k > 0:
                # 距离越近，传播贡献越大
                A_ij += np.exp(-L_k * 1000) / (1 + L_k * 1000)  # 缩放到合适范围
                pts_count += 1

        # 归一化
        if pts_count > 0:
            A_ij = A_ij / self.N_p

        return min(A_ij, 1.0)

    def calculate_panic_value(self, agent, all_agents):
        """
        计算单个agent的恐慌值（公式5）

        P = D * [(1 - exp(-α*l_c)) / (1 + exp(α*l_o)) + A_ij] * exp(-β*t)

        其中：
        - l_c: 到出口的"距离因子"
        - l_o: 到危险源的"距离因子"
        - A_ij: 恐慌传播项
        - t: 时间
        """
        pos = (agent.x, agent.y)

        # ==================== 距离计算 ====================
        # 到安全区的距离因子
        if self.exit_positions:
            l_c = min(math.sqrt((pos[0] - ex) ** 2 + (pos[1] - ey) ** 2)
                      for ex, ey in self.exit_positions) * 1000  # 缩放
        else:
            # 没有出口时，使用与家的距离
            home = getattr(agent, 'home_position', None)
            if home:
                l_c = math.sqrt((pos[0] - home[0]) ** 2 + (pos[1] - home[1]) ** 2) * 1000
            else:
                l_c = 1.0

        # 到危险源的距离因子
        if self.hazard_positions:
            l_o = min(math.sqrt((pos[0] - hx) ** 2 + (pos[1] - hy) ** 2)
                      for hx, hy in self.hazard_positions) * 1000
        else:
            l_o = 10.0  # 无危险源时设为较大值

        # 停电增加危险感（但增长更平缓）
        if not getattr(agent, 'powered', True):
            t_outage = getattr(agent, 't_outage', 0)
            # 【调整】降低停电对危险感知的影响，使用对数增长而非线性
            outage_effect = min(5.0, t_outage * 0.02)  # 最多减少5，增长更慢
            l_o = max(0.5, l_o - outage_effect)  # 最小值提高到0.5

        # ==================== 恐慌传播项 ====================
        A_ij = self.calculate_panic_transmission(agent, all_agents)

        # ==================== 恐慌值计算（公式5） ====================
        # 基础恐慌项
        term1 = (1 - np.exp(-self.alpha * l_c)) / (1 + np.exp(self.alpha * l_o))

        # 时间衰减（随时间恐慌有所减缓）
        # 【调整】即使有危险也有轻微衰减，避免恐慌持续累积
        if self.hazard_positions or not getattr(agent, 'powered', True):
            time_decay = max(0.7, np.exp(-self.beta * self.time_step * 0.5))  # 最低0.7
        else:
            time_decay = np.exp(-self.beta * self.time_step)

        # 最终恐慌值
        panic = self.D * (term1 + A_ij) * time_decay

        # 【恐慌累积机制】恐慌不会立刻达到高值，需要时间累积
        instant_panic = panic / 10.0  # 当前瞬时恐慌（归一化）
        instant_panic = max(0, min(1, instant_panic))

        # 获取之前的累积恐慌
        agent_id = id(agent)
        prev_panic = self.panic_accumulation.get(agent_id, 0.0)

        # 恐慌累积：每步最多增加0.02，最多减少0.01
        # 这样从0到0.5需要至少25步（6小时），到0.8需要40步（10小时）
        if instant_panic > prev_panic:
            # 恐慌上升：缓慢累积
            delta = min(0.02, (instant_panic - prev_panic) * 0.1)
            new_panic = prev_panic + delta
        else:
            # 恐慌下降：缓慢恢复
            delta = min(0.01, (prev_panic - instant_panic) * 0.05)
            new_panic = prev_panic - delta

        # 停电时间越长，恐慌上限越高
        t_outage = getattr(agent, 't_outage', 0)
        # 第1天最高0.4，第2天最高0.6，第3天最高0.8，第4天才能到1.0
        max_panic_by_time = min(1.0, 0.2 + t_outage / 72.0)  # 72小时=3天

        new_panic = min(new_panic, max_panic_by_time)
        new_panic = max(0, min(1, new_panic))

        # 保存累积值
        self.panic_accumulation[agent_id] = new_panic

        return new_panic

    def calculate_dynamic_sensitivity(self, panic_value):
        """
        计算动态敏感系数（公式9-11）

        恐慌值越高 → 本能反应越强（k_h增加）
        恐慌值越低 → 理性因素越强（k_s增加）

        返回:
            (k_s, k_h): 理性和本能的敏感系数
        """
        # 公式9: S = k_sin * exp(-a*p) + k_hin * exp(a*p)
        S = (self.k_sin * np.exp(-self.a * panic_value) +
             self.k_hin * np.exp(self.a * panic_value))

        # 公式10: k_s = k_sin * exp(-a*p) / S
        k_s = (self.k_sin * np.exp(-self.a * panic_value)) / S

        # 公式11: k_h = k_hin * exp(a*p) / S
        k_h = (self.k_hin * np.exp(self.a * panic_value)) / S

        return k_s, k_h

    def calculate_transition_probabilities(self, agent, neighbors):
        """
        计算转移概率（公式7）

        P_ij ∝ exp(k_s * S_ij + k_h * H_ij)

        用于确定agent移动的方向

        返回:
            probabilities: 3x3的概率矩阵（相对于当前位置的9个方向）
        """
        panic_value = getattr(agent, 'panic_value', 0)
        k_s, k_h = self.calculate_dynamic_sensitivity(panic_value)

        # 计算9个方向的概率
        probabilities = np.zeros((3, 3))
        step_size = 0.0001  # 移动步长

        for di in [-1, 0, 1]:
            for dj in [-1, 0, 1]:
                # 候选位置
                new_x = agent.x + di * step_size
                new_y = agent.y + dj * step_size

                # 创建临时位置对象
                class TempPos:
                    def __init__(self, x, y):
                        self.x = x
                        self.y = y

                temp = TempPos(new_x, new_y)
                temp.powered = getattr(agent, 'powered', True)
                temp.home_position = getattr(agent, 'home_position', None)

                # 计算场值
                static_val = self.calculate_static_field(temp)
                hazard_val = self.calculate_hazard_field(temp)

                # 转移概率 (公式7)
                # 注意：危险场是要远离的，所以用hazard_val（值越高越危险，应该避开）
                prob = np.exp(k_s * static_val - k_h * hazard_val * 0.5)

                probabilities[di + 1, dj + 1] = prob

        # 归一化
        total = np.sum(probabilities)
        if total > 0:
            probabilities /= total
        else:
            probabilities = np.ones((3, 3)) / 9.0

        return probabilities

    def update_panic_states(self, agents, dt=1.0):
        """
        更新所有agent的恐慌状态

        【重要修复】
        不再直接覆盖 agent.panic_value，因为 ResidentAgent._update_panic()
        有更精细的长尾效应处理。这里只更新 PTS 状态。

        参数:
            agents: 居民Agent列表
            dt: 时间步长
        """
        self.time_step += 1

        # 【修复】不再直接设置恐慌值，交给 ResidentAgent._update_panic() 处理
        # 这里只同步 PTS 状态
        for agent in agents:
            # PTS状态由当前恐慌值决定
            agent.pts_status = getattr(agent, 'panic_value', 0) > self.pts_threshold

    def get_all_panic_levels(self, agents):
        """获取所有agent的恐慌值列表"""
        return [getattr(a, 'panic_value', 0) for a in agents]

    def get_pts_count(self, agents):
        """获取PTS状态的人数"""
        return sum(1 for a in agents if getattr(a, 'pts_status', False))

    def get_statistics(self, agents):
        """
        获取恐慌统计信息

        返回:
            dict: 统计数据 → 用于图表
        """
        panic_values = self.get_all_panic_levels(agents)
        pts_count = self.get_pts_count(agents)

        return {
            'avg_panic': np.mean(panic_values) if panic_values else 0,
            'max_panic': max(panic_values) if panic_values else 0,
            'min_panic': min(panic_values) if panic_values else 0,
            'pts_count': pts_count,
            'pts_ratio': pts_count / len(agents) if agents else 0,
        }


class IntegratedForceCalculator:
    """
    综合力计算器 - 整合社会力和恐慌模型

    功能：
    - 统一计算居民受到的所有力
    - 协调社会力和恐慌行为
    - 更新居民位置
    - 提供统计接口

    【数据输出】用于可视化
    - calculate_force() → 力向量
    - calculate_region_panic_levels() → 区域恐慌水平 → 地图颜色
    - get_statistics() → 统计数据 → 图表
    """

    def __init__(self, social_force_config=None, panic_config=None):
        """初始化综合力计算器"""
        self.social_force_model = SocialForceModel(social_force_config)
        self.panic_model = PanicModel(panic_config)
        self.stores = []  # 商店列表（行为切换模型需要）
        self.sw = SwitchParams()  # 行为切换参数

    def update(self, agents, dt=1.0, hazard_positions=None, region_geometries=None,
               zone_status=None, region_centroids=None):
        """
        更新所有agent的状态和位置

        参数:
            agents: 居民Agent列表
            dt: 时间步长
            hazard_positions: 危险源位置（停电区域中心）
            region_geometries: 区域几何字典 {zone_id: geometry}
            zone_status: 区域供电状态 {zone_id: True/False}
            region_centroids: 区域中心点 {zone_id: Point}
        """
        # 设置危险源
        if hazard_positions:
            self.panic_model.set_hazards(hazard_positions)

        # 更新恐慌状态
        # self.panic_model.update_panic_states(agents, dt)
        # 停用：panic_value 现由 ResidentAgent.step 的 P=σ^0.8 统一给出（§3.2.4）
        #       否则会覆盖 stress 派生的 panic_value

        # ============ 计算有电区域的吸引点 ============
        safe_zones = []
        if zone_status and region_centroids:
            for zone_id, is_powered in zone_status.items():
                if is_powered and zone_id in region_centroids:
                    centroid = region_centroids[zone_id]
                    safe_zones.append((centroid.x, centroid.y, zone_id))

        # ============ 为每个agent设置安全区域目标 ============
        for agent in agents:
            if self.stores:
                update_perceived_occupancy(agent, self.stores, self.sw)
            if not getattr(agent, 'powered', True) and safe_zones:
                # 找最近的有电区域
                min_dist = float('inf')
                nearest_safe = None
                for sx, sy, sz in safe_zones:
                    dist = math.sqrt((agent.x - sx) ** 2 + (agent.y - sy) ** 2)
                    if dist < min_dist:
                        min_dist = dist
                        nearest_safe = (sx, sy)

                # 设置安全区域目标（稍微偏移以避免集中在一点）
                if nearest_safe and min_dist < 0.01:  # 只考虑1km内的安全区域
                    offset_x = (random.random() - 0.5) * 0.002
                    offset_y = (random.random() - 0.5) * 0.002
                    agent._safe_zone_target = (nearest_safe[0] + offset_x,
                                               nearest_safe[1] + offset_y)
                else:
                    agent._safe_zone_target = None
            else:
                agent._safe_zone_target = None

        # ============ 计算并应用力，更新位置 ============
        for agent in agents:
            # 获取邻居
            neighbors = getattr(agent, 'neighbors', agents[:20])  # 限制计算数量

            # 计算总力
            force = self.social_force_model.calculate_total_force(agent, agents, neighbors)

            # 获取区域几何约束
            region_geom = None
            if region_geometries and agent.zone is not None:
                region_geom = region_geometries.get(agent.zone)

            # 更新位置（传递所有区域几何用于空白区域检测）
            self.social_force_model.update_agent_position(
                agent, force, dt, region_geom,
                all_region_geometries=region_geometries
            )

    def calculate_force(self, agent, neighbors):
        """计算单个agent受到的综合力"""
        return self.social_force_model.calculate_total_force(agent, [], neighbors)

    def calculate_region_panic_levels(self, agents, region_ids):
        """
        计算所有区域的恐慌水平

        返回:
            dict: {region_id: panic_level} → 用于地图颜色渲染
        """
        levels = {}
        for region_id in region_ids:
            levels[region_id] = self.social_force_model.calculate_region_panic_level(
                agents, region_id
            )
        return levels

    def get_statistics(self, agents):
        """
        获取统计信息

        返回:
            dict: 统计数据 → 用于图表显示
        """
        return self.panic_model.get_statistics(agents)

    def get_transition_probabilities(self, agent, neighbors):
        """获取转移概率矩阵"""
        return self.panic_model.calculate_transition_probabilities(agent, neighbors)