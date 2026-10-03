# DataMind × BrachyBot Integration Analysis Report

**Analysis Date:** 2026-06-03
**Analysis Objective:** Study the merits of DataMind (zjunlp/DataMind) and propose improvement plans applicable to BrachyBot
**DataMind Source:** https://github.com/zjunlp/DataMind
**Papers:** ICLR 2026 / AAAI 2026 / KDD 2026

---

## 1. Project Background Comparison

### 1.1 DataMind Overview

DataMind is an **open-source LLM data-analysis Agent** framework developed by the Zhejiang University NLP Lab (zjunlp), published at ICLR/AAAI/KDD 2026. Its core contributions:

| Paper | Venue | Core Contribution |
|------|------|---------|
| Scaling Generalist Data-Analytic Agents | ICLR 2026 | DataMind-12K dataset + SFT/RL training scheme |
| Why Do Open-Source LLMs Struggle with Data Analysis? | AAAI 2026 | Systematic empirical analysis; found that planning quality is the decisive factor |
| Rewarding the Scientific Process | KDD 2026 | Process Reward Modeling (Process Reward Model) |
| LongDS-Bench | 2026-05 | Long-sequence multi-step analysis benchmark |

**Key Result:** DataMind-14B achieves an average score of 71.16% across multiple data-analysis benchmarks, surpassing DeepSeek-V3.1 and GPT-5.

### 1.2 BrachyBot Overview

BrachyBot is a **closed-loop self-evolving AI brachytherapy treatment planning system**. Its core architecture:

| Module | Function | Technology |
|------|------|------|
| AgenticSys | LLM-driven decision making | Function Calling, 15 LLM providers |
| Layered Memory (L0-L4) | Context management | Meta Rules → Insight Index → Global Facts → Skills → Archive |
| ReflexionEngine | Trajectory reflection | Actor/Evaluator/Self-Reflection Loop |
| SkillCrystallizer | Skill crystallization | Trajectory → SOP → Executable Skill |
| Multi-Agent Critique | Safety review | Multi-agent clinical review |
| Web UI | User interaction | Three-column layout, CT Viewer, Chat, Analysis |

### 1.3 Key Differences

| Dimension | DataMind | BrachyBot |
|------|----------|-----------|
| **Domain** | General data analysis | Brachytherapy (medical imaging) |
| **Agent Mode** | Code-execution Agent | Tool Chain Agent |
| **Training Approach** | SFT + RL to train own model | Uses off-the-shelf LLM APIs |
| **Evolution Approach** | Data synthesis + retraining | Reflexion + skill crystallization |
| **Evaluation Approach** | Pass@3 + LLM Judge | Keyword matching |
| **Benchmark** | Automatically generated | Manually written |

---

## 2. In-Depth Analysis of DataMind's Core Innovations

### 2.1 Fine-Grained Task Taxonomy + Progressive Composition

**DataMind's approach:**

```
Task Taxonomy (three-level classification):
  ┌─ Data Understanding
  │   ├─ File format identification
  │   ├─ Schema parsing
  │   └─ Data quality checking
  ├─ Code Generation
  │   ├─ Single-step query
  │   ├─ Multi-step transformation
  │   └─ Complex aggregation
  └─ Strategic Planning
      ├─ Analysis path design
      ├─ Exception handling
      └─ Result validation

Recursive Composition:
  Level 1: Single sub-task (e.g., "read CSV")
  Level 2: Combination of 2-3 sub-tasks (e.g., "read + clean + summarize")
  Level 3: Multi-step task with constraints (e.g., "handle missing values + anomaly detection + generate report")
  Level 4: Complete analysis pipeline (e.g., end-to-end flow from data to insights)
```

**Key findings:**
- The granularity of task classification directly affects data diversity
- Recursive composition can expand the task space exponentially
- Progressive difficulty is more effective than random combination

### 2.2 Process Reward Modeling (Process Reward Model)

