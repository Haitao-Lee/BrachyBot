(function() {
    const container = document.getElementById('dataTreeContainer');
    const handle = document.getElementById('dataTreeResize');
    if (!container || !handle) return;

    let startX, startWidth;
    handle.addEventListener('mousedown', (e) => {
        startX = e.clientX;
        startWidth = container.offsetWidth;
        document.addEventListener('mousemove', onDrag);
        document.addEventListener('mouseup', onDragEnd);
        e.preventDefault();
    });

    function onDrag(e) {
        const newWidth = Math.max(120, Math.min(400, startWidth + (e.clientX - startX)));
        container.style.width = newWidth + 'px';
    }

    function onDragEnd() {
        document.removeEventListener('mousemove', onDrag);
        document.removeEventListener('mouseup', onDragEnd);
        if (!(typeof window.isWorkspacePresentationRestoreActive === 'function'
            && window.isWorkspacePresentationRestoreActive())
            && typeof window.scheduleWorkspaceSave === 'function') {
            window.scheduleWorkspaceSave('viewer.data_tree.width');
        }
    }
})();

/******** TOOLTIPS ********/
function addTooltips() {
    const tooltips = {
        'windowPreset': 'Window/Level preset for CT display',
        'viewerWindow': 'Window width (contrast)',
        'viewerLevel': 'Window level (brightness)',
        'viewerZoom': 'Zoom level',
        'viewerThreshold': 'HU threshold for segmentation overlay',
        'displayMode': 'CT Only / CT+Label / Label Only display mode',
        'overlayCTV': 'Toggle Clinical Target Volume overlay',
        'overlayOAR': 'Toggle Organs at Risk overlay',
        'toolCrosshair': 'Crosshair tool - click to navigate',
        'toolMeasure': 'Measure distance between two points',
        'toolAngle': 'Measure angle between three points',
        'toolRect': 'Rectangle measurement tool',
        'toolZoombox': 'Zoom into a region',
        'toolAnnotate': 'Freehand drawing tool',
    };
    for (const [id, tip] of Object.entries(tooltips)) {
        const el = document.getElementById(id);
        if (el && !el.title) el.title = tip;
    }
    // Add tooltips to file buttons
    document.querySelectorAll('.file-btn').forEach(btn => {
        if (!btn.title) {
            const text = btn.textContent.trim();
            if (text.includes('FlipH')) btn.title = 'Flip image horizontally';
            else if (text.includes('FlipV')) btn.title = 'Flip image vertically';
            else if (text.includes('Rotate')) btn.title = 'Rotate image 90°';
            else if (text.includes('Undo')) btn.title = 'Undo last action';
            else if (text.includes('Redo')) btn.title = 'Redo last action';
            else if (text.includes('Reset')) btn.title = 'Reset viewer settings';
            else if (text.includes('3D')) btn.title = '3D reconstruction from threshold';
        }
    });
}
setTimeout(addTooltips, 1000);

function applyZoom(val) {
    state.viewerSettings.zoom = parseInt(val) / 100;
    document.getElementById('zoomLabel').textContent = val + '%';
    applyViewerTransform();
    if (typeof window.scheduleWorkspaceSave === 'function') {
        window.scheduleWorkspaceSave('viewer.zoom');
    }
}

function wrapViewersInRow(panel, mode) {
    const row = document.createElement('div');
    row.className = 'viewers-row';
    const axial = document.getElementById('viewerAxial');
    const sagittal = document.getElementById('viewerSagittal');
    const coronal = document.getElementById('viewerCoronal');
    const viewer3d = document.getElementById('viewer3d');
    if (axial && sagittal && coronal) {
        row.appendChild(axial);
        row.appendChild(sagittal);
        row.appendChild(coronal);
        if (mode === 'after-3d' && viewer3d) {
            // 3D on top: 3D first, then row
            panel.appendChild(viewer3d);
            panel.appendChild(row);
        } else if (mode === 'before-3d' && viewer3d) {
            // 3D on bottom: row first, then 3D
            panel.appendChild(row);
            panel.appendChild(viewer3d);
        } else {
            panel.appendChild(row);
        }
    }
}

// Unified resize state
const _resize = { active: false, type: null, card: null, cards: [], startPos: 0, startSizes: [], handle: null };

// Keep viewer geometry synchronization in one place. Browser zoom, fullscreen
// restore, and flex reparenting can otherwise make a canvas render against a
// stale or zero-sized container.
const _viewerGeometrySync = { generation: 0, timer: null };

/**
 * Capture pan in image-relative coordinates before a viewer card changes size.
 * Pixel pan values cannot be reused across normal and fullscreen layouts: the
 * same number of CSS pixels represents a different location in each layout.
 */
function captureViewerViewport(axis) {
    const canvas = getSliceCanvas(axis);
    if (!canvas) return null;
    const displayW = Number(canvas._displayW || canvas.offsetWidth || 0);
    const displayH = Number(canvas._displayH || canvas.offsetHeight || 0);
    if (displayW < 1 || displayH < 1) return null;
    return {
        axis,
        panFractionX: Number(state.viewerSettings.panX || 0) / displayW,
        panFractionY: Number(state.viewerSettings.panY || 0) / displayH,
    };
}
window.captureViewerViewport = captureViewerViewport;

function _restoreViewerViewport(snapshot) {
    if (!snapshot) return;
    const canvas = getSliceCanvas(snapshot.axis);
    if (!canvas) return;
    const displayW = Number(canvas._displayW || canvas.offsetWidth || 0);
    const displayH = Number(canvas._displayH || canvas.offsetHeight || 0);
    if (displayW < 1 || displayH < 1) return;
    state.viewerSettings.panX = Number(snapshot.panFractionX || 0) * displayW;
    state.viewerSettings.panY = Number(snapshot.panFractionY || 0) * displayH;
    if (typeof applyViewerTransform === 'function') applyViewerTransform();
}

function _clearViewerResizeOverrides(panel) {
    if (!panel) return;
    panel.querySelectorAll('.viewers-row, .viewer-card').forEach(el => {
        el.classList.remove('viewer-resized');
        el.style.removeProperty('--resize-h');
        el.style.removeProperty('height');
        el.style.removeProperty('width');
        el.style.removeProperty('flex');
    });
}

function syncViewerGeometry({ resetPositions = false, settleMs = 0, viewportSnapshot = null } = {}) {
    const generation = ++_viewerGeometrySync.generation;
    // A ResizeObserver callback may arrive between the immediate fullscreen
    // pass and its delayed settle pass. Do not let that harmless callback
    // cancel the settle measurement; only another explicit settled layout
    // transition supersedes it.
    if (_viewerGeometrySync.timer && settleMs > 0) {
        clearTimeout(_viewerGeometrySync.timer);
        _viewerGeometrySync.timer = null;
    }
    const render = (acceptNewerGeneration = false) => {
        if (!acceptNewerGeneration && generation !== _viewerGeometrySync.generation) return;
        if (resetPositions) {
            ['axial', 'sagittal', 'coronal'].forEach(axis => {
                [
                    getSliceCanvas(axis),
                    document.getElementById('crosshairCanvas' + capitalize(axis)),
                    document.getElementById('labelOverlay_' + capitalize(axis)),
                ].forEach(canvas => { if (canvas) canvas._posSet = false; });
            });
        }
        ['axial', 'sagittal', 'coronal'].forEach(axis => resizeCanvas(axis));
        _restoreViewerViewport(viewportSnapshot);
        // resizeCanvas establishes the CT geometry first. Reconcile every
        // dependent canvas only after that geometry and the restored viewport
        // have both settled, otherwise a dose/projection layer can retain the
        // previous session's left/top/transform until the user presses Fit.
        if (typeof window.reconcile2DViewerLayers === 'function') {
            window.reconcile2DViewerLayers({
                reason: 'viewer-geometry-sync',
                rerender: true,
            });
        }
        if (typeof window.resizeViewer3D === 'function') window.resizeViewer3D();
    };
    const schedule = (acceptNewerGeneration = false) => requestAnimationFrame(() =>
        requestAnimationFrame(() => render(acceptNewerGeneration)));
    // Measure once immediately so fullscreen never displays a stretched old
    // frame, then once more after flex/grid layout has fully settled.
    schedule();
    if (settleMs > 0) {
        _viewerGeometrySync.timer = setTimeout(() => {
            _viewerGeometrySync.timer = null;
            schedule(true);
        }, settleMs);
    }
}
window.syncViewerGeometry = syncViewerGeometry;

function _installViewerGeometryObserver() {
    const panel = document.getElementById('viewersPanel');
    if (!panel || panel._geometryObserver || typeof ResizeObserver === 'undefined') return;
    panel._geometryObserver = new ResizeObserver(() => syncViewerGeometry());
    // The panel itself does not resize when a child card is changed by the
    // horizontal handle. Observe the 3D card and its actual canvas host too;
    // this keeps the WebGL drawing buffer and camera aspect synchronized with
    // the rectangle the user can see.
    [panel, panel.querySelector('#viewer3d'), panel.querySelector('#canvas3D')]
        .filter(Boolean)
        .forEach(element => panel._geometryObserver.observe(element));
}

// Width resize (horizontal layout only): sync all viewer widths proportionally
function setupVerticalResize() {
    document.querySelectorAll('.viewer-resize-v').forEach(handle => {
        if (handle._resizeListener) return;
        handle._resizeListener = true;
        handle.addEventListener('mousedown', e => {
            const card = handle.previousElementSibling;
            if (!card || card.classList.contains('fullscreen')) return;
            const panel = document.getElementById('viewersPanel');
            const allCards = Array.from(panel.querySelectorAll('.viewer-card'));
            _resize.active = true;
            _resize.type = 'width';
            _resize.card = card;
            _resize.cards = allCards;
            _resize.startPos = e.clientX;
            _resize.startSizes = allCards.map(c => c.offsetWidth);
            _resize.totalWidth = panel.scrollWidth;
            _resize.handle = handle;
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });
    });
}

// Height resize: sync all viewers in the same row
function setupHorizontalResize() {
    document.querySelectorAll('.viewer-resize-h').forEach(handle => {
        if (handle._resizeListener) return;
        handle._resizeListener = true;
        handle.addEventListener('mousedown', e => {
            e.preventDefault();
            e.stopPropagation();
            // The resize handle is INSIDE the viewer-card (not a sibling).
            // Use closest() to find the parent viewer-card.
            const viewerCard = handle.closest('.viewer-card');
            if (!viewerCard) return;
            // Find all viewer-cards in the same parent (panel)
            const parent = viewerCard.parentElement;
            const allCards = Array.from(parent.querySelectorAll(':scope > .viewer-card'));
            _resize.active = true;
            _resize.type = 'height';
            _resize.card = viewerCard;
            _resize.cards = allCards;
            _resize.parent = parent;
            _resize.startPos = e.clientY;
            _resize.startSizes = allCards.map(c => c.offsetHeight);
            _resize.startParentH = parent.offsetHeight;
            _resize.handle = handle;
            document.body.style.cursor = 'row-resize';
            document.body.style.userSelect = 'none';
        });
    });
}

// Global mousemove: synchronized resize
document.addEventListener('mousemove', e => {
    if (!_resize.active || !_resize.cards.length) return;

    if (_resize.type === 'width') {
        // Width: all 4 viewers get the SAME width
        const delta = e.clientX - _resize.startPos;
        const minW = 150;
        const newW = Math.max(minW, _resize.startSizes[0] + delta);
        _resize.cards.forEach(card => {
            card.style.flex = `0 0 ${newW}px`;
        });
    } else {
        // Height: all cards in row get same new height
        const delta = e.clientY - _resize.startPos;
        const newH = Math.max(100, _resize.startSizes[0] + delta);
        const newHPx = newH + 'px';
        if (_resize.parent && _resize.parent.classList.contains('viewers-row')) {
            // Cards in a row — resize the ROW, not individual cards
            _resize.parent.style.setProperty('--resize-h', newHPx);
            _resize.parent.classList.add('viewer-resized');
        } else {
            // Vertical layout — resize each card directly.
            // Set BOTH the CSS variable AND inline flex/height to
            // guarantee the override regardless of CSS specificity.
            _resize.cards.forEach(card => {
                card.style.setProperty('--resize-h', newHPx);
                card.style.flex = '0 0 ' + newHPx;
                card.style.height = newHPx;
                card.classList.add('viewer-resized');
            });
        }
        // Resize canvases
        _resize.cards.forEach(card => {
            const axis = card.id.replace('viewer', '').toLowerCase();
            if (axis !== '3d') requestAnimationFrame(() => resizeCanvas(axis));
        });
    }
});

// Global mouseup
document.addEventListener('mouseup', () => {
    if (_resize.active) {
        const changed = !!_resize.active;
        _resize.active = false;
        _resize.card = null;
        _resize.cards = [];
        _resize.handle = null;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        if (changed
            && !(typeof window.isWorkspacePresentationRestoreActive === 'function'
                && window.isWorkspacePresentationRestoreActive())
            && typeof window.scheduleWorkspaceSave === 'function') {
            window.scheduleWorkspaceSave('viewer.geometry');
        }
    }
});

function setViewerLayout(layout, options = {}) {
    const panel = document.getElementById('viewersPanel');
    if (!panel) return;
    _installViewerGeometryObserver();
    panel.classList.remove('layout-grid', 'layout-horizontal', 'layout-vertical', 'layout-3d-top', 'layout-3d-bottom');
    _clearViewerResizeOverrides(panel);

    // Remove any existing viewers-row wrapper
    const existingRow = panel.querySelector('.viewers-row');
    if (existingRow) {
        while (existingRow.firstChild) panel.insertBefore(existingRow.firstChild, existingRow);
        existingRow.remove();
    }

    // Remove all dynamic resize handles
    panel.querySelectorAll('.viewer-resize-v').forEach(h => h.remove());

    // Show/hide horizontal resize handles based on layout
    const hHandles = panel.querySelectorAll('.viewer-resize-h');

    if (layout === 'grid') {
        panel.classList.add('layout-grid');
        // Grid: no height resize, cells fill evenly
        hHandles.forEach(h => h.style.display = 'none');
    } else if (layout === 'horizontal') {
        panel.classList.add('layout-horizontal');
        hHandles.forEach(h => h.style.display = 'none');
        // Mouse wheel scrolls horizontally ONLY when not over a viewer canvas
        if (!panel._hWheelHandler) {
            panel._hWheelHandler = e => {
                if (!panel.classList.contains('layout-horizontal')) return;
                // If mouse is over a viewer canvas, let it handle slice scrolling
                const overCanvas = e.target.closest('.viewer-card-canvas, .viewer-card-body, canvas');
                if (overCanvas) return;
                panel.scrollLeft += (e.deltaY || e.deltaX);
                e.preventDefault();
                e.stopPropagation();
            };
            panel.addEventListener('wheel', panel._hWheelHandler, { capture: true, passive: false });
        }
        // Add vertical resize handles for width dragging
        const cards = ['viewerAxial', 'viewerSagittal', 'viewerCoronal', 'viewer3d'];
        cards.forEach(id => {
            const card = document.getElementById(id);
            if (card) {
                const vHandle = document.createElement('div');
                vHandle.className = 'viewer-resize-v';
                vHandle.dataset.view = id.replace('viewer', '').toLowerCase();
                card.parentNode.insertBefore(vHandle, card.nextSibling);
            }
        });
        setupVerticalResize();
    } else if (layout === '3d-top') {
        panel.classList.add('layout-3d-top');
        hHandles.forEach(h => h.style.display = '');
        wrapViewersInRow(panel, 'after-3d');
        setupHorizontalResize();
    } else if (layout === '3d-bottom') {
        panel.classList.add('layout-3d-bottom');
        hHandles.forEach(h => h.style.display = '');
        wrapViewersInRow(panel, 'before-3d');
        setupHorizontalResize();
    } else {
        panel.classList.add('layout-vertical');
        hHandles.forEach(h => h.style.display = '');
        setupHorizontalResize();
    }
    // Update active button
    document.querySelectorAll('.layout-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.layout === layout);
    });
    state.viewerSettings.layout = layout;
    if (options.persist !== false
        && !(typeof window.isWorkspacePresentationRestoreActive === 'function'
            && window.isWorkspacePresentationRestoreActive())
        && typeof window.scheduleWorkspaceSave === 'function') {
        window.scheduleWorkspaceSave('viewer.layout');
    }
    // Wait for flex/grid geometry, then resize all viewers without changing
    // the user's camera pose or slice values.
    syncViewerGeometry({ resetPositions: true, settleMs: 150 });
}

