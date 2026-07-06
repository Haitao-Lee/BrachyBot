"""
Self-Evolution Engine
=====================
The agent's meta-cognition system: analyzes experiences,
extracts lessons, updates skills, and improves itself.
"""

import os
import json
import logging
from typing import Dict, List, Optional, Any
from collections import Counter

logger = logging.getLogger(__name__)


class SelfEvolutionEngine:
    """
    Analyzes agent experiences and drives self-improvement.
    Produces: updated skills, new lessons, parameter optimizations,
    and code improvement suggestions.
    """

    def __init__(self, experience_memory, skill_registry=None, preference_store=None):
        self.exp_memory = experience_memory
        self.skill_registry = skill_registry
        self.preference_store = preference_store
        self.evolution_log: List[Dict] = []
        self._log_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data", "evolution_log.json"
        )
        self._load_log()

    def _load_log(self):
        if os.path.exists(self._log_file):
            try:
                with open(self._log_file, "r") as f:
                    self.evolution_log = json.load(f)
            except Exception:
                self.evolution_log = []

    def _save_log(self):
        os.makedirs(os.path.dirname(self._log_file), exist_ok=True)
        with open(self._log_file, "w") as f:
            json.dump(self.evolution_log, f, indent=2, default=str)

    def clear(self):
        """Clear evolution log."""
        self.evolution_log.clear()
        logger.info("SelfEvolutionEngine: Cleared evolution log")

    def evolve(self) -> Dict:
        """Run full evolution cycle."""
        results = {
            "new_skills": [],
            "updated_skills": [],
            "lessons": [],
            "parameter_updates": [],
            "failure_insights": [],
            "code_suggestions": [],
        }
        self.exp_memory.extract_patterns()
        results["lessons"] = self._extract_lessons()
        results["new_skills"] = self._create_skills_from_patterns()
        results["updated_skills"] = self._update_existing_skills()
        results["parameter_updates"] = self._optimize_parameters()
        results["failure_insights"] = self._analyze_failures()
        results["code_suggestions"] = self._suggest_code_improvements()
        self.evolution_log.append({
            "timestamp": __import__("time").time(),
            "results": results,
        })
        self._save_log()
        logger.info(f"Evolution complete: {len(results['new_skills'])} new skills, "
                     f"{len(results['lessons'])} lessons")
        return results

    def _extract_lessons(self) -> List[Dict]:
        """Extract actionable lessons from experiences."""
        lessons = []
        for exp in self.exp_memory.experiences:
            if not exp.lesson:
                continue
            lessons.append({
                "context": exp.user_intent,
                "lesson": exp.lesson,
                "tags": exp.tags,
                "success": exp.success,
            })
        return lessons

    def _create_skills_from_patterns(self) -> List[Dict]:
        """Create new skills from successful tool chains."""
        new_skills = []
        chains = self.exp_memory.get_successful_chains(min_count=2)
        for chain_info in chains:
            tools = [t.get("tool", "") for t in chain_info["chain"]]
            if len(tools) < 2:
                continue
            skill_name = f"auto_{tools[0]}_{'_'.join(tools[1:3])}"
            trigger = chain_info["intent"]
            new_skill = {
                "name": skill_name,
                "description": f"Auto-learned: {chain_info['intent']}",
                "category": "learned",
                "triggers": [trigger],
                "tool_sequence": tools,
                "parameters": {},
                "success_rate": 1.0,
                "usage_count": chain_info["count"],
            }
            if self.skill_registry:
                existing = self.skill_registry.get(skill_name)
                if existing is None:
                    try:
                        from skills.skill_base import Skill
                    except ImportError as exc:
                        logger.warning("Skill registry is configured but skills.skill_base is unavailable: %s", exc)
                    else:
                        skill = Skill(
                            name=skill_name,
                            description=new_skill["description"],
                            category="learned",
                            triggers=[trigger],
                            tool_sequence=tools,
                            parameters={},
                        )
                        self.skill_registry.register(skill)
            new_skills.append(new_skill)
        return new_skills

    def _update_existing_skills(self) -> List[Dict]:
        """Update success rates of existing skills based on recent experiences."""
        updated = []
        if not self.skill_registry:
            return updated
        # REVIEW: previously iterated `self.skill_registry.list_skills()`, which
        # returns throwaway summary dicts; mutating them updated nothing and the
        # underlying SkillRegistry.skills dict was never persisted. Iterate the
        # live Skill instances and call `_save_skill` to persist changes.
        skills_dict = getattr(self.skill_registry, "skills", None)
        if not isinstance(skills_dict, dict):
            return updated
        for skill in skills_dict.values():
            if skill.category != "learned":
                continue
            name = skill.name
            matching = [
                e for e in self.exp_memory.experiences
                if name in str(e.tool_chain)
            ]
            if matching:
                success_rate = sum(1 for m in matching if m.success) / len(matching)
                # Reset cumulative counters and resync usage_count with the
                # matching experience list directly (the underlying Skill
                # dataclass tracks usage_count and success_count separately).
                skill.usage_count = len(matching)
                skill.success_count = sum(1 for m in matching if m.success)
                save_skill = getattr(self.skill_registry, "_save_skill", None)
                if callable(save_skill):
                    save_skill(skill)
                updated.append({
                    "name": name,
                    "success_rate": success_rate,
                    "usage_count": len(matching),
                })
        return updated

    def _optimize_parameters(self) -> List[Dict]:
        """Find optimal parameters from successful experiences."""
        param_stats = {}
        for exp in self.exp_memory.experiences:
            if not exp.success:
                continue
            for tool in exp.tool_chain:
                tool_name = tool.get("tool", "")
                params = tool.get("params", {})
                if tool_name not in param_stats:
                    param_stats[tool_name] = {}
                for k, v in params.items():
                    if k not in param_stats[tool_name]:
                        param_stats[tool_name][k] = []
                    if isinstance(v, (int, float)):
                        param_stats[tool_name][k].append(v)
        updates = []
        for tool_name, params in param_stats.items():
            for param, values in params.items():
                if len(values) >= 2:
                    avg = sum(values) / len(values)
                    updates.append({
                        "tool": tool_name,
                        "parameter": param,
                        "recommended_value": round(avg, 4),
                        "sample_size": len(values),
                    })
        if self.preference_store:
            for update in updates:
                self.preference_store.set(
                    category="optimized_params",
                    key=f"{update['tool']}_{update['parameter']}",
                    value=update["recommended_value"],
                    confidence=min(0.9, update["sample_size"] * 0.1),
                    source="self_evolution",
                )
        return updates

    def _analyze_failures(self) -> List[Dict]:
        """Analyze failures and produce insights."""
        insights = []
        failures = self.exp_memory.get_failure_patterns(min_count=1)
        for f in failures:
            insight = {
                "error": f["error"],
                "lesson": f["lesson"],
                "tools_involved": f.get("tools", f.get("tool_chain", [])),
                "tags": f["tags"],
                "avoidance_strategy": f.get("lesson", ""),
            }
            insights.append(insight)
        return insights

    def _suggest_code_improvements(self) -> List[Dict]:
        """Suggest code improvements based on experience patterns."""
        suggestions = []
        tool_errors = Counter()
        for exp in self.exp_memory.experiences:
            if not exp.success:
                for t in exp.tool_chain:
                    tool_errors[t.get("tool", "unknown")] += 1
        for tool, error_count in tool_errors.most_common(5):
            if error_count >= 2:
                suggestions.append({
                    "type": "tool_improvement",
                    "tool": tool,
                    "issue": f"Failed {error_count} times",
                    "suggestion": f"Review and fix {tool} — recurring failures detected",
                })
        return suggestions

    def get_evolution_summary(self) -> Dict:
        """Get a summary of all evolution activity."""
        return {
            "experience_summary": self.exp_memory.get_summary(),
            "evolution_cycles": len(self.evolution_log),
            "total_lessons": sum(
                len(e.get("results", {}).get("lessons", []))
                for e in self.evolution_log
            ),
            "total_new_skills": sum(
                len(e.get("results", {}).get("new_skills", []))
                for e in self.evolution_log
            ),
        }