**DataMind's approach:**

Traditional evaluation looks only at the final outcome (outcome-only reward):
```
Answer == Gold → Reward = 1
Answer != Gold → Reward = 0
```

DataMind introduces process-level reward:
```
Step 1: Data loading → Evaluate (is the format correct?)
Step 2: Data cleaning → Evaluate (is the handling of missing values reasonable?)
Step 3: Analysis computation → Evaluate (is the statistical method correct?)
Step 4: Result output → Evaluate (is the conclusion reasonable?)

Total Reward = Σ(step_reward × step_weight)
```

**Key findings:**
- "Strategic planning quality serves as the primary determinant of model performance"
- Process reward is more stable than outcome reward
- The correctness of intermediate steps strongly predicts the final result

### 2.3 Memory-Efficient + Stable Multi-Turn Rollout

**DataMind's approach:**

```
Problem: context window explosion during long-sequence rollout

Solution:
1. Sliding window: keep only the complete actions of the most recent N steps
2. History compression: compress earlier steps into summaries
3. Key-point retention: keep complete records of important decisions
4. Error recovery: detailed records of failed steps for debugging
```

**Engineering practices:**
- Use a separate conda environment to run code execution
- Asynchronous interpreter to avoid blocking the main flow
- Timeout mechanism to prevent infinite loops

### 2.4 SKILL.md Standardized Skill Format

**DataMind's approach:**

```yaml
---
name: data_analysis_skill
description: "Skill for data analysis tasks, including data cleaning, statistical analysis, and visualization"
---

## Trigger Conditions
Triggered when the user requests data analysis, statistical computation, or data visualization.

## Workflow
1. Identify the data format and structure
2. Design the analysis path
3. Execute the analysis step by step
4. Validate the results
5. Generate a report

## Notes
- Check the data type before handling missing values
- Check normality assumptions before statistical tests
- The choice of visualization depends on the data type and analysis objective
```

Each skill is a standalone folder + `SKILL.md`, automatically discoverable by Claude Code / Codex.

### 2.5 LLM-as-Judge Evaluation Framework

**DataMind's approach:**

```
Evaluation levels:
1. Rule validation: exact match / SQL result comparison
2. LLM Judge: use another LLM to assess semantic correctness
3. Pass@3: at least 1 pass out of 3 attempts

Judge Prompt:
"Please evaluate whether the following data analysis result is correct.
 Gold answer: {gold}
 Student answer: {prediction}
 Please score along the following dimensions:
 1. Data processing correctness (0-1)
 2. Reasonableness of the analysis method (0-1)
 3. Accuracy of the conclusion (0-1)
 Total score: (0-1)"
```

### 2.6 LongDS-Bench Long-Sequence Benchmark

**DataMind's approach:**

Specifically built to test Agent performance on long-sequence multi-step tasks:
- Analysis pipelines of 5-10 steps
- Requires passing context across steps
- Includes error-recovery scenarios
- Tests the Agent's planning and error-correction abilities

**Key finding:** Long-sequence tasks are the main failure point of current Agents.

---

## 3. Detailed Design of Adoptable Solutions

### 3.1 Solution A: Fine-Grained Task Taxonomy + Progressive Benchmark Generation

#### 3.1.1 Current-State Analysis

BrachyBot's current benchmark consists of 1700+ manually written cases and has the following problems:

```
Problem 1: Uneven difficulty distribution
  Easy (1-10 chars):   ████████████████████ 45%
  Medium (10-50 chars): ████ 12%  ← severely insufficient
  Complex (50+ chars):  ████████████ 28%
  Detailed clinical (100+ chars): ██████ 15%

Problem 2: Lack of systematic difficulty progression
  G001 "你好" → MC001 "前列腺处方剂量" → Q1003 "55岁男性完整病例"
  (Large difficulty jumps, weak intermediate layer)

Problem 3: High manual authoring cost
  Each case requires manual design by a domain expert
  Difficult to scale systematically
```