function setViewerTool(tool) {
    // Clicking the already-active tool toggles it off (deselect + unhighlight).
    // This keeps the toolbar honest: pressing a highlighted tool again cancels
    // the mode instead of leaving it stuck on.
    if (tool !== 'crosshair' && state.viewerSettings.activeTool === tool) {
        state.viewerSettings.activeTool = null;
        if (window._annotationToolState) {
            window._annotationToolState.active = false;
            window._annotationToolState.points = [];
        }
        // For the Draw tool, toggling off also finalises the in-progress mask.
        if (tool === 'annotate' && state.activeMaskId && state.maskLabels?.[state.activeMaskId]) {
            const finalName = state.maskLabels[state.activeMaskId].name;
            state.activeMaskId = null;
            addChat('system', `Manual mask "${finalName}" finalised. Right-click it in the Data Tree to rename or move it.`);
        }
        const toolIds = ['toolCrosshair', 'toolMeasure', 'toolAngle', 'toolRect', 'toolZoombox', 'toolAnnotate', 'toolEraser', 'toolSat3dPositive', 'toolSat3dNegative'];
        toolIds.forEach(id => {
            const btn = document.getElementById(id);
            if (btn) btn.style.background = '';
        });
        ['axial', 'sagittal', 'coronal'].forEach(axis => {
            const canvas = document.getElementById('sliceCanvas' + capitalize(axis));
            if (canvas) canvas.style.cursor = 'default';
        });
        if (typeof window.scheduleWorkspaceSave === 'function') {
            window.scheduleWorkspaceSave('viewer.tool');
        }
        return;
    }
    state.viewerSettings.activeTool = tool;
    // Reset annotation tool state when switching tools
    if (window._annotationToolState) {
        window._annotationToolState.active = false;
        window._annotationToolState.points = [];
    }
    // The Draw tool is a manual-mask entry point: the first click creates a
    // new empty mask and enters painting; clicking Draw again (or another
    // tool) finalises it. Track the active mask so subsequent strokes merge
    // into it instead of spawning a new mask per stroke.
    if (tool === 'annotate') {
        if (state.activeMaskId && state.maskLabels?.[state.activeMaskId]) {
            // Finalise the current mask.
            const finalName = state.maskLabels[state.activeMaskId].name;
            state.activeMaskId = null;
            addChat('system', `Manual mask "${finalName}" finalised. Right-click it in the Data Tree to rename or move it.`);
        } else {
            const id = _startNewMask();
            state.activeMaskId = id;
            if (id) {
                const name = state.maskLabels[id].name;
                addChat('system', `Manual mask "${name}" created. Paint on the slices with the Draw tool; click Draw again to finalise.`);
            }
        }
    } else if (tool === 'eraser') {
        // Erase needs an active mask target; if none exists, erase is a no-op
        // hint. Do not auto-create here.
        if (!state.activeMaskId) {
            addChat('system', 'Erase removes voxels from the currently active mask. Click Draw first to create/paint a mask, then Erase.');
        }
    } else {
        // Selecting any other tool (including crosshair) finalises an
        // in-progress mask.
        if (state.activeMaskId && state.maskLabels?.[state.activeMaskId]) {
            const finalName = state.maskLabels[state.activeMaskId].name;
            state.activeMaskId = null;
            addChat('system', `Manual mask "${finalName}" finalised.`);
        }
    }
    const toolIds = ['toolCrosshair', 'toolMeasure', 'toolAngle', 'toolRect', 'toolZoombox', 'toolAnnotate', 'toolEraser', 'toolSat3dPositive', 'toolSat3dNegative'];
    toolIds.forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.style.background = '';
    });
    const toolMap = { crosshair: 'toolCrosshair', measure: 'toolMeasure', angle: 'toolAngle', rect: 'toolRect', zoombox: 'toolZoombox', annotate: 'toolAnnotate', eraser: 'toolEraser', sat3d_positive: 'toolSat3dPositive', sat3d_negative: 'toolSat3dNegative' };
    const activeBtn = document.getElementById(toolMap[tool]);
    if (activeBtn) activeBtn.style.background = 'var(--primary)';

    // Update cursor on all slice canvases
    const cursors = { crosshair: 'crosshair', measure: 'crosshair', angle: 'crosshair', rect: 'crosshair', zoombox: 'zoom-in', annotate: 'crosshair', eraser: 'cell', sat3d_positive: 'crosshair', sat3d_negative: 'crosshair' };
    ['axial', 'sagittal', 'coronal'].forEach(axis => {
        const canvas = document.getElementById('sliceCanvas' + capitalize(axis));
        if (canvas) canvas.style.cursor = cursors[tool] || 'default';
    });
    if (typeof window.scheduleWorkspaceSave === 'function') {
        window.scheduleWorkspaceSave('viewer.tool');
    }
}

// Restore only the visual affordance of the active tool.  Calling
// setViewerTool() during hydration is unsafe because selecting Draw creates a
// new mask and selecting another tool finalises the current one.  The tool is
// already persisted in viewerSettings; this helper synchronises buttons and
// cursors without creating or mutating clinical annotations.
function applyRestoredViewerToolPresentation() {
    const tool = state?.viewerSettings?.activeTool || null;
    const toolIds = [
        'toolCrosshair', 'toolMeasure', 'toolAngle', 'toolRect',
        'toolZoombox', 'toolAnnotate', 'toolEraser',
        'toolSat3dPositive', 'toolSat3dNegative',
    ];
    toolIds.forEach(id => {
        const button = document.getElementById(id);
        if (button) button.style.background = '';
    });
    const toolMap = {
        crosshair: 'toolCrosshair',
        measure: 'toolMeasure',
        angle: 'toolAngle',
        rect: 'toolRect',
        zoombox: 'toolZoombox',
        annotate: 'toolAnnotate',
        eraser: 'toolEraser',
        sat3d_positive: 'toolSat3dPositive',
        sat3d_negative: 'toolSat3dNegative',
    };
    const activeButton = document.getElementById(toolMap[tool]);
    if (activeButton) activeButton.style.background = 'var(--primary)';
    const cursors = {
        crosshair: 'crosshair',
        measure: 'crosshair',
        angle: 'crosshair',
        rect: 'crosshair',
        zoombox: 'zoom-in',
        annotate: 'crosshair',
        eraser: 'cell',
        sat3d_positive: 'crosshair',
        sat3d_negative: 'crosshair',
    };
    ['axial', 'sagittal', 'coronal'].forEach(axis => {
        const canvas = document.getElementById('sliceCanvas' + capitalize(axis));
        if (canvas) canvas.style.cursor = cursors[tool] || 'default';
    });
    return tool;
}
window.applyRestoredViewerToolPresentation = applyRestoredViewerToolPresentation;

function fitView() {
    // Lightweight reset: only center and fit, preserve window/level and other settings
    state.viewerSettings.zoom = 1.0;
    state.viewerSettings.panX = 0;
    state.viewerSettings.panY = 0;
    state.viewerSettings.flipH = false;
    state.viewerSettings.flipV = false;
    state.viewerSettings.rotation = 0;
    document.getElementById('viewerZoom').value = 100;
    document.getElementById('zoomLabel').textContent = '100%';
    // Reset base position so next renderSliceFromVolume re-centers
    ['axial', 'sagittal', 'coronal'].forEach(axis => {
        const canvas = getSliceCanvas(axis);
        if (canvas) { canvas._posSet = false; }
        const crossCanvas = document.getElementById('crosshairCanvas' + capitalize(axis));
        if (crossCanvas) { crossCanvas._posSet = false; }
        const overlayCanvas = document.getElementById('labelOverlay_' + capitalize(axis));
        if (overlayCanvas) { overlayCanvas._posSet = false; }
    });
    applyViewerTransform();
    if (state.ctLoaded) loadAllSlices();
    syncViewerGeometry({ resetPositions: true, settleMs: 80 });
    if (typeof window.scheduleWorkspaceSave === 'function') {
        window.scheduleWorkspaceSave('viewer.fit');
    }
}

// Session restore is different from an operator pressing Fit: the CT canvas,
// dose/contour layers, and the WebGL scene become ready in separate async
// phases.  Keep their final framing in one transaction so a restored case
// cannot leave the MPR panes black or leave an overlay at the previous case's
// pixel offset.  This helper is intentionally session-scoped and idempotent;
// a late pass from an older restore must never fit the currently active case.
let _workspaceViewerFitGeneration = 0;
async function fitAllViewersAfterWorkspaceRestore({
    sessionId = null,
    reason = 'workspace-restore-fit',
    preserveSavedView = false,
} = {}) {
    const generation = ++_workspaceViewerFitGeneration;
    const requestedSessionId = String(sessionId || '');
    const isCurrent = () => {
        if (generation !== _workspaceViewerFitGeneration) return false;
        if (!requestedSessionId) return true;
        // `activeSessionId` is a global lexical binding in chat-core.js, not
        // a window property. Prefer the same authoritative helper used by
        // API requests, then fall back to the binding/state for legacy boot
        // paths. Reading only window.activeSessionId allowed a late restore
        // pass to fit the wrong case when the browser had just switched.
        const active = String(
            (typeof _activeApiSessionId === 'function' && _activeApiSessionId())
            || (typeof activeSessionId !== 'undefined' && activeSessionId)
            || window.activeSessionId
            || state?.sessionId
            || ''
        );
        return !active || active === requestedSessionId;
    };
    const waitPaint = () => new Promise(resolve => {
        const raf = typeof window.requestAnimationFrame === 'function'
            ? window.requestAnimationFrame.bind(window)
            : callback => setTimeout(callback, 0);
        raf(() => setTimeout(resolve, 0));
    });

    if (!isCurrent()) return false;
    // A saved workspace view is an operator choice, not a request to Fit.
    // Only use the visible Fit behavior for legacy/empty snapshots that have
    // no valid camera pose.
    if (!preserveSavedView && typeof fitView === 'function') fitView();
    await waitPaint();
    if (!isCurrent()) return false;

    // Wait for the volume renderer to repaint all planes before the geometry
    // pass.  This matters on cold restart where the first render can otherwise
    // establish a zero/old-size canvas and make the dose contour disappear.
    if (typeof loadAllSlices === 'function' && state?.ctLoaded) {
        await loadAllSlices();
    }
    if (!isCurrent()) return false;
    if (typeof syncViewerGeometry === 'function') {
        syncViewerGeometry({
            resetPositions: !preserveSavedView,
            settleMs: 120,
        });
    }
    await waitPaint();
    await waitPaint();
    if (!isCurrent()) return false;

    if (typeof window.reconcile2DViewerLayers === 'function') {
        window.reconcile2DViewerLayers({
            reason,
            rerender: true,
            immediate: true,
        });
    }
    if (typeof window.resizeViewer3D === 'function') window.resizeViewer3D();
    if (preserveSavedView) {
        // Reapply the Data Tree-owned visibility/opacity after all late meshes
        // exist, but do not recenter the camera or alter the saved 2D pose.
        window.applyDataTreeViewVisibility?.();
        window.syncSceneAppearanceFromDataTree?.({ preserveDoseTexture: true });
    } else if (typeof window.ensureCameraFitsVisibleScene === 'function') {
        window.ensureCameraFitsVisibleScene({ forceCenter: true, reason });
    }
    if (typeof window.forceRender3DViewer === 'function') window.forceRender3DViewer();
    // This helper runs outside init3DScene(), so it must use the scheduler
    // owned by the live scene rather than an optional local render closure.
    else if (typeof scene3D !== 'undefined' && typeof scene3D.requestRender === 'function') {
        scene3D.requestRender(4);
    }
    return true;
}
window.fitAllViewersAfterWorkspaceRestore = fitAllViewersAfterWorkspaceRestore;

function resetViewer() {
    state.viewerSettings = {
        window: 400, level: 40, threshold: null,
        showCTV: false, showOAR: false, zoom: 1.0,
        userConfigured: false,
        activeTool: null, panX: 0, panY: 0,
        flipH: false, flipV: false, rotation: 0,
        displayMode: 'ct',
    };
    state.annotations = [];
    state.annotationUndoStack = [];
    state.annotationRedoStack = [];
    document.getElementById('viewerWindow').value = 400;
    document.getElementById('viewerLevel').value = 40;
    document.getElementById('viewerThreshold').value = '';
    document.getElementById('viewerZoom').value = 100;
    document.getElementById('zoomLabel').textContent = '100%';
    document.getElementById('overlayCTV').checked = false;
    document.getElementById('overlayOAR').checked = false;
    ['axial', 'sagittal', 'coronal'].forEach(axis => {
        const canvas = document.getElementById('sliceCanvas' + capitalize(axis));
        if (canvas) {
            canvas.style.transform = 'scale(1)';
            canvas.style.transformOrigin = 'center center';
            canvas._posSet = false;
        }
        const crossCanvas = document.getElementById('crosshairCanvas' + capitalize(axis));
        if (crossCanvas) crossCanvas._posSet = false;
        const overlayCanvas = document.getElementById('labelOverlay_' + capitalize(axis));
        if (overlayCanvas) overlayCanvas._posSet = false;
        const annCanvas = document.getElementById('annotationCanvas' + capitalize(axis));
        if (annCanvas) {
            const ctx = annCanvas.getContext('2d');
            ctx.clearRect(0, 0, annCanvas.width, annCanvas.height);
        }
    });
    if (state.ctLoaded) loadAllSlices();
    syncViewerGeometry({ resetPositions: true, settleMs: 80 });
}

