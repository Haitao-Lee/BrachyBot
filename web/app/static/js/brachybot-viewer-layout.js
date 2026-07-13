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
        _resize.active = false;
        _resize.card = null;
        _resize.cards = [];
        _resize.handle = null;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
    }
});

function setViewerLayout(layout) {
    const panel = document.getElementById('viewersPanel');
    if (!panel) return;
    panel.classList.remove('layout-grid', 'layout-horizontal', 'layout-vertical', 'layout-3d-top', 'layout-3d-bottom');

    // Remove any existing viewers-row wrapper
    const existingRow = panel.querySelector('.viewers-row');
    if (existingRow) {
        while (existingRow.firstChild) panel.insertBefore(existingRow.firstChild, existingRow);
        existingRow.remove();
    }

    // Remove all dynamic resize handles
    panel.querySelectorAll('.viewer-resize-v').forEach(h => h.remove());

    // Reset all viewer card inline styles
    ['viewerAxial', 'viewerSagittal', 'viewerCoronal', 'viewer3d'].forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.style.height = ''; el.style.width = ''; el.style.flex = ''; }
    });

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
    // Re-render current slices to fit new layout
    setTimeout(() => {
        ['axial', 'sagittal', 'coronal'].forEach(axis => {
            const slider = document.getElementById('slider' + capitalize(axis));
            if (slider && state.ctLoaded) updateSlice(axis, slider.value);
        });
    }, 150);
}

function setViewerTool(tool) {
    state.viewerSettings.activeTool = tool;
    // Reset annotation tool state when switching tools
    if (window._annotationToolState) {
        window._annotationToolState.active = false;
        window._annotationToolState.points = [];
    }
    const toolIds = ['toolCrosshair', 'toolMeasure', 'toolAngle', 'toolRect', 'toolZoombox', 'toolAnnotate', 'toolEraser'];
    toolIds.forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.style.background = '';
    });
    const toolMap = { crosshair: 'toolCrosshair', measure: 'toolMeasure', angle: 'toolAngle', rect: 'toolRect', zoombox: 'toolZoombox', annotate: 'toolAnnotate', eraser: 'toolEraser' };
    const activeBtn = document.getElementById(toolMap[tool]);
    if (activeBtn) activeBtn.style.background = 'var(--primary)';

    // Update cursor on all slice canvases
    const cursors = { crosshair: 'crosshair', measure: 'crosshair', angle: 'crosshair', rect: 'crosshair', zoombox: 'zoom-in', annotate: 'crosshair', eraser: 'cell' };
    ['axial', 'sagittal', 'coronal'].forEach(axis => {
        const canvas = document.getElementById('sliceCanvas' + capitalize(axis));
        if (canvas) canvas.style.cursor = cursors[tool] || 'default';
    });
}

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
}

