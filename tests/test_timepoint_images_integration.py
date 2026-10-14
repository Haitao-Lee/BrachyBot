"""Real uploads, image decoding, store publication and recovery; no model substitute."""
from io import BytesIO
import numpy as np
import pytest
import SimpleITK as sitk

from web.timepoint_images import TimepointImageService
from web.timepoints import TimepointConflict, TimepointError
from web.workspace_store import WorkspaceStore


@pytest.fixture
def collection(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACHYBOT_ARCHIVE_ROOT", str(tmp_path / "archive"))
    store = WorkspaceStore(tmp_path / "runtime")
    owner = store.create_user("image_owner", "synthetic-hash")["id"]
    sid = store.create_session(owner, "Synthetic patient").id
    tid = store.migrate_default_timepoint(owner, sid)["default_timepoint_id"]
    return store, owner, sid, tid, TimepointImageService(store)


def image_file(tmp_path, name="ct.nii.gz", offset=0):
    array = np.arange(240, dtype=np.int16).reshape(4, 6, 10) + offset
    image = sitk.GetImageFromArray(array)
    image.SetSpacing((.8, 1.1, 2.4))
    image.SetOrigin((5., 8., 12.))
    image.SetDirection((0., -1., 0., 1., 0., 0., 0., 0., 1.))
    path = tmp_path / name
    sitk.WriteImage(image, str(path))
    return path, image


def upload(collection, path, **kwargs):
    store, owner, sid, tid, service = collection
    expected = service.list_images(owner, sid, tid)["collection_revision"]
    with path.open("rb") as stream:
        return service.register_upload(owner, sid, tid, stream, path.name, modality="CT",
            expected_collection_revision=expected, editor_token="", select_first_reference=True, **kwargs)


def update(collection, identifier, patch):
    _, owner, sid, tid, service = collection
    return service.update_image(owner, sid, tid, identifier, patch, editor_token="",
        expected_collection_revision=service.list_images(owner, sid, tid)["collection_revision"])


def test_latest_display_is_exclusive_and_does_not_change_planning_reference(collection, tmp_path):
    store, owner, sid, tid, service = collection
    first = upload(collection, image_file(tmp_path)[0])["created_image_id"]
    second = upload(collection, image_file(tmp_path, "later.nii.gz", 1000)[0])["created_image_id"]
    packet = service.list_images(owner, sid, tid)
    assert packet["display_image_id"] == second and packet["planning_reference_image_id"] == first
    assert [row["id"] for row in packet["images"] if row["show"]] == [second]
    assert packet["clinical_visible"] is False
    reference = service.planning_reference_bridge(owner, sid, tid)
    display = service.display_image_bridge(owner, sid, tid)
    assert float(display["ct_data"].min()) == float(reference["ct_data"].min()) + 1000
    update(collection, second, {"display": False})
    assert service.list_images(owner, sid, tid)["display_image_id"] is None
    assert service.planning_reference_bridge(owner, sid, tid)["planning_reference_image_id"] == first


def test_appearance_and_role_survive_restart_without_changing_clinical_inputs(collection, tmp_path):
    store, owner, sid, tid, service = collection
    first = upload(collection, image_file(tmp_path)[0])["created_image_id"]
    before = store.capture_timepoint_context(owner, sid, tid)
    update(collection, first, {"opacity": .31, "color": "#22D3EE", "wwl": {"width": 630., "level": 50.}, "role": "intraop"})
    recovered = TimepointImageService(WorkspaceStore(store.runtime_dir)).list_images(owner, sid, tid)
    image = recovered["images"][0]
    assert image["opacity"] == .31 and image["wwl"] == {"width": 630., "level": 50.} and image["role"] == "intraop"
    assert image['color'] == '#22d3ee'
    before.assert_current(owner, sid, store._timepoint_catalog(owner, sid), legacy_revision=store.get_session(owner, sid).revision)


def test_reference_change_invalidates_and_unchanged_previous_source_can_reuse_its_own_data(collection, tmp_path):
    store, owner, sid, tid, service = collection
    first = upload(collection, image_file(tmp_path)[0])["created_image_id"]
    snapshot = store.load_timepoint_snapshot(owner, sid, tid)
    store.save_timepoint_results(owner, sid, tid, {"ctv_binary_array": np.ones((4, 6, 10), np.uint8),
        "dose_metrics": {"v100": .9}}, expected_clinical_revision=snapshot["timepoint_clinical_revision"])
    second = upload(collection, image_file(tmp_path, "new.nii.gz", 1000)[0])["created_image_id"]
    update(collection, second, {"planning_reference": True})
    changed = store.load_timepoint_snapshot(owner, sid, tid)
    assert "ctv_binary_array" not in changed["agent"]["planning_results"]
    assert changed["report"]["status"] == "stale"
    update(collection, first, {"planning_reference": True})
    recovered = store.load_timepoint_snapshot(owner, sid, tid, decode_arrays=True)
    assert recovered["agent"]["planning_results"]["ctv_binary_array"].sum() == 240
    assert recovered["agent"]["planning_results"]["dose_metrics"]["v100"] == .9
    assert recovered["scientific_dependencies"]["reason"] == "unchanged_owned_reference_recovered"


def test_legacy_saved_pixels_and_appearance_migrate_without_losing_masks_or_report(collection, tmp_path):
    store, owner, sid, tid, service = collection
    _, image = image_file(tmp_path)
    state = store.load_timepoint_snapshot(owner, sid, tid)
    store.save_timepoint_results(owner, sid, tid, {"ct_data": sitk.GetArrayFromImage(image),
        "ct_spacing": image.GetSpacing(), "ct_origin": image.GetOrigin(), "ct_direction": image.GetDirection(),
        "ctv_binary_array": np.ones((4, 6, 10), np.uint8)},
        expected_clinical_revision=state["timepoint_clinical_revision"])
    state = store.load_timepoint_snapshot(owner, sid, tid)
    store.save_timepoint_patch(owner, sid, tid, {"ui": {"state": {"color": "#123456"}},
        "report": {"form": {"title": "Existing report"}}}, expected_state_revision=state["timepoint_state_revision"])
    before = store.capture_timepoint_context(owner, sid, tid)
    packet = service.adopt_saved_reference(owner, sid, tid)
    assert packet["display_image_id"] == packet["planning_reference_image_id"]
    result = store.load_timepoint_snapshot(owner, sid, tid, decode_arrays=True)
    assert result["agent"]["planning_results"]["ctv_binary_array"].sum() == 240
    assert result["ui"]["state"]["color"] == "#123456"
    assert result["report"]["form"]["title"] == "Existing report"
    before.assert_current(owner, sid, store._timepoint_catalog(owner, sid), legacy_revision=store.get_session(owner, sid).revision)
    assert service.adopt_saved_reference(owner, sid, tid)["collection_revision"] == packet["collection_revision"]


@pytest.mark.parametrize("lpi", [False, True])
def test_legacy_source_without_transient_pixels_recovers_on_saved_grid(collection, tmp_path, lpi):
    store, owner, sid, tid, service = collection
    path, native = image_file(tmp_path)
    image = sitk.DICOMOrient(native, "LPI") if lpi else native
    with path.open("rb") as stream:
        owned = store.write_upload(owner, sid, "legacy.nii.gz", stream)
    before = store.load_timepoint_snapshot(owner, sid, tid)
    store.save_timepoint_results(owner, sid, tid, {
        "ct_path": str(owned), "ct_spacing": image.GetSpacing(), "ct_origin": image.GetOrigin(),
        "ct_direction": image.GetDirection(), "image_volume_index": 0,
        "ctv_binary_array": np.ones(sitk.GetArrayFromImage(image).shape, np.uint8),
        "dose_metrics": {"v100": .93}}, expected_clinical_revision=before["timepoint_clinical_revision"])
    context = store.capture_timepoint_context(owner, sid, tid)
    packet = service.adopt_saved_reference(owner, sid, tid)
    assert len(packet["images"]) == 1
    restored = service.planning_reference_bridge(owner, sid, tid)
    assert np.array_equal(restored["ct_data"], sitk.GetArrayFromImage(image))
    assert np.allclose(restored["ct_image"].GetDirection(), image.GetDirection())
    result = store.load_timepoint_snapshot(owner, sid, tid, decode_arrays=True)
    assert result["agent"]["planning_results"]["dose_metrics"]["v100"] == .93
    assert result["agent"]["planning_results"]["ctv_binary_array"].sum() == 240
    context.assert_current(owner, sid, store._timepoint_catalog(owner, sid), legacy_revision=store.get_session(owner, sid).revision)


def test_legacy_source_cannot_escape_owner_or_change_saved_geometry(collection, tmp_path):
    store, owner, sid, tid, service = collection
    path, image = image_file(tmp_path)
    before = store.load_timepoint_snapshot(owner, sid, tid)
    store.save_timepoint_results(owner, sid, tid, {"ct_path": str(path)},
        expected_clinical_revision=before["timepoint_clinical_revision"])
    with pytest.raises(TimepointError, match="owning workspace"):
        service.adopt_saved_reference(owner, sid, tid)
    with path.open("rb") as stream:
        owned = store.write_upload(owner, sid, "legacy.nii.gz", stream)
    before = store.load_timepoint_snapshot(owner, sid, tid)
    store.save_timepoint_results(owner, sid, tid, {"ct_path": str(owned), "ct_origin": [999, 999, 999]},
        expected_clinical_revision=before["timepoint_clinical_revision"])
    with pytest.raises(TimepointError, match="geometry"):
        service.adopt_saved_reference(owner, sid, tid)
    assert not service.list_images(owner, sid, tid)["images"]


def test_reloading_committed_upload_path_does_not_duplicate_image(collection, tmp_path):
    store, owner, sid, tid, service = collection
    source = image_file(tmp_path)[0]
    with source.open("rb") as stream:
        owned = store.write_upload(owner, sid, f"timepoints/{tid}/incoming.nii.gz", stream)
    first = service.register_owned_source(owner, sid, tid, owned, modality="CT", expected_collection_revision=0,
        editor_token="", select_first_reference=True)
    second = service.register_owned_source(owner, sid, tid, owned, modality="CT",
        expected_collection_revision=first["collection_revision"], editor_token="")
    assert len(second["images"]) == 1 and second["display_image_id"] == first["created_image_id"]
    other = store.create_session(owner, "Other patient").id
    with pytest.raises(TimepointError):
        service.register_owned_source(owner, sid, tid, store.workspace_root(owner, other) / "inputs" / "scan.nii.gz",
            modality="CT", expected_collection_revision=second["collection_revision"], editor_token="")