function renderSliceToCanvas(axis, sliceData, sliceIndex = state.slices?.[axis]) {
    const renderGeneration = window.__viewerRenderGeneration || 0;
    const canvasId = 'sliceCanvas' + capitalize(axis);
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const container = canvas.parentElement;

    // Check if it's a base64 PNG
    if (typeof sliceData === 'string' && sliceData.startsWith('data:image/png;base64,')) {
        const img = new Image();
        img.onload = () => {
            if (renderGeneration !== (window.__viewerRenderGeneration || 0)) return;
            // PNG decoding is asynchronous. A result for an older slider
            // position must never replace the CT frame currently requested.
            if (Number(state.slices?.[axis]) !== Number(sliceIndex)) return;
            // Calculate display size maintaining aspect ratio
            const containerRect = container.getBoundingClientRect();
            const containerW = containerRect.width;
            const containerH = containerRect.height;
            const imgW = img.width;
            const imgH = img.height;

            // Fit image to container while maintaining aspect ratio
            const scale = Math.min(containerW / imgW, containerH / imgH);
            const displayW = imgW * scale;
            const displayH = imgH * scale;

            // Set canvas display size
            canvas.style.width = displayW + 'px';
            canvas.style.height = displayH + 'px';
            canvas.style.position = 'absolute';
            // BUG FIX 2026-06-16 (dose map persistence): if the
            // slice canvas has been wrapped in a transform-host
            // (because the dose overlay was activated), position
            // the slice relative to the WRAPPER (which now hosts
            // both slice + dose) — not relative to the original
            // .viewer-card-canvas container.
            const posParent = canvas._doseWrapper || container;
            if (!canvas._posSet || canvas._posContainerW !== containerW || canvas._posContainerH !== containerH) {
                canvas.style.left = ((containerW - displayW) / 2) + 'px';
                canvas.style.top = ((containerH - displayH) / 2) + 'px';
                canvas._posSet = true;
                canvas._posContainerW = containerW;
                canvas._posContainerH = containerH;
            }
            // Size the wrapper to match the container so the
            // slice canvas (positioned absolutely inside) has
            // the right coordinate space. Without this, the
            // wrapper would collapse to 0x0 since it only has
            // absolutely-positioned children. Note: the wrapper
            // itself uses width:100%;height:100% to fill the
            // flex parent, so explicit sizing here is only a
            // safety net for browsers that don't auto-size
            // absolute children.
            if (canvas._doseWrapper) {
                canvas._doseWrapper.style.width = containerW + 'px';
                canvas._doseWrapper.style.height = containerH + 'px';
                // ALSO make sure the slice canvas itself fills
                // the wrapper, since the wrapper's flex-sizing
                // doesn't auto-size the absolutely-positioned
                // child.
                canvas.style.width = Math.min(displayW, containerW) + 'px';
                canvas.style.height = Math.min(displayH, containerH) + 'px';
            }
            canvas.style.margin = '0';

            // Set actual canvas resolution
            canvas.width = imgW;
            canvas.height = imgH;

            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.drawImage(img, 0, 0);
            canvas.style.display = 'block';

            const placeholder = container.querySelector('.viewer-no-data');
            if (placeholder) placeholder.style.display = 'none';

            // Store CT geometry before any dependent layer is resized. The
            // server-slice fallback used to update annotations first, causing
            // overlays restored after a restart to use a stale display box.
            canvas._displayScale = scale;
            canvas._displayW = displayW;
            canvas._displayH = displayH;
            canvas._offsetX = (containerW - displayW) / 2;
            canvas._offsetY = (containerH - displayH) / 2;

            if (typeof window.mark2DViewerBaseSliceRendered === 'function') {
                window.mark2DViewerBaseSliceRendered(axis, sliceIndex);
            } else {
                canvas.dataset.requestedAxis = axis;
                canvas.dataset.requestedSlice = String(sliceIndex);
                canvas.dataset.renderedAxis = axis;
                canvas.dataset.renderedSlice = String(sliceIndex);
            }

            // Update crosshair canvas size
            const crossCanvas = document.getElementById('crosshairCanvas' + capitalize(axis));
            if (crossCanvas) {
                crossCanvas.width = displayW;
                crossCanvas.height = displayH;
                crossCanvas.style.width = displayW + 'px';
                crossCanvas.style.height = displayH + 'px';
                crossCanvas.style.position = 'absolute';
                if (!crossCanvas._posSet || crossCanvas._posContainerW !== containerW || crossCanvas._posContainerH !== containerH) {
                    crossCanvas.style.left = ((containerW - displayW) / 2) + 'px';
                    crossCanvas.style.top = ((containerH - displayH) / 2) + 'px';
                    crossCanvas._posSet = true;
                    crossCanvas._posContainerW = containerW;
                    crossCanvas._posContainerH = containerH;
                }
            }

            // Update annotation canvas size
            syncAnnotationCanvasSize(axis);
            redrawAllAnnotations();
            if (typeof window.reconcile2DViewerLayers === 'function') {
                window.reconcile2DViewerLayers({
                    reason: 'server-slice-decoded',
                    rerender: true,
                });
            }
        };
        img.src = sliceData;
        return;
    }

    // Fallback: handle raw array data (legacy)
    const isRGB = Array.isArray(sliceData[0]) && Array.isArray(sliceData[0][0]);

    if (isRGB) {
        canvas.width = sliceData[0].length;
        canvas.height = sliceData.length;
        const imageData = ctx.createImageData(canvas.width, canvas.height);
        for (let y = 0; y < sliceData.length; y++) {
            for (let x = 0; x < sliceData[y].length; x++) {
                const idx = (y * canvas.width + x) * 4;
                imageData.data[idx] = sliceData[y][x][0];
                imageData.data[idx + 1] = sliceData[y][x][1];
                imageData.data[idx + 2] = sliceData[y][x][2];
                imageData.data[idx + 3] = 255;
            }
        }
        ctx.putImageData(imageData, 0, 0);
    } else {
        canvas.width = sliceData[0].length;
        canvas.height = sliceData.length;
        const imageData = ctx.createImageData(canvas.width, canvas.height);
        for (let y = 0; y < sliceData.length; y++) {
            for (let x = 0; x < sliceData[y].length; x++) {
                const idx = (y * canvas.width + x) * 4;
                const val = sliceData[y][x];
                imageData.data[idx] = val;
                imageData.data[idx + 1] = val;
                imageData.data[idx + 2] = val;
                imageData.data[idx + 3] = 255;
            }
        }
        ctx.putImageData(imageData, 0, 0);
    }

    canvas.style.display = 'block';
    if (typeof window.mark2DViewerBaseSliceRendered === 'function') {
        window.mark2DViewerBaseSliceRendered(axis, sliceIndex);
    } else {
        canvas.dataset.requestedAxis = axis;
        canvas.dataset.requestedSlice = String(sliceIndex);
        canvas.dataset.renderedAxis = axis;
        canvas.dataset.renderedSlice = String(sliceIndex);
    }
    const placeholder = canvas.parentElement.querySelector('.viewer-no-data');
    if (placeholder) placeholder.style.display = 'none';

    if (state.viewerSettings.zoom !== 1.0) {
        canvas.style.transform = `scale(${state.viewerSettings.zoom})`;
        canvas.style.transformOrigin = 'center center';
    }
}

let _sliceRenderGeneration = 0;

function _yieldViewerPaint() {
    return new Promise(resolve => {
        const raf = typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function'
            ? window.requestAnimationFrame.bind(window)
            : callback => setTimeout(callback, 0);
        raf(() => setTimeout(resolve, 0));
    });
}

async function loadAllSlices() {
    if (!state.ctPath) return;
    const generation = ++_sliceRenderGeneration;

    // Use volume-based rendering for instant response
    if (volumeData && volumeShape) {
        for (const axis of ['axial', 'sagittal', 'coronal']) {
            if (generation !== _sliceRenderGeneration) return;
            renderSliceFromVolume(axis, state.slices[axis]);
            // Let the browser paint the active spinner and the completed
            // plane before the next expensive MPR pass. This also keeps
            // threshold/overlay changes responsive on large CT volumes.
            await _yieldViewerPaint();
            if (generation !== _sliceRenderGeneration) return;
        }
        if (typeof window.reconcile2DViewerLayers === 'function') {
            window.reconcile2DViewerLayers({
                reason: 'all-volume-slices-loaded',
                rerender: true,
            });
        }
        return;
    }

    // Fallback to server-based rendering
    await Promise.all([
        loadSlice('axial', state.slices.axial),
        loadSlice('sagittal', state.slices.sagittal),
        loadSlice('coronal', state.slices.coronal),
    ]);
    if (generation !== _sliceRenderGeneration) return;
    if (typeof window.reconcile2DViewerLayers === 'function') {
        window.reconcile2DViewerLayers({
            reason: 'all-server-slices-loaded',
            rerender: true,
        });
    }
}

// BUG FIX 2026-06-17 (3D default reconstruction): the previous
// `reconstruct3D` only fetched the CTV as a single marching-cubes
// mesh, producing a "Brachround red box" (a single iso-surface
// from the CTV mask). The user wanted:
//   1. Default = CTV + non-traversable OARs (e.g. arteries/veins/
//      bones) under CTV/OAR — these are the structures the
//      planning pipeline treats as obstacles.
//   2. For planning runs, also reconstruct seeds, needles, and
//      iso surfaces.
//   3. Default opacity from hyperparam config (display_3d) so the
//      user can tune globally; per-mesh overrides via the data
//      tree still work.
//   4. Compatible with the data tree's per-mesh visibility + opacity
//      controls — addMeshToScene already mirrors each mesh into
//      dataTreeState.planning.meshes, so the data tree sees the new
//      meshes automatically.
let _3dConfigCache = null;
let _viewer3DRequestGeneration = 0;

function _activeViewer3DSessionId() {
    if (typeof activeSessionId !== 'undefined' && activeSessionId) return String(activeSessionId);
    return String(state?.sessionId || '');
}

function _captureViewer3DRequestScope() {
    return {
        generation: _viewer3DRequestGeneration,
        sessionId: _activeViewer3DSessionId(),
    };
}

function _viewer3DRequestScopeIsCurrent(scope) {
    return !!scope
        && scope.generation === _viewer3DRequestGeneration
        && scope.sessionId === _activeViewer3DSessionId()
        && (!state?.sessionId || scope.sessionId === String(state.sessionId));
}

async function _viewer3DJsonRequest(url, init = {}, options = {}) {
    const requestHelper = window.fetchViewerJsonWithRetry;
    if (typeof requestHelper !== 'function') {
        throw new Error('Viewer request helper is not available');
    }
    const request = await requestHelper(url, init, {
        requestTimeoutMs: Number(options.requestTimeoutMs) || 120000,
        maxWaitMs: Number(options.maxWaitMs) || 300000,
    });
    if (!request.response) {
        throw request.error || new Error('Viewer resource request timed out');
    }
    return request;
}

function _viewer3DRequestHeaders(scope, headers = {}) {
    return {
        ...headers,
        ...(scope?.sessionId ? { 'X-BrachyBot-Session': scope.sessionId } : {}),
    };
}

// 3D reconstruction has several independent producers (manual requests,
// planning restore, segmentation prewarm, and dose surfaces).  A single
// boolean loading flag is incorrect when one producer finishes while another
// is still decoding meshes: the first completion hides the overlay for the
// whole scene.  Track ownership tokens instead, so loading ends only after the
// last real 3D task settles.  Workspace switches can reset the token set; late
// task finalizers are deliberately harmless when their token was invalidated.
const _viewer3DLoadingState = {
    nextToken: 0,
    tokens: new Map(),
};

function _renderViewer3DLoading() {
    const loading = document.getElementById('loading3D');
    if (!loading) return;
    const active = _viewer3DLoadingState.tokens.size > 0;
    // The HTML starts with the hidden attribute for a zero-flash initial render.
    // Toggle the attribute as well as the class; CSS/UA hidden rules otherwise
    // keep the progress indicator invisible forever.
    loading.hidden = !active;
    // Loading is progressive and must never become an input boundary.  Keep
    // this runtime guard as well as the stylesheet contract so a mixed-cache
    // tab cannot put an older blocking overlay in front of OrbitControls.
    loading.style.pointerEvents = 'none';
    loading.dataset.interactionMode = 'passthrough';
    loading.classList.toggle('active', active);
    loading.setAttribute('aria-hidden', active ? 'false' : 'true');
    const canvas = document.getElementById('canvas3D');
    if (canvas) canvas.setAttribute('aria-busy', active ? 'true' : 'false');
    const text = loading.querySelector('.loading-text');
    if (text) {
        const messages = [..._viewer3DLoadingState.tokens.values()]
            .filter(Boolean);
        text.textContent = messages.length ? messages[messages.length - 1] : 'Rendering...';
    }
}

function beginViewer3DLoading(message = 'Rendering...') {
    const token = ++_viewer3DLoadingState.nextToken;
    _viewer3DLoadingState.tokens.set(token, String(message || 'Rendering...'));
    _renderViewer3DLoading();
    return token;
}

function updateViewer3DLoading(token, message) {
    if (token == null || !_viewer3DLoadingState.tokens.has(token)) return;
    _viewer3DLoadingState.tokens.set(token, String(message || 'Rendering...'));
    _renderViewer3DLoading();
}

function endViewer3DLoading(token) {
    if (token != null) _viewer3DLoadingState.tokens.delete(token);
    _renderViewer3DLoading();
}

function resetViewer3DLoading() {
    _viewer3DLoadingState.tokens.clear();
    _renderViewer3DLoading();
}

window.beginViewer3DLoading = beginViewer3DLoading;
window.updateViewer3DLoading = updateViewer3DLoading;
window.endViewer3DLoading = endViewer3DLoading;
window.resetViewer3DLoading = resetViewer3DLoading;

function invalidateViewer3DRequests() {
    _viewer3DRequestGeneration += 1;
    return _viewer3DRequestGeneration;
}
window.invalidateViewer3DRequests = invalidateViewer3DRequests;
async function _get3DConfig() {
    if (_3dConfigCache) return _3dConfigCache;
    try {
        const resp = await fetch(API + '/config');
        if (resp.ok) {
            const j = await resp.json();
            if (j.success && j.defaults && j.defaults.display_3d) {
                _3dConfigCache = j.defaults.display_3d;
                return _3dConfigCache;
            }
        }
    } catch (e) {}
    // Hard-coded fallback matching default_params.json
    _3dConfigCache = {
        default_opacity: 0.7,
        ctv_color: '#ff304c',
        oar_non_traversable_color: '#e58a48',
        oar_traversable_color: '#3ccb8f',
        seed_color: '#facc15',
        needle_color: '#a855f7',
        seed_opacity: 0.95,
        needle_opacity: 0.85,
        ctv_opacity: 0.65,
        oar_opacity: 0.55,
        show_isosurfaces_by_default: false,
        show_seeds_by_default: true,
        show_needles_by_default: true,
    };
    return _3dConfigCache;
}

