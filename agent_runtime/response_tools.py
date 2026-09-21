"""Response and tool normalization mixin methods for BrachyAgent.

The methods are kept as regular class methods so the public AgenticSys.BrachyAgent
API remains compatible while the monolithic implementation is easier to review.
"""

import json
import logging
import math
import os
import re
from typing import Any, Dict, List, Mapping, Optional


from agent_runtime.core import ToolResultPipeline
from agent_runtime.response_contract import presentation_fallback_message
from agent_runtime.turn_policy import (
    classify_local_turn,
    is_current_case_dose_recompute_request,
    is_planning_reexecution_request,
    is_surgical_guide_generation_request,
    is_viewer_result_display_request,
    requires_planning_before_guide,
    resolve_report_request_action,
    unambiguous_report_generation_request,
    unambiguous_guide_generation_request,
    resolve_session_content_target,
    resolve_session_visual_location_request,
    resolve_ui_operation_request,
    _has_visual_annotation_request,
)
from agent_runtime.shortcut_contract import planning_command, explicit_repeat, explicit_segmentation_request
from plans.dose_pre.model_loader import resolve_prescription_gy
from tool_factory.ui_controller import normalize_ui_controller_request, CONTROL_REGISTRY
from utils.user_errors import format_tool_error, sanitize_user_response
from agent_runtime import request_parse as _request_parse
from agent_runtime.execution_authorization import MUTATING_TOOLS

logger = logging.getLogger(__name__)


def _canonical_ui_action_value(value: Any) -> str:
    """Stable value comparison for provider-vs-user UI action authorization."""
    if value is None:
        return ""
    if isinstance(value, str):
        raw = value.strip()
        try:
            parsed = json.loads(raw)
        except Exception:
            return re.sub(r"\s+", " ", raw).strip().casefold()
        return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _ui_action_signature(action: Mapping[str, Any]) -> tuple:
    """Compare only executable identity and payload, not provider diagnostics."""
    return (
        str(action.get("target") or "").strip().casefold(),
        str(action.get("command") or "set").strip().casefold(),
        _canonical_ui_action_value(action.get("value")),
    )


