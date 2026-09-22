"""dose_evaluation must receive one grid-consistent, Gy-scaled workspace tuple.

Regression: the memory injection paired the stale planning-grid
``dose_distribution`` alias (64, 128, 128) with CT-grid masks (57, 512, 512).
``dose_evaluation`` then failed with "ctv_mask shape must match dose_array" in
0.00s and the chat surface reported "planning not completed" for a case whose
planning had long been finished.
"""

import numpy as np
import pytest

from AgenticSys import BrachyAgent
from agent_runtime.contracts import RunLedger, ToolCallGateway
from agent_runtime.core import ToolRegistry
from plans.dose_pre.evaluation_inputs import (
    MISSING_INPUT_ERROR,
    resolve_dose_evaluation_inputs,
)
from tool_factory.dose_eval import DoseEvaluationTool


def _retrieve(mapping):
    def retrieve(key, default=None):
        return mapping.get(key, default)
    return retrieve


def _ct_grid_case():
    dose_norm = np.zeros((2, 4, 4), dtype=np.float32)
    dose_norm[:, :2, :] = 130.0 / 190.8  # 130 Gy on half the grid
    ctv = np.zeros((2, 4, 4), dtype=np.uint8)
    ctv[:, :, :2] = 1  # first two columns are CTV (8 voxels)
    oar = np.zeros((2, 4, 4), dtype=np.uint16)
    oar[:, :, 2:] = 3
    return {
        # Stale planning-grid alias: must NOT be paired with CT-grid masks.
        "dose_distribution": np.zeros((2, 8, 8), dtype=np.float32),
        # Normalized model output on the CT grid (despite the key name).
        "dose_distribution_gy": dose_norm,
        "ctv_array": ctv,
        "oar_array": oar,
        "dose_scale_gy": 190.8,
        "metrics": {"prescription_gy": 120.0, "dose_scale_gy": 190.8},
        "ct_spacing": [0.5, 0.5, 5.0],
        "organ_names": {3: "Bladder"},
    }


def test_pairs_ct_grid_masks_with_the_normalized_dose_scaled_to_gy():
    memory = _ct_grid_case()
    resolved = resolve_dose_evaluation_inputs(_retrieve(memory))
    assert resolved["resolution_error"] is None
    params = resolved["params"]
    dose = params["dose_array"]
    assert dose.shape == memory["ctv_array"].shape
    assert float(dose.max()) == pytest.approx(130.0)
    assert float(dose.min()) == pytest.approx(0.0)
    assert params["ctv_mask"] is memory["ctv_array"]
    assert params["oar_mask"] is memory["oar_array"]
    assert params["prescribed_dose"] == pytest.approx(120.0)
    assert params["spacing"] == [0.5, 0.5, 5.0]
    assert params["organ_names"] == {3: "Bladder"}


def test_physical_gy_grid_is_used_unchanged():
    memory = _ct_grid_case()
    dose_gy = memory["dose_distribution_gy"] * 190.8
    memory.pop("dose_distribution_gy")
    memory["dose_distribution_physical_gy"] = dose_gy
    resolved = resolve_dose_evaluation_inputs(_retrieve(memory))
    assert resolved["resolution_error"] is None
    dose = resolved["params"]["dose_array"]
    assert float(dose.max()) == pytest.approx(130.0, rel=1e-5)


def test_planning_grid_pair_uses_the_resampled_masks():
    memory = {
        "dose_distribution": np.zeros((2, 8, 8), dtype=np.float32),
        "dose_distribution_gy": np.zeros((2, 4, 4), dtype=np.float32),
        "ctv_array": np.zeros((2, 4, 4), dtype=np.uint8),  # CT grid: no dose match below
        "resampled_ctv": np.ones((2, 8, 8), dtype=np.uint8),
        "dose_scale_gy": 2.0,
        "metrics": {"prescription_gy": 120.0},
    }
    # Make the CT-grid candidate shapes disagree so the planning-grid pair wins
    # through its own dose candidates.
    memory["dose_distribution_gy"] = np.zeros((3, 3, 3), dtype=np.float32)
    memory["dose_distribution"] = np.full((2, 8, 8), 3.0, dtype=np.float32)
    resolved = resolve_dose_evaluation_inputs(_retrieve(memory))
    assert resolved["resolution_error"] is None
    params = resolved["params"]
    assert params["ctv_mask"] is memory["resampled_ctv"]
    assert params["dose_array"].shape == (2, 8, 8)
    assert float(params["dose_array"].max()) == pytest.approx(6.0)


