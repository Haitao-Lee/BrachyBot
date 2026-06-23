"""
Clinical Knowledge Base Tool
=============================
Stores and queries clinical guidelines, dose constraints, organ tolerances,
and treatment protocols for evidence-based planning.
"""

import os
import json
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)

KB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(KB_DIR, exist_ok=True)

# Initialize default knowledge base if empty
# Per-site dose standards sourced from:
#   prostate: ABS/AUA/ASTRO 2012 (PMID 22265436)
#   cervical: EMBRACE II (PMID 42211610)
#   breast: GEC-ESTRO APBI 2016
#   lung: ABS lung consensus
#   pancreatic: Chinese I-125 guideline 2023
#   liver: ABS liver consensus
#   head_neck: ABS H&N consensus
_DEFAULT_KB = {
    "dose_standards": {
        "prostate": {
            "ldr": {
                "target": {"v100_min": 0.95, "d90_min_pct": 1.00, "v150_max": 0.50, "v200_max": 0.35},
                "oar": {"urethra": {"dmax_pct": 1.20}, "rectum": {"d2cc_gy_eqd2": 75}, "bladder": {"d2cc_gy_eqd2": 90}},
                "source": "ABS/AUA/ASTRO 2012 (PMID 22265436)"
            }
        },
        "cervical": {
            "hdr": {
                "target": {"v100_min": 0.90, "d90_gy_eqd2_min": 85},
                "oar": {"bladder": {"d2cc_gy_eqd2": 90}, "rectum": {"d2cc_gy_eqd2": 75}, "sigmoid": {"d2cc_gy_eqd2": 70}},
                "source": "EMBRACE II (PMID 42211610)"
            }
        },
        "default": {
            "target": {"v100_min": 0.90, "d90_min_pct": 1.00, "v200_max": 0.35},
            "source": "GEC-ESTRO / ABS composite defaults"
        }
    },
    "organ_tolerances": {
        "spinal_cord": {"max_dose_gy": 45, "tolerance": "Very sensitive"},
        "brainstem": {"max_dose_gy": 54, "tolerance": "Sensitive"},
        "heart": {"max_dose_gy": 60, "tolerance": "Sensitive"},
        "esophagus": {"max_dose_gy": 60, "tolerance": "Moderate"},
        "small_bowel": {"max_dose_gy": 50, "tolerance": "Sensitive"},
        "rectum": {"max_dose_gy": 75, "tolerance": "Moderate"},
        "bladder": {"max_dose_gy": 90, "tolerance": "Moderate"},
        "kidney": {"mean_dose_gy": 18, "tolerance": "Sensitive"},
        "liver": {"mean_dose_gy": 30, "tolerance": "Moderate"},
        "lung": {"mean_dose_gy": 20, "tolerance": "Sensitive"},
    },
    "treatment_protocols": {
        "prostate_low_risk": {
            "description": "Low-risk prostate cancer monotherapy",
            "prescription_dose_gy": 145,
            "seeds_per_cc": 0.7,
            "technique": "Peripheral loading with modified uniform distribution",
        },
        "prostate_intermediate_risk": {
            "description": "Intermediate-risk prostate cancer with boost",
            "prescription_dose_gy": 110,
            "boost_dose_gy": 90,
            "technique": "Combined EBRT + HDR boost",
        },
        "cervical_hdr": {
            "description": "Cervical cancer HDR brachytherapy",
            "prescription_dose_gy": 28,
            "fractions": 4,
            "technique": "Intracavitary with tandem/ovoids",
        },
    },
    "plan_quality_benchmarks": {
        "excellent": {"min_score": 90, "v100_min": 0.95, "v200_max": 0.25},
        "good": {"min_score": 80, "v100_min": 0.90, "v200_max": 0.35},
        "acceptable": {"min_score": 70, "v100_min": 0.85, "v200_max": 0.40},
        "marginal": {"min_score": 60, "v100_min": 0.80, "v200_max": 0.45},
    },
}


def _ensure_default_kb():
    """Initialize default knowledge base if not present."""
    kb_file = os.path.join(KB_DIR, "knowledge_base.json")
    if not os.path.exists(kb_file):
        with open(kb_file, 'w', encoding='utf-8') as f:
            json.dump(_DEFAULT_KB, f, indent=2, ensure_ascii=False)
        logger.info("Initialized default clinical knowledge base")


_ensure_default_kb()