#### 3.1.2 Adoptable Solution

**Step 1: Define the BrachyBot task taxonomy tree**

```
BrachyBot Task Taxonomy:

├─ L1: Single Tool
│   ├─ CT information query (spacing, dimensions, HU range)
│   ├─ Simple segmentation request (CTV/OAR)
│   ├─ Dose parameter query (D90, V100)
│   └─ File operations (export, save)
│
├─ L2: Two-Step Combo
│   ├─ Segmentation + evaluation ("分割 CTV 然后检查质量")
│   ├─ Query + comparison ("查一下 OAR 约束然后对比当前计划")
│   ├─ Analysis + recommendation ("分析 DVH 然后给优化建议")
│   └─ Computation + validation ("计算剂量然后验证约束")
│
├─ L3: Multi-Step + Constraints
│   ├─ Complete segmentation workflow (CTV + OAR + quality check)
│   ├─ Plan optimization (find issues → adjust parameters → recompute)
│   ├─ Emergency scenario (time pressure + multiple constraints)
│   └─ Exception handling (device alarm + recovery workflow)
│
└─ L4: Full Clinical Reasoning
    ├─ End-to-end planning (CT → segmentation → plan → evaluation → export)
    ├─ Multi-turn dialogue (context passing + preference learning)
    ├─ Complex cases (multiple comorbidities + individualized plans)
    └─ Cross-modality reasoning (CT + MRI fusion + dose accumulation)
```

**Step 2: Recursively compose and generate benchmark cases**

```python
# Pseudocode: recursive composition generator
def generate_benchmark_tasks(taxonomy, target_count):
    tasks = []
    
    # Level 1: atomic tasks
    for atom in taxonomy.atomic_tasks:
        tasks.extend(generate_variations(atom, count=10))
    
    # Level 2: two-step combinations
    for combo in itertools.combinations(taxonomy.atomic_tasks, 2):
        if is_composable(combo):
            tasks.append(compose_task(combo))
    
    # Level 3: combinations with constraints
    for base_task in tasks:
        for constraint in taxonomy.constraints:
            tasks.append(add_constraint(base_task, constraint))
    
    # Level 4: full workflows
    for workflow in taxonomy.workflows:
        tasks.append(generate_workflow_task(workflow))
    
    return sample_diverse(tasks, target_count)
```

**Step 3: Automatic difficulty labeling**

```python
def auto_label_difficulty(task):
    """Automatically label difficulty based on features"""
    features = {
        "input_length": len(task.input),
        "tool_count": estimate_tool_calls(task),
        "constraint_count": count_constraints(task),
        "context_required": requires_context(task),
        "clinical_depth": clinical_depth_score(task),
    }
    
    # Weighted scoring
    score = sum(features[k] * WEIGHTS[k] for k in features)
    
    if score < 2: return "easy"
    if score < 5: return "medium"
    if score < 8: return "hard"
    return "expert"
```

#### 3.1.3 Expected Benefits

| Metric | Current | After Improvement |
|------|------|--------|
| Medium-difficulty share | 12% | 35%+ |
| Difficulty-gradient continuity | Jumpy | Smooth progression |
| Benchmark generation cost | Fully manual | Semi-automated |
| Case diversity | Depends on expert experience | Systematic coverage |

---

### 3.2 Solution B: LLM-as-Judge Evaluation Framework

#### 3.2.1 Current-State Analysis

BrachyBot's current evaluation method:

```python
# Current: keyword matching
def evaluate_response(response, case):
    keywords = case.get("expected_keywords", [])
    for kw in keywords:
        if kw.lower() in text:
            return "pass"  # passes as long as a keyword appears
    return "fail"
```

**Problems:**
- The presence of "前列腺" in an answer ≠ correctly answering a prostate-related question
- Cannot assess the completeness and accuracy of an answer
- Cannot handle synonyms and semantically equivalent expressions

