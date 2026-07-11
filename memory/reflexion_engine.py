"""
Trajectory-Based Self-Reflection (Reflexion Pattern)
=====================================================
Implements the Reflexion framework: Actor/Evaluator/Self-Reflection loop.
After each task execution, the agent critiques its own trajectory,
extracts lessons, and stores them in episodic memory for future reuse.

Inspired by: Shinn et al. (2023) "Reflexion: Language Agents with Verbal Reinforcement Learning"
Extended with: Multi-Agent Reflexion (MAR) to avoid confirmation bias.
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
class ReflexionEntry:
    """A single self-reflection on a trajectory."""
    id: str
    trajectory_id: str
    task_description: str
    tool_chain: list
    outcome: str
    success: bool
    critique: str = ""
    root_cause: str = ""
    lesson: str = ""
    alternative_approach: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    applied_count: int = 0


@dataclass
class EpisodicMemory:
    """Stores reflections for cross-trajectory learning."""
    reflections: dict = field(default_factory=dict)
    failure_patterns: dict = field(default_factory=dict)
    success_patterns: dict = field(default_factory=dict)


class ReflexionEngine:
    """
    Self-reflection engine that critiques trajectories and extracts reusable lessons.
    
    Three modes:
    1. Self-Reflection: Agent critiques its own trajectory
    2. Multi-Agent Reflexion (MAR): Separate critic personas review the trajectory
    3. Heuristic Reflection: Rule-based pattern detection for common failures
    """

    def __init__(self, memory_dir: str = None, llm_callback=None):
        if memory_dir is None:
            memory_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory", "data")
        self.memory_dir = memory_dir
        os.makedirs(self.memory_dir, exist_ok=True)
        self.llm_callback = llm_callback

        self.episodic = EpisodicMemory()
        self.max_reflections = 10
        self._load()

    def clear(self):
        """Clear all reflections and reset state."""
        self.episodic.reflections.clear()
        self.episodic.failure_patterns.clear()
        logger.info("ReflexionEngine: Cleared all reflections")

    def _load(self):
        path = os.path.join(self.memory_dir, "reflexion_memory.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                for rid, rdata in data.get("reflections", {}).items():
                    self.episodic.reflections[rid] = ReflexionEntry(**rdata)
                self.episodic.failure_patterns = data.get("failure_patterns", {})
                self.episodic.success_patterns = data.get("success_patterns", {})
            except (json.JSONDecodeError, TypeError):
                pass

    def save(self):
        path = os.path.join(self.memory_dir, "reflexion_memory.json")
        serializable = {
            "reflections": {k: {key: val for key, val in v.__dict__.items() if not key.startswith("_")}
                           for k, v in self.episodic.reflections.items()},
            "failure_patterns": self.episodic.failure_patterns,
            "success_patterns": self.episodic.success_patterns,
        }
        with open(path, "w") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False, default=str)

    def reflect(self, task_description: str, tool_chain: list, tool_results: list,
                outcome: str, success: bool, mode: str = "auto") -> ReflexionEntry:
        """
        Perform self-reflection on a completed trajectory.
        
        Args:
            task_description: What the user asked for
            tool_chain: List of tool names that were executed
            tool_results: List of (tool_name, success, message) tuples
            outcome: Final result description
            success: Whether the task succeeded
            mode: "auto", "self", "mar", or "heuristic"
        """
        trajectory_id = f"traj{hashlib.md5(f'{task_description}{tool_chain}'.encode(), usedforsecurity=False).hexdigest()[:8]}"

        if mode == "auto":
            if not success:
                mode = "mar"
            else:
                mode = "heuristic"

        if mode == "self" and self.llm_callback:
            critique, root_cause, lesson, alternative = self._self_reflect_llm(
                task_description, tool_chain, tool_results, outcome, success,
            )
        elif mode == "mar" and self.llm_callback:
            critique, root_cause, lesson, alternative = self._multi_agent_reflexion(
                task_description, tool_chain, tool_results, outcome, success,
            )
        else:
            critique, root_cause, lesson, alternative = self._heuristic_reflection(
                task_description, tool_chain, tool_results, outcome, success,
            )

        entry = ReflexionEntry(
            id=f"ref{hashlib.md5(f'{trajectory_id}{datetime.now().isoformat()}'.encode(), usedforsecurity=False).hexdigest()[:6]}",
            trajectory_id=trajectory_id,
            task_description=task_description,
            tool_chain=tool_chain,
            outcome=outcome,
            success=success,
            critique=critique,
            root_cause=root_cause,
            lesson=lesson,
            alternative_approach=alternative,
        )

        self.episodic.reflections[entry.id] = entry

        if success:
            self._update_success_patterns(tool_chain, task_description)
        else:
            self._update_failure_patterns(tool_chain, tool_results, root_cause)

        self._trim_reflections()
        self.save()
        return entry

    def _self_reflect_llm(self, task, chain, results, outcome, success):
        prompt = f"""You are a medical AI agent reviewing your own performance.

