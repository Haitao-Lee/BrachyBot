from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_STAGE = Path(__file__).resolve().parent
ASSET_ROOT = PROJECT_ROOT / "web" / "app"
if not ASSET_ROOT.exists():
    ASSET_ROOT = LOCAL_STAGE


def _read(name):
    path = ASSET_ROOT / name if name == "index.html" else ASSET_ROOT / "static" / "js" / name
    if not path.exists():
        path = LOCAL_STAGE / name
    return path.read_text(encoding="utf-8")


def test_editable_mode_is_explicit_and_label_has_no_toolbar_checkbox():
    index = _read("index.html")
    manual3d = _read("brachybot-3d-manual.js")
    annotation = _read("brachybot-manual-annotation.js")
    assert 'id="editMode3d"' in index
    assert "Editable" in index
    assert 'id="labelShow3d"' not in index
    assert "function is3DMouseEditEnabled()" in manual3d
    assert "if (!is3DMouseEditEnabled()) return false;" in manual3d
    assert "if (!is3DMouseEditEnabled()) return;" in manual3d
    assert "window.is3DMouseEditEnabled" in annotation


def test_programmatic_label_state_defaults_to_visible_without_checkbox():
    api = _read("brachybot-ui-api.js")
    volume = _read("brachybot-viewer-volume.js")
    manual3d = _read("brachybot-3d-manual.js")
    assert "'3d':     { visible: true, opacity: 0.6 }" in api
    assert "const visible = view === '3d'" in volume
    assert "const labelShow = true;" in manual3d


def test_seed_mutation_merges_partial_needle_payload_but_delete_is_exact():
    manual3d = _read("brachybot-3d-manual.js")
    api = _read("brachybot-ui-api.js")
    monitor = _read("brachybot-monitor-interaction.js")
    assert "function _mergeManualNeedleRecords" in manual3d
    assert "preserveNeedleTopology: true" in manual3d
    assert "_applyAuthoritativeManualSeeds(data);" in manual3d
    assert "Needle deletion is the one manual mutation" in manual3d
    assert "monitor.edit.restored" in api
    assert "fallbackNeedles: typeof _currentManualNeedles" in api
    assert "monitor.candidate.applied" in monitor
    assert "fallbackNeedles: typeof _currentManualNeedles" in monitor


def test_workspace_spinner_closes_with_matching_scheduler_scope_and_deadline():
    workspace = _read("brachybot-workspace.js")
    assert "const forceHide = scope?.forceHide === true;" in workspace
    assert "__workspaceHydrationNoticeSuppressedSessionId" in workspace
    assert "timeoutMs: 15000, waitForCompletion: false" in workspace
    assert "optional visual producers continue after the user-facing restore deadline" in workspace
    assert "{ sessionId, runId: generation, forceHide: true }" in workspace


def test_edit_mode_is_not_persisted_as_case_presentation():
    workspace = _read("brachybot-workspace.js")
    assert "if (el.id === 'editMode3d') return;" in workspace
    assert "delete normalized.controls.labelShow3d;" in workspace
    assert "['overlayCTV', true], ['overlayOAR', true], ['editMode3d', false]" in workspace
