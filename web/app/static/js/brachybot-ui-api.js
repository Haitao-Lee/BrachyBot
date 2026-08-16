/**
 * Present a short, non-blocking application notification.
 *
 * Native ``alert`` dialogs pause rendering and can leave a WebGL interaction
 * or a long-running request looking frozen. Keeping notices in the document
 * also makes their lifecycle predictable for remote and embedded browsers.
 */
function showBrachyBotNotice(message, kind = 'info', durationMs = 6000) {
    const text = String(message || '').trim();
    if (!text || typeof document === 'undefined') return;
    let stack = document.getElementById('brachybotNoticeStack');
    if (!stack) {
        stack = document.createElement('div');
        stack.id = 'brachybotNoticeStack';
        stack.className = 'app-notice-stack';
        stack.setAttribute('aria-live', 'polite');
        stack.setAttribute('aria-relevant', 'additions');
        document.body.appendChild(stack);
    }
    const notice = document.createElement('div');
    const safeKind = ['info', 'success', 'warning', 'error'].includes(kind) ? kind : 'info';
    notice.className = `app-notice app-notice-${safeKind}`;
    notice.setAttribute('role', safeKind === 'error' ? 'alert' : 'status');
    const label = document.createElement('span');
    label.className = 'app-notice-message';
    label.textContent = text;
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'app-notice-close';
    close.setAttribute('aria-label', 'Dismiss notification');
    close.textContent = '×';
    let timer = null;
    const dismiss = () => {
        if (timer) clearTimeout(timer);
        notice.classList.add('leaving');
        setTimeout(() => notice.remove(), 180);
    };
    close.addEventListener('click', dismiss);
    notice.append(label, close);
    stack.appendChild(notice);
    requestAnimationFrame(() => notice.classList.add('visible'));
    if (Number.isFinite(durationMs) && durationMs > 0) timer = setTimeout(dismiss, durationMs);
}
window.showBrachyBotNotice = showBrachyBotNotice;

/**
 * Collect a declarative schema of every editable parameter in the UI.
 *
 * Unlike collectUIState (a point-in-time value snapshot), this returns the
 * editable contract for each control: its semantic id, human label, group,
 * input type, bounds, step, allowed options, and default. The schema is
 * derived directly from the live DOM, so it stays in sync with every panel
 * without a hard-coded parameter registry. The LLM can inspect this catalog
 * and then set any parameter through parameter.set.
 */
function collectParameterSchema() {
    const excluded = new Set([
        'ctPath', 'ctvPath', 'oarPath', 'dicomRtPath',
        'fileCT', 'fileCTV', 'fileOAR', 'fileDicomRT',
        'guideStlValidationFile', 'guideVersionSelect',
        'authUsername', 'authPassword', 'authRemember', 'authDeploymentKey',
        'currentPassword', 'newPassword', 'chatInput',
    ]);
    const groupOf = (el) => {
        let node = el;
        while (node && node !== document.body) {
            if (node.id === 'hyperparamsSection') return 'hyperparams';
            if (node.id === 'surgicalGuideParameters') return 'surgical_guide';
            if (node.id === 'doseColorbarPanel') return 'colorbar';
            if (node.id === 'panelReport' || node.id === 'reportFormHost') return 'report';
            if (node.id === 'panelViewers') return 'viewer';
            if (node.id === 'panelInput') return 'input';
            node = node.parentElement;
        }
        return 'other';
    };
    const labelOf = (el) => {
        const label = el.closest('.form-group')?.querySelector('.form-label');
        if (label) return (label.textContent || '').trim();
        const container = el.closest('.form-group, .control-row, label');
        if (container) {
            const txt = (container.textContent || '').replace(/\s+/g, ' ').trim();
            return txt.slice(0, 60);
        }
        return el.getAttribute('aria-label') || el.title || el.id || '';
    };
    const nodes = document.querySelectorAll('input[id], select[id], textarea[id]');
    const items = [];
    nodes.forEach((el) => {
        const id = el.id;
        if (!id || excluded.has(id)) return;
        const type = el.type || 'text';
        if (type === 'password' || type === 'file' || type === 'hidden') return;
        if (id.toLowerCase().includes('apikey') || id.toLowerCase().includes('token')) return;
        const item = {
            id,
            label: labelOf(el),
            group: groupOf(el),
            type,
            disabled: !!el.disabled,
        };
        if (el.tagName === 'SELECT') {
            item.options = Array.from(el.options).map((o) => o.value).filter(Boolean);
            item.value = el.value || '';
        } else if (type === 'checkbox') {
            item.value = !!el.checked;
        } else if (type === 'number' || type === 'range') {
            item.min = el.min || undefined;
            item.max = el.max || undefined;
            item.step = el.step || undefined;
            item.value = el.value === '' ? null : Number(el.value);
        } else {
            item.value = el.value || '';
        }
        item.default = el.defaultValue !== undefined
            ? (type === 'checkbox' ? !!el.defaultChecked : el.defaultValue)
            : item.value;
        items.push(item);
    });
    return items;
}

/** Apply a single parameter schema entry to the live control. */
function applyParameterSet(param) {
    const id = param && (param.id || param.control);
    const value = param && param.value;
    if (!id) return false;
    const el = document.getElementById(id);
    if (!el) return false;
    if ('checked' in el && (el.type === 'checkbox' || el.type === 'radio')) {
        el.checked = !!value;
    } else if ('value' in el) {
        el.value = value === undefined || value === null ? '' : String(value);
    } else {
        el.textContent = String(value === undefined ? '' : value);
    }
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    reportUIEvent('parameter.set', id, { value });
    // Compute parameters need an explicit apply step to reach the server.
    const group = collectParameterSchema().find((p) => p.id === id)?.group || '';
    if (group === 'hyperparams' && typeof applyHyperparams === 'function') {
        applyHyperparams();
    } else if (group === 'surgical_guide' && typeof window.scheduleWorkspaceSave === 'function') {
        window.scheduleWorkspaceSave('surgical_guide.parameters');
    }
    return true;
}

function _cloneUiStateValue(value, fallback = {}) {
    // UI state is optional context for the agent. Keep its cloning local to
    // this bundle: Workspace owns a separate private serializer and scripts
    // are loaded independently during startup.
    try {
        return JSON.parse(JSON.stringify(value));
    } catch (error) {
        console.warn('[ui-state] Unable to clone optional UI state:', error);
        return fallback;
    }
}

function collectUIState() {
    // A broken optional presentation field must never prevent a clinical or
    // conversational request from reaching the server. This boundary is
    // deliberately defensive because callers include chat, manual planning,
    // export, and monitor actions.
    try {
        return _collectUIState();
    } catch (error) {
        console.error('[ui-state] UI state collection failed; continuing without it:', error);
        return {};
    }
}

function _collectUIState() {
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
            reference_direc_mode: (document.getElementById('refDirecAuto')?.checked) ? 'auto' : 'manual',
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
            dose_value_unit: 'gy',
            in_lowest_energy: Number(document.getElementById('inLowestEnergy')?.value || 120),
            out_highest_energy: Number(document.getElementById('outHighestEnergy')?.value || 120),
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
            // CTV auxiliary labels are persisted separately from OAR rows.
            // This preserves user-selected hard-obstacle classifications
            // without polluting the OAR whitelist or inventing anatomy.
            ctv_labels: Object.entries(dataTreeState.ctvLabels || {}).map(([id, label]) => ({
                id,
                label_id: Number.isFinite(Number(label?.labelId ?? label?.label_id))
                    ? Number(label.labelId ?? label.label_id) : null,
                label: label?.label || null,
                category: label?.category === 'non_traversable' ? 'non_traversable' : 'traversable',
                source: 'ctv',
                visible: label?.visible !== false,
                visible_2d: label?.visible2D !== false,
                visible_3d: label?.visible3D !== false,
                opacity: Number.isFinite(Number(label?.opacity)) ? Number(label.opacity) : 0.7,
                color: label?.color || null,
            })).filter(item => item.id || item.label_id !== null),
            seeds: dataTreeState.planning?.seeds?.length || 0,
            needles: dataTreeState.planning?.needles?.length || 0,
            dose_levels: dataTreeState.planning?.doseLevels?.length || 0,
            // The compact counts above are useful for status responses, but
            // the durable UI snapshot also needs the canonical visual-node
            // contract so colors, opacity, visibility and artifact status can
            // be restored without reconstructing a second tree model.
            nodes: typeof window.getDataTreeNodeSnapshot === 'function'
                ? window.getDataTreeNodeSnapshot()
                : [],
            // Keep the compact UI bridge session-aware as well.  The full
            // workspace snapshot stores the same state in camelCase, but
            // hydration can arrive through this smaller state endpoint first.
            expansion_state: (dataTreeState.expansionState
                && typeof dataTreeState.expansionState === 'object'
                && !Array.isArray(dataTreeState.expansionState))
                ? _cloneUiStateValue(dataTreeState.expansionState)
                : {},
            dose_overlay_visible: dataTreeState.planning?.doseOverlay?.visible !== false,
            dvh_ready: !!dataTreeState.planning?.dvh?.loaded,
        } : {},
        manual: (typeof manualPlanningState !== 'undefined') ? {
            active_needle_id: manualPlanningState.activeNeedleId,
            seed_counter: manualPlanningState.seedCounter,
            needle_counter: manualPlanningState.needleCounter,
            dose_engine: manualPlanningState.doseEngine || 'dose_unet_spacing1mm',
        } : {},
        training: (typeof trainingMonitorState !== 'undefined') ? {
            active: !!trainingMonitorState.active,
            phase: trainingMonitorState.phase || (trainingMonitorState.active ? 'active' : 'inactive'),
            run_id: trainingMonitorState.runId || null,
            language: trainingMonitorState.language || null,
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
        // False means the controls are still at their case defaults.  A
        // freshly generated/imported mask may therefore enable its normal
        // overlay presentation without overriding an explicit user choice.
        userConfigured: false,
        zoom: 1.0,
        panX: 0,
        panY: 0,
        flipH: false,
        flipV: false,
        rotation: 0,
        activeTool: 'crosshair',
        layout: '3d-top',
    },
    annotations: [],
    annotationUndoStack: [],
    annotationRedoStack: [],
    // Manual mask drawing state
    maskLabels: {}, // { 'mask_1': { name: 'Manual Mask 1', color: '#ff0000', voxels: Set<'x,y,z'>, visible: true, opacity: 0.6, movedTo: 'ctv'|'oar'|undefined } }
    maskLabelCounter: 0,
    // The mask being painted by the Draw tool; null when no mask is in
    // progress. Clicking Draw again (or another tool) finalises it.
    activeMaskId: null,
    labelImage: {
        axial:   { visible: true, opacity: 0.6 },
        sagittal: { visible: true, opacity: 0.6 },
        coronal:  { visible: true, opacity: 0.6 },
        '3d':     { visible: true, opacity: 0.6 },
    },
};

/******** API ********/
const API = '/api';

// Planning controls and workspace snapshots use physical Gy. Raw DoseUNet
// conversion is reserved for viewer/model boundaries.
const DEFAULT_DOSE_MODEL_SCALE_GY = 190.8;
const DEFAULT_PRESCRIPTION_GY = 120;
window.__doseModelScaleGy = Number(window.__doseModelScaleGy || DEFAULT_DOSE_MODEL_SCALE_GY);
function doseModelScaleGy() {
    const value = Number(window.__doseModelScaleGy);
    return Number.isFinite(value) && value > 0 ? value : DEFAULT_DOSE_MODEL_SCALE_GY;
}
function doseGyToModel(value, fallback = 1) {
    const gy = Number(value);
    return Number.isFinite(gy) && gy >= 0 ? gy / doseModelScaleGy() : fallback;
}
function doseModelToGy(value, fallback = doseModelScaleGy()) {
    const modelValue = Number(value);
    return Number.isFinite(modelValue) && modelValue >= 0 ? modelValue * doseModelScaleGy() : fallback;
}
function prescriptionMultiplierToGy(value, fallback = DEFAULT_PRESCRIPTION_GY) {
    const multiplier = Number(value);
    return Number.isFinite(multiplier) && multiplier >= 0
        ? multiplier * DEFAULT_PRESCRIPTION_GY
        : fallback;
}
function planningDoseValueToGy(value, valueUnit = '', fallback = DEFAULT_PRESCRIPTION_GY) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
    const unit = String(valueUnit || '').trim().toLowerCase();
    if (unit === 'gy' || unit === 'physical_gy' || unit === 'dose_gy') return parsed;
    // Unit-less values <= 5 are legacy Rx multipliers from old sessions.
    return parsed <= 5 ? prescriptionMultiplierToGy(parsed, fallback) : parsed;
}

var trainingMonitorState = {
    active: false,
    phase: 'inactive',
    runId: null,
    language: 'en',
    goal: '',
    sessionId: 'web',
    lastFeedbackAt: 0,
    lastScreenshotAt: 0,
    pendingFeedback: [],
    feedbackTimer: null,
    // One monitor turn can produce several evidence targets.  Keep one
    // gallery context for the whole run so each checkpoint becomes a tile in
    // one chronological chat message instead of a separate floating gallery.
    screenshotGalleryContext: null,
};

function _clearMonitorFeedbackTimer() {
    if (trainingMonitorState.feedbackTimer) {
        clearTimeout(trainingMonitorState.feedbackTimer);
        trainingMonitorState.feedbackTimer = null;
    }
}

function _flushMonitorFeedback(ownerSessionId, ownerRunId, options = {}) {
    _clearMonitorFeedbackTimer();
    const ownsRun = trainingMonitorState.sessionId === ownerSessionId
        && trainingMonitorState.runId === ownerRunId;
    // A delayed timer from a case we have left must never clear the feedback
    // accumulated by the newly selected case. It simply becomes irrelevant.
    if (!ownsRun || ownerSessionId !== _activeApiSessionId()) {
        return false;
    }
    // Finish Monitoring deliberately flushes the last small batch before its
    // presentation changes to "stopping". Keep that batch user-visible rather
    // than silently dropping the final manual edits.
    if (!trainingMonitorState.active && !options.allowStopping) {
        trainingMonitorState.pendingFeedback = [];
        return false;
    }
    const pending = Array.isArray(trainingMonitorState.pendingFeedback)
        ? trainingMonitorState.pendingFeedback.splice(0)
        : [];
    if (!pending.length) return false;
    const unique = [...new Map(pending.map(item => [item.message, item])).values()];
    const title = monitorChatText('阶段监测', 'Stage monitor', ownerSessionId);
    const body = unique.length === 1
        ? unique[0].message
        : unique.map(item => `- ${item.message}`).join('\n');
    const requestId = `monitor-${ownerRunId}`;
    addChat(
        'bot-response',
        `**${title}**\n\n${body}`,
        true,
        Date.now(),
        false,
        ownerSessionId,
        {
            requestId,
            messageId: `assistant-${requestId}-feedback-${Date.now()}`,
            messageKind: 'monitor_feedback',
            responseLanguage: monitorConversationLanguage(ownerSessionId),
        },
    );
    return true;
}

function _queueMonitorFeedback(message, type, label, ownerSessionId, ownerRunId) {
    if (!message || !trainingMonitorState.active) return false;
    const immediate = type === 'manual.dose'
        || (/^(planning|segmentation)\.step$/i.test(type)
            && /completed|complete|done|failed|error/i.test(label || ''));
    const aggregate = /^manual\.(seed|needle)/i.test(type);
    if (immediate) {
        _flushMonitorFeedback(ownerSessionId, ownerRunId);
        const title = monitorChatText('监测建议', 'Monitor feedback', ownerSessionId);
        const requestId = `monitor-${ownerRunId}`;
        addChat(
            'bot-response',
            `**${title}**\n\n${message}`,
            true,
            Date.now(),
            false,
            ownerSessionId,
            {
                requestId,
                messageId: `assistant-${requestId}-feedback-${Date.now()}`,
                messageKind: 'monitor_feedback',
                responseLanguage: monitorConversationLanguage(ownerSessionId),
            },
        );
        return true;
    }
    if (!aggregate) return false;
    if (!Array.isArray(trainingMonitorState.pendingFeedback)) {
        trainingMonitorState.pendingFeedback = [];
    }
    trainingMonitorState.pendingFeedback.push({ message, type, label, at: Date.now() });
    _clearMonitorFeedbackTimer();
    trainingMonitorState.feedbackTimer = setTimeout(() => {
        _flushMonitorFeedback(ownerSessionId, ownerRunId);
    }, 2500);
    return true;
}

function monitorConversationLanguage(sessionId = trainingMonitorState.sessionId) {
    if (typeof window.conversationLanguageForSession === 'function') {
        const conversation = window.conversationLanguageForSession(sessionId);
        if (conversation === 'zh' || conversation === 'en') return conversation;
    }
    return window._responseLanguage || window._i18nLang || 'en';
}
window.monitorConversationLanguage = monitorConversationLanguage;

function monitorChatText(zh, en, sessionId = trainingMonitorState.sessionId) {
    return monitorConversationLanguage(sessionId) === 'zh' ? zh : en;
}
window.monitorChatText = monitorChatText;

// Keep the monitor affordance in one place. Monitoring is case-owned state;
// the presentation must be explicitly cleared during a case transition
// instead of relying on a stale body class from the previous case.
function setMonitorPresentation(phaseOrActive) {
    const phase = typeof phaseOrActive === 'string'
        ? phaseOrActive
        : (phaseOrActive ? 'active' : 'inactive');
    const enabled = ['starting', 'active', 'stopping'].includes(phase);
    if (typeof document === 'undefined') return;
    document.body.classList.toggle('monitor-active', enabled);
    document.body.classList.toggle('monitor-starting', phase === 'starting');
    document.body.classList.toggle('monitor-stopping', phase === 'stopping');
    document.body.dataset.monitorPhase = phase;
    const edge = document.getElementById('monitorEdgeOverlay');
    if (edge) {
        if (edge._monitorHideTimer) {
            clearTimeout(edge._monitorHideTimer);
            edge._monitorHideTimer = null;
        }
        if (enabled) {
            edge.hidden = false;
            // Let the browser paint the non-visible state first so entering
            // Monitor has a quiet, deliberate transition rather than a flash.
            const showEdge = () => {
                if (document.body.dataset.monitorPhase === phase) {
                    edge.classList.add('is-visible');
                }
            };
            if (typeof requestAnimationFrame === 'function') requestAnimationFrame(showEdge);
            else showEdge();
        } else {
            edge.classList.remove('is-visible');
            // Do not use `hidden` until the opacity transition has finished;
            // otherwise Finish Monitoring visibly snaps the perimeter off.
            edge._monitorHideTimer = setTimeout(() => {
                if (document.body.dataset.monitorPhase === 'inactive') edge.hidden = true;
            }, 280);
        }
        edge.setAttribute('aria-hidden', enabled ? 'false' : 'true');
        edge.dataset.phase = phase;
    }
    const icon = document.querySelector('.chat-header-icon');
    if (icon) {
        icon.setAttribute('data-monitoring', enabled ? 'true' : 'false');
        icon.setAttribute('aria-busy', enabled ? 'true' : 'false');
        icon.setAttribute(
            'aria-label',
            enabled ? monitorChatText('监测中', 'Monitoring active')
                : monitorChatText('未启用监测', 'Monitoring inactive')
        );
    }
    const status = document.getElementById('monitorStatus');
    if (status) {
        status.hidden = !enabled;
        status.setAttribute('aria-hidden', enabled ? 'false' : 'true');
        status.setAttribute('aria-live', 'polite');
        const label = status.querySelector('[data-i18n-zh][data-i18n-en]');
        if (label) {
            label.textContent = phase === 'starting'
                ? monitorChatText('正在启动监测', 'Starting monitor')
                : phase === 'stopping'
                    ? monitorChatText('正在整理监测结果', 'Finalizing monitor')
                    : monitorChatText('持续监测中', 'Monitoring');
        }
    }
    const startButton = document.getElementById('monitorStartButton');
    const stopButton = document.getElementById('monitorStopButton');
    if (startButton) {
        startButton.disabled = enabled;
        startButton.setAttribute('aria-pressed', enabled ? 'true' : 'false');
    }
    if (stopButton) {
        stopButton.disabled = !enabled || phase === 'starting' || phase === 'stopping';
        stopButton.setAttribute('aria-pressed', phase === 'stopping' ? 'true' : 'false');
    }
}
window.setMonitorPresentation = setMonitorPresentation;

function setTrainingMonitorPhase(phase) {
    const normalized = ['inactive', 'starting', 'active', 'stopping', 'error'].includes(phase)
        ? phase
        : 'inactive';
    trainingMonitorState.phase = normalized;
    trainingMonitorState.active = normalized === 'active';
    setMonitorPresentation(normalized);
}
window.setTrainingMonitorPhase = setTrainingMonitorPhase;

function restoreTrainingMonitorSnapshot(training, sessionId) {
    const snapshot = training && typeof training === 'object' ? training : {};
    const staleRunId = snapshot.run_id || snapshot.runId || null;
    trainingMonitorState.runId = staleRunId;
    trainingMonitorState.language = snapshot.language || monitorConversationLanguage(sessionId);
    trainingMonitorState.goal = snapshot.goal || '';
    trainingMonitorState.sessionId = sessionId;
    if (snapshot.active) {
        // Hydration restores history, never a live subscription. The browser
        // or server may have restarted since this run was recorded.
        trainingMonitorState.active = false;
        trainingMonitorState.phase = 'inactive';
        trainingMonitorState.runId = null;
        trainingMonitorState.pendingFeedback = [];
        trainingMonitorState.screenshotGalleryContext = null;
        setTrainingMonitorPhase('inactive');
        if (typeof window.releaseTrainingMonitorForSession === 'function') {
            void window.releaseTrainingMonitorForSession(
                sessionId,
                'ui_state_restore',
                { runId: staleRunId, skipLocal: true },
            );
        }
    } else {
        setTrainingMonitorPhase('inactive');
    }
}

var manualPlanningState = {
    activeNeedleId: null,
    seedCounter: 0,
    needleCounter: 0,
    planningId: null,
    planningVersion: 0,
    artifactStatus: {},
    doseEngine: 'dose_unet_spacing1mm',
    // Keep the last accepted geometry separate from the live drag preview.
    lastDoseNeedles: [],
    needleReplanPrompt: null,
    // Coalesce rapid edits before the expensive dose/DVH request. The owner
    // session fence prevents a timer from firing after a case switch.
    doseRecomputeTimer: null,
    doseRecomputeOwnerSessionId: null,
    doseRecomputeScheduledPromise: null,
    doseRecomputeRunning: false,
    doseRecomputeQueued: false,
    doseRecomputeSequence: 0,
    _doseRecomputePromise: null,
    _doseRecomputeJob: null,
};

function _activeApiSessionId() {
    return (typeof activeSessionId !== 'undefined' && activeSessionId) || state.sessionId || 'web';
}

function _shouldLogTrainingFeedback(message, type = '', label = '') {
    if (!message || !trainingMonitorState.active) return false;
    const now = Date.now();
    // Manual geometry events are aggregated by _queueMonitorFeedback. Keep
    // this throttle for lower-value UI chatter and non-manual checkpoints.
    const highValueEvent = /^(planning|segmentation)\.step$|^manual\.dose$/i.test(type);
    const important = highValueEvent || /dose|V100|D90|Seed|Needle|step|剂量|粒子|针道|分割|步骤/i.test(`${message} ${label}`);
    if (highValueEvent) {
        trainingMonitorState.lastFeedbackAt = now;
        return true;
    }
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
        if (typeof scheduleWorkspaceSave === 'function') scheduleWorkspaceSave(reason);
    } catch (e) {
        console.debug('[ui-state] sync skipped:', e);
    }
}

