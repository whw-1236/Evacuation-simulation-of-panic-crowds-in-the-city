# -*- coding: utf-8 -*-
"""
================================================================================
SimulationConfig — 论文超参数集中管理
================================================================================
对应 Methodology Table 2，所有参数集中在此，消融实验直接改这里。

使用:
    from config.simulation_config import SimulationConfig, AblationPreset
    cfg = SimulationConfig()              # 默认参数
    cfg_ablate = AblationPreset.hard_switch()  # 消融: 硬切换
    cfg_ablate = AblationPreset.no_inertia()   # 消融: 无Leader惯性
================================================================================
"""
from dataclasses import dataclass, field
from core.behavior_switching import SwitchParams


# =============================================================================
# I1/I2/I3 参数 (从 behavior_switching.SwitchParams 展开，方便直接访问)
# =============================================================================
@dataclass
class SimulationConfig:
    """论文全部超参数的统一配置"""

    # ---- I1: 三阶段阈值 & sigmoid陡度 (Eq.11) ----
    theta1: float = 0.4            # home→hoard 断点 (对应 stress=0.4)
    theta2: float = 0.6            # hoard→herd 断点 (对应 stress=0.6)
    k1: float = 10.0               # home权重下降陡度
    k2: float = 10.0               # hoard权重上升陡度
    k3: float = 10.0               # hoard权重下降陡度
    k4: float = 10.0               # herd权重上升陡度
    lambda_pts: float = 2.0        # PTS触发从众的强化系数
    supply_threshold: float = 0.35  # 个人物资低于此→触发囤积需要 H_i=1

    # ---- I2: 商店效用 (Eq.13-14) ----
    lambda_d: float = 0.5          # 距离权重
    lambda_f: float = 0.3          # 熟悉度权重
    lambda_c: float = 0.4          # 感知占用率权重
    dist_scale: float = 0.01       # 距离归一化 (~1km)
    gamma: float = 0.3             # 感知占用学习率
    fam_scale: float = 0.005       # 熟悉度衰减距离 (~500m)
    arrival_radius: float = 0.0005  # agent到达商店的判定距离

    # ---- I3: Leader惯性 (Eqs.15-16) ----
    mu: float = 1.3                # 滞后系数 (>1, mu=1→每步重选)
    alpha_s: float = 0.5           # 情绪稳定性权重
    alpha_f: float = 0.3           # 熟悉度权重
    alpha_v: float = 0.2           # 视野可见性权重

    # ---- I1 扩展 P1.A: 行为切换迟滞带 (2026-06-13) ----
    delta_hoard: float = 0.08      # σ < θ₁-δ_hoard 才退出囤积态
    delta_herd: float = 0.10       # σ < θ₂-δ_herd 才退出从众态
    enable_hysteresis: bool = True

    # ---- I1 扩展 P1.B: 行为结果反馈 σ ----
    feedback_hoard_success: float = -0.07   # 囤积成功 -> σ 下降脉冲
    feedback_hoard_failure: float = 0.11    # 囤积失败 -> σ 上升脉冲
    feedback_herd_smooth:   float = -0.04   # 跟随Leader成功疏散
    feedback_herd_jam:      float = 0.06    # 跟随Leader陷入拥堵
    feedback_failure_amplify_repeat: float = 0.2  # 连续失败放大系数
    enable_outcome_feedback: bool = True

    # ---- I1 扩展 P2: 行为示范对 θ 的压低 ----
    eta_demo_hoard: float = 0.12   # 邻居囤积比例对 θ₁ 的压低系数
    eta_demo_herd:  float = 0.15   # 邻居从众比例对 θ₂ 的压低系数
    enable_behavior_demo: bool = True

    # ---- I1 扩展 P3: 信息搜寻第四态 ----
    theta_mild: float = 0.2        # inquire 态下边界 (σ)
    k5:         float = 10.0       # inquire sigmoid 陡度
    inquire_radius: float = 0.01   # 信息搜寻半径 (~1 km)
    enable_inquire: bool = False   # 默认关闭，避免破坏 baseline

    # ---- 社会力模型 ----
    A: float = 2000.0              # 社会力强度 (N)
    B: float = 0.08                # 社会力范围 (m)
    tau: float = 0.5               # 松弛时间 (s)
    K_body: float = 1.2e5          # 身体力弹性常数
    k_friction: float = 2.4e5      # 摩擦力常数
    lambda_anisotropy: float = 0.5  # 各向异性因子 (后方影响=前方×λ)

    # ---- 速度模型 (Greenshields) ----
    v_free: float = 1.3            # 自由流速度 (m/s)
    v_max: float = 2.0             # 最大速度 (m/s)
    rho_jam: float = 5.4           # 堵塞密度 (pers/m²)
    g_max: float = 1.37            # 恐慌加速因子 (来自实证文献)

    # ---- 统一压力模型 ----
    threshold_mild: float = 0.2    # 轻度焦虑
    threshold_moderate: float = 0.4  # 中度焦虑 (囤积开始)
    threshold_high: float = 0.6      # 高度恐慌 (从众开始)
    threshold_extreme: float = 0.8   # 极度恐慌 (PTS触发)
    latent_reaction_factor: float = 0.5
    outage_threat_coef: float = 0.25
    base_internal_coef: float = 0.15

    # ---- SEIR信息传播 ----
    beta_seir: float = 0.15        # 感染率
    incubation_period: int = 4      # 潜伏期 (步)
    recovery_period: int = 24       # 恢复期 (步)

    # ---- 仿真设置 ----
    N: int = 1000                   # 居民数量
    dt: float = 0.25                # 时间步长 (h), 15min
    total_steps: int = 384          # 总步数 (默认96h = 4天)
    seed: int = 42                  # 随机种子

    # ---- 停电场景 ----
    damage: float = 0.7             # 损坏程度
    repair_difficulty: float = 30.0  # 修复难度

    # ---- 网格修复 ----
    kappa_0: float = 1.5            # 基础修复能力 (h⁻¹)
    e_0: float = 0.3
    e_max: float = 1.2
    R_half: float = 80.0

    # ------------------------------------------------------------------
    # 便捷方法
    # ------------------------------------------------------------------
    def to_switch_params(self) -> SwitchParams:
        """导出为 behavior_switching 模块需要的 SwitchParams"""
        return SwitchParams(
            theta1=self.theta1, theta2=self.theta2,
            k1=self.k1, k2=self.k2, k3=self.k3, k4=self.k4,
            lambda_pts=self.lambda_pts, supply_threshold=self.supply_threshold,
            lambda_d=self.lambda_d, lambda_f=self.lambda_f, lambda_c=self.lambda_c,
            dist_scale=self.dist_scale, gamma=self.gamma, fam_scale=self.fam_scale,
            arrival_radius=self.arrival_radius,
            mu=self.mu, alpha_s=self.alpha_s, alpha_f=self.alpha_f, alpha_v=self.alpha_v,
            # P1.A
            delta_hoard=self.delta_hoard, delta_herd=self.delta_herd,
            enable_hysteresis=self.enable_hysteresis,
            # P1.B
            feedback_hoard_success=self.feedback_hoard_success,
            feedback_hoard_failure=self.feedback_hoard_failure,
            feedback_herd_smooth=self.feedback_herd_smooth,
            feedback_herd_jam=self.feedback_herd_jam,
            feedback_failure_amplify_repeat=self.feedback_failure_amplify_repeat,
            enable_outcome_feedback=self.enable_outcome_feedback,
            # P2
            eta_demo_hoard=self.eta_demo_hoard,
            eta_demo_herd=self.eta_demo_herd,
            enable_behavior_demo=self.enable_behavior_demo,
            # P3
            theta_mild=self.theta_mild, k5=self.k5,
            inquire_radius=self.inquire_radius,
            enable_inquire=self.enable_inquire,
        )

    def clone(self, **overrides):
        """返回修改了某些参数的新配置（不改原对象）"""
        d = {k: v for k, v in self.__dict__.items()}
        d.update(overrides)
        return SimulationConfig(**d)


