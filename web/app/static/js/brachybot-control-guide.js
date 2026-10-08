/* Shared source-bound control usage: optional, non-blocking Monitor coaching.
 * Never dispatch controls, alter a mask, invent a completion, or append chat.
 */
(() => {
    let cards = null, pending = null, owner = null, timer = null, dismissed = null;
    const modeIds = {measure:'toolMeasure', angle:'toolAngle', rect:'toolRect',
        zoombox:'toolZoombox', annotate:'toolAnnotate', eraser:'toolEraser',
        crosshair:'toolCrosshair', sat3d_positive:'toolSat3dPositive', sat3d_negative:'toolSat3dNegative'};
    const monitor = () => typeof trainingMonitorState !== 'undefined' ? trainingMonitorState : {};
    const session = () => typeof _activeApiSessionId === 'function' ? _activeApiSessionId() : null;
    const mode = () => typeof state !== 'undefined' ? state.viewerSettings?.activeTool : null;
    const language = () => String(window._i18nLang || document.documentElement.lang || 'en').startsWith('zh') ? 'zh' : 'en';
    const t = (zh, en) => language() === 'zh' ? zh : en;
    function hide() {
        document.getElementById('controlUsageGuide')?.remove();
        if (timer) clearInterval(timer);
        timer = null; owner = null;
    }
    function same(a, b) { return a && b && a.session === b.session && a.run === b.run && a.mode === b.mode; }
    function text(el, value) {
        // A stable hint must not re-announce identical text to screen readers
        // on every ownership check, or disturb selection/focus.
        if (el.textContent !== value) el.textContent = value;
    }
    function current() {
        const m = monitor();
        return m.active && m.runId && session() && modeIds[mode()]
            ? {session:session(), run:m.runId, mode:mode()} : null;
    }
    async function load() {
        if (cards) return cards;
        if (pending) return pending;
        const abort = new AbortController();
        const timeout = setTimeout(() => abort.abort(), 4000);
        pending = (async () => {
            try {
                const response = await fetch((typeof API === 'undefined' ? '/api' : API) + '/ui/manual', {signal:abort.signal});
                if (!response.ok) return null;
                const payload = await response.json();
                if (!payload.success || !Array.isArray(payload.cards)) return null;
                cards = payload.cards; return cards;
            } catch (_) { return null; }
            finally { clearTimeout(timeout); pending = null; }
        })();
        return pending;
    }
    function render(card) {
        if (!same(owner, current())) { hide(); return; }
        const host = document.getElementById('panelViewers');
        if (!host) return;
        let box = document.getElementById('controlUsageGuide');
        if (!box) {
            box = document.createElement('aside'); box.id = 'controlUsageGuide';
            box.className = 'control-usage-guide'; box.setAttribute('aria-live', 'polite');
            const body = document.createElement('div'); body.className = 'control-usage-body';
            for (const role of ['heading', 'steps', 'progress', 'limits']) {
                const el = document.createElement(role === 'heading' ? 'strong' : 'p');
                el.dataset.usagePart = role; body.appendChild(el);
            }
            const close = document.createElement('button'); close.type = 'button';
            close.className = 'control-usage-dismiss'; close.textContent = '×';
            close.addEventListener('click', () => { dismissed = owner; hide(); });
            box.append(body, close);
            // After the toolbar, before the viewport; never obscure anatomy.
            const grid = host.querySelector('.viewer-workspace');
            if (grid) grid.before(box); else host.prepend(box);
        }
        const lang = language();
        text(box.querySelector('[data-usage-part="heading"]'), t('操作提示 · ', 'Usage hint · ') + card.names[lang]);
        text(box.querySelector('[data-usage-part="steps"]'), card.steps[lang]);
        text(box.querySelector('[data-usage-part="limits"]'), card.caution[lang]);
        const dismiss = box.querySelector('button'), dismissLabel = t('关闭这条提示', 'Dismiss this hint');
        if (dismiss.getAttribute('aria-label') !== dismissLabel) dismiss.setAttribute('aria-label', dismissLabel);
        const progress = box.querySelector('[data-usage-part="progress"]');
        const ready = typeof state !== 'undefined' && state.ctLoaded;
        const tool = window._annotationToolState || {};
        const sameSlice = ready && tool.axis && tool.sliceIndex === state.slices?.[tool.axis];
        const points = sameSlice ? tool.points?.length || 0 : 0;
        const angle = sameSlice && !points ? (state.annotations || []).findLast(ann =>
            ann.type === 'angle' && ann.axis === tool.axis && ann.sliceIndex === tool.sliceIndex
            && Number.isFinite(ann.angleDeg)) : null;
        text(progress, !ready ? t('请先加载 CT；提示不代表工具已经完成操作。', 'Load CT first; this hint is not an operation receipt.')
            : owner.mode === 'angle' && angle ? t(`当前切片最近记录的角度：${angle.angleDeg.toFixed(1)}°；继续点选可开始下一次测量。`, `Latest recorded angle on this slice: ${angle.angleDeg.toFixed(1)}°; click to begin another measurement.`)
            : owner.mode === 'angle' ? t(`当前待完成角度：${Math.min(points, 2)}/3 个点；第二点是顶点。`, `Pending angle: ${Math.min(points, 2)}/3 points; the second is the vertex.`)
            : card.result[lang]);
    }
    async function show() {
        const requested = current();
        if (!requested) { hide(); return; }
        if (same(requested, dismissed)) return;
        const docs = await load();
        if (!same(requested, current())) return;
        const card = docs?.find(c => c.control_ids?.includes(modeIds[requested.mode]));
        if (!card) { hide(); return; } // Unknown docs are not guessed.
        hide(); owner = requested; render(card);
        // Only while a hint is visible. Guard case/run/tool changes, including
        // stop, logout and async hydration; no network polling or model call.
        timer = setInterval(() => {
            if (!same(owner, current()) || document.hidden) { hide(); return; }
            render(card);
        }, 350);
    }
    document.addEventListener('pointerover', event => {
        if (monitor().active && Object.values(modeIds).includes(event.target.closest?.('button')?.id)) void load();
    });
    window.addEventListener('i18nchange', () => { if (owner) void show(); });
    document.addEventListener('visibilitychange', () => { if (document.hidden) hide(); });
    window.addEventListener('pagehide', hide);
    // Called from the authoritative mode setter and Monitor phase setter,
    // including natural-language controller execution, not just mouse clicks.
    window.refreshControlUsageGuide = () => {
        if (!same(dismissed, current())) dismissed = null;
        void show().catch(() => hide());
    };
})();
