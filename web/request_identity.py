"""One request-case identity for routes, path resolution and editor leases."""
from flask import request
from web.workspace_store import WorkspaceError


class RequestIdentityError(WorkspaceError):
    """A typed scope error, without parsing exception prose in the UI."""
    code = "invalid_timepoint_scope"


def explicit_case_id(explicit=None):
    body = request.get_json(silent=True) if request.is_json else None
    values = [explicit, request.headers.get("X-BrachyBot-Session"), request.args.get("session_id")]
    if isinstance(body, dict):
        values.append(body.get("session_id"))
    candidates = {str(value).strip() for value in values if value is not None and str(value).strip()}
    if len(candidates) > 1:
        raise RequestIdentityError("Conflicting request-bound case identifiers")
    # The cookie is only the navigation default: an async callback may correctly
    # name the previous case after the browser has selected another one.
    return next(iter(candidates), None)


def explicit_timepoint_id(explicit=None):
    """Resolve one captured timepoint; never use a mutable navigation cookie."""
    from web.timepoints import timepoint_id

    body = request.get_json(silent=True) if request.is_json else None
    values = [explicit, request.headers.get("X-BrachyBot-Timepoint"), request.args.get("timepoint_id")]
    if isinstance(body, dict):
        values.append(body.get("timepoint_id"))
    candidates = {str(value).strip() for value in values if value is not None and str(value).strip()}
    if len(candidates) > 1:
        raise RequestIdentityError("Conflicting request-bound timepoint identifiers")
    if not candidates:
        return None
    try:
        return timepoint_id(next(iter(candidates)))
    except ValueError as exc:
        raise RequestIdentityError("Invalid request-bound timepoint identifier") from exc