def test_grid_mismatch_is_an_honest_error():
    memory = _ct_grid_case()
    memory["dose_distribution"] = np.zeros((2, 8, 8), dtype=np.float32)
    memory.pop("dose_distribution_gy")
    resolved = resolve_dose_evaluation_inputs(_retrieve(memory))
    assert resolved["params"] == {}
    assert "grids do not match" in resolved["resolution_error"]


def test_missing_inputs_are_an_honest_error():
    resolved = resolve_dose_evaluation_inputs(_retrieve({}))
    assert resolved["params"] == {}
    assert resolved["resolution_error"] == MISSING_INPUT_ERROR
    assert "required" in resolved["resolution_error"]


def test_resolved_inputs_satisfy_the_dose_evaluation_tool():
    memory = _ct_grid_case()
    resolved = resolve_dose_evaluation_inputs(_retrieve(memory))
    result = DoseEvaluationTool().execute(**resolved["params"])
    assert result.success is True, result.error
    # CTV voxels sit on the first two columns: half of them receive 130 Gy
    # (>= 120 Gy prescription), the other half receive 0 Gy.
    assert result.metadata["v100"] == pytest.approx(0.5)
    assert "CTV" in result.data


class _Memory:
    def __init__(self, values):
        self.values = values
        self.conversation_state = {"last_tool_calls": []}
        self.logged = []

    def retrieve(self, key, default=None):
        return self.values.get(key, default)

    def get_ui_state(self):
        return {}

    def store(self, key, value):
        self.values[key] = value

    def log_tool_call(self, *args):
        self.logged.append(args)


def test_agent_injection_replaces_model_supplied_arrays_with_the_workspace_tuple():
    memory = _Memory(_ct_grid_case())
    registry = ToolRegistry()
    registry.register(DoseEvaluationTool())
    agent = object.__new__(BrachyAgent)
    agent.memory = memory
    agent.registry = registry
    agent.run_ledger = RunLedger()
    agent.tool_gateway = ToolCallGateway(agent.run_ledger)

    params = {
        "dose_array": "array([...])",
        "ctv_mask": "array([...])",
        "oar_mask": None,
    }
    result = agent._execute_tool_with_memory("dose_evaluation", params)

    assert result.success is True, result.error
    assert isinstance(params["dose_array"], np.ndarray)
    assert params["dose_array"].shape == (2, 4, 4)
    assert isinstance(params["ctv_mask"], np.ndarray)
    assert isinstance(params.get("oar_mask"), np.ndarray)
    assert params["prescribed_dose"] == pytest.approx(120.0)
    assert result.metadata["v100"] == pytest.approx(0.5)


def test_agent_injection_reports_a_grid_mismatch_without_blaming_planning():
    from utils.user_errors import format_tool_error

    values = _ct_grid_case()
    values.pop("dose_distribution_gy")
    values["dose_distribution"] = np.zeros((2, 8, 8), dtype=np.float32)
    memory = _Memory(values)
    registry = ToolRegistry()
    registry.register(DoseEvaluationTool())
    agent = object.__new__(BrachyAgent)
    agent.memory = memory
    agent.registry = registry
    agent.run_ledger = RunLedger()
    agent.tool_gateway = ToolCallGateway(agent.run_ledger)

    result = agent._execute_tool_with_memory("dose_evaluation", {})
    assert result.success is False
    assert "grids do not match" in result.error
    message = format_tool_error("dose_evaluation", result.error, {}, "zh")
    assert "规划没有完成" not in message
    assert "网格" in message
