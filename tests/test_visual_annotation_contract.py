from pathlib import Path

import pytest

from agent_runtime.visual_evidence import (
    VISUAL_EVIDENCE_PROTOCOL_MARKER,
    VISUAL_RESPONSE_PROTOCOL_MARKER,
    build_visual_evidence_prompt,
    normalize_visual_evidence_context,
)
from web.routes.planning_routes import (
    _snapshot_annotation_planning_state,
    _validate_screenshot_annotation_marks,
)


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _target(
    target_ref: str,
    *,
    kind: str = "scene-object",
    locator: str = "scene-projection",
    scene_visible: bool = True,
    data_tree_visible: bool = True,
    status: str = "ready",
) -> dict:
    return {
        "target_ref": target_ref,
        "label": target_ref,
        "kind": kind,
        "locator": locator,
        "visible": True,
        "scene_visible": scene_visible,
        "data_tree_visible": data_tree_visible,
        "in_view": True,
        "annotatable": True,
        "status": status,
        "normalized_bounds": [0.2, 0.25, 0.3, 0.35],
    }


def _attachment(target: dict, *, policy: str = "required") -> dict:
    return {
        "id": "shot-1",
        "session_id": "a" * 32,
        "planning_id": "planning-a",
        "data_version": "7",
        "annotation_policy": policy,
        "view_metadata": {
            "grounding_manifest": {
                "version": 1,
                "target": "viewer-3d",
                "capture_state": {
                    "session_id": "a" * 32,
                    "planning_id": "planning-a",
                    "data_version": "7",
                },
                "targets": [target],
            }
        },
    }


def test_visual_v2_keeps_signed_urls_and_fails_closed_for_hidden_scene_objects():
    session_id = "a" * 32
    hidden_guide = _target(
        "surgical_guide:active",
        scene_visible=False,
        data_tree_visible=False,
    )
    raw = {
        "version": 2,
        "parent_request": "手术导板在哪里？",
        "evidence": [{
            "attachment_id": "shot-1",
            "url": f"/api/sessions/{session_id}/screenshots/guide.png?sig=deadbeef",
            "target": "viewer-3d",
            "visual_purpose": "locate",
            "annotation_policy": "required",
            "planning_id": "planning-a",
            "data_version": "7",
            "grounding_manifest": {
                "target": "viewer-3d",
                "capture_state": {
                    "session_id": session_id,
                    "planning_id": "planning-a",
                    "data_version": "7",
                },
                "targets": [hidden_guide],
            },
        }],
    }

    context = normalize_visual_evidence_context(raw, session_id)

    assert context is not None
    assert context["evidence"][0]["url"].endswith("?sig=deadbeef")
    normalized_target = context["evidence"][0]["grounding_manifest"]["targets"][0]
    assert normalized_target["scene_visible"] is False
    assert normalized_target["data_tree_visible"] is False
    assert normalized_target["annotatable"] is False

    prompt = build_visual_evidence_prompt(context, "zh-CN")
    assert VISUAL_EVIDENCE_PROTOCOL_MARKER in prompt
    assert VISUAL_RESPONSE_PROTOCOL_MARKER in prompt
    assert "Never point to where a hidden" in prompt
    assert "Use Chinese for every user-visible sentence and annotation label" in prompt


def test_server_rejects_a_hidden_scene_mark_even_if_client_claims_annotatable():
    source = _attachment(_target(
        "surgical_guide:active",
        scene_visible=False,
        data_tree_visible=False,
    ))

    with pytest.raises(ValueError, match="hidden 3D object"):
        _validate_screenshot_annotation_marks(source, [{
            "target_ref": "surgical_guide:active",
            "shape": "arrow",
            "label": "导板",
        }])


