"""Numerical contracts of the actual checker; no model/clinical outcome claims."""

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from tool_factory.plan_quality.clinical_standards import OAR_STANDARDS
from tool_factory.plan_quality.oar_constraint_checker import OARConstraintCheckerTool


KB_PATH = Path(__file__).resolve().parents[1] / "tool_factory/clinical_kb/data/knowledge_base.json"
KB = json.loads(KB_PATH.read_text(encoding="utf-8"))["dose_standards"]
MISSING = object()
INVALID = [MISSING, None, float("nan"), float("inf"), float("-inf"),
           -1.0, True, False, np.bool_(False), "invalid", [], {}]


def check(metrics, **kwargs):
    result = OARConstraintCheckerTool().execute(oar_metrics=metrics, **kwargs)
    assert result.success, result.error
    for key, value in result.data.items():
        assert result.metadata[key] == value
    assert "source=" + result.data["constraint_source"] in result.message
    return result.data


def assert_unchecked(data, organ):
    assert data["all_checked_pass"] is False
    assert data["oar_status"][organ]["status"] == "NOT_CHECKED"
    assert organ in data["unchecked"]


@pytest.mark.parametrize("constraint,metric", [
    ("max_dose", "max_dose"), ("dmax", "dmax"), ("d2cc", "D2cc"),
    ("d1cc", "D1cc"), ("mean_dose", "mean_dose"), ("dmean_max", "Dmean"),
])
@pytest.mark.parametrize("value", INVALID)
def test_absolute_measurement_invalidity_never_becomes_zero(constraint, metric, value):
    row = {} if value is MISSING else {metric: value}
    # A zero custom ceiling exercises input validity, not a clinical guideline.
    data = check({"test_oar": row}, custom_constraints={"test_oar": {constraint: 0.0}})
    assert_unchecked(data, "test_oar")
    assert data["violations"] == []


@pytest.mark.parametrize("constraint,metric", [
    ("max_dose", "max_dose"), ("dmax", "dmax"), ("max_dose", "Dmax"),
    ("d2cc", "d2cc"), ("d2cc", "D2cc"), ("d1cc", "d1cc"),
    ("d1cc", "D1cc"), ("mean_dose", "mean_dose"),
    ("dmean_max", "dmean"), ("dmean_max", "Dmean"),
])
def test_absolute_aliases_accept_measured_zero_and_enforce_zero_limit(constraint, metric):
    constraints = {"test_oar": {constraint: 0.0}}
    zero = check({"test_oar": {metric: 0.0}}, custom_constraints=constraints)
    assert zero["all_checked_pass"] is True
    assert zero["oar_status"]["test_oar"]["status"] == "PASS"
    positive = check({"test_oar": {metric: 0.1}}, custom_constraints=constraints)
    assert positive["all_checked_pass"] is False
    assert positive["oar_status"]["test_oar"]["status"] == "FAIL"
    assert positive["violations"][0]["limit"] == 0.0


@pytest.mark.parametrize("site,organ", [("lung", "heart"), ("pancreatic", "duodenum")])
@pytest.mark.parametrize("metric,source_key", [("max_dose", "dmax_gy"), ("d2cc", "d2cc_gy")])
@pytest.mark.parametrize("offset", [-0.01, 0.0, 0.01])
def test_absolute_kb_limits_both_sides_and_equality(site, organ, metric, source_key, offset):
    source_limits = KB[site]["ldr"]["oar"][organ]
    row = {"max_dose": source_limits["dmax_gy"], "d2cc": source_limits["d2cc_gy"]}
    row[metric] += offset
    data = check({organ: row}, tumor_type=site)
    assert data["constraint_source"] == "clinical_standards_mirror:" + site
    assert data["all_checked_pass"] is (offset <= 0)
    assert data["oar_status"][organ]["constraints"][metric] == source_limits[source_key]
    if offset > 0:
        violation, = data["violations"]
        assert violation["constraint_type"] == metric
        assert violation["actual"] == row[metric]
        assert violation["limit"] == source_limits[source_key]


@pytest.mark.parametrize("site,modality,organ", [
    ("prostate", "ldr", "urethra"), ("breast", "apbi", "skin"),
    ("breast", "apbi", "ribs"),
])
@pytest.mark.parametrize("rx", [60.0, 120.0])
@pytest.mark.parametrize("offset", [-0.01, 0.0, 0.01])
def test_relative_kb_limits_compare_physical_dmax_over_current_rx(site, modality, organ, rx, offset):
    ratio_limit = KB[site][modality]["oar"][organ]["dmax_pct"]
    original = copy.deepcopy(OAR_STANDARDS)
    dmax = (ratio_limit + offset) * rx
    data = check({organ: {"max_dose": dmax}}, tumor_type=site, prescribed_dose=rx)
    assert data["all_checked_pass"] is (offset <= 0)
    assert data["oar_status"][organ]["constraints"]["max_dose_pct"] == ratio_limit
    assert OAR_STANDARDS == original
    if offset > 0:
        violation, = data["violations"]
        assert violation["constraint_type"] == "max_dose_pct"
        assert violation["actual"] == pytest.approx(dmax / rx)
        assert violation["limit"] == ratio_limit
        assert violation["units"] == violation["actual_unit"] == violation["limit_unit"] == "ratio"
        assert violation["actual_pct"] == pytest.approx(dmax / rx * 100.0)
        assert violation["limit_pct"] == pytest.approx(ratio_limit * 100.0)
        assert violation["excess_pct"] == pytest.approx(offset / ratio_limit * 100.0)


