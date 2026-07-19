"""Chat and planning workflow mixin methods for BrachyAgent.

The methods are kept as regular class methods so the public AgenticSys.BrachyAgent
API remains compatible while the monolithic implementation is easier to review.
"""

import ast
import json
import logging
import os
import re
import threading
import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import SimpleITK as sitk

from agent_runtime.core import PlanningPhase
from agent_runtime.contracts import RunStatus
from agent_runtime.turn_policy import classify_local_turn

logger = logging.getLogger(__name__)


class ChatWorkflowMixin:
    @staticmethod
    def _is_3d_status_request(message: str) -> bool:
        """Recognize questions that require a concrete 3D viewer diagnosis."""
        text = str(message or "")
        return bool(re.search(
            r"(?:3d|3-d|three[- ]?dimensional|三维|3d viewer|三维窗口).*(?:空白|黑|不显示|消失|没有|看不到|blank|black|empty|missing|not\s+show|disappear)"
            r"|(?:空白|黑屏|什么都不显示|不显示任何内容).*(?:3d|三维|viewer|窗口)",
            text,
            re.IGNORECASE,
        ))

    def _build_3d_status_response(self, lang: str = "en") -> str:
        """Explain the current 3D state without inventing a rendering cause."""
        ui_state = self.memory.get_ui_state() or {}
        viewer = ui_state.get("viewer") if isinstance(ui_state.get("viewer"), dict) else {}
        three_d = viewer.get("three_d") if isinstance(viewer.get("three_d"), dict) else {}
        mesh_count = three_d.get("mesh_count")
        visible_count = three_d.get("visible_mesh_count")
        initialized = three_d.get("initialized")
        canvas_w = three_d.get("canvas_width")
        canvas_h = three_d.get("canvas_height")

        if lang == "zh":
            lines = ["我检查了当前 Web UI 上报的 3D 状态："]
            if initialized is None:
                lines.append("- 当前会话尚未提供 3D 渲染器状态，暂时不能确认是模型、可见性还是 WebGL 原因。")
            else:
                lines.append(f"- 渲染器：{'已初始化' if initialized else '未初始化'}；场景模型：{mesh_count or 0} 个；当前可见：{visible_count or 0} 个。")
                if canvas_w is not None and canvas_h is not None:
                    lines.append(f"- 画布尺寸：{canvas_w} × {canvas_h}。")
            if isinstance(mesh_count, int) and mesh_count > 0 and isinstance(visible_count, int) and visible_count == 0:
                lines.append("这更像是模型被数据树可见性/透明度状态全部隐藏，或报告截图恢复过程未同步完成；不是 CT/规划数据必然丢失。")
                lines.append("请先点击 3D Viewer 的 Normal Surface 或数据树的父级可见性开关；系统会在下一次渲染时尝试恢复有意显示的对象。")
            elif isinstance(mesh_count, int) and mesh_count == 0:
                lines.append("当前场景没有已加载的 3D 模型，通常表示 3D 重建尚未完成或重建结果没有重新挂载到当前会话。")
                lines.append("可重新执行 3D Reconstruction/刷新 Viewer；这不会重新计算剂量。")
            elif isinstance(canvas_w, int) and isinstance(canvas_h, int) and (canvas_w < 10 or canvas_h < 10):
                lines.append("渲染画布尺寸接近 0，常见于 Viewer 面板刚切换或布局尚未完成；重新打开 Viewers 面板会触发 resize 和重绘。")
            else:
                lines.append("如果画布仍是黑屏，下一步应查看浏览器 WebGL context lost/restore 日志，而不是重新运行规划。")
            return "\n".join(lines)

        lines = ["I checked the 3D state reported by the Web UI:"]
        if initialized is None:
            lines.append("- This session has not reported renderer telemetry yet, so the cause cannot be assigned to model visibility or WebGL with confidence.")
        else:
            lines.append(f"- Renderer: {'initialized' if initialized else 'not initialized'}; scene meshes: {mesh_count or 0}; visible meshes: {visible_count or 0}.")
            if canvas_w is not None and canvas_h is not None:
                lines.append(f"- Canvas size: {canvas_w} x {canvas_h}.")
        if isinstance(mesh_count, int) and mesh_count > 0 and isinstance(visible_count, int) and visible_count == 0:
            lines.append("This points to all scene objects being hidden by data-tree visibility/opacity state, or to an incomplete report-capture restore; it does not by itself mean the CT or plan was lost.")
            lines.append("Toggle Normal Surface or the relevant parent visibility control; the viewer will attempt a render-time recovery for objects that should be visible.")
        elif isinstance(mesh_count, int) and mesh_count == 0:
            lines.append("The scene has no mounted 3D meshes, which usually means reconstruction has not completed or its results were not reattached to this session.")
            lines.append("Run 3D Reconstruction/refresh the Viewer; this does not recompute dose.")
        elif isinstance(canvas_w, int) and isinstance(canvas_h, int) and (canvas_w < 10 or canvas_h < 10):
            lines.append("The render canvas is effectively zero-sized, commonly while the Viewer panel is changing layout; reopening Viewers will trigger resize and redraw.")
        else:
            lines.append("If the canvas remains black, the next diagnostic is the browser WebGL context-lost/restore log, not another planning run.")
        return "\n".join(lines)

    def _begin_turn(self, message: str = "") -> int:
        """Start an isolated chat turn and return its cancellation token."""
        lock = getattr(self, "_turn_state_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._turn_state_lock = lock
        with lock:
            self._turn_generation = int(getattr(self, "_turn_generation", 0)) + 1
            self._active_turn_token = self._turn_generation
            self._cancel_requested = False
            token = self._active_turn_token
        local = getattr(self, "_turn_local", None)
        if local is None:
            local = threading.local()
            self._turn_local = local
        local.token = token
        ledger = getattr(self, "run_ledger", None)
        if ledger is not None:
            ledger.begin(message)
        return token

    def _current_turn_token(self) -> int:
        local = getattr(self, "_turn_local", None)
        token = getattr(local, "token", None) if local is not None else None
        return int(token if token is not None else getattr(self, "_active_turn_token", 0))

    def _cancel_active_turn(self) -> None:
        """Invalidate the active turn without allowing a later turn to revive it."""
        lock = getattr(self, "_turn_state_lock", None)
        if lock is None:
            self._cancel_requested = True
            return
        with lock:
            self._cancel_requested = True
            self._turn_generation = int(getattr(self, "_turn_generation", 0)) + 1
            self._active_turn_token = self._turn_generation
        ledger = getattr(self, "run_ledger", None)
        if ledger is not None:
            ledger.transition(RunStatus.CANCELLED, "run.cancelled_by_user")

    def _finish_turn(self, response: Any) -> None:
        """Close a run unless its next valid state is user clarification."""
        ledger = getattr(self, "run_ledger", None)
        if ledger is None or ledger.active_status() is None:
            return
        if ledger.active_status() == RunStatus.AWAITING_INPUT:
            return
        if bool(getattr(self, "_cancel_requested", False)):
            ledger.transition(RunStatus.CANCELLED, "run.cancelled")
            return
        text = str(response or "").strip().lower()
        failed = text.startswith("error:") or text.startswith("exception:")
        ledger.transition(
            RunStatus.FAILED if failed else RunStatus.COMPLETED,
            "run.failed" if failed else "run.completed",
        )

    def _is_turn_cancelled(self, token: int) -> bool:
        lock = getattr(self, "_turn_state_lock", None)
        if lock is None:
            return bool(getattr(self, "_cancel_requested", False))
        with lock:
            return bool(getattr(self, "_cancel_requested", False)) or int(token) != int(
                getattr(self, "_active_turn_token", 0)
            )

    def _parse_tool_calls(self, content: str) -> List[Dict]:
        """Parse tool calls from LLM response. Supports multiple formats."""
        tool_calls = []

        # Format 1: ```tool_call blocks
        pattern = r'```tool_call\s*\n(.*?)\n```'
        matches = re.findall(pattern, content, re.DOTALL)
        for match in matches:
            try:
                # Try direct parse first
                tc = json.loads(match.strip())
                if isinstance(tc, list):
                    tool_calls.extend(tc)
                elif isinstance(tc, dict) and "tool" in tc:
                    tool_calls.append(tc)
            except json.JSONDecodeError:
                # If direct parse fails, try to extract the JSON object
                # by finding the outermost braces
                cleaned = match.strip()
                start = cleaned.find('{')
                end = cleaned.rfind('}')
                if start != -1 and end != -1 and end > start:
                    json_str = cleaned[start:end+1]
                    # Fix: escape literal newlines in string values
                    # This handles the case where the LLM outputs JSON with actual newlines
                    fixed = json_str.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
                    try:
                        tc = json.loads(fixed)
                        if isinstance(tc, list):
                            tool_calls.extend(tc)
                        elif isinstance(tc, dict) and "tool" in tc:
                            tool_calls.append(tc)
                    except json.JSONDecodeError:
                        pass

        # Format 1B: Python list format tool_use (MiniMax sometimes outputs this)
        if not tool_calls:
            # Match [{'type': 'tool_use', ...}] or [{"type": "tool_use", ...}]
            py_tool_use = re.search(r"\[[\s]*\{[\s]*['\"]type['\"]\s*:\s*['\"]tool_use['\"].*?\}[\s]*\]", content, re.DOTALL)
            if py_tool_use:
                try:
                    raw = py_tool_use.group(0)
                    # MiniMax may emit Python repr style tool_use blocks. Use
                    # literal_eval instead of global quote replacement so
                    # apostrophes inside user strings are preserved.
                    parsed = ast.literal_eval(raw) if "'" in raw else json.loads(raw)
                    if isinstance(parsed, list):
                        for item in parsed:
                            if isinstance(item, dict) and item.get("type") == "tool_use":
                                tool_calls.append({
                                    "id": item.get("id", f"tool_{len(tool_calls)}"),
                                    "tool": item.get("name", ""),
                                    "params": item.get("input", {}),
                                })
                except (json.JSONDecodeError, Exception):
                    pass

        # Format 2: MiniMax XML-style variations
        if not tool_calls:
            minimax_pattern = r'<minimax:tool_call>(.*?)</minimax:tool_call>'
            minimax_matches = re.findall(minimax_pattern, content, re.DOTALL)
            for match in minimax_matches:
                try:
                    invoke_match = re.search(r'<invoke\s+name="([^"]+)">(.*?)</invoke>', match, re.DOTALL)
                    if invoke_match:
                        tool_name = invoke_match.group(1)
                        inner = invoke_match.group(2)
                        params = {}
                        for pmatch in re.finditer(r'<parameter\s+name="([^"]+)">(.*?)</parameter>', inner, re.DOTALL):
                            params[pmatch.group(1)] = pmatch.group(2)
                        tool_calls.append({"tool": tool_name, "params": params})
                        continue
                    # Format 2B: <invoke name="tool_name", "params": {...}>
                    invoke_json = re.search(r'<invoke\s+name="([^"]+)",\s*"params":\s*\{', match, re.DOTALL)
                    if invoke_json:
                        tool_name = invoke_json.group(1)
                        # Find the matching closing brace by counting
                        brace_start = invoke_json.end() - 1  # position of opening {
                        depth = 0
                        brace_end = -1
                        for i in range(brace_start, len(match)):
                            if match[i] == '{':
                                depth += 1
                            elif match[i] == '}':
                                depth -= 1
                                if depth == 0:
                                    brace_end = i
                                    break
                        if brace_end != -1:
                            params_str = match[brace_start:brace_end+1]
                            tool_calls.append({"tool": tool_name, "params": json.loads(params_str)})
                            continue
                except (json.JSONDecodeError, AttributeError):
                    pass

        # Format 3: [TOOL_CALL] prefix with JSON
        if not tool_calls:
            toc_pattern = r'\[TOOL_CALL\]\s*(\{.*?\})'
            toc_matches = re.findall(toc_pattern, content, re.DOTALL)
            for match in toc_matches:
                try:
                    tc = json.loads(match.strip())
                    if isinstance(tc, dict) and "tool" in tc:
                        tool_calls.append(tc)
                except json.JSONDecodeError:
                    # Try extracting from nested braces
                    start = match.find('{')
                    end = match.rfind('}')
                    if start != -1 and end != -1 and end > start:
                        try:
                            tc = json.loads(match[start:end+1].replace('\n', '\\n'))
                            if isinstance(tc, dict) and "tool" in tc:
                                tool_calls.append(tc)
                        except json.JSONDecodeError:
                            pass

        # Format 4: Bare JSON objects with "tool" key
        if not tool_calls:
            pattern2 = r'\{[^{}]*"tool"[^{}]*\}'
            matches2 = re.findall(pattern2, content)
            for match in matches2:
                try:
                    tc = json.loads(match)
                    if "tool" in tc:
                        tool_calls.append(tc)
                except json.JSONDecodeError:
                    pass

        # Format 5: Anthropic format [{"type": "tool_use", "name": "...", "input": {...}}]
        if not tool_calls:
            anthropic_pattern = r'\[[\s]*\{[^{}]*"type"\s*:\s*"tool_use"[^{}]*"name"\s*:\s*"([^"]+)"[^{}]*"input"\s*:\s*(\{[^}]*\})[^{}]*\}[\s]*\]'
            anthropic_matches = re.findall(anthropic_pattern, content, re.DOTALL)
            for name, input_str in anthropic_matches:
                try:
                    params = json.loads(input_str)
                    tool_calls.append({"tool": name, "params": params})
                except json.JSONDecodeError:
                    tool_calls.append({"tool": name, "params": {}})

        return tool_calls

    def _handle_self_evolution(self) -> str:
        """Handle self-evolution request."""
        if not self.evolution_engine:
            return "Self-evolution system not available."
        results = self.evolution_engine.evolve()
        lines = ["Self-evolution cycle complete:"]
        if results["new_skills"]:
            lines.append(f"  New skills: {len(results['new_skills'])}")
            for s in results["new_skills"]:
                lines.append(f"    - {s['name']}: {s['description']}")
        if results["lessons"]:
            lines.append(f"  Lessons learned: {len(results['lessons'])}")
        if results["parameter_updates"]:
            lines.append(f"  Parameter optimizations: {len(results['parameter_updates'])}")
        if results["failure_insights"]:
            lines.append(f"  Failure insights: {len(results['failure_insights'])}")
        summary = self.evolution_engine.get_evolution_summary()
        lines.append(f"\nTotal experiences: {summary['experience_summary']['total_experiences']}")
        lines.append(f"Success rate: {summary['experience_summary']['success_rate']:.1%}")
        return "\n".join(lines)

    def _handle_code_writing(self, params: Dict) -> str:
        """Handle tool code writing request."""
        if not self.tool_code_writer:
            return "Tool code writer not available."
        if not self.brain_available:
            return "LLM brain required for code writing."

        tool_spec = params.get("tool_spec", params)
        if "name" not in tool_spec:
            spec_prompt = (
                "Please provide a tool specification with these fields:\n"
                "- name: tool name (snake_case)\n"
                "- description: what the tool does\n"
                "- category: subdirectory under tool_factory/\n"
                "- input_schema: input parameters\n"
                "- output_schema: output format\n"
                "- execute_logic: Python code for the _execute method"
            )
            return spec_prompt

        result = self.tool_code_writer.generate_tool_from_llm_spec(tool_spec)
        if result["success"]:
            tool_info = result["tool"]
            reg_result = self.tool_code_writer.register_generated_tool(tool_info["name"])
            if reg_result["success"]:
                return (
                    f"Tool '{tool_info['name']}' generated and registered successfully!\n"
                    f"  File: {tool_info['file_path']}\n"
                    f"  Class: {tool_info['class_name']}\n"
                    f"  Description: {tool_info['description']}"
                )
            else:
                return f"Tool generated but registration failed: {reg_result['error']}"
        else:
            return f"Tool generation failed: {result['error']}"

    def chat(self, message: str) -> str:
        self._begin_turn(message)
        self.memory.add_message("user", message)
        self.memory.user_lang = "zh" if re.search(r'[一-鿿]', message) else "en"

        if self.enhanced:
            self.enhanced.pre_task_hook(message)

        if self.brain_available:
            _result = self._run_llm_function_calling(message, [], [0])
            response = _result[0] if isinstance(_result, tuple) else _result
        else:
            response = self._rule_based_chat(message)

        self._record_experience(message, response)

        if self.enhanced:
            tool_chain = []
            tool_results = []
            for step in self.memory.tool_results[-10:]:
                tool_chain.append(step.get("tool", ""))
                tool_results.append((step.get("tool", ""), step.get("success", False), step.get("message", "")))
            self.enhanced.post_task_hook(
                user_input=message, tool_chain=tool_chain, tool_results=tool_results,
                outcome=response[:500], success="error" not in response.lower() and "fail" not in response.lower(),
            )

        self._finish_turn(response)
        return response

    def chat_with_trace(self, message: str) -> Dict[str, Any]:
        self._begin_turn(message)
        self.memory.add_message("user", message)
        self.memory.user_lang = "zh" if re.search(r'[一-鿿]', message) else "en"
        steps = []
        step_id = [0]

        def add_step(step_type, title, content, status="done", **kwargs):
            step_id[0] += 1
            steps.append({
                "id": step_id[0],
                "type": step_type,
                "title": title,
                "content": content,
                "status": status,
                **kwargs
            })

        add_step("user", "User Input", message)

        # Deterministic low-risk turns should not spend an LLM round-trip on
        # routing, context assembly, or completeness review. Clinical and
        # evidence-based requests are intentionally excluded by the policy.
        local_policy = classify_local_turn(message)
        self._active_turn_policy = local_policy
        if local_policy.fast_response is not None:
            add_step("thinking", "Local Fast Path", "Answered locally; no model call required.")
            self._finish_turn(local_policy.fast_response)
            return {
                "response": local_policy.fast_response,
                "steps": steps,
                "llm_meta": {
                    "usage": {}, "latency_ms": 0, "llm_calls": 0,
                    "route": "local_fast_path",
                    "phase_timings_ms": {"local_response": 0},
                },
            }

        if self.enhanced:
            pre_ctx = self.enhanced.pre_task_hook(message)
            if self._planning_requested(message) and pre_ctx.get("matched_sop"):
                sop = pre_ctx["matched_sop"]
                add_step("memory", "Matched SOP", f"{sop['name']} ({sop['success_rate']:.0%} success): {' -> '.join(sop['steps'])}")
            if self._planning_requested(message) and pre_ctx.get("crystallized_skill") and self.memory.retrieve("ct_image") is not None and self.memory.retrieve("dose_metrics") is None:
                sk = pre_ctx["crystallized_skill"]
                add_step("memory", "Crystallized Skill", f"{sk['name']} ({sk['success_rate']:.0%} confidence)")
            if pre_ctx.get("reflexion_warnings"):
                add_step("memory", "Experience Recall", pre_ctx["reflexion_warnings"][:300])

        if self.brain_available:
            add_step("thinking", "LLM Brain", "Using AI brain system with function calling...")
            try:
                _result = self._run_llm_function_calling(message, steps, step_id)
                # _run_llm_function_calling may return a tuple (response, llm_meta)
                # or a single string (from _execute_direct_tools path).
                if isinstance(_result, tuple) and len(_result) >= 2:
                    response, llm_meta = _result[0], _result[1]
                else:
                    response = _result
                    llm_meta = {"usage": {}, "latency_ms": 0, "llm_calls": 0}
            except Exception as e:
                import traceback as _tb
                logger.error(f"LLM function calling failed: {e}\n{_tb.format_exc()}")
                add_step("error", "LLM Error", str(e), status="error")
                response = f"Error: {e}"
                llm_meta = {"usage": {}, "latency_ms": 0, "llm_calls": 0}
        else:
            add_step("thinking", "Rule Matcher", "Brain unavailable — using rule-based parsing")
            response = self._rule_based_chat_with_steps(message, steps, step_id)
            llm_meta = {"usage": {}, "latency_ms": 0, "llm_calls": 0}

        self._record_experience(message, response, steps)

        if self.enhanced:
            tool_chain = [s.get("tool", "") for s in steps if s.get("type") == "tool"]
            tool_results = [(s.get("tool", ""), s.get("status") == "done", s.get("result", "")) for s in steps if s.get("type") == "tool"]
            self.enhanced.post_task_hook(
                user_input=message, tool_chain=tool_chain, tool_results=tool_results,
                outcome=response[:500], success="error" not in response.lower() and "fail" not in response.lower(),
            )
            enhanced_status = self.enhanced.get_agent_status()
            add_step("evolution", "Self-Evolution Status", json.dumps({
                "layered_memory": enhanced_status["layered_memory"],
                "reflexion": enhanced_status["reflexion"],
                "skill_crystallizer": {"total_skills": enhanced_status["skill_crystallizer"]["total_skills"], "verified": enhanced_status["skill_crystallizer"]["verified_skills"]},
            }, ensure_ascii=False))

        # WORKFLOW ENFORCER: If user requested planning but LLM didn't execute tools, force-execute
        is_planning_request = self._planning_requested(message)
        if is_planning_request:
            has_ctv = (
                self.memory.retrieve("ctv_array") is not None
                or any(s.get("tool") == "ctv_segmentation" and s.get("status") == "done" for s in steps if s.get("type") == "tool")
            )
            has_oar = (
                self.memory.retrieve("oar_array") is not None
                or any(s.get("tool") == "oar_segmentation" and s.get("status") == "done" for s in steps if s.get("type") == "tool")
            )
            has_planning = self._has_completed_planning_in_steps(steps)

            if not (has_ctv and has_oar and has_planning):
                logger.info(f"[WORKFLOW-ENFORCER] Planning requested but incomplete. CTV={has_ctv}, OAR={has_oar}, Planning={has_planning}")
                ct_path = self.memory.retrieve("ct_path")
                if ct_path:
                    detected_tumor_type = (
                        self.memory.retrieve("tumor_type_used")
                        or self._detect_tumor_type_from_message(message)
                    )
                    # Auto-execute missing steps
                    if not has_ctv:
                        if not detected_tumor_type:
                            logger.info("[WORKFLOW-ENFORCER] Tumor type unknown — skip auto-execution, LLM will ask naturally")
                        else:
                            logger.info("[WORKFLOW-ENFORCER] Auto-running CTV segmentation")
                            try:
                                if self.registry.get("ctv_segmentation"):
                                    ctv_result = self._execute_tool_with_memory(
                                        "ctv_segmentation",
                                        {
                                            "image_path": ct_path,
                                            "tumor_type": detected_tumor_type,
                                        },
                                    )
                                    if ctv_result and ctv_result.success:
                                        logger.info("[WORKFLOW-ENFORCER] ✓ CTV completed")
                                        add_step("tool", "Auto CTV Segmentation", "Auto-executed by workflow enforcer", tool="ctv_segmentation", status="done")
                                    else:
                                        err = (
                                            ctv_result.error or ctv_result.message
                                            if ctv_result is not None else "CTV segmentation failed"
                                        )
                                        logger.warning(f"[WORKFLOW-ENFORCER] CTV auto-execution did not run: {err}")
                                        add_step(
                                            "tool",
                                            "Auto CTV Segmentation",
                                            err,
                                            tool="ctv_segmentation",
                                            status="error",
                                        )
                            except Exception as e:
                                logger.error(f"[WORKFLOW-ENFORCER] CTV auto-execution failed: {e}")

                    # Re-check after CTV
                    has_ctv = (
                        self.memory.retrieve("ctv_array") is not None
                        or any(s.get("tool") == "ctv_segmentation" and s.get("status") == "done" for s in steps if s.get("type") == "tool")
                    )

                    if (
                        has_ctv and not has_oar
                        and self.memory.retrieve("oar_array") is not None
                        and bool(self.memory.retrieve("oar_is_full"))
                    ):
                        has_oar = True
                        logger.info(
                            "[WORKFLOW-ENFORCER] Using existing full OAR data "
                            f"(source={self.memory.retrieve('oar_source') or 'unknown'}, "
                            f"full={bool(self.memory.retrieve('oar_is_full'))}) for planning; "
                            "not auto-running full TotalSegmentator."
                        )

                    if has_ctv and not has_oar:
                        logger.info("[WORKFLOW-ENFORCER] Auto-running OAR segmentation")
                        try:
                            if self.registry.get("oar_segmentation"):
                                oar_result = self._execute_tool_with_memory(
                                    "oar_segmentation", {"image_path": ct_path}
                                )
                                if oar_result and oar_result.success:
                                    logger.info("[WORKFLOW-ENFORCER] ✓ OAR completed")
                                    add_step("tool", "Auto OAR Segmentation", "Auto-executed by workflow enforcer", tool="oar_segmentation", status="done")
                        except Exception as e:
                            logger.error(f"[WORKFLOW-ENFORCER] OAR auto-execution failed: {e}")

                    # Re-check after OAR
                    has_oar = (
                        self.memory.retrieve("oar_array") is not None
                        or any(s.get("tool") == "oar_segmentation" and s.get("status") == "done" for s in steps if s.get("type") == "tool")
                    )

                    if has_ctv and has_oar and not has_planning:
                        logger.info("[WORKFLOW-ENFORCER] Auto-running planning pipeline")
                        try:
                            if self.registry.get("planning_pipeline"):
                                planning_result = self._execute_tool_with_memory(
                                    "planning_pipeline",
                                    {"ct_image_path": ct_path, "mode": "rule_based", "step": "full"},
                                )
                                if planning_result and planning_result.success:
                                    logger.info("[WORKFLOW-ENFORCER] ✓ Planning completed")
                                    add_step("tool", "Auto Planning Pipeline", "Auto-executed by workflow enforcer", tool="planning_pipeline", status="done")
                                    # Generate proper planning report to REPLACE error response
                                    try:
                                        _report = self._build_planning_report(self.memory.user_lang, steps)
                                        if _report and len(_report) > len(response):
                                            response = _report
                                        else:
                                            response = "✅ 自动完成完整规划流程（CTV → OAR → Planning）"
                                    except Exception as _rep_e:
                                        logger.warning(f"Failed to build planning report: {_rep_e}")
                                        response = "✅ 自动完成完整规划流程（CTV → OAR → Planning）"
                        except Exception as e:
                            logger.error(f"[WORKFLOW-ENFORCER] Planning auto-execution failed: {e}")

        # Run completeness check if multi-agent is available
        if (
            self.multi_agent_wrapper
            and self.multi_agent_wrapper.enabled
            and local_policy.use_completeness
        ):
            try:
                import asyncio
                # REVIEW: previously called `asyncio.set_event_loop(_loop)`
                # and closed it in `finally` without restoring the prior
                # global loop. After every chat the global event loop was
                # a CLOSED loop, breaking any downstream code that later
                # calls `asyncio.get_event_loop()` (raises on closed loop).
                _prev_loop = None
                try:
                    _prev_loop = asyncio.get_event_loop_policy().get_event_loop()
                except Exception:
                    _prev_loop = None
                _loop = asyncio.new_event_loop()
                asyncio.set_event_loop(_loop)
                try:
                    _cc_result = _loop.run_until_complete(
                        self.multi_agent_wrapper.check_completeness_append(
                            message, response, steps, self.memory.user_lang
                        )
                    )
                    if _cc_result:
                        # REVIEW: previously appended checker result inline, which
                        # duplicated content when the main response was also shown.
                        # Checker status is visible in the progress panel; no need
                        # to embed it in the response text.
                        pass
                finally:
                    _loop.close()
                    try:
                        asyncio.set_event_loop(_prev_loop)
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"Completeness check failed: {e}")

        self._finish_turn(response)
        return {"response": response, "steps": steps, "llm_meta": llm_meta}

    def chat_with_stream(self, message: str):
        """Streaming version of chat_with_trace. Yields SSE events."""
        self._begin_turn(message)
        self.memory.add_message("user", message)
        self.memory.user_lang = "zh" if re.search(r'[一-鿿]', message) else "en"
        steps = []
        step_id = [0]
        response = ""  # Initialize response variable
        llm_meta = {"usage": {}, "latency_ms": 0, "llm_calls": 0}
        workflow_turn_token = self._current_turn_token()
        self._turn_started_at = time.perf_counter()
        self._turn_timings = {}

        def add_step(step_type, title, content, status="done", **kwargs):
            step_id[0] += 1
            step = {
                "id": step_id[0],
                "type": step_type,
                "title": title,
                "content": content,
                "status": status,
                **kwargs
            }
            steps.append(step)
            return step

        def yield_event(event_type, data):
            return f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"

        def workflow_cancelled() -> bool:
            """Check cancellation while the workflow enforcer waits on a tool."""
            return self._is_turn_cancelled(workflow_turn_token)

        def cancelled_workflow_events(step):
            """Finish SSE cleanly when a daemonized workflow tool is cancelled.

            Python cannot safely kill an in-flight GPU inference thread.  The
            old request therefore stops receiving events immediately and never
            schedules downstream OAR/planning work; the daemon may only finish
            its already-started operation in the background.
            """
            step["status"] = "error"
            step["content"] = "Stopped by user"
            step["result"] = "Cancelled before workflow completion"
            yield yield_event("step", step)
            message_text = (
                "已停止本次请求。已启动的底层推理可能在后台自然结束，但不会再触发后续规划步骤。"
                if self.memory.user_lang == "zh"
                else "This request was stopped. Any already-started inference may finish in the background, but no downstream planning steps will run."
            )
            yield yield_event("response", {"response": message_text, "steps": steps, "llm_meta": llm_meta})
            yield yield_event("done", {"cancelled": True, "context": {"ui_state": self.memory.get_ui_state()}})

        # Start
        # Include the detected language so the frontend can pick
        # language-aware labels for the todo list, status messages,
        # and other UI text. The detection uses memory/language.py
        # which counts character ranges (CJK vs Latin) and falls
        # back to the previous session's language for ambiguous
        # short messages. See memory/language.py for the full
        # detection rules and the rationale for top-level injection.
        try:
            from memory.language import detect as _lang_detect_start
            _lang_info_start = _lang_detect_start(message)
        except Exception:
            _lang_info_start = {"code": "en", "name": "English", "source": "default"}
        yield yield_event("start", {"message": message, "language": _lang_info_start})

        # User step
        add_step("user", "User Input", message)
        yield yield_event("step", steps[-1])

        local_policy = classify_local_turn(message)
        self._active_turn_policy = local_policy
        if local_policy.fast_response is not None:
            fast_step = add_step(
                "thinking", "Local Fast Path",
                "Answered locally; no model call or remote review required.",
            )
            yield yield_event("step", fast_step)
            response = local_policy.fast_response
            self._finish_turn(response)
            llm_meta.update({
                "route": "local_fast_path",
                "phase_timings_ms": {"local_response": 0},
            })
            yield yield_event("response", {"response": response, "llm_meta": llm_meta})
            yield yield_event("done", {"context": {"message_count": len(self.memory.conversation)}})
            return

        # Multi-agent routing (if available). The local policy has already
        # handled deterministic greetings and decides whether this expensive
        # route is needed for the current intent.
        _ma_routing = None
        _route_started = time.perf_counter()
        if (
            self.multi_agent_wrapper
            and self.multi_agent_wrapper.enabled
            and local_policy.use_router
        ):
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                try:
                    ma_result = loop.run_until_complete(
                        self.multi_agent_wrapper.process_request(message, self.memory.conversation_state)
                    )
                finally:
                    loop.close()
                _ma_routing = ma_result.get("routing")
                if _ma_routing:
                    # Store routing intent for context building
                    self.memory._last_routing_intent = _ma_routing.intent
                    step = add_step("thinking", "Multi-Agent Router",
                                  f"Intent: {_ma_routing.intent}, Complexity: {_ma_routing.complexity}, "
                                  f"Review: {'Required' if _ma_routing.requires_review else 'Optional'}")
                    yield yield_event("step", step)
            except Exception as e:
                logger.debug(f"Multi-agent routing failed: {e}")
        elif not local_policy.use_router:
            # Keep the trace explicit while avoiding a second remote model
            # call for low-risk turns.
            _ma_routing = SimpleNamespace(
                intent=local_policy.intent,
                complexity=local_policy.complexity,
                requires_review=local_policy.requires_review,
            )
            self.memory._last_routing_intent = local_policy.intent
            local_route_step = add_step(
                "thinking", "Local Intent",
                f"Intent: {local_policy.intent}, Complexity: {local_policy.complexity}, "
                f"Review: {'Required' if local_policy.requires_review else 'Optional'}",
            )
            yield yield_event("step", local_route_step)
        self._turn_timings["router_ms"] = round((time.perf_counter() - _route_started) * 1000, 1)

        # Direct tool execution for explicit tool requests
        _direct_tool_calls = self._detect_tool_request(message)
        if _direct_tool_calls:
            _lang = self.memory.user_lang
            logger.info(f"Direct tool execution (stream): {len(_direct_tool_calls)} tools")
            for tc in _direct_tool_calls:
                step = add_step("tool", f"Direct: {tc['tool']}", json.dumps(tc['params'], default=str)[:200],
                                status="pending", tool=tc['tool'], params=tc['params'])
                yield yield_event("step", step)
                try:
                    # Store ct_path for downstream tools
                    if tc['tool'] in ('ctv_segmentation', 'oar_segmentation') and 'image_path' in tc['params']:
                        self.memory.store("ct_path", tc['params']['image_path'])
                        # Also load and store CT image if not already in memory
                        if self.memory.retrieve("ct_image") is None:
                            try:
                                import SimpleITK as sitk
                                ct_img = sitk.ReadImage(tc['params']['image_path'])
                                self.memory.store("ct_image", ct_img)
                                # Keep raw frame for label metadata alignment
                                self.memory.retrieve("ct_image_raw") or self.memory.store("ct_image_raw", ct_img)
                            except Exception as _e:
                                logger.warning(f"Failed to pre-load CT image: {_e}")

                    if self.registry.get(tc['tool']):
                        result = self._execute_tool_with_memory(
                            tc['tool'], dict(tc['params'])
                        )
                        step["status"] = "done"
                        # Inject FactChecker feedback for search tools
                        _fmt = self._format_tool_result(tc['tool'], result, lang=_lang)
                        if tc['tool'] in ("web_search", "web_fetch", "web_access") and result.success:
                            _fmt = self._check_search_reliability(tc['tool'], _fmt)
                        step["result"] = _fmt
                        step["metadata"] = result.metadata if result.success else {}
                        yield yield_event("step", step)
                        if result.success:
                            # After CTV/OAR seg, ensure ct_image is stored for downstream tools
                            if tc['tool'] == 'ctv_segmentation' and 'image_path' in tc['params']:
                                if self.memory.retrieve("ct_image") is None:
                                    try:
                                        import SimpleITK as sitk
                                        ct_img = sitk.ReadImage(tc['params']['image_path'])
                                        self.memory.store("ct_image", ct_img)
                                        # Also keep raw frame for label metadata alignment
                                        self.memory.retrieve("ct_image_raw") or self.memory.store("ct_image_raw", ct_img)
                                    except Exception as e:
                                        logger.warning(
                                            f"Failed to auto-load CT from {tc['params']['image_path']}: {e}. "
                                            f"Downstream planning may fail with 'No CT image available'."
                                        )
                        # Store in conversation for context persistence
                        self.memory.add_message("assistant", f"[Called {tc['tool']}]")
                        result_summary = result.message[:500] if result.success else f"Error: {result.error}"
                        self.memory.add_message("user", f"[Tool result: {result_summary}]")
                except Exception as e:
                    step["status"] = "error"
                    step["result"] = str(e)
                    yield yield_event("step", step)
                    logger.error(f"Direct tool failed: {tc['tool']}: {e}")
                    self.memory.add_message("assistant", f"[Called {tc['tool']}]")
                    self.memory.add_message("user", f"[Tool result: Error: {str(e)[:200]}]")

            raw_response = self._build_direct_response(steps, _lang)
            user_msg = message
            # BUG FIX 2026-06-16 (LLM response still brief): the user
            # complained that the LLM synthesis after planning was
            # just a 5-row table — no OAR analysis, no flagged
            # issues, no clinical context. Even with the 10-section
            # template in the prompt, the LLM keeps producing brief
            # output (probably max_tokens truncation or the LLM
            # ignoring long instructions). For PLANNING runs, we
            # now BYPASS LLM synthesis and generate the full
            # structured response directly from the actual stored
            # metrics. This guarantees the user always sees the
            # complete clinical report.
            has_planning = self._has_completed_planning_in_steps(steps)
            if has_planning:
                response = self._build_planning_report(_lang, steps)
            else:
                query_type = self._classify_query_type(user_msg)
                response = self._synthesize_with_llm(raw_response, steps, _lang, user_msg, query_type)
            self.memory.add_message("assistant", response)

            # Quality review DISABLED (2026-06-22): the review triggered
            # a mysterious "Review Feedback" retry that generated a brief
            # English stub after the comprehensive Chinese report.
            # if self.multi_agent_wrapper and self.multi_agent_wrapper.enabled:
            #     ...

            # BUG FIX 2026-06-17: after quality review retry, the
            # LLM might produce a brief response that overwrites the
            # comprehensive planning report. Always regenerate from
            # stored metrics when planning tools were executed.
            if has_planning:
                response = self._build_planning_report(_lang, steps)
                logger.info(f"[streaming] Regenerated planning report after review: {len(response)} chars")

            # Direct-tool requests return from this branch, so run the
            # same user-visible completeness check here before the final
            # response event. This keeps the UI order consistent:
            # tools -> requirement coverage -> final answer.
            if (
                self.multi_agent_wrapper
                and self.multi_agent_wrapper.enabled
                and local_policy.use_completeness
            ):
                step_id[0] += 1
                _direct_cc_step = {
                    "id": step_id[0],
                    "type": "tool",
                    "title": "Completeness Check",
                    "tool": "completeness_checker",
                    "content": "Checking requirement coverage...",
                    "status": "pending",
                }
                steps.append(_direct_cc_step)
                yield yield_event("step", _direct_cc_step)
                try:
                    import asyncio as _asyncio_direct_review
                    # REVIEW: restore previous global event loop in finally to
                    # avoid leaving a closed loop as the global (breaks any
                    # downstream code calling `asyncio.get_event_loop()`).
                    _direct_prev_loop = None
                    try:
                        _direct_prev_loop = _asyncio_direct_review.get_event_loop_policy().get_event_loop()
                    except Exception:
                        _direct_prev_loop = None
                    _direct_loop = _asyncio_direct_review.new_event_loop()
                    try:
                        _asyncio_direct_review.set_event_loop(_direct_loop)
                        _cc_result = _direct_loop.run_until_complete(
                            self.multi_agent_wrapper.check_completeness_append(
                                message, response, steps, _lang
                            )
                        )
                    finally:
                        _direct_loop.close()
                        try:
                            _asyncio_direct_review.set_event_loop(_direct_prev_loop)
                        except Exception:
                            pass
                    if isinstance(_cc_result, str) and _cc_result:
                        pass  # Checker status shown in progress panel only
                    _direct_cc_step["status"] = "done"
                    _direct_cc_step["content"] = "Checked" if not _cc_result else "Issues found"
                    yield yield_event("step", _direct_cc_step)
                except Exception as e:
                    logger.debug(f"Direct completeness check skipped: {e}")
                    _direct_cc_step["status"] = "done"
                    _direct_cc_step["content"] = "Coverage check unavailable; continuing."
                    yield yield_event("step", _direct_cc_step)

            self._finish_turn(response)
            llm_meta["phase_timings_ms"] = dict(getattr(self, "_turn_timings", {}) or {})
            llm_meta["route"] = "direct_tool"
            yield yield_event("response", {"response": response, "llm_meta": llm_meta})
            yield yield_event("done", {"context": {"message_count": len(self.memory.conversation)}})
            return

        # Enhanced context
        if self.enhanced:
            pre_ctx = self.enhanced.pre_task_hook(message)
            if self._planning_requested(message) and pre_ctx.get("matched_sop"):
                sop = pre_ctx["matched_sop"]
                step = add_step("memory", "Matched SOP", f"{sop['name']} ({sop['success_rate']:.0%} success): {' -> '.join(sop['steps'])}")
                yield yield_event("step", step)
            if self._planning_requested(message) and pre_ctx.get("crystallized_skill") and self.memory.retrieve("ct_image") is not None:
                sk = pre_ctx["crystallized_skill"]
                step = add_step("memory", "Crystallized Skill", f"{sk['name']} ({sk['success_rate']:.0%} confidence)")
                yield yield_event("step", step)
            if pre_ctx.get("reflexion_warnings"):
                step = add_step("memory", "Experience Recall", pre_ctx["reflexion_warnings"][:300])
                yield yield_event("step", step)

        if self.brain_available:
            try:
                for ev in self._run_llm_function_calling_stream(message, steps, step_id, yield_event):
                    if isinstance(ev, dict) and ev.get("type") == "_result":
                        response = ev.get("response", "")
                        llm_meta = ev.get("llm_meta", {})
                    else:
                        yield ev
            except Exception as e:
                import traceback as _tb
                logger.error(f"LLM function calling failed: {e}\n{_tb.format_exc()}")
                add_step("error", "LLM Error", str(e), status="error")
                response = f"Error: {e}"
                llm_meta = {"usage": {}, "latency_ms": 0, "llm_calls": 0}
                yield yield_event("error", {"message": str(e)})
        else:
            response = self._rule_based_chat_with_steps_stream(message, steps, step_id, yield_event)
            llm_meta = {"usage": {}, "latency_ms": 0, "llm_calls": 0}

        # A low-level status question must still receive a concrete answer if
        # the model only emitted a tool acknowledgement or the completeness
        # checker consumed an empty response. The UI telemetry is the source
        # of truth; this fallback deliberately states uncertainty instead of
        # claiming a specific WebGL failure without evidence.
        _response_text = str(response or "").strip()
        if self._is_3d_status_request(message) and (
            not _response_text
            or _response_text.lower() in {"no response generated.", "tools executed. check the execution trace above for results."}
            or _response_text.startswith("需求覆盖检查")
        ):
            response = self._build_3d_status_response(self.memory.user_lang)

        self._record_experience(message, response, steps)

        # Quality review DISABLED (2026-06-22): the review triggered a
        # mysterious "Review Feedback" retry that generated a brief
        # English stub after the comprehensive Chinese report. The retry
        # source could not be found in the codebase. Disabling the
        # review entirely to prevent the confusing UX.
        # if self.multi_agent_wrapper and self.multi_agent_wrapper.enabled:
        #     ...

        # SAFETY NET: after quality review retry, ensure the response
        # is the full planning report (not a brief LLM acknowledgment).
        _has_planning = self._has_completed_planning_in_steps(steps)
        if _has_planning and response:
            # Check if response is suspiciously short (likely a retry
            # artifact that didn't regenerate the full report)
            logger.info(f"[chat_with_stream] Safety net check: has_planning={_has_planning}, response_len={len(response)}")
            if len(response) < 500:
                try:
                    _full_report = self._build_planning_report(self.memory.user_lang, steps)
                    logger.info(f"[chat_with_stream] Safety net: regenerated report len={len(_full_report) if _full_report else 0}")
                    if _full_report and len(_full_report) > len(response):
                        logger.info(f"[chat_with_stream] Safety net: replaced {len(response)}-char response with {len(_full_report)}-char planning report")
                        response = _full_report
                except Exception as e:
                    logger.warning(f"[chat_with_stream] Safety net report generation failed: {e}")

        # ── Review phase (append-only, NO retries) ──────────────────
        # Runs PlanReviewer + CompletenessChecker.
        # FactChecker runs DURING tool execution (injected into search
        # results), not here. Results are appended to the response as
        # supplementary sections. Never triggers re-execution.
        #
        # SMART REVIEW: Only run review phase when needed:
        # - If RouterAgent says review is required (_ma_routing.requires_review)
        # - If planning tools were used (_has_plan) → always review plan quality
        # - If complexity is "high" or "medium" → review for quality
        # - Skip for "low" complexity or simple Q&A → save latency + tokens
        review_sections = []
        _needs_review = False
        _review_reason = ""
        _review_started = time.perf_counter()

        # Smart review decision based on tool usage and response complexity
        _high_value_tools = {
            "planning_pipeline", "seed_planning", "dose_evaluation", "dose_calc",
            "ctv_segmentation", "oar_segmentation", "trajectory_planning",
            "safety_validator", "clinical_kb"
        }
        _tools_called = {s.get("tool") for s in steps if s.get("type") == "tool"}
        _high_value_called = _tools_called & _high_value_tools
        _knowledge_tools = {"web_search", "web_fetch", "web_access"}
        _knowledge_called = _tools_called & _knowledge_tools
        _has_plan = self._has_completed_planning_in_steps(steps)
        _router_requires_review = bool(
            _ma_routing and getattr(_ma_routing, "requires_review", False)
        )
        _response_len = len(response)
        _visual_analysis_request = bool(re.search(
            r"\b(?:analy[sz]e|describe|interpret|assess|evaluate|what\s+do\s+you\s+see|explain|findings?)\b"
            r"|(?:介绍|分析|解读|说明|描述|看到了什么|看到什么|评价|评估|判断|结果如何|有什么问题)",
            str(message or ""),
            re.IGNORECASE,
        ))

        if _router_requires_review:
            _needs_review = True
            _review_reason = "router_requires_review"
        elif _knowledge_called:
            _needs_review = True
            _review_reason = f"knowledge_tools: {_knowledge_called}"
        elif _high_value_called:
            _needs_review = True
            _review_reason = f"high_value_tools: {_high_value_called}"
        elif len(_tools_called) >= 3:
            _needs_review = True
            _review_reason = f"many_tools: {len(_tools_called)}"
        elif _response_len > 500 and local_policy.use_completeness:
            _needs_review = True
            _review_reason = f"long_response: {_response_len} chars"
        elif ("ui_screenshot" in _tools_called and _visual_analysis_request) or "[Screenshot captured:" in message:
            # A screenshot used as evidence needs a final completeness pass,
            # even when the router labels the request as low complexity.
            _needs_review = True
            _review_reason = "visual_screenshot_analysis"
        else:
            _needs_review = False
            _review_reason = f"skip: tools={len(_tools_called)}, response={_response_len} chars"

        if self.multi_agent_wrapper and self.multi_agent_wrapper.enabled and _needs_review:
            logger.info(f"[Review phase] Running review: {_review_reason}")
            _lang = self.memory.user_lang
            try:
                import asyncio
                # REVIEW: restore previous global event loop in finally to
                # avoid leaving a closed loop as the global (breaks any
                # downstream code calling `asyncio.get_event_loop()`).
                _prev_loop = None
                try:
                    _prev_loop = asyncio.get_event_loop_policy().get_event_loop()
                except Exception:
                    _prev_loop = None
                _loop = asyncio.new_event_loop()
                asyncio.set_event_loop(_loop)

                # Inject global context so sub-agents have full
                # situational awareness. Only include decision-relevant
                # info — skip large dicts (organ_names) and paths.
                _oar_names = self.memory.retrieve("organ_names", {}) or {}
                _oar_count = len(_oar_names)
                _organ_counts = self.memory.retrieve("organ_counts", {}) or {}

                def _organ_voxel_count(label, name):
                    for key in (label, str(label), name):
                        if key in _organ_counts:
                            return _organ_counts[key]
                    return 0

                _top_oars = [
                    name for label, name in sorted(
                        _oar_names.items(),
                        key=lambda item: _organ_voxel_count(item[0], item[1]),
                        reverse=True,
                    )[:10]
                ] if _oar_names else []

                self.multi_agent_wrapper.update_global_context({
                    "patient_info": {
                        "tumor_type": self.memory.retrieve("tumor_type_used", ""),
                    },
                    "segmentation": {
                        "ctv_voxels": self.memory.retrieve("ctv_voxels", 0),
                        "ctv_volume_mm3": self.memory.retrieve("ctv_volume_mm3", 0),
                        "oar_count": _oar_count,
                        "top_oars": _top_oars,
                    },
                    "planning": {
                        "total_seeds": self.memory.retrieve("total_seeds", 0),
                        "num_trajectories": self.memory.retrieve("num_trajectories", 0),
                    },
                    "conversation_state": dict(self.memory.conversation_state),
                    "user_message": message,
                    "tool_history": [
                        s.get("tool") for s in steps if s.get("type") == "tool"
                    ],
                    "lang": _lang,
                })

                # 1. Emit step events for todo list
                _review_step = None
                _cc_step = None

                if _has_plan:
                    step_id[0] += 1
                    _review_step = {
                        "id": step_id[0], "type": "tool",
                        "title": "Quality Check", "tool": "plan_reviewer",
                        "content": "Reviewing plan metrics...",
                        "status": "pending",
                    }
                    steps.append(_review_step)
                    yield yield_event("step", _review_step)

                step_id[0] += 1
                _cc_step = {
                    "id": step_id[0], "type": "tool",
                    "title": "Completeness Check", "tool": "completeness_checker",
                    "content": "Checking requirement coverage...",
                    "status": "pending",
                }
                steps.append(_cc_step)
                yield yield_event("step", _cc_step)

                # 2. Run reviews IN PARALLEL (asyncio.gather)
                async def _run_plan_review():
                    if not _has_plan:
                        return ""
                    _metrics = self.memory.retrieve("metrics", {}) or {}
                    _config = self.memory.retrieve("plan_config", {}) or {}
                    _plan_info = {"total_seeds": self.memory.retrieve("total_seeds", 0)}
                    return await self.multi_agent_wrapper.review_plan_append(
                        _metrics, _plan_info, _config, _lang
                    )

                async def _run_completeness():
                    return await self.multi_agent_wrapper.check_completeness_append(
                        message, response, steps, _lang
                    )

                try:
                    _results = _loop.run_until_complete(
                        asyncio.gather(
                            _run_plan_review(),
                            _run_completeness(),
                            return_exceptions=True,
                        )
                    )
                    _plan_result, _cc_result = _results

                    if isinstance(_plan_result, Exception):
                        logger.error(f"[Review] Plan review failed: {_plan_result}")
                        _plan_result = ""
                    if isinstance(_cc_result, Exception):
                        logger.error(f"[Review] Completeness check failed: {_cc_result}")
                        _cc_result = ""

                    if isinstance(_plan_result, str) and _plan_result:
                        review_sections.append(_plan_result)
                    if _review_step:
                        _review_step["status"] = "done"
                        _review_step["content"] = "Reviewed" if _plan_result else "No issues"
                        yield yield_event("step", _review_step)

                    if isinstance(_cc_result, str) and _cc_result:
                        review_sections.append(_cc_result)
                    if _cc_step:
                        _cc_step["status"] = "done"
                        _cc_step["content"] = "Checked" if not (isinstance(_cc_result, str) and _cc_result) else "Issues found"
                        yield yield_event("step", _cc_step)

                except Exception as e:
                    logger.error(f"[Review] Review phase failed: {e}", exc_info=True)
                    if _review_step:
                        _review_step["status"] = "error"
                        _review_step["content"] = f"Error: {str(e)[:50]}"
                    if _cc_step:
                        _cc_step["status"] = "error"
                        _cc_step["content"] = f"Error: {str(e)[:50]}"

            except Exception as e:
                logger.debug(f"Review phase skipped: {e}")
            finally:
                try:
                    _loop.close()
                except Exception as exc:
                    logger.debug("Review event loop close failed: %s", exc)
                try:
                    asyncio.set_event_loop(_prev_loop)
                except Exception as exc:
                    logger.debug("Review event loop restore failed: %s", exc)
        elif _needs_review:
            logger.info(f"[Review phase] Running fallback completeness check: {_review_reason}")
            try:
                step_id[0] += 1
                _cc_step = {
                    "id": step_id[0],
                    "type": "tool",
                    "title": "Completeness Check",
                    "tool": "completeness_checker",
                    "content": "Checking requirement coverage...",
                    "status": "pending",
                }
                steps.append(_cc_step)
                yield yield_event("step", _cc_step)

                _checks = []
                _has_plan_now = self._has_completed_planning_in_steps(steps)
                _planning_requested_now = self._planning_requested(message)
                if _planning_requested_now and not _has_plan_now:
                    _checks.append("planning request detected but planning_pipeline has not completed")
                if _has_plan_now and not (self.memory.retrieve("dose_metrics") or self.memory.retrieve("metrics")):
                    _checks.append("planning completed but dose metrics were not found in memory")
                if response and len(response) < 80:
                    _checks.append("final response is unusually short")

                _cc_step["status"] = "done"
                if _checks:
                    _cc_step["content"] = "Checked with warnings: " + "; ".join(_checks)
                else:
                    _cc_step["content"] = "Checked final response coverage."
                yield yield_event("step", _cc_step)
            except Exception as e:
                logger.debug(f"Fallback completeness check skipped: {e}")

        self._turn_timings["checker_ms"] = round(
            (time.perf_counter() - _review_started) * 1000, 1
        ) if _needs_review else 0

        # WORKFLOW ENFORCER: If user requested planning but LLM didn't execute tools, force-execute
        is_planning_request = self._planning_requested(message)
        _workflow_enforced = False
        if is_planning_request:
            has_ctv = (
                self.memory.retrieve("ctv_array") is not None
                or any(s.get("tool") == "ctv_segmentation" and s.get("status") == "done" for s in steps if s.get("type") == "tool")
            )
            has_oar = (
                self.memory.retrieve("oar_array") is not None
                or any(s.get("tool") == "oar_segmentation" and s.get("status") == "done" for s in steps if s.get("type") == "tool")
            )
            has_planning = self._has_completed_planning_in_steps(steps)

            if not (has_ctv and has_oar and has_planning):
                logger.info(f"[WORKFLOW-ENFORCER-STREAM] Planning requested but incomplete. CTV={has_ctv}, OAR={has_oar}, Planning={has_planning}")
                ct_path = self.memory.retrieve("ct_path")
                if ct_path:
                    detected_tumor_type = (
                        self.memory.retrieve("tumor_type_used")
                        or self._detect_tumor_type_from_message(message)
                    )
                    # Auto-execute missing steps with proper SSE events
                    if not has_ctv:
                        if not detected_tumor_type:
                            logger.info("[WORKFLOW-ENFORCER-STREAM] Tumor type unknown — skip auto-execution, LLM will ask naturally")
                        else:
                            logger.info("[WORKFLOW-ENFORCER-STREAM] Auto-running CTV segmentation")
                            _workflow_enforced = True
                            ctv_step = add_step("tool", "Auto CTV Segmentation", "Auto-executed by workflow enforcer", status="pending", tool="ctv_segmentation")
                            yield yield_event("step", ctv_step)
                            try:
                                if self.registry.get("ctv_segmentation"):
                                    import threading as _thr_ctv
                                    _ctv_rbox = [None]
                                    _ctv_ebox = [None]
                                    def _run_ctv():
                                        try:
                                            _ctv_rbox[0] = self._execute_tool_with_memory(
                                                "ctv_segmentation",
                                                {
                                                    "image_path": ct_path,
                                                    "tumor_type": detected_tumor_type,
                                                },
                                            )
                                        except Exception as _e:
                                            _ctv_ebox[0] = _e
                                    _ctv_th = _thr_ctv.Thread(target=_run_ctv, daemon=True)
                                    _ctv_th.start()
                                    _ctv_hb = 0
                                    while _ctv_th.is_alive():
                                        _ctv_th.join(timeout=1)
                                        if workflow_cancelled():
                                            yield from cancelled_workflow_events(ctv_step)
                                            return
                                        if _ctv_th.is_alive():
                                            _ctv_hb += 1
                                            ctv_step["content"] = f"CTV segmentation running... ({_ctv_hb}s)"
                                            yield yield_event("step", ctv_step)
                                    if _ctv_ebox[0] is not None:
                                        raise _ctv_ebox[0]
                                    ctv_result = _ctv_rbox[0]
                                if ctv_result and ctv_result.success:
                                    logger.info("[WORKFLOW-ENFORCER-STREAM] ✓ CTV completed")
                                    ctv_step["status"] = "done"
                                    ctv_step["result"] = str(ctv_result.message)[:200] if ctv_result.message else "Completed"
                                    yield yield_event("step", ctv_step)
                                else:
                                    err = (
                                        ctv_result.error or ctv_result.message
                                        if ctv_result is not None else "CTV segmentation failed"
                                    )
                                    if ctv_result is not None and ctv_result.metadata:
                                        question = ctv_result.metadata.get("clarification_question")
                                        if question:
                                            err = f"{err} {question}"
                                    logger.warning(f"[WORKFLOW-ENFORCER-STREAM] CTV auto-execution did not run: {err}")
                                    ctv_step["status"] = "error"
                                    ctv_step["result"] = str(err)[:200]
                                    yield yield_event("step", ctv_step)
                            except Exception as e:
                                logger.error(f"[WORKFLOW-ENFORCER-STREAM] CTV auto-execution failed: {e}")
                                ctv_step["status"] = "error"
                                ctv_step["result"] = str(e)[:200]
                                yield yield_event("step", ctv_step)

                    # Re-check after CTV
                    has_ctv = (
                        self.memory.retrieve("ctv_array") is not None
                        or any(s.get("tool") == "ctv_segmentation" and s.get("status") == "done" for s in steps if s.get("type") == "tool")
                    )

                    if (
                        has_ctv and not has_oar
                        and self.memory.retrieve("oar_array") is not None
                        and bool(self.memory.retrieve("oar_is_full"))
                    ):
                        has_oar = True
                        logger.info(
                            "[WORKFLOW-ENFORCER-STREAM] Using existing full OAR data "
                            f"(source={self.memory.retrieve('oar_source') or 'unknown'}, "
                            f"full={bool(self.memory.retrieve('oar_is_full'))}) for planning; "
                            "not auto-running full TotalSegmentator."
                        )

                    if has_ctv and not has_oar:
                        logger.info("[WORKFLOW-ENFORCER-STREAM] Auto-running OAR segmentation")
                        _workflow_enforced = True
                        oar_step = add_step("tool", "Auto OAR Segmentation", "Auto-executed by workflow enforcer", status="pending", tool="oar_segmentation")
                        yield yield_event("step", oar_step)
                        try:
                            if self.registry.get("oar_segmentation"):
                                import threading as _thr_o2
                                _oar2_rbox = [None]
                                _oar2_ebox = [None]
                                def _run_oar2():
                                    try:
                                        _oar2_rbox[0] = self._execute_tool_with_memory(
                                            "oar_segmentation", {"image_path": ct_path}
                                        )
                                    except Exception as _e:
                                        _oar2_ebox[0] = _e
                                _oar2_th = _thr_o2.Thread(target=_run_oar2, daemon=True)
                                _oar2_th.start()
                                _oar_hb = 0
                                while _oar2_th.is_alive():
                                    _oar2_th.join(timeout=1)
                                    if workflow_cancelled():
                                        yield from cancelled_workflow_events(oar_step)
                                        return
                                    if _oar2_th.is_alive():
                                        _oar_hb += 1
                                        oar_step["content"] = f"OAR segmentation running... ({_oar_hb}s)"
                                        yield yield_event("step", oar_step)
                                if _oar2_ebox[0] is not None:
                                    raise _oar2_ebox[0]
                                oar_result = _oar2_rbox[0]
                                if oar_result and oar_result.success:
                                    logger.info("[WORKFLOW-ENFORCER-STREAM] ✓ OAR completed")
                                    oar_step["status"] = "done"
                                    oar_step["result"] = str(oar_result.message)[:200] if oar_result.message else "Completed"
                                    yield yield_event("step", oar_step)
                        except Exception as e:
                            logger.error(f"[WORKFLOW-ENFORCER-STREAM] OAR auto-execution failed: {e}")
                            oar_step["status"] = "error"
                            oar_step["result"] = str(e)[:200]
                            yield yield_event("step", oar_step)

                    # Re-check after OAR
                    has_oar = (
                        self.memory.retrieve("oar_array") is not None
                        or any(s.get("tool") == "oar_segmentation" and s.get("status") == "done" for s in steps if s.get("type") == "tool")
                    )

                    if has_ctv and has_oar and not has_planning:
                        logger.info("[WORKFLOW-ENFORCER-STREAM] Auto-running planning pipeline")
                        _workflow_enforced = True
                        planning_step = add_step("tool", "Auto Planning Pipeline", "Auto-executed by workflow enforcer", status="pending", tool="planning_pipeline")
                        yield yield_event("step", planning_step)
                        try:
                            if self.registry.get("planning_pipeline"):
                                import threading as _thr_p
                                _plan_rbox = [None]
                                _plan_ebox = [None]
                                def _run_plan():
                                    try:
                                        _plan_rbox[0] = self._execute_tool_with_memory(
                                            "planning_pipeline",
                                            {"ct_image_path": ct_path, "mode": "rule_based", "step": "full"},
                                        )
                                    except Exception as _e:
                                        _plan_ebox[0] = _e
                                _plan_th = _thr_p.Thread(target=_run_plan, daemon=True)
                                _plan_th.start()
                                _plan_hb = 0
                                while _plan_th.is_alive():
                                    _plan_th.join(timeout=1)
                                    if workflow_cancelled():
                                        yield from cancelled_workflow_events(planning_step)
                                        return
                                    if _plan_th.is_alive():
                                        _plan_hb += 1
                                        planning_step["content"] = f"Planning pipeline running... ({_plan_hb}s)"
                                        yield yield_event("step", planning_step)
                                if _plan_ebox[0] is not None:
                                    raise _plan_ebox[0]
                                planning_result = _plan_rbox[0]
                                if planning_result and planning_result.success:
                                    logger.info("[WORKFLOW-ENFORCER-STREAM] ✓ Planning completed")
                                    planning_step["status"] = "done"
                                    planning_step["result"] = str(planning_result.message)[:200] if planning_result.message else "Completed"
                                    yield yield_event("step", planning_step)
                                    # Generate proper planning report to REPLACE error response
                                    try:
                                        _report = self._build_planning_report(self.memory.user_lang, steps)
                                        if _report and len(_report) > len(response):
                                            response = _report
                                        else:
                                            response = "✅ 自动完成完整规划流程（CTV → OAR → Planning）"
                                    except Exception as _rep_e:
                                        logger.warning(f"Failed to build planning report: {_rep_e}")
                                        response = "✅ 自动完成完整规划流程（CTV → OAR → Planning）"
                        except Exception as e:
                            logger.error(f"[WORKFLOW-ENFORCER-STREAM] Planning auto-execution failed: {e}")
                            planning_step["status"] = "error"
                            planning_step["result"] = str(e)[:200]
                            yield yield_event("step", planning_step)

        if _workflow_enforced and self.multi_agent_wrapper and self.multi_agent_wrapper.enabled:
            _post_loop = None
            try:
                import asyncio as _asyncio_post_enforcer
                # REVIEW: restore previous global event loop in finally to
                # avoid leaving a closed loop as the global (breaks any
                # downstream code calling `asyncio.get_event_loop()`).
                _post_prev_loop = None
                try:
                    _post_prev_loop = _asyncio_post_enforcer.get_event_loop_policy().get_event_loop()
                except Exception:
                    _post_prev_loop = None
                _post_loop = _asyncio_post_enforcer.new_event_loop()
                _asyncio_post_enforcer.set_event_loop(_post_loop)
                _post_review_step = None
                _post_cc_step = None
                if self._has_completed_planning_in_steps(steps):
                    step_id[0] += 1
                    _post_review_step = {
                        "id": step_id[0],
                        "type": "tool",
                        "title": "Quality Check",
                        "tool": "plan_reviewer",
                        "content": "Reviewing enforced planning result...",
                        "status": "pending",
                    }
                    steps.append(_post_review_step)
                    yield yield_event("step", _post_review_step)

                step_id[0] += 1
                _post_cc_step = {
                    "id": step_id[0],
                    "type": "tool",
                    "title": "Completeness Check",
                    "tool": "completeness_checker",
                    "content": "Checking final response after workflow enforcement...",
                    "status": "pending",
                }
                steps.append(_post_cc_step)
                yield yield_event("step", _post_cc_step)

                async def _run_post_plan_review():
                    if _post_review_step is None:
                        return ""
                    _metrics = self.memory.retrieve("metrics", {}) or {}
                    _config = self.memory.retrieve("plan_config", {}) or {}
                    _plan_info = {"total_seeds": self.memory.retrieve("total_seeds", 0)}
                    return await self.multi_agent_wrapper.review_plan_append(
                        _metrics, _plan_info, _config, self.memory.user_lang
                    )

                async def _run_post_completeness():
                    return await self.multi_agent_wrapper.check_completeness_append(
                        message, response, steps, self.memory.user_lang
                    )

                _post_plan_result, _post_cc_result = _post_loop.run_until_complete(
                    _asyncio_post_enforcer.gather(
                        _run_post_plan_review(),
                        _run_post_completeness(),
                        return_exceptions=True,
                    )
                )
                if isinstance(_post_plan_result, Exception):
                    logger.error(f"[Post-enforcer review] Plan review failed: {_post_plan_result}")
                    _post_plan_result = ""
                if isinstance(_post_cc_result, Exception):
                    logger.error(f"[Post-enforcer review] Completeness check failed: {_post_cc_result}")
                    _post_cc_result = ""
                if isinstance(_post_plan_result, str) and _post_plan_result:
                    review_sections.append(_post_plan_result)
                if isinstance(_post_cc_result, str) and _post_cc_result:
                    review_sections.append(_post_cc_result)
                if _post_review_step:
                    _post_review_step["status"] = "done"
                    _post_review_step["content"] = "Reviewed" if _post_plan_result else "No issues"
                    yield yield_event("step", _post_review_step)
                if _post_cc_step:
                    _post_cc_step["status"] = "done"
                    _post_cc_step["content"] = "Checked" if not _post_cc_result else "Issues found"
                    yield yield_event("step", _post_cc_step)
            except Exception as e:
                logger.debug(f"Post-enforcer review skipped: {e}")
            finally:
                if _post_loop is not None:
                    try:
                        _post_loop.close()
                    except Exception as exc:
                        logger.debug("Post-enforcer review event loop close failed: %s", exc)
                try:
                    _asyncio_post_enforcer.set_event_loop(_post_prev_loop)
                except Exception as exc:
                    logger.debug("Post-enforcer review event loop restore failed: %s", exc)

        # Append review sections to response after any workflow enforcement so
        # the final message reflects the actual tool chain that ran.
        if review_sections:
            response += "\n\n---\n" + "\n\n".join(review_sections)

        # Final response
        self._finish_turn(response)
        llm_meta.setdefault("phase_timings_ms", {}).update(self._turn_timings)
        llm_meta["phase_timings_ms"]["sse_push_ms"] = round(
            (time.perf_counter() - getattr(self, "_turn_started_at", time.perf_counter())) * 1000,
            1,
        )
        yield yield_event("response", {"response": response, "steps": steps, "llm_meta": llm_meta})
        yield yield_event("done", {
            "context": {
                "summary": self.memory.context_summary or None,
                "compaction_count": self.memory.compaction_count,
                "message_count": len(self.memory.conversation),
                "ui_state": self.memory.get_ui_state(),
            }
        })

    def _rule_based_chat_with_steps_stream(self, message: str, steps: List[Dict], step_id: List[int], yield_event) -> str:
        """Streaming version of rule-based chat that yields steps as they happen."""
        msg_lower = message.lower()

        def yield_step(step):
            steps.append(step)
            yield_event("step", step)

        if "分割" in msg_lower or "segment" in msg_lower:
            target = "CTV"
            if "oar" in msg_lower or "organ" in msg_lower or "器官" in msg_lower:
                target = "OAR"

            step_id[0] += 1
            tool_step = {
                "id": step_id[0], "type": "tool", "title": f"Segmentation: {target}",
                "content": f"Running {target} segmentation...", "status": "pending",
                "tool": f"{target.lower()}_segmentation", "params": {},
            }
            yield_step(tool_step)

            result = self._handle_ctv_segmentation_request(message) if target == "CTV" else self._handle_oar_segmentation_request(message)

            tool_step["status"] = "done"
            tool_step["result"] = result[:200]
            yield_step(tool_step)

            step_id[0] += 1
            result_step = {"id": step_id[0], "type": "result", "title": f"{target} Result", "content": result, "status": "done"}
            yield_step(result_step)

            return result

        elif self._planning_requested(message):
            mode = "rl" if "rl" in msg_lower or "强化" in msg_lower else "rule_based"

            step_id[0] += 1
            tool_step = {
                "id": step_id[0], "type": "tool", "title": "Seed Planning",
                "content": f"Generating seed plan ({mode} mode)...", "status": "pending",
                "tool": "seed_planning", "params": {"mode": mode},
            }
            yield_step(tool_step)

            result = self._handle_planning_request(message)

            tool_step["status"] = "done"
            tool_step["result"] = result[:200]
            yield_step(tool_step)

            step_id[0] += 1
            result_step = {"id": step_id[0], "type": "result", "title": "Planning Result", "content": result, "status": "done"}
            yield_step(result_step)

            return result

        elif "评估" in msg_lower or "eval" in msg_lower or "剂量" in msg_lower:
            step_id[0] += 1
            tool_step = {
                "id": step_id[0], "type": "tool", "title": "Dose Evaluation",
                "content": "Evaluating dose distribution...", "status": "pending",
                "tool": "dose_evaluation", "params": {},
            }
            yield_step(tool_step)

            result = self._handle_evaluation_request(message)

            tool_step["status"] = "done"
            tool_step["result"] = result[:200]
            yield_step(tool_step)

            step_id[0] += 1
            result_step = {"id": step_id[0], "type": "result", "title": "Evaluation Result", "content": result, "status": "done"}
            yield_step(result_step)

            return result

        elif "优化" in msg_lower or "optim" in msg_lower or "调整" in msg_lower:
            result = self._handle_optimization_request(message)
            return result

        elif "进化" in msg_lower or "evolve" in msg_lower or "学习" in msg_lower or "总结经验" in msg_lower:
            result = self._handle_self_evolution()
            return result

        elif "写工具" in msg_lower or "create tool" in msg_lower or "新工具" in msg_lower:
            result = self._handle_code_writing({})
            return result

        else:
            result = (
                "I can help with brachytherapy planning. Try:\n"
                "  - 'Segment CTV' - Segment CTV\n"
                "  - 'Generate plan' - Generate treatment plan\n"
                "  - 'Evaluate dose' - Evaluate dose distribution\n"
                "  - 'Optimize plan' - Optimize treatment plan\n"
                "  - 'Self-evolve' - Trigger self-evolution\n"
                "  - 'Create tool' - Create new tool"
            )
            return result

    def _rule_based_chat_with_steps(self, message: str, steps: List[Dict], step_id: List[int]) -> str:
        msg_lower = message.lower()
        if "分割" in msg_lower or "segment" in msg_lower:
            target = "CTV"
            if "oar" in msg_lower or "organ" in msg_lower or "器官" in msg_lower:
                target = "OAR"
            step_id[0] += 1
            steps.append({
                "id": step_id[0], "type": "tool", "title": f"Segmentation: {target}",
                "content": f"Running {target} segmentation...", "status": "done",
                "tool": f"{target.lower()}_segmentation", "params": {},
            })
            result = self._handle_ctv_segmentation_request(message) if target == "CTV" else self._handle_oar_segmentation_request(message)
            step_id[0] += 1
            steps.append({"id": step_id[0], "type": "result", "title": f"{target} Result", "content": result, "status": "done"})
            return result
        elif self._planning_requested(message):
            mode = "rl" if "rl" in msg_lower or "强化" in msg_lower else "rule_based"
            step_id[0] += 1
            steps.append({
                "id": step_id[0], "type": "tool", "title": "Seed Planning",
                "content": f"Generating seed plan ({mode} mode)...", "status": "done",
                "tool": "seed_planning", "params": {"mode": mode},
            })
            result = self._handle_planning_request(message)
            step_id[0] += 1
            steps.append({"id": step_id[0], "type": "result", "title": "Planning Result", "content": result, "status": "done"})
            return result
        elif "评估" in msg_lower or "eval" in msg_lower or "剂量" in msg_lower:
            step_id[0] += 1
            steps.append({
                "id": step_id[0], "type": "tool", "title": "Dose Evaluation",
                "content": "Evaluating dose distribution...", "status": "done",
                "tool": "dose_evaluation", "params": {},
            })
            result = self._handle_evaluation_request(message)
            step_id[0] += 1
            steps.append({"id": step_id[0], "type": "result", "title": "Evaluation Result", "content": result, "status": "done"})
            return result
        elif "优化" in msg_lower or "optim" in msg_lower or "调整" in msg_lower:
            result = self._handle_optimization_request(message)
            return result
        elif "进化" in msg_lower or "evolve" in msg_lower or "学习" in msg_lower or "总结经验" in msg_lower:
            result = self._handle_self_evolution()
            return result
        elif "写工具" in msg_lower or "create tool" in msg_lower or "新工具" in msg_lower:
            result = self._handle_code_writing({})
            return result
        else:
            result = (
                "I can help with brachytherapy planning. Try:\n"
                "  - 'Segment CTV' - Segment CTV\n"
                "  - 'Generate plan' - Generate treatment plan\n"
                "  - 'Evaluate dose' - Evaluate dose distribution\n"
                "  - 'Optimize plan' - Optimize treatment plan\n"
                "  - 'Self-evolve' - Trigger self-evolution\n"
                "  - 'Create tool' - Create new tool"
            )
            return result

    def _record_experience(self, message: str, response: str, steps: List[Dict] = None):
        """Record the interaction as an experience for self-evolution."""
        if not getattr(self, "exp_memory", None):
            return
        tool_chain = []
        for step in (steps or []):
            if step.get("type") == "tool":
                tool_chain.append({
                    "tool": step.get("tool", ""),
                    "params": step.get("params", {}),
                })
        success = "error" not in response.lower() and "fail" not in response.lower()
        self.exp_memory.record(
            user_intent=message,
            context={"phase": self.memory.current_phase.value},
            tool_chain=tool_chain,
            outcome=response[:500],
            success=success,
            metrics=self.memory.planning_results.get("metrics", {}),
        )

    def _rule_based_chat(self, message: str) -> str:
        msg_lower = message.lower()
        if "分割" in msg_lower or "segment" in msg_lower:
            if "ctv" in msg_lower or "target" in msg_lower or "肿瘤" in msg_lower:
                response = self._handle_ctv_segmentation_request(message)
            elif "oar" in msg_lower or "organ" in msg_lower or "器官" in msg_lower:
                response = self._handle_oar_segmentation_request(message)
            else:
                response = self._handle_ctv_segmentation_request(message)
        elif "计划" in msg_lower or "plan" in msg_lower or "规划" in msg_lower:
            response = self._handle_planning_request(message)
        elif "评估" in msg_lower or "eval" in msg_lower or "剂量" in msg_lower:
            response = self._handle_evaluation_request(message)
        elif "优化" in msg_lower or "optim" in msg_lower or "调整" in msg_lower:
            response = self._handle_optimization_request(message)
        elif "进化" in msg_lower or "evolve" in msg_lower or "学习" in msg_lower or "总结经验" in msg_lower:
            response = self._handle_self_evolution()
        elif "写工具" in msg_lower or "create tool" in msg_lower or "新工具" in msg_lower:
            response = self._handle_code_writing({})
        elif "工具" in msg_lower or "tool" in msg_lower or "帮助" in msg_lower or "help" in msg_lower:
            tools_info = "\n".join(
                f"  - {t['name']}: {t['description'][:80]}..."
                for t in self.registry.list_tools()
            )
            response = f"Available tools:\n{tools_info}"
        else:
            response = (
                "I can help with brachytherapy planning. Try:\n"
                "  - 'Segment CTV' - Segment CTV\n"
                "  - 'Generate plan' - Generate treatment plan\n"
                "  - 'Evaluate dose' - Evaluate dose distribution\n"
                "  - 'Optimize plan' - Optimize treatment plan\n"
                "  - 'Self-evolve' - Trigger self-evolution\n"
                "  - 'Create tool' - Create new tool"
            )
        return response

    def _handle_ctv_segmentation_request(self, message: str) -> str:
        ct_image = self.memory.retrieve("ct_image")
        ctv_path = self.memory.retrieve("ctv_path")
        if ct_image is None:
            return "Please provide CT image path first. Use run_preoperative_plan(ct_path=...) to load CT."
        # Detect tumor type from message
        tumor_type = self._detect_tumor_type_from_message(message)
        if not tumor_type and not ctv_path:
            return (
                "请先明确需要分割的肿瘤部位，或提供已有 CTV 标签文件。"
                "例如：胰腺癌、肝癌、肾癌、肺癌、结直肠癌、前列腺。"
            )
        params = {"image": ct_image, "label_path": ctv_path}
        if tumor_type:
            params["tumor_type"] = tumor_type
        result = self.registry.execute("ctv_segmentation", **params)
        self.memory.log_tool_call("ctv_segmentation", params, result)
        if result.success:
            self.memory.store("ctv_array", result.metadata["ctv_array"])
            self.memory.store("ctv_mask", result.metadata.get("ctv_mask"))
            if "label_stats" in result.metadata:
                self.memory.store("ctv_label_stats", result.metadata["label_stats"])
            if "label_map" in result.metadata:
                self.memory.store("ctv_label_map", result.metadata["label_map"])
            # Store ctv_voxels/volume for report generation
            _cv = result.metadata.get("ctv_voxel_count")
            if not _cv:
                try:
                    _cv = int(np.sum(np.asarray(result.metadata["ctv_array"]) > 0))
                except Exception:
                    _cv = 0
            self.memory.store("ctv_voxels", _cv)
            _cvm3 = result.metadata.get("ctv_volume_mm3")
            if _cvm3:
                self.memory.store("ctv_volume_mm3", _cvm3)
            if params.get("tumor_type"):
                self.memory.store("tumor_type_used", params["tumor_type"])
            elif result.metadata.get("tumor_type_used"):
                self.memory.store("tumor_type_used", result.metadata["tumor_type_used"])
            if result.metadata.get("ctv_source"):
                self.memory.store("ctv_source", result.metadata["ctv_source"])
            return result.message
        return f"CTV segmentation failed: {result.error}"

    def _handle_oar_segmentation_request(self, message: str) -> str:
        ct_image = self.memory.retrieve("ct_image")
        oar_path = self.memory.retrieve("oar_path")
        if ct_image is None:
            return "Please provide CT image path first."
        result = self.registry.execute("oar_segmentation", image=ct_image, label_path=oar_path)
        self.memory.log_tool_call("oar_segmentation", {}, result)
        if result.success:
            self.memory.store("oar_array", result.metadata.get("oar_array"))
            if "organ_names" in result.metadata:
                self.memory.store("organ_names", result.metadata["organ_names"])
            if "organ_counts" in result.metadata:
                self.memory.store("organ_counts", result.metadata["organ_counts"])
            return result.message
        return f"OAR segmentation failed: {result.error}"

    def _handle_planning_request(self, message: str) -> str:
        trajectories = self.memory.retrieve("trajectories")
        radiation_volume = self.memory.retrieve("radiation_volume")
        ct_image = self.memory.retrieve("ct_image")
        if trajectories is None or radiation_volume is None or ct_image is None:
            return "Please load CT image and generate segmentation results first, then proceed with planning."
        mode = "rl" if "rl" in message.lower() or "强化" in message else "rule_based"
        seed_info = self.config.get("seed_info", {"radius": 0.4, "length": 4.5, "seed_avr_dose": 50})
        dl_params = self.config.get("dl_params", {})
        result = self.registry.execute(
            "seed_planning",
            trajectories=trajectories,
            radiation_volume=radiation_volume,
            dose_image=ct_image,
            mode=mode,
            dl_params=dl_params,
            seed_info=seed_info,
        )
        self.memory.log_tool_call("seed_planning", {"mode": mode}, result)
        if result.success:
            self.memory.store("optimal_plan", result.metadata["optimal_plan"])
            self.memory.store("dose_distribution", result.metadata.get("dose_distribution"))
            self.memory.store("total_seeds", result.metadata["total_seeds"])
            return result.message
        return f"Seed planning failed: {result.error}"

    def _handle_evaluation_request(self, message: str) -> str:
        dose = self.memory.retrieve("dose_distribution")
        ctv = self.memory.retrieve("ctv_array")
        oar = self.memory.retrieve("oar_array")
        if dose is None or ctv is None:
            return "Please complete treatment plan generation first, then proceed with evaluation."
        result = self.registry.execute(
            "dose_evaluation", dose_array=dose, ctv_mask=ctv, oar_mask=oar,
        )
        self.memory.log_tool_call("dose_evaluation", {}, result)
        if result.success:
            return result.message
        return f"Dose evaluation failed: {result.error}"

    def _handle_optimization_request(self, message: str) -> str:
        dose = self.memory.retrieve("dose_distribution")
        ctv = self.memory.retrieve("ctv_array")
        oar = self.memory.retrieve("oar_array")
        if dose is None:
            return "No optimizable plan found. Please generate a treatment plan first."
        eval_result = self.registry.execute(
            "dose_evaluation", dose_array=dose, ctv_mask=ctv, oar_mask=oar,
        )
        if not eval_result.success:
            return f"Evaluation failed: {eval_result.error}"
        metrics = eval_result.metadata
        suggestions = []
        v100 = metrics.get("v100")
        v200 = metrics.get("v200")
        if v100 is not None:
            suggestions.append(
                f"Observed V100={float(v100):.1%}. Compare this with applicable site-specific guidance or the confirmed case protocol before judging acceptability."
            )
        if v200 is not None:
            suggestions.append(
                f"Observed V200={float(v200):.1%}. Review applicable hotspot limits before labeling a dose excess."
            )
        if metrics.get("oar_violations"):
            violations = metrics["oar_violations"]
            suggestions.append(
                f"Detected {len(violations)} source-backed OAR violation(s). Re-optimize only after confirming the constraints apply to this tumor site."
            )
        plan_score = metrics.get("plan_score", 0)
        if plan_score:
            suggestions.append(
                f"Plan score={plan_score}. Treat this as an advisory ranking signal, not final clinical approval."
            )
        if not suggestions:
            suggestions.append("Plan evaluation complete. Retrieve applicable site-specific guidance to produce source-backed optimization advice.")
        return f"Optimization suggestions:\n" + "\n".join(f"  - {s}" for s in suggestions)

    def run_preoperative_plan(
        self,
        ct_path: str,
        ctv_path: Optional[str] = None,
        oar_path: Optional[str] = None,
        mode: str = "rule_based",
        seed_info: Optional[Dict] = None,
        radiation_array_params: Optional[Dict] = None,
        reference_direc: Optional[List] = None,
        in_lowest_energy: Optional[int] = None,
        out_highest_energy: Optional[int] = None,
        DVH_rate: Optional[float] = None,
        max_iter: Optional[int] = None,
        rf_params: Optional[Dict] = None,
        output_dir: str = "./output",
        tumor_type: Optional[str] = None,
    ) -> Dict:
        self.memory.current_phase = PlanningPhase.PRE_OPERATIVE
        self.memory.add_message("system", f"Starting pre-operative planning for {ct_path}")

        requested_mode = mode
        if mode == "auto":
            mode = "rl" if bool(self.config.get("use_rf", False)) else "rule_based"
        if mode not in {"rule_based", "rl"}:
            return {
                "success": False,
                "phase": "pre_operative",
                "error": "mode must be 'rule_based', 'rl', or 'auto'",
            }

        requested_tumor_type = tumor_type or self.config.get("tumor_type")
        if requested_tumor_type:
            mapper = getattr(self, "_map_tumor_type", None)
            tumor_type = mapper(requested_tumor_type) if callable(mapper) else requested_tumor_type
        if not ctv_path and not tumor_type:
            return {
                "success": False,
                "phase": "pre_operative",
                "clarification_required": True,
                "error": (
                    "tumor_type is required for automatic CTV segmentation when "
                    "ctv_path is not provided"
                ),
            }

        default_seed_info = {"radius": 0.4, "length": 3.7, "seed_avr_dose": 50}
        seed_info = seed_info or self.config.get("seed_info") or default_seed_info
        radiation_array_params = radiation_array_params or self.config.get("radiation_array_params", {})
        reference_direc = reference_direc or self.config.get("reference_direc")
        if reference_direc is None:
            ui_state = self.memory.get_ui_state() if hasattr(self, 'memory') and hasattr(self.memory, 'get_ui_state') else {}
            planning_state = ui_state.get("planning") if isinstance(ui_state.get("planning"), dict) else {}
            reference_direc = planning_state.get("reference_direc") or [0, 1, 0]
        in_lowest_energy = in_lowest_energy if in_lowest_energy is not None else self.config.get("in_lowest_energy", 1)
        out_highest_energy = out_highest_energy if out_highest_energy is not None else self.config.get("out_highest_energy", 1)
        DVH_rate = DVH_rate if DVH_rate is not None else self.config.get("DVH_rate", 0.9)
        iter_rate = max_iter if max_iter is not None else self.config.get("iter_rate", self.config.get("max_iter", 2))

        target_value = radiation_array_params.get("target_value", 1)
        obstacle_value = radiation_array_params.get("obstacle_value", 2)
        background_value = radiation_array_params.get("background_value", 0)
        backlit_angle = radiation_array_params.get("backlit_angle", 0.5)
        max_candi_traj = radiation_array_params.get("maximum_candidate_trajectories", 200)
        min_depth = radiation_array_params.get("min_depth", 2)
        infer_img_size = radiation_array_params.get("infer_img_size", [64, 64, 64])
        direc_resolution = self.config.get("direc_resolution", [30, 3, 2])
        image_normalize = self.config.get("image_normalize", [-1000, 3000, 255])
        dl_params = self.config.get("dl_params", {})
        distance_filter = self.config.get("distance_filter") or self.config.get("distance_filtter") or {}

        try:
            logger.info("Step 1: Loading CT image")
            ct_image = sitk.ReadImage(ct_path)
            self.memory.store("ct_image", ct_image)
            self.memory.store("ct_path", ct_path)

            logger.info("Step 2: CTV Segmentation")
            ctv_kwargs = {"image": ct_image, "label_path": ctv_path}
            if tumor_type:
                ctv_kwargs["tumor_type"] = tumor_type
            ctv_result = self.registry.execute("ctv_segmentation", **ctv_kwargs)
            self.memory.log_tool_call(
                "ctv_segmentation",
                {"image_path": ct_path, "label_path": ctv_path, "tumor_type": tumor_type},
                ctv_result,
            )
            if not ctv_result.success:
                raise RuntimeError(f"CTV segmentation failed: {ctv_result.error}")

            ctv_metadata = ctv_result.metadata or {}
            ctv_array = ctv_metadata.get("ctv_array")
            if ctv_array is None:
                raise RuntimeError("CTV segmentation succeeded without a ctv_array result")
            self.memory.store("ctv_array", ctv_array)
            self.memory.store("ctv_voxels", ctv_metadata.get("ctv_voxel_count", 0))
            self.memory.store(
                "tumor_type_used",
                ctv_metadata.get("tumor_type_used")
                or tumor_type
                or "manual_label",
            )
            self.memory.store(
                "ctv_source",
                ctv_metadata.get("ctv_source")
                or ("manual_label" if ctv_path else "model"),
            )
            _cvm3 = ctv_metadata.get("ctv_volume_mm3")
            if _cvm3:
                self.memory.store("ctv_volume_mm3", _cvm3)
            logger.info(f"  CTV voxels: {ctv_metadata.get('ctv_voxel_count', int(np.count_nonzero(ctv_array)))}")

            logger.info("Step 3: OAR Segmentation")
            oar_result = self.registry.execute("oar_segmentation", image=ct_image, label_path=oar_path)
            self.memory.log_tool_call("oar_segmentation", {"image_path": ct_path, "label_path": oar_path}, oar_result)
            if not oar_result.success:
                raise RuntimeError(f"OAR segmentation failed: {oar_result.error}")

            oar_metadata = oar_result.metadata or {}
            oar_array = oar_metadata.get("oar_array")
            dose_constraints = {}
            if oar_array is not None:
                self.memory.store("oar_array", oar_array)
                if "organ_names" in oar_metadata:
                    self.memory.store("organ_names", oar_metadata["organ_names"])
                if "organ_counts" in oar_metadata:
                    self.memory.store("organ_counts", oar_metadata["organ_counts"])
                dose_constraints = self.config.get("oar_constraints", {})
                logger.info(f"  OAR labels: {list(oar_metadata.get('organ_counts', {}).keys())}")

            logger.info("Step 4: Building radiation volume")
            radiation_volume = np.zeros_like(ctv_array, dtype=np.float64)
            radiation_volume[ctv_array > 0] = target_value
            if oar_array is not None:
                oar_labels = np.unique(oar_array[oar_array > 0])
                for label in oar_labels:
                    radiation_volume[oar_array == label] = obstacle_value
            self.memory.store("radiation_volume", radiation_volume)

            logger.info("Step 5: Trajectory Planning")
            traj_result = self.registry.execute(
                "trajectory_planning",
                dose_image=ct_image, radiation_volume=radiation_volume,
                target_value=target_value, background_value=background_value, obstacle_value=obstacle_value,
                ref_direc=reference_direc,
                direc_resolution=direc_resolution,
                extract_angle=backlit_angle,
                maximum_candidate_trajectories=max_candi_traj,
                min_depth=min_depth,
            )
            self.memory.log_tool_call("trajectory_planning", {"num_candidates": "computed"}, traj_result)
            if not traj_result.success:
                raise RuntimeError(f"Trajectory planning failed: {traj_result.error}")

            trajectories = traj_result.metadata["trajectories"]
            self.memory.store("trajectories", trajectories)
            logger.info(f"  Generated {len(trajectories)} candidate trajectories")

            logger.info(f"Step 6: Seed Planning (mode={mode})")
            plan_kwargs = {
                "trajectories": trajectories, "radiation_volume": radiation_volume,
                "dose_image": ct_image, "mode": mode,
                "seed_info": seed_info, "target_value": target_value, "background_value": background_value, "obstacle_value": obstacle_value,
                "dl_params": dl_params,
                "in_lowest_dose": in_lowest_energy,
                "out_highest_dose": out_highest_energy,
                "DVH_rate": DVH_rate,
                "infer_img_size": infer_img_size,
                "image_normalize": image_normalize,
                "iter_rate": iter_rate,
                "lower_bound": distance_filter.get("lower_bound", 0.8),
                "upper_bound": distance_filter.get("upper_bound", 10),
                "distance_rate": distance_filter.get("distance_rate", 0.8),
                "interval_rate": distance_filter.get("interval_rate", 2),
            }
            if mode == "rl" and rf_params:
                plan_kwargs["rf_params"] = rf_params

            seed_result = self.registry.execute("seed_planning", **plan_kwargs)
            self.memory.log_tool_call("seed_planning", {"mode": mode, "num_trajectories": len(trajectories)}, seed_result)
            if not seed_result.success:
                raise RuntimeError(f"Seed planning failed: {seed_result.error}")

            optimal_plan = seed_result.metadata["optimal_plan"]
            dose_distribution = seed_result.metadata.get("dose_distribution", np.zeros_like(radiation_volume))
            total_seeds = seed_result.metadata["total_seeds"]

            self.memory.store("optimal_plan", optimal_plan)
            self.memory.store("dose_distribution", dose_distribution)
            self.memory.store("total_seeds", total_seeds)
            logger.info(f"  Planned {total_seeds} seeds")

            logger.info("Step 7: Dose Evaluation")
            dose_spacing = ct_image.GetSpacing() if hasattr(ct_image, "GetSpacing") else [1.0, 1.0, 1.0]
            eval_result = self.registry.execute(
                "dose_evaluation", dose_array=dose_distribution, ctv_mask=ctv_array,
                oar_mask=oar_array, prescribed_dose=float(in_lowest_energy), target_value=target_value,
                oar_constraints=dose_constraints,
                organ_names=oar_metadata.get("organ_names", {}),
                spacing=dose_spacing,
                tumor_type=self.memory.retrieve("tumor_type_used") or "",
            )
            self.memory.log_tool_call("dose_evaluation", {"prescribed_dose": float(in_lowest_energy)}, eval_result)
            if not eval_result.success:
                raise RuntimeError(f"Dose evaluation failed: {eval_result.error}")

            eval_metrics = eval_result.metadata or {}
            v100_val = eval_metrics.get("v100", 0)
            v100_display = f"{v100_val * 100:.1f}%" if v100_val <= 1 else f"{v100_val:.1f}%"
            logger.info(f"  V100={v100_display}, D90={eval_metrics.get('d90', 0):.2f}Gy, Score={eval_metrics.get('plan_score', 0):.1f}")

            os.makedirs(output_dir, exist_ok=True)
            self.memory.export_state(os.path.join(output_dir, "agent_state.json"))

            self.memory.current_phase = PlanningPhase.COMPLETED

            return {
                "success": True, "phase": "pre_operative",
                "requested_mode": requested_mode, "mode": mode,
                "total_seeds": total_seeds,
                "num_trajectories": len(optimal_plan) if optimal_plan else 0,
                "metrics": eval_metrics, "optimal_plan": optimal_plan,
                "dose_distribution": dose_distribution, "output_dir": output_dir,
            }
        except Exception as e:
            self.memory.current_phase = PlanningPhase.FAILED
            self.memory.add_message("system", f"Planning failed: {str(e)}")
            logger.error(f"Pre-operative planning failed: {str(e)}")
            return {"success": False, "phase": "pre_operative", "error": str(e)}

    def run_intraoperative_replan(
        self,
        intra_op_ct_path: str,
        original_plan: Any,
        deviation_threshold_mm: float = 2.0,
        output_dir: str = "./output/replan",
    ) -> Dict:
        self.memory.current_phase = PlanningPhase.INTRA_OPERATIVE
        self.memory.deviation_threshold_mm = deviation_threshold_mm

        try:
            logger.info(f"Loading intra-op CT from {intra_op_ct_path}")
            intra_op_image = sitk.ReadImage(intra_op_ct_path)

            logger.info("Detecting implanted seeds")
            planned_seeds = self._extract_planned_seeds(original_plan)
            if not planned_seeds:
                raise RuntimeError("A non-empty original plan with physical seed positions is required")

            preop_image = self.memory.retrieve("ct_image")
            if preop_image is None:
                raise RuntimeError("The pre-operative CT is not available in this session")
            same_frame, frame_reason = self._images_share_physical_frame(preop_image, intra_op_image)
            if not same_frame:
                raise RuntimeError(
                    "Intra-operative CT registration is not verified: " + frame_reason
                )

            seed_seg_result = self.registry.execute(
                "seed_segmentation", image=intra_op_image, planned_seeds=planned_seeds,
            )
            self.memory.log_tool_call("seed_segmentation", {"image_path": intra_op_ct_path}, seed_seg_result)

            if not seed_seg_result.success:
                raise RuntimeError(f"Seed detection failed: {seed_seg_result.error}")

            detected_seeds = seed_seg_result.metadata.get("detected_seeds") or seed_seg_result.data or []
            if not detected_seeds:
                raise RuntimeError("No implanted seeds were detected; automatic deviation assessment is unsafe")

            if len(detected_seeds) != len(planned_seeds):
                self.memory.current_phase = PlanningPhase.COMPLETED
                return {
                    "success": True,
                    "phase": "intraoperative_review",
                    "deviation_detected": True,
                    "requires_human_review": True,
                    "automatic_replanning_blocked": True,
                    "planned_seed_count": len(planned_seeds),
                    "detected_seed_count": len(detected_seeds),
                    "detected_seeds": detected_seeds,
                    "message": (
                        "Detected and planned seed counts differ. Review segmentation and "
                        "registration before reconstructing delivered dose or replanning."
                    ),
                }

            matched_seeds, deviations = self._match_detected_seeds(
                planned_seeds, detected_seeds
            )
            max_deviation = float(np.max(deviations))
            mean_deviation = float(np.mean(deviations))
            logger.info(f"  Max deviation: {max_deviation:.2f}mm, Mean: {mean_deviation:.2f}mm")

            needs_replan = max_deviation > deviation_threshold_mm

            if needs_replan:
                logger.info(f"Deviation {max_deviation:.2f}mm > threshold. Triggering replanning...")
                self.memory.current_phase = PlanningPhase.REPLANNING
                replan_result = self._trigger_replanning(
                    intra_op_image, original_plan, matched_seeds, output_dir,
                )
                if not replan_result.get("success"):
                    self.memory.current_phase = PlanningPhase.FAILED
                    return {
                        "success": False,
                        "phase": "replanning",
                        "deviation_detected": True,
                        "max_deviation_mm": max_deviation,
                        "mean_deviation_mm": mean_deviation,
                        "error": replan_result.get("error", "Replanning failed"),
                        "replan_result": replan_result,
                    }
                self.memory.current_phase = PlanningPhase.COMPLETED
                return {
                    "success": True, "phase": "replanning",
                    "deviation_detected": True,
                    "max_deviation_mm": max_deviation, "mean_deviation_mm": mean_deviation,
                    "replan_result": replan_result,
                }
            else:
                logger.info(f"Deviation {max_deviation:.2f}mm within threshold.")
                self.memory.current_phase = PlanningPhase.COMPLETED
                return {
                    "success": True, "phase": "intra_operative",
                    "deviation_detected": False,
                    "max_deviation_mm": max_deviation, "mean_deviation_mm": mean_deviation,
                    "planned_seed_count": len(planned_seeds),
                    "detected_seed_count": len(detected_seeds),
                    "message": "Seed positions within acceptable range.",
                }
        except Exception as e:
            self.memory.current_phase = PlanningPhase.FAILED
            logger.error(f"Intra-operative replanning failed: {str(e)}")
            return {"success": False, "phase": "intra_operative", "error": str(e)}

    def _extract_planned_seeds(self, plan) -> List:
        planned_seeds = []
        if isinstance(plan, dict):
            nested = None
            for key in ("optimal_plan", "seed_plan", "trajectories", "plan"):
                candidate = plan.get(key)
                if candidate is not None:
                    nested = candidate
                    break
            if nested is not None:
                return self._extract_planned_seeds(nested)
            if isinstance(plan.get("seeds"), list):
                plan = [plan]
        if isinstance(plan, (list, tuple)):
            for entry in plan:
                if isinstance(entry, dict):
                    seeds = entry.get("seeds") or []
                elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    seeds = entry[1]
                else:
                    continue
                if not isinstance(seeds, (list, tuple)):
                    continue
                for seed in seeds:
                    if isinstance(seed, dict):
                        position = seed.get("position", seed.get("physical_position"))
                        direction = seed.get("direction", [0.0, 0.0, 1.0])
                    elif isinstance(seed, (list, tuple)) and len(seed) >= 1:
                        position = seed[0]
                        direction = seed[1] if len(seed) > 1 else [0.0, 0.0, 1.0]
                    else:
                        continue
                    pos = np.asarray(position, dtype=np.float64).reshape(-1)
                    direc = np.asarray(direction, dtype=np.float64).reshape(-1)
                    if (
                        pos.size == 3
                        and direc.size == 3
                        and np.all(np.isfinite(pos))
                        and np.all(np.isfinite(direc))
                    ):
                        planned_seeds.append([pos.tolist(), direc.tolist()])
        return planned_seeds

    @staticmethod
    def _images_share_physical_frame(reference_image, moving_image) -> Tuple[bool, str]:
        """Verify a shared DICOM frame or a matching legacy image geometry."""
        tag = "0020|0052"  # FrameOfReferenceUID

        def frame_uid(image):
            try:
                if image.HasMetaDataKey(tag):
                    return str(image.GetMetaData(tag)).strip()
            except Exception:
                return ""
            return ""

        reference_uid = frame_uid(reference_image)
        moving_uid = frame_uid(moving_image)
        if reference_uid or moving_uid:
            if reference_uid and moving_uid and reference_uid == moving_uid:
                return True, "matching FrameOfReferenceUID"
            return False, "FrameOfReferenceUID is missing or does not match"

        reference_origin = np.asarray(reference_image.GetOrigin(), dtype=np.float64)
        moving_origin = np.asarray(moving_image.GetOrigin(), dtype=np.float64)
        reference_direction = np.asarray(reference_image.GetDirection(), dtype=np.float64)
        moving_direction = np.asarray(moving_image.GetDirection(), dtype=np.float64)
        if not np.allclose(reference_origin, moving_origin, atol=1e-3, rtol=0.0):
            return False, "image origins differ and no FrameOfReferenceUID is available"
        if not np.allclose(reference_direction, moving_direction, atol=1e-5, rtol=0.0):
            return False, "image directions differ and no FrameOfReferenceUID is available"
        return True, "matching origin and direction fallback"

    @staticmethod
    def _match_detected_seeds(planned_seeds: List, detected_seeds: List) -> Tuple[List[Dict], np.ndarray]:
        """One-to-one match detected centers to planned directions in physical LPS."""
        from scipy.optimize import linear_sum_assignment

        planned_positions = np.asarray([seed[0] for seed in planned_seeds], dtype=np.float64)
        planned_directions = np.asarray([seed[1] for seed in planned_seeds], dtype=np.float64)
        detected_positions = np.asarray(
            [seed.get("physical_position") for seed in detected_seeds],
            dtype=np.float64,
        )
        if (
            planned_positions.shape != detected_positions.shape
            or planned_positions.ndim != 2
            or planned_positions.shape[1] != 3
            or not np.all(np.isfinite(planned_positions))
            or not np.all(np.isfinite(detected_positions))
        ):
            raise ValueError("Planned and detected seed positions must be finite Nx3 arrays")

        distances = np.linalg.norm(
            planned_positions[:, None, :] - detected_positions[None, :, :],
            axis=2,
        )
        planned_indices, detected_indices = linear_sum_assignment(distances)
        matched = []
        matched_distances = []
        for planned_index, detected_index in zip(planned_indices, detected_indices):
            detected = detected_seeds[int(detected_index)]
            matched.append({
                "id": detected.get("id", int(detected_index) + 1),
                "position": detected_positions[detected_index].tolist(),
                "direction": planned_directions[planned_index].tolist(),
                "planned_index": int(planned_index),
                "detected_index": int(detected_index),
            })
            matched_distances.append(float(distances[planned_index, detected_index]))
        return matched, np.asarray(matched_distances, dtype=np.float64)

    def _trigger_replanning(self, intra_op_image, original_plan, detected_seeds, output_dir) -> Dict:
        logger.info("Starting residual-dose intra-operative replanning")
        del intra_op_image, original_plan  # Registration and matching were verified by the caller.

        ct_image = self.memory.retrieve("ct_image")
        ctv_array = self.memory.retrieve("ctv_array")
        oar_array = self.memory.retrieve("oar_array")
        if ct_image is None or ctv_array is None:
            return {"success": False, "error": "Pre-operative CT and CTV are required for replanning"}

        from tool_factory.seed_plan.model_support import (
            compute_world_seed_dose_grid,
            resolve_dose_model,
        )
        from tool_factory.seed_plan.planning_pipeline import (
            NEW_SLICES_ROUNDED,
            _resample_for_planning,
        )

        resampled_ct = self.memory.retrieve("resampled_ct")
        resampled_ctv = self.memory.retrieve("resampled_ctv")
        resampled_oar = self.memory.retrieve("resampled_oar")
        if resampled_ct is None or resampled_ctv is None:
            resampled_ct, resampled_ctv, resampled_oar = _resample_for_planning(
                ct_image,
                np.asarray(ctv_array),
                np.asarray(oar_array) if oar_array is not None else None,
                new_size=[128, 128, NEW_SLICES_ROUNDED],
            )
            self.memory.store("resampled_ct", resampled_ct)
            self.memory.store("resampled_ctv", resampled_ctv)
            if resampled_oar is not None:
                self.memory.store("resampled_oar", resampled_oar)

        ctv_grid = sitk.GetArrayFromImage(resampled_ctv)
        oar_grid = sitk.GetArrayFromImage(resampled_oar) if resampled_oar is not None else None
        radiation_config = self.config.get("radiation_array_params", {}) or {}
        target_value = int(radiation_config.get("target_value", 1))
        background_value = int(radiation_config.get("background_value", 0))
        obstacle_value = int(radiation_config.get("obstacle_value", 3))
        target_mask = ctv_grid == target_value
        if not np.any(target_mask):
            return {"success": False, "error": "Resampled CTV contains no target voxels"}

        radiation_volume = np.full(ctv_grid.shape, background_value, dtype=np.float64)
        radiation_volume[target_mask] = target_value
        if oar_grid is not None:
            if oar_grid.shape != radiation_volume.shape:
                return {"success": False, "error": "Resampled OAR shape does not match the planning grid"}
            radiation_volume[oar_grid > 0] = obstacle_value
        active_target_mask = radiation_volume == target_value
        if not np.any(active_target_mask):
            return {"success": False, "error": "No target voxels remain after applying OAR obstacles"}

        dl_params = dict(self.config.get("dl_params", {}) or {})
        dl_params.setdefault("infer_img_size", radiation_config.get("infer_img_size", [64, 64, 64]))
        dl_params.setdefault("image_normalize", self.config.get("image_normalize", [-1000, 3000, 255]))
        seed_info = self.config.get(
            "seed_info", {"radius": 0.4, "length": 4.5, "seed_avr_dose": 50}
        )
        dose_model, model_error = resolve_dose_model({}, dl_params)
        if dose_model is None:
            return {"success": False, "error": model_error or "dose_unet_spacing1mm is unavailable"}

        try:
            delivered_dose, accepted_detected = compute_world_seed_dose_grid(
                detected_seeds,
                resampled_ct,
                dose_model,
                dl_params,
                seed_info,
            )
        except Exception as exc:
            return {"success": False, "error": f"Delivered-dose reconstruction failed: {exc}"}
        if len(accepted_detected) != len(detected_seeds):
            return {
                "success": False,
                "error": "One or more detected seeds fall outside the registered planning grid",
            }

        prescription = float(self.config.get("in_lowest_energy", 1.0))
        adjusted_volume = radiation_volume.copy()
        covered_target = active_target_mask & (delivered_dose >= prescription)
        adjusted_volume[covered_target] = background_value

        supplemental_plan = []
        supplemental_dose = np.zeros_like(delivered_dose, dtype=np.float32)
        if np.any(adjusted_volume == target_value):
            from tool_factory.seed_plan.planning_pipeline import _resolve_ref_direc

            ui_state = self.memory.get_ui_state() if hasattr(self, 'memory') and hasattr(self.memory, 'get_ui_state') else {}
            planning_state = ui_state.get("planning") if isinstance(ui_state.get("planning"), dict) else {}
            ref_direction = _resolve_ref_direc(
                planning_state.get("reference_direc") or self.config.get("reference_direc", "auto"),
                resampled_ct,
                ctv_grid,
                self,
            )
            traj_result = self.registry.execute(
                "trajectory_planning",
                dose_image=resampled_ct,
                radiation_volume=adjusted_volume,
                target_value=target_value,
                background_value=background_value,
                obstacle_value=obstacle_value,
                ref_direc=ref_direction,
                direc_resolution=self.config.get("direc_resolution", [30, 3, 2]),
                extract_angle=radiation_config.get("backlit_angle", 0.5),
                maximum_candidate_trajectories=radiation_config.get(
                    "maximum_candidate_trajectories", 200
                ),
                min_depth=radiation_config.get("min_depth", 2),
            )
            if not traj_result.success or not traj_result.data:
                return {"success": False, "error": "No safe supplemental trajectories were found"}

            distance_filter = self.config.get("distance_filter") or self.config.get("distance_filtter") or {}
            plan_result = self.registry.execute(
                "seed_planning",
                trajectories=traj_result.data,
                radiation_volume=adjusted_volume,
                dose_image=resampled_ct,
                dose_cal_model=dose_model,
                mode="rule_based",
                dl_params=dl_params,
                seed_info=seed_info,
                target_value=target_value,
                background_value=background_value,
                obstacle_value=obstacle_value,
                in_lowest_dose=prescription,
                out_highest_dose=float(self.config.get("out_highest_energy", 1.0)),
                DVH_rate=float(self.config.get("DVH_rate", 0.9)),
                iter_rate=int(self.config.get("iter_rate", self.config.get("max_iter", 2))),
                lower_bound=distance_filter.get("lower_bound", 0.8),
                upper_bound=distance_filter.get("upper_bound", 10),
                distance_rate=distance_filter.get("distance_rate", 0.8),
                interval_rate=distance_filter.get("interval_rate", 2),
            )
            if not plan_result.success:
                return {"success": False, "error": f"Supplemental seed planning failed: {plan_result.error}"}
            supplemental_plan = plan_result.data or []
            supplemental_dose = np.asarray(
                (plan_result.metadata or {}).get("dose_distribution"), dtype=np.float32
            )
            if supplemental_dose.shape != delivered_dose.shape:
                return {"success": False, "error": "Supplemental dose shape does not match delivered dose"}

        cumulative_dose = delivered_dose + supplemental_dose
        eval_result = self.registry.execute(
            "dose_evaluation",
            dose_array=cumulative_dose,
            ctv_mask=ctv_grid,
            target_value=target_value,
            oar_mask=oar_grid,
            organ_names=self.memory.retrieve("organ_names", {}) or {},
            oar_constraints=self.config.get("oar_constraints", {}) or {},
            prescribed_dose=prescription,
            spacing=resampled_ct.GetSpacing(),
            tumor_type=self.memory.retrieve("tumor_type_used", "") or "",
        )
        if not eval_result.success:
            return {"success": False, "error": f"Cumulative dose evaluation failed: {eval_result.error}"}

        implanted_entry = {
            "trajectory": {"id": "implanted_detected", "points": []},
            "seeds": [
                {"position": seed["position"], "direction": seed["direction"]}
                for seed in accepted_detected
            ],
            "num_seeds": len(accepted_detected),
        }
        combined_plan = [implanted_entry] + list(supplemental_plan)
        supplemental_count = int(sum(
            len(entry[1])
            for entry in supplemental_plan
            if isinstance(entry, (list, tuple)) and len(entry) >= 2 and entry[1] is not None
        ))
        total_seeds = len(accepted_detected) + supplemental_count

        self.memory.store("delivered_dose_distribution", delivered_dose)
        self.memory.store("supplemental_plan", supplemental_plan)
        self.memory.store("seed_plan", combined_plan)
        self.memory.store("seed_plan_serialized", combined_plan)
        self.memory.store("dose_distribution", cumulative_dose)
        self.memory.store("dose_metrics", eval_result.metadata or {})
        self.memory.store("metrics", eval_result.metadata or {})
        self.memory.store("total_seeds", total_seeds)
        self.memory.store("num_trajectories", len(supplemental_plan))
        os.makedirs(output_dir, exist_ok=True)
        self.memory.export_state(os.path.join(output_dir, "replan_state.json"))
        return {
            "success": True,
            "new_plan": supplemental_plan,
            "implanted_seed_count": len(accepted_detected),
            "supplemental_seed_count": supplemental_count,
            "total_seeds": total_seeds,
            "metrics": eval_result.metadata or {},
            "registration_status": "physical_frame_verified",
            "dose_engine": "dose_unet_spacing1mm",
        }

    def get_status(self) -> Dict:
        status = {
            "session_id": self.memory.session_id,
            "phase": self.memory.current_phase.value,
            "tools_available": self.registry.tool_names,
            "tool_calls_made": len(self.memory.tool_results),
            "messages": len(self.memory.conversation),
            "stored_keys": list(self.memory.planning_results.keys()),
            "ct_loaded": self.memory.retrieve("ct_image") is not None,
            "ct_path": self.memory.retrieve("ct_path") or "",
        }
        try:
            status["skills_available"] = len(self.skill_registry.list_skills())
        except AttributeError:
            status["skills_available"] = 0
        try:
            status["learned_preferences"] = len(self.preference_store.get_high_confidence())
        except AttributeError:
            status["learned_preferences"] = 0
        if getattr(self, "exp_memory", None):
            status["experiences"] = self.exp_memory.get_summary()
        if self.evolution_engine:
            status["evolution"] = self.evolution_engine.get_evolution_summary()
        if self.enhanced:
            status["enhanced"] = self.enhanced.get_agent_status()
        return status

    def get_recommended_skill(self, message: str) -> Optional[Dict]:
        matching_skills = self.skill_registry.find_by_trigger(message)
        if not matching_skills:
            return None
        best = matching_skills[0]
        return {
            "name": best.name, "description": best.description,
            "tool_sequence": best.tool_sequence, "parameters": best.parameters,
            "success_rate": best.success_rate(), "usage_count": best.usage_count,
        }

    def evolve_from_interactions(self) -> Dict:
        learned_skills = self.skill_learner.learn_from_interactions(min_occurrences=3)
        learned_prefs = self.skill_learner.learn_parameter_preferences()
        self.preference_store.update_from_learned(learned_prefs)
        evolved = self.skill_registry.evolve_from_interactions(
            self.interaction_memory, self.skill_learner
        )
        evolution_results = {}
        if self.evolution_engine:
            evolution_results = self.evolution_engine.evolve()
        return {
            "new_skills": [s.to_dict() for s in learned_skills],
            "evolved_skills": [s.to_dict() for s in evolved],
            "updated_preferences": self.preference_store.get_all_preferences(),
            "evolution_results": evolution_results,
        }

    def apply_user_preference(self, tool_name: str, params: Dict) -> Dict:
        return self.preference_store.apply_to_tool_params(tool_name, params)
