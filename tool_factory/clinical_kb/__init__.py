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
_DEFAULT_KB = {
    "dose_constraints": {
        "prostate": {
            "ctv_v100": {"target": ">=95%", "description": "CTV should receive 100% of prescription dose"},
            "ctv_d90": {"target": ">=100%", "description": "90% of CTV should get full prescription"},
            "rectum_d0.1cc": {"limit": "<=150%", "description": "Rectum max dose per 0.1cc"},
            "rectum_d1cc": {"limit": "<=120%", "description": "Rectum max dose per 1cc"},
            "bladder_d0.1cc": {"limit": "<=150%", "description": "Bladder max dose per 0.1cc"},
            "urethra_d0.1cc": {"limit": "<=120%", "description": "Urethra max dose per 0.1cc"},
            "v200": {"limit": "<=35%", "description": "Volume receiving 200% dose"},
        },
        "cervical": {
            "ctv_v100": {"target": ">=90%", "description": "CTV coverage"},
            "bladder_d2cc": {"limit": "<=90Gy", "description": "Bladder D2cc EQD2"},
            "rectum_d2cc": {"limit": "<=75Gy", "description": "Rectum D2cc EQD2"},
            "sigmoid_d2cc": {"limit": "<=75Gy", "description": "Sigmoid D2cc EQD2"},
        },
        "lung": {
            "ctv_v100": {"target": ">=95%", "description": "CTV coverage"},
            "spinal_cord_d0.1cc": {"limit": "<=45Gy", "description": "Spinal cord max dose"},
            "esophagus_d0.1cc": {"limit": "<=60Gy", "description": "Esophagus max dose"},
            "heart_d0.1cc": {"limit": "<=60Gy", "description": "Heart max dose"},
        },
        "liver": {
            "ctv_v100": {"target": ">=90%", "description": "CTV coverage"},
            "normal_liver_mean": {"limit": "<=30Gy", "description": "Normal liver mean dose"},
            "spinal_cord_d0.1cc": {"limit": "<=45Gy", "description": "Spinal cord max dose"},
        },
        "head_neck": {
            "ctv_v100": {"target": ">=95%", "description": "CTV coverage"},
            "spinal_cord_d0.1cc": {"limit": "<=45Gy", "description": "Spinal cord max dose"},
            "brainstem_d0.1cc": {"limit": "<=54Gy", "description": "Brainstem max dose"},
            "parotid_mean": {"limit": "<=26Gy", "description": "Parotid mean dose"},
        },
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
- constraints: Get dose constraints for a specific organ/cancer type
- tolerance: Check organ tolerance limits
- protocol: Get treatment protocol recommendations
- benchmark: Check plan quality against benchmarks
- search: Search the knowledge base by keyword
- add: Add new knowledge entry"""

    input_schema = {
        "action": {
            "type": "string",
            "description": "Action: constraints, tolerance, protocol, benchmark, search, add",
            "enum": ["constraints", "tolerance", "protocol", "benchmark", "search", "add"]
        },
        "organ": {"type": "string", "description": "Organ or cancer type name"},
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

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "")
        if not action:
            return ToolResult(success=False, error="No action", message="Specify: constraints, tolerance, protocol, benchmark, search, add")

        if action == "constraints":
            return self._get_constraints(kwargs.get("organ", ""))
        elif action == "tolerance":
            return self._get_tolerance(kwargs.get("organ", ""))
        elif action == "protocol":
            return self._get_protocol(kwargs.get("organ", ""))
        elif action == "benchmark":
            return self._check_benchmark(kwargs.get("data", {}))
        elif action == "search":
            return self._search_kb(kwargs.get("keyword", ""))
        elif action == "add":
            return self._add_entry(kwargs.get("data", {}))
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}", message="Valid: constraints, tolerance, protocol, benchmark, search, add")
