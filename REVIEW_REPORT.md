# AI-BrachyBot 项目全面审查报告

**审查日期**: 2026-05-15
**项目路径**: `/home/lht/snap/brachyplan/BrachyBot`

---

## 一、项目概述

**AI-BrachyBot** 是一个由 LLM 驱动的近距离放疗（brachytherapy）计划系统，支持术前规划和术中实时重规划。项目采用 Agent 架构，集成了基于深度学习的肿瘤/OAR分割（VoCo、nnU-Net）、剂量计算、高质量种子置入优化等功能。

---

## 二、系统架构总览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           AI-BrachyBot                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────┐     ┌─────────────────────────────────────────┐  │
│  │  Web Interface  │     │          BrachyAgent                    │  │
│  │  (index.html)   │────▶│  ┌─────────────┐  ┌─────────────────┐  │  │
│  │  Flask API      │     │  │ AgentMemory │  │  ToolRegistry   │  │  │
│  │  (server.py)    │     │  └─────────────┘  └─────────────────┘  │  │
│  └─────────────────┘     │                                         │  │
│                         │  ┌─────────────────────────────────────┐ │  │
│  ┌─────────────────┐     │  │           Brain System              │ │  │
│  │  CLI / Chat     │     │  │  ┌─────────┐ ┌──────┐ ┌─────────┐ │ │  │
│  │  (brachybot.py) │────▶│  │  │Router   │ │Decider│ │Executor │ │ │  │
│  └─────────────────┘     │  │  └─────────┘ └──────┘ └─────────┘ │ │  │
│                          │  │  LLMs: OpenAI/Claude/DeepSeek/...  │ │  │
│                          │  │  RAG: Dose Constraints Knowledge   │ │  │
│                          │  └─────────────────────────────────────┘ │  │
│                          └─────────────────────────────────────────┘  │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                      Tool Factory                                 │  │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ │  │
│  │  │  CTV_seg   │ │  OAR_seg   │ │ dose_engine │ │ dose_eval   │ │  │
│  │  │ (12 tools) │ │ (3 tools)  │ │  (2 tools) │ │ (5 tools)  │ │  │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘ │  │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ │  │
│  │  │ seed__plan  │ │ seed_seg   │ │ traj_plan   │ │   output    │ │  │
│  │  │ (3 tools)  │ │ (1 tool)  │ │ (2 tools)  │ │ (3 tools)  │ │  │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘ │  │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐                  │  │
│  │  │plan_quality│ │    image_   │ │             │                  │  │
│  │  │ (3 tools)  │ │  processing │ │   skills    │                  │  │
│  │  └─────────────┘ └─────────────┘ └─────────────┘                  │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                     外部依赖模块                                   │  │
│  │  /home/lht/snap/brachyplan/core.py         (核心算法)             │  │
│  │  /home/lht/snap/brachyplan/utilizations.py  (剂量计算工具)        │  │
│  │  /home/lht/snap/brachyplan/utilizations_promax.py (增强工具)      │  │
│  │  /home/lht/snap/brachyplan/BrachyBot/VoCo/ (VoCo微调权重, 18个)  │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 三、术前规划工作流（Pre-operative Planning）

```
                          开始术前规划
                                │
                                ▼
                    ┌───────────────────────┐
                    │  Step 1: 加载CT影像   │
                    │  sitk.ReadImage(ct)   │
                    └───────────┬───────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │  Step 2: CTV分割      │
                    │  ctv_segmentation     │
                    │  (12个工具可选)        │
                    │  ┌─────────────────┐  │
                    │  │  nnU-Net模型    │  │
                    │  │  (需单独训练)    │  │
                    │  ├─────────────────┤  │
                    │  │  VoCo微调模型    │  │
                    │  │  6种肿瘤类型    │  │
                    │  │  ✓ 权重已就位   │  │
                    │  └─────────────────┘  │
                    └───────────┬───────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │  Step 3: OAR分割      │
                    │  oar_segmentation     │
                    │  (3个工具可选)        │
                    │  • VoCo 104器官       │
                    │  • TotalSegmentator   │
                    │  • 胰腺专用OAR        │
                    └───────────┬───────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │  Step 4: 构建辐射体积  │
                    │  CTV=1, OAR=3, BG=0   │
                    └───────────┬───────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │  Step 5: 轨迹规划      │
                    │  trajectory_planning   │
                    │  ┌─────────────────┐  │
                    │  │ trajectory_init  │  │
                    │  │ (方向采样)       │  │
                    │  ├─────────────────┤  │
                    │  │ trajectory_refine│  │
                    │  │ (质量过滤)       │  │
                    │  └─────────────────┘  │
                    └───────────┬───────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │  Step 6: 种子规划      │
                    │  seed_planning        │
                    │  模式: rule_based/rl  │
                    │  ┌─────────────────┐  │
                    │  │ CNN剂量引擎     │  │
                    │  │ (myDoseNet)    │  │
                    │  ├─────────────────┤  │
                    │  │ 高斯剂量引擎    │  │
                    │  │ (解析模型)      │  │
                    │  └─────────────────┘  │
                    └───────────┬───────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │  Step 7: 剂量评估      │
                    │  dose_evaluation      │
                    │  V100, D90, PlanScore │
                    │  OAR约束检查          │
                    └───────────┬───────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │  Step 8: 输出结果     │
                    │  DICOM RT / 报告      │
                    └───────────┬───────────┘
                                │
                                ▼
                          规划完成 ✓
```

