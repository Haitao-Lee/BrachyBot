# DataMind × BrachyBot 集成分析报告

**分析日期:** 2026-06-03
**分析目标:** 研究 DataMind (zjunlp/DataMind) 的可取之处，提出适用于 BrachyBot 的改进方案
**DataMind 来源:** https://github.com/zjunlp/DataMind
**论文:** ICLR 2026 / AAAI 2026 / KDD 2026

---

## 一、项目背景对比

### 1.1 DataMind 概述

DataMind 是浙江大学 NLP 实验室（zjunlp）开发的**开源 LLM 数据分析 Agent** 框架，发表于 ICLR/AAAI/KDD 2026。核心贡献：

| 论文 | 会议 | 核心贡献 |
|------|------|---------|
| Scaling Generalist Data-Analytic Agents | ICLR 2026 | DataMind-12K 数据集 + SFT/RL 训练方案 |
| Why Do Open-Source LLMs Struggle with Data Analysis? | AAAI 2026 | 系统性实证分析，发现规划质量是决定性因素 |
| Rewarding the Scientific Process | KDD 2026 | 过程奖励建模（Process Reward Model） |
| LongDS-Bench | 2026-05 | 长序列多步骤分析基准 |

**核心成果：** DataMind-14B 在多个数据分析基准上平均得分 71.16%，超越 DeepSeek-V3.1 和 GPT-5。

### 1.2 BrachyBot 概述

BrachyBot 是一个**闭环自进化 AI 近距离治疗计划系统**，核心架构：

| 模块 | 功能 | 技术 |
|------|------|------|
| AgenticSys | LLM 驱动决策 | Function Calling, 15 家 LLM Provider |
| 分层记忆 (L0-L4) | 上下文管理 | Meta Rules → Insight Index → Global Facts → Skills → Archive |
| ReflexionEngine | 轨迹反思 | Actor/Evaluator/Self-Reflection Loop |
| SkillCrystallizer | 技能结晶 | Trajectory → SOP → Executable Skill |
| Multi-Agent Critique | 安全审查 | 多 Agent 临床评审 |
| Web UI | 用户交互 | 三栏布局, CT Viewer, Chat, Analysis |

### 1.3 关键差异

| 维度 | DataMind | BrachyBot |
|------|----------|-----------|
| **领域** | 通用数据分析 | 近距离治疗（医学影像） |
| **Agent 模式** | 代码执行 Agent | Tool Chain Agent |
| **训练方式** | SFT + RL 训练自有模型 | 使用现成 LLM API |
| **进化方式** | 数据合成 + 重新训练 | Reflexion + 技能结晶 |
| **评估方式** | Pass@3 + LLM Judge | 关键词匹配 |
| **Benchmark** | 自动化生成 | 人工编写 |

---

## 二、DataMind 核心创新深度解析

### 2.1 细粒度任务分类 + 递进式组合

**DataMind 的方法：**

```
Task Taxonomy (三级分类):
  ┌─ 数据理解 (Data Understanding)
  │   ├─ 文件格式识别
  │   ├─ Schema 解析
  │   └─ 数据质量检查
  ├─ 代码生成 (Code Generation)
  │   ├─ 单步查询
  │   ├─ 多步转换
  │   └─ 复杂聚合
  └─ 策略规划 (Strategic Planning)
      ├─ 分析路径设计
      ├─ 异常处理
      └─ 结果验证

Recursive Composition (递归组合):
  Level 1: 单一子任务 (e.g., "读取 CSV")
  Level 2: 2-3 个子任务组合 (e.g., "读取 + 清洗 + 统计")
  Level 3: 带约束的多步任务 (e.g., "处理缺失值 + 异常检测 + 生成报告")
  Level 4: 完整分析流水线 (e.g., 从数据到洞察的端到端流程)
```

**核心发现：**
- 任务分类的粒度直接影响数据多样性
- 递归组合可以指数级扩大任务空间
- 难度递进比随机组合更有效

### 2.2 过程奖励建模（Process Reward Model）

**DataMind 的方法：**

