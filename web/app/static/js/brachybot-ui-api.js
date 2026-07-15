function collectUIState() {
    const gv = (id) => {
        const el = document.getElementById(id);
        return el ? (el.value || '').trim() : '';
    };
    // Checkbox helper: read .checked (not .value — .value on a
    // checkbox is always "on" by default and doesn't reflect the
    // actual checked state).
    const gc = (id) => {
        const el = document.getElementById(id);
        return !!(el && el.checked);
    };
    const controls = Array.from(document.querySelectorAll('button, input, select, textarea, [role="button"], [data-ui-control]'))
        .slice(0, 260)
        .map((el) => {
            const ident = `${el.id || ''} ${el.getAttribute('name') || ''} ${el.getAttribute('autocomplete') || ''} ${el.getAttribute('placeholder') || ''}`.toLowerCase();
            const type = el.getAttribute('type') || null;
            const sensitive = type === 'password' || /(api[_-]?key|token|secret|password|authorization|bearer)/i.test(ident);
            return {
                id: el.id || null,
                tag: el.tagName.toLowerCase(),
                type,
                role: el.getAttribute('role') || null,
                text: (el.getAttribute('aria-label') || el.getAttribute('title') || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 80),
                value: sensitive ? '[redacted]' : (('value' in el) ? String(el.value || '').slice(0, 120) : ''),
                checked: ('checked' in el) ? !!el.checked : null,
                disabled: !!el.disabled,
                visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
            };
        })
        .filter(c => c.id || c.text || c.value);
    // 3D telemetry is intentionally compact: it gives the agent enough
    // evidence to distinguish an empty scene, hidden objects, and a layout
    // canvas that has not received a usable size, without serializing meshes.
    const _scene3d = (typeof scene3D !== 'undefined' && scene3D) ? scene3D : null;
    const _meshEntries = _scene3d && _scene3d.meshes ? Object.entries(_scene3d.meshes) : [];
    const _visibleMeshCount = _meshEntries.filter(([, mesh]) => {
        if (!mesh || mesh.visible === false) return false;
        const surface = (typeof getMeshSurface === 'function') ? getMeshSurface(mesh) : mesh;
        if (surface && surface.visible === false) return false;
        const material = surface && surface.material;
        const opacity = Array.isArray(material)
            ? Math.max(...material.map(m => Number(m?.opacity ?? 1)))
            : Number(material?.opacity ?? 1);
        return opacity > 0.001;
    }).length;
    const _canvas3d = document.getElementById('canvas3D');
    const _rendererCanvas3d = _scene3d?.renderer?.domElement;
    return {
        ct_path: gv('ctPath'),
        ctv_path: gv('ctvPath'),
        oar_path: gv('oarPath'),
        // The "useRLToggle" checkbox controls RL vs rule_based. The
        // previous version read `.value` which is always "on" and
        // made plan_mode ALWAYS report as 'rl' even when the user
        // hadn't checked the box.
        plan_mode: gc('useRLToggle') ? 'rl' : 'rule_based',
        dev_threshold: gv('devThreshold'),
        active_panel: document.querySelector('.panel-tab.active')?.dataset?.panel || null,
        overlays: {
            ctv: gc('overlayCTV'),
            oar: gc('overlayOAR'),
            dose_opacity: state?.doseOpacity ?? null,
            dose_visible: !!state?.doseOverlay?.visible,
            dose_texture_3d: !!state?.doseTexture?.enabled,
            dose_colorbar: (typeof getDoseColorbarConfig === 'function') ? {
                twoD: getDoseColorbarConfig('twoD'),
                threeD: getDoseColorbarConfig('threeD'),
            } : null,
        },
        planning: {
            metrics: state?.metrics || {},
            seed_count: state?.seeds?.length || 0,
            trajectories: state?.trajectories?.length || 0,
            // Preserve the editable vector for chat-driven replanning. The
            // generic control snapshot is not a reliable numeric contract.
            // When refDirecAuto is checked, planning uses geometric
            // auto-detection — expose that intent so the LLM knows the
            // actual planning input (not just the stale manual vector).
            ref_direc_auto: !!(document.getElementById('refDirecAuto')?.checked),
            reference_direc: (document.getElementById('refDirecAuto')?.checked)
                ? 'auto'
                : [
                    Number(document.getElementById('refDirecX')?.value || 0),
                    Number(document.getElementById('refDirecY')?.value || 1),
                    Number(document.getElementById('refDirecZ')?.value || 0),
                ],
            plan_mode: gc('useRLToggle') ? 'rl' : 'rule_based',
            seed_info: {
                radius: Number(document.getElementById('seedRadius')?.value || 0.4),
                length: Number(document.getElementById('seedLength')?.value || 4.5),
                seed_avr_dose: Number(document.getElementById('seedAvgDose')?.value || 50),
            },
            radiation_params: {
                target_value: Math.round(Number(document.getElementById('targetValue')?.value || 1)),
                obstacle_value: Math.round(Number(document.getElementById('obstacleValue')?.value || 2)),
                backlit_angle: Number(document.getElementById('backlitAngle')?.value || 0.5),
                maximum_candidate_trajectories: Math.round(Number(document.getElementById('maxCandiTraj')?.value || 500)),
            },
            in_lowest_energy: Number(document.getElementById('inLowestEnergy')?.value || 1),
            out_highest_energy: Number(document.getElementById('outHighestEnergy')?.value || 1),
            dvh_rate: Number(document.getElementById('dvhRate')?.value || 0.9),
            max_iter: Math.round(Number(document.getElementById('maxIter')?.value || 4)),
            iter_rate: Number(document.getElementById('iterRate')?.value || 2),
            replan_rate: Number(document.getElementById('replanRate')?.value || 0.6),
            distance_filter: {
                lower_bound: Number(document.getElementById('distLowerBound')?.value || 0.8),
                upper_bound: Number(document.getElementById('distUpperBound')?.value || 10),
            },
            manual_state: (typeof _manualState === 'function') ? _manualState() : {},
        },
        data_tree: (typeof dataTreeState !== 'undefined') ? {
            ctv_loaded: !!dataTreeState.ctv?.loaded,
            oar_count: dataTreeState.organs?.length || 0,
            // Planning consumes this compact whitelist. Keep IDs, labels and
            // parent categories, but never serialize mesh geometry here.
            organs: (dataTreeState.organs || []).map((organ) => ({
                id: organ.id || null,
                label_id: Number.isFinite(Number(organ.labelId)) ? Number(organ.labelId) : null,
                label: organ.label || organ.name || null,
                category: organ.category === 'non_traversable' ? 'non_traversable' : 'traversable',
                source: organ.source || (String(organ.id || '').startsWith('ctv_') ? 'ctv' : 'oar'),
            })).filter((organ) => organ.id || organ.label_id !== null),
            seeds: dataTreeState.planning?.seeds?.length || 0,
            needles: dataTreeState.planning?.needles?.length || 0,
            dose_levels: dataTreeState.planning?.doseLevels?.length || 0,
        } : {},
        manual: (typeof manualPlanningState !== 'undefined') ? {
            active_needle_id: manualPlanningState.activeNeedleId,
            seed_counter: manualPlanningState.seedCounter,
            needle_counter: manualPlanningState.needleCounter,
            dose_engine: manualPlanningState.doseEngine || 'dose_unet_spacing1mm',
        } : {},
        training: (typeof trainingMonitorState !== 'undefined') ? {
            active: !!trainingMonitorState.active,
            goal: trainingMonitorState.goal || '',
        } : {},
        controls,
        viewer: {
            ct_loaded: !!(state && state.ctLoaded),
            ct_shape: (state && state.ctShape) || null,
            current_slices: (state && state.slices) || null,
            window: (state && state.viewerSettings && state.viewerSettings.window) || null,
            level: (state && state.viewerSettings && state.viewerSettings.level) || null,
            threshold: (state && state.viewerSettings && state.viewerSettings.threshold) || null,
            show_ctv: !!(state && state.viewerSettings && state.viewerSettings.showCTV),
            show_oar: !!(state && state.viewerSettings && state.viewerSettings.showOAR),
            three_d: {
                initialized: !!_scene3d?.initialized,
                mesh_count: _meshEntries.length,
                visible_mesh_count: _visibleMeshCount,
                canvas_width: _canvas3d?.clientWidth || 0,
                canvas_height: _canvas3d?.clientHeight || 0,
                renderer_width: _rendererCanvas3d?.width || 0,
                renderer_height: _rendererCanvas3d?.height || 0,
                context_lost: !!_scene3d?.contextLost,
            },
        },
    };
}

const state = {
    brainAvailable: false,
    sessionId: 'web',
    metrics: {},
    seeds: [],
    dvhData: null,
    plan3D: null,
    mesh3D: null,
    ctPath: null,
    ctLoaded: false,
    ctShape: null,
    ctSpacing: null,
    ctOrigin: null,
    ctDirection: null,
    seedsOverlay: null,  // { seeds: [...], needles: [...] } in world coords
    slices: { axial: 0, sagittal: 0, coronal: 0 },
    doseOpacity: 0.4,
    doseTexture: {
        enabled: false,
        applying: false,
        rawAxialSlices: {},
        rawAxialSlicePromises: {},
        originalMaterials: {},
        originalSceneStyle: {},
        originalSkinStyle: null,
    },
    viewerSettings: {
        window: 400,
        level: 40,
        threshold: null,
        showCTV: false,
        showOAR: false,
        displayMode: 'ct',
        zoom: 1.0,
        panX: 0,
        panY: 0,
        flipH: false,
        flipV: false,
        rotation: 0,
        activeTool: 'crosshair',
        layout: 'vertical',
    },
    annotations: [],
    annotationUndoStack: [],
    annotationRedoStack: [],
    // Manual mask drawing state
    maskLabels: {}, // { 'mask_1': { name: 'Manual Mask 1', color: '#ff0000', slices: { axial: Set, sagittal: Set, coronal: Set }, visible: true, opacity: 0.6 } }
    maskLabelCounter: 0,
    labelImage: {
        axial:   { visible: true, opacity: 0.6 },
        sagittal: { visible: true, opacity: 0.6 },
        coronal:  { visible: true, opacity: 0.6 },
        '3d':     { visible: true, opacity: 0.6 },
    },
};

/******** API ********/
const API = '/api';

var trainingMonitorState = {
    active: false,
    goal: '',
    sessionId: 'web',
    lastFeedbackAt: 0,
    lastScreenshotAt: 0,
};

var manualPlanningState = {
    activeNeedleId: null,
    seedCounter: 0,
    needleCounter: 0,
    doseEngine: 'dose_unet_spacing1mm',
};

function _activeApiSessionId() {
    return (typeof activeSessionId !== 'undefined' && activeSessionId) || state.sessionId || 'web';
}

function _shouldLogTrainingFeedback(message) {
    if (!message || !trainingMonitorState.active) return false;
    const now = Date.now();
    const important = /dose|V100|D90|Seed|Needle|step/i.test(message);
    if (!important && now - trainingMonitorState.lastFeedbackAt < 15000) return false;
    trainingMonitorState.lastFeedbackAt = now;
    return true;
}

async function syncUIBridgeState(reason = 'snapshot') {
    try {
        await fetch(API + '/ui/state', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: _activeApiSessionId(),
                reason,
                state: (typeof collectUIState === 'function') ? collectUIState() : {},
            }),
        });
    } catch (e) {
        console.debug('[ui-state] sync skipped:', e);
    }
}

async function reportUIEvent(type, label, detail = {}, options = {}) {
    try {
        const res = await fetch(API + '/ui/event', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: _activeApiSessionId(),
                type,
                label,
                detail,
                ui_state: (typeof collectUIState === 'function') ? collectUIState() : {},
            }),
        });
        const data = await res.json().catch(() => null);
        if (data && data.feedback && _shouldLogTrainingFeedback(data.feedback)) {
            addChat('system', `Monitor: ${data.feedback}`);
        }
        if (data && data.suggested_screenshot && trainingMonitorState.active) {
            const now = Date.now();
            if (now - trainingMonitorState.lastScreenshotAt > 45000 && typeof _interceptScreenshot === 'function') {
                trainingMonitorState.lastScreenshotAt = now;
                const ss = data.suggested_screenshot;
                setTimeout(() => _interceptScreenshot(ss.target || 'dose-overview', ss.question || ss.description || 'Monitor screenshot'), 500);
            }
        }
        if (options.returnData) return data;
    } catch (e) {
        console.debug('[ui-event] report skipped:', e);
    }
    return null;
}

function _parseUIControlPayload(value) {
    if (value && typeof value === 'object') return value;
    if (typeof value !== 'string') return {};
    const raw = value.trim();
    if (!raw) return {};
    try {
        return JSON.parse(raw);
    } catch (_) {
        return raw.startsWith('#') || raw.includes('[') || raw.includes('.') || raw.includes(' ')
            ? { selector: raw }
            : { id: raw };
    }
}

