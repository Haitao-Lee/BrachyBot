"""
Image Loader Tool
================
Loads medical images (CT, MR, CBCT) from various file formats.
Supports .nii.gz, .mhd, .dcm, and directory-based DICOM loading.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult
from typing import Dict, Optional, Tuple
import SimpleITK as sitk


class ImageLoaderTool(BaseTool):
    """
    Tool for loading medical images from various formats.

    Supports NIfTI (.nii, .nii.gz), MetaImage (.mhd), and DICOM files/directories.
    Automatically detects format and handles 3D/4D images.
    """

    @property
    def name(self) -> str:
        return "image_loader"

    @property
    def description(self) -> str:
        return (
            "Load medical images (CT, MR, CBCT) from files. "
            "Supports NIfTI (.nii.gz), MetaImage (.mhd), and DICOM directories. "
            "Returns SimpleITK image with full spatial metadata (spacing, origin, direction). "
            "Input: file path or DICOM directory. "
            "Output: SimpleITK Image object."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to image file (.nii.gz, .nii, .mhd) or DICOM directory",
                },
                "series_id": {
                    "type": ["string", "integer"],
                    "description": "DICOM series ID (UID or index) if loading from directory",
                },
                "load_into_memory": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to load image fully into memory",
                },
            },
            "required": ["file_path"],
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "image": {"type": "object", "description": "SimpleITK Image"},
                "array": {"type": "array", "description": "NumPy array of image data"},
                "spacing": {"type": "array", "description": "Voxel spacing [x, y, z] in mm"},
                "origin": {"type": "array", "description": "Physical origin [x, y, z] in mm"},
                "direction": {"type": "array", "description": "Direction cosines (9 values)"},
                "size": {"type": "array", "description": "Image dimensions [x, y, z]"},
                "modality": {"type": "string", "description": "Imaging modality (CT, MR, etc.)"},
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        import numpy as np

        file_path = kwargs["file_path"]
        series_id = kwargs.get("series_id")
        load_into_memory = kwargs.get("load_into_memory", True)

        if not os.path.exists(file_path):
            return ToolResult(success=False, error=f"File not found: {file_path}")

        try:
            if os.path.isdir(file_path):
                image = self._load_dicom(file_path, series_id)
                modality = "DICOM"
            elif file_path.endswith(".dcm"):
                image = self._load_dicom_file(file_path)
                modality = "DICOM"
            elif file_path.endswith((".nii", ".nii.gz")):
                image = sitk.ReadImage(file_path)
                modality = self._infer_modality(image)
            elif file_path.endswith(".mhd"):
                image = sitk.ReadImage(file_path)
                modality = "Unknown"
            else:
                image = sitk.ReadImage(file_path)
                modality = "Unknown"

            array = sitk.GetArrayFromImage(image)
            size = list(image.GetSize())
            spacing = list(image.GetSpacing())
            origin = list(image.GetOrigin())
            direction = list(image.GetDirection())

            return ToolResult(
                success=True,
                data=image,
                message=f"Image loaded: {os.path.basename(file_path)}, shape={array.shape}, modality={modality}",
                metadata={
                    "image": image,
                    "array": array,
                    "spacing": spacing,
                    "origin": origin,
                    "direction": direction,
                    "size": size,
                    "modality": modality,
                    "file_path": file_path,
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=f"Failed to load image: {str(e)}")

    def _load_dicom(self, dicom_dir: str, series_id=None) -> sitk.Image:
        reader = sitk.ImageFileReader()
        reader.ImageFileReaderWarningOff()

        if series_id is not None:
            import sitk as s
            if isinstance(series_id, int):
                series_reader = sitk.ImageSeriesReader()
                series_ids = series_reader.GetGDCMSeriesIDs(dicom_dir)
                if 0 <= series_id < len(series_ids):
                    series_id = series_ids[series_id]
                else:
                    series_id = None

            if series_id is not None:
                series_reader = sitk.ImageSeriesReader()
                series_reader.SetOutputPixelType(sitk.sitkFloat32)
                dicom_files = series_reader.GetGDCMSeriesFileNames(dicom_dir, series_id)
                series_reader.SetFileNames(dicom_files)
                return series_reader.Execute()

        series_reader = sitk.ImageSeriesReader()
        series_reader.SetOutputPixelType(sitk.sitkFloat32)
        dicom_files = series_reader.GetGDCMSeriesFileNames(dicom_dir)
        series_reader.SetFileNames(dicom_files)
        return series_reader.Execute()

    def _load_dicom_file(self, dcm_file: str) -> sitk.Image:
        reader = sitk.ImageFileReader()
        reader.SetFileName(dcm_file)
        return reader.Execute()

    def _infer_modality(self, image) -> str:
        try:
            if hasattr(image, "GetMetaData"):
                modality = image.GetMetaData("0008|0060")
                return modality
        except:
            pass
        return "CT"


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Image Loader - Load medical images")
    parser.add_argument("--file_path", required=True, help="Path to image file or DICOM directory")
    parser.add_argument("--output", help="Output path for numpy array")
    args = parser.parse_args()

    tool = ImageLoaderTool()
    result = tool._execute(file_path=args.file_path)

    if result.success:
        print(result.message)
        print(f"Shape: {result.metadata['array'].shape}")
        print(f"Spacing: {result.metadata['spacing']}")
        if args.output:
            import numpy as np
            np.save(args.output, result.metadata["array"])
            print(f"Saved array to {args.output}")
    else:
        print(f"Error: {result.error}")


if __name__ == "__main__":
    main()