async function reconstruct3D() {
    const requestScope = _captureViewer3DRequestScope();
    if (!state.ctPath || !state.ctLoaded) {
        try {
            const resp = await fetch(API + '/status', {
                headers: _viewer3DRequestHeaders(requestScope),
            });
            if (resp.ok) {
                const sd = await resp.json();
                if (!_viewer3DRequestScopeIsCurrent(requestScope)) return { stale: true };
                if (sd.ct_path) {
                    state.ctPath = sd.ct_path;
                    state.ctLoaded = true;
                }
                if (!volumeData && sd.ct_loaded) {
                    await loadVolumeData();
                }
                if (!_viewer3DRequestScopeIsCurrent(requestScope)) return { stale: true };
            }
        } catch (e) {}
    }
    if (!_viewer3DRequestScopeIsCurrent(requestScope)) return { stale: true };
    if (!state.ctPath) {
        addChat('error', 'No CT image loaded');
        return;
    }

    const loadingToken = beginViewer3DLoading('Rendering 3D scene...');

    try {
        // 1) CTV + non-traversable OARs (the structures the planning
        //    pipeline actually cares about). This replaces the old
        //    "single red box from CTV" default that the user
        //    complained about — those meshes are real, segmentable
        //    surfaces, not just an iso-contour.
        await loadCTVAndObstacleMeshes();
        if (!_viewer3DRequestScopeIsCurrent(requestScope)) return { stale: true };

        // Threshold/manual masks are independent Data Tree segmentation
        // nodes. Reconstruct every persisted threshold mask when the user
        // presses the toolbar 3D button so it cannot silently remain a 2D-only
        // transient overlay.
        const thresholdMasks = Object.keys(state.maskLabels || {})
            .filter(maskId => state.maskLabels[maskId]?.kind === 'threshold');
        for (const maskId of thresholdMasks) {
            if (!_viewer3DRequestScopeIsCurrent(requestScope)) return { stale: true };
            try { await reconstructOrgan3D(maskId, true); } catch (error) {
                console.warn('[viewer] threshold mask reconstruction skipped:', error);
            }
        }
        if (dataTreeState.skin?.loaded && isDataTreeNodeVisible3D(dataTreeState.skin)) {
            try { await reconstructOrgan3D('skin_surface', true); } catch (error) {
                console.warn('[viewer] guide skin reconstruction skipped:', error);
            }
        }

        // 2) For planning runs, also reconstruct seeds, needles,
        //    and iso surfaces. The user can disable any of these
        //    via the data tree (which already mirrors them as
        //    planning.meshes entries).
        const hasPlanning = (state && state.metrics
            && (state.metrics.total_seeds || state.metrics.trajectories
                || state.metrics.v100 || state.metrics.d90));
        if (hasPlanning) {
            const cfg = await _get3DConfig();
            if (cfg.show_seeds_by_default && typeof loadSeeds3D === 'function') {
                try { await loadSeeds3D(); } catch (e) { console.warn('loadSeeds3D failed:', e); }
            }
            if (!_viewer3DRequestScopeIsCurrent(requestScope)) return { stale: true };
            if (typeof loadAllIsoSurfaces === 'function') {
                try {
                    await loadAllIsoSurfaces({
                        reconstruct3d: cfg.show_isosurfaces_by_default !== false,
                    });
                } catch (e) { console.warn('loadAllIsoSurfaces failed:', e); }
            }
        }
    } catch (e) {
        if (_viewer3DRequestScopeIsCurrent(requestScope)) {
            addChat('error', '3D reconstruction failed: ' + e.message);
        }
    } finally {
        endViewer3DLoading(loadingToken);
    }
}

// 3D reconstruction for individual organs from data tree
//
// Restore, segmentation prewarm, and a user clicking the same tree action can
// all reach this function during a cold restart. Coalesce identical
// case/generation requests so they cannot issue duplicate mesh requests or
// publish duplicate rate-limit errors.
const _organ3DReconstructionInFlight = new Map();

// Tolerant wrapper for render3DMesh. brachybot-3d-manual.js is loaded
// AFTER this file in index.html, so during version-skew (e.g. a stale
// cached 3d-manual without the render3DMesh top-level binding) the bare
// call raised "render3DMesh is not defined" and aborted the whole 3D
// reconstruction, leaving CTV/OAR/seed/needle/DVH/surgical guide blank.
// Fall back to addMeshToScene (same module, also global) when available,
// otherwise surface a concrete hint instead of a silent ReferenceError.
function _safeRender3DMesh(meshData) {
    const fn = (typeof window.render3DMesh === 'function')
        ? window.render3DMesh
        : (typeof render3DMesh === 'function' ? render3DMesh : null);
    if (fn) return fn(meshData);
    if (typeof window.addMeshToScene === 'function') {
        return window.addMeshToScene(meshData);
    }
    throw new Error('render3DMesh module not loaded; please refresh the page to reload viewer scripts.');
}

function getCtvMeshLabelIds() {
    const ids = new Set();
    Object.keys(window._ctvLabelMap || {}).forEach(value => {
        const n = Number(value);
        if (Number.isFinite(n) && n > 0) ids.add(n);
    });
    Object.keys((typeof dataTreeState !== 'undefined' && dataTreeState.ctvLabels) || {}).forEach(value => {
        const n = Number(String(value).replace(/^ctv_/, ''));
        if (Number.isFinite(n) && n > 0) ids.add(n);
    });
    // A missing label map means a legacy/binary CTV mask, whose foreground
    // label is 1. Never assume pancreas-specific labels for another tumor site.
    if (ids.size === 0) ids.add(1);
    return [...ids].sort((a, b) => a - b);
}

async function reconstructOrgan3D(id, silent = false) {
    const requestScope = _captureViewer3DRequestScope();
    const key = `${requestScope.sessionId}:${String(id)}`;
    const existing = _organ3DReconstructionInFlight.get(key);
    if (existing && _viewer3DRequestScopeIsCurrent(existing.scope)) {
        return existing.promise;
    }
    const promise = _reconstructOrgan3D(id, silent, requestScope);
    _organ3DReconstructionInFlight.set(key, { scope: requestScope, promise });
    try {
        const result = await promise;
        return _normalizeViewer3DResult(result);
    } finally {
        if (_organ3DReconstructionInFlight.get(key)?.promise === promise) {
            _organ3DReconstructionInFlight.delete(key);
        }
    }
}

function _viewer3DText(zh, en) {
    if (typeof window._t === 'function') return window._t(zh, en);
    if (typeof _dtText === 'function') return _dtText(zh, en);
    try {
        return document.documentElement.lang?.toLowerCase().startsWith('zh') ? zh : en;
    } catch (_) {
        return en;
    }
}

function _viewer3DNodeForId(id) {
    try {
        if (typeof _findDataTreeNode === 'function') {
            const node = _findDataTreeNode(id);
            if (node) return node;
        }
    } catch (_) {}
    if (typeof dataTreeState === 'undefined') return null;
    if (id === 'ctv') return dataTreeState.ctv || null;
    if (id === 'skin_surface') return dataTreeState.skin || null;
    if (String(id).startsWith('ctv_')) return dataTreeState.ctvLabels?.[id] || null;
    if (String(id).startsWith('organ_')) {
        return (dataTreeState.organs || []).find(item => item.id === id) || null;
    }
    if (typeof state !== 'undefined' && state.maskLabels?.[id]) return state.maskLabels[id];
    return null;
}

function _setViewer3DNodeState(id, patch = {}) {
    const node = _viewer3DNodeForId(id);
    if (!node) return null;
    Object.assign(node, patch);
    try {
        if (typeof renderDataTree === 'function') renderDataTree();
    } catch (_) {}
    return node;
}

function _normalizeViewer3DResult(result) {
    if (result && typeof result === 'object') {
        if (result.stale === true) return { ...result, success: false };
        if (result.success === false || result.success === true) return result;
        if (result.pending === true || result.error) return { ...result, success: false };
        return { ...result, success: true };
    }
    return {
        success: false,
        error: result === false
            ? '3D reconstruction did not produce a mesh.'
            : '3D reconstruction returned no result.',
    };
}

