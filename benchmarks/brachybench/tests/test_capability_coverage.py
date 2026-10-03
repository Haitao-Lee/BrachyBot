"""Capability-coverage gate tests (DESIGN §32).

Guard the machine-readable capability census and make sure the coverage gate
has no dangling references.  The gate itself (``tools/coverage.py``) is what
turns "some capability is untested" into a visible, enforcable number.
"""

from __future__ import annotations

import json
import os
import sys

BB = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BB)
sys.path.insert(0, os.path.join(BB, "tools"))

import coverage as cov  # noqa: E402


def test_registry_is_well_formed():
    reg = cov.load_registry()
    dims = set((reg.get("dimensions") or {}).keys())
    assert dims == {"F", "E", "P", "S", "R", "I", "A"}
    caps = cov.capabilities(reg)
    assert len(caps) >= 50, f"capability census too small: {len(caps)}"
    ids = [c["id"] for c in caps]
    assert len(ids) == len(set(ids)), "duplicate capability id"
    for c in caps:
        assert isinstance(c.get("mutates"), bool), c
        req = c.get("required_dims") or []
        assert req, f"{c['id']} has no required dimensions"
        assert set(req) <= dims, f"{c['id']} uses unknown dimension(s): {set(req) - dims}"


def test_coverage_evidence_references_resolve():
    report = cov.compute()
    assert report["bad_capability_refs"] == [], report["bad_capability_refs"]
    assert report["bad_evidence_refs"] == [], report["bad_evidence_refs"]


def test_coverage_report_has_substance_and_honest_gaps():
    report = cov.compute()
    assert report["n_capabilities"] >= 50
    assert report["total_cells"] > 0
    assert report["covered_cells"] > 0
    # the registry is a census: coverage is tracked honestly, never inflated --
    # covered cells can equal the total (full coverage) but must never exceed it,
    # and the gap count must match the rows that actually carry missing dims.
    assert report["covered_cells"] <= report["total_cells"]
    assert report["n_capabilities_with_gaps"] == len(
        [r for r in report["rows"] if r["missing"]]
    )


def test_authorization_capability_is_fully_covered():
    report = cov.compute()
    row = next(r for r in report["rows"] if r["id"] == "safety:authorization")
    assert row["missing"] == [], row
    assert row["n"] == row["covered"] == 6


def test_strict_gate_fails_below_threshold():
    # a threshold above any possible coverage must fail; a trivially low one pass.
    assert cov.main(["--strict", "--min", "1.01"]) == 1
    assert cov.main(["--strict", "--min", "0.0"]) == 0
