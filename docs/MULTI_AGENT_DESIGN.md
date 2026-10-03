# BrachyBot Multi-Agent System Design

## 1. Existing Architecture Analysis

### Current Components
```
BrachyBot/
├── AgenticSys.py          # Main Agent (BrachyAgent)
│   ├── chat_with_stream() # LLM conversation + tool execution
│   ├── ToolRegistry       # Tool registry
│   └── AgentMemory        # Memory system
│
├── brain/                 # Brain system
│   ├── core/
│   │   ├── multi_agent_critic.py  # ✅ Existing: 4 reviewer personas
│   │   ├── tree_search_planner.py # Tree-search planning
│   │   └── tool_code_writer.py    # Tool code generation
│   ├── deciders/
│   │   ├── clinical_decider.py    # Clinical decision
│   │   ├── planner_decider.py     # Planning decision
│   │   └── quality_decider.py     # Quality decision
│   ├── integration/
│   │   └── enhanced_agent.py      # ✅ Existing: self-evolution integration
│   ├── knowledge/
│   │   └── rag.py                 # RAG knowledge retrieval
│   └── providers/                 # 14 LLM providers
│
├── memory/                # Memory system
│   ├── layered_memory.py  # L0-L4 layered memory
│   ├── reflexion_engine.py # Self-reflection
│   └── skill_crystallizer.py # Skill crystallization
│
└── skills/                # Skill system
```

### Existing but Underutilized Capabilities
1. **MultiAgentCritic** - has 4 reviewer personas, but is only invoked during plan review
2. **EnhancedAgentIntegration** - has pre/post hooks, but is not deeply integrated
3. **Deciders** - has Clinical/Planner/Quality deciders, but they are not connected

## 2. Multi-Agent Architecture Design

### Core Concepts
Drawing on the design philosophies of OpenCode, AutoGPT, and CrewAI:
- **Each agent has a clear role and responsibility**
- **Agents collaborate through message passing**
- **Critical outputs must be reviewed by independent agents**
- **Supports parallel execution and asynchronous communication**

### Architecture Diagram
```
┌─────────────────────────────────────────────────────────────────┐
│                      BrachyBot Multi-Agent System                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │  User Input   │───▶│  Router      │───▶│  Planner     │       │
│  │  (Natural     │    │  Agent       │    │  Agent       │       │
│  │   Language)   │    │  (Dispatch)  │    │  (Planning)  │       │
│  └──────────────┘    └──────────────┘    └──────┬───────┘       │
│                    ┌─────────────────────────────┼────────┐      │
│                    ▼                             ▼        ▼      │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │  Clinical         │  │  Tool            │  │  Knowledge   │  │
│  │  Executor         │  │  Executor        │  │  Agent       │  │
│  │  (Clinical)       │  │  (Tool Exec)     │  │  (Knowledge) │  │
│  └────────┬─────────┘  └────────┬─────────┘  └──────┬───────┘  │
│           │                      │                    │          │
│           └──────────────────────┼────────────────────┘          │
│                                  ▼                               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Quality Gate Layer                      │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐          │   │
│  │  │  Plan       │  │  Fact      │  │  Safety    │          │   │
│  │  │  Reviewer   │  │  Checker   │  │  Guardian  │          │   │
│  │  │  (Review)   │  │  (Verify)   │  │  (Safety)  │          │   │
│  │  └────────────┘  └────────────┘  └────────────┘          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                  │                               │
│                                  ▼                               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Response Synthesizer                    │   │
│  │  (Synthesizes all agent outputs into the final response)  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## 3. Agent Role Definitions

### 3.1 Router Agent
**Responsibility**: Understand user intent and dispatch to the correct execution path

```python
class RouterAgent:
    """Analyze user input and decide which agents to invoke"""
    
    def route(self, user_input: str) -> RoutingDecision:
        # 1. Intent recognition
        # 2. Complexity assessment
        # 3. Select execution path
        return RoutingDecision(
            intent="clinical_planning",
            complexity="high",
            agents_needed=["clinical_executor", "knowledge_agent"],
            requires_review=True
        )
