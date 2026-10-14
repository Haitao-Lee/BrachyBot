/* Input actions own their initiating case, decoded image and request lifetime.
 * A late result can remain saved on the server without repainting another case. */
(function () {
    'use strict';
    const pending = new Map();
    const session = () => String(typeof _activeApiSessionId === 'function' ? _activeApiSessionId() || '' : '');
    const scope = () => window.BrachyBotTimepointWorkspace?.captureRequestScope?.() || null;
    const ownerKey = (sid, target, key) => JSON.stringify([sid, target?.timepointId, target?.generation, key]);
    const t = (zh, en) => typeof window._t === 'function' ? window._t(zh, en) : en;
    // Input controls are a projection of the accepted clinical config. File
    // defaults and saved browser drafts must not replace that owned source.
    let configPaintRevision = 0;
    const object = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
    const configFields = ['seed_info', 'radiation_array_params', 'reference_direc', 'ref_direc_auto',
        'reference_direc_mode', 'tumor_type', 'dose_value_unit', 'in_lowest_energy', 'out_highest_energy',
        'in_lowest_dose_gy', 'out_highest_dose_gy', 'DVH_rate', 'max_iter', 'rf_params',
        'distance_filter', 'direc_resolution', 'dl_params', 'iter_rate', 'replan_rate', 'mode'];
    const allowConfig = config => Object.fromEntries(configFields.filter(key =>
        Object.prototype.hasOwnProperty.call(object(config), key)).map(key => [key, config[key]]));
    function snapshotConfig(snapshot) {
        return {...allowConfig(snapshot.agent?.config),
            ...allowConfig(snapshot.agent?.planning_results?.timepoint_planning_config)};
    }
    function configControls(config, defaults = false) {
        const c = object(config), controls = {};
        const value = (id, val) => { if (val !== undefined && val !== null) controls[id] = {value: String(val)}; };
        const group = (name, fields) => {
            for (const [field, id] of Object.entries(fields)) value(id, object(c[name])[field]);
        };
        group('seed_info', {radius:'seedRadius', length:'seedLength', margin_rate:'seedMarginRate', seed_avr_dose:'seedAvgDose'});
        const array = (values, ids) => { if (Array.isArray(values)) ids.forEach((id, i) => value(id, values[i])); };
        array(c.seed_info?.num_of_seeds, ['seedCountMin', 'seedCountMax']);
        group('radiation_array_params', {target_value:'targetValue', obstacle_value:'obstacleValue',
            background_value:'backgroundValue', backlit_angle:'backlitAngle', maximum_candidate_trajectories:'maxCandiTraj'});
        array(c.radiation_array_params?.infer_img_size, ['inferSizeX', 'inferSizeY', 'inferSizeZ']);
        const p = defaults ? object(c.planning) : c;
        for (const [field, id] of Object.entries({DVH_rate:'dvhRate', max_iter:'maxIter', iter_rate:'iterRate', replan_rate:'replanRate'})) value(id, p[field]);
        for (const [physical, legacy, id] of [['in_lowest_dose_gy','in_lowest_energy','inLowestEnergy'],
            ['out_highest_dose_gy','out_highest_energy','outHighestEnergy']]) {
            if (p[physical] !== undefined && p[physical] !== null) value(id, p[physical]);
            else if (p[legacy] !== undefined && p[legacy] !== null) value(id,
                ['gy','physical_gy','dose_gy'].includes(String(p.dose_value_unit || '').toLowerCase()) ? p[legacy]
                : typeof planningDoseValueToGy === 'function'
                    ? planningDoseValueToGy(p[legacy], p.dose_value_unit, DEFAULT_PRESCRIPTION_GY) : p[legacy]);
        }
        array(p.direc_resolution, ['direcResCone', 'direcResStep', 'direcResRings']);
        group('distance_filter', {lower_bound:'distLowerBound', upper_bound:'distUpperBound', distance_rate:'distRate', interval_rate:'intervalRate'});
        group('dl_params', {lr:'dlLR', lr_decay:'dlLRDecay', epochs:'dlEpochs', patience:'dlPatience', search_region:'dlSearchRegion', DVH_margin:'dlDVHMargin'});
        group('rf_params', {max_episodes:'rfMaxEpisodes', bandwidth:'rfBandwidth'});
        if (defaults || c.mode !== undefined) controls.useRLToggle = {checked: c.mode === 'rl'};
        if (defaults || c.reference_direc !== undefined || c.reference_direc_mode !== undefined || c.ref_direc_auto !== undefined) {
            const auto = typeof c.ref_direc_auto === 'boolean' ? c.ref_direc_auto
                : c.reference_direc_mode ? c.reference_direc_mode === 'auto'
                    : ['auto', 'auto_detect'].includes(c.reference_direc);
            controls.refDirecAuto = {checked: auto};
            // An auto config has no saved manual vector. Clear the preceding
            // timepoint's vector without firing change handlers or writing it.
            array(Array.isArray(c.reference_direc) ? c.reference_direc : [0, 1, 0], ['refDirecX','refDirecY','refDirecZ']);
        }
        const model = c.tumor_type;
        if (model !== undefined) value('ctvModelSelect', ({biomedparse_lung_lesion:'vista3d_lung_tumor',
            biomedparse_head_neck_cancer:'nnunet_head_neck_gtv'})[model] || model);
        return controls;
    }
    function projectSnapshot(snapshot, config, defaults = {}) {
        const projected = JSON.parse(JSON.stringify(snapshot));
        const ui = object(projected.ui);
        const saved = object(ui.state || ui);
        projected.ui = {...ui, state: {...saved, dose_value_unit: 'gy', controls: {
            ...object(saved.controls), ...configControls(defaults, true), ...configControls(config),
        }}};
        return projected;
    }
    function paintControls(controls) {
        for (const [id, saved] of Object.entries(controls)) {
            const el = document.getElementById(id);
            if (!el) continue;
            if ('value' in saved) el.value = saved.value;
            if ('checked' in saved) el.checked = saved.checked;
        }
        configPaintRevision++;
        window._syncTumorTypeSelectorAppearance?.();
    }
    async function readConfig(target, isCurrent) {
        const abort = new AbortController();
        const timer = setTimeout(() => abort.abort(), 60000);
        const sid = target?.sessionId || session();
        const inputHeaders = sid ? {'X-BrachyBot-Session':sid} : {};
        try {
            if (!isCurrent()) return null;
            const response = await fetch(API + '/config', {signal:abort.signal,
                headers: window.BrachyBotTimepointWorkspace?.headers?.(target, inputHeaders) || inputHeaders});
            const data = await response.json();
            if (!isCurrent()) return null;
            if (!response.ok || data.success !== true) throw new Error(data.error || `HTTP ${response.status}`);
            for (const [header, expected] of [['X-BrachyBot-Session',sid], ['X-BrachyBot-Timepoint',target?.timepointId]]) {
                const actual = response.headers.get(header);
                if (expected && actual && actual !== expected) throw new Error('timepoint_workspace_scope_mismatch');
            }
            return data;
        } finally { clearTimeout(timer); }
    }
    window.BrachyBotInputPlanningConfig = Object.freeze({
        configControls, snapshotConfig, projectSnapshot,
        async prepareSnapshot(snapshot, target, isCurrent) {
            const data = await readConfig(target, isCurrent);
            if (!data) return null;
            return projectSnapshot(snapshot, {...allowConfig(data.config), ...snapshotConfig(snapshot)}, data.defaults);
        },
        mounted() { configPaintRevision++; },
        accepted(config, owner) {
            if (!owner.current() || !config || typeof config !== 'object') return false;
            paintControls(configControls(config));
            window.BrachyBotTimepointWorkspace?.acceptPlanningConfig?.(owner.timepointScope, allowConfig(config));
            return true;
        },
        async loadCurrent() {
            const sid = session(), revision = configPaintRevision;
            let target;
            try { target = scope(); } catch (_) { return false; }
            // The prepare/commit path owns a mount that is still switching.
            if (!target && window.BrachyBotTimepoints?.enabled?.()) return false;
            const isCurrent = () => sid === session() && revision === configPaintRevision
                && (target ? window.BrachyBotTimepointWorkspace.scopeIsCurrent(target)
                    : !window.BrachyBotTimepoints?.enabled?.());
            try {
                const data = await readConfig(target, isCurrent);
                if (!data || !isCurrent()) return false;
                window.__doseModelScaleGy = Number(data.dose_scale_gy || DEFAULT_DOSE_MODEL_SCALE_GY);
                paintControls({...configControls(data.defaults, true), ...configControls(allowConfig(data.config))});
                return true;
            } catch (error) {
                if (isCurrent()) console.warn('Failed to restore Input configuration:', error);
                return false;
            }
        },
    });
    window.beginInputAction = function (key, options = {}) {
        const sid = session();
        if (!sid) throw new Error(t('请等待病例工作区就绪。', 'Wait for the case workspace to be ready.'));
        const target = scope();
        const lock = ownerKey(sid, target, options.mutation ? 'mutation' : key);
        if (pending.has(lock) || (options.mutation && window.manualStepRequestPending?.())) {
            throw new Error(t('当前操作仍在执行，请等待完成。', 'An operation is still running; wait for it to finish.'));
        }
        const generation = window.__viewerRenderGeneration || 0;
        const path = String(document.getElementById('ctPath')?.value || '').trim();
        if (options.image && (!path || state.ctLoaded !== true || String(state.ctPath || '') !== path)) {
            throw new Error(t('请先加载所选影像并等待就绪。', 'Load the selected image and wait until it is ready.'));
        }
        const collection = window.BrachyBotTimepointWorkspace?.resourceState?.()?.images;
        const reference = collection?.images?.find(image=>image.id===collection.planning_reference_image_id);
        const token = {sessionId: sid, timepointScope: target, ctPath: reference?.path || path,
            referenceImageId: reference?.id || null, key,
            current: () => sid === session() && generation === (window.__viewerRenderGeneration || 0)
                && (!target || window.BrachyBotTimepointWorkspace.scopeIsCurrent(target)),
            headers: window.BrachyBotTimepointWorkspace?.headers?.(target,
                {'Content-Type': 'application/json', 'X-BrachyBot-Session': sid})
                || {'Content-Type': 'application/json', 'X-BrachyBot-Session': sid},
            finish: () => { if (pending.get(lock) === token) pending.delete(lock); window._refreshManualStepUI?.(); },
        };
        pending.set(lock, token);
        window._refreshManualStepUI?.();
        return token;
    };
    window.inputMutationPending = () => {
        try { return pending.has(ownerKey(session(), scope(), 'mutation')); }
        catch (_) { return true; }
    };
    window.fetchInputJson = async function (token, path, body) {
        if (!token.current()) return null;
        if (token.referenceImageId && ['ct_path','ct_image_path','image_path'].some(key=>key in (body || {})))
            body={...body,planning_reference_image_id:token.referenceImageId};
        const response = await fetch(API + path, {method: 'POST', headers: token.headers, body: JSON.stringify(body || {})});
        const data = await response.json().catch(() => null);
        if (!token.current()) return null;
        // A producer can save observations and pause before supplemental
        // planning. This is not a transport failure or a completed plan.
        if (response.status === 202 && data?.pending_review === true && data.requires_human_review === true)
            return data;
        if (!response.ok || !data || data.success === false || data.error) {
            throw new Error(data?.error || data?.message || `HTTP ${response.status}`);
        }
        if (response.status === 202) throw new Error(t('病例资源仍在加载，请稍后重试。', 'Case resources are still loading; retry when ready.'));
        return data;
    };
    window.presentInputDownloads = function (token, urls, label) {
        if (!token.current()) return;
        const safe = [...new Set((urls || []).filter(url => typeof url === 'string'
            && url.startsWith(`/api/sessions/${token.sessionId}/artifacts/`)))];
        if (!safe.length) throw new Error(t('文件已生成，但没有有效的病例下载地址。', 'Files were generated without a valid case-owned download URL.'));
        // Keep authenticated links available without triggering dozens of automatic downloads.
        addChat('bot-response', `${label}\n\n` + safe.map((url, i) => `- [${t('下载', 'Download')} ${i + 1}](${url})`).join('\n'));
    };
    document.addEventListener('DOMContentLoaded', () => {
        // A fixed trained model is not retrained by the Input panel. Likewise,
        // clinical label semantics cannot be changed by legacy numeric labels.
        const unsupported = ['seedCountMin', 'seedCountMax', 'seedAvgDose', 'targetValue', 'obstacleValue', 'backgroundValue',
            'direcResCone', 'direcResStep', 'direcResRings', 'dlLR', 'dlLRDecay', 'dlEpochs', 'dlPatience',
            'dlSearchRegion', 'dlDVHMargin', 'inferSizeX', 'inferSizeY', 'inferSizeZ'];
        unsupported.forEach(id => {
            const input = document.getElementById(id);
            if (!input) return;
            input.disabled = true;
            const zh = '只读：该字段不属于当前规划器可调整的参数。标签由结构集决定，模型设置已固定。';
            const en = 'Read-only: not adjustable by the current planner. Labels are Structure Set-owned; trained model settings are fixed.';
            input.setAttribute('data-i18n-title-zh', zh);
            input.setAttribute('data-i18n-title-en', en);
            input.title = t(zh, en);
        });
        for (const id of ['iterRate', 'intervalRate']) {
            const input = document.getElementById(id);
            if (input) { input.min = '1'; input.step = '1'; }
        }
    });
})();