async function _reconstructOrgan3D(id, silent = false, scope = null) {
    const requestScope = scope || _captureViewer3DRequestScope();
    const nodeId = String(id);
    if (!state.ctPath || !state.ctLoaded) {
        try {
            const resp = await fetch(API + '/status', {
                headers: _viewer3DRequestHeaders(requestScope),
            });
            if (resp.ok) {
                const sd = await resp.json();
                if (!_viewer3DRequestScopeIsCurrent(requestScope)) return { success: false, stale: true };
                if (sd.ct_path) {
                    state.ctPath = sd.ct_path;
                    state.ctLoaded = true;
                }
                if (!volumeData && sd.ct_loaded) {
                    await loadVolumeData();
                }
                if (!_viewer3DRequestScopeIsCurrent(requestScope)) return { success: false, stale: true };
            }
        } catch (_) {}
    }
    if (!_viewer3DRequestScopeIsCurrent(requestScope)) return { success: false, stale: true };
    if (!state.ctPath) {
        const error = _viewer3DText('尚未加载 CT 图像，无法执行 3D 重建。', 'No CT image is loaded for 3D reconstruction.');
        _setViewer3DNodeState(nodeId, { loading: false, status: 'error', error });
        if (!silent && typeof addChat === 'function') addChat('error', error);
        return { success: false, error };
    }

    _setViewer3DNodeState(nodeId, { loading: true, status: 'loading', error: null });
    const loadingToken = beginViewer3DLoading(
        nodeId === 'ctv'
            ? _viewer3DText('正在重建 CTV 表面…', 'Reconstructing CTV surfaces...')
            : _viewer3DText('正在重建 3D 表面…', 'Reconstructing 3D surface...'),
    );

    try {
        if (nodeId === 'skin_surface') {
            return await _reconstructGuideSkinSurface3D(silent);
        }

        // CTV is a multi-label object. Every persisted target label is
        // reconstructed independently and reported as one truthful operation.
        if (nodeId === 'ctv') {
            const labelIds = getCtvMeshLabelIds();
            let successCount = 0;
            let failedCount = 0;
            for (let i = 0; i < labelIds.length; i++) {
                const labelId = labelIds[i];
                try {
                    const request = await _viewer3DJsonRequest(API + '/viewer/3d_mask', {
                        method: 'POST',
                        headers: _viewer3DRequestHeaders(requestScope, { 'Content-Type': 'application/json' }),
                        body: JSON.stringify({
                            label_id: labelId,
                            source: 'ctv',
                            smoothing: 1,
                            allow_missing: silent,
                        }),
                    });
                    const res = request.response;
                    const errData = request.data || {};
                    if (!res.ok) {
                        const errMsg = errData.error || errData.message || ('HTTP ' + res.status);
                        if (res.status === 400 && errMsg.includes('not found')) continue;
                        if (silent && [202, 404, 409, 429].includes(res.status)) {
                            failedCount++;
                            continue;
                        }
                        throw new Error(errMsg);
                    }
                    const data = request.data || {};
                    if (!_viewer3DRequestScopeIsCurrent(requestScope)) return { success: false, stale: true };
                    if (data.success && data.vertex_count > 0) {
                        const c = ctvLabelColorLUT[labelId];
                        data.color = c ? (c[0] << 16 | c[1] << 8 | c[2]) : 0xff304c;
                        data.organ_id = 'ctv_' + labelIds[i];
                        _safeRender3DMesh(data);
                        successCount++;
                    } else {
                        failedCount++;
                    }
                } catch (error) {
                    failedCount++;
                    if (!silent) throw error;
                }
            }
            if (successCount === 0) {
                const error = _viewer3DText(
                    '没有找到可用于 3D 重建的 CTV 标签。',
                    'No CTV labels were available for 3D reconstruction.',
                );
                _setViewer3DNodeState(nodeId, { loading: false, status: 'error', error });
                if (!silent && typeof addChat === 'function') addChat('error', error);
                return { success: false, reconstructed: 0, failed: failedCount, total: labelIds.length, error };
            }
            _setViewer3DNodeState(nodeId, {
                loading: false,
                loaded: true,
                meshLoaded: true,
                status: 'ready',
                error: null,
            });
            if (!silent) {
                switchPanel('viewers', document.querySelectorAll('.panel-tab')[2]);
                if (typeof addChat === 'function') {
                    addChat('system', _viewer3DText(
                        '3D 重建完成：已生成 ' + successCount + '/' + labelIds.length + ' 个 CTV 表面。',
                        '3D reconstruction complete: ' + successCount + '/' + labelIds.length + ' CTV surface(s) generated.',
                    ));
                }
            }
            return {
                success: true,
                reconstructed: successCount,
                failed: failedCount,
                total: labelIds.length,
            };
        }

        // Seeds and needles are planning geometry rather than mask surfaces,
        // but their Data Tree reconstruction controls must still perform a
        // real operation instead of entering an unsupported no-op branch.
        if (nodeId.startsWith('seed_') || nodeId.startsWith('needle_')) {
            if (typeof loadSeeds3D !== 'function') {
                throw new Error(_viewer3DText(
                    '种子/针道 3D 重建模块尚未加载，请刷新页面后重试。',
                    'The seed/needle 3D module is not loaded; refresh and retry.',
                ));
            }
            const planningResult = await loadSeeds3D();
            if (!planningResult || planningResult.error) {
                throw new Error(planningResult?.error || _viewer3DText(
                    '种子和针道没有生成可显示的 3D 几何。',
                    'No displayable seed/needle geometry was generated.',
                ));
            }
            _setViewer3DNodeState(nodeId, {
                loading: false,
                loaded: true,
                meshLoaded: true,
                status: 'ready',
                error: null,
            });
            if (!silent) {
                switchPanel('viewers', document.querySelectorAll('.panel-tab')[2]);
                if (typeof addChat === 'function') addChat('system', _viewer3DText(
                    '种子和针道的 3D 几何已刷新。',
                    'The seed and needle 3D geometry has been refreshed.',
                ));
            }
            return { success: true, ...planningResult };
        }

        let label_id;
        let source;
        let color;
        if (nodeId.startsWith('ctv_')) {
            label_id = parseInt(nodeId.replace('ctv_', ''), 10);
            source = 'ctv';
            const c = ctvLabelColorLUT[label_id];
            color = c ? (c[0] << 16 | c[1] << 8 | c[2]) : 0xff304c;
        } else if (nodeId.startsWith('organ_')) {
            label_id = parseInt(nodeId.replace('organ_', ''), 10);
            source = 'oar';
            const organ = (dataTreeState.organs || []).find(o => o.id === nodeId);
            if (organ) {
                const c = organ.color;
                if (c.startsWith('#')) color = parseInt(c.slice(1), 16);
                else {
                    const m = c.match(/(\d+)/g);
                    color = m ? (parseInt(m[0]) << 16 | parseInt(m[1]) << 8 | parseInt(m[2])) : 0x0ea5e9;
                }
            } else {
                color = 0x0ea5e9;
            }
        } else if (
            (typeof window.isDataTreeMaskId === 'function'
                ? window.isDataTreeMaskId(nodeId)
                : nodeId.startsWith('mask_') || nodeId.startsWith('mask:'))
        ) {
            const mask = typeof window.getDataTreeMaskState === 'function'
                ? window.getDataTreeMaskState(nodeId)
                : state.maskLabels?.[nodeId];
            if (mask?.kind === 'threshold' && Number.isFinite(Number(mask.threshold))) {
                return await _reconstructThresholdMask3D(nodeId, silent);
            }
            const isGenericMask = !!mask && (
                mask.kind === 'generic_segmentation'
                || mask.kind === 'uploaded_mask_label'
                || mask.source === 'uploaded_mask'
                || mask.upload_mask_id
            );
            if (isGenericMask) {
                const genericColor = mask.color || '#f08a5d';
                color = genericColor.startsWith('#')
                    ? parseInt(genericColor.slice(1), 16)
                    : 0xf08a5d;
                source = 'generic';
                const request = await _viewer3DJsonRequest(API + '/viewer/3d_mask', {
                    method: 'POST',
                    headers: _viewer3DRequestHeaders(requestScope, { 'Content-Type': 'application/json' }),
                    body: JSON.stringify({
                        source,
                        mask_id: mask.serverMaskId || mask.mask_id || nodeId,
                        smoothing: 1,
                        allow_missing: silent,
                    }),
                });
                const res = request.response;
                const errData = request.data || {};
                if (!res.ok) {
                    const deferred = silent && [202, 404, 409, 429].includes(res.status);
                    if (deferred) {
                        const result = {
                            success: false,
                            pending: res.status === 202,
                            code: errData.code || ('viewer_mask_http_' + res.status),
                            error: errData.error || ('HTTP ' + res.status),
                        };
                        _setViewer3DNodeState(nodeId, {
                            loading: false,
                            status: 'persisted_not_loaded',
                            error: result.error,
                        });
                        return result;
                    }
                    throw new Error(errData.error || ('HTTP ' + res.status));
                }
                const data = request.data || {};
                if (!_viewer3DRequestScopeIsCurrent(requestScope)) return { success: false, stale: true };
                if (!data.success) throw new Error(data.error || '3D mask reconstruction failed');
                data.color = color;
                data.organ_id = nodeId;
                state.mesh3D = data;
                _safeRender3DMesh(data);
                _setViewer3DNodeState(nodeId, {
                    loading: false,
                    loaded: true,
                    meshLoaded: true,
                    status: 'ready',
                    error: null,
                });
                if (!silent) switchPanel('viewers', document.querySelectorAll('.panel-tab')[2]);
                return data;
            }

            const localResult = _reconstructMask3D(nodeId, silent);
            if (localResult && Number(localResult.vertices) > 0) {
                _setViewer3DNodeState(nodeId, {
                    loading: false,
                    loaded: true,
                    meshLoaded: true,
                    status: 'ready',
                    error: null,
                });
                if (!silent) switchPanel('viewers', document.querySelectorAll('.panel-tab')[2]);
                return { success: true, ...localResult };
            }
            throw new Error(_viewer3DText(
                '掩膜没有生成可显示的体素表面。',
                'The mask did not produce a displayable voxel surface.',
            ));
        } else {
            throw new Error(_viewer3DText(
                '当前节点不支持 3D 重建。',
                'This node does not support 3D reconstruction.',
            ));
        }

        const request = await _viewer3DJsonRequest(API + '/viewer/3d_mask', {
            method: 'POST',
            headers: _viewer3DRequestHeaders(requestScope, { 'Content-Type': 'application/json' }),
            body: JSON.stringify({
                label_id,
                source,
                smoothing: 1,
                allow_missing: silent,
            }),
        });
        const res = request.response;
        if (!res.ok) {
            const errData = request.data || {};
            const errMsg = errData.error || ('HTTP ' + res.status);
            if (res.status === 400 && errMsg.includes('not found')) {
                const result = { success: false, error: errMsg };
                _setViewer3DNodeState(nodeId, {
                    loading: false,
                    status: 'unavailable',
                    error: errMsg,
                });
                if (!silent && typeof addChat === 'function') addChat('error', errMsg);
                return result;
            }
            if (silent && [202, 404, 409, 429].includes(res.status)) {
                const result = {
                    success: false,
                    pending: res.status === 202,
                    code: errData.code || ('viewer_mask_http_' + res.status),
                    error: errMsg,
                };
                _setViewer3DNodeState(nodeId, {
                    loading: false,
                    status: 'persisted_not_loaded',
                    error: errMsg,
                });
                return result;
            }
            throw new Error(errMsg);
        }

        const data = request.data || {};
        if (!_viewer3DRequestScopeIsCurrent(requestScope)) return { success: false, stale: true };
        if (!data.success) throw new Error(data.error || '3D mask reconstruction failed');
        data.color = color;
        data.organ_id = nodeId;
        state.mesh3D = data;
        _safeRender3DMesh(data);
        _setViewer3DNodeState(nodeId, {
            loading: false,
            loaded: true,
            meshLoaded: true,
            status: 'ready',
            error: null,
        });
        if (!silent) {
            switchPanel('viewers', document.querySelectorAll('.panel-tab')[2]);
            if (typeof addChat === 'function') addChat('system', _viewer3DText(
                '3D 重建完成。',
                '3D reconstruction complete.',
            ));
        }
        return data;
    } catch (error) {
        const message = error?.message || String(error);
        if (_viewer3DRequestScopeIsCurrent(requestScope)) {
            _setViewer3DNodeState(nodeId, {
                loading: false,
                status: 'error',
                error: message,
            });
            if (!silent && typeof addChat === 'function') {
                addChat('error', _viewer3DText(
                    '3D 重建失败：' + message,
                    '3D reconstruction failed: ' + message,
                ));
            }
        }
        return { success: false, error: message };
    } finally {
        endViewer3DLoading(loadingToken);
        if (_viewer3DRequestScopeIsCurrent(requestScope)) {
            const node = _viewer3DNodeForId(nodeId);
            if (node?.loading) {
                node.loading = false;
                if (node.status === 'loading') node.status = node.meshLoaded ? 'ready' : 'error';
                try {
                    if (typeof renderDataTree === 'function') renderDataTree();
                } catch (_) {}
            }
        }
    }
}
// Reconstruct a manual/threshold mask (a local voxel Set) as a merged cube
// mesh on the client. Masks live in patient-world coordinates derived from the
// CT origin/spacing, matching how the 2D overlay renders them. A hard cap keeps
// the mesh renderable for large threshold masks by sparse-sampling the voxels.
function _reconstructMask3D(id, silent = false) {
    const requestScope = _captureViewer3DRequestScope();
    const mask = (typeof state !== 'undefined' && state.maskLabels) ? state.maskLabels[id] : null;
    if (!mask || !mask.voxels || mask.voxels.size === 0) {
        if (!silent) addChat('error', 'Mask has no voxels to reconstruct.');
        return;
    }
    const origin = (state.ctOrigin || [0, 0, 0]).slice(0, 3);
    const spacing = (state.ctSpacing || [0.68, 0.68, 5.0]).slice(0, 3);
    const all = Array.from(mask.voxels);
    const cap = 120000;
    const step = all.length > cap ? Math.ceil(all.length / cap) : 1;
    const color = typeof mask.color === 'string' && mask.color.startsWith('#')
        ? parseInt(mask.color.slice(1), 16)
        : 0x8b5cf6;
    const opacity = typeof mask.opacity === 'number' ? mask.opacity : 0.6;

    // Build a single BufferGeometry from unit cubes at each sampled voxel.
    const positions = [];
    const indices = [];
    const cube = new Float32Array([
        0,0,0, 1,0,0, 1,1,0, 0,1,0,
        0,0,1, 1,0,1, 1,1,1, 0,1,1,
    ]);
    const cubeIdx = [
        0,1,2, 0,2,3, 4,5,6, 4,6,7,
        0,1,5, 0,5,4, 2,3,7, 2,7,6,
        0,3,7, 0,7,4, 1,2,6, 1,6,5,
    ];
    let count = 0;
    for (let i = 0; i < all.length; i += step) {
        const parts = String(all[i]).split(',');
        const x = Number(parts[0]);
        const y = Number(parts[1]);
        const z = Number(parts[2]);
        if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) continue;
        const wx = origin[0] + x * spacing[0];
        const wy = origin[1] + y * spacing[1];
        const wz = origin[2] + z * spacing[2];
        const base = positions.length / 3;
        for (let v = 0; v < 8; v++) {
            positions.push(wx + cube[v * 3] * spacing[0],
                            wy + cube[v * 3 + 1] * spacing[1],
                            wz + cube[v * 3 + 2] * spacing[2]);
        }
        for (let f = 0; f < cubeIdx.length; f++) indices.push(base + cubeIdx[f]);
        count++;
        if (count >= cap) break;
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(positions), 3));
    geometry.setIndex(indices);
    geometry.computeVertexNormals();
    const material = new THREE.MeshPhysicalMaterial({
        color, transparent: opacity < 0.999, opacity,
        side: THREE.DoubleSide, roughness: 0.5, metalness: 0.1,
        depthWrite: opacity >= 0.999,
        depthTest: true,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.userData = { type: 'mask', id, source: 'mask' };
    // This client-side mask is built directly in patient world coordinates.
    // Recenter it before insertion so transparent depth sorting and scene
    // bounds use the actual mask center instead of the global origin.
    window.centerWorldGeometryForDepthSort?.(mesh);

    if (typeof init3DScene === 'function') init3DScene();
    if (scene3D.meshes[id]) {
        scene3D.scene.remove(scene3D.meshes[id]);
        scene3D.meshes[id].geometry?.dispose?.();
        scene3D.meshes[id].material?.dispose?.();
        delete scene3D.meshes[id];
    }
    scene3D.scene.add(mesh);
    scene3D.meshes[id] = mesh;
    if (typeof window.applyDataTreeViewVisibility === 'function') window.applyDataTreeViewVisibility();
    window.scheduleCameraFitForSceneMutation?.('manual-mask-loaded');
    if (scene3D.requestRender) scene3D.requestRender(4);
    if (!silent) switchPanel('viewers', document.querySelectorAll('.panel-tab')[2]);
    return { vertices: positions.length / 3, faces: indices.length / 3 };
}

// Persistent 3D scene manager
const scene3D = {    scene: null, camera: null, renderer: null, controls: null,
    meshes: {},       // {organ_id: THREE.Group (with surfaceMesh + wireframe)}
    skinMesh: null,   // CT skin mesh
    initialized: false,
    contextLost: false,
    requestRender: null,
};

// Helper: get surface mesh from group or legacy mesh
function getMeshSurface(mesh) {
    if (!mesh) return null;
    // If it's a group with surfaceMesh child, return that
    if (mesh.surfaceMesh && mesh.surfaceMesh !== mesh) return mesh.surfaceMesh;
    // Otherwise it's already a mesh
    return mesh;
}

function _forEachMaterial(mesh, fn) {
    const surface = getMeshSurface(mesh);
    if (!surface || !surface.material) return;
    const mats = Array.isArray(surface.material) ? surface.material : [surface.material];
    mats.forEach(mat => { if (mat) fn(mat); });
}

function applyMeshVisibility(mesh, visible, opacity = 1) {
    if (!mesh) return;
    mesh.visible = !!visible && opacity > 0.001;
    const surface = getMeshSurface(mesh);
    if (surface && surface !== mesh) surface.visible = mesh.visible;
    if (scene3D.requestRender) scene3D.requestRender(2);
}

function applyMeshOpacity(mesh, opacity, visible = true) {
    if (!mesh) return;
    const op = Math.max(0, Math.min(1, Number(opacity) || 0));
    _forEachMaterial(mesh, mat => {
        mat.transparent = op < 0.999;
        mat.opacity = op;
        // Surgical Guide is translucent for inspection, but remains a real
        // physical boundary.  Preserve its depth-writing policy when the
        // Data Tree opacity control changes; otherwise a guide that is
        // transparent in the UI would let a needle behind it render on top.
        mat.depthWrite = op >= 0.999 || mesh.userData?.depthWriteWhenTransparent === true;
        mat.needsUpdate = true;
    });
    applyMeshVisibility(mesh, visible, op);
}

function _isDoseTexturableMesh(id, mesh) {
    const surface = getMeshSurface(mesh);
    if (!surface || !surface.geometry || !surface.geometry.attributes || !surface.geometry.attributes.position) return false;
    if (id === 'ctv' || id.startsWith('ctv_') || id.startsWith('organ_') || id.startsWith('oar_')) return true;
    const t = surface.userData?.type || surface.userData?.source || mesh?.userData?.type || mesh?.userData?.source || '';
    return t === 'ctv' || t === 'oar' || t === 'organ';
}

// `state.doseTexture.enabled` is persisted, but Three.js materials, vertex
// colors, and geometry userData are runtime-only.  A restored `enabled=true`
// therefore does not prove that the current meshes are actually dose-mapped.
// Keep an explicit runtime marker so report capture can distinguish a real
// dose surface from a normal segmentation surface that happens to use vertex
// colors for anatomy labels.
const DOSE_TEXTURE_RUNTIME_SIGNATURE = 'dose_texture_vertex_colors';

function _markDoseTextureRuntime(mesh, mapped) {
    const surface = getMeshSurface(mesh);
    [mesh, surface].forEach(target => {
        if (!target) return;
        target.userData = { ...(target.userData || {}) };
        if (mapped) {
            target.userData.doseTextureMapped = true;
            target.userData.doseTextureRenderSignature = DOSE_TEXTURE_RUNTIME_SIGNATURE;
        } else {
            delete target.userData.doseTextureMapped;
            delete target.userData.doseTextureRenderSignature;
        }
    });
}

function _doseTextureRuntimeReady() {
    if (!state?.doseTexture?.enabled || state.doseTexture.applying) return false;
    const entries = Object.entries(scene3D.meshes || {})
        .filter(([id, mesh]) => _isDoseTexturableMesh(id, mesh));
    if (!entries.length) return false;
    const recorded = new Set(
        Array.isArray(state.doseTexture.mappedMeshIds)
            ? state.doseTexture.mappedMeshIds.map(value => String(value))
            : [],
    );
    return entries.every(([id, mesh]) => {
        const surface = getMeshSurface(mesh);
        const positions = surface?.geometry?.attributes?.position;
        const colors = surface?.geometry?.attributes?.color;
        const materials = Array.isArray(surface?.material) ? surface.material : [surface?.material];
        const materialMapped = materials.some(material => (
            material?.vertexColors === true || material?.vertexColors === 2
        ));
        const marker = (
            surface?.userData?.doseTextureMapped === true
            && surface?.userData?.doseTextureRenderSignature === DOSE_TEXTURE_RUNTIME_SIGNATURE
        ) || (
            mesh?.userData?.doseTextureMapped === true
            && mesh?.userData?.doseTextureRenderSignature === DOSE_TEXTURE_RUNTIME_SIGNATURE
        );
        return (!recorded.size || recorded.has(String(id)))
            && marker
            && materialMapped
            && positions?.count > 0
            && colors?.count === positions.count;
    });
}

function _rememberDoseTextureMaterial(id, mesh) {
    const surface = getMeshSurface(mesh);
    if (!surface || !surface.material) return;
    if (!state.doseTexture.originalMaterials[id]) {
        state.doseTexture.originalMaterials[id] = surface.material;
    }
    if (!state.doseTexture.originalSceneStyle[id]) {
        const mat = Array.isArray(surface.material) ? surface.material[0] : surface.material;
        state.doseTexture.originalSceneStyle[id] = {
            visible: mesh.visible,
            surfaceVisible: surface.visible,
            opacity: Number(mat?.opacity ?? 1),
            transparent: !!mat?.transparent,
            depthWrite: mat?.depthWrite !== false,
        };
    }
}

function _restoreDoseTextureMaterials() {
    Object.entries(state.doseTexture.originalMaterials || {}).forEach(([id, mat]) => {
        const mesh = scene3D.meshes?.[id];
        const surface = getMeshSurface(mesh);
        if (!surface || !mat) return;
        surface.material = mat;
        if (surface.geometry?.attributes?.color) {
            surface.geometry.deleteAttribute('color');
        }
        _forEachMaterial(surface, m => { if (m) m.needsUpdate = true; });
        const style = state.doseTexture.originalSceneStyle?.[id];
        if (style) {
            mesh.visible = style.visible;
            surface.visible = style.surfaceVisible;
            _forEachMaterial(mesh, m => {
                m.opacity = style.opacity;
                m.transparent = style.transparent;
                m.depthWrite = style.depthWrite;
                m.needsUpdate = true;
            });
        }
    });
    Object.entries(state.doseTexture.originalSceneStyle || {}).forEach(([id, style]) => {
        if (state.doseTexture.originalMaterials?.[id]) return;
        const mesh = scene3D.meshes?.[id];
        const surface = getMeshSurface(mesh);
        if (!mesh || !style) return;
        mesh.visible = style.visible;
        if (surface) surface.visible = style.surfaceVisible;
        _forEachMaterial(mesh, m => {
            m.opacity = style.opacity;
            m.transparent = style.transparent;
            m.depthWrite = style.depthWrite;
            m.needsUpdate = true;
        });
    });
    state.doseTexture.originalMaterials = {};
    state.doseTexture.originalSceneStyle = {};
    state.doseTexture.mappedMeshIds = [];
    state.doseTexture.renderSignature = '';
    Object.values(scene3D.meshes || {}).forEach(mesh => _markDoseTextureRuntime(mesh, false));
    if (state.doseTexture.originalSkinStyle && scene3D.skinMesh) {
        scene3D.skinMesh.visible = state.doseTexture.originalSkinStyle.visible;
        _forEachMaterial(scene3D.skinMesh, mat => {
            mat.opacity = state.doseTexture.originalSkinStyle.opacity;
            mat.transparent = state.doseTexture.originalSkinStyle.transparent;
            mat.depthWrite = state.doseTexture.originalSkinStyle.depthWrite;
            mat.needsUpdate = true;
        });
    }
    state.doseTexture.originalSkinStyle = null;
    // The snapshot above is only a material transport mechanism.  The Data
    // Tree may have changed while dose texture was enabled, so re-apply its
    // current canonical state instead of reviving the stale pre-toggle look.
    if (typeof window.syncSceneAppearanceFromDataTree === 'function') {
        window.syncSceneAppearanceFromDataTree({ preserveDoseTexture: false });
    }
}

// Three.js materials and vertex colours are runtime objects.  They must be
// restored before a case switch, otherwise a newly hydrated mesh can inherit
// the previous case's material through an id collision.  Keep the user's
// desired display mode separate from that runtime state: a case may request
// Dose Surface while its meshes are still being reconstructed.
function resetDoseTextureRuntime(options = {}) {
    const doseTexture = typeof state !== 'undefined' ? state?.doseTexture : null;
    if (!doseTexture) return;
    const preserveDesired = options.preserveDesired !== false;
    const hasRuntimeState = !!doseTexture.enabled
        || !!doseTexture.applying
        || Array.isArray(doseTexture.mappedMeshIds) && doseTexture.mappedMeshIds.length > 0
        || Object.keys(doseTexture.originalMaterials || {}).length > 0
        || Object.keys(doseTexture.originalSceneStyle || {}).length > 0
        || !!doseTexture.originalSkinStyle;
    const desiredEnabled = doseTexture.desiredEnabled === true;
    if (hasRuntimeState) _restoreDoseTextureMaterials();
    doseTexture.enabled = false;
    doseTexture.applying = false;
    doseTexture.mappedMeshIds = [];
    doseTexture.renderSignature = '';
    doseTexture.originalMaterials = {};
    doseTexture.originalSceneStyle = {};
    doseTexture.originalSkinStyle = null;
    doseTexture.restorePending = preserveDesired && desiredEnabled;
    if (!preserveDesired) doseTexture.desiredEnabled = false;
    else if (typeof doseTexture.desiredEnabled !== 'boolean') doseTexture.desiredEnabled = false;
    Object.values(typeof scene3D !== 'undefined' ? (scene3D.meshes || {}) : {})
        .forEach(mesh => _markDoseTextureRuntime(mesh, false));
}
window.resetDoseTextureRuntime = resetDoseTextureRuntime;
window.isDoseTextureRuntimeReady = _doseTextureRuntimeReady;

function _isSeedOrNeedleMesh(id, mesh) {
    const t = mesh?.userData?.type || mesh?.userData?.source || '';
    // Handles are interaction affordances, never treatment geometry.  In
    // particular, the deep endpoint stays hidden until hover and must not be
    // revived by a display-mode switch such as Dose Surface.
    if (t === 'needle_handle') return false;
    return id.startsWith('seed_') || id.startsWith('needle_') || t === 'seed' || t === 'needle';
}

function _isDoseIsoMesh(id, mesh) {
    const t = mesh?.userData?.type || mesh?.userData?.source || '';
    return id.startsWith('dose_iso_') || t === 'dose' || t === 'dose_isosurface';
}

function _meshBaseColor(mesh) {
    const surface = getMeshSurface(mesh);
    const mat = Array.isArray(surface?.material) ? surface.material[0] : surface?.material;
    const c = mat?.color;
    if (c && typeof c.r === 'number') return [c.r, c.g, c.b];
    return [0.45, 0.18, 0.65];
}

function _rememberDoseTextureSceneMesh(id, mesh) {
    if (!mesh || state.doseTexture.originalSceneStyle[id]) return;
    const surface = getMeshSurface(mesh);
    const mat = Array.isArray(surface?.material) ? surface.material[0] : surface?.material;
    state.doseTexture.originalSceneStyle[id] = {
        visible: mesh.visible,
        surfaceVisible: surface ? surface.visible : mesh.visible,
        opacity: Number(mat?.opacity ?? 1),
        transparent: !!mat?.transparent,
        depthWrite: mat?.depthWrite !== false,
    };
}

function _prepareDoseTextureSceneVisibility() {
    if (scene3D.skinMesh && !state.doseTexture.originalSkinStyle) {
        const mat = Array.isArray(scene3D.skinMesh.material) ? scene3D.skinMesh.material[0] : scene3D.skinMesh.material;
        state.doseTexture.originalSkinStyle = {
            visible: scene3D.skinMesh.visible,
            opacity: Number(mat?.opacity ?? 1),
            transparent: !!mat?.transparent,
            depthWrite: mat?.depthWrite !== false,
        };
        scene3D.skinMesh.visible = false;
    }

    Object.entries(scene3D.meshes || {}).forEach(([id, mesh]) => {
        if (!mesh) return;
        const appearance = typeof window.getDataTreeAppearanceForMesh === 'function'
            ? window.getDataTreeAppearanceForMesh(id, mesh) : null;
        const visible = appearance?.visible !== false;
        const opacity = Number.isFinite(appearance?.opacity) ? appearance.opacity : 1;
        if (_isDoseTexturableMesh(id, mesh)) {
            _rememberDoseTextureSceneMesh(id, mesh);
            applyMeshOpacity(mesh, opacity, visible);
        } else if (_isSeedOrNeedleMesh(id, mesh)) {
            _rememberDoseTextureSceneMesh(id, mesh);
            applyMeshOpacity(mesh, opacity, visible);
        } else if (_isDoseIsoMesh(id, mesh)) {
            _rememberDoseTextureSceneMesh(id, mesh);
            applyMeshOpacity(mesh, opacity, visible);
        }
    });
}

async function _fetchDoseRawAxialSlice(rawZ, requestScope = _captureViewer3DRequestScope()) {
    if (!state.doseOverlay || !state.doseOverlay.shape) return null;
    const maxZ = (state.doseOverlay.shape[0] || 1) - 1;
    const z = Math.max(0, Math.min(maxZ, Math.round(rawZ)));
    const cache = state.doseTexture.rawAxialSlices || (state.doseTexture.rawAxialSlices = {});
    if (Object.prototype.hasOwnProperty.call(cache, z)) return cache[z];
    const pending = state.doseTexture.rawAxialSlicePromises
        || (state.doseTexture.rawAxialSlicePromises = {});
    if (pending[z]) return pending[z];
    pending[z] = (async () => {
        const request = await _viewer3DJsonRequest(API + '/planning/dose_overlay_slice', {
            method: 'POST',
            headers: _viewer3DRequestHeaders(requestScope, { 'Content-Type': 'application/json' }),
            body: JSON.stringify({ axis: 'axial', slice_index: z }),
        });
        const res = request.response;
        if (!res?.ok) return null;
        const data = request.data || {};
        if (!_viewer3DRequestScopeIsCurrent(requestScope)) return null;
        if (!data.success || !data.slice) return null;
        cache[z] = data.slice;
        return cache[z];
    })().finally(() => { delete pending[z]; });
    return pending[z];
}

function _sampleDoseNormalizedAtIndex(idx) {
    if (!idx || !state.doseOverlay?.shape) return 0;
    const [Z, Y, X] = state.doseOverlay.shape;
    const z = Math.max(0, Math.min(Z - 1, Math.round(idx[0])));
    const y = Math.max(0, Math.min(Y - 1, Math.round(idx[1])));
    const x = Math.max(0, Math.min(X - 1, Math.round(idx[2])));
    const slice = state.doseTexture.rawAxialSlices?.[z];
    if (!slice || !slice[y]) return 0;
    return Number(slice[y][x]) || 0;
}

async function _applyDoseTextureToMesh(id, mesh, requestScope = _captureViewer3DRequestScope()) {
    if (!_viewer3DRequestScopeIsCurrent(requestScope)) return { stale: true };
    const surface = getMeshSurface(mesh);
    if (!_isDoseTexturableMesh(id, mesh) || !surface) return;
    const posAttr = surface.geometry.attributes.position;
    if (!posAttr || posAttr.count <= 0) return;
    _rememberDoseTextureMaterial(id, mesh);

    const colors = new Float32Array(posAttr.count * 3);
    const v = new THREE.Vector3();
    const sampleEvery = posAttr.count > 25000 ? 2 : 1;

    // Warm the dose-slice cache before the color loop so that the per-vertex
    // _sampleDoseNormalizedAtIndex calls return from cache (the old code
    // fetched slices one-at-a-time inside the loop, adding O(Z) sequential
    // latency).  Pre-fetch every unique Z slice in parallel.
    const doseZ = state.doseOverlay?.shape?.[0];
    if (doseZ) {
        const zSet = new Set();
        for (let i = 0; i < posAttr.count; i += sampleEvery) {
            v.fromBufferAttribute(posAttr, i);
            surface.localToWorld(v);
            const idx = _worldToIndex(v.x, v.y, v.z);
            if (idx) zSet.add(Math.max(0, Math.min(doseZ - 1, Math.round(idx[0]))));
        }
        await Promise.all([...zSet].map(z => _fetchDoseRawAxialSlice(z, requestScope).catch(() => null)));
    }
    if (!_viewer3DRequestScopeIsCurrent(requestScope) || scene3D.meshes[id] !== mesh) {
        return { stale: true };
    }

    let lastRgb = [0, 0, 0];
    for (let i = 0; i < posAttr.count; i++) {
        if (sampleEvery > 1 && (i % sampleEvery) !== 0) {
            colors[i * 3] = lastRgb[0];
            colors[i * 3 + 1] = lastRgb[1];
            colors[i * 3 + 2] = lastRgb[2];
            continue;
        }
        v.fromBufferAttribute(posAttr, i);
        surface.localToWorld(v);
        const idx = _worldToIndex(v.x, v.y, v.z);
        const doseNorm = _sampleDoseNormalizedAtIndex(idx);
        const doseGy = doseNorm * (typeof _getDoseScaleGy === 'function' ? _getDoseScaleGy() : 120);
        const t = _doseDisplayT(doseGy, 'threeD');
        const [r, g, b] = _doseColorFromScope('threeD', t);
        const doseRgb = [r / 255, g / 255, b / 255];
        lastRgb = doseRgb;
        colors[i * 3] = lastRgb[0];
        colors[i * 3 + 1] = lastRgb[1];
        colors[i * 3 + 2] = lastRgb[2];
    }

    surface.geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    const appearance = typeof window.getDataTreeAppearanceForMesh === 'function'
        ? window.getDataTreeAppearanceForMesh(id, mesh) : null;
    const opacity = Number.isFinite(appearance?.opacity) ? appearance.opacity : 1;
    const visible = appearance?.visible !== false;
    surface.material = new THREE.MeshPhongMaterial({
        vertexColors: true,
        transparent: opacity < 0.999,
        opacity,
        side: THREE.DoubleSide,
        shininess: 35,
        depthWrite: opacity >= 0.999,
    });
    _markDoseTextureRuntime(mesh, true);
    mesh.visible = visible && opacity > 0.001;
    surface.visible = mesh.visible;
}

function fitCameraToDoseSurfaceScene() {
    if (!scene3D.camera || !scene3D.controls) return;
    const priorityBox = new THREE.Box3();
    const contextBox = new THREE.Box3();
    Object.entries(scene3D.meshes || {}).forEach(([id, mesh]) => {
        if (!mesh || mesh.visible === false) return;
        if (_isDoseTexturableMesh(id, mesh)) contextBox.expandByObject(mesh);
        if (id === 'ctv' || id.startsWith('ctv_') || _isSeedOrNeedleMesh(id, mesh) || _isDoseIsoMesh(id, mesh)) {
            priorityBox.expandByObject(mesh);
        }
    });
    const box = priorityBox.isEmpty() ? contextBox : priorityBox;
    if (box.isEmpty()) {
        // Dose-surface toggles must not reset the user's camera. Keep the
        // current pose when there is no dose geometry to frame.
        return;
    }
    const center = new THREE.Vector3();
    const size = new THREE.Vector3();
    box.getCenter(center);
    box.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z, 40);
    const dist = maxDim * 2.4;
    const position = new THREE.Vector3(
        center.x + dist * 0.45,
        center.y - dist * 1.05,
        center.z + dist * 0.55,
    );
    const pose = {
        position,
        target: center,
        up: new THREE.Vector3(0, 1, 0),
        near: Math.max(0.1, dist * 0.002),
        far: dist * 25,
        aspect: scene3D.camera.aspect,
        fov: scene3D.camera.fov,
        zoom: 1,
        saveState: true,
    };
    if (typeof window.sync3DCameraPose === 'function') {
        window.sync3DCameraPose(pose);
    } else {
        // Compatibility fallback for a partially loaded legacy page. Keep the
        // same full pose transaction even when the central helper is absent.
        scene3D.controls.target.copy(center);
        scene3D.camera.position.copy(position);
        scene3D.camera.up.copy(pose.up);
        scene3D.camera.near = pose.near;
        scene3D.camera.far = pose.far;
        scene3D.camera.updateProjectionMatrix();
        scene3D.controls.syncExternalState?.();
    }
}