function _resolveUIControlElement(payload) {
    const p = _parseUIControlPayload(payload);
    if (p.id) return document.getElementById(String(p.id).replace(/^#/, ''));
    if (p.selector) {
        try { return document.querySelector(String(p.selector)); } catch (_) { return null; }
    }
    return null;
}

function executeGenericUIControl(command, value) {
    const payload = _parseUIControlPayload(value);
    const el = _resolveUIControlElement(payload);
    if (!el) {
        if (typeof addChat === 'function') addChat('error', `UI control not found: ${JSON.stringify(value)}`);
        return false;
    }
    const cmd = command || payload.command || 'click';
    if (cmd === 'click') {
        el.click();
    } else if (cmd === 'toggle') {
        if ('checked' in el) {
            el.checked = payload.checked !== undefined ? !!payload.checked : !el.checked;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        } else {
            el.click();
        }
    } else if (cmd === 'set') {
        const nextValue = payload.value !== undefined ? payload.value : payload.text;
        if ('checked' in el && (el.type === 'checkbox' || el.type === 'radio')) {
            el.checked = !!nextValue;
        } else if ('value' in el) {
            el.value = nextValue === undefined ? '' : String(nextValue);
        } else if (nextValue !== undefined) {
            el.textContent = String(nextValue);
        }
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
    } else if (cmd === 'focus') {
        el.focus();
    } else if (cmd === 'blur') {
        el.blur();
    } else {
        console.warn('[UIAction] Unsupported generic control command:', cmd);
        return false;
    }
    reportUIEvent('ui.control', payload.id || payload.selector || el.id || el.tagName.toLowerCase(), { command: cmd, payload });
    return true;
}

function instrumentUIControls() {
    if (window._brachyUiInstrumentationReady) return;
    window._brachyUiInstrumentationReady = true;
    let rangeTimer = null;
    document.addEventListener('click', (event) => {
        const btn = event.target.closest('button');
        if (!btn || btn.disabled) return;
        const label = (btn.getAttribute('title') || btn.textContent || btn.id || '').trim().replace(/\s+/g, ' ').slice(0, 80);
        reportUIEvent('ui.click', label || 'button', { id: btn.id || null, classes: btn.className || '' });
    }, true);
    document.addEventListener('change', (event) => {
        const el = event.target;
        if (!el || !['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName)) return;
        const value = el.type === 'checkbox' ? !!el.checked : el.value;
        reportUIEvent('ui.change', el.id || el.name || el.tagName.toLowerCase(), { value });
    }, true);
    document.addEventListener('input', (event) => {
        const el = event.target;
        if (!el || el.type !== 'range') return;
        clearTimeout(rangeTimer);
        rangeTimer = setTimeout(() => {
            reportUIEvent('ui.slider', el.id || el.name || 'range', { value: el.value });
        }, 400);
    }, true);
}

(function installApiRequestFetchWrapper() {
    const nativeFetch = window.fetch.bind(window);
    // Support ?api_key=xxx in URL
    const urlParams = new URLSearchParams(window.location.search);
    const keyFromUrl = urlParams.get('api_key');
    if (keyFromUrl) {
        localStorage.setItem('BRACHYBOT_API_KEY', keyFromUrl);
        window.BRACHYBOT_API_KEY = keyFromUrl;
        // Clean URL without reload
        const cleanUrl = window.location.pathname;
        window.history.replaceState({}, '', cleanUrl);
    }
    window.setBrachyBotApiKey = function setBrachyBotApiKey(key) {
        const value = String(key || '').trim();
        window.BRACHYBOT_API_KEY = value;
        if (value) localStorage.setItem('BRACHYBOT_API_KEY', value);
        else localStorage.removeItem('BRACHYBOT_API_KEY');
    };
    window.fetch = function brachybotFetch(input, init) {
        const key = window.BRACHYBOT_API_KEY || localStorage.getItem('BRACHYBOT_API_KEY') || '';
        const url = typeof input === 'string' ? input : (input && input.url) || '';
        let isApiRequest = url.startsWith(API + '/') || url.startsWith('/api/');
        if (!isApiRequest) {
            try {
                const parsed = new URL(url, window.location.href);
                isApiRequest = parsed.origin === window.location.origin
                    && parsed.pathname.startsWith('/api/');
            } catch (_) { /* native fetch will report malformed URLs */ }
        }
        if (!isApiRequest) return nativeFetch(input, init);
        const nextInit = Object.assign({}, init || {});
        const headers = new Headers(nextInit.headers || (input && input.headers) || {});
        if (key && !headers.has('X-API-Key')) headers.set('X-API-Key', key);
        if (!headers.has('X-BrachyBot-Session')) {
            headers.set('X-BrachyBot-Session', _activeApiSessionId());
        }
        nextInit.headers = headers;
        return nativeFetch(input, nextInit);
    };
})();

// Abort controller for stopping streaming responses
let chatAbortController = null;
let isStreaming = false;

async function api(endpoint, body) {
    const res = await fetch(API + endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
        throw new Error(err.error || `Request failed: ${res.status}`);
    }
    return res.json();
}

/******** FILE PICKER ********/
async function handleFileSelect(input, targetId) {
    const files = input.files ? Array.from(input.files) : [];
    if (files.length === 0) return;

    const pathInput = document.getElementById(targetId);
    const overlay = document.getElementById('uploadProgressOverlay');
    const progressText = document.getElementById('uploadProgressText');
    const progressFilename = document.getElementById('uploadProgressFilename');

    // Show upload progress overlay
    progressText.textContent = files.length === 1
        ? 'Uploading file...'
        : `Uploading ${files.length} files...`;
    progressFilename.textContent = files.length === 1
        ? files[0].name
        : `${files[0].name} … (+${files.length - 1} more)`;
    overlay.classList.add('active');
    pathInput.disabled = true;

    try {
        const formData = new FormData();
        // Append every file with the same form key — the server's
        // `getlist('file')` collects them all. For folder uploads each
        // File carries its webkitRelativePath so the server can keep
        // per-folder structure.
        for (const f of files) formData.append('file', f, f.name);

        const res = await fetch(API + '/upload', {
            method: 'POST',
            body: formData,
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({ error: 'Upload failed' }));
            throw new Error(err.error || 'Upload failed');
        }

        const data = await res.json();
        pathInput.value = data.path;
        pathInput.disabled = false;

        // Auto-load CT to viewers if it's a CT file
        if (targetId === 'ctPath') {
            state.ctPath = data.path;
            state.ctSourceKind = data.kind || null;
            addChat('system',
                data.kind === 'dicom_folder'
                    ? `Uploaded DICOM folder (${data.file_count} files) → ${data.path}`
                    : `Uploaded ${data.filename} (${(data.size / 1024 / 1024).toFixed(2)} MB)`);
            await loadCTToViewers(data.path);
        }

        overlay.classList.remove('active');
    } catch (e) {
        overlay.classList.remove('active');
        pathInput.value = '';
        pathInput.disabled = false;
        alert('File upload failed: ' + e.message);
    }

    input.value = '';
}

/**
 * Reset all segmentation, planning, and data tree state when loading a new CT.
 * Must be called before loading new CT to clear stale data.
 */
function resetAllState() {
    // Clear segmentation data arrays
    ctvLabelData = null;
    oarLabelData = null;
    labelColorLUT = {};
    organMetaFromServer = {};
    window._ctvLabelMap = {};

    // Reset data tree state
    dataTreeState.ctv.loaded = false;
    dataTreeState.ctv.visible = true;
    dataTreeState.oar.loaded = false;
    dataTreeState.oar.visible = true;
    dataTreeState.organs = [];
    dataTreeState.ctvLabels = {};
    dataTreeState.dose.loaded = false;
    dataTreeState.seeds.loaded = false;
    dataTreeState.needles.loaded = false;
    dataTreeState.planning.trajectories = [];
    dataTreeState.planning.trajectoriesLoaded = false;
    dataTreeState.planning.seeds = [];
    dataTreeState.planning.needles = [];
    dataTreeState.planning.doseLevels = [];
    dataTreeState.planning.meshes = [];

    // Clear 3D meshes
    if (typeof scene3D !== 'undefined' && scene3D.meshes) {
        Object.keys(scene3D.meshes).forEach(id => {
            const mesh = scene3D.meshes[id];
            if (mesh && mesh.parent) mesh.parent.remove(mesh);
            if (mesh && mesh.geometry) mesh.geometry.dispose();
            if (mesh && mesh.material) mesh.material.dispose();
        });
        scene3D.meshes = {};
    }

    // Clear slice caches
    if (typeof sliceCache !== 'undefined') {
        sliceCache.axial = {};
        sliceCache.sagittal = {};
        sliceCache.coronal = {};
    }
    if (typeof overlayCache !== 'undefined') {
        overlayCache.axial = {};
        overlayCache.sagittal = {};
        overlayCache.coronal = {};
    }

    // Clear volume data
    if (typeof volumeData !== 'undefined') volumeData = null;

    // Reset image analysis data
    imageAnalysisData.ct = null;
    imageAnalysisData.ctv = null;
    imageAnalysisData.oar = null;

    // Re-render data tree
    renderDataTree();
}

/**
 * Clear the browser workspace without touching another server session.
 * Session changes call this before restoring the selected session so CT,
 * contours, dose, planning geometry, and report fields cannot bleed from
 * the previously active case.
 */
function clearClientWorkspace(options = {}) {
    resetAllState();
    state.ctLoaded = false;
    state.ctPath = null;
    state.ctShape = null;
    state.ctSpacing = null;
    state.ctOrigin = null;
    state.ctDirection = null;
    state.ctHURange = null;
    state.ctDicomTags = {};
    state.ctSourceKind = null;
    state.ctSourceMeta = {};
    state.doseOverlay = null;
    state.dvhData = null;
    state.metrics = {};
    state.seeds = [];
    state.trajectories = [];
    if (typeof volumeShape !== 'undefined') volumeShape = null;
    if (typeof volumeSpacing !== 'undefined') volumeSpacing = null;
    if (typeof updateSeeds === 'function') updateSeeds([]);
    if (typeof updateMetrics === 'function') updateMetrics({});
    if (typeof updateOARTable === 'function') updateOARTable({});
    const ctPathInput = document.getElementById('ctPath');
    if (ctPathInput) ctPathInput.value = '';
    const dvhEl = document.getElementById('dvhChart');
    if (dvhEl && typeof Plotly !== 'undefined' && Plotly.purge) {
        try { Plotly.purge(dvhEl); } catch (_) {}
    }
    if (typeof drawDVH === 'function') drawDVH._lastSig = null;
    const dvhPlaceholder = document.getElementById('dvhPlaceholder');
    if (dvhPlaceholder) dvhPlaceholder.style.display = '';
    document.querySelectorAll('.dose-colorbar').forEach(el => { el.style.display = 'none'; });
    document.querySelectorAll('.viewer-no-data').forEach(el => { el.style.display = ''; });
    if (options.clearReport !== false && typeof _newEmptyReportForm === 'function') {
        window.reportForm = _newEmptyReportForm();
        try { renderReportEditor(); } catch (_) {}
        try { _updateReportPreview(); } catch (_) {}
    }
    updateImageAnalysis();
    renderDataTree();
    if (typeof _refreshManualStepUI === 'function') _refreshManualStepUI();
}
window.clearClientWorkspace = clearClientWorkspace;

// ----- Image Analysis (DICOM-aware) -----
// `imageAnalysisData` is referenced widely but was never declared. We
// declare it here so the Analysis panel can render, and so we have a
// canonical place to stash header metadata that the report and viewer
// can both read from.
var imageAnalysisData = { ct: null, ctv: null, oar: null };

async function pullHeaderInfo(ctPath) {
    // Fetch /api/header/info for a CT path, stash tags into state + agent
    // memory proxies, and re-render the Analysis panel.
    // Idempotent: safe to call multiple times for the same path.
    if (!ctPath) return;
    try {
        const res = await fetch(API + '/header/info', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ct_path: ctPath }),
        });
        if (!res.ok) return;
        const data = await res.json();
        if (!data.success) return;
        // Stash where everything else can read it
        state.ctDicomTags = data.tags || {};
        state.ctSourceKind = data.kind || state.ctSourceKind || null;
        state.ctSourceMeta = data.meta || {};
        // Mirror into imageAnalysisData.ct (preserving existing shape/spacing)
        const cur = imageAnalysisData.ct || {};
        imageAnalysisData.ct = Object.assign({}, cur, {
            dicom: data.tags || {},
            kind: data.kind || null,
            sourceMeta: data.meta || {},
        });
        updateImageAnalysis();
    } catch (e) {
        console.warn('pullHeaderInfo failed:', e);
    }
}

function updateImageAnalysis() {
    const host = document.getElementById('analysisContent');
    const section = document.getElementById('analysisSection');
    const timeEl = document.getElementById('analysisTime');
    if (!host) return;
    if (!section) return;

    const ct = imageAnalysisData.ct;
    if (!ct) {
        section.style.display = 'none';
        return;
    }
    section.style.display = '';

    const d = ct.dicom || {};
    // 2026-06-16: prefer the global UI language toggle
    // (window._i18nLang, controlled by the EN/中 chip in the
    // top-right header). Fall back to the Report panel's own
    // `language` field for legacy callers that don't go through
    // the global toggle, then 'en' as final default. The user
    // reported (round 2) that the previous version read
    // reportForm.language which defaults to 'zh', so the
    // Analysis panel always showed Chinese even when the UI
    // toggle was set to English.
    const lang = window._i18nLang
        || (window.reportForm && window.reportForm.language)
        || 'en';
    const t = (zh, en) => lang === 'en' ? en : zh;

    // Build the table as a list of grouped sections so the panel
    // can show more rows (CT stats, DICOM metadata, segmentation
    // stats) without becoming a wall of text. Each group has a
    // sub-header and a 2-col key/value table underneath.
    const groups = [];

    // ----- Group 1: Image geometry (always present after /viewer/load) -----
    const geo = [];
    if (ct.shape && ct.shape.length === 3) {
        const [z, y, x] = ct.shape;
        geo.push([t('体素 (X × Y × Z)', 'Voxels (X × Y × Z)'), `${x} × ${y} × ${z}`]);
        // Total slice count for the 3 viewports
        geo.push([t('总切片数', 'Total slices'), `${z} (axial) / ${y} (coronal) / ${x} (sagittal)`]);
    }
    if (ct.spacing && ct.spacing.length === 3) {
        const [sx, sy, sz] = ct.spacing;
        geo.push([t('像素间距 (mm)', 'Pixel spacing (mm)'),
            `${sx.toFixed(3)} × ${sy.toFixed(3)} × ${sz.toFixed(3)}`]);
        // Physical volume (mm³ → cm³)
        if (ct.shape && ct.shape.length === 3) {
            const [z, y, x] = ct.shape;
            const physVolMm3 = x * y * z * sx * sy * sz;
            const physVolCm3 = physVolMm3 / 1000;
            geo.push([t('物理体积', 'Physical volume'), `${physVolMm3.toFixed(0)} mm³ (${physVolCm3.toFixed(1)} cm³)`]);
        }
    }
    if (ct.huRange && ct.huRange.length === 2) {
        geo.push([t('HU 范围', 'HU range'),
            `${ct.huRange[0].toFixed(0)} → ${ct.huRange[1].toFixed(0)}`]);
        // Histogram peak / mode (useful to confirm the CT is the
        // expected body window)
        if (ct.huHistogram && Array.isArray(ct.huHistogram)) {
            const peakBin = ct.huHistogram.reduce((maxIdx, v, i, a) =>
                v > (a[maxIdx] || 0) ? i : maxIdx, 0);
            const peakHU = ct.huMin != null && ct.huMax != null
                ? ct.huMin + (peakBin / Math.max(1, ct.huHistogram.length - 1)) * (ct.huMax - ct.huMin)
                : null;
            if (peakHU !== null) {
                geo.push([t('HU 峰值', 'HU peak (mode)'), `${peakHU.toFixed(0)} HU`]);
            }
        }
    }
    // Window/Level (matches the 2D viewer's current W/L)
    if (state && state.viewerSettings) {
        geo.push([t('窗位 / 窗宽', 'Window / Level'),
            `W ${state.viewerSettings.window.toFixed(0)} / L ${state.viewerSettings.level.toFixed(0)}`]);
    }
    if (geo.length) groups.push({ title: t('📐 图像几何', '📐 Image Geometry'), rows: geo });

    // ----- Group 2: DICOM metadata (only if DICOM source) -----
    const meta = [];
    if (d.patient_name)         meta.push([t('患者姓名', 'Patient name'),       d.patient_name]);
    if (d.patient_id)           meta.push([t('患者 ID',   'Patient ID'),         d.patient_id]);
    if (d.patient_sex_label_zh || d.patient_sex_label_en) {
        meta.push([t('性别', 'Sex'),
            lang === 'en' ? (d.patient_sex_label_en || d.patient_sex) : (d.patient_sex_label_zh || d.patient_sex)]);
    }
    if (d.study_date)           meta.push([t('检查日期', 'Study date'),         d.study_date]);
    if (d.modality)             meta.push([t('影像模态', 'Modality'),           d.modality]);
    if (d.manufacturer)         meta.push([t('设备厂家', 'Manufacturer'),       d.manufacturer]);
    if (d.station_name)         meta.push([t('工作站',   'Station'),            d.station_name]);
    if (d.institution_name)     meta.push([t('送检单位', 'Institution'),        d.institution_name]);
    if (d.study_description)    meta.push([t('检查描述', 'Study description'),  d.study_description]);
    if (d.series_description)   meta.push([t('序列描述', 'Series description'), d.series_description]);
    if (d.accession_number)     meta.push([t('检查号',   'Accession #'),        d.accession_number]);
    if (d.performing_physician) meta.push([t('检查医师', 'Performing physician'), d.performing_physician]);
    if (meta.length) groups.push({ title: t('🏥 DICOM 元数据', '🏥 DICOM Metadata'), rows: meta });

    // ----- Group 3: Source -----
    const kindLabel = {
        volume:        t('NIfTI / 体积文件', 'NIfTI / volume file'),
        dicom_file:    t('DICOM 单文件',     'DICOM single file'),
        dicom_series:  t('DICOM 序列',       'DICOM series'),
    };
    if (ct.kind && kindLabel[ct.kind]) {
        const tail = ct.kind === 'dicom_series' && ct.sourceMeta
            ? ` · ${ct.sourceMeta.series_count || '?'} series · ${ct.sourceMeta.file_count || '?'} ${t('切片', 'slices')}`
            : '';
        groups.push({ title: t('📁 数据来源', '📁 Source'), rows: [
            [t('数据来源', 'Source'), kindLabel[ct.kind] + tail]
        ]});
    }

    // ----- Group 4: Segmentation stats (NEW 2026-06-16) -----
    // Pull CTV and OAR label counts + volumes from dataTreeState, which
    // is the canonical client-side store for segmentation results
    // (ctvLabelData / oarLabelData get written by loadLabelVolumes
    // and re-fetched by refreshPlanningUI).
    const seg = [];
    const ctvLabels = (typeof ctvLabelData !== 'undefined' && ctvLabelData && ctvLabelData.labels) || [];
    const oarLabels = (typeof oarLabelData !== 'undefined' && oarLabelData && oarLabelData.labels) || [];
    if (ctvLabels.length) {
        const totalVoxels = ctvLabels.reduce((s, l) => s + (l.voxel_count || 0), 0);
        const totalVolMm3 = ctvLabels.reduce((s, l) => s + (l.volume_mm3 || 0), 0);
        seg.push([t('CTV 标签数', 'CTV labels'), `${ctvLabels.length}`]);
        if (totalVoxels > 0) {
            seg.push([t('CTV 体素 / 体积', 'CTV voxels / volume'),
                `${totalVoxels.toLocaleString()} voxels · ${totalVolMm3.toFixed(0)} mm³ (${(totalVolMm3/1000).toFixed(2)} cm³)`]);
        }
        // Per-label top-3
        const top3 = [...ctvLabels].sort((a, b) => (b.volume_mm3 || 0) - (a.volume_mm3 || 0)).slice(0, 3);
        for (const lbl of top3) {
            if (lbl.name) {
                seg.push([`  · ${lbl.name}`,
                    `${(lbl.voxel_count || 0).toLocaleString()} vox · ${(lbl.volume_mm3 || 0).toFixed(0)} mm³`]);
            }
        }
    }
    if (oarLabels.length) {
        const totalOarVoxels = oarLabels.reduce((s, l) => s + (l.voxel_count || 0), 0);
        const totalOarVolMm3 = oarLabels.reduce((s, l) => s + (l.volume_mm3 || 0), 0);
        seg.push([t('OAR 标签数', 'OAR labels'), `${oarLabels.length}`]);
        if (totalOarVoxels > 0) {
            seg.push([t('OAR 总体素 / 体积', 'OAR total voxels / volume'),
                `${totalOarVoxels.toLocaleString()} voxels · ${totalOarVolMm3.toFixed(0)} mm³ (${(totalOarVolMm3/1000).toFixed(2)} cm³)`]);
        }
        // Top-3 OAR by volume
        const top3 = [...oarLabels].sort((a, b) => (b.volume_mm3 || 0) - (a.volume_mm3 || 0)).slice(0, 3);
        for (const lbl of top3) {
            if (lbl.name) {
                seg.push([`  · ${lbl.name}`,
                    `${(lbl.voxel_count || 0).toLocaleString()} vox · ${(lbl.volume_mm3 || 0).toFixed(0)} mm³`]);
            }
        }
    }
    // Plan metrics (only when planning has run — these are the
    // headline numbers the user actually looks for)
    if (state.metrics && Object.keys(state.metrics).length > 0) {
        const m = state.metrics;
        if (m.d90 != null) seg.push([t('D90 (CTV 覆盖)', 'D90 (CTV coverage)'), `${m.d90.toFixed(2)} Gy`]);
        if (m.v100 != null) seg.push([t('V100 (CTV 覆盖)', 'V100 (CTV coverage)'), `${(m.v100 * 100).toFixed(1)}%`]);
        if (m.v150 != null) seg.push([t('V150', 'V150'), `${(m.v150 * 100).toFixed(1)}%`]);
        if (m.d2 != null)   seg.push([t('D2 (最高剂量)', 'D2 (max dose)'), `${m.d2.toFixed(2)} Gy`]);
        if (m.dmean != null) seg.push([t('Dmean', 'Dmean'), `${m.dmean.toFixed(2)} Gy`]);
        if (m.plan_score != null) seg.push([t('计划评分', 'Plan score'), `${m.plan_score.toFixed(0)}/100`]);
        if (state.seeds && state.seeds.length) {
            seg.push([t('粒子数 / 路径数', 'Seeds / Trajectories'),
                `${state.seeds.length} seeds · ${(state.trajectories || []).length} trajectories`]);
        }
    }
    if (seg.length) groups.push({ title: t('🧬 分割 & 计划', '🧬 Segmentation & Plan'), rows: seg });

    // Render
    const renderGroup = (g) => `
        <div style="margin-top:6px;">
            <div style="font-size:0.6rem;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.06em;padding:3px 6px;border-bottom:1px solid var(--border-hairline);margin-bottom:2px;">${g.title}</div>
            <table class="rp-oar-table" style="font-size:0.66rem;">
                <tbody>
                ${g.rows.map(([k, v]) => `<tr><th style="text-align:left;color:var(--text-dim);font-weight:500;width:42%;padding:2px 6px;vertical-align:top;">${k}</th><td style="padding:2px 6px;vertical-align:top;">${v}</td></tr>`).join('')}
                </tbody>
            </table>
        </div>
    `;
    const html = groups.length === 0
        ? `<div style="font-size:0.7rem;color:var(--text-dim);padding:6px;">—</div>`
        : groups.map(renderGroup).join('');
    host.innerHTML = html;
    if (timeEl) timeEl.textContent = new Date().toLocaleTimeString();
}

async function loadCTToViewers(ctPath, options = {}) {
    if (!ctPath) return;

    const announce = options.announce !== false;

    const overlay = document.getElementById('uploadProgressOverlay');
    const progressText = document.getElementById('uploadProgressText');

    // Update overlay text to show CT loading
    progressText.textContent = 'Loading CT to viewers...';

    if (announce) addChat('system', 'Loading CT image to viewers...');

    // Reset all segmentation and planning state for new CT
    resetAllState();

    // Per-patient memory isolation on the FRONTEND. The server
    // also clears its memory if the CT path changed (see
    // /api/viewer/load). We additionally:
    //   - clear the DVH chart (so old curves don't linger)
    //   - clear metrics / OAR table
    //   - clear state.seeds (so the data tree badge resets)
    //   - clear the Report panel so the next plan gets a fresh form
    //   - reset the local DVH "last signature" so the next plan
    //     is allowed to redraw (otherwise drawDVH thinks the data
    //     is unchanged and skips the render).
    state.metrics = {};
    state.dvhData = null;
    state.seeds = [];
    if (typeof updateMetrics === 'function') updateMetrics({});
    const dvhPlaceholder = document.getElementById('dvhPlaceholder');
    if (dvhPlaceholder) dvhPlaceholder.style.display = '';
    const dvhEl = document.getElementById('dvhChart');
    if (dvhEl && typeof Plotly !== 'undefined' && Plotly.purge) {
        try { Plotly.purge(dvhEl); } catch (_) {}
    }
    if (typeof drawDVH === 'function') drawDVH._lastSig = null;
    const oarTbody = document.getElementById('oarTableBody');
    if (oarTbody) oarTbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-dim);padding:0.75rem;">No OAR data</td></tr>';
    try { if (typeof renderDataTree === 'function') renderDataTree(); } catch (_) {}
    try {
        if (typeof _newEmptyReportForm === 'function') {
            window.reportForm = _newEmptyReportForm();
            if (typeof renderReportEditor === 'function') renderReportEditor();
            if (typeof _updateReportPreview === 'function') _updateReportPreview();
        }
    } catch (_) {}

    try {
        const res = await fetch(API + '/viewer/load', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ct_path: ctPath,
                window_center: state.viewerSettings.level,
                window_width: state.viewerSettings.window,
            }),
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const data = await res.json();
        if (data.success) {
            state.ctPath = ctPath;
            state.ctShape = data.shape;
            state.ctSpacing = data.spacing;
            state.ctOrigin = data.origin;
            state.ctDirection = data.direction;
            state.ctHURange = data.hu_range;

            // Update slice sliders
            const axes = ['axial', 'sagittal', 'coronal'];
            axes.forEach((axis, i) => {
                const slider = document.getElementById('slider' + capitalize(axis));
                const sliceInfo = data.slices[axis];
                if (slider && sliceInfo) {
                    slider.max = sliceInfo.total_slices - 1;
                    slider.value = sliceInfo.slice_index;
                    state.slices[axis] = sliceInfo.slice_index;
                    const label = document.getElementById('sliceLabel' + capitalize(axis));
                    if (label) label.textContent = sliceInfo.slice_index;
                }
            });

            // Load CT volume for client-side rendering
            await loadVolumeData();
            state.ctLoaded = true;

            // Render initial slices from volume
            ['axial', 'sagittal', 'coronal'].forEach(axis => {
                renderSliceFromVolume(axis, state.slices[axis]);
            });

            // Rebind viewer interactions after canvases are rendered
            setTimeout(() => {
                setupViewerInteractions();
            }, 500);

            // Update data tree and load overlays if data exists
            renderDataTree();
            // Load overlays for all axes (will show nothing if no segmentation data)
            setTimeout(() => {
                ['axial', 'sagittal', 'coronal'].forEach(axis => {
                    loadOverlay(axis, state.slices[axis]);
                });
            }, 100);

            const ctPathInput = document.getElementById('ctPath');
            if (ctPathInput) ctPathInput.value = ctPath;
            if (announce) {
                addChat('system', `CT loaded: ${data.shape.join(' × ')} voxels, ${data.hu_range[0].toFixed(0)} to ${data.hu_range[1].toFixed(0)} HU`);
            }

            // Image Analysis is updated in loadVolumeData() after volume data loads
            // If volume data failed to load, set basic CT info from server response
            if (!imageAnalysisData.ct) {
                imageAnalysisData.ct = {
                    shape: data.shape,
                    spacing: data.spacing,
                    huRange: data.hu_range,
                    meanHU: 0,
                    scanRange: data.shape.map((s, i) => (s * data.spacing[i] / 10).toFixed(1)),
                    tissueDist: null,
                };
                updateImageAnalysis();
            }

            // Pull DICOM header (works for .dcm and DICOM series folders
            // too — the server now resolves any of NIfTI / single .dcm /
            // DICOM series). This populates the Analysis panel and stashes
            // the same tags into state.ctDicomTags for the report
            // auto-fill to read.
            pullHeaderInfo(ctPath);
        }
    } catch (e) {
        overlay.classList.remove('active');
        if (announce) addChat('error', 'Failed to load CT: ' + e.message);
        else console.warn('[session restore] Failed to restore CT:', e);
        throw e;
    }
}

