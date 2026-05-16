"""
Image Preprocessor Tool
======================
Preprocesses medical images: resampling, normalization, bias correction.
Prepares images for downstream segmentation and dose calculation.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult
from typing import Dict, Optional, Tuple, List
import numpy as np
import SimpleITK as sitk


class ImagePreprocessorTool(BaseTool):
    """
    Tool for preprocessing medical images.

    Operations include:
    - Resampling to target spacing
    - Intensity normalization (window/level, min-max, z-score)
    - Bias field correction (N4ITK)
    - Skull stripping / body masking
    - Cropping / padding to target size
    """

    @property
    def name(self) -> str:
        return "image_preprocessor"

    @property
    def description(self) -> str:
        return (
            "Preprocess medical images for planning: resampling, normalization, bias correction. "
            "Input: SimpleITK image. "
            "Output: Preprocessed image with same metadata structure."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "image": {"type": "object", "description": "SimpleITK Image to preprocess"},
                "target_spacing": {
                    "type": "array",
                    "description": "Target voxel spacing [x, y, z] in mm (optional, resamples if provided)",
                },
                "normalization_method": {
                    "type": "string",
                    "description": "'window_level', 'minmax', 'zscore', or 'none'",
                    "enum": ["window_level", "minmax", "zscore", "none"],
                    "default": "window_level",
                },
                "window_center": {"type": "number", "default": 40, "description": "Window center for CT (HU)"},
                "window_width": {"type": "number", "default": 400, "description": "Window width for CT (HU)"},
                "bias_correction": {"type": "boolean", "default": False, "description": "Apply N4 bias field correction"},
                "target_size": {
                    "type": "array",
                    "description": "Target size [x, y, z] for cropping/padding (optional)",
                },
                "clip_min": {"type": "number", "description": "Minimum value to clip (optional)"},
                "clip_max": {"type": "number", "description": "Maximum value to clip (optional)"},
            },
            "required": ["image"],
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "image": {"type": "object", "description": "Preprocessed SimpleITK Image"},
                "array": {"type": "array", "description": "Preprocessed NumPy array"},
                "original_spacing": {"type": "array", "description": "Original voxel spacing"},
                "new_spacing": {"type": "array", "description": "New voxel spacing after resampling"},
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        image = kwargs["image"]
        target_spacing = kwargs.get("target_spacing")
        norm_method = kwargs.get("normalization_method", "window_level")
        window_center = kwargs.get("window_center", 40)
        window_width = kwargs.get("window_width", 400)
        bias_correction = kwargs.get("bias_correction", False)
        target_size = kwargs.get("target_size")
        clip_min = kwargs.get("clip_min")
        clip_max = kwargs.get("clip_max")

        original_spacing = list(image.GetSpacing())
        processed = image

        if target_spacing is not None:
            processed = self._resample_image(processed, target_spacing)

        if clip_min is not None or clip_max is not None:
            clip_min = clip_min if clip_min is not None else -np.inf
            clip_max = clip_max if clip_max is not None else np.inf
            arr = sitk.GetArrayFromImage(processed)
            arr = np.clip(arr, clip_min, clip_max)
            processed = sitk.GetImageFromArray(arr)
            processed.CopyInformation(image)

        if bias_correction:
            processed = self._apply_bias_correction(processed)

        if norm_method != "none":
            processed = self._normalize(processed, norm_method, window_center, window_width)

        if target_size is not None:
            processed = self._crop_or_pad(processed, target_size)

        array = sitk.GetArrayFromImage(processed)

        return ToolResult(
            success=True,
            data=processed,
            message=f"Preprocessing completed. Shape: {array.shape}, method: {norm_method}",
            metadata={
                "image": processed,
                "array": array,
                "original_spacing": original_spacing,
                "new_spacing": list(processed.GetSpacing()),
            },
        )

    def _resample_image(self, image: sitk.Image, target_spacing: List[float]) -> sitk.Image:
        original_spacing = image.GetSpacing()
        original_size = image.GetSize()
        target_size = [
            int(round(original_size[i] * original_spacing[i] / target_spacing[i]))
            for i in range(3)
        ]

        resampler = sitk.ResampleImageFilter()
        resampler.SetOutputSpacing(target_spacing)
        resampler.SetSize(target_size)
        resampler.SetOutputDirection(image.GetDirection())
        resampler.SetOutputOrigin(image.GetOrigin())
        resampler.SetTransform(sitk.Transform())
        resampler.SetDefaultPixelValue(image.GetPixelIDValue())
        resampler.SetInterpolator(sitk.sitkLinear)
        return resampler.Execute(image)

    def _apply_bias_correction(self, image: sitk.Image) -> sitk.Image:
        mask_image = sitk.OtsuThreshold(image, 0, 1, 200)
        corrector = sitk.N4BiasFieldCorrectionImageFilter()
        return corrector.Execute(image, mask_image)

    def _normalize(self, image: sitk.Image, method: str, window_center: float, window_width: float) -> sitk.Image:
        arr = sitk.GetArrayFromImage(image).astype(np.float32)

        if method == "window_level":
            clip_low = window_center - window_width / 2
            clip_high = window_center + window_width / 2
            arr = np.clip(arr, clip_low, clip_high)
            arr = (arr - clip_low) / (clip_high - clip_low)

        elif method == "minmax":
            min_val = np.min(arr)
            max_val = np.max(arr)
            if max_val > min_val:
                arr = (arr - min_val) / (max_val - min_val)

        elif method == "zscore":
            mean_val = np.mean(arr)
            std_val = np.std(arr)
            if std_val > 0:
                arr = (arr - mean_val) / std_val

        result = sitk.GetImageFromArray(arr)
        result.CopyInformation(image)
        return result

    def _crop_or_pad(self, image: sitk.Image, target_size: List[int]) -> sitk.Image:
        current_size = list(image.GetSize())
        current_array = sitk.GetArrayFromImage(image)

        pad_before = [max(0, (target_size[i] - current_size[i]) // 2) for i in range(3)]
        pad_after = [max(0, target_size[i] - current_size[i] - pad_before[i]) for i in range(3)]

        if any(p > 0 for p in pad_before + pad_after):
            pad_width = [(pad_before[i], pad_after[i]) for i in range(3)]
            current_array = np.pad(current_array, pad_width, mode="constant", constant_values=0)

        crop_start = [max(0, (current_array.shape[i] - target_size[i]) // 2) for i in range(3)]
        crop_end = [crop_start[i] + min(target_size[i], current_array.shape[i]) for i in range(3)]

        current_array = current_array[
            crop_start[0]:crop_end[0],
            crop_start[1]:crop_end[1],
            crop_start[2]:crop_end[2],
        ]

        result = sitk.GetImageFromArray(current_array)
        result.SetSpacing(image.GetSpacing())
        result.SetOrigin(image.GetOrigin())
        result.SetDirection(image.GetDirection())
        return result


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Image Preprocessor Tool")
    parser.add_argument("--input", required=True, help="Input image path (.nii.gz)")
    parser.add_argument("--output", required=True, help="Output image path (.nii.gz)")
    parser.add_argument("--target_spacing", nargs=3, type=float, help="Target spacing [x, y, z]")
    parser.add_argument("--normalization", choices=["window_level", "minmax", "zscore", "none"], default="window_level")
    args = parser.parse_args()

    tool = ImagePreprocessorTool()
    image = sitk.ReadImage(args.input)
    result = tool._execute(
        image=image,
        target_spacing=args.target_spacing,
        normalization_method=args.normalization,
    )

    if result.success:
        sitk.WriteImage(result.data, args.output)
        print(f"Preprocessed image saved to {args.output}")
    else:
        print(f"Error: {result.error}")


if __name__ == "__main__":
    main()