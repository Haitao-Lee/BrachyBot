(function () {
    const state = {
        overlay: null,
        sessionId: '',
        catalog: null,
        directoryHandle: null,
        activeJobId: '',
        cancelled: false,
        collapsedGroups: new Set(),
        busy: false,
        generation: 0,
        fileHandle: null,
        previousFocus: null,
        timer: null,
        startedAt: 0,
        options: {},
        errors: [],
        saveAbort: null,
        exportRequested: false,
        terminalOutcome: null,
    };

    function text(zh, en) {
        try {
            if (typeof effectiveUiLanguage === 'function') {
                return effectiveUiLanguage() === 'zh' ? zh : en;
            }
            if (typeof window._t === 'function') return window._t(zh, en);
        } catch (_) {}
        return document.documentElement.lang?.toLowerCase().startsWith('zh') ? zh : en;
    }

    function sessionHeaders(sessionId, json = false) {
        const headers = typeof _viewerDataHeaders === 'function'
            ? _viewerDataHeaders(sessionId)
            : { 'X-BrachyBot-Session': sessionId };
        if (json) headers['Content-Type'] = 'application/json';
        return headers;
    }

    async function fetchJson(url, options = {}) {
        const response = await fetch(url, options);
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.success === false) {
            throw new Error(payload.error || `${response.status} ${response.statusText}`);
        }
        return payload;
    }

    function selectorEscape(value) {
        if (window.CSS && typeof window.CSS.escape === 'function') {
            return window.CSS.escape(String(value));
        }
        return String(value).replace(/["\\]/g, '\\$&');
    }

    function groupTitle(group) {
        const labels = {
            'group:images': ['医学影像', 'Medical Images'], 'group:structures': ['结构', 'Structures'],
            'group:structures:ctv': ['CTV 靶区', 'CTV'], 'group:structures:oar': ['危及器官', 'OAR'],
            'group:structures:skin': ['皮肤表面', 'Skin surface'], 'group:structures:masks': ['其他掩膜', 'Additional masks'],
            'group:planning': ['规划', 'Planning'], 'group:planning:trajectories': ['候选轨迹', 'Trajectories'],
            'group:planning:needles': ['针道', 'Needles'], 'group:planning:seeds': ['粒子', 'Seeds'],
            'group:dose': ['剂量', 'Dose'], 'group:dose:isosurfaces': ['等剂量面', 'Dose iso-surfaces'],
            'group:dvh': ['DVH', 'DVH'], 'group:surgical_guide': ['手术导板', 'Surgical Guide'],
            'group:report': ['报告', 'Report'], 'group:figures': ['图件', 'Figures'],
            'group:annotations': ['测量与标注', 'Annotations'], 'group:chat': ['对话与执行记录', 'Chat & Agent History'],
            'group:chat:screenshots': ['截图', 'Screenshots'],
        };
        return labels[group.object_id] ? text(...labels[group.object_id]) : group.name;
    }

    function typeTitle(type) {
        const labels = { image: ['影像', 'Image'], ctv: ['靶区', 'CTV'], oar: ['危及器官', 'OAR'],
            generic_mask: ['掩膜', 'Mask'], skin_surface: ['皮肤表面', 'Skin surface'], needle: ['针道', 'Needle'],
            seed: ['粒子', 'Seed'], trajectory: ['候选轨迹', 'Trajectory'], planning_parameters: ['规划参数', 'Parameters'],
            dose: ['剂量', 'Dose'], dose_isosurface: ['等剂量面', 'Iso-surface'], dvh_data: ['DVH 数据', 'DVH data'],
            dvh_curve: ['DVH 曲线', 'DVH curve'], report: ['报告', 'Report'], report_data: ['报告数据', 'Report data'],
            report_figure: ['报告图件', 'Report figure'], surgical_guide: ['导板', 'Guide'], annotation: ['测量标注', 'Annotation'],
            screenshot: ['截图', 'Screenshot'], chat_messages: ['对话', 'Chat'], execution_trace: ['执行追踪', 'Execution trace'],
            tool_history: ['工具记录', 'Tool history'], session_settings: ['会话设置', 'Session settings'] };
        return labels[type] ? text(...labels[type]) : type;
    }

    function close() {
        if (state.busy) return;
        if (!state.terminalOutcome && state.overlay) publishOutcome('cancelled', text('已关闭保存窗口；未保存文件。', 'Save dialog closed; no file was saved.'));
        clearInterval(state.timer);
        state.generation += 1;
        state.overlay?.remove();
        state.overlay = null;
        state.directoryHandle = null;
        state.activeJobId = '';
        state.collapsedGroups.clear();
        state.previousFocus?.focus?.();
    }

    function publishOutcome(status, message, extra = {}) {
        state.terminalOutcome = status;
        try { state.options.onState?.({ status, message, saved: status === 'saved',
            export_dialog: true, session_id: state.sessionId, ...extra }); } catch (_) {}
    }

    function assertReportOwner() {
        const active = String(typeof activeSessionId !== 'undefined' ? activeSessionId : window.activeSessionId);
        const owner = String(window.reportForm?.sessionId || window.__reportWorkspaceSessionId || active);
        if (active !== state.sessionId || owner !== state.sessionId) {
            throw new Error(text('报告不属于当前请求的病例，未保存；请等待正确报告加载后重试。', 'The report does not belong to this request case; nothing was saved. Wait for the correct report to load and retry.'));
        }
    }

    function descendants(groupId, groups, objects) {
        const childGroups = groups.filter(group => group.parent_id === groupId);
        const output = objects.filter(item => item.parent_id === groupId);
        childGroups.forEach(group => output.push(...descendants(group.object_id, groups, objects)));
        return output;
    }

    function selectedRows() {
        if (!state.overlay) return [];
        return [...state.overlay.querySelectorAll('tr[data-object-id]')]
            .filter(row => row.querySelector('input[type="checkbox"]')?.checked)
            .map(row => ({
                object_id: row.dataset.objectId,
                format: row.querySelector('select')?.value || row.dataset.defaultFormat,
                filename: row.querySelector('[data-export-filename]')?.value,
            }));
    }

    function syncSummary() {
        const node = state.overlay?.querySelector('[data-export-summary]');
        if (!node) return;
        const count = selectedRows().length;
        node.textContent = text(
            `已选择 ${count} 项真实数据`,
            `${count} real data item${count === 1 ? '' : 's'} selected`,
        );
        const start = state.overlay.querySelector('[data-export-start]');
        if (start) start.disabled = !count || state.busy;
    }

    function leafName(value, extension = '') {
        const name = String(value || '');
        if (!name || name.length > 120 || /[<>:"/\\|?*\x00-\x1f]/.test(name)
            || /[ .]$/.test(name) || name === '.' || name === '..'
            || /^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i.test(name)) {
            throw new Error(text('请输入有效文件名，不要填写路径。', 'Enter a valid filename, not a path.'));
        }
        if (extension && !name.toLowerCase().endsWith(extension)) {
            throw new Error(text(`文件名需要以 ${extension} 结尾。`, `Filename must end with ${extension}.`));
        }
        return name;
    }

    function proposedFilename(item, format) {
        const extension = item.formats.find(spec => spec.key === format)?.extension || '';
        const base = String(item.name || 'data').replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').replace(/[ .]+$/g, '').slice(0, 64) || 'data';
        return (/^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i.test(base) ? '_' : '') + base + extension;
    }

    function resolveSelection(catalog, options) {
        const ids = new Set();
        const issues = [];
        const objects = catalog.objects || [];
        const requested = ['object_ids', 'objectIds', 'group_ids', 'groupIds', 'data_types', 'names']
            .some(key => Array.isArray(options[key]) && options[key].length) || Number.isInteger(options.guide_version);
        if (Number.isInteger(options.guide_version)) {
            const saved = objects.filter(item => item.data_type === 'surgical_guide' && Number(item.metadata?.version) === options.guide_version);
            if (saved.length === 1) ids.add(saved[0].object_id);
            else issues.push(text(`未找到唯一的导板版本 ${options.guide_version}。`, `Guide version ${options.guide_version} is missing or ambiguous.`));
        }
        if (options.all === true || (!requested && options.all !== false && !options.requireCurrentSession)) objects.forEach(item => ids.add(item.object_id));
        if (!requested && options.all !== true && options.requireCurrentSession) issues.push(text('请求未明确指定数据，请在清单中选择；没有自动选择整个 Session。', 'The request did not identify data; select it in the list. The entire Session was not selected automatically.'));
        for (const id of options.object_ids || options.objectIds || []) {
            if (objects.some(item => item.object_id === id)) ids.add(id);
            else issues.push(text(`未找到数据：${id}`, `Data not found: ${id}`));
        }
        for (const groupId of options.group_ids || options.groupIds || []) {
            const found = (catalog.groups || []).find(group => group.object_id === groupId);
            if (!found) issues.push(text(`未找到数据组：${groupId}`, `Group not found: ${groupId}`));
            else descendants(groupId, catalog.groups || [], objects).forEach(item => ids.add(item.object_id));
        }
        for (const type of options.data_types || []) {
            const matches = objects.filter(item => item.data_type === type && (type !== 'surgical_guide' || !Number.isInteger(options.guide_version) || Number(item.metadata?.version) === options.guide_version));
            if (!matches.length) issues.push(text(`没有可用的 ${type} 数据。`, `No ${type} data is available.`));
            matches.forEach(item => ids.add(item.object_id));
        }
        for (const name of options.names || []) {
            const matches = objects.filter(item => item.name?.toLocaleLowerCase() === name.toLocaleLowerCase());
            if (matches.length !== 1) issues.push(text(`“${name}”未找到或不唯一，请在清单中确认。`, `“${name}” is missing or ambiguous; choose it in the list.`));
            else ids.add(matches[0].object_id);
        }
        const excluded = { object_ids: options.exclude_object_ids, group_ids: options.exclude_group_ids,
            data_types: options.exclude_data_types, names: options.exclude_names };
        if (Object.values(excluded).some(value => value?.length)) {
            const exclusion = resolveSelection(catalog, excluded);
            exclusion.ids.forEach(id => ids.delete(id));
            issues.push(...exclusion.issues);
        }
        for (const id of new Set([...Object.keys(options.filenames || {}), ...Object.keys(options.formats_by_object || {})])) {
            if (!objects.some(item => item.object_id === id)) issues.push(text(`文件设置对应的数据不存在：${id}`, `File settings refer to unavailable data: ${id}`));
        }
        for (const type of Object.keys(options.formats_by_type || {})) {
            if (!objects.some(item => item.data_type === type)) issues.push(text(`格式设置对应的类型不存在：${type}`, `Format settings refer to an unavailable type: ${type}`));
        }
        // An incomplete request is never silently widened to all available data.
        return { ids: issues.length ? new Set() : ids, issues };
    }

    function setGroupChecked(groupId, checked) {
        const { groups = [], objects = [] } = state.catalog || {};
        const objectIds = new Set(descendants(groupId, groups, objects).map(item => item.object_id));
        state.overlay?.querySelectorAll('tr[data-object-id]').forEach(row => {
            if (objectIds.has(row.dataset.objectId)) {
                row.querySelector('input[type="checkbox"]').checked = checked;
            }
        });
        updateGroupCheckboxes();
        syncSummary();
    }

    function updateGroupCheckboxes() {
        const { groups = [], objects = [] } = state.catalog || {};
        groups.forEach(group => {
            const checkbox = state.overlay?.querySelector(
                `tr[data-group-id="${selectorEscape(group.object_id)}"] input[type="checkbox"]`,
            );
            if (!checkbox) return;
            const ids = descendants(group.object_id, groups, objects).map(item => item.object_id);
            const values = ids.map(id => state.overlay.querySelector(
                `tr[data-object-id="${selectorEscape(id)}"] input[type="checkbox"]`,
            )?.checked === true);
            checkbox.checked = values.length > 0 && values.every(Boolean);
            checkbox.indeterminate = values.some(Boolean) && !values.every(Boolean);
        });
    }

    function orderedRows() {
        const groups = state.catalog.groups || [];
        const objects = state.catalog.objects || [];
        const rows = [];
        const visitGroup = (group, depth, ancestors = []) => {
            rows.push({ kind: 'group', value: group, depth, ancestors });
            const childAncestors = [...ancestors, group.object_id];
            groups.filter(item => item.parent_id === group.object_id)
                .forEach(item => visitGroup(item, depth + 1, childAncestors));
            objects.filter(item => item.parent_id === group.object_id)
                .forEach(item => rows.push({
                    kind: 'object',
                    value: item,
                    depth: depth + 1,
                    ancestors: childAncestors,
                }));
        };
        groups.filter(group => !group.parent_id).forEach(group => visitGroup(group, 0));
        objects.filter(item => !item.parent_id).forEach(item => {
            rows.push({ kind: 'object', value: item, depth: 0, ancestors: [] });
        });
        return rows;
    }

    function renderRows(filterIds = null) {
        const tbody = state.overlay.querySelector('tbody');
        const allowed = filterIds ? new Set(filterIds) : null;
        const suggestedNames = new Set();
        tbody.innerHTML = orderedRows().map(row => {
            const value = row.value;
            if (row.kind === 'group') {
                const descendantsForGroup = descendants(
                    value.object_id,
                    state.catalog.groups,
                    state.catalog.objects,
                );
                if (allowed && !descendantsForGroup.some(item => allowed.has(item.object_id))) return '';
                return `<tr class="scene-export-group-row" data-group-id="${escHtml(value.object_id)}"
                    data-export-ancestors="${escHtml((row.ancestors || []).join('|'))}">
                    <td><input type="checkbox" checked aria-label="${escHtml(value.name)}"></td>
                    <td colspan="4"><div class="scene-export-name">
                        <span class="scene-export-indent" style="width:${row.depth * 18}px"></span>
                        <button class="scene-export-disclosure" type="button"
                            data-export-disclosure aria-expanded="true"
                            aria-label="${escHtml(text('折叠或展开', 'Collapse or expand'))}">⌄</button>
                        <span data-export-group-name>${escHtml(groupTitle(value))}</span>
                    </div></td>
                </tr>`;
            }
            if (allowed && !allowed.has(value.object_id)) return '';
            const requestedFormat = state.options.formats_by_object?.[value.object_id]
                || state.options.formats_by_type?.[value.data_type] || state.options.format;
            const requestedSpec = value.formats.find(spec => spec.key.toLowerCase() === String(requestedFormat).toLowerCase()
                || spec.extension.toLowerCase().replace(/^\./, '') === String(requestedFormat).toLowerCase().replace(/^\./, ''));
            const chosen = requestedSpec?.key || value.default_format;
            const unsupported = requestedFormat && !requestedSpec;
            let filename = state.options.filenames?.[value.object_id] || proposedFilename(value, chosen);
            const extension = value.formats.find(spec => spec.key === chosen).extension;
            const basename = filename.slice(0, -extension.length);
            let duplicate = 1;
            while (!state.options.filenames?.[value.object_id] && suggestedNames.has(`${value.parent_id}/${filename}`.toLocaleLowerCase())) filename = `${basename}_${++duplicate}${extension}`;
            suggestedNames.add(`${value.parent_id}/${filename}`.toLocaleLowerCase());
            const formats = (value.formats || []).map(format =>
                `<option value="${escHtml(format.key)}" ${format.key === chosen ? 'selected' : ''}>${escHtml(format.label)}</option>`
            ).join('');
            return `<tr data-object-id="${escHtml(value.object_id)}"
                data-export-ancestors="${escHtml((row.ancestors || []).join('|'))}"
                data-default-format="${escHtml(value.default_format)}">
                <td><input type="checkbox" ${state.selectedIds?.has(value.object_id) && !unsupported ? 'checked' : ''} aria-label="${escHtml(value.name)}"></td>
                <td><div class="scene-export-name">
                    <span class="scene-export-indent" style="width:${row.depth * 18}px"></span>
                    <span title="${escHtml(value.name)}">${escHtml(value.name)}</span>
                    ${value.status === 'stale' ? `<small class="scene-export-warning">${text('过期', 'Stale')}</small>` : ''}
                </div></td>
                <td data-export-type="${escHtml(value.data_type)}">${escHtml(typeTitle(value.data_type))}</td>
                <td><select class="scene-export-format" ${value.formats?.length <= 1 ? 'disabled' : ''}>${formats}</select>${unsupported ? `<small class="scene-export-warning">${escHtml(text(`不支持 ${requestedFormat}；请明确选择`, `Unsupported ${requestedFormat}; choose explicitly`))}</small>` : ''}</td>
                <td><input class="scene-export-filename" data-export-filename data-format="${escHtml(chosen)}" maxlength="120" aria-label="${escHtml(text('文件名', 'Filename'))}" value="${escHtml(filename)}"></td>
            </tr>`;
        }).join('');

        tbody.querySelectorAll('tr[data-group-id]').forEach(row => {
            row.querySelector('input').addEventListener('change', event => {
                setGroupChecked(row.dataset.groupId, event.target.checked);
            });
            row.querySelector('[data-export-disclosure]')?.addEventListener('click', event => {
                event.stopPropagation();
                const groupId = row.dataset.groupId;
                if (state.collapsedGroups.has(groupId)) state.collapsedGroups.delete(groupId);
                else state.collapsedGroups.add(groupId);
                applyCollapsedRows();
            });
        });
        tbody.querySelectorAll('tr[data-object-id] input[type="checkbox"]').forEach(input => {
            input.addEventListener('change', () => {
                updateGroupCheckboxes();
                syncSummary();
            });
        });
        tbody.querySelectorAll('tr[data-object-id] select').forEach(select => {
            select.addEventListener('change', () => {
                const row = select.closest('tr');
                const item = state.catalog.objects.find(item => item.object_id === row.dataset.objectId);
                const input = row.querySelector('[data-export-filename]');
                const previous = input.dataset.format;
                const oldExtension = item.formats.find(spec => spec.key === previous)?.extension || '';
                const base = oldExtension && input.value.toLowerCase().endsWith(oldExtension)
                    ? input.value.slice(0, -oldExtension.length) : input.value.replace(/\.[^.]+$/, '');
                input.value = base + item.formats.find(spec => spec.key === select.value).extension;
                input.dataset.format = select.value;
                row.querySelector('td:nth-child(4) .scene-export-warning')?.remove();
            });
        });
        updateGroupCheckboxes();
        syncSummary();
        applyCollapsedRows();
    }

    function chosenFormat(item) {
        return item.formats.some(spec => spec.key === state.options.format) ? state.options.format : item.default_format;
    }

    function applyCollapsedRows() {
        const tbody = state.overlay?.querySelector('tbody');
        if (!tbody) return;
        tbody.querySelectorAll('tr[data-group-id]').forEach(row => {
            const button = row.querySelector('[data-export-disclosure]');
            button?.setAttribute(
                'aria-expanded',
                state.collapsedGroups.has(row.dataset.groupId) ? 'false' : 'true',
            );
        });
        tbody.querySelectorAll('tr[data-export-ancestors]').forEach(row => {
            const ancestors = String(row.dataset.exportAncestors || '').split('|').filter(Boolean);
            row.classList.toggle(
                'scene-export-row-hidden',
                ancestors.some(groupId => state.collapsedGroups.has(groupId)),
            );
        });
    }

    async function chooseDirectory() {
        if (typeof window.showDirectoryPicker !== 'function' || !window.isSecureContext) {
            state.directoryHandle = null;
            state.overlay.querySelector('[data-export-path]').textContent = text(
                '无法直接写入文件夹，将使用浏览器下载（单项文件 / 多项 ZIP）',
                'Folder access is unavailable; use browser download (one file / multiple items as ZIP)',
            );
            return;
        }
        try {
            state.directoryHandle = await window.showDirectoryPicker({ mode: 'readwrite' });
            state.overlay.querySelector('[data-export-path]').textContent = state.directoryHandle.name;
        } catch (error) {
            if (error?.name !== 'AbortError') throw error;
        }
    }

    async function writeBlobToDirectory(rootHandle, relativePath, blob) {
        const parts = String(relativePath).split('/');
        parts.forEach(part => leafName(part));
        let directory = rootHandle;
        for (const part of parts.slice(0, -1)) {
            directory = await directory.getDirectoryHandle(part, { create: true });
        }
        const file = await directory.getFileHandle(parts.at(-1), { create: true });
        const writer = await file.createWritable();
        try { await writer.write(blob); await writer.close(); }
        catch (error) { await writer.abort().catch(() => {}); throw error; }
    }

    function encodedRelativePath(path) {
        return String(path).split('/').map(encodeURIComponent).join('/');
    }

    async function assertNewFolder(name) {
        if (!state.directoryHandle) return;
        try {
            await state.directoryHandle.getDirectoryHandle(name);
            throw new Error(text('目标子文件夹已存在，请换一个名称以避免覆盖。', 'The destination subfolder already exists; choose another name to prevent overwriting.'));
        } catch (error) { if (error.name !== 'NotFoundError') throw error; }
    }

    async function persistCompletedExport(job) {
        if (state.directoryHandle) {
            const folderName = leafName(state.overlay.querySelector('[data-export-bundle]').value);
            await assertNewFolder(folderName);
            const folder = await state.directoryHandle.getDirectoryHandle(folderName, { create: true });
            for (const file of job.files || []) {
                const response = await fetch(
                    `/api/data/exports/${encodeURIComponent(job.job_id)}/files/${encodedRelativePath(file.relative_path)}`,
                    { signal: state.saveAbort?.signal },
                );
                if (!response.ok) throw new Error(`${file.relative_path}: ${response.statusText}`);
                if (state.cancelled) throw new Error(text('保存已停止；文件夹中可能保留已写入文件。', 'Saving stopped; already written files may remain in the folder.'));
                const blob = await response.blob();
                if (state.cancelled) throw new Error(text('保存已停止。', 'Saving stopped.'));
                await writeBlobToDirectory(folder, file.relative_path, blob);
            }
            return 'saved';
        }
        // Download through an authenticated fetch instead of a plain link
        // navigation: the deployment API-key boundary requires the
        // X-API-Key header, which a browser navigation cannot carry.
        const regular = (job.files || []).filter(file => file.object_id !== 'session:manifest');
        if (!regular.length) throw new Error(text('没有成功导出的数据。请检查失败详情。', 'No data was exported successfully. Review the failure details.'));
        const single = regular.length === 1 && selectedRows().length === 1;
        const response = await fetch(single
            ? `/api/data/exports/${encodeURIComponent(job.job_id)}/files/${encodedRelativePath(regular[0].relative_path)}`
            : (job.download_url || `/api/data/exports/${encodeURIComponent(job.job_id)}/download`), { signal: state.saveAbort?.signal });
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
        if (state.fileHandle && response.body) {
            const writer = await state.fileHandle.createWritable();
            if (writer instanceof WritableStream) {
                await response.body.pipeTo(writer, { signal: state.saveAbort?.signal });
                return 'saved';
            }
            // Test/older implementations may provide only the file-write API.
            try { await writer.write(await response.blob()); await writer.close(); }
            catch (error) { await writer.abort().catch(() => {}); throw error; }
            return 'saved';
        }
        const blob = await response.blob();
        return saveBlob(blob, single ? regular[0].relative_path.split('/').at(-1) : `${job.folder_name}.zip`);
    }

    async function saveBlob(blob, filename) {
        if (state.cancelled) throw new Error(text('保存已停止。', 'Saving stopped.'));
        if (state.directoryHandle) {
            const folderName = leafName(state.overlay.querySelector('[data-export-bundle]').value);
            await assertNewFolder(folderName);
            const folder = await state.directoryHandle.getDirectoryHandle(folderName, { create: true });
            await writeBlobToDirectory(folder, `Report/${leafName(filename)}`, blob);
            return 'saved';
        }
        if (state.fileHandle) {
            const writer = await state.fileHandle.createWritable();
            try { await writer.write(blob); await writer.close(); }
            catch (error) { await writer.abort().catch(() => {}); throw error; }
            return 'saved';
        }
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 30000);
        return 'download_requested';
    }

    function updateProgress(job) {
        const progress = state.overlay.querySelector('[data-export-progress]');
        const value = progress.querySelector('.scene-export-progress-value');
        const label = progress.querySelector('.scene-export-progress-text');
        progress.classList.add('active');
        const total = Math.max(0, Number(job.total) || 0);
        const completed = Math.max(0, Number(job.completed) || 0);
        value.style.width = `${total ? Math.min(100, completed / total * 100) : 0}%`;
        label.textContent = job.current
            ? text(`正在导出：${job.current}（${completed}/${total}）`, `Exporting: ${job.current} (${completed}/${total})`)
            : text(`已处理 ${completed}/${total}`, `Processed ${completed}/${total}`);
    }

    async function pollJob(jobId) {
        while (!state.cancelled) {
            const payload = await fetchJson(`/api/data/exports/${encodeURIComponent(jobId)}`);
            const job = payload.job;
            updateProgress(job);
            if (['completed', 'completed_with_errors', 'cancelled', 'failed'].includes(job.status)) {
                return job;
            }
            await new Promise(resolve => setTimeout(resolve, 800));
        }
        return null;
    }

    async function startExport() {
        if (state.busy) return;
        const selections = selectedRows();
        if (!selections.length) return;
        const generation = state.generation;
        state.cancelled = false;
        state.terminalOutcome = null;
        state.saveAbort = new AbortController();
        state.exportRequested = false;
        state.busy = true;
        state.startedAt = performance.now();
        state.timer = setInterval(() => {
            const node = state.overlay?.querySelector('[data-export-elapsed]');
            if (node) node.textContent = `${((performance.now() - state.startedAt) / 1000).toFixed(1)}s`;
        }, 200);
        const exportButton = state.overlay.querySelector('[data-export-start]');
        const cancelButton = state.overlay.querySelector('[data-export-cancel]');
        state.overlay.querySelectorAll('input, select, [data-export-folder], [data-export-download], [data-export-all], [data-export-none]').forEach(node => { node.disabled = true; });
        exportButton.disabled = true;
        cancelButton.textContent = text('停止', 'Stop');
        try {
            const names = new Set();
            for (const selection of selections) {
                const item = state.catalog.objects.find(item => item.object_id === selection.object_id);
                leafName(selection.filename, item.formats.find(spec => spec.key === selection.format).extension);
                const key = `${item.parent_id}/${selection.filename}`.toLocaleLowerCase();
                if (names.has(key)) throw new Error(text('同一组中不能使用重复文件名。', 'Duplicate filenames within a group are not allowed.'));
                names.add(key);
            }
            const bundle = leafName(state.overlay.querySelector('[data-export-bundle]').value);
            const browserReport = selections.find(selection => selection.object_id === 'report:browser');
            if (browserReport && selections.length !== 1) throw new Error(text('屏幕报告请单独保存。', 'Save the on-screen report separately.'));
            if (browserReport?.format === 'pdf') {
                if (state.directoryHandle) throw new Error(text('PDF 需在系统打印窗口中选择保存位置；请先切换到“文件 / 下载”。', 'PDF requires a destination in the system print dialog; switch to File / Download first.'));
                assertReportOwner();
                if (state.sessionId !== String(typeof activeSessionId !== 'undefined' ? activeSessionId : window.activeSessionId)) throw new Error(text('病例已切换，请重新打开报告保存窗口。', 'The case changed; reopen the report save dialog.'));
                const result = await window.exportReportPDF({ filename: browserReport.filename, confirmed: true });
                if (result?.success === false) throw new Error(result.error);
                state.overlay.querySelector('[data-export-summary]').textContent = text('已打开打印窗口，请选择“保存为 PDF”和保存位置；网页无法确认是否已保存。', 'Print dialog opened. Choose Save as PDF and a destination; the page cannot verify that you saved it.');
                publishOutcome('print_dialog_opened', state.overlay.querySelector('[data-export-summary]').textContent);
                return;
            }
            // Invoke the system chooser while still inside the confirm click.
            // A model/SSE callback cannot supply the required user activation.
            state.fileHandle = null;
            if (state.directoryHandle) await assertNewFolder(bundle);
            if (!state.directoryHandle && typeof window.showSaveFilePicker === 'function' && window.isSecureContext) {
                const one = selections.length === 1 ? selections[0] : null;
                const extension = one ? state.catalog.objects.find(item => item.object_id === one.object_id).formats.find(spec => spec.key === one.format).extension : '.zip';
                state.fileHandle = await window.showSaveFilePicker({ suggestedName: one ? one.filename : `${bundle}.zip`,
                    types: [{ description: text('导出文件', 'Export file'), accept: { 'application/octet-stream': [extension] } }] });
                if (state.fileHandle.name) leafName(state.fileHandle.name, extension);
            }
            if (state.cancelled || generation !== state.generation) return;
            if (browserReport) {
                assertReportOwner();
                if (state.sessionId !== String(typeof activeSessionId !== 'undefined' ? activeSessionId : window.activeSessionId)) throw new Error(text('病例已切换。', 'The case changed.'));
                const fn = { html: window.exportReportHTML, markdown: window.exportReportMarkdown, json: window.reportSaveJSON }[browserReport.format];
                if (!fn) throw new Error(text('该报告格式尚不可用。', 'This report format is unavailable.'));
                const blob = await fn({ returnBlob: true });
                assertReportOwner();
                if (!(blob instanceof Blob)) throw new Error(text('未取得可保存的报告。', 'No saveable report was returned.'));
                const outcome = await saveBlob(blob, browserReport.filename);
                state.overlay.querySelector('[data-export-summary]').textContent = outcome === 'saved' ? text('文件已保存。', 'File saved.') : text('已交给浏览器下载，请在下载列表确认位置。', 'Download requested; confirm the location in your browser downloads.');
                publishOutcome(outcome, state.overlay.querySelector('[data-export-summary]').textContent);
                return;
            }
            state.exportRequested = true;
            const payload = await fetchJson('/api/data/exports', {
                method: 'POST',
                headers: sessionHeaders(state.sessionId, true),
                body: JSON.stringify({ session_id: state.sessionId, selections, bundle_name: bundle }),
            });
            state.activeJobId = payload.job.job_id;
            if (state.cancelled) {
                await fetchJson(`/api/data/exports/${encodeURIComponent(state.activeJobId)}/cancel`, { method: 'POST' });
                publishOutcome('cancelled', text('导出已取消；未保存文件。', 'Export cancelled; no file was saved.'));
                return;
            }
            const job = await pollJob(state.activeJobId);
            if (!job) { publishOutcome('cancelled', text('导出已取消；未保存文件。', 'Export cancelled; no file was saved.')); return; }
            state.activeJobId = '';
            state.cancelled = false;
            if (job.status === 'cancelled') {
                state.overlay.querySelector('[data-export-summary]').textContent = text(
                    `导出已取消；已处理 ${job.completed || 0}/${job.total || 0} 项，未生成下载包。`,
                    `Export cancelled after ${job.completed || 0}/${job.total || 0} items; no download was created.`,
                );
                cancelButton.textContent = text('关闭', 'Close');
                exportButton.disabled = false;
                publishOutcome('cancelled', state.overlay.querySelector('[data-export-summary]').textContent);
                return;
            }
            if (job.status === 'failed') {
                throw new Error(job.failures?.map(item => item.error).join('; ') || text('导出失败', 'Export failed'));
            }
            state.overlay.querySelector('.scene-export-progress-text').textContent = text('正在保存文件…', 'Saving files…');
            const issueNode = state.overlay.querySelector('[data-export-issues]');
            issueNode.textContent = [...(job.failures || []), ...(job.skipped || [])].map(item => `${item.object_id}: ${item.error || item.reason}`).join('\n');
            const outcome = await persistCompletedExport(job);
            const failures = job.failures?.length || 0;
            const skipped = job.skipped?.length || 0;
            const succeeded = (job.files || []).filter(
                item => item.object_id !== 'session:manifest',
            ).length;
            state.overlay.querySelector('[data-export-summary]').textContent = text(
                `${outcome === 'saved' ? '已保存' : '已请求下载（请在浏览器确认）'}：${succeeded} 项；失败 ${failures}，跳过 ${skipped}`,
                `${outcome === 'saved' ? 'Saved' : 'Download requested (confirm in browser)'}: ${succeeded} items; ${failures} failed, ${skipped} skipped`,
            );
            publishOutcome(outcome, state.overlay.querySelector('[data-export-summary]').textContent,
                { saved_count: succeeded, failures_count: failures, skipped_count: skipped, partial: failures > 0 || skipped > 0 });
            cancelButton.textContent = text('关闭', 'Close');
            exportButton.disabled = false;
        } catch (error) {
            state.activeJobId = '';
            state.overlay.querySelector('[data-export-summary]').textContent = error.name === 'AbortError'
                ? (state.exportRequested ? text('保存已取消；已生成的导出文件不代表已经保存到本地。', 'Saving cancelled; generated export files are not proof of a local save.')
                    : text('已取消保存，未请求生成新的导出文件。', 'Save cancelled; no new export was requested.')) : error.message;
            cancelButton.textContent = text('关闭', 'Close');
            exportButton.disabled = false;
            publishOutcome(state.cancelled || error.name === 'AbortError' ? 'cancelled' : 'failed', state.overlay.querySelector('[data-export-summary]').textContent);
        } finally {
            clearInterval(state.timer);
            state.activeJobId = '';
            state.busy = false;
            if (state.cancelled && !state.terminalOutcome) publishOutcome('cancelled', text('保存已取消。', 'Saving cancelled.'));
            cancelButton.textContent = text('关闭', 'Close');
            state.overlay?.querySelectorAll('input, select, [data-export-folder], [data-export-download], [data-export-all], [data-export-none]').forEach(node => { node.disabled = false; });
            exportButton.disabled = !selectedRows().length;
        }
    }

    async function cancelOrClose() {
        if (state.busy) {
            state.cancelled = true;
            state.saveAbort?.abort();
            if (state.activeJobId) {
                await fetchJson(`/api/data/exports/${encodeURIComponent(state.activeJobId)}/cancel`, { method: 'POST' }).catch(() => {});
            }
            state.overlay.querySelector('[data-export-summary]').textContent = text('正在停止，请等待当前保存操作结束。', 'Stopping; waiting for the current save operation.');
            return;
        }
        if (state.activeJobId) {
            state.cancelled = true;
            try {
                await fetchJson(`/api/data/exports/${encodeURIComponent(state.activeJobId)}/cancel`, {
                    method: 'POST',
                });
            } catch (_) {}
            state.activeJobId = '';
        }
        close();
    }

    async function openSessionExportDialog(options = {}) {
        if (state.busy) return { success: false, error: text('已有保存任务进行中。', 'A save operation is already running.') };
        if (options.requireCurrentSession && state.overlay) return { success: false,
            error: text('已有保存窗口，未替换你的选择。请先完成或关闭它；复合导出可在一个窗口使用多项和不同格式。', 'A save dialog is already open; your selection was not replaced. Complete or close it first. Use one dialog for multiple items and mixed formats.') };
        if (state.overlay) close();
        const currentSessionId = typeof activeSessionId !== 'undefined'
            ? activeSessionId
            : window.activeSessionId;
        const sessionId = String(options.sessionId || currentSessionId || '');
        if (!sessionId) return;
        state.generation += 1;
        const generation = state.generation;
        state.options = options;
        state.terminalOutcome = null;
        state.previousFocus = document.activeElement;
        state.overlay?.remove();
        state.sessionId = sessionId;
        state.directoryHandle = null;
        state.activeJobId = '';
        state.cancelled = false;
        state.collapsedGroups.clear();

        const payload = await fetchJson('/api/data/catalog', {
            headers: sessionHeaders(sessionId),
        });
        if (generation !== state.generation) return { success: false, error: 'Save dialog was superseded.' };
        if (payload.resources_ready === false) throw new Error(text('病例资源尚未恢复完成，请等待加载结束后再导出。', 'Case resources are still restoring; wait for loading to finish before exporting.'));
        const activeNow = String(typeof activeSessionId !== 'undefined' ? activeSessionId : window.activeSessionId);
        if (options.requireCurrentSession && activeNow !== sessionId) return { success: false, stale: true, error: text('病例已切换，未打开旧请求的保存窗口。', 'The case changed; the old request did not open a save dialog.') };
        if ((options.data_types || []).includes('report')) {
            assertReportOwner();
            payload.objects = payload.objects.filter(item => item.data_type !== 'report');
            if (window.reportForm && sessionId === String(currentSessionId)) {
                payload.objects.push({ object_id: 'report:browser', parent_id: 'group:report', name: text('当前屏幕报告', 'Current on-screen report'), data_type: 'report', default_format: 'pdf',
                    formats: [{ key: 'pdf', extension: '.pdf', label: 'PDF (Print / Save as PDF)' }, { key: 'html', extension: '.html', label: 'HTML' }, { key: 'markdown', extension: '.md', label: 'Markdown' }, { key: 'json', extension: '.json', label: 'JSON' }] });
                if (!payload.groups.some(group => group.object_id === 'group:report')) payload.groups.push({ object_id: 'group:report', name: text('报告', 'Report'), parent_id: null });
            }
        }
        state.catalog = payload;
        const resolved = resolveSelection(payload, options);
        state.selectedIds = resolved.ids;
        const overlay = document.createElement('div');
        overlay.className = 'scene-export-overlay';
        overlay.innerHTML = `<section class="scene-export-dialog" role="dialog" aria-modal="true" aria-labelledby="sceneExportTitle">
            <header class="scene-export-header">
                <div style="min-width:0;flex:1">
                    <h2 id="sceneExportTitle">${text('保存数据', 'Save Data')}</h2>
                    <p>${escHtml((
                        (typeof sessions !== 'undefined' ? sessions?.[sessionId]?.title : '')
                        || sessionId
                    ))}</p>
                </div>
                <button class="scene-export-close" type="button" data-export-close aria-label="${text('关闭', 'Close')}">×</button>
            </header>
            <div>
                <div class="scene-export-location">
                    <strong>${text('导出位置', 'Export Location')}</strong>
                    <span class="scene-export-path" data-export-path>${text('文件 / ZIP（另存为或浏览器下载）', 'File / ZIP (Save As or browser download)')}</span>
                    <button class="scene-export-button" type="button" data-export-folder>${text('选择文件夹', 'Select Folder')}</button>
                    <button class="scene-export-button" type="button" data-export-download>${text('文件 / 下载', 'File / Download')}</button>
                    <small data-export-storage-note>${text('保存单项为文件，多项为结构化 ZIP。支持的浏览器可选择本地文件夹；含患者信息，请谨慎共享。', 'Save one item as a file or multiple items as a structured ZIP. Supported browsers can write to a local folder. May contain patient information; share carefully.')}</small>
                    <label>${text('目录 / ZIP 名称', 'Folder / ZIP name')}<input class="scene-export-filename" data-export-bundle maxlength="120" value="${escHtml(options.bundle_name || `BrachyBot_${sessionId.slice(0, 8)}`)}"></label>
                    <small data-export-units-note>${text('数据交换包包含选中数据与清单，不是完整工作区备份。STL 使用患者 LPS 坐标，单位毫米。', 'An exchange bundle contains selected data and a manifest, not a native workspace backup. STL uses patient LPS coordinates in mm.')}</small>
                    <p class="scene-export-warning" data-export-issues role="status">${escHtml(resolved.issues.join(' '))}</p>
                </div>
                <div class="scene-export-toolbar">
                    <button class="scene-export-button" type="button" data-export-all>${text('全选', 'Select All')}</button>
                    <button class="scene-export-button" type="button" data-export-none>${text('全不选', 'Deselect All')}</button>
                </div>
            </div>
            <div class="scene-export-table-wrap">
                <table class="scene-export-table">
                    <thead><tr>
                        <th>${text('导出', 'Export')}</th>
                        <th>${text('数据', 'Data')}</th>
                        <th>${text('类型', 'Type')}</th>
                        <th>${text('格式', 'Format')}</th>
                        <th>${text('文件名', 'Filename')}</th>
                    </tr></thead>
                    <tbody></tbody>
                </table>
            </div>
            <footer class="scene-export-footer">
                <div class="scene-export-summary" data-export-summary aria-live="polite"></div><span data-export-elapsed></span>
                <div class="scene-export-progress" data-export-progress>
                    <div class="scene-export-progress-track"><div class="scene-export-progress-value"></div></div>
                    <div class="scene-export-progress-text"></div>
                </div>
                <button class="scene-export-button" type="button" data-export-cancel>${text('取消', 'Cancel')}</button>
                <button class="scene-export-button primary" type="button" data-export-start>${text('导出', 'Export')}</button>
            </footer>
        </section>`;
        document.body.appendChild(overlay);
        state.overlay = overlay;
        // Keep the entire real catalog available for corrections; preselect
        // only resolved requested objects. Missing IDs never become Select All.
        renderRows();
        overlay.querySelector('[data-export-close]').onclick = cancelOrClose;
        overlay.querySelector('[data-export-cancel]').onclick = cancelOrClose;
        overlay.querySelector('[data-export-folder]').onclick = () => chooseDirectory().catch(error => {
            overlay.querySelector('[data-export-summary]').textContent = error.message;
        });
        overlay.querySelector('[data-export-download]').onclick = () => {
            if (state.busy) return;
            state.directoryHandle = null;
            overlay.querySelector('[data-export-path]').textContent = text('文件 / ZIP（另存为或浏览器下载）', 'File / ZIP (Save As or browser download)');
        };
        overlay.querySelector('[data-export-start]').onclick = startExport;
        overlay.querySelector('[data-export-all]').onclick = () => {
            overlay.querySelectorAll('input[type="checkbox"]').forEach(input => {
                input.checked = true;
                input.indeterminate = false;
            });
            syncSummary();
        };
        overlay.querySelector('[data-export-none]').onclick = () => {
            overlay.querySelectorAll('input[type="checkbox"]').forEach(input => {
                input.checked = false;
                input.indeterminate = false;
            });
            syncSummary();
        };
        overlay.addEventListener('pointerdown', event => {
            if (event.target === overlay && !state.activeJobId) close();
        });
        overlay.addEventListener('keydown', event => {
            if (event.key === 'Escape') { event.preventDefault(); void cancelOrClose(); }
            if (event.key === 'Tab') {
                const nodes = [...overlay.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled)')].filter(node => node.offsetParent !== null);
                const first = nodes[0], last = nodes.at(-1);
                if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
                if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
            }
        });
        overlay.querySelector('[data-export-close]')?.focus();
        return { success: true, status: 'awaiting_user_confirmation', saved: false, export_dialog: true,
            message: text('已打开保存窗口，等待你确认数据、格式、文件名和位置；尚未导出或保存。', 'Save dialog opened. Confirm data, formats, filenames and destination; nothing has been exported or saved yet.'),
            session_id: sessionId, selected_count: resolved.ids.size, issues: resolved.issues };
    }

    function openSessionContextMenu(event, sessionId) {
        event.preventDefault();
        event.stopPropagation();
        document.querySelectorAll('.session-export-menu').forEach(node => node.remove());
        const menu = document.createElement('div');
        menu.className = 'session-export-menu';
        const entry = (typeof sessions !== 'undefined' && sessions[sessionId]) || {};
        const archived = entry.storageStatus === 'archived';
        const archiveLabel = archived
            ? text('激活并恢复到本地', 'Activate and restore')
            : text('归档到低速存储', 'Archive to cold storage');
        menu.innerHTML = '<button type="button" data-session-archive>' + archiveLabel + '</button>'
            + '<button type="button" data-session-export>' + text('导出 Session', 'Export Session') + '</button>';
        menu.style.left = `${event.clientX}px`;
        menu.style.top = `${event.clientY}px`;
        menu.querySelector('[data-session-archive]').onclick = () => {
            menu.remove();
            if (archived) {
                window.switchSession?.(sessionId);
            } else {
                window.archiveServerSession?.(sessionId);
            }
        };
        menu.querySelector('[data-session-export]').onclick = () => {
            menu.remove();
            openSessionExportDialog({ sessionId }).catch(error => {
                if (typeof addChat === 'function') addChat('error', error.message);
            });
        };
        document.body.appendChild(menu);
        if (typeof window.positionBrachyContextMenu === 'function') {
            window.positionBrachyContextMenu(menu, event.clientX, event.clientY);
        } else {
            const rect = menu.getBoundingClientRect();
            if (rect.right > innerWidth) menu.style.left = `${Math.max(6, event.clientX - rect.width)}px`;
            if (rect.bottom > innerHeight) menu.style.top = `${Math.max(6, event.clientY - rect.height)}px`;
        }
        setTimeout(() => document.addEventListener('pointerdown', () => menu.remove(), { once: true }), 0);
    }

    window.openSessionExportDialog = openSessionExportDialog;
    window.BrachyBotExport = { resolveSelection, leafName };
    window.addEventListener('i18nchange', () => {
        const overlay = state.overlay;
        if (!overlay) return;
        const labels = {
            '[data-export-folder]': ['选择文件夹', 'Select Folder'],
            '[data-export-download]': ['文件 / 下载', 'File / Download'],
            '[data-export-all]': ['全选', 'Select All'],
            '[data-export-none]': ['全不选', 'Deselect All'],
            '[data-export-start]': ['导出', 'Export'],
            '[data-export-cancel]': state.busy ? ['停止', 'Stop'] : ['关闭', 'Close'],
            '.scene-export-location strong': ['导出位置', 'Export Location'],
            '[data-export-storage-note]': ['保存单项为文件，多项为结构化 ZIP；含患者信息，请谨慎共享。', 'Save one item as a file or multiple items as a ZIP; may contain patient information.'],
            '[data-export-units-note]': ['数据交换包不是完整工作区备份。STL 使用患者 LPS 坐标，单位毫米。', 'An exchange bundle is not a native workspace backup. STL uses patient LPS coordinates in mm.'],
        };
        for (const [selector, pair] of Object.entries(labels)) {
            const node = overlay.querySelector(selector);
            if (node) node.textContent = text(...pair);
        }
        const headers = [['导出', 'Export'], ['数据', 'Data'], ['类型', 'Type'], ['格式', 'Format'], ['文件名', 'Filename']];
        overlay.querySelectorAll('thead th').forEach((node, index) => { node.textContent = text(...headers[index]); });
        const title = overlay.querySelector('h2');
        if (title) title.textContent = text('保存数据', 'Save Data');
        const label = overlay.querySelector('[data-export-bundle]')?.parentElement;
        if (label?.firstChild?.nodeType === 3) label.firstChild.textContent = text('目录 / ZIP 名称', 'Folder / ZIP name');
        overlay.querySelectorAll('[data-group-id]').forEach(row => {
            const group = state.catalog.groups.find(group => group.object_id === row.dataset.groupId);
            const node = row.querySelector('[data-export-group-name]');
            if (group && node) node.textContent = groupTitle(group);
        });
        overlay.querySelectorAll('[data-export-type]').forEach(node => { node.textContent = typeTitle(node.dataset.exportType); });
        if (!state.busy) syncSummary();
    });
    window.openSessionContextMenu = openSessionContextMenu;
})();