传统评估只看最终结果（outcome-only reward）：
```
Answer == Gold → Reward = 1
Answer != Gold → Reward = 0
```

DataMind 引入过程级奖励（process-level reward）：
```
Step 1: 数据加载 → 评估 (格式是否正确？)
Step 2: 数据清洗 → 评估 (缺失值处理是否合理？)
Step 3: 分析计算 → 评估 (统计方法是否正确？)
Step 4: 结果输出 → 评估 (结论是否合理？)

Total Reward = Σ(step_reward × step_weight)
```

**核心发现：**
- "Strategic planning quality serves as the primary determinant of model performance"
- 过程奖励比结果奖励更稳定
- 中间步骤的正确性高度预测最终结果

### 2.3 记忆高效 + 稳定的多轮 Rollout

**DataMind 的方法：**

```
问题: 长序列 rollout 中 context 窗口爆炸

解决方案:
1. 滑动窗口: 只保留最近 N 步完整 action
2. 历史压缩: 更早步骤压缩为 summary
3. 关键点保留: 重要决策保持完整记录
4. 错误恢复: 失败步骤的详细记录用于调试
```

**工程实践：**
- 使用独立的 conda 环境运行代码执行
- 异步解释器避免主流程阻塞
- 超时机制防止无限循环

### 2.4 SKILL.md 标准化技能格式

**DataMind 的方法：**

```yaml
---
name: data_analysis_skill
description: "用于数据分析任务的技能，包括数据清洗、统计分析、可视化"
---

## 触发条件
当用户请求数据分析、统计计算、数据可视化时触发。

## 工作流程
1. 识别数据格式和结构
2. 设计分析路径
3. 逐步执行分析
4. 验证结果
5. 生成报告

## 注意事项
- 处理缺失值前先检查数据类型
- 统计检验前检查正态性假设
- 可视化选择取决于数据类型和分析目标
```

每个技能是独立文件夹 + `SKILL.md`，可被 Claude Code / Codex 自动发现。

### 2.5 LLM-as-Judge 评估框架

**DataMind 的方法：**

```
评估层次:
1. 规则验证: 精确匹配 / SQL 结果对比
2. LLM Judge: 用另一个 LLM 评估语义正确性
3. Pass@3: 3 次尝试中至少 1 次通过

Judge Prompt:
"请评估以下数据分析结果是否正确。
 标准答案: {gold}
 学生答案: {prediction}
 请从以下维度评分:
 1. 数据处理正确性 (0-1)
 2. 分析方法合理性 (0-1)
 3. 结论准确性 (0-1)
 总分: (0-1)"
```

### 2.6 LongDS-Bench 长序列基准

**DataMind 的方法：**

专门构建测试 Agent 在长序列多步骤任务中的表现：
- 5-10 步的分析流水线
- 需要跨步骤传递上下文
- 包含错误恢复场景
- 测试 Agent 的规划和纠错能力

**核心发现：** 长序列任务是当前 Agent 的主要失败点。

---

## 三、可借鉴方案详细设计

### 3.1 方案 A：细粒度任务分类 + 递进式 Benchmark 生成

#### 3.1.1 现状分析

BrachyBot 当前的 benchmark 是人工编写的 1700+ 用例，存在以下问题：

```
问题 1: 难度分布不均
  简单 (1-10 字):  ████████████████████ 45%
  中等 (10-50字):  ████ 12%  ← 严重不足
  复杂 (50+字):     ████████████ 28%
  临床详述 (100+字): ██████ 15%

问题 2: 缺乏系统化的难度递进
  G001 "你好" → MC001 "前列腺处方剂量" → Q1003 "55岁男性完整病例"
  （难度跳跃大，中间层薄弱）

问题 3: 手工编写成本高
  每个用例需要领域专家手工设计
  难以系统化扩展
```

#### 3.1.2 借鉴方案

**Step 1: 定义 BrachyBot 任务分类树**

