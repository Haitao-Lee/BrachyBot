"""Explicit human continuation geometry settings for the addressed scan."""
from functools import wraps
import uuid

from flask import jsonify, request
from web.auth import current_user
from web.guide_placement import BoreValidationProfile
from web.request_identity import explicit_case_id, explicit_timepoint_id
from web.server_support import require_api_key
from web.timepoint_messages import request_timepoint_language, timepoint_error
from web.timepoints import TimepointError, TimepointConflict
from web.workspace_store import WorkspaceError

SCOPED_INTRAOPERATIVE_ENDPOINTS = frozenset({"intraoperative_settings"})


def register_intraoperative_routes(app, store):
    raw = getattr(store, "raw", store)
    @app.route("/api/sessions/<session_id>/timepoints/<identifier>/intraoperative-settings", methods=["GET", "POST"])
    @require_api_key
    def intraoperative_settings(session_id, identifier):
        user = current_user(raw)
        if not user:
            return jsonify(success=False, code="authentication_required"), 401
        try:
            explicit_case_id(session_id)
            explicit_timepoint_id(identifier)
            snapshot = raw.load_timepoint_snapshot(user["id"], session_id, identifier)
            if snapshot["timepoint"]["stage"] != "intraoperative":
                raise TimepointError("Continuation settings require an intraoperative timepoint")
            results = snapshot["agent"]["planning_results"]
            if request.method == "GET":
                return jsonify(success=True, session_id=session_id, timepoint_id=identifier,
                    settings=results.get("continuation_review_profile"), state_revision=snapshot["timepoint_state_revision"],
                    clinical_revision=snapshot['timepoint_clinical_revision'],clinical_use_approved=False)
            raw.assert_editable(user["id"], session_id, request.headers.get("X-BrachyBot-Editor", ""))
            data = request.get_json(silent=True)
            fields = {"needle_radius_mm", "minimum_guiding_length_mm", "obstacle_clearance_mm", "maximum_depth_mm"}
            revision_key = 'expected_clinical_revision' if isinstance(data,dict) and 'expected_clinical_revision' in data else 'expected_state_revision'
            if not isinstance(data, dict) or set(data) != fields | {revision_key, "confirmed"} or data["confirmed"] is not True:
                raise TimepointError("Confirm all continuation geometry inputs explicitly")
            actual = snapshot['timepoint_clinical_revision'] if revision_key == 'expected_clinical_revision' else snapshot['timepoint_state_revision']
            if type(data[revision_key]) is not int or data[revision_key] != actual:
                raise TimepointConflict("Continuation inputs changed before confirmation")
            if any(type(data[key]) not in {float, int} for key in fields):
                raise TimepointError("Continuation geometry thresholds must be numerical")
            profile = BoreValidationProfile(uuid.uuid4().hex, **{key: data[key] for key in fields})
            from dataclasses import asdict
            settings = {**asdict(profile), "confirmed_by": user["id"],
                "confirmation_scope": "software_geometry_inputs_not_clinical_approval"}
            raw.save_timepoint_results(user["id"], session_id, identifier,
                {"continuation_review_profile": settings, "continuation_baseline_record": None,
                 "continuation_search_record": None}, **{revision_key:data[revision_key]})
            return jsonify(success=True, settings=settings, clinical_use_approved=False)
        except (WorkspaceError, TimepointError, ValueError, TypeError) as exc:
            packet, status = timepoint_error(exc, request_timepoint_language())
            return jsonify(packet), status
