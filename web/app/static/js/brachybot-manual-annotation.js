function setupViewerInteractions() {
    ['axial', 'sagittal', 'coronal'].forEach(axis => {
        const sliceCanvas = getSliceCanvas(axis);
        if (!sliceCanvas) return;
        syncAnnotationCanvasSize(axis);
        setupAnnotationTool(axis);
    });
}

// Export DICOM-RT
async function exportDicomRT() {
    addChat('system', 'Exporting DICOM-RT...');
    try {
        const ctPath = document.getElementById('ctPath').value.trim();
        const res = await fetch(API + '/export/dicom_rt', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ct_path: ctPath }),
        });
        if (res.ok) {
            const data = await res.json();
            if (data.success) {
                addChat('system', `✅ DICOM-RT exported to: ${data.output_dir}`);
            } else {
                addChat('error', `Export failed: ${data.error}`);
            }
        }
    } catch (e) {
        addChat('error', `Export failed: ${e.message}`);
    }
}

// Export STL
async function exportSTL() {
    addChat('system', 'Exporting STL files...');
    try {
        const res = await fetch(API + '/export/stl', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });
        if (res.ok) {
            const data = await res.json();
            if (data.success) {
                addChat('system', `✅ STL exported: ${data.count} files to ${data.output_dir}`);
            } else {
                addChat('error', `Export failed: ${data.error}`);
            }
        }
    } catch (e) {
        addChat('error', `Export failed: ${e.message}`);
    }
}

// Export Report
async function exportReport() {
    addChat('system', 'Generating treatment plan report...');
    try {
        const res = await fetch(API + '/export/report', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });
        if (res.ok) {
            const data = await res.json();
            if (data.success) {
                addChat('system', `✅ Report generated: ${data.report_path}`);
            } else {
                addChat('error', `Report generation failed: ${data.error}`);
            }
        }
    } catch (e) {
        addChat('error', `Report failed: ${e.message}`);
    }
}

// =============================================================================
// STEP-BY-STEP MANUAL PLANNING (2026-06-15)
// The "Step-by-Step" section in the Input panel used to have these
// buttons but their onclick handlers referenced three functions
// (toggleStepButtons / runPlanningStep / showStepResults) that were
// NEVER DECLARED. The user reported "折叠打不开了" — the toggle was
// dead because the function was missing. We restore them here, with
// proper UI feedback (loading spinner, error display, auto-refresh of
// the relevant panel).
//
// Workflow design (product-manager view):
//   1. Load CT (existing Browse button in Image Data section)
//   2. Run CTV segmentation (calls /api/header/info ctv_segmentation)
//   3. Run OAR segmentation
//   4. Run trajectory_init  → first-pass needle paths
//   5. Run trajectory_refine → collision-checked paths
//   6. Run seed_planning    → optimize seed positions
//   7. Run dose_calc        → trained dose_unet_spacing1mm dose distribution
//   8. Run dose_eval        → DVH + V100/D90 + OAR constraints
//   9. View Results (trajectories / seeds / dose / DVH / metrics)
//  10. Export (DICOM-RT / STL / Report PDF)
//
// Each step is a separate button so the user can stop and inspect at any
// point. Its progress belongs to the active server workspace, not localStorage.
// =============================================================================

function _manualState() {
    if (!window.__manualWorkspaceState) {
        window.__manualWorkspaceState = {
            ct_loaded: false,
            ctv_segmentation: false,
            oar_segmentation: false,
            trajectory_init: false,
            trajectory_refine: false,
            seed_planning: false,
            dose_calc: false,
            dose_eval: false,
            last_step: null,
        };
    }
    return window.__manualWorkspaceState;
}
function _saveManualState(patch) {
    Object.assign(_manualState(), patch || {});
    if (typeof window.scheduleWorkspaceSave === 'function') {
        window.scheduleWorkspaceSave('manual.progress');
    }
}

function toggleStepButtons() {
    const sec = document.getElementById('stepButtonsSection');
    const tog = document.getElementById('stepToggle');
    if (!sec) return;
    const wasHidden = sec.style.display === 'none' || !sec.style.display;
    sec.style.display = wasHidden ? 'flex' : 'none';
    if (tog) tog.innerHTML = wasHidden ? '&#9660;' : '&#9654;';
    // If the section is opening, log to the chat so the user has a
    // record of what they did. The buttons themselves emit chat
    // messages on each click.
    if (wasHidden) {
        if (typeof addChat === 'function') {
            addChat('system', 'Manual planning mode: click the step buttons in the Input panel to run each pipeline stage individually.');
        }
    }
}

function _num(id, fallback = null) {
    const el = document.getElementById(id);
    const v = el ? parseFloat(el.value) : NaN;
    return Number.isFinite(v) ? v : fallback;
}

async function applyHyperparams() {
    const refAuto = !!document.getElementById('refDirecAuto')?.checked;
    const config = {
        mode: document.getElementById('useRLToggle')?.checked ? 'rl' : 'rule_based',
        tumor_type: document.getElementById('ctvModelSelect')?.value || 'nnunet_pancreatic',
        seed_info: {
            radius: _num('seedRadius', 0.4),
            length: _num('seedLength', 4.5),
            num_of_seeds: [Math.round(_num('seedCountMin', 5)), Math.round(_num('seedCountMax', 200))],
            margin_rate: _num('seedMarginRate', 1.0),
            seed_avr_dose: _num('seedAvgDose', 50),
        },
        radiation_array_params: {
            target_value: Math.round(_num('targetValue', 1)),
            obstacle_value: Math.round(_num('obstacleValue', 2)),
            background_value: Math.round(_num('backgroundValue', 0)),
        },
        ref_direc_auto: refAuto,
        reference_direc_mode: refAuto ? 'auto' : 'manual',
        reference_direc: refAuto
            ? 'auto'
            : [_num('refDirecX', 0), _num('refDirecY', 1), _num('refDirecZ', 0)],
        in_lowest_energy: _num('inLowestEnergy', 1),
        out_highest_energy: _num('outHighestEnergy', 1),
        DVH_rate: _num('dvhRate', 0.9),
        max_iter: Math.round(_num('maxIter', 4)),
        iter_rate: _num('iterRate', 2),
        replan_rate: _num('replanRate', 0.6),
        distance_filter: {
            lower_bound: _num('distLowerBound', 0.8),
            upper_bound: _num('distUpperBound', 10),
            distance_rate: _num('distRate', 0.8),
            interval_rate: _num('intervalRate', 2),
        },
        direc_resolution: [
            Math.round(_num('direcResCone', 30)),
            Math.round(_num('direcResStep', 3)),
            Math.round(_num('direcResRings', 2)),
        ],
        dl_params: {
            lr: _num('dlLR', 0.0004),
            lr_decay: _num('dlLRDecay', 1.5),
            epochs: Math.round(_num('dlEpochs', 1000)),
            patience: Math.round(_num('dlPatience', 200)),
            search_region: _num('dlSearchRegion', 0.5),
            DVH_margin: _num('dlDVHMargin', 0.05),
            infer_size: [
                Math.round(_num('inferSizeX', 32)),
                Math.round(_num('inferSizeY', 32)),
                Math.round(_num('inferSizeZ', 32)),
            ],
        },
        rf_params: {
            max_episodes: Math.round(_num('rfMaxEpisodes', 100)),
            bandwidth: _num('rfBandwidth', 50),
        },
    };
    try {
        const res = await fetch(API + '/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config),
        });
        const data = await res.json().catch(() => null);
        if (!res.ok || !data || data.error) throw new Error((data && data.error) || `HTTP ${res.status}`);
        addChat('system', 'Hyperparameters applied to the server configuration.');
        reportUIEvent('planning.config', 'Hyperparameters applied', { mode: config.mode });
        return data;
    } catch (e) {
        addChat('error', `Apply hyperparameters failed: ${e.message}`);
        return null;
    }
}

async function runPlanning() {
    const ctPath = ((document.getElementById('ctPath') || {}).value || '').trim();
    if (!ctPath) {
        addChat('error', 'Load CT before running the full planning pipeline.');
        return { success: false, error: 'Load CT before running the full planning pipeline.' };
    }
    await applyHyperparams();
    addChat('system', 'Full planning pipeline started...');
    reportUIEvent('planning.step', 'Full pipeline started', { step: 'full' });
    try {
        const res = await fetch(API + '/planning/run_step', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ct_image_path: ctPath, step: 'full' }),
        });
        const data = await res.json().catch(() => null);
        if (!res.ok || !data || !data.success) throw new Error((data && (data.error || data.message)) || `HTTP ${res.status}`);
        _saveManualState({
            ctv_segmentation: true,
            oar_segmentation: true,
            trajectory_init: true,
            trajectory_refine: true,
            seed_planning: true,
            dose_calc: true,
            dose_eval: true,
            last_step: 'full',
        });
        addChat('system', 'Full planning pipeline completed.');
        reportUIEvent('planning.step', 'Full pipeline completed', { step: 'full' });
        if (typeof _refreshManualStepUI === 'function') _refreshManualStepUI();
        if (typeof refreshPlanningUI === 'function') await refreshPlanningUI();
        if (trainingMonitorState.active) await requestPlanningAdvice();
        return { success: true, step: 'full' };
    } catch (e) {
        addChat('error', `Full planning pipeline failed: ${e.message}`);
        reportUIEvent('planning.error', 'Full pipeline failed', { error: e.message });
        return { success: false, error: e.message };
    }
}

async function runIntra() {
    const ctPath = ((document.getElementById('ctPath') || {}).value || '').trim();
    if (!ctPath) {
        addChat('error', 'Load intra-operative CT before running intraoperative replanning.');
        return;
    }
    const threshold = _num('devThreshold', 2.0);
    addChat('system', `Intraoperative replanning started (deviation threshold ${threshold} mm)...`);
    reportUIEvent('planning.step', 'Intraoperative replanning started', { threshold });
    try {
        const res = await fetch(API + '/plan/intraoperative', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ct_path: ctPath, threshold }),
        });
        const data = await res.json().catch(() => null);
        if (!res.ok || !data || data.error || data.success === false) throw new Error((data && data.error) || `HTTP ${res.status}`);
        addChat('system', 'Intraoperative replanning completed.');
        reportUIEvent('planning.step', 'Intraoperative replanning completed', {});
        if (typeof refreshPlanningUI === 'function') await refreshPlanningUI();
    } catch (e) {
        addChat('error', `Intraoperative replanning failed: ${e.message}`);
    }
}

