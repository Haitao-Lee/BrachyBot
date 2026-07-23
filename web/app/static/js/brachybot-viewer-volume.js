function switchPanel(name, el) {
    uiDebugLog('[switchPanel] Switching to:', name);
    document.querySelectorAll('.panel-tab').forEach(t => {
        t.classList.remove('active');
        t.setAttribute('aria-selected', 'false');
    });
    document.querySelectorAll('.panel-content').forEach(c => c.classList.remove('active'));
    el.classList.add('active');
    el.setAttribute('aria-selected', 'true');
    const panel = document.getElementById('panel' + capitalize(name));
    if (panel) {
        panel.classList.add('active');
        uiDebugLog('[switchPanel] Panel activated:', 'panel' + capitalize(name));
    } else {
        console.error('[switchPanel] Panel not found:', 'panel' + capitalize(name));
    }
    // Hide summary bar when viewers panel is active
    const summaryBar = document.getElementById('summaryBar');
    if (summaryBar) summaryBar.style.display = name === 'viewers' ? 'none' : '';
    // When the report panel becomes active, re-initialize the
    // preview zoom state. The zoom module is in the IIFE named
    // `preview` (line 14645+); we poke it so the wheel handler is
    // bound to the freshly-rendered #reportPreview and the
    // persisted zoom level is re-applied.
    if (name === 'report' && typeof Report !== 'undefined' && Report.preview) {
        try {
            // re-install wheel handler (idempotent)
            const prev = document.getElementById('reportPreview');
            if (prev && !prev._rpZoomWired) {
                prev._rpZoomWired = true;
                prev.addEventListener('wheel', (e) => {
                    if (!e.ctrlKey && !e.metaKey) return;
                    e.preventDefault();
                    const z = Report.preview.getZoom();
                    if (e.deltaY < 0) Report.preview.setZoom(z + 0.1);
                    else if (e.deltaY > 0) Report.preview.setZoom(z - 0.1);
                }, { passive: false });
            }
        } catch (_) { /* best-effort */ }
    }
    if (name === 'viewers' && state.ctLoaded) {
        loadAllSlices();
        // Delayed re-render to fix black screen when container size changes
        setTimeout(() => loadAllSlices(), 100);
        // BUG FIX 2026-06-22: force 3D viewer re-render when panel
        // becomes visible. The canvas was 0x0 while the panel was
        // hidden (display:none), so the renderer had nothing to draw
        // into. Now that the panel is visible, re-size and fit camera.
        if (Object.keys(scene3D.meshes).length > 0) {
            setTimeout(() => forceRender3DViewer(), 50);
        }
    }
    if (name === 'metrics') {
        _resizeDVHChartSoon();
    }
    // BUG FIX 2026-06-16 (report auto-screenshots): previously the
    // report panel opened with NO figures and the user had to
    // manually click 📷 Capture 2D / 3D / DVH or wait for PDF
    // export. Now we auto-capture the standard set of evidence
    // figures (segmentation overlay + dose heatmap + 3D plan +
    // DVH curve) the FIRST time the report panel opens AFTER a
    // plan has run. Subsequent opens won't re-capture (because
    // the figures array is already populated).
    if (name === 'report' && window.state && window.state.ctLoaded) {
        try {
            if (typeof autoCaptureReportFigures === 'function') {
                // Wait for 3D meshes and DVH to be ready before capturing.
                // Retry up to 5 times with increasing delays.
                let _attempts = 0;
                const _tryCapture = () => {
                    _attempts++;
                    const _meshCount = Object.keys(scene3D.meshes).length;
                    const _hasDvh = !!state.dvhData;
                    const _hasDose = !!(state.doseOverlay && state.doseOverlay.peakVoxel);
                    const _allReady = _meshCount > 0 && _hasDvh && _hasDose;
                    uiDebugLog(`[Report] Capture attempt ${_attempts}: meshes=${_meshCount} dvh=${_hasDvh} dose=${_hasDose} allReady=${_allReady}`);
                    if (_allReady || _attempts >= 5) {
                        autoCaptureReportFigures();
                    } else {
                        setTimeout(_tryCapture, 500);
                    }
                };
                setTimeout(_tryCapture, 100);
            }
        } catch (_) { /* best-effort */ }
    }
    reportUIEvent('ui.panel', `Panel switched to ${name}`, { panel: name });
}

function _planningItems(kind) {
    const planning = dataTreeState && dataTreeState.planning ? dataTreeState.planning : {};
    return Array.isArray(planning[kind]) ? planning[kind] : [];
}

function _planningVisualEntries() {
    const entries = [
        ..._planningItems('trajectories'),
        ..._planningItems('seeds'),
        ..._planningItems('needles'),
        ..._planningItems('doseLevels'),
        ...(_planningItems('meshes')),
    ];
    if (state?.doseOverlay?.shape) entries.push(state.doseOverlay);
    return entries;
}

function _trajectoryContains(item, trajectory) {
    const itemId = item?.trajectory_id ?? item?.trajectoryId;
    if (itemId === undefined || itemId === null) return false;
    const normalize = value => {
        const text = String(value);
        return new Set([text, text.replace(/^traj_/, ''), `traj_${text.replace(/^traj_/, '')}`]);
    };
    const itemValues = normalize(itemId);
    const trajectoryValues = new Set();
    [trajectory?.id, trajectory?.index, Number(trajectory?.index) + 1]
        .filter(v => v !== undefined && v !== null && !Number.isNaN(v))
        .forEach(v => normalize(v).forEach(x => trajectoryValues.add(x)));
    return [...itemValues].some(value => trajectoryValues.has(value));
}

function _ctVoxelVolumeCm3() {
    const spacing = state?.ctSpacing;
    if (!Array.isArray(spacing) || spacing.length < 3) return null;
    const volume = Number(spacing[0]) * Number(spacing[1]) * Number(spacing[2]) / 1000;
    return Number.isFinite(volume) && volume > 0 ? volume : null;
}

function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

/******** VOLUME-BASED RENDERING ********/
let volumeData = null;
let volumeShape = null;
let volumeSpacing = null;

/**
 * Compute statistics over the loaded CT volume and return an object
 * shaped for imageAnalysisData.ct.
 *
 * Reads (module-level):
 *   volumeData    — Int16Array of HU values, length = Z*Y*X
 *   volumeShape   — [Z, Y, X]
 *   volumeSpacing — [X, Y, Z] in mm
 *
 * Returns:
 *   {
 *     shape: [Z, Y, X], spacing: [X, Y, Z],
 *     huRange: [minHU, maxHU], meanHU,
 *     scanRange: [Z*Zspacing, Y*Yspacing, X*Xspacing] in cm (for the
 *                "scan range" rows in the Analysis panel),
 *     voxelCount, kind: 'volume', sourceMeta: {}
 *   }
 *
 * Falls back to safe empty stats if volumeData is null (e.g. before a
 * load completes) so callers can still consume the result.
 */
function computeCTStats() {
    try {
        if (!volumeData || !volumeShape || volumeShape.length !== 3) {
            return { shape: null, spacing: null, huRange: null, meanHU: 0, scanRange: null, voxelCount: 0, kind: 'volume' };
        }
        // Use sampled statistics — full volume scan on a 48x512x512
        // (~12.5M voxels) takes ~50ms. Sample every Nth voxel so the
        // mean is within ~0.1% of the exact value, but scan is ~5ms.
        const N = volumeData.length;
        const step = Math.max(1, Math.floor(N / 200000)); // ≤ 200k samples
        let minHU = Infinity, maxHU = -Infinity, sum = 0, count = 0;
        for (let i = 0; i < N; i += step) {
            const v = volumeData[i];
            if (v < minHU) minHU = v;
            if (v > maxHU) maxHU = v;
            sum += v;
            count++;
        }
        const meanHU = count > 0 ? sum / count : 0;
        const sx = volumeSpacing[0] || 1;
        const sy = volumeSpacing[1] || 1;
        const sz = volumeSpacing[2] || 1;
        // scanRange: physical extent of each axis in cm (mm / 10)
        const scanRange = [
            (volumeShape[0] * sz / 10).toFixed(1),
            (volumeShape[1] * sy / 10).toFixed(1),
            (volumeShape[2] * sx / 10).toFixed(1),
        ];
        return {
            shape: volumeShape.slice(),
            spacing: [sx, sy, sz],
            huRange: [minHU, maxHU],
            meanHU,
            scanRange,
            voxelCount: N,
            kind: 'volume',
            sourceMeta: {},
        };
    } catch (e) {
        console.warn('computeCTStats failed:', e);
        return { shape: null, spacing: null, huRange: null, meanHU: 0, scanRange: null, voxelCount: 0, kind: 'volume' };
    }
}

// Label volumes for client-side overlay rendering (3D Slicer style)
let ctvLabelData = null;   // Uint8Array, shape (Z, Y, X)
let oarLabelData = null;   // Uint8Array, shape (Z, Y, X)
let labelColorLUT = {};    // {label_id: [R, G, B]}
let organMetaFromServer = {};  // {label_id: {name, color, voxels}}
let viewerDataLoadGeneration = 0;

function invalidateViewerDataLoads() {
    viewerDataLoadGeneration += 1;
    return viewerDataLoadGeneration;
}
function _getMprGeometry(axis, shape, spacing) {
    const [Z, Y, X] = shape;
    const sp = spacing || [0.68, 0.68, 5.0];
    const spacingX = sp[0] || 0.68;
    const spacingY = sp[1] || 0.68;
    const spacingZ = sp[2] || 5.0;
    if (axis === 'axial') return { width: X, height: Y, resampleRatio: 1 };
    if (axis === 'sagittal') {
        const ratio = Math.max(spacingZ / spacingY, 0.01);
        return { width: Y, height: Math.max(1, Math.round(Z * ratio)), resampleRatio: ratio };
    }
    const ratio = Math.max(spacingZ / spacingX, 0.01);
    return { width: X, height: Math.max(1, Math.round(Z * ratio)), resampleRatio: ratio };
}

function _displayYToVolumeZ(py, resampleRatio, zCount) {
    return Math.max(0, Math.min(Math.floor(py / (resampleRatio || 1)), zCount - 1));
}

function _volumeZToDisplayY(z, resampleRatio) {
    return z * (resampleRatio || 1);
}

async function loadVolumeData() {
    const generation = viewerDataLoadGeneration;
    const sessionId = state.sessionId || null;
    // Threshold is an optional display filter, not a segmentation result.
    // Reset it when a new volume is loaded so a stale session setting cannot
    // create an unexplained red whole-body overlay.
    state.viewerSettings.threshold = null;
    const thresholdInput = document.getElementById('viewerThreshold');
    if (thresholdInput) thresholdInput.value = '';
    const res = await fetch(API + '/viewer/volume');
    if (!res.ok) throw new Error('Failed to load volume');
    if (generation !== viewerDataLoadGeneration || (sessionId != null && sessionId !== state.sessionId)) return false;

    const shapeZ = parseInt(res.headers.get('X-Shape-Z'));
    const shapeY = parseInt(res.headers.get('X-Shape-Y'));
    const shapeX = parseInt(res.headers.get('X-Shape-X'));
    volumeShape = [shapeZ, shapeY, shapeX];
    volumeSpacing = [
        parseFloat(res.headers.get('X-Spacing-X')),
        parseFloat(res.headers.get('X-Spacing-Y')),
        parseFloat(res.headers.get('X-Spacing-Z'))
    ];

    const buffer = await res.arrayBuffer();
    if (generation !== viewerDataLoadGeneration || (sessionId != null && sessionId !== state.sessionId)) return false;
    volumeData = new Int16Array(buffer);
    uiDebugLog(`Volume loaded: ${shapeZ}x${shapeY}x${shapeX}, ${volumeData.length} voxels`);

    // Update Image Analysis now that volume data is available
    if (!imageAnalysisData.ct) {
        imageAnalysisData.ct = computeCTStats();
    }
    updateImageAnalysis();

    // Setup resize observer for 2D viewers to fix black screen issue
    ['axial', 'sagittal', 'coronal'].forEach(axis => {
        const canvas = document.getElementById('sliceCanvas' + capitalize(axis));
        if (canvas && canvas.parentElement) {
            if (!canvas._resizeObserver) {
                canvas._resizeObserver = new ResizeObserver(() => {
                    if (volumeData && canvas.style.display !== 'none') {
                        requestAnimationFrame(() => renderSliceFromVolume(axis, state.slices[axis]));
                    }
                });
                canvas._resizeObserver.observe(canvas.parentElement);
            }
        }
    });
}

async function hydrateOarDataTreeFromServer(expectedGeneration, expectedSessionId) {
    // The binary label-volume response is deliberately optimized for 2D
    // rendering. Reverse proxies may omit a large optional metadata header,
    // which used to leave the OAR pixels visible while the Data Tree appeared
    // empty after a session restore. The lightweight organs endpoint is the
    // authoritative metadata fallback for the same selected workspace.
    try {
        const response = await fetch(API + '/viewer/organs');
        if (!response.ok) return false;
        const payload = await response.json();
        if (expectedGeneration !== viewerDataLoadGeneration
            || (expectedSessionId != null && expectedSessionId !== state.sessionId)) return false;
        const organs = payload?.organs || {};
        if (!Object.keys(organs).length) return false;
        updateOrganList(organs, payload.oar_source || '');
        if (typeof dataTreeState !== 'undefined' && dataTreeState.oar) {
            dataTreeState.oar.loaded = true;
            dataTreeState.oar.visible = true;
        }
        try { if (typeof renderDataTree === 'function') renderDataTree(); } catch (_) {}
        return true;
    } catch (error) {
        console.debug('[viewer] OAR Data Tree metadata fallback unavailable:', error);
        return false;
    }
}

async function loadLabelVolumes() {
    const generation = viewerDataLoadGeneration;
    const sessionId = state.sessionId || null;
    try {
        const res = await fetch(API + '/viewer/label_volume');
        if (!res.ok) { uiDebugLog('No label volumes available'); return; }
        if (generation !== viewerDataLoadGeneration || (sessionId != null && sessionId !== state.sessionId)) return false;

        const shapeZ = parseInt(res.headers.get('X-Shape-Z'));
        const shapeY = parseInt(res.headers.get('X-Shape-Y'));
        const shapeX = parseInt(res.headers.get('X-Shape-X'));
        const hasCTV = res.headers.get('X-Has-CTV') === 'true';
        const hasOAR = res.headers.get('X-Has-OAR') === 'true';
        const ctvSize = parseInt(res.headers.get('X-CTV-Size') || '0');
        const oarSize = parseInt(res.headers.get('X-OAR-Size') || '0');
        const oarSource = res.headers.get('X-OAR-Source') || '';

        labelColorLUT = JSON.parse(res.headers.get('X-Color-LUT') || '{}');
        // Override CTV label 1 (tumor) color: bright pink instead of
        // the server's blue which is too close to the dose overlay color.
        if (labelColorLUT[1]) labelColorLUT[1] = [255, 105, 180]; // hot pink
        // Override OAR labels whose golden-ratio HSV hue lands near red
        // (labels 5, 8, 13, 21, 34, 55, 89 have h≈0 from _label_color).
        // These large organs rendered in orange-red created the 'red mask' effect.
        if (labelColorLUT[5])  labelColorLUT[5]  = [46, 180, 140];  // liver → teal
        if (labelColorLUT[8])  labelColorLUT[8]  = [200, 130, 180];  // adrenal → mauve
        if (labelColorLUT[13]) labelColorLUT[13] = [60, 160, 210];  // lung → sky blue
        if (labelColorLUT[21]) labelColorLUT[21] = [140, 90, 200];  // bladder → purple
        if (labelColorLUT[34]) labelColorLUT[34] = [100, 150, 200]; // vertebra → steel blue
        if (labelColorLUT[55]) labelColorLUT[55] = [200, 120, 80];  // vessel → brown
        if (labelColorLUT[89]) labelColorLUT[89] = [120, 180, 110]; // iliopsoas → sage
        // Load CTV label names from backend (not hardcoded)
        const ctvLabelMapRaw = res.headers.get('X-CTV-Label-Map');
        if (ctvLabelMapRaw) {
            try { window._ctvLabelMap = JSON.parse(ctvLabelMapRaw); } catch(e) { window._ctvLabelMap = {}; }
        }
        try {
            organMetaFromServer = JSON.parse(res.headers.get('X-Organ-Meta') || '{}');
        } catch (error) {
            // Keep rendering the binary labels and fetch names through the
            // metadata endpoint below. A malformed optional header must not
            // discard an otherwise valid session restore.
            console.warn('[viewer] Invalid OAR metadata header:', error);
            organMetaFromServer = {};
        }

        const buffer = await res.arrayBuffer();
        if (generation !== viewerDataLoadGeneration || (sessionId != null && sessionId !== state.sessionId)) return false;
        const allBytes = new Uint8Array(buffer);
        const sliceSize = shapeY * shapeX;

        ctvLabelData = null;
        oarLabelData = null;

        if (hasCTV && ctvSize > 0) {
            ctvLabelData = new Uint8Array(allBytes.buffer, 0, ctvSize / 1);
            // Verify size matches expected
            const expected = shapeZ * sliceSize;
            if (ctvLabelData.length !== expected) {
                console.warn(`CTV label size mismatch: ${ctvLabelData.length} vs expected ${expected}`);
            }
        }

        if (hasOAR && oarSize > 0) {
            const oarStart = ctvSize;
            oarLabelData = new Uint8Array(allBytes.buffer, oarStart, oarSize / 1);
            const expected = shapeZ * sliceSize;
            if (oarLabelData.length !== expected) {
                console.warn(`OAR label size mismatch: ${oarLabelData.length} vs expected ${expected}`);
            }
        }

        uiDebugLog(`Label volumes loaded: CTV=${hasCTV}, OAR=${hasOAR}, ${Object.keys(labelColorLUT).length} labels`);

        // Update data tree with organ metadata
        if (Object.keys(organMetaFromServer).length > 0) {
            // Convert to {label_id: {name, voxel_count, color}} format for updateOrganList
            const organData = {};
            for (const [id, meta] of Object.entries(organMetaFromServer)) {
                organData[id] = {
                    name: meta.name,
                    voxel_count: meta.voxels,
                    color: `rgb(${meta.color.join(',')})`,
                };
            }
            updateOrganList(organData, oarSource);
        } else if (hasOAR) {
            // Do not block slice rendering on metadata. The Data Tree is
            // repaired asynchronously once the browser has painted the
            // restored 2D labels.
            void hydrateOarDataTreeFromServer(generation, sessionId);
        }
        // Always flip the data tree flags based on what we got, then
        // re-render. This is what makes "CTV/OAR don't show in the
        // data tree" go away — the previous version only re-rendered
        // when organMeta was non-empty, so empty-CT cases (and the
        // very first response from /viewer/label_volume) left the
        // tree with .loaded = false.
        if (typeof dataTreeState !== 'undefined' && dataTreeState.ctv) {
            if (hasCTV) {
                dataTreeState.ctv.loaded = true;
                dataTreeState.ctv.visible = true;
            }
        }
        if (typeof dataTreeState !== 'undefined' && dataTreeState.oar) {
            if (hasOAR) {
                dataTreeState.oar.loaded = true;
                dataTreeState.oar.visible = true;
            }
        }
        // Force a re-render of the data tree regardless of metadata.
        try { if (typeof renderDataTree === 'function') renderDataTree(); } catch (_) {}
        if ((hasCTV || hasOAR) && state && state.viewerSettings) {
            state.viewerSettings.displayMode = 'overlay';
            state.viewerSettings.showCTV = true;
            // OAR slice overlay is ON by default but all individual organs
            // start invisible — showing 57+ TotalSegmentator labels
            // simultaneously creates a confusing full-body mask appearance.
            // Users enable specific organs via the data tree toggles.
            state.viewerSettings.showOAR = true;
            const dm = document.getElementById('displayMode');
            if (dm) dm.value = 'overlay';
            const ctvCb = document.getElementById('overlayCTV');
            if (ctvCb) ctvCb.checked = true;
            const oarCb = document.getElementById('overlayOAR');
            if (oarCb) oarCb.checked = false;
            if (volumeData && volumeShape) {
                ['axial', 'sagittal', 'coronal'].forEach(axis => {
                    try { renderSliceFromVolume(axis, state.slices[axis]); } catch (_) {}
                });
            }
        }
    } catch (e) {
        console.error('Failed to load label volumes:', e);
    }
}

