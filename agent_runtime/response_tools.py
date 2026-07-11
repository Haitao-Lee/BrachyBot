"""Response and tool normalization mixin methods for BrachyAgent.

The methods are kept as regular class methods so the public AgenticSys.BrachyAgent
API remains compatible while the monolithic implementation is easier to review.
"""

import asyncio
import base64
import io
import json
import logging
import os
import re
import threading
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

import numpy as np
import SimpleITK as sitk

from config.prompts import SYSTEM_PROMPT_TEMPLATE, get_prompt_modules
from agent_runtime.core import PlanningPhase, ToolResultPipeline
from plans.dose_pre.model_loader import DOSE_MODEL_SCALE_GY

logger = logging.getLogger(__name__)


class ResponseToolMixin:
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

    def _detect_tool_request(self, message: str) -> Optional[List[Dict]]:
        """Detect explicit tool requests. Returns tool calls in user-specified order, or None.
        Bypasses LLM to prevent unnecessary questions or wrong skill chains."""
        msg = message.strip().lower()
        ct_path = self.memory.retrieve("ct_path") or ""
        if not ct_path:
            ct_path = (self.memory.get_ui_state() or {}).get("ct_path", "")

        # Find action keywords and their positions to preserve user's intended order
        # Bilingual patterns: Chinese terms match Chinese user input.
        # zh: 分割=segment, 靶区=target, 肿瘤=tumor, 器官=organ, 危及器官=OAR
        ACTION_PATTERNS = [
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

        # If no specific segment found but generic "segment" is present, add segment_all
        has_specific_seg = 'segment_ctv' in seen or 'segment_oar' in seen
        if not has_specific_seg:
            for match in re.finditer(r'(分割|segment|再分)', msg, re.IGNORECASE):
                start, end = match.span()
                overlaps = any(not (end <= s or start >= e) for s, e in matched_spans)
                if not overlaps:
                    ordered_actions.append('segment_all')
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

        if not ordered_actions:
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

            if action == 'analyze' and ct_path:
                code = self._ANALYSIS_CODE_TEMPLATE.format(ct_path=ct_path)
                tools.append({"id": "tool_direct_analysis", "tool": "code_executor",
                              "params": {"code": code, "description": "Analyze CT image"}})
            elif action == 'segment_ctv' and ct_path:
                tools.append({"id": "tool_direct_ctv", "tool": "ctv_segmentation", "params": {"image_path": ct_path}})
            elif action == 'segment_oar' and ct_path:
                tools.append({"id": "tool_direct_oar", "tool": "oar_segmentation", "params": {"image_path": ct_path}})
            elif action == 'segment_all' and ct_path:
                tools.append({"id": "tool_direct_ctv", "tool": "ctv_segmentation", "params": {"image_path": ct_path}})
                tools.append({"id": "tool_direct_oar", "tool": "oar_segmentation", "params": {"image_path": ct_path}})
            elif action == 'dose' and ct_path:
                tools.append({"id": "tool_direct_dose", "tool": "dose_engine", "params": {}})

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
                result = self._validate_and_execute(tc['tool'], tc['params'])
                tool_step["status"] = "done"
                tool_step["result"] = self._format_tool_result(tc['tool'], result, lang=_lang)
                tool_step["metadata"] = result.metadata if result.success else {}
                tool_step["data"] = result.data if result.success else {}
                if result.success:
                    self._store_tool_result(tc['tool'], result)
                # Store tool call + result in conversation for context persistence
                self.memory.add_message("assistant", f"[Called {tc['tool']}]")
                result_summary = result.message[:500] if result.success else f"Error: {result.error}"
                self.memory.add_message("user", f"[Tool result: {result_summary}]")
            except Exception as e:
                tool_step["status"] = "error"
                tool_step["result"] = str(e)
                logger.error(f"Direct tool failed: {tc['tool']}: {e}")
                self.memory.add_message("assistant", f"[Called {tc['tool']}]")
                self.memory.add_message("user", f"[Tool result: Error: {str(e)[:200]}]")
            # Yield completed step for streaming UI (enables incremental viewer updates)
            if yield_event:
                yield_event(tool_step)

        # Build raw results summary, then synthesize with LLM
        raw_results = self._build_direct_response(steps, _lang)
        user_msg = ""
        for msg in reversed(self.memory.conversation):
            if msg.get("role") == "user":
                user_msg = msg.get("content", "")
                break
        query_type = self._classify_query_type(user_msg)
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

        # Extract prescription dose in Gy.
        #
        # DOSE_SCALE (120.0): the dose prediction model (myDoseNet) was
        # trained with labels where model output 1.0 = 120 Gy.  All
        # internal dose values are in "normalized" units (0~1.0 for
        # prescription, 0~255 for raw CNN output).  To convert to Gy:
        #   dose_gy = dose_normalized * DOSE_SCALE
        # This factor is the same as in planning_pipeline.py and
        # The web planning routes use the same display scale for dose summaries.
        DOSE_SCALE = DOSE_MODEL_SCALE_GY
        rx_gy = DOSE_SCALE  # default: 1.0 * 120 = 120 Gy
        try:
            _plan_cfg = self.memory.retrieve("plan_config") or {}
            # "in_lowest_energy" is the normalized prescription (typically 1.0).
            # "prescription_dose" is a legacy key — both map to the same value.
            _rx_norm = _plan_cfg.get("in_lowest_energy",
                         _plan_cfg.get("prescription_dose", 1.0))
            rx_gy = float(_rx_norm) * DOSE_SCALE
        except Exception as exc:
            logger.debug("Could not parse prescription dose from plan_config; using default 120 Gy: %s", exc)

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

        def _ctv_source_labels(source):
            source = str(source or "").strip()
            if source in {"manual_label", "label_path", "user_label"}:
                return (
                    L("用户提供的 CTV", "user-provided CTV"),
                    L("手动/导入 CTV 标签", "manual/imported CTV label"),
                )
            if not source or source == "unknown":
                return (L("未记录", "not recorded"), L("未记录", "not recorded"))
            clean = source.replace("_", " ").replace("nnunet ", "").replace("voco ", "")
            return (clean, f"CTV model ({source})")

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
        # Section 1: Workflow Summary
        lines.append(f"## {L('1. 流程总结', '1. Workflow Summary')}")
        lines.append("")
        # Find CTV/OAR/planning tool names from steps
        tools_run = []
        if steps:
            for s in steps:
                if s.get("tool") in ("ctv_segmentation", "oar_segmentation",
                                       "planning_pipeline", "trajectory_planning"):
                    tools_run.append(s["tool"])
        tools_summary = ", ".join(set(tools_run)) if tools_run else "ctv_segmentation, planning_pipeline"
        lines.append(L(
            f"已完成放射性粒子植入规划全流程,执行工具:{tools_summary}。靶区覆盖率V100达{v100_frac*100:.1f}%,D90为{d90_gy:.2f} Gy,规划评分{ps_pct:.0f}/100。",
            f"Brachytherapy planning pipeline completed. Tools executed: {tools_summary}. CTV coverage V100 = {v100_frac*100:.1f}%, D90 = {d90_gy:.2f} Gy, plan score = {ps_pct:.0f}/100."
        ))
        lines.append("")

        # Section 2: CTV Segmentation
        ctv_vol_str = f"{ctv_vol_cm3:.2f} cm³" if ctv_vol_cm3 else "N/A"
        ctv_location_label, ctv_algorithm_label = _ctv_source_labels(tumor_type)
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
            lines.append(f"| {L('危及器官', 'OAR')} | {L('最大剂量 (Gy)', 'Dmax (Gy)')} | D2cc (Gy) | D1cc (Gy) | {L('解释状态', 'Interpretation status')} |")
            lines.append("|" + "|".join(["---"] * 5) + "|")
            for organ, om in sorted(oar_metrics.items(), key=lambda kv: _metric_dmax(kv[1]), reverse=True):
                dmax = _metric_dmax(om)
                d2cc = om.get('d2cc') or 0
                d1cc = om.get('d1cc') or 0
                # Do not infer PASS/WARN/FAIL from generic local ratios.
                # OAR tolerances are site-specific; use clinical_kb or explicit
                # plan_config constraints for clinical interpretation.
                status = L('需结合 clinical_kb/plan_config 判读', 'Needs clinical_kb/plan_config review')
                lines.append(f"| {organ} | {dmax:.2f} | {d2cc:.2f} | {d1cc:.2f} | {status} |")
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
                    f"- {organ}: Dmax={dmax:.2f} Gy, D2cc={d2cc:.2f} Gy. "
                    f"{L('请用 clinical_kb 或显式 plan_config 的部位特异性限值判读。', 'Interpret with site-specific limits from clinical_kb or explicit plan_config.')}"
                )
        review_items.append(
            f"- V100={v100:.1f}%, V150={v150:.1f}%, V200={v200:.1f}%, D90={d90:.2f} Gy. "
            f"{L('这些是观测指标,不是本地模板自动达标结论。', 'These are observed metrics, not a local-template acceptability verdict.')}"
        )
        lines.extend(review_items)
        lines.append("")

        # Section 8: Clinical Recommendations
        lines.append(f"## {L('8. 临床建议', '8. Clinical Recommendations')}")
        lines.append("")
        lines.append(f"- {L('请放射肿瘤科医师审核本计划并签署批准', 'Have a radiation oncologist review and sign off on this plan')}")
        lines.append(f"- {L('使用独立剂量算法进行二次校验(蒙特卡罗或 TG-43)', 'Perform secondary dose verification using an independent algorithm (Monte Carlo or TG-43)')}")
        if oar_metrics:
            lines.append(f"- {L('在 clinical_kb 中检索当前病种的 OAR 限值后再给出超限/通过结论', 'Query clinical_kb for this tumor site before labeling any OAR as exceeded or passed')}")
        lines.append(f"- {L('术后 1 个月复查 CT,评估粒子迁移和剂量验证', 'Schedule a 1-month follow-up CT to assess seed migration and dose verification')}")
        lines.append("")

        # Section 9: References
        lines.append(f"## {L('9. 参考文献', '9. References')}")
        lines.append("")
        lines.append(f"- {L('部位特异性阈值和 OAR 限值应由 clinical_kb 检索结果或显式 plan_config 提供。', 'Site-specific thresholds and OAR limits should come from clinical_kb retrieval results or explicit plan_config.')}")
        lines.append(f"- [AAPM TG-43U1](https://pubmed.ncbi.nlm.nih.gov/15070264/) — {L('近距离放疗源剂量学报告框架', 'Brachytherapy source dosimetry reporting framework')}")
        lines.append(f"- [ICRU Report 89](https://www.icru.org/report/icru-report-89-prescribing-recording-and-reporting-photon-beam-therapy-2nd-edition) — {L('处方、记录和报告原则', 'Prescribing, recording, and reporting principles')}")
        lines.append("")

        return "\n".join(lines)

    def _synthesize_with_llm(self, raw_results: str, steps: List, lang: str, user_message: str = "", query_type: str = "knowledge") -> str:
        """Synthesize tool results. Delegates to ToolResultPipeline."""
        formatted = []
        for s in steps:
            if s.get("type") == "tool" and s.get("status") == "done":
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

    # Tumor type → CTV tool mapping
    _TUMOR_TYPE_MAP = {
        # English names — pancreatic uses nnUNet (more accurate)
        "pancreatic_tumor": "nnunet_pancreatic",
        "pancreatic": "nnunet_pancreatic",
        "pancreas": "nnunet_pancreatic",
        "liver_tumor": "voco_liver",
        "liver": "voco_liver",
        "kidney_tumor": "voco_kidney",
        "kidney": "voco_kidney",
        "colon_tumor": "voco_colon",
        "colon": "voco_colon",
        "lung_tumor": "voco_lung",
        "lung": "voco_lung",
        "brain_tumor": "voco_brats21",
        "brain": "voco_brats21",
        "pulmonary_embolism": "voco_fumpe",
        "covid": "voco_covid",
        "aorta": "voco_aorta",
        "pdac": "nnunet_pancreatic",
        "hepatocellular": "voco_liver",
        "hcc": "voco_liver",
        "renal": "voco_kidney",
        "colorectal": "voco_colon",
        "nsclc": "voco_lung",
        "prostate": "prostate_tumor",
        "prostate_tumor": "prostate_tumor",
        "head_neck": "head_neck_tumor",
        "head and neck": "head_neck_tumor",
        "胰腺癌": "nnunet_pancreatic",
        "胰腺肿瘤": "nnunet_pancreatic",
        "胰腺": "nnunet_pancreatic",
        "肝癌": "voco_liver",
        "肝肿瘤": "voco_liver",
        "肝脏": "voco_liver",
        "肾癌": "voco_kidney",
        "肾肿瘤": "voco_kidney",
        "肾脏": "voco_kidney",
        "结肠癌": "voco_colon",
        "结直肠癌": "voco_colon",
        "结肠": "voco_colon",
        "肺癌": "voco_lung",
        "肺肿瘤": "voco_lung",
        "肺部": "voco_lung",
        "前列腺": "prostate_tumor",
        "前列腺癌": "prostate_tumor",
        "头颈部": "head_neck_tumor",
        "头颈癌": "head_neck_tumor",
        "脑肿瘤": "voco_brats21",
        "脑癌": "voco_brats21",
        "肺栓塞": "voco_fumpe",
        "新冠": "voco_covid",
        "主动脉": "voco_aorta",
        "胰腺癌患者": "nnunet_pancreatic",   # pancreatic cancer patient
        "肝癌患者": "voco_liver",            # liver cancer patient
        "肾癌患者": "voco_kidney",           # kidney cancer patient
        "肺癌患者": "voco_lung",             # lung cancer patient
        "结肠癌患者": "voco_colon",          # colon cancer patient
        "脑肿瘤患者": "voco_brats21",        # brain tumor patient
    }

    def _map_tumor_type(self, tumor_type: Optional[str]) -> Optional[str]:
        """Map user-provided tumor type to VoCo tool name."""
        if tumor_type is None:
            return None
        # Already a valid VoCo tool name
        if tumor_type.startswith("voco_") or tumor_type in {"nnunet_pancreatic", "prostate_tumor", "head_neck_tumor"}:
            return tumor_type
        # Look up in mapping
        mapped = self._TUMOR_TYPE_MAP.get(tumor_type.lower())
        if mapped:
            return mapped
        # Partial match for Chinese
        for key, val in self._TUMOR_TYPE_MAP.items():
            if key in tumor_type or tumor_type in key:
                return val
        # Keep explicit unknown sites unsupported. The unified CTV tool will
        # fail closed with the model catalog instead of silently running a
        # pancreatic model on another disease site.
        logger.warning(f"Unknown tumor_type '{tumor_type}', leaving it unsupported")
        return tumor_type

    def _detect_tumor_type_from_message(self, message: str) -> Optional[str]:
        """Detect tumor type from user message for CTV segmentation routing."""
        msg = message.lower()
        # Check each keyword in the mapping
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
        valid = []
        for tc in tool_calls:
            tn = tc.get("tool", "")
            p = tc.get("params", {})
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
            valid.append(tc)
        return valid