def test_data_tree_evidence_row_can_be_boxed_without_claiming_hidden_3d_visibility():
    target = _target(
        "surgical_guide:active",
        kind="data-tree-row",
        locator="data-tree-card",
        scene_visible=False,
        data_tree_visible=True,
    )
    source = _attachment(target)

    marks = _validate_screenshot_annotation_marks(source, [{
        "target_ref": "surgical_guide:active",
        "shape": "box",
        "label": "导板节点（当前在 3D 中隐藏）",
    }])

    assert marks == [{
        "target_ref": "surgical_guide:active",
        "shape": "box",
        "label": "导板节点（当前在 3D 中隐藏）",
        "locator": "data-tree-card",
    }]


def test_grounded_2d_viewer_object_can_be_annotated_from_capture_manifest():
    target = _target(
        "structure:ctv:1",
        kind="viewer-object-2d",
        locator="ctv-label-volume",
    )
    source = _attachment(target)

    marks = _validate_screenshot_annotation_marks(source, [{
        "target_ref": "structure:ctv:1",
        "shape": "ellipse",
        "label": "肿瘤",
    }])

    assert marks[0]["target_ref"] == "structure:ctv:1"
    assert marks[0]["shape"] == "ellipse"
    assert marks[0]["locator"] == "ctv-label-volume"


@pytest.mark.parametrize("status", ["loading", "stale", "error", "deleted"])
def test_server_rejects_non_current_targets(status):
    source = _attachment(_target("seed_1", status=status))
    with pytest.raises(ValueError, match="stale or unavailable"):
        _validate_screenshot_annotation_marks(source, [{
            "target_ref": "seed_1",
            "shape": "arrow",
        }])


def test_server_rejects_non_box_ui_annotations_and_annotation_policy_none():
    ui_target = _target(
        "generateSurgicalGuideButton",
        kind="ui-element",
        locator="dom",
    )
    with pytest.raises(ValueError, match="must use a box"):
        _validate_screenshot_annotation_marks(_attachment(ui_target), [{
            "target_ref": "generateSurgicalGuideButton",
            "shape": "arrow",
        }])
    with pytest.raises(ValueError, match="disabled"):
        _validate_screenshot_annotation_marks(
            _attachment(ui_target, policy="none"),
            [{"target_ref": "generateSurgicalGuideButton", "shape": "box"}],
        )


def test_server_reads_active_planning_generation_from_durable_snapshot():
    snapshot = {
        "agent": {
            "planning_results": {
                "active_planning_id": "planning-b",
                "manual_plan_version": 5,
                "planning_runs": [
                    {"planning_id": "planning-a", "data_version": 3},
                    {"planning_id": "planning-b", "data_version": 9},
                ],
            }
        }
    }

    assert _snapshot_annotation_planning_state(snapshot) == ("planning-b", "9")
    assert _snapshot_annotation_planning_state({}) == ("", "")


def test_browser_annotation_pipeline_is_semantic_state_aware_and_non_mutating():
    chat = _source("web/app/static/js/brachybot-chat-todo.js")
    annotation = _source("web/app/static/js/brachybot-visual-annotation.js")
    viewer = _source("web/app/static/js/brachybot-3d-manual.js")
    ui_api = _source("web/app/static/js/brachybot-ui-api.js")
    gallery = _source("web/app/static/js/brachybot-chat-core.js")
    route = _source("web/routes/planning_routes.py")
    index = _source("web/app/index.html")

    # No user-phrase whitelist decides whether multimodal analysis runs.
    assert "function _isVisualAnalysisRequest" not in chat
    assert "_visualAttachmentRequiresAnalysis" in chat
    assert "visual_purpose" in chat
    assert "annotation_policy" in chat

    # Stable refs, capture state, and a second current-state check own pixels.
    assert "target_ref" in annotation
    assert "scene_visible" in annotation
    assert "data_tree_visible" in annotation
    assert "state_changed_during_annotation" in annotation
    assert "data-tree-card" in annotation
    assert annotation.index("planning.dataVersion") < annotation.index("planning.version")
    assert "get3DScreenshotGroundingManifest" in viewer
    assert "appearance ? appearance.visible !== false : false" in viewer

    focus_block = viewer.split("function focusPlanningObjectsForScreenshot", 1)[1].split(
        "window.focusPlanningObjectsForScreenshot", 1
    )[0]
    assert "mesh.visible = true" not in focus_block
    assert "mesh.visible = isTarget && meshState.visible !== false" in focus_block

    # The derived PNG is additive; the immutable source remains available.
    assert "original_url" in gallery
    assert "annotated_url" in gallery
    assert "updateAssistantAttachmentVariant" in gallery
    assert "source screenshot integrity check failed" in route.lower()
    assert "_validate_screenshot_annotation_marks" in route
    assert "/api/screenshot/annotation" in route
    assert "grounding_manifest: groundingManifest" in ui_api
    assert "brachybot-visual-annotation.js?v=3" in index


