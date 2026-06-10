# -*- coding: utf-8 -*-
"""
================================================================================
多主体Agent模块 - 各类Agent定义
================================================================================
包含：
    0. ResidentAttributeConfig - 居民属性配置接口（来自顾松宇-江猛-多主体11.27.py）
    1. GovernmentAgent - 政府Agent
    2. PowerGridAgent - 电网Agent
    3. EnterpriseAgent - 企业Agent
    4. ResidentAgent - 居民Agent（整合社会力+恐慌模型+属性系统）
    5. CriticalInfraAgent - 关键基础设施Agent

【数据输出说明】
    各Agent的step()方法会更新内部状态，这些状态用于：
    - 绘制时间序列图表
    - 计算统计指标
    - 参数效果分析
================================================================================
"""

import numpy as np
import random
import math

# 导入统一心理压力模型
unified_stress_model = None
migrate_to_unified_model = None

try:
    from .unified_stress_model import unified_stress_model as _usm, migrate_to_unified_model as _mtum

    unified_stress_model = _usm
    migrate_to_unified_model = _mtum
    print("   [OK] 统一心理压力模型加载成功")
except ImportError:
    # 兼容直接运行时的导入
    try:
        from unified_stress_model import unified_stress_model as _usm, migrate_to_unified_model as _mtum

        unified_stress_model = _usm
        migrate_to_unified_model = _mtum
        print("   [OK] 统一心理压力模型加载成功 (直接导入)")
    except ImportError as e:
        print(f"   [!] 统一心理压力模型加载失败: {e}")
        print("   [!] 将使用原有的分离模型")
        unified_stress_model = None
        migrate_to_unified_model = None


# =============================================================================
# 居民属性配置接口类 - 来自顾松宇-江猛-多主体11.27.py
# =============================================================================
class ResidentAttributeConfig:
    """
    居民属性配置接口类：统一管理所有居民属性，便于扩展

    【功能说明】
    - 定义居民的各种属性（年龄、健康状态等）
    - 支持两种属性类型：range（范围随机）和choice（选项随机）
    - 提供扩展接口，可动态添加新属性

    【使用示例】
    config = ResidentAttributeConfig()

    # 添加新属性
    config.add_attribute(
        attr_name='gender',
        attr_type='choice',
        config={'choices': ['男', '女'], 'weights': [0.51, 0.49]},
        description='居民性别'
    )

    # 生成属性值
    age = config.generate_attribute_value('age')
    """

    # =================================================================
    # 【改进3】基于距离衰减的恐慌定量传播 - 类级常量
    # 参考: Wang et al. 2022, Chin.Phys.B 31(6), Eq.6
    # =================================================================
    # 距离核尺度因子 σ (米) ★ 对比实验可调 ★
    #   S1=100m(楼栋级) S2=300m(街区级) S3=800m(小区级)
    #   S4=2000m(片区级) S5=5000m(街道级) S6=inf(无距离核,基线)
    DISTANCE_KERNEL_SIGMA = 300.0

    # SEIR 源权重 (方案C2: I态主动传播, E态被动泄露, S/R态不传播)
    SEIR_SOURCE_WEIGHT = {
        'I': 1.0,  # 表达性恐慌: 主动向外传播
        'E': 0.3,  # 暴露期: 被动泄露焦虑情绪
        'S': 0.0,  # 易感期: 不传播
        'R': 0.0,  # 恢复期/适应期: 不传播
    }

    # 经纬度-米换算常数（基于厦门思明区平均纬度24.45°N）
    # 如仿真其他城市需重新设置，或动态根据居民坐标均值计算
    LAT_TO_M = 111000.0  # 1° 纬度 ≈ 111 km
    LON_TO_M = 101000.0  # 1° 经度 ≈ 111 × cos(24.45°) ≈ 101 km

    def __init__(self):
        # 初始化基础属性配置
        self.attributes = {
            # 年龄属性配置 - 基于中国实际人口年龄分布（2020年普查数据近似）
            # 0-14岁: 17.95%, 15-59岁: 63.35%, 60+岁: 18.70%
            'age': {
                'type': 'choice',  # 改为按权重选择年龄段
                'config': {
                    'choices': list(range(0, 101)),  # 0-100岁
                    'weights': (
                        # 0-4岁: 约5% (每岁1%)
                            [1.0] * 5 +
                            # 5-14岁: 约13% (每岁1.3%)
                            [1.3] * 10 +
                            # 15-24岁: 约11% (每岁1.1%)
                            [1.1] * 10 +
                            # 25-34岁: 约15% (每岁1.5%) - 主力人群
                            [1.5] * 10 +
                            # 35-44岁: 约15% (每岁1.5%) - 主力人群
                            [1.5] * 10 +
                            # 45-54岁: 约17% (每岁1.7%) - 最大年龄段
                            [1.7] * 10 +
                            # 55-64岁: 约12% (每岁1.2%)
                            [1.2] * 10 +
                            # 65-74岁: 约8% (每岁0.8%)
                            [0.8] * 10 +
                            # 75-84岁: 约3% (每岁0.3%)
                            [0.3] * 10 +
                            # 85-100岁: 约1% (每岁0.06%)
                            [0.06] * 16
                    )
                },
                'description': '居民年龄（基于实际人口分布）'
            },
            # 健康状态属性配置
            'health_status': {
                'type': 'choice',  # 类型：选项随机
                'config': {
                    'choices': ['健康', '亚健康', '轻微疾病', '严重疾病', '残疾'],
                    'weights': [0.5, 0.3, 0.15, 0.03, 0.02]  # 权重（总和1）
                },
                'description': '居民健康状态'
            },
            # 【新增】性格属性 - 影响情绪敏感度和行为阈值
            'personality': {
                'type': 'choice',
                'config': {
                    'choices': ['理性型', '稳定型', '普通型', '敏感型', '焦虑型'],
                    'weights': [0.10, 0.25, 0.40, 0.15, 0.10]
                },
                'description': '性格类型：理性型冷静不易恐慌，焦虑型容易情绪波动'
            },
            # 【新增】社交活跃度 - 影响信息传播和聚集行为
            'social_activity': {
                'type': 'range',
                'config': {'min': 0.1, 'max': 1.0},
                'description': '社交活跃度：越高越容易传播信息、参与聚集'
            },
            # 【新增】抗压能力 - 影响危机应对
            'stress_resistance': {
                'type': 'range',
                'config': {'min': 0.3, 'max': 1.0},
                'description': '抗压能力：越高越能承受长时间停电压力'
            },
            # =============================================================
            # 【改进1】OCEAN五因素人格模型 (Ren et al.)
            # ψ = ⟨O, C, E, A, N⟩ ∈ [-1, 1]
            # 用于计算共情系数ε 和 情绪激发/平复参数α1/α2
            # =============================================================
            'ocean_O': {
                'type': 'range',
                'config': {'min': -1.0, 'max': 1.0},
                'description': 'OCEAN开放性 (Openness): 正值=好奇开放, 负值=保守封闭'
            },
            'ocean_C': {
                'type': 'range',
                'config': {'min': -1.0, 'max': 1.0},
                'description': 'OCEAN自律性 (Conscientiousness): 正值=自律有序, 负值=随性散漫'
            },
            'ocean_E': {
                'type': 'range',
                'config': {'min': -1.0, 'max': 1.0},
                'description': 'OCEAN外向性 (Extraversion): 正值=外向活跃, 负值=内向安静'
            },
            'ocean_A': {
                'type': 'range',
                'config': {'min': -1.0, 'max': 1.0},
                'description': 'OCEAN宜人性 (Agreeableness): 正值=友善合作, 负值=竞争对抗'
            },
            'ocean_N': {
                'type': 'range',
                'config': {'min': -1.0, 'max': 1.0},
                'description': 'OCEAN情绪稳定性 (Neuroticism反转): 正值=情绪稳定, 负值=神经质/易焦虑'
            },
        }

    def add_attribute(self, attr_name, attr_type, config, description):
        """
        新增居民属性（扩展接口）

        参数:
            attr_name: 属性名称（如 'gender'）
            attr_type: 属性类型（'range' 范围随机 / 'choice' 选项随机）
            config: 配置字典：
                    - range类型：{'min': 最小值, 'max': 最大值, 'step': 步长（可选）}
                    - choice类型：{'choices': 选项列表, 'weights': 权重列表（可选）}
            description: 属性描述
        """
        if attr_name in self.attributes:
            print(f"⚠️ 属性「{attr_name}」已存在，将覆盖原有配置")

        # 校验配置合法性
        if attr_type == 'range':
            required_keys = ['min', 'max']
            if not all(key in config for key in required_keys):
                raise ValueError(f"range类型属性需包含配置：{required_keys}")
            if config['min'] > config['max']:
                raise ValueError("min不能大于max")
        elif attr_type == 'choice':
            required_keys = ['choices']
            if not all(key in config for key in required_keys):
                raise ValueError(f"choice类型属性需包含配置：{required_keys}")
            if 'weights' in config and len(config['weights']) != len(config['choices']):
                raise ValueError("weights长度需与choices一致")
        else:
            raise ValueError(f"不支持的属性类型：{attr_type}（仅支持 'range' / 'choice'）")

        self.attributes[attr_name] = {
            'type': attr_type,
            'config': config,
            'description': description
        }
        print(f"✅ 成功添加属性：「{attr_name}」- {description}")

    def generate_attribute_value(self, attr_name):
        """根据属性配置生成随机值"""
        if attr_name not in self.attributes:
            raise KeyError(f"属性「{attr_name}」未配置")

        attr = self.attributes[attr_name]
        if attr['type'] == 'range':
            min_val = attr['config']['min']
            max_val = attr['config']['max']
            step = attr['config'].get('step', 1)
            # 生成范围内的随机值
            if isinstance(min_val, int) and isinstance(max_val, int) and isinstance(step, int):
                return random.randrange(min_val, max_val + 1, step)
            else:
                return round(random.uniform(min_val, max_val), 2)

        elif attr['type'] == 'choice':
            choices = attr['config']['choices']
            weights = attr['config'].get('weights')
            # 按权重随机选择（无权重则等概率）
            return random.choices(choices, weights=weights, k=1)[0]

    def generate_all_attributes(self):
        """生成所有属性的值"""
        return {attr_name: self.generate_attribute_value(attr_name)
                for attr_name in self.attributes}

    def get_all_attributes(self):
        """获取所有属性配置"""
        return self.attributes.copy()

    def get_attribute_description(self, attr_name):
        """获取属性描述"""
        if attr_name in self.attributes:
            return self.attributes[attr_name].get('description', '无描述')
        return None

    # =================================================================
    # 【改进1】OCEAN 五因素计算方法
    # =================================================================

    @staticmethod
    def compute_empathy(ocean_values):
        """
        计算共情系数 ε（Paper 1, Eq.3）

        公式: ε = 0.354·O + 0.177·C + 0.135·E + 0.312·A + 0.021·N

        含义: 共情系数越高 → 越容易被他人恐慌感染（社会传染敏感度）

        参数:
            ocean_values: dict, 包含 ocean_O/C/E/A/N

        返回:
            float: 共情系数 ε ∈ 约[-1, 1]
        """
        O = ocean_values.get('ocean_O', 0.0)
        C = ocean_values.get('ocean_C', 0.0)
        E = ocean_values.get('ocean_E', 0.0)
        A = ocean_values.get('ocean_A', 0.0)
        N = ocean_values.get('ocean_N', 0.0)
        return 0.354 * O + 0.177 * C + 0.135 * E + 0.312 * A + 0.021 * N

    @staticmethod
    def compute_emotion_params(ocean_values):
        """
        从OCEAN计算情绪激发-平复双因子模型参数（Paper 1, Eq.7-10）

        【参数含义】
        - alpha1: 激发速率。值越大 → 情绪上升越陡。
                   高神经质(N<0) + 高外向性(E>0) → 大α1
        - alpha2: 平复速率。值越大 → 情绪下降越陡。
                   高自律(C>0) + 高情绪稳定(N>0) → 大α2
        - tc:     峰值持续时长（小时）。超过tc后情绪开始下降。
                   高神经质 → 长tc（沉浸负面情绪更久）
        - te:     激发起始延迟（小时）。反应启动后到情绪真正上升的缓冲。
                   高稳定性(N>0) → 较大te

        【参考值】
        - 极度恐慌型 (N≈-1, C≈-0.5): α1≈1.8, α2≈0.3, tc≈13h
        - 领导型     (N≈-0.3, C≈0.8, E≈0.9): α1≈1.6, α2≈0.9, tc≈5h
        - 普通型     (N≈0, C≈0): α1≈1.2, α2≈0.5, tc≈8h

        返回:
            dict: {'alpha1', 'alpha2', 'tc', 'te'}
        """
        N = ocean_values.get('ocean_N', 0.0)
        C = ocean_values.get('ocean_C', 0.0)
        E = ocean_values.get('ocean_E', 0.0)
        A = ocean_values.get('ocean_A', 0.0)

        # α1: 激发速率 —— 神经质(N负)使激发更快，外向性(E正)轻微加速
        alpha1 = max(0.3, 1.2 - 0.6 * N + 0.2 * E)

        # α2: 平复速率 —— 自律性(C正)/情绪稳定(N正)/外向社交(E正)/宜人(A正)共同促进平复
        # 【改进】纳入 E 和 A，以还原"领导型人格快升快降"的论文预期
        #   领导型 ψ=⟨0,0,1,0,-1⟩: α2 = 0.4+0-0.15+0.4+0 = 0.65 (快降)
        #   焦虑型 ψ=⟨0,-1,0,0,-1⟩: α2 = 0.4-0.3-0.15+0+0 = max(0.15,-0.05)=0.15 (慢降)
        alpha2 = max(0.15, 0.4 + 0.3 * C + 0.15 * N + 0.4 * E + 0.15 * A)

        # tc: 峰值持续时长（小时）—— 神经质使峰值更持久，自律性缩短
        tc = max(2.0, 8.0 + 3.5 * (-N) - 2.0 * C)

        # te: 起始延迟（小时）—— 稳定的人情绪启动更慢
        te = max(0.0, 0.5 + 0.3 * N)

        return {'alpha1': alpha1, 'alpha2': alpha2, 'tc': tc, 'te': te}

    @staticmethod
    def ocean_to_personality(ocean_values):
        """
        从OCEAN连续值映射到离散性格类型（向后兼容）

        【映射规则】
        以情绪稳定性N为主轴，自律性C为辅轴:
        - N < -0.5              → 焦虑型（高神经质）
        - -0.5 ≤ N < -0.1      → 敏感型
        - N > 0.5 且 C > 0.3   → 理性型（高稳定+高自律）
        - N > 0.2              → 稳定型
        - 其他                  → 普通型

        注意: 此映射用于兼容下游基于离散性格类型的逻辑。
        OCEAN连续值本身才是更精确的个体描述。

        返回:
            str: 性格类型名称
        """
        N = ocean_values.get('ocean_N', 0.0)
        C = ocean_values.get('ocean_C', 0.0)
        if N < -0.5:
            return '焦虑型'
        elif N < -0.1:
            return '敏感型'
        elif N > 0.5 and C > 0.3:
            return '理性型'
        elif N > 0.2:
            return '稳定型'
        else:
            return '普通型'

    @staticmethod
    def get_special_ocean_profiles():
        """
        论文中三种典型人格的OCEAN配置（用于验证/测试）

        返回值可直接赋给 agent.ocean 后调用 compute_emotion_params
        """
        return {
            'panic_prone': {
                'ocean_O': -0.2, 'ocean_C': -0.5, 'ocean_E': -0.3,
                'ocean_A': -0.1, 'ocean_N': -0.7,
                '_desc': '极度恐慌型: α1≈1.8, α2≈0.3, 快速激发缓慢平复',
            },
            'leader': {
                'ocean_O': 0.5, 'ocean_C': 0.8, 'ocean_E': 0.9,
                'ocean_A': 0.3, 'ocean_N': -0.3,
                '_desc': '领导型: α1≈1.6, α2≈0.9, 快速激发快速平复',
            },
            'rational': {
                'ocean_O': 0.4, 'ocean_C': 0.6, 'ocean_E': 0.0,
                'ocean_A': 0.1, 'ocean_N': 0.6,
                '_desc': '理性型: α1≈0.7, α2≈0.8, 缓慢激发快速平复',
            },
        }

    # =================================================================
    # 【改进3】基于距离衰减的恐慌定量传播 - 距离核方法
    # 参考: Wang et al. 2022, Chin.Phys.B 31(6), Eq.6
    # =================================================================

    @classmethod
    def geo_distance_meters(cls, lon1, lat1, lon2, lat2):
        """
        计算两点间欧氏距离（米），使用等距投影近似。

        对厦门思明区这种小范围（<20km）精度足够（误差<1%）。

        参数:
            lon1, lat1: 点1经纬度（十进制度）
            lon2, lat2: 点2经纬度（十进制度）

        返回:
            float: 两点距离（米）
        """
        dx = (lon1 - lon2) * cls.LON_TO_M
        dy = (lat1 - lat2) * cls.LAT_TO_M
        return math.sqrt(dx * dx + dy * dy)

    @classmethod
    def distance_kernel(cls, L, sigma=None):
        """
        距离衰减核函数（方案B1: sigmoid + 尺度因子σ）

        公式: w(L) = 1 - 1/(1+exp(-L/σ))

        特征:
            L=0    → w=0.5   (论文原公式同样，并非1)
            L=σ    → w≈0.27
            L=2σ   → w≈0.12
            L=3σ   → w≈0.047
            L→∞    → w→0

        参数:
            L: 距离（米，≥0）
            sigma: 尺度因子σ（米）。若为None则用类默认值DISTANCE_KERNEL_SIGMA

        返回:
            float: 权重 ∈ (0, 0.5]
        """
        if sigma is None:
            sigma = cls.DISTANCE_KERNEL_SIGMA
        # sigma=inf 对应"无距离衰减"基线实验（S6组）
        if sigma == float('inf'):
            return 0.5  # 返回常数,所有邻居等权
        # 数值保护: L/σ > 50 时 exp(50)≈5e21 已经溢出风险,直接返回0
        ratio = L / sigma
        if ratio > 50:
            return 0.0
        return 1.0 - 1.0 / (1.0 + math.exp(-ratio))


