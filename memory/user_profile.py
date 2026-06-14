"""
User Preference Modeling (Dialectic User Profiling)
=====================================================
Builds and maintains a dynamic model of the user's preferences, working style,
and clinical tendencies. The profile evolves through dialectic interaction:
the agent observes, hypothesizes, and validates preferences over time.

Inspired by: Hermes Agent's Honcho dialectic user modeling.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class PreferenceDimension:
    """A single dimension of user preference."""
    name: str
    category: str
    value: str
    confidence: float = 0.5
    evidence_count: int = 0
    last_updated: str = ""
    source: str = "observation"
    contradictory_evidence: int = 0


@dataclass
class InteractionPattern:
    """A recurring pattern in user interactions."""
    pattern_id: str
    description: str
    frequency: int = 1
    last_seen: str = ""
    context: str = ""


class UserProfile:
    """
    Dialectic user profile that evolves through observation and validation.
    
    The profile has three layers:
    1. Explicit: Preferences the user has directly stated
    2. Inferred: Patterns the agent has observed and hypothesized
    3. Validated: Inferred preferences that have been confirmed through interaction
    """

    def __init__(self, user_id: str = "default", profile_dir: str = None):
        self.user_id = user_id
        if profile_dir is None:
            profile_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "memory", "data", "user_profiles",
            )
        self.profile_dir = profile_dir
        os.makedirs(self.profile_dir, exist_ok=True)
        self._path = os.path.join(self.profile_dir, f"{user_id}.json")

        self.explicit_prefs: dict[str, PreferenceDimension] = {}
        self.inferred_prefs: dict[str, PreferenceDimension] = {}
        self.validated_prefs: dict[str, PreferenceDimension] = {}
        self.interaction_patterns: dict[str, InteractionPattern] = {}
        self.session_count = 0
        self.total_interactions = 0
        self.created_at = datetime.now().isoformat()
        self.last_active = datetime.now().isoformat()

        self._load()

    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path, "r") as f:
                    data = json.load(f)
                self.session_count = data.get("session_count", 0)
                self.total_interactions = data.get("total_interactions", 0)
                self.created_at = data.get("created_at", self.created_at)
                self.last_active = data.get("last_active", self.last_active)

                for layer, storage in [
                    ("explicit_prefs", self.explicit_prefs),
                    ("inferred_prefs", self.inferred_prefs),
                    ("validated_prefs", self.validated_prefs),
                ]:
                    for pid, pdata in data.get(layer, {}).items():
                        storage[pid] = PreferenceDimension(**pdata)

                for pat_id, pat_data in data.get("interaction_patterns", {}).items():
                    self.interaction_patterns[pat_id] = InteractionPattern(**pat_data)
            except (json.JSONDecodeError, TypeError):
                pass

    def save(self):
        self.last_active = datetime.now().isoformat()
        data = {
            "user_id": self.user_id,
            "session_count": self.session_count,
            "total_interactions": self.total_interactions,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "explicit_prefs": {k: {key: val for key, val in v.__dict__.items() if not key.startswith("_")}
                              for k, v in self.explicit_prefs.items()},
            "inferred_prefs": {k: {key: val for key, val in v.__dict__.items() if not key.startswith("_")}
                              for k, v in self.inferred_prefs.items()},
            "validated_prefs": {k: {key: val for key, val in v.__dict__.items() if not key.startswith("_")}
                               for k, v in self.validated_prefs.items()},
            "interaction_patterns": {k: {key: val for key, val in v.__dict__.items() if not key.startswith("_")}
                                    for k, v in self.interaction_patterns.items()},
        }
        with open(self._path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def record_explicit_preference(self, name: str, value: str, category: str = "general"):
        pref_id = name.lower().replace(" ", "_")
        self.explicit_prefs[pref_id] = PreferenceDimension(
            name=name, category=category, value=value,
            confidence=1.0, evidence_count=1,
            last_updated=datetime.now().isoformat(), source="explicit",
        )
        self.save()

    def observe_behavior(self, observation: str, implied_preference: str, category: str = "general"):
        pref_id = implied_preference.lower().replace(" ", "_")

        if pref_id in self.explicit_prefs:
            existing = self.explicit_prefs[pref_id]
            if existing.value == implied_preference:
                existing.evidence_count += 1
            else:
                existing.contradictory_evidence += 1
                existing.confidence = max(0.3, existing.confidence - 0.1)
            existing.last_updated = datetime.now().isoformat()
            self.save()
            return

        if pref_id in self.inferred_prefs:
            existing = self.inferred_prefs[pref_id]
            if existing.value == implied_preference:
                existing.evidence_count += 1
                existing.confidence = min(0.95, existing.confidence + 0.1)
                if existing.confidence >= 0.8 and existing.evidence_count >= 3:
                    self.validated_prefs[pref_id] = existing
                    del self.inferred_prefs[pref_id]
            else:
                existing.contradictory_evidence += 1
                existing.confidence = max(0.2, existing.confidence - 0.15)
            existing.last_updated = datetime.now().isoformat()
        else:
            self.inferred_prefs[pref_id] = PreferenceDimension(
                name=implied_preference, category=category, value=implied_preference,
                confidence=0.5, evidence_count=1,
                last_updated=datetime.now().isoformat(), source="inferred",
            )

        self.save()

    def record_interaction(self, user_input: str, agent_response: str, success: bool):
        self.total_interactions += 1

        if "plan" in user_input.lower() or "规划" in user_input:
            self._detect_planning_preference(user_input)
        if "dose" in user_input.lower() or "剂量" in user_input:
            self._detect_dose_preference(user_input)
        if "seg" in user_input.lower() or "分割" in user_input:
            self._detect_segmentation_preference(user_input)

        pattern_key = self._classify_interaction(user_input)
        if pattern_key in self.interaction_patterns:
            self.interaction_patterns[pattern_key].frequency += 1
            self.interaction_patterns[pattern_key].last_seen = datetime.now().isoformat()
        else:
            self.interaction_patterns[pattern_key] = InteractionPattern(
                pattern_id=pattern_key, description=user_input[:100],
                frequency=1, last_seen=datetime.now().isoformat(),
                context=pattern_key,
            )
        self.save()

    def _detect_planning_preference(self, input_text: str):
        if any(w in input_text.lower() for w in ["quick", "fast", "简单", "快速"]):
            self.observe_behavior(input_text, "prefers_quick_planning", "planning")
        if any(w in input_text.lower() for w in ["detailed", "thorough", "详细", "完整"]):
            self.observe_behavior(input_text, "prefers_detailed_planning", "planning")
        if any(w in input_text.lower() for w in ["rl", "reinforcement", "优化"]):
            self.observe_behavior(input_text, "prefers_rl_optimization", "planning")

    def _detect_dose_preference(self, input_text: str):
        if any(w in input_text.lower() for w in ["CNN", "myDoseNet", "深度学习", "deep learning"]):
            self.observe_behavior(input_text, "prefers_cnn_dose", "dose")

    def _detect_segmentation_preference(self, input_text: str):
        if any(w in input_text.lower() for w in ["nnunet", "nnU-Net"]):
            self.observe_behavior(input_text, "prefers_nnunet_seg", "segmentation")
        if any(w in input_text.lower() for w in ["voco", "VoCo"]):
            self.observe_behavior(input_text, "prefers_voco_seg", "segmentation")

    def _classify_interaction(self, input_text: str) -> str:
        lower = input_text.lower()
        if "plan" in lower or "规划" in lower:
            return "planning"
        if "seg" in lower or "分割" in lower:
            return "segmentation"
        if "dose" in lower or "剂量" in lower:
            return "dose_evaluation"
        if "eval" in lower or "评估" in lower:
            return "evaluation"
        if "export" in lower or "导出" in lower:
            return "export"
        return "general"

    def get_active_preferences(self) -> dict:
        prefs = {}
        for layer in [self.validated_prefs, self.explicit_prefs, self.inferred_prefs]:
            for pid, pref in layer.items():
                if pid not in prefs or pref.confidence > prefs[pid].confidence:
                    prefs[pid] = pref
        return {k: {"name": v.name, "value": v.value, "confidence": v.confidence, "category": v.category}
                for k, v in prefs.items()}

    def get_preference_for_category(self, category: str) -> list[dict]:
        prefs = self.get_active_preferences()
        return [v for v in prefs.values() if v["category"] == category]

    def get_frequent_patterns(self, top_k: int = 5) -> list[dict]:
        patterns = sorted(
            self.interaction_patterns.values(),
            key=lambda p: p.frequency, reverse=True,
        )[:top_k]
        return [{"description": p.description, "frequency": p.frequency, "context": p.context} for p in patterns]

    def get_profile_summary(self) -> dict:
        return {
            "user_id": self.user_id,
            "session_count": self.session_count,
            "total_interactions": self.total_interactions,
            "preferences": self.get_active_preferences(),
            "top_patterns": self.get_frequent_patterns(3),
            "profile_maturity": min(1.0, self.total_interactions / 50),
        }

    def increment_session(self):
        self.session_count += 1
        self.save()
