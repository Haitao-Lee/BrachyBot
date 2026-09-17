"""Regression tests for seed/needle metrics read from real plan containers.

A completed case with 22 needles and 181 seeds answered ``粒子数量 22``:
``query_metrics(seed_count)`` received the optimizer's per-trajectory plan
entries (22 items) instead of flat seed records and counted the needles.
These tests pin the correct contract across every plan shape the workspace
can hold.
"""

import numpy as np

from agent_runtime.core import ToolResultPipeline
from tool_factory.viewer_command.query_metrics import QueryMetricsTool

NEEDLE_COUNTS = [8] * 21 + [13]  # 22 needles, 181 seeds


def _auto_plan(needle_counts):
    """Optimizer shape: [trajectory, seeds, per-seed dose maps]."""
    plan = []
    for index, count in enumerate(needle_counts):
        trajectory = ([0.0, 0.0, float(index)], [0.0, 0.0, float(index) + 1.0])
        seeds = [
            ((float(seed), 0.0, float(index)), (1.0, 0.0, 0.0))
            for seed in range(count)
        ]
        doses = [np.zeros((2, 2, 2), dtype=np.float32) for _ in range(count)]
        plan.append([trajectory, seeds, doses])
    return plan


def _serialized_plan(needle_counts):
    """Published shape: per-trajectory dicts with explicit seed records."""
    plan = []
    for index, count in enumerate(needle_counts):
        trajectory_id = f"traj_{index + 1}"
        plan.append(
            {
                "trajectory_id": trajectory_id,
                "needle_id": f"needle_{index}",
                "trajectory": {"id": trajectory_id, "points": []},
                "seeds": [
                    {
                        "id": f"seed_{index}_{seed}",
                        "position": [float(seed), 0.0, float(index)],
                        "direction": [1.0, 0.0, 0.0],
                        "trajectory_id": trajectory_id,
                    }
                    for seed in range(count)
                ],
                "num_seeds": count,
            }
        )
    return plan


def _flat_seed_records(needle_counts):
    """Manual-edit shape: flat {position, direction, trajectory_id} records."""
    records = []
    for index, count in enumerate(needle_counts):
        for seed in range(count):
            records.append(
                {
                    "id": f"seed_{index}_{seed}",
                    "position": [float(seed), 0.0, float(index)],
                    "direction": [1.0, 0.0, 0.0],
                    "trajectory_id": f"traj_{index + 1}",
                }
            )
    return records


def test_seed_count_counts_seeds_in_nested_optimizer_plan():
    tool = QueryMetricsTool()
    result = tool._execute(
        metric_type="seed_count",
        seed_positions=_auto_plan(NEEDLE_COUNTS),
        total_seeds=181,
    )

    assert result.success is True
    assert result.metadata["seed_count"] == 181
    assert result.metadata["seed_count"] != 22


def test_seed_count_prefers_published_serialized_plan_over_legacy_alias():
    tool = QueryMetricsTool()
    result = tool._execute(
        metric_type="seed_count",
        seed_positions=_auto_plan(NEEDLE_COUNTS),
        seed_plan_serialized=_serialized_plan(NEEDLE_COUNTS),
        total_seeds=181,
    )

    assert result.metadata["seed_count"] == 181


def test_seed_count_uses_memory_total_when_no_structured_plan_is_available():
    tool = QueryMetricsTool()
    result = tool._execute(
        metric_type="seed_count",
        seed_positions=[],
        total_seeds=181,
    )

    assert result.metadata["seed_count"] == 181


def test_seed_count_keeps_flat_numpy_and_zero_total_behavior():
    tool = QueryMetricsTool()
    flat = tool._execute(
        metric_type="seed_count",
        seed_positions=np.zeros((3, 3), dtype=np.float32),
        total_seeds=99,
    )
    empty = tool._execute(
        metric_type="seed_count",
        seed_positions=np.zeros((0, 3), dtype=np.float32),
        total_seeds=0,
    )

    assert flat.metadata["seed_count"] == 3
    assert empty.metadata["seed_count"] == 0


