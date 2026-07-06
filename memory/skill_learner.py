"""
Skill Learner
=============
Analyzes interaction patterns to learn and generate new skills
that match user habits/preferences.
"""

import os
import json
import time
import hashlib
from typing import Dict, List, Optional, Any, Tuple
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict

from .interaction_memory import InteractionMemory, ToolCall


@dataclass
class LearnedSkill:
    """A skill learned from user interactions."""
    name: str
    description: str
    trigger_patterns: List[str]  # Keywords or patterns that trigger this skill
    tool_sequence: List[str]      # Sequence of tools to call
    parameters: Dict[str, Any]    # Default/frequently used parameters
    success_rate: float          # Historical success rate
    usage_count: int              # Number of times used
    learned_from: int             # Number of interactions analyzed
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["created_at"] = self.created_at
        d["last_used"] = self.last_used
        return d

    @classmethod
    def from_dict(cls, d: Dict) -> "LearnedSkill":
        return cls(
            name=d["name"],
            description=d["description"],
            trigger_patterns=d.get("trigger_patterns", []),
            tool_sequence=d.get("tool_sequence", []),
            parameters=d.get("parameters", {}),
            success_rate=d.get("success_rate", 0.0),
            usage_count=d.get("usage_count", 0),
            learned_from=d.get("learned_from", 0),
            created_at=d.get("created_at", time.time()),
            last_used=d.get("last_used", time.time()),
        )

    def use(self):
        """Record a use of this skill."""
        self.usage_count += 1
        self.last_used = time.time()


