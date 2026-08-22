function escHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function _safeReportUrl(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    try {
        const url = new URL(raw, window.location.origin);
        return (url.protocol === 'http:' || url.protocol === 'https:') ? url.href : '';
    } catch (_) {
        return '';
    }
}
function _safeReportImageUrl(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    if (/^data:image\/(png|jpe?g|webp);base64,[a-z0-9+/=\r\n]+$/i.test(raw)) return raw;
    try {
        const url = new URL(raw, window.location.origin);
        if ((url.protocol === 'http:' || url.protocol === 'https:') && url.origin === window.location.origin) {
            return url.href;
        }
    } catch (_) {}
    return '';
}
function _formField(opts) {
    const id = 'rf-' + opts.key.replace(/[^a-zA-Z0-9_]/g, '_');
    const edited = window.reportForm.editedFields && window.reportForm.editedFields.has(opts.key);
    // Source badge (auto/user/bot) from window.Report.sources
    let srcBadge = '';
    let srcReset = '';
    try {
        if (window.Report && window.Report.sources) {
            const src = window.Report.sources.get(opts.key);
            const labels = { auto: 'AUTO', user: 'YOU', bot: 'BOT' };
            const label = labels[src] || 'AUTO';
            const title = src === 'user' ? 'Edited by you' : src === 'bot' ? 'Filled by brachybot' : 'Auto-extracted';
            srcBadge = `<span class="rp-source-badge ${src}" data-source-key="${opts.key.replace(/[^a-zA-Z0-9_]/g, '_')}" title="${title}">${label}</span>`;
            const resetArg = JSON.stringify(String(opts.key || ''))
                .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
            srcReset = `<span class="rp-source-reset" title="Reset to auto" onclick="Report.sources.resetTo(${resetArg})">↻</span>`;
        }
    } catch (e) {}
    const reqBadge = opts.required ? `<span style="color:var(--danger);font-size:0.7rem;margin-left:2px;" title="required">*</span>` : '';
    const hint = opts.hint ? `<div class="rp-field-hint">${opts.hint}</div>` : '';
    const suffixHtml = opts.suffix ? `<span class="rp-field-suffix">${opts.suffix}</span>` : '';
    let inputHtml;
    if (opts.type === 'textarea' || opts.multiline) {
        inputHtml = `<textarea id="${id}" data-key="${opts.key}" class="form-input" rows="${opts.rows || 3}" placeholder="${opts.placeholder || ''}" oninput="onReportFieldEdit('${opts.key}')">${escHtml(String(opts.value || ''))}</textarea>`;
    } else {
        const tval = opts.value !== null && opts.value !== undefined ? String(opts.value) : '';
        inputHtml = `<input id="${id}" data-key="${opts.key}" class="form-input" type="${opts.type || 'text'}" placeholder="${opts.placeholder || ''}" value="${escHtml(tval)}" step="${opts.step || 'any'}" ${opts.min !== undefined ? `min="${opts.min}"` : ''} ${opts.max !== undefined ? `max="${opts.max}"` : ''} oninput="onReportFieldEdit('${opts.key}')"/>`;
    }
    return `<div class="form-group" style="margin-bottom:8px;">
        <label class="rp-field-label" for="${id}">${opts.label}${reqBadge}${srcBadge}${srcReset}</label>
        <div style="display:flex;align-items:center;gap:0;">${inputHtml}${suffixHtml}</div>
        ${hint}
    </div>`;
}

function _formSection(title, key, body, opts = {}) {
    const isCollapsed = (window._reportCollapsed || {})[key] === true;
    const arrow = isCollapsed ? '▶' : '▼';
    return `<div class="rp-form-section" data-section="${key}">
        <div class="rp-form-section-header" onclick="toggleReportSection('${key}')">
            <span class="rp-form-section-arrow">${arrow}</span>
            <span class="rp-form-section-title">${title}</span>
        </div>
        <div class="rp-form-section-body" style="${isCollapsed ? 'display:none;' : ''}">
            ${body}
        </div>
    </div>`;
}

function toggleReportSection(key) {
    window._reportCollapsed = window._reportCollapsed || {};
    window._reportCollapsed[key] = !window._reportCollapsed[key];
    renderReportEditor();
}