Task: {task}
Tools used: {' -> '.join(chain)}
Results:
"""
        for tool_name, tool_success, tool_msg in results:
            prompt += f"- {tool_name}: {'OK' if tool_success else 'FAILED'} - {tool_msg}\n"
        prompt += f"\nFinal outcome: {outcome}\nOverall success: {success}\n\n"
        prompt += """Provide a structured critique:
1. CRITIQUE: What went well and what went wrong?
2. ROOT_CAUSE: What was the fundamental issue (if any)?
3. LESSON: One key takeaway for future similar tasks.
4. ALTERNATIVE: What would you do differently next time?

Format as:
CRITIQUE: ...
ROOT_CAUSE: ...
LESSON: ...
ALTERNATIVE: ..."""

        try:
            response = self.llm_callback(prompt)
            if not isinstance(response, str) or not response.strip():
                return self._heuristic_reflection(task, chain, results, outcome, success)
            lines = response.strip().split("\n")
            critique = root_cause = lesson = alternative = ""
            for line in lines:
                if line.startswith("CRITIQUE:"):
                    critique = line[len("CRITIQUE:"):].strip()
                elif line.startswith("ROOT_CAUSE:"):
                    root_cause = line[len("ROOT_CAUSE:"):].strip()
                elif line.startswith("LESSON:"):
                    lesson = line[len("LESSON:"):].strip()
                elif line.startswith("ALTERNATIVE:"):
                    alternative = line[len("ALTERNATIVE:"):].strip()
            return critique, root_cause, lesson, alternative
        except Exception:
            return self._heuristic_reflection(task, chain, results, outcome, success)

    def _multi_agent_reflexion(self, task, chain, results, outcome, success):
        """
        Multi-Agent Reflexion (MAR): Three separate critic personas review the trajectory.
        This avoids confirmation bias that occurs when a single model critiques itself.
        """
        personas = [
            ("Clinical Safety Reviewer", "Focus on clinical safety and protocol compliance. "
             "Would this approach be safe for a real patient? What clinical guidelines were followed or violated?"),
            ("Technical Efficiency Reviewer", "Focus on technical efficiency and tool selection. "
             "Were the right tools used in the right order? Could the workflow be optimized?"),
            ("Error Analysis Specialist", "Focus on failure modes and error patterns. "
             "What specific errors occurred? What are the root causes? How can they be prevented?"),
        ]

        all_critiques = []
        for persona_name, persona_focus in personas:
            prompt = f"""You are a {persona_name} reviewing a medical AI agent's performance.

{persona_focus}

