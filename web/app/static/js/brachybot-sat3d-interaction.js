/* Explicit point-guided research workflow, separate from automatic CTV models. */
(function () {
    let models = [];
    let pending = null;
    let running = false;
    let confirming = false;
    const text = (zh, en) => typeof window._t === 'function' ? window._t(zh, en) : en;
    const session = () => String(typeof _activeApiSessionId === 'function' ? _activeApiSessionId() || '' : window.activeSessionId || '');
    const scope = () => JSON.stringify([session(), state.ctPath || '', state.ctShape || [],
        document.getElementById('ctPath')?.value || '', document.getElementById('ctvImageModality')?.value || 'CT',
        document.getElementById('ctvVolumeIndex')?.value || '0']);
    const selected = () => models.find(item => item.tumor_type === document.getElementById('sat3dInteractiveSite')?.value);

    function status(zh, en) {
        const node = document.getElementById('sat3dInteractionStatus');
        if (!node) return;
        node.dataset.i18nZh = zh;
        node.dataset.i18nEn = en;
        node.textContent = text(zh, en);
    }

    window.syncSat3dInteraction = function () {
        const model = selected();
        const payload = sat3dPromptPayload();
        const button = document.getElementById('sat3dRun');
        const site = document.getElementById('sat3dInteractiveSite');
        if (site) site.disabled = running;
        ['toolSat3dPositive','toolSat3dNegative','toolSat3dClear'].forEach(id => {
            const control = document.getElementById(id);
            if (control) control.disabled = running;
        });
        if (button) {
            button.disabled = running || !state.ctLoaded || !model?.callable || !payload.positive_points.length;
            button.setAttribute('aria-busy', running ? 'true' : 'false');
        }
        if (confirming) status('请确认是否生成并替换候选轮廓。', 'Confirm whether to generate and replace the candidate contour.');
        else if (running) status('正在生成候选轮廓，可继续查看影像…', 'Generating a candidate contour; you can continue viewing the image…');
        else if (!state.ctLoaded) status('请先加载影像。', 'Load an image first.');
        else if (pending) status('正在检查 SAT3D 环境…', 'Checking the SAT3D runtime…');
        else if (!model?.callable) status('当前 SAT3D 环境不可用；现有轮廓不会改变。', 'SAT3D is unavailable; existing contours are unchanged.');
        else status(`正点 ${payload.positive_points.length} · 负点 ${payload.negative_points.length}。模态使用 Input 中的选择；结果需复核。`,
            `${payload.positive_points.length} positive · ${payload.negative_points.length} negative. Uses the Input modality; review the result.`);
    };

    async function loadModels() {
        if (pending) return pending;
        pending = (async () => {
            const response = await fetch(API + '/ctv/models?interaction=point', { credentials: 'same-origin' });
            const payload = await response.json();
            if (!response.ok || !payload.success) throw new Error('SAT3D capability check failed');
            models = payload.models || [];
            const select = document.getElementById('sat3dInteractiveSite');
            if (!select) return;
            const previous = select.value;
            select.replaceChildren();
            for (const model of models) {
                const option = document.createElement('option');
                option.value = model.tumor_type;
                const names = {
                    liver:['肝脏','Liver'], kidney:['肾脏','Kidney'], lung:['肺','Lung'], colon:['结肠','Colon'],
                    head_neck:['头颈','Head and neck'], prostate:['前列腺','Prostate'], unspecified:['其他部位（研究候选）','Other site (research candidate)'],
                };
                const pair = names[model.site] || [model.site, model.site];
                option.dataset.i18nZh = pair[0]; option.dataset.i18nEn = pair[1];
                option.textContent = text(...pair);
                option.disabled = !model.callable;
                select.appendChild(option);
            }
            const automatic = document.getElementById('ctvModelSelect')?.value || '';
            const site = automatic.includes('head_neck') || automatic.includes('nasopharynx') ? 'head_neck'
                : ['liver','kidney','lung','colon','prostate'].find(value => automatic.includes(value)) || 'unspecified';
            const suggested = models.find(item => item.site === site)?.tumor_type;
            select.value = models.some(item => item.tumor_type === previous) ? previous : suggested || models[0]?.tumor_type || '';
            select.onchange = window.syncSat3dInteraction;
        })().catch(() => { models = []; }).finally(() => { pending = null; window.syncSat3dInteraction(); });
        window.syncSat3dInteraction();
        return pending;
    }

    window.prepareSat3dInteraction = function () {
        const panel = document.getElementById('sat3dInteractionPanel');
        if (panel) { panel.hidden = false; panel.style.display = 'flex'; }
        if (!models.length) void loadModels();
        window.syncSat3dInteraction();
        return state.ctLoaded === true && !running;
    };

    window.closeSat3dInteraction = function () {
        const panel = document.getElementById('sat3dInteractionPanel');
        if (panel) { panel.hidden = true; panel.style.display = 'none'; }
        if (String(state.viewerSettings.activeTool || '').startsWith('sat3d_')) setViewerTool('crosshair');
    };

    window.runSat3dInteractive = async function () {
        if (running) return { success: false, code: 'sat3d_busy' };
        const owner = scope();
        if (!window.prepareSat3dInteraction()) return { success: false, code: 'image_not_ready' };
        await loadModels();
        const model = selected();
        if (scope() !== owner || !model?.callable || !sat3dPromptPayload().positive_points.length) return { success: false, code: 'sat3d_not_ready' };
        // The displayed prompts belong to the loaded volume, not an arbitrary
        // path typed later in Input. Do not run on an unseen replacement image.
        if (String(document.getElementById('ctPath')?.value || '') !== String(state.ctPath || '')) {
            status('Input 影像路径已改变，请先加载该影像，再重新选点。', 'The Input image path changed. Load that image and place new points first.');
            return { success: false, code: 'image_identity_changed' };
        }
        running = true;
        confirming = true;
        window.syncSat3dInteraction();
        try {
            const confirmed = await _confirmAction(
                'SAT3D 将根据提示点生成需人工复核的候选轮廓，并替换当前 CTV（如有）。其他部位或未验证模态属于研究性使用，不保证任意肿瘤的准确性。继续吗？',
                'SAT3D will create a review-required candidate from your points and replace the current CTV, if any. Unvalidated sites/modalities are research use; accuracy for every tumor is not guaranteed. Continue?',
                { titleZh:'生成候选轮廓', titleEn:'Generate a candidate contour', yesZh:'运行分割', yesEn:'Run segmentation' });
            if (!confirmed || owner !== scope()) return { success: false, code: 'cancelled_or_changed_case' };
            confirming = false;
            window.syncSat3dInteraction();
            const result = await runSegmentationStep('ctv_segmentation', {
                tumor_type: model.tumor_type, allow_out_of_distribution: true,
            });
            if (owner === scope() && result?.success) status('候选轮廓已生成，正在载入 CTV；请逐层复核边界。', 'Candidate generated; loading CTV. Review its boundary on every relevant slice.');
            return result;
        } finally {
            running = false;
            confirming = false;
            window.syncSat3dInteraction();
        }
    };
    window.addEventListener('i18nchange', window.syncSat3dInteraction);
})();
