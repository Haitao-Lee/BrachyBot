"""
Skill Base and Registry
=======================
Base class for all skills and the skill registry for management.
"""

import os
import json
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from abc import ABC, abstractmethod


@dataclass
class Skill:
    """Base skill definition."""
    name: str
    description: str
    category: str
    triggers: List[str]          # Keywords that activate this skill
    tool_sequence: List[str]    # Ordered list of tools to call
    parameters: Dict[str, Any]  # Default parameters for each tool
    success_threshold: float = 0.8
    usage_count: int = 0
    success_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    version: str = "1.0.0"

    def success_rate(self) -> float:
        if self.usage_count == 0:
            return 0.0
        return self.success_count / self.usage_count

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "Skill":
        return cls(**d)

    def use(self, success: bool):
        """Record a use of this skill."""
        self.usage_count += 1
        if success:
            self.success_count += 1
        self.last_used = time.time()

    def update_parameters(self, new_params: Dict[str, Any]):
        """Update skill parameters based on usage."""
        for tool, params in new_params.items():
            if tool in self.parameters:
                self.parameters[tool].update(params)
            else:
                self.parameters[tool] = params


class SkillRegistry:
    """
    Registry for managing all available skills.

    Skills can be:
    - Registered from code
    - Loaded from JSON files
    - Created dynamically by SkillLearner
    """

    def __init__(self, storage_dir: str = None):
        self.storage_dir = storage_dir or os.path.join(
            os.path.dirname(__file__), "data", "skills"
        )
        os.makedirs(self.storage_dir, exist_ok=True)

        self.skills: Dict[str, Skill] = {}
        self._load_skills()

    def register(self, skill: Skill):
        """Register a skill."""
        self.skills[skill.name] = skill
        self._save_skill(skill)

    def get(self, name: str) -> Optional[Skill]:
        """Get a skill by name."""
        return self.skills.get(name)

    def find_by_trigger(self, text: str) -> List[Skill]:
        """Find skills matching a trigger text."""
        text_lower = text.lower()
        matches = []
        for skill in self.skills.values():
            if any(t.lower() in text_lower for t in skill.triggers):
                matches.append(skill)
        return sorted(matches, key=lambda s: s.success_rate() * s.usage_count, reverse=True)

    def find_by_category(self, category: str) -> List[Skill]:
        """Find all skills in a category."""
        return [s for s in self.skills.values() if s.category == category]

    def list_skills(self) -> List[Dict]:
        """List all skills with metadata."""
        return [
            {
                "name": s.name,
                "description": s.description,
                "category": s.category,
                "success_rate": s.success_rate(),
                "usage_count": s.usage_count,
                "last_used": s.last_used,
            }
            for s in sorted(self.skills.values(), key=lambda x: x.success_rate(), reverse=True)
        ]

    def record_use(self, skill_name: str, success: bool):
        """Record the result of using a skill."""
        if skill_name in self.skills:
            self.skills[skill_name].use(success)
            self._save_skill(self.skills[skill_name])

    def evolve_from_interactions(self, interaction_memory, skill_learner) -> List[Skill]:
        """
        Create new skills or refine existing ones based on interaction history.

        Returns list of newly created/updated skills.
        """
        new_or_updated = []

        patterns = interaction_memory.extract_tool_patterns(min_occurrences=3)

        for pattern in patterns:
            skill_name = f"learned_{'_'.join(pattern)}"

            if skill_name in self.skills:
                skill = self.skills[skill_name]
            else:
                skill = self._create_skill_from_pattern(pattern)
                self.skills[skill_name] = skill
                new_or_updated.append(skill)

            success_rate = interaction_memory.get_success_rate(tool_name=pattern[0])
            skill.success_threshold = success_rate
            new_or_updated.append(skill)
            self._save_skill(skill)

        return new_or_updated

    def _create_skill_from_pattern(self, pattern: List[str]) -> Skill:
        """Create a new skill from a tool pattern."""
        category_map = {
            "segmentation": ["ctv_segmentation", "oar_segmentation"],
            "planning": ["seed_planning", "trajectory_planning"],
            "evaluation": ["dose_evaluation", "plan_quality_scorer"],
        }

        category = "general"
        for cat, tools in category_map.items():
            if any(t in tools for t in pattern):
                category = cat
                break

        trigger_map = {
            "ctv_segmentation": ["分割", "肿瘤", "target", "segment"],
            "oar_segmentation": ["器官", "OAR", "organ"],
            "seed_planning": ["种子", "seed", "规划", "plan"],
            "trajectory_planning": ["轨迹", "trajectory"],
            "dose_evaluation": ["评估", "剂量", "eval", "dose"],
        }

        triggers = []
        for tool in pattern:
            if tool in trigger_map:
                triggers.extend(trigger_map[tool])

        description = f"Auto-generated: {' -> '.join(pattern)}"

        return Skill(
            name=f"learned_{'_'.join(pattern)}",
            description=description,
            category=category,
            triggers=list(set(triggers)),
            tool_sequence=pattern,
            parameters={},
        )

    def _load_skills(self):
        """Load skills from disk."""
        skills_file = os.path.join(self.storage_dir, "skills_registry.json")
        if os.path.exists(skills_file):
            try:
                with open(skills_file, "r") as f:
                    data = json.load(f)
                self.skills = {k: Skill.from_dict(v) for k, v in data.items()}
            except (json.JSONDecodeError, KeyError):
                self.skills = {}
        else:
            self.skills = {}

    def _save_skill(self, skill: Skill):
        """Save a skill to disk."""
        skills_file = os.path.join(self.storage_dir, "skills_registry.json")
        data = {k: v.to_dict() for k, v in self.skills.items()}
        with open(skills_file, "w") as f:
            json.dump(data, f, indent=2)

    def export(self, path: str = None) -> str:
        """Export all skills to JSON."""
        if path is None:
            path = os.path.join(self.storage_dir, f"skills_export_{int(time.time())}.json")

        data = {
            "export_time": time.time(),
            "skills": {k: v.to_dict() for k, v in self.skills.items()},
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

        return path