# 全局居民属性配置实例（可在其他模块使用）
RESIDENT_ATTR_CONFIG = ResidentAttributeConfig()


class GovernmentAgent:
    """
    政府Agent - 负责资源调配和应急响应

    【行为参数（外部可调）】
    - initiative: 积极性 (0-1) → 影响资源下发意愿
    - response: 响应效率 (0.1-2.0) → 影响对压力的反应速度
    - warning_threshold: 预警阈值 → 控制何时发布预警
    - allocation_ratio: 资源分配比例 → 控制资源去向

    【状态变量（内部演化）】
    - pressure_index: 政府压力指数 (0-1)
    - current_resource_level: 当前资源量
    - response_state: 响应状态 (normal/warning/emergency)

    【事件触发状态】
    - emergency_warning_issued: 触发事件1(发布应急预警)
    - resource_to_grid: 触发事件2(分配资源给电网)
    - resource_to_enterprise: 触发事件3(分配资源给企业)
    - resource_to_resident: 触发事件4(分配资源给居民)
    - public_opinion_active: 触发事件5(实施舆情管理)
    """

    def __init__(self, initiative=0.5, response=1.0,
                 w_L=1.0, w_E=1.0, w_Q=1.0, w_C=1.0, delta=0.02,
                 behavior_config=None):
        # ============ 行为参数（外部可调）============
        self.initiative = initiative  # 积极性
        self.response = response  # 响应效率

        # 行为配置
        if behavior_config:
            self.warning_threshold = behavior_config.WARNING_OUTAGE_THRESHOLD
            self.opinion_threshold = behavior_config.OPINION_MANAGE_THRESHOLD
            self.enterprise_threshold = behavior_config.RESOURCE_TO_ENTERPRISE_THRESHOLD
            self.resident_threshold = behavior_config.RESOURCE_TO_RESIDENT_THRESHOLD
            self.allocation_grid = behavior_config.ALLOCATION_RATIO_GRID
            self.allocation_enterprise = behavior_config.ALLOCATION_RATIO_ENTERPRISE
            self.allocation_resident = behavior_config.ALLOCATION_RATIO_RESIDENT
            self.base_resource_capacity = behavior_config.RESOURCE_CAPACITY
        else:
            # 默认值 【调低阈值让事件更容易触发】
            self.warning_threshold = 0.1
            self.opinion_threshold = 0.3  # 舆情管理阈值（原0.4）
            self.enterprise_threshold = 0.1  # 分配资源给企业阈值（原0.3）
            self.resident_threshold = 0.3  # 分配资源给居民阈值（原0.5）
            self.allocation_grid = 0.5
            self.allocation_enterprise = 0.3
            self.allocation_resident = 0.2
            self.base_resource_capacity = 100.0

        # 权重参数
        self.w_L = w_L
        self.w_E = w_E
        self.w_Q = w_Q
        self.w_C = w_C
        self.delta = delta

        # 动态归一化
        self.max_loss = 1.0
        self.max_Q = 1.0
        self.max_C = 1.0

        # ============ 状态变量（内部演化）============
        self.current_resource_level = self.base_resource_capacity
        self.pressure_index = 0.0  # 政府压力指数
        self.response_state = 'normal'  # 响应状态: normal/warning/emergency

        # ============ 事件触发状态 ============
        self.emergency_warning_issued = False  # 事件1: 发布应急预警
        self.resource_to_grid = False  # 事件2: 分配资源给电网
        self.resource_to_enterprise = False  # 事件3: 分配资源给企业
        self.resource_to_resident = False  # 事件4: 分配资源给居民
        self.public_opinion_active = False  # 事件5: 实施舆情管理
        self.last_deployment = 0.0  # 上次资源下发量

        # ============ 人为控制模式 ============
        # 当use_manual_events=True时，事件触发由外部控制
        # 当use_manual_events=False时，使用自动逻辑
        self.use_manual_events = False
        self.manual_emergency_warning = False
        self.manual_resource_to_grid = False
        self.manual_resource_to_enterprise = False
        self.manual_resource_to_resident = False
        self.manual_public_opinion = False

        # ============ 区域目标控制 ============
        # target_all_zones=True时，事件影响所有区域
        # target_all_zones=False时，仅影响target_zones列表中的区域
        self.target_all_zones = True
        self.target_zones = []  # 目标区域ID列表

        # 各区域的资源分配比例（供event_influence使用）
        self.zone_resource_allocation = {}

    def is_target_zone(self, zone_id):
        """
        检查区域是否是当前目标区域

        参数:
            zone_id: 区域ID

        返回:
            bool: 是否是目标区域
        """
        if self.target_all_zones:
            return True
        return str(zone_id) in [str(z) for z in self.target_zones]

    def decide(self, loss, avg_emotion, Q, C, region_panic_levels=None, outage_ratio=0.0):
        """
        决策函数 - 基于行为参数和状态演化，计算资源下发量

        【状态演化公式】
        pressure_index = w_L×损失 + w_E×情绪 + w_Q×企业求助 + w_C×关键设施 + 0.2×恐慌

        【资源下发公式】
        deployment = initiative × 3.0 × response × (1 + pressure) × 0.4

        参数:
            loss: 企业总损失
            avg_emotion: 平均情绪
            Q: 企业总求助强度
            C: 关键设施求助强度
            region_panic_levels: 区域恐慌水平字典
            outage_ratio: 停电区域比例

        返回:
            actual_deployment: 资源下发量
        """
        # 【修改】不重置标志，让事件持续
        # 标志会在条件不满足时自动变为False

        # 更新归一化基准
        self.max_loss = max(self.max_loss, loss)
        self.max_Q = max(self.max_Q, Q)
        self.max_C = max(self.max_C, C)

        # 计算最大区域恐慌
        max_panic = 0
        if region_panic_levels:
            max_panic = max(region_panic_levels.values()) if region_panic_levels else 0

        # ============ 状态演化：计算压力指数 ============
        emotion_impact = max(0, (avg_emotion - 0.3) * 2)
        self.pressure_index = (
                self.w_L * (loss / self.max_loss if self.max_loss > 0 else 0)
                + self.w_E * emotion_impact
                + self.w_Q * (Q / self.max_Q if self.max_Q > 0 else 0)
                + self.w_C * (C / self.max_C if self.max_C > 0 else 0)
                + 0.2 * max_panic
        )
        self.pressure_index = min(1.0, self.pressure_index)

        # ============ 状态演化：更新响应状态 ============
        if outage_ratio > 0.3 or self.pressure_index > 0.7:
            self.response_state = 'emergency'
        elif outage_ratio > self.warning_threshold or self.pressure_index > 0.4:
            self.response_state = 'warning'
        else:
            self.response_state = 'normal'

        # ============ 事件1: 发布应急预警 ============
        # 【人为控制模式】由外部控制开始/结束
        # 【自动模式】停电比例 > warning_threshold 时触发
        if self.use_manual_events:
            self.emergency_warning_issued = self.manual_emergency_warning
        else:
            if outage_ratio > self.warning_threshold and not self.emergency_warning_issued:
                self.emergency_warning_issued = True
            elif outage_ratio <= self.warning_threshold * 0.5:
                self.emergency_warning_issued = False

        # ============ 事件5: 实施舆情管理 ============
        # 【人为控制模式】由外部控制开始/结束
        # 【自动模式】舆情压力 > opinion_threshold 时触发
        if self.use_manual_events:
            self.public_opinion_active = self.manual_public_opinion
        else:
            opinion_pressure = emotion_impact * 0.5 + max_panic * 0.5
            self.public_opinion_active = opinion_pressure > self.opinion_threshold

        # ============ 资源下发决策 ============
        # 公式: deployment = initiative × 3.0 × response × (1 + pressure) × 0.4
        max_willing_deploy = self.initiative * 3.0
        urgency_multiplier = self.response * (1 + self.pressure_index)

        # 紧急状态下增加资源
        if self.response_state == 'emergency':
            urgency_multiplier *= 1.5

        actual_deployment = max_willing_deploy * urgency_multiplier * 0.4

        # ============ 事件2: 政府分配资源给电网 ============
        # 【人为控制模式】由外部控制开始/结束
        # 【自动模式】有停电且有资源时触发
        if self.use_manual_events:
            self.resource_to_grid = self.manual_resource_to_grid
        else:
            if actual_deployment > 0.1 and outage_ratio > 0:
                self.resource_to_grid = True
            else:
                self.resource_to_grid = False

        self.last_deployment = actual_deployment

        return actual_deployment

    def adjust(self, public_pressure, outage_ratio):
        """保持用户设定参数不变"""
        pass

    def allocate_resources(self, enterprises, deployed_resources, region_panic_levels=None, residents=None):
        """
        资源分配给企业和居民 - 按区域严重程度差异化分配

        【核心改进】资源分配不再平均，而是按区域严重程度加权分配
        - 严重程度高的区域获得更多资源
        - 严重程度 = 停电影响 × 0.4 + 恐慌水平 × 0.3 + 企业求助 × 0.3

        参数:
            enterprises: 企业Agent列表
            deployed_resources: 下发的资源量
            region_panic_levels: 区域恐慌水平 {zone_id: panic_level}
            residents: 居民Agent列表（可选）
        """
        if deployed_resources <= 0:
            return

        # 按配置的比例分配资源
        resource_for_enterprise = deployed_resources * self.allocation_enterprise
        resource_for_resident = deployed_resources * self.allocation_resident

        # ============ 计算各区域严重程度 ============
        zone_severity = {}  # {zone_id: severity_score}

        # 按区域统计企业情况
        zone_enterprise_stats = {}  # {zone_id: {'count': n, 'total_request': x, 'crisis_count': y}}
        if enterprises:
            for e in enterprises:
                zone = getattr(e, 'zone', 'unknown')
                if zone not in zone_enterprise_stats:
                    zone_enterprise_stats[zone] = {'count': 0, 'total_request': 0, 'crisis_count': 0}
                zone_enterprise_stats[zone]['count'] += 1
                zone_enterprise_stats[zone]['total_request'] += e.request()
                if getattr(e, 'is_in_crisis', False):
                    zone_enterprise_stats[zone]['crisis_count'] += 1

        # 按区域统计居民情况
        zone_resident_stats = {}  # {zone_id: {'count': n, 'avg_emotion': x, 'outage_count': y}}
        if residents:
            for r in residents:
                zone = getattr(r, 'zone', 'unknown')
                if zone not in zone_resident_stats:
                    zone_resident_stats[zone] = {'count': 0, 'total_emotion': 0, 'outage_count': 0}
                zone_resident_stats[zone]['count'] += 1
                zone_resident_stats[zone]['total_emotion'] += r.emotion
                if not r.powered:
                    zone_resident_stats[zone]['outage_count'] += 1

        # 计算各区域综合严重程度
        all_zones = set(zone_enterprise_stats.keys()) | set(zone_resident_stats.keys())
        if region_panic_levels:
            all_zones |= set(region_panic_levels.keys())

        # 【区域过滤】如果指定了目标区域，仅计算目标区域
        if not self.target_all_zones and self.target_zones:
            all_zones = {z for z in all_zones if self.is_target_zone(z)}

        for zone in all_zones:
            # 1. 停电影响程度 (0-1)
            outage_severity = 0.0
            if zone in zone_resident_stats and zone_resident_stats[zone]['count'] > 0:
                outage_severity = zone_resident_stats[zone]['outage_count'] / zone_resident_stats[zone]['count']

            # 2. 恐慌水平 (0-1)
            panic_severity = 0.0
            if region_panic_levels and zone in region_panic_levels:
                panic_severity = region_panic_levels[zone]

            # 3. 企业求助程度 (0-1)
            enterprise_severity = 0.0
            if zone in zone_enterprise_stats and zone_enterprise_stats[zone]['count'] > 0:
                avg_request = zone_enterprise_stats[zone]['total_request'] / zone_enterprise_stats[zone]['count']
                crisis_ratio = zone_enterprise_stats[zone]['crisis_count'] / zone_enterprise_stats[zone]['count']
                enterprise_severity = avg_request * 0.6 + crisis_ratio * 0.4

            # 综合严重程度
            zone_severity[zone] = (outage_severity * 0.4 +
                                   panic_severity * 0.3 +
                                   enterprise_severity * 0.3)

        # 归一化严重程度（用于分配权重）
        total_severity = sum(zone_severity.values()) or 1.0
        zone_weights = {z: s / total_severity for z, s in zone_severity.items()}

        # ============ 事件3: 政府分配资源给企业 ============
        # 【人为控制模式】由外部控制开始/结束
        enterprise_allocated = False
        if self.use_manual_events:
            self.resource_to_enterprise = self.manual_resource_to_enterprise
            enterprise_allocated = self.resource_to_enterprise
        elif enterprises:
            avg_request = sum(e.request() for e in enterprises) / len(enterprises)

            if avg_request > self.enterprise_threshold:
                self.resource_to_enterprise = True
                enterprise_allocated = True

                # 【改进】按区域严重程度加权分配给企业
                for e in enterprises:
                    if e.request() > 0:
                        zone = getattr(e, 'zone', 'unknown')
                        zone_weight = zone_weights.get(zone, 1.0 / len(all_zones) if all_zones else 1.0)

                        # 企业获得资源 = 区域配额 × 企业在区域内的求助权重 × 类型系数
                        zone_resource = resource_for_enterprise * zone_weight * len(all_zones)

                        # 计算企业在其区域内的求助权重
                        zone_total_request = zone_enterprise_stats.get(zone, {}).get('total_request', 1.0)
                        enterprise_weight = e.request() / zone_total_request if zone_total_request > 0 else 0

                        type_multiplier = {'小型': 1.4, '中型': 1.2, '大型': 1.0}[e.enterprise_type]
                        compensation = zone_resource * enterprise_weight * type_multiplier
                        e.receive_compensation(compensation)

        if not enterprise_allocated:
            self.resource_to_enterprise = False

        # ============ 事件4: 政府分配资源给居民 ============
        # 【人为控制模式】由外部控制开始/结束
        resident_allocated = False
        if self.use_manual_events:
            self.resource_to_resident = self.manual_resource_to_resident
            resident_allocated = self.resource_to_resident
            if resident_allocated:
                self.zone_resource_allocation = zone_weights.copy()
        elif residents:
            avg_emotion = sum(r.emotion for r in residents) / len(residents)

            # 【改进】基于区域严重程度判断是否分配
            high_severity_zones = [z for z, s in zone_severity.items() if s > 0.3]

            if avg_emotion > self.resident_threshold or high_severity_zones:
                self.resource_to_resident = True
                resident_allocated = True

                # 记录各区域获得的资源比例（供event_influence使用）
                self.zone_resource_allocation = zone_weights.copy()

        # 备用：根据恐慌水平分配（非人为控制模式下）
        if not self.use_manual_events:
            if not resident_allocated and region_panic_levels:
                high_panic_zones = [z for z, p in region_panic_levels.items() if p > 0.5]
                if high_panic_zones:
                    self.resource_to_resident = True
                    resident_allocated = True

            if not resident_allocated:
                self.resource_to_resident = False