async function _reconstructGuideSkinSurface3D(silent = false) {
    const scope = _captureViewer3DRequestScope();
    const node = dataTreeState.skin;
    if (!node?.loaded) return { success: false, error: 'Guide skin surface is not available' };
    node.loading = true;
    node.status = 'loading';
    renderDataTree?.();
    try {
        if (!_viewer3DRequestScopeIsCurrent(scope)) return { stale: true };
        const request = await _viewer3DJsonRequest(API + '/viewer/3d_skin', {
                method: 'POST',
                headers: _viewer3DRequestHeaders(scope, { 'Content-Type': 'application/json' }),
                body: JSON.stringify({ source: 'guide' }),
            }, { requestTimeoutMs: 120000, maxWaitMs: 300000 });
        const response = request.response;
        const payload = request.data || {};
        if (!response?.ok || !payload?.success) {
            throw new Error(payload?.error || `HTTP ${response?.status || 500}`);
        }
        if (!_viewer3DRequestScopeIsCurrent(scope)) return { stale: true };
        payload.organ_id = 'skin_surface';
        payload.source = 'skin_surface';
        payload.label = node.label || 'Guide skin surface';
        payload.object_id = node.objectId || payload.object_id || 'skin_surface:guide';
        payload.data_tree_node_id = node.nodeId || 'skin_surface';
        payload.color = Number.parseInt(String(node.color || '#f2a088').replace('#', ''), 16) || 0xf2a088;
        payload.opacity = Number(node.opacity ?? 0.10);
        payload.visible = node.visible !== false;
        payload.visible2D = node.visible2D !== false;
        payload.visible3D = node.visible3D !== false;
        _safeRender3DMesh(payload);
        node.loading = false;
        node.status = 'ready';
        node.meshLoaded = true;
        renderDataTree?.();
        if (!silent) switchPanel('viewers', document.querySelectorAll('.panel-tab')[2]);
        return { success: true, vertex_count: payload.vertex_count, face_count: payload.face_count };
    } catch (error) {
        if (_viewer3DRequestScopeIsCurrent(scope)) {
            node.loading = false;
            node.status = 'error';
            node.error = error?.message || String(error);
            renderDataTree?.();
            if (!silent) addChat?.('error', error?.message || String(error));
        }
        return { success: false, error: error?.message || String(error) };
    }
}