function resetViewer() {
    state.viewerSettings = {
        window: 400, level: 40, threshold: null,
        showCTV: false, showOAR: false, zoom: 1.0,
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
}

function renderSliceToCanvas(axis, sliceData) {
    const canvasId = 'sliceCanvas' + capitalize(axis);
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const container = canvas.parentElement;

    // Check if it's a base64 PNG
    if (typeof sliceData === 'string' && sliceData.startsWith('data:image/png;base64,')) {
        const img = new Image();
        img.onload = () => {
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

            // Store display info for coordinate mapping
            canvas._displayScale = scale;
            canvas._displayW = displayW;
            canvas._displayH = displayH;
            canvas._offsetX = (containerW - displayW) / 2;
            canvas._offsetY = (containerH - displayH) / 2;
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
    const placeholder = canvas.parentElement.querySelector('.viewer-no-data');
    if (placeholder) placeholder.style.display = 'none';

    if (state.viewerSettings.zoom !== 1.0) {
        canvas.style.transform = `scale(${state.viewerSettings.zoom})`;
        canvas.style.transformOrigin = 'center center';
    }
}

async function loadAllSlices() {
    if (!state.ctPath) return;

    // Use volume-based rendering for instant response
    if (volumeData && volumeShape) {
        ['axial', 'sagittal', 'coronal'].forEach(axis => {
            renderSliceFromVolume(axis, state.slices[axis]);
        });
        return;
    }

    // Fallback to server-based rendering
    await Promise.all([
        loadSlice('axial', state.slices.axial),
        loadSlice('sagittal', state.slices.sagittal),
        loadSlice('coronal', state.slices.coronal),
    ]);
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
        ctv_color: '#ff4444',
        oar_non_traversable_color: '#fb923c',
        oar_traversable_color: '#0ea5e9',
        seed_color: '#facc15',
        needle_color: '#a855f7',
        seed_opacity: 0.95,
        needle_opacity: 0.85,
        ctv_opacity: 0.65,
        oar_opacity: 0.55,
        show_isosurfaces_by_default: true,
        show_seeds_by_default: true,
        show_needles_by_default: true,
    };
    return _3dConfigCache;
}

async function reconstruct3D() {
    if (!state.ctPath || !state.ctLoaded) {
        try {
            const resp = await fetch(API + '/status');
            if (resp.ok) {
                const sd = await resp.json();
                if (sd.ct_path) {
                    state.ctPath = sd.ct_path;
                    state.ctLoaded = true;
                }
                if (!volumeData && sd.ct_loaded) {
                    await loadVolumeData();
                }
            }
        } catch (e) {}
    }
    if (!state.ctPath) {
        addChat('error', 'No CT image loaded');
        return;
    }

    const loading = document.getElementById('loading3D');
    const external3dStatus = document.getElementById('meshPrewarmStatus')
        || document.getElementById('auto3DStatusBar');
    if (loading && !external3dStatus) {
        loading.classList.add('active');
        loading.setAttribute('aria-hidden', 'false');
    }

    try {
        // 1) CTV + non-traversable OARs (the structures the planning
        //    pipeline actually cares about). This replaces the old
        //    "single red box from CTV" default that the user
        //    complained about — those meshes are real, segmentable
        //    surfaces, not just an iso-contour.
        await loadCTVAndObstacleMeshes();

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
            if (cfg.show_isosurfaces_by_default && typeof loadAllIsoSurfaces === 'function') {
                try { await loadAllIsoSurfaces(); } catch (e) { console.warn('loadAllIsoSurfaces failed:', e); }
            }
        }
    } catch (e) {
        addChat('error', '3D reconstruction failed: ' + e.message);
    } finally {
        if (loading && !external3dStatus) {
            loading.classList.remove('active');
            loading.setAttribute('aria-hidden', 'true');
        }
    }
}

// 3D reconstruction for individual organs from data tree
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
    if (!state.ctPath || !state.ctLoaded) {
        try {
            const resp = await fetch(API + '/status');
            if (resp.ok) {
                const sd = await resp.json();
                if (sd.ct_path) {
                    state.ctPath = sd.ct_path;
                    state.ctLoaded = true;
                }
                if (!volumeData && sd.ct_loaded) {
                    await loadVolumeData();
                }
            }
        } catch (e) {}
    }
    if (!state.ctPath) {
        if (!silent) addChat('error', 'No CT image loaded');
        return;
    }

    const loading = document.getElementById('loading3D');
    const external3dStatus = document.getElementById('meshPrewarmStatus')
        || document.getElementById('auto3DStatusBar');
    if (loading && !external3dStatus) {
        loading.classList.add('active');
        loading.setAttribute('aria-hidden', 'false');
    }

    try {
        // CTV: reconstruct all labels (multi-label)
        if (id === 'ctv') {
            const labelIds = getCtvMeshLabelIds();
            let successCount = 0;
            for (let i = 0; i < labelIds.length; i++) {
                try {
                    const res = await fetch(API + '/viewer/3d_mask', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ label_id: labelIds[i], source: 'ctv', smoothing: 1 }),
                    });
                    if (res.ok) {
                        const data = await res.json();
                        if (data.success && data.vertex_count > 0) {
                            // Use same color as data tree (from labelColorLUT)
                            const c = labelColorLUT[labelIds[i]];
                            data.color = c ? (c[0] << 16 | c[1] << 8 | c[2]) : 0xff6b6b;
                            data.organ_id = `ctv_${labelIds[i]}`;  // Use same ID as data tree
                            render3DMesh(data);
                            successCount++;
                        }
                    }
                    // Skip 400 errors (label not found in mask)
                } catch (e) { /* skip failed labels */ }
            }
            if (successCount === 0 && !silent) {
                addChat('error', 'No CTV labels found for 3D reconstruction');
            }
            if (!silent) switchPanel('viewers', document.querySelectorAll('.panel-tab')[2]);
            return;
        }

        let label_id, source, color;
        if (id.startsWith('ctv_')) {
            // Individual CTV label. Label 1 = tumor (source='ctv'),
            // labels 2+ = vessels/organs categorized as OAR (source='oar').
            label_id = parseInt(id.replace('ctv_', ''));
            // Use 'ctv' for API fetch (mesh data is in CTV mask),
            // but 'oar' for display source when label > 1 so
            // addMeshToScene uses OAR opacity config.
            source = 'ctv';
            const c = labelColorLUT[label_id];
            color = c ? (c[0] << 16 | c[1] << 8 | c[2]) : 0xff6b6b;
        } else if (id.startsWith('organ_')) {
            label_id = parseInt(id.replace('organ_', ''));
            source = 'oar';
            const organ = dataTreeState.organs.find(o => o.id === id);
            if (organ) {
                const c = organ.color;
                if (c.startsWith('#')) { color = parseInt(c.slice(1), 16); }
                else { const m = c.match(/(\d+)/g); color = m ? (parseInt(m[0]) << 16 | parseInt(m[1]) << 8 | parseInt(m[2])) : 0x0ea5e9; }
            } else { color = 0x0ea5e9; }
        } else {
            return;
        }

        const res = await fetch(API + '/viewer/3d_mask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ label_id, source, smoothing: 1 }),
        });

        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            const errMsg = errData.error || `HTTP ${res.status}`;
            // Don't show error for "label not found" - just skip silently
            if (res.status === 400 && errMsg.includes('not found')) {
                return;
            }
            throw new Error(errMsg);
        }

        const data = await res.json();
        if (data.success) {
            data.color = color;
            data.organ_id = id;
            state.mesh3D = data;
            render3DMesh(data);
            switchPanel('viewers', document.querySelectorAll('.panel-tab')[2]);
        }
    } catch (e) {
        addChat('error', '3D reconstruction failed: ' + e.message);
    } finally {
        if (loading && !external3dStatus) {
            loading.classList.remove('active');
            loading.setAttribute('aria-hidden', 'true');
        }
    }
}

