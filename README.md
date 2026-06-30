# 城市大停电人群行为动态仿真系统

> Evacuation Simulation of Panic Crowds in the City — multi-agent Python simulation for panic crowd evacuation in urban public space.

本项目是基于多智能体的城市停电应急仿真系统，用于模拟大规模停电事件下居民的心理-行为动态、基础设施响应以及政府/电网的应急决策过程。该系统对应 IJDRR 论文 *"城市大停电下的人群行为动态仿真研究"* 的 Methodology 第3章，所有模块均与论文公式对齐。

> **PTS 定义修订**：`pts_status` 由 **σ 迟滞带** 控制：进入 σ ≥ 0.8 × 性格系数（封顶 0.95）、退出 σ < 0.5 × 性格系数（迟滞带 0.3）；非永久锁存。基准取 EXTREME（0.8），PTS 为少数极端态。依据文献（SIR 含 Recovered 态、P-SIS 情绪可逆、伊比利亚大停电情绪随恢复消退）：PTS 不永久锁存但需迟滞。

> **运行环境**：必须用 conda env `Crowds_sim` 跑 sim (含 networkx / osmnx 路网依赖)；推荐通过 `.venv/run_in_crowds_env.ps1` wrapper 启动 (内部走 `cmd /c "call activate.bat ..."`，确保 `Library\bin\` 的 freetype/libpng/zlib DLL 进 PATH，否则 matplotlib/scipy 的 C 扩展会抛 `0xC00000FF / 0xc06d007f` STATUS_INVALID_IMAGE_FORMAT，详见 §14)。

---

## 1. 多主体仿真系统

系统模拟五类主体在停电事件中的行为和交互：

- **政府主体** (GovernmentAgent)：负责应急资源调配和信息发布，具有积极性和响应效率两个核心参数。根据社会意见压力指数 Π 触发预警、资源拨付等决策。

- **电网主体** (PowerGridAgent)：负责故障修复和供电恢复，具有积极性、响应效率和故障传播率三个核心参数。修复能力受资源投入和群体恐慌的双向影响（宏观反馈环）。

- **企业主体** (EnterpriseAgent)：模拟企业在停电时的求助行为和累积损失，发出资源请求信号。

- **居民主体** (ResidentAgent)：**核心建模对象**。具有 OCEAN 五因素人格、统一心理压力状态 σ(t)、情绪 E(t)、恐慌 P(t) 和 PTS 状态，以及由应力驱动的三阶段行为切换（回家→囤积→从众）。

- **关键基础设施主体** (CriticalInfraAgent)：包括医院、学校、应急机构、政府机构、工业企业五类，具有优先级和备用电源属性，发出公共影响信号。

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

### 3.1 I1 — 应力驱动的战术行为选择 (MML 主形式 + sigmoid legacy fallback)

> **默认开关**: 自 2026-06-28 起 `SwitchParams.use_mml = True` 为默认。论文 §5 主结论用 MML 形式得出。`use_mml=False` 留作 sigmoid legacy fallback (supplementary materials 用)。

#### 3.1.1 MML 主形式 (Mixed Multinomial Logit, McFadden 1973)

`compute_goal_direction_mml()` 在 4 个 action `{home, hoard, herd, flee}` 上做 softmax 离散选择:

```
P_k = exp(β · V_k) / Σ exp(β · V_j),   β = mml_scale = 1.5
```

每个 V_k 是 alternative-specific constant (ASC) + linear-in-attributes 项 (论文 §3.3.2 Eq. 12):

- **home** V_home = α_home − β_σ · σ (σ↑ → V_home↓)
- **hoard** V_hoard = α_hoard + β_σ · σ + β_supply · H − β_dist · dist_shop − β_occ · occ
- **herd** V_herd = α_herd + β_σ · σ + β_pts · Z − β_dist · dist_leader
- **flee** V_flee = (α_flee + β_σ · σ + β_vis − β_dist · dist_shelter) · VIS_i + (1−VIS_i) · (−∞)

其中 VIS_i = 1 iff graph-on 且 shelter_node 已 snap。**VIS gate** 是论文 §5.1 的"graph-off ↔ graph-on 切换"在 RUM 框架下的严格理论解释 (visibility-conditioned choice set, 引 Haghani & Sarvi 2016 [REF28])。

返回 expected direction `Σ P_k · d_k` 给 social_force 用; 同时记 `agent._dom_action = argmax_k P_k` 给 path_planner 用。

#### 3.1.2 Sigmoid soft-blend (legacy, `use_mml=False` fallback)

三个候选目标方向 (home / hoard / herd) 按 sigmoid 权重加权合成, 加 hard flee override (σ > flee_threshold = 0.6 时强制冲向最近避难所):

- w_home, w_hoard, w_herd: σ 跨 θ₁=0.4 / θ₂=0.6 时 logistic 平滑过渡 (陡度 k₁~k₄ = 10)
- flee override: σ > 0.6 时 `target_node = nearest_shelter_node`, 覆盖 home/hoard/herd 决策

历史地位: 这是早期 M3 / 早期 M4 drafts 的形式, 已被 MML 取代。两者主结论 (flee 通道激活, BC 失败, N-invariance) 都 robust; 但 §5.1 的 IIA herd substitution 是 MML 特有 (sigmoid 加性 blend 没法把 herd 概率挪给 flee), 详见论文 §5 supplementary note。

### 3.2 I2 — 熟人网络商店选择

商店效用函数 U_i(s) = -λ_d·d(i,s) + λ_f·f_i(s) - λ_c·ô_i(s)：

- d：距离
- f_i(s)：个人熟悉度（随访问增加）
- ô_i(s)：**感知占用率**（仅通过熟人 gossip 更新，非全局广播）

信息不对称导致不同 agent 对同一商店持有不同信念，产生自加强的非均衡挤兑（消融：λ_c=0 退化为仅看距离）。

### 3.3 I3 — Leader 惯性选择与滞后带

Leader 评分 = α_s·(1-E_j) + α_f·f_ij + α_v·可见性

**滞后切换规则**：新候选者得分必须超过当前 leader 的 μ 倍（μ=1.3）才切换，防止每步重选导致的羊群崩溃（消融：μ=1.0 退化为无惯性）。

### 3.4 I1 扩展（ 新增 P1.A / P1.B / P2 / P3）

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
- 加载 CSV 节点数据（医院/学校/工业/应急/政府五类设施）
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

`config/simulation_config.py` 提供 SimulationConfig dataclass，所有参数集中在此：

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

## 12. 路网层与避难所架构 ⭐（ M2 / M3 / M3+ 新增）

把模型从"连续空间 social force"升级为 **graph-constrained ABM + 真实避难所驱动 flee 行为**，目的是让仿真能与城市真实路网拓扑对齐、给论文的 §4.2 / §5.x 提供硬证据。

### 12.1 三层架构

```
┌──────────────────────────────────────────────────────────┐
│ Layer 1: GeoJSON polygon  (行政边界 + 真实 POI, 不动)      │
├──────────────────────────────────────────────────────────┤
│ Layer 2: OSM road graph  (osmnx 下载 + edge capacity)     │
│   - 节点 = 路口     边 = 路段 (length / capacity / speed) │
├──────────────────────────────────────────────────────────┤
│ Layer 3: Agent 行为 (I1/I2/I3) → target_node              │
│   - I1 stress 驱动 (home/hoard/herd/flee)                 │
│   - Dijkstra 路径规划 (congestion-aware + 动态重路由)     │
│   - Greenshields 速度衰减 (软约束)                        │
│   - 拥堵 → σ 反馈 (panic cascade loop)                    │
└──────────────────────────────────────────────────────────┘
```

### 12.2 启用方式

向后兼容：默认 `use_road_graph=False`，行为不变。打开方式（在 `city_config` 里加一个键）：

```python
city_config = {
    'city': '厦门市',
    'geojson_paths': [...],
    'districts': ['思明区'],
    'use_road_graph': True,    # ← M2 关键开关
}
sim = BlackoutSimulation(config=cfg, city_config=city_config)
```

仿真启动后会自动：
1. 从 `road_graph_cache/{城市}_{区}.graphml` 读图（缺失则联网下载并缓存）
2. 调 `snap_to_nodes_batch` 把所有 agent 落到最近的 graph node（current_node = home_node）
3. 加载 `simulation map data/{城市}/{区}/{区}POI/应急.csv`，过滤出真避难所，给每个 agent 分配最近 shelter（KD-Tree）
4. 把 graph 引用注入 `social_force.road_graph`，让 driving_force 朝路径走

### 12.3 Panic Cascade Loop

```
拥堵 (cong↑)
    ↓ feedback_congestion=+0.05 × cong / step
σ 被推升
    ↓ sigmoid 权重压向 herd
agent 转为 herd, 聚集到同 edge
    ↓
edge occupancy↑ → cong↑ (循环)
```

**关键: 这个 loop 靠 dynamic re-routing 才能闭合** (详见 §12.3.1)。如果只在出发时算一次路径不重路由, 这个 loop 半开 (只有新出发的 agent 响应拥堵), cascade 信号会明显弱化。

### 12.3.1 Dynamic re-routing — 关上 cascade loop

`core/path_planner.py` 给每个 agent 持续刷新路径, **不是出发时算一次就锁死**。类比 Google Maps / Waze 实时导航。

**congestion-aware 权重** (公式跟论文 §3.5.7 Eq.24 一致):
```
w(edge) = length(edge) × (1 + α · cong)
cong = min(1.0, occupancy(edge) / capacity_per_step(edge))
α = CONGESTION_WEIGHT_ALPHA = 2.0
```

**重路由触发条件** (4 选 1 命中即触发, [path_planner.py:16-20](core/path_planner.py#L16)):

| 触发 | 时机 | 通常对应 |
|---|---|---|
| **`target_node` 变了** | I1 重算 dom_action 选了新目标节点 | herd → flee 切换 (§5.1 IIA), leader 换人, hoard → herd |
| **≥ `REPLAN_EVERY_STEPS` (默认 25) 步** | 周期刷拥堵 | "实时导航式" 路径调整, 6.25h 一次 |
| **`current_path` 空** | 出发时 / 走完了 | 新 spawn 或 path 用完 |
| **`force=True`** | 外部强制 | 现在没用上 |

**console log**: 当单步重路由 agent 数 ≥ `max(20, N/20)` 时打印 `[path_plan] step N: replanned X/N agents`。这不是 bug, 是模型在工作的证据。两种 pattern:
- 大批量 (300+) 每 25 步规整出现 → 周期刷新触发
- 小批量 (40-60) 散落出现 → target_node 变化触发 (典型: σ 在 0.55-0.65 边界的 herd/flee 摇摆人群)

**4 个关键好处**:

1. **关上 panic cascade loop** — 见 §12.3 上面流程图. 没 replan, loop 只能影响新出发的 agent, 大部分 cascade 信号被吃掉
2. **拥堵空间再分配** — 避免所有 flee agent 挤同一条街形成单点死锁. 重路由让拥堵在多条 funnel street 间动态分流, 这是论文 §5.3 BC failure 的力学根源之一 (load 不在最短路上, 而在"绕道终点"窄街)
3. **跟真实人类导航行为对齐** — 真实疏散里人会避堵车, 25 步 ≈ 6h 间隔模拟 "看到/听说交通信息后调整路径" 的节奏
4. **MML IIA substitution 真正可见** — 论文 §5.1 herd→flee 替代需要 herd agent 在路上切换 target 到 shelter, 这次切换由 path_planner 在下一步生效, 没 replan 就只是 dom_action 标记变了但人还在原路上

**调参 `REPLAN_EVERY_STEPS`** (默认 25):

| 值 | 真实意义 | 计算成本 |
|---|---|---|
| 5 (1.25h) | 接近实时导航 (Waze 级) | 5× |
| **25 (6.25h)** ⭐ | 论文 §5 用这个, "first-leg commitment + destination-aware adjustment" | 基线 |
| 100 (25h) | "黑天事件无导航信息" 假设 | 1/4× |
| `∞` (不刷) | sanity baseline, agent 锁路, 退化为 static shortest-path routing | 最低 |

代码位置: [path_planner.py:30](core/path_planner.py#L30)

### 12.4 Flee 行为（M3+ 新增）

当 `σ > 0.6` 且 agent 有最近避难所时，I1 强制 `target_node = nearest_shelter_node`，覆盖 home/hoard/herd 决策。在厦门思明区跑 N=800 时，peak flee_ratio ≈ 10.4%，即约 83 个 agents 同时向真实避难所逃。

| 关键参数 | 位置 | 默认值 |
|---|---|---|
| `feedback_congestion` | `SwitchParams` | +0.05 |
| `enable_congestion_feedback` | `SwitchParams` | True |
| `flee_threshold` | `SwitchParams` | 0.6（= PTS 进入阈值） |
| `enable_flee_behavior` | `SwitchParams` | True |
| `CONGESTION_WEIGHT_ALPHA` | `path_planner` | 2.0 |
| `REPLAN_EVERY_STEPS` | `path_planner` | 25 |
| `DEFAULT_JAM_RATIO` (Greenshields) | `movement_layer` | 0.9 |
| `DEFAULT_OCC_DECAY` | `movement_layer` | 0.5 |
| `MIN_SPEED_FACTOR` | `movement_layer` | 0.10 |

### 12.5 trace 输出扩展

`global_metrics.csv` 增 3 列：
- `avg_edge_congestion` — 所有 agent 当前 edge 拥堵率的均值
- `pct_on_path` — 多少比例的 agent 当前正在 edge 上
- `max_edge_occupancy` — 全图最大单边 occupancy

新增 `edge_observations.csv` — 仿真结束时 dump 每条边的累计观测，字段：
`edge_id, u, v, k, highway, length_m, capacity_per_step, cum_occupancy, mean_occupancy, peak_occupancy`

用于 T16 betweenness ↔ 仿真观测的 Pearson 相关性分析。

### 12.6 三城路网指标对比（V3 polish）

`_compare_cities.py` 跑厦门思明 / 沈阳沈河 / 北京东城，输出：
- `road_graph_cache/{城市}_{区}/metrics.json`（4 组指标）
- `orientation_rose.png`（玫瑰图：方位熵 0.991 / 0.941 / 0.743）
- `betweenness_heatmap.png`（瓶颈预测）

四组指标：
1. **topology**：节点/边数、路网总长、面积（**polygon 而非 bbox**）、密度、平均路段长
2. **geometry**：方位熵（归一化 [0,1]）、circuity、bearing 36-bin 直方图（可离线重画玫瑰图）
3. **evacuation**：betweenness max/mean/std/**Gini**/**top-1% share**、top-10 节点、直径
4. **coupling**：人口、人均路网、人均路口

---

## 13. M4 实验框架 ⭐（2026-06 新增）

为论文 §4-§5 准备的批量实验脚本族, 与 [[2026-06-22 后续优化清单 (M4 实验计划)]] 中的 F1-F19 任务对齐。所有 batch runner 通过 `scripts/run_ablation.py` 跑单个 (city, seed, N, home_dist) 组合, 由 batch runner 循环调度。

### 13.1 单跑 harness — `scripts/run_ablation.py`

graph-on vs graph-off 对照实验, 默认跑厦门思明 N=800 seed=42:

```powershell
.\.venv\run_in_crowds_env.ps1 scripts\run_ablation.py `
    --city 厦门市 --district 思明区 `
    --n-residents 800 --seed 42 `
    --tag baseline --output-base M4_F1_cross_city `
    --home-distribution poi          # 'poi' 默认 / 'uniform' 见 §F2 (POI 控制实验)
    # --flee-threshold 0.6          # 可选: 仅 sigmoid fallback 时生效; MML 下 flee 由 V_flee 自动控制
    # --no-mml                      # 可选: 切回 sigmoid legacy fallback; 默认走 MML
```

**CLI 参数清单** (定义在 `_parse_args()`):

| flag | 默认 | 用途 |
|---|---|---|
| `--city` / `--district` | 厦门市/思明区 | 选区县 |
| `--n-residents` / `--n-enterprises` | 800 / 30 | 人口规模 |
| `--total-steps` / `--outage-step` | 120 / 16 | 仿真步数 / 停电触发步 |
| `--seed` | 42 | RNG seed |
| `--tag` | '' | 输出目录后缀 (e.g. `seed42`, `N500`) |
| `--output-base` | `trace_output/` | 输出根目录 (M4 子组传 `M4_F4_multi_seed` 等) |
| `--home-distribution` | `poi` | 居民 home 分布: `poi` (按 POI 圆) / `uniform` (polygon 面积均匀) |
| `--flee-threshold` | None (=0.6) | **legacy F5**: 只在 sigmoid fallback 下生效 (MML 由 V_flee 自动控制); supplementary 用 |
| `--use-mml` | True (默认) | **F13**: Mixed Multinomial Logit (McFadden 1973), 论文 §5 主形式 |

每次跑会跑 graph-off + graph-on 各 120 步, 输出:
- `trace_output/<output-base>/t15_<城>_<区>_<tag>/graph_off/global_metrics.csv`
- `trace_output/<output-base>/t15_<城>_<区>_<tag>/graph_on/{global_metrics.csv, edge_observations.csv}`
- `summary.json` (config + final / peak 关键指标, **summary-first** 保证即使 plot crash 也落盘; config 段含 `home_distribution / flee_threshold / use_mml` 字段供后处理筛选)
- `comparison.png` (matplotlib 出图)

### 13.2 批量 runner

| 脚本 | 任务编号 | 跑多少次 | 用途 |
|---|---|---|---|
| `scripts/run_f4_multi_seed.py` | F4 | 30 (三城 × seed 42-51) | 多 seed 95% CI; §5.1 主表 |
| `scripts/run_f7_n_scan.py` | F7 | 15 (三城 × N ∈ {200, 500, 800, 1500, 3000}) | cascade vs N N-invariance; §5.2 主图 |
| `scripts/run_f5_theta_flee.py` | legacy F5 | 24 (三城 × θ ∈ {0.40..0.80}) | sigmoid 时代 θ_flee 扫描; 论文 supplementary 用 |
| `scripts/run_f2_home_dist.py` | F2 | 6 (三城 × {poi, uniform}) | 去 POI bias 控制实验; §5.3 |
| `scripts/run_mml_all.py` | F13 master | 54 (F1+F4+F7+F2) | 一键串联 4 个 F-runner 跑完整 §5 数据集 (默认 MML, 输出 `M4_MML_*`); 历史保留 |

所有 batch runner subprocess 模式 + fail-fast 检查 networkx/osmnx。启动方式 (推荐通过 wrapper, 自动处理 conda env 激活):

```powershell
.\.venv\run_in_crowds_env.ps1 scripts\run_<f4|f5|f7|f2>_<name>.py

# 一键跑完整 §5 数据集 (默认 MML, 输出 M4_MML_*)
.\.venv\run_in_crowds_env.ps1 scripts\run_mml_all.py
```

长任务建议 detach 模式 (避免 Bash 工具 10 min timeout):

```powershell
$p = Start-Process -FilePath "powershell" -ArgumentList @(
    "-NoProfile", "-File", ".\.venv\run_in_crowds_env.ps1", "scripts\run_f4_multi_seed.py"
) -RedirectStandardOutput "trace_output\F4.log" `
  -RedirectStandardError  "trace_output\F4.err" `
  -NoNewWindow -PassThru
```

**`BLACKOUT_USE_MML` 环境变量** (2026-06-28 起语义反转): 4 个 F-runner + 3 个 analysis 脚本都读这个 env var:
- 默认 (不设 或 `=1`) → MML 模式, 输出到 `trace_output/M4_MML_*/` (论文 §5 主形式)
- `=0` → sigmoid legacy fallback, 输出到 `trace_output/M4_*/` (§5 supplementary Tables S1–S3 来源), 内部 subprocess 自动加 `--no-mml`
- 两套数据**并列存放, 互不覆盖**

### 13.3 后处理 / aggregate 脚本

| 脚本 | 输入 | 输出 | 用途 |
|---|---|---|---|
| `analysis/f4_aggregate.py` | `M4_F4_multi_seed/t15_*/summary.json` (×30) | `aggregate_ci.{csv,json}` + `errorbar.png` | 三城 × 4 指标 95% CI 表 + 误差棒图; §5.1 主图 source |
| `analysis/f7_n_curve.py` | `M4_F7_N_scan/t15_*/summary.json` (×15) | `n_curve.{csv,png}` | cascade 指标 vs N log-x 曲线; §5.2.1 主图 source |
| `analysis/f5_phase_transition.py` | `M4_F5_theta_flee/t15_*/summary.json` (×24) | `theta_curve.{csv,png}` | cascade 指标 vs θ_flee phase transition; §5.2.2 sigmoid 主图 source |
| `analysis/f2_compare_r.py` | `M4_F2_home_dist/t15_*/graph_on/edge_observations.csv` (×6) | `r_compare.{csv,json}` + `_corr/<...>/correlation.json` | poi vs uniform 的 Pearson r 对照; §5.3 主图 source; 内部调 `betweenness_vs_sim.py` 6 次 |
| `analysis/betweenness_vs_sim.py` | `<output-base>/.../edge_observations.csv` + `road_graph_cache/<城>_<区>.graphml` | `correlation.{png,json}` | T16: 单城市标准 node BC vs 仿真累计 occupancy 的 Pearson/Spearman |
| `analysis/shelter_aware_bc.py` | 同上 + `应急.csv` shelter 点 | shelter-aware BC vs sim 散点 | T17: "BC 失败是因为是 home→shelter 有向流" 假说验证; 论文 §6 Discussion "demand-aware centrality" 实证依据 |
| `analysis/compare_cities.py` | `road_graph_cache/{城}_{区}/metrics.json` (3 城) | 三城拓扑指标对比表 | M2/M3 时代早期工作; §4 数据描述段 source (polygon area, Gini, top-1% share, density) |

所有 analysis 脚本通过 wrapper 启动:

```powershell
.\.venv\run_in_crowds_env.ps1 analysis\f4_aggregate.py

# MML 数据出表: 同样的脚本通过 env var 切到 M4_MML_* 路径
$env:BLACKOUT_USE_MML="1"
.\.venv\run_in_crowds_env.ps1 analysis\f4_aggregate.py        # → M4_MML_F4_multi_seed/
.\.venv\run_in_crowds_env.ps1 analysis\f7_n_curve.py          # → M4_MML_F7_N_scan/
.\.venv\run_in_crowds_env.ps1 analysis\f2_compare_r.py        # → M4_MML_F2_home_dist/
```

### 13.4 实测数据落盘

```
trace_output/
├── M3_baseline/                     # 早期实验留存
│
│  ─── MML 主形式 (McFadden conditional logit, 论文 §5 主表数据源) ───
├── M4_MML_F1_cross_city/            # F1-MML 三城 baseline (3 sub-run)
├── M4_MML_F4_multi_seed/            # F4-MML 三城 × 10 seed (×30) — §5.1 主表
│   ├── aggregate_ci.{csv,json}
│   └── errorbar.png
├── M4_MML_F7_N_scan/                # F7-MML 三城 × 5 N (×15) — §5.2 主表
│   └── n_curve.{csv,png}
├── M4_MML_F2_home_dist/             # F2-MML 三城 × {poi, uniform} (×6) — §5.3 主表
│   ├── r_compare.{csv,json}
│   └── _corr/<城>_<区>_<hd>/correlation.png  (×6) — §5.3 散点图
│
│  ─── sigmoid legacy (早期 1990s 风格 soft-blend, 论文 §5 supplementary Tables S1-S3) ───
├── M4_F1_cross_city/                # F1 三城 baseline (6-22)
├── M4_T16_cross_city/               # T16 BC vs sim 相关性三城外推 (6-22)
├── M4_F4_multi_seed/                # F4 三城 × 10 seed (6-26) — supplementary Table S1
├── M4_F7_N_scan/                    # F7 三城 × 5 N (6-26) — supplementary Table S2
├── M4_F5_theta_flee/                # F5 三城 × 8 θ_flee (6-27) — supplementary Fig S2 (sigmoid-only artefact)
│   ├── theta_curve.{csv,png}
│   └── t15_<城>_<区>_theta{0.4..0.8}/  (×24)
└── M4_F2_home_dist/                 # F2 三城 × {poi, uniform} (6-26) — supplementary Table S3
```

**两套数据并列**: MML 主形式在 `M4_MML_*/`, sigmoid legacy 在 `M4_*/`, 完全平行。论文 §5 主表用 MML; supplementary Tables S1–S3 用 sigmoid 数据展示主结论 (BC failure, N-invariance) 是 formulation-invariant, IIA herd substitution 是 MML 特有。

---

## 代码模块总览

```
Evacuation-simulation-of-panic-crowds-in-the-city/
├── core/
│   ├── agents.py              # 5类Agent (~3100行) +graph state字段
│   ├── behavior_switching.py  # ⭐ I1/I2/I3 + P1.A/P1.B/P2/P3 + 拥堵反馈 + flee 行为 + 【F13】MML 离散选择 (McFadden 1973)
│   ├── social_force.py        # 社会力 + path-based driving + Greenshields 速度衰减
│   ├── unified_stress_model.py # Lazarus统一压力模型
│   ├── region_manager.py      # GeoJSON区域管理 + distribute_residents_{by_poi, uniform}
│   ├── event_types.py         # 事件类型定义
│   ├── event_recorder.py      # 事件记录器
│   ├── event_influence.py     # 事件影响计算
│   ├── road_graph.py          # 【M2】osmnx 下载 + edge 标注 + snap helper
│   ├── path_planner.py        # 【M2】Dijkstra + congestion-aware + 动态重路由
│   ├── movement_layer.py      # 【M2】Greenshields + node load + occupancy decay
│   ├── city_metrics.py        # 【M2】4 组路网指标 + Gini + 玫瑰图 + 热力图
│   └── shelter_loader.py      # 【M3+】应急.csv 加载 + name 过滤
├── decision/
│   ├── base.py / rule_based.py / utility.py
├── config/
│   ├── config.py              # 含 SimulationConfig.HOME_DISTRIBUTION ('poi'/'uniform')
│   ├── simulation_config.py / behavior_config.py
│   └── city_manager.py        # 【M2】+load_road_graph
├── simulation/
│   └── simulation.py          # 【M2/M3+】+_init_road_graph + _init_shelters + _path_planning_hook
├── visualization/
│   ├── dashboard.py           # +avg_edge_congestion/pct_on_path/max_edge_occupancy 字段
│   ├── small_area_viewer.py / trace_plotter.py
├── scripts/                   # ⭐【M4】实验 runner 族
│   ├── run_ablation.py            # 单跑 harness (--seed/--n-residents/--home-distribution/--flee-threshold/--use-mml)
│   ├── run_f4_multi_seed.py       # F4 batch: 三城 × seed 42-51 (30 sub-run)
│   ├── run_f7_n_scan.py           # F7 batch: 三城 × N ∈ {200, 500, 800, 1500, 3000} (15 sub-run)
│   ├── run_f5_theta_flee.py       # F5 batch: 三城 × θ ∈ {0.40..0.80} 8 点加密 (24 sub-run)
│   ├── run_f2_home_dist.py        # F2 batch: 三城 × {poi, uniform} (6 sub-run)
│   └── run_mml_all.py             # ⭐ F13: MML 双形式 master launcher (F1+F4+F7+F2 = 54 sub-run, 受 BLACKOUT_USE_MML=1 触发)
├── analysis/                  # ⭐【M4】后处理 / 画图 (全部支持 BLACKOUT_USE_MML=1 切到 M4_MML_* 路径)
│   ├── betweenness_vs_sim.py      # T16: 单城市标准 node BC vs cum_occupancy Pearson/Spearman
│   ├── shelter_aware_bc.py        # T17: shelter-aware BC vs sim (验证"BC 失败因为是 home→shelter 有向流"假说; §6 Discussion source)
│   ├── compare_cities.py          # 三城拓扑指标对比 (polygon area / Gini / top-1% share / density)
│   ├── f4_aggregate.py            # F4 → 95% CI 表 + errorbar.png (§5.1 主图 source)
│   ├── f7_n_curve.py              # F7 → log-x N 曲线 (§5.2.1 主图 source)
│   ├── f5_phase_transition.py     # F5 → θ_flee phase transition 曲线 (§5.2.2 sigmoid 主图)
│   └── f2_compare_r.py            # F2 → poi vs uniform 的 Pearson r 对比 (§5.3 主图 source)
├── .venv/
│   └── run_in_crowds_env.ps1      # ⭐ Crowds_sim env wrapper (走 cmd /c "call activate.bat" 解 DLL 路径)
├── road_graph_cache/          # 【M2】OSM graphml + metrics.json + plots (gitignored)
│   ├── 厦门市_思明区.graphml / 沈阳市_沈河区.graphml / 北京市_东城区.graphml
│   └── {城市}_{区}/{metrics.json, orientation_rose.png, betweenness_heatmap.png}
├── run_dashboard.py           # 一键启动仪表盘
├── output/                    # 截图 / 概览图 (gitignored)
├── trace_output/              # 每次 run 的 trace CSV / summary.json / aggregate (gitignored)
├── simulation map data/       # Layer 1 polygon + POI CSV (沈阳/北京 gitignored)
├── 属性说明.md                 # 输出数据JSON属性详解
└── README.md                  # 本文档
```

### 复现命令

> 所有命令通过 `.venv/run_in_crowds_env.ps1` wrapper 启动 (内部 `cmd /c "call activate.bat Crowds_sim && python ..."`, 确保 `Library\bin\` 的 DLL 进 PATH; 不要直接调 `D:/EnvironmentAnaconda/envs/Crowds_sim/python.exe`, 否则 matplotlib/scipy 的 C 扩展会抛 0xC00000FF, 详见 §14)。

```powershell
# 1. 启动交互仪表盘 (本地 GUI)
.\.venv\run_in_crowds_env.ps1 run_dashboard.py

# 2. 单次对照实验 (graph-on vs graph-off, 默认厦门思明 N=800 seed=42)
.\.venv\run_in_crowds_env.ps1 scripts\run_ablation.py

# 3. 跨城市验证 (F1)
.\.venv\run_in_crowds_env.ps1 scripts\run_ablation.py `
    --city 沈阳市 --district 沈河区 --output-base M4_F1_cross_city

# 4. 多 seed 批量 (F4, ~25 min, 30 个 subprocess)
.\.venv\run_in_crowds_env.ps1 scripts\run_f4_multi_seed.py

# 5. N 扫描批量 (F7, ~20 min)
.\.venv\run_in_crowds_env.ps1 scripts\run_f7_n_scan.py

# 6. home 分布对照批量 (F2, ~6 min)
.\.venv\run_in_crowds_env.ps1 scripts\run_f2_home_dist.py

# 7. θ_flee 扫描 (F5, ~10 min)
.\.venv\run_in_crowds_env.ps1 scripts\run_f5_theta_flee.py

# 8. 后处理 / aggregate (统一通过 wrapper, matplotlib + scipy 都正常)
.\.venv\run_in_crowds_env.ps1 analysis\f4_aggregate.py
.\.venv\run_in_crowds_env.ps1 analysis\f7_n_curve.py
.\.venv\run_in_crowds_env.ps1 analysis\f2_compare_r.py
.\.venv\run_in_crowds_env.ps1 analysis\f5_phase_transition.py
.\.venv\run_in_crowds_env.ps1 analysis\betweenness_vs_sim.py

# 9. 一键跑完整 §5 数据集 (默认 MML, ~40 min, 输出到 M4_MML_*/) + analysis
.\.venv\run_in_crowds_env.ps1 scripts\run_mml_all.py
.\.venv\run_in_crowds_env.ps1 analysis\f4_aggregate.py        # → M4_MML_F4_multi_seed/
.\.venv\run_in_crowds_env.ps1 analysis\f7_n_curve.py
.\.venv\run_in_crowds_env.ps1 analysis\f2_compare_r.py

# 10. 跑 sigmoid legacy supplementary (重现论文 §5 Tables S1-S3, 输出 M4_*/)
$env:BLACKOUT_USE_MML="0"
.\.venv\run_in_crowds_env.ps1 scripts\run_f4_multi_seed.py
.\.venv\run_in_crowds_env.ps1 analysis\f4_aggregate.py
Remove-Item Env:\BLACKOUT_USE_MML
```

### 长任务的 detach 模式 (避免 Bash/PowerShell tool 10 min timeout)

```powershell
$p = Start-Process -FilePath "powershell" -ArgumentList @(
    "-NoProfile", "-File", ".\.venv\run_in_crowds_env.ps1", "scripts\run_f4_multi_seed.py"
) -RedirectStandardOutput "trace_output\M4_F4_multi_seed.log" `
  -RedirectStandardError  "trace_output\M4_F4_multi_seed.err" `
  -NoNewWindow -PassThru
"PID=$($p.Id)"
# 监控: until grep -q "F4 complete" trace_output/M4_F4_multi_seed.log; do sleep 30; done
```

---

## 14. 已知问题与环境注意事项

| 问题 | 现象 | 处理 |
|---|---|---|
| **默认 `python` 没装 networkx/osmnx** | graph-on silent fallback 到 graph-off, 数据失效但不报错 | 所有 batch runner 加 fail-fast import 检查; 必须用 `Crowds_sim` env |
| **Bash/PowerShell tool timeout 上限 10 min** | F4 (30 min) / F7 (20 min) 长任务被超时杀进程 | 用 `Start-Process -NoNewWindow -PassThru` detach 出独立进程 + log file 监控 |
| **直接调 Crowds_sim env 的 python.exe 会让 matplotlib/scipy 抛 `0xC00000FF`** | `D:/EnvironmentAnaconda/envs/Crowds_sim/python.exe script.py` 跑到 `fig.savefig` 或 `scipy.stats.pearsonr` 时整个进程 kernel-level crash (`STATUS_INVALID_IMAGE_FORMAT`, except 接不到) | **必须通过 `.venv/run_in_crowds_env.ps1` wrapper 启动** (`cmd /c "call activate.bat Crowds_sim && python ..."`)。原因: conda env 的 freetype/libpng/zlib DLL 装在 `{env}\Library\bin\`, activate 时才会加入 PATH。详细诊断: 6-26 误诊为 env 损坏 (P3/P4), 6-27 翻案确认为 PATH 问题。env 本身完好 (scipy 1.18.0 + numpy 2.2.6 + matplotlib 3.11.0 在 n=6000 长 array 上 pearsonr 正常)。|