#### 3.2.2 Adoptable Solution

**Multi-layer evaluation framework:**

```
Layer 1: Rule layer (Rule-Based) — fast filtering
  ├─ Keyword pre-screening (existing)
  ├─ Forbidden-word check (existing)
  └─ Format validation (new: check whether dose values, units, etc. are present)

Layer 2: Semantic layer (LLM-as-Judge) — core evaluation
  ├─ Relevance: is the answer on topic?
  ├─ Accuracy: is the medical information correct?
  ├─ Completeness: are all key points covered?
  ├─ Safety: are there harmful recommendations?
  └─ Actionability: are the recommendations executable?

Layer 3: Clinical rule validation (Clinical Rules) — domain validation
  ├─ Dose range check (e.g., prostate D90 should be 100-180 Gy)
  ├─ OAR constraint validation (e.g., bladder D2cc < 70 Gy)
  ├─ Indication matching (e.g., Gleason score matches treatment modality)
  └─ Device parameter reasonableness (e.g., Ir-192 source strength range)

Layer 4: Expert simulation (Expert Simulation) — advanced evaluation
  ├─ Simulate physicist review
  ├─ Simulate physician review
  └─ Simulate safety committee review
```

**LLM Judge Prompt design:**

```python
JUDGE_PROMPT = """
You are a senior brachytherapy physicist. Please evaluate the quality of the following answer.

## Evaluation Dimensions

1. **Accuracy** (0-10): Is the medical information correct?
2. **Completeness** (0-10): Are all key points covered?
3. **Safety** (0-10): Are there potentially harmful recommendations?
4. **Actionability** (0-10): Are the recommendations specific and executable?
5. **Professionalism** (0-10): Are correct terminology and concepts used?

## Scoring Criteria

- 9-10: Excellent, directly usable in clinical practice
- 7-8: Good, requires minor revisions
- 5-6: Fair, requires major revisions
- 3-4: Poor, basically unusable
- 1-2: Wrong, potentially harmful

## Output Format

{{
  "accuracy": <score>,
  "completeness": <score>,
  "safety": <score>,
  "actionability": <score>,
  "professionalism": <score>,
  "overall": <weighted_average>,
  "issues": ["issue 1", "issue 2"],
  "suggestion": "improvement suggestion"
}}

## Question
{question}

## Reference Answer
{reference}

## Answer to Evaluate
{response}
"""
```

**Evaluation flow:**

```python
class LLMJudgeEvaluator:
    def evaluate(self, response, case):
        # Layer 1: rule layer
        rule_result = self.rule_check(response, case)
        if rule_result == "fail":
            return {"verdict": "fail", "score": 0, "layer": "rule"}
        
        # Layer 2: LLM Judge
        llm_result = self.llm_judge(response, case)
        
        # Layer 3: clinical rules
        clinical_result = self.clinical_rule_check(response, case)
        
        # Composite score
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

#### 3.2.3 Expected Benefits

| Metric | Keyword Matching | LLM-as-Judge |
|------|-----------|--------------|
| Evaluation accuracy | ~60% | ~90%+ |
| Misjudgment rate | High | Low |
| Evaluation dimensions | Single (keywords) | Multi-dimensional (5 dimensions) |
| Interpretability | Low | High (with detailed scoring rationale) |
| Cost | Zero | One LLM call per evaluation |

---

### 3.3 Solution C: Process Reward Modeling (Step-Level Evaluation)

#### 3.3.1 Current-State Analysis

BrachyBot's ReflexionEngine performs an overall reflection after task completion:

```
Current flow:
  Execute full trajectory → success/failure → reflect → store lesson

Problems:
  - Only the final result is known; the step where an error occurred is unknown
  - Cannot precisely locate the cause of failure
  - Reflection granularity is too coarse to be reusable
