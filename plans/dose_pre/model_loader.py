"""Load the canonical spacing-normalized DoseUNet checkpoint."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional, Tuple


_REPO_ROOT = Path(__file__).resolve().parents[2]
DOSE_MODEL_NAME = "dose_unet_spacing1mm"
DOSE_MODEL_RELATIVE_PATH = Path("models") / DOSE_MODEL_NAME / "best_model.pth"

# The planning pipeline keeps this display calibration for legacy report fields.
# The DoseUNet checkpoint itself stores its physical-output multiplier in the
# checkpoint metadata and the inference adapter applies that value.
try:
    DOSE_MODEL_SCALE_GY = float(os.environ.get("BRACHYBOT_DOSE_MODEL_SCALE_GY", "120.0"))
except ValueError as exc:  # Fail during startup instead of displaying wrong Gy.
    raise ValueError("BRACHYBOT_DOSE_MODEL_SCALE_GY must be numeric") from exc
if not DOSE_MODEL_SCALE_GY > 0:
    raise ValueError("BRACHYBOT_DOSE_MODEL_SCALE_GY must be greater than zero")


def resolve_dose_model_path(explicit_path: Optional[str] = None) -> Optional[Path]:
    candidates = []
    env_path = os.environ.get("BRACHYBOT_DOSE_MODEL_PATH")
    for raw_path in (explicit_path, env_path):
        if raw_path:
            path = Path(raw_path).expanduser()
            candidates.append(path if path.is_absolute() else _REPO_ROOT / path)
    candidates.append(_REPO_ROOT / DOSE_MODEL_RELATIVE_PATH)
    return next((path.resolve() for path in candidates if path.is_file()), None)


def load_dose_model(explicit_path: Optional[str] = None,
                    device: Any = "cpu", **model_kwargs) -> Tuple[Any, Optional[str], Optional[str]]:
    """Return (model, error, resolved_path) without silently fabricating dose."""
    path = resolve_dose_model_path(explicit_path)
    if path is None:
        return None, (
            f"{DOSE_MODEL_NAME} checkpoint not found. Set BRACHYBOT_DOSE_MODEL_PATH or "
            f"install it at {_REPO_ROOT / DOSE_MODEL_RELATIVE_PATH}."
        ), None

    try:
        import torch
        try:
            checkpoint = torch.load(path, map_location=device, weights_only=False)
        except TypeError:
            # Compatibility with trusted local PyTorch releases without the
            # weights_only keyword. The deployed checkpoint is a metadata dict.
            checkpoint = torch.load(path, map_location=device)

        if not isinstance(checkpoint, dict) or "model_state_dict" not in checkpoint:
            raise ValueError(
                f"{DOSE_MODEL_NAME} checkpoint must contain model_state_dict metadata"
            )

        channel_order = tuple(checkpoint.get("channel_order", ()))
        expected_channels = ("line_map", "ct", "soft_pos")
        if channel_order != expected_channels:
            raise ValueError(
                f"Unsupported {DOSE_MODEL_NAME} channel_order={channel_order}; "
                f"expected {expected_channels}"
            )
        target_spacing = checkpoint.get("target_spacing")
        if target_spacing is None:
            args = checkpoint.get("args") or {}
            target_spacing = args.get("target_spacing") if isinstance(args, dict) else None
        if target_spacing is None or len(target_spacing) != 3:
            raise ValueError(
                f"{DOSE_MODEL_NAME} checkpoint is missing its 3-axis target_spacing"
            )
        dose_multiplier = checkpoint.get("dose_multiplier")
        if dose_multiplier is None:
            args = checkpoint.get("args") or {}
            dose_multiplier = args.get("dose_multiplier") if isinstance(args, dict) else None
        if dose_multiplier is None or float(dose_multiplier) <= 0:
            raise ValueError(
                f"{DOSE_MODEL_NAME} checkpoint is missing a positive dose_multiplier"
            )

        from .dose_unet import DoseUNet

        # Architecture is part of the deployed checkpoint contract. Ignore
        # legacy caller kwargs so an old six-width network cannot be selected.
        model = DoseUNet(in_channels=3, out_channels=1)
        model.load_state_dict(checkpoint["model_state_dict"])
        args = checkpoint.get("args") or {}
        patch_size = args.get("patch_size", (64, 64, 64)) if isinstance(args, dict) else (64, 64, 64)
        model._brachybot_dose_contract = {
            "name": DOSE_MODEL_NAME,
            "channel_order": expected_channels,
            "target_spacing": tuple(float(value) for value in target_spacing),
            "dose_multiplier": float(dose_multiplier),
            "patch_size": tuple(int(value) for value in patch_size),
            "overlap": 0.5,
            "output_size_cm": 12.0,
            "line_length": 4.5,
            "seed_soft_radius": 4.0,
        }
        model.to(device)
        model.eval()
        return model, None, str(path)
    except Exception as exc:
        return None, f"Failed to load {DOSE_MODEL_NAME} checkpoint {path}: {exc}", str(path)


__all__ = [
    "DOSE_MODEL_NAME",
    "DOSE_MODEL_RELATIVE_PATH",
    "DOSE_MODEL_SCALE_GY",
    "load_dose_model",
    "resolve_dose_model_path",
]
