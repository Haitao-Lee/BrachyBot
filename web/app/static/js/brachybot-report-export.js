function _oarVolumePercent(value, units) {
    const n = Number(value);
    if (!Number.isFinite(n)) return null;
    const kind = String(units || '').toLowerCase();
    if (['fraction', 'ratio', '0-1'].includes(kind)) {
        return n >= 0 && n <= 1 ? n * 100 : null;
    }
    if (['percent', 'percentage', '0-100'].includes(kind)) {
        return n >= 0 && n <= 100 ? n : null;
    }
    return n >= 0 && n <= 1 ? n * 100 : (n >= 0 && n <= 100 ? n : null);
}

function _composite2DViewerCanvas(axis, options = {}) {
    const sliceCanvas = document.getElementById('sliceCanvas' + axis.charAt(0).toUpperCase() + axis.slice(1));
    if (!sliceCanvas || sliceCanvas.width < 1 || sliceCanvas.height < 1) return null;
    const cap = axis.charAt(0).toUpperCase() + axis.slice(1);
    const sourceWidth = Number(sliceCanvas.width);
    const sourceHeight = Number(sliceCanvas.height);
    const outputScale = Math.max(1, 1400 / Math.max(sourceWidth, sourceHeight));
    const out = document.createElement('canvas');
    out.width = Math.max(1, Math.round(sourceWidth * outputScale));
    out.height = Math.max(1, Math.round(sourceHeight * outputScale));
    const ctx = out.getContext('2d');
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, out.width, out.height);

    // Capture only the canonical medical-image stack. The viewer container
    // also owns a narrow dose-colorbar canvas. Querying every descendant
    // canvas and stretching it to the CT extent turned that 16 x 512 gradient
    // into a full-frame rainbow image in exported reports.
    const layerIds = [
        `sliceCanvas${cap}`,
        `labelOverlay_${cap}`,
        `doseOverlayCanvas${cap}`,
        `contourCanvas${cap}`,
        `seedsOverlayCanvas${cap}`,
        `crosshairCanvas${cap}`,
        `annotationCanvas${cap}`,
    ];
    layerIds.forEach(id => {
        const layer = document.getElementById(id);
        if (!layer || layer.width < 1 || layer.height < 1) return;
        const style = window.getComputedStyle ? window.getComputedStyle(layer) : layer.style;
        const liveOpacity = Number.parseFloat(style?.opacity ?? '1');
        const captureDoseOpacity = id === `doseOverlayCanvas${cap}`
            ? Number(options.doseOpacity)
            : NaN;
        // Publication captures can make dose easier to inspect without
        // mutating the operator's live Data Tree/Viewer opacity.
        const opacity = Number.isFinite(captureDoseOpacity)
            ? Math.max(0, Math.min(1, captureDoseOpacity))
            : liveOpacity;
        if (style?.display === 'none' || style?.visibility === 'hidden' || opacity <= 0) return;
        try {
            ctx.save();
            ctx.globalAlpha = Number.isFinite(opacity) ? Math.max(0, Math.min(1, opacity)) : 1;
            ctx.drawImage(layer, 0, 0, out.width, out.height);
            ctx.restore();
        } catch (error) {
            console.warn(`[Report] Unable to composite ${id}:`, error);
        }
    });

    // Recreate the compact color scale from its numeric configuration instead
    // of raster-stretching the DOM colorbar. Text and tick marks therefore
    // remain legible in a full-width PDF subfigure.
    const colorbar = document.getElementById(`doseColorbar${cap}`);
    const colorbarStyle = colorbar && window.getComputedStyle
        ? window.getComputedStyle(colorbar) : colorbar?.style;
    if (colorbar && colorbarStyle?.display !== 'none' && colorbarStyle?.visibility !== 'hidden'
        && typeof _drawDoseColorbarGradient === 'function'
        && typeof _doseColorbarLabelSpecs === 'function') {
        const pad = Math.max(12, Math.round(out.width * 0.012));
        const panelWidth = Math.max(90, Math.round(out.width * 0.105));
        const panelHeight = Math.max(180, Math.round(out.height * 0.82));
        const panelX = out.width - panelWidth - pad;
        const panelY = Math.round((out.height - panelHeight) / 2);
        const barWidth = Math.max(15, Math.round(panelWidth * 0.2));
        const barX = panelX + Math.round(panelWidth * 0.12);
        const barY = panelY + Math.round(panelHeight * 0.08);
        const barHeight = Math.round(panelHeight * 0.84);
        ctx.save();
        ctx.fillStyle = 'rgba(2,6,23,0.82)';
        ctx.fillRect(panelX, panelY, panelWidth, panelHeight);
        const gradientCanvas = document.createElement('canvas');
        gradientCanvas.width = barWidth;
        gradientCanvas.height = barHeight;
        _drawDoseColorbarGradient(gradientCanvas.getContext('2d'), barWidth, barHeight);
        ctx.drawImage(gradientCanvas, barX, barY);
        ctx.strokeStyle = 'rgba(226,232,240,0.75)';
        ctx.strokeRect(barX + 0.5, barY + 0.5, barWidth - 1, barHeight - 1);
        const fontSize = Math.max(11, Math.round(out.width * 0.011));
        _doseColorbarLabelSpecs(barHeight).forEach(spec => {
            const y = barY + (barHeight - 1) * (spec.pct / 100);
            ctx.strokeStyle = 'rgba(226,232,240,0.78)';
            ctx.beginPath();
            ctx.moveTo(barX + barWidth + 3, y);
            ctx.lineTo(barX + barWidth + 10, y);
            ctx.stroke();
            ctx.fillStyle = '#f8fafc';
            ctx.font = `${spec.major ? 'bold ' : ''}${fontSize}px Inter, Arial, sans-serif`;
            ctx.textAlign = 'left';
            ctx.fillText(spec.label, barX + barWidth + 13, y + fontSize * 0.34);
        });
        ctx.restore();
    }
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
function _activeReportSessionId() {
    if (typeof activeSessionId !== 'undefined' && activeSessionId) return String(activeSessionId);
    return String(window.state?.sessionId || '');
}

async function reportAutoFill(options = {}) {
    const expectedSessionId = String(options.sessionId || _activeReportSessionId());
    const isCurrentCase = () => !expectedSessionId || expectedSessionId === _activeReportSessionId();
    if (!isCurrentCase()) return { stale: true };
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
                v100: _oarVolumePercent(x.v100, state.metrics.volume_metric_units),
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
        if (!isCurrentCase()) return { stale: true };
        applyReportTemplate(f.templateKey);
        return { stale: false };
    }
    if (!isCurrentCase()) return { stale: true };
    // Rebuild from the metrics/source fingerprint. A forced rebuild here can
    // erase durable Reference/Status cells while planning context hydrates.
    syncReportQualityAssessment(f, { preserveStored: true });
    _setReportStatus('Auto-filled from NIfTI + planning', 'ok');
    renderReportEditor(); _updateReportPreview(); _scheduleReportAutoSave();
    return { stale: false };
}