```
BrachyBot Task Taxonomy:

├─ L1: 单工具调用 (Single Tool)
│   ├─ CT 信息查询 (spacing, dimensions, HU range)
│   ├─ 简单分割请求 (CTV/OAR)
│   ├─ 剂量参数查询 (D90, V100)
│   └─ 文件操作 (导出, 保存)
│
├─ L2: 两步组合 (Two-Step Combo)
│   ├─ 分割 + 评估 ("分割 CTV 然后检查质量")
│   ├─ 查询 + 对比 ("查一下 OAR 约束然后对比当前计划")
│   ├─ 分析 + 建议 ("分析 DVH 然后给优化建议")
│   └─ 计算 + 验证 ("计算剂量然后验证约束")
│
├─ L3: 多步带约束 (Multi-Step + Constraints)
│   ├─ 完整分割流程 (CTV + OAR + 质量检查)
│   ├─ 计划优化 (发现问题 → 调整参数 → 重新计算)
│   ├─ 紧急场景 (时间压力 + 多约束)
│   └─ 异常处理 (设备报警 + 恢复流程)
│
└─ L4: 完整临床推理 (Full Clinical Reasoning)
    ├─ 端到端计划 (CT → 分割 → 计划 → 评估 → 导出)
    ├─ 多轮对话 (上下文传递 + 偏好学习)
    ├─ 复杂病例 (多并发症 + 个体化方案)
    └─ 跨模态推理 (CT + MRI 融合 + 剂量叠加)
```

**Step 2: 递归组合生成 Benchmark 用例**

```python
# 伪代码: 递归组合生成器
def generate_benchmark_tasks(taxonomy, target_count):
    tasks = []
    
    # Level 1: 原子任务
    for atom in taxonomy.atomic_tasks:
        tasks.extend(generate_variations(atom, count=10))
    
    # Level 2: 两步组合
    for combo in itertools.combinations(taxonomy.atomic_tasks, 2):
        if is_composable(combo):
            tasks.append(compose_task(combo))
    
    # Level 3: 带约束组合
    for base_task in tasks:
        for constraint in taxonomy.constraints:
            tasks.append(add_constraint(base_task, constraint))
    
    # Level 4: 完整流程
    for workflow in taxonomy.workflows:
        tasks.append(generate_workflow_task(workflow))
    
    return sample_diverse(tasks, target_count)
```

**Step 3: 难度自动标注**

```python
def auto_label_difficulty(task):
    """基于特征自动标注难度"""
    features = {
        "input_length": len(task.input),
        "tool_count": estimate_tool_calls(task),
        "constraint_count": count_constraints(task),
        "context_required": requires_context(task),
        "clinical_depth": clinical_depth_score(task),
    }
    
    # 加权评分
    score = sum(features[k] * WEIGHTS[k] for k in features)
    
    if score < 2: return "easy"
    if score < 5: return "medium"
    if score < 8: return "hard"
    return "expert"
```

#### 3.1.3 预期收益

| 指标 | 当前 | 改进后 |
|------|------|--------|
| 中等难度占比 | 12% | 35%+ |
| 难度梯度连续性 | 跳跃式 | 平滑递进 |
| Benchmark 生成成本 | 全手工 | 半自动 |
| 用例多样性 | 依赖专家经验 | 系统化覆盖 |

---

### 3.2 方案 B：LLM-as-Judge 评估框架

#### 3.2.1 现状分析

BrachyBot 当前的评估方式：

```python
# 当前: 关键词匹配
def evaluate_response(response, case):
    keywords = case.get("expected_keywords", [])
    for kw in keywords:
        if kw.lower() in text:
            return "pass"  # 只要出现关键词就通过
    return "fail"
```

**问题：**
- "前列腺" 出现在回答中 ≠ 正确回答了前列腺相关问题
- 无法评估回答的完整性和准确性
- 无法处理同义词和语义等价表达

#### 3.2.2 借鉴方案

**多层评估框架：**