// Persistent 3D scene manager
const scene3D = {
    scene: null, camera: null, renderer: null, controls: null,
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
        mat.depthWrite = op > 0.001;
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
}

function _isSeedOrNeedleMesh(id, mesh) {
    const t = mesh?.userData?.type || mesh?.userData?.source || '';
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

function _doseTextureOpacityForMesh(id, mesh) {
    const surface = getMeshSurface(mesh);
    const t = surface?.userData?.type || surface?.userData?.source || mesh?.userData?.type || mesh?.userData?.source || '';
    if (id === 'ctv' || id.startsWith('ctv_') || t === 'ctv') return 0.86;
    return 0.52;
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
        if (_isDoseTexturableMesh(id, mesh)) {
            _rememberDoseTextureSceneMesh(id, mesh);
            applyMeshOpacity(mesh, _doseTextureOpacityForMesh(id, mesh), true);
        } else if (_isSeedOrNeedleMesh(id, mesh)) {
            _rememberDoseTextureSceneMesh(id, mesh);
            mesh.visible = true;
            _forEachMaterial(mesh, mat => {
                mat.transparent = true;
                mat.opacity = id.startsWith('needle_') ? 0.95 : 1.0;
                mat.depthWrite = true;
                mat.needsUpdate = true;
            });
        } else if (_isDoseIsoMesh(id, mesh)) {
            _rememberDoseTextureSceneMesh(id, mesh);
            applyMeshOpacity(mesh, 0.18, true);
        }
    });
}

