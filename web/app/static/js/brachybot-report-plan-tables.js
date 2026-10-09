// Shared report table presentation. Persist numerical facts; localize at render.
function _reportTableContext(form = window.reportForm) {
    const planning = typeof dataTreeState !== 'undefined' ? dataTreeState?.planning : null;
    const version = planning?.version;
    return {
        planningId: String(planning?.activePlanningId || planning?.id
            || (typeof activeReportPlanningId === 'function' ? activeReportPlanningId() : '')
            || window.state?.dvhPlanningId || form?.planningId || ''),
        version: version !== null && version !== undefined && Number.isFinite(Number(version)) ? Number(version) : null,
    };
}

function _reportTableNumber(value, digits = 2) {
    return value !== null && value !== undefined && value !== '' && typeof value !== 'boolean' && Number.isFinite(Number(value))
        ? Number(value).toFixed(digits) : '—';
}

function _reportTablePoint(value) {
    return Array.isArray(value) && value.length === 3 && value.every(v => v !== null && v !== '' && typeof v !== 'boolean' && Number.isFinite(Number(v)))
        ? '[' + value.map(v => Number(v).toFixed(2)).join(', ') + ']' : '—';
}

function _reportTableText(language) {
    return language === 'zh' ? {
        title: '针道与粒子位置明细', start: '起点：皮肤入点', end: '终点：针道末端',
        length: '皮肤至末端的轴向长度', channel: '针道', seed: '粒子', depth: '距针尖末端',
        gap: '轴向间距', offset: '离轴偏差', position: '实际位置 XYZ', status: '几何记录',
        noPrevious: '不适用', noPreviousNote: '最靠近针尖的首颗粒子没有上一颗粒子，间距不适用。',
        empty: '尚无已保存的针道/粒子几何。生成或保存规划后重新填充报告。',
        missingEntry: '未能确认皮肤入点；不以外部拖拽端点代替。针轴有效时，距针尖的距离仍可记录。',
        mismatch: '本表属于其他规划版本，请重新生成报告；未展示旧位置为当前结果。',
        unassigned: '未能唯一关联针道的粒子', recorded: '已记录',
        note: '坐标为已保存计划的患者物理 XYZ 坐标，单位 mm；保留原坐标系，不作显示坐标变换。以针尖末端为 0，从针尖沿针轴向皮肤方向量至粒子中心，按距针尖由近到远排列。负值表示超出针尖，不取绝对值；间距为相邻粒子中心的轴向间距，并非表面间隙。离轴超过 0.10 mm 仅作几何复核提示，不是临床验收阈值。',
        sampled: '皮肤入点沿用已保存导板皮肤包络，按原导板入点算法采样；不是对手术实际入点的测量。',
        priorityNote: '排序为复核优先级：有来源的可比限值需复核项 → 病例指定顺序 → 部位规范关注器官及可比限值占比 → 观测 D₂cc/Dmax。无适用限值时不声称临床重要性或超限；自动表列出全部可读取的器官，零值与缺失值区分。',
        basis: { criterion_review: '记录限值需复核', case_priority: '病例指定优先', constraint_utilization: '可比限值占比', site_criterion: '部位规范关注器官', observed_dose: '观测剂量排序', unassessed: '剂量未评估', manual_edit: '手动报告记录，未自动重排' },
        flags: { duplicate_seed_identity: '粒子 ID 重复', invalid_position: '位置无效', ambiguous_or_missing_owner: '针道归属不明确', off_axis: '离轴需复核', outside_insertion_span: '位于入针范围外', needle_axis_unavailable: '针轴未确认' },
        continuation: '续表', volume: '体积', organ: '器官', reviewBasis: '复核排序依据', reference: '记录参考', stale: '剂量为过期参考，不作当前限值比较',
        incomplete: '结构/剂量尚未全部就绪；下表不是已核验完整的器官清单。',
        coordinates: { patient_world_lps: '患者 LPS 物理坐标系（左、后、上）', patient_world_mm: '已保存的患者物理坐标系' },
        reasons: { saved_skin_unavailable: '没有可核验的已保存皮肤包络', invalid_needle_geometry: '针道几何无效', duplicate_needle_identity: '针道 ID 重复', truncated_ct_entry: '入点位于截断的 CT 边界', invalid_skin_entry: '皮肤入点无效', skin_entry_off_axis: '皮肤入点偏离针轴', skin_entry_outside_segment: '皮肤入点位于针道线段外' },
    } : {
        title: 'Needle and Seed Position Schedule', start: 'Start: skin entry', end: 'End: needle tip',
        length: 'Axial skin-to-tip length', channel: 'Needle', seed: 'Seed', depth: 'From needle tip',
        gap: 'Axial spacing', offset: 'Axis offset', position: 'Actual XYZ position', status: 'Geometry record',
        noPrevious: 'N/A', noPreviousNote: 'The first seed nearest the tip has no preceding seed; spacing is not applicable.',
        empty: 'No saved needle/seed geometry is available. Generate or save the plan and refill the report.',
        missingEntry: 'Skin entry could not be confirmed. External drag handles are not substituted. Tip distances remain available when the needle axis is valid.',
        mismatch: 'This table belongs to another planning revision. Regenerate the report; old positions are not shown as current.',
        unassigned: 'Seeds without a unique owning needle', recorded: 'Recorded',
        note: 'Coordinates are the saved plan\'s physical patient XYZ coordinates in mm; the original coordinate system is retained, without a display transform. Needle tip is zero. Distances run back along the needle axis toward skin to each seed center, sorted nearest tip first. Negative values lie beyond the tip and are not converted to absolute values. Spacing is axial center-to-center spacing, not surface clearance. Axis offsets above 0.10 mm are geometry-review flags, not clinical acceptance thresholds.',
        sampled: 'Skin entry is sampled from the saved guide skin envelope using the original guide entry algorithm, not measured intraoperatively.',
        priorityNote: 'Review ordering: source-backed comparable criterion review → case-specified order → site-criterion organs and comparable limit utilization → observed D₂cc/Dmax. Without applicable criteria, no clinical importance or over-limit claim is made. Automatic tables include every readable organ; zero and missing values remain distinct.',
        basis: { criterion_review: 'Recorded criterion review', case_priority: 'Case-specified priority', constraint_utilization: 'Comparable limit utilization', site_criterion: 'Site-criterion organ', observed_dose: 'Observed-dose ordering', unassessed: 'Dose unassessed', manual_edit: 'Manual report record; order not recomputed' },
        flags: { duplicate_seed_identity: 'Duplicate seed ID', invalid_position: 'Invalid position', ambiguous_or_missing_owner: 'Uncertain needle ownership', off_axis: 'Off-axis: review', outside_insertion_span: 'Outside insertion span', needle_axis_unavailable: 'Needle axis unconfirmed' },
        continuation: 'continued', volume: 'Volume', organ: 'Organ', reviewBasis: 'Review-order basis', reference: 'Recorded reference', stale: 'Dose is a stale reference; no current limit comparison',
        incomplete: 'Structure/dose loading or assessment is incomplete; the table is not a verified complete organ inventory.',
        coordinates: { patient_world_lps: 'Patient LPS physical coordinates (left, posterior, superior)', patient_world_mm: 'Saved patient physical coordinates' },
        reasons: { saved_skin_unavailable: 'No verifiable saved skin envelope', invalid_needle_geometry: 'Invalid needle geometry', duplicate_needle_identity: 'Duplicate needle ID', truncated_ct_entry: 'Entry at a truncated CT boundary', invalid_skin_entry: 'Invalid skin entry', skin_entry_off_axis: 'Skin entry is off axis', skin_entry_outside_segment: 'Skin entry is outside the needle segment' },
    };
}

