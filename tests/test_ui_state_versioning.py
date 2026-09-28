"""UI state version contract (audit defect F07).

A cached agent used to merge browser state with a shallow ``dict.update``,
so a deleted object, an old selection or a control the browser no longer
reports survived as a stale value.  Nothing ordered concurrent snapshots, so
a slower older write could overwrite a newer one.  The contract here is a
three-way distinction — full snapshot (``replace``), typed patch, and explicit
tombstone — validated by ``state_seq`` / ``browser_instance`` / ``plan_revision``.
"""

from __future__ import annotations

import pytest

from agent_runtime.core import UI_STATE_DELETE, AgentMemory


def _memory() -> AgentMemory:
    return AgentMemory("case-state-versioning")


# ---------------------------------------------------------------------------
# Full snapshot vs typed patch
# ---------------------------------------------------------------------------


def test_patch_keeps_existing_behaviour_for_partial_updates():
    """A one-key patch (e.g. `{"ct_path": ...}`) must keep working."""
    memory = _memory()
    memory.set_ui_state({"ct_path": "a.nii", "plan_mode": "auto"})

    memory.set_ui_state({"ct_path": "b.nii"})

    state = memory.get_ui_state()
    assert state["ct_path"] == "b.nii"
    assert state["plan_mode"] == "auto", "an unrelated key survives a patch"


def test_replace_drops_keys_the_browser_no_longer_reports():
    """A full snapshot is authoritative: absence means gone."""
    memory = _memory()
    memory.set_ui_state(
        {"ct_path": "a.nii", "selected_object": "seed_12", "stale_panel": "x"},
        mode="replace",
    )

    memory.set_ui_state({"ct_path": "a.nii"}, mode="replace")

    state = memory.get_ui_state()
    assert state == {"ct_path": "a.nii"}
    assert "selected_object" not in state, "an old selection must not linger"
    assert "stale_panel" not in state


def test_replace_install_the_payload_verbatim():
    memory = _memory()
    memory.set_ui_state({"viewer": {"axis": "axial", "zoom": 120}})

    memory.set_ui_state({"viewer": {"axis": "coronal"}}, mode="replace")

    assert memory.get_ui_state() == {"viewer": {"axis": "coronal"}}


# ---------------------------------------------------------------------------
# Tombstones: a deleted object disappears, it is not merely hidden
# ---------------------------------------------------------------------------


def test_delete_marker_removes_a_top_level_key():
    memory = _memory()
    memory.set_ui_state({"selection": "ctv_1", "viewer": {"a": 1}})

    memory.set_ui_state({"selection": UI_STATE_DELETE})

    state = memory.get_ui_state()
    assert "selection" not in state
    assert state["viewer"] == {"a": 1}


def test_tombstones_remove_nested_paths():
    memory = _memory()
    memory.set_ui_state({
        "viewer": {"selection": "needle_3", "zoom": 100},
        "planning": {"objects": ["a", "b"]},
    })

    memory.set_ui_state(
        {"viewer": {"zoom": 110}},
        tombstones=("viewer.selection", "planning.objects"),
    )

    state = memory.get_ui_state()
    assert state["viewer"] == {"zoom": 110}
    assert "objects" not in state["planning"]


def test_tombstone_on_a_missing_path_is_a_no_op():
    memory = _memory()
    memory.set_ui_state({"a": 1})

    memory.set_ui_state({}, tombstones=("never.there",))

    assert memory.get_ui_state() == {"a": 1}


def test_delete_marker_inside_replace_still_removes():
    memory = _memory()
    memory.set_ui_state({"keep": 1, "drop": 2})

    memory.set_ui_state({"keep": 1, "drop": UI_STATE_DELETE}, mode="replace")

    assert memory.get_ui_state() == {"keep": 1}


# ---------------------------------------------------------------------------
# state_seq / browser_instance / plan_revision
# ---------------------------------------------------------------------------


def test_newer_state_seq_is_applied_and_reported():
    memory = _memory()

    revision = memory.set_ui_state(
        {"v": 1}, state_seq=5, browser_instance="tab-a", plan_revision=3,
    )

    assert revision["accepted"] is True
    assert revision["state_seq"] == 5
    assert revision["plan_revision"] == 3
    assert revision["browser_instance"] == "tab-a"
    assert memory.get_ui_state()["v"] == 1


def test_older_state_seq_is_rejected_without_touching_the_state():
    """A slow older snapshot must not overwrite a newer one."""
    memory = _memory()
    memory.set_ui_state({"v": 2}, state_seq=9, browser_instance="tab-a")

    revision = memory.set_ui_state(
        {"v": 1}, state_seq=4, browser_instance="tab-a",
    )

    assert revision["accepted"] is False
    assert revision["reason"] == "stale_state_seq"
    assert revision["state_seq"] == 9, "the accepted sequence stays at the newest"
    assert memory.get_ui_state()["v"] == 2


def test_replayed_state_seq_is_rejected():
    memory = _memory()
    memory.set_ui_state({"v": 1}, state_seq=7, browser_instance="tab-a")

    revision = memory.set_ui_state({"v": 9}, state_seq=7, browser_instance="tab-a")

    assert revision["accepted"] is False
    assert memory.get_ui_state()["v"] == 1


def test_state_without_a_sequence_is_still_accepted_for_legacy_callers():
    memory = _memory()

    revision = memory.set_ui_state({"v": 1})

    assert revision["accepted"] is True
    assert revision["state_seq"] is None


def test_different_browser_instances_do_not_share_a_sequence():
    memory = _memory()
    memory.set_ui_state({"tab": "a"}, state_seq=3, browser_instance="tab-a")

    revision = memory.set_ui_state({"tab": "b"}, state_seq=1, browser_instance="tab-b")

    assert revision["accepted"] is True
    assert memory.get_ui_state()["tab"] == "b"


def test_a_case_switch_does_not_inherit_the_previous_sequence():
    memory = _memory()
    memory.set_ui_state({"v": 1}, state_seq=50, browser_instance="tab-a")

    memory.reset_ui_state_for_case_switch()
    revision = memory.set_ui_state({"v": 2}, state_seq=1, browser_instance="tab-a")

    assert revision["accepted"] is True
    assert memory.get_ui_state() == {"v": 2}


def test_plan_revision_is_recorded_on_the_accepted_write():
    memory = _memory()
    memory.set_ui_state({"v": 1}, state_seq=1, plan_revision=4, browser_instance="t")

    assert memory.get_ui_state_revision()["plan_revision"] == 4


def test_rejected_write_does_not_advance_plan_revision():
    memory = _memory()
    memory.set_ui_state({"v": 1}, state_seq=5, plan_revision=4, browser_instance="t")

    memory.set_ui_state({"v": 2}, state_seq=2, plan_revision=9, browser_instance="t")

    assert memory.get_ui_state_revision()["plan_revision"] == 4


def test_get_ui_state_returns_a_copy_that_cannot_mutate_the_store():
    memory = _memory()
    memory.set_ui_state({"viewer": {"a": 1}})

    snapshot = memory.get_ui_state()
    snapshot["viewer"]["a"] = 99
    snapshot["injected"] = True

    assert memory.get_ui_state() == {"viewer": {"a": 1}}
