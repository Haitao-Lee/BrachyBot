# BrachyBot 项目全面报告

> **版本**: 1.0.0  
> **最后更新**: 2026-05-27  
> **作者**: Ruijin Hospital AI Research Team (Haitao-Lee)  
> **许可证**: MIT License  
> **Python**: 3.10+  
> **仓库**: https://github.com/Haitao-Lee/BrachyBot

---

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构](#2-系统架构)
3. [目录结构](#3-目录结构)
4. [核心模块详解](#4-核心模块详解)
5. [工具工厂 (Tool Factory)](#5-工具工厂-tool-factory)
6. [大脑系统 (Brain System)](#6-大脑系统-brain-system)
7. [记忆系统 (Memory System)](#7-记忆系统-memory-system)
8. [技能系统 (Skills System)](#8-技能系统-skills-system)
9. [Web界面与API](#9-web界面与api)
10. [VoCo预训练模型](#10-voco预训练模型)
11. [临床工作流](#11-临床工作流)
12. [配置与环境变量](#12-配置与环境变量)
13. [数据格式](#13-数据格式)
14. [自进化机制](#14-自进化机制)
15. [部署与运行](#15-部署与运行)
16. [已知问题与注意事项](#16-已知问题与注意事项)
17. [开发指南](#17-开发指南)

---

## 1. 项目概述

### 1.1 什么是BrachyBot

BrachyBot是一个**自进化的AI Agent系统**，专为**近距离放射治疗（Brachytherapy）**计划而设计。它结合了：

- **医学图像分割** - 自动分割肿瘤（CTV）和危及器官（OAR）
- **治疗计划生成** - 自动生成种子源植入方案
- **剂量计算与评估** - 高斯模型和CNN剂量预测
- **自然语言交互** - 通过对话驱动整个工作流
- **自我进化** - 从每次交互中学习并改进

### 1.2 核心特性

| 特性 | 描述 |
|------|------|
| **多模态分割** | 支持14种CTV分割工具（VoCo/nnU-Net/TotalSegmentator）和104种OAR |
| **智能规划** | 规则引擎 + 强化学习两种规划模式 |
| **实时Viewer** | 浏览器端CT切片查看，支持窗宽窗位、十字线联动、3D重建 |
| **流式对话** | SSE流式输出，逐字显示AI响应 |
| **工具自创建** | LLM可以动态创建新工具 |
| **多Agent评审** | 4个专家角色（剂量安全、临床协议、风险评估、QA审计）加权投票 |
| **技能结晶** | 成功的工作流自动转化为可复用技能 |

### 1.3 技术栈

```
后端: Python 3.10+, Flask, SimpleITK, NumPy, PyTorch, MONAI
前端: 单文件HTML (5255行), Plotly.js, Three.js
LLM: MiniMax M2.7 (默认), 支持15+提供商
医学图像: SimpleITK, NIfTI, DICOM
深度学习: VoCo, nnU-Net, TotalSegmentator
```

---

## 2. 系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    用户界面 (Web/CLI)                        │
├─────────────────────────────────────────────────────────────┤
│                    Flask API 服务器                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ /api/chat│  │/api/plan │  │/api/view │  │/api/export│   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘    │
├───────┼──────────────┼────────────┼──────────────┼──────────┤
│       ▼              ▼            ▼              ▼          │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              AgenticSys.py (BrachyAgent)            │    │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐            │    │
│  │  │  Brain  │  │  Memory │  │  Skills │            │    │
│  │  │ System  │  │ System  │  │ System  │            │    │
│  │  └────┬────┘  └────┬────┘  └────┬────┘            │    │
│  └───────┼────────────┼────────────┼──────────────────┘    │
│          ▼            ▼            ▼                       │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              Tool Factory (40+ Tools)               │    │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐      │    │
│  │  │CTV Seg │ │OAR Seg │ │Dose Eng│ │Seed Plan│     │    │
│  │  └────────┘ └────────┘ └────────┘ └────────┘      │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
1. 用户上传CT → SimpleITK加载 → LPI方向重定向 → 体积数据存储
2. 用户请求分割 → 调用CTV/OAR工具 → 生成mask → 存储到memory
3. 用户请求规划 → 构建辐射体积 → 轨迹规划 → 种子规划 → 剂量计算
4. 剂量评估 → V100/V150/V200/D90/D95 → 评分 → 报告生成
5. 导出DICOM → RT Structure/Plan/Dose
```

---

## 3. 目录结构

```
BrachyBot/
├── __init__.py                    # 包初始化，版本1.0.0
├── AgenticSys.py                  # 核心Agent类 (2200+行)
├── brachybot.py                   # CLI入口
├── requirements.txt               # Python依赖
├── LICENSE                        # MIT许可证
├── .gitignore                     # Git忽略规则
│
├── brain/                         # LLM大脑系统
│   ├── core/                      # 核心抽象
│   │   ├── base.py                # BaseLLM, BaseDecider, BasePlanner
│   │   ├── router.py              # LLM路由 (15+提供商)
│   │   ├── tool_registry.py       # 工具注册表
│   │   ├── toolset.json           # 工具定义 (40+工具)
│   │   ├── tool_code_writer.py    # 动态工具创建
│   │   ├── multi_agent_critic.py  # 多Agent评审
│   │   └── tree_search_planner.py # 树搜索规划 (LATS/MCTS)
│   ├── providers/                 # 15个LLM提供商实现
│   │   ├── openai_llm.py
│   │   ├── anthropic_llm.py
│   │   ├── minimax_llm.py         # 默认使用
│   │   └── ... (12个更多)
│   ├── deciders/                  # 决策模块
│   │   ├── planner_decider.py     # 规划决策
│   │   ├── clinical_decider.py    # 临床决策
│   │   └── quality_decider.py     # 质量评分
│   ├── execution/                 # 执行引擎
│   │   ├── plan_executor.py       # 计划执行
│   │   └── case_executor.py       # 依赖解析执行
│   ├── knowledge/                 # RAG知识库
│   │   ├── rag.py                 # 简单RAG + 剂量RAG
│   │   └── knowledge_base.json    # 近距离治疗领域知识
│   └── integration/               # 集成层
│       ├── integration.py         # BrainToolBridge
│       └── enhanced_agent.py      # 增强Agent集成
│
├── memory/                        # 自进化记忆系统
│   ├── interaction_memory.py      # 交互记忆
│   ├── skill_learner.py           # 技能学习器
│   ├── preference_store.py        # 用户偏好存储
│   ├── experience_memory.py       # 经验记忆
│   ├── self_evolution.py          # 自进化引擎
│   ├── layered_memory.py          # 分层记忆 (L0-L4)
│   ├── reflexion_engine.py        # 反思引擎
│   ├── context_optimizer.py       # 上下文优化器
│   ├── user_profile.py            # 用户画像
│   ├── skill_crystallizer.py      # 技能结晶器
│   └── data/                      # 持久化存储
│       ├── reflexion_memory.json
│       ├── l0_rules.json          # 元规则
│       ├── l1_index.json          # 索引
│       ├── l2_facts.json          # 事实
│       ├── l3_sops.json           # 标准操作程序
│       ├── l4_archives.json       # 归档
│       └── user_profiles/         # 用户画像文件
│
├── skills/                        # 技能系统
│   ├── __init__.py                # 导出28+技能类
│   ├── skill_base.py              # 技能基类 + 注册表
│   ├── planning_skills.py         # 规划技能
│   ├── segmentation_skills.py     # 分割技能
│   ├── evaluation_skills.py       # 评估技能
│   ├── advanced_skills.py         # 15个高级技能
│   ├── markdown_loader.py         # Markdown技能加载器
│   └── markdown/                  # 10个Markdown技能定义
│       ├── standard_planning.md
│       ├── rl_planning.md
│       ├── pancreas_segmentation.md
│       └── ... (7个更多)
│
├── tool_factory/                  # 40+医学AI工具
│   ├── __init__.py                # BaseTool, ToolResult
│   ├── CTV_seg/                   # CTV分割 (14个工具)
│   │   ├── pancreatic_tumor.py    # nnU-Net胰腺
│   │   ├── pancreatic_tumor_voco.py # VoCo胰腺
│   │   └── ... (12个更多)
│   ├── OAR_seg/                   # OAR分割 (5个工具)
│   │   ├── totalsegmentator_oar.py # 104种解剖结构
│   │   └── ... (4个更多)
│   ├── traj_plan/                 # 轨迹规划 (2个工具)
│   ├── seed_plan/                 # 种子规划 (3个工具)
│   ├── dose_engine/               # 剂量计算 (2个工具)
│   ├── dose_eval/                 # 剂量评估 (5个工具)
│   ├── seed_seg/                  # 种子检测
│   ├── plan_quality/              # 计划质量 (3个工具)
│   ├── image_processing/          # 图像处理
│   ├── output/                    # 导出工具
│   ├── code_executor/             # 代码执行器
│   ├── filesystem_browser/        # 文件浏览器
│   └── viewer_command/            # Viewer控制 (3个工具)
│
├── VoCo/                          # VoCo预训练模型 (36个权重文件)
│   ├── 3D-IRCADb/                 # 肝脏分割
│   ├── BTCV/                      # 腹部器官
│   ├── Totalsegmentator/          # 全身分割
│   └── ... (15个更多数据集)
│
├── dose_pre/                      # CNN剂量预测模型
│   ├── myDoseNet.py               # UNet架构
│   ├── functions.py               # 工具函数
│   └── dose_model.pth             # 预训练权重 (~24MB)
│
├── web/                           # Web界面
│   ├── server.py                  # Flask服务器 (1086行)
│   └── app/
│       └── index.html             # 单页应用 (5255行)
│
├── uploads/                       # 上传的CT文件
├── examples/                      # 使用示例
├── tests/                         # 测试套件
└── docs/                          # 文档目录
```

---

## 4. 核心模块详解

### 4.1 AgenticSys.py - 核心Agent

这是整个系统的核心，包含`BrachyAgent`类（2200+行）。主要职责：

```python
class BrachyAgent:
    """
    自进化的Brachytherapy AI Agent
    
    核心功能:
    1. 初始化大脑系统 (LLM路由、工具注册)
    2. 初始化记忆系统 (分层记忆、经验、反思)
    3. 初始化技能系统 (技能注册、匹配)
    4. 处理用户输入 (自然语言理解、工具调用)
    5. 执行治疗计划工作流
    6. 自我进化 (学习、优化、结晶)
    """
```

**关键方法**:

| 方法 | 功能 |
|------|------|
| `__init__()` | 初始化所有子系统 |
| `chat()` | 处理用户对话 |
| `execute_plan()` | 执行治疗计划 |
| `_execute_tool_with_memory()` | 执行工具并记录经验 |
| `_trigger_evolution()` | 触发自进化 |
| `_build_system_prompt()` | 构建系统提示词 |

**系统提示词结构**:

```
1. 角色定义 - BrachyBot是近距离治疗AI助手
2. 可用工具列表 - 所有可调用的工具
3. Viewer控制API - set_window, set_preset, navigate_slice等
4. 当前UI状态 - CT是否加载、分割状态、当前切片
5. 重要规则 - 11条规则（分割时同时调用CTV和OAR等）
```

### 4.2 brachybot.py - CLI入口

```bash
# 直接规划
python brachybot.py --ct path/to/ct.nii.gz --ctv path/to/ctv.nii.gz --mode rule_based

# 交互式聊天
python brachybot.py --chat

# 启动Web服务器
python brachybot.py --server --port 8080

# 指定CT文件
python brachybot.py --ct path/to/ct.nii --chat
```

**参数说明**:

| 参数 | 类型 | 描述 |
|------|------|------|
| `--ct` | str | CT图像路径 |
| `--ctv` | str | CTV mask路径 |
| `--oar` | str | OAR mask路径 |
| `--mode` | str | 规划模式: `rule_based` 或 `rl` |
| `--chat` | flag | 启动聊天模式 |
| `--server` | flag | 启动Web服务器 |
| `--port` | int | 服务器端口 (默认8080) |

---

## 5. 工具工厂 (Tool Factory)

### 5.1 工具基类

```python
# tool_factory/__init__.py

class BaseTool(ABC):
    """所有工具的抽象基类"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称"""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述"""
        pass
    
    @property
    @abstractmethod
    def input_schema(self) -> Dict:
        """输入JSON Schema"""
        pass
    
    @abstractmethod
    def _execute(self, **kwargs) -> ToolResult:
        """执行工具逻辑"""
        pass

class ToolResult:
    """标准化工具返回"""
    success: bool
    data: Any
    message: str
    error: str
    metadata: Dict
```

### 5.2 CTV分割工具 (14个)

| 工具名 | 文件 | 方法 | 支持肿瘤类型 |
|--------|------|------|-------------|
| `pancreatic_tumor` | pancreatic_tumor.py | nnU-Net | 胰腺癌 |
| `pancreatic_tumor_voco` | pancreatic_tumor_voco.py | VoCo | 胰腺癌 |
| `prostate_tumor` | prostate_tumor.py | nnU-Net | 前列腺癌 |
| `prostate_tumor_voco` | prostate_tumor_voco.py | VoCo | 前列腺癌 |
| `liver_tumor` | liver_tumor.py | TotalSegmentator | 肝癌 |
| `liver_tumor_voco` | liver_tumor_voco.py | VoCo | 肝癌 |
| `lung_tumor` | lung_tumor.py | TotalSegmentator | 肺癌 |
| `lung_tumor_voco` | lung_tumor_voco.py | VoCo | 肺癌 |
| `kidney_tumor` | kidney_tumor.py | TotalSegmentator | 肾癌 |
| `kidney_tumor_voco` | kidney_tumor_voco.py | VoCo | 肾癌 |
| `colon_tumor_voco` | colon_tumor_voco.py | VoCo | 结肠癌 |
| `head_neck_tumor` | head_neck_tumor.py | TotalSegmentator | 头颈癌 |
| `btcv_tumor_voco` | btcv_tumor_voco.py | VoCo | 腹部多器官 |
| `segthor_tumor_voco` | segthor_tumor_voco.py | VoCo | 胸部器官 |

**VoCo vs nnU-Net**:

- **VoCo**: 使用视觉上下文学习，不需要外部权重，开箱即用
- **nnU-Net**: 需要预训练权重，放在`plans/seg/`目录下
- **TotalSegmentator**: 需要安装`TotalSegmentator`包

**默认选择**: 当用户请求CTV分割但未指定肿瘤类型时，默认使用`pancreatic_tumor_voco`（VoCo版本）。

### 5.3 OAR分割工具 (5个)

| 工具名 | 文件 | 方法 | 支持器官数 |
|--------|------|------|-----------|
| `totalsegmentator_oar` | totalsegmentator_oar.py | TotalSegmentator | 104种 |
| `voco_total_segmentation` | voco_total_segmentation.py | VoCo | 多器官 |
| `pancreatic_oar` | pancreatic_oar.py | nnU-Net | 胰腺相关 |
| `aorta_vessel_voco` | aorta_vessel_voco.py | VoCo | 主动脉 |

**104种解剖结构** (totalsegmentator_oar.py):

```
包括: 脊柱(颈椎7+胸椎12+腰椎5+骶骨), 肋骨(24根),
      膀胱, 直肠, 股骨头(左右), 肺(左右), 肾脏(左右),
      肝脏, 胃, 食管, 心脏, 主动脉, 腔静脉, 门静脉,
      肝静脉, 肠道, 脊髓, 气管, 支气管, 甲状腺,
      前列腺/子宫, 卵巢(左右), 输尿管(左右) 等
```

### 5.4 轨迹规划工具 (2个)

```python
# trajectory_init.py - 初始化轨迹
def _execute(self, **kwargs):
    """
    输入:
        ct_array: CT数据 (Z, Y, X)
        ctv_mask: CTV二值mask
        oar_mask: OAR多标签mask
        num_trajectories: 轨迹数量 (默认10)
        reference_point: 参考点 (可选)
    
    算法:
        1. 在参考点周围均匀采样方向
        2. 计算每个方向的CTV覆盖率
        3. 计算OAR避让距离
        4. 按质量评分筛选
    """

# trajectory_refine.py - 优化轨迹
def _execute(self, **kwargs):
    """
    输入:
        trajectories: 初始轨迹列表
        ctv_mask: CTV mask
        oar_mask: OAR mask
    
    算法:
        1. 过滤CTV覆盖率 < 阈值的轨迹
        2. 过滤OAR距离 < 安全距离的轨迹
        3. 过滤角度偏差过大的轨迹
        4. 返回优化后的轨迹
    """
```

### 5.5 种子规划工具 (3个)

```python
# seed_planning.py - 统一接口
class SeedPlanningTool(BaseTool):
    """
    统一的种子规划接口
    
    参数:
        mode: "rule_based" 或 "rl"
        ct_array, ctv_mask, oar_mask, trajectories
        prescribed_dose: 处方剂量 (Gy)
        seed_activity: 种子活度 (U)
    """

# seed_planning_rule_based.py - 规则引擎
class RuleBasedSeedPlanning:
    """
    规则引擎种子规划
    
    算法:
        1. 沿每条轨迹等间距放置种子
        2. 使用CNN预测剂量分布
        3. 贪心优化种子位置
        4. 满足剂量约束时停止
    """

# seed_planning_rl.py - 强化学习
class RLSeedPlanning:
    """
    REINFORCE强化学习种子规划
    
    算法:
        1. 策略网络预测种子位置
        2. 环境计算奖励 (剂量覆盖 - OAR剂量)
        3. REINFORCE更新策略
        4. 迭代优化直到收敛
    """
```

### 5.6 剂量计算工具 (2个)

```python
# gaussian_dose_engine.py - 高斯模型
class GaussianDoseEngine:
    """
    基于TG-43协议的高斯剂量模型
    
    公式: D(r) = S_k * Λ * [G(r,θ)/G(r0,θ0)] * g(r) * F(r,θ)
    
    参数:
        r: 距离种子中心的距离
        θ: 角度
        S_k: 源强度
        Λ: 剂量率常数
    """

# cnn_dose_engine.py - CNN预测
class CNNDoseEngine:
    """
    myDoseNet CNN剂量预测
    
    架构: BasicUNet (MONAI)
    输入: CT + 种子位置
    输出: 3D剂量分布
    
    优势: 比高斯模型快100倍
    """
```

### 5.7 剂量评估工具 (5个)

```python
# vx_metrics.py - 体积指标
def calculate_v_metrics(dose_array, prescribed_dose):
    """
    V100: 处方剂量覆盖的CTV体积百分比 (目标: >90%)
    V150: 150%处方剂量覆盖的体积 (目标: <50%)
    V200: 200%处方剂量覆盖的体积 (目标: <20%)
    """

# dx_metrics.py - 剂量指标
def calculate_d_metrics(dose_array, ctv_mask):
    """
    D90: 覆盖90%CTV的最小剂量 (目标: >处方剂量)
    D100: 覆盖100%CTV的最小剂量
    """

# dvh_calculation.py - DVH曲线
def calculate_dvh(dose_array, structure_mask, num_bins=100):
    """
    计算剂量-体积直方图 (DVH)
    
    返回:
        dose_bins: 剂量轴 (Gy)
        volume_percent: 体积百分比轴 (%)
    """

# comprehensive_dose_evaluation.py - 综合评估
def comprehensive_evaluation(dose_array, ctv_mask, oar_masks):
    """
    综合评估所有指标:
    - CTV覆盖: V100, V150, V200, D90, D95
    - OAR保护: 各器官Dmax, Dmean
    - 均匀性指数 (HI)
    - 适形性指数 (CI)
    - 综合评分 (0-100)
    """
```

### 5.8 其他工具

```python
# code_executor/__init__.py - 代码执行器
class CodeExecutorTool(BaseTool):
    """
    沙盒化Python代码执行
    
    安全限制:
    - 禁止import os, sys, subprocess
    - 禁止文件系统写入
    - 执行超时: 30秒
    - 内存限制: 1GB
    """

# filesystem_browser/__init__.py - 文件浏览器
class FilesystemBrowserTool(BaseTool):
    """
    文件系统浏览
    
    功能:
    - list_directory: 列出目录内容
    - read_file: 读取文件内容 (限制100KB)
    - search_files: 搜索文件
    """

# viewer_command/viewer_command.py - Viewer控制
class ViewerCommandTool(BaseTool):
    """
    CT Viewer控制
    
    命令:
    - set_window: 设置窗宽窗位
    - set_preset: 应用预设 (soft/bone/lung/brain)
    - navigate_slice: 跳转到指定切片
    - set_threshold: 设置HU阈值
    - toggle_overlay: 切换CTV/OAR显示
    - get_state: 获取当前状态
    """

# dicom_rt_exporter.py - DICOM导出
class DICOMRTExporter(BaseTool):
    """
    导出DICOM RT格式
    
    输出:
    - RT Structure Set (.dcm)
    - RT Plan (.dcm)
    - RT Dose (.dcm)
    """

# report_generator.py - 报告生成
class ReportGenerator(BaseTool):
    """
    生成治疗计划报告
    
    格式:
    - JSON: 结构化数据
    - HTML: 可视化报告
    - PDF: 打印报告 (需要weasyprint)
    """
```

---

## 6. 大脑系统 (Brain System)

### 6.1 LLM路由 (router.py)

```python
class LLMRouter:
    """
    LLM请求路由器
    
    支持15个提供商:
    1. OpenAI (GPT-4, GPT-4o)
    2. Anthropic (Claude)
    3. OpenRouter (聚合)
    4. Qwen (通义千问)
    5. Kimi (月之暗面)
    6. MiniMax (M2.7) ← 默认
    7. GLM (智谱)
    8. Gemini (Google)
    9. Groq
    10. Grok (xAI)
    11. Mimo (小米)
    12. DeepSeek
    13. Tencent (腾讯)
    14. LocalLLM (本地)
    15. OllamaLLM
    """
    
    def chat_messages(self, messages, tools=None):
        """
        发送消息到LLM
        
        支持:
        - 普通请求
        - 工具调用 (function calling)
        - 流式输出 (stream=True)
        """
```

**当前默认配置** (MiniMax):

```python
# 使用Anthropic兼容API
provider = "anthropic"
model = "MiniMax-M2.7-highspeed"
base_url = "https://api.minimax.chat/v1"
api_key = os.getenv("ANTHROPIC_API_KEY")
```

### 6.2 工具注册表 (tool_registry.py)

```python
class ToolRegistry:
    """
    大脑侧的工具管理
    
    功能:
    - 从toolset.json加载工具定义
    - 按ID查找工具
    - 生成工具描述给LLM
    - 与AgenticSys的ToolRegistry同步
    """
```

**toolset.json结构**:

```json
{
  "tools": [
    {
      "id": 1,
      "name": "ctv_segmentation",
      "type": "segmentation",
      "category": "CTV",
      "description": "Segment clinical target volume",
      "parameters": {
        "image_path": {"type": "string"},
        "tumor_type": {"type": "string", "enum": ["pancreatic", "prostate", ...]}
      }
    },
    // ... 40+ more tools
  ]
}
```

### 6.3 多Agent评审 (multi_agent_critic.py)

```python
class MultiAgentCritic:
    """
    4个专家角色评审治疗计划
    
    专家角色:
    1. 剂量安全专家 (权重: 1.5x)
       - 检查CTV覆盖率
       - 检查OAR剂量限制
       - 检查热点/冷点
    
    2. 临床协议专家 (权重: 1.3x)
       - 检查是否符合临床指南
       - 检查TG-43/TG-186合规性
       - 检查QUANTEC限制
    
    3. 风险评估专家 (权重: 1.2x)
       - 评估潜在风险
       - 检查边界情况
       - 评估鲁棒性
    
    4. QA审计专家 (权重: 1.0x)
       - 检查数据完整性
       - 检查计算正确性
       - 生成审计报告
    
    投票机制:
    - 加权投票决定是否接受计划
    - 至少3/4专家同意才能通过
    """
```

### 6.4 树搜索规划 (tree_search_planner.py)

```python
class PlanningTreeSearch:
    """
    LATS/MCTS树搜索规划
    
    算法:
    1. 初始化根节点 (当前状态)
    2. 选择: UCB1选择最优子节点
    3. 扩展: LLM生成新的规划步骤
    4. 模拟: 执行计划并评估
    5. 回溯: 更新节点统计
    
    参数:
    - max_iterations: 最大迭代次数 (默认10)
    - exploration_weight: 探索权重 (默认1.414)
    - beam_width: 束宽度 (默认3)
    """
```

### 6.5 动态工具创建 (tool_code_writer.py)

```python
class ToolCodeWriter:
    """
    LLM动态创建新工具
    
    流程:
    1. 用户描述需求
    2. LLM生成工具代码
    3. 语法检查
    4. 安全审查 (禁止os.system, eval等)
    5. 单元测试
    6. 注册到工具注册表
    
    示例:
    用户: "我需要一个计算膀胱D2cc的工具"
    LLM: 生成tool代码 -> 验证 -> 注册
    """
```

---

## 7. 记忆系统 (Memory System)

### 7.1 分层记忆 (layered_memory.py)

```python
class LayeredMemory:
    """
    5层记忆架构
    
    L0 - 元规则 (MetaRules)
        - 始终激活的硬编码规则
        - 例如: "CTV覆盖率必须>90%"
        - 最高优先级
    
    L1 - 索引 (Index)
        - 快速路由查找
        - 关键词 -> 经验映射
        - O(1)查找复杂度
    
    L2 - 事实 (Facts)
        - 稳定的领域知识
        - 例如: "胰腺癌处方剂量通常为..."
        - 中等优先级
    
    L3 - SOP (标准操作程序)
        - 可复用的工作流
        - 从成功经验结晶而来
        - 例如: "胰腺癌标准计划流程"
    
    L4 - 归档 (Archives)
        - 历史会话记录
        - 完整的交互轨迹
        - 最低优先级
    
    检索策略:
    1. L0检查 (硬性约束)
    2. L1快速匹配
    3. L2事实查询
    4. L3 SOP匹配
    5. L4相似案例检索
    """
```

### 7.2 反思引擎 (reflexion_engine.py)

```python
class ReflexionEngine:
    """
    3种反思模式
    
    1. Self-Reflection (自我反思)
       - LLM分析自己的行为
       - 识别错误和改进点
       - 生成改进建议
    
    2. Multi-Agent Reflexion (多Agent反思)
       - 多个角色分别反思
       - 综合不同视角
       - 生成更全面的改进
    
    3. Heuristic Reflection (启发式反思)
       - 基于规则的反思
       - 快速、确定性
       - 适用于常见错误
    
    触发条件:
    - 任务失败时自动触发
    - 每5次交互触发一次
    - 用户请求时触发
    """
```

### 7.3 技能结晶器 (skill_crystallizer.py)

```python
class SkillCrystallizer:
    """
    将成功的工作流转化为可复用技能
    
    流程:
    1. 记录完整的交互轨迹
    2. 任务成功后提取模式
    3. LLM分析并生成SOP
    4. 验证SOP的正确性
    5. 注册为新技能
    6. 后续自动匹配应用
    
    命名规则:
    Auto_{Type}_{Tools}
    例如: Auto_PancreasPlan_ctv_seg+oar_seg+traj+seed
    """
```

### 7.4 上下文优化器 (context_optimizer.py)

```python
class ContextDensityOptimizer:
    """
    Token高效的提示构建
    
    Token预算分配 (总计8000):
    - System: 1500 tokens
    - Tools: 2000 tokens
    - Memory: 1500 tokens
    - Conversation: 3000 tokens
    
    优化策略:
    1. 压缩冗余信息
    2. 优先保留关键上下文
    3. 动态调整预算
    4. 截断低优先级内容
    """
```

### 7.5 用户画像 (user_profile.py)

```python
class UserProfile:
    """
    辩证式用户画像 (3层)
    
    Layer 1 - 显式偏好 (Explicit)
        - 用户直接声明的偏好
        - 最高置信度
        - 例如: "我总是使用规则引擎"
    
    Layer 2 - 推断偏好 (Inferred)
        - 从行为推断的偏好
        - 中等置信度
        - 例如: 用户总是修改剂量约束
    
    Layer 3 - 验证偏好 (Validated)
        - 经过验证的偏好
        - 动态置信度
        - 例如: 多次确认的偏好
    
    更新机制:
    - 每次交互后更新
    - 使用贝叶斯推理
    - 置信度衰减
    """
```

---

## 8. 技能系统 (Skills System)

### 8.1 技能基类

```python
# skills/skill_base.py

class Skill(ABC):
    """技能抽象基类"""
    
    @property
    @abstractmethod
    def name(self) -> str: pass
    
    @property
    @abstractmethod
    def triggers(self) -> List[str]:
        """触发关键词"""
        pass
    
    @abstractmethod
    def execute(self, agent, **kwargs) -> Any:
        """执行技能"""
        pass

class SkillRegistry:
    """技能注册表
    
    存储: skills/data/skills/skills_registry.json
    支持:
    - 注册新技能
    - 关键词匹配
    - 优先级排序
    """
```

### 8.2 Python类技能 (28个)

```python
# 规划技能
class StandardPlanningSkill(Skill):
    triggers = ["规划", "标准计划", "treatment plan"]
    
class RLPlanningSkill(Skill):
    triggers = ["RL", "强化学习", "complex"]
    
class QuickPlanningSkill(Skill):
    triggers = ["快速计划", "quick plan"]

# 分割技能
class PancreasSegmentationSkill(Skill):
    triggers = ["胰腺分割", "pancreas"]
    
class ProstateSegmentationSkill(Skill):
    triggers = ["前列腺分割", "prostate"]
    
class GenericSegmentationSkill(Skill):
    triggers = ["分割", "segment"]

# 工作流技能
class PancreasFullSkill(Skill):
    triggers = ["胰腺完整计划"]
    
class ProstateFullSkill(Skill):
    triggers = ["前列腺完整计划"]

# 评估技能
class StandardEvaluationSkill(Skill):
    triggers = ["评估", "evaluate"]
    
class DetailedEvaluationSkill(Skill):
    triggers = ["详细评估", "detailed eval"]

# 元技能
class SelfEvolveSkill(Skill):
    triggers = ["进化", "总结经验", "evolve"]
    
class CodeWriterSkill(Skill):
    triggers = ["写工具", "create tool"]
```

### 8.3 Markdown技能 (10个)

```markdown
# skills/markdown/pancreas_segmentation.md

---
name: pancreas_segmentation
description: 胰腺癌CTV分割技能
triggers:
  - 胰腺分割
  - pancreatic segmentation
  - 胰腺癌
tools:
  - ctv_segmentation
  - oar_segmentation
parameters:
  tumor_type: pancreatic
  fast_mode: true
---

## 执行步骤

1. 加载CT图像
2. 调用ctv_segmentation (tumor_type=pancreatic)
3. 调用oar_segmentation
4. 返回分割结果
```

---

## 9. Web界面与API

### 9.1 Flask服务器 (server.py)

```python
# web/server.py - 1086行

# 主要功能:
# 1. 静态文件服务
# 2. REST API端点
# 3. SSE流式响应
# 4. 任务管理
# 5. 文件上传

# 启动方式:
# python web/server.py --port 8080 --host 0.0.0.0
```

**API端点完整列表**:

| 端点 | 方法 | 认证 | 描述 |
|------|------|------|------|
| `/` | GET | - | 提供index.html |
| `/api/upload` | POST | - | 上传文件 |
| `/api/chat` | POST | API Key | 自然语言对话 (SSE流式) |
| `/api/status` | GET | - | 获取Agent状态 |
| `/api/plan/preoperative` | POST | API Key | 术前计划 |
| `/api/plan/intraoperative` | POST | API Key | 术中再计划 |
| `/api/config` | POST | - | 更新配置 |
| `/api/reset` | POST | API Key | 重置状态 |
| `/api/viewer/load` | POST | - | 加载CT图像 |
| `/api/viewer/slice` | POST | - | 获取切片PNG |
| `/api/viewer/volume` | GET | - | 获取体积数据 |
| `/api/viewer/overlay` | POST | - | 获取分割overlay |
| `/api/viewer/threshold` | POST | - | HU阈值分割 |
| `/api/viewer/hu` | POST | - | 获取HU值 |
| `/api/viewer/3d` | POST | - | 3D网格重建 |
| `/api/viewer/control` | POST | API Key | Viewer控制 |
| `/api/export/dicom` | POST | API Key | DICOM导出 |
| `/api/export/report` | POST | API Key | 报告生成 |
| `/api/tasks/stream` | SSE | - | 任务进度流 |
| `/api/tasks/<id>` | GET | - | 任务状态 |
| `/api/tasks` | GET | - | 任务列表 |

### 9.2 前端界面 (index.html)

**单文件HTML应用 (5255行)**:

```
依赖库:
- Plotly.js 2.35.2 (DVH图表)
- Three.js r128 (3D渲染)
- Google Fonts (Inter字体)

布局:
┌─────────────────┬─────────────────┐
│                 │                 │
│   聊天区域       │   控制面板       │
│   (左侧)        │   (右侧, Tab)   │
│                 │                 │
│   - 消息流       │   - Input       │
│   - 工具进度     │   - Metrics     │
│   - AI响应      │   - DVH         │
│                 │   - Seeds       │
│                 │   - Viewers     │
│                 │                 │
└─────────────────┴─────────────────┘
```

**Viewer功能**:

```javascript
// 核心功能
1. 体积渲染 - CT数据以Int16Array发送到前端，浏览器端渲染
2. 三平面显示 - Axial, Sagittal, Coronal
3. 窗宽窗位 - 预设: soft/bone/lung/brain + 自定义
4. 十字线联动 - 点击一个viewer，其他viewer同步
5. 测量工具 - 距离、角度、矩形
6. 缩放平移 - 鼠标滚轮缩放，拖拽平移
7. 3D重建 - marching cubes算法
8. HU值显示 - 鼠标悬停显示HU值
9. Overlay显示 - CTV/OAR半透明叠加
10. Display模式 - CT Only / CT+Label / Label Only
```

**Slash命令**:

```
/help     - 显示帮助
/plan     - 开始治疗计划
/segment  - 分割CTV和OAR
/evaluate - 评估剂量
/export   - 导出DICOM
/viewer   - 切换到Viewer标签
/goal     - 自主执行直到目标完成
/stop     - 停止当前任务
/clear    - 清空对话
```

### 9.3 SSE流式响应

```python
# /api/chat 端点的SSE格式

# 文本块
data: {"type": "text_chunk", "content": "正在分析"}

# 工具调用开始
data: {"type": "tool_call", "tool": "ctv_segmentation", "args": {...}}

# 工具执行进度
data: {"type": "tool_progress", "tool": "ctv_segmentation", "progress": 50}

# 工具调用完成
data: {"type": "tool_result", "tool": "ctv_segmentation", "result": {...}}

# 完整响应
data: {"type": "done", "content": "分割完成！"}
```

---

## 10. VoCo预训练模型

### 10.1 模型列表

```
VoCo/
├── 3D-IRCADb/          # 肝脏分割
│   ├── model_basline_57.19.pt
│   ├── model_suprem_68.48.pt
│   └── model_voco_74.27.pt      ← 最佳
│
├── BTCV/               # 腹部多器官
│   ├── model_baseline.pt
│   ├── model_swin_82.58.pt
│   ├── model_unimiss_81.85.pt
│   ├── model_suprem_85.32.pt
│   └── model_voco_86.64.pt      ← 最佳
│
├── Totalsegmentator/   # 全身分割
│   ├── model_voco_large_85.27.pt
│   └── model_86.18.pt.zip       ← 需要解压
│
├── PANORAMA/           # 胰腺
│   ├── model_suprem.pt
│   └── model_voco.pt            ← 用于胰腺分割
│
└── ... (15个更多数据集)
```

### 10.2 使用方式

```python
# 在CTV分割工具中使用
from tool_factory.CTV_seg.pancreatic_tumor_voco import VoCoPancreaticTumorTool

tool = VoCoPancreaticTumorTool()
result = tool.execute(image=sitk_image)

# 返回
# result.metadata["ctv_array"] - 分割mask
# result.metadata["ctv_volume_mm3"] - 体积
```

### 10.3 模型加载

```python
# pancreatic_tumor_voco.py

def _load_model(self):
    """加载VoCo模型"""
    model_path = os.path.join(
        os.path.dirname(__file__), 
        "..", "..", "VoCo", "PANORAMA", "model_voco.pt"
    )
    
    model = VoCoSegModel(...)  # MONAI模型
    model.load_state_dict(torch.load(model_path))
    model.eval()
    return model
```

---

## 11. 临床工作流

### 11.1 术前计划流程

```
┌─────────────────────────────────────────────────────────────┐
│                    术前计划流程                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. CT图像加载                                               │
│     └─ SimpleITK读取 → LPI方向重定向                         │
│                                                             │
│  2. CTV分割                                                  │
│     └─ VoCo/nnU-Net → 二值mask                              │
│                                                             │
│  3. OAR分割                                                  │
│     └─ TotalSegmentator → 104种器官mask                      │
│                                                             │
│  4. 构建辐射体积                                              │
│     └─ CTV=1.0, OAR=3.0, 其他=0.0                           │
│                                                             │
│  5. 轨迹规划                                                 │
│     └─ 方向采样 → 质量筛选 → 优化                            │
│                                                             │
│  6. 种子规划                                                 │
│     └─ 规则引擎/强化学习 → 种子位置                          │
│                                                             │
│  7. 剂量计算                                                 │
│     └─ 高斯模型/CNN预测 → 3D剂量分布                         │
│                                                             │
│  8. 剂量评估                                                 │
│     └─ V100/V150/V200/D90/D95 → 综合评分                    │
│                                                             │
│  9. 导出                                                     │
│     └─ DICOM RT Structure/Plan/Dose + 报告                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 11.2 术中再计划流程

```
┌─────────────────────────────────────────────────────────────┐
│                    术中再计划流程                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 加载术中CT                                               │
│                                                             │
│  2. 种子检测                                                 │
│     └─ 阈值分割 + 连通域分析                                 │
│                                                             │
│  3. 偏差检查                                                 │
│     └─ 计划位置 vs 实际位置                                  │
│                                                             │
│  4. 决策                                                     │
│     ├─ 偏差 < 阈值 → 接受当前计划                            │
│     └─ 偏差 > 阈值 → 重新规划                                │
│                                                             │
│  5. 如果需要重新规划                                         │
│     └─ 基于实际种子位置重新优化                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 11.3 支持的癌症类型

| 癌症 | CTV分割 | OAR分割 | 特殊考虑 |
|------|---------|---------|----------|
| **胰腺癌** | VoCo/nnU-Net | TotalSegmentator | 注意十二指肠保护 |
| **前列腺癌** | VoCo/nnU-Net | TotalSegmentator | 注意直肠、膀胱保护 |
| **肝癌** | VoCo/TotalSeg | TotalSegmentator | 注意门静脉、肝静脉 |
| **肺癌** | VoCo/TotalSeg | TotalSegmentator | 注意食管、脊髓 |
| **肾癌** | VoCo/TotalSeg | TotalSegmentator | 注意对侧肾脏 |
| **头颈癌** | TotalSegmentator | TotalSegmentator | 注意脊髓、脑干 |
| **结肠癌** | VoCo | TotalSegmentator | 注意肠道 |

### 11.4 剂量约束参考

```json
// brain/knowledge/knowledge_base.json

{
  "prostate": {
    "prescribed_dose_gy": 145,
    "ctv_V100": ">90%",
    "ctv_D90": ">100%",
    "rectum_D2cc": "<75 Gy",
    "bladder_D2cc": "<80 Gy"
  },
  "pancreas": {
    "prescribed_dose_gy": 25,
    "ctv_V100": ">90%",
    "duodenum_D2cc": "<15 Gy",
    "stomach_D2cc": "<15 Gy"
  },
  "liver": {
    "prescribed_dose_gy": 30,
    "ctv_V100": ">90%",
    "normal_liver_Dmean": "<15 Gy"
  }
}
```

---

## 12. 配置与环境变量

### 12.1 LLM提供商配置

```bash
# 默认使用MiniMax
export ANTHROPIC_API_KEY="your-minimax-api-key"
export ANTHROPIC_BASE_URL="https://api.minimax.chat/v1"
export ANTHROPIC_MODEL="MiniMax-M2.7-highspeed"

# 或使用OpenRouter
export OPENROUTER_API_KEY="your-openrouter-key"
export BRACHY_LLM_PROVIDER="openrouter"

# 或使用OpenAI
export OPENAI_API_KEY="your-openai-key"
export BRACHY_LLM_PROVIDER="openai"

# 或使用Qwen
export QWEN_API_KEY="your-qwen-key"
export BRACHY_LLM_PROVIDER="qwen"
```

### 12.2 服务器配置

```bash
# 端口
export BRACHY_PORT=8080

# 主机
export BRACHY_HOST=0.0.0.0

# API密钥 (可选，保护敏感端点)
export BRACHYBOT_API_KEY="your-api-key"
```

### 12.3 配置文件

```python
# 虽然没有config.json，但可以在代码中配置

# AgenticSys.py 中的默认配置
DEFAULT_CONFIG = {
    "planning": {
        "default_mode": "rule_based",
        "num_trajectories": 10,
        "prescribed_dose_gy": 145,
        "seed_activity_u": 1.0
    },
    "dose": {
        "engine": "gaussian",  # 或 "cnn"
        "resolution_mm": 1.0
    },
    "evolution": {
        "trigger_interval": 5,
        "max_skills": 100
    }
}
```

---

## 13. 数据格式

### 13.1 输入格式

| 格式 | 扩展名 | 用途 |
|------|--------|------|
| NIfTI | `.nii`, `.nii.gz` | CT图像, 分割mask |
| DICOM | `.dcm` | CT图像 |
| MetaImage | `.mha`, `.mhd` | CT图像 |
| NRRD | `.nrrd` | CT图像 |

### 13.2 内部表示

```python
# CT图像
ct_image: sitk.Image  # SimpleITK图像对象
ct_array: np.ndarray  # Shape: (Z, Y, X), dtype: int16, 值: HU

# CTV mask
ctv_array: np.ndarray  # Shape: (Z, Y, X), dtype: uint8, 值: 0或1

# OAR mask
oar_array: np.ndarray  # Shape: (Z, Y, X), dtype: uint8, 值: 0-104

# 辐射体积
radiation_volume: np.ndarray  # Shape: (Z, Y, X), dtype: float64
# 1.0 = CTV, 0.0 = 背景, 3.0 = OAR

# 种子位置
seed_positions: List[List[float]]  # [[x, y, z], ...] 物理坐标(mm)

# 剂量分布
dose_array: np.ndarray  # Shape: (Z, Y, X), dtype: float, 值: Gy

# 轨迹
trajectories: List[Dict]  # [{"origin": [x,y,z], "direction": [dx,dy,dz], "depth": float}, ...]
```

### 13.3 输出格式

```python
# DICOM RT Structure Set
# - RT Structure Set (.dcm)
# - 包含CTV、OAR的轮廓定义

# DICOM RT Plan
# - RT Plan (.dcm)
# - 包含种子位置、活度

# DICOM RT Dose
# - RT Dose (.dcm)
# - 包含3D剂量分布

# JSON报告
{
    "report_info": {
        "plan_name": "Plan_20260527_150945",
        "patient_id": "P001",
        "generated_at": "2026-05-27T15:09:45",
        "format_version": "1.0"
    },
    "plan_summary": {
        "total_seeds": 50,
        "total_trajectories": 5,
        "prescribed_dose_gy": 145.0,
        "plan_score": 85.5
    },
    "ctv_metrics": {
        "voxels": 12345,
        "volume_mm3": 5678.9
    },
    "dose_metrics": {
        "V100": 92.5,
        "V150": 45.2,
        "V200": 12.3,
        "D90": 148.5,
        "D95": 142.1
    },
    "oar_metrics": {
        "rectum_D2cc": 65.2,
        "bladder_D2cc": 72.1
    }
}
```

---

## 14. 自进化机制

### 14.1 六大自进化机制

```
┌─────────────────────────────────────────────────────────────┐
│                    自进化机制                                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 分层记忆 (L0-L4)                                        │
│     └─ 从元规则到归档的5层记忆架构                           │
│                                                             │
│  2. 反思引擎                                                │
│     └─ 自我反思、多Agent反思、启发式反思                     │
│                                                             │
│  3. 技能结晶                                                │
│     └─ 成功轨迹 → 提取模式 → 生成SOP → 验证 → 注册技能      │
│                                                             │
│  4. 上下文优化                                              │
│     └─ Token预算管理，高效提示构建                           │
│                                                             │
│  5. 多Agent评审                                             │
│     └─ 4专家加权投票，提高决策质量                           │
│                                                             │
│  6. 自动进化触发                                            │
│     └─ 每5次交互自动触发进化                                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 14.2 技能结晶流程

```
成功的工作流
    ↓
提取交互轨迹
    ↓
LLM分析模式
    ↓
生成SOP描述
    ↓
验证SOP
    ↓
注册为技能
    ↓
后续自动匹配
```

### 14.3 反思触发条件

```python
# 1. 任务失败时
if task_result.success == False:
    reflexion_engine.reflect(task_result)

# 2. 定期触发
if interaction_count % 5 == 0:
    reflexion_engine.reflect(recent_interactions)

# 3. 用户请求
if user_input.contains(["反思", "反思", "reflect"]):
    reflexion_engine.reflect()
```

---

## 15. 部署与运行

### 15.1 环境准备

```bash
# 1. 克隆仓库
git clone https://github.com/Haitao-Lee/BrachyBot.git
cd BrachyBot

# 2. 创建虚拟环境
conda create -n brachybot python=3.10
conda activate brachybot

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
export ANTHROPIC_API_KEY="your-key"
export ANTHROPIC_BASE_URL="https://api.minimax.chat/v1"
export ANTHROPIC_MODEL="MiniMax-M2.7-highspeed"
```

### 15.2 启动方式

```bash
# 方式1: 直接启动Web服务器
python web/server.py --port 8080 --host 0.0.0.0

# 方式2: 通过CLI启动
python brachybot.py --server --port 8080

# 方式3: 后台启动
nohup python web/server.py > /tmp/flask.log 2>&1 &

# 方式4: 使用setsid (推荐，不会被终端关闭)
setsid python web/server.py < /dev/null > /tmp/flask.log 2>&1 &
disown
```

### 15.3 访问

```
Web界面: http://localhost:8080
API文档: http://localhost:8080/api/status
```

### 15.4 重启服务器

```bash
# 停止
pkill -f "python web/server"

# 启动
cd /home/lht/snap/brachyplan/BrachyBot
setsid python web/server.py < /dev/null > /tmp/flask.log 2>&1 &
disown
```

---

## 16. 已知问题与注意事项

### 16.1 CTV分割问题

**问题**: 默认CTV分割返回0体积

**原因**: 
- nnU-Net模型权重缺失 (`plans/seg/pancreatic_tumor/` 不存在)
- 系统回退到简单阈值方法，但阈值无法检测肿瘤

**解决**:
1. 使用VoCo版本: 告诉AI "用voco_pancreatic模型分割"
2. 下载nnU-Net权重放到 `plans/seg/` 目录
3. 代码已修改为默认使用VoCo版本

### 16.2 分割后不显示

**问题**: 分割完成后Viewer不显示overlay

**原因**: 前端默认`showCTV`和`showOAR`都是false

**解决**: 代码已修改，分割完成后自动：
1. 勾选OAR/CTV复选框
2. 切换到overlay显示模式
3. 刷新所有viewer

### 16.3 流式输出

**问题**: LLM输出时前端卡住

**原因**: MiniMax流式API返回tool_calls时，需要累积所有块

**解决**: 
- router.py添加了fallback处理
- minimax_llm.py实现了逐块累积后yield final事件

### 16.4 十字线坐标精度

**问题**: 鼠标轻微移动导致十字线大幅跳动

**原因**: Sagittal/Coronal的Z轴重采样坐标转换错误

**解决**: 修正了坐标转换（除以resampleRatio而非乘）

### 16.5 JSON解析

**问题**: tool_calls参数解析失败

**原因**: LLM返回的参数可能是dict或string格式

**解决**: 代码已支持两种格式：
```python
if isinstance(args, dict):
    tool_args = args
else:
    tool_args = json.loads(args)
```

### 16.6 CT方向

**问题**: CT图像方向不一致

**解决**: 使用SimpleITK DICOMOrient转LPI方向
```python
ct_image = sitk.DICOMOrient(ct_image, 'LPI')
```

### 16.7 各向异性显示

**问题**: Sagittal/Coronal显示变形

**原因**: CT spacing (0.68, 0.68, 5.0) 导致Z轴拉伸

**解决**: 前端重采样Z轴到各向同性
```javascript
resampleRatio = spacingZ / spacingY;  // 5.0 / 0.68 ≈ 7.35
height = Math.round(Z * resampleRatio);
```

### 16.8 服务器进程管理

**问题**: 服务器被终端关闭

**解决**: 使用setsid启动
```bash
setsid python web/server.py < /dev/null > /tmp/flask.log 2>&1 &
disown
```

---

## 17. 开发指南

### 17.1 添加新工具

```python
# 1. 在tool_factory/下创建新文件
# tool_factory/my_tool/__init__.py

from tool_factory import BaseTool, ToolResult

class MyTool(BaseTool):
    @property
    def name(self) -> str:
        return "my_tool"
    
    @property
    def description(self) -> str:
        return "My custom tool"
    
    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "param1": {"type": "string", "description": "Parameter 1"}
            },
            "required": ["param1"]
        }
    
    def _execute(self, **kwargs) -> ToolResult:
        param1 = kwargs.get("param1")
        
        # 工具逻辑
        result = do_something(param1)
        
        return ToolResult(
            success=True,
            data=result,
            message="Tool executed successfully"
        )

# 2. 注册到AgenticSys.py
from tool_factory.my_tool import MyTool

# 在__init__中添加
self.tools["my_tool"] = MyTool()

# 3. 更新toolset.json
{
    "id": 41,
    "name": "my_tool",
    "type": "custom",
    "category": "utility",
    "description": "My custom tool",
    "parameters": {
        "param1": {"type": "string"}
    }
}
```

### 17.2 添加新LLM提供商

```python
# brain/providers/my_llm.py

from brain.core.base import BaseLLM, LLMResponse

class MyLLMProvider(BaseLLM):
    def __init__(self, api_key, model="default"):
        self.api_key = api_key
        self.model = model
    
    def chat_messages(self, messages, tools=None) -> LLMResponse:
        # 调用API
        response = call_my_api(messages, tools)
        
        return LLMResponse(
            content=response.text,
            tool_calls=response.tool_calls,
            usage=response.usage
        )
    
    def chat_messages_stream(self, messages, tools=None):
        # 流式输出
        for chunk in stream_my_api(messages, tools):
            yield chunk

# 注册到router.py
from brain.providers.my_llm import MyLLMProvider

providers["my_llm"] = MyLLMProvider
```

### 17.3 添加新技能

```python
# skills/my_skill.py

from skills.skill_base import Skill

class MySkill(Skill):
    @property
    def name(self) -> str:
        return "my_skill"
    
    @property
    def triggers(self) -> list:
        return ["我的技能", "my skill"]
    
    def execute(self, agent, **kwargs):
        # 技能逻辑
        result = agent.chat("执行我的技能")
        return result

# 注册
from skills.my_skill import MySkill
skill_registry.register(MySkill())
```

### 17.4 测试

```bash
# 运行所有测试
pytest tests/

# 运行特定测试
pytest tests/test_brain_system.py

# 运行带覆盖率
pytest --cov=. tests/
```

### 17.5 代码风格

```python
# 遵循PEP 8
# 使用类型提示
# 编写docstring
# 避免全局变量

# 示例
def my_function(param1: str, param2: int = 10) -> dict:
    """
    函数描述
    
    Args:
        param1: 参数1描述
        param2: 参数2描述，默认10
    
    Returns:
        dict: 返回值描述
    
    Raises:
        ValueError: 异常描述
    """
    pass
```

---

## 附录A: 术语表

| 术语 | 英文 | 描述 |
|------|------|------|
| CTV | Clinical Target Volume | 临床靶区 |
| OAR | Organ at Risk | 危及器官 |
| GTV | Gross Tumor Volume | 大体肿瘤区 |
| PTV | Planning Target Volume | 计划靶区 |
| DVH | Dose-Volume Histogram | 剂量-体积直方图 |
| V100 | Volume at 100% | 100%处方剂量覆盖体积 |
| D90 | Dose to 90% | 覆盖90%体积的剂量 |
| HI | Homogeneity Index | 均匀性指数 |
| CI | Conformity Index | 适形性指数 |
| TG-43 | Task Group 43 | AAPM剂量计算协议 |
| QUANTEC | Quantitative Analyses of Normal Tissue Effects | 正常组织效应量化分析 |
| VoCo | Visual Context | 视觉上下文学习 |
| nnU-Net | No-New U-Net | 自配置U-Net |
| LATS | Language Agent Tree Search | 语言Agent树搜索 |
| MCTS | Monte Carlo Tree Search | 蒙特卡洛树搜索 |
| SOP | Standard Operating Procedure | 标准操作程序 |
| RAG | Retrieval-Augmented Generation | 检索增强生成 |

---

## 附录B: 文件大小参考

```
BrachyBot/
├── VoCo/                  # ~2GB (36个模型权重)
├── dose_pre/              # ~24MB (CNN剂量模型)
├── uploads/               # ~50-200MB per CT
├── memory/data/           # ~10MB (记忆数据)
├── skills/data/           # ~1MB (技能注册)
└── web/app/index.html     # ~200KB (前端)
```

---

## 附录C: 端口和进程管理

```bash
# 查看服务器状态
ps aux | grep "python web/server" | grep -v grep

# 查看端口占用
ss -tlnp | grep 8080

# 强制停止
pkill -f "python web/server"

# 查看日志
tail -f /tmp/flask.log

# 重启
pkill -f "python web/server" && sleep 1 && \
cd /home/lht/snap/brachyplan/BrachyBot && \
setsid python web/server.py < /dev/null > /tmp/flask.log 2>&1 &
disown
```

---

## 附录D: 常见问题

### Q1: 为什么CTV分割返回0体积？

**A**: 可能原因：
1. nnU-Net模型权重缺失 - 使用VoCo版本
2. 未指定肿瘤类型 - 告诉AI具体癌症类型
3. 图像中无明显肿瘤 - 尝试其他分割工具

### Q2: 为什么分割后Viewer不显示？

**A**: 检查：
1. Display模式是否为"CT + Label"或"Label Only"
2. OAR/CTV复选框是否勾选
3. 刷新页面重试

### Q3: 为什么服务器显示offline？

**A**: 检查：
1. 服务器进程是否在运行
2. 端口8080是否被占用
3. 查看日志是否有错误

### Q4: 如何更换LLM提供商？

**A**: 
```bash
export BRACHY_LLM_PROVIDER="openai"
export OPENAI_API_KEY="your-key"
```

### Q5: 如何添加新的癌症类型？

**A**: 
1. 在`tool_factory/CTV_seg/`添加新工具
2. 在`__init__.py`注册到TOOL_REGISTRY
3. 更新toolset.json
4. 创建对应的技能文件

---

**文档版本**: 1.0.0  
**最后更新**: 2026-05-27  
**维护者**: Haitao-Lee