# =============================================================================
# 消融实验预设 (对应 Experiment 2 消融矩阵)
# =============================================================================
class AblationPreset:
    """消融实验的参数预设 — 每个类方法返回一个新的 SimulationConfig"""

    @staticmethod
    def default() -> SimulationConfig:
        """默认参数（基线）"""
        return SimulationConfig()

    @staticmethod
    def hard_switch() -> SimulationConfig:
        """E2.2 硬切换消融: k→∞ 退化为硬阈值"""
        return SimulationConfig(k1=50.0, k2=50.0, k3=50.0, k4=50.0)

    @staticmethod
    def no_info_network() -> SimulationConfig:
        """E2.3 无信息网消融: λ_c=0 不看感知占用"""
        return SimulationConfig(lambda_c=0.0, gamma=0.0)

    @staticmethod
    def no_inertia() -> SimulationConfig:
        """E2.4 无Leader惯性消融: μ=1.0 每步重选"""
        return SimulationConfig(mu=1.0)

    @staticmethod
    def no_personality() -> SimulationConfig:
        """E2.5 无OCEAN异质性消融: 所有人同参数"""
        # 此消融需在 agents.py 中配合修改 OCEAN 采样逻辑
        return SimulationConfig()

    @staticmethod
    def soft_switch() -> SimulationConfig:
        """软切换对照组: 降低陡度"""
        return SimulationConfig(k1=1.0, k2=1.0, k3=1.0, k4=1.0)

    @staticmethod
    def distance_only_store() -> SimulationConfig:
        """只看距离选商店: λ_f=λ_c=0"""
        return SimulationConfig(lambda_f=0.0, lambda_c=0.0)

    # ---- I1 扩展消融 (2026-06-13) ----
    @staticmethod
    def no_hysteresis() -> SimulationConfig:
        """E2.6 关闭行为切换迟滞带（验证 P1.A 贡献）"""
        return SimulationConfig(enable_hysteresis=False)

    @staticmethod
    def no_outcome_feedback() -> SimulationConfig:
        """E2.7 关闭行为结果反馈 σ（验证 P1.B 贡献）"""
        return SimulationConfig(enable_outcome_feedback=False)

    @staticmethod
    def no_behavior_demo() -> SimulationConfig:
        """E2.8 关闭行为示范阈值压低（验证 P2 贡献）"""
        return SimulationConfig(enable_behavior_demo=False)

    @staticmethod
    def with_inquire() -> SimulationConfig:
        """E2.9 启用信息搜寻第四态（验证 P3 贡献）"""
        return SimulationConfig(enable_inquire=True)

    @staticmethod
    def i1_minimal() -> SimulationConfig:
        """关闭全部 I1 扩展（P1.A + P1.B + P2 + P3 全部关）"""
        return SimulationConfig(
            enable_hysteresis=False,
            enable_outcome_feedback=False,
            enable_behavior_demo=False,
            enable_inquire=False,
        )


# =============================================================================
# 参数网格扫描 (对应 Experiment 2 敏感性分析)
# =============================================================================
def theta_grid():
    """生成 θ₁×θ₂ 的 5×5 网格 (满足 θ₂-θ₁≥0.2)"""
    configs = []
    for t1 in [0.20, 0.25, 0.30, 0.35, 0.40]:
        for t2 in [0.55, 0.60, 0.65, 0.70, 0.75]:
            if t2 - t1 >= 0.20:
                configs.append(SimulationConfig(theta1=t1, theta2=t2))
    return configs


# =============================================================================
# 自检
# =============================================================================
if __name__ == "__main__":
    cfg = SimulationConfig()
    print(f"Default: θ₁={cfg.theta1}, θ₂={cfg.theta2}, μ={cfg.mu}")
    sp = cfg.to_switch_params()
    print(f"SwitchParams: θ₁={sp.theta1}, θ₂={sp.theta2}, μ={sp.mu}")

    hard = AblationPreset.hard_switch()
    print(f"Hard switch: k1-4 = {hard.k1}")

    no_iner = AblationPreset.no_inertia()
    print(f"No inertia: μ = {no_iner.mu}")

    grid = theta_grid()
    print(f"Theta grid: {len(grid)} valid combinations")
