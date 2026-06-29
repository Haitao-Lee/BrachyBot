"""
Report Auto-Fill Tool
====================
BrachyBot tool that asks the backend to build a *partial* report patch
from current planning data (DICOM, NIfTI, planning metrics) and returns
it to the agent. The frontend applies the patch to the editable Report
panel, respecting user-edited fields.

Returns a ToolResult whose `metadata.marker = "report-update"` so the
frontend chat handler can recognize it and apply it to the form.

Endpoints called:
    POST /api/report/auto-fill   — server-side patch builder
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult
from typing import Dict


def _server_url():
    """Resolve the backend URL. Default to localhost dev server."""
    return os.environ.get("BRACHYBOT_SERVER_URL", "http://127.0.0.1:8080")


class ReportAutoFillTool(BaseTool):
    """Build a partial Report-panel patch from current planning data.

    Inputs:
        scope: which section(s) to fill — 'all' | 'patient' | 'metrics'
               | 'oar' | 'interpretation' | 'safety' (default: 'all')
        language: 'zh' | 'en' (default: 'zh')
        include_llm_narrative: bool — if true, also calls an LLM to
               enrich the interpretation narrative. (Reserved for future
               use; current server returns a templated narrative.)

    Output:
        ToolResult with:
          - data: the patch dict
          - metadata: { provenance, language, marker: "report-update" }
          - display: human-readable summary in zh/en
    """

    @property
    def name(self) -> str:
        return "report_auto_fill"

    @property
    def description(self) -> str:
        return (
            "Auto-fill the Report panel from the currently loaded CT, "
            "DICOM header, and planning results. Returns a partial form "
            "patch that the UI applies (skipping fields the user has "
            "manually edited). Use when the user asks to 'fill the "
            "report', '生成报告', 'fill the interpretation', or wants "
            "patient / metrics / OAR / narrative auto-populated. Pair "
            "with /report en or /report zh in chat to set language."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["all", "patient", "metrics", "oar",
                             "interpretation", "safety"],
                    "default": "all",
                    "description": "Which section(s) to fill.",
                },
                "language": {
                    "type": "string",
                    "enum": ["zh", "en"],
                    "default": "zh",
                },
                "include_llm_narrative": {
                    "type": "boolean",
                    "default": False,
                    "description": "Reserved — enrich narrative via LLM.",
                },
            },
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "patch": {"type": "object", "description": "Dotted-key form patch."},
                "provenance": {"type": "object", "description": "Which keys came from which source."},
                "language": {"type": "string"},
            },
        }

    def _retrieve(self, agent, key, default=None):
        memory = getattr(agent, "memory", None)
        if memory is None:
            return default
        try:
            value = memory.retrieve(key)
        except TypeError:
            value = memory.retrieve(key, default)
        except Exception:
            return default
        return default if value is None else value

    def _coerce_prescription_gy(self, value):
        try:
            rx = float(value)
        except Exception:
            return None
        if not (rx > 0):
            return None
        # Some planning metrics store the normalized dose level (1.0),
        # while the report form expects Gy.
        return rx * 120.0 if rx <= 5.0 else rx

    def _append_patch(self, patch, provenance, source, key, value, ndigits=None):
        if value is None:
            return
        try:
            if ndigits is not None:
                value = round(float(value), ndigits)
        except Exception:
            return
        patch[key] = value
        provenance.setdefault(source, []).append(key)

    def _build_interpretation(self, language, dose, total_seeds, num_trajectories):
        v100 = dose.get("v100")
        d90 = dose.get("d90")
        score = dose.get("plan_score")
        try:
            v100_pct = float(v100) * 100 if v100 is not None and float(v100) <= 1.5 else float(v100)
        except Exception:
            v100_pct = None

        if language == "zh":
            lines = ["本报告由当前分割、轨迹规划和剂量计算结果自动填充。"]
            if total_seeds or num_trajectories:
                lines.append(f"计划包含 {int(total_seeds or 0)} 颗粒子、{int(num_trajectories or 0)} 条穿刺轨迹。")
            metric_bits = []
            if v100_pct is not None:
                metric_bits.append(f"CTV V100={v100_pct:.1f}%")
            if d90 is not None:
                metric_bits.append(f"D90={float(d90):.2f} Gy")
            if score is not None:
                metric_bits.append(f"plan score={float(score):.1f}/100")
            if metric_bits:
                lines.append("关键剂量指标：" + "，".join(metric_bits) + "。")
            safety = (
                "请由放射肿瘤科医师复核靶区、危及器官、穿刺路径和剂量分布；"
                "正式治疗前应进行独立剂量校验，并结合影像、病理和临床禁忌证综合判断。"
            )
            return "\n".join(lines), safety

        lines = ["This report was auto-filled from the current segmentation, trajectory planning, and dose calculation results."]
        if total_seeds or num_trajectories:
            lines.append(f"The plan contains {int(total_seeds or 0)} seeds across {int(num_trajectories or 0)} trajectories.")
        metric_bits = []
        if v100_pct is not None:
            metric_bits.append(f"CTV V100={v100_pct:.1f}%")
        if d90 is not None:
            metric_bits.append(f"D90={float(d90):.2f} Gy")
        if score is not None:
            metric_bits.append(f"plan score={float(score):.1f}/100")
        if metric_bits:
            lines.append("Key dose metrics: " + ", ".join(metric_bits) + ".")
        safety = (
            "A radiation oncologist must review the target, OARs, needle paths, and dose distribution. "
            "Perform independent dose verification before clinical use."
        )
        return "\n".join(lines), safety

    def _build_patch_from_agent(self, agent, scope, language):
        patch = {}
        provenance = {"nifti": [], "dicom": [], "planning": [], "derived": []}

        if scope in ("all", "patient"):
            tags = self._retrieve(agent, "ct_dicom_tags", {}) or {}
            tag_map = {
                "patient_name": "patient.name",
                "patient_id": "patient.id",
                "patient_sex": "patient.sex",
                "study_date": "study.date",
                "modality": "study.modality",
            }
            for tag, key in tag_map.items():
                if tags.get(tag):
                    patch[key] = str(tags[tag])
                    provenance["dicom"].append(key)
            ct_path = self._retrieve(agent, "ct_path")
            if ct_path and not patch.get("case.patientId"):
                base = os.path.basename(str(ct_path))
                for ext in (".nii.gz", ".nii", ".mha", ".nrrd"):
                    if base.lower().endswith(ext):
                        base = base[:-len(ext)]
                        break
                patch["case.patientId"] = base
                provenance["nifti"].append("case.patientId")

        if scope in ("all", "patient", "metrics"):
            spacing = self._retrieve(agent, "ct_spacing")
            shape = self._retrieve(agent, "ct_shape")
            if spacing and shape:
                try:
                    patch["imaging.sliceCount"] = int(shape[0])
                    patch["imaging.pixelSpacingMm"] = float(spacing[0])
                    patch["imaging.sliceThicknessMm"] = float(spacing[2])
                    provenance["nifti"].extend([
                        "imaging.sliceCount",
                        "imaging.pixelSpacingMm",
                        "imaging.sliceThicknessMm",
                    ])
                except Exception:
                    pass

        dose = self._retrieve(agent, "dose_metrics", {}) or self._retrieve(agent, "metrics", {}) or {}
        if isinstance(dose, dict) and isinstance(dose.get("metrics"), dict):
            dose = dose.get("metrics") or {}

        total_seeds = self._retrieve(agent, "total_seeds")
        num_trajectories = self._retrieve(agent, "num_trajectories")

        if scope in ("all", "metrics", "oar"):
            percent_keys = {
                "v100": "metrics.v100",
                "v150": "metrics.v150",
                "v200": "metrics.v200",
            }
            for source_key, patch_key in percent_keys.items():
                value = dose.get(source_key)
                if value is None:
                    continue
                try:
                    value = float(value)
                    if value <= 1.5:
                        value *= 100.0
                    self._append_patch(patch, provenance, "planning", patch_key, value, 2)
                except Exception:
                    pass

            for source_key, patch_key, ndigits in (
                ("d90", "metrics.d90", 2),
                ("d95", "metrics.d95", 2),
                ("ci", "metrics.ci", 3),
                ("hi", "metrics.hi", 3),
                ("gi", "metrics.gi", 3),
                ("plan_score", "metrics.score", 1),
            ):
                self._append_patch(patch, provenance, "planning", patch_key, dose.get(source_key), ndigits)

            rx_gy = self._coerce_prescription_gy(dose.get("prescribed_dose"))
            self._append_patch(patch, provenance, "planning", "planning.prescriptionGy", rx_gy, 1)
            if total_seeds:
                self._append_patch(patch, provenance, "planning", "planning.totalSeeds", int(total_seeds))
            if num_trajectories:
                self._append_patch(patch, provenance, "planning", "planning.trajectoryCount", int(num_trajectories))

            ctv_volume_mm3 = self._retrieve(agent, "ctv_volume_mm3")
            if ctv_volume_mm3 is None:
                ctv_voxels = self._retrieve(agent, "ctv_voxels")
                spacing = self._retrieve(agent, "ct_spacing")
                if ctv_voxels and spacing:
                    try:
                        ctv_volume_mm3 = float(ctv_voxels) * float(spacing[0]) * float(spacing[1]) * float(spacing[2])
                    except Exception:
                        ctv_volume_mm3 = None
            self._append_patch(patch, provenance, "planning", "case.ctvVolumeMm3", ctv_volume_mm3, 1)

        if scope in ("all", "oar"):
            oar = self._retrieve(agent, "oar_metrics", {}) or dose.get("oar_metrics") or {}
            if isinstance(oar, dict) and oar:
                oar_list = []
                for name, values in oar.items():
                    if not isinstance(values, dict):
                        continue
                    row = {"organ": str(name)}
                    has_value = False
                    for metric_key in ("d2cc", "d1cc", "d0_1cc", "dmax"):
                        value = values.get(metric_key)
                        if value is not None:
                            try:
                                row[metric_key] = round(float(value), 1)
                                has_value = True
                            except Exception:
                                pass
                    if values.get("v100") is not None:
                        try:
                            v100 = float(values.get("v100"))
                            row["v100"] = round(v100 * 100 if v100 <= 1.5 else v100, 1)
                            has_value = True
                        except Exception:
                            pass
                    if has_value:
                        oar_list.append(row)
                oar_list.sort(key=lambda row: (row.get("d2cc") or row.get("dmax") or 0), reverse=True)
                patch["oarDose"] = oar_list[:12]
                provenance["planning"].append("oarDose")

        if scope in ("all", "interpretation", "safety"):
            interp, safety = self._build_interpretation(language, dose, total_seeds, num_trajectories)
            if scope in ("all", "interpretation"):
                patch["interpretation"] = interp
                provenance["derived"].append("interpretation")
            if scope in ("all", "safety"):
                patch["safety"] = safety
                provenance["derived"].append("safety")

        return patch, provenance

    def _execute(self, scope="all", language="zh", include_llm_narrative=False, **kwargs) -> ToolResult:
        url = _server_url().rstrip("/")
        endpoint = f"{url}/api/report/auto-fill"
        payload = {
            "scope": scope,
            "language": language,
            "sources": ["nifti", "dicom", "planning"],
        }
        # We do an in-process call if possible (same Flask app) to avoid
        # HTTP overhead, but fall back to requests if the app isn't
        # importable here.
        patch = None
        provenance = None
        err = None
        agent = kwargs.get("_agent") or kwargs.get("agent")
        if agent is not None:
            try:
                patch, provenance = self._build_patch_from_agent(agent, scope, language)
            except Exception as e:
                err = f"agent-memory: {e}"
        try:
            if patch is None:
                patch, provenance = self._in_process_call(payload)
        except Exception as e:
            err = f"{err}; in-process: {e}" if err else f"in-process: {e}"
        if patch is None:
            try:
                import requests  # type: ignore
                r = requests.post(endpoint, json=payload, timeout=30)
                data = r.json()
                if not data.get("success"):
                    raise RuntimeError(data.get("error", "unknown"))
                patch = data.get("patch", {})
                provenance = data.get("provenance", {})
            except Exception as e:
                return ToolResult(
                    success=False,
                    error=f"Auto-fill failed ({err}; http: {e})",
                    message="Could not build report patch.",
                    display=(
                        "⚠️ Report auto-fill failed. The server endpoint "
                        "`/api/report/auto-fill` is unreachable. Make sure "
                        "the Flask server is running and the CT/planning "
                        "pipeline has completed."
                    ),
                )

        # If include_llm_narrative requested, we could call a separate
        # LLM helper here. For now, the server already produces a
        # templated narrative.
        n_filled = len(patch)
        lang_label = "中文" if language == "zh" else "English"
        summary_lines = [f"📝 Report auto-fill ({scope}, {lang_label}) — {n_filled} field(s):"]
        # Group by section
        sections = {"patient": [], "study": [], "case": [], "planning": [],
                    "metrics": [], "imaging": [], "oarDose": [], "narrative": []}
        for k in patch.keys():
            head = k.split(".", 1)[0]
            sections.setdefault(head, []).append(k)
        for sec, keys in sections.items():
            if keys:
                summary_lines.append(f"  - {sec}: {len(keys)} field(s)")
        if "interpretation" in patch:
            interp = str(patch["interpretation"])
            preview = interp.split("\n", 1)[0][:80]
            summary_lines.append("")
            summary_lines.append(f"  narrative: {preview}…")

        display_md = "\n".join(summary_lines)
        # Also embed a JSON marker block so the frontend can detect it
        marker_block = (
            "```json\n"
            + json.dumps({
                "marker": "report-update",
                "data": patch,
                "provenance": provenance,
                "language": language,
            }, indent=2, ensure_ascii=False)
            + "\n```"
        )
        display_md += "\n\n" + marker_block

        return ToolResult(
            success=True,
            data=patch,
            message=f"Report patch ready ({n_filled} field(s), {language}).",
            display=display_md,
            metadata={
                "provenance": provenance,
                "language": language,
                "marker": "report-update",
                "scope": scope,
            },
        )

    def _in_process_call(self, payload):
        """Try to invoke the Flask endpoint handler in-process (no HTTP).

        Falls back to raising; the outer _execute will fall back to HTTP.
        """
        # We import the server module lazily to avoid circular imports
        # at module load time.
        try:
            from web import server as _server_mod
        except Exception as e:
            raise RuntimeError(f"web.server not importable: {e}")
        handler = getattr(_server_mod, "api_report_auto_fill", None) or \
                  getattr(_server_mod, "_api_report_auto_fill", None)
        if handler is None:
            raise RuntimeError("api_report_auto_fill handler not found")
        # Stub a Flask request context
        from flask import Flask, request  # type: ignore
        app = Flask(__name__)
        with app.test_request_context(json=payload):
            resp = handler()
            # resp is a flask Response or tuple
            try:
                body = resp.get_json() if hasattr(resp, "get_json") else resp[0].get_json()
            except Exception:
                body = resp[0] if isinstance(resp, tuple) else resp
        if not body.get("success"):
            raise RuntimeError(body.get("error", "handler returned error"))
        return body.get("patch", {}), body.get("provenance", {})


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--scope", default="all")
    p.add_argument("--language", default="zh")
    args = p.parse_args()
    tool = ReportAutoFillTool()
    res = tool._execute(scope=args.scope, language=args.language)
    print(res.message)
    print("---")
    print(res.display[:2000])


if __name__ == "__main__":
    main()
