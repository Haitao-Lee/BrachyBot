function _composite2DViewerCanvas(axis) {
    const sliceCanvas = document.getElementById('sliceCanvas' + axis.charAt(0).toUpperCase() + axis.slice(1));
    if (!sliceCanvas) return null;
    const out = document.createElement('canvas');
    out.width = sliceCanvas.width;
    out.height = sliceCanvas.height;
    const ctx = out.getContext('2d');
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, out.width, out.height);
    const parent = sliceCanvas.parentElement;
    const canvases = parent.querySelectorAll('canvas');
    canvases.forEach(c => {
        if (c.width === sliceCanvas.width && c.height === sliceCanvas.height && c.style.display !== 'none') {
            try { ctx.drawImage(c, 0, 0); } catch (e) {}
        }
    });
    return out.toDataURL('image/png');
}

// ----- 10. Language toggle -----
function setReportLanguage(lang) {
    if (typeof REPORT_STRINGS === 'undefined' || !REPORT_STRINGS[lang]) return;
    window.reportForm.language = lang;
    if (!window.reportForm.editedFields.has('interpretation')) _autoFillInterpretation();
    _updateLanguageButtons();
    renderReportEditor();
    _updateReportPreview();
    _scheduleReportAutoSave();
}
function _updateLanguageButtons() {
    // 2026-06-16: only target the Report-internal lang buttons (those
    // scoped to `.rp-lang-toggle`). The top-right header has its own
    // `.lang-btn` toggle with `data-lang-btn` — we MUST NOT clobber
    // its CSS-driven styles or the new EN/中 chip looks dead (white
    // background on both states). The previous version used
    // `querySelectorAll('.lang-btn')` which caught both and wrote
    // `#fff` inline on the header's active button.
    const lang = window.reportForm.language;
    document.querySelectorAll('.rp-lang-toggle .lang-btn').forEach(btn => {
        const isActive = btn.dataset.lang === lang;
        btn.style.background = isActive ? '#0ea5e9' : '#fff';
        btn.style.color = isActive ? '#fff' : '#334155';
    });
}
function _detectLanguageFromText(text) {
    if (!text) return null;
    if (/[一-鿿]/.test(text)) return 'zh';
    return 'en';
}

// ----- 11. Templates -----
function applyReportTemplate(templateKey) {
    if (!templateKey) return;
    const tpl = REPORT_TEMPLATES[templateKey];
    if (!tpl) return;
    const lang = window.reportForm.language || 'zh';
    const dict = (typeof REPORT_STRINGS !== 'undefined') ? REPORT_STRINGS[lang] : null;
    const pick = (zh, en) => (lang === 'en' ? en : zh);
    const _S_or = (k, fallback) => (dict && dict[k] != null) ? dict[k] : fallback;
    window.reportForm.templateKey = templateKey;
    if (!window.reportForm.planning.prescriptionGy) window.reportForm.planning.prescriptionGy = tpl.prescriptionGy;
    if (!window.reportForm.planning.technique) {
        window.reportForm.planning.technique = tpl.i125
            ? _S_or('defaultTechniqueI125', pick('放射性粒子植入 (¹²⁵I Radioactive Seed Implantation)', 'Radioactive Seed Implantation (¹²⁵I)'))
            : _S_or('defaultTechniqueHDR',    pick('HDR 近距离治疗 (Ir-192)',                       'HDR Brachytherapy (Ir-192)'));
    }
    if (!window.reportForm.case.tumorType) {
        const tumorMap = {
            pancreas:   pick('胰腺癌',   'Pancreatic cancer'),
            prostate:   pick('前列腺癌', 'Prostate cancer'),
            head_neck:  pick('头颈肿瘤', 'Head & Neck cancer'),
            gynecology: pick('妇科肿瘤', 'Gynecological cancer'),
            liver:      pick('肝癌',     'Liver cancer'),
        };
        window.reportForm.case.tumorType = tumorMap[templateKey] || '';
    }
    if (!window.reportForm.references) window.reportForm.references = [];
    tpl.defaultReferences.forEach(key => {
        if (!window.reportForm.references.some(r => r.citeKey === key)) {
            const ref = REPORT_REFERENCES_CATALOG[key];
            if (ref) window.reportForm.references.push({ ...ref, custom: false });
        }
    });
    renderReportEditor(); _updateReportPreview(); _scheduleReportAutoSave();
}

// ----- 12. Auto-fill from NIfTI + planning data -----
async function reportAutoFill() {
    if (!window.reportForm) {
        console.warn('[reportAutoFill] window.reportForm not initialized, skipping');
        return;
    }
    const f = window.reportForm;
    if (state.ctPath) f.case.patientId = state.ctPath.split(/[\/\\]/).pop().replace(/\.nii(\.gz)?$/i, '');
    // BUG FIX 2026-06-17: set segmentation model names dynamically
    // based on tumor type (not hard-coded to pancreatic).
    if (state.metrics && state.metrics.tumor_type) {
        const tt = state.metrics.tumor_type;
        f.segmentation.ctvModelName = `nnUNet (${tt})`;
        f.segmentation.oarModelName = `TotalSegmentator (${tt})`;
    } else if (window._lastToolResults) {
        // Fallback: check tool results for tumor type info
        const tr = window._lastToolResults;
        if (tr.ctv_segmentation && tr.ctv_segmentation.tumor_type) {
            const tt = tr.ctv_segmentation.tumor_type;
            f.segmentation.ctvModelName = `nnUNet (${tt})`;
            f.segmentation.oarModelName = `TotalSegmentator (${tt})`;
        }
    }
    if (state.ctShape && state.ctSpacing) {
        // CT arrays are stored as Z,Y,X; axial slice count is axis 0.
        f.imaging.sliceCount = state.ctShape[0] || f.imaging.sliceCount;
        f.imaging.pixelSpacingMm = state.ctSpacing[0] || f.imaging.pixelSpacingMm;
        f.imaging.sliceThicknessMm = state.ctSpacing[2] || f.imaging.sliceThicknessMm;
    }
    if (state.metrics) {
        const m = state.metrics;
        if (m.total_seeds !== undefined) {
            f.planning.totalSeeds = m.total_seeds;
        }
        if (m.num_trajectories !== undefined) f.planning.trajectoryCount = m.num_trajectories;
        if (m.ctv_voxels !== undefined) f.segmentation.ctvVoxels = m.ctv_voxels;
        // Dose-grid voxel counts are not guaranteed to use the original CT
        // spacing. Use the source volume persisted by the segmentation chain.
        if (Number.isFinite(Number(m.ctv_volume_mm3))) {
            f.case.ctvVolumeMm3 = Number(m.ctv_volume_mm3);
        }
        if (m.v100 !== undefined) f.metrics.v100 = m.v100 * 100;
        if (m.d90 !== undefined) f.metrics.d90 = m.d90;
        if (m.d95 !== undefined) f.metrics.d95 = m.d95;
        if (m.v150 !== undefined) f.metrics.v150 = m.v150 * 100;
        if (m.v200 !== undefined) f.metrics.v200 = m.v200 * 100;
        if (m.ci !== undefined) f.metrics.ci = m.ci;
        if (m.hi !== undefined) f.metrics.hi = m.hi;
        if (m.gi !== undefined) f.metrics.gi = m.gi;
        if (m.plan_score !== undefined) f.metrics.score = m.plan_score;
    }
    if (state.metrics && state.metrics.oar_metrics) {
        f.oarDose = Object.entries(state.metrics.oar_metrics)
            .filter(([n, x]) => x && (x.d2cc || x.d1cc || x.d0_1cc))
            .map(([n, x]) => ({
                organ: _resolveOARDisplayName(n, x),
                label_id: x.label_id ?? x.labelId ?? null,
                d2cc: x.d2cc || null,
                d1cc: x.d1cc || null,
                d0_1cc: x.d0_1cc || null,
                dmax: x.dmax || x.max_dose || null,
                v100: x.v100 ? x.v100 * 100 : null,
            }))
            .sort((a, b) => (b.d2cc || 0) - (a.d2cc || 0)).slice(0, 12);
    }
    if (dataTreeState && dataTreeState.organs) f.case.oarCount = dataTreeState.organs.length || f.case.oarCount;
    // BUG FIX 2026-06-22: respect global UI language first
    if (typeof window._i18nLang === 'string') {
        f.language = window._i18nLang;
    } else if (window._lastUserMessage) {
        const detected = _detectLanguageFromText(window._lastUserMessage);
        if (detected) f.language = detected;
    }
    if (!f.editedFields.has('interpretation')) _autoFillInterpretation();
    if ((!f.references || f.references.length === 0) && f.templateKey) {
        applyReportTemplate(f.templateKey);
        return;
    }
    _setReportStatus('Auto-filled from NIfTI + planning', 'ok');
    renderReportEditor(); _updateReportPreview(); _scheduleReportAutoSave();
}