async function restoreActiveSessionWorkspace(options = {}) {
    const sessionAtStart = _activeApiSessionId();
    clearClientWorkspace({ clearReport: options.clearReport !== false });
    if (options.clearReport !== false && typeof _loadReportFromStorage === 'function') {
        _loadReportFromStorage();
        try { renderReportEditor(); } catch (_) {}
        try { _updateReportPreview(); } catch (_) {}
    }

    let status = options.status || null;
    if (!status || status.session_id !== sessionAtStart) {
        const response = await fetch(API + '/status');
        if (!response.ok) throw new Error(`Session status failed: HTTP ${response.status}`);
        status = await response.json();
    }
    if (_activeApiSessionId() !== sessionAtStart) return null;

    state.sessionId = status.session_id || sessionAtStart;
    state.brainAvailable = !!status.brain_available;
    const sessionDisplay = document.getElementById('sessionDisplay');
    if (sessionDisplay) sessionDisplay.textContent = state.sessionId;

    // Training state belongs to the selected planning session as well.
    try {
        const uiResponse = await fetch(API + '/ui/state');
        if (uiResponse.ok && _activeApiSessionId() === sessionAtStart) {
            const uiData = await uiResponse.json();
            const training = uiData.training || {};
            trainingMonitorState.active = !!training.active;
            trainingMonitorState.goal = training.goal || '';
            trainingMonitorState.sessionId = sessionAtStart;
        }
    } catch (error) {
        console.debug('[session restore] UI state unavailable:', error);
    }

    const ctPath = String(status.ct_path || '').trim();
    if (_activeApiSessionId() !== sessionAtStart) return null;
    if (!ctPath) {
        if (typeof _saveManualState === 'function') {
            _saveManualState({
                ct_loaded: false,
                ctv_segmentation: false,
                oar_segmentation: false,
                trajectory_init: false,
                trajectory_refine: false,
                seed_planning: false,
                dose_calc: false,
                dose_eval: false,
                last_step: null,
            });
            if (typeof _refreshManualStepUI === 'function') _refreshManualStepUI();
        }
        return status;
    }

    await loadCTToViewers(ctPath, { announce: false });
    if (_activeApiSessionId() !== sessionAtStart) return null;

    const storedKeys = new Set(Array.isArray(status.stored_keys) ? status.stored_keys : []);
    if (typeof _saveManualState === 'function') {
        const ctvDone = ['ctv_array', 'ctv_mask'].some(key => storedKeys.has(key));
        const oarDone = storedKeys.has('oar_array');
        const trajectoryInitDone = storedKeys.has('trajectories');
        const trajectoryRefineDone = storedKeys.has('refined_trajectories');
        const seedDone = ['seed_plan', 'seed_plan_serialized', 'seed_positions'].some(key => storedKeys.has(key));
        const doseDone = storedKeys.has('dose_distribution_gy');
        const evaluationDone = storedKeys.has('dose_metrics');
        const completed = [
            ['dose_eval', evaluationDone],
            ['dose_calc', doseDone],
            ['seed_planning', seedDone],
            ['trajectory_refine', trajectoryRefineDone],
            ['trajectory_init', trajectoryInitDone],
            ['oar_segmentation', oarDone],
            ['ctv_segmentation', ctvDone],
        ].find(([, done]) => done);
        _saveManualState({
            ct_loaded: true,
            ctv_segmentation: ctvDone,
            oar_segmentation: oarDone,
            trajectory_init: trajectoryInitDone,
            trajectory_refine: trajectoryRefineDone,
            seed_planning: seedDone,
            dose_calc: doseDone,
            dose_eval: evaluationDone,
            last_step: completed ? completed[0] : null,
        });
        if (typeof _refreshManualStepUI === 'function') _refreshManualStepUI();
    }
    const hasPlanning = [
        'dose_metrics', 'dose_distribution', 'dose_distribution_gy',
        'seed_plan', 'seed_plan_serialized', 'manual_planning_preview',
    ].some(key => storedKeys.has(key));
    if (hasPlanning && typeof refreshPlanningUI === 'function') {
        await refreshPlanningUI({ switchToViewers: false });
    } else if (typeof loadLabelVolumes === 'function') {
        await loadLabelVolumes();
        ['axial', 'sagittal', 'coronal'].forEach(axis => {
            try { renderSliceFromVolume(axis, state.slices[axis]); } catch (_) {}
        });
    }
    return status;
}
window.restoreActiveSessionWorkspace = restoreActiveSessionWorkspace;

