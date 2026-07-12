# BrachyBot Multi-Agent System Design

## 1. 现有架构分析

### 当前组件
```
BrachyBot/
├── AgenticSys.py          # 主Agent (BrachyAgent)
│   ├── chat_with_stream() # LLM对话 + 工具执行
│   ├── ToolRegistry       # 工具注册表
│   └── AgentMemory        # 记忆系统
│
├── brain/                 # 大脑系统
│   ├── core/
│   │   ├── multi_agent_critic.py  # ✅ 已有：4个评审persona
│   │   ├── tree_search_planner.py # 树搜索规划
│   │   └── tool_code_writer.py    # 工具代码生成
│   ├── deciders/
│   │   ├── clinical_decider.py    # 临床决策
│   │   ├── planner_decider.py     # 规划决策
│   │   └── quality_decider.py     # 质量决策
│   ├── integration/
│   │   └── enhanced_agent.py      # ✅ 已有：自我进化集成
│   ├── knowledge/
│   │   └── rag.py                 # RAG知识检索
│   └── providers/                 # 14个LLM提供商
│
├── memory/                # 记忆系统
│   ├── layered_memory.py  # L0-L4分层记忆
│   ├── reflexion_engine.py # 自我反思
│   └── skill_crystallizer.py # 技能结晶
│
└── skills/                # 技能系统
```

### 已有但未充分利用的能力
1. **MultiAgentCritic** - 有4个评审persona，但只在plan review时调用
2. **EnhancedAgentIntegration** - 有pre/post hook，但未深度集成
3. **Deciders** - 有Clinical/Planner/Quality decider，但未串联

## 2. Multi-Agent 架构设计

### 核心理念
借鉴 OpenCode、AutoGPT、CrewAI 的设计理念：
- **每个Agent有明确的角色和职责**
- **Agent之间通过消息传递协作**
- **关键输出必须经过独立Agent审核**
- **支持并行执行和异步通信**

### 架构图
```
┌─────────────────────────────────────────────────────────────────┐
│                      BrachyBot Multi-Agent System                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │  User Input   │───▶│  Router      │───▶│  Planner     │       │
│  │  (Natural     │    │  Agent       │    │  Agent       │       │
│  │   Language)   │    │  (任务分发)   │    │  (任务规划)   │       │
│  └──────────────┘    └──────────────┘    └──────┬───────┘       │
│                                                  │               │
│                    ┌─────────────────────────────┼────────┐      │
│                    ▼                             ▼        ▼      │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │  Clinical         │  │  Tool            │  │  Knowledge   │  │
│  │  Executor         │  │  Executor        │  │  Agent       │  │
│  │  (临床执行)        │  │  (工具执行)       │  │  (知识检索)   │  │
│  └────────┬─────────┘  └────────┬─────────┘  └──────┬───────┘  │
│           │                      │                    │          │
│           └──────────────────────┼────────────────────┘          │
│                                  ▼                               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Quality Gate Layer                      │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐          │   │
│  │  │  Plan       │  │  Fact      │  │  Safety    │          │   │
│  │  │  Reviewer   │  │  Checker   │  │  Guardian  │          │   │
│  │  │  (计划审核)  │  │  (事实核查) │  │  (安全守护) │          │   │
│  │  └────────────┘  └────────────┘  └────────────┘          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                  │                               │
│                                  ▼                               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Response Synthesizer                    │   │
│  │  (综合所有Agent输出，生成最终响应)                            │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## 3. Agent 角色定义

### 3.1 Router Agent (路由Agent)
**职责**: 理解用户意图，分发到正确的执行路径

```python
class RouterAgent:
    """分析用户输入，决定调用哪些Agent"""
    
    def route(self, user_input: str) -> RoutingDecision:
        # 1. 意图识别
        # 2. 复杂度评估
        # 3. 选择执行路径
        return RoutingDecision(
            intent="clinical_planning",
            complexity="high",
            agents_needed=["clinical_executor", "knowledge_agent"],
            requires_review=True
        )