async function _fetchDoseRawAxialSlice(rawZ) {
    if (!state.doseOverlay || !state.doseOverlay.shape) return null;
    const maxZ = (state.doseOverlay.shape[0] || 1) - 1;
    const z = Math.max(0, Math.min(maxZ, Math.round(rawZ)));
    const cache = state.doseTexture.rawAxialSlices || (state.doseTexture.rawAxialSlices = {});
    if (Object.prototype.hasOwnProperty.call(cache, z)) return cache[z];
    const pending = state.doseTexture.rawAxialSlicePromises
        || (state.doseTexture.rawAxialSlicePromises = {});
    if (pending[z]) return pending[z];
    pending[z] = (async () => {
        const res = await fetch(API + '/planning/dose_overlay_slice', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ axis: 'axial', slice_index: z }),
        });
        if (!res.ok) return null;
        const data = await res.json();
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

async function _applyDoseTextureToMesh(id, mesh) {
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
        await Promise.all([...zSet].map(z => _fetchDoseRawAxialSlice(z).catch(() => null)));
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
    surface.material = new THREE.MeshPhongMaterial({
        vertexColors: true,
        transparent: false,
        side: THREE.DoubleSide,
        shininess: 35,
        depthWrite: true,
    });
    mesh.visible = true;
    surface.visible = true;
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
        fitCameraToScene();
        return;
    }
    const center = new THREE.Vector3();
    const size = new THREE.Vector3();
    box.getCenter(center);
    box.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z, 40);
    const dist = maxDim * 2.4;
    scene3D.controls.target.copy(center);
    scene3D.camera.position.set(center.x + dist * 0.45, center.y - dist * 1.05, center.z + dist * 0.55);
    scene3D.camera.near = Math.max(0.1, dist * 0.002);
    scene3D.camera.far = dist * 25;
    scene3D.camera.updateProjectionMatrix();
    scene3D.controls.update();
}

async function setDoseTextureMode(enabled, opts = {}) {
    if (state.doseTexture.applying) return;
    state.doseTexture.applying = true;
    const btn = document.getElementById('doseTextureToggle');
    if (btn) {
        btn.disabled = true;
        btn.textContent = enabled ? 'Mapping...' : 'Dose Surface';
    }
    // Safety timer: if the operation hangs (network timeout, server stall),
    // reset the button after 60 seconds so the user can retry.
    const safetyTimer = setTimeout(() => {
        state.doseTexture.applying = false;
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Dose Surface';
            btn.classList.remove('active');
        }
    }, 60000);
    try {
        if (enabled) {
            // Dose surface mode only changes mesh texture — it does NOT
            // add or remove models, nor reset camera. Whatever CTV/OAR
            // meshes are already visible get the dose texture; anything
            // hidden stays hidden.
            const opacityBefore = state.doseOverlay?.opacity;
            if (!state.doseOverlay) await loadDoseOverlay();
            if (!state.doseOverlay?.shape) throw new Error('Dose overlay is not available');
            if (state.doseOverlay && state.doseOverlay.opacity !== opacityBefore) {
                console.warn('[DoseTexture] 2D dose overlay opacity changed during setDoseTextureMode:', opacityBefore, '->', state.doseOverlay.opacity);
            }
            _prepareDoseTextureSceneVisibility();
            const entries = Object.entries(scene3D.meshes || {}).filter(([id, mesh]) => _isDoseTexturableMesh(id, mesh));
            if (entries.length === 0) throw new Error('No CTV/OAR 3D meshes are available for dose surface mapping');
            await Promise.all(entries.map(([id, mesh]) => _applyDoseTextureToMesh(id, mesh)));
            _prepareDoseTextureSceneVisibility();
            state.doseTexture.enabled = true;
            // Show 3D colorbar when dose surface mode is active
            update3DColorbar(true);
        } else {
            _restoreDoseTextureMaterials();
            state.doseTexture.enabled = false;
            // Hide 3D colorbar when switching back to normal surface
            update3DColorbar(false);
        }
        if (scene3D.renderer && scene3D.scene && scene3D.camera) {
            scene3D.renderer.render(scene3D.scene, scene3D.camera);
        }
    } catch (e) {
        console.warn('[DoseTexture] failed:', e);
        if (!opts.silent) alert('Dose surface mapping failed: ' + (e.message || e));
        _restoreDoseTextureMaterials();
        state.doseTexture.enabled = false;
        update3DColorbar(false);
    } finally {
        clearTimeout(safetyTimer);
        state.doseTexture.applying = false;
        if (btn) {
            btn.disabled = false;
            btn.textContent = state.doseTexture.enabled ? 'Normal Surface' : 'Dose Surface';
            btn.classList.toggle('active', state.doseTexture.enabled);
        }
    }
}

