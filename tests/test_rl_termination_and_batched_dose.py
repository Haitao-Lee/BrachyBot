"""Regression tests for bounded RL action loops and batched DoseUNet inference."""

import sys
import time
import unittest
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import SimpleITK as sitk
    import torch
except ImportError as exc:  # pragma: no cover - controlled by deployment image.
    raise unittest.SkipTest("SimpleITK and torch are required for dose inference tests") from exc

from plans.dose_pre.inference import (
    DoseInferenceDeadlineExceeded,
    predict_seed_dose,
    predict_seed_doses,
    sliding_window_predict_batch,
)
try:
    from plans.reinforcement import LowLevelEnv
except ModuleNotFoundError:  # pragma: no cover - optional RL runtime dependency.
    LowLevelEnv = None


class _IdentityDoseModel(torch.nn.Module):
    """Tiny deterministic model that validates inference batching semantics."""

    def __init__(self):
        super().__init__()
        self.scale = torch.nn.Parameter(torch.tensor(1.0))
        self._brachybot_dose_contract = {
            "name": "test-dose-unet",
            "target_spacing": (1.0, 1.0, 1.0),
            "dose_multiplier": 1.0,
            "planning_output_scale": 1.0,
            "patch_size": (8, 8, 8),
            "overlap": 0.5,
            "output_size_cm": 1.6,
            "line_length": 4.5,
            "seed_soft_radius": 4.0,
            "inference_batch_size": 2,
        }

    def forward(self, values):
        return values[:, :1] * self.scale


class RlTerminationAndDoseBatchTests(unittest.TestCase):
    @unittest.skipIf(LowLevelEnv is None, "gymnasium is required for RL environment tests")
    def test_low_level_environment_ends_after_the_configured_action_budget(self):
        env = LowLevelEnv([0, 1, 2, 3], max_steps=2)
        env.reset()

        _, done, _ = env.step(0)
        self.assertFalse(done)
        _, done, _ = env.step(1)
        self.assertTrue(done)
        self.assertFalse(env.used_mask[0])
        self.assertFalse(env.used_mask[1])

    def test_batched_seed_inference_matches_single_seed_inference(self):
        image = sitk.GetImageFromArray(np.linspace(-1000, 500, 20 ** 3, dtype=np.float32).reshape(20, 20, 20))
        image.SetSpacing((1.0, 1.0, 1.0))
        image.SetOrigin((0.0, 0.0, 0.0))
        model = _IdentityDoseModel().eval()
        direction = (1.0, 0.0, 0.0)
        particles = [((8.0, 9.0, 10.0), direction, 1.0), ((12.0, 10.0, 9.0), direction, 0.75)]

        expected = [
            predict_seed_dose(position, direction, image, model, weight)
            for position, direction, weight in particles
        ]
        actual = predict_seed_doses(particles, image, model)

        self.assertEqual(len(actual), len(expected))
        for observed, reference in zip(actual, expected):
            np.testing.assert_allclose(observed, reference, rtol=1e-6, atol=1e-6)

    def test_expired_deadline_stops_before_another_dose_window(self):
        model = _IdentityDoseModel().eval()
        inputs = np.ones((2, 3, 8, 8, 8), dtype=np.float32)

        with self.assertRaises(DoseInferenceDeadlineExceeded):
            sliding_window_predict_batch(
                model,
                inputs,
                patch_size=(8, 8, 8),
                overlap=0.5,
                device=torch.device("cpu"),
                deadline=time.monotonic() - 1.0,
            )


if __name__ == "__main__":
    unittest.main()