// Pre-allocate pixel buffer for reuse
let _pixelBuffer = null;
let _imageDataBuffer = null;

function renderOverlayFromVolume(axis, sliceIndex) {
    if (!volumeShape) return;

    const overlayCanvas = document.getElementById('labelOverlay_' + capitalize(axis));
    if (!overlayCanvas) return;

    const displayMode = state.viewerSettings.displayMode || 'ct';
    const showCTV = state.viewerSettings.showCTV;
    const showOAR = state.viewerSettings.showOAR;
    const ctCanvas = document.getElementById('sliceCanvas' + capitalize(axis));

    // Handle display mode
    if (displayMode === 'label') {
        if (ctCanvas) ctCanvas.style.opacity = '0';
        overlayCanvas.style.opacity = '1';
        overlayCanvas.style.display = 'block';
    } else if (displayMode === 'overlay') {
        if (ctCanvas) ctCanvas.style.opacity = '1';
        overlayCanvas.style.opacity = '1';
        overlayCanvas.style.display = 'block';
    } else {
        if (ctCanvas) ctCanvas.style.opacity = '1';
        overlayCanvas.style.display = 'none';
        return;
    }

    const ctvVisible = dataTreeState.ctv.visible && showCTV;
    const oarVisible = dataTreeState.oar.visible && showOAR;

    if (!oarVisible && !ctvVisible && displayMode !== 'label') {
        overlayCanvas.style.display = 'none';
        if (displayMode === 'label' && ctCanvas) ctCanvas.style.opacity = '1';
        return;
    }

    if (!ctvLabelData && !oarLabelData) {
        // Fallback to server-based overlay (debounced to avoid spam)
        // Clear overlay first to prevent stale mask from previous slice
        const ctx = overlayCanvas.getContext('2d');
        ctx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
        if (!renderOverlayFromVolume._timers) renderOverlayFromVolume._timers = {};
        if (renderOverlayFromVolume._timers[axis]) clearTimeout(renderOverlayFromVolume._timers[axis]);
        renderOverlayFromVolume._timers[axis] = setTimeout(() => loadOverlay(axis, sliceIndex), 50);
        return;
    }

    const [Z, Y, X] = volumeShape;
    const spacing = volumeSpacing || [0.68, 0.68, 5.0];
    const geom = _getMprGeometry(axis, [Z, Y, X], spacing);
    const width = geom.width;
    const height = geom.height;
    const resampleRatio = geom.resampleRatio;

    // Size overlay canvas to match CT canvas pixel dimensions
    // IMPORTANT: setting canvas.width/height clears the canvas, so only do it when needed
    const sizeChanged = overlayCanvas.width !== width || overlayCanvas.height !== height;
    if (sizeChanged) {
        overlayCanvas.width = width;
        overlayCanvas.height = height;
    }

    const ctx = overlayCanvas.getContext('2d');
    // Always clear before drawing to prevent stale mask from previous slice
    ctx.clearRect(0, 0, width, height);
    const imageData = ctx.createImageData(width, height);
    const data = imageData.data;
    const sliceSize = Y * X;

    // Get organ opacities from data tree
    const organOpacities = {};
    dataTreeState.organs.forEach(o => { organOpacities[o.labelId] = o.opacity; });

    for (let py = 0; py < height; py++) {
        for (let px = 0; px < width; px++) {
            // Map display coords to volume coords.
            // Keep sagittal/coronal Z in the same display order used by
            // crosshair and dose overlays. Axial keeps its historical
            // slice-index flip below, but vertical Z in reformatted views
            // must not be inverted.
            let volZ, volY, volX;
            if (axis === 'axial') {
                volZ = (Z - 1) - sliceIndex; volY = py; volX = px;
            }
            else if (axis === 'sagittal') {
                volZ = _displayYToVolumeZ(py, resampleRatio, Z);
                volY = px; volX = sliceIndex;
            } else {
                volZ = _displayYToVolumeZ(py, resampleRatio, Z);
                volY = sliceIndex; volX = px;
            }

            const flatIdx = volZ * sliceSize + volY * X + volX;
            const outIdx = (py * width + px) * 4;

            let r = 0, g = 0, b = 0, a = 0;

            // OAR takes priority (drawn on top)
            if (oarVisible && oarLabelData && oarLabelData.length > flatIdx) {
                const oarVal = oarLabelData[flatIdx];
                if (oarVal > 0) {
                    const visible = !dataTreeState.organs.length ||
                                    dataTreeState.organs.some(o => o.labelId === oarVal && o.visible);
                    if (visible) {
                        const color = labelColorLUT[oarVal] || [200, 200, 200];
                        const opacity = organOpacities[oarVal] !== undefined ? organOpacities[oarVal] : 0.5;
                        r = color[0];
                        g = color[1];
                        b = color[2];
                        a = Math.round(opacity * 255);
                    }
                }
            }

            // CTV drawn underneath (only if no OAR at this pixel)
            if (ctvVisible && a === 0 && ctvLabelData && ctvLabelData.length > flatIdx) {
                const ctvVal = ctvLabelData[flatIdx];
                if (ctvVal > 0) {
                    // Use per-label color from LUT (label 1=blue, 2=green, 3=pink, etc.)
                    const color = labelColorLUT[ctvVal] || [220, 160, 210];
                    const opacity = dataTreeState.ctv.opacity ?? 0.7;
                    r = color[0];
                    g = color[1];
                    b = color[2];
                    a = Math.round(opacity * 255);
                }
            }

            data[outIdx] = r;
            data[outIdx + 1] = g;
            data[outIdx + 2] = b;
            data[outIdx + 3] = a;
        }
    }

    ctx.putImageData(imageData, 0, 0);

    // Match overlay display to CT canvas
    if (ctCanvas) {
        overlayCanvas.style.width = ctCanvas.style.width;
        overlayCanvas.style.height = ctCanvas.style.height;
        overlayCanvas.style.position = 'absolute';
        overlayCanvas.style.left = ctCanvas.style.left;
        overlayCanvas.style.top = ctCanvas.style.top;
    }
}

function renderSliceFromVolume(axis, sliceIndex) {
    if (!volumeData || !volumeShape) return;

    const [Z, Y, X] = volumeShape;
    const wc = state.viewerSettings.level;
    const ww = state.viewerSettings.window;
    const lower = wc - ww / 2;
    const upper = wc + ww / 2;
    const range = ww || 1;  // Avoid division by zero
    const scale = 255 / range;

    // Get spacing for isotropic resampling
    const spacing = volumeSpacing || [0.68, 0.68, 5.0];
    const geom = _getMprGeometry(axis, [Z, Y, X], spacing);

    let width = geom.width, height = geom.height;
    let resampleRatio = geom.resampleRatio;

    /*
    if (axis === 'axial') {
        width = X;
        height = Y;
    } else if (axis === 'sagittal') {
        // Y × Z, need to resample Z to match Y spacing
        width = Y;
        height = Math.round(Z * spacingZ / spacingY); // Resample Z to isotropic
        resampleRatio = spacingZ / spacingY;
    } else {
        // X × Z, need to resample Z to match X spacing
        width = X;
        height = Math.round(Z * spacingZ / spacingX);
        resampleRatio = spacingZ / spacingX;
    }
    */

    const pixelCount = width * height;

    // Reuse pixel buffer if size matches
    if (!_pixelBuffer || _pixelBuffer.length !== pixelCount) {
        _pixelBuffer = new Uint8ClampedArray(pixelCount);
    }
    const pixels = _pixelBuffer;

    // Extract and transform pixels in one pass.
    // Axial keeps the historical Z slice-index flip. Sagittal/coronal
    // reformats do not flip display Y; dose, crosshair, and contours already
    // use the non-flipped Z order there.
    if (axis === 'axial') {
        const srcSliceIdx = (Z - 1) - sliceIndex;
        const offset = srcSliceIdx * Y * X;
        for (let i = 0; i < pixelCount; i++) {
            const val = volumeData[offset + i];
            pixels[i] = val <= lower ? 0 : (val >= upper ? 255 : ((val - lower) * scale));
        }
    } else if (axis === 'sagittal') {
        // Resample Z axis to match Y spacing (isotropic display)
        let idx = 0;
        for (let displayY = 0; displayY < height; displayY++) {
            const srcZ = _displayYToVolumeZ(displayY, resampleRatio, Z);
            const zOffset = srcZ * Y * X + sliceIndex;
            for (let y = 0; y < Y; y++) {
                const val = volumeData[zOffset + y * X];
                pixels[idx++] = val <= lower ? 0 : (val >= upper ? 255 : ((val - lower) * scale));
            }
        }
    } else {
        // Resample Z axis to match X spacing (isotropic display)
        let idx = 0;
        for (let displayY = 0; displayY < height; displayY++) {
            const srcZ = _displayYToVolumeZ(displayY, resampleRatio, Z);
            const zOffset = srcZ * Y * X + sliceIndex * X;
            for (let x = 0; x < X; x++) {
                const val = volumeData[zOffset + x];
                pixels[idx++] = val <= lower ? 0 : (val >= upper ? 255 : ((val - lower) * scale));
            }
        }
    }

    const canvasId = 'sliceCanvas' + capitalize(axis);
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const container = canvas.parentElement;
    const ctx = canvas.getContext('2d');

    canvas.width = width;
    canvas.height = height;

    // Reuse imageData buffer if size matches
    if (!_imageDataBuffer || _imageDataBuffer.width !== width || _imageDataBuffer.height !== height) {
        _imageDataBuffer = ctx.createImageData(width, height);
    }
    const imageData = _imageDataBuffer;

    // Fill RGBA in one pass (grayscale), compositing overlay inline
    const data = imageData.data;
    const displayMode = state.viewerSettings.displayMode || 'ct';
    const isLabelOnly = displayMode === 'label';
    const showOverlay = (ctvLabelData || oarLabelData) &&
                        (displayMode === 'overlay' || isLabelOnly) &&
                        ((dataTreeState.ctv.visible && state.viewerSettings.showCTV) ||
                         (dataTreeState.oar.visible && state.viewerSettings.showOAR));
    const labelSliceSize = Y * X;
    const organOpacities = showOverlay ? (() => { const m = {}; dataTreeState.organs.forEach(o => { m[o.labelId] = o.opacity; }); return m; })() : {};
    const thresholdRaw = state.viewerSettings.threshold;
    const thresholdEnabled = thresholdRaw !== null && Number.isFinite(Number(thresholdRaw));
    const thresholdValue = thresholdEnabled ? Number(thresholdRaw) : 0;

    for (let py = 0; py < height; py++) {
        for (let px = 0; px < width; px++) {
            // Map display coords to volume coords for label lookup.
            // Match the CT extraction above: axial slice index is flipped,
            // sagittal/coronal display Y is not.
            let volZ, volY2, volX2;
            if (axis === 'axial') {
                volZ = (Z - 1) - sliceIndex; volY2 = py; volX2 = px;
            }
            else if (axis === 'sagittal') {
                volZ = _displayYToVolumeZ(py, resampleRatio, Z);
                volY2 = px; volX2 = sliceIndex;
            } else {
                volZ = _displayYToVolumeZ(py, resampleRatio, Z);
                volY2 = sliceIndex; volX2 = px;
            }
            const flatIdx = volZ * labelSliceSize + volY2 * X + volX2;

            let r, g, b, a = 255;
            const ctVal = pixels[py * width + px];
            r = ctVal; g = ctVal; b = ctVal;

            // Match the server-rendered fallback: thresholding is evaluated in
            // physical HU, then highlighted over the windowed CT image.
            if (thresholdEnabled && !isLabelOnly && volumeData[flatIdx] > thresholdValue) {
                r = Math.min(255, r + 120);
                g = Math.max(0, g - 80);
                b = Math.max(0, b - 80);
            }

            if (showOverlay && flatIdx >= 0) {
                let oR = 0, oG = 0, oB = 0, oA = 0;

                // OAR overlay
                if (dataTreeState.oar.visible && state.viewerSettings.showOAR && oarLabelData && oarLabelData.length > flatIdx) {
                    const oarVal = oarLabelData[flatIdx];
                    if (oarVal > 0) {
                        const visible = !dataTreeState.organs.length ||
                                        dataTreeState.organs.some(o => o.labelId === oarVal && o.visible);
                        if (visible) {
                            const color = labelColorLUT[oarVal] || [200, 200, 200];
                            const opacity = organOpacities[oarVal] !== undefined ? organOpacities[oarVal] : 0.5;
                            oR = color[0]; oG = color[1]; oB = color[2]; oA = Math.round(opacity * 255);
                            oR = color[0]; oG = color[1]; oB = color[2]; oA = Math.round(opacity * 255);
                        }
                    }
                }

                // CTV overlay (only if no OAR at this pixel)
                if (oA === 0 && dataTreeState.ctv.visible && state.viewerSettings.showCTV && ctvLabelData && ctvLabelData.length > flatIdx) {
                    const ctvVal = ctvLabelData[flatIdx];
                    if (ctvVal > 0) {
                        // Use per-label color from LUT
                        const color = labelColorLUT[ctvVal] || [220, 160, 210];
                            const labelState = dataTreeState.ctvLabels?.[`ctv_${ctvVal}`];
                            const labelVisible = labelState ? labelState.visible !== false : true;
                            if (labelVisible) {
                                const opacity = dataTreeState.ctv.labelOpacities?.[ctvVal]
                                    ?? labelState?.opacity
                                    ?? dataTreeState.ctv.opacity
                                    ?? 0.7;
                                oR = color[0]; oG = color[1]; oB = color[2]; oA = Math.round(opacity * 255);
                            }
                    }
                }

                // Alpha-blend overlay onto CT (or onto black in label-only mode)
                if (oA > 0) {
                    const alpha = oA / 255;
                    const bg = isLabelOnly ? 0 : ctVal;
                    r = Math.round(bg * (1 - alpha) + oR * alpha);
                    g = Math.round(bg * (1 - alpha) + oG * alpha);
                    b = Math.round(bg * (1 - alpha) + oB * alpha);
                } else if (isLabelOnly) {
                    r = 0; g = 0; b = 0;
                }
            }

            const outIdx = (py * width + px) * 4;
            data[outIdx] = r;
            data[outIdx + 1] = g;
            data[outIdx + 2] = b;
            data[outIdx + 3] = a;
        }
    }
    ctx.putImageData(imageData, 0, 0);

    const containerRect = container.getBoundingClientRect();
    // Do not render against an invented fallback size while the viewer is
    // hidden during tab/fullscreen transitions. The next ResizeObserver event
    // will render with the real geometry once the container is visible.
    const containerW = containerRect.width;
    const containerH = containerRect.height;
    if (containerW < 1 || containerH < 1) return;
    const displayScale = Math.min(containerW / width, containerH / height) || 1;
    const displayW = width * displayScale;
    const displayH = height * displayScale;

    canvas.style.width = displayW + 'px';
    canvas.style.height = displayH + 'px';
    canvas.style.position = 'absolute';
    // Only set base position once per container size change (not every slice)
    // to avoid overriding pan transform from applyViewerTransform
    const baseLeft = ((containerW - displayW) / 2) + 'px';
    const baseTop = ((containerH - displayH) / 2) + 'px';
    if (!canvas._posSet || canvas._posContainerW !== containerW || canvas._posContainerH !== containerH) {
        canvas.style.left = baseLeft;
        canvas.style.top = baseTop;
        canvas._posSet = true;
        canvas._posContainerW = containerW;
        canvas._posContainerH = containerH;
    }
    canvas.style.display = 'block';

    const placeholder = container.querySelector('.viewer-no-data');
    if (placeholder) placeholder.style.display = 'none';

    canvas._displayScale = displayScale;
    canvas._displayW = displayW;
    canvas._displayH = displayH;
    canvas._offsetX = (containerW - displayW) / 2;
    canvas._offsetY = (containerH - displayH) / 2;

    const crossCanvas = document.getElementById('crosshairCanvas' + capitalize(axis));
    if (crossCanvas) {
        // Use CT canvas pixel dimensions for consistent alignment
        crossCanvas.width = width;
        crossCanvas.height = height;
        crossCanvas.style.width = displayW + 'px';
        crossCanvas.style.height = displayH + 'px';
        crossCanvas.style.position = 'absolute';
        if (!crossCanvas._posSet || crossCanvas._posContainerW !== containerW || crossCanvas._posContainerH !== containerH) {
            crossCanvas.style.left = baseLeft;
            crossCanvas.style.top = baseTop;
            crossCanvas._posSet = true;
            crossCanvas._posContainerW = containerW;
            crossCanvas._posContainerH = containerH;
        }
    }

    syncAnnotationCanvasSize(axis);
    redrawAllAnnotations();

    // Dose overlay rendering: AFTER the CT canvas's display dimensions
    // (_displayW, _displayH, _offsetX, _offsetY) are fully set above,
    // so the dose canvas copies the correct position/size.
    if (state.doseOverlay && state.doseOverlay.visible) {
        renderDoseForCurrentSlice(axis, sliceIndex);
        triggerDoseContourRender(axis, sliceIndex);
    }

    if (state.seedsOverlay && ((state.seedsOverlay.seeds || []).length || (state.seedsOverlay.needles || []).length)) {
        renderSeedsOverlay(axis, sliceIndex);
    }

    // Overlay is composited inline into CT pixels — hide the separate overlay canvas
    const overlayCanvas = document.getElementById('labelOverlay_' + capitalize(axis));
    if (overlayCanvas) {
        overlayCanvas.style.display = 'none';
    }
}

