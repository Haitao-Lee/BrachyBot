"""Timepoint help is source-bound and never pretends that disabled UI is ready."""
from agent_runtime.ui_control_manual import catalog, coverage, compact


def test_new_timepoint_buttons_are_known_without_claiming_live_execution():
    assert not coverage()["unknown_controls"]
    cards = {row["key"]: row for row in catalog()}
    for key, control in (("workspace.timepoint.add", "timepointAdd"), ("workspace.timepoint.manage", "timepointManage")):
        row = cards[key]
        assert row["sources"]
        assert any(binding["id"] == control and binding["disabled_by_default"] for binding in row["bindings"])
        en = compact(row, "en")
        assert en["authorization"] == "none"
        assert en["runtime_availability"] == "not_observed"
    assert "Disabled buttons" in compact(cards["workspace.timepoint.add"], "en")["limits_and_exit"]
    assert "legacy default" in compact(cards["workspace.timepoint.manage"], "en")["limits_and_exit"]


def test_dynamically_rendered_implant_controls_have_passive_source_bound_usage():
    from agent_runtime.ui_control_manual import lookup
    for identity in ('implantDetect','implantAddMissed','implantSourceSettings','implantReviewObservations',
                     'implantSaveCorrection','implantRecomputeDose'):
        rows=lookup(identity)
        assert rows and rows[0]['source_bound_dynamic'] is True
        assert rows[0]['sources']
        evidence=compact(rows[0],'en')
        assert evidence['runtime_availability']=='not_observed'
        assert evidence['authorization']=='none'