// ----- 7. Render the form editor -----
function renderReportEditor() {
    const host = document.getElementById('reportFormHost');
    if (!host) return;
    if (!window.reportForm) window.reportForm = _newEmptyReportForm();
    const f = window.reportForm;
    // Always use the GLOBAL UI language for report labels, not
    // f.language which may be stale from localStorage. The user's
    // complaint: "report still shows Chinese even though global UI is English".
    const _reportLang = (typeof window._i18nLang === 'string') ? window._i18nLang : (f.language || 'en');
    const s = (typeof REPORT_STRINGS !== 'undefined') ? REPORT_STRINGS[_reportLang] : null;
    if (!s) return;
    const editorLabels = _reportLang === 'zh' ? {
        markdown: '（Markdown）',
        qaNotes: '质保备注',
        open: '打开',
        addReference: '添加参考文献',
        selectReference: '选择目录文献',
        orAddCustom: '或手动添加',
        citeKey: '引用键',
        publisher: '出版方',
        jurisdiction: '适用范围',
        title: '标题',
        year: '年份',
        url: '链接',
        add: '添加',
        capture2d: '📷 截取 2D',
        capture3d: '📷 截取 3D',
        upload: '📁 上传',
        observedCoverage: '观测到的 CTV 覆盖率；请结合引用的病例标准判读',
        observedDose: '观测到的剂量；请结合有来源支持的处方剂量判读',
    } : {
        markdown: ' (Markdown)', qaNotes: 'QA Notes', open: 'Open',
        addReference: 'Add Reference', selectReference: 'Select catalog reference',
        orAddCustom: 'or add custom', citeKey: 'Cite key', publisher: 'Publisher',
        jurisdiction: 'Jurisdiction', title: 'Title', year: 'Year', url: 'URL',
        add: 'Add', capture2d: '📷 Capture 2D', capture3d: '📷 Capture 3D', upload: '📁 Upload',
        observedCoverage: 'Observed CTV coverage; assess against cited case criteria',
        observedDose: 'Observed dose; compare with the sourced prescription',
    };

    let html = '';
    // Hospital info
    html += _formSection('🏥 ' + s.name, 'hospital', `
        ${_formField({key:'hospital.name', label:s.name, value:f.hospital.name, section:'hospital'})}
        ${_formField({key:'hospital.dept', label:s.department, value:f.hospital.dept, section:'hospital'})}
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            ${_formField({key:'hospital.address', label:s.hospitalAddress || 'Address', value:f.hospital.address, section:'hospital'})}
            ${_formField({key:'hospital.contact', label:s.hospitalContact || 'Contact', value:f.hospital.contact, section:'hospital'})}
        </div>
    `);
    // Patient info
    html += _formSection('👤 ' + s.patientInfo, 'patient', `
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;">
            ${_formField({key:'patient.name', label:s.name, value:f.patient.name, section:'patient'})}
            ${_formField({key:'patient.gender', label:s.gender, value:f.patient.gender, section:'patient'})}
            ${_formField({key:'patient.age', label:s.age, value:f.patient.age, type:'number', section:'patient'})}
        </div>
        <div style="display:grid;grid-template-columns:2fr 1fr 1fr;gap:8px;">
            ${_formField({key:'patient.id', label:s.id, value:f.patient.id, section:'patient'})}
            ${_formField({key:'patient.ward', label:s.ward, value:f.patient.ward, section:'patient'})}
            ${_formField({key:'patient.bed', label:s.bed, value:f.patient.bed, section:'patient'})}
        </div>
        ${_formField({key:'patient.department', label:s.department, value:f.patient.department, section:'patient'})}
    `);
    // Study info
    html += _formSection('🩻 ' + (s.imagingSectionTitle || (_reportLang === 'zh' ? '影像学资料' : 'Imaging Data')), 'study', `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            ${_formField({key:'study.modality', label:s.modality, value:f.study.modality, section:'study'})}
            ${_formField({key:'study.scanDate', label:s.scanDate, value:f.study.scanDate, type:'date', section:'study'})}
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;">
            ${_formField({key:'study.accession', label:s.accession, value:f.study.accession, section:'study'})}
            ${_formField({key:'study.radiologist', label:s.radiologist, value:f.study.radiologist, section:'study'})}
            ${_formField({key:'imaging.scanner', label:s.scanner, value:f.imaging.scanner, section:'study'})}
        </div>
        ${_formField({key:'study.diagnosis', label:s.diagnosis, value:f.study.diagnosis, type:'textarea', rows:2, section:'study'})}
        ${_formField({key:'study.clinicalHistory', label:s.clinicalHistory, value:f.study.clinicalHistory, type:'textarea', rows:2, section:'study'})}
        ${_formField({key:'study.priorTreatment', label:s.priorTreatment, value:f.study.priorTreatment, type:'textarea', rows:2, section:'study'})}
    `);
    // Case summary
    html += _formSection('📋 ' + (s.caseSectionTitle || (_reportLang === 'zh' ? '病例摘要' : 'Patient Summary')), 'case', `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            ${_formField({key:'case.patientId', label:s.id, value:f.case.patientId, section:'case'})}
            ${_formField({key:'case.tumorType', label:s.tumorType, value:f.case.tumorType, section:'case'})}
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            ${_formField({key:'case.planDate', label:s.planDate, value:f.case.planDate, type:'date', section:'case'})}
            ${_formField({key:'case.plannerName', label:s.planner, value:f.case.plannerName, section:'case'})}
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            ${_formField({key:'case.ctvVolumeMm3', label:s.ctvVolume, value:f.case.ctvVolumeMm3, type:'number', step:'0.1', suffix:'mm³', section:'case'})}
            ${_formField({key:'case.oarCount', label:s.oarCount, value:f.case.oarCount, type:'number', step:'1', section:'case'})}
        </div>
    `);
    // Planning
    html += _formSection('🎯 ' + (s.planSectionTitle || (_reportLang === 'zh' ? '治疗计划' : 'Treatment Plan')), 'planning', `
        ${_formField({key:'planning.technique', label:s.technique, value:f.planning.technique, type:'textarea', rows:2, section:'planning'})}
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            ${_formField({key:'planning.prescriptionGy', label:s.prescription, value:f.planning.prescriptionGy, type:'number', step:'0.1', suffix:'Gy', section:'planning'})}
            ${_formField({key:'planning.totalSeeds', label:s.totalSeeds, value:f.planning.totalSeeds, type:'number', step:'1', section:'planning'})}
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            ${_formField({key:'planning.totalActivityMBq', label:s.totalActivity, value:f.planning.totalActivityMBq, type:'number', step:'0.1', suffix:'MBq', section:'planning'})}
            ${_formField({key:'planning.trajectoryCount', label:s.trajectories, value:f.planning.trajectoryCount, type:'number', step:'1', section:'planning'})}
        </div>
        ${_formField({key:'planning.dwellPositionCount', label:s.dwellPositions, value:f.planning.dwellPositionCount, type:'number', step:'1', section:'planning'})}
    `);
    // Metrics
    html += _formSection('📊 ' + s.section2, 'metrics', `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            ${_formField({key:'metrics.v100', label:'V100', value:f.metrics.v100, type:'number', step:'0.01', suffix:'%', hint:editorLabels.observedCoverage})}
            ${_formField({key:'metrics.d90', label:'D90', value:f.metrics.d90, type:'number', step:'0.01', suffix:'Gy', hint:editorLabels.observedDose})}
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            ${_formField({key:'metrics.d95', label:'D95', value:f.metrics.d95, type:'number', step:'0.01', suffix:'Gy'})}
            ${_formField({key:'metrics.v150', label:'V150', value:f.metrics.v150, type:'number', step:'0.01', suffix:'%'})}
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            ${_formField({key:'metrics.v200', label:'V200', value:f.metrics.v200, type:'number', step:'0.01', suffix:'%'})}
            ${_formField({key:'metrics.ci', label:'CI', value:f.metrics.ci, type:'number', step:'0.001'})}
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            ${_formField({key:'metrics.hi', label:'HI', value:f.metrics.hi, type:'number', step:'0.001'})}
            ${_formField({key:'metrics.gi', label:'GI', value:f.metrics.gi, type:'number', step:'0.001'})}
        </div>
        ${_formField({key:'metrics.score', label:s.planScoreFormLabel || 'Plan score', value:f.metrics.score, type:'number', step:'0.1', section:'metrics'})}
    `);
    // OAR table
    const oarRows = (f.oarDose || []).map((o, i) => `
        <tr>
            <td><input value="${escHtml(o.organ || '')}" oninput="updateOARDoseRow(${i}, 'organ', this.value)"/></td>
            <td><input value="${o.d2cc ?? ''}" type="number" step="0.1" oninput="updateOARDoseRow(${i}, 'd2cc', this.value)"/></td>
            <td><input value="${o.d1cc ?? ''}" type="number" step="0.1" oninput="updateOARDoseRow(${i}, 'd1cc', this.value)"/></td>
            <td><input value="${o.d0_1cc ?? ''}" type="number" step="0.1" oninput="updateOARDoseRow(${i}, 'd0_1cc', this.value)"/></td>
            <td><input value="${o.v100 ?? ''}" type="number" step="0.1" oninput="updateOARDoseRow(${i}, 'v100', this.value)"/></td>
            <td style="text-align:center;">
                <button onclick="removeOARDoseRow(${i})" class="btn btn-outline" style="height:22px;padding:0 6px;font-size:0.65rem;color:var(--danger);">✕</button>
            </td>
        </tr>
    `).join('');
    html += _formSection('🛡️ ' + s.section3, 'oarDose', `
        <table class="rp-oar-table">
            <thead><tr>
                <th>${s.organ}</th>
                <th>D₂cc (Gy)</th>
                <th>D₁cc (Gy)</th>
                <th>D₀.₁cc (Gy)</th>
                <th>V100 (%)</th>
                <th></th>
            </tr></thead>
            <tbody>${oarRows || `<tr><td colspan="6" class="rp-empty">—</td></tr>`}</tbody>
        </table>
        <div class="rp-btn-row">
            <button class="btn btn-outline" onclick="addOARDoseRow()">${s.addButtonLabel || '+ Add'}</button>
        </div>
    `);
    // Narrative
    html += _formSection('📝 ' + s.section5 + ' / ' + s.section6, 'narrative', `
        ${_formField({key:'interpretation', label:s.section5 + editorLabels.markdown, value:f.interpretation, type:'textarea', rows:5, section:'narrative'})}
        ${_formField({key:'safety', label:s.section6, value:f.safety, type:'textarea', rows:3, section:'narrative'})}
        ${_formField({key:'qaNotes', label:editorLabels.qaNotes, value:f.qaNotes, type:'textarea', rows:2, section:'narrative'})}
    `);
    // References
    const refList = (f.references || []).map((r, i) => `
        <div class="rp-ref-card">
            <div class="rp-ref-body">
                <div><b>[${escHtml(r.citeKey || `ref${i+1}`)}]</b> ${escHtml(r.title || '')}</div>
                <div class="rp-ref-meta">${escHtml(r.publisher || '')}${r.year ? ', ' + r.year : ''}</div>
                ${_safeReportUrl(r.url) ? `<a href="${escHtml(_safeReportUrl(r.url))}" target="_blank" rel="noopener noreferrer">↗ ${editorLabels.open}</a>` : ''}
            </div>
            <button onclick="removeReportReference(${i})" class="btn btn-outline" style="height:22px;padding:0 6px;font-size:0.65rem;color:var(--danger);">✕</button>
        </div>`).join('');
    html += _formSection('📚 ' + s.section7 + ` (${(f.references || []).length})`, 'references', `
        <div>${refList || '<div class="rp-empty">—</div>'}</div>
        <details style="margin-top:6px;">
            <summary style="font-size:0.7rem;color:var(--primary);cursor:pointer;font-weight:500;">+ ${editorLabels.addReference}</summary>
            <div style="margin-top:6px;padding:8px;background:var(--primary-soft);border:1px solid var(--primary);border-radius:var(--radius-xs);">
                <select onchange="if(this.value){addReportReferenceFromCatalog(this.value);this.value='';}" class="form-select" style="font-size:0.7rem;margin-bottom:5px;">
                    <option value="">— ${editorLabels.selectReference} —</option>
                    ${Object.values(REPORT_REFERENCES_CATALOG).map(r => `<option value="${escHtml(r.citeKey)}">[${escHtml(r.citeKey)}] ${escHtml(r.title.substring(0, 70))}…</option>`).join('')}
                </select>
                <div style="font-size:0.65rem;color:var(--text-dim);margin:4px 0;">— ${editorLabels.orAddCustom} —</div>
                <div style="display:grid;grid-template-columns:1fr 2fr;gap:6px;margin-bottom:5px;">
                    <input id="refCiteKey" placeholder="${editorLabels.citeKey}" class="form-input" style="font-size:0.7rem;"/>
                    <input id="refTitle" placeholder="${editorLabels.title}" class="form-input" style="font-size:0.7rem;"/>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-top:5px;">
                    <input id="refPublisher" placeholder="${editorLabels.publisher}" class="form-input" style="font-size:0.7rem;"/>
                    <input id="refYear" placeholder="${editorLabels.year}" type="number" class="form-input" style="font-size:0.7rem;"/>
                    <input id="refJurisdiction" placeholder="${editorLabels.jurisdiction}" class="form-input" style="font-size:0.7rem;"/>
                </div>
                <input id="refUrl" placeholder="${editorLabels.url}" class="form-input" style="font-size:0.7rem;margin-top:5px;"/>
                <div class="rp-btn-row">
                    <button onclick="addReportReferenceCustom()" class="btn btn-primary">${editorLabels.add}</button>
                </div>
            </div>
        </details>
    `);
    // Figures
    const figList = (f.figures || []).map((fig, i) => {
        const safeImageUrl = _safeReportImageUrl(fig.dataUrl);
        if (!safeImageUrl) return '';
        return `
        <div class="rp-figure-card">
            <img src="${escHtml(safeImageUrl)}" alt="${escHtml(fig.title || '')}"/>
            <div class="rp-figure-meta">
                <div style="font-weight:500;">${escHtml(fig.title || '(untitled)')}</div>
                <div class="rp-figure-sub">${fig.axis ? `${fig.axis} slice ${fig.sliceIdx ?? '?'}` : ''} · ${fig.capturedAt ? new Date(fig.capturedAt).toLocaleString() : ''}</div>
                ${fig.caption ? `<div class="rp-figure-sub" style="margin-top:1px;">${escHtml(fig.caption)}</div>` : ''}
            </div>
            <button onclick="removeReportFigure(${i})" class="btn btn-outline" style="height:22px;padding:0 6px;font-size:0.65rem;color:var(--danger);">✕</button>
        </div>
    `;
    }).join('');
    html += _formSection((s.figuresSectionTitle || '🖼️ Figures') + ' (' + (f.figures || []).length + ')', 'figures', `
        <div>${figList || '<div class="rp-empty">—</div>'}</div>
        <div class="rp-btn-row">
            <button class="btn btn-outline" onclick="captureReportFigure2D()">${editorLabels.capture2d}</button>
            <button class="btn btn-outline" onclick="captureReportFigure3D()">${editorLabels.capture3d}</button>
            <label class="btn btn-outline" style="cursor:pointer;">
                ${editorLabels.upload}
                <input type="file" accept="image/png,image/jpeg,image/webp" onchange="uploadReportFigure(event)" style="display:none;"/>
            </label>
        </div>
    `);
    // Signature
    html += _formSection('✍️ ' + s.section9, 'signature', `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            ${_formField({key:'signature.name', label:s.reviewerName, value:f.signature.name, section:'signature'})}
            ${_formField({key:'signature.title', label:s.reviewerTitle, value:f.signature.title, section:'signature'})}
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            ${_formField({key:'signature.date', label:s.planDate, value:f.signature.date, type:'date', section:'signature'})}
            ${_formField({key:'signature.notes', label:s.notes || 'Notes', value:f.signature.notes, type:'textarea', rows:2, section:'signature'})}
        </div>
    `);

    host.innerHTML = html;
    _updateLanguageButtons();
    _updateReportStatusbar();
}

// ----- 8. Field-edit handler (two-way binding) -----
function onReportFieldEdit(key) {
    const f = window.reportForm;
    const el = document.getElementById('rf-' + key.replace(/[^a-zA-Z0-9_]/g, '_'));
    if (!el) return;
    const val = el.type === 'number' ? (el.value === '' ? null : parseFloat(el.value)) : el.value;
    const parts = key.split('.');
    let obj = f;
    for (let i = 0; i < parts.length - 1; i++) {
        if (obj[parts[i]] === undefined) obj[parts[i]] = {};
        obj = obj[parts[i]];
    }
    obj[parts[parts.length - 1]] = val;
    f.editedFields.add(key);
    _scheduleReportAutoSave();
    _updateReportStatusbar();
}