```

### 3.2 Planner Agent
**Responsibility**: Decompose complex tasks into executable steps

```python
class PlannerAgent:
    """Decompose complex tasks into a sequence of tool calls"""
    
    def plan(self, task: str, context: dict) -> ExecutionPlan:
        # 1. Analyze task requirements
        # 2. Query available tools
        # 3. Generate execution plan
        # 4. Optimize execution order
        return ExecutionPlan(steps=[...], parallel_groups=[...])
```

### 3.3 Clinical Executor
**Responsibility**: Execute clinically related tool calls

```python
class ClinicalExecutor:
    """Execute clinical tools such as CTV segmentation, OAR segmentation, and dose calculation"""
    
    def execute(self, step: PlanStep) -> ToolResult:
        # 1. Prepare tool parameters
        # 2. Invoke tool
        # 3. Validate results
        # 4. Record execution history
```

### 3.4 Knowledge Agent
**Responsibility**: Retrieve and verify medical knowledge

```python
class KnowledgeAgent:
    """RAG retrieval + web search + fact verification"""
    
    def search(self, query: str) -> KnowledgeResult:
        # 1. Local RAG retrieval
        # 2. Web search (if needed)
        # 3. Result verification
        # 4. Citation tracking
```

### 3.5 Plan Reviewer
**Responsibility**: Review the quality of treatment plans

```python
class PlanReviewer:
    """Independently review the plan and provide improvement suggestions"""
    
    def review(self, plan: dict, dose_metrics: dict) -> ReviewResult:
        # 1. Dosimetric review
        # 2. Clinical guideline review
        # 3. Risk assessment
        # 4. Overall scoring
```

### 3.6 Fact Checker
**Responsibility**: Verify the accuracy and sources of information

```python
class FactChecker:
    """Verify the accuracy of web search results and medical knowledge"""
    
    def verify(self, claims: list, sources: list) -> VerificationResult:
        # 1. Source verification
        # 2. Cross-validation
        # 3. Timeliness check
        # 4. Confidence assessment
```

### 3.7 Safety Guardian
**Responsibility**: Ensure output safety and prevent dangerous operations

```python
class SafetyGuardian:
    """Inspect all outputs to ensure clinical safety"""
    
    def check(self, action: str, context: dict) -> SafetyResult:
        # 1. Dose safety check
        # 2. Operation compliance check
        # 3. Risk alerting
        # 4. Intercept dangerous operations
```

## 4. Quality Gate Mechanism

### 4.1 Trigger Conditions
```python
QUALITY_GATE_TRIGGERS = {
    # Scenarios requiring mandatory review
    "mandatory": [
        "dose_evaluation",        # Dose evaluation results
        "treatment_plan",         # Treatment plan
        "clinical_recommendation", # Clinical recommendation
        "web_search_result",      # Web search results
    ],
    
    # Scenarios with optional review
    "optional": [
        "segmentation_result",    # Segmentation results
        "trajectory_plan",        # Trajectory planning
    ],
}
```

### 4.2 Review Flow
```python
class QualityGate:
    """Quality gate layer"""
    
    def gate(self, output_type: str, content: dict) -> GateResult:
        if output_type in MANDATORY_TRIGGERS:
            # Invoke multiple review agents in parallel
            reviews = parallel([
                self.plan_reviewer.review(content),
                self.fact_checker.verify(content),
                self.safety_guardian.check(content),
            ])
            
            # Overall judgment
            return self._synthesize_reviews(reviews)
        
        return GateResult(passed=True)