async function resetSession() {
    try {
        const response = await fetch(API + '/planning/clear', { method: 'POST' });
        if (!response.ok) {
            const data = await response.json().catch(() => null);
            throw new Error(data?.error || `HTTP ${response.status}`);
        }
    } catch (error) {
        const message = `Planning reset failed: ${error.message}`;
        addChat('error', message);
        return { success: false, error: message };
    }
    _saveManualState({
        ctv_segmentation: false,
        oar_segmentation: false,
        trajectory_init: false,
        trajectory_refine: false,
        seed_planning: false,
        dose_calc: false,
        dose_eval: false,
        last_step: null,
    });
    dataTreeState.planning.trajectories = [];
    dataTreeState.planning.trajectoriesLoaded = false;
    dataTreeState.planning.seeds = [];
    dataTreeState.planning.needles = [];
    dataTreeState.planning.doseLevels = [];
    dataTreeState.planning.meshes = [];
    dataTreeState.seeds.loaded = false;
    dataTreeState.needles.loaded = false;
    state.seeds = [];
    state.seedsOverlay = null;
    state.doseOverlay = null;
    state.dvhData = null;
    state.metrics = {};
    Object.keys(scene3D.meshes || {}).forEach(id => {
        if (id.startsWith('seed_') || id.startsWith('needle_') || id.startsWith('dose_iso_')) {
            const mesh = scene3D.meshes[id];
            scene3D.scene?.remove(mesh);
            try { mesh.geometry?.dispose(); } catch (_) {}
            try { mesh.material?.dispose(); } catch (_) {}
            delete scene3D.meshes[id];
        }
    });
    if (typeof drawDVH === 'function') drawDVH._lastSig = null;
    if (typeof _refreshManualStepUI === 'function') _refreshManualStepUI();
    renderDataTree();
    if (state.ctLoaded) await loadAllSlices();
    reportUIEvent('planning.reset', 'Planning state reset', {});
    addChat('system', 'Planning state reset. CT remains loaded.');
    return { success: true };
}

// Run a single planning step manually. The user must have a CT
// loaded first; we surface a clear error if not.
async function runPlanningStep(step) {
    const stepLabels = {
        trajectory_init:  { num: 1, label: 'Trajectory init',  i18n_zh: '轨迹初始化' },
        trajectory_refine:{ num: 2, label: 'Trajectory refine',i18n_zh: '轨迹优化' },
        seed_planning:    { num: 3, label: 'Seed planning',    i18n_zh: '粒子布源' },
        dose_calc:        { num: 4, label: 'Dose calculation', i18n_zh: '剂量计算' },
        dose_eval:        { num: 5, label: 'Dose evaluation',  i18n_zh: '剂量评估' },
    };
    const info = stepLabels[step];
    if (!info) {
        if (typeof addChat === 'function') addChat('error', `Unknown planning step: ${step}`);
        return { success: false, error: `Unknown planning step: ${step}` };
    }
    const ctPathEl = document.getElementById('ctPath');
    const ctPath = ctPathEl ? ctPathEl.value.trim() : '';
    if (!ctPath) {
        if (typeof addChat === 'function') {
            addChat('error', '请先在 Image Data 区域加载 CT 图像,然后再运行规划步骤。');
        }
        return { success: false, error: 'Load CT before running a planning step.' };
    }
    // Validate prerequisite steps are met.
    const st = _manualState();
    const prerequisites = {
        trajectory_init:   { needs: 'ctv_segmentation',     label: 'CTV segmentation' },
        trajectory_refine: { needs: 'trajectory_init',      label: 'Trajectory init' },
        seed_planning:     { needs: 'trajectory_refine',    label: 'Trajectory refine' },
        dose_calc:         { needs: 'seed_planning',        label: 'Seed planning' },
        dose_eval:         { needs: 'dose_calc',            label: 'Dose calculation' },
    };
    const prereq = prerequisites[step];
    if (prereq && !st[prereq.needs]) {
        if (typeof addChat === 'function') {
            addChat('error', `请先完成前置步骤: ${prereq.label} (${prereq.needs})`);
        }
        return { success: false, error: `Complete ${prereq.label} before ${info.label}.` };
    }
    if (typeof addChat === 'function') {
        addChat('system', `▶ Step ${info.num}/5: ${info.label} (${info.i18n_zh})...`);
    }
    // Show a small loading badge next to the clicked button.
    const btn = document.querySelector(`button[onclick="runPlanningStep('${step}')"]`);
    const oldText = btn ? btn.innerHTML : null;
    if (btn) { btn.disabled = true; btn.innerHTML = '... ' + info.label; }
    reportUIEvent('planning.step', `${info.label} started`, { step });
    try {
        const res = await fetch(API + '/planning/run_step', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ct_image_path: ctPath, step: step }),
        });
        if (!res.ok) {
            const errText = await res.text();
            throw new Error(`HTTP ${res.status}: ${errText.slice(0, 200)}`);
        }
        const data = await res.json();
        if (data.success) {
            _saveManualState({ [step]: true, last_step: step });
            reportUIEvent('planning.step', `${info.label} completed`, { step });
            if (typeof addChat === 'function') {
                addChat('system', `✅ Step ${info.num}/5: ${info.label} done.`);
            }
            // Update step button badges (digit → checkmark).
            if (typeof _refreshManualStepUI === 'function') _refreshManualStepUI();
            // Refresh the analysis panel / 3D viewer if available.
            if (typeof refreshPlanningUI === 'function') {
                try { await refreshPlanningUI(); } catch (_) {}
            }
            return { success: true, step };
        } else {
            throw new Error(data.error || 'Unknown error');
        }
    } catch (e) {
        reportUIEvent('planning.error', `${info.label} failed`, { step, error: e.message });
        if (typeof addChat === 'function') {
            addChat('error', `Step ${info.num} (${info.label}) failed: ${e.message}`);
        }
        return { success: false, error: e.message };
    } finally {
        if (btn) { btn.disabled = false; if (oldText) btn.innerHTML = oldText; }
    }
}

// Show specific step results — pushes a summary into the chat and
// also switches the right panel to the Analysis tab so the user
// sees DVH / metrics.
async function showStepResults(step) {
    if (typeof addChat === 'function') {
        addChat('system', `Fetching results for: ${step}...`);
    }
    try {
        const res = await fetch(API + '/planning/show_step', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ step: step }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        // Build a human-friendly summary.
        const lines = [];
        if (step === 'all' || step === 'trajectories') {
            const n = data.num_trajectories || 0;
            lines.push(`**Trajectories**: ${n} candidate needle paths`);
        }
        if (step === 'all' || step === 'seeds' || step === 'seed_planning') {
            const total = data.total_seeds || 0;
            lines.push(`**Seeds**: ${total} seeds placed`);
        }
        if (step === 'all' || step === 'dose' || step === 'dose_distribution') {
            if (data.has_dose) {
                const [lo, hi] = data.dose_range || [0, 0];
                const scaleGy = data.dose_scale_gy
                    || (typeof _getDoseScaleGy === 'function' ? _getDoseScaleGy() : 120);
                lines.push(`**Dose**: normalized range [${lo.toFixed(2)}, ${hi.toFixed(2)}] (${(lo * scaleGy).toFixed(1)}-${(hi * scaleGy).toFixed(1)} Gy)`);
            } else {
                lines.push(`**Dose**: not computed yet`);
            }
        }
        if (step === 'all' || step === 'dvh' || step === 'dose_eval' || step === 'metrics') {
            const m = data.metrics || {};
            if (Object.keys(m).length) {
                lines.push(`**Metrics**: V100=${m.v100 || '-'}, D90=${m.d90 || '-'}`);
            } else {
                lines.push(`**Metrics**: not evaluated yet`);
            }
        }
        if (typeof addChat === 'function') {
            addChat('system', lines.join('\n') || 'No data yet — run the corresponding step first.');
        }
        // Switch right panel to Analysis for visualization.
        const analysisTab = document.querySelector('.panel-tab:nth-child(2)');
        if (analysisTab && typeof switchPanel === 'function') {
            try { switchPanel('metrics', analysisTab); } catch (_) {}
        }
        if (typeof refreshPlanningUI === 'function') {
            try { await refreshPlanningUI(); } catch (_) {}
        }
    } catch (e) {
        if (typeof addChat === 'function') {
            addChat('error', `Show results failed: ${e.message}`);
        }
    }
}

