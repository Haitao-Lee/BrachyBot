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

from agent_runtime.core import PlanningPhase, ToolResultPipeline, resolve_reference_direction_input
from agent_runtime.contracts import RunStatus
from agent_runtime.execution_authorization import TurnExecutionAuthorization
from agent_runtime.visual_evidence import VISUAL_EVIDENCE_PROTOCOL_MARKER
from agent_runtime.turn_policy import (
    classify_local_turn,
    resolve_session_content_presentation,
    resolve_session_content_target,
    visual_analysis_policy,
)
from plans.dose_pre.model_loader import (
    DEFAULT_PRESCRIPTION_GY,
    DOSE_MODEL_SCALE_GY,
    planning_dose_value_to_gy,
    planning_dose_value_to_model,
    resolve_prescription_gy,
)

logger = logging.getLogger(__name__)


class ChatWorkflowMixin:
    @staticmethod
    def _internal_followup_language(turn_context: Dict[str, Any]) -> str:
        """Return the original user language for a hidden child turn.

        Screenshot analysis is an implementation detail of the visible parent
        reply. Its generated multimodal prompt contains English protocol text,
        so inferring language from that prompt would incorrectly override the
        language chosen by the real user. The task layer persists the parent's
        response language expressly for this hand-off.
        """
        raw = str((turn_context or {}).get("response_language") or "").strip().lower()
        if raw.startswith("zh"):
            return "zh"
        if raw.startswith("en"):
            return "en"
        return ""

    @staticmethod
    def _strip_internal_visual_context_text(value: Any) -> str:
        """Remove complete generated screenshot-child blocks from summaries.

        A hidden multimodal child can be compacted into ``AgentMemory``'s
        plain-text summary before the child finishes. Removing only the URL
        and instruction lines is insufficient because the embedded
        ``User request: ...`` line then survives as an apparently current
        command and can steer a later unrelated turn. The generated protocol
        has a stable structure, so remove the whole block up to the next
        assistant record while preserving real user/assistant discussion.
        """
        text = str(value or "")
        if not text:
            return ""
        lines = text.splitlines()
        cleaned: List[str] = []
        assistant_boundary = re.compile(
            r"^\s*(?:assistant|brachybot|助手|机器人|ai)\s*:", re.IGNORECASE,
        )
        user_boundary = re.compile(r"^\s*(?:user|用户)\s*:", re.IGNORECASE)
        protocol_marker = VISUAL_EVIDENCE_PROTOCOL_MARKER
        terminal_markers = (
            "Analyze the supplied screenshot",
            "Do not request another screenshot",
            "Do not repeat attachment titles",
            "Mention uncertainty instead of inventing details",
            "Use Chinese for every user-visible sentence",
            "Use English for every user-visible sentence",
            "分析提供的截图",
            "不要请求另一个截图",
            "不要重复附件标题",
            "如无法确认请说明不确定性",
        )

        index = 0
        while index < len(lines):
            # A compacted block normally starts with ``User: [Screenshot ...]``.
            # It can also begin directly at the screenshot line after a legacy
            # compaction pass, so include either shape in the candidate.  Do
            # not begin a candidate at every ``User:`` line: doing so could
            # consume a real later user request when an interrupted child has
            # no assistant response yet.
            starts_with_user = bool(user_boundary.match(lines[index]))
            starts_with_capture = "[Screenshot captured:" in lines[index]
            starts_with_embedded_request = "User request:" in lines[index] or "用户请求：" in lines[index]
            starts_with_protocol = protocol_marker in lines[index]
            if not (
                starts_with_capture
                or starts_with_embedded_request
                or starts_with_protocol
                or (starts_with_user and (starts_with_capture or starts_with_protocol))
            ):
                cleaned.append(lines[index])
                index += 1
                continue

            end = index + 1
            while end < len(lines):
                if assistant_boundary.match(lines[end]):
                    break
                candidate_so_far = "\n".join(lines[index:end])
                # A worker may have been cancelled before it wrote its child
                # assistant response.  Once the generated protocol is
                # complete, the following real ``User:`` record is a hard
                # boundary, not part of the visual child.
                if (
                    user_boundary.match(lines[end])
                    and any(marker in candidate_so_far for marker in terminal_markers)
                    and (
                        "[Screenshot captured:" in candidate_so_far
                        or "User request:" in candidate_so_far
                        or "用户请求：" in candidate_so_far
                        or protocol_marker in candidate_so_far
                    )
                ):
                    break
                end += 1
            candidate = "\n".join(lines[index:end])
            has_capture = "[Screenshot captured:" in candidate
            has_embedded_request = "User request:" in candidate or "用户请求：" in candidate
            has_protocol = protocol_marker in candidate
            has_terminal_instruction = any(marker in candidate for marker in terminal_markers)
            # The second clause repairs summaries already partially cleaned by
            # prior versions, where only the generated request plus terminal
            # instruction survived after the original capture URL was removed.
            is_generated_block = (
                (has_capture or has_protocol) and has_terminal_instruction
            ) or (
                has_embedded_request
                and has_terminal_instruction
                and (starts_with_user or starts_with_embedded_request or starts_with_protocol)
            )
            if is_generated_block:
                if cleaned and user_boundary.match(cleaned[-1]) and not cleaned[-1].split(":", 1)[-1].strip():
                    cleaned.pop()
                index = end
                continue
            cleaned.append(lines[index])
            index += 1
        return "\n".join(cleaned).strip()

    @staticmethod
    def _is_internal_visual_context_entry(entry: Any) -> bool:
        """Recognize only the generated multimodal child prompt.

        This is deliberately a protocol check, not an intent classifier.  A
        real user may ask to inspect a screenshot, so the ordinary words
        "screenshot" and "analyze" must never be enough to delete context.
        The generated child always carries the capture marker, a ``User
        request`` block, and one of the fixed analysis instructions.
        """
        if isinstance(entry, dict):
            content = entry.get("content") or entry.get("message") or entry.get("text") or ""
            marked = (
                entry.get("internal_followup") is True
                or entry.get("internalFollowup") is True
                or str(entry.get("message_kind") or entry.get("messageKind") or "").lower()
                == "internal_followup"
            )
        else:
            content = getattr(entry, "content", "")
            marked = bool(getattr(entry, "internal_followup", False))
        if marked:
            return True
        content = str(content or "")
        has_capture = "[Screenshot captured:" in content
        has_request = "User request:" in content or "用户请求：" in content
        has_instruction = (
            "Analyze the supplied screenshot" in content
            or "分析提供的截图" in content
            or "Do not request another screenshot" in content
            or "不要请求另一个截图" in content
        )
        has_terminal_instruction = (
            "Do not repeat attachment titles" in content
            or "Mention uncertainty instead of inventing details" in content
            or "不要重复附件标题" in content
            or "如无法确认请说明不确定性" in content
        )
        return (
            has_capture and (has_instruction or has_terminal_instruction)
        ) or (
            has_request
            and has_terminal_instruction
            and (has_instruction or has_terminal_instruction)
        )

    def _purge_orphaned_visual_context(self) -> None:
        """Remove legacy hidden visual prompts before a new user turn.

        Older clients persisted the generated multimodal prompt in the
        AgentMemory conversation.  Workspace migration protects future
        snapshots, but an already-hydrated Agent can still hold that row in
        memory.  Purging this exact protocol record at the turn boundary is
        what prevents a later unrelated question from inheriting the previous
        screenshot task while preserving all genuine clinical conversation.
        """
        memory = getattr(self, "memory", None)
        if memory is None or not hasattr(memory, "_lock"):
            return
        with memory._lock:
            conversation = getattr(memory, "conversation", None)
            if isinstance(conversation, list):
                memory.conversation = [
                    entry for entry in conversation
                    if not self._is_internal_visual_context_entry(entry)
                ]
            smart = getattr(memory, "smart_context", None)
            smart_messages = getattr(smart, "messages", None) if smart is not None else None
            if isinstance(smart_messages, list):
                smart.messages = [
                    entry for entry in smart_messages
                    if not self._is_internal_visual_context_entry(entry)
                ]
            # Compaction stores the same child prompt as plain text.  Clean
            # that second representation as well, otherwise ``get_clean_context``
            # can reintroduce the old screenshot task after the message row is
            # removed and make an unrelated user request appear to be pending.
            summary = getattr(memory, "context_summary", "")
            cleaned_summary = self._strip_internal_visual_context_text(summary)
            if cleaned_summary != summary:
                memory.context_summary = cleaned_summary
            # A removed prompt changes the context inputs.  Never reuse a
            # cleaned prompt summary or relevance cache for the next turn.
            if hasattr(memory, "_clean_context_cache_key"):
                memory._clean_context_cache_key = None
            if hasattr(memory, "_clean_context_cache_value"):
                memory._clean_context_cache_value = ""

    @staticmethod
    def _llm_unavailable_message(lang: str = "zh") -> str:
        """Explain an unavailable model instead of fabricating an LLM answer.

        Greetings and self-description are conversational requests. A static
        reply here would make the product look like a keyword bot and could
        hide a broken provider configuration. The UI can still use explicit
        direct tools while the user fixes the provider.
        """
        if str(lang or "").lower().startswith("en"):
            return (
                "The AI language service is temporarily unavailable, so I cannot "
                "produce a reliable answer right now. No clinical action was started. "
                "Please retry after the service connection is restored."
            )
        return (
            "AI 语言服务暂时不可用，因此我现在无法生成可靠回答。"
            "本次没有启动任何临床操作；请在服务连接恢复后重试。"
        )

    def _current_llm_unavailable_message(self) -> str:
        """Return a provider-failure message in the current conversation language."""
        lang = getattr(getattr(self, "memory", None), "user_lang", "zh")
        return self._llm_unavailable_message(lang)

    def _response_language(self, lang: Optional[str] = None) -> str:
        """Return the normalized language for the current user-visible turn."""
        value = lang or getattr(getattr(self, "memory", None), "user_lang", "en")
        return "zh" if str(value or "").lower().startswith("zh") else "en"

    @staticmethod
    def _is_explicit_capability_request(message: str) -> bool:
        """Recognize a request for help/capabilities, not an arbitrary action."""
        text = re.sub(r"\s+", " ", str(message or "").strip().lower())
        if not text:
            return False
        return bool(
            re.search(
                r"(?:你能做什么|你可以做什么|有哪些(?:工具|功能)|工具列表|功能列表|使用说明|能力说明)[?？.!！ ]*$",
                text,
            )
            or re.search(
                r"^(?:help|capabilities|available tools|list tools|what can you do|"
                r"what are your capabilities|how do i use you)[?.! ]*$",
                text,
                flags=re.IGNORECASE,
            )
        )

    @staticmethod
    def _is_generic_capability_menu(response: Any) -> bool:
        """Detect the legacy hard-coded menu that answered unrelated turns."""
        text = str(response or "").strip().lower()
        if not text or "i can help with brachytherapy planning" not in text:
            return False
        if "try:" not in text:
            return False
        markers = (
            "segment ctv", "generate plan", "evaluate dose",
            "optimize plan", "self-evolve", "create tool",
        )
        return sum(marker in text for marker in markers) >= 2

    @staticmethod
    def _capability_response(lang: str = "en") -> str:
        """Describe capabilities in the language used by the current turn."""
        if str(lang or "").lower().startswith("zh"):
            return (
                "我可以协助当前病例的 CT 与分割、Planning、Dose/DVH、针道与粒子、"
                "手术导板和报告。请直接说明要查询的对象或要执行的操作；"
                "查询类问题不会自动启动临床流程。"
            )
        return (
            "Available tools and capabilities: I can help with the current case's CT and segmentation, Planning, "
            "Dose/DVH, needle and seed geometry, Surgical Guide, and report. "
            "State the object you want to inspect or the operation you want to "
            "run; read-only questions do not start a clinical workflow."
        )

    def _unmatched_turn_response(self, message: str = "", lang: Optional[str] = None) -> str:
        """Return a safe, same-language response when no reliable route exists."""
        response_lang = self._response_language(lang)
        if self._is_explicit_capability_request(message):
            return self._capability_response(response_lang)
        if response_lang == "zh":
            return (
                "我没有可靠识别出这条请求的具体目标。为避免误执行，本次没有启动任何临床操作，"
                "也没有根据关键词擅自执行规划。请明确说明要查询或执行的对象；"
                "如果是当前 Session 查询，请说明要查看 Planning、Dose/DVH、针道、粒子或手术导板。"
            )
        return (
            "I could not reliably identify the target of this request. To avoid an unintended action, "
            "no clinical operation was started and no planning was inferred from keywords. "
            "Please specify the object or operation; for a current-Session query, mention Planning, "
            "Dose/DVH, needles, seeds, or the Surgical Guide."
        )

    def _no_provider_fallback_response(self, message: str = "", lang: Optional[str] = None) -> str:
        """Explain an unavailable provider without returning an unrelated menu."""
        response_lang = self._response_language(lang)
        if self._is_explicit_capability_request(message):
            return self._capability_response(response_lang)
        if response_lang == "zh":
            return (
                "AI 语言服务当前不可用，我无法可靠理解或回答这条请求。为避免误执行，"
                "本次没有启动任何临床操作。请检查 LLM provider 配置后重试；"
                "如果是当前 Session 查询，请明确说明要查看 Planning、Dose/DVH、针道、粒子或手术导板。"
            )
        return (
            "The AI language service is currently unavailable, so I cannot reliably interpret or answer "
            "this request. To avoid an unintended action, no clinical operation was started. "
            "Check the LLM provider configuration and retry; for a current-Session query, specify "
            "Planning, Dose/DVH, needles, seeds, or the Surgical Guide."
        )

    def _normalize_user_facing_response(self, message: str, response: Any) -> Any:
        """Block the legacy unrelated menu and keep its explicit-help form localized."""
        if self._is_generic_capability_menu(response):
            if self._is_explicit_capability_request(message):
                return self._capability_response(self._response_language())
            return self._unmatched_turn_response(message)
        return response

    @staticmethod
    def _is_llm_provider_error(response: Any) -> bool:
        """Identify provider/runtime failures that must not leak into chat output.

        Tool failures are handled by their normal tool-result path. This guard is
        intentionally limited to strings returned by the LLM orchestration layer.
        Detailed provider diagnostics remain in server logs.
        """
        text = str(response or "").strip().lower()
        if not text:
            return False
        return text.startswith(("error:", "llm error:")) or any(
            marker in text
            for marker in (
                "all providers failed",
                "no llm provider available",
                "invalid api key",
                "authentication failed",
                "unauthorized",
            )
        )

    def _run_lightweight_conversation_stream(self, message, steps, step_id_ref, yield_event):
        """Single-shot conversational answer for low-risk chat intents.

        Small-talk turns (greetings, thanks, self-description, simple chit-chat)
        do not need the clinical function-calling pipeline: that path serializes
        every tool schema, renders the multi-thousand-token clinical system
        prompt, injects runtime context, and loops up to N LLM rounds. A plain
        casual greeting therefore used to wait ~30s for a response.

        This method performs one non-tool LLM call with a minimal prompt, so
        conversational intents complete in a couple of seconds. It is a
        structural optimization keyed on the *intent category* produced by
        turn_policy.classify_local_turn (any small_talk turn), not on a
        whitelist of greeting keywords.

        Yields the same events as _run_llm_function_calling_stream (one
        "LLM Call" thinking step, then a final "_result" dict) so the caller
        in chat_with_stream does not need a second code path.
        """
        import asyncio
        router = getattr(self, "brain_router", None)
        if router is None:
            yield {
                "type": "_result",
                "response": self._current_llm_unavailable_message(),
                "llm_meta": {"usage": {}, "latency_ms": 0, "llm_calls": 0},
            }
            return

        step_id_ref[0] += 1
        thinking_step = {
            "id": step_id_ref[0],
            "type": "thinking",
            "title": "LLM Call 1",
            "content": "Waiting for AI response...",
            "status": "pending",
        }
        steps.append(thinking_step)
        yield yield_event("step", thinking_step)

        try:
            # Minimal prompt: a short persona + the recent exchange. No tool
            # schemas, no clinical context modules, no runtime state injection.
            lang_clause = ""
            try:
                from memory.language import detect as _lang_detect, system_prompt_clause as _lang_clause
                # The global UI locale controls static controls and reports;
                # it must not override the language of a user conversation.
                # A Chinese request in an English UI still needs a Chinese
                # reply and Execution Trace.
                _lang_info = _lang_detect(message)
                lang_clause = "\n" + _lang_clause(_lang_info) + "\n"
            except Exception as _e:
                logger.debug("Lightweight language detection skipped: %s", _e)

            system_prompt = (
                "You are BrachyBot, a concise, helpful clinical AI assistant for "
                "radioactive-seed brachytherapy treatment planning. The user is "
                "chatting casually; answer briefly and naturally in the user's "
                "language. Do not invent tools, files, or clinical results that "
                "do not exist."
                + lang_clause
            )

            messages = [{"role": "system", "content": system_prompt}]
            history = list(getattr(self.memory, "conversation", None) or [])[-8:]
            for entry in history:
                content = entry.get("content", "")
                if isinstance(content, str):
                    content = re.sub(r'\[Called [^\]]+\]', '', content).strip()
                    content = re.sub(r'\[Tool result: [^\]]*\]', '', content).strip()
                if not content:
                    continue
                messages.append({"role": entry.get("role", "user"), "content": content})

            try:
                if callable(getattr(self, '_pack_context_for_provider', None)):
                    messages = self._pack_context_for_provider(messages, message)
            except Exception as _p:
                logger.debug("Lightweight context packing skipped: %s", _p)
            call_start = time.perf_counter()
            response = router.chat_messages(messages=messages, tools=None, task_type="general")
            latency_ms = round((time.perf_counter() - call_start) * 1000, 1)
            content = response.content or ""
            finish_reason = getattr(response, "finish_reason", "") or ""
            if hasattr(response, "usage") and response.usage:
                usage = dict(response.usage)
            else:
                usage = {}
            thinking_step["status"] = "done"
            thinking_step["content"] = "Response generated"
            yield yield_event("step", thinking_step)
            # Providers may return a graceful error instead of raising. Keep
            # technical details in logs; raw credentials/endpoints/errors do
            # not belong in the user-facing chat stream.
            if finish_reason == "error" or content.startswith("Error:"):
                logger.warning("Lightweight LLM provider failure: %s", content[:500])
                thinking_step["status"] = "error"
                thinking_step["content"] = "AI language service unavailable"
                content = self._current_llm_unavailable_message()
            yield {
                "type": "_result",
                "response": content,
                "llm_meta": {
                    "usage": usage,
                    "latency_ms": latency_ms,
                    "llm_calls": 1,
                    "route": "lightweight_conversation",
                },
            }
        except Exception as e:
            # A conversational turn never needs the tool-calling pipeline, so
            # on failure do not re-enter the heavy path. The full technical
            # reason remains in server logs for operators.
            logger.warning("Lightweight conversation failed: %s", e)
            thinking_step["status"] = "error"
            thinking_step["content"] = "AI language service unavailable"
            yield yield_event("step", thinking_step)
            yield {
                "type": "_result",
                "response": self._current_llm_unavailable_message(),
                "llm_meta": {"usage": {}, "latency_ms": 0, "llm_calls": 0},
            }

    def _pending_tumor_site_clarification(self) -> bool:
        """Return whether the previous turn is waiting for a tumor site."""
        try:
            pending = self.memory.retrieve("pending_clarification") or {}
            return isinstance(pending, dict) and pending.get("kind") == "tumor_site"
        except Exception:
            return False

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

    @staticmethod
    def _is_current_oar_count_request(message: str) -> bool:
        """Recognize a live Data Tree count request, not a guideline query."""
        text = str(message or "").strip().lower()
        if re.search(r"(?:guideline|standard|constraint|limit|recommended|clinical)", text):
            return False
        return bool(
            re.search(r"(?:how many|number of|count of)\s+(?:the\s+)?(?:oars?|organs?)", text)
            or re.search(r"(?:oars?|organs?).*(?:how many|how much|number|count)", text)
            or re.search(r"(?:多少|几种|数量|数一下).*(?:oar|危及器官|器官)", text)
            or re.search(r"(?:oar|危及器官|器官).*(?:多少|几种|数量)", text)
        )

    def _build_current_oar_count_response(self, lang: str = "en") -> str:
        """Answer from the current case state without an external tool call."""
        names = self.memory.retrieve("organ_names", {}) or {}
        counts = self.memory.retrieve("organ_counts", {}) or {}
        oar_array = self.memory.retrieve("oar_array")
        if isinstance(names, dict):
            labels = [str(value) for value in names.values() if str(value).strip()]
        elif isinstance(names, (list, tuple, set)):
            labels = [str(value) for value in names if str(value).strip()]
        else:
            labels = []
        labels = list(dict.fromkeys(labels))
        if not labels and isinstance(oar_array, np.ndarray):
            labels = [f"OAR {int(label)}" for label in np.unique(oar_array) if int(label) > 0]
        count = len(labels)
        if count == 0:
            if lang == "zh":
                return "当前病例的 Data Tree 中尚未加载可识别的 OAR 节点。"
            return "No identifiable OAR nodes are currently loaded in this case's Data Tree."
        if lang == "zh":
            detail = "、".join(labels)
            return f"当前病例 Data Tree 中有 {count} 个 OAR 结构。它们是：{detail}。这是当前已加载的分割结果，不是临床指南推荐的 OAR 清单。"
        detail = ", ".join(labels)
        return f"The current case Data Tree contains {count} loaded OAR structures: {detail}. This is the loaded segmentation state, not a guideline-recommended OAR list."

    def _current_image_metadata(self) -> Dict[str, Any]:
        """Build technical metadata from the active Session's loaded CT.

        The viewer and planning pipeline already keep the CT in memory. Read
        that canonical state first so a chat query is fast and cannot inspect
        a stale file from another Session. Only the display-safe file name is
        returned; the absolute workspace path never enters the response.
        """
        image = self.memory.retrieve("ct_image")
        if image is None:
            image = self.memory.retrieve("ct_image_raw")
        ct_data = self.memory.retrieve("ct_data")
        ct_shape = self.memory.retrieve("ct_shape")
        ct_spacing = self.memory.retrieve("ct_spacing")
        ct_origin = self.memory.retrieve("ct_origin")
        ct_direction = self.memory.retrieve("ct_direction")
        ct_path = self.memory.retrieve("ct_path") or self.memory.retrieve("ct_source_path")

        def _numbers(value: Any) -> List[float]:
            if value is None:
                return []
            try:
                return [float(item) for item in value]
            except (TypeError, ValueError):
                return []

        size_xyz: List[int] = []
        spacing_xyz = _numbers(ct_spacing)
        origin_xyz = _numbers(ct_origin)
        direction = _numbers(ct_direction)
        pixel_type = "-"
        components = 1

        if image is not None and hasattr(image, "GetSize"):
            try:
                size_xyz = [int(item) for item in image.GetSize()]
                spacing_xyz = [float(item) for item in image.GetSpacing()]
                origin_xyz = [float(item) for item in image.GetOrigin()]
                direction = [float(item) for item in image.GetDirection()]
                pixel_type = image.GetPixelIDTypeAsString()
                components = int(image.GetNumberOfComponentsPerPixel())
            except Exception as exc:
                logger.debug("Failed to read SimpleITK CT metadata from memory: %s", exc)

        if not size_xyz and isinstance(ct_shape, (list, tuple)):
            try:
                shape_zyx = [int(item) for item in ct_shape]
                size_xyz = list(reversed(shape_zyx))
            except (TypeError, ValueError):
                size_xyz = []

        array = None
        if isinstance(ct_data, np.ndarray):
            array = ct_data
        elif image is not None:
            try:
                array = np.asarray(sitk.GetArrayViewFromImage(image))
            except Exception as exc:
                logger.debug("Failed to read CT voxel statistics from memory: %s", exc)
        if array is not None and array.size and not size_xyz:
            size_xyz = [int(item) for item in reversed(array.shape[-3:])]

        if not size_xyz:
            return {}
        if len(spacing_xyz) < 3:
            spacing_xyz = (spacing_xyz + [1.0, 1.0, 1.0])[:3]
        if len(origin_xyz) < 3:
            origin_xyz = (origin_xyz + [0.0, 0.0, 0.0])[:3]
        if len(direction) != 9:
            direction = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]

        metadata: Dict[str, Any] = {
            "file": os.path.basename(str(ct_path)) if ct_path else "current CT",
            "format": "NIfTI" if str(ct_path).lower().endswith((".nii", ".nii.gz")) else "Image",
            "dimension": len(size_xyz),
            "size_xyz": size_xyz,
            "shape": size_xyz,
            "shape_xyz": size_xyz,
            "array_shape_zyx": list(reversed(size_xyz)),
            "spacing": spacing_xyz,
            "spacing_mm_xyz": spacing_xyz,
            "origin_mm_xyz": origin_xyz,
            "direction": direction,
            "direction_matrix": [direction[index:index + 3] for index in range(0, 9, 3)],
            "coordinate_system": "LPI viewer / SimpleITK physical LPS",
            "pixel_type": pixel_type,
            "components_per_pixel": components,
            "voxel_count": int(np.prod(size_xyz, dtype=np.int64)),
            "physical_extent_mm_xyz": [
                float(size_xyz[index] * spacing_xyz[index]) for index in range(3)
            ],
        }

        if array is not None and array.size:
            try:
                numeric = np.asarray(array)
                finite = (
                    numeric[np.isfinite(numeric)]
                    if np.issubdtype(numeric.dtype, np.inexact)
                    else numeric.reshape(-1)
                )
                if finite.size:
                    metadata.update({
                        "value_min": float(np.min(finite)),
                        "value_max": float(np.max(finite)),
                        "value_mean": float(np.mean(finite, dtype=np.float64)),
                    })
            except (TypeError, ValueError, OverflowError) as exc:
                logger.debug("Failed to summarize current CT voxels: %s", exc)

        for key, memory_key in (
            ("window_center", "ct_window_center"),
            ("window_width", "ct_window_width"),
        ):
            value = self.memory.retrieve(memory_key)
            if value is not None:
                metadata[key] = value
        return metadata

    def _build_current_image_metadata_response(self, lang: str = "en") -> str:
        """Return a localized technical summary of the loaded CT image."""
        metadata = self._current_image_metadata()
        if not metadata:
            if lang == "zh":
                return "\u5f53\u524d Session \u5c1a\u672a\u52a0\u8f7d\u53ef\u8bfb\u53d6\u7684 CT \u56fe\u50cf\u3002\u8bf7\u5148\u5728 Input \u4e2d\u52a0\u8f7d CT \u6587\u4ef6\u3002"
            return "No readable CT image is loaded in the current Session. Load a CT file from Input first."

        # Reuse the same formatter as doc_reader so direct local reads and
        # tool-backed reads have identical fields and language behavior.
        result = SimpleNamespace(
            success=True,
            data={"metadata": metadata},
            metadata=metadata,
            display="",
            message="Current CT metadata loaded",
        )
        return ToolResultPipeline._format_document(result, metadata, lang)

    @staticmethod
    def _dose_fraction(value: Any) -> Optional[float]:
        """Normalize a Vx value to the shared 0..1 planning contract."""
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not np.isfinite(number) or number < 0:
            return None
        if number > 1.0 and number <= 100.0:
            number /= 100.0
        return number if 0.0 <= number <= 1.0 else None

    def _current_dose_metrics(self) -> Dict[str, Any]:
        """Return the newest complete local dose snapshot.

        Planning and direct dose evaluation historically used both ``metrics``
        and ``dose_metrics``. Some older snapshots also wrapped target values
        under ``metrics -> CTV``. Normalize those shapes here so a read-only
        question never needs to call the expensive dose tool again.
        """
        candidates = [
            self.memory.retrieve("metrics") or {},
            self.memory.retrieve("dose_metrics") or {},
        ]
        for raw in candidates:
            if not isinstance(raw, dict) or not raw:
                continue
            data = dict(raw)
            nested = data.get("metrics")
            if isinstance(nested, dict):
                target = nested.get("CTV") or nested.get("ctv")
                if not isinstance(target, dict):
                    for value in nested.values():
                        if isinstance(value, dict) and str(value.get("type", "")).lower() == "target":
                            target = value
                            break
                if isinstance(target, dict):
                    merged = dict(data)
                    merged.update(target)
                    if not merged.get("oar_metrics"):
                        merged["oar_metrics"] = {
                            name: value for name, value in nested.items()
                            if name not in {"CTV", "ctv"} and isinstance(value, dict)
                        }
                    data = merged
            if any(key in data for key in ("v100", "V100", "d90", "D90", "oar_metrics")):
                return data
        return {}

    def _build_current_dose_response(self, lang: str = "en") -> str:
        """Answer a current-dose question from the active case only.

        This intentionally does not consult clinical_kb, web_search, or
        web_fetch. Standards questions remain on the evidence-backed route;
        this method reports the actual dose/DVH snapshot already produced by
        the current planning run.
        """
        metrics = self._current_dose_metrics()
        if not metrics:
            if lang == "zh":
                return (
                    "当前病例还没有可读取的剂量评估结果。请先完成剂量计算和 DVH 评估，"
                    "然后再查询当前剂量。"
                )
            return "No completed dose/DVH result is available for the current case yet. Run dose evaluation before asking for the current dose."

        plan_config = self.memory.retrieve("plan_config") or {}
        try:
            prescription = float(resolve_prescription_gy(plan_config, metrics))
        except Exception:
            prescription = float(
                metrics.get("prescription_gy")
                or metrics.get("prescribed_dose")
                or DEFAULT_PRESCRIPTION_GY
            )

        def number(*keys: str) -> Optional[float]:
            for key in keys:
                value = metrics.get(key)
                if value is not None:
                    try:
                        value = float(value)
                    except (TypeError, ValueError):
                        continue
                    if np.isfinite(value):
                        return value
            return None

        v100 = self._dose_fraction(metrics.get("v100", metrics.get("V100")))
        v150 = self._dose_fraction(metrics.get("v150", metrics.get("V150")))
        v200 = self._dose_fraction(metrics.get("v200", metrics.get("V200")))
        d90 = number("d90", "D90")
        d95 = number("d95", "D95")
        dmean = number("dmean", "Dmean", "mean_dose")
        d2 = number("d2", "D2", "d2cc", "D2cc")
        dmax = number("dmax", "Dmax", "max_dose")
        ci = number("ci", "CI")
        hi = number("hi", "HI")
        score = number("plan_score", "score")

        def fmt(value: Optional[float], suffix: str = "", digits: int = 2) -> str:
            return f"{value:.{digits}f}{suffix}" if value is not None else "未提供"

        oar_metrics = metrics.get("oar_metrics") or {}
        ranked_oars = []
        if isinstance(oar_metrics, dict):
            for name, item in oar_metrics.items():
                if not isinstance(item, dict):
                    continue
                dmax = item.get("dmax", item.get("max_dose"))
                d2cc = item.get("d2cc", item.get("D2cc"))
                try:
                    dmax_value = float(dmax) if dmax is not None else None
                except (TypeError, ValueError):
                    dmax_value = None
                try:
                    d2cc_value = float(d2cc) if d2cc is not None else None
                except (TypeError, ValueError):
                    d2cc_value = None
                if dmax_value is None and d2cc_value is None:
                    continue
                ranked_oars.append((
                    max(dmax_value or 0.0, d2cc_value or 0.0),
                    str(name).replace("_", " "),
                    dmax_value,
                    d2cc_value,
                ))
        ranked_oars.sort(key=lambda item: item[0], reverse=True)

        if lang == "zh":
            v100_text = fmt(v100 * 100 if v100 is not None else None, "%", 1)
            v150_text = fmt(v150 * 100 if v150 is not None else None, "%", 1)
            v200_text = fmt(v200 * 100 if v200 is not None else None, "%", 1)
            ci_text = fmt(ci, "", 3)
            hi_text = fmt(hi, "", 3)
            score_text = fmt(score, "/100", 0)
            lines = [
                "## 当前病例剂量结果",
                "",
                "以下内容直接读取当前 Session 已保存的剂量和 DVH 结果。",
                "",
                "### CTV 剂量指标",
                "",
                f"- 处方剂量：{prescription:.1f} Gy",
                f"- V100 / V150 / V200：{v100_text} / {v150_text} / {v200_text}",
                f"- D90 / Dmean / D2：{fmt(d90)} / {fmt(dmean)} / {fmt(d2)} Gy",
                f"- CI / HI：{ci_text} / {hi_text}",
                f"- 计划评分：{score_text}",
            ]
            if d95 is not None:
                lines.insert(-2, f"- D95：{fmt(d95)} Gy")
            if dmax is not None:
                lines.insert(-2, f"- Dmax：{fmt(dmax)} Gy")
            if ranked_oars:
                lines.extend([
                    "",
                    "### 当前 OAR 剂量较高的结构",
                    "",
                    "| 结构 | Dmax (Gy) | D2cc (Gy) |",
                    "|---|---:|---:|",
                ])
                for _, name, dmax_value, d2cc_value in ranked_oars[:5]:
                    lines.append(
                        f"| {name} | {fmt(dmax_value)} | {fmt(d2cc_value)} |"
                    )
            lines.extend(["", "### 当前结果解读", ""])
            if v100 is not None:
                lines.append(f"- CTV 的 V100 为 {v100 * 100:.1f}%，可直接作为当前覆盖情况的主要指标。")
            if v200 is not None and v200 >= 0.30:
                lines.append(f"- V200 为 {v200 * 100:.1f}%，且 D2 为 {fmt(d2)} Gy；建议在 2D/3D Viewer 中检查热点区域，并确认是否需要重新优化。")
            elif d90 is not None:
                lines.append(f"- D90 为 {d90:.2f} Gy；建议结合处方剂量、DVH 和 OAR 结果进行最终审核。")
            lines.append("- 如需查询部位特异性的剂量标准或 OAR 限值，请单独提出“指南/标准/限值”查询；那会走证据检索流程。")
            return "\n".join(lines)

        lines = [
            "## Current Case Dose Results",
            "",
            "Read directly from the dose/DVH snapshot saved in the active session.",
            "",
            "### CTV dose metrics",
            "",
            f"- Prescription: {prescription:.1f} Gy",
            f"- V100 / V150 / V200: {fmt(v100 * 100 if v100 is not None else None, '%', 1)} / {fmt(v150 * 100 if v150 is not None else None, '%', 1)} / {fmt(v200 * 100 if v200 is not None else None, '%', 1)}",
            f"- D90 / Dmean / D2: {fmt(d90)} / {fmt(dmean)} / {fmt(d2)} Gy",
            f"- CI / HI: {fmt(ci, '', 3)} / {fmt(hi, '', 3)}",
            f"- Plan score: {fmt(score, '/100', 0)}",
        ]
        if d95 is not None:
            lines.insert(-2, f"- D95: {fmt(d95)} Gy")
        if dmax is not None:
            lines.insert(-2, f"- Dmax: {fmt(dmax)} Gy")
        if ranked_oars:
            lines.extend(["", "### Highest current OAR dose structures", "", "| Structure | Dmax (Gy) | D2cc (Gy) |", "|---|---:|---:|"])
            for _, name, dmax_value, d2cc_value in ranked_oars[:5]:
                lines.append(f"| {name} | {fmt(dmax_value)} | {fmt(d2cc_value)} |")
        lines.extend(["", "### Interpretation", ""])
        if v100 is not None:
            lines.append(f"- CTV V100 is {v100 * 100:.1f}%, the main current coverage indicator.")
        if v200 is not None and v200 >= 0.30:
            lines.append(f"- V200 is {v200 * 100:.1f}% and D2 is {fmt(d2)} Gy; inspect the hotspot in the 2D/3D Viewer before final approval.")
        elif d90 is not None:
            lines.append(f"- D90 is {d90:.2f} Gy; review it together with the prescription, DVH, and OAR results.")
        lines.append("- Ask separately for site-specific dose standards or OAR limits when an evidence lookup is intended.")
        return "\n".join(lines)

    def _build_current_planning_provenance_response(self, lang: str = "en") -> str:
        """Explain which persisted Planning supplied the current calculation.

        This is deliberately a local read. It does not ask the LLM to infer a
        Planning label from conversation text and it never starts planning,
        dose, segmentation, or review work.
        """
        response_lang = self._response_language(lang)
        try:
            from web.planning_runs import current_planning_context

            context = current_planning_context(self.memory)
        except Exception as exc:
            logger.exception("Failed to read current Planning provenance")
            if response_lang == "zh":
                return f"当前 Session 的 Planning 来源暂时无法读取，因此我不能可靠确认本次计算依据哪次规划（{exc}）。"
            return f"The current Session's Planning provenance could not be read, so I cannot reliably identify the source Planning ({exc})."

        planning_id = str(context.get("planning_id") or "").strip()
        if not planning_id:
            if response_lang == "zh":
                return "当前 Session 没有可识别的激活 Planning，也没有足够的持久化信息确认本次计算依据哪次规划。"
            return "The current Session has no identifiable active Planning and not enough persisted information to confirm which Planning was used."

        provenance = context.get("dose_recompute_provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        label = str(
            provenance.get("planning_label")
            or context.get("label")
            or planning_id
        )
        status = str(
            provenance.get("planning_status")
            or context.get("status")
            or "unknown"
        )
        seed_count = provenance.get("total_seeds") or context.get("total_seeds") or 0
        needle_count = provenance.get("num_trajectories") or context.get("num_trajectories") or 0
        try:
            seed_count = int(seed_count)
        except (TypeError, ValueError):
            seed_count = 0
        try:
            needle_count = int(needle_count)
        except (TypeError, ValueError):
            needle_count = 0
        source = str(provenance.get("source") or context.get("source") or "unknown")
        source_text = {
            "active_planning_run": "active Planning run snapshot",
            "legacy_active_aliases": "legacy active Session aliases",
        }.get(source, source)
        status_text_zh = {
            "completed": "已完成",
            "running": "执行中",
            "draft": "草稿",
            "failed": "失败",
            "cancelled": "已取消",
        }.get(status, status)

        if response_lang == "zh":
            lines = [
                "## 本次剂量/DVH计算的依据",
                "",
                f"本次计算依据的是 **{label}**（Planning ID：`{planning_id}`）。",
                f"- Planning 状态：{status_text_zh}",
                f"- 规划几何：{needle_count} 个针道、{seed_count} 个粒子。",
                f"- 持久化来源：{source_text}。",
            ]
            if provenance:
                lines.extend([
                    "- 计算边界：读取该 Planning 已保存的针道和粒子位置，仅重新计算 Dose/DVH；"
                    "没有重新进行分割、重新选择针道，也没有重新运行完整 Planning pipeline。",
                ])
            else:
                lines.extend([
                    "- 当前 Session 没有保存这次重算的独立审计记录；上面的 Planning 身份和数量是当前可核验的持久化状态。",
                    "- 因此不能仅凭当前快照额外断言当时是否重新分割或重新选择针道。",
                ])
            return "\n".join(lines)

        lines = [
            "## Planning used for this Dose/DVH calculation",
            "",
            f"This calculation used **{label}** (Planning ID: `{planning_id}`).",
            f"- Planning status: {status}",
            f"- Planning geometry: {needle_count} needles and {seed_count} seeds.",
            f"- Persisted source: {source_text}.",
        ]
        if provenance:
            lines.append(
                "- Calculation boundary: the saved Needle/Seed geometry from this Planning was used to recompute Dose/DVH; segmentation, needle selection, and the full Planning pipeline were not rerun."
            )
        else:
            lines.extend([
                "- The Session does not contain a separate audit record for that recomputation; the Planning identity and counts above are the currently verifiable persisted state.",
                "- The current snapshot alone cannot establish whether segmentation or needle selection was rerun at that time.",
            ])
        return "\n".join(lines)

    @staticmethod
    def _session_content_response(target: str, lang: str = "en") -> str:
        """Return a localized acknowledgement for a browser content bridge.

        The browser resolves the command against the active Session and may
        attach persisted figures or open the matching panel. This text is
        deliberately factual: it does not claim that an artifact exists until
        the browser has verified it.
        """
        target = str(target or "session_summary")
        zh = {
            "report_figures": "\u6b63\u5728\u5448\u73b0\u5f53\u524d\u62a5\u544a\u4e2d\u5df2\u4fdd\u5b58\u7684\u622a\u56fe\u3002",
            "report": "\u6b63\u5728\u6253\u5f00\u5f53\u524d\u62a5\u544a\u5e76\u5448\u73b0\u5176\u5df2\u4fdd\u5b58\u9644\u4ef6\u3002",
            "session_screenshots": "\u6b63\u5728\u5448\u73b0\u5f53\u524d Session \u4e2d\u5df2\u4fdd\u5b58\u7684\u622a\u56fe\u3002",
            "reply_attachments": "\u6b63\u5728\u5448\u73b0\u4e0a\u4e00\u6761\u53ef\u89c1\u56de\u590d\u4e2d\u7684\u56fe\u50cf\u9644\u4ef6\u3002",
            "planning": "\u6b63\u5728\u5448\u73b0\u5f53\u524d\u89c4\u5212\u7ed3\u679c\u3002",
            "dose": "\u6b63\u5728\u5448\u73b0\u5f53\u524d\u5242\u91cf\u7ed3\u679c\u3002",
            "dvh": "\u6b63\u5728\u5448\u73b0\u5f53\u524d DVH \u6570\u636e\u3002",
            "metrics": "\u6b63\u5728\u5448\u73b0\u5f53\u524d\u89c4\u5212\u6307\u6807\u3002",
            "ct": "\u6b63\u5728\u5448\u73b0\u5f53\u524d CT \u56fe\u50cf\u548c\u5143\u6570\u636e\u3002",
            "structures": "\u6b63\u5728\u5448\u73b0\u5f53\u524d\u7ed3\u6784\u548c\u5206\u5272\u7ed3\u679c\u3002",
            "surgical_guide": "\u6b63\u5728\u5448\u73b0\u5f53\u524d\u624b\u672f\u5bfc\u677f\u3002",
            "data_tree": "\u6b63\u5728\u5448\u73b0\u5f53\u524d Session \u7684 Data Tree\u3002",
            "chat_history": "\u6b63\u5728\u5448\u73b0\u5f53\u524d Session \u7684\u5bf9\u8bdd\u5386\u53f2\u3002",
            "artifact": "\u6b63\u5728\u5448\u73b0\u5f53\u524d Session \u4e2d\u9009\u62e9\u7684\u6570\u636e\u5bf9\u8c61\u3002",
        }
        en = {
            "report_figures": "Presenting the saved figures from the current report.",
            "report": "Opening the current report and presenting its saved attachments.",
            "session_screenshots": "Presenting saved screenshots from the current Session.",
            "reply_attachments": "Presenting the image attachments from the most recent visible reply.",
            "planning": "Presenting the current planning result.",
            "dose": "Presenting the current dose result.",
            "dvh": "Presenting the current DVH data.",
            "metrics": "Presenting the current planning metrics.",
            "ct": "Presenting the loaded CT image and metadata.",
            "structures": "Presenting the current structures and segmentation results.",
            "surgical_guide": "Presenting the current Surgical Guide.",
            "data_tree": "Presenting the current Session Data Tree.",
            "chat_history": "Presenting the current Session conversation history.",
            "artifact": "Presenting the selected data object from the current Session.",
        }
        return (zh if lang == "zh" else en).get(
            target,
            "\u6b63\u5728\u5448\u73b0\u5f53\u524d Session \u4e2d\u53ef\u8bbf\u95ee\u7684\u5185\u5bb9\u3002"
            if lang == "zh"
            else "Presenting the accessible content in the current Session.",
        )

    @staticmethod
    def _report_generation_params() -> Dict[str, Any]:
        """Build the single browser action that owns full report generation.

        ``report.autofill`` runs the real Report pipeline in the browser: it
        reads current Session/planning data, applies the server patch, rebuilds
        quality rows, captures canonical figures, renders, and persists the
        result.  Do not replace it with ``ui_content(report)``, which is a
        read-only presentation capability.
        """
        return {
            "actions": [{"target": "report.autofill", "command": "run"}],
        }

    @staticmethod
    def _report_generation_response(lang: str = "en", success: bool = True) -> str:
        if success:
            return (
                "\u5df2\u6839\u636e\u5f53\u524d Session \u7684 CT\u3001\u5206\u5272\u3001\u89c4\u5212\u3001\u5242\u91cf\u548c DVH \u7ed3\u679c\u91cd\u65b0\u751f\u6210\u62a5\u544a\u3002"
                "\u62a5\u544a\u6b63\u6587\u3001\u8868\u683c\u3001Reference/Status \u8bc4\u4f30\u548c\u6807\u51c6\u56fe\u4ef6\u5df2\u540c\u6b65\u66f4\u65b0\u5e76\u4fdd\u5b58\u3002"
                if lang == "zh"
                else "The report has been regenerated from the current Session's CT, segmentation, planning, dose, and DVH results. Report text, tables, Reference/Status assessment, and canonical figures were updated and saved together."
            )
        return (
            "\u5f53\u524d Session \u7684\u62a5\u544a\u751f\u6210\u64cd\u4f5c\u672a\u80fd\u542f\u52a8\u3002\u8bf7\u786e\u8ba4\u8be5 Session \u5df2\u5b8c\u6210\u52a0\u8f7d\u4e14\u5df2\u6709\u53ef\u7528\u7684\u89c4\u5212\u7ed3\u679c\u540e\u91cd\u8bd5\u3002"
            if lang == "zh"
            else "Report generation could not be started for the current Session. Confirm that the Session is fully loaded and has an available planning result, then retry."
        )

    @staticmethod
    def _viewer_display_params() -> Dict[str, Any]:
        """Build the typed, display-only command for the active planning run."""
        return {
            "actions": [{
                "target": "viewer.refresh_planning",
                "command": "run",
            }],
        }

    @staticmethod
    def _viewer_display_response(lang: str = "en", success: bool = True) -> str:
        """Acknowledge Viewer refresh without claiming a new clinical run."""
        if success:
            return (
                "已从当前 Session 发起规划结果刷新，并将在 Viewer 中显示可用的粒子、针道、剂量/等剂量面、DVH 和手术导板等结果；不会重新运行规划或重新计算剂量。"
                if lang == "zh"
                else "A refresh of the saved planning result was started for the current Session. The Viewer will present available seeds, needles, dose/isodose surfaces, DVH, and surgical-guide results; planning and dose computation will not be rerun."
            )
        return (
            "当前 Session 的规划结果未能发起 Viewer 刷新。请先确认病例已经完成加载并存在可用的规划结果。"
            if lang == "zh"
            else "The Viewer refresh could not be started for the current Session. Confirm that the case has finished loading and contains an available planning result."
        )

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
        # Every chat turn receives a fresh authorization ledger.  Workflow
        # recovery and tool normalization must use this ledger instead of
        # re-reading keywords from the raw user message.
        authorization = TurnExecutionAuthorization(token)
        self._turn_execution_authorization = authorization
        local.authorization = authorization
        ledgers = getattr(self, "_turn_execution_authorizations", None)
        if not isinstance(ledgers, dict):
            ledgers = {}
            self._turn_execution_authorizations = ledgers
        ledgers[token] = authorization
        # Retain a small diagnostic window without allowing an unbounded
        # per-Agent history to accumulate across a long-lived Session.
        for old_token in sorted(ledgers)[:-8]:
            ledgers.pop(old_token, None)
        ledger = getattr(self, "run_ledger", None)
        if ledger is not None:
            ledger.begin(message)
        return token

    def _activate_turn_policy(self, policy) -> None:
        """Install a routing hint and its explicit fast-path grants."""
        self._active_turn_policy = policy
        authorization = self._current_execution_authorization()
        if authorization is not None:
            authorization.grant_policy(policy)
            action_plan = getattr(policy, "action_plan", None)
            if action_plan is not None:
                authorization.set_action_plan(action_plan, source="local_action_plan")
                ledger = getattr(self, "run_ledger", None)
                if ledger is not None and action_plan.steps:
                    ledger.transition(
                        RunStatus.REASONING,
                        "action.plan.created",
                        action_plan=authorization.action_plan.to_dict(),
                    )

    def _current_execution_authorization(self):
        """Return the authorization ledger owned by the calling turn."""
        local = getattr(self, "_turn_local", None)
        authorization = getattr(local, "authorization", None) if local is not None else None
        if authorization is not None:
            return authorization
        token = self._current_turn_token()
        ledgers = getattr(self, "_turn_execution_authorizations", None)
        if isinstance(ledgers, dict) and token in ledgers:
            return ledgers[token]
        fallback = getattr(self, "_turn_execution_authorization", None)
        return fallback if getattr(fallback, "token", token) == token else None

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
        turn_context = getattr(self, "_active_turn_context", {}) or {}
        internal_followup = bool(turn_context.get("internal_followup"))
        inherited_language = (
            self._internal_followup_language(turn_context)
            if internal_followup
            else ""
        )
        if not internal_followup:
            self._purge_orphaned_visual_context()
        self._begin_turn(message)
        # Hidden screenshot-analysis prompts are execution context, not a new
        # user turn. Persisting their raw URL markers into conversation memory
        # lets a later question inherit the previous screenshot task.
        if not internal_followup:
            self.memory.add_message("user", message)
        if inherited_language:
            self.memory.user_lang = inherited_language
        else:
            try:
                from memory.language import detect as _detect_turn_language
                _language = _detect_turn_language(message)
                self.memory.user_lang = "zh" if _language.get("code") == "zh" else "en"
            except Exception:
                self.memory.user_lang = "zh" if re.search(r'[\u4e00-\u9fff]', message) else "en"
        self._active_trace_language = self.memory.user_lang

        # A current-case result question is a local read-only data query.
        # Resolve it before the enhanced agent and generic LLM router so it
        # cannot trigger clinical_kb/web_fetch or an unnecessary second LLM.
        local_policy = (
            visual_analysis_policy()
            if internal_followup
            else classify_local_turn(
                message,
                pending_tumor_site=self._pending_tumor_site_clarification(),
            )
        )
        self._activate_turn_policy(local_policy)
        if local_policy.intent == "planning_provenance_query":
            response = self._build_current_planning_provenance_response(self.memory.user_lang)
            self.memory.add_message("assistant", response)
            self._record_experience(message, response)
            self._finish_turn(response)
            return response

        if local_policy.intent == "case_dose_query":
            response = self._build_current_dose_response(self.memory.user_lang)
            self.memory.add_message("assistant", response)
            self._record_experience(message, response)
            self._finish_turn(response)
            return response

        if local_policy.intent == "image_metadata_query":
            response = self._build_current_image_metadata_response(self.memory.user_lang)
            self.memory.add_message("assistant", response)
            self._record_experience(message, response)
            self._finish_turn(response)
            return response

        if local_policy.intent == "report_generation" and local_policy.direct_execution:
            try:
                result = self._execute_tool_with_memory(
                    "ui_controller", self._report_generation_params(),
                )
                success = bool(result.success)
            except Exception:
                logger.exception("Report-generation UI action construction failed")
                success = False
            response = self._report_generation_response(self.memory.user_lang, success)
            self.memory.add_message("assistant", response)
            self._record_experience(message, response)
            self._finish_turn(response)
            return response

        if local_policy.intent == "viewer_display" and local_policy.direct_execution:
            params = self._viewer_display_params()
            try:
                result = self._execute_tool_with_memory("ui_controller", params)
                success = bool(result.success)
            except Exception:
                logger.exception("Viewer planning refresh action failed")
                success = False
            response = self._viewer_display_response(self.memory.user_lang, success)
            self.memory.add_message("assistant", response)
            self._record_experience(message, response)
            self._finish_turn(response)
            return response

        if not internal_followup and local_policy.intent == "session_content_query":
            target = resolve_session_content_target(message) or "session_summary"
            response = self._session_content_response(target, self.memory.user_lang)
            self.memory.add_message("assistant", response)
            self._record_experience(message, response)
            self._finish_turn(response)
            return response

        if self.enhanced and not internal_followup:
            self.enhanced.pre_task_hook(message)

        if self.brain_available:
            _result = self._run_llm_function_calling(message, [], [0])
            response = _result[0] if isinstance(_result, tuple) else _result
            if self._is_llm_provider_error(response):
                logger.warning("LLM provider failure suppressed from non-trace chat output: %s", str(response)[:500])
                response = self._current_llm_unavailable_message()
        else:
            # The non-trace API is still used by a few integrations. Keep its
            # behavior aligned with chat_with_trace/stream: a conversational
            # request must never receive a fabricated keyword-bot greeting
            # merely because the configured provider is unavailable.
            if local_policy.intent == "small_talk":
                response = self._current_llm_unavailable_message()
            elif local_policy.direct_execution:
                response = self._rule_based_chat(message)
            else:
                # A semantic/knowledge turn is not authorized for keyword
                # execution. In particular, a question mentioning "Planning"
                # must not start a new plan when the provider is unavailable.
                response = self._no_provider_fallback_response(message)

        response = self._normalize_user_facing_response(message, response)

        if not internal_followup:
            self._record_experience(message, response)

        if self.enhanced and not internal_followup:
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
        turn_context = getattr(self, "_active_turn_context", {}) or {}
        internal_followup = bool(turn_context.get("internal_followup"))
        inherited_language = (
            self._internal_followup_language(turn_context)
            if internal_followup
            else ""
        )
        if not internal_followup:
            self._purge_orphaned_visual_context()
        self._begin_turn(message)
        if not internal_followup:
            self.memory.add_message("user", message)
        if inherited_language:
            self.memory.user_lang = inherited_language
        else:
            try:
                from memory.language import detect as _detect_turn_language
                _language = _detect_turn_language(message)
                self.memory.user_lang = "zh" if _language.get("code") == "zh" else "en"
            except Exception:
                self.memory.user_lang = "zh" if re.search(r'[一-鿿]', message) else "en"
        self._active_trace_language = self.memory.user_lang
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

        # Keep the non-streaming compatibility path subject to the same
        # hidden-child boundary as the SSE path.  A visual-analysis prompt is
        # transport context, never a second user message or Trace row.
        if not internal_followup:
            add_step("user", "User Input", message)

        # Local classification only controls expensive routing/review/tool
        # policy. The configured LLM still generates the user-facing answer,
        # including greetings and self-description requests.
        local_policy = (
            visual_analysis_policy()
            if internal_followup
            else classify_local_turn(
                message,
                pending_tumor_site=self._pending_tumor_site_clarification(),
            )
        )
        self._activate_turn_policy(local_policy)

        if local_policy.intent == "planning_provenance_query":
            add_step(
                "ui",
                "\u672c\u6b21\u89c4\u5212\u6765\u6e90" if self.memory.user_lang == "zh" else "Current Planning Provenance",
                "\u6b63\u5728\u8bfb\u53d6\u5f53\u524d\u6fc0\u6d3b Planning \u53ca\u672c\u6b21\u91cd\u7b97\u7684\u6765\u6e90..."
                if self.memory.user_lang == "zh"
                else "Reading the active Planning and the source recorded for this recomputation...",
                status="done",
            )
            response = self._build_current_planning_provenance_response(self.memory.user_lang)
            self.memory.add_message("assistant", response)
            self._record_experience(message, response, steps)
            self._finish_turn(response)
            return {
                "response": response,
                "steps": steps,
                "llm_meta": {"usage": {}, "latency_ms": 0, "llm_calls": 0, "route": "local_planning_provenance"},
            }

        if local_policy.intent == "case_dose_query":
            title = "当前病例剂量" if self.memory.user_lang == "zh" else "Current Case Dose"
            content = (
                "正在读取当前 Session 已保存的剂量和 DVH 结果..."
                if self.memory.user_lang == "zh"
                else "Reading the saved dose and DVH results from the active case..."
            )
            add_step("ui", title, content, status="done")
            response = self._build_current_dose_response(self.memory.user_lang)
            self.memory.add_message("assistant", response)
            self._record_experience(message, response, steps)
            self._finish_turn(response)
            return {
                "response": response,
                "steps": steps,
                "llm_meta": {"usage": {}, "latency_ms": 0, "llm_calls": 0, "route": "local_case_dose"},
            }

        if local_policy.intent == "image_metadata_query":
            title = "\u5f53\u524d CT \u5143\u6570\u636e" if self.memory.user_lang == "zh" else "Current CT Metadata"
            content = (
                "\u6b63\u5728\u8bfb\u53d6\u5f53\u524d Session \u4e2d\u5df2\u52a0\u8f7d\u7684 CT \u6280\u672f\u4fe1\u606f..."
                if self.memory.user_lang == "zh"
                else "Reading technical metadata from the CT loaded in the active Session..."
            )
            add_step("ui", title, content, status="done")
            response = self._build_current_image_metadata_response(self.memory.user_lang)
            self.memory.add_message("assistant", response)
            self._record_experience(message, response, steps)
            self._finish_turn(response)
            return {
                "response": response,
                "steps": steps,
                "llm_meta": {"usage": {}, "latency_ms": 0, "llm_calls": 0, "route": "local_image_metadata"},
            }

        if local_policy.intent == "report_generation" and local_policy.direct_execution:
            title = "\u91cd\u65b0\u751f\u6210\u62a5\u544a" if self.memory.user_lang == "zh" else "Regenerate Report"
            params = self._report_generation_params()
            add_step(
                "tool", title,
                "\u6b63\u5728\u6839\u636e\u5f53\u524d Session \u7ed3\u679c\u66f4\u65b0\u62a5\u544a..."
                if self.memory.user_lang == "zh"
                else "Updating the report from the current Session results...",
                status="pending", tool="ui_controller", params=params,
            )
            try:
                result = self._execute_tool_with_memory("ui_controller", params)
                steps[-1]["status"] = "done" if result.success else "error"
                steps[-1]["result"] = ToolResultPipeline.format(
                    "ui_controller", result, self.memory.user_lang,
                )
                steps[-1]["metadata"] = ToolResultPipeline.trace_metadata(
                    "ui_controller", dict(getattr(result, "metadata", {}) or {}),
                ) if result.success else {}
                success = bool(result.success)
            except Exception:
                logger.exception("Report-generation UI action construction failed")
                steps[-1]["status"] = "error"
                steps[-1]["content"] = ""
                success = False
            response = self._report_generation_response(self.memory.user_lang, success)
            self.memory.add_message("assistant", response)
            self._record_experience(message, response, steps)
            self._finish_turn(response)
            return {
                "response": response,
                "steps": steps,
                "llm_meta": {"usage": {}, "latency_ms": 0, "llm_calls": 0, "route": "local_report_generation"},
            }

        if local_policy.intent == "viewer_display" and local_policy.direct_execution:
            params = self._viewer_display_params()
            add_step(
                "tool",
                "刷新 Viewer 中的规划结果" if self.memory.user_lang == "zh" else "Refresh Planning Results in Viewer",
                "正在从当前 Session 读取已保存的规划结果..."
                if self.memory.user_lang == "zh"
                else "Reading the saved planning result from the current Session...",
                status="pending",
                tool="ui_controller",
                params=params,
            )
            try:
                result = self._execute_tool_with_memory("ui_controller", params)
                steps[-1]["status"] = "done" if result.success else "error"
                steps[-1]["content"] = ""
                steps[-1]["result"] = ToolResultPipeline.format(
                    "ui_controller", result, self.memory.user_lang,
                )
                steps[-1]["metadata"] = ToolResultPipeline.trace_metadata(
                    "ui_controller", dict(getattr(result, "metadata", {}) or {}),
                ) if result.success else {}
                success = bool(result.success)
            except Exception:
                logger.exception("Viewer planning refresh action failed")
                steps[-1]["status"] = "error"
                steps[-1]["content"] = ""
                steps[-1]["result"] = ""
                steps[-1]["metadata"] = {}
                success = False
            response = self._viewer_display_response(self.memory.user_lang, success)
            self.memory.add_message("assistant", response)
            self._record_experience(message, response, steps)
            self._finish_turn(response)
            return {
                "response": response,
                "steps": steps,
                "llm_meta": {"usage": {}, "latency_ms": 0, "llm_calls": 0, "route": "local_viewer_display"},
            }

        if not internal_followup and local_policy.intent == "session_content_query":
            target = resolve_session_content_target(message) or "session_summary"
            from tool_factory.ui_content import normalize_session_content_request

            content_contract = normalize_session_content_request(
                question=message,
                presentation=resolve_session_content_presentation(message, target),
            )
            presentation = content_contract["presentation"]
            title = "\u5448\u73b0 Session \u5185\u5bb9" if self.memory.user_lang == "zh" else "Present Session Content"
            content = (
                "\u6b63\u5728\u8bfb\u53d6\u5f53\u524d Session \u4e2d\u5df2\u4fdd\u5b58\u7684\u5185\u5bb9..."
                if self.memory.user_lang == "zh"
                else "Reading saved content from the current Session..."
            )
            params = {
                "target": target,
                "presentation": presentation,
                "selection": content_contract["selection"],
                "analysis": content_contract["analysis"],
                "mode": "chat",
                "question": message,
            }
            add_step(
                "ui", title, content, status="pending", tool="ui_content",
                params=ToolResultPipeline.trace_params("ui_content", params),
            )
            try:
                # The JSON fallback route still needs the same browser command
                # as SSE.  Creating it here avoids a second, legacy-only path
                # that could acknowledge a report request without presenting
                # the Session-owned figures.
                from tool_factory.ui_content import UISessionContentTool

                result = UISessionContentTool().execute(**params)
                steps[-1]["status"] = "done" if result.success else "error"
                steps[-1]["metadata"] = ToolResultPipeline.trace_metadata(
                    "ui_content", dict(getattr(result, "metadata", {}) or {}),
                ) if result.success else {}
                steps[-1]["result"] = ToolResultPipeline.format(
                    "ui_content", result, self.memory.user_lang,
                )
                if result.success:
                    response = self._session_content_response(target, self.memory.user_lang)
                else:
                    errors = dict(getattr(result, "metadata", {}) or {}).get("user_error_i18n", {})
                    response = str(errors.get(self.memory.user_lang) or errors.get("en") or steps[-1]["result"])
            except Exception:
                logger.exception("Session-content command construction failed")
                steps[-1]["status"] = "error"
                steps[-1]["content"] = ""
                response = (
                    "\u5f53\u524d Session \u4e2d\u7684\u8bf7\u6c42\u5185\u5bb9\u6682\u65f6\u65e0\u6cd5\u5448\u73b0\u3002\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002"
                    if self.memory.user_lang == "zh"
                    else "The requested Session content cannot be presented right now. Please retry shortly."
                )
            self.memory.add_message("assistant", response)
            self._record_experience(message, response, steps)
            self._finish_turn(response)
            return {
                "response": response,
                "steps": steps,
                "llm_meta": {"usage": {}, "latency_ms": 0, "llm_calls": 0, "route": "local_session_content"},
            }

        if self.enhanced and not internal_followup:
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
                add_step(
                    "error",
                    "AI 服务不可用" if self.memory.user_lang == "zh" else "AI Service Unavailable",
                    "自然语言服务连接失败；未启动临床操作。"
                    if self.memory.user_lang == "zh"
                    else "The language service connection failed; no clinical action was started.",
                    status="error",
                )
                response = self._current_llm_unavailable_message()
                llm_meta = {"usage": {}, "latency_ms": 0, "llm_calls": 0}
            if self._is_llm_provider_error(response):
                logger.warning("LLM provider failure suppressed from trace chat output: %s", str(response)[:500])
                add_step(
                    "error",
                    "AI 服务不可用" if self.memory.user_lang == "zh" else "AI Service Unavailable",
                    "自然语言服务连接失败；未启动临床操作。"
                    if self.memory.user_lang == "zh"
                    else "The language service connection failed; no clinical action was started.",
                    status="error",
                )
                response = self._current_llm_unavailable_message()
        else:
            if local_policy.intent == "small_talk":
                add_step("error", "LLM Unavailable", "No configured model; no canned answer was generated.", status="error")
                response = self._current_llm_unavailable_message()
            elif local_policy.direct_execution:
                add_step("thinking", "Rule Matcher", "Brain unavailable — using rule-based parsing")
                response = self._rule_based_chat_with_steps(message, steps, step_id)
            else:
                add_step(
                    "error",
                    "AI 服务不可用" if self.memory.user_lang == "zh" else "AI Service Unavailable",
                    "无法可靠解析该请求；未启动临床操作。"
                    if self.memory.user_lang == "zh"
                    else "The request could not be interpreted reliably; no clinical action was started.",
                    status="error",
                )
                response = self._no_provider_fallback_response(message)
            llm_meta = {"usage": {}, "latency_ms": 0, "llm_calls": 0}

        response = self._normalize_user_facing_response(message, response)

        if not internal_followup:
            self._record_experience(message, response, steps)

        if self.enhanced and not internal_followup:
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
        is_planning_request = not internal_followup and self._planning_requested(message)
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

    def _snapshot_internal_turn_memory(self) -> Dict[str, Any]:
        """Capture only conversational state for a hidden visual child.

        Screenshot analysis may need temporary tool-result messages so a
        second model call can see the captured image. Those messages are not
        a new user turn, however, and must not become context for the next
        question. Clinical planning data and UI state are deliberately not
        included: a hidden child is read-only with respect to those stores.
        """
        import copy

        memory = self.memory
        snapshot: Dict[str, Any] = {}
        with memory._lock:
            for name in (
                "conversation",
                "tool_results",
                "conversation_state",
                "context_summary",
                "_clean_context_cache_key",
                "_clean_context_cache_value",
                "compaction_count",
                "user_lang",
            ):
                if hasattr(memory, name):
                    snapshot[name] = copy.deepcopy(getattr(memory, name))
            smart = getattr(memory, "smart_context", None)
            if smart is not None:
                snapshot["smart_context"] = {
                    name: copy.deepcopy(getattr(smart, name))
                    for name in (
                        "messages",
                        "entities",
                        "topics",
                        "current_topic",
                        "_message_counter",
                    )
                    if hasattr(smart, name)
                }
        return snapshot

    def _restore_internal_turn_memory(self, snapshot: Dict[str, Any]) -> None:
        """Restore the parent conversation after a hidden visual child."""
        import copy

        memory = self.memory
        with memory._lock:
            for name, value in snapshot.items():
                if name == "smart_context":
                    continue
                setattr(memory, name, copy.deepcopy(value))
            smart_snapshot = snapshot.get("smart_context")
            smart = getattr(memory, "smart_context", None)
            if isinstance(smart_snapshot, dict) and smart is not None:
                for name, value in smart_snapshot.items():
                    setattr(smart, name, copy.deepcopy(value))

    def chat_with_stream(self, message: str):
        """Stream a turn, isolating internal visual-analysis children.

        The browser may reconnect a screenshot child after a Session switch.
        Keeping the isolation at this boundary means every entry path
        (initial request, replay, or server-side recovery) gets the same
        memory and persistence semantics.
        """
        turn_context = getattr(self, "_active_turn_context", {}) or {}
        if not bool(turn_context.get("internal_followup")):
            yield from self._chat_with_stream_impl(message)
            return

        snapshot = self._snapshot_internal_turn_memory()
        memory = self.memory
        previous_suppression = bool(getattr(memory, "_suppress_persistence", False))
        memory._suppress_persistence = True
        try:
            yield from self._chat_with_stream_impl(message)
        finally:
            memory._suppress_persistence = previous_suppression
            self._restore_internal_turn_memory(snapshot)

    def _chat_with_stream_impl(self, message: str):
        """Streaming version of chat_with_trace. Yields SSE events."""
        turn_context = getattr(self, "_active_turn_context", {}) or {}
        internal_followup = bool(turn_context.get("internal_followup"))
        inherited_language = (
            self._internal_followup_language(turn_context)
            if internal_followup
            else ""
        )
        if not internal_followup:
            self._purge_orphaned_visual_context()
        self._begin_turn(message)
        # The multimodal prompt is still passed to the current LLM call, but
        # it must never become a durable user message. Its screenshot URLs are
        # transport-only evidence owned by the parent assistant reply.
        if not internal_followup:
            self.memory.add_message("user", message)
        if inherited_language:
            self.memory.user_lang = inherited_language
        else:
            try:
                from memory.language import detect as _detect_turn_language
                _language = _detect_turn_language(message)
                self.memory.user_lang = "zh" if _language.get("code") == "zh" else "en"
            except Exception:
                # Trace locale follows this user request, independent of the
                # application-wide locale used by persistent panels and reports.
                self.memory.user_lang = "zh" if re.search(r"[\u4e00-\u9fff]", message) else "en"
        steps = []
        step_id = [0]
        response = ""  # Initialize response variable
        llm_meta = {"usage": {}, "latency_ms": 0, "llm_calls": 0}
        workflow_turn_token = self._current_turn_token()
        self._turn_started_at = time.perf_counter()
        self._turn_timings = {}

        def add_step(step_type, title, content, status="done", **kwargs):
            # Trace text belongs to the conversational turn, not the global
            # UI/report locale. Never expose raw internal English titles in a
            # Chinese trace (or vice versa) merely because the tool registry
            # happens to use English identifiers.
            trace_lang = getattr(self, "_active_trace_language", None)
            if trace_lang == "zh":
                title = {
                    "Final Response": "最终回复",
                    "Response Synthesis": "生成回复",
                    "Completeness Check": "完整性检查",
                    "Source Verification": "来源核验",
                    "Quality Check": "质量检查",
                    "Auto Planning Pipeline": "自动规划流程",
                }.get(title, title)
                if isinstance(title, str) and title.startswith("Direct: "):
                    tool_name = title.removeprefix("Direct: ")
                    title = {
                        "ctv_segmentation": "CTV 分割",
                        "oar_segmentation": "OAR 分割",
                        "planning_pipeline": "粒子植入规划",
                        "surgical_guide": "手术导板生成",
                        "ui_controller": "界面控制",
                    }.get(tool_name, tool_name)
                content = {
                    "Preparing the reviewed response...": "正在整理回复...",
                    "Response delivered": "回复已发送",
                    "Preparing the response from the completed tool results...": "正在根据工具结果整理回复...",
                    "Response prepared": "回复已整理完成",
                    "Checking requirement coverage...": "正在检查需求覆盖情况...",
                    "Checked": "已检查",
                    "Issues found": "发现需要关注的项目",
                    "Auto-executed by workflow enforcer": "已按完整规划流程自动执行",
                }.get(content, content)
            elif trace_lang == "en":
                if isinstance(title, str) and title.startswith("Direct: "):
                    title = title.removeprefix("Direct: ")
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

        def final_response_events(payload):
            """Emit the reviewed answer incrementally, then its authoritative copy.

            Tool-call text is intentionally kept out of the user-facing answer
            until the review gate has completed.  Providers can also return a
            fully buffered final response, so the post-review protocol emits
            bounded chunks here as a transport fallback.  The final ``response``
            event remains the source of truth and lets clients replace any
            incomplete last chunk without creating a second answer bubble.
            """
            # Keep the execution trace truthful through the last byte of the
            # answer.  Review/tool events can all be terminal while the
            # response is still being serialized and streamed to the browser;
            # without this explicit phase the UI shows N/N ``done`` and looks
            # frozen during that gap.
            final_step = add_step(
                "assistant",
                "Final Response",
                "Preparing the reviewed response...",
                status="pending",
            )
            yield yield_event("step", final_step)
            answer = str((payload or {}).get("response") or "")
            if answer:
                # Keep chunks large enough for efficient SSE traffic while
                # making progress visible for both CJK and Latin text.
                chunk_size = 24
                for offset in range(0, len(answer), chunk_size):
                    yield yield_event(
                        "final_text_chunk",
                        {"text": answer[offset:offset + chunk_size], "complete_length": len(answer)},
                    )
                    if offset + chunk_size < len(answer):
                        time.sleep(0.008)
            yield yield_event("response", payload)
            # Mark delivery complete only after the authoritative response
            # event has been emitted.  The following ``done`` event closes
            # the turn, so the client keeps the breathing pending state while
            # final text is in flight and receives a terminal state before it
            # collapses the trace.
            final_step["status"] = "done"
            final_step["content"] = "Response delivered"
            yield yield_event("step", final_step)

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
            yield from final_response_events({"response": message_text, "steps": steps, "llm_meta": llm_meta})
            yield yield_event("done", {"cancelled": True, "context": {"ui_state": self.memory.get_ui_state()}})

        # Start
        # Include the detected language so the frontend can pick
        # language-aware labels for the todo list, status messages,
        # and other UI text. The detection uses memory/language.py
        # which counts character ranges (CJK vs Latin) and falls
        # back to the previous session's language for ambiguous
        # short messages. See memory/language.py for the full
        # detection rules and the rationale for top-level injection.
        if inherited_language:
            _lang_info_start = {
                "code": inherited_language,
                "name": "Chinese" if inherited_language == "zh" else "English",
                "source": "parent_turn",
            }
        else:
            try:
                from memory.language import detect as _lang_detect_start
                _lang_info_start = _lang_detect_start(message)
            except Exception:
                _lang_info_start = {"code": "en", "name": "English", "source": "default"}
        _trace_lang = "zh" if _lang_info_start.get("code") == "zh" else "en"
        # The request locale is the source of truth for this turn's trace and
        # direct-tool response. Persistent panels/reports deliberately use a
        # separate global UI locale.
        self.memory.user_lang = _trace_lang
        self._active_trace_language = _trace_lang

        def _trace_text(zh: str, en: str) -> str:
            """Keep a request's trace in the language used for that request.

            This deliberately does not read the global UI/report locale.  The
            trace belongs to a conversational turn, while persistent controls
            and reports follow the global language selector.
            """
            return zh if _trace_lang == "zh" else en

        def _routing_summary(intent: str, complexity: str, review: bool) -> str:
            if _trace_lang == "zh":
                return "\u610f\u56fe: {}; \u590d\u6742\u5ea6: {}; \u590d\u6838: {}".format(
                    intent,
                    complexity,
                    "\u9700\u8981" if review else "\u53ef\u9009",
                )
            return "Intent: {}, Complexity: {}, Review: {}".format(
                intent,
                complexity,
                "Required" if review else "Optional",
            )
        # A visual-analysis child receives the screenshot prompt only as
        # short-lived model context.  It is never a conversational user turn,
        # so do not put the raw URLs/instructions into the SSE transport or its
        # step list.  This is the source-level boundary that protects both live
        # rendering and reconnect/replay paths; filtering durable rows alone is
        # too late because a client can render a replayed event immediately.
        if internal_followup:
            yield yield_event(
                "start",
                {
                    "message": "Visual screenshot analysis follow-up",
                    "language": _lang_info_start,
                    "internal_followup": True,
                },
            )
        else:
            yield yield_event("start", {"message": message, "language": _lang_info_start})
            add_step("user", _trace_text("\u7528\u6237\u8f93\u5165", "User Input"), message)
            yield yield_event("step", steps[-1])

        # The local policy is an execution hint only. It does not synthesize
        # an answer; all user-facing text continues through the configured LLM.
        local_policy = (
            visual_analysis_policy()
            if internal_followup
            else classify_local_turn(
                message,
                pending_tumor_site=self._pending_tumor_site_clarification(),
            )
        )
        self._activate_turn_policy(local_policy)

        # Multi-agent routing (if available). The local policy decides whether
        # this expensive route is needed for the current intent, while the LLM
        # remains responsible for the final answer.
        _ma_routing = None
        _route_started = time.perf_counter()
        if (
            self.multi_agent_wrapper
            and self.multi_agent_wrapper.enabled
            and local_policy.use_router
        ):
            router_step = add_step(
                "thinking",
                _trace_text("\u591a\u667a\u80fd\u4f53\u8def\u7531", "Multi-Agent Router"),
                _trace_text("\u6b63\u5728\u5206\u6790\u8bf7\u6c42...", "Analyzing request..."),
                status="pending",
            )
            yield yield_event("step", router_step)
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
                    router_step["status"] = "done"
                    router_step["content"] = _routing_summary(
                        _ma_routing.intent,
                        _ma_routing.complexity,
                        _ma_routing.requires_review,
                    )
                else:
                    router_step["status"] = "done"
                    router_step["content"] = _trace_text("\u8def\u7531\u4e0d\u53ef\u7528", "Routing not available")
                yield yield_event("step", router_step)
            except Exception as e:
                logger.debug(f"Multi-agent routing failed: {e}")
                router_step["status"] = "error"
                router_step["content"] = _trace_text("\u8def\u7531\u5931\u8d25", "Routing failed")
                yield yield_event("step", router_step)
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
                "thinking", _trace_text("\u672c\u5730\u610f\u56fe\u8bc6\u522b", "Local Intent"),
                _routing_summary(
                    local_policy.intent,
                    local_policy.complexity,
                    local_policy.requires_review,
                ),
            )
            yield yield_event("step", local_route_step)
        self._turn_timings["router_ms"] = round((time.perf_counter() - _route_started) * 1000, 1)

        # Planning provenance is a local, read-only Session query. It must be
        # answered before provider routing/tool execution so a follow-up about
        # the previous dose calculation cannot restart Planning or fall into a
        # generic semantic-action response when the provider is unavailable.
        if local_policy.intent == "planning_provenance_query":
            state_step = add_step(
                "ui",
                _trace_text("本次规划来源", "Current Planning Provenance"),
                _trace_text(
                    "正在读取当前激活 Planning 及本次重算的来源...",
                    "Reading the active Planning and the source recorded for this recomputation...",
                ),
                status="pending",
            )
            yield yield_event("step", state_step)
            response = self._build_current_planning_provenance_response(self.memory.user_lang)
            state_step["status"] = "done"
            state_step["content"] = _trace_text("已读取 Planning 来源", "Planning provenance loaded")
            yield yield_event("step", state_step)
            self.memory.add_message("assistant", response)
            self._finish_turn(response)
            llm_meta["route"] = "local_planning_provenance"
            llm_meta["phase_timings_ms"] = dict(getattr(self, "_turn_timings", {}) or {})
            yield from final_response_events({"response": response, "llm_meta": llm_meta})
            yield yield_event("done", {"context": {"message_count": len(self.memory.conversation)}})
            return

        # Technical image metadata is a local read-only query. Resolve it
        # before any tool-calling loop so the chat answer uses the active
        # Session's canonical CT object and never exposes raw tool logs.
        if local_policy.intent == "image_metadata_query":
            state_step = add_step(
                "ui",
                _trace_text("\u5f53\u524d CT \u5143\u6570\u636e", "Current CT Metadata"),
                _trace_text(
                    "\u6b63\u5728\u8bfb\u53d6\u5f53\u524d Session \u4e2d\u5df2\u52a0\u8f7d\u7684 CT \u6280\u672f\u4fe1\u606f...",
                    "Reading technical metadata from the CT loaded in the active Session...",
                ),
                status="pending",
            )
            yield yield_event("step", state_step)
            response = self._build_current_image_metadata_response(self.memory.user_lang)
            state_step["status"] = "done"
            state_step["content"] = _trace_text("\u5df2\u8bfb\u53d6 CT \u6280\u672f\u4fe1\u606f", "Current CT metadata loaded")
            yield yield_event("step", state_step)
            self.memory.add_message("assistant", response)
            self._finish_turn(response)
            llm_meta["route"] = "local_image_metadata"
            llm_meta["phase_timings_ms"] = dict(getattr(self, "_turn_timings", {}) or {})
            yield from final_response_events({"response": response, "llm_meta": llm_meta})
            yield yield_event("done", {"context": {"message_count": len(self.memory.conversation)}})
            return

        if local_policy.intent == "report_generation" and local_policy.direct_execution:
            params = self._report_generation_params()
            state_step = add_step(
                "tool",
                _trace_text("\u91cd\u65b0\u751f\u6210\u62a5\u544a", "Regenerate Report"),
                _trace_text(
                    "\u6b63\u5728\u6839\u636e\u5f53\u524d Session \u7ed3\u679c\u66f4\u65b0\u62a5\u544a...",
                    "Updating the report from the current Session results...",
                ),
                status="pending",
                tool="ui_controller",
                params=params,
            )
            yield yield_event("step", state_step)
            try:
                result = self._execute_tool_with_memory("ui_controller", params)
                state_step["status"] = "done" if result.success else "error"
                state_step["content"] = ""
                state_step["result"] = ToolResultPipeline.format(
                    "ui_controller", result, self.memory.user_lang,
                )
                state_step["metadata"] = ToolResultPipeline.trace_metadata(
                    "ui_controller", dict(getattr(result, "metadata", {}) or {}),
                ) if result.success else {}
                success = bool(result.success)
            except Exception:
                logger.exception("Report-generation UI action construction failed")
                state_step["status"] = "error"
                state_step["content"] = ""
                state_step["metadata"] = {}
                success = False
            yield yield_event("step", state_step)
            response = self._report_generation_response(self.memory.user_lang, success)
            self.memory.add_message("assistant", response)
            self._finish_turn(response)
            llm_meta["route"] = "local_report_generation"
            llm_meta["phase_timings_ms"] = dict(getattr(self, "_turn_timings", {}) or {})
            yield from final_response_events({"response": response, "llm_meta": llm_meta})
            yield yield_event("done", {"context": {"message_count": len(self.memory.conversation)}})
            return

        # Content already persisted in the current Session is presented by the
        # browser against the owner Session, not recaptured from a potentially
        # unmounted panel. The tool step carries only a compact, localized
        # command; the frontend resolves attachments and structured data.
        if not internal_followup and local_policy.intent == "session_content_query":
            target = resolve_session_content_target(message) or "session_summary"
            from tool_factory.ui_content import normalize_session_content_request

            content_contract = normalize_session_content_request(
                question=message,
                presentation=resolve_session_content_presentation(message, target),
            )
            params = {
                "target": target,
                "presentation": content_contract["presentation"],
                "selection": content_contract["selection"],
                "analysis": content_contract["analysis"],
                "mode": "chat",
                "question": message,
            }
            state_step = add_step(
                "tool",
                _trace_text("\u5448\u73b0 Session \u5185\u5bb9", "Present Session Content"),
                _trace_text(
                    "\u6b63\u5728\u8bfb\u53d6\u5f53\u524d Session \u4e2d\u5df2\u4fdd\u5b58\u7684\u5185\u5bb9...",
                    "Reading saved content from the current Session...",
                ),
                status="pending",
                tool="ui_content",
                params=ToolResultPipeline.trace_params("ui_content", params),
            )
            yield yield_event("step", state_step)
            tool = None
            if getattr(self, "registry", None):
                try:
                    tool = self.registry.get("ui_content")
                except Exception as error:
                    # A rolling server upgrade can briefly serve a restored
                    # Session with an older registry. Treat that as a normal,
                    # localized unavailable state instead of aborting the
                    # entire chat turn with a registry exception.
                    logger.warning("Session-content tool is unavailable: %s", error)
                    tool = None
            if tool is None:
                state_step["status"] = "error"
                state_step["content"] = _trace_text(
                    "Session \u5185\u5bb9\u5448\u73b0\u670d\u52a1\u6682\u4e0d\u53ef\u7528\u3002",
                    "The Session content presentation service is unavailable.",
                )
                response = (
                    "\u6682\u65f6\u65e0\u6cd5\u8bfb\u53d6\u5f53\u524d Session \u4e2d\u7684\u8bf7\u6c42\u5185\u5bb9\u3002\u8bf7\u7a0d\u540e\u91cd\u8bd5\uff0c\u6216\u5148\u786e\u8ba4\u8be5 Session \u5df2\u5b8c\u6210\u52a0\u8f7d\u3002"
                    if self.memory.user_lang == "zh"
                    else "The requested content cannot be read from the current Session right now. Retry after the Session finishes loading."
                )
            else:
                try:
                    result = self._execute_tool_with_memory("ui_content", params)
                except Exception:
                    logger.exception("Session-content tool execution failed")
                    state_step["status"] = "error"
                    state_step["content"] = ""
                    state_step["result"] = (
                        "\u5f53\u524d Session \u4e2d\u7684\u8bf7\u6c42\u5185\u5bb9\u6682\u65f6\u65e0\u6cd5\u5448\u73b0\u3002\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002"
                        if self.memory.user_lang == "zh"
                        else "The requested Session content cannot be presented right now. Please retry shortly."
                    )
                    response = state_step["result"]
                else:
                    raw_metadata = dict(getattr(result, "metadata", {}) or {})
                    state_step["status"] = "done" if result.success else "error"
                    state_step["content"] = ""
                    # Keep only the compact browser command and localized
                    # trace summary in the live event. The tool's
                    # model_instruction is intentionally not sent to the
                    # browser, persisted Trace, or normal chat message.
                    if result.success:
                        state_step["metadata"] = ToolResultPipeline.trace_metadata(
                            "ui_content",
                            raw_metadata,
                        )
                    else:
                        state_step["metadata"] = {}
                    state_step["result"] = ToolResultPipeline.format("ui_content", result, self.memory.user_lang)
                    if result.success:
                        response = self._session_content_response(target, self.memory.user_lang)
                    else:
                        error_map = raw_metadata.get("user_error_i18n", {})
                        response = str(error_map.get(self.memory.user_lang) or error_map.get("en") or state_step["result"])
            yield yield_event("step", state_step)
            self.memory.add_message("assistant", response)
            self._finish_turn(response)
            llm_meta["route"] = "local_session_content"
            llm_meta["phase_timings_ms"] = dict(getattr(self, "_turn_timings", {}) or {})
            yield from final_response_events({"response": response, "llm_meta": llm_meta})
            yield yield_event("done", {"context": {"message_count": len(self.memory.conversation)}})
            return

        # A request for the number of currently loaded OARs is a local UI
        # state query. It reads the active case instead of searching the
        # clinical KB, taking a screenshot, or asking the model to infer it.
        if self._is_current_oar_count_request(message):
            state_step = add_step(
                "ui", "Current Data Tree",
                "Reading loaded OAR structures from the active case...",
                status="pending",
            )
            yield yield_event("step", state_step)
            response = self._build_current_oar_count_response(self.memory.user_lang)
            state_step["status"] = "done"
            state_step["content"] = "Current OAR state read"
            yield yield_event("step", state_step)
            self.memory.add_message("assistant", response)
            self._finish_turn(response)
            llm_meta["route"] = "live_ui_state"
            llm_meta["phase_timings_ms"] = dict(getattr(self, "_turn_timings", {}) or {})
            yield from final_response_events({"response": response, "llm_meta": llm_meta})
            yield yield_event("done", {"context": {"message_count": len(self.memory.conversation)}})
            return

        # A current-dose question is a read-only workspace query. Keep it
        # ahead of direct tools and the LLM function-calling loop so it cannot
        # drift into clinical_kb/web_fetch and return source-page text instead
        # of the dose/DVH values already computed for this case.
        if local_policy.intent == "case_dose_query":
            state_step = add_step(
                "ui",
                _trace_text("当前病例剂量", "Current Case Dose"),
                _trace_text(
                    "正在读取当前 Session 已保存的剂量和 DVH 结果...",
                    "Reading the saved dose and DVH results from the active case...",
                ),
                status="pending",
            )
            yield yield_event("step", state_step)
            response = self._build_current_dose_response(self.memory.user_lang)
            state_step["status"] = "done"
            state_step["content"] = _trace_text("已读取当前剂量结果", "Current dose results loaded")
            yield yield_event("step", state_step)
            self.memory.add_message("assistant", response)
            self._finish_turn(response)
            llm_meta["route"] = "local_case_dose"
            llm_meta["phase_timings_ms"] = dict(getattr(self, "_turn_timings", {}) or {})
            yield from final_response_events({"response": response, "llm_meta": llm_meta})
            yield yield_event("done", {"context": {"message_count": len(self.memory.conversation)}})
            return

        # Direct tool execution — only for locally-confirmed actionable intents.
        # Knowledge queries, status checks, and small talk always route through
        # the LLM so it can read the current case state and produce a meaningful
        # answer instead of auto-executing a tool the user didn't ask for.
        _direct_tool_calls = None
        _has_explicit_planning_action_plan = bool(
            getattr(local_policy, "action_plan", None) is not None
            and local_policy.action_plan.requires_tool("planning_pipeline")
        )
        if (
            (
                local_policy.direct_execution
                and local_policy.intent in (
                    "segmentation",
                    "planning",
                    "treatment_plan",
                    "clinical_planning",
                    "surgical_guide_generation",
                    "dose_recompute",
                    "viewer_display",
                )
            )
            or _has_explicit_planning_action_plan
        ):
            _direct_tool_calls = self._detect_tool_request(message)
        if _direct_tool_calls:
            authorization = self._current_execution_authorization()
            if authorization is not None:
                authorization.grant_tool_calls(_direct_tool_calls, source="local_direct_calls")
            _lang = self.memory.user_lang
            logger.info(f"Direct tool execution (stream): {len(_direct_tool_calls)} tools")
            for tc in _direct_tool_calls:
                trace_params = ToolResultPipeline.trace_params(tc["tool"], tc["params"])
                step = add_step("tool", f"Direct: {tc['tool']}", json.dumps(trace_params, default=str)[:200],
                                status="pending", tool=tc['tool'], params=trace_params)
                yield yield_event("step", step)
                try:
                    # Store ct_path for downstream tools
                    if tc['tool'] in ('ctv_segmentation', 'oar_segmentation', 'biomedparse_segmentation') and 'image_path' in tc['params']:
                        self.memory.store("ct_path", tc['params']['image_path'])
                        # Also load and store CT image if not already in memory
                        if self.memory.retrieve("ct_image") is None:
                            try:
                                import SimpleITK as sitk
                                from utils.ct_volume import normalize_ct_image
                                ct_img, source_meta = normalize_ct_image(
                                    sitk.ReadImage(tc['params']['image_path'])
                                )
                                self.memory.store("ct_image", ct_img)
                                # Keep raw frame for label metadata alignment
                                self.memory.retrieve("ct_image_raw") or self.memory.store("ct_image_raw", ct_img)
                                existing_meta = dict(self.memory.retrieve("ct_source_meta") or {})
                                existing_meta.update(source_meta)
                                self.memory.store("ct_source_meta", existing_meta)
                            except Exception as _e:
                                logger.warning(f"Failed to pre-load CT image: {_e}")

                    if self.registry.get(tc['tool']):
                        result = self._execute_tool_with_memory(
                            tc['tool'], dict(tc['params'])
                        )
                        step["status"] = "done" if result.success else "error"
                        # Fact checking may perform additional model work.  It
                        # is therefore a first-class trace phase rather than
                        # hidden work after the search tool is marked done.
                        _fmt = self._format_tool_result(tc['tool'], result, lang=_lang)
                        if tc['tool'] in ("web_search", "web_fetch", "web_access") and result.success:
                            step_id[0] += 1
                            _fact_step = add_step(
                                "tool",
                                "Source Verification",
                                "Checking search claims and source reliability...",
                                status="pending",
                                tool="fact_checker",
                            )
                            yield yield_event("step", _fact_step)
                            try:
                                _fmt = self._check_search_reliability(tc['tool'], _fmt)
                                _fact_step["status"] = "done"
                                _fact_step["content"] = "Source reliability checked"
                            except Exception as _fact_exc:
                                logger.debug("Fact-check phase failed: %s", _fact_exc)
                                _fact_step["status"] = "error"
                                _fact_step["content"] = f"Source check unavailable: {str(_fact_exc)[:80]}"
                            yield yield_event("step", _fact_step)
                        step["result"] = _fmt
                        step["metadata"] = (
                            ToolResultPipeline.trace_metadata(tc["tool"], result.metadata)
                            if result.success
                            else {}
                        )
                        yield yield_event("step", step)
                        if result.success:
                            # After a segmentation tool, ensure ct_image is
                            # stored for downstream tools and later Viewer
                            # hydration. Generic BiomedParse masks use the
                            # same canonical CT grid as CTV/OAR.
                            if tc['tool'] in ('ctv_segmentation', 'biomedparse_segmentation') and 'image_path' in tc['params']:
                                if self.memory.retrieve("ct_image") is None:
                                    try:
                                        import SimpleITK as sitk
                                        from utils.ct_volume import normalize_ct_image
                                        ct_img, source_meta = normalize_ct_image(
                                            sitk.ReadImage(tc['params']['image_path'])
                                        )
                                        self.memory.store("ct_image", ct_img)
                                        # Also keep raw frame for label metadata alignment
                                        self.memory.retrieve("ct_image_raw") or self.memory.store("ct_image_raw", ct_img)
                                        existing_meta = dict(self.memory.retrieve("ct_source_meta") or {})
                                        existing_meta.update(source_meta)
                                        self.memory.store("ct_source_meta", existing_meta)
                                    except Exception as e:
                                        logger.warning(
                                            f"Failed to auto-load CT from {tc['params']['image_path']}: {e}. "
                                            f"Downstream planning may fail with 'No CT image available'."
                                        )
                        # Store in conversation for context persistence
                        self.memory.add_message("assistant", f"[Called {tc['tool']}]")
                        result_summary = (
                            _fmt[:500]
                            if tc["tool"] in {"ui_screenshot", "ui_content"}
                            else (result.message[:500] if result.success else f"Error: {result.error}")
                        )
                        self.memory.add_message("user", f"[Tool result: {result_summary}]")
                        if not result.success and tc["tool"] in {
                            "ctv_segmentation", "oar_segmentation", "planning_pipeline"
                        }:
                            logger.info(
                                "Stopping direct streaming clinical chain after failed prerequisite: %s",
                                tc["tool"],
                            )
                            break
                except Exception as e:
                    step["status"] = "error"
                    step["result"] = str(e)
                    yield yield_event("step", step)
                    logger.error(f"Direct tool failed: {tc['tool']}: {e}")
                    self.memory.add_message("assistant", f"[Called {tc['tool']}]")
                    self.memory.add_message("user", f"[Tool result: Error: {str(e)[:200]}]")
                    if tc["tool"] in {
                        "ctv_segmentation", "oar_segmentation", "planning_pipeline"
                    }:
                        break

            # Viewer result refresh is a display-only action. Finish it here
            # before the clinical/report synthesis path: calling
            # _build_direct_response or _has_completed_planning_in_steps would
            # add unnecessary coupling to planning-only helpers and make this
            # provider-independent browser operation fragile.
            if local_policy.intent == "viewer_display":
                _viewer_synthesis_step = add_step(
                    "assistant",
                    "生成回复",
                    "正在整理回复...",
                    status="pending",
                )
                yield yield_event("step", _viewer_synthesis_step)
                response = self._viewer_display_response(
                    _lang,
                    any(
                        step.get("tool") == "ui_controller"
                        and step.get("status") == "done"
                        for step in steps
                    ),
                )
                _viewer_synthesis_step["status"] = "done"
                _viewer_synthesis_step["content"] = "Response prepared"
                yield yield_event("step", _viewer_synthesis_step)
                self.memory.add_message("assistant", response)
                self._finish_turn(response)
                llm_meta["phase_timings_ms"] = dict(getattr(self, "_turn_timings", {}) or {})
                llm_meta["route"] = "direct_tool"
                yield from final_response_events({
                    "response": response,
                    "llm_meta": llm_meta,
                })
                yield yield_event("done", {"context": {"message_count": len(self.memory.conversation)}})
                return

            # Direct tool requests used to have a silent interval here:
            # tools were already marked done while report construction or a
            # synthesis LLM call was still running.  Expose that work as a
            # real pending trace phase instead of making the user infer that
            # the request is stuck.
            _synthesis_step = add_step(
                "assistant",
                "Response Synthesis",
                "Preparing the response from the completed tool results...",
                status="pending",
            )
            yield yield_event("step", _synthesis_step)
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
            _direct_tool_names = {
                str(step.get("tool") or "")
                for step in steps
                if step.get("type") == "tool"
            }
            if _direct_tool_names == {"dose_recompute"}:
                # The tool formatter is the authoritative localized response
                # and contains the before/after consistency result. Avoid a
                # second synthesis call for this focused operation.
                response = raw_response
            elif local_policy.intent == "viewer_display" and _direct_tool_names == {"ui_controller"}:
                # Viewer refresh is a deterministic browser operation. A
                # synthesis call here would reintroduce the exact provider
                # dependency that this fast path is designed to remove.
                response = self._viewer_display_response(
                    _lang,
                    any(
                        step.get("tool") == "ui_controller"
                        and step.get("status") == "done"
                        for step in steps
                    ),
                )
            elif has_planning:
                response = self._build_planning_report(_lang, steps)
            else:
                query_type = self._classify_query_type(user_msg)
                response = self._synthesize_with_llm(raw_response, steps, _lang, user_msg, query_type)
            _synthesis_step["status"] = "done"
            _synthesis_step["content"] = "Response prepared"
            yield yield_event("step", _synthesis_step)
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
                    "title": _trace_text("完整性检查", "Completeness Check"),
                    "tool": "completeness_checker",
                    "content": _trace_text("正在检查需求覆盖情况...", "Checking requirement coverage..."),
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
                    _direct_cc_step["content"] = _trace_text(
                        "已完成" if not _cc_result else "发现待处理项",
                        "Checked" if not _cc_result else "Issues found",
                    )
                    yield yield_event("step", _direct_cc_step)
                except Exception as e:
                    logger.debug(f"Direct completeness check skipped: {e}")
                    _direct_cc_step["status"] = "done"
                    _direct_cc_step["content"] = _trace_text(
                        "需求覆盖检查暂不可用，将继续生成回复。",
                        "Coverage check unavailable; continuing.",
                    )
                    yield yield_event("step", _direct_cc_step)

            self._finish_turn(response)
            llm_meta["phase_timings_ms"] = dict(getattr(self, "_turn_timings", {}) or {})
            llm_meta["route"] = "direct_tool"
            yield from final_response_events({"response": response, "llm_meta": llm_meta})
            yield yield_event("done", {"context": {"message_count": len(self.memory.conversation)}})
            return

        # Enhanced context
        if self.enhanced and not internal_followup:
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
                if local_policy.intent == "small_talk":
                    # Conversational intent: use the single-shot lightweight
                    # path (no tool schemas, no clinical context, no loop).
                    # This is a structural fast lane for the whole small_talk
                    # intent category, so a casual greeting no longer pays the
                    # 30s function-calling pipeline cost.
                    for ev in self._run_lightweight_conversation_stream(message, steps, step_id, yield_event):
                        if isinstance(ev, dict) and ev.get("type") == "_result":
                            response = ev.get("response", "")
                            llm_meta = ev.get("llm_meta", {})
                        else:
                            yield ev
                else:
                    for ev in self._run_llm_function_calling_stream(message, steps, step_id, yield_event):
                        if isinstance(ev, dict) and ev.get("type") == "_result":
                            response = ev.get("response", "")
                            llm_meta = ev.get("llm_meta", {})
                        else:
                            yield ev
            except Exception as e:
                import traceback as _tb
                logger.error(f"LLM function calling failed: {e}\n{_tb.format_exc()}")
                step = add_step(
                    "error",
                    "AI 服务不可用" if self.memory.user_lang == "zh" else "AI Service Unavailable",
                    "自然语言服务连接失败；未启动临床操作。"
                    if self.memory.user_lang == "zh"
                    else "The language service connection failed; no clinical action was started.",
                    status="error",
                )
                yield yield_event("step", step)
                response = self._current_llm_unavailable_message()
                llm_meta = {"usage": {}, "latency_ms": 0, "llm_calls": 0}
            if self._is_llm_provider_error(response):
                logger.warning("LLM provider failure suppressed from streaming chat output: %s", str(response)[:500])
                step = add_step(
                    "error",
                    "AI 服务不可用" if self.memory.user_lang == "zh" else "AI Service Unavailable",
                    "自然语言服务连接失败；未启动临床操作。"
                    if self.memory.user_lang == "zh"
                    else "The language service connection failed; no clinical action was started.",
                    status="error",
                )
                yield yield_event("step", step)
                response = self._current_llm_unavailable_message()
        else:
            if local_policy.intent == "small_talk":
                step = add_step("error", "LLM Unavailable", "No configured model; no canned answer was generated.", status="error")
                yield yield_event("step", step)
                response = self._current_llm_unavailable_message()
            elif local_policy.direct_execution:
                response = self._rule_based_chat_with_steps_stream(message, steps, step_id, yield_event)
            else:
                step = add_step(
                    "error",
                    _trace_text("AI 服务不可用", "AI Service Unavailable"),
                    _trace_text(
                        "无法可靠解析该请求；未启动临床操作。",
                        "The request could not be interpreted reliably; no clinical action was started.",
                    ),
                    status="error",
                )
                yield yield_event("step", step)
                response = self._no_provider_fallback_response(message)
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

        response = self._normalize_user_facing_response(message, response)

        # A hidden visual child is not an independent user interaction. Its
        # temporary analysis must not enter episodic/skill memory either.
        if not internal_followup:
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
        # Reviewer/checker output is internal orchestration feedback. It is
        # never appended verbatim to the user-facing answer.
        review_feedback = []
        _needs_review = False
        _review_reason = ""
        _review_started = time.perf_counter()

        # Smart review decision based on tool usage and response complexity
        _high_value_tools = {
            "planning_pipeline", "seed_planning", "dose_evaluation", "dose_calc",
            "ctv_segmentation", "oar_segmentation", "biomedparse_segmentation", "trajectory_planning",
            "safety_validator", "clinical_kb"
        }
        _tools_called = {s.get("tool") for s in steps if s.get("type") == "tool"}
        _high_value_called = _tools_called & _high_value_tools
        _knowledge_tools = {"web_search", "web_fetch", "web_access"}
        _knowledge_called = _tools_called & _knowledge_tools
        _direct_read_result = any(
            isinstance((step.get("metadata") or {}).get("response_contract"), dict)
            and (step.get("metadata") or {}).get("response_contract", {}).get("mode") == "direct_read"
            and step.get("status") == "done"
            for step in steps
            if step.get("type") == "tool"
        )
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

        if _direct_read_result:
            # A successful typed read from the active session is already a
            # deterministic answer. Review is useful for planning and
            # evidence synthesis, but it only adds latency and a redundant
            # checker round here.
            _needs_review = False
            _review_reason = "direct_read_contract"
        elif _router_requires_review:
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
        elif not internal_followup and (
            ("ui_screenshot" in _tools_called and _visual_analysis_request)
            or "[Screenshot captured:" in message
        ):
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
                        _metrics, _plan_info, _config, _lang,
                        skip_distill=True,
                    )

                async def _run_completeness():
                    return await self.multi_agent_wrapper.check_completeness_append(
                        message, response, steps, _lang,
                        skip_distill=True,
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
                        review_feedback.append({"kind": "plan_review", "text": _plan_result})
                    if _review_step:
                        _review_step["status"] = "done"
                        _review_step["content"] = "Reviewed" if _plan_result else "No issues"
                        yield yield_event("step", _review_step)

                    if isinstance(_cc_result, str) and _cc_result:
                        review_feedback.append({"kind": "completeness", "text": _cc_result})
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
        # The generated visual-child prompt embeds the parent request as
        # evidence. It must never reactivate the parent workflow enforcer.
        is_planning_request = not internal_followup and self._planning_requested(message)
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
                                    # Guide generation is a separate persistent
                                    # mutation.  Run it only when this turn's
                                    # semantic decision (or the exact legacy full-
                                    # planning shortcut) granted that tool.
                                    authorization = self._current_execution_authorization()
                                    guide_authorized = bool(
                                        authorization is not None
                                        and authorization.tool_allowed("surgical_guide")
                                    )
                                    if guide_authorized and self.registry.get("surgical_guide"):
                                        try:
                                            logger.info("[WORKFLOW-ENFORCER-STREAM] Auto-generating surgical guide")
                                            guide_step = add_step(
                                                "tool",
                                                "Auto Surgical Guide",
                                                "Generating puncture guide from planned needle paths...",
                                                status="pending",
                                                tool="surgical_guide",
                                            )
                                            yield yield_event("step", guide_step)
                                            guide_result = self._execute_tool_with_memory(
                                                "surgical_guide", {"action": "generate"}
                                            )
                                            if guide_result and guide_result.success:
                                                guide_step["status"] = "done"
                                                guide_step["result"] = str(guide_result.message)[:200] if guide_result.message else "Guide generated"
                                            else:
                                                err = (
                                                    guide_result.error or guide_result.message
                                                    if guide_result is not None else "Guide generation failed"
                                                )
                                                guide_step["status"] = "error"
                                                guide_step["result"] = str(err)[:200]
                                            yield yield_event("step", guide_step)
                                        except Exception as _guide_e:
                                            logger.error(f"[WORKFLOW-ENFORCER-STREAM] Guide auto-generation failed: {_guide_e}")
                                            guide_step["status"] = "error"
                                            guide_step["result"] = str(_guide_e)[:200]
                                            yield yield_event("step", guide_step)
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
                        _metrics, _plan_info, _config, self.memory.user_lang,
                        skip_distill=True,
                    )

                async def _run_post_completeness():
                    return await self.multi_agent_wrapper.check_completeness_append(
                        message, response, steps, self.memory.user_lang,
                        skip_distill=True,
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
                    review_feedback.append({"kind": "plan_review", "text": _post_plan_result})
                if isinstance(_post_cc_result, str) and _post_cc_result:
                    review_feedback.append({"kind": "completeness", "text": _post_cc_result})
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

        if _workflow_enforced and _needs_review:
            # Include the post-enforcer review in the single checker phase
            # reported to the client; otherwise planning turns under-report
            # their actual review latency.
            self._turn_timings["checker_ms"] = round(
                (time.perf_counter() - _review_started) * 1000, 1
            )

        # Store review feedback for diagnostics and future orchestration, but
        # keep the final response single-speaker: the main response or the
        # structured planning report is what the user should read. Raw
        # reviewer prose belongs in Execution Trace only.
        if review_feedback:
            try:
                self.memory.store("last_review_feedback", review_feedback)
            except Exception as exc:
                logger.debug("Could not persist internal review feedback: %s", exc)
            llm_meta["review_feedback"] = [
                {"kind": item.get("kind"), "text_length": len(item.get("text") or "")}
                for item in review_feedback
            ]

        # Final response
        self._finish_turn(response)
        llm_meta.setdefault("phase_timings_ms", {}).update(self._turn_timings)
        llm_meta["phase_timings_ms"]["sse_push_ms"] = round(
            (time.perf_counter() - getattr(self, "_turn_started_at", time.perf_counter())) * 1000,
            1,
        )
        yield from final_response_events({"response": response, "steps": steps, "llm_meta": llm_meta})
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
        if not bool(getattr(getattr(self, "_active_turn_policy", None), "direct_execution", False)):
            return self._unmatched_turn_response(message)
        msg_lower = message.lower()

        def yield_step(step):
            steps.append(step)
            yield_event("step", step)

        if "分割" in msg_lower or "segment" in msg_lower:
            target = "CTV"
            if "oar" in msg_lower or "organ" in msg_lower or "器官" in msg_lower:
                target = "OAR"
            elif self._segmentation_scope(message) == "oar":
                # A generic repeat inherits the last explicit segmentation
                # target instead of unexpectedly running both models.
                target = "OAR"

            step_id[0] += 1
            tool_step = {
                "id": step_id[0], "type": "tool", "title": f"Segmentation: {target}",
                "content": f"Running {target} segmentation...", "status": "pending",
                "tool": f"{target.lower()}_segmentation", "params": {},
            }
            yield_step(tool_step)

            result = self._handle_ctv_segmentation_request(message) if target == "CTV" else self._handle_oar_segmentation_request(message)

            tool_step["status"] = (
                "done" if self.memory.retrieve("last_segmentation_success", True)
                else "error"
            )
            tool_step["result"] = result[:200]
            yield_step(tool_step)

            step_id[0] += 1
            result_step = {
                "id": step_id[0], "type": "result", "title": f"{target} Result",
                "content": result,
                "status": "done" if self.memory.retrieve("last_segmentation_success", True) else "error",
            }
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
            return self._unmatched_turn_response(message)

    def _rule_based_chat_with_steps(self, message: str, steps: List[Dict], step_id: List[int]) -> str:
        if not bool(getattr(getattr(self, "_active_turn_policy", None), "direct_execution", False)):
            return self._unmatched_turn_response(message)
        msg_lower = message.lower()
        if "分割" in msg_lower or "segment" in msg_lower:
            target = "CTV"
            if "oar" in msg_lower or "organ" in msg_lower or "器官" in msg_lower:
                target = "OAR"
            elif self._segmentation_scope(message) == "oar":
                target = "OAR"
            step_id[0] += 1
            steps.append({
                "id": step_id[0], "type": "tool", "title": f"Segmentation: {target}",
                "content": f"Running {target} segmentation...", "status": "pending",
                "tool": f"{target.lower()}_segmentation", "params": {},
            })
            result = self._handle_ctv_segmentation_request(message) if target == "CTV" else self._handle_oar_segmentation_request(message)
            steps[-1]["status"] = (
                "done" if self.memory.retrieve("last_segmentation_success", True)
                else "error"
            )
            step_id[0] += 1
            steps.append({
                "id": step_id[0], "type": "result", "title": f"{target} Result",
                "content": result,
                "status": "done" if self.memory.retrieve("last_segmentation_success", True) else "error",
            })
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
            return self._unmatched_turn_response(message)

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
        if not bool(getattr(getattr(self, "_active_turn_policy", None), "direct_execution", False)):
            return self._unmatched_turn_response(message)
        msg_lower = message.lower()
        if "分割" in msg_lower or "segment" in msg_lower:
            if "ctv" in msg_lower or "target" in msg_lower or "肿瘤" in msg_lower:
                response = self._handle_ctv_segmentation_request(message)
            elif "oar" in msg_lower or "organ" in msg_lower or "器官" in msg_lower:
                response = self._handle_oar_segmentation_request(message)
            elif self._segmentation_scope(message) == "oar":
                # Keep the fallback path scope-aware as well. A generic
                # repeat inherits the last explicit segmentation target.
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
            response = self._unmatched_turn_response(message)
        return response

    def _handle_ctv_segmentation_request(self, message: str) -> str:
        ct_image = self.memory.retrieve("ct_image")
        ctv_path = self.memory.retrieve("ctv_path")
        if ct_image is None:
            self.memory.store("last_segmentation_success", False)
            return "Please provide CT image path first. Use run_preoperative_plan(ct_path=...) to load CT."
        # Detect tumor type from message
        tumor_type = self._detect_tumor_type_from_message(message)
        if not tumor_type and not ctv_path:
            self.memory.store("last_segmentation_success", False)
            return (
                "请先明确需要分割的肿瘤部位，或提供已有 CTV 标签文件。"
                "例如：胰腺癌、肝癌、肾癌、肺癌、结直肠癌、前列腺。"
            )
        params = {"image": ct_image, "label_path": ctv_path}
        if tumor_type:
            params["tumor_type"] = tumor_type
        # Reuse is the safe default, but an explicit repeat/overwrite request
        # must reach the same execution gateway as the LLM path.
        if self._force_reexecution_requested(message=message):
            params["force_reexecution"] = True
        result = self._execute_tool_with_memory("ctv_segmentation", params)
        self.memory.log_tool_call("ctv_segmentation", params, result)
        if result.success:
            self.memory.store("last_segmentation_success", True)
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
            self.memory.store("label_grid_orientation", result.metadata.get("label_grid_orientation") or "LPI")
            # Replace provenance-bearing sidecars atomically. A manual CTV
            # upload must clear any previous model multi-label/OAR payload.
            self.memory.store("ctv_full_labels", result.metadata.get("full_label_array"))
            self.memory.store("ctv_embedded_oar_array", result.metadata.get("oar_array"))
            from web.structure_service import replace_structure_source
            replace_structure_source(self.memory, "ctv")
            return result.message
        self.memory.store("last_segmentation_success", False)
        return f"CTV segmentation failed: {result.error}"

    def _handle_oar_segmentation_request(self, message: str) -> str:
        ct_image = self.memory.retrieve("ct_image")
        oar_path = self.memory.retrieve("oar_path")
        if ct_image is None:
            self.memory.store("last_segmentation_success", False)
            return "Please provide CT image path first."
        params = {"image": ct_image, "label_path": oar_path}
        if self._force_reexecution_requested(message=message):
            params["force_reexecution"] = True
        result = self._execute_tool_with_memory("oar_segmentation", params)
        self.memory.log_tool_call("oar_segmentation", {}, result)
        if result.success:
            self.memory.store("last_segmentation_success", True)
            self.memory.store("oar_array", result.metadata.get("oar_array"))
            # Keep the same durable provenance contract as the web upload
            # route.  Chat-triggered re-segmentation must hydrate the Data
            # Tree and label volume after a reload instead of leaving only a
            # transient tool message in AgentMemory.
            self.memory.store("oar_label_data", result.metadata.get("oar_label_data") or result.metadata.get("oar_array"))
            if "organ_names" in result.metadata:
                self.memory.store("organ_names", result.metadata["organ_names"])
            if "organ_counts" in result.metadata:
                self.memory.store("organ_counts", result.metadata["organ_counts"])
            self.memory.store(
                "oar_source",
                result.metadata.get("oar_source") or (
                    "uploaded_unknown" if oar_path else "unknown_model"
                ),
            )
            self.memory.store(
                "oar_mask_provenance",
                result.metadata.get("oar_mask_provenance") or (
                    "uploaded_unknown" if oar_path else "model"
                ),
            )
            self.memory.store("label_grid_orientation", result.metadata.get("label_grid_orientation") or "LPI")
            self.memory.store("oar_segmented", True)
            self.memory.store("oar_is_full", True)
            from web.structure_service import replace_structure_source
            replace_structure_source(self.memory, "oar")
            return result.message
        self.memory.store("last_segmentation_success", False)
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
        in_lowest_energy: Optional[float] = None,
        out_highest_energy: Optional[float] = None,
        dose_value_unit: Optional[str] = "gy",
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
        if reference_direc is None:
            ui_state = self.memory.get_ui_state() if hasattr(self, 'memory') and hasattr(self.memory, 'get_ui_state') else {}
            planning_state = ui_state.get("planning") if isinstance(ui_state.get("planning"), dict) else {}
            reference_direc = resolve_reference_direction_input(
                planning_state,
                self.config,
                default="auto",
            )
        in_lowest_from_argument = in_lowest_energy is not None
        out_highest_from_argument = out_highest_energy is not None
        in_lowest_energy = (
            in_lowest_energy
            if in_lowest_energy is not None
            else self.config.get("in_lowest_energy", DEFAULT_PRESCRIPTION_GY)
        )
        out_highest_energy = (
            out_highest_energy
            if out_highest_energy is not None
            else self.config.get("out_highest_energy", DEFAULT_PRESCRIPTION_GY)
        )
        resolved_value_unit = (
            dose_value_unit
            if in_lowest_from_argument or out_highest_from_argument
            else self.config.get("dose_value_unit")
        )
        in_lowest_gy = planning_dose_value_to_gy(
            in_lowest_energy,
            value_unit=resolved_value_unit,
        )
        out_highest_gy = planning_dose_value_to_gy(
            out_highest_energy,
            value_unit=resolved_value_unit,
        )
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
                "in_lowest_dose": in_lowest_gy,
                "out_highest_dose": out_highest_gy,
                "dose_value_unit": "gy",
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
            # Keep the historical workspace key in normalized model units so
            # viewer APIs and restored sessions have one stable array contract.
            # Store the physical-Gy representation separately.
            self.memory.store("dose_distribution_gy", dose_distribution)
            self.memory.store(
                "dose_distribution_physical_gy",
                dose_distribution * DOSE_MODEL_SCALE_GY,
            )
            self.memory.store("dose_scale_gy", DOSE_MODEL_SCALE_GY)
            self.memory.store("plan_config", {
                "dose_value_unit": "gy",
                "in_lowest_energy": float(in_lowest_gy),
                "out_highest_energy": float(out_highest_gy),
                "in_lowest_dose_gy": float(in_lowest_gy),
                "out_highest_dose_gy": float(out_highest_gy),
                "dose_scale_gy": DOSE_MODEL_SCALE_GY,
            })
            self.memory.store("total_seeds", total_seeds)
            logger.info(f"  Planned {total_seeds} seeds")

            logger.info("Step 7: Dose Evaluation")
            dose_spacing = ct_image.GetSpacing() if hasattr(ct_image, "GetSpacing") else [1.0, 1.0, 1.0]
            eval_result = self.registry.execute(
                "dose_evaluation", dose_array=dose_distribution * DOSE_MODEL_SCALE_GY, ctv_mask=ctv_array,
                oar_mask=oar_array, prescribed_dose=in_lowest_gy, target_value=target_value,
                oar_constraints=dose_constraints,
                organ_names=oar_metadata.get("organ_names", {}),
                spacing=dose_spacing,
                tumor_type=self.memory.retrieve("tumor_type_used") or "",
            )
            self.memory.log_tool_call(
                "dose_evaluation",
                {"prescribed_dose": in_lowest_gy},
                eval_result,
            )
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

        dose_value_unit = self.config.get("dose_value_unit")
        prescription_gy = planning_dose_value_to_gy(
            self.config.get("in_lowest_energy", DEFAULT_PRESCRIPTION_GY),
            value_unit=dose_value_unit,
        )
        prescription = planning_dose_value_to_model(
            prescription_gy,
            value_unit="gy",
        )
        out_highest_gy = planning_dose_value_to_gy(
            self.config.get("out_highest_energy", DEFAULT_PRESCRIPTION_GY),
            value_unit=dose_value_unit,
        )
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
                resolve_reference_direction_input(planning_state, self.config, default="auto"),
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
                in_lowest_dose=prescription_gy,
                out_highest_dose=out_highest_gy,
                dose_value_unit="gy",
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
            dose_array=cumulative_dose * DOSE_MODEL_SCALE_GY,
            ctv_mask=ctv_grid,
            target_value=target_value,
            oar_mask=oar_grid,
            organ_names=self.memory.retrieve("organ_names", {}) or {},
            oar_constraints=self.config.get("oar_constraints", {}) or {},
            prescribed_dose=prescription_gy,
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
        self.memory.store("dose_distribution_gy", cumulative_dose)
        self.memory.store(
            "dose_distribution_physical_gy",
            cumulative_dose * DOSE_MODEL_SCALE_GY,
        )
        self.memory.store("dose_scale_gy", DOSE_MODEL_SCALE_GY)
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