```

## 5. Implementation Plan

### 5.1 New File Structure
```
BrachyBot/
├── agents/                    # New: Agent directory
│   ├── __init__.py
│   ├── base_agent.py          # Agent base class
│   ├── router_agent.py        # Router Agent
│   ├── planner_agent.py       # Planner Agent
│   ├── clinical_executor.py   # Clinical Executor
│   ├── knowledge_agent.py     # Knowledge Agent
│   ├── plan_reviewer.py       # Plan Reviewer Agent
│   ├── fact_checker.py        # Fact Checker Agent
│   ├── safety_guardian.py     # Safety Guardian Agent
│   └── response_synthesizer.py # Response Synthesizer
│
├── quality/                   # New: Quality gate
│   ├── __init__.py
│   ├── quality_gate.py        # Quality gate main logic
│   ├── review_aggregator.py   # Review result aggregation
│   └── feedback_loop.py       # Feedback loop
│
└── communication/             # New: Agent communication
    ├── __init__.py
    ├── message_bus.py          # Message bus
    ├── agent_registry.py       # Agent registry
    └── protocol.py             # Communication protocol
```

### 5.2 Core Interface Design

#### Agent Base Class
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
    reasoning: str     # Reasoning process
    suggestions: List[str] = None
    warnings: List[str] = None

class BaseAgent(ABC):
    """Base class for all agents"""
    
    def __init__(self, role: AgentRole, llm_callback=None):
        self.role = role
        self.llm_callback = llm_callback
        self.message_history: List[AgentMessage] = []
    
    @abstractmethod
    def process(self, message: AgentMessage) -> AgentResponse:
        """Process a message and return a response"""
        pass
    
    def send_message(self, receiver: AgentRole, content: Any, 
                     message_type: str = "request") -> AgentMessage:
        """Send a message to another agent"""
        msg = AgentMessage(
            sender=self.role,
            receiver=receiver,
            message_type=message_type,
            content=content
        )
        self.message_history.append(msg)
        return msg
    
    def receive_feedback(self, feedback: AgentMessage):
        """Receive feedback for self-improvement"""
        self.message_history.append(feedback)
```

#### Message Bus
```python
# communication/message_bus.py
from typing import Dict, List, Callable
from collections import defaultdict
import asyncio

class MessageBus:
    """Message bus for inter-agent communication"""
    
    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._history: List[AgentMessage] = []
    
    def subscribe(self, message_type: str, handler: Callable):
        """Subscribe to a message type"""
        self._subscribers[message_type].append(handler)
    
    async def publish(self, message: AgentMessage):
        """Publish a message"""
        self._history.append(message)
        
        # Notify subscribers
        for handler in self._subscribers.get(message.message_type, []):
            await handler(message)
        
        # Notify subscribers of the target agent
        for handler in self._subscribers.get(message.receiver.value, []):
            await handler(message)
    
    def get_history(self, agent_role: AgentRole = None) -> List[AgentMessage]:
        """Get message history"""
        if agent_role:
            return [m for m in self._history 
                   if m.sender == agent_role or m.receiver == agent_role]
        return self._history
```

