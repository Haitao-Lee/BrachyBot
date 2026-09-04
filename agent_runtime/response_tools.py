"""Response and tool normalization mixin methods for BrachyAgent.

The methods are kept as regular class methods so the public AgenticSys.BrachyAgent
API remains compatible while the monolithic implementation is easier to review.
"""

import json
import logging
import math
import re
from typing import Dict, List, Optional


from agent_runtime.core import ToolResultPipeline
from agent_runtime.response_contract import presentation_fallback_message
from agent_runtime.turn_policy import (
    is_current_case_dose_recompute_request,
    is_planning_reexecution_request,
    is_surgical_guide_generation_request,
    is_viewer_result_display_request,
    requires_planning_before_guide,
    resolve_report_request_action,
    resolve_session_content_target,
    resolve_session_visual_location_target,
    _has_visual_annotation_request,
)
from plans.dose_pre.model_loader import resolve_prescription_gy

logger = logging.getLogger(__name__)


class ResponseToolMixin:
    @staticmethod
    def _force_reexecution_requested(message: str = "", params: Optional[Dict] = None) -> bool:
        """Detect an explicit request to replace a reusable clinical result.

        State-aware routing remains the default.  This flag is deliberately
        limited to reuse decisions; it never bypasses model, geometry, or
        safety validation.
        """
        params = params or {}
        if any(bool(params.get(key)) for key in ("force_reexecution", "force", "overwrite", "rerun")):
            return True
        if is_planning_reexecution_request(message):
            return True
        return bool(re.search(
            r"(?:\u518d\u6b21|\u518d\u5206\u5272|\u91cd\u65b0\u5206\u5272|\u91cd\u65b0\u89c4\u5212|\u518d\u89c4\u5212|\u91cd\u505a|\u91cd\u8dd1|\u5ffd\u7565\u73b0\u6709|\u4e0d\u4f7f\u7528\u73b0\u6709|"
            r"force|overwrite|rerun|re-run|run again|ignore (?:the )?existing)",
            str(message or "").lower(),
            re.IGNORECASE,
        ))

    def _segmentation_scope(self, message: str) -> str:
        """Resolve the requested segmentation scope without broadening it.

        A generic repeat command inherits the last explicit CTV/OAR scope,
        matching the case-local, node-oriented behavior users expect from
        tools such as 3D Slicer.
        """
        text = str(message or "").lower()
        wants_oar = bool(re.search(r"\boar\b|\borgan(?:s)?\b|\u5371\u53ca\u5668\u5b98|\u5668\u5b98", text, re.IGNORECASE))
        wants_ctv = bool(re.search(r"\bctv\b|\btumou?r\b|\blesion\b|\u9776\u533a|\u80bf\u7624", text, re.IGNORECASE))
        if wants_oar and wants_ctv:
            return "all"
        if wants_oar:
            return "oar"
        if wants_ctv:
            return "ctv"
        previous = self.memory.retrieve("last_segmentation_target")
        return previous if previous in {"ctv", "oar", "all"} else "all"

    @staticmethod
    def _full_oar_scope_requested(message: str) -> bool:
        """Return whether the user explicitly asked for a complete OAR set.

        This is intentionally narrower than merely mentioning an organ. It
        prevents the request-scope guard from turning a genuine planning/full
        OAR request into a partial anatomy result.
        """
        text = str(message or "").lower()
        return bool(re.search(
            r"(?:\b(?:all|every|whole|full|complete|total)\b|全部|所有|全套|完整|全身).{0,16}"
            r"(?:\boar\b|\borgans?\b|危及器官|器官)"
            r"|(?:\boar\b|\borgans?\b|危及器官|器官).{0,16}"
            r"(?:\b(?:all|every|whole|full|complete|total)\b|全部|所有|全套|完整|全身)",
            text,
            re.IGNORECASE,
        ))

    def _requested_oar_organs(self, message: str) -> List[str]:
        """Resolve named OAR entities from a focused user request.

        This is not a response whitelist and does not decide whether an OAR
        tool should run. The LLM/policy still owns the action decision. Once
        it has selected an OAR tool, this entity scope stops that tool from
        broadening a request such as ``肝脏和肿瘤`` into a full structure set.
        """
        if self._full_oar_scope_requested(message):
            return []
        try:
            from tool_factory.OAR_seg.totalsegmentator_oar import (
                extract_totalseg_organ_filter_from_text,
            )
            return extract_totalseg_organ_filter_from_text(message)
        except Exception as exc:
            # Scope resolution must never make the clinical tool unavailable.
            # The tool boundary still validates an explicit organ_filter.
            logger.debug("Unable to resolve focused OAR entities: %s", exc)
            return []

    def _explicit_organ_plus_tumor_scope(self, message: str) -> List[str]:
        """Return named organs only for an explicit anatomy-plus-tumor ask.

        A tumor site alone (for example ``分割肝癌``) is a CTV request. A
        coordinated request (``分割肝脏和肿瘤``) authorizes both the tumor CTV
        and the named anatomy mask. This avoids inventing a broad OAR action
        from a cancer-site name while still honoring the user's two objects.
        """
        organs = self._requested_oar_organs(message)
        if not organs:
            return []
        text = str(message or "").lower()
        has_tumor = bool(re.search(
            r"\b(?:tumou?r|lesion|cancer)\b|肿瘤|肿块|病灶|癌",
            text,
            re.IGNORECASE,
        ))
        has_coordinating_connector = bool(re.search(
            r"\b(?:and|with)\b|和|与|及|以及|、|,|，",
            text,
            re.IGNORECASE,
        ))
        return organs if has_tumor and has_coordinating_connector else []

    def _normalize_oar_tool_params(self, params: Dict, message: str = "") -> Dict:
        """Normalize and cap named OAR calls at the execution contract.

        The caller may use friendly aliases, but a current-turn explicit
        anatomy scope always wins over a provider's omitted or overly broad
        filter. An unknown explicit value is preserved for the OAR tool to
        reject rather than silently expanding to every organ.
        """
        normalized = dict(params or {})
        raw_filter = None
        for alias in (
            "organ_filter", "organs", "target_organs", "requested_organs",
            "requested_structures", "structures",
        ):
            if alias not in normalized:
                continue
            value = normalized.get(alias)
            if value is not None and value != "":
                raw_filter = value
                break
        for alias in (
            "organs", "target_organs", "requested_organs",
            "requested_structures", "structures",
        ):
            normalized.pop(alias, None)

        if message and self._full_oar_scope_requested(message):
            normalized.pop("organ_filter", None)
            return normalized

        message_scope = self._requested_oar_organs(message) if message else []
        # The user's named structures are the outer boundary for this turn;
        # do not let an LLM-provided generic/full OAR choice widen it.
        if message_scope:
            raw_filter = message_scope
        if raw_filter is None:
            normalized.pop("organ_filter", None)
            return normalized

        try:
            from tool_factory.OAR_seg.totalsegmentator_oar import (
                normalize_totalseg_organ_filter,
            )
            normalized["organ_filter"] = normalize_totalseg_organ_filter(raw_filter)
        except Exception:
            # Preserve the explicit invalid payload. OARSegmentationTool will
            # return an actionable validation error instead of running a full
            # TotalSegmentator job as an unsafe fallback.
            normalized["organ_filter"] = raw_filter
        return normalized

    @staticmethod
    def _open_segmentation_target(message: str) -> Optional[str]:
        """Extract an explicit free-form anatomy target.

        A bare anatomy request is deliberately distinct from CTV/OAR language:
        ``segment the pancreas`` means a displayable anatomy mask, while
        ``segment the pancreatic tumor`` remains the dedicated CTV workflow.
        The returned prompt is concise and stable so repeated requests can
        replace the same session-owned Data Tree node.
        """
        text = str(message or "").strip().lower()
        if not re.search(
            r"(?:\bsegment(?:ation)?\b|\b(?:outline|delineate|extract)\b|"
            r"\u5206\u5272|\u52fe\u753b|\u52fe\u52d2|\u63d0\u53d6)",
            text,
            re.IGNORECASE,
        ):
            return None
        # Clinical target and OAR requests must never be reinterpreted as an
        # open mask, even when the sentence also contains a site name.
        if re.search(
            r"\b(?:ctv|oar|clinical\s+target\s+volume|tumou?r|lesion|"
            r"organs?\s+at\s+risk)\b|"
            r"\u9776\u533a|\u5371\u53ca\u5668\u5b98|\u80bf\u7624|\u75c5\u7076|\u75c5\u53d8",
            text,
            re.IGNORECASE,
        ):
            return None

        aliases = (
            ("shoulder joint", "shoulder joint"),
            ("shoulder", "shoulder"),
            ("liver", "liver"),
            ("pancreas", "pancreas"),
            ("kidney", "kidney"),
            ("spleen", "spleen"),
            ("heart", "heart"),
            ("liver", "liver"),
            ("\u80a9\u5173\u8282", "shoulder joint"),
            ("\u80a9", "shoulder"),
            ("\u809d\u810f", "liver"),
            ("\u80f0\u817a", "pancreas"),
            ("\u80be\u810f", "kidney"),
            ("\u80be", "kidney"),
            ("\u813e", "spleen"),
            ("\u5fc3\u810f", "heart"),
        )
        for alias, prompt in aliases:
            if alias in text:
                return prompt

        # Accept other explicit English anatomy names without allowing the
        # surrounding command or CT filename to become the prompt.
        match = re.search(
            r"\b(?:segment(?:ation)?|outline|delineate|extract)\s+(?:the\s+)?"
            r"([a-z][a-z0-9 -]{1,72}?)(?=\s+(?:from|in|on|of|for)\b|[?.!,;:]|$)",
            text,
            re.IGNORECASE,
        )
        if match:
            candidate = re.sub(r"\s+", " ", match.group(1)).strip(" -")
            if candidate and candidate not in {"ct", "ct image", "image"}:
                return candidate
        match = re.search(
            r"(?:\u5206\u5272|\u52fe\u753b|\u52fe\u52d2|\u63d0\u53d6)"
            r"(?:\u4e00\u4e0b|\u51fa|\u6211\u7684)?"
            r"([\u3400-\u4dbf\u4e00-\u9fff]{2,16})",
            text,
        )
        return match.group(1) if match else None

    @staticmethod
    def _is_image_tumor_measurement_request(message: str) -> bool:
        """Recognize a patient-specific tumor location/size request."""
        text = str(message or "").strip().lower()
        if not text:
            return False
        return (
            bool(re.search(
                r"(?:\bct\b|\bimage\b|\bscan\b|\bnifti\b|\buploaded\b|\bpatient\b|"
                r"\u56fe\u50cf|\u5f71\u50cf|\u4e0a\u4f20|\u60a3\u8005)", text, re.IGNORECASE,
            ))
            and bool(re.search(
                r"(?:\btumou?r\b|\blesion\b|\bcancer\b|\u80bf\u7624|\u80bf\u5757|\u75c5\u7076|\u764c)",
                text, re.IGNORECASE,
            ))
            and bool(re.search(
                r"(?:analy|where|location|size|volume|large|\u5206\u6790|\u5728\u54ea|\u4f4d\u7f6e|\u591a\u5927|\u4f53\u79ef)",
                text, re.IGNORECASE,
            ))
            and bool(re.search(
                r"(?:pancreas|pancreatic|liver|kidney|lung|colon|prostate|"
                r"\u80f0\u817a|\u809d|\u80be|\u80ba|\u7ed3\u80a0|\u524d\u5217\u817a)",
                text, re.IGNORECASE,
            ))
        )

    def _normalize_ctv_tool_params(self, params: Dict, message: str = "") -> Dict:
        """Normalize every CTV call alias before tool contract validation.

        Catalog-driven model calls historically used ``model``/``organ``
        while the unified CTV tool uses ``tumor_type``. Resolve both forms
        here and keep a second fallback to the current user turn so a model
        omission cannot erase a site that the user already supplied.
        """
        normalized = dict(params or {})
        if not normalized.get("image_path"):
            image_alias = normalized.get("ct_image_path") or normalized.get("ct_path")
            if image_alias:
                normalized["image_path"] = image_alias
        fallback_tumor_type = None
        for alias in (
            "tumor_type",
            "model",
            "tumor_site",
            "site",
            "organ",
            "organ_type",
        ):
            value = normalized.get(alias)
            if value is None or not str(value).strip():
                continue
            mapped = self._map_tumor_type(str(value))
            if not mapped:
                continue
            if mapped in self._SUPPORTED_AUTOMATIC_CTV_TYPES:
                normalized["tumor_type"] = mapped
                break
            if fallback_tumor_type is None:
                fallback_tumor_type = mapped
        for alias in ("model", "tumor_site", "site", "organ", "organ_type", "ct_image_path", "ct_path"):
            normalized.pop(alias, None)
        if not normalized.get("tumor_type"):
            inferred = None
            if message:
                try:
                    inferred = self._detect_tumor_type_from_message(message)
                except Exception:
                    inferred = None
            if not inferred:
                try:
                    inferred = self._detect_tumor_type_from_message("")
                except Exception:
                    inferred = None
            mapped = self._map_tumor_type(str(inferred)) if inferred else None
            if mapped:
                normalized["tumor_type"] = mapped
        if not normalized.get("tumor_type"):
            retrieve = getattr(self.memory, "retrieve", None)
            stored = retrieve("tumor_type_used") if callable(retrieve) else None
            mapped = self._map_tumor_type(str(stored)) if stored else None
            if mapped in self._SUPPORTED_AUTOMATIC_CTV_TYPES:
                normalized["tumor_type"] = mapped
        if not normalized.get("tumor_type") and fallback_tumor_type:
            # Preserve an unsupported value for the normal clarification/error
            # path, but only after current-message and persisted Session
            # context had a chance to resolve a valid route.
            normalized["tumor_type"] = fallback_tumor_type
        return normalized

    @staticmethod
    def _format_tool_result(tool_name: str, result, lang: str = "en") -> str:
        """Format tool result for display. Uses result.display, then auto-generates from metadata."""
        return ToolResultPipeline.format(tool_name, result, lang)

    # --- Analysis code template (used by direct execution) ---
    _ANALYSIS_CODE_TEMPLATE = """
import nibabel as nib
import numpy as np
import json

ct = nib.load('{ct_path}')
data = ct.get_fdata()
spacing = ct.header.get_zooms()

# Compute tissue distribution
total = data.size
tissues = []
for name, lo, hi in [("Air", -9999, -900), ("Fat", -900, -30), ("Soft tissue", -30, 200), ("Muscle/organ", 200, 400), ("Bone", 400, 9999)]:
    pct = np.sum((data >= lo) & (data < hi)) / total * 100
    tissues.append({{"name": name, "range": f"{{lo}}~{{hi}} HU" if lo > -9009 else f"< {{hi}} HU", "pct": round(pct, 1)}})

result = {{
    "dimensions": list(data.shape),
    "voxel_size": [round(float(s), 2) for s in spacing],
    "scan_range_cm": [round(data.shape[i]*float(spacing[i])/10, 1) for i in range(3)],
    "hu_range": [int(data.min()), int(data.max())],
    "mean_hu": round(float(data.mean()), 1),
    "tissues": tissues,
}}
print(json.dumps(result))
"""

    @staticmethod
    def _session_visual_location_screenshot_params(message: str, target: str) -> Dict:
        """Build a grounded screenshot plan for a live location question.

        The route deliberately produces a structured evidence request rather
        than a textual location answer.  Stable IDs are passed to the browser,
        which verifies that the object belongs to the active Session and is
        actually loaded/visible before it frames or annotates it.
        """
        text = str(message or "").strip()
        target = str(target or "").strip().lower()
        is_zh = bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))

        stable_refs: List[str] = []
        for raw in re.findall(
            r"\b(?:needle|seed|trajectory|planning)[_-][a-z0-9][a-z0-9_-]*\b",
            text.lower(),
            flags=re.IGNORECASE,
        ):
            prefix, _, _ = raw.partition("_")
            if not _:
                prefix, _, _ = raw.partition("-")
            ref = f"{prefix}:{raw}"
            if ref not in stable_refs:
                stable_refs.append(ref)

        # UI-control location is a different visual contract from a case
        # object location.  Capture the real toolbar, and use the stable DOM
        # id as the sole annotation target.  It must not be copied into the
        # planning-object or Data Tree identity fields.
        object_refs = list(stable_refs)
        data_tree_refs = list(stable_refs)
        layout = ""
        if target == "ui_control:viewer.reconstruct3d":
            views = ["overlay-controls"]
            stable_refs = ["reconstruct3DButton"]
            object_refs = []
            data_tree_refs = []
            layout = "single"
            title = "3D重建按钮位置" if is_zh else "3D reconstruction button location"
            description = (
                "定位 Viewer 工具栏中真实存在的 3D 重建按钮，并在截图中标注。"
                if is_zh
                else "Locate the real 3D reconstruction button in the Viewer toolbar and mark it in the screenshot."
            )
            focus = {"kind": "current-view"}
            overlays = {}
            hide_unrelated = False
            # A location question is itself a request for an unambiguous mark,
            # even when the user did not repeat the words "圈出" or "标注".
            annotation_policy = "required"
        elif target == "surgical_guide":
            views = ["viewer-3d", "data-tree"]
            stable_refs = ["surgical_guide:active"]
            object_refs = list(stable_refs)
            data_tree_refs = list(stable_refs)
            title = "手术导板位置" if is_zh else "Surgical guide location"
            description = (
                "定位当前已保存且实际可见的手术导板；仅在 Viewer/Data Tree 中验证后标注。"
                if is_zh
                else "Locate the saved surgical guide and annotate it only after it is verified visible in the Viewer and Data Tree."
            )
            focus = {"kind": "close-up", "padding": 0.35}
            overlays = {"surgical_guide": True}
            hide_unrelated = True
            annotation_policy = "required"
        elif target == "data_tree":
            views = ["data-tree"]
            title = "数据树位置" if is_zh else "Data Tree location"
            description = "定位当前数据树对象。" if is_zh else "Locate the current Data Tree object."
            focus = {"kind": "auto", "padding": 0.35}
            overlays = {}
            hide_unrelated = False
            annotation_policy = "required" if _has_visual_annotation_request(text) else "auto"
        elif target in {"dvh", "metrics"}:
            views = [target]
            title = "当前结果位置" if is_zh else "Current result location"
            description = "定位当前结果。" if is_zh else "Locate the current result."
            focus = {"kind": "current-view"}
            overlays = {}
            hide_unrelated = False
            annotation_policy = "required" if _has_visual_annotation_request(text) else "auto"
        elif target == "dose":
            views = ["viewer-axial", "viewer-sagittal", "viewer-coronal", "dvh"]
            title = "剂量结果位置" if is_zh else "Dose result location"
            description = "定位当前剂量结果。" if is_zh else "Locate the current dose result."
            focus = {"kind": "auto", "padding": 0.35}
            overlays = {"dose": True, "dose_contours": True}
            hide_unrelated = False
            annotation_policy = "required" if _has_visual_annotation_request(text) else "auto"
        elif target == "ct":
            views = ["viewer-axial", "viewer-sagittal", "viewer-coronal"]
            title = "CT影像位置" if is_zh else "CT image location"
            description = "定位当前CT影像。" if is_zh else "Locate the current CT image."
            focus = {"kind": "current-view"}
            overlays = {}
            hide_unrelated = False
            annotation_policy = "required" if _has_visual_annotation_request(text) else "auto"
        else:
            views = ["viewer-3d", "data-tree"]
            title = "规划对象位置" if is_zh else "Planning object location"
            description = "定位当前规划对象。" if is_zh else "Locate the current planning object."
            focus = {"kind": "close-up" if stable_refs else "auto", "padding": 0.35}
            overlays = {}
            hide_unrelated = bool(stable_refs)
            annotation_policy = "required" if _has_visual_annotation_request(text) else "auto"

        return {
            "mode": "chat",
            "views": views,
            "layout": layout or ("side-by-side" if len(views) == 2 else "auto"),
            "question": text,
            "title": title,
            "description": description,
            "object_ids": object_refs,
            "data_tree_node_ids": data_tree_refs,
            "highlight_object_ids": object_refs,
            "hide_unrelated": hide_unrelated,
            "focus": focus,
            "overlays": overlays,
            "visual_purpose": "locate",
            "analysis_required": True,
            "annotation_policy": annotation_policy,
            "target_refs": list(stable_refs),
        }

    def _detect_tool_request(self, message: str) -> Optional[List[Dict]]:
        """Detect explicit tool requests. Returns tool calls in user-specified order, or None.

        Called after local policy classification for deterministic clinical or
        browser actions. Semantic requests still go through the provider; this
        function only materializes commands whose target and parameters are
        unambiguous from the user's request.
        """
        # This is the only direct clinical call for a current Dose/DVH
        # refresh. Do it before the legacy action-pattern scan so wording such
        # as "重新计算DVH相关指标" cannot be mistaken for a full plan, and so
        # the route also works for older callers that did not install a local
        # policy first.
        if is_current_case_dose_recompute_request(message):
            return [{
                "id": "tool_direct_dose",
                "tool": "dose_recompute",
                "params": {},
            }]

        # Showing a saved planning result is a browser refresh, not a new
        # planning/dose operation and not a request for LLM prose. Keep the
        # action typed so the frontend can reload the active Session's
        # canonical results (seeds, needles, dose, DVH, meshes and guide).
        if is_viewer_result_display_request(message):
            return [{
                "id": "tool_ui_refresh_planning_viewer",
                "tool": "ui_controller",
                "params": {
                    "actions": [{
                        "target": "viewer.refresh_planning",
                        "command": "run",
                    }],
                },
            }]

        # A location question is not a guide-generation request.  Materialize
        # one state-safe screenshot plan before the generic clinical/action
        # scan so a provider cannot turn "where is the guide?" into a
        # mutating surgical_guide(action=generate) call.
        visual_location_target = resolve_session_visual_location_target(
            message,
            conversation=getattr(getattr(self, "memory", None), "conversation", None),
        )
        if visual_location_target:
            return [{
                "id": "tool_direct_session_visual_location",
                "tool": "ui_screenshot",
                "params": self._session_visual_location_screenshot_params(
                    message,
                    visual_location_target,
                ),
            }]

        msg = message.strip().lower()
        generic_target = self._open_segmentation_target(message)
        ct_path = self.memory.retrieve("ct_path") or ""
        if not ct_path:
            ct_path = (self.memory.get_ui_state() or {}).get("ct_path", "")
        requested_tumor_type = (
            self._detect_tumor_type_from_message(message)
            or self.memory.retrieve("tumor_type_used")
        )
        tumor_type = (
            self._map_tumor_type(requested_tumor_type)
            if requested_tumor_type else None
        )
        # An explicit bare-anatomy request wins over a remembered tumor site.
        # This is the key boundary between open masks and CTV planning.
        if generic_target:
            tumor_type = None
        if tumor_type not in self._SUPPORTED_AUTOMATIC_CTV_TYPES:
            tumor_type = None

        def ctv_params():
            params = {"image_path": ct_path}
            if tumor_type:
                params["tumor_type"] = tumor_type
            return params

        focused_oar_organs = self._explicit_organ_plus_tumor_scope(message)

        def oar_params():
            params = {"image_path": ct_path}
            if focused_oar_organs:
                params["organ_filter"] = list(focused_oar_organs)
            return params

        force_reexecution = self._force_reexecution_requested(message=message)
        segmentation_scope = self._segmentation_scope(message)

        # A local dependency plan is already an explicit business decision:
        # reuse the existing masks, rerun the planning pipeline with the live
        # planning parameters, and optionally generate the downstream guide.
        # Do not wait for a second provider round to rediscover this queue.
        # This is intentionally limited to the routing-created clinical plan;
        # arbitrary compound requests still go through the primary LLM.
        get_action_plan = getattr(self, "_current_action_plan", None)
        action_plan = get_action_plan() if callable(get_action_plan) else None
        planned_tools = set(getattr(action_plan, "tool_names", ()) or ())
        is_local_planning_plan = bool(
            action_plan is not None
            and action_plan.requires_tool("planning_pipeline")
            and planned_tools.issubset({
                "ctv_segmentation",
                "oar_segmentation",
                "planning_pipeline",
                "surgical_guide",
            })
        )

        # Explicit reconstruction commands are deterministic UI actions, not
        # clinical segmentation requests. Route them directly so an existing
        # uploaded OAR mask is reconstructed instead of being sent through
        # the LLM's segmentation/completeness path.
        wants_all_oar_3d = bool(re.search(
            r"(?:all|every|全部|所有).*(?:oar|organ|危及器官|器官).*(?:3d|3-d|三维).*(?:reconstruct|重建)"
            r"|(?:3d|3-d|三维).*(?:reconstruct|重建).*(?:all|every|全部|所有).*(?:oar|organ|危及器官|器官)",
            msg,
            re.IGNORECASE,
        ))
        if wants_all_oar_3d:
            return [{
                "id": "tool_ui_reconstruct_all_oar",
                "tool": "ui_controller",
                "params": {
                    "actions": [{
                        "target": "tree.group.reconstruct3d",
                        "command": "run",
                        "value": "oar",
                    }]
                },
            }]

        # Materialize an explicitly authorized local business plan before any
        # terminal-action shortcut.  The provider may have emitted only the
        # last step after the policy was created, but a guide cannot replace
        # the required re-planning step.  The normalizer still reuses ready
        # CTV/OAR masks and injects live parameters, so this is a queue
        # materialization step rather than a second keyword router.
        if is_local_planning_plan:
            normalizer = getattr(self, "_normalize_clinical_tool_calls", None)
            if callable(normalizer):
                requested_calls = []
                emitted_tools = set()
                for index, step in enumerate(action_plan.ordered_steps()):
                    tool_name = str(step.tool or "")
                    if tool_name not in {
                        "ctv_segmentation",
                        "oar_segmentation",
                        "planning_pipeline",
                        "surgical_guide",
                    } or tool_name in emitted_tools:
                        continue
                    params = dict(step.params or {})
                    if tool_name == "planning_pipeline":
                        params.setdefault("step", "full")
                    elif tool_name == "surgical_guide":
                        params.setdefault("action", "generate")
                    requested_calls.append({
                        "id": f"tool_action_plan_{index}_{tool_name}",
                        "tool": tool_name,
                        "params": params,
                    })
                    emitted_tools.add(tool_name)
                planned_calls = normalizer(requested_calls, message)
                if planned_calls:
                    return planned_calls

        # Guide generation is an explicit clinical action. Keep it on the
        # registered tool path so the model cannot replace it with Python code
        # or expose a disabled code_executor error to the user.
        if is_surgical_guide_generation_request(message):
            # A compound request belongs to the semantic action-plan path.
            # Returning a guide-only direct call here would discard the
            # preceding planning action before dependency normalization.
            if action_plan is None and requires_planning_before_guide(message):
                normalizer = getattr(self, "_normalize_clinical_tool_calls", None)
                if callable(normalizer):
                    planned_calls = normalizer(
                        [{
                            "id": "tool_planned_surgical_guide",
                            "tool": "surgical_guide",
                            "params": {"action": "generate"},
                        }],
                        message,
                    )
                    if planned_calls:
                        return planned_calls
                return None
            return [{
                "id": "tool_direct_surgical_guide",
                "tool": "surgical_guide",
                "params": {"action": "generate"},
            }]

        # A short correction such as "I meant rerun the plan" has no
        # standalone keyword that the legacy detector can turn into a tool
        # call.  When the current turn already contains the structured
        # dependency plan, seed the normalizer with its terminal operation so
        # it can build the complete queue and inject the missing prerequisites.
        if is_local_planning_plan:
            terminal_tool = (
                "surgical_guide"
                if action_plan.requires_tool("surgical_guide")
                else "planning_pipeline"
            )
            normalizer = getattr(self, "_normalize_clinical_tool_calls", None)
            if callable(normalizer):
                planned_calls = normalizer(
                    [{
                        "id": f"tool_planned_{terminal_tool}",
                        "tool": terminal_tool,
                        "params": (
                            {"action": "generate"}
                            if terminal_tool == "surgical_guide"
                            else {"step": "full"}
                        ),
                    }],
                    message,
                )
                if planned_calls:
                    return planned_calls

        # Find action keywords and their positions to preserve user's intended order
        # Bilingual patterns: Chinese terms below match Chinese user input
        # (segment, target, tumor, organ, OAR in the zh locale).
        ACTION_PATTERNS = [
            # A complete seed-implant planning request is deterministic once
            # a CT and a supported target type are known. Avoid a redundant
            # remote router call that merely rediscovered CTV -> OAR -> plan.
            (r'(?:\u653e\u5c04\u6027?\u7c92\u5b50(?:\u690d\u5165)?\u89c4\u5212|\u7c92\u5b50(?:\u690d\u5165)?\u89c4\u5212|\u8fd1\u8ddd\u79bb\u653e\u7597\u89c4\u5212|'
             r'brachytherapy\s+(?:implant\s+)?plan|treatment\s+plan|planning[_\s-]*pipeline)', 'plan_full'),
            # UTF-8-safe aliases; legacy mojibake patterns remain below for
            # compatibility with old transcripts.
            (r'(ctv|clinical\s+target\s+volume).{0,8}(segment|seg|\u5206\u5272)', 'segment_ctv'),
            (r'(segment|seg|\u5206\u5272).{0,8}(ctv|clinical\s+target\s+volume)', 'segment_ctv'),
            (r'(oar|organs?|\u5371\u53ca\u5668\u5b98).{0,8}(segment|seg|\u5206\u5272)', 'segment_oar'),
            (r'(segment|seg|\u5206\u5272).{0,8}(oar|organs?|\u5371\u53ca\u5668\u5b98)', 'segment_oar'),
            (r'(分析|analyze)', 'analyze'),
            (r'(ctv|靶区|临床靶区|病灶|肿瘤|tumor|lesion).{0,8}(分割|segment)', 'segment_ctv'),
            (r'(分割|segment).{0,8}(ctv|靶区|临床靶区|病灶|肿瘤|tumor|lesion)', 'segment_ctv'),
            (r'(oar|危及器官|器官).{0,5}(分割|segment)', 'segment_oar'),
            (r'(分割|segment).{0,5}(oar|危及器官|器官)', 'segment_oar'),
            # NOTE: "dose" alone is too broad — "screenshot to view dose
            # distribution" should route to ui_screenshot, not dose_engine.
            # Only match when the user explicitly asks to COMPUTE/EXECUTE
            # dose, not when they want to VIEW/SCREENSHOT existing dose
            # results.
            (r'(计算剂量|计算.*剂量|剂量.*计算|执行.*剂量|dose.*(calc|comput|run)|calc.*dose|comput.*dose|run.*dose)', 'dose'),
            (r'(切换|switch).{0,10}(viewer|查看|浏览|视图)', 'ui:panel:viewers'),
            (r'(切换|switch).{0,10}(input|输入)', 'ui:panel:input'),
            (r'(切换|switch).{0,10}(metrics|指标)', 'ui:panel:metrics'),
        ]
        action_positions = []
        matched_spans = []
        for pattern, action in ACTION_PATTERNS:
            for match in re.finditer(pattern, msg, re.IGNORECASE):
                start, end = match.span()
                overlaps = any(not (end <= s or start >= e) for s, e in matched_spans)
                if not overlaps:
                    action_positions.append((start, action))
                    matched_spans.append((start, end))

        # Deduplicate, keeping first occurrence of each action
        seen = set()
        ordered_actions = []
        for pos, action in sorted(action_positions):
            if action not in seen:
                seen.add(action)
                ordered_actions.append(action)

        # "Analyze the uploaded liver-tumor CT and tell me where/how large"
        # is an image-grounded CTV request, not a generic Python/HU analysis.
        # Keep full planning commands untouched; only replace the ambiguous
        # lightweight analysis action for this specific patient-data query.
        if (
            self._is_image_tumor_measurement_request(message)
            and "plan_full" not in ordered_actions
            and "segment_ctv" not in ordered_actions
        ):
            ordered_actions = [action for action in ordered_actions if action != "analyze"]
            ordered_actions.insert(0, "segment_ctv")

        if generic_target:
            # Remove any broad fallback that the legacy keyword detector might
            # have added for the same sentence, then route exactly one generic
            # mask request through BiomedParse.
            ordered_actions = [
                action for action in ordered_actions
                if action not in {"segment_ctv", "segment_oar", "segment_all"}
            ]
            ordered_actions.insert(0, "segment_generic")

        # If no specific segment found but generic "segment" is present, add segment_all
        has_specific_seg = (
            'segment_ctv' in seen or 'segment_oar' in seen or generic_target is not None
        )
        if not has_specific_seg:
            for match in re.finditer(r'(分割|segment|再分)', msg, re.IGNORECASE):
                start, end = match.span()
                overlaps = any(not (end <= s or start >= e) for s, e in matched_spans)
                if not overlaps:
                    ordered_actions.append(
                        'segment_oar' if segmentation_scope == 'oar' else
                        'segment_ctv' if segmentation_scope == 'ctv' else
                        'segment_all'
                    )
                    break

        # Handle "segment CTV and OAR" — detect both from a single "segment" action
        if has_specific_seg:
            has_ctv = 'segment_ctv' in seen
            has_oar = 'segment_oar' in seen
            # If we found CTV but not OAR, check if OAR keywords appear in the message
            if has_ctv and not has_oar:
                if re.search(r'(oar|危及器官|器官)', msg, re.IGNORECASE):
                    ordered_actions.append('segment_oar')
            elif has_oar and not has_ctv:
                if re.search(r'(ctv|靶区|临床靶区)', msg, re.IGNORECASE):
                    ordered_actions.append('segment_ctv')
            # A coordinated request such as "分割肝脏和肿瘤" explicitly
            # names an anatomy mask plus a CTV candidate. Add only the named
            # OAR action; the OAR params below retain that same subset.
            if (
                focused_oar_organs
                and 'segment_ctv' in ordered_actions
                and 'segment_oar' not in ordered_actions
            ):
                ordered_actions.append('segment_oar')

        if not ordered_actions:
            # A clarification reply such as "pancreas" has no action verb.
            # Restore the complete action contract recorded by the previous
            # turn instead of reducing every clarification to CTV only. This
            # is what preserves "execute a full plan" across the two-turn
            # tumor-site clarification flow.
            pending = self.memory.retrieve("pending_clarification") or {}
            if (
                isinstance(pending, dict)
                and pending.get("kind") == "tumor_site"
                and tumor_type
                and ct_path
            ):
                requested_actions = pending.get("requested_actions")
                if isinstance(requested_actions, (list, tuple)):
                    ordered_actions.extend(
                        action for action in requested_actions
                        if action in {"segment_ctv", "segment_oar", "segment_all", "plan_full"}
                    )
                if not ordered_actions:
                    ordered_actions.append("segment_ctv")
            else:
                return None

        # CTV model selection is a clinical input, not a recoverable tool
        # default. Leave ambiguous or unsupported target requests to the LLM,
        # whose system prompt asks one concise clarification question before
        # any CTV tool is called. OAR-only requests remain directly executable.
        if not tumor_type and any(
            action in {"segment_ctv", "segment_all", "plan_full"} for action in ordered_actions
        ):
            # Some legacy test/integration memory adapters are read-only. The
            # marker is an optimization for the next clarification turn, not
            # a prerequisite for safe behavior, so do not make it a hard
            # dependency of CTV ambiguity handling.
            if hasattr(self.memory, "store"):
                requested_actions = [
                    action for action in ordered_actions
                    if action in {"segment_ctv", "segment_oar", "segment_all", "plan_full"}
                ]
                if not requested_actions:
                    requested_actions = ["segment_ctv"]
                self.memory.store(
                    "pending_clarification",
                    {
                        "kind": "tumor_site",
                        "requested_tool": "ctv_segmentation",
                        "requested_actions": requested_actions,
                        "requested_workflow": (
                            "clinical_planning"
                            if "plan_full" in requested_actions
                            else "segmentation"
                        ),
                    },
                )
            return None

        # Map actions to tool calls
        tools = []
        for action in ordered_actions:
            # UI control actions
            if action.startswith('ui:'):
                _, target, value = action.split(':')
                tools.append({"id": f"tool_ui_{target}_{value}", "tool": "ui_controller",
                              "params": {"actions": [{"target": target, "command": "switch", "value": value}]}})
                continue

            if action == 'analyze' and ct_path and self.registry.is_available('code_executor'):
                code = self._ANALYSIS_CODE_TEMPLATE.format(ct_path=ct_path)
                tools.append({"id": "tool_direct_analysis", "tool": "code_executor",
                              "params": {"code": code, "description": "Analyze CT image"}})
            elif action == 'segment_ctv' and ct_path:
                params = ctv_params()
                if force_reexecution:
                    params["force_reexecution"] = True
                tools.append({"id": "tool_direct_ctv", "tool": "ctv_segmentation", "params": params})
            elif action == 'segment_oar' and ct_path:
                params = oar_params()
                if force_reexecution:
                    params["force_reexecution"] = True
                tools.append({"id": "tool_direct_oar", "tool": "oar_segmentation", "params": params})
            elif action == 'segment_generic' and ct_path and generic_target:
                tools.append({
                    "id": "tool_direct_biomedparse",
                    "tool": "biomedparse_segmentation",
                    "params": {
                        "image_path": ct_path,
                        "target": generic_target,
                        "prompt": generic_target,
                    },
                })
            elif action == 'segment_all' and ct_path:
                ctv_call = ctv_params()
                oar_call = oar_params()
                if force_reexecution:
                    ctv_call["force_reexecution"] = True
                    oar_call["force_reexecution"] = True
                tools.append({"id": "tool_direct_ctv", "tool": "ctv_segmentation", "params": ctv_call})
                tools.append({"id": "tool_direct_oar", "tool": "oar_segmentation", "params": oar_call})
            elif action == 'plan_full' and ct_path:
                # A full planning request is intentionally explicit.  The
                # caller receives segmentation completion events before the
                # planning tool starts, allowing the browser to publish masks
                # into the Data Tree and 2D/3D viewers in parallel with the
                # remaining clinical computation.
                ctv_call = ctv_params()
                oar_call = {"image_path": ct_path}
                if force_reexecution:
                    ctv_call["force_reexecution"] = True
                    oar_call["force_reexecution"] = True
                tools.extend([
                    {"id": "tool_direct_ctv", "tool": "ctv_segmentation", "params": ctv_call},
                    {"id": "tool_direct_oar", "tool": "oar_segmentation", "params": oar_call},
                    {
                        "id": "tool_direct_plan",
                        "tool": "planning_pipeline",
                        "params": {
                            "ct_image_path": ct_path,
                            "mode": "rule_based",
                            "step": "full",
                        },
                    },
                    # planning_pipeline deliberately invalidates an older
                    # guide because the needle geometry changed.  Generate a
                    # fresh, case-scoped guide as an explicit, traceable
                    # completion step instead of relying solely on a later
                    # browser refresh to notice the stale artifact.
                    {
                        "id": "tool_direct_surgical_guide",
                        "tool": "surgical_guide",
                        "params": {"action": "generate"},
                    },
                ])
            elif action == 'dose' and ct_path:
                # Route an explicit conversational dose action to the
                # application-level capability.  ``dose_engine`` is the
                # low-level model contract and requires raw CT/seed arrays;
                # the high-level tool resolves the active Planning itself.
                tools.append({"id": "tool_direct_dose", "tool": "dose_recompute", "params": {}})

        return tools or None

    def _execute_direct_tools(self, tools: List[Dict], steps: List, step_id_ref: List[int], yield_event=None):
        """Execute tools with validation and recovery. Shared by streaming and non-streaming paths.

        Args:
            yield_event: Optional callback(step_data) called after each tool completes,
                         enabling incremental UI updates in streaming mode.
        """
        _lang = self.memory.user_lang
        for tc in tools:
            step_id_ref[0] += 1
            tool_step = {
                "id": step_id_ref[0], "type": "tool", "title": f"Direct: {tc['tool']}",
                "content": json.dumps(tc['params'], default=str)[:200],
                "status": "pending", "tool": tc['tool'], "params": tc['params'],
            }
            steps.append(tool_step)
            # Yield pending step for streaming UI
            if yield_event:
                yield_event(tool_step)

            try:
                result = self._execute_tool_with_memory(tc['tool'], dict(tc['params']))
                tool_step["status"] = "done" if result.success else "error"
                tool_step["result"] = self._format_tool_result(tc['tool'], result, lang=_lang)
                tool_step["metadata"] = (
                    ToolResultPipeline.trace_metadata(tc["tool"], result.metadata)
                    if result.success
                    else {}
                )
                tool_step["data"] = result.data if result.success else {}
                if tc["tool"] in ("ctv_segmentation", "oar_segmentation", "biomedparse_segmentation") and result.success:
                    self.memory.store("pending_clarification", None)
                    if tc["tool"] == "biomedparse_segmentation":
                        self.memory.store("last_segmentation_target", "generic")
                    else:
                        self.memory.store(
                            "last_segmentation_target",
                            "ctv" if tc["tool"] == "ctv_segmentation" else "oar",
                        )
                # Store tool call + result in conversation for context persistence
                self.memory.add_message("assistant", f"[Called {tc['tool']}]")
                _reason = result.error or result.message or "execution failed"
                result_summary = result.message[:500] if result.success else f"Error: {_reason}"
                self.memory.add_message("user", f"[Tool result: {result_summary}]")
                if not result.success and tc["tool"] in {
                    "ctv_segmentation", "oar_segmentation", "planning_pipeline"
                }:
                    logger.info(
                        "Stopping direct clinical chain after failed prerequisite: %s",
                        tc["tool"],
                    )
                    if yield_event:
                        yield_event(tool_step)
                    break
            except Exception as e:
                tool_step["status"] = "error"
                tool_step["result"] = str(e)
                logger.error(f"Direct tool failed: {tc['tool']}: {e}")
                self.memory.add_message("assistant", f"[Called {tc['tool']}]")
                self.memory.add_message("user", f"[Tool result: Error: {str(e)[:200]}]")
                if tc["tool"] in {
                    "ctv_segmentation", "oar_segmentation", "planning_pipeline"
                }:
                    if yield_event:
                        yield_event(tool_step)
                    break
            # Yield completed step for streaming UI (enables incremental viewer updates)
            if yield_event:
                yield_event(tool_step)

        # Build raw results summary, then synthesize with LLM
        raw_results = self._build_direct_response(steps, _lang)
        user_msg = ""
        for msg in reversed(self.memory.conversation):
            if msg.get("role") == "user":
                candidate = str(msg.get("content", "") or "")
                # Tool results are persisted as synthetic user records for
                # context continuity. They are not the user's question and
                # must not become the language/response-contract input for
                # the visible parent reply.
                if candidate.startswith("[Tool result:"):
                    continue
                user_msg = candidate
                break
        query_type = self._classify_query_type(user_msg)
        direct_tool_names = {
            str(step.get("tool") or "")
            for step in steps
            if step.get("type") == "tool"
        }
        # dose_recompute already has a complete, localized formatter and a
        # deterministic comparison summary. A second LLM synthesis adds cost
        # and can obscure the authoritative result, so return that contract
        # directly. Other direct operations keep their established synthesis
        # path because they may contain richer multi-tool context.
        if direct_tool_names == {"dose_recompute"}:
            response = raw_results
        elif (
            getattr(getattr(self, "_active_turn_policy", None), "intent", None)
            == "session_visual_location_query"
            and direct_tool_names == {"ui_screenshot"}
        ):
            # This is a typed two-stage presentation turn. The browser owns
            # the capture and will launch one hidden multimodal child for the
            # actual user-facing explanation; do not let the parent response
            # be mistaken for that explanation by streaming or replay code.
            self._visual_analysis_pending = True
            # Keep the visible parent response useful without invoking a
            # second text-only synthesis call. The browser owns the grounded
            # screenshot and the hidden multimodal child owns the explanation.
            response = presentation_fallback_message(
                _lang,
                user_msg,
                ("ui_screenshot",),
            )
        else:
            response = self._synthesize_with_llm(raw_results, steps, _lang, user_msg, query_type)

        # Quality review DISABLED (2026-06-22).
        # if self.multi_agent_wrapper and self.multi_agent_wrapper.enabled:
        #     ...

        return response

    def _build_direct_response(self, steps: List, lang: str) -> str:
        """Build structured response. Delegates to ToolResultPipeline."""
        return ToolResultPipeline.format_steps(steps, lang)

    # BUG FIX 2026-06-16 (LLM response still brief): server-side
    # generation of a comprehensive planning report. Reads metrics
    # directly from memory and assembles a 10-section markdown
    # report — guaranteed to be detailed regardless of LLM behavior.
    def _build_planning_report(self, lang: str, steps: List = None) -> str:
        """Build a comprehensive planning report directly from
        stored metrics. Used to bypass the LLM synthesis when the
        user explicitly runs a planning pipeline, because the LLM
        was producing brief 5-row tables ignoring the detailed
        template prompt.
        """
        is_zh = lang == "zh"
        # Pull all the relevant metrics from memory. BUG FIX 2026-06-17
        # (empty report): the 'metrics' key holds the FLAT dict that
        # dose_evaluation populates. But for some planning modes
        # (e.g. rl) the 'metrics' key is not populated, while
        # 'dose_metrics' (raw nested dict) IS stored. Fall back to
        # dose_metrics if metrics is empty.
        metrics = self.memory.retrieve("metrics", {}) or {}
        if not metrics:
            dose_metrics_raw = self.memory.retrieve("dose_metrics", {}) or {}
            # If dose_metrics is the nested {metrics: {CTV: {...}, oars: ...}, ...}
            # shape, pull the target sub-dict (CTV) to the top level.
            if isinstance(dose_metrics_raw, dict) and "metrics" in dose_metrics_raw:
                nested = dose_metrics_raw.get("metrics", {}) or {}
                ctv_sub = nested.get("CTV", {}) if isinstance(nested, dict) else {}
                if ctv_sub:
                    metrics = dict(dose_metrics_raw)
                    metrics.update(ctv_sub)
                else:
                    metrics = dose_metrics_raw
            else:
                metrics = dose_metrics_raw
        total_seeds = self.memory.retrieve("total_seeds", 0) or 0
        num_traj = self.memory.retrieve("num_trajectories", 0) or 0
        ctv_voxels = self.memory.retrieve("ctv_voxels", 0) or 0
        logger.info(f"[_build_planning_report] ctv_voxels={ctv_voxels}, ctv_array={'exists' if self.memory.retrieve('ctv_array') is not None else 'None'}, tumor_type_used='{self.memory.retrieve('tumor_type_used', '')}'")
        # Fallback: compute from ctv_array if not stored directly
        if not ctv_voxels:
            ctv_array = self.memory.retrieve("ctv_array")
            if ctv_array is not None:
                try:
                    import numpy as _np
                    ctv_voxels = int(_np.sum(_np.asarray(ctv_array) > 0))
                    self.memory.store("ctv_voxels", ctv_voxels)
                except Exception as exc:
                    logger.debug("Could not derive CTV voxel count from ctv_array: %s", exc)
        tumor_type = self.memory.retrieve("tumor_type_used", "")
        organ_names = self.memory.retrieve("organ_names", {}) or {}

        # Compute CTV volume in cm³ — prefer pre-computed value
        ctv_vol_cm3 = None
        _cvm3 = self.memory.retrieve("ctv_volume_mm3")
        if _cvm3:
            ctv_vol_cm3 = _cvm3 / 1000.0
        elif ctv_voxels:
            spacing = self.memory.retrieve("ct_spacing")
            if spacing and len(spacing) >= 3:
                sx, sy, sz = (float(spacing[0]), float(spacing[1]), float(spacing[2]))
                if sx > 0 and sy > 0 and sz > 0:
                    vol_mm3 = ctv_voxels * sx * sy * sz
                    ctv_vol_cm3 = vol_mm3 / 1000.0

        # Current plan configuration stores physical Gy. The resolver also
        # migrates unit-less legacy Rx multipliers.
        plan_config = self.memory.retrieve("plan_config") or {}
        rx_gy = resolve_prescription_gy(plan_config, metrics)

        # BUG FIX 2026-06-17 (None format): wrap metric reads with
        # `or 0` so None values don't crash :.1f / :.0f format specs.
        # Earlier code used metrics.get(k, 0) which returns None
        # when the key exists but value is None — the format spec
        # then raised "unsupported format string passed to NoneType".
        #
        # BUG FIX 2026-06-17 (plan_score double scaling): plan_score
        # is already on a 0-100 scale (e.g. 92.71 for a great plan).
        # Multiplying by 100 then formatting as :.0f yields 9271.
        # Section 5 displays it correctly as 93/100 (no scaling).
        # The workflow summary was incorrectly doing `*100` again.
        v100 = (metrics.get("v100") or 0) * 100
        v150 = (metrics.get("v150") or 0) * 100
        v200 = (metrics.get("v200") or 0) * 100
        d90 = metrics.get("d90") or 0
        dmean = metrics.get("dmean") or 0
        d2 = metrics.get("d2") or 0
        ci = metrics.get("ci") or 0
        hi = metrics.get("hi") or 0
        ps = metrics.get("plan_score") or 0
        v100_frac = metrics.get("v100") or 0
        d90_gy = metrics.get("d90") or 0
        # ps is already 0-100, do not multiply again
        ps_pct = ps

        # Helper for zh/en label lookup
        def L(zh, en):
            return zh if is_zh else en

        try:
            from tool_factory.report_context import (
                build_report_context,
                format_prescription_rationale_markdown,
                format_tumor_assessment_markdown,
            )

            def _report_lookup(key, default=None):
                if key == "plan_config":
                    return self.memory.retrieve(key) or getattr(self, "config", {}) or default
                return self.memory.retrieve(key, default)

            report_context = build_report_context(_report_lookup)
            tumor_assessment_md = format_tumor_assessment_markdown(report_context, lang)
            prescription_rationale_md = format_prescription_rationale_markdown(report_context, lang)
        except Exception as exc:
            logger.warning(f"Failed to build report context: {exc}")
            report_context = {}
            tumor_assessment_md = ""
            prescription_rationale_md = ""

        def _ctv_source_labels(source, declared_type):
            source = str(source or "").strip()
            declared_type = str(declared_type or "").strip()
            if source in {"manual_label", "label_path", "user_label"}:
                location = declared_type
                if location in {"manual_label", "label_path", "user_label", "unknown"}:
                    location = ""
                location = location.replace("_", " ").replace("nnunet ", "").replace("voco ", "")
                return (
                    location or L("用户提供的 CTV", "user-provided CTV"),
                    L("手动/导入 CTV 标签", "manual/imported CTV label"),
                )
            model = declared_type if source == "model" else (declared_type or source)
            if not model or model == "unknown":
                return (L("未记录", "not recorded"), L("未记录", "not recorded"))
            if source.startswith("sat3d") or model.startswith("sat3d_"):
                site = model.removeprefix("sat3d_").replace("_tumor", "").replace("_", " ")
                return (
                    f"SAT3D {site}",
                    L("SAT3D 研究候选轮廓（需临床复核）", "SAT3D research candidate (clinical review required)"),
                )
            if source.startswith("biomedparse") or model.startswith("biomedparse_"):
                site = (
                    model.removeprefix("biomedparse_")
                    .replace("_lesion", "")
                    .replace("_primary", "")
                    .replace("_cancer", "")
                    .replace("_tumor", "")
                    .replace("_", " ")
                )
                return (
                    f"BiomedParse v2 {site}",
                    L(
                        "BiomedParse v2 自动文本引导候选轮廓（需临床复核）",
                        "BiomedParse v2 automatic text-guided candidate (clinical review required)",
                    ),
                )
            clean = model.replace("_", " ").replace("nnunet ", "").replace("voco ", "")
            return (clean, f"CTV model ({model})")

        def _label_id_from_generic_name(name):
            s = str(name or "").strip().lower().replace("-", "_").replace(" ", "_")
            for prefix in ("oar_", "organ_", "label_"):
                if s.startswith(prefix):
                    tail = s[len(prefix):]
                    if tail.isdigit():
                        return int(tail)
            return None

        def _display_organ_name(name):
            label_id = _label_id_from_generic_name(name)
            if label_id is None:
                return str(name)
            for key in (label_id, str(label_id)):
                resolved = organ_names.get(key) if isinstance(organ_names, dict) else None
                if resolved and not str(resolved).lower().startswith(("oar_", "organ_", "label_")):
                    return str(resolved)
            nnunet_oar_names = {201: "artery", 202: "vein", 203: "pancreas"}
            if label_id in nnunet_oar_names:
                return nnunet_oar_names[label_id]
            try:
                from tool_factory.OAR_seg.totalsegmentator_oar import TOTALSEG_LABEL_MAPPING
                resolved = TOTALSEG_LABEL_MAPPING.get(label_id)
                if resolved:
                    return resolved
            except Exception as exc:
                logger.debug("Could not import TotalSegmentator label mapping for label %s: %s", label_id, exc)
            return f"Organ {label_id}"

        def _metric_dmax(om):
            return (om.get('dmax') or om.get('max_dose') or 0) if isinstance(om, dict) else 0

        lines = []
        # Surgical-guide generation is part of the full planning delivery
        # contract. Report its real outcome from the bound tool step, falling
        # back to the persisted guide only when this report is rebuilt after a
        # refresh. This prevents a successful dose plan from being presented
        # as a successful printable guide when guide generation actually failed.
        try:
            from web.surgical_guide import guide_status_payload

            guide_status = guide_status_payload(self)
            guide_state = guide_status.get("guide") or {}
        except Exception:
            # A legacy/lightweight test agent may not expose the new resolver.
            # In that case rely only on an explicit completed tool step below;
            # never fabricate a ready guide from an empty alias.
            guide_status = {}
            guide_state = {}
        guide_step = None
        if steps:
            for candidate in reversed(steps):
                if candidate.get("tool") == "surgical_guide":
                    guide_step = candidate
                    break

        guide_summary = ""
        if guide_step and guide_step.get("status") == "error":
            guide_summary = L(
                "\u751f\u6210\u5931\u8d25\uff1b\u8bf7\u67e5\u770b\u6267\u884c\u8ffd\u8e2a\u4e2d\u7684\u5bfc\u677f\u9519\u8bef\u8be6\u60c5\u3002",
                "Generation failed; see the surgical-guide error in the execution trace.",
            )
        elif (
            (guide_step and guide_step.get("status") == "done")
            or str(guide_status.get("state") or "") in {
                "ready", "stale", "persisted_not_loaded",
            }
            or (isinstance(guide_state, dict) and guide_state.get("status") == "ready")
        ):
            version = int(
                guide_status.get("version")
                or (guide_state.get("version") if isinstance(guide_state, dict) else 0)
                or 1
            )
            needle_count = len(
                guide_status.get("selected_needle_ids")
                or (guide_state.get("selected_needle_ids") if isinstance(guide_state, dict) else [])
                or []
            )
            if needle_count:
                guide_summary = L(
                    f"\u5df2\u751f\u6210\u7a7f\u523a\u5bfc\u677f v{version}\uff0c\u5305\u542b {needle_count} \u6761\u89c4\u5212\u9488\u9053\u3002",
                    f"Puncture guide v{version} generated for {needle_count} planned needle paths.",
                )
            else:
                guide_summary = L(
                    f"\u5df2\u751f\u6210\u7a7f\u523a\u5bfc\u677f v{version}\u3002",
                    f"Puncture guide v{version} generated.",
                )
        # Section 1: Workflow Summary
        lines.append(f"## {L('1. 流程总结', '1. Workflow Summary')}")
        lines.append("")
        # Find CTV/OAR/planning tool names from steps
        tools_run = []
        if steps:
            for s in steps:
                if s.get("tool") in ("ctv_segmentation", "oar_segmentation",
                                       "planning_pipeline", "trajectory_planning",
                                       "surgical_guide"):
                    tools_run.append(s["tool"])
        tools_summary = ", ".join(dict.fromkeys(tools_run)) if tools_run else "ctv_segmentation, planning_pipeline"
        lines.append(L(
            f"已完成放射性粒子植入规划全流程,执行工具:{tools_summary}。靶区覆盖率V100达{v100_frac*100:.1f}%,D90为{d90_gy:.2f} Gy,规划评分{ps_pct:.0f}/100。",
            f"Brachytherapy planning pipeline completed. Tools executed: {tools_summary}. CTV coverage V100 = {v100_frac*100:.1f}%, D90 = {d90_gy:.2f} Gy, plan score = {ps_pct:.0f}/100."
        ))
        lines.append("")

        # Section 2: CTV Segmentation
        ctv_vol_str = f"{ctv_vol_cm3:.2f} cm³" if ctv_vol_cm3 else "N/A"
        ctv_location_label, ctv_algorithm_label = _ctv_source_labels(
            self.memory.retrieve("ctv_source") or tumor_type,
            tumor_type,
        )
        lines.append(f"## {L('2. CTV 靶区分割', '2. CTV Segmentation')}")
        lines.append("")
        lines.append(f"- **{L('肿瘤体积', 'Tumor volume')}**: {ctv_vol_str} ({ctv_voxels:,} {L('体素', 'voxels')})")
        lines.append(f"- **{L('解剖位置', 'Anatomical location')}**: {ctv_location_label}")
        lines.append(f"- **{L('分割算法', 'Segmentation algorithm')}**: {ctv_algorithm_label}")
        if tumor_assessment_md:
            lines.append("")
            lines.append(tumor_assessment_md)
        lines.append("")

        # Section 3: OAR Segmentation
        lines.append(f"## {L('3. OAR 危及器官分割', '3. OAR Segmentation')}")
        lines.append("")
        oar_count = len(organ_names) if organ_names else 0
        lines.append(f"- **{L('OAR 总数', 'Total OAR count')}**: {oar_count}")
        # Show the 8 most clinically relevant OARs
        clinical_oars = ["duodenum", "small_bowel", "colon", "stomach", "liver",
                         "kidney", "spinal_cord", "pancreas", "spleen", "adrenal_gland"]
        organ_name_values = [str(v) for v in organ_names.values()] if isinstance(organ_names, dict) else []
        relevant = [name for name in clinical_oars if any(name in v for v in organ_name_values)][:8]
        if relevant:
            lines.append(f"- **{L('临床相关 OAR', 'Clinically relevant OARs detected')}**: {', '.join(relevant)}")
        lines.append("")

        # Section 4: Trajectory & Seed Plan
        lines.append(f"## {L('4. 轨迹与粒子计划', '4. Trajectory & Seed Plan')}")
        lines.append("")
        lines.append(f"- **{L('轨迹数', 'Trajectories generated')}**: {num_traj}")
        lines.append(f"- **{L('粒子数', 'Seeds placed')}**: {total_seeds}")
        if ctv_vol_cm3 and total_seeds:
            density = total_seeds / ctv_vol_cm3
            lines.append(f"- **{L('粒子密度', 'Seed density')}**: {density:.2f} {L('颗 / cm³', 'seeds/cm³')}")
        lines.append(f"- **{L('规划模式', 'Planning mode')}**: rule_based")

        # RL execution telemetry is distinct from the effective plan mode.
        # A rule-based fallback can be the final plan while the user still
        # needs to know whether RL reached its target, timed out, or exhausted
        # a bounded search budget.  Render only compact, persisted scalars so
        # this section remains useful after a restart and cannot leak arrays.
        rl_status = plan_config.get("rl_status")
        if not isinstance(rl_status, dict):
            rl_status = self.memory.retrieve("rl_status") or {}
        if isinstance(rl_status, dict) and rl_status:
            execution_labels = {
                "completed": L("已完成", "completed"),
                "interrupted": L("已中断", "interrupted"),
                "failed": L("失败", "failed"),
            }
            reason_labels = {
                "target_reached": L("达到目标覆盖率", "target reached"),
                "wall_clock_budget": L("达到墙钟时间预算", "wall-clock budget reached"),
                "dose_inference_deadline": L("达到剂量推理截止时间", "dose-inference deadline reached"),
                "episode_budget_exhausted": L("回合预算耗尽", "episode budget exhausted"),
                "no_valid_dense_trajectory": L("没有有效的密集针道候选", "no valid dense trajectory"),
                "no_available_action": L("没有可用动作", "no available action"),
                "internal_exception": L("内部异常", "internal exception"),
                "completed_without_target": L("完成但未达到目标", "completed without target"),
            }

            def _rl_number(key, default="—"):
                value = rl_status.get(key, default)
                return default if value is None else value

            def _rl_float(key, default=0.0):
                try:
                    value = float(rl_status.get(key, default))
                except (TypeError, ValueError):
                    return default
                return value if math.isfinite(value) else default

            execution = str(rl_status.get("execution") or "").strip()
            stop_reason = str(rl_status.get("stop_reason") or "").strip()
            execution_text = execution_labels.get(execution, execution or "—")
            reason_text = reason_labels.get(stop_reason, stop_reason or "—")
            lines.append("")
            lines.append(f"### {L('RL 执行诊断', 'RL execution diagnostics')}")
            lines.append(
                f"- **{L('执行状态', 'Execution')}**: {execution_text}"
                f" ({execution or '—'})"
            )
            lines.append(
                f"- **{L('停止原因', 'Stop reason')}**: {reason_text}"
                f" ({stop_reason or '—'})"
            )
            lines.append(
                f"- **{L('目标覆盖率 / 最佳覆盖率', 'Target / best coverage')}**: "
                f"{_rl_float('target_coverage'):.1%} / "
                f"{_rl_float('best_coverage'):.1%}"
            )
            best_reward = rl_status.get("best_reward")
            try:
                reward_value = float(best_reward)
            except (TypeError, ValueError):
                reward_value = None
            reward_text = (
                "—"
                if reward_value is None or not math.isfinite(reward_value)
                else f"{reward_value:.4f}"
            )
            lines.append(f"- **{L('最佳奖励', 'Best reward')}**: {reward_text}")
            lines.append(
                f"- **{L('回合数（总 / 高层 / 低层）', 'Episodes (total / high / low)')}**: "
                f"{_rl_number('episodes_completed')} / "
                f"{_rl_number('high_level_episodes')} / "
                f"{_rl_number('low_level_episodes')}"
            )
            lines.append(
                f"- **{L('动作数 / 密集针道 / 密集粒子候选', 'Actions / dense trajectories / dense seed candidates')}**: "
                f"{_rl_number('actions_taken')} / "
                f"{_rl_number('dense_trajectories_completed')} / "
                f"{_rl_number('dense_seed_candidates')}"
            )
            lines.append(
                f"- **{L('耗时 / 剂量缓存命中 / 未命中', 'Elapsed / dose-cache hits / misses')}**: "
                f"{_rl_float('elapsed_seconds'):.3f} s / "
                f"{_rl_number('dose_cache_hits')} / "
                f"{_rl_number('dose_cache_misses')}"
            )
        if guide_summary:
            lines.append(f"- **{L('手术导板', 'Surgical guide')}**: {guide_summary}")
        lines.append("")

        # Section 5: Dose Distribution
        lines.append(f"## {L('5. 剂量分布', '5. Dose Distribution')}")
        lines.append("")
        lines.append(f"- **{L('处方剂量', 'Prescription dose')}**: {rx_gy:.1f} Gy")
        lines.append(f"- **V100 / V150 / V200**: {v100:.1f}% / {v150:.1f}% / {v200:.1f}%")
        lines.append(f"- **D90 / Dmean / D2**: {d90:.2f} / {dmean:.2f} / {d2:.2f} Gy")
        lines.append(f"- **{L('适形指数 CI', 'Conformity Index (CI)')}**: {ci:.3f}")
        lines.append(f"- **{L('均匀指数 HI', 'Homogeneity Index (HI)')}**: {hi:.3f}")
        lines.append(f"- **{L('规划评分', 'Plan Score')}**: {ps:.0f}/100")
        if prescription_rationale_md:
            lines.append("")
            lines.append(prescription_rationale_md)
        lines.append("")

        # Section 6: OAR Dose Analysis (table)
        lines.append(f"## {L('6. OAR 剂量分析', '6. OAR Dose Analysis')}")
        lines.append("")
        oar_metrics = metrics.get('oar_metrics', {}) or {}
        if isinstance(oar_metrics, dict):
            oar_metrics = {_display_organ_name(organ): om for organ, om in oar_metrics.items()}
        if oar_metrics:
            lines.append(L(
                "以下 OAR 数值为观测结果；请在最终临床审核时依据当前部位适用指南或已确认的病例方案判读，不将软件默认值当作通过/超限结论。",
                "The OAR values below are observed metrics. Interpret them during final clinical review against applicable site-specific guidance or a confirmed case protocol; the software does not infer pass/fail from defaults."
            ))
            lines.append(f"| {L('危及器官', 'OAR')} | {L('最大剂量 (Gy)', 'Dmax (Gy)')} | D2cc (Gy) | D1cc (Gy) |")
            lines.append("|" + "|".join(["---"] * 4) + "|")
            for organ, om in sorted(oar_metrics.items(), key=lambda kv: _metric_dmax(kv[1]), reverse=True):
                dmax = _metric_dmax(om)
                d2cc = om.get('d2cc') or 0
                d1cc = om.get('d1cc') or 0
                lines.append(f"| {organ} | {dmax:.2f} | {d2cc:.2f} | {d1cc:.2f} |")
        else:
            lines.append(L('(剂量评估未返回 OAR 指标)', '(No OAR metrics returned by dose evaluation)'))
        lines.append("")

        # Section 7: Review Items
        lines.append(f"## {L('7. 需复核项目', '7. Review Items')}")
        lines.append("")
        review_items = []
        if oar_metrics:
            for organ, om in sorted(oar_metrics.items(), key=lambda kv: _metric_dmax(kv[1]), reverse=True)[:5]:
                dmax = _metric_dmax(om)
                d2cc = om.get('d2cc') or 0
                review_items.append(
                    f"- {organ}: Dmax={dmax:.2f} Gy, D2cc={d2cc:.2f} Gy."
                )
        review_items.append(
            f"- V100={v100:.1f}%, V150={v150:.1f}%, V200={v200:.1f}%, D90={d90:.2f} Gy."
        )
        lines.extend(review_items)
        lines.append("")

        # Section 8: Clinical Recommendations
        lines.append(f"## {L('8. 临床建议', '8. Clinical Recommendations')}")
        lines.append("")
        lines.append(f"- {L('请放射肿瘤科医师审核本计划并签署批准', 'Have a radiation oncologist review and sign off on this plan')}")
        lines.append(f"- {L('使用独立剂量算法进行二次校验(蒙特卡罗或 TG-43)', 'Perform secondary dose verification using an independent algorithm (Monte Carlo or TG-43)')}")
        if oar_metrics:
            lines.append(f"- {L('请在最终临床审核时，依据当前肿瘤部位的适用指南和已确认的病例方案限值复核 OAR 剂量，避免仅凭软件默认值下结论。', 'During final clinical review, verify OAR doses against applicable site-specific guidance and confirmed case-protocol limits; do not rely on software defaults alone.')}")
        lines.append(f"- {L('术后 1 个月复查 CT,评估粒子迁移和剂量验证', 'Schedule a 1-month follow-up CT to assess seed migration and dose verification')}")
        lines.append("")

        # Section 9: References
        lines.append(f"## {L('9. 参考文献', '9. References')}")
        lines.append("")
        lines.append(f"- {L('部位特异性阈值和 OAR 限值应以当前肿瘤部位适用的临床指南、机构协议或已确认的病例方案为准。', 'Site-specific thresholds and OAR limits should come from applicable clinical guidance, institutional protocols, or confirmed case-specific settings.')}")
        lines.append(f"- [AAPM TG-43U1](https://pubmed.ncbi.nlm.nih.gov/15070264/) — {L('近距离放疗源剂量学报告框架', 'Brachytherapy source dosimetry reporting framework')}")
        lines.append(f"- [ICRU Report 89](https://www.icru.org/report/icru-report-89-prescribing-recording-and-reporting-photon-beam-therapy-2nd-edition) — {L('处方、记录和报告原则', 'Prescribing, recording, and reporting principles')}")
        lines.append("")

        # The mode is part of the persisted plan configuration. Keep this
        # final normalization as a compatibility guard for older report code
        # paths that still emitted the historical hard-coded rule-based label.
        mode = str(plan_config.get("effective_mode") or plan_config.get("mode") or "rule_based")
        mode_labels = {
            "rule_based": L("规则优化", "rule-based"),
            "rl": L("强化学习", "reinforcement learning"),
            "rule_based_fallback": L("规则优化兜底（RL 未达到目标）", "rule-based fallback (RL target not reached)"),
        }
        report = "\n".join(lines).replace(": rule_based", f": {mode_labels.get(mode, mode)}")
        if plan_config.get("rl_fallback_used"):
            report += "\n\n" + L(
                "RL 在有限预算内未达到目标覆盖率，系统使用同一组安全候选路径执行了 AI 剂量模型的规则优化兜底。",
                "RL did not reach the target coverage within its bounded budget; the same safety-filtered candidates were replanned with the AI-dose rule-based optimizer.",
            )
        return report

    def _synthesize_with_llm(self, raw_results: str, steps: List, lang: str, user_message: str = "", query_type: str = "knowledge") -> str:
        """Synthesize tool results. Delegates to ToolResultPipeline."""
        formatted = []
        for s in steps:
            if s.get("type") == "tool" and s.get("status") in ("done", "error"):
                meta = s.get("metadata", {})
                data = s.get("data", {})
                # Extract source URLs from data or metadata
                source_urls = []
                if isinstance(data, dict):
                    sources = data.get("sources", [])
                    if isinstance(sources, list):
                        source_urls = [u for u in sources if u]
                if not source_urls and isinstance(meta, dict):
                    sources = meta.get("sources", [])
                    if isinstance(sources, list):
                        source_urls = [u for u in sources if u]
                formatted.append({
                    "tool": s.get("tool", ""),
                    "display": s.get("result", ""),
                    "source_url": source_urls[0] if source_urls else "",
                    "all_source_urls": source_urls,
                })
        # Tell the synthesizer when the user intentionally overrode state
        # reuse. This prevents a successful forced rerun from being followed
        # by a contradictory canned recommendation that it was unnecessary.
        if self._force_reexecution_requested(message=user_message):
            scope = self._segmentation_scope(user_message)
            user_message = (
                f"{user_message}\n\n"
                f"Execution contract: the user explicitly requested a forced segmentation rerun; "
                f"the requested scope is {scope}. Do not say that rerunning was unnecessary, "
                f"do not ask whether to rerun, and do not claim a tool succeeded if its tool step is error. "
                f"Report the actual result and any empty-mask failure plainly."
            )
        return ToolResultPipeline.synthesize(formatted, user_message, self.brain_router, lang, query_type)

    # ============================================================
    # Information Reliability Hierarchy
    # ============================================================
    # Query Type → Strategy → Source Attribution
    #
    # ┌──────────────┬──────────────────────────────────────┐
    # │  Query Type  │  Strategy                            │
    # ├──────────────┼──────────────────────────────────────┤
    # │  realtime    │  MUST search. Use results + source.  │
    # │  knowledge   │  LLM first, search to verify/suppl.  │
    # │  analysis    │  LLM reasoning. Tag "AI analysis".   │
    # │  system      │  Read memory/tool_results. No search.│
    # └──────────────┴──────────────────────────────────────┘

    # Patterns for each query type
    _REALTIME_PATTERNS = [
        # Impact factors, journal metrics
        (r'(影响因子|impact\s*factor|cite\s*score|JCR|分区)', 'journal_metric'),   # impact factor
        # Financial data
        (r'(股价|市值|行情|汇率|利率|stock|price)', 'financial'),   # stock/price
        # Weather
        (r'(天气|气温|下雨|weather|temperature)', 'weather'),   # weather
        # Time/date
        (r'(今天|今日|现在|当前|几点|时间|日期|current.*time|current.*date)', 'datetime'),   # today/now/time
        # News
        (r'(最新新闻|latest.*news|headline)', 'news'),   # latest news
        # Rankings, scores
        (r'(排名|排行|ranking|score|得分)', 'ranking'),   # ranking
        # Version numbers, releases
        (r'(最新版本|latest.*version|release)', 'version'),   # latest version
        # Statistics that change
        (r'(发病率|mortality|prevalence|incidence)', 'epidemiology'),   # mortality/prevalence
    ]

    _KNOWLEDGE_PATTERNS = [
        # Medical knowledge
        (r'(什么是|definition|explain|原理|mechanism)', 'definition'),   # what is/definition
        # Guidelines, protocols
        (r'(指南|protocol|guideline|standard|TG-\d+|AAPM|ABS|ESTRO)', 'guideline'),   # guideline
        # Dose, technique
        (r'(剂量|dose|technique|方法|method|procedure)', 'technique'),   # dose/technique
        # Anatomy
        (r'(解剖|anatomy|organ|器官|structure)', 'anatomy'),   # anatomy/organ
        # Drug, treatment
        (r'(药物|treatment|therapy|drug)', 'treatment'),   # treatment/drug
    ]

    _ANALYSIS_PATTERNS = [
        # Comparison
        (r'(比较|compare|versus|vs|which.*better)', 'comparison'),   # compare
        # Opinion, recommendation
        (r'(建议|recommend|opinion|should)', 'recommendation'),   # recommend
        # Pros/cons
        (r'(优缺点|pros.*cons|advantage|disadvantage)', 'evaluation'),   # pros/cons
    ]

    _SYSTEM_PATTERNS = [
        # Internal state
        (r'(刚才|之前|已.*分割|已.*分析|当前.*状态|what.*done)', 'state'),   # previous/current state
        # List/show results
        (r'(列.*表|显示.*结果|show.*result|list|display)', 'display'),   # show/list
        # File/system operations
        (r'(保存|导出|加载|save|export|load|upload)', 'file_op'),   # save/export/load
        # Tool operations (analyze image, segment, etc.)
        (r'(分析.*图像|分割.*图像|analyze.*image|segment.*image|计算.*剂量)', 'tool_op'),   # analyze/segment image
    ]

    def _prepare_fact_check_brief(self, result_text: str, sources: list = None) -> list:
        """Use LLM to intelligently select claims for FactChecker verification.

        Instead of regex patterns, let LLM understand context and prioritize
        claims that FactChecker should verify. Falls back to regex if LLM fails.

        Returns a list of claims (max 7) for FactChecker to verify.
        """
        # Try LLM-based extraction first
        _llm_cb = self._get_llm_callback()
        if _llm_cb:
            try:
                prompt = f"""You are preparing claims for a medical fact-checker agent.

From the following text, identify the MOST IMPORTANT claims that need verification.
Prioritize in this order:
1. Suspicious assertions (fabricated studies, findings, placeholder references)
2. Clinical guidelines (NCCN, AAPM, ASTRO, ICRU recommendations)
3. Literature citations (PMID, study references, trial names)
4. Numerical claims (doses, percentages, metrics like V100, D90)

Return a JSON array of up to 7 claims as strings, in priority order (most important first).
Only include claims that are factually verifiable.

Text to analyze:
{result_text}

Output (JSON array of strings):"""

                response = _llm_cb(prompt)
                # Parse JSON response
                import json
                claims = json.loads(response.strip())
                if isinstance(claims, list) and len(claims) > 0:
                    logger.debug(f"LLM extracted {len(claims)} claims for FactChecker")
                    return claims[:7]
            except Exception as e:
                logger.debug(f"LLM claim extraction failed, using regex fallback: {e}")

        # Fallback: regex-based extraction (original implementation)
        return self._prepare_fact_check_brief_regex(result_text, sources)

    def _prepare_fact_check_brief_regex(self, result_text: str, sources: list = None) -> list:
        """Fallback: regex-based claim extraction (original implementation)."""
        claims = []
        text_lower = result_text.lower()

        # 1. Suspicious assertions (HIGHEST priority - FactChecker's specialty)
        suspicious_patterns = [
            (r'according to (?:a|our)\s+(?:study|research|data)', 'Potential fabricated study'),
            (r'(?:we|I)\s+(?:found|discovered|demonstrated)\s+that', 'Potential fabricated finding'),
            (r'(?:my|our)\s+(?:research|data)\s+shows', 'Potential fabricated research'),
            (r'recently published in\s+\[', 'Placeholder journal'),
            (r'Dr\.\s+[A-Z][a-z]+\s+(?:from|at)\s+\[', 'Placeholder institution'),
        ]
        for pattern, desc in suspicious_patterns:
            if re.search(pattern, result_text, re.IGNORECASE):
                # Extract the suspicious sentence
                for sentence in re.split(r'[.。]', result_text):
                    if re.search(pattern, sentence, re.IGNORECASE):
                        claim = f"[{desc}] {sentence.strip()}"
                        if claim not in claims and len(claims) < 7:
                            claims.append(claim)
                        break

        # 2. Clinical guideline references (high priority)
        guideline_orgs = ['NCCN', 'AAPM', 'ASTRO', 'ICRU', 'WHO', 'ESTRO']
        for org in guideline_orgs:
            if org.lower() in text_lower:
                # Extract sentence containing the org
                for sentence in re.split(r'[.。]', result_text):
                    if org.lower() in sentence.lower() and len(sentence) > 15:
                        claim = sentence.strip()
                        if claim not in claims and len(claims) < 7:
                            claims.append(claim)
                        break  # Only first occurrence per org

        # 3. Literature citations (PMID, study references)
        pmid_pattern = r'PMID:\s*(\d+)'
        pmids = re.findall(pmid_pattern, result_text, re.IGNORECASE)
        for pmid in pmids[:2]:
            claim = f"PMID: {pmid}"
            if claim not in claims and len(claims) < 7:
                claims.append(claim)

        # Study reference patterns
        study_patterns = [
            r'(?:study|trial|research)\s+(?:ID|number|#)\s*[\w-]+',
        ]
        for pattern in study_patterns:
            matches = re.findall(pattern, result_text, re.IGNORECASE)
            for match in matches[:1]:
                if match not in claims and len(claims) < 7:
                    claims.append(match.strip())

        # 4. Numerical claims (important for fact-checking)
        # Only add if we have room and they're not already covered by guideline sentences
        if len(claims) < 5:
            numerical_patterns = [
                r'(V\d+|D\d+)\s*[<>=]+\s*\d+\.?\d*\s*%?',  # V100 > 95%, D90 = 145
                r'prescription\s+(?:dose\s+)?(?:is|of)\s+\d+\s*Gy',  # prescription is 120 Gy
            ]
            for pattern in numerical_patterns:
                matches = re.findall(pattern, result_text, re.IGNORECASE)
                for match in matches[:2]:
                    # Get the full sentence containing this match
                    for sentence in re.split(r'[.。]', result_text):
                        if match in sentence and len(sentence) > 10:
                            claim = sentence.strip()
                            if claim not in claims and len(claims) < 7:
                                claims.append(claim)
                            break

        # 5. Fallback: key factual statements with clinical data
        if len(claims) < 3:
            sentences = re.split(r'[.。!！?？\n]', result_text)
            for sentence in sentences:
                sentence = sentence.strip()
                if len(sentence) < 15 or len(sentence) > 200:
                    continue
                # Check if sentence contains specific clinical data
                has_dose_metric = bool(re.search(r'(V\d+|D\d+|dose|volume)\s*\d', sentence, re.IGNORECASE))
                has_percentage = bool(re.search(r'\d+\.?\d*\s*%', sentence))
                if (has_dose_metric or has_percentage) and sentence not in claims and len(claims) < 7:
                    claims.append(sentence)

        return claims[:7]

    def _check_search_reliability(self, tool_name: str, result_text: str,
                                     sources: list = None) -> str:
        """Run FactChecker on search results and append reliability note.

        Called after web_search/web_fetch/web_access tool execution.
        The note is appended to the tool result so the LLM sees it
        and can decide whether to re-search with better keywords.

        Returns the result_text with reliability note appended.
        """
        if not self.multi_agent_wrapper or not self.multi_agent_wrapper.enabled:
            return result_text

        # Skip the extra LLM round when the search returned almost nothing.
        # Running FactChecker on an empty/3-line result adds a full LLM call
        # per tool step without evidence to verify, multiplying the cost of
        # many small searches. The LLM still sees the raw (empty) result and
        # can decide to re-search with better keywords.
        _stripped = (result_text or "").strip()
        if len(_stripped) < 300:
            return result_text

        # Intelligently extract claims for FactChecker
        claims = self._prepare_fact_check_brief(result_text, sources)
        if not claims:
            return result_text

        # Extract sources if not provided
        if sources is None:
            sources = []
            url_pattern = r'https?://[^\s\])<>"]+'
            found_urls = re.findall(url_pattern, result_text)
            sources.extend(found_urls[:5])

        try:
            import asyncio
            loop = asyncio.new_event_loop()
            try:
                # skip_distill=True because we're in a sync context
                # (inside run_until_complete) and nested event loops
                # would cause issues. FactChecker is fast anyway.
                note = loop.run_until_complete(
                    self.multi_agent_wrapper.review_facts_append(
                        claims, sources, "en", skip_distill=True
                    )
                )
                if note:
                    return result_text + f"\n\n{note}"
            finally:
                loop.close()
        except Exception as e:
            logger.debug(f"Search reliability check skipped: {e}")

        return result_text

    def _classify_query_type(self, message: str) -> str:
        """Classify query into: realtime, knowledge, analysis, system.

        Returns the query type string for strategy selection.
        Priority: system > realtime > knowledge > analysis
        """
        msg = message.strip().lower()

        # Check system patterns first (highest priority for internal queries)
        for pattern, _ in self._SYSTEM_PATTERNS:
            if re.search(pattern, msg, re.IGNORECASE):
                return 'system'

        # Check realtime patterns (must search, can't use training data)
        for pattern, _ in self._REALTIME_PATTERNS:
            if re.search(pattern, msg, re.IGNORECASE):
                return 'realtime'

        # Check knowledge patterns (LLM + search verification)
        # BEFORE analysis — because "recommendation" in guideline context is knowledge, not opinion
        for pattern, _ in self._KNOWLEDGE_PATTERNS:
            if re.search(pattern, msg, re.IGNORECASE):
                return 'knowledge'

        # Check analysis patterns (LLM reasoning)
        for pattern, _ in self._ANALYSIS_PATTERNS:
            if re.search(pattern, msg, re.IGNORECASE):
                return 'analysis'

        # Default: let LLM decide
        return 'knowledge'

    @staticmethod
    def _get_source_attribution(query_type: str, has_search: bool, lang: str = "en", search_year: str = "") -> str:
        """Generate source attribution text based on query type and data source."""
        if lang == "zh":
            if query_type == 'realtime':
                if has_search:
                    return f"📊 数据来源: 网络搜索 ({search_year})" if search_year else "📊 数据来源: 网络搜索"
                else:
                    return "⚠️ 注意: 未找到最新数据，以下信息可能已过时"
            elif query_type == 'knowledge':
                return "📚 数据来源: AI知识库 + 网络验证" if has_search else "📚 数据来源: AI知识库（未经实时验证）"
            elif query_type == 'analysis':
                return "💡 数据来源: AI分析（仅供参考）"
            elif query_type == 'system':
                return "📋 数据来源: 系统内部数据"
        else:
            if query_type == 'realtime':
                if has_search:
                    return f"📊 Source: Web search ({search_year})" if search_year else "📊 Source: Web search"
                else:
                    return "⚠️ Note: Latest data not found, information may be outdated"
            elif query_type == 'knowledge':
                return "📚 Source: AI knowledge + web verification" if has_search else "📚 Source: AI knowledge (not verified by search)"
            elif query_type == 'analysis':
                return "💡 Source: AI analysis (for reference only)"
            elif query_type == 'system':
                return "📋 Source: Internal system data"
        return ""

    # Tumor type maps to canonical CTV tools. The registry retains legacy
    # aliases for restored Sessions, but automatic planning must only emit the
    # current nnU-Net or BiomedParse v2 automatic route names.
    _TUMOR_TYPE_MAP = {
        # English names — pancreatic uses nnUNet (more accurate)
        "pancreatic_tumor": "nnunet_pancreatic",
        "pancreatic": "nnunet_pancreatic",
        "pancreas": "nnunet_pancreatic",
        "liver_tumor": "biomedparse_liver_tumor",
        "liver": "biomedparse_liver_tumor",
        "kidney_tumor": "biomedparse_kidney_lesion",
        "kidney": "biomedparse_kidney_lesion",
        "colon_tumor": "biomedparse_colon_primary",
        "colon": "biomedparse_colon_primary",
        "lung_tumor": "biomedparse_lung_lesion",
        "lung": "biomedparse_lung_lesion",
        "head_neck": "biomedparse_head_neck_cancer",
        "head and neck": "biomedparse_head_neck_cancer",
        "pdac": "nnunet_pancreatic",
        "hepatocellular": "biomedparse_liver_tumor",
        "hcc": "biomedparse_liver_tumor",
        "renal": "biomedparse_kidney_lesion",
        "colorectal": "biomedparse_colon_primary",
        "nsclc": "biomedparse_lung_lesion",
        "prostate": "biomedparse_prostate_lesion",
        "prostate_tumor": "biomedparse_prostate_lesion",
        "胰腺癌": "nnunet_pancreatic",
        "胰腺肿瘤": "nnunet_pancreatic",
        "胰腺": "nnunet_pancreatic",
        "肝癌": "biomedparse_liver_tumor",
        "肝肿瘤": "biomedparse_liver_tumor",
        "肝脏": "biomedparse_liver_tumor",
        "肾癌": "biomedparse_kidney_lesion",
        "肾肿瘤": "biomedparse_kidney_lesion",
        "肾脏": "biomedparse_kidney_lesion",
        "结肠癌": "biomedparse_colon_primary",
        "结直肠癌": "biomedparse_colon_primary",
        "结肠": "biomedparse_colon_primary",
        "肺癌": "biomedparse_lung_lesion",
        "肺肿瘤": "biomedparse_lung_lesion",
        "肺部": "biomedparse_lung_lesion",
        "头颈": "biomedparse_head_neck_cancer",
        "头颈肿瘤": "biomedparse_head_neck_cancer",
        "前列腺": "biomedparse_prostate_lesion",
        "前列腺癌": "biomedparse_prostate_lesion",
        "胰腺癌患者": "nnunet_pancreatic",   # pancreatic cancer patient
        "肝癌患者": "biomedparse_liver_tumor",  # liver cancer patient
        "肾癌患者": "biomedparse_kidney_lesion",    # kidney cancer patient
        "肺癌患者": "biomedparse_lung_lesion",      # lung cancer patient
        "结肠癌患者": "biomedparse_colon_primary",   # colon cancer patient
    }

    _SUPPORTED_AUTOMATIC_CTV_TYPES = frozenset({
        "nnunet_pancreatic",
        "biomedparse_liver_tumor",
        "biomedparse_kidney_lesion",
        "biomedparse_lung_lesion",
        "biomedparse_colon_primary",
        "biomedparse_head_neck_cancer",
        "biomedparse_prostate_lesion",
    })

    def _map_tumor_type(self, tumor_type: Optional[str]) -> Optional[str]:
        """Map a user, catalog, or legacy spelling to one CTV route."""
        if tumor_type is None:
            return None
        raw = str(tumor_type).strip()
        if not raw:
            return None
        # The CTV package owns public aliases so direct planning, LLM calls,
        # restored Sessions, and the model catalog cannot drift apart.
        try:
            from tool_factory.CTV_seg import normalize_tumor_type
            canonical = normalize_tumor_type(raw)
        except Exception:
            canonical = raw
        if canonical in self._SUPPORTED_AUTOMATIC_CTV_TYPES:
            return canonical
        # Look up in mapping
        mapped = self._TUMOR_TYPE_MAP.get(raw.lower())
        if mapped:
            try:
                from tool_factory.CTV_seg import normalize_tumor_type
                return normalize_tumor_type(mapped)
            except Exception:
                return mapped
        # Partial match for Chinese
        for key, val in self._TUMOR_TYPE_MAP.items():
            if key in raw or raw in key:
                try:
                    from tool_factory.CTV_seg import normalize_tumor_type
                    return normalize_tumor_type(val)
                except Exception:
                    return val
        # Keep explicit unknown sites unsupported. The unified CTV tool will
        # fail closed with the model catalog instead of silently running a
        # pancreatic model on another disease site.
        logger.warning(f"Unknown tumor_type '{raw}', leaving it unsupported")
        return canonical

    @staticmethod
    def _message_text(value) -> str:
        """Extract readable text from persisted plain or multimodal messages."""
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ("content", "text", "message"):
                if key in value:
                    text = ResponseToolMixin._message_text(value.get(key))
                    if text:
                        return text
            return ""
        if isinstance(value, (list, tuple)):
            return " ".join(
                text for text in (ResponseToolMixin._message_text(item) for item in value)
                if text
            )
        return str(value or "")

    def _detect_tumor_type_from_message(self, message: str) -> Optional[str]:
        """Detect a site from the current or recent user messages.

        Follow-up commands often omit the site (for example, ``再分割 CTV``).
        Only user-authored history is considered so assistant prose and tool
        output cannot accidentally change the active tumor model.
        """
        messages = [self._message_text(message)]
        for item in reversed(getattr(self.memory, "conversation", []) or []):
            if not isinstance(item, dict) or str(item.get("role", "")).lower() != "user":
                continue
            text = self._message_text(item.get("content", ""))
            if text.lstrip().startswith(("[Tool result:", "[Called ")):
                continue
            if text and text not in messages:
                messages.append(text)
        # Current input wins; the rest are newest-to-oldest user context.
        # These aliases are deliberately kept separate from the legacy
        # transcript map above: they are real Unicode user input, not the
        # mojibake spellings found in older persisted prompts.
        unicode_aliases = (
            ("\u80f0\u817a\u764c", "nnunet_pancreatic"),
            ("\u80f0\u817a\u80bf\u7624", "nnunet_pancreatic"),
            ("\u80f0\u817a", "nnunet_pancreatic"),
            ("\u809d\u764c", "biomedparse_liver_tumor"),
            ("\u809d\u810f", "biomedparse_liver_tumor"),
            ("\u80be\u764c", "biomedparse_kidney_lesion"),
            ("\u80be", "biomedparse_kidney_lesion"),
            ("\u80ba\u764c", "biomedparse_lung_lesion"),
            ("\u80ba", "biomedparse_lung_lesion"),
            ("\u7ed3\u80a0\u764c", "biomedparse_colon_primary"),
            ("\u7ed3\u80a0", "biomedparse_colon_primary"),
            ("\u5934\u9888", "biomedparse_head_neck_cancer"),
            ("\u524d\u5217\u817a", "biomedparse_prostate_lesion"),
            ("pancreatic cancer", "nnunet_pancreatic"),
            ("pancreatic tumor", "nnunet_pancreatic"),
            ("liver cancer", "biomedparse_liver_tumor"),
            ("liver tumor", "biomedparse_liver_tumor"),
            ("kidney cancer", "biomedparse_kidney_lesion"),
            ("kidney tumor", "biomedparse_kidney_lesion"),
            ("lung cancer", "biomedparse_lung_lesion"),
            ("lung tumor", "biomedparse_lung_lesion"),
            ("colon cancer", "biomedparse_colon_primary"),
            ("colon tumor", "biomedparse_colon_primary"),
            ("head and neck", "biomedparse_head_neck_cancer"),
            ("prostate cancer", "biomedparse_prostate_lesion"),
            ("prostate tumor", "biomedparse_prostate_lesion"),
        )
        for text in messages:
            msg = text.lower()
            for keyword, tool_name in unicode_aliases:
                if keyword in msg:
                    return tool_name
            for keyword, tool_name in self._TUMOR_TYPE_MAP.items():
                if keyword in msg:
                    return tool_name
        return None

    def _detect_realtime_query(self, message: str) -> Optional[str]:
        """Detect if the message requires a real-time web search.
        Returns a search query string if detected, None otherwise.
        The query is optimized for Bing/Baidu (not PubMed)."""
        msg = message.strip().lower()
        # Patterns that require real-time search
        # Weather queries are handled by specialized engine — just detect the intent
        realtime_patterns = [
            (r'(今天|today|明天|tomorrow|昨天|yesterday|本周|this week|当前|now).*(天气|天气|气温|temperature|下雨|rain|晴|sunny)', True),   # weather queries
            (r'(天气|weather|气温|temperature).*(如何|怎么样|how|多少|what|预报|forecast)', True),   # weather queries
            (r'(weather|temperature|forecast)', True),
            (r'(现在|now|今天|today|几点|time|日期|date)', False),   # time/date
            (r'(what time|current time|what date)', False),
            (r'(最新|latest|最近|recent|今日|today).*(新闻|news|消息|headline|头条)', False),   # news
            (r'(news|headline|latest news)', False),
            (r'(nba|NBA|basketball).*(finals|playoffs|game|result)', False),   # NBA
            (r'(soccer|football|world cup|champions league|premier league).*(game|match|result|score)', False),   # soccer
            (r'(stock|股价|市值|market cap)', False),   # stock
            (r'(exchange rate|汇率|dollar|euro|rmb)', False),   # exchange rate
            (r'(pandemic|疫情|covid|case count)', False),   # pandemic
        ]
        for pattern, is_weather in realtime_patterns:
            if re.search(pattern, msg, re.IGNORECASE):
                if is_weather:
                    # Weather: pass original message, specialized engine extracts city
                    return message.strip()
                # Non-weather: generate a search query from the message
                return message.strip()
        return None

    def _detect_external_project_query(self, message: str) -> Optional[str]:
        """Detect external-project research and return a web-search query.

        A named external project must be researched from public sources.  This
        detector also handles short follow-ups such as ``其代码在哪里`` by
        looking at recent user messages, while an explicit BrachyBot path/name
        keeps the request in the local-code workflow.
        """
        msg = str(message or "").strip()
        if not msg:
            return None
        low = msg.lower()
        local_markers = (
            "brachybot", "brachyplan", "本项目", "当前项目", "本地代码",
            "当前仓库", "/home/lht/snap/brachyplan/brachybot",
        )
        if any(marker in low for marker in local_markers):
            return None

        followup = bool(re.search(
            r"(其|它|该项目|这个项目|the project|its)"
            r".{0,10}(代码|源码|仓库|repository|repo|source code|github|gitlab|code)",
            low,
            re.IGNORECASE,
        ))
        context_parts = [msg]
        if followup:
            for item in reversed(getattr(self.memory, "conversation", []) or []):
                if item.get("role") == "user":
                    content = str(item.get("content", "")).strip()
                    if content:
                        context_parts.append(content)
                    if len(context_parts) >= 7:
                        break
        scope_text = "\n".join(context_parts)
        scope_low = scope_text.lower()
        external_markers = (
            "github", "gitlab", "repository", "repo", "source code",
            "代码", "源码", "项目", "project", "论文", "paper",
        )
        lookup_markers = (
            "查", "查询", "介绍", "研究", "find", "search", "look",
            "code", "源码", "代码", "repository", "仓库",
        )
        # ``\b`` does not split a Latin project name from adjacent CJK text
        # because both sides are Unicode word characters. Use ASCII-aware
        # guards so a capitalized project name embedded in a CJK sentence is
        # still recognized as a named project.
        named_projects = re.findall(
            r"(?<![A-Za-z0-9_])[A-Z][A-Za-z0-9_-]{2,}(?![A-Za-z0-9_])",
            scope_text,
        )
        named_projects = [
            name for name in named_projects
            if name.lower() not in {"BrachyBot".lower(), "BrachyPlan".lower()}
        ]
        if not named_projects and not any(
            marker in scope_low for marker in ("github", "gitlab", "repository", "项目", "project")
        ):
            return None
        if not any(marker in scope_low for marker in external_markers + lookup_markers):
            return None

        # Keep the user's wording and add a source-oriented suffix so the
        # search tool is used instead of a local filesystem tool.
        suffix = " official repository source code" if any(
            marker in scope_low for marker in ("代码", "源码", "source code", "repository", "github", "gitlab", "code")
        ) else " authoritative project information"
        # Use the detected project name(s) as the search body instead of the
        # raw user utterance. Feeding the whole natural-language request to the
        # search engine matches unrelated terms and returns an unhelpful "not
        # found" answer. Restricting the query to the project name keeps the
        # search focused and English-indexable; the original message is still
        # in the conversation so the downstream LLM can phrase the final
        # answer in the user's language.
        if followup and named_projects:
            # The current turn may only say "its code". Carry forward the
            # most recent named external project instead of searching that
            # pronoun literally.
            query_text = f"{named_projects[-1]} {msg}"
        else:
            query_text = " ".join(named_projects) if named_projects else msg
        return f"{query_text}{suffix}"

    def _normalize_tool_params(self, tool_calls: List[Dict]) -> List[Dict]:
        """Normalize tool call parameters (alias mapping, validation).

        Returns filtered list of valid tool calls. Invalid ones are dropped.
        """
        # INTERNAL FIELDS that the LLM must NEVER inject into a tool call.
        # These are runtime-side-channel values that the agent passes
        # via Python kwargs (e.g. step_callback), not part of the tool
        # input_schema. If the LLM hallucinates one of these field names
        # (M2.7-highspeed has been observed doing this in 2026-06-16
        # when the LLM saw "step_callback" leak through system prompt
        # wording), the literal repr "<function ...>" or "<class ...>"
        # would otherwise be passed to the tool, which would then log
        # it AND potentially inject it back into the next turn's
        # messages, causing an infinite hallucination loop.
        _INTERNAL_FIELDS = {
            "step_callback", "progress_callback", "memory", "agent",
            "_internal", "callback", "context", "ctx", "self_ref",
        }
        # Values that look like Python reprs — only seen when the LLM
        # is mimicking a schema field that doesn't exist. Reject any
        # tool call whose params include such a value.
        _PYTHON_REPR_RE = re.compile(
            r"^<function\s|^<class\s|^<bound method\s|^<module\s|^<object\s"
        )
        # Enforce the deterministic guide route even if a provider emits an
        # invalid code_executor call despite the local policy/schema filter.
        # This is a boundary guard, not a UI workaround: the user's explicit
        # clinical action always maps to the registered guide tool.
        active_policy = getattr(self, "_active_turn_policy", None)
        get_action_plan = getattr(self, "_current_action_plan", None)
        action_plan = get_action_plan() if callable(get_action_plan) else None
        if getattr(active_policy, "intent", None) == "session_visual_location_query":
            # This turn has a typed read-only visual contract. Even if a
            # provider unexpectedly emits extra function calls, do not let a
            # location question reach a mutating clinical tool. The canonical
            # direct route already supplies the complete screenshot plan;
            # this is a last-line authorization boundary, not an answer list.
            visual_calls = [
                call for call in (tool_calls or [])
                if str(call.get("tool") or "") == "ui_screenshot"
            ]
            if not visual_calls:
                logger.error(
                    "Rejected non-visual provider calls for a session visual "
                    "location turn"
                )
                return []
            tool_calls = visual_calls
        if getattr(active_policy, "intent", None) == "ui_control_location_query":
            # Unknown-control location questions are read-only.  The model may
            # inspect the real capability catalog and request a screenshot,
            # but it must not click, toggle, or mutate a UI control while
            # answering where that control is.
            inspector_calls = [
                call for call in (tool_calls or [])
                if str(call.get("tool") or "") in {"ui_inspector", "ui_screenshot"}
            ]
            if not inspector_calls:
                logger.error(
                    "Rejected non-read-only provider calls for a UI control "
                    "location turn"
                )
                return []
            tool_calls = inspector_calls
        if (
            getattr(active_policy, "intent", None) == "surgical_guide_generation"
            and not (
                action_plan is not None
                and action_plan.requires_tool("planning_pipeline")
            )
        ):
            guide_call = next(
                (call for call in (tool_calls or []) if call.get("tool") == "surgical_guide"),
                None,
            )
            return [{
                "id": (guide_call or {}).get("id", "tool_direct_surgical_guide"),
                "tool": "surgical_guide",
                "params": {
                    **dict((guide_call or {}).get("params") or {}),
                    "action": "generate",
                },
            }]

        valid = []
        for tc in tool_calls:
            tn = tc.get("tool", "")
            p = tc.get("params", {})
            if not isinstance(p, dict):
                # Provider arguments are JSON objects by contract. Treat a
                # malformed value as an empty object so the capability
                # boundary can return a localized business error instead of
                # crashing while inspecting ``.get`` below.
                p = {}
            # Providers occasionally use a descriptive function name for an
            # already-registered capability. Normalize the tool API at this
            # boundary instead of branching on the user's wording. This keeps
            # natural-language understanding with the LLM while making the
            # server contract tolerant of equivalent provider decisions.
            _dose_aliases = {
                "dose_calc",
                "recalculate_dose",
                "recompute_dose",
                "dose_calculation",
                "current_plan_dose",
                "update_dose",
            }
            if tn in _dose_aliases:
                tn = "dose_recompute"
                tc = {**tc, "tool": tn, "params": dict(p or {})}
                p = tc["params"]
            elif tn == "dose_engine":
                # The raw engine requires runtime image/seed payloads and is
                # not a conversational API. If the provider selected it for
                # a stateful request, translate the incomplete call to the
                # high-level capability. The tool itself will then give an
                # honest "no active Planning" result when the Session lacks
                # usable geometry; we must not silently drop the turn.
                raw_image = p.get("dose_image")
                raw_seeds = p.get("seeds")
                raw_payload_ready = (
                    raw_image is not None
                    and not isinstance(raw_image, str)
                    and isinstance(raw_seeds, (list, tuple))
                    and bool(raw_seeds)
                )
                if not raw_payload_ready:
                    tn = "dose_recompute"
                    tc = {**tc, "tool": tn, "params": dict(p)}
                    p = tc["params"]
            # GENERAL SANITIZATION (applies to ALL tools):
            # 1) Drop any internal-field name from the params dict
            #    silently — the LLM is hallucinating; the tool's
            #    runtime side-channel will set it correctly.
            # 2) Reject the entire tool call if any value looks like
            #    a Python repr (function/class object literal). The
            #    user saw `step_callback=<function ...>` get logged
            #    in 2026-06-16, which is exactly this shape.
            stripped = []
            for k in list(p.keys()):
                v = p[k]
                if k in _INTERNAL_FIELDS:
                    logger.warning(
                        f"Stripped internal field {k!r} from LLM "
                        f"tool call params for {tn!r}"
                    )
                    p.pop(k, None)
                    stripped.append(k)
                elif isinstance(v, str) and _PYTHON_REPR_RE.match(v):
                    logger.warning(
                        f"Refusing tool call {tn!r}: param {k!r} "
                        f"contains a Python repr ({v[:60]!r}) — the "
                        f"LLM is hallucinating a function-valued field"
                    )
                    p = None
                    break
            if p is None:
                continue  # Skip this tool call entirely
            if tn in {"ui_screenshot", "ui_content"}:
                question = str(p.get("question") or "").strip()
                if not question:
                    memory = getattr(self, "memory", None)
                    for item in reversed(getattr(memory, "conversation", []) or []):
                        if isinstance(item, dict) and str(item.get("role", "")).lower() == "user":
                            question = self._message_text(item.get("content", ""))
                            if question:
                                break
                if (
                    getattr(active_policy, "direct_execution", False)
                    and resolve_report_request_action(question) == "regenerate"
                ):
                    # The model selected a read-only presentation tool for a
                    # canonical fast-path report request. Semantic turns keep
                    # the model's structured tool decision instead of being
                    # reinterpreted from raw text after function calling.
                    tn = "ui_controller"
                    p = {
                        "actions": [{"target": "report.autofill", "command": "run"}],
                    }
                    tc = {**tc, "tool": tn, "params": p}
            if tn == "filesystem_browser":
                if "dirPath" in p and "path" not in p:
                    p["path"] = p.pop("dirPath")
                if "directory" in p and "path" not in p:
                    p["path"] = p.pop("directory")
                if "action" not in p:
                    p["action"] = "list"
                if p.get("action") not in ("list", "info"):
                    p["action"] = "list"
                if not p.get("path", "").strip():
                    continue
            elif tn == "code_executor":
                for alias in ("script", "python", "command"):
                    if alias in p and "code" not in p:
                        p["code"] = p.pop(alias)
                if not p.get("code", "").strip():
                    continue
            elif tn == "ctv_segmentation":
                # LLM calls can contain a friendly site name, an old saved
                # VoCo alias, or a BiomedParse catalog id. Normalize before
                # the tool schema is checked so all entry points use the same
                # canonical model route.
                p = self._normalize_ctv_tool_params(p)
                tc["params"] = p
            elif tn == "ui_controller":
                # Normalize: LLM may pass target/command at top level instead of inside actions
                if "target" in p and "actions" not in p:
                    p["actions"] = [{"target": p.pop("target"), "command": p.pop("command", "set"), "value": p.pop("value", None)}]
                if not p.get("actions"):
                    logger.warning(f"Dropping ui_controller call with no actions")
                    continue
            elif tn == "web_search":
                # Validate required parameters for web_search
                if not p.get("query", "").strip():
                    logger.warning(f"Dropping web_search call with empty query")
                    continue
            elif tn == "web_access":
                # Validate required parameters for web_access
                if not p.get("action"):
                    logger.warning(f"Dropping web_access call with no action")
                    continue
                if p.get("action") == "search" and not p.get("query", "").strip():
                    logger.warning(f"Dropping web_access search with empty query")
                    continue
                if p.get("action") == "fetch" and not p.get("url", "").strip():
                    logger.warning(f"Dropping web_access fetch with no URL")
                    continue
            elif tn == "web_fetch":
                # Validate required parameters for web_fetch
                if not p.get("url", "").strip():
                    logger.warning(f"Dropping web_fetch call with no URL")
                    continue
            elif tn == "ui_screenshot":
                # A malformed screenshot call can otherwise enter the retry
                # loop and waste several model calls before failing with a
                # low-level missing-parameter error. A structured multi-view
                # plan may legitimately omit the legacy single `target`.
                target = str(p.get("target") or "").strip()
                views = p.get("views")
                has_views = isinstance(views, list) and any(
                    str(view or "").strip() for view in views
                )
                question = str(p.get("question") or "").strip()
                if (not target and not has_views) or not question:
                    logger.warning(
                        "Dropping ui_screenshot call without a target/views and question"
                    )
                    continue
                # A report-only request reads artifacts already persisted in
                # the Session. It is not a live DOM capture: the report panel
                # may be unmounted or still restoring when this command runs.
                requested_targets = []
                if target:
                    requested_targets.append(target.lower())
                if isinstance(views, list):
                    for view in views:
                        if isinstance(view, dict):
                            view = view.get("target") or view.get("viewer")
                        value = str(view or "").strip().lower()
                        if value:
                            requested_targets.append(value)
                if requested_targets and all(value == "report" for value in requested_targets):
                    from tool_factory.ui_content import normalize_session_content_request

                    content_contract = normalize_session_content_request(
                        question=question,
                        presentation="attachments",
                    )
                    # A live-report capture proposed by the model can still be
                    # a deictic reference to images shown in the preceding
                    # reply. Preserve that source relation instead of silently
                    # widening it to every report figure.
                    content_target = (
                        "reply_attachments"
                        if resolve_session_content_target(question) == "reply_attachments"
                        else "report_figures"
                    )
                    tc = dict(tc)
                    tc["tool"] = "ui_content"
                    tc["params"] = {
                        "target": content_target,
                        "presentation": content_contract["presentation"],
                        "selection": content_contract["selection"],
                        "analysis": content_contract["analysis"],
                        "mode": str(p.get("mode") or "chat"),
                        "question": question,
                        "planning_id": str(p.get("planning_id") or ""),
                    }
            elif tn == "ui_content":
                from tool_factory.ui_content import (
                    SESSION_CONTENT_TARGETS,
                    normalize_session_content_request,
                )
                target = str(p.get("target") or "").strip().lower()
                question = str(p.get("question") or "").strip()
                if target not in SESSION_CONTENT_TARGETS or not question:
                    logger.warning("Dropping ui_content call with unsupported target or no question")
                    continue
                # The primary model chooses ordinary content families. Only a
                # source-level conversational reference is canonicalized here:
                # ``last image`` refers to the ordered attachments of the
                # preceding reply, not to a similarly named global collection.
                if resolve_session_content_target(question) == "reply_attachments":
                    target = "reply_attachments"
                p["target"] = target
                p.update(normalize_session_content_request(
                    question=question,
                    presentation=p.get("presentation"),
                    selection=p.get("selection"),
                    analysis=p.get("analysis"),
                ))
                tc["params"] = p
            valid.append(tc)
        return valid
