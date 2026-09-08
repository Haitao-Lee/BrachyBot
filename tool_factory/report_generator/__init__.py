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
            "description": "Action: generate/full_report, summary, dvh_report, export_json, export_markdown. 'generate' produces the complete treatment report.",
            "enum": ["generate", "full_report", "summary", "dvh_report", "export_json", "export_markdown"]
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
        """Generate a full report from one canonical, source-aware fact set.

        This tool is also used outside the browser. Keep its semantics aligned
        with the Report panel: known planning values are resolved through
        explicit aliases, quality rows cite actual references, and unavailable
        clinical thresholds are explained rather than hidden behind placeholders.
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        metrics = plan.get("metrics") if isinstance(plan.get("metrics"), dict) else {}
        rationale = plan.get("prescription_rationale") or {}
        if not isinstance(rationale, dict):
            rationale = {}
        organ = plan.get("organ") or plan.get("tumor_type") or "Unknown"
        cancer_type = plan.get("cancer_type") or plan.get("tumor_type") or "Unknown"

        def number(value):
            try:
                value = float(value)
                return value if value == value and abs(value) != float("inf") else None
            except (TypeError, ValueError):
                return None

        def fmt_float(value, digits=2, default="Not recorded"):
            value = number(value)
            return f"{value:.{digits}f}" if value is not None else default

        def first(*values):
            for value in values:
                if value not in (None, ""):
                    return value
            return None

        rx_raw = first(
            rationale.get("prescription_gy"),
            plan.get("prescription_dose_gy"),
            plan.get("prescription_gy"),
            metrics.get("prescription_gy"),
            metrics.get("prescribed_dose_gy"),
            metrics.get("prescribed_dose"),
        )
        rx = number(rx_raw)
        if rx is not None and rx <= 5:
            rx *= 120.0
        rx = rx if rx is not None and rx > 0 else None

        total_seeds = first(plan.get("seed_count"), plan.get("total_seeds"), metrics.get("total_seeds"))
        needle_count = first(plan.get("needle_count"), plan.get("num_trajectories"), metrics.get("num_trajectories"))
        total_activity = first(
            plan.get("total_activity_mbq"), plan.get("totalActivityMBq"),
            metrics.get("total_activity_mbq"), metrics.get("totalActivityMBq"),
        )
        activity_text = f"{fmt_float(total_activity, 3)} MBq" if number(total_activity) is not None else "Not recorded in plan configuration"
        prescription_text = f"{fmt_float(rx, 1)} Gy" if rx is not None else "Not recorded"

        raw_sources = rationale.get("source_records") or rationale.get("sources") or []
        references = []
        seen_urls = set()
        for source in raw_sources:
            if isinstance(source, dict):
                url = str(source.get("url") or "").strip()
                title = str(source.get("title") or "").strip()
                publisher = str(source.get("publisher") or "").strip()
                year = source.get("year") or ""
            else:
                url = str(source or "").strip()
                title = ""
                publisher = ""
                year = ""
            if not url.startswith(("http://", "https://")) or url in seen_urls:
                continue
            seen_urls.add(url)
            references.append({
                "title": title or url,
                "publisher": publisher,
                "year": year,
                "url": url,
            })

        def citation_text():
            if not references:
                return ""
            return " " + ", ".join(f"[{i + 1}]({ref['url']})" for i, ref in enumerate(references))

        source_suffix = citation_text()
        criteria = rationale.get("target_criteria") if isinstance(rationale.get("target_criteria"), dict) else {}
        has_sources = bool(references)

        def quality_rule(key, value, operator, unit="fraction"):
            value_number = number(value)
            raw = criteria.get(key)
            threshold = number(raw)
            if value_number is None:
                return "Not observed", "No observed value"
            if threshold is None:
                if has_sources:
                    return f"No configured criterion{source_suffix}", "Informational — no criterion configured"
                return "No site-specific criterion configured", "Not assessed — no site-specific source"
            if unit == "rx":
                if rx is None:
                    return f"{threshold:.0%} Rx{source_suffix}", "Not assessed — prescription unavailable"
                absolute = threshold * rx
                passed = value_number >= absolute if operator == ">=" else value_number <= absolute
                return (
                    f"{operator}{threshold:.0%} Rx ({absolute:.1f} Gy){source_suffix}",
                    "Pass" if passed else "Review required",
                )
            passed = value_number >= threshold if operator == ">=" else value_number <= threshold
            return (
                f"{operator}{threshold:.0%}{source_suffix}",
                "Pass" if passed else "Review required",
            )

        def observed_metric(key, value, unit, digits=2):
            value_number = number(value)
            return f"{value_number:.{digits}f} {unit}" if value_number is not None else "Not observed"

        v100 = metrics.get("v100")
        v150 = metrics.get("v150")
        v200 = metrics.get("v200")
        d90 = metrics.get("d90")
        d95 = metrics.get("d95")
        # Generic plans historically stored Vx as fractions. Preserve that
        # contract in this Markdown tool while accepting percent inputs.
        def fraction(value):
            value = number(value)
            if value is None:
                return None
            return value / 100.0 if value > 1.5 else value

        lines = [
            "# Brachytherapy Treatment Plan Report",
            f"**Generated:** {now}",
            "**System:** BrachyBot AI Planning System",
            "",
            "---",
            "",
            "## Patient Information",
            f"- **Diagnosis:** {cancer_type} ({organ})",
            f"- **Prescription dose:** {prescription_text}",
        ]
        if patient:
            for key, value in patient.items():
                lines.append(f"- **{key.replace('_', ' ').title()}:** {value}")

        lines += [
            "",
            "## CT Image",
            f"- **Dimensions:** {plan.get('ct_dimensions') or 'Not recorded'}",
            f"- **Spacing:** {plan.get('ct_spacing') or 'Not recorded'}",
            f"- **Voxel size:** {plan.get('voxel_size') or 'Not recorded'}",
            "",
            "## Segmentation",
            f"- **CTV volume:** {fmt_float(first(plan.get('ctv_volume_cc'), plan.get('ctv_volume_cm3')), 2, 'Not recorded')} cc",
            f"- **OAR organs segmented:** {first(plan.get('oar_count'), metrics.get('oar_count')) or 'Not recorded'}",
        ]

        lines += [
            "",
            "## Seed Plan",
            f"- **Total seeds:** {total_seeds if total_seeds not in (None, '') else 'Not recorded'}",
            f"- **Needle/trajectory count:** {needle_count if needle_count not in (None, '') else 'Not recorded'}",
            f"- **Total source activity:** {activity_text}",
            f"- **Technique:** {plan.get('technique') or 'Radioactive seed implantation (¹²⁵I)'}",
        ]

        lines += [
            "",
            "## Target & Prescription",
            f"- **Prescribed dose:** {prescription_text}",
            f"- **Prescription source:** {rationale.get('prescription_source') or 'Planning record; clinician verification required'}",
            f"- **Treatment site:** {rationale.get('site') or organ or 'Unknown'}",
            f"- **Rationale:** {rationale.get('rationale') or 'No case-specific rationale was recorded.'}",
            "",
            "## Plan Quality Assessment",
            "| Metric | Observed value | Reference | Status |",
            "|---|---:|---|---|",
        ]

        quality_rows = [
            ("V100 (CTV)", fraction(v100), "%", "v100_min", ">=", "fraction"),
            ("D90", d90, "Gy", "d90_min_pct", ">=", "rx"),
            ("D95", d95, "Gy", None, ">=", "none"),
            ("V150", fraction(v150), "%", "v150_max", "<=", "fraction"),
            ("V200", fraction(v200), "%", "v200_max", "<=", "fraction"),
        ]
        for label, value, unit, key, operator, rule_unit in quality_rows:
            if key is None:
                ref = f"No configured criterion{source_suffix}" if has_sources else "No site-specific criterion configured"
                status = "Informational — no criterion configured" if has_sources else "Not assessed — no site-specific source"
            else:
                ref, status = quality_rule(key, value, operator, rule_unit)
            displayed = "Not observed" if value is None else (
                f"{value * 100:.1f} %" if unit == "%" else f"{number(value):.2f} {unit}"
            )
            lines.append(f"| {label} | {displayed} | {ref} | {status} |")

        for label, key in (("CI", "ci"), ("HI", "hi"), ("GI", "gi")):
            value = number(metrics.get(key))
            ref = f"No configured criterion{source_suffix}" if has_sources else "No site-specific criterion configured"
            status = "Informational — no criterion configured" if has_sources else "Not assessed — no site-specific source"
            lines.append(f"| {label} | {fmt_float(value)} | {ref} | {status} |")
        score = number(metrics.get("plan_score"))
        lines.append(
            f"| Plan score | {fmt_float(score, 1, 'Not recorded')}/100 | "
            "Internal QA ranking (not a clinical criterion) | Advisory only — not clinical approval |"
        )

        if rationale:
            lines += [
                "",
                "## Prescription Dose Rationale",
                f"- **Current prescription:** {prescription_text}",
                f"- **Clinical guidance site:** {rationale.get('site') or 'unknown'}",
                f"- **Target criteria:** {rationale.get('target_criteria') or 'No site-specific target threshold configured'}",
                f"- **Clinical boundary:** {rationale.get('clinical_boundary') or 'A clinician must confirm the prescription and applicability of all criteria.'}",
            ]

        oar_violations = metrics.get("oar_violations", [])
        if oar_violations:
            lines += ["", "## OAR Violations"]
            for item in oar_violations:
                lines.append(
                    f"- **{item.get('organ', 'Unknown')}:** {item.get('dose', 'Not recorded')} Gy "
                    f"(limit: {item.get('limit', 'Not recorded')} Gy)"
                )

        lines += [
            "",
            "## DVH Summary",
            f"- **CTV D90:** {observed_metric('d90', d90, 'Gy')}",
            f"- **CTV D100:** {observed_metric('d100', metrics.get('d100'), 'Gy')}",
            f"- **OAR maximum dose:** {metrics.get('oar_max_dose') or 'Not recorded'}",
        ]
        if references:
            lines += ["", "## References"]
            for index, reference in enumerate(references, 1):
                meta = ""
                if reference["publisher"]:
                    meta += f" *{reference['publisher']}*"
                if reference["year"]:
                    meta += f", {reference['year']}"
                lines.append(f"{index}. [{reference['title']}]({reference['url']}){meta}.")
        else:
            lines += ["", "## References", "No verified clinical references were attached to this case."]
        lines += [
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

        # The LLM commonly asks to "generate/regenerate the report". Treat those
        # as the full-report action so a natural-language request never fails
        # with "Invalid value for action".
        if str(action or "").strip().lower() in ("generate", "regenerate", "full_report"):
            action = "full_report"

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
