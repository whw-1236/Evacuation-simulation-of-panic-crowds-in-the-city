# Evacuation-simulation-of-panic-crowds-in-the-city
Python simulation model for panic crowd evacuation in urban public space.
# 城市大停电人群行为动态仿真系统 — 功能说明文档

本项目是基于多智能体的城市停电应急仿真系统，用于模拟大规模停电事件下居民的心理-行为动态、基础设施响应以及政府/电网的应急决策过程。该系统对应 IJDRR 论文 *"城市大停电下的人群行为动态仿真研究"* 的 Methodology 第3章，所有模块均与论文公式对齐。

> **PTS 定义修订（2026-06-12 已确认）**：`pts_status` 由 **σ 迟滞带** 控制：进入 σ ≥ 0.8 × 性格系数（封顶 0.95）、退出 σ < 0.5 × 性格系数（迟滞带 0.3）；非永久锁存。基准取 EXTREME（0.8），PTS 为少数极端态。依据文献（SIR 含 Recovered 态、P-SIS 情绪可逆、伊比利亚大停电情绪随恢复消退）：PTS 不永久锁存但需迟滞。

---

## 1. 多主体仿真系统

系统模拟五类主体在停电事件中的行为和交互：

- **政府主体** (GovernmentAgent)：负责应急资源调配和信息发布，具有积极性和响应效率两个核心参数。根据社会意见压力指数 Π 触发预警、资源拨付等决策。

- **电网主体** (PowerGridAgent)：负责故障修复和供电恢复，具有积极性、响应效率和故障传播率三个核心参数。修复能力受资源投入和群体恐慌的双向影响（宏观反馈环）。

- **企业主体** (EnterpriseAgent)：模拟企业在停电时的求助行为和累积损失，发出资源请求信号。

- **居民主体** (ResidentAgent)：**核心建模对象**。具有 OCEAN 五因素人格、统一心理压力状态 σ(t)、情绪 E(t)、恐慌 P(t) 和 PTS 状态，以及由应力驱动的三阶段行为切换（回家→囤积→从众）。

- **关键基础设施主体** (CriticalInfraAgent)：包括医院、学校、应急机构、政府机构、社区卫生院、工业企业六类，具有优先级和备用电源属性，发出公共影响信号。

---

## 2. 统一心理压力模型（心理层）

**理论基础**：Lazarus 应激-评估-应对理论 (Lazarus & Folkman, 1984)

### 2.1 主应力状态 σ(t)

单一主应力变量 σ_i(t) ∈ [0,1] 通过 ODE 驱动：

```
dσ/dt = α·T·(1-σ) - β·C·σ + γ·(σ̄-σ) + Σ(事件影响)
```

- T：威胁感知（停电时长、物资缺口、邻居恐慌、信息缺失、健康脆弱性）
- C：应对资源（政府支持、个人韧性、社交支持、信息获取、物资储备）
- σ̄：邻居距离加权平均应力（社会传染）
- α/β/γ：个体差异系数（由 OCEAN 人格和 SEIR 信息状态决定）

### 2.2 行为触发阈值（性格化）

所有阈值均为 **基准常数 × 性格系数**（`unified_stress_model._update_behavior_states`）。基准常数：

| 阈值名 | 基准值 | 触发行为 |
|------|:--:|------|
| 轻度焦虑 MILD | 0.2 | 开始关注信息 |
| 中度焦虑 MODERATE | 0.4 | 触发囤积行为（θ₁）、请求供电 |
| 高度恐慌 HIGH | 0.6 | 触发从众（θ₂）、情绪爆发（`is_emotion_burst`，与 PTS 解耦） |
| 极度恐慌 EXTREME | 0.8 | **PTS 进入阈值**（`pts_status`） |

> PTS 退出阈值 0.5×mult，迟滞带 0.3（进入 0.8×mult / 退出 0.5×mult）。性格系数（mult）：焦虑型 0.7 / 敏感型 0.85 / 普通型 1.0 / 稳定型 1.15 / 理性型 1.3（封顶 0.95）。

### 2.3 派生变量

- **情绪 E(t)**：σ(t) 经 Pe/Pc 双因子激发-平复包络调制后的外显情绪
- **恐慌 P(t)**：σ(t)^0.8 的急性放大表达（**仅作显示量，不用于触发 PTS**）
- **PTS 状态 Z(t)**：由 **σ 迟滞带** 控制——进入 σ ≥ 0.8×mult（封顶 0.95）、退出 σ < 0.5×mult（迟滞带 0.3）；非永久锁存。PTS 为少数极端态（典型 5–20%）。与 `is_emotion_burst`（σ≥0.6×mult）已解耦。依据文献（SIR 含 Recovered 态、P-SIS 情绪可逆、伊比利亚大停电情绪随恢复消退）：PTS 不永久锁存但需迟滞。

