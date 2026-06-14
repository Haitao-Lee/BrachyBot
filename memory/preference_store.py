"""
Preference Store
================
Persistent storage for user preferences and learned defaults.
Complements InteractionMemory with structured preference data.
"""

import os
import json
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict


@dataclass
class UserPreference:
    """A single user preference item."""
    category: str           # e.g., "planning", "segmentation", "dose"
    key: str               # e.g., "default_mode", "preferred_organ"
    value: Any             # The preference value
    confidence: float      # 0-1, how confident we are in this preference
    source: str            # "explicit", "learned", "default"
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["updated_at"] = self.updated_at
        return d

    @classmethod
    def from_dict(cls, d: Dict) -> "UserPreference":
        return cls(**d)


class PreferenceStore:
    """
    Stores and retrieves user preferences.

    Manages preferences across categories:
    - planning: mode, seed_info, etc.
    - segmentation: tumor_type, organ_type, etc.
    - dose: engine, normalization, etc.
    - ui: output_format, verbosity, etc.
    """

    DEFAULT_PREFERENCES = {
        "planning": {
            "default_mode": {"value": "rule_based", "confidence": 1.0, "source": "default"},
            "default_seed_avr_dose": {"value": 50.0, "confidence": 1.0, "source": "default"},
            "default_prescribed_dose": {"value": 1.0, "confidence": 1.0, "source": "default"},
        },
        "segmentation": {
            "default_tumor_type": {"value": "pancreatic", "confidence": 1.0, "source": "default"},
            "default_organ_type": {"value": "general", "confidence": 1.0, "source": "default"},
        },
        "dose": {
            "default_engine": {"value": "cnn", "confidence": 1.0, "source": "default"},
            "default_normalize_min": {"value": -1000, "confidence": 1.0, "source": "default"},
            "default_normalize_max": {"value": 3000, "confidence": 1.0, "source": "default"},
        },
        "ui": {
            "output_format": {"value": "json", "confidence": 1.0, "source": "default"},
            "verbose": {"value": True, "confidence": 1.0, "source": "default"},
        },
    }

    def __init__(self, user_id: str = "default", storage_dir: str = None):
        self.user_id = user_id
        self.storage_dir = storage_dir or os.path.join(
            os.path.dirname(__file__), "data", "preferences"
        )
        os.makedirs(self.storage_dir, exist_ok=True)

        self.preferences: Dict[str, Dict[str, UserPreference]] = {}
        self._load_preferences()

    def get(self, category: str, key: str, default: Any = None) -> Any:
        """Get a preference value."""
        if category in self.preferences and key in self.preferences[category]:
            return self.preferences[category][key].value
        return default

    def set(self, category: str, key: str, value: Any,
            confidence: float = 1.0, source: str = "explicit"):
        """Set a preference value."""
        if category not in self.preferences:
            self.preferences[category] = {}

        self.preferences[category][key] = UserPreference(
            category=category,
            key=key,
            value=value,
            confidence=confidence,
            source=source,
        )

        self._save_preferences()

    def update_from_learned(self, learned_prefs: Dict[str, Dict[str, Any]]):
        """
        Update preferences from SkillLearner's learned preferences.

        learned_prefs format: {tool_name: {param_name: {"value": v, "confidence": c}}}
        """
        for tool_name, params in learned_prefs.items():
            category = self._tool_to_category(tool_name)
            for param_name, data in params.items():
                key = f"{tool_name}_{param_name}"
                current = self.get(category, key)

                if current is None or data.get("confidence", 0) > 0.5:
                    self.set(
                        category=category,
                        key=key,
                        value=data.get("value"),
                        confidence=data.get("confidence", 0.5),
                        source="learned",
                    )

    def get_category(self, category: str) -> Dict[str, Any]:
        """Get all preferences in a category."""
        if category not in self.preferences:
            defaults = self.DEFAULT_PREFERENCES.get(category, {})
            return {k: v["value"] for k, v in defaults.items()}

        return {k: v.value for k, v in self.preferences[category].items()}

    def get_all_preferences(self) -> Dict[str, Dict[str, Any]]:
        """Get all preferences organized by category."""
        result = {}
        for category in set(list(self.preferences.keys()) +
                          list(self.DEFAULT_PREFERENCES.keys())):
            result[category] = self.get_category(category)
        return result

    def get_high_confidence(self, min_confidence: float = 0.7) -> Dict[str, Any]:
        """Get all high-confidence preferences."""
        result = {}
        for category, prefs in self.preferences.items():
            high_conf = {
                k: v.value for k, v in prefs.items()
                if v.confidence >= min_confidence
            }
            if high_conf:
                result[category] = high_conf
        return result

    def apply_to_tool_params(self, tool_name: str,
                            params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply learned preferences to tool parameters.

        Returns modified params dict with defaults filled in.
        """
        category = self._tool_to_category(tool_name)
        tool_prefs = self.get_category(category)

        applied = {}
        for key, value in params.items():
            if value is None:
                pref_key = f"{tool_name}_{key}"
                if pref_key in self.preferences.get(category, {}):
                    applied[key] = self.preferences[category][pref_key].value
                elif key in tool_prefs:
                    applied[key] = tool_prefs[key]
                else:
                    applied[key] = value
            else:
                applied[key] = value

        return applied

    def reset_category(self, category: str):
        """Reset a category to defaults."""
        if category in self.preferences:
            del self.preferences[category]
        self._save_preferences()

    def reset_all(self):
        """Reset all preferences to defaults."""
        self.preferences = {}
        self._save_preferences()

    def _tool_to_category(self, tool_name: str) -> str:
        """Map tool name to preference category."""
        mapping = {
            "seed_planning": "planning",
            "trajectory_planning": "planning",
            "ctv_segmentation": "segmentation",
            "oar_segmentation": "segmentation",
            "dose_engine": "dose",
            "dose_evaluation": "dose",
            "plan_quality_scorer": "planning",
        }
        return mapping.get(tool_name, "general")

    def _load_preferences(self):
        """Load preferences from disk."""
        prefs_file = os.path.join(self.storage_dir, f"{self.user_id}_prefs.json")
        if os.path.exists(prefs_file):
            try:
                with open(prefs_file, "r") as f:
                    data = json.load(f)
                self.preferences = {
                    cat: {k: UserPreference.from_dict(v) for k, v in prefs.items()}
                    for cat, prefs in data.items()
                }
            except (json.JSONDecodeError, KeyError):
                self.preferences = {}
        else:
            self.preferences = {}

    def _save_preferences(self):
        """Save preferences to disk."""
        prefs_file = os.path.join(self.storage_dir, f"{self.user_id}_prefs.json")
        data = {
            cat: {k: v.to_dict() for k, v in prefs.items()}
            for cat, prefs in self.preferences.items()
        }
        with open(prefs_file, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def export(self, path: str = None) -> str:
        """Export preferences to JSON."""
        if path is None:
            path = os.path.join(self.storage_dir, f"{self.user_id}_prefs_export.json")

        data = {
            "user_id": self.user_id,
            "export_time": time.time(),
            "preferences": {
                cat: {k: v.to_dict() for k, v in prefs.items()}
                for cat, prefs in self.preferences.items()
            },
        }

        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

        return path