function _reportOarRowsFromMetrics(metrics, units) {
    return Object.entries(metrics || {}).filter(([, x]) => x && typeof x === 'object').map(([name, x]) => {
        const row = { ...x, organ: typeof _resolveOARDisplayName === 'function' ? _resolveOARDisplayName(name, x) : name };
        row.dmax = x.dmax ?? x.max_dose ?? null;
        row.dmean = x.dmean ?? x.mean_dose ?? null;
        for (const key of ['d2cc', 'd1cc', 'd0_1cc', 'd90', 'd95', 'volume_cm3']) row[key] = x[key] ?? null;
        row.v100 = _oarVolumePercent(x.v100, x.volume_metric_units || units);
        row.importance_basis = 'observed_dose';
        return row;
    }).sort((a, b) => (b.d2cc ?? -1) - (a.d2cc ?? -1) || (b.dmax ?? -1) - (a.dmax ?? -1) || a.organ.localeCompare(b.organ));
}

function _reportOarNameCell(row, language, includeBasis = true) {
    const text = _reportTableText(language);
    const name = typeof _resolveOARDisplayName === 'function' ? _resolveOARDisplayName(row.organ, row) : row.organ;
    const color = typeof _getOrganColor === 'function' ? _getOrganColor(row.organ, row) : '#374151';
    const safeColor = /^(#[0-9a-f]{3,8}|rgba?\([0-9.,%\s]+\))$/i.test(String(color)) ? color : '#374151';
    const reference = row.reference_metric && row.reference_limit_gy != null
        ? `${row.reference_metric} ≤ ${_reportTableNumber(row.reference_limit_gy)} Gy; ${_reportTableNumber((row.constraint_utilization ?? 0) * 100, 1)}%` : '';
    return `<span class="hp-organ-name" style="border-left:3px solid ${safeColor};padding-left:5px">${escHtml(name)}</span>`
        + (includeBasis ? `<small class="hp-table-note">${escHtml(text.basis[row.importance_basis] || text.basis.observed_dose)}${reference ? '<br>' + escHtml(reference) : ''}</small>` : '');
}

function _reportOarTables(rows, language) {
    const text = _reportTableText(language);
    const table = (fields, labels, includeBasis = true) => `<table class="hp-grid-table hp-oar-detail-table"><thead><tr>
        <th>#</th><th>${language === 'zh' ? '器官' : 'Organ'}</th>${labels.map(x => `<th>${x}</th>`).join('')}</tr></thead><tbody>
        ${rows.map((r, i) => `<tr data-structure-id="${escHtml(r.object_id || '')}"><td>${r.review_order ?? i + 1}</td><td>${_reportOarNameCell(r, language, includeBasis)}</td>
            ${fields.map(k => `<td>${_reportTableNumber(r[k], k === 'volume_cm3' || k === 'v100' ? 1 : 2)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
    return table(['dmax', 'dmean', 'd0_1cc', 'd1cc', 'd2cc'], ['Dmax<br>(Gy)', 'Dmean<br>(Gy)', 'D₀.₁cc<br>(Gy)', 'D₁cc<br>(Gy)', 'D₂cc<br>(Gy)'])
        + table(['d90', 'd95', 'v100', 'volume_cm3'], ['D90<br>(Gy)', 'D95<br>(Gy)', 'V100<br>(%)', escHtml(text.volume) + '<br>(cm³)'], false);
}

function _reportSeedTable(seeds, language, owner = '') {
    const t = _reportTableText(language);
    return `<table class="hp-grid-table hp-implant-table">${owner ? `<caption>${escHtml(owner)}</caption>` : ''}<thead><tr><th>${escHtml(t.seed)}</th><th>${escHtml(t.depth)}<br>(mm)</th>
        <th>${escHtml(t.gap)}<br>(mm)</th><th>${escHtml(t.offset)}<br>(mm)</th><th>${escHtml(t.position)}<br>(mm)</th><th>${escHtml(t.status)}</th></tr></thead><tbody>
        ${(seeds || []).map(s => `<tr data-seed-id="${escHtml(s.seed_id)}"><td>${escHtml(s.seed_id)}</td><td>${_reportTableNumber(s.tip_distance_mm)}</td>
            <td${s.spacing_status === 'not_applicable_first' ? ` title="${escHtml(t.noPreviousNote)}"` : ''}>${s.spacing_status === 'not_applicable_first' ? escHtml(t.noPrevious) : _reportTableNumber(s.distance_from_previous_mm)}</td><td>${_reportTableNumber(s.axis_offset_mm)}</td><td class="hp-coordinate">${escHtml(_reportTablePoint(s.position_world_mm))}</td>
            <td>${escHtml((s.flags || []).map(f => t.flags[f] || f).join('; ') || t.recorded)}</td></tr>`).join('')}</tbody></table>`;
}

function _reportImplantSections(form) {
    const t = _reportTableText(form.language);
    const plan = form.implantPlan;
    const header = content => `<section class="report-flow-section" data-report-flow-key="implant"><h2 class="hp-section-title">${escHtml(t.title)}</h2><div class="hp-section-body">${content}</div></section>`;
    if (!plan || !Array.isArray(plan.channels) || (!plan.channels.length && !plan.unassigned_seeds?.length)) return header(`<p>${escHtml(t.empty)}</p>`);
    if (form.planningId && plan.planning_id && String(form.planningId) !== String(plan.planning_id)) return header(`<p>${escHtml(t.mismatch)}</p>`);
    let html = header(`<p>${escHtml(t.note)} ${escHtml(t.noPreviousNote)}</p><p class="hp-table-note">${escHtml(t.sampled)} ${escHtml(t.coordinates[plan.coordinate_system] || plan.coordinate_system || '')}</p>`);
    for (const [i, channel] of plan.channels.entries()) {
        html += `<section class="report-flow-section" data-report-flow-key="implant-channel-${i}"><h3 class="hp-section-title">${escHtml(t.channel)} ${i + 1} · ${escHtml(channel.needle_id)} / ${escHtml(channel.trajectory_id)}</h3><div class="hp-section-body">
            <p class="hp-needle-endpoints"><b>${escHtml(t.start)}</b> ${escHtml(_reportTablePoint(channel.entry_world_mm))} mm<br>
                <b>${escHtml(t.end)}</b> ${escHtml(_reportTablePoint(channel.tip_world_mm))} mm<br>
                <b>${escHtml(t.length)}</b> ${_reportTableNumber(channel.insertion_length_mm)} mm</p>
            ${channel.entry_world_mm ? '' : `<p class="hp-table-note">${escHtml(t.missingEntry)}${channel.entry_reason ? ' (' + escHtml(t.reasons[channel.entry_reason] || channel.entry_reason) + ')' : ''}</p>`}
            ${_reportSeedTable(channel.seeds, form.language, `${t.channel} ${i + 1} · ${channel.needle_id} / ${channel.trajectory_id}`)}</div></section>`;
    }
    if (plan.unassigned_seeds?.length) html += `<section class="report-flow-section" data-report-flow-key="implant-unassigned"><h3 class="hp-section-title">${escHtml(t.unassigned)}</h3><div class="hp-section-body">${_reportSeedTable(plan.unassigned_seeds, form.language, t.unassigned)}</div></section>`;
    return html;
}

function _reportDetailedTablesMarkdown(form) {
    const t = _reportTableText(form.language);
    const cell = value => String(value ?? '').replace(/\|/g, '\\|').replace(/[\r\n]+/g, ' ');
    const lines = ['', '## ' + (form.language === 'zh' ? '各器官剂量明细' : 'Organ Dose Details'), '', t.priorityNote, '',
        `| # | ${t.organ} | Dmax (Gy) | Dmean (Gy) | D0.1cc (Gy) | D1cc (Gy) | D2cc (Gy) | D90 (Gy) | D95 (Gy) | V100 (%) | ${t.volume} (cm3) | ${t.reviewBasis} |`,
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|'];
    if (form.oarDoseOrdering?.stale) lines.splice(5, 0, t.stale, '');
    if (form.oarDoseOrdering?.coverage?.status && form.oarDoseOrdering.coverage.status !== 'complete') lines.splice(5, 0, t.incomplete, '');
    for (const [i, row] of (form.oarDose || []).entries()) lines.push('| ' + [row.review_order ?? i + 1, cell(row.organ), ...['dmax','dmean','d0_1cc','d1cc','d2cc','d90','d95','v100','volume_cm3'].map(k => _reportTableNumber(row[k])), cell(t.basis[row.importance_basis] || t.basis.observed_dose)].join(' | ') + ' |');
    lines.push('', '## ' + t.title, '', t.note + ' ' + t.noPreviousNote, '', t.sampled);
    const plan = form.implantPlan;
    if (!plan) { lines.push(t.empty); return lines; }
    lines.push(t.coordinates[plan.coordinate_system] || plan.coordinate_system || '');
    if (form.planningId && plan.planning_id && String(form.planningId) !== String(plan.planning_id)) { lines.push(t.mismatch); return lines; }
    const seedRows = seeds => {
        lines.push('', `| ${t.seed} | ${t.depth} (mm) | ${t.gap} (mm) | ${t.offset} (mm) | ${t.position} (mm) | ${t.status} |`, '|---|---:|---:|---:|---|---|');
        for (const s of seeds || []) lines.push('| ' + [cell(s.seed_id), _reportTableNumber(s.tip_distance_mm), s.spacing_status === 'not_applicable_first' ? t.noPrevious : _reportTableNumber(s.distance_from_previous_mm), _reportTableNumber(s.axis_offset_mm), _reportTablePoint(s.position_world_mm), cell((s.flags || []).map(f => t.flags[f] || f).join('; ') || t.recorded)].join(' | ') + ' |');
    };
    for (const c of plan.channels || []) {
        lines.push('', '### ' + cell(c.needle_id), '', `${t.start}: ${_reportTablePoint(c.entry_world_mm)} mm; ${t.end}: ${_reportTablePoint(c.tip_world_mm)} mm; ${t.length}: ${_reportTableNumber(c.insertion_length_mm)} mm`);
        if (!c.entry_world_mm) lines.push(t.missingEntry);
        seedRows(c.seeds);
    }
    if (plan.unassigned_seeds?.length) { lines.push('', '### ' + t.unassigned); seedRows(plan.unassigned_seeds); }
    return lines;
}