// ----- 9. OAR / Reference / Figure helpers -----
function addOARDoseRow() {
    if (!window.reportForm.oarDose) window.reportForm.oarDose = [];
    window.reportForm.oarDose.push({ organ: '', d2cc: null, d1cc: null, d0_1cc: null, v100: null });
    renderReportEditor();
    _updateReportPreview();
}
function updateOARDoseRow(idx, key, value) {
    const row = window.reportForm.oarDose[idx];
    if (!row) return;
    row[key] = (key !== 'organ' && value !== '') ? parseFloat(value) : value;
    _scheduleReportAutoSave();
}
function removeOARDoseRow(idx) {
    window.reportForm.oarDose.splice(idx, 1);
    renderReportEditor();
    _updateReportPreview();
    _scheduleReportAutoSave();
}
function addReportReferenceFromCatalog(citeKey) {
    const ref = REPORT_REFERENCES_CATALOG[citeKey];
    if (!ref) return;
    if (!window.reportForm.references) window.reportForm.references = [];
    if (window.reportForm.references.some(r => r.citeKey === citeKey)) { _setReportStatus(citeKey + ' already in list', 'warn'); return; }
    window.reportForm.references.push({ ...ref, custom: false });
    renderReportEditor(); _updateReportPreview(); _scheduleReportAutoSave();
}
function addReportReferenceCustom() {
    const citeKey = document.getElementById('refCiteKey').value.trim() || `custom${Date.now()}`;
    const title = document.getElementById('refTitle').value.trim();
    if (!title) { _setReportStatus('Title required', 'warn'); return; }
    const rawUrl = document.getElementById('refUrl').value.trim();
    const safeUrl = _safeReportUrl(rawUrl);
    if (rawUrl && !safeUrl) { _setReportStatus('Reference URL must use http or https', 'warn'); return; }
    if (!window.reportForm.references) window.reportForm.references = [];
    window.reportForm.references.push({
        citeKey, title,
        publisher: document.getElementById('refPublisher').value.trim(),
        year: parseInt(document.getElementById('refYear').value) || null,
        jurisdiction: document.getElementById('refJurisdiction').value.trim(),
        url: safeUrl,
        custom: true,
    });
    ['refCiteKey','refTitle','refPublisher','refYear','refJurisdiction','refUrl'].forEach(id => { const e = document.getElementById(id); if (e) e.value = ''; });
    renderReportEditor(); _updateReportPreview(); _scheduleReportAutoSave();
}
function removeReportReference(idx) {
    window.reportForm.references.splice(idx, 1);
    renderReportEditor(); _updateReportPreview(); _scheduleReportAutoSave();
}
async function captureReportFigure2D() {
    const axes = ['axial', 'sagittal', 'coronal'];
    let captured = null;
    for (const ax of axes) {
        const card = document.getElementById('viewer' + ax.charAt(0).toUpperCase() + ax.slice(1));
        if (card && card.offsetParent !== null) {
            const sliceIdx = (state.slices && state.slices[ax]) || 0;
            const composite = _composite2DViewerCanvas(ax);
            if (composite) {
                captured = { type: 'screenshot', title: `${ax} view (slice ${sliceIdx})`, dataUrl: composite, axis: ax, sliceIdx, caption: '', capturedAt: new Date().toISOString() };
                break;
            }
        }
    }
    if (!captured) { _setReportStatus('Open the Viewers panel first', 'warn'); return; }
    if (!window.reportForm.figures) window.reportForm.figures = [];
    window.reportForm.figures.push(captured);
    renderReportEditor(); _updateReportPreview(); _scheduleReportAutoSave();
}
function captureReportFigure3D() {
    const canvas = document.querySelector('#canvas3D canvas');
    if (!canvas) { _setReportStatus('3D viewer not initialized', 'warn'); return; }
    try {
        const dataUrl = canvas.toDataURL('image/png');
        const captured = { type: 'screenshot', title: '3D reconstruction', dataUrl, axis: '3d', sliceIdx: null, caption: '', capturedAt: new Date().toISOString() };
        if (!window.reportForm.figures) window.reportForm.figures = [];
        window.reportForm.figures.push(captured);
        renderReportEditor(); _updateReportPreview(); _scheduleReportAutoSave();
    } catch (e) { _setReportStatus('3D capture failed: ' + e.message, 'warn'); }
}
function uploadReportFigure(event) {
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    const allowedTypes = new Set(['image/png', 'image/jpeg', 'image/webp']);
    if (!allowedTypes.has(file.type) || file.size > 15 * 1024 * 1024) {
        _setReportStatus('Use a PNG, JPEG, or WebP image up to 15 MB', 'warn');
        event.target.value = '';
        return;
    }
    const reader = new FileReader();
    reader.onload = (e) => {
        const dataUrl = _safeReportImageUrl(e.target.result);
        if (!dataUrl) { _setReportStatus('Invalid report image', 'warn'); return; }
        const fig = { type: 'upload', title: file.name, dataUrl, caption: '', capturedAt: new Date().toISOString() };
        if (!window.reportForm.figures) window.reportForm.figures = [];
        window.reportForm.figures.push(fig);
        renderReportEditor(); _updateReportPreview(); _scheduleReportAutoSave();
    };
    reader.readAsDataURL(file);
    event.target.value = '';
}
function removeReportFigure(idx) {
    window.reportForm.figures.splice(idx, 1);
    renderReportEditor(); _updateReportPreview(); _scheduleReportAutoSave();
}

// Auto-capture visual evidence for the report (2026-06-15, rewritten 2026-06-26).
// Captures segmentation overlay, dose heatmap, DVH curves, and 3D
// planning view — each as a figure with a descriptive caption.
// Called before PDF export so the report always has evidence.
//
// FIGURE 1: 3D Seed Implant Plan (two independent subfigures)
//   Left:  Front-facing panoramic with all OARs (semi-transparent),
//          needle paths (red), radioactive seeds (yellow), CTV
//   Right: Camera aimed at translucent CTV tumor showing internal
//          3D seed distribution; OAR and guide-skin meshes are hidden
//
// FIGURE 2: Dose Distribution & DVH (five independent subfigures)
//   Top:   Axial / Sagittal / Coronal CT with dose heatmap at
//          peak dose voxel, arranged in a row
//   Bottom: DVH curve (CTV + OARs)
let _reportCapturePromise = null;
let _reportCaptureGeneration = 0;

// Figure 1 is a clinical evidence contract rather than a snapshot of the
// operator's current camera. Persisting the contract lets a later hydration
// path identify a legacy capture and regenerate the intended global/detail
// pair instead of silently preserving a semantically swapped image.
const REPORT_FIGURE_ONE_CAPTURE_CONTRACT = 'figure1-global-overview-target-detail-v3-no-oar-closeup';
window.REPORT_FIGURE_ONE_CAPTURE_CONTRACT = REPORT_FIGURE_ONE_CAPTURE_CONTRACT;

function _currentReportCaptureSessionId() {
    const value = (typeof _activeApiSessionId === 'function' && _activeApiSessionId())
        || (typeof activeSessionId !== 'undefined' && activeSessionId)
        || window.state?.sessionId
        || '';
    return String(value || '');
}

function invalidateReportCapture() {
    _reportCaptureGeneration += 1;
    return _reportCaptureGeneration;
}
window.invalidateReportCapture = invalidateReportCapture;

// Serialize report captures. A planning refresh can be triggered by several
// SSE events; overlapping captures otherwise race over mesh visibility and
// leave the 3D renderer in the partially hidden state used by Figure 1.
async function autoCaptureReportFigures(options = {}) {
    const requestedSessionId = String(options.sessionId || _currentReportCaptureSessionId());
    if (_reportCapturePromise) {
        await _reportCapturePromise;
        if (requestedSessionId !== _currentReportCaptureSessionId()) return { stale: true };
        return autoCaptureReportFigures(options);
    }
    const context = {
        generation: _reportCaptureGeneration,
        sessionId: requestedSessionId,
        reportForm: window.reportForm,
    };
    const promise = _autoCaptureReportFiguresImpl(context);
    _reportCapturePromise = promise;
    try {
        return await promise;
    } finally {
        if (_reportCapturePromise === promise) _reportCapturePromise = null;
    }
}