// Small global helpers used directly by static HTML attributes. Planning,
// export, and reset handlers are implemented in their dedicated modules and
// deliberately have no fallback: a missing module must surface as an error
// instead of displaying a false-success message.
const _staticUiHelpers = {
    insertSlashCommand(cmd) { const i = document.getElementById('chatInput'); if (i) { i.value = cmd; i.focus(); } },
    toggleContextPanel() { const el = document.querySelector('.context-panel'); if (el) el.style.display = (el.style.display === 'none' ? '' : 'none'); },
    toggleHyperparams()  { const el = document.getElementById('hyperparamsSection'); if (el) el.style.display = (el.style.display === 'none' ? '' : 'none'); const t = document.getElementById('hyperparamToggle'); if (t) t.textContent = (el && el.style.display === 'none') ? '▶' : '▼'; },
};
for (const [name, fn] of Object.entries(_staticUiHelpers)) {
    if (typeof window[name] !== 'function') window[name] = fn;
}

/******** INIT ********/
async function init() {
    try { instrumentUIControls(); } catch (e) { console.warn('instrumentUIControls failed:', e); }

    // --- PRIORITY 0: Restore chat history IMMEDIATELY (no await) ---
    // Sessions live in localStorage; rendering them must NOT be blocked
    // by any server round-trip.  Previously, loadSessions() was called
    // AFTER three sequential await fetch() calls (/status, /planning/clear,
    // /config), which meant the user saw a blank chat area for 1-3s on
    // every page refresh.
    try {
        if (typeof loadSessions === 'function') loadSessions();
        if (typeof renderSessionList === 'function') renderSessionList();
        if (typeof loadSessionChat === 'function' && activeSessionId) {
            loadSessionChat(activeSessionId);
        }
    } catch (e) { console.warn('Session init failed:', e); }

    // --- PRIORITY 1: Server init — run /status, /planning/clear, /config
    // in parallel instead of sequentially.  The /status response is needed
    // by downstream UI, so we await it; /planning/clear and /config are
    // fire-and-forget.
    let _statusData = null;
    const _statusPromise = fetch(API + '/status').then(async resp => {
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        _statusData = data;
        state.brainAvailable = data.brain_available;
        state.sessionId = data.session_id || 'web';
        document.getElementById('brainDot').className = 'dot ' + (data.brain_available ? 'green' : 'yellow');
        document.getElementById('brainStatusText').textContent = data.brain_available ? _t('在线', 'Online') : _t('离线', 'Offline');
        document.getElementById('sessionDisplay').textContent = state.sessionId;
    }).catch(e => {
        document.getElementById('serverDot').className = 'dot red';
        document.getElementById('serverStatus').textContent = _t('已断开', 'Offline');
    });

    // Fire-and-forget: load config defaults
    loadDefaultParams().catch(e => console.warn('loadDefaultParams failed:', e));

    // Wait for /status (needed by UI below); clear/config run in background.
    await _statusPromise;

    // Clear frontend state (runs once per page load)
    if (!window._stateCleared) {
        window._stateCleared = true;
        state.seeds = [];
        state.dvhData = null;
        state.metrics = {};
        state.plan3D = null;
        state.mesh3D = null;
        window._pipelineShown = false;
        window._pipelineBlock = null;
    }
    if (window._pipelineKeeper) { clearInterval(window._pipelineKeeper); window._pipelineKeeper = null; }
    const oldBox = document.getElementById('pipeline_box');
    if (oldBox) oldBox.remove();
    // pipelineState may not be declared in some boot paths — guard
    // so a single missing global doesn't abort init() before the
    // splitters are installed.
    if (typeof pipelineState === 'undefined') {
        window.pipelineState = { steps: [], containerId: null };
    }
    pipelineState.steps = [];
    pipelineState.containerId = null;
    imageAnalysisData.ct = null;
    imageAnalysisData.ctv = null;
    imageAnalysisData.oar = null;
    // Clear data tree planning state
    dataTreeState.planning.seeds = [];
    dataTreeState.planning.needles = [];
    dataTreeState.planning.doseLevels = [];
    dataTreeState.planning.meshes = [];
    dataTreeState.seeds.loaded = false;
    dataTreeState.needles.loaded = false;
    // Clear CTV/OAR state — on refresh, no images are loaded in
    // the frontend even if the server has them in memory. The data
    // tree should start clean until the user loads data again.
    dataTreeState.ctv.loaded = false;
    dataTreeState.ctv.visible = true;
    dataTreeState.oar.loaded = false;
    dataTreeState.oar.visible = true;
    dataTreeState.organs = [];
    state.ctLoaded = false;
    state.doseOverlay = null;
    volumeData = null;
    volumeShape = null;
    // Clear 3D meshes
    if (scene3D && scene3D.meshes) {
        Object.keys(scene3D.meshes).forEach(id => {
            const mesh = scene3D.meshes[id];
            if (mesh && mesh.parent) mesh.parent.remove(mesh);
            if (mesh && mesh.geometry) mesh.geometry.dispose();
            if (mesh && mesh.material) mesh.material.dispose();
        });
        scene3D.meshes = {};
    }
    // Clear dose overlay ONLY if CT is not loaded (new session / CT changed).
    // Previously this ran on EVERY updateImageAnalysis() call, which destroyed
    // the dose overlay that refreshPlanningUI() had just loaded — causing the
    // "dose map doesn't update on slice drag" bug.
    if (!state.ctLoaded) {
        state.doseOverlay = null;
        Object.keys(_doseContourCache).forEach(key => delete _doseContourCache[key]);
        // Clear 2D viewer canvases and dose overlay canvases
        ['axial', 'sagittal', 'coronal'].forEach(axis => {
            const canvas = document.getElementById('sliceCanvas' + capitalize(axis));
            if (canvas) {
                const ctx = canvas.getContext('2d');
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                canvas.style.display = 'none';
            }
            const doseCanvas = document.getElementById('doseOverlayCanvas' + capitalize(axis));
            if (doseCanvas) { doseCanvas.remove(); }
            const contourCanvas = document.getElementById('contourCanvas' + capitalize(axis));
            if (contourCanvas) { contourCanvas.remove(); }
        });
    }
    // Show "No CT data" placeholders ONLY when CT is not loaded.
    // Previously this ran on EVERY updateImageAnalysis() call, which
    // re-showed placeholders over the already-rendered CT slices.
    if (!state.ctLoaded) {
        document.querySelectorAll('.viewer-no-data').forEach(el => { el.style.display = ''; });
    }
    // Update UI
    updateSeeds([]);
    updateMetrics({});
    updateOARTable({});
    updateImageAnalysis();
    renderDataTree();
    // Hide colorbars (all 3 viewers)
    document.querySelectorAll('.dose-colorbar').forEach(el => { el.style.display = 'none'; });
    // BUG FIX 2026-06-17: removed auto-load of CT from server on
    // page refresh. The server keeps CT in memory, and the old code
    // re-fetched it on every refresh — so the viewer was never
    // "clean" after a browser refresh. The user must explicitly load
    // CT via the chat or file upload for each new session.
    // Load default hyperparameters from config
    await loadDefaultParams();

    try {
        await restoreActiveSessionWorkspace({ status: _statusData, clearReport: true });
    } catch (error) {
        console.warn('Active session workspace restore failed:', error);
        clearClientWorkspace({ clearReport: true });
    }
    syncUIBridgeState('init').catch(e => console.warn('Initial UI state sync failed:', e));

    // Apply default viewer layout (vertical = 4 rows in 1 column)
    setViewerLayout(state.viewerSettings.layout || 'vertical');

    // Install the drag-resize splitters. These were previously defined
    // but never called — the user reported that the chat/right-panel
    // divider and the session-sidebar resize handle had become
    // non-functional. Both are bound to the global mousemove so they
    // work even if the user drags fast and releases outside the
    // handle. They run once on init and never need to re-bind.
    try { setupSplitter(); } catch (e) { console.warn('setupSplitter failed:', e); }
    try { setupSidebarResize(); } catch (e) { console.warn('setupSidebarResize failed:', e); }
    try { setupChatAreaResize(); } catch (e) { console.warn('setupChatAreaResize failed:', e); }
    try { setupMetricsResize(); } catch (e) { console.warn('setupMetricsResize failed:', e); }

    // Wire the manual Step-by-Step section (2026-06-15): the buttons
    // re-evaluate their enable/disable state when the CT path input
    // changes, and once on init so the section reflects the current
    // pipeline state. Also runs after a short delay to catch the
    // case where the CT is auto-loaded from server status.
    try { _wireManualStepInputs(); } catch (e) { console.warn('wireManualStepInputs failed:', e); }

    // Cache-bust diagnostic: a long history of splitter/cursor fixes
    // failed silently because the user's browser was serving a cached
    // version of this HTML. We now check TWO fingerprints:
    //   (1) the CDN-vs-local script src (was the original signal),
    //   (2) the data-splitter-version attribute on the 3 main
    //       splitters (added in commit d305d36 as a hard marker for
    //       "this HTML includes the cursor-leak fix").
    // Either mismatch → show a top-of-screen banner asking the user
    // to hard-refresh. The banner auto-dismisses after 30s so it
    // doesn't block the UI in case the user can't refresh.
    try {
        let stale = false;
        let reason = '';
        const probe = document.querySelector('script[src*="plotly"]');
        if (probe && probe.getAttribute('src') && probe.getAttribute('src').startsWith('https://')) {
            stale = true;
            reason = 'still references CDN';
        } else {
            // Check splitter version fingerprint. If the splitters
            // don't have the marker attribute, the page is older
            // than the cursor-leak fix.
            const vs = document.querySelector('#vSplitter');
            const expectedVer = 'v3-2026-06-15';
            if (vs && vs.getAttribute('data-splitter-version') !== expectedVer) {
                stale = true;
                reason = 'is missing the splitter-version marker (pre-cursor-leak-fix)';
            }
        }
        if (stale) {
            const banner = document.createElement('div');
            banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:#dc2626;color:white;padding:12px 20px;font-size:14px;text-align:center;font-family:system-ui;box-shadow:0 2px 8px rgba(0,0,0,0.2);';
            banner.innerHTML = '⚠️ 您的浏览器加载了 <b>旧版</b> BrachyBot 页面（' + reason + '）。请按 <kbd style="background:#fff;color:#dc2626;padding:2px 6px;border-radius:3px;font-family:monospace;">Ctrl+Shift+R</kbd>（Mac: <kbd style="background:#fff;color:#dc2626;padding:2px 6px;border-radius:3px;font-family:monospace;">Cmd+Shift+R</kbd>）强刷。';
            document.body.appendChild(banner);
            setTimeout(() => { try { banner.remove(); } catch (_) {} }, 30000);
        }
    } catch (_) { /* best-effort diagnostic */ }

    // The selected session workspace has already been restored above. New
    // sessions remain empty; existing sessions recover their case state.
}

