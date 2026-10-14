"""Timepoint persistence negative controls; all data is synthetic."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

from web.timepoints import (
    TimepointConflict, TimepointDependencyConflict, TimepointError,
    TimepointIntegrityError, default_timepoint_id,
)
from web.workspace_store import INLINE_ARRAY_MAX_BYTES, WorkspaceNotFound, WorkspaceStore


@pytest.fixture
def owned(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACHYBOT_ARCHIVE_ROOT", str(tmp_path / "archive"))
    store = WorkspaceStore(tmp_path / "runtime")
    user = store.create_user("timepoint_user", "synthetic-password-hash")
    session = store.create_session(user["id"], "Synthetic patient")
    return store, user["id"], session.id


def create(store, user, session, name="Scan", **kwargs):
    current = store.list_timepoints(user, session)
    result = store.create_timepoint(user, session, name,
                                   expected_revision=current["catalog_revision"], **kwargs)
    return result["created_timepoint_id"]


def update(store, user, session, identifier, patch):
    return store.update_timepoint(user, session, identifier, patch,
                                  expected_revision=store.list_timepoints(user, session)["catalog_revision"])


def test_presentation_only_save_does_not_make_an_empty_timepoint_clinically_populated(owned):
    store,user,sid=owned
    source=create(store,user,sid,'Preoperative source')
    target=create(store,user,sid,'Empty current workspace')
    store.save_timepoint_patch(user,sid,target,{'ui':{'state':{'viewer':{'window':400}}}},expected_state_revision=0)
    before=store.load_timepoint_snapshot(user,sid,target)
    assert before['timepoint_state_revision']>0 and before['timepoint_clinical_revision']==0
    update(store,user,sid,target,{'stage':'intraoperative','preoperative_timepoint_id':source})
    after=store.load_timepoint_snapshot(user,sid,target)
    assert after['timepoint']['stage']=='intraoperative'
    assert after['timepoint']['lifecycle_revision']>before['timepoint']['lifecycle_revision']
    assert after['ui']['state']['viewer']['window']==400
    assert after['timepoint_clinical_revision']==0
    store.save_timepoint_results(user,sid,target,{'ct_data':np.zeros((3,3,3),np.int16)},expected_clinical_revision=0)
    with pytest.raises(TimepointConflict,match='explicit migration'):
        update(store,user,sid,target,{'stage':'preoperative','preoperative_timepoint_id':None})


def test_default_catalog_is_stable_read_only_and_preserves_schema_one(owned):
    store, user, sid = owned
    before = store.load_snapshot(user, sid)
    first = store.list_timepoints(user, sid)
    second = store.list_timepoints(user, sid)
    assert first == second
    assert first["default_timepoint_id"] == default_timepoint_id(sid)
    assert first["capabilities"]["execution_scope"] is False
    assert store.load_snapshot(user, sid) == before
    assert not (store.workspace_root(user, sid) / "timepoints").exists()


def test_intraoperative_requires_owned_preoperative_source(owned):
    store, user, sid = owned
    source = create(store, user, sid, "Preoperative source")
    intra = create(store, user, sid, "During implantation", stage="intraoperative",
                   preoperative_timepoint_id=source)
    assert store.list_timepoints(user, sid)["items"][intra]["preoperative_timepoint_id"] == source
    with pytest.raises(TimepointError):
        create(store, user, sid, stage="intraoperative")
    with pytest.raises(TimepointError):
        create(store, user, sid, stage="intraoperative", preoperative_timepoint_id="f" * 32)
    with pytest.raises(TimepointError):
        create(store, user, sid, stage="intraoperative", preoperative_timepoint_id=intra)


@pytest.mark.parametrize("value", [True, -1, 1.0, "0", None])
def test_revisions_are_typed_and_fail_closed(owned, value):
    store, user, sid = owned
    with pytest.raises(TimepointError):
        store.create_timepoint(user, sid, "Scan", expected_revision=value)


@pytest.mark.parametrize("name", ["", " ", "x" * 161, "line\nbreak", None, 123])
def test_title_validation(owned, name):
    store, user, sid = owned
    with pytest.raises(TimepointError):
        create(store, user, sid, name)


def test_names_are_not_identities_and_rename_retains_links(owned):
    store, user, sid = owned
    source = create(store, user, sid, "Same file.nii.gz")
    other = create(store, user, sid, "Same file.nii.gz")
    intra = create(store, user, sid, stage="intraoperative", preoperative_timepoint_id=source)
    assert source != other
    update(store, user, sid, source, {"title": "Renamed source"})
    assert store.list_timepoints(user, sid)["items"][intra]["preoperative_timepoint_id"] == source


def test_cross_session_and_cross_owner_references_are_rejected(owned):
    store, user, sid = owned
    other_session = store.create_session(user, "Other patient")
    foreign_id = create(store, user, other_session.id)
    with pytest.raises(TimepointError):
        create(store, user, sid, stage="intraoperative", preoperative_timepoint_id=foreign_id)
    other_user = store.create_user("other_owner", "synthetic-password-hash")
    with pytest.raises(WorkspaceNotFound):
        store.list_timepoints(other_user["id"], sid)


def test_catalog_stale_write_does_not_replace_newer_record(owned):
    store, user, sid = owned
    before = store.list_timepoints(user, sid)
    identifier = create(store, user, sid)
    with pytest.raises(TimepointConflict):
        store.update_timepoint(user, sid, identifier, {"title": "Stale"},
                               expected_revision=before["catalog_revision"])
    assert store.list_timepoints(user, sid)["items"][identifier]["title"] == "Scan"


def test_two_store_instances_have_a_real_database_cas(owned):
    store, user, sid = owned
    other = WorkspaceStore(store.runtime_dir)
    def contender(target, name):
        try:
            target.create_timepoint(user, sid, name, expected_revision=0)
            return "published"
        except TimepointConflict:
            return "conflict"
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda args: contender(*args), [(store, "A"), (other, "B")]))
    assert sorted(results) == ["conflict", "published"]
    assert len(store.list_timepoints(user, sid)["timepoints"]) == 2


def test_sequence_cycle_and_different_sources_are_rejected(owned):
    store, user, sid = owned
    source = create(store, user, sid)
    a = create(store, user, sid, stage="intraoperative", preoperative_timepoint_id=source)
    b = create(store, user, sid, stage="intraoperative", preoperative_timepoint_id=source)
    update(store, user, sid, a, {"previous_intraoperative_timepoint_id": b})
    with pytest.raises(TimepointError):
        update(store, user, sid, b, {"previous_intraoperative_timepoint_id": a})
    different_source = create(store, user, sid)
    c = create(store, user, sid, stage="intraoperative", preoperative_timepoint_id=different_source)
    with pytest.raises(TimepointError):
        update(store, user, sid, c, {"previous_intraoperative_timepoint_id": a})


def test_shared_conversation_is_not_overwritten_by_timepoint_state(owned):
    store, user, sid = owned
    store.save_snapshot_patch(user, sid, {"chat": {"messages": [{"id": "m1", "role": "user", "content": "shared"}]}})
    identifier = create(store, user, sid)
    state = store.load_timepoint_snapshot(user, sid, identifier)
    assert state["chat"]["messages"][0]["content"] == "shared"
    with pytest.raises(TimepointError):
        store.save_timepoint_patch(user, sid, identifier, {"chat": {"messages": []}}, expected_state_revision=0)
    store.save_timepoint_patch(user, sid, identifier, {"ui": {"state": {"color": "#22D3EE"}}}, expected_state_revision=0)
    assert store.load_snapshot(user, sid)["chat"]["messages"][0]["content"] == "shared"


def test_independent_state_and_presentation_survive_restart(owned):
    store, user, sid = owned
    a, b = create(store, user, sid), create(store, user, sid)
    for identifier, color in [(a, "#22D3EE"), (b, "#FBBF24")]:
        store.save_timepoint_patch(user, sid, identifier, {
            "ui": {"state": {"viewer": {"opacity": 0.37, "color": color}}},
        }, expected_state_revision=0)
    restarted = WorkspaceStore(store.runtime_dir)
    for identifier, color in [(a, "#22D3EE"), (b, "#FBBF24")]:
        state = restarted.load_timepoint_snapshot(user, sid, identifier)
        assert state["ui"]["state"]["viewer"] == {"opacity": 0.37, "color": color}
        assert state["timepoint_state_revision"] == 1


def test_stale_state_and_unsupported_browser_sections_are_rejected(owned):
    store, user, sid = owned
    identifier = create(store, user, sid)
    store.save_timepoint_patch(user, sid, identifier, {"ui": {"color": "cyan"}}, expected_state_revision=0)
    with pytest.raises(TimepointConflict):
        store.save_timepoint_patch(user, sid, identifier, {"ui": {"color": "red"}}, expected_state_revision=0)
    with pytest.raises(TimepointError):
        store.save_timepoint_patch(user, sid, identifier, {"agent": {"planning_results": {}}}, expected_state_revision=1)


def test_default_projection_remains_live_and_uses_session_revision(owned):
    store, user, sid = owned
    default = default_timepoint_id(sid)
    current = store.load_timepoint_snapshot(user, sid, default)
    store.save_timepoint_patch(user, sid, default, {"ui": {"mode": "updated"}},
                               expected_state_revision=current["timepoint_state_revision"])
    assert store.load_snapshot(user, sid)["ui"]["mode"] == "updated"
    assert store.load_timepoint_snapshot(user, sid, default)["ui"]["mode"] == "updated"


def test_numerical_arrays_are_scoped_and_retained_across_default_checkpoint(owned):
    from test_workspace_store import _Agent
    store, user, sid = owned
    a, b = create(store, user, sid), create(store, user, sid)
    count = max(65536, INLINE_ARRAY_MAX_BYTES // 4 + 128)
    for identifier, value in [(a, 1.0), (b, 2.0)]:
        store.save_timepoint_results(user, sid, identifier,
                                    {"dose_distribution_gy": np.full(count, value, dtype=np.float32)},
                                    expected_state_revision=0)
    refs = store.timepoint_array_references(user, sid)
    assert len(refs) == 2
    store.snapshot_agent(user, sid, _Agent())
    assert all((store.workspace_root(user, sid) / relative).is_file() for relative in refs)
    for identifier, value in [(a, 1.0), (b, 2.0)]:
        state = store.load_timepoint_snapshot(user, sid, identifier, decode_arrays=True)
        assert np.all(state["agent"]["planning_results"]["dose_distribution_gy"] == value)


def test_history_and_trash_keep_array_references(owned):
    store, user, sid = owned
    identifier = create(store, user, sid)
    count = max(65536, INLINE_ARRAY_MAX_BYTES // 4 + 128)
    store.save_timepoint_results(user, sid, identifier, {"dose": np.ones(count)}, expected_state_revision=0)
    old = store.timepoint_array_references(user, sid)
    store.save_timepoint_results(user, sid, identifier, {"dose": np.zeros(count)}, expected_state_revision=1)
    refs = store.timepoint_array_references(user, sid)
    assert old < refs
    store.delete_timepoint(user, sid, identifier,
                           expected_revision=store.list_timepoints(user, sid)["catalog_revision"])
    assert store.timepoint_array_references(user, sid) == refs
    store.restore_timepoint(user, sid, identifier,
                            expected_revision=store.list_timepoints(user, sid)["catalog_revision"])
    assert np.all(store.load_timepoint_snapshot(user, sid, identifier, decode_arrays=True)["agent"]["planning_results"]["dose"] == 0)


def test_public_catalog_does_not_serialize_clinical_payloads(owned):
    store, user, sid = owned
    identifier = create(store, user, sid)
    store.save_timepoint_results(user, sid, identifier, {"large_private_result": np.ones(100)}, expected_state_revision=0)
    result = store.list_timepoints(user, sid)
    assert "state_ref" not in result["items"][identifier]
    assert "state_history" not in result["items"][identifier]
    assert "large_private_result" not in repr(result)


def test_failed_publication_does_not_make_partial_state_current(owned, monkeypatch):
    store, user, sid = owned
    identifier = create(store, user, sid)
    store.save_timepoint_patch(user, sid, identifier, {"ui": {"color": "cyan"}}, expected_state_revision=0)
    real = store._publish_timepoint_catalog
    def fail(*args, **kwargs):
        raise OSError("synthetic crash before metadata publication")
    monkeypatch.setattr(store, "_publish_timepoint_catalog", fail)
    with pytest.raises(OSError):
        store.save_timepoint_patch(user, sid, identifier, {"ui": {"color": "red"}}, expected_state_revision=1)
    monkeypatch.setattr(store, "_publish_timepoint_catalog", real)
    state = store.load_timepoint_snapshot(user, sid, identifier)
    assert state["ui"]["color"] == "cyan"
    assert state["timepoint_state_revision"] == 1


def test_state_checksum_failure_is_not_treated_as_empty_case(owned):
    store, user, sid = owned
    identifier = create(store, user, sid)
    store.save_timepoint_patch(user, sid, identifier, {"ui": {"color": "cyan"}}, expected_state_revision=0)
    ref = store._timepoint_catalog(user, sid)["items"][identifier]["state_ref"]
    (store.workspace_root(user, sid) / ref["path"]).write_bytes(b"{}")
    with pytest.raises(TimepointIntegrityError):
        store.load_timepoint_snapshot(user, sid, identifier)


def test_deletion_impact_blocks_referenced_sources_and_preserves_identity(owned):
    store, user, sid = owned
    source = create(store, user, sid)
    dependent = create(store, user, sid, stage="intraoperative", preoperative_timepoint_id=source)
    impact = store.timepoint_delete_impact(user, sid, source)
    assert impact["dependents"] == [dependent]
    with pytest.raises(TimepointDependencyConflict):
        store.delete_timepoint(user, sid, source,
                               expected_revision=store.list_timepoints(user, sid)["catalog_revision"])
    store.delete_timepoint(user, sid, dependent,
                           expected_revision=store.list_timepoints(user, sid)["catalog_revision"])
    store.restore_timepoint(user, sid, dependent,
                            expected_revision=store.list_timepoints(user, sid)["catalog_revision"])
    assert store.list_timepoints(user, sid)["items"][dependent]["preoperative_timepoint_id"] == source


def test_unknown_identity_and_legacy_deletion_fail_closed(owned):
    store, user, sid = owned
    with pytest.raises(TimepointError):
        store.load_timepoint_snapshot(user, sid, "../../other")
    with pytest.raises(TimepointConflict):
        store.delete_timepoint(user, sid, default_timepoint_id(sid), expected_revision=0)


def test_presentation_saves_do_not_consume_clinical_history(owned):
    store, user, sid = owned
    identifier = create(store, user, sid)
    for index in range(5):
        store.save_timepoint_patch(user, sid, identifier, {"ui": {"opacity": index / 5}}, expected_state_revision=index)
    assert store._timepoint_catalog(user, sid)["items"][identifier]["state_history"] == []


def test_presentation_edits_do_not_prevent_captured_clinical_commit(owned):
    store, user, sid = owned
    identifier = create(store, user, sid)
    captured = store.load_timepoint_snapshot(user, sid, identifier)["timepoint_clinical_revision"]
    store.save_timepoint_patch(user, sid, identifier, {"ui": {"opacity": 0.37}}, expected_state_revision=0)
    state = store.save_timepoint_results(user, sid, identifier, {"metrics": {"v100": 90.1}},
                                         expected_clinical_revision=captured)
    assert state["ui"]["opacity"] == 0.37
    assert state["timepoint_clinical_revision"] == captured + 1
    with pytest.raises(TimepointConflict):
        store.save_timepoint_results(user, sid, identifier, {"metrics": {"v100": 10}},
                                      expected_clinical_revision=captured)


def test_independent_store_state_saves_merge_without_lost_updates(owned, monkeypatch):
    import threading
    store, user, sid = owned
    a, b = create(store, user, sid), create(store, user, sid)
    other = WorkspaceStore(store.runtime_dir)
    barrier = threading.Barrier(2)
    for target in (store, other):
        original = target._publish_timepoint_catalog
        attempts = [0]
        def publish(*args, _original=original, _attempts=attempts, **kwargs):
            _attempts[0] += 1
            if _attempts[0] == 1:
                barrier.wait(timeout=10)
            return _original(*args, **kwargs)
        monkeypatch.setattr(target, "_publish_timepoint_catalog", publish)
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(target.save_timepoint_patch, user, sid, identifier,
                               {"ui": {"owner": identifier}}, expected_state_revision=0)
                   for target, identifier in [(store, a), (other, b)]]
        assert all(future.result()["timepoint_state_revision"] == 1 for future in futures)
    for identifier in (a, b):
        assert store.load_timepoint_snapshot(user, sid, identifier)["ui"]["owner"] == identifier


def test_partial_timepoint_appearance_patch_preserves_siblings(owned):
    store, user, sid = owned
    identifier = create(store, user, sid)
    store.save_timepoint_patch(user, sid, identifier, {"ui": {"state": {
        "data_tree": {"masks": {"a": {"color": "cyan", "opacity": .37}, "b": {"color": "gold"}}},
        "viewer": {"camera": [1, 2, 3], "annotations": [{"id": "old"}]},
    }}}, expected_state_revision=0)
    result = store.save_timepoint_patch(user, sid, identifier, {"ui": {"state": {
        "data_tree": {"masks": {"a": {"color": "violet"}}},
        "viewer": {"annotations": []},
    }}}, expected_state_revision=1)
    ui = result["ui"]["state"]
    assert ui["data_tree"]["masks"]["a"] == {"color": "violet", "opacity": .37}
    assert ui["data_tree"]["masks"]["b"] == {"color": "gold"}
    assert ui["viewer"]["camera"] == [1, 2, 3]
    assert ui["viewer"]["annotations"] == []


def test_captured_context_rejects_changed_source_but_not_display_or_rename(owned):
    store, user, sid = owned
    source = create(store, user, sid)
    target = create(store, user, sid, stage="intraoperative", preoperative_timepoint_id=source)
    context = store.capture_timepoint_context(user, sid, target)
    update(store, user, sid, source, {"title": "Renamed source"})
    store.save_timepoint_patch(user, sid, source, {"ui": {"opacity": .37}}, expected_state_revision=0)
    result = store.save_timepoint_results(user, sid, target, {"dose": [1]}, expected_clinical_revision=0,
                                          execution_context=context)
    assert result["timepoint_clinical_revision"] == 1
    next_context = store.capture_timepoint_context(user, sid, target)
    store.save_timepoint_results(user, sid, source, {"guide": {"version": 2}}, expected_clinical_revision=0)
    with pytest.raises(TimepointConflict, match="inputs changed"):
        store.save_timepoint_results(user, sid, target, {"dose": [2]}, expected_clinical_revision=1,
                                      execution_context=next_context)
    assert store.load_timepoint_snapshot(user, sid, target)["agent"]["planning_results"]["dose"] == [1]


def test_context_checks_source_again_inside_sqlite_commit(owned, monkeypatch):
    store, user, sid = owned
    source = create(store, user, sid)
    target = create(store, user, sid, stage="intraoperative", preoperative_timepoint_id=source)
    context = store.capture_timepoint_context(user, sid, target)
    other = WorkspaceStore(store.runtime_dir)
    original = store._publish_timepoint_catalog
    changed = [False]
    def race(*args, **kwargs):
        if not changed[0]:
            changed[0] = True
            other.save_timepoint_results(user, sid, source, {"new_input": 1}, expected_clinical_revision=0)
        return original(*args, **kwargs)
    monkeypatch.setattr(store, "_publish_timepoint_catalog", race)
    with pytest.raises(TimepointConflict, match="inputs changed"):
        store.save_timepoint_results(user, sid, target, {"old_output": 1}, expected_clinical_revision=0,
                                      execution_context=context)
    assert "old_output" not in store.load_timepoint_snapshot(user, sid, target)["agent"]["planning_results"]


def test_delete_restore_does_not_resurrect_authority_of_old_job(owned):
    store, user, sid = owned
    target = create(store, user, sid)
    context = store.capture_timepoint_context(user, sid, target)
    store.delete_timepoint(user, sid, target, expected_revision=store.list_timepoints(user, sid)["catalog_revision"])
    store.restore_timepoint(user, sid, target, expected_revision=store.list_timepoints(user, sid)["catalog_revision"])
    with pytest.raises(TimepointConflict, match="inputs changed"):
        store.save_timepoint_results(user, sid, target, {"late_result": 1}, expected_clinical_revision=0,
                                      execution_context=context)


def test_context_cannot_be_rebound_to_other_owner_or_target(owned):
    store, user, sid = owned
    target, other = create(store, user, sid), create(store, user, sid)
    context = store.capture_timepoint_context(user, sid, target)
    with pytest.raises(TimepointError):
        store.save_timepoint_results(user, sid, other, {"wrong": 1}, expected_clinical_revision=0,
                                      execution_context=context)
    from dataclasses import replace
    foreign = replace(context, owner_id="different-owner")
    with pytest.raises(TimepointConflict, match="another patient or owner"):
        store.save_timepoint_results(user, sid, target, {"wrong": 1}, expected_clinical_revision=0,
                                      execution_context=foreign)
