"""
Report Generator Tool
=====================
Generates clinical treatment reports in various formats.
"""

import os
import json
import time
import logging
from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output", "reports")
os.makedirs(OUTPUT_DIR, exist_ok=True)


class ReportGeneratorTool(BaseTool):
    """Generate clinical treatment reports."""

    name = "report_generator"
    description = """Generate clinical treatment plan reports.
Capabilities:
- full_report: Complete treatment report with all sections
- summary: Brief summary of the plan
- dvh_report: DVH analysis report
- export_json: Export plan data as structured JSON
- export_markdown: Export plan as Markdown document"""

    input_schema = {
        "action": {
            "type": "string",
            "description": "Action: full_report, summary, dvh_report, export_json, export_markdown",
            "enum": ["full_report", "summary", "dvh_report", "export_json", "export_markdown"]
        },
        "plan_data": {"type": "object", "description": "Complete plan data"},
        "patient_info": {"type": "object", "description": "Patient info (optional)"},
        "output_path": {"type": "string", "description": "Output file path (optional)"},
    }
    output_schema = {
        "success": {"type": "boolean"},
        "data": {"type": "object"},
    }

    def _generate_full_report(self, plan: Dict, patient: Dict = None) -> str:
        """Generate a full clinical report."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        metrics = plan.get("metrics", {})
        organ = plan.get("organ", "Unknown")
        cancer_type = plan.get("cancer_type", "Unknown")

        def fmt_float(value, digits=2, default="N/A"):
            try:
                return f"{float(value):.{digits}f}"
            except (TypeError, ValueError):
                return default

        lines = [
            f"# Brachytherapy Treatment Plan Report",
            f"**Generated:** {now}",
            f"**System:** BrachyBot AI Planning System",
            "",
            "---",
            "",
            "## Patient Information",
            f"- **Diagnosis:** {cancer_type} ({organ})",
            f"- **Prescription Dose:** {plan.get('prescription_dose_gy', 'N/A')} Gy",
        ]

        if patient:
            for k, v in patient.items():
                lines.append(f"- **{k.replace('_', ' ').title()}:** {v}")

        lines += [
            "",
            "## CT Image",
            f"- **Dimensions:** {plan.get('ct_dimensions', 'N/A')}",
            f"- **Spacing:** {plan.get('ct_spacing', 'N/A')}",
            f"- **Voxel Size:** {plan.get('voxel_size', 'N/A')}",
            "",
            "## Segmentation",
            f"- **CTV Volume:** {fmt_float(plan.get('ctv_volume_cc'))} cc",
            f"- **OAR Organs Segmented:** {plan.get('oar_count', 'N/A')}",
        ]

        tumor_assessment = plan.get("tumor_imaging_assessment") or plan.get("tumor_assessment")
        if isinstance(tumor_assessment, dict) and tumor_assessment.get("available"):
            dims = tumor_assessment.get("bbox_dimensions_cm_xyz", [0, 0, 0])
            center = tumor_assessment.get("centroid_world_cm_xyz", [0, 0, 0])
            lines += [
                "",
                "## Tumor Imaging Assessment",
                f"- **Volume:** {fmt_float(tumor_assessment.get('volume_cm3'))} cm³",
                f"- **Maximum Diameter:** {fmt_float(tumor_assessment.get('max_diameter_cm'))} cm",
                f"- **Bounding Dimensions (X/Y/Z):** {fmt_float(dims[0])} / {fmt_float(dims[1])} / {fmt_float(dims[2])} cm",
                f"- **Centroid World Coordinates:** ({fmt_float(center[0])}, {fmt_float(center[1])}, {fmt_float(center[2])}) cm",
                f"- **Shape Regularity:** {tumor_assessment.get('edge_regularity', 'N/A')}",
                f"- **Boundary:** {tumor_assessment.get('interpretation_boundary', 'Geometry-only planning descriptor')}",
            ]

        lines += [
            "",
            "## Seed Plan",
            f"- **Total Seeds:** {plan.get('seed_count', 'N/A')}",
            f"- **Needle Count:** {plan.get('needle_count', 'N/A')}",
            f"- **Technique:** {plan.get('technique', 'Standard')}",
            "",
            "## Dose Metrics",
            f"| Metric | Value | Target | Status |",
            f"|--------|-------|--------|--------|",
        ]

        v100 = metrics.get("v100", 0)
        v150 = metrics.get("v150", 0)
        v200 = metrics.get("v200", 0)
        d90 = metrics.get("d90", 0)
        rx_gy = plan.get("prescription_dose_gy", 120)  # Default I-125 pancreatic
        if not isinstance(rx_gy, (int, float)) or rx_gy <= 0:
            rx_gy = 120

        def status(val, target, op=">="):
            if not val: return "N/A"
            if op == ">=": return "✅" if val >= target else "❌"
            if op == "<=": return "✅" if val <= target else "❌"
            return ""

        lines.append(f"| V100 | {v100:.1%} | ≥90% | {status(v100, 0.90)} |")
        lines.append(f"| V150 | {v150:.1%} | ≤60% | {status(v150, 0.60, '<=')} |")
        lines.append(f"| V200 | {v200:.1%} | ≤35% | {status(v200, 0.35, '<=')} |")
        lines.append(f"| D90 | {d90:.1f} Gy | ≥{rx_gy:.0f} Gy | {status(d90, rx_gy)} |")
        lines.append(f"| Plan Score | {metrics.get('plan_score', 0):.1f}/100 | ≥80 | {status(metrics.get('plan_score', 0), 80)} |")

        prescription_rationale = plan.get("prescription_rationale")
        if isinstance(prescription_rationale, dict):
            sources = prescription_rationale.get("sources", []) or []
            lines += [
                "",
                "## Prescription Dose Rationale",
                f"- **Current Prescription:** {fmt_float(prescription_rationale.get('prescription_gy', rx_gy), 1)} Gy",
                f"- **Rationale:** {prescription_rationale.get('rationale', 'No case-specific rationale provided')}",
                f"- **clinical_kb Site:** {prescription_rationale.get('site', 'unknown')}",
            ]
            if prescription_rationale.get("target_criteria"):
                lines.append(f"- **Target Criteria:** {prescription_rationale.get('target_criteria')}")
            for i, url in enumerate(sources[:5], start=1):
                lines.append(f"- **Source {i}:** {url}")
            lines.append(f"- **Boundary:** {prescription_rationale.get('clinical_boundary', 'Clinician must confirm prescription appropriateness')}")

        oar_violations = metrics.get("oar_violations", [])
        if oar_violations:
            lines += [
                "",
                "## ⚠️ OAR Violations",
            ]
            for ov in oar_violations:
                lines.append(f"- **{ov.get('organ', 'Unknown')}:** {ov.get('dose', 0):.1f} Gy (limit: {ov.get('limit', 0):.1f} Gy)")

        lines += [
            "",
            "## DVH Summary",
            f"- **CTV D90:** {d90:.1f} Gy",
            f"- **CTV D100:** {metrics.get('d100', 0):.1f} Gy",
            f"- **OAR Max Dose:** {metrics.get('oar_max_dose', 'N/A')}",
            "",
            "---",
            "",
            f"*Report generated by BrachyBot AI Planning System at {now}*",
        ]

        return "\n".join(lines)

    def _generate_summary(self, plan: Dict) -> str:
        """Generate a brief summary."""
        metrics = plan.get("metrics", {})
        organ = plan.get("organ", "Unknown")
        score = metrics.get("plan_score", 0)
        v100 = metrics.get("v100", 0)

        rating = "Excellent" if score >= 90 else "Good" if score >= 80 else "Acceptable" if score >= 70 else "Marginal"

        return (
            f"**{organ.title()} Treatment Plan Summary**\n\n"
            f"- Rating: {rating} ({score:.0f}/100)\n"
            f"- Coverage (V100): {v100:.1%}\n"
            f"- Seeds: {plan.get('seed_count', 'N/A')}\n"
            f"- OAR Violations: {len(metrics.get('oar_violations', []))}\n"
        )

    def _generate_dvh_report(self, plan: Dict) -> str:
        """Generate DVH analysis report."""
        metrics = plan.get("metrics", {})
        lines = [
            "# DVH Analysis Report",
            "",
            "## Target Coverage",
            f"- D98: {metrics.get('d98', 'N/A')}%",
            f"- D90: {metrics.get('d90', 'N/A')}%",
            f"- D50: {metrics.get('d50', 'N/A')}%",
            f"- D2: {metrics.get('d2', 'N/A')}%",
            "",
            "## Conformity",
            f"- CI: {metrics.get('conformity_index', 'N/A')}",
            f"- HI: {metrics.get('homogeneity_index', 'N/A')}",
            f"- EI: {metrics.get('external_index', 'N/A')}",
        ]
        return "\n".join(lines)

    def _export_json(self, plan: Dict, output_path: str = None) -> ToolResult:
        """Export plan as JSON."""
        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(OUTPUT_DIR, f"plan_{timestamp}.json")

        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(plan, f, indent=2, ensure_ascii=False)
            return ToolResult(success=True, data={"path": output_path, "format": "json"}, message=f"Exported to {output_path}")
        except Exception as e:
            return ToolResult(success=False, error=str(e), message=f"Export failed: {e}")

    def _export_markdown(self, plan: Dict, patient: Dict = None, output_path: str = None) -> ToolResult:
        """Export plan as Markdown."""
        content = self._generate_full_report(plan, patient)
        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(OUTPUT_DIR, f"plan_{timestamp}.md")

        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return ToolResult(success=True, data={"path": output_path, "format": "markdown"}, message=f"Exported to {output_path}")
        except Exception as e:
            return ToolResult(success=False, error=str(e), message=f"Export failed: {e}")

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "")
        plan = kwargs.get("plan_data", {})
        patient = kwargs.get("patient_info")
        output_path = kwargs.get("output_path")

        if not action:
            # Return error with helpful guidance about available actions
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            guidance = (
                "## BrachyBot Report Generator\n\n"
                "Please specify an action parameter. Available report types:\n\n"
                "### Available Actions\n"
                "- **full_report**: Complete treatment plan report with patient information, "
                "CT image details, segmentation metrics, seed plan, dose metrics (V100, V150, V200, D90), "
                "DVH summary, and OAR violations\n"
                "- **summary**: Brief treatment plan summary with rating, coverage, seed count, "
                "and OAR violation count\n"
                "- **dvh_report**: Dose-Volume Histogram analysis with target coverage "
                "(D98, D90, D50, D2), conformity index (CI), homogeneity index (HI), and external index (EI)\n"
                "- **export_json**: Export plan data as structured JSON file for record systems\n"
                "- **export_markdown**: Export plan as formatted Markdown document\n\n"
                "### How to Generate\n"
                "To generate a report, I need the treatment plan data. Please complete the planning workflow first:\n"
                "1. Load CT images\n"
                "2. Segment CTV and OARs\n"
                "3. Plan seed placement\n"
                "4. Calculate dose distribution\n\n"
                f"Generated by BrachyBot AI Planning System at {now}"
            )
            return ToolResult(
                success=False,
                error="No action specified",
                data={"report": guidance, "available_actions": [
                    "full_report", "summary", "dvh_report", "export_json", "export_markdown"
                ]},
                message="Specify action: full_report, summary, dvh_report, export_json, export_markdown"
            )

        if action == "full_report":
            report = self._generate_full_report(plan, patient)
            result = self._export_markdown(plan, patient, output_path)
            result.data["report_text"] = report
            return result
        elif action == "summary":
            return ToolResult(success=True, data={"summary": self._generate_summary(plan)}, message="Summary generated")
        elif action == "dvh_report":
            return ToolResult(success=True, data={"report": self._generate_dvh_report(plan)}, message="DVH report generated")
        elif action == "export_json":
            return self._export_json(plan, output_path)
        elif action == "export_markdown":
            return self._export_markdown(plan, patient, output_path)
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}", message="Valid: full_report, summary, dvh_report, export_json, export_markdown")