```
Layer 1: 规则层 (Rule-Based) — 快速过滤
  ├─ 关键词初筛 (existing)
  ├─ 禁止词检查 (existing)
  └─ 格式验证 (新增: 检查是否包含剂量数值、单位等)

Layer 2: 语义层 (LLM-as-Judge) — 核心评估
  ├─ 相关性: 回答是否切题？
  ├─ 准确性: 医学信息是否正确？
  ├─ 完整性: 是否覆盖了所有要点？
  ├─ 安全性: 是否有有害建议？
  └─ 可操作性: 建议是否可执行？

Layer 3: 临床规则验证 (Clinical Rules) — 领域校验
  ├─ 剂量范围检查 (e.g., 前列腺 D90 应在 100-180 Gy)
  ├─ OAR 约束验证 (e.g., 膀胱 D2cc < 70 Gy)
  ├─ 适应症匹配 (e.g., Gleason 评分与治疗方式匹配)
  └─ 设备参数合理性 (e.g., Ir-192 源强度范围)

Layer 4: 专家模拟 (Expert Simulation) — 高级评估
  ├─ 模拟物理师审查
  ├─ 模拟医生审查
  └─ 模拟安全委员会审查
```

**LLM Judge Prompt 设计：**

```python
JUDGE_PROMPT = """
你是一位资深的近距离治疗物理师。请评估以下回答的质量。

## 评估维度

1. **准确性** (0-10): 医学信息是否正确？
2. **完整性** (0-10): 是否覆盖了所有关键要点？
3. **安全性** (0-10): 是否有潜在的有害建议？
4. **可操作性** (0-10): 建议是否具体可执行？
5. **专业性** (0-10): 是否使用了正确的术语和概念？

## 评分标准

- 9-10: 优秀，可直接用于临床
- 7-8: 良好，需要小幅修改
- 5-6: 一般，需要重大修改
- 3-4: 较差，基本不可用
- 1-2: 错误，可能有害

## 输出格式

{{
  "accuracy": <score>,
  "completeness": <score>,
  "safety": <score>,
  "actionability": <score>,
  "professionalism": <score>,
  "overall": <weighted_average>,
  "issues": ["问题1", "问题2"],
  "suggestion": "改进建议"
}}

## 问题
{question}

## 参考答案
{reference}

## 待评估回答
{response}
"""
```

**评估流程：**

```python
class LLMJudgeEvaluator:
    def evaluate(self, response, case):
        # Layer 1: 规则层
        rule_result = self.rule_check(response, case)
        if rule_result == "fail":
            return {"verdict": "fail", "score": 0, "layer": "rule"}
        
        # Layer 2: LLM Judge
        llm_result = self.llm_judge(response, case)
        
        # Layer 3: 临床规则
        clinical_result = self.clinical_rule_check(response, case)
        
        # 综合评分
        final_score = (
            rule_result["score"] * 0.1 +
            llm_result["score"] * 0.6 +
            clinical_result["score"] * 0.3
        )
        
        return {
            "verdict": "pass" if final_score >= 7 else "fail",
            "score": final_score,
            "details": {
                "rule": rule_result,
                "llm_judge": llm_result,
                "clinical": clinical_result,
            }
        }
```

#### 3.2.3 预期收益

| 指标 | 关键词匹配 | LLM-as-Judge |
|------|-----------|--------------|
| 评估准确性 | ~60% | ~90%+ |
| 误判率 | 高 | 低 |
| 评估维度 | 单一（关键词） | 多维（5 个维度） |
| 可解释性 | 低 | 高（有详细评分理由） |
| 成本 | 零 | 每次评估调用一次 LLM |

---

### 3.3 方案 C：过程奖励建模（Step-Level Evaluation）

#### 3.3.1 现状分析

BrachyBot 的 ReflexionEngine 在任务完成后做整体反思：

```
当前流程:
  执行完整 trajectory → 成功/失败 → 反思 → 存储 lesson

问题:
  - 只知道最终结果，不知道哪一步出错
  - 无法精确定位失败原因
  - 反思粒度太粗，难以复用
```

#### 3.3.2 借鉴方案

**Step-Level Evaluation Pipeline：**

```
Trajectory = [Step1, Step2, Step3, ..., StepN]

对每个 Step:
  1. 输入: tool_call 的输入参数
  2. 输出: tool_call 的执行结果
  3. 评估: 这一步是否正确？
  4. 奖励: 给予 reward signal

Total Reward = Σ(step_reward × importance_weight)
```

**实现设计：**

