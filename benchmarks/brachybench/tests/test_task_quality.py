"""Task-corpus quality gate (DESIGN §36).

The size-expansion waves (Ch. 34–35) can drift into "same sentinel observation
under many labels".  These tests are the guard rail: they run
``tools/quality_audit.py`` and fail on any corpus defect.

Defects checked:
  * an empty prompt where the construct is not deliberately "empty input";
  * a placeholder / missing ``clinical_intent``;
  * an unresolved ``provenance.derived_from`` file reference;
  * ``obs_pos == obs_neg`` (a non-discriminating pair);
  * a **generic observation** -- identical ``(obs_pos, obs_neg)`` under one
    ``oracle.check`` across *different* constructs, with no shared
    ``paraphrase_group`` / ``contrast_family_id`` (and not a decision-surface
    ``tool_call_boundary`` or a degenerate-input restraint task).
"""

from __future__ import annotations

import os
import sys

BB = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(BB, "tools"))

import quality_audit as qa  # noqa: E402


def _report():
    return qa.audit()


def test_no_empty_prompt_or_weak_intent():
    rep = _report()
    assert rep["empty_text"] == [], rep["empty_text"][:10]
    assert rep["weak_intent"] == [], rep["weak_intent"][:10]


def test_all_grounding_references_resolve():
    rep = _report()
    assert rep["unresolved_grounding"] == [], rep["unresolved_grounding"][:10]


def test_safe_and_unsafe_observations_differ():
    rep = _report()
    assert rep["pos_eq_neg"] == [], rep["pos_eq_neg"][:10]


def test_no_generic_observation_across_constructs():
    rep = _report()
    assert rep["generic_observation"] == [], rep["generic_observation"][:15]
