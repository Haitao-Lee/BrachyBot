"""
Performance Tracker Tool
========================
Tracks system performance, user feedback, and learning metrics.
Enables the self-evolving agent to measure and improve over time.
"""

import os
import json
import time
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path
from datetime import datetime

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)

TRACKER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(TRACKER_DIR, exist_ok=True)

METRICS_FILE = os.path.join(TRACKER_DIR, "performance_metrics.json")


def _load_metrics() -> Dict:
    """Load performance metrics."""
    if os.path.exists(METRICS_FILE):
        try:
            with open(METRICS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("Failed to load performance metrics from %s: %s", METRICS_FILE, exc)
    return {
        "sessions": [],
        "plan_scores": [],
        "tool_usage": {},
        "user_feedback": [],
        "error_log": [],
        "evolution_events": [],
    }


def _save_metrics(data: Dict):
    """Save performance metrics."""
    with open(METRICS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


class PerformanceTrackerTool(BaseTool):
    """Track system performance and learning metrics for self-evolution."""

    name = "performance_tracker"
    description = """Track and analyze system performance for self-evolution.
Capabilities:
- log_session: Log a completed planning session
- log_feedback: Log user feedback on a plan
- log_error: Log an error for learning
- log_evolution: Log a self-evolution event (skill creation, lesson learned)
- dashboard: Get performance dashboard with trends
- trends: Analyze performance trends over time
- get_suggestions: Get improvement suggestions based on past performance"""

    input_schema = {
        "action": {
            "type": "string",
            "description": "Action: log_session, log_feedback, log_error, log_evolution, dashboard, trends, get_suggestions",
            "enum": ["log_session", "log_feedback", "log_error", "log_evolution", "dashboard", "trends", "get_suggestions"]
        },
        "data": {"type": "object", "description": "Data to log or query parameters"},
    }
    output_schema = {
        "success": {"type": "boolean"},
        "data": {"type": "object"},
    }

    def _log_session(self, data: Dict) -> ToolResult:
        """Log a completed planning session."""
        metrics = _load_metrics()
        session = {
            "timestamp": time.time(),
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "organ": data.get("organ", "unknown"),
            "cancer_type": data.get("cancer_type", "unknown"),
            "plan_score": data.get("plan_score", 0),
            "v100": data.get("v100", 0),
            "v200": data.get("v200", 0),
            "seed_count": data.get("seed_count", 0),
            "tools_used": data.get("tools_used", []),
            "duration_seconds": data.get("duration_seconds", 0),
            "iterations": data.get("iterations", 0),
        }
        metrics["sessions"].append(session)
        metrics["plan_scores"].append(session["plan_score"])

        # Track tool usage
        for tool in session["tools_used"]:
            metrics["tool_usage"][tool] = metrics["tool_usage"].get(tool, 0) + 1

        _save_metrics(metrics)
        return ToolResult(
            success=True,
            data={"session_count": len(metrics["sessions"]), "avg_score": sum(metrics["plan_scores"]) / len(metrics["plan_scores"]) if metrics["plan_scores"] else 0},
            message=f"Session logged. Total sessions: {len(metrics['sessions'])}"
        )

    def _log_feedback(self, data: Dict) -> ToolResult:
        """Log user feedback."""
        metrics = _load_metrics()
        feedback = {
            "timestamp": time.time(),
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "session_id": data.get("session_id"),
            "rating": data.get("rating", 0),  # 1-5
            "comment": data.get("comment", ""),
            "category": data.get("category", "general"),  # plan_quality, usability, speed
        }
        metrics["user_feedback"].append(feedback)
        _save_metrics(metrics)
        return ToolResult(success=True, data={"feedback_count": len(metrics["user_feedback"])}, message="Feedback logged")

    def _log_error(self, data: Dict) -> ToolResult:
        """Log an error for learning."""
        metrics = _load_metrics()
        error = {
            "timestamp": time.time(),
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "error_type": data.get("error_type", "unknown"),
            "message": data.get("message", ""),
            "tool": data.get("tool", ""),
            "context": data.get("context", ""),
            "resolution": data.get("resolution", ""),
        }
        metrics["error_log"].append(error)
        _save_metrics(metrics)
        return ToolResult(success=True, data={"error_count": len(metrics["error_log"])}, message="Error logged")

    def _log_evolution(self, data: Dict) -> ToolResult:
        """Log a self-evolution event."""
        metrics = _load_metrics()
        event = {
            "timestamp": time.time(),
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "type": data.get("type", "skill_created"),  # skill_created, lesson_learned, sop_updated
            "description": data.get("description", ""),
            "trigger": data.get("trigger", ""),
            "impact": data.get("impact", ""),
        }
        metrics["evolution_events"].append(event)
        _save_metrics(metrics)
        return ToolResult(success=True, data={"evolution_count": len(metrics["evolution_events"])}, message="Evolution event logged")

    def _get_dashboard(self) -> ToolResult:
        """Get performance dashboard."""
        metrics = _load_metrics()
        sessions = metrics.get("sessions", [])
        scores = metrics.get("plan_scores", [])
        feedback = metrics.get("user_feedback", [])
        errors = metrics.get("error_log", [])
        evolution = metrics.get("evolution_events", [])

        avg_score = sum(scores) / len(scores) if scores else 0
        avg_rating = sum(f.get("rating", 0) for f in feedback) / len(feedback) if feedback else 0

        # Recent trend (last 10 vs previous 10)
        recent = scores[-10:] if len(scores) >= 10 else scores
        previous = scores[-20:-10] if len(scores) >= 20 else []
        recent_avg = sum(recent) / len(recent) if recent else 0
        previous_avg = sum(previous) / len(previous) if previous else 0
        trend = "improving" if recent_avg > previous_avg + 2 else "declining" if recent_avg < previous_avg - 2 else "stable"

        dashboard = {
            "summary": {
                "total_sessions": len(sessions),
                "avg_plan_score": round(avg_score, 1),
                "avg_user_rating": round(avg_rating, 1),
                "total_errors": len(errors),
                "evolution_events": len(evolution),
                "trend": trend,
            },
            "recent_scores": scores[-5:],
            "top_tools": sorted(metrics.get("tool_usage", {}).items(), key=lambda x: x[1], reverse=True)[:5],
            "recent_feedback": feedback[-3:],
            "recent_errors": errors[-3:],
        }

        return ToolResult(success=True, data=dashboard, message=f"Dashboard: {len(sessions)} sessions, avg score {avg_score:.1f}")

    def _get_trends(self) -> ToolResult:
        """Analyze performance trends."""
        metrics = _load_metrics()
        sessions = metrics.get("sessions", [])

        if len(sessions) < 3:
            return ToolResult(success=True, data={"message": "Not enough data for trends (need 3+ sessions)"}, message="Insufficient data")

        scores = [s.get("plan_score", 0) for s in sessions]
        v100s = [s.get("v100", 0) for s in sessions]

        # Simple moving average
        window = min(5, len(scores))
        recent_avg = sum(scores[-window:]) / window
        overall_avg = sum(scores) / len(scores)

        # Organ-specific trends
        organ_scores = {}
        for s in sessions:
            organ = s.get("organ", "unknown")
            if organ not in organ_scores:
                organ_scores[organ] = []
            organ_scores[organ].append(s.get("plan_score", 0))

        organ_trends = {}
        for organ, slist in organ_scores.items():
            avg = sum(slist) / len(slist)
            organ_trends[organ] = {"count": len(slist), "avg_score": round(avg, 1)}

        trends = {
            "overall_avg": round(overall_avg, 1),
            "recent_avg": round(recent_avg, 1),
            "improvement": round(recent_avg - overall_avg, 1),
            "organ_trends": organ_trends,
            "total_sessions": len(sessions),
        }

        return ToolResult(success=True, data=trends, message=f"Trends: avg {overall_avg:.1f}, recent {recent_avg:.1f}")

    def _get_suggestions(self) -> ToolResult:
        """Get improvement suggestions based on past performance."""
        metrics = _load_metrics()
        sessions = metrics.get("sessions", [])
        errors = metrics.get("error_log", [])
        feedback = metrics.get("user_feedback", [])

        suggestions = []

        # Analyze scores
        if sessions:
            scores = [s.get("plan_score", 0) for s in sessions]
            avg = sum(scores) / len(scores)
            if avg < 75:
                suggestions.append({
                    "priority": "HIGH",
                    "area": "plan_quality",
                    "suggestion": f"Average plan score is {avg:.0f}/100. Focus on improving seed distribution algorithms.",
                })

        # Analyze errors
        error_types = {}
        for e in errors:
            et = e.get("error_type", "unknown")
            error_types[et] = error_types.get(et, 0) + 1
        for et, count in sorted(error_types.items(), key=lambda x: x[1], reverse=True)[:3]:
            suggestions.append({
                "priority": "MEDIUM" if count > 3 else "LOW",
                "area": "reliability",
                "suggestion": f"Recurring error type '{et}' ({count} times). Consider adding error handling.",
            })

        # Analyze feedback
        if feedback:
            low_ratings = [f for f in feedback if f.get("rating", 0) <= 2]
            if len(low_ratings) > len(feedback) * 0.3:
                suggestions.append({
                    "priority": "HIGH",
                    "area": "user_satisfaction",
                    "suggestion": f"{len(low_ratings)}/{len(feedback)} feedback ratings are low. Review user pain points.",
                })

        if not suggestions:
            suggestions.append({"priority": "LOW", "area": "general", "suggestion": "System performing well. Continue monitoring."})

        return ToolResult(success=True, data={"suggestions": suggestions}, message=f"{len(suggestions)} suggestion(s)")

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "")
        data = kwargs.get("data", {})

        if not action:
            return ToolResult(success=False, error="No action", message="Specify: log_session, log_feedback, log_error, log_evolution, dashboard, trends, get_suggestions")

        if action == "log_session":
            return self._log_session(data)
        elif action == "log_feedback":
            return self._log_feedback(data)
        elif action == "log_error":
            return self._log_error(data)
        elif action == "log_evolution":
            return self._log_evolution(data)
        elif action == "dashboard":
            return self._get_dashboard()
        elif action == "trends":
            return self._get_trends()
        elif action == "get_suggestions":
            return self._get_suggestions()
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}", message="Valid: log_session, log_feedback, log_error, log_evolution, dashboard, trends, get_suggestions")