```

#### 3.3.2 Adoptable Solution

**Step-Level Evaluation Pipeline:**

```
Trajectory = [Step1, Step2, Step3, ..., StepN]

For each Step:
  1. Input: the input parameters of the tool_call
  2. Output: the execution result of the tool_call
  3. Evaluation: is this step correct?
  4. Reward: assign a reward signal

Total Reward = Σ(step_reward × importance_weight)
```

**Implementation design:**

```python
@dataclass
class StepEvaluation:
    """Single-step evaluation result"""
    step_id: int
    tool_name: str
    input_params: dict
    output_result: dict
    correctness: float      # 0-1, whether correct
    completeness: float     # 0-1, whether complete
    safety: float           # 0-1, whether safe
    importance: float       # 0-1, importance of this step
    reward: float           # weighted reward
    issues: List[str]       # issues found
    suggestion: str         # improvement suggestion


class StepLevelEvaluator:
    """Process-level evaluator"""
    
    def evaluate_trajectory(self, trajectory):
        step_evals = []
        
        for i, step in enumerate(trajectory):
            eval_result = self.evaluate_step(
                step=step,
                context=trajectory[:i],  # preceding steps as context
                expected_outcome=self.get_expected_outcome(step)
            )
            step_evals.append(eval_result)
        
        # Compute total reward
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
        """Evaluate a single step"""
        # 1. Check whether the tool call succeeded
        if step.get("status") == "error":
            return StepEvaluation(
                correctness=0.0,
                safety=0.5,  # an error is not necessarily unsafe
                suggestion=f"Tool {step['tool']} execution failed: {step['error']}"
            )
        
        # 2. Check whether the output is reasonable
        output_check = self.check_output_reasonableness(
            step["tool"], step["output"]
        )
        
        # 3. Check whether it satisfies clinical constraints
        clinical_check = self.check_clinical_constraints(
            step["tool"], step["output"]
        )
        
        # 4. Check consistency with preceding steps
        consistency_check = self.check_consistency(
            step, context
        )
        
        # Composite score
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

**Integration with ReflexionEngine:**

```python
class EnhancedReflexionEngine:
    """Enhanced Reflexion engine with integrated process-level evaluation"""
    
    def __init__(self):
        self.step_evaluator = StepLevelEvaluator()
    
    def reflect(self, trajectory, outcome):
        # 1. Process-level evaluation
        step_evals = self.step_evaluator.evaluate_trajectory(trajectory)
        
        # 2. Find weak points
        weak_points = step_evals.weak_points
        
        # 3. Targeted reflection
        for weak in weak_points:
            reflection = self.reflect_on_step(weak, trajectory)
            self.store_reflection(reflection)
        
        # 4. Extract reusable lessons
        lessons = step_evals.lessons
        for lesson in lessons:
            self.store_lesson(lesson)
        
        return {
            "step_evaluations": step_evals,
            "weak_points": weak_points,
            "lessons": lessons
        }
```

#### 3.3.3 Expected Benefits

| Metric | Overall Reflection | Process-Level Evaluation |
|------|---------|-----------|
| Failure-localization precision | The entire trajectory | A specific step |
| Reflection granularity | Coarse (overall lesson) | Fine (per-step lesson) |
| Lesson reusability | Low (scenario-specific) | High (step-general) |
| Improvement targeting | Weak | Strong |

---

### 3.4 Solution D: Multi-Turn Dialogue Long-Sequence Benchmark

#### 3.4.1 Current-State Analysis

99% of BrachyBot's current benchmark consists of single-turn queries:

```
Current:
  Q: "前列腺处方剂量是多少？"  (single turn)
  Q: "帮我分割 CTV"          (single turn)
  Q: "55岁男性完整病例..."    (single turn)

Missing:
  - Multi-turn context passing
  - Cross-step decision making
  - Preference learning
  - Error recovery
```

