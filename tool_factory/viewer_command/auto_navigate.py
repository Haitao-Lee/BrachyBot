"""
Auto Navigate Tool
==================
Automatically navigate to tumor/organ location in the viewer.
Uses segmentation results to find and navigate to the center of structures.
"""

import os
import sys
import json
import logging
import numpy as np
from typing import Dict, Any, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class AutoNavigateTool(BaseTool):
    """Automatically navigate to tumor/organ location."""

    @property
    def name(self) -> str:
        return "auto_navigate"

    @property
    def description(self) -> str:
        return (
            "Automatically navigate the viewer to show a specific structure (tumor, organ, etc.). "
            "Finds the center of the structure from segmentation mask and navigates all 3 views. "
            "Use this when the user asks to 'go to', 'show', 'navigate to' a specific anatomy."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Structure to navigate to: 'ctv', 'oar', or specific organ name like 'liver', 'pancreas', 'prostate', 'rectum', 'bladder', etc."
                },
                "organ_name": {
                    "type": "string",
                    "description": "For OAR: specific organ name (e.g., 'liver', 'kidney_right', 'pancreas')"
                }
            },
            "required": ["target"]
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "center": {"type": "object", "description": "Center coordinates {axial, sagittal, coronal}"},
                "message": {"type": "string"}
            }
        }

    def _execute(self, **kwargs) -> ToolResult:
        """Navigate to structure center."""
        target = kwargs.get("target", "ctv")
        organ_name = kwargs.get("organ_name")

        try:
            # Get the segmentation mask from memory
            import SimpleITK as sitk

            if target.lower() == "ctv":
                mask = self._get_ctv_mask()
                structure_name = "CTV"
            elif target.lower() == "oar":
                mask = self._get_oar_mask(organ_name)
                structure_name = organ_name or "OAR"
            else:
                # Try as organ name
                mask = self._get_oar_mask(target)
                structure_name = target

            if mask is None:
                return ToolResult(
                    success=False,
                    error=f"No segmentation mask found for {target}",
                    message=f"Please segment {target} first before navigating to it."
                )

            # Find center of mass
            center = self._find_center_of_mass(mask)

            if center is None:
                return ToolResult(
                    success=False,
                    error=f"Empty mask for {target}",
                    message=f"The {structure_name} mask is empty."
                )

            # Navigate viewer to center
            self._navigate_to_center(center)

            return ToolResult(
                success=True,
                message=f"Navigated to {structure_name} center: axial={center[0]}, sagittal={center[1]}, coronal={center[2]}",
                metadata={
                    "structure": structure_name,
                    "center": {
                        "axial": int(center[0]),
                        "sagittal": int(center[1]),
                        "coronal": int(center[2])
                    },
                    "shape": list(mask.shape) if hasattr(mask, 'shape') else None
                }
            )

        except Exception as e:
            logger.error(f"Auto navigate failed: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                message=f"Navigation failed: {e}"
            )

    def _get_ctv_mask(self) -> Optional[np.ndarray]:
        """Get CTV segmentation mask."""
        # Try to get from agent memory via import
        try:
            from AgenticSys import BrachyAgent
            # This will be handled by the agent's memory system
            pass
        except:
            pass

        # Try to load from file
        ctv_paths = [
            "./output/ctv_mask.nii.gz",
            "./output/segmentation_ctv.nii.gz"
        ]
        for path in ctv_paths:
            if os.path.exists(path):
                import nibabel as nib
                img = nib.load(path)
                return img.get_fdata()

        return None

    def _get_oar_mask(self, organ_name: Optional[str] = None) -> Optional[np.ndarray]:
        """Get OAR segmentation mask."""
        # Try to load from file
        oar_paths = [
            "./output/oar_mask.nii.gz",
            "./output/segmentation_oar.nii.gz"
        ]
        for path in oar_paths:
            if os.path.exists(path):
                import nibabel as nib
                img = nib.load(path)
                data = img.get_fdata()

                if organ_name and data.max() > 1:
                    # Multi-label mask, find specific organ
                    # This would need the label mapping
                    pass

                return data

        return None

    def _find_center_of_mass(self, mask: np.ndarray) -> Optional[Tuple[int, int, int]]:
        """Find center of mass of a binary mask."""
        if mask is None or mask.sum() == 0:
            return None

        # Find non-zero voxels
        coords = np.where(mask > 0)
        if len(coords[0]) == 0:
            return None

        # Calculate center of mass
        center = tuple(int(np.mean(c)) for c in coords)
        return center

    def _navigate_to_center(self, center: Tuple[int, int, int]) -> None:
        """Navigate viewer to center coordinates."""
        import requests

        API_BASE = "http://localhost:8080/api"

        # Navigate axial
        requests.post(f"{API_BASE}/viewer/control", json={
            "action": "navigate_slice",
            "axis": "axial",
            "slice_index": center[0]
        })

        # Navigate sagittal
        requests.post(f"{API_BASE}/viewer/control", json={
            "action": "navigate_slice",
            "axis": "sagittal",
            "slice_index": center[1]
        })

        # Navigate coronal
        requests.post(f"{API_BASE}/viewer/control", json={
            "action": "navigate_slice",
            "axis": "coronal",
            "slice_index": center[2]
        })


if __name__ == "__main__":
    tool = AutoNavigateTool()
    print(f"Tool: {tool.name}")
    print(f"Description: {tool.description}")
