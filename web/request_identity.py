"""One request-case identity for routes, path resolution and editor leases."""
from flask import request
from web.workspace_store import WorkspaceError


def explicit_case_id(explicit=None):
    body = request.get_json(silent=True) if request.is_json else None
    values = [explicit, request.headers.get("X-BrachyBot-Session"), request.args.get("session_id")]
    if isinstance(body, dict):
        values.append(body.get("session_id"))
    candidates = {str(value).strip() for value in values if value is not None and str(value).strip()}
    if len(candidates) > 1:
        raise WorkspaceError("Conflicting request-bound case identifiers")
    # The cookie is only the navigation default: an async callback may correctly
    # name the previous case after the browser has selected another one.
    return next(iter(candidates), None)