function _autoFillInterpretation() {
    const f = window.reportForm;
    const m = (window.state && window.state.metrics) || {};
    const v100 = m.v100 !== undefined ? m.v100 * 100 : null;
    const d90 = m.d90 || null;
    const score = m.plan_score;
    const oarMetrics = m.oar_metrics || {};
    const lines = [];

    lines.push('**Planning metric interpretation**');
    lines.push('');
    lines.push('This section summarizes observed planning metrics only. Clinical pass/fail decisions must use source-backed thresholds from `clinical_kb` retrieval results or explicit `plan_config` constraints for the current tumor site.');
    lines.push('');

    if (v100 !== null) {
        lines.push(`- CTV V100: ${v100.toFixed(1)}%. This is an observed coverage metric, not a local-template pass/fail verdict.`);
    }
    if (d90 !== null) {
        const rxGy = typeof _getCurrentPrescriptionGy === 'function'
            ? _getCurrentPrescriptionGy()
            : 120;
        lines.push(`- CTV D90: ${d90.toFixed(2)} Gy; current report prescription is ${rxGy.toFixed(0)} Gy. Interpret the threshold from the cited source.`);
    }
    if (score !== undefined) {
        lines.push(`- Plan score: ${Number(score).toFixed(0)}/100. This score is for ranking and QA triage, not clinical approval.`);
    }
    lines.push('');

    const sortedOars = Object.entries(oarMetrics)
        .filter(([_, x]) => x && (x.d2cc || x.dmax || x.max_dose))
        .sort((a, b) => ((b[1].d2cc || b[1].dmax || b[1].max_dose || 0) - (a[1].d2cc || a[1].dmax || a[1].max_dose || 0)))
        .slice(0, 5);
    if (sortedOars.length > 0) {
        lines.push('**Organ-at-risk dose summary** (highest available OAR metrics):');
        for (const [rawName, om] of sortedOars) {
            const name = _resolveOARDisplayName(rawName, om);
            const d2cc = om.d2cc || 0;
            const dmax = om.dmax || om.max_dose || 0;
            lines.push(`- **${name}**: D2cc = ${d2cc.toFixed(2)} Gy, Dmax = ${dmax.toFixed(2)} Gy; interpret with site-specific OAR limits.`);
        }
        lines.push('');
    }

    lines.push('**Recommended next steps**:');
    lines.push('- Query `clinical_kb` for prescription dose, V100/D90/V150/V200 criteria, and OAR limits for the current tumor site; include real links in report references.');
    lines.push('- Radiation oncologist and physicist review should combine sourced thresholds, image registration, trajectory feasibility, and independent dose verification.');
    lines.push('');
    lines.push('_This is an auto-generated metric summary from BrachyBot; it does not replace a signed clinical treatment plan._');

    f.interpretation = lines.join('\n');
    f.safety = '**Safety & Quality Control**\n\n- Seed activity and source strength require physicist verification.\n- Pre/post-treatment dose verification should use an independent method.\n- OAR limits and target coverage thresholds must come from `clinical_kb` or explicit `plan_config`, not local report defaults.\n- Informed consent and final sign-off follow institutional workflow.';
}

// ----- 13. Reset -----
function reportReset() {
    if (!confirm('Reset all report fields?')) return;
    window.reportForm = _newEmptyReportForm();
    renderReportEditor(); _updateReportPreview(); _scheduleReportAutoSave();
}

// ----- 14. Auto-save to localStorage -----
let _reportAutoSaveTimer = null;
function _scheduleReportAutoSave() {
    if (_reportAutoSaveTimer) clearTimeout(_reportAutoSaveTimer);
    _reportAutoSaveTimer = setTimeout(_reportAutoSave, 800);
    const t = document.getElementById('reportAutoSaveText');
    if (t) t.textContent = 'Auto-save: pending…';
}
function _reportAutoSave() {
    try {
        const f = window.reportForm;
        f.editedFields = Array.from(f.editedFields);
        const key = typeof caseStorageKey === 'function'
            ? caseStorageKey('brachyplan_reportForm')
            : 'brachyplan_reportForm:web';
        localStorage.setItem(key, JSON.stringify(f));
        f.editedFields = new Set(f.editedFields);
        const t = document.getElementById('reportAutoSaveText');
        if (t) t.textContent = 'Auto-save: ' + new Date().toLocaleTimeString();
    } catch (e) {}
}

function flushActiveReportState() {
    if (_reportAutoSaveTimer) {
        clearTimeout(_reportAutoSaveTimer);
        _reportAutoSaveTimer = null;
    }
    if (window.reportForm) _reportAutoSave();
    if (window.Report && Report.persist && typeof Report.persist.flush === 'function') {
        Report.persist.flush();
    }
}
window.flushActiveReportState = flushActiveReportState;
function _newEmptyReportForm() {
    // BUG FIX 2026-06-16: default language is now 'en' to match the
    // global UI language default. The previous 'zh' default caused
    // English-speaking users to see Chinese labels until they manually
    // switched. We use the global _i18nLang if available, falling
    // back to 'en'.
    const lang = (typeof window._i18nLang === 'string') ? window._i18nLang : 'en';
    return _localizedEmptyReportForm(lang);
}

function _localizedEmptyReportForm(language) {
    // Resolve defaults through REPORT_STRINGS so the form is always in
    // the active language, with an ASCII fallback if REPORT_STRINGS
    // hasn't loaded yet.
    const S = (typeof REPORT_STRINGS !== 'undefined' && REPORT_STRINGS[language]) ? REPORT_STRINGS[language] : null;
    const pick = (zh, en) => (language === 'en' ? en : zh);
    const _S_or = (k, fallback) => (S && S[k] != null) ? S[k] : fallback;
    return {
        version: 3,
        language: language,
        templateKey: '',
        hospital: { name: '', dept: '', address: '', contact: '', logoDataUrl: '' },
        patient: {
            name: '',
            // Demographic fields must come from DICOM or explicit user input.
            gender: '',
            age: '',
            id: '',
            department: _S_or('defaultDepartment', pick('放射治疗科', 'Radiation Oncology')),
            ward: '',
            bed: '',
        },
        study: { modality: 'CT', scanDate: '', accession: '', radiologist: '', diagnosis: '', clinicalHistory: '', priorTreatment: '' },
        case: { patientId: '', tumorType: '', planDate: new Date().toISOString().slice(0, 10), plannerName: '', ctvVolumeMm3: null, oarCount: null },
        imaging: { modality: 'CT', scanner: '', sliceCount: null, pixelSpacingMm: null, sliceThicknessMm: null, contrast: '', acquisitionDate: '' },
        segmentation: { ctvModelName: '', ctvVoxels: null, oarModelName: '', contouringNotes: '' },
        planning: {
            technique: _S_or('defaultTechniqueI125', pick('放射性粒子植入 (¹²⁵I Radioactive Seed Implantation)', 'Radioactive Seed Implantation (¹²⁵I)')),
            prescriptionGy: null, prescriptionUnit: 'Gy',
            totalSeeds: null, totalActivityMBq: null, trajectoryCount: null, dwellPositionCount: null,
        },
        metrics: { v100: null, d90: null, d95: null, v150: null, v200: null, ci: null, hi: null, gi: null, score: null },
        oarDose: [],
        interpretation: '',
        safety: '',
        qaNotes: '',
        references: [],
        figures: [],
        signature: {
            name: '',
            title: '',
            date: '',
            notes: '',
            drawnDataUrl: '',
        },
        editedFields: new Set(),
    };
}

