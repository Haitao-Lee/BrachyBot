#!/usr/bin/env python3
"""Isolated official-SAT3D inference worker used by BrachyBot.

This file provides only deployment glue.  Model components and the custom
sliding-window implementation are imported from the configured official
SAT3D checkout at runtime.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np


def _parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--critic", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--points", required=True)
    parser.add_argument("--device", default="cuda:0")
    return parser.parse_args()


def _remove_module_prefix(state):
    return {key.removeprefix("module."): value for key, value in state.items()}


def _load_sliding_window(root: Path):
    path = root / "SAT3D-slicer" / "sat3D" / "sat3DLib" / "utils_monai_bts.py"
    spec = importlib.util.spec_from_file_location("sat3d_official_sliding_window", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import official SAT3D sliding window: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.sliding_window_inference


def _load_official_modeling(root: Path):
    package_dir = root / "segment_anything_with_swin_conf" / "modeling"
    name = "sat3d_official_modeling"
    spec = importlib.util.spec_from_file_location(
        name,
        package_dir / "__init__.py",
        submodule_search_locations=[str(package_dir)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import official SAT3D model components: {package_dir}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _build_model(root: Path):
    # The repository root builder at the pinned commit references a missing
    # build_sam3D_swin symbol.  Build the exact published checkpoint topology
    # from the official model components instead of modifying upstream source.
    import torch
    modeling = _load_official_modeling(root)
    MaskDecoder3D = modeling.MaskDecoder3D
    PromptEncoder3D = modeling.PromptEncoder3D
    Sam3D = modeling.Sam3D
    SwinTransformer = modeling.SwinTransformer

    image_size = 128
    prompt_embed_dim = 384
    return Sam3D(
        image_encoder=SwinTransformer(
            img_size=(128, 128, 128),
            patch_size=(2, 2, 2),
            in_chans=1,
            num_classes=1,
            embed_dim=48,
            depths=[2, 2, 2, 1],
            depths_decoder=[1, 2, 2, 2],
            num_heads=[3, 6, 12, 24],
            window_size=(8, 8, 8),
            mlp_ratio=4.0,
            qkv_bias=True,
            qk_scale=None,
            drop_rate=0.0,
            attn_drop_rate=0.0,
            drop_path_rate=0.1,
            norm_layer=torch.nn.LayerNorm,
            patch_norm=True,
            use_checkpoint=False,
            frozen_stages=-1,
            final_upsample="expand_first",
        ),
        prompt_encoder=PromptEncoder3D(
            in_chans=1,
            embed_dim=prompt_embed_dim,
            image_embedding_size=(8, 8, 8),
            input_image_size=(image_size, image_size, image_size),
            mask_in_chans=16,
        ),
        mask_decoder=MaskDecoder3D(
            num_multimask_outputs=3,
            transformer_dim=prompt_embed_dim,
            iou_head_depth=3,
            iou_head_hidden_dim=256,
        ),
        pixel_mean=[123.675, 116.28, 103.53],
        pixel_std=[58.395, 57.12, 57.375],
    )


def _retain_prompt_components(mask: np.ndarray, positive_points):
    if not positive_points or not np.any(mask):
        return mask, []
    from scipy import ndimage

    labels, count = ndimage.label(mask > 0)
    if count <= 1:
        return mask, [1] if count else []
    retained = set()
    foreground = np.argwhere(labels > 0)
    for point in positive_points:
        point_tuple = tuple(int(value) for value in point)
        component = int(labels[point_tuple])
        if component <= 0 and foreground.size:
            nearest = foreground[np.argmin(np.sum((foreground - np.asarray(point)) ** 2, axis=1))]
            component = int(labels[tuple(nearest)])
        if component > 0:
            retained.add(component)
    if not retained:
        return np.zeros_like(mask, dtype=np.uint8), []
    return np.isin(labels, list(retained)).astype(np.uint8), sorted(retained)


def _explicit_roi_padding(shape, points, roi_size=128):
    """Return symmetric padding and prompt coordinates on the padded grid."""
    shape = tuple(int(value) for value in shape)
    before = [max((int(roi_size) - size) // 2, 0) for size in shape]
    after = [
        max(int(roi_size) - size - offset, 0)
        for size, offset in zip(shape, before)
    ]
    shifted = [
        [int(point[axis]) + before[axis] for axis in range(3)]
        for point in points
    ]
    return before, after, shifted


def main() -> int:
    args = _parse_args()
    started = time.perf_counter()
    root = Path(args.root).resolve()
    sys.path.insert(0, str(root))

    import SimpleITK as sitk
    import torch
    import torch.nn.functional as F
    import torchio as tio
    from networks.critic import Discriminator

    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("SAT3D requested CUDA but CUDA is unavailable")
    device = torch.device(args.device)
    sliding_window_inference = _load_sliding_window(root)

    model = _build_model(root).to(device)
    critic = Discriminator().to(device)
    model_state = torch.load(args.model, map_location=device, weights_only=False)
    critic_state = torch.load(args.critic, map_location=device, weights_only=False)
    # Fail closed on any topology/artifact mismatch. A partial load can still
    # emit a plausible-looking tensor and must never be accepted as a valid
    # candidate from the pinned model.
    model.load_state_dict(
        _remove_module_prefix(model_state["model_state_dict"]), strict=True
    )
    critic.load_state_dict(
        _remove_module_prefix(critic_state["model_state_dict"]), strict=True
    )
    model.eval()
    critic.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    for parameter in critic.parameters():
        parameter.requires_grad_(False)

    image = sitk.ReadImage(args.input)
    array = sitk.GetArrayFromImage(image).astype(np.float32, copy=False)
    finite = np.isfinite(array)
    foreground = finite & (array > 0)
    if not np.any(foreground):
        foreground = finite
    if not np.any(foreground):
        raise RuntimeError("SAT3D input contains no finite voxels")
    lo, hi = np.percentile(array[foreground], (0.5, 99.5))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        raise RuntimeError("SAT3D input has no usable intensity range")
    clipped = np.clip(np.nan_to_num(array, nan=float(lo)), lo, hi)
    tensor = torch.as_tensor(clipped[None, ...], dtype=torch.float32)
    scalar = tio.ScalarImage(tensor=tensor)
    normalised = tio.ZNormalization(masking_method=lambda x: x > 0)(scalar).data.unsqueeze(0)
    normalised = normalised.to(device, non_blocking=True)

    point_payload = json.loads(Path(args.points).read_text(encoding="utf-8"))
    positive = point_payload.get("positive") or []
    negative = point_payload.get("negative") or []
    all_points = positive + negative
    original_shape = tuple(int(value) for value in normalised.shape[2:])
    # The official custom sliding-window function pads volumes smaller than
    # 128^3 but does not shift global prompt coordinates by the padding
    # offset.  Thin CT/MRI series are common in BrachyBot, so a correct click
    # at z=5 could otherwise be embedded at padded z=5 while the image starts
    # near z=60.  Pad explicitly, shift only the model prompts, then crop the
    # logits back to the original grid.  The published model and official
    # sliding-window implementation remain unmodified.
    pad_before, pad_after, shifted_points = _explicit_roi_padding(
        original_shape,
        all_points,
        roi_size=128,
    )
    if any(pad_before) or any(pad_after):
        normalised = F.pad(
            normalised,
            (
                pad_before[2], pad_after[2],
                pad_before[1], pad_after[1],
                pad_before[0], pad_after[0],
            ),
            mode="constant",
            value=0.0,
        )
    points = None
    if all_points:
        points_t = torch.as_tensor(shifted_points, dtype=torch.int64, device=device).unsqueeze(0)
        labels_t = torch.as_tensor(
            [1] * len(positive) + [0] * len(negative),
            dtype=torch.int64,
            device=device,
        ).unsqueeze(0)
        points = [points_t, labels_t]

    low_res_mask = torch.zeros((1, 1, 32, 32, 32), dtype=torch.float32, device=device)
    with torch.inference_mode():
        # The critic is pointwise (1x1x1 convolutions), so evaluating the
        # 32^3 prompt grid is numerically equivalent to evaluating a full zero
        # volume and downsampling, while avoiding a very large temporary tensor.
        low_res_conf = torch.sigmoid(critic(torch.sigmoid(low_res_mask)))
        amp_context = (
            torch.amp.autocast("cuda")
            if device.type == "cuda"
            else torch.autocast("cpu", enabled=False)
        )
        with amp_context:
            logits = sliding_window_inference(
                inputs=normalised,
                roi_size=(128, 128, 128),
                sw_batch_size=1,
                predictor=model,
                points=points,
                low_res_prev_masks=low_res_mask,
                overlap=0.625,
                low_res_conf=low_res_conf,
            )
        probability = torch.sigmoid(logits[0, 0]).float().cpu().numpy()
    if any(pad_before) or any(pad_after):
        probability = probability[
            pad_before[0]:pad_before[0] + original_shape[0],
            pad_before[1]:pad_before[1] + original_shape[1],
            pad_before[2]:pad_before[2] + original_shape[2],
        ]
    mask = (probability > 0.5).astype(np.uint8)
    mask, retained_components = _retain_prompt_components(mask, positive)

    output = sitk.GetImageFromArray(mask)
    output.CopyInformation(image)
    sitk.WriteImage(output, args.output, True)
    metadata = {
        "voxel_count": int(mask.sum()),
        "shape_zyx": [int(value) for value in mask.shape],
        "positive_points": positive,
        "negative_points": negative,
        "model_points_after_padding": shifted_points,
        "explicit_padding_before_zyx": pad_before,
        "explicit_padding_after_zyx": pad_after,
        "prompt_mode": "point_guided" if all_points else "zero_prompt",
        "retained_components": retained_components,
        "threshold": 0.5,
        "roi_size": [128, 128, 128],
        "overlap": 0.625,
        "device": str(device),
        "elapsed_seconds": time.perf_counter() - started,
        "torch_version": torch.__version__,
    }
    Path(args.metadata).write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    if device.type == "cuda":
        torch.cuda.empty_cache()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
