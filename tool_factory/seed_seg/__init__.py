"""
Seed Segmentation Tool
======================
Detects and segments implanted seeds from intra-operative imaging (CT/CBCT).
Used for real-time seed position verification during treatment.
"""

from tool_factory import BaseTool, ToolResult
import numpy as np
import SimpleITK as sitk
from scipy.ndimage import label, center_of_mass, gaussian_filter
from typing import Dict, Optional, List


class SeedSegmentationTool(BaseTool):
    """
    Tool for detecting and segmenting implanted brachytherapy seeds from CT images.
    
    Used during intra-operative imaging to verify seed positions against the planned plan.
    Applies intensity thresholding and connected component analysis to identify seeds,
    then computes their physical coordinates for comparison with planned positions.
    """
    
    @property
    def name(self) -> str:
        return "seed_segmentation"
    
    @property
    def description(self) -> str:
        return (
            "Detect and segment implanted brachytherapy seeds from intra-operative CT/CBCT images. "
            "Uses intensity thresholding and connected component analysis to identify individual seeds. "
            "Returns detected seed positions in both voxel and physical coordinates. "
            "Can compare detected positions against planned positions to compute deviation metrics."
        )
    
    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "image": {
                    "type": "object",
                    "description": "SimpleITK Image of the intra-operative CT/CBCT scan",
                },
                "image_path": {
                    "type": "string",
                    "description": "Path to the CT image file",
                },
                "seed_threshold": {
                    "type": "number",
                    "description": "HU threshold for seed detection (default: 2000)",
                    "default": 2000,
                },
                "min_seed_volume": {
                    "type": "number",
                    "description": "Minimum connected component volume in voxels (default: 3)",
                    "default": 3,
                },
                "max_seed_volume": {
                    "type": "number",
                    "description": "Maximum connected component volume in voxels (default: 200)",
                    "default": 200,
                },
                "gaussian_sigma": {
                    "type": "number",
                    "description": "Gaussian smoothing sigma before detection (default: 0.5)",
                    "default": 0.5,
                },
                "planned_seeds": {
                    "type": "array",
                    "description": "List of planned seed positions for deviation analysis (optional)",
                },
            },
            "required": [],
        }
    
    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "detected_seeds": {
                    "type": "array",
                    "description": "List of detected seed positions (voxel and physical coords)",
                },
                "seed_mask": {
                    "type": "object",
                    "description": "Binary mask of detected seeds",
                },
                "num_detected": {
                    "type": "integer",
                    "description": "Number of detected seeds",
                },
                "deviation_stats": {
                    "type": "object",
                    "description": "Statistics of deviation from planned positions (if provided)",
                },
            },
        }
    
    def _execute(self, **kwargs) -> ToolResult:
        image = kwargs.get("image")
        image_path = kwargs.get("image_path")
        seed_threshold = kwargs.get("seed_threshold", 2000)
        min_seed_volume = kwargs.get("min_seed_volume", 3)
        max_seed_volume = kwargs.get("max_seed_volume", 200)
        gaussian_sigma = kwargs.get("gaussian_sigma", 0.5)
        planned_seeds = kwargs.get("planned_seeds")
        
        if image is None and image_path is not None:
            image = sitk.ReadImage(image_path)
        elif image is None:
            raise ValueError("Either 'image' or 'image_path' must be provided")
        
        array = sitk.GetArrayFromImage(image)
        smoothed = gaussian_filter(array.astype(np.float64), sigma=gaussian_sigma)
        seed_binary = (smoothed >= seed_threshold).astype(np.int32)
        
        labeled_array, num_features = label(seed_binary)
        
        detected_seeds = []
        seed_mask = np.zeros_like(array, dtype=np.int32)
        
        for i in range(1, num_features + 1):
            component = (labeled_array == i)
            volume = np.sum(component)
            
            if min_seed_volume <= volume <= max_seed_volume:
                com = center_of_mass(component)
                com_voxel = np.array([com[0], com[1], com[2]])
                com_physical = self._voxel_to_physical(image, com_voxel)
                
                seed_mask[component] = i
                detected_seeds.append({
                    "id": i,
                    "voxel_position": com_voxel.tolist(),
                    "physical_position": com_physical.tolist(),
                    "volume_voxels": int(volume),
                })
        
        deviation_stats = {}
        if planned_seeds is not None and len(detected_seeds) > 0:
            deviations = self._compute_deviations(detected_seeds, planned_seeds, image)
            deviation_stats = {
                "mean_deviation_mm": float(np.mean(deviations)) if len(deviations) > 0 else 0.0,
                "max_deviation_mm": float(np.max(deviations)) if len(deviations) > 0 else 0.0,
                "min_deviation_mm": float(np.min(deviations)) if len(deviations) > 0 else 0.0,
                "num_matched": len(deviations),
                "individual_deviations_mm": deviations.tolist(),
            }
        
        return ToolResult(
            success=True,
            data=detected_seeds,
            message=f"Seed segmentation completed. Detected {len(detected_seeds)} seeds.",
            metadata={
                "detected_seeds": detected_seeds,
                "seed_mask": seed_mask,
                "num_detected": len(detected_seeds),
                "deviation_stats": deviation_stats,
            },
        )
    
    def _voxel_to_physical(self, image, voxel_coords_zyx):
        """Convert NumPy-order ``(z, y, x)`` coordinates to physical LPS."""
        coords = np.asarray(voxel_coords_zyx, dtype=np.float64).reshape(-1)
        if coords.size != image.GetDimension() or not np.all(np.isfinite(coords)):
            raise ValueError("voxel coordinates must contain one finite value per image dimension")
        index_xyz = tuple(float(v) for v in coords[::-1])
        return np.asarray(
            image.TransformContinuousIndexToPhysicalPoint(index_xyz),
            dtype=np.float64,
        )
    
    def _compute_deviations(self, detected_seeds, planned_seeds, image):
        detected_physical = np.array([s["physical_position"] for s in detected_seeds])
        planned_physical = []
        for ps in planned_seeds:
            pos = ps[0] if isinstance(ps, (list, tuple)) else ps
            if len(pos) == 3:
                planned_physical.append(pos)
            else:
                planned_physical.append(self._voxel_to_physical(image, np.array(pos)).tolist())
        planned_physical = np.array(planned_physical)
        
        deviations = []
        used_detected = set()
        for pp in planned_physical:
            dists = np.linalg.norm(detected_physical - pp, axis=1)
            for idx in np.argsort(dists):
                if idx not in used_detected:
                    deviations.append(dists[idx])
                    used_detected.add(idx)
                    break
        
        return np.array(deviations)