// Load default hyperparameters from server config and populate UI
async function loadDefaultParams() {
    try {
        const res = await fetch(API + '/config');
        if (!res.ok) return;
        const data = await res.json();
        if (!data.success || !data.defaults) return;

        const d = data.defaults;
        const setVal = (id, val) => {
            const el = document.getElementById(id);
            if (el && val !== undefined && val !== null) el.value = val;
        };

        // Seed info
        if (d.seed_info) {
            setVal('seedRadius', d.seed_info.radius);
            setVal('seedLength', d.seed_info.length);
            setVal('seedMarginRate', d.seed_info.margin_rate);
            if (d.seed_info.num_of_seeds && d.seed_info.num_of_seeds.length >= 2) {
                setVal('seedCountMin', d.seed_info.num_of_seeds[0]);
                setVal('seedCountMax', d.seed_info.num_of_seeds[1]);
            }
            setVal('seedAvgDose', d.seed_info.seed_avr_dose);
        }

        // Radiation array params
        if (d.radiation_array_params) {
            const r = d.radiation_array_params;
            setVal('targetValue', r.target_value);
            setVal('obstacleValue', r.obstacle_value);
            setVal('backgroundValue', r.background_value);
            setVal('backlitAngle', r.backlit_angle);
            setVal('maxCandiTraj', r.maximum_candidate_trajectories);
            if (r.infer_img_size && r.infer_img_size.length >= 3) {
                setVal('inferSizeX', r.infer_img_size[0]);
                setVal('inferSizeY', r.infer_img_size[1]);
                setVal('inferSizeZ', r.infer_img_size[2]);
            }
        }

        // Planning params
        if (d.planning) {
            const p = d.planning;
            setVal('inLowestEnergy', p.in_lowest_energy);
            setVal('outHighestEnergy', p.out_highest_energy);
            setVal('dvhRate', p.DVH_rate);
            setVal('maxIter', p.max_iter);
            setVal('iterRate', p.iter_rate);
            setVal('replanRate', p.replan_rate);
            if (p.direc_resolution && p.direc_resolution.length >= 3) {
                setVal('direcResCone', p.direc_resolution[0]);
                setVal('direcResStep', p.direc_resolution[1]);
                setVal('direcResRings', p.direc_resolution[2]);
            }
        }

        // Distance filter
        if (d.distance_filter) {
            const df = d.distance_filter;
            setVal('distLowerBound', df.lower_bound);
            setVal('distUpperBound', df.upper_bound);
            setVal('distRate', df.distance_rate);
            setVal('intervalRate', df.interval_rate);
        }

        // DL params
        if (d.dl_params) {
            const dl = d.dl_params;
            setVal('dlLR', dl.lr);
            setVal('dlLRDecay', dl.lr_decay);
            setVal('dlEpochs', dl.epochs);
            setVal('dlPatience', dl.patience);
            setVal('dlSearchRegion', dl.search_region);
            setVal('dlDVHMargin', dl.DVH_margin);
        }

        // RF params
        if (d.rf_params) {
            const rf = d.rf_params;
            setVal('rfMaxEpisodes', rf.max_episodes);
            setVal('rfBandwidth', rf.bandwidth);
        }

        uiDebugLog('Default parameters loaded from config');
    } catch (e) {
        console.error('Failed to load default params:', e);
    }
}

/******** VIEWER FULLSCREEN & RESIZE ********/
function toggleViewerFullscreen(view) {
    const card = document.getElementById('viewer' + capitalize(view));
    if (!card) return;
    const panel = document.getElementById('viewersPanel');

    if (card.classList.contains('fullscreen')) {
        // Restore
        card.classList.remove('fullscreen');
        card.querySelector('.viewer-card-expand-btn').innerHTML = '&#9974;';
        // Show all direct children of panel and viewers-rows
        Array.from(panel.children).forEach(c => { c.style.display = ''; });
        panel.querySelectorAll('.viewers-row').forEach(row => {
            row.style.display = '';
            Array.from(row.children).forEach(c => { c.style.display = ''; });
        });
        // Reset card inline styles
        card.style.position = ''; card.style.top = ''; card.style.left = '';
        card.style.right = ''; card.style.bottom = ''; card.style.zIndex = '';
        card.style.width = ''; card.style.height = ''; card.style.flex = '';
        setTimeout(() => {
            ['axial', 'sagittal', 'coronal'].forEach(axis => {
                resizeCanvas(axis);
                const slider = document.getElementById('slider' + capitalize(axis));
                if (slider && state.ctLoaded) updateSlice(axis, slider.value);
            });
        }, 100);
    } else {
        // Enter fullscreen
        card.classList.add('fullscreen');
        card.querySelector('.viewer-card-expand-btn').innerHTML = '&#10006;';
        // Hide all siblings (handles both flat and .viewers-row layouts)
        Array.from(panel.children).forEach(c => {
            if (c !== card && !c.contains(card)) c.style.display = 'none';
        });
        panel.querySelectorAll('.viewers-row').forEach(row => {
            if (row.contains(card)) {
                // This row has the fullscreen card — hide sibling cards in this row
                Array.from(row.children).forEach(c => {
                    if (c !== card) c.style.display = 'none';
                });
            } else {
                row.style.display = 'none';
            }
        });
        setTimeout(() => {
            const axis = card.id.replace('viewer', '').toLowerCase();
            resizeCanvas(axis);
            if (axis !== '3d') {
                const slider = document.getElementById('slider' + capitalize(axis));
                if (slider && state.ctLoaded) updateSlice(axis, slider.value);
            }
        }, 100);
    }
}

/******** VIEWER RESIZE — free stretching with scroll overflow ********/
function setupViewerResizers() {
    document.querySelectorAll('.viewer-resize-h').forEach(handle => {
        let resizing = false;
        let startY = 0;
        let startH = 0;
        let card = null;
        let siblings = [];

        handle.addEventListener('mousedown', e => {
            const view = handle.dataset.view;
            card = document.getElementById('viewer' + capitalize(view));
            if (!card || card.classList.contains('fullscreen')) return;
            resizing = true;
            startY = e.clientY;
            startH = card.offsetHeight;
            // Get all sibling viewer-cards in the same parent
            const parent = card.parentElement;
            siblings = Array.from(parent.querySelectorAll(':scope > .viewer-card'));
            document.body.style.cursor = 'row-resize';
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });

        document.addEventListener('mousemove', e => {
            if (!resizing || !card) return;
            const dy = e.clientY - startY;
            const newH = Math.max(150, startH + dy);
            // Apply same height to all siblings in the row
            siblings.forEach(s => {
                s.style.flex = 'none';
                s.style.height = newH + 'px';
            });
            // Trigger canvas resize for all siblings
            siblings.forEach(s => {
                const axis = s.id.replace('viewer', '').toLowerCase();
                if (axis !== '3d') requestAnimationFrame(() => resizeCanvas(axis));
            });
        });

        document.addEventListener('mouseup', () => {
            if (resizing) {
                resizing = false;
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
            }
        });
    });
}

/******** DRAGGABLE SPLITTER ********/
function setupSplitter() {
    const splitter = document.getElementById('vSplitter');
    const sidebar = document.querySelector('.session-sidebar');
    const rightPanel = document.querySelector('.right-panel');
    if (!splitter || !rightPanel) return;
    let dragging = false;
    let activePointerId = null;
    let lastWidth = rightPanel.offsetWidth;

    // CRITICAL DESIGN NOTE (4th fix attempt):
    //
    // The previous version bound pointermove to the SPLITTER
    // element itself. The splitter is only 5px wide. The user's
    // cursor is essentially guaranteed to leave the 5px area
    // within a few pixels of drag movement — and the moment it
    // does, the pointermove event stops firing on the splitter.
    // setPointerCapture is supposed to fix this, but the
    // capture is fragile: it can fail silently if the click
    // actually landed on a child element (e.g. the visible
    // 3px ::after pseudo), if the element has been detached /
    // re-attached since pointerdown, or if the browser's
    // pointer-capture policy rejects it (e.g. cross-iframe,
    // different document, etc).
    //
    // The robust fix is to bind pointermove and pointerup to
    // the DOCUMENT, not the splitter. Document-level events
    // fire no matter where the cursor goes on the page, so the
    // drag tracks even if the user drags the cursor into a
    // child element, off the window, or onto a totally
    // different element. We still need pointerdown on the
    // splitter to detect WHEN the drag starts; everything else
    // is on document.
    // Use BOTH pointer and mouse events for maximum compatibility.
    // Some browsers/configurations don't fire pointermove reliably
    // when setPointerCapture fails (e.g. cross-origin iframes,
    // certain Linux WMs). mousedown/mousemove always works for mouse.
    const _startDrag = (e) => {
        if (e.button !== 0) return;  // left click only
        dragging = true;
        activePointerId = e.pointerId || null;
        lastWidth = rightPanel.offsetWidth;
        document.body.classList.add('v-dragging');
        splitter.classList.add('dragging');
        try { if (e.pointerId !== undefined) splitter.setPointerCapture(e.pointerId); } catch (_) {}
        e.preventDefault();
        e.stopPropagation();
    };
    splitter.addEventListener('pointerdown', _startDrag);
    splitter.addEventListener('mousedown', _startDrag);
    const _onPointerMove = (e) => {
        if (!dragging) return;
        // If we know which pointer started the drag, ignore
        // other pointers' moves (e.g. touch + pen simultaneously).
        if (activePointerId !== null && e.pointerId !== undefined && e.pointerId !== activePointerId) return;
        const container = document.querySelector('.app-body');
        if (!container) return;
        const containerRect = container.getBoundingClientRect();
        const newWidth = containerRect.right - e.clientX;
        if (newWidth >= 50 && newWidth <= containerRect.width - 100) {
            rightPanel.style.width = newWidth + 'px';
            // Force flex recalculation on viewers-panel so the 2D
            // canvases re-measure against the new panel width.
            const panel = document.getElementById('viewersPanel');
            if (panel) {
                panel.style.display = 'none';
                panel.offsetHeight; // force reflow
                panel.style.display = '';
            }
            ['axial', 'sagittal', 'coronal'].forEach(axis => {
                requestAnimationFrame(() => resizeCanvas(axis));
            });
            try { localStorage.setItem('layout.right.width', String(Math.round(newWidth))); } catch (_) {}
        }
    };
    document.addEventListener('pointermove', _onPointerMove);
    document.addEventListener('mousemove', _onPointerMove);
    const _endDrag = (e) => {
        if (!dragging) return;
        if (activePointerId !== null && e && e.pointerId !== undefined && e.pointerId !== activePointerId) return;
        dragging = false;
        activePointerId = null;
        document.body.classList.remove('v-dragging');
        splitter.classList.remove('dragging');
        try { if (e && e.pointerId !== undefined) splitter.releasePointerCapture(e.pointerId); } catch (_) {}
    };
    // Listen on BOTH the splitter and document. Splitter catches
    // pointerup that ends ON the splitter; document catches
    // pointerup that ends ELSEWHERE on the page. Together they
    // guarantee the drag always ends cleanly.
    splitter.addEventListener('pointerup', _endDrag);
    splitter.addEventListener('pointercancel', _endDrag);
    document.addEventListener('pointerup', _endDrag);
    document.addEventListener('pointercancel', _endDrag);
    document.addEventListener('mouseup', _endDrag);

    // Restore previously-saved right-panel width on page load
    try {
        const saved = localStorage.getItem('layout.right.width');
        if (saved) {
            const w = parseInt(saved, 10);
            if (w >= 50 && w <= 4000) rightPanel.style.width = w + 'px';
        }
    } catch (_) {}
}

function setupSidebarResize() {
    const handle = document.getElementById('sidebarResizeHandle');
    const sidebar = document.getElementById('sessionSidebar');
    if (!handle || !sidebar) return;

    let dragging = false;
    let startX = 0;
    let startWidth = 0;

    // Use Pointer Events for reliability across mouse / trackpad /
    // touch. The user reported the drag does nothing — switching
    // from mouse events to pointer events makes the handler robust
    // to the other resize-handle that overlaps this handle's hit
    // area (the chat-area-resize-handle sits at the same 3px
    // boundary; pointer events fire on the deepest hit target so
    // whichever handle the user actually grabbed wins cleanly).
    //
    // Round 4 fix: pointermove and pointerup are on DOCUMENT
    // (not the handle itself). The handle is only 6px wide and
    // the cursor will leave it within the first few pixels of
    // any drag. setPointerCapture is fragile and can fail
    // silently — so we don't depend on it. Document-level
    // pointermove fires no matter where the cursor goes.
    handle.addEventListener('pointerdown', (e) => {
        if (e.button !== 0) return;
        dragging = true;
        startX = e.clientX;
        startWidth = sidebar.offsetWidth;
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        handle.classList.add('dragging');
        try { handle.setPointerCapture(e.pointerId); } catch (_) {}
        e.preventDefault();
        e.stopPropagation();
    });

    const _onPointerMove = (e) => {
        if (!dragging) return;
        const newWidth = startWidth + (e.clientX - startX);
        if (newWidth >= 180 && newWidth <= 500) {
            sidebar.style.width = newWidth + 'px';
            try { localStorage.setItem('layout.sidebar.width', String(Math.round(newWidth))); } catch (_) {}
        }
    };
    document.addEventListener('pointermove', _onPointerMove);

    const _endDrag = (e) => {
        if (!dragging) return;
        dragging = false;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        handle.classList.remove('dragging');
        try { if (e && e.pointerId !== undefined) handle.releasePointerCapture(e.pointerId); } catch (_) {}
    };
    handle.addEventListener('pointerup', _endDrag);
    handle.addEventListener('pointercancel', _endDrag);
    document.addEventListener('pointerup', _endDrag);
    document.addEventListener('pointercancel', _endDrag);

    // Restore previously-saved width
    try {
        const saved = localStorage.getItem('layout.sidebar.width');
        if (saved) sidebar.style.width = saved + 'px';
    } catch (_) {}
}