async function reportUIEvent(type, label, detail = {}, options = {}) {
    const ownerSessionId = _activeApiSessionId();
    const language = monitorConversationLanguage(ownerSessionId);
    const ownerRunId = trainingMonitorState.runId;
    try {
        const res = await fetch(API + '/ui/event', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: ownerSessionId,
                type,
                label,
                detail,
                language,
                monitor_run_id: ownerRunId,
                ui_state: (typeof collectUIState === 'function') ? collectUIState() : {},
            }),
        });
        const data = await res.json().catch(() => null);
        if (ownerSessionId !== _activeApiSessionId()) return null;
        if (ownerRunId && data?.monitor_run_id && ownerRunId !== data.monitor_run_id) return null;
        const feedbackText = data && (data.feedback_localized || data.feedback);
        const queued = _queueMonitorFeedback(
            feedbackText,
            type,
            label,
            ownerSessionId,
            ownerRunId,
        );
        if (!queued && feedbackText && _shouldLogTrainingFeedback(feedbackText, type, label)) {
            const monitorPrefix = monitorChatText('监测建议', 'Monitor feedback', ownerSessionId);
            const requestId = `monitor-${ownerRunId}`;
            addChat(
                'bot-response',
                `**${monitorPrefix}**\n\n${feedbackText}`,
                true,
                Date.now(),
                false,
                ownerSessionId,
                {
                    requestId,
                    messageId: `assistant-${requestId}-feedback-${Date.now()}`,
                    messageKind: 'monitor_feedback',
                    responseLanguage: language,
                },
            );
        }
        if (data && data.suggested_screenshot && trainingMonitorState.active) {
            const now = Date.now();
            const ss = data.suggested_screenshot;
            // Dose recomputation is an explicit teaching checkpoint: the
            // monitor must not hide the corresponding screenshot behind the
            // generic 45-second chatter throttle. Other event types remain
            // throttled to avoid filling the chat with redundant captures.
            const isStageCheckpoint = /^(planning|segmentation)\.step$/i.test(type)
                && /completed|complete|done/i.test(label || '');
            const isDoseCheckpoint = type === 'manual.dose'
                || ss.target === 'dose-overview'
                || ss.target === 'dvh';
            if ((isStageCheckpoint || isDoseCheckpoint || now - trainingMonitorState.lastScreenshotAt > 45000)
                && typeof _interceptScreenshot === 'function') {
                trainingMonitorState.lastScreenshotAt = now;
                // ``description`` is kept as a compatibility fallback for
                // older servers; current training payloads use ``question``.
                setTimeout(() => {
                    // A delayed checkpoint must not outlive the monitor run or
                    // leak into a newly selected case.
                    if (!trainingMonitorState.active
                        || ownerRunId !== trainingMonitorState.runId
                        || ownerSessionId !== _activeApiSessionId()) return;
                    if (!trainingMonitorState.screenshotGalleryContext) {
                        trainingMonitorState.screenshotGalleryContext = {
                            keys: new Set(),
                            items: [],
                            sessionId: ownerSessionId,
                            requestId: `monitor-${ownerRunId || Date.now()}`,
                            messageId: `assistant-monitor-${ownerRunId || Date.now()}`,
                            mode: 'monitor',
                            layout: 'auto',
                        };
                    }
                    const monitorScreenshotContext = trainingMonitorState.screenshotGalleryContext;
                    const focusObjectIds = [
                        ...(Array.isArray(ss.focus_seed_ids) ? ss.focus_seed_ids : []),
                        ...(Array.isArray(ss.object_ids) ? ss.object_ids : []),
                    ].map(String);
                    _interceptScreenshot(
                        ss.target || 'dose-overview',
                        ss.question || ss.description || monitorChatText('监测截图', 'Monitor screenshot', ownerSessionId),
                        monitorScreenshotContext,
                        {
                            sessionId: ownerSessionId,
                            requestId: monitorScreenshotContext.requestId,
                            messageId: monitorScreenshotContext.messageId,
                            mode: 'monitor',
                            monitorOnly: true,
                            plan: {
                                version: 2,
                                mode: 'monitor',
                                question: ss.question || ss.description || '',
                                description: ss.description || '',
                                layout: ss.layout || 'auto',
                                views: Array.isArray(ss.views) && ss.views.length
                                    ? ss.views
                                    : [ss.target || 'dose-overview'],
                                object_ids: focusObjectIds,
                                highlight_object_ids: focusObjectIds,
                                hide_unrelated: !!ss.hide_unrelated || focusObjectIds.length > 0,
                                focus: {
                                    kind: focusObjectIds.length ? 'close-up' : 'auto',
                                    padding: Number(ss.padding || 0.35),
                                },
                                overlays: ss.overlays || {},
                                data_version: ss.data_version || '',
                                planning_id: ss.planning_id || '',
                                case_id: ownerSessionId,
                            },
                        },
                    ).then(result => {
                        if (!result?.success
                            || !trainingMonitorState.active
                            || ownerRunId !== trainingMonitorState.runId
                            || ownerSessionId !== _activeApiSessionId()) return;
                        const title = monitorChatText('监测证据', 'Monitor evidence', ownerSessionId);
                        const evidenceCaption = monitorChatText(
                            '已捕获与当前规划检查对应的可视化证据。',
                            'Captured visual evidence for the current planning checkpoint.',
                            ownerSessionId,
                        );
                        const attachments = Array.isArray(result.attachments) && result.attachments.length
                            ? result.attachments
                            : (monitorScreenshotContext.items || []);
                        addChat(
                            'bot-response',
                            `**${title}**\n\n${evidenceCaption}`,
                            true,
                            Date.now(),
                            false,
                            ownerSessionId,
                            {
                                requestId: monitorScreenshotContext.requestId,
                                messageId: monitorScreenshotContext.messageId,
                                messageKind: 'monitor_evidence',
                                responseLanguage: language,
                                attachments,
                            },
                        );
                    }).catch(error => {
                        console.debug('[monitor] screenshot evidence skipped:', error);
                    });
                }, 500);
            }
        }
        // UI events include viewer, Data Tree, manual-planning and form
        // interactions. Coalesce their workspace checkpoint after the API
        // event succeeds so a reload restores the visible case state.
        if (typeof window.scheduleWorkspaceSave === 'function') {
            window.scheduleWorkspaceSave(`ui.event:${type}`);
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
        // A deployment key may be supplied in the URL for convenience. Keep
        // it scoped to this browser session; credentials must not survive a
        // deleted case or leak into a later session through persistent storage.
        sessionStorage.setItem('BRACHYBOT_API_KEY', keyFromUrl);
        window.BRACHYBOT_API_KEY = keyFromUrl;
        // Clean URL without reload
        const cleanUrl = window.location.pathname;
        window.history.replaceState({}, '', cleanUrl);
    }
    window.setBrachyBotApiKey = function setBrachyBotApiKey(key) {
        const value = String(key || '').trim();
        window.BRACHYBOT_API_KEY = value;
        if (value) sessionStorage.setItem('BRACHYBOT_API_KEY', value);
        else sessionStorage.removeItem('BRACHYBOT_API_KEY');
        // Capability probes can run before the auth overlay is submitted.
        // Notify the UI so protected, read-only probes are retried as soon as
        // the deployment key becomes available.
        window.dispatchEvent(new Event('brachybot:api-key-changed'));
    };
    window.fetch = function brachybotFetch(input, init) {
        // The deployment key is persisted in localStorage so the operator's
        // remembered credential survives reloads and tab closings on this
        // workstation, and setBrachyBotApiKey() keeps the in-memory copy in
        // sync. Reading order keeps a fresh in-memory key authoritative.
        const key = window.BRACHYBOT_API_KEY
            || sessionStorage.getItem('BRACHYBOT_API_KEY')
            || localStorage.getItem('BRACHYBOT_API_KEY')
            || '';
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
function _uploadProgressElements(targetId) {
    const suffix = targetId === 'ctvPath'
        ? 'CTV'
        : (targetId === 'oarPath' ? 'OAR' : 'CT');
    const prefix = suffix === 'CT' ? 'uploadProgressOverlay' : `uploadProgressOverlay_${suffix.toLowerCase()}`;
    const overlay = document.getElementById(prefix)
        || document.getElementById('uploadProgressOverlay');
    return {
        overlay,
        progressText: overlay?.querySelector('.upload-progress-text')
            || document.getElementById('uploadProgressText'),
        progressFilename: overlay?.querySelector('.upload-progress-filename')
            || document.getElementById('uploadProgressFilename'),
    };
}

async function handleFileSelect(input, targetId) {
    const files = input.files ? Array.from(input.files) : [];
    if (files.length === 0) return;
    const ownerSessionId = String(_activeApiSessionId());
    const ownerCtPath = (document.getElementById('ctPath')?.value || '').trim();
    const ownerTumorType = document.getElementById('ctvModelSelect')?.value || null;
    const isCurrentOwner = () => ownerSessionId === String(_activeApiSessionId());

    const pathInput = document.getElementById(targetId);
    const { overlay, progressText, progressFilename } = _uploadProgressElements(targetId);
    const uploadLabel = targetId === 'ctvPath'
        ? 'CTV mask'
        : (targetId === 'oarPath' ? 'OAR mask' : 'CT image');

    // Show upload progress overlay
    if (!overlay || !progressText || !progressFilename) {
        throw new Error(`Upload progress UI is missing for ${targetId}`);
    }
    progressText.textContent = files.length === 1
        ? `Uploading ${uploadLabel}...`
        : `Uploading ${uploadLabel} (${files.length} files)...`;
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
            headers: { 'X-BrachyBot-Session': ownerSessionId },
            body: formData,
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({ error: 'Upload failed' }));
            throw new Error(err.error || 'Upload failed');
        }

        const data = await res.json();
        if (isCurrentOwner()) {
            pathInput.value = data.path;
            pathInput.disabled = false;
        }
        if (isCurrentOwner() && (targetId === 'ctvPath' || targetId === 'oarPath')) {
            state[targetId] = data.path;
            if (typeof scheduleWorkspaceSave === 'function') scheduleWorkspaceSave();
        }

        // Auto-load CT to viewers if it's a CT file
        if (targetId === 'ctPath') {
            if (isCurrentOwner()) {
                state.ctPath = data.path;
                state.ctSourceKind = data.kind || null;
            }
            if (isCurrentOwner()) addChat('system',
                data.kind === 'dicom_folder'
                    ? `Uploaded DICOM folder (${data.file_count} files) → ${data.path}`
                    : `Uploaded ${data.filename} (${(data.size / 1024 / 1024).toFixed(2)} MB)`);
            await loadCTToViewers(data.path, {
                sessionId: ownerSessionId,
                announce: isCurrentOwner(),
            });
        } else if (targetId === 'ctvPath' || targetId === 'oarPath') {
            await importUploadedMask(targetId === 'ctvPath' ? 'ctv' : 'oar', data.path, {
                sessionId: ownerSessionId,
                ctPath: ownerCtPath,
                tumorType: ownerTumorType,
            });
        }

        if (isCurrentOwner()) overlay.classList.remove('active');
    } catch (e) {
        if (isCurrentOwner()) {
            overlay.classList.remove('active');
            pathInput.value = '';
            pathInput.disabled = false;
            showBrachyBotNotice(`File upload failed: ${e.message || e}`, 'error');
        }
    }

    if (isCurrentOwner()) input.value = '';
}

/** Import a user-provided label into the session-scoped agent memory. */
async function importUploadedMask(kind, labelPath, options = {}) {
    const ownerSessionId = String(options.sessionId || _activeApiSessionId());
    const isCurrentOwner = () => ownerSessionId === String(_activeApiSessionId());
    const ctPath = String(
        options.ctPath
        || (isCurrentOwner() ? document.getElementById('ctPath')?.value : '')
        || ''
    ).trim();
    if (!ctPath) {
        showBrachyBotNotice('Load the CT image before importing a CTV/OAR mask.', 'warning');
        return { success: false, error: 'CT image is required before mask import.' };
    }
    try {
        const body = {
            kind,
            image_path: ctPath,
            label_path: String(labelPath || '').trim(),
        };
        if (kind === 'ctv') {
            body.tumor_type = options.tumorType
                || (isCurrentOwner() ? document.getElementById('ctvModelSelect')?.value : null)
                || null;
        }
        // A session may still be decoding its durable arrays after the shell
        // has switched.  Retry the server's explicit 202 response instead of
        // treating it as a failed upload; this keeps the Browse workflow
        // non-blocking while preserving the authoritative mask write.
        let res;
        for (let attempt = 0; attempt <= 60; attempt += 1) {
            res = await fetch(API + '/segmentation', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-BrachyBot-Session': ownerSessionId,
                },
                body: JSON.stringify(body),
            });
            if (res.status !== 202 || attempt >= 60) break;
            const retryAfter = Number(res.headers.get('Retry-After-Ms') || 250);
            await new Promise(resolve => setTimeout(resolve, Math.max(100, Math.min(1000, retryAfter))));
        }
        const payload = await res.json().catch(() => ({}));
        if (!res.ok || !payload.success) throw new Error(payload.error || `HTTP ${res.status}`);
        if (!isCurrentOwner()) return payload;
        if (typeof addChat === 'function') addChat('system', `${kind.toUpperCase()} mask imported for the current CT.`);
        if (typeof _saveManualState === 'function') {
            _saveManualState({ [kind === 'ctv' ? 'ctv_segmentation' : 'oar_segmentation']: true });
        }
        if (kind === 'oar' && typeof window.hydrateOarDataTreeFromPayload === 'function') {
            // Paint server-confirmed numbered OAR nodes before the binary
            // volume fetch. This is the immediate control-plane update; the
            // label volume and organs endpoint below reconcile the voxels and
            // metadata without inventing anatomical names for an opaque mask.
            window.hydrateOarDataTreeFromPayload(payload, ownerSessionId);
        }
        if (typeof loadLabelVolumes === 'function') {
            await loadLabelVolumes({
                forceFresh: true,
                preserveViewerState: true,
                resetPresentation: true,
                sessionId: ownerSessionId,
            });
        }
        if (!isCurrentOwner()) return payload;
        if (kind === 'oar' && typeof window.hydrateOarDataTreeFromPayload === 'function') {
            // A background label refresh may replace the tree while it is
            // decoding. Re-apply the small authoritative response last so a
            // successful upload can never finish with an empty OAR branch.
            window.hydrateOarDataTreeFromPayload(payload, ownerSessionId);
        }
        if (kind === 'oar' && typeof hydrateOarDataTreeFromServer === 'function') {
            await hydrateOarDataTreeFromServer(undefined, ownerSessionId);
        }
        if (!isCurrentOwner()) return payload;
        if (typeof renderDataTree === 'function') renderDataTree();
        if (typeof startSegmentationMeshPrewarm === 'function') startSegmentationMeshPrewarm(kind);
        if (typeof _refreshManualStepUI === 'function') _refreshManualStepUI();
        if (typeof scheduleWorkspaceSave === 'function') scheduleWorkspaceSave();
        showBrachyBotNotice(`${kind.toUpperCase()} mask imported.`, 'success');
        return payload;
    } catch (error) {
        const message = error.message || String(error);
        if (isCurrentOwner()) {
            showBrachyBotNotice(`${kind.toUpperCase()} mask import failed: ${message}`, 'error');
            if (typeof addChat === 'function') addChat('error', `${kind.toUpperCase()} mask import failed: ${message}`);
        }
        return { success: false, error: message };
    }
}
window.importUploadedMask = importUploadedMask;

function _dicomRtText(zh, en) {
    return typeof window._t === 'function' ? window._t(zh, en) : en;
}

function renderDicomRTImportStatus(imports, options = {}) {
    const status = document.getElementById('dicomRtImportStatus');
    const path = document.getElementById('dicomRtPath');
    if (!status) return;
    const records = Array.isArray(imports) ? imports.filter(item => item && typeof item === 'object') : [];
    status.className = 'dicom-rt-status';
    status.replaceChildren();
    if (!records.length) {
        status.hidden = true;
        if (path) path.value = '';
        return;
    }
    const latest = records[records.length - 1];
    const modality = String(latest.modality || 'DICOM-RT');
    const filename = String(latest.filename || modality);
    const detail = modality === 'RTSTRUCT'
        ? _dicomRtText(`${Number(latest.structure_count || 0)} 个结构`, `${Number(latest.structure_count || 0)} structures`)
        : modality === 'RTDOSE'
            ? _dicomRtText(`最大剂量 ${Number(latest.dose_max || 0).toFixed(2)} ${latest.dose_units || ''}`, `maximum dose ${Number(latest.dose_max || 0).toFixed(2)} ${latest.dose_units || ''}`)
            : '';
    const count = records.length > 1
        ? _dicomRtText(`当前病例共 ${records.length} 个导入记录。`, `${records.length} imports are stored in this case.`)
        : '';
    const strong = document.createElement('strong');
    strong.textContent = `${modality}: ${filename}`;
    const message = document.createElement('span');
    message.textContent = ` ${[detail, count].filter(Boolean).join(' · ')}`;
    const warning = document.createElement('div');
    warning.textContent = _dicomRtText(
        '配准尚未确认；数据尚未应用到规划。',
        'Registration is unconfirmed; the data has not been applied to planning.',
    );
    warning.style.marginTop = '0.2rem';
    status.append(strong, message, warning);
    status.hidden = false;
    status.classList.add('is-warning');
    if (path) path.value = filename;
    if (!options.silent && typeof scheduleWorkspaceSave === 'function') scheduleWorkspaceSave('dicom_rt.imported');
}

