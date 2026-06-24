"""
Router Agent
============
Analyzes user input and routes to appropriate agents.
Inspired by OpenCode's task routing and LangChain's agent routing.
"""

import re
import logging
from typing import List, Dict, Any
from .base_agent import LLMCapableAgent
from communication.protocol import (
    AgentRole, AgentMessage, AgentResponse, MessageType,
    RoutingDecision, Priority
)

logger = logging.getLogger(__name__)


class RouterAgent(LLMCapableAgent):
    """
    Routes user requests to appropriate agents based on intent analysis.

    Responsibilities:
    1. Understand user intent
    2. Assess task complexity
    3. Determine which agents are needed
    4. Decide if quality review is required
    """

    # Intent patterns for quick matching.
    # ORDER MATERS: first match wins. "follow_up" must come before
    # "clinical_planning" so that requests like "规划的结论可以详细一些吗"
    # (which contains "规划") are classified as follow-up, not planning.
    INTENT_PATTERNS = {
        "follow_up": {
            # Requests for more detail, clarification, or modification
            # of an EXISTING plan. These should NOT trigger re-planning.
            "keywords": ["详细", "具体", "解释", "为什么", "原因", "意义",
                         "more detail", "explain", "why", "clarify",
                         "修改", "调整", "改", "modify", "adjust",
                         "对比", "比较", "compare", "different"],
            "complexity": "low",
            "agents": [AgentRole.KNOWLEDGE],
            "requires_review": False,
        },
        "clinical_planning": {
            "keywords": ["计划", "规划", "plan", "planning", "植入", "implant", "粒子", "seed",
                         "执行", "开始", "运行", "execute", "run", "start"],
            "complexity": "high",
            "agents": [AgentRole.CLINICAL_EXECUTOR, AgentRole.KNOWLEDGE],
            "requires_review": True,
        },
        "segmentation": {
            "keywords": ["分割", "segment", "ctv", "oar", "器官", "organ", "肿瘤", "tumor"],
            "complexity": "medium",
            "agents": [AgentRole.CLINICAL_EXECUTOR],
            "requires_review": False,
        },
        "dose_evaluation": {
            "keywords": ["计算剂量", "evaluate dose", "评估剂量", "dose calc", "dvh分析", "DVH分析", "dose_engine", "dose_evaluation"],
            "complexity": "medium",
            "agents": [AgentRole.CLINICAL_EXECUTOR],
            "requires_review": True,
        },
        "knowledge_query": {
            "keywords": ["什么是", "解释", "指南", "guide", "标准", "standard", "what is", "explain",
                         "查询", "query", "介绍", "introduce", "了解", "learn", "知识", "knowledge",
                         "约束", "constraint", "限制", "limit", "耐受", "tolerance",
                         "剂量标准", "剂量要求", "剂量约束", "剂量限制", "处方剂量", "prescription dose",
                         "dose constraint", "dose limit", "dose standard", "dose requirement",
                         "为什么", "why", "区别", "difference", "比较", "compare"],
            "complexity": "low",
            "agents": [AgentRole.KNOWLEDGE],
            "requires_review": False,
        },
        # BUG FIX 2026-06-16 (web search quality): the user asked
        # "请你全网搜索权威指南，各个部位的肿瘤处方剂量应该如何设计"
        # and the previous router matched "剂量" → dose_engine (a
        # computation tool), which then errored. Add explicit
        # web_search intent for any query mentioning "search",
        # "guideline", "PubMed", "NCCN", "ESTRO", "ICRU",
        # "文献", "联网", "指南", etc. — anything that sounds
        # like a literature lookup rather than a computation.
        "web_search": {
            "keywords": [
                "search", "搜索", "检索", "联网", "全网", "online",
                "pubmed", "pmid", "nccn", "estro", "icru", "aapm",
                "csco", "abs", "guideline", "指南", "标准",
                "文献", "literature", "review", "paper", "论文",
                "consensus", "共识", "权威", "authoritative",
                "最新", "latest", "最新指南", "2024", "2025", "2026",
                "prescription dose", "处方剂量",
                "头颈部", "胸部", "盆腔", "腹部", "肝", "胰腺", "前列腺", "宫颈",
                "head neck", "thorax", "pelvis", "abdomen", "liver",
                "pancreas", "prostate", "cervix", "lung", "食管",
            ],
            "complexity": "medium",
            "agents": [AgentRole.KNOWLEDGE],
            "requires_review": False,
        },
        "optimization": {
            "keywords": ["优化", "optimize", "调整", "adjust", "改进", "improve"],
            "complexity": "high",
            "agents": [AgentRole.PLANNER, AgentRole.CLINICAL_EXECUTOR],
            "requires_review": True,
        },
        "status_check": {
            "keywords": ["状态", "status", "结果", "result", "当前", "current"],
            "complexity": "low",
            "agents": [],
            "requires_review": False,
        },
    }

    def __init__(self, llm_callback=None):
        super().__init__(AgentRole.ROUTER, llm_callback)

    async def process(self, message: AgentMessage) -> AgentResponse:
        """
        Analyze user input and determine routing.

        Args:
            message: Contains user input in content

        Returns:
            AgentResponse with RoutingDecision as result
        """
        user_input = message.content if isinstance(message.content, str) else str(message.content)

        # Try quick pattern matching first (with conversation state awareness)
        conversation_state = getattr(self, '_conversation_state', None)
        routing = self._quick_route(user_input, conversation_state)

        # If no clear match, use LLM for complex routing
        if routing.confidence < 0.6 and self.llm_callback:
            routing = await self._llm_route(user_input)

        return AgentResponse(
            agent_role=self.role,
            success=True,
            result=routing,
            confidence=routing.confidence if hasattr(routing, 'confidence') else 0.8,
            reasoning=routing.reasoning if hasattr(routing, 'reasoning') else "",
        )

    def _quick_route(self, user_input: str, conversation_state: dict = None) -> RoutingDecision:
        """
        Quick pattern-based routing, aware of conversation state.

        When planning is already completed and the user asks something
        that matches planning keywords but also contains clarification
        keywords (详细, 为什么, etc.), classify as follow_up — not
        clinical_planning. This prevents the LLM from re-running tools.

        Args:
            user_input: User's input text
            conversation_state: Structured state from AgentMemory

        Returns:
            RoutingDecision
        """
        input_lower = user_input.lower()
        best_match = None
        best_score = 0

        for intent, config in self.INTENT_PATTERNS.items():
            score = 0
            matched_keywords = []

            for keyword in config["keywords"]:
                if keyword.lower() in input_lower:
                    score += 1
                    matched_keywords.append(keyword)

            if score > best_score:
                best_score = score
                best_match = {
                    "intent": intent,
                    "config": config,
                    "matched_keywords": matched_keywords,
                }

        if best_match and best_score > 0:
            config = best_match["config"]
            intent = best_match["intent"]

            # STATE-AWARE OVERRIDE: if planning is already completed,
            # any planning-keyword match that ALSO has clarification
            # keywords should be classified as follow_up. This is the
            # structural fix for "规划的结论可以详细一些吗" being
            # misclassified as clinical_planning.
            cs = conversation_state or {}
            if intent == "clinical_planning" and cs.get("planning_completed"):
                clarification_keywords = ["详细", "具体", "解释", "为什么", "原因",
                                          "意义", "more detail", "explain", "why"]
                has_clarification = any(k in input_lower for k in clarification_keywords)
                if has_clarification:
                    intent = "follow_up"
                    config = self.INTENT_PATTERNS["follow_up"]
                    best_match["matched_keywords"] = [k for k in clarification_keywords if k in input_lower]

            return RoutingDecision(
                intent=intent,
                complexity=config["complexity"],
                agents_needed=config["agents"],
                requires_review=config["requires_review"],
                context={"matched_keywords": best_match["matched_keywords"]},
                reasoning=f"Pattern match: {intent} "
                         f"(keywords: {', '.join(best_match['matched_keywords'])})",
                confidence=min(0.5 + best_score * 0.15, 0.95),
            )

        # Default routing for unclear input
        return RoutingDecision(
            intent="general",
            complexity="low",
            agents_needed=[AgentRole.SYNTHESIZER],
            requires_review=False,
            reasoning="No clear intent detected, routing to synthesizer",
            confidence=0.3,
        )

    async def _llm_route(self, user_input: str) -> RoutingDecision:
        """
        LLM-based routing for complex inputs.

        Args:
            user_input: User's input text

        Returns:
            RoutingDecision
        """
        # Use the loaded system prompt from config (self._system_prompt),
        # append JSON format instruction.
        system_prompt = (
            self._system_prompt
            + "\n\nRespond in JSON format:\n"
            + '{"intent":"...","complexity":"...","agents_needed":["..."],'
            + '"requires_review":true,"reasoning":"..."}'
        )

        try:
            response = await self.call_llm(user_input, system_prompt, temperature=0.1)

            # Parse JSON response
            import json
            # Try to extract JSON from response
            json_match = re.search(r'\{[^{}]+\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())

                # Map agent names to roles
                agent_map = {
                    "clinical_executor": AgentRole.CLINICAL_EXECUTOR,
                    "knowledge": AgentRole.KNOWLEDGE,
                    "planner": AgentRole.PLANNER,
                    "plan_reviewer": AgentRole.PLAN_REVIEWER,
                    "fact_checker": AgentRole.FACT_CHECKER,
                    "safety_guardian": AgentRole.SAFETY_GUARDIAN,
                    "synthesizer": AgentRole.SYNTHESIZER,
                }

                agents_needed = []
                for agent_name in data.get("agents_needed", []):
                    if agent_name in agent_map:
                        agents_needed.append(agent_map[agent_name])

                return RoutingDecision(
                    intent=data.get("intent", "general"),
                    complexity=data.get("complexity", "medium"),
                    agents_needed=agents_needed,
                    requires_review=data.get("requires_review", False),
                    reasoning=data.get("reasoning", "LLM-based routing"),
                    confidence=0.85,
                )

        except Exception as e:
            logger.warning(f"LLM routing failed: {e}")

        # Fallback to general routing
        return RoutingDecision(
            intent="general",
            complexity="medium",
            agents_needed=[AgentRole.CLINICAL_EXECUTOR, AgentRole.SYNTHESIZER],
            requires_review=False,
            reasoning="LLM routing failed, using default",
            confidence=0.4,
        )

    def add_intent_pattern(self, intent: str, keywords: List[str],
                          complexity: str = "medium",
                          agents: List[AgentRole] = None,
                          requires_review: bool = False):
        """
        Add a custom intent pattern.

        Args:
            intent: Intent name
            keywords: Keywords to match
            complexity: Task complexity
            agents: Agents needed
            requires_review: Whether review is required
        """
        self.INTENT_PATTERNS[intent] = {
            "keywords": keywords,
            "complexity": complexity,
            "agents": agents or [AgentRole.CLINICAL_EXECUTOR],
            "requires_review": requires_review,
        }
        logger.info(f"Added intent pattern: {intent}")