### 2.4 OCEAN 人格异质性

每个居民从 OCEAN 五因素向量导出共情系数 ε，决定个体在应力敏感度 α_i、恢复能力 β_i、情绪激发/平复速率 α₁/α₂ 上的差异，并经 `personality` 类型映射为 PTS/行为阈值的性格系数 mult。

---

## 3. 三阶段行为切换（核心创新 I1/I2/I3）

由 `core/behavior_switching.py` 实现，对应论文 Eq.(10)-(16)。

### 3.1 I1 — 应力驱动的 sigmoid 软切换

三个候选目标方向按其 sigmoid 权重加权合成：

- **回家** w_home：σ < θ₁ 时主导
- **囤积** w_hoard：θ₁ ≤ σ < θ₂ 且物资低于阈值时主导
- **从众** w_herd：σ ≥ θ₂ 或 PTS 时主导

权重使用 logistic 函数平滑过渡（软切换），避免硬阈值的行为抖动。陡度参数 k₁~k₄ 控制切换锐度（消融：k→∞ 退化为硬切换）。

### 3.2 I2 — 熟人网络商店选择

商店效用函数 U_i(s) = -λ_d·d(i,s) + λ_f·f_i(s) - λ_c·ô_i(s)：

- d：距离
- f_i(s)：个人熟悉度（随访问增加）
- ô_i(s)：**感知占用率**（仅通过熟人 gossip 更新，非全局广播）

信息不对称导致不同 agent 对同一商店持有不同信念，产生自加强的非均衡挤兑（消融：λ_c=0 退化为仅看距离）。

### 3.3 I3 — Leader 惯性选择与滞后带

Leader 评分 = α_s·(1-E_j) + α_f·f_ij + α_v·可见性

**滞后切换规则**：新候选者得分必须超过当前 leader 的 μ 倍（μ=1.3）才切换，防止每步重选导致的羊群崩溃（消融：μ=1.0 退化为无惯性）。

### 3.4 I1 扩展（2026-06-13 新增 P1.A / P1.B / P2 / P3）

四项独立可消融增强（全部受 `SwitchParams` 开关控制）：

| 编号 | 名称 | 机制 | 关键参数 / 字段 |
|:--:|------|------|------|
| **P1.A** | 行为切换迟滞带 | 囤积/从众进入 σ≥θ / 退出 σ<θ-δ；通过 `agent._hoard_active`、`_herd_active` 状态记忆实现，避免阈值附近反复抖动 | `delta_hoard=0.08`, `delta_herd=0.10`, `enable_hysteresis` |
| **P1.B** | 结果反馈 σ（再评估） | 囤积成功/失败、跟随 Leader 顺利疏散/陷入拥堵 → 对 σ 加正/负脉冲（Lazarus secondary appraisal） | `feedback_hoard_success=-0.07`, `feedback_hoard_failure=+0.11`, `feedback_herd_jam=+0.06`, `feedback_failure_amplify_repeat=0.2` |
| **P2** | 行为示范压低 θ | θ_eff = θ × mult - η · 邻居同行为比例；η 由 OCEAN 宜人性调节。结果写入 `agent._theta1_eff`、`_theta2_eff` | `eta_demo_hoard=0.12`, `eta_demo_herd=0.15`, `enable_behavior_demo` |
| **P3** | 信息搜寻第四态 | σ∈[θ_mild, θ₁) 且 SEIR∈{S,E} 时激活 w_inquire，朝最近信息节点移动；此时 `_goal_shares` 扩为 4-tuple | `theta_mild=0.2`, `k5=10`, `inquire_radius=0.01`, `enable_inquire`（默认关闭，避免破坏 baseline） |

四项扩展可独立消融，对应 AblationPreset 的 `no_hysteresis()` / `no_outcome_feedback()` / `no_behavior_demo()` / `with_inquire()` / `i1_minimal()`（详见 §9.2）。

---

## 4. 社会力模型（行为层执行）

由 `core/social_force.py` 实现，基于 Helbing & Molnár (1995) 经典社会力模型：

- **驱动力**：f⁰ = m·(v⁰·d(t) - v)/τ，其中期望方向 d(t) 由 I1 的 compute_goal_direction() 计算
- **社会心理力**：f^soc = A·exp((r-d)/B)·n·w(φ)，含各向异性因子
- **身体接触力**：f^body = K·Θ(r-d)·n + κ·Θ(r-d)·Δv^t·t