```python
@dataclass
class StepEvaluation:
    """单步评估结果"""
    step_id: int
    tool_name: str
    input_params: dict
    output_result: dict
    correctness: float      # 0-1, 是否正确
    completeness: float     # 0-1, 是否完整
    safety: float           # 0-1, 是否安全
    importance: float       # 0-1, 这一步的重要性
    reward: float           # 加权奖励
    issues: List[str]       # 发现的问题
    suggestion: str         # 改进建议


class StepLevelEvaluator:
    """过程级评估器"""
    
    def evaluate_trajectory(self, trajectory):
        step_evals = []
        
        for i, step in enumerate(trajectory):
            eval_result = self.evaluate_step(
                step=step,
                context=trajectory[:i],  # 前序步骤作为上下文
                expected_outcome=self.get_expected_outcome(step)
            )
            step_evals.append(eval_result)
        
        # 计算总奖励
        total_reward = sum(
            e.reward * e.importance for e in step_evals
        ) / sum(e.importance for e in step_evals)
        
        return TrajectoryEvaluation(
            steps=step_evals,
            total_reward=total_reward,
            weak_points=self.find_weak_points(step_evals),
            lessons=self.extract_lessons(step_evals)
        )
    
    def evaluate_step(self, step, context, expected_outcome):
        """评估单个步骤"""
        # 1. 检查 tool call 是否成功
        if step.get("status") == "error":
            return StepEvaluation(
                correctness=0.0,
                safety=0.5,  # 错误不一定不安全
                suggestion=f"Tool {step['tool']} 执行失败: {step['error']}"
            )
        
        # 2. 检查输出是否合理
        output_check = self.check_output_reasonableness(
            step["tool"], step["output"]
        )
        
        # 3. 检查是否符合临床约束
        clinical_check = self.check_clinical_constraints(
            step["tool"], step["output"]
        )
        
        # 4. 检查是否与前序步骤一致
        consistency_check = self.check_consistency(
            step, context
        )
        
        # 综合评分
        correctness = (
            output_check["score"] * 0.4 +
            clinical_check["score"] * 0.4 +
            consistency_check["score"] * 0.2
        )
        
        return StepEvaluation(
            correctness=correctness,
            completeness=output_check["completeness"],
            safety=clinical_check["safety"],
            importance=self.estimate_importance(step["tool"]),
            reward=correctness * self.estimate_importance(step["tool"]),
            issues=output_check["issues"] + clinical_check["issues"],
            suggestion=output_check.get("suggestion", "")
        )
```

**与 ReflexionEngine 集成：**

```python
class EnhancedReflexionEngine:
    """增强版 Reflexion 引擎，集成过程级评估"""
    
    def __init__(self):
        self.step_evaluator = StepLevelEvaluator()
    
    def reflect(self, trajectory, outcome):
        # 1. 过程级评估
        step_evals = self.step_evaluator.evaluate_trajectory(trajectory)
        
        # 2. 找到薄弱环节
        weak_points = step_evals.weak_points
        
        # 3. 针对性反思
        for weak in weak_points:
            reflection = self.reflect_on_step(weak, trajectory)
            self.store_reflection(reflection)
        
        # 4. 提取可复用的教训
        lessons = step_evals.lessons
        for lesson in lessons:
            self.store_lesson(lesson)
        
        return {
            "step_evaluations": step_evals,
            "weak_points": weak_points,
            "lessons": lessons
        }
```

#### 3.3.3 预期收益

| 指标 | 整体反思 | 过程级评估 |
|------|---------|-----------|
| 失败定位精度 | 整个 trajectory | 具体某一步 |
| 反思粒度 | 粗（整体教训） | 细（每步教训） |
| 教训复用性 | 低（场景特定） | 高（步骤通用） |
| 改进针对性 | 弱 | 强 |

---

### 3.4 方案 D：多轮对话长序列 Benchmark

#### 3.4.1 现状分析

BrachyBot 当前的 benchmark 99% 是单轮查询：