class ClinicalKnowledgeBaseTool(BaseTool):
    """Query clinical guidelines, dose constraints, and treatment protocols."""

    name = "clinical_kb"
    description = """Clinical knowledge base for evidence-based treatment planning.
Capabilities:
- standards: Get per-site dose standards (V100, D90, V200, OAR constraints) with source citations
- constraints: Get dose constraints for a specific organ/cancer type
- tolerance: Check organ tolerance limits
- protocol: Get treatment protocol recommendations
- benchmark: Check plan quality against benchmarks
- search: Search the knowledge base by keyword
- guidelines: Search authoritative guidelines (AAPM, ABS, GEC-ESTRO, Chinese) by keyword — returns only matching sections with source citations
- add: Add new knowledge entry"""

    input_schema = {
        "action": {
            "type": "string",
            "description": "Action: standards, constraints, tolerance, protocol, benchmark, search, guidelines, add",
            "enum": ["standards", "constraints", "tolerance", "protocol", "benchmark", "search", "guidelines", "add"]
        },
        "organ": {"type": "string", "description": "Organ or cancer type name (e.g. 'prostate', 'cervical', 'lung')"},
        "keyword": {"type": "string", "description": "Search keyword"},
        "data": {"type": "object", "description": "Data to add (for add action)"},
    }
    output_schema = {
        "success": {"type": "boolean"},
        "data": {"type": "object"},
    }

    def _load_kb(self) -> Dict:
        """Load the knowledge base."""
        kb_file = os.path.join(KB_DIR, "knowledge_base.json")
        try:
            with open(kb_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return _DEFAULT_KB

    def _save_kb(self, kb: Dict):
        """Save the knowledge base."""
        kb_file = os.path.join(KB_DIR, "knowledge_base.json")
        with open(kb_file, 'w', encoding='utf-8') as f:
            json.dump(kb, f, indent=2, ensure_ascii=False)

    def _get_constraints(self, organ: str) -> ToolResult:
        """Get dose constraints for an organ or cancer type."""
        kb = self._load_kb()
        organ_lower = organ.lower().replace(" ", "_")

        # Check dose_constraints
        constraints = kb.get("dose_constraints", {})
        result = constraints.get(organ_lower)

        if result:
            return ToolResult(
                success=True,
                data={"organ": organ, "constraints": result},
                message=f"Dose constraints for {organ}"
            )

        # Partial match
        matches = {k: v for k, v in constraints.items() if organ_lower in k or k in organ_lower}
        if matches:
            return ToolResult(
                success=True,
                data={"organ": organ, "matches": matches},
                message=f"Found {len(matches)} matching constraint set(s)"
            )

        return ToolResult(
            success=True,
            data={"organ": organ, "constraints": None, "available": list(constraints.keys())},
            message=f"No specific constraints for '{organ}'. Available: {', '.join(constraints.keys())}"
        )

    def _get_tolerance(self, organ: str) -> ToolResult:
        """Get organ tolerance information."""
        kb = self._load_kb()
        organ_lower = organ.lower().replace(" ", "_")

        tolerances = kb.get("organ_tolerances", {})
        result = tolerances.get(organ_lower)

        if result:
            return ToolResult(
                success=True,
                data={"organ": organ, "tolerance": result},
                message=f"Tolerance for {organ}: max {result.get('max_dose_gy', 'N/A')} Gy"
            )

        # Partial match
        matches = {k: v for k, v in tolerances.items() if organ_lower in k or k in organ_lower}
        if matches:
            return ToolResult(success=True, data={"organ": organ, "matches": matches}, message=f"Found {len(matches)} match(es)")

        return ToolResult(
            success=True,
            data={"organ": organ, "tolerance": None, "available": list(tolerances.keys())},
            message=f"No tolerance data for '{organ}'"
        )

    def _get_protocol(self, protocol_name: str) -> ToolResult:
        """Get treatment protocol."""
        kb = self._load_kb()
        protocols = kb.get("treatment_protocols", {})

        if protocol_name:
            name_lower = protocol_name.lower().replace(" ", "_")
            result = protocols.get(name_lower)
            if result:
                return ToolResult(success=True, data={"protocol": protocol_name, "details": result}, message=f"Protocol: {protocol_name}")
            # Partial match
            matches = {k: v for k, v in protocols.items() if name_lower in k or k in name_lower}
            if matches:
                return ToolResult(success=True, data={"matches": matches}, message=f"Found {len(matches)} protocol(s)")

        return ToolResult(
            success=True,
            data={"protocols": {k: v.get("description", "") for k, v in protocols.items()}},
            message=f"Available protocols: {', '.join(protocols.keys())}"
        )

    def _check_benchmark(self, metrics: Dict) -> ToolResult:
        """Check plan quality against benchmarks."""
        kb = self._load_kb()
        benchmarks = kb.get("plan_quality_benchmarks", {})

        score = metrics.get("plan_score", 0)
        v100 = metrics.get("v100", 0)
        v200 = metrics.get("v200", 0)

        rating = "poor"
        for level, criteria in sorted(benchmarks.items(), key=lambda x: x[1].get("min_score", 0), reverse=True):
            if (score >= criteria["min_score"] and
                v100 >= criteria["v100_min"] and
                v200 <= criteria["v200_max"]):
                rating = level
                break

        suggestions = []
        if v100 < 0.90:
            suggestions.append("V100 below 90%: increase seed count or adjust positions")
        if v200 > 0.35:
            suggestions.append("V200 above 35%: reduce seed density in high-dose regions")
        if score < 70:
            suggestions.append("Plan score below acceptable threshold: consider full re-optimization")

        return ToolResult(
            success=True,
            data={"rating": rating, "score": score, "v100": v100, "v200": v200, "suggestions": suggestions},
            message=f"Plan rated as '{rating}' (score: {score})"
        )

    def _search_kb(self, keyword: str) -> ToolResult:
        """Search the knowledge base by keyword."""
        kb = self._load_kb()
        keyword_lower = keyword.lower()
        results = []

        def search_dict(d, path=""):
            for k, v in d.items():
                current_path = f"{path}.{k}" if path else k
                if keyword_lower in str(k).lower() or keyword_lower in str(v).lower():
                    results.append({"path": current_path, "key": k, "value": v})
                if isinstance(v, dict):
                    search_dict(v, current_path)

        search_dict(kb)
        return ToolResult(
            success=True,
            data={"keyword": keyword, "results": results[:20], "total": len(results)},
            message=f"Found {len(results)} match(es) for '{keyword}'"
        )

    def _add_entry(self, data: Dict) -> ToolResult:
        """Add a new entry to the knowledge base."""
        if not data or "category" not in data or "key" not in data:
            return ToolResult(success=False, error="Need category and key", message="Provide 'category', 'key', and 'value'")

        kb = self._load_kb()
        category = data["category"]
        key = data["key"]
        value = data.get("value", {})

        if category not in kb:
            kb[category] = {}
        kb[category][key] = value
        self._save_kb(kb)

        return ToolResult(
            success=True,
            data={"category": category, "key": key},
            message=f"Added '{key}' to '{category}'"
        )

    def _search_guidelines(self, keyword: str) -> ToolResult:
        """Search the guidelines markdown file by keyword, returning only matching sections."""
        guidelines_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "clinical_kb", "guidelines_brachytherapy.md")
        if not os.path.exists(guidelines_path):
            return ToolResult(success=False, message="Guidelines file not found")

        with open(guidelines_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Split into sections by ## headers (skip preamble before first section)
        # The actual format uses ## <a id="..."> not ## §
        import re
        parts = re.split(r'\n(?=## )', content)
        sections = [p for p in parts if p.strip().startswith('## ')]
        keyword_lower = keyword.lower()

        matched = []
        for section in sections:
            if keyword_lower in section.lower():
                # Trim to reasonable length
                trimmed = section[:2000] if len(section) > 2000 else section
                matched.append(trimmed)

        if not matched:
            return ToolResult(success=True, message=f"No guideline sections match '{keyword}'", data={"keyword": keyword, "results": []})

        return ToolResult(
            success=True,
            data={"keyword": keyword, "results": matched[:3], "total": len(matched)},
            message=f"Found {len(matched)} guideline section(s) for '{keyword}'"
        )

    def _get_standards(self, organ: str) -> ToolResult:
        """Get per-site dose standards (V100, D90, V200, OAR) with source citations."""
        kb = self._load_kb()
        standards = kb.get("dose_standards", {})
        organ_lower = (organ or "").lower().replace(" ", "_").replace("-", "_")

        # Try exact match first
        result = standards.get(organ_lower)
        if not result:
            # Try partial match
            for key in standards:
                if key in organ_lower or organ_lower in key:
                    result = standards[key]
                    organ_lower = key
                    break
        if not result:
            # Try mapping common names
            _map = {"nnunet_pancreatic": "pancreatic", "pancreas": "pancreatic",
                    "voco_liver": "liver", "voco_lung": "lung", "voco_kidney": "liver",
                    "voco_colon": "liver", "voco_brats21": "head_neck"}
            for pattern, site in _map.items():
                if pattern in organ_lower:
                    result = standards.get(site)
                    organ_lower = site
                    break

        if not result:
            result = standards.get("default", {})
            organ_lower = "default"

        return ToolResult(
            success=True,
            data={"site": organ_lower, "standards": result},
            message=f"Dose standards for {organ_lower}"
        )

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "")
        if not action:
            return ToolResult(success=False, error="No action", message="Specify: standards, constraints, tolerance, protocol, benchmark, search, guidelines, add")

        if action == "standards":
            return self._get_standards(kwargs.get("organ", ""))
        elif action == "constraints":
            return self._get_constraints(kwargs.get("organ", ""))
        elif action == "tolerance":
            return self._get_tolerance(kwargs.get("organ", ""))
        elif action == "protocol":
            return self._get_protocol(kwargs.get("organ", ""))
        elif action == "benchmark":
            return self._check_benchmark(kwargs.get("data", {}))
        elif action == "search":
            return self._search_kb(kwargs.get("keyword", ""))
        elif action == "guidelines":
            return self._search_guidelines(kwargs.get("keyword", ""))
        elif action == "add":
            return self._add_entry(kwargs.get("data", {}))
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}", message="Valid: standards, constraints, tolerance, protocol, benchmark, search, guidelines, add")
