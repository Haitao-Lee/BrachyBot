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

// Planning has one persisted all-view master switch plus independent 2D/3D
// switches.  Keep the parent constraint in the visibility helpers themselves,
// rather than relying on each loader or renderer to remember it.  A planning
// mesh can be created long after the compact workspace snapshot was applied;
// centralising this rule prevents a late dose/seed/guide callback from making a
// hidden Planning partially visible again.
function _isPlanningDescendantNode(node) {
    if (!node || typeof node !== 'object') return false;
    const id = String(node.id || node.nodeId || '');
    if (!id || id === 'planning') return false;
    if (String(node.parentId || '') === 'planning') return true;
    if (id === 'dose_overlay'
        || id.startsWith('traj_')
        || id.startsWith('seed_')
        || id.startsWith('needle_')
        || id.startsWith('dose_iso_')) return true;
    const planning = dataTreeState?.planning;
    return !!planning && (
        (planning.trajectories || []).some(item => item === node || String(item?.id || '') === id)
        || (planning.seeds || []).some(item => item === node || String(item?.id || '') === id)
        || (planning.needles || []).some(item => item === node || String(item?.id || '') === id)
        || (planning.doseLevels || []).some(item => item === node || String(item?.id || '') === id)
        || (planning.meshes || []).some(item => item === node || String(item?.id || '') === id)
        || planning.doseOverlay === node
    );
}

function _planningViewVisible(view) {
    const planning = dataTreeState?.planning;
    if (!planning) return false;
    const viewKey = view === '2d' ? 'visible2D' : 'visible3D';
    return planning.visible !== false && planning[viewKey] !== false;
}

function _planningMasterVisible() {
    return dataTreeState?.planning?.visible !== false;
}