#### 3.4.2 Adoptable Solution

**Long-sequence benchmark design:**

```
Scenario 1: End-to-end planning workflow (6 steps)
  Turn 1: "我有个前列腺癌病人，Gleason 3+4，PSA 8.5"
  Turn 2: "CT 已上传，帮我分析影像质量"
  Turn 3: "CTV 分割结果怎么样？调整一下前部边界"
  Turn 4: "OAR 有没有超量？膀胱 D2cc 多少？"
  Turn 5: "帮我优化一下，V150 太高了"
  Turn 6: "导出 DICOM，我要传到治疗计划系统"

Scenario 2: Error recovery (4 steps)
  Turn 1: "帮我分割 CTV"
  Turn 2: "分割结果不对，肿瘤位置标错了"
  Turn 3: "重新分割，这次用 MRI 融合的边界"
  Turn 4: "好多了，现在帮我评估剂量"

Scenario 3: Multi-plan comparison (5 steps)
  Turn 1: "帮我做两个计划方案"
  Turn 2: "方案 A 的 V150 是多少？"
  Turn 3: "方案 B 呢？"
  Turn 4: "对比一下两个方案"
  Turn 5: "选方案 A，帮我优化细节"

Scenario 4: Emergency scenario (3 steps)
  Turn 1: "15 分钟后要给病人治疗，快帮我检查计划！"
  Turn 2: "OAR 超量了怎么办？"
  Turn 3: "快速调整一下，能用就行"
```

**Evaluation dimensions:**

```python
long_sequence_metrics = {
    "context_retention": "Context retention ability (does it remember prior information)",
    "decision_consistency": "Decision consistency (are earlier and later decisions contradictory)",
    "error_recovery": "Error recovery ability (can it recover from errors)",
    "preference_learning": "Preference learning ability (does it learn user preferences)",
    "efficiency": "Efficiency (does it complete the task in the fewest steps)",
}
```

#### 3.4.3 Expected Benefits

| Metric | Single-Turn Benchmark | Long-Sequence Benchmark |
|------|---------------|-----------------|
| Real-world scenario coverage | Low | High |
| Context-management testing | None | Yes |
| Agent planning-ability testing | Weak | Strong |
| User preference-learning testing | None | Yes |

---

### 3.5 Solution E: Adaptive Context Compression

#### 3.5.1 Current-State Analysis

BrachyBot already has layered memory (L0-L4), but may still encounter context bloat during long conversations:

```
L0 - Meta Rules: always in the prompt
L1 - Insight Index: fast routing index
L2 - Global Facts: long-term knowledge
L3 - Task Skills: reusable workflows
L4 - Session Archive: archived records

Problems:
  - L4 may become too large during long conversations
  - CT image data consumes a large amount of context
  - Historical tool call results accumulate
```

#### 3.5.2 Adoptable Solution

**Adaptive Compression strategy:**

```python
class AdaptiveContextCompressor:
    """Adaptive context compressor"""
    
    def __init__(self, max_context_tokens=8000):
        self.max_tokens = max_context_tokens
    
    def compress(self, context):
        current_tokens = self.count_tokens(context)
        
        if current_tokens <= self.max_tokens:
            return context  # no compression needed
        
        # Compute the amount that needs compression
        excess = current_tokens - self.max_tokens
        
        compressed = context.copy()
        
        # Strategy 1: compress early messages
        compressed["messages"] = self.compress_old_messages(
            compressed["messages"], excess
        )
        
        # Strategy 2: compress tool call results
        compressed["tool_results"] = self.compress_tool_results(
            compressed["tool_results"]
        )
        
        # Strategy 3: compress CT metadata
        compressed["ct_metadata"] = self.compress_ct_metadata(
            compressed["ct_metadata"]
        )
        
        return compressed
    
    def compress_old_messages(self, messages, excess_tokens):
        """Compress early messages into a summary"""
        if len(messages) <= 3:
            return messages  # too few to compress
        
        # Keep the most recent 3 messages intact
        recent = messages[-3:]
        old = messages[:-3]
        
        # Compress early messages into a summary
        summary = self.summarize_messages(old)
        
        return [{"role": "system", "content": summary}] + recent
    
    def compress_tool_results(self, results):
        """Compress tool call results"""
        compressed = {}
        for key, value in results.items():
            if isinstance(value, dict):
                # Keep only key fields
                compressed[key] = {
                    "status": value.get("status"),
                    "summary": value.get("summary", ""),
                    "key_metrics": self.extract_key_metrics(value)
                }
            else:
                compressed[key] = str(value)[:200]  # truncate long text
        return compressed
    
    def compress_ct_metadata(self, metadata):
        """Compress CT metadata"""
        return {
            "dimensions": metadata.get("dimensions"),
            "spacing": metadata.get("spacing"),
            "hu_range": metadata.get("hu_range"),
            # do not retain raw pixel-data summaries
        }
```