---

## 四、术中重规划工作流（Intra-operative Replanning）

```
                      开始术中重规划
                            │
                            ▼
              ┌─────────────────────────────┐
              │ 加载术中CT/CBCT影像         │
              └─────────────┬───────────────┘
                            │
                            ▼
              ┌─────────────────────────────┐
              │ 检测已植入种子位置           │
              │ seed_segmentation           │
              │ (强度阈值+连通域分析)        │
              └─────────────┬───────────────┘
                            │
                            ▼
              ┌─────────────────────────────┐
              │ 计算种子偏移统计            │
              │ deviation_stats              │
              │ max_deviation_mm            │
              │ mean_deviation_mm           │
              └─────────────┬───────────────┘
                            │
                            ▼
                    ┌───────────────────┐
                    │ 偏移 > 阈值?      │
                    │ threshold=2.0mm   │
                    └───────┬───────────┘
                            │
              ┌─────────────┴─────────────┐
              │ YES                       │ NO
              ▼                           ▼
    ┌─────────────────┐         ┌─────────────────┐
    │ 触发重规划      │         │ 继续治疗        │
    │                 │         │ (无需调整)      │
    │ 1.计算已递送剂量│         └─────────────────┘
    │ 2.调整辐射体积  │
    │ 3.重新轨迹规划  │
    │ 4.种子再优化    │
    │ 5.生成新计划    │
    └─────────────────┘
```

---

## 五、Tool Factory 详细结构

```
tool_factory/
│
├── CTV_seg/                    # CTV/肿瘤分割 (12个工具)
│   ├── __init__.py
│   │   CTVSegmentationTool     ← 统一入口
│   │
│   ├── pancreatic_tumor.py    # nnU-Net (需训练权重)
│   ├── pancreatic_tumor_voco.py  # VoCo (✓ PANORAMA权重就位)
│   │
│   ├── liver_tumor.py         # nnU-Net (需训练权重)
│   ├── liver_tumor_voco.py     # VoCo (✓ 3D-IRCADb权重就位)
│   │
│   ├── kidney_tumor.py        # nnU-Net (需训练权重)
│   ├── kidney_tumor_voco.py    # VoCo (✓ KiPA权重就位)
│   │
│   ├── prostate_tumor.py      # nnU-Net (需训练权重)
│   ├── prostate_tumor_voco.py  # VoCo (✓ Amos-MR权重就位, MRI)
│   │
│   ├── lung_tumor.py          # nnU-Net (需训练权重)
│   ├── lung_tumor_voco.py      # VoCo (✓ MSD Lung权重就位)
│   │
│   ├── colon_tumor_voco.py    # VoCo (✓ MSD Colon权重就位)
│   │
│   ├── head_neck_tumor.py    # nnU-Net (需训练权重)
│   │
│   └── voco_tumor_segmentation.py  # 旧版统一VoCo (已弃用)
│
├── OAR_seg/                    # OAR/危及器官分割 (3个工具)
│   ├── __init__.py
│   │   OARSegmentationTool    ← 统一入口
│   ├── pancreatic_oar.py       # 胰腺专用OAR
│   ├── totalsegmentator_oar.py # TotalSegmentator (104器官)
│   └── voco_total_segmentation.py  # VoCo 104器官分割
│
├── dose_engine/                # 剂量计算引擎
│   ├── __init__.py
│   │   DoseEngineTool         ← 统一入口 (gaussian/cnn)
│   ├── gaussian_dose_engine.py # 解析高斯模型 (✓ 可用)
│   └── cnn_dose_engine.py     # CNN剂量计算 (✓ 可用)
│
├── dose_eval/                  # 剂量评估 (5个工具)
│   ├── __init__.py
│   │   DoseEvaluationTool     ← 统一入口
│   ├── vx_metrics.py
│   ├── dx_metrics.py
│   ├── absolute_dose_metrics.py
│   ├── dvh_calculation.py
│   └── comprehensive_dose_evaluation.py
│
├── seed__plan/                 # 种子置入规划 (3个工具)
│   ├── __init__.py
│   │   SeedPlanningTool       ← 统一入口
│   ├── seed_planning.py       # 统一入口
│   ├── seed_planning_rule_based.py  # 规则基础
│   └── seed_planning_rl.py    # 强化学习
│
├── seed_seg/                   # 种子检测 (1个工具)
│   └── __init__.py
│       SeedSegmentationTool   ← 术中种子位置检测
│
├── traj_plan/                  # 轨迹规划 (2个工具)
│   ├── __init__.py
│   │   TrajectoryPlanningTool ← 统一入口
│   ├── trajectory_init.py     # 初始化(方向采样)
│   └── trajectory_refine.py  # 质量过滤
│
├── plan_quality/               # 计划质量评估
│   ├── __init__.py
│   ├── plan_quality_scorer.py
│   ├── oar_constraint_checker.py
│   └── plan_refinement.py
│
├── image_processing/            # 影像预处理
│   ├── __init__.py
│   ├── image_loader.py
│   └── image_preprocessor.py
│
└── output/                     # 输出/导出
    ├── __init__.py
    ├── dose_exporter.py
    ├── dicom_rt_exporter.py
    └── report_generator.py
```

