(function () {
    const state = {
        overlay: null,
        sessionId: '',
        catalog: null,
        directoryHandle: null,
        activeJobId: '',
        cancelled: false,
        collapsedGroups: new Set(),
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

    function close() {
        if (state.activeJobId && !state.cancelled) return;
        state.overlay?.remove();
        state.overlay = null;
        state.directoryHandle = null;
        state.activeJobId = '';
        state.collapsedGroups.clear();
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
                    <td colspan="3"><div class="scene-export-name">
                        <span class="scene-export-indent" style="width:${row.depth * 18}px"></span>
                        <button class="scene-export-disclosure" type="button"
                            data-export-disclosure aria-expanded="true"
                            aria-label="${escHtml(text('折叠或展开', 'Collapse or expand'))}">⌄</button>
                        <span>${escHtml(value.name)}</span>
                    </div></td>
                </tr>`;
            }
            if (allowed && !allowed.has(value.object_id)) return '';
            const formats = (value.formats || []).map(format =>
                `<option value="${escHtml(format.key)}" ${format.key === value.default_format ? 'selected' : ''}>${escHtml(format.label)}</option>`
            ).join('');
            return `<tr data-object-id="${escHtml(value.object_id)}"
                data-export-ancestors="${escHtml((row.ancestors || []).join('|'))}"
                data-default-format="${escHtml(value.default_format)}">
                <td><input type="checkbox" checked aria-label="${escHtml(value.name)}"></td>
                <td><div class="scene-export-name">
                    <span class="scene-export-indent" style="width:${row.depth * 18}px"></span>
                    <span title="${escHtml(value.name)}">${escHtml(value.name)}</span>
                </div></td>
                <td>${escHtml(value.data_type)}</td>
                <td><select class="scene-export-format" ${value.formats?.length <= 1 ? 'disabled' : ''}>${formats}</select></td>
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
        updateGroupCheckboxes();
        syncSummary();
        applyCollapsedRows();
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
        if (typeof window.showDirectoryPicker !== 'function') {
            state.directoryHandle = null;
            state.overlay.querySelector('[data-export-path]').textContent = text(
                '浏览器不支持直接写入文件夹，将下载结构化 ZIP',
                'Folder access is unavailable; a structured ZIP will be downloaded',
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
        const parts = String(relativePath).split('/').filter(Boolean);
        let directory = rootHandle;
        for (const part of parts.slice(0, -1)) {
            directory = await directory.getDirectoryHandle(part, { create: true });
        }
        const file = await directory.getFileHandle(parts.at(-1), { create: true });
        const writer = await file.createWritable();
        await writer.write(blob);
        await writer.close();
    }

    function encodedRelativePath(path) {
        return String(path).split('/').map(encodeURIComponent).join('/');
    }

    async function persistCompletedExport(job) {
        if (state.directoryHandle) {
            const folder = await state.directoryHandle.getDirectoryHandle(
                job.folder_name || `BrachyBot_Session_${state.sessionId}`,
                { create: true },
            );
            for (const file of job.files || []) {
                const response = await fetch(
                    `/api/data/exports/${encodeURIComponent(job.job_id)}/files/${encodedRelativePath(file.relative_path)}`,
                );
                if (!response.ok) throw new Error(`${file.relative_path}: ${response.statusText}`);
                await writeBlobToDirectory(folder, file.relative_path, await response.blob());
            }
            return;
        }
        const link = document.createElement('a');
        link.href = job.download_url;
        link.download = '';
        document.body.appendChild(link);
        link.click();
        link.remove();
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
        const selections = selectedRows();
        if (!selections.length) return;
        state.cancelled = false;
        const exportButton = state.overlay.querySelector('[data-export-start]');
        const cancelButton = state.overlay.querySelector('[data-export-cancel]');
        exportButton.disabled = true;
        cancelButton.textContent = text('停止', 'Stop');
        try {
            const payload = await fetchJson('/api/data/exports', {
                method: 'POST',
                headers: sessionHeaders(state.sessionId, true),
                body: JSON.stringify({ session_id: state.sessionId, selections }),
            });
            state.activeJobId = payload.job.job_id;
            const job = await pollJob(state.activeJobId);
            if (!job) return;
            state.activeJobId = '';
            state.cancelled = false;
            if (job.status === 'cancelled') {
                state.overlay.querySelector('[data-export-summary]').textContent = text(
                    `导出已取消；已处理 ${job.completed || 0}/${job.total || 0} 项，未生成下载包。`,
                    `Export cancelled after ${job.completed || 0}/${job.total || 0} items; no download was created.`,
                );
                cancelButton.textContent = text('关闭', 'Close');
                exportButton.disabled = false;
                return;
            }
            if (job.status === 'failed') {
                throw new Error(job.failures?.map(item => item.error).join('; ') || text('导出失败', 'Export failed'));
            }
            await persistCompletedExport(job);
            const failures = job.failures?.length || 0;
            const skipped = job.skipped?.length || 0;
            const succeeded = (job.files || []).filter(
                item => item.object_id !== 'session:manifest',
            ).length;
            state.overlay.querySelector('[data-export-summary]').textContent = text(
                `导出完成：成功 ${succeeded}，失败 ${failures}，跳过 ${skipped}`,
                `Export complete: ${succeeded} succeeded, ${failures} failed, ${skipped} skipped`,
            );
            cancelButton.textContent = text('关闭', 'Close');
            exportButton.disabled = false;
        } catch (error) {
            state.activeJobId = '';
            state.overlay.querySelector('[data-export-summary]').textContent = error.message;
            cancelButton.textContent = text('关闭', 'Close');
            exportButton.disabled = false;
        }
    }

    async function cancelOrClose() {
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
        const currentSessionId = typeof activeSessionId !== 'undefined'
            ? activeSessionId
            : window.activeSessionId;
        const sessionId = String(options.sessionId || currentSessionId || '');
        if (!sessionId) return;
        state.overlay?.remove();
        state.sessionId = sessionId;
        state.directoryHandle = null;
        state.activeJobId = '';
        state.cancelled = false;
        state.collapsedGroups.clear();

        const payload = await fetchJson('/api/data/catalog', {
            headers: sessionHeaders(sessionId),
        });
        state.catalog = payload;
        const filteredExport = (
            Array.isArray(options.objectIds) && options.objectIds.length
        ) || (
            Array.isArray(options.groupIds) && options.groupIds.length
        );
        const overlay = document.createElement('div');
        overlay.className = 'scene-export-overlay';
        overlay.innerHTML = `<section class="scene-export-dialog" role="dialog" aria-modal="true" aria-labelledby="sceneExportTitle">
            <header class="scene-export-header">
                <div style="min-width:0;flex:1">
                    <h2 id="sceneExportTitle">${filteredExport
                        ? text('导出数据', 'Export Data')
                        : text('导出 Session', 'Export Session')}</h2>
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
                    <span class="scene-export-path" data-export-path>${text('结构化 ZIP（兼容模式）', 'Structured ZIP (compatible mode)')}</span>
                    <button class="scene-export-button" type="button" data-export-folder>${text('选择文件夹', 'Select Folder')}</button>
                    <small>${text('浏览器不支持目录写入时自动使用单个 ZIP', 'A single ZIP is used when directory writing is unavailable')}</small>
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
                    </tr></thead>
                    <tbody></tbody>
                </table>
            </div>
            <footer class="scene-export-footer">
                <div class="scene-export-summary" data-export-summary></div>
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
        let filterIds = Array.isArray(options.objectIds) ? [...options.objectIds] : null;
        if (Array.isArray(options.groupIds) && options.groupIds.length) {
            const grouped = options.groupIds.flatMap(groupId => descendants(
                groupId,
                state.catalog.groups || [],
                state.catalog.objects || [],
            ).map(item => item.object_id));
            filterIds = [...new Set([...(filterIds || []), ...grouped])];
        }
        renderRows(filterIds);
        overlay.querySelector('[data-export-close]').onclick = cancelOrClose;
        overlay.querySelector('[data-export-cancel]').onclick = cancelOrClose;
        overlay.querySelector('[data-export-folder]').onclick = () => chooseDirectory().catch(error => {
            overlay.querySelector('[data-export-summary]').textContent = error.message;
        });
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
    }

    function openSessionContextMenu(event, sessionId) {
        event.preventDefault();
        event.stopPropagation();
        document.querySelectorAll('.session-export-menu').forEach(node => node.remove());
        const menu = document.createElement('div');
        menu.className = 'session-export-menu';
        menu.innerHTML = `<button type="button">${text('导出 Session', 'Export Session')}</button>`;
        menu.style.left = `${event.clientX}px`;
        menu.style.top = `${event.clientY}px`;
        menu.querySelector('button').onclick = () => {
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
    window.openSessionContextMenu = openSessionContextMenu;
})();