#### 3.5.3 Expected Benefits

| Metric | No Compression | Adaptive Compression |
|------|--------|-----------|
| Long-conversation stability | Low (context overflow) | High |
| Information retention | 100% (but may overflow) | 85%+ (key information retained) |
| Response latency | Grows with conversation | Stable |

---

### 3.6 Solution F: SKILL.md Standardization

#### 3.6.1 Current-State Analysis

BrachyBot already has 28+ skill templates (the `skills/` directory), but the formats are not unified:

```
Current:
  skills/segmentation_skills.py  (Python code)
  skills/planning_skills.py      (Python code)
  skills/evaluation_skills.py    (Python code)
  
Problems:
  - No standardized description format
  - Cannot be discovered by external tools
  - Lack of a unified interface between skills
```

#### 3.6.2 Adoptable Solution

**Standardized skill directory structure:**

```
skills/
├── ct_analysis/
│   ├── SKILL.md              # standardized description
│   ├── implementation.py     # concrete implementation
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

**SKILL.md standard format:**

```yaml
---
name: ctv_segmentation
version: 1.2.0
description: "CTV (Clinical Target Volume) segmentation skill, used to segment tumor target volumes from CT/MRI images"
author: BrachyBot Team
tags: [segmentation, CTV, oncology, medical-imaging]
trigger_keywords: ["segment", "CTV", "tumor", "contour", "分割", "靶区"]
input_schema:
  ct_path: "string - path to the CT image"
  modality: "string - CT/MRI"
  cancer_type: "string - prostate/pancreas/cervical"
  hints: "dict - optional segmentation hints"
output_schema:
  ctv_mask: "string - path to the CTV mask"
  metrics: "dict - segmentation quality metrics"
  visualization: "string - path to the visualization image"
clinical_constraints:
  - "CTV must fully cover the GTV"
  - "The CTV expansion margin depends on the cancer type"
  - "Prostate CTV typically has a 3-5mm expansion"
---

## Trigger Conditions
Triggered when the user requests CTV segmentation, tumor target volume delineation, or target volume contouring.

## Workflow
1. Receive the CT/MRI image path
2. Check image quality and modality
3. Select a segmentation strategy according to the cancer type
4. Perform automatic segmentation
5. Quality check and boundary adjustment
6. Output the CTV mask and a quality report

## Notes
- Segmentation results require review by a physicist/physician
- The definition of CTV differs across cancer types
- Prostate patients with a history of TURP require special handling