```

### 3.2 Planner Agent (规划Agent)
**职责**: 分解复杂任务为可执行步骤

```python
class PlannerAgent:
    """将复杂任务分解为工具调用序列"""
    
    def plan(self, task: str, context: dict) -> ExecutionPlan:
        # 1. 分析任务需求
        # 2. 查询可用工具
        # 3. 生成执行计划
        # 4. 优化执行顺序
        return ExecutionPlan(steps=[...], parallel_groups=[...])
```

### 3.3 Clinical Executor (临床执行器)
**职责**: 执行临床相关的工具调用

```python
class ClinicalExecutor:
    """执行CTV分割、OAR分割、剂量计算等临床工具"""
    
    def execute(self, step: PlanStep) -> ToolResult:
        # 1. 准备工具参数
        # 2. 调用工具
        # 3. 验证结果
        # 4. 记录执行历史
```

### 3.4 Knowledge Agent (知识Agent)
**职责**: 检索和验证医学知识

```python
class KnowledgeAgent:
    """RAG检索 + 联网查询 + 事实验证"""
    
    def search(self, query: str) -> KnowledgeResult:
        # 1. 本地RAG检索
        # 2. 联网搜索 (如果需要)
        # 3. 结果验证
        # 4. 引用追踪
```

### 3.5 Plan Reviewer (计划审核Agent)
**职责**: 审核治疗计划的质量

```python
class PlanReviewer:
    """独立审核计划，给出改进建议"""
    
    def review(self, plan: dict, dose_metrics: dict) -> ReviewResult:
        # 1. 剂量学审核
        # 2. 临床规范审核
        # 3. 风险评估
        # 4. 综合评分
```

### 3.6 Fact Checker (事实核查Agent)
**职责**: 验证信息的准确性和来源

```python
class FactChecker:
    """验证联网搜索结果和医学知识的准确性"""
    
    def verify(self, claims: list, sources: list) -> VerificationResult:
        # 1. 来源验证
        # 2. 交叉验证
        # 3. 时效性检查
        # 4. 置信度评估
```

### 3.7 Safety Guardian (安全守护Agent)
**职责**: 确保输出安全，防止危险操作

```python
class SafetyGuardian:
    """检查所有输出，确保临床安全"""
    
    def check(self, action: str, context: dict) -> SafetyResult:
        # 1. 剂量安全检查
        # 2. 操作合规检查
        # 3. 风险预警
        # 4. 拦截危险操作
```

## 4. 质量门控机制 (Quality Gate)

### 4.1 触发条件
```python
QUALITY_GATE_TRIGGERS = {
    # 必须经过审核的场景
    "mandatory": [
        "dose_evaluation",        # 剂量评估结果
        "treatment_plan",         # 治疗计划
        "clinical_recommendation", # 临床建议
        "web_search_result",      # 联网搜索结果
    ],
    
    # 可选审核的场景
    "optional": [
        "segmentation_result",    # 分割结果
        "trajectory_plan",        # 轨迹规划
    ],
}
```

### 4.2 审核流程
```python
class QualityGate:
    """质量门控层"""
    
    def gate(self, output_type: str, content: dict) -> GateResult:
        if output_type in MANDATORY_TRIGGERS:
            # 并行调用多个审核Agent
            reviews = parallel([
                self.plan_reviewer.review(content),
                self.fact_checker.verify(content),
                self.safety_guardian.check(content),
            ])
            
            # 综合判断
            return self._synthesize_reviews(reviews)
        
        return GateResult(passed=True)