def test_screenshot_autoframing_is_target_derived_verified_and_reversible():
    tool = _source("tool_factory/ui_screenshot/__init__.py")
    mpr = _source("web/app/static/js/brachybot-manual-annotation.js")
    viewer = _source("web/app/static/js/brachybot-3d-manual.js")
    ui_api = _source("web/app/static/js/brachybot-ui-api.js")
    annotation = _source("web/app/static/js/brachybot-visual-annotation.js")
    index = _source("web/app/index.html")

    # The model names stable objects. It is explicitly told not to estimate
    # medical coordinates or slices from prose/image pixels.
    assert '"version": 4' in tool
    assert "not guess center_voxel or slice_indices" in tool
    assert "Those fields are expert" in tool
    assert "focus.kind=`auto` or `close-up`" in tool

    # 2D uses the largest real cross-section and preserves the historical
    # axial display flip. The capture manifest owns exact MPR-space bounds.
    assert "function resolve2DScreenshotFocus" in mpr
    assert "deterministic-largest-cross-section" in mpr
    assert "counts[index] > counts[best]" in mpr
    assert "(shape[0] - 1) - volumeSlice" in mpr
    assert "function get2DScreenshotGroundingManifest" in mpr
    assert "kind: 'viewer-object-2d'" in mpr
    assert "hidden_in_data_tree_or_2d_view" in mpr

    # 3D fits the target against the limiting camera FOV, verifies projected
    # margins, and still never turns a hidden target on.
    focus_block = viewer.split("function focusPlanningObjectsForScreenshot", 1)[1].split(
        "window.focusPlanningObjectsForScreenshot", 1
    )[0]
    assert "getBoundingSphere" in focus_block
    assert "limitingHalfFov" in focus_block
    assert "edgeSafe" in focus_block
    assert "camera_restored_after_capture: true" in focus_block
    assert "occlusion_control: options.hideUnrelated ? 'target-isolated' : 'context-preserved'" in focus_block
    assert "mesh.visible = true" not in focus_block

    # Framing runs after the target panel is laid out, once per attachment;
    # every temporary 3D pose is restored even if capture/upload throws.
    assert "_applyStructuredScreenshotPlan(captureSpec, viewTarget)" in ui_api
    assert ui_api.index("await _prepareScreenshotTarget(viewTarget, captureSpec)") < ui_api.index(
        "_applyStructuredScreenshotPlan(captureSpec, viewTarget)"
    )
    assert "per-view focus restore skipped" in ui_api
    assert "automatic_framing_not_verified" in ui_api
    assert "_wait2DScreenshotSliceStable" in ui_api
    assert "const isolateTargetForStrictLocate" in ui_api
    assert "plan.visual_purpose === 'locate'" in ui_api
    assert "plan.annotation_policy === 'required'" in ui_api

    # Annotation revalidation checks live identity/visibility/freshness after
    # the temporary slice/camera has been restored; it does not demand that
    # the restored view still matches the immutable capture.
    assert "kind === 'viewer-object-2d'" in annotation
    assert "mpr_object_currently_hidden_or_stale" in annotation
    assert "does not" in annotation and "remain inside the restored live camera" in annotation

    assert "brachybot-ui-api.js?v=59" in index
    assert "brachybot-3d-manual.js?v=80" in index
    assert "brachybot-manual-annotation.js?v=22" in index
