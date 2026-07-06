"""
Context Density Optimizer
==========================
Maximizes contextual information density within a fixed token budget.
Inspired by GenericAgent's core principle: long-horizon performance is determined
not by context length, but by how much decision-relevant information is maintained.

Three failure modes addressed:
1. Positional bias: mid-context evidence gets buried
2. Irrelevant content: actively degrades reasoning
3. Effective context length: ~10x shorter than nominal window
"""

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ContextSegment:
    """A segment of context with metadata for density scoring."""
    content: str
    segment_type: str
    relevance: float = 1.0
    recency: float = 1.0
    importance: float = 1.0
    token_estimate: int = 0

    @property
    def density_score(self) -> float:
        return self.relevance * 0.4 + self.recency * 0.3 + self.importance * 0.3


class ContextDensityOptimizer:
    """
    Manages context window to maximize decision-relevant information density.
    
    Strategies:
    1. Tiered retention: critical info always kept, optional info pruned
    2. Compression: summarize verbose sections while preserving key facts
    3. Rotation: move older but relevant info to summary form
    4. Token budgeting: enforce hard limits per context category
    """

    def __init__(
        self,
        max_tokens: int = 8000,
        system_prompt_tokens: int = 1500,
        tool_desc_tokens: int = 2000,
        memory_tokens: int = 1500,
        conversation_tokens: int = 3000,
    ):
        self.max_tokens = max_tokens
        self.budget = {
            "system_prompt": system_prompt_tokens,
            "tool_descriptions": tool_desc_tokens,
            "memory_context": memory_tokens,
            "conversation": conversation_tokens,
        }
        self.compression_threshold = 0.7

    def estimate_tokens(self, text: str) -> int:
        rough = len(text) / 4
        return int(rough)

    def build_context(self, system_prompt: str, tool_descriptions: str,
                      memory_context: str, conversation_history: list[str],
                      current_task: str) -> dict:
        segments = []

        segments.append(ContextSegment(
            content=system_prompt, segment_type="system_prompt",
            relevance=1.0, recency=1.0, importance=1.0,
            token_estimate=self.estimate_tokens(system_prompt),
        ))

        segments.append(ContextSegment(
            content=tool_descriptions, segment_type="tool_descriptions",
            relevance=0.9, recency=1.0, importance=0.9,
            token_estimate=self.estimate_tokens(tool_descriptions),
        ))

        if memory_context:
            segments.append(ContextSegment(
                content=memory_context, segment_type="memory_context",
                relevance=0.8, recency=0.7, importance=0.8,
                token_estimate=self.estimate_tokens(memory_context),
            ))

        for i, msg in enumerate(reversed(conversation_history)):
            recency = 1.0 - (i * 0.15)
            segments.append(ContextSegment(
                content=msg, segment_type="conversation",
                relevance=0.7, recency=max(0.1, recency), importance=0.6,
                token_estimate=self.estimate_tokens(msg),
            ))

        segments.append(ContextSegment(
            content=current_task, segment_type="current_task",
            relevance=1.0, recency=1.0, importance=1.0,
            token_estimate=self.estimate_tokens(current_task),
        ))

        total_tokens = sum(s.token_estimate for s in segments)

        if total_tokens > self.max_tokens:
            segments = self._prune_and_compress(segments)

        assembled = self._assemble(segments)
        return {
            "prompt": assembled,
            "token_count": self.estimate_tokens(assembled),
            "segments_kept": len(segments),
            "density": self._calculate_density(assembled),
        }

    def _prune_and_compress(self, segments: list[ContextSegment]) -> list[ContextSegment]:
        segments.sort(key=lambda s: s.density_score, reverse=True)

        required = []
        optional = []
        for seg in segments:
            if seg.segment_type in ("system_prompt", "current_task"):
                required.append(seg)
            else:
                optional.append(seg)

        required_tokens = sum(s.token_estimate for s in required)
        remaining_budget = max(0, self.max_tokens - required_tokens)

        result = list(required)
        for seg in optional:
            if seg.token_estimate <= remaining_budget:
                result.append(seg)
                remaining_budget -= seg.token_estimate
            else:
                if remaining_budget <= 0:
                    continue
                compressed = self._compress_segment(seg, remaining_budget)
                if compressed and self.estimate_tokens(compressed) > 50:
                    result.append(ContextSegment(
                        content=compressed, segment_type=seg.segment_type,
                        relevance=seg.relevance, recency=seg.recency,
                        importance=seg.importance,
                        token_estimate=self.estimate_tokens(compressed),
                    ))
                    remaining_budget -= self.estimate_tokens(compressed)

        result.sort(key=lambda s: s.segment_type == "current_task", reverse=True)
        return result

    def _compress_segment(self, segment: ContextSegment, max_tokens: int) -> Optional[str]:
        content = segment.content
        target_tokens = min(max_tokens, int(segment.token_estimate * self.compression_threshold))

        if segment.segment_type == "tool_descriptions":
            return self._compress_tool_descriptions(content, target_tokens)
        elif segment.segment_type == "conversation":
            return self._compress_conversation(content, target_tokens)
        elif segment.segment_type == "memory_context":
            return self._compress_memory(content, target_tokens)

        words = content.split()
        target_words = target_tokens * 2
        if len(words) > target_words:
            return " ".join(words[:target_words]) + "..."
        return content

    def _compress_tool_descriptions(self, content: str, max_tokens: int) -> str:
        tools = content.split("\n\n")
        compressed = []
        current_tokens = 0
        for tool in tools:
            tool_tokens = self.estimate_tokens(tool)
            if current_tokens + tool_tokens <= max_tokens:
                compressed.append(tool)
                current_tokens += tool_tokens
            else:
                name_match = re.search(r"(?:Tool|Name):\s*(\w+)", tool)
                desc_match = re.search(r"(?:Description|desc):\s*(.+?)(?:\n|$)", tool)
                if name_match:
                    summary = f"Tool: {name_match.group(1)}"
                    if desc_match:
                        summary += f" - {desc_match.group(1)[:100]}"
                    compressed.append(summary)
        return "\n\n".join(compressed)

    def _compress_conversation(self, content: str, max_tokens: int) -> str:
        lines = content.split("\n")
        if len(lines) <= 4:
            return content

        first_lines = lines[:2]
        last_lines = lines[-2:]
        middle_summary = f"\n... [{len(lines) - 4} intermediate messages omitted for brevity] ...\n"
        compressed = "\n".join(first_lines) + middle_summary + "\n".join(last_lines)

        if self.estimate_tokens(compressed) > max_tokens:
            words = content.split()
            target_words = max_tokens * 2
            if len(words) > target_words:
                return " ".join(words[:target_words]) + "..."
        return compressed

    def _compress_memory(self, content: str, max_tokens: int) -> str:
        facts = content.split("\n")
        important = [f for f in facts if any(kw in f.lower() for kw in ["critical", "important", "warning", "must"])]
        other = [f for f in facts if f not in important]

        result = list(important)
        remaining = max_tokens - sum(self.estimate_tokens(f) for f in important)

        for fact in other:
            if self.estimate_tokens(fact) <= remaining:
                result.append(fact)
                remaining -= self.estimate_tokens(fact)

        return "\n".join(result)

    def _assemble(self, segments: list[ContextSegment]) -> str:
        parts = []
        type_order = ["system_prompt", "tool_descriptions", "memory_context", "conversation", "current_task"]
        for t in type_order:
            for seg in segments:
                if seg.segment_type == t:
                    parts.append(seg.content)
        return "\n\n".join(parts)

    def _calculate_density(self, text: str) -> float:
        decision_keywords = [
            "tool", "execute", "call", "run", "plan", "dose", "ctv", "oar",
            "segment", "evaluate", "check", "verify", "result", "success",
            "fail", "error", "warning", "critical", "important", "must",
            "should", "recommend", "optimal", "best", "worst", "next",
        ]
        words = text.lower().split()
        if not words:
            return 0.0
        keyword_count = sum(1 for w in words if w in decision_keywords)
        return keyword_count / len(words)

    def get_budget_status(self, current_usage: dict) -> dict:
        status = {}
        total_used = 0
        total_budget = sum(self.budget.values())
        for category, used in current_usage.items():
            budget = self.budget.get(category, 0)
            pct = (used / budget * 100) if budget > 0 else 0
            status[category] = {"used": used, "budget": budget, "pct": round(pct, 1)}
            total_used += used
        status["total"] = {"used": total_used, "budget": total_budget, "pct": round(total_used / total_budget * 100, 1)}
        return status