```

## 5. 实现方案

### 5.1 新增文件结构
```
BrachyBot/
├── agents/                    # 新增：Agent目录
│   ├── __init__.py
│   ├── base_agent.py          # Agent基类
│   ├── router_agent.py        # 路由Agent
│   ├── planner_agent.py       # 规划Agent
│   ├── clinical_executor.py   # 临床执行器
│   ├── knowledge_agent.py     # 知识Agent
│   ├── plan_reviewer.py       # 计划审核Agent
│   ├── fact_checker.py        # 事实核查Agent
│   ├── safety_guardian.py     # 安全守护Agent
│   └── response_synthesizer.py # 响应合成器
│
├── quality/                   # 新增：质量门控
│   ├── __init__.py
│   ├── quality_gate.py        # 质量门控主逻辑
│   ├── review_aggregator.py   # 审核结果聚合
│   └── feedback_loop.py       # 反馈循环
│
└── communication/             # 新增：Agent通信
    ├── __init__.py
    ├── message_bus.py          # 消息总线
    ├── agent_registry.py       # Agent注册表
    └── protocol.py             # 通信协议
```

### 5.2 核心接口设计

#### Agent基类
```python
# agents/base_agent.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from enum import Enum

class AgentRole(Enum):
    ROUTER = "router"
    PLANNER = "planner"
    EXECUTOR = "executor"
    KNOWLEDGE = "knowledge"
    REVIEWER = "reviewer"
    FACT_CHECKER = "fact_checker"
    SAFETY_GUARDIAN = "safety_guardian"
    SYNTHESIZER = "synthesizer"

@dataclass
class AgentMessage:
    sender: AgentRole
    receiver: AgentRole
    message_type: str  # "request", "response", "feedback", "alert"
    content: Any
    metadata: Dict = None
    priority: int = 0  # 0=normal, 1=high, 2=critical

@dataclass
class AgentResponse:
    agent_role: AgentRole
    success: bool
    result: Any
    confidence: float  # 0.0-1.0
    reasoning: str     # 推理过程
    suggestions: List[str] = None
    warnings: List[str] = None

class BaseAgent(ABC):
    """所有Agent的基类"""
    
    def __init__(self, role: AgentRole, llm_callback=None):
        self.role = role
        self.llm_callback = llm_callback
        self.message_history: List[AgentMessage] = []
    
    @abstractmethod
    def process(self, message: AgentMessage) -> AgentResponse:
        """处理消息并返回响应"""
        pass
    
    def send_message(self, receiver: AgentRole, content: Any, 
                     message_type: str = "request") -> AgentMessage:
        """发送消息给其他Agent"""
        msg = AgentMessage(
            sender=self.role,
            receiver=receiver,
            message_type=message_type,
            content=content
        )
        self.message_history.append(msg)
        return msg
    
    def receive_feedback(self, feedback: AgentMessage):
        """接收反馈用于自我改进"""
        self.message_history.append(feedback)
```

#### 消息总线
```python
# communication/message_bus.py
from typing import Dict, List, Callable
from collections import defaultdict
import asyncio

class MessageBus:
    """Agent间通信的消息总线"""
    
    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._history: List[AgentMessage] = []
    
    def subscribe(self, message_type: str, handler: Callable):
        """订阅消息类型"""
        self._subscribers[message_type].append(handler)
    
    async def publish(self, message: AgentMessage):
        """发布消息"""
        self._history.append(message)
        
        # 通知订阅者
        for handler in self._subscribers.get(message.message_type, []):
            await handler(message)
        
        # 通知目标Agent的订阅者
        for handler in self._subscribers.get(message.receiver.value, []):
            await handler(message)
    
    def get_history(self, agent_role: AgentRole = None) -> List[AgentMessage]:
        """获取消息历史"""
        if agent_role:
            return [m for m in self._history 
                   if m.sender == agent_role or m.receiver == agent_role]
        return self._history
```

#### 质量门控
```python
# quality/quality_gate.py
from typing import List, Dict, Any
from dataclasses import dataclass
from enum import Enum

class GateDecision(Enum):
    PASS = "pass"           # 通过
    CONDITIONAL = "conditional"  # 有条件通过
    REJECT = "reject"       # 拒绝
    ESCALATE = "escalate"   # 上报给人类