### 4.1 Greenshields 速度-密度模型

期望速度 v⁰ = min(v_max, g(E)·v_free·(1-ρ/ρ_jam))：

- ρ：局部密度
- ρ_jam：堵塞密度 (5.4 pers/m²)
- g(E)：恐慌加速因子 (1.0~1.37，来自实证文献)
- 恐慌者欲快走，但拥挤降低可达速度 → 拥堵自加强

---

## 5. 信息传播系统（三通道独立）

| 通道 | 机制 | 模块位置 |
|------|------|------|
| 灾情/官方信息 | SEIR 传染模型（S→E→I→R），知悉者应力敏感性降低 | agents.py: _update_seir_state |
| 物资点实时占用率 | 熟人网络 gossip（I2） | behavior_switching.py: update_perceived_occupancy |
| 恐慌情绪 | 距离衰减社会传染（γ(σ̄-σ)项） | unified_stress_model.py |

三通道机制不同、互不广播；gossip 的局部性是非均衡挤兑的根源。

---

## 6. 社会技术环境（宏观反馈环）

### 6.1 停电与故障模型

支持 **8 种停电原因**（config/config.py: OUTAGE_CAUSES）：

| 原因 | 损坏程度 | 预估修复时间 |
|------|------|------|
| 过载跳闸 | 20% | 4-8 小时 |
| 设备故障 | 50% | 12-24 小时 |
| 外力破坏 | 70% | 1-2 天 |
| 自然灾害 | 90% | 2-4 天 |
| 计划停电 | 0% | 无需修复 |
| 台风过境 | 85% | 3-7 天 |
| 导弹袭击 | 95% | 7-14 天 |
| 战争破坏 | 100% | 14-30 天 |

### 6.2 电网修复动态

修复进度 φ = W_done/W_c，每步增量 ΔW = κ_eff·Δt。有效修复能力 κ_eff 受群体恐慌抑制（χ_ECR 因子）——恐慌越严重，修复越慢。

### 6.3 政府决策

采用规则专家系统（decision/rule_based.py）：
- 读取各区的应力/恐慌/企业求助均值
- 情境分类（正常/危机/紧急，对应 `response_state` = normal/warning/emergency）
- 触发政府 5 事件 + 电网 2 事件
- 资源按 0.5/0.3/0.2 比例分配给电网/企业/居民

### 6.4 宏观反馈闭环

```
停电 → 居民σ↑ → E↑, P↑ → 囤积/从众 → 聚集密度↑
    → 恐慌传播加速 → σ↑↑ → 社会压力Π↑ → 政府响应
    → 电网修复（但被 χ_ECR 抑制）→ 供电恢复 → σ↓
```

---

## 7. 区域管理系统

由 `core/region_manager.py` 实现：

- 加载 GeoJSON 城市行政区划边界数据
- 自动将居民和企业分布到各区域
- 管理区域级停电状态和故障严重程度
- 加载 CSV 节点数据（医院/学校/工业/应急/政府/社区卫生院六类设施）
- 支持多城市切换（config/city_manager.py）
- 支持行政区独立停电模式（指定区域选择性停电）

---

## 8. 可视化与输出

由 `visualization/` 模块提供（一键启动入口：`python run_dashboard.py`）：

- **`dashboard.py` SimulationDashboard**：交互式仪表盘（matplotlib + Tk 后端）
  - 控制面板：▶启动/⏸暂停/↺重置；居民数 / 停电步 / 总步数滑块；1x/2x/4x 速度；full/partial 停电模式；散点/热力图/密度/流向图层切换
  - 多 Run 对比：勾选"对比模式"将历史 run 以虚线叠加；支持加载 `step_history.json`
  - 按区县分解指标：全局 / 分区 / SEIR 三选项卡
  - 帧缓存导出 GIF（PillowWriter）
- **`small_area_viewer.py` 区域地图渲染**：居民点情绪用 4 级填充色随 σ 变化（绿→琥珀→橙→红），PTS 用紫色独立描边（读 `pts_status` bool，不阈值反算）；区域面按停电 4 态着色
- **`trace_plotter.py` 时间序列追踪**：绘制情绪/恐慌/停电恢复的时序曲线

### 输出数据

- **`output/`**：仪表盘截图、概览图（`overview.png`）、追踪图（`traces.png`）、每步全量 history JSON（`step_history.json`）
- **`trace_output/run_<时间戳>_<tag>/`**：每次仿真自动新建子目录存储节流写入的 trace CSV（默认每 25 步 flush 一次；`--tag` 可加实验标签便于筛选）
- 每步输出 JSON（GeoJSON 格式）：
  - 点数据：居民的位置、SEIR 状态、情绪等级、恐慌值、PTS 状态、移动速度/方向、目标份额(home/hoard/herd[/inquire])
  - 面数据：各区域的停电状态、平均情绪、PTS 比例、恐慌指数、修复状态
  - 详细属性说明见 `属性说明.md`