class SkillLearner:
    """
    Learns new skills from interaction patterns.

    Evolution pipeline:
    1. Analyze interaction history for patterns
    2. Identify successful tool sequences
    3. Extract frequently used parameter combinations
    4. Generate new skills with trigger patterns
    5. Test and refine skills based on success rate
    """

    def __init__(self, memory: InteractionMemory, storage_dir: str = None):
        self.memory = memory
        self.storage_dir = storage_dir or os.path.join(
            os.path.dirname(__file__), "data", "learned_skills"
        )
        os.makedirs(self.storage_dir, exist_ok=True)

        self.skills: Dict[str, LearnedSkill] = {}
        self._load_skills()

    def learn_from_interactions(self, min_occurrences: int = 3) -> List[LearnedSkill]:
        """
        Analyze interaction history and learn new skills.

        Returns list of newly learned skills.
        """
        new_skills = []

        patterns = self.memory.extract_tool_patterns(min_occurrences=min_occurrences)

        for pattern in patterns:
            skill_name = self._pattern_to_skill_name(pattern)

            if skill_name in self.skills:
                skill = self.skills[skill_name]
                skill.learned_from += 1
                skill.success_rate = self.memory.get_success_rate(tool_name=pattern[0])
            else:
                skill = self._create_skill_from_pattern(pattern)
                self.skills[skill_name] = skill
                new_skills.append(skill)
                self._save_skill(skill)

        return new_skills

    def learn_parameter_preferences(self) -> Dict[str, Any]:
        """
        Extract frequently used parameter combinations.

        E.g., if user always uses mode='rl', extract this as preference.
        """
        param_counter = defaultdict(int)

        for tc in self.memory.tool_call_history:
            if tc.success:
                for key, value in tc.inputs.items():
                    if isinstance(value, (str, int, float, bool)):
                        param_key = f"{tc.tool_name}.{key}"
                        param_counter[f"{param_key}={value}"] += 1

        preferences = {}
        for param_str, count in param_counter.items():
            if count >= 3:
                # REVIEW: previously `param_str.rsplit(".", 1)` returned
                # `["seed_planning", "mode=rl"]` so param_name carried the
                # `"=rl"` suffix. The downstream `preference_store` looks up
                # the preference by `f"{tool_name}_{param_name}"` (just the
                # key, no value), so the suffix caused every learned
                # preference to be silently stored but never applied. Split
                # out the param_name and value separately.
                if "=" not in param_str:
                    continue
                key_part, value = param_str.split("=", 1)
                tool_param = key_part.rsplit(".", 1)
                if len(tool_param) != 2:
                    continue
                tool_name, param_name = tool_param
                try:
                    value = int(value) if value.isdigit() else float(value) if "." in value else value
                except ValueError:
                    pass

                if tool_name not in preferences:
                    preferences[tool_name] = {}
                preferences[tool_name][param_name] = {
                    "value": value,
                    "confidence": min(count / 10, 1.0),
                }

        return preferences

    def learn_trigger_patterns(self, content: str) -> List[str]:
        """
        Extract trigger patterns from conversation content.

        Identifies keywords and phrases that precede successful actions.
        """
        patterns = []

        content_lower = content.lower()

        keyword_map = {
            "segment": ["ctv_segmentation", "oar_segmentation", "segment"],
            "tumor": ["ctv_segmentation"],
            "organ": ["oar_segmentation"],
            "plan": ["seed_planning", "trajectory_planning"],
            "seed": ["seed_planning"],
            "trajectory": ["trajectory_planning"],
            "dose": ["dose_evaluation", "dose_engine"],
            "eval": ["dose_evaluation"],
            "optimize": ["plan_refinement"],
            "OAR": ["oar_segmentation", "oar_constraint_checker"],
            "D90": ["dose_evaluation"],
            "V100": ["dose_evaluation"],
        }

        for keyword, tools in keyword_map.items():
            if keyword in content_lower:
                patterns.append(keyword)
                for tool in tools:
                    if tool not in patterns:
                        patterns.append(tool)

        return patterns

    def suggest_next_tool(self) -> Optional[str]:
        """
        Suggest the next tool based on learned patterns.

        Uses the most recent tool call sequence to predict next tool.
        """
        recent_seq = self.memory.get_tool_sequence(n=3)
        if not recent_seq:
            return None

        for skill in sorted(self.skills.values(),
                          key=lambda s: s.success_rate * s.usage_count,
                          reverse=True):
            if len(skill.tool_sequence) > len(recent_seq):
                if skill.tool_sequence[:len(recent_seq)] == recent_seq:
                    return skill.tool_sequence[len(recent_seq)]

        return None

    def get_skill(self, name: str) -> Optional[LearnedSkill]:
        """Get a learned skill by name."""
        return self.skills.get(name)

    def get_skills_by_trigger(self, trigger: str) -> List[LearnedSkill]:
        """Get all skills matching a trigger pattern."""
        trigger_lower = trigger.lower()
        return [
            s for s in self.skills.values()
            if any(trigger_lower in p.lower() for p in s.trigger_patterns)
        ]

    def get_best_skill(self, trigger: str) -> Optional[LearnedSkill]:
        """Get the highest-rated skill matching a trigger."""
        matches = self.get_skills_by_trigger(trigger)
        if not matches:
            return None
        return max(matches, key=lambda s: s.success_rate * s.usage_count)

    def record_skill_use(self, skill_name: str, success: bool):
        """Record the result of using a learned skill."""
        if skill_name in self.skills:
            skill = self.skills[skill_name]
            skill.use()
            if not success:
                skill.success_rate = max(0.0, skill.success_rate - 0.1)
            else:
                skill.success_rate = min(1.0, skill.success_rate + 0.05)
            self._save_skill(skill)

    def evolve_skills(self) -> Dict[str, List[LearnedSkill]]:
        """
        Run the full evolution pipeline.

        Returns dict with 'new', 'updated', 'removed' skill lists.
        """
        result = {
            "new": [],
            "updated": [],
        }

        new_skills = self.learn_from_interactions(min_occurrences=3)
        result["new"] = new_skills

        for skill in self.skills.values():
            if skill.usage_count > 0:
                result["updated"].append(skill)

        return result

    def _pattern_to_skill_name(self, pattern: List[str]) -> str:
        """Convert a tool pattern to a skill name."""
        name = "_".join(pattern)
        name_hash = hashlib.md5(name.encode()).hexdigest()[:6]
        return f"learned_{name_hash}"

    def _create_skill_from_pattern(self, pattern: List[str]) -> LearnedSkill:
        """Create a new learned skill from a tool pattern."""
        tool_usage = self.memory.get_tool_usage_stats()

        skill_name = self._pattern_to_skill_name(pattern)
        description = f"Auto-learned sequence: {' -> '.join(pattern)}"

        trigger_map = {
            "ctv_segmentation": ["tumor", "segment", "target"],
            "oar_segmentation": ["organ", "OAR", "segment"],
            "trajectory_planning": ["trajectory", "needle"],
            "seed_planning": ["seed", "plan", "planning"],
            "dose_engine": ["dose", "dosimetry"],
            "dose_evaluation": ["eval", "evaluation", "D90", "V100"],
        }

        trigger_patterns = []
        for tool in pattern:
            if tool in trigger_map:
                trigger_patterns.extend(trigger_map[tool])

        success_rate = 0.0
        if pattern[0] in tool_usage:
            success_rate = self.memory.get_success_rate(tool_name=pattern[0])

        return LearnedSkill(
            name=skill_name,
            description=description,
            trigger_patterns=list(set(trigger_patterns)),
            tool_sequence=pattern,
            parameters={},
            success_rate=success_rate,
            usage_count=0,
            learned_from=1,
        )

    def _load_skills(self):
        """Load learned skills from disk."""
        skills_file = os.path.join(self.storage_dir, "skills.json")
        if os.path.exists(skills_file):
            try:
                with open(skills_file, "r") as f:
                    data = json.load(f)
                self.skills = {k: LearnedSkill.from_dict(v) for k, v in data.items()}
            except (json.JSONDecodeError, KeyError):
                self.skills = {}

    def _save_skill(self, skill: LearnedSkill):
        """Save a skill to disk."""
        skills_file = os.path.join(self.storage_dir, "skills.json")
        skills_data = {k: v.to_dict() for k, v in self.skills.items()}
        with open(skills_file, "w", encoding="utf-8") as f:
            json.dump(skills_data, f, indent=2, default=str)

    def export_skills(self, path: str = None) -> str:
        """Export all learned skills to JSON."""
        if path is None:
            path = os.path.join(self.storage_dir, f"skills_export_{int(time.time())}.json")

        skills_data = {k: v.to_dict() for k, v in self.skills.items()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "export_time": time.time(),
                "skills": skills_data,
            }, f, indent=2, default=str)

        return path
