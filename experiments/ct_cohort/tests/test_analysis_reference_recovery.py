import copy
from pathlib import Path
import numpy as np
import pytest
import SimpleITK as sitk

from brachycohort.core import Blocked, atomic_json, sha256
from brachycohort.analysis import locked_paired_analysis, results
from brachycohort.verify import physics_reference, archive_manifest, review
from brachycohort.recovery import render_pdf


def locked_pairs(n=30):
    frame = {str(i): {"cluster_id": str(i), "stratum": "s"} for i in range(n)}
    protocol = {"study_kind": "paired_workflow", "sampling_seed": 17, "row_ids": list(frame),
                "analysis": {"method": "stratified_paired_cluster_bootstrap_v1", "stratum_weights": {"s": 1},
                             "noninferiority_margin": .05, "alpha": .025, "bootstrap_replicates": 1000,
                             "minimum_clusters_per_stratum": 30}}
    rows = [{"row_id": str(i), "arm": arm, "status": "PARTIAL", "workflow_completion": "UNKNOWN" if i == 0 else "PASS"}
            for i in range(n) for arm in ("browser-chat", "manual-ui")]
    return rows, protocol, frame


def test_locked_paired_unknown_counts_zero_not_dropped():
    rows, p, frame = locked_pairs()
    result = locked_paired_analysis(rows, p, frame)
    assert result["pairs"] == 30 and result["difference"] == 0
    assert result["bootstrap_interval"] == [0, 0]
    assert not result["lower_bound_above_negative_margin"]
    assert result["interval"][0] < 0 < result["interval"][1]


@pytest.mark.parametrize("problem", ["missing_arm", "unfinished", "duplicate", "wrong_row", "cluster_collision", "sparse"])
def test_primary_analysis_does_not_hide_missingness(problem):
    rows, p, frame = locked_pairs()
    if problem == "missing_arm":
        rows.pop()
    elif problem == "unfinished":
        rows[0]["status"] = "INCOMPLETE"
    elif problem == "duplicate":
        rows.append(rows[0])
    elif problem == "wrong_row":
        rows[0]["row_id"] = "wrong"
    elif problem == "cluster_collision":
        frame["1"]["cluster_id"] = "0"
    else:
        p["analysis"]["minimum_clusters_per_stratum"] = 50
    assert locked_paired_analysis(rows, p, frame)["status"] != "LOCKED_DESIGN_ESTIMATE"


def test_primary_weights_must_be_frozen_probabilities():
    rows, p, frame = locked_pairs()
    p["analysis"]["stratum_weights"] = {"s": 2}
    with pytest.raises(Blocked):
        locked_paired_analysis(rows, p, frame)


def test_stale_adjudication_never_replaces_original(storage):
    root = storage.path("runs/h/a")
    atomic_json(root / "attempt.json", {"dummy": True})
    atomic_json(root / "terminal_result.json", {"recipe_hash": "h", "attempt_id": "a"})
    reviewed = storage.path("tables/adjudications/a/r.json")
    atomic_json(reviewed, {"recipe_hash": "h", "attempt_id": "a", "workflow_completion": "PASS"})
    atomic_json(reviewed.parent / "current.json", {"path": str(reviewed), "sha256": sha256(reviewed),
                "first_attempt_terminal_sha256": "wrong"})
    with pytest.raises(Blocked, match="ADJUDICATION_LINK_CHANGED"):
        results(storage.base)


def test_reference_binds_actual_bytes(tmp_path, approved_profile):
    dose, ref, target = (tmp_path / n for n in ("dose.nii.gz", "ref.nii.gz", "target.nii.gz"))
    for path, value in ((dose, 10), (ref, 11), (target, 1)):
        image = sitk.GetImageFromArray(np.full((3, 3, 3), value, dtype=np.float32))
        sitk.WriteImage(image, str(path))
    geometry = tmp_path / "geometry.json"
    atomic_json(geometry, {"synthetic": True})
    r = {"engine": "independent test", "version": "1", "source_model": "synthetic",
         **approved_profile["source"], "reviewer": "test", "approval_reference": "test",
         "reference_sha256": sha256(ref), "sut_dose_sha256": sha256(dose), "target_sha256": sha256(target),
         "geometry_path": str(geometry), "geometry_sha256": sha256(geometry), "dose_unit": "Gy"}
    result = physics_reference(dose, ref, target, approved_profile, r)
    assert result["status"] == "PASS" and result["mean_absolute_error_gy"] == 1
    assert result["physical_acceptance"] == "REVIEW_REQUIRED"
    r["sut_dose_sha256"] = "wrong"
    assert physics_reference(dose, ref, target, approved_profile, r)["status"] == "FAIL"
    r.pop("geometry_sha256")
    assert physics_reference(dose, ref, target, approved_profile, r)["status"] == "UNKNOWN"


def test_review_missing_evidence_or_boolean_never_passes(tmp_path):
    path = tmp_path / "review.json"
    (tmp_path / "report.pdf").write_bytes(b"test")
    (tmp_path / "guide.stl").write_bytes(b"test")
    entries = archive_manifest(tmp_path)
    for item in entries:
        if item["path"] == "guide.stl":
            item["data_type"] = "surgical_guide"
    receipt = {"status": "APPROVED_RESEARCH_REVIEW", "reviewer": "test", "reviewed_at": "test", "recipe_hash": "h", "rules_hash": "rule", "attempt_id": "a",
               "artifact_hashes": {v["path"]: v["sha256"] for v in entries}, "checks": {"k": "PASS"}}
    atomic_json(path, receipt)
    assert review(path, "h", entries, ["k"], "rule", "a")["status"] == "PASS"
    receipt["checks"]["k"] = True
    atomic_json(path, receipt)
    assert review(path, "h", entries, ["k"], "rule", "a")["status"] == "UNKNOWN"


def test_pdf_review_is_separate_from_original_archive(storage):
    from pypdf import PdfWriter
    root = storage.path("runs/h/a")
    root.mkdir(parents=True)
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    with (root / "report.pdf").open("wb") as f:
        writer.write(f)
    before = sha256(root / "report.pdf")
    result = render_pdf(root, storage)
    assert result["pages"] and sha256(root / "report.pdf") == before
    assert str(storage.base / "tables") in result["output"]
    assert not (root / "page-1.png").exists()