// Drag-resize for the chat column (the middle column, between the
// session sidebar and the right panel). The handle is the thin
// vertical bar on the LEFT edge of #chatArea. Dragging it changes
// the chat column's width — by SHRINKING the sidebar (since the
// chat column itself has flex: 1, the natural way to resize the
// middle column is to consume space from the sidebar on the left).
// We persist the resulting width to localStorage so it survives
// page reloads.
function setupChatAreaResize() {
    const handle = document.getElementById('chatAreaResizeHandle');
    const chatArea = document.getElementById('chatArea');
    const sidebar = document.getElementById('sessionSidebar');
    if (!handle || !chatArea || !sidebar) return;

    let dragging = false;
    let startX = 0;
    let startChatWidth = 0;
    let startSidebarWidth = 0;

    // Pointer Events for the same reasons as setupSplitter /
    // setupSidebarResize. The chat-area-resize-handle sits at the
    // SAME 3px boundary as the sidebar-resize-handle (the chat
    // handle is `left: -3px` of the chat-area; the sidebar handle
    // is `right: -3px` of the sidebar). The two handles' hit
    // targets overlap, but pointer events fire on the deepest hit
    // target — whichever handle the user actually grabbed wins
    // cleanly. The user reported that the older mouse-event
    // version "does nothing" — switching to pointer events also
    // makes the drag work even if the user starts moving the
    // cursor over a different element after grabbing the handle.
    handle.addEventListener('pointerdown', (e) => {
        if (e.button !== 0) return;
        dragging = true;
        startX = e.clientX;
        startChatWidth = chatArea.getBoundingClientRect().width;
        startSidebarWidth = sidebar.offsetWidth;
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        handle.classList.add('dragging');
        try { handle.setPointerCapture(e.pointerId); } catch (_) {}
        e.preventDefault();
        e.stopPropagation();
    });

    const _onPointerMove = (e) => {
        if (!dragging) return;
        const dx = e.clientX - startX;
        const newSidebarWidth = startSidebarWidth - dx;
        if (newSidebarWidth >= 180 && newSidebarWidth <= 500) {
            sidebar.style.width = newSidebarWidth + 'px';
            try { localStorage.setItem('layout.sidebar.width', String(Math.round(newSidebarWidth))); } catch (_) {}
        }
    };
    document.addEventListener('pointermove', _onPointerMove);

    const _endDrag = (e) => {
        if (!dragging) return;
        dragging = false;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        handle.classList.remove('dragging');
        try { if (e && e.pointerId !== undefined) handle.releasePointerCapture(e.pointerId); } catch (_) {}
    };
    handle.addEventListener('pointerup', _endDrag);
    handle.addEventListener('pointercancel', _endDrag);
    document.addEventListener('pointerup', _endDrag);
    document.addEventListener('pointercancel', _endDrag);
}

/******** METRICS SECTION RESIZE ********
   Vertical drag handle between the DVH chart and the OAR metrics
   table. Persists heights to localStorage. Each handle's data-target
   attribute points at the section whose height it controls.
   =========================================================== */
function setupMetricsResize() {
    const handles = document.querySelectorAll('.metrics-resize-handle');
    if (!handles.length) return;

    let dragging = null;

    handles.forEach(handle => {
        const targetId = handle.dataset.target;
        const minH = parseInt(handle.dataset.min || '120', 10);
        const maxH = parseInt(handle.dataset.max || '900', 10);
        const storageKey = `metrics.height.${targetId}`;

        // Restore previously saved height
        try {
            const saved = localStorage.getItem(storageKey);
            if (saved) {
                const target = document.getElementById(targetId);
                if (target) {
                    // Apply the user's saved height on top of the CSS
                    // default. Don't set `flex: none` — the metrics-panel
                    // is no longer a flex container (it's now `display:
                    // block` so all sections stack naturally and the
                    // outer scrollbar handles overflow). The user's
                    // dragged height is preserved verbatim.
                    target.style.height = saved + 'px';
                    target.style.minHeight = saved + 'px';
                }
            }
        } catch (e) { /* localStorage may be disabled */ }

        handle.addEventListener('mousedown', (e) => {
            const target = document.getElementById(targetId);
            if (!target) return;
            dragging = {
                handle, target,
                startY: e.clientY,
                startH: target.getBoundingClientRect().height,
                minH, maxH,
                storageKey,
            };
            handle.classList.add('dragging');
            document.body.style.cursor = 'ns-resize';
            document.body.style.userSelect = 'none';
            e.preventDefault();
            e.stopPropagation();
        });
    });

    document.addEventListener('mousemove', (e) => {
        if (!dragging) return;
        const dy = e.clientY - dragging.startY;
        let newH = dragging.startH + dy;
        newH = Math.max(dragging.minH, Math.min(dragging.maxH, newH));
        // Set BOTH height and min-height so the change sticks even when
        // the user tries to shrink below the CSS default. Sections are
        // independent block children now, so this only affects the
        // dragged section — siblings are untouched. We deliberately
        // do NOT touch `flex` here: the metrics-panel is now a normal
        // block container (display: block), so `flex: none` would be
        // a no-op at best and an override at worst.
        dragging.target.style.height = newH + 'px';
        dragging.target.style.minHeight = newH + 'px';
    });

    document.addEventListener('mouseup', () => {
        if (!dragging) return;
        // Persist
        try {
            const finalH = dragging.target.getBoundingClientRect().height;
            localStorage.setItem(dragging.storageKey, Math.round(finalH));
        } catch (e) { /* ignore */ }
        dragging.handle.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        // Ask Plotly to re-fit since DVH container changed size
        const dvhEl = document.getElementById('dvhChart');
        if (dvhEl && window.Plotly) {
            try { Plotly.Plots.resize(dvhEl); } catch (e) {}
        }
        dragging = null;
    });
}

// ============================================================
// UI Controller action executor
// ============================================================
// Confirmation dialog for destructive operations (i18n-aware)
function _confirmAction(msgZh, msgEn) {
    return new Promise(resolve => {
        const t = window._t || ((zh) => zh);
        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:10000;display:flex;align-items:center;justify-content:center;';
        overlay.innerHTML = `
            <div style="background:var(--bg-2);border:1px solid var(--border);border-radius:14px;padding:24px 28px;max-width:380px;width:88%;text-align:center;box-shadow:var(--shadow-xl);">
                <div style="width:44px;height:44px;border-radius:50%;background:var(--danger-soft);display:flex;align-items:center;justify-content:center;margin:0 auto 14px;font-size:1.3rem;line-height:1;">⚠️</div>
                <div style="font-size:0.88rem;font-weight:550;color:var(--text);margin-bottom:4px;">${t('确认操作', 'Confirm')}</div>
                <div style="font-size:0.78rem;color:var(--text-secondary);line-height:1.5;margin-bottom:20px;padding:0 2px;">${escHtml(t(msgZh, msgEn || msgZh))}</div>
                <div style="display:flex;gap:10px;justify-content:center;">
                    <button id="_confirmYes" style="min-width:80px;padding:7px 18px;border-radius:8px;border:none;font-size:0.8rem;font-weight:500;cursor:pointer;background:var(--danger);color:#fff;">${t('确认', 'Yes')}</button>
                    <button id="_confirmNo" style="min-width:80px;padding:7px 18px;border-radius:8px;border:1px solid var(--border);background:transparent;font-size:0.8rem;font-weight:500;cursor:pointer;color:var(--text);">${t('取消', 'Cancel')}</button>
                </div>
            </div>`;
        document.body.appendChild(overlay);
        overlay.querySelector('#_confirmYes').onclick = () => { overlay.remove(); resolve(true); };
        overlay.querySelector('#_confirmNo').onclick = () => { overlay.remove(); resolve(false); };
        overlay.onclick = (e) => { if (e.target === overlay) { overlay.remove(); resolve(false); } };
    });
}

function _executeUIAction(a) {
    const { target, command, value, requires_confirm } = a;
    if (requires_confirm) {
        const pairs = {
            'session.delete': [`确定要删除会话 ${value} 吗？此操作不可撤销。`, `Delete session ${value}? This cannot be undone.`],
            'session.clear_all': ['确定要清空所有会话和本地数据吗？此操作不可撤销。', 'Clear all sessions and local data? This cannot be undone.'],
            'plan.reset': ['确定要重置当前规划会话吗？所有规划数据将被清除。', 'Reset the current planning session? All data will be cleared.'],
            'report.clear': ['确定要清空报告数据吗？', 'Clear the report data?'],
            'chat.clear_history': ['确定要清空当前聊天记录吗？', 'Clear the current chat history?'],
        };
        const p = pairs[target] || [`确定要执行 ${target} 吗？`, `Execute ${target}?`];
        _confirmAction(p[0], p[1]).then(ok => { if (ok) _executeUIActionRaw(a); });
        return;
    }
    _executeUIActionRaw(a);
}

