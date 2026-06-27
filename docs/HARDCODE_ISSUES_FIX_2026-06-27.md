# Sub-Agent 硬编码问题全面修复报告

**日期**: 2026-06-27  
**触发**: 用户指出"都说是 agent 为什么不让 LLM 来决策呢"  
**范围**: 所有子 agent 的硬编码输入准备逻辑

---

## 核心问题

在 LLM-based agent 系统中，关键决策逻辑不应该硬编码。硬编码会遇到：
- 无法理解上下文和语义
- 无法覆盖所有表述方式
- 需要手动维护模式
- 容易漏掉重要信息

---

## 发现并修复的硬编码问题

### 1. FactChecker 输入准备 ✅ 已修复

**问题**: `_prepare_fact_check_brief()` 使用硬编码正则表达式提取声明
```python
# 硬编码优先级
suspicious_patterns = [
    (r'according to (?:a|our)\s+(?:study|research|data)', 'Potential fabricated study'),
    ...
]
guideline_orgs = ['NCCN', 'AAPM', 'ASTRO', ...]
pmid_pattern = r'PMID:\s*(\d+)'
```

**改进**: 优先使用 LLM 理解上下文，正则作为 fallback
```python
# 改进后
if self.llm_callback:
    prompt = """从文本中识别最重要的待验证声明，按优先级排序：
    1. 可疑断言
    2. 临床指南
    3. 文献引用
    4. 数值指标
    返回 JSON 数组（最多 7 个）"""
    response = self.llm_callback(prompt)
    claims = json.loads(response)
else:
    # Fallback 到正则
    claims = self._prepare_fact_check_brief_regex(result_text)
```

**影响**: FactChecker 现在能理解上下文，提取真正重要的声明

---

### 2. RouterAgent 路由决策 ✅ 已修复

**问题**: `_quick_route()` 使用硬编码关键词匹配
```python
# 硬编码关键词
INTENT_PATTERNS = {
    "clinical_planning": {
        "keywords": ["分割", "计划", "规划", "segmentation", "planning", ...],
    },
    ...
}
```

**之前逻辑**:
1. 先用硬编码关键词匹配
2. 如果置信度 < 0.6，才用 LLM

**改进后逻辑**:
1. **优先使用 LLM 理解语义**
2. 如果 LLM 失败或置信度低，才用硬编码作为 fallback

```python
# 改进后
if self.llm_callback:
    try:
        routing = await self._llm_route(user_input)
        if routing.confidence >= 0.6:
            return routing
    except:
        pass

# Fallback 到硬编码
routing = self._quick_route(user_input, conversation_state)
```

**影响**: 路由决策更准确，能理解复杂语义（如"详细解释计划结论"不会被误分类为重新规划）

---

### 3. CompletenessChecker 完整性检查 ✅ 已修复

**问题**: `_extract_requirements()` 使用硬编码正则 + 停用词列表
```python
# 硬编码动作动词
action_verbs = [
    'segment', 'analyze', 'evaluate', 'calculate', 'generate',
    '分割', '分析', '评估', '计算', '生成', ...
]

# 硬编码停用词
stopwords = {'the', 'a', 'an', 'is', 'are', 'of', 'to', ...}
```

**之前逻辑**:
1. Layer 1: 确定性提取（硬编码）
2. Layer 2: LLM 语义匹配
3. 合并结果

**改进后逻辑**:
1. **优先使用 LLM 提取需求和检查完整性**
2. 如果 LLM 失败，才用确定性方法作为 fallback

```python
# 改进后
if self.llm_callback:
    try:
        llm_results = await self._llm_check(user_message, response, steps)
        if llm_results:
            return llm_results
    except:
        pass

# Fallback 到确定性方法
det_requirements = self._extract_requirements(user_message)
```

**影响**: 能理解同义词和改述（如"分割 CTV" 和 "segment the clinical target volume"）

---

## 保留硬编码的合理场景

### PlanReviewer - OAR 约束默认值 ⚠️ 保留
```python
_DEFAULT_OAR_MULTIPLIERS = {
    "duodenum": {"d2cc": 1.0},
    "stomach": {"d2cc": 1.0},
    ...
}
```
**原因**: 这是默认值，可以从 `plan_config` 覆盖。确定性检查是合理的，因为这是客观的数值比较。

