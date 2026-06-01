"""
Case Memory Tool
================
Stores and retrieves past treatment plans for learning and recommendation.
Enables the agent to learn from experience and recommend similar cases.
"""

import os
import json
import time
import logging
import hashlib
from typing import Dict, Any, Optional, List
from pathlib import Path

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)

MEMORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases")
os.makedirs(MEMORY_DIR, exist_ok=True)


class CaseMemoryTool(BaseTool):
    """Store, retrieve, and search past treatment plans for experience-based learning."""

    name = "case_memory"
    description = """Store and retrieve treatment plan cases for learning.
Capabilities:
- save: Save a completed treatment plan as a case
- retrieve: Get a specific case by ID
- search: Search cases by similarity (organ, cancer type, metrics)
- list: List all stored cases
- statistics: Get aggregate statistics across all cases
- recommend: Get recommendations based on similar past cases"""

    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Action: save, retrieve, search, list, statistics, recommend",
                "enum": ["save", "retrieve", "search", "list", "statistics", "recommend"]
            },
            "case_id": {"type": "string", "description": "Case ID (for retrieve)"},
            "case_data": {"type": "object", "description": "Case data to save (for save)"},
            "query": {"type": "object", "description": "Search query with filters (for search/recommend)"},
        },
        "required": ["action"],
    }
    output_schema = {
        "success": {"type": "boolean"},
        "data": {"type": "object"},
    }

    def _generate_case_id(self, case_data: Dict) -> str:
        """Generate a unique case ID."""
        key_parts = [
            case_data.get("organ", ""),
            case_data.get("cancer_type", ""),
            str(case_data.get("ctv_volume_cc", "")),
            str(time.time()),
        ]
        return hashlib.md5("|".join(key_parts).encode()).hexdigest()[:12]

    def _save_case(self, case_data: Dict) -> ToolResult:
        """Save a treatment plan case."""
        if not case_data:
            return ToolResult(success=False, error="No case data", message="Please provide case_data")

        case_id = case_data.get("case_id") or self._generate_case_id(case_data)
        case_data["case_id"] = case_id
        case_data["saved_at"] = time.time()

        case_file = os.path.join(MEMORY_DIR, f"{case_id}.json")
        try:
            with open(case_file, 'w', encoding='utf-8') as f:
                json.dump(case_data, f, indent=2, ensure_ascii=False)
            return ToolResult(
                success=True,
                data={"case_id": case_id, "file": case_file},
                message=f"Case '{case_id}' saved successfully"
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e), message=f"Failed to save case: {e}")

    def _retrieve_case(self, case_id: str) -> ToolResult:
        """Retrieve a specific case."""
        case_file = os.path.join(MEMORY_DIR, f"{case_id}.json")
        if not os.path.exists(case_file):
            return ToolResult(success=False, error=f"Case '{case_id}' not found", message=f"Case not found: {case_id}")
        try:
            with open(case_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return ToolResult(success=True, data=data, message=f"Retrieved case '{case_id}'")
        except Exception as e:
            return ToolResult(success=False, error=str(e), message=f"Failed to retrieve case: {e}")

    def _search_cases(self, query: Dict) -> ToolResult:
        """Search cases by filters."""
        results = []
        organ_filter = query.get("organ", "").lower()
        cancer_filter = query.get("cancer_type", "").lower()
        min_v100 = query.get("min_v100", 0)
        min_score = query.get("min_plan_score", 0)

        for case_file in Path(MEMORY_DIR).glob("*.json"):
            try:
                with open(case_file, 'r', encoding='utf-8') as f:
                    case = json.load(f)

                match = True
                if organ_filter and organ_filter not in case.get("organ", "").lower():
                    match = False
                if cancer_filter and cancer_filter not in case.get("cancer_type", "").lower():
                    match = False
                if min_v100 and case.get("metrics", {}).get("v100", 0) < min_v100:
                    match = False
                if min_score and case.get("metrics", {}).get("plan_score", 0) < min_score:
                    match = False

                if match:
                    results.append({
                        "case_id": case.get("case_id"),
                        "organ": case.get("organ"),
                        "cancer_type": case.get("cancer_type"),
                        "metrics": case.get("metrics", {}),
                        "saved_at": case.get("saved_at"),
                    })
            except Exception:
                continue

        results.sort(key=lambda x: x.get("saved_at", 0), reverse=True)
        return ToolResult(
            success=True,
            data={"cases": results[:20], "total": len(results)},
            message=f"Found {len(results)} matching case(s)"
        )

    def _list_cases(self) -> ToolResult:
        """List all stored cases."""
        cases = []
        for case_file in Path(MEMORY_DIR).glob("*.json"):
            try:
                with open(case_file, 'r', encoding='utf-8') as f:
                    case = json.load(f)
                cases.append({
                    "case_id": case.get("case_id"),
                    "organ": case.get("organ"),
                    "cancer_type": case.get("cancer_type"),
                    "plan_score": case.get("metrics", {}).get("plan_score"),
                    "saved_at": case.get("saved_at"),
                })
            except Exception:
                continue
        cases.sort(key=lambda x: x.get("saved_at", 0), reverse=True)
        return ToolResult(success=True, data={"cases": cases, "count": len(cases)}, message=f"Found {len(cases)} case(s)")

    def _get_statistics(self) -> ToolResult:
        """Get aggregate statistics across all cases."""
        cases = []
        for case_file in Path(MEMORY_DIR).glob("*.json"):
            try:
                with open(case_file, 'r', encoding='utf-8') as f:
                    cases.append(json.load(f))
            except Exception:
                continue

        if not cases:
            return ToolResult(success=True, data={"count": 0, "message": "No cases stored yet"}, message="No cases found")

        scores = [c.get("metrics", {}).get("plan_score", 0) for c in cases if c.get("metrics", {}).get("plan_score")]
        v100s = [c.get("metrics", {}).get("v100", 0) for c in cases if c.get("metrics", {}).get("v100")]

        stats = {
            "total_cases": len(cases),
            "organs": list(set(c.get("organ", "unknown") for c in cases)),
            "avg_plan_score": round(sum(scores) / len(scores), 2) if scores else 0,
            "avg_v100": round(sum(v100s) / len(v100s), 3) if v100s else 0,
            "best_score": max(scores) if scores else 0,
            "worst_score": min(scores) if scores else 0,
        }
        return ToolResult(success=True, data=stats, message=f"Statistics from {len(cases)} cases")

    def _recommend(self, query: Dict) -> ToolResult:
        """Get recommendations based on similar past cases."""
        organ = query.get("organ", "").lower()
        cancer_type = query.get("cancer_type", "").lower()

        similar = []
        for case_file in Path(MEMORY_DIR).glob("*.json"):
            try:
                with open(case_file, 'r', encoding='utf-8') as f:
                    case = json.load(f)

                similarity = 0
                if organ and organ in case.get("organ", "").lower():
                    similarity += 2
                if cancer_type and cancer_type in case.get("cancer_type", "").lower():
                    similarity += 2

                score = case.get("metrics", {}).get("plan_score", 0)
                if score >= 80:
                    similarity += 1

                if similarity >= 2:
                    similar.append({
                        "case_id": case.get("case_id"),
                        "organ": case.get("organ"),
                        "cancer_type": case.get("cancer_type"),
                        "metrics": case.get("metrics", {}),
                        "seed_count": case.get("seed_count"),
                        "similarity_score": similarity,
                        "lessons_learned": case.get("lessons_learned", ""),
                        "optimization_notes": case.get("optimization_notes", ""),
                    })
            except Exception:
                continue

        similar.sort(key=lambda x: (x["similarity_score"], x.get("metrics", {}).get("plan_score", 0)), reverse=True)

        return ToolResult(
            success=True,
            data={"recommendations": similar[:5], "total_similar": len(similar)},
            message=f"Found {len(similar)} similar case(s) for recommendation"
        )

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "")
        if not action:
            return ToolResult(success=False, error="No action", message="Specify: save, retrieve, search, list, statistics, recommend")

        if action == "save":
            return self._save_case(kwargs.get("case_data", {}))
        elif action == "retrieve":
            return self._retrieve_case(kwargs.get("case_id", ""))
        elif action == "search":
            return self._search_cases(kwargs.get("query", {}))
        elif action == "list":
            return self._list_cases()
        elif action == "statistics":
            return self._get_statistics()
        elif action == "recommend":
            return self._recommend(kwargs.get("query", {}))
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}", message="Valid: save, retrieve, search, list, statistics, recommend")