// Threshold masks represent a real CT-derived surface. Reuse the server's
// marching-cubes implementation instead of creating one cube per voxel in
// the browser; this keeps large whole-body masks smooth and interactive.
async function _reconstructThresholdMask3D(id, silent = false) {
    const scope = _captureViewer3DRequestScope();
    const mask = state.maskLabels?.[id];
    if (!mask || !Number.isFinite(Number(mask.threshold))) {
        if (!silent) addChat('error', typeof _dtText === 'function'
            ? _dtText('当前没有可用于 3D 重建的阈值掩膜。', 'The threshold mask is not available for 3D reconstruction.')
            : 'The threshold mask is not available for 3D reconstruction.');
        return { success: false };
    }
    const loadingToken = beginViewer3DLoading('Rendering threshold surface...');
    mask.loading = true;
    mask.status = 'loading';
    renderDataTree?.();
    try {
        if (!_viewer3DRequestScopeIsCurrent(scope)) return { stale: true };
        const request = await _viewer3DJsonRequest(API + '/viewer/3d_skin', {
                method: 'POST',
                headers: _viewer3DRequestHeaders(scope, { 'Content-Type': 'application/json' }),
                body: JSON.stringify({ threshold: Number(mask.threshold) }),
            }, { requestTimeoutMs: 120000, maxWaitMs: 300000 });
        const res = request.response;
        const data = request.data || {};
        if (!res?.ok || !data?.success) throw new Error(data?.error || `HTTP ${res?.status || 500}`);
        if (!_viewer3DRequestScopeIsCurrent(scope)) return { stale: true };
        const color = String(mask.color || '#8b5cf6').replace('#', '');
        data.color = Number.parseInt(color, 16) || 0x8b5cf6;
        data.organ_id = id;
        data.label = mask.label || mask.name || 'Threshold mask';
        data.source = 'mask';
        data.visible = mask.visible !== false;
        data.visible2D = mask.visible2D !== false;
        data.visible3D = mask.visible3D !== false;
        data.opacity = typeof mask.opacity === 'number' ? mask.opacity : 0.5;
        data.object_id = mask.objectId || 'mask:threshold';
        _safeRender3DMesh(data);
        mask.loading = false;
        mask.status = 'ready';
        mask.meshLoaded = true;
        renderDataTree?.();
        if (!silent) switchPanel('viewers', document.querySelectorAll('.panel-tab')[2]);
        return { success: true, vertex_count: data.vertex_count, face_count: data.face_count };
    } catch (error) {
        if (_viewer3DRequestScopeIsCurrent(scope)) {
            mask.loading = false;
            mask.status = 'error';
            mask.error = error?.message || String(error);
            renderDataTree?.();
            if (!silent) addChat('error', typeof _dtText === 'function'
                ? _dtText(`3D 阈值掩膜生成失败：${error?.message || error}`, `3D threshold mask failed: ${error?.message || error}`)
                : `3D threshold mask failed: ${error?.message || error}`);
        }
        return { success: false, error: error?.message || String(error) };
    } finally {
        endViewer3DLoading(loadingToken);
    }
}

async function setDoseTextureMode(enabled, opts = {}) {
    const requestScope = _captureViewer3DRequestScope();
    const requestedEnabled = !!enabled;
    const userIntent = opts.restore !== true
        && opts.silent !== true
        && opts.userIntent !== false;
    if (userIntent && typeof scene3D !== 'undefined' && scene3D) {
        // A manual mode change cancels a pending case-restore retry.  The
        // restore chain must never turn Dose Surface back on behind the user.
        try { window._cancelWorkspaceDoseSurfaceRestore?.(); } catch (_) {}
        scene3D._workspaceDoseSurfaceRestoreCancelled = true;
        scene3D._workspaceDoseSurfaceRestoreGeneration = null;
    }
    if (userIntent && state?.doseTexture) {
        state.doseTexture.desiredEnabled = requestedEnabled;
        state.doseTexture.restorePending = false;
    }
    // Report capture and an operator-triggered toggle can overlap during
    // workspace hydration.  The old early return let the report continue
    // with the normal materials while it still appended a dose colorbar.
    // Wait for the in-flight transaction so callers receive a truthful
    // result instead of silently capturing the wrong display mode.
    if (state.doseTexture.applying) {
        const waitUntil = Date.now() + 60000;
        while (state.doseTexture.applying && Date.now() < waitUntil) {
            await new Promise(resolve => setTimeout(resolve, 25));
        }
        if (state.doseTexture.applying) {
            return {
                success: false,
                enabled: !!state.doseTexture.enabled,
                error: 'Dose surface mapping is still in progress',
            };
        }
        if (requestedEnabled === !!state.doseTexture.enabled
            && (!requestedEnabled || _doseTextureRuntimeReady())) {
            return { success: true, enabled: !!state.doseTexture.enabled, waited: true };
        }
    }
    // A workspace restore can leave the persisted flag enabled while the
    // current WebGL scene still contains normal materials.  Clear that stale
    // flag and rebuild the runtime mapping instead of treating the mode as
    // already complete.  This is the key boundary for truthful Fig 2(d).
    if (requestedEnabled && state.doseTexture.enabled && !_doseTextureRuntimeReady()) {
        _restoreDoseTextureMaterials();
        state.doseTexture.enabled = false;
    }
    state.doseTexture.applying = true;
    let mappedMeshIds = [];
    const btn = document.getElementById('doseTextureToggle');
    if (btn) {
        btn.disabled = true;
        btn.textContent = requestedEnabled ? 'Mapping...' : 'Dose Surface';
    }
    // Safety timer: if the operation hangs (network timeout, server stall),
    // reset the button after 60 seconds so the user can retry.
    const safetyTimer = setTimeout(() => {
        if (!_viewer3DRequestScopeIsCurrent(requestScope)) return;
        state.doseTexture.applying = false;
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Dose Surface';
            btn.classList.remove('active');
        }
    }, 60000);
    try {
        if (requestedEnabled) {
            // Dose surface mode only changes mesh texture — it does NOT
            // add or remove models, nor reset camera. Whatever CTV/OAR
            // meshes are already visible get the dose texture; anything
            // hidden stays hidden.
            const opacityBefore = state.doseOverlay?.opacity;
            if (!state.doseOverlay) await loadDoseOverlay();
            if (!_viewer3DRequestScopeIsCurrent(requestScope)) return { stale: true };
            if (!state.doseOverlay?.shape) throw new Error('Dose overlay is not available');
            if (state.doseOverlay && state.doseOverlay.opacity !== opacityBefore) {
                console.warn('[DoseTexture] 2D dose overlay opacity changed during setDoseTextureMode:', opacityBefore, '->', state.doseOverlay.opacity);
            }
            _prepareDoseTextureSceneVisibility();
            const entries = Object.entries(scene3D.meshes || {}).filter(([id, mesh]) => _isDoseTexturableMesh(id, mesh));
            if (entries.length === 0) throw new Error('No CTV/OAR 3D meshes are available for dose surface mapping');
            mappedMeshIds = entries.map(([id]) => id);
            const mappingResults = await Promise.all(entries.map(([id, mesh]) => _applyDoseTextureToMesh(id, mesh, requestScope)));
            if (mappingResults.some(result => result?.stale)) {
                throw new Error('Dose surface mapping became stale before render');
            }
            if (!_viewer3DRequestScopeIsCurrent(requestScope)) return { stale: true };
            _prepareDoseTextureSceneVisibility();
            state.doseTexture.enabled = true;
            state.doseTexture.desiredEnabled = true;
            state.doseTexture.restorePending = false;
            state.doseTexture.mappedMeshIds = mappedMeshIds.slice();
            state.doseTexture.renderSignature = DOSE_TEXTURE_RUNTIME_SIGNATURE;
            if (typeof window.syncSceneAppearanceFromDataTree === 'function') {
                window.syncSceneAppearanceFromDataTree({ preserveDoseTexture: true });
            }
            // Show 3D colorbar when dose surface mode is active
            update3DColorbar(true);
        } else {
            _restoreDoseTextureMaterials();
            state.doseTexture.enabled = false;
            state.doseTexture.desiredEnabled = false;
            state.doseTexture.restorePending = false;
            state.doseTexture.mappedMeshIds = [];
            state.doseTexture.renderSignature = '';
            if (typeof window.syncSceneAppearanceFromDataTree === 'function') {
                window.syncSceneAppearanceFromDataTree({ preserveDoseTexture: false });
            }
            // Hide 3D colorbar when switching back to normal surface
            update3DColorbar(false);
        }
        // Keep all live-scene renders on the 3D scheduler.  Calling the raw
        // renderer here can inherit the axes viewport/scissor from the last
        // frame and paint only an inner rectangle of the viewer.
        if (typeof scene3D.renderNow === 'function') scene3D.renderNow();
        else if (scene3D.requestRender) scene3D.requestRender(2);
        if (userIntent && typeof window.scheduleWorkspaceSave === 'function') {
            window.scheduleWorkspaceSave(
                requestedEnabled ? 'viewer.dose_surface.enabled' : 'viewer.dose_surface.disabled',
            );
        }
        return { success: true, enabled: !!state.doseTexture.enabled, mappedMeshIds };
    } catch (e) {
        if (!_viewer3DRequestScopeIsCurrent(requestScope)) return { stale: true };
        console.warn('[DoseTexture] failed:', e);
        if (!opts.silent) {
            const message = `Dose surface mapping failed: ${e.message || e}`;
            if (typeof window.showBrachyBotNotice === 'function') window.showBrachyBotNotice(message, 'error');
            else console.error(message);
        }
        _restoreDoseTextureMaterials();
        state.doseTexture.enabled = false;
        if (opts.restore === true) {
            state.doseTexture.desiredEnabled = true;
            state.doseTexture.restorePending = true;
        } else if (userIntent) {
            state.doseTexture.desiredEnabled = requestedEnabled;
            state.doseTexture.restorePending = false;
        }
        state.doseTexture.mappedMeshIds = [];
        state.doseTexture.renderSignature = '';
        if (typeof window.syncSceneAppearanceFromDataTree === 'function') {
            window.syncSceneAppearanceFromDataTree({ preserveDoseTexture: false });
        }
        update3DColorbar(false);
        return { success: false, enabled: false, error: e?.message || String(e) };
    } finally {
        clearTimeout(safetyTimer);
        if (_viewer3DRequestScopeIsCurrent(requestScope)) {
            state.doseTexture.applying = false;
            if (btn) {
                btn.disabled = false;
                btn.textContent = state.doseTexture.enabled ? 'Normal Surface' : 'Dose Surface';
                btn.classList.toggle('active', state.doseTexture.enabled);
            }
        }
    }
}