```
当前:
  Q: "前列腺处方剂量是多少？"  (单轮)
  Q: "帮我分割 CTV"          (单轮)
  Q: "55岁男性完整病例..."    (单轮)

缺失:
  - 多轮上下文传递
  - 跨步骤决策
  - 偏好学习
  - 错误恢复
```

#### 3.4.2 借鉴方案

**长序列 Benchmark 设计：**

```
场景 1: 端到端计划流程 (6 步)
  Turn 1: "我有个前列腺癌病人，Gleason 3+4，PSA 8.5"
  Turn 2: "CT 已上传，帮我分析影像质量"
  Turn 3: "CTV 分割结果怎么样？调整一下前部边界"
  Turn 4: "OAR 有没有超量？膀胱 D2cc 多少？"
  Turn 5: "帮我优化一下，V150 太高了"
  Turn 6: "导出 DICOM，我要传到治疗计划系统"

场景 2: 错误恢复 (4 步)
  Turn 1: "帮我分割 CTV"
  Turn 2: "分割结果不对，肿瘤位置标错了"
  Turn 3: "重新分割，这次用 MRI 融合的边界"
  Turn 4: "好多了，现在帮我评估剂量"

场景 3: 多方案对比 (5 步)
  Turn 1: "帮我做两个计划方案"
  Turn 2: "方案 A 的 V150 是多少？"
  Turn 3: "方案 B 呢？"
  Turn 4: "对比一下两个方案"
  Turn 5: "选方案 A，帮我优化细节"

场景 4: 紧急场景 (3 步)
  Turn 1: "15 分钟后要给病人治疗，快帮我检查计划！"
  Turn 2: "OAR 超量了怎么办？"
  Turn 3: "快速调整一下，能用就行"
```

**评估维度：**

```python
long_sequence_metrics = {
    "context_retention": "上下文保持能力（是否记住前序信息）",
    "decision_consistency": "决策一致性（前后决策是否矛盾）",
    "error_recovery": "错误恢复能力（能否从错误中恢复）",
    "preference_learning": "偏好学习能力（是否学会用户偏好）",
    "efficiency": "效率（是否用最少步骤完成任务）",
}
```

#### 3.4.3 预期收益

| 指标 | 单轮 Benchmark | 长序列 Benchmark |
|------|---------------|-----------------|
| 真实场景覆盖 | 低 | 高 |
| 上下文管理测试 | 无 | 有 |
| Agent 规划能力测试 | 弱 | 强 |
| 用户偏好学习测试 | 无 | 有 |

---

### 3.5 方案 E：Adaptive Context Compression

#### 3.5.1 现状分析

BrachyBot 已有分层记忆（L0-L4），但在长对话中仍可能遇到 context 膨胀问题：

```
L0 - Meta Rules: 始终在 prompt 中
L1 - Insight Index: 快速路由索引
L2 - Global Facts: 长期知识
L3 - Task Skills: 可复用工作流
L4 - Session Archive: 归档记录

问题:
  - 长对话中 L4 可能过大
  - CT 影像数据占用大量 context
  - 历史 tool call 结果累积
```

#### 3.5.2 借鉴方案

**Adaptive Compression 策略：**

```python
class AdaptiveContextCompressor:
    """自适应上下文压缩器"""
    
    def __init__(self, max_context_tokens=8000):
        self.max_tokens = max_context_tokens
    
    def compress(self, context):
        current_tokens = self.count_tokens(context)
        
        if current_tokens <= self.max_tokens:
            return context  # 无需压缩
        
        # 计算需要压缩的量
        excess = current_tokens - self.max_tokens
        
        compressed = context.copy()
        
        # 策略 1: 压缩早期消息
        compressed["messages"] = self.compress_old_messages(
            compressed["messages"], excess
        )
        
        # 策略 2: 压缩 tool call 结果
        compressed["tool_results"] = self.compress_tool_results(
            compressed["tool_results"]
        )
        
        # 策略 3: 压缩 CT 元数据
        compressed["ct_metadata"] = self.compress_ct_metadata(
            compressed["ct_metadata"]
        )
        
        return compressed
    
    def compress_old_messages(self, messages, excess_tokens):
        """压缩早期消息为摘要"""
        if len(messages) <= 3:
            return messages  # 太少不压缩
        
        # 保留最近 3 条完整消息
        recent = messages[-3:]
        old = messages[:-3]
        
        # 将早期消息压缩为摘要
        summary = self.summarize_messages(old)
        
        return [{"role": "system", "content": summary}] + recent
    
    def compress_tool_results(self, results):
        """压缩 tool call 结果"""
        compressed = {}
        for key, value in results.items():
            if isinstance(value, dict):
                # 只保留关键字段
                compressed[key] = {
                    "status": value.get("status"),
                    "summary": value.get("summary", ""),
                    "key_metrics": self.extract_key_metrics(value)
                }
            else:
                compressed[key] = str(value)[:200]  # 截断长文本
        return compressed
    
    def compress_ct_metadata(self, metadata):
        """压缩 CT 元数据"""
        return {
            "dimensions": metadata.get("dimensions"),
            "spacing": metadata.get("spacing"),
            "hu_range": metadata.get("hu_range"),
            # 不保留原始像素数据摘要
        }
```