function _deduplicatePlanningRows() {
    const planning = dataTreeState?.planning;
    if (!planning) return;
    const uniqueById = (items) => {
        const byId = new Map();
        (Array.isArray(items) ? items : []).forEach(item => {
            const id = String(item?.id || '').trim();
            if (id) byId.set(id, item);
        });
        return [...byId.values()];
    };
    planning.trajectories = uniqueById(planning.trajectories);
    planning.seeds = uniqueById(planning.seeds);
    planning.needles = uniqueById(planning.needles);
    planning.trajectories.forEach(trajectory => {
        trajectory.seeds = planning.seeds.filter(seed => _trajectoryContains(seed, trajectory));
    });
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
let skinSurfaceData = null;  // Uint8Array, exact guide body envelope (Z, Y, X)
let skinSurfaceShape = null;
let labelColorLUT = {};    // Legacy alias for the OAR LUT
let ctvLabelColorLUT = {}; // CTV labels have their own namespace (label 1 is red)
let oarLabelColorLUT = {}; // OAR label IDs may overlap CTV label IDs
let organMetaFromServer = {};  // {label_id: {name, color, voxels}}
// Generic BiomedParse masks are kept outside the CTV/OAR byte stream. The
// catalogue is durable metadata; this map holds only the active session's
// binary volume needed for 2D compositing.
let genericMaskVolumeData = Object.create(null);
let genericMaskCatalogGeneration = 0;
let genericMaskCatalogSessionId = '';
let viewerDataLoadGeneration = 0;
const viewerDataAbortControllers = new Set();

function invalidateViewerDataLoads() {
    viewerDataLoadGeneration += 1;
    // A CT/session switch can otherwise leave old slice requests in flight.
    // They are harmless after the generation check, but cancelling them also
    // prevents a stale request from reaching the server after the new CT has
    // already replaced the old volume.
    viewerDataAbortControllers.forEach(controller => {
        try { controller.abort(); } catch (_) {}
    });
    viewerDataAbortControllers.clear();
    return viewerDataLoadGeneration;
}

function _viewerDataSessionId(explicitSessionId = null) {
    const value = explicitSessionId
        || (typeof _activeApiSessionId === 'function' ? _activeApiSessionId() : null)
        || state?.sessionId
        || '';
    return String(value || '');
}

function _viewerDataHeaders(sessionId, headers = {}) {
    const result = { ...headers };
    if (sessionId) result['X-BrachyBot-Session'] = sessionId;
    return result;
}

function _captureViewerDataScope(explicitSessionId = null) {
    return {
        sessionId: _viewerDataSessionId(explicitSessionId),
        dataGeneration: viewerDataLoadGeneration,
        renderGeneration: window.__viewerRenderGeneration || 0,
    };
}

function _viewerDataScopeIsCurrent(scope, requireRenderGeneration = false) {
    if (!scope) return false;
    if (scope.dataGeneration !== viewerDataLoadGeneration) return false;
    if (scope.sessionId && scope.sessionId !== _viewerDataSessionId()) return false;
    if (requireRenderGeneration
        && scope.renderGeneration !== (window.__viewerRenderGeneration || 0)) return false;
    return true;
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

async function loadVolumeData(options = {}) {
    const scope = _captureViewerDataScope(options.sessionId);
    const volumeRetryAttempt = Number(options._volumeRetryAttempt || 0);
    const sid = scope.sessionId || (typeof activeSessionId !== 'undefined' ? String(activeSessionId) : '');
    if (_viewerDataScopeIsCurrent(scope)) {
        state.viewerSettings.threshold = null;
        const thresholdInput = document.getElementById('viewerThreshold');
        if (thresholdInput) thresholdInput.value = '';
    }

    let buffer = null, shapeZ, shapeY, shapeX, spacingX, spacingY, spacingZ, fromCache = false;

    // --- browser cache: CT volume is immutable per session ---
    if (sid && window.SessionCache) {
        // IndexedDB is only an optimisation. A blocked browser transaction
        // must not prevent the authoritative server request from starting.
        const cached = await Promise.race([
            Promise.resolve()
                .then(() => window.SessionCache.get(sid, 'ct', 'volume'))
                .catch(() => null),
            new Promise(resolve => setTimeout(() => resolve(null), 5000)),
        ]);
        if (cached && cached.byteLength > 16) {
            try {
                const view = new DataView(cached);
                const hdrLen = view.getInt32(0, true);
                if (hdrLen > 0 && hdrLen < 512 && cached.byteLength > hdrLen + 8) {
                    const hdrBytes = new Uint8Array(cached, 4, hdrLen);
                    const hdr = JSON.parse(new TextDecoder().decode(hdrBytes));
                    shapeZ = hdr.z; shapeY = hdr.y; shapeX = hdr.x;
                    spacingX = hdr.sx; spacingY = hdr.sy; spacingZ = hdr.sz;
                    if (shapeZ > 0 && shapeY > 0 && shapeX > 0) {
                        buffer = cached.slice(4 + hdrLen);
                        fromCache = true;
                    }
                }
            } catch (_) { /* corrupt cache, fall through */ }
        }
    }

    if (!buffer) {
        const request = typeof window.fetchViewerJsonWithRetry === 'function'
            ? await window.fetchViewerJsonWithRetry(
                API + '/viewer/volume',
                { headers: _viewerDataHeaders(scope.sessionId) },
                { requestTimeoutMs: 60000, maxWaitMs: 300000, responseType: 'arrayBuffer' },
            )
            : null;
        if (!request?.response) {
            throw request?.error || new Error('CT volume request timed out');
        }
        const res = request.response;
        if (!res.ok) throw new Error(request.data?.error || 'Failed to load volume');
        if (!_viewerDataScopeIsCurrent(scope)) return false;

        shapeZ = parseInt(res.headers.get('X-Shape-Z'));
        shapeY = parseInt(res.headers.get('X-Shape-Y'));
        shapeX = parseInt(res.headers.get('X-Shape-X'));
        spacingX = parseFloat(res.headers.get('X-Spacing-X'));
        spacingY = parseFloat(res.headers.get('X-Spacing-Y'));
        spacingZ = parseFloat(res.headers.get('X-Spacing-Z'));
        buffer = request.data;
        if (!(buffer instanceof ArrayBuffer) || buffer.byteLength === 0) {
            throw new Error('CT volume response was empty');
        }
        if (!_viewerDataScopeIsCurrent(scope)) return false;
    }

    volumeShape = [shapeZ, shapeY, shapeX];
    volumeSpacing = [spacingX, spacingY, spacingZ];
    volumeData = new Int16Array(buffer);
    uiDebugLog(`Volume loaded: ${shapeZ}x${shapeY}x${shapeX}, ${volumeData.length} voxels${fromCache ? ' (cache)' : ''}`);

    // Async cache write — never block rendering.
    if (!fromCache && sid && window.SessionCache && buffer.byteLength > 0) {
        const hdr = JSON.stringify({ z: shapeZ, y: shapeY, x: shapeX, sx: spacingX, sy: spacingY, sz: spacingZ });
        const hdrBytes = new TextEncoder().encode(hdr);
        const hdrLenBuf = new ArrayBuffer(4);
        new DataView(hdrLenBuf).setInt32(0, hdrBytes.length, true);
        const cached = new Uint8Array(4 + hdrBytes.length + buffer.byteLength);
        cached.set(new Uint8Array(hdrLenBuf), 0);
        cached.set(hdrBytes, 4);
        cached.set(new Uint8Array(buffer), 4 + hdrBytes.length);
        window.SessionCache.put(sid, 'ct', 'volume', cached.buffer).catch(function() {});
    }

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
    // Callers outside the label-volume loader (manual segmentation, a
    // planning-step refresh, and workspace restore) often do not have a
    // generation captured at the call site.  Treat omitted values as the
    // current scope instead of comparing ``undefined`` with the numeric
    // generation and discarding valid metadata as stale.
    const generationValue = Number(expectedGeneration);
    const generation = Number.isFinite(generationValue)
        ? generationValue
        : viewerDataLoadGeneration;
    const sessionId = String(expectedSessionId || _viewerDataSessionId() || '');
    try {
        const request = typeof window.fetchViewerJsonWithRetry === 'function'
            ? await window.fetchViewerJsonWithRetry(
                API + '/viewer/organs',
                { headers: _viewerDataHeaders(sessionId) },
                { requestTimeoutMs: 30000, maxWaitMs: 120000 },
            )
            : null;
        if (!request?.response?.ok) return false;
        const payload = request.data || {};
        if (generation !== viewerDataLoadGeneration
            || (sessionId && sessionId !== _viewerDataSessionId())) return false;
        let organs = payload?.organs || {};
        if (!Object.keys(organs).length) {
            const counts = payload?.organ_counts || payload?.label_counts || {};
            const names = payload?.organ_names || {};
            const derived = {};
            Object.entries(counts).forEach(([labelId, count], index) => {
                const key = String(labelId);
                derived[key] = {
                    name: names[key] || names[labelId] || `OAR ${index + 1}`,
                    voxel_count: Number(count) || 0,
                };
            });
            organs = derived;
        }
        if (!Object.keys(organs).length) return false;
        updateOrganList(organs, payload.oar_source || payload.oar_mask_provenance || '');
        if (typeof dataTreeState !== 'undefined' && dataTreeState.oar) {
            dataTreeState.oar.loaded = true;
            if (!state?.viewerSettings?.userConfigured) dataTreeState.oar.visible = true;
        }
        try { if (typeof renderDataTree === 'function') renderDataTree(); } catch (_) {}
        if (typeof window.scheduleWorkspaceSave === 'function') {
            window.scheduleWorkspaceSave('viewer.oar_metadata_loaded');
        }
        return true;
    } catch (error) {
        console.debug('[viewer] OAR Data Tree metadata fallback unavailable:', error);
        return false;
    }
}

async function loadLabelVolumes(options = {}) {
    const scope = _captureViewerDataScope(options.sessionId);
    const sid = scope.sessionId || (typeof activeSessionId !== 'undefined' ? String(activeSessionId) : '');
    // Generic/open masks are independent from the shared clinical volume.
    // Start hydration in parallel so standalone masks restore without CTV/OAR,
    // but publish the promise to a cold workspace restore when it supplies a
    // task registrar. The old fire-and-forget call left Upload Mask children
    // in "Loading" after the case-level progress notice had already closed.
    const genericMasksTask = Promise.resolve(hydrateGenericMasksFromServer(scope));
    if (typeof options.registerBackgroundTask === 'function') {
        options.registerBackgroundTask(genericMasksTask, { kind: 'generic_masks' });
    } else {
        void genericMasksTask;
    }
    const preserveViewerState = options.preserveViewerState === true;
    // A fresh segmentation/import is a new clinical result, not a viewer
    // preference restore.  Older snapshots could persist the initial CT-only
    // defaults as if the user had explicitly selected them, which left valid
    // masks invisible after segmentation.  Callers opt into this reset only
    // for a completed segmentation or mask import; ordinary session restore
    // continues to preserve the user's saved presentation.
    if (options.resetPresentation === true && state?.viewerSettings) {
        state.viewerSettings.userConfigured = false;
    }
    // A new load belongs to one session scope.  Reset transient metadata
    // before consulting IndexedDB so an empty/new case cannot inherit OAR
    // names from the previously visible case while its own payload loads.
    organMetaFromServer = {};
    // A completed segmentation/upload replaces the authoritative server label
    // volume. Do not let an older IndexedDB entry hide that new Data Tree state.
    const forceFresh = options.forceFresh === true;
    const retryAttempt = Number(options._labelVolumeRetryAttempt || 0);

    let allBytes = null, fromCache = false;
    let shapeZ, shapeY, shapeX, hasCTV, hasOAR, ctvSize, oarSize, oarSource = '';
    let ctvBytesPerVoxel = 1, oarBytesPerVoxel = 1;
    let cachedColorLUT = null, cachedCtvColorLUT = null, cachedOarColorLUT = null;
    let cachedCtvLabelMap = null, cachedCtvObjectMap = null;
    let cachedOrganMeta = null, cachedStructureVersion = 0;

    // --- IndexedDB cache ---
    if (!forceFresh && sid && window.SessionCache) {
        // A stale/locked IndexedDB read is not a valid restore boundary. Fall
        // back to the session-owned server volume after a short deadline.
        const cached = await Promise.race([
            Promise.resolve()
                .then(() => window.SessionCache.get(sid, 'labels', 'volume'))
                .catch(() => null),
            new Promise(resolve => setTimeout(() => resolve(null), 5000)),
        ]);
        if (cached && cached.byteLength > 512) {
            try {
                const view = new DataView(cached);
                const hdrLen = view.getInt32(0, true);
                if (hdrLen > 0 && hdrLen < 65536 && cached.byteLength > 4 + hdrLen) {
                    const hdrBytes = new Uint8Array(cached, 4, hdrLen);
                    const hdr = JSON.parse(new TextDecoder().decode(hdrBytes));
                    shapeZ = hdr.z; shapeY = hdr.y; shapeX = hdr.x;
                    hasCTV = hdr.hasCTV; hasOAR = hdr.hasOAR;
                    ctvSize = hdr.ctvSize; oarSize = hdr.oarSize;
                    ctvBytesPerVoxel = Number(hdr.ctvBytesPerVoxel || 1);
                    oarBytesPerVoxel = Number(hdr.oarBytesPerVoxel || 1);
                    oarSource = hdr.oarSource || '';
                    cachedColorLUT = hdr.colorLUT || null;
                    cachedCtvColorLUT = hdr.ctvColorLUT || null;
                    cachedOarColorLUT = hdr.oarColorLUT || null;
                    cachedCtvLabelMap = hdr.ctvLabelMap || null;
                    cachedCtvObjectMap = hdr.ctvObjectMap || null;
                    cachedOrganMeta = hdr.organMeta || null;
                    cachedStructureVersion = Number(hdr.structureVersion || 0);
                    // Cache format v1 stored OAR labels as uint8. Labels from
                    // nnUNet and uploaded volumes can be 201-203 or 10000, so
                    // reusing that entry would silently wrap IDs and make the
                    // Data Tree disagree with the 2D overlay. Only the
                    // explicitly versioned uint16 format is safe to restore.
                    // v5 separates CTV and OAR namespaces and introduces the
                    // higher-chroma clinical structure palette.
                    const cacheFormatCurrent = Number(hdr.formatVersion || 0) >= 5;
                    const oarEncodingCurrent = !hasOAR || oarBytesPerVoxel === 2;
                    if (shapeZ > 0 && shapeY > 0 && shapeX > 0
                            && cacheFormatCurrent && oarEncodingCurrent) {
                        allBytes = new Uint8Array(cached, 4 + hdrLen);
                        fromCache = true;
                    }
                }
            } catch (_) { /* corrupt, fall through */ }
        }
    }

    if (!allBytes) {
        try {
            const request = typeof window.fetchViewerJsonWithRetry === 'function'
                ? await window.fetchViewerJsonWithRetry(
                    API + '/viewer/label_volume',
                    { headers: _viewerDataHeaders(scope.sessionId) },
                    { requestTimeoutMs: 60000, maxWaitMs: 300000, responseType: 'arrayBuffer' },
                )
                : null;
            if (!request?.response) {
                uiDebugLog('Label volume restore timed out; keeping the current viewer state');
                return false;
            }
            const res = request.response;
            if (!res.ok) { uiDebugLog(request.data?.error || 'No label volumes available'); return false; }
            if (!_viewerDataScopeIsCurrent(scope)) return false;

            shapeZ = parseInt(res.headers.get('X-Shape-Z'));
            shapeY = parseInt(res.headers.get('X-Shape-Y'));
            shapeX = parseInt(res.headers.get('X-Shape-X'));
            hasCTV = res.headers.get('X-Has-CTV') === 'true';
            hasOAR = res.headers.get('X-Has-OAR') === 'true';
            ctvSize = parseInt(res.headers.get('X-CTV-Size') || '0');
            oarSize = parseInt(res.headers.get('X-OAR-Size') || '0');
            ctvBytesPerVoxel = parseInt(res.headers.get('X-CTV-Bytes-Per-Voxel') || '1');
            oarBytesPerVoxel = parseInt(res.headers.get('X-OAR-Bytes-Per-Voxel') || '1');
            // Keep provenance in the outer variable so the metadata update
            // below receives it for fresh loads as well as cached loads.
            oarSource = res.headers.get('X-OAR-Source') || '';

            labelColorLUT = JSON.parse(res.headers.get('X-Color-LUT') || '{}');
            ctvLabelColorLUT = JSON.parse(res.headers.get('X-CTV-Color-LUT') || '{}');
            oarLabelColorLUT = JSON.parse(res.headers.get('X-OAR-Color-LUT') || '{}');
            if (!Object.keys(ctvLabelColorLUT).length) ctvLabelColorLUT = { ...labelColorLUT };
            if (!Object.keys(oarLabelColorLUT).length) oarLabelColorLUT = { ...labelColorLUT };
            labelColorLUT = oarLabelColorLUT;
            const ctvLabelMapRaw = res.headers.get('X-CTV-Label-Map');
            if (ctvLabelMapRaw) {
                try { window._ctvLabelMap = JSON.parse(ctvLabelMapRaw); } catch(e) { window._ctvLabelMap = {}; }
            }
            const ctvObjectMapRaw = res.headers.get('X-CTV-Object-Map');
            if (ctvObjectMapRaw) {
                try { window._ctvObjectMap = JSON.parse(ctvObjectMapRaw); } catch(e) { window._ctvObjectMap = {}; }
            }
            const structureVersion = Number(res.headers.get('X-Structure-Version') || 0);
            window._structureVersion = structureVersion;
            try {
                organMetaFromServer = JSON.parse(res.headers.get('X-Organ-Meta') || '{}');
            } catch (error) {
                console.warn('[viewer] Invalid OAR metadata header:', error);
                organMetaFromServer = {};
            }

            const buffer = request.data;
            if (!(buffer instanceof ArrayBuffer) || buffer.byteLength === 0) {
                uiDebugLog('Label volume response was empty');
                return false;
            }
            if (!_viewerDataScopeIsCurrent(scope)) return false;
            allBytes = new Uint8Array(buffer);

            // Async cache write
            if (sid && window.SessionCache) {
                const hdr = JSON.stringify({
                    formatVersion: 5,
                    z: shapeZ, y: shapeY, x: shapeX,
                    hasCTV: hasCTV, hasOAR: hasOAR,
                    ctvSize: ctvSize, oarSize: oarSize,
                    ctvBytesPerVoxel: ctvBytesPerVoxel,
                    oarBytesPerVoxel: oarBytesPerVoxel,
                    oarSource: oarSource || '',
                    colorLUT: labelColorLUT,
                    ctvColorLUT: ctvLabelColorLUT,
                    oarColorLUT: oarLabelColorLUT,
                    ctvLabelMap: window._ctvLabelMap || {},
                    ctvObjectMap: window._ctvObjectMap || {},
                    organMeta: organMetaFromServer,
                    structureVersion,
                });
                const hdrBytes = new TextEncoder().encode(hdr);
                const hdrLenBuf = new ArrayBuffer(4);
                new DataView(hdrLenBuf).setInt32(0, hdrBytes.length, true);
                const cached = new Uint8Array(4 + hdrBytes.length + allBytes.byteLength);
                cached.set(new Uint8Array(hdrLenBuf), 0);
                cached.set(hdrBytes, 4);
                cached.set(allBytes, 4 + hdrBytes.length);
                window.SessionCache.put(sid, 'labels', 'volume', cached.buffer).catch(function(){});
            }
        } catch (e) {
            console.error('Failed to load label volumes:', e);
            return;
        }
    } else {
        // Restore headers from cache
        labelColorLUT = cachedColorLUT || {};
        ctvLabelColorLUT = cachedCtvColorLUT || cachedColorLUT || {};
        oarLabelColorLUT = cachedOarColorLUT || cachedColorLUT || {};
        labelColorLUT = oarLabelColorLUT;
        if (cachedCtvLabelMap) window._ctvLabelMap = cachedCtvLabelMap;
        if (cachedCtvObjectMap) window._ctvObjectMap = cachedCtvObjectMap;
        if (cachedOrganMeta) organMetaFromServer = cachedOrganMeta;
        window._structureVersion = cachedStructureVersion;
    }

    // --- post-processing (shared by cache and fetch paths) ---
    // The backend LUT is the single color source for Data Tree, 2D overlays
    // and 3D meshes. Per-label overrides here previously made the OAR tree
    // disagree with the 2D viewer whenever CTV and OAR reused a numeric ID.

    const sliceSize = shapeY * shapeX;
    ctvLabelData = null;
    oarLabelData = null;

    const baseOff = allBytes.byteOffset || 0;
    if (hasCTV && ctvSize > 0) {
        ctvLabelData = ctvBytesPerVoxel === 2
            ? new Uint16Array(allBytes.buffer, baseOff, ctvSize / 2)
            : new Uint8Array(allBytes.buffer, baseOff, ctvSize);
        const expected = shapeZ * sliceSize;
        if (ctvLabelData.length !== expected) {
            console.warn(`CTV label size mismatch: ${ctvLabelData.length} vs expected ${expected}`);
        }
    }

    if (hasOAR && oarSize > 0) {
        const oarByteOffset = baseOff + ctvSize;
        if (oarBytesPerVoxel === 2) {
            // Typed-array offsets must be aligned.  Most CT voxel counts are
            // even, but odd-sized research volumes are valid; copy only in
            // that uncommon case instead of throwing and losing all labels.
            oarLabelData = (oarByteOffset % 2 === 0)
                ? new Uint16Array(allBytes.buffer, oarByteOffset, oarSize / 2)
                : new Uint16Array(
                    allBytes.slice(ctvSize, ctvSize + oarSize).buffer,
                );
        } else {
            oarLabelData = new Uint8Array(allBytes.buffer, oarByteOffset, oarSize);
        }
        const expected = shapeZ * sliceSize;
        if (oarLabelData.length !== expected) {
            console.warn(`OAR label size mismatch: ${oarLabelData.length} vs expected ${expected}`);
        }
    }

    // Headers describe source availability, but only actual non-zero voxels
    // prove that a usable segmentation was decoded for this session.
    hasCTV = !!(ctvLabelData && ctvLabelData.length
        && ctvLabelData.some(value => Number(value) > 0));
    hasOAR = !!(oarLabelData && oarLabelData.length
        && oarLabelData.some(value => Number(value) > 0));

    // A forced reload after a Data Tree mutation is authoritative.  Without
    // this guard, a slower pre-delete response could finish after the fresh
    // response and restore the just-deleted CTV/OAR nodes and overlays.
    if (!_viewerDataScopeIsCurrent(scope)) return false;

    uiDebugLog(`Label volumes loaded: CTV=${hasCTV}, OAR=${hasOAR}, ${Object.keys(labelColorLUT).length} labels`);

    // Update data tree with organ metadata.  Uploaded OAR masks intentionally
    // have no anatomical ontology, so the server may return the binary volume
    // before its optional metadata endpoint is ready.  Derive stable numbered
    // nodes from the already received labels instead of leaving the OAR tree
    // empty until a second refresh (or inventing anatomy names).
    // Build OAR nodes from the union of server ontology metadata and labels
    // actually present in the binary volume. Metadata can be partial during
    // restore; dropping payload-only labels makes 2D and Data Tree disagree.
    if (hasOAR && oarLabelData && oarLabelData.length > 0) {
        const counts = new Map();
        for (let i = 0; i < oarLabelData.length; i += 1) {
            const labelId = Number(oarLabelData[i]);
            if (labelId > 0) counts.set(labelId, (counts.get(labelId) || 0) + 1);
        }
        const organData = {};
        const metadata = organMetaFromServer || {};
        let ordinal = 1;
        for (const [labelId, voxelCount] of [...counts.entries()].sort((a, b) => a[0] - b[0])) {
            const meta = metadata[String(labelId)] || metadata[labelId] || {};
            const metaColor = Array.isArray(meta.color)
                ? `rgb(${meta.color.join(',')})`
                : meta.color;
            organData[String(labelId)] = {
                name: meta.name || (oarSource === 'uploaded_unknown' ? `OAR ${ordinal}` : `OAR ${labelId}`),
                voxel_count: voxelCount,
                object_id: meta.object_id || `structure:oar:${labelId}`,
                color: metaColor || (oarLabelColorLUT[labelId]
                    ? `rgb(${oarLabelColorLUT[labelId].join(',')})`
                    : undefined),
            };
            ordinal += 1;
        }
        if (Object.keys(organData).length > 0) updateOrganList(organData, oarSource);
    }
        // Do not block slice rendering on metadata. Always reconcile the
        // lightweight organs endpoint after the binary payload, even when the
        // payload included a non-empty X-Organ-Meta header. The header can be
        // a partial projection (for example while a restored TotalSegmentator
        // map is still being merged with embedded CTV structures); the
        // session-scoped organs endpoint is the authoritative Data Tree view.
        if (hasOAR) {
            void hydrateOarDataTreeFromServer(scope.dataGeneration, scope.sessionId);
        }
        // Always flip the data tree flags based on what we got, then
        // re-render. This is what makes "CTV/OAR don't show in the
        // data tree" go away — the previous version only re-rendered
        // when organMeta was non-empty, so empty-CT cases (and the
        // very first response from /viewer/label_volume) left the
        // tree with .loaded = false.
        if (typeof dataTreeState !== 'undefined' && dataTreeState.ctv) {
            dataTreeState.ctv.loaded = hasCTV;
            if (hasCTV) {
                dataTreeState.ctv.visible = true;
            } else {
                // A removed final CTV label used to leave its old child node
                // and mesh in the browser even though the server returned an
                // empty label volume.  Clear the derived presentation only;
                // the server remains the source for the next load.
                Object.keys(dataTreeState.ctvLabels || {}).forEach(id => _disposeSceneMesh(id));
                dataTreeState.ctvLabels = {};
                window._ctvObjectMap = {};
                window._ctvLabelMap = {};
                _disposeSceneMesh('ctv');
            }
        }
        if (typeof dataTreeState !== 'undefined' && dataTreeState.oar) {
            dataTreeState.oar.loaded = hasOAR;
            if (hasOAR) {
                if (!state?.viewerSettings?.userConfigured) dataTreeState.oar.visible = true;
            } else {
                (dataTreeState.organs || []).forEach(organ => _disposeSceneMesh(organ.id));
                dataTreeState.organs = [];
                organMetaFromServer = {};
            }
        }
        // Force a re-render of the data tree regardless of metadata.
        try { if (typeof renderDataTree === 'function') renderDataTree(); } catch (_) {}
        // A newly computed segmentation may use the normal overlay defaults.
        // During session restore, however, this function must not overwrite
        // the saved display mode, overlay checkboxes, or Data Tree choices.
        if (_viewerDataScopeIsCurrent(scope)
            && typeof window.scheduleWorkspaceSave === 'function') {
            // Persist the derived Data Tree immediately. The large label
            // array remains in the session-scoped cache and is checkpointed
            // separately, so this does not block the first viewer paint.
            window.scheduleWorkspaceSave('viewer.labels_loaded');
        }
        // A preserve request only preserves a deliberate user preference.
        // Before the user touches the controls, the default case presentation
        // is still CT-only, so a successful segmentation must turn on the
        // standard mask overlay and repaint immediately.  This closes the
        // common race where the server has valid labels but the 2D viewer
        // stays blank until a slice interaction.
        const presentationWasConfigured = !!state?.viewerSettings?.userConfigured;
        if ((hasCTV || hasOAR) && state && state.viewerSettings
            && (!preserveViewerState || !presentationWasConfigured
                || options.resetPresentation === true)) {
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
            if (oarCb) oarCb.checked = true;
        }
        // Preserving viewer state means preserving controls and visibility,
        // not leaving the canvases stale. Use one reconciliation path for
        // Data Tree readiness, default overlay presentation, and all three
        // slice paints. This also guarantees a manual mask import is visible
        // without requiring a later slice interaction.
        reconcileSegmentationViewerState({
            sessionId: scope.sessionId,
            reason: 'label-volume-loaded',
        });
        // Generic/open masks were started in parallel at function entry. Do
        // not issue a second request here: duplicate hydration can race tree
        // rendering and restore an older presentation snapshot.
        return true;
}

/**
 * Hydrate session-owned open BiomedParse masks for the 2D and 3D viewers.
 * The backend remains authoritative for voxels and spatial metadata; the
 * browser stores only presentation state and a transient typed-array cache.
 */
async function hydrateGenericMasksFromServer(scope, retryAttempt = 0) {
    if (!scope || !_viewerDataScopeIsCurrent(scope)) return false;
    const scopeSessionId = String(scope.sessionId || '');
    // A case switch must never reuse another case's binary masks.  A same-case
    // data mutation, however, should retain the volumes of unaffected open
    // masks while the authoritative catalogue removes or replaces only the
    // changed entries.  Clearing the complete cache on every mutation made a
    // Delete action briefly erase unrelated masks and amplified race windows.
    if (genericMaskCatalogSessionId !== scopeSessionId) {
        genericMaskVolumeData = Object.create(null);
        genericMaskCatalogSessionId = scopeSessionId;
    }
    genericMaskCatalogGeneration = scope.dataGeneration;
    try {
        const request = typeof window.fetchViewerJsonWithRetry === 'function'
            ? await window.fetchViewerJsonWithRetry(
                API + '/viewer/generic_masks',
                { headers: _viewerDataHeaders(scope.sessionId) },
                { requestTimeoutMs: 30000, maxWaitMs: 120000 },
            )
            : null;
        if (!request?.response?.ok) {
            throw new Error(
                request?.data?.error || 'Generic mask catalogue request timed out',
            );
        }
        const payload = request.data || {};
        if (!_viewerDataScopeIsCurrent(scope)) return false;
        const entries = Array.isArray(payload.masks) ? payload.masks : [];
        if (Array.isArray(payload.uploads)) dataTreeState.uploadMasks = payload.uploads;
        const ids = new Set(entries.map(entry => String(entry?.mask_id || '')).filter(Boolean));
        state.maskLabels = state.maskLabels || {};
        Object.keys(state.maskLabels).forEach(id => {
            const mask = state.maskLabels[id];
            if (_isGenericSegmentationMask(mask) && !ids.has(id)) {
                _disposeSceneMesh(id);
                delete state.maskLabels[id];
                delete genericMaskVolumeData[id];
            }
        });

        const jobs = entries.map(async metadata => {
            // A Data Tree mutation can finish after this catalogue request but
            // before this per-mask task starts.  Do not recreate a deleted
            // row from that stale catalogue response.
            if (!_viewerDataScopeIsCurrent(scope)) return false;
            const id = String(metadata.mask_id || '').trim();
            if (!id) return false;
            const existing = state.maskLabels[id] || {};
            const serverClassification = String(
                metadata.classification || metadata.moved_to || '',
            ).trim().toLowerCase();
            const nextMask = {
                ...existing,
                ...metadata,
                id,
                mask_id: id,
                serverMaskId: id,
                objectId: metadata.object_id || existing.objectId || `mask:${id}`,
                nodeId: metadata.data_tree_node_id || existing.nodeId || id,
                // Server classification is authoritative.  Retaining a
                // browser-side CTV/OAR value here could make an already
                // removed or reclassified mask reappear under the wrong
                // parent after a delayed hydration callback.
                movedTo: serverClassification || null,
                classification: serverClassification || 'unclassified',
                source: metadata.source || existing.source || 'biomedparse_v2',
                kind: metadata.kind || existing.kind || 'generic_segmentation',
                name: metadata.name || metadata.label || metadata.target || id,
                label: metadata.label || metadata.target || id,
                loaded: false,
                loading: true,
                status: 'loading',
                error: null,
                visible: existing.visible !== false,
                visible2D: existing.visible2D !== false,
                visible3D: existing.visible3D !== false,
                opacity: typeof existing.opacity === 'number'
                    ? existing.opacity
                    : (metadata.kind === 'uploaded_mask_label' ? 0.6 : 0.42),
                color: existing.color || '#f08a5d',
            };
            state.maskLabels[id] = nextMask;

            // Promoted masks are rendered through the authoritative CTV/OAR
            // label volume.  Fetching their standalone binary volume creates
            // a duplicate asynchronous source and, when they are deleted,
            // used to turn the old Data Tree row into a misleading Error row.
            if (!_isOpenGenericMask(nextMask)) {
                delete genericMaskVolumeData[id];
                nextMask.loaded = true;
                nextMask.loading = false;
                nextMask.status = 'ready';
                nextMask.error = null;
                return true;
            }

            const sourceVersion = String(
                metadata.data_version ?? metadata.dataVersion ?? '',
            );
            const cachedVolume = genericMaskVolumeData[id];
            if (cachedVolume && String(cachedVolume.dataVersion ?? '') === sourceVersion) {
                nextMask.loaded = true;
                nextMask.loading = false;
                nextMask.status = 'ready';
                nextMask.error = null;
                nextMask.voxelCount = Number(metadata.voxel_count || nextMask.voxelCount || 0);
                return true;
            }
            try {
                const volumeRequest = typeof window.fetchViewerJsonWithRetry === 'function'
                    ? await window.fetchViewerJsonWithRetry(
                        API + '/viewer/generic_mask_volume?mask_id=' + encodeURIComponent(id),
                        { headers: _viewerDataHeaders(scope.sessionId) },
                        { requestTimeoutMs: 60000, maxWaitMs: 300000, responseType: 'arrayBuffer' },
                    )
                    : null;
                if (!volumeRequest?.response?.ok) {
                    throw new Error(
                        volumeRequest?.data?.error || 'Generic mask volume request timed out',
                    );
                }
                const volumeResponse = volumeRequest.response;
                const shape = [
                    Number(volumeResponse.headers.get('X-Shape-Z')),
                    Number(volumeResponse.headers.get('X-Shape-Y')),
                    Number(volumeResponse.headers.get('X-Shape-X')),
                ];
                const buffer = volumeRequest.data;
                if (!(buffer instanceof ArrayBuffer) || buffer.byteLength === 0) {
                    throw new Error('empty generic mask volume response');
                }
                const expected = shape[0] * shape[1] * shape[2];
                if (!_viewerDataScopeIsCurrent(scope)) return false;
                if (!shape.every(value => Number.isInteger(value) && value > 0)
                    || buffer.byteLength !== expected) {
                    throw new Error('invalid generic mask geometry');
                }
                const parseHeader = (name, fallback) => {
                    try {
                        const value = JSON.parse(volumeResponse.headers.get(name) || '');
                        return Array.isArray(value) ? value : fallback;
                    } catch (_) { return fallback; }
                };
                genericMaskVolumeData[id] = {
                    data: new Uint8Array(buffer),
                    shape,
                    spacing: parseHeader('X-Spacing', metadata.spacing || [1, 1, 1]),
                    origin: parseHeader('X-Origin', metadata.origin || [0, 0, 0]),
                    direction: parseHeader('X-Direction', metadata.direction || [1, 0, 0, 0, 1, 0, 0, 0, 1]),
                    dataVersion: sourceVersion,
                };
                const current = state.maskLabels[id];
                if (current) {
                    current.loaded = true;
                    current.loading = false;
                    current.status = 'ready';
                    current.error = null;
                    current.voxelCount = Number(metadata.voxel_count || current.voxelCount || 0);
                }
                return true;
            } catch (error) {
                // Ignore an aborted/stale request.  It belongs to the old
                // catalogue and must not turn a post-delete node into an
                // error badge in the current tree.
                if (!_viewerDataScopeIsCurrent(scope)) return false;
                const current = state.maskLabels[id];
                if (current) {
                    current.loaded = false;
                    current.loading = false;
                    current.status = 'error';
                    current.error = error?.message || String(error);
                }
                return false;
            }
        });
        await Promise.allSettled(jobs);
        if (!_viewerDataScopeIsCurrent(scope)) return false;
        try { renderDataTree?.(); } catch (_) {}
        try { loadAllSlices?.(); } catch (_) {}
        const ready = entries.filter(entry => {
            const mask = state.maskLabels?.[String(entry?.mask_id || '')];
            // A mask promoted into the effective CTV/OAR Structure Set is
            // reconstructed by the structure-volume path.  Reconstructing its
            // standalone generic mesh as well would create a second scene
            // object that ignores the CTV/OAR parent visibility and opacity.
            return mask?.status === 'ready'
                && _isOpenGenericMask(mask)
                && mask.visible3D !== false;
        });
        if (typeof reconstructOrgan3D === 'function') {
            await Promise.allSettled(ready.map(entry => reconstructOrgan3D(String(entry.mask_id), true)));
        }
        window.scheduleWorkspaceSave?.('viewer.generic_masks_loaded');
        return true;
    } catch (error) {
        console.debug('[viewer] generic mask hydration unavailable:', error);
        return false;
    }
}

window.hydrateGenericMasksFromServer = hydrateGenericMasksFromServer;

// Generic masks stay as independent Segmentation children until the user
// explicitly moves them to CTV/OAR.  A promoted mask is represented by the
// effective label volume and Structure Set, so its standalone mesh/tree row
// must not be rendered a second time on top of that authoritative object.
function _isGenericSegmentationMask(mask) {
    return Boolean(mask && (
        mask.kind === 'generic_segmentation'
        || mask.kind === 'uploaded_mask_label'
        || mask.source === 'biomedparse_v2'
        || mask.source === 'uploaded_mask'
        || mask.upload_mask_id
    ));
}

function _genericMaskClassification(mask) {
    return String(mask?.classification || mask?.movedTo || mask?.moved_to || '')
        .trim().toLowerCase();
}

function _isOpenGenericMask(mask) {
    return _isGenericSegmentationMask(mask)
        && !_genericMaskClassification(mask).match(/^(ctv|oar)$/);
}

// A mask has three identifiers in historical snapshots: its persisted
// mask_id (usually ``mask_x``), a stable backend object id (``mask:mask_x``),
// and, in a few old scene callbacks, the raw DOM id.  Resolve all of them to
// the one browser state entry before touching visibility or mesh state.
function _maskStateEntry(nodeId) {
    const labels = (typeof state !== 'undefined' && state.maskLabels) || {};
    const value = String(nodeId || '');
    const candidates = [value];
    if (value.startsWith('mask:')) candidates.push(value.slice(5));
    if (value.startsWith('mask_')) candidates.push(value.slice(5));
    const key = candidates.find(candidate => Object.prototype.hasOwnProperty.call(labels, candidate));
    return key === undefined ? null : labels[key];
}

function _maskStateKey(nodeId) {
    const labels = (typeof state !== 'undefined' && state.maskLabels) || {};
    const value = String(nodeId || '');
    const candidates = [value];
    if (value.startsWith('mask:')) candidates.push(value.slice(5));
    if (value.startsWith('mask_')) candidates.push(value.slice(5));
    return candidates.find(candidate => Object.prototype.hasOwnProperty.call(labels, candidate)) || value;
}

// A Data Tree mask ID is not required to use the historical mask_* spelling.
// Uploaded label children deliberately use the durable ID emitted by
// uploaded_mask_service.py (upload_mask_<digest>_label_<label>). Use the live
// mask registry as the identity source and keep the two old spellings only for
// snapshots that predate the registry metadata.
function _isDataTreeMaskId(nodeId) {
    const value = String(nodeId || '');
    return value.startsWith('mask_')
        || value.startsWith('mask:')
        || !!_maskStateEntry(value);
}

window.isDataTreeMaskId = _isDataTreeMaskId;
window.getDataTreeMaskState = _maskStateEntry;

function _maskSceneMeshId(nodeId) {
    const mask = _maskStateEntry(nodeId);
    return String(mask?.id || mask?.mask_id || _maskStateKey(nodeId));
}

// Group-level mask actions must use the same ownership rule as the Data Tree:
// ordinary/manual masks belong to "masks", while an open BiomedParse mask
// belongs to "generic_masks" until a real structure transaction promotes it
// to CTV/OAR. Promoted masks are intentionally in neither standalone group.
function _maskBelongsToGroup(category, mask) {
    if (!mask || typeof mask !== 'object') return false;
    if (category === 'upload_masks') {
        return _isOpenGenericMask(mask)
            && (mask.kind === 'uploaded_mask_label'
                || mask.source === 'uploaded_mask'
                || mask.upload_mask_id);
    }
    if (category === 'generic_masks') {
        return _isOpenGenericMask(mask) && !_maskBelongsToGroup('upload_masks', mask);
    }
    if (category === 'masks') return !_isGenericSegmentationMask(mask);
    return false;
}

/**
 * Hydrate the exact skin envelope used by Surgical Guide generation.
 *
 * The binary volume remains outside the serialized UI snapshot; the backend
 * is authoritative and the Data Tree stores only presentation/identity state.
 */
async function loadGuideSkinSurface(options = {}) {
    const scope = _captureViewerDataScope(options.sessionId);
    try {
        const request = await window.fetchViewerJsonWithRetry(
            API + '/viewer/skin_surface_volume',
            { headers: _viewerDataHeaders(scope.sessionId) },
            {
                responseType: 'arrayBuffer',
                requestTimeoutMs: 120000,
                maxWaitMs: 300000,
            },
        );
        const response = request.response;
        if (!response) throw request.error || new Error('Guide skin request timed out');
        if (response.status === 404) {
            if (!_viewerDataScopeIsCurrent(scope)) return false;
            skinSurfaceData = null;
            skinSurfaceShape = null;
            dataTreeState.skin.loaded = false;
            dataTreeState.skin.status = 'not_generated';
            const mesh = scene3D?.meshes?.skin_surface;
            if (mesh) {
                scene3D.scene?.remove(mesh);
                mesh.geometry?.dispose?.();
                mesh.material?.dispose?.();
                delete scene3D.meshes.skin_surface;
            }
            renderDataTree?.();
            loadAllSlices?.();
            return false;
        }
        if (!response.ok) throw new Error(`Guide skin request failed: HTTP ${response.status}`);
        const shape = [
            Number(response.headers.get('X-Shape-Z')),
            Number(response.headers.get('X-Shape-Y')),
            Number(response.headers.get('X-Shape-X')),
        ];
        const buffer = request.data instanceof ArrayBuffer
            ? request.data
            : await response.arrayBuffer();
        if (!_viewerDataScopeIsCurrent(scope)) return false;
        const expected = shape[0] * shape[1] * shape[2];
        if (!shape.every(value => Number.isInteger(value) && value > 0)
            || buffer.byteLength !== expected) {
            throw new Error('Guide skin volume has invalid geometry');
        }
        skinSurfaceData = new Uint8Array(buffer);
        skinSurfaceShape = shape;
        const node = dataTreeState.skin;
        node.id = 'skin_surface';
        node.objectId = response.headers.get('X-Object-ID') || 'skin_surface:guide';
        node.nodeId = response.headers.get('X-Data-Tree-Node-ID') || 'skin_surface';
        node.planningId = response.headers.get('X-Planning-ID') || null;
        node.dataVersion = Number(response.headers.get('X-Data-Version') || 1);
        node.thresholdHu = Number(response.headers.get('X-Threshold-HU') || -300);
        node.voxelCount = Number(response.headers.get('X-Voxel-Count') || 0);
        node.loaded = true;
        node.loading = false;
        node.status = 'ready';
        node.error = null;
        ensureDataTreeNodeMetadata(node, 'skin_surface', 'segmentation');
        renderDataTree?.();
        loadAllSlices?.();
        if (isDataTreeNodeVisible3D(node) && typeof reconstructOrgan3D === 'function') {
            await reconstructOrgan3D('skin_surface', true);
        }
        window.scheduleWorkspaceSave?.('viewer.guide_skin_loaded');
        return true;
    } catch (error) {
        if (_viewerDataScopeIsCurrent(scope)) {
            dataTreeState.skin.loading = false;
            dataTreeState.skin.status = 'error';
            dataTreeState.skin.error = error?.message || String(error);
            renderDataTree?.();
        }
        if (options.userInitiated) addChat?.('error', error?.message || String(error));
        return false;
    }
}

window.loadGuideSkinSurface = loadGuideSkinSurface;

// Segmentation tools finish on the agent worker before every browser-facing
// endpoint has necessarily observed the new label arrays. Keep one
// session-scoped reconciliation job per result so CTV/OAR data reaches the
// Data Tree, all 2D canvases, and the 3D scene without making the chat turn
// wait for mesh extraction.
const _completedSegmentationArtifactJobs = new Map();

function _segmentationLabelsReady(kind) {
    const ctvReady = !!(ctvLabelData && ctvLabelData.length
        && ctvLabelData.some(value => Number(value) > 0));
    const oarReady = !!(oarLabelData && oarLabelData.length
        && oarLabelData.some(value => Number(value) > 0));
    return kind === 'ctv' ? ctvReady : oarReady;
}

window.hydrateCompletedSegmentationArtifacts = function hydrateCompletedSegmentationArtifacts({
    sessionId = null,
    kind = 'ctv',
    reason = 'segmentation-complete',
} = {}) {
    const normalizedKind = kind === 'oar' ? 'oar' : 'ctv';
    const scope = _captureViewerDataScope(sessionId);
    const sid = String(scope.sessionId || '');
    if (!sid || !_viewerDataScopeIsCurrent(scope)) return Promise.resolve({ stale: true });
    const key = `${sid}:${normalizedKind}`;
    if (_completedSegmentationArtifactJobs.has(key)) {
        return _completedSegmentationArtifactJobs.get(key);
    }

    const job = (async () => {
        const treeGroup = normalizedKind === 'ctv' ? dataTreeState.ctv : dataTreeState.oar;
        if (treeGroup) {
            treeGroup.loading = true;
            treeGroup.error = null;
            try { renderDataTree(); } catch (_) {}
        }
        let lastError = null;
        try {
            // A failed first fetch is normally a short publication race, not
            // a failed segmentation. Keep this retry detached from the chat
            // stream and cancel presentation as soon as the case changes.
            for (let attempt = 0; attempt < 8; attempt += 1) {
                if (!_viewerDataScopeIsCurrent(scope)) return { stale: true };
                try {
                    const loaded = await loadLabelVolumes({
                        sessionId: sid,
                        forceFresh: true,
                        preserveViewerState: true,
                        resetPresentation: true,
                    });
                    if (!_viewerDataScopeIsCurrent(scope)) return { stale: true };
                    if (loaded && _segmentationLabelsReady(normalizedKind)) {
                        if (normalizedKind === 'oar') {
                            try { await hydrateOarDataTreeFromServer(scope.dataGeneration, sid); } catch (_) {}
                        }
                        reconcileSegmentationViewerState({ sessionId: sid, reason });
                        try { renderDataTree(); } catch (_) {}
                        if (typeof startSegmentationMeshPrewarm === 'function') {
                            // Mesh extraction is deliberately background work.
                            // It begins immediately and carries the current
                            // result generation, while the user can continue
                            // reviewing the freshly painted 2D structures.
                            startSegmentationMeshPrewarm(normalizedKind, {
                                sessionId: sid,
                                allOAR: normalizedKind === 'oar',
                                force: true,
                                batchSize: 3,
                            });
                        }
                        return { ready: true, kind: normalizedKind };
                    }
                } catch (error) {
                    lastError = error;
                }
                await new Promise(resolve => setTimeout(resolve, 350 + attempt * 150));
            }
            if (_viewerDataScopeIsCurrent(scope) && treeGroup) {
                treeGroup.error = lastError?.message || 'Segmentation labels are not available yet';
            }
            return { ready: false, error: lastError || new Error('Segmentation labels are not available yet') };
        } finally {
            if (_viewerDataScopeIsCurrent(scope) && treeGroup) {
                treeGroup.loading = false;
                try { renderDataTree(); } catch (_) {}
            }
            _completedSegmentationArtifactJobs.delete(key);
        }
    })();
    _completedSegmentationArtifactJobs.set(key, job);
    return job;
};

// Pre-allocate pixel buffer for reuse
let _pixelBuffer = null;
let _imageDataBuffer = null;

function _sourceOverPackedRgba(bgR, bgG, bgB, bgA, fgR, fgG, fgB, fgOpacity) {
    // Keep the hot 512 x 512 raster path allocation-free.  The packed return
    // value represents straight-alpha RGBA in little-endian component order:
    // r | g << 8 | b << 16 | a << 24.  Callers unpack with unsigned shifts.
    const foregroundAlpha = Math.max(0, Math.min(1, Number(fgOpacity) || 0));
    if (foregroundAlpha <= 0) {
        return ((Math.round(bgA) << 24) | (Math.round(bgB) << 16)
            | (Math.round(bgG) << 8) | Math.round(bgR)) >>> 0;
    }
    const backgroundAlpha = Math.max(0, Math.min(1, (Number(bgA) || 0) / 255));
    const outputAlpha = foregroundAlpha + backgroundAlpha * (1 - foregroundAlpha);
    if (outputAlpha <= 0) return 0;
    const outputR = (fgR * foregroundAlpha + bgR * backgroundAlpha * (1 - foregroundAlpha)) / outputAlpha;
    const outputG = (fgG * foregroundAlpha + bgG * backgroundAlpha * (1 - foregroundAlpha)) / outputAlpha;
    const outputB = (fgB * foregroundAlpha + bgB * backgroundAlpha * (1 - foregroundAlpha)) / outputAlpha;
    return ((Math.round(outputAlpha * 255) << 24) | (Math.round(outputB) << 16)
        | (Math.round(outputG) << 8) | Math.round(outputR)) >>> 0;
}

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

            // Segmentation is source-over composited in a stable clinical
            // layer order: OAR first, then CTV.  CTV therefore remains
            // legible wherever it overlaps a semi-transparent OAR.
            if (oarVisible && oarLabelData && oarLabelData.length > flatIdx) {
                const oarVal = oarLabelData[flatIdx];
                if (oarVal > 0) {
                    const visible = !dataTreeState.organs.length ||
                                    dataTreeState.organs.some(o => o.labelId === oarVal && o.visible);
                    if (visible) {
                        const color = oarLabelColorLUT[oarVal] || [200, 200, 200];
                        const opacity = organOpacities[oarVal] !== undefined ? organOpacities[oarVal] : 0.5;
                        const composed = _sourceOverPackedRgba(r, g, b, a, color[0], color[1], color[2], opacity);
                        r = composed & 0xff;
                        g = (composed >>> 8) & 0xff;
                        b = (composed >>> 16) & 0xff;
                        a = composed >>> 24;
                    }
                }
            }

            if (ctvVisible && ctvLabelData && ctvLabelData.length > flatIdx) {
                const ctvVal = ctvLabelData[flatIdx];
                if (ctvVal > 0) {
                    const color = ctvLabelColorLUT[ctvVal] || [255, 48, 76];
                    const opacity = dataTreeState.ctv.opacity ?? 0.7;
                    const composed = _sourceOverPackedRgba(r, g, b, a, color[0], color[1], color[2], opacity);
                    r = composed & 0xff;
                    g = (composed >>> 8) & 0xff;
                    b = (composed >>> 16) & 0xff;
                    a = composed >>> 24;
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

async function _retryLabelVolumeLoad(options, attempt) {
    const maxAttempts = 60;
    if (attempt > maxAttempts) {
        uiDebugLog('Label volume restore timed out; keeping the current viewer state');
        return false;
    }
    await new Promise(resolve => setTimeout(
        resolve,
        Math.max(1000, Math.min(5000, 1000 + attempt * 50)),
    ));
    return loadLabelVolumes({ ...options, _labelVolumeRetryAttempt: attempt });
}

function renderSliceFromVolume(axis, sliceIndex) {
    if (!volumeData || !volumeShape) return;

    if (typeof window.mark2DViewerBaseSliceRequested === 'function') {
        window.mark2DViewerBaseSliceRequested(axis, sliceIndex);
    }

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
    const hasMasks2d = Object.keys(state.maskLabels || {}).some(id => _maskVisibleInTarget(state.maskLabels[id]));
    const hasSkin2d = !!(skinSurfaceData && isDataTreeNodeVisible2D(dataTreeState.skin));
    const showOverlay = (ctvLabelData || oarLabelData || hasMasks2d || hasSkin2d) &&
                        (displayMode === 'overlay' || isLabelOnly || hasMasks2d || hasSkin2d) &&
                        (((isDataTreeNodeVisible2D(dataTreeState.ctv) && state.viewerSettings.showCTV)) ||
                         (isDataTreeNodeVisible2D(dataTreeState.oar) && state.viewerSettings.showOAR) ||
                         hasMasks2d || hasSkin2d);
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

                // The guide skin is a filled 3D envelope, but MPR views show
                // only its one-voxel contour so anatomy remains readable at
                // the deliberately low default opacity.
                if (hasSkin2d && skinSurfaceData.length > flatIdx && skinSurfaceData[flatIdx]) {
                    const neighborOffsets = [-1, 1, -X, X, -labelSliceSize, labelSliceSize];
                    const atBoundary = volX2 === 0 || volX2 === X - 1
                        || volY2 === 0 || volY2 === Y - 1
                        || volZ === 0 || volZ === Z - 1
                        || neighborOffsets.some(offset => !skinSurfaceData[flatIdx + offset]);
                    if (atBoundary) {
                        const hex = dataTreeState.skin.color || '#f2a088';
                        oR = parseInt(hex.slice(1, 3), 16) || 242;
                        oG = parseInt(hex.slice(3, 5), 16) || 160;
                        oB = parseInt(hex.slice(5, 7), 16) || 136;
                        oA = Math.round(Number(dataTreeState.skin.opacity ?? 0.10) * 255);
                    }
                }

                // Manual/threshold masks are the lowest overlay layer. Each
                // visible mask paints its voxels with its own color/opacity.
                const flatKeyBase = `${volX2},${volY2},${volZ}`;
                if (hasMasks2d) {
                    for (const mask of Object.values(state.maskLabels || {})) {
                        if (!_maskVisibleInTarget(mask)) continue;
                        if (mask.movedTo === 'ctv' && !(isDataTreeNodeVisible2D(dataTreeState.ctv) && state.viewerSettings.showCTV)) continue;
                        if (mask.movedTo === 'oar' && !(isDataTreeNodeVisible2D(dataTreeState.oar) && state.viewerSettings.showOAR)) continue;
                        // Threshold masks are represented by their source
                        // metadata instead of millions of string voxel keys.
                        // Evaluate them against the already loaded HU volume
                        // for the current pixel; hand-drawn masks continue to
                        // use their explicit voxel Set.
                        const thresholdMask = mask.kind === 'threshold'
                            && Number.isFinite(Number(mask.threshold));
                        const genericVolume = _isGenericSegmentationMask(mask)
                            ? genericMaskVolumeData[mask.id]
                            : null;
                        const maskHit = thresholdMask
                            ? !!(volumeData && volumeData[flatIdx] > Number(mask.threshold))
                            : genericVolume
                                ? !!(genericVolume.data && genericVolume.data[flatIdx] > 0)
                                : !!(mask.voxels && mask.voxels.has(flatKeyBase));
                        if (!maskHit) continue;
                        const hex = mask.color || '#8b5cf6';
                        const mr = parseInt(hex.slice(1, 3), 16) || 139;
                        const mg = parseInt(hex.slice(3, 5), 16) || 92;
                        const mb = parseInt(hex.slice(5, 7), 16) || 246;
                        const opacity = typeof mask.opacity === 'number' ? mask.opacity : 0.6;
                        oR = mr; oG = mg; oB = mb; oA = Math.round(opacity * 255);
                        break;
                    }
                }

                // OAR is composited above open/manual masks and skin.  CTV
                // gets a second source-over pass immediately afterward so it
                // cannot disappear simply because an OAR occupies the same
                // voxel in the displayed slice.
                if (isDataTreeNodeVisible2D(dataTreeState.oar) && state.viewerSettings.showOAR && oarLabelData && oarLabelData.length > flatIdx) {
                    const oarVal = oarLabelData[flatIdx];
                    if (oarVal > 0) {
                        const visible = !dataTreeState.organs.length ||
                                        dataTreeState.organs.some(o => o.labelId === oarVal && isDataTreeNodeVisible2D(o));
                        if (visible) {
                            const color = oarLabelColorLUT[oarVal] || [200, 200, 200];
                            const opacity = organOpacities[oarVal] !== undefined ? organOpacities[oarVal] : 0.5;
                            const composed = _sourceOverPackedRgba(oR, oG, oB, oA, color[0], color[1], color[2], opacity);
                            oR = composed & 0xff;
                            oG = (composed >>> 8) & 0xff;
                            oB = (composed >>> 16) & 0xff;
                            oA = composed >>> 24;
                        }
                    }
                }

                if (isDataTreeNodeVisible2D(dataTreeState.ctv) && state.viewerSettings.showCTV && ctvLabelData && ctvLabelData.length > flatIdx) {
                    const ctvVal = ctvLabelData[flatIdx];
                    if (ctvVal > 0) {
                        const color = ctvLabelColorLUT[ctvVal] || [255, 48, 76];
                            const labelState = dataTreeState.ctvLabels?.[`ctv_${ctvVal}`];
                            const labelVisible = labelState ? isDataTreeNodeVisible2D(labelState) : true;
                            if (labelVisible) {
                                const opacity = dataTreeState.ctv.labelOpacities?.[ctvVal]
                                    ?? labelState?.opacity
                                    ?? dataTreeState.ctv.opacity
                                    ?? 0.7;
                                const composed = _sourceOverPackedRgba(oR, oG, oB, oA, color[0], color[1], color[2], opacity);
                                oR = composed & 0xff;
                                oG = (composed >>> 8) & 0xff;
                                oB = (composed >>> 16) & 0xff;
                                oA = composed >>> 24;
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

    if (typeof window.mark2DViewerBaseSliceRendered === 'function') {
        window.mark2DViewerBaseSliceRendered(axis, sliceIndex);
    } else {
        canvas.dataset.requestedAxis = axis;
        canvas.dataset.requestedSlice = String(sliceIndex);
        canvas.dataset.renderedAxis = axis;
        canvas.dataset.renderedSlice = String(sliceIndex);
    }

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

    const hasGuideProjection = typeof hasSurgicalGuideProjection === 'function'
        && hasSurgicalGuideProjection();
    if ((state.seedsOverlay && ((state.seedsOverlay.seeds || []).length || (state.seedsOverlay.needles || []).length))
        || hasGuideProjection) {
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
    const scope = _captureViewerDataScope();
    const sliceIsCurrent = () => _viewerDataScopeIsCurrent(scope, true)
        && Number(state?.slices?.[axis]) === Number(sliceIndex);

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
            const ctvRequest = await window.fetchViewerJsonWithRetry(API + '/viewer/overlay', {
                    method: 'POST',
                    headers: _viewerDataHeaders(scope.sessionId, { 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ axis, slice_index: sliceIndex, overlay_type: 'ctv', ctv_opacity: dataTreeState.ctv.opacity }),
                }, {
                    requestTimeoutMs: 60000,
                    maxWaitMs: 120000,
                });
            const resCtv = ctvRequest.response;
            if (!sliceIsCurrent()) return;
            if (resCtv?.ok) {
                const d = ctvRequest.data || {};
                if (!sliceIsCurrent()) return;
                if (d.has_mask && d.data) {
                    const img = new Image();
                    await new Promise(r => { img.onload = r; img.src = d.data; });
                    if (!sliceIsCurrent()) return;
                    ctx.drawImage(img, 0, 0, overlayCanvas.width, overlayCanvas.height);
                    hasAnyMask = true;
                }
            }
        }

        if (oarVisible && dataTreeState.organs.length > 0) {
            const visibleOrgans = dataTreeState.organs.filter(o => o.visible).map(o => o.labelId);
            const organOpacities = {};
            dataTreeState.organs.forEach(o => { organOpacities[o.labelId] = o.opacity; });
            const oarRequest = await window.fetchViewerJsonWithRetry(API + '/viewer/overlay', {
                    method: 'POST',
                    headers: _viewerDataHeaders(scope.sessionId, { 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ axis, slice_index: sliceIndex, overlay_type: 'oar', visible_organs: visibleOrgans, organ_opacities: organOpacities, oar_opacity: dataTreeState.oar.opacity }),
                }, {
                    requestTimeoutMs: 60000,
                    maxWaitMs: 120000,
                });
            const resOar = oarRequest.response;
            if (!sliceIsCurrent()) return;
            if (resOar?.ok) {
                const d = oarRequest.data || {};
                if (!sliceIsCurrent()) return;
                if (d.has_mask && d.data) {
                    const img = new Image();
                    await new Promise(r => { img.onload = r; img.src = d.data; });
                    if (!sliceIsCurrent()) return;
                    ctx.drawImage(img, 0, 0, overlayCanvas.width, overlayCanvas.height);
                    hasAnyMask = true;
                }
            }
        }

        if (!sliceIsCurrent()) return;
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
        renderSliceToCanvas(axis, cached, sliceIndex);
        return true;
    }
    return false;
}

async function loadSlice(axis, sliceIndex) {
    if (!state.ctPath) return;
    const scope = _captureViewerDataScope();

    const cached = sliceCache[axis][sliceIndex];
    if (cached) {
        renderSliceToCanvas(axis, cached, sliceIndex);
        return;
    }

    const requestController = new AbortController();
    viewerDataAbortControllers.add(requestController);
    try {
        const request = await window.fetchViewerJsonWithRetry(API + '/viewer/slice', {
                method: 'POST',
                headers: _viewerDataHeaders(scope.sessionId, { 'Content-Type': 'application/json' }),
                body: JSON.stringify({
                    axis: axis,
                    slice_index: sliceIndex,
                    window_center: state.viewerSettings.level,
                    window_width: state.viewerSettings.window,
                    threshold: state.viewerSettings.threshold !== null ? state.viewerSettings.threshold : undefined,
                }),
                signal: requestController.signal,
            }, {
                requestTimeoutMs: 60000,
                maxWaitMs: 120000,
            });
        const res = request.response;

        if (!res?.ok) return;

        const data = request.data || {};
        if (!_viewerDataScopeIsCurrent(scope, true)
            || Number(state?.slices?.[axis]) !== Number(sliceIndex)) return;
        if (data.success) {
            sliceCache[axis][sliceIndex] = data.data;
            renderSliceToCanvas(axis, data.data, sliceIndex);
        }
    } catch (e) {
        if (e?.name !== 'AbortError') console.error('Failed to load slice:', e);
    } finally {
        viewerDataAbortControllers.delete(requestController);
    }
}

async function preloadAxis(axis) {
    const slider = document.getElementById('slider' + capitalize(axis));
    if (!slider) return;
    const scope = _captureViewerDataScope();
    const max = parseInt(slider.max) || 48;
    sliceCache[axis] = {};

    const batchSize = 10;
    for (let start = 0; start < max; start += batchSize) {
        const end = Math.min(start + batchSize, max);
        const promises = [];
        for (let i = start; i < end; i++) {
            promises.push(
                window.fetchViewerJsonWithRetry(API + '/viewer/slice', {
                    method: 'POST',
                    headers: _viewerDataHeaders(scope.sessionId, { 'Content-Type': 'application/json' }),
                    body: JSON.stringify({
                        axis: axis,
                        slice_index: i,
                        window_center: state.viewerSettings.level,
                        window_width: state.viewerSettings.window,
                        threshold: state.viewerSettings.threshold !== null ? state.viewerSettings.threshold : undefined,
                    }),
                }, {
                    requestTimeoutMs: 60000,
                    maxWaitMs: 120000,
                })
                .then(request => request.response?.ok ? request.data : null)
                .then(data => {
                    if (!_viewerDataScopeIsCurrent(scope, true)) return;
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
    if (typeof window.mark2DViewerBaseSliceRequested === 'function') {
        window.mark2DViewerBaseSliceRequested(view, sliceIndex);
    }
    const label = document.getElementById('sliceLabel' + capitalize(view));
    if (label) label.textContent = sliceIndex;
    // Apply the operator's Data Tree opacity before any synchronous CT work
    // or asynchronous dose response can paint this frame. This keeps the
    // existing layer invariant for the complete pointer-drag lifecycle.
    if (typeof applyDoseOverlayLayerOpacity === 'function') {
        applyDoseOverlayLayerOpacity(
            document.getElementById('doseOverlayCanvas' + capitalize(view)),
        );
    }

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
    if (state.seedsOverlay || (typeof hasSurgicalGuideProjection === 'function' && hasSurgicalGuideProjection())) {
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

const WINDOW_LEVEL_PRESETS = Object.freeze({
    soft: { w: 400, l: 40 },
    bone: { w: 2000, l: 400 },
    lung: { w: 1500, l: -600 },
    brain: { w: 80, l: 40 },
});

const DEFAULT_CT_HU_RANGE = Object.freeze([-1024, 3071]);
const WINDOW_LEVEL_MIN_SPAN = 1;

let windowLevelRenderTimer = null;

function _viewerWindowValue(value, fallback) {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0
        ? Math.max(1, Math.round(parsed * 2) / 2)
        : Math.max(1, Math.round((Number(fallback) || 400) * 2) / 2);
}

function _viewerLevelValue(value, fallback) {
    const parsed = Number(value);
    // Half-HU endpoints can produce a quarter-HU midpoint. Preserve it so the
    // dual-handle contract remains exact: L=(upper+lower)/2.
    return Number.isFinite(parsed)
        ? Math.round(parsed * 4) / 4
        : Math.round((Number(fallback) || 40) * 4) / 4;
}

function _windowLevelBounds(windowWidth, windowLevel) {
    const width = _viewerWindowValue(windowWidth, 400);
    const level = _viewerLevelValue(windowLevel, 40);
    return {
        low: level - width / 2,
        high: level + width / 2,
    };
}

function _ctWindowSliderDomain(windowWidth, windowLevel) {
    const bounds = _windowLevelBounds(windowWidth, windowLevel);
    const storedRange = Array.isArray(state?.ctHURange) ? state.ctHURange : [];
    const storedLow = Number(storedRange[0]);
    const storedHigh = Number(storedRange[1]);
    let min = Number.isFinite(storedLow) ? Math.floor(storedLow) : DEFAULT_CT_HU_RANGE[0];
    let max = Number.isFinite(storedHigh) ? Math.ceil(storedHigh) : DEFAULT_CT_HU_RANGE[1];

    // A restored custom window may extend beyond the sampled scalar range.
    // Keep both handles reachable instead of silently clamping that state.
    min = Math.min(min, Math.floor(bounds.low));
    max = Math.max(max, Math.ceil(bounds.high));
    if (max - min < WINDOW_LEVEL_MIN_SPAN) max = min + WINDOW_LEVEL_MIN_SPAN;
    return { min, max };
}

function _formatWindowLevelValue(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return '0';
    if (Number.isInteger(numeric)) return String(numeric);
    if (Number.isInteger(numeric * 2)) return numeric.toFixed(1);
    return numeric.toFixed(2);
}

function _normalizeWindowRange(lowValue, highValue, changedHandle, domain) {
    let low = Number(lowValue);
    let high = Number(highValue);
    if (!Number.isFinite(low) || !Number.isFinite(high)) {
        const current = _windowLevelBounds(state?.viewerSettings?.window, state?.viewerSettings?.level);
        low = current.low;
        high = current.high;
    }

    low = Math.max(domain.min, Math.min(domain.max, low));
    high = Math.max(domain.min, Math.min(domain.max, high));
    if (high - low < WINDOW_LEVEL_MIN_SPAN) {
        if (changedHandle === 'low') {
            low = Math.max(domain.min, high - WINDOW_LEVEL_MIN_SPAN);
        } else {
            high = Math.min(domain.max, low + WINDOW_LEVEL_MIN_SPAN);
        }
    }
    return { low, high };
}

function _updateWindowRangePresentation(control, low, high, domain) {
    if (!control) return;
    const span = Math.max(WINDOW_LEVEL_MIN_SPAN, domain.max - domain.min);
    const lowPercent = Math.max(0, Math.min(100, ((low - domain.min) / span) * 100));
    const highPercent = Math.max(0, Math.min(100, ((high - domain.min) / span) * 100));
    control.style.setProperty('--wl-low-pct', `${lowPercent}%`);
    control.style.setProperty('--wl-high-pct', `${highPercent}%`);

    const windowWidth = high - low;
    const windowLevel = (high + low) / 2;
    const lowOutput = control.querySelector('[data-ct-window-output="low"]');
    const highOutput = control.querySelector('[data-ct-window-output="high"]');
    const summaryOutput = control.querySelector('[data-ct-window-output="summary"]');
    if (lowOutput) lowOutput.textContent = _formatWindowLevelValue(low);
    if (highOutput) highOutput.textContent = _formatWindowLevelValue(high);
    if (summaryOutput) {
        summaryOutput.textContent = `W${_formatWindowLevelValue(windowWidth)} L${_formatWindowLevelValue(windowLevel)}`;
    }

    const lowInput = control.querySelector('[data-ct-window-level="low"]');
    const highInput = control.querySelector('[data-ct-window-level="high"]');
    if (lowInput) lowInput.setAttribute('aria-valuetext', `${_formatWindowLevelValue(low)} HU`);
    if (highInput) highInput.setAttribute('aria-valuetext', `${_formatWindowLevelValue(high)} HU`);
}

function _matchingWindowLevelPreset(windowWidth, windowLevel) {
    return Object.entries(WINDOW_LEVEL_PRESETS).find(([, preset]) => (
        preset.w === windowWidth && preset.l === windowLevel
    ))?.[0] || 'custom';
}

function _syncWindowLevelControls() {
    const settings = state.viewerSettings || {};
    const windowWidth = _viewerWindowValue(settings.window, 400);
    const windowLevel = _viewerLevelValue(settings.level, 40);
    const preset = _matchingWindowLevelPreset(windowWidth, windowLevel);

    const toolbarWindow = document.getElementById('viewerWindow');
    const toolbarLevel = document.getElementById('viewerLevel');
    const toolbarPreset = document.getElementById('windowPreset');
    if (toolbarWindow && document.activeElement !== toolbarWindow) toolbarWindow.value = windowWidth;
    if (toolbarLevel && document.activeElement !== toolbarLevel) toolbarLevel.value = windowLevel;
    if (toolbarPreset) toolbarPreset.value = preset;

    // The Data Tree is a second control surface for the same Viewer state.
    // Do not store a duplicate W/L value on the CT node; that would drift
    // after Session hydration or a toolbar edit.
    const bounds = _windowLevelBounds(windowWidth, windowLevel);
    const domain = _ctWindowSliderDomain(windowWidth, windowLevel);
    document.querySelectorAll('.ct-window-level-controls').forEach(control => {
        const lowInput = control.querySelector('[data-ct-window-level="low"]');
        const highInput = control.querySelector('[data-ct-window-level="high"]');
        [lowInput, highInput].forEach(input => {
            if (!input) return;
            input.min = domain.min;
            input.max = domain.max;
        });
        if (lowInput) lowInput.value = bounds.low;
        if (highInput) highInput.value = bounds.high;
        _updateWindowRangePresentation(control, bounds.low, bounds.high, domain);
    });
}

function _renderWindowLevelSlices(delayMs = 0) {
    if (!state.ctLoaded) return;
    clearTimeout(windowLevelRenderTimer);
    if (delayMs > 0) {
        windowLevelRenderTimer = setTimeout(() => {
            windowLevelRenderTimer = null;
            if (state.ctLoaded) {
                clearSliceCache();
                loadAllSlices();
            }
        }, delayMs);
        return;
    }
    clearSliceCache();
    loadAllSlices();
}

function setViewerWindowLevel(windowWidth, windowLevel, options = {}) {
    state.viewerSettings = state.viewerSettings || {};
    const nextWindow = _viewerWindowValue(windowWidth, state.viewerSettings.window);
    const nextLevel = _viewerLevelValue(windowLevel, state.viewerSettings.level);
    const changed = nextWindow !== Number(state.viewerSettings.window)
        || nextLevel !== Number(state.viewerSettings.level);
    state.viewerSettings.window = nextWindow;
    state.viewerSettings.level = nextLevel;
    if (options.userConfigured !== false) state.viewerSettings.userConfigured = true;
    _syncWindowLevelControls();
    if (changed || options.forceRender) {
        _renderWindowLevelSlices(Number(options.renderDelayMs) || 0);
    }
    if ((changed || options.persistOnNoChange) && options.persist !== false
        && typeof window.scheduleWorkspaceSave === 'function') {
        window.scheduleWorkspaceSave(options.reason || 'viewer.window_level');
    }
    return { window: nextWindow, level: nextLevel, changed };
}

function applyViewerSettings() {
    const windowWidth = document.getElementById('viewerWindow')?.value;
    const windowLevel = document.getElementById('viewerLevel')?.value;
    return setViewerWindowLevel(windowWidth, windowLevel, {
        reason: 'viewer.window_level.toolbar',
    });
}

function applyDataTreeWindowRange(changedHandle, persist = false) {
    const lowInput = document.getElementById('dataTreeWindowLow');
    const highInput = document.getElementById('dataTreeWindowHigh');
    if (!lowInput || !highInput) return null;

    const domain = {
        min: Number(lowInput.min),
        max: Number(lowInput.max),
    };
    const normalized = _normalizeWindowRange(lowInput.value, highInput.value, changedHandle, domain);
    lowInput.value = normalized.low;
    highInput.value = normalized.high;
    _updateWindowRangePresentation(
        lowInput.closest('.ct-window-level-controls'),
        normalized.low,
        normalized.high,
        domain,
    );

    return setViewerWindowLevel(
        normalized.high - normalized.low,
        (normalized.high + normalized.low) / 2,
        {
            // Input events can arrive faster than a three-plane MPR render. A
            // one-frame debounce keeps the Viewer live without building a queue.
            renderDelayMs: 16,
            persist,
            persistOnNoChange: persist,
            reason: 'viewer.window_level.data_tree',
        },
    );
}
window.applyDataTreeWindowRange = applyDataTreeWindowRange;

function applyWindowPreset() {
    const preset = document.getElementById('windowPreset')?.value;
    applyWindowPresetByName(preset);
}

function applyWindowPresetByName(preset) {
    const selected = WINDOW_LEVEL_PRESETS[preset];
    if (!selected) {
        _syncWindowLevelControls();
        return;
    }
    setViewerWindowLevel(selected.w, selected.l, {
        reason: 'viewer.window_level.preset',
    });
}

async function syncViewerState() {
    if (!state.ctLoaded) return;
    const scope = _captureViewerDataScope();
    try {
        const res = await fetch(API + '/viewer/control', {
            method: 'POST',
            headers: _viewerDataHeaders(scope.sessionId, { 'Content-Type': 'application/json' }),
            body: JSON.stringify({ action: 'get_state' }),
        });
        if (!res.ok) return;
        const data = await res.json();
        if (!_viewerDataScopeIsCurrent(scope, true)) return;
        if (!data.success) return;

        const s = data;
        const changed = {};

        const hasWindow = Number.isFinite(Number(s.window));
        const hasLevel = Number.isFinite(Number(s.level));
        if (hasWindow || hasLevel) {
            const updated = setViewerWindowLevel(
                hasWindow ? s.window : state.viewerSettings.window,
                hasLevel ? s.level : state.viewerSettings.level,
                { persist: false, userConfigured: false },
            );
            if (updated.changed) {
                changed.window = hasWindow;
                changed.level = hasLevel;
            }
        }
        if (s.threshold !== undefined && s.threshold !== state.viewerSettings.threshold) {
            state.viewerSettings.threshold = s.threshold;
            document.getElementById('viewerThreshold').value = s.threshold;
            changed.threshold = true;
        }
        // Don't sync slice positions - frontend is source of truth
        // (Server doesn't store them unless navigate_slice is called)

        if (Object.keys(changed).length > 0) _syncWindowLevelControls();
    } catch (e) {
        // Ignore sync errors
    }
}

let _thresholdApplyGeneration = 0;

function _setThresholdApplyBusy(active, message = '') {
    const button = document.getElementById('viewerThresholdApply');
    if (!button) return;
    button.setAttribute('aria-busy', active ? 'true' : 'false');
    button.disabled = !!active;
    if (message) button.title = message;
}

function _yieldViewerWork() {
    return new Promise(resolve => {
        // Two scheduling turns are intentional: the first lets the browser
        // paint the busy state, the second prevents a large CT scan from
        // monopolising the main thread immediately after the click.
        const raf = typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function'
            ? window.requestAnimationFrame.bind(window)
            : callback => setTimeout(callback, 0);
        raf(() => setTimeout(resolve, 0));
    });
}

async function _countThresholdVoxels(threshold, generation) {
    if (!volumeData || !volumeShape) return 0;
    const source = volumeData;
    let count = 0;
    const chunkSize = 250000;
    for (let start = 0; start < source.length; start += chunkSize) {
        if (generation !== _thresholdApplyGeneration || source !== volumeData) return null;
        const end = Math.min(source.length, start + chunkSize);
        for (let index = start; index < end; index += 1) {
            if (source[index] > threshold) count += 1;
        }
        if (end < source.length) await _yieldViewerWork();
    }
    return count;
}

async function applyThreshold() {
    const generation = ++_thresholdApplyGeneration;
    const raw = document.getElementById('viewerThreshold')?.value?.trim() || '';
    const threshold = raw === '' ? null : Number(raw);
    const normalizedThreshold = Number.isFinite(threshold) ? threshold : null;
    state.viewerSettings.threshold = normalizedThreshold;
    _setThresholdApplyBusy(true, normalizedThreshold === null ? 'Clearing threshold mask...' : 'Building threshold mask...');

    try {
        await _yieldViewerWork();
        if (generation !== _thresholdApplyGeneration) return;

        if (state.ctLoaded) {
            clearSliceCache();
        }

        const id = 'mask_threshold';
        if (normalizedThreshold === null || !volumeData || !volumeShape) {
            if (state.maskLabels?.[id] && typeof deleteDataTreeMask === 'function') {
                deleteDataTreeMask(id);
            } else if (state.maskLabels) {
                delete state.maskLabels[id];
                renderDataTree();
            }
            await loadAllSlices();
            _scheduleDataTreeSave('mask.threshold.clear');
            return;
        }

        // A threshold mask is a real, case-owned visual data node, but its
        // voxels are derived from the immutable CT. Storing the threshold and
        // count rather than millions of `"x,y,z"` strings keeps Apply,
        // persistence, and session hydration responsive without changing the
        // actual 2D mask semantics.
        if (!state.maskLabels) state.maskLabels = {};
        const existing = state.maskLabels[id] || {};
        const mask = state.maskLabels[id] = {
            ...existing,
            id,
            objectId: existing.objectId || 'mask:threshold',
            name: existing.name || _dtText(`全身皮肤阈值 ${normalizedThreshold} HU`, `Skin threshold ${normalizedThreshold} HU`),
            label: existing.label || _dtText(`全身皮肤阈值 ${normalizedThreshold} HU`, `Skin threshold ${normalizedThreshold} HU`),
            type: 'mask',
            source: 'viewer_threshold',
            kind: 'threshold',
            threshold: normalizedThreshold,
            voxels: null,
            voxelCount: null,
            status: 'loading',
            loading: true,
            error: null,
            color: existing.color || '#8b5cf6',
            visible: existing.visible !== false,
            visible2D: existing.visible2D !== false,
            visible3D: existing.visible3D !== false,
            opacity: typeof existing.opacity === 'number' ? existing.opacity : 0.5,
            axis: 'axial',
            sessionId: _viewerDataSessionId(),
        };
        // Start the real 3D surface request immediately. It is independent of
        // the metadata count and runs while the count yields to the browser.
        const reconstruction = typeof reconstructOrgan3D === 'function'
            ? reconstructOrgan3D(id)
            : Promise.resolve(null);
        renderDataTree();
        // Render after the node exists so the current CT slice can use the
        // same threshold metadata as the Data Tree and 3D reconstruction.
        // The 3D request is already in flight while the three MPR planes
        // yield between paints.
        await loadAllSlices();
        requestViewerVisualRefresh('mask-threshold-start');
        _scheduleDataTreeSave('mask.threshold.start');
        const voxelCount = await _countThresholdVoxels(normalizedThreshold, generation);
        if (generation !== _thresholdApplyGeneration || voxelCount === null) return;
        if (voxelCount === 0) {
            delete state.maskLabels[id];
            renderDataTree();
            reloadOverlays();
            addChat('error', _dtText(
                '当前阈值没有生成任何区域，请调整 HU 阈值后重试。',
                'The threshold produced an empty mask. Choose a lower or higher HU value.',
            ));
            return;
        }
        mask.voxelCount = voxelCount;
        mask.status = 'ready';
        mask.loading = false;
        renderDataTree();
        _scheduleDataTreeSave('mask.threshold.ready');
        await reconstruction;
        if (generation === _thresholdApplyGeneration) {
            const hasMesh = typeof scene3D !== 'undefined' && !!scene3D?.meshes?.[id];
            mask.status = hasMesh ? 'ready' : (mask.status || 'ready');
            mask.loading = false;
            renderDataTree();
            _scheduleDataTreeSave('mask.threshold.mesh');
        }
    } catch (error) {
        if (generation !== _thresholdApplyGeneration) return;
        const mask = state.maskLabels?.mask_threshold;
        if (mask) {
            mask.loading = false;
            mask.status = 'error';
            mask.error = error?.message || String(error);
        }
        renderDataTree();
        addChat('error', _dtText(
            `阈值掩膜生成失败：${error?.message || error}`,
            `Threshold mask failed: ${error?.message || error}`,
        ));
    } finally {
        if (generation === _thresholdApplyGeneration) _setThresholdApplyBusy(false);
    }
}

function toggleOverlay() {
    if (state.viewerSettings) state.viewerSettings.userConfigured = true;
    state.viewerSettings.showCTV = document.getElementById('overlayCTV').checked;
    state.viewerSettings.showOAR = document.getElementById('overlayOAR').checked;
    // Sync with data tree
    dataTreeState.ctv.visible = state.viewerSettings.showCTV;
    dataTreeState.oar.visible = state.viewerSettings.showOAR;
    renderDataTree();
    if (state.ctLoaded) loadAllSlices();
}

function setDisplayMode() {
    if (state.viewerSettings) state.viewerSettings.userConfigured = true;
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
const STRUCTURE_PALETTE_VERSION = 2;
const DEFAULT_CTV_STRUCTURE_COLOR = '#ff304c';
const DEFAULT_OAR_STRUCTURE_COLOR = '#4d9de0';
const DEFAULT_NON_TRAVERSABLE_COLOR = '#e58a48';
const DEFAULT_TRAVERSABLE_COLOR = '#3ccb8f';
const dataTreeState = {
    structurePaletteVersion: STRUCTURE_PALETTE_VERSION,
    // Expansion is session-scoped UI state, not transient DOM state.
    expansionState: {},
    ct:       { visible: true, opacity: 1.0, color: '#888', loaded: false, label: 'CT Image' },
    ctv:      { visible: true, opacity: 0.7, color: DEFAULT_CTV_STRUCTURE_COLOR, loaded: false, label: 'CTV Mask' },
    oar:      { visible: true, opacity: 0.5, color: DEFAULT_OAR_STRUCTURE_COLOR, loaded: false, label: 'All OARs' },
    skin:     {
        id: 'skin_surface', objectId: 'skin_surface:guide', visible: true,
        visible2D: true, visible3D: true, opacity: 0.10, color: '#f2a088',
        loaded: false, label: 'Guide skin surface', status: 'not_generated',
    },
    // Provenance controls whether previous user-edited categories may be
    // carried across a mask replacement. Uploaded unknown labels start as
    // numbered traversable OARs; they must not inherit an old ontology.
    oarSource: '',
    // CTV auxiliary labels (vessels, bone, or model-specific structures)
    // live under the CTV branch. They are deliberately separate from the OAR
    // collection so uploaded OAR masks cannot be confused with CTV labels.
    ctvLabels: {},
    organs:   [],  // Individual organs: [{id, label, color, visible, opacity, voxelCount, category}]
    dose:     { visible: true, opacity: 0.4, color: '#f59e0b', loaded: false, label: 'Dose Distribution' },
    seeds:    { visible: true, opacity: 1.0, color: '#ffcc00', loaded: false, label: 'Seed Positions' },
    needles:  { visible: true, opacity: 0.8, color: '#ff6644', loaded: false, label: 'Needle Paths' },
    // Planning state
    planning: {
        id: null,
        // Planning is versioned at the session level.  ``runs`` contains
        // compact registry rows; only the active run's clinical arrays are
        // loaded into the fields below.  Switching a row performs an
        // authenticated backend activation and then refreshes these fields,
        // so the tree never pretends that an unloaded historical run is
        // already present in the current Viewer scene.
        activePlanningId: null,
        runs: [],
        label: null,
        status: null,
        dataVersion: 0,
        version: 0,
        visible: true,
        // `visible` is also the Planning master switch.  Keep an explicit
        // marker so a compact restart snapshot (which has the placeholder
        // Planning node but none of the restored clinical children) cannot
        // be mistaken for an operator's deliberate hide action.
        visibilityConfigured: false,
        opacity: 1.0,
        color: '#60a5fa',
        artifactStatus: {},
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
        // Runtime-created visual artifacts are registered here as control
        // nodes, while their large arrays/meshes remain in the owning store.
        doseOverlay: null,
        dvh: null,
    },
    annotations: [],
    // Durable non-visual artifacts are hydrated from the backend catalog.
    // Geometry remains in its owning stores; these rows expose the same
    // stable Object IDs to Delete/Export without inventing UI-only records.
    exportArtifacts: [],
};

let _dataTreeArtifactCatalogSession = '';
let _dataTreeArtifactCatalogPromise = null;

async function hydrateDataTreeArtifactCatalog({ force = false } = {}) {
    const sessionId = _viewerDataSessionId();
    if (!sessionId) {
        dataTreeState.exportArtifacts = [];
        _dataTreeArtifactCatalogSession = '';
        return [];
    }
    if (!force && _dataTreeArtifactCatalogSession === sessionId) {
        return dataTreeState.exportArtifacts;
    }
    if (
        !force
        && _dataTreeArtifactCatalogPromise
        && _dataTreeArtifactCatalogPromise.sessionId === sessionId
    ) {
        return _dataTreeArtifactCatalogPromise.promise;
    }
    if (_dataTreeArtifactCatalogSession !== sessionId) {
        dataTreeState.exportArtifacts = [];
    }
    const promise = (async () => {
        try {
            const response = await fetch(API + '/data/catalog', {
                headers: _viewerDataHeaders(sessionId),
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || payload.success === false) {
                throw new Error(payload.error || 'Data catalog is unavailable');
            }
            if (sessionId !== _viewerDataSessionId()) return [];
            const rows = (payload.objects || [])
                .filter(item => ['report_data', 'report', 'report_figure', 'screenshot'].includes(
                    String(item?.data_type || ''),
                ))
                .map((item, index) => ensureDataTreeNodeMetadata({
                    id: `artifact_${index + 1}`,
                    objectId: String(item.object_id),
                    label: String(item.name || item.object_id),
                    dataType: String(item.data_type),
                    parentId: 'artifacts',
                    loaded: true,
                    visible: true,
                    opacity: 1,
                    color: ['screenshot', 'report_figure'].includes(item.data_type)
                        ? '#38bdf8' : '#a78bfa',
                    planningId: item.planning_id,
                    dataVersion: item.data_version,
                    status: item.status || 'ready',
                    error: item.error || null,
                    // Report recovery needs the capture contract in addition
                    // to the stable filename axis.  Keep this small public
                    // metadata bundle on the node; it contains no file path.
                    viewMetadata: item.metadata?.view_metadata || item.metadata || {},
                }, String(item.data_type), 'artifacts'));
            dataTreeState.exportArtifacts = rows;
            _dataTreeArtifactCatalogSession = sessionId;
            renderDataTree();
            return rows;
        } catch (error) {
            if (sessionId === _viewerDataSessionId()) {
                console.warn('[data-tree] artifact catalog hydration failed', error);
            }
            return [];
        } finally {
            if (_dataTreeArtifactCatalogPromise?.sessionId === sessionId) {
                _dataTreeArtifactCatalogPromise = null;
            }
        }
    })();
    _dataTreeArtifactCatalogPromise = { sessionId, promise };
    return promise;
}

/**
 * Add the stable identity/control contract shared by every Data Tree node.
 * Viewer code may keep geometry in specialized stores, but it must never
 * create a visible object without a corresponding node carrying this scope.
 */
function ensureDataTreeNodeMetadata(node, type, parentId = null) {
    if (!node || typeof node !== 'object') return node;
    const sessionId = String(
        (typeof activeSessionId !== 'undefined' && activeSessionId)
        || state?.sessionId || 'web',
    );
    const planningId = node.planningId ?? node.planning_id
        ?? dataTreeState.planning?.id ?? null;
    node.id = String(node.id || node.nodeId || `${type}_${sessionId}`);
    node.nodeId = String(node.nodeId || node.id);
    node.objectId = String(node.objectId || node.id);
    node.type = String(node.type || type);
    node.parentId = node.parentId ?? parentId;
    node.sessionId = sessionId;
    node.caseId = String(node.caseId || state?.caseId || sessionId);
    node.planningId = planningId == null ? null : String(planningId);
    node.dataVersion = Number.isFinite(Number(node.dataVersion))
        ? Number(node.dataVersion)
        : Number(node.version ?? dataTreeState.planning?.version ?? 0);
    node.loading = !!node.loading;
    node.error = node.error || null;
    const explicitStatus = String(node.status || '').toLowerCase();
    // 'ready' is authoritative and must not be downgraded to 'not_generated'
    // merely because the node lacks a `loaded` flag (planning meshes such as
    // the surgical guide carry status 'ready' without a `loaded` field).
    node.status = node.error ? 'error'
        : node.loading ? 'loading'
        : ['expired', 'stale'].includes(explicitStatus) ? explicitStatus
        : (node.loaded || explicitStatus === 'ready') ? 'ready' : 'not_generated';
    node.contextActions = Array.isArray(node.contextActions)
        ? node.contextActions
        : ['toggle_visibility', 'set_opacity', 'set_color', 'reconstruct3d'];
    // `visible` remains the backward-compatible master switch.  View-specific
    // state lets an operator keep the same real object in the 2D MPR views,
    // the 3D scene, or both without changing its colour/opacity contract.
    node.visible2D = node.visible2D !== false;
    node.visible3D = node.visible3D !== false;
    return node;
}

function isDataTreeNodeVisible2D(node) {
    return !!node
        && node.visible !== false
        && node.visible2D !== false
        && (!_isPlanningDescendantNode(node) || _planningViewVisible('2d'));
}

function isDataTreeNodeVisible3D(node) {
    return !!node
        && node.visible !== false
        && node.visible3D !== false
        && (!_isPlanningDescendantNode(node) || _planningViewVisible('3d'));
}

window.isDataTreeNodeVisible2D = isDataTreeNodeVisible2D;
window.isDataTreeNodeVisible3D = isDataTreeNodeVisible3D;

function reconcileDataTreeVisualNodes() {
    const roots = [
        ['ct', dataTreeState.ct, 'image', null],
        ['ctv', dataTreeState.ctv, 'segmentation', 'segmentation'],
        ['oar', dataTreeState.oar, 'segmentation', 'segmentation'],
        ['skin_surface', dataTreeState.skin, 'skin_surface', 'segmentation'],
        ['dose', dataTreeState.dose, 'dose', 'planning'],
        ['seeds', dataTreeState.seeds, 'seed_collection', 'planning'],
        ['needles', dataTreeState.needles, 'needle_collection', 'planning'],
        ['planning', dataTreeState.planning, 'planning', null],
    ];
    roots.forEach(([id, node, type, parent]) => {
        if (node) { node.id = node.id || id; ensureDataTreeNodeMetadata(node, type, parent); }
    });
    (dataTreeState.organs || []).forEach(node => ensureDataTreeNodeMetadata(node, 'oar_mask', 'oar'));
    Object.values(dataTreeState.ctvLabels || {}).forEach(node => ensureDataTreeNodeMetadata(node, 'ctv_label', 'ctv'));
    (dataTreeState.planning?.trajectories || []).forEach(node => ensureDataTreeNodeMetadata(node, 'trajectory', 'planning'));
    (dataTreeState.planning?.seeds || []).forEach(node => ensureDataTreeNodeMetadata(node, 'seed', node.trajectory_id || 'planning'));
    (dataTreeState.planning?.needles || []).forEach(node => ensureDataTreeNodeMetadata(node, 'needle', node.trajectory_id || 'planning'));
    (dataTreeState.planning?.doseLevels || []).forEach(node => {
        node.id = node.id || `dose_iso_${node.threshold}`;
        ensureDataTreeNodeMetadata(node, 'dose_iso_surface', 'planning');
    });
    (dataTreeState.planning?.meshes || []).forEach(node => ensureDataTreeNodeMetadata(node, node.source || 'planning_mesh', 'planning'));
    (dataTreeState.exportArtifacts || []).forEach(node => ensureDataTreeNodeMetadata(
        node, node.dataType || node.type || 'artifact', 'artifacts',
    ));

    const overlay = state?.doseOverlay?.shape ? state.doseOverlay : null;
    dataTreeState.planning.doseOverlay = overlay
        ? ensureDataTreeNodeMetadata({
            ...(dataTreeState.planning.doseOverlay || {}), id: 'dose_overlay',
            label: 'Dose overlay (2D)',
            // state.doseOverlay.visible is the active canvas switch. Preserve
            // the Data Tree master switch so a 2D-only hide is not mistaken
            // for deletion of the underlying dose result at the next refresh.
            visible: dataTreeState.planning.doseOverlay?.visible !== false,
            visible2D: dataTreeState.planning.doseOverlay?.visible2D
                ?? overlay.visible2D ?? overlay.visible !== false,
            // The dose grid has no standalone 3D mesh; dose iso-surfaces are
            // the 3D representation and keep their own node state.
            visible3D: false,
            // Per-view colorbar visibility (toggled from the right-click menu).
            // Preserved on the dose node so a refresh does not reset them.
            colorbarVisible2D: dataTreeState.planning.doseOverlay?.colorbarVisible2D !== false,
            colorbarVisible3D: dataTreeState.planning.doseOverlay?.colorbarVisible3D !== false,
            opacity: typeof getDoseOverlayOpacity === 'function'
                ? getDoseOverlayOpacity()
                : Number(overlay.opacity ?? state.doseOpacity ?? 0.4),
            status: overlay.status || (overlay.doseStale === true ? 'stale' : 'ready'),
            doseStale: overlay.doseStale === true,
            doseSource: overlay.doseSource || 'current_planning',
            doseSourcePlanningId: overlay.doseSourcePlanningId || null,
            color: '#f59e0b', loaded: true,
        }, 'dose_contour_2d', 'planning')
        : null;
    const hasDvhData = !!(state?.dvhData && typeof state.dvhData === 'object'
        && Object.keys(state.dvhData).length > 0);
    dataTreeState.planning.dvh = hasDvhData
        ? ensureDataTreeNodeMetadata({
            ...(dataTreeState.planning.dvh || {}), id: 'dvh', label: 'DVH',
            visible: true, opacity: 1, color: '#60a5fa', loaded: true,
        }, 'dvh', 'planning')
        : null;

    const annotations = Array.isArray(state?.annotations) ? state.annotations : [];
    dataTreeState.annotations = annotations.map((annotation, index) => ensureDataTreeNodeMetadata({
        ...annotation, id: annotation.id || `annotation_${index + 1}`,
        label: annotation.label || annotation.name || `Annotation ${index + 1}`,
        visible: annotation.visible !== false, opacity: annotation.opacity ?? 1,
        color: annotation.color || '#60a5fa', loaded: true,
    }, 'manual_annotation', 'annotations'));

    // Manual edits are persisted as one authoritative artifact-status map on
    // the planning snapshot. Project those statuses back onto the concrete
    // Data Tree nodes so an old Dose/DVH/Guide is never presented as current
    // merely because its binary/mesh payload is still visible. This is a
    // one-way projection; it does not create placeholder data nodes.
    const artifactStatus = dataTreeState.planning?.artifactStatus;
    if (artifactStatus && typeof artifactStatus === 'object') {
        const applyArtifactStatus = (node, key) => {
            if (!node) return;
            const status = String(artifactStatus[key] || '').toLowerCase();
            if (['ready', 'stale', 'expired', 'loading', 'error'].includes(status)) {
                node.status = status;
            }
        };
        applyArtifactStatus(dataTreeState.dose, 'dose');
        applyArtifactStatus(dataTreeState.planning?.doseOverlay, 'dose');
        applyArtifactStatus(dataTreeState.planning?.dvh, 'dvh');
        (dataTreeState.planning?.doseLevels || []).forEach(node => applyArtifactStatus(node, 'dose'));
        (dataTreeState.planning?.meshes || []).forEach(node => {
            if (String(node.source || '').toLowerCase() === 'surgical_guide') {
                applyArtifactStatus(node, 'surgical_guide');
            }
        });
        (dataTreeState.exportArtifacts || []).forEach(node => {
            const type = String(node.dataType || node.type || '').toLowerCase();
            if (type === 'report' || type === 'pdf') applyArtifactStatus(node, 'report');
            if (type.includes('guide')) applyArtifactStatus(node, 'surgical_guide');
            if (type === 'dvh') applyArtifactStatus(node, 'dvh');
        });
    }
}

window.ensureDataTreeNodeMetadata = ensureDataTreeNodeMetadata;
window.reconcileDataTreeVisualNodes = reconcileDataTreeVisualNodes;

function getDataTreeNodeSnapshot() {
    reconcileDataTreeVisualNodes();
    const nodes = [];
    const add = (node) => {
        if (!node || typeof node !== 'object') return;
        nodes.push({
            id: node.id,
            nodeId: node.nodeId,
            objectId: node.objectId,
            type: node.type,
            parentId: node.parentId ?? null,
            sessionId: node.sessionId,
            caseId: node.caseId,
            planningId: node.planningId,
            dataVersion: node.dataVersion,
            status: node.status,
            loading: !!node.loading,
            error: node.error || null,
            visible: node.visible !== false,
            visible2D: node.visible2D !== false,
            visible3D: node.visible3D !== false,
            color: node.color || null,
            opacity: Number.isFinite(Number(node.opacity)) ? Number(node.opacity) : 1,
            label: node.label || node.name || node.id,
            contextActions: Array.isArray(node.contextActions) ? [...node.contextActions] : [],
        });
    };
    [dataTreeState.ct, dataTreeState.ctv, dataTreeState.oar, dataTreeState.skin,
        dataTreeState.dose, dataTreeState.seeds, dataTreeState.needles,
        dataTreeState.planning, dataTreeState.planning?.doseOverlay,
        dataTreeState.planning?.dvh, ...Object.values(dataTreeState.ctvLabels || {}),
        ...(dataTreeState.organs || []),
        ...(dataTreeState.planning?.trajectories || []),
        ...(dataTreeState.planning?.seeds || []),
        ...(dataTreeState.planning?.needles || []),
        ...(dataTreeState.planning?.doseLevels || []),
        ...(dataTreeState.planning?.meshes || []).filter(node => _findDataTreeNode(node.id) === node),
        ...(dataTreeState.annotations || []),
        ...(dataTreeState.exportArtifacts || [])].forEach(add);
    return nodes;
}

window.getDataTreeNodeSnapshot = getDataTreeNodeSnapshot;

/**
 * Reconcile the segmentation control plane and all three slice canvases.
 *
 * Segmentation completion used to update the backend memory and the binary
 * label buffer through separate callbacks.  A late callback could therefore
 * leave a valid mask in memory while the tree still reported "not generated"
 * or the canvases remained in CT-only mode.  This function is deliberately
 * idempotent and session-scoped: it derives readiness from actual non-zero
 * label data, preserves an explicit user display choice, and then repaints
 * every current slice from the same buffers used by the 2D renderer.
 */
function reconcileSegmentationViewerState({ sessionId = null, reason = 'segmentation-reconcile' } = {}) {
    if (sessionId && String(sessionId) !== _viewerDataSessionId()) return false;
    const ctvReady = !!(ctvLabelData && ctvLabelData.length
        && ctvLabelData.some(value => Number(value) > 0));
    const oarReady = !!(oarLabelData && oarLabelData.length
        && oarLabelData.some(value => Number(value) > 0));
    if (typeof dataTreeState !== 'undefined') {
        dataTreeState.ctv.loaded = ctvReady;
        dataTreeState.oar.loaded = oarReady || dataTreeState.organs.length > 0;
        if (ctvReady || oarReady) {
            const configured = !!state?.viewerSettings?.userConfigured;
            if (!configured) {
                state.viewerSettings = state.viewerSettings || {};
                state.viewerSettings.displayMode = 'overlay';
                state.viewerSettings.showCTV = ctvReady;
                state.viewerSettings.showOAR = oarReady;
                const mode = document.getElementById('displayMode');
                if (mode) mode.value = 'overlay';
                const ctv = document.getElementById('overlayCTV');
                if (ctv) ctv.checked = ctvReady;
                const oar = document.getElementById('overlayOAR');
                if (oar) oar.checked = oarReady;
            }
        }
        reconcileDataTreeVisualNodes();
        if (typeof renderDataTree === 'function') renderDataTree();
    }
    if (volumeData && volumeShape && _viewerDataScopeIsCurrent(
        _captureViewerDataScope(sessionId),
    )) {
        ['axial', 'sagittal', 'coronal'].forEach(axis => {
            try { renderSliceFromVolume(axis, state.slices[axis]); } catch (error) {
                console.debug(`[viewer] ${reason} ${axis} repaint failed:`, error);
            }
        });
    }
    requestViewerVisualRefresh(reason);
    return ctvReady || oarReady;
}

window.reconcileSegmentationViewerState = reconcileSegmentationViewerState;

// The Data Tree is the canonical display-state model.  Viewer modes may
// change materials (for example a dose texture), but they must never invent
// a second source of truth for visibility, opacity, or the normal-surface
// color chosen by the user.
function getDataTreeAppearanceForMesh(id, mesh) {
    let item = null;
    if (id === 'ctv') item = dataTreeState.ctv;
    else if (id === 'skin_surface') item = dataTreeState.skin;
    else if (id.startsWith('ctv_')) item = dataTreeState.ctvLabels?.[id] || dataTreeState.ctv;
    else if (id.startsWith('organ_')) item = dataTreeState.organs.find(organ => organ.id === id);
    else if (id.startsWith('seed_')) item = dataTreeState.planning.seeds.find(seed => seed.id === id);
    else if (id.startsWith('needle_') && mesh?.userData?.type !== 'needle_handle') {
        item = dataTreeState.planning.needles.find(needle => needle.id === id);
    } else if (id.startsWith('dose_iso_')) {
        const threshold = Number(id.replace('dose_iso_', ''));
        item = dataTreeState.planning.doseLevels.find(level => Math.abs(Number(level.threshold) - threshold) < 1e-6);
    } else if (_isDataTreeMaskId(id)) {
        item = _maskStateEntry(id);
    } else {
        item = dataTreeState.planning.meshes.find(entry => entry.id === id);
    }
    if (!item) return null;
    // A category is a parent constraint. Child edits remain local in the
    // Data Tree, but a hidden CTV/OAR/Planning parent must hide every
    // descendant mesh, including meshes restored after a mode switch.
    const parentVisible = id === 'skin_surface'
        ? dataTreeState.skin?.visible !== false
        : id.startsWith('organ_')
        ? dataTreeState.oar?.visible !== false
        : (id === 'ctv' || id.startsWith('ctv_'))
            ? dataTreeState.ctv?.visible !== false
            : (id.startsWith('seed_') || id.startsWith('needle_') || id.startsWith('dose_iso_')
                || dataTreeState.planning?.meshes?.some(entry => entry.id === id))
                ? _planningViewVisible('3d')
                : true;
    return {
        // This helper is consumed by the 3D scene synchronizer.  Keep the
        // view-specific flag here as well as in _apply3DNodeVisibility;
        // otherwise a later scene-wide appearance sync can resurrect a skin
        // mesh that the user explicitly hid in 3D.
        visible: parentVisible && item.visible !== false && item.visible3D !== false,
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
    ctv:              { label: 'CTV', icon: '🎯', color: DEFAULT_CTV_STRUCTURE_COLOR },
    non_traversable:  { label: 'Non-traversable', icon: '🚫', color: DEFAULT_NON_TRAVERSABLE_COLOR },
    traversable:      { label: 'Traversable', icon: '✅', color: DEFAULT_TRAVERSABLE_COLOR },
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

// All context menus are fixed to the viewport, so their coordinates must be
// resolved after the menu has been mounted.  The old callers only flipped the
// menu above/left when it crossed the right/bottom edge.  A tall menu opened
// near the bottom could therefore still receive a negative top coordinate and
// become partly unreachable.  Keep the measurement, flip, and final clamp in
// one shared helper so Data Tree, 2D, and 3D menus follow the same rules.
function positionBrachyContextMenu(menu, anchorX, anchorY) {
    if (!menu) return;

    const margin = 8;
    const viewportWidth = Math.max(
        1,
        Number(document.documentElement?.clientWidth) || Number(window.innerWidth) || 1,
    );
    const viewportHeight = Math.max(
        1,
        Number(document.documentElement?.clientHeight) || Number(window.innerHeight) || 1,
    );
    const x = Number.isFinite(Number(anchorX)) ? Number(anchorX) : margin;
    const y = Number.isFinite(Number(anchorY)) ? Number(anchorY) : margin;
    const maxMenuHeight = Math.max(120, viewportHeight - margin * 2);

    const previousVisibility = menu.style.visibility;
    menu.style.visibility = 'hidden';
    menu.style.left = '0px';
    menu.style.top = '0px';
    menu.style.maxHeight = `${maxMenuHeight}px`;
    menu.style.overflowY = 'auto';
    menu.style.overflowX = 'hidden';
    menu.style.overscrollBehavior = 'contain';

    let rect = menu.getBoundingClientRect();
    const maxMenuWidth = Math.max(120, viewportWidth - margin * 2);
    if (rect.width > maxMenuWidth) menu.style.maxWidth = `${maxMenuWidth}px`;
    rect = menu.getBoundingClientRect();

    const maxLeft = Math.max(margin, viewportWidth - rect.width - margin);
    const maxTop = Math.max(margin, viewportHeight - rect.height - margin);
    let left = x;
    let top = y;
    if (left + rect.width > viewportWidth - margin) left = x - rect.width;
    if (top + rect.height > viewportHeight - margin) top = y - rect.height;

    left = Math.min(Math.max(margin, left), maxLeft);
    top = Math.min(Math.max(margin, top), maxTop);
    menu.style.left = `${Math.round(left)}px`;
    menu.style.top = `${Math.round(top)}px`;
    menu.style.visibility = previousVisibility || 'visible';
}

// Other viewer modules are separate scripts and cannot access this file's
// lexical helpers.  Expose only the positioning primitive as the shared
// context-menu contract.
window.positionBrachyContextMenu = positionBrachyContextMenu;

// Context menus are transient UI, not state. A single capture-phase boundary
// closes them for clicks, touch/pointer presses, right-clicks on another
// target, Escape, scrolling, and case switches. Keeping this lifecycle in one
// place is important: the old one-shot bubble listeners installed by each menu
// could run after a new menu had been created and immediately close that new
// menu, making a second right-click appear to do nothing.
if (!window.__brachyContextMenuDismissalBound) {
    window.__brachyContextMenuDismissalBound = true;
    document.addEventListener('pointerdown', event => {
        const menu = activeContextMenu || window.__brachyContextMenuElement;
        if (!menu || menu.contains(event.target)) return;
        hideContextMenu();
    }, true);
    document.addEventListener('click', event => {
        const menu = activeContextMenu || window.__brachyContextMenuElement;
        if (!menu || menu.contains(event.target)) return;
        hideContextMenu();
    }, true);
    document.addEventListener('contextmenu', event => {
        const menu = activeContextMenu || window.__brachyContextMenuElement;
        // Capture-phase dismissal runs before the target's inline handler. It
        // removes the previous menu, then lets the target open its replacement
        // without a delayed document listener closing it again.
        if (!menu || menu.contains(event.target)) return;
        hideContextMenu();
    }, true);
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') hideContextMenu();
    }, true);
    document.addEventListener('scroll', event => {
        const menu = activeContextMenu || window.__brachyContextMenuElement;
        // Scrolling a long menu is an expected interaction.  Only scrolling
        // outside the menu dismisses it.
        if (menu && (event.target === menu || menu.contains?.(event.target))) return;
        hideContextMenu();
    }, true);
}

// Multi-select state (like Windows Explorer)
const selectedItems = new Set();  // Set of organ IDs (e.g., 'organ_1', 'ctv')
let lastClickedId = null;  // For shift+click range selection
// Deletion can trigger a label-volume refresh that takes longer than the
// request itself.  Keep a per-object lock across that whole transaction so a
// second right-click cannot submit a duplicate request against a row that is
// already being removed.
const pendingDataTreeDeleteIds = new Set();

function getSelectableIds() {
    // Return every real leaf node in tree order. Group headers are routed to
    // their own menu and therefore do not participate in range selection.
    const ids = [];
    if (dataTreeState.ct.loaded) ids.push('ct');
    if (dataTreeState.ctv.loaded) {
        const ctvIds = Object.keys(dataTreeState.ctvLabels || {});
        ids.push(...(ctvIds.length ? ctvIds : ['ctv']));
    }
    // The guide skin surface is a first-class segmentation node. Keep it in
    // the selectable leaf list so its context menu uses the same visibility,
    // view-specific, opacity, color, export, and delete paths as other data.
    if (dataTreeState.skin?.loaded) ids.push('skin_surface');
    dataTreeState.organs.forEach(o => ids.push(o.id));
    _planningItems('trajectories').forEach(item => ids.push(item.id));
    _planningItems('seeds').forEach(item => ids.push(item.id));
    _planningItems('needles').forEach(item => ids.push(item.id));
    _planningItems('doseLevels').forEach(item => ids.push(`dose_iso_${item.threshold}`));
    if (dataTreeState.planning?.doseOverlay) ids.push('dose_overlay');
    if (dataTreeState.planning?.dvh) ids.push('dvh');
    _planningItems('meshes').forEach(item => ids.push(item.id));
    (dataTreeState.annotations || []).forEach(item => ids.push(item.id));
    (dataTreeState.exportArtifacts || []).forEach(item => ids.push(item.id));
    Object.keys(state.maskLabels || {}).forEach(id => ids.push(id));
    return ids;
}

// Moderately saturated, 3D-Slicer-inspired fallback colors. The backend LUT remains
// authoritative; this table covers manual/imported structures while metadata
// is still arriving and uses the same ordering as server_support.py.
const ORGAN_COLORS = [
    '#4d9de0', '#3ccb8f', '#a66de0', '#f2b84b', '#2db7c4', '#e77aa8',
    '#7fc843', '#5e8fd8', '#e58a48', '#8b7ddb', '#e3c64f', '#38a6a5',
    '#d66b78', '#63b85c', '#b477d1', '#ed9b72', '#4b88c7', '#c7a83f',
    '#47b9a8', '#d56ab6', '#93b657', '#6978d1', '#d99c5a', '#45a875',
    '#c878a0', '#5fa9d8', '#e28168', '#abb248', '#4ea6b8', '#c96f54',
    '#64bc92', '#a86cc2',
];

// Version 1 used a deliberately pastel palette. Migrate only those exact
// application defaults so saved user-selected colors remain untouched.
const LEGACY_STRUCTURE_COLORS = new Set([
    '#f2a692', '#8cacd9', '#bc9ccc', '#e8c484', '#87bea8', '#da9ab1',
    '#a6bc7f', '#91b8c3', '#cfa386', '#aaa6d1', '#e5b078', '#7fb4be',
    '#c6919b', '#95be8b', '#b8a4c9', '#e1a089', '#82a4cd', '#c9b577',
    '#86c2b8', '#d397c4', '#adbb95', '#969eca', '#dbb999', '#8bb99b',
    '#c49eb2', '#a0b7d3', '#dfaa97', '#b7b57f', '#89afb4', '#cc9784',
    '#9cc5b1', '#be9ac6',
]);

function _normalizeStructureColor(color) {
    if (Array.isArray(color) && color.length >= 3) {
        return `#${color.slice(0, 3)
            .map(channel => Math.max(0, Math.min(255, Number(channel))).toString(16).padStart(2, '0'))
            .join('')}`;
    }
    const value = String(color || '').trim().toLowerCase();
    if (/^#[0-9a-f]{6}$/.test(value)) return value;
    const match = value.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
    if (!match) return value;
    return `#${match.slice(1, 4)
        .map(channel => Math.max(0, Math.min(255, Number(channel))).toString(16).padStart(2, '0'))
        .join('')}`;
}

function _setStructureLutColor(lut, labelId, color) {
    const numericLabel = Number(labelId);
    const normalized = _normalizeStructureColor(color);
    if (!Number.isFinite(numericLabel) || !/^#[0-9a-f]{6}$/.test(normalized)) return false;
    lut[numericLabel] = [
        parseInt(normalized.slice(1, 3), 16),
        parseInt(normalized.slice(3, 5), 16),
        parseInt(normalized.slice(5, 7), 16),
    ];
    return true;
}

function syncStructureColorLUTsFromTree(tree = dataTreeState) {
    if (!tree || typeof tree !== 'object') return;
    const ctvLabels = tree.ctvLabels || tree.ctv_labels || {};
    Object.entries(ctvLabels).forEach(([id, item]) => {
        if (!item) return;
        const labelId = Number(item.labelId ?? item.label_id ?? String(id).replace(/^ctv_/, ''));
        _setStructureLutColor(ctvLabelColorLUT, labelId, item.color);
    });
    (tree.organs || []).forEach(item => {
        if (!item) return;
        _setStructureLutColor(oarLabelColorLUT, item.labelId ?? item.label_id, item.color);
    });
    labelColorLUT = oarLabelColorLUT;
}

window.syncStructureColorLUTsFromTree = syncStructureColorLUTsFromTree;

function _structurePaletteColor(labelId, offset = 0) {
    const numeric = Math.max(1, Math.abs(Number(labelId) || 1));
    const ordinal = numeric - 1 + Number(offset || 0);
    const base = ORGAN_COLORS[ordinal % ORGAN_COLORS.length];
    const cycle = Math.floor(ordinal / ORGAN_COLORS.length);
    if (cycle === 0) return base;
    const factor = [0.84, 1.08, 0.72, 0.94][(cycle - 1) % 4];
    const rgb = [1, 3, 5].map(index => Math.max(
        0,
        Math.min(255, Math.round(parseInt(base.slice(index, index + 2), 16) * factor)),
    ));
    return `#${rgb.map(channel => channel.toString(16).padStart(2, '0')).join('')}`;
}

function migrateLegacyStructurePalette(tree) {
    if (!tree || typeof tree !== 'object') return false;
    if (Number(tree.structurePaletteVersion || 0) >= STRUCTURE_PALETTE_VERSION) return false;

    let changed = false;
    const replaceKnownDefault = (target, legacyColors, replacement) => {
        if (!target || typeof target !== 'object') return;
        const normalized = _normalizeStructureColor(target.color);
        if (legacyColors.has(normalized)) {
            target.color = replacement;
            changed = true;
        }
    };

    replaceKnownDefault(tree.ctv, new Set(['#f2a692', '#ff4444', '#ff6b6b']), DEFAULT_CTV_STRUCTURE_COLOR);
    replaceKnownDefault(tree.oar, new Set(['#8cacd9', '#0ea5e9']), DEFAULT_OAR_STRUCTURE_COLOR);
    replaceKnownDefault(tree.nonTraversable || tree.non_traversable, new Set(['#cfa386', '#fb923c']), DEFAULT_NON_TRAVERSABLE_COLOR);
    replaceKnownDefault(tree.traversable, new Set(['#87bea8', '#0ea5e9']), DEFAULT_TRAVERSABLE_COLOR);

    const ctvLabels = tree.ctvLabels || tree.ctv_labels || {};
    Object.entries(ctvLabels).forEach(([id, label]) => {
        if (!label || !LEGACY_STRUCTURE_COLORS.has(_normalizeStructureColor(label.color))) return;
        const labelId = Number(label.labelId ?? label.label_id ?? String(id).replace(/^ctv_/, '')) || 1;
        label.color = labelId === 1
            ? DEFAULT_CTV_STRUCTURE_COLOR
            : _structurePaletteColor(labelId, 10);
        changed = true;
    });

    (tree.organs || []).forEach((organ, index) => {
        if (!organ || !LEGACY_STRUCTURE_COLORS.has(_normalizeStructureColor(organ.color))) return;
        organ.color = _structurePaletteColor(organ.labelId ?? organ.label_id ?? (index + 1));
        changed = true;
    });

    tree.structurePaletteVersion = STRUCTURE_PALETTE_VERSION;
    syncStructureColorLUTsFromTree(tree);
    return changed;
}

window.migrateLegacyStructurePalette = migrateLegacyStructurePalette;

function updateOrganList(organData, source = '') {
    // organData: {label_id: {name, voxel_count, color?}}
    if (!organData) return;

    // A 202/pending response or a lightweight snapshot can legitimately carry
    // no organ rows while the binary label volume is still hydrating.  An
    // empty update is not an authoritative deletion: clearing the existing
    // array here used to make a successful upload disappear from the Data
    // Tree after a later background refresh.
    const entries = Object.entries(organData).filter(([labelId, info]) => {
        const numericLabel = Number(labelId);
        return Number.isFinite(numericLabel) && numericLabel > 0 && info && typeof info === 'object';
    });
    if (!entries.length) return false;

    // Preserve existing visibility/opacity state
    const existingState = {};
    const existingByObjectId = {};
    // A metadata refresh can omit provenance while the binary label request
    // is still completing. Keep the last confirmed source in that case so an
    // uploaded mask cannot briefly inherit a model ontology.
    const effectiveSource = String(source || dataTreeState.oarSource || '').trim().toLowerCase();
    const sourceChanged = Boolean(
        effectiveSource && dataTreeState.oarSource && effectiveSource !== String(dataTreeState.oarSource).toLowerCase(),
    );
    dataTreeState.organs.forEach(o => {
        if (!sourceChanged) {
            existingState[o.id] = {
                label: o.label,
                objectId: o.objectId,
                visible: o.visible,
                visible2D: o.visible2D,
                visible3D: o.visible3D,
                opacity: o.opacity,
                category: o.category,
                color: o.color,
            };
            if (o.objectId) existingByObjectId[String(o.objectId)] = existingState[o.id];
        }
    });
    // Presentation may be restored before the asynchronous OAR metadata
    // arrives. Apply that deferred map when the authoritative rows are built.
    const pendingPresentation = window.__pendingOarPresentation || {};
    const pendingById = pendingPresentation.byId || {};
    const pendingByLabel = pendingPresentation.byLabel || {};
    if (effectiveSource) dataTreeState.oarSource = effectiveSource;

    dataTreeState.organs = [];
    let i = 0;
    const uploadedUnknownSource = new Set(['uploaded_unknown', 'uploaded', 'manual_upload']).has(effectiveSource);
    for (const [labelId, info] of entries) {
        // An unknown uploaded multi-label mask has no anatomical ontology.
        // Never let a stale cache or a coincidental numeric label turn it into
        // a falsely named artery, stomach, or vessel; users can rename or
        // reclassify these numbered nodes explicitly in the Data Tree.
        const id = `organ_${labelId}`;
        const stableObjectId = String(info.object_id || `structure:oar:${labelId}`);
        const existing = existingByObjectId[stableObjectId] || existingState[id];
        const pending = pendingById[id] || pendingByLabel[String(labelId)] || null;
        const renamed = !sourceChanged && existing?.label
            && !/^OAR\s+\d+$/i.test(String(existing.label).trim())
            ? String(existing.label).trim()
            : '';
        const name = renamed || (uploadedUnknownSource ? `OAR ${i + 1}` : (info.name || `OAR ${i + 1}`));
        const cat = existing?.category || pending?.category || (uploadedUnknownSource ? 'traversable' : classifyOrgan(name));
        const finalColor = existing?.color || pending?.color || info.color || _structurePaletteColor(labelId);
        dataTreeState.organs.push({
            id: id,
            objectId: stableObjectId,
            labelId: parseInt(labelId),
            label: name,
            color: _normalizeStructureColor(finalColor),
            // Start all OARs visible — users can toggle individual organs
            // via the data tree.
            visible: existing?.visible ?? pending?.visible ?? true,
            visible2D: existing?.visible2D ?? pending?.visible2D ?? true,
            visible3D: existing?.visible3D ?? pending?.visible3D ?? true,
            opacity: existing?.opacity ?? pending?.opacity ?? 0.5,
            voxelCount: info.voxel_count || 0,
            category: cat,
            source: 'oar',
        });
        _setStructureLutColor(oarLabelColorLUT, labelId, finalColor);
        i++;
    }
    labelColorLUT = oarLabelColorLUT;
    // Metadata is a control-plane update. Do not rely on every caller to
    // remember a second render; this was the source of successful OAR
    // imports that remained invisible until manual 3D reconstruction.
    dataTreeState.oar.loaded = true;
    if (!state?.viewerSettings?.userConfigured) dataTreeState.oar.visible = true;
    if (typeof renderDataTree === 'function') renderDataTree();
    if (window.__pendingOarPresentation) delete window.__pendingOarPresentation;
    return true;
}

// Apply server-confirmed OAR metadata before the binary label volume arrives.
// This closes the race where the backend has completed segmentation but the
// Data Tree remains empty until a later manual 3D reconstruction request.
window.hydrateOarDataTreeFromPayload = function hydrateOarDataTreeFromPayload(payload, expectedSessionId = null) {
    const scopedSessionId = String(expectedSessionId || '');
    if (scopedSessionId && scopedSessionId !== _viewerDataSessionId()) {
        // A response from a hidden case is valid server data, but it must not
        // repopulate the currently visible case after a session switch.
        return false;
    }
    const data = payload || {};
    const organData = {};
    // `/viewer/organs` returns this normalized object.  Treat it as the
    // preferred source because it can preserve numbered uploaded-mask labels
    // even when the binary volume is still unavailable.  Older manual upload
    // responses only contain organ_counts/label_counts, so retain that
    // compatibility path as a fallback.
    if (data.organs && typeof data.organs === 'object' && !Array.isArray(data.organs)) {
        Object.entries(data.organs).forEach(([labelId, info]) => {
            if (!info || typeof info !== 'object') return;
            const key = String(labelId);
            organData[key] = {
                name: info.name || `OAR ${Object.keys(organData).length + 1}`,
                voxel_count: Number(info.voxel_count ?? info.voxels ?? info.count) || 0,
                color: info.color,
                object_id: info.object_id || data.object_map?.[key],
            };
        });
    }
    if (!Object.keys(organData).length) {
        const counts = data.organ_counts && Object.keys(data.organ_counts).length
            ? data.organ_counts
            : (data.label_counts || {});
        const names = data.organ_names || {};
        Object.entries(counts).forEach(([labelId, count], index) => {
            const key = String(labelId);
            organData[key] = {
                name: names[key] || names[labelId] || `OAR ${index + 1}`,
                voxel_count: Number(count) || 0,
            };
        });
    }
    if (!Object.keys(organData).length) return false;
    if (!updateOrganList(organData, data.oar_source || data.oar_mask_provenance || 'unknown_model')) return false;
    dataTreeState.oar.loaded = true;
    if (!state?.viewerSettings?.userConfigured) dataTreeState.oar.visible = true;
    if (typeof state !== 'undefined' && !state.viewerSettings?.userConfigured) {
        state.viewerSettings = state.viewerSettings || {};
        state.viewerSettings.showOAR = true;
        state.viewerSettings.displayMode = 'overlay';
    }
    const checkbox = document.getElementById('overlayOAR');
    if (checkbox && !state.viewerSettings?.userConfigured) checkbox.checked = true;
    renderDataTree();
    if (typeof window.scheduleWorkspaceSave === 'function') {
        window.scheduleWorkspaceSave('viewer.oar_metadata_payload');
    }
    return true;
};

// Data Tree range inputs used to re-render their own DOM every 150 ms.  That
// replaced the native range element while it was being dragged, which made the
// thumb lose pointer capture and appear to lag behind a fast pointer.  Treat a
// drag as a small transaction: update the viewer live and rebuild the tree only
// after the pointer is released.
let _dataTreeOpacityDrag = null;
let _dataTreeOpacityRerenderPending = false;
let _dataTreeOpacityVisualFrame = null;
let _pendingGroupOpacityCategory = null;

function _isDataTreeOpacityDragActive() {
    return !!_dataTreeOpacityDrag;
}

function _requestDataTreeOpacityVisualRefresh() {
    if (_dataTreeOpacityVisualFrame) return;
    const schedule = typeof requestAnimationFrame === 'function'
        ? requestAnimationFrame
        : callback => setTimeout(callback, 0);
    _dataTreeOpacityVisualFrame = schedule(() => {
        _dataTreeOpacityVisualFrame = null;
        if (state.ctLoaded) reloadOverlays();
        redrawSeedNeedleOverlays();
        requestViewerVisualRefresh('data-tree-opacity');
    });
}

function _finishDataTreeOpacityDrag(event) {
    const active = _dataTreeOpacityDrag;
    if (!active) return;
    if (event?.pointerId !== undefined && active.pointerId !== undefined && event.pointerId !== active.pointerId) return;
    try {
        if (active.control?.hasPointerCapture?.(active.pointerId)) {
            active.control.releasePointerCapture(active.pointerId);
        }
    } catch (_) {}
    _dataTreeOpacityDrag = null;
    clearTimeout(_groupOpacityTimer);
    const pendingCategory = _pendingGroupOpacityCategory;
    _pendingGroupOpacityCategory = null;
    if (pendingCategory) {
        _dataTreeOpacityRerenderPending = false;
        _commitGroupOpacity(pendingCategory);
    } else if (_dataTreeOpacityRerenderPending) {
        _dataTreeOpacityRerenderPending = false;
        renderDataTree();
    }
}

function _bindDataTreeOpacityControls(body) {
    body.querySelectorAll('input.opacity-slider').forEach(control => {
        control.addEventListener('pointerdown', event => {
            event.stopPropagation();
            _dataTreeOpacityDrag = { control, pointerId: event.pointerId };
            try { control.setPointerCapture?.(event.pointerId); } catch (_) {}
        });
        control.addEventListener('keydown', event => event.stopPropagation());
    });
}

if (!window.__brachybotDataTreeOpacityDragEndBound) {
    window.__brachybotDataTreeOpacityDragEndBound = true;
    document.addEventListener('pointerup', _finishDataTreeOpacityDrag, true);
    document.addEventListener('pointercancel', _finishDataTreeOpacityDrag, true);
    window.addEventListener('blur', () => _finishDataTreeOpacityDrag(), true);
}

// Debounced version to prevent excessive re-renders
let _renderDataTreeTimer = null;
function renderDataTreeDebounced() {
    clearTimeout(_renderDataTreeTimer);
    _renderDataTreeTimer = setTimeout(() => {
        if (_isDataTreeOpacityDragActive()) {
            _dataTreeOpacityRerenderPending = true;
            return;
        }
        renderDataTree();
    }, 50);
}

function renderDataTree() {
    const body = document.getElementById('dataTreeBody');
    if (!body) return;

    // Stable IDs are the Data Tree/Viewer identity boundary. Repair legacy
    // snapshots before rendering so one needle or seed cannot appear twice
    // under different trajectory rows after hydration or a manual edit.
    _deduplicatePlanningRows();
    reconcileDataTreeVisualNodes();
    // Catalog hydration is deliberately non-blocking. The active Session UI
    // renders immediately, then durable artifact rows arrive independently.
    void hydrateDataTreeArtifactCatalog();

    // Check what data is loaded
    dataTreeState.ct.loaded = state.ctLoaded;
    // CTV loaded = CT loaded AND CTV segmentation data exists
    dataTreeState.ctv.loaded = !!state.ctLoaded && !!ctvLabelData
        && ctvLabelData.some(value => Number(value) > 0);
    // Metadata and binary labels are loaded independently.  Keep the group
    // available while either source proves that OAR data exists; otherwise a
    // transient empty metadata response hides valid server-side masks.
    dataTreeState.oar.loaded = dataTreeState.organs.length > 0
        || !!(typeof oarLabelData !== 'undefined' && oarLabelData
            && oarLabelData.some(value => Number(value) > 0));
    dataTreeState.dose.loaded = !!(state.metrics && state.metrics.v100 !== undefined);
    dataTreeState.seeds.loaded = !!(state.seeds && state.seeds.length > 0);

    // Reconcile after readiness and child labels are updated. The earlier
    // implementation annotated nodes before these assignments, so persisted
    // status could lag behind the actual rendered data by one pass.
    reconcileDataTreeVisualNodes();

    let html = '';

    // === Image group ===
    html += `<div class="tree-group" data-group="image">
        <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="handleTreeItemRightClick('image', event)">
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
    // CTV subnodes are derived entirely from the current authoritative label
    // volume.  Prune labels that disappeared after a Delete or reclassification
    // so an old browser object cannot remain selectable and issue a second
    // "Structure was not found" deletion request.
    const liveCtvNodeIds = new Set(ctvLabels.map(labelId => `ctv_${labelId}`));
    Object.keys(dataTreeState.ctvLabels || {}).forEach(id => {
        if (liveCtvNodeIds.has(id)) return;
        _disposeSceneMesh(id);
        delete dataTreeState.ctvLabels[id];
    });
    const hasMultiLabelCtv = ctvLabels.length > 1;

    const hasOpenGenericMask = Object.values(state.maskLabels || {})
        .some(mask => _isOpenGenericMask(mask));
    const hasLocalMask = Object.values(state.maskLabels || {})
        .some(mask => !_isGenericSegmentationMask(mask));
    const hasSeg = dataTreeState.ctv.loaded || dataTreeState.organs.length > 0
        || dataTreeState.skin.loaded || hasOpenGenericMask || hasLocalMask;
    // Promoted generic masks are represented by the authoritative CTV/OAR
    // label volume above. Count them there, never as a second standalone row.
    const maskCount = Object.values(state.maskLabels || {})
        .filter(mask => !_isGenericSegmentationMask(mask) || _isOpenGenericMask(mask))
        .length;
    const segCount = hasMultiLabelCtv ? ctvLabels.length : (dataTreeState.ctv.loaded ? 1 : 0);
    html += `<div class="tree-group" data-group="segmentation">
        <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="handleTreeItemRightClick('segmentation', event)">
            <span class="arrow">&#9660;</span>
            <span>Segmentation ${hasSeg ? `(${dataTreeState.organs.length + segCount + maskCount + (dataTreeState.skin.loaded ? 1 : 0)})` : ''}</span>
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
        const previousCtvByObjectId = {};
        Object.values(dataTreeState.ctvLabels || {}).forEach(item => {
            if (item?.objectId) previousCtvByObjectId[String(item.objectId)] = item;
        });
        const ctvAppearanceFor = (labelId) => {
            const objectId = String(
                window._ctvObjectMap?.[labelId] || `structure:ctv:${labelId}`,
            );
            return {
                objectId,
                current: previousCtvByObjectId[objectId]
                    || dataTreeState.ctvLabels?.[`ctv_${labelId}`]
                    || {},
            };
        };

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
        // CTV models may emit auxiliary structures (for example vessels) in
        // the same label volume. Keep those rows inside the CTV branch. They
        // are not OAR records and must never be appended to
        // dataTreeState.organs, otherwise every render changes the OAR count,
        // whitelist, and persisted snapshot.
        const ctvSubLabels = [];
        const addCtvSubLabel = (labelId, category, fallbackColor) => {
            const count = ctvLabelData.filter(v => v === labelId).length;
            const defaultName = labelNames[labelId] || `Label ${labelId}`;
            const color = ctvLabelColorLUT[labelId]
                ? `rgb(${ctvLabelColorLUT[labelId].join(',')})`
                : fallbackColor;
            const id = `ctv_${labelId}`;
            const { objectId, current } = ctvAppearanceFor(labelId);
            // Preserve a user-renamed label; fall back to the default otherwise.
            const customLabel = current?.label && !/^label\s+\d+$/i.test(String(current.label).trim())
                ? current.label
                : '';
            const item = {
                id,
                objectId,
                labelId,
                label: customLabel || defaultName,
                color,
                visible: current.visible !== false,
                opacity: Number.isFinite(Number(current.opacity)) ? Number(current.opacity) : 0.5,
                voxelCount: count,
                category,
                source: 'ctv',
            };
            if (!dataTreeState.ctvLabels) dataTreeState.ctvLabels = {};
            dataTreeState.ctvLabels[id] = {
                ...current,
                objectId: item.objectId,
                label: item.label,
                labelId: item.labelId,
                category: item.category,
                source: item.source,
                voxelCount: item.voxelCount,
                color: current.color || item.color,
                visible: item.visible,
                opacity: item.opacity,
            };
            ctvSubLabels.push(item);
        };
        nonTravLabels.forEach((labelId, index) => addCtvSubLabel(
            labelId,
            'non_traversable',
            ORGAN_COLORS[(labelId + index) % ORGAN_COLORS.length],
        ));
        otherLabels.forEach((labelId, index) => addCtvSubLabel(
            labelId,
            'traversable',
            ORGAN_COLORS[(labelId + index + 7) % ORGAN_COLORS.length],
        ));

        // CTV group header (like OAR)
        const ctvVis = dataTreeState.ctv.visible;
        const ctvOp = dataTreeState.ctv.opacity ?? 0.7;
        const ctvGroupLabel = dataTreeState.ctv.label || 'CTV';
        html += `<div class="tree-group" data-group="ctv">
            <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="handleTreeItemRightClick('ctv', event)">
                <span class="arrow">&#9660;</span>
                <button class="eye-btn ${ctvVis ? '' : 'hidden'}" onclick="event.stopPropagation();toggleDataVisibility('ctv')">${ctvVis ? '&#128065;' : '&#128064;'}</button>
                <span>${escHtml(ctvGroupLabel)}</span>
                <span style="margin-left:auto;display:flex;align-items:center;gap:4px;">
                    <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(ctvOp * 100)}" onclick="event.stopPropagation()" oninput="setGroupOpacity('ctv', this.value)" title="Opacity">
                </span>
            </div>
            <div class="tree-group-items">`;

        // Show tumor label(s) as children under CTV
        if (tumorLabels.length > 0) {
            tumorLabels.forEach(labelId => {
                const count = ctvLabelData ? ctvLabelData.filter(v => v === labelId).length : 0;
                const defaultName = labelNames[labelId] || 'tumor';
                const volumeText = count > 0 && voxelVolumeCm3
                    ? `${(count * voxelVolumeCm3).toFixed(1)} cm³`
                    : '';
                // Use the shared structure palette so the Data Tree swatch,
                // 2D label and reconstructed mesh remain identical.
                const tumorColor = ctvLabelColorLUT[labelId]
                    ? `rgb(${ctvLabelColorLUT[labelId].join(',')})`
                    : DEFAULT_CTV_STRUCTURE_COLOR;
                const { objectId, current } = ctvAppearanceFor(labelId);
                // Preserve a user-renamed label; only fall back to the default
                // when no custom label was assigned.
                const customLabel = current?.label && !/^tumor$/i.test(String(current.label).trim())
                    ? current.label
                    : '';
                const tumorState = ensureDataTreeNodeMetadata({
                    ...current,
                    id: `ctv_${labelId}`, labelId,
                    label: customLabel || defaultName, color: tumorColor,
                    visible: current.visible !== false && dataTreeState.ctv.visible !== false,
                    visible2D: current.visible2D !== false,
                    visible3D: current.visible3D !== false,
                    opacity: dataTreeState.ctv.opacity ?? 0.7,
                    loaded: true,
                    objectId,
                }, 'ctv_label', 'ctv');
                dataTreeState.ctvLabels[`ctv_${labelId}`] = tumorState;
                html += renderTreeItem(`ctv_${labelId}`, tumorState, volumeText);
            });
        } else if (!hasMultiLabelCtv) {
            // Single-label CTV (not from nnUNet multi-label)
            const ctvVolume = state.ctvVolume || null;
            const ctvInfo = ctvVolume ? `${ctvVolume.toFixed(1)} mm³` : '';
            html += renderTreeItem('ctv', ensureDataTreeNodeMetadata({
                ...dataTreeState.ctv, label: dataTreeState.ctv.label || 'CTV Mask', loaded: true,
            }, 'segmentation', 'segmentation'), ctvInfo);
        }

        // Render auxiliary CTV labels as children of CTV. This keeps their
        // individual visibility, opacity and color controls compatible with
        // the 3D/2D renderers without changing the OAR collection.
        ctvSubLabels.forEach(sub => {
            const item = dataTreeState.ctvLabels[sub.id] || sub;
            const itemColor = item.color || sub.color;
            const visible = item.visible !== false;
            const opacity = Number.isFinite(Number(item.opacity)) ? Number(item.opacity) : 0.5;
            const voxelVolume = _ctVoxelVolumeCm3();
            const volumeText = sub.voxelCount > 0 && voxelVolume
                ? `${(sub.voxelCount * voxelVolume).toFixed(1)} cm³`
                : '';
            const subState = ensureDataTreeNodeMetadata({ ...item, loaded: true }, 'ctv_label', 'ctv');
            dataTreeState.ctvLabels[sub.id] = subState;
            html += renderTreeItem(sub.id, subState, volumeText);
        });

        html += `</div></div>`; // close CTV group
    } else {
        const notGenText = dataTreeState.ctv.loading
            ? _dtText('CTV 分割进行中…', 'CTV segmentation in progress...')
            : _dtText('尚未生成 CTV 分割', 'CTV segmentation not generated yet');
        html += renderTreeItem('ctv', { ...dataTreeState.ctv, loaded: dataTreeState.ctv.loading }, notGenText);
    }

    // Guide skin surface is a first-class segmentation sibling of CTV/OAR.
    // It is the exact smoothed envelope consumed by guide generation, not a
    // viewer-only threshold preview.
    if (dataTreeState.skin.loaded || dataTreeState.skin.loading || dataTreeState.skin.status === 'error') {
        const skinInfo = dataTreeState.skin.loading
            ? _dtText('生成中...', 'Building...')
            : dataTreeState.skin.status === 'error'
                ? _dtText('生成失败', 'Failed')
                : `${Number(dataTreeState.skin.voxelCount || 0).toLocaleString()} vox`;
        html += renderTreeItem('skin_surface', dataTreeState.skin, skinInfo);
    }

    // Generic/open masks are independent segmentation siblings. They retain
    // the same row controls as manual masks until an explicit Move action
    // promotes them into the authoritative CTV/OAR Structure Set.
    const masks = Object.entries(state.maskLabels || {});
    const openGenericMasks = masks.filter(([, mask]) => _isOpenGenericMask(mask));
    const uploadedMasks = openGenericMasks.filter(([, mask]) => _maskBelongsToGroup('upload_masks', mask));
    const genericMasks = openGenericMasks.filter(([, mask]) => _maskBelongsToGroup('generic_masks', mask));
    const localMasks = masks.filter(([, mask]) => !_isGenericSegmentationMask(mask));
    const renderMaskGroup = (entries, groupId, label) => {
        if (!entries.length) return '';
        const visible = entries.some(([, mask]) => mask.visible !== false);
        const opacity = entries[0]?.[1]?.opacity ?? 0.6;
        let groupHtml = `<div class="tree-group" data-group="${groupId}">
            <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="handleTreeItemRightClick('${groupId}', event)">
                <span class="arrow">&#9660;</span>
                <button class="eye-btn ${visible ? '' : 'hidden'}" onclick="event.stopPropagation();setGroupVisibility('${groupId}', ${!visible})" title="Toggle ${label}">${visible ? '&#128065;' : '&#128064;'}</button>
                <span>${label} (${entries.length})</span>
                <span style="margin-left:auto;display:flex;align-items:center;gap:4px;">
                    <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(opacity * 100)}" onclick="event.stopPropagation()" oninput="setGroupOpacity('${groupId}', this.value)" title="Opacity for ${label}">
                </span>
            </div>
            <div class="tree-group-items">`;
        entries.forEach(([id, mask]) => {
            const state_ = ensureDataTreeNodeMetadata(
                mask,
                _isGenericSegmentationMask(mask) ? 'generic_mask' : 'mask',
                groupId,
            );
            state_.label = mask.name || mask.label || id;
            state_.source = mask.source || 'mask';
            state_.loaded = !mask.loading && mask.status !== 'error';
            state_.visible = mask.visible !== false;
            state_.visible2D = mask.visible2D !== false;
            state_.visible3D = mask.visible3D !== false;
            state_.movedTo = mask.movedTo || mask.moved_to || null;
            state_.classification = mask.classification || 'unclassified';
            state_.opacity = typeof mask.opacity === 'number' ? mask.opacity : 0.6;
            state_.color = mask.color || '#f08a5d';
            const voxelCount = Number.isFinite(Number(mask.voxelCount))
                ? Number(mask.voxelCount)
                : (Number(mask.voxel_count) || (mask.voxels ? mask.voxels.size : 0));
            groupHtml += renderTreeItem(id, state_, mask.loading
                ? _dtText('生成中...', 'Building...')
                : `${voxelCount} vox`);
        });
        return groupHtml + `</div></div>`;
    };
    html += renderMaskGroup(uploadedMasks, 'upload_masks', _dtText('上传掩膜', 'Upload Mask'));
    html += renderMaskGroup(genericMasks, 'generic_masks', _dtText('其他分割掩膜', 'Additional masks'));
    html += renderMaskGroup(localMasks, 'masks', _dtText('手动/阈值掩膜', 'Manual / threshold masks'));

    // OAR with sub-categories
    const nonTrav = dataTreeState.organs.filter(o => o.category === 'non_traversable');
    const trav = dataTreeState.organs.filter(o => o.category === 'traversable');

    // OAR master group
    const oarVis = dataTreeState.organs.some(o => o.visible);
    const oarOp = dataTreeState.organs.length > 0
        ? dataTreeState.organs.reduce((sum, o) => sum + (o.opacity ?? 0.5), 0) / dataTreeState.organs.length
        : 0.5;
    html += `<div class="tree-group" data-group="oar">
        <div class="tree-group-header" data-node-id="${escHtml(dataTreeState.oar.nodeId || 'oar')}" data-node-type="segmentation" data-status="${escHtml(dataTreeState.oar.status || 'not_generated')}" onclick="toggleTreeGroup(this)" oncontextmenu="handleTreeItemRightClick('oar', event)">
            <span class="arrow">&#9660;</span>
            <button class="eye-btn ${oarVis ? '' : 'hidden'}" onclick="event.stopPropagation();setGroupVisibility('oar', ${!oarVis})" title="Toggle">${oarVis ? '&#128065;' : '&#128064;'}</button>
            <span>OAR (${dataTreeState.organs.length})</span>
            <span style="margin-left:auto;display:flex;align-items:center;gap:4px;">
                <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(oarOp * 100)}" onclick="event.stopPropagation()" oninput="setGroupOpacity('oar', this.value)" title="Opacity">
            </span>
        </div>
        <div class="tree-group-items">`;

    if (dataTreeState.organs.length === 0) {
        const oarStatus = ensureDataTreeNodeMetadata({
            id: 'oar_status', label: _dtText('尚未生成 OAR 分割', 'OAR segmentation not generated yet'), loaded: false,
            status: dataTreeState.oar.loading ? 'loading' : 'not_generated',
            visible: false, opacity: 0.5, color: DEFAULT_OAR_STRUCTURE_COLOR,
            contextActions: [],
        }, 'status', 'oar');
        html += renderTreeItem('oar_status', oarStatus,
            dataTreeState.oar.loading ? _dtText('OAR 分割进行中…', 'Loading') : _dtText('运行 OAR 分割后此处将显示器官', 'Run OAR segmentation to list organs here'));
    }

    // Non-traversable sub-group
    if (nonTrav.length > 0) {
        const gVis = nonTrav.some(o => o.visible);
        const gOp = nonTrav[0]?.opacity ?? 0.5;
        html += `<div class="tree-group" data-group="non_traversable">
            <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="handleTreeItemRightClick('non_traversable', event)">
                <span class="arrow">&#9660;</span>
                <span style="color:rgba(249,115,22,0.7);">&#9679; Non-traversable (${nonTrav.length})</span>
                <span style="margin-left:auto;display:flex;align-items:center;gap:4px;">
                    <button class="eye-btn ${gVis ? '' : 'hidden'}" onclick="event.stopPropagation();setGroupVisibility('non_traversable', ${!gVis})" title="Toggle">${gVis ? '&#128065;' : '&#128064;'}</button>
                    <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(gOp * 100)}" onclick="event.stopPropagation()" oninput="setGroupOpacity('non_traversable', this.value)" title="Opacity">
                </span>
            </div>
            <div class="tree-group-items">`;
        for (const organ of nonTrav) {
            const organState = ensureDataTreeNodeMetadata({ ...organ, loaded: true }, 'oar_mask', 'oar');
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
            <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="handleTreeItemRightClick('traversable', event)">
                <span class="arrow">&#9660;</span>
                <span style="color:rgba(34,197,94,0.7);">&#9679; Traversable (${trav.length})</span>
                <span style="margin-left:auto;display:flex;align-items:center;gap:4px;">
                    <button class="eye-btn ${gVis ? '' : 'hidden'}" onclick="event.stopPropagation();setGroupVisibility('traversable', ${!gVis})" title="Toggle">${gVis ? '&#128065;' : '&#128064;'}</button>
                    <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(gOp * 100)}" onclick="event.stopPropagation()" oninput="setGroupOpacity('traversable', this.value)" title="Opacity">
                </span>
            </div>
            <div class="tree-group-items">`;
        for (const organ of trav) {
            const organState = ensureDataTreeNodeMetadata({ ...organ, loaded: true }, 'oar_mask', 'oar');
            const voxelVolume = _ctVoxelVolumeCm3();
            const info = organ.voxelCount > 0 && voxelVolume ? `${(organ.voxelCount * voxelVolume).toFixed(1)} cm³` : '';
            html += renderTreeItem(organ.id, organState, info);
        }
        html += `</div></div>`;
    }

    // Legacy mask renderer retained only as a reference while the unified
    // sibling renderer above owns the actual tree output.
    if (false) {
    // === Manual/Threshold Mask group (sibling of CTV/OAR) ===
    // Masks come from the Draw/Erase tools and the Threshold slider. They are
    // display-only structures: they share the full data-tree interaction set
    // (visibility, opacity, color, context menu, 3D) but never participate in
    // dose calculation or planning.
    const masks = Object.entries(state.maskLabels || {});
    if (masks.length > 0) {
        const maskVis = masks.some(([, m]) => m.visible !== false);
        const maskOp = masks[0]?.[1]?.opacity ?? 0.6;
        html += `<div class="tree-group" data-group="masks">
        <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="handleTreeItemRightClick('masks', event)">
                <span class="arrow">&#9660;</span>
                <button class="eye-btn ${maskVis ? '' : 'hidden'}" onclick="event.stopPropagation();setGroupVisibility('masks', ${!maskVis})" title="Toggle all masks">${maskVis ? '&#128065;' : '&#128064;'}</button>
                <span>Masks (${masks.length})</span>
                <span style="margin-left:auto;display:flex;align-items:center;gap:4px;">
                    <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(maskOp * 100)}" onclick="event.stopPropagation()" oninput="setGroupOpacity('masks', this.value)" title="Opacity for all masks">
                </span>
            </div>
            <div class="tree-group-items">`;
        masks.forEach(([id, mask]) => {
            // Mutate the durable mask object itself so the identity/status
            // contract survives a refresh and session hydration; passing a
            // throwaway object here made the row look correct while its
            // session/case/version metadata remained absent from the saved
            // state.
            const state_ = ensureDataTreeNodeMetadata(mask, 'mask', 'masks');
            state_.label = mask.name || mask.label || id;
            state_.source = mask.source || 'mask';
            state_.loaded = !mask.loading && mask.status !== 'error';
            state_.visible = mask.visible !== false;
            state_.visible2D = mask.visible2D !== false;
            state_.visible3D = mask.visible3D !== false;
            state_.opacity = typeof mask.opacity === 'number' ? mask.opacity : 0.6;
            state_.color = mask.color || '#8b5cf6';
            const voxelCount = Number.isFinite(Number(mask.voxelCount))
                ? Number(mask.voxelCount)
                : (mask.voxels ? mask.voxels.size : 0);
            html += renderTreeItem(id, state_, mask.loading
                ? _dtText('生成中...', 'Building...')
                : `${voxelCount} vox`);
        });
        html += `</div></div>`;
    }

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
    const planningRuns = Array.isArray(dataTreeState.planning.runs)
        ? dataTreeState.planning.runs : [];
    const preferredActivePlanningId = String(
        dataTreeState.planning.activePlanningId
        || dataTreeState.planning.id
        || planningRuns.find(run => run && run.visible)?.planning_id
        || '',
    );
    // A stale active alias can survive the metadata pass while a restarted
    // case is still decoding its registry. Never synthesize a second legacy
    // active wrapper when the compact catalog already has authoritative IDs.
    const planningIds = new Set(planningRuns
        .map(run => String(run?.planning_id || ''))
        .filter(Boolean));
    const activePlanningId = String(
        planningRuns.length > 0
            ? (planningIds.has(preferredActivePlanningId)
                ? preferredActivePlanningId
                : String(
                    planningRuns.find(run => run?.visible === true)?.planning_id
                    || planningRuns[planningRuns.length - 1]?.planning_id
                    || '',
                ))
            : preferredActivePlanningId,
    );
    const activePlanningRun = planningRuns.find(
        run => String(run?.planning_id || '') === activePlanningId,
    );
    const historicalPlanningRuns = planningRuns.filter(
        run => String(run?.planning_id || '') !== activePlanningId,
    );
    // The parent Planning node is an effective visibility constraint.  The
    // compact restart snapshot can contain the parent without its clinical
    // children, so deriving this eye icon from children alone makes a hidden
    // parent look enabled and leaves the operator no reliable way to reveal
    // the dose layers again.
    const planningMasterVisible = _planningMasterVisible();
    const planningVis = planningMasterVisible
        && (planningEntries.length === 0 || planningEntries.some(item => item.visible !== false));
    const planningOp = planningEntries.length
        ? planningEntries.reduce((sum, item) => sum + Number(item.opacity ?? 0.7), 0) / planningEntries.length
        : 0.7;

    html += `<div class="tree-group" data-group="planning">
        <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="handleTreeItemRightClick('planning', event)">
            <span class="arrow">&#9660;</span>
            <button class="eye-btn ${planningVis ? '' : 'hidden'}" onclick="event.stopPropagation();setGroupVisibility('planning', ${!planningVis})" title="Toggle all planning objects">${planningVis ? '&#128065;' : '&#128064;'}</button>
            <span>Planning ${planningRuns.length ? `(${planningRuns.length})` : (hasPlanning ? `(${planningEntries.length})` : '')}</span>
            <span style="margin-left:auto;display:flex;align-items:center;gap:4px;">
                <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(planningOp * 100)}" onclick="event.stopPropagation()" oninput="setGroupOpacity('planning', this.value)" title="Opacity for all planning objects">
            </span>
        </div>
        <div class="tree-group-items">`;

    // Every Planning run has a stable backend identity. Historical rows are
    // intentionally summary-only until activated; their geometry is loaded
    // through the same session-scoped endpoints as the active run.
    if (historicalPlanningRuns.length > 0) {
        html += `<div class="tree-group" data-group="planning_history">
            <div class="tree-group-header" onclick="toggleTreeGroup(this)">
                <span class="arrow">&#9660;</span>
                <span data-i18n-zh="历史规划" data-i18n-en="Planning history">Planning history</span>
                <span style="margin-left:auto;color:var(--text-dim);font-size:0.62rem;">${historicalPlanningRuns.length}</span>
            </div>
            <div class="tree-group-items">`;
        historicalPlanningRuns.forEach(run => {
            const runId = String(run?.planning_id || '');
            if (!runId) return;
            const sequence = Number.isFinite(Number(run?.sequence)) ? Number(run.sequence) + 1 : null;
            const runLabel = String(run?.label || (sequence === null ? 'Planning' : `Planning_${sequence}`));
            const runStatus = String(run?.status || 'unknown');
            const runVisible = run?.visible === true;
            const runInfo = [
                runStatus,
                run?.num_trajectories ? `${run.num_trajectories} trajectories` : '',
                run?.total_seeds ? `${run.total_seeds} seeds` : '',
            ].filter(Boolean).join(' · ');
            const runArg = JSON.stringify(runId).replace(/</g, '\\u003c');
            // Report text and figures are stored in the planning-scoped UI
            // snapshot, while the durable artifact catalog may arrive later.
            // Use both sources so a historical Planning exposes its real
            // Report state instead of silently looking empty after restart.
            const savedReportSection = window.__reportWorkspaceByPlanning
                && window.__reportWorkspaceByPlanning[runId];
            const savedReportForm = savedReportSection?.form || savedReportSection;
            const reportArtifactExists = typeof dataTreeState !== 'undefined'
                && (dataTreeState.exportArtifacts || []).some(item =>
                    String(item?.planningId || '') === runId
                    && ['report', 'report_data', 'report_figure', 'screenshot'].includes(
                        String(item?.dataType || item?.type || '').toLowerCase(),
                    ));
            const reportFormHasContent = !!savedReportForm && (
                (Array.isArray(savedReportForm.figures) && savedReportForm.figures.length > 0)
                || Object.keys(savedReportForm.metrics || {}).length > 0
                || Object.keys(savedReportForm.qualityAssessment?.metrics || {}).length > 0
                || ['interpretation', 'safety', 'qaNotes', 'planning', 'references']
                    .some(key => String(savedReportForm[key] || '').trim())
            );
            const hasReport = reportArtifactExists || reportFormHasContent;
            const storedArtifactStatus = run?.artifact_status && typeof run.artifact_status === 'object'
                ? run.artifact_status : {};
            const artifactState = (key, generated) => {
                const explicit = String(
                    storedArtifactStatus[key]
                    || (key === 'guide' ? storedArtifactStatus.surgical_guide : '')
                    || '',
                ).trim();
                return explicit || (generated ? 'ready' : 'not_generated');
            };
            const artifactRows = [
                ['trajectories', 'Trajectories', run?.num_trajectories ? `${run.num_trajectories}` : 'not generated', artifactState('trajectories', run?.num_trajectories)],
                ['seeds', 'Seeds', run?.total_seeds ? `${run.total_seeds}` : 'not generated', artifactState('seeds', run?.total_seeds)],
                ['dose', 'Dose / iso-surfaces', run?.has_current_dose
                    ? 'ready'
                    : (run?.has_reference_dose ? 'reference' : 'not generated'),
                    artifactState('dose', run?.has_dose || run?.has_reference_dose)],
                ['dvh', 'DVH / metrics', run?.has_dvh || run?.has_metrics ? 'ready' : 'not generated', artifactState('dvh', run?.has_dvh || run?.has_metrics)],
                ['guide', 'Surgical Guide', run?.has_guide ? 'ready' : 'not generated', artifactState('guide', run?.has_guide)],
                ['skin', 'Guide skin surface', run?.has_skin ? 'ready' : 'not generated', artifactState('skin', run?.has_skin)],
                ['report', 'Report', hasReport ? 'ready' : 'not generated', artifactState('report', hasReport)],
            ];
            const runVisibilityTitle = runVisible
                ? _dtText('当前显示的 Planning', 'Currently displayed Planning')
                : _dtText('显示此 Planning 及其全部产物', 'Show this Planning and all of its artifacts');
            html += `<div class="tree-group planning-history-run" data-group="planning_run_${escHtml(runId)}" data-planning-id="${escHtml(runId)}">
                <div class="tree-group-header planning-run-item" data-node-id="planning:${escHtml(runId)}" data-node-type="planning_run" data-status="${escHtml(runStatus)}"
                    onclick="activatePlanningRunFromTree(${runArg})"
                    oncontextmenu="event.preventDefault();event.stopPropagation();activatePlanningRunFromTree(${runArg})"
                    style="padding-left:1rem;cursor:pointer;">
                    <span class="arrow">&#9660;</span>
                    <button class="eye-btn" onclick="event.stopPropagation();activatePlanningRunFromTree(${runArg})" title="${escHtml(runVisibilityTitle)}" aria-label="${escHtml(runVisibilityTitle)}">${runVisible ? '&#128065;' : '&#128064;'}</button>
                    <span style="color:#60a5fa;">&#9679;</span>
                    <span class="item-label">${escHtml(runLabel)}</span>
                    <span class="item-info">${escHtml(runInfo || 'saved')}</span>
                </div>
                <div class="tree-group-items planning-history-artifacts">`;
            artifactRows.forEach(([key, label, status, lifecycle]) => {
                html += `<div class="tree-item planning-history-artifact" data-node-id="planning:${escHtml(runId)}:${escHtml(key)}" data-node-type="planning_artifact" data-planning-id="${escHtml(runId)}"
                    data-artifact-key="${escHtml(key)}" data-status="${escHtml(lifecycle)}"
                    onclick="activatePlanningRunFromTree(${runArg})" title="Activate ${escHtml(runLabel)} to show this artifact">
                    <span style="color:${lifecycle === 'ready' ? 'var(--accent-green, #38d39f)' : 'var(--text-dim)'};">${lifecycle === 'ready' ? '&#9679;' : '&#9675;'}</span>
                    <span class="item-label">${escHtml(label)}</span>
                    <span class="item-info">${escHtml(status)}${lifecycle !== status && lifecycle ? ` · ${escHtml(lifecycle)}` : ''}</span>
                </div>`;
            });
            html += `</div></div>`;
        });
        html += `</div></div>`;
    }

    const shouldWrapActivePlanning = !!activePlanningRun;
    if (shouldWrapActivePlanning) {
        const activeSequence = Number.isFinite(Number(activePlanningRun.sequence))
            ? Number(activePlanningRun.sequence) + 1 : null;
        const activeLabel = String(activePlanningRun.label
            || (activeSequence === null ? 'Planning' : `Planning_${activeSequence}`));
        html += `<div class="tree-group planning-active-run" data-group="planning_run_active">
            <div class="tree-group-header" onclick="toggleTreeGroup(this)">
                <span class="arrow">&#9660;</span>
                <button class="eye-btn" onclick="event.stopPropagation();setGroupVisibility('planning', ${!planningVis})" title="Toggle active Planning">${planningVis ? '&#128065;' : '&#128064;'}</button>
                <span class="item-label">${escHtml(activeLabel)}</span>
                <span class="item-info">${escHtml(String(activePlanningRun.status || 'active'))}</span>
            </div>
            <div class="tree-group-items">`;
    }

    // Trajectories group (parent of seeds) — only shown when the
    // server returned the new "trajectories" array. Without it, fall
    // back to the flat seeds list below.
    if (planningTrajectories.length > 0) {
        const trajVis = planningMasterVisible && planningTrajectories.some(t => t.visible);
        const trajOp = planningTrajectories[0]?.opacity ?? 0.8;
        html += `<div class="tree-group" data-group="planning_trajectories">
        <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="handleTreeItemRightClick('planning_trajectories', event)">
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
            const trajLabel = traj.label || `Trajectory ${traj.index + 1}`;
            const trajState = ensureDataTreeNodeMetadata({ ...traj, visible: planningMasterVisible && traj.visible !== false, opacity: traj.opacity, color: traj.color, loaded: true, label: trajLabel }, 'trajectory', 'planning');
            const childSeeds = traj.seeds || [];
            const childHeader = childSeeds.length > 0 ? ` (${childSeeds.length} seeds)` : '';
            html += `<div class="tree-group" data-group="${trajId}">
            <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="handleTreeItemRightClick('${trajId}', event)" style="padding-left:1.2rem;">
                    <span class="arrow">&#9660;</span>
                    <button class="eye-btn ${planningMasterVisible && traj.visible !== false ? '' : 'hidden'}" onclick="event.stopPropagation();toggleDataVisibility('${trajId}')">${planningMasterVisible && traj.visible !== false ? '&#128065;' : '&#128064;'}</button>
                    <span style="color:#88ccff;">➤</span>
                    <span>${escHtml(trajLabel)}${childHeader}</span>
                </div>
                <div class="tree-group-items">`;
            childSeeds.forEach(seed => {
                const seedLabel = seed.label || `Seed ${seed.id.split('_').slice(-1)[0]}`;
                const seedState = ensureDataTreeNodeMetadata({ ...seed, visible: planningMasterVisible && seed.visible !== false, opacity: seed.opacity ?? 1.0, color: seed.color || '#ffcc00', loaded: true, label: seedLabel }, 'seed', trajId);
                html += renderTreeItem(seed.id, seedState, '');
            });
            html += `</div></div>`; // close trajectory sub-group
        });
        html += `</div></div>`; // close trajectories group
    } else if (planningSeeds.length > 0) {
        // Fallback: flat seeds list (server didn't return trajectories)
        const seedsVis = planningMasterVisible && planningSeeds.some(s => s.visible !== false);
        const seedsOp = planningSeeds[0]?.opacity ?? 1.0;
        html += `<div class="tree-group" data-group="planning_seeds">
        <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="handleTreeItemRightClick('planning_seeds', event)">
                <span class="arrow">&#9660;</span>
                <button class="eye-btn ${seedsVis ? '' : 'hidden'}" onclick="event.stopPropagation();setGroupVisibility('planning_seeds', ${!seedsVis})" title="Toggle">${seedsVis ? '&#128065;' : '&#128064;'}</button>
                <span>Seeds (${planningSeeds.length})</span>
                <span style="margin-left:auto;display:flex;align-items:center;gap:4px;">
                    <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(seedsOp * 100)}" onclick="event.stopPropagation()" oninput="setGroupOpacity('planning_seeds', this.value)" title="Opacity">
                </span>
            </div>
            <div class="tree-group-items">`;
        planningSeeds.forEach(seed => {
            const seedState = ensureDataTreeNodeMetadata({ ...seed, visible: planningMasterVisible && seed.visible !== false, opacity: seed.opacity, color: seed.color, loaded: true, label: seed.label || `Seed ${seed.id}` }, 'seed', 'planning');
            html += renderTreeItem(seed.id, seedState, `Traj ${seed.trajectory_id}`);
        });
        html += `</div></div>`;
    }

    // Needles group
    if (planningNeedles.length > 0) {
        const needlesVis = planningMasterVisible && planningNeedles.some(n => n.visible !== false);
        const needlesOp = planningNeedles[0]?.opacity ?? 0.8;
        html += `<div class="tree-group" data-group="planning_needles">
        <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="handleTreeItemRightClick('planning_needles', event)">
                <span class="arrow">&#9660;</span>
                <button class="eye-btn ${needlesVis ? '' : 'hidden'}" onclick="event.stopPropagation();setGroupVisibility('planning_needles', ${!needlesVis})" title="Toggle">${needlesVis ? '&#128065;' : '&#128064;'}</button>
                <span>Needles (${planningNeedles.length})</span>
                <span style="margin-left:auto;display:flex;align-items:center;gap:4px;">
                    <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(needlesOp * 100)}" onclick="event.stopPropagation()" oninput="setGroupOpacity('planning_needles', this.value)" title="Opacity">
                </span>
            </div>
            <div class="tree-group-items">`;
        planningNeedles.forEach(needle => {
            const needleState = ensureDataTreeNodeMetadata({ ...needle, visible: planningMasterVisible && needle.visible !== false, opacity: needle.opacity, color: needle.color, loaded: true, label: needle.label || `Needle ${needle.id}` }, 'needle', 'planning');
            html += renderTreeItem(needle.id, needleState, `${needle.points.length} pts`);
        });
        html += `</div></div>`;
    }

    // Dose isosurfaces group
    if (doseLevels.length > 0) {
        const doseVis = planningMasterVisible && doseLevels.some(
            d => d.loaded === true && d.visible !== false,
        );
        const doseOp = doseLevels[0]?.opacity ?? 0.3;
        html += `<div class="tree-group" data-group="dose_isosurfaces">
        <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="handleTreeItemRightClick('dose_isosurfaces', event)">
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
            // Preserve a user-renamed iso-surface label; default remains "N Gy".
            const doseLabel = level.label || `${absGy} Gy`;
            const levelState = ensureDataTreeNodeMetadata({
                ...level,
                visible: planningMasterVisible && level.visible !== false,
                opacity: level.opacity,
                color: level.color,
                // The row is only "ready" when the current refresh actually
                // produced the corresponding mesh.  Do not advertise a
                // surface merely because its threshold is configured.
                loaded: level.loaded === true,
                label: doseLabel,
            }, 'dose_iso_surface', 'planning');
            const coveragePct = Number(level.coveragePct ?? level.coverageAudit?.coverage_percent);
            const pctLabel = Number.isFinite(coveragePct) && level.coverageAudit?.reported_metric === 'v100'
                ? `${absGy} Gy · V100 ${coveragePct.toFixed(1)}%`
                : (level.pctLabel || `${absGy} Gy`);
            html += renderTreeItem(`dose_iso_${level.threshold}`, levelState, pctLabel);
        });
        html += `</div></div>`;
    }

    // Dose overlay toggle (2D overlay on CT slices)
    if (dataTreeState.planning.doseOverlay) {
        const ovVis = planningMasterVisible && isDataTreeNodeVisible2D(dataTreeState.planning.doseOverlay);
        const overlayStatus = String(dataTreeState.planning.doseOverlay.status || 'ready');
        const overlayStatusLabel = overlayStatus !== 'ready'
            ? `<span class="item-status item-status-${escHtml(overlayStatus)}" title="${escHtml(
                dataTreeState.planning.doseOverlay.doseStale
                    ? _dtText('显示的是算法规划基线；当前几何尚未重新计算剂量', 'Algorithm-plan reference; dose has not been recomputed for the current geometry')
                    : overlayStatus
            )}">${escHtml(_dtStatusText(overlayStatus))}</span>`
            : '';
        const ovOp = typeof getDoseOverlayOpacity === 'function'
            ? getDoseOverlayOpacity()
            : Number(state.doseOverlay?.opacity ?? dataTreeState.planning.doseOverlay.opacity ?? 0.4);
        html += `<div class="tree-item" data-item="dose_overlay" data-node-id="${escHtml(dataTreeState.planning.doseOverlay.nodeId || 'dose_overlay')}" data-node-type="dose_contour_2d" data-status="${escHtml(dataTreeState.planning.doseOverlay.status || 'ready')}" onclick="handleTreeItemClick('dose_overlay', event)" oncontextmenu="event.preventDefault();event.stopPropagation();handleTreeItemRightClick('dose_overlay', event)" style="display:flex;align-items:center;gap:6px;padding:2px 8px;font-size:0.7rem;">
            <button class="eye-btn ${ovVis ? '' : 'hidden'}" onclick="event.stopPropagation();toggleDataVisibility('dose_overlay')" style="font-size:0.65rem;">${ovVis ? '&#128065;' : '&#128064;'}</button>
            <span style="color:#22d3ee;">◉</span>
            <span>${escHtml(dataTreeState.planning.doseOverlay.label || 'Dose Overlay (2D)')}</span>
            <span style="margin-left:auto;font-size:0.6rem;color:var(--text-dim);">max: ${state.doseOverlay.doseMax?.toFixed(1) || '--'}</span>${overlayStatusLabel}
            <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(ovOp * 100)}" onclick="event.stopPropagation()" oninput="setDoseOverlayOpacity(this.value)" title="Opacity">
        </div>`;
    }

    if (dataTreeState.planning.dvh) {
        html += renderTreeItem('dvh', dataTreeState.planning.dvh, 'DVH structures and curves');
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

    // CTV, OAR and dose meshes already have canonical rows above. Render only
    // independent planning artifacts here so every scene object has one owner.
    const independentPlanningMeshes = planningMeshes.filter(mesh =>
        ['surgical_guide', 'manual_annotation', 'planning_artifact'].includes(String(mesh.source || ''))
    );
    if (independentPlanningMeshes.length > 0) {
        const artifactsVisible = planningMasterVisible && independentPlanningMeshes.some(mesh => mesh.visible !== false);
        const artifactsOpacity = independentPlanningMeshes.reduce(
            (sum, mesh) => sum + Number(mesh.opacity ?? 0.75), 0,
        ) / independentPlanningMeshes.length;
        html += `<div class="tree-group" data-group="planning_meshes">
        <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="handleTreeItemRightClick('planning_meshes', event)">
                <span class="arrow">&#9660;</span>
                <button class="eye-btn ${artifactsVisible ? '' : 'hidden'}" onclick="event.stopPropagation();setGroupVisibility('planning_meshes', ${!artifactsVisible})" title="Toggle planning artifacts">${artifactsVisible ? '&#128065;' : '&#128064;'}</button>
                <span data-i18n-zh="规划产物" data-i18n-en="Planning Artifacts">Planning Artifacts</span>
                <span>(${independentPlanningMeshes.length})</span>
                <span style="margin-left:auto;display:flex;align-items:center;gap:4px;">
                    <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(artifactsOpacity * 100)}" onclick="event.stopPropagation()" oninput="setGroupOpacity('planning_meshes', this.value)" title="Opacity">
                </span>
            </div>
            <div class="tree-group-items">`;
        independentPlanningMeshes.forEach(mesh => {
            const status = mesh.status && mesh.status !== 'ready' ? String(mesh.status) : '';
            html += renderTreeItem(mesh.id, {
                ...mesh,
                visible: planningMasterVisible && mesh.visible !== false,
                loaded: true,
                label: mesh.label || mesh.id,
            }, status);
        });
        html += `</div></div>`;
    }

    // Legacy dose/seed items (if no planning data)
    if (!hasPlanning) {
        html += renderTreeItem('dose', dataTreeState.dose, state.metrics && state.metrics.v100 !== undefined ? `V100: ${(state.metrics.v100 * 100).toFixed(1)}%` : '');
        html += renderTreeItem('seeds', dataTreeState.seeds, state.seeds ? `${state.seeds.length} seeds` : '');
    }

    if (shouldWrapActivePlanning) html += `</div></div>`; // close active Planning run
    html += `</div></div>`; // close Planning group

    const annotations = dataTreeState.annotations || [];
    const exportArtifacts = dataTreeState.exportArtifacts || [];
    if (annotations.length || exportArtifacts.length) {
        html += `<div class="tree-group" data-group="artifacts">
        <div class="tree-group-header" onclick="toggleTreeGroup(this)" oncontextmenu="handleTreeItemRightClick('artifacts', event)">
                <span class="arrow">&#9660;</span>
                <span>${_dtText('工件与标注', 'Artifacts & Annotations')}</span>
                <span>(${annotations.length + exportArtifacts.length})</span>
            </div>
            <div class="tree-group-items">`;
        annotations.forEach(item => {
            html += renderTreeItem(item.id, item, _dtText('手动标注', 'Manual annotation'));
        });
        exportArtifacts.forEach(item => {
            html += renderArtifactTreeItem(item);
        });
        html += `</div></div>`;
    }

    body.innerHTML = html;
    _bindDataTreeOpacityControls(body);
    _restoreTreeGroupExpansionState(body);
    requestViewerVisualRefresh('data-tree-render');
}

function _scheduleDataTreeSave(reason) {
    if (typeof window.scheduleWorkspaceSave === 'function') {
        window.scheduleWorkspaceSave(reason || 'viewer.data_tree_changed');
    }
}

function renderTreeItem(id, itemState, info) {
    const eyeIcon = itemState.visible ? '&#128065;' : '&#128064;';
    const eyeClass = itemState.visible ? '' : 'hidden';
    const loadedClass = itemState.loaded ? '' : 'style="opacity:0.4;"';
    const disabledAttr = itemState.loaded ? '' : 'disabled';
    // Indent for sub-items: organs, CTV labels, planning items, masks
    const isMaskId = _isDataTreeMaskId(id);
    const isSubItem = id.startsWith('organ_') || id.startsWith('ctv_') || id.startsWith('seed_') || id.startsWith('needle_') || id.startsWith('dose_iso_') || isMaskId;
    const indent = isSubItem ? 'style="padding-left:1.6rem;"' : '';
    // 3D button for organs, CTV, CTV sub-labels, planning items, and masks
    const canRecon3d = id === 'ctv' || id === 'skin_surface' || id.startsWith('organ_') || id.startsWith('ctv_') || id.startsWith('seed_') || id.startsWith('needle_') || isMaskId;
    const recon3dBtn = canRecon3d ? `<button class="recon3d-btn" title="3D Reconstruct" onclick="event.stopPropagation();reconstructOrgan3D('${id}')">&#9638;</button>` : '';
    const isCt = id === 'ct';
    const windowWidth = _viewerWindowValue(state?.viewerSettings?.window, 400);
    const windowLevel = _viewerLevelValue(state?.viewerSettings?.level, 40);
    const windowBounds = _windowLevelBounds(windowWidth, windowLevel);
    const windowDomain = _ctWindowSliderDomain(windowWidth, windowLevel);
    const lowTitle = typeof _dtText === 'function' ? _dtText('显示灰度下限', 'Display intensity lower bound') : 'Display intensity lower bound';
    const highTitle = typeof _dtText === 'function' ? _dtText('显示灰度上限', 'Display intensity upper bound') : 'Display intensity upper bound';
    const rangeTitle = typeof _dtText === 'function'
        ? _dtText('拖动两端实时调整窗宽窗位', 'Drag either handle to adjust window and level live')
        : 'Drag either handle to adjust window and level live';
    const windowSpan = Math.max(WINDOW_LEVEL_MIN_SPAN, windowDomain.max - windowDomain.min);
    const lowPercent = Math.max(0, Math.min(100, ((windowBounds.low - windowDomain.min) / windowSpan) * 100));
    const highPercent = Math.max(0, Math.min(100, ((windowBounds.high - windowDomain.min) / windowSpan) * 100));
    const ctWindowLevelControls = isCt && itemState.loaded
        ? `<span class="ct-window-level-controls" title="${escHtml(rangeTitle)}" style="--wl-low-pct:${lowPercent}%;--wl-high-pct:${highPercent}%;" onclick="event.stopPropagation()" ondblclick="event.stopPropagation()" onmousedown="event.stopPropagation()" onpointerdown="event.stopPropagation()" onkeydown="event.stopPropagation()">
            <span class="ct-window-range-values" aria-hidden="true">
                <output data-ct-window-output="low">${_formatWindowLevelValue(windowBounds.low)}</output>
                <output data-ct-window-output="summary">W${_formatWindowLevelValue(windowWidth)} L${_formatWindowLevelValue(windowLevel)}</output>
                <output data-ct-window-output="high">${_formatWindowLevelValue(windowBounds.high)}</output>
            </span>
            <span class="ct-window-range-track">
                <span class="ct-window-range-base"></span>
                <span class="ct-window-range-fill"></span>
                <input id="dataTreeWindowLow" data-ct-window-level="low" type="range" min="${windowDomain.min}" max="${windowDomain.max}" step="0.5" value="${windowBounds.low}" aria-label="${escHtml(lowTitle)}" aria-valuetext="${_formatWindowLevelValue(windowBounds.low)} HU" ${disabledAttr} onpointerdown="event.stopPropagation();this.classList.add('is-active')" onpointerup="event.stopPropagation();this.classList.remove('is-active')" onpointercancel="this.classList.remove('is-active')" onblur="this.classList.remove('is-active')" oninput="event.stopPropagation();applyDataTreeWindowRange('low', false)" onchange="event.stopPropagation();applyDataTreeWindowRange('low', true)">
                <input id="dataTreeWindowHigh" data-ct-window-level="high" type="range" min="${windowDomain.min}" max="${windowDomain.max}" step="0.5" value="${windowBounds.high}" aria-label="${escHtml(highTitle)}" aria-valuetext="${_formatWindowLevelValue(windowBounds.high)} HU" ${disabledAttr} onpointerdown="event.stopPropagation();this.classList.add('is-active')" onpointerup="event.stopPropagation();this.classList.remove('is-active')" onpointercancel="this.classList.remove('is-active')" onblur="this.classList.remove('is-active')" oninput="event.stopPropagation();applyDataTreeWindowRange('high', false)" onchange="event.stopPropagation();applyDataTreeWindowRange('high', true)">
            </span>
        </span>`
        : '';

    const dataAttr = (id === 'ctv' || id.startsWith('organ_') || id.startsWith('ctv_')) ? `data-organ-id="${id}"` : '';
    const selectedClass = selectedItems.has(id) ? 'selected' : '';

    const statusLabel = itemState.status && itemState.status !== 'ready'
        ? `<span class="item-status item-status-${itemState.status}" title="${escHtml(itemState.error || itemState.status)}">${escHtml(_dtStatusText(itemState.status))}</span>`
        : '';
    return `<div class="tree-item ${isCt ? 'tree-item--ct' : ''} ${selectedClass}" data-node-id="${escHtml(itemState.nodeId || id)}" data-object-id="${escHtml(itemState.objectId || id)}" data-node-type="${escHtml(itemState.type || 'visual') }" data-status="${escHtml(itemState.status || 'ready')}" data-visible="${itemState.visible !== false}" data-visible-2d="${itemState.visible2D !== false}" data-visible-3d="${itemState.visible3D !== false}" ${loadedClass} ${indent} ${dataAttr}
        onclick="handleTreeItemClick('${id}', event)"
        oncontextmenu="event.preventDefault();event.stopPropagation();handleTreeItemRightClick('${id}', event)">
        <button class="eye-btn ${eyeClass}" onclick="event.stopPropagation();toggleDataVisibility('${id}')" ${disabledAttr}>${eyeIcon}</button>
        <span class="color-swatch" style="background:${itemState.color};" onclick="event.stopPropagation();openColorPicker('${id}', this)" title="Click to change color"></span>
        <span class="item-label">${escHtml(itemState.label || '')}</span>
        <span class="item-info">${escHtml(info || '')}</span>${ctWindowLevelControls}${statusLabel}
        ${recon3dBtn}
        <input type="range" class="opacity-slider" min="0" max="100" value="${Math.round(itemState.opacity * 100)}"
            ${disabledAttr}
            onclick="event.stopPropagation()"
            oninput="setDataOpacity('${id}', this.value)">
    </div>`;
}

function renderArtifactTreeItem(itemState) {
    const id = String(itemState.id);
    const selectedClass = selectedItems.has(id) ? 'selected' : '';
    const typeLabel = itemState.dataType === 'screenshot'
        ? _dtText('截图', 'Screenshot')
        : _dtText('报告', 'Report');
    return `<div class="tree-item ${selectedClass}" data-node-id="${escHtml(itemState.nodeId || id)}" data-object-id="${escHtml(itemState.objectId || id)}" data-node-type="${escHtml(itemState.type || 'artifact')}" data-status="${escHtml(itemState.status || 'ready')}" data-visible="${itemState.visible !== false}" data-visible-2d="${itemState.visible2D !== false}" data-visible-3d="${itemState.visible3D !== false}"
        onclick="handleTreeItemClick('${id}', event)"
        oncontextmenu="event.preventDefault();event.stopPropagation();handleTreeItemRightClick('${id}', event)">
        <span class="color-swatch" style="background:${itemState.color};pointer-events:none;"></span>
        <span class="item-label">${escHtml(itemState.label || '')}</span>
        <span class="item-info">${escHtml(typeLabel)}</span>
    </div>`;
}

// Qt-style color dialog
function openColorPicker(id, swatchEl) {
    // Get current color
    let itemState;
    if (id === 'ctv') itemState = dataTreeState.ctv;
    else if (id === 'oar') itemState = dataTreeState.oar;
    else if (id === 'skin_surface') itemState = dataTreeState.skin;
    else if (id === 'dose') itemState = dataTreeState.dose;
    else if (id === 'seeds') itemState = dataTreeState.seeds;
    else if (id === 'needles') itemState = dataTreeState.needles;
    else if (id.startsWith('ctv_')) {
        // CTV sub-labels (tumor, artery, vein, pancreas, etc.)
        if (!dataTreeState.ctvLabels) dataTreeState.ctvLabels = {};
        if (!dataTreeState.ctvLabels[id]) dataTreeState.ctvLabels[id] = { visible: true, opacity: 0.7, color: DEFAULT_CTV_STRUCTURE_COLOR };
        itemState = dataTreeState.ctvLabels[id];
    } else if (id.startsWith('seed_')) {
        itemState = dataTreeState.planning.seeds.find(s => s.id === id);
    } else if (id.startsWith('needle_')) {
        itemState = dataTreeState.planning.needles.find(n => n.id === id);
    } else if (id.startsWith('dose_iso_')) {
        const threshold = parseFloat(id.replace('dose_iso_', ''));
        itemState = dataTreeState.planning.doseLevels.find(d => d.threshold === threshold);
    } else if (_isDataTreeMaskId(id)) {
        itemState = _maskStateEntry(id);
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
        // Update the typed LUT. CTV and OAR can reuse the same numeric label.
        if (id.startsWith('organ_')) {
            const organ = dataTreeState.organs.find(o => o.id === id);
            if (organ && organ.labelId !== undefined) {
                const r = parseInt(pendingColor.slice(1,3), 16);
                const g = parseInt(pendingColor.slice(3,5), 16);
                const b = parseInt(pendingColor.slice(5,7), 16);
                oarLabelColorLUT[organ.labelId] = [r, g, b];
                labelColorLUT = oarLabelColorLUT;
            }
        }
        if (id.startsWith('ctv_')) {
            const labelId = parseInt(id.replace('ctv_', ''));
            const r = parseInt(pendingColor.slice(1,3), 16);
            const g = parseInt(pendingColor.slice(3,5), 16);
            const b = parseInt(pendingColor.slice(5,7), 16);
            ctvLabelColorLUT[labelId] = [r, g, b];
        }
        if (id.startsWith('dose_iso_')) {
            const threshold = parseFloat(id.replace('dose_iso_', ''));
            const doseLevel = dataTreeState.planning?.doseLevels?.find(level => Math.abs(Number(level.threshold) - threshold) < 1e-6);
            if (doseLevel) doseLevel.color = pendingColor;
        }
        // Update 3D mesh color if mesh exists
        const mesh3d = _isDataTreeMaskId(id)
            ? scene3D.meshes[_maskSceneMeshId(id)]
            : scene3D.meshes[id];
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
            _scheduleDataTreeSave(`viewer.color:${id}`);
            requestViewerVisualRefresh('color-picker');
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

// Programmatic color change for a data-tree node, mirroring the color-dialog
// applyColor path. Supported node ids include the guide skin sibling and the
// existing CTV, OAR, mask, planning, and dose visual nodes. Refreshes 2D
// overlays and the 3D mesh.
function setDataTreeItemColor(id, color) {
    if (!/^#[0-9a-f]{6}$/i.test(String(color || ''))) return false;
    let itemState;
    if (id === 'ctv') itemState = dataTreeState.ctv;
    else if (id === 'oar') itemState = dataTreeState.oar;
    else if (id === 'skin_surface') itemState = dataTreeState.skin;
    else if (id === 'dose') itemState = dataTreeState.dose;
    else if (id === 'seeds') itemState = dataTreeState.seeds;
    else if (id === 'needles') itemState = dataTreeState.needles;
    else if (id.startsWith('ctv_')) itemState = dataTreeState.ctvLabels?.[id];
    else if (id.startsWith('seed_')) itemState = dataTreeState.planning.seeds.find(s => s.id === id);
    else if (id.startsWith('needle_')) itemState = dataTreeState.planning.needles.find(n => n.id === id);
    else if (id.startsWith('dose_iso_')) {
        const threshold = parseFloat(id.replace('dose_iso_', ''));
        itemState = dataTreeState.planning.doseLevels.find(d => d.threshold === threshold);
    } else if (_isDataTreeMaskId(id)) itemState = _maskStateEntry(id);
    else itemState = dataTreeState.organs.find(o => o.id === id);
    if (!itemState) return false;
    itemState.color = color;
    if (id.startsWith('organ_') || id.startsWith('ctv_')) {
        const labelId = itemState.labelId ?? parseInt(id.replace('ctv_', ''), 10);
        if (Number.isFinite(Number(labelId))) {
            const r = parseInt(color.slice(1, 3), 16);
            const g = parseInt(color.slice(3, 5), 16);
            const b = parseInt(color.slice(5, 7), 16);
            if (id.startsWith('ctv_')) {
                ctvLabelColorLUT[labelId] = [r, g, b];
            } else {
                oarLabelColorLUT[labelId] = [r, g, b];
                labelColorLUT = oarLabelColorLUT;
            }
        }
    }
    const mesh3d = _isDataTreeMaskId(id)
        ? scene3D.meshes[_maskSceneMeshId(id)]
        : scene3D.meshes[id];
    if (mesh3d) {
        _setMeshMaterialColor(mesh3d, color);
        const savedMaterial = state.doseTexture?.originalMaterials?.[id];
        if (savedMaterial) _setMeshMaterialColor({ material: savedMaterial }, color);
    }
    reloadOverlays();
    redrawSeedNeedleOverlays();
    renderDataTreeDebounced();
    _scheduleDataTreeSave(`viewer.color:${id}`);
    requestViewerVisualRefresh('tree-color');
    return true;
}
window.setDataTreeItemColor = setDataTreeItemColor;

function getItemGroup(id) {
    // Shift selection is a range operation, so its ordering domain must be
    // stable even while asynchronous segmentation/planning rows are being
    // hydrated.  The old fallback put most non-organ rows in one `other`
    // bucket, allowing a range to cross unrelated Data Tree branches and
    // making a later redraw appear to drop all but the first item.
    const value = String(id || '');
    if (value === 'ct') return 'image';
    if (value === 'ctv' || value.startsWith('ctv_')) return 'ctv';
    if (value === 'skin_surface') return 'segmentation';
    if (value.startsWith('organ_')) {
        const organ = dataTreeState.organs.find(item => item.id === value);
        return organ?.category || 'oar';
    }
    if (_isDataTreeMaskId(value)) {
        const mask = _maskStateEntry(value);
        const classification = _genericMaskClassification(mask);
        // A promoted generic mask is now represented by the effective CTV or
        // OAR Structure Set.  It must follow that branch for range selection
        // and group commands; only an unclassified generic mask remains in
        // the standalone mask group.
        if (classification === 'ctv' || classification === 'oar') return classification;
        return _maskBelongsToGroup('upload_masks', mask)
            ? 'upload_masks'
            : (_isGenericSegmentationMask(mask) ? 'generic_masks' : 'masks');
    }
    if (value.startsWith('seed_')) return 'planning_seeds';
    if (value.startsWith('needle_')) return 'planning_needles';
    if (value.startsWith('dose_iso_')) return 'dose_isosurfaces';
    if (value.startsWith('traj_') || value.startsWith('trajectory_')) {
        return 'planning_trajectories';
    }
    if (value === 'dose_overlay' || value === 'dvh') return 'planning';
    if (value.startsWith('planning_mesh_')) return 'planning_meshes';
    if ((dataTreeState.annotations || []).some(item => item.id === value)
        || (dataTreeState.exportArtifacts || []).some(item => item.id === value)) {
        return 'artifacts';
    }
    return 'other';
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
        } else {
            // A late async tree refresh may remove the old anchor.  The
            // current item must still become selected instead of making a
            // Shift-click appear to do nothing or leaving a stale selection.
            if (!event.ctrlKey) selectedItems.clear();
            selectedItems.add(id);
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
        'image', 'segmentation', 'ctv', 'oar', 'non_traversable', 'traversable',
        'planning', 'planning_trajectories', 'planning_seeds',
        'planning_needles', 'dose_isosurfaces', 'planning_meshes',
        'masks', 'generic_masks', 'upload_masks', 'artifacts',
    ]);
    if (groupIds.has(id)) {
        selectedItems.clear();
        showGroupContextMenu(event.clientX, event.clientY, id);
        return;
    }
    // A leaf context menu acts on the existing selection when the pointer is
    // already inside it, which is how a Windows-style Shift/Ctrl selection
    // reaches batch actions. A right-click outside the selection intentionally
    // starts a new single-item selection, so Delete cannot inherit unrelated
    // rows from a previous operation.
    if (!selectedItems.has(id)) {
        selectedItems.clear();
        selectedItems.add(id);
    }
    lastClickedId = id;
    // Show menu immediately
    showContextMenu(event.clientX, event.clientY);
}

function showGroupContextMenu(x, y, category) {
    hideContextMenu();

    // Determine group info based on category
    let catInfo, count;
    if (category === 'image') {
        catInfo = { label: _dtText('影像', 'Image'), icon: 'I' };
        count = state.ctLoaded ? 1 : 0;
    } else if (category === 'segmentation') {
        catInfo = { label: _dtText('分割结构', 'Segmentation'), icon: 'S' };
        count = _dataTreeGroupObjectIds('segmentation').length;
    } else if (category === 'ctv') {
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
    } else if (category === 'artifacts') {
        catInfo = { label: _dtText('工件与标注', 'Artifacts & Annotations'), icon: 'A' };
        count = _dataTreeGroupObjectIds('artifacts').length;
    } else if (category === 'masks' || category === 'generic_masks' || category === 'upload_masks') {
        catInfo = {
            label: category === 'upload_masks'
                ? _dtText('上传掩膜', 'Upload Mask')
                : _dtText('手动/阈值掩膜', 'Masks'),
            icon: '🎨',
        };
        count = Object.values(state.maskLabels || {})
            .filter(mask => category === 'masks'
                ? !_isGenericSegmentationMask(mask)
                : _maskBelongsToGroup(category, mask))
            .length;
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

    // Rename the CTV / OAR group node from its header context menu.
    if (category === 'ctv' || category === 'oar') {
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();renameDataTreeNode('${category}')">
            <span class="ctx-icon">&#9998;</span> ${_dtText('重命名', 'Rename')}</div>`;
        items += `<div class="ctx-menu-sep"></div>`;
    }

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

    // Structure classification changes are real backend transactions. The
    // group action is useful for imported masks whose initial class is wrong.
    if (category === 'oar' || category === 'ctv') {
        const destination = category === 'oar' ? 'ctv' : 'oar';
        const destinationLabel = destination.toUpperCase();
        if (_dataTreeGroupObjectIds(category).length) {
            items += `<div class="ctx-menu-item" onclick="hideContextMenu();_runDataTreeAction(moveDataTreeGroup('${category}', '${destination}'))">
                <span class="ctx-icon">&#8644;</span> ${_dtText(`移动全部到 ${destinationLabel}`, `Move all to ${destinationLabel}`)}</div>`;
        }
    }

    if (count > 0) {
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();_runDataTreeAction(exportDataTreeGroup('${category}'))">
            <span class="ctx-icon">&#8681;</span> ${_dtText('导出', 'Export')}</div>`;
        items += `<div class="ctx-menu-item ctx-menu-danger" onclick="hideContextMenu();_runDataTreeAction(deleteDataTreeGroup('${category}'))">
            <span class="ctx-icon">&#128465;</span> ${_dtText('删除真实数据', 'Delete data')}</div>`;
        items += `<div class="ctx-menu-sep"></div>`;
    }

    // Image and the abstract Segmentation collection do not own a separate
    // viewer state. Their children remain the authoritative visual nodes.
    if (category !== 'artifacts') {
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();setGroupVisibility('${category}',true)">
            <span class="ctx-icon">&#128065;</span> Show All</div>`;
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();setGroupVisibility('${category}',false)">
            <span class="ctx-icon">&#128064;</span> Hide All</div>`;
        items += `<div class="ctx-menu-sep"></div>`;
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();setGroupViewVisibility('${category}','2d',true)">
            <span class="ctx-icon">2D</span> Show in 2D</div>`;
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();setGroupViewVisibility('${category}','2d',false)">
            <span class="ctx-icon">2D</span> Hide in 2D</div>`;
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();setGroupViewVisibility('${category}','3d',true)">
            <span class="ctx-icon">3D</span> Show in 3D</div>`;
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();setGroupViewVisibility('${category}','3d',false)">
            <span class="ctx-icon">3D</span> Hide in 3D</div>`;
    }

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

    // Opacity belongs to visual groups only.
    if (!['image', 'segmentation'].includes(category)) {
        items += `<div class="ctx-menu-sep"></div>`;
        items += `<div class="ctx-menu-item" style="opacity:0.5;cursor:default;font-size:0.6rem;">
            <span class="ctx-icon">&#127912;</span> Opacity</div>`;
        for (const op of [100, 75, 50, 25]) {
            items += `<div class="ctx-menu-item" onclick="hideContextMenu();setGroupOpacityValue('${category}', ${op})">
                <span class="ctx-icon" style="opacity:${op / 100}">&#9632;</span> ${op}%</div>`;
        }
        items += `<label class="ctx-menu-item" onclick="event.stopPropagation()">
            <span class="ctx-icon">&#127912;</span> Group color
            <input type="color" value="${getGroupDisplayColor(category)}"
                aria-label="Group color"
                style="margin-left:auto;width:28px;height:20px;border:0;background:transparent;cursor:pointer"
                onchange="setGroupColor('${category}', this.value);hideContextMenu()">
        </label>`;
    }

    items += `<div class="ctx-menu-sep"></div>`;
    items += `<div class="ctx-menu-item" onclick="hideContextMenu();showAllOrgans()">
        <span class="ctx-icon">&#128065;</span> Show All Organs</div>`;

    menu.innerHTML = items;
    document.body.appendChild(menu);

    positionBrachyContextMenu(menu, x, y);

    activeContextMenu = menu;
}

 function soloGroup(category) {
    dataTreeState.organs.forEach(o => { o.visible = (o.category === category); });
    dataTreeState.ctv.visible = (category === 'ctv');
    _planningItems('seeds').forEach(s => { s.visible = (category === 'planning_seeds'); });
    _planningItems('needles').forEach(n => { n.visible = (category === 'planning_needles'); });
    _planningItems('doseLevels').forEach(d => { d.visible = (category === 'dose_isosurfaces'); });
    Object.entries(state.maskLabels || {}).forEach(([id, m]) => {
        m.visible = _maskBelongsToGroup(category, m) ? true : false;
    });
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
        else if (_isDataTreeMaskId(id)) {
            const m = _maskStateEntry(id);
            const groupVisible = _maskBelongsToGroup(category, m);
            applyMeshVisibility(mesh, m?.visible !== false && groupVisible, m?.opacity ?? 0.6);
        }
    });
    applyDataTreeViewVisibility();
    renderDataTree();
    if (state.ctLoaded) loadAllSlices();
}

async function groupReconstruct3D(category) {
    const scope = _captureViewerDataScope();
    // A manually uploaded mask can arrive before the label-volume request
    // populates the client tree. Hydrate the authoritative list first rather
    // than treating an empty list as a successful no-op.
    if (!Array.isArray(dataTreeState.organs) || dataTreeState.organs.length === 0) {
        try {
            const response = await fetch(API + '/viewer/organs', {
                headers: _viewerDataHeaders(scope.sessionId),
            });
            if (response.ok) {
                const payload = await response.json();
                if (!_viewerDataScopeIsCurrent(scope, true)) return { success: false, stale: true };
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
    if (!_viewerDataScopeIsCurrent(scope, true)) return { success: false, stale: true };
    const results = await Promise.allSettled(organs.map(organ => reconstructOrgan3D(organ.id, true)));
    if (!_viewerDataScopeIsCurrent(scope, true)) return { success: false, stale: true };
    return {
        success: results.some(result => result.status === 'fulfilled'),
        reconstructed: results.filter(result => result.status === 'fulfilled').length,
        total: organs.length,
    };
}

function getSelectedOrganIds() {
    // Keep the historical function name for callers, but return the complete
    // selected leaf snapshot. The old implementation rebuilt the selectable
    // list at each caller and several batch paths then effectively consumed
    // only the first visible organ after a render.
    return getSelectedDataTreeIds();
}

function getSelectedDataTreeIds() {
    // Return a detached, de-duplicated snapshot. Batch actions may trigger a
    // render or an async backend refresh; they must continue operating on the
    // selection that the user made, not on a live Set whose visible rows have
    // already changed.
    const selectable = new Set(getSelectableIds());
    return [...selectedItems].filter(id => selectable.has(id));
}

function resetDataTreeSelectionState() {
    // Selection and its Shift anchor are presentation state, not clinical
    // data. Clear both when a new Session is mounted so stale IDs cannot
    // affect the first batch action in the new case.
    selectedItems.clear();
    lastClickedId = null;
    renderDataTree();
}
window.resetDataTreeSelectionState = resetDataTreeSelectionState;

function _dtText(zh, en) {
    if (typeof window._t === 'function') return window._t(zh, en);
    try {
        if (typeof effectiveUiLanguage === 'function') {
            return effectiveUiLanguage() === 'zh' ? zh : en;
        }
    } catch (_) {}
    return document.documentElement.lang?.toLowerCase().startsWith('zh') ? zh : en;
}

// Localized status badge text for Data Tree nodes.
function _dtStatusText(status) {
    const map = {
        'not_generated': _dtText('未生成', 'Not generated'),
        'stale': _dtText('已过期', 'Stale'),
        'expired': _dtText('已过期', 'Expired'),
        'loading': _dtText('进行中', 'Loading'),
        'error': _dtText('错误', 'Error'),
    };
    return map[status] || String(status || '').replace('_', ' ');
}

function _findDataTreeNode(id) {
    if (id === 'ct') return dataTreeState.ct;
    if (id === 'skin_surface') return dataTreeState.skin;
    if (id === 'dose' || id === 'dose_overlay') {
        return dataTreeState.planning?.doseOverlay || dataTreeState.dose;
    }
    if (id === 'dvh') return dataTreeState.planning?.dvh;
    if (id === 'ctv') return dataTreeState.ctv;
    if (id.startsWith('ctv_')) return dataTreeState.ctvLabels?.[id] || null;
    if (id.startsWith('organ_')) return dataTreeState.organs.find(item => item.id === id) || null;
    if (_isDataTreeMaskId(id)) {
        return _maskStateEntry(id);
    }
    for (const key of ['trajectories', 'seeds', 'needles', 'doseLevels', 'meshes']) {
        const item = _planningItems(key).find(value => {
            if (key === 'doseLevels') return `dose_iso_${value.threshold}` === id;
            return String(value.id) === String(id);
        });
        if (item) return item;
    }
    return (dataTreeState.annotations || []).find(item => item.id === id)
        || (dataTreeState.exportArtifacts || []).find(item => item.id === id)
        || null;
}

function _dataTreeObjectId(id, purpose = 'export') {
    const node = _findDataTreeNode(id);
    if (id === 'ct') return 'image:ct';
    if (id === 'skin_surface') return String(node?.objectId || 'skin_surface:guide');
    if (id === 'dose' || id === 'dose_overlay') return 'dose:volume';
    if (id === 'dvh') return purpose === 'delete' ? 'dvh' : 'dvh:data';
    if (id === 'ctv') return String(
        node?.objectId || window._ctvObjectMap?.[1] || 'structure:ctv:1',
    );
    if (id.startsWith('ctv_') || id.startsWith('organ_')) {
        return String(node?.objectId || id);
    }
    if (_isDataTreeMaskId(id)) {
        const rawMaskId = String(id).replace(/^mask:/, '');
        return String(node?.objectId || `mask:${rawMaskId}`);
    }
    if (id.startsWith('seed_')) return `seed:${id}`;
    if (id.startsWith('needle_')) return `needle:${id}`;
    if (id.startsWith('traj_') || id.startsWith('trajectory_')) return `trajectory:${id}`;
    if (id.startsWith('dose_iso_')) {
        const level = _planningItems('doseLevels').find(
            item => `dose_iso_${item.threshold}` === id,
        );
        const threshold = Number(level?.thresholdGy ?? level?.threshold ?? id.replace('dose_iso_', ''));
        return `dose_iso:${Number.isFinite(threshold) ? threshold : id.replace('dose_iso_', '')}`;
    }
    if (node?.source === 'surgical_guide' || id.includes('surgical_guide')) {
        return 'surgical_guide:active';
    }
    if (node?.type === 'manual_annotation' || id.startsWith('annotation_')) {
        return `annotation:${id}`;
    }
    return String(node?.objectId || id);
}

function _dataTreeGroupObjectIds(category) {
    if (category === 'image') return state.ctLoaded ? ['image:ct'] : [];
    if (category === 'segmentation') {
        return [
            ..._dataTreeGroupObjectIds('ctv'),
            ..._dataTreeGroupObjectIds('oar'),
            ...(dataTreeState.skin.loaded ? [_dataTreeObjectId('skin_surface')] : []),
            ..._dataTreeGroupObjectIds('upload_masks'),
            ..._dataTreeGroupObjectIds('generic_masks'),
            ..._dataTreeGroupObjectIds('masks'),
        ];
    }
    if (category === 'ctv') {
        const labels = Object.values(dataTreeState.ctvLabels || {});
        return (labels.length ? labels : [dataTreeState.ctv])
            .map(item => String(
                item?.objectId
                || (item === dataTreeState.ctv
                    ? window._ctvObjectMap?.[1] || 'structure:ctv:1'
                    : ''),
            ))
            .filter(Boolean);
    }
    if (category === 'oar') {
        return dataTreeState.organs.map(item => String(item.objectId || item.id));
    }
    if (category === 'generic_masks' || category === 'upload_masks' || category === 'masks') {
        return Object.entries(state.maskLabels || {})
            .filter(([, item]) => category === 'masks'
                ? !_isGenericSegmentationMask(item)
                : _maskBelongsToGroup(category, item))
            .map(([id, item]) => String(item?.objectId || `mask:${id}`));
    }
    if (category === 'non_traversable' || category === 'traversable') {
        return dataTreeState.organs
            .filter(item => item.category === category)
            .map(item => String(item.objectId || item.id));
    }
    if (category === 'planning_trajectories') return ['group:planning:trajectories'];
    if (category === 'planning_seeds') return ['group:planning:seeds'];
    if (category === 'planning_needles') return ['group:planning:needles'];
    if (category === 'dose_isosurfaces') return ['group:dose:isosurfaces'];
    if (category === 'planning') return ['group:planning'];
    if (category === 'planning_meshes') {
        return _planningItems('meshes')
            .map(item => _dataTreeObjectId(item.id))
            .filter(Boolean);
    }
    if (category === 'artifacts') {
        return [
            ...(dataTreeState.annotations || []),
            ...(dataTreeState.exportArtifacts || []),
        ].map(item => _dataTreeObjectId(item.id)).filter(Boolean);
    }
    return [];
}

function _dataTreeExportGroups(category) {
    const mapping = {
        image: 'group:images',
        segmentation: 'group:structures',
        ctv: 'group:structures:ctv',
        oar: 'group:structures:oar',
        masks: 'group:structures:masks',
        generic_masks: 'group:structures:masks',
        upload_masks: 'group:structures:masks',
        planning: 'group:planning',
        planning_trajectories: 'group:planning:trajectories',
        planning_seeds: 'group:planning:seeds',
        planning_needles: 'group:planning:needles',
        dose_isosurfaces: 'group:dose:isosurfaces',
    };
    return mapping[category] ? [mapping[category]] : [];
}

function _structureAppearanceMap() {
    const result = {};
    [
        ...Object.values(dataTreeState.ctvLabels || {}),
        ...(dataTreeState.organs || []),
    ].forEach(item => {
        if (!item?.objectId) return;
        result[String(item.objectId)] = {
            color: item.color,
            opacity: item.opacity,
            visible: item.visible,
            visible2D: item.visible2D,
            visible3D: item.visible3D,
            category: item.category,
        };
    });
    return result;
}

function _applyStructureAppearanceMap(appearance) {
    [
        ...Object.values(dataTreeState.ctvLabels || {}),
        ...(dataTreeState.organs || []),
    ].forEach(item => {
        const saved = appearance[String(item?.objectId || '')];
        if (!saved) return;
        item.color = saved.color || item.color;
        item.opacity = Number.isFinite(Number(saved.opacity)) ? Number(saved.opacity) : item.opacity;
        item.visible = saved.visible !== false;
        item.visible2D = saved.visible2D !== false;
        item.visible3D = saved.visible3D !== false;
        // Traversability is an OAR presentation concern. Do not leak it into
        // the CTV business classification when an OAR is promoted.
        if (item.source === 'oar' && saved.category) item.category = saved.category;
    });
}

function _disposeSceneMesh(id) {
    const mesh = scene3D?.meshes?.[id];
    if (!mesh) return;
    try { scene3D.scene?.remove(mesh); } catch (_) {}
    mesh.traverse?.(child => {
        child.geometry?.dispose?.();
        const materials = Array.isArray(child.material) ? child.material : [child.material];
        materials.forEach(material => material?.dispose?.());
    });
    mesh.geometry?.dispose?.();
    const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    materials.forEach(material => material?.dispose?.());
    delete scene3D.meshes[id];
}

function _canonicalDataTreeObjectId(value) {
    const raw = String(value || '').trim();
    if (raw.startsWith('mask_')) return `mask:${raw.slice(5)}`;
    return raw;
}

function _purgeDeletedDataTreePresentation(objectIds) {
    const targets = new Set(
        (objectIds || []).map(_canonicalDataTreeObjectId).filter(Boolean),
    );
    if (!targets.size) return;
    const matches = node => targets.has(_canonicalDataTreeObjectId(
        node?.objectId || node?.object_id || node?.id,
    ));

    // Generic masks use a durable `mask:*` object ID even when they are
    // displayed as a CTV/OAR label.  Remove every local representation before
    // the fresh server hydration starts, so a user cannot act on a ghost row.
    Object.entries(state.maskLabels || {}).forEach(([id, mask]) => {
        if (!matches(mask)) return;
        _disposeSceneMesh(_maskSceneMeshId(id));
        _disposeSceneMesh(id);
        delete state.maskLabels[id];
        delete genericMaskVolumeData[id];
    });

    Object.entries(dataTreeState.ctvLabels || {}).forEach(([id, label]) => {
        if (!matches(label)) return;
        _disposeSceneMesh(id);
        delete dataTreeState.ctvLabels[id];
    });
    dataTreeState.organs = (dataTreeState.organs || []).filter(organ => {
        if (!matches(organ)) return true;
        _disposeSceneMesh(organ.id);
        return false;
    });

    if (window._ctvObjectMap && typeof window._ctvObjectMap === 'object') {
        Object.entries(window._ctvObjectMap).forEach(([labelId, objectId]) => {
            if (targets.has(_canonicalDataTreeObjectId(objectId))) {
                delete window._ctvObjectMap[labelId];
            }
        });
    }
    [...selectedItems].forEach(id => {
        const objectId = _canonicalDataTreeObjectId(_dataTreeObjectId(id, 'delete'));
        if (targets.has(objectId)) selectedItems.delete(id);
    });
}

function _clearInvalidatedPlanningPresentation(invalidated = []) {
    const flags = new Set(invalidated || []);
    if (flags.has('all_case_data') || flags.has('planning')) {
        if (typeof clearPlanningVisualization === 'function') clearPlanningVisualization();
    }
    if (flags.has('all_case_data') || flags.has('dose') || flags.has('dvh') || flags.has('evaluation')) {
        if (typeof clearDoseOverlayRuntime === 'function') clearDoseOverlayRuntime();
        state.doseOverlay = null;
        state.dvhData = null;
        dataTreeState.planning.doseOverlay = null;
        dataTreeState.planning.dvh = null;
        dataTreeState.planning.doseLevels = [];
        Object.keys(scene3D?.meshes || {})
            .filter(id => id.startsWith('dose_iso_'))
            .forEach(_disposeSceneMesh);
        const dvhNode = document.getElementById('dvhChart');
        if (dvhNode && window.Plotly?.purge) window.Plotly.purge(dvhNode);
    }
    if (flags.has('surgical_guide') || flags.has('guide')) {
        if (typeof window.invalidateSurgicalGuidePresentation === 'function') {
            window.invalidateSurgicalGuidePresentation();
        }
    }
}

async function _refreshAfterDataMutation(
    payload,
    appearance,
    expectedSessionId,
    options = {},
) {
    if (String(expectedSessionId) !== _viewerDataSessionId()) return false;
    const invalidated = [
        ...(payload?.invalidated || []),
        ...((payload?.results || []).flatMap(result => result?.invalidated || [])),
    ];
    const objectIds = [...new Set((options.objectIds || []).map(String))];
    const allCaseData = invalidated.includes('all_case_data');
    const structureMutation = Boolean(payload?.structures)
        || objectIds.some(id => id.startsWith('structure:'));
    const genericMaskMutation = invalidated.includes('generic_mask')
        || objectIds.some(id => _isDataTreeMaskId(id));
    const planningMutation = invalidated.includes('planning')
        || objectIds.some(id => (
            id === 'planning'
            || id.startsWith('group:planning')
            || id.startsWith('needle:')
            || id.startsWith('needle_')
            || id.startsWith('seed:')
            || id.startsWith('seed_')
            || id.startsWith('trajectory:')
            || id.startsWith('trajectory_')
        ));

    // Server confirmation is the mutation boundary.  Cancel earlier
    // label/mask requests before they can write an old catalogue back into the
    // tree, and remove the confirmed rows locally while the fresh payload is
    // loading.  This applies to every structural Data Tree delete/move, not
    // just the original CTV upload case.
    if (structureMutation || genericMaskMutation) {
        _purgeDeletedDataTreePresentation(objectIds);
        invalidateViewerDataLoads();
    }

    if (allCaseData) {
        if (typeof clearClientWorkspace === 'function') {
            clearClientWorkspace({ clearReport: true, deferDisposal: true });
        }
        if (state) state.sessionId = expectedSessionId;
        _scheduleDataTreeSave('data_tree.ct_deleted');
        return true;
    }

    // When a structure is reclassified but the user chose NOT to replan
    // (preserveDoseDvh), keep the existing dose/DVH/surgical-guide visible and
    // only mark them stale. Clearing them made a simple "move to CTV/OAR"
    // wipe the dose heatmap, DVH curve, and guide from the viewer and data
    // tree even though the needle geometry was unchanged.
    if (options.preserveDoseDvh === true) {
        _clearInvalidatedPlanningPresentation(
            invalidated.filter(item => !['dose', 'dvh', 'evaluation', 'surgical_guide', 'guide'].includes(item)),
        );
    } else {
        _clearInvalidatedPlanningPresentation(invalidated);
    }
    if (structureMutation) {
        Object.keys(scene3D?.meshes || {})
            .filter(id => id === 'ctv' || id.startsWith('ctv_') || id.startsWith('organ_'))
            .forEach(_disposeSceneMesh);
        if (window.SessionCache) {
            await window.SessionCache.invalidate(
                expectedSessionId, 'labels', 'volume',
            ).catch(() => {});
        }
        await loadLabelVolumes({
            sessionId: expectedSessionId,
            forceFresh: true,
            preserveViewerState: true,
        });
        if (String(expectedSessionId) !== _viewerDataSessionId()) return false;
        _applyStructureAppearanceMap(appearance || {});
        // Rebuilding the moved structure's 3D mesh is required: the CTV/OAR
        // meshes were disposed above, and loadLabelVolumes only refreshes the
        // 2D overlays and data tree. Without this, a "Move to CTV/OAR" left
        // the moved mask gone from the 3D viewer.
        try {
            if (typeof startSegmentationMeshPrewarm === 'function') {
                startSegmentationMeshPrewarm('ctv', { force: true, batchSize: 3 });
                startSegmentationMeshPrewarm('oar', { force: true, batchSize: 3 });
            }
        } catch (_) {}
    }

    // A generic mask that remains an independent Segmentation row does not
    // require a CTV/OAR label-volume reload.  Still reconcile its catalogue
    // after a backend mutation; the prior implementation left open masks in
    // the client until a later unrelated viewer refresh.
    if (genericMaskMutation && !structureMutation) {
        await hydrateGenericMasksFromServer(_captureViewerDataScope(expectedSessionId));
        if (String(expectedSessionId) !== _viewerDataSessionId()) return false;
    }

    if (planningMutation && typeof refreshPlanningUI === 'function') {
        if (typeof clearPlanningVisualization === 'function') {
            clearPlanningVisualization();
        }
        await refreshPlanningUI({
            sessionId: expectedSessionId,
            skipLabelLoad: true,
            preserveViewerState: true,
            switchToViewers: false,
            backgroundRestore: true,
            autoGenerateGuide: false,
        });
        if (String(expectedSessionId) !== _viewerDataSessionId()) return false;
    }

    if (objectIds.some(id => id.startsWith('annotation:'))) {
        const deleted = new Set(objectIds.map(id => id.split(':', 2)[1]));
        state.annotations = (state.annotations || []).filter(
            (row, index) => !deleted.has(String(row?.id || `annotation_${index + 1}`)),
        );
    }
    if (
        objectIds.some(id => id.startsWith('screenshot:') || id.startsWith('figure:') || id.startsWith('report'))
        || invalidated.some(id => ['annotation', 'screenshot', 'report'].includes(id))
    ) {
        const removedFiles = new Set(
            objectIds
                .filter(id => id.startsWith('screenshot:') || id.startsWith('figure:'))
                .map(id => id.split(':', 2)[1]),
        );
        if (removedFiles.size && Array.isArray(window.reportForm?.figures)) {
            window.reportForm.figures = window.reportForm.figures.filter(figure => {
                const url = String(figure?._serverUrl || figure?.dataUrl || '');
                return ![...removedFiles].some(filename => url.includes(filename));
            });
            try { if (typeof renderReportEditor === 'function') renderReportEditor(); } catch (_) {}
            try { if (typeof _updateReportPreview === 'function') _updateReportPreview(); } catch (_) {}
        }
        if (
            objectIds.some(id => ['report', 'report:data', 'group:report'].includes(id))
            && typeof _newEmptyReportForm === 'function'
        ) {
            window.reportForm = _newEmptyReportForm();
            try { if (typeof renderReportEditor === 'function') renderReportEditor(); } catch (_) {}
            try { if (typeof _updateReportPreview === 'function') _updateReportPreview(); } catch (_) {}
        }
        _dataTreeArtifactCatalogSession = '';
        await hydrateDataTreeArtifactCatalog({ force: true });
        if (String(expectedSessionId) !== _viewerDataSessionId()) return false;
    }
    if (payload?.artifact_status) {
        dataTreeState.planning.artifactStatus = payload.artifact_status;
        if (typeof _syncManualSafetyState === 'function') {
            _syncManualSafetyState({ artifact_status: payload.artifact_status });
        }
    }
    reconcileSegmentationViewerState({
        sessionId: expectedSessionId,
        reason: 'data-tree-mutation',
    });
    renderDataTree();
    syncSceneAppearanceFromDataTree();
    _scheduleDataTreeSave('data_tree.backend_mutation');
    return true;
}

async function moveSelectedStructures(classification, objectIds = null) {
    const expectedSessionId = _viewerDataSessionId();
    const appearance = _structureAppearanceMap();
    // Snapshot the caller's IDs before the confirmation dialog or hydration
    // can redraw the tree. An explicit empty array must remain empty; it
    // must never fall back to a newer live selection.
    const selected = (objectIds == null ? getSelectedDataTreeIds()
        : Array.from(objectIds))
        .map(id => _dataTreeObjectId(id))
        .filter(id => id.startsWith('structure:'));
    if (!selected.length) return false;
    const response = await fetch(API + '/data/structures/classification', {
        method: 'PATCH',
        headers: {
            ..._viewerDataHeaders(expectedSessionId),
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            session_id: expectedSessionId,
            object_ids: selected,
            classification,
        }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.success === false) {
        throw new Error(payload.error || _dtText('结构分类更新失败', 'Structure classification failed'));
    }
    // Ask the user whether to replan with the new structure masks. Choosing
    // "No" (or dismissing) keeps the moved structures visible under their new
    // parent's default presentation and preserves the current dose/DVH/guide
    // as stale-but-visible evidence; choosing "Yes" replans with the new mask.
    const shouldReplan = await _confirmAction(
        _dtText(
            `结构分类已更改。是否基于新的 ${classification.toUpperCase()} 掩码重新规划？选择“否”将保留当前剂量显示。`,
            `Structure classification changed. Replan with the new ${classification.toUpperCase()} mask? Choosing "No" keeps the current dose display.`,
        ),
        null,
        {
            yesZh: '重新规划',
            yesEn: 'Replan',
            noZh: '仅移动',
            noEn: 'Just move',
            titleZh: '结构分类已更改',
            titleEn: 'Structure classification changed',
        },
    );
    await _refreshAfterDataMutation(payload, appearance, expectedSessionId, {
        objectIds: selected,
        // Preserve dose/DVH unless the user explicitly chose to replan.
        preserveDoseDvh: shouldReplan !== true,
    });
    selectedItems.clear();
    if (shouldReplan) {
        try {
            await replanAfterStructureChange(expectedSessionId);
        } catch (error) {
            console.warn('[data-tree] replan after structure move failed:', error);
            addChat('error', _dtText(
                `重新规划失败：${error.message}；结构已移动，可稍后重试。`,
                `Replan failed: ${error.message}; the structure was moved and can be replanned later.`,
            ));
        }
    }
    addChat('system', _dtText(
        `已将 ${selected.length} 个结构移动到 ${classification.toUpperCase()}；相关剂量、DVH、评估和报告已标记为需要更新。`,
        `${selected.length} structure(s) moved to ${classification.toUpperCase()}; related dose, DVH, evaluation, and report results are now stale.`,
    ));
    return true;
}

async function replanAfterStructureChange(expectedSessionId) {
    const ctPath = typeof state !== 'undefined' ? state.ctPath : '';
    if (!ctPath) throw new Error('No CT image available for replanning');
    if (typeof refreshPlanningUI !== 'function') throw new Error('Planning refresh unavailable');
    await refreshPlanningUI({
        sessionId: expectedSessionId,
        skipLabelLoad: false,
        preserveViewerState: true,
        switchToViewers: false,
        backgroundRestore: false,
        autoGenerateGuide: true,
    });
}

async function exportSelectedDataTreeItems(objectIds = null) {
    // Keep export tied to the selection that opened the menu, even if the
    // asynchronous export dialog causes a Data Tree rerender.
    const ids = (objectIds == null ? getSelectedDataTreeIds() : Array.from(objectIds))
        .map(id => _dataTreeObjectId(id));
    const clean = [...new Set(ids.filter(Boolean))];
    if (!clean.length || typeof window.openSessionExportDialog !== 'function') return false;
    await window.openSessionExportDialog({
        sessionId: _viewerDataSessionId(),
        objectIds: clean,
    });
    return true;
}

async function exportDataTreeGroup(category) {
    if (typeof window.openSessionExportDialog !== 'function') return false;
    const groupIds = _dataTreeExportGroups(category);
    const objectIds = groupIds.length ? null : _dataTreeGroupObjectIds(category);
    await window.openSessionExportDialog({
        sessionId: _viewerDataSessionId(),
        groupIds,
        objectIds,
    });
    return true;
}

async function deleteSelectedDataTreeItems(objectIds = null, options = {}) {
    const expectedSessionId = _viewerDataSessionId();
    const appearance = _structureAppearanceMap();
    // Resolve one detached batch snapshot. A session hydration/render callback
    // must not change which objects a destructive operation targets while the
    // confirmation dialog is open.
    const ids = [...new Set((objectIds == null
        ? getSelectedDataTreeIds()
        : Array.from(objectIds))
        .map(id => _dataTreeObjectId(id, 'delete')).filter(Boolean))];
    if (!ids.length) return false;
    const confirmed = typeof window._confirmAction === 'function'
        ? await window._confirmAction(
            `删除选中的 ${ids.length} 项真实数据？相关下游结果可能同时失效。`,
            `Delete ${ids.length} selected data item(s)? Related downstream results may also become stale.`,
            {
                titleZh: '删除数据',
                titleEn: 'Delete data',
                yesZh: '删除',
                yesEn: 'Delete',
                noZh: '取消',
                noEn: 'Cancel',
            },
        )
        : false;
    if (!confirmed) return false;
    const mutationKeys = ids.map(_canonicalDataTreeObjectId).filter(Boolean);
    if (mutationKeys.some(id => pendingDataTreeDeleteIds.has(id))) {
        addChat('system', _dtText(
            '所选数据正在删除中，请等待当前操作完成。',
            'The selected data is already being deleted. Please wait for the current operation to finish.',
        ));
        return false;
    }
    mutationKeys.forEach(id => pendingDataTreeDeleteIds.add(id));
    try {
        const response = await fetch(API + '/data/objects/batch-delete', {
            method: 'POST',
            headers: {
                ..._viewerDataHeaders(expectedSessionId),
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                session_id: expectedSessionId,
                object_ids: ids,
                recursive_groups: options.recursiveGroups === true,
            }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.success === false) {
            throw new Error(payload.error || _dtText('删除失败', 'Delete failed'));
        }
        const returnedIds = (payload.results || [])
            .map(result => String(result?.object_id || ''))
            .filter(Boolean);
        await _refreshAfterDataMutation(payload, appearance, expectedSessionId, {
            // Prefer server-canonical IDs when available.  This is essential
            // for a promoted upload whose visual CTV label is `ctv_1` but its
            // durable object identity is `mask:<upload-label-id>`.
            objectIds: [...new Set([...ids, ...returnedIds])],
        });
        selectedItems.clear();
        addChat('system', _dtText(
            `已删除 ${ids.length} 项数据。`,
            `${ids.length} data item(s) deleted.`,
        ));
        return true;
    } finally {
        mutationKeys.forEach(id => pendingDataTreeDeleteIds.delete(id));
    }
}

async function deleteDataTreeGroup(category) {
    // Expand a Data Tree parent to its stable descendants on the client.
    // The API deliberately rejects an unqualified parent alias, so a stale
    // selection cannot promote a leaf deletion into a category deletion.
    return deleteSelectedDataTreeItems(_dataTreeGroupObjectIds(category), {
        recursiveGroups: true,
    });
}

async function moveDataTreeGroup(category, classification) {
    return moveSelectedStructures(classification, _dataTreeGroupObjectIds(category));
}

async function _refreshDataTreeAfterMissingObject(expectedSessionId) {
    if (String(expectedSessionId || '') !== _viewerDataSessionId()) return false;
    // An item may have been removed by a concurrent browser tab or a prior
    // request whose visual refresh was interrupted.  Treat a known 404 as a
    // reconciliation event, not as a clinical-operation failure.
    invalidateViewerDataLoads();
    const refreshes = [
        loadLabelVolumes({
            sessionId: expectedSessionId,
            forceFresh: true,
            preserveViewerState: true,
        }),
        hydrateDataTreeArtifactCatalog({ force: true }),
    ];
    if (typeof refreshPlanningUI === 'function') {
        refreshes.push(refreshPlanningUI({
            sessionId: expectedSessionId,
            skipLabelLoad: true,
            preserveViewerState: true,
            switchToViewers: false,
            backgroundRestore: true,
            autoGenerateGuide: false,
        }));
    }
    await Promise.allSettled(refreshes);
    if (String(expectedSessionId || '') !== _viewerDataSessionId()) return false;
    reconcileSegmentationViewerState({
        sessionId: expectedSessionId,
        reason: 'data-tree-missing-object-reconcile',
    });
    renderDataTree();
    return true;
}

async function _runDataTreeAction(action) {
    try {
        return await Promise.resolve(action);
    } catch (error) {
        console.error('[data-tree] action failed', error);
        const message = String(error?.message || error || '');
        if (/not found|no longer exists|missing/i.test(message)) {
            const reconciled = await _refreshDataTreeAfterMissingObject(_viewerDataSessionId());
            if (reconciled) {
                addChat('system', _dtText(
                    '该数据已不在服务器中，已按最新状态刷新 Data Tree 和查看器。',
                    'This data no longer exists on the server. The Data Tree and viewers were refreshed to the latest state.',
                ));
                return false;
            }
        }
        addChat('error', _dtText(
            `数据操作失败：${message}`,
            `Data operation failed: ${message}`,
        ));
        return false;
    }
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
    const isStructureSelection = selIds.every(
        id => id === 'ctv' || id === 'skin_surface'
            || id.startsWith('ctv_') || id.startsWith('organ_'),
    );
    const isPlanningItem = selIds.every(id =>
        id.startsWith('seed_') || id.startsWith('needle_')
        || id.startsWith('dose_iso_') || id.startsWith('traj_')
        || id.startsWith('trajectory_') || id === 'dose_overlay'
        || id === 'dose' || id === 'dvh'
        || !!_findDataTreeNode(id)?.planningId,
    );
    const isNonVisualArtifact = selIds.every(id => (
        dataTreeState.exportArtifacts || []
    ).some(item => item.id === id));

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
    if (isStructureSelection) {
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

    if (isSingle && (
        firstId.startsWith('needle_')
        || firstId.startsWith('traj_')
        || firstId.startsWith('trajectory_')
    )) {
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();addManualSeedToPlanningNode('${firstId}', {source:'data_tree_context'})">
            <span class="ctx-icon">&#10133;</span> ${_dtText('在此针道添加粒子', 'Add seed to this needle')}</div>`;
    }

    if (isSingle && firstId.startsWith('needle_')) {
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();restoreNeedleToAlgorithm('${firstId}')">
            <span class="ctx-icon">&#8634;</span> Restore algorithm position</div>`;
        items += `<div class="ctx-menu-sep"></div>`;
    }

    // Manual/threshold masks: rename, move to a structure, or delete.
    // Masks are display-only (no dose/planning participation), so they offer
    // the same presentation controls as OAR/CTV plus rename.
    const isMaskSelection = selIds.every(id => {
        const value = String(id);
        return _isDataTreeMaskId(value);
    });
    if (isMaskSelection) {
        if (isSingle) {
            items += `<div class="ctx-menu-item" onclick="hideContextMenu();renameDataTreeMask('${firstId}')">
                <span class="ctx-icon">&#9998;</span> ${_dtText('重命名', 'Rename')}</div>`;
            items += `<div class="ctx-menu-item" onclick="hideContextMenu();reconstructOrgan3D('${firstId}')">
                <span class="ctx-icon">&#9638;</span> ${_dtText('3D 重建', '3D Reconstruct')}</div>`;
        } else {
            items += `<div class="ctx-menu-item" onclick="hideContextMenu();batchReconstruct3D()">
                <span class="ctx-icon">&#9638;</span> ${_dtText('3D 重建全部', '3D Reconstruct All')}</div>`;
        }
        items += `<div class="ctx-menu-sep"></div>`;
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();_runDataTreeAction(moveSelectedMasks('ctv'))">
            <span class="ctx-icon">&#8644;</span> ${_dtText('移动到 CTV', 'Move to CTV')}</div>`;
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();_runDataTreeAction(moveSelectedMasks('oar'))">
            <span class="ctx-icon">&#8644;</span> ${_dtText('移动到 OAR', 'Move to OAR')}</div>`;
        items += `<div class="ctx-menu-sep"></div>`;
        if (isSingle) {
            items += `<div class="ctx-menu-item ctx-menu-danger" onclick="hideContextMenu();_runDataTreeAction(deleteDataTreeMask('${firstId}'))">
                <span class="ctx-icon">&#128465;</span> ${_dtText('删除掩膜', 'Delete mask')}</div>`;
        }
    }

    // Change Color (for single item: organs, CTV labels, or planning items)
    if (isSingle && (firstId === 'skin_surface' || firstId.startsWith('organ_') || firstId.startsWith('ctv_') || isPlanningItem || _isDataTreeMaskId(firstId))) {
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();openColorPicker('${firstId}')">
            <span class="ctx-icon">&#127912;</span> Change Color</div>`;
        items += `<div class="ctx-menu-sep"></div>`;
    }

    // Universal rename for any single leaf node (CTV label, OAR, seed, needle,
    // trajectory, dose iso-surface, planning mesh, annotation, mask). Masks
    // already offer Rename above; this adds it for every other node type.
    if (isSingle && !_isDataTreeMaskId(firstId) && !['ctv', 'oar'].includes(firstId)
        && (firstId.startsWith('organ_') || firstId.startsWith('ctv_') || firstId.startsWith('seed_')
            || firstId.startsWith('needle_') || firstId.startsWith('traj_') || firstId.startsWith('trajectory_')
            || firstId.startsWith('dose_iso_') || firstId.startsWith('planning_mesh_')
            || firstId === 'skin_surface'
            || firstId === 'dose_overlay')) {
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();renameDataTreeNode('${firstId}')">
            <span class="ctx-icon">&#9998;</span> ${_dtText('重命名', 'Rename')}</div>`;
        items += `<div class="ctx-menu-sep"></div>`;
    }

    // OAR traversability remains a presentation classification. CTV/OAR is a
    // clinical structure classification and therefore uses the backend
    // transaction below instead of the legacy local category assignment.
    if (hasOrgans) {
        for (const [catKey, catInfo] of Object.entries(ORGAN_CATEGORIES)) {
            if (catKey === 'ctv') continue;
            items += `<div class="ctx-menu-item" onclick="hideContextMenu();batchMoveToCategory('${catKey}')">
                <span class="ctx-icon">${catInfo.icon}</span> Move to ${catInfo.label}</div>`;
        }
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();_runDataTreeAction(moveSelectedStructures('ctv'))">
            <span class="ctx-icon">&#8644;</span> ${_dtText('移动到 CTV', 'Move to CTV')}</div>`;
        items += `<div class="ctx-menu-sep"></div>`;
    }
    if (isCTVOnly) {
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();_runDataTreeAction(moveSelectedStructures('oar'))">
            <span class="ctx-icon">&#8644;</span> ${_dtText('移动到 OAR', 'Move to OAR')}</div>`;
        items += `<div class="ctx-menu-sep"></div>`;
    }

    if (isNonVisualArtifact) {
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();_runDataTreeAction(exportSelectedDataTreeItems())">
            <span class="ctx-icon">&#8681;</span> ${_dtText('导出', 'Export')}</div>`;
        items += `<div class="ctx-menu-item ctx-menu-danger" onclick="hideContextMenu();_runDataTreeAction(deleteSelectedDataTreeItems())">
            <span class="ctx-icon">&#128465;</span> ${_dtText('删除真实数据', 'Delete data')}</div>`;
        items += `<div class="ctx-menu-sep"></div>`;
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();selectedItems.clear();renderDataTree();">
            <span class="ctx-icon">&#10005;</span> ${_dtText('清除选择', 'Clear selection')}</div>`;
        menu.innerHTML = items;
        document.body.appendChild(menu);
        positionBrachyContextMenu(menu, x, y);
        activeContextMenu = menu;
        window.__brachyContextMenuElement = menu;
        return;
    }

    // Visibility
    items += `<div class="ctx-menu-item" onclick="hideContextMenu();batchToggleVisibility(true)">
        <span class="ctx-icon">&#128065;</span> Show Selected</div>`;
    items += `<div class="ctx-menu-item" onclick="hideContextMenu();batchToggleVisibility(false)">
        <span class="ctx-icon">&#128064;</span> Hide Selected</div>`;
    items += `<div class="ctx-menu-sep"></div>`;
    items += `<div class="ctx-menu-item" onclick="hideContextMenu();batchSetViewVisibility('2d',true)">
        <span class="ctx-icon">2D</span> Show in 2D</div>`;
    items += `<div class="ctx-menu-item" onclick="hideContextMenu();batchSetViewVisibility('2d',false)">
        <span class="ctx-icon">2D</span> Hide in 2D</div>`;
    items += `<div class="ctx-menu-item" onclick="hideContextMenu();batchSetViewVisibility('3d',true)">
        <span class="ctx-icon">3D</span> Show in 3D</div>`;
    items += `<div class="ctx-menu-item" onclick="hideContextMenu();batchSetViewVisibility('3d',false)">
        <span class="ctx-icon">3D</span> Hide in 3D</div>`;

    // Colorbar visibility for the dose overlay node (2D and 3D).
    if (isSingle && firstId === 'dose_overlay') {
        const doseNode = dataTreeState?.planning?.doseOverlay;
        const cb2d = doseNode?.colorbarVisible2D !== false;
        const cb3d = doseNode?.colorbarVisible3D !== false;
        items += `<div class="ctx-menu-sep"></div>`;
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();setDoseColorbarViewVisibility('2d',true)">
            <span class="ctx-icon">${cb2d ? '&#9745;' : '&#9744;'}</span> ${_dtText('显示 2D Color Bar', 'Show 2D Color Bar')}</div>`;
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();setDoseColorbarViewVisibility('2d',false)">
            <span class="ctx-icon">${cb2d ? '&#9744;' : '&#9745;'}</span> ${_dtText('隐藏 2D Color Bar', 'Hide 2D Color Bar')}</div>`;
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();setDoseColorbarViewVisibility('3d',true)">
            <span class="ctx-icon">${cb3d ? '&#9745;' : '&#9744;'}</span> ${_dtText('显示 3D Color Bar', 'Show 3D Color Bar')}</div>`;
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();setDoseColorbarViewVisibility('3d',false)">
            <span class="ctx-icon">${cb3d ? '&#9744;' : '&#9745;'}</span> ${_dtText('隐藏 3D Color Bar', 'Hide 3D Color Bar')}</div>`;
    }

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

    items += `<div class="ctx-menu-item" onclick="hideContextMenu();_runDataTreeAction(exportSelectedDataTreeItems())">
        <span class="ctx-icon">&#8681;</span> ${_dtText('导出', 'Export')}</div>`;
    items += `<div class="ctx-menu-item ctx-menu-danger" onclick="hideContextMenu();_runDataTreeAction(deleteSelectedDataTreeItems())">
        <span class="ctx-icon">&#128465;</span> ${_dtText('删除真实数据', 'Delete data')}</div>`;
    items += `<div class="ctx-menu-sep"></div>`;

    // Show all
    items += `<div class="ctx-menu-item" onclick="hideContextMenu();showAllOrgans()">
        <span class="ctx-icon">&#128065;</span> Show All</div>`;

    // Clear selection
    items += `<div class="ctx-menu-item" onclick="hideContextMenu();selectedItems.clear();renderDataTree();">
        <span class="ctx-icon">&#10005;</span> Clear Selection</div>`;

    menu.innerHTML = items;
    document.body.appendChild(menu);

    positionBrachyContextMenu(menu, x, y);

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
            if (!dataTreeState.ctvLabels[id]) dataTreeState.ctvLabels[id] = { visible: true, opacity: 0.7, color: DEFAULT_CTV_STRUCTURE_COLOR };
            dataTreeState.ctvLabels[id].visible = visible;
            const mesh = scene3D.meshes[id];
            if (mesh) applyMeshVisibility(mesh, visible, dataTreeState.ctvLabels[id].opacity ?? dataTreeState.ctv.opacity ?? 0.7);
        }
        // Guide skin surface
        else if (id === 'skin_surface') {
            dataTreeState.skin.visible = visible;
            const mesh = scene3D.meshes.skin_surface;
            if (mesh) applyMeshVisibility(mesh, isDataTreeNodeVisible3D(dataTreeState.skin), dataTreeState.skin.opacity ?? 0.1);
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
                if (mesh) applyMeshVisibility(mesh, isDataTreeNodeVisible3D(s), s.opacity ?? 1.0);
            }
        }
        // Planning needles
        else if (id.startsWith('needle_')) {
            const n = dataTreeState.planning.needles.find(n => n.id === id);
            if (n) {
                n.visible = visible;
                const mesh = scene3D.meshes[id];
                if (mesh) applyMeshVisibility(mesh, isDataTreeNodeVisible3D(n), n.opacity ?? 0.8);
            }
        }
        // Dose isosurfaces
        else if (id.startsWith('dose_iso_')) {
            const threshold = parseFloat(id.replace('dose_iso_', ''));
            const d = dataTreeState.planning.doseLevels.find(d => d.threshold === threshold);
            if (d) {
                d.visible = visible;
                const mesh = scene3D.meshes[id];
                if (mesh) applyMeshVisibility(mesh, isDataTreeNodeVisible3D(d), d.opacity ?? 0.3);
            }
        }
        // Manual/threshold masks
        else if (_isDataTreeMaskId(id)) {
            const rawId = _maskSceneMeshId(id);
            const m = _maskStateEntry(id);
            if (m && (!_isGenericSegmentationMask(m) || _isOpenGenericMask(m))) {
                m.visible = visible;
                const mesh = scene3D.meshes[rawId];
                if (mesh) applyMeshVisibility(mesh, visible, m.opacity ?? 0.6);
            }
        }
    });
    renderDataTree();
    if (state.ctLoaded) reloadOverlays();
    redrawSeedNeedleOverlays();
    requestViewerVisualRefresh('batch-visibility');
    applyDataTreeViewVisibility();
    _scheduleDataTreeSave('viewer.batch_visibility');
}

function _allDataTreeVisualNodes() {
    return [
        dataTreeState.ct,
        dataTreeState.ctv,
        dataTreeState.oar,
        dataTreeState.skin,
        ...(Object.values(dataTreeState.ctvLabels || {})),
        ...(dataTreeState.organs || []),
        ...(Object.entries(state.maskLabels || {})).map(([maskId, mask]) => {
            if (typeof mask !== 'object' || mask === null) return null;
            if (_isGenericSegmentationMask(mask) && !_isOpenGenericMask(mask)) return null;
            if (!mask.id) mask.id = maskId;
            return mask;
        }).filter(Boolean),
        ..._planningItems('trajectories'),
        ..._planningItems('seeds'),
        ..._planningItems('needles'),
        ..._planningItems('doseLevels'),
        ...(dataTreeState.planning?.meshes || []).filter(node => _findDataTreeNode(node.id) === node),
    ].filter(Boolean);
}

function _setNodeViewVisibility(node, view, visible) {
    if (!node) return;
    node[view === '2d' ? 'visible2D' : 'visible3D'] = !!visible;
}

function _apply3DNodeVisibility(node) {
    if (!node?.id) return;
    const meshId = node.id.startsWith('dose_iso_')
        ? node.id
        : node.id;
    const mesh = scene3D?.meshes?.[meshId];
    const visible = isDataTreeNodeVisible3D(node);
    if (mesh) applyMeshVisibility(mesh, visible, node.opacity ?? 1);
    if (node.id.startsWith('needle_') && typeof _setNeedleHandlesVisibility === 'function') {
        _setNeedleHandlesVisibility(node.id, visible, node.opacity ?? 0.8);
    }
}

/**
 * Reapply persisted per-view state after any tree, mesh, or session update.
 * The master `visible` state is deliberately not changed here: it remains the
 * existing all-view compatibility control, while 2D/3D stay independent.
 */
function applyDataTreeViewVisibility() {
    _allDataTreeVisualNodes().forEach(_apply3DNodeVisibility);
    const ct2D = isDataTreeNodeVisible2D(dataTreeState.ct);
    ['axial', 'sagittal', 'coronal'].forEach(axis => {
        const canvas = document.getElementById('sliceCanvas' + capitalize(axis));
        if (canvas) canvas.style.visibility = ct2D ? 'visible' : 'hidden';
    });
    const doseNode = dataTreeState.planning?.doseOverlay;
    const planning2D = isDataTreeNodeVisible2D(dataTreeState.planning);
    const dose2D = planning2D && (!doseNode || isDataTreeNodeVisible2D(doseNode));
    _setPlanningDoseProjectionVisibility(dose2D, { preserveMaster: false });
    if (state.ctLoaded) reloadOverlays();
    redrawSeedNeedleOverlays();
    requestViewerVisualRefresh('data-tree-view-visibility');
}

function batchSetViewVisibility(view, visible) {
    const key = view === '2d' ? 'visible2D' : 'visible3D';
    getSelectedOrganIds().forEach(id => {
        const node = _findDataTreeNode(id);
        if (!node) return;
        node[key] = !!visible;
        // A group selection only propagates downward; it never changes a
        // parent or a sibling selected by a different branch.
        if (id === 'ctv') Object.values(dataTreeState.ctvLabels || {}).forEach(item => { item[key] = !!visible; });
        if (id === 'oar') dataTreeState.organs.forEach(item => { item[key] = !!visible; });
        const trajectory = _planningItems('trajectories').find(item => item.id === id);
        if (trajectory) {
            [..._planningItems('seeds'), ..._planningItems('needles')]
                .filter(item => _trajectoryContains(item, trajectory))
                .forEach(item => { item[key] = !!visible; });
        }
    });
    applyDataTreeViewVisibility();
    renderDataTree();
    _scheduleDataTreeSave(`viewer.batch_${view}_visibility`);
}

function _groupViewNodes(category) {
    if (category === 'image') return [dataTreeState.ct];
    const maskNodes = Object.entries(state.maskLabels || {}).map(([maskId, mask]) => {
        if (!mask || typeof mask !== 'object') return null;
        if (!mask.id) mask.id = maskId;
        return mask;
    }).filter(Boolean);
    const genericMaskNodes = maskNodes.filter(mask => _maskBelongsToGroup('generic_masks', mask));
    const uploadedMaskNodes = maskNodes.filter(mask => _maskBelongsToGroup('upload_masks', mask));
    const localMaskNodes = maskNodes.filter(mask => !_isGenericSegmentationMask(mask));
    if (category === 'segmentation') return [
        dataTreeState.ctv, ...Object.values(dataTreeState.ctvLabels || {}),
        dataTreeState.oar, ...(dataTreeState.organs || []),
        dataTreeState.skin,
        ...uploadedMaskNodes,
        ...genericMaskNodes,
        ...localMaskNodes,
    ];
    if (category === 'masks') return localMaskNodes;
    if (category === 'generic_masks') return genericMaskNodes;
    if (category === 'upload_masks') return uploadedMaskNodes;
    if (category === 'ctv') return [dataTreeState.ctv, ...Object.values(dataTreeState.ctvLabels || {})];
    if (category === 'oar') return [dataTreeState.oar, ...(dataTreeState.organs || [])];
    if (category === 'non_traversable' || category === 'traversable') {
        return (dataTreeState.organs || []).filter(item => item.category === category);
    }
    if (category === 'planning') return [
        dataTreeState.planning,
        ...(dataTreeState.planning?.doseOverlay ? [dataTreeState.planning.doseOverlay] : []),
        ..._planningVisualEntries(),
    ];
    if (category === 'planning_trajectories') {
        const trajectories = _planningItems('trajectories');
        return [
            ...trajectories,
            ..._planningItems('seeds').filter(item => trajectories.some(t => _trajectoryContains(item, t))),
            ..._planningItems('needles').filter(item => trajectories.some(t => _trajectoryContains(item, t))),
        ];
    }
    if (category === 'planning_seeds') return [dataTreeState.seeds, ..._planningItems('seeds')];
    if (category === 'planning_needles') return [dataTreeState.needles, ..._planningItems('needles')];
    if (category === 'dose_isosurfaces') return [dataTreeState.dose, ..._planningItems('doseLevels')];
    if (category === 'planning_meshes') return dataTreeState.planning?.meshes || [];
    return [];
}

function setGroupViewVisibility(category, view, visible) {
    _groupViewNodes(category).forEach(node => _setNodeViewVisibility(node, view, visible));
    applyDataTreeViewVisibility();
    renderDataTree();
    _scheduleDataTreeSave(`viewer.group_${view}_visibility:${category}`);
}

window.batchSetViewVisibility = batchSetViewVisibility;
window.setGroupViewVisibility = setGroupViewVisibility;
window.applyDataTreeViewVisibility = applyDataTreeViewVisibility;

function batchMoveToCategory(category) {
    const selected = getSelectedDataTreeIds();
    selected.forEach(id => {
        if (id.startsWith('organ_')) {
            const o = dataTreeState.organs.find(o => o.id === id);
            if (o) o.category = category;
        }
    });
    renderDataTree();
    if (state.ctLoaded) loadAllSlices();
    redrawSeedNeedleOverlays();
    requestViewerVisualRefresh('batch-category');
    _scheduleDataTreeSave(`viewer.batch-category:${category}`);
    if (typeof syncUIBridgeState === 'function') syncUIBridgeState('data_tree.category').catch(() => {});
}

function batchSolo() {
    const selSet = new Set(getSelectedDataTreeIds());
    dataTreeState.organs.forEach(o => { o.visible = selSet.has(o.id); });
    dataTreeState.ctv.visible = selSet.has('ctv');
    dataTreeState.skin.visible = selSet.has('skin_surface');
    Object.entries(state.maskLabels || {}).forEach(([id, mask]) => {
        if (!mask || typeof mask !== 'object') return;
        if (_isGenericSegmentationMask(mask) && !_isOpenGenericMask(mask)) return;
        const nodeId = mask.id || id;
        mask.visible = selSet.has(nodeId) || selSet.has(`mask:${id}`);
    });
    applyDataTreeViewVisibility();
    renderDataTree();
    if (state.ctLoaded) loadAllSlices();
    requestViewerVisualRefresh('batch-solo');
}

function batchSetOpacity(opacity) {
    const selected = getSelectedDataTreeIds();
    selected.forEach(id => {
        if (id === 'ctv') {
            dataTreeState.ctv.opacity = opacity;
            applyMeshOpacity(scene3D.meshes['ctv'], opacity, dataTreeState.ctv.visible !== false);
        } else if (id.startsWith('ctv_')) {
            // Individual CTV label
            const labelId = parseInt(id.replace('ctv_', ''));
            if (!dataTreeState.ctv.labelOpacities) dataTreeState.ctv.labelOpacities = {};
            dataTreeState.ctv.labelOpacities[labelId] = opacity;
            if (!dataTreeState.ctvLabels) dataTreeState.ctvLabels = {};
            if (!dataTreeState.ctvLabels[id]) dataTreeState.ctvLabels[id] = { visible: true, opacity, color: DEFAULT_CTV_STRUCTURE_COLOR };
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
        } else if (_isDataTreeMaskId(id)) {
            const rawId = _maskSceneMeshId(id);
            const m = _maskStateEntry(id);
            if (m && (!_isGenericSegmentationMask(m) || _isOpenGenericMask(m))) {
                m.opacity = opacity;
                applyMeshOpacity(scene3D.meshes[rawId], opacity, m.visible !== false);
                reloadOverlays();
            }
        } else if (id === 'skin_surface') {
            dataTreeState.skin.opacity = opacity;
            applyMeshOpacity(
                scene3D.meshes.skin_surface,
                opacity,
                isDataTreeNodeVisible3D(dataTreeState.skin),
            );
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
    _scheduleDataTreeSave('viewer.batch-opacity');
}

async function batchReconstruct3D() {
    const ids = getSelectedDataTreeIds();
    for (const id of ids) {
        await reconstructOrgan3D(id);
    }

    if (genericMaskMutation) {
        // The backend owns the mask catalogue and voxel buffers. Rehydrate
        // it after delete/classification mutations so the Data Tree, 2D
        // overlays, and 3D meshes cannot diverge from persistent state.
        await hydrateGenericMasksFromServer(
            _captureViewerDataScope(expectedSessionId),
        );
        if (String(expectedSessionId) !== _viewerDataSessionId()) return false;
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
    applyDataTreeViewVisibility();
    renderDataTree();
    if (state.ctLoaded) loadAllSlices();
}

function showAllOrgans() {
    dataTreeState.organs.forEach(o => { o.visible = true; });
    dataTreeState.ctv.visible = true;
    dataTreeState.skin.visible = true;
    Object.values(state.maskLabels || {}).forEach(mask => {
        // A promoted generic mask is rendered through the effective CTV/OAR
        // Structure Set and must not be resurrected as a second standalone
        // overlay or mesh.
        if (mask && typeof mask === 'object' && _isOpenGenericMask(mask)) mask.visible = true;
    });
    // "Show all" is an explicit operator action.  Record it as a real
    // Planning master-visibility choice so a later compact restore cannot
    // reinterpret the state as an unset/default value.
    dataTreeState.planning.visible = true;
    dataTreeState.planning.visibilityConfigured = true;
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
        else if (_isDataTreeMaskId(id)) {
            const mask = _maskStateEntry(id);
            const isStandalone = mask && (!_isGenericSegmentationMask(mask) || _isOpenGenericMask(mask));
            if (!isStandalone) {
                applyMeshVisibility(mesh, false, 0.6);
                return;
            }
            opacity = mask.opacity ?? 0.6;
        }
        const planningMesh = id.startsWith('seed_')
            ? _planningItems('seeds').find(item => item.id === id)
            : id.startsWith('needle_')
                ? _planningItems('needles').find(item => item.id === id)
                : id.startsWith('dose_iso_')
                    ? _planningItems('doseLevels').find(item => item.threshold === parseFloat(id.replace('dose_iso_', '')))
                    : (dataTreeState.planning.meshes || []).find(item => item.id === id);
        applyMeshVisibility(
            mesh,
            planningMesh ? isDataTreeNodeVisible3D(planningMesh) : true,
            opacity,
        );
    });
    applyDataTreeViewVisibility();
    renderDataTree();
    if (state.ctLoaded) loadAllSlices();
}

function _setPlanningDoseProjectionVisibility(visible, options = {}) {
    if (typeof state === 'undefined') return;
    if (state.doseOverlay && !options.preserveMaster) state.doseOverlay.visible = !!visible;
    // Dose projections use independent canvases instead of the CT canvas.
    // Hiding the Planning parent must clear those layers immediately; merely
    // changing doseOverlay.visible would leave the last painted slice visible.
    ['axial', 'sagittal', 'coronal'].forEach(axis => {
        ['doseOverlayCanvas', 'doseCanvas', 'contourCanvas'].forEach(prefix => {
            const canvas = document.getElementById(prefix + capitalize(axis));
            if (!canvas) return;
            if (!visible) canvas.getContext('2d')?.clearRect(0, 0, canvas.width, canvas.height);
            canvas.style.display = visible ? 'block' : 'none';
        });
    });
    if (typeof updateDoseColorbars === 'function') updateDoseColorbars(!!visible);
}

function setGroupVisibility(category, visible) {
    if (category === 'image') {
        dataTreeState.ct.visible = !!visible;
    } else if (category === 'segmentation') {
        dataTreeState.ctv.visible = !!visible;
        Object.values(dataTreeState.ctvLabels || {}).forEach(label => { label.visible = !!visible; });
        dataTreeState.oar.visible = !!visible;
        dataTreeState.organs.forEach(organ => { organ.visible = !!visible; });
        dataTreeState.skin.visible = !!visible;
        Object.values(state.maskLabels || {}).forEach(mask => {
            if (mask && typeof mask === 'object' && _isOpenGenericMask(mask)) {
                mask.visible = !!visible;
            }
        });
    } else if (category === 'planning') {
        dataTreeState.planning.visible = !!visible;
        dataTreeState.planning.visibilityConfigured = true;
        _planningVisualEntries().forEach(item => { item.visible = visible; });
        _planningItems('seeds').forEach(seed => {
            const mesh = scene3D.meshes[seed.id];
            if (mesh) applyMeshVisibility(mesh, isDataTreeNodeVisible3D(seed), seed.opacity ?? 1.0);
        });
        _planningItems('needles').forEach(needle => {
            const mesh = scene3D.meshes[needle.id];
            const effectiveVisible = isDataTreeNodeVisible3D(needle);
            if (mesh) applyMeshVisibility(mesh, effectiveVisible, needle.opacity ?? 0.8);
            if (typeof _setNeedleHandlesVisibility === 'function') _setNeedleHandlesVisibility(needle.id, effectiveVisible, needle.opacity ?? 0.8);
        });
        _planningItems('doseLevels').forEach(level => {
            const mesh = scene3D.meshes[`dose_iso_${level.threshold}`];
            if (mesh) applyMeshVisibility(mesh, isDataTreeNodeVisible3D(level), level.opacity ?? 0.3);
        });
        _setPlanningDoseProjectionVisibility(_planningViewVisible('2d'));
        (dataTreeState.planning.meshes || []).forEach(item => {
            const mesh = scene3D.meshes[item.id];
            if (mesh) applyMeshVisibility(mesh, isDataTreeNodeVisible3D(item), item.opacity ?? 0.7);
        });
    } else if (category === 'planning_trajectories') {
        _planningItems('trajectories').forEach(trajectory => { trajectory.visible = visible; });
        // Only descendants of the selected trajectory branch are changed.
        // A sibling trajectory must remain untouched when the user edits one
        // parent node in the Data Tree.
        const trajectories = _planningItems('trajectories');
        const ownsTrajectory = item => trajectories.some(t => _trajectoryContains(item, t));
        _planningItems('seeds').filter(ownsTrajectory).forEach(seed => {
            seed.visible = visible;
            const mesh = scene3D.meshes[seed.id];
            if (mesh) applyMeshVisibility(mesh, isDataTreeNodeVisible3D(seed), seed.opacity ?? 1.0);
        });
        _planningItems('needles').filter(ownsTrajectory).forEach(needle => {
            needle.visible = visible;
            const mesh = scene3D.meshes[needle.id];
            const effectiveVisible = isDataTreeNodeVisible3D(needle);
            if (mesh) applyMeshVisibility(mesh, effectiveVisible, needle.opacity ?? 0.8);
            if (typeof _setNeedleHandlesVisibility === 'function') _setNeedleHandlesVisibility(needle.id, effectiveVisible, needle.opacity ?? 0.8);
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
    } else if (category === 'masks' || category === 'generic_masks' || category === 'upload_masks') {
        Object.entries(state.maskLabels || {}).forEach(([id, mask]) => {
            if (!_maskBelongsToGroup(category, mask)) return;
            mask.visible = !!visible;
            const mesh = scene3D.meshes[_maskSceneMeshId(id)];
            if (mesh) applyMeshVisibility(mesh, !!visible, mask.opacity ?? 0.6);
        });
        reloadOverlays();
    } else if (category === 'planning_seeds') {
        _planningItems('seeds').forEach(seed => {
            seed.visible = visible;
            const mesh = scene3D.meshes[seed.id];
            if (mesh) applyMeshVisibility(mesh, isDataTreeNodeVisible3D(seed), seed.opacity ?? 1.0);
        });
    } else if (category === 'planning_needles') {
        _planningItems('needles').forEach(needle => {
            needle.visible = visible;
            const mesh = scene3D.meshes[needle.id];
            const effectiveVisible = isDataTreeNodeVisible3D(needle);
            if (mesh) applyMeshVisibility(mesh, effectiveVisible, needle.opacity ?? 0.8);
            if (typeof _setNeedleHandlesVisibility === 'function') {
                _setNeedleHandlesVisibility(needle.id, effectiveVisible, needle.opacity ?? 0.8);
            }
        });
    } else if (category === 'dose_isosurfaces') {
        _planningItems('doseLevels').forEach(level => {
            level.visible = visible;
            const mesh = scene3D.meshes[`dose_iso_${level.threshold}`];
            if (mesh) applyMeshVisibility(mesh, isDataTreeNodeVisible3D(level), level.opacity ?? 0.3);
        });
    } else if (category === 'planning_meshes') {
        (dataTreeState.planning.meshes || []).forEach(m => {
            m.visible = visible;
            const mesh = scene3D.meshes[m.id];
            if (mesh) applyMeshVisibility(mesh, isDataTreeNodeVisible3D(m), m.opacity ?? 0.7);
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
    applyDataTreeViewVisibility();
    _scheduleDataTreeSave(`viewer.group_visibility:${category}`);
}

let _groupOpacityTimer = null;
function _commitGroupOpacity(category) {
    renderDataTree();
    if (state.ctLoaded) loadAllSlices();
    redrawSeedNeedleOverlays();
    requestViewerVisualRefresh('group-opacity');
    applyDataTreeViewVisibility();
    _scheduleDataTreeSave(`viewer.group_opacity:${category}`);
}

function setGroupOpacity(category, value) {
    // Mesh materials are updated synchronously below. Repaint 2D projection
    // layers on the next frame instead of re-creating the slider DOM while
    // the pointer is still captured by the native range input.
    _requestDataTreeOpacityVisualRefresh();
    const opacity = parseInt(value) / 100;
    if (category === 'segmentation') {
        dataTreeState.ctv.opacity = opacity;
        Object.values(dataTreeState.ctvLabels || {}).forEach(label => { label.opacity = opacity; });
        dataTreeState.oar.opacity = opacity;
        dataTreeState.organs.forEach(organ => { organ.opacity = opacity; });
        dataTreeState.skin.opacity = opacity;
        Object.values(state.maskLabels || {}).forEach(mask => {
            if (!mask || typeof mask !== 'object') return;
            if (_isGenericSegmentationMask(mask) && !_isOpenGenericMask(mask)) return;
            mask.opacity = opacity;
        });
        [
            ...Object.keys(dataTreeState.ctvLabels || {}),
            ...dataTreeState.organs.map(organ => organ.id),
            ...Object.entries(state.maskLabels || {})
                .filter(([, mask]) => !_isGenericSegmentationMask(mask) || _isOpenGenericMask(mask))
                .map(([id]) => id),
            'skin_surface',
        ].forEach(id => {
            const meshId = _isDataTreeMaskId(id)
                ? _maskSceneMeshId(id)
                : id;
            applyMeshOpacity(scene3D.meshes[meshId], opacity, _findDataTreeNode(id)?.visible !== false);
        });
    } else if (category === 'planning' || category === 'planning_trajectories') {
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
            applyMeshOpacity(scene3D.meshes[seed.id], opacity, isDataTreeNodeVisible3D(seed));
        });
        _planningItems('needles').forEach(needle => {
            if (category === 'planning_trajectories' && !_planningItems('trajectories').some(t => _trajectoryContains(needle, t))) return;
            const effectiveVisible = isDataTreeNodeVisible3D(needle);
            applyMeshOpacity(scene3D.meshes[needle.id], opacity, effectiveVisible);
            if (typeof _setNeedleHandlesVisibility === 'function') _setNeedleHandlesVisibility(needle.id, effectiveVisible, opacity);
        });
        if (category === 'planning') {
            _planningItems('doseLevels').forEach(level => {
                applyMeshOpacity(scene3D.meshes[`dose_iso_${level.threshold}`], opacity, isDataTreeNodeVisible3D(level));
            });
            if (state.doseOverlay) state.doseOverlay.opacity = opacity;
            if (dataTreeState.planning.doseOverlay) {
                dataTreeState.planning.doseOverlay.opacity = opacity;
            }
            if (typeof applyDoseOverlayLayerOpacity === 'function') {
                applyDoseOverlayLayerOpacity();
            }
            (dataTreeState.planning.meshes || []).forEach(item => {
                applyMeshOpacity(scene3D.meshes[item.id], opacity, isDataTreeNodeVisible3D(item));
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
    } else if (category === 'masks' || category === 'generic_masks' || category === 'upload_masks') {
        Object.entries(state.maskLabels || {}).forEach(([id, mask]) => {
            if (!_maskBelongsToGroup(category, mask)) return;
            mask.opacity = opacity;
            applyMeshOpacity(scene3D.meshes[_maskSceneMeshId(id)], opacity, mask.visible !== false);
        });
        reloadOverlays();
    } else if (category === 'planning_seeds') {
        _planningItems('seeds').forEach(seed => {
            seed.opacity = opacity;
            applyMeshOpacity(scene3D.meshes[seed.id], opacity, isDataTreeNodeVisible3D(seed));
        });
    } else if (category === 'planning_needles') {
        _planningItems('needles').forEach(needle => {
            needle.opacity = opacity;
            const effectiveVisible = isDataTreeNodeVisible3D(needle);
            applyMeshOpacity(scene3D.meshes[needle.id], opacity, effectiveVisible);
            if (typeof _setNeedleHandlesVisibility === 'function') {
                _setNeedleHandlesVisibility(needle.id, effectiveVisible, opacity);
            }
        });
    } else if (category === 'dose_isosurfaces') {
        _planningItems('doseLevels').forEach(level => {
            level.opacity = opacity;
            applyMeshOpacity(scene3D.meshes[`dose_iso_${level.threshold}`], opacity, isDataTreeNodeVisible3D(level));
        });
    } else if (category === 'planning_meshes') {
        (dataTreeState.planning.meshes || []).forEach(m => {
            m.opacity = opacity;
            applyMeshOpacity(scene3D.meshes[m.id], opacity, isDataTreeNodeVisible3D(m));
        });
    } else {
        dataTreeState.organs.filter(o => o.category === category).forEach(o => {
            o.opacity = opacity;
            // Update 3D mesh
            applyMeshOpacity(scene3D.meshes[o.id], opacity, o.visible !== false);
        });
    }
    // Persist the final state after a short quiet period. A drag keeps its
    // original input node alive until pointerup so high-speed adjustments do
    // not lose capture or snap back to an older DOM value.
    clearTimeout(_groupOpacityTimer);
    _groupOpacityTimer = setTimeout(() => {
        _groupOpacityTimer = null;
        if (_isDataTreeOpacityDragActive()) {
            _pendingGroupOpacityCategory = category;
            _dataTreeOpacityRerenderPending = true;
            return;
        }
        _commitGroupOpacity(category);
    }, 150);
}

// Wrapper for context menu: takes percentage (0-100) directly
function setGroupOpacityValue(category, percentValue) {
    // setGroupOpacity expects value 0-100 (it divides by 100 internally)
    setGroupOpacity(category, percentValue);
}

function getGroupDisplayColor(category) {
    if (category === 'segmentation') return dataTreeState.skin.color || '#f2a088';
    if (category === 'ctv') return dataTreeState.ctv.color || DEFAULT_CTV_STRUCTURE_COLOR;
    if (category === 'oar') return dataTreeState.oar.color || DEFAULT_OAR_STRUCTURE_COLOR;
    if (category === 'masks' || category === 'generic_masks' || category === 'upload_masks') {
        const entries = Object.values(state.maskLabels || {}).filter(mask => {
            return _maskBelongsToGroup(category, mask);
        });
        return entries.find(entry => entry?.color)?.color || '#f08a5d';
    }
    if (category === 'planning') return dataTreeState.planning.color || '#60a5fa';
    const entries = category === 'planning_seeds'
        ? _planningItems('seeds')
        : category === 'planning_needles'
            ? _planningItems('needles')
            : category === 'dose_isosurfaces'
                ? _planningItems('doseLevels')
                : category === 'planning_meshes'
                    ? (dataTreeState.planning.meshes || [])
                    : dataTreeState.organs.filter(organ => organ.category === category);
    return entries.find(entry => entry?.color)?.color || '#60a5fa';
}

function setGroupColor(category, color) {
    requestAnimationFrame(() => applyDataTreeViewVisibility());
    const normalized = String(color || '').trim();
    if (!/^#[0-9a-f]{6}$/i.test(normalized)) return;
    let entries = [];
    if (category === 'segmentation') {
        dataTreeState.ctv.color = normalized;
        dataTreeState.oar.color = normalized;
        dataTreeState.skin.color = normalized;
        entries = [
            ...Object.entries(dataTreeState.ctvLabels || {}).map(([id, value]) => ({ id, value })),
            ...dataTreeState.organs.map(value => ({ id: value.id, value })),
            { id: 'skin_surface', value: dataTreeState.skin },
        ];
    } else if (category === 'ctv') {
        dataTreeState.ctv.color = normalized;
        entries = Object.entries(dataTreeState.ctvLabels || {}).map(([id, value]) => ({ id, value }));
    } else if (category === 'oar') {
        dataTreeState.oar.color = normalized;
        entries = dataTreeState.organs.map(value => ({ id: value.id, value }));
    } else if (category === 'masks' || category === 'generic_masks' || category === 'upload_masks') {
        entries = Object.entries(state.maskLabels || {}).filter(([, value]) => {
            return _maskBelongsToGroup(category, value);
        }).map(([id, value]) => ({ id, value }));
    } else if (category === 'planning') {
        dataTreeState.planning.color = normalized;
        entries = [
            ..._planningItems('seeds').map(value => ({ id: value.id, value })),
            ..._planningItems('needles').map(value => ({ id: value.id, value })),
            ..._planningItems('doseLevels').map(value => ({ id: `dose_iso_${value.threshold}`, value })),
            ...(dataTreeState.planning.meshes || []).map(value => ({ id: value.id, value })),
        ];
    } else if (category === 'planning_seeds') {
        entries = _planningItems('seeds').map(value => ({ id: value.id, value }));
    } else if (category === 'planning_needles') {
        entries = _planningItems('needles').map(value => ({ id: value.id, value }));
    } else if (category === 'dose_isosurfaces') {
        entries = _planningItems('doseLevels').map(value => ({ id: `dose_iso_${value.threshold}`, value }));
    } else if (category === 'planning_meshes') {
        entries = (dataTreeState.planning.meshes || []).map(value => ({ id: value.id, value }));
    } else {
        entries = dataTreeState.organs
            .filter(value => value.category === category)
            .map(value => ({ id: value.id, value }));
    }
    entries.forEach(({ id, value }) => {
        value.color = normalized;
        const parsedLabelId = Number.isFinite(Number(value.labelId))
            ? Number(value.labelId)
            : (/^ctv_(\d+)$/.test(String(id)) ? Number(String(id).slice(4)) : null);
        if (Number.isFinite(parsedLabelId)) {
            const targetLut = category === 'ctv' || String(id).startsWith('ctv_')
                ? ctvLabelColorLUT : oarLabelColorLUT;
            targetLut[parsedLabelId] = [
                parseInt(normalized.slice(1, 3), 16),
                parseInt(normalized.slice(3, 5), 16),
                parseInt(normalized.slice(5, 7), 16),
            ];
            labelColorLUT = oarLabelColorLUT;
        }
        const mesh = scene3D.meshes[id];
        if (mesh) _setMeshMaterialColor(mesh, normalized);
        const savedMaterial = state.doseTexture?.originalMaterials?.[id];
        if (savedMaterial) _setMeshMaterialColor({ material: savedMaterial }, normalized);
    });
    renderDataTree();
    if (state.ctLoaded) reloadOverlays();
    redrawSeedNeedleOverlays();
    requestViewerVisualRefresh('group-color');
    _scheduleDataTreeSave(`viewer.group_color:${category}`);
}

function _treeExpansionState() {
    if (!dataTreeState.expansionState
        || typeof dataTreeState.expansionState !== 'object'
        || Array.isArray(dataTreeState.expansionState)) {
        dataTreeState.expansionState = {};
    }
    return dataTreeState.expansionState;
}

function _applyTreeGroupExpansion(group, expanded) {
    if (!group) return;
    const arrow = group.querySelector(':scope > .tree-group-header .arrow');
    const items = group.querySelector(':scope > .tree-group-items');
    if (!items) return;
    items.classList.toggle('collapsed', !expanded);
    if (arrow) arrow.classList.toggle('collapsed', !expanded);
    group.dataset.expanded = expanded ? 'true' : 'false';
}

function _restoreTreeGroupExpansionState(body) {
    const expansion = _treeExpansionState();
    body.querySelectorAll('.tree-group[data-group]').forEach(group => {
        const key = String(group.dataset.group || '').trim();
        if (key) _applyTreeGroupExpansion(group, expansion[key] !== false);
    });
}

function toggleTreeGroup(header) {
    const group = header.closest('.tree-group');
    if (!group) return;
    const items = group.querySelector(':scope > .tree-group-items');
    if (!items) return;
    const expanded = items.classList.contains('collapsed');
    _applyTreeGroupExpansion(group, expanded);
    const key = String(group.dataset.group || '').trim();
    if (key) {
        _treeExpansionState()[key] = expanded;
        _scheduleDataTreeSave(`viewer.tree_group:${key}`);
    }
}

function setTreeGroupExpansion(key, expanded) {
    const groupKey = String(key || '').trim();
    if (!groupKey) return false;
    const value = !!expanded;
    _treeExpansionState()[groupKey] = value;
    // Do not build a selector from the group key.  Group keys are currently
    // controlled values, but this entry point is also used by the UI command
    // bridge and old WebViews do not guarantee selector escaping helpers.
    // Matching the data attribute directly keeps expand/collapse reliable
    // across browsers.
    document.querySelectorAll('.tree-group[data-group]').forEach(group => {
        if (String(group.dataset.group || '').trim() === groupKey) {
            _applyTreeGroupExpansion(group, value);
        }
    });
    _scheduleDataTreeSave(`viewer.tree_group:${groupKey}`);
    return true;
}

function setAllTreeGroupsExpansion(expanded) {
    const value = !!expanded;
    document.querySelectorAll('.tree-group[data-group]').forEach(group => {
        const key = String(group.dataset.group || '').trim();
        if (!key) return;
        _treeExpansionState()[key] = value;
        _applyTreeGroupExpansion(group, value);
    });
    _scheduleDataTreeSave(`viewer.tree_groups:${value ? 'expand' : 'collapse'}_all`);
    return true;
}

// The UI command bridge and automated UI actions use these same stateful
// entry points instead of mutating only the current DOM instance.
window.setTreeGroupExpansion = setTreeGroupExpansion;
window.setAllTreeGroupsExpansion = setAllTreeGroupsExpansion;

function toggleDataVisibility(id) {
    requestAnimationFrame(() => applyDataTreeViewVisibility());
    if (id === 'dose_overlay') {
        const node = dataTreeState.planning?.doseOverlay;
        if (node) node.visible2D = !isDataTreeNodeVisible2D(node);
        else if (state.doseOverlay) state.doseOverlay.visible = state.doseOverlay.visible === false;
        applyDataTreeViewVisibility();
        renderDataTree();
        _scheduleDataTreeSave('viewer.visibility:dose_overlay');
        return;
    }
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
            _scheduleDataTreeSave(`viewer.visibility:${id}`);
        }
        return;
    }

    // Handle individual CTV label toggles
    if (id.startsWith('ctv_')) {
        if (!dataTreeState.ctvLabels) dataTreeState.ctvLabels = {};
        if (!dataTreeState.ctvLabels[id]) {
            dataTreeState.ctvLabels[id] = { visible: true, opacity: 0.7, color: DEFAULT_CTV_STRUCTURE_COLOR };
        }
        dataTreeState.ctvLabels[id].visible = !dataTreeState.ctvLabels[id].visible;
        // Also toggle 3D mesh visibility
            const mesh = scene3D.meshes[id];
            if (mesh) applyMeshVisibility(mesh, dataTreeState.ctvLabels[id].visible, dataTreeState.ctvLabels[id].opacity ?? dataTreeState.ctv.opacity ?? 0.7);
        renderDataTree();
        if (state.ctLoaded) reloadOverlays();
        _scheduleDataTreeSave(`viewer.visibility:${id}`);
        return;
    }

    // The guide skin surface is a segmentation sibling, not an OAR child.
    // Route it through the same persisted master/view-specific state used by
    // every other Data Tree visual node.
    if (id === 'skin_surface') {
        dataTreeState.skin.visible = !dataTreeState.skin.visible;
        const mesh = scene3D.meshes.skin_surface;
        if (mesh) applyMeshVisibility(mesh, isDataTreeNodeVisible3D(dataTreeState.skin), dataTreeState.skin.opacity ?? 0.1);
        renderDataTree();
        if (state.ctLoaded) reloadOverlays();
        _scheduleDataTreeSave(`viewer.visibility:${id}`);
        return;
    }

    // Handle individual trajectory toggles and all of their descendants.
    const trajectory = _planningItems('trajectories').find(t => String(t.id) === String(id));
    if (trajectory) {
        trajectory.visible = !trajectory.visible;
        _planningItems('seeds').filter(seed => _trajectoryContains(seed, trajectory)).forEach(seed => {
            seed.visible = trajectory.visible;
            const mesh = scene3D.meshes[seed.id];
            if (mesh) applyMeshVisibility(mesh, isDataTreeNodeVisible3D(seed), seed.opacity ?? 1.0);
        });
        _planningItems('needles').filter(needle => _trajectoryContains(needle, trajectory)).forEach(needle => {
            needle.visible = trajectory.visible;
            const mesh = scene3D.meshes[needle.id];
            const effectiveVisible = isDataTreeNodeVisible3D(needle);
            if (mesh) applyMeshVisibility(mesh, effectiveVisible, needle.opacity ?? 0.8);
            if (typeof _setNeedleHandlesVisibility === 'function') _setNeedleHandlesVisibility(needle.id, effectiveVisible, needle.opacity ?? 0.8);
        });
        renderDataTree();
        redrawSeedNeedleOverlays();
        _scheduleDataTreeSave(`viewer.visibility:${id}`);
        return;
    }

    // Handle planning seed toggles
    if (id.startsWith('seed_')) {
        const seed = dataTreeState.planning.seeds.find(s => s.id === id);
        if (seed) {
            seed.visible = !seed.visible;
            const mesh = scene3D.meshes[id];
            if (mesh) applyMeshVisibility(mesh, isDataTreeNodeVisible3D(seed), seed.opacity ?? 1.0);
            renderDataTree();
            redrawSeedNeedleOverlays();
            _scheduleDataTreeSave(`viewer.visibility:${id}`);
        }
        return;
    }

    // Handle planning needle toggles
    if (id.startsWith('needle_')) {
        const needle = dataTreeState.planning.needles.find(n => n.id === id);
        if (needle) {
            needle.visible = !needle.visible;
            const mesh = scene3D.meshes[id];
            const effectiveVisible = isDataTreeNodeVisible3D(needle);
            if (mesh) applyMeshVisibility(mesh, effectiveVisible, needle.opacity ?? 0.8);
            if (typeof _setNeedleHandlesVisibility === 'function') {
                _setNeedleHandlesVisibility(needle.id, effectiveVisible, needle.opacity ?? 0.8);
            }
            renderDataTree();
            redrawSeedNeedleOverlays();
            _scheduleDataTreeSave(`viewer.visibility:${id}`);
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
            if (mesh) applyMeshVisibility(mesh, isDataTreeNodeVisible3D(level), level.opacity ?? 0.3);
            renderDataTree();
            _scheduleDataTreeSave(`viewer.visibility:${id}`);
        }
        return;
    }

    // Handle manual/threshold mask toggles
    if (_isDataTreeMaskId(id)) {
        const rawId = _maskSceneMeshId(id);
        const mask = _maskStateEntry(id);
        // Promoted generic masks are now rendered through the effective CTV/
        // OAR label volume. Do not let a stale legacy callback toggle a second
        // standalone mesh or overwrite the structure-owned visibility state.
        if (mask && (!_isGenericSegmentationMask(mask) || _isOpenGenericMask(mask))) {
            mask.visible = !(mask.visible !== false);
            const mesh = scene3D.meshes[rawId];
            if (mesh) applyMeshVisibility(mesh, mask.visible !== false, mask.opacity ?? 0.6);
            renderDataTree();
            reloadOverlays();
            _scheduleDataTreeSave(`viewer.visibility:${id}`);
        }
        return;
    }

    // Handle individual 3D mesh toggles (CTV/OAR/dose/etc. added via
    // addMeshToScene). The id is the same one used in scene3D.meshes.
    const meshEntry = (dataTreeState.planning.meshes || []).find(m => m.id === id);
    if (meshEntry) {
        meshEntry.visible = !meshEntry.visible;
        const mesh = scene3D.meshes[id];
        if (mesh) applyMeshVisibility(mesh, isDataTreeNodeVisible3D(meshEntry), meshEntry.opacity ?? 0.7);
        renderDataTree();
        _scheduleDataTreeSave(`viewer.visibility:${id}`);
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
        dataTreeState.planning.visibilityConfigured = true;
        // Propagate to all planning sub-items
        _planningItems('trajectories').forEach(t => t.visible = dataTreeState.planning.visible);
        _planningItems('seeds').forEach(s => {
            s.visible = dataTreeState.planning.visible;
            const m = scene3D.meshes[s.id];
            if (m) applyMeshVisibility(m, isDataTreeNodeVisible3D(s), s.opacity ?? 1.0);
        });
        _planningItems('needles').forEach(n => {
            n.visible = dataTreeState.planning.visible;
            const m = scene3D.meshes[n.id];
            if (m) applyMeshVisibility(m, isDataTreeNodeVisible3D(n), n.opacity ?? 0.8);
        });
        _planningItems('doseLevels').forEach(d => {
            d.visible = dataTreeState.planning.visible;
            const m = scene3D.meshes[`dose_iso_${d.threshold}`];
            if (m) applyMeshVisibility(m, isDataTreeNodeVisible3D(d), d.opacity ?? 0.3);
        });
        (dataTreeState.planning.meshes || []).forEach(item => {
            item.visible = dataTreeState.planning.visible;
            const m = scene3D.meshes[item.id];
            if (m) applyMeshVisibility(m, isDataTreeNodeVisible3D(item), item.opacity ?? 0.7);
        });
        _setPlanningDoseProjectionVisibility(_planningViewVisible('2d'));
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
    _scheduleDataTreeSave(`viewer.visibility:${id}`);
}

function setDataItemVisibility(id, visible) {
    let current = null;
    if (id.startsWith('organ_')) current = dataTreeState.organs.find(o => o.id === id)?.visible;
    else if (id.startsWith('ctv_')) current = dataTreeState.ctvLabels?.[id]?.visible;
    else if (_isDataTreeMaskId(id)) current = _maskStateEntry(id)?.visible;
    // Guide skin is a segmentation sibling with its own stable node ID, not
    // a dynamically keyed property on dataTreeState.  Keep this explicit so
    // bridge commands and restore-time UI actions use the same master switch
    // as the Data Tree eye button.
    else if (id === 'skin_surface') current = dataTreeState.skin?.visible;
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
    requestAnimationFrame(() => applyDataTreeViewVisibility());
    const opacity = parseInt(value) / 100;
    if (id === 'dose_overlay') {
        if (typeof setDoseOverlayOpacity === 'function') {
            setDoseOverlayOpacity(value);
        } else if (state.doseOverlay) {
            state.doseOverlay.opacity = opacity;
            if (typeof reloadOverlays === 'function') reloadOverlays();
            renderDataTreeDebounced();
            _scheduleDataTreeSave('viewer.opacity:dose_overlay');
        }
        return;
    }
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
            _scheduleDataTreeSave(`viewer.opacity:${id}`);
        }, 150);
        return;
    }

    // Handle individual CTV label opacity
    if (id.startsWith('ctv_')) {
        if (!dataTreeState.ctvLabels) dataTreeState.ctvLabels = {};
        if (!dataTreeState.ctvLabels[id]) {
            dataTreeState.ctvLabels[id] = { visible: true, opacity: opacity, color: DEFAULT_CTV_STRUCTURE_COLOR };
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
            _scheduleDataTreeSave(`viewer.opacity:${id}`);
        }, 150);
        return;
    }

    // Handle individual trajectory opacity and descendants.
    const trajectory = _planningItems('trajectories').find(t => String(t.id) === String(id));
    if (trajectory) {
        trajectory.opacity = opacity;
        _planningItems('seeds').filter(seed => _trajectoryContains(seed, trajectory)).forEach(seed => {
            seed.opacity = opacity;
            applyMeshOpacity(scene3D.meshes[seed.id], opacity, isDataTreeNodeVisible3D(seed));
        });
        _planningItems('needles').filter(needle => _trajectoryContains(needle, trajectory)).forEach(needle => {
            needle.opacity = opacity;
            const effectiveVisible = isDataTreeNodeVisible3D(needle);
            applyMeshOpacity(scene3D.meshes[needle.id], opacity, effectiveVisible);
            if (typeof _setNeedleHandlesVisibility === 'function') _setNeedleHandlesVisibility(needle.id, effectiveVisible, opacity);
        });
        renderDataTreeDebounced();
        redrawSeedNeedleOverlays();
        _scheduleDataTreeSave(`viewer.opacity:${id}`);
        return;
    }

    // Handle planning seed opacity
    if (id.startsWith('seed_')) {
        const seed = dataTreeState.planning.seeds.find(s => s.id === id);
        if (seed) {
            seed.opacity = opacity;
            applyMeshOpacity(scene3D.meshes[id], opacity, isDataTreeNodeVisible3D(seed));
            redrawSeedNeedleOverlays();
            requestViewerVisualRefresh('seed-opacity');
            _scheduleDataTreeSave(`viewer.opacity:${id}`);
        }
        return;
    }

    // Handle planning needle opacity
    if (id.startsWith('needle_')) {
        const needle = dataTreeState.planning.needles.find(n => n.id === id);
        if (needle) {
            needle.opacity = opacity;
            const effectiveVisible = isDataTreeNodeVisible3D(needle);
            applyMeshOpacity(scene3D.meshes[id], opacity, effectiveVisible);
            if (typeof _setNeedleHandlesVisibility === 'function') {
                _setNeedleHandlesVisibility(needle.id, effectiveVisible, opacity);
            }
            redrawSeedNeedleOverlays();
            requestViewerVisualRefresh('needle-opacity');
            _scheduleDataTreeSave(`viewer.opacity:${id}`);
        }
        return;
    }

    // Handle dose isosurface opacity
    if (id.startsWith('dose_iso_')) {
        const threshold = parseFloat(id.replace('dose_iso_', ''));
        const level = dataTreeState.planning.doseLevels.find(d => d.threshold === threshold);
        if (level) {
            level.opacity = opacity;
            applyMeshOpacity(scene3D.meshes[id], opacity, isDataTreeNodeVisible3D(level));
            requestViewerVisualRefresh('dose-isosurface-opacity');
            _scheduleDataTreeSave(`viewer.opacity:${id}`);
        }
        return;
    }

    // Handle manual/threshold mask opacity
    if (_isDataTreeMaskId(id)) {
        const rawId = _maskSceneMeshId(id);
        const mask = _maskStateEntry(id);
        if (mask && (!_isGenericSegmentationMask(mask) || _isOpenGenericMask(mask))) {
            mask.opacity = opacity;
            applyMeshOpacity(scene3D.meshes[rawId], opacity, mask.visible !== false);
            reloadOverlays();
            requestViewerVisualRefresh('mask-opacity');
            _scheduleDataTreeSave(`viewer.opacity:${id}`);
        }
        return;
    }

    // Guide skin uses a dedicated top-level Data Tree node rather than the
    // planning mesh collection.  This branch must run before the generic
    // dataTreeState[id] guard below; otherwise the skin opacity slider is a
    // silent no-op even though the node is rendered correctly.
    if (id === 'skin_surface') {
        dataTreeState.skin.opacity = opacity;
        applyMeshOpacity(
            scene3D.meshes.skin_surface,
            opacity,
            isDataTreeNodeVisible3D(dataTreeState.skin),
        );
        clearTimeout(_opacityTimer);
        _opacityTimer = setTimeout(() => {
            if (state.ctLoaded) reloadOverlays();
            requestViewerVisualRefresh('skin-opacity');
            renderDataTreeDebounced();
            _scheduleDataTreeSave('viewer.opacity:skin_surface');
        }, 150);
        return;
    }

    const meshEntry = (dataTreeState.planning.meshes || []).find(m => m.id === id);
    if (meshEntry) {
        meshEntry.opacity = opacity;
        applyMeshOpacity(scene3D.meshes[id], opacity, meshEntry.visible !== false);
        requestViewerVisualRefresh('planning-mesh-opacity');
        _scheduleDataTreeSave(`viewer.opacity:${id}`);
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
    _scheduleDataTreeSave(`viewer.opacity:${id}`);
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

/******** MANUAL / THRESHOLD MASKS ********/

// Rename a manual/threshold mask. When invoked from the UI (right-click) a
// prompt is shown; the ui_controller path passes the new name directly.
function renameDataTreeMask(id, providedName) {
    const mask = _maskStateEntry(id);
    if (!mask) return;
    const current = mask.name || id;
    let next = typeof providedName === 'string' ? providedName : null;
    if (next === null) {
        next = window.prompt(_dtText('输入新的掩膜名称', 'Enter a new mask name'), current);
    }
    if (next === null) return;
    const trimmed = String(next).trim();
    if (!trimmed) return;
    mask.name = trimmed;
    renderDataTree();
    _scheduleDataTreeSave('mask.rename');
    addChat('system', _dtText(`掩膜已重命名为 "${trimmed}"`, `Mask renamed to "${trimmed}"`));
}

// Rename any Data Tree node from its right-click menu. Masks keep the dedicated
// mask path; every other leaf (CTV label, OAR organ, seed, needle, trajectory,
// dose iso-surface, planning mesh, annotation) is renamed generically by
// updating its persisted `label`/`name` field, then re-rendering.
function renameDataTreeNode(id, providedName) {
    let node = _findDataTreeNode(id);
    let current = '';
    let setLabel = null;

    if (_isDataTreeMaskId(id)) {
        return renameDataTreeMask(id.replace(/^mask:/, ''), providedName);
    }
    if (id === 'ctv') {
        node = dataTreeState.ctv;
        current = node?.label || 'CTV Mask';
        setLabel = value => { if (node) node.label = value; };
    } else if (id === 'oar') {
        node = dataTreeState.oar;
        current = node?.label || 'All OARs';
        setLabel = value => { if (node) node.label = value; };
    } else if (id.startsWith('ctv_')) {
        node = dataTreeState.ctvLabels?.[id];
        current = node?.label || id;
        setLabel = value => { if (node) node.label = value; };
    } else if (id.startsWith('organ_')) {
        node = dataTreeState.organs.find(item => item.id === id) || null;
        current = node?.label || node?.name || id;
        setLabel = value => { if (node) { node.label = value; node.name = value; } };
    } else if (id.startsWith('dose_iso_')) {
        const threshold = parseFloat(id.replace('dose_iso_', ''));
        node = _planningItems('doseLevels').find(item => item.threshold === threshold) || null;
        current = node?.label || id;
        setLabel = value => { if (node) node.label = value; };
    } else {
        // Planning trajectories / seeds / needles / meshes and annotations.
        node = _findDataTreeNode(id);
        current = node?.label || node?.name || id;
        setLabel = value => {
            if (node) { node.label = value; node.name = value; }
        };
    }

    if (!node || !setLabel) return;
    let next = typeof providedName === 'string' ? providedName : null;
    if (next === null) {
        next = window.prompt(_dtText('输入新的名称', 'Enter a new name'), current);
    }
    if (next === null) return;
    const trimmed = String(next).trim();
    if (!trimmed) return;
    setLabel(trimmed);
    renderDataTree();
    // Organ/CTV 3D mesh labels read the data-tree label directly, so a rename
    // propagates to the 3D scene on the next appearance sync.
    if (typeof syncSceneAppearanceFromDataTree === 'function') syncSceneAppearanceFromDataTree();
    _scheduleDataTreeSave(`tree.rename:${id}`);
    addChat('system', _dtText(`已重命名为 "${trimmed}"`, `Renamed to "${trimmed}"`));
}
window.renameDataTreeNode = renameDataTreeNode;

// Delete a mask through the backend transaction. The old implementation only
// removed the browser mesh, so the object returned after refresh or Session
// restore. This wrapper intentionally shares the batch-delete path with all
// other Data Tree nodes.
function deleteDataTreeMask(id) {
    const value = String(id || '');
    if (!value) return false;
    return deleteSelectedDataTreeItems([value]);
}

// Move selected masks to the CTV or OAR display group. Masks are display-only
// structures (they never feed dose/planning); moving reclassifies their
// presentation so they render under the target structure's color/visibility.
async function moveSelectedMasks(classification, objectIds = null) {
    // Treat an explicitly supplied empty array as an intentional no-op.  A
    // live selection Set is not safe here because the async refresh below can
    // re-render the tree and change selection before the mutation completes.
    const ids = [...new Set((objectIds == null
        ? getSelectedDataTreeIds()
        : Array.from(objectIds)
    ).filter(id => {
        const value = String(id);
        return _isDataTreeMaskId(value);
    }))];
    if (!ids.length) return false;
    const expectedSessionId = _viewerDataSessionId();
    const stableIds = ids.map(id => _dataTreeObjectId(id)).filter(Boolean);
    const response = await fetch(API + '/data/generic-masks/classification', {
        method: 'PATCH',
        headers: {
            ..._viewerDataHeaders(expectedSessionId),
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            session_id: expectedSessionId,
            object_ids: stableIds,
            classification,
        }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.success === false) {
        throw new Error(payload.error || _dtText('掩膜分类更新失败', 'Mask classification failed'));
    }
    const targetColor = classification === 'ctv'
        ? (dataTreeState.ctv.color || DEFAULT_CTV_STRUCTURE_COLOR)
        : (dataTreeState.oar.color || DEFAULT_OAR_STRUCTURE_COLOR);
    ids.forEach(id => {
        const mask = _maskStateEntry(id);
        if (!mask) return;
        mask.movedTo = classification;
        mask.classification = classification;
        mask.parent_group = classification;
        mask.color = targetColor;
        // The promoted structure is now rendered from the effective label
        // volume. Hide the standalone binary-mask mesh to avoid double
        // rendering and to keep Data Tree visibility controlled by CTV/OAR.
        mask.visible = false;
        mask.visible2D = false;
        mask.visible3D = false;
        const mesh = scene3D?.meshes?.[_maskSceneMeshId(id)];
        if (mesh) applyMeshVisibility(mesh, false, mask.opacity ?? 0.6);
    });
    // The PATCH rebuilt the server-side effective CTV/OAR arrays. Hydrate
    // those arrays before drawing, otherwise the browser would only reflect
    // the metadata move and the next refresh would resurrect the old image.
    if (typeof loadLabelVolumes === 'function') {
        await loadLabelVolumes({
            sessionId: expectedSessionId,
            preserveViewerState: true,
            resetPresentation: false,
        });
    }
    await hydrateGenericMasksFromServer(_captureViewerDataScope(expectedSessionId));
    renderDataTree();
    reloadOverlays();
    requestViewerVisualRefresh('mask-move');
    if (typeof applyDataTreeViewVisibility === 'function') applyDataTreeViewVisibility();
    _scheduleDataTreeSave('mask.move');
    addChat('system', _dtText(
        `已移动 ${ids.length} 个掩膜到 ${classification.toUpperCase()}（仅显示，不参与剂量计算）。`,
        `Moved ${ids.length} mask(s) to ${classification.toUpperCase()} and rebuilt the effective Structure Set. Dose/DVH/report/guide are now stale and require recomputation.`,
    ));
    selectedItems.clear();
    return true;
}

// Parse a "x,y,z" voxel key.
function _maskKeyParts(key) {
    const parts = String(key).split(',');
    if (parts.length !== 3) return null;
    const x = Number(parts[0]);
    const y = Number(parts[1]);
    const z = Number(parts[2]);
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) return null;
    return { x, y, z };
}

// Whether a mask is currently displayed (respects its movedTo target and the
// target group's visibility).
function _maskVisibleInTarget(mask) {
    if (!mask || mask.visible === false || mask.visible2D === false) return false;
    // Promoted generic masks are painted from ctvLabelData/oarLabelData. If
    // they also enter this loop they are drawn twice after a tree refresh.
    const classification = _genericMaskClassification(mask);
    if (classification === 'ctv' || classification === 'oar') return false;
    const target = mask.movedTo;
    if (target === 'ctv') {
        const g = dataTreeState.ctv;
        return g.visible !== false && (state.viewerSettings.showCTV !== false);
    }
    if (target === 'oar') {
        const g = dataTreeState.oar;
        return g.visible !== false && (state.viewerSettings.showOAR !== false);
    }
    return true;
}
