"""
Tree-Search Exploration for Complex Planning (LATS-Inspired)
=============================================================
Implements Language Agent Tree Search (LATS) adapted for brachytherapy planning.
Explores multiple planning paths via Monte Carlo Tree Search, using LLM-powered
value functions and self-reflection for systematic exploration.

Key adaptation: Instead of generic actions, the tree explores tool-chain sequences
for medical planning tasks. Each node represents a partial plan state.

Inspired by: Zhou et al. (2023) "Language Agent Tree Search Unifies Reasoning, Acting, and Planning"
"""

import math
import hashlib
from dataclasses import dataclass, field
from typing import Optional, Callable
from datetime import datetime


@dataclass
class PlanningNode:
    """A node in the planning search tree."""
    node_id: str
    parent_id: Optional[str]
    tool_name: str
    tool_params: dict
    state_description: str
    children: list = field(default_factory=list)
    visits: int = 0
    value: float = 0.0
    depth: int = 0
    reflection: str = ""
    is_terminal: bool = False
    execution_result: dict = field(default_factory=dict)

    def _iter_ancestors(self, tree: "PlanningTreeSearch"):
        current = self
        while current:
            yield current
            if current.parent_id:
                current = tree._find_node(current.parent_id)
            else:
                current = None

    @property
    def ucb_score(self) -> float:
        if self.visits == 0:
            return float("inf")
        parent_visits = 1
        return self.value + 1.4 * math.sqrt(math.log(max(parent_visits, 2)) / self.visits)


