"""
Auto Navigate Tool
==================
Navigate to tumor/organ center from segmentation masks.
Returns slice indices for frontend to navigate.
"""

import os
import sys
import logging
import numpy as np
from typing import Dict, Any, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class AutoNavigateTool(BaseTool):
    """Navigate viewer to tumor/organ center from segmentation masks."""

    @property
    def name(self) -> str:
        return "auto_navigate"

    @property
    def description(self) -> str:
        return (
            "Navigate the viewer to show a specific structure (tumor, organ). "
            "Finds the center of the structure from segmentation and returns slice indices. "
            "Use when user says 'go to tumor', 'show pancreas', 'navigate to slice X'."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Structure: 'ctv', 'tumor', or organ name like 'pancreas', 'liver'"
                },
                "label_id": {
                    "type": "integer",
                    "description": "Specific label ID to navigate to (for multi-label OAR masks)"
                },
                "ctv_array": {"type": "object", "description": "CTV segmentation array from memory"},
                "oar_array": {"type": "object", "description": "OAR segmentation array from memory"},
                "organ_names": {"type": "object", "description": "Organ name mapping from memory"},
            },
            "required": ["target"]
        }

    def _execute(self, **kwargs) -> ToolResult:
        target = kwargs.get("target", "ctv").lower()
        label_id = kwargs.get("label_id")

        try:
            if target in ("ctv", "tumor"):
                mask = kwargs.get("ctv_array")
                if mask is None:
                    return ToolResult(success=False, error="No CTV mask",
                                    message="No CTV segmentation found. Run segmentation first.")
                structure_name = "CTV/Tumor"
            else:
                mask = kwargs.get("oar_array")
                if mask is None:
                    return ToolResult(success=False, error="No OAR mask",
                                    message="No OAR segmentation found. Run segmentation first.")
                # Try to find specific organ by name
                organ_names = kwargs.get("organ_names", {})
                if label_id is None:
                    # Find label_id by organ name
                    for lid, name in organ_names.items():
                        if target in str(name).lower():
                            label_id = int(lid) if isinstance(lid, str) else lid
                            break
                structure_name = target

            center = self._find_center(mask, label_id)
            if center is None:
                return ToolResult(success=False, error="Empty mask",
                                message=f"No voxels found for {structure_name}")

            actions = [
                {"target": "slice.axial", "command": "set", "value": center[0]},
                {"target": "slice.sagittal", "command": "set", "value": center[1]},
                {"target": "slice.coronal", "command": "set", "value": center[2]},
            ]

            return ToolResult(
                success=True,
                message=f"Navigated to {structure_name}: axial={center[0]}, sagittal={center[1]}, coronal={center[2]}",
                metadata={
                    "actions": actions,
                    "structure": structure_name,
                    "center": {"axial": center[0], "sagittal": center[1], "coronal": center[2]},
                }
            )
        except Exception as e:
            logger.error(f"Auto navigate failed: {e}")
            return ToolResult(success=False, error=str(e), message=f"Navigation failed: {e}")

    def _find_center(self, mask, label_id=None):
        if label_id is not None:
            coords = np.where(mask == label_id)
        else:
            coords = np.where(mask > 0)
        if len(coords[0]) == 0:
            return None
        return tuple(int(np.mean(c)) for c in coords)