class ResponseToolMixin:
    @staticmethod
    def _force_reexecution_requested(message: str = "", params: Optional[Dict] = None) -> bool:
        """Detect an explicit request to replace a reusable clinical result.

        State-aware routing remains the default.  This flag is deliberately
        limited to reuse decisions; it never bypasses model, geometry, or
        safety validation.
        """
        params = params or {}
        if explicit_repeat(message):
            return True
        if any(bool(params.get(key)) for key in ("force_reexecution", "force", "overwrite", "rerun")):
            return True
        if is_planning_reexecution_request(message) and planning_command(message):
            return True
        return bool(re.fullmatch(
            r"(?:\u518d\u6b21|\u518d\u5206\u5272|\u91cd\u65b0\u5206\u5272|\u91cd\u65b0\u89c4\u5212|\u518d\u89c4\u5212|\u91cd\u505a|\u91cd\u8dd1|\u5ffd\u7565\u73b0\u6709|\u4e0d\u4f7f\u7528\u73b0\u6709|"
            r"force|overwrite|rerun|re-run|run again|ignore (?:the )?existing)",
            re.sub(r"^(?:请|帮我|please\s+)", "", str(message or "").strip().lower()).strip(" 。.!"),
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

    @staticmethod
    def _normalize_case_path(path: Any) -> str:
        raw = str(path or "").strip()
        if not raw:
            return ""
        return os.path.normcase(os.path.realpath(os.path.expanduser(raw)))

    def _active_ct_path_for_site(self) -> str:
        memory = getattr(self, "memory", None)
        retrieve = getattr(memory, "retrieve", None)
        path = retrieve("ct_path") if callable(retrieve) else None
        if path:
            return str(path)
        getter = getattr(memory, "get_ui_state", None)
        state = getter() if callable(getter) else {}
        return str(state.get("ct_path") or "") if isinstance(state, Mapping) else ""

    def _active_case_tumor_type(self, image_path: str = "") -> Optional[str]:
        """Use a saved site only when it is bound to the active CT geometry."""
        memory = getattr(self, "memory", None)
        retrieve = getattr(memory, "retrieve", None)
        if not callable(retrieve):
            return None
        current_path = image_path or self._active_ct_path_for_site()
        bound_path = retrieve("tumor_type_used_ct_path")
        if not current_path or not bound_path:
            return None
        if self._normalize_case_path(current_path) != self._normalize_case_path(bound_path):
            return None
        stored = retrieve("tumor_type_used")
        mapped = self._map_tumor_type(str(stored)) if stored else None
        return mapped if mapped in self._SUPPORTED_AUTOMATIC_CTV_TYPES else None

    def _store_tumor_type_binding(self, tumor_type: str, image_path: str = "") -> None:
        """Persist an explicitly used site together with its owning CT path."""
        memory = getattr(self, "memory", None)
        store = getattr(memory, "store", None)
        if not callable(store):
            return
        mapped = self._map_tumor_type(tumor_type)
        if not mapped:
            return
        ct_path = image_path or self._active_ct_path_for_site()
        store("tumor_type_used", mapped)
        # Empty is deliberate: it invalidates a previous case binding rather
        # than allowing a site to leak when the current image path is unknown.
        store("tumor_type_used_ct_path", str(ct_path or ""))

    def _normalize_ctv_tool_params(self, params: Dict, message: str = "") -> Dict:
        """Normalize CTV aliases without trusting a model-selected site.

        For provider calls, only a site stated in this user turn or a site
        already bound to the active CT can select an automatic model. Internal
        execution calls with no message may preserve an already-normalized
        server-selected route.
        """
        normalized = dict(params or {})
        if not normalized.get("image_path"):
            image_alias = normalized.get("ct_image_path") or normalized.get("ct_path")
            if image_alias:
                normalized["image_path"] = image_alias
        # The active Session owns the input image. Never let a provider's stale
        # image_path select a previous case or steer a site binding.
        active_image_path = self._active_ct_path_for_site()
        if message and active_image_path:
            normalized["image_path"] = active_image_path

        supplied = []
        for alias in ("tumor_type", "model", "tumor_site", "site", "organ", "organ_type"):
            value = normalized.get(alias)
            if value is None or not str(value).strip():
                continue
            mapped = self._map_tumor_type(str(value))
            if mapped in self._SUPPORTED_AUTOMATIC_CTV_TYPES and mapped not in supplied:
                supplied.append(mapped)
        for alias in ("model", "tumor_site", "site", "organ", "organ_type", "ct_image_path", "ct_path"):
            normalized.pop(alias, None)

        selected = None
        if message:
            explicit = self._explicit_tumor_types_from_message(message)
            if len(explicit) == 1:
                selected = explicit[0]
            elif len(explicit) == 0:
                # Reuse a site only when it is bound to the server-owned
                # active CT, never to an image path supplied by the model.
                selected = self._active_case_tumor_type()
            # Conflicting explicit sites deliberately suppress both model
            # arguments and case-memory fallback; the CTV tool will ask.
        else:
            # This branch is for the in-process executor after the provider
            # boundary has already checked the current user request.
            if len(supplied) == 1:
                selected = supplied[0]
            elif not supplied:
                selected = self._active_case_tumor_type()

        if selected in self._SUPPORTED_AUTOMATIC_CTV_TYPES:
            normalized["tumor_type"] = selected
        else:
            normalized.pop("tumor_type", None)
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
    def _session_visual_location_screenshot_params(message: str, target: Any) -> Dict:
        """Build a grounded screenshot plan for a live location question.

        The browser captures the live Data Tree first. If the exact target row
        is verified there, it may temporarily reveal that same Session-owned
        object for a Viewer capture and annotation, then restore its prior
        visibility, opacity, and focus. Missing or unresolved targets fail
        closed instead of borrowing a neighboring object.
        """
        text = str(message or "").strip()
        request = dict(target) if isinstance(target, Mapping) else {
            "semantic_targets": [str(target or "").strip().lower()],
            "target_refs": [],
            "target_query": text,
            "target_source": "legacy",
            "target_surfaces": [],
        }
        semantic_targets = list(dict.fromkeys(
            str(value or "").strip().lower()
            for value in (request.get("semantic_targets") or [])
            if str(value or "").strip()
        ))[:32]
        target = semantic_targets[0] if len(semantic_targets) == 1 else "composite"
        is_zh = bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))

        stable_refs: List[str] = [
            str(value or "").strip()
            for value in (request.get("target_refs") or [])
            if str(value or "").strip()
        ]
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
            views = ["data-tree", "viewer-3d"]
            stable_refs = ["surgical_guide:active"]
            object_refs = list(stable_refs)
            data_tree_refs = list(stable_refs)
            title = "手术导板位置" if is_zh else "Surgical guide location"
            description = (
                "先在实时 Data Tree 中核验手术导板节点；如节点存在但 3D 隐藏，则临时显示同一对象后再截 Viewer 并标注，完成后恢复原显示状态。"
                if is_zh
                else "Verify the surgical-guide row in the live Data Tree first; if that exact object is hidden in 3D, temporarily reveal it for a marked Viewer capture, then restore its original display state."
            )
            # The Data Tree row is the first evidence surface. The browser
            # transaction may reveal this exact live object for the Viewer
            # capture, then restores the saved state before returning.
            focus = {"kind": "current-view"}
            overlays = {}
            hide_unrelated = False
            annotation_policy = "required"
        elif target in {"ctv", "oar", "seeds", "needles", "trajectories"}:
            # A visual-location request must name one current-turn semantic
            # object all the way through capture and annotation.  The active
            # aliases are resolved against the live scene/Data Tree registry;
            # they are never substituted with a previously selected artifact.
            stable_ref_by_target = {
                "ctv": "structure:ctv:active",
                "oar": "structure:oar:active",
                "seeds": "group:planning:seeds",
                "needles": "group:planning:needles",
                "trajectories": "group:planning:trajectories",
            }
            stable_refs = [stable_ref_by_target[target]]
            object_refs = list(stable_refs)
            data_tree_refs = list(stable_refs)
            views = ["data-tree", "viewer-3d"]
            labels = {
                "ctv": ("CTV 靶区位置", "CTV target location"),
                "oar": ("危及器官位置", "OAR location"),
                "seeds": ("粒子位置", "Seed locations"),
                "needles": ("穿刺针位置", "Needle locations"),
                "trajectories": ("针道轨迹位置", "Trajectory locations"),
            }
            descriptions = {
                "ctv": ("定位当前病例中已加载且可见的 CTV 肿瘤靶区。", "Locate the loaded, visible CTV tumor target in the current case."),
                "oar": ("定位当前病例中已加载且可见的危及器官。", "Locate the loaded, visible organs at risk in the current case."),
                "seeds": ("定位当前规划中已加载且可见的粒子。", "Locate the loaded, visible seeds in the current plan."),
                "needles": ("定位当前规划中已加载且可见的穿刺针。", "Locate the loaded, visible needles in the current plan."),
                "trajectories": ("定位当前规划中已加载且可见的针道轨迹。", "Locate the loaded, visible trajectories in the current plan."),
            }
            title = labels[target][0 if is_zh else 1]
            description = descriptions[target][0 if is_zh else 1]
            # Preserve the operator's present composition. Exact scene
            # projection/Data Tree bounds provide the marker; if the target is
            # hidden or outside this capture, the browser must report that
            # instead of changing visibility or marking a replacement object.
            focus = {"kind": "current-view"}
            overlays = {}
            hide_unrelated = False
            annotation_policy = "required"
        elif target == "composite" or request.get("target_source") == "live_catalog":
            surfaces = set(str(value or "").strip().lower() for value in (
                request.get("target_surfaces") or []
            ))
            ui_surface_order = [
                "overlay-controls", "input", "metrics", "planning", "report", "full",
            ]
            ui_views = [surface for surface in ui_surface_order if surface in surfaces]
            visual_object_surfaces = surfaces.intersection({
                "3d", "viewer-3d", "scene", "data-tree", "tree", "data_tree",
            })
            if ui_views and not visual_object_surfaces:
                views = ui_views[:4]
                object_refs = []
                data_tree_refs = []
                layout = "single" if len(views) == 1 else "auto"
            else:
                views = []
                if not surfaces or surfaces.intersection({"data-tree", "tree", "data_tree"}):
                    views.append("data-tree")
                if not surfaces or surfaces.intersection({"3d", "viewer-3d", "scene"}):
                    views.append("viewer-3d")
                if not views:
                    # A stable ID with an unknown/new provider may be exposed
                    # on either current visual surface.  Capture both and let
                    # each live manifest independently prove or reject it.
                    views = ["data-tree", "viewer-3d"]
                object_refs = list(stable_refs)
                data_tree_refs = list(stable_refs)
            title = "目标对象位置" if is_zh else "Requested object locations"
            description = (
                "按当前请求中的多个或动态对象身份定位；只标注实时目录与截图清单共同验证的目标。"
                if is_zh else
                "Locate the requested dynamic or combined identities and mark only targets verified by both the live catalog and capture manifest."
            )
            focus = {"kind": "current-view"}
            overlays = {}
            hide_unrelated = False
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
            views = ["data-tree", "viewer-3d"]
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
            # Annotation is rendered on the immutable screenshot. Keep the
            # live Viewer appearance untouched for current-view location
            # evidence; scene highlight IDs are only meaningful for an
            # explicitly framed capture.
            "highlight_object_ids": [] if target in {
                "ui_control:viewer.reconstruct3d", "surgical_guide", "ctv", "oar",
                "seeds", "needles", "trajectories", "data_tree",
                "dvh", "metrics", "dose", "ct", "composite",
            } else object_refs,
            "hide_unrelated": hide_unrelated,
            "focus": focus,
            "overlays": overlays,
            "visual_purpose": "locate",
            "analysis_required": True,
            "annotation_policy": annotation_policy,
            "target_refs": list(stable_refs),
            # This canonical object family is a cross-layer integrity key. The
            # browser and visual child reject any capture/mark whose stable ID
            # does not belong to the current request, preventing a prior turn's
            # guide annotation from satisfying a later CTV question.
            "semantic_target": semantic_targets[0] if len(semantic_targets) == 1 else "composite",
            "semantic_targets": semantic_targets,
            "target_query": str(request.get("target_query") or text)[:8000],
            "target_source": str(request.get("target_source") or "canonical")[:80],
            "request_intent": "session_visual_location_query",
            "preserve_current_view": True,
        }

    def _downstream_update_calls(self, message: str) -> Optional[List[Dict]]:
        """Ordered repair plan for an aggregate "update everything" command.

        The Session already records which downstream artifacts are stale in
        ``artifact_status`` (``quality_check`` / ``report`` / ``surgical_guide``).
        Executing exactly those, in dependency order, is what "全部更新" means;
        deriving it from the record keeps the turn deterministic and avoids
        re-running operations that are already current.  Targets explicitly
        carved out ("不含导板") are skipped.  Returns ``None`` when there is no
        active planning or nothing is stale, leaving the turn to the model.
        """
        parsed = _request_parse.parse_request(message)
        if not _request_parse.is_downstream_update_request(parsed):
            return None
        memory = getattr(self, "memory", None)
        retrieve = getattr(memory, "retrieve", None)
        if not callable(retrieve):
            return None
        # A downstream repair only makes sense once a planning/dose result
        # exists.  Use identity checks so numpy-backed values are never
        # evaluated for truthiness.
        if (
            retrieve("dose_metrics") is None
            and retrieve("planning_results") is None
        ):
            return None
        status = retrieve("artifact_status") or retrieve("manual_artifact_status") or {}
        if not isinstance(status, Mapping):
            status = {}
        stale = {
            str(key)
            for key, value in status.items()
            if str(value).lower() == "stale"
        }
        excluded = set(parsed.excluded_targets)
        calls: List[Dict] = []
        # 1. Quality control must be recomputed before anything that consumes it.
        if stale & {"quality_check", "dose", "dose_metrics"}:
            calls.append({
                "id": "tool_downstream_quality",
                "tool": "dose_evaluation",
                "params": {},
            })
        # 2. Report is regenerated from the current dose/geometry.
        if "report" in stale and "report" not in excluded:
            calls.append({
                "id": "tool_downstream_report",
                "tool": "ui_controller",
                "params": {
                    "actions": [{"target": "report.autofill", "command": "run"}],
                },
            })
        # 3. The guide is only rebuilt when its geometry actually changed.
        if "surgical_guide" in stale and "surgical_guide" not in excluded:
            calls.append({
                "id": "tool_downstream_guide",
                "tool": "surgical_guide",
                "params": {"action": "generate"},
            })
        if not calls:
            return None
        # 4. Reload the refreshed results into the Viewer / Data Tree.
        calls.append({
            "id": "tool_downstream_refresh",
            "tool": "ui_controller",
            "params": {
                "actions": [{"target": "viewer.refresh_planning", "command": "run"}],
            },
        })
        return calls

    def _detect_tool_request(self, message: str) -> Optional[List[Dict]]:
        """Detect explicit tool requests. Returns tool calls in user-specified order, or None.

        Called after local policy classification for deterministic clinical or
        browser actions. Semantic requests still go through the provider; this
        function only materializes commands whose target and parameters are
        unambiguous from the user's request.
        """
        # Independent/legacy callers must pass the same whole-request gate as
        # all chat entrypoints. A rejected candidate must never be revived by
        # the older keyword materializer further below.
        memory = getattr(self, "memory", None)
        ui_state_getter = getattr(memory, "get_ui_state", None)
        ui_state = ui_state_getter() if callable(ui_state_getter) else None
        retrieve = getattr(memory, "retrieve", None)
        pending = retrieve("pending_clarification") if callable(retrieve) else None
        policy = classify_local_turn(
            message, pending_tumor_site=bool(pending),
            conversation=getattr(memory, "conversation", None), ui_state=ui_state,
        )
        inherited_repeat = explicit_repeat(message) and callable(retrieve) and retrieve("last_segmentation_target") in {"ctv", "oar"}
        # An explicit, unambiguous "3D reconstruct <group>" command is a browser
        # mutation fully determined by the message; it must not be dropped by
        # the semantic direct-execution gate. Only a resolved *reconstruct*
        # operation qualifies, so explanatory or scope-constrained UI
        # candidates ("explain hiding OAR", "set OAR translucent but keep CTV")
        # remain non-permission and stay out of the deterministic path.
        reconstruct_operation = None
        contract_rejected = (
            str(getattr(policy, "routing_reason", "") or "")
            == "whole_request_contract_not_satisfied"
        )
        if (
            not contract_rejected
            and policy.intent not in {"multi_intent_query", "surgical_guide_status_query"}
        ):
            candidate_operation = resolve_ui_operation_request(message, ui_state=ui_state)
            if isinstance(candidate_operation, dict) and not candidate_operation.get("ambiguous"):
                if float(candidate_operation.get("confidence") or 0.0) >= 0.75:
                    candidate_actions = candidate_operation.get("actions")
                    if isinstance(candidate_actions, list) and candidate_actions:
                        targets = {
                            action.get("target")
                            for action in candidate_actions
                            if isinstance(action, dict)
                        }
                        if targets and targets <= {
                            "tree.group.reconstruct3d",
                            "viewer.reconstruct3d",
                        }:
                            reconstruct_operation = candidate_operation
        if not (policy.direct_execution or policy.action_plan or inherited_repeat
                or explicit_segmentation_request(message)
                or reconstruct_operation is not None):
            return None
        # Ambiguous live labels are a clarification state, never permission to
        # continue into the legacy keyword materializer below.
        if policy.intent == "ambiguous_visual_target_query":
            return None
        active_intent = getattr(getattr(self, "_active_turn_policy", None), "intent", None)

        # Materialize only the read-only subcalls accepted by the structured
        # clause resolver. Screenshot subcalls retain their exact clause for
        # target resolution while the original whole request remains attached
        # for the visual follow-up.
        if policy.intent == "multi_intent_query":
            calls = []
            for index, (sub_intent, clause) in enumerate(policy.parsed_subtasks):
                if sub_intent == "surgical_guide_status_query":
                    calls.append({
                        "id": f"tool_direct_guide_status_{index}",
                        "tool": "surgical_guide",
                        "params": {"action": "status"},
                    })
                elif sub_intent == "session_visual_location_query":
                    visual = resolve_session_visual_location_request(
                        clause,
                        conversation=getattr(memory, "conversation", None),
                        ui_state=ui_state,
                    )
                    if not visual or visual.get("requires_discovery") or visual.get("ambiguous"):
                        # One unresolved target must not cancel independently
                        # resolved siblings in the same read-only request.
                        continue
                    params = self._session_visual_location_screenshot_params(clause, visual)
                    params["question"] = message
                    calls.append({
                        "id": f"tool_direct_visual_location_{index}",
                        "tool": "ui_screenshot",
                        "params": params,
                    })
            return calls or None

        if policy.intent == "surgical_guide_status_query":
            return [{
                "id": "tool_direct_surgical_guide_status",
                "tool": "surgical_guide",
                "params": {"action": "status"},
            }]

        # An explicit "update everything" command is executed from the
        # Session's own stale-artifact record, in dependency order, instead of
        # making the model re-derive which downstream results need repair.
        if policy.intent == "downstream_update":
            return self._downstream_update_calls(message)

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
        memory = getattr(self, "memory", None)
        getter = getattr(memory, "get_ui_state", None)
        ui_state = getter() if callable(getter) else {}
        visual_location_request = resolve_session_visual_location_request(
            message,
            conversation=getattr(getattr(self, "memory", None), "conversation", None),
            ui_state=ui_state,
        )
        if visual_location_request and not visual_location_request.get("requires_discovery"):
            return [{
                "id": "tool_direct_session_visual_location",
                "tool": "ui_screenshot",
                "params": self._session_visual_location_screenshot_params(
                    message,
                    visual_location_request,
                ),
            }]

        # UI mutations use the same capability contract as the local turn
        # policy.  Resolve them before the legacy clinical keyword scan so a
        # command mentioning OAR/Viewer cannot fall into ui_content or a
        # segmentation route.  Only a unique, high-confidence capability is
        # executed here; an unresolved request remains available to the
        # inspector-driven semantic path.
        active_policy = getattr(self, "_active_turn_policy", None)
        ui_operation = getattr(active_policy, "ui_operation", None)
        active_intent = getattr(active_policy, "intent", None)
        if not isinstance(ui_operation, dict) and (
            active_policy is None
            or active_intent in {"ui_operation", "ui_control"}
            or reconstruct_operation is not None
        ):
            ui_operation = reconstruct_operation or resolve_ui_operation_request(
                message, ui_state=ui_state
            )
        ui_actions = ui_operation.get("actions") if isinstance(ui_operation, dict) else None
        ui_confidence = float((ui_operation or {}).get("confidence") or 0.0) if isinstance(ui_operation, dict) else 0.0
        if (
            isinstance(ui_actions, list)
            and ui_actions
            and not (ui_operation or {}).get("ambiguous")
            and ui_confidence >= 0.75
        ):
            # Preserve the historical trace identity for this already
            # published typed capability.  The routing decision is still made
            # by the live/typed capability contract; this identifier is only
            # a compatibility label for existing trace consumers.
            trace_id = "tool_direct_ui_operation"
            if len(ui_actions) == 1:
                first_action = ui_actions[0] if isinstance(ui_actions[0], dict) else {}
                if (
                    first_action.get("target") == "tree.group.reconstruct3d"
                    and first_action.get("command") == "run"
                    and first_action.get("value") == "oar"
                ):
                    trace_id = "tool_ui_reconstruct_all_oar"
            return [{
                "id": trace_id,
                "tool": "ui_controller",
                "params": {"actions": ui_actions},
            }]

        msg = message.strip().lower()
        generic_target = self._open_segmentation_target(message)
        ct_path = self.memory.retrieve("ct_path") or ""
        if not ct_path:
            ct_path = (self.memory.get_ui_state() or {}).get("ct_path", "")
        explicit_sites = self._explicit_tumor_types_from_message(message)
        requested_tumor_type = (
            explicit_sites[0] if len(explicit_sites) == 1
            else None if len(explicit_sites) > 1
            else self._active_case_tumor_type(ct_path)
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
            # State gate: a guide that is already ready and whose inputs were
            # not explicitly changed is a read/presentation request, not a new
            # long-running computation.  An explicit "重新/重建/重做/覆盖"
            # keeps the regeneration path.
            memory = getattr(self, "memory", None)
            retrieve = getattr(memory, "retrieve", None)
            existing_guide = None
            if callable(retrieve):
                try:
                    existing_guide = retrieve("surgical_guide")
                except Exception:
                    existing_guide = None
            guide_forced = bool(re.search(
                r"(?:重新|再次|重建|重做|重跑|覆盖|无视现有|忽略现有|overwrite|rerun|re-run)",
                message,
            )) or self._force_reexecution_requested(message)
            if existing_guide and not guide_forced:
                logger.info(
                    "Guide already ready and inputs unchanged; presenting it "
                    "instead of recomputing"
                )
                return [{
                    "id": "tool_direct_surgical_guide_ready",
                    "tool": "ui_controller",
                    "params": {
                        "actions": [{"target": "viewer.refresh_planning", "command": "run"}],
                    },
                }]
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
                result_summary = (
                    result.message[:500]
                    if result.success
                    else format_tool_error(tc["tool"], _reason, result.metadata, _lang)
                )
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
                tool_step["result"] = format_tool_error(tc["tool"], str(e), {}, _lang)
                logger.error(f"Direct tool failed: {tc['tool']}: {e}")
                self.memory.add_message("assistant", f"[Called {tc['tool']}]")
                self.memory.add_message("user", f"[Tool result: {tool_step['result']}]")
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
        ui_validation_error = any(
            step.get("type") == "tool"
            and str(step.get("tool") or "") == "ui_controller"
            and str(step.get("status") or "") == "error"
            for step in steps
        )
        # dose_recompute already has a complete, localized formatter and a
        # deterministic comparison summary. A second LLM synthesis adds cost
        # and can obscure the authoritative result, so return that contract
        # directly. Other direct operations keep their established synthesis
        # path because they may contain richer multi-tool context.
        if direct_tool_names == {"dose_recompute"}:
            response = raw_results
        elif ui_validation_error:
            # A rejected UI action is already a localized, authoritative
            # contract. Never let a second LLM round turn it into a success
            # claim such as "renamed" or "updated".
            response = raw_results
        elif (
            getattr(getattr(self, "_active_turn_policy", None), "intent", None)
            == "surgical_guide_status_query"
            and direct_tool_names == {"surgical_guide"}
        ):
            # Status is a server-derived lifecycle fact, not a text-generation
            # task. Return the localized tool contract without another LLM turn.
            response = raw_results
        elif getattr(getattr(self, "_active_turn_policy", None), "intent", None) == "multi_intent_query":
            # The parent response is also supplied to the hidden visual child
            # as preliminary context. If a screenshot was requested, the child
            # remains responsible for the final answer after capture evidence
            # and annotation have completed.
            if any(
                step.get("tool") == "ui_screenshot" and step.get("status") == "done"
                for step in steps
            ):
                self._visual_analysis_pending = True
            response = self._build_multi_intent_response(
                user_msg, steps, getattr(self, "_active_turn_policy", None),
            )
        elif (
            getattr(getattr(self, "_active_turn_policy", None), "intent", None)
            == "session_visual_location_query"
            and direct_tool_names == {"ui_screenshot"}
        ):
            # This is a typed two-stage presentation turn. The browser owns
            # the capture and will launch one hidden multimodal child for the
            # actual user-facing explanation; do not let the parent response
            # be mistaken for that explanation by streaming or replay code.
            screenshot_ready = any(
                step.get("tool") == "ui_screenshot" and step.get("status") == "done"
                for step in steps
            )
            if screenshot_ready:
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
                # A failed capture plan is not a pending visual turn. Preserve
                # the localized tool failure instead of asking the browser to
                # analyze evidence that will never arrive.
                response = raw_results
        else:
            response = self._synthesize_with_llm(raw_results, steps, _lang, user_msg, query_type)

        # Quality review DISABLED (2026-06-22).
        # if self.multi_agent_wrapper and self.multi_agent_wrapper.enabled:
        #     ...

        return sanitize_user_response(response, lang=_lang)

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
            # A watertight mesh is necessary but not sufficient to claim that
            # every planned channel has an independently printable wall.  The
            # guide generator keeps this spacing audit in the persisted
            # validation payload; carry it into the user-facing report so a
            # topology repair cannot hide a dense-channel manufacturing risk.
            guide_validation = (
                guide_state.get("validation")
                if isinstance(guide_state, dict)
                else None
            )
            guide_spacing = (
                guide_validation.get("needle_spacing")
                if isinstance(guide_validation, dict)
                else None
            )
            if isinstance(guide_spacing, dict) and (
                bool(guide_spacing.get("requires_operator_review"))
                or int(guide_spacing.get("bore_wall_conflict_pair_count") or 0) > 0
            ):
                conflict_count = int(
                    guide_spacing.get("bore_wall_conflict_pair_count") or 0
                )
                minimum_distance = guide_spacing.get("minimum_centerline_distance_mm")
                minimum_wall_distance = guide_spacing.get("minimum_bore_wall_distance_mm")
                try:
                    minimum_distance_text = f"{float(minimum_distance):.2f} mm"
                except (TypeError, ValueError):
                    minimum_distance_text = "unknown"
                try:
                    minimum_wall_distance_text = f"{float(minimum_wall_distance):.2f} mm"
                except (TypeError, ValueError):
                    minimum_wall_distance_text = "unknown"
                guide_summary += " " + L(
                    (
                        f"间距审计发现 {conflict_count} 对通道低于当前独立孔壁间距"
                        f"阈值（最小中心距 {minimum_distance_text}，阈值 {minimum_wall_distance_text}）；"
                        "网格虽已通过闭合性校验，但不能据此视为每条针道都保有独立孔壁，"
                        "打印和临床使用前必须复核针道可制造性。"
                    ),
                    (
                        f"Spacing QA found {conflict_count} channel pairs below the configured"
                        f" independent-wall distance ({minimum_distance_text} minimum centerline"
                        f" distance vs {minimum_wall_distance_text} threshold). The mesh passed"
                        " watertight QA, but this does not prove that every channel retains an"
                        " independent printable wall; verify manufacturability before printing"
                        " or clinical use."
                    ),
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
        target_coverage = float(plan_config.get("DVH_rate") or 0.9)
        if v100_frac + 1e-9 < target_coverage:
            lines.append(L(
                f"⚠️ 当前计划未达到设定的靶区覆盖目标：V100 {v100_frac:.1%} < {target_coverage:.1%}。流程结束不代表剂量目标达成或临床可用；请勿将此结果作为已达标计划。",
                f"⚠️ Configured coverage target NOT reached: V100 {v100_frac:.1%} < {target_coverage:.1%}. Workflow completion does not establish dosimetric goal attainment or clinical suitability."
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
        "liver_tumor": "nnunet_liver_tumor",
        "liver": "nnunet_liver_tumor",
        "kidney_tumor": "nnunet_kidney_tumor",
        "kidney": "nnunet_kidney_tumor",
        "colon_tumor": "biomedparse_colon_primary",
        "colon": "biomedparse_colon_primary",
        "lung_tumor": "biomedparse_lung_lesion",
        "lung": "biomedparse_lung_lesion",
        "head_neck": "biomedparse_head_neck_cancer",
        "head and neck": "biomedparse_head_neck_cancer",
        "pdac": "nnunet_pancreatic",
        "hepatocellular": "nnunet_liver_tumor",
        "hcc": "nnunet_liver_tumor",
        "renal": "nnunet_kidney_tumor",
        "colorectal": "biomedparse_colon_primary",
        "nsclc": "biomedparse_lung_lesion",
        "prostate": "biomedparse_prostate_lesion",
        "prostate_tumor": "biomedparse_prostate_lesion",
        "胰腺癌": "nnunet_pancreatic",
        "胰腺肿瘤": "nnunet_pancreatic",
        "胰腺": "nnunet_pancreatic",
        "肝癌": "nnunet_liver_tumor",
        "肝肿瘤": "nnunet_liver_tumor",
        "肝脏": "nnunet_liver_tumor",
        "肾癌": "nnunet_kidney_tumor",
        "肾肿瘤": "nnunet_kidney_tumor",
        "肾脏": "nnunet_kidney_tumor",
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
        "肝癌患者": "nnunet_liver_tumor",  # liver cancer patient
        "肾癌患者": "nnunet_kidney_tumor",    # kidney cancer patient
        "肺癌患者": "biomedparse_lung_lesion",      # lung cancer patient
        "结肠癌患者": "biomedparse_colon_primary",   # colon cancer patient
    }

    _SUPPORTED_AUTOMATIC_CTV_TYPES = frozenset({
        # Sentinel route: the phase (ncct/cect) is a clinical choice, so the
        # tool asks for it instead of guessing from image intensity.
        "nasopharynx",
        "vista3d_lung_tumor",
        "nnunet_head_neck_gtv",
        "nnunet_nasopharynx_ncct",
        "nnunet_nasopharynx_cect",
        "nnunet_pancreatic",
        "nnunet_liver_tumor",
        "nnunet_kidney_tumor",
        "biomedparse_lung_lesion",
        "biomedparse_colon_primary",
        "biomedparse_head_neck_cancer",
        "biomedparse_prostate_lesion",
    })

    def _map_tumor_type(self, tumor_type: Optional[str]) -> Optional[str]:
        """Map an exact explicit site/model alias; never infer by substring."""
        if tumor_type is None:
            return None
        raw = str(tumor_type).strip()
        if not raw:
            return None
        compact = re.sub(r"[\s_/-]+", "", raw.casefold())
        if compact in {
            "tumor", "tumour", "cancer", "lesion", "ctv", "target",
            "肿瘤", "肿瘤分割", "病灶", "癌症", "癌", "ctv分割", "automatic", "auto", "default",
        }:
            return None
        try:
            from tool_factory.CTV_seg import normalize_tumor_type
            canonical = normalize_tumor_type(raw)
        except Exception:
            canonical = raw
        if canonical in self._SUPPORTED_AUTOMATIC_CTV_TYPES:
            return canonical
        mapped = self._TUMOR_TYPE_MAP.get(raw.casefold())
        if mapped:
            try:
                from tool_factory.CTV_seg import normalize_tumor_type
                return normalize_tumor_type(mapped)
            except Exception:
                return mapped
        # Unsupported explicit sites stay unsupported so the unified tool can
        # ask for a verified model; fuzzy substring matches are unsafe.
        logger.warning("Unknown tumor_type '%s'; no automatic route selected", raw)
        return canonical if canonical in self._SUPPORTED_AUTOMATIC_CTV_TYPES else None

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

    def _explicit_tumor_types_from_message(self, message: str) -> List[str]:
        """Return distinct positive, non-quoted sites from this turn only.

        Site names in negated, conditional, or attributed clauses cannot steer
        the model route. This uses the shared clause parser so site scope stays
        aligned with the authorization parser.
        """
        raw_message = self._message_text(message)
        if not raw_message:
            return []
        parsed = _request_parse.parse_request(raw_message)
        fragments = []
        for task in parsed.subtasks:
            if task.negated or task.conditional or task.attributed:
                continue
            fragment = _request_parse._mask_quoted_content(task.raw)
            if fragment.strip():
                fragments.append(fragment)
        if not fragments:
            return []
        text = " ".join(fragments).casefold()
        aliases = (
            ("鼻咽癌平扫", "nnunet_nasopharynx_ncct"),
            ("鼻咽平扫", "nnunet_nasopharynx_ncct"),
            ("鼻咽癌增强", "nnunet_nasopharynx_cect"),
            ("鼻咽增强", "nnunet_nasopharynx_cect"),
            ("胰腺肿瘤", "nnunet_pancreatic"), ("胰腺癌", "nnunet_pancreatic"), ("胰腺", "nnunet_pancreatic"),
            ("肝脏肿瘤", "nnunet_liver_tumor"), ("肝肿瘤", "nnunet_liver_tumor"), ("肝癌", "nnunet_liver_tumor"), ("肝脏", "nnunet_liver_tumor"), ("肝", "nnunet_liver_tumor"),
            ("肾脏肿瘤", "nnunet_kidney_tumor"), ("肾肿瘤", "nnunet_kidney_tumor"), ("肾癌", "nnunet_kidney_tumor"), ("肾脏", "nnunet_kidney_tumor"), ("肾", "nnunet_kidney_tumor"),
            ("肺部肿瘤", "vista3d_lung_tumor"), ("肺肿瘤", "vista3d_lung_tumor"), ("肺癌", "vista3d_lung_tumor"), ("肺部", "vista3d_lung_tumor"), ("肺", "vista3d_lung_tumor"),
            ("结直肠癌", "biomedparse_colon_primary"), ("结肠肿瘤", "biomedparse_colon_primary"), ("结肠癌", "biomedparse_colon_primary"), ("结肠", "biomedparse_colon_primary"),
            ("头颈部肿瘤", "nnunet_head_neck_gtv"), ("头颈部", "nnunet_head_neck_gtv"), ("头颈肿瘤", "nnunet_head_neck_gtv"), ("头颈", "nnunet_head_neck_gtv"),
            ("前列腺癌", "biomedparse_prostate_lesion"), ("前列腺肿瘤", "biomedparse_prostate_lesion"), ("前列腺", "biomedparse_prostate_lesion"),
        )
        found = []
        for alias, route in aliases:
            if alias in text:
                mapped = self._map_tumor_type(route)
                if mapped and mapped not in found:
                    found.append(mapped)
        english_aliases = (
            (r"(?<![a-z0-9_])(?:pancreas|pancreatic)(?![a-z0-9_])", "nnunet_pancreatic"),
            (r"(?<![a-z0-9_])(?:liver|hepatic)(?![a-z0-9_])", "nnunet_liver_tumor"),
            (r"(?<![a-z0-9_])(?:kidney|renal)(?![a-z0-9_])", "nnunet_kidney_tumor"),
            (r"(?<![a-z0-9_])(?:lung|pulmonary)(?![a-z0-9_])", "vista3d_lung_tumor"),
            (r"(?<![a-z0-9_])(?:colon|colorectal)(?![a-z0-9_])", "biomedparse_colon_primary"),
            (r"(?<![a-z0-9_])(?:head\s*(?:and|&)\s*neck|head[-\s]+neck)(?![a-z0-9_])", "nnunet_head_neck_gtv"),
            (r"(?<![a-z0-9_])(?:prostate)(?![a-z0-9_])", "biomedparse_prostate_lesion"),
        )
        for pattern, route in english_aliases:
            if re.search(pattern, text, re.IGNORECASE):
                mapped = self._map_tumor_type(route)
                if mapped and mapped not in found:
                    found.append(mapped)
        if re.search(r"(?<![a-z0-9_])(?:nasopharynx|nasopharyngeal)(?![a-z0-9_])", text, re.IGNORECASE) or "鼻咽" in text:
            ncct = bool(re.search(r"ncct|non[-\s]?contrast|平扫", text, re.IGNORECASE))
            cect = bool(re.search(r"cect|contrast[-\s]?enhanced|增强", text, re.IGNORECASE))
            if ncct != cect:
                route = "nnunet_nasopharynx_ncct" if ncct else "nnunet_nasopharynx_cect"
            else:
                route = "nasopharynx"
            mapped = self._map_tumor_type(route)
            if mapped and mapped not in found:
                found.append(mapped)
        return found

    def _detect_tumor_type_from_message(
        self, message: str, *, include_context: bool = True, image_path: str = "",
    ) -> Optional[str]:
        """Resolve only this turn's explicit site, then optional case-bound site."""
        explicit = self._explicit_tumor_types_from_message(message)
        if len(explicit) == 1:
            return explicit[0]
        if len(explicit) > 1:
            return None
        return self._active_case_tumor_type(image_path) if include_context else None

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
            "当前仓库",
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
        guard_memory = getattr(self, "memory", None)
        guard_question = ""
        for item in reversed(getattr(guard_memory, "conversation", []) or []):
            if isinstance(item, dict) and str(item.get("role", "")).lower() == "user":
                candidate = self._message_text(item.get("content", ""))
                if candidate and not _request_parse.is_internal_tool_result_message(candidate):
                    guard_question = candidate
                    break
        if getattr(active_policy, "intent", None) == "ambiguous_visual_target_query":
            # Ambiguity is a clarification response, not a discovery request.
            # Do not let provider-selected captures bypass that decision.
            logger.warning("Dropping provider calls for an ambiguous visual target")
            return []
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
        if getattr(active_policy, "intent", None) == "session_visual_discovery_query":
            # Open discovery is not open-ended execution.  The only legal
            # sequence is: inspect the current browser-published registry,
            # then optionally capture stable IDs that registry actually
            # contains.  If the requested object does not exist, the model
            # answers that fact and no neighboring/previous object is used.
            read_only_calls = [
                call for call in (tool_calls or [])
                if str(call.get("tool") or "") in {"ui_inspector", "ui_screenshot"}
            ]
            ui_state = self.memory.get_ui_state() if hasattr(self.memory, "get_ui_state") else {}
            catalog = ui_state.get("visual_target_catalog") if isinstance(ui_state, dict) else []
            catalog_refs = set()
            for item in catalog if isinstance(catalog, list) else []:
                if not isinstance(item, dict):
                    continue
                refs = item.get("target_refs", item.get("targetRefs", item.get("identities", [])))
                if isinstance(refs, str):
                    refs = [refs]
                if isinstance(refs, (list, tuple)):
                    catalog_refs.update(
                        str(ref or "").strip() for ref in refs if str(ref or "").strip()
                    )
            filtered_calls = []
            def _list_param(params: Dict, key: str) -> List[Any]:
                value = params.get(key)
                if isinstance(value, (list, tuple)):
                    return list(value)
                return [value] if value not in (None, "") else []

            for call in read_only_calls:
                if str(call.get("tool") or "") != "ui_screenshot":
                    filtered_calls.append(call)
                    continue
                params = call.get("params") if isinstance(call.get("params"), dict) else {}
                requested_question = str(
                    guard_question or params.get("question") or ""
                ).strip()
                location = resolve_session_visual_location_request(
                    requested_question,
                    conversation=getattr(self.memory, "conversation", None),
                    ui_state=ui_state,
                )
                if (
                    not location
                    or location.get("requires_discovery")
                    or location.get("ambiguous")
                ):
                    logger.warning(
                        "Dropping discovery screenshot: current request has no unique live target"
                    )
                    continue
                expected_refs = {
                    str(ref or "").strip()
                    for ref in (location.get("target_refs") or [])
                    if str(ref or "").strip()
                }
                refs = [
                    str(ref or "").strip()
                    for ref in [
                        *_list_param(params, "target_refs"),
                        *_list_param(params, "object_ids"),
                        *_list_param(params, "data_tree_node_ids"),
                    ]
                    if str(ref or "").strip()
                ]
                provided_refs = set(refs)
                if (
                    not expected_refs
                    or not provided_refs
                    or not provided_refs.issubset(expected_refs)
                    or not expected_refs.issubset(catalog_refs)
                ):
                    logger.warning(
                        "Dropping discovery screenshot: provider refs do not match "
                        "the unique target resolved from the current request"
                    )
                    continue
                grounded = self._session_visual_location_screenshot_params(
                    requested_question, location
                )
                params.update(grounded)
                params["question"] = requested_question
                params["request_intent"] = "session_visual_discovery_query"
                call["params"] = params
                filtered_calls.append(call)
            tool_calls = filtered_calls
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

        # Object-level mis-selection guard: an unambiguous report mutation can
        # never be executed by the guide tool or by a read-only presentation
        # tool. A provider occasionally maps "手术报告" (surgical report) to
        # `surgical_guide` because of the word "手术". Keep the protected
        # report object attached to the single report capability even when a
        # semantic/compound turn bypassed the deterministic report route.
        # Negation/compound wording is excluded by the predicate itself, so
        # only the wrong-object call is corrected and every other planned
        # action is preserved.
        if guard_question and unambiguous_report_generation_request(guard_question):
            guard_params = {"actions": [{"target": "report.autofill", "command": "run"}]}
            guarded: List[Dict] = []
            converted = False
            for call in (tool_calls or []):
                if str(call.get("tool") or "") in {"surgical_guide", "ui_screenshot", "ui_content"}:
                    if not converted:
                        guarded.append({**call, "tool": "ui_controller", "params": guard_params})
                        converted = True
                else:
                    guarded.append(call)
            tool_calls = guarded

        # Symmetric object-level guard: an unambiguous guide mutation can never
        # be executed by the report capability, even if the provider selected
        # ``report_auto_fill``/``report_generator`` for wording that merely
        # mentions a report as an output.  Compound "guide and report" turns
        # are excluded by the predicate itself and keep their semantic plan.
        if guard_question and unambiguous_guide_generation_request(guard_question):
            guide_params = {"action": "generate"}
            guided: List[Dict] = []
            converted = False
            for call in (tool_calls or []):
                if str(call.get("tool") or "") in {
                    "report_auto_fill", "report_generator", "ui_screenshot", "ui_content",
                }:
                    if not converted:
                        guided.append({**call, "tool": "surgical_guide", "params": guide_params})
                        converted = True
                else:
                    guided.append(call)
            tool_calls = guided

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
                # Provider-supplied tool arguments are not the user's request.
                # Bind this typed conversion to the server's current user turn,
                # which is also the text used for local intent authorization.
                if (
                    getattr(active_policy, "intent", None) == "report_generation"
                    and getattr(active_policy, "direct_execution", False)
                    and guard_question
                    and resolve_report_request_action(guard_question) == "regenerate"
                    and _request_parse.mutating_execution_authorized(
                        guard_question, "report_auto_fill"
                    )
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
                if not guard_question:
                    logger.warning(
                        "Dropping provider CTV call without a current user request"
                    )
                    continue
                # LLM calls can contain a friendly site name, an old saved
                # VoCo alias, or a BiomedParse catalog id. Normalize before
                # the tool schema is checked so all entry points use the same
                # canonical model route.
                p = self._normalize_ctv_tool_params(p, message=guard_question)
                tc["params"] = p
            elif tn == "ui_controller":
                # Normalize: LLM may pass target/command at top level instead of inside actions
                if "target" in p and "actions" not in p:
                    p["actions"] = [{"target": p.pop("target"), "command": p.pop("command", "set"), "value": p.pop("value", None)}]
                # Providers and older clients may use a semantic envelope
                # (action + transparency/opacity + a structured group target)
                # instead of the canonical registry target. Normalize it
                # before validation so the browser receives only executable
                # capability actions.
                p = normalize_ui_controller_request(p)
                if not p.get("actions"):
                    logger.warning(f"Dropping ui_controller call with no actions")
                    continue
                # Action-level whitelist and destructive-command gate. Unknown
                # targets cannot execute, and clear/delete/reset actions require
                # an explicit command in the current user turn instead of an
                # inferred one.
                current_turn = guard_question or ""
                memory = getattr(self, "memory", None)
                get_ui_state = getattr(memory, "get_ui_state", None)
                current_ui_state = get_ui_state() if callable(get_ui_state) else {}
                expected_actions = []
                policy_ui = getattr(active_policy, "ui_operation", None)
                if isinstance(policy_ui, dict) and not policy_ui.get("ambiguous"):
                    expected_actions.extend(
                        item for item in policy_ui.get("actions", [])
                        if isinstance(item, Mapping)
                    )
                if current_turn:
                    resolved_ui = resolve_ui_operation_request(
                        current_turn, ui_state=current_ui_state
                    )
                    if isinstance(resolved_ui, dict) and not resolved_ui.get("ambiguous"):
                        expected_actions.extend(
                            item for item in resolved_ui.get("actions", [])
                            if isinstance(item, Mapping)
                        )
                    # Report autofill has a server-owned typed UI action. It
                    # is granted only by the same target/action parser used
                    # for clinical mutations, not by the provider's choice.
                    if (
                        resolve_report_request_action(current_turn) == "regenerate"
                        and _request_parse.mutating_execution_authorized(
                            current_turn, "report_auto_fill"
                        )
                    ):
                        expected_actions.append({
                            "target": "report.autofill",
                            "command": "run",
                        })
                    # Destructive UI controls must be materialized from the
                    # same positive, clause-local request that authorizes
                    # them. The provider's chosen target alone is never a grant.
                    for destructive_target in sorted(
                        _request_parse.DESTRUCTIVE_UI_TARGETS
                    ):
                        if _request_parse.ui_action_explicitly_authorized(
                            current_turn, destructive_target
                        ):
                            expected_actions.append({
                                "target": destructive_target,
                                "command": "run",
                            })
                allowed_ui_signatures = {
                    _ui_action_signature(item) for item in expected_actions
                }
                safe_actions = []
                for action in p.get("actions") or []:
                    if not isinstance(action, dict):
                        continue
                    target = str(action.get("target") or "")
                    if target not in CONTROL_REGISTRY:
                        logger.warning(
                            "Dropping ui_controller action with unregistered target %r",
                            target,
                        )
                        continue
                    if not current_turn or _ui_action_signature(action) not in allowed_ui_signatures:
                        logger.warning(
                            "Blocking ui_controller action %r: it does not match a "
                            "positive current-turn UI subtask",
                            target,
                        )
                        continue
                    if not _request_parse.ui_action_explicitly_authorized(
                        current_turn, target
                    ):
                        logger.warning(
                            "Blocking destructive ui_controller action %r without an "
                            "explicit clear/delete command",
                            target,
                        )
                        continue
                    safe_actions.append(action)
                if not safe_actions:
                    logger.warning("Dropping ui_controller call with no authorized actions")
                    continue
                p["actions"] = safe_actions
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
                # The provider chose a screenshot, not a clinical mutation.
                # Preserve the actual user question (including its language)
                # and bind location evidence to the whole-request resolver.
                # This also carries a deictic Data Tree follow-up's subject;
                # never infer its subject from whichever rows are on screen.
                question = guard_question or str(p.get("question") or "").strip()
                p["question"] = question
                memory = getattr(self, "memory", None)
                getter = getattr(memory, "get_ui_state", None)
                conversation = getattr(memory, "conversation", None)
                ui_state = getter() if callable(getter) else {}
                location = None
                if getattr(active_policy, "intent", None) == "multi_intent_query":
                    # A multi-target turn has one full user question but
                    # several independently resolved screenshot plans. Match
                    # this call back to exactly one canonical visual subtask;
                    # never re-resolve the whole sentence here, since that
                    # would replace a guide/CTV plan with a composite target.
                    requested_refs = {
                        str(ref or "").strip()
                        for key in ("target_refs", "object_ids", "data_tree_node_ids")
                        for ref in (
                            p.get(key) if isinstance(p.get(key), (list, tuple))
                            else [p.get(key)]
                        )
                        if str(ref or "").strip()
                    }
                    requested_semantic = str(
                        p.get("semantic_target") or p.get("semanticTarget") or ""
                    ).strip().lower()
                    requested_query = re.sub(
                        r"\s+", " ",
                        str(p.get("target_query") or p.get("targetQuery") or "").strip(),
                    ).casefold()
                    for sub_intent, clause in (
                        getattr(active_policy, "parsed_subtasks", ()) or ()
                    ):
                        if sub_intent != "session_visual_location_query":
                            continue
                        candidate = resolve_session_visual_location_request(
                            clause,
                            conversation=conversation,
                            ui_state=ui_state,
                        )
                        if not candidate or candidate.get("requires_discovery"):
                            continue
                        expected = self._session_visual_location_screenshot_params(
                            clause, candidate
                        )
                        expected_refs = {
                            str(ref or "").strip()
                            for ref in expected.get("target_refs", [])
                            if str(ref or "").strip()
                        }
                        expected_query = re.sub(
                            r"\s+", " ",
                            str(candidate.get("target_query") or clause).strip(),
                        ).casefold()
                        if (
                            requested_refs
                            and requested_refs == expected_refs
                            and requested_semantic == str(
                                expected.get("semantic_target") or ""
                            ).strip().lower()
                            and requested_query
                            and requested_query == expected_query
                        ):
                            location = candidate
                            break
                    if location is None:
                        logger.warning(
                            "Dropping multi-intent screenshot not bound to a "
                            "resolved visual subtask"
                        )
                        continue
                else:
                    location = resolve_session_visual_location_request(
                        p["question"],
                        conversation=conversation,
                        ui_state=ui_state,
                    )
                if (
                    p.get("mode", "chat") == "chat"
                    and getattr(active_policy, "intent", None) == "session_visual_location_query"
                    and (
                        not location
                        or location.get("requires_discovery")
                        or location.get("ambiguous")
                    )
                ):
                    logger.warning(
                        "Dropping screenshot because the current visual target "
                        "no longer resolves uniquely"
                    )
                    continue
                if (p.get("mode", "chat") == "chat"
                        and location and not location.get("requires_discovery")):
                    grounded = self._session_visual_location_screenshot_params(p["question"], location)
                    # Keep a specifically requested Data Tree-only view. All
                    # other locate captures use the resolved multi-view plan.
                    explicit_views = p.get("views") or [p.get("target")]
                    tree_only = all(
                        (v.get("target") if isinstance(v, dict) else v) == "data-tree"
                        for v in explicit_views
                    )
                    p.update(grounded)
                    if tree_only:
                        p["views"] = ["data-tree"]
                    p["annotation_policy"] = "required"
                    tc["params"] = p
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
        # Second-line authorization for provider-selected mutations.  A local
        # deterministic fast path already validated the whole request through
        # ``shortcut_supported``; a semantic turn is checked against the parsed
        # current command here so a question, negation, quoted log or purely
        # conditional sentence can never execute a write merely because the
        # provider selected its tool.  ui_controller is governed by the
        # action-level gate above.
        blocked_mutating: List[str] = []
        if guard_question and getattr(self, "_active_turn_policy", None) is not None and not getattr(
            getattr(self, "_active_turn_policy", None), "direct_execution", False
        ):
            conversation = getattr(getattr(self, "memory", None), "conversation", None)
            allowed = []
            for call in valid:
                tool_name = str(call.get("tool") or "")
                if (
                    tool_name in MUTATING_TOOLS
                    and tool_name != "ui_controller"
                    and not _request_parse.mutating_execution_authorized(
                        guard_question, tool_name, conversation
                    )
                ):
                    logger.warning(
                        "Blocked mutating tool %r: current turn is not an affirmative "
                        "command for that operation",
                        tool_name,
                    )
                    blocked_mutating.append(tool_name)
                    continue
                allowed.append(call)
            valid = allowed
        # Surface the dropped operations to the turn so the model can ask for
        # an explicit confirmation instead of the user seeing a generic
        # "no verifiable result".  Reset every call so it reflects one turn.
        self._blocked_mutating_tool_names = blocked_mutating
        return valid