class PowerGridAgent:
    """
    电网Agent - 负责大电网故障修复

    【可调参数】
    - initiative: 积极性 (0-1) → 影响修复效率和并行修复数
    - response: 响应效率 (0.1-2.0) → 影响修复速度
    - lambda_prop: 故障传播率 (0-1) → 影响故障扩散

    【修复能力计算公式】
    修复能力 = 基础修复能力 × 资源效率 × (基础加成 + 积极程度×倍数) × (基础加成 + 响应效率×倍数)

    其中：
    - 资源效率 = 基础值 + (1-基础值) × (资源量 / (资源量 + 半效率点))
      采用Michaelis-Menten型函数，资源越多效率越高，但有上限

    【修复进度计算】
    每步修复量 = 修复能力 / 修复难度
    总需修复量 = 损坏程度 × 损坏工作系数 + 修复难度 × 难度工作系数
    修复完成条件：累计修复量 >= 总需修复量
    """

    def __init__(self, initiative=0.5, response=1.0,
                 restore_rate=4, lambda_prop=0.1, delta=0.02):
        # 【可调参数】
        self.initiative = initiative
        self.response = response
        self.lambda_prop = lambda_prop

        self.restore_rate = restore_rate
        self.delta = delta
        self.strategy = 'longest'  # 恢复策略
        self.base_recovery = 0.3
        self.feedback_factor = 0.0

        # 资源管理
        self.base_resource_capacity = 50.0
        self.current_resource_level = self.base_resource_capacity
        self.occupied_resources = 0.0

        # 区域恢复管理（现在是大电网级别的修复）
        self.ongoing_repairs = {}  # {zone_id: repair_info}

        # 事件状态
        self.is_repairing = False  # 是否正在抢修
        self.is_setting_temp_power = False  # 是否设置临时供电
        self.repair_progress_percent = 0.0  # 修复进度百分比

        # ============ 人为控制模式 ============
        # 事件7（临时供电站）和事件8（抢修）可由外部控制开始/结束
        self.use_manual_events = False
        self.manual_temp_station = False  # 事件7人为控制
        self.manual_repair = False  # 事件8人为控制

        # ============ 区域目标控制 ============
        # target_all_zones=True时，修复/临时供电影响所有区域
        # target_all_zones=False时，仅影响target_zones列表中的区域
        self.target_all_zones = True
        self.target_zones = []  # 目标区域ID列表

    def is_target_zone(self, zone_id):
        """
        检查区域是否是当前目标区域

        参数:
            zone_id: 区域ID

        返回:
            bool: 是否是目标区域
        """
        if self.target_all_zones:
            return True
        return str(zone_id) in [str(z) for z in self.target_zones]

    def calculate_repair_capacity(self, config=None):
        """
        计算当前修复能力

        公式：
        修复能力 = BASE × 资源效率 × 积极程度系数 × 响应效率系数

        资源效率 = BASE_EFF + (MAX_EFF - BASE_EFF) × R / (R + HALF)
        积极程度系数 = INIT_BASE + initiative × INIT_MULT
        响应效率系数 = RESP_BASE + response × RESP_MULT

        返回：
            float: 每步的修复能力值
        """
        # 使用默认参数或配置
        BASE = 10.0
        EFF_BASE = 0.3
        EFF_MAX = 1.0
        HALF = 50.0
        INIT_BASE = 0.5
        INIT_MULT = 2.0
        RESP_BASE = 0.3
        RESP_MULT = 1.5

        if config:
            rc = config.grid_repair
            BASE = rc.BASE_REPAIR_CAPACITY
            EFF_BASE = rc.RESOURCE_EFFICIENCY_BASE
            EFF_MAX = rc.RESOURCE_EFFICIENCY_MAX
            HALF = rc.RESOURCE_HALF_POINT
            INIT_BASE = rc.INITIATIVE_BASE
            INIT_MULT = rc.INITIATIVE_MULTIPLIER
            RESP_BASE = rc.RESPONSE_BASE
            RESP_MULT = rc.RESPONSE_MULTIPLIER

        # 资源效率：Michaelis-Menten型函数
        R = self.current_resource_level
        resource_efficiency = EFF_BASE + (EFF_MAX - EFF_BASE) * R / (R + HALF)

        # 积极程度系数
        initiative_factor = INIT_BASE + self.initiative * INIT_MULT

        # 响应效率系数
        response_factor = RESP_BASE + self.response * RESP_MULT

        # 总修复能力
        capacity = BASE * resource_efficiency * initiative_factor * response_factor

        return capacity

    def calculate_total_work(self, damage_level, repair_difficulty, config=None):
        """
        计算总修复工作量

        公式：
        总工作量 = 损坏程度 × 损坏系数 + 修复难度 × 难度系数

        参数：
            damage_level: 损坏程度 (0-100)
            repair_difficulty: 修复难度系数 (由停电原因决定)

        返回：
            float: 总需修复的工作量
        """
        DAMAGE_MULT = 2.0
        DIFF_MULT = 5.0

        if config:
            rc = config.grid_repair
            DAMAGE_MULT = rc.DAMAGE_WORK_MULTIPLIER
            DIFF_MULT = rc.DIFFICULTY_WORK_MULTIPLIER

        total_work = damage_level * DAMAGE_MULT + repair_difficulty * DIFF_MULT
        return max(1.0, total_work)  # 最小工作量为1

    def decide_recovery(self, gov_influence, outage_ratio, public_pressure, region_panic_levels=None):
        """计算恢复决策（兼容旧接口）"""
        self.feedback_factor = gov_influence
        return self.calculate_repair_capacity()

    def adjust(self, outage_ratio, public_pressure):
        pass

    def update_resources(self, gov_support=0.0):
        """
        更新资源池

        政府支持会增加资源容量
        """
        if gov_support > 0:
            support_efficiency = 0.5
            resource_gain = gov_support * support_efficiency
            self.base_resource_capacity = min(100.0, self.base_resource_capacity + resource_gain)

        self.current_resource_level = max(0, self.base_resource_capacity - self.occupied_resources)

    def start_repair(self, zone, damage_level, repair_difficulty, config=None):
        """
        开始修复大电网

        参数：
            zone: 区域ID（或"main_grid"表示大电网）
            damage_level: 损坏程度 (0-100)，由外部停电原因决定
            repair_difficulty: 修复难度系数，由停电原因决定
            config: 配置对象

        返回：
            bool: 是否成功开始修复
        """
        if zone in self.ongoing_repairs:
            return False

        # 计算总工作量
        total_work = self.calculate_total_work(damage_level, repair_difficulty, config)

        # 计算所需资源（与工作量成正比）
        resources_needed = total_work * 0.1

        if self.current_resource_level >= resources_needed:
            self.ongoing_repairs[zone] = {
                'damage_level': damage_level,
                'repair_difficulty': repair_difficulty,
                'progress': 0.0,
                'total_work': total_work,
                'resources_needed': resources_needed,
                'start_time': 0  # 将由simulation设置
            }
            self.occupied_resources += resources_needed
            self.current_resource_level = max(0, self.base_resource_capacity - self.occupied_resources)
            self.is_repairing = True
            return True
        return False

    def update_repairs(self, config=None):
        """
        更新修复进度（针对多区域分别修复的情况）

        每步根据修复能力推进进度

        返回：
            list: 修复完成的区域列表
        """
        completed_zones = []

        # 计算当前修复能力
        capacity = self.calculate_repair_capacity(config)

        # 获取时间步长
        dt = 0.25  # 默认15分钟
        if config:
            dt = config.simulation.DT

        # 分配修复能力给所有正在修复的区域
        n_repairs = len(self.ongoing_repairs)
        if n_repairs == 0:
            self.is_repairing = False
            self.repair_progress_percent = 0.0
            return completed_zones

        # 每个区域分配的修复能力
        capacity_per_zone = capacity / n_repairs

        total_progress = 0.0
        total_work = 0.0

        for zone, repair_info in list(self.ongoing_repairs.items()):
            # 每步修复量 = 分配能力 × DT
            work_done = capacity_per_zone * dt

            repair_info['progress'] += work_done

            # 统计总进度
            total_progress += repair_info['progress']
            total_work += repair_info['total_work']

            # 检查是否完成
            if repair_info['progress'] >= repair_info['total_work']:
                completed_zones.append(zone)

        # 更新修复进度百分比
        if total_work > 0:
            self.repair_progress_percent = min(100.0, total_progress / total_work * 100)

        # 清理完成的修复
        for zone in completed_zones:
            repair_info = self.ongoing_repairs.pop(zone)
            self.occupied_resources -= repair_info['resources_needed']
            self.current_resource_level = max(0, self.base_resource_capacity - self.occupied_resources)

        # 更新修复状态
        self.is_repairing = len(self.ongoing_repairs) > 0

        return completed_zones

    def update_district_repair(self, total_work, config=None):
        """
        更新行政区级（大电网）修复进度

        【计算公式】
        - 修复能力 = 基础能力 × 资源效率 × 积极程度系数 × 响应效率系数
        - 每步修复量 = 修复能力 × DT
        - 修复进度 = 累计修复量 / 总工作量

        【时间换算】（DT=0.25小时=15分钟）
        - 如果修复能力=5，总工作量=100
        - 每步修复量 = 5 × 0.25 = 1.25
        - 需要步数 = 100 / 1.25 = 80步 = 20小时

        参数：
            total_work: 总工作量
            config: 配置对象

        返回：
            float: 修复进度 (0.0 - 1.0)
        """
        # 获取时间步长
        dt = 0.25  # 默认15分钟
        if config:
            dt = config.simulation.DT

        # 计算当前修复能力
        capacity = self.calculate_repair_capacity(config)

        # 每步修复量
        work_done = capacity * dt

        # 更新累计修复量
        if not hasattr(self, 'district_repair_done'):
            self.district_repair_done = 0.0

        self.district_repair_done += work_done

        # 计算进度
        progress = self.district_repair_done / max(1.0, total_work)

        # 更新修复进度百分比（用于显示）
        self.repair_progress_percent = min(100.0, progress * 100)
        self.is_repairing = progress < 1.0

        return min(1.0, progress)

    def reset_district_repair(self):
        """重置行政区修复进度（用于新的停电事件）"""
        self.district_repair_done = 0.0
        self.repair_progress_percent = 0.0
        self.is_repairing = True

    def get_max_concurrent_repairs(self, gov_support_level=0.0, config=None):
        """
        计算最大同时修复数量

        公式：
        最大并行数 = BASE + initiative × 3 + gov_bonus + response_bonus
        """
        BASE = 2
        MAX_CONCURRENT = 8

        if config:
            rc = config.grid_repair
            BASE = rc.MAX_CONCURRENT_REPAIRS_BASE
            MAX_CONCURRENT = rc.MAX_CONCURRENT_REPAIRS_MAX

        initiative_bonus = self.initiative * 3

        gov_bonus = 0
        if gov_support_level > 0.5:
            effective_support = (gov_support_level - 0.5) / 0.5
            gov_bonus = effective_support * 1.5

        response_bonus = max(0, (self.response - 1.0)) * 2

        total_concurrent = BASE + initiative_bonus + gov_bonus + response_bonus
        return max(1, min(MAX_CONCURRENT, int(total_concurrent)))

    def get_repair_status(self):
        """获取当前修复状态信息"""
        return {
            'is_repairing': self.is_repairing,
            'ongoing_count': len(self.ongoing_repairs),
            'progress_percent': self.repair_progress_percent,
            'resource_level': self.current_resource_level,
            'zones': list(self.ongoing_repairs.keys())
        }