#### Quality Gate
```python
# quality/quality_gate.py
from typing import List, Dict, Any
from dataclasses import dataclass
from enum import Enum

class GateDecision(Enum):
    PASS = "pass"           # Pass
    CONDITIONAL = "conditional"  # Conditional pass
    REJECT = "reject"       # Reject
    ESCALATE = "escalate"   # Escalate to human

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
    """Quality gate layer - reviews all critical outputs"""
    
    # Output types requiring mandatory review
    MANDATORY_REVIEWS = {
        "treatment_plan",
        "dose_evaluation", 
        "clinical_recommendation",
        "web_search_medical",
    }
    
    # Output types with optional review
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
        """Review output"""
        
        if output_type not in self.MANDATORY_REVIEWS:
            if output_type not in self.OPTIONAL_REVIEWS:
                return GateResult(passed=True, decision=GateDecision.PASS, 
                                reviews=[], final_message="No review needed")
        
        # Invoke review agents in parallel
        reviews = await self._parallel_review(content, context)
        
        # Aggregate results
        gate_result = self._aggregate_reviews(reviews)
        
        # Record history
        self.review_history.append(gate_result)
        
        return gate_result
    
    async def _parallel_review(self, content: Any, 
                              context: Dict) -> List[ReviewResult]:
        """Invoke multiple review agents in parallel"""
        import asyncio
        
        tasks = []
        
        # Plan review
        if "plan_reviewer" in self.agents:
            tasks.append(self.agents["plan_reviewer"].review(content, context))
        
        # Fact check
        if "fact_checker" in self.agents and self._needs_fact_check(content):
            tasks.append(self.agents["fact_checker"].verify(content, context))
        
        # Safety check
        if "safety_guardian" in self.agents:
            tasks.append(self.agents["safety_guardian"].check(content, context))
        
        # Parallel execution
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter exceptions
        valid_results = []
        for r in results:
            if isinstance(r, ReviewResult):
                valid_results.append(r)
            elif isinstance(r, Exception):
                # Log exception but do not block
                pass
        
        return valid_results
    
    def _aggregate_reviews(self, reviews: List[ReviewResult]) -> GateResult:
        """Aggregate review results"""
        if not reviews:
            return GateResult(passed=True, decision=GateDecision.PASS,
                            reviews=[], final_message="No reviews available")
        
        # Compute weighted score
        total_weight = sum(r.confidence for r in reviews)
        if total_weight == 0:
            weighted_score = sum(r.score for r in reviews) / len(reviews)
        else:
            weighted_score = sum(r.score * r.confidence for r in reviews) / total_weight
        
        # Collect all concerns and suggestions
        all_concerns = []
        all_suggestions = []
        for r in reviews:
            all_concerns.extend(r.concerns)
            all_suggestions.extend(r.suggestions)
        
        # Determine decision
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

### 5.3 Integration into the Existing System

#### Modifying AgenticSys.py
```python
# Integrate multi-agent system into BrachyAgent
class BrachyAgent:
    def __init__(self, ...):
        # ... existing initialization code ...
        
        # Initialize multi-agent system
        self._init_multi_agent_system()
    
    def _init_multi_agent_system(self):
        """Initialize the multi-agent system"""
        from agents import (
            RouterAgent, PlannerAgent, ClinicalExecutor,
            KnowledgeAgent, PlanReviewer, FactChecker, 
            SafetyGuardian, ResponseSynthesizer
        )
        from quality import QualityGate
        from communication import MessageBus
        
        # Create message bus
        self.message_bus = MessageBus()
        
        # Create agents
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
        
        # Create quality gate
        self.quality_gate = QualityGate(self.agents)
    
    async def chat_with_multi_agent(self, message: str):
        """Multi-agent version of chat"""
        
        # 1. Router Agent analyzes intent
        routing = await self.agents["router"].process(message)
        
        # 2. Planner Agent formulates a plan
        if routing.complexity == "high":
            plan = await self.agents["planner"].process(routing)
        else:
            plan = None
        
        # 3. Execute plan
        results = []
        if plan:
            for step in plan.steps:
                # Knowledge Agent retrieves relevant knowledge
                if step.needs_knowledge:
                    knowledge = await self.agents["knowledge"].process(step)
                    step.context["knowledge"] = knowledge
                
                # Clinical Executor executes
                result = await self.agents["clinical"].process(step)
                results.append(result)
        else:
            # Execute simple tasks directly
            result = await self.agents["clinical"].process(message)
            results.append(result)
        
        # 4. Quality gate review
        for result in results:
            if result.needs_review:
                gate_result = await self.quality_gate.review(
                    result.output_type, result.content
                )
                
                if not gate_result.passed:
                    # Needs revision or escalation
                    if gate_result.requires_human_review:
                        yield self._format_human_review_request(gate_result)
                    else:
                        # Revise based on feedback
                        result = await self._revise_based_on_feedback(
                            result, gate_result.reviews
                        )
        
        # 5. Synthesize final response
        response = await self.agents["synthesizer"].process(results)
        
        yield response
