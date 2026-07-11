"""
Experience Memory — Self-Evolving Experience Store
===================================================
Stores successful/failed execution traces, extracts patterns,
and enables the agent to learn from its own history.
"""

import os
import json
import time
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from collections import Counter

logger = logging.getLogger(__name__)


@dataclass
class ExperienceEntry:
    """A single experience: user intent → tool chain → outcome."""
    id: str
    timestamp: float
    user_intent: str
    context: Dict[str, Any]
    tool_chain: List[Dict]
    outcome: str
    success: bool
    metrics: Dict[str, Any]
    lesson: str = ""
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "user_intent": self.user_intent,
            "context": {k: str(v)[:200] for k, v in self.context.items()},
            "tool_chain": self.tool_chain,
            "outcome": self.outcome,
            "success": self.success,
            "metrics": self.metrics,
            "lesson": self.lesson,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "ExperienceEntry":
        return cls(**d)


class ExperienceMemory:
    """
    Persistent store of agent experiences.
    Enables learning from past successes and failures.
    """

    def __init__(self, data_dir: str = None, session_id: str = "default"):
        self.session_id = session_id
        self.data_dir = data_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data", session_id
        )
        self.experience_file = os.path.join(self.data_dir, "experiences.json")
        self.pattern_file = os.path.join(self.data_dir, "experience_patterns.json")
        self.experiences: List[ExperienceEntry] = []
        self.patterns: List[Dict] = []
        self._load()

    def _load(self):
        os.makedirs(self.data_dir, exist_ok=True)
        if os.path.exists(self.experience_file):
            try:
                with open(self.experience_file, "r") as f:
                    data = json.load(f)
                self.experiences = [ExperienceEntry.from_dict(e) for e in data]
            except Exception as e:
                logger.warning(f"Failed to load experiences: {e}")
                self.experiences = []
        if os.path.exists(self.pattern_file):
            try:
                with open(self.pattern_file, "r") as f:
                    self.patterns = json.load(f)
            except Exception:
                self.patterns = []

    def _save(self):
        try:
            with open(self.experience_file, "w") as f:
                json.dump([e.to_dict() for e in self.experiences], f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Failed to save experiences: {e}")

    def _save_patterns(self):
        try:
            with open(self.pattern_file, "w") as f:
                json.dump(self.patterns, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Failed to save patterns: {e}")

    def clear(self):
        """Clear all experiences and patterns."""
        self.experiences.clear()
        self.patterns.clear()
        logger.info(f"ExperienceMemory: Cleared all experiences for session {self.session_id}")

    def record(self, user_intent: str, context: Dict, tool_chain: List[Dict],
               outcome: str, success: bool, metrics: Dict = None,
               lesson: str = "", tags: List[str] = None) -> ExperienceEntry:
        """Record a new experience."""
        entry_id = hashlib.md5(
            f"{user_intent}{time.time()}".encode(), usedforsecurity=False
        ).hexdigest()[:12]
        entry = ExperienceEntry(
            id=entry_id,
            timestamp=time.time(),
            user_intent=user_intent,
            context=context,
            tool_chain=tool_chain,
            outcome=outcome,
            success=success,
            metrics=metrics or {},
            lesson=lesson,
            tags=tags or self._auto_tag(user_intent, tool_chain),
        )
        self.experiences.append(entry)
        self._save()
        logger.info(f"Experience recorded: {entry_id} success={success}")
        return entry

    def _auto_tag(self, intent: str, tool_chain: List[Dict]) -> List[str]:
        tags = []
        intent_lower = intent.lower()
        if any(k in intent_lower for k in ["segment", "segmentation"]):
            tags.append("segmentation")
        if any(k in intent_lower for k in ["plan", "planning"]):
            tags.append("planning")
        if any(k in intent_lower for k in ["eval", "evaluation", "dose", "dosimetry"]):
            tags.append("evaluation")
        if any(k in intent_lower for k in ["optim", "optimize", "adjust", "refine"]):
            tags.append("optimization")
        if any(k in intent_lower for k in ["intra", "intraop", "replan", "replanning"]):
            tags.append("intraoperative")
        tools_used = [t.get("tool", "") for t in tool_chain]
        if "ctv_segmentation" in tools_used:
            tags.append("ctv")
        if "oar_segmentation" in tools_used:
            tags.append("oar")
        if "seed_planning" in tools_used:
            tags.append("seed")
        if "dose_evaluation" in tools_used:
            tags.append("dose")
        return list(set(tags))

    def find_similar(self, query: str, top_k: int = 5, tag_filter: str = None) -> List[ExperienceEntry]:
        """Find experiences similar to the query."""
        query_words = set(query.lower().split())
        scored = []
        for exp in self.experiences:
            score = 0
            exp_words = set(exp.user_intent.lower().split())
            score += len(query_words & exp_words) * 2
            for tag in exp.tags:
                if tag in query_words:
                    score += 3
            if tag_filter and tag_filter not in exp.tags:
                score = 0
            if exp.success:
                score += 1
            if score > 0:
                scored.append((score, exp))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [exp for _, exp in scored[:top_k]]

    def get_successful_chains(self, tag: str = None, min_count: int = 2) -> List[Dict]:
        """Get tool chains that succeeded repeatedly."""
        chain_counter = Counter()
        chain_examples = {}
        for exp in self.experiences:
            if not exp.success:
                continue
            if tag and tag not in exp.tags:
                continue
            chain_key = tuple(t.get("tool", "") for t in exp.tool_chain)
            chain_counter[chain_key] += 1
            if chain_key not in chain_examples:
                chain_examples[chain_key] = {
                    "chain": exp.tool_chain,
                    "intent": exp.user_intent,
                    "metrics": exp.metrics,
                    "lesson": exp.lesson,
                }
        return [
            {**chain_examples[chain], "count": count}
            for chain, count in chain_counter.most_common()
            if count >= min_count
        ]

    def get_failure_patterns(self, min_count: int = 2) -> List[Dict]:
        """Get recurring failure patterns with lessons."""
        failure_lessons = []
        for exp in self.experiences:
            if exp.success or not exp.lesson:
                continue
            failure_lessons.append({
                "intent": exp.user_intent,
                "error": exp.outcome,
                "lesson": exp.lesson,
                "tool_chain": [t.get("tool", "") for t in exp.tool_chain],
                "tags": exp.tags,
            })
        return failure_lessons

    def extract_patterns(self):
        """Analyze experiences and extract reusable patterns."""
        self.patterns = []
        successful_chains = self.get_successful_chains(min_count=1)
        for sc in successful_chains:
            tools = [t.get("tool", "") for t in sc["chain"]]
            self.patterns.append({
                "type": "successful_chain",
                "tools": tools,
                "count": sc["count"],
                "example_intent": sc["intent"],
                "metrics": sc.get("metrics", {}),
                "lesson": sc.get("lesson", ""),
            })
        failures = self.get_failure_patterns()
        for f in failures:
            self.patterns.append({
                "type": "failure_pattern",
                "tools": f["tool_chain"],
                "error": f["error"],
                "lesson": f["lesson"],
                "tags": f["tags"],
            })
        self._save_patterns()
        return self.patterns

    def get_summary(self) -> Dict:
        total = len(self.experiences)
        success_count = sum(1 for e in self.experiences if e.success)
        tool_counts = Counter()
        for exp in self.experiences:
            for t in exp.tool_chain:
                tool_counts[t.get("tool", "unknown")] += 1
        tag_counts = Counter()
        for exp in self.experiences:
            for tag in exp.tags:
                tag_counts[tag] += 1
        return {
            "total_experiences": total,
            "success_rate": success_count / total if total > 0 else 0,
            "most_used_tools": dict(tool_counts.most_common(10)),
            "tags": dict(tag_counts.most_common(10)),
            "patterns_extracted": len(self.patterns),
        }