function _loadReportFromStorage() {
    try {
        const key = typeof caseStorageKey === 'function'
            ? caseStorageKey('brachyplan_reportForm')
            : 'brachyplan_reportForm:web';
        const stored = localStorage.getItem(key);
        if (!stored) return;
        const parsed = JSON.parse(stored);
        if (parsed && typeof parsed === 'object' && parsed.version) {
            parsed.editedFields = new Set(parsed.editedFields || []);
            // BUG FIX 2026-06-17: when restoring from localStorage,
            // sync the report language with the GLOBAL UI language.
            // Previously the report kept its stored language (often
            // 'zh' from a prior session) even when the global default
            // was 'en', leaving Chinese content visible until the
            // user manually toggled. Now we align to global
            // (window._i18nLang) on every restore.
            try {
                const globalLang = (typeof window._i18nLang === 'string')
                    ? window._i18nLang : 'en';
                if (parsed.language !== globalLang) {
                    parsed.language = globalLang;
                }
            } catch (_) {}
            window.reportForm = parsed;
        }
    } catch (e) {}
}

// ----- 15. Save / Load JSON -----
function reportSaveJSON() {
    const f = window.reportForm;
    f.editedFields = Array.from(f.editedFields);
    const blob = new Blob([JSON.stringify(f, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `brachybot-report-${(f.case.patientId || 'form')}-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
    f.editedFields = new Set(f.editedFields);
    _setReportStatus('Saved JSON', 'ok');
}
function reportLoadJSON() {
    const input = document.createElement('input');
    input.type = 'file'; input.accept = 'application/json';
    input.onchange = (e) => {
        const file = e.target.files[0]; if (!file) return;
        const reader = new FileReader();
        reader.onload = (ev) => {
            try {
                const parsed = JSON.parse(ev.target.result);
                parsed.editedFields = new Set(parsed.editedFields || []);
                window.reportForm = parsed;
                renderReportEditor(); _updateReportPreview();
                _setReportStatus('Loaded JSON', 'ok');
            } catch (err) { _setReportStatus('JSON parse failed: ' + err.message, 'warn'); }
        };
        reader.readAsText(file);
    };
    input.click();
}

// ----- 16. Markdown → safe HTML -----
function _renderMarkdown(md) {
    if (!md) return '';
    let html = escHtml(md);
    html = html.replace(/^## (.+)$/gm, '<h3 style="font-size:10.5pt;margin:4px 0 2px 0;color:#0c4a6e;">$1</h3>');
    html = html.replace(/^# (.+)$/gm, '<h2 style="font-size:11pt;margin:6px 0 3px 0;color:#0c4a6e;">$1</h2>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
    html = html.replace(/\*(.+?)\*/g, '<i>$1</i>');
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (m, t, u) => {
        const safe = /^(https?:|mailto:|#)/i.test(u.trim()) ? u : '#';
        return `<a href="${safe}" target="_blank" rel="noopener" style="color:#0c4a6e;text-decoration:underline;">${t}</a>`;
    });
    html = html.replace(/^[\-\*] (.+)$/gm, '<li style="margin:1.5px 0;">$1</li>');
    html = html.replace(/(<li[^>]*>.+?<\/li>\s*)+/g, m => `<ul style="margin:2px 0 2px 18px;padding:0;">${m}</ul>`);
    html = html.replace(/_([^_]+)_/g, '<i>$1</i>');
    html = html.replace(/\n{2,}/g, '</p><p style="margin:2px 0;text-indent:2em;">');
    html = '<p style="margin:2px 0;text-indent:2em;">' + html + '</p>';
    html = html.replace(/<p[^>]*>\s*<\/p>/g, '');
    html = html.replace(/<p[^>]*>(<h[23])/g, '$1');
    html = html.replace(/(<\/h[23]>)<\/p>/g, '$1');
    return html;
}

// ----- 17. Render the multi-page A4 preview -----
function _sourceBackedMetricAssessment(form, metricKey, value) {
    const rationale = form?.planning?.prescriptionRationale || {};
    const criteria = rationale.target_criteria || {};
    const sources = Array.isArray(rationale.sources) ? rationale.sources : [];
    const notAssessed = form?.language === 'zh' ? '未评估' : 'Not assessed';
    if (!sources.length || !criteria || typeof criteria !== 'object') {
        return { reference: form?.language === 'zh' ? '见病例引用标准' : 'See cited case criteria', statusClass: null, statusText: notAssessed };
    }
    let threshold = null;
    let reference = '';
    let passed = null;
    const numericValue = Number(value);
    if (!Number.isFinite(numericValue)) return { reference: '—', statusClass: null, statusText: notAssessed };
    if (metricKey === 'v100' && Number.isFinite(Number(criteria.v100_min))) {
        threshold = Number(criteria.v100_min) * 100;
        reference = `≥ ${threshold.toFixed(1)} %`;
        passed = numericValue >= threshold;
    } else if (metricKey === 'v150' && Number.isFinite(Number(criteria.v150_max))) {
        threshold = Number(criteria.v150_max) * 100;
        reference = `≤ ${threshold.toFixed(1)} %`;
        passed = numericValue <= threshold;
    } else if (metricKey === 'v200' && Number.isFinite(Number(criteria.v200_max))) {
        threshold = Number(criteria.v200_max) * 100;
        reference = `≤ ${threshold.toFixed(1)} %`;
        passed = numericValue <= threshold;
    } else if (metricKey === 'd90' && Number.isFinite(Number(criteria.d90_min_pct))) {
        const rxGy = Number(form?.planning?.prescriptionGy);
        if (Number.isFinite(rxGy) && rxGy > 0) {
            threshold = Number(criteria.d90_min_pct) * rxGy;
            reference = `≥ ${(Number(criteria.d90_min_pct) * 100).toFixed(0)}% Rx (${threshold.toFixed(1)} Gy)`;
            passed = numericValue >= threshold;
        }
    }
    if (passed === null) {
        return { reference: form?.language === 'zh' ? '当前来源未定义' : 'Not defined by current source', statusClass: null, statusText: notAssessed };
    }
    return {
        reference,
        statusClass: passed ? 'pass' : 'warn',
        statusText: passed ? (form?.language === 'zh' ? '符合' : 'Meets criterion') : (form?.language === 'zh' ? '需复核' : 'Needs review'),
    };
}

function _sourceBackedOarAssessment(form, row) {
    const rationale = form?.planning?.prescriptionRationale || {};
    const allCriteria = rationale.oar_criteria || {};
    const sources = Array.isArray(rationale.sources) ? rationale.sources : [];
    const notAssessed = form?.language === 'zh' ? '未评估' : 'Not assessed';
    if (!sources.length || !allCriteria || typeof allCriteria !== 'object') {
        return { statusClass: null, statusText: notAssessed };
    }
    const normalized = String(row?.organ || '').toLowerCase().replace(/[^a-z0-9]+/g, '_');
    let criterion = null;
    for (const [name, candidate] of Object.entries(allCriteria)) {
        const key = String(name).toLowerCase().replace(/[^a-z0-9]+/g, '_');
        if (normalized === key || normalized.includes(key) || (key === 'bowel' && normalized.includes('bowel'))) {
            criterion = candidate;
            break;
        }
    }
    if (!criterion || typeof criterion !== 'object') return { statusClass: null, statusText: notAssessed };
    if (row?.d2cc === null || row?.d2cc === undefined) return { statusClass: null, statusText: notAssessed };
    const d2cc = Number(row.d2cc);
    let limit = Number(criterion.d2cc_gy);
    if (!Number.isFinite(limit) && Number.isFinite(Number(criterion.d2cc_pct_max))) {
        const rxGy = Number(form?.planning?.prescriptionGy);
        if (Number.isFinite(rxGy) && rxGy > 0) limit = Number(criterion.d2cc_pct_max) * rxGy;
    }
    // EQD2 constraints are not compared with unconverted physical dose.
    if (!Number.isFinite(d2cc) || !Number.isFinite(limit)) return { statusClass: null, statusText: notAssessed };
    const passed = d2cc <= limit;
    return {
        statusClass: passed ? 'pass' : 'warn',
        statusText: passed ? (form?.language === 'zh' ? '符合' : 'Meets criterion') : (form?.language === 'zh' ? '需复核' : 'Needs review'),
    };
}

function _updateReportPreview() {
    const pagesEl = document.getElementById('reportPages');
    if (!pagesEl) return;
    if (!window.reportForm) window.reportForm = _newEmptyReportForm();
    const f = window.reportForm;
    const s = (typeof REPORT_STRINGS !== 'undefined') ? REPORT_STRINGS[f.language] : null;
    if (!s) return;
    const hospitalName = f.hospital.name || s.hospitalName;
    const hospitalDept = f.hospital.dept || s.hospitalDept;
    const hospitalAddress = f.hospital.address || s.hospitalAddress;
    const hospitalContact = f.hospital.contact || s.hospitalContact;
    const hospitalNameEn = s.hospitalNameEn;
    const U = s.units || { Gy: 'Gy', mm3: 'mm³', percent: '%', cc: 'cc', mm: 'mm', MBq: 'MBq' };
    const ND = s.noData || '—';
    const d2ccLabel = f.language === 'zh' ? 'D₂cc' : 'D₂cc';
    const d1ccLabel = f.language === 'zh' ? 'D₁cc' : 'D₁cc';
    const d01ccLabel = f.language === 'zh' ? 'D₀.₁cc' : 'D₀.₁cc';
    const v100Label = 'V100';
    const gyUnit = U.Gy;
    const reportTotalPages = 4;
    const pageFooter = (pageNo) =>
        `<div class="hp-page-footer"><span class="pageno">— ${escHtml(s.page)} ${pageNo} ${escHtml(s.pageOf)} ${reportTotalPages} —</span></div>`;
    const secondaryTitle = (label) => f.language === 'zh'
        ? `<span class="hp-section-title-en">${escHtml(label)}</span>`
        : '';

    // ============== PAGE 1: Letterhead + Patient ID + Imaging + Case ==============
    // BUG FIX 2026-06-17 (header redesign): the user requested a
    // letterhead with 3 logos on the LEFT and a 2-line right-aligned
    // credit block on the RIGHT:
    //   Line 1: Brachybot by SJTU × Ruijin Hospital × 放射治疗科
    //   Line 2: full GitHub clone URL (no "github:" label — the URL
    //           itself starts with "github.com" so a label would
    //           be redundant duplication)
    // BUG FIX 2026-06-17 (real logos): SJTU and Ruijin logos are
    // the real high-res PNGs in _assets/sjtu-real.png and
    // _assets/ruijin-real.png.
    const bylineLine1 = 'Powered by BrachyBot';
    const bylineLine2 = 'Developed by SJTU && Ruijin Hospital';
    const githubUrl = 'https://github.com/Haitao-Lee/BrachyBot.git';
    let p1 = `
        <div class="report-page">
            <div class="hp-letterhead">
                <div class="hp-logo-group">
                    <img src="_assets/brachybot-logo.png" alt="BrachyBot" class="hp-logo-img" title="BrachyBot"/>
                    <img src="_assets/sjtu-real.png" alt="SJTU" class="hp-logo-img" title="Shanghai Jiao Tong University"/>
                    <img src="_assets/ruijin-real.png" alt="Ruijin" class="hp-logo-img" title="Ruijin Hospital"/>
                </div>
                <div class="hp-letterhead-text">
                    <div class="hp-letterhead-byline">${escHtml(bylineLine1)}</div>
                    <div class="hp-letterhead-byline">${escHtml(bylineLine2)}</div>
                    <div class="hp-letterhead-github">
                        <a href="${escHtml(githubUrl)}" target="_blank" rel="noopener">${escHtml(githubUrl)}</a>
                    </div>
                </div>
            </div>
            <div class="hp-running-header">
                <span>${escHtml(s.confidentiality)}</span>
                <span class="right">${escHtml(hospitalName)}</span>
            </div>
            <h1 class="hp-title">${escHtml(s.reportTitle)}</h1>
            <div class="hp-subtitle">${escHtml(s.reportSubtitle)}</div>
            <h2 class="hp-section-title">${escHtml(s.section1)}${secondaryTitle('Patient Summary')}</h2>
            <div class="hp-section-body">
                <table class="hp-id-table">
                    <tr><th>${escHtml(s.name)}</th><td>${escHtml(f.patient.name) || ND}</td>
                        <th>${escHtml(s.gender)}</th><td>${escHtml(f.patient.gender) || ND}</td></tr>
                    <tr><th>${escHtml(s.age)}</th><td>${f.patient.age || ND}</td>
                        <th>${escHtml(s.id)}</th><td>${escHtml(f.patient.id) || escHtml(f.case.patientId) || ND}</td></tr>
                    <tr><th>${escHtml(s.department)}</th><td colspan="3">${escHtml(f.patient.department) || ND}</td></tr>
                    <tr><th>${escHtml(s.ward)}</th><td>${escHtml(f.patient.ward) || ND}</td>
                        <th>${escHtml(s.bed)}</th><td>${escHtml(f.patient.bed) || ND}</td></tr>
                    <tr><th>${escHtml(s.diagnosis)}</th><td colspan="3">${_renderInlineMd(f.study.diagnosis) || ND}</td></tr>
                    <tr><th>${escHtml(s.clinicalHistory)}</th><td colspan="3">${_renderInlineMd(f.study.clinicalHistory) || ND}</td></tr>
                </table>
            </div>
            <h2 class="hp-section-title">${escHtml(s.sectionN1)}${secondaryTitle('Imaging Data')}</h2>
            <div class="hp-section-body">
                <table class="hp-id-table">
                    <tr><th>${escHtml(s.modality)}</th><td>${escHtml(f.study.modality) || ND}</td>
                        <th>${escHtml(s.scanDate)}</th><td>${escHtml(f.study.scanDate) || ND}</td></tr>
                    <tr><th>${escHtml(s.accession)}</th><td>${escHtml(f.study.accession) || ND}</td>
                        <th>${escHtml(s.radiologist)}</th><td>${escHtml(f.study.radiologist) || ND}</td></tr>
                </table>
            </div>
            <h2 class="hp-section-title">${escHtml(s.sectionN2)}${secondaryTitle('Target Delineation')}</h2>
            <div class="hp-section-body">
                <p class="no-indent"><span class="hp-key">${escHtml(s.ctvVolume)}：</span>${f.case.ctvVolumeMm3 !== null ? f.case.ctvVolumeMm3.toFixed(1) + ' ' + U.mm3 : ND}；<span class="hp-key">${escHtml(s.oarCount)}：</span>${f.case.oarCount !== null ? f.case.oarCount : ND}；<span class="hp-key">${escHtml(s.segmentationModel)}：</span>${escHtml(f.segmentation.ctvModelName) || ND}</p>
            </div>
    `;
    // Figures on page 1 if any
    if (f.figures && f.figures.length > 0) {
        const fig1 = f.figures[0];
        const fig1Url = _safeReportImageUrl(fig1.dataUrl);
        if (fig1Url) p1 += `<div class="hp-figure"><img src="${escHtml(fig1Url)}" alt="${escHtml(fig1.title || '')}"/><div class="hp-figure-cap">${escHtml(s.figCaption)} 1 · ${escHtml(fig1.title || '')}${fig1.caption ? ' — ' + escHtml(fig1.caption) : ''}</div></div>`;
    }
    p1 += `${pageFooter(1)}</div>`;

    // ============== PAGE 2: Methodology + Planning + Plan Quality ==============
    const t = (key) => escHtml(s[key]);
    const unitGy = (v) => v !== null ? `${v} ${U.Gy}` : ND;
    const unitMm3 = (v) => v !== null ? `${v.toFixed(1)} ${U.mm3}` : ND;
    const unitMBq = (v) => v !== null ? `${v} ${U.MBq}` : ND;
    const seedsUnit = s.seedsUnitWord ? ' ' + s.seedsUnitWord : '';
    const trajUnit = s.trajUnitWord ? ' ' + s.trajUnitWord : '';
    const aV100 = _sourceBackedMetricAssessment(f, 'v100', f.metrics.v100);
    const aD90 = _sourceBackedMetricAssessment(f, 'd90', f.metrics.d90);
    const aV150 = _sourceBackedMetricAssessment(f, 'v150', f.metrics.v150);
    const aV200 = _sourceBackedMetricAssessment(f, 'v200', f.metrics.v200);
    const notAssessed = f.language === 'zh' ? '未评估' : 'Not assessed';
    let p2 = `<div class="report-page">
        <div class="hp-running-header"><span>${escHtml(s.confidentiality)}</span><span class="right">${escHtml(s.section2)}</span></div>
        <h2 class="hp-section-title">${escHtml(s.section4)}${secondaryTitle('Target & Prescription')}</h2>
        <div class="hp-section-body">
            <p class="no-indent"><span class="hp-key">${t('technique')}：</span>${_renderInlineMd(f.planning.technique) || ND}</p>
            <p class="no-indent"><span class="hp-key">${t('prescriptionDose')}：</span>${f.planning.prescriptionGy !== null ? f.planning.prescriptionGy + ' ' + U.Gy : ND}；
                <span class="hp-key">${t('totalSeeds')}：</span>${f.planning.totalSeeds !== null ? f.planning.totalSeeds + seedsUnit : ND}；
                <span class="hp-key">${t('totalActivity')}：</span>${unitMBq(f.planning.totalActivityMBq)}；
                <span class="hp-key">${t('trajectories')}：</span>${f.planning.trajectoryCount !== null ? f.planning.trajectoryCount + trajUnit : ND}</p>
        </div>
        <h2 class="hp-section-title">${escHtml(s.section2)}${secondaryTitle('Plan Quality Assessment')}</h2>
        <div class="hp-section-body">
            <table class="hp-table">
                <thead><tr><th style="width:25%">${t('metric')}</th><th style="width:18%">${t('value')}</th><th>${t('reference')}</th><th>${t('status')}</th></tr></thead>
                <tbody>
                    ${_hpMetricRow('V100 (CTV)', f.metrics.v100, U.percent, aV100.reference, aV100.statusClass, s, aV100.statusText)}
                    ${_hpMetricRow('D90', f.metrics.d90, U.Gy, aD90.reference, aD90.statusClass, s, aD90.statusText)}
                    ${_hpMetricRow('D95', f.metrics.d95, U.Gy, '—', null, s, notAssessed)}
                    ${_hpMetricRow('V150', f.metrics.v150, U.percent, aV150.reference, aV150.statusClass, s, aV150.statusText)}
                    ${_hpMetricRow('V200', f.metrics.v200, U.percent, aV200.reference, aV200.statusClass, s, aV200.statusText)}
                    ${_hpMetricRow('CI', f.metrics.ci, '', '—', null, s, notAssessed)}
                    ${_hpMetricRow('HI', f.metrics.hi, '', '—', null, s, notAssessed)}
                    ${_hpMetricRow('GI', f.metrics.gi, '', '—', null, s, notAssessed)}
                    ${_hpMetricRow(s.planScoreLabel || 'Plan score', f.metrics.score, '/100', f.language === 'zh' ? '内部质量排序' : 'Internal QA ranking', null, s, f.language === 'zh' ? '非临床批准' : 'Not clinical approval')}
                </tbody>
            </table>
        </div>
    `;
    if (f.figures && f.figures.length > 1) {
        const fig2 = f.figures[1];
        const fig2Url = _safeReportImageUrl(fig2.dataUrl);
        if (fig2Url) p2 += `<div class="hp-figure"><img src="${escHtml(fig2Url)}" alt="${escHtml(fig2.title || '')}"/><div class="hp-figure-cap">${escHtml(s.figCaption)} 2 · ${escHtml(fig2.title || '')}${fig2.caption ? ' — ' + escHtml(fig2.caption) : ''}</div></div>`;
    }
    p2 += `${pageFooter(2)}</div>`;

    // ============== PAGE 3: OAR Dose + Interpretation ==============
    let p3 = `<div class="report-page">
        <div class="hp-running-header"><span>${escHtml(s.confidentiality)}</span><span class="right">${escHtml(s.section3)}</span></div>`;
    if (f.oarDose && f.oarDose.length > 0) {
        p3 += `<h2 class="hp-section-title">${escHtml(s.section3)}${secondaryTitle('OAR Dose')}</h2>
        <div class="hp-section-body">
            <table class="hp-grid-table">
                <thead><tr><th>${escHtml(s.organ)}</th><th>${d2ccLabel} (${U.Gy})</th><th>${d1ccLabel} (${U.Gy})</th><th>${d01ccLabel} (${U.Gy})</th><th>${v100Label} (${U.percent})</th><th>${t('status')}</th></tr></thead>
                <tbody>
                ${f.oarDose.map(o => {
                    const organName = _resolveOARDisplayName(o.organ, o);
                    const assessment = _sourceBackedOarAssessment(f, o);
                    const cls = assessment.statusClass || '';
                    const statusText = assessment.statusText;
                    return `<tr>
                        <td>${escHtml(organName)}</td>
                        <td>${o.d2cc !== null ? o.d2cc.toFixed(1) : ND}</td>
                        <td>${o.d1cc !== null ? o.d1cc.toFixed(1) : ND}</td>
                        <td>${o.d0_1cc !== null ? o.d0_1cc.toFixed(1) : ND}</td>
                        <td>${o.v100 !== null ? o.v100.toFixed(1) : ND}</td>
                        <td class="${cls}">${escHtml(statusText)}</td>
                    </tr>`;
                }).join('')}
                </tbody>
            </table>
        </div>`;
    } else {
        const noOarDose = f.language === 'zh'
            ? '当前病例尚无可用的危及器官剂量结果。完成剂量计算后，此处将自动显示器官剂量指标与来源支持的限值评估。'
            : 'No organ-at-risk dose results are available for this case. After dose calculation, this section will show organ dose metrics and source-backed limit assessments.';
        p3 += `<h2 class="hp-section-title">${escHtml(s.section3)}${secondaryTitle('OAR Dose')}</h2>
        <div class="hp-section-body"><p class="no-indent">${escHtml(noOarDose)}</p></div>`;
    }
    if (f.interpretation) {
        p3 += `<h2 class="hp-section-title">${escHtml(s.section5)}${secondaryTitle('Clinical Interpretation')}</h2>
        <div class="hp-section-body">${_renderMarkdown(f.interpretation)}</div>`;
    }
    p3 += `${pageFooter(3)}</div>`;

    // ============== PAGE 4: Safety + QA + Methodology + References + Disclaimer + Signatures ==============
    let p4 = `<div class="report-page">
        <div class="hp-running-header"><span>${escHtml(s.confidentiality)}</span><span class="right">${escHtml(s.section6)} · ${s.section7}</span></div>`;
    if (f.safety) {
        p4 += `<h2 class="hp-section-title">${escHtml(s.section6)}${secondaryTitle('Safety & QC')}</h2>
        <div class="hp-section-body">${_renderMarkdown(f.safety)}</div>`;
    }
    if (f.qaNotes) {
        p4 += `<h2 class="hp-section-title">${escHtml(s.qaNotes)}${secondaryTitle('QA Notes')}</h2>
        <div class="hp-section-body">${_renderMarkdown(f.qaNotes)}</div>`;
    }
    // Method (small reference block)
    p4 += `<h2 class="hp-section-title">${escHtml(s.method)}${secondaryTitle('Methodology')}</h2>
        <div class="hp-section-body"><ol style="margin:2px 0 2px 18px;padding:0;font-size:9pt;">${s.methodSteps.map(st => `<li style="margin:1.5px 0;">${st}</li>`).join('')}</ol></div>`;
    // References
    if (f.references && f.references.length > 0) {
        p4 += `<h2 class="hp-section-title">${escHtml(s.section7)}${secondaryTitle('References')}</h2>
        <div class="hp-section-body"><ol class="hp-references">${f.references.map((r, i) => {
            const key = r.citeKey || `ref${i+1}`;
            const safeUrl = _safeReportUrl(r.url);
            return `<li><span class="ref-num">[${i+1}]</span> ${escHtml(r.title || '')}${r.publisher ? ' <i>(' + escHtml(r.publisher) + ')</i>' : ''}${r.year ? ', ' + r.year : ''}.${safeUrl ? ' <a href="' + escHtml(safeUrl) + '" target="_blank" rel="noopener noreferrer">↗</a>' : ''}</li>`;
        }).join('')}</ol></div>`;
    }
    // Disclaimer
    p4 += `<div class="hp-disclaimer"><b>⚠️ ${escHtml(s.disclaimer)}:</b><br/>${escHtml(s.disclaimerText)}</div>`;
    // BrachyBot generates the document but never signs as a clinician. The
    // planning and review fields stay independent and require human identity.
    const safeSignatureUrl = _safeReportImageUrl(f.signature.drawnDataUrl);
    const reviewerSignature = safeSignatureUrl
        ? `<img class="hp-signature-image" src="${escHtml(safeSignatureUrl)}" alt="Reviewer signature"/>`
        : '';
    p4 += `<h2 class="hp-section-title">${escHtml(s.section9)}${secondaryTitle('Physician Signatures')}</h2>
        <div class="hp-section-body">
            <div class="hp-signature">
                <div class="hp-signature-block">
                    <div class="hp-signature-label">${escHtml(s.physicianPlanner)}</div>
                    <div class="hp-signature-name">${escHtml(f.case.plannerName) || ND}</div>
                    <div class="hp-signature-title">${escHtml(f.patient.department) || ''}</div>
                    <div class="hp-signature-date">${escHtml(f.case.planDate) || ''}</div>
                </div>
                <div class="hp-signature-block">
                    <div class="hp-signature-label">${escHtml(s.physicianReviewer)}</div>
                    <div class="hp-signature-name">${escHtml(f.signature.name) || ND}</div>
                    <div class="hp-signature-title">${escHtml(f.signature.title) || ''}</div>
                    <div class="hp-signature-date">${escHtml(f.signature.date) || ''}</div>
                    ${reviewerSignature}
                </div>
            </div>
            ${f.signature.notes ? `<p style="margin-top:6px;font-size:9pt;color:#64748b;">${escHtml(f.signature.notes)}</p>` : ''}
        </div>`;
    p4 += `${pageFooter(4)}</div>`;

    pagesEl.innerHTML = p1 + p2 + p3 + p4;
}

function _hpMetricRow(name, value, unit, refText, statusClass, sOverride, statusTextOverride) {
    const s = sOverride || ((typeof REPORT_STRINGS !== 'undefined') ? REPORT_STRINGS[window.reportForm.language] : null);
    const ND = s.noData || '—';
    if (value === null || value === undefined) {
        return `<tr><td>${name}</td><td colspan="3" style="color:#94a3b8;text-align:center;">${ND}</td></tr>`;
    }
    const labels = { pass: s.statusPass || s.pass, warn: s.statusWarn || '', fail: s.statusFail || s.fail };
    const statusText = statusTextOverride || labels[statusClass] || statusClass || ND;
    const status = statusClass
        ? `<span class="hp-badge ${statusClass}">${escHtml(statusText)}</span>`
        : `<span style="color:#64748b;">${escHtml(statusText)}</span>`;
    return `<tr><td>${name}</td><td>${value.toFixed(2)} ${unit}</td><td>${refText}</td><td>${status}</td></tr>`;
}

function _renderInlineMd(text) {
    if (!text) return '';
    return escHtml(text).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
}

// ----- 18. Refresh report (called after planning completes) -----
function refreshFinalReport() {
    if (window._reportCollapsed === undefined) window._reportCollapsed = {};
    if (!window.reportForm) window.reportForm = _newEmptyReportForm();
    // BUG FIX 2026-06-22: respect the GLOBAL UI language first.
    // Previously this detected language from the user's Chinese input
    // and overrode the global English setting, causing the report to
    // switch to Chinese after planning even when the UI was English.
    if (typeof window._i18nLang === 'string') {
        window.reportForm.language = window._i18nLang;
    } else if (window._lastUserMessage && !window.reportForm.editedFields.has('language')) {
        const detected = _detectLanguageFromText(window._lastUserMessage);
        if (detected) window.reportForm.language = detected;
    }
    if (state.metrics && (state.metrics.v100 !== undefined || state.metrics.d90 !== undefined)) {
        reportAutoFill();
    } else {
        renderReportEditor();
        _updateReportPreview();
    }
}

// ----- 19. Status bar -----
function _setReportStatus(text, kind = 'info') {
    const el = document.getElementById('reportStatusText');
    if (!el) return;
    const colors = { ok: '#16a34a', warn: '#d97706', error: '#dc2626', info: '#64748b' };
    el.textContent = text;
    el.style.color = colors[kind] || colors.info;
    setTimeout(() => { if (el.textContent === text) el.textContent = 'Ready'; }, 3000);
}
function _updateReportStatusbar() {
    const f = window.reportForm;
    const el = document.getElementById('reportStatusText');
    if (!el) return;
    const missing = [];
    if (!f.patient.name) missing.push('Name');
    if (!f.patient.gender) missing.push('Gender');
    if (!f.patient.id && !f.case.patientId) missing.push('ID');
    if (!f.study.diagnosis) missing.push('Diagnosis');
    if (missing.length === 0) {
        el.textContent = 'All required fields complete';
        el.style.color = '#16a34a';
    } else {
        el.textContent = `Missing: ${missing.join(', ')}`;
        el.style.color = '#d97706';
    }
}

// ----- 20. Export menu / functions -----
function toggleExportMenu() {
    const m = document.getElementById('exportMenu');
    if (m) m.style.display = m.style.display === 'none' ? 'block' : 'none';
}
function hideExportMenu() {
    const m = document.getElementById('exportMenu');
    if (m) m.style.display = 'none';
}

async function exportReportPDF() {
    // Auto-capture visual evidence before rendering PDF.
    try { await autoCaptureReportFigures(); } catch (e) { console.warn('autoCaptureReportFigures failed:', e); }
    // Re-render preview so captured figures appear in the pages.
    _updateReportPreview();
    // Small delay to let the preview DOM update.
    await new Promise(r => setTimeout(r, 200));
    const pages = document.querySelectorAll('#reportPages .report-page');
    if (!pages.length) return;
    const f = window.reportForm;
    const css = _printableCss();
    const pagesHtml = Array.from(pages).map(p => p.outerHTML).join('');
    const printWindow = window.open('', '_blank');
    if (!printWindow) { _setReportStatus('Popup blocked', 'warn'); return; }
    printWindow.document.write(`<!DOCTYPE html><html><head><title>${_tr('reportTitle')}</title><style>${css}</style></head><body class="report-print">${pagesHtml}</body></html>`);
    printWindow.document.close();
    setTimeout(() => { printWindow.focus(); printWindow.print(); }, 500);
    _setReportStatus('Saved PDF', 'ok');
}

function exportReportHTML() {
    const pages = document.querySelectorAll('#reportPages .report-page');
    if (!pages.length) return;
    const f = window.reportForm;
    const css = _printableCss();
    const pagesHtml = Array.from(pages).map(p => p.outerHTML).join('');
    const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${_tr('reportTitle')}</title><style>${css}</style></head><body class="report-print">${pagesHtml}</body></html>`;
    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `brachybot-report-${(f.case.patientId || 'form')}-${new Date().toISOString().slice(0, 10)}.html`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
    _setReportStatus('Saved HTML', 'ok');
}

function exportReportMarkdown() {
    const f = window.reportForm;
    const s = (typeof REPORT_STRINGS !== 'undefined') ? REPORT_STRINGS[f.language] : null;
    const lines = [];
    lines.push(`# ${s.reportTitle}`);
    lines.push('');
    lines.push(`**${s.hospitalName} · ${s.hospitalDept}**`);
    lines.push('');
    lines.push(`## ${s.patientInfo}`);
    lines.push(`- **${s.name}**: ${f.patient.name || '—'}  |  **${s.gender}**: ${f.patient.gender || '—'}  |  **${s.age}**: ${f.patient.age || '—'}`);
    lines.push(`- **${s.id}**: ${f.patient.id || f.case.patientId || '—'}`);
    lines.push(`- **${s.diagnosis}**: ${f.study.diagnosis || '—'}`);
    lines.push('');
    lines.push(`## ${s.section2}`);
    if (f.metrics.v100 !== null) {
        const assessment = _sourceBackedMetricAssessment(f, 'v100', f.metrics.v100);
        lines.push(`| V100 | ${f.metrics.v100.toFixed(1)} % | ${assessment.reference} | ${assessment.statusText} |`);
    }
    if (f.metrics.d90 !== null) {
        const assessment = _sourceBackedMetricAssessment(f, 'd90', f.metrics.d90);
        lines.push(`| D90 | ${f.metrics.d90.toFixed(2)} Gy | ${assessment.reference} | ${assessment.statusText} |`);
    }
    if (f.metrics.score !== null) lines.push(`| Plan score | ${f.metrics.score.toFixed(0)}/100 | Internal QA ranking | Not clinical approval |`);
    if (f.interpretation) { lines.push(''); lines.push(`## ${s.section5}`); lines.push(f.interpretation); }
    if (f.references && f.references.length > 0) {
        lines.push(''); lines.push(`## ${s.section7}`);
        f.references.forEach((r, i) => { lines.push(`${i+1}. ${r.title}${r.publisher ? '. *' + r.publisher + '*' : ''}${r.year ? ', ' + r.year : ''}.${r.url ? ' <' + r.url + '>' : ''}`); });
    }
    if (f.figures && f.figures.length > 0) {
        lines.push(''); lines.push(`## Figures`);
        f.figures.forEach(fig => { lines.push(`![${fig.title}](${fig.dataUrl})`); if (fig.caption) lines.push(`*${fig.caption}*`); });
    }
    lines.push(''); lines.push('---');
    lines.push(`**${s.physicianPlanner}**: ${f.case.plannerName || '—'} | ${f.case.planDate || '—'}`);
    lines.push(`**${s.physicianReviewer}**: ${f.signature.name || '—'} | ${f.signature.title || '—'} | ${f.signature.date || '—'}`);
    const md = lines.join('\n');
    const blob = new Blob([md], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `brachybot-report-${(f.case.patientId || 'form')}-${new Date().toISOString().slice(0, 10)}.md`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
    _setReportStatus('Saved MD', 'ok');
}

function _printableCss() {
    return `
        /* Print settings — formal hospital standards:
           - A4 double-sided (back-to-back, save paper)
           - Mirror left/right margins on odd vs even pages (typical book layout)
           - Times New Roman for digits/Latin, SimSun for CJK
           - 12pt (小四号), 1.5x line-height
           - All black, no grey tints
        */
        @page {
            size: A4;
            margin: 0;
        }
        @page :left {
            margin-left: 22mm;
            margin-right: 18mm;
        }
        @page :right {
            margin-left: 18mm;
            margin-right: 22mm;
        }
        html, body { margin: 0; padding: 0; background: #fff; color: #000; }
        body.report-print { background: #fff; padding: 0; color: #000; }
        .report-page {
            width: 210mm; min-height: 297mm; padding: 18mm 16mm 18mm 16mm;
            background: #fff; color: #000;
            box-sizing: border-box; page-break-after: always; break-after: page;
            position: relative;
            font-family: 'Times New Roman', 'SimSun', 'Liberation Serif', serif;
            font-size: 12pt; line-height: 1.5;
            font-feature-settings: "tnum" 1, "lnum" 1;
        }
        .report-page:last-child { page-break-after: auto; }
        /* BUG FIX 2026-06-17 (print letterhead): match the screen
           design — small unified logos on the left, 2-line
           right-aligned credit block on the right. */
        .hp-letterhead { display: flex; align-items: center; gap: 6mm; padding-bottom: 3mm; margin-bottom: 5mm; border-bottom: 2px solid #0c4a6e; }
        .hp-logo-group { display: flex; align-items: center; gap: 2mm; flex-shrink: 0; }
        .hp-logo-img { width: 10mm; height: 10mm; object-fit: contain; background: #fff; border-radius: 3px; border: 1px solid #e2e8f0; }
        .hp-logo { width: 10mm; height: 10mm; display: flex; align-items: center; justify-content: center; border-radius: 50%; overflow: hidden; }
        .hp-letterhead-text { margin-left: auto; text-align: right; font-size: 7pt; color: #94a3b8; font-family: 'Helvetica Neue', 'Arial', 'Microsoft YaHei', sans-serif; line-height: 1.4; flex-shrink: 0; max-width: 70%; }
        .hp-letterhead-byline { font-weight: 600; color: #64748b; margin-bottom: 0.4mm; font-size: 7pt; }
        .hp-letterhead-github { font-weight: 400; color: #94a3b8; font-size: 6.5pt; }
        .hp-letterhead-github a { color: #0369a1; text-decoration: none; border-bottom: 1px dotted #0369a1; font-family: 'SFMono-Regular', 'Consolas', 'Monaco', monospace; font-size: 8.5pt; }
        .hp-letterhead-credit { font-weight: 600; color: #0c4a6e; }
        .hp-letterhead-credit a { color: #0369a1; text-decoration: none; border-bottom: 1px dotted #0369a1; }
        .hp-letterhead-name { font-size: 13pt; font-weight: 700; color: #0c4a6e; }
        .hp-letterhead-en { font-size: 9pt; color: #64748b; font-style: italic; }
        .hp-letterhead-dept { font-size: 9pt; color: #475569; margin-top: 2mm; }
        .hp-letterhead-contact { font-size: 8pt; color: #64748b; text-align: right; line-height: 1.5; }
        .hp-title { text-align: center; font-size: 18pt; font-weight: 700; color: #0c4a6e; margin: 6mm 0 4mm 0; letter-spacing: 2px; }
        .hp-subtitle { text-align: center; font-size: 9pt; color: #64748b; margin-bottom: 6mm; font-style: italic; }
        .hp-section { margin: 6mm 0 3mm 0; page-break-inside: avoid; }
        .hp-section-title { font-size: 12pt; font-weight: 700; color: #fff; background: #0c4a6e; padding: 2mm 4mm; margin: 0 0 3mm 0; border-left: 4px solid #f59e0b; }
        .hp-section-title-en { font-size: 8pt; color: #f59e0b; font-style: italic; font-weight: 400; margin-left: 4mm; }
        .hp-section-body { font-size: 10pt; line-height: 1.7; }
        .hp-section-body p { margin: 1.5mm 0; text-indent: 2em; }
        .hp-section-body p.no-indent { text-indent: 0; }
        .hp-id-table, .hp-table, .hp-grid-table { width: 100%; border-collapse: collapse; margin: 2mm 0 3mm 0; font-size: 9.5pt; }
        .hp-id-table th, .hp-id-table td { border: 1px solid #94a3b8; padding: 2mm 3mm; text-align: left; }
        .hp-id-table th { background: #f1f5f9; font-weight: 600; width: 22%; }
        .hp-table thead tr { border-top: 2px solid #000; border-bottom: 1px solid #000; }
        .hp-table tbody tr:last-child { border-bottom: 2px solid #000; }
        .hp-table th, .hp-table td { padding: 1.5mm 2.5mm; text-align: left; vertical-align: top; border: none; }
        .hp-table th { font-weight: 700; background: #fff; }
        .hp-grid-table th, .hp-grid-table td { border: 1px solid #cbd5e1; padding: 1.2mm 2mm; text-align: left; }
        .hp-grid-table th { background: #e0f2fe; color: #0c4a6e; font-weight: 600; }
        .hp-grid-table tr:nth-child(even) td { background: #f8fafc; }
        .hp-key { color: #0c4a6e; font-weight: 600; }
        .hp-badge.pass { background: #dcfce7; color: #166534; padding: 0.5mm 2mm; border-radius: 1mm; font-size: 8.5pt; }
        .hp-badge.warn { background: #fef3c7; color: #92400e; padding: 0.5mm 2mm; border-radius: 1mm; font-size: 8.5pt; }
        .hp-badge.fail { background: #fee2e2; color: #991b1b; padding: 0.5mm 2mm; border-radius: 1mm; font-size: 8.5pt; }
        .hp-disclaimer { background: #fef9e7; border: 1px solid #f59e0b; border-left: 5px solid #f59e0b; padding: 3mm 4mm; margin: 4mm 0; font-size: 9pt; color: #78350f; }
        .hp-figure { margin: 4mm 0; text-align: center; page-break-inside: avoid; }
        .hp-figure img { max-width: 100%; max-height: 110mm; border: 1px solid #cbd5e1; }
        .hp-figure-cap { font-size: 8.5pt; color: #475569; margin-top: 1.5mm; font-style: italic; }
        .hp-references { font-size: 9pt; line-height: 1.55; padding-left: 6mm; }
        .hp-references li { margin-bottom: 1.5mm; text-indent: -5mm; padding-left: 5mm; }
        .hp-references a { color: #0c4a6e; text-decoration: none; }
        .hp-references .ref-num { font-weight: 700; color: #0c4a6e; margin-right: 2mm; }
        .hp-signature { margin-top: 8mm; page-break-inside: avoid; display: grid; grid-template-columns: 1fr 1fr; gap: 4mm; font-size: 9.5pt; }
        .hp-signature-block { border: 1px solid #cbd5e1; padding: 3mm 4mm; background: #f8fafc; min-height: 24mm; position: relative; }
        .hp-signature-label { font-size: 7.5pt; color: #64748b; text-transform: uppercase; }
        .hp-signature-name { font-size: 11pt; font-weight: 700; color: #0c4a6e; }
        .hp-signature-title { font-size: 8.5pt; color: #475569; margin-top: 0.5mm; }
        .hp-signature-date { font-size: 8.5pt; color: #475569; margin-top: 1mm; border-top: 1px solid #cbd5e1; padding-top: 1mm; }
        .hp-signature-image { display: block; max-width: 36mm; max-height: 12mm; margin-top: 2mm; object-fit: contain; object-position: left center; }
        .hp-signature-stamp { position: absolute; right: 4mm; bottom: 4mm; width: 18mm; height: 18mm; border: 2px solid #0ea5e9; border-radius: 50%; color: #0ea5e9; font-size: 7pt; font-weight: 700; display: flex; align-items: center; justify-content: center; text-align: center; line-height: 1.1; transform: rotate(-8deg); opacity: 0.65; pointer-events: none; }
        .hp-running-header { display: flex; justify-content: space-between; align-items: center; font-size: 7.5pt; color: #94a3b8; border-bottom: 1px solid #e2e8f0; padding-bottom: 1.5mm; margin-bottom: 4mm; }
        .hp-page-footer { position: absolute; bottom: 8mm; left: 16mm; right: 16mm; display: flex; justify-content: space-between; align-items: center; font-size: 7.5pt; color: #94a3b8; border-top: 1px solid #e2e8f0; padding-top: 2mm; }
        .hp-page-footer .pageno { font-weight: 600; color: #475569; }
    `;
}

// ----- 21. Chat language detection hook -----
function processReportCommand(userMessage) {
    if (!userMessage) return false;
    const f = window.reportForm;
    let consumed = false;
    const detected = _detectLanguageFromText(userMessage);
    if (detected && !f.editedFields.has('language')) f.language = detected;
    const m = userMessage.match(/^\/report\s+(zh|zh-CN|chinese|中文|en|english)\b/i);
    if (m) {
        f.language = /^zh|chinese|中文/i.test(m[1]) ? 'zh' : 'en';
        f.editedFields.add('language');
        _setReportStatus('Language set to ' + (f.language === 'zh' ? '中文' : 'English'), 'ok');
        if (typeof renderReportEditor === 'function') renderReportEditor();
        if (typeof _updateReportPreview === 'function') _updateReportPreview();
        consumed = true;
    }
    return consumed;
}

const _origSendChat = window.sendChat;
if (_origSendChat && !window._reportLangHooked) {
    window._reportLangHooked = true;
    window.sendChat = function(...args) {
        if (args[0] && window.processReportCommand) {
            const msg = typeof args[0] === 'string' ? args[0] : (args[0].value || args[0].message || '');
            window._lastUserMessage = msg;
            processReportCommand(msg);
        }
        return _origSendChat.apply(this, args);
    };
}

// ----- 22. Boot -----
function initReportPanel() {
    // Start empty until the active chat session is known. Workspace restore
    // then loads that session's scoped report, preventing cross-patient data
    // from appearing while preserving report edits across refreshes.
    if (!window.reportForm) window.reportForm = _newEmptyReportForm();
    if (!window.reportForm.editedFields) window.reportForm.editedFields = new Set();
    // BUG FIX 2026-06-17: sync report language with global UI language
    // on boot. Previously defaulted to 'zh' unconditionally, causing
    // Chinese report preview when the global toggle was English.
    if (!window.reportForm.language || window.reportForm.language !== window._i18nLang) {
        window.reportForm.language = window._i18nLang || 'en';
    }
    renderReportEditor();
    _updateReportPreview();
    if (window._lastUserMessage) {
        const detected = _detectLanguageFromText(window._lastUserMessage);
        if (detected && !window.reportForm.editedFields.has('language')) {
            window.reportForm.language = detected;
            _updateLanguageButtons();
            _updateReportPreview();
        }
    }
}
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initReportPanel);
} else {
    setTimeout(initReportPanel, 100);
}

// =============================================================================
// BOOT — kick off the main init() that wires splitters, layout, and status.
// init() was defined at line 7134 but its boot invocation was lost during
// the 24aa6ad "12-issue fix batch" commit. Without this call none of the
// drag-resize splitters bind their pointerdown handlers, which is why
// the 3 main column handles (sidebar / chat / right-panel) have been
// dead for multiple fix rounds. Real-browser Playwright trace confirmed
// the handler closure never ran — init() was never invoked.
// =============================================================================
uiDebugLog('[BOOT] BrachyBot starting…');
try {
    if (typeof init === 'function') {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => init().catch(e => console.error('[BOOT] init() rejected:', e)));
        } else {
            // Fire after a tick so the report module (which also boots
            // at the end of this script) can finish its own setup first.
            setTimeout(() => init().catch(e => console.error('[BOOT] init() rejected:', e)), 0);
        }
    } else {
        console.error('[BOOT] init() not declared');
    }

    // I18N BOOT (2026-06-16): run the initial language pass over the
    // DOM so the header (Connected/Online/Session) and the toggle
    // button show the correct language from the very first paint.
    // Then set the toggle's "active" state and register a re-render
    // hook so dynamic renderers (Analysis panel, Report form, todo
    // dock) can refresh on language change.
    if (typeof applyI18n === 'function') {
        applyI18n();
        // Mark the active language on the toggle button(s).
        const _activeLang = window._i18nLang || 'en';
        document.querySelectorAll('[data-lang-btn]').forEach(b => {
            const isActive = b.getAttribute('data-lang-btn') === _activeLang;
            b.classList.toggle('lang-active', isActive);
            b.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        });
        // When language changes, re-render the Analysis panel and the
        // todo dock. The Report module has its own language flow
        // (window.Report.i18n.set) which already handles itself.
        window.addEventListener('i18nchange', (ev) => {
            try { if (typeof updateImageAnalysis === 'function') updateImageAnalysis(); } catch (_) {}
            // The todo dock keeps a separate _TODO_I18N dict with its
            // own `setActiveTodoLang(code)` switch. Sync the dock
            // language to the new global one. The dock's own re-render
            // is driven by the SSE step event that arrives AFTER a
            // language change, so we don't need to repaint here — the
            // active label will pick up the new strings on its next
            // update.
            try {
                if (typeof _setActiveTodoLang === 'function' && ev && ev.detail && ev.detail.lang) {
                    _setActiveTodoLang(ev.detail.lang);
                }
            } catch (_) {}
            // Re-render the visible report language button highlight.
            try { if (typeof Report !== 'undefined' && Report.i18n && Report.i18n.set) {
                Report.i18n.set(ev.detail.lang, { userInitiated: false });
            }} catch (_) {}
        });
    }
} catch (e) {
    console.error('[BOOT] boot wiring failed:', e);
}

// =============================================================================
// CURSOR LEAK GUARD — global safety net. The 3 splitter setups set
// `document.body.style.cursor = 'col-resize'` on pointerdown and reset
// it to '' on pointerup. If a drag is interrupted (browser context
// loss, system dialog, JS error inside the handler, etc.) the body
// cursor can stay stuck on 'col-resize', making the user feel like
// "the cursor is the resize arrow everywhere". This document-level
// pointerup listener is the last line of defense: ANY pointerup on
// the page, anywhere, will clear the body cursor. Costs ~no-op on
// normal drags (each handler's own pointerup fires first; this one
// just sets '' to '' which is a no-op), but rescues stuck cursors.
// =============================================================================
document.addEventListener('pointerup', () => {
    if (document.body.style.cursor === 'col-resize' ||
        document.body.style.cursor === 'row-resize') {
        document.body.style.cursor = '';
    }
    if (document.body.classList.contains('v-dragging')) {
        document.body.classList.remove('v-dragging');
    }
}, true);
document.addEventListener('pointercancel', () => {
    document.body.style.cursor = '';
    document.body.classList.remove('v-dragging');
}, true);