@dataclass
class ReviewResult:
    reviewer: str
    decision: GateDecision
    score: float  # 0-10
    concerns: List[str]
    suggestions: List[str]
    confidence: float

@dataclass
class GateResult:
    passed: bool
    decision: GateDecision
    reviews: List[ReviewResult]
    final_message: str
    requires_human_review: bool = False

class QualityGate:
    """质量门控层 - 审核所有关键输出"""
    
    # 必须审核的输出类型
    MANDATORY_REVIEWS = {
        "treatment_plan",
        "dose_evaluation", 
        "clinical_recommendation",
        "web_search_medical",
    }
    
    # 可选审核的输出类型
    OPTIONAL_REVIEWS = {
        "segmentation_result",
        "trajectory_plan",
        "general_response",
    }
    
    def __init__(self, agents: Dict[str, BaseAgent]):
        self.agents = agents
        self.review_history: List[GateResult] = []
    
    async def review(self, output_type: str, content: Any, 
                    context: Dict = None) -> GateResult:
        """审核输出"""
        
        if output_type not in self.MANDATORY_REVIEWS:
            if output_type not in self.OPTIONAL_REVIEWS:
                return GateResult(passed=True, decision=GateDecision.PASS, 
                                reviews=[], final_message="No review needed")
        
        # 并行调用审核Agent
        reviews = await self._parallel_review(content, context)
        
        # 聚合结果
        gate_result = self._aggregate_reviews(reviews)
        
        # 记录历史
        self.review_history.append(gate_result)
        
        return gate_result
    
    async def _parallel_review(self, content: Any, 
                              context: Dict) -> List[ReviewResult]:
        """并行调用多个审核Agent"""
        import asyncio
        
        tasks = []
        
        # 计划审核
        if "plan_reviewer" in self.agents:
            tasks.append(self.agents["plan_reviewer"].review(content, context))
        
        # 事实核查
        if "fact_checker" in self.agents and self._needs_fact_check(content):
            tasks.append(self.agents["fact_checker"].verify(content, context))
        
        # 安全检查
        if "safety_guardian" in self.agents:
            tasks.append(self.agents["safety_guardian"].check(content, context))
        
        # 并行执行
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 过滤异常
        valid_results = []
        for r in results:
            if isinstance(r, ReviewResult):
                valid_results.append(r)
            elif isinstance(r, Exception):
                # 记录异常但不阻塞
                pass
        
        return valid_results
    
    def _aggregate_reviews(self, reviews: List[ReviewResult]) -> GateResult:
        """聚合审核结果"""
        if not reviews:
            return GateResult(passed=True, decision=GateDecision.PASS,
                            reviews=[], final_message="No reviews available")
        
        # 计算加权分数
        total_weight = sum(r.confidence for r in reviews)
        if total_weight == 0:
            weighted_score = sum(r.score for r in reviews) / len(reviews)
        else:
            weighted_score = sum(r.score * r.confidence for r in reviews) / total_weight
        
        # 收集所有concerns和suggestions
        all_concerns = []
        all_suggestions = []
        for r in reviews:
            all_concerns.extend(r.concerns)
            all_suggestions.extend(r.suggestions)
        
        # 判断决策
        reject_count = sum(1 for r in reviews if r.decision == GateDecision.REJECT)
        escalate_count = sum(1 for r in reviews if r.decision == GateDecision.ESCALATE)
        
        if reject_count > len(reviews) / 2:
            decision = GateDecision.REJECT
            passed = False
        elif escalate_count > 0 or weighted_score < 5:
            decision = GateDecision.ESCALATE
            passed = False
        elif weighted_score < 7:
            decision = GateDecision.CONDITIONAL
            passed = True
        else:
            decision = GateDecision.PASS
            passed = True
        
        return GateResult(
            passed=passed,
            decision=decision,
            reviews=reviews,
            final_message=self._build_final_message(reviews, decision),
            requires_human_review=decision == GateDecision.ESCALATE
        )