async function loadOverlay(axis, sliceIndex) {
    // Skip server-based overlay when label volumes are loaded (inline compositing handles it)
    if (ctvLabelData || oarLabelData) return;

    const overlayCanvas = document.getElementById('labelOverlay_' + capitalize(axis));
    if (!overlayCanvas) return;

    const ctCanvas = document.getElementById('sliceCanvas' + capitalize(axis));
    const displayMode = state.viewerSettings.displayMode || 'ct';

    const showOAR = state.viewerSettings.showOAR;
    const showCTV = state.viewerSettings.showCTV;

    // Label Only mode
    if (displayMode === 'label') {
        if (ctCanvas) ctCanvas.style.opacity = '0';
        overlayCanvas.style.opacity = '1';
        overlayCanvas.style.display = 'block';
    } else if (displayMode === 'overlay') {
        if (ctCanvas) ctCanvas.style.opacity = '1';
        overlayCanvas.style.opacity = '1';  // Alpha is baked into RGBA from server
        overlayCanvas.style.display = 'block';
    } else {
        // CT Only mode
        if (ctCanvas) ctCanvas.style.opacity = '1';
        overlayCanvas.style.display = 'none';
        return;
    }

    const ctvVisible = dataTreeState.ctv.visible && showCTV;
    const oarVisible = dataTreeState.oar.visible && showOAR;

    if (!oarVisible && !ctvVisible) {
        overlayCanvas.style.display = 'none';
        if (displayMode === 'label' && ctCanvas) ctCanvas.style.opacity = '1';
        return;
    }

    try {
        // Set overlay canvas to CT canvas pixel dimensions (not display size)
        const ctW = ctCanvas ? ctCanvas.width : 512;
        const ctH = ctCanvas ? ctCanvas.height : 512;
        // Only resize if pixel dimensions actually changed to prevent flicker
        if (overlayCanvas.width !== ctW || overlayCanvas.height !== ctH) {
            overlayCanvas.width = ctW;
            overlayCanvas.height = ctH;
        }

        // Fetch CTV and OAR separately, draw onto one canvas
        let hasAnyMask = false;
        const ctx = overlayCanvas.getContext('2d');
        ctx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);

        if (ctvVisible) {
            const resCtv = await fetch(API + '/viewer/overlay', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ axis, slice_index: sliceIndex, overlay_type: 'ctv', ctv_opacity: dataTreeState.ctv.opacity }),
            });
            if (resCtv.ok) {
                const d = await resCtv.json();
                if (d.has_mask && d.data) {
                    const img = new Image();
                    await new Promise(r => { img.onload = r; img.src = d.data; });
                    ctx.drawImage(img, 0, 0, overlayCanvas.width, overlayCanvas.height);
                    hasAnyMask = true;
                }
            }
        }

        if (oarVisible && dataTreeState.organs.length > 0) {
            const visibleOrgans = dataTreeState.organs.filter(o => o.visible).map(o => o.labelId);
            const organOpacities = {};
            dataTreeState.organs.forEach(o => { organOpacities[o.labelId] = o.opacity; });
            const resOar = await fetch(API + '/viewer/overlay', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ axis, slice_index: sliceIndex, overlay_type: 'oar', visible_organs: visibleOrgans, organ_opacities: organOpacities, oar_opacity: dataTreeState.oar.opacity }),
            });
            if (resOar.ok) {
                const d = await resOar.json();
                if (d.has_mask && d.data) {
                    const img = new Image();
                    await new Promise(r => { img.onload = r; img.src = d.data; });
                    ctx.drawImage(img, 0, 0, overlayCanvas.width, overlayCanvas.height);
                    hasAnyMask = true;
                }
            }
        }

        if (hasAnyMask) {
            if (ctCanvas) {
                overlayCanvas.style.width = ctCanvas.style.width;
                overlayCanvas.style.height = ctCanvas.style.height;
                overlayCanvas.style.position = 'absolute';
                overlayCanvas.style.left = ctCanvas.style.left;
                overlayCanvas.style.top = ctCanvas.style.top;
                overlayCanvas.style.right = 'auto';
                overlayCanvas.style.bottom = 'auto';
                overlayCanvas.style.display = 'block';
                // Copy transform from CT canvas
                if (ctCanvas.style.transform) {
                    overlayCanvas.style.transform = ctCanvas.style.transform;
                    overlayCanvas.style.transformOrigin = ctCanvas.style.transformOrigin || 'center center';
                }
            }

        } else {
            overlayCanvas.style.display = 'none';
            if (displayMode === 'label' && ctCanvas) ctCanvas.style.opacity = '1';
        }
    } catch (e) {
        // Silently fail - don't hide overlay on error
    }
}

function toggleOAROverlay() {
    state.viewerSettings.showOAR = !state.viewerSettings.showOAR;
    // Reload current slices to update overlay
    ['axial', 'sagittal', 'coronal'].forEach(axis => {
        renderSliceFromVolume(axis, state.slices[axis]);
    });
}

function toggleCTVOverlay() {
    state.viewerSettings.showCTV = !state.viewerSettings.showCTV;
    ['axial', 'sagittal', 'coronal'].forEach(axis => {
        renderSliceFromVolume(axis, state.slices[axis]);
    });
}

/******** VIEWER CONTROLS ********/
const sliceCache = { axial: {}, sagittal: {}, coronal: {} };
const sliceCacheOrder = { axial: [], sagittal: [], coronal: [] };

function clearSliceCache() {
    ['axial', 'sagittal', 'coronal'].forEach(axis => {
        sliceCache[axis] = {};
        sliceCacheOrder[axis] = [];
    });
}

function renderCachedSlice(axis, sliceIndex) {
    const cached = sliceCache[axis][sliceIndex];
    if (cached) {
        renderSliceToCanvas(axis, cached);
        return true;
    }
    return false;
}

async function loadSlice(axis, sliceIndex) {
    if (!state.ctPath) return;
    const generation = window.__viewerRenderGeneration || 0;
    const sessionId = state.sessionId || null;

    const cached = sliceCache[axis][sliceIndex];
    if (cached) {
        renderSliceToCanvas(axis, cached);
        return;
    }

    try {
        const res = await fetch(API + '/viewer/slice', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                axis: axis,
                slice_index: sliceIndex,
                window_center: state.viewerSettings.level,
                window_width: state.viewerSettings.window,
                threshold: state.viewerSettings.threshold !== null ? state.viewerSettings.threshold : undefined,
            }),
        });

        if (!res.ok) return;

        const data = await res.json();
        if (generation !== (window.__viewerRenderGeneration || 0)
            || (sessionId != null && sessionId !== state.sessionId)) return;
        if (data.success) {
            sliceCache[axis][sliceIndex] = data.data;
            renderSliceToCanvas(axis, data.data);
        }
    } catch (e) {
        console.error('Failed to load slice:', e);
    }
}

async function preloadAxis(axis) {
    const slider = document.getElementById('slider' + capitalize(axis));
    if (!slider) return;
    const generation = window.__viewerRenderGeneration || 0;
    const sessionId = state.sessionId || null;
    const max = parseInt(slider.max) || 48;
    sliceCache[axis] = {};

    const batchSize = 10;
    for (let start = 0; start < max; start += batchSize) {
        const end = Math.min(start + batchSize, max);
        const promises = [];
        for (let i = start; i < end; i++) {
            promises.push(
                fetch(API + '/viewer/slice', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        axis: axis,
                        slice_index: i,
                        window_center: state.viewerSettings.level,
                        window_width: state.viewerSettings.window,
                        threshold: state.viewerSettings.threshold !== null ? state.viewerSettings.threshold : undefined,
                    }),
                })
                .then(res => res.ok ? res.json() : null)
                .then(data => {
                    if (generation !== (window.__viewerRenderGeneration || 0)
                        || (sessionId != null && sessionId !== state.sessionId)) return;
                    if (data && data.success) {
                        sliceCache[axis][i] = data.data;
                    }
                })
                .catch(() => {})
            );
        }
        await Promise.all(promises);
    }
    uiDebugLog(`Preloaded ${axis}: ${max} slices`);
}

async function preloadAllSlices() {
    await preloadAxis('axial');
    uiDebugLog('Axial preloaded, sagittal/coronal will load on demand');
}

function resizeCanvas(axis) {
    // Trigger re-render of the current slice to fit new container size
    if (!state.ctLoaded) return;
    const slider = document.getElementById('slider' + capitalize(axis));
    if (slider) {
        renderSliceFromVolume(axis, parseInt(slider.value));
    }
}

function updateSlice(view, val) {
    const sliceIndex = parseInt(val);
    state.slices[view] = sliceIndex;
    const label = document.getElementById('sliceLabel' + capitalize(view));
    if (label) label.textContent = sliceIndex;

    // Use volume-based rendering for instant response
    if (volumeData && volumeShape) {
        renderSliceFromVolume(view, sliceIndex);
    } else {
        // Fallback to server-based rendering
        renderCachedSlice(view, sliceIndex);
        loadSlice(view, sliceIndex);
    }

    // Dose overlay rendering: renderSliceFromVolume calls
    // renderDoseForCurrentSlice at the end. As a safety net, also
    // trigger it here in case the async path in renderSliceFromVolume
    // didn't complete (e.g. dose canvas not yet created).
    if (state.doseOverlay && state.doseOverlay.visible) {
        renderDoseForCurrentSlice(view, sliceIndex);
        triggerDoseContourRender(view, sliceIndex);
    }
    // Seed/needle 2D overlay — render on every slice change
    if (state.seedsOverlay) {
        renderSeedsOverlay(view, sliceIndex);
    }
}

// Coalesce visual updates from controls that change scene state without a
// camera interaction.  This keeps all 2D canvases and the 3D renderer in sync
// while preserving the current slice indices and camera pose.
let _viewerRefreshTimer = null;
function refreshAllViewerCanvases(reason = 'ui-change') {
    if (!state || !state.ctLoaded) {
        if (typeof forceRender3DViewer === 'function') forceRender3DViewer();
        return;
    }
    ['axial', 'sagittal', 'coronal'].forEach(axis => {
        const value = Number.isFinite(Number(state.slices?.[axis])) ? Number(state.slices[axis]) : 0;
        const slider = document.getElementById('slider' + capitalize(axis));
        if (slider) slider.value = String(value);
        updateSlice(axis, value);
    });
    if (typeof forceRender3DViewer === 'function') forceRender3DViewer();
    uiDebugLog(`Viewer refresh: ${reason}`);
}

function requestViewerVisualRefresh(reason = 'ui-change') {
    clearTimeout(_viewerRefreshTimer);
    _viewerRefreshTimer = setTimeout(() => {
        _viewerRefreshTimer = null;
        refreshAllViewerCanvases(reason);
    }, 0);
}

function updateDoseOpacity(val) {
    state.doseOpacity = val / 100;
    requestViewerVisualRefresh('dose-opacity');
}

function updateLabelImage(view) {
    const showEl = document.getElementById('labelShow' + capitalize(view));
    const opEl = document.getElementById('labelOp' + capitalize(view));
    if (!showEl || !opEl) return;

    state.labelImage[view] = {
        visible: showEl.checked,
        opacity: parseInt(opEl.value) / 100,
    };

    const overlay = document.getElementById('labelOverlay_' + view);
    if (overlay) {
        overlay.style.display = state.labelImage[view].visible ? 'block' : 'none';
        overlay.style.opacity = state.labelImage[view].opacity;
    }
}

function applyViewerSettings() {
    const wc = document.getElementById('viewerWindow').value;
    const wl = document.getElementById('viewerLevel').value;
    state.viewerSettings.window = parseInt(wc);
    state.viewerSettings.level = parseInt(wl);
    if (state.ctLoaded) {
        clearSliceCache();
        loadAllSlices();
    }
}

function applyWindowPreset() {
    const preset = document.getElementById('windowPreset').value;
    applyWindowPresetByName(preset);
}

function applyWindowPresetByName(preset) {
    const presets = {
        soft: { w: 400, l: 40 },
        bone: { w: 2000, l: 400 },
        lung: { w: 1500, l: -600 },
        brain: { w: 80, l: 40 },
        custom: null,
    };
    const p = presets[preset];
    if (p) {
        state.viewerSettings.window = p.w;
        state.viewerSettings.level = p.l;
        document.getElementById('viewerWindow').value = p.w;
        document.getElementById('viewerLevel').value = p.l;
        document.getElementById('windowPreset').value = preset;
        if (state.ctLoaded) {
            clearSliceCache();
            loadAllSlices();
        }
    }
}

async function syncViewerState() {
    if (!state.ctLoaded) return;
    try {
        const res = await fetch(API + '/viewer/control', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'get_state' }),
        });
        if (!res.ok) return;
        const data = await res.json();
        if (!data.success) return;

        const s = data;
        const changed = {};

        if (s.window && s.window !== state.viewerSettings.window) {
            state.viewerSettings.window = s.window;
            document.getElementById('viewerWindow').value = s.window;
            changed.window = true;
        }
        if (s.level && s.level !== state.viewerSettings.level) {
            state.viewerSettings.level = s.level;
            document.getElementById('viewerLevel').value = s.level;
            changed.level = true;
        }
        if (s.threshold !== undefined && s.threshold !== state.viewerSettings.threshold) {
            state.viewerSettings.threshold = s.threshold;
            document.getElementById('viewerThreshold').value = s.threshold;
            changed.threshold = true;
        }
        // Don't sync slice positions - frontend is source of truth
        // (Server doesn't store them unless navigate_slice is called)

        if (Object.keys(changed).length > 0) {
            clearSliceCache();
            loadAllSlices();
        }
    } catch (e) {
        // Ignore sync errors
    }
}

function applyThreshold() {
    const raw = document.getElementById('viewerThreshold')?.value?.trim() || '';
    const threshold = raw === '' ? null : Number(raw);
    state.viewerSettings.threshold = Number.isFinite(threshold) ? threshold : null;
    if (state.ctLoaded) {
        clearSliceCache();
        loadAllSlices();
    }
}

function toggleOverlay() {
    state.viewerSettings.showCTV = document.getElementById('overlayCTV').checked;
    state.viewerSettings.showOAR = document.getElementById('overlayOAR').checked;
    // Sync with data tree
    dataTreeState.ctv.visible = state.viewerSettings.showCTV;
    dataTreeState.oar.visible = state.viewerSettings.showOAR;
    renderDataTree();
    if (state.ctLoaded) loadAllSlices();
}

function setDisplayMode() {
    const mode = document.getElementById('displayMode').value;
    state.viewerSettings.displayMode = mode;

    // Auto-check overlay checkboxes based on mode
    if (mode === 'overlay' || mode === 'label') {
        // Enable OAR by default if available
        const oarCb = document.getElementById('overlayOAR');
        if (oarCb && !oarCb.checked) {
            oarCb.checked = true;
            state.viewerSettings.showOAR = true;
            dataTreeState.oar.visible = true;
        }
    }

    renderDataTree();
    if (state.ctLoaded) loadAllSlices();
}

// Reload only overlays (for visibility/opacity changes) without re-rendering CT
function reloadOverlays() {
    // Overlay is composited inline into CT canvas via renderSliceFromVolume
    // Just re-render all slices to pick up overlay changes
    if (state.ctLoaded) {
        loadAllSlices();
    }
}

/******** DATA TREE ********/
const dataTreeState = {
    ct:       { visible: true, opacity: 1.0, color: '#888', loaded: false, label: 'CT Image' },
    ctv:      { visible: true, opacity: 0.7, color: '#ef4444', loaded: false, label: 'CTV Mask' },
    oar:      { visible: true, opacity: 0.5, color: '#22c55e', loaded: false, label: 'All OARs' },
    // Provenance controls whether previous user-edited categories may be
    // carried across a mask replacement. Uploaded unknown labels start as
    // numbered traversable OARs; they must not inherit an old ontology.
    oarSource: '',
    organs:   [],  // Individual organs: [{id, label, color, visible, opacity, voxelCount, category}]
    dose:     { visible: true, opacity: 0.4, color: '#f59e0b', loaded: false, label: 'Dose Distribution' },
    seeds:    { visible: true, opacity: 1.0, color: '#ffcc00', loaded: false, label: 'Seed Positions' },
    needles:  { visible: true, opacity: 0.8, color: '#ff6644', loaded: false, label: 'Needle Paths' },
    // Planning state
    planning: {
        trajectories: [],       // [{id, index, entry, target, visible, opacity, color, seeds: [seed_id, ...]}]
        trajectoriesLoaded: false,
        seeds: [],       // [{id, position, direction, trajectory_id, visible, opacity, color}]
        needles: [],     // [{id, points, trajectory_id, visible, opacity, color}]
        doseLevels: [],  // [{threshold, visible, opacity, color}]
        // 3D meshes reconstructed via 3d.reconstruct / reconstructOrgan3D.
        // Tracked so the data tree can show every mesh currently in the
        // 3D viewer with its own visibility toggle, and the user can see
        // at a glance what's loaded.
        meshes: [],      // [{id, label, source, color, vertices, faces, visible, opacity}]
    },
};

