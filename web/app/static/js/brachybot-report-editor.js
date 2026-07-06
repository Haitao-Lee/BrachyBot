function escHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
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
            srcReset = `<span class="rp-source-reset" title="Reset to auto" onclick="Report.sources.resetTo('${opts.key.replace(/'/g, "\\'")}')">↻</span>`;
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
            ${_formField({key:'metrics.v100', label:'V100', value:f.metrics.v100, type:'number', step:'0.01', suffix:'%', hint:'CTV coverage ≥ 90 %'})}
            ${_formField({key:'metrics.d90', label:'D90', value:f.metrics.d90, type:'number', step:'0.01', suffix:'Gy', hint:'≥ 100 Gy prescription'})}
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
        ${_formField({key:'interpretation', label:s.section5 + ' (Markdown)', value:f.interpretation, type:'textarea', rows:5, section:'narrative'})}
        ${_formField({key:'safety', label:s.section6, value:f.safety, type:'textarea', rows:3, section:'narrative'})}
        ${_formField({key:'qaNotes', label:'QA Notes', value:f.qaNotes, type:'textarea', rows:2, section:'narrative'})}
    `);
    // References
    const refList = (f.references || []).map((r, i) => `
        <div class="rp-ref-card">
            <div class="rp-ref-body">
                <div><b>[${r.citeKey || `ref${i+1}`}]</b> ${escHtml(r.title || '')}</div>
                <div class="rp-ref-meta">${escHtml(r.publisher || '')}${r.year ? ', ' + r.year : ''}</div>
                ${r.url ? `<a href="${escHtml(r.url)}" target="_blank" rel="noopener">↗ Open</a>` : ''}
            </div>
            <button onclick="removeReportReference(${i})" class="btn btn-outline" style="height:22px;padding:0 6px;font-size:0.65rem;color:var(--danger);">✕</button>
        </div>`).join('');
    html += _formSection('📚 ' + s.section7 + ` (${(f.references || []).length})`, 'references', `
        <div>${refList || '<div class="rp-empty">—</div>'}</div>
        <details style="margin-top:6px;">
            <summary style="font-size:0.7rem;color:var(--primary);cursor:pointer;font-weight:500;">+ Add Reference</summary>
            <div style="margin-top:6px;padding:8px;background:var(--primary-soft);border:1px solid var(--primary);border-radius:var(--radius-xs);">
                <select onchange="if(this.value){addReportReferenceFromCatalog(this.value);this.value='';}" class="form-select" style="font-size:0.7rem;margin-bottom:5px;">
                    <option value="">— Select catalog reference —</option>
                    ${Object.values(REPORT_REFERENCES_CATALOG).map(r => `<option value="${r.citeKey}">[${r.citeKey}] ${r.title.substring(0, 70)}…</option>`).join('')}
                </select>
                <div style="font-size:0.65rem;color:var(--text-dim);margin:4px 0;">— or add custom —</div>
                <div style="display:grid;grid-template-columns:1fr 2fr;gap:6px;margin-bottom:5px;">
                    <input id="refCiteKey" placeholder="Cite key" class="form-input" style="font-size:0.7rem;"/>
                    <input id="refTitle" placeholder="Title" class="form-input" style="font-size:0.7rem;"/>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-top:5px;">
                    <input id="refPublisher" placeholder="Publisher" class="form-input" style="font-size:0.7rem;"/>
                    <input id="refYear" placeholder="Year" type="number" class="form-input" style="font-size:0.7rem;"/>
                    <input id="refJurisdiction" placeholder="Jurisdiction" class="form-input" style="font-size:0.7rem;"/>
                </div>
                <input id="refUrl" placeholder="URL" class="form-input" style="font-size:0.7rem;margin-top:5px;"/>
                <div class="rp-btn-row">
                    <button onclick="addReportReferenceCustom()" class="btn btn-primary">Add</button>
                </div>
            </div>
        </details>
    `);
    // Figures
    const figList = (f.figures || []).map((fig, i) => `
        <div class="rp-figure-card">
            <img src="${fig.dataUrl}" alt="${escHtml(fig.title || '')}"/>
            <div class="rp-figure-meta">
                <div style="font-weight:500;">${escHtml(fig.title || '(untitled)')}</div>
                <div class="rp-figure-sub">${fig.axis ? `${fig.axis} slice ${fig.sliceIdx ?? '?'}` : ''} · ${fig.capturedAt ? new Date(fig.capturedAt).toLocaleString() : ''}</div>
                ${fig.caption ? `<div class="rp-figure-sub" style="margin-top:1px;">${escHtml(fig.caption)}</div>` : ''}
            </div>
            <button onclick="removeReportFigure(${i})" class="btn btn-outline" style="height:22px;padding:0 6px;font-size:0.65rem;color:var(--danger);">✕</button>
        </div>
    `).join('');
    html += _formSection((s.figuresSectionTitle || '🖼️ Figures') + ' (' + (f.figures || []).length + ')', 'figures', `
        <div>${figList || '<div class="rp-empty">—</div>'}</div>
        <div class="rp-btn-row">
            <button class="btn btn-outline" onclick="captureReportFigure2D()">📷 Capture 2D</button>
            <button class="btn btn-outline" onclick="captureReportFigure3D()">📷 Capture 3D</button>
            <label class="btn btn-outline" style="cursor:pointer;">
                📁 Upload
                <input type="file" accept="image/*" onchange="uploadReportFigure(event)" style="display:none;"/>
            </label>
        </div>
    `);
    // Signature
    html += _formSection('✍️ ' + s.section9, 'signature', `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            ${_formField({key:'signature.name', label:s.name, value:f.signature.name, section:'signature'})}
            ${_formField({key:'signature.title', label:s.title, value:f.signature.title, section:'signature'})}
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
    if (!window.reportForm.references) window.reportForm.references = [];
    window.reportForm.references.push({
        citeKey, title,
        publisher: document.getElementById('refPublisher').value.trim(),
        year: parseInt(document.getElementById('refYear').value) || null,
        jurisdiction: document.getElementById('refJurisdiction').value.trim(),
        url: document.getElementById('refUrl').value.trim(),
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
    const reader = new FileReader();
    reader.onload = (e) => {
        const fig = { type: 'upload', title: file.name, dataUrl: e.target.result, caption: '', capturedAt: new Date().toISOString() };
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
// FIGURE 1: 3D Seed Implant Plan (composite)
//   Left:  Front-facing panoramic with all OARs (semi-transparent),
//          needle paths (red), radioactive seeds (yellow), CTV
//   Right: Camera aimed at translucent CTV tumor showing internal
//          3D seed distribution
//
// FIGURE 2: Dose Distribution & DVH (composite)
//   Top:   Axial / Sagittal / Coronal CT with dose heatmap at
//          peak dose voxel, arranged in a row
//   Bottom: DVH curve (CTV + OARs)
async function autoCaptureReportFigures() {
    console.log('[Report] autoCaptureReportFigures called');
    if (!window.reportForm) { console.warn('[Report] No reportForm, skipping'); return; }
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
        console.log('[Report] Figures already exist:', window.reportForm.figures.length, '- skipping');
        return;
    }
    console.log('[Report] Starting capture, 3D meshes:', Object.keys(scene3D.meshes).length,
        'doseOverlay:', !!state.doseOverlay, 'dvhData:', !!state.dvhData);

    // Language-aware labels
    const _f = window.reportForm;
    const lang = (typeof window._i18nLang === 'string') ? window._i18nLang : ((_f && _f.language) || 'en');
    const labels = (lang === 'zh') ? {
        seed3d: '粒子植入方案',
        seed3dCap: '左：正面全景含穿刺针道（红色）、放射性粒子（黄色）、CTV 及所有危及器官；右：半透明 CTV 肿瘤内部三维粒子分布',
        doseDvh: '剂量分布与DVH',
        doseDvhCap: '上方：最大剂量层面轴位/矢状位/冠状位 CT 叠加剂量热图；下方：CTV 及各 OAR 的剂量-体积曲线',
        lblFront: '正面全景（含危及器官）',
        lblInside: '半透明肿瘤内部（粒子分布）',
        lblAxial: '轴位', lblSagittal: '矢状位', lblCoronal: '冠状位',
    } : {
        seed3d: 'Seed Implant Plan',
        seed3dCap: 'Left: Front view with Data Tree-matched colors for CTV/tumor, OARs, needle paths, and seeds; Right: translucent CTV showing internal 3D seed distribution. Legend colors match the Data Tree.',
        doseDvh: 'Dose Distribution & DVH',
        doseDvhCap: '(a) Axial, (b) Sagittal, and (c) Coronal CT slices with dose heatmap at the peak-dose voxel; (d) CTV/OAR dose surface close-up; (e) dose-volume histogram for CTV and OARs.',
        lblFront: 'Front view (with OARs)',
        lblInside: 'Translucent tumor (seed distribution)',
        lblAxial: 'Axial', lblSagittal: 'Sagittal', lblCoronal: 'Coronal',
        lblDoseSurface: 'CTV/OAR dose surface',
    };

    const _ts = () => new Date().toISOString();
    const _push = (title, caption, dataUrl, axis, extra) => {
        if (!dataUrl || dataUrl.length < 1000) {
            console.warn('[Report] Figure skipped: dataUrl too short or null');
            return;
        }
        window.reportForm.figures.push({
            type: 'screenshot', title, dataUrl, axis: axis || '3d',
            sliceIdx: null, caption, capturedAt: _ts(), ...extra,
        });
        console.log('[Report] Figure captured:', title, Math.round(dataUrl.length / 1024), 'KB');
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
        const ctvColor = dataTreeState.ctv?.color || '#ef4444';
        items.push({ type: 'swatch', color: ctvColor, label: 'CTV / tumor' });
        const firstOar = (dataTreeState.organs || []).find(o => o.visible !== false) || dataTreeState.organs?.[0];
        items.push({ type: 'swatch', color: firstOar?.color || dataTreeState.oar?.color || '#22c55e', label: 'OAR surfaces' });
        items.push({ type: 'seed', color: dataTreeState.planning?.seeds?.[0]?.color || dataTreeState.seeds?.color || '#ffcc00', label: 'I-125 seeds' });
        items.push({ type: 'needle', color: dataTreeState.planning?.needles?.[0]?.color || dataTreeState.needles?.color || '#ff2266', label: 'Needle paths' });
        items.push({ type: 'gradient', label: 'Dose surface: <10 to >200 Gy' });

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

    // ═══════════════════════════════════════════════════════════
    // FIGURE 1: 3D SEED IMPLANT PLAN — COMPOSITE
    //   Left: Front-facing with all OARs + needles + seeds
    //   Right: Translucent tumor showing seeds inside
    //   Combined into a single side-by-side image
    // ═══════════════════════════════════════════════════════════
    try {
        const _meshCount = Object.keys(scene3D.meshes).length;
        if (scene3D.camera && scene3D.controls && scene3D.renderer && _meshCount > 0) {
            console.log('[Report] Figure 1: starting 3D capture, meshes:', _meshCount);

            // Save all visibility and opacity states
            const _saved = {};
            const _savedOpacities = {};
            for (const [id, mesh] of Object.entries(scene3D.meshes)) {
                if (!mesh) continue;
                _saved[id] = mesh.visible;
                if (mesh.material) _savedOpacities[id] = mesh.material.opacity;
            }

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

            function _computeFocusedPlanBox({ includeOars = false } = {}) {
                const box = new THREE.Box3();
                const expandMesh = (mesh) => {
                    if (!mesh || !mesh.visible) return;
                    try { box.expandByObject(mesh); } catch (_) {}
                };
                for (const [id, mesh] of Object.entries(scene3D.meshes)) {
                    if (!mesh) continue;
                    const isCtv = id === 'ctv' || id.startsWith('ctv_') || mesh?.userData?.source === 'ctv' || mesh?.userData?.type === 'ctv';
                    const isSeed = id.startsWith('seed_') || mesh?.userData?.type === 'seed';
                    const isNeedle = id.startsWith('needle_') || mesh?.userData?.type === 'needle';
                    const isDose = id.startsWith('dose_iso_') || mesh?.userData?.type === 'dose_isosurface';
                    const isSkin = id === 'skin' || mesh === scene3D.skinMesh || mesh?.userData?.type === 'skin';
                    const isOar = !isCtv && !isSeed && !isNeedle && !isDose && !isSkin;
                    if (isCtv || isSeed || isNeedle || (includeOars && isOar)) expandMesh(mesh);
                }
                if (!(box.min.x < box.max.x)) return _computeSceneBox();
                return box;
            }

            function _frameCameraToBox(box, mode) {
                if (!(box && box.min.x < box.max.x) || !scene3D.camera || !scene3D.controls) return;
                const center = box.getCenter(new THREE.Vector3());
                const size = box.getSize(new THREE.Vector3());
                const maxDim = Math.max(size.x, size.y, size.z, 1);
                const fov = (scene3D.camera.fov || 45) * Math.PI / 180;
                const padding = mode === 'detail' ? 1.25 : 1.55;
                const dist = (maxDim * padding) / (2 * Math.tan(fov / 2));
                const dir = mode === 'detail'
                    ? new THREE.Vector3(0.55, -0.25, 0.8).normalize()
                    : new THREE.Vector3(0.35, -0.55, 0.76).normalize();
                scene3D.controls.target.copy(center);
                scene3D.camera.position.copy(center.clone().add(dir.multiplyScalar(dist)));
                scene3D.camera.near = Math.max(0.1, dist / 100);
                scene3D.camera.far = Math.max(2000, dist * 20);
                scene3D.camera.updateProjectionMatrix();
                scene3D.controls.update();
            }

            // Helper: render and capture 3D canvas
            async function _capture3D(label) {
                await _waitFrames(3);
                scene3D.renderer.render(scene3D.scene, scene3D.camera);
                await _waitFrames(2);
                // The actual WebGL canvas is scene3D.renderer.domElement (child of #canvas3D)
                const c = scene3D.renderer.domElement;
                if (!c) { console.warn('[Report] 3D canvas not found for', label); return null; }
                try {
                    const url = c.toDataURL('image/png');
                    console.log('[Report] 3D capture', label, ':', Math.round(url.length / 1024), 'KB');
                    return url;
                } catch (e) {
                    console.warn('[Report] 3D toDataURL failed:', e);
                    return null;
                }
            }

            // ── View A: Front-facing with all OARs ──
            // Show everything
            for (const [id, mesh] of Object.entries(scene3D.meshes)) {
                if (mesh) mesh.visible = true;
            }
            // OARs semi-transparent (not seeds, needles, dose, or CTV)
            for (const [id, mesh] of Object.entries(scene3D.meshes)) {
                if (mesh?.material && !id.startsWith('seed_') && !id.startsWith('needle_')
                    && !id.startsWith('dose_iso_') && !id.startsWith('ctv_') && id !== 'ctv') {
                    mesh.material.opacity = 0.15;
                    mesh.material.transparent = true;
                }
            }
            // CTV semi-transparent
            const ctvMesh = scene3D.meshes['ctv']
                || Object.values(scene3D.meshes).find(m => m?.userData?.source === 'ctv');
            if (ctvMesh?.material) { ctvMesh.material.opacity = 0.3; ctvMesh.material.transparent = true; }

            _frameCameraToBox(_computeFocusedPlanBox({ includeOars: true }), 'overview');
            await _waitFrames(2);
            const imgA = await _capture3D('View A (front+OARs)');

            // ── View B: Translucent tumor, seeds visible inside ──
            // Hide non-essential OARs, keep CTV + seeds + needles only
            for (const [id, mesh] of Object.entries(scene3D.meshes)) {
                if (!mesh) continue;
                const isCtv = id === 'ctv' || id.startsWith('ctv_');
                const isSeed = id.startsWith('seed_');
                const isNeedle = id.startsWith('needle_');
                mesh.visible = isCtv || isSeed || isNeedle;
            }
            // CTV very translucent so seeds inside are visible
            if (ctvMesh?.material) { ctvMesh.material.opacity = 0.12; ctvMesh.material.transparent = true; }
            // Seeds bright and opaque
            for (const [id, mesh] of Object.entries(scene3D.meshes)) {
                if (id.startsWith('seed_') && mesh?.material) { mesh.material.opacity = 1.0; }
            }
            // Needles visible but thin
            for (const [id, mesh] of Object.entries(scene3D.meshes)) {
                if (id.startsWith('needle_') && mesh?.material) { mesh.material.opacity = 0.8; }
            }

            _frameCameraToBox(_computeFocusedPlanBox({ includeOars: false }), 'detail');
            await _waitFrames(2);
            const imgB = await _capture3D('View B (translucent tumor)');

            // ── Composite: side by side ──
            if (imgA || imgB) {
                const W = 1200, halfW = 560, gap = 40, titleH = 44, labelH = 28, legendH = 66, pad = 20;
                const compCanvas = document.createElement('canvas');
                compCanvas.width = W;
                compCanvas.height = titleH + pad + halfW + labelH + legendH;
                const ctx = compCanvas.getContext('2d');

                // Background
                ctx.fillStyle = '#0f172a';
                ctx.fillRect(0, 0, W, compCanvas.height);

                // Title
                ctx.fillStyle = '#e2e8f0';
                ctx.font = 'bold 16px Inter, system-ui, sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(labels.seed3d, W / 2, 30);

                // Draw View A (left)
                await _drawImg(ctx, imgA, pad, titleH, halfW, halfW);
                _drawLabel(ctx, labels.lblFront, pad + halfW / 2, titleH + halfW + 18, halfW);

                // Draw View B (right)
                await _drawImg(ctx, imgB, pad + halfW + gap, titleH, halfW, halfW);
                _drawLabel(ctx, labels.lblInside, pad + halfW + gap + halfW / 2, titleH + halfW + 18, halfW);

                // Thin separator line between views
                ctx.strokeStyle = 'rgba(148,163,184,0.2)';
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(W / 2, titleH + 10);
                ctx.lineTo(W / 2, titleH + halfW - 10);
                ctx.stroke();

                _drawPlanLegend(ctx, pad, titleH + halfW + labelH + 6, W - pad * 2);

                _push(labels.seed3d, labels.seed3dCap, compCanvas.toDataURL('image/png'), '3d_seeds');
            }

            // Restore all states
            for (const [id, mesh] of Object.entries(scene3D.meshes)) {
                if (!mesh) continue;
                if (_saved[id] !== undefined) mesh.visible = _saved[id];
                if (mesh.material && _savedOpacities[id] !== undefined) mesh.material.opacity = _savedOpacities[id];
            }
            fitCameraToScene();
            await _waitFrames(2);
        } else {
            console.warn('[Report] Figure 1 skipped: 3D scene not ready', {
                camera: !!scene3D.camera, controls: !!scene3D.controls,
                renderer: !!scene3D.renderer, meshes: _meshCount
            });
        }
    } catch (e) { console.warn('[Report] Figure 1 (3D seed plan) capture failed:', e); }

    // ═══════════════════════════════════════════════════════════
    // FIGURE 2: DOSE + DVH COMPOSITE
    //   Top row: Axial + Sagittal + Coronal CT with dose heatmap
    //            at peak dose voxel (3 views side by side)
    //   Bottom: DVH curve
    //   Combined into a single image
    // ═══════════════════════════════════════════════════════════
    try {
        // Check for dose data existence, NOT just visibility — the user may
        // not have toggled dose on yet, but we still need to capture it.
        const hasDose = state.doseOverlay && state.doseOverlay.peakVoxel
            && state.doseOverlay.shape;
        if (hasDose) {
            const pv = state.doseOverlay.peakVoxel;
            console.log('[Report] Figure 2: starting dose+DVH capture, peak voxel:', pv);

            // Save original slices and opacity
            const origSlices = {
                axial: state.slices.axial,
                sagittal: state.slices.sagittal,
                coronal: state.slices.coronal,
            };
            const origOpacity = state.doseOverlay.opacity;
            const origVisible = state.doseOverlay.visible;

            // Ensure dose overlay is visible and high opacity for screenshot
            state.doseOverlay.visible = true;
            state.doseOverlay.opacity = 0.75;

            // Navigate all 3 views to peak dose voxel
            const axesCfg = [
                { ax: 'axial', slice: pv.z, cap: labels.lblAxial },
                { ax: 'sagittal', slice: pv.x, cap: labels.lblSagittal },
                { ax: 'coronal', slice: pv.y, cap: labels.lblCoronal },
            ];
            for (const cfg of axesCfg) {
                const slider = document.getElementById('slider' + cfg.ax.charAt(0).toUpperCase() + cfg.ax.slice(1));
                const maxVal = slider ? parseInt(slider.max) : 200;
                const clampedSlice = Math.max(0, Math.min(maxVal, Math.round(cfg.slice)));
                if (slider) slider.value = clampedSlice;
                updateSlice(cfg.ax, clampedSlice);
            }
            // Wait for all 3 views + dose overlay to render
            await _waitFrames(8);

            // Capture all 3 views
            const doseImages = [];
            for (const cfg of axesCfg) {
                const composite = _composite2DViewerCanvas(cfg.ax);
                if (composite) {
                    doseImages.push({ dataUrl: composite, label: cfg.cap });
                    console.log('[Report] Captured', cfg.cap, 'dose view:', Math.round(composite.length / 1024), 'KB');
                }
            }

            let doseSurfaceDataUrl = null;
            try {
                const savedTextureMode = !!state.doseTexture.enabled;
                await setDoseTextureMode(true, { silent: true });
                const savedVis = {};
                const savedOp = {};
                for (const [id, mesh] of Object.entries(scene3D.meshes || {})) {
                    if (!mesh) continue;
                    savedVis[id] = mesh.visible;
                    const surface = getMeshSurface(mesh);
                    if (surface?.material && !Array.isArray(surface.material)) savedOp[id] = surface.material.opacity;
                    const isCtv = id === 'ctv' || id.startsWith('ctv_') || mesh?.userData?.type === 'ctv';
                    const isSeed = id.startsWith('seed_') || mesh?.userData?.type === 'seed';
                    const isNeedle = id.startsWith('needle_') || mesh?.userData?.type === 'needle';
                    mesh.visible = isCtv || isSeed || isNeedle;
                    if (isCtv) applyMeshOpacity(mesh, 0.92, true);
                }
                const box = new THREE.Box3();
                Object.entries(scene3D.meshes || {}).forEach(([id, mesh]) => {
                    if (!mesh || !mesh.visible) return;
                    if (id.startsWith('dose_iso_')) return;
                    try { box.expandByObject(mesh); } catch (_) {}
                });
                if (box.min.x < box.max.x && scene3D.camera && scene3D.controls) {
                    const center = box.getCenter(new THREE.Vector3());
                    const size = box.getSize(new THREE.Vector3());
                    const maxDim = Math.max(size.x, size.y, size.z, 1);
                    const fov = (scene3D.camera.fov || 45) * Math.PI / 180;
                    const dist = (maxDim * 1.2) / (2 * Math.tan(fov / 2));
                    const dir = new THREE.Vector3(0.5, -0.25, 0.82).normalize();
                    scene3D.controls.target.copy(center);
                    scene3D.camera.position.copy(center.clone().add(dir.multiplyScalar(dist)));
                    scene3D.camera.near = Math.max(0.1, dist / 100);
                    scene3D.camera.far = Math.max(2000, dist * 20);
                    scene3D.camera.updateProjectionMatrix();
                    scene3D.controls.update();
                    await _waitFrames(4);
                    scene3D.renderer.render(scene3D.scene, scene3D.camera);
                    doseSurfaceDataUrl = scene3D.renderer.domElement.toDataURL('image/png');
                }
                for (const [id, vis] of Object.entries(savedVis)) {
                    const mesh = scene3D.meshes[id];
                    if (!mesh) continue;
                    mesh.visible = vis;
                    if (savedOp[id] !== undefined) applyMeshOpacity(mesh, savedOp[id], vis);
                }
                if (!savedTextureMode) await setDoseTextureMode(false, { silent: true });
                fitCameraToScene();
                await _waitFrames(2);
            } catch (e) {
                console.warn('[Report] dose surface close-up capture failed:', e);
            }

            // Restore original slices and opacity
            state.doseOverlay.opacity = origOpacity;
            state.doseOverlay.visible = origVisible;
            for (const [ax, sl] of Object.entries(origSlices)) {
                const slider = document.getElementById('slider' + ax.charAt(0).toUpperCase() + ax.slice(1));
                if (slider) slider.value = sl;
                updateSlice(ax, sl);
            }
            await _waitFrames(2);

            // Capture DVH chart — try Plotly.toImage first, fallback to html2canvas
            let dvhDataUrl = null;
            const dvhEl = document.getElementById('dvhChart');
            if (dvhEl) {
                // Try Plotly export (vector-quality)
                if (typeof Plotly !== 'undefined' && typeof Plotly.toImage === 'function') {
                    try {
                        await new Promise(r => setTimeout(r, 500)); // let Plotly finish rendering
                        dvhDataUrl = await Plotly.toImage(dvhEl, { format: 'png', width: 1200, height: 400 });
                        console.log('[Report] DVH captured via Plotly:', Math.round(dvhDataUrl.length / 1024), 'KB');
                    } catch (e) {
                        console.warn('[Report] Plotly.toImage failed:', e);
                    }
                }
                // Fallback: html2canvas
                if (!dvhDataUrl && typeof html2canvas !== 'undefined') {
                    try {
                        const canvas = await html2canvas(dvhEl, { useCORS: true, scale: 2 });
                        dvhDataUrl = canvas.toDataURL('image/png');
                        console.log('[Report] DVH captured via html2canvas:', Math.round(dvhDataUrl.length / 1024), 'KB');
                    } catch (e) {
                        console.warn('[Report] html2canvas DVH failed:', e);
                    }
                }
            }

            // Compose into single image
            if (doseImages.length > 0 || doseSurfaceDataUrl || dvhDataUrl) {
                const W = 1400;
                const pad = 24;
                const gap = 14;
                const titleH = 48;
                const colorbarW = 78;
                const topPanelCount = 4;
                const viewW = Math.floor((W - pad * 2 - gap * (topPanelCount - 1) - colorbarW - gap) / topPanelCount);
                const viewH = 270;
                const dvhH = 370;
                const dvhYPad = 44;

                const compositeCanvas = document.createElement('canvas');
                compositeCanvas.width = W;
                compositeCanvas.height = titleH + viewH + gap + dvhYPad + dvhH + pad;
                const ctx = compositeCanvas.getContext('2d');

                // Background
                ctx.fillStyle = '#0f172a';
                ctx.fillRect(0, 0, compositeCanvas.width, compositeCanvas.height);

                // Title
                ctx.fillStyle = '#e2e8f0';
                ctx.font = 'bold 16px Inter, system-ui, sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(labels.doseDvh, W / 2, 30);

                // Draw dose views + 3D dose surface in uniform panels (top)
                const panelLabels = [
                    labels.lblAxial || 'Axial',
                    labels.lblSagittal || 'Sagittal',
                    labels.lblCoronal || 'Coronal',
                    labels.lblDoseSurface || 'CTV/OAR dose surface',
                ];
                const topPanels = doseImages.slice(0, 3);
                if (doseSurfaceDataUrl) topPanels.push({ dataUrl: doseSurfaceDataUrl, label: labels.lblDoseSurface || 'CTV/OAR dose surface' });
                for (let i = 0; i < topPanels.length; i++) {
                    const entry = topPanels[i];
                    const xPos = pad + i * (viewW + gap);
                    await _drawFigurePanel(ctx, entry.dataUrl, xPos, titleH, viewW, viewH, String.fromCharCode(97 + i), panelLabels[i] || entry.label);
                }
                _drawDoseColorbar(ctx, W - pad - colorbarW, titleH, colorbarW, viewH, 'Dose (Gy)');

                // Draw thin separator line
                const sepY = titleH + viewH + gap;
                ctx.strokeStyle = 'rgba(148,163,184,0.15)';
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(pad, sepY);
                ctx.lineTo(W - pad, sepY);
                ctx.stroke();

                // DVH section label
                ctx.fillStyle = '#64748b';
                ctx.font = '11px Inter, system-ui, sans-serif';
                ctx.textAlign = 'left';
                ctx.fillText('(e) DVH - Dose Volume Histogram', pad, sepY + 20);

                // Draw DVH chart (bottom)
                const dvhY = sepY + dvhYPad;
                if (dvhDataUrl) {
                    await _drawFigurePanel(ctx, dvhDataUrl, pad, dvhY, W - pad * 2, dvhH, 'e', 'Dose-volume histogram');
                } else {
                    // No DVH available — draw placeholder
                    ctx.fillStyle = 'rgba(148,163,184,0.1)';
                    ctx.fillRect(pad, dvhY, W - pad * 2, dvhH);
                    ctx.fillStyle = '#64748b';
                    ctx.font = '14px Inter, system-ui, sans-serif';
                    ctx.textAlign = 'center';
                    ctx.fillText('DVH chart not available', W / 2, dvhY + dvhH / 2);
                }

                _push(labels.doseDvh, labels.doseDvhCap, compositeCanvas.toDataURL('image/png'), 'dose_dvh_composite');
            }
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
    if (window.reportForm.figures.length > 0) {
        console.log('[Report] Total figures captured:', window.reportForm.figures.length);
        renderReportEditor(); _updateReportPreview(); _scheduleReportAutoSave();
    } else {
        console.warn('[Report] No figures were captured');
    }
}