```

### 5.3 集成到现有系统

#### 修改 AgenticSys.py
```python
# 在 BrachyAgent 中集成 multi-agent system
class BrachyAgent:
    def __init__(self, ...):
        # ... 现有初始化代码 ...
        
        # 初始化 multi-agent system
        self._init_multi_agent_system()
    
    def _init_multi_agent_system(self):
        """初始化多Agent系统"""
        from agents import (
            RouterAgent, PlannerAgent, ClinicalExecutor,
            KnowledgeAgent, PlanReviewer, FactChecker, 
            SafetyGuardian, ResponseSynthesizer
        )
        from quality import QualityGate
        from communication import MessageBus
        
        # 创建消息总线
        self.message_bus = MessageBus()
        
        # 创建Agent
        self.agents = {
            "router": RouterAgent(llm_callback=self._llm_callback),
            "planner": PlannerAgent(llm_callback=self._llm_callback),
            "clinical": ClinicalExecutor(agent=self),
            "knowledge": KnowledgeAgent(llm_callback=self._llm_callback),
            "plan_reviewer": PlanReviewer(llm_callback=self._llm_callback),
            "fact_checker": FactChecker(llm_callback=self._llm_callback),
            "safety_guardian": SafetyGuardian(llm_callback=self._llm_callback),
            "synthesizer": ResponseSynthesizer(llm_callback=self._llm_callback),
        }
        
        # 创建质量门控
        self.quality_gate = QualityGate(self.agents)
    
    async def chat_with_multi_agent(self, message: str):
        """Multi-agent 版本的 chat"""
        
        # 1. Router Agent 分析意图
        routing = await self.agents["router"].process(message)
        
        # 2. Planner Agent 制定计划
        if routing.complexity == "high":
            plan = await self.agents["planner"].process(routing)
        else:
            plan = None
        
        # 3. 执行计划
        results = []
        if plan:
            for step in plan.steps:
                # Knowledge Agent 检索相关知识
                if step.needs_knowledge:
                    knowledge = await self.agents["knowledge"].process(step)
                    step.context["knowledge"] = knowledge
                
                # Clinical Executor 执行
                result = await self.agents["clinical"].process(step)
                results.append(result)
        else:
            # 简单任务直接执行
            result = await self.agents["clinical"].process(message)
            results.append(result)
        
        # 4. 质量门控审核
        for result in results:
            if result.needs_review:
                gate_result = await self.quality_gate.review(
                    result.output_type, result.content
                )
                
                if not gate_result.passed:
                    # 需要修改或上报
                    if gate_result.requires_human_review:
                        yield self._format_human_review_request(gate_result)
                    else:
                        # 根据反馈修改
                        result = await self._revise_based_on_feedback(
                            result, gate_result.reviews
                        )
        
        # 5. 合成最终响应
        response = await self.agents["synthesizer"].process(results)
        
        yield response