#### 3.5.3 预期收益

| 指标 | 无压缩 | 自适应压缩 |
|------|--------|-----------|
| 长对话稳定性 | 低（context 溢出） | 高 |
| 信息保留度 | 100%（但可能溢出） | 85%+（关键信息保留） |
| 响应延迟 | 随对话增长 | 稳定 |

---

### 3.6 方案 F：SKILL.md 标准化

#### 3.6.1 现状分析

BrachyBot 已有 28+ 技能模板（`skills/` 目录），但格式不统一：

```
当前:
  skills/segmentation_skills.py  (Python 代码)
  skills/planning_skills.py      (Python 代码)
  skills/evaluation_skills.py    (Python 代码)
  
问题:
  - 无标准化描述格式
  - 无法被外部工具发现
  - 技能之间缺乏统一接口
```

#### 3.6.2 借鉴方案

**标准化技能目录结构：**

```
skills/
├── ct_analysis/
│   ├── SKILL.md              # 标准化描述
│   ├── implementation.py     # 具体实现
│   ├── examples/
│   │   ├── input_example.json
│   │   └── output_example.json
│   └── tests/
│       └── test_ct_analysis.py
│
├── ctv_segmentation/
│   ├── SKILL.md
│   ├── implementation.py
│   ├── examples/
│   └── tests/
│
├── dose_calculation/
│   ├── SKILL.md
│   ├── implementation.py
│   ├── examples/
│   └── tests/
│
└── ...
```

**SKILL.md 标准格式：**

```yaml
---
name: ctv_segmentation
version: 1.2.0
description: "CTV (Clinical Target Volume) 分割技能，用于从 CT/MRI 影像中分割肿瘤靶区"
author: BrachyBot Team
tags: [segmentation, CTV, oncology, medical-imaging]
trigger_keywords: ["segment", "CTV", "tumor", "contour", "分割", "靶区"]
input_schema:
  ct_path: "string - CT 影像路径"
  modality: "string - CT/MRI"
  cancer_type: "string - prostate/pancreas/cervical"
  hints: "dict - 可选的分割提示"
output_schema:
  ctv_mask: "string - CTV mask 路径"
  metrics: "dict - 分割质量指标"
  visualization: "string - 可视化图片路径"
clinical_constraints:
  - "CTV 必须完全覆盖 GTV"
  - "CTV 外扩边界取决于癌症类型"
  - "前列腺 CTV 通常 3-5mm 外扩"
---

## 触发条件
当用户请求 CTV 分割、肿瘤靶区勾画、靶区 contour 时触发。

## 工作流程
1. 接收 CT/MRI 影像路径
2. 检查影像质量和模态
3. 根据癌症类型选择分割策略
4. 执行自动分割
5. 质量检查和边界调整
6. 输出 CTV mask 和质量报告

## 注意事项
- 分割结果需要物理师/医生审核
- 不同癌症类型的 CTV 定义不同
- 有 TURP 病史的前列腺患者需要特殊处理

## 参考文献
- ICRU Report 83: Prostate CTV definition
- GEC-ESTRO: Cervical cancer CTV guidelines
```