function _autoFillInterpretation() {
    const f = window.reportForm;
    const m = (window.state && window.state.metrics) || {};
    const v100 = m.v100 !== undefined ? m.v100 * 100 : null;
    const d90 = m.d90 || null;
    const score = m.plan_score;
    const oarMetrics = m.oar_metrics || {};
    const zh = f.language === 'zh';
    const lines = [];

    lines.push(zh ? '**剂量学评估与临床解读**' : '**Planning metric interpretation**');
    lines.push('');
    lines.push(zh
        ? '本节仅报告观测到的计划指标。临床通过/不通过结论必须引用适用的部位特异性指南，或使用已确认的病例方案限值。'
        : 'This section summarizes observed planning metrics only. Clinical pass/fail decisions must use source-backed thresholds from applicable site-specific guidance or the confirmed case protocol.');
    lines.push('');

    if (v100 !== null) {
        lines.push(zh
            ? `- CTV V100：${v100.toFixed(1)}%。请结合适用指南或已确认的病例方案核对靶区覆盖要求。`
            : `- CTV V100: ${v100.toFixed(1)}%. Compare it with the applicable target-coverage criteria.`);
    }
    if (d90 !== null) {
        const rxGy = typeof _getCurrentPrescriptionGy === 'function'
            ? _getCurrentPrescriptionGy()
            : 120;
        lines.push(zh
            ? `- CTV D90：${d90.toFixed(2)} Gy；当前报告处方剂量为 ${rxGy.toFixed(0)} Gy。阈值应依据引用来源判读。`
            : `- CTV D90: ${d90.toFixed(2)} Gy; current report prescription is ${rxGy.toFixed(0)} Gy. Interpret the threshold from the cited source.`);
    }
    if (score !== undefined) {
        lines.push(zh
            ? `- 计划评分：${Number(score).toFixed(0)}/100。该分数仅用于排序和质量复核，不代表临床批准。`
            : `- Plan score: ${Number(score).toFixed(0)}/100. This score is for ranking and QA triage, not clinical approval.`);
    }
    lines.push('');

    const sortedOars = Object.entries(oarMetrics)
        .filter(([_, x]) => x && (x.d2cc || x.dmax || x.max_dose))
        .sort((a, b) => ((b[1].d2cc || b[1].dmax || b[1].max_dose || 0) - (a[1].d2cc || a[1].dmax || a[1].max_dose || 0)))
        .slice(0, 5);
    if (sortedOars.length > 0) {
        lines.push(zh ? '**危及器官剂量摘要**（按可用指标最高者列出）：' : '**Organ-at-risk dose summary** (highest available OAR metrics):');
        for (const [rawName, om] of sortedOars) {
            const name = _resolveOARDisplayName(rawName, om);
            const d2cc = om.d2cc || 0;
            const dmax = om.dmax || om.max_dose || 0;
            lines.push(zh
                ? `- **${name}**：D2cc = ${d2cc.toFixed(2)} Gy，Dmax = ${dmax.toFixed(2)} Gy；请结合部位特异性 OAR 限值判读。`
                : `- **${name}**: D2cc = ${d2cc.toFixed(2)} Gy, Dmax = ${dmax.toFixed(2)} Gy; interpret with site-specific OAR limits.`);
        }
        lines.push('');
    }

    lines.push(zh ? '**建议的下一步**：' : '**Recommended next steps**:');
    lines.push(zh
        ? '- 依据适用的部位特异性指南复核处方剂量、V100/D90/V150/V200 指标和 OAR 限值，并在报告参考文献中保留真实链接。'
        : '- Verify prescription dose, V100/D90/V150/V200 criteria, and OAR limits against applicable site-specific guidance; include real links in report references.');
    lines.push(zh
        ? '- 放射肿瘤科医师和医学物理师应结合来源支持的阈值、图像配准、针道可行性和独立剂量复核共同审核。'
        : '- Radiation oncologist and physicist review should combine sourced thresholds, image registration, trajectory feasibility, and independent dose verification.');
    lines.push('');
    lines.push(zh
        ? '_本段由 BrachyBot 自动生成，不替代已签署的临床治疗计划。_'
        : '_This is an auto-generated metric summary from BrachyBot; it does not replace a signed clinical treatment plan._');

    f.interpretation = lines.join('\n');
    f.safety = zh
        ? '**安全与质量控制**\n\n- 复核粒子活度和源强。\n- 治疗前后使用独立方法进行剂量复核。\n- OAR 限值和靶区覆盖阈值必须来自适用的部位特异性指南或已确认的病例方案，不使用本地报告默认值。\n- 知情同意和最终签署应遵循所在机构流程。'
        : '**Safety & Quality Control**\n\n- Seed activity and source strength require physicist verification.\n- Pre/post-treatment dose verification should use an independent method.\n- OAR limits and target coverage thresholds must come from applicable site-specific guidance or confirmed case-protocol settings, not local report defaults.\n- Informed consent and final sign-off follow institutional workflow.';
}

// ----- 13. Reset -----
async function reportReset() {
    const confirmed = typeof window._confirmAction === 'function'
        ? await window._confirmAction('重置所有报告字段？', 'Reset all report fields?')
        : false;
    if (!confirmed) return false;
    window.reportForm = _newEmptyReportForm();
    renderReportEditor(); _updateReportPreview(); _scheduleReportAutoSave();
    return true;
}

// ----- 14. Durable workspace auto-save -----
let _reportAutoSaveTimer = null;
function _scheduleReportAutoSave() {
    if (_reportAutoSaveTimer) clearTimeout(_reportAutoSaveTimer);
    _reportAutoSaveTimer = setTimeout(_reportAutoSave, 800);
    const t = document.getElementById('reportAutoSaveText');
    if (t) t.textContent = 'Auto-save: pending…';
}
function _reportAutoSave(options = {}) {
    try {
        const f = window.reportForm;
        const ownerSessionId = String(
            options.sessionId
            || (typeof activeSessionId !== 'undefined' ? activeSessionId : '')
            || '',
        );
        // Quality rows are durable report content. Materialize the same
        // Reference/Status values shown in Preview before the workspace
        // serializer clones the form, including during a fast Session switch.
        syncReportQualityAssessment(f, { preserveStored: true });
        if (ownerSessionId) f.sessionId = ownerSessionId;
        f.updatedAt = Date.now();
        f.editedFields = Array.from(f.editedFields || []);
        f.editedFields = new Set(f.editedFields);
        const t = document.getElementById('reportAutoSaveText');
        if (t) t.textContent = 'Auto-save: ' + new Date().toLocaleTimeString();
        // An explicit old-session flush runs after the new shell has painted.
        // Its direct persist call below is case-bound, so do not schedule a
        // normal active-session timer that could serialize the old report into
        // the newly selected Session.
        if (options.schedule !== false && typeof scheduleWorkspaceSave === 'function') {
            scheduleWorkspaceSave('report.changed');
        }
    } catch (e) {}
}