```

## 6. 与 OpenCode 等开源库的对比

### OpenCode 的特点
1. **Subagent 机制**: 每个复杂任务派出独立的 subagent
2. **Tool 隔离**: 每个 subagent 有自己的工具集
3. **结果聚合**: 主 agent 综合所有 subagent 的结果

### BrachyBot 的增强
1. **专业化的 Agent**: 针对临床场景的 specialized agents
2. **质量门控**: 独立的审核层，确保输出安全
3. **知识验证**: 事实核查 agent，防止幻觉
4. **反馈循环**: 基于审核结果的持续改进

## 7. 实施路线图

### Phase 1: 基础框架 (1-2周)
- [ ] 创建 `agents/` 目录和基类
- [ ] 实现 `MessageBus` 消息总线
- [ ] 实现 `RouterAgent` 路由Agent

### Phase 2: 核心Agent (2-3周)
- [ ] 实现 `PlanReviewer` 计划审核Agent
- [ ] 实现 `FactChecker` 事实核查Agent
- [ ] 实现 `SafetyGuardian` 安全守护Agent
- [ ] 实现 `QualityGate` 质量门控

### Phase 3: 集成测试 (1-2周)
- [ ] 集成到 `AgenticSys.py`
- [ ] 修改 `chat_with_stream()` 使用 multi-agent
- [ ] 添加前端展示审核结果

### Phase 4: 优化迭代 (持续)
- [ ] 收集用户反馈
- [ ] 优化 Agent 提示词
- [ ] 添加更多 specialized agents

## 8. 配置示例

```yaml
# config/multi_agent.yaml
multi_agent:
  enabled: true
  
  agents:
    router:
      model: "deepseek"  # 使用便宜的模型做路由
      temperature: 0.1
    
    planner:
      model: "deepseek"
      temperature: 0.2
    
    plan_reviewer:
      model: "deepseek"  # 使用更强的模型做审核
      temperature: 0.1
      personas:
        - name: "Dosimetry Expert"
          weight: 1.5
        - name: "Clinical Reviewer"
          weight: 1.3
        - name: "Risk Assessor"
          weight: 1.2
    
    fact_checker:
      model: "deepseek"
      temperature: 0.0  # 事实核查用低温度
      sources:
        - "pubmed"
        - "nccn_guidelines"
        - "aapm_reports"
    
    safety_guardian:
      model: "deepseek"
      temperature: 0.0
      rules:
        - "max_dose_check"
        - "oar_constraint_check"
        - "coverage_check"
  
  quality_gate:
    enabled: true
    mandatory_reviews:
      - "treatment_plan"
      - "dose_evaluation"
    optional_reviews:
      - "segmentation_result"
    
    thresholds:
      pass: 7.0
      conditional: 5.0
      escalate: 3.0
  
  communication:
    max_rounds: 5
    timeout_seconds: 30
    parallel_execution: true
```

## 9. 示例场景

### 场景1: 治疗计划审核
```
用户: "请为这个胰腺癌患者生成治疗计划"

[Router Agent] → 识别为复杂临床任务
[Planner Agent] → 制定执行计划:
  1. CTV分割
  2. OAR分割  
  3. 轨迹规划
  4. 种子规划
  5. 剂量计算
  6. 剂量评估

[Clinical Executor] → 按计划执行步骤1-6

[Quality Gate] → 触发审核
  [Plan Reviewer] → 检查剂量学参数
    - D90: 0.75 (偏低，建议增加种子)
    - V100: 80.3% (低于95%目标)
    - Score: 41/100 (需要改进)
  
  [Safety Guardian] → 安全检查
    - 最大剂量70.26 (需要确认OAR耐受)
    - 建议检查十二指肠受量

[Response Synthesizer] → 综合生成响应
  - 展示计划结果
  - 显示审核意见
  - 提供改进建议
```

### 场景2: 联网搜索验证
```
用户: "胰腺癌粒子植入的最新指南是什么？"

[Router Agent] → 识别为知识查询
[Knowledge Agent] → 联网搜索
  - 搜索结果: NCCN指南2024版...

[Quality Gate] → 触发事实核查
  [Fact Checker] → 验证搜索结果
    - 来源: nccn.org ✓
    - 时效性: 2024年 ✓
    - 引用: 有具体引用 ✓
    - 置信度: 0.9

[Response Synthesizer] → 生成响应
  - 展示指南内容
  - 标注来源和置信度
  - 提供引用链接
```

## 10. 总结

本方案的核心优势:

1. **专业化分工**: 每个Agent专注自己的领域
2. **质量门控**: 关键输出必须经过独立审核
3. **事实验证**: 防止LLM幻觉，确保信息准确
4. **安全守护**: 临床安全是第一优先级
5. **可扩展性**: 易于添加新的Agent和规则
6. **透明性**: 用户可以看到审核过程和结果

与现有系统的兼容性:
- 基于现有的 `MultiAgentCritic` 扩展
- 利用现有的 `EnhancedAgentIntegration` 框架
- 复用现有的 LLM Router 和 Provider
- 保持与前端的 SSE 流式通信