function toggleDoseTextureMode() {
    setDoseTextureMode(!state.doseTexture.enabled);
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
    const geometry = new THREE.CylinderGeometry(0.8, 0.8, 4.5, 16);
    const material = new THREE.MeshPhysicalMaterial({
        color: 0xe6e64d,
        metalness: 0.5,
        roughness: 0.3,
        emissive: 0x332200,
        emissiveIntensity: 0.5,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.setRotationFromQuaternion(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir));
    mesh.position.copy(pos);
    mesh.userData = { type: 'seed', id: seed.id, trajectoryId: _normalizeTrajectoryId(seed.trajectory_id) };
    return mesh;
}

function _makeNeedleMesh(needle) {
    init3DScene();
    const points = (needle.points || []).map(p => new THREE.Vector3(..._vec3Array(p))).filter(p => Number.isFinite(p.x + p.y + p.z));
    if (points.length < 2) return null;
    const dir = new THREE.Vector3().subVectors(points[1], points[0]);
    const length = dir.length();
    if (length < 0.1) return null;
    dir.normalize();
    const geo = new THREE.CylinderGeometry(0.22, 0.22, length, 10);
    const mat = new THREE.MeshPhysicalMaterial({
        color: 0xff2266,
        transparent: true,
        opacity: needle.opacity ?? 0.75,
        metalness: 0.1,
        roughness: 0.4,
        emissive: 0x550011,
        emissiveIntensity: 0.45,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.copy(new THREE.Vector3().addVectors(points[0], points[1]).multiplyScalar(0.5));
    mesh.setRotationFromQuaternion(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir));
    mesh.userData = { type: 'needle', id: needle.id, trajectoryId: _normalizeTrajectoryId(needle.trajectory_id) };
    return mesh;
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
    const point = needle.points?.[pointIndex];
    if (!point) return null;
    const color = pointIndex === 0 ? 0xff77aa : 0x66d9ff;
    // Endpoint handles are deliberately larger than the needle radius and
    // rendered on top so they remain easy to select beside a dense surface.
    const geo = new THREE.SphereGeometry(3.5, 20, 20);
    const mat = new THREE.MeshPhysicalMaterial({
        color,
        transparent: true,
        opacity: Math.max(0.35, needle.opacity ?? 0.8),
        emissive: pointIndex === 0 ? 0x551122 : 0x003355,
        emissiveIntensity: 0.55,
        metalness: 0.15,
        roughness: 0.3,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.renderOrder = 1000;
    mat.depthTest = false;
    mat.depthWrite = false;
    mesh.position.set(..._vec3Array(point));
    mesh.userData = {
        type: 'needle_handle',
        id: _needleHandleId(needle.id, pointIndex),
        needleId: needle.id,
        pointIndex,
        trajectoryId: _normalizeTrajectoryId(needle.trajectory_id),
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
    _setNeedleHandlesVisibility(needle.id, needle.visible !== false, needle.opacity ?? 0.8);
}

function _setNeedleHandlesVisibility(needleId, visible, opacity = 0.8) {
    [0, 1].forEach(i => {
        const mesh = scene3D.meshes[_needleHandleId(needleId, i)];
        if (mesh) applyMeshOpacity(mesh, Math.max(0, Math.min(1, opacity)), !!visible);
    });
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