```

## 6. Comparison with Open Source Libraries Such as OpenCode

### OpenCode's Characteristics
1. **Subagent mechanism**: dispatch an independent subagent for each complex task
2. **Tool isolation**: each subagent has its own tool set
3. **Result aggregation**: the main agent synthesizes results from all subagents

### BrachyBot's Enhancements
1. **Specialized agents**: agents specialized for clinical scenarios
2. **Quality gate**: an independent review layer to ensure output safety
3. **Knowledge verification**: a fact-checking agent to prevent hallucinations
4. **Feedback loop**: continuous improvement based on review results

## 7. Implementation Roadmap

### Phase 1: Foundation Framework (1-2 weeks)
- [ ] Create the `agents/` directory and base classes
- [ ] Implement the `MessageBus` message bus
- [ ] Implement the `RouterAgent` router agent

### Phase 2: Core Agents (2-3 weeks)
- [ ] Implement the `PlanReviewer` plan review agent
- [ ] Implement the `FactChecker` fact-checking agent
- [ ] Implement the `SafetyGuardian` safety guardian agent
- [ ] Implement the `QualityGate` quality gate

### Phase 3: Integration Testing (1-2 weeks)
- [ ] Integrate into `AgenticSys.py`
- [ ] Modify `chat_with_stream()` to use multi-agent
- [ ] Add frontend display of review results

### Phase 4: Optimization and Iteration (Continuous)
- [ ] Collect user feedback
- [ ] Optimize agent prompts
- [ ] Add more specialized agents

## 8. Configuration Example

```yaml
# config/multi_agent.yaml
multi_agent:
  enabled: true
  
  agents:
    router:
      model: "deepseek"  # Use a cheaper model for routing
      temperature: 0.1
    
    planner:
      model: "deepseek"
      temperature: 0.2
    
    plan_reviewer:
      model: "deepseek"  # Use a stronger model for review
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
      temperature: 0.0  # Low temperature for fact checking
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

## 9. Example Scenarios

### Scenario 1: Treatment Plan Review
```
User: "Please generate a treatment plan for this pancreatic cancer patient"

[Router Agent] → Recognized as a complex clinical task
[Planner Agent] → Formulates an execution plan:
  1. CTV segmentation
  2. OAR segmentation
  3. Trajectory planning
  4. Seed planning
  5. Dose calculation
  6. Dose evaluation

[Clinical Executor] → Executes steps 1-6 as planned

[Quality Gate] → Triggers review
  [Plan Reviewer] → Checks dosimetric parameters
    - D90: 0.75 (low, consider adding seeds)
    - V100: 80.3% (below the 95% target)
    - Score: 41/100 (needs improvement)
  
  [Safety Guardian] → Safety check
    - Max dose 70.26 (needs confirmation of OAR tolerance)
    - Recommend checking duodenum dose

[Response Synthesizer] → Synthesizes the response
  - Present plan results
  - Show review comments
  - Provide improvement suggestions
```

### Scenario 2: Web Search Verification
```
User: "What are the latest guidelines for pancreatic cancer seed implantation?"

[Router Agent] → Recognized as a knowledge query
[Knowledge Agent] → Web search
  - Search result: NCCN Guidelines 2024 edition...

[Quality Gate] → Triggers fact checking
  [Fact Checker] → Verifies search results
    - Source: nccn.org ✓
    - Timeliness: 2024 ✓
    - Citations: specific citations present ✓
    - Confidence: 0.9

[Response Synthesizer] → Generates response
  - Present guideline content
  - Annotate sources and confidence
  - Provide citation links
```

## 10. Summary

Core advantages of this approach:

1. **Specialized division of labor**: each agent focuses on its own domain
2. **Quality gate**: critical outputs must undergo independent review
3. **Fact verification**: prevent LLM hallucinations and ensure information accuracy
4. **Safety guardian**: clinical safety is the top priority
5. **Extensibility**: easy to add new agents and rules
6. **Transparency**: users can see the review process and results

Compatibility with the existing system:
- Extends the existing `MultiAgentCritic`
- Leverages the existing `EnhancedAgentIntegration` framework
- Reuses the existing LLM Router and Provider
- Maintains SSE streaming communication with the frontend
