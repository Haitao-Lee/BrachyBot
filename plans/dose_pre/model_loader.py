"""Canonical myDoseNet checkpoint discovery and loading."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional, Tuple


_REPO_ROOT = Path(__file__).resolve().parents[2]

# The deployed myDoseNet checkpoint was trained in normalized dose units where
# 1.0 maps to 120 Gy. Alternate calibrated checkpoints may override this value
# explicitly; every backend and frontend response reads the same scale.
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
    candidates.append(Path(__file__).resolve().parent / "dose_model.pth")
    # Read-only compatibility for deployments created before dose_pre was
    # canonicalized under plans/. New installations should use the env var or
    # plans/dose_pre/dose_model.pth.
    candidates.append(_REPO_ROOT / "dose_pre" / "dose_model.pth")
    return next((path.resolve() for path in candidates if path.is_file()), None)


def load_dose_model(explicit_path: Optional[str] = None,
                    device: Any = "cpu", **model_kwargs) -> Tuple[Any, Optional[str], Optional[str]]:
    """Return (model, error, resolved_path) without silently fabricating dose."""
    path = resolve_dose_model_path(explicit_path)
    if path is None:
        return None, (
            "myDoseNet checkpoint not found. Set BRACHYBOT_DOSE_MODEL_PATH or "
            "install it at plans/dose_pre/dose_model.pth."
        ), None

    try:
        import torch
        from .myDoseNet import myDoseNet

        defaults = {
            "spatial_dims": 3,
            "in_channels": 3,
            "out_channels": 1,
            "features": (16, 32, 64, 128, 256, 32),
        }
        defaults.update(model_kwargs)
        model = myDoseNet(**defaults)
        try:
            state = torch.load(path, map_location=device, weights_only=True)
        except TypeError:
            # Compatibility with older, trusted local PyTorch releases.
            state = torch.load(path, map_location=device)
        model.load_state_dict(state)
        model.to(device)
        model.eval()
        return model, None, str(path)
    except Exception as exc:
        return None, f"Failed to load myDoseNet checkpoint {path}: {exc}", str(path)