class PlanningTreeSearch:
    """
    Monte Carlo Tree Search for brachytherapy planning.
    
    Explores multiple tool-chain sequences and selects the best one
    based on LLM-evaluated progress scores and execution feedback.
    """

    def __init__(self, max_depth: int = 7, max_branches: int = 3, max_iterations: int = 10,
                 tool_executor: Callable = None, llm_callback: Callable = None):
        self.max_depth = max_depth
        self.max_branches = max_branches
        self.max_iterations = max_iterations
        self.tool_executor = tool_executor
        self.llm_callback = llm_callback
        self.root: Optional[PlanningNode] = None
        self.search_log: list = []

    def search(self, task_description: str, available_tools: list,
               initial_state: dict = None) -> dict:
        self.root = PlanningNode(
            node_id="root", parent_id=None, tool_name="START",
            tool_params={}, state_description=task_description,
            depth=0,
        )
        self._store_node(self.root)

        initial_state = initial_state or {}

        for iteration in range(self.max_iterations):
            node = self._select(self.root)

            if node.depth < self.max_depth and not node.is_terminal:
                node = self._expand(node, available_tools, initial_state)

            if node and not node.is_terminal:
                value = self._evaluate(node, task_description, initial_state)
                self._backpropagate(node, value)

            self.search_log.append({
                "iteration": iteration + 1,
                "node": node.node_id if node else "none",
                "depth": node.depth if node else 0,
                "value": node.value if node else 0,
            })

        best_path = self._extract_best_path()
        return {
            "best_path": best_path,
            "best_value": self._get_path_value(best_path),
            "iterations": self.max_iterations,
            "nodes_explored": sum(1 for _ in self._iter_all_nodes()),
            "search_log": self.search_log,
        }

    def _select(self, node: PlanningNode) -> PlanningNode:
        current = node
        while current.children and not current.is_terminal:
            best_child = None
            best_score = -1
            for child_id in current.children:
                child = self._find_node(child_id)
                if child and child.ucb_score > best_score:
                    best_score = child.ucb_score
                    best_child = child
            if best_child:
                current = best_child
            else:
                break
        return current

    def _get_parent_visits(self, node: PlanningNode) -> int:
        count = 0
        current = node
        while current and current.parent_id:
            parent = self._find_node(current.parent_id)
            if parent:
                count += parent.visits
                current = parent
            else:
                break
        return max(count, 1)

    def _expand(self, node: PlanningNode, available_tools: list, state: dict) -> PlanningNode:
        candidate_tools = self._get_candidate_tools(node, available_tools, state)

        best_child = None
        best_score = -1

        for tool_name, params in candidate_tools[:self.max_branches]:
            child_id = f"{node.node_id}_{tool_name}_{hashlib.md5(str(params).encode()).hexdigest()[:4]}"

            if self.tool_executor:
                try:
                    result = self.tool_executor(tool_name, params)
                    success = result.get("success", False)
                    result_data = result
                except Exception as e:
                    success = False
                    result_data = {"success": False, "error": str(e)}
            else:
                success = True
                result_data = {"success": True}

            child = PlanningNode(
                node_id=child_id, parent_id=node.node_id,
                tool_name=tool_name, tool_params=params,
                state_description=f"After {tool_name}",
                depth=node.depth + 1,
                is_terminal=not success or node.depth + 1 >= self.max_depth,
                execution_result=result_data,
            )

            if self.llm_callback and success:
                reflection = self._reflect_on_step(
                    tool_name, params, result_data, state,
                )
                child.reflection = reflection

            node.children.append(child_id)
            self._store_node(child)

            if success and child.value > best_score:
                best_score = child.value
                best_child = child

        return best_child or node

    def _get_candidate_tools(self, node: PlanningNode, available_tools: list, state: dict) -> list:
        candidates = []
        current_depth = node.depth

        planning_sequences = {
            0: [("ctv_segmentation", {"auto": True}), ("oar_segmentation", {"auto": True})],
            1: [("oar_segmentation", {"auto": True}), ("radiation_volume", {})],
            2: [("trajectory_planning", {"auto": True}), ("radiation_volume", {})],
            3: [("seed_planning", {"auto": True}), ("trajectory_planning", {})],
            4: [("dose_calculation", {"method": "cnn"}), ("seed_planning", {})],
            5: [("dose_evaluation", {"comprehensive": True}), ("dose_calculation", {})],
            6: [("plan_quality_check", {}), ("dose_evaluation", {})],
        }

        for seq_depth, tools in planning_sequences.items():
            if seq_depth == current_depth:
                for tool_name, params in tools:
                    if tool_name in available_tools:
                        candidates.append((tool_name, params))

        if not candidates:
            for tool in available_tools:
                if tool not in [node.tool_name]:
                    candidates.append((tool, {"auto": True}))

        return candidates[:self.max_branches * 2]

    def _evaluate(self, node: PlanningNode, task_desc: str, state: dict) -> float:
        if node.is_terminal and node.execution_result.get("success"):
            return 1.0
        elif node.is_terminal:
            return 0.0

        if self.llm_callback:
            prompt = f"""Evaluate the current progress of this brachytherapy planning task.

Task: {task_desc}
Current step: {node.tool_name} at depth {node.depth}/{self.max_depth}
State: {node.state_description}
Execution result: {node.execution_result}

Score from 0.0 (no progress) to 1.0 (complete). Only return a number."""
            try:
                response = self.llm_callback(prompt).strip()
                score = float(response.split()[0])
                return max(0.0, min(1.0, score))
            except (ValueError, IndexError):
                pass

        return node.depth / self.max_depth

    def _backpropagate(self, node: PlanningNode, value: float):
        current = node
        while current:
            current.visits += 1
            current.value = (current.value * (current.visits - 1) + value) / current.visits
            if current.parent_id:
                current = self._find_node(current.parent_id)
            else:
                break

    def _reflect_on_step(self, tool_name: str, params: dict, result: dict, state: dict) -> str:
        if not self.llm_callback:
            return ""

        prompt = f"""Review this planning step:

Tool: {tool_name}
Parameters: {params}
Result: {result}

Is this step appropriate for the overall plan? What should be the next step?
Provide a brief reflection (1-2 sentences)."""

        try:
            return self.llm_callback(prompt).strip()
        except Exception:
            return ""

    def _extract_best_path(self) -> list:
        path = []
        current = self.root

        while current and current.children:
            best_child_id = None
            best_value = -1
            for child_id in current.children:
                child = self._find_node(child_id)
                if child and child.value > best_value:
                    best_value = child.value
                    best_child_id = child_id

            if best_child_id:
                best_child = self._find_node(best_child_id)
                path.append({
                    "tool": best_child.tool_name,
                    "params": best_child.tool_params,
                    "value": round(best_child.value, 3),
                    "reflection": best_child.reflection,
                })
                current = best_child
            else:
                break

        return path

    def _get_path_value(self, path: list) -> float:
        if not path:
            return 0.0
        return path[-1].get("value", 0.0)

    def _find_node(self, node_id: str) -> Optional[PlanningNode]:
        if hasattr(self, "_node_cache"):
            return self._node_cache.get(node_id)
        return None

    def _store_node(self, node: PlanningNode):
        if not hasattr(self, "_node_cache"):
            self._node_cache = {}
        self._node_cache[node.node_id] = node

    def _iter_all_nodes(self):
        if hasattr(self, "_node_cache"):
            yield from self._node_cache.values()

    def get_search_summary(self) -> dict:
        return {
            "iterations": self.max_iterations,
            "nodes_explored": sum(1 for _ in self._iter_all_nodes()),
            "max_depth_reached": max((n.depth for n in self._iter_all_nodes()), default=0),
            "best_path_length": len(self._extract_best_path()),
        }