// CTV / OAR segmentation step. These are NOT in the planning pipeline
// (run_step), they're separate tool calls. We expose them as
// Step-by-Step buttons 0 and "0.5" so the user can drive the
// full workflow without going through the LLM.
async function runSegmentationStep(kind) {
    if (kind !== 'ctv_segmentation' && kind !== 'oar_segmentation') {
        if (typeof addChat === 'function') addChat('error', `Unknown segmentation step: ${kind}`);
        return { success: false, error: `Unknown segmentation step: ${kind}` };
    }
    const label = kind === 'ctv_segmentation' ? 'CTV segmentation' : 'OAR segmentation';
    const apiKind = kind === 'ctv_segmentation' ? 'ctv' : 'oar';
    const ctPath = (document.getElementById('ctPath') || {}).value || '';
    if (!ctPath.trim()) {
        if (typeof addChat === 'function') {
            addChat('error', '请先在 Image Data 区域加载 CT 图像,然后再运行分割。');
        }
        return { success: false, error: 'Load CT before running segmentation.' };
    }
    const btn = document.getElementById('stepBtn_' + kind);
    if (btn) {
        btn.disabled = true;
        const numEl = btn.querySelector('.step-num');
        if (numEl) numEl.textContent = '...';
    }
    if (typeof addChat === 'function') {
        addChat('system', `▶ ${label} (${apiKind.toUpperCase()}) — running...`);
    }
    try {
        reportUIEvent('segmentation.step', `${label} started`, { kind });
        const res = await fetch(API + '/segmentation', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                kind: apiKind,
                image_path: ctPath.trim(),
                ...(apiKind === 'ctv' ? {
                    tumor_type: document.getElementById('ctvModelSelect')?.value || 'nnunet_pancreatic',
                } : {}),
            }),
        });
        if (!res.ok) {
            const t = await res.text();
            throw new Error(`HTTP ${res.status}: ${t.slice(0, 200)}`);
        }
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Segmentation failed');
        const n = data.total_labels || Object.keys(data.label_counts || {}).length || 0;
        _saveManualState({ [kind]: true });
        reportUIEvent('segmentation.step', `${label} completed`, { kind, labels: n });
        if (typeof addChat === 'function') {
            addChat('system', `✅ ${label} done — ${n} label(s) found.`);
        }
        if (typeof loadLabelVolumes === 'function') {
            try { await loadLabelVolumes(); } catch (e) { console.warn('[manual segmentation] loadLabelVolumes failed:', e); }
        }
        if (typeof renderDataTree === 'function') {
            try { renderDataTree(); } catch (_) {}
        }
        if (typeof startSegmentationMeshPrewarm === 'function') {
            startSegmentationMeshPrewarm(kind === 'ctv_segmentation' ? 'ctv' : 'oar');
        }
        return { success: true, kind, labels: n };
    } catch (e) {
        reportUIEvent('segmentation.error', `${label} failed`, { kind, error: e.message });
        if (typeof addChat === 'function') {
            addChat('error', `${label} failed: ${e.message}`);
        }
        return { success: false, error: e.message };
    } finally {
        if (btn) {
            btn.disabled = false;
            // The step number reflects state — re-render via _refreshManualStepUI.
            if (typeof _refreshManualStepUI === 'function') _refreshManualStepUI();
        }
    }
}

// Re-evaluate which Step-by-Step buttons should be enabled. The
// chain is:
//   ct loaded         → enables CTV seg
//   CTV segmented     → enables OAR seg AND trajectory_init
//   trajectory_init   → enables trajectory_refine
//   trajectory_refine → enables seed_planning
//   seed_planning     → enables dose_calc
//   dose_calc         → enables dose_eval
// Buttons are also disabled if the corresponding /planning/run_step
// reported a previous success (in manual state).
function _refreshManualStepUI() {
    const s = _manualState();
    const ctPath = ((document.getElementById('ctPath') || {}).value || '').trim();
    const ctLoaded = !!ctPath;
    const ctvDone = !!s.ctv_segmentation;
    const oarDone = !!s.oar_segmentation;
    const trajInit = !!s.trajectory_init;
    const trajRefine = !!s.trajectory_refine;
    const seeds = !!s.seed_planning;
    const dose = !!s.dose_calc;
    const evalDone = !!s.dose_eval;

    function setBtn(id, enabled, num, done) {
        const el = document.getElementById(id);
        if (!el) return;
        el.disabled = !enabled;
        const numEl = el.querySelector('.step-num');
        if (numEl) {
            numEl.textContent = done ? '✓' : String(num);
            numEl.style.color = done ? 'var(--success)' : '';
        }
        // Subtle visual cue for "done"
        if (done) el.style.borderColor = 'var(--success)';
        else el.style.borderColor = '';
    }
    setBtn('stepBtn_ctv_segmentation', ctLoaded, 0, ctvDone);
    setBtn('stepBtn_oar_segmentation', ctvDone, 0, oarDone);
    setBtn('stepBtn_trajectory_init', ctvDone, 1, trajInit);
    setBtn('stepBtn_trajectory_refine', trajInit, 2, trajRefine);
    setBtn('stepBtn_seed_planning', trajRefine, 3, seeds);
    setBtn('stepBtn_dose_calc', seeds, 4, dose);
    setBtn('stepBtn_dose_eval', dose, 5, evalDone);
}

// Wire the Step-by-Step section: re-evaluate button state when the
// CT path input changes, so the buttons react to the user loading
// a CT.
function _wireManualStepInputs() {
    const ctPathEl = document.getElementById('ctPath');
    if (ctPathEl) {
        ctPathEl.addEventListener('input', () => {
            try { _refreshManualStepUI(); } catch (_) {}
        });
        ctPathEl.addEventListener('change', () => {
            try { _refreshManualStepUI(); } catch (_) {}
        });
    }
    // Also re-evaluate when the user lands on the Input panel
    // (in case the CT was loaded programmatically).
    setTimeout(() => { try { _refreshManualStepUI(); } catch (_) {} }, 800);
}

let huFetchTimeout = null;
function fetchHUValue(volX, volY, volZ) {
    if (huFetchTimeout) clearTimeout(huFetchTimeout);

    huFetchTimeout = setTimeout(async () => {
        try {
            const res = await fetch(API + '/viewer/hu', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    x: volX,
                    y: volY,
                    z: volZ,
                }),
            });
            if (res.ok) {
                const data = await res.json();
                if (data.success) {
                    document.getElementById('huDisplay').textContent = `HU: ${data.hu.toFixed(0)} | [${volX}, ${volY}, ${volZ}]`;
                }
            }
        } catch (e) {
            // Ignore errors
        }
    }, 50);
}

function drawLinkedCrosshairs(volX, volY, volZ, sourceAxis) {
    const axes = ['axial', 'sagittal', 'coronal'];
    axes.forEach(axis => {
        const crossCanvas = document.getElementById('crosshairCanvas' + capitalize(axis));
        const sliceCanvas = document.getElementById('sliceCanvas' + capitalize(axis));
        if (!crossCanvas || !sliceCanvas) return;

        // Use CT canvas pixel dimensions (not display dimensions) for consistent alignment
        const w = sliceCanvas.width;
        const h = sliceCanvas.height;
        const displayW = sliceCanvas._displayW || sliceCanvas.offsetWidth;
        const displayH = sliceCanvas._displayH || sliceCanvas.offsetHeight;
        const offsetX = sliceCanvas._offsetX || 0;
        const offsetY = sliceCanvas._offsetY || 0;

        crossCanvas.width = w;
        crossCanvas.height = h;
        crossCanvas.style.width = displayW + 'px';
        crossCanvas.style.height = displayH + 'px';
        crossCanvas.style.position = 'absolute';
        crossCanvas.style.left = offsetX + 'px';
        crossCanvas.style.top = offsetY + 'px';
        crossCanvas.style.display = 'block';
        crossCanvas.style.pointerEvents = 'none';
        crossCanvas.style.zIndex = '6';

        const ctx = crossCanvas.getContext('2d');
        ctx.clearRect(0, 0, w, h);
        ctx.strokeStyle = axis === sourceAxis ? '#ff4444' : '#0ea5e9';
        // Compensate for zoom so line width stays constant
        const zoom = state.viewerSettings.zoom || 1;
        ctx.lineWidth = 1 / zoom;
        ctx.setLineDash([4 / zoom, 4 / zoom]);

        let cx, cy;

        // Get spacing for coordinate conversion
        const spacing = volumeSpacing || [0.68, 0.68, 5.0];

        // Map volume coordinates to canvas pixel coordinates
        // ctShape = [Z, Y, X]
        if (axis === 'axial') {
            cx = (volX / state.ctShape[2]) * w;
            cy = (volY / state.ctShape[1]) * h;
        } else if (axis === 'sagittal') {
            // Canvas: width=Y, height=resampled_Z. Map volZ (original) to resampled position
            cx = (volY / state.ctShape[1]) * w;
            cy = (volZ / state.ctShape[0]) * h;
        } else {
            // Canvas: width=X, height=resampled_Z. Map volZ (original) to resampled position
            cx = (volX / state.ctShape[2]) * w;
            cy = (volZ / state.ctShape[0]) * h;
        }

        // Draw crosshair lines
        ctx.beginPath();
        ctx.moveTo(cx, 0);
        ctx.lineTo(cx, h);
        ctx.stroke();

        ctx.beginPath();
        ctx.moveTo(0, cy);
        ctx.lineTo(w, cy);
        ctx.stroke();
    });
}

function clearLinkedCrosshairs() {
    ['axial', 'sagittal', 'coronal'].forEach(axis => {
        const crossCanvas = document.getElementById('crosshairCanvas' + capitalize(axis));
        if (crossCanvas) {
            crossCanvas.style.display = 'none';
            const ctx = crossCanvas.getContext('2d');
            ctx.clearRect(0, 0, crossCanvas.width, crossCanvas.height);
        }
    });
}

/******** ANNOTATION & MEASUREMENT TOOLS ********/
function getAnnotationCanvas(axis) {
    return document.getElementById('annotationCanvas' + capitalize(axis));
}

function getSliceCanvas(axis) {
    return document.getElementById('sliceCanvas' + capitalize(axis));
}

// Sync the dose overlay layer's size + position to the CT canvas,
// then draw (cached) or fetch (uncached) the slice's dose data.
//
// 2026-06-16 fix: extracted from inside renderSliceFromVolume so it
// runs AFTER the CT canvas's width/height/left/top are finalized.
// Previously the dose canvas was synced using stale CT style values
// (the slider's drag fired updateSlice → renderSliceFromVolume, which
// updated canvas.style.width/left a few lines AFTER the dose sync),
// so the dose layer drifted one slice behind on every drag and
// vanished after a pan/zoom. Now the CT style is set, THEN we
// read it via getBoundingClientRect to copy the actual rendered
// position (this also picks up pan/zoom transforms that the inline
// left/top no longer represent — applyViewerTransform overrides
// those via transform).
// Track last-rendered slice per axis to avoid redundant re-renders
// and to detect stale canvases that need re-painting.
const _doseLastRendered = { axial: -1, sagittal: -1, coronal: -1 };

function _viewerTransformString() {
    const { flipH, flipV, rotation, zoom, panX, panY } = state.viewerSettings;
    const scaleX = flipH ? -1 : 1;
    const scaleY = flipV ? -1 : 1;
    return `rotate(${rotation}deg) scale(${zoom * scaleX}, ${zoom * scaleY}) translate(${panX}px, ${panY}px)`;
}

