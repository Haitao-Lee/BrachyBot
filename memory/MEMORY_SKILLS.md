# 🧠 BrachyBot Memory & Skills System

> 自进化系统：让 BrachyBot 通过与用户的交互学习，形成更符合用户习惯的规划和操作方式。

---

## 📋 概述

BrachyBot 具备**自进化能力**，能够：

1. **记忆交互历史** — 记录所有对话、工具调用、参数选择
2. **学习用户偏好** — 从历史中提取常用的参数组合和工具序列
3. **生成个性化技能** — 基于学习到的模式，自动生成新的 skills
4. **持续优化** — 每次交互后更新偏好和技能的成功率

---

## 🧠 Memory System (`memory/`)

### 交互记忆 (`interaction_memory.py`)

记录完整的交互历史：

```python
from memory import InteractionMemory

memory = InteractionMemory(session_id="patient_001")

# 记录对话
memory.add_turn("user", "为胰腺癌患者生成治疗计划")

# 记录工具调用
memory.add_tool_call(
    tool_name="ctv_segmentation",
    inputs={"tumor_type": "pancreatic"},
    outputs={"success": True},
    success=True,
    execution_time=2.3
)

# 获取统计信息
stats = memory.get_tool_usage_stats()
print(stats)  # {'ctv_segmentation': 5, 'seed_planning': 3, ...}

# 提取工具调用模式
patterns = memory.extract_tool_patterns(min_occurrences=3)
print(patterns)  # [['ctv_segmentation', 'oar_segmentation', 'trajectory_planning'], ...]
```

### 参数偏好学习 (`skill_learner.py`)

从交互历史中学习用户习惯：

```python
from memory import SkillLearner

learner = SkillLearner(memory)

# 学习参数偏好
prefs = learner.learn_parameter_preferences()
print(prefs)
# {
#     'seed_planning': {
#         'mode': {'value': 'rl', 'confidence': 0.8},
#     },
#     'dose_engine': {
#         'engine': {'value': 'cnn', 'confidence': 0.6},
#     }
# }

# 基于交互学习新技能
new_skills = learner.learn_from_interactions(min_occurrences=3)

# 获取下一个推荐工具
next_tool = learner.suggest_next_tool()
print(next_tool)  # 'dose_evaluation'
```

### 用户偏好存储 (`preference_store.py`)

持久化存储用户偏好：

```python
from memory import PreferenceStore

store = PreferenceStore(user_id="doctor_wang")

# 设置偏好
store.set("planning", "default_mode", "rl", confidence=0.9, source="learned")

# 获取偏好
mode = store.get("planning", "default_mode")
print(mode)  # 'rl'

# 批量应用偏好到工具参数
params = {"mode": None, "engine": None}
applied = store.apply_to_tool_params("seed_planning", params)
print(applied)  # {'mode': 'rl', 'engine': 'gaussian'}
```

---

## 🎯 Skills System (`skills/`)

### 技能注册与管理 (`skill_base.py`)

Skills 是可复用的行为单元，包含工具序列和默认参数：

```python
from skills import SkillRegistry

registry = SkillRegistry()

# 获取技能
skill = registry.get("standard_planning")
print(skill.tool_sequence)
# ['ctv_segmentation', 'oar_segmentation', 'trajectory_planning', 'seed_planning', 'dose_engine', 'dose_evaluation']

# 按触发词查找
matches = registry.find_by_trigger("胰腺癌治疗计划")
print(matches[0].name)  # 'standard_planning'

# 记录使用结果
registry.record_use("standard_planning", success=True)
```

### 预设技能

| 技能 | 触发词 | 工具序列 |
|------|--------|---------|
| `standard_planning` | 规划、标准计划、治疗计划 | CTV→OAR→轨迹→种子→剂量→评估 |
| `rl_planning` | RL、强化学习、复杂 | CTV→OAR→轨迹→种子(RL)→CNN剂量→评估 |
| `quick_planning` | 快速、预览 | CTV→轨迹→种子→Gaussian剂量 |
| `pancreas_segmentation` | 胰腺、pancreas | CTV(胰腺) + OAR(胰腺) |
| `prostate_segmentation` | 前列腺、prostate | CTV(前列腺) + OAR(通用) |
| `detailed_evaluation` | 详细评估、DVH | 评估→DVH→约束→评分→报告 |

---

## 🔄 自进化流程

```
用户交互
    │
    ▼
┌─────────────────┐
│ InteractionMemory │ 记录所有交互
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  SkillLearner   │ 分析模式
│  - 工具序列     │ 学习参数偏好
│  - 触发词       │ 生成新技能
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│PreferenceStore │ 更新偏好
│  SkillRegistry  │ 更新/创建技能
└────────┬────────┘
         │
         ▼
    进化完成
```

---

## 💡 使用示例

### 在 BrachyAgent 中自动使用

```python
from AgenticSys import BrachyAgent

agent = BrachyAgent(session_id="doctor_li")

# 正常使用
agent.run_preoperative_plan(ct_path="ct.nii.gz", mode="rule_based")

# 获取推荐的技能
skill = agent.get_recommended_skill("为前列腺癌患者生成治疗计划")
if skill:
    print(f"推荐使用: {skill['name']}")
    print(f"工具序列: {' -> '.join(skill['tool_sequence'])}")

# 触发自进化
evolution = agent.evolve_from_interactions()
print(f"新学会 {len(evolution['new_skills'])} 个技能")
```

### 手动触发进化

```python
# 经过多次交互后，手动触发进化
agent.evolve_from_interactions()

# 查看当前技能状态
for skill in agent.skill_registry.list_skills():
    print(f"{skill['name']}: 成功率 {skill['success_rate']:.0%}, 使用 {skill['usage_count']}次")
```

---

## 📁 数据存储

```
memory/
├── data/
│   ├── default/           # 默认 session 数据
│   │   ├── session.json   # 交互历史
│   │   ├── preferences.json  # 用户偏好
│   │   └── skills.json    # 学习到的技能
│   └── {session_id}/      # 各 session 数据
skills/
└── data/
    └── skills_registry.json  # 技能注册表
```

---

## 🎓 进化策略

| 策略 | 说明 |
|------|------|
| **最小出现次数** | 工具序列出现 ≥3 次才学习为技能 |
| **成功率衰减** | 技能使用失败，成功率 -10% |
| **成功率提升** | 技能使用成功，成功率 +5% |
| **置信度阈值** | 偏好置信度 ≥0.7 才自动应用 |
| **技能选择** | 按 `成功率 × 使用次数` 排序推荐 |

---

*BrachyBot Memory & Skills System - 让 AI 更懂你的习惯*