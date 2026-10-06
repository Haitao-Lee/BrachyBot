"""Receipt-only completion of pure location requests; never image interpretation.

The browser owns capture geometry. This boundary uses only same-turn persisted
captures and server-validated annotations, not a child's submitted manifest.
Mixed/clinical/explanatory questions remain on the normal multimodal path.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit, unquote

from agent_runtime.turn_policy import classify_local_turn
from agent_runtime.visual_evidence import normalize_visual_evidence_context


def location_delivery_context(snapshot: Mapping[str, Any], submitted: Mapping[str, Any],
                              parent_request_id: str, session_id: str,
                              planning_state: tuple[str, str], artifact_path) -> dict | None:
    """Return complete, current receipt evidence or fail closed to model analysis.

    A no-model answer needs a verified server annotation for every supplied
    image and every capture plan/view in the owning trace. Unknown protocols,
    absent IDs, mixed tasks, partial captures and changed plans do not qualify.
    """
    if not parent_request_id or submitted.get("omitted_count", 0):
        return None
    chat = snapshot.get("chat") or {}
    messages = chat.get("messages") or []
    same_turn = [row for row in messages if isinstance(row, Mapping)
                 and row.get("request_id") == parent_request_id]
    users = [row for row in same_turn if row.get("type") == "user"]
    if len(users) != 1:
        return None
    question = str(users[0].get("content") or "").strip()
    if question != str(submitted.get("parent_request") or "").strip():
        return None
    # Reuse the request parser/speech-act policy. Do not add another natural-
    # language whitelist or treat a locate attachment as the whole request.
    if classify_local_turn(question).intent != "session_visual_location_query":
        return None
    traces = [row for row in same_turn if row.get("type") == "thinking"]
    steps = traces[-1].get("steps", []) if traces else []
    tools = [s for s in steps if isinstance(s, Mapping) and s.get("type") == "tool"]
    if not tools or any(s.get("tool") != "ui_screenshot" or s.get("status") != "done"
                        for s in tools):
        return None
    expected_views = []
    expected_families = set()
    for step in tools:
        plan = (step.get("metadata") or {}).get("screenshot_plan") or {}
        if plan.get("visual_purpose") != "locate":
            return None
        expected_families.update(plan.get("semantic_targets") or [])
        views = plan.get("views") or []
        for view in views:
            name = view if isinstance(view, str) else view.get("target")
            if not name:
                return None
            expected_views.append(str(name))
    incoming = submitted.get("evidence") or []
    if not expected_views or len(incoming) != len(expected_views):
        return None
    if len({item.get("attachment_id") for item in incoming}) != len(incoming):
        return None
    registry = [item for item in chat.get("attachments", []) if isinstance(item, Mapping)]
    registry.extend(item for row in same_turn for item in row.get("attachments", [])
                    if isinstance(item, Mapping))
    active_id, active_version = planning_state
    evidence = []
    for request in incoming:
        matches = [item for item in registry
                   if str(item.get("id") or "") == str(request.get("attachment_id") or "")
                   and item.get("request_id") == parent_request_id
                   and item.get("session_id") == session_id]
        item = next((item for item in reversed(matches) if item.get("annotated_url")), None)
        if not item or item.get("visual_purpose") != "locate":
            return None
        # Require the same immutable source; allow the browser's current URL
        # to be either the source or its persisted derived annotation.
        if request.get("url") not in {item.get("url"), item.get("annotated_url")}:
            return None
        if (str(item.get("planning_id") or "") != str(active_id or "")
                or str(item.get("data_version") or "") != str(active_version or "")):
            return None
        annotation = item.get("annotation") or {}
        marks = annotation.get("marks") or []
        if not marks or annotation.get("source_sha256") != item.get("sha256"):
            return None
        # Check both persisted artifacts, not merely existence flags. These
        # images are bounded by screenshot upload limits and use no CT arrays.
        for url, expected_hash in ((item.get("url"), item.get("sha256")),
                                   (item.get("annotated_url"), item.get("annotation_sha256"))):
            parsed = urlsplit(str(url or ""))
            prefix = f"/api/sessions/{session_id}/screenshots/"
            filename = unquote(parsed.path[len(prefix):])
            if not parsed.path.startswith(prefix) or not filename or Path(filename).name != filename:
                return None
            try:
                path = artifact_path(filename)
                digest = hashlib.sha256()
                with open(path, "rb") as stream:
                    for chunk in iter(lambda: stream.read(65536), b""):
                        digest.update(chunk)
                if not expected_hash or digest.hexdigest() != expected_hash:
                    return None
            except OSError:
                return None
        metadata = item.get("view_metadata") or {}
        manifest = metadata.get("grounding_manifest") or {}
        refs = {str(mark.get("target_ref") or "") for mark in marks}
        targets = manifest.get("targets") or []
        if not targets or any(
            not isinstance(target, Mapping) or target.get("target_ref") not in refs
            or target.get("annotatable") is not True or target.get("visible") is not True
            or target.get("in_view") is not True
            or (item.get("target") == "viewer-3d" and (
                target.get("loaded") is False or target.get("scene_visible") is not True
                or target.get("data_tree_visible") is not True))
            for target in targets
        ):
            return None
        evidence.append({**metadata, **item, "attachment_id": item["id"],
                         "grounding_manifest": manifest,
                         "annotation_target_refs": sorted(refs), "annotation_present": True})
    if sorted(item.get("target") for item in evidence) != sorted(expected_views):
        return None
    # Normalize only the persisted receipt, never submitted target names,
    # coordinates, annotation flags, preliminary prose or case-state claims.
    normalized = normalize_visual_evidence_context({
        "version": 2, "parent_request": question, "evidence": evidence,
    }, session_id)
    if normalized is None or len(normalized["evidence"]) != len(evidence):
        return None
    actual_families = {family for item in normalized["evidence"]
                       for family in item.get("semantic_targets", [])}
    if not expected_families or not expected_families.issubset(actual_families):
        return None
    if any(target.get("annotatable") is not True
           for item in normalized["evidence"]
           for target in item["grounding_manifest"]["targets"]):
        return None
    return normalized
