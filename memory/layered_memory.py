"""
Layered Memory System for BrachyBot
====================================
Inspired by GenericAgent's hierarchical memory architecture.
Maximizes contextual information density by keeping only decision-relevant
tokens in the active context, while richer knowledge is retrieved on-demand.

L0 - Meta Rules: Core behavioral rules and system constraints (always in prompt)
L1 - Insight Index: Minimal memory index for fast routing and recall
L2 - Global Facts: Stable knowledge accumulated over long-term operation
L3 - Task Skills / SOPs: Reusable workflows for specific task types
L4 - Session Archive: Archived task records distilled from finished sessions
"""

import json
import os
import hashlib
import time
from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime


@dataclass
class MetaRule:
    """L0: Core behavioral rules that are always active."""
    id: str
    rule: str
    priority: int = 1
    category: str = "general"
    source: str = "system"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    violations: int = 0


@dataclass
class InsightEntry:
    """L1: Minimal index for fast routing and recall."""
    id: str
    keywords: list = field(default_factory=list)
    summary: str = ""
    target_layer: str = ""
    target_id: str = ""
    relevance_score: float = 1.0
    last_accessed: str = ""
    access_count: int = 0


@dataclass
class GlobalFact:
    """L2: Stable knowledge accumulated over long-term operation."""
    id: str
    fact: str
    category: str = "general"
    confidence: float = 1.0
    source: str = "experience"
    evidence_count: int = 1
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    verified: bool = False


@dataclass
class SOPStep:
    """A single step in a Standard Operating Procedure."""
    step_id: int
    tool_name: str
    description: str
    input_mapping: dict = field(default_factory=dict)
    output_key: str = ""
    fallback: str = ""
    critical: bool = True


@dataclass
class SOP:
    """L3: Reusable workflow for a specific task type."""
    id: str
    name: str
    trigger_keywords: list = field(default_factory=list)
    steps: list = field(default_factory=list)
    success_rate: float = 1.0
    usage_count: int = 0
    avg_tokens: int = 0
    avg_time: float = 0.0
    created_from: str = "experience"
    source_trajectory: str = ""
    last_used: str = ""
    version: int = 1
    notes: str = ""


@dataclass
class SessionArchive:
    """L4: Distilled record from a finished session."""
    id: str
    session_id: str
    user_intent: str
    outcome: str
    success: bool
    tool_chain: list = field(default_factory=list)
    key_decisions: list = field(default_factory=list)
    lessons_learned: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    tags: list = field(default_factory=list)


