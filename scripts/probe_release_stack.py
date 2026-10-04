"""Bounded synthetic compatibility probe, not clinical or full-model validation.

No real patient input, external request, segmentation job, planning, guide or
report is run. Real DoseUNet weights are checked against an observed manifest;
VoCo gets an API/shape check only, never unsafe pickle fallback loading.
"""
import argparse
import hashlib
import importlib
import importlib.metadata
import json
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cuda", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output must be new")
    import numpy as np
    import SimpleITK as sitk
    import torch
    torch.set_num_threads(1)
    # This numerical compatibility probe compares FP32 with FP32, not the
    # CUDA backend's default TF32/mixed-precision policy. It does not change
    # production settings or qualify those faster precision profiles.
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    versions = {name: importlib.metadata.version(name) for name in (
        "torch", "torchvision", "monai", "nnunetv2", "TotalSegmentator", "numpy", "scipy", "SimpleITK", "pydicom", "dicom2nifti")}
    for module in ("monai", "nnunetv2.inference.predict_from_raw_data", "totalsegmentator.python_api", "tool_factory.CTV_seg.voco_base"):
        importlib.import_module(module)
    checkpoint = REPO / "models/dose_unet_spacing1mm/best_model.pth"
    manifest = json.loads(args.model_manifest.read_text())
    expected = next(item for item in manifest["models"] if item["path"] == "models/dose_unet_spacing1mm/best_model.pth")
    if hashlib.sha256(checkpoint.read_bytes()).hexdigest() != expected["sha256"]:
        raise RuntimeError("DoseUNet model bytes differ from frozen manifest")
    from plans.dose_pre.model_loader import load_dose_model
    model, error, resolved = load_dose_model(str(checkpoint), device="cpu")
    if error or model is None:
        raise RuntimeError("Strict DoseUNet checkpoint loading failed")
    model.eval()
    # Build input in NumPy, independent of PyTorch RNG/version behavior.
    inputs = np.random.default_rng(1927).normal(0, .1, (1, 3, 32, 32, 32)).astype(np.float32)
    start = time.perf_counter()
    with torch.inference_mode():
        cpu = model(torch.from_numpy(inputs)).cpu().numpy()
    if not np.isfinite(cpu).all() or cpu.shape != (1, 1, 32, 32, 32):
        raise RuntimeError("Invalid synthetic DoseUNet output")
    result = {"scope": "Synthetic ABI/API and real DoseUNet checkpoint compatibility only; no independent dose truth or clinical validation",
              "versions": versions, "checkpoint_sha256": expected["sha256"], "cpu_seconds": time.perf_counter() - start,
              "dose_shape": list(cpu.shape), "dose_finite": True, "cuda_available": torch.cuda.is_available(),
              "voCo_real_checkpoint_and_physical_mapping": "NOT_VALIDATED"}
    result["validation_precision"] = "FP32; TF32 disabled only in this detached probe"
    from monai.networks.nets import SwinUNETR
    swin = SwinUNETR(in_channels=1, out_channels=2, feature_size=12, use_v2=True).eval()
    with torch.inference_mode():
        swin_shape = list(swin(torch.zeros((1, 1, 64, 64, 64))).shape)
    if swin_shape != [1, 2, 64, 64, 64]:
        raise RuntimeError("MONAI/VoCo architecture API shape mismatch")
    result["monai_voCo_api_shape"] = swin_shape
    image = sitk.GetImageFromArray(np.zeros((17, 19, 23), np.uint8))
    image.SetSpacing((.8, 1.1, 2.3))
    image.SetOrigin((-31., 24., -70.))
    angle = .37
    image.SetDirection((np.cos(angle), -np.sin(angle), 0., np.sin(angle), np.cos(angle), 0., 0., 0., 1.))
    index = (6.2, 7.8, 8.1)
    error = float(np.max(np.abs(np.array(image.TransformPhysicalPointToContinuousIndex(image.TransformContinuousIndexToPhysicalPoint(index))) - index)))
    if error > 1e-9:
        raise RuntimeError("SimpleITK physical-grid round trip failed")
    result["sitk_roundtrip_index_error"] = error
    if args.cuda:
        if not torch.cuda.is_available():
            raise RuntimeError("Requested CUDA probe is unavailable")
        from plans.device_manager import device_session
        from tool_factory.CTV_seg.site_model_runtime import gpu_lock
        with device_session("release_compatibility_probe") as lease:
            device = torch.device(lease.device_str)
            if device.type != "cuda":
                raise RuntimeError("CUDA lease did not resolve to a CUDA device")
            with gpu_lock(device.index or 0, timeout=10):
                model.to(device)
                with torch.inference_mode():
                    gpu = model(torch.from_numpy(inputs).to(device)).cpu().numpy()
                result["cuda_cpu_max_abs_error"] = float(np.max(np.abs(gpu - cpu)))
                result["cuda_cpu_allclose"] = bool(np.allclose(gpu, cpu, rtol=1e-4, atol=1e-5))
                if not result["cuda_cpu_allclose"]:
                    print(json.dumps({"cuda_cpu_max_abs_error": result["cuda_cpu_max_abs_error"],
                                      "validation_precision": result["validation_precision"]}))
                    raise RuntimeError("Synthetic CUDA/CPU DoseUNet parity failed")
                model.to("cpu")
                torch.cuda.empty_cache()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.save(args.output.with_suffix(".npy"), cpu)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "versions": versions, "dose_finite": True, "cuda_cpu_allclose": result.get("cuda_cpu_allclose")}))


if __name__ == "__main__":
    main()