def test_needle_count_reports_trajectories_not_seeds():
    tool = QueryMetricsTool()
    result = tool._execute(
        metric_type="needle_count",
        seed_positions=_auto_plan(NEEDLE_COUNTS),
        total_seeds=181,
        num_trajectories=22,
    )

    assert result.success is True
    assert result.metadata["needle_count"] == 22


def test_needle_seed_counts_reports_per_needle_distribution():
    tool = QueryMetricsTool()
    result = tool._execute(
        metric_type="needle_seed_counts",
        seed_positions=_serialized_plan(NEEDLE_COUNTS),
        total_seeds=181,
        num_trajectories=22,
    )

    assert result.success is True
    data = result.data
    assert data["needle_count"] == 22
    assert data["total_seeds"] == 181
    assert [row["seed_count"] for row in data["per_needle"]] == NEEDLE_COUNTS
    assert data["per_needle"][0]["needle_id"] in {"traj_1", "needle_0"}
    assert result.metadata["response_contract"]["covers"] == [
        "needle_count",
        "seed_total",
        "seeds_per_needle",
    ]


def test_needle_seed_counts_accepts_manual_flat_records():
    tool = QueryMetricsTool()
    result = tool._execute(
        metric_type="needle_seed_counts",
        seed_positions=_flat_seed_records(NEEDLE_COUNTS),
        total_seeds=181,
        num_trajectories=22,
    )

    assert result.success is True
    assert result.data["needle_count"] == 22
    assert [row["seed_count"] for row in result.data["per_needle"]] == NEEDLE_COUNTS


def test_needle_seed_counts_falls_back_to_memory_totals_without_geometry():
    tool = QueryMetricsTool()
    result = tool._execute(
        metric_type="needle_seed_counts",
        seed_positions=[],
        total_seeds=181,
        num_trajectories=22,
    )

    assert result.success is True
    assert result.data["needle_count"] == 22
    assert result.data["total_seeds"] == 181
    assert result.data["per_needle"] == []


def test_seed_count_contract_declares_only_total_seed_coverage():
    tool = QueryMetricsTool()
    result = tool._execute(
        metric_type="seed_count",
        seed_positions=_auto_plan(NEEDLE_COUNTS),
        total_seeds=181,
    )

    assert result.metadata["response_contract"]["covers"] == ["seed_total"]


def test_needle_count_contract_declares_needle_coverage():
    tool = QueryMetricsTool()
    result = tool._execute(
        metric_type="needle_count",
        seed_positions=_auto_plan(NEEDLE_COUNTS),
        total_seeds=181,
        num_trajectories=22,
    )

    assert result.metadata["response_contract"]["covers"] == ["needle_count"]


def test_needle_seed_counts_renders_localized_distribution_table():
    tool = QueryMetricsTool()
    result = tool._execute(
        metric_type="needle_seed_counts",
        seed_positions=_serialized_plan(NEEDLE_COUNTS),
        total_seeds=181,
        num_trajectories=22,
    )

    rendered = ToolResultPipeline.format("query_metrics", result, "zh")

    assert "穿刺针" in rendered
    assert "181" in rendered
    assert "| 针道 | 粒子数 |" in rendered
    assert "| 针道 1 | 8 |" in rendered
    assert "| 针道 22 | 13 |" in rendered


def test_needle_count_renders_scalar_answer():
    tool = QueryMetricsTool()
    result = tool._execute(
        metric_type="needle_count",
        seed_positions=_auto_plan(NEEDLE_COUNTS),
        total_seeds=181,
        num_trajectories=22,
    )

    rendered = ToolResultPipeline.format("query_metrics", result, "zh")

    assert "穿刺针" in rendered
    assert "22" in rendered