@pytest.mark.parametrize("rx", INVALID + [0.0])
def test_relative_physical_measurement_requires_known_positive_rx(rx):
    args = {} if rx is MISSING else {"prescribed_dose": rx}
    data = check({"urethra": {"max_dose": 0.0}}, tumor_type="prostate", **args)
    assert_unchecked(data, "urethra")
    assert data["violations"] == []


@pytest.mark.parametrize("value", INVALID)
def test_relative_physical_measurement_must_be_valid(value):
    row = {} if value is MISSING else {"Dmax": value}
    assert_unchecked(check({"urethra": row}, tumor_type="prostate", prescribed_dose=120.0), "urethra")


def test_current_rx_changes_relative_decision_and_measured_zero_is_valid():
    limit = KB["prostate"]["ldr"]["oar"]["urethra"]["dmax_pct"]
    metrics = {"urethra": {"dmax": limit * 120.0}}
    assert check(metrics, tumor_type="prostate", prescribed_dose=120.0)["all_checked_pass"] is True
    low_rx = check(metrics, tumor_type="prostate", prescribed_dose=60.0)
    assert low_rx["oar_status"]["urethra"]["status"] == "FAIL"
    assert low_rx["violations"][0]["actual"] == pytest.approx(2 * limit)
    assert check({"urethra": {"Dmax": 0.0}}, tumor_type="prostate",
                 prescribed_dose=120.0)["all_checked_pass"] is True


@pytest.mark.parametrize("alias", ["max_dose_pct", "dmax_pct"])
@pytest.mark.parametrize("offset", [-0.01, 0.0, 0.01])
def test_explicit_measured_ratio_needs_no_gy_conversion_or_rx(alias, offset):
    limit = KB["prostate"]["ldr"]["oar"]["urethra"]["dmax_pct"]
    data = check({"urethra": {alias: limit + offset}}, tumor_type="prostate")
    assert data["all_checked_pass"] is (offset <= 0)
    if offset > 0:
        assert data["violations"][0]["units"] == "ratio"


@pytest.mark.parametrize("value", INVALID)
def test_invalid_relative_ratio_cannot_pass(value):
    row = {} if value is MISSING else {"max_dose_pct": value}
    assert_unchecked(check({"urethra": row}, tumor_type="prostate"), "urethra")


def test_missing_one_required_measurement_keeps_real_violation_but_cannot_pass():
    source = KB["lung"]["ldr"]["oar"]["heart"]
    data = check({"heart": {"max_dose": source["dmax_gy"] + 1.0}}, tumor_type="lung")
    assert_unchecked(data, "heart")
    assert data["violations"][0]["limit"] == source["dmax_gy"]


def test_unchecked_organ_blocks_aggregate_even_when_another_organ_passes():
    data = check({"spinal_cord": {"max_dose": 0.0}, "unmapped": {"max_dose": 0.0}}, tumor_type="lung")
    assert data["oar_status"]["spinal_cord"]["status"] == "PASS"
    assert_unchecked(data, "unmapped")
    assert check({}, tumor_type="lung")["all_checked_pass"] is False


def test_unsupported_source_units_are_not_reinterpreted_as_physical_gy():
    data = check({"bladder": {"d2cc": 0.0}}, tumor_type="cervical")
    assert data["oar_status"]["bladder"]["constraints"]["d2cc_gy_eqd2"] == KB["cervical"]["hdr"]["oar"]["bladder"]["d2cc_gy_eqd2"]
    assert_unchecked(data, "bladder")


@pytest.mark.parametrize("limit", [None, float("nan"), float("inf"), -1.0, True, "bad"])
def test_invalid_explicit_limit_is_not_silently_skipped(limit):
    assert_unchecked(check({"test_oar": {"max_dose": 0.0}},
        custom_constraints={"test_oar": {"max_dose": limit}}), "test_oar")


def test_absolute_and_relative_constraints_are_both_required_and_provenance_is_retained():
    absolute = KB["lung"]["ldr"]["oar"]["spinal_cord"]["dmax_gy"]
    custom = {"urethra": {"max_dose": absolute}}
    before = copy.deepcopy(custom)
    data = check({"urethra": {"max_dose": absolute}}, tumor_type="prostate", custom_constraints=custom)
    assert_unchecked(data, "urethra")
    assert data["constraint_source"] == "clinical_standards_mirror:prostate+custom_constraints"
    assert custom == before
    data = check({"urethra": {"max_dose": absolute}}, tumor_type="prostate",
                 custom_constraints=custom, prescribed_dose=120.0)
    assert data["all_checked_pass"] is True
    data = check({"urethra": {"max_dose": absolute + 1.0}}, tumor_type="prostate",
                 custom_constraints=custom, prescribed_dose=120.0)
    assert data["oar_status"]["urethra"]["status"] == "FAIL"
    assert data["violations"][0]["constraint_type"] == "max_dose"


@pytest.mark.parametrize("value", [None, True, float("nan"), -1.0])
def test_invalid_canonical_measurement_is_not_hidden_by_zero_alias(value):
    data = check({"spinal_cord": {"max_dose": value, "dmax": 0.0}}, tumor_type="lung")
    assert_unchecked(data, "spinal_cord")


def test_derived_nonfinite_ratio_cannot_pass():
    data = check({"urethra": {"max_dose": 1e308}}, tumor_type="prostate", prescribed_dose=1e-308)
    assert_unchecked(data, "urethra")