Task: {task}
Tools used: {' -> '.join(chain)}
Results:
"""
            for tool_name, tool_success, tool_msg in results:
                prompt += f"- {tool_name}: {'OK' if tool_success else 'FAILED'} - {tool_msg}\n"
            prompt += f"\nFinal outcome: {outcome}\nOverall success: {success}\n\n"
            prompt += "Provide your critique in 2-3 sentences."

            try:
                response = self.llm_callback(prompt)
                if isinstance(response, str) and response.strip():
                    all_critiques.append(f"[{persona_name}] {response.strip()}")
            except Exception as exc:
                logger.warning("Multi-agent reflexion persona '%s' failed: %s", persona_name, exc)

        combined_critique = "\n".join(all_critiques) if all_critiques else "No critiques generated."

        root_cause = ""
        lesson = ""
        alternative = ""

        if not success:
            failed_tools = [t[0] for t in results if not t[1]]
            if failed_tools:
                root_cause = f"Failure in tool(s): {', '.join(failed_tools)}"
                lesson = f"When using {', '.join(failed_tools)}, verify inputs carefully and have fallback ready"
                alternative = f"Try alternative tools or validate inputs before calling {', '.join(failed_tools)}"
            else:
                root_cause = "Task outcome did not meet success criteria"
                lesson = "Review task requirements and ensure all success criteria are met"
                alternative = "Consider breaking the task into smaller sub-tasks"

        return combined_critique, root_cause, lesson, alternative

    def _heuristic_reflection(self, task, chain, results, outcome, success):
        critique = ""
        root_cause = ""
        lesson = ""
        alternative = ""

        if not success:
            failed_tools = [t[0] for t in results if not t[1]]
            repeated_actions = self._detect_repetitions(results)

            if failed_tools:
                critique = f"Task failed. Failed tool(s): {', '.join(failed_tools)}"
                root_cause = f"Execution failure in: {', '.join(failed_tools)}"
                lesson = f"Verify preconditions before calling {', '.join(failed_tools)}"
                alternative = f"Check input data quality and tool availability before execution"
            elif repeated_actions:
                critique = f"Agent got stuck in repetitive loop: {repeated_actions}"
                root_cause = "Inefficient planning led to repeated identical actions"
                lesson = "If a tool fails twice, try a different approach or tool"
                alternative = "Implement backtracking when the same action fails multiple times"
            else:
                critique = "Task did not achieve desired outcome"
                root_cause = "Unclear failure mode"
                lesson = "Add more diagnostic checks during execution"
                alternative = "Break task into smaller verifiable steps"
        else:
            critique = "Task completed successfully"
            if len(chain) > 5:
                lesson = f"Long chain ({len(chain)} tools) succeeded; consider if all steps were necessary"
            else:
                lesson = f"Efficient {len(chain)}-step workflow for this task type"

        return critique, root_cause, lesson, alternative

    def _detect_repetitions(self, results):
        tool_names = [r[0] for r in results]
        for i in range(len(tool_names) - 2):
            if tool_names[i] == tool_names[i + 1] == tool_names[i + 2]:
                return tool_names[i]
        return None

    def _update_failure_patterns(self, chain, results, root_cause):
        for tool_name, tool_success, tool_msg in results:
            if not tool_success:
                pattern_key = tool_name
                if pattern_key not in self.episodic.failure_patterns:
                    self.episodic.failure_patterns[pattern_key] = {
                        "count": 0, "root_causes": [], "contexts": [], "last_seen": "",
                    }
                self.episodic.failure_patterns[pattern_key]["count"] += 1
                if root_cause and root_cause not in self.episodic.failure_patterns[pattern_key]["root_causes"]:
                    self.episodic.failure_patterns[pattern_key]["root_causes"].append(root_cause)
                self.episodic.failure_patterns[pattern_key]["contexts"].append(" -> ".join(chain))
                self.episodic.failure_patterns[pattern_key]["last_seen"] = datetime.now().isoformat()

    def _update_success_patterns(self, chain, task_desc):
        chain_key = " -> ".join(chain)
        if chain_key not in self.episodic.success_patterns:
            self.episodic.success_patterns[chain_key] = {
                "count": 0, "tasks": [], "last_used": "",
            }
        self.episodic.success_patterns[chain_key]["count"] += 1
        self.episodic.success_patterns[chain_key]["tasks"].append(task_desc)
        self.episodic.success_patterns[chain_key]["last_used"] = datetime.now().isoformat()

    def _trim_reflections(self):
        if len(self.episodic.reflections) > self.max_reflections:
            sorted_refs = sorted(
                self.episodic.reflections.values(),
                key=lambda r: r.applied_count, reverse=True,
            )
            keep = sorted_refs[:self.max_reflections]
            self.episodic.reflections = {r.id: r for r in keep}

    def get_relevant_reflections(self, query: str, top_k: int = 3) -> list[ReflexionEntry]:
        query_lower = query.lower()
        scored = []
        for entry in self.episodic.reflections.values():
            score = 0
            if query_lower in entry.task_description.lower():
                score += 3
            for tool in entry.tool_chain:
                if query_lower in tool.lower():
                    score += 2
            if query_lower in entry.lesson.lower():
                score += 2
            if query_lower in entry.root_cause.lower():
                score += 1
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:top_k]]

    def get_failure_warnings(self, tool_name: str) -> list[str]:
        if tool_name in self.episodic.failure_patterns:
            pattern = self.episodic.failure_patterns[tool_name]
            warnings = []
            if pattern["count"] >= 3:
                warnings.append(f"WARNING: {tool_name} has failed {pattern['count']} times")
            for rc in pattern["root_causes"][:2]:
                warnings.append(f"Known issue: {rc}")
            return warnings
        return []

    def get_success_recommendations(self, task_desc: str) -> list[str]:
        recommendations = []
        for chain_key, pattern in self.episodic.success_patterns.items():
            if pattern["count"] >= 2:
                for prev_task in pattern["tasks"]:
                    if any(word in task_desc.lower() for word in prev_task.lower().split() if len(word) > 3):
                        recommendations.append(
                            f"Proven workflow: {chain_key} (used {pattern['count']} times successfully)"
                        )
                        break
        return recommendations

    def get_reflection_context(self, task_desc: str) -> str:
        relevant = self.get_relevant_reflections(task_desc)
        warnings = []
        for entry in relevant:
            if not entry.success:
                warnings.append(f"Past failure: {entry.critique}")
                warnings.append(f"Lesson: {entry.lesson}")
                if entry.alternative_approach:
                    warnings.append(f"Alternative: {entry.alternative_approach}")

        recommendations = self.get_success_recommendations(task_desc)

        context = ""
        if warnings:
            context += "\n### Past Failures to Avoid\n" + "\n".join(f"- {w}" for w in warnings)
        if recommendations:
            context += "\n### Proven Workflows\n" + "\n".join(f"- {r}" for r in recommendations)
        return context