class EnterpriseAgent:
    """
    企业Agent - 模拟停电对企业的影响

    【可调参数】
    - initiative: 积极性 (0-1)
    - response: 响应效率 (0.1-2.0)

    【个体差异属性】
    - enterprise_type: 企业规模 (小型/中型/大型)
    - industry: 行业类型 (影响对停电的敏感度)
    - financial_reserve: 资金储备 (0-1, 影响抗压能力)
    - backup_power: 备用电源能力 (0-1, 影响危机延迟)
    - management_level: 管理水平 (0-1, 影响应急响应)

    【输出数据】用于画图
    - request() → Q_hist (企业求助强度曲线)
    - loss → 累计损失（可选显示）

    【事件触发状态】
    - is_requesting: 是否正在请求资源
    - is_in_crisis: 是否处于经营危机
    - is_shutdown: 是否已停工
    - just_resumed: 本步是否刚恢复生产
    """

    def __init__(self, initiative=0.5, response=1.0, cost_rate=1.0, delta=0.02):
        self.initiative = initiative
        self.response = response
        self.cost_rate = cost_rate
        self.loss = 0.0
        self.delta = delta

        # 位置信息（会被区域管理器更新）
        self.x = 0.0
        self.y = 0.0
        self.zone = None
        self.powered = True
        self._is_load_shed = False  # 【新增】切负荷标记（部分停电时使用）

        # =================================================================
        # 【企业个体差异属性】
        # =================================================================

        # 企业规模类型
        self.enterprise_type = random.choices(
            ['小型', '中型', '大型'],
            weights=[0.6, 0.3, 0.1]  # 小型企业占多数
        )[0]

        # 【新增】行业类型 - 不同行业对停电敏感度不同
        self.industry = random.choices(
            ['制造业', '服务业', '零售业', 'IT科技', '餐饮业', '医疗健康'],
            weights=[0.25, 0.20, 0.20, 0.15, 0.15, 0.05]
        )[0]

        # 【新增】资金储备 - 影响抗压能力
        # 不同规模企业的资金储备分布不同
        reserve_ranges = {
            '小型': (0.1, 0.4),  # 小型企业资金紧张
            '中型': (0.3, 0.7),
            '大型': (0.5, 0.9),  # 大型企业资金雄厚
        }
        r_min, r_max = reserve_ranges[self.enterprise_type]
        self.financial_reserve = random.uniform(r_min, r_max)

        # 【新增】备用电源能力 - 影响能撑多久
        # IT科技和医疗健康更可能有备用电源
        backup_base = {'IT科技': 0.6, '医疗健康': 0.7}.get(self.industry, 0.2)
        type_bonus = {'大型': 0.3, '中型': 0.15, '小型': 0}.get(self.enterprise_type, 0)
        self.backup_power = min(1.0, backup_base + type_bonus + random.uniform(-0.1, 0.2))

        # 【新增】管理水平 - 影响应急响应效率
        mgmt_ranges = {
            '小型': (0.2, 0.6),
            '中型': (0.4, 0.8),
            '大型': (0.6, 0.95),
        }
        m_min, m_max = mgmt_ranges[self.enterprise_type]
        self.management_level = random.uniform(m_min, m_max)

        # =================================================================
        # 【计算综合抗压能力】
        # =================================================================

        # 类型基础参数
        type_params = {
            '小型': {'urgency': 1.5, 'recovery': 0.8, 'crisis_mult': 0.7},
            '中型': {'urgency': 1.0, 'recovery': 1.0, 'crisis_mult': 1.0},
            '大型': {'urgency': 0.7, 'recovery': 1.3, 'crisis_mult': 1.5},
        }
        params = type_params[self.enterprise_type]

        # 行业敏感度 - 影响损失速度和危机触发
        industry_sensitivity = {
            '制造业': 1.2,  # 停电影响大
            '服务业': 0.9,
            '零售业': 1.0,
            'IT科技': 1.3,  # 数据中心等对停电非常敏感
            '餐饮业': 1.1,  # 食材保鲜问题
            '医疗健康': 1.5,  # 医疗设备，影响最大
        }
        self.industry_sensitivity = industry_sensitivity.get(self.industry, 1.0)

        # 综合抗压系数 = 资金储备 × 0.3 + 备用电源 × 0.4 + 管理水平 × 0.3
        self.stress_resistance = (
                self.financial_reserve * 0.3 +
                self.backup_power * 0.4 +
                self.management_level * 0.3
        )

        # 应用抗压系数调整参数
        self.urgency_factor = params['urgency'] * (1.5 - self.stress_resistance)  # 抗压强则不急
        self.recovery_factor = params['recovery'] * (0.7 + self.stress_resistance * 0.6)  # 抗压强恢复快

        # 求助机制
        self.outage_duration = 0.0
        self.last_compensation = 0.0
        self.desperation_level = 0.0
        self.base_initiative = initiative

        self.current_request_intensity = 0.0
        self.recovery_rate = 0.01 * self.recovery_factor

        # 成本损失率受行业和规模影响
        self.cost_rate = cost_rate * self.industry_sensitivity * {
            '小型': 0.8, '中型': 1.0, '大型': 1.3  # 大型企业单位时间损失更大
        }[self.enterprise_type]

        # ============ 事件触发状态 ============
        self.is_requesting = False
        self.is_in_crisis = False
        self.is_shutdown = False
        self.just_resumed = False
        self.prev_powered = True

        # ============ 【新增】企业恢复渐进化属性 ============
        #
        # 【设计理念】
        # 1. 恢复供电后，企业不是立即恢复生产
        # 2. 需要时间：设备重启、人员召回、检查安全
        # 3. 不同企业恢复时间不同（规模、行业、管理水平）
        #
        self.recovery_delay = 0.0  # 恢复延迟（小时）
        self.is_recovering = False  # 是否正在恢复中
        self.recovery_progress = 0.0  # 恢复进度 [0,1]
        self.power_restored_time = 0.0  # 恢复供电的时刻

        # 【恢复时间计算】基于企业特性
        # - 小型企业：恢复快（1-3小时）
        # - 中型企业：中等（2-6小时）
        # - 大型企业：恢复慢（4-12小时）但有更多资源
        base_recovery = {
            '小型': random.uniform(1, 3),
            '中型': random.uniform(2, 6),
            '大型': random.uniform(4, 12),
        }.get(self.enterprise_type, 3)

        # 管理水平影响恢复速度
        management_factor = 1.0 - self.management_level * 0.4  # [0.6, 1.0]

        # 行业影响（制造业恢复慢，服务业恢复快）
        industry_factor = {
            '制造业': 1.3,
            '服务业': 0.7,
            '商业': 0.8,
            '金融业': 0.6,
            '科技业': 0.9,
        }.get(self.industry, 1.0)

        self.base_recovery_time = base_recovery * management_factor * industry_factor

        # 恢复优先级（用于决定恢复顺序）
        # 大型企业、管理好的企业优先恢复
        self.recovery_priority = (
                0.3 * (1 if self.enterprise_type == '大型' else 0.5 if self.enterprise_type == '中型' else 0.2) +
                0.3 * self.management_level +
                0.2 * self.financial_reserve +
                0.2 * random.random()  # 随机因素
        )

        # =================================================================
        # 【个体化阈值计算】- 让不同企业在不同时间触发事件
        # =================================================================

        crisis_mult = params['crisis_mult']

        # 基础随机因子
        random_factor = random.uniform(0.75, 1.25)

        # 抗压能力调整阈值
        resistance_mult = 0.7 + self.stress_resistance * 0.6  # [0.7, 1.3]

        # 求助阈值：抗压强的企业不容易求助
        self.request_threshold = 0.15 * random_factor * resistance_mult

        # 危机阈值：抗压强的企业危机门槛高
        self.crisis_threshold = 0.25 * random_factor * resistance_mult

        # 危机所需停电时长：
        # - 备用电源可以延长
        # - 资金储备可以延长
        # - 管理水平可以延长
        backup_hours = self.backup_power * 8  # 备用电源最多撑8小时
        base_duration = 15.0 * crisis_mult * random_factor
        self.crisis_duration = base_duration + backup_hours + self.financial_reserve * 5

    def step(self, powered, dt=1.0):
        """
        每步更新 - 考虑企业个体差异

        【个体差异影响】
        - backup_power: 有备用电源的企业在停电初期不会立即受影响
        - stress_resistance: 抗压能力影响危机触发和求助强度
        - industry_sensitivity: 行业敏感度影响损失速度
        """
        # 重置本步事件状态
        self.just_resumed = False

        # ============ 事件12/13: 企业停工/恢复生产 ============
        # 【改进1】有备用电源的企业不会立即停工
        # 【改进2】恢复生产是渐进的，需要时间

        if self.prev_powered and not powered:
            # 从有电变为停电
            if self.backup_power < 0.3:
                # 无/低备用电源：立即停工
                self.is_shutdown = True
            else:
                # 有备用电源：延迟停工（在outage_duration超过备用时长后）
                self.is_shutdown = False
            # 重置恢复状态
            self.is_recovering = False
            self.recovery_progress = 0.0

        elif not self.prev_powered and powered:
            # 从停电变为有电 → 开始恢复过程（不是立即恢复！）
            if not self.is_recovering:
                self.is_recovering = True
                self.power_restored_time = 0.0
                self.recovery_progress = 0.0
                # 恢复延迟 = 基础恢复时间 × (1 + 停电时长影响)
                # 停电越久，设备损坏越多，恢复越慢
                outage_penalty = min(1.0, self.outage_duration / 48)  # 48小时后翻倍
                self.recovery_delay = self.base_recovery_time * (1 + outage_penalty * 0.5)

        # 【渐进式恢复过程】
        if self.is_recovering and powered:
            self.power_restored_time += dt

            # 恢复进度 = 已恢复时间 / 所需恢复时间
            self.recovery_progress = min(1.0, self.power_restored_time / self.recovery_delay)

            # 恢复完成
            if self.recovery_progress >= 1.0:
                self.is_recovering = False
                self.is_shutdown = False
                self.just_resumed = True  # 这一步才真正恢复生产
            else:
                # 恢复中：仍算停工状态，但损失逐渐减少
                self.is_shutdown = True
                self.just_resumed = False
        elif powered and not self.is_recovering and not self.just_resumed:
            # 正常供电状态
            self.is_shutdown = False

        self.prev_powered = powered
        self.powered = powered

        if not powered:
            # 【改进】备用电源期间损失减半
            backup_hours = self.backup_power * 8
            if self.outage_duration < backup_hours:
                # 备用电源运行中，损失减半
                effective_loss = self.cost_rate * dt * 0.5
                # 备用电源期间不算完全停工
                if not self.is_shutdown and self.outage_duration > backup_hours * 0.8:
                    # 备用电源快耗尽，准备停工
                    self.is_shutdown = True
            else:
                # 备用电源耗尽，全额损失
                effective_loss = self.cost_rate * dt
                self.is_shutdown = True

            self.loss += effective_loss
            self.outage_duration += dt

            # 危机程度计算：考虑备用电源延长的时间
            effective_duration = max(0, self.outage_duration - backup_hours)
            self.desperation_level = min(1.0, effective_duration / self.crisis_duration)

            # 求助强度增加：抗压能力强的企业增长慢
            intensity_increase = 0.08 * dt * self.urgency_factor
            # 管理水平高的企业更能控制求助节奏
            intensity_increase *= (1.3 - self.management_level * 0.5)
            self.current_request_intensity = min(1.0, self.current_request_intensity + intensity_increase)

            # ============ 事件11: 企业经营危机 ============
            # 不同企业因抗压能力不同，在不同时间进入危机
            self.is_in_crisis = self.desperation_level > self.crisis_threshold
        else:
            # 恢复供电
            recovery_speed = 0.1 * self.recovery_factor
            self.desperation_level = max(0.0, self.desperation_level - dt * recovery_speed)
            self.outage_duration = 0.0

            # 【新增】恢复期间的损失计算
            # 恢复中的企业仍有部分损失（设备重启、人员召回成本）
            if self.is_recovering:
                # 损失随恢复进度减少：100% → 0%
                recovery_loss_ratio = 1.0 - self.recovery_progress
                recovery_loss = self.cost_rate * dt * recovery_loss_ratio * 0.3  # 最多30%的损失
                self.loss += recovery_loss

            # 管理水平高的企业恢复更快
            effective_recovery_rate = self.recovery_rate * (0.8 + self.management_level * 0.4)
            self.current_request_intensity = max(0.0,
                                                 self.current_request_intensity - effective_recovery_rate * dt)

            # 恢复后解除危机
            if self.desperation_level < 0.15:
                self.is_in_crisis = False

        # ============ 事件10: 企业请求资源 ============
        self.is_requesting = self.request() > self.request_threshold

    def request(self):
        """计算求助强度"""
        initiative_modifier = 0.5 + 0.5 * self.initiative
        return min(1.0, self.current_request_intensity * initiative_modifier)

    def receive_compensation(self, amount):
        """接收补偿"""
        self.last_compensation = amount
        self.loss = max(0, self.loss - amount)
        self.initiative = min(1.0, self.initiative + 0.1)

    def adjust(self, outage_ratio):
        if not self.powered:
            if self.desperation_level > 0.5:
                self.initiative = min(1.0, self.initiative + self.delta * 0.5)
            else:
                self.initiative = max(0.3, self.initiative - self.delta * 0.5)
        else:
            if self.initiative < self.base_initiative:
                self.initiative = min(self.base_initiative, self.initiative + self.delta * 0.3)