async function _autoCaptureReportFiguresImpl(captureContext = {}) {
    uiDebugLog('[Report] autoCaptureReportFigures called');
    if (!window.reportForm) { console.warn('[Report] No reportForm, skipping'); return; }
    const captureSessionId = String(captureContext.sessionId || _currentReportCaptureSessionId());
    const captureGeneration = Number(captureContext.generation ?? _reportCaptureGeneration);
    const captureForm = captureContext.reportForm || window.reportForm;
    const isCurrentCapture = () => captureGeneration === _reportCaptureGeneration
        && captureSessionId === _currentReportCaptureSessionId()
        && captureForm === window.reportForm;
    if (!isCurrentCapture()) return { stale: true };
    if (!window.reportForm.figures) window.reportForm.figures = [];

    // Drop stale auto-captured figures (user-uploads are kept).
    // Also drop incomplete auto-captures (missing DVH or dose).
    try {
        const _lastPlan = window.state && window.state.lastPlanTimestamp;
        if (_lastPlan && window.reportForm.figures) {
            const _ts = new Date(_lastPlan).getTime();
            window.reportForm.figures = window.reportForm.figures.filter(f => {
                if (!f) return false;
                if (f.type === 'upload') return true;
                const fts = f.capturedAt ? new Date(f.capturedAt).getTime() : 0;
                // Keep if captured after last plan AND not a stale auto-capture
                if (fts >= _ts) return true;
                return false;
            });
        }
    } catch (_) {}

    // Always clear auto-captured figures to allow fresh capture with complete data
    window.reportForm.figures = (window.reportForm.figures || []).filter(f => f && f.type === 'upload');

    if (window.reportForm.figures.length > 0) {
        // User-provided evidence supplements the standard report; it must not
        // suppress the seven required Planning/Dose subfigures.
        uiDebugLog('[Report] Keeping user figures while capturing standard figures:', window.reportForm.figures.length);
    }
    uiDebugLog('[Report] Starting capture, 3D meshes:', Object.keys(scene3D.meshes).length,
        'doseOverlay:', !!state.doseOverlay, 'dvhData:', !!state.dvhData);

    // Language-aware labels
    const _f = window.reportForm;
    const lang = (typeof window._i18nLang === 'string') ? window._i18nLang : ((_f && _f.language) || 'en');
    const labels = (lang === 'zh') ? {
        seed3d: '粒子植入方案',
        seed3dCap: '正面全景与靶区特写分别保存为独立高分辨率子图。',
        doseDvh: '剂量分布与DVH',
        doseDvhCap: '三个最大剂量层面、三维剂量面和 DVH 分别保存为独立高分辨率子图。',
        lblFront: '正面全景（含危及器官）',
        lblInside: '半透明肿瘤内部（粒子分布）',
        lblAxial: '轴位', lblSagittal: '矢状位', lblCoronal: '冠状位',
        lblDoseSurface: 'CTV/OAR 三维剂量面',
        lblDvh: 'DVH 剂量体积直方图',
        capFront: '沿穿刺参考方向观察的全局规划视图，显示 CTV、邻近 OAR、穿刺针与粒子。',
        capInside: 'CTV 局部特写，显示半透明靶区内的粒子及其所属针道。',
        capAxial: '经过峰值剂量体素的轴位 CT 与剂量叠加图。',
        capSagittal: '经过峰值剂量体素的矢状位 CT 与剂量叠加图。',
        capCoronal: '经过峰值剂量体素的冠状位 CT 与剂量叠加图。',
        capDoseSurface: '沿穿刺参考方向观察的 CTV、邻近 OAR 与三维剂量分布。',
        capDvh: '当前 Planning 的 CTV 与 OAR 剂量体积曲线。',
    } : {
        seed3d: 'Seed Implant Plan',
        seed3dCap: 'The planning overview and target close-up are stored as independent high-resolution subfigures.',
        doseDvh: 'Dose Distribution & DVH',
        doseDvhCap: 'The three peak-dose planes, 3D dose surface, and DVH are stored as independent high-resolution subfigures.',
        lblFront: 'Reference-direction front view',
        lblInside: 'Translucent tumor (seed distribution)',
        lblAxial: 'Axial', lblSagittal: 'Sagittal', lblCoronal: 'Coronal',
        lblDoseSurface: 'CTV/OAR dose surface',
        lblDvh: 'DVH - Dose Volume Histogram',
        capFront: 'Global plan viewed along the needle reference direction, including CTV, nearby OARs, needles, and seeds.',
        capInside: 'Target close-up showing seeds and their needle paths inside the translucent CTV.',
        capAxial: 'Axial CT and dose overlay through the peak-dose voxel.',
        capSagittal: 'Sagittal CT and dose overlay through the peak-dose voxel.',
        capCoronal: 'Coronal CT and dose overlay through the peak-dose voxel.',
        capDoseSurface: 'CTV, nearby OARs, and 3D dose distribution viewed along the needle reference direction.',
        capDvh: 'Dose-volume curves for the CTV and OARs in the current Planning run.',
    };

    const _ts = () => new Date().toISOString();
    function _pngDataUrlSize(dataUrl) {
        if (typeof dataUrl !== 'string' || !dataUrl.startsWith('data:image/png;base64,')) return null;
        try {
            // PNG stores width and height as big-endian uint32 values in IHDR.
            // Reading only the header avoids decoding the full clinical capture.
            const header = atob(dataUrl.slice(dataUrl.indexOf(',') + 1, dataUrl.indexOf(',') + 65));
            if (header.length < 24 || header.slice(1, 4) !== 'PNG') return null;
            const uint32 = offset => (
                (header.charCodeAt(offset) << 24)
                | (header.charCodeAt(offset + 1) << 16)
                | (header.charCodeAt(offset + 2) << 8)
                | header.charCodeAt(offset + 3)
            ) >>> 0;
            const width = uint32(16);
            const height = uint32(20);
            return width > 0 && height > 0 ? { width, height } : null;
        } catch (_) {
            return null;
        }
    }

    const _push = (title, caption, dataUrl, axis, extra) => {
        if (!isCurrentCapture()) return;
        if (!dataUrl || dataUrl.length < 1000) {
            console.warn('[Report] Figure skipped: dataUrl too short or null');
            return;
        }
        const stableAxis = axis || '3d';
        const imageSize = _pngDataUrlSize(dataUrl);
        const figure = {
            type: 'screenshot', title, dataUrl, axis: stableAxis,
            sliceIdx: null, caption, capturedAt: _ts(), ...extra,
            ...(imageSize ? {
                pixelWidth: imageSize.width,
                pixelHeight: imageSize.height,
                aspectRatio: imageSize.width / imageSize.height,
            } : {}),
        };
        const figures = Array.isArray(window.reportForm.figures)
            ? window.reportForm.figures : (window.reportForm.figures = []);
        const existingIndex = figures.findIndex(existing => (
            existing?.type === 'screenshot' && String(existing.axis || '') === stableAxis
        ));
        if (existingIndex >= 0) figures.splice(existingIndex, 1, figure);
        else figures.push(figure);
        uiDebugLog('[Report] Figure captured:', title, Math.round(dataUrl.length / 1024), 'KB');
    };

    // Helper: wait for render
    const _waitFrames = (n = 2) => new Promise(r => {
        let count = 0;
        const tick = () => { if (++count >= n) r(); else requestAnimationFrame(tick); };
        requestAnimationFrame(tick);
    });

    // Helper: draw image onto canvas context, returns Promise
    function _drawImg(ctx, dataUrl, dx, dy, maxW, maxH, opts = {}) {
        return new Promise(resolve => {
            if (!dataUrl) { resolve(false); return; }
            const img = new Image();
            img.onload = () => {
                const fit = opts.fit === 'cover' ? 'cover' : 'contain';
                const rawScale = fit === 'cover'
                    ? Math.max(maxW / img.width, maxH / img.height)
                    : Math.min(maxW / img.width, maxH / img.height);
                const scale = opts.allowUpscale ? rawScale : Math.min(rawScale, 1);
                const w = img.width * scale, h = img.height * scale;
                ctx.drawImage(img, dx + (maxW - w) / 2, dy + (maxH - h) / 2, w, h);
                resolve(true);
            };
            img.onerror = () => resolve(false);
            img.src = dataUrl;
        });
    }

    async function _drawFigurePanel(ctx, dataUrl, x, y, w, h, badge, label) {
        ctx.save();
        ctx.fillStyle = '#020617';
        ctx.strokeStyle = 'rgba(148,163,184,0.28)';
        ctx.lineWidth = 1;
        ctx.fillRect(x, y, w, h);
        ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
        await _drawImg(ctx, dataUrl, x + 8, y + 24, w - 16, h - 54, { allowUpscale: true, fit: 'contain' });
        ctx.fillStyle = 'rgba(15,23,42,0.92)';
        ctx.strokeStyle = 'rgba(148,163,184,0.32)';
        ctx.beginPath();
        if (typeof ctx.roundRect === 'function') {
            ctx.roundRect(x + 10, y + 8, 28, 22, 6);
        } else {
            ctx.rect(x + 10, y + 8, 28, 22);
        }
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = '#e2e8f0';
        ctx.font = 'bold 12px Inter, system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(`(${badge})`, x + 24, y + 23);
        ctx.fillStyle = '#cbd5e1';
        ctx.font = '12px Inter, system-ui, sans-serif';
        ctx.fillText(label, x + w / 2, y + h - 18);
        ctx.restore();
    }

    function _drawDoseColorbar(ctx, x, y, w, h, title = 'Dose (Gy)') {
        ctx.save();
        ctx.fillStyle = 'rgba(2,6,23,0.92)';
        ctx.strokeStyle = 'rgba(148,163,184,0.32)';
        ctx.lineWidth = 1;
        ctx.fillRect(x, y, w, h);
        ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);

        const barX = x + 12;
        const barY = y + 28;
        const barW = 18;
        const barH = h - 52;
        const gradCanvas = document.createElement('canvas');
        gradCanvas.width = barW;
        gradCanvas.height = barH;
        _drawDoseColorbarGradient(gradCanvas.getContext('2d'), barW, barH);
        ctx.drawImage(gradCanvas, barX, barY);
        ctx.strokeStyle = 'rgba(226,232,240,0.65)';
        ctx.strokeRect(barX + 0.5, barY + 0.5, barW - 1, barH - 1);

        ctx.fillStyle = '#e2e8f0';
        ctx.font = 'bold 11px Inter, system-ui, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(title, x + 8, y + 18);
        _doseColorbarLabelSpecs(barH).forEach(spec => {
            const ty = barY + (barH - 1) * (spec.pct / 100);
            ctx.strokeStyle = 'rgba(226,232,240,0.72)';
            ctx.beginPath();
            ctx.moveTo(barX + barW + 2, ty);
            ctx.lineTo(barX + barW + 7, ty);
            ctx.stroke();
            ctx.fillStyle = '#cbd5e1';
            ctx.font = `${spec.major ? 'bold ' : ''}9px Inter, system-ui, sans-serif`;
            ctx.textAlign = 'left';
            ctx.fillText(spec.label, barX + barW + 10, ty + 3);
        });
        ctx.restore();
    }

    function _drawPlanLegend(ctx, x, y, w) {
        const items = [];
        const ctvColor = dataTreeState.ctv?.color || '#ff304c';
        items.push({ type: 'swatch', color: ctvColor, label: 'CTV / tumor' });
        const firstOar = (dataTreeState.organs || []).find(o => o.visible !== false) || dataTreeState.organs?.[0];
        items.push({ type: 'swatch', color: firstOar?.color || dataTreeState.oar?.color || '#4d9de0', label: 'OAR surfaces' });
        items.push({ type: 'seed', color: dataTreeState.planning?.seeds?.[0]?.color || dataTreeState.seeds?.color || '#ffcc00', label: 'I-125 seeds' });
        items.push({ type: 'needle', color: dataTreeState.planning?.needles?.[0]?.color || dataTreeState.needles?.color || '#ff2266', label: 'Needle paths' });
        const doseCfg = typeof getDoseColorbarConfig === 'function'
            ? getDoseColorbarConfig('threeD') : { minGy: 0, maxGy: 200 };
        items.push({ type: 'gradient', label: `Dose surface: <${doseCfg.minGy.toFixed(0)} to >${doseCfg.maxGy.toFixed(0)} Gy` });

        ctx.save();
        ctx.fillStyle = 'rgba(2,6,23,0.94)';
        ctx.strokeStyle = 'rgba(148,163,184,0.28)';
        ctx.lineWidth = 1;
        ctx.fillRect(x, y, w, 56);
        ctx.strokeRect(x + 0.5, y + 0.5, w - 1, 55);
        ctx.font = '11px Inter, system-ui, sans-serif';
        ctx.textAlign = 'left';
        let cx = x + 14;
        const cy = y + 29;
        items.forEach(item => {
            if (item.type === 'swatch') {
                ctx.fillStyle = item.color;
                ctx.fillRect(cx, cy - 6, 12, 12);
                ctx.strokeStyle = 'rgba(255,255,255,0.65)';
                ctx.strokeRect(cx + 0.5, cy - 5.5, 11, 11);
                cx += 18;
            } else if (item.type === 'seed') {
                ctx.fillStyle = item.color;
                ctx.beginPath();
                ctx.arc(cx + 6, cy, 6, 0, 2 * Math.PI);
                ctx.fill();
                ctx.strokeStyle = 'rgba(255,255,255,0.75)';
                ctx.stroke();
                cx += 18;
            } else if (item.type === 'needle') {
                ctx.strokeStyle = item.color;
                ctx.lineWidth = 3;
                ctx.beginPath();
                ctx.moveTo(cx, cy);
                ctx.lineTo(cx + 18, cy);
                ctx.stroke();
                cx += 24;
            } else {
                const grad = ctx.createLinearGradient(cx, cy, cx + 34, cy);
                grad.addColorStop(0, '#0034ff');
                grad.addColorStop(0.5, '#00ffff');
                grad.addColorStop(0.75, '#ffff00');
                grad.addColorStop(1, '#ff0000');
                ctx.fillStyle = grad;
                ctx.fillRect(cx, cy - 6, 34, 12);
                ctx.strokeStyle = 'rgba(255,255,255,0.65)';
                ctx.strokeRect(cx + 0.5, cy - 5.5, 33, 11);
                cx += 40;
            }
            ctx.fillStyle = '#cbd5e1';
            ctx.font = '11px Inter, system-ui, sans-serif';
            ctx.fillText(item.label, cx, cy + 4);
            cx += ctx.measureText(item.label).width + 22;
        });
        ctx.restore();
    }

    // Helper: draw a label centered below an image area
    function _drawLabel(ctx, text, cx, y, maxW) {
        ctx.fillStyle = '#94a3b8';
        ctx.font = '12px Inter, system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(text, cx, y, maxW);
    }

    /**
     * Resolve the plan's external-facing reference direction from authoritative
     * needle geometry. Planned needles use [deep target, shallow skin entry],
     * so points[1] - points[0] places the report camera on the entry side.
     */
    function _reportReferenceViewDirection() {
        const needles = Array.isArray(dataTreeState?.planning?.needles)
            ? dataTreeState.planning.needles
            : [];
        const directions = [];
        for (const needle of needles) {
            if (!Array.isArray(needle?.points) || needle.points.length < 2) continue;
            const deep = needle.points[0];
            const entry = needle.points[1];
            if (!Array.isArray(deep) || !Array.isArray(entry)) continue;
            const direction = new THREE.Vector3(
                Number(entry[0]) - Number(deep[0]),
                Number(entry[1]) - Number(deep[1]),
                Number(entry[2]) - Number(deep[2]),
            );
            if (![direction.x, direction.y, direction.z].every(Number.isFinite)
                || direction.lengthSq() < 1e-8) continue;
            directions.push(direction.normalize());
        }
        if (directions.length) {
            const anchor = directions[0];
            const averaged = new THREE.Vector3();
            directions.forEach(direction => {
                averaged.add(direction.dot(anchor) < 0 ? direction.clone().negate() : direction);
            });
            if (averaged.lengthSq() >= 1e-8) return averaged.normalize();
        }

        const fallback = new THREE.Vector3(
            Number(document.getElementById('refDirecX')?.value || 0),
            Number(document.getElementById('refDirecY')?.value || 1),
            Number(document.getElementById('refDirecZ')?.value || 0),
        );
        return fallback.lengthSq() >= 1e-8 ? fallback.normalize() : new THREE.Vector3(0, 1, 0);
    }

    function _reportCameraUp(viewDirection) {
        const direction = viewDirection.clone().normalize();
        const candidates = [
            new THREE.Vector3(0, 0, 1),
            new THREE.Vector3(0, 1, 0),
            new THREE.Vector3(1, 0, 0),
        ];
        return candidates.find(candidate => Math.abs(candidate.dot(direction)) < 0.92).clone();
    }

    /**
     * Frame a world-space box for the aspect ratio of the final report panel.
     * The live WebGL canvas is often much wider than the report panel, so using
     * its aspect directly leaves large black margins after composition.
     */
    function _frameReportCamera(box, {
        direction,
        targetAspect = 1,
        margin = 1.08,
    } = {}) {
        if (!(box && !box.isEmpty()) || !scene3D.camera || !scene3D.controls) return false;
        const center = box.getCenter(new THREE.Vector3());
        const cameraDirection = (direction || new THREE.Vector3(0, 1, 0)).clone().normalize();
        const cameraUp = _reportCameraUp(cameraDirection);
        const forward = cameraDirection.clone().negate();
        const right = forward.clone().cross(cameraUp).normalize();
        const trueUp = right.clone().cross(forward).normalize();
        const corners = [];
        for (const x of [box.min.x, box.max.x]) {
            for (const y of [box.min.y, box.max.y]) {
                for (const z of [box.min.z, box.max.z]) corners.push(new THREE.Vector3(x, y, z));
            }
        }
        let halfWidth = 0;
        let halfHeight = 0;
        let halfDepth = 0;
        corners.forEach(corner => {
            const relative = corner.sub(center);
            halfWidth = Math.max(halfWidth, Math.abs(relative.dot(right)));
            halfHeight = Math.max(halfHeight, Math.abs(relative.dot(trueUp)));
            halfDepth = Math.max(halfDepth, Math.abs(relative.dot(cameraDirection)));
        });
        const fov = (Number(scene3D.camera.fov) || 45) * Math.PI / 180;
        const halfFovY = Math.max(0.05, fov / 2);
        const aspect = Math.max(0.2, Number(targetAspect) || 1);
        const halfFovX = Math.atan(Math.tan(halfFovY) * aspect);
        const planarDistance = Math.max(
            halfHeight / Math.tan(halfFovY),
            halfWidth / Math.tan(halfFovX),
            1,
        );
        const distance = halfDepth + planarDistance * Math.max(1, Number(margin) || 1);
        window.sync3DCameraPose?.({
            position: center.clone().add(cameraDirection.multiplyScalar(distance)),
            target: center,
            up: trueUp,
            near: 0.01,
            far: Math.max(2000, distance * 20),
            aspect: scene3D.camera.aspect,
            fov: scene3D.camera.fov,
            // Report composition must not inherit an operator's previous
            // zoom-out state. The exact user zoom is restored after capture.
            zoom: 1,
        });
        return true;
    }

    function _captureReportCanvasCrop(canvas, targetAspect = 1, maxOutputEdge = 1200) {
        if (!canvas || canvas.width < 1 || canvas.height < 1) return null;
        const aspect = Math.max(0.2, Number(targetAspect) || 1);
        const sourceAspect = canvas.width / canvas.height;
        let sx = 0;
        let sy = 0;
        let sw = canvas.width;
        let sh = canvas.height;
        if (sourceAspect > aspect) {
            sw = sh * aspect;
            sx = (canvas.width - sw) / 2;
        } else if (sourceAspect < aspect) {
            sh = sw / aspect;
            sy = (canvas.height - sh) / 2;
        }
        const output = document.createElement('canvas');
        if (aspect >= 1) {
            output.width = maxOutputEdge;
            output.height = Math.max(1, Math.round(maxOutputEdge / aspect));
        } else {
            output.height = maxOutputEdge;
            output.width = Math.max(1, Math.round(maxOutputEdge * aspect));
        }
        output.getContext('2d').drawImage(canvas, sx, sy, sw, sh, 0, 0, output.width, output.height);
        return output.toDataURL('image/png');
    }

    const reportReferenceDirection = _reportReferenceViewDirection();
    // Report subfigures are captured independently at a page-friendly aspect.
    // Keeping native images separate preserves far more clinical detail than
    // drawing several small panels into one irreversible composite bitmap.
    const REPORT_FIGURE_ASPECT = 16 / 9;
    const REPORT_DOSE_SURFACE_ASPECT = REPORT_FIGURE_ASPECT;
    // Native subfigures are placed one per A4 evidence page. Retain enough
    // pixels for seed distribution and needle geometry to remain legible in
    // both the preview and exported PDF.
    const REPORT_FIGURE_LONG_EDGE = 1800;

    async function _waitForReportDoseSlice(axis, sliceIndex, timeoutMs = 12000) {
        const cap = axis.charAt(0).toUpperCase() + axis.slice(1);
        const expected = String(sliceIndex);
        const startedAt = performance.now();
        while (isCurrentCapture() && performance.now() - startedAt < timeoutMs) {
            const doseCanvas = document.getElementById(`doseOverlayCanvas${cap}`);
            const contourCanvas = document.getElementById(`contourCanvas${cap}`);
            const doseReady = doseCanvas?.dataset?.renderedAxis === axis
                && doseCanvas?.dataset?.renderedSlice === expected
                && doseCanvas?.dataset?.dosePending !== 'true';
            const contourReady = contourCanvas?.dataset?.renderedAxis === axis
                && contourCanvas?.dataset?.renderedSlice === expected;
            if (doseReady && contourReady && Number(state.slices?.[axis]) === Number(sliceIndex)) {
                return true;
            }
            await _waitFrames(1);
        }
        console.warn(`[Report] Timed out waiting for ${axis} dose/contour slice ${sliceIndex}`);
        return false;
    }

    // ═══════════════════════════════════════════════════════════
    // FIGURE 1: 3D SEED IMPLANT PLAN — TWO NATIVE SUBFIGURES
    //   (a) Reference-direction global view with nearby anatomy
    //   (b) Translucent target close-up showing seeds inside
    // ═══════════════════════════════════════════════════════════
    let _restoreFigure1State = null;
    try {
        const _meshCount = Object.keys(scene3D.meshes).length;
        if (scene3D.camera && scene3D.controls && scene3D.renderer && _meshCount > 0) {
            uiDebugLog('[Report] Figure 1: starting 3D capture, meshes:', _meshCount);

            // Save all visibility and opacity states
            const _saved = {};
            const _savedMaterials = {};
            const _savedHandleObjects = [];
            const _savedSkin = scene3D.skinMesh ? {
                mesh: scene3D.skinMesh,
                visible: scene3D.skinMesh.visible,
                material: scene3D.skinMesh.material,
            } : null;
            for (const [id, mesh] of Object.entries(scene3D.meshes)) {
                if (!mesh) continue;
                _saved[id] = { mesh, visible: mesh.visible };
                const surface = (typeof getMeshSurface === 'function') ? getMeshSurface(mesh) : mesh;
                if (surface) {
                    const materials = [];
                    const renderOrders = [];
                    const seenMaterials = new Set();
                    surface.traverse?.(object => {
                        renderOrders.push({ object, value: object.renderOrder });
                        const objectMaterials = Array.isArray(object.material)
                            ? object.material : [object.material];
                        objectMaterials.forEach(material => {
                            if (!material || seenMaterials.has(material)) return;
                            seenMaterials.add(material);
                            materials.push({
                                material,
                                opacity: material.opacity,
                                transparent: material.transparent,
                                depthWrite: material.depthWrite,
                                depthTest: material.depthTest,
                            });
                        });
                    });
                    _savedMaterials[id] = {
                        surface,
                        visible: surface.visible,
                        materials,
                        renderOrders,
                    };
                }
            }
            // Endpoint handles are interaction affordances, not treatment
            // geometry. Keep their state for restoration but exclude them
            // from publication figures.
            scene3D.scene?.traverse?.(object => {
                if (object?.userData?.type === 'needle_handle') {
                    _savedHandleObjects.push({ object, visible: object.visible });
                }
            });
            const _savedCamera = scene3D.camera ? {
                camera: scene3D.camera,
                controls: scene3D.controls,
                position: scene3D.camera.position.clone(),
                quaternion: scene3D.camera.quaternion.clone(),
                up: scene3D.camera.up.clone(),
                near: scene3D.camera.near,
                far: scene3D.camera.far,
                aspect: scene3D.camera.aspect,
                fov: scene3D.camera.fov,
                zoom: scene3D.camera.zoom,
                target: scene3D.controls.target.clone(),
            } : null;
            _restoreFigure1State = () => {
                for (const saved of Object.values(_saved)) {
                    const mesh = saved?.mesh;
                    if (!mesh) continue;
                    mesh.visible = saved.visible;
                }
                for (const material of Object.values(_savedMaterials)) {
                    if (!material?.surface) continue;
                    material.surface.visible = material.visible;
                    (material.renderOrders || []).forEach(savedOrder => {
                        if (savedOrder.object) savedOrder.object.renderOrder = savedOrder.value;
                    });
                    (material.materials || []).forEach(savedMaterial => {
                        const target = savedMaterial.material;
                        if (!target) return;
                        target.opacity = savedMaterial.opacity;
                        target.transparent = savedMaterial.transparent;
                        target.depthWrite = savedMaterial.depthWrite;
                        target.depthTest = savedMaterial.depthTest;
                        target.needsUpdate = true;
                    });
                }
                if (_savedSkin?.mesh) {
                    _savedSkin.mesh.visible = _savedSkin.visible;
                    _savedSkin.mesh.material = _savedSkin.material;
                }
                _savedHandleObjects.forEach(({ object, visible }) => {
                    if (object) object.visible = visible;
                });
                if (isCurrentCapture() && _savedCamera
                    && scene3D.camera === _savedCamera.camera
                    && scene3D.controls === _savedCamera.controls) {
                    if (typeof window.sync3DCameraPose === 'function') {
                        window.sync3DCameraPose({
                            position: _savedCamera.position,
                            target: _savedCamera.target,
                            quaternion: _savedCamera.quaternion,
                            up: _savedCamera.up,
                            near: _savedCamera.near,
                            far: _savedCamera.far,
                            aspect: _savedCamera.aspect,
                            fov: _savedCamera.fov,
                            zoom: _savedCamera.zoom,
                        });
                    } else {
                        _savedCamera.camera.position.copy(_savedCamera.position);
                        _savedCamera.camera.quaternion.copy(_savedCamera.quaternion);
                        _savedCamera.camera.up.copy(_savedCamera.up);
                        _savedCamera.controls.target.copy(_savedCamera.target);
                        _savedCamera.camera.near = _savedCamera.near;
                        _savedCamera.camera.far = _savedCamera.far;
                        _savedCamera.camera.aspect = _savedCamera.aspect;
                        _savedCamera.camera.fov = _savedCamera.fov;
                        _savedCamera.camera.zoom = _savedCamera.zoom;
                        _savedCamera.camera.updateProjectionMatrix();
                        _savedCamera.controls.syncExternalState?.();
                    }
                } else if (isCurrentCapture() && scene3D.controls) {
                    // A report capture may not have a saved camera only when
                    // the viewer was not initialized. Never fit implicitly;
                    // Fit/Reset are explicit user actions.
                    scene3D.controls.syncExternalState?.();
                }
                if (isCurrentCapture()) forceRender3DViewer();
            };

            // Helper: compute bounding box of all visible meshes
            function _computeSceneBox() {
                const box = new THREE.Box3();
                for (const mesh of Object.values(scene3D.meshes)) {
                    if (mesh && mesh.visible) {
                        try { box.expandByObject(mesh); } catch (_) {}
                    }
                }
                return box;
            }

            function _computeFocusedPlanBox({ includeOars = false, includeNeedles = true } = {}) {
                // Start at the clinical target and its sources.  Whole-body
                // OAR meshes must not define the framing box: that made both
                // Figure 1 panels too small to inspect.  Nearby OARs are
                // added in a second pass only when they overlap the local
                // planning context around the target.
                const coreBox = new THREE.Box3();
                const expand = (box, mesh) => {
                    if (!mesh || !mesh.visible) return;
                    try { box.expandByObject(mesh); } catch (_) {}
                };
                for (const [id, mesh] of Object.entries(scene3D.meshes)) {
                    if (!mesh) continue;
                    const isCtv = id === 'ctv' || id.startsWith('ctv_') || mesh?.userData?.source === 'ctv' || mesh?.userData?.type === 'ctv';
                    const isSeed = id.startsWith('seed_') || mesh?.userData?.type === 'seed';
                    const isNeedleHandle = mesh?.userData?.type === 'needle_handle';
                    const isNeedle = !isNeedleHandle && (id.startsWith('needle_') || mesh?.userData?.type === 'needle');
                    const isDose = id.startsWith('dose_iso_') || mesh?.userData?.type === 'dose_isosurface';
                    // The persisted guide skin is a full-body envelope used
                    // for fit/attachment inspection, not local anatomy for a
                    // planning figure.  Including it here makes Figure 1(a)
                    // frame the entire CT envelope and leaves the implant
                    // tiny in the center of the report image.
                    const isSkin = id === 'skin' || id === 'skin_surface'
                        || mesh === scene3D.skinMesh
                        || ['skin', 'skin_surface', 'guide_skin_surface'].includes(String(mesh?.userData?.type || ''));
                    const isOar = !isCtv && !isSeed && !isNeedle && !isDose && !isSkin;
                    if (isCtv || isSeed || (includeNeedles && isNeedle)) expand(coreBox, mesh);
                }
                if (!(coreBox.min.x < coreBox.max.x)) return _computeSceneBox();
                const box = coreBox.clone();
                if (includeOars) {
                    const size = coreBox.getSize(new THREE.Vector3());
                    const localContext = coreBox.clone().expandByScalar(Math.max(20, size.length() * 0.4));
                    for (const [id, mesh] of Object.entries(scene3D.meshes)) {
                        if (!mesh) continue;
                        const isCtv = id === 'ctv' || id.startsWith('ctv_') || mesh?.userData?.source === 'ctv' || mesh?.userData?.type === 'ctv';
                        const isSeed = id.startsWith('seed_') || mesh?.userData?.type === 'seed';
                        const isNeedle = mesh?.userData?.type !== 'needle_handle' && (id.startsWith('needle_') || mesh?.userData?.type === 'needle');
                        const isDose = id.startsWith('dose_iso_') || mesh?.userData?.type === 'dose_isosurface';
                        const isSkin = id === 'skin' || id === 'skin_surface'
                            || mesh === scene3D.skinMesh
                            || ['skin', 'skin_surface', 'guide_skin_surface'].includes(String(mesh?.userData?.type || ''));
                        const isOar = !isCtv && !isSeed && !isNeedle && !isDose && !isSkin;
                        if (!isOar || !mesh.visible) continue;
                        const candidate = new THREE.Box3();
                        try { candidate.expandByObject(mesh); } catch (_) { continue; }
                        if (!candidate.intersectsBox(localContext)) continue;
                        const localCandidate = candidate.clone().intersect(localContext);
                        if (!localCandidate.isEmpty()) box.union(localCandidate);
                    }
                }
                if (!(box.min.x < box.max.x)) return _computeSceneBox();
                return box;
            }

            function _frameCameraToBox(box, mode) {
                const direction = mode === 'detail'
                    ? new THREE.Vector3(0.55, -0.25, 0.8).normalize()
                    : reportReferenceDirection;
                _frameReportCamera(box, {
                    direction,
                    targetAspect: REPORT_FIGURE_ASPECT,
                    // The overview needs enough surrounding anatomy to make
                    // the full implant geometry intelligible in a report.
                    // The close-up remains intentionally tight around CTV.
                    margin: mode === 'detail' ? 1.10 : 1.30,
                });
            }

            // Helper: render and capture 3D canvas
            async function _capture3D(label, targetAspect = 1, maxOutputEdge = REPORT_FIGURE_LONG_EDGE) {
                if (!isCurrentCapture()) return null;
                await _waitFrames(3);
                if (!isCurrentCapture()) return null;
                const renderer = scene3D.renderer;
                const c = renderer && renderer.domElement;
                if (!renderer || !c) return null;
                const width = c.clientWidth || c.width;
                const height = c.clientHeight || c.height;
                if (!width || !height) {
                    console.warn('[Report] 3D canvas has no drawable size for', label);
                    return null;
                }
                // Keep the live renderer buffer and CSS geometry authoritative.
                // Resizing it to capture dimensions changes the next interactive
                // frame's aspect/DPR and was a source of zoom distortion.
                scene3D.resize?.();
                scene3D.renderNow?.();
                await _waitFrames(2);
                if (!isCurrentCapture()) return null;
                // Render once more after the browser has committed visibility,
                // material, and camera changes. This avoids intermittent black
                // captures when the report is generated during reconstruction.
                scene3D.renderNow?.();
                try {
                    const gl = renderer.getContext?.();
                    if (gl && renderer.domElement.width > 0 && renderer.domElement.height > 0) {
                        const sample = new Uint8Array(4);
                        let hasLitPixel = false;
                        for (let gx = 1; gx <= 5 && !hasLitPixel; gx++) {
                            for (let gy = 1; gy <= 5 && !hasLitPixel; gy++) {
                                gl.readPixels(
                                    Math.floor(renderer.domElement.width * gx / 6),
                                    Math.floor(renderer.domElement.height * gy / 6),
                                    1, 1, gl.RGBA, gl.UNSIGNED_BYTE, sample,
                                );
                                hasLitPixel = sample[0] > 4 || sample[1] > 4 || sample[2] > 4;
                            }
                        }
                        if (!hasLitPixel) {
                            console.warn('[Report] 3D capture contains no lit pixels for', label);
                            return null;
                        }
                    }
                    const url = _captureReportCanvasCrop(c, targetAspect, maxOutputEdge);
                    if (!url || url.length < 5000) {
                        console.warn('[Report] 3D capture appears blank for', label);
                        return null;
                    }
                    uiDebugLog('[Report] 3D capture', label, ':', Math.round(url.length / 1024), 'KB');
                    return url;
                } catch (e) {
                    console.warn('[Report] 3D toDataURL failed:', e);
                    return null;
                }
            }

            // ── View A: Front-facing with all OARs ──
            if (!isCurrentCapture()) return { stale: true };
            window.__reportCaptureActive = true;
            // Show all models for the overall panel. The focused camera below
            // still limits the frame to the target and its local OAR context.
            for (const [id, mesh] of Object.entries(scene3D.meshes)) {
                if (mesh) mesh.visible = true;
            }
            _savedHandleObjects.forEach(({ object }) => { if (object) object.visible = false; });
            const _isFigureOneCtv = (id, mesh) => id === 'ctv' || id.startsWith('ctv_')
                || mesh?.userData?.source === 'ctv' || mesh?.userData?.type === 'ctv';
            const _isFigureOneSeed = (id, mesh) => id.startsWith('seed_')
                || mesh?.userData?.type === 'seed' || mesh?.userData?.kind === 'seed';
            const _isFigureOneNeedle = (id, mesh) => mesh?.userData?.type !== 'needle_handle'
                && (id.startsWith('needle_') || mesh?.userData?.type === 'needle');
            // Figure 1(b) is an implant-target detail, not an anatomy panel.
            // Keep this classification explicit because restored/generic meshes
            // may not use the `organ_*` ID convention consistently. OAR has
            // priority over the allow-list below so an incorrectly inherited
            // source tag can never leak an OAR into the close-up.
            const _isFigureOneOar = (id, mesh) => {
                const key = String(id || '').toLowerCase();
                const source = String(mesh?.userData?.source || '').toLowerCase();
                const type = String(mesh?.userData?.type || '').toLowerCase();
                const category = String(mesh?.userData?.category || mesh?.userData?.classification || '').toLowerCase();
                return key === 'oar' || key.startsWith('oar_') || key.startsWith('organ_')
                    || source === 'oar' || type === 'oar' || type === 'oar_mask'
                    || category === 'oar';
            };
            const _isFigureOneSkin = (id, mesh) => id === 'skin' || id === 'skin_surface'
                || mesh === scene3D.skinMesh
                || ['skin', 'skin_surface', 'guide_skin_surface'].includes(String(mesh?.userData?.type || ''));
            const _setFigureOneOpacity = (mesh, opacity) => {
                if (!mesh) return;
                const surface = (typeof getMeshSurface === 'function') ? getMeshSurface(mesh) : mesh;
                surface?.traverse?.(object => {
                    const materials = Array.isArray(object.material) ? object.material : [object.material];
                    materials.forEach(material => {
                        if (!material) return;
                        material.opacity = opacity;
                        material.transparent = opacity < 1;
                        material.needsUpdate = true;
                    });
                });
            };

            // The guide-fit skin surface is useful in the interactive viewer,
            // but it is a CT-wide envelope rather than planning evidence. Keep
            // it out of Figure 1(a) so the global plan is not framed or hidden
            // by the whole-body surface. The saved state is restored below.
            for (const [id, mesh] of Object.entries(scene3D.meshes)) {
                if (_isFigureOneSkin(id, mesh) && mesh) mesh.visible = false;
            }
            if (scene3D.skinMesh) scene3D.skinMesh.visible = false;

            // OARs semi-transparent (not seeds, needles, dose, or CTV)
            for (const [id, mesh] of Object.entries(scene3D.meshes)) {
                if (!mesh || _isFigureOneSkin(id, mesh) || _isFigureOneCtv(id, mesh) || _isFigureOneSeed(id, mesh)
                    || _isFigureOneNeedle(id, mesh) || id.startsWith('dose_iso_')) continue;
                _setFigureOneOpacity(mesh, 0.15);
            }
            // CTV semi-transparent
            const ctvMesh = scene3D.meshes['ctv']
                || Object.values(scene3D.meshes).find(m => m?.userData?.source === 'ctv');
            _setFigureOneOpacity(ctvMesh, 0.30);

            // Figure 1(a) is the global plan. Include the full planned needle
            // geometry, but omit the CT-wide skin envelope from the framing.
            _frameCameraToBox(_computeFocusedPlanBox({ includeOars: true, includeNeedles: true }), 'overview');
            await _waitFrames(2);
            if (!isCurrentCapture()) return { stale: true };
            let imgA = await _capture3D('View A (front+OARs)', REPORT_FIGURE_ASPECT);
            if (!imgA) {
                forceRender3DViewer();
                await _waitFrames(4);
                if (!isCurrentCapture()) return { stale: true };
                imgA = await _capture3D('View A (front+OARs retry)', REPORT_FIGURE_ASPECT);
            }

            // ── View B: Translucent tumor, seeds visible inside ──
            // Figure 1(b) is an explicit allow-list: CTV/tumor, seeds, and
            // needle paths only. In particular, hide every OAR even if a
            // restored mesh carries an ambiguous or stale CTV source tag.
            for (const [id, mesh] of Object.entries(scene3D.meshes)) {
                if (!mesh) continue;
                mesh.visible = !_isFigureOneOar(id, mesh)
                    && (_isFigureOneCtv(id, mesh)
                        || _isFigureOneSeed(id, mesh)
                        || _isFigureOneNeedle(id, mesh));
            }
            _savedHandleObjects.forEach(({ object }) => { if (object) object.visible = false; });
            // CTV very translucent so seeds inside are visible
            _setFigureOneOpacity(ctvMesh, 0.12);
            // Seeds bright and opaque
            for (const [id, mesh] of Object.entries(scene3D.meshes)) {
                if (_isFigureOneSeed(id, mesh)) _setFigureOneOpacity(mesh, 1.0);
            }
            // Needles visible but thin
            for (const [id, mesh] of Object.entries(scene3D.meshes)) {
                if (_isFigureOneNeedle(id, mesh)) _setFigureOneOpacity(mesh, 0.8);
            }

            // The CTV is translucent, but depth testing can still hide a
            // needle from selected camera angles. Promote only treatment
            // geometry for this temporary publication capture; the complete
            // material and render state is restored in _restoreFigure1State.
            const promotePlanGeometry = (mesh, order) => {
                if (!mesh) return;
                mesh.renderOrder = order;
                mesh.traverse?.(child => {
                    child.renderOrder = order;
                    const materials = Array.isArray(child.material)
                        ? child.material : [child.material];
                    materials.forEach(material => {
                        if (!material) return;
                        material.depthTest = false;
                        material.depthWrite = false;
                        material.needsUpdate = true;
                    });
                });
            };
            for (const [id, mesh] of Object.entries(scene3D.meshes)) {
                if (_isFigureOneNeedle(id, mesh)) {
                    promotePlanGeometry(mesh, 2000);
                } else if (_isFigureOneSeed(id, mesh)) {
                    promotePlanGeometry(mesh, 2100);
                }
            }

            // Excluding the full needle shaft keeps the right panel a true
            // target close-up when a needle extends far outside the CTV.
            _frameCameraToBox(_computeFocusedPlanBox({ includeOars: false, includeNeedles: false }), 'detail');
            await _waitFrames(2);
            if (!isCurrentCapture()) return { stale: true };
            let imgB = await _capture3D('View B (translucent tumor)', REPORT_FIGURE_ASPECT);
            if (!imgB) {
                forceRender3DViewer();
                await _waitFrames(4);
                if (!isCurrentCapture()) return { stale: true };
                imgB = await _capture3D('View B (translucent tumor retry)', REPORT_FIGURE_ASPECT);
            }

            // Figure 1 is a semantic group, not a pre-composed bitmap. The
            // export layer lays out these native captures at full page width.
            if (imgA) _push(labels.lblFront, labels.capFront, imgA, 'report_fig1_global', {
                figureGroup: 'figure1', figureNumber: 1, subfigure: 'a', sortOrder: 1,
                captureRole: 'planning_overview',
                captureContract: REPORT_FIGURE_ONE_CAPTURE_CONTRACT,
            });
            if (imgB) _push(labels.lblInside, labels.capInside, imgB, 'report_fig1_closeup', {
                figureGroup: 'figure1', figureNumber: 1, subfigure: 'b', sortOrder: 2,
                captureRole: 'planning_closeup',
                captureContract: REPORT_FIGURE_ONE_CAPTURE_CONTRACT,
            });

            // Restore immediately on the normal path; the finally block
            // repeats this idempotently for any capture/composition error.
            _restoreFigure1State();
            await _waitFrames(2);
        } else {
            console.warn('[Report] Figure 1 skipped: 3D scene not ready', {
                camera: !!scene3D.camera, controls: !!scene3D.controls,
                renderer: !!scene3D.renderer, meshes: _meshCount
            });
        }
    } catch (e) { console.warn('[Report] Figure 1 (3D seed plan) capture failed:', e); }
    finally {
        // A blank WebGL capture, canvas error, or image decode failure must
        // never leave OAR meshes hidden. This was the cause of the post-report
        // flicker followed by a viewer containing only CTV/seeds/needles.
        try { _restoreFigure1State?.(); } catch (restoreError) {
            console.warn('[Report] Figure 1 state restore failed:', restoreError);
        }
        window.__reportCaptureActive = false;
        if (isCurrentCapture()) {
            try { window.syncSceneAppearanceFromDataTree?.({ preserveDoseTexture: !!state.doseTexture?.enabled }); } catch (_) {}
            try { _setReportStatus?.('3D viewer restored after report capture', 'info'); } catch (_) {}
        }
    }

    // ═══════════════════════════════════════════════════════════
    // FIGURE 2: DOSE + DVH — FIVE NATIVE SUBFIGURES
    //   Top row: Axial + Sagittal + Coronal CT with dose heatmap
    //            at peak dose voxel (3 views side by side)
    //   Bottom: DVH curve
    //   Combined into a single image
    // ═══════════════════════════════════════════════════════════
    if (!isCurrentCapture()) return { stale: true };
    try {
        // Check for dose data existence, NOT just visibility — the user may
        // not have toggled dose on yet, but we still need to capture it.
        const hasDose = state.doseOverlay && state.doseOverlay.peakVoxel
            && state.doseOverlay.shape;
        if (hasDose) {
            const pv = state.doseOverlay.peakVoxel;
            uiDebugLog('[Report] Figure 2: starting dose+DVH capture, peak voxel:', pv);

            // Save the operator's slices and visibility. Capture-specific
            // dose opacity is applied only by the offscreen compositor.
            const origSlices = {
                axial: state.slices.axial,
                sagittal: state.slices.sagittal,
                coronal: state.slices.coronal,
            };
            const origVisible = state.doseOverlay.visible;

            // Ensure dose data is rendered; do not change live opacity.
            state.doseOverlay.visible = true;

            // Navigate all 3 views to peak dose voxel
            const axesCfg = [
                { ax: 'axial', slice: pv.z, axis: 'report_fig2_axial', title: labels.lblAxial, caption: labels.capAxial, subfigure: 'a', order: 1 },
                { ax: 'sagittal', slice: pv.x, axis: 'report_fig2_sagittal', title: labels.lblSagittal, caption: labels.capSagittal, subfigure: 'b', order: 2 },
                { ax: 'coronal', slice: pv.y, axis: 'report_fig2_coronal', title: labels.lblCoronal, caption: labels.capCoronal, subfigure: 'c', order: 3 },
            ];
            for (const cfg of axesCfg) {
                const slider = document.getElementById('slider' + cfg.ax.charAt(0).toUpperCase() + cfg.ax.slice(1));
                const maxVal = slider ? parseInt(slider.max) : 200;
                const clampedSlice = Math.max(0, Math.min(maxVal, Math.round(cfg.slice)));
                if (slider) slider.value = clampedSlice;
                updateSlice(cfg.ax, clampedSlice);
            }
            // Wait for the requested peak-dose slice itself, not a fixed
            // number of animation frames. On a cache miss the canvas can
            // otherwise still contain the previous slice when captured.
            await Promise.all(axesCfg.map(cfg => _waitForReportDoseSlice(
                cfg.ax,
                Math.max(0, Math.min(
                    parseInt(document.getElementById('slider' + cfg.ax.charAt(0).toUpperCase() + cfg.ax.slice(1))?.max || '200'),
                    Math.round(cfg.slice),
                )),
            )));
            if (!isCurrentCapture()) return { stale: true };

            // Capture all 3 views
            for (const cfg of axesCfg) {
                const composite = _composite2DViewerCanvas(cfg.ax, { doseOpacity: 0.75 });
                if (composite) {
                    _push(cfg.title, cfg.caption, composite, cfg.axis, {
                        figureGroup: 'figure2', figureNumber: 2,
                        subfigure: cfg.subfigure, sortOrder: cfg.order,
                        captureRole: `peak_dose_${cfg.ax}`,
                        sliceIdx: Math.round(cfg.slice), peakVoxel: { ...pv },
                    });
                    uiDebugLog('[Report] Captured', cfg.title, 'dose view:', Math.round(composite.length / 1024), 'KB');
                }
            }

            let doseSurfaceDataUrl = null;
            let restoreDoseSurfaceState = null;
            try {
                const savedTextureMode = !!state.doseTexture.enabled;
                const savedCamera = scene3D.camera && scene3D.controls ? {
                    camera: scene3D.camera,
                    controls: scene3D.controls,
                    position: scene3D.camera.position.clone(),
                    quaternion: scene3D.camera.quaternion.clone(),
                    up: scene3D.camera.up.clone(),
                    near: scene3D.camera.near,
                    far: scene3D.camera.far,
                    aspect: scene3D.camera.aspect,
                    fov: scene3D.camera.fov,
                    zoom: scene3D.camera.zoom,
                    target: scene3D.controls.target.clone(),
                } : null;
                const savedVis = {};
                const savedOp = {};
                for (const [id, mesh] of Object.entries(scene3D.meshes || {})) {
                    if (!mesh) continue;
                    savedVis[id] = { mesh, visible: mesh.visible };
                    const surface = getMeshSurface(mesh);
                    if (surface?.material && !Array.isArray(surface.material)) {
                        savedOp[id] = { mesh, opacity: surface.material.opacity };
                    }
                }
                restoreDoseSurfaceState = async () => {
                    for (const [id, saved] of Object.entries(savedVis)) {
                        const mesh = saved?.mesh;
                        if (!mesh) continue;
                        mesh.visible = saved.visible;
                        if (savedOp[id] !== undefined) {
                            applyMeshOpacity(mesh, savedOp[id].opacity, saved.visible);
                        }
                    }
                    if (isCurrentCapture() && !savedTextureMode && state.doseTexture.enabled) {
                        await setDoseTextureMode(false, { silent: true });
                    }
                    if (isCurrentCapture() && savedCamera
                        && scene3D.camera === savedCamera.camera
                        && scene3D.controls === savedCamera.controls) {
                        if (typeof window.sync3DCameraPose === 'function') {
                            window.sync3DCameraPose({
                                position: savedCamera.position,
                                target: savedCamera.target,
                                quaternion: savedCamera.quaternion,
                                up: savedCamera.up,
                                near: savedCamera.near,
                                far: savedCamera.far,
                                aspect: savedCamera.aspect,
                                fov: savedCamera.fov,
                                zoom: savedCamera.zoom,
                            });
                        } else {
                            savedCamera.camera.position.copy(savedCamera.position);
                            savedCamera.camera.quaternion.copy(savedCamera.quaternion);
                            savedCamera.camera.up.copy(savedCamera.up);
                            savedCamera.controls.target.copy(savedCamera.target);
                            savedCamera.camera.near = savedCamera.near;
                            savedCamera.camera.far = savedCamera.far;
                            savedCamera.camera.aspect = savedCamera.aspect;
                            savedCamera.camera.fov = savedCamera.fov;
                            savedCamera.camera.zoom = savedCamera.zoom;
                            savedCamera.camera.updateProjectionMatrix();
                            savedCamera.controls.syncExternalState?.();
                        }
                    }
                    if (isCurrentCapture()) forceRender3DViewer();
                };
                await setDoseTextureMode(true, { silent: true });
                if (!isCurrentCapture()) return { stale: true };
                for (const [id, mesh] of Object.entries(scene3D.meshes || {})) {
                    if (!mesh) continue;
                    const isCtv = id === 'ctv' || id.startsWith('ctv_') || mesh?.userData?.type === 'ctv';
                    const isSeed = id.startsWith('seed_') || mesh?.userData?.type === 'seed';
                    const isNeedle = id.startsWith('needle_') || mesh?.userData?.type === 'needle';
                    mesh.visible = isCtv || isSeed || isNeedle;
                    if (isCtv) applyMeshOpacity(mesh, 0.92, true);
                }
                // Keep the dose-surface panel focused on the treatment region.
                // Whole-body OAR meshes can be very large, so including every
                // visible mesh here would either make the target unreadable or
                // leave the WebGL scene effectively empty after the camera is
                // moved. Include the CTV, seeds, needles, and only OARs that
                // overlap a padded CTV context.
                const box = new THREE.Box3();
                const ctvBox = new THREE.Box3();
                Object.entries(scene3D.meshes || {}).forEach(([id, mesh]) => {
                    if (!mesh || id.startsWith('dose_iso_')) return;
                    const isCtv = id === 'ctv' || id.startsWith('ctv_') || mesh?.userData?.type === 'ctv';
                    const isSeed = id.startsWith('seed_') || mesh?.userData?.type === 'seed';
                    // Needles remain visible, but their long external shafts do
                    // not define the close-up framing box.
                    if (isCtv || isSeed) {
                        mesh.visible = true;
                        try {
                            if (isCtv) ctvBox.expandByObject(mesh);
                            box.expandByObject(mesh);
                        } catch (_) {}
                    }
                });
                if (!ctvBox.isEmpty()) {
                    const ctvSize = ctvBox.getSize(new THREE.Vector3());
                    const context = ctvBox.clone().expandByScalar(Math.max(18, ctvSize.length() * 0.6));
                    Object.entries(scene3D.meshes || {}).forEach(([id, mesh]) => {
                        if (!mesh || typeof _isDoseTexturableMesh !== 'function'
                            || !_isDoseTexturableMesh(id, mesh)) return;
                        if (id === 'ctv' || id.startsWith('ctv_')) return;
                        const candidate = new THREE.Box3();
                        try { candidate.expandByObject(mesh); } catch (_) { return; }
                        if (!candidate.intersectsBox(context)) return;
                        const appearance = typeof window.getDataTreeAppearanceForMesh === 'function'
                            ? window.getDataTreeAppearanceForMesh(id, mesh) : null;
                        mesh.visible = appearance?.visible !== false;
                        const localCandidate = candidate.clone().intersect(context);
                        if (mesh.visible && !localCandidate.isEmpty()) box.union(localCandidate);
                    });
                }
                if (box.min.x < box.max.x && scene3D.camera && scene3D.controls) {
                    _frameReportCamera(box, {
                        direction: reportReferenceDirection,
                        targetAspect: REPORT_DOSE_SURFACE_ASPECT,
                        margin: 1.06,
                    });
                    // A WebGL canvas can contain a valid-looking, very large
                    // PNG even when the last frame was cleared to black. Force
                    // two committed frames and reject captures with no lit
                    // pixels so Figure 2 never embeds an apparent black panel.
                    async function captureDoseSurface3D(label) {
                        if (!isCurrentCapture()) return null;
                        const renderer = scene3D.renderer;
                        const canvas = renderer?.domElement;
                        if (!renderer || !canvas) return null;
                        const width = canvas.clientWidth || canvas.width;
                        const height = canvas.clientHeight || canvas.height;
                        if (!width || !height) return null;
                        scene3D.resize?.();
                        scene3D.renderNow?.();
                        await _waitFrames(2);
                        if (!isCurrentCapture()) return null;
                        scene3D.renderNow?.();
                        try {
                            const gl = renderer.getContext?.();
                            if (gl && canvas.width > 0 && canvas.height > 0) {
                                const pixel = new Uint8Array(4);
                                let hasLitPixel = false;
                                for (let gx = 1; gx <= 9 && !hasLitPixel; gx++) {
                                    for (let gy = 1; gy <= 9 && !hasLitPixel; gy++) {
                                        gl.readPixels(
                                            Math.floor(canvas.width * gx / 10),
                                            Math.floor(canvas.height * gy / 10),
                                            1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel,
                                        );
                                        hasLitPixel = pixel[0] > 4 || pixel[1] > 4 || pixel[2] > 4;
                                    }
                                }
                                if (!hasLitPixel) {
                                    console.warn('[Report] 3D dose-surface capture is black:', label);
                                    return null;
                                }
                            }
                            const url = _captureReportCanvasCrop(canvas, REPORT_DOSE_SURFACE_ASPECT);
                            if (!url || url.length < 5000) return null;
                            uiDebugLog('[Report] 3D dose-surface capture', label, ':', Math.round(url.length / 1024), 'KB');
                            return url;
                        } catch (captureError) {
                            console.warn('[Report] 3D dose-surface toDataURL failed:', captureError);
                            return null;
                        }
                    }
                    doseSurfaceDataUrl = await captureDoseSurface3D('primary');
                    if (!isCurrentCapture()) return { stale: true };
                    if (!doseSurfaceDataUrl) {
                        forceRender3DViewer();
                        await _waitFrames(5);
                        if (!isCurrentCapture()) return { stale: true };
                        doseSurfaceDataUrl = await captureDoseSurface3D('retry');
                    }
                }
                if (isCurrentCapture()) await restoreDoseSurfaceState();
                await _waitFrames(2);
            } catch (e) {
                console.warn('[Report] dose surface close-up capture failed:', e);
            } finally {
                try { await restoreDoseSurfaceState?.(); } catch (restoreError) {
                    console.warn('[Report] dose surface state restore failed:', restoreError);
                }
            }

            // Restore original slices and visibility.
            if (!isCurrentCapture()) return { stale: true };
            state.doseOverlay.visible = origVisible;
            for (const [ax, sl] of Object.entries(origSlices)) {
                const slider = document.getElementById('slider' + ax.charAt(0).toUpperCase() + ax.slice(1));
                if (slider) slider.value = sl;
                updateSlice(ax, sl);
            }
            await _waitFrames(2);
            if (!isCurrentCapture()) return { stale: true };

            // Capture DVH chart — try Plotly.toImage first, fallback to html2canvas
            let dvhDataUrl = null;
            const dvhEl = document.getElementById('dvhChart');
            if (dvhEl) {
                // Try Plotly export (vector-quality)
                if (typeof Plotly !== 'undefined' && typeof Plotly.toImage === 'function') {
                    try {
                        await new Promise(r => setTimeout(r, 500)); // let Plotly finish rendering
                        if (!isCurrentCapture()) return { stale: true };
                        dvhDataUrl = await Plotly.toImage(dvhEl, { format: 'png', width: 1200, height: 400 });
                        uiDebugLog('[Report] DVH captured via Plotly:', Math.round(dvhDataUrl.length / 1024), 'KB');
                    } catch (e) {
                        console.warn('[Report] Plotly.toImage failed:', e);
                    }
                }
                // Fallback: html2canvas
                if (!dvhDataUrl && typeof html2canvas !== 'undefined') {
                    try {
                        const canvas = await html2canvas(dvhEl, { useCORS: true, scale: 2 });
                        dvhDataUrl = canvas.toDataURL('image/png');
                        uiDebugLog('[Report] DVH captured via html2canvas:', Math.round(dvhDataUrl.length / 1024), 'KB');
                    } catch (e) {
                        console.warn('[Report] html2canvas DVH failed:', e);
                    }
                }
            }

            if (doseSurfaceDataUrl) _push(
                labels.lblDoseSurface, labels.capDoseSurface, doseSurfaceDataUrl,
                'report_fig2_dose_surface', {
                    figureGroup: 'figure2', figureNumber: 2, subfigure: 'd', sortOrder: 4,
                    captureRole: 'dose_surface_3d', peakVoxel: { ...pv },
                },
            );
            if (dvhDataUrl) _push(labels.lblDvh, labels.capDvh, dvhDataUrl, 'report_fig2_dvh', {
                figureGroup: 'figure2', figureNumber: 2, subfigure: 'e', sortOrder: 5,
                captureRole: 'dvh',
            });
        } else {
            console.warn('[Report] Figure 2 skipped: no dose overlay data', {
                hasOverlay: !!state.doseOverlay,
                hasPeakVoxel: !!(state.doseOverlay && state.doseOverlay.peakVoxel),
                hasShape: !!(state.doseOverlay && state.doseOverlay.shape),
                hasData: !!(state.doseOverlay && state.doseOverlay.data),
            });
        }
    } catch (e) { console.warn('[Report] Figure 2 (dose+DVH) capture failed:', e); }

    // Re-render editor + preview
    if (!isCurrentCapture()) return { stale: true };
    if (window.reportForm.figures.length > 0) {
        uiDebugLog('[Report] Total figures captured:', window.reportForm.figures.length);
        renderReportEditor(); _updateReportPreview(); _scheduleReportAutoSave();
    } else {
        console.warn('[Report] No figures were captured');
    }
}