function _syncLayerToSliceCanvas(axis, layerCanvas, zIndex) {
    const sliceCanvas = getSliceCanvas(axis);
    if (!sliceCanvas || !layerCanvas) return false;
    if (layerCanvas.width !== sliceCanvas.width || layerCanvas.height !== sliceCanvas.height) {
        layerCanvas.width = sliceCanvas.width;
        layerCanvas.height = sliceCanvas.height;
    }
    const sw = sliceCanvas._displayW || sliceCanvas.offsetWidth;
    const sh = sliceCanvas._displayH || sliceCanvas.offsetHeight;
    const sx = sliceCanvas._offsetX || parseFloat(sliceCanvas.style.left) || 0;
    const sy = sliceCanvas._offsetY || parseFloat(sliceCanvas.style.top) || 0;
    layerCanvas.style.position = 'absolute';
    layerCanvas.style.pointerEvents = 'none';
    layerCanvas.style.zIndex = String(zIndex);
    layerCanvas.style.display = 'block';
    layerCanvas.style.width = sw + 'px';
    layerCanvas.style.height = sh + 'px';
    layerCanvas.style.left = sx + 'px';
    layerCanvas.style.top = sy + 'px';
    layerCanvas.style.transform = _viewerTransformString();
    layerCanvas.style.transformOrigin = 'center center';
    return true;
}

function renderDoseForCurrentSlice(axis, sliceIndex) {
    if (!state.doseOverlay || !state.doseOverlay.visible) return;
    const sliceCanvas = getSliceCanvas(axis);
    if (!sliceCanvas) return;
    const doseCanvasId = 'doseOverlayCanvas' + capitalize(axis);
    let doseCanvas = document.getElementById(doseCanvasId);
    if (!doseCanvas) {
        doseCanvas = document.createElement('canvas');
        doseCanvas.id = doseCanvasId;
        const parent = sliceCanvas.parentElement;
        doseCanvas.style.cssText = 'position:absolute;pointer-events:none;z-index:5;display:block;';
        parent.appendChild(doseCanvas);
        sliceCanvas._doseCanvas = doseCanvas;
    }
    _syncLayerToSliceCanvas(axis, doseCanvas, 5);

    const cacheKey = axis + '_' + sliceIndex;
    if (state.doseOverlay.slices[cacheKey]) {
        // Cache hit — render, but skip if this exact slice was already
        // painted on this canvas (prevents redundant work on rapid
        // scroll events that call us multiple times for the same slice).
        if (_doseLastRendered[axis] !== sliceIndex) {
            try { renderDoseOverlayOnLayer(doseCanvas, axis, sliceIndex, state.doseOverlay.slices[cacheKey]); } catch (e) { console.warn(`[dose] render error for ${cacheKey}:`, e); }
            _doseLastRendered[axis] = sliceIndex;
        }
    } else {
        // Cache miss — show nearest cached slice as placeholder, then
        // fetch the actual data from the server.
        _doseLastRendered[axis] = -1; // mark canvas as stale
        const slices = state.doseOverlay.slices;
        let nearestKey = null, nearestDist = Infinity;
        for (const k in slices) {
            if (!k.startsWith(axis + '_')) continue;
            const dist = Math.abs(parseInt(k.split('_')[1]) - sliceIndex);
            if (dist < nearestDist) { nearestDist = dist; nearestKey = k; }
        }
        if (nearestKey && nearestDist <= 5) {
            try { renderDoseOverlayOnLayer(doseCanvas, axis, sliceIndex, slices[nearestKey]); } catch (_) {}
        }
        fetchDoseOverlaySlice(axis, sliceIndex).then(sliceData => {
            if (sliceData && state.slices[axis] === sliceIndex) {
                try {
                    renderDoseOverlayOnLayer(doseCanvas, axis, sliceIndex, sliceData);
                    _doseLastRendered[axis] = sliceIndex;
                } catch (e) { console.warn(`[dose] render error after fetch:`, e); }
            } else {
                uiDebugLog(`[dose] fetch callback skipped: sliceData=${!!sliceData}, axis=${axis}, requested=${sliceIndex}, current=${state.slices[axis]}`);
            }
        });
        preloadDoseSlices(axis, sliceIndex);
    }
}

// ==================== SEED/NEEDLE 2D OVERLAY ====================
// Renders seed positions and needle paths as overlays on 2D CT slices.
// Seeds are drawn as yellow circles, needles as red lines.

function _worldToIndex(wx, wy, wz) {
    // Convert world coordinates (LPS) to CT array index (Z, Y, X)
    // using the inverse of the voxel_to_world transform:
    //   world = (idx[::-1] * spacing) @ direction.T + origin
    //   idx[::-1] = (world - origin) @ direction / spacing
    if (!state.ctOrigin || !state.ctDirection || !state.ctSpacing) return null;
    const origin = state.ctOrigin;
    const spacing = state.ctSpacing;
    const dir = state.ctDirection;
    // Direction matrix 3x3
    const d00=dir[0], d01=dir[1], d02=dir[2];
    const d10=dir[3], d11=dir[4], d12=dir[5];
    const d20=dir[6], d21=dir[7], d22=dir[8];
    // (world - origin)
    const dx = wx - origin[0];
    const dy = wy - origin[1];
    const dz = wz - origin[2];
    // Inverse direction matrix (direction is orthogonal, so inverse = transpose)
    // (dx,dy,dz) @ D^T = (ix*spacing_x, iy*spacing_y, iz*spacing_z) in reversed order
    const r0 = dx*d00 + dy*d10 + dz*d20;
    const r1 = dx*d01 + dy*d11 + dz*d21;
    const r2 = dx*d02 + dy*d12 + dz*d22;
    // Divide by spacing and reverse (x,y,z) → (z,y,x) for numpy array indexing
    const idx_x = r0 / spacing[0];
    const idx_y = r1 / spacing[1];
    const idx_z = r2 / spacing[2];
    return [idx_z, idx_y, idx_x]; // numpy (Z, Y, X) order
}

