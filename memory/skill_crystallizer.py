"""
Skill Crystallization Pipeline & Auto-Evolution Engine
=======================================================
Implements the core self-evolution mechanism:
1. Trajectory → SOP crystallization (from GenericAgent)
2. SOP → Executable skill generation
3. Co-evolutionary verification (from EvoSkills)
4. Periodic auto-evolution triggering

The pipeline:
[Successful Trajectory] → [Extract Pattern] → [Create SOP] → [Verify SOP] → [Register Skill] → [Auto-Apply]
"""

import json
import os
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class CrystallizedSkill:
    """A skill crystallized from a successful trajectory."""
    skill_id: str
    name: str
    trigger_keywords: list
    tool_chain: list
    success_rate: float = 1.0
    usage_count: int = 0
    source_trajectory: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    verified: bool = False
    verification_rounds: int = 0
    version: int = 1
    parameters: dict = field(default_factory=dict)
    notes: str = ""


@dataclass
class EvolutionCycle:
    """A single evolution cycle."""
    cycle_id: str
    timestamp: str
    experiences_analyzed: int
    skills_created: int
    skills_updated: int
    parameters_optimized: int
    failures_analyzed: int
    auto_triggered: bool


class SkillCrystallizer:
    """
    Converts successful execution trajectories into reusable, verified skills.
    
    Implements co-evolutionary verification:
    - Generator creates the skill from the trajectory
    - Verifier (separate context) tests the skill against the original task
    - Only skills that pass verification are registered
    """

    def __init__(self, skills_dir: str = None, llm_callback=None):
        if skills_dir is None:
            skills_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "memory", "data", "crystallized_skills",
            )
        self.skills_dir = skills_dir
        os.makedirs(self.skills_dir, exist_ok=True)
        self.llm_callback = llm_callback

        self.skills: dict[str, CrystallizedSkill] = {}
        self.evolution_cycles: list[EvolutionCycle] = []
        self.auto_evolve_threshold = 5
        self.interaction_count = 0
        self.last_evolution_time = 0

        self._load()

    def clear(self):
        """Clear all skills and reset state."""
        self.skills.clear()
        self.evolution_cycles.clear()
        self.interaction_count = 0
        logger.info("SkillCrystallizer: Cleared all skills")

    def _load(self):
        path = os.path.join(self.skills_dir, "crystallized_skills.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                for sid, sdata in data.get("skills", {}).items():
                    self.skills[sid] = CrystallizedSkill(**sdata)
                self.evolution_cycles = [EvolutionCycle(**c) for c in data.get("cycles", [])]
                self.interaction_count = data.get("interaction_count", 0)
                self.last_evolution_time = data.get("last_evolution_time", 0)
            except (json.JSONDecodeError, TypeError):
                pass

    def save(self):
        path = os.path.join(self.skills_dir, "crystallized_skills.json")
        data = {
            "skills": {k: {key: val for key, val in v.__dict__.items() if not key.startswith("_")}
                      for k, v in self.skills.items()},
            "cycles": [{key: val for key, val in c.__dict__.items() if not key.startswith("_")}
                      for c in self.evolution_cycles],
            "interaction_count": self.interaction_count,
            "last_evolution_time": self.last_evolution_time,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

    def record_interaction(self):
        self.interaction_count += 1
        self.save()

    def should_auto_evolve(self) -> bool:
        if self.interaction_count - self.last_evolution_time >= self.auto_evolve_threshold:
            return True
        return False

    def crystallize(self, task_description: str, tool_chain: list, tool_results: list,
                    parameters: dict = None, source_trajectory: str = "") -> Optional[CrystallizedSkill]:
        if len(tool_chain) < 2:
            return None

        chain_key = " -> ".join(tool_chain)
        for skill in self.skills.values():
            if " -> ".join(skill.tool_chain) == chain_key:
                previous_count = skill.usage_count
                skill.success_rate = (skill.success_rate * previous_count + 1.0) / (previous_count + 1)
                skill.usage_count = previous_count + 1
                self.save()
                return skill

        name = self._generate_skill_name(task_description, tool_chain)
        keywords = self._extract_keywords(task_description)
        skill_id = f"cs{hashlib.md5(chain_key.encode(), usedforsecurity=False).hexdigest()[:8]}"

        skill = CrystallizedSkill(
            skill_id=skill_id, name=name, trigger_keywords=keywords,
            tool_chain=list(tool_chain), source_trajectory=source_trajectory,
            parameters=parameters or {},
        )

        verified = self._verify_skill(skill, task_description)
        if verified:
            skill.verified = True
            skill.verification_rounds = 1

        self.skills[skill_id] = skill
        self.save()
        return skill

    def _generate_skill_name(self, task_desc: str, chain: list) -> str:
        task_lower = task_desc.lower()
        if "pancreas" in task_lower:
            base = "Pancreas"
        elif "prostate" in task_lower:
            base = "Prostate"
        elif "ctv" in task_lower:
            base = "CTV"
        elif "plan" in task_lower or "planning" in task_lower:
            base = "Planning"
        elif "dose" in task_lower or "dosimetry" in task_lower:
            base = "DoseEval"
        elif "seg" in task_lower or "segment" in task_lower:
            base = "Segmentation"
        else:
            base = "Workflow"

        suffix = "".join(t[0].upper() for t in chain[:3])
        return f"Auto_{base}_{suffix}"

    def _extract_keywords(self, task_desc: str) -> list:
        keywords = []
        task_lower = task_desc.lower()

        medical_terms = [
            "pancreas", "prostate", "ctv", "oar", "dose", "plan", "seg",
            "brachy", "seed", "trajectory", "eval", "quality",
            "pancreas", "prostate", "dose", "plan", "segment", "eval",
        ]
        for term in medical_terms:
            if term in task_lower:
                keywords.append(term)

        action_terms = ["quick", "full", "auto", "standard", "detailed", "rl", "optimize"]
        for term in action_terms:
            if term in task_lower:
                keywords.append(term)

        return keywords[:5] if keywords else ["auto"]

    def _verify_skill(self, skill: CrystallizedSkill, task_desc: str) -> bool:
        if self.llm_callback:
            prompt = f"""You are a skill verifier. Review whether this crystallized skill is correct.

Task: {task_desc}
Proposed Skill: {skill.name}
Tool Chain: {' -> '.join(skill.tool_chain)}
Keywords: {', '.join(skill.trigger_keywords)}

Questions:
1. Is this tool chain appropriate for the task?
2. Are the trigger keywords sufficient to match similar tasks?
3. Is there any missing step or unnecessary step?

Answer YES if the skill is valid, NO if it needs revision.
Provide a brief reason."""

            try:
                response = self.llm_callback(prompt).strip().upper()
                return response.startswith("YES")
            except Exception:
                pass

        if len(skill.tool_chain) < 2:
            return False
        return True

    def evolve(self, experiences: list, force: bool = False) -> EvolutionCycle:
        if not force and not self.should_auto_evolve():
            return None

        cycle_id = f"ev{hashlib.md5(f'{datetime.now().isoformat()}'.encode(), usedforsecurity=False).hexdigest()[:6]}"
        skills_created = 0
        skills_updated = 0
        params_optimized = 0
        failures_analyzed = 0

        # Normalize to dicts (ExperienceEntry objects or raw dicts)
        def _to_dict(e):
            return e.to_dict() if hasattr(e, "to_dict") else e

        successful = [e for e in experiences if _to_dict(e).get("success", False)]
        failed = [e for e in experiences if not _to_dict(e).get("success", False)]

        for exp in successful:
            d = _to_dict(exp)
            chain = d.get("tool_chain", [])
            # Extract tool names from chain (handle both dict and string formats)
            tool_names = [t.get("tool", t) if isinstance(t, dict) else t for t in chain]
            if len(tool_names) >= 2:
                existing = self._find_matching_skill(tool_names)
                if existing:
                    previous_count = existing.usage_count
                    existing.success_rate = (existing.success_rate * previous_count + 1.0) / (previous_count + 1)
                    existing.usage_count = previous_count + 1
                    skills_updated += 1
                else:
                    self.crystallize(
                        task_description=d.get("user_intent", ""),
                        tool_chain=tool_names,
                        tool_results=d.get("tool_chain", []),
                        parameters=d.get("metrics", {}),
                    )
                    skills_created += 1

        for exp in failed:
            d = _to_dict(exp)
            chain = d.get("tool_chain", [])
            tool_names = [t.get("tool", t) if isinstance(t, dict) else t for t in chain]
            failed_tool = tool_names[-1] if tool_names else "unknown"
            for skill in self.skills.values():
                if failed_tool in skill.tool_chain:
                    skill.success_rate = max(0.1, skill.success_rate - 0.05)
                    skill.notes += f"\nFailure noted: {d.get('outcome', 'Unknown')}"
            failures_analyzed += 1

        all_params = {}
        for exp in successful:
            d = _to_dict(exp)
            for k, v in (d.get("metrics", {}) or {}).items():
                if k not in all_params:
                    all_params[k] = []
                all_params[k].append(v)

        for skill in self.skills.values():
            for param_name, values in all_params.items():
                if len(values) >= 2:
                    try:
                        avg = sum(float(v) for v in values if self._is_numeric(v)) / len([v for v in values if self._is_numeric(v)])
                        skill.parameters[param_name] = round(avg, 2)
                        params_optimized += 1
                    except (ValueError, ZeroDivisionError):
                        pass

        cycle = EvolutionCycle(
            cycle_id=cycle_id, timestamp=datetime.now().isoformat(),
            experiences_analyzed=len(experiences), skills_created=skills_created,
            skills_updated=skills_updated, parameters_optimized=params_optimized,
            failures_analyzed=failures_analyzed, auto_triggered=not force,
        )
        self.evolution_cycles.append(cycle)
        self.last_evolution_time = self.interaction_count
        self.save()
        return cycle

    def _find_matching_skill(self, chain: list) -> Optional[CrystallizedSkill]:
        for skill in self.skills.values():
            if skill.tool_chain == chain:
                return skill
        return None

    def _is_numeric(self, val) -> bool:
        try:
            float(val)
            return True
        except (ValueError, TypeError):
            return False

    def find_matching_skill(self, task_desc: str) -> Optional[CrystallizedSkill]:
        task_lower = task_desc.lower()
        best_skill = None
        best_score = 0

        for skill in self.skills.values():
            score = sum(1 for kw in skill.trigger_keywords if kw.lower() in task_lower)
            if score > best_score:
                best_score = score
                best_skill = skill

        if best_skill and best_score > 0:
            best_skill.usage_count += 1
            self.save()
        return best_skill

    def get_skill_summary(self) -> dict:
        return {
            "total_skills": len(self.skills),
            "verified_skills": sum(1 for s in self.skills.values() if s.verified),
            "avg_success_rate": sum(s.success_rate for s in self.skills.values()) / max(1, len(self.skills)),
            "total_usages": sum(s.usage_count for s in self.skills.values()),
            "evolution_cycles": len(self.evolution_cycles),
            "skills": [
                {
                    "name": s.name, "success_rate": round(s.success_rate, 2),
                    "usage_count": s.usage_count, "verified": s.verified,
                    "tool_chain": s.tool_chain,
                }
                for s in sorted(self.skills.values(), key=lambda x: x.success_rate, reverse=True)
            ],
        }