## References
- ICRU Report 83: Prostate CTV definition
- GEC-ESTRO: Cervical cancer CTV guidelines
```

#### 3.6.3 Expected Benefits

| Metric | Current | After Standardization |
|------|------|---------|
| Skill discoverability | Low (requires reading code) | High (SKILL.md is self-describing) |
| External tool integration | Not supported | Supported (Claude Code/Codex) |
| Skill reusability | Low | High |
| Test coverage | Inconsistent | Consistent |

---

## 4. Implementation Priorities and Roadmap

### 4.1 Priority Matrix

| Solution | Impact | Effort | Dependencies | Priority |
|------|--------|--------|------|--------|
| **B: LLM-as-Judge** | High | Small | None | **P0** |
| **A: Task taxonomy + Benchmark generation** | High | Medium | None | **P0** |
| **D: Long-sequence Benchmark** | Medium | Medium | A | **P1** |
| **C: Process reward modeling** | High | Large | B | **P1** |
| **F: SKILL.md standardization** | Medium | Small | None | **P2** |
| **E: Adaptive Context** | Medium | Medium | None | **P2** |

### 4.2 Implementation Roadmap

```
Phase 1 (2 weeks): Evaluation upgrade
├── Implement the LLM-as-Judge evaluation framework
├── Test on the existing benchmark
└── Compare evaluation differences between keyword matching and LLM Judge

Phase 2 (3 weeks): Benchmark systematization
├── Define the BrachyBot task taxonomy tree
├── Implement the recursive composition generator
├── Generate 500+ new benchmark cases
└── Validate the difficulty distribution

Phase 3 (3 weeks): Long-sequence + process evaluation
├── Create a long-sequence benchmark (20+ scenarios)
├── Implement the Step-Level Evaluator
├── Integrate with ReflexionEngine
└── Test the Agent's performance on long-sequence tasks

Phase 4 (2 weeks): Engineering optimization
├── SKILL.md standardization
├── Adaptive Context Compression
└── Performance testing and optimization
```

### 4.3 Resource Requirements

| Resource | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|------|---------|---------|---------|---------|
| Developers | 1 person | 1 person | 1-2 people | 1 person |
| LLM API cost | Low (for evaluation) | Low (for generation) | Medium (for training) | Low |
| Compute resources | None | None | GPU (optional) | None |
| Domain experts | 0.5 day (validation) | 1 day (taxonomy validation) | 1 day (scenario design) | 0 |

---

## 5. Risks and Mitigation

| Risk | Impact | Mitigation |
|------|------|---------|
| LLM Judge evaluation instability | Fluctuating evaluation results | Average over multiple evaluations; set temperature=0 |
| Low benchmark generation quality | Unrealistic cases | Domain expert review; compare against real dialogues |
| High process-evaluation cost | Increased API costs | Layered evaluation; use the rule layer for simple cases |
| Difficulty evaluating long sequences | Hard to define correctness criteria | Multi-dimensional evaluation; allow partial correctness |
| Large effort for skill standardization | Delayed delivery | Prioritize standardizing core skills; expand incrementally |

---

## 6. Conclusion

### 6.1 Three Core Ideas from DataMind Most Worth Adopting

1. **Systematization > Manual work**: Replace manual benchmark writing with a taxonomy + recursive composition
2. **Process > Outcome**: Replace outcome-only assessment with step-level evaluation
3. **Standardization > Free-form**: Replace free-form skill definitions with the SKILL.md standard format

### 6.2 BrachyBot's Unique Strengths (No Need to Adopt)

- ✅ The layered memory system (L0-L4) is already well developed
- ✅ Reflexion + skill crystallization is already an advanced self-evolution mechanism
- ✅ Medical-domain-specific clinical constraints and safety review
- ✅ A professional UI with a three-column layout + CT Viewer

### 6.3 One-Sentence Summary

> **DataMind's methodology (systematic data generation, process-level evaluation, and standardized skills) can significantly improve BrachyBot's evaluation quality and Agent capabilities, while BrachyBot's unique medical-domain knowledge and self-evolving architecture are its core competitive advantages.**

---

**Report Generated:** 2026-06-03
**Analysis Method:** Project source-code analysis + paper interpretation + architecture comparison
**Report Author:** BrachyBot AI Assistant