// The Data Tree is the canonical display-state model.  Viewer modes may
// change materials (for example a dose texture), but they must never invent
// a second source of truth for visibility, opacity, or the normal-surface
// color chosen by the user.
function getDataTreeAppearanceForMesh(id, mesh) {
    let item = null;
    if (id === 'ctv') item = dataTreeState.ctv;
    else if (id.startsWith('ctv_')) item = dataTreeState.ctvLabels?.[id] || dataTreeState.ctv;
    else if (id.startsWith('organ_')) item = dataTreeState.organs.find(organ => organ.id === id);
    else if (id.startsWith('seed_')) item = dataTreeState.planning.seeds.find(seed => seed.id === id);
    else if (id.startsWith('needle_') && mesh?.userData?.type !== 'needle_handle') {
        item = dataTreeState.planning.needles.find(needle => needle.id === id);
    } else if (id.startsWith('dose_iso_')) {
        const threshold = Number(id.replace('dose_iso_', ''));
        item = dataTreeState.planning.doseLevels.find(level => Math.abs(Number(level.threshold) - threshold) < 1e-6);
    } else {
        item = dataTreeState.planning.meshes.find(entry => entry.id === id);
    }
    if (!item) return null;
    return {
        visible: item.visible !== false,
        opacity: Number.isFinite(Number(item.opacity)) ? Number(item.opacity) : 1,
        color: item.color,
    };
}

function _setMeshMaterialColor(mesh, color) {
    if (!mesh || !color || !/^#[0-9a-f]{6}$/i.test(color)) return;
    const surface = mesh.surfaceMesh || mesh;
    const r = parseInt(color.slice(1, 3), 16) / 255;
    const g = parseInt(color.slice(3, 5), 16) / 255;
    const b = parseInt(color.slice(5, 7), 16) / 255;
    const materials = Array.isArray(surface.material) ? surface.material : [surface.material];
    materials.forEach(material => material?.color?.setRGB(r, g, b));
}

function syncSceneAppearanceFromDataTree({ preserveDoseTexture = !!state.doseTexture?.enabled } = {}) {
    Object.entries(scene3D.meshes || {}).forEach(([id, mesh]) => {
        if (!mesh || mesh?.userData?.type === 'needle_handle') return;
        const appearance = getDataTreeAppearanceForMesh(id, mesh);
        if (!appearance) return;
        applyMeshOpacity(mesh, appearance.opacity, appearance.visible);
        // Vertex colors are the dose surface itself.  Retain them while that
        // mode is active, but restore the user-selected normal-surface color
        // the moment normal rendering is selected again.
        if (!preserveDoseTexture) _setMeshMaterialColor(mesh, appearance.color);
    });
    if (scene3D.requestRender) scene3D.requestRender(2);
}

window.getDataTreeAppearanceForMesh = getDataTreeAppearanceForMesh;
window.syncSceneAppearanceFromDataTree = syncSceneAppearanceFromDataTree;

// Organ categories for constraint-based planning
const ORGAN_CATEGORIES = {
    ctv:              { label: 'CTV', icon: '🎯', color: '#ef4444' },
    non_traversable:  { label: 'Non-traversable', icon: '🚫', color: '#f97316' },
    traversable:      { label: 'Traversable', icon: '✅', color: '#22c55e' },
};

// Default category classification by organ name keywords
const CATEGORY_RULES = [
    // Non-traversable: bones, cartilage, major vessels, nerves
    { pattern: /bone|rib|skull|spine|vertebra|sacrum|sternum|pelvis|femur|humerus|scapula|clavicula|hip|ilium|ischium|pubis/i, category: 'non_traversable' },
    { pattern: /cartilage|disc|meniscus/i, category: 'non_traversable' },
    { pattern: /aorta|vena\s*cava|iliac\s+(artery|vein|vena)|femoral\s*(artery|vein)|carotid|jugular|artery|vein|vessel|brachiocephalic\s+trunk/i, category: 'non_traversable' },
    { pattern: /nerve|plexus|sciatic|spinal\s*cord|brachial/i, category: 'non_traversable' },
    // Traversable: soft tissue organs
    { pattern: /bladder|rectum|sigmoid|colon|small\s*bowel|intestine|stomach/i, category: 'traversable' },
    { pattern: /prostate|uterus|cervix|vagina|seminal|vesicle/i, category: 'traversable' },
    { pattern: /liver|kidney|spleen|pancreas|adrenal/i, category: 'traversable' },
    { pattern: /lung|heart|esophagus|trachea|bronchus/i, category: 'traversable' },
    { pattern: /muscle|fat|skin|connective/i, category: 'traversable' },
];

function classifyOrgan(organName) {
    // Normalize underscores to spaces so TotalSegmentator names like
    // "spinal_cord" and "small_bowel" match the pattern rules below.
    const name = (organName || '').replace(/_/g, ' ');
    for (const rule of CATEGORY_RULES) {
        if (rule.pattern.test(name)) return rule.category;
    }
    return 'traversable'; // Default: traversable
}

// Context menu state
let activeContextMenu = null;

// Context menus are transient UI, not state. A single capture-phase boundary
// closes them for clicks, touch/pointer presses, Escape, scrolling, and case
// switches. The old one-shot bubble listeners were bypassed by canvas and
// stopPropagation handlers, leaving some endpoint menus stuck on screen.
if (!window.__brachyContextMenuDismissalBound) {
    window.__brachyContextMenuDismissalBound = true;
    document.addEventListener('pointerdown', event => {
        const menu = activeContextMenu || window.__brachyContextMenuElement;
        if (!menu || menu.contains(event.target)) return;
        hideContextMenu();
    }, true);
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') hideContextMenu();
    }, true);
    document.addEventListener('scroll', () => hideContextMenu(), true);
}

// Multi-select state (like Windows Explorer)
const selectedItems = new Set();  // Set of organ IDs (e.g., 'organ_1', 'ctv')
let lastClickedId = null;  // For shift+click range selection

function getSelectableIds() {
    // Return all organ IDs + ctv in tree order
    const ids = [];
    if (dataTreeState.ctv.loaded) ids.push('ctv');
    dataTreeState.organs.forEach(o => ids.push(o.id));
    return ids;
}

// Predefined colors for organs
const ORGAN_COLORS = [
    '#22c55e', '#06b6d4', '#8b5cf6', '#f59e0b', '#ef4444',
    '#ec4899', '#14b8a6', '#f97316', '#6366f1', '#84cc16',
    '#e11d48', '#0ea5e9', '#a855f7', '#eab308', '#10b981',
    '#d946ef', '#0891b2', '#7c3aed', '#ca8a04', '#059669',
];

function updateOrganList(organData, source = '') {
    // organData: {label_id: {name, voxel_count, color?}}
    if (!organData) return;

    // Preserve existing visibility/opacity state
    const existingState = {};
    const sourceChanged = Boolean(source && dataTreeState.oarSource && source !== dataTreeState.oarSource);
    dataTreeState.organs.forEach(o => {
        if (!sourceChanged) {
            existingState[o.id] = { visible: o.visible, opacity: o.opacity, category: o.category, color: o.color };
        }
    });
    if (source) dataTreeState.oarSource = source;

    dataTreeState.organs = [];
    let i = 0;
    for (const [labelId, info] of Object.entries(organData)) {
        const name = info.name || `OAR ${i + 1}`;
        const id = `organ_${labelId}`;
        const existing = existingState[id];
        const cat = existing?.category || classifyOrgan(name);
        dataTreeState.organs.push({
            id: id,
            labelId: parseInt(labelId),
            label: name,
            color: existing?.color || info.color || ORGAN_COLORS[i % ORGAN_COLORS.length],
            // Start all OARs visible — users can toggle individual organs
            // via the data tree.
            visible: existing?.visible ?? true,
            opacity: existing?.opacity ?? 0.5,
            voxelCount: info.voxel_count || 0,
            category: cat,
            source: 'oar',
        });
        i++;
    }
}

// Debounced version to prevent excessive re-renders
let _renderDataTreeTimer = null;
function renderDataTreeDebounced() {
    clearTimeout(_renderDataTreeTimer);
    _renderDataTreeTimer = setTimeout(renderDataTree, 50);
}