function _executeUIActionRaw(a) {
    const { target, command, value } = a;
    try {
        if (target === 'ui.control') {
            executeGenericUIControl(command, value);
            return;
        }
        // ── Panel switching ──
        if (target === 'panel' && command === 'switch') {
            const tab = document.querySelector(`.panel-tab[data-panel="${value}"]`)
                     || document.querySelector(`.panel-tab[onclick*="${value}"]`);
            if (tab) switchPanel(value, tab);
            else console.warn('[UIAction] Panel tab not found:', value);
            return;
        }
        // ── Viewer settings ──
        if (target === 'viewer.window') {
            const el = document.getElementById('viewerWindow');
            if (!el) return;
            let v = parseInt(el.value) || 400;
            if (command === 'set') v = parseInt(value) || v;
            else if (command === 'increase') v += parseInt(value) || 50;
            else if (command === 'decrease') v -= parseInt(value) || 50;
            el.value = v; state.viewerSettings.window = v;
            if (state.ctLoaded) loadAllSlices();
            return;
        }
        if (target === 'viewer.level') {
            const el = document.getElementById('viewerLevel');
            if (!el) return;
            let v = parseInt(el.value) || 40;
            if (command === 'set') v = parseInt(value) || v;
            else if (command === 'increase') v += parseInt(value) || 20;
            else if (command === 'decrease') v -= parseInt(value) || 20;
            el.value = v; state.viewerSettings.level = v;
            if (state.ctLoaded) loadAllSlices();
            return;
        }
        if (target === 'viewer.zoom') {
            if (command === 'fit') {
                fitView();
            } else {
                let v = Math.round((state.viewerSettings.zoom || 1) * 100);
                if (command === 'set') v = parseInt(value) || v;
                else if (command === 'increase') v += parseInt(value) || 20;
                else if (command === 'decrease') v -= parseInt(value) || 20;
                applyZoom(Math.max(50, Math.min(300, v)));
            }
            return;
        }
        if (target === 'viewer.threshold') {
            const el = document.getElementById('viewerThreshold');
            if (el) { el.value = value; applyThreshold(); }
            return;
        }
        if (target === 'viewer.fullscreen') {
            toggleViewerFullscreen(value); return;
        }
        if (target === 'viewer.reset') {
            resetViewer(); return;
        }
        if (target === 'viewer.fit_all') {
            fitView(); return;
        }
        if (target === 'viewer.preset') {
            const pp = document.getElementById('windowPreset');
            if (pp) { pp.value = value; applyWindowPreset(); }
            return;
        }
        // ── Overlay controls ──
        if (target === 'overlay.ctv') {
            const cb = document.getElementById('overlayCTV');
            if (cb) { cb.checked = command === 'show' || (command === 'toggle' && !cb.checked); toggleOverlay(); }
            return;
        }
        if (target === 'overlay.oar') {
            const cb = document.getElementById('overlayOAR');
            if (cb) { cb.checked = command === 'show' || (command === 'toggle' && !cb.checked); toggleOverlay(); }
            return;
        }
        if (target === 'overlay.dose.opacity') {
            setDoseOverlayOpacity(value);
            return;
        }
        if (target === 'overlay.ctv.opacity' || target === 'overlay.oar.opacity') {
            const axis = target.includes('ctv') ? 'ctv' : 'oar';
            setGroupOpacity(axis, value);
            return;
        }
        if (target === 'overlay.display_mode') {
            const dm = document.getElementById('displayMode');
            if (dm) { dm.value = value; setDisplayMode(); }
            return;
        }
        // ── Slice navigation ──
        if (target.startsWith('slice.')) {
            const axis = target.split('.')[1];
            const slider = document.getElementById('slider' + capitalize(axis));
            if (!slider) return;
            let v = parseInt(slider.value) || 0;
            const max = parseInt(slider.max) || 0;
            if (command === 'set') v = parseInt(value) || 0;
            else if (command === 'next') v = Math.min(v + 1, max);
            else if (command === 'prev') v = Math.max(v - 1, 0);
            else if (command === 'first') v = 0;
            else if (command === 'last') v = max;
            slider.value = v; updateSlice(axis, v);
            return;
        }
        // ── Layout ──
        if (target === 'layout') {
            setViewerLayout(value);
            return;
        }
        // ── Data tree ──
        if (target === 'data_tree') {
            if (command === 'expand_all') {
                document.querySelectorAll('.tree-group').forEach(g => {
                    g.querySelector(':scope > .tree-group-header > .arrow')?.classList.remove('collapsed');
                    g.querySelector(':scope > .tree-group-items')?.classList.remove('collapsed');
                });
            } else if (command === 'collapse_all') {
                document.querySelectorAll('.tree-group').forEach(g => {
                    g.querySelector(':scope > .tree-group-header > .arrow')?.classList.add('collapsed');
                    g.querySelector(':scope > .tree-group-items')?.classList.add('collapsed');
                });
            } else {
                const group = document.querySelector(`.tree-group[data-group="${value}"]`);
                if (group) {
                    const arrow = group.querySelector(':scope > .tree-group-header > .arrow');
                    const items = group.querySelector(':scope > .tree-group-items');
                    if (command === 'expand') { arrow?.classList.remove('collapsed'); items?.classList.remove('collapsed'); }
                    else if (command === 'collapse') { arrow?.classList.add('collapsed'); items?.classList.add('collapsed'); }
                }
            }
            return;
        }
        if (target === 'tree.visibility') {
            const parts = (value || '').split(',');
            const id = parts[0], vis = parts[1] === 'on';
            if (id) setDataItemVisibility(id, vis);
            return;
        }
        if (target === 'tree.opacity') {
            const parts = (value || '').split(',');
            const id = parts[0], op = parseInt(parts[1]) || 50;
            if (id) setDataOpacity(id, op);
            return;
        }
        if (target === 'tree.reconstruct3d') {
            // Use the same function as right-click → 3D reconstruction
            reconstructOrgan3D(value);
            return;
        }
        if (target === 'tree.group.visibility') {
            const [group, vis] = (value || '').split(',');
            if (group) setGroupVisibility(group, vis === 'show');
            return;
        }
        if (target === 'tree.group.opacity') {
            const [group, op] = (value || '').split(',');
            if (group) setGroupOpacity(group, parseInt(op) || 50);
            return;
        }
        if (target === 'tree.group.reconstruct3d') {
            // Reconstruct all organs in the group using the data tree method
            if (value === 'ctv') {
                reconstructOrgan3D('ctv');
            } else {
                // For OAR groups, reconstruct all organs in the group
                if (dataTreeState && dataTreeState.organs) {
                    const organs = dataTreeState.organs.filter(o => {
                        if (value === 'non_traversable') return o.category === 'non_traversable';
                        if (value === 'traversable') return o.category === 'traversable';
                        return true;
                    });
                    organs.forEach(o => reconstructOrgan3D(o.id, true));
                }
            }
            return;
        }
        if (target === 'tree.dose.visibility') {
            if (state.doseOverlay) {
                state.doseOverlay.visible = value === 'on';
                if (state.ctLoaded) loadAllSlices();
            }
            return;
        }
        if (target === 'tree.trajectories.visibility') {
            setGroupVisibility('planning_needles', value === 'on');
            return;
        }
        if (target === 'tree.seeds.visibility') {
            setGroupVisibility('planning_seeds', value === 'on');
            return;
        }
        if (target === 'tree.needles.visibility') {
            setGroupVisibility('planning_needles', value === 'on');
            return;
        }
        if (target === 'tree.isosurfaces.visibility') {
            setGroupVisibility('dose_isosurfaces', value === 'on');
            return;
        }
        // ── Session management ──
        if (target === 'session.new') { newChat(); return; }
        if (target === 'session.switch') { switchSession(value); return; }
        if (target === 'session.rename') {
            if (activeSessionId && sessions[activeSessionId]) {
                sessions[activeSessionId].title = value;
                saveSessions(); renderSessionList();
            }
            return;
        }
        if (target === 'session.delete') { deleteSession(value, { skipConfirm: true }); return; }
        if (target === 'session.clear_all') { clearLocalChatData({ skipConfirm: true }); return; }
        // ── Planning ──
        if (target === 'plan.run') {
            runPlanning();
            return;
        }
        if (target === 'plan.run_manual_step') {
            const step = String(value || '').trim();
            if (step === 'ctv_segmentation' || step === 'oar_segmentation') {
                runSegmentationStep(step);
            } else if (step) {
                runPlanningStep(step);
            }
            return;
        }
        if (target === 'plan.reset') {
            resetSession();
            return;
        }
        if (target === 'ui.state') {
            syncUIBridgeState(command || 'ui_controller');
            if (typeof addChat === 'function') addChat('system', 'UI state snapshot synced.');
            return;
        }
        if (target === 'training.mode') {
            if (command === 'start') startTrainingMode(value || 'Monitor planning workflow');
            else if (command === 'stop') stopTrainingMode();
            else if (command === 'advice') requestPlanningAdvice();
            else if (typeof addChat === 'function') {
                addChat('system', trainingMonitorState.active ? 'Monitor mode is active.' : 'Monitor mode is not active.');
            }
            return;
        }
        if (target === 'manual.needle.create') {
            addManualNeedle();
            return;
        }
        if (target === 'manual.seed.add') {
            addManualSeed();
            return;
        }
        if (target === 'manual.dose.recompute') {
            recomputeManualDose(value || 'ui_controller');
            return;
        }
        if (target === 'manual.plan.replan') {
            replanManualPlan();
            return;
        }
        if (target === 'manual.plan.finish') {
            requestPlanningAdvice();
            return;
        }
        if (target === 'system.readiness') {
            checkSystemReadiness();
            return;
        }
        // ── Report ──
        if (target === 'report.autofill') {
            if (typeof Report !== 'undefined' && Report.autoFill) Report.autoFill.fromAll();
            else if (typeof reportAutoFill === 'function') reportAutoFill();
            return;
        }
        if (target === 'report.export') {
            if (typeof Report !== 'undefined' && Report.export) {
                const fn = Report.export[value];
                if (fn) fn();
            }
            return;
        }
        if (target === 'report.import') {
            if (typeof Report !== 'undefined' && Report.persist) Report.persist.importJSON();
            return;
        }
        if (target === 'report.snapshot.save') {
            if (typeof Report !== 'undefined' && Report.snapshots) Report.snapshots.save();
            return;
        }
        if (target === 'report.snapshot.open') {
            if (typeof Report !== 'undefined' && Report.snapshots) Report.snapshots.openModal();
            return;
        }
        if (target === 'report.audit.open') {
            if (typeof Report !== 'undefined' && Report.audit) Report.audit.openModal();
            return;
        }
        if (target === 'report.validation.open') {
            if (typeof Report !== 'undefined' && Report.validation) Report.validation.openModal();
            return;
        }
        if (target === 'report.preview.zoom') {
            if (typeof Report !== 'undefined' && Report.preview) {
                if (command === 'reset') Report.preview.zoomReset();
                else if (command === 'set') Report.preview.setZoom(parseInt(value) / 100);
                else if (command === 'increase') Report.preview.zoomIn();
                else if (command === 'decrease') Report.preview.zoomOut();
            }
            return;
        }
        if (target === 'report.layout') {
            if (typeof Report !== 'undefined' && Report.panels) Report.panels.layout2col(value === '2col');
            return;
        }
        if (target === 'report.section.toggle') { toggleReportSection(value); return; }
        if (target === 'report.reference.add') { addReportReferenceFromCatalog(value); return; }
        if (target === 'report.reference.remove') { removeReportReference(parseInt(value)); return; }
        if (target === 'report.clear') {
            if (typeof Report !== 'undefined' && Report.persist) Report.persist.clear();
            return;
        }
        // ── 3D controls ──
        if (target === '3d.reconstruct') {
            // Use the same function as right-click → 3D reconstruction
            reconstructOrgan3D(value);
            return;
        }
        if (target === '3d.wireframe') {
            const on = value === 'on' || (value === undefined);
            const cb = document.getElementById('wireframe3D');
            if (cb) { cb.checked = on; toggle3DWireframe(on); }
            return;
        }
        if (target === '3d.skin') {
            const on = value === 'on' || (value === undefined);
            const cb = document.getElementById('skinToggle3D');
            if (cb) { cb.checked = on; toggle3DSkin(on); }
            return;
        }
        if (target === '3d.dose_opacity') {
            const sl = document.getElementById('doseOpacity');
            if (sl) { sl.value = value; updateDoseOpacity(value); }
            return;
        }
        if (target === '3d.dose_surface') {
            const on = value === 'on' ? true : value === 'off' ? false : !state.doseTexture?.enabled;
            setDoseTextureMode(on);
            return;
        }
        if (target === '3d.fit') { fitCameraToScene(); return; }
        if (target === '3d.reset') {
            if (typeof reset3DView === 'function') reset3DView();
            else fitCameraToScene();
            return;
        }
        if (target === '3d.show_all') {
            showAllOrgans();
            return;
        }
        if (target === '3d.hide_all') {
            setGroupVisibility('ctv', false);
            setGroupVisibility('oar', false);
            setGroupVisibility('planning_seeds', false);
            setGroupVisibility('planning_needles', false);
            setGroupVisibility('dose_isosurfaces', false);
            return;
        }
        // ── Chat ──
        if (target === 'chat.language') { setUiLanguage(value); return; }
        if (target === 'chat.clear_history') {
            clearCurrentChatHistory({ skipConfirm: true });
            return;
        }
        if (target === 'chat.sidebar.toggle') { toggleSessionSidebar(); return; }
        // ── Screenshot ──
        if (target === 'screenshot') {
            _captureScreenshot(value); return;
        }
        // ── Tools ──
        if (target === 'tool') { setViewerTool(value); return; }
    } catch (e) {
        console.warn('[UIAction] Error executing:', target, command, value, e);
    }
}

// Screenshot capture — uses unified target map
async function _captureScreenshot(view) {
    // Normalize legacy short names to full target names
    const ALIAS = { 'axial': 'viewer-axial', 'sagittal': 'viewer-sagittal',
                    'coronal': 'viewer-coronal', '3d': 'viewer-3d', 'dvh': 'dvh',
                    'dose': 'dose-overview', 'dose-overview': 'dose-overview' };
    const target = ALIAS[view] || view;
    const preparedEl = await _prepareScreenshotTarget(target);
    if (target === 'dose-overview' || target === 'dvh') {
        const dataUrl = await _captureScreenshotDataUrl(target, preparedEl);
        if (dataUrl) {
            const link = document.createElement('a');
            link.download = `brachybot_${view}_${Date.now()}.png`;
            link.href = dataUrl;
            link.click();
        }
        return;
    }
    const el = preparedEl;
    if (!el) { console.warn('[screenshot] Target not found:', view); return; }
    if (typeof html2canvas !== 'undefined') {
        const canvas = await html2canvas(el);
        const link = document.createElement('a');
        link.download = `brachybot_${view}_${Date.now()}.png`;
        link.href = canvas.toDataURL();
        link.click();
    } else {
        // Fallback: just capture the 3D canvas
        const canvas = el.querySelector('canvas') || el;
        if (canvas.toDataURL) {
            const link = document.createElement('a');
            link.download = `brachybot_${view}_${Date.now()}.png`;
            link.href = canvas.toDataURL();
            link.click();
        }
    }
}

// ── Unified screenshot target resolver ──
// Single source of truth for ALL screenshot targets. Both
// _interceptScreenshot (SSE-driven) and _captureScreenshot (direct)
// use this to find the DOM element to capture.
const _SCREENSHOT_TARGET_MAP = {
    'viewer-axial':     '#viewerAxial',
    'viewer-sagittal':  '#viewerSagittal',
    'viewer-coronal':   '#viewerCoronal',
    'viewer-3d':        '#canvas3D',
    'data-tree':        '#dataTreeBody',
    'chat':             '#chatMessages',
    'metrics':          '#panelMetrics',
    'dvh':              '#dvhChart',
    'dose-overview':    null,
    'input':            '#panelInput',
    'seeds':            '#panelViewers',      // seeds are inside viewers panel
    'planning':         '#panelInput',        // planning controls are in input panel
    'report':           '#panelReport',
    'overlay-controls': '.viewers-toolbar',
    'full':             null,                 // null → document.body
};
// Panels that must be active for the target to be visible
const _SCREENSHOT_PANEL_MAP = {
    'viewer-axial': 'viewers', 'viewer-sagittal': 'viewers', 'viewer-coronal': 'viewers',
    'viewer-3d': 'viewers', 'data-tree': 'viewers', 'overlay-controls': 'viewers',
    'seeds': 'viewers', 'dose-overview': 'viewers',
    'metrics': 'metrics', 'dvh': 'metrics', 'input': 'input', 'planning': 'input',
    'report': 'report',
};
function _resolveScreenshotTarget(target) {
    const selector = _SCREENSHOT_TARGET_MAP[target];
    let el = null;
    if (selector) el = document.querySelector(selector);
    if (!el && target === 'full') el = document.body;
    // Auto-switch panel if target is hidden
    const panelName = _SCREENSHOT_PANEL_MAP[target];
    const hiddenByInactivePanel = !!(el && target !== 'full' && el.offsetParent === null && panelName);
    if (!el || hiddenByInactivePanel) {
        if (panelName) {
            const tab = document.querySelector(`.panel-tab[data-panel="${panelName}"]`)
                     || document.querySelector(`.panel-tab[onclick*="${panelName}"]`);
            if (tab && !tab.classList.contains('active')) {
                switchPanel(panelName, tab);
            }
            if (selector) el = document.querySelector(selector);
        }
    }
    return el;
}

