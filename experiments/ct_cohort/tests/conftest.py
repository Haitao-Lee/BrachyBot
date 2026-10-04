from pathlib import Path
import pytest
import nibabel as nib
import numpy as np

from brachycohort.core import child


class TestStorage:
    __test__ = False
    def __init__(self, root):
        self.source = root / "sources"
        self.base = root / "results"
        self.source.mkdir()
        self.base.mkdir()
        self.cfg = {}
    def check(self, reserve=0):
        return {}
    def path(self, name):
        return child(self.base, name)


@pytest.fixture
def storage(tmp_path):
    return TestStorage(tmp_path)


@pytest.fixture
def make_pair(storage):
    def make(labels, target_values=(2,), dataset="synthetic", mask_affine=None, units="mm", ct_units=None):
        a = np.asarray(labels, dtype=np.float32)
        ct = storage.source / "ct.nii.gz"
        mask = storage.source / "mask.nii.gz"
        affine = np.diag([1.1, 1.2, 1.3, 1])
        for path, array, aff, unit in ((ct, np.ones(a.shape, dtype=np.float32), affine, ct_units or units),
                                     (mask, a, affine if mask_affine is None else mask_affine, units)):
            img = nib.Nifti1Image(array, aff)
            img.header.set_xyzt_units(unit)
            nib.save(img, path)
        return {"row_id": "test-case", "dataset": dataset, "ct_path": str(ct), "label_path": str(mask),
                "image_modality": "CT", "target_values": list(target_values), "target_semantics": "research tumor",
                "clinical_eligibility": "NOT_ESTABLISHED", "phase": "NCCT", "metadata_positive": False}
    return make


@pytest.fixture
def approved_profile():
    return {"id": "test-only", "version": "1", "status": "APPROVED_RESEARCH",
            "clinical_reviewer": "synthetic-test-reviewer", "physics_reviewer": "synthetic-test-physicist", "approved_at": "2026-10-04",
            "applicability": {"datasets": ["synthetic"], "target_semantics": ["research tumor"], "site": "synthetic", "purpose": "unit test"},
            "evidence": [{"reference": "synthetic fixture, not clinical evidence", "section": "test", "applicability": "unit test only"}],
            "source": {"isotope": "test", "model": "synthetic", "strength": 1, "strength_unit": "test unit", "time_assumptions": "test only"},
            "engine": {"name": "synthetic", "weights_sha256": "a" * 64, "calibration": "test", "compatibility_review": "test"},
            "target_policy": {"kind": "supplied_union_no_margin"}, "oar_policy": {"kind": "product_inference"},
            "guide_policy": {"truncation_margin_mm": 5.0},
            "settings": {"prescription_gy": 42, "upper_dose_gy": 84, "coverage_fraction": 0.8, "max_iterations": 2, "mode": "rl"}}