function renderDataTree() {
    const body = document.getElementById('dataTreeBody');
    if (!body) return;

    // Check what data is loaded
    dataTreeState.ct.loaded = state.ctLoaded;
    // CTV loaded = CT loaded AND CTV segmentation data exists
    dataTreeState.ctv.loaded = !!state.ctLoaded && !!ctvLabelData && ctvLabelData.length > 0;
    dataTreeState.oar.loaded = dataTreeState.organs.length > 0;
    dataTreeState.dose.loaded = !!(state.metrics && state.metrics.v100 !== undefined);
    dataTreeState.seeds.loaded = !!(state.seeds && state.seeds.length > 0);

    let html = '';

    // === Image group ===
    html += `<div class="tree-group">
        <div class="tree-group-header" onclick="toggleTreeGroup(this)">
            <span class="arrow">&#9660;</span>
            <span>Image</span>
        </div>
        <div class="tree-group-items">`;
    html += renderTreeItem('ct', dataTreeState.ct, state.ctShape ? `${state.ctShape[2]}×${state.ctShape[1]}×${state.ctShape[0]}` : '');
    html += `</div></div>`;

    // === Segmentation group (CTV + OAR parallel) ===
    // Check if CTV has multiple labels
    const ctvLabels = [];
    if (ctvLabelData) {
        const uniqueLabels = new Set(ctvLabelData);
        uniqueLabels.forEach(l => { if (l > 0) ctvLabels.push(l); });
        ctvLabels.sort((a, b) => a - b);
    }
    const hasMultiLabelCtv = ctvLabels.length > 1;

    const hasSeg = dataTreeState.ctv.loaded || dataTreeState.organs.length > 0;
    const segCount = hasMultiLabelCtv ? ctvLabels.length : (dataTreeState.ctv.loaded ? 1 : 0);
    html += `<div class="tree-group">
        <div class="tree-group-header" onclick="toggleTreeGroup(this)">
            <span class="arrow">&#9660;</span>
            <span>Segmentation ${hasSeg ? `(${dataTreeState.organs.length + segCount})` : ''}</span>
        </div>
        <div class="tree-group-items">`;

    // CTV — show as collapsible group with tumor label(s) as children
    if (dataTreeState.ctv.loaded) {
        const tumorTypeUsed = String(state.tumorTypeUsed || '').trim();
        const genericTargetName = tumorTypeUsed && tumorTypeUsed !== 'auto'
            ? `${tumorTypeUsed.replaceAll('_', ' ')} target`
            : 'CTV';
        const labelNames = window._ctvLabelMap || {1: genericTargetName};
        const voxelVolumeCm3 = _ctVoxelVolumeCm3();

        // Tumor labels (label 1) → CTV group
        const tumorLabels = ctvLabels.filter(l => l === 1);
        // Use semantic label names instead of assuming pancreas-specific label
        // numbers. Models for other tumor sites may assign labels 2/3 to
        // completely different structures.
        const nonTravLabels = ctvLabels.filter(labelId => {
            const name = String(labelNames[labelId] || '').toLowerCase();
            return /arter|vein|vessel/.test(name);
        });
        const nonTravSet = new Set(nonTravLabels);
        const otherLabels = ctvLabels.filter(labelId => labelId !== 1 && !nonTravSet.has(labelId));

        // CTV group header (like OAR)
        const ctvVis = dataTreeState.ctv.visible;
        const ctvOp = dataTreeState.ctv.opacity ?? 0.7;
        html += `<div class="tree-group" data-group="ctv">
            <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="event.preventDefault();handleTreeItemRightClick('ctv', event)">
                <span class="arrow">&#9660;</span>
                <button class="eye-btn ${ctvVis ? '' : 'hidden'}" onclick="event.stopPropagation();toggleDataVisibility('ctv')">${ctvVis ? '&#128065;' : '&#128064;'}</button>
                <span>CTV</span>
                <span style="margin-left:auto;display:flex;align-items:center;gap:4px;">
                    <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(ctvOp * 100)}" onclick="event.stopPropagation()" oninput="setGroupOpacity('ctv', this.value)" title="Opacity">
                </span>
            </div>
            <div class="tree-group-items">`;

        // Show tumor label(s) as children under CTV
        if (tumorLabels.length > 0) {
            tumorLabels.forEach(labelId => {
                const count = ctvLabelData ? ctvLabelData.filter(v => v === labelId).length : 0;
                const name = labelNames[labelId] || 'tumor';
                const volumeText = count > 0 && voxelVolumeCm3
                    ? `${(count * voxelVolumeCm3).toFixed(1)} cm³`
                    : '';
                // Tumor color: bright pink (#ff69b4) instead of blue (too close to dose)
                const tumorColor = labelColorLUT[labelId]
                    ? `rgb(${labelColorLUT[labelId].join(',')})`
                    : '#ff69b4';
                html += `<div class="tree-item" data-item="ctv_${labelId}" data-organ-id="ctv_${labelId}"
                    style="display:flex;align-items:center;gap:6px;padding:2px 8px 2px 28px;font-size:0.7rem;"
                    onclick="handleTreeItemClick('ctv_${labelId}', event)"
                    oncontextmenu="event.preventDefault();event.stopPropagation();handleTreeItemRightClick('ctv_${labelId}', event)">
                    <button class="eye-btn" onclick="event.stopPropagation();toggleDataVisibility('ctv')" style="font-size:0.65rem;">&#128065;</button>
                    <span class="color-swatch" style="background:${tumorColor};width:10px;height:10px;border-radius:2px;cursor:pointer;" onclick="event.stopPropagation();openColorPicker('ctv_${labelId}', this)"></span>
                    <span class="item-label">${escHtml(name)}</span>
                    <span style="margin-left:auto;font-size:0.6rem;color:var(--text-dim);">${volumeText}</span>
                    <button class="recon3d-btn" title="3D Reconstruct" onclick="event.stopPropagation();reconstructOrgan3D('ctv_${labelId}')">&#9638;</button>
                    <input type="range" class="opacity-slider" min="0" max="100" value="70"
                        onclick="event.stopPropagation()"
                        oninput="setDataOpacity('ctv_${labelId}', this.value)">
                </div>`;
            });
        } else if (!hasMultiLabelCtv) {
            // Single-label CTV (not from nnUNet multi-label)
            const ctvVolume = state.ctvVolume || null;
            const ctvInfo = ctvVolume ? `${ctvVolume.toFixed(1)} mm³` : '';
            html += `<div class="tree-item" data-item="ctv" style="display:flex;align-items:center;gap:6px;padding:2px 8px 2px 28px;font-size:0.7rem;">
                <button class="eye-btn" onclick="event.stopPropagation();toggleDataVisibility('ctv')" style="font-size:0.65rem;">&#128065;</button>
                <span class="color-swatch" style="background:${dataTreeState.ctv.color};width:10px;height:10px;border-radius:2px;"></span>
                <span>CTV Mask</span>
                <span style="margin-left:auto;font-size:0.6rem;color:var(--text-dim);">${ctvInfo}</span>
            </div>`;
        }

        html += `</div></div>`; // close CTV group

        // Add CTV sub-labels (artery/vein/unknown) to OAR categories
        const ctvSubLabels = [];

        // Non-traversable: artery (2), vein (3)
        nonTravLabels.forEach(labelId => {
            const count = ctvLabelData.filter(v => v === labelId).length;
            const name = labelNames[labelId] || `Label ${labelId}`;
            const color = labelColorLUT[labelId] ? `rgb(${labelColorLUT[labelId].join(',')})` : '#f97316';
            ctvSubLabels.push({
                id: `ctv_${labelId}`,
                labelId: labelId,
                label: name,
                color: color,
                visible: true,
                opacity: 0.5,
                voxelCount: count,
                category: 'non_traversable',
                source: 'ctv',
            });
        });

        // Traversable: unknown labels (4, 5, 6, etc.)
        otherLabels.forEach(labelId => {
            const count = ctvLabelData.filter(v => v === labelId).length;
            const name = labelNames[labelId] || `Label ${labelId}`;
            const color = labelColorLUT[labelId] ? `rgb(${labelColorLUT[labelId].join(',')})` : '#22c55e';
            ctvSubLabels.push({
                id: `ctv_${labelId}`,
                labelId: labelId,
                label: name,
                color: color,
                visible: true,
                opacity: 0.5,
                voxelCount: count,
                category: 'traversable',
                source: 'ctv',
            });
        });

        // Merge CTV sub-labels into organs list (avoid duplicates)
        ctvSubLabels.forEach(sub => {
            if (!dataTreeState.organs.some(o => o.id === sub.id)) {
                dataTreeState.organs.push(sub);
            }
        });
    }

    // OAR with sub-categories
    const nonTrav = dataTreeState.organs.filter(o => o.category === 'non_traversable');
    const trav = dataTreeState.organs.filter(o => o.category === 'traversable');

    // OAR master group
    const oarVis = dataTreeState.organs.some(o => o.visible);
    const oarOp = dataTreeState.organs.length > 0
        ? dataTreeState.organs.reduce((sum, o) => sum + (o.opacity ?? 0.5), 0) / dataTreeState.organs.length
        : 0.5;
    html += `<div class="tree-group" data-group="oar">
        <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="event.preventDefault();handleTreeItemRightClick('oar', event)">
            <span class="arrow">&#9660;</span>
            <button class="eye-btn ${oarVis ? '' : 'hidden'}" onclick="event.stopPropagation();setGroupVisibility('oar', ${!oarVis})" title="Toggle">${oarVis ? '&#128065;' : '&#128064;'}</button>
            <span>OAR (${dataTreeState.organs.length})</span>
            <span style="margin-left:auto;display:flex;align-items:center;gap:4px;">
                <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(oarOp * 100)}" onclick="event.stopPropagation()" oninput="setGroupOpacity('oar', this.value)" title="Opacity">
            </span>
        </div>
        <div class="tree-group-items">`;

    // Non-traversable sub-group
    if (nonTrav.length > 0) {
        const gVis = nonTrav.some(o => o.visible);
        const gOp = nonTrav[0]?.opacity ?? 0.5;
        html += `<div class="tree-group" data-group="non_traversable">
            <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="event.preventDefault();showGroupContextMenu(event.clientX,event.clientY,'non_traversable')">
                <span class="arrow">&#9660;</span>
                <span style="color:rgba(249,115,22,0.7);">&#9679; Non-traversable (${nonTrav.length})</span>
                <span style="margin-left:auto;display:flex;align-items:center;gap:4px;">
                    <button class="eye-btn ${gVis ? '' : 'hidden'}" onclick="event.stopPropagation();setGroupVisibility('non_traversable', ${!gVis})" title="Toggle">${gVis ? '&#128065;' : '&#128064;'}</button>
                    <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(gOp * 100)}" onclick="event.stopPropagation()" oninput="setGroupOpacity('non_traversable', this.value)" title="Opacity">
                </span>
            </div>
            <div class="tree-group-items">`;
        for (const organ of nonTrav) {
            const organState = { visible: organ.visible, opacity: organ.opacity, color: organ.color, loaded: true, label: organ.label };
            const voxelVolume = _ctVoxelVolumeCm3();
            const info = organ.voxelCount > 0 && voxelVolume ? `${(organ.voxelCount * voxelVolume).toFixed(1)} cm³` : '';
            html += renderTreeItem(organ.id, organState, info);
        }
        html += `</div></div>`;
    }

    if (trav.length > 0) {
        const gVis = trav.some(o => o.visible);
        const gOp = trav[0]?.opacity ?? 0.5;
        html += `<div class="tree-group" data-group="traversable">
            <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="event.preventDefault();showGroupContextMenu(event.clientX,event.clientY,'traversable')">
                <span class="arrow">&#9660;</span>
                <span style="color:rgba(34,197,94,0.7);">&#9679; Traversable (${trav.length})</span>
                <span style="margin-left:auto;display:flex;align-items:center;gap:4px;">
                    <button class="eye-btn ${gVis ? '' : 'hidden'}" onclick="event.stopPropagation();setGroupVisibility('traversable', ${!gVis})" title="Toggle">${gVis ? '&#128065;' : '&#128064;'}</button>
                    <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(gOp * 100)}" onclick="event.stopPropagation()" oninput="setGroupOpacity('traversable', this.value)" title="Opacity">
                </span>
            </div>
            <div class="tree-group-items">`;
        for (const organ of trav) {
            const organState = { visible: organ.visible, opacity: organ.opacity, color: organ.color, loaded: true, label: organ.label };
            const voxelVolume = _ctVoxelVolumeCm3();
            const info = organ.voxelCount > 0 && voxelVolume ? `${(organ.voxelCount * voxelVolume).toFixed(1)} cm³` : '';
            html += renderTreeItem(organ.id, organState, info);
        }
        html += `</div></div>`;
    }

    html += `</div></div>`; // close OAR group
    html += `</div></div>`; // close Segmentation group

    // === Planning group (Seeds, Needles, Dose) ===
    const planningTrajectories = _planningItems('trajectories');
    const planningSeeds = _planningItems('seeds');
    const planningNeedles = _planningItems('needles');
    const doseLevels = _planningItems('doseLevels');
    const planningMeshes = _planningItems('meshes');
    const hasDoseOverlay = !!(state.doseOverlay && state.doseOverlay.shape);
    const hasPlanning = planningTrajectories.length > 0 || planningSeeds.length > 0 || planningNeedles.length > 0 || doseLevels.length > 0 || planningMeshes.length > 0 || hasDoseOverlay;
    const planningEntries = _planningVisualEntries();
    const planningVis = planningEntries.length === 0 || planningEntries.some(item => item.visible !== false);
    const planningOp = planningEntries.length
        ? planningEntries.reduce((sum, item) => sum + Number(item.opacity ?? 0.7), 0) / planningEntries.length
        : 0.7;

    html += `<div class="tree-group" data-group="planning">
        <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="event.preventDefault();showGroupContextMenu(event.clientX,event.clientY,'planning')">
            <span class="arrow">&#9660;</span>
            <button class="eye-btn ${planningVis ? '' : 'hidden'}" onclick="event.stopPropagation();setGroupVisibility('planning', ${!planningVis})" title="Toggle all planning objects">${planningVis ? '&#128065;' : '&#128064;'}</button>
            <span>Planning ${hasPlanning ? `(${planningEntries.length})` : ''}</span>
            <span style="margin-left:auto;display:flex;align-items:center;gap:4px;">
                <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(planningOp * 100)}" onclick="event.stopPropagation()" oninput="setGroupOpacity('planning', this.value)" title="Opacity for all planning objects">
            </span>
        </div>
        <div class="tree-group-items">`;

    // Trajectories group (parent of seeds) — only shown when the
    // server returned the new "trajectories" array. Without it, fall
    // back to the flat seeds list below.
    if (planningTrajectories.length > 0) {
        const trajVis = planningTrajectories.some(t => t.visible);
        const trajOp = planningTrajectories[0]?.opacity ?? 0.8;
        html += `<div class="tree-group" data-group="planning_trajectories">
            <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="event.preventDefault();handleTreeItemRightClick('planning_trajectories', event)">
                <span class="arrow">&#9660;</span>
                <button class="eye-btn ${trajVis ? '' : 'hidden'}" onclick="event.stopPropagation();setGroupVisibility('planning_trajectories', ${!trajVis})" title="Toggle">${trajVis ? '&#128065;' : '&#128064;'}</button>
                <span>Trajectories (${planningTrajectories.length})</span>
                <span style="margin-left:auto;display:flex;align-items:center;gap:4px;">
                    <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(trajOp * 100)}" onclick="event.stopPropagation()" oninput="setGroupOpacity('planning_trajectories', this.value)" title="Opacity">
                </span>
            </div>
            <div class="tree-group-items">`;
        planningTrajectories.forEach(traj => {
            const trajId = traj.id;
            const trajState = { visible: traj.visible, opacity: traj.opacity, color: traj.color, loaded: true, label: `Trajectory ${traj.index + 1}` };
            const childSeeds = traj.seeds || [];
            const childHeader = childSeeds.length > 0 ? ` (${childSeeds.length} seeds)` : '';
            html += `<div class="tree-group" data-group="${trajId}">
                <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="event.preventDefault();handleTreeItemRightClick('${trajId}', event)" style="padding-left:1.2rem;">
                    <span class="arrow">&#9660;</span>
                    <button class="eye-btn ${traj.visible ? '' : 'hidden'}" onclick="event.stopPropagation();toggleDataVisibility('${trajId}')">${traj.visible ? '&#128065;' : '&#128064;'}</button>
                    <span style="color:#88ccff;">➤</span>
                    <span>Trajectory ${traj.index + 1}${childHeader}</span>
                </div>
                <div class="tree-group-items">`;
            childSeeds.forEach(seed => {
                const seedState = { visible: seed.visible !== false, opacity: seed.opacity ?? 1.0, color: seed.color || '#ffcc00', loaded: true, label: `Seed ${seed.id.split('_').slice(-1)[0]}` };
                html += renderTreeItem(seed.id, seedState, '');
            });
            html += `</div></div>`; // close trajectory sub-group
        });
        html += `</div></div>`; // close trajectories group
    } else if (planningSeeds.length > 0) {
        // Fallback: flat seeds list (server didn't return trajectories)
        const seedsVis = planningSeeds.some(s => s.visible);
        const seedsOp = planningSeeds[0]?.opacity ?? 1.0;
        html += `<div class="tree-group" data-group="planning_seeds">
            <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="event.preventDefault();handleTreeItemRightClick('planning_seeds', event)">
                <span class="arrow">&#9660;</span>
                <button class="eye-btn ${seedsVis ? '' : 'hidden'}" onclick="event.stopPropagation();setGroupVisibility('planning_seeds', ${!seedsVis})" title="Toggle">${seedsVis ? '&#128065;' : '&#128064;'}</button>
                <span>Seeds (${planningSeeds.length})</span>
                <span style="margin-left:auto;display:flex;align-items:center;gap:4px;">
                    <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(seedsOp * 100)}" onclick="event.stopPropagation()" oninput="setGroupOpacity('planning_seeds', this.value)" title="Opacity">
                </span>
            </div>
            <div class="tree-group-items">`;
        planningSeeds.forEach(seed => {
            const seedState = { visible: seed.visible, opacity: seed.opacity, color: seed.color, loaded: true, label: `Seed ${seed.id}` };
            html += renderTreeItem(seed.id, seedState, `Traj ${seed.trajectory_id}`);
        });
        html += `</div></div>`;
    }

    // Needles group
    if (planningNeedles.length > 0) {
        const needlesVis = planningNeedles.some(n => n.visible);
        const needlesOp = planningNeedles[0]?.opacity ?? 0.8;
        html += `<div class="tree-group" data-group="planning_needles">
            <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="event.preventDefault();handleTreeItemRightClick('planning_needles', event)">
                <span class="arrow">&#9660;</span>
                <button class="eye-btn ${needlesVis ? '' : 'hidden'}" onclick="event.stopPropagation();setGroupVisibility('planning_needles', ${!needlesVis})" title="Toggle">${needlesVis ? '&#128065;' : '&#128064;'}</button>
                <span>Needles (${planningNeedles.length})</span>
                <span style="margin-left:auto;display:flex;align-items:center;gap:4px;">
                    <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(needlesOp * 100)}" onclick="event.stopPropagation()" oninput="setGroupOpacity('planning_needles', this.value)" title="Opacity">
                </span>
            </div>
            <div class="tree-group-items">`;
        planningNeedles.forEach(needle => {
            const needleState = { visible: needle.visible, opacity: needle.opacity, color: needle.color, loaded: true, label: `Needle ${needle.id}` };
            html += renderTreeItem(needle.id, needleState, `${needle.points.length} pts`);
        });
        html += `</div></div>`;
    }

    // Dose isosurfaces group
    if (doseLevels.length > 0) {
        const doseVis = doseLevels.some(d => d.visible);
        const doseOp = doseLevels[0]?.opacity ?? 0.3;
        html += `<div class="tree-group" data-group="dose_isosurfaces">
            <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="event.preventDefault();handleTreeItemRightClick('dose_isosurfaces', event)">
                <span class="arrow">&#9660;</span>
                <button class="eye-btn ${doseVis ? '' : 'hidden'}" onclick="event.stopPropagation();setGroupVisibility('dose_isosurfaces', ${!doseVis})" title="Toggle">${doseVis ? '&#128065;' : '&#128064;'}</button>
                <span>Dose Isosurfaces (${doseLevels.length})</span>
                <span style="margin-left:auto;display:flex;align-items:center;gap:4px;">
                    <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(doseOp * 100)}" onclick="event.stopPropagation()" oninput="setGroupOpacity('dose_isosurfaces', this.value)" title="Opacity">
                </span>
            </div>
            <div class="tree-group-items">`;
        doseLevels.forEach(level => {
            // 2026-06-16 fix: `threshold` is now stored in ABSOLUTE Gy
            // (previously it was a relative multiplier × prescription,
            // so the label was wrong after the user's Rx changed).
            // Show "120 Gy" not "1.0× Rx".
            const absGy = (level.thresholdGy != null)
                ? level.thresholdGy
                : Math.round(level.threshold);
            const levelState = { visible: level.visible, opacity: level.opacity, color: level.color, loaded: true, label: `${absGy} Gy` };
            const pctLabel = level.pctLabel || `${absGy} Gy`;
            html += renderTreeItem(`dose_iso_${level.threshold}`, levelState, pctLabel);
        });
        html += `</div></div>`;
    }

    // Dose overlay toggle (2D overlay on CT slices)
    if (state.doseOverlay && state.doseOverlay.shape) {
        const ovVis = state.doseOverlay.visible;
        const ovOp = state.doseOverlay.opacity;
        html += `<div class="tree-item" data-item="dose_overlay" style="display:flex;align-items:center;gap:6px;padding:2px 8px;font-size:0.7rem;">
            <button class="eye-btn ${ovVis ? '' : 'hidden'}" onclick="event.stopPropagation();toggleDoseOverlayVisibility()" style="font-size:0.65rem;">${ovVis ? '&#128065;' : '&#128064;'}</button>
            <span style="color:#22d3ee;">◉</span>
            <span>Dose Overlay (2D)</span>
            <span style="margin-left:auto;font-size:0.6rem;color:var(--text-dim);">max: ${state.doseOverlay.doseMax?.toFixed(1) || '--'}</span>
            <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(ovOp * 100)}" onclick="event.stopPropagation()" oninput="setDoseOverlayOpacity(this.value)" title="Opacity">
        </div>`;
    }

    // BUG FIX 2026-06-16 (data tree 3D meshes): removed the
    // redundant "3D Meshes (N)" parent group. The user complained
    // that this group duplicated entries that already live under
    // their source (CTV / OAR / Dose), and that each item already
    // has a per-row "3D Reconstruct" button (renderTreeItem at
    // line ~10994) which they want to use instead of a separate
    // toggle group. Now meshes only appear as a "Meshes" sub-row
    // under their source — no duplicate parent group.
    //
    // We no longer emit a `3D Meshes` tree-group at all here; the
    // meshes are still rendered as items via renderTreeItem under
    // their owning source (CTV, OAR, dose iso-surface).

    // Legacy dose/seed items (if no planning data)
    if (!hasPlanning) {
        html += renderTreeItem('dose', dataTreeState.dose, state.metrics && state.metrics.v100 !== undefined ? `V100: ${(state.metrics.v100 * 100).toFixed(1)}%` : '');
        html += renderTreeItem('seeds', dataTreeState.seeds, state.seeds ? `${state.seeds.length} seeds` : '');
    }

    html += `</div></div>`; // close Planning group

    body.innerHTML = html;
    requestViewerVisualRefresh('data-tree-render');
}

function renderTreeItem(id, itemState, info) {
    const eyeIcon = itemState.visible ? '&#128065;' : '&#128064;';
    const eyeClass = itemState.visible ? '' : 'hidden';
    const loadedClass = itemState.loaded ? '' : 'style="opacity:0.4;"';
    const disabledAttr = itemState.loaded ? '' : 'disabled';
    // Indent for sub-items: organs, CTV labels, planning items
    const isSubItem = id.startsWith('organ_') || id.startsWith('ctv_') || id.startsWith('seed_') || id.startsWith('needle_') || id.startsWith('dose_iso_');
    const indent = isSubItem ? 'style="padding-left:1.6rem;"' : '';
    // 3D button for organs, CTV, CTV sub-labels, and planning items
    const canRecon3d = id === 'ctv' || id.startsWith('organ_') || id.startsWith('ctv_') || id.startsWith('seed_') || id.startsWith('needle_');
    const recon3dBtn = canRecon3d ? `<button class="recon3d-btn" title="3D Reconstruct" onclick="event.stopPropagation();reconstructOrgan3D('${id}')">&#9638;</button>` : '';

    const dataAttr = (id === 'ctv' || id.startsWith('organ_') || id.startsWith('ctv_')) ? `data-organ-id="${id}"` : '';
    const selectedClass = selectedItems.has(id) ? 'selected' : '';

    return `<div class="tree-item ${selectedClass}" ${loadedClass} ${indent} ${dataAttr}
        onclick="handleTreeItemClick('${id}', event)"
        oncontextmenu="event.preventDefault();event.stopPropagation();handleTreeItemRightClick('${id}', event)">
        <button class="eye-btn ${eyeClass}" onclick="event.stopPropagation();toggleDataVisibility('${id}')" ${disabledAttr}>${eyeIcon}</button>
        <span class="color-swatch" style="background:${itemState.color};" onclick="event.stopPropagation();openColorPicker('${id}', this)" title="Click to change color"></span>
        <span class="item-label">${escHtml(itemState.label || '')}</span>
        <span class="item-info">${escHtml(info || '')}</span>
        ${recon3dBtn}
        <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(itemState.opacity * 100)}"
            ${disabledAttr}
            onclick="event.stopPropagation()"
            oninput="setDataOpacity('${id}', this.value)">
    </div>`;
}