function _waitScreenshotFrames(n = 2) {
    return new Promise(resolve => {
        let count = 0;
        const tick = () => {
            count += 1;
            if (count >= n) resolve();
            else requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
    });
}

async function _prepareScreenshotTarget(target) {
    const panelName = _SCREENSHOT_PANEL_MAP[target];
    const tab = panelName ? document.querySelector(`.panel-tab[data-panel="${panelName}"]`) : null;
    const switchedPanel = !!(tab && !tab.classList.contains('active'));
    const el = _resolveScreenshotTarget(target);
    if (!el) return null;

    // Panel switches, canvas resizes, Plotly relayouts, and Three.js renders
    // complete on different animation frames. Waiting on frames rather than a
    // fixed timer makes capture deterministic on both fast and slow clients.
    await _waitScreenshotFrames(switchedPanel ? 4 : 2);
    if (target === 'dvh' && typeof _resizeDVHChartSoon === 'function') {
        _resizeDVHChartSoon();
        await _waitScreenshotFrames(3);
    }
    if (target === 'viewer-3d' && typeof scene3D !== 'undefined' && scene3D.requestRender) {
        scene3D.requestRender(2);
        await _waitScreenshotFrames(2);
    }
    return el;
}

function _drawScreenshotColorbar(ctx, x, y, w, h) {
    ctx.save();
    ctx.fillStyle = 'rgba(2,6,23,0.96)';
    ctx.strokeStyle = 'rgba(148,163,184,0.32)';
    ctx.fillRect(x, y, w, h);
    ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
    const barX = x + 12, barY = y + 34, barW = 20, barH = h - 68;
    const gradCanvas = document.createElement('canvas');
    gradCanvas.width = barW;
    gradCanvas.height = barH;
    _drawDoseColorbarGradient(gradCanvas.getContext('2d'), barW, barH);
    ctx.drawImage(gradCanvas, barX, barY);
    ctx.strokeStyle = 'rgba(226,232,240,0.7)';
    ctx.strokeRect(barX + 0.5, barY + 0.5, barW - 1, barH - 1);
    ctx.fillStyle = '#e2e8f0';
    ctx.font = 'bold 12px Inter, system-ui, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText('Dose (Gy)', x + 8, y + 20);
    _doseColorbarLabelSpecs(barH).forEach(spec => {
        const ty = barY + (barH - 1) * (spec.pct / 100);
        ctx.beginPath();
        ctx.moveTo(barX + barW + 3, ty);
        ctx.lineTo(barX + barW + 8, ty);
        ctx.stroke();
        ctx.font = `${spec.major ? 'bold ' : ''}9px Inter, system-ui, sans-serif`;
        ctx.fillStyle = '#cbd5e1';
        ctx.fillText(spec.label, barX + barW + 12, ty + 3);
    });
    ctx.restore();
}

async function _captureDoseOverviewDataUrl() {
    const panelTab = document.querySelector('.panel-tab[data-panel="viewers"]');
    if (panelTab && !panelTab.classList.contains('active')) switchPanel('viewers', panelTab);
    const origSlices = {
        axial: state.slices?.axial || 0,
        sagittal: state.slices?.sagittal || 0,
        coronal: state.slices?.coronal || 0,
    };
    let origVisible = null;
    let origOpacity = null;
    if (state.doseOverlay) {
        origVisible = state.doseOverlay.visible;
        origOpacity = state.doseOverlay.opacity;
        state.doseOverlay.visible = true;
        if (typeof state.doseOverlay.opacity === 'number' && state.doseOverlay.opacity < 0.55) {
            state.doseOverlay.opacity = 0.7;
        }
        updateDoseColorbars(true, state.doseOverlay.doseMin, state.doseOverlay.doseMax);
    }
    const pv = state.doseOverlay && state.doseOverlay.peakVoxel;
    const restore = () => {
        if (pv) {
            Object.entries(origSlices).forEach(([ax, sl]) => {
                const name = ax.charAt(0).toUpperCase() + ax.slice(1);
                const slider = document.getElementById('slider' + name);
                if (slider) slider.value = sl;
                updateSlice(ax, sl);
            });
        }
        if (state.doseOverlay && origVisible !== null) {
            state.doseOverlay.visible = origVisible;
            state.doseOverlay.opacity = origOpacity;
            updateDoseColorbars(state.doseOverlay.visible, state.doseOverlay.doseMin, state.doseOverlay.doseMax);
        }
    };

    try {
        if (pv) {
            [
                { ax: 'axial', slice: pv.z },
                { ax: 'sagittal', slice: pv.x },
                { ax: 'coronal', slice: pv.y },
            ].forEach(cfg => {
                const name = cfg.ax.charAt(0).toUpperCase() + cfg.ax.slice(1);
                const slider = document.getElementById('slider' + name);
                const maxVal = slider ? parseInt(slider.max, 10) : Math.round(cfg.slice);
                const clamped = Math.max(0, Math.min(maxVal, Math.round(cfg.slice)));
                if (slider) slider.value = clamped;
                updateSlice(cfg.ax, clamped);
            });
            await _waitScreenshotFrames(6);
        } else {
            await _waitScreenshotFrames(3);
        }

        const imgs = [
            { ax: 'axial', label: 'Axial' },
            { ax: 'sagittal', label: 'Sagittal' },
            { ax: 'coronal', label: 'Coronal' },
        ].map(a => ({ ...a, dataUrl: _composite2DViewerCanvas(a.ax) })).filter(x => x.dataUrl);
        if (!imgs.length) return null;

        // The report uses one composed evidence figure. Reuse that visual
        // contract here: three aligned dose views above one DVH chart. This
        // keeps an unspecified "show me the dose" request from silently
        // degrading to one arbitrary plane.
        let dvhUrl = null;
        const dvhEl = document.getElementById('dvhChart');
        if (dvhEl && typeof Plotly !== 'undefined' && typeof Plotly.toImage === 'function') {
            try {
                dvhUrl = await Plotly.toImage(dvhEl, { format: 'png', width: 1180, height: 340 });
            } catch (e) { console.warn('[screenshot] DVH export for dose overview failed:', e); }
        }

        const W = 1320, topH = 420, bottomH = dvhUrl ? 390 : 0;
        const H = topH + (dvhUrl ? 18 + bottomH : 0);
        const pad = 22, gap = 14, colorbarW = 82;
        const panelW = Math.floor((W - pad * 2 - colorbarW - gap * 3) / 3);
        const panelH = 320;
        const out = document.createElement('canvas');
        out.width = W; out.height = H;
        const ctx = out.getContext('2d');
        ctx.fillStyle = '#0f172a';
        ctx.fillRect(0, 0, W, H);
        ctx.fillStyle = '#e2e8f0';
        ctx.font = 'bold 17px Inter, system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Dose Distribution Overview', W / 2, 28);

        const drawImage = (entry, i, y = 50, width = panelW, height = panelH) => new Promise(resolve => {
            const img = new Image();
            img.onload = () => {
                const x = i < 3 ? pad + i * (panelW + gap) : pad;
                ctx.fillStyle = '#020617';
                ctx.strokeStyle = 'rgba(148,163,184,0.25)';
                ctx.fillRect(x, y, width, height);
                ctx.strokeRect(x + 0.5, y + 0.5, width - 1, height - 1);
                const scale = Math.min(width / img.width, (height - 32) / img.height);
                const iw = img.width * scale, ih = img.height * scale;
                ctx.drawImage(img, x + (width - iw) / 2, y + 12 + ((height - 44) - ih) / 2, iw, ih);
                ctx.fillStyle = '#cbd5e1';
                ctx.font = '12px Inter, system-ui, sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(`(${String.fromCharCode(97 + i)}) ${entry.label}`, x + width / 2, y + height - 12);
                resolve();
            };
            img.onerror = () => resolve();
            img.src = entry.dataUrl;
        });
        for (let i = 0; i < imgs.length; i++) await drawImage(imgs[i], i);
        _drawScreenshotColorbar(ctx, W - pad - colorbarW, 50, colorbarW, panelH);
        if (dvhUrl) {
            await drawImage({ dataUrl: dvhUrl, label: 'DVH' }, 3, topH + 18, W - pad * 2, bottomH);
        }
        return out.toDataURL('image/png');
    } finally {
        // Always restore the user's slices and dose visibility, including
        // capture failures or an empty viewer. Screenshot capture must not
        // mutate the live treatment view.
        restore();
    }
}

async function _captureScreenshotDataUrl(target, el) {
    if (target === 'dose-overview') return _captureDoseOverviewDataUrl();
    if (target === 'viewer-axial' || target === 'viewer-sagittal' || target === 'viewer-coronal') {
        const axis = target.replace('viewer-', '');
        const composite = _composite2DViewerCanvas(axis);
        if (composite) return composite;
    }
    if (target === 'dvh') {
        const dvhEl = el || _resolveScreenshotTarget('dvh');
        if (dvhEl && typeof Plotly !== 'undefined' && typeof Plotly.toImage === 'function') {
            try {
                await _waitScreenshotFrames(2);
                return await Plotly.toImage(dvhEl, {
                    format: 'png',
                    width: Math.max(900, dvhEl.clientWidth || 900),
                    height: Math.max(420, dvhEl.clientHeight || 420),
                });
            } catch (e) {
                console.warn('[screenshot] Plotly DVH export failed:', e);
            }
        }
    }
    const targetEl = el || _resolveScreenshotTarget(target);
    if (!targetEl || typeof html2canvas === 'undefined') return null;
    const canvas = await html2canvas(targetEl, { useCORS: true, allowTaint: true, scale: 1 });
    return canvas.toDataURL('image/png');
}

function _openScreenshotModal(url, label, index = 0, total = 1) {
    const old = document.querySelector('.image-modal-overlay');
    if (old) old.remove();
    const overlay = document.createElement('div');
    overlay.className = 'image-modal-overlay';
    overlay.addEventListener('click', event => { if (event.target === overlay) overlay.remove(); });
    const close = document.createElement('button');
    close.className = 'image-modal-close';
    close.type = 'button';
    close.textContent = '×';
    close.title = 'Close image';
    close.addEventListener('click', () => overlay.remove());
    const image = document.createElement('img');
    image.src = url;
    image.alt = label || 'Screenshot';
    image.addEventListener('click', event => event.stopPropagation());
    const info = document.createElement('div');
    info.className = 'image-modal-info';
    info.textContent = total > 1 ? `${label || 'Screenshot'} · ${index + 1}/${total}` : (label || 'Screenshot');
    overlay.append(close, image, info);
    document.body.appendChild(overlay);
    const onKey = event => {
        if (event.key === 'Escape') {
            overlay.remove();
            document.removeEventListener('keydown', onKey);
        }
    };
    document.addEventListener('keydown', onKey);
}

function _appendScreenshotToGallery(url, target, question, galleryContext) {
    const context = galleryContext || {};
    const messages = document.getElementById('chatMessages');
    if (!messages || !url) return;
    const label = target || 'Screenshot';
    const requestKey = `${label}|${String(question || '').trim()}`;
    // The same SSE completion can arrive through both the step and final
    // event paths. Keep one tile per logical target/question, while still
    // allowing a single turn to contain different screenshot targets.
    if (!context.keys) context.keys = new Set();
    if (context.keys.has(requestKey)) return;
    context.keys.add(requestKey);
    if (!context.element) {
        const row = document.createElement('div');
        row.className = 'chat-row bot';
        const avatar = document.createElement('div');
        avatar.className = 'chat-avatar bot-avatar';
        avatar.innerHTML = (typeof CHAT_AVATAR_SVGS !== 'undefined' ? CHAT_AVATAR_SVGS.bot : 'B');
        const wrapper = document.createElement('div');
        wrapper.className = 'chat-msg-wrapper bot';
        const message = document.createElement('div');
        message.className = 'chat-msg bot screenshot-gallery-message';
        const title = document.createElement('div');
        title.className = 'chat-gallery-title';
        title.textContent = 'Screenshots';
        const gallery = document.createElement('div');
        gallery.className = 'chat-image-gallery';
        message.append(title, gallery);
        wrapper.appendChild(message);
        row.append(avatar, wrapper);
        messages.appendChild(row);
        context.element = gallery;
        context.title = title;
        context.items = [];
    }
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'chat-image-container chat-gallery-item';
    item.title = 'Open screenshot';
    const image = document.createElement('img');
    image.className = 'chat-screenshot';
    image.src = url;
    image.alt = target || 'Screenshot';
    const zoom = document.createElement('span');
    zoom.className = 'chat-image-zoom-icon';
    zoom.textContent = 'Open';
    const caption = document.createElement('span');
    caption.className = 'chat-image-caption';
    caption.textContent = target || 'Screenshot';
    item.append(image, zoom, caption);
    context.element.appendChild(item);
    context.items.push({ url, label, question: question || '' });
    context.title.textContent = `Screenshots (${context.items.length})`;
    item.addEventListener('click', () => {
        const index = context.items.findIndex(entry => entry.url === url && entry.label === label);
        _openScreenshotModal(url, question || target || 'Screenshot', Math.max(0, index), context.items.length);
    });
    scrollToBottom();
}

// Intercept ui_screenshot: capture the target element, upload to server,
// and display the image in the chat. This bridges the gap between the
// LLM's ui_screenshot tool call and the frontend's actual capture.
async function _interceptScreenshot(target, question, galleryContext) {
    // Unified screenshot target map — single source of truth for both
    // _interceptScreenshot (SSE-driven) and _captureScreenshot (direct).
    uiDebugLog('[screenshot] Capturing target:', target);
    const normalizedTarget = ({ 'dose': 'dose-overview', 'dose_distribution': 'dose-overview', 'dvh-chart': 'dvh' })[target] || target;
    const el = normalizedTarget === 'dose-overview'
        ? document.body
        : await _prepareScreenshotTarget(normalizedTarget);
    if (!el) {
        console.warn('[screenshot] Target element not found:', target);
        if (typeof addChat === 'function') addChat('error', `截图失败：未找到目标元素 "${target}"`);
        return { success: false, error: 'target_not_found' };
    }
    if (typeof html2canvas === 'undefined' && normalizedTarget !== 'dose-overview' && normalizedTarget !== 'dvh') {
        console.warn('[screenshot] html2canvas not loaded');
        if (typeof addChat === 'function') addChat('error', '截图失败：html2canvas 库未加载');
        return { success: false, error: 'html2canvas_unavailable' };
    }
    let dataUrl = null;
    try {
        uiDebugLog('[screenshot] Capturing element:', el.tagName, el.id || el.className);
        dataUrl = await _captureScreenshotDataUrl(normalizedTarget, el);
        if (!dataUrl) throw new Error('No screenshot data was produced');
        uiDebugLog('[screenshot] Data URL size:', Math.round(dataUrl.length / 1024), 'KB');

        const res = await fetch(API + '/screenshot', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                image: dataUrl,
                target: normalizedTarget,
                description: question || `Screenshot of ${normalizedTarget}`,
            }),
        });
        const text = await res.text();
        let data = {};
        try {
            data = text ? JSON.parse(text) : {};
        } catch (_) {
            data = { error: text || `HTTP ${res.status}` };
        }
        if (!res.ok) throw new Error(data.error || data.message || `HTTP ${res.status}`);

        const screenshotUrl = data.url || data.screenshot_url || data.image_url || data.path
            || (data.data && (data.data.url || data.data.path));
        if (!screenshotUrl) throw new Error(data.error || data.message || 'server did not return a screenshot URL');
        _appendScreenshotToGallery(screenshotUrl, normalizedTarget, question, galleryContext);
        uiDebugLog('[screenshot] Captured and uploaded:', screenshotUrl);
        return { success: true, url: screenshotUrl, target: normalizedTarget };
    } catch (e) {
        console.warn('[screenshot] Capture or upload failed:', e);
        if (dataUrl) {
            _appendScreenshotToGallery(dataUrl, normalizedTarget, question, galleryContext);
            if (!galleryContext && typeof addChat === 'function') {
                addChat('system', `Screenshot captured locally, but server persistence failed: ${escHtml(e.message || String(e))}`);
            }
        } else if (typeof addChat === 'function') {
            addChat('error', `Screenshot failed: ${e.message || String(e)}`);
        }
        return { success: false, error: e.message || String(e), target: normalizedTarget };
    }
}

/******** PANEL SWITCHING ********/
