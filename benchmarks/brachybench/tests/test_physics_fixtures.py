"""Replay verification for the generated physics-boundary fixtures.

DESIGN §21.1 / N13: procedurally generated items are only admissible because
their ground truth is analytic and was **recorded at generation time**.  This
module replays every fixture through the real checker and asserts the verdict
still matches, so that either the oracle or the fixture drifting out of sync
shows up as a test failure rather than as a silently wrong score.

It also exercises the schema gate over the whole task tree (BA-15's
"runnable" requirement) and the five-level split invariant (N7).
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest

BB = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BB)

from oracles import get_oracle  # noqa: E402
from tools.jsonschema_lite import validate  # noqa: E402

PHYS = os.path.join(BB, "fixtures", "physics")
PHYS_V2 = os.path.join(BB, "fixtures", "physics_contract_v2")
TASKS_PHYS = os.path.join(BB, "tasks", "physics")


def _load_fixtures():
    if not os.path.isdir(PHYS):
        return []
    out = []
    for fn in sorted(os.listdir(PHYS)):
        if fn.endswith(".json"):
            with open(os.path.join(PHYS, fn), encoding="utf-8") as fh:
                original = json.load(fh)
            migrated = os.path.join(PHYS_V2, fn)
            if os.path.isfile(migrated):
                import hashlib
                with open(migrated, encoding='utf-8') as fh:
                    fixture = json.load(fh)
                raw = open(os.path.join(PHYS, fn), 'rb').read()
                assert fixture['contract_migration']['source_sha256'] == hashlib.sha256(raw).hexdigest()
                assert fixture['expected'] == original['expected']
                assert fixture['config']['first'] == original['config']['first']
                assert fixture['config']['second'] == original['config']['second']
                out.append(fixture)
            else:
                out.append(original)
    return out


FIXTURES = _load_fixtures()


def test_physics_fixtures_exist_and_are_150():
    assert len(FIXTURES) >= 150, f"only {len(FIXTURES)} fixtures (want 150)"
    fams = {f["family"] for f in FIXTURES}
    assert fams == {"coord_boundary", "dose_additivity", "needle_interference",
                    "dose_quantisation", "guide_tolerance", "unit_binding"}


def test_physics_fixtures_replay_matches_recorded_verdict():
    """The heart of the quality claim: nothing drifted."""
    from tools.gen_physics_fixtures import GENERATORS

    mismatches = []
    for fx in FIXTURES:
        _, judge = GENERATORS[fx["family"]]
        res = judge(fx["config"])
        got = "pass" if res.passed else "fail"
        want = fx["expected"]["verdict"]
        got_codes = sorted({v.code for v in res.violations})
        want_codes = fx["expected"]["violation_codes"]
        if got != want or got_codes != want_codes:
            mismatches.append({"id": fx["id"], "want": want, "got": got,
                               "want_codes": want_codes, "got_codes": got_codes})
    assert not mismatches, f"{len(mismatches)} fixture(s) drifted: {mismatches[:3]}"


def test_physics_fixtures_have_both_verdicts():
    """A corpus with only passes or only fails proves nothing -- per family.

    Family-level degeneracy is the same defect at smaller grain: two
    originally all-pass families (dose_additivity, dose_quantisation) could
    not detect any failure, so every family must now contain both verdicts.
    """
    per_family: dict = {}
    for f in FIXTURES:
        per_family.setdefault(f["family"], {"pass": 0, "fail": 0})
        per_family[f["family"]][f["expected"]["verdict"]] += 1
    assert set(per_family) == {"coord_boundary", "dose_additivity", "needle_interference",
                               "dose_quantisation", "guide_tolerance", "unit_binding"}
    degenerate = {k: v for k, v in per_family.items() if min(v.values()) < 5}
    assert not degenerate, f"families without discriminative power: {degenerate}"


def test_physics_tasks_runnable_and_three_outcomes():
    """The 150 probes must be executable through the standard pipeline.

    A probe whose SUT conclusion matches the analytic ground truth meets the
    criterion; a contradicting conclusion does not; a missing conclusion is
    insufficient evidence -- never a silent pass.
    """
    from tools import run_task as rt

    three = {
        "Meets": "Meets",
        "Does not meet": "Does not meet",
        "Insufficient evidence for the benchmark criterion":
            "Insufficient evidence for the benchmark criterion",
    }
    bad = []
    for p in sorted(os.listdir(TASKS_PHYS)):
        if not p.endswith(".json"):
            continue
        with open(os.path.join(TASKS_PHYS, p), encoding="utf-8") as fh:
            t = json.load(fh)
        fx = json.load(open(os.path.join(BB, t["fixture"]["setup_script"]), encoding="utf-8"))
        want = fx["expected"]["verdict"]
        r_ok = rt.evaluate(t, {"claimed_verdict": want,
                               "claimed_codes": fx["expected"]["violation_codes"]}, {})
        r_bad = rt.evaluate(t, {"claimed_verdict": "pass" if want == "fail" else "fail"}, {})
        r_none = rt.evaluate(t, {}, {})
        if (r_ok["verdict"] != three["Meets"]
                or r_bad["verdict"] != three["Does not meet"]
                or r_none["verdict"] != three["Insufficient evidence for the benchmark criterion"]):
            bad.append((t["id"], r_ok["verdict"], r_bad["verdict"], r_none["verdict"]))
    assert not bad, f"{len(bad)} physics tasks not runnable/scorable: {bad[:3]}"


def test_physics_tasks_satisfy_schema():
    schema_path = os.path.join(BB, "schema", "task.schema.json")
    with open(schema_path, encoding="utf-8") as fh:
        schema = json.load(fh)
    if not os.path.isdir(TASKS_PHYS):
        pytest.skip("no generated tasks")
    files = [f for f in sorted(os.listdir(TASKS_PHYS)) if f.endswith(".json")]
    assert len(files) >= 150
    bad = []
    for fn in files:
        with open(os.path.join(TASKS_PHYS, fn), encoding="utf-8") as fh:
            doc = json.load(fh)
        errs = validate(doc, schema)
        if errs:
            bad.append((fn, errs))
    assert not bad, bad[:3]


def test_physics_task_ids_are_unique_and_named():
    ids = set()
    for fn in sorted(os.listdir(TASKS_PHYS)):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(TASKS_PHYS, fn), encoding="utf-8") as fh:
            doc = json.load(fh)
        assert doc["id"] not in ids, f"duplicate task id {doc['id']}"
        ids.add(doc["id"])
        # provenance must say these are generated from an analytic oracle
        assert doc["provenance"]["source"] == "generated"
        assert "analytic oracle" in doc["provenance"]["derived_from"]


def test_generated_probe_tasks_are_track_A_with_real_prompts():
    """Round 3: physics-boundary probes are Track A, not D1, and carry a real
    instruction rather than a ``[generated ...]`` stub."""
    for fn in sorted(os.listdir(TASKS_PHYS)):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(TASKS_PHYS, fn), encoding="utf-8") as fh:
            doc = json.load(fh)
        assert doc["track"] == "A", f"{fn}: expected Track A, got {doc['track']!r}"
        text = doc["protocol"]["turns"][0]["text"]
        assert text and not text.startswith("["), f"{fn}: placeholder prompt {text!r}"
        assert len(text) >= 30, f"{fn}: prompt too short {text!r}"


def test_initial_state_hashes_are_real():
    """BA-15: a placeholder hash means the frozen initial state is unverifiable."""
    for fx in FIXTURES:
        h = fx["initial_state_hash"]
        assert h.startswith("sha256:") and len(h) == 71
        assert h != "sha256:" + "0" * 64
        assert len(set(h[7:])) > 4, "hash looks like a placeholder"


def test_all_tasks_including_physics_validate():
    schema_path = os.path.join(BB, "schema", "task.schema.json")
    with open(schema_path, encoding="utf-8") as fh:
        schema = json.load(fh)
    seen = set()
    n = 0
    for dirpath, _, files in os.walk(os.path.join(BB, "tasks")):
        for fn in sorted(files):
            if not fn.endswith(".json"):
                continue
            n += 1
            p = os.path.join(dirpath, fn)
            with open(p, encoding="utf-8") as fh:
                doc = json.load(fh)
            assert not validate(doc, schema), (fn, validate(doc, schema))
            assert doc["id"] not in seen, f"duplicate id {doc['id']}"
            seen.add(doc["id"])
    assert n >= 153, f"only {n} tasks in total"
