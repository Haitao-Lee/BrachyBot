"""
Completeness Checker Agent
===========================
Dual-layer requirement coverage checker.

Layer 1 (deterministic): keyword extraction + matching. Cannot be wrong.
Layer 2 (LLM, optional): semantic matching for paraphrased requirements.
"""

import json
import re
import logging
from typing import Dict, List, Any, Optional
from .base_agent import LLMCapableAgent
from communication.protocol import (
    AgentRole, AgentMessage, AgentResponse, MessageType,
    ReviewResult, Priority
)

logger = logging.getLogger(__name__)


class CompletenessChecker(LLMCapableAgent):
    """
    Checks if the final response addresses every user requirement.

    Layer 1 (deterministic):
    - Extract requirements from user message (numbered lists, action verbs)
    - Check keyword overlap with response + tool steps
    - Always correct for exact matches

    Layer 2 (LLM, optional):
    - Semantic matching: "分割 CTV" matches "segment the clinical target volume"
    - Understand paraphrases and synonyms
    - If LLM fails, only Layer 1 results are returned
    """

    _COMPLETENESS_PROMPT = """You are a completeness checker. Given the user's request and the assistant's response, check if EVERY requirement was addressed.

## User Request
{user_message}

## Assistant Response (first 1500 chars)
{response_summary}

## Tool Execution Steps
{tool_steps}

## Rules
- A requested action is fulfilled only when its tool step completed successfully
- A failed/cancelled action is not fulfilled; the response must clearly report the failure and next action
- Short greetings / simple questions with no specific requirements → always pass
- Do NOT judge clinical quality — only whether each requirement was completed or explicitly reported as blocked

## Output Format (JSON)
{{
    "requirements": ["requirement 1", "requirement 2", "requirement 3"],
    "addressed": ["requirement 1", "requirement 2"],
    "missed": ["requirement 3"],
    "confidence": 0.0-1.0
}}"""

    def __init__(self, llm_callback=None):
        super().__init__(AgentRole.COMPLETENESS_CHECKER, llm_callback)
        self._conversation_state = {}

    @property
    def name(self) -> str:
        return "completeness_checker"

    async def process(self, message: AgentMessage) -> AgentResponse:
        content = message.content
        user_message = content.get("user_message", "")
        response = content.get("response", "")
        steps = content.get("steps", [])
        # Store conversation_state for LLM context
        self._conversation_state = content.get("conversation_state", {})
        self._lang = content.get("lang", "en")

        # ── Priority: LLM semantic matching (most accurate) ─────────
        llm_results = None
        if self.llm_callback:
            try:
                llm_results = await self._llm_check(user_message, response, steps)
                if llm_results:
                    logger.debug("LLM completeness check succeeded")
            except Exception as e:
                logger.debug(f"LLM completeness check failed, using deterministic fallback: {e}")

        # ── Fallback: Deterministic extraction + matching ───────────
        if not llm_results:
            det_requirements = self._extract_requirements(user_message)

            if not det_requirements:
                return AgentResponse(
                    agent_role=self.role,
                    success=True,
                    result=ReviewResult(
                        reviewer="Completeness Checker", decision="pass",
                        score=10.0, concerns=[], suggestions=[], confidence=0.8,
                    ),
                    confidence=0.8,
                )

            det_addressed = []
            det_missed = []
            for req in det_requirements:
                if self._is_addressed(req, response, steps):
                    det_addressed.append(req)
                else:
                    det_missed.append(req)

            final_addressed = det_addressed
            final_missed = det_missed
            final_requirements = det_requirements
        else:
            # Use LLM results
            final_addressed = llm_results.get("addressed", [])
            final_missed = llm_results.get("missed", [])
            final_requirements = llm_results.get("requirements", [])

        total = len(final_requirements)
        addressed_count = len(final_addressed)
        score = (addressed_count / total * 10) if total > 0 else 10.0

        concerns = [f"Missed: {m}" for m in final_missed]
        suggestions = [f"Address: {m}" for m in final_missed[:3]]

        result = ReviewResult(
            reviewer="Completeness Checker",
            decision="pass" if not final_missed else "conditional",
            score=score,
            concerns=concerns,
            suggestions=suggestions,
            confidence=0.7 if not llm_results else 0.85,
        )

        return AgentResponse(
            agent_role=self.role,
            success=True,
            result=result,
            confidence=result.confidence,
            reasoning=f"Addressed {addressed_count}/{total} requirements",
            suggestions=suggestions,
            warnings=concerns,
        )

    def _extract_requirements(self, message: str) -> List[str]:
        """Deterministic requirement extraction."""
        # Numbered list
        numbered = re.findall(
            r'(?:^|\n)\s*\d+[.、)]\s*(.+?)(?=\n\s*\d+[.、)]|\n\n|$)',
            message, re.MULTILINE
        )
        if numbered:
            return [r.strip() for r in numbered if r.strip()]

        # Action verb detection
        action_verbs = [
            'segment', 'analyze', 'evaluate', 'calculate', 'generate',
            'export', 'search', 'find', 'compare', 'optimize', 'plan',
            '分割', '分析', '评估', '计算', '生成', '导出', '搜索', '查找',
            '比较', '优化', '规划',
        ]
        requirements = []
        for verb in action_verbs:
            matches = re.findall(
                rf'(?:{verb})\s[^,，;。.!?！？\n]+',
                message, re.IGNORECASE
            )
            requirements.extend(m.strip() for m in matches)

        if requirements:
            return list(dict.fromkeys(requirements))

        if len(message.strip()) > 5:
            return [message.strip()]

        return []

    def _is_addressed(self, requirement: str, response: str, steps: List[Dict]) -> bool:
        """Conservative exact-token fallback; semantic matching belongs to the LLM."""
        req_words = self._tokens(requirement) - {
            'the', 'a', 'an', 'is', 'are', 'of', 'to', 'in', 'for',
            'and', 'or', 'on', 'with', 'by', 'at', 'from', 'that',
            'this', 'it', 'be', 'as', 'not', 'no', 'please', 'help',
            'me', 'my', 'your', 'you', 'i', 'we', 'can', 'will',
            '的', '了', '吗', '呢', '吧', '啊', '我', '你', '他',
        }
        if not req_words:
            return True

        if req_words.issubset(self._tokens(response)):
            return True

        for step in steps:
            if str(step.get("status", "")).lower() not in {"done", "success", "completed"}:
                continue
            step_text = json.dumps(step, ensure_ascii=False).lower()
            if req_words.issubset(self._tokens(step_text)):
                return True

        return False

    @staticmethod
    def _tokens(text: str) -> set[str]:
        """Tokenize English words and CJK bigrams without external NLP deps."""
        lowered = str(text).lower()
        tokens = set(re.findall(r"[a-z0-9_]+", lowered))
        for sequence in re.findall(r"[\u3400-\u9fff]+", lowered):
            if len(sequence) == 1:
                tokens.add(sequence)
            else:
                tokens.update(sequence[i:i + 2] for i in range(len(sequence) - 1))
        return tokens

    async def _llm_check(self, user_message: str, response: str,
                          steps: List[Dict]) -> Optional[dict]:
        """Layer 2: LLM semantic completeness check with full context."""
        if not self.llm_callback:
            return None

        response_summary = response[:1500]
        tool_steps = "\n".join(
            f"- {s.get('tool', '?')}: {s.get('status', '?')}"
            for s in steps if s.get("type") == "tool"
        )[:500] or "No tools executed"

        # Add conversation state context
        conv_state = self._conversation_state if hasattr(self, '_conversation_state') else {}
        ctx_lines = []
        if conv_state.get("ctv_segmented"):
            ctx_lines.append("- CTV segmentation: completed")
        if conv_state.get("oar_segmented"):
            ctx_lines.append("- OAR segmentation: completed")
        if conv_state.get("planning_completed"):
            ctx_lines.append("- Treatment planning: completed")
        ctx_note = "\n".join(ctx_lines)
        if ctx_note:
            tool_steps = f"## Conversation State\n{ctx_note}\n\n## Tool Steps\n{tool_steps}"

        prompt = self._COMPLETENESS_PROMPT.format(
            user_message=user_message,
            response_summary=response_summary,
            tool_steps=tool_steps,
        )

        if getattr(self, "_lang", "en") == "zh":
            prompt += "\n\n**Language**: 请用中文回答。"

        try:
            resp = await self.call_llm(prompt, temperature=0.1)
            json_match = re.search(r'\{[^{}]+\}', resp, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            logger.debug(f"LLM completeness check failed: {e}")

        return None

    def format_as_appendix(self, result: ReviewResult, lang: str = "en") -> str:
        """Format as appendix. Empty if all requirements addressed."""
        if not result or not result.concerns:
            return ""

        if lang == "zh":
            lines = [f"### 📋 需求覆盖检查 (覆盖: {result.score / 10:.0%})"]
            if result.concerns:
                lines.append("\n**未响应的需求**:")
                for concern in result.concerns[:5]:
                    lines.append(f"- {concern}")
        else:
            lines = [f"### 📋 Requirement Coverage ({result.score / 10:.0%})"]
            if result.concerns:
                lines.append("\n**Missed requirements**:")
                for concern in result.concerns[:5]:
                    lines.append(f"- {concern}")

        return "\n".join(lines)