// Qt-style color dialog
function openColorPicker(id, swatchEl) {
    // Get current color
    let itemState;
    if (id === 'ctv') itemState = dataTreeState.ctv;
    else if (id === 'oar') itemState = dataTreeState.oar;
    else if (id === 'dose') itemState = dataTreeState.dose;
    else if (id === 'seeds') itemState = dataTreeState.seeds;
    else if (id === 'needles') itemState = dataTreeState.needles;
    else if (id.startsWith('ctv_')) {
        // CTV sub-labels (tumor, artery, vein, pancreas, etc.)
        if (!dataTreeState.ctvLabels) dataTreeState.ctvLabels = {};
        if (!dataTreeState.ctvLabels[id]) dataTreeState.ctvLabels[id] = { visible: true, opacity: 0.7, color: '#ef4444' };
        itemState = dataTreeState.ctvLabels[id];
    } else if (id.startsWith('seed_')) {
        itemState = dataTreeState.planning.seeds.find(s => s.id === id);
    } else if (id.startsWith('needle_')) {
        itemState = dataTreeState.planning.needles.find(n => n.id === id);
    } else if (id.startsWith('dose_iso_')) {
        const threshold = parseFloat(id.replace('dose_iso_', ''));
        itemState = dataTreeState.planning.doseLevels.find(d => d.threshold === threshold);
    } else {
        const organ = dataTreeState.organs.find(o => o.id === id);
        if (organ) itemState = organ;
    }
    if (!itemState) return;

    // Remove existing dialog if any
    const existing = document.getElementById('colorDialog');
    if (existing) existing.remove();

    const currentColor = itemState.color || '#888888';

    // Create dialog
    const dialog = document.createElement('div');
    dialog.id = 'colorDialog';
    dialog.style.cssText = `
        position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
        z-index: 10000; background: var(--bg-2); border: 1px solid var(--card-border);
        border-radius: 12px; padding: 16px; box-shadow: 0 20px 60px rgba(0,0,0,0.5);
        min-width: 280px; font-size: 0.75rem;
    `;

    // Convert hex to HSV
    function hexToHSV(hex) {
        let r = parseInt(hex.slice(1,3), 16) / 255;
        let g = parseInt(hex.slice(3,5), 16) / 255;
        let b = parseInt(hex.slice(5,7), 16) / 255;
        let max = Math.max(r, g, b), min = Math.min(r, g, b);
        let h, s, v = max;
        let d = max - min;
        s = max === 0 ? 0 : d / max;
        if (max === min) h = 0;
        else {
            switch (max) {
                case r: h = (g - b) / d + (g < b ? 6 : 0); break;
                case g: h = (b - r) / d + 2; break;
                case b: h = (r - g) / d + 4; break;
            }
            h /= 6;
        }
        return [h * 360, s * 100, v * 100];
    }

    function hsvToHex(h, s, v) {
        h /= 360; s /= 100; v /= 100;
        let r, g, b;
        let i = Math.floor(h * 6);
        let f = h * 6 - i;
        let p = v * (1 - s);
        let q = v * (1 - f * s);
        let t = v * (1 - (1 - f) * s);
        switch (i % 6) {
            case 0: r = v; g = t; b = p; break;
            case 1: r = q; g = v; b = p; break;
            case 2: r = p; g = v; b = t; break;
            case 3: r = p; g = q; b = v; break;
            case 4: r = t; g = p; b = v; break;
            case 5: r = v; g = p; b = q; break;
        }
        return '#' + [r, g, b].map(x => Math.round(x * 255).toString(16).padStart(2, '0')).join('');
    }

    let [h, s, v] = hexToHSV(currentColor);

    dialog.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
            <span style="font-weight:600;color:var(--text);">Color Picker</span>
            <span id="colorDialogClose" style="cursor:pointer;font-size:1rem;color:var(--text-dim);">✕</span>
        </div>
        <div id="colorPreview" style="width:100%;height:40px;border-radius:8px;margin-bottom:12px;border:1px solid var(--card-border);background:${currentColor};"></div>
        <div style="margin-bottom:8px;">
            <label style="color:var(--text-dim);font-size:0.65rem;">Hue</label>
            <input type="range" id="colorH" min="0" max="360" value="${h}" style="width:100%;accent-color:#ff4444;">
        </div>
        <div style="margin-bottom:8px;">
            <label style="color:var(--text-dim);font-size:0.65rem;">Saturation</label>
            <input type="range" id="colorS" min="0" max="100" value="${s}" style="width:100%;accent-color:#4488ff;">
        </div>
        <div style="margin-bottom:8px;">
            <label style="color:var(--text-dim);font-size:0.65rem;">Value</label>
            <input type="range" id="colorV" min="0" max="100" value="${v}" style="width:100%;accent-color:#44dd44;">
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px;">
            ${['#ff4444','#ff8800','#ffcc00','#44dd44','#4488ff','#8844ff','#ff44aa','#ffffff','#888888','#000000'].map(c =>
                `<div class="color-preset" data-color="${c}" style="width:24px;height:24px;border-radius:6px;background:${c};cursor:pointer;border:2px solid transparent;"></div>`
            ).join('')}
        </div>
        <div style="display:flex;justify-content:flex-end;gap:8px;">
            <button id="colorCancel" style="padding:6px 16px;border-radius:6px;border:1px solid var(--card-border);background:var(--bg-3);color:var(--text);cursor:pointer;font-size:0.7rem;">Cancel</button>
            <button id="colorApply" style="padding:6px 16px;border-radius:6px;border:none;background:var(--primary);color:white;cursor:pointer;font-size:0.7rem;">Apply</button>
        </div>
    `;

    document.body.appendChild(dialog);

    // Backdrop
    const backdrop = document.createElement('div');
    backdrop.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.3);';
    backdrop.id = 'colorBackdrop';
    document.body.appendChild(backdrop);

    const preview = dialog.querySelector('#colorPreview');
    const hSlider = dialog.querySelector('#colorH');
    const sSlider = dialog.querySelector('#colorS');
    const vSlider = dialog.querySelector('#colorV');

    let pendingColor = currentColor;

    function updateFromSliders() {
        pendingColor = hsvToHex(parseFloat(hSlider.value), parseFloat(sSlider.value), parseFloat(vSlider.value));
        preview.style.background = pendingColor;
    }

    hSlider.addEventListener('input', updateFromSliders);
    sSlider.addEventListener('input', updateFromSliders);
    vSlider.addEventListener('input', updateFromSliders);

    // Preset colors
    dialog.querySelectorAll('.color-preset').forEach(el => {
        el.addEventListener('click', () => {
            pendingColor = el.dataset.color;
            [h, s, v] = hexToHSV(pendingColor);
            hSlider.value = h; sSlider.value = s; vSlider.value = v;
            preview.style.background = pendingColor;
        });
    });

    function applyColor() {
        itemState.color = pendingColor;
        if (swatchEl) swatchEl.style.background = pendingColor;
        // Update labelColorLUT
        if (id.startsWith('organ_')) {
            const organ = dataTreeState.organs.find(o => o.id === id);
            if (organ && organ.labelId !== undefined) {
                const r = parseInt(pendingColor.slice(1,3), 16);
                const g = parseInt(pendingColor.slice(3,5), 16);
                const b = parseInt(pendingColor.slice(5,7), 16);
                labelColorLUT[organ.labelId] = [r, g, b];
            }
        }
        if (id.startsWith('ctv_')) {
            const labelId = parseInt(id.replace('ctv_', ''));
            const r = parseInt(pendingColor.slice(1,3), 16);
            const g = parseInt(pendingColor.slice(3,5), 16);
            const b = parseInt(pendingColor.slice(5,7), 16);
            labelColorLUT[labelId] = [r, g, b];
        }
        if (id.startsWith('dose_iso_')) {
            const threshold = parseFloat(id.replace('dose_iso_', ''));
            const doseLevel = dataTreeState.planning?.doseLevels?.find(level => Math.abs(Number(level.threshold) - threshold) < 1e-6);
            if (doseLevel) doseLevel.color = pendingColor;
        }
        // Update 3D mesh color if mesh exists
        const mesh3d = scene3D.meshes[id];
        if (mesh3d) {
            _setMeshMaterialColor(mesh3d, pendingColor);
            // Dose texture owns the active material, so update the saved
            // normal material too.  Otherwise changing color during dose
            // mode would be lost as soon as Normal Surface is restored.
            const savedMaterial = state.doseTexture?.originalMaterials?.[id];
            if (savedMaterial) {
                const saved = { material: savedMaterial };
                _setMeshMaterialColor(saved, pendingColor);
            }
        }
        // Redraw overlays (debounced)
        clearTimeout(window._colorOverlayTimer);
        window._colorOverlayTimer = setTimeout(() => {
            if (state.ctLoaded) reloadOverlays();
            redrawSeedNeedleOverlays();
            ['axial', 'sagittal', 'coronal'].forEach(axis => {
                const canvas = document.getElementById('contourCanvas' + capitalize(axis));
                if (canvas && typeof renderDoseContourOnCanvas === 'function') {
                    renderDoseContourOnCanvas(canvas, axis, state.slices?.[axis]);
                }
            });
            renderDataTreeDebounced();
        }, 100);
        closeDialog();
    }

    function closeDialog() {
        dialog.remove();
        backdrop.remove();
    }

    dialog.querySelector('#colorApply').addEventListener('click', applyColor);
    dialog.querySelector('#colorCancel').addEventListener('click', closeDialog);
    dialog.querySelector('#colorDialogClose').addEventListener('click', closeDialog);
    backdrop.addEventListener('click', closeDialog);
}

function getItemGroup(id) {
    if (id === 'ctv') return 'ctv';
    const organ = dataTreeState.organs.find(o => o.id === id);
    return organ ? organ.category : 'other';
}

function handleTreeItemClick(id, event) {
    if (event.shiftKey && lastClickedId) {
        // Shift+click: range select within the SAME group only
        const group = getItemGroup(id);
        const selectableIds = getSelectableIds().filter(i => getItemGroup(i) === group);
        const startIdx = selectableIds.indexOf(lastClickedId);
        const endIdx = selectableIds.indexOf(id);
        if (startIdx >= 0 && endIdx >= 0) {
            const lo = Math.min(startIdx, endIdx);
            const hi = Math.max(startIdx, endIdx);
            if (!event.ctrlKey) selectedItems.clear();
            for (let i = lo; i <= hi; i++) selectedItems.add(selectableIds[i]);
        }
    } else if (event.ctrlKey || event.metaKey) {
        // Ctrl+click: toggle individual
        if (selectedItems.has(id)) selectedItems.delete(id);
        else selectedItems.add(id);
    } else {
        // Normal click: single select
        selectedItems.clear();
        selectedItems.add(id);
    }
    lastClickedId = id;
    renderDataTree();
}

function handleTreeItemRightClick(id, event) {
    event.preventDefault();
    event.stopPropagation();
    // Group headers must open the group menu directly. Routing a group id
    // through the item menu leaves no selected organ and appears unresponsive.
    const groupIds = new Set([
        'ctv', 'oar', 'non_traversable', 'traversable',
        'planning', 'planning_trajectories', 'planning_seeds',
        'planning_needles', 'dose_isosurfaces', 'planning_meshes',
    ]);
    if (groupIds.has(id)) {
        selectedItems.clear();
        showGroupContextMenu(event.clientX, event.clientY, id);
        return;
    }
    // If right-clicking an unselected item, select only it
    if (!selectedItems.has(id)) {
        selectedItems.clear();
        selectedItems.add(id);
        lastClickedId = id;
    }
    // Show menu immediately
    showContextMenu(event.clientX, event.clientY);
}

function showGroupContextMenu(x, y, category) {
    hideContextMenu();

    // Determine group info based on category
    let catInfo, count;
    if (category === 'ctv') {
        catInfo = { label: 'CTV', icon: '🎯' };
        count = dataTreeState.ctv.loaded ? 1 : 0;
    } else if (category === 'oar') {
        catInfo = { label: 'All OARs', icon: '🏥' };
        count = dataTreeState.organs.length;
    } else if (category === 'planning_seeds') {
        catInfo = { label: 'Planning Seeds', icon: '💊' };
        count = dataTreeState.planning.seeds.length;
    } else if (category === 'planning_needles') {
        catInfo = { label: 'Planning Needles', icon: '📍' };
        count = dataTreeState.planning.needles.length;
    } else if (category === 'dose_isosurfaces') {
        catInfo = { label: 'Dose Isosurfaces', icon: '🌈' };
        count = dataTreeState.planning.doseLevels.length;
    } else if (category === 'planning_meshes') {
        catInfo = { label: 'Planning Meshes', icon: '▣' };
        count = (dataTreeState.planning.meshes || []).length;
    } else if (category === 'planning' || category === 'planning_trajectories') {
        catInfo = { label: category === 'planning' ? 'Planning' : 'Trajectories', icon: 'P' };
        count = category === 'planning' ? _planningVisualEntries().length : dataTreeState.planning.trajectories.length;
    } else {
        catInfo = ORGAN_CATEGORIES[category] || { label: category, icon: '📁' };
        count = dataTreeState.organs.filter(o => o.category === category).length;
    }

    const menu = document.createElement('div');
    menu.className = 'ctx-menu';
    menu.id = 'ctxMenu';
    menu.style.left = x + 'px';
    menu.style.top = y + 'px';

    let items = `<div class="ctx-menu-item" style="opacity:0.5;cursor:default;font-size:0.6rem;">
        <span class="ctx-icon">${catInfo.icon}</span> ${catInfo.label} (${count})</div>`;
    items += `<div class="ctx-menu-sep"></div>`;

    // 3D Reconstruct all in group (only for OAR/organ groups)
    if (category === 'oar' || (ORGAN_CATEGORIES[category] && category !== 'ctv')) {
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();groupReconstruct3D('${category}')">
            <span class="ctx-icon">&#9638;</span> 3D Reconstruct All (${count})</div>`;
        items += `<div class="ctx-menu-sep"></div>`;
    }
    if (category === 'dose_isosurfaces') {
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();reconstructDoseIsosurfaces3D()">
            <span class="ctx-icon">&#9638;</span> 3D Reconstruct All (${count})</div>`;
        items += `<div class="ctx-menu-sep"></div>`;
    }

    // Visibility
    items += `<div class="ctx-menu-item" onclick="hideContextMenu();setGroupVisibility('${category}',true)">
        <span class="ctx-icon">&#128065;</span> Show All</div>`;
    items += `<div class="ctx-menu-item" onclick="hideContextMenu();setGroupVisibility('${category}',false)">
        <span class="ctx-icon">&#128064;</span> Hide All</div>`;

    // Solo this group (only for organ groups)
    if (category === 'oar' || (ORGAN_CATEGORIES[category] && category !== 'ctv')) {
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();soloGroup('${category}')">
            <span class="ctx-icon">&#128269;</span> Solo This Group</div>`;
    }

    // Clear planning visualization (only for planning groups)
    if (category === 'planning' || category === 'planning_trajectories' || category === 'planning_seeds' || category === 'planning_needles' || category === 'dose_isosurfaces' || category === 'planning_meshes') {
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();clearPlanningVisualization()">
            <span class="ctx-icon">&#128465;</span> Clear Planning</div>`;
    }

    // Opacity submenu
    items += `<div class="ctx-menu-sep"></div>`;
    items += `<div class="ctx-menu-item" style="opacity:0.5;cursor:default;font-size:0.6rem;">
        <span class="ctx-icon">&#127912;</span> Opacity</div>`;
    for (const op of [100, 75, 50, 25]) {
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();setGroupOpacityValue('${category}', ${op})">
            <span class="ctx-icon" style="opacity:${op / 100}">&#9632;</span> ${op}%</div>`;
    }

    items += `<div class="ctx-menu-sep"></div>`;
    items += `<div class="ctx-menu-item" onclick="hideContextMenu();showAllOrgans()">
        <span class="ctx-icon">&#128065;</span> Show All Organs</div>`;

    menu.innerHTML = items;
    document.body.appendChild(menu);

    const rect = menu.getBoundingClientRect();
    if (rect.right > window.innerWidth) menu.style.left = (x - rect.width) + 'px';
    if (rect.bottom > window.innerHeight) menu.style.top = (y - rect.height) + 'px';

    setTimeout(() => {
        document.addEventListener('click', hideContextMenu, { once: true });
        document.addEventListener('contextmenu', hideContextMenu, { once: true });
    }, 0);
    activeContextMenu = menu;
}

function soloGroup(category) {
    dataTreeState.organs.forEach(o => { o.visible = (o.category === category); });
    dataTreeState.ctv.visible = (category === 'ctv');
    _planningItems('seeds').forEach(s => { s.visible = (category === 'planning_seeds'); });
    _planningItems('needles').forEach(n => { n.visible = (category === 'planning_needles'); });
    _planningItems('doseLevels').forEach(d => { d.visible = (category === 'dose_isosurfaces'); });
    // Update 3D meshes
    Object.entries(scene3D.meshes).forEach(([id, mesh]) => {
        if (id.startsWith('seed_')) {
            const s = dataTreeState.planning.seeds.find(s => s.id === id);
            applyMeshVisibility(mesh, s?.visible ?? false, s?.opacity ?? 1.0);
        }
        else if (id.startsWith('needle_')) {
            const n = dataTreeState.planning.needles.find(n => n.id === id);
            applyMeshVisibility(mesh, n?.visible ?? false, n?.opacity ?? 0.8);
        }
        else if (id.startsWith('dose_iso_')) {
            const threshold = parseFloat(id.replace('dose_iso_', ''));
            const d = dataTreeState.planning.doseLevels.find(d => d.threshold === threshold);
            applyMeshVisibility(mesh, d?.visible ?? false, d?.opacity ?? 0.3);
        }
    });
    renderDataTree();
    if (state.ctLoaded) loadAllSlices();
}

async function groupReconstruct3D(category) {
    // A manually uploaded mask can arrive before the label-volume request
    // populates the client tree. Hydrate the authoritative list first rather
    // than treating an empty list as a successful no-op.
    if (!Array.isArray(dataTreeState.organs) || dataTreeState.organs.length === 0) {
        try {
            const response = await fetch(API + '/viewer/organs');
            if (response.ok) {
                const payload = await response.json();
                if (payload.organs) updateOrganList(payload.organs, payload.oar_source || '');
            }
        } catch (error) {
            console.warn('[viewer] OAR metadata hydration failed', error);
        }
    }
    const organs = category === 'oar'
        ? dataTreeState.organs
        : dataTreeState.organs.filter(o => o.category === category);
    if (!organs.length) {
        addChat('error', 'No OAR labels are available for 3D reconstruction');
        return { success: false, reconstructed: 0, total: 0 };
    }
    const results = await Promise.allSettled(organs.map(organ => reconstructOrgan3D(organ.id, true)));
    return {
        success: results.some(result => result.status === 'fulfilled'),
        reconstructed: results.filter(result => result.status === 'fulfilled').length,
        total: organs.length,
    };
}

function getSelectedOrganIds() {
    // Return selected IDs that are organs, CTV, OAR group, planning items, or sub-labels
    return [...selectedItems].filter(id =>
        id === 'ctv' || id === 'oar' || id === 'needles' ||
        id.startsWith('organ_') || id.startsWith('ctv_') ||
        id.startsWith('seed_') || id.startsWith('needle_') || id.startsWith('dose_iso_') ||
        id === 'planning_seeds' || id === 'planning_needles' || id === 'dose_isosurfaces'
    );
}