async function refreshDicomRTImportStatus(options = {}) {
    const ownerSessionId = String(options.sessionId || _activeApiSessionId());
    const isCurrentOwner = () => ownerSessionId === String(_activeApiSessionId());
    try {
        const response = await fetch(API + '/import/dicom_rt', {
            headers: { 'X-BrachyBot-Session': ownerSessionId },
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
        if (!isCurrentOwner()) return [];
        const records = Array.isArray(payload.imports) ? payload.imports : [];
        state.dicomRtImports = records;
        renderDicomRTImportStatus(records, { silent: true });
        return records;
    } catch (error) {
        if (isCurrentOwner() && !options.silent) {
            showBrachyBotNotice(error.message || String(error), 'error');
        }
        return [];
    }
}

async function handleDicomRTImport(input) {
    const file = input?.files?.[0];
    if (!file) return;
    const button = document.getElementById('dicomRtImportButton');
    const status = document.getElementById('dicomRtImportStatus');
    const path = document.getElementById('dicomRtPath');
    const sessionAtStart = String(_activeApiSessionId());
    const isCurrentOwner = () => sessionAtStart === String(_activeApiSessionId());
    if (button) button.disabled = true;
    if (path) path.value = file.name;
    if (status) {
        status.hidden = false;
        status.className = 'dicom-rt-status is-loading';
        status.textContent = _dicomRtText(`正在读取 ${file.name}...`, `Reading ${file.name}...`);
    }
    try {
        const formData = new FormData();
        formData.append('file', file, file.name);
        const response = await fetch(API + '/import/dicom_rt', {
            method: 'POST',
            headers: { 'X-BrachyBot-Session': sessionAtStart },
            body: formData,
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload.success) throw new Error(payload.error || `HTTP ${response.status}`);
        if (!isCurrentOwner()) return payload;
        state.dicomRtImports = [...(Array.isArray(state.dicomRtImports) ? state.dicomRtImports : []), payload.import];
        renderDicomRTImportStatus(state.dicomRtImports);
        showBrachyBotNotice(
            _dicomRtText('DICOM-RT 已导入；应用前请确认配准。', 'DICOM-RT imported; confirm registration before use.'),
            'success',
        );
        reportUIEvent('dicom_rt.import', payload.import?.modality || 'DICOM-RT', {
            filename: payload.import?.filename || file.name,
            clinical_status: payload.clinical_status,
        });
    } catch (error) {
        if (isCurrentOwner() && status) {
            status.hidden = false;
            status.className = 'dicom-rt-status is-error';
            status.textContent = _dicomRtText(`导入失败：${error.message || error}`, `Import failed: ${error.message || error}`);
        }
        if (isCurrentOwner()) showBrachyBotNotice(error.message || String(error), 'error', 8000);
    } finally {
        if (isCurrentOwner()) {
            if (button) button.disabled = false;
            input.value = '';
        }
    }
}
window.handleDicomRTImport = handleDicomRTImport;
window.refreshDicomRTImportStatus = refreshDicomRTImportStatus;
window.addEventListener('i18nchange', () => {
    renderDicomRTImportStatus(state.dicomRtImports || [], { silent: true });
});

// Keep the manual selector synchronized with a tumor site identified by the
// agent. Unsupported sites intentionally do not get mapped to a model: the
// user must provide a CTV mask before planning can proceed.
function _syncTumorTypeSelectorAppearanceLegacy() {
    const select = document.getElementById('ctvModelSelect');
    if (!select) return;
    const selected = select.options[select.selectedIndex];
    const available = selected?.dataset?.availability === 'available';
    select.classList.toggle('tumor-type-unavailable', !available);
    select.classList.toggle('tumor-type-available', available);
    // Native option styling is constrained by some operating systems, but
    // these colors are honored by Chromium and retain a textual fallback in
    // the help line for platforms that use a system-owned select menu.
    Array.from(select.options).forEach(option => {
        const optionAvailable = option.dataset.availability === 'available';
        option.style.color = optionAvailable ? '#4ade80' : '#fb7185';
        option.style.fontWeight = optionAvailable ? '600' : '500';
    });

    const help = document.getElementById('ctvModelHelp');
    if (help) {
        const zh = available
            ? '绿色肿瘤类型可直接自动分割。'
            : '红色肿瘤类型暂不可直接自动分割；请上传匹配的 CTV mask 后再规划。';
        const en = available
            ? 'Green tumor types can be segmented automatically.'
            : 'Red tumor types require an uploaded matching CTV mask before planning.';
        help.dataset.i18nZh = zh;
        help.dataset.i18nEn = en;
        help.textContent = typeof window._t === 'function' ? window._t(zh, en) : en;
    }
}

function _syncTumorTypeSelectorAppearance() {
    const select = document.getElementById('ctvModelSelect');
    if (!select) return;
    const selected = select.options[select.selectedIndex];
    const capability = selected?.dataset?.capabilityState || 'disabled';
    // The user-facing distinction is operational availability, not the
    // research/verified maturity label. Experimental BiomedParse routes are
    // green when callable; missing runtimes and disabled routes are red.
    const callable = selected?.dataset?.callable === 'true'
        || capability === 'verified'
        // The validated pancreatic route gets an immediate green bootstrap
        // state; the async probe can still downgrade it if this runtime is
        // missing the model resource.
        || (capability === 'loading' && selected?.value === 'nnunet_pancreatic');
    ['available', 'unavailable', 'verified', 'experimental', 'disabled'].forEach(name => {
        select.classList.remove(`tumor-type-${name}`);
    });
    select.classList.add(callable ? 'tumor-type-available' : 'tumor-type-unavailable');
    Array.from(select.options).forEach(option => {
        const stateName = option.dataset.capabilityState || 'disabled';
        const optionCallable = option.dataset.callable === 'true'
            || stateName === 'verified'
            || (stateName === 'loading' && option.value === 'nnunet_pancreatic');
        option.style.color = optionCallable ? '#4ade80' : '#fb7185';
        option.style.fontWeight = optionCallable ? '600' : '500';
        option.title = option.dataset.capabilityReason || '';
    });

    const help = document.getElementById('ctvModelHelp');
    if (help) {
        const labels = {
            verified: ['已验证可用', 'Verified and available'],
            experimental: ['已接入，待进一步验证', 'Integrated; further validation required'],
            unavailable: ['当前环境不可用', 'Unavailable in this runtime'],
            disabled: ['尚未接入或暂未开放', 'Not integrated or not enabled'],
        };
        const pair = labels[capability] || labels.disabled;
        const reason = selected?.dataset?.capabilityReason || '';
        const zh = `${pair[0]}。${reason}`;
        const en = `${pair[1]}. ${reason}`;
        help.dataset.state = capability;
        help.dataset.i18nZh = zh;
        help.dataset.i18nEn = en;
        help.textContent = typeof window._t === 'function' ? window._t(zh, en) : en;
    }
    const ctvPath = document.getElementById('ctvPath')?.value?.trim();
    const stepButton = document.getElementById('stepBtn_ctv_segmentation');
    if (stepButton) {
        stepButton.dataset.modelCallable = callable ? 'true' : 'false';
        if (!callable && !ctvPath) {
            stepButton.title = selected?.dataset?.capabilityReason || 'Upload a matching CTV mask.';
        }
    }
}

async function refreshTumorTypeAvailability() {
    const select = document.getElementById('ctvModelSelect');
    if (!select) return;
    // Paint the deterministic two-state fallback before the asynchronous
    // capability probe resolves, so startup never exposes an unstyled third
    // state in the native menu.
    _syncTumorTypeSelectorAppearance();
    try {
        // Include the optional research catalog so a configured BiomedParse
        // runtime can mark the corresponding tumor type as actionable. The
        // catalog is not rendered as model-brand text in the selector.
        const response = await fetch(API + '/ctv/models?include_experimental=1', {
            credentials: 'same-origin',
        });
        const payload = await response.json();
        if (!response.ok || !payload?.success) throw new Error(payload?.error || `HTTP ${response.status}`);
        const capabilities = new Map();
        (payload.models || []).forEach(model => {
            const type = String(model.tumor_type || '');
            if (!type) return;
            // A model is selectable automatically only when its required
            // local resource is present. Manual CTV import remains available
            // for every tumor type, so unavailable options stay selectable.
            // An optional site is automatically actionable when its local
            // model exists or its explicitly configured BiomedParse research
            // fallback is available. The server still preserves provenance
            // and blocks empty/failed candidates.
            capabilities.set(type, {
                state: String(model.capability_state || 'disabled'),
                callable: !!model.callable,
                reason: String(model.capability_reason || ''),
                technical: !!model.technical_call_chain_passed,
                spatial: !!model.space_alignment_passed,
                clinical: !!model.clinical_case_validation,
            });
        });
        Array.from(select.options).forEach(option => {
            const capability = capabilities.get(option.value);
            option.dataset.capabilityState = capability?.state || 'disabled';
            option.dataset.callable = capability?.callable ? 'true' : 'false';
            option.dataset.capabilityReason = capability?.reason || 'No registered runtime capability.';
            option.dataset.technicalValidation = capability?.technical ? 'passed' : 'not-run';
            option.dataset.spatialValidation = capability?.spatial ? 'passed' : 'not-run';
            option.dataset.clinicalValidation = capability?.clinical ? 'passed' : 'not-established';
        });
    } catch (error) {
        // Keep the server-rendered fallback rather than disabling the manual
        // workflow when an availability probe is temporarily unavailable.
        console.warn('[CTV] tumor type availability probe failed:', error);
    }
    _syncTumorTypeSelectorAppearance();
}

function updateTumorTypeSelector(value) {
    const raw = String(value || '').trim();
    if (!raw) return false;
    const aliases = {
        pancreas: 'nnunet_pancreatic', pancreatic: 'nnunet_pancreatic',
        liver: 'totalsegmentator_liver_tumor', kidney: 'biomedparse_kidney_lesion',
        lung: 'biomedparse_lung_lesion', colon: 'biomedparse_colon_primary',
        prostate: 'prostate_tumor',
        'head and neck': 'biomedparse_head_neck_cancer', head_neck: 'biomedparse_head_neck_cancer',
        '胰腺': 'nnunet_pancreatic', '胰脏': 'nnunet_pancreatic',
        '肝': 'totalsegmentator_liver_tumor', '肝脏': 'totalsegmentator_liver_tumor',
        '肾': 'biomedparse_kidney_lesion', '肾脏': 'biomedparse_kidney_lesion',
        '肺': 'biomedparse_lung_lesion', '肺部': 'biomedparse_lung_lesion',
        '结肠': 'biomedparse_colon_primary', '结肠癌': 'biomedparse_colon_primary',
        '前列腺': 'prostate_tumor', '头颈': 'biomedparse_head_neck_cancer',
        '头颈部': 'biomedparse_head_neck_cancer', '头颈肿瘤': 'biomedparse_head_neck_cancer',
    };
    const key = aliases[raw.toLowerCase()] || raw.toLowerCase();
    const select = document.getElementById('ctvModelSelect');
    if (!select || !Array.from(select.options).some(option => option.value === key)) {
        const help = document.getElementById('ctvModelHelp');
        if (help) {
            const zh = `暂不支持“${raw}”的自动 CTV 分割；请上传匹配的 CTV mask 并手动确认剂量参数后再规划。`;
            const en = `Automatic CTV segmentation is not available for "${raw}". Upload a matching CTV mask and confirm dose parameters manually before planning.`;
            help.dataset.i18nZh = zh;
            help.dataset.i18nEn = en;
            help.textContent = typeof window._t === 'function' ? window._t(zh, en) : en;
        }
        return false;
    }
    select.value = key;
    select.dispatchEvent(new Event('change', { bubbles: true }));
    _syncTumorTypeSelectorAppearance();
    if (typeof scheduleWorkspaceSave === 'function') scheduleWorkspaceSave();
    return true;
}
window.updateTumorTypeSelector = updateTumorTypeSelector;
window.refreshTumorTypeAvailability = refreshTumorTypeAvailability;
window.addEventListener('i18nchange', _syncTumorTypeSelectorAppearance);
// The first probe intentionally runs before the auth overlay is resolved.
// Retry after session authentication (or deployment-key entry) so a 401 from
// that early probe cannot leave every optional tumor type red for the rest of
// the page lifetime.
window.addEventListener('brachybot:auth-ready', () => {
    void refreshTumorTypeAvailability();
});
window.addEventListener('brachybot:api-key-changed', () => {
    void refreshTumorTypeAvailability();
});
setTimeout(refreshTumorTypeAvailability, 0);

function clearViewerCanvases() {
    // Session switches invalidate every pending image callback. Without this
    // generation fence, an old case can repaint a canvas after the new case
    // has already been selected.
    window.__viewerRenderGeneration = (window.__viewerRenderGeneration || 0) + 1;
    if (typeof invalidateDoseOverlayRenderCache === 'function') invalidateDoseOverlayRenderCache();
    document.querySelectorAll(
        '[id^="sliceCanvas"], [id^="labelOverlay_"], [id^="doseOverlay_"], '
        + '[id^="doseOverlayCanvas"], [id^="contourCanvas"], [id^="seedsOverlayCanvas"], '
        + '[id^="crosshairCanvas"], [id^="annotationCanvas"]'
    ).forEach(canvas => {
        const ctx = canvas.getContext?.('2d');
        if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
        canvas.style.display = 'none';
        // Canvas elements survive a case change. Clear their presentation
        // transform as well as pixels so a late hydration cannot briefly show
        // a new CT beneath a dose/projection layer positioned for the old one.
        ['transform', 'transform-origin', 'left', 'top', 'width', 'height'].forEach(property => {
            canvas.style.removeProperty(property);
        });
        canvas._posSet = false;
        canvas._doseWrapper = null;
    });
    document.querySelectorAll('.viewer-no-data').forEach(el => { el.style.display = ''; });
    if (typeof hideContextMenu === 'function') hideContextMenu();
    return window.__viewerRenderGeneration;
}

/**
 * Reset all segmentation, planning, and data tree state when loading a new CT.
 * Must be called before loading new CT to clear stale data.
 */
function deferSceneResourceDisposal(resources) {
    if (!resources.length) return;
    // Removing old objects is required before the next case paints. GPU
    // disposal is deliberately deferred one frame so session switching is
    // responsive even when the previous case contains many meshes.
    const dispose = () => resources.forEach(resource => {
        try {
            resource?.traverse?.(node => {
                node.geometry?.dispose?.();
                const material = node.material;
                if (Array.isArray(material)) material.forEach(item => item?.dispose?.());
                else material?.dispose?.();
            });
            resource?.geometry?.dispose?.();
            const material = resource?.material;
            if (Array.isArray(material)) material.forEach(item => item?.dispose?.());
            else material?.dispose?.();
        } catch (error) {
            console.debug('[viewer] deferred resource disposal failed:', error);
        }
    });
    const schedule = () => setTimeout(dispose, 0);
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(schedule);
    else schedule();
}

function resetAllState(options = {}) {
    const deferredResources = options.deferDisposal ? [] : null;
    clearViewerCanvases();
    // Invalidate and cancel slice/overlay requests before a new CT can be
    // installed.  This matters when an upload replaces a short study while
    // the previous study still has slider requests in flight.
    try { if (typeof invalidateViewerDataLoads === 'function') invalidateViewerDataLoads(); } catch (_) {}
    if (state.slices) Object.assign(state.slices, { axial: 0, sagittal: 0, coronal: 0 });
    ['axial', 'sagittal', 'coronal'].forEach(axis => {
        const slider = document.getElementById('slider' + capitalize(axis));
        if (slider) slider.value = '0';
        const label = document.getElementById('sliceLabel' + capitalize(axis));
        if (label) label.textContent = '0';
    });
    // Clear segmentation data arrays
    ctvLabelData = null;
    oarLabelData = null;
    skinSurfaceData = null;
    skinSurfaceShape = null;
    labelColorLUT = {};
    ctvLabelColorLUT = {};
    oarLabelColorLUT = {};
    organMetaFromServer = {};
    window._ctvLabelMap = {};

    // Reset data tree state
    dataTreeState.ctv.loaded = false;
    dataTreeState.ctv.visible = true;
    dataTreeState.oar.loaded = false;
    dataTreeState.oar.visible = true;
    dataTreeState.skin.loaded = false;
    dataTreeState.skin.visible = true;
    dataTreeState.skin.visible2D = true;
    dataTreeState.skin.visible3D = true;
    dataTreeState.skin.status = 'not_generated';
    dataTreeState.skin.loading = false;
    dataTreeState.skin.error = null;
    dataTreeState.skin.voxelCount = 0;
    // The source belongs to the current case. Keeping it during a case reset
    // can make a fresh uploaded mask inherit the previous case's ontology.
    dataTreeState.oarSource = '';
    dataTreeState.organs = [];
    dataTreeState.ctvLabels = {};
    dataTreeState.expansionState = {};
    // Selection is case-scoped UI state. Clear it together with the tree so
    // an old Shift anchor cannot select or mutate rows in the next Session.
    try { window.resetDataTreeSelectionState?.(); } catch (_) {}
    dataTreeState.dose.loaded = false;
    dataTreeState.seeds.loaded = false;
    dataTreeState.needles.loaded = false;
    dataTreeState.planning.trajectories = [];
    dataTreeState.planning.trajectoriesLoaded = false;
    dataTreeState.planning.seeds = [];
    dataTreeState.planning.needles = [];
    dataTreeState.planning.doseLevels = [];
    dataTreeState.planning.meshes = [];
    dataTreeState.annotations = [];
    dataTreeState.exportArtifacts = [];
    if (typeof _dataTreeArtifactCatalogSession !== 'undefined') {
        _dataTreeArtifactCatalogSession = '';
    }
    if (typeof _dataTreeArtifactCatalogPromise !== 'undefined') {
        _dataTreeArtifactCatalogPromise = null;
    }
    state.annotations = [];

    // Manual/threshold masks are case data; clear them so a previous case's
    // masks cannot leak into a newly selected session.
    state.maskLabels = {};
    state.maskLabelCounter = 0;
    state.activeMaskId = null;

    // Prevent cross-session seed/needle contamination in 2D viewer
    state.seedsOverlay = null;

    // Reset the presentation preference marker with the case.  Without this
    // reset a previous case's explicit CT-only choice can suppress overlays
    // in a newly created case even though its masks are valid and loaded.
    if (state.viewerSettings) state.viewerSettings.userConfigured = false;

    // Clear 3D meshes
    if (typeof scene3D !== 'undefined' && scene3D.meshes) {
        Object.keys(scene3D.meshes).forEach(id => {
            const mesh = scene3D.meshes[id];
            if (mesh && mesh.parent) mesh.parent.remove(mesh);
            if (deferredResources) deferredResources.push(mesh);
            else {
                if (mesh && mesh.geometry) mesh.geometry.dispose();
                if (mesh && mesh.material) mesh.material.dispose();
            }
        });
        scene3D.meshes = {};
    }
    // Some legacy reconstruction paths keep the optional skin surface
    // outside scene3D.meshes. Remove it explicitly so a new case cannot
    // inherit an untracked surface from the previous case.
    if (typeof scene3D !== 'undefined' && scene3D.skinMesh) {
        try { scene3D.scene?.remove(scene3D.skinMesh); } catch (_) {}
        if (deferredResources) deferredResources.push(scene3D.skinMesh);
        else {
            try { scene3D.skinMesh.geometry?.dispose(); } catch (_) {}
            try { scene3D.skinMesh.material?.dispose(); } catch (_) {}
        }
        scene3D.skinMesh = null;
    }
    // Keep lights and the renderer, but remove any untracked renderable
    // objects left by an asynchronous reconstruction callback.
    if (typeof scene3D !== 'undefined' && scene3D.scene) {
        [...scene3D.scene.children].forEach(child => {
            if (!child.isLight) {
                scene3D.scene.remove(child);
                if (deferredResources) deferredResources.push(child);
                else {
                    try { child.traverse?.(node => { node.geometry?.dispose?.(); node.material?.dispose?.(); }); } catch (_) {}
                }
            }
        });
    }
    if (deferredResources) deferSceneResourceDisposal(deferredResources);

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
    // The persistent Progress dock and manual dose row live outside a normal
    // chat message.  Clear only their browser presentation while preserving
    // every server-side task so an old case cannot animate inside a new one.
    try { window.clearCaseScopedProgressPresentation?.(); } catch (_) {}
    try { window.clearManualDoseProgressPresentation?.(); } catch (_) {}
    try { window.clearManualWorkflowProgressPresentation?.(); } catch (_) {}
    try { window.cancelScheduledManualDoseRecompute?.(); } catch (_) {}
    // Invalidate asynchronous 3D mesh fetches before removing current-case
    // objects. A late response from the previous session may still complete,
    // but it is no longer allowed to add geometry to the new case.
    if (typeof invalidateSegmentationMeshPrewarm === 'function') {
        invalidateSegmentationMeshPrewarm();
    }
    if (typeof invalidatePlanningSceneLoads === 'function') {
        invalidatePlanningSceneLoads();
    }
    if (typeof invalidateViewer3DRequests === 'function') {
        invalidateViewer3DRequests();
    }
    if (typeof invalidateViewerDataLoads === 'function') {
        invalidateViewerDataLoads();
    }
    if (typeof invalidatePlanningRefresh === 'function') {
        invalidatePlanningRefresh();
    }
    if (typeof invalidateReportCapture === 'function') {
        invalidateReportCapture();
    }
    if (typeof window.invalidateSurgicalGuidePresentation === 'function') {
        // The guide is case-owned geometry. Removing its old WebGL mesh before
        // a workspace switch prevents it appearing briefly in a new case.
        window.invalidateSurgicalGuidePresentation();
    }
    // Geometry settings are case-owned input, just like CT/CTV/OAR paths.
    // Reset them before hydrating the next case so its default UI never shows
    // dimensions from a guide created in the previously selected session.
    if (typeof window.resetSurgicalGuideControls === 'function') {
        window.resetSurgicalGuideControls();
    }
    if (typeof clearDoseOverlayRuntime === 'function') {
        clearDoseOverlayRuntime();
    }
    const loading3D = document.getElementById('loading3D');
    if (loading3D) {
        loading3D.classList.remove('active');
        loading3D.setAttribute('aria-hidden', 'true');
    }
    resetAllState({ deferDisposal: options.deferDisposal === true });
    state.ctLoaded = false;
    state.ctPath = null;
    // Input paths are case-owned form state.  Clearing only the CT field left
    // CTV/OAR paths from the previous case visible in a newly created case,
    // even though the clinical arrays and viewer meshes had been removed.
    state.ctvPath = null;
    state.oarPath = null;
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
    state.seedsOverlay = null;
    state.dicomRtImports = [];
    // Manual workflow progress is case data. Drop the in-browser copy before
    // applying the next workspace snapshot so it cannot bleed into a session.
    window.__manualWorkspaceState = null;
    if (typeof volumeShape !== 'undefined') volumeShape = null;
    if (typeof volumeSpacing !== 'undefined') volumeSpacing = null;
    if (typeof updateSeeds === 'function') updateSeeds([]);
    if (typeof updateMetrics === 'function') updateMetrics({});
    if (typeof updateOARTable === 'function') updateOARTable({});
    const ctPathInput = document.getElementById('ctPath');
    if (ctPathInput) {
        ctPathInput.value = '';
        ctPathInput.disabled = false;
    }
    ['ctvPath', 'oarPath'].forEach(id => {
        const pathInput = document.getElementById(id);
        if (pathInput) {
            pathInput.value = '';
            pathInput.disabled = false;
        }
    });
    ['fileCT', 'fileCTV', 'fileOAR'].forEach(id => {
        const fileInput = document.getElementById(id);
        if (fileInput) fileInput.value = '';
    });
    renderDicomRTImportStatus([], { silent: true });
    const dvhEl = document.getElementById('dvhChart');
    if (dvhEl && typeof Plotly !== 'undefined' && Plotly.purge) {
        try { Plotly.purge(dvhEl); } catch (_) {}
    }
    if (typeof drawDVH === 'function') drawDVH._lastSig = null;
    const dvhPlaceholder = document.getElementById('dvhPlaceholder');
    if (dvhPlaceholder) dvhPlaceholder.style.display = '';
    document.querySelectorAll('.dose-colorbar').forEach(el => { el.style.display = 'none'; });
    document.querySelectorAll('.viewer-no-data').forEach(el => { el.style.display = ''; });
    const clinicalHost = document.getElementById('clinicalEvaluationContent');
    if (clinicalHost) {
        const text = typeof _t === 'function'
            ? _t('规划完成后此处显示详细评估', 'Detailed evaluation will appear here after planning completes.')
            : 'Detailed evaluation will appear here after planning completes.';
        clinicalHost.innerHTML = `<div style="color:var(--text-dim);font-style:italic;">${text}</div>`;
    }
    if (options.clearReport !== false && typeof _newEmptyReportForm === 'function') {
        window.reportForm = _newEmptyReportForm();
        // Report maps are Session-owned. Keeping these globals while the CT
        // workspace is cleared lets a delayed save attach the previous case's
        // Planning report to the newly selected Session.
        window.__reportWorkspaceByPlanning = {};
        window.__reportWorkspaceActivePlanningId = null;
        window.__reportWorkspaceSessionId = null;
        window.__reportWorkspaceAudit = [];
        window.__reportWorkspaceSnapshots = [];
        window._reportCollapsed = {};
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

async function pullHeaderInfo(ctPath, options = {}) {
    // Fetch /api/header/info for a CT path, stash tags into state + agent
    // memory proxies, and re-render the Analysis panel.
    // Idempotent: safe to call multiple times for the same path.
    if (!ctPath) return;
    const expectedSessionId = String(
        options.sessionId
        || state.sessionId
        || (typeof activeSessionId !== 'undefined' ? activeSessionId : '')
        || '',
    );
    const expectedPath = String(ctPath);
    const ownsResponse = () => {
        const selected = String(
            (typeof activeSessionId !== 'undefined' ? activeSessionId : '')
            || state.sessionId
            || '',
        );
        const hydrated = String(state.sessionId || '');
        return (!expectedSessionId || !selected || selected === expectedSessionId)
            && (!expectedSessionId || !hydrated || hydrated === expectedSessionId)
            && String(state.ctPath || '') === expectedPath;
    };
    try {
        const res = await fetch(API + '/header/info', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(expectedSessionId ? { 'X-BrachyBot-Session': expectedSessionId } : {}),
            },
            body: JSON.stringify({ ct_path: ctPath }),
        });
        if (!res.ok) return;
        const data = await res.json();
        if (!data.success || !ownsResponse()) return;
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

    const ownerSessionId = String(options.sessionId || _activeApiSessionId());

    // A new explicit CT upload invalidates cached CT + label volumes.
    if (!options.skipReset && ownerSessionId && window.SessionCache) {
        window.SessionCache.invalidateSession(ownerSessionId).catch(function(){});
    }

    const isCurrentOwner = () => ownerSessionId === String(_activeApiSessionId());
    const announce = options.announce !== false;
    const { overlay, progressText } = _uploadProgressElements('ctPath');
    const windowCenter = Number.isFinite(Number(options.windowCenter))
        ? Number(options.windowCenter)
        : Number(state.viewerSettings.level);
    const windowWidth = Number.isFinite(Number(options.windowWidth))
        ? Number(options.windowWidth)
        : Number(state.viewerSettings.window);

    if (isCurrentOwner()) {
        // Only the owning case may change the visible loading state. An
        // upload can finish after the user has already switched cases.
        if (progressText) progressText.textContent = 'Loading CT to viewers...';
        if (announce) addChat('system', 'Loading CT image to viewers...');
        if (!options.skipReset) resetAllState();
    }
    const renderGeneration = window.__viewerRenderGeneration || 0;

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
    // Skip all of this during session restore — the snapshot already
    // populated metrics and report via applyWorkspaceSnapshot.
    if (isCurrentOwner() && !options.skipReset) {
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
    }

    const loadCtrl = new AbortController();
    // A cold workspace may still be decoding its persisted CT in the server
    // worker.  Poll the lightweight gate instead of turning that normal state
    // into a misleading "Failed to load CT" error.
    const loadTimer = setTimeout(() => loadCtrl.abort(), Math.max(180000, Number(options.timeoutMs || 60000)));
    try {
        let data = null;
        for (let attempt = 0; attempt < 360; attempt += 1) {
            const res = await fetch(API + '/viewer/load', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-BrachyBot-Session': ownerSessionId,
                },
                body: JSON.stringify({
                    ct_path: ctPath,
                    window_center: windowCenter,
                    window_width: windowWidth,
                }),
                signal: loadCtrl.signal,
            });
            if (res.status === 202) {
                const pending = await res.json().catch(() => ({}));
                const waitMs = Math.max(100, Math.min(1000, Number(
                    pending.retry_after_ms || res.headers.get('Retry-After-Ms') || 250,
                )));
                await new Promise(resolve => setTimeout(resolve, waitMs));
                continue;
            }
            if (!res.ok) {
                // A just-uploaded CT can race a detached session hydration
                // worker.  The server now cancels stale publishes, but retain
                // a short retry for an in-flight request which started before
                // that cancellation was observed.
                if (res.status >= 500 && attempt < 2) {
                    await new Promise(resolve => setTimeout(resolve, 250 * (attempt + 1)));
                    continue;
                }
                const problem = await res.json().catch(() => ({}));
                const detail = String(problem.error || problem.message || '').trim();
                throw new Error(detail || `HTTP ${res.status}`);
            }
            data = await res.json();
            break;
        }
        if (!data) throw new Error('Case resources did not become ready before the restore timeout.');
        if (!isCurrentOwner()) return { ...data, background: true };
        if (renderGeneration !== window.__viewerRenderGeneration) return { ...data, stale: true };
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
            await loadVolumeData({ sessionId: ownerSessionId });
            if (!isCurrentOwner() || renderGeneration !== window.__viewerRenderGeneration) {
                return { ...data, stale: true };
            }
            state.ctLoaded = true;

            // Render initial slices from volume
            ['axial', 'sagittal', 'coronal'].forEach(axis => {
                renderSliceFromVolume(axis, state.slices[axis]);
            });

            // The canvases now contain decoded voxels, so bind navigation in
            // the same transaction. Deferring the only bind by 500 ms allowed
            // workspace/report work (or a quick tab change) to cancel the
            // practical double-click window after restart.
            if (typeof setupViewerInteractions === 'function') setupViewerInteractions();
            // Keep a delayed idempotent pass for layouts whose canvas size is
            // finalized by a subsequent ResizeObserver frame.
            setTimeout(() => {
                if (!isCurrentOwner() || renderGeneration !== window.__viewerRenderGeneration) return;
                setupViewerInteractions();
            }, 500);

            // Update data tree and load overlays if data exists
            renderDataTree();
            // Load overlays for all axes (will show nothing if no segmentation data)
            setTimeout(() => {
                if (!isCurrentOwner() || renderGeneration !== window.__viewerRenderGeneration) return;
                ['axial', 'sagittal', 'coronal'].forEach(axis => {
                    loadOverlay(axis, state.slices[axis]);
                });
            }, 100);

            const ctPathInput = document.getElementById('ctPath');
            if (ctPathInput) {
                ctPathInput.value = ctPath;
                // Programmatic uploads do not fire native input/change
                // events. Refresh manual-step prerequisites explicitly so
                // the CTV button becomes usable immediately after upload.
                ctPathInput.dispatchEvent(new Event('input', { bubbles: true }));
                ctPathInput.dispatchEvent(new Event('change', { bubbles: true }));
            }
            // A mask may have been selected before its CT. Import it only
            // when the current session has not already restored that mask.
            setTimeout(() => {
                if (!isCurrentOwner() || renderGeneration !== window.__viewerRenderGeneration) return;
                if (state.ctvPath && !dataTreeState.ctv.loaded) {
                    importUploadedMask('ctv', state.ctvPath, {
                        sessionId: ownerSessionId,
                        ctPath,
                    });
                }
                if (state.oarPath && !dataTreeState.oar.loaded) {
                    importUploadedMask('oar', state.oarPath, {
                        sessionId: ownerSessionId,
                        ctPath,
                    });
                }
            }, 0);
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
            pullHeaderInfo(ctPath, { sessionId: ownerSessionId });
        }
        return data;
    } catch (e) {
        if (isCurrentOwner()) {
            if (overlay) overlay.classList.remove('active');
            if (announce) addChat('error', 'Failed to load CT: ' + e.message);
            else console.warn('[session restore] Failed to restore CT:', e);
        }
        throw e;
    } finally {
        clearTimeout(loadTimer);
    }
}

function _statusFromWorkspaceSnapshot(workspace, sessionId) {
    const agent = workspace?.agent || {};
    const results = agent.planning_results || {};
    const controls = workspace?.ui?.state?.controls || workspace?.ui?.controls || {};
    const uiState = agent.ui_state || {};
    const value = (keys) => {
        for (const source of [results, uiState, controls]) {
            for (const key of keys) {
                const candidate = source?.[key];
                if (typeof candidate === 'string' && candidate.trim()) return candidate;
                if (candidate && typeof candidate === 'object' && typeof candidate.value === 'string' && candidate.value.trim()) {
                    return candidate.value;
                }
            }
        }
        return '';
    };
    const operation = workspace?.operation || {};
    return {
        session_id: String(sessionId || workspace?.session_id || ''),
        ct_path: value(['ct_path', 'ctPath', 'ct_image_path', 'ctImagePath']),
        ctv_path: value(['ctv_path', 'ctvPath', 'ctv_mask_path', 'ctvMaskPath']),
        oar_path: value(['oar_path', 'oarPath', 'oar_mask_path', 'oarMaskPath']),
        stored_keys: Object.keys(results),
        brain_available: false,
        runtime: agent.runtime_state || {},
        workspace: {
            revision: workspace?.session?.revision ?? workspace?.workspace?.revision ?? null,
            recovery_status: workspace?.session?.recovery_status || operation.state || 'ready',
        },
        lightweight: true,
    };
}

function _workspaceNeedsClinicalRestore(workspace, status) {
    // An authoritative empty workspace must win over any stale lightweight
    // status object left by the previous case. This is the key guard against
    // an empty New case inheriting the old case's loading spinner or paths.
    if (workspace && typeof workspace === 'object') {
        if (typeof window.workspaceSnapshotHasClinicalResources === 'function') {
            return window.workspaceSnapshotHasClinicalResources(workspace);
        }
        return Object.keys(workspace?.agent?.planning_results || {}).length > 0;
    }
    const candidate = status || {};
    return Boolean(
        String(candidate.ct_path || '').trim()
        || String(candidate.ctv_path || '').trim()
        || String(candidate.oar_path || '').trim()
        || (Array.isArray(candidate.stored_keys) && candidate.stored_keys.length)
    );
}

async function _restoreActiveSessionWorkspace(options = {}) {
    const sessionAtStart = _activeApiSessionId();
    const restoreStartedAt = typeof performance !== 'undefined' ? performance.now() : Date.now();
    const recordStage = (stage, startedAt, details = {}) => {
        if (typeof window.recordWorkspacePerformance === 'function') {
            window.recordWorkspacePerformance(stage, {
                sessionId: sessionAtStart,
                startedAt,
                details,
            });
        }
    };
    // Helper: yield to the browser's rendering pipeline so DOM mutations
    // painted before this yield become visible to the user.  Without this
    // the entire restore runs in one microtask and the user sees a frozen
    // loading spinner for seconds followed by everything appearing at once.
    const _yield = () => new Promise(r => {
        requestAnimationFrame(() => setTimeout(r, 0));
    });
    // The optimistic case shell already cleared the visible workspace before
    // scheduling background hydration. Clearing it again here can erase a
    // just-resumed execution trace for this same case.
    if (options.skipClientClear !== true) {
        clearClientWorkspace({ clearReport: options.clearReport !== false });
    }
    let workspace = options.workspace || window._activeWorkspaceSnapshot || null;
    const workspaceSessionId = (value) => String(value?.session_id || value?.session?.id || '');
    if (workspace && workspaceSessionId(workspace) !== sessionAtStart) workspace = null;
    if (!workspace) {
        const snapshotStartedAt = typeof performance !== 'undefined' ? performance.now() : Date.now();
        try {
            const wsCtrl = new AbortController();
            const wsTimer = setTimeout(function(){ wsCtrl.abort(); }, 15000);
            let workspaceResponse;
            try {
                workspaceResponse = await fetch(API + '/workspace/snapshot', {
                    headers: { 'X-BrachyBot-Session': sessionAtStart },
                    signal: wsCtrl.signal,
                });
            } finally { clearTimeout(wsTimer); }
            if (workspaceResponse.ok) {
                const candidate = (await workspaceResponse.json()).workspace || null;
                if (workspaceSessionId(candidate) === sessionAtStart) workspace = candidate;
            }
        } catch (error) { console.debug('[session restore] Workspace snapshot unavailable:', error); }
        recordStage('restore.snapshot', snapshotStartedAt, { available: !!workspace });
    }

    let status = options.status || null;
    // A supplied workspace snapshot already contains the compact paths and
    // artifact keys needed to start the viewer loaders. Do not call the heavy
    // /api/status endpoint here: that endpoint hydrates a full Agent and can
    // synchronously read CT/plan arrays before the UI becomes usable.
    if ((!status || status.session_id !== sessionAtStart) && workspace && options.background === true) {
        status = _statusFromWorkspaceSnapshot(workspace, sessionAtStart);
    }
    if (!status || status.session_id !== sessionAtStart) {
        const statusStartedAt = typeof performance !== 'undefined' ? performance.now() : Date.now();
        const stCtrl = new AbortController();
        const stTimer = setTimeout(function(){ stCtrl.abort(); }, 30000);
        let response;
        try {
            response = await fetch(API + '/status?lightweight=1', {
                headers: { 'X-BrachyBot-Session': sessionAtStart },
                signal: stCtrl.signal,
            });
        } finally { clearTimeout(stTimer); }
        if (!response.ok) throw new Error(`Session status failed: HTTP ${response.status}`);
        status = await response.json();
        recordStage('restore.status', statusStartedAt);
    }
    if (_activeApiSessionId() !== sessionAtStart) return null;

    state.sessionId = status.session_id || sessionAtStart;
    if (trainingMonitorState.sessionId !== sessionAtStart) {
        // Per-session monitor throttles are transient UI state. Reset them
        // on case switch so one case cannot suppress feedback in another.
        trainingMonitorState.lastFeedbackAt = 0;
        trainingMonitorState.lastScreenshotAt = 0;
    }
    state.brainAvailable = !!status.brain_available;
    const sessionDisplay = document.getElementById('sessionDisplay');
    if (sessionDisplay) sessionDisplay.textContent = state.sessionId;
    // DICOM-RT metadata is lightweight and case-scoped. Restore its summary
    // independently so it does not delay CT/mesh hydration or leak between
    // rapidly switched sessions.
    refreshDicomRTImportStatus({ sessionId: sessionAtStart, silent: true });

    // Training state belongs to the selected planning session as well. The
    // workspace snapshot already carries this state during background restore;
    // avoid a second request on the critical hydration path.
    let restoredTraining = {};
    if (!(options.background === true && workspace)) {
        try {
            const uiCtrl = new AbortController();
            const uiTimer = setTimeout(function(){ uiCtrl.abort(); }, 10000);
            let uiResponse;
            try {
                uiResponse = await fetch(API + '/ui/state', {
                    headers: { 'X-BrachyBot-Session': sessionAtStart },
                    signal: uiCtrl.signal,
                });
            } finally { clearTimeout(uiTimer); }
            if (uiResponse.ok && _activeApiSessionId() === sessionAtStart) {
                const uiData = await uiResponse.json();
                const training = uiData.training || {};
                restoredTraining = training;
                restoreTrainingMonitorSnapshot(training, sessionAtStart);
            }
        } catch (error) {
            console.debug('[session restore] UI state unavailable:', error);
        }
    } else {
        const training = workspace?.ui?.bridge?.training || workspace?.ui?.state?.training || {};
        restoredTraining = training;
        restoreTrainingMonitorSnapshot(training, sessionAtStart);
    }
    // A Finish Monitoring request may return after a session switch. The
    // server keeps the final summary on the case bridge, so restore it as a
    // normal case-owned chat message exactly once when this case is revisited.
    const persistedSummary = restoredTraining?.last_summary;
    if (persistedSummary?.content && typeof sessions !== 'undefined' && sessions[sessionAtStart]) {
        const summaryMessageId = String(persistedSummary.message_id || '');
        const alreadyPresent = (sessions[sessionAtStart].messages || []).some(message =>
            summaryMessageId && String(message?.id || '') === summaryMessageId
        );
        if (!alreadyPresent) {
            const rawSummaryTimestamp = Number(persistedSummary.completed_at || Date.now());
            const summaryTimestamp = rawSummaryTimestamp > 0 && rawSummaryTimestamp < 1e12
                ? rawSummaryTimestamp * 1000
                : rawSummaryTimestamp;
            addChat(
                'bot-response',
                String(persistedSummary.content),
                false,
                summaryTimestamp,
                false,
                sessionAtStart,
                {
                    requestId: persistedSummary.request_id || '',
                    messageId: summaryMessageId || `assistant-monitor-${Date.now()}-summary`,
                    messageKind: 'monitor_summary',
                    responseLanguage: persistedSummary.language || monitorConversationLanguage(sessionAtStart),
                },
            );
        }
    }

    const ctPath = String(status.ct_path || '').trim();
    const savedControls = workspace?.ui?.state?.controls || workspace?.ui?.controls || {};
    const savedAgentUi = workspace?.agent?.ui_state || {};
    const savedInputPath = (kind) => {
        const controlId = kind === 'ctv' ? 'ctvPath' : 'oarPath';
        return savedAgentUi[`${kind}_path`]
            || savedControls?.[controlId]?.value
            || '';
    };
    // Input paths are part of the durable case, not a generic browser form.
    // Restore them before CT hydration so a user-provided CTV/OAR mask can be
    // loaded when needed, and so the Input panel always describes the same
    // case as the viewer. The server owns these paths and validates them.
    const restoreCaseInputPath = (kind, value) => {
        const path = String(value || '').trim();
        const stateKey = kind === 'ctv' ? 'ctvPath' : 'oarPath';
        const inputId = kind === 'ctv' ? 'ctvPath' : 'oarPath';
        state[stateKey] = path || null;
        const input = document.getElementById(inputId);
        if (input) input.value = path;
    };
    restoreCaseInputPath('ctv', status.ctv_path || savedInputPath('ctv'));
    restoreCaseInputPath('oar', status.oar_path || savedInputPath('oar'));
    if (_activeApiSessionId() !== sessionAtStart) return null;
    if (!ctPath) {
        if (workspace && typeof applyWorkspaceSnapshot === 'function') {
            await applyWorkspaceSnapshot(workspace, {
                preserveClinicalData: true,
                // Switching restores chat/task presentation from the small
                // control-plane snapshot first. Do not create a competing
                // replay subscription during background resource hydration.
                skipChat: options.background === true,
            });
        }
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
        // Yield a frame so the chat, sidebar, and Input panel populate
        // visibly before heavy data begins.
        await _yield();
        return status;
    }

    // --- CT data exists: restore dependency layers in order ---
    // Labels and planning results depend on CT geometry held by the current
    // Agent. The shell remains responsive, but CT must hydrate first.
    resetAllState({ deferDisposal: true });
    // Let the reset paint before initiating network I/O.
    await _yield();

    let ctVolumeResult = null;
    let ctLoadError = null;
    const ctTask = (async () => {
        const ctStartedAt = typeof performance !== 'undefined' ? performance.now() : Date.now();
        try {
            ctVolumeResult = await loadCTToViewers(ctPath, {
                announce: false, sessionId: sessionAtStart, skipReset: true,
                timeoutMs: options.background === true ? 45000 : 60000,
            });
        } catch (e) {
            ctLoadError = e;
            console.warn('[session restore] CT load failed:', e);
        } finally {
            recordStage('restore.ct_first_paint', ctStartedAt, { loaded: !!state.ctLoaded });
        }
    })();

    const storedKeys = new Set(Array.isArray(status.stored_keys) ? status.stored_keys : []);
    // On a fresh server process the lightweight status endpoint can only see
    // the metadata shell while the Agent is decoding its durable sidecars.
    // The authenticated workspace snapshot already contains the authoritative
    // planning-result keys, so use both sources when deciding whether the
    // planning restore must run. Otherwise restart recovery restores CT/labels
    // but silently skips seeds, dose, DVH, and guide reconstruction.
    Object.keys(workspace?.agent?.planning_results || {}).forEach(key => storedKeys.add(String(key)));
    const hasPlanning = [
        'dose_metrics', 'dose_distribution', 'dose_distribution_gy',
        'seed_plan', 'seed_plan_serialized', 'manual_planning_preview',
    ].some(key => storedKeys.has(key))
        // A geometry-only draft has no dose/metrics keys by design, but it is
        // still a real Planning that must appear in the Data Tree after a
        // server restart. The compact registry and namespaced snapshots are
        // the durable source for this case.
        || storedKeys.has('planning_runs')
        || Array.from(storedKeys).some(key => String(key).startsWith('planning_run:'));

    // These tasks depend on the CT being present in the current Agent. They
    // are created after ctTask resolves below; starting them here races the
    // Agent hydration and can leave Data Tree/Planning empty.
    // CT is the base layer for every subsequent restore request.
    await ctTask;
    if (_activeApiSessionId() !== sessionAtStart) return null;
    // A restored Data Tree entry is not proof that the CT is usable. The old
    // path swallowed /viewer/load or /viewer/volume failures and continued to
    // labels/planning, then announced a fully interactive workspace with blank
    // canvases and no double-click handlers. Make decoded voxel state an
    // explicit transaction prerequisite instead.
    const expectedVoxelCount = Array.isArray(state.ctShape)
        ? state.ctShape.reduce((total, size) => total * Math.max(0, Number(size) || 0), 1)
        : 0;
    const decodedVoxelCount = (typeof volumeData !== 'undefined' && volumeData)
        ? Number(volumeData.length || 0)
        : 0;
    const ctReady = !ctLoadError
        && ctVolumeResult?.success === true
        && state.ctLoaded === true
        && expectedVoxelCount > 0
        && decodedVoxelCount === expectedVoxelCount;
    if (!ctReady) {
        state.ctLoaded = false;
        throw ctLoadError || new Error(
            `CT restore incomplete for session ${sessionAtStart}: expected ${expectedVoxelCount} voxels, decoded ${decodedVoxelCount}`,
        );
    }
    // Bind interactions synchronously once all three canvases have real voxel
    // data. The delayed load-time binding remains a resize fallback, but is no
    // longer the only opportunity to install double-click navigation.
    if (typeof setupViewerInteractions === 'function') setupViewerInteractions();
    await _yield();

    // Labels and planning results share the CT grid but are otherwise
    // independent restore products. Start both after CT is ready so OAR/CTV
    // reconstruction cannot disappear when a planning refresh is slow or
    // returns no dose payload.
    const labelsStartedAt = typeof performance !== 'undefined' ? performance.now() : Date.now();
    const labelTask = (typeof loadLabelVolumes === 'function')
        ? Promise.resolve(loadLabelVolumes({
            sessionId: sessionAtStart,
            preserveViewerState: true,
        })).finally(() => recordStage('restore.labels_data_tree', labelsStartedAt))
        : Promise.resolve();

    const planningStartedAt = typeof performance !== 'undefined' ? performance.now() : Date.now();
    const planningTask = (hasPlanning && typeof refreshPlanningUI === 'function')
        ? Promise.resolve(refreshPlanningUI({
            switchToViewers: false,
            sessionId: sessionAtStart,
            preserveViewerState: true,
            skipLabelLoad: true,
            backgroundRestore: options.background === true,
            retryPending: true,
            autoGenerateGuide: true,
        })).finally(() => recordStage('restore.planning_dvh', planningStartedAt))
        : Promise.resolve();

    // A segmentation-only case still needs real 3D objects. Planning refresh
    // also starts this loader, so only launch the independent path when no
    // Planning owns the reconstruction. The mesh work remains progressive and
    // does not block CT/2D interaction readiness.
    const segmentationMeshTask = labelTask.then(labelsLoaded => {
        if (!labelsLoaded || hasPlanning || typeof loadCTVAndObstacleMeshes !== 'function') return null;
        return loadCTVAndObstacleMeshes();
    });
    segmentationMeshTask.catch(error =>
        console.warn('[session restore] segmentation mesh reconstruction failed:', error));

    const restoreResults = await Promise.allSettled([labelTask, planningTask]);
    if (_activeApiSessionId() !== sessionAtStart) return null;
    const [labelResult, planningResult] = restoreResults;
    if (labelResult.status === 'rejected') throw labelResult.reason;
    if (planningResult.status === 'rejected') throw planningResult.reason;
    const expectsLabels = ['ctv_array', 'ctv_mask', 'oar_array'].some(key => storedKeys.has(key));
    if (expectsLabels && labelResult.value !== true) {
        throw new Error(`Segmentation restore did not produce label volumes for session ${sessionAtStart}`);
    }
    await _yield();

    // Clinical loaders create the current case's Data Tree entries after the
    // lightweight snapshot has painted. Reapply only presentation state now
    // that those entries exist; never replace their arrays, labels, geometry,
    // or coordinate metadata with a browser snapshot.
    if (workspace && typeof applyWorkspaceSnapshot === 'function') {
        await applyWorkspaceSnapshot(workspace, {
            preserveClinicalData: true,
            skipChat: true,
            skipTaskResume: true,
        });
        if (_activeApiSessionId() !== sessionAtStart) return null;
    }

    // --- manual state from stored keys ---
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
    if (_activeApiSessionId() !== sessionAtStart) return null;

    // Yield a frame so label volumes / dose meshes are painted before
    // the final snapshot merge and slice re-render.
    await _yield();

    if (workspace && typeof applyWorkspaceSnapshot === 'function') {
        const reportStartedAt = typeof performance !== 'undefined' ? performance.now() : Date.now();
        // The server has now reconstructed the authoritative CT, labels,
        // plan, dose and Data Tree. Reapply only display preferences; a full
        // snapshot merge here can overwrite freshly restored OAR metadata
        // with an older empty tree and blank Input paths.
        await applyWorkspaceSnapshot(workspace, { preserveClinicalData: true, skipChat: true });
        recordStage('restore.report_and_presentation', reportStartedAt);
    }
    // Re-render after the saved slice indices, visibility, and material state
    // have been applied.  This avoids a transient old-case frame on switch.
    ['axial', 'sagittal', 'coronal'].forEach(axis => {
        try { if (state.slices && Number.isFinite(Number(state.slices[axis]))) renderSliceFromVolume(axis, Number(state.slices[axis])); } catch (_) {}
    });
    // The final presentation snapshot may restore a saved pan/zoom after the
    // clinical loaders have already drawn their layers. Reconcile once at the
    // transaction boundary so CT, dose, contours, and planning projections
    // leave hydration with the same geometry instead of requiring Fit.
    if (typeof window.reconcile2DViewerLayers === 'function') {
        window.reconcile2DViewerLayers({
            reason: 'workspace-hydration-complete',
            rerender: true,
            immediate: true,
        });
    }
    if (typeof setupViewerInteractions === 'function') setupViewerInteractions();
    // The final restore barrier is the first point at which CT pixels,
    // dependent 2D layers, and planning meshes have all been requested for
    // the current case.  Fit every viewer here so restart/session hydration
    // has the same visible result as pressing Fit manually.
    if (typeof window.fitAllViewersAfterWorkspaceRestore === 'function') {
        try {
            await window.fitAllViewersAfterWorkspaceRestore({
                sessionId: sessionAtStart,
                reason: 'workspace-hydration-fit',
            });
        } catch (error) {
            console.warn('[session restore] automatic viewer fit failed:', error);
        }
    }
    recordStage('restore.fully_interactive', restoreStartedAt, {
        ct_loaded: !!state.ctLoaded,
        planning: hasPlanning,
    });
    return status;
}
async function restoreActiveSessionWorkspace(options = {}) {
    const sessionAtStart = String(_activeApiSessionId() || '');
    window.__workspaceHydrationRunId = (window.__workspaceHydrationRunId || 0) + 1;
    const hydrationRunId = window.__workspaceHydrationRunId;
    const hydrationScope = { sessionId: sessionAtStart, runId: hydrationRunId };
    const authoritativeWorkspace = options.workspace || window._activeWorkspaceSnapshot || null;
    if (authoritativeWorkspace && !_workspaceNeedsClinicalRestore(authoritativeWorkspace, options.status)) {
        console.debug('[session restore] skipped empty case', authoritativeWorkspace.session_id || authoritativeWorkspace.session?.id);
        window.setWorkspaceHydrationState?.(false, '', hydrationScope);
        return options.status || null;
    }
    // Show a small non-blocking status while the case is restored. Clinical
    // controls remain usable; heavy meshes and report figures may finish in
    // the background after the essential transcript and paths are visible.
    window.setWorkspaceHydrationState?.(
        true,
        typeof _t === 'function'
            ? _t('正在加载病例资源…', 'Loading case resources...')
            : 'Loading case resources...',
        hydrationScope,
    );
    // The workspace bridge owns the single loading presentation. Keep this
    // compatibility call after its older local wording so startup and a
    // session switch converge on the same lower-right notice.
    window.showCaseResourceLoading?.(hydrationScope);
    const slowNoticeTimer = setTimeout(() => {
        if (String(_activeApiSessionId() || '') !== sessionAtStart
            || window.__workspaceHydrationRunId !== hydrationRunId) return;
        const notice = document.getElementById('workspaceHydrationNotice');
        const message = document.getElementById('workspaceHydrationMessage');
        if (notice && message && !notice.hidden) {
            message.textContent = typeof _t === 'function'
                ? _t(
                    '病例资源仍在后台恢复，聊天和面板操作可以继续使用。',
                    'Case resources are still restoring in the background; chat and panels remain available.',
                )
                : 'Case resources are still restoring in the background; chat and panels remain available.';
        }
    }, 30000);
    try {
        return await _restoreActiveSessionWorkspace(options);
    } finally {
        clearTimeout(slowNoticeTimer);
        window.setWorkspaceHydrationState?.(false, '', hydrationScope);
    }
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

    // The authenticated server is the case-session source of truth.  Do not
    // render a localStorage transcript before the selected case is known.
    try {
        // Use the server-backed function explicitly.  The legacy chat script
        // still contains a localStorage-compatible loadSessions binding for
        // old embeds; calling it here would restore a different case than the
        // authenticated browser workspace.
        if (typeof window.loadSessions === 'function') await window.loadSessions();
        if (typeof renderSessionList === 'function') renderSessionList();
    } catch (e) { console.warn('Session init failed:', e); }

    // --- PRIORITY 1: Server init — run /status, /planning/clear, /config
    // There is intentionally no startup call to /planning/clear: an existing
    // durable case must be restored rather than reset by a browser refresh.
    let _statusData = null;
    // The full status route hydrates an Agent. Initialization must use the
    // compact control-plane contract so a browser refresh never blocks chat on
    // CT/NPY/GPU restoration.
    const _statusPromise = fetch(API + '/status?lightweight=1').then(async resp => {
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

    // Wait for /status (needed by UI below); config defaults are background-only.
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
    dataTreeState.oarSource = '';
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
        if (typeof _doseContourInflight !== 'undefined') _doseContourInflight.clear();
        if (typeof _doseContourPreloadTimers !== 'undefined') {
            _doseContourPreloadTimers.forEach(timer => clearTimeout(timer));
            _doseContourPreloadTimers.clear();
        }
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
    // Clinical state is restored from the authenticated workspace below.
    // New cases remain empty; existing cases rehydrate their own CT, masks,
    // planning arrays, Data Tree, viewer state, DVH, and report.
    // Load default hyperparameters from config
    await loadDefaultParams();

    // Do not hold initialization, chat input, or panel switching behind CT,
    // NPY, mesh, or report restoration. Loader callbacks are fenced by the
    // selected session, so a later switch cannot receive old data.
    // The initial shell must remain interactive while heavy CT/mesh restoration
    // runs in the background.  The session snapshot has already painted the
    // durable chat/control-plane state above, so waiting here only delays input.
    const authoritativeWorkspace = window._activeWorkspaceSnapshot || null;
    const restoreAlreadyScheduled = String(window.__workspaceRestoreScheduledSessionId || '') === String(activeSessionId || '')
        || String(window.__workspaceRestoreCompletedSessionId || '') === String(activeSessionId || '');
    if (_workspaceNeedsClinicalRestore(authoritativeWorkspace, _statusData) && !restoreAlreadyScheduled) {
        void restoreActiveSessionWorkspace({ status: _statusData, clearReport: true, background: true })
            .catch(error => {
                console.warn('Active session workspace restore failed:', error);
                if (typeof clearClientWorkspace === 'function') clearClientWorkspace({ clearReport: true });
            });
    } else {
        // A newly-created or deliberately empty case has nothing to hydrate.
        // Do not show a misleading Loading case resources notice or start a
        // cold Agent solely to prove that the case is empty.
        console.debug('[session restore] initial case has no clinical resources; hydration skipped');
        window.setWorkspaceHydrationState?.(false, '', { immediate: true });
    }
    if (typeof loadSessionChat === 'function' && activeSessionId) loadSessionChat(activeSessionId);
    syncUIBridgeState('init').catch(e => console.warn('Initial UI state sync failed:', e));

    // Persist reference-direction changes immediately. Chat requests may
    // start before the next general UI checkpoint, leaving a stale manual
    // vector beside a newly checked Auto box on the server.
    ['refDirecAuto', 'refDirecX', 'refDirecY', 'refDirecZ'].forEach(id => {
        const control = document.getElementById(id);
        if (!control || control.dataset.referenceDirectionSyncBound === '1') return;
        control.dataset.referenceDirectionSyncBound = '1';
        control.addEventListener('change', () => {
            syncUIBridgeState(`planning.${id}`).catch(() => {});
        });
    });

    // New workspaces open with 3D on top and all orthogonal 2D viewers below.
    // A persisted user choice is intentionally retained across session restores.
    setViewerLayout(state.viewerSettings.layout || '3d-top');

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
            banner.id = 'assetVersionNotice';
            banner.setAttribute('role', 'status');
            banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:#dc2626;color:white;padding:12px 20px;font-size:14px;text-align:center;font-family:system-ui;box-shadow:0 2px 8px rgba(0,0,0,0.2);';
            banner.innerHTML = '⚠️ 您的浏览器加载了 <b>旧版</b> BrachyBot 页面（' + reason + '）。请按 <kbd style="background:#fff;color:#dc2626;padding:2px 6px;border-radius:3px;font-family:monospace;">Ctrl+Shift+R</kbd>（Mac: <kbd style="background:#fff;color:#dc2626;padding:2px 6px;border-radius:3px;font-family:monospace;">Cmd+Shift+R</kbd>）强刷。';
            const close = document.createElement('button');
            close.type = 'button';
            close.textContent = 'x';
            close.setAttribute('aria-label', 'Dismiss outdated-page notice');
            close.title = 'Dismiss';
            close.style.cssText = 'position:absolute;right:10px;top:7px;width:28px;height:28px;border:0;border-radius:5px;background:rgba(255,255,255,.15);color:#fff;cursor:pointer;font-size:18px;line-height:1;';
            close.addEventListener('click', () => banner.remove());
            banner.appendChild(close);
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
        window.__doseModelScaleGy = Number(data.dose_scale_gy || DEFAULT_DOSE_MODEL_SCALE_GY);

        const d = data.defaults;
        const setVal = (id, val) => {
            const el = document.getElementById(id);
            if (el && val !== undefined && val !== null) el.value = val;
        };

        // Keep the manual selector aligned with the server-side default.
        // The value is a model identifier, not a translated display label.
        setVal('ctvModelSelect', d.tumor_type || 'nnunet_pancreatic');

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
            setVal(
                'inLowestEnergy',
                Number.isFinite(Number(p.in_lowest_dose_gy))
                    ? Number(p.in_lowest_dose_gy)
                    : planningDoseValueToGy(
                        p.in_lowest_energy,
                        p.dose_value_unit,
                        DEFAULT_PRESCRIPTION_GY
                    )
            );
            setVal(
                'outHighestEnergy',
                Number.isFinite(Number(p.out_highest_dose_gy))
                    ? Number(p.out_highest_dose_gy)
                    : planningDoseValueToGy(
                        p.out_highest_energy,
                        p.dose_value_unit,
                        DEFAULT_PRESCRIPTION_GY
                    )
            );
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
    if (!panel) return;
    const viewportSnapshot = typeof window.captureViewerViewport === 'function'
        ? window.captureViewerViewport(view)
        : null;

    if (card.classList.contains('fullscreen')) {
        // Restore
        card.classList.remove('fullscreen');
        panel.classList.remove('viewer-fullscreen-active');
        card.querySelector('.viewer-card-expand-btn').innerHTML = '&#9974;';
        // Restore only elements hidden by this fullscreen action. This keeps
        // intentional layout visibility state intact after the restore.
        panel.querySelectorAll('[data-fullscreen-hidden="1"]').forEach(el => {
            el.style.display = '';
            delete el.dataset.fullscreenHidden;
        });
        // Reset card inline styles
        card.style.position = ''; card.style.top = ''; card.style.left = '';
        card.style.right = ''; card.style.bottom = ''; card.style.zIndex = '';
        card.style.width = ''; card.style.height = ''; card.style.flex = '';
        if (typeof window.syncViewerGeometry === 'function') {
            window.syncViewerGeometry({ resetPositions: true, settleMs: 160, viewportSnapshot });
        }
    } else {
        // Enter fullscreen
        panel.classList.add('viewer-fullscreen-active');
        card.classList.add('fullscreen');
        card.querySelector('.viewer-card-expand-btn').innerHTML = '&#10006;';
        // Hide all siblings (handles both flat and .viewers-row layouts)
        Array.from(panel.children).forEach(c => {
            if (c !== card && !c.contains(card)) {
                c.style.display = 'none';
                c.dataset.fullscreenHidden = '1';
            }
        });
        panel.querySelectorAll('.viewers-row').forEach(row => {
            if (row.contains(card)) {
                // This row has the fullscreen card — hide sibling cards in this row
                Array.from(row.children).forEach(c => {
                    if (c !== card) {
                        c.style.display = 'none';
                        c.dataset.fullscreenHidden = '1';
                    }
                });
            } else {
                row.style.display = 'none';
                row.dataset.fullscreenHidden = '1';
            }
        });
        if (typeof window.syncViewerGeometry === 'function') {
            window.syncViewerGeometry({ resetPositions: true, settleMs: 160, viewportSnapshot });
        }
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
function _confirmAction(msgZh, msgEn, options = {}) {
    return new Promise(resolve => {
        const t = window._t || ((zh) => zh);
        const yesZh = options.yesZh || '确认';
        const yesEn = options.yesEn || 'Yes';
        const noZh = options.noZh || '取消';
        const noEn = options.noEn || 'Cancel';
        const titleZh = options.titleZh || '确认操作';
        const titleEn = options.titleEn || 'Confirm';
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
        // Callers can reuse this dialog for non-destructive decisions such as
        // confirming a replan after a geometry preview.
        const titleNode = overlay.firstElementChild?.children?.[1];
        if (titleNode && (options.titleZh || options.titleEn)) {
            titleNode.textContent = t(titleZh, titleEn);
        }
        const yesButton = overlay.querySelector('#_confirmYes');
        const noButton = overlay.querySelector('#_confirmNo');
        if (yesButton && (options.yesZh || options.yesEn)) {
            yesButton.textContent = t(yesZh, yesEn);
            yesButton.style.background = 'var(--primary)';
        }
        if (noButton && (options.noZh || options.noEn)) {
            noButton.textContent = t(noZh, noEn);
        }
        overlay.querySelector('#_confirmYes').onclick = () => { overlay.remove(); resolve(true); };
        overlay.querySelector('#_confirmNo').onclick = () => { overlay.remove(); resolve(false); };
        overlay.onclick = (e) => { if (e.target === overlay) { overlay.remove(); resolve(false); } };
    });
}

function _uiActionSessionIsCurrent(sessionId) {
    return !sessionId || String(sessionId) === String(_activeApiSessionId());
}

async function _executeUIAction(a, options = {}) {
    const ownerSessionId = String(options.sessionId || '');
    if (!_uiActionSessionIsCurrent(ownerSessionId)) {
        return { success: false, stale: true, error: 'The UI action belongs to another case.' };
    }
    const { target, command, value, requires_confirm } = a;
    if (requires_confirm) {
        const pairs = {
            'session.delete': [`确定要删除会话 ${value} 吗？此操作不可撤销。`, `Delete session ${value}? This cannot be undone.`],
            'session.clear_all': ['确定要清除浏览器本地显示缓存吗？服务端病例不会删除。', 'Clear browser display caches? Persistent server cases will be retained.'],
            'browser_cache.clear': ['确定要清除浏览器本地显示缓存吗？服务端病例不会删除。', 'Clear browser display caches? Persistent server cases will be retained.'],
            'plan.reset': ['确定要重置当前规划会话吗？所有规划数据将被清除。', 'Reset the current planning session? All data will be cleared.'],
            'report.clear': ['确定要清空报告数据吗？', 'Clear the report data?'],
            'chat.clear_history': ['确定要清空当前聊天记录吗？', 'Clear the current chat history?'],
        };
        const p = pairs[target] || [`确定要执行 ${target} 吗？`, `Execute ${target}?`];
        return _confirmAction(p[0], p[1]).then(ok => {
            if (!ok) return { success: false, cancelled: true };
            if (!_uiActionSessionIsCurrent(ownerSessionId)) {
                return { success: false, stale: true, error: 'The selected case changed before confirmation.' };
            }
            return Promise.resolve(_executeUIActionRaw(a, options));
        });
    }
    if (!_uiActionSessionIsCurrent(ownerSessionId)) {
        return { success: false, stale: true, error: 'The selected case changed before the UI action ran.' };
    }
    return Promise.resolve(_executeUIActionRaw(a, options));
}

function _emitUIActionProgress(step) {
    try {
        document.dispatchEvent(new CustomEvent('brachy:ui-action-progress', { detail: step }));
    } catch (_) { /* Progress reporting must never block a UI action. */ }
}

async function _executeUIActionsWithProgress(actions, options = {}) {
    const ownerSessionId = String(options.sessionId || '');
    const results = [];
    for (let i = 0; i < actions.length; i += 1) {
        if (!_uiActionSessionIsCurrent(ownerSessionId)) break;
        const action = actions[i] || {};
        const id = `ui-action-${Date.now()}-${i}`;
        const target = String(action.target || 'ui.control');
        const command = String(action.command || 'run');
        const base = {
            id,
            // The todo renderer treats assistant milestones as business
            // steps, while the tool trace still shows the exact target.
            type: 'assistant',
            title: `UI action: ${target} / ${command}`,
            tool: id,
            parent_tool: 'ui_controller',
            params: { target, command, value: action.value },
            session_id: ownerSessionId || _activeApiSessionId(),
        };
        _emitUIActionProgress({ ...base, status: 'pending', content: 'Applying UI action' });
        // Yield once so the live Execution Trace can paint its breathing state
        // before a synchronous control handler starts doing work.
        await new Promise(resolve => setTimeout(resolve, 0));
        try {
            const result = await _executeUIAction(action, { sessionId: ownerSessionId });
            if (!_uiActionSessionIsCurrent(ownerSessionId)) break;
            results.push(result);
            const failed = result === false
                || (result && (result.success === false || result.stale === true));
            if (failed) {
                const message = (result && result.error) || 'The browser could not apply this UI action.';
                _emitUIActionProgress({ ...base, status: 'error', result: message });
                break;
            }
            _emitUIActionProgress({
                ...base,
                status: result && result.cancelled ? 'cancelled' : 'done',
                result: result || 'Applied',
            });
            if (result && result.cancelled) break;
        } catch (error) {
            const failure = { success: false, error: String(error) };
            results.push(failure);
            _emitUIActionProgress({ ...base, status: 'error', result: failure.error });
            break;
        }
    }
    return results;
}
window._executeUIActionsWithProgress = _executeUIActionsWithProgress;

async function navigateToDosePeakSlices() {
    const peak = state?.doseOverlay?.peakVoxel;
    if (!peak) {
        const message = 'Dose peak is unavailable until a dose overlay has been calculated.';
        if (typeof addChat === 'function') addChat('error', message);
        return { success: false, error: message };
    }
    const requested = { axial: peak.z, sagittal: peak.x, coronal: peak.y };
    const updates = [];
    Object.entries(requested).forEach(([axis, rawValue]) => {
        const slider = document.getElementById('slider' + capitalize(axis));
        if (!slider) return;
        const max = Number.parseInt(slider.max, 10);
        const value = Math.max(0, Math.min(Number.isFinite(max) ? max : Number(rawValue), Math.round(Number(rawValue) || 0)));
        slider.value = String(value);
        updates.push(Promise.resolve(updateSlice(axis, value)));
    });
    await Promise.all(updates);
    if (typeof reportUIEvent === 'function') {
        reportUIEvent('viewer.dose_peak', 'Moved axial, sagittal, and coronal viewers to the dose peak', requested);
    }
    return { success: true, slices: requested };
}

async function _executeUIActionRaw(a, options = {}) {
    const ownerSessionId = String(options.sessionId || _activeApiSessionId());
    const { target, command, value } = a;
    try {
        if (target === 'ui.control') {
            return executeGenericUIControl(command, value);
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
            if (state.ctLoaded) return loadAllSlices();
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
            if (state.ctLoaded) return loadAllSlices();
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
        if (target === 'viewer.dose_peak' && command === 'run') {
            return navigateToDosePeakSlices();
        }
        if (target === 'viewer.transform') {
            const handlers = {
                flip_h: window.viewerFlipH,
                flip_v: window.viewerFlipV,
                rotate: window.viewerRotate,
                undo: window.viewerUndo,
                redo: window.viewerRedo,
                fit: window.fitView,
                reset: window.resetViewer,
            };
            const handler = handlers[command];
            if (typeof handler === 'function') return handler();
            return { success: false, error: `Viewer transform is unavailable: ${command}` };
        }
        if (target === 'viewer.tool') {
            setViewerTool(value);
            return;
        }
        // ── Manual / threshold masks ──
        if (target === 'mask.create') {
            if (typeof setViewerTool === 'function') setViewerTool('annotate');
            return;
        }
        if (target === 'mask.finalize') {
            if (typeof setViewerTool === 'function' && state.activeMaskId) setViewerTool('annotate');
            return;
        }
        if (target === 'mask.threshold') {
            const el = document.getElementById('viewerThreshold');
            if (el) { el.value = String(value); }
            if (typeof applyThreshold === 'function') applyThreshold();
            return;
        }
        if (target === 'mask.rename') {
            const cfg = _parseUIControlPayload(value);
            if (cfg && cfg.id && typeof renameDataTreeMask === 'function') {
                renameDataTreeMask(cfg.id, cfg.name);
            }
            return;
        }
        if (target === 'mask.move') {
            const cfg = _parseUIControlPayload(value);
            // Accept {"id":"mask_1","to":"ctv"} JSON, or a plain "ctv"/"oar"
            // (applies to the active mask).
            const cls = String(cfg?.to || cfg?.classification || (typeof value === 'string' && !value.startsWith('{') ? value : 'ctv')).toLowerCase();
            const id = cfg?.id || null;
            const targetCls = cls === 'oar' ? 'oar' : 'ctv';
            if (typeof moveSelectedMasks === 'function' && (id || state.activeMaskId)) {
                moveSelectedMasks(targetCls, id ? [String(id)] : null);
            }
            return;
        }
        if (target === 'mask.delete') {
            const cfg = _parseUIControlPayload(value);
            const id = cfg?.id || value || null;
            if (id && typeof deleteDataTreeMask === 'function') {
                deleteDataTreeMask(String(id));
            }
            return;
        }
        if (target === 'viewer.colorbar' || target === 'viewer.dose_scale') {
            if (command === 'reset') return resetDoseColorbarSettings();
            const cfg = _parseUIControlPayload(value);
            const scope = cfg.scope === 'threeD' ? 'threeD' : 'twoD';
            const scopeEl = document.getElementById('doseColorbarScope');
            const minEl = document.getElementById('doseColorbarMinInput');
            const maxEl = document.getElementById('doseColorbarMaxInput');
            const paletteEl = document.getElementById('doseColorbarPalette');
            if (scopeEl) scopeEl.value = scope;
            if (cfg.min !== undefined && minEl) minEl.value = cfg.min;
            if (cfg.minGy !== undefined && minEl) minEl.value = cfg.minGy;
            if (cfg.max !== undefined && maxEl) maxEl.value = cfg.max;
            if (cfg.maxGy !== undefined && maxEl) maxEl.value = cfg.maxGy;
            if (cfg.palette !== undefined && paletteEl) paletteEl.value = cfg.palette;
            return applyDoseColorbarSettings();
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
            slider.value = v;
            return updateSlice(axis, v);
        }
        // ── Layout ──
        if (target === 'layout') {
            setViewerLayout(value);
            return;
        }
        // ── Data tree ──
        if (target === 'data_tree') {
            if (command === 'expand_all') {
                if (typeof window.setAllTreeGroupsExpansion === 'function') {
                    window.setAllTreeGroupsExpansion(true);
                }
            } else if (command === 'collapse_all') {
                if (typeof window.setAllTreeGroupsExpansion === 'function') {
                    window.setAllTreeGroupsExpansion(false);
                }
            } else {
                if (typeof window.setTreeGroupExpansion === 'function'
                    && (command === 'expand' || command === 'collapse')) {
                    window.setTreeGroupExpansion(value, command === 'expand');
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
            return reconstructOrgan3D(value);
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
                return reconstructOrgan3D('ctv');
            } else {
                // Hydrate the tree when a manual mask was uploaded before
                // label_volume finished loading. An empty client list used to
                // make this action silently do nothing.
                const hydrateOrgans = async () => {
                    if (typeof dataTreeState === 'undefined') return;
                    if (Array.isArray(dataTreeState.organs) && dataTreeState.organs.length) return;
                    try {
                        const response = await fetch(API + '/viewer/organs', {
                            headers: { 'X-BrachyBot-Session': ownerSessionId },
                        });
                        if (!response.ok) return;
                        const payload = await response.json();
                        if (!_uiActionSessionIsCurrent(ownerSessionId)) return;
                        if (payload.organs && typeof updateOrganList === 'function') {
                            updateOrganList(payload.organs, payload.oar_source || '');
                        }
                    } catch (error) {
                        console.warn('[viewer] OAR metadata hydration failed', error);
                    }
                };
                await hydrateOrgans();
                if (!_uiActionSessionIsCurrent(ownerSessionId)) {
                    return { success: false, stale: true, error: 'The selected case changed during reconstruction.' };
                }
                const organs = (dataTreeState && Array.isArray(dataTreeState.organs))
                    ? dataTreeState.organs.filter(o => {
                        if (value === 'non_traversable') return o.category === 'non_traversable';
                        if (value === 'traversable') return o.category === 'traversable';
                        return true;
                    })
                    : [];
                if (!organs.length) {
                    addChat('error', 'No OAR labels are available for 3D reconstruction');
                    return { success: false, error: 'No OAR labels are available for 3D reconstruction' };
                }
                // One malformed label must not prevent valid OAR meshes from
                // rendering; report partial completion to the caller.
                const results = await Promise.allSettled(
                    organs.map(o => reconstructOrgan3D(o.id, true))
                );
                const completed = results.filter(r => r.status === 'fulfilled').length;
                return { success: completed > 0, reconstructed: completed, total: organs.length };
            }
        }
        if (target === 'tree.dose.visibility') {
            if (state.doseOverlay) {
                state.doseOverlay.visible = value === 'on';
                if (state.ctLoaded) return loadAllSlices();
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
        if (target === 'session.new') return window.newChat();
        if (target === 'session.switch') return window.switchSession(value);
        if (target === 'session.rename') {
            const title = String(value || '').trim();
            if (!activeSessionId || !sessions[activeSessionId]) {
                return { success: false, error: 'No active case is available to rename.' };
            }
            if (!title) {
                return { success: false, error: 'A case title is required.' };
            }
            // Case metadata belongs to the durable session repository, not
            // the browser UI snapshot. Updating only `sessions` looked right
            // until refresh, then the server list restored the old title.
            if (typeof window.renameServerSession !== 'function') {
                return { success: false, error: 'Durable case renaming is unavailable.' };
            }
            return window.renameServerSession(activeSessionId, title)
                .then(() => {
                    if (sessions[activeSessionId]) sessions[activeSessionId].title = title;
                    renderSessionList();
                    return { success: true, title };
                })
                .catch(error => ({
                    success: false,
                    error: String(error?.message || error || 'Unable to rename the case.'),
                }));
        }
        if (target === 'session.delete') return window.deleteSession(value, { skipConfirm: true });
        if (target === 'session.clear_all' || target === 'browser_cache.clear') {
            // ``session.clear_all`` is a legacy alias. It has never deleted
            // durable cases; retain it only so older prompts cannot turn a
            // cache cleanup into a failed or misleading UI action.
            return clearLocalChatData({ skipConfirm: true });
        }
        // ── Case input file pickers ──
        if (target.startsWith('input.') && target.endsWith('.browse')) {
            const pickerIds = {
                'input.ct.browse': 'fileCT',
                'input.ctv.browse': 'fileCTV',
                'input.oar.browse': 'fileOAR',
                'input.dicom_rt.browse': 'fileDicomRT',
            };
            const picker = document.getElementById(pickerIds[target]);
            if (!picker) return { success: false, error: `File picker is unavailable: ${target}` };
            picker.click();
            return { success: true, target };
        }
        // ── Planning ──
        if (target === 'plan.run') {
            return runPlanning();
        }
        if (target === 'plan.run_manual_step') {
            const step = String(value || '').trim();
            if (step === 'ctv_segmentation' || step === 'oar_segmentation') {
                return runSegmentationStep(step);
            } else if (step) {
                return runPlanningStep(step);
            }
            return;
        }
        if (target === 'plan.reset') {
            return resetSession();
        }
        if (target === 'ui.state') {
            return Promise.resolve(syncUIBridgeState(command || 'ui_controller')).then(() => {
                if (typeof addChat === 'function') {
                    addChat('system', monitorChatText('界面状态已同步。', 'UI state synchronized.'));
                }
                return { success: true };
            });
        }
        if (target === 'ui.catalog') {
            const schema = (typeof collectParameterSchema === 'function') ? collectParameterSchema() : [];
            const compact = schema.map((p) => ({
                id: p.id,
                label: p.label,
                group: p.group,
                type: p.type,
                min: p.min, max: p.max, step: p.step,
                options: p.options,
                value: p.value,
            }));
            return { success: true, parameters: compact, count: compact.length,
                     message: `UI parameter catalog has ${compact.length} editable parameters.` };
        }
        if (target === 'parameter.catalog') {
            const schema = (typeof collectParameterSchema === 'function') ? collectParameterSchema() : [];
            return { success: true, parameters: schema, count: schema.length,
                     message: `Exposed ${schema.length} editable UI parameters.` };
        }
        if (target === 'parameter.set') {
            const cfg = _parseUIControlPayload(value);
            // Accept {"id":"seedRadius","value":0.5}, or JSON array of such entries.
            if (Array.isArray(cfg)) {
                let applied = 0;
                cfg.forEach((entry) => { if (applyParameterSet(entry)) applied++; });
                return { success: true, applied, message: `Applied ${applied} parameter(s).` };
            }
            if (cfg && cfg.id) {
                const ok = applyParameterSet(cfg);
                return ok ? { success: true, applied: 1, message: `Set ${cfg.id} = ${cfg.value}.` }
                          : { success: false, error: `Parameter control not found: ${cfg.id}` };
            }
            return { success: false, error: 'parameter.set needs JSON {"id":"<control>","value":<value>}' };
        }
        if (target === 'planning.hyperparams.set') {
            const cfg = _parseUIControlPayload(value);
            const values = cfg && typeof cfg === 'object' && !Array.isArray(cfg)
                ? cfg
                : (typeof value === 'string' && !value.startsWith('{') ? {} : cfg || {});
            let applied = 0;
            for (const [id, v] of Object.entries(values)) {
                if (applyParameterSet({ id, value: v })) applied++;
            }
            if (applied > 0 && typeof applyHyperparams === 'function') applyHyperparams();
            return { success: true, applied,
                     message: `Set ${applied} hyperparameter(s) and applied them to the planner.` };
        }
        if (target === 'surgical_guide.parameters.set') {
            const cfg = _parseUIControlPayload(value);
            const values = cfg && typeof cfg === 'object' && !Array.isArray(cfg)
                ? cfg
                : (typeof value === 'string' && !value.startsWith('{') ? {} : cfg || {});
            // Map service-side radius fields to the UI diameter controls, and
            // the service-side parameter names to the panel control ids.
            const RADIUS_TO_DIAMETER = {
                channel_radius_mm: 'guideChannelDiameter',
                sleeve_outer_radius_mm: 'guideSleeveOuterDiameter',
            };
            const PARAM_TO_CONTROL = {
                skin_threshold_hu: 'guideSkinThreshold',
                skin_clearance_mm: 'guideSkinClearance',
                plate_thickness_mm: 'guidePlateThickness',
                patch_margin_mm: 'guidePatchMargin',
                channel_diameter_mm: 'guideChannelDiameter',
                channel_radius_mm: 'guideChannelDiameter',
                sleeve_outer_diameter_mm: 'guideSleeveOuterDiameter',
                sleeve_outer_radius_mm: 'guideSleeveOuterDiameter',
                sleeve_outward_mm: 'guideSleeveOutward',
                sleeve_inward_mm: 'guideSleeveInward',
                geometry_resolution_mm: 'guideGeometryResolution',
            };
            let applied = 0;
            for (const [key, raw] of Object.entries(values)) {
                let id = PARAM_TO_CONTROL[key] || key;
                let v = raw;
                if (RADIUS_TO_DIAMETER[key] && raw !== undefined && raw !== null) v = Number(raw) * 2;
                if (applyParameterSet({ id, value: v })) applied++;
            }
            if (applied > 0 && typeof window.scheduleWorkspaceSave === 'function') {
                window.scheduleWorkspaceSave('surgical_guide.parameters');
            }
            return { success: true, applied,
                     message: `Set ${applied} puncture-guide parameter(s). They take effect on the next "Generate guide".` };
        }
        if (target === 'tree.color') {
            const cfg = _parseUIControlPayload(value);
            const id = cfg && cfg.id;
            const color = cfg && (cfg.color || cfg.value);
            if (!id || !color) return { success: false, error: 'tree.color needs JSON {"id":"...","color":"#rrggbb"}' };
            if (typeof setDataTreeItemColor === 'function') {
                const ok = setDataTreeItemColor(id, color);
                return ok ? { success: true, message: `Set color of ${id} to ${color}.` }
                          : { success: false, error: `Data-tree node not found or bad color: ${id}` };
            }
            return { success: false, error: 'Color control is unavailable.' };
        }
        if (target === 'report.field.set') {
            const cfg = _parseUIControlPayload(value);
            const key = cfg && cfg.key;
            const v = cfg && (cfg.value !== undefined ? cfg.value : cfg.text);
            if (!key) return { success: false, error: 'report.field.set needs JSON {"key":"...","value":...}' };
            const el = document.getElementById('rf-' + String(key).replace(/[^a-zA-Z0-9_]/g, '_'));
            if (!el) { return { success: false, error: `Report field not found: ${key}` }; }
            if ('checked' in el && (el.type === 'checkbox' || el.type === 'radio')) el.checked = !!v;
            else if ('value' in el) el.value = v === undefined || v === null ? '' : String(v);
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            if (typeof onReportFieldEdit === 'function') onReportFieldEdit(key);
            if (typeof _scheduleReportAutoSave === 'function') _scheduleReportAutoSave();
            return { success: true, message: `Set report field ${key}.` };
        }
        if (target === 'report.template.set') {
            const sel = document.getElementById('reportTemplateSelect');
            if (!sel) return { success: false, error: 'Report template selector is unavailable.' };
            sel.value = String(value || '');
            sel.dispatchEvent(new Event('change', { bubbles: true }));
            if (typeof applyReportTemplate === 'function') applyReportTemplate();
            return { success: true, message: `Report template set to ${value}.` };
        }
        if (target === 'planning.parameter') {
            return executeGenericUIControl('set', value);
        }
        if (target === 'training.mode') {
            if (command === 'start') return startTrainingMode(value || 'Monitor planning workflow')
                .then(result => result || ({ success: false, error: 'Training monitor did not start.' }));
            else if (command === 'stop') return stopTrainingMode()
                .then(result => result || ({ success: false, error: 'Training monitor did not stop.' }));
            else if (command === 'advice') return requestPlanningAdvice()
                .then(result => result || ({ success: false, error: 'Planning advice is unavailable.' }));
            else if (typeof addChat === 'function') {
                addChat(
                    'system',
                    trainingMonitorState.active
                        ? monitorChatText('监测模式正在运行。', 'Monitor mode is active.')
                        : monitorChatText('监测模式未启用。', 'Monitor mode is not active.')
                );
            }
            return;
        }
        if (target === 'manual.needle.create') {
            return addManualNeedle();
        }
        if (target === 'manual.needle.endpoint') {
            if (typeof moveManualNeedleEndpointFromUi !== 'function') {
                return { success: false, error: 'Manual needle editing is unavailable before the 3D viewer initializes.' };
            }
            return moveManualNeedleEndpointFromUi(value);
        }
        if (target === 'manual.seed.add') {
            return addManualSeed();
        }
        if (target === 'manual.seed.position') {
            if (typeof moveManualSeedFromUi !== 'function') {
                return { success: false, error: 'Manual seed editing is unavailable before the 3D viewer initializes.' };
            }
            return moveManualSeedFromUi(value);
        }
        if (target === 'manual.dose.recompute') {
            return recomputeManualDose(value || 'ui_controller');
        }
        if (target === 'manual.plan.replan') {
            return replanManualPlan();
        }
        if (target === 'manual.plan.finish') {
            return requestPlanningAdvice();
        }
        if (target === 'system.readiness') {
            return checkSystemReadiness()
                .then(result => result || ({ success: false, error: 'System readiness is unavailable.' }));
        }
        // ── Report ──
        if (target === 'report.autofill') {
            if (typeof Report !== 'undefined' && Report.autoFill) {
                return Report.autoFill.fromAll({ sessionId: ownerSessionId });
            }
            if (typeof reportAutoFill === 'function') return reportAutoFill();
            return { success: false, error: 'Report auto-fill is unavailable.' };
        }
        if (target === 'report.export') {
            if (typeof Report !== 'undefined' && Report.export) {
                const fn = Report.export[value];
                if (fn) return fn();
            }
            return { success: false, error: 'The requested report export is unavailable.' };
        }
        if (target === 'report.import') {
            if (typeof Report !== 'undefined' && Report.persist) return Report.persist.importJSON();
            return { success: false, error: 'Report import is unavailable.' };
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
        if (target === 'report.review.open') {
            if (typeof Report !== 'undefined' && Report.review) Report.review.openModal();
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
            return reconstructOrgan3D(value);
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
            return setDoseTextureMode(on);
        }
        if (target === '3d.mesh_opacity') {
            const slider = document.getElementById('meshOpacity3D');
            if (!slider) return { success: false, error: '3D mesh opacity control is unavailable' };
            let next = Number(slider.value || 70);
            if (command === 'increase') next += Number(value || 10);
            else if (command === 'decrease') next -= Number(value || 10);
            else next = Number(value);
            next = Math.max(Number(slider.min || 0), Math.min(Number(slider.max || 100), next));
            slider.value = String(next);
            return update3DMeshOpacity(next);
        }
        if (target === '3d.labels') {
            const checkbox = document.getElementById('labelShow3d');
            const on = value === 'on' || (value === undefined && !checkbox?.checked);
            if (checkbox) checkbox.checked = on;
            return updateLabelImage('3d');
        }
        if (target === '3d.label_opacity') {
            const slider = document.getElementById('labelOp3d');
            if (!slider) return { success: false, error: '3D label opacity control is unavailable' };
            let next = Number(slider.value || 70);
            if (command === 'increase') next += Number(value || 10);
            else if (command === 'decrease') next -= Number(value || 10);
            else next = Number(value);
            next = Math.max(Number(slider.min || 0), Math.min(Number(slider.max || 100), next));
            slider.value = String(next);
            return updateLabelImage('3d');
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
            return clearCurrentChatHistory({ skipConfirm: true });
        }
        if (target === 'chat.sidebar.toggle') { toggleSessionSidebar(); return; }
        // ── Screenshot ──
        if (target === 'screenshot') {
            return _captureScreenshot(value);
        }
        // ── Tools ──
        if (target === 'tool') { setViewerTool(value); return; }
        return { success: false, error: `No browser dispatcher is available for ${target}.` };
    } catch (e) {
        console.warn('[UIAction] Error executing:', target, command, value, e);
        return { success: false, error: String(e && e.message ? e.message : e) };
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
    close.title = typeof window._t === 'function'
        ? window._t('关闭图片', 'Close image')
        : 'Close image';
    close.addEventListener('click', () => overlay.remove());
    const image = document.createElement('img');
    image.src = url;
    image.alt = label || 'Screenshot';
    image.addEventListener('click', event => event.stopPropagation());
    const info = document.createElement('div');
    info.className = 'image-modal-info';
    info.textContent = total > 1
        ? `${label || (typeof window._t === 'function' ? window._t('截图', 'Screenshot') : 'Screenshot')} · ${index + 1}/${total}`
        : (label || 'Screenshot');
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

function _localizedScreenshotTargetLabelLegacy(target) {
    const labels = {
        'viewer-axial': ['轴位', 'Axial'],
        'viewer-sagittal': ['矢状位', 'Sagittal'],
        'viewer-coronal': ['冠状位', 'Coronal'],
        'viewer-3d': ['三维查看器', '3D viewer'],
        'dose-overview': ['剂量总览', 'Dose overview'],
        'dvh': ['DVH 曲线', 'DVH'],
        'data-tree': ['数据树', 'Data Tree'],
    };
    const pair = labels[target] || [target || '截图', target || 'Screenshot'];
    const language = typeof window.conversationLanguageForSession === 'function'
        ? window.conversationLanguageForSession(_activeApiSessionId())
        : (window._i18nLang || 'en');
    return language === 'zh' ? pair[0] : pair[1];
}

function _appendScreenshotToGalleryLegacy(url, target, question, galleryContext) {
    const context = galleryContext || {};
    const messages = document.getElementById('chatMessages');
    if (!messages || !url) return;
    const label = _localizedScreenshotTargetLabelLegacy(target);
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
        title.textContent = typeof window.chatTranslate === 'function'
            ? window.chatTranslate('截图', 'Screenshots', _activeApiSessionId())
            : 'Screenshots';
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
    item.title = typeof window.chatTranslate === 'function'
        ? window.chatTranslate('打开截图', 'Open screenshot', _activeApiSessionId())
        : 'Open screenshot';
    const image = document.createElement('img');
    image.className = 'chat-screenshot';
    image.src = url;
    image.alt = target || 'Screenshot';
    const zoom = document.createElement('span');
    zoom.className = 'chat-image-zoom-icon';
    zoom.textContent = typeof window.chatTranslate === 'function'
        ? window.chatTranslate('打开', 'Open', _activeApiSessionId())
        : 'Open';
    const caption = document.createElement('span');
    caption.className = 'chat-image-caption';
    caption.textContent = label;
    item.append(image, zoom, caption);
    context.element.appendChild(item);
    context.items.push({ url, label, question: question || '' });
    const galleryTitle = typeof window.chatTranslate === 'function'
        ? window.chatTranslate('截图', 'Screenshots', _activeApiSessionId())
        : 'Screenshots';
    context.title.textContent = `${galleryTitle} (${context.items.length})`;
    item.addEventListener('click', () => {
        const index = context.items.findIndex(entry => entry.url === url && entry.label === label);
        _openScreenshotModal(url, question || target || 'Screenshot', Math.max(0, index), context.items.length);
    });
    scrollToBottom();
}

function _activeScreenshotPanel() {
    return document.querySelector('.panel-tab.active')?.dataset?.panel || null;
}

function _restoreScreenshotPanel(panelName) {
    if (!panelName || typeof switchPanel !== 'function') return false;
    const tab = document.querySelector(`.panel-tab[data-panel="${panelName}"]`);
    if (!tab || tab.classList.contains('active')) return false;
    switchPanel(panelName, tab);
    return true;
}

// Intercept ui_screenshot: capture the target element, upload to server,
// and display the image in the chat. This bridges the gap between the
// LLM's ui_screenshot tool call and the frontend's actual capture.
async function _interceptScreenshotLegacy(target, question, galleryContext, options = {}) {
    // Older cached callers retain this name. Route all of them through the
    // structured executor so the owning reply, Session checks, viewer-state
    // restoration, and localized failure handling cannot diverge.
    return _interceptScreenshot(target, question, galleryContext, options);
}

// Structured chat/Monitor screenshot executor. The earlier single-target
// implementation remains above for compatibility with old bundles, but this
// declaration intentionally supersedes it. Report figures continue to use the
// report subsystem and its fixed composition.
function _openScreenshotModal(url, label, index = 0, total = 1) {
    document.querySelector('.image-modal-overlay')?.remove();
    const language = _screenshotLanguage(_activeApiSessionId());
    const overlay = document.createElement('div');
    overlay.className = 'image-modal-overlay';
    overlay.addEventListener('click', event => {
        if (event.target === overlay) overlay.remove();
    });
    const close = document.createElement('button');
    close.className = 'image-modal-close';
    close.type = 'button';
    close.textContent = '\u00d7';
    close.title = language === 'zh' ? '\u5173\u95ed\u56fe\u7247' : 'Close image';
    close.addEventListener('click', () => overlay.remove());
    const image = document.createElement('img');
    image.src = url;
    image.alt = label || (language === 'zh' ? '\u622a\u56fe' : 'Screenshot');
    image.addEventListener('click', event => event.stopPropagation());
    const info = document.createElement('div');
    info.className = 'image-modal-info';
    const fallback = language === 'zh' ? '\u622a\u56fe' : 'Screenshot';
    info.textContent = total > 1
        ? `${label || fallback} \u00b7 ${index + 1}/${total}`
        : (label || fallback);
    overlay.append(close, image, info);
    document.body.appendChild(overlay);
    const onKey = event => {
        if (event.key !== 'Escape') return;
        overlay.remove();
        document.removeEventListener('keydown', onKey);
    };
    document.addEventListener('keydown', onKey);
}

function _screenshotLanguage(sessionId, preferredLanguage = '') {
    // Chat evidence belongs to the request language, not the static UI
    // language. The report and other application panels still use the global
    // locale, but screenshot attachments and their trace are part of a reply.
    const sessionLanguage = typeof window.conversationLanguageForSession === 'function'
        ? window.conversationLanguageForSession(sessionId || _activeApiSessionId())
        : '';
    const raw = preferredLanguage
        || sessionLanguage
        || window._responseLanguage
        || window._i18nLang
        || 'en';
    return String(raw || 'en').toLowerCase().startsWith('zh') ? 'zh' : 'en';
}

function _localizedScreenshotText(candidate, fallback, sessionId, preferredLanguage = '') {
    const value = String(candidate || '').trim();
    if (!value) return fallback;
    const language = _screenshotLanguage(sessionId, preferredLanguage);
    const hasChinese = /[\u3400-\u9fff]/.test(value);
    if ((language === 'zh' && !hasChinese) || (language === 'en' && hasChinese)) {
        return fallback;
    }
    return value;
}

function _localizedScreenshotTargetLabel(target, sessionId = _activeApiSessionId(), preferredLanguage = '') {
    const labels = {
        'viewer-axial': ['\u8f74\u4f4d', 'Axial'],
        'viewer-sagittal': ['\u77e2\u72b6\u4f4d', 'Sagittal'],
        'viewer-coronal': ['\u51a0\u72b6\u4f4d', 'Coronal'],
        'viewer-3d': ['\u4e09\u7ef4\u67e5\u770b\u5668', '3D viewer'],
        'dvh': ['DVH \u66f2\u7ebf', 'DVH'],
        'data-tree': ['\u6570\u636e\u6811', 'Data Tree'],
        'metrics': ['\u89c4\u5212\u6307\u6807', 'Planning metrics'],
        'report': ['\u62a5\u544a\u622a\u56fe', 'Report figures'],
        'full': ['\u5b8c\u6574\u754c\u9762', 'Full application'],
    };
    const language = _screenshotLanguage(sessionId, preferredLanguage);
    const pair = labels[target] || [target || '\u622a\u56fe', target || 'Screenshot'];
    return language === 'zh' ? pair[0] : pair[1];
}

function _safePersistedReportFigureUrl(candidate, ownerSessionId) {
    const value = String(candidate || '').trim();
    if (/^data:image\/(?:png|jpe?g|webp);base64,[a-z0-9+/=\s]+$/i.test(value)) {
        return value;
    }
    const match = value.match(/^\/api\/sessions\/([^/]+)\/screenshots\/(report_screenshot_[A-Za-z0-9_.-]+\.png)$/i);
    if (!match) return '';
    try {
        return decodeURIComponent(match[1]) === String(ownerSessionId || '') ? value : '';
    } catch (_) {
        return '';
    }
}

function _reportFigureMetadataFromArtifactFilename(filename, index) {
    const stem = String(filename || '').replace(/\.png$/i, '');
    const identityMatch = stem.match(/^report_screenshot_(report_fig[12]_.+?)_[0-9a-f]{12}$/i);
    const axis = identityMatch ? identityMatch[1] : `restored-${index + 1}`;
    const metadata = {
        report_fig1_global: { figureGroup: 'figure1', figureNumber: 1, subfigure: 'a', sortOrder: 1, captureRole: 'planning_overview' },
        report_fig1_closeup: { figureGroup: 'figure1', figureNumber: 1, subfigure: 'b', sortOrder: 2, captureRole: 'planning_closeup' },
        report_fig2_axial: { figureGroup: 'figure2', figureNumber: 2, subfigure: 'a', sortOrder: 1, captureRole: 'peak_dose_axial' },
        report_fig2_sagittal: { figureGroup: 'figure2', figureNumber: 2, subfigure: 'b', sortOrder: 2, captureRole: 'peak_dose_sagittal' },
        report_fig2_coronal: { figureGroup: 'figure2', figureNumber: 2, subfigure: 'c', sortOrder: 3, captureRole: 'peak_dose_coronal' },
        report_fig2_dose_surface: { figureGroup: 'figure2', figureNumber: 2, subfigure: 'd', sortOrder: 4, captureRole: 'dose_surface_3d' },
        report_fig2_dvh: { figureGroup: 'figure2', figureNumber: 2, subfigure: 'e', sortOrder: 5, captureRole: 'dvh' },
    };
    return Object.assign({ axis }, metadata[axis] || {});
}

function _reportFigureStableKey(figure, index = 0) {
    const axis = String(figure?.axis || '').trim();
    if (/^report_fig[12]_/i.test(axis)) return `axis:${axis}`;
    const role = String(figure?.captureRole || figure?.capture_role || '').trim();
    if (role) return `role:${role}`;
    return `other:${figure?._serverUrl || figure?.dataUrl || figure?.id || index}`;
}

function _reportFiguresFromArtifactCatalog(ownerSessionId, activePlanningId) {
    const artifacts = typeof dataTreeState !== 'undefined'
        && Array.isArray(dataTreeState?.exportArtifacts)
        ? dataTreeState.exportArtifacts : [];
    return artifacts.map((item, index) => {
        const dataType = String(item?.dataType || item?.type || '');
        const objectId = String(item?.objectId || item?.object_id || '');
        const filename = objectId.includes(':')
            ? objectId.split(':').slice(1).join(':')
            : objectId || String(item?.name || '');
        const ownerPlanningId = String(item?.planningId || item?.planning_id || '');
        if (!['screenshot', 'report_figure'].includes(dataType)
            || !/^report_screenshot_[^/\\]+\.png$/i.test(filename)
            || (activePlanningId && ownerPlanningId && ownerPlanningId !== activePlanningId)) {
            return null;
        }
        const metadata = _reportFigureMetadataFromArtifactFilename(filename, index);
        // Old UUID-only images do not carry enough semantic information to
        // become a report attachment. Retain them as exported artifacts, but
        // never guess that an unlabelled file is a new Figure 1/2 subfigure.
        if (!metadata.figureGroup) return null;
        const display = typeof window.describeReportFigure === 'function'
            ? window.describeReportFigure(metadata.axis) : null;
        return Object.assign({
            id: `report-artifact-${filename.replace(/[^A-Za-z0-9_-]/g, '_')}`,
            type: 'screenshot',
            title: display?.title || '',
            caption: display?.caption || '',
            _artifactFallback: true,
            _serverUrl: `/api/sessions/${encodeURIComponent(ownerSessionId)}/screenshots/${encodeURIComponent(filename)}`,
        }, metadata);
    }).filter(Boolean);
}

async function _appendPersistedReportFigures(plan, galleryContext, ownerSessionId) {
    const context = galleryContext || {};
    let form = window.reportForm;
    const requestedPlanningId = String(
        plan?.planning_id
        || window.__reportWorkspaceActivePlanningId
        || dataTreeState?.planning?.activePlanningId
        || form?.active_planning_id
        || ''
    );
    // The workspace restore and chat shell are deliberately asynchronous. A
    // content request can therefore arrive before the report editor has
    // selected its Session-owned form. Restore the persisted report model
    // first; do not fall back to rasterizing an unmounted report panel.
    if (
        String(ownerSessionId || '') === String(_activeApiSessionId())
        && (!form || (form.sessionId && String(form.sessionId) !== String(ownerSessionId)))
        && typeof window.restoreReportForPlanning === 'function'
    ) {
        try {
            window.restoreReportForPlanning(requestedPlanningId, { persist: false });
            await _waitScreenshotFrames(1);
            form = window.reportForm;
        } catch (error) {
            console.debug('[report-content] Unable to restore persisted report form', error);
        }
    }
    const formSessionMatches = !form?.sessionId
        || String(form.sessionId) === String(ownerSessionId || '');
    const activePlanningId = String(
        requestedPlanningId
        || form?.active_planning_id
        || ''
    );
    const figures = formSessionMatches && Array.isArray(form?.figures)
        ? form.figures.filter(figure => {
            if (!figure || typeof figure !== 'object') return false;
            const figurePlanningId = String(figure.planningId || figure.planning_id || '');
            return !activePlanningId || !figurePlanningId || figurePlanningId === activePlanningId;
        }).slice()
        : [];

    // A report is restored independently from the chat shell.  If a user asks
    // for its figures during that narrow window, fall back to the durable
    // catalog instead of trying to rasterize the report panel or reporting a
    // false "not loaded" error.
    if (typeof hydrateDataTreeArtifactCatalog === 'function'
        && String(ownerSessionId) === String(_activeApiSessionId())) {
        try { await hydrateDataTreeArtifactCatalog(); } catch (_) {}
    }
    const seenUrls = new Set(
        figures.map(figure => _safePersistedReportFigureUrl(
            figure?._serverUrl || figure?.dataUrl,
            ownerSessionId,
        )).filter(Boolean),
    );
    const seenFigureKeys = new Set(
        figures.map((figure, index) => _reportFigureStableKey(figure, index)),
    );
    _reportFiguresFromArtifactCatalog(ownerSessionId, activePlanningId).forEach(figure => {
        const url = _safePersistedReportFigureUrl(figure._serverUrl, ownerSessionId);
        const stableKey = _reportFigureStableKey(figure, figures.length);
        if (!url || seenUrls.has(url) || seenFigureKeys.has(stableKey)) return;
        seenUrls.add(url);
        seenFigureKeys.add(stableKey);
        figures.push(figure);
    });

    const language = _screenshotLanguage(ownerSessionId, context.responseLanguage);
    const ordered = figures.map((figure, index) => ({ figure, index })).sort((left, right) => (
        Number(left.figure.figureNumber || 99) - Number(right.figure.figureNumber || 99)
        || Number(left.figure.sortOrder || 99) - Number(right.figure.sortOrder || 99)
        || left.index - right.index
    ));
    const attachments = [];
    ordered.forEach(({ figure, index }) => {
        const url = _safePersistedReportFigureUrl(
            figure._serverUrl || figure.dataUrl,
            ownerSessionId,
        );
        if (!url) return;
        const figureLabel = figure.figureNumber
            ? `${language === 'zh' ? '\u62a5\u544a\u56fe' : 'Report figure'} ${figure.figureNumber}${figure.subfigure ? `(${String(figure.subfigure).toLowerCase()})` : ''}`
            : `${language === 'zh' ? '\u62a5\u544a\u622a\u56fe' : 'Report screenshot'} ${index + 1}`;
        const attachment = _appendScreenshotToGallery(url, 'report', plan.question, context, {
            id: String(
                figure.id
                || `${context.requestId || 'request'}-report-${figure.axis || index}`
            ),
            title: _localizedScreenshotText(
                figure.title,
                figureLabel,
                ownerSessionId,
                context.responseLanguage,
            ),
            description: _localizedScreenshotText(
                figure.caption,
                plan.question || '',
                ownerSessionId,
                context.responseLanguage,
            ),
            mode: plan.mode,
            request_id: context.requestId,
            message_id: context.messageId,
            session_id: ownerSessionId,
            planning_id: activePlanningId,
            source: 'report_artifact',
            response_language: context.responseLanguage || language,
            view_metadata: {
                axis: String(figure.axis || ''),
                figure_group: String(figure.figureGroup || ''),
                figure_number: Number(figure.figureNumber) || null,
                subfigure: String(figure.subfigure || ''),
                sort_order: Number(figure.sortOrder) || null,
                capture_role: String(figure.captureRole || ''),
                capture_contract: String(figure.captureContract || ''),
            },
        });
        if (attachment) attachments.push(attachment);
    });
    return attachments;
}

function _safeSessionScreenshotUrl(candidate, ownerSessionId) {
    const value = String(candidate || '').trim();
    if (/^data:image\/(?:png|jpe?g|webp);base64,[a-z0-9+/=\s]+$/i.test(value)) {
        return value;
    }
    const match = value.match(/^\/api\/sessions\/([^/]+)\/screenshots\/([A-Za-z0-9_.-]+\.(?:png|jpe?g|webp))$/i);
    if (!match) return '';
    try {
        return decodeURIComponent(match[1]) === String(ownerSessionId || '') ? value : '';
    } catch (_) {
        return '';
    }
}

function _sessionArtifactFilename(item) {
    const objectId = String(item?.objectId || item?.object_id || '');
    const raw = objectId.includes(':')
        ? objectId.split(':').slice(1).join(':')
        : objectId || String(item?.name || '');
    return String(raw || '').split(/[\\/]/).pop() || '';
}

function _sessionScreenshotArtifacts(ownerSessionId, activePlanningId, options = {}) {
    const artifacts = typeof dataTreeState !== 'undefined'
        && Array.isArray(dataTreeState?.exportArtifacts)
        ? dataTreeState.exportArtifacts : [];
    const includeReportOnly = options.reportOnly === true;
    return artifacts.map((item, index) => {
        const dataType = String(item?.dataType || item?.data_type || item?.type || '').toLowerCase();
        const filename = _sessionArtifactFilename(item);
        const ownerPlanningId = String(item?.planningId || item?.planning_id || '');
        const isScreenshot = ['screenshot', 'report_figure'].includes(dataType);
        const isReport = /^report_screenshot_[^/\\]+\.(?:png|jpe?g|webp)$/i.test(filename);
        if (!isScreenshot || !filename || (includeReportOnly && !isReport)) return null;
        if (activePlanningId && ownerPlanningId && ownerPlanningId !== String(activePlanningId)) return null;
        return {
            id: `session-artifact-${filename.replace(/[^A-Za-z0-9_-]/g, '_')}`,
            objectId: `${isReport ? 'figure' : 'screenshot'}:${filename}`,
            filename,
            title: String(item?.label || item?.name || filename),
            planningId: ownerPlanningId,
            dataType,
            index,
            isReport,
            url: `/api/sessions/${encodeURIComponent(ownerSessionId)}/screenshots/${encodeURIComponent(filename)}`,
        };
    }).filter(Boolean);
}

async function _appendPersistedSessionScreenshots(command, galleryContext, ownerSessionId) {
    const context = galleryContext || {};
    if (typeof hydrateDataTreeArtifactCatalog === 'function'
        && String(ownerSessionId) === String(_activeApiSessionId())) {
        try { await hydrateDataTreeArtifactCatalog(); } catch (_) {}
    }
    const activePlanningId = String(
        command?.planning_id
        || window.__reportWorkspaceActivePlanningId
        || dataTreeState?.planning?.activePlanningId
        || ''
    );
    const language = _screenshotLanguage(ownerSessionId, context.responseLanguage);
    const requestedObjectIds = new Set(
        (Array.isArray(command?.object_ids) ? command.object_ids : [])
            .map(value => String(value || '').trim().toLowerCase())
            .filter(Boolean),
    );
    const artifacts = _sessionScreenshotArtifacts(ownerSessionId, activePlanningId).filter(artifact => (
        !requestedObjectIds.size
        || requestedObjectIds.has(String(artifact.objectId || '').toLowerCase())
    ));
    const attachments = [];
    artifacts.forEach((artifact, index) => {
        const url = _safeSessionScreenshotUrl(artifact.url, ownerSessionId);
        if (!url) return;
        const title = artifact.isReport
            ? (language === 'zh' ? '\u62a5\u544a\u622a\u56fe' : 'Report figure')
            : (language === 'zh' ? '\u5df2\u4fdd\u5b58\u622a\u56fe' : 'Saved screenshot');
        const attachment = _appendScreenshotToGallery(url, 'report', command?.question || '', context, {
            id: artifact.id,
            title: `${title} ${index + 1}`,
            description: command?.question || '',
            mode: command?.mode || 'chat',
            request_id: context.requestId,
            message_id: context.messageId,
            session_id: ownerSessionId,
            planning_id: artifact.planningId || activePlanningId,
            source: 'session_artifact',
            response_language: context.responseLanguage || language,
            view_metadata: {
                filename: artifact.filename,
                data_type: artifact.dataType,
                report_figure: artifact.isReport,
            },
        });
        if (attachment) attachments.push(attachment);
    });
    return attachments;
}

async function _readPlanningResultsForPresentation(ownerSessionId) {
    let response = null;
    for (let attempt = 0; attempt < 3; attempt += 1) {
        response = await fetch(API + '/planning/results', {
            headers: { 'X-BrachyBot-Session': String(ownerSessionId || '') },
        });
        if (response.status !== 202 || attempt === 2) break;
        const retryAfter = Number(response.headers.get('Retry-After-Ms') || 250);
        await new Promise(resolve => setTimeout(resolve, Math.max(100, Math.min(800, retryAfter))));
    }
    const payload = await response?.json().catch(() => ({}));
    if (!response?.ok || payload?.success === false) {
        const error = String(payload?.error || response?.status || 'planning_results_unavailable');
        throw new Error(error);
    }
    return payload || {};
}

function _contentNumber(value, digits = 1) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return '';
    return numeric.toFixed(digits).replace(/\.0+$/, '');
}

function _contentPercent(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return '';
    const percent = Math.abs(numeric) <= 1.001 ? numeric * 100 : numeric;
    return `${_contentNumber(percent, 1)}%`;
}

function _contentMetric(metrics, names) {
    if (!metrics || typeof metrics !== 'object') return undefined;
    for (const name of names) {
        if (Object.prototype.hasOwnProperty.call(metrics, name)) return metrics[name];
    }
    return undefined;
}

function _sessionContentTreeSnapshot() {
    const tree = typeof dataTreeState !== 'undefined' ? dataTreeState : null;
    if (!tree) return null;
    const planning = tree.planning || {};
    const guide = (planning.meshes || []).find(item =>
        String(item?.source || '').toLowerCase() === 'surgical_guide'
    );
    return {
        ctLoaded: !!tree.ct?.loaded,
        ctvLoaded: !!tree.ctv?.loaded,
        ctvCount: Object.keys(tree.ctvLabels || {}).length || (tree.ctv?.loaded ? 1 : 0),
        oarCount: Array.isArray(tree.organs) ? tree.organs.length : 0,
        skinLoaded: !!tree.skin?.loaded,
        planningId: String(planning.activePlanningId || planning.id || ''),
        planningRuns: Array.isArray(planning.runs) ? planning.runs.length : 0,
        seedCount: Array.isArray(planning.seeds) ? planning.seeds.length : 0,
        needleCount: Array.isArray(planning.needles) ? planning.needles.length : 0,
        doseLoaded: !!tree.dose?.loaded || !!planning.doseOverlay,
        dvhLoaded: !!planning.dvh?.loaded || !!planning.dvh,
        guide,
        artifactCount: Array.isArray(tree.exportArtifacts) ? tree.exportArtifacts.length : 0,
    };
}

function _sessionContentObjectIndex() {
    // This is a read-only index over the same state that renders the Data
    // Tree.  Do not substitute names for identifiers: an object can be
    // renamed by a clinician, while its local node ID and persistent object
    // ID remain the identity boundary shared by Viewer, Session, and export.
    const tree = typeof dataTreeState !== 'undefined' ? dataTreeState : null;
    if (!tree) return [];
    const planning = tree.planning || {};
    const viewerState = (typeof state !== 'undefined' && state) || window.state || {};
    const records = [];
    const seen = new Set();
    const add = (node, fallback = {}) => {
        if (!node || typeof node !== 'object') return;
        const localId = String(
            node.id || node.nodeId || node.node_id || fallback.localId || '',
        ).trim();
        const objectId = String(
            node.objectId || node.object_id || fallback.objectId || localId,
        ).trim();
        if (!localId && !objectId) return;
        const key = `${localId}|${objectId}`;
        if (seen.has(key)) return;
        seen.add(key);
        records.push({
            localId: localId || objectId,
            nodeId: String(node.nodeId || node.node_id || localId || objectId),
            objectId: objectId || localId,
            label: String(node.name || node.label || node.displayName || fallback.label || objectId || localId),
            type: String(node.dataType || node.data_type || node.type || node.source || fallback.type || 'data'),
            visible: node.visible !== false,
            visible2D: node.visible2D !== false,
            visible3D: node.visible3D !== false,
        });
    };

    add(tree.ct, { localId: 'ct', objectId: 'image:ct', label: 'CT', type: 'image' });
    const ctvLabels = Object.values(tree.ctvLabels || {});
    if (ctvLabels.length) {
        ctvLabels.forEach((node, index) => add(node, {
            localId: `ctv_${index + 1}`,
            objectId: `structure:ctv:${index + 1}`,
            label: `CTV ${index + 1}`,
            type: 'ctv_label',
        }));
    } else {
        add(tree.ctv, { localId: 'ctv', objectId: 'structure:ctv:1', label: 'CTV', type: 'ctv' });
    }
    add(tree.skin, {
        localId: 'skin_surface', objectId: 'skin_surface:guide',
        label: 'Guide skin surface', type: 'skin_surface',
    });
    (tree.organs || []).forEach((node, index) => add(node, {
        localId: `organ_${index + 1}`,
        objectId: `structure:oar:${index + 1}`,
        label: `OAR ${index + 1}`,
        type: 'oar',
    }));
    (planning.trajectories || []).forEach((node, index) => add(node, {
        localId: `trajectory_${index + 1}`,
        objectId: `trajectory:${node?.id || index + 1}`,
        label: `Trajectory ${index + 1}`,
        type: 'trajectory',
    }));
    (planning.needles || []).forEach((node, index) => add(node, {
        localId: `needle_${index + 1}`,
        objectId: `needle:${node?.id || index + 1}`,
        label: `Needle ${index + 1}`,
        type: 'needle',
    }));
    (planning.seeds || []).forEach((node, index) => add(node, {
        localId: `seed_${index + 1}`,
        objectId: `seed:${node?.id || index + 1}`,
        label: `Seed ${index + 1}`,
        type: 'seed',
    }));
    if (planning.doseOverlay || tree.dose) {
        add(planning.doseOverlay || tree.dose, {
            localId: planning.doseOverlay ? 'dose_overlay' : 'dose',
            objectId: 'dose:volume', label: 'Dose volume', type: 'dose',
        });
    }
    (planning.doseLevels || []).forEach((node, index) => {
        const threshold = Number(node?.thresholdGy ?? node?.threshold);
        const token = Number.isFinite(threshold) ? threshold : index + 1;
        add(node, {
            localId: `dose_iso_${token}`,
            objectId: `dose_iso:${token}`,
            label: `${token} Gy iso-surface`, type: 'dose_isosurface',
        });
    });
    add(planning.dvh, { localId: 'dvh', objectId: 'dvh:data', label: 'DVH', type: 'dvh_data' });
    (planning.meshes || []).forEach((node, index) => {
        const isGuide = String(node?.source || '').toLowerCase() === 'surgical_guide';
        add(node, {
            localId: `planning_mesh_${index + 1}`,
            objectId: isGuide ? 'surgical_guide:active' : `planning_mesh:${node?.id || index + 1}`,
            label: isGuide ? 'Surgical guide' : `Planning mesh ${index + 1}`,
            type: isGuide ? 'surgical_guide' : 'planning_mesh',
        });
    });
    (tree.annotations || []).forEach((node, index) => add(node, {
        localId: `annotation_${index + 1}`,
        objectId: `annotation:${node?.id || index + 1}`,
        label: `Annotation ${index + 1}`, type: 'annotation',
    }));
    (tree.exportArtifacts || []).forEach((node, index) => add(node, {
        localId: `artifact_${index + 1}`,
        objectId: `artifact:${index + 1}`,
        label: `Session artifact ${index + 1}`, type: 'artifact',
    }));
    Object.entries(viewerState.maskLabels || {}).forEach(([id, node]) => add(node, {
        localId: String(id), objectId: `mask:${id}`,
        label: String(node?.label || node?.name || id), type: 'mask',
    }));
    return records;
}

function _sessionContentSelectedLocalIds() {
    try {
        return typeof getSelectedOrganIds === 'function'
            ? getSelectedOrganIds().map(value => String(value || '')).filter(Boolean)
            : [];
    } catch (_) {
        return [];
    }
}

function _sessionContentObjectMatches(objectIds, options = {}) {
    const index = _sessionContentObjectIndex();
    let requested = Array.isArray(objectIds)
        ? objectIds.map(value => String(value || '').trim()).filter(Boolean)
        : [];
    if (!requested.length && options.useSelection !== false) {
        requested = _sessionContentSelectedLocalIds();
    }
    const requestedKeys = new Set(requested.map(value => value.toLowerCase()));
    const matches = index.filter(item => requestedKeys.has(String(item.localId).toLowerCase())
        || requestedKeys.has(String(item.nodeId).toLowerCase())
        || requestedKeys.has(String(item.objectId).toLowerCase()));
    return { requested, matches };
}

function _sessionContentVisibilityText(item, language) {
    if (item.type === 'report' || item.type === 'report_data' || item.type === 'report_figure'
        || item.type === 'screenshot' || item.type === 'chat_messages'
        || item.type === 'execution_trace' || item.type === 'tool_history') {
        return '';
    }
    const zh = language === 'zh';
    const visible2D = item.visible && item.visible2D;
    const visible3D = item.visible && item.visible3D;
    return zh
        ? `，2D${visible2D ? '\u5df2\u663e\u793a' : '\u5df2\u9690\u85cf'}，3D${visible3D ? '\u5df2\u663e\u793a' : '\u5df2\u9690\u85cf'}`
        : `, 2D ${visible2D ? 'visible' : 'hidden'}, 3D ${visible3D ? 'visible' : 'hidden'}`;
}

async function _focusSessionContentObjects(objectIds) {
    const { matches } = _sessionContentObjectMatches(objectIds);
    if (!matches.length) return [];
    // Selection is a view-only operation.  It never changes a node's
    // visibility, geometry, planning data, or Session persistence state.
    if (typeof handleTreeItemClick === 'function') {
        matches.slice(0, 16).forEach((item, index) => {
            handleTreeItemClick(item.localId, {
                shiftKey: false,
                ctrlKey: index > 0,
                metaKey: false,
            });
        });
    }
    await _waitScreenshotFrames(1);
    const rows = Array.from(document.querySelectorAll('#dataTreeBody .tree-item'));
    const matchedNodeIds = new Set(matches.map(item => String(item.nodeId)));
    const matchedLocalIds = new Set(matches.map(item => String(item.localId)));
    const first = rows.find(row => matchedNodeIds.has(String(row.dataset.nodeId || ''))
        || matchedLocalIds.has(String(row.dataset.item || '')));
    if (first?.scrollIntoView) {
        first.scrollIntoView({ block: 'center', behavior: 'smooth' });
        first.classList.add('session-content-focus');
        window.setTimeout(() => first.classList.remove('session-content-focus'), 1600);
    }
    return matches;
}

function _sessionContentObjectSummary(objectIds, tree, language) {
    const { requested, matches } = _sessionContentObjectMatches(objectIds);
    const zh = language === 'zh';
    if (!requested.length) {
        return zh
            ? '\u672a\u6307\u5b9a\u53ef\u8bfb\u53d6\u7684 Data Tree \u5bf9\u8c61\uff0c\u4e5f\u6ca1\u6709\u5f53\u524d\u9009\u4e2d\u8282\u70b9\u3002'
            : 'No readable Data Tree object was specified or currently selected.';
    }
    if (!matches.length) {
        return zh
            ? '\u5728\u5f53\u524d Session \u4e2d\u6ca1\u6709\u627e\u5230\u8bf7\u6c42\u7684\u6570\u636e\u5bf9\u8c61\u3002'
            : 'The requested data object was not found in the current Session.';
    }
    const items = matches.slice(0, 16).map(item => {
        const type = String(item.type || 'data');
        return zh
            ? `${item.label}\uff08${type}${_sessionContentVisibilityText(item, language)}\uff09`
            : `${item.label} (${type}${_sessionContentVisibilityText(item, language)})`;
    });
    const more = matches.length > items.length
        ? (zh ? `\u8fd8\u6709 ${matches.length - items.length} \u9879` : `${matches.length - items.length} more item(s)`)
        : '';
    return zh
        ? `\u5df2\u8bfb\u53d6 Data Tree \u5bf9\u8c61：${items.join('\u3001')}${more ? `\uff1b${more}` : ''}\u3002`
        : `Read Data Tree object(s): ${items.join(', ')}${more ? `; ${more}` : ''}.`;
}

function _sessionContentSummary(target, planning, tree, language, command = {}) {
    const zh = language === 'zh';
    const metrics = planning?.metrics && typeof planning.metrics === 'object' ? planning.metrics : {};
    const report = window.reportForm && (!window.reportForm.sessionId
        || String(window.reportForm.sessionId) === String(_activeApiSessionId()))
        ? window.reportForm : null;
    const chat = typeof window.getSessionContentSnapshot === 'function'
        ? window.getSessionContentSnapshot(_activeApiSessionId()) : null;
    const seedCount = Number(planning?.total_seeds ?? tree?.seedCount ?? 0);
    const needleCount = Number(planning?.num_trajectories ?? tree?.needleCount ?? 0);
    const v100 = _contentPercent(_contentMetric(metrics, ['V100', 'v100', 'coverage_v100']));
    const d90 = _contentNumber(_contentMetric(metrics, ['D90', 'd90', 'dose_d90']), 2);
    const planningId = String(planning?.planning_id || tree?.planningId || '');
    const prefix = planningId ? ` (${planningId})` : '';
    const lines = [];

    if (target === 'planning' || target === 'session_summary') {
        lines.push(zh
            ? `\u5f53\u524d\u89c4\u5212${prefix}\uff1a${seedCount}\u9897\u7c92\u5b50\uff0c${needleCount}\u6761\u9488\u9053\u3002`
            : `Current planning${prefix}: ${seedCount} seed(s) across ${needleCount} needle path(s).`);
    }
    if (target === 'dose' || target === 'metrics' || target === 'session_summary') {
        if (planning?.has_dose) {
            const doseRange = [planning.dose_min, planning.dose_max]
                .map(value => _contentNumber(value, 2)).filter(Boolean).join(' - ');
            lines.push(zh
                ? `\u5242\u91cf\u7ed3\u679c\u5df2\u52a0\u8f7d${doseRange ? `\uff08${doseRange} Gy\uff09` : ''}\u3002`
                : `Dose result is loaded${doseRange ? ` (${doseRange} Gy)` : ''}.`);
        } else if (target !== 'session_summary') {
            lines.push(zh ? '\u5f53\u524d\u89c4\u5212\u5c1a\u65e0\u53ef\u7528\u5242\u91cf\u7ed3\u679c\u3002' : 'No current dose result is available for this planning run.');
        }
        if (v100 || d90) {
            lines.push(zh
                ? `\u6307\u6807\uff1a${v100 ? `CTV V100 ${v100}` : ''}${v100 && d90 ? '\uff1b' : ''}${d90 ? `D90 ${d90} Gy` : ''}\u3002`
                : `Metrics: ${v100 ? `CTV V100 ${v100}` : ''}${v100 && d90 ? '; ' : ''}${d90 ? `D90 ${d90} Gy` : ''}.`);
        }
    }
    if (target === 'dvh' || target === 'session_summary') {
        const dvh = planning?.dvh;
        const curveCount = Array.isArray(dvh) ? dvh.length : (dvh && typeof dvh === 'object' ? Object.keys(dvh).length : 0);
        if (curveCount) {
            lines.push(zh ? `DVH \u6570\u636e\u5df2\u52a0\u8f7d\uff08${curveCount}\u4e2a\u7ed3\u6784\u6216\u66f2\u7ebf\uff09\u3002` : `DVH data is loaded (${curveCount} structure(s) or curve(s)).`);
        } else if (target === 'dvh') {
            lines.push(zh ? '\u5f53\u524d\u89c4\u5212\u5c1a\u65e0\u53ef\u5c55\u793a\u7684 DVH \u6570\u636e\u3002' : 'No DVH data is currently available for presentation.');
        }
    }
    if (target === 'ct' || target === 'session_summary') {
        const shape = Array.isArray(window.state?.ctShape) ? window.state.ctShape.join(' \u00d7 ') : '';
        if (tree?.ctLoaded || window.state?.ctLoaded) {
            lines.push(zh ? `CT \u5df2\u52a0\u8f7d${shape ? `\uff08${shape}\uff09` : ''}\u3002` : `CT is loaded${shape ? ` (${shape})` : ''}.`);
        } else if (target === 'ct') {
            lines.push(zh ? '\u5f53\u524d Session \u4e2d\u6ca1\u6709\u5df2\u52a0\u8f7d\u7684 CT \u56fe\u50cf\u3002' : 'No CT image is loaded in the current Session.');
        }
    }
    if (target === 'structures' || target === 'data_tree' || target === 'session_summary') {
        lines.push(zh
            ? `\u7ed3\u6784\uff1aCTV ${tree?.ctvCount || 0}\u4e2a\uff0cOAR ${tree?.oarCount || 0}\u4e2a${tree?.skinLoaded ? '\uff0c\u5bfc\u677f\u76ae\u80a4\u8868\u9762\u5df2\u52a0\u8f7d' : ''}\u3002`
            : `Structures: ${tree?.ctvCount || 0} CTV item(s), ${tree?.oarCount || 0} OAR item(s)${tree?.skinLoaded ? ', guide skin surface loaded' : ''}.`);
    }
    if (target === 'surgical_guide' || target === 'session_summary') {
        if (tree?.guide) {
            lines.push(zh ? `\u624b\u672f\u5bfc\u677f\u5df2\u52a0\u8f7d\uff1a${tree.guide.label || '\u7a7f\u523a\u5bfc\u677f'}\u3002` : `Surgical Guide is loaded: ${tree.guide.label || 'puncture guide'}.`);
        } else if (target === 'surgical_guide') {
            lines.push(zh ? '\u5f53\u524d\u89c4\u5212\u5c1a\u65e0\u53ef\u5c55\u793a\u7684\u624b\u672f\u5bfc\u677f\u3002' : 'No Surgical Guide is currently available for presentation.');
        }
    }
    if (target === 'report' || target === 'session_summary') {
        if (report) {
            const figureCount = Array.isArray(report.figures) ? report.figures.length : 0;
            const technique = String(report.technique || report.treatmentTechnique || '').trim();
            lines.push(zh
                ? `\u62a5\u544a\u5df2\u52a0\u8f7d${technique ? `\uff08${technique}\uff09` : ''}\uff0c\u5305\u542b ${figureCount} \u4e2a\u5df2\u4fdd\u5b58\u56fe\u4ef6\u3002`
                : `Report is loaded${technique ? ` (${technique})` : ''} with ${figureCount} saved figure(s).`);
        } else if (target === 'report') {
            lines.push(zh ? '\u5f53\u524d Session \u5c1a\u65e0\u5df2\u52a0\u8f7d\u7684\u62a5\u544a\u6587\u672c\u3002' : 'No report text is loaded for the current Session.');
        }
    }
    if (target === 'chat_history' || target === 'session_summary') {
        if (chat?.available) {
            lines.push(zh
                ? `\u5bf9\u8bdd\u5386\u53f2\uff1a${chat.messageCount} \u6761\u7528\u6237\u53ef\u89c1\u6d88\u606f\uff0c${chat.executionTraceCount} \u4e2a\u6267\u884c\u8ffd\u8e2a\u3002`
                : `Conversation history: ${chat.messageCount} user-visible message(s) and ${chat.executionTraceCount} execution trace(s).`);
        } else if (target === 'chat_history') {
            lines.push(zh ? '\u5f53\u524d Session \u5c1a\u65e0\u5df2\u4fdd\u5b58\u7684\u5bf9\u8bdd\u5386\u53f2\u3002' : 'No saved conversation history is available for the current Session.');
        }
    }
    if (target === 'data_tree') {
        lines.push(zh
            ? `Data Tree \u4e2d\u5f53\u524d\u5305\u542b ${tree?.planningRuns || 0}\u4e2a\u89c4\u5212\u7248\u672c\u548c ${tree?.artifactCount || 0}\u4e2a\u6301\u4e45\u5de5\u4ef6\u3002`
            : `The Data Tree currently contains ${tree?.planningRuns || 0} planning run(s) and ${tree?.artifactCount || 0} persisted artifact(s).`);
    }
    if (target === 'artifact') {
        lines.push(_sessionContentObjectSummary(command?.object_ids, tree, language));
    }
    return lines.filter(Boolean).join('\n\n');
}

function _sessionContentUnavailableMessage(target, language) {
    const labels = {
        report_figures: ['\u5f53\u524d\u62a5\u544a\u5c1a\u672a\u4fdd\u5b58\u53ef\u5c55\u793a\u7684\u622a\u56fe\u3002\u8bf7\u5148\u751f\u6210\u6216\u66f4\u65b0\u62a5\u544a\u3002', 'The current report does not yet contain saved figures to present. Generate or update the report first.'],
        session_screenshots: ['\u5f53\u524d Session \u5c1a\u672a\u4fdd\u5b58\u53ef\u5c55\u793a\u7684\u622a\u56fe\u3002', 'The current Session does not yet contain saved screenshots to present.'],
        report: ['\u5f53\u524d Session \u5c1a\u65e0\u53ef\u5c55\u793a\u7684\u62a5\u544a\u5185\u5bb9\u3002', 'The current Session does not yet contain report content to present.'],
    };
    const pair = labels[target] || ['\u5f53\u524d Session \u4e2d\u6682\u672a\u627e\u5230\u8bf7\u6c42\u7684\u771f\u5b9e\u6570\u636e\u3002', 'The requested real data is not currently available in this Session.'];
    return language === 'zh' ? pair[0] : pair[1];
}

function _openSessionContentPanel(target) {
    // Opening a panel is opt-in. Ordinary content requests stay in the chat
    // so a model cannot unexpectedly move a clinician away from the current
    // viewer while it reads persistent Session-owned data.
    const panelByTarget = {
        report_figures: 'report',
        report: 'report',
        session_screenshots: 'report',
        planning: 'input',
        dose: 'viewers',
        dvh: 'metrics',
        metrics: 'metrics',
        ct: 'viewers',
        structures: 'viewers',
        surgical_guide: 'viewers',
        data_tree: 'viewers',
        artifact: 'viewers',
    };
    const panelName = panelByTarget[String(target || '').toLowerCase()];
    if (!panelName || typeof switchPanel !== 'function') return;
    const tab = document.querySelector(`.panel-tab[data-panel="${panelName}"]`)
        || document.querySelector(`.panel-tab[onclick*="${panelName}"]`);
    if (tab && !tab.classList.contains('active')) switchPanel(panelName, tab);
}

// Read persisted Session data for a normal chat reply. This is intentionally
// data-first: it never substitutes a browser screenshot for a missing report,
// and it never synthesizes a clinical result that the Session does not contain.
window.presentSessionContent = async function presentSessionContent(command = {}, galleryContext = {}, options = {}) {
    const context = galleryContext || {};
    const ownerSessionId = String(options.sessionId || context.sessionId || _activeApiSessionId());
    const language = _screenshotLanguage(ownerSessionId, options.responseLanguage || context.responseLanguage);
    const target = String(command.target || 'session_summary').toLowerCase();
    context.sessionId = ownerSessionId;
    context.requestId = String(options.requestId || context.requestId || '');
    context.messageId = String(options.messageId || context.messageId || '');
    context.responseLanguage = String(options.responseLanguage || context.responseLanguage || language);
    context.mode = String(command.mode || context.mode || 'chat');
    context.layout = context.layout || 'auto';
    const ownerStillActive = () => ownerSessionId === String(_activeApiSessionId());
    if (!ownerStillActive()) return { success: false, stale: true, error: 'case_changed' };

    try {
        if (typeof hydrateDataTreeArtifactCatalog === 'function') {
            await hydrateDataTreeArtifactCatalog();
        }
        if (!ownerStillActive()) return { success: false, stale: true, error: 'case_changed' };
        const presentation = String(command.presentation || 'auto').toLowerCase();
        if (presentation === 'open') {
            _openSessionContentPanel(target);
        }
        const tree = _sessionContentTreeSnapshot();
        const requestedPlanningId = String(command.planning_id || tree?.planningId || '');
        const planningTargets = new Set(['planning', 'dose', 'dvh', 'metrics', 'session_summary']);
        const needPlanning = planningTargets.has(target) || target === 'report';
        let planning = null;
        if (needPlanning) {
            try {
                planning = await _readPlanningResultsForPresentation(ownerSessionId);
            } catch (error) {
                if (planningTargets.has(target)) throw error;
                console.debug('[session-content] Planning summary is not available for report presentation', error);
            }
        }
        if (!ownerStillActive()) return { success: false, stale: true, error: 'case_changed' };

        let attachments = [];
        if (target === 'report_figures' || target === 'report') {
            attachments = await _appendPersistedReportFigures(Object.assign({}, command, {
                planning_id: requestedPlanningId,
            }), context, ownerSessionId);
        } else if (target === 'session_screenshots') {
            attachments = await _appendPersistedSessionScreenshots(command, context, ownerSessionId);
        } else if (target === 'artifact') {
            // A selected screenshot/report figure is still a durable Session
            // artifact, so embed the real file in the reply. Other Data Tree
            // objects remain represented by their own Viewer/Tree nodes; do
            // not manufacture an image where the Session has none.
            const selected = _sessionContentObjectMatches(command.object_ids).matches;
            const selectedScreenshotIds = selected
                .filter(item => ['screenshot', 'report_figure'].includes(String(item.type || '').toLowerCase()))
                .map(item => item.objectId);
            if (selectedScreenshotIds.length) {
                attachments = await _appendPersistedSessionScreenshots(Object.assign({}, command, {
                    object_ids: selectedScreenshotIds,
                }), context, ownerSessionId);
            }
        }
        if (!ownerStillActive()) return { success: false, stale: true, error: 'case_changed' };

        let focusedObjects = [];
        if (target === 'artifact' && presentation === 'open') {
            focusedObjects = await _focusSessionContentObjects(command.object_ids);
            if (!ownerStillActive()) return { success: false, stale: true, error: 'case_changed' };
        }
        const summary = _sessionContentSummary(target, planning, tree, language, Object.assign({}, command, {
            object_ids: command.object_ids?.length ? command.object_ids : focusedObjects.map(item => item.objectId),
        }));
        if ((target === 'report_figures' || target === 'session_screenshots') && !attachments.length) {
            return {
                success: false,
                error: target === 'report_figures' ? 'report_figures_unavailable' : 'session_screenshots_unavailable',
                userMessage: _sessionContentUnavailableMessage(target, language),
                attachments: [],
            };
        }
        if (target === 'report' && !attachments.length && !summary) {
            return {
                success: false,
                error: 'report_unavailable',
                userMessage: _sessionContentUnavailableMessage(target, language),
                attachments: [],
            };
        }
        const attachmentIntro = attachments.length
            ? (language === 'zh'
                ? `\u5df2\u4ece\u5f53\u524d Session \u4e2d\u8bfb\u53d6 ${attachments.length} \u4e2a\u5df2\u4fdd\u5b58\u7684\u56fe\u50cf\u9644\u4ef6\u3002`
                : `Loaded ${attachments.length} saved image attachment(s) from the current Session.`)
            : '';
        const message = [attachmentIntro, summary].filter(Boolean).join('\n\n');
        if (!message) {
            return {
                success: false,
                error: 'session_content_unavailable',
                userMessage: _sessionContentUnavailableMessage(target, language),
                attachments,
            };
        }
        return { success: true, userMessage: message, attachments, target, planning_id: requestedPlanningId };
    } catch (error) {
        if (!ownerStillActive()) return { success: false, stale: true, error: 'case_changed' };
        console.warn('[session-content] Presentation failed', error);
        return {
            success: false,
            error: 'session_content_unavailable',
            userMessage: _sessionContentUnavailableMessage(target, language),
            attachments: [],
        };
    }
};

function _appendScreenshotToGallery(url, target, question, galleryContext, attachmentMeta = {}) {
    const context = galleryContext || {};
    if (!url) return null;
    if (!Array.isArray(context.items)) context.items = [];
    if (!context.keys) context.keys = new Set();
    const label = _localizedScreenshotTargetLabel(
        target,
        context.sessionId || attachmentMeta?.session_id || _activeApiSessionId(),
        context.responseLanguage || attachmentMeta?.response_language || '',
    );
    const attachment = Object.assign({}, attachmentMeta || {}, {
        id: String(
            attachmentMeta?.id
            || `${context.requestId || 'request'}-${target}-${context.items.length}`
        ),
        url,
        target,
        title: attachmentMeta?.title || label,
        description: attachmentMeta?.description || question || '',
        mode: attachmentMeta?.mode || context.mode || 'chat',
        request_id: attachmentMeta?.request_id || context.requestId || '',
        message_id: attachmentMeta?.message_id || context.messageId || '',
        session_id: attachmentMeta?.session_id || context.sessionId || _activeApiSessionId(),
        response_language: attachmentMeta?.response_language || context.responseLanguage || '',
    });
    const key = String(attachment.id || attachment.url);
    if (context.keys.has(key)) return null;
    context.keys.add(key);
    const messageKind = String(
        context.messageKind
        || (attachment.mode === 'monitor' ? 'monitor_evidence' : 'assistant_final')
    );

    const shell = typeof window.ensureAssistantReplyContainer === 'function'
        ? window.ensureAssistantReplyContainer(
            context.requestId || attachment.request_id,
            context.messageId || attachment.message_id,
            Date.now(),
            messageKind,
        )
        : null;
    if (!shell) return null;
    if (typeof window.renderAssistantAttachments === 'function') {
        window.renderAssistantAttachments(shell, [attachment], context.layout || 'auto');
    }
    context.items.push(attachment);
    if (typeof saveSessionMessage === 'function') {
        saveSessionMessage(
            'bot-response',
            '',
            null,
            Date.now(),
            context.sessionId || attachment.session_id || _activeApiSessionId(),
            {
                requestId: context.requestId || attachment.request_id,
                messageId: context.messageId || attachment.message_id,
                messageKind,
                attachments: [attachment],
                screenshotLayout: context.layout || 'auto',
            },
        );
    }
    scrollToBottom();
    return attachment;
}

function _normalizeStructuredScreenshotPlan(target, question, options = {}) {
    const supplied = options.plan && typeof options.plan === 'object' ? options.plan : {};
    const mode = ['chat', 'monitor', 'report'].includes(supplied.mode || options.mode)
        ? String(supplied.mode || options.mode)
        : 'chat';
    let views = Array.isArray(supplied.views) && supplied.views.length
        ? supplied.views
        : [{ target: target || 'full' }];
    views = views.map(view => typeof view === 'string' ? { target: view } : Object.assign({}, view));
    // Older cached callers used focusSeedIds directly. Merge those stable
    // IDs into the current plan rather than dropping the requested close-up
    // when the call crosses the legacy-to-structured boundary.
    const objectIds = [...new Set([
        ...(Array.isArray(supplied.object_ids) ? supplied.object_ids : []),
        ...(Array.isArray(options.focusSeedIds) ? options.focusSeedIds : []),
        ...(Array.isArray(options.objectIds) ? options.objectIds : []),
    ].map(value => String(value || '').trim()).filter(Boolean))];
    const expanded = [];
    views.forEach(view => {
        const normalizedTarget = ({
            dose: 'dose-overview',
            dose_distribution: 'dose-overview',
            'dvh-chart': 'dvh',
        })[view.target] || view.target || 'full';
        if (normalizedTarget === 'dose-overview' && mode !== 'report') {
            ['viewer-axial', 'viewer-sagittal', 'viewer-coronal', 'dvh'].forEach(item => {
                expanded.push(Object.assign({}, view, { target: item }));
            });
        } else {
            expanded.push(Object.assign({}, view, { target: normalizedTarget }));
        }
    });
    return Object.assign({}, supplied, {
        version: Number(supplied.version || 2),
        mode,
        question: supplied.question || question || '',
        layout: supplied.layout || options.layout || 'auto',
        views: expanded.slice(0, 8),
        object_ids: objectIds,
        data_tree_node_ids: Array.isArray(supplied.data_tree_node_ids) ? supplied.data_tree_node_ids : [],
        highlight_object_ids: Array.isArray(supplied.highlight_object_ids)
            ? supplied.highlight_object_ids
            : [],
        focus: supplied.focus && typeof supplied.focus === 'object' ? supplied.focus : {},
        slice_indices: supplied.slice_indices && typeof supplied.slice_indices === 'object'
            ? supplied.slice_indices
            : {},
        overlays: supplied.overlays && typeof supplied.overlays === 'object' ? supplied.overlays : {},
    });
}

function _snapshotScreenshotViewerState() {
    const viewerState = typeof state !== 'undefined' && state ? state : {};
    const checkboxValue = id => {
        const element = document.getElementById(id);
        return element ? !!element.checked : null;
    };
    return {
        panel: _activeScreenshotPanel(),
        slices: {
            axial: Number(viewerState.slices?.axial || 0),
            sagittal: Number(viewerState.slices?.sagittal || 0),
            coronal: Number(viewerState.slices?.coronal || 0),
        },
        overlays: {
            ctv: checkboxValue('overlayCTV'),
            oar: checkboxValue('overlayOAR'),
        },
        dose: viewerState.doseOverlay ? {
            visible: !!viewerState.doseOverlay.visible,
            opacity: viewerState.doseOverlay.opacity,
        } : null,
    };
}

async function _restoreScreenshotViewerState(snapshot, restoreFocus) {
    const viewerState = typeof state !== 'undefined' && state ? state : {};
    try {
        if (typeof restoreFocus === 'function') restoreFocus();
    } catch (error) {
        console.debug('[screenshot] object focus restore skipped:', error);
    }
    if (!snapshot) return;
    Object.entries(snapshot.slices || {}).forEach(([axis, value]) => {
        if (typeof updateSlice === 'function') updateSlice(axis, value);
    });
    [['overlayCTV', snapshot.overlays?.ctv], ['overlayOAR', snapshot.overlays?.oar]].forEach(([id, value]) => {
        const element = document.getElementById(id);
        if (!element || value === null || value === undefined || element.checked === value) return;
        element.checked = value;
        element.dispatchEvent(new Event('change', { bubbles: true }));
    });
    if (snapshot.dose && viewerState.doseOverlay) {
        viewerState.doseOverlay.visible = snapshot.dose.visible;
        viewerState.doseOverlay.opacity = snapshot.dose.opacity;
        if (typeof updateDoseColorbars === 'function') {
            updateDoseColorbars(
                viewerState.doseOverlay.visible,
                viewerState.doseOverlay.doseMin,
                viewerState.doseOverlay.doseMax,
            );
        }
    }
    if (snapshot.panel && _activeScreenshotPanel() !== snapshot.panel) {
        _restoreScreenshotPanel(snapshot.panel);
    }
    await _waitScreenshotFrames(3);
}

async function _applyStructuredScreenshotPlan(plan) {
    const viewerState = typeof state !== 'undefined' && state ? state : {};
    Object.entries(plan.slice_indices || {}).forEach(([axis, value]) => {
        if (['axial', 'sagittal', 'coronal'].includes(axis)
            && Number.isFinite(Number(value))
            && typeof updateSlice === 'function') {
            updateSlice(axis, Math.round(Number(value)));
        }
    });
    const centerVoxel = plan.focus?.center_voxel;
    if (Array.isArray(centerVoxel) && centerVoxel.length === 3 && typeof updateSlice === 'function') {
        updateSlice('sagittal', Math.round(Number(centerVoxel[0])));
        updateSlice('coronal', Math.round(Number(centerVoxel[1])));
        updateSlice('axial', Math.round(Number(centerVoxel[2])));
    }
    [['overlayCTV', plan.overlays?.ctv], ['overlayOAR', plan.overlays?.oar]].forEach(([id, value]) => {
        const element = document.getElementById(id);
        if (!element || typeof value !== 'boolean' || element.checked === value) return;
        element.checked = value;
        element.dispatchEvent(new Event('change', { bubbles: true }));
    });
    if (typeof plan.overlays?.dose === 'boolean' && viewerState.doseOverlay) {
        viewerState.doseOverlay.visible = plan.overlays.dose;
        if (typeof updateDoseColorbars === 'function') {
            updateDoseColorbars(
                plan.overlays.dose,
                viewerState.doseOverlay.doseMin,
                viewerState.doseOverlay.doseMax,
            );
        }
    }
    const focusIds = [...new Set([
        ...(plan.object_ids || []),
        ...(plan.highlight_object_ids || []),
    ].map(String).filter(Boolean))];
    if (focusIds.length && typeof window.focusPlanningObjectsForScreenshot === 'function') {
        return window.focusPlanningObjectsForScreenshot(focusIds, {
            hideUnrelated: !!plan.hide_unrelated,
            highlightObjectIds: plan.highlight_object_ids || [],
            padding: Number(plan.focus?.padding || 0.35),
        });
    }
    if (focusIds.length && typeof window.focusPlanningSeedsForScreenshot === 'function') {
        return window.focusPlanningSeedsForScreenshot(focusIds);
    }
    return null;
}

function _validateScreenshotDataUrl(dataUrl) {
    return new Promise(resolve => {
        if (!String(dataUrl || '').startsWith('data:image/') || dataUrl.length < 1800) {
            resolve(false);
            return;
        }
        const image = new Image();
        image.onload = () => {
            try {
                const canvas = document.createElement('canvas');
                canvas.width = 24;
                canvas.height = 24;
                const ctx = canvas.getContext('2d', { willReadFrequently: true });
                ctx.drawImage(image, 0, 0, 24, 24);
                const pixels = ctx.getImageData(0, 0, 24, 24).data;
                let min = 255;
                let max = 0;
                let alphaPixels = 0;
                for (let index = 0; index < pixels.length; index += 4) {
                    const value = Math.round((pixels[index] + pixels[index + 1] + pixels[index + 2]) / 3);
                    min = Math.min(min, value);
                    max = Math.max(max, value);
                    if (pixels[index + 3] > 8) alphaPixels += 1;
                }
                resolve(alphaPixels > 32 && max - min > 2);
            } catch (_) {
                resolve(dataUrl.length > 4000);
            }
        };
        image.onerror = () => resolve(false);
        image.src = dataUrl;
    });
}

function _screenshotFailureMessage(galleryContext, errorCode) {
    const context = galleryContext || {};
    const language = _screenshotLanguage(context.sessionId, context.responseLanguage);
    const reportUnavailable = String(errorCode || '').includes('report_figures_unavailable');
    return reportUnavailable
        ? (language === 'zh'
            ? '\u5f53\u524d\u62a5\u544a\u5c1a\u672a\u751f\u6210\u53ef\u5c55\u793a\u7684\u622a\u56fe\u3002\u8bf7\u5148\u751f\u6210\u6216\u66f4\u65b0\u62a5\u544a\u540e\u518d\u67e5\u770b\u3002'
            : 'The current report does not yet contain a generated screenshot. Generate or update the report, then try again.')
        : (language === 'zh'
            ? '\u672a\u80fd\u751f\u6210\u6709\u6548\u622a\u56fe\u3002\u8bf7\u786e\u8ba4\u76ee\u6807\u6570\u636e\u5df2\u52a0\u8f7d\u540e\u91cd\u8bd5\u3002'
            : 'A valid screenshot could not be generated. Confirm that the target data is loaded, then retry.');
}

async function _interceptScreenshot(target, question, galleryContext, options = {}) {
    const context = galleryContext || {};
    const ownerSessionId = String(options.sessionId || context.sessionId || _activeApiSessionId());
    context.sessionId = ownerSessionId;
    context.requestId = String(options.requestId || context.requestId || '');
    context.messageId = String(options.messageId || context.messageId || '');
    context.responseLanguage = String(
        options.responseLanguage
        || context.responseLanguage
        || (typeof window.conversationLanguageForSession === 'function'
            ? window.conversationLanguageForSession(ownerSessionId)
            : '')
        || window._responseLanguage
        || 'en'
    );
    const plan = _normalizeStructuredScreenshotPlan(target, question, options);
    context.mode = plan.mode;
    context.layout = plan.layout;
    const ownerStillActive = () => ownerSessionId === String(_activeApiSessionId())
        && (!options.monitorOnly || trainingMonitorState.active);
    if (!ownerStillActive()) return { success: false, stale: true, error: 'case_changed' };

    const reportViews = plan.views.filter(view => String(view?.target || '') === 'report');
    const captureViews = plan.views.filter(view => String(view?.target || '') !== 'report');
    const snapshot = captureViews.length ? _snapshotScreenshotViewerState() : null;
    let restoreFocus = null;
    const attachments = [];
    try {
        if (reportViews.length) {
            const reportAttachments = await _appendPersistedReportFigures(plan, context, ownerSessionId);
            if (!reportAttachments.length) throw new Error('report_figures_unavailable');
            attachments.push(...reportAttachments);
        }
        if (captureViews.length) {
            const capturePlan = Object.assign({}, plan, { views: captureViews });
            restoreFocus = await _applyStructuredScreenshotPlan(capturePlan);
        }
        for (let index = 0; index < captureViews.length; index += 1) {
            if (!ownerStillActive()) return { success: false, stale: true, error: 'case_changed' };
            const view = captureViews[index];
            const viewTarget = String(view.target || 'full');
            const element = viewTarget === 'dose-overview'
                ? document.body
                : await _prepareScreenshotTarget(viewTarget);
            if (!element) throw new Error(`target_not_found:${viewTarget}`);
            const dataUrl = await _captureScreenshotDataUrl(viewTarget, element);
            if (!await _validateScreenshotDataUrl(dataUrl)) {
                throw new Error(`blank_or_invalid:${viewTarget}`);
            }
            const attachmentId = String(
                view.attachment_id
                || `${context.requestId || 'request'}-${viewTarget}-${index}`
            );
            const fallbackTitle = _localizedScreenshotTargetLabel(
                viewTarget,
                ownerSessionId,
                context.responseLanguage,
            );
            const localizedTitle = _localizedScreenshotText(
                view.title || plan.title,
                fallbackTitle,
                ownerSessionId,
                context.responseLanguage,
            );
            const response = await fetch(API + '/screenshot', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-BrachyBot-Session': ownerSessionId,
                },
                body: JSON.stringify({
                    image: dataUrl,
                    target: viewTarget,
                    description: view.description || plan.description || plan.question || '',
                    title: localizedTitle,
                    mode: plan.mode,
                    layout: plan.layout,
                    request_id: context.requestId,
                    message_id: context.messageId,
                    attachment_id: attachmentId,
                    planning_id: plan.planning_id || '',
                    case_id: plan.case_id || ownerSessionId,
                    data_version: plan.data_version || '',
                    question: plan.question || '',
                    response_language: context.responseLanguage || '',
                    view_metadata: {
                        index,
                        focus: plan.focus || {},
                        object_ids: plan.object_ids || [],
                        data_tree_node_ids: plan.data_tree_node_ids || [],
                        overlays: plan.overlays || {},
                    },
                }),
            });
            const bodyText = await response.text();
            let payload = {};
            try { payload = bodyText ? JSON.parse(bodyText) : {}; } catch (_) {}
            if (!response.ok) throw new Error(payload.error || `upload_failed:${response.status}`);
            const screenshotUrl = payload.url || payload.screenshot_url || payload.path;
            if (!screenshotUrl) throw new Error('missing_screenshot_url');
            const attachment = _appendScreenshotToGallery(
                screenshotUrl,
                viewTarget,
                plan.question,
                context,
                payload.attachment || {
                    id: attachmentId,
                    mode: plan.mode,
                    request_id: context.requestId,
                    message_id: context.messageId,
                    session_id: ownerSessionId,
                },
            );
            if (attachment) attachments.push(attachment);
        }
        return {
            success: attachments.length > 0,
            attachments,
            url: attachments[0]?.url || '',
            target: attachments[0]?.target || target,
            plan,
        };
    } catch (error) {
        if (!ownerStillActive()) return { success: false, stale: true, error: 'case_changed' };
        const errorCode = error?.message || String(error);
        console.warn('[screenshot] capture failed for the owning reply:', errorCode);
        return {
            success: false,
            error: errorCode,
            userMessage: _screenshotFailureMessage(context, errorCode),
            attachments,
            plan,
        };
    } finally {
        await _restoreScreenshotViewerState(snapshot, restoreFocus);
    }
}

window.executeStructuredScreenshotPlan = (plan, context = {}) => _interceptScreenshot(
    plan?.views?.[0]?.target || 'full',
    plan?.question || '',
    context,
    {
        plan,
        mode: plan?.mode || 'chat',
        sessionId: context.sessionId,
        responseLanguage: context.responseLanguage || context.response_language || '',
    },
);

/******** PANEL SWITCHING ********/