### SafetyGuardian - 确定性安全检查 ✅ 保留
```python
# 纯确定性检查
def _check_dose_range(self, dose_metrics, prescription):
    if max_dose_val > 3.0 * prescription:
        # 热点警告
```
**原因**: 安全检查需要确定性，不应该由 LLM 做可能出错的判断。

---

## 改进后的架构

```
用户输入
  ↓
RouterAgent
  ├─ 优先：LLM 理解语义 → 路由决策
  └─ Fallback：硬编码关键词匹配
  ↓
BrachyAgent 执行工具
  ↓
FactChecker (web_search 后)
  ├─ 优先：LLM 提取重要声明 → 验证
  └─ Fallback：正则表达式提取
  ↓
PlanReviewer (规划后)
  ├─ Layer 1：确定性阈值检查（保留）
  └─ Layer 2：LLM 临床解释
  ↓
CompletenessChecker (响应后)
  ├─ 优先：LLM 语义匹配 → 检查完整性
  └─ Fallback：确定性关键词匹配
  ↓
SafetyGuardian (关键决策后)
  └─ 纯确定性检查（保留）
```

---

## 设计原则

1. **LLM 优先**: 关键决策（路由、声明提取、完整性检查）由 LLM 驱动
2. **Fallback 机制**: 如果 LLM 失败，使用确定性方法作为兜底
3. **确定性检查保留**: 客观的数值比较（安全检查、阈值检查）保持硬编码
4. **渐进式改进**: 不一次性替换所有逻辑，保留 fallback 确保安全

---

## 测试验证

### FactChecker 测试
```python
# LLM 提取
text = "According to a study we conducted, V100 > 95%..."
claims = agent._prepare_fact_check_brief(text)
# 期望：LLM 理解"study we conducted"是可疑的，优先提取

# Fallback
agent.llm_callback = None
claims = agent._prepare_fact_check_brief(text)
# 期望：正则表达式提取
```

### RouterAgent 测试
```python
# LLM 路由
message = "详细解释一下计划的结论"
routing = await router.process(message)
# 期望：LLM 理解为 follow_up，不是 clinical_planning

# Fallback
router.llm_callback = None
routing = await router.process(message)
# 期望：硬编码关键词匹配
```

### CompletenessChecker 测试
```python
# LLM 检查
user_message = "分割 CTV 并分析剂量分布"
llm_results = await checker._llm_check(user_message, response, steps)
# 期望：LLM 理解"分割 CTV" 和 "segment the CTV" 是同一个需求

# Fallback
checker.llm_callback = None
requirements = checker._extract_requirements(user_message)
# 期望：正则表达式提取
```

---

## 预期效果

| Agent | 改进前 | 改进后 |
|-------|--------|--------|
| FactChecker | 漏掉微妙声明 | 理解上下文，提取真正重要的 |
| RouterAgent | 误分类复杂请求 | 理解语义，准确路由 |
| CompletenessChecker | 无法识别同义词 | 理解改述，准确检查 |

---

## 风险评估

### 低风险 ✅
- 所有改进都有 fallback 机制
- 如果 LLM 失败，自动回退到确定性方法
- 不会导致系统崩溃

### 性能影响 ⚠️
- 增加 LLM 调用次数
- 可能增加延迟（每次调用 1-2 秒）
- 建议：监控性能，必要时缓存 LLM 结果

### Token 消耗 ⚠️
- 每次路由/提取/检查都会消耗 token
- 建议：优化 prompt，减少 token 使用

---

## 后续建议

1. **监控性能**: 记录 LLM 调用次数、延迟、成功率
2. **优化 Prompt**: 根据实际效果调整 prompt
3. **缓存机制**: 对相似输入缓存 LLM 结果
4. **渐进式部署**: 先在测试环境验证，再上线

---

## 总结

**核心理念**: 在 LLM-based agent 系统中，关键决策应该由 LLM 驱动，硬编码只作为 fallback。

**修复了 3 个关键问题**:
1. FactChecker 声明提取 → LLM 优先
2. RouterAgent 路由决策 → LLM 优先
3. CompletenessChecker 完整性检查 → LLM 优先

**保留了合理的硬编码**:
1. PlanReviewer OAR 默认值（可覆盖）
2. SafetyGuardian 安全检查（需要确定性）

**结果**: Agent 系统更符合"agent"的定义，能够理解语义和上下文，而不是简单的模式匹配。