---

## 六、Brain System 结构

```
brain/
├── __init__.py                 # 统一导出
│
├── core/
│   ├── __init__.py
│   ├── base.py                # BaseLLM, BaseDecider, LLMResponse, PlanStep
│   ├── router.py               # LLMRouter (多LLM提供商路由)
│   ├── tool_registry.py       # ToolRegistry (brain专用)
│   └── toolset.json           # 工具集描述
│
├── providers/                 # LLM提供商 (14个)
│   ├── __init__.py
│   ├── openai_llm.py          # OpenAI GPT
│   ├── anthropic_llm.py       # Claude
│   ├── deepseek_llm.py        # DeepSeek
│   ├── glm_llm.py             # ChatGLM
│   ├── local_llm.py           # vLLM / LMDeploy
│   ├── ollama_llm.py          # Ollama
│   ├── qwen_llm.py            # Qwen
│   ├── kimi_llm.py            # Kimi
│   ├── minimax_llm.py         # MiniMax
│   ├── gemini_llm.py          # Gemini
│   ├── groq_llm.py            # Groq
│   ├── grok_llm.py            # Grok
│   ├── mimo_llm.py            # Mimo
│   ├── tencent_llm.py         # Tencent Hunyuan
│   └── openrouter_llm.py      # OpenRouter
│
├── deciders/                  # 决策模块
│   ├── __init__.py
│   ├── planner_decider.py      # PlannerDecider (工具链规划)
│   ├── clinical_decider.py     # ClinicalDecider (临床决策)
│   └── quality_decider.py     # QualityDecider (质量评分)
│
├── execution/
│   ├── __init__.py
│   ├── plan_executor.py       # PlanExecutor (执行工具链)
│   └── case_executor.py       # CaseExecutor (案例执行)
│
├── integration/
│   ├── __init__.py
│   ├── integration.py          # BrainToolBridge (脑-工具桥接)
│   └── integration_example.py
│
├── knowledge/
│   ├── __init__.py
│   └── rag.py                 # SimpleRAG, DoseRAG (知识检索)
│
├── prompts/
│   ├── __init__.py
│   └── role_prompts.py        # Planner/Clinical/Quality提示词
│
└── demos/
    ├── __init__.py
    └── demo.py
```

---

## 七、问题修复清单

### ✅ 已修复问题

#### 修复 #1: integration.py 陈旧导入路径
- **问题**: `brain/integration/integration.py` 中的工厂函数导入了不存在的模块路径
  - `tool_factory.segmentation.ctv.pancreatic_ct` (不存在)
  - `tool_factory.segmentation.oar.totalsegmentator_oar` (不存在)
  - `tool_factory.seed_planning.unified` (不存在)
- **修复**: 重写所有工厂函数，改为正确导入现有模块
- **影响文件**: `brain/integration/integration.py`
- **状态**: ✅ 已修复