function _seedCylinderSliceOutline(seed, axis, sliceIndex, orientIdx, toDisplay, axisIdx) {
    const pos = Array.isArray(seed?.position) ? seed.position.map(Number) : null;
    const rawDir = Array.isArray(seed?.direction) ? seed.direction.map(Number) : [0, 0, 1];
    if (!pos || pos.length < 3 || !pos.every(Number.isFinite)) return [];
    const dirLength = Math.hypot(...rawDir);
    if (!Number.isFinite(dirLength) || dirLength < 1e-8) return [];
    const d = rawDir.map(v => v / dirLength);
    const geometry = state.seedsOverlay.geometry || {};
    const length = Math.max(0.1, Number(geometry.length || document.getElementById('seedLength')?.value || 3.7));
    const radius = Math.max(0.05, Number(geometry.radius || document.getElementById('seedRadius')?.value || 0.4));

    // Build an orthonormal basis around the physical seed axis. Sampling the
    // real cylinder surface and clipping it to the current MPR plane keeps
    // the 2D contour faithful for oblique seeds, unlike the old point-circle.
    const ref = Math.abs(d[2]) < 0.9 ? [0, 0, 1] : [0, 1, 0];
    const cross = (a, b) => [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ];
    const norm = v => Math.hypot(...v) || 1;
    let u = cross(d, ref); const un = norm(u); u = u.map(v => v / un);
    let v = cross(d, u); const vn = norm(v); v = v.map(x => x / vn);
    const worldPoint = (t, angle) => {
        const ca = Math.cos(angle), sa = Math.sin(angle);
        return pos.map((base, i) => base + d[i] * t + radius * (u[i] * ca + v[i] * sa));
    };
    const toPlane = world => {
        const idx = _worldToIndex(world[0], world[1], world[2]);
        if (!idx) return null;
        const flipped = orientIdx(idx);
        return { value: flipped[axisIdx], point: toDisplay(flipped) };
    };
    const rows = 12, cols = 24, clipped = [];
    const planeTolerance = 0.75;
    const grid = [];
    for (let row = 0; row <= rows; row++) {
        const t = -length / 2 + length * row / rows;
        grid[row] = [];
        for (let col = 0; col < cols; col++) {
            grid[row][col] = toPlane(worldPoint(t, 2 * Math.PI * col / cols));
        }
    }
    const addCrossing = (a, b) => {
        if (!a || !b) return;
        const da = a.value - sliceIndex, db = b.value - sliceIndex;
        if (Math.abs(da) <= planeTolerance) clipped.push(a.point);
        if (da * db < 0 || Math.abs(db) <= planeTolerance) {
            const t = da === db ? 0.5 : Math.max(0, Math.min(1, da / (da - db)));
            clipped.push({ x: a.point.x + t * (b.point.x - a.point.x), y: a.point.y + t * (b.point.y - a.point.y) });
        }
    };
    for (let row = 0; row <= rows; row++) {
        for (let col = 0; col < cols; col++) {
            addCrossing(grid[row][col], grid[row][(col + 1) % cols]);
            if (row < rows) addCrossing(grid[row][col], grid[row + 1][col]);
        }
    }
    if (clipped.length < 3) return clipped;
    const points = [...new Map(clipped.map(p => [`${p.x.toFixed(3)}:${p.y.toFixed(3)}`, p])).values()];
    const cross2 = (o, a, b) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
    points.sort((a, b) => a.x - b.x || a.y - b.y);
    const lower = [], upper = [];
    for (const p of points) { while (lower.length >= 2 && cross2(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop(); lower.push(p); }
    for (let i = points.length - 1; i >= 0; i--) { const p = points[i]; while (upper.length >= 2 && cross2(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop(); upper.push(p); }
    return lower.slice(0, -1).concat(upper.slice(0, -1));
}

// Product overlay: finite needle projection + true seed-cylinder contour.
// This is the canonical seed/needle overlay implementation.
function renderSeedsOverlay(axis, sliceIndex) {
    if (!state.seedsOverlay || !state.ctShape) return;
    const sliceCanvas = getSliceCanvas(axis);
    if (!sliceCanvas) return;

    const canvasId = 'seedsOverlayCanvas' + capitalize(axis);
    let canvas = document.getElementById(canvasId);
    if (!canvas) {
        canvas = document.createElement('canvas');
        canvas.id = canvasId;
        canvas.style.cssText = 'position:absolute;pointer-events:none;z-index:6;display:block;';
        sliceCanvas.parentElement.appendChild(canvas);
    }
    _syncLayerToSliceCanvas(axis, canvas, 6);
    const w = canvas.width;
    const h = canvas.height;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, w, h);

    const [Z, Y, X] = state.ctShape;
    const geom = _getMprGeometry(axis, [Z, Y, X], volumeSpacing || state.ctSpacing || [0.68, 0.68, 5.0]);
    let axisIdx, dimA, dimB, sizeA, sizeB, zFlipped;
    if (axis === 'axial') {
        axisIdx = 0; dimA = 2; dimB = 1; sizeA = X; sizeB = Y; zFlipped = true;
    } else if (axis === 'sagittal') {
        axisIdx = 2; dimA = 1; dimB = 0; sizeA = Y; sizeB = Z; zFlipped = false;
    } else {
        axisIdx = 1; dimA = 2; dimB = 0; sizeA = X; sizeB = Z; zFlipped = false;
    }

    const scaleX = w / sizeA;
    const scaleY = h / (axis === 'axial' ? sizeB : geom.height);
    const orientIdx = (idx) => zFlipped ? [Z - 1 - idx[0], idx[1], idx[2]] : idx;
    const toDisplay = (idx) => ({
        x: idx[dimA] * scaleX,
        y: (axis === 'axial' ? idx[dimB] : _volumeZToDisplayY(idx[dimB], geom.resampleRatio)) * scaleY,
    });

    const needles = state.seedsOverlay.needles || [];
    for (const needle of needles) {
        const needleState = dataTreeState.planning.needles.find(n => n.id === needle.id);
        if (needleState && needleState.visible === false) continue;
        const needleOpacity = needleState?.opacity ?? needle.opacity ?? 0.8;
        if (needleOpacity <= 0.001) continue;
        const pts = needle.points;
        if (!pts || pts.length < 2) continue;
        const idx0_raw = _worldToIndex(pts[0][0], pts[0][1], pts[0][2]);
        const lastPt = pts[pts.length - 1];
        const idx1_raw = _worldToIndex(lastPt[0], lastPt[1], lastPt[2]);
        if (!idx0_raw || !idx1_raw) continue;
        const idx0 = orientIdx(idx0_raw);
        const idx1 = orientIdx(idx1_raw);
        const s0 = idx0[axisIdx];
        const s1 = idx1[axisIdx];
        const sMin = Math.min(s0, s1);
        const sMax = Math.max(s0, s1);
        if (sliceIndex < sMin || sliceIndex > sMax) continue;

        const p0 = toDisplay(idx0);
        const p1 = toDisplay(idx1);
        // Needle geometry is stored as target/internal first and entry/outer
        // second.  The 2D view intentionally shows only the physical segment
        // from the outer entry to the current slice plane; the full needle is
        // still preserved in world coordinates for 3D editing and replanning.
        const t = Math.abs(s1 - s0) < 1e-6 ? 0.5 : Math.max(0, Math.min(1, (sliceIndex - s0) / (s1 - s0)));
        const hit = { x: p0.x + t * (p1.x - p0.x), y: p0.y + t * (p1.y - p0.y) };
        const segmentStart = p1;
        const segmentEnd = hit;
        const lineLen = Math.hypot(segmentEnd.x - segmentStart.x, segmentEnd.y - segmentStart.y);
        const needleRgb = _hexToRgbArray(needleState?.color || needle.color || '#ff2266', [255, 34, 102]);
        const grad = ctx.createLinearGradient(segmentStart.x, segmentStart.y, segmentEnd.x, segmentEnd.y);
        grad.addColorStop(0, `rgba(56, 189, 248, ${0.25 + 0.55 * needleOpacity})`);
        grad.addColorStop(1, `rgba(${needleRgb[0]}, ${needleRgb[1]}, ${needleRgb[2]}, ${0.25 + 0.65 * needleOpacity})`);

        if (lineLen > 1.5) {
            ctx.save();
            ctx.lineCap = 'round';
            ctx.lineJoin = 'round';
            ctx.strokeStyle = 'rgba(2, 6, 23, 0.85)';
            ctx.lineWidth = 4.2;
            ctx.beginPath();
            ctx.moveTo(segmentStart.x, segmentStart.y);
            ctx.lineTo(segmentEnd.x, segmentEnd.y);
            ctx.stroke();
            ctx.strokeStyle = grad;
            ctx.lineWidth = 2.2;
            ctx.beginPath();
            ctx.moveTo(segmentStart.x, segmentStart.y);
            ctx.lineTo(segmentEnd.x, segmentEnd.y);
            ctx.stroke();
            ctx.restore();
        }
    }

    const seeds = state.seedsOverlay.seeds || [];
    for (const seed of seeds) {
        const seedState = dataTreeState.planning.seeds.find(s => s.id === seed.id);
        if (seedState && seedState.visible === false) continue;
        const baseOpacity = seedState?.opacity ?? seed.opacity ?? 1.0;
        if (baseOpacity <= 0.001) continue;
        const outline = _seedCylinderSliceOutline(seed, axis, sliceIndex, orientIdx, toDisplay, axisIdx);
        if (outline.length < 3) continue;
        const seedRgb = _hexToRgbArray(seedState?.color || seed.color || '#ffcc00', [255, 204, 0]);
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(outline[0].x, outline[0].y);
        outline.slice(1).forEach(p => ctx.lineTo(p.x, p.y));
        ctx.closePath();
        const alpha = 0.95 * baseOpacity;
        ctx.fillStyle = `rgba(${seedRgb[0]}, ${seedRgb[1]}, ${seedRgb[2]}, ${0.18 * alpha})`;
        ctx.fill();
        ctx.strokeStyle = `rgba(${seedRgb[0]}, ${seedRgb[1]}, ${seedRgb[2]}, ${alpha})`;
        ctx.lineWidth = 1.4;
        ctx.stroke();
        ctx.restore();
    }
}

function syncAnnotationCanvasSize(axis) {
    const sliceCanvas = getSliceCanvas(axis);
    const annCanvas = getAnnotationCanvas(axis);
    if (!sliceCanvas || !annCanvas) return;

    const displayW = sliceCanvas._displayW || sliceCanvas.offsetWidth;
    const displayH = sliceCanvas._displayH || sliceCanvas.offsetHeight;
    const offsetX = sliceCanvas._offsetX || 0;
    const offsetY = sliceCanvas._offsetY || 0;

    annCanvas.width = displayW;
    annCanvas.height = displayH;
    annCanvas.style.width = displayW + 'px';
    annCanvas.style.height = displayH + 'px';
    annCanvas.style.position = 'absolute';
    // Only reposition if container size changed
    if (!annCanvas._posSet || annCanvas._posOffsetX !== offsetX || annCanvas._posOffsetY !== offsetY) {
        annCanvas.style.left = offsetX + 'px';
        annCanvas.style.top = offsetY + 'px';
        annCanvas._posSet = true;
        annCanvas._posOffsetX = offsetX;
        annCanvas._posOffsetY = offsetY;
    }
    annCanvas.style.display = 'block';
    annCanvas.style.pointerEvents = 'none';
}

function redrawAllAnnotations() {
    ['axial', 'sagittal', 'coronal'].forEach(axis => {
        const annCanvas = getAnnotationCanvas(axis);
        if (!annCanvas) return;
        const ctx = annCanvas.getContext('2d');
        ctx.clearRect(0, 0, annCanvas.width, annCanvas.height);

        state.annotations.filter(a => a.axis === axis).forEach(ann => {
            drawAnnotation(ctx, ann);
        });
    });
}

function drawAnnotation(ctx, ann) {
    ctx.save();
    ctx.strokeStyle = ann.color || '#00ff00';
    ctx.fillStyle = ann.color || '#00ff00';
    ctx.lineWidth = 2;
    ctx.font = '12px monospace';

    if (ann.type === 'line') {
        ctx.beginPath();
        ctx.moveTo(ann.x1, ann.y1);
        ctx.lineTo(ann.x2, ann.y2);
        ctx.stroke();

        // Draw endpoints
        ctx.beginPath();
        ctx.arc(ann.x1, ann.y1, 4, 0, Math.PI * 2);
        ctx.arc(ann.x2, ann.y2, 4, 0, Math.PI * 2);
        ctx.fill();

        // Distance label with real mm
        const dx = ann.x2 - ann.x1;
        const dy = ann.y2 - ann.y1;
        const distMm = Math.sqrt(
            Math.pow(dx * (ann.spacingX || 0.68), 2) +
            Math.pow(dy * (ann.spacingY || 0.68), 2)
        ).toFixed(1);
        const midX = (ann.x1 + ann.x2) / 2;
        const midY = (ann.y1 + ann.y2) / 2;
        ctx.fillStyle = '#000';
        ctx.fillRect(midX - 30, midY - 10, 60, 16);
        ctx.fillStyle = ann.color || '#00ff00';
        ctx.textAlign = 'center';
        ctx.fillText(`${distMm} mm`, midX, midY + 3);
    } else if (ann.type === 'angle') {
        ctx.beginPath();
        ctx.moveTo(ann.x1, ann.y1);
        ctx.lineTo(ann.x2, ann.y2);
        ctx.lineTo(ann.x3, ann.y3);
        ctx.stroke();

        // Draw endpoints
        ctx.beginPath();
        ctx.arc(ann.x1, ann.y1, 4, 0, Math.PI * 2);
        ctx.arc(ann.x2, ann.y2, 4, 0, Math.PI * 2);
        ctx.arc(ann.x3, ann.y3, 4, 0, Math.PI * 2);
        ctx.fill();

        // Use pre-calculated angle or calculate
        const angleDeg = ann.angleDeg != null ? ann.angleDeg.toFixed(1) : (() => {
            const v1x = ann.x1 - ann.x2, v1y = ann.y1 - ann.y2;
            const v2x = ann.x3 - ann.x2, v2y = ann.y3 - ann.y2;
            const dot = v1x * v2x + v1y * v2y;
            const mag1 = Math.sqrt(v1x * v1x + v1y * v1y);
            const mag2 = Math.sqrt(v2x * v2x + v2y * v2y);
            return (Math.acos(Math.max(-1, Math.min(1, dot / (mag1 * mag2 || 1)))) * 180 / Math.PI).toFixed(1);
        })();

        // Draw angle arc
        const a1 = Math.atan2(ann.y1 - ann.y2, ann.x1 - ann.x2);
        const a2 = Math.atan2(ann.y3 - ann.y2, ann.x3 - ann.x2);
        ctx.beginPath();
        ctx.arc(ann.x2, ann.y2, 20, Math.min(a1, a2), Math.max(a1, a2));
        ctx.strokeStyle = ann.color || '#ffaa00';
        ctx.lineWidth = 1.5;
        ctx.stroke();

        ctx.fillStyle = '#000';
        ctx.fillRect(ann.x2 - 25, ann.y2 - 28, 50, 16);
        ctx.fillStyle = ann.color || '#ffaa00';
        ctx.textAlign = 'center';
        ctx.font = '11px monospace';
        ctx.fillText(`${angleDeg}°`, ann.x2, ann.y2 - 16);
    } else if (ann.type === 'rect') {
        ctx.strokeRect(ann.x1, ann.y1, ann.x2 - ann.x1, ann.y2 - ann.y1);

        // Dimension labels with real mm
        const widthMm = (Math.abs(ann.x2 - ann.x1) * (ann.spacingX || 0.68)).toFixed(1);
        const heightMm = (Math.abs(ann.y2 - ann.y1) * (ann.spacingY || 0.68)).toFixed(1);
        ctx.fillStyle = '#000';
        ctx.fillRect(ann.x1, ann.y1 - 16, 80, 14);
        ctx.fillStyle = ann.color || '#00ff00';
        ctx.textAlign = 'left';
        ctx.fillText(`${widthMm}x${heightMm}mm`, ann.x1 + 2, ann.y1 - 5);
    } else if (ann.type === 'freehand') {
        if (ann.points && ann.points.length > 1) {
            ctx.beginPath();
            ctx.moveTo(ann.points[0].x, ann.points[0].y);
            for (let i = 1; i < ann.points.length; i++) {
                ctx.lineTo(ann.points[i].x, ann.points[i].y);
            }
            ctx.stroke();
        }
    }
    ctx.restore();
}

function pushUndo(annotation) {
    state.annotationUndoStack.push(annotation);
    state.annotationRedoStack = [];
}

/******** MANUAL MASK DRAWING ********/
const MASK_COLORS = ['#ff4444','#44ff44','#4488ff','#ffaa00','#ff44ff','#44ffff','#ffff44','#ff8844'];

function createMaskFromFreehand(axis, points) {
    if (!state.ctShape || points.length < 3) return;
    state.maskLabelCounter++;
    const id = 'mask_' + state.maskLabelCounter;
    const color = MASK_COLORS[(state.maskLabelCounter - 1) % MASK_COLORS.length];

    // Create a canvas to rasterize the polygon
    const sliceCanvas = getSliceCanvas(axis);
    const w = sliceCanvas.width;
    const h = sliceCanvas.height;
    const displayScale = sliceCanvas._displayScale || 1;

    const maskCanvas = document.createElement('canvas');
    maskCanvas.width = w;
    maskCanvas.height = h;
    const mctx = maskCanvas.getContext('2d');
    mctx.fillStyle = '#fff';
    mctx.beginPath();
    mctx.moveTo(points[0].x / displayScale, points[0].y / displayScale);
    for (let i = 1; i < points.length; i++) {
        mctx.lineTo(points[i].x / displayScale, points[i].y / displayScale);
    }
    mctx.closePath();
    mctx.fill();

    const maskData = mctx.getImageData(0, 0, w, h).data;

    // Convert to voxel coordinates
    const voxelSet = new Set();
    for (let py = 0; py < h; py++) {
        for (let px = 0; px < w; px++) {
            const idx = (py * w + px) * 4;
            if (maskData[idx] > 128) {
                let volX, volY, volZ;
                if (axis === 'axial') {
                    volX = px; volY = py; volZ = state.slices.axial;
                } else if (axis === 'sagittal') {
                    volX = state.slices.sagittal; volY = px;
                    const spacing = window.volumeSpacing || [0.68, 0.68, 5.0];
                    volZ = Math.round(py * spacing[1] / spacing[2]);
                } else {
                    volX = px; volY = state.slices.coronal;
                    const spacing = window.volumeSpacing || [0.68, 0.68, 5.0];
                    volZ = Math.round(py * spacing[0] / spacing[2]);
                }
                if (volX >= 0 && volX < state.ctShape[2] && volY >= 0 && volY < state.ctShape[1] && volZ >= 0 && volZ < state.ctShape[0]) {
                    voxelSet.add(`${volX},${volY},${volZ}`);
                }
            }
        }
    }

    state.maskLabels[id] = {
        name: `Manual Mask ${state.maskLabelCounter}`,
        color: color,
        voxels: voxelSet,
        visible: true,
        opacity: 0.6,
        axis: axis,
    };

    renderDataTree();
    reloadOverlays();
    addChat('system', `Created mask "${state.maskLabels[id].name}" with ${voxelSet.size} voxels`);
}

function eraseMaskArea(axis, points) {
    if (!state.ctShape || points.length < 3) return;

    const sliceCanvas = getSliceCanvas(axis);
    const w = sliceCanvas.width;
    const h = sliceCanvas.height;
    const displayScale = sliceCanvas._displayScale || 1;

    const maskCanvas = document.createElement('canvas');
    maskCanvas.width = w;
    maskCanvas.height = h;
    const mctx = maskCanvas.getContext('2d');
    mctx.fillStyle = '#fff';
    mctx.beginPath();
    mctx.moveTo(points[0].x / displayScale, points[0].y / displayScale);
    for (let i = 1; i < points.length; i++) {
        mctx.lineTo(points[i].x / displayScale, points[i].y / displayScale);
    }
    mctx.closePath();
    mctx.fill();

    const maskData = mctx.getImageData(0, 0, w, h).data;

    // Erase from all visible masks
    let erased = 0;
    for (const [id, mask] of Object.entries(state.maskLabels)) {
        if (!mask.visible) continue;
        for (let py = 0; py < h; py++) {
            for (let px = 0; px < w; px++) {
                const idx = (py * w + px) * 4;
                if (maskData[idx] > 128) {
                    let volX, volY, volZ;
                    if (axis === 'axial') {
                        volX = px; volY = py; volZ = state.slices.axial;
                    } else if (axis === 'sagittal') {
                        volX = state.slices.sagittal; volY = px;
                        const spacing = window.volumeSpacing || [0.68, 0.68, 5.0];
                        volZ = Math.round(py * spacing[1] / spacing[2]);
                    } else {
                        volX = px; volY = state.slices.coronal;
                        const spacing = window.volumeSpacing || [0.68, 0.68, 5.0];
                        volZ = Math.round(py * spacing[0] / spacing[2]);
                    }
                    const key = `${volX},${volY},${volZ}`;
                    if (mask.voxels.has(key)) {
                        mask.voxels.delete(key);
                        erased++;
                    }
                }
            }
        }
    }

    if (erased > 0) {
        renderDataTree();
        reloadOverlays();
        addChat('system', `Erased ${erased} voxels from masks`);
    }
}

function viewerUndo() {
    if (state.annotationUndoStack.length === 0) return;
    const ann = state.annotationUndoStack.pop();
    state.annotations = state.annotations.filter(a => a !== ann);
    state.annotationRedoStack.push(ann);
    redrawAllAnnotations();
}

function viewerRedo() {
    if (state.annotationRedoStack.length === 0) return;
    const ann = state.annotationRedoStack.pop();
    state.annotations.push(ann);
    state.annotationUndoStack.push(ann);
    redrawAllAnnotations();
}

function viewerFlipH() {
    state.viewerSettings.flipH = !state.viewerSettings.flipH;
    applyViewerTransform();
}

function viewerFlipV() {
    state.viewerSettings.flipV = !state.viewerSettings.flipV;
    applyViewerTransform();
}

function viewerRotate() {
    state.viewerSettings.rotation = (state.viewerSettings.rotation + 90) % 360;
    applyViewerTransform();
}

function applyViewerTransform() {
    const transform = _viewerTransformString();

    ['axial', 'sagittal', 'coronal'].forEach(axis => {
        const canvas = getSliceCanvas(axis);
        // BUG FIX 2026-06-16 (dose map persistence, FINAL): if
        // the slice canvas has been wrapped in a transform-host
        // (because the dose overlay was activated), apply the
        // transform to the WRAPPER so both slice and dose move
        // together. Otherwise apply to the canvas directly.
        const wrapper = canvas && canvas._doseWrapper;
        const transformTarget = wrapper || canvas;
        if (transformTarget) {
            transformTarget.style.transform = transform;
            transformTarget.style.transformOrigin = 'center center';
        }
        const annCanvas = getAnnotationCanvas(axis);
        if (annCanvas) {
            annCanvas.style.transform = transform;
            annCanvas.style.transformOrigin = 'center center';
        }
        const crossCanvas = document.getElementById('crosshairCanvas' + capitalize(axis));
        if (crossCanvas) {
            crossCanvas.style.transform = transform;
            crossCanvas.style.transformOrigin = 'center center';
        }
        // Apply same transform to overlay div
        const overlayDiv = document.getElementById('labelOverlay_' + capitalize(axis));
        if (overlayDiv) {
            overlayDiv.style.transform = transform;
            overlayDiv.style.transformOrigin = 'center center';
        }
        // Apply same transform to dose overlay canvas (sibling of
        // slice canvas, NOT inside wrapper — must be explicit).
        const doseCanvas = document.getElementById('doseOverlayCanvas' + capitalize(axis));
        if (doseCanvas) {
            doseCanvas.style.transform = transform;
            doseCanvas.style.transformOrigin = 'center center';
        }
        const contourCanvas = document.getElementById('contourCanvas' + capitalize(axis));
        if (contourCanvas) {
            contourCanvas.style.transform = transform;
            contourCanvas.style.transformOrigin = 'center center';
        }
        const seedsCanvas = document.getElementById('seedsOverlayCanvas' + capitalize(axis));
        if (seedsCanvas) {
            seedsCanvas.style.transform = transform;
            seedsCanvas.style.transformOrigin = 'center center';
        }
    });
}

function screenToImageCoords(axis, screenX, screenY) {
    const sliceCanvas = getSliceCanvas(axis);
    if (!sliceCanvas) return { x: screenX, y: screenY, displayX: screenX, displayY: screenY };

    const rect = sliceCanvas.getBoundingClientRect();
    const displayScale = sliceCanvas._displayScale || 1;
    const zoom = state.viewerSettings.zoom || 1;

    // Account for zoom scaling
    const canvasX = (screenX - rect.left) / zoom;
    const canvasY = (screenY - rect.top) / zoom;

    // Convert to image coordinates
    const imgX = canvasX / displayScale;
    const imgY = canvasY / displayScale;

    return { x: imgX, y: imgY, displayX: canvasX, displayY: canvasY };
}

function setupAnnotationTool(axis) {
    const sliceCanvas = getSliceCanvas(axis);
    if (!sliceCanvas) return;

    // Don't re-setup if already done
    if (sliceCanvas._annotationSetup) return;
    sliceCanvas._annotationSetup = true;

    // Use global tool state so setViewerTool can reset it
    if (!window._annotationToolState) {
        window._annotationToolState = { active: false, startX: 0, startY: 0, currentX: 0, currentY: 0, points: [] };
    }
    const toolState = window._annotationToolState;

    // Setup basic interactions (wheel, drag, crosshair)
    setupBasicInteractions(axis, sliceCanvas);

    // Annotation overlay canvas for drawing preview
    const annCanvas = getAnnotationCanvas(axis);

    sliceCanvas.addEventListener('mousedown', (e) => {
        const tool = state.viewerSettings.activeTool;
        if (tool === 'crosshair' || !tool) return;
        if (e.button !== 0) return;

        const coords = screenToImageCoords(axis, e.clientX, e.clientY);
        toolState.active = true;
        toolState.startX = coords.displayX;
        toolState.startY = coords.displayY;
        toolState.currentX = coords.displayX;
        toolState.currentY = coords.displayY;
        // Don't reset points for angle tool (accumulates across clicks)
        if (tool !== 'angle') {
            toolState.points = [{ x: coords.displayX, y: coords.displayY }];
        }

        if (tool === 'annotate' || tool === 'eraser') {
            annCanvas.style.pointerEvents = 'auto';
        }
    });

    sliceCanvas.addEventListener('mousemove', (e) => {
        const coords = screenToImageCoords(axis, e.clientX, e.clientY);
        toolState.currentX = coords.displayX;
        toolState.currentY = coords.displayY;

        // Collect points for freehand/eraser tools only (angle collects on mouseup)
        const tool = state.viewerSettings.activeTool;
        if (toolState.active && (tool === 'annotate' || tool === 'eraser')) {
            toolState.points.push({ x: coords.displayX, y: coords.displayY });
        }

        // Preview drawing
        if (tool === 'crosshair' || !tool || !toolState.active) return;

        const ctx = annCanvas.getContext('2d');
        ctx.clearRect(0, 0, annCanvas.width, annCanvas.height);

        // Redraw existing annotations for this axis
        state.annotations.filter(a => a.axis === axis).forEach(ann => drawAnnotation(ctx, ann));

        ctx.save();
        ctx.strokeStyle = '#00ff00';
        ctx.lineWidth = 2;
        ctx.setLineDash([5, 5]);

        if (tool === 'measure' || tool === 'zoombox') {
            ctx.beginPath();
            ctx.moveTo(toolState.startX, toolState.startY);
            ctx.lineTo(toolState.currentX, toolState.currentY);
            ctx.stroke();

            if (tool === 'measure') {
                const dx = toolState.currentX - toolState.startX;
                const dy = toolState.currentY - toolState.startY;
                const volSpacing = window.volumeSpacing || [0.68, 0.68, 5.0];
                let sx, sy;
                if (axis === 'axial') { sx = volSpacing[0]; sy = volSpacing[1]; }
                else if (axis === 'sagittal') { sx = volSpacing[1]; sy = volSpacing[2]; }
                else { sx = volSpacing[0]; sy = volSpacing[2]; }
                const distMm = Math.sqrt(Math.pow(dx * sx, 2) + Math.pow(dy * sy, 2)).toFixed(1);
                const midX = (toolState.startX + toolState.currentX) / 2;
                const midY = (toolState.startY + toolState.currentY) / 2;
                ctx.setLineDash([]);
                ctx.fillStyle = '#000';
                ctx.fillRect(midX - 30, midY - 10, 60, 16);
                ctx.fillStyle = '#00ff00';
                ctx.textAlign = 'center';
                ctx.font = '12px monospace';
                ctx.fillText(`${distMm} mm`, midX, midY + 3);
            }
        } else if (tool === 'angle') {
            // Draw existing points
            toolState.points.forEach(p => {
                ctx.beginPath();
                ctx.arc(p.x, p.y, 4, 0, Math.PI * 2);
                ctx.fillStyle = '#00ff00';
                ctx.fill();
            });
            if (toolState.points.length > 0) {
                ctx.beginPath();
                ctx.moveTo(toolState.points[0].x, toolState.points[0].y);
                toolState.points.slice(1).forEach(p => ctx.lineTo(p.x, p.y));
                ctx.lineTo(toolState.currentX, toolState.currentY);
                ctx.stroke();
            }
            // Show angle preview if 2 points placed
            if (toolState.points.length === 2) {
                const p = toolState.points;
                const v1x = p[0].x - p[1].x, v1y = p[0].y - p[1].y;
                const v2x = toolState.currentX - p[1].x, v2y = toolState.currentY - p[1].y;
                const dot = v1x * v2x + v1y * v2y;
                const mag1 = Math.sqrt(v1x * v1x + v1y * v1y);
                const mag2 = Math.sqrt(v2x * v2x + v2y * v2y);
                if (mag1 > 2 && mag2 > 2) {
                    const angle = (Math.acos(Math.max(-1, Math.min(1, dot / (mag1 * mag2)))) * 180 / Math.PI).toFixed(1);
                    ctx.setLineDash([]);
                    ctx.fillStyle = '#000';
                    ctx.fillRect(p[1].x - 25, p[1].y - 28, 50, 16);
                    ctx.fillStyle = '#ffaa00';
                    ctx.textAlign = 'center';
                    ctx.font = '11px monospace';
                    ctx.fillText(`${angle}°`, p[1].x, p[1].y - 16);
                }
            }
        } else if (tool === 'rect') {
            ctx.strokeRect(toolState.startX, toolState.startY,
                          toolState.currentX - toolState.startX,
                          toolState.currentY - toolState.startY);
        } else if (tool === 'annotate' || tool === 'eraser') {
            if (toolState.points.length > 1) {
                ctx.beginPath();
                ctx.moveTo(toolState.points[0].x, toolState.points[0].y);
                toolState.points.slice(1).forEach(p => ctx.lineTo(p.x, p.y));
                ctx.stroke();
            }
        }
        ctx.restore();
    });

    sliceCanvas.addEventListener('mouseup', (e) => {
        if (!toolState.active) return;
        toolState.active = false;

        const tool = state.viewerSettings.activeTool;
        if (tool === 'crosshair' || !tool) return;

        const coords = screenToImageCoords(axis, e.clientX, e.clientY);
        toolState.currentX = coords.displayX;
        toolState.currentY = coords.displayY;

        const volSpacing = window.volumeSpacing || [0.68, 0.68, 5.0];
        // Get pixel spacing for this axis
        let pxSpacingX, pxSpacingY;
        if (axis === 'axial') { pxSpacingX = volSpacing[0]; pxSpacingY = volSpacing[1]; }
        else if (axis === 'sagittal') { pxSpacingX = volSpacing[1]; pxSpacingY = volSpacing[2]; }
        else { pxSpacingX = volSpacing[0]; pxSpacingY = volSpacing[2]; }
        let annotation = null;

        if (tool === 'measure') {
            annotation = {
                type: 'line',
                axis: axis,
                x1: toolState.startX, y1: toolState.startY,
                x2: toolState.currentX, y2: toolState.currentY,
                spacingX: pxSpacingX, spacingY: pxSpacingY,
                color: '#00ff00',
            };
        } else if (tool === 'angle') {
            toolState.points.push({ x: toolState.currentX, y: toolState.currentY });
            if (toolState.points.length >= 3) {
                const p = toolState.points;
                // Calculate angle at p1 between vectors p0->p1 and p2->p1
                const v1x = p[0].x - p[1].x, v1y = p[0].y - p[1].y;
                const v2x = p[2].x - p[1].x, v2y = p[2].y - p[1].y;
                const dot = v1x * v2x + v1y * v2y;
                const mag1 = Math.sqrt(v1x * v1x + v1y * v1y);
                const mag2 = Math.sqrt(v2x * v2x + v2y * v2y);
                const angleDeg = (Math.acos(Math.max(-1, Math.min(1, dot / (mag1 * mag2 || 1)))) * 180 / Math.PI);
                annotation = {
                    type: 'angle',
                    axis: axis,
                    x1: p[0].x, y1: p[0].y,
                    x2: p[1].x, y2: p[1].y,
                    x3: p[2].x, y3: p[2].y,
                    angleDeg: angleDeg,
                    color: '#ffaa00',
                };
                toolState.points = [];
            }
        } else if (tool === 'rect') {
            annotation = {
                type: 'rect',
                axis: axis,
                x1: toolState.startX, y1: toolState.startY,
                x2: toolState.currentX, y2: toolState.currentY,
                pixelSpacing: spacing,
                color: '#00aaff',
            };
        } else if (tool === 'annotate') {
            if (toolState.points.length > 2) {
                annotation = {
                    type: 'freehand',
                    axis: axis,
                    points: [...toolState.points],
                    color: '#ff00ff',
                };
                // Create mask from freehand
                createMaskFromFreehand(axis, toolState.points);
            }
            toolState.points = [];
        } else if (tool === 'eraser') {
            if (toolState.points.length > 2) {
                eraseMaskArea(axis, toolState.points);
            }
            toolState.points = [];
        } else if (tool === 'zoombox') {
            // Apply zoom to box
            const dx = Math.abs(toolState.currentX - toolState.startX);
            const dy = Math.abs(toolState.currentY - toolState.startY);
            if (dx > 20 && dy > 20) {
                const boxCenterX = (toolState.startX + toolState.currentX) / 2;
                const boxCenterY = (toolState.startY + toolState.currentY) / 2;
                const sliceCanvas = getSliceCanvas(axis);
                const containerW = sliceCanvas._displayW || sliceCanvas.offsetWidth;
                const containerH = sliceCanvas._displayH || sliceCanvas.offsetHeight;

                const zoomFactor = Math.min(containerW / dx, containerH / dy);
                state.viewerSettings.zoom = Math.min(zoomFactor, 10);
                state.viewerSettings.panX = (containerW / 2 - boxCenterX) * state.viewerSettings.zoom;
                state.viewerSettings.panY = (containerH / 2 - boxCenterY) * state.viewerSettings.zoom;
                applyViewerTransform();
                document.getElementById('viewerZoom').value = Math.round(state.viewerSettings.zoom * 100);
                document.getElementById('zoomLabel').textContent = Math.round(state.viewerSettings.zoom * 100) + '%';
            }
        }

        if (annotation) {
            state.annotations.push(annotation);
            pushUndo(annotation);
        }

        // Redraw
        const ctx = annCanvas.getContext('2d');
        ctx.clearRect(0, 0, annCanvas.width, annCanvas.height);
        redrawAllAnnotations();

        if (tool !== 'annotate') {
            annCanvas.style.pointerEvents = 'none';
        }
    });

    sliceCanvas.addEventListener('mouseleave', () => {
        toolState.active = false;
    });
}

function setupBasicInteractions(axis, canvas) {
    // Mouse wheel: scroll slices
    canvas.addEventListener('wheel', (e) => {
        e.preventDefault();
        // Ctrl+scroll = zoom in/out
        if (e.ctrlKey || e.metaKey) {
            const delta = e.deltaY > 0 ? -0.1 : 0.1;
            let newZoom = (state.viewerSettings.zoom || 1) + delta;
            newZoom = Math.max(0.5, Math.min(3.0, newZoom));
            state.viewerSettings.zoom = newZoom;
            applyViewerTransform();
            return;
        }
        // Normal scroll = slice navigation
        const slider = document.getElementById('slider' + capitalize(axis));
        if (!slider) return;
        const delta = e.deltaY > 0 ? 1 : -1;
        let newVal = parseInt(slider.value) + delta;
        const maxVal = parseInt(slider.max) || 100;
        newVal = Math.max(0, Math.min(maxVal, newVal));
        slider.value = newVal;
        updateSlice(axis, newVal);
    }, { passive: false });

    // Mouse drag: window/level or pan
    let isDragging = false;
    let dragStart = { x: 0, y: 0 };
    let wlStart = { w: 0, l: 0 };

    canvas.addEventListener('mousedown', (e) => {
        const tool = state.viewerSettings.activeTool;
        if (tool && tool !== 'crosshair') return; // Let annotation tool handle it
        if (e.button !== 0) return;
        isDragging = true;
        dragStart = { x: e.clientX, y: e.clientY };
        wlStart = { w: state.viewerSettings.window, l: state.viewerSettings.level };
        canvas.style.cursor = 'crosshair';
    });

    canvas.addEventListener('mousemove', (e) => {
        const rect = canvas.getBoundingClientRect();
        const displayScale = canvas._displayScale || 1;
        const zoom = state.viewerSettings.zoom || 1;
        // rect.left includes CSS position; account for zoom scaling
        const mouseX = (e.clientX - rect.left) / zoom;
        const mouseY = (e.clientY - rect.top) / zoom;
        const imgX = Math.floor(mouseX / displayScale);
        const imgY = Math.floor(mouseY / displayScale);

        // Linked MPR crosshairs
        if (state.ctShape && (!state.viewerSettings.activeTool || state.viewerSettings.activeTool === 'crosshair')) {
            const zAxial = state.slices.axial;
            const zSag = state.slices.sagittal;
            const zCor = state.slices.coronal;

            // Get spacing for coordinate conversion
            const spacing = volumeSpacing || [0.68, 0.68, 5.0];

            let volX, volY, volZ;
            if (axis === 'axial') {
                // axial: imgX = X, imgY = Y
                volX = imgX; volY = imgY; volZ = zAxial;
            } else if (axis === 'sagittal') {
                // sagittal: imgX = Y, imgY = Z (resampled)
                // Need to convert from resampled Z to original Z
                const resampleRatio = _getMprGeometry('sagittal', state.ctShape, spacing).resampleRatio;
                volX = zSag; volY = imgX; volZ = Math.round(imgY / resampleRatio);
            } else {
                // coronal: imgX = X, imgY = Z (resampled)
                const resampleRatio = _getMprGeometry('coronal', state.ctShape, spacing).resampleRatio;
                volX = imgX; volY = zCor; volZ = Math.round(imgY / resampleRatio);
            }

            if (volX >= 0 && volX < state.ctShape[2] && volY >= 0 && volY < state.ctShape[1] && volZ >= 0 && volZ < state.ctShape[0]) {
                drawLinkedCrosshairs(volX, volY, volZ, axis);
                fetchHUValue(volX, volY, volZ);

                // Update other viewers' slice positions on click (isDragging is set on mousedown)
                if (isDragging) {
                    const updates = {};
                    if (axis === 'axial') {
                        updates.sagittal = volX;
                        updates.coronal = volY;
                    } else if (axis === 'sagittal') {
                        updates.axial = volZ;
                        updates.coronal = volY;
                    } else {
                        updates.axial = volZ;
                        updates.sagittal = volX;
                    }

                    Object.entries(updates).forEach(([view, sliceIdx]) => {
                        const slider = document.getElementById('slider' + capitalize(view));
                        if (slider) {
                            sliceIdx = Math.max(0, Math.min(parseInt(slider.max), Math.round(sliceIdx)));
                            slider.value = sliceIdx;
                            updateSlice(view, sliceIdx);
                        }
                    });
                }
            }
        }

        if (!isDragging) return;
        const dx = e.clientX - dragStart.x;
        const dy = e.clientY - dragStart.y;

        if (e.buttons === 1 && !e.shiftKey) {
            state.viewerSettings.panX += dx;
            state.viewerSettings.panY += dy;
            applyViewerTransform();
            dragStart = { x: e.clientX, y: e.clientY };
        } else if (e.buttons === 1 && e.shiftKey) {
            state.viewerSettings.window = Math.max(1, wlStart.w + dx * 2);
            state.viewerSettings.level = wlStart.l + dy * 2;
            document.getElementById('viewerWindow').value = Math.round(state.viewerSettings.window);
            document.getElementById('viewerLevel').value = Math.round(state.viewerSettings.level);
            loadSlice(axis, state.slices[axis]);
        }
    });

    canvas.addEventListener('mouseup', () => {
        isDragging = false;
        canvas.style.cursor = '';
    });
    canvas.addEventListener('mouseleave', () => {
        isDragging = false;
        canvas.style.cursor = '';
        document.getElementById('huDisplay').textContent = '';
        clearLinkedCrosshairs();
    });

    // Double-click: navigate all viewers to clicked position
    canvas.addEventListener('dblclick', (e) => {
        e.preventDefault();
        const rect = canvas.getBoundingClientRect();
        const displayScale = canvas._displayScale || 1;
        const zoom = state.viewerSettings.zoom || 1;
        // Account for zoom scaling
        const mouseX = (e.clientX - rect.left) / zoom;
        const mouseY = (e.clientY - rect.top) / zoom;
        const imgX = Math.floor(mouseX / displayScale);
        const imgY = Math.floor(mouseY / displayScale);

        if (!state.ctShape) return;
        const spacing = volumeSpacing || [0.68, 0.68, 5.0];

        let volX, volY, volZ;
        if (axis === 'axial') {
            volX = imgX; volY = imgY; volZ = state.slices.axial;
        } else if (axis === 'sagittal') {
            const resampleRatio = _getMprGeometry('sagittal', state.ctShape, spacing).resampleRatio;
            volX = state.slices.sagittal; volY = imgX;
            volZ = Math.round(imgY / resampleRatio);
        } else {
            const resampleRatio = _getMprGeometry('coronal', state.ctShape, spacing).resampleRatio;
            volX = imgX; volY = state.slices.coronal;
            volZ = Math.round(imgY / resampleRatio);
        }

        if (volX < 0 || volX >= state.ctShape[2] || volY < 0 || volY >= state.ctShape[1] || volZ < 0 || volZ >= state.ctShape[0]) return;

        // Draw crosshairs
        drawLinkedCrosshairs(volX, volY, volZ, axis);
        fetchHUValue(volX, volY, volZ);

        // Navigate other viewers
        const updates = {};
        if (axis === 'axial') {
            updates.sagittal = volX;
            updates.coronal = volY;
        } else if (axis === 'sagittal') {
            updates.axial = volZ;
            updates.coronal = volY;
        } else {
            updates.axial = volZ;
            updates.sagittal = volX;
        }

        Object.entries(updates).forEach(([view, sliceIdx]) => {
            const slider = document.getElementById('slider' + capitalize(view));
            if (slider) {
                sliceIdx = Math.max(0, Math.min(parseInt(slider.max), Math.round(sliceIdx)));
                slider.value = sliceIdx;
                updateSlice(view, sliceIdx);
            }
        });
    });

    // Mark as having listeners set up
    canvas._listenersSetup = true;
}

/******** 3D RENDERING ********/