function toggleDoseTextureMode() {
    // During a cold session restore, `enabled` is deliberately false until
    // the current case's WebGL materials have been rebuilt.  The operator's
    // actual mode is `desiredEnabled`; toggling the runtime flag here would
    // otherwise turn a pending "restore Dose Surface" click into another
    // enable request and could not cancel the restore.
    const doseTexture = typeof state !== 'undefined' ? state?.doseTexture : null;
    const currentMode = doseTexture && typeof doseTexture.desiredEnabled === 'boolean'
        ? doseTexture.desiredEnabled
        : !!doseTexture?.enabled;
    setDoseTextureMode(!currentMode);
}

function _hexToRgbArray(hex, fallback = [255, 204, 0]) {
    if (Array.isArray(hex)) return hex;
    if (typeof hex !== 'string' || !/^#[0-9a-f]{6}$/i.test(hex)) return fallback;
    return [
        parseInt(hex.slice(1, 3), 16),
        parseInt(hex.slice(3, 5), 16),
        parseInt(hex.slice(5, 7), 16),
    ];
}

function redrawSeedNeedleOverlays() {
    if (!state.seedsOverlay) return;
    ['axial', 'sagittal', 'coronal'].forEach(axis => {
        try { renderSeedsOverlay(axis, state.slices[axis]); } catch (_) {}
    });
}

function _vec3Array(v, fallback = [0, 0, 0]) {
    if (Array.isArray(v) && v.length >= 3) return [Number(v[0]) || 0, Number(v[1]) || 0, Number(v[2]) || 0];
    if (v && typeof v === 'object' && 'x' in v) return [Number(v.x) || 0, Number(v.y) || 0, Number(v.z) || 0];
    return fallback.slice();
}

function _normalizeArray3(v, fallback = [0, 0, 1]) {
    const a = _vec3Array(v, fallback);
    const n = Math.hypot(a[0], a[1], a[2]);
    if (!Number.isFinite(n) || n < 1e-8) return fallback.slice();
    return [a[0] / n, a[1] / n, a[2] / n];
}

function _planningCenterWorld() {
    init3DScene();
    const preferred = scene3D.meshes.ctv
        || Object.entries(scene3D.meshes).find(([id]) => id === 'ctv' || id.startsWith('ctv_'))?.[1]
        || Object.values(scene3D.meshes).find(m => m && m.visible);
    if (preferred) {
        const box = new THREE.Box3().setFromObject(preferred);
        if (!box.isEmpty()) {
            const c = box.getCenter(new THREE.Vector3());
            return [c.x, c.y, c.z];
        }
    }
    if (state.ctOrigin && state.ctSpacing && state.ctShape) {
        const x = state.ctOrigin[0] + state.ctSpacing[0] * (state.ctShape[2] || 1) * 0.5;
        const y = state.ctOrigin[1] + state.ctSpacing[1] * (state.ctShape[1] || 1) * 0.5;
        const z = state.ctOrigin[2] + state.ctSpacing[2] * (state.ctShape[0] || 1) * 0.5;
        return [x, y, z];
    }
    return [0, 0, 0];
}

function _makeSeedMesh(seed) {
    init3DScene();
    const pos = new THREE.Vector3(..._vec3Array(seed.position || seed.pos));
    const dir = new THREE.Vector3(..._normalizeArray3(seed.direction || [0, 0, 1]));
    // Use the geometry returned by the active plan so manual edits and
    // automatic-plan reloads render the same physical seed dimensions.
    const configured = state?.seedsOverlay?.geometry || {};
    const radius = Math.max(0.05, Number(seed.radius || configured.radius || 0.4));
    const length = Math.max(0.1, Number(seed.length || configured.length || 4.5));
    const geometry = new THREE.CylinderGeometry(radius, radius, length, 16);
    const material = new THREE.MeshPhysicalMaterial({
        color: 0xe6e64d,
        // Use the transparent planning queue even at opacity 1 so the
        // Surgical Guide depth pass runs before seeds and needles. The
        // physical seed remains fully opaque and depth-writing.
        transparent: true,
        opacity: 1,
        metalness: 0.5,
        roughness: 0.3,
        emissive: 0x332200,
        emissiveIntensity: 0.5,
        depthWrite: true,
        depthTest: true,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.setRotationFromQuaternion(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir));
    mesh.position.copy(pos);
    mesh.renderOrder = 40;
    mesh.userData = {
        type: 'seed',
        id: seed.id,
        trajectoryId: _normalizeTrajectoryId(seed.trajectory_id),
        renderRole: 'planning_seed',
    };
    return mesh;
}

function _makeNeedleMesh(needle) {
    init3DScene();
    const points = _needleDisplayPoints(needle);
    if (points.length < 2) return null;
    const dir = new THREE.Vector3().subVectors(points[1], points[0]);
    const length = dir.length();
    if (length < 0.1) return null;
    dir.normalize();
    const geo = new THREE.CylinderGeometry(0.22, 0.22, length, 10);
    const mat = new THREE.MeshPhysicalMaterial({
        color: 0xff2266,
        transparent: (needle.opacity ?? 0.75) < 0.999,
        opacity: needle.opacity ?? 0.75,
        metalness: 0.1,
        roughness: 0.4,
        emissive: 0x550011,
        emissiveIntensity: 0.45,
        depthWrite: (needle.opacity ?? 0.75) >= 0.999,
        depthTest: true,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.renderOrder = 30;
    mesh.position.copy(new THREE.Vector3().addVectors(points[0], points[1]).multiplyScalar(0.5));
    mesh.setRotationFromQuaternion(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir));
    mesh.userData = {
        type: 'needle',
        id: needle.id,
        trajectoryId: _normalizeTrajectoryId(needle.trajectory_id),
        // Report capture can rebuild a thinner temporary shaft from the same
        // world-space display points; the planning geometry itself is not
        // modified.
        displayPoints: points.map(point => [point.x, point.y, point.z]),
        depthWriteWhenTransparent: false,
        renderRole: 'planning_needle',
    };
    return mesh;
}

function _viewerNeedleOwnersMatch(seed, needle) {
    const normalize = value => {
        const raw = String(value ?? '').trim();
        if (!raw) return '';
        if (/^\d+$/.test(raw)) return `traj_${Number(raw) + 1}`;
        return raw;
    };
    const seedKeys = [seed?.id, seed?.needle_id, seed?.trajectory_id]
        .map(normalize).filter(Boolean);
    const needleKeys = [needle?.id, needle?.needle_id, needle?.trajectory_id]
        .map(normalize).filter(Boolean);
    return seedKeys.some(key => needleKeys.includes(key));
}

// Keep the rendered intrabody endpoint physically attached to the deepest
// seed on the same trajectory.  The stored algorithm line remains untouched;
// this helper only defines the display geometry and therefore cannot alter the
// planning coordinate chain or dose calculation inputs.
function _needleDisplayPoints(needle) {
    const raw = (needle?.points || [])
        .map(p => new THREE.Vector3(..._vec3Array(p)))
        .filter(p => Number.isFinite(p.x + p.y + p.z));
    if (raw.length < 2) return raw;
    const entry = raw[raw.length - 1].clone();
    const target = raw[0].clone();
    const direction = new THREE.Vector3().subVectors(target, entry);
    const length2 = direction.lengthSq();
    const seeds = (dataTreeState?.planning?.seeds || [])
        .filter(seed => _viewerNeedleOwnersMatch(seed, needle))
        .map(seed => new THREE.Vector3(..._vec3Array(seed.position || seed.pos)))
        .filter(point => Number.isFinite(point.x + point.y + point.z));
    if (!seeds.length || length2 < 1e-8) return [target, entry];
    let deepest = null;
    let deepestParam = -Infinity;
    seeds.forEach(seed => {
        const param = new THREE.Vector3().subVectors(seed, entry).dot(direction) / length2;
        if (!Number.isFinite(param) || param < -1e-3 || param > 1.0 + 1e-3) return;
        const projected = entry.clone().add(direction.clone().multiplyScalar(param));
        // Do not let a stale seed that merely projects deepest onto the line
        // redefine the displayed endpoint. The display shaft must remain
        // attached to an actual seed on the physical needle.
        if (projected.distanceTo(seed) > 1e-3) return;
        if (param > deepestParam) {
            deepestParam = param;
            deepest = seed;
        }
    });
    return [deepest || target, entry];
}

function _needleHandleId(needleId, pointIndex) {
    return `needle_handle_${needleId}_${pointIndex}`;
}

function _removeNeedleHandles(needleId) {
    [0, 1].forEach(i => {
        const id = _needleHandleId(needleId, i);
        const mesh = scene3D.meshes[id];
        if (!mesh) return;
        scene3D.scene.remove(mesh);
        try { mesh.geometry?.dispose(); } catch (_) {}
        try { mesh.material?.dispose(); } catch (_) {}
        delete scene3D.meshes[id];
    });
}

function _makeNeedleHandle(needle, pointIndex) {
    const points = _needleDisplayPoints(needle);
    const point = points?.[pointIndex];
    if (!point) return null;
    const color = pointIndex === 0 ? 0xff77aa : 0x66d9ff;
    // Endpoint handles are larger than the needle radius so they stay easy to
    // select beside a dense surface, but they must NOT be always-on-top:
    // depthTest=false plus the capture-phase hit guard made a handle float
    // over every other object, so orbiting the scene would lock rotation
    // whenever the pointer crossed a handle's screen position. With depth
    // testing on, a handle occluded by the patient surface or needle shaft is
    // invisible and cannot steal a rotation drag; only visible handles are
    // draggable. Slightly smaller radius keeps selection precise.
    const geo = new THREE.SphereGeometry(2.2, 20, 20);
    const mat = new THREE.MeshPhysicalMaterial({
        color,
        transparent: true,
        // Endpoint handles follow the needle's saved opacity.  A minimum
        // alpha of 0.35 made a deliberately faint/hidden needle reappear
        // after a workspace restore even though the shaft itself was
        // correctly restored.
        opacity: Math.max(0.001, Math.min(1, Number(needle.opacity ?? 0.8))),
        emissive: pointIndex === 0 ? 0x551122 : 0x003355,
        emissiveIntensity: 0.55,
        metalness: 0.15,
        roughness: 0.3,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.renderOrder = 1000;
    mat.depthTest = true;
    mat.depthWrite = false;
    if (point.isVector3) mesh.position.copy(point);
    else mesh.position.set(..._vec3Array(point));
    mesh.userData = {
        type: 'needle_handle',
        id: _needleHandleId(needle.id, pointIndex),
        needleId: needle.id,
        pointIndex,
        trajectoryId: _normalizeTrajectoryId(needle.trajectory_id),
        internal: pointIndex === 0,
        hoverVisible: pointIndex !== 0,
    };
    return mesh;
}

function _syncNeedleHandles(needle) {
    if (!needle || !needle.id || !Array.isArray(needle.points) || needle.points.length < 2) return;
    _removeNeedleHandles(needle.id);
    [0, 1].forEach(i => {
        const handle = _makeNeedleHandle(needle, i);
        if (handle) _upsertSceneMesh(handle.userData.id, handle);
    });
    // Endpoint handles are part of the needle's 3D presentation.  A late
    // seed/needle rebuild used to pass only the all-view flag here, so a
    // needle hidden in 3D (or hidden through the Planning/Needles parent)
    // could briefly reappear after session hydration.
    const planning = typeof dataTreeState !== 'undefined' ? dataTreeState?.planning : null;
    const needlesRoot = typeof dataTreeState !== 'undefined' ? dataTreeState?.needles : null;
    const visible3D = needle.visible !== false
        && needle.visible3D !== false
        && needlesRoot?.visible !== false
        && needlesRoot?.visible3D !== false
        && planning?.visible !== false
        && planning?.visible3D !== false;
    const opacity = Number.isFinite(Number(needle.opacity)) ? Number(needle.opacity) : 0.8;
    _setNeedleHandlesVisibility(needle.id, visible3D, opacity);
}

function _setNeedleHandlesVisibility(needleId, visible, opacity = 0.8) {
    [0, 1].forEach(i => {
        const mesh = scene3D.meshes[_needleHandleId(needleId, i)];
        if (mesh) {
            const safeOpacity = Math.max(0, Math.min(1, opacity));
            // Report capture must never contain endpoint gizmos, even if a
            // mesh is rebuilt while the renderer is preparing a figure.
            if (window.__reportCaptureActive) {
                applyMeshOpacity(mesh, 0.001, false);
                return;
            }
            applyMeshOpacity(mesh, i === 0 && !mesh.userData.hoverVisible ? 0.001 : safeOpacity, !!visible);
            mesh.userData.baseVisible = !!visible;
            mesh.userData.baseOpacity = safeOpacity;
        }
    });
}

function _setNeedleInternalHandleHover(needleId, show) {
    const mesh = scene3D.meshes[_needleHandleId(needleId, 0)];
    if (!mesh) return;
    mesh.userData.hoverVisible = !!show;
    const opacity = mesh.userData.baseOpacity ?? 0.8;
    applyMeshOpacity(mesh, show ? opacity : 0.001, mesh.userData.baseVisible !== false);
    // This helper lives outside init3DScene(), so the local requestRender()
    // closure is not in scope here. Use the scene-owned scheduler instead;
    // calling an undefined local function used to abort pointer-move and
    // pointer-up handlers, leaving endpoint interaction looking stuck.
    if (typeof scene3D !== 'undefined' && scene3D.requestRender) scene3D.requestRender(1);
}

function setNeedleInteractionHighlight(needleId, active) {
    const ids = [needleId, _needleHandleId(needleId, 0), _needleHandleId(needleId, 1)];
    ids.forEach(id => {
        const mesh = scene3D.meshes[id];
        const material = mesh?.material;
        if (!mesh || !material) return;
        if (active) {
            if (material.color && mesh.userData.originalColor === undefined) mesh.userData.originalColor = material.color.getHex();
            if (material.emissive && mesh.userData.originalEmissive === undefined) mesh.userData.originalEmissive = material.emissive.getHex();
            material.color?.setHex(0xffd166);
            material.emissive?.setHex(0xff8a00);
        } else {
            if (material.color && mesh.userData.originalColor !== undefined) material.color.setHex(mesh.userData.originalColor);
            if (material.emissive && mesh.userData.originalEmissive !== undefined) material.emissive.setHex(mesh.userData.originalEmissive);
        }
    });
    if (typeof scene3D !== 'undefined' && scene3D.requestRender) scene3D.requestRender(2);
}

function _upsertSceneMesh(id, mesh) {
    if (!mesh) return;
    if (scene3D.meshes[id]) {
        scene3D.scene.remove(scene3D.meshes[id]);
        try { scene3D.meshes[id].geometry?.dispose(); } catch (_) {}
        try { scene3D.meshes[id].material?.dispose(); } catch (_) {}
    }
    scene3D.scene.add(mesh);
    scene3D.meshes[id] = mesh;
}