class ResidentAgent:
    """
    居民Agent - 整合社会力+恐慌模型+属性系统，支持小范围移动

    【居民属性】来自顾松宇-江猛-多主体11.27.py
    - age: 年龄 (0-100)
    - health_status: 健康状态 ('健康', '亚健康', '轻微疾病', '严重疾病', '残疾')
    - 可通过 ResidentAttributeConfig 扩展更多属性

    【输出数据】用于画图
    - emotion → emotion_hist (情绪曲线)
    - state → seir_hist (SEIR分布)
    - x, y → 地图上的位置
    - panic_value → 恐慌值（地图颜色）

    【新增特性】
    - 基于社会力的小范围移动
    - 恐慌传播机制
    - PTS（恐慌状态）
    """

    def __init__(self, initiative=0.5, response=1.0,
                 alpha=0.1, beta=0.15, delta=0.02, seir_type='S',
                 attr_config=None):
        """
        初始化居民Agent

        参数:
            initiative: 积极性
            response: 响应效率
            alpha, beta, delta: 情绪模型参数
            seir_type: SEIR初始状态 ('S', 'E', 'I', 'R')
            attr_config: ResidentAttributeConfig实例，用于生成属性
        """
        # 基础参数
        self.initiative = initiative
        self.response = response
        # 注：alpha / beta / delta 入参保留仅为兼容旧调用签名（如 simulation.py 传入
        # config.agent.RESIDENT_ALPHA / RESIDENT_BETA），实际不再存储为实例属性。
        # 心理压力动力学完全由 unified_stress_model 接管，其内部自有 α / β 设定。

        # =================================================================
        # 【居民属性系统】来自顾松宇-江猛-多主体11.27.py
        # =================================================================
        if attr_config is None:
            attr_config = RESIDENT_ATTR_CONFIG

        # 生成所有配置的属性
        self.attributes = attr_config.generate_all_attributes()

        # 直接访问常用属性（兼容性）
        self.age = self.attributes.get('age', random.randint(0, 100))
        self.health_status = self.attributes.get('health_status', '健康')
        self.social_activity = self.attributes.get('social_activity', 0.5)
        self.stress_resistance = self.attributes.get('stress_resistance', 0.6)

        # =============================================================
        # 【改进1】OCEAN五因素提取 + 共情系数 + 向后兼容性格映射
        # =============================================================
        self.ocean = {
            'ocean_O': self.attributes.get('ocean_O', 0.0),
            'ocean_C': self.attributes.get('ocean_C', 0.0),
            'ocean_E': self.attributes.get('ocean_E', 0.0),
            'ocean_A': self.attributes.get('ocean_A', 0.0),
            'ocean_N': self.attributes.get('ocean_N', 0.0),
        }

        # 共情系数 ε：影响社会传染敏感度（高ε → 更容易被邻居恐慌感染）
        self.empathy = attr_config.compute_empathy(self.ocean)

        # 从OCEAN推导离散性格类型（向后兼容下游所有基于personality的逻辑）
        # 注意：不再使用 self.attributes.get('personality')，改为OCEAN推导
        self.personality = attr_config.ocean_to_personality(self.ocean)
        # 同步到 attributes 字典，保证 self.attributes['personality'] 与 self.personality 一致
        self.attributes['personality'] = self.personality

        # =============================================================
        # 【改进2】情绪激发-平复双因子模型参数 (Paper 1, Eq.7-10)
        # =============================================================
        # Pe(t) = 1/(1+exp(-α1·(t-te)))  控制激发速度
        # Pc(t) = 1/(1+exp( α2·(t-tc-te))) 控制平复速度
        # P(t) = min(Pe, Pc)  产生"先升后降"的山丘形情绪包络
        #
        emotion_params = attr_config.compute_emotion_params(self.ocean)
        self.alpha1_emotion = emotion_params['alpha1']  # 激发速率
        self.alpha2_emotion = emotion_params['alpha2']  # 平复速率
        self.tc_emotion = emotion_params['tc']  # 峰值持续时长（小时）
        self.te_emotion = emotion_params['te']  # 激发起始延迟（小时）
        self.emotion_reaction_time = 0.0  # 情绪反应累计时间（小时）

        # 根据属性调整行为参数
        self._apply_attribute_effects()
        # =================================================================

        # 情绪状态 [0,1]
        self.emotion = 0.0
        self.t_outage = 0.0
        self.powered = True
        self.informed = False
        self._is_load_shed = False  # 【新增】切负荷标记（部分停电时使用）

        # 位置（经纬度坐标）
        self.x = 0.0
        self.y = 0.0
        self.zone = None
        self.neighbors = []

        # SEIR状态
        self.state = seir_type
        self.incubation = 0.0
        self.recovery_time = 0.0
        self.safe_time = 0.0

        # =============================================================
        # 【改进3 · 论文 Eq.前后文 + 2.2.1 描述】T1/T2 双阈值机制
        # =============================================================
        # T1: 易感阈值（susceptible threshold），stress ≥ T1 → S→E (开始恐慌)
        #     均值由共情系数 ε 决定: μ_T1 = 0.5 + 0.5·ε
        # T2: 传播阈值（spreading/expressive threshold），stress ≥ T2 → E→I (开始传播恐慌)
        #     均值由外向性 ψ^E 决定: μ_T2 = 0.5 + 0.5·ψ^E
        #
        # 个体化：每人初始化时各采样一次，此后固定（论文 B1 设定）。
        # 噪声：论文原方差为 μ²/10，此处放大 2× → σ² = 2·μ²/10 = μ²/5
        # 修正：论文未保证 T1 < T2，此处强制 T2 ≥ T1 + 0.1（C1 方案兜底）
        #
        _psi_E = self.ocean['ocean_E']
        _mu_T1 = 0.5 + 0.5 * self.empathy  # 共情决定易感阈值
        _mu_T2 = 0.5 + 0.5 * _psi_E  # 外向性决定传播阈值
        _var_T1 = 2.0 * (_mu_T1 ** 2) / 10  # 放大 2× 后的方差
        _var_T2 = 2.0 * (_mu_T2 ** 2) / 10
        # random.gauss(μ, σ) 接受标准差，因此用 sqrt
        self.T1 = random.gauss(_mu_T1, math.sqrt(abs(_var_T1)))
        self.T2 = random.gauss(_mu_T2, math.sqrt(abs(_var_T2)))
        # 值域裁剪：T1 上限 0.85（为 T2 留足 0.1 的 gap 空间，避免边界兜底失效）
        self.T1 = max(0.05, min(0.85, self.T1))
        self.T2 = max(0.05, min(0.95, self.T2))
        # 强制 T2 ≥ T1 + 0.1 (C1 兜底，防止 T1>T2 的逻辑矛盾)
        if self.T2 < self.T1 + 0.1:
            self.T2 = min(0.95, self.T1 + 0.1)

        # 【降级滞后计时器】防止 stress 在阈值附近抖动导致 SEIR 状态反复翻转
        # 设计：I→E 和 E→S 降级时需要"持续维持"低 stress 一段时间才真正降级
        #
        # ★ 滞后时间可调 ★（直接修改下面两个常量即可）
        self.SEIR_DEGRADE_I_TO_E_HOURS = 2.0  # I→E 降级滞后时长（初始设置2小时）符合论文中提出的快速激发缓慢恢复
        self.SEIR_DEGRADE_E_TO_S_HOURS = 1.0  # E→S 降级滞后时长（初始设置1小时）

        # 累计"低于阈值"的时长（滞后计数器）
        self._below_T2_hours = 0.0  # stress 低于 T2 已持续多久
        self._below_T1_hours = 0.0  # stress 低于 T1 已持续多久

        # 【社会力模型属性】
        self.velocity = np.array([0.0, 0.0])  # 速度向量
        self.acceleration = np.array([0.0, 0.0])
        self.mobility = random.uniform(0.1, 0.5)  # 移动性
        self.radius = 0.0001  # 行人半径（经纬度单位）
        self.mass = 1.0

        # 【恐慌模型属性】
        self.panic_value = 0.0  # 恐慌值 [0,1]
        self.pts_status = False  # PTS状态
        self.home_position = None  # 家的位置（用于计算静态场）

        # ============================================================
        # 【统一心理压力模型】- 基于Lazarus应激-评估-应对理论
        # ============================================================
        #
        # 【核心设计】
        # stress_level = f(威胁感知 T, 应对资源 C, 社会传染, 事件影响)
        # 动力学: dσ/dt = α·T·(1-σ) - β·C·σ + γ·(σ̄-σ) + 事件项
        #
        # emotion 和 panic_value 作为派生量:
        #   panic_value = stress ** 0.8   (凹函数，低压力时 panic 相对放大)
        #   emotion     = 一阶滤波 → stress * 0.9 (平滑持续情绪)
        #
        self.stress_level = 0.0  # 心理压力值 [0,1]（主量）
        self.peak_stress = 0.0  # 峰值压力（长尾效应用）
        self._stress_components = {}  # 压力分量详情（调试用）

        # 【心理创伤/长尾效应属性】
        # 注：原有的 peak_panic / trauma_level / recovery_resistance 字段已废弃
        # （初始化后从未被读写），长尾效应现由 unified_stress_model 的 peak_stress
        # 和 powered_recovery 分支统一处理。
        self.total_outage_hours = 0.0  # 累计停电时长

        # 【停电恢复后长尾效应】- 新增
        self.time_since_recovery = 0.0  # 恢复供电后经过的时间（小时）
        self.was_affected = False  # 是否曾受停电影响（用于判断是否需要长尾效应）
        self.recovery_phase = False  # 是否处于恢复期
        self.max_emotion_during_outage = 0.0  # 停电期间的最高情绪值
        self.prev_powered_state = True  # 上一步的供电状态

        # 【区域差异化属性】- 在distribute_residents时设置
        self.zone_spread_index = 0.5  # 所在区域的传播指数 [0,1]
        self.zone_vulnerability_index = 0.5  # 所在区域的脆弱指数 [0,1]

        # ============ 【新增】信息传播系统 ============
        #
        # 【设计理念】
        # 1. 信息分为：官方信息(official)、谣言(rumor)、混合信息(mixed)
        # 2. 谣言传播更快，但可信度下降
        # 3. 官方信息可抑制谣言，但传播较慢
        # 4. 信息可信度影响情绪和恐慌
        #
        self.info_received = {
            'official': 0.0,  # 官方信息量 [0,1]
            'rumor': 0.0,  # 谣言信息量 [0,1]
        }
        self.info_credibility = 0.5  # 当前持有信息的可信度 [0,1]
        self.is_spreading_rumor = False  # 是否在传播谣言
        self.rumor_belief = 0.0  # 对谣言的相信程度 [0,1]

        # 【信息敏感度】基于性格
        # 焦虑型更容易相信谣言，理性型更依赖官方信息
        self.rumor_susceptibility = {
            '焦虑型': 0.8,  # 很容易相信谣言
            '敏感型': 0.6,
            '普通型': 0.4,
            '稳定型': 0.3,
            '理性型': 0.15,  # 不容易相信谣言
        }.get(self.personality, 0.4)

        # 【社交媒体使用频率】影响谣言传播速度
        # 年轻人使用更频繁
        if self.age < 30:
            self.social_media_usage = random.uniform(0.6, 0.95)
        elif self.age < 50:
            self.social_media_usage = random.uniform(0.4, 0.7)
        elif self.age < 65:
            self.social_media_usage = random.uniform(0.2, 0.5)
        else:
            self.social_media_usage = random.uniform(0.05, 0.25)

        # 注：原有的 reaction_start_delay 启动延迟机制已废弃。
        # 现在的"延迟反应"由 unified_stress_model 的 tolerance 机制完整实现：
        # 不同属性（性格/年龄/健康/抗压）的人 tolerance 不同，
        # 只有 internal_stress 超过 tolerance 后 stress 才显著增长，
        # 因此反应时间自然因人而异（见 calculate_stress_change 的"延迟机制"段）。

        # 移动参数（根据年龄和健康状态调整）
        self.max_speed = 0.0003  # 最大速度（经纬度/步）
        self.desired_speed = 0.0001
        self._adjust_mobility_by_attributes()

        # ============ 事件触发状态 ============
        self.is_hoarding = False  # 是否在囤积物资
        self.is_gathering = False  # 是否在聚集/传播信息
        self.is_requesting_power = False  # 是否在请求恢复供电
        self.is_emotion_burst = False  # 是否情绪爆发
        self.is_self_helping = False  # 是否在自救互助

        # 【行为影响情绪】
        self.recent_movement = 0.0  # 最近移动量（用于计算行为对情绪的影响）
        self.gathering_count = 0  # 聚集次数
        self.last_position = None  # 上一步位置

        # ============ 个人物资储备系统 ============
        # 【核心理念】
        # 1. 每个居民家里本来有一定物资储备
        # 2. 停电后物资逐渐消耗（用电器不能用，需要备用物资）
        # 3. 物资快用完了 + 感觉停电还要持续 → 触发囤积
        # 4. 去商店抢购 → 成功/失败影响情绪

        # 个人物资储备初始值（不同人储备习惯不同）
        # 理性型、老人通常储备更多，年轻人储备少
        base_supply = random.uniform(0.6, 1.0)
        personality_supply_bonus = {'焦虑型': 0.1, '普通型': 0.0, '理性型': 0.15}.get(self.personality, 0)
        age_supply_bonus = 0.1 if self.age > 50 else (-0.1 if self.age < 30 else 0)

        self.personal_supply = min(1.0, base_supply + personality_supply_bonus + age_supply_bonus)

        # 物资消耗速率（每小时消耗比例）
        # 停电时消耗更快（需要用蜡烛、电池、备用食物等）
        self.supply_consumption_normal = 0.005  # 有电时：每小时0.5%
        self.supply_consumption_outage = 0.02  # 停电时：每小时2%

        # 囤积触发阈值（物资低于这个值时考虑囤积）
        self.supply_warning_threshold = 0.4  # 物资<40%时开始警惕
        self.supply_critical_threshold = 0.2  # 物资<20%时紧急囤积

        # 区域物资（商店库存），由simulation传入
        self.zone_supply_level = 1.0  # 所在区域物资水平 [0,1]
        self.supply_shortage = False  # 区域物资短缺标志
        self.supply_critical = False  # 区域物资严重短缺标志

        # 囤积状态
        self.hoarding_success = True  # 囤积是否成功（能否买到物资）
        self.hoarding_attempts = 0  # 尝试囤积次数
        self.hoarding_failures = 0  # 囤积失败次数（抢不到物资）
        self.last_hoarding_time = -999  # 上次囤积时间（避免频繁囤积）

        # 注: 事件触发阈值相关的个体差异已由 _apply_attribute_effects
        # 写入 self.combined_threshold_mult（在构造函数早期调用）。
        # 此处不再需要单独的 hoarding_threshold / power_request_threshold 等字段。

    def _apply_attribute_effects(self):
        """
        根据居民属性调整行为参数和事件触发阈值

        【核心机制】
        - 性格：影响情绪敏感度alpha和所有事件阈值
        - 年龄：影响alpha、initiative、response和阈值
        - 健康状态：影响各项参数
        - 抗压能力：影响危机相关阈值
        - 社交活跃度：影响聚集/传播相关行为

        【结果】不同属性组合的居民会在不同时间点触发事件，形成扩散效果
        """
        # =================================================================
        # 【性格影响】- 核心差异化因素
        # =================================================================
        personality_effects = {
            '理性型': {
                'alpha_mult': 0.6,  # 情绪敏感度低
                'threshold_mult': 1.4,  # 所有阈值提高40%（更难触发事件）
                'recovery_mult': 1.3,  # 情绪恢复更快
            },
            '稳定型': {
                'alpha_mult': 0.8,
                'threshold_mult': 1.2,
                'recovery_mult': 1.15,
            },
            '普通型': {
                'alpha_mult': 1.0,
                'threshold_mult': 1.0,
                'recovery_mult': 1.0,
            },
            '敏感型': {
                'alpha_mult': 1.3,  # 情绪敏感度高
                'threshold_mult': 0.8,  # 阈值降低20%（更容易触发事件）
                'recovery_mult': 0.85,
            },
            '焦虑型': {
                'alpha_mult': 1.6,  # 情绪敏感度非常高
                'threshold_mult': 0.6,  # 阈值降低40%
                'recovery_mult': 0.7,
            },
        }
        p_effects = personality_effects.get(self.personality, personality_effects['普通型'])
        # 注：alpha_mult 的乘法累加已废弃（self.alpha 不再存储），
        # 性格对心理压力敏感度的影响由 unified_stress_model 的 personality_alpha 直接处理。
        self.personality_threshold_mult = p_effects['threshold_mult']
        self.personality_recovery_mult = p_effects['recovery_mult']

        # =================================================================
        # 【年龄影响】
        # =================================================================
        # 注：对 self.alpha 的乘法累加已废弃，年龄对情绪敏感度的影响
        # 由 unified_stress_model 通过 tolerance 的 age_adj 间接实现。
        age_threshold_mult = 1.0
        if self.age < 10:
            self.initiative *= 0.6
            age_threshold_mult = 0.7  # 阈值降低
        elif self.age < 18:
            self.initiative *= 0.8
            age_threshold_mult = 0.85
        elif self.age < 30:
            # 青年人相对稳定
            age_threshold_mult = 1.1
        elif self.age > 75:
            self.initiative *= 0.5
            self.response *= 0.7
            age_threshold_mult = 0.65
        elif self.age > 60:
            self.initiative *= 0.7
            self.response *= 0.9
            age_threshold_mult = 0.8

        self.age_threshold_mult = age_threshold_mult

        # =================================================================
        # 【健康状态影响】
        # =================================================================
        health_effects = {
            '健康': {'alpha': 1.0, 'initiative': 1.0, 'response': 1.0, 'threshold': 1.0},
            '亚健康': {'alpha': 1.1, 'initiative': 0.95, 'response': 0.95, 'threshold': 0.95},
            '轻微疾病': {'alpha': 1.2, 'initiative': 0.9, 'response': 0.9, 'threshold': 0.85},
            '严重疾病': {'alpha': 1.5, 'initiative': 0.6, 'response': 0.7, 'threshold': 0.6},
            '残疾': {'alpha': 1.3, 'initiative': 0.5, 'response': 0.6, 'threshold': 0.7},
        }
        h_effects = health_effects.get(self.health_status, health_effects['健康'])
        # 注：h_effects['alpha'] 不再累加到 self.alpha（已废弃），
        # 健康对压力敏感度的影响由 unified_stress_model 通过 tolerance 的 health_adj 实现。
        self.initiative *= h_effects['initiative']
        self.response *= h_effects['response']
        self.health_threshold_mult = h_effects['threshold']

        # =================================================================
        # 【抗压能力影响】- 直接影响阈值
        # =================================================================
        # stress_resistance 范围 [0.3, 1.0]，越高阈值越高
        self.stress_threshold_mult = 0.7 + self.stress_resistance * 0.5  # [0.85, 1.2]

        # =================================================================
        # 【综合阈值乘数】- 由性格×年龄×健康×抗压×随机扰动合成
        # =================================================================
        #
        # 由 _update_event_states 在计算 personal_*_threshold 时读取使用。
        # 例：焦虑型老年病人 combined_threshold_mult ≈ 0.2，
        #     对应 emotion_burst 阈值 0.55×0.2 ≈ 0.11，容易触发。
        # 例：理性型青年健康人 combined_threshold_mult ≈ 1.8，
        #     对应 emotion_burst 阈值 0.55×1.8 ≈ 1.0，极难触发。
        random_factor = random.uniform(0.85, 1.15)  # ±15%随机性
        self.combined_threshold_mult = (
                self.personality_threshold_mult *
                self.age_threshold_mult *
                self.health_threshold_mult *
                self.stress_threshold_mult *
                random_factor
        )

        # 【社交活跃度影响】- 影响聚集/传播相关阈值
        # 社交活跃度高的人更容易参与聚集
        self.gathering_propensity = self.social_activity * random.uniform(0.8, 1.2)

    def _adjust_mobility_by_attributes(self):
        """根据属性调整移动能力"""
        # 年龄影响移动速度
        if self.age < 10:
            self.max_speed *= 0.6
            self.desired_speed *= 0.6
        elif self.age < 18:
            self.max_speed *= 0.9
            self.desired_speed *= 0.9
        elif self.age > 70:
            self.max_speed *= 0.5
            self.desired_speed *= 0.4
        elif self.age > 60:
            self.max_speed *= 0.7
            self.desired_speed *= 0.6

        # 健康状态影响移动能力
        if self.health_status in ['严重疾病', '残疾']:
            self.max_speed *= 0.3
            self.desired_speed *= 0.2
            self.mobility *= 0.3
        elif self.health_status == '轻微疾病':
            self.max_speed *= 0.8
            self.desired_speed *= 0.7

    # =================================================================
    # 【改进3】距离衰减恐慌传播 - 邻居权重相关方法
    # =================================================================

    def precompute_neighbor_weights(self, sigma=None):
        """
        预计算邻居距离权重（基于当前 self.neighbors 列表）。

        调用时机:
            应在 simulation._build_social_network() 完成后调用一次;
            如对比实验需切换 σ,重跑仿真前刷新所有居民权重即可。

        参数:
            sigma: 距离核尺度因子（米）。若 None 则使用
                   ResidentAttributeConfig.DISTANCE_KERNEL_SIGMA

        副作用:
            写入 self._neighbor_distance_weights: list[float]
                  与 self.neighbors 逐项对应的权重
            写入 self._neighbor_weights_sigma: float (记录采用的σ)
        """
        cfg = ResidentAttributeConfig
        if sigma is None:
            sigma = cfg.DISTANCE_KERNEL_SIGMA

        self._neighbor_weights_sigma = sigma

        if not self.neighbors:
            self._neighbor_distance_weights = []
            return

        weights = []
        for n in self.neighbors:
            # 使用经纬度欧氏距离（等距投影近似）
            n_x = getattr(n, 'x', self.x)
            n_y = getattr(n, 'y', self.y)
            L = cfg.geo_distance_meters(self.x, self.y, n_x, n_y)
            w = cfg.distance_kernel(L, sigma)
            weights.append(w)

        self._neighbor_distance_weights = weights

    def compute_weighted_neighbor_stress(self):
        """
        计算距离加权的邻居平均压力 σ̄_weighted（方案D1+E1）。

        公式: σ̄ = Σ(w_k · s_k · stress_k) / Σ(w_k · s_k)
            其中:
                w_k = 距离核权重（sigmoid衰减）
                s_k = SEIR源权重（I:1.0, E:0.3, S/R:0）
                stress_k = 邻居k的 stress_level

        【方案对齐】
            - B1: sigmoid 距离核 w(L) = 1 - 1/(1+exp(-L/σ))
            - C2: SEIR 源权重分级
            - D1: 加权平均归一化（有效源分母）
            - E1: 替换原 σ̄ 的接入位置

        返回:
            float: σ̄_weighted ∈ [0,1]
                   若无有效传染源返回自身 stress_level（维持现状）
        """
        cfg = ResidentAttributeConfig
        source_weights = cfg.SEIR_SOURCE_WEIGHT

        # 惰性计算:若权重缓存不存在,尝试即时计算(但建议外部预先调用 precompute)
        if not hasattr(self, '_neighbor_distance_weights'):
            self.precompute_neighbor_weights()

        if not self.neighbors or not self._neighbor_distance_weights:
            return getattr(self, 'stress_level', 0.0)

        num = 0.0
        den = 0.0
        for n, w_dist in zip(self.neighbors, self._neighbor_distance_weights):
            n_state = getattr(n, 'state', 'S')
            s_src = source_weights.get(n_state, 0.0)
            if s_src <= 0.0 or w_dist <= 0.0:
                continue
            n_stress = getattr(n, 'stress_level', 0.0)
            w_total = w_dist * s_src
            num += w_total * n_stress
            den += w_total

        if den <= 1e-9:
            # 没有有效传染源:返回自身压力等价于"无输入"
            return getattr(self, 'stress_level', 0.0)

        return num / den

    def set_position(self, x, y, zone):
        """设置初始位置"""
        self.x = x
        self.y = y
        self.zone = zone
        self.home_position = (x, y)

    def step(self, dt=1.0, social_force=None, gov_resource=0.0,
             region_panic_level=0.0, hazard_positions=None,
             time_factors=None, sim_time=0.0):  # 新增 sim_time 参数
        self._sim_time = sim_time
        """
        每步更新 - 整合社会力和恐慌机制

        参数:
            dt: 时间步长
            social_force: 来自邻居的社会力 [fx, fy]
            gov_resource: 政府资源
            region_panic_level: 区域恐慌水平
            hazard_positions: 危险源位置列表 [(x,y), ...]
            time_factors: 【新增】时间因子字典（昼夜差异）
                - emotion_sensitivity: 情绪敏感度系数
                - panic_sensitivity: 恐慌敏感度系数
                - gathering_tendency: 聚集倾向系数
        """
        # 【新增】应用时间因子（默认无影响）
        if time_factors is None:
            time_factors = {
                'emotion_sensitivity': 1.0,
                'panic_sensitivity': 1.0,
                'gathering_tendency': 1.0,
            }
        self.current_time_factors = time_factors

        # 1. SEIR状态转换
        self._update_seir_state(dt)

        # 2. 停电状态更新
        if not self.powered:
            self.t_outage += dt
            # 【长尾效应】累计停电时长（用于计算心理创伤）
            self.total_outage_hours += dt
            self.informed = True
            self.safe_time = 0
        else:
            self.safe_time += dt
            if self.safe_time > 5 and len(self.neighbors) > 0:
                if all(getattr(n, 'safe_time', 0) > 3 for n in self.neighbors[:2]):
                    if random.random() < 0.2:
                        self.informed = False
            # t_outage在恢复供电后缓慢衰减（不是瞬间清零）
            if self.t_outage > 0:
                self.t_outage = max(0, self.t_outage - dt * 3)
                if self.t_outage < 1.0:
                    self.t_outage = 0

        # 2.5 个人物资消耗
        # 【核心理念】停电时物资消耗更快（需要用蜡烛、电池、备用食物等）
        if not self.powered:
            consumption = self.supply_consumption_outage * dt
        else:
            consumption = self.supply_consumption_normal * dt

        # 囤积成功会补充物资
        if getattr(self, 'just_hoarded', False) and getattr(self, 'hoarding_success', False):
            self.personal_supply = min(1.0, self.personal_supply + 0.3)  # 补充30%
            self.just_hoarded = False

        self.personal_supply = max(0, self.personal_supply - consumption)

        # ============================================================
        # 3 & 4. 更新心理状态（统一压力模型）
        # ============================================================
        # 【核心公式】基于Lazarus应激-评估-应对理论
        # dσ/dt = α·T·(1-σ) - β·C·σ + γ·(σ̄-σ) + Σ(事件影响)
        #
        # 其中：
        # - T: 威胁感知 = f(停电时长, 物资短缺, 邻居恐慌, 信息缺失, 健康脆弱性)
        # - C: 应对资源 = f(政府支持, 个人韧性, 社会支持, 信息获取, 物资储备)
        # - σ̄: 邻居平均压力（社会传染）
        #
        zone_data = {
            'spread_index': getattr(self, 'zone_spread_index', 0.5),
            'vulnerability_index': getattr(self, 'zone_vulnerability_index', 0.5),
            'supply_level': getattr(self, 'zone_supply_level', 1.0),
        }

        # 【从gov_resource推断政府事件状态】
        if not hasattr(self, '_gov_events'):
            self._gov_events = {}
        # 注：_grid_events（如 temp_station / accelerated_repair）应由外部 simulation
        # 根据 PowerGridAgent 的真实状态写入；本处仅初始化占位字典。
        # TODO: 当前 _gov_events 仍用 gov_resource 阈值启发式推断，理想情况下应由
        # simulation 直接传递 GovernmentAgent 的真实事件标志（与 _gov_resource_received
        # / _opinion_management_active 的传递方式一致）。
        if not hasattr(self, '_grid_events'):
            self._grid_events = {}

        # 根据gov_resource推断政府事件（gov_resource 数值越高说明政府支持越多）
        self._gov_events['outage_notice'] = gov_resource > 0.3 and not self.powered
        self._gov_events['emergency_response'] = gov_resource > 0.8 and not self.powered
        self._gov_events['supply_distribution'] = gov_resource > 1.2 and not self.powered
        self._gov_events['psychological_comfort'] = gov_resource > 1.5 and not self.powered
        # 疏散安置：需要更高的资源投入门槛（重大举措）
        self._gov_events['evacuation'] = gov_resource > 2.0 and not self.powered

        # ============================================================
        # 【改进3】距离加权的邻居压力 σ̄_weighted
        # ============================================================
        # 在调用 unified_stress_model 前计算,结果挂在 self 上供其读取
        # unified_stress_model 端应优先使用 self.sigma_bar_weighted
        # (若该属性存在),fallback 到原 sum(neighbors)/len 简单平均
        #
        # 数据流:
        #   self.neighbors (固定社交圈,3-5人)
        #   → 结合距离核 w(L) 和 SEIR 源权重 s_k
        #   → σ̄_weighted ∈ [0,1]
        #   → 传入 unified_stress_model 的 γ·(σ̄-σ) 社会传染项
        self.sigma_bar_weighted = self.compute_weighted_neighbor_stress()

        if unified_stress_model is None:
            raise RuntimeError(
                "unified_stress_model 未导入成功，但当前心理模型依赖它；"
                "请检查 unified_stress_model.py 的导入路径（agent 顶部 27–45 行）。")
        components = unified_stress_model.update_resident_stress(
            self, gov_resource, zone_data, dt
        )

        # 调用统一模型更新 stress_level 及 peak_stress
        components = unified_stress_model.update_resident_stress(
            self, gov_resource, zone_data, dt
        )
        self._stress_components = components

        # 从 stress_level 派生 panic_value 和 emotion
        # - panic_value: 恐慌是压力的急性显性表达，低压力时相对放大
        # - emotion: 【改进2】经Pe/Pc双因子包络调制的情绪状态
        stress = self.stress_level

        # panic_value: 凹函数 x^0.8
        #   stress=0.1 → panic=0.16（低压力时恐慌感明显）
        #   stress=0.5 → panic=0.57
        #   stress=1.0 → panic=1.00（高压力时两者趋同）
        self.panic_value = stress ** 0.8

        # ============================================================
        # 【改进2】情绪激发-平复双因子模型 (Paper 1, Eq.7-10)
        # ============================================================
        #
        # 核心思想：stress_level 是内在心理压力（由ODE驱动），
        # emotion 是外显情绪表达，二者通过 P(t) 包络函数关联：
        #
        #   Pe(t) = 1/(1+exp(-α1·(t-te)))   激发S形曲线（0→1上升）
        #   Pc(t) = 1/(1+exp( α2·(t-tc-te)))  平复S形曲线（1→0下降）
        #   P(t)  = min(Pe, Pc)              山丘形包络
        #   emotion ≈ stress × 0.9 × P(t)
        #
        # 效果：即使 stress 持续高位，emotion 也会经历
        # "缓慢上升 → 维持高峰 → 逐渐适应下降"的心理学动态曲线。
        # α1/α2/tc/te 均由OCEAN五因素决定，实现个体差异化。
        #

        # 1) 更新情绪反应累计时间
        #    - 正在反应中（停电且超过耐受）或恢复期：时间推进
        #    - 完全恢复后：缓慢归零，为下次事件做准备
        internal_stress = getattr(self, '_internal_stress', 0.0)
        tolerance = getattr(self, '_tolerance', 0.3)
        is_reacting = internal_stress > tolerance
        is_recovering = getattr(self, 'recovery_phase', False)

        if is_reacting or is_recovering:
            self.emotion_reaction_time += dt
        elif self.emotion_reaction_time > 0 and stress < 0.05:
            # 完全平静后，反应时间缓慢归零（下次事件可重新计时）
            self.emotion_reaction_time = max(0.0, self.emotion_reaction_time - dt * 0.5)

        # 2) 计算 Pe/Pc 包络
        t = self.emotion_reaction_time
        te = self.te_emotion
        tc = self.tc_emotion

        # Pe: 激发曲线 0→1。t < te 时 Pe≈0.5以下；t >> te 时 Pe→1
        pe_exp = -self.alpha1_emotion * (t - te)
        Pe = 1.0 / (1.0 + np.exp(np.clip(pe_exp, -50, 50)))

        # Pc: 平复曲线 1→0。t < tc+te 时 Pc≈1；t >> tc+te 时 Pc→0
        pc_exp = self.alpha2_emotion * (t - tc - te)
        Pc = 1.0 / (1.0 + np.exp(np.clip(pc_exp, -50, 50)))

        P_envelope = min(Pe, Pc)

        # 3) emotion = stress × P(t)，严格按论文 Eq.10 E(t)=En·P(t)
        # 【改进】去除原有的 0.9 衰减系数和一阶平滑滤波，严格对齐论文公式。
        # Pe/Pc 本身是 sigmoid 函数，已自带平滑性；
        # stress 由 unified_stress_model 的 ODE 更新，本身也是连续变化，
        # 因此无需额外滤波即可保证 emotion 无抖动。
        self.emotion = stress * P_envelope
        self.emotion = np.clip(self.emotion, 0, 1)

        # 注：pts_status 已由 unified_stress_model._update_behavior_states（经由
        # update_resident_stress 调用）根据性格调整后的阈值设置，此处不再覆盖，
        # 避免抹掉性格差异化。

        # 5. 更新位置（小范围移动）
        if social_force is not None:
            self._update_position(dt, social_force)

        # 6. 【新增】更新信息传播状态
        self._update_information_spread(dt, gov_resource)

        # ============ 更新事件触发状态 ============
        self._update_event_states(dt, gov_resource, region_panic_level)

    def _update_event_states(self, dt, gov_resource, region_panic_level):
        """
        更新居民的事件触发状态

        【核心机制】阈值已根据个体属性（性格、年龄、健康、抗压能力）计算
        不同居民的阈值不同 → 事件触发时间不同 → 形成扩散效果

        【阈值示例】
        - 焦虑型+高龄+疾病：阈值可能低至0.15（很容易触发）
        - 理性型+青年+健康：阈值可能高达0.6（不容易触发）
        """
        # 注：启动延迟已由 unified_stress_model 的 tolerance 机制接管，
        # 不再需要 reaction_start_delay / start_delay。
        # has_started_reacting 改为直接读取 internal_stress > tolerance 判定（见下方）。

        # ============ 【修复】长尾效应：恢复期状态管理 ============
        #
        # 问题：原代码 has_started_reacting = not self.powered and self.t_outage >= start_delay
        #       一旦恢复供电，所有事件状态立即结束，不符合现实
        #
        # 修复：引入"恢复期"概念
        # - 停电期间：正常记录负面状态
        # - 恢复供电后：进入"恢复期"，负面状态基于情绪/恐慌值逐渐消退
        # - 恢复期时长：取决于停电时长、峰值情绪、抗压能力等

        # 检测供电状态变化
        if self.prev_powered_state and not self.powered:
            # 从有电变停电：开始记录影响
            self.was_affected = True
            self.recovery_phase = False
            self.time_since_recovery = 0.0
            self.max_emotion_during_outage = 0.0  # 重置最高情绪记录
            # 【改进2】重置情绪反应计时器（新一轮Pe/Pc曲线）
            self.emotion_reaction_time = 0.0
        elif not self.prev_powered_state and self.powered:
            # 从停电变有电：进入恢复期
            self.recovery_phase = True
            self.time_since_recovery = 0.0
            # 记录停电期间的最高情绪
            self.max_emotion_during_outage = max(self.max_emotion_during_outage, self.emotion)
        elif not self.powered:
            # 持续停电中：更新最高情绪记录
            self.max_emotion_during_outage = max(self.max_emotion_during_outage, self.emotion)

        self.prev_powered_state = self.powered

        # 恢复期时间累加
        if self.recovery_phase:
            self.time_since_recovery += dt

            # 【退出条件】以时间为主：
            #   - 快速退出: stress < 0.1 且 time_since_recovery > 2h（应激已消退）
            #   - 兜底退出: time_since_recovery > 12h（无论 stress 多少，12h 足够恢复）
            #
            # 为什么不能只用 stress<0.1：info_threat 的"信息缺失"贡献 ~0.075
            # 让 stress 的平衡点在 ~0.19，永远跌不到 0.1（死锁）。
            # 12h 兜底保证 recovery_phase 必然退出。
            stress_recovered = self.stress_level < 0.1 and self.time_since_recovery > 2.0
            time_recovered = self.time_since_recovery > 12.0

            if stress_recovered or time_recovered:
                self.recovery_phase = False
                self.was_affected = False
                self.total_outage_hours = 0.0
                # 注意：此处不重置 emotion_reaction_time。
                # 让 Pc 继续保持 P(t) ≈ 0，避免 P(0) ≈ 0.4 导致虚假情绪反弹。
                # emotion_reaction_time 仅在新一轮停电开始时重置（见上方 prev_powered 检测）。
                # 正常状态下 stress < 0.05 时，ert 会在 step() 中缓慢自然归零。

        # 【核心修复】has_started_reacting 逻辑
        #
        # "开始反应" = 内部压力超过个人耐受阈值
        # 不同属性的人耐受不同，所以开始反应的时间不同
        # 这才是"延迟"效果的真正体现
        #
        # 【数据来源】self._internal_stress 和 self._tolerance 由
        # unified_stress_model.calculate_stress_change 在本步更早处写入。
        # 这里直接读取即可，不再重复计算（避免两份 tolerance 表不一致）。
        #
        internal_stress = getattr(self, '_internal_stress', 0.0)
        tolerance = getattr(self, '_tolerance', 0.3)

        # 【判断是否开始反应】内部压力超过耐受阈值
        # 注: _internal_stress 在有电时为 0（由 unified_stress_model 保证），
        # 所以这里不需要再显式检查 not self.powered
        is_actively_affected = internal_stress > tolerance

        # 恢复期判断：情绪或恐慌仍较高时，继续维持反应状态
        recovery_threshold_emotion = 0.20
        recovery_threshold_panic = 0.15

        is_in_recovery_phase = (
                self.recovery_phase and
                (self.emotion > recovery_threshold_emotion or self.panic_value > recovery_threshold_panic)
        )

        # 【综合判断】
        has_started_reacting = is_actively_affected or is_in_recovery_phase

        # ============ 事件14: 居民囤积物资 ============
        #
        # 【现实分析】囤积行为的触发条件：
        # 1. 不是简单的"停电>2h就囤积"，现实中通知停电一天也常见，不会囤积
        # 2. 囤积需要"危机感"：感觉事态严重、可能长期、物资可能短缺
        # 3. 触发因素：
        #    - 信息源：听说大面积停电、听说物资紧张、看到别人抢购
        #    - 个人状态：物资确实不足、有依赖电器的需求（冰箱食物等）
        #    - 恐慌传染：区域恐慌水平高、邻居在囤积
        #
        # 【触发条件优化】
        # - 必须是"意识到危机"后才会囤积（has_started_reacting）
        # - 需要"多重信号"才会触发，而非单一条件

        personal_supply = getattr(self, 'personal_supply', 1.0)
        supply_warning = getattr(self, 'supply_warning_threshold', 0.4)
        supply_critical = getattr(self, 'supply_critical_threshold', 0.2)
        last_hoard_time = getattr(self, 'last_hoarding_time', -999)
        current_time = getattr(self, '_sim_time', 0.0)  # 使用 sim_time 代替 t_outage 防止第二次停电时，囤积冷却时间被锁

        # 囤积间隔（至少间隔几小时再囤积）
        min_hoard_interval = 6.0  # 提高到6小时间隔
        time_since_last_hoard = current_time - last_hoard_time
        can_go_hoard = time_since_last_hoard > min_hoard_interval

        # 【信号1】物资状况
        supply_low = personal_supply < supply_warning
        supply_very_low = personal_supply < supply_critical

        # 【信号2】感知到的危机程度（多因素综合）
        perceived_crisis = 0.0

        # 2.1 停电持续时间
        if self.t_outage > 24:  # 超过24小时
            perceived_crisis += 0.4
        elif self.t_outage > 12:  # 超过12小时
            perceived_crisis += 0.25
        elif self.t_outage > 6:  # 超过6小时
            perceived_crisis += 0.15
        elif self.t_outage > 3:  # 超过3小时
            perceived_crisis += 0.08

        # 2.2 区域恐慌水平
        perceived_crisis += region_panic_level * 0.3

        # 2.3 个人恐慌/PTS状态
        if self.pts_status:
            perceived_crisis += 0.35
        else:
            perceived_crisis += self.panic_value * 0.25

        # 2.4 【从众心理核心】看到邻居在囤积
        # 从众效应是非线性的：越多人囤积，跟风概率越高
        herd_effect = 0.0
        if self.neighbors:
            hoarding_neighbors = sum(1 for n in self.neighbors if getattr(n, 'is_hoarding', False))
            total_neighbors = len(self.neighbors)

            if hoarding_neighbors > 0 and total_neighbors > 0:
                # 从众比例：邻居中有多少比例在囤积
                herd_ratio = hoarding_neighbors / total_neighbors

                # 从众效应强度：随比例指数增长
                # 10%邻居囤积 → 效应0.1
                # 30%邻居囤积 → 效应0.35
                # 50%邻居囤积 → 效应0.6
                herd_effect = herd_ratio * (1 + herd_ratio)  # 非线性增长

                # 性格影响从众敏感度
                herd_sensitivity = {
                    '焦虑型': 1.5,  # 很容易跟风
                    '敏感型': 1.3,
                    '普通型': 1.0,
                    '稳定型': 0.7,
                    '理性型': 0.4,  # 不容易跟风
                }.get(self.personality, 1.0)

                herd_effect *= herd_sensitivity
                herd_effect = min(0.6, herd_effect)  # 最高加成0.6

        perceived_crisis += herd_effect

        # 【信号3】性格影响危机感知阈值
        crisis_threshold = {
            '焦虑型': 0.25,  # 容易感到危机
            '敏感型': 0.35,
            '普通型': 0.45,
            '稳定型': 0.55,
            '理性型': 0.65,  # 需要较强的信号才会囤积
        }.get(self.personality, 0.45)

        # 【恐慌驱动囤积】高恐慌的焦虑型即使物资够也会因害怕而囤积
        # 这是启动从众效应的"种子"
        panic_driven_hoarding = (
                self.panic_value > 0.5 and
                self.personality in ['焦虑型', '敏感型'] and
                can_go_hoard and
                random.random() < self.panic_value * 0.3  # 恐慌越高，概率越大
        )

        # 【综合判断】是否触发囤积
        # 条件：必须正在反应中 + (物资很低 OR (物资较低+危机感够强+有间隔) OR 恐慌驱动 OR 从众跟风)
        wants_to_hoard = (
                has_started_reacting and (
                supply_very_low or  # 紧急：物资很低（<20%）必须去
                (supply_low and perceived_crisis > crisis_threshold and can_go_hoard) or
                panic_driven_hoarding or  # 【新增】恐慌驱动（启动从众的种子）
                # 【从众心理】即使物资还行，但从众效应很强时也会跟风囤积
                (herd_effect > 0.3 and perceived_crisis > crisis_threshold * 0.8 and can_go_hoard)
        )
        )

        # 【物资抢购系统】- 去商店买东西
        zone_supply = getattr(self, 'zone_supply_level', 1.0)

        if wants_to_hoard:
            self.hoarding_attempts += 1
            self.last_hoarding_time = current_time

            # 抢购成功率取决于区域物资水平
            if zone_supply > 0.5:
                success_rate = 0.95
            elif zone_supply > 0.3:
                success_rate = 0.6 + zone_supply * 0.5
            elif zone_supply > 0.1:
                success_rate = zone_supply * 2
            else:
                success_rate = zone_supply * 0.5  # 几乎买不到

            # 【个体差异】行动力强的人更容易抢到
            success_rate *= (0.8 + self.initiative * 0.4)
            success_rate = min(1.0, success_rate)

            self.hoarding_success = random.random() < success_rate

            if self.hoarding_success:
                # 囤积成功：标记，下一步会补充物资
                self.just_hoarded = True
            else:
                self.hoarding_failures += 1
                self.just_hoarded = False
        else:
            self.hoarding_success = True
            self.just_hoarded = False

        self.is_hoarding = wants_to_hoard

        # ============ 事件15: 居民聚集与信息传播 ============
        #
        # 【聚集行为与移动系统配合】
        # 1. 聚集需要物理上的接近（基于移动后的位置）
        # 2. 聚集会形成局部热点，加速情绪传播
        # 3. 聚集人数影响传播强度
        #
        # 【触发条件】
        # - 已开始反应
        # - 社交活跃度足够高 或 SEIR传播状态
        # - 附近有其他人（基于移动后的物理距离）

        gathering_active = False
        self.gathering_density = 0.0  # 聚集密度，用于计算传播强度

        if has_started_reacting:
            # 【修复】计算附近人数：社交邻居 + 物理距离近的邻居
            # 原问题：仅基于物理距离（<30米），但社交邻居分布在整个区域，导致nearby_count始终为0
            nearby_count = 0
            nearby_gathering = 0
            gathering_distance_threshold = 0.002  # 扩大到约200米（经纬度）

            if self.neighbors:
                for n in self.neighbors:
                    # 【修复】社交邻居本身就算"附近的人"（社交意义上的聚集）
                    # 同时也考虑物理距离（物理意义上的聚集）
                    n_x = getattr(n, 'x', 0)
                    n_y = getattr(n, 'y', 0)
                    distance = np.sqrt((self.x - n_x) ** 2 + (self.y - n_y) ** 2)

                    # 条件1：物理距离近（<200米）
                    # 条件2：同一区域的社交邻居（无论距离）
                    # 条件3：I/E状态的邻居主动传播（无论距离）
                    is_nearby = (
                            distance < gathering_distance_threshold or  # 物理距离近
                            getattr(n, 'zone', None) == self.zone or  # 同区域
                            getattr(n, 'state', 'S') in ['I', 'E']  # 传播状态
                    )

                    if is_nearby:
                        nearby_count += 1
                        if getattr(n, 'is_gathering', False):
                            nearby_gathering += 1

            # 【聚集倾向计算】
            # 因素1：SEIR状态（I/E状态更容易聚集传播）
            seir_gathering_boost = 0.3 if self.state in ['I', 'E'] else 0

            # 因素2：社交活跃度
            social_boost = self.social_activity * 0.4

            # 因素3：附近已有人聚集（从众效应）
            crowd_boost = min(0.4, nearby_gathering * 0.15)

            # 因素4：恐慌会促进聚集（想获取信息、寻求安慰）
            panic_boost = self.panic_value * 0.25

            # 因素5：停电时间越长，越容易聚集讨论
            # 【修复】恢复期也会讨论"刚发生的事"，但强度降低
            if not self.powered:
                outage_boost = min(0.2, self.t_outage * 0.02)
            elif self.recovery_phase:
                # 恢复期：讨论强度随时间衰减
                recovery_decay = max(0, 1 - self.time_since_recovery / 24)  # 24小时内逐渐衰减
                outage_boost = min(0.15, self.total_outage_hours * 0.01) * recovery_decay
            else:
                outage_boost = 0

            # 综合聚集倾向
            gathering_tendency = seir_gathering_boost + social_boost + crowd_boost + panic_boost + outage_boost

            # 【新增】应用昼夜时间因子
            # 夜间聚集倾向降低（深夜大家都在家），傍晚最高
            time_gathering_factor = getattr(self, 'current_time_factors', {}).get('gathering_tendency', 1.0)
            gathering_tendency *= time_gathering_factor

            # 【政府干预抑制聚集】
            # 政府分配资源给居民 → 居民有事做（领物资、安排生活），减少聚集
            # 舆论管控 → 信息渠道被管控，减少聚集讨论的动机
            # 取消资源/管控后 → 聚集行为恢复
            gov_resource_active = getattr(self, '_gov_resource_received', False)
            opinion_management_active = getattr(self, '_opinion_management_active', False)

            gov_suppression = 0.0
            if gov_resource_active:
                # 政府资源分配：抑制40%的聚集倾向
                gov_suppression += 0.40
            if opinion_management_active:
                # 舆论管控：抑制30%的聚集倾向（人们不敢公开讨论）
                gov_suppression += 0.30

            # 应用抑制效果
            if gov_suppression > 0:
                gathering_tendency *= (1 - min(0.60, gov_suppression))  # 最多抑制60%

            # 【触发判断】
            # 需要有邻居 且 倾向足够高
            if nearby_count >= 1 and gathering_tendency > 0.35:
                gathering_active = random.random() < gathering_tendency
            # 【新增】高社交活跃度的人即使邻居不多也可能主动发起聚集
            elif self.social_activity > 0.7 and gathering_tendency > 0.5:
                gathering_active = random.random() < gathering_tendency * 0.5

            # 【记录聚集密度】用于情绪传播计算
            if gathering_active:
                self.gathering_density = min(1.0, (nearby_count + 1) * 0.15)
                self.gathering_count += 1

        self.is_gathering = gathering_active

        # ============ 事件16/17/18: 三种应对方式 ============
        #
        # 【核心修复】各状态独立判断，直接基于emotion/panic_value
        # 不再依赖统一的has_started_reacting前提条件
        # 这样停电结束后，只要emotion/panic_value仍然高，状态就会保持
        #
        # 1. 情绪爆发（事件17）：emotion高 或 PTS状态
        # 2. 请求供电（事件16）：emotion中等 + 非PTS + (停电中或恢复期)
        # 3. 自救互助（事件18）：emotion稳定 + 有能力 + 曾受影响

        # ============ 判断当前状态 ============
        current_emotion = self.emotion
        is_pts = self.pts_status  # PTS状态（恐慌值>0.7）

        # 个体化阈值（基于性格×年龄×健康×抗压×随机的综合乘数）
        # combined_threshold_mult 范围大约 [0.2, 1.8]：
        # - 敏感群体（焦虑型/老年/病人/低抗压）: mult 小 → 阈值低 → 易触发
        # - 抗压群体（理性型/青年/健康/高抗压）: mult 大 → 阈值高 → 难触发
        cmul = getattr(self, 'combined_threshold_mult', 1.0)
        personal_burst_threshold = 0.55 * cmul  # 基础 0.55
        personal_request_threshold = 0.30 * cmul  # 基础 0.30
        personal_help_threshold = 0.50 * cmul  # 基础 0.50

        # 是否曾受停电影响（用于判断是否参与相关事件）
        was_ever_affected = self.was_affected or not self.powered or self.total_outage_hours > 0

        # ============ 事件17: 居民情绪爆发 ============
        # 【独立判断】只要emotion够高就可以爆发，不管是否正在停电
        # 情绪是逐渐衰减的，所以停电结束后如果emotion仍高，仍然会爆发
        self.is_emotion_burst = (
                was_ever_affected and  # 必须曾受影响（正常情况下不会无故爆发）
                (is_pts or current_emotion > personal_burst_threshold)
        )

        # ============ 事件16: 恢复供电请求 ============
        # 【独立判断】emotion中等以上 + 非PTS + (正在停电 或 恢复期仍有余波)
        # 恢复期的请求内容可能是"担心再停电"而非"快恢复"
        is_anxious_enough = current_emotion > personal_request_threshold

        # 请求条件：停电中，或恢复期但情绪仍较高
        if not self.powered:
            # 停电中：正常请求
            request_condition = is_anxious_enough and not is_pts
        elif self.recovery_phase and current_emotion > personal_request_threshold + 0.1:
            # 恢复期：情绪需要更高才会继续请求（表达担忧）
            request_condition = not is_pts
        else:
            request_condition = False

        self.is_requesting_power = was_ever_affected and request_condition

        # ============ 事件18: 邻居互救 ============
        #
        # 【核心设计】邻居之间相互帮助
        #
        # 互救触发条件：
        # 1. 经历过较长时间停电（>12小时，学会了应对）
        # 2. 自己情绪相对稳定（是周围人中情绪较低的）
        # 3. 邻居中有高情绪的人需要帮助
        # 4. 性格适合帮助他人
        #
        # 互救效果：
        # 1. 帮助者：轻微降低自己情绪（获得掌控感）
        # 2. 被帮助者：情绪降低
        #

        # 条件1：停电足够长（学会了适应）
        min_outage = 12.0  # 停电超过12小时
        has_experience = self.total_outage_hours >= min_outage or self.t_outage >= min_outage

        # 条件2：自己情绪相对较低（在邻居中属于稳定的）
        if self.neighbors:
            neighbor_emotions = [getattr(n, 'emotion', 0.5) for n in self.neighbors]
            avg_neighbor_emotion = sum(neighbor_emotions) / len(neighbor_emotions)
            # 比周围平均情绪低20%以上，才算"相对稳定"
            is_relatively_stable = self.emotion < avg_neighbor_emotion - 0.1 and self.emotion < 0.65

            # 条件3：有高情绪邻居需要帮助
            high_emotion_neighbors = [n for n in self.neighbors if getattr(n, 'emotion', 0) > self.emotion + 0.15]
            has_neighbors_to_help = len(high_emotion_neighbors) >= 1
        else:
            is_relatively_stable = self.emotion < 0.45
            has_neighbors_to_help = False

        # 条件4：性格适合互救（放宽概率）
        personality_help_prob = {
            '理性型': 0.70,  # 理性型最可能帮助
            '稳定型': 0.55,
            '普通型': 0.30,  # 普通型也有机会
            '敏感型': 0.15,  # 敏感型较少
            '焦虑型': 0.05,  # 焦虑型基本不会
        }.get(self.personality, 0.25)

        # 条件5：基本能力（放宽阈值）
        has_capability = self.initiative > 0.35 and self.stress_resistance > 0.35

        # 条件6：不在严重恐慌状态
        not_panicking = not is_pts and self.panic_value < 0.50  # 放宽到0.5

        # 综合概率
        base_prob = personality_help_prob * (0.5 + 0.5 * self.initiative)

        # 互救判断
        self.is_mutual_helping = False  # 新增：邻居互救标记
        if has_experience and is_relatively_stable and has_neighbors_to_help and has_capability and not_panicking:
            if random.random() < base_prob:
                self.is_mutual_helping = True
                self.mutual_help_duration = getattr(self, 'mutual_help_duration', 0) + dt
        else:
            self.mutual_help_duration = 0

        # 兼容旧接口：is_self_helping = is_mutual_helping
        self.is_self_helping = self.is_mutual_helping

    def _update_information_spread(self, dt, gov_resource):
        """
        【新增】信息传播更新 - 官方信息 vs 谣言竞争

        【设计理念】
        1. 停电时信息需求增加，人们更主动寻找信息
        2. 谣言传播速度比官方信息快50%（社交媒体效应）
        3. 官方信息可信度高，能抑制谣言
        4. 信息影响情绪和恐慌

        【谣言类型】
        - "听说要停好几天"
        - "物资要涨价了"
        - "其他地方发生了XX"
        """
        # ============ 1. 政府信息接收 ============
        # 政府资源分配时会发布官方信息
        # 【公式关联】官方信息 → 抑制谣言 → 减少恐慌增量 → 间接影响情绪
        if gov_resource > 0.1:
            # 官方信息传播速度 = k × 政府资源投入
            # 公式: info_official += k_spread × gov_resource × dt
            official_spread_rate = 0.08 * gov_resource  # 传播系数
            self.info_received['official'] = min(1.0,
                                                 self.info_received['official'] + official_spread_rate * dt)

            # 【公式关联】官方信息抑制谣言相信程度
            # 公式: rumor_belief -= k_suppress × official_info × rumor_belief × dt
            # 官方信息越多、当前谣言相信度越高，抑制效果越明显
            k_suppress = 0.15
            rumor_suppression = k_suppress * self.info_received['official'] * self.rumor_belief * dt
            self.rumor_belief = max(0, self.rumor_belief - rumor_suppression)

        # ============ 2. 谣言传播（邻居传播）============
        if self.neighbors and not self.powered:
            # 停电时更容易听到谣言
            rumor_spreading_neighbors = [n for n in self.neighbors
                                         if getattr(n, 'is_spreading_rumor', False)]

            if rumor_spreading_neighbors:
                # 谣言传播速度 = 基础速度 × 社交媒体使用 × 易感性 × 传播者数量
                rumor_spread_rate = (0.08 * self.social_media_usage *
                                     self.rumor_susceptibility *
                                     min(len(rumor_spreading_neighbors), 3))

                # 夜间谣言传播更快（焦虑增加）
                time_factor = getattr(self, 'current_time_factors', {}).get('panic_sensitivity', 1.0)
                rumor_spread_rate *= time_factor

                self.info_received['rumor'] = min(1.0,
                                                  self.info_received['rumor'] + rumor_spread_rate * dt)

        # ============ 3. 谣言相信程度更新 ============
        # 谣言相信程度 = f(谣言信息量, 官方信息量, 个人易感性)
        rumor_info = self.info_received['rumor']
        official_info = self.info_received['official']

        # 官方信息多时，谣言可信度下降
        if official_info > rumor_info:
            belief_delta = -0.02 * (official_info - rumor_info)
        else:
            # 谣言多时，相信程度上升（取决于易感性）
            belief_delta = 0.015 * (rumor_info - official_info) * self.rumor_susceptibility

        # 高情绪时更容易相信谣言
        if self.emotion > 0.5:
            belief_delta += 0.01 * (self.emotion - 0.5) * self.rumor_susceptibility

        self.rumor_belief = np.clip(self.rumor_belief + belief_delta * dt, 0, 1)

        # ============ 4. 是否传播谣言 ============
        # 条件：相信谣言 + 高情绪/恐慌 + I状态（传播者）
        self.is_spreading_rumor = (
                self.rumor_belief > 0.4 and  # 相信谣言
                (self.emotion > 0.4 or self.panic_value > 0.3) and  # 有情绪
                (self.state == 'I' or random.random() < 0.1)  # I状态或10%概率
        )

        # ============ 5. 信息对压力的影响（已移除直接修改）============
        # 注：原先此处会基于 rumor_belief / official_info 直接 ±self.stress_level，
        # 但这些信号已在 unified_stress_model 的威胁感知 T（information_gap）和
        # 应对资源 C（information_access）通道中被完整建模。
        # 此处再次直接修改 stress_level 会造成同一信号被重复加权，
        # 也是导致"信息缺失死锁"（stress 平衡点 ~0.19 跌不到 0.1）的根源之一。
        # 现已统一到 T/C 通道，此段不再执行。

        # ============ 6. 信息衰减 ============
        # 信息随时间衰减（人们忘记）
        # 【修复】政府资源停止后，官方信息衰减加速（人们觉得"政府不管了"）
        if gov_resource > 0.1:
            decay_rate = 0.005 * dt  # 正常衰减
        else:
            decay_rate = 0.025 * dt  # 资源停止后加速衰减5倍
        self.info_received['official'] = max(0, self.info_received['official'] - decay_rate)
        self.info_received['rumor'] = max(0, self.info_received['rumor'] - decay_rate * 0.7)  # 谣言衰减慢

        # 整体可信度 = 官方信息占比
        total_info = self.info_received['official'] + self.info_received['rumor'] + 0.01
        self.info_credibility = self.info_received['official'] / total_info

    def _update_seir_state(self, dt):
        """
        SEIR状态转换 - 【改进3】基于 T1/T2 双阈值的心理学驱动版本

        【论文映射】Ren et al. 2023, Section 2.2.1
        - dose < T1           → S (anxious, 易感)
        - T1 ≤ dose < T2      → E (panic, 不传播)
        - dose ≥ T2           → I (expressive, 传播恐慌)
        此处 dose ≡ self.stress_level（方案 A1：直接用瞬时压力值）

        【转换逻辑】
        升级（立即触发）:
        - S → E: stress ≥ T1
        - E → I: stress ≥ T2

        降级（带滞后，防止阈值附近抖动）:
        - I → E: stress < T2 累计持续 SEIR_DEGRADE_I_TO_E_HOURS 小时
        - E → S: stress < T1 累计持续 SEIR_DEGRADE_E_TO_S_HOURS 小时

        保留原有逻辑:
        - I → R: 在 I 状态持续 24-48 小时后"适应恢复"（形成心理免疫）
        - R → E: R 状态的人在高压新事件中可重新激活
        """
        stress = self.stress_level

        # ============ 升级（即时触发）============
        # S → E: stress 跨越 T1 阈值
        if self.state == 'S' and stress >= self.T1:
            self.state = 'E'
            self.incubation = 0
            # 清零降级计数器（新一轮事件开始）
            self._below_T2_hours = 0.0
            self._below_T1_hours = 0.0

        # E → I: stress 跨越 T2 阈值
        elif self.state == 'E' and stress >= self.T2:
            self.state = 'I'
            self.recovery_time = 0
            self._below_T2_hours = 0.0

        # ============ 降级（带滞后）============
        # I → E: stress 跌破 T2 持续 SEIR_DEGRADE_I_TO_E_HOURS 小时
        elif self.state == 'I':
            if stress < self.T2:
                self._below_T2_hours += dt
                # ★ 滞后时间可调 ★ 修改 self.SEIR_DEGRADE_I_TO_E_HOURS（默认 2.0h）
                if self._below_T2_hours >= self.SEIR_DEGRADE_I_TO_E_HOURS:
                    self.state = 'E'
                    self._below_T2_hours = 0.0
                    self.recovery_time = 0
            else:
                # stress 重新回到 T2 以上，重置滞后计数
                self._below_T2_hours = 0.0

            # I → R: 在 I 状态持续累计 24-48h 后形成"心理免疫"
            # 这是我们在论文 S/E/I 基础上扩展的 R 状态，表示"适应并恢复"
            self.recovery_time += dt
            if self.recovery_time >= 24 and self.emotion < 0.4:
                self.state = 'R'
                self.recovery_time = 0
                self._below_T2_hours = 0.0
            elif self.recovery_time >= 48:
                self.state = 'R'
                self.recovery_time = 0
                self._below_T2_hours = 0.0

        # E → S: stress 跌破 T1 持续 SEIR_DEGRADE_E_TO_S_HOURS 小时
        if self.state == 'E':
            if stress < self.T1:
                self._below_T1_hours += dt
                # ★ 滞后时间可调 ★ 修改 self.SEIR_DEGRADE_E_TO_S_HOURS（默认 1.0h）
                if self._below_T1_hours >= self.SEIR_DEGRADE_E_TO_S_HOURS:
                    self.state = 'S'
                    self._below_T1_hours = 0.0
                    self.incubation = 0
            else:
                self._below_T1_hours = 0.0

        # ============ R → E: 高压事件下重新激活 ============
        # 保留原有机制：即使已"适应"，在新的强刺激下仍可能再次进入恐慌
        elif self.state == 'R':
            # 使用 T1 作为重激活阈值（一致性：进入恐慌统一用 T1）
            if stress >= self.T1 and not self.powered:
                reactivation_prob = 0.01 + self.panic_value * 0.02
                if random.random() < reactivation_prob:
                    self.state = 'E'
                    self.incubation = 0
                    self._below_T1_hours = 0.0
                    self._below_T2_hours = 0.0

    def _update_position(self, dt, social_force):
        """
        更新位置 - 基于社会力模型的小范围移动

        【新增】记录移动量，用于计算行为对情绪的影响
        """
        if social_force is None:
            self.recent_movement = 0.0
            return

        # 保存上一步位置
        old_x, old_y = self.x, self.y

        # 驱动力：倾向于回到家的位置（如果有）
        driving_force = np.array([0.0, 0.0])
        if self.home_position:
            direction = np.array([self.home_position[0] - self.x,
                                  self.home_position[1] - self.y])
            dist = np.linalg.norm(direction)
            if dist > 0.0001:  # 如果离家较远
                direction = direction / dist
                driving_force = self.mass * (self.desired_speed * direction - self.velocity) / 0.5

        # 恐慌状态下增加随机移动
        random_force = np.array([0.0, 0.0])
        if self.pts_status:
            random_force = np.random.randn(2) * 0.00001 * self.panic_value

        # 【新增】情绪高时增加逃离倾向
        escape_force = np.array([0.0, 0.0])
        if self.emotion > 0.6 and self.panic_value > 0.5:
            # 高情绪+高恐慌：可能产生逃离冲动
            escape_direction = np.random.randn(2)
            escape_direction = escape_direction / (np.linalg.norm(escape_direction) + 0.001)
            escape_force = escape_direction * self.emotion * 0.00002

        # 总力 = 驱动力 + 社会力 + 随机力 + 逃离力
        total_force = driving_force + np.array(social_force) * 0.00001 + random_force + escape_force

        # 更新速度
        self.acceleration = total_force / self.mass
        self.velocity = self.velocity + self.acceleration * dt

        # 限速
        speed = np.linalg.norm(self.velocity)
        if speed > self.max_speed:
            self.velocity = self.velocity / speed * self.max_speed

        # 恐慌时速度增加
        if self.pts_status:
            self.velocity *= (1.0 + self.panic_value * 0.3)

        # 更新位置
        new_x = self.x + self.velocity[0] * dt
        new_y = self.y + self.velocity[1] * dt

        # 边界约束（不能离家太远）
        position_updated = False
        if self.home_position:
            max_range = 0.002  # 最大活动范围
            dx = new_x - self.home_position[0]
            dy = new_y - self.home_position[1]
            if math.sqrt(dx ** 2 + dy ** 2) < max_range:
                self.x = new_x
                self.y = new_y
                position_updated = True

        # 【新增】计算本步移动量（用于影响情绪）
        if position_updated:
            self.recent_movement = math.sqrt((self.x - old_x) ** 2 + (self.y - old_y) ** 2)
        else:
            self.recent_movement = 0.0

    # 注：原有的 feedback() 和 adjust() 方法已删除（simulation 从不调用它们，
    # 且依赖的 self.delta / self.alpha / self.beta 已随统一压力模型迁移废弃）。


class CriticalInfraAgent:
    """
    关键基础设施Agent - 医院、泵站等

    【输出数据】用于画图
    - request() → C_hist (关键设施求助曲线)
    """

    def __init__(self, initiative=0.5, response=1.0, gamma=1.0, delta=0.02):
        self.initiative = initiative
        self.response = response
        self.gamma = gamma
        self.delta = delta

    def request(self, outage_ratio, emotion_factor):
        """计算紧急度"""
        urgency = self.gamma * self.initiative * outage_ratio * (1 + emotion_factor)
        return urgency

    def feedback(self):
        return self.gamma * self.initiative * self.response

    def adjust(self, outage_ratio):
        if outage_ratio > 1e-2:
            self.initiative = min(1.0, self.initiative + self.delta * 0.5)