#### 3.6.3 预期收益

| 指标 | 当前 | 标准化后 |
|------|------|---------|
| 技能可发现性 | 低（需要读代码） | 高（SKILL.md 自描述） |
| 外部工具集成 | 不支持 | 支持（Claude Code/Codex） |
| 技能复用性 | 低 | 高 |
| 测试覆盖率 | 不统一 | 统一 |

---

## 四、实施优先级和路线图

### 4.1 优先级矩阵

| 方案 | 影响力 | 工作量 | 依赖 | 优先级 |
|------|--------|--------|------|--------|
| **B: LLM-as-Judge** | 高 | 小 | 无 | **P0** |
| **A: 任务分类 + Benchmark 生成** | 高 | 中 | 无 | **P0** |
| **D: 长序列 Benchmark** | 中 | 中 | A | **P1** |
| **C: 过程奖励建模** | 高 | 大 | B | **P1** |
| **F: SKILL.md 标准化** | 中 | 小 | 无 | **P2** |
| **E: Adaptive Context** | 中 | 中 | 无 | **P2** |

### 4.2 实施路线图

```
Phase 1 (2 周): 评估升级
├── 实现 LLM-as-Judge 评估框架
├── 在现有 benchmark 上测试
└── 对比关键词匹配 vs LLM Judge 的评估差异

Phase 2 (3 周): Benchmark 系统化
├── 定义 BrachyBot 任务分类树
├── 实现递归组合生成器
├── 生成 500+ 新 benchmark 用例
└── 验证难度分布

Phase 3 (3 周): 长序列 + 过程评估
├── 创建长序列 benchmark (20+ 场景)
├── 实现 Step-Level Evaluator
├── 与 ReflexionEngine 集成
└── 测试 Agent 在长序列任务上的表现

Phase 4 (2 周): 工程优化
├── SKILL.md 标准化
├── Adaptive Context Compression
└── 性能测试和优化
```

### 4.3 资源需求

| 资源 | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|------|---------|---------|---------|---------|
| 开发人员 | 1 人 | 1 人 | 1-2 人 | 1 人 |
| LLM API 成本 | 低（评估用） | 低（生成用） | 中（训练用） | 低 |
| 计算资源 | 无 | 无 | GPU（可选） | 无 |
| 领域专家 | 0.5 天（验证） | 1 天（分类验证） | 1 天（场景设计） | 0 |

---

## 五、风险和缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| LLM Judge 评估不稳定 | 评估结果波动 | 多次评估取平均，设置 temperature=0 |
| Benchmark 生成质量低 | 用例不真实 | 领域专家审核，与真实对话对比 |
| 过程评估成本高 | API 费用增加 | 分层评估，简单用例用规则层 |
| 长序列评估困难 | 难以定义正确标准 | 多维度评估，允许部分正确 |
| 技能标准化工作量大 | 延期交付 | 优先标准化核心技能，渐进扩展 |

---

## 六、总结

### 6.1 DataMind 最值得借鉴的三个核心理念

1. **系统化 > 手工化**: 用 taxonomy + 递归组合替代手工编写 benchmark
2. **过程 > 结果**: 用 step-level evaluation 替代 outcome-only assessment
3. **标准化 > 自由化**: 用 SKILL.md 标准格式替代自由格式的技能定义

### 6.2 BrachyBot 的独特优势（不需要借鉴）

- ✅ 分层记忆系统 (L0-L4) 已经很完善
- ✅ Reflexion + 技能结晶已经是先进的自进化机制
- ✅ 医学领域特定的临床约束和安全审查
- ✅ 三栏布局 + CT Viewer 的专业 UI

### 6.3 一句话总结

> **DataMind 的方法论（系统化数据生成、过程级评估、标准化技能）可以显著提升 BrachyBot 的评估质量和 Agent 能力，同时 BrachyBot 独有的医学领域知识和自进化架构是其核心竞争力。**

---

**报告生成时间:** 2026-06-03
**分析方法:** 项目源码分析 + 论文解读 + 架构对比
**报告作者:** BrachyBot AI Assistant
