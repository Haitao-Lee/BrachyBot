"""EXT track structural tests (DESIGN §25).

Only benchmarks BrachyBot can participate in are included (EXT-1..4); the
FHIR/EHR/gated candidates live under ``external/excluded/``.  These tests need
no vendor/data trees -- they certify the manifests and adapter wiring.
"""

from __future__ import annotations

import glob
import os
import sys

BB = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EXT = os.path.abspath(os.path.join(BB, "..", "external"))
sys.path.insert(0, BB)
sys.path.insert(0, os.path.join(BB, "tools"))
sys.path.insert(0, EXT)

import validate as _v  # noqa: E402  (tools/validate.py)
from jsonschema_lite import validate  # noqa: E402
import ext_common as xc  # noqa: E402  (benchmarks/external/ext_common.py)
from adapter_base import ExtAdapter  # noqa: E402

EXT_IDS = ["EXT-1", "EXT-2", "EXT-3", "EXT-4",
           "EXT-9", "EXT-10", "EXT-11", "EXT-12", "EXT-13",
           "EXT-14", "EXT-15"]
EXCLUDED_IDS = ["EXT-5", "EXT-6", "EXT-7", "EXT-8"]
_SCHEMA = _v.load_schema("acquisition")


def _manifest_paths():
    return sorted(glob.glob(os.path.join(EXT, "acquisition", "EXT-*.yaml")))


def _top_manifest():
    return _v.parse_yaml_lite(open(os.path.join(EXT, "manifest.yaml"), encoding="utf-8").read())


def test_included_acquisition_manifests_validate():
    paths = _manifest_paths()
    assert len(paths) == len(EXT_IDS), f"expected {len(EXT_IDS)} manifests, found {len(paths)}"
    for path in paths:
        doc = _v.load_doc(path)
        errs = validate(doc, _SCHEMA)
        assert errs == [], f"{os.path.basename(path)}: {errs}"
        assert not _v._find_placeholders(doc), os.path.basename(path)


def test_only_brachybot_participable_benchmarks_included():
    ids = {os.path.splitext(os.path.basename(p))[0] for p in _manifest_paths()}
    assert ids == set(EXT_IDS)
    for ex in EXCLUDED_IDS:
        assert not os.path.exists(os.path.join(EXT, ex)), f"{ex} must not be included"


def test_excluded_candidates_are_recorded_with_reasons():
    doc = _top_manifest()
    rec = {e["ext_id"]: e for e in doc.get("excluded_candidates", [])}
    assert set(rec) == set(EXCLUDED_IDS)
    for ex in EXCLUDED_IDS:
        assert rec[ex].get("reason"), f"{ex} needs a reason"
        assert os.path.isfile(os.path.join(EXT, "excluded", f"{ex}.yaml")), f"{ex} manifest missing"


def test_top_manifest_status_matches_acquisition():
    doc = _top_manifest()
    listed = []
    for tier in ("main", "specialty", "conditional"):
        for e in doc.get(tier, []) or []:
            listed.append(e["ext_id"])
            acq = _v.load_doc(os.path.join(EXT, "acquisition", f"{e['ext_id']}.yaml"))
            assert e["status"] == acq["status"], f"{e['ext_id']} status drift"
    assert set(listed) == set(EXT_IDS)


def test_every_adapter_imports_and_implements_the_contract():
    for ext_id in EXT_IDS:
        adapter = xc.load_adapter(ext_id)
        assert isinstance(adapter, ExtAdapter), f"{ext_id} must subclass ExtAdapter"
        assert adapter.EXT_ID == ext_id
        for method in ("list_tasks", "build_input", "run_task", "score"):
            assert callable(getattr(adapter, method)), f"{ext_id}.{method} missing"


def test_active_main_anchors_are_r0():
    doc = _top_manifest()
    for e in doc["main"]:
        if e["status"] == "active":
            assert e["grade_R"] == "R0" and e["grade_C"] == "C3"