function showContextMenu(x, y) {
    hideContextMenu();

    const selIds = getSelectedOrganIds();
    if (selIds.length === 0) return;

    // Handle group selections - show group context menu
    if (selIds.includes('oar')) {
        showGroupContextMenu(x, y, 'oar');
        return;
    }
    if (selIds.includes('planning_seeds')) {
        showGroupContextMenu(x, y, 'planning_seeds');
        return;
    }
    if (selIds.includes('planning_needles')) {
        showGroupContextMenu(x, y, 'planning_needles');
        return;
    }
    if (selIds.includes('dose_isosurfaces')) {
        showGroupContextMenu(x, y, 'dose_isosurfaces');
        return;
    }

    const isSingle = selIds.length === 1;
    const firstId = selIds[0];
    const isCTVOnly = selIds.every(id => id === 'ctv' || id.startsWith('ctv_'));
    const hasOrgans = selIds.some(id => id.startsWith('organ_'));
    const isPlanningItem = firstId.startsWith('seed_') || firstId.startsWith('needle_') || firstId.startsWith('dose_iso_');

    const menu = document.createElement('div');
    menu.className = 'ctx-menu';
    menu.id = 'ctxMenu';
    menu.style.left = x + 'px';
    menu.style.top = y + 'px';

    let items = '';

    // Selection info
    if (!isSingle) {
        items += `<div class="ctx-menu-item" style="opacity:0.5;cursor:default;font-size:0.6rem;">
            <span class="ctx-icon">&#9745;</span> ${selIds.length} items selected</div>`;
        items += `<div class="ctx-menu-sep"></div>`;
    }

    // 3D Reconstruct (only for organs/CTV; dose iso reconstruction is
    // explicit because dose surfaces are intentionally not built by default)
    if (!isPlanningItem) {
        if (isSingle) {
            items += `<div class="ctx-menu-item" onclick="hideContextMenu();reconstructOrgan3D('${firstId}')">
                <span class="ctx-icon">&#9638;</span> 3D Reconstruct</div>`;
        } else {
            items += `<div class="ctx-menu-item" onclick="hideContextMenu();batchReconstruct3D()">
                <span class="ctx-icon">&#9638;</span> 3D Reconstruct All (${selIds.length})</div>`;
        }
        items += `<div class="ctx-menu-sep"></div>`;
    }
    if (isSingle && firstId.startsWith('dose_iso_')) {
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();reconstructDoseIsosurface3D('${firstId}')">
            <span class="ctx-icon">&#9638;</span> 3D Reconstruct</div>`;
        items += `<div class="ctx-menu-sep"></div>`;
    }

    if (isSingle && firstId.startsWith('needle_')) {
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();restoreNeedleToAlgorithm('${firstId}')">
            <span class="ctx-icon">&#8634;</span> Restore algorithm position</div>`;
        items += `<div class="ctx-menu-sep"></div>`;
    }

    // Change Color (for single item: organs, CTV labels, or planning items)
    if (isSingle && (firstId.startsWith('organ_') || firstId.startsWith('ctv_') || isPlanningItem)) {
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();openColorPicker('${firstId}')">
            <span class="ctx-icon">&#127912;</span> Change Color</div>`;
        items += `<div class="ctx-menu-sep"></div>`;
    }

    // Move to category (only for organs, not CTV)
    if (hasOrgans) {
        for (const [catKey, catInfo] of Object.entries(ORGAN_CATEGORIES)) {
            items += `<div class="ctx-menu-item" onclick="hideContextMenu();batchMoveToCategory('${catKey}')">
                <span class="ctx-icon">${catInfo.icon}</span> Move to ${catInfo.label}</div>`;
        }
        items += `<div class="ctx-menu-sep"></div>`;
    }

    // Visibility
    items += `<div class="ctx-menu-item" onclick="hideContextMenu();batchToggleVisibility(true)">
        <span class="ctx-icon">&#128065;</span> Show Selected</div>`;
    items += `<div class="ctx-menu-item" onclick="hideContextMenu();batchToggleVisibility(false)">
        <span class="ctx-icon">&#128064;</span> Hide Selected</div>`;

    // Solo
    items += `<div class="ctx-menu-item" onclick="hideContextMenu();batchSolo()">
        <span class="ctx-icon">&#128269;</span> Solo Selected</div>`;

    // Opacity submenu
    items += `<div class="ctx-menu-sep"></div>`;
    items += `<div class="ctx-menu-item" style="opacity:0.5;cursor:default;font-size:0.6rem;">
        <span class="ctx-icon">&#127912;</span> Opacity</div>`;
    for (const op of [100, 75, 50, 25]) {
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();batchSetOpacity(${op / 100})">
            <span class="ctx-icon" style="opacity:${op / 100}">&#9632;</span> ${op}%</div>`;
    }

    items += `<div class="ctx-menu-sep"></div>`;

    // Show all
    items += `<div class="ctx-menu-item" onclick="hideContextMenu();showAllOrgans()">
        <span class="ctx-icon">&#128065;</span> Show All</div>`;

    // Clear selection
    items += `<div class="ctx-menu-item" onclick="hideContextMenu();selectedItems.clear();renderDataTree();">
        <span class="ctx-icon">&#10005;</span> Clear Selection</div>`;

    menu.innerHTML = items;
    document.body.appendChild(menu);

    const rect = menu.getBoundingClientRect();
    if (rect.right > window.innerWidth) menu.style.left = (x - rect.width) + 'px';
    if (rect.bottom > window.innerHeight) menu.style.top = (y - rect.height) + 'px';

    setTimeout(() => {
        document.addEventListener('click', hideContextMenu, { once: true });
        document.addEventListener('contextmenu', hideContextMenu, { once: true });
    }, 0);

    activeContextMenu = menu;
}

function hideContextMenu() {
    if (activeContextMenu) {
        activeContextMenu.remove();
        activeContextMenu = null;
    }
    // 3D endpoint menus are created by brachybot-3d-manual.js, which cannot
    // safely share this file's lexical `let activeContextMenu` across load
    // orders. Keep a window-level reference as the cross-module contract.
    const externalMenu = window.__brachyContextMenuElement;
    if (externalMenu && externalMenu !== activeContextMenu) externalMenu.remove();
    window.__brachyContextMenuElement = null;
}

function batchToggleVisibility(visible) {
    getSelectedOrganIds().forEach(id => {
        // CTV group
        if (id === 'ctv') {
            dataTreeState.ctv.visible = visible;
            const mesh = scene3D.meshes['ctv'];
            if (mesh) applyMeshVisibility(mesh, visible, dataTreeState.ctv.opacity ?? 0.7);
        }
        // CTV sub-labels
        else if (id.startsWith('ctv_')) {
            if (!dataTreeState.ctvLabels) dataTreeState.ctvLabels = {};
            if (!dataTreeState.ctvLabels[id]) dataTreeState.ctvLabels[id] = { visible: true, opacity: 0.7, color: '#ef4444' };
            dataTreeState.ctvLabels[id].visible = visible;
            const mesh = scene3D.meshes[id];
            if (mesh) applyMeshVisibility(mesh, visible, dataTreeState.ctvLabels[id].opacity ?? dataTreeState.ctv.opacity ?? 0.7);
        }
        // OAR group
        else if (id === 'oar') {
            dataTreeState.organs.forEach(o => {
                o.visible = visible;
                const mesh = scene3D.meshes[o.id];
                if (mesh) applyMeshVisibility(mesh, visible, o.opacity ?? 0.5);
            });
        }
        // Individual organs
        else if (id.startsWith('organ_')) {
            const o = dataTreeState.organs.find(o => o.id === id);
            if (o) {
                o.visible = visible;
                const mesh = scene3D.meshes[id];
                if (mesh) applyMeshVisibility(mesh, visible, o.opacity ?? 0.5);
            }
        }
        // Planning seeds
        else if (id.startsWith('seed_')) {
            const s = dataTreeState.planning.seeds.find(s => s.id === id);
            if (s) {
                s.visible = visible;
                const mesh = scene3D.meshes[id];
                if (mesh) applyMeshVisibility(mesh, visible, s.opacity ?? 1.0);
            }
        }
        // Planning needles
        else if (id.startsWith('needle_')) {
            const n = dataTreeState.planning.needles.find(n => n.id === id);
            if (n) {
                n.visible = visible;
                const mesh = scene3D.meshes[id];
                if (mesh) applyMeshVisibility(mesh, visible, n.opacity ?? 0.8);
            }
        }
        // Dose isosurfaces
        else if (id.startsWith('dose_iso_')) {
            const threshold = parseFloat(id.replace('dose_iso_', ''));
            const d = dataTreeState.planning.doseLevels.find(d => d.threshold === threshold);
            if (d) {
                d.visible = visible;
                const mesh = scene3D.meshes[id];
                if (mesh) applyMeshVisibility(mesh, visible, d.opacity ?? 0.3);
            }
        }
    });
    renderDataTree();
    if (state.ctLoaded) reloadOverlays();
    redrawSeedNeedleOverlays();
    requestViewerVisualRefresh('batch-visibility');
}

function batchMoveToCategory(category) {
    getSelectedOrganIds().forEach(id => {
        if (id.startsWith('organ_')) {
            const o = dataTreeState.organs.find(o => o.id === id);
            if (o) o.category = category;
        }
    });
    renderDataTree();
    if (state.ctLoaded) loadAllSlices();
    redrawSeedNeedleOverlays();
    requestViewerVisualRefresh('batch-category');
    if (typeof syncUIBridgeState === 'function') syncUIBridgeState('data_tree.category').catch(() => {});
}

function batchSolo() {
    const selSet = new Set(getSelectedOrganIds());
    dataTreeState.organs.forEach(o => { o.visible = selSet.has(o.id); });
    dataTreeState.ctv.visible = selSet.has('ctv');
    renderDataTree();
    if (state.ctLoaded) loadAllSlices();
    requestViewerVisualRefresh('batch-solo');
}

function batchSetOpacity(opacity) {
    getSelectedOrganIds().forEach(id => {
        if (id === 'ctv') {
            dataTreeState.ctv.opacity = opacity;
            applyMeshOpacity(scene3D.meshes['ctv'], opacity, dataTreeState.ctv.visible !== false);
        } else if (id.startsWith('ctv_')) {
            // Individual CTV label
            const labelId = parseInt(id.replace('ctv_', ''));
            if (!dataTreeState.ctv.labelOpacities) dataTreeState.ctv.labelOpacities = {};
            dataTreeState.ctv.labelOpacities[labelId] = opacity;
            if (!dataTreeState.ctvLabels) dataTreeState.ctvLabels = {};
            if (!dataTreeState.ctvLabels[id]) dataTreeState.ctvLabels[id] = { visible: true, opacity, color: '#ef4444' };
            dataTreeState.ctvLabels[id].opacity = opacity;
            applyMeshOpacity(scene3D.meshes[id], opacity, dataTreeState.ctvLabels[id].visible !== false);
        } else if (id.startsWith('seed_')) {
            const s = dataTreeState.planning.seeds.find(s => s.id === id);
            if (s) {
                s.opacity = opacity;
                applyMeshOpacity(scene3D.meshes[id], opacity, s.visible !== false);
            }
        } else if (id.startsWith('needle_')) {
            const n = dataTreeState.planning.needles.find(n => n.id === id);
            if (n) {
                n.opacity = opacity;
                applyMeshOpacity(scene3D.meshes[id], opacity, n.visible !== false);
            }
        } else if (id.startsWith('dose_iso_')) {
            const threshold = parseFloat(id.replace('dose_iso_', ''));
            const d = dataTreeState.planning.doseLevels.find(d => d.threshold === threshold);
            if (d) {
                d.opacity = opacity;
                applyMeshOpacity(scene3D.meshes[id], opacity, d.visible !== false);
            }
        } else {
            const o = dataTreeState.organs.find(o => o.id === id);
            if (o) {
                o.opacity = opacity;
                applyMeshOpacity(scene3D.meshes[id], opacity, o.visible !== false);
            }
        }
    });
    renderDataTree();
    if (state.ctLoaded) loadAllSlices();
    redrawSeedNeedleOverlays();
}

async function batchReconstruct3D() {
    const ids = getSelectedOrganIds();
    for (const id of ids) {
        await reconstructOrgan3D(id);
    }
}

function moveOrganToCategory(organId, newCategory) {
    const organ = dataTreeState.organs.find(o => o.id === organId);
    if (organ) {
        organ.category = newCategory;
        renderDataTree();
        if (state.ctLoaded) loadAllSlices();
        if (typeof syncUIBridgeState === 'function') syncUIBridgeState('data_tree.category').catch(() => {});
    }
}

function soloOrgan(organId) {
    dataTreeState.organs.forEach(o => { o.visible = (o.id === organId); });
    if (organId === 'ctv') { dataTreeState.ctv.visible = true; }
    else { dataTreeState.ctv.visible = false; }
    renderDataTree();
    if (state.ctLoaded) loadAllSlices();
}

function showAllOrgans() {
    dataTreeState.organs.forEach(o => { o.visible = true; });
    dataTreeState.ctv.visible = true;
    _planningItems('seeds').forEach(s => { s.visible = true; });
    _planningItems('needles').forEach(n => { n.visible = true; });
    _planningItems('doseLevels').forEach(d => { d.visible = true; });
    // Update 3D meshes visibility
    Object.entries(scene3D.meshes).forEach(([id, mesh]) => {
        if (!mesh) return;
        let opacity = 1;
        if (id.startsWith('seed_')) opacity = _planningItems('seeds').find(s => s.id === id)?.opacity ?? 1.0;
        else if (id.startsWith('needle_')) opacity = _planningItems('needles').find(n => n.id === id)?.opacity ?? 0.8;
        else if (id.startsWith('dose_iso_')) {
            const threshold = parseFloat(id.replace('dose_iso_', ''));
            opacity = _planningItems('doseLevels').find(d => d.threshold === threshold)?.opacity ?? 0.3;
        }
        else if (id.startsWith('organ_')) opacity = dataTreeState.organs.find(o => o.id === id)?.opacity ?? 0.5;
        else if (id.startsWith('ctv_')) opacity = dataTreeState.ctvLabels?.[id]?.opacity ?? dataTreeState.ctv.opacity ?? 0.7;
        applyMeshVisibility(mesh, true, opacity);
    });
    renderDataTree();
    if (state.ctLoaded) loadAllSlices();
}

function setGroupVisibility(category, visible) {
    if (category === 'planning') {
        _planningVisualEntries().forEach(item => { item.visible = visible; });
        _planningItems('seeds').forEach(seed => {
            const mesh = scene3D.meshes[seed.id];
            if (mesh) applyMeshVisibility(mesh, visible, seed.opacity ?? 1.0);
        });
        _planningItems('needles').forEach(needle => {
            const mesh = scene3D.meshes[needle.id];
            if (mesh) applyMeshVisibility(mesh, visible, needle.opacity ?? 0.8);
            if (typeof _setNeedleHandlesVisibility === 'function') _setNeedleHandlesVisibility(needle.id, visible, needle.opacity ?? 0.8);
        });
        _planningItems('doseLevels').forEach(level => {
            const mesh = scene3D.meshes[`dose_iso_${level.threshold}`];
            if (mesh) applyMeshVisibility(mesh, visible, level.opacity ?? 0.3);
        });
        if (state.doseOverlay) state.doseOverlay.visible = visible;
        (dataTreeState.planning.meshes || []).forEach(item => {
            const mesh = scene3D.meshes[item.id];
            if (mesh) applyMeshVisibility(mesh, visible, item.opacity ?? 0.7);
        });
    } else if (category === 'planning_trajectories') {
        _planningItems('trajectories').forEach(trajectory => { trajectory.visible = visible; });
        // The trajectory branch owns its seed children. Keep all seed/needle
        // projections synchronized because a trajectory may have no mesh of
        // its own.
        _planningItems('seeds').forEach(seed => {
            seed.visible = visible;
            const mesh = scene3D.meshes[seed.id];
            if (mesh) applyMeshVisibility(mesh, visible, seed.opacity ?? 1.0);
        });
        _planningItems('needles').forEach(needle => {
            needle.visible = visible;
            const mesh = scene3D.meshes[needle.id];
            if (mesh) applyMeshVisibility(mesh, visible, needle.opacity ?? 0.8);
            if (typeof _setNeedleHandlesVisibility === 'function') _setNeedleHandlesVisibility(needle.id, visible, needle.opacity ?? 0.8);
        });
    } else if (category === 'ctv') {
        dataTreeState.ctv.visible = visible;
        // Update all CTV child labels
        if (dataTreeState.ctvLabels) {
            Object.entries(dataTreeState.ctvLabels).forEach(([id, label]) => {
                label.visible = visible;
                // Update 3D mesh
                const mesh = scene3D.meshes[id];
                if (mesh) applyMeshVisibility(mesh, visible, label.opacity ?? dataTreeState.ctv.opacity ?? 0.7);
            });
        }
    } else if (category === 'oar') {
        dataTreeState.organs.forEach(o => {
            o.visible = visible;
            // Update 3D mesh
            const mesh = scene3D.meshes[o.id];
            if (mesh) applyMeshVisibility(mesh, visible, o.opacity ?? 0.5);
        });
    } else if (category === 'planning_seeds') {
        _planningItems('seeds').forEach(seed => {
            seed.visible = visible;
            const mesh = scene3D.meshes[seed.id];
            if (mesh) applyMeshVisibility(mesh, visible, seed.opacity ?? 1.0);
        });
    } else if (category === 'planning_needles') {
        _planningItems('needles').forEach(needle => {
            needle.visible = visible;
            const mesh = scene3D.meshes[needle.id];
            if (mesh) applyMeshVisibility(mesh, visible, needle.opacity ?? 0.8);
            if (typeof _setNeedleHandlesVisibility === 'function') {
                _setNeedleHandlesVisibility(needle.id, visible, needle.opacity ?? 0.8);
            }
        });
    } else if (category === 'dose_isosurfaces') {
        _planningItems('doseLevels').forEach(level => {
            level.visible = visible;
            const mesh = scene3D.meshes[`dose_iso_${level.threshold}`];
            if (mesh) applyMeshVisibility(mesh, visible, level.opacity ?? 0.3);
        });
    } else if (category === 'planning_meshes') {
        (dataTreeState.planning.meshes || []).forEach(m => {
            m.visible = visible;
            const mesh = scene3D.meshes[m.id];
            if (mesh) applyMeshVisibility(mesh, visible, m.opacity ?? 0.7);
        });
    } else {
        dataTreeState.organs.filter(o => o.category === category).forEach(o => {
            o.visible = visible;
            // Update 3D mesh
            const mesh = scene3D.meshes[o.id];
            if (mesh) applyMeshVisibility(mesh, visible, o.opacity ?? 0.5);
        });
    }
    renderDataTree();
    if (state.ctLoaded) reloadOverlays();
    redrawSeedNeedleOverlays();
    requestViewerVisualRefresh('group-visibility');
}