function flushActiveReportState(options = {}) {
    const ownerSessionId = String(
        options.sessionId
        || (typeof activeSessionId !== 'undefined' ? activeSessionId : '')
        || '',
    );
    if (_reportAutoSaveTimer) {
        clearTimeout(_reportAutoSaveTimer);
        _reportAutoSaveTimer = null;
    }
    if (window.reportForm) _reportAutoSave({ sessionId: ownerSessionId, schedule: false });
    // _reportAutoSave schedules the durable workspace write. During a case
    // transition the caller performs the old-case write immediately; cancel
    // the delayed timer before activeSessionId changes.
    if (typeof window.cancelScheduledWorkspaceSave === 'function') {
        window.cancelScheduledWorkspaceSave();
    }
    const writes = [];
    if (ownerSessionId && typeof window.persistWorkspace === 'function') {
        // This is an explicit old-session flush. It must be allowed while the
        // background hydration flag is still set. `sessionId` pins both the
        // payload and request header to the old case after the visible shell
        // has already switched to the next one.
        writes.push(Promise.resolve(window.persistWorkspace('report.flush', {
            allowDuringRestore: true,
            sessionId: ownerSessionId,
        })));
    }
    const activeId = String((typeof activeSessionId !== 'undefined' ? activeSessionId : '') || '');
    if (ownerSessionId === activeId && window.Report && Report.persist && typeof Report.persist.flush === 'function') {
        try { writes.push(Promise.resolve(Report.persist.flush())); } catch (_) {}
    }
    return Promise.allSettled(writes);
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
        // Persist the rendered quality columns with the report. Rebuilding
        // these cells from in-memory rationale loses them after restore.
        qualityAssessment: { version: 2, language: language, generatedAt: 0, inputFingerprint: '', metrics: {} },
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

// ----- 15. Save / Load JSON -----
async function _persistGeneratedReportArtifact(blob, filename) {
    if (!window.brachybotAuth?.user) return null;
    const ownerSessionId = String(
        (typeof activeSessionId !== 'undefined' && activeSessionId)
            || window.state?.sessionId
            || '',
    );
    try {
        const form = new FormData();
        form.append('category', 'reports');
        form.append('file', new File([blob], filename, { type: blob.type || 'application/octet-stream' }));
        const response = await fetch('/api/workspace/artifacts', {
            method: 'POST',
            headers: ownerSessionId ? { 'X-BrachyBot-Session': ownerSessionId } : {},
            body: form,
        });
        const data = await response.json().catch(() => null);
        if (!response.ok) throw new Error(data?.error || `HTTP ${response.status}`);
        return data;
    } catch (error) {
        // Downloads still succeed locally if a transient workspace upload
        // fails; the durable form state remains checkpointed separately.
        console.warn('[report] workspace artifact save failed:', error);
        return null;
    }
}

function reportSaveJSON() {
    const f = window.reportForm;
    f.editedFields = Array.from(f.editedFields);
    const blob = new Blob([JSON.stringify(f, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const filename = `brachybot-report-${(f.case.patientId || 'form')}-${new Date().toISOString().slice(0, 10)}.json`;
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
    void _persistGeneratedReportArtifact(blob, filename);
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
function _storedMetricAssessment(form, metricKey) {
    const stored = form?.qualityAssessment?.metrics?.[metricKey];
    if (!stored || typeof stored !== 'object') return null;
    if (!Object.prototype.hasOwnProperty.call(stored, 'reference')
        && !Object.prototype.hasOwnProperty.call(stored, 'statusText')) return null;
    return {
        reference: stored.reference == null ? '—' : String(stored.reference),
        statusClass: stored.statusClass || null,
        statusText: stored.statusText == null ? 'Not assessed' : String(stored.statusText),
    };
}

const _REPORT_QUALITY_METRICS = ['v100', 'd90', 'd95', 'v150', 'v200', 'ci', 'hi', 'gi', 'score'];

function _stableReportQualityValue(value) {
    if (value === null || value === undefined) return null;
    if (Array.isArray(value)) return value.map(_stableReportQualityValue);
    if (typeof value !== 'object') return value;
    const result = {};
    Object.keys(value).sort().forEach(key => {
        const normalized = _stableReportQualityValue(value[key]);
        if (normalized !== undefined) result[key] = normalized;
    });
    return result;
}

function _normalizedReportMetricValue(value) {
    if (value === null || value === undefined || value === '') return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
}

function _reportQualityInputFingerprint(form) {
    const metrics = {};
    _REPORT_QUALITY_METRICS.forEach(key => {
        metrics[key] = _normalizedReportMetricValue(form?.metrics?.[key]);
    });
    const planning = form?.planning || {};
    return JSON.stringify(_stableReportQualityValue({
        language: form?.language || 'en',
        metrics,
        prescriptionGy: _normalizedReportMetricValue(planning.prescriptionGy),
        prescriptionRationale: planning.prescriptionRationale || null,
    }));
}

function _hasStoredMetricAssessment(row) {
    if (!row || typeof row !== 'object') return false;
    const reference = row.reference == null ? '' : String(row.reference).trim();
    const statusText = row.statusText == null ? '' : String(row.statusText).trim();
    return reference.length > 0 || statusText.length > 0;
}

function _hasStoredQualityAssessment(assessment) {
    const rows = assessment?.metrics;
    return !!rows && typeof rows === 'object'
        && _REPORT_QUALITY_METRICS.some(key => _hasStoredMetricAssessment(rows[key]));
}

function _qualityAssessmentMatchesMetrics(assessment, form) {
    if (!assessment || typeof assessment !== 'object') return false;
    return _REPORT_QUALITY_METRICS.every(key => {
        const row = assessment.metrics?.[key];
        if (!row || typeof row !== 'object') return false;
        const expected = _normalizedReportMetricValue(form?.metrics?.[key]);
        const actual = _normalizedReportMetricValue(row.value);
        return expected === null ? actual === null : actual === expected;
    });
}

function _reportHasSourceContext(form) {
    const rationale = form?.planning?.prescriptionRationale;
    if (!rationale || typeof rationale !== 'object') return false;
    return (Array.isArray(rationale.sources) && rationale.sources.length > 0)
        || (Array.isArray(rationale.source_records) && rationale.source_records.length > 0)
        || (rationale.target_criteria && typeof rationale.target_criteria === 'object'
            && Object.keys(rationale.target_criteria).length > 0);
}

/**
 * Return true when a restored report needs the server's source-backed patch.
 * Numeric Planning metrics alone are insufficient: an older or partially
 * checkpointed form can have correct V100/D90 values while its Reference and
 * Status cells are generic hydration placeholders. This predicate lets the
 * restart path repair only those incomplete forms and leave an authoritative
 * planning-specific report untouched.
 */
function reportNeedsSourceBackedQualityRefresh(form) {
    if (!form || typeof form !== 'object') return true;
    if (!_reportHasSourceContext(form)) return true;
    const assessment = form.qualityAssessment;
    if (!_qualityAssessmentMatchesMetrics(assessment, form)) return true;
    if (assessment?.inputFingerprint !== _reportQualityInputFingerprint(form)) return true;
    return ['v100', 'd90', 'v150', 'v200'].some(key => {
        const row = assessment?.metrics?.[key] || {};
        const reference = String(row.reference || '').trim().toLowerCase();
        return reference === 'see cited case criteria';
    });
}
window.reportNeedsSourceBackedQualityRefresh = reportNeedsSourceBackedQualityRefresh;

function _sourceBackedMetricAssessment(form, metricKey, value, options = {}) {
    if (!options.ignoreStored) {
        const stored = _storedMetricAssessment(form, metricKey);
        const rawStored = form?.qualityAssessment?.metrics?.[metricKey];
        if (stored && _hasStoredMetricAssessment(rawStored)) return stored;
    }
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
    const sourceUrls = (Array.isArray(rationale.sources) ? rationale.sources : [])
        .map(src => typeof src === 'string' ? src : src?.url).filter(Boolean);
    const notAssessed = form?.language === 'zh' ? '未评估' : 'Not assessed';
    if (!sourceUrls.length || !allCriteria || typeof allCriteria !== 'object') {
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

function _defaultMetricAssessment(form, metricKey, value) {
    if (['v100', 'd90', 'v150', 'v200'].includes(metricKey)) {
        return _sourceBackedMetricAssessment(form, metricKey, value, { ignoreStored: true });
    }
    if (metricKey === 'score') {
        return {
            reference: form?.language === 'zh' ? '内部质量排序' : 'Internal QA ranking',
            statusClass: null,
            statusText: form?.language === 'zh' ? '非临床批准' : 'Not clinical approval',
        };
    }
    return {
        reference: '—',
        statusClass: null,
        statusText: form?.language === 'zh' ? '未评估' : 'Not assessed',
    };
}

function syncReportQualityAssessment(form, options = {}) {
    if (!form || typeof form !== 'object') return null;
    const language = form.language || 'en';
    const metricKeys = _REPORT_QUALITY_METRICS;
    const values = form.metrics || {};
    const previous = form.qualityAssessment;
    const inputFingerprint = _reportQualityInputFingerprint(form);
    const metricsMatch = _qualityAssessmentMatchesMetrics(previous, form);
    const hasStoredRows = _hasStoredQualityAssessment(previous);
    const hasSourceContext = _reportHasSourceContext(form);
    const fingerprintMatches = previous?.inputFingerprint === inputFingerprint;
    const unchanged = previous
        && (previous.version === 1 || previous.version === 2)
        && previous.language === language
        && previous.inputFingerprint === inputFingerprint
        && metricsMatch
        && (!options.force || hasSourceContext);
    if (unchanged) return previous;

    // A persisted assessment is part of the report, not a disposable render
    // cache. During restart hydration the planning rationale can arrive after
    // the report form, which used to rebuild these rows and erase the saved
    // Reference/Status cells. Keep durable rows while their metric values
    // still match. An explicit criteria refresh may replace them.
    if (options.preserveStored !== false
        && options.refreshCriteria !== true
        && hasStoredRows
        && metricsMatch
        && previous.language === language) return previous;

    const metrics = {};
    metricKeys.forEach(key => {
        const raw = values[key];
        const value = raw == null || raw === '' || !Number.isFinite(Number(raw)) ? null : Number(raw);
        const previousRow = previous?.metrics?.[key];
        const preservePreviousRow = options.preserveStored !== false
            && options.refreshCriteria !== true
            && previous?.language === language
            && _hasStoredMetricAssessment(previousRow)
            && _normalizedReportMetricValue(previousRow.value) === value;
        metrics[key] = preservePreviousRow
            ? { ...previousRow, value }
            : { value, ..._defaultMetricAssessment(form, key, value) };
    });
    form.qualityAssessment = {
        version: 2,
        language,
        generatedAt: Date.now(),
        inputFingerprint,
        metrics,
    };
    return form.qualityAssessment;
}
window.syncReportQualityAssessment = syncReportQualityAssessment;

const _REPORT_FIGURE_AXIS_GROUPS = Object.freeze({
    figure1: new Set([
        'report_fig1_global', 'report_fig1_closeup',
        // Legacy axes remain readable until a fresh capture replaces them.
        '3d_seeds', '3d_ctv', 'seed_plan_composite',
    ]),
    figure2: new Set([
        'report_fig2_axial', 'report_fig2_sagittal', 'report_fig2_coronal',
        'report_fig2_dose_surface', 'report_fig2_dvh',
        'dose_axial', 'dose_sagittal', 'dose_coronal', 'dvh',
        'dose_dvh_composite',
    ]),
});

function _reportFigureGroup(figure) {
    const explicit = String(figure?.figureGroup || '').toLowerCase();
    if (explicit === 'figure1' || explicit === 'figure2') return explicit;
    const axis = String(figure?.axis || '').toLowerCase();
    for (const [group, axes] of Object.entries(_REPORT_FIGURE_AXIS_GROUPS)) {
        if (axes.has(axis)) return group;
    }
    return '';
}

function _reportFigureStableIdentity(figure, index = 0) {
    const axis = String(figure?.axis || '').trim();
    if (/^report_fig[12]_/i.test(axis)) return `axis:${axis}`;
    const role = String(figure?.captureRole || figure?.capture_role || '').trim();
    if (role) return `role:${role}`;
    return `legacy:${axis || figure?.id || figure?._serverUrl || figure?.dataUrl || index}`;
}

function _reportFigureDisplayText(figure) {
    const described = typeof window.describeReportFigure === 'function'
        ? window.describeReportFigure(figure?.axis)
        : null;
    return {
        title: String(figure?.title || described?.title || ''),
        caption: String(figure?.caption || described?.caption || ''),
    };
}

function _reportFigureAspectRatio(figure) {
    const storedRatio = Number(figure?.aspectRatio);
    if (Number.isFinite(storedRatio) && storedRatio > 0) return storedRatio;
    const width = Number(figure?.pixelWidth);
    const height = Number(figure?.pixelHeight);
    if (Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0) {
        return width / height;
    }
    const dataUrl = String(figure?.dataUrl || '');
    if (dataUrl.startsWith('data:image/png;base64,')) {
        try {
            // Restored legacy captures may predate persisted dimensions. Read
            // the PNG IHDR so page orientation still follows the real image.
            const comma = dataUrl.indexOf(',');
            const header = atob(dataUrl.slice(comma + 1, comma + 65));
            const uint32 = offset => (
                (header.charCodeAt(offset) << 24)
                | (header.charCodeAt(offset + 1) << 16)
                | (header.charCodeAt(offset + 2) << 8)
                | header.charCodeAt(offset + 3)
            ) >>> 0;
            const pngWidth = uint32(16);
            const pngHeight = uint32(20);
            if (pngWidth > 0 && pngHeight > 0) return pngWidth / pngHeight;
        } catch (_) {}
    }
    return null;
}

function _reportFigurePageOrientation(figure) {
    const explicit = String(figure?.pageOrientation || '').toLowerCase();
    if (explicit === 'landscape' || explicit === 'portrait') return explicit;
    const ratio = _reportFigureAspectRatio(figure);
    if (Number.isFinite(ratio)) return ratio >= 1.2 ? 'landscape' : 'portrait';
    // Server-backed captures from older Sessions may have no inline PNG header.
    // Use semantic capture roles only as a compatibility fallback.
    const role = String(figure?.captureRole || figure?.capture_role || '').toLowerCase();
    if (['planning_overview', 'planning_closeup', 'dose_surface_3d', 'dvh'].includes(role)) {
        return 'landscape';
    }
    return 'portrait';
}

function _reportFiguresForGroup(form, group) {
    const rows = (Array.isArray(form?.figures) ? form.figures : [])
        .filter(figure => figure && _reportFigureGroup(figure) === group);
    // A legacy composite is useful for old Sessions only. As soon as native
    // subfigures exist, never display the downsampled composite beside them.
    const nativePrefix = group === 'figure1' ? 'report_fig1_' : 'report_fig2_';
    const nativeRows = rows.filter(figure => String(figure.axis || '').startsWith(nativePrefix));
    const sorted = (nativeRows.length ? nativeRows : rows).sort((left, right) => {
        const leftOrder = Number(left?.sortOrder);
        const rightOrder = Number(right?.sortOrder);
        if (Number.isFinite(leftOrder) || Number.isFinite(rightOrder)) {
            return (Number.isFinite(leftOrder) ? leftOrder : 999)
                - (Number.isFinite(rightOrder) ? rightOrder : 999);
        }
        return String(left?.subfigure || left?.axis || '').localeCompare(
            String(right?.subfigure || right?.axis || ''),
        );
    });
    // Defend PDF export against snapshots created before report figures had a
    // durable role. The workspace restore path also normalizes them, but the
    // export boundary must never render two copies as the same Figure 1(a).
    const seen = new Set();
    return sorted.filter((figure, index) => {
        const identity = _reportFigureStableIdentity(figure, index);
        if (seen.has(identity)) return false;
        seen.add(identity);
        return true;
    });
}

function _updateReportPreview() {
    const pagesEl = document.getElementById('reportPages');
    if (!pagesEl) return;
    if (!window.reportForm) window.reportForm = _newEmptyReportForm();
    const f = window.reportForm;
    syncReportQualityAssessment(f, { preserveStored: true });
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
    const figure1Rows = _reportFiguresForGroup(f, 'figure1');
    const figure2Rows = _reportFiguresForGroup(f, 'figure2');
    const supplementalRows = (Array.isArray(f.figures) ? f.figures : []).filter(
        figure => figure && !_reportFigureGroup(figure),
    );
    // Each evidence image gets an independent A4 page. Report captures are
    // native, full-resolution views; putting multiple images in one page made
    // PDF previews crop or scale them into unreadable miniatures.
    const figure1PageCount = figure1Rows.length;
    const figure2PageCount = figure2Rows.length;
    const supplementalPageCount = supplementalRows.length;
    const reportTotalPages = 5 + figure1PageCount + figure2PageCount + supplementalPageCount;
    const pageFooter = (pageNo) =>
        `<div class="hp-page-footer"><span class="pageno">— ${escHtml(s.page)} ${pageNo} ${escHtml(s.pageOf)} ${reportTotalPages} —</span></div>`;
    // A report has one language at a time. English secondary headings used to
    // be appended to every Chinese heading, which made the exported report
    // look partially translated even after the global language switch.
    const secondaryTitle = () => '';
    const renderFigurePages = (rows, figureNumber, groupTitle, startPageNo) => {
        if (!rows.length) return '';
        let html = '';
        for (let offset = 0; offset < rows.length; offset += 1) {
            const pageRows = rows.slice(offset, offset + 1);
            const pageNo = startPageNo + offset;
            const headingFigure = pageRows[0] || {};
            const headingSubfigure = String(
                headingFigure.subfigure || String.fromCharCode(97 + offset)
            ).toLowerCase();
            const orientation = _reportFigurePageOrientation(headingFigure);
            html += `<div class="report-page report-figure-page report-page--${orientation}" data-page-orientation="${orientation}">
                <div class="hp-running-header"><span>${escHtml(s.confidentiality)}</span><span class="right">${escHtml(groupTitle)}</span></div>
                <h2 class="hp-section-title">${escHtml(s.figCaption)} ${figureNumber}(${escHtml(headingSubfigure)}) - ${escHtml(groupTitle)}</h2>
                <div class="hp-subfigure-list">${pageRows.map((figure, pageIndex) => {
                    const imageUrl = _safeReportImageUrl(figure.dataUrl);
                    if (!imageUrl) return '';
                    const fallbackIndex = offset + pageIndex;
                    const subfigure = String(figure.subfigure || String.fromCharCode(97 + fallbackIndex)).toLowerCase();
                    const display = _reportFigureDisplayText(figure);
                    return `<figure class="hp-subfigure">
                        <img src="${escHtml(imageUrl)}" alt="${escHtml(display.title)}"/>
                        <figcaption><b>${escHtml(s.figCaption)} ${figureNumber}(${escHtml(subfigure)}) - ${escHtml(display.title)}</b>${display.caption ? ': ' + escHtml(display.caption) : ''}</figcaption>
                    </figure>`;
                }).join('')}</div>
                ${pageFooter(pageNo)}
            </div>`;
        }
        return html;
    };

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
    const bylineLine1 = f.language === 'zh' ? 'BrachyBot 智能近距离放疗规划' : 'Powered by BrachyBot';
    const bylineLine2 = f.language === 'zh' ? '上海交通大学医学院附属瑞金医院联合开发' : 'Developed by SJTU && Ruijin Hospital';
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
    p1 += `${pageFooter(1)}</div>`;

    let nextPageNo = 2;
    const figure1Pages = renderFigurePages(
        figure1Rows,
        1,
        f.language === 'zh' ? '粒子植入方案' : 'Seed Implant Plan',
        nextPageNo,
    );
    nextPageNo += figure1PageCount;

    // ============== PAGE 2: Plan Quality Assessment ==============
    const t = (key) => escHtml(s[key]);
    const unitGy = (v) => v !== null ? `${v} ${U.Gy}` : ND;
    const unitMm3 = (v) => v !== null ? `${v.toFixed(1)} ${U.mm3}` : ND;
    const unitMBq = (v) => v !== null ? `${v} ${U.MBq}` : ND;
    const seedsUnit = s.seedsUnitWord ? ' ' + s.seedsUnitWord : '';
    const trajUnit = s.trajUnitWord ? ' ' + s.trajUnitWord : '';
    const aV100 = _sourceBackedMetricAssessment(f, 'v100', f.metrics.v100);
    const aD90 = _sourceBackedMetricAssessment(f, 'd90', f.metrics.d90);
    const aD95 = _storedMetricAssessment(f, 'd95') || _defaultMetricAssessment(f, 'd95', f.metrics.d95);
    const aV150 = _sourceBackedMetricAssessment(f, 'v150', f.metrics.v150);
    const aV200 = _sourceBackedMetricAssessment(f, 'v200', f.metrics.v200);
    const aCI = _storedMetricAssessment(f, 'ci') || _defaultMetricAssessment(f, 'ci', f.metrics.ci);
    const aHI = _storedMetricAssessment(f, 'hi') || _defaultMetricAssessment(f, 'hi', f.metrics.hi);
    const aGI = _storedMetricAssessment(f, 'gi') || _defaultMetricAssessment(f, 'gi', f.metrics.gi);
    const aScore = _storedMetricAssessment(f, 'score') || _defaultMetricAssessment(f, 'score', f.metrics.score);
    const notAssessed = f.language === 'zh' ? '未评估' : 'Not assessed';
    const targetSection = s.sectionTargetPrescription || s.section4;
    const qualitySection = s.sectionPlanQuality || s.section2;
    const oarSection = s.sectionOarDose || s.section3;
    const interpretationSection = s.sectionClinicalInterpretation || s.section5;
    let p2 = `<div class="report-page">
        <div class="hp-running-header"><span>${escHtml(s.confidentiality)}</span><span class="right">${escHtml(targetSection)} · ${escHtml(qualitySection)}</span></div>
        <h2 class="hp-section-title">${escHtml(targetSection)}${secondaryTitle('Target & Prescription')}</h2>
        <div class="hp-section-body">
            <p class="no-indent"><span class="hp-key">${t('technique')}：</span>${_renderInlineMd(f.planning.technique) || ND}</p>
            <p class="no-indent"><span class="hp-key">${t('prescriptionDose')}：</span>${f.planning.prescriptionGy !== null ? f.planning.prescriptionGy + ' ' + U.Gy : ND}；
                <span class="hp-key">${t('totalSeeds')}：</span>${f.planning.totalSeeds !== null ? f.planning.totalSeeds + seedsUnit : ND}；
                <span class="hp-key">${t('totalActivity')}：</span>${unitMBq(f.planning.totalActivityMBq)}；
                <span class="hp-key">${t('trajectories')}：</span>${f.planning.trajectoryCount !== null ? f.planning.trajectoryCount + trajUnit : ND}</p>
        </div>
        <h2 class="hp-section-title">${escHtml(qualitySection)}${secondaryTitle('Plan Quality Assessment')}</h2>
        <div class="hp-section-body">
            <table class="hp-table">
                <thead><tr><th style="width:25%">${t('metric')}</th><th style="width:18%">${t('value')}</th><th>${t('reference')}</th><th>${t('status')}</th></tr></thead>
                <tbody>
                    ${_hpMetricRow('V100 (CTV)', f.metrics.v100, U.percent, aV100.reference, aV100.statusClass, s, aV100.statusText)}
                    ${_hpMetricRow('D90', f.metrics.d90, U.Gy, aD90.reference, aD90.statusClass, s, aD90.statusText)}
                    ${_hpMetricRow('D95', f.metrics.d95, U.Gy, aD95.reference, aD95.statusClass, s, aD95.statusText)}
                    ${_hpMetricRow('V150', f.metrics.v150, U.percent, aV150.reference, aV150.statusClass, s, aV150.statusText)}
                    ${_hpMetricRow('V200', f.metrics.v200, U.percent, aV200.reference, aV200.statusClass, s, aV200.statusText)}
                    ${_hpMetricRow('CI', f.metrics.ci, '', aCI.reference, aCI.statusClass, s, aCI.statusText)}
                    ${_hpMetricRow('HI', f.metrics.hi, '', aHI.reference, aHI.statusClass, s, aHI.statusText)}
                    ${_hpMetricRow('GI', f.metrics.gi, '', aGI.reference, aGI.statusClass, s, aGI.statusText)}
                    ${_hpMetricRow(s.planScoreLabel || 'Plan score', f.metrics.score, '/100', aScore.reference, aScore.statusClass, s, aScore.statusText)}
                </tbody>
            </table>
        </div>
    `;
    p2 += `${pageFooter(nextPageNo)}</div>`;
    nextPageNo += 1;

    const figure2Pages = renderFigurePages(
        figure2Rows,
        2,
        f.language === 'zh' ? '剂量分布与 DVH' : 'Dose Distribution & DVH',
        nextPageNo,
    );
    nextPageNo += figure2PageCount;

    const supplementalPages = renderFigurePages(
        supplementalRows,
        3,
        f.language === 'zh' ? '附加图像' : 'Additional Figures',
        nextPageNo,
    );
    nextPageNo += supplementalPageCount;

    // ============== PAGE 3: OAR Dose ==============
    let p3 = `<div class="report-page">
        <div class="hp-running-header"><span>${escHtml(s.confidentiality)}</span><span class="right">${escHtml(oarSection)}</span></div>`;
    if (f.oarDose && f.oarDose.length > 0) {
        p3 += `<h2 class="hp-section-title">${escHtml(oarSection)}${secondaryTitle('OAR Dose')}</h2>
        <div class="hp-section-body">
            <p class="no-indent">${escHtml(f.language === 'zh'
                ? '以下 OAR 数值为观测结果；请依据当前部位适用指南或已确认的病例方案进行临床判读，软件不依据默认值自动给出通过或超限结论。'
                : 'The OAR values below are observed metrics. Interpret them against applicable site-specific guidance or a confirmed case protocol; the software does not infer pass/fail from defaults.')}</p>
            <table class="hp-grid-table">
                <thead><tr><th>${escHtml(s.organ)}</th><th>${d2ccLabel} (${U.Gy})</th><th>${d1ccLabel} (${U.Gy})</th><th>${d01ccLabel} (${U.Gy})</th><th>${v100Label} (${U.percent})</th></tr></thead>
                <tbody>
                ${f.oarDose.map(o => {
                    const organName = _resolveOARDisplayName(o.organ, o);
                    const oarV100 = _oarVolumePercent(o.v100, 'percent');
                    return `<tr>
                        <td>${escHtml(organName)}</td>
                        <td>${o.d2cc !== null ? o.d2cc.toFixed(1) : ND}</td>
                        <td>${o.d1cc !== null ? o.d1cc.toFixed(1) : ND}</td>
                        <td>${o.d0_1cc !== null ? o.d0_1cc.toFixed(1) : ND}</td>
                        <td>${oarV100 !== null ? oarV100.toFixed(1) : ND}</td>
                    </tr>`;
                }).join('')}
                </tbody>
            </table>
        </div>`;
    } else {
        const noOarDose = f.language === 'zh'
            ? '当前病例尚无可用的危及器官剂量结果。完成剂量计算后，此处将自动显示器官剂量指标与来源支持的限值评估。'
            : 'No organ-at-risk dose results are available for this case. After dose calculation, this section will show organ dose metrics and source-backed limit assessments.';
        p3 += `<h2 class="hp-section-title">${escHtml(oarSection)}${secondaryTitle('OAR Dose')}</h2>
        <div class="hp-section-body"><p class="no-indent">${escHtml(noOarDose)}</p></div>`;
    }
    p3 += `${pageFooter(nextPageNo)}</div>`;
    nextPageNo += 1;

    // ============== PAGE 4: Clinical Interpretation ==============
    let p4 = `<div class="report-page">
        <div class="hp-running-header"><span>${escHtml(s.confidentiality)}</span><span class="right">${escHtml(interpretationSection)}</span></div>`;
    if (f.interpretation) {
        p4 += `<h2 class="hp-section-title">${escHtml(interpretationSection)}${secondaryTitle('Clinical Interpretation')}</h2>
        <div class="hp-section-body">${_renderMarkdown(f.interpretation)}</div>`;
    } else {
        p4 += `<h2 class="hp-section-title">${escHtml(interpretationSection)}${secondaryTitle('Clinical Interpretation')}</h2>
        <div class="hp-section-body"><p class="no-indent">${escHtml(ND)}</p></div>`;
    }
    p4 += `${pageFooter(nextPageNo)}</div>`;
    nextPageNo += 1;

    // ============== PAGE 5: Safety + QA + Methodology + References + Disclaimer + Signatures ==============
    let p5 = `<div class="report-page">
        <div class="hp-running-header"><span>${escHtml(s.confidentiality)}</span><span class="right">${escHtml(s.section6)} · ${s.section7}</span></div>`;
    if (f.safety) {
        p5 += `<h2 class="hp-section-title">${escHtml(s.section6)}${secondaryTitle('Safety & QC')}</h2>
        <div class="hp-section-body">${_renderMarkdown(f.safety)}</div>`;
    }
    if (f.qaNotes) {
        p5 += `<h2 class="hp-section-title">${escHtml(s.qaNotes)}${secondaryTitle('QA Notes')}</h2>
        <div class="hp-section-body">${_renderMarkdown(f.qaNotes)}</div>`;
    }
    // Method (small reference block)
    p5 += `<h2 class="hp-section-title">${escHtml(s.method)}${secondaryTitle('Methodology')}</h2>
        <div class="hp-section-body"><ol style="margin:2px 0 2px 18px;padding:0;font-size:9pt;">${s.methodSteps.map(st => `<li style="margin:1.5px 0;">${st}</li>`).join('')}</ol></div>`;
    // References
    if (f.references && f.references.length > 0) {
        p5 += `<h2 class="hp-section-title">${escHtml(s.section7)}${secondaryTitle('References')}</h2>
        <div class="hp-section-body"><ol class="hp-references">${f.references.map((r, i) => {
            const key = r.citeKey || `ref${i+1}`;
            const safeUrl = _safeReportUrl(r.url);
            return `<li><span class="ref-num">[${i+1}]</span> ${escHtml(r.title || '')}${r.publisher ? ' <i>(' + escHtml(r.publisher) + ')</i>' : ''}${r.year ? ', ' + r.year : ''}.${safeUrl ? ' <a href="' + escHtml(safeUrl) + '" target="_blank" rel="noopener noreferrer">↗</a>' : ''}</li>`;
        }).join('')}</ol></div>`;
    }
    // Disclaimer
    p5 += `<div class="hp-disclaimer"><b>⚠️ ${escHtml(s.disclaimer)}:</b><br/>${escHtml(s.disclaimerText)}</div>`;
    // BrachyBot generates the document but never signs as a clinician. The
    // planning and review fields stay independent and require human identity.
    const safeSignatureUrl = _safeReportImageUrl(f.signature.drawnDataUrl);
    const reviewerSignature = safeSignatureUrl
        ? `<img class="hp-signature-image" src="${escHtml(safeSignatureUrl)}" alt="Reviewer signature"/>`
        : '';
    p5 += `<h2 class="hp-section-title">${escHtml(s.section9)}${secondaryTitle('Physician Signatures')}</h2>
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
    p5 += `${pageFooter(nextPageNo)}</div>`;

    pagesEl.innerHTML = p1 + figure1Pages + p2 + figure2Pages + supplementalPages + p3 + p4 + p5;
    // Mixed portrait/landscape A4 pages can change the widest preview page.
    // Recalculate fit after the DOM commit instead of retaining the old scale.
    window.requestAnimationFrame(() => window.Report?.preview?.refresh?.());
}

function _hpMetricRow(name, value, unit, refText, statusClass, sOverride, statusTextOverride) {
    const s = sOverride || ((typeof REPORT_STRINGS !== 'undefined') ? REPORT_STRINGS[window.reportForm.language] : null);
    const ND = s.noData || '—';
    let metricKey = {
        'V100 (CTV)': 'v100', D90: 'd90', D95: 'd95', V150: 'v150', V200: 'v200',
        CI: 'ci', HI: 'hi', GI: 'gi', 'Plan score': 'score',
    }[name];
    if (!metricKey && (/score|评分/i.test(String(name)) || unit === '/100')) metricKey = 'score';
    const stored = metricKey ? _storedMetricAssessment(window.reportForm, metricKey) : null;
    if (stored) {
        refText = stored.reference;
        statusClass = stored.statusClass;
        statusTextOverride = stored.statusText;
    }
    // Never emit empty cells when a legacy snapshot contains a blank field.
    // The durable assessment or the source-backed fallback supplies the
    // visible value instead.
    if (refText === null || refText === undefined || String(refText).trim() === '') refText = ND;
    if (statusTextOverride === null || statusTextOverride === undefined
        || String(statusTextOverride).trim() === '') statusTextOverride = 'Not assessed';
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
    const filename = `brachybot-report-${(f.case.patientId || 'form')}-${new Date().toISOString().slice(0, 10)}.html`;
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
    void _persistGeneratedReportArtifact(blob, filename);
    _setReportStatus('Saved HTML', 'ok');
}

function exportReportMarkdown() {
    const f = window.reportForm;
    syncReportQualityAssessment(f, { preserveStored: true });
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
    const targetSection = s.sectionTargetPrescription || s.section4;
    const qualitySection = s.sectionPlanQuality || s.section2;
    lines.push(`## ${targetSection}`);
    lines.push(`- **${s.technique}**: ${f.planning.technique || '—'}`);
    lines.push(`- **${s.prescriptionDose}**: ${f.planning.prescriptionGy !== null ? `${f.planning.prescriptionGy} Gy` : '—'}`);
    lines.push(`- **${s.totalSeeds}**: ${f.planning.totalSeeds !== null ? f.planning.totalSeeds : '—'}`);
    lines.push(`- **${s.trajectories}**: ${f.planning.trajectoryCount !== null ? f.planning.trajectoryCount : '—'}`);
    lines.push('');
    lines.push(`## ${qualitySection}`);
    if (f.metrics.v100 !== null) {
        const assessment = _sourceBackedMetricAssessment(f, 'v100', f.metrics.v100);
        lines.push(`| V100 | ${f.metrics.v100.toFixed(1)} % | ${assessment.reference} | ${assessment.statusText} |`);
    }
    if (f.metrics.d90 !== null) {
        const assessment = _sourceBackedMetricAssessment(f, 'd90', f.metrics.d90);
        lines.push(`| D90 | ${f.metrics.d90.toFixed(2)} Gy | ${assessment.reference} | ${assessment.statusText} |`);
    }
    if (f.metrics.score !== null) {
        const assessment = _storedMetricAssessment(f, 'score') || _defaultMetricAssessment(f, 'score', f.metrics.score);
        lines.push(`| Plan score | ${f.metrics.score.toFixed(0)}/100 | ${assessment.reference} | ${assessment.statusText} |`);
    }
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
    const filename = `brachybot-report-${(f.case.patientId || 'form')}-${new Date().toISOString().slice(0, 10)}.md`;
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
    void _persistGeneratedReportArtifact(blob, filename);
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
        @page reportPortrait {
            size: A4 portrait;
            margin: 0;
        }
        @page reportLandscape {
            size: A4 landscape;
            margin: 0;
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
            page: reportPortrait;
        }
        .report-figure-page { height: 297mm; max-height: 297mm; }
        .report-page--landscape {
            width: 297mm; min-height: 210mm; height: 210mm; max-height: 210mm;
            padding: 14mm 16mm 14mm 16mm; page: reportLandscape;
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
        /* One native report capture per evidence page. The page box, figure
           box, and image share the same width constraint so browser preview
           scaling cannot let a wide canvas escape or crop the PDF page. */
        .report-figure-page { display: flex; flex-direction: column; max-width: none; min-width: 0; overflow: hidden; box-sizing: border-box; }
        .hp-subfigure-list { display: flex; flex-direction: column; justify-content: center; flex: 1 1 auto; width: 100%; min-width: 0; min-height: 0; max-width: 100%; overflow: hidden; }
        .hp-subfigure { display: flex; flex-direction: column; justify-content: center; flex: 1 1 auto; width: 100%; max-width: 100%; min-width: 0; margin: 0; text-align: center; page-break-inside: avoid; break-inside: avoid; min-height: 0; overflow: hidden; box-sizing: border-box; }
        .hp-subfigure img { display: block; width: auto; max-width: 100%; min-width: 0; height: auto; max-height: 176mm; object-fit: contain; margin: 0 auto; border: 1px solid #cbd5e1; background: #020617; box-sizing: border-box; }
        .report-page--landscape .hp-subfigure img { max-height: 132mm; }
        .hp-subfigure figcaption { font-size: 9pt; line-height: 1.35; color: #334155; margin-top: 1.5mm; font-style: italic; }
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
let _brachyBotApplicationStarted = false;
window.startBrachyBotApplication = async function startBrachyBotApplication() {
    if (_brachyBotApplicationStarted) return;
    if (window.brachybotAuth && !(await window.brachybotAuth.authenticated())) return;
    _brachyBotApplicationStarted = true;
    try { await init(); } catch (error) { console.error('[BOOT] init() rejected:', error); }
};
try {
    if (typeof init === 'function') {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => window.startBrachyBotApplication());
        } else {
            // Fire after a tick so the report module (which also boots
            // at the end of this script) can finish its own setup first.
            setTimeout(() => window.startBrachyBotApplication(), 0);
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
        // Also paint the auth overlay (which sits above the SPA and is
        // visible before the main boot completes). The auth module
        // registers its own i18nchange listener so subsequent switches
        // also re-render.
        try { if (typeof window.brachybotAuth !== 'undefined' && window.brachybotAuth && typeof window.brachybotAuth.renderAuthI18n === 'function') {
            window.brachybotAuth.renderAuthI18n();
            window.brachybotAuth.setAuthLangToggleState();
        }} catch (_) {}
        // Mark the active language on the toggle button(s).
        const _activeLang = window._i18nLang || 'en';
        document.querySelectorAll('[data-lang-btn]').forEach(b => {
            const isActive = b.getAttribute('data-lang-btn') === _activeLang;
            b.classList.toggle('lang-active', isActive);
            b.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        });
        // <html lang> must follow the active language so screen readers
        // and the browser spell-checker pick the correct locale. Set on
        // boot and on every language change.
        const _syncHtmlLang = () => {
            try {
                document.documentElement.setAttribute('lang', _activeLang === 'zh' ? 'zh-CN' : 'en');
            } catch (_) {}
        };
        _syncHtmlLang();
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
            _syncHtmlLang();
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
