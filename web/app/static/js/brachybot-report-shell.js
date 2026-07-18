// =============================================================================
// window.Report — additive upgrade layer (P4-P19)
// =============================================================================
// This block is inserted BEFORE the legacy Report module (which begins at
// the next `// ----- 1. Static reference catalog -----` marker).  It:
//   1. Declares the window.Report namespace with all P4-P19 features.
//   2. Uses getters to transparently forward to the legacy state
//      (window.reportForm) and functions (renderReportEditor, etc.).
//   3. Adds sources/audit/snapshots/sign/persist/export/validation/shortcuts.
//   4. Boots after the legacy module has initialized.
// =============================================================================

window.Report = (function () {
    'use strict';

    // ---------- Forward declarations of legacy bits ----------
    // These names are defined later in the legacy block.  We reference them
    // via window.* at call time so the order doesn't matter.
    function _legacy(name) { return window[name]; }

    // ---------- State (forward to window.reportForm) ----------
    const stateProxy = {
        get language() { return (window.reportForm && window.reportForm.language) || 'en'; },
        set language(v) { if (window.reportForm) window.reportForm.language = v; },
        get editedFields() { return (window.reportForm && window.reportForm.editedFields) || new Set(); },
        set editedFields(v) { if (window.reportForm) window.reportForm.editedFields = v; },
    };
    // The state object — direct reference, but reads/writes flow to window.reportForm
    const state = new Proxy({}, {
        get(_, k) { return window.reportForm ? window.reportForm[k] : undefined; },
        set(_, k, v) { if (window.reportForm) window.reportForm[k] = v; return true; },
        has(_, k) { return window.reportForm ? (k in window.reportForm) : false; },
    });

    // ---------- Helpers ----------
    function _getByPath(obj, dottedKey) {
        const parts = dottedKey.split('.');
        let cur = obj;
        for (const p of parts) {
            if (cur == null) return undefined;
            cur = cur[p];
        }
        return cur;
    }
    function _setByPath(obj, dottedKey, val) {
        const parts = dottedKey.split('.');
        let cur = obj;
        for (let i = 0; i < parts.length - 1; i++) {
            if (cur[parts[i]] === undefined || cur[parts[i]] === null || typeof cur[parts[i]] !== 'object') {
                cur[parts[i]] = {};
            }
            cur = cur[parts[i]];
        }
        cur[parts[parts.length - 1]] = val;
    }
    function _detectLanguageFromText(text) {
        if (!text) return null;
        if (/[一-鿿]/.test(text)) return 'zh';
        return 'en';
    }
    function _escHtml(s) {
        if (s === null || s === undefined) return '';
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    // ---------- i18n (P4 + P6) ----------
    const i18n = {
        detect() {
            // BUG FIX 2026-06-17: respect the global UI language toggle
            // (window._i18nLang, set by getInitialLang() from
            // 'brachybot_ui_lang' in localStorage). Previously this
            // method only checked 'brachyplan_report_lang' (a separate
            // Report-specific key), so the Report panel could show
            // Chinese when the global toggle was English.
            if (typeof window._i18nLang === 'string'
                && (window._i18nLang === 'zh' || window._i18nLang === 'en')) {
                return window._i18nLang;
            }
            try {
                const stored = localStorage.getItem('brachyplan_report_lang');
                if (stored && (stored === 'zh' || stored === 'en')) return stored;
            } catch (e) {}
            const nav = ((typeof navigator !== 'undefined' && navigator.language) || 'zh').toLowerCase();
            if (nav.startsWith('en')) return 'en';
            return 'zh';
        },
        set(lang, opts = {}) {
            if (lang !== 'zh' && lang !== 'en') return;
            const prevLang = window.reportForm ? window.reportForm.language : null;
            if (window.reportForm) window.reportForm.language = lang;
            if (!opts.silent) {
                try { localStorage.setItem('brachyplan_report_lang', lang); } catch (e) {}
            }
            // ---- Refresh localized defaults that the user has not edited ----
            // The form's default values (gender / department / technique)
            // are language-localized. When the user switches language we
            // want any untouched default to also switch, otherwise an
            // English PDF would still show 男 / 放射治疗科 / 永久粒子植入.
            // We do NOT overwrite fields the user has actually edited.
            if (window.reportForm && prevLang && prevLang !== lang
                && typeof _localizedEmptyReportForm === 'function') {
                const tpl = _localizedEmptyReportForm(lang);
                const f = window.reportForm;
                const edited = f.editedFields || new Set();
                // gender
                if (!edited.has('patient.gender')) f.patient.gender = tpl.patient.gender;
                // department
                if (!edited.has('patient.department')) f.patient.department = tpl.patient.department;
                // technique (planning.technique is the famous 永久粒子植入 leak)
                if (!edited.has('planning.technique')) f.planning.technique = tpl.planning.technique;
            }
            if (opts.userInitiated && window.reportForm && window.reportForm.editedFields) {
                window.reportForm.editedFields.add('language');
            }
            if (window.reportForm && !window.reportForm.editedFields.has('interpretation')) {
                autoFill.interpret();
            }
            _updateLanguageButtons();
            panels.editor(); panels.preview();
            persist.autoSave();
            audit.log('i18n.set', 'language', null, lang);
        },
        _tr(key) {
            const lang = stateProxy.language;
            const dict = (typeof REPORT_STRINGS !== 'undefined') ? REPORT_STRINGS[lang] : null;
            return (dict && dict[key]) || key;
        },
    };

    function _updateLanguageButtons() {
        // 2026-06-16: scope to `.rp-lang-toggle` only. The header
        // language toggle uses `.lang-btn` too but is managed by
        // its own `setUiLanguage()` — touching it here would
        // override the active state with a flat white background.
        const lang = stateProxy.language;
        document.querySelectorAll('.rp-lang-toggle .lang-btn').forEach(btn => {
            const isActive = btn.dataset.lang === lang;
            btn.style.background = isActive ? '#0ea5e9' : '#fff';
            btn.style.color = isActive ? '#fff' : '#334155';
        });
    }

    // ---------- Sources (badges) — P5 ----------
    const sources = {
        _map: new Map(),
        get(key) { return this._map.get(key) || 'auto'; },
        set(key, src) {
            this._map.set(key, src);
            try {
                const safe = (key || '').replace(/[^a-zA-Z0-9_]/g, '_');
                document.querySelectorAll(`[data-source-key="${safe}"]`).forEach(badge => {
                    const colors = { auto: '#10b981', user: '#f59e0b', bot: '#3b82f6' };
                    const labels = { auto: 'AUTO', user: 'YOU', bot: 'BOT' };
                    badge.style.background = colors[src] || colors.auto;
                    badge.textContent = labels[src] || src;
                    badge.title = (src === 'user' ? 'Edited by you' : src === 'bot' ? 'Filled by brachybot' : 'Auto-extracted');
                });
            } catch (e) {}
        },
        bulkSet(patch, defaultSrc = 'auto') {
            Object.entries(patch || {}).forEach(([k, v]) => {
                if (v !== null && v !== undefined && v !== '') this._map.set(k, defaultSrc);
            });
        },
        badgeHtml(key) {
            const src = this.get(key);
            const colors = { auto: '#10b981', user: '#f59e0b', bot: '#3b82f6' };
            const labels = { auto: 'AUTO', user: 'YOU', bot: 'BOT' };
            const safeKey = String(key || '').replace(/[^a-zA-Z0-9_]/g, '_');
            const callArg = JSON.stringify(String(key || ''))
                .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
            return `<span data-source-key="${safeKey}" style="background:${colors[src]};color:#fff;font-size:0.58rem;padding:1px 6px;border-radius:8px;margin-left:4px;letter-spacing:0.04em;vertical-align:middle;cursor:help;" title="Click reset to restore auto">${labels[src] || src}</span><span onclick="Report.sources.resetTo(${callArg})" title="Reset to auto" style="cursor:pointer;margin-left:3px;font-size:0.7rem;color:#94a3b8;">reset</span>`;
        },
        resetTo(key) {
            if (!key) return;
            this._map.set(key, 'auto');
            if (window.reportForm && window.reportForm.editedFields) {
                window.reportForm.editedFields.delete(key);
            }
            autoFill.fromAll({ onlyKey: key });
        },
    };

    // ---------- Panels ----------
    const panels = {
        editor() { const fn = _legacy('renderReportEditor'); if (fn) fn(); },
        preview() { const fn = _legacy('_updateReportPreview'); if (fn) fn(); },
        switch(mode) { /* In the new top/bottom layout both panes are always visible. */ },
        layout2col(on) {
            try { document.body.classList.toggle('report-2col', !!on); } catch (e) {}
            try { localStorage.setItem('brachyplan_report_2col', on ? '1' : '0'); } catch (e) {}
            // BUG FIX 2026-06-16: sync the actual checkbox UI when
            // layout2col is called from anywhere (auto-restore, the
            // toolbar toggle, etc.) so the visible state matches the
            // body class.
            try {
                const cb = document.querySelector('.rp-2col-toggle input[type="checkbox"]');
                if (cb && cb.checked !== !!on) cb.checked = !!on;
            } catch (_) {}
        },
    };

    // ---------- Preview zoom (P+user) ----------
    // Keep the report pages at their real A4 dimensions for export. The visual
    // preview applies a separate fit-to-panel scale so narrow and split layouts
    // never crop the document at the default zoom.
    const preview = (function() {
        let _zoom = 1.0;
        let _fitScale = 1.0;
        let _resizeObserver = null;
        let _updateFrame = 0;
        const MIN = 0.5, MAX = 2.0, STEP = 0.1;

        function _measureFitScale() {
            const host = document.getElementById('reportPreview');
            const page = document.querySelector('#reportPages .report-page');
            if (!host || !page) return 1.0;
            const style = window.getComputedStyle(host);
            const horizontalPadding = (parseFloat(style.paddingLeft) || 0)
                + (parseFloat(style.paddingRight) || 0);
            const availableWidth = Math.max(0, host.clientWidth - horizontalPadding - 2);
            const pageWidth = page.offsetWidth;
            if (availableWidth <= 0 || pageWidth <= 0) return 1.0;
            return Math.min(1.0, availableWidth / pageWidth);
        }

        function _update() {
            const wrap = document.getElementById('reportPagesWrapper');
            const pages = document.getElementById('reportPages');
            const ind = document.getElementById('rpZoomIndicator');
            _fitScale = _measureFitScale();
            const effectiveZoom = Math.max(0.2, Math.min(MAX, _zoom * _fitScale));
            if (wrap) {
                wrap.style.transform = `scale(${effectiveZoom})`;
                // Transforms do not affect normal-flow height. Reserve the
                // scaled height explicitly to avoid a large blank area below
                // the preview or overlap with the status bar.
                wrap.style.height = pages
                    ? `${Math.ceil(pages.scrollHeight * effectiveZoom)}px`
                    : '';
                wrap.dataset.fitScale = String(_fitScale);
                wrap.dataset.effectiveZoom = String(effectiveZoom);
            }
            if (ind) {
                const percent = Math.round(effectiveZoom * 100);
                ind.textContent = percent + '%';
                ind.title = _fitScale < 0.999
                    ? `Preview ${percent}% (fit-to-panel ${Math.round(_fitScale * 100)}%). Click to reset (Ctrl+0).`
                    : `Preview ${percent}%. Click to reset (Ctrl+0).`;
            }
        }

        function refresh() {
            if (_updateFrame) window.cancelAnimationFrame(_updateFrame);
            _updateFrame = window.requestAnimationFrame(() => {
                _updateFrame = 0;
                _update();
            });
        }
        function _persist() {
            try { localStorage.setItem('brachyplan_report_zoom', String(_zoom)); } catch (e) {}
        }
        function _restore() {
            try {
                const v = parseFloat(localStorage.getItem('brachyplan_report_zoom'));
                if (!isNaN(v) && v >= MIN && v <= MAX) _zoom = v;
            } catch (e) {}
        }
        function setZoom(z) {
            _zoom = Math.max(MIN, Math.min(MAX, z));
            refresh(); _persist();
        }
        function zoomIn() { setZoom(_zoom + STEP); }
        function zoomOut() { setZoom(_zoom - STEP); }
        function zoomReset() { setZoom(1.0); }
        function getZoom() { return _zoom; }

        // Install interaction and resize listeners on the preview area.
        function _installWheelHandler() {
            const host = document.getElementById('reportPreview');
            if (!host) return;
            if (!host._rpZoomWired) host.addEventListener('wheel', (e) => {
                if (!e.ctrlKey && !e.metaKey) return;
                e.preventDefault();
                if (e.deltaY < 0) zoomIn();
                else if (e.deltaY > 0) zoomOut();
            }, { passive: false });
            host._rpZoomWired = true;

            if (!host._rpImageLoadWired) {
                host.addEventListener('load', refresh, true);
                host._rpImageLoadWired = true;
            }
            if (typeof ResizeObserver !== 'undefined') {
                if (_resizeObserver) _resizeObserver.disconnect();
                _resizeObserver = new ResizeObserver(refresh);
                _resizeObserver.observe(host);
            }
            refresh();
        }
        _restore();
        refresh();
        // Re-install when preview element is re-created (preview re-renders)
        const _origPreview = panels.preview;
        panels.preview = function() {
            _origPreview();
            // Restore transform after re-render
            setTimeout(_installWheelHandler, 0);
        };
        // Also install once on boot via DOMContentLoaded
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', _installWheelHandler);
        } else {
            _installWheelHandler();
        }
        return { setZoom, zoomIn, zoomOut, zoomReset, getZoom, refresh };
    })();

    // Ctrl+0 reset shortcut
    document.addEventListener('keydown', (e) => {
        if (e.ctrlKey && (e.key === '0' || e.key === ')')) {
            const ed = document.activeElement;
            if (ed && (ed.tagName === 'INPUT' || ed.tagName === 'TEXTAREA' || ed.isContentEditable)) return;
            e.preventDefault();
            preview.zoomReset();
        }
    });

    // ---------- Status ----------
    function _setReportStatus(text, kind = 'info') {
        const el = document.getElementById('reportStatusText');
        if (!el) return;
        el.textContent = text;
        el.classList.remove('ok', 'warn', 'error');
        if (kind === 'ok' || kind === 'warn' || kind === 'error') el.classList.add(kind);
        setTimeout(() => { if (el.textContent === text) { el.textContent = 'Ready'; el.classList.remove('ok','warn','error'); } }, 3000);
    }

    // ---------- Auto-fill (P7) ----------
    async function _fetchHeader() {
        try {
            const ws = window.state || {};
            if (!ws.ctPath) return {};
            const r = await fetch('/api/header/info', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ct_path: ws.ctPath }),
            });
            const j = await r.json();
            return (j && j.success && j.tags) || {};
        } catch (e) { return {}; }
    }

    async function _fetchServerReportPatch(scope, language) {
        const response = await fetch('/api/report/auto-fill', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                scope: scope || 'all',
                language: language || 'en',
                sources: ['nifti', 'dicom', 'planning'],
            }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload.success) {
            throw new Error(payload.error || `HTTP ${response.status}`);
        }
        return payload;
    }

    function _applyReportPatch(patch, source = 'bot', options = {}) {
        const f = window.reportForm;
        if (!f) return { applied: 0, skipped: 0 };
        const onlyKey = options.onlyKey || null;
        let applied = 0, skipped = 0;
        for (const [key, value] of Object.entries(patch || {})) {
            if (onlyKey && key !== onlyKey) continue;
            if (f.editedFields && f.editedFields.has(key)) {
                skipped++;
                continue;
            }
            _setByPath(f, key, value);
            sources.set(key, source);
            if (key === 'planning.prescriptionRationale' && value && Array.isArray(value.sources)) {
                if (!Array.isArray(f.references)) f.references = [];
                value.sources.forEach((sourceItem, index) => {
                    const url = typeof sourceItem === 'string' ? sourceItem : sourceItem?.url;
                    const title = typeof sourceItem === 'string' ? '' : sourceItem?.title;
                    if (typeof url !== 'string' || !/^https?:\/\//i.test(url)) return;
                    if (f.references.some(ref => ref && ref.url === url)) return;
                    f.references.push({
                        citeKey: `clinical-kb-${value.site || 'case'}-${index + 1}`,
                        title: title || `Clinical criterion source (${value.site || 'case'})`,
                        publisher: 'Verified clinical source',
                        year: '',
                        url,
                        custom: false,
                    });
                });
            }
            applied++;
        }
        if (options.render !== false) {
            panels.editor();
            panels.preview();
            persist.autoSave();
        }
        return { applied, skipped };
    }

    const autoFill = {
        async fromAll(opts = {}) {
            const onlyKey = opts.onlyKey || null;
            const f = window.reportForm;
            if (!f) { _setReportStatus('No report form', 'error'); return; }
            // 1. DICOM
            try {
                const tags = await _fetchHeader();
                this.fromDicom(tags, onlyKey);
            } catch (e) { console.warn('DICOM auto-fill failed:', e); }
            // 2. NIfTI
            this.fromNifti(onlyKey);
            // 3. Planning
            this.fromPlanning(onlyKey);
            // 4. Interpretation (if not user-edited)
            if ((!onlyKey || onlyKey === 'interpretation') && (!f.editedFields || !f.editedFields.has('interpretation'))) {
                this.interpret();
            }
            // The server contributes source-backed prescription rationale,
            // target/OAR criteria, and geometry-derived tumor assessment. The
            // local path remains an offline fallback when the server is down.
            let serverApplied = 0;
            try {
                const language = (typeof window._i18nLang === 'string') ? window._i18nLang : (f.language || 'en');
                const payload = await _fetchServerReportPatch('all', language);
                serverApplied = _applyReportPatch(payload.patch || {}, 'bot', {
                    onlyKey,
                    render: false,
                }).applied;
            } catch (e) {
                console.warn('Server report auto-fill unavailable; using local data:', e);
            }
            // BUG FIX 2026-06-17 (auto-screenshots in report):
            // auto-capture visual evidence (CT + masks, dose heatmap,
            // 3D plan, DVH curve) as report figures. The previous
            // version only triggered on panel-open, but users who
            // hit "Auto-fill" expected everything to land together.
            try {
                if (typeof autoCaptureReportFigures === 'function') {
                    setTimeout(() => autoCaptureReportFigures(), 0);
                }
            } catch (_) {}
            panels.editor(); panels.preview();
            persist.autoSave();
            audit.log('autoFill.fromAll', '*', null, 'filled');
            _setReportStatus(serverApplied > 0
                ? `Auto-filled with ${serverApplied} source-backed server field(s)`
                : 'Auto-filled from local NIfTI + planning data', 'ok');
        },
        fromDicom(tags, onlyKey = null) {
            if (!tags || Object.keys(tags).length === 0) return;
            const f = window.reportForm;
            if (!f) return;
            const lang = (window._i18nLang) || f.language || 'en';
            const map = [];
            if (tags.patient_name)        map.push(['patient.name', tags.patient_name]);
            if (tags.patient_id)          map.push(['patient.id', tags.patient_id]);
            if (lang === 'zh' && tags.patient_sex_label_zh) map.push(['patient.gender', tags.patient_sex_label_zh]);
            if (lang === 'en' && tags.patient_sex_label_en) map.push(['patient.gender', tags.patient_sex_label_en]);
            if (tags.patient_birth_date)  map.push(['patient.birthDate', tags.patient_birth_date]);
            if (tags.study_date)          map.push(['study.scanDate', tags.study_date]);
            if (tags.accession_number)    map.push(['study.accession', tags.accession_number]);
            if (tags.modality)            map.push(['study.modality', tags.modality]);
            if (tags.institution_name)    map.push(['hospital.name', tags.institution_name]);
            if (tags.performing_physician) map.push(['study.radiologist', tags.performing_physician]);
            if (tags.referring_physician)  map.push(['study.referring', tags.referring_physician]);
            if (tags.manufacturer)        map.push(['imaging.scanner', tags.manufacturer]);
            if (tags.study_description)   map.push(['study.description', tags.study_description]);
            if (tags.series_description)  map.push(['study.series', tags.series_description]);
            for (const [k, v] of map) {
                if (onlyKey && k !== onlyKey) continue;
                if (f.editedFields && f.editedFields.has(k)) continue;
                _setByPath(f, k, v);
                sources.set(k, 'auto');
            }
        },
        fromNifti(onlyKey = null) {
            try {
                const f = window.reportForm;
                const ws = window.state || {};
                if (!f) return;
                if (ws.ctPath) {
                    if (!onlyKey || onlyKey === 'case.patientId') {
                        if (!f.editedFields || !f.editedFields.has('case.patientId')) {
                            f.case.patientId = ws.ctPath.split(/[\/\\]/).pop().replace(/\.nii(\.gz)?$/i, '');
                            sources.set('case.patientId', 'auto');
                        }
                    }
                }
                if (ws.ctShape && ws.ctSpacing) {
                    const writes = [
                        // Volume arrays are stored as Z, Y, X throughout the viewer.
                        ['imaging.sliceCount', ws.ctShape[0] || null],
                        ['imaging.pixelSpacingMm', ws.ctSpacing[0] || null],
                        ['imaging.sliceThicknessMm', ws.ctSpacing[2] || null],
                    ];
                    for (const [k, v] of writes) {
                        if (onlyKey && k !== onlyKey) continue;
                        if (f.editedFields && f.editedFields.has(k)) continue;
                        if (v !== null) { _setByPath(f, k, v); sources.set(k, 'auto'); }
                    }
                }
            } catch (e) { console.warn('NIfTI auto-fill failed:', e); }
        },
        fromPlanning(onlyKey = null) {
            try {
                const f = window.reportForm;
                const ws = window.state || {};
                if (!f) return;
                const m = ws.metrics || {};
                const dataTree = (typeof dataTreeState !== 'undefined') ? dataTreeState : (window.dataTreeState || null);
                const writes = [];
                if (m.total_seeds !== undefined) writes.push(['planning.totalSeeds', m.total_seeds]);
                if (m.num_trajectories !== undefined) writes.push(['planning.trajectoryCount', m.num_trajectories]);
                // Activity is intentionally not inferred from seed count.
                // Source strength varies by radionuclide and vendor; only an
                // explicit backend/plan_config value may populate it.
                if (Number.isFinite(Number(m.ctv_volume_mm3))) {
                    writes.push(['case.ctvVolumeMm3', Number(m.ctv_volume_mm3)]);
                }
                if (m.ctv_voxels !== undefined) {
                    writes.push(['segmentation.ctvVoxels', m.ctv_voxels]);
                }
                if (m.v100 !== undefined) writes.push(['metrics.v100', m.v100 * 100]);
                if (m.d90 !== undefined)  writes.push(['metrics.d90', m.d90]);
                if (m.d95 !== undefined)  writes.push(['metrics.d95', m.d95]);
                if (m.v150 !== undefined) writes.push(['metrics.v150', m.v150 * 100]);
                if (m.v200 !== undefined) writes.push(['metrics.v200', m.v200 * 100]);
                if (m.ci !== undefined)   writes.push(['metrics.ci', m.ci]);
                if (m.hi !== undefined)   writes.push(['metrics.hi', m.hi]);
                if (m.gi !== undefined)   writes.push(['metrics.gi', m.gi]);
                if (m.plan_score !== undefined) writes.push(['metrics.score', m.plan_score]);
                for (const [k, v] of writes) {
                    if (onlyKey && k !== onlyKey) continue;
                    if (f.editedFields && f.editedFields.has(k)) continue;
                    _setByPath(f, k, v);
                    sources.set(k, 'auto');
                }
                if ((!onlyKey || onlyKey === 'oarDose') && m.oar_metrics) {
                    if (!f.editedFields || !f.editedFields.has('oarDose')) {
                        // BUG FIX 2026-06-17: previously capped at 12
                        // OARs, hiding many clinically relevant organs
                        // (stomach, kidney, liver, lung, vessels). Now
                        // we include ALL OARs that received any dose
                        // (D2cc, D1cc, D0.1cc, OR Dmax > 5 Gy), sorted
                        // by D2cc descending so the highest-dose
                        // organs appear first. User can still mark
                        // rows hidden via editedFields.
                        f.oarDose = Object.entries(m.oar_metrics)
                            .filter(([n, x]) => x && (
                                x.d2cc || x.d1cc || x.d0_1cc ||
                                (x.dmax && x.dmax > 5)
                            ))
                            .map(([n, x]) => ({
                                organ: _resolveOARDisplayName(n, x),
                                label_id: x.label_id ?? x.labelId ?? null,
                                d2cc: x.d2cc || null,
                                d1cc: x.d1cc || null,
                                d0_1cc: x.d0_1cc || null,
                                dmax: x.dmax || x.max_dose || null,
                                v100: x.v100 ? x.v100 * 100 : null,
                            }))
                            .sort((a, b) => (b.d2cc || 0) - (a.d2cc || 0));
                        sources.set('oarDose', 'auto');
                    }
                }
                if ((!onlyKey || onlyKey === 'case.oarCount') && dataTree && dataTree.organs) {
                    if (!f.editedFields || !f.editedFields.has('case.oarCount')) {
                        f.case.oarCount = dataTree.organs.length || null;
                        sources.set('case.oarCount', 'auto');
                    }
                }
            } catch (e) { console.warn('Planning auto-fill failed:', e); }
        },
        interpret() {
            const fn = _legacy('_autoFillInterpretation');
            if (fn) fn();
        },
    };

    // ---------- Brachybot (P10) ----------
    const brachybot = {
        async onChatCommand(msg) {
            if (!msg) return false;
            const m = String(msg).trim();
            // /report en | /report zh
            let mm = m.match(/^\/report\s+(zh|zh-CN|chinese|中文|en|english)\b/i);
            if (mm) {
                const lang = /^zh|chinese|中文/i.test(mm[1]) ? 'zh' : 'en';
                i18n.set(lang, { userInitiated: true });
                _setReportStatus('Language set to ' + (lang === 'zh' ? '中文' : 'English'), 'ok');
                return true;
            }
            // /report fill [scope]
            mm = m.match(/^\/report\s+fill(?:\s+([a-zA-Z_-]+))?\s*$/i);
            if (mm) {
                const scope = (mm[1] || 'all').toLowerCase();
                const valid = ['all', 'patient', 'metrics', 'oar', 'interpretation', 'safety'];
                const finalScope = valid.includes(scope) ? scope : 'all';
                // Use GLOBAL UI language, not stateProxy.language which
                // may be stale from localStorage.
                const _fillLang = (typeof window._i18nLang === 'string') ? window._i18nLang : 'en';
                await this.fillFromServer({ scope: finalScope, language: _fillLang });
                return true;
            }
            // /report export
            if (/^\/report\s+export(\s+(pdf|html|md|markdown|json))?\s*$/i.test(m)) {
                const kind = (m.match(/export\s+(\w+)/i) || [])[1] || 'pdf';
                _exportCmd(kind);
                return true;
            }
            // /report snapshot
            if (/^\/report\s+snapshot/i.test(m)) {
                snapshots.save('');
                _setReportStatus('Snapshot saved', 'ok');
                return true;
            }
            // /report reset
            if (/^\/report\s+reset/i.test(m)) {
                persist.clear();
                return true;
            }
            // Natural language: 用中文生成报告 / 用英文生成报告 / 英文报告 / 中文报告
            const nat = m.match(/(用|use\s+in|switch\s+to)?\s*(中文|zh|chinese|英文|english|en)(的|生成|的)?\s*(报告|report)/i);
            if (nat) {
                const lang = /中文|zh|chinese/i.test(nat[2]) ? 'zh' : 'en';
                i18n.set(lang, { userInitiated: true });
                _setReportStatus('Language set to ' + (lang === 'zh' ? '中文' : 'English'), 'ok');
                return true;
            }
            return false;
        },
        async fillFromServer({ scope = 'all', language = 'en' } = {}) {
            _setReportStatus('Filling from server…', 'info');
            try {
                const payload = await _fetchServerReportPatch(scope, language);
                const result = this.applyPatch(payload.patch || {}, 'bot');
                _setReportStatus(`Bot updated ${result.applied} field(s)`, 'ok');
                return { success: true, ...result, provenance: payload.provenance || {} };
            } catch (e) {
                _setReportStatus('Bot fill failed: ' + e.message, 'error');
                return { success: false, error: e.message || String(e), applied: 0, skipped: 0 };
            }
        },
        applyPatch(patch, source = 'bot') {
            const result = _applyReportPatch(patch, source);
            const { applied, skipped } = result;
            audit.log('brachybot.applyPatch', '*', null, `applied=${applied} skipped=${skipped}`);
            return result;
        },
        scanChatResponse(text) {
            if (!text) return false;
            const m = text.match(/```json\s*(\{[\s\S]*?"marker"\s*:\s*"report-update"[\s\S]*?\})\s*```/);
            if (!m) return false;
            try {
                const j = JSON.parse(m[1]);
                const patch = j.data || j.patch || {};
                const result = this.applyPatch(patch, 'bot');
                _setReportStatus(`Bot updated ${result.applied} field(s)`, 'ok');
                return true;
            } catch (e) {
                console.warn('Bad report-update JSON', e);
                return false;
            }
        },
    };

    function _exportCmd(kind) {
        const k = (kind || 'pdf').toLowerCase();
        if (k === 'pdf' && _legacy('exportReportPDF')) _legacy('exportReportPDF')();
        else if (k === 'html' && _legacy('exportReportHTML')) _legacy('exportReportHTML')();
        else if ((k === 'md' || k === 'markdown') && _legacy('exportReportMarkdown')) _legacy('exportReportMarkdown')();
        else if (k === 'json') persist.exportJSON();
    }

    // ---------- Refs (P14) ----------
    const refs = {
        addFromCatalog(citeKey) { const fn = _legacy('addReportReferenceFromCatalog'); if (fn) fn(citeKey); },
        addCustom() { const fn = _legacy('addReportReferenceCustom'); if (fn) fn(); },
        remove(i) { const fn = _legacy('removeReportReference'); if (fn) fn(i); },
        catalog() { return (typeof REPORT_REFERENCES_CATALOG !== 'undefined') ? REPORT_REFERENCES_CATALOG : {}; },
        search(q) {
            q = (q || '').toLowerCase();
            const cat = this.catalog();
            const out = [];
            for (const k of Object.keys(cat)) {
                const r = cat[k];
                if (!q || (r.title || '').toLowerCase().includes(q) || (r.publisher || '').toLowerCase().includes(q) || (k || '').toLowerCase().includes(q)) {
                    out.push(r);
                }
            }
            return out;
        },
    };

    // ---------- Figures (P15) ----------
    const figures = {
        capture2D() { const fn = _legacy('captureReportFigure2D'); if (fn) fn(); },
        capture3D() { const fn = _legacy('captureReportFigure3D'); if (fn) fn(); },
        upload(e) { const fn = _legacy('uploadReportFigure'); if (fn) fn(e); },
        remove(i) { const fn = _legacy('removeReportFigure'); if (fn) fn(i); },
        reorder(fromIdx, toIdx) {
            const f = window.reportForm;
            if (!f || !f.figures) return;
            if (fromIdx === toIdx) return;
            const [m] = f.figures.splice(fromIdx, 1);
            f.figures.splice(toIdx, 0, m);
            panels.editor(); panels.preview();
            persist.autoSave();
        },
        setCaption(i, text) {
            const f = window.reportForm;
            if (!f || !f.figures || !f.figures[i]) return;
            f.figures[i].caption = text;
            persist.autoSave();
        },
    };

    // ---------- OAR (P12) ----------
    const oar = {
        add() { const fn = _legacy('addOARDoseRow'); if (fn) fn(); },
        remove(i) { const fn = _legacy('removeOARDoseRow'); if (fn) fn(i); },
        update(i, k, v) { const fn = _legacy('updateOARDoseRow'); if (fn) fn(i, k, v); },
        sparkline() {
            // Placeholder mini-DVH (P12). Future: read from dose_distribution.
            const path = 'M 0 22 L 8 22 L 16 18 L 24 12 L 32 8 L 40 5 L 48 3 L 56 2 L 64 2';
            return `<svg width="64" height="24" viewBox="0 0 64 24" style="vertical-align:middle;"><path d="${path}" fill="none" stroke="#0c4a6e" stroke-width="1"/></svg>`;
        },
    };

    // ---------- Audit log (P11) ----------
    const audit = {
        log(action, key, before, after) {
            const arr = window.__reportWorkspaceAudit || (window.__reportWorkspaceAudit = []);
            arr.push({ t: Date.now(), action, key, before, after, lang: stateProxy.language });
            window.__reportWorkspaceAudit = arr.slice(-500);
            if (typeof window.scheduleWorkspaceSave === 'function') window.scheduleWorkspaceSave('report.audit');
        },
        list() { return Array.isArray(window.__reportWorkspaceAudit) ? window.__reportWorkspaceAudit : []; },
        openModal() {
            const list = this.list();
            const html = list.slice().reverse().slice(0, 100).map(e => {
                const ts = new Date(e.t).toLocaleString();
                return `<div style="padding:4px 0;border-bottom:1px solid var(--card-border,#334155);font-size:0.7rem;">
                    <span style="color:var(--text-dim,#94a3b8);">${ts}</span> · <b style="color:var(--text,#e2e8f0);">${_escHtml(e.action)}</b> · <span style="color:var(--text-dim,#94a3b8);">${_escHtml(e.key || '')}</span>
                </div>`;
            }).join('');
            _showModal('审计日志 / Audit log (' + list.length + ')', html || '<i>Empty</i>');
        },
    };

    // ---------- Snapshots (P11) ----------
    const snapshots = {
        save(label = '') {
            try {
                const f = window.reportForm;
                if (!f) return -1;
                const arr = window.__reportWorkspaceSnapshots || (window.__reportWorkspaceSnapshots = []);
                const clone = JSON.parse(JSON.stringify(f, (k, v) => v instanceof Set ? Array.from(v) : v));
                arr.push({ t: Date.now(), label, form: clone });
                window.__reportWorkspaceSnapshots = arr.slice(-30);
                if (typeof window.scheduleWorkspaceSave === 'function') window.scheduleWorkspaceSave('report.snapshot');
                _setReportStatus('Snapshot saved', 'ok');
                return arr.length - 1;
            } catch (e) { _setReportStatus('Snapshot failed: ' + e.message, 'error'); return -1; }
        },
        list() { return Array.isArray(window.__reportWorkspaceSnapshots) ? window.__reportWorkspaceSnapshots : []; },
        async restore(idx) {
            const arr = this.list();
            const snap = arr[idx];
            if (!snap) return false;
            const confirmed = typeof window._confirmAction === 'function'
                ? await window._confirmAction(
                    `恢复 ${new Date(snap.t).toLocaleString()} 的报告快照？`,
                    `Restore snapshot from ${new Date(snap.t).toLocaleString()}?`,
                )
                : false;
            if (!confirmed) return false;
            const clone = JSON.parse(JSON.stringify(snap.form));
            clone.editedFields = new Set(clone.editedFields || []);
            const f = window.reportForm;
            if (f) {
                Object.keys(f).forEach(k => delete f[k]);
                Object.assign(f, clone);
                f.editedFields = new Set(clone.editedFields);
            }
            sources._map = new Map();
            panels.editor(); panels.preview();
            persist.autoSave();
            _setReportStatus('Snapshot restored', 'ok');
            return true;
        },
        openModal() {
            const arr = this.list();
            const html = arr.slice().reverse().map((s, i) => {
                const realIdx = arr.length - 1 - i;
                return `<div style="display:flex;justify-content:space-between;padding:6px;border-bottom:1px solid var(--card-border,#334155);font-size:0.7rem;">
                    <span><b style="color:var(--text,#e2e8f0);">${new Date(s.t).toLocaleString()}</b> · <span style="color:var(--text-dim,#94a3b8);">${_escHtml(s.label || '(no label)')}</span></span>
                    <button onclick="Report.snapshots.restore(${realIdx}).then(ok => { if (ok) Report._closeModal(); });" style="background:#0ea5e9;color:#fff;border:none;padding:3px 10px;border-radius:3px;cursor:pointer;">Restore</button>
                </div>`;
            }).join('');
            _showModal('版本快照 / Snapshots (' + arr.length + ')', html || '<i>No snapshots</i>');
        },
    };

    // ---------- Sign (P16) ----------
    const sign = {
        type(name, title) {
            const f = window.reportForm;
            if (!f) return;
            if (name !== undefined) f.signature.name = name;
            if (title !== undefined) f.signature.title = title;
            persist.autoSave();
        },
        draw(dataUrl) {
            const f = window.reportForm;
            if (!f) return;
            f.signature.drawnDataUrl = dataUrl || '';
            persist.autoSave();
        },
    };

    // ---------- Validation (P13, P19) ----------
    // Clinical badges are built only from the source-backed criteria returned
    // by /api/report/auto-fill. Local tumor-name heuristics must never create
    // treatment thresholds or imply clinical approval.
    function THRESHOLDS() {
        const planning = window.reportForm?.planning || {};
        const rationale = planning.prescriptionRationale || {};
        const criteria = rationale.target_criteria || {};
        const sourceUrls = Array.isArray(rationale.sources) ? rationale.sources : [];
        if (!sourceUrls.length || !criteria || typeof criteria !== 'object') return {};
        const rules = {};
        const fraction = value => Number(value) * 100;
        if (Number.isFinite(Number(criteria.v100_min))) {
            const limit = fraction(criteria.v100_min);
            rules['metrics.v100'] = { ok: v => v >= limit, warn: () => false, unit: '%', label: 'V100' };
        }
        if (Number.isFinite(Number(criteria.v150_max))) {
            const limit = fraction(criteria.v150_max);
            rules['metrics.v150'] = { ok: v => v <= limit, warn: () => false, unit: '%', label: 'V150' };
        }
        if (Number.isFinite(Number(criteria.v200_max))) {
            const limit = fraction(criteria.v200_max);
            rules['metrics.v200'] = { ok: v => v <= limit, warn: () => false, unit: '%', label: 'V200' };
        }
        const rxGy = Number(planning.prescriptionGy);
        if (Number.isFinite(rxGy) && rxGy > 0 && Number.isFinite(Number(criteria.d90_min_pct))) {
            const limit = rxGy * Number(criteria.d90_min_pct);
            rules['metrics.d90'] = { ok: v => v >= limit, warn: () => false, unit: 'Gy', label: 'D90' };
        }
        return rules;
    }
    const validation = {
        check() {
            const f = window.reportForm;
            const issues = [];
            if (!f) return issues;
            if (!f.patient.name) issues.push({ key: 'patient.name', msg: 'Patient name is required' });
            if (!f.patient.gender) issues.push({ key: 'patient.gender', msg: 'Gender is required' });
            if (!f.patient.id && !f.case.patientId) issues.push({ key: 'patient.id', msg: 'Patient ID is required' });
            if (!f.study.diagnosis) issues.push({ key: 'study.diagnosis', msg: 'Clinical diagnosis is required' });
            if (f.metrics.d90 !== null && f.metrics.d90 !== undefined && (f.metrics.d90 < 0 || f.metrics.d90 > 250))
                issues.push({ key: 'metrics.d90', msg: 'D90 out of plausible range (0–250 Gy)' });
            if (f.metrics.v100 !== null && f.metrics.v100 !== undefined && (f.metrics.v100 < 0 || f.metrics.v100 > 100))
                issues.push({ key: 'metrics.v100', msg: 'V100 out of 0–100%' });
            if (f.metrics.ci !== null && f.metrics.ci !== undefined && (f.metrics.ci < 0 || f.metrics.ci > 1))
                issues.push({ key: 'metrics.ci', msg: 'CI should be 0–1' });
            return issues;
        },
        openModal() {
            const issues = this.check();
            const html = issues.length === 0
                ? '<div style="color:#4ade80;padding:8px;">✅ All required fields present and within plausible ranges.</div>'
                : issues.map(i => `<div style="padding:4px;border-left:3px solid #ef4444;background:rgba(239,68,68,0.1);margin:4px 0;font-size:0.72rem;color:var(--text,#e2e8f0);"><b>${_escHtml(i.key)}</b>: ${_escHtml(i.msg)}</div>`).join('');
            _showModal('校验 / Validation', html);
        },
    };

    function metricBadge(key, val) {
        const T = THRESHOLDS();
        const r = T[key];
        if (!r || val === null || val === undefined) return '';
        const cls = r.ok(val) ? 'pass' : r.warn(val) ? 'warn' : 'fail';
        const labels = { pass: 'PASS', warn: 'WARN', fail: 'FAIL' };
        const colors = { pass: '#dcfce7|#166534', warn: '#fef3c7|#92400e', fail: '#fee2e2|#991b1b' };
        const [bg, fg] = colors[cls].split('|');
        return `<span style="background:${bg};color:${fg};font-size:0.6rem;padding:1px 5px;border-radius:6px;margin-left:3px;vertical-align:middle;">${labels[cls]}</span>`;
    }

    // ---------- Modal helper ----------
    function _showModal(title, body) {
        _closeModal();
        const previouslyFocused = document.activeElement;
        const ov = document.createElement('div');
        ov.className = 'rp-modal-overlay';
        ov.innerHTML = `<section class="rp-modal-dialog" role="dialog" aria-modal="true" aria-labelledby="rp-modal-title" tabindex="-1">
            <div class="rp-modal-header">
                <b id="rp-modal-title" class="rp-modal-title">${_escHtml(title)}</b>
                <button type="button" class="rp-modal-close" aria-label="Close dialog">✕</button>
            </div>
            <div class="rp-modal-body">${body}</div>
        </section>`;
        ov.setAttribute('data-rp-modal', '1');
        const dialog = ov.querySelector('.rp-modal-dialog');
        const close = (immediate = false) => {
            if (!ov.isConnected || ov.dataset.closing) return;
            ov.dataset.closing = '1';
            ov.classList.remove('is-open');
            ov.classList.add('is-closing');
            const remove = () => {
                if (ov.isConnected) ov.remove();
                if (previouslyFocused && typeof previouslyFocused.focus === 'function') previouslyFocused.focus();
            };
            const prefersReducedMotion = typeof window.matchMedia === 'function'
                && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
            if (immediate || prefersReducedMotion) remove();
            else window.setTimeout(remove, 160);
        };
        ov.querySelector('.rp-modal-close').addEventListener('click', () => close());
        ov.addEventListener('click', (event) => { if (event.target === ov) close(); });
        ov.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') { event.preventDefault(); close(); }
            if (event.key !== 'Tab') return;
            const focusable = [...dialog.querySelectorAll('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')];
            if (!focusable.length) return;
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
            else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        });
        document.body.appendChild(ov);
        window.requestAnimationFrame(() => { ov.classList.add('is-open'); dialog.focus(); });
        return close;
    }
    function _closeModal() { document.querySelectorAll('[data-rp-modal]').forEach(e => e.remove()); }

    // ---------- Inline language hint (P8) ----------
    function _attachLangHint(el) {
        if (!el) return;
        let hint = el.parentElement && el.parentElement.querySelector('.rp-lang-hint');
        if (!hint) {
            hint = document.createElement('div');
            hint.className = 'rp-lang-hint';
            hint.style.cssText = 'font-size:0.62rem;color:#94a3b8;margin-top:2px;font-style:italic;';
            (el.parentElement || el).appendChild(hint);
        }
        const update = () => {
            const d = _detectLanguageFromText(el.value);
            if (!d || !el.value) { hint.textContent = ''; return; }
            hint.textContent = `Detected: ${d === 'zh' ? '中文' : 'English'} (report language not auto-switched)`;
        };
        el.addEventListener('input', update);
        update();
    }

    // ---------- Persistence ----------
    let _autoSaveTimer = null;
    const persist = {
        autoSave() {
            if (_autoSaveTimer) clearTimeout(_autoSaveTimer);
            _autoSaveTimer = setTimeout(() => this._save(), 800);
            const t = document.getElementById('reportAutoSaveText');
            if (t) t.textContent = 'Auto-save: pending…';
        },
        flush() {
            if (_autoSaveTimer) {
                clearTimeout(_autoSaveTimer);
                _autoSaveTimer = null;
            }
            this._save();
        },
        _save() {
            try {
                const f = window.reportForm;
                if (!f) return;
                // Clinical report content is case data. The durable workspace
                // snapshot owns it; localStorage is reserved for account-level
                // display preferences such as language and panel geometry.
                if (typeof window.scheduleWorkspaceSave === 'function') {
                    window.scheduleWorkspaceSave('report.shell_changed');
                }
                const t = document.getElementById('reportAutoSaveText');
                if (t) t.textContent = 'Auto-save: ' + new Date().toLocaleTimeString();
            } catch (e) {
                const t = document.getElementById('reportAutoSaveText');
                if (t) t.textContent = 'Auto-save: quota exceeded';
            }
        },
        exportJSON() { const fn = _legacy('reportSaveJSON'); if (fn) fn(); },
        importJSON() { const fn = _legacy('reportLoadJSON'); if (fn) fn(); },
        async clear() {
            const confirmed = typeof window._confirmAction === 'function'
                ? await window._confirmAction(
                    '重置所有报告字段？系统将先保存一个快照。',
                    'Reset all report fields? A snapshot will be saved first.',
                )
                : false;
            if (!confirmed) return false;
            snapshots.save('pre-reset');
            const lang = stateProxy.language;
            const fn = _legacy('_newEmptyReportForm');
            if (fn) {
                const empty = fn();
                empty.language = lang;
                const f = window.reportForm;
                if (f) {
                    Object.keys(f).forEach(k => delete f[k]);
                    Object.assign(f, empty);
                    f.editedFields = new Set();
                }
                sources._map = new Map();
                panels.editor(); panels.preview();
                this.autoSave();
                _setReportStatus('Reset complete', 'ok');
            }
            return true;
        },
    };

    // ---------- Export ----------
    const exportFns = {
        pdf() { const fn = _legacy('exportReportPDF'); if (fn) fn(); },
        html() { const fn = _legacy('exportReportHTML'); if (fn) fn(); },
        markdown() { const fn = _legacy('exportReportMarkdown'); if (fn) fn(); },
        json() { persist.exportJSON(); },
    };

    // ---------- Export menu helpers ----------
    function _toggleExportMenu() {
        const m = document.getElementById('exportMenu');
        if (m) m.style.display = m.style.display === 'none' ? 'block' : 'none';
    }
    function _hideExportMenu() {
        const m = document.getElementById('exportMenu');
        if (m) m.style.display = 'none';
    }
    // Click-outside to close export menu
    function _installExportMenuClickOutside() {
        if (window._rpExportClickHooked) return;
        window._rpExportClickHooked = true;
        document.addEventListener('click', (e) => {
            const menu = document.getElementById('exportMenu');
            if (!menu || menu.style.display === 'none') return;
            // Check if click was on the export button or inside the menu
            if (e.target.closest('#exportMenu') || e.target.closest('[onclick*="_toggleExportMenu"]')) return;
            menu.style.display = 'none';
        });
    }

    // ---------- Chat palette (P9) ----------
    function _installChatPalette() {
        const inp = document.getElementById('chatInput') || document.querySelector('[data-role="chat-input"]') || document.querySelector('textarea[placeholder*="chat" i]');
        if (!inp || inp._rpPaletteHooked) return;
        inp._rpPaletteHooked = true;
        let pop = null;
        const hide = () => { if (pop) { pop.remove(); pop = null; } };
        const show = (anchor, items) => {
            hide();
            pop = document.createElement('div');
            pop.style.cssText = 'position:absolute;z-index:9999;background:#fff;border:1px solid #cbd5e1;border-radius:6px;box-shadow:0 8px 24px rgba(0,0,0,0.15);min-width:260px;font-size:0.78rem;';
            const rect = anchor.getBoundingClientRect();
            pop.style.top = (window.scrollY + rect.bottom + 4) + 'px';
            pop.style.left = (window.scrollX + rect.left) + 'px';
            pop.innerHTML = items.map((it, i) => `<div data-idx="${i}" style="padding:8px 12px;cursor:pointer;border-bottom:1px solid #f1f5f9;">${_escHtml(it.label)}<div style="font-size:0.62rem;color:#94a3b8;">${_escHtml(it.cmd)}</div></div>`).join('');
            pop.querySelectorAll('[data-idx]').forEach(el => {
                el.addEventListener('mouseenter', () => { el.style.background = '#f0f9ff'; });
                el.addEventListener('mouseleave', () => { el.style.background = ''; });
                el.addEventListener('click', () => {
                    anchor.value = items[el.dataset.idx].cmd;
                    anchor.focus();
                    hide();
                    const form = anchor.closest('form');
                    if (form) { try { form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true })); } catch (e) {} }
                    else if (typeof window.sendChat === 'function') {
                        try { window.sendChat(anchor.value); } catch (e) {}
                    }
                });
            });
            document.body.appendChild(pop);
        };
        const items = [
            { cmd: '/report fill',            label: '📝 Fill all from current data' },
            { cmd: '/report fill patient',     label: '👤 Fill patient fields only' },
            { cmd: '/report fill metrics',     label: '📊 Fill metrics & OAR' },
            { cmd: '/report fill interpretation', label: '📝 Fill narrative only' },
            { cmd: '/report zh',               label: '🇨🇳 切换到中文' },
            { cmd: '/report en',               label: '🇺🇸 Switch to English' },
            { cmd: '/report export pdf',       label: '🖨️ Export PDF' },
            { cmd: '/report export json',      label: '💾 Export JSON' },
            { cmd: '/report snapshot',         label: '📸 Save snapshot' },
        ];
        inp.addEventListener('input', () => {
            if (inp.value.startsWith('/report')) show(inp, items);
            else hide();
        });
        inp.addEventListener('blur', () => setTimeout(hide, 200));
    }

    // ---------- Chat response patch scanner (P10) ----------
    function _installChatScanner() {
        if (window._reportBotResponseHooked) return;
        window._reportBotResponseHooked = true;
        // Hook the existing sendChat wrapper so /report commands are processed
        // (the legacy module already wraps sendChat for language detection;
        // we replace that wrap with one that also handles fill/export/etc.).
        const orig = window.sendChat;
        const self = this;
        window.sendChat = function (...args) {
            const msg = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].value) || '';
            window._lastUserMessage = msg;
            // Process our commands first
            const handled = brachybot.onChatCommand(msg);
            // If we consumed the command, intercept the legacy hook
            if (handled) {
                // Let the original sendChat still run if it was a fill (so the bot
                // is also notified). For pure UI commands (en/zh), skip.
                if (/^\/report\s+(en|zh|fill|fill|export|snapshot|reset)/i.test(msg.trim())) {
                    return orig.apply(this, args);
                }
            }
            return orig.apply(this, args);
        };
        // Poll for new bot messages and scan them for report-update markers
        setInterval(() => {
            try {
                document.querySelectorAll('.chat-message, .bot-message, [data-role="assistant"]').forEach(el => {
                    if (el.dataset && el.dataset.rpScanned) return;
                    el.dataset.rpScanned = '1';
                    const text = el.textContent || el.innerText || '';
                    brachybot.scanChatResponse(text);
                });
            } catch (e) {}
        }, 1500);
    }

    // ---------- Keyboard shortcuts (P18) ----------
    function _installShortcuts() {
        if (window._rpShortcutsHooked) return;
        window._rpShortcutsHooked = true;
        document.addEventListener('keydown', (e) => {
            const tag = (e.target && e.target.tagName) || '';
            const inForm = ['INPUT', 'TEXTAREA', 'SELECT'].includes(tag) && !e.ctrlKey && !e.metaKey;
            if (inForm) return;
            if (e.ctrlKey && !e.shiftKey && (e.key === 's' || e.key === 'S')) {
                e.preventDefault();
                exportFns.json();
            } else if (e.ctrlKey && !e.shiftKey && (e.key === 'p' || e.key === 'P')) {
                e.preventDefault();
                exportFns.pdf();
            } else if (e.ctrlKey && e.shiftKey && (e.key === 'L' || e.key === 'l')) {
                e.preventDefault();
                i18n.set(stateProxy.language === 'zh' ? 'en' : 'zh', { userInitiated: true });
            } else if (e.ctrlKey && e.shiftKey && (e.key === 'P' || e.key === 'p')) {
                e.preventDefault();
                panels.switch('preview');
            }
        });
    }

    // ---------- 2-col CSS (P17) ----------
    function _install2colCss() {
        if (document.getElementById('rp-2col-css')) return;
        const s = document.createElement('style');
        s.id = 'rp-2col-css';
        s.textContent = `
            /* 2-col mode: side-by-side editor + preview */
            body.report-2col #panelReport .rp-body {
                display: flex;
                flex-direction: row;
                align-items: flex-start;
            }
            body.report-2col #panelReport .rp-edit-area,
            body.report-2col #panelReport #reportEditor {
                flex: 1 1 50% !important;
                min-width: 0;
                height: auto !important;
                max-height: none !important;
                border-right: 1px solid var(--border-hairline);
                border-bottom: none !important;
            }
            body.report-2col #panelReport .rp-preview-area,
            body.report-2col #panelReport #reportPreview {
                flex: 1 1 50% !important;
                min-width: 0;
                height: auto !important;
                max-height: none !important;
            }
            @media (max-width: 900px) {
                body.report-2col #panelReport .rp-body {
                    flex-direction: column;
                }
                body.report-2col #panelReport .rp-edit-area,
                body.report-2col #panelReport #reportEditor,
                body.report-2col #panelReport .rp-preview-area,
                body.report-2col #panelReport #reportPreview {
                    flex: 0 0 auto !important;
                    width: 100%;
                    border-right: none;
                }
                body.report-2col #panelReport .rp-edit-area,
                body.report-2col #panelReport #reportEditor {
                    border-bottom: 1px solid var(--border-hairline) !important;
                }
            }
            .oar-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
            .oar-card { background:var(--bg-2); border:1px solid var(--border-hairline); border-radius:var(--radius-xs); padding:8px 10px; }
            .oar-card-head { display:flex; justify-content:space-between; align-items:center; }
        `;
        document.head.appendChild(s);
        try {
            // BUG FIX 2026-06-16: user reported that the "2-col layout"
            // checkbox was defaulting to ON even though the HTML markup
            // had no `checked` attribute. Root cause: localStorage was
            // restoring the body.report-2col class from a previous
            // session, which silently made the layout 2-col WITHOUT
            // checking the actual checkbox. Now we ALSO sync the
            // checkbox element from the same stored value so the UI
            // and the layout are always consistent.
            //
            // The user explicitly wants 2-col to DEFAULT TO OFF. If
            // no user-initiated value is stored, ensure the class is
            // absent and the checkbox is unchecked.
            const stored = localStorage.getItem('brachyplan_report_2col');
            const cb = document.querySelector('.rp-2col-toggle input[type="checkbox"]');
            if (stored === '1') {
                document.body.classList.add('report-2col');
                if (cb) cb.checked = true;
            } else {
                document.body.classList.remove('report-2col');
                if (cb) cb.checked = false;
            }
        } catch (e) {}
    }

    // ---------- Boot ----------
    function boot() {
        _install2colCss();
        _installChatPalette();
        _installChatScanner();
        _installShortcuts();
        _installExportMenuClickOutside();
        _updateLanguageButtons();
        panels.editor();
        panels.preview();
        _setReportStatus('Ready', 'info');
    }

    return {
        state, i18n, sources, panels, autoFill, brachybot,
        refs, figures, oar, audit, snapshots, sign, persist,
        export: exportFns, validation,
        boot, metricBadge, preview,
        _closeModal, _escHtml, _setByPath, _getByPath, _attachLangHint, _showModal,
        _toggleExportMenu, _hideExportMenu,
    };
})();

// =============================================================================
// Boot the new module after the legacy module has initialized.
// =============================================================================
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        setTimeout(() => Report.boot(), 200);
    });
} else {
    setTimeout(() => Report.boot(), 200);
}


// =============================================================================
// Legacy Report module follows below (preserved verbatim)
// =============================================================================