let _groupOpacityTimer = null;
function setGroupOpacity(category, value) {
    const opacity = parseInt(value) / 100;
    if (category === 'planning' || category === 'planning_trajectories') {
        const trajectories = _planningItems('trajectories');
        const entries = category === 'planning'
            ? _planningVisualEntries()
            : [
                ...trajectories,
                ..._planningItems('seeds').filter(seed => trajectories.some(t => _trajectoryContains(seed, t))),
                ..._planningItems('needles').filter(needle => trajectories.some(t => _trajectoryContains(needle, t))),
            ];
        entries.forEach(item => { item.opacity = opacity; });
        _planningItems('seeds').forEach(seed => {
            if (category === 'planning_trajectories' && !_planningItems('trajectories').some(t => _trajectoryContains(seed, t))) return;
            applyMeshOpacity(scene3D.meshes[seed.id], opacity, seed.visible !== false);
        });
        _planningItems('needles').forEach(needle => {
            if (category === 'planning_trajectories' && !_planningItems('trajectories').some(t => _trajectoryContains(needle, t))) return;
            applyMeshOpacity(scene3D.meshes[needle.id], opacity, needle.visible !== false);
            if (typeof _setNeedleHandlesVisibility === 'function') _setNeedleHandlesVisibility(needle.id, needle.visible !== false, opacity);
        });
        if (category === 'planning') {
            _planningItems('doseLevels').forEach(level => {
                applyMeshOpacity(scene3D.meshes[`dose_iso_${level.threshold}`], opacity, level.visible !== false);
            });
            if (state.doseOverlay) state.doseOverlay.opacity = opacity;
            (dataTreeState.planning.meshes || []).forEach(item => {
                applyMeshOpacity(scene3D.meshes[item.id], opacity, item.visible !== false);
            });
        }
    } else if (category === 'ctv') {
        dataTreeState.ctv.opacity = opacity;
        // Update all CTV child labels
        if (dataTreeState.ctvLabels) {
            Object.entries(dataTreeState.ctvLabels).forEach(([id, label]) => {
                label.opacity = opacity;
                // Update 3D mesh
                applyMeshOpacity(scene3D.meshes[id], opacity, label.visible !== false);
            });
        }
    } else if (category === 'oar') {
        dataTreeState.organs.forEach(o => {
            o.opacity = opacity;
            // Update 3D mesh
            applyMeshOpacity(scene3D.meshes[o.id], opacity, o.visible !== false);
        });
    } else if (category === 'planning_seeds') {
        _planningItems('seeds').forEach(seed => {
            seed.opacity = opacity;
            applyMeshOpacity(scene3D.meshes[seed.id], opacity, seed.visible !== false);
        });
    } else if (category === 'planning_needles') {
        _planningItems('needles').forEach(needle => {
            needle.opacity = opacity;
            applyMeshOpacity(scene3D.meshes[needle.id], opacity, needle.visible !== false);
            if (typeof _setNeedleHandlesVisibility === 'function') {
                _setNeedleHandlesVisibility(needle.id, needle.visible !== false, opacity);
            }
        });
    } else if (category === 'dose_isosurfaces') {
        _planningItems('doseLevels').forEach(level => {
            level.opacity = opacity;
            applyMeshOpacity(scene3D.meshes[`dose_iso_${level.threshold}`], opacity, level.visible !== false);
        });
    } else if (category === 'planning_meshes') {
        (dataTreeState.planning.meshes || []).forEach(m => {
            m.opacity = opacity;
            applyMeshOpacity(scene3D.meshes[m.id], opacity, m.visible !== false);
        });
    } else {
        dataTreeState.organs.filter(o => o.category === category).forEach(o => {
            o.opacity = opacity;
            // Update 3D mesh
            applyMeshOpacity(scene3D.meshes[o.id], opacity, o.visible !== false);
        });
    }
    // Debounce tree re-render and overlay reload
    clearTimeout(_groupOpacityTimer);
    _groupOpacityTimer = setTimeout(() => {
        renderDataTree();
        if (state.ctLoaded) loadAllSlices();
        redrawSeedNeedleOverlays();
        requestViewerVisualRefresh('group-opacity');
    }, 150);
}

// Wrapper for context menu: takes percentage (0-100) directly
function setGroupOpacityValue(category, percentValue) {
    // setGroupOpacity expects value 0-100 (it divides by 100 internally)
    setGroupOpacity(category, percentValue);
}

function toggleTreeGroup(header) {
    const arrow = header.querySelector('.arrow');
    // Find the .tree-group-items that is a sibling of the parent .tree-group
    const group = header.closest('.tree-group');
    if (!group) return;
    const items = group.querySelector(':scope > .tree-group-items');
    if (arrow && items) {
        arrow.classList.toggle('collapsed');
        items.classList.toggle('collapsed');
    }
}

function toggleDataVisibility(id) {
    // Handle individual organ toggles
    if (id.startsWith('organ_')) {
        const organ = dataTreeState.organs.find(o => o.id === id);
        if (organ) {
            organ.visible = !organ.visible;
            // Also toggle 3D mesh visibility
            const mesh = scene3D.meshes[id];
            if (mesh) applyMeshVisibility(mesh, organ.visible, organ.opacity ?? 0.5);
            renderDataTree();
            if (state.ctLoaded) reloadOverlays();
        }
        return;
    }

    // Handle individual CTV label toggles
    if (id.startsWith('ctv_')) {
        if (!dataTreeState.ctvLabels) dataTreeState.ctvLabels = {};
        if (!dataTreeState.ctvLabels[id]) {
            dataTreeState.ctvLabels[id] = { visible: true, opacity: 0.7, color: '#ef4444' };
        }
        dataTreeState.ctvLabels[id].visible = !dataTreeState.ctvLabels[id].visible;
        // Also toggle 3D mesh visibility
            const mesh = scene3D.meshes[id];
            if (mesh) applyMeshVisibility(mesh, dataTreeState.ctvLabels[id].visible, dataTreeState.ctvLabels[id].opacity ?? dataTreeState.ctv.opacity ?? 0.7);
        renderDataTree();
        if (state.ctLoaded) reloadOverlays();
        return;
    }

    // Handle individual trajectory toggles and all of their descendants.
    const trajectory = _planningItems('trajectories').find(t => String(t.id) === String(id));
    if (trajectory) {
        trajectory.visible = !trajectory.visible;
        _planningItems('seeds').filter(seed => _trajectoryContains(seed, trajectory)).forEach(seed => {
            seed.visible = trajectory.visible;
            const mesh = scene3D.meshes[seed.id];
            if (mesh) applyMeshVisibility(mesh, seed.visible, seed.opacity ?? 1.0);
        });
        _planningItems('needles').filter(needle => _trajectoryContains(needle, trajectory)).forEach(needle => {
            needle.visible = trajectory.visible;
            const mesh = scene3D.meshes[needle.id];
            if (mesh) applyMeshVisibility(mesh, needle.visible, needle.opacity ?? 0.8);
            if (typeof _setNeedleHandlesVisibility === 'function') _setNeedleHandlesVisibility(needle.id, needle.visible, needle.opacity ?? 0.8);
        });
        renderDataTree();
        redrawSeedNeedleOverlays();
        return;
    }

    // Handle planning seed toggles
    if (id.startsWith('seed_')) {
        const seed = dataTreeState.planning.seeds.find(s => s.id === id);
        if (seed) {
            seed.visible = !seed.visible;
            const mesh = scene3D.meshes[id];
            if (mesh) applyMeshVisibility(mesh, seed.visible, seed.opacity ?? 1.0);
            renderDataTree();
            redrawSeedNeedleOverlays();
        }
        return;
    }

    // Handle planning needle toggles
    if (id.startsWith('needle_')) {
        const needle = dataTreeState.planning.needles.find(n => n.id === id);
        if (needle) {
            needle.visible = !needle.visible;
            const mesh = scene3D.meshes[id];
            if (mesh) applyMeshVisibility(mesh, needle.visible, needle.opacity ?? 0.8);
            if (typeof _setNeedleHandlesVisibility === 'function') {
                _setNeedleHandlesVisibility(needle.id, needle.visible, needle.opacity ?? 0.8);
            }
            renderDataTree();
            redrawSeedNeedleOverlays();
        }
        return;
    }

    // Handle dose isosurface toggles
    if (id.startsWith('dose_iso_')) {
        const threshold = parseFloat(id.replace('dose_iso_', ''));
        const level = dataTreeState.planning.doseLevels.find(d => d.threshold === threshold);
        if (level) {
            level.visible = !level.visible;
            const mesh = scene3D.meshes[id];
            if (mesh) applyMeshVisibility(mesh, level.visible, level.opacity ?? 0.3);
            renderDataTree();
        }
        return;
    }

    // Handle individual 3D mesh toggles (CTV/OAR/dose/etc. added via
    // addMeshToScene). The id is the same one used in scene3D.meshes.
    const meshEntry = (dataTreeState.planning.meshes || []).find(m => m.id === id);
    if (meshEntry) {
        meshEntry.visible = !meshEntry.visible;
        const mesh = scene3D.meshes[id];
        if (mesh) applyMeshVisibility(mesh, meshEntry.visible, meshEntry.opacity ?? 0.7);
        renderDataTree();
        return;
    }

    if (!dataTreeState[id]) return;
    dataTreeState[id].visible = !dataTreeState[id].visible;
    // Toggle 3D mesh for CTV
    if (id === 'ctv') {
        const mesh = scene3D.meshes['ctv'];
        if (mesh) applyMeshVisibility(mesh, dataTreeState[id].visible, dataTreeState[id].opacity ?? 0.7);
        // Propagate to all CTV child labels
        if (dataTreeState.ctvLabels) {
            Object.values(dataTreeState.ctvLabels).forEach(label => {
                label.visible = dataTreeState.ctv.visible;
                const m = scene3D.meshes[label.id || label.labelId];
                if (m) applyMeshVisibility(m, label.visible, label.opacity ?? dataTreeState.ctv.opacity ?? 0.7);
            });
        }
    } else if (id === 'planning') {
        // Propagate to all planning sub-items
        _planningItems('trajectories').forEach(t => t.visible = dataTreeState.planning.visible);
        _planningItems('seeds').forEach(s => {
            s.visible = dataTreeState.planning.visible;
            const m = scene3D.meshes[s.id];
            if (m) applyMeshVisibility(m, s.visible, s.opacity ?? 1.0);
        });
        _planningItems('needles').forEach(n => {
            n.visible = dataTreeState.planning.visible;
            const m = scene3D.meshes[n.id];
            if (m) applyMeshVisibility(m, n.visible, n.opacity ?? 0.8);
        });
        _planningItems('doseLevels').forEach(d => {
            d.visible = dataTreeState.planning.visible;
            const m = scene3D.meshes[`dose_iso_${d.threshold}`];
            if (m) applyMeshVisibility(m, d.visible, d.opacity ?? 0.3);
        });
        (dataTreeState.planning.meshes || []).forEach(item => {
            item.visible = dataTreeState.planning.visible;
            const m = scene3D.meshes[item.id];
            if (m) applyMeshVisibility(m, item.visible, item.opacity ?? 0.7);
        });
    }

    // Sync with existing overlay system
    if (id === 'ctv') {
        state.viewerSettings.showCTV = dataTreeState.ctv.visible;
        const cb = document.getElementById('overlayCTV');
        if (cb) cb.checked = dataTreeState.ctv.visible;
    } else if (id === 'oar') {
        state.viewerSettings.showOAR = dataTreeState.oar.visible;
        const cb = document.getElementById('overlayOAR');
        if (cb) cb.checked = dataTreeState.oar.visible;
        // Toggle all organs
        dataTreeState.organs.forEach(o => o.visible = dataTreeState.oar.visible);
    }

    renderDataTree();
    if (state.ctLoaded) reloadOverlays();
}

function setDataItemVisibility(id, visible) {
    let current = null;
    if (id.startsWith('organ_')) current = dataTreeState.organs.find(o => o.id === id)?.visible;
    else if (id.startsWith('ctv_')) current = dataTreeState.ctvLabels?.[id]?.visible;
    else if (_planningItems('trajectories').some(t => String(t.id) === String(id))) current = _planningItems('trajectories').find(t => String(t.id) === String(id))?.visible;
    else if (id.startsWith('seed_')) current = _planningItems('seeds').find(s => s.id === id)?.visible;
    else if (id.startsWith('needle_')) current = _planningItems('needles').find(n => n.id === id)?.visible;
    else if (id.startsWith('dose_iso_')) {
        const threshold = parseFloat(id.replace('dose_iso_', ''));
        current = _planningItems('doseLevels').find(d => d.threshold === threshold)?.visible;
    } else if (dataTreeState[id]) current = dataTreeState[id].visible;
    if (current === null || current === undefined) return false;
    if (!!current !== !!visible) toggleDataVisibility(id);
    return true;
}

let _opacityTimer = null;
function setDataOpacity(id, value) {
    const opacity = parseInt(value) / 100;
    // Handle individual organ opacity
    if (id.startsWith('organ_')) {
        const organ = dataTreeState.organs.find(o => o.id === id);
        if (organ) {
            organ.opacity = opacity;
            // Also update 3D mesh opacity
            applyMeshOpacity(scene3D.meshes[id], opacity, organ.visible !== false);
        }
        // Debounce overlay reload
        clearTimeout(_opacityTimer);
        _opacityTimer = setTimeout(() => {
            if (state.ctLoaded) reloadOverlays();
            requestViewerVisualRefresh('organ-opacity');
        }, 150);
        return;
    }

    // Handle individual CTV label opacity
    if (id.startsWith('ctv_')) {
        if (!dataTreeState.ctvLabels) dataTreeState.ctvLabels = {};
        if (!dataTreeState.ctvLabels[id]) {
            dataTreeState.ctvLabels[id] = { visible: true, opacity: opacity, color: '#ef4444' };
        } else {
            dataTreeState.ctvLabels[id].opacity = opacity;
        }
        // Also update 3D mesh opacity
        applyMeshOpacity(scene3D.meshes[id], opacity, dataTreeState.ctvLabels[id].visible !== false);
        // Debounce overlay reload
        clearTimeout(_opacityTimer);
        _opacityTimer = setTimeout(() => {
            if (state.ctLoaded) reloadOverlays();
            requestViewerVisualRefresh('ctv-opacity');
        }, 150);
        return;
    }

    // Handle individual trajectory opacity and descendants.
    const trajectory = _planningItems('trajectories').find(t => String(t.id) === String(id));
    if (trajectory) {
        trajectory.opacity = opacity;
        _planningItems('seeds').filter(seed => _trajectoryContains(seed, trajectory)).forEach(seed => {
            seed.opacity = opacity;
            applyMeshOpacity(scene3D.meshes[seed.id], opacity, seed.visible !== false);
        });
        _planningItems('needles').filter(needle => _trajectoryContains(needle, trajectory)).forEach(needle => {
            needle.opacity = opacity;
            applyMeshOpacity(scene3D.meshes[needle.id], opacity, needle.visible !== false);
            if (typeof _setNeedleHandlesVisibility === 'function') _setNeedleHandlesVisibility(needle.id, needle.visible !== false, opacity);
        });
        renderDataTreeDebounced();
        return;
    }

    // Handle planning seed opacity
    if (id.startsWith('seed_')) {
        const seed = dataTreeState.planning.seeds.find(s => s.id === id);
        if (seed) {
            seed.opacity = opacity;
            applyMeshOpacity(scene3D.meshes[id], opacity, seed.visible !== false);
            redrawSeedNeedleOverlays();
            requestViewerVisualRefresh('seed-opacity');
        }
        return;
    }

    // Handle planning needle opacity
    if (id.startsWith('needle_')) {
        const needle = dataTreeState.planning.needles.find(n => n.id === id);
        if (needle) {
            needle.opacity = opacity;
            applyMeshOpacity(scene3D.meshes[id], opacity, needle.visible !== false);
            if (typeof _setNeedleHandlesVisibility === 'function') {
                _setNeedleHandlesVisibility(needle.id, needle.visible !== false, opacity);
            }
            redrawSeedNeedleOverlays();
            requestViewerVisualRefresh('needle-opacity');
        }
        return;
    }

    // Handle dose isosurface opacity
    if (id.startsWith('dose_iso_')) {
        const threshold = parseFloat(id.replace('dose_iso_', ''));
        const level = dataTreeState.planning.doseLevels.find(d => d.threshold === threshold);
        if (level) {
            level.opacity = opacity;
            applyMeshOpacity(scene3D.meshes[id], opacity, level.visible !== false);
            requestViewerVisualRefresh('dose-isosurface-opacity');
        }
        return;
    }

    const meshEntry = (dataTreeState.planning.meshes || []).find(m => m.id === id);
    if (meshEntry) {
        meshEntry.opacity = opacity;
        applyMeshOpacity(scene3D.meshes[id], opacity, meshEntry.visible !== false);
        requestViewerVisualRefresh('planning-mesh-opacity');
        return;
    }

    if (!dataTreeState[id]) return;
    dataTreeState[id].opacity = opacity;
    // Update CTV 3D mesh
    if (id === 'ctv') {
        applyMeshOpacity(scene3D.meshes['ctv'], opacity, dataTreeState[id].visible !== false);
    }

    if (state.ctLoaded) reloadOverlays();
    requestViewerVisualRefresh('data-opacity');
}

function selectDataItem(id) {
    // Highlight selected item
    document.querySelectorAll('.tree-item').forEach(el => el.classList.remove('selected'));
    const items = document.querySelectorAll('.tree-item');
    items.forEach(el => {
        if (el.onclick && el.onclick.toString().includes(`'${id}'`)) {
            el.classList.add('selected');
        }
    });
}

function refreshDataTree() {
    renderDataTree();
}

// Initialize data tree on load
setTimeout(() => renderDataTree(), 500);

/******** DATA TREE RESIZE ********/