---

## 9. 参数配置与消融实验

### 9.1 超参数集中管理

`config/simulation_config.py` 提供 SimulationConfig dataclass，所有论文 Table 2 参数集中在此：

- I1/I2/I3 全部参数（θ₁, θ₂, k₁~k₄, λ_d/f/c, μ 等）
- 社会力模型参数（A, B, τ, K, κ, λ）
- Greenshields 速度参数（v_free, ρ_jam, g_max）
- 统一压力模型阈值
- SEIR 传播参数
- 仿真规模设置

### 9.2 消融实验预设

AblationPreset 类提供一键切换的消融配置：

| 预设 | 对应消融 | 操作 |
|------|------|------|
| `hard_switch()` | E2.2 无软切换 | k₁~k₄ = 50 |
| `no_info_network()` | E2.3 无信息网 | λ_c = 0, γ = 0 |
| `no_inertia()` | E2.4 无Leader惯性 | μ = 1.0 |
| `no_personality()` | E2.5 无 OCEAN 异质性 | （配合 agents.py 修改 OCEAN 采样） |
| `soft_switch()` | 软切换对照 | k₁~k₄ = 1 |
| `distance_only_store()` | 仅看距离选商店 | λ_f = λ_c = 0 |
| `no_hysteresis()` | E2.6 无 P1.A 迟滞带 | `enable_hysteresis=False` |
| `no_outcome_feedback()` | E2.7 无 P1.B 结果反馈 | `enable_outcome_feedback=False` |
| `no_behavior_demo()` | E2.8 无 P2 行为示范 | `enable_behavior_demo=False` |
| `with_inquire()` | E2.9 启用 P3 信息搜寻第四态 | `enable_inquire=True` |
| `i1_minimal()` | 关闭全部 I1 扩展 | P1.A + P1.B + P2 + P3 全关 |

### 9.3 参数网格扫描

`theta_grid()` 函数生成 θ₁(0.20-0.40) × θ₂(0.55-0.75) 的 5×5 网格（满足 θ₂-θ₁ ≥ 0.2），输出 23 个有效参数组合，用于 Experiment 2 敏感性分析。

---

## 10. 事件记录系统

由 `core/event_recorder.py` 和 `core/event_influence.py` 实现：

- 自动记录仿真过程中的所有事件（停电/恢复/恐慌爆发/群体移动等）
- 评估事件的连锁影响和影响范围
- 支持导出 CSV 格式的事件记录

---

## 代码模块总览

```
Evacuation-simulation-of-panic-crowds-in-the-city/
├── core/
│   ├── agents.py              # 5类Agent (3093行)
│   ├── behavior_switching.py  # ⭐ I1/I2/I3 + P1.A/P1.B/P2/P3 扩展 (499行)
│   ├── social_force.py        # 社会力 + Greenshields (1188行)
│   ├── unified_stress_model.py # Lazarus统一压力模型 (637行) — pts_status 真值来源
│   ├── region_manager.py      # GeoJSON区域管理 (1276行)
│   ├── event_types.py         # 事件类型定义 (209行)
│   ├── event_recorder.py      # 事件记录器 (628行)
│   └── event_influence.py     # 事件影响计算 (1995行)
├── decision/
│   ├── base.py                # 决策接口定义
│   ├── rule_based.py          # 规则专家系统
│   └── utility.py             # 效用函数
├── config/
│   ├── config.py              # 路径/模型参数配置
│   ├── behavior_config.py     # Agent行为参数
│   ├── city_manager.py        # 多城市管理
│   └── simulation_config.py   # ⭐ 超参数集中管理 + 消融预设（含 I1 扩展）
├── simulation/
│   └── simulation.py          # 仿真主引擎 (2246行)
├── visualization/
│   ├── dashboard.py           # ⭐ 交互式仪表盘 SimulationDashboard (1258行)
│   ├── small_area_viewer.py   # 区域地图可视化 (235行)
│   └── trace_plotter.py       # 时序曲线绘制 (384行)
├── run_dashboard.py           # 一键启动仪表盘的 CLI 入口
├── output/                    # 仪表盘截图 / 概览图 / step_history.json
├── trace_output/              # 每次 run 的 trace CSV (run_<时间戳>_<tag>/)
├── 属性说明.md                 # 输出数据JSON属性详解
└── README.md                  # 本文档
```