#### 修复 #2: DoseEvaluationTool `structure_type` 未传递
- **问题**: `DoseEvaluationTool._execute()` 调用 `ComprehensiveDoseEvaluationTool` 时未设置 `structure_type={"CTV": "target"}`，导致 `plan_score` 始终为 0
- **修复**: 添加 `structure_type` 参数传递，并修复 `metrics` 提取逻辑
- **影响文件**: `tool_factory/dose_eval/__init__.py`
- **状态**: ✅ 已修复

#### 修复 #3: AgenticSys.py 多余导入
- **问题**: `run_preoperative_plan()` 导入了不存在的 `data_preprocess` 模块
  ```python
  from data_preprocess import DataPreprocessor, PatientData  # 不存在!
  ```
- **修复**: 删除该无用导入
- **影响文件**: `AgenticSys.py`
- **状态**: ✅ 已修复

---

## 八、现有问题与限制

### ⚠️ 限制（不属于bug）

#### L1: nnU-Net 权重未训练
- **描述**: CTV_seg 中的 nnU-Net 模型 (`pancreatic_tumor.py` 等) 需要在 `plans/seg/<tumor>/` 目录下有训练好的 nnU-Net 权重
- **当前状态**: 权重目录不存在
- **影响**: nnU-Net 分割工具会回退到简单的 HU 阈值分割
- **解决**: 需要单独完成 nnU-Net 训练流程

#### L2: VoCo 前列腺模型为 MRI 模态
- **描述**: `prostate_tumor_voco.py` 使用 MRI 强度范围 (`A_MIN=0, A_MAX=3000`)，与其他 CT 模型不同 (`A_MIN=-175, A_MAX=250`)
- **影响**: 如果输入 CT 影像，MRI 模型可能无法正确分割
- **建议**: 前列腺分割应优先使用 CT 模型或单独训练 CT 版 VoCo

#### L3: 缺少 `data_preprocess` 模块
- **描述**: `AgenticSys.py` 第385行原本尝试导入 `data_preprocess`，但该模块不存在（已删除无用导入）
- **实际影响**: 无（该导入未被使用）

---

## 九、文件路径速查

| 功能 | 文件路径 |
|------|---------|
| 主Agent | `AgenticSys.py` |
| CLI入口 | `brachybot.py` |
| Web服务 | `web/server.py` |
| 前端界面 | `web/app/index.html` |
| VoCo权重 | `VoCo/<数据集>/model_voco*.pt` |
| 剂量模型 | `dose_pre/dose_model.pth` |
| 外部核心 | `/home/lht/snap/brachyplan/core.py` |
| 外部工具 | `/home/lht/snap/brachyplan/utilizations*.py` |

---

## 十、VoCo 模型权重清单

| 肿瘤类型 | 权重路径 | 数据集 | 状态 |
|---------|---------|-------|------|
| 胰腺 | `VoCo/PANORAMA/model_voco.pt` | PANORAMA | ✅ 就位 (284.8MB) |
| 肝脏 | `VoCo/3D-IRCADb/model_voco_74.27.pt` | 3D-IRCADb | ✅ 就位 (284.8MB) |
| 结肠 | `VoCo/colon/model_voco_42.57.pt` | MSD Colon | ✅ 就位 (284.8MB) |
| 肾脏 | `VoCo/Kipa/model_voco.pt` | KiPA22 | ✅ 就位 (284.8MB) |
| 肺 | `VoCo/Lung/model_voco_75.74.pt` | MSD Lung | ✅ 就位 (284.8MB) |
| 前列腺 | `VoCo/Amos-MR/model_voco_79.24.pt` | Amos-MR (MRI) | ✅ 就位 (284.8MB) |

---

## 十一、快速启动命令

```bash
# 术前规划
python brachybot.py --ct path/to/ct.nii.gz --mode rule_based

# 交互式对话
python brachybot.py --chat

# 启动Web服务
python brachybot.py --server --port 8080

# VoCo工具独立使用
python -m tool_factory.CTV_seg.pancreatic_tumor_voco --image ct.nii.gz --output tumor.nii.gz
```

---

## 十二、总结

**AI-BrachyBot** 是一个功能完整的 LLM 驱动近距离放疗计划系统，架构清晰，模块化程度高。主要修复了 3 个关键问题（integration.py陈旧导入、DoseEvaluationTool结构类型未传递、无用data_preprocess导入）。所有6个VoCo肿瘤模型权重已就位，系统可正常初始化运行。nnU-Net模型需单独训练，VoCo模型无需额外训练可直接使用。