class LayeredMemory:
    """
    Hierarchical memory system that maximizes contextual information density.
    
    Only L0 (meta rules) and a compact L1 (insight index) are always in context.
    L2, L3, L4 are retrieved on-demand based on the current task.
    """

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory", "data")
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

        self.l0_rules: dict[str, MetaRule] = {}
        self.l1_index: dict[str, InsightEntry] = {}
        self.l2_facts: dict[str, GlobalFact] = {}
        self.l3_sops: dict[str, SOP] = {}
        self.l4_archives: dict[str, SessionArchive] = {}

        self._load_all()
        if not self.l0_rules:
            self._init_default_rules()

    def _load_all(self):
        for layer_name, storage in [
            ("l0_rules", self.l0_rules),
            ("l1_index", self.l1_index),
            ("l2_facts", self.l2_facts),
            ("l3_sops", self.l3_sops),
            ("l4_archives", self.l4_archives),
        ]:
            path = os.path.join(self.base_dir, f"{layer_name}.json")
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        data = json.load(f)
                    for item_id, item_data in data.items():
                        cls_map = {
                            "l0_rules": MetaRule,
                            "l1_index": InsightEntry,
                            "l2_facts": GlobalFact,
                            "l3_sops": SOP,
                            "l4_archives": SessionArchive,
                        }
                        cls = cls_map[layer_name]
                        storage[item_id] = cls(**item_data)
                except (json.JSONDecodeError, TypeError):
                    pass

    def _save_layer(self, layer_name: str, storage: dict):
        path = os.path.join(self.base_dir, f"{layer_name}.json")
        serializable = {}
        for k, v in storage.items():
            if hasattr(v, "__dict__"):
                serializable[k] = {key: val for key, val in v.__dict__.items() if not key.startswith("_")}
            else:
                serializable[k] = v
        with open(path, "w") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False)

    def save_all(self):
        self._save_layer("l0_rules", self.l0_rules)
        self._save_layer("l1_index", self.l1_index)
        self._save_layer("l2_facts", self.l2_facts)
        self._save_layer("l3_sops", self.l3_sops)
        self._save_layer("l4_archives", self.l4_archives)

    def _init_default_rules(self):
        default_rules = [
            MetaRule(id="r001", rule="Always validate tool inputs before execution", priority=1, category="safety"),
            MetaRule(id="r002", rule="Never execute destructive operations without user confirmation", priority=1, category="safety"),
            MetaRule(id="r003", rule="Record every interaction as experience for self-evolution", priority=2, category="memory"),
            MetaRule(id="r004", rule="When uncertain, prefer conservative clinical decisions", priority=1, category="clinical"),
            MetaRule(id="r005", rule="Check past successful tool chains before planning new ones", priority=2, category="planning"),
            MetaRule(id="r006", rule="After 3 consecutive failures on same tool, suggest alternative approach", priority=2, category="error_handling"),
            MetaRule(id="r007", rule="Always include dose evaluation after seed placement", priority=1, category="clinical"),
            MetaRule(id="r008", rule="Preserve patient data privacy; never expose raw DICOM data in logs", priority=1, category="privacy"),
        ]
        for rule in default_rules:
            self.l0_rules[rule.id] = rule
        self._save_layer("l0_rules", self.l0_rules)

    # === L0: Meta Rules ===

    def get_active_rules(self, category: str = None) -> list[str]:
        rules = list(self.l0_rules.values())
        if category:
            rules = [r for r in rules if r.category == category]
        rules.sort(key=lambda r: r.priority)
        return [r.rule for r in rules]

    def add_rule(self, rule: str, category: str = "general", priority: int = 2, source: str = "evolution") -> str:
        rule_id = f"r{hashlib.md5(rule.encode()).hexdigest()[:6]}"
        self.l0_rules[rule_id] = MetaRule(id=rule_id, rule=rule, priority=priority, category=category, source=source)
        self._save_layer("l0_rules", self.l0_rules)
        self._update_index(keywords=[category, rule[:30]], target_layer="l0_rules", target_id=rule_id, summary=rule)
        return rule_id

    def remove_rule(self, rule_id: str) -> bool:
        if rule_id in self.l0_rules:
            del self.l0_rules[rule_id]
            self._save_layer("l0_rules", self.l0_rules)
            return True
        return False

    def record_violation(self, rule_id: str):
        if rule_id in self.l0_rules:
            self.l0_rules[rule_id].violations += 1
            self._save_layer("l0_rules", self.l0_rules)

    # === L1: Insight Index ===

    def _update_index(self, keywords: list, target_layer: str, target_id: str, summary: str = ""):
        idx_key = f"{target_layer}:{target_id}"
        if idx_key in self.l1_index:
            entry = self.l1_index[idx_key]
            entry.keywords = list(set(entry.keywords + keywords))
            entry.last_accessed = datetime.now().isoformat()
        else:
            self.l1_index[idx_key] = InsightEntry(
                id=idx_key, keywords=keywords, summary=summary,
                target_layer=target_layer, target_id=target_id,
            )
        self._save_layer("l1_index", self.l1_index)

    def search_index(self, query_keywords: list, top_k: int = 5) -> list[InsightEntry]:
        query_set = set(query_keywords)
        scored = []
        for entry in self.l1_index.values():
            overlap = len(query_set & set(entry.keywords))
            if overlap > 0:
                entry.relevance_score = overlap / len(query_set)
                entry.access_count += 1
                entry.last_accessed = datetime.now().isoformat()
                scored.append(entry)
        scored.sort(key=lambda e: e.relevance_score, reverse=True)
        self._save_layer("l1_index", self.l1_index)
        return scored[:top_k]

    # === L2: Global Facts ===

    def add_fact(self, fact: str, category: str = "general", source: str = "experience", confidence: float = 0.8) -> str:
        fact_id = f"f{hashlib.md5(fact.encode()).hexdigest()[:6]}"
        self.l2_facts[fact_id] = GlobalFact(
            id=fact_id, fact=fact, category=category, source=source, confidence=confidence,
        )
        self._save_layer("l2_facts", self.l2_facts)
        self._update_index(keywords=[category, fact[:30]], target_layer="l2_facts", target_id=fact_id, summary=fact)
        return fact_id

    def get_facts(self, category: str = None, min_confidence: float = 0.5) -> list[GlobalFact]:
        facts = list(self.l2_facts.values())
        if category:
            facts = [f for f in facts if f.category == category]
        facts = [f for f in facts if f.confidence >= min_confidence]
        facts.sort(key=lambda f: f.confidence, reverse=True)
        return facts

    def update_fact_confidence(self, fact_id: str, delta: float):
        if fact_id in self.l2_facts:
            fact = self.l2_facts[fact_id]
            fact.confidence = max(0.0, min(1.0, fact.confidence + delta))
            fact.evidence_count += 1
            if fact.confidence >= 0.9:
                fact.verified = True
            self._save_layer("l2_facts", self.l2_facts)

    def extract_facts_from_experience(self, tool_chain: list, success: bool, metrics: dict):
        if success and len(tool_chain) >= 2:
            chain_str = " -> ".join(tool_chain)
            fact = f"Tool chain '{chain_str}' is effective for this task type"
            self.add_fact(fact, category="tool_chain", confidence=0.7)

            for tool_name in tool_chain:
                fact = f"Tool '{tool_name}' produces reliable results"
                self.add_fact(fact, category="tool_reliability", confidence=0.6)

        if not success and tool_chain:
            failed_tool = tool_chain[-1]
            fact = f"Tool '{failed_tool}' may fail under certain conditions"
            self.add_fact(fact, category="tool_risk", confidence=0.5)

    # === L3: SOPs (Standard Operating Procedures) ===

    def create_sop_from_trajectory(self, name: str, trigger_keywords: list, tool_chain: list, source_trajectory: str = "") -> str:
        sop_id = f"sop{hashlib.md5(name.encode()).hexdigest()[:6]}"
        steps = []
        for i, tool_name in enumerate(tool_chain):
            steps.append(SOPStep(
                step_id=i, tool_name=tool_name,
                description=f"Execute {tool_name}",
                input_mapping={"auto": True},
                output_key=f"result_{i}",
            ))
        self.l3_sops[sop_id] = SOP(
            id=sop_id, name=name, trigger_keywords=trigger_keywords,
            steps=steps, source_trajectory=source_trajectory,
        )
        self._save_layer("l3_sops", self.l3_sops)
        self._update_index(
            keywords=trigger_keywords + [name],
            target_layer="l3_sops", target_id=sop_id,
            summary=f"SOP: {name} with {len(steps)} steps",
        )
        return sop_id

    def find_sop(self, query: str) -> Optional[SOP]:
        query_lower = query.lower()
        best_sop = None
        best_score = 0
        for sop in self.l3_sops.values():
            score = sum(1 for kw in sop.trigger_keywords if kw.lower() in query_lower)
            if score > best_score:
                best_score = score
                best_sop = sop
        if best_sop and best_score > 0:
            best_sop.usage_count += 1
            best_sop.last_used = datetime.now().isoformat()
            self._save_layer("l3_sops", self.l3_sops)
        return best_sop

    def update_sop_metrics(self, sop_id: str, success: bool, tokens: int = 0, exec_time: float = 0.0):
        if sop_id in self.l3_sops:
            sop = self.l3_sops[sop_id]
            n = sop.usage_count
            sop.success_rate = (sop.success_rate * n + (1 if success else 0)) / (n + 1)
            if tokens > 0:
                sop.avg_tokens = (sop.avg_tokens * n + tokens) / (n + 1)
            if exec_time > 0:
                sop.avg_time = (sop.avg_time * n + exec_time) / (n + 1)
            self._save_layer("l3_sops", self.l3_sops)

    def get_sops_by_success_rate(self, min_rate: float = 0.7, min_usage: int = 1) -> list[SOP]:
        sops = [s for s in self.l3_sops.values() if s.success_rate >= min_rate and s.usage_count >= min_usage]
        sops.sort(key=lambda s: s.success_rate, reverse=True)
        return sops

    # === L4: Session Archive ===

    def archive_session(self, session_id: str, user_intent: str, outcome: str,
                       success: bool, tool_chain: list, lessons: list = None,
                       metrics: dict = None, tags: list = None):
        archive_id = f"arch{hashlib.md5(f'{session_id}{time.time()}'.encode()).hexdigest()[:6]}"
        self.l4_archives[archive_id] = SessionArchive(
            id=archive_id, session_id=session_id, user_intent=user_intent,
            outcome=outcome, success=success, tool_chain=tool_chain,
            lessons_learned=lessons or [], metrics=metrics or {},
            tags=tags or [],
        )
        self._save_layer("l4_archives", self.l4_archives)
        self._update_index(
            keywords=tags + [user_intent[:20]],
            target_layer="l4_archives", target_id=archive_id,
            summary=f"{user_intent} -> {'success' if success else 'failed'}",
        )

    def search_archives(self, query: str, top_k: int = 3) -> list[SessionArchive]:
        query_lower = query.lower()
        scored = []
        for archive in self.l4_archives.values():
            score = 0
            if query_lower in archive.user_intent.lower():
                score += 3
            if query_lower in archive.outcome.lower():
                score += 2
            for tag in archive.tags:
                if query_lower in tag.lower():
                    score += 1
            for lesson in archive.lessons_learned:
                if query_lower in lesson.lower():
                    score += 2
            if score > 0:
                scored.append((score, archive))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [a for _, a in scored[:top_k]]

    def get_similar_successful_sessions(self, tool_chain: list, top_k: int = 3) -> list[SessionArchive]:
        scored = []
        for archive in self.l4_archives.values():
            if not archive.success:
                continue
            common = len(set(tool_chain) & set(archive.tool_chain))
            if common > 0:
                scored.append((common, archive))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [a for _, a in scored[:top_k]]

    # === Cross-layer operations ===

    def get_context_summary(self, query: str, max_rules: int = 5, max_facts: int = 3, max_sops: int = 2) -> dict:
        keywords = query.lower().split()
        relevant_facts = self.get_facts(min_confidence=0.6)[:max_facts]
        relevant_sops = self.get_sops_by_success_rate(min_rate=0.7)[:max_sops]
        matched_sop = self.find_sop(query)

        return {
            "l0_rules": self.get_active_rules()[:max_rules],
            "l2_facts": [(f.fact, f.confidence) for f in relevant_facts],
            "l3_sops": [(s.name, s.success_rate, [step.tool_name for step in s.steps]) for s in relevant_sops],
            "matched_sop": (matched_sop.name, [step.tool_name for step in matched_sop.steps]) if matched_sop else None,
        }

    def get_stats(self) -> dict:
        return {
            "l0_rules": len(self.l0_rules),
            "l1_index": len(self.l1_index),
            "l2_facts": len(self.l2_facts),
            "l3_sops": len(self.l3_sops),
            "l4_archives": len(self.l4_archives),
            "verified_facts": sum(1 for f in self.l2_facts.values() if f.verified),
            "high_rate_sops": sum(1 for s in self.l3_sops.values() if s.success_rate >= 0.8),
        }
