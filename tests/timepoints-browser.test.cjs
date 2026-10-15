// Synthetic browser state and an in-page fetch fixture; no server or patient mutation.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(process.argv[2] || path.join(__dirname, '../web/app/static/js'));
const html = fs.readFileSync(path.join(root, '../../index.html'), 'utf8');
const strip = html.slice(html.indexOf('<section id="timepointStrip"'), html.indexOf('</section>', html.indexOf('<section id="timepointStrip"')) + 10);
const apiSource = fs.readFileSync(path.join(root, 'brachybot-ui-api.js'), 'utf8');
const apiWrapper = apiSource.slice(apiSource.indexOf('(function installApiRequestFetchWrapper()'), apiSource.indexOf('// Abort controller for stopping streaming responses'));
const confirmSource = apiSource.slice(apiSource.indexOf('function _confirmAction('), apiSource.indexOf('function _uiActionSessionIsCurrent('));
const A = 'preoperative-a', B = 'intraoperative-b', SID = '11111111111111111111111111111111';
let scenarios = 0;
const check = name => { scenarios++; console.log('PASS ' + name); };

(async () => {
    const browser = await chromium.launch({ headless: true,
        ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}),
        args: ['--no-sandbox'] });
    const page = await browser.newPage({ viewport: { width: 1280, height: 850 } });
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/*', route => {
        if (route.request().url() === 'http://timepoints.invalid/') return route.fulfill({ contentType: 'text/html', body: '<!doctype html><html><body></body></html>' });
        return route.abort('blockedbyclient');
    });
    try {
        await page.goto('http://timepoints.invalid/');
        await page.setContent(`<div id="chatMessages"><p>Shared conversation sentinel</p></div>${strip}
            <section id="panelInput">One mounted input</section><section id="panelViewers"></section><section id="panelReport"></section>`);
        await page.addStyleTag({ path: path.join(root, '../css/brachybot-theme-layout.css') });
        await page.addStyleTag({ path: path.join(root, '../css/brachybot-timepoints.css') });
        await page.evaluate(({ SID, A, B }) => {
            window.API = '/api'; window._i18nLang = 'en'; window.activeSessionId = SID;
            window._activeApiSessionId = () => activeSessionId;
            window._t = (zh, en) => _i18nLang === 'zh' ? zh : en;
            window.escHtml = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
            window.brachybotAuth = { user: { id: 'synthetic-user' } };
            window.nativeConfirmCalls = 0; window.confirm = window.prompt = () => { nativeConfirmCalls++; throw Error('Native dialog forbidden'); };
            window.calls = []; window.failCatalog = false; window.failSave = false; window.blockDelete = false; window.deferCatalog = false;
            window.catalog = { session_id: SID, catalog_revision: 2, default_timepoint_id: A,
                capabilities: { execution_scope: false }, timepoints: [
                    { id: A, title: 'CT baseline', stage: 'preoperative', preoperative_timepoint_id: null, revision: 3, state_revision: 3 },
                    { id: B, title: 'CT during surgery', stage: 'intraoperative', preoperative_timepoint_id: A, revision: 5, state_revision: 5 },
                    { id: 'deleted-c', title: 'Old scan', stage: 'preoperative', revision: 1, deleted: true }
                ] };
            window.workspaces = {
                [A]: { session_id: SID, timepoint_id: A, timepoint_state_revision: 3, ui: { viewer: { camera: [11,22,33], slice: 9 },
                    objects: { seed_1: { color: '#22D3EE', opacity: .6, visible: false } }, report: 'Report A', image: 'same-name.nii.gz' } },
                [B]: { session_id: SID, timepoint_id: B, timepoint_state_revision: 5, ui: { viewer: { camera: [44,55,66], slice: 2 },
                    objects: { seed_1: { color: '#C084FC', opacity: .8, visible: true } }, report: 'Report B', image: 'same-name.nii.gz' } },
                'deleted-c': { session_id: SID, timepoint_id: 'deleted-c', timepoint_state_revision: 1, ui: {} }
            };
            Object.values(workspaces).forEach(w=>w.timepoint_clinical_revision=0);
            catalog.timepoints.forEach(r=>r.lifecycle_revision=0);
            const copy = obj => JSON.parse(JSON.stringify(obj));
            const response = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
            window.fetch = async (input, init = {}) => {
                const url = new URL(typeof input === 'string' ? input : input.url, location.href), headers = Object.fromEntries(new Headers(init.headers || input.headers || {}));
                const method = init.method || input.method || 'GET', body = init.body ? JSON.parse(init.body) : null;
                calls.push({ path: url.pathname, search: url.search, method, body, headers });
                if (url.pathname === '/api/upload' && window.deferUpload) return new Promise(resolve => { window.finishUpload = () => resolve(response({ image: 'uploaded-on-A' })); });
                if (url.pathname === '/api/upload') return response({ image: 'uploaded' });
                if (!url.pathname.includes('/timepoints')) return response({ ok: true });
                const bits = url.pathname.split('/'), sid = bits[3], id = bits[5];
                if (!id && method === 'GET') {
                    if (failCatalog) return response({ code: 'not_enabled' }, 404);
                    const value = copy(catalog);
                    if (deferCatalog) return new Promise(resolve => { window.finishCatalog = () => resolve(response(value)); });
                    return response(value);
                }
                const row = catalog.timepoints.find(r => r.id === id);
                if (bits[6] === 'delete-impact') return response({ can_delete: !blockDelete, dependents: blockDelete ? [B] : [], reason: null });
                if (bits[6] === 'workspace') {
                    if (method === 'GET') {
                        const value = { ...copy(workspaces[id]), timepoint: copy(row) };
                        if (window.deferWorkspace === id) return new Promise(resolve => { window.finishWorkspace = () => resolve(response({ workspace: value })); });
                        return response({ workspace: window.badWorkspaceScope ? { ...value, timepoint_id: A } : value });
                    }
                    if (failSave) return response({ code: 'revision_conflict', error: 'Revision conflict' }, 409);
                    if (body.expected_state_revision !== workspaces[id].timepoint_state_revision) return response({ code: 'revision_conflict', error: 'Revision conflict' }, 409);
                    Object.assign(workspaces[id], copy(body.patch)); workspaces[id].timepoint_state_revision++;
                    row.state_revision = workspaces[id].timepoint_state_revision; catalog.catalog_revision++;
                    if(window.compactAck) return response({presentation_receipt:{session_id:SID,timepoint_id:id,
                        timepoint_state_revision:workspaces[id].timepoint_state_revision,timepoint_clinical_revision:0,
                        timepoint:copy(row)},presentation:copy(body.patch)});
                    return response({ workspace: { ...copy(workspaces[id]), timepoint: copy(row) } });
                }
                if (body.expected_revision !== catalog.catalog_revision) return response({ code: 'revision_conflict', error: 'Revision conflict' }, 409);
                let created_timepoint_id;
                if (method === 'POST' && !id) {
                    const next = { id: 'created-' + catalog.timepoints.length, revision: 1, state_revision: 0, ...copy(body) };
                    catalog.timepoints.push(next); workspaces[next.id] = { session_id: sid, timepoint_id: next.id, timepoint_state_revision: 0, ui: {} };
                    created_timepoint_id = next.id;
                } else if (method === 'PATCH') Object.assign(row, copy(body), { revision: row.revision + 1 });
                else if (method === 'DELETE') { row.deleted = true; row.revision++; }
                else if (bits[6] === 'restore') { row.deleted = false; row.revision++; }
                catalog.catalog_revision++; return response({ ...copy(catalog), ...(created_timepoint_id ? { created_timepoint_id } : {}) });
            };
            window.paints = []; window.suspends = []; window.disposals = 0;
            window.makeBridge = () => ({ timepoint_scope: true, async_fencing: true, scoped_persistence: true, preserves_shared_chat: true,
                capture: () => {window.captureCalls=(window.captureCalls||0)+1;
                    return { ui: copy(window.mounted), report: { title: window.mounted?.report || '' } };},
                suspend: scope => { suspends.push(scope.timepointId); window.mounted = null; document.getElementById('panelViewers').textContent = ''; },
                prepare: async (workspace, context) => {
                    if (window.deferPrepare === workspace.timepoint_id) await new Promise(resolve => { window.finishPrepare = resolve; });
                    return { dispose: () => { disposals++; }, commit: () => {
                        assertCurrent = context.isCurrent(); if (!assertCurrent) throw Error('Stale bridge commit');
                        window.mounted = copy(workspace.ui); paints.push(workspace.timepoint_id);
                        document.getElementById('panelViewers').textContent = JSON.stringify(mounted);
                        window.lateResource = () => { if (context.isCurrent()) mounted.lateAppearance = copy(context.presentation.objects); };
                    } };
                }
            });
        }, { SID, A, B });
        await page.addScriptTag({ content: apiWrapper });
        await page.addScriptTag({ content: confirmSource });
        await page.addScriptTag({ path: path.join(root, 'brachybot-timepoints.js') });
        await page.waitForFunction(() => !!BrachyBotTimepoints.getCatalog());
        assert.equal(await page.getByRole('button', { name: 'Add timepoint', exact: true }).isDisabled(), true);
        assert.equal(await page.locator('#timepointTabs button').count(), 2);
        assert.match(await page.locator('#timepointStatus').innerText(), /independent execution is not enabled/);
        assert.equal(await page.evaluate(() => calls.filter(c => c.method !== 'GET').length), 0);
        check('Catalog with execution_scope false is read-only and never hydrates clinical data');

        await page.evaluate(async () => { catalog.capabilities.execution_scope = true; await BrachyBotTimepoints.refresh(); });
        assert.match(await page.locator('#timepointStatus').innerText(), /restoration is not ready/);
        assert.equal(await page.locator('#timepointAdd').isDisabled(), true);
        await page.evaluate(() => BrachyBotTimepoints.registerBridge(makeBridge()));
        await page.waitForFunction(A => BrachyBotTimepoints.captureTarget().timepointId === A && document.querySelector('#timepointStrip').getAttribute('aria-busy') === 'false', A);
        assert.deepEqual(await page.evaluate(() => mounted.viewer.camera), [11,22,33]);
        await page.evaluate(()=>{
            window.captureCalls=0;window.compactAck=true;
            for(let i=0;i<60;i++){mounted.viewer.slice=i;BrachyBotTimepoints.schedulePresentationSave();}
        });
        assert.equal(await page.evaluate(()=>captureCalls),0);
        await page.waitForFunction(()=>captureCalls===1 && !document.querySelector('.timepoint-badge'));
        assert.equal(await page.evaluate(A=>workspaces[A].ui.viewer.slice,A),59);
        const ackRequest=await page.evaluate(()=>calls.filter(c=>c.method==='PATCH'&&c.path.endsWith('/workspace')).at(-1));
        assert.equal(ackRequest.body.response_mode,'presentation_receipt');
        check('60 interaction events capture once after settling and compact owned receipt saves latest state');
        await page.evaluate(async B=>{
            mounted.viewer.slice=61;BrachyBotTimepoints.schedulePresentationSave();
            await BrachyBotTimepoints.select(B);
        },B);
        await page.waitForTimeout(800);
        assert.equal(await page.evaluate(A=>workspaces[A].ui.viewer.slice,A),61);
        assert.equal(await page.evaluate(()=>mounted.viewer.slice),2);
        await page.evaluate(async A=>{await BrachyBotTimepoints.select(A);window.compactAck=false;},A);
        assert.equal(await page.evaluate(()=>mounted.viewer.slice),61);
        check('Navigation flushes outgoing state before deferred capture; stale timer never copies the new owner');
        assert.equal(await page.locator('#panelInput').count(), 1);
        check('Backend scope still needs a complete bridge; one mounted workspace restores the default');

        await page.locator(`[data-timepoint-id="${A}"]`).focus(); await page.keyboard.press('ArrowRight');
        await page.waitForFunction(B => document.activeElement.dataset.timepointId === B, B);
        assert.equal(await page.evaluate(() => mounted.report), 'Report B');
        await page.keyboard.press('Home');
        await page.waitForFunction(A => document.activeElement.dataset.timepointId === A, A);
        assert.equal(await page.evaluate(() => mounted.report), 'Report A');
        assert.equal(await page.locator('#timepointTabs [tabindex="0"]').count(), 1);
        check('Keyboard tab navigation retains focus and mounts exactly one selected workspace');

        await page.evaluate(() => { mounted.viewer.camera = [91,92,93]; mounted.objects.seed_1.color = '#00FFFF'; window.aScope = BrachyBotTimepoints.captureTarget(); deferUpload = true;
            window.uploadPromise = BrachyBotTimepoints.request(aScope, '/api/upload', { method: 'POST' }).then(r => r.json()).then(result => BrachyBotTimepoints.applyResult(aScope, result, value => { mounted.image = value.image; })); });
        assert.equal(await page.evaluate(async B => BrachyBotTimepoints.select(B), B), true);
        const headers = await page.evaluate(() => calls.find(c => c.path === '/api/upload').headers);
        assert.equal(headers['x-brachybot-session'], SID); assert.equal(headers['x-brachybot-timepoint'], A);
        await page.evaluate(async () => { finishUpload(); window.uploadPainted = await uploadPromise; BrachyBotTimepoints.setJobState(aScope, 'job-on-a', 'running'); });
        assert.equal(await page.evaluate(() => uploadPainted), false);
        assert.equal(await page.evaluate(() => mounted.report), 'Report B');
        assert.equal(await page.evaluate(() => mounted.image), 'same-name.nii.gz');
        assert.match(await page.locator(`[data-timepoint-id="${A}"]`).innerText(), /Running/);
        assert.equal(await page.evaluate(() => BrachyBotTimepoints.getDataState(aScope).result.image), 'uploaded-on-A');
        assert.equal(await page.locator('#chatMessages').innerText(), 'Shared conversation sentinel');
        check('A upload completing on B keeps stable headers, stores A result and never paints B or clears chat');

        await page.evaluate(async () => {
            await fetch('/api/dose/status');
            await fetch('/api/dose/status', { headers: { 'X-BrachyBot-Session': '22222222222222222222222222222222' } });
            await fetch(new Request(location.origin + '/api/dose/status', { headers: { 'X-BrachyBot-Session': aScope.sessionId, 'X-BrachyBot-Timepoint': aScope.timepointId } }));
            await fetch('/api/sessions'); await fetch('/api/auth/me');
        });
        const recent = await page.evaluate(() => calls.slice(-5));
        assert.equal(recent[0].headers['x-brachybot-timepoint'], B);
        assert.equal(recent[1].headers['x-brachybot-timepoint'], undefined);
        assert.equal(recent[2].headers['x-brachybot-timepoint'], A);
        assert.equal(recent[3].headers['x-brachybot-timepoint'], undefined);
        assert.equal(recent[4].headers['x-brachybot-timepoint'], undefined);
        await page.evaluate(async () => { window.foreignRejected = false; try { await BrachyBotTimepoints.request(aScope, 'https://foreign.invalid/api/upload'); } catch (_) { foreignRejected = true; } });
        assert.equal(await page.evaluate(() => foreignRejected), true);
        check('Legacy clinical fetch wrapper preserves explicit targets and separates Session/control-plane headers');

        await page.evaluate(() => { mounted.viewer.camera = [7,8,9]; mounted.objects.seed_1.visible = false; });
        await page.evaluate(async A => BrachyBotTimepoints.select(A), A);
        assert.deepEqual(await page.evaluate(() => mounted.viewer.camera), [91,92,93]);
        assert.equal(await page.evaluate(() => mounted.objects.seed_1.color), '#00FFFF');
        assert.equal(await page.evaluate(() => mounted.objects.seed_1.visible), false);
        await page.evaluate(() => { lateResource(); BrachyBotTimepoints.applyResult(aScope, { image: 'obsolete-view-generation' }, value => { mounted.image = value.image; }); });
        assert.equal(await page.evaluate(() => mounted.lateAppearance.seed_1.color), '#00FFFF');
        assert.equal(await page.evaluate(() => mounted.image), 'same-name.nii.gz');
        await page.evaluate(async B => BrachyBotTimepoints.select(B), B);
        assert.deepEqual(await page.evaluate(() => mounted.viewer.camera), [7,8,9]);
        assert.equal(await page.evaluate(() => mounted.objects.seed_1.color), '#C084FC');
        check('Same seed/file names remain separate; exact cameras, colors and visibility survive save/restore and late resources');

        await page.evaluate(async A => { failSave = true; window.failedSwitch = await BrachyBotTimepoints.select(A); }, A);
        assert.equal(await page.evaluate(() => failedSwitch), false);
        assert.equal(await page.evaluate(() => BrachyBotTimepoints.captureTarget().timepointId), B);
        assert.deepEqual(await page.evaluate(() => mounted.viewer.camera), [7,8,9]);
        assert.match(await page.locator('#timepointStatus').innerText(), /Revision conflict/);
        await page.evaluate(() => { failSave = false; });
        check('Revision conflict retains the outgoing mounted data and prevents an unsaved switch');

        await page.evaluate(async A => {
            catalog.timepoints.find(r=>r.id===A).auto_title=true;
            catalog.timepoints.find(r=>r.id===A).title='Preoperative';
            await BrachyBotTimepoints.refresh({activate:false});
            _i18nLang='zh';dispatchEvent(new Event('i18nchange'));deferCatalog=true;
            window.dialogCallCount=calls.length;
        },A);
        for(let attempt=0;attempt<3;attempt++) {
            await page.getByRole('button',{name:'添加时间点',exact:true}).click();
            await page.getByLabel('阶段',{exact:true}).selectOption('intraoperative');
            assert.equal(await page.locator('select[name="preoperative_timepoint_id"] option[value="'+A+'"]').textContent(),'术前');
            assert.equal(await page.evaluate(()=>calls.length),await page.evaluate(()=>dialogCallCount),'Opening Add never waits on a catalog request');
            await page.keyboard.press('Escape');
        }
        await page.evaluate(()=>{deferCatalog=false;_i18nLang='en';dispatchEvent(new Event('i18nchange'));});
        check('Add opens repeatedly without a catalog round trip and default reference matches the localized tab');

        await page.evaluate(A=>{
            const original=window.fetch;window.beforeFastSwitch=calls.length;
            window.fetch=async(input,init={})=>{
                if(init.method==='PATCH'&&String(input).endsWith('/workspace'))
                    await new Promise(resolve=>window.releaseOutgoing=resolve);
                return original(input,init);
            };
            window.fastSwitch=BrachyBotTimepoints.select(A);window.originalFetch=original;
        },A);
        await page.waitForFunction(()=>typeof releaseOutgoing==='function');
        assert.equal(await page.evaluate(A=>calls.slice(beforeFastSwitch).some(c=>c.path.endsWith('/'+A+'/workspace')&&c.method==='GET'),A),true,'Incoming workspace is read while the outgoing save is pending');
        assert.equal(await page.getByRole('button',{name:'Add timepoint',exact:true}).isEnabled(),true);
        await page.getByRole('button',{name:'Add timepoint',exact:true}).click();
        assert.equal(await page.getByRole('dialog').count(),1);await page.keyboard.press('Escape');
        await page.evaluate(()=>releaseOutgoing());assert.equal(await page.evaluate(()=>fastSwitch),true);
        assert.equal(await page.evaluate(()=>calls.slice(beforeFastSwitch).some(c=>c.path.endsWith('/timepoints'))),false,'Navigation does not add a redundant catalog round trip');
        await page.evaluate(async B=>{fetch=originalFetch;await BrachyBotTimepoints.select(B);},B);
        check('Navigation overlaps the incoming read with the fenced outgoing save and keeps Add responsive');

        await page.getByRole('button', { name: 'Add timepoint', exact: true }).click();
        assert.equal(await page.getByLabel('Stage', { exact: true }).inputValue(), 'preoperative');
        await page.getByLabel('Title', { exact: true }).fill('New scan');
        await page.getByLabel('Stage', { exact: true }).selectOption('intraoperative');
        const count = await page.evaluate(() => calls.filter(c => c.method === 'POST').length);
        await page.getByRole('button', { name: 'Save', exact: true }).click();
        assert.equal(await page.evaluate(() => calls.filter(c => c.method === 'POST').length), count);
        assert.equal(await page.getByRole('dialog').count(), 1);
        await page.getByLabel('Associated preoperative timepoint').selectOption(A);
        await page.getByRole('button', { name: 'Save', exact: true }).click();
        await page.waitForFunction(() => catalog.timepoints.some(r => r.title === 'New scan'));
        await page.waitForFunction(() => document.querySelector('#timepointStrip').getAttribute('aria-busy') === 'false'
            && BrachyBotTimepoints.captureTarget().timepointId.startsWith('created-'));
        assert.equal(await page.evaluate(() => catalog.timepoints.find(r => r.title === 'New scan').preoperative_timepoint_id), A);
        assert.equal(await page.evaluate(() => calls.some(c => /plan|segment|dose/.test(c.path) && c.method === 'POST')), false);
        check('Create defaults preoperative; intraoperative requires an explicit stable reference and triggers no planning');

        await page.evaluate(async A => BrachyBotTimepoints.select(A), A);
        await page.getByRole('button', { name: 'Manage', exact: true }).click();
        await page.getByRole('button', { name: 'Rename / stage', exact: true }).click();
        assert.equal(await page.getByLabel('Stage', { exact: true }).isDisabled(), true);
        await page.getByLabel('Title', { exact: true }).fill('<b>Renamed source</b>');
        await page.getByRole('button', { name: 'Save', exact: true }).click();
        await page.waitForFunction(A => BrachyBotTimepoints.getCatalog().timepoints.find(r => r.id === A).title.includes('Renamed source'), A);
        assert.equal(await page.locator(`#timepointTabs b`).count(), 0);
        assert.equal(await page.evaluate(B => BrachyBotTimepoints.getCatalog().timepoints.find(r => r.id === B).preoperative_timepoint_id, B), A);
        await page.evaluate(() => { blockDelete = true; });
        await page.getByRole('button', { name: 'Manage', exact: true }).click();
        await page.getByRole('button', { name: 'Delete', exact: true }).click();
        await page.waitForFunction(() => document.querySelector('#timepointStatus').textContent.includes('Dependent timepoints'));
        assert.equal(await page.evaluate(() => calls.some(c => c.method === 'DELETE')), false);
        check('Rename cannot change reference identity or inject HTML; dependency impact blocks delete before mutation');

        await page.getByRole('button', { name: 'Manage', exact: true }).click();
        await page.getByRole('button', { name: 'Restore', exact: true }).click();
        await page.locator('#_confirmYes').click();
        await page.waitForFunction(() => BrachyBotTimepoints.getCatalog().timepoints.find(r => r.id === 'deleted-c').deleted === false);
        assert.equal(await page.evaluate(() => nativeConfirmCalls), 0);
        await page.evaluate(() => { _i18nLang = 'zh'; dispatchEvent(new CustomEvent('i18nchange')); });
        assert.equal(await page.getByRole('button', { name: '添加时间点', exact: true }).count(), 1);
        assert.match(await page.locator('#timepointTabs').innerText(), /术前.*术中/s);
        await page.getByRole('button', { name: '管理', exact: true }).click();
        await page.keyboard.press('Escape');
        assert.equal(await page.getByRole('dialog').count(), 0);
        check('Restore reuses localized application confirmation; language updates and Escape dismiss are supported');

        await page.evaluate(B => { _i18nLang = 'en'; dispatchEvent(new CustomEvent('i18nchange'));
            window.openLanguageForm = BrachyBotTimepoints.editTimepoint(B); }, B);
        await page.getByLabel('Title', { exact: true }).fill('Clinician-defined scan name');
        await page.evaluate(() => { _i18nLang = 'zh'; dispatchEvent(new CustomEvent('i18nchange')); });
        assert.equal(await page.getByRole('dialog').getAttribute('lang'), 'zh-CN');
        assert.equal(await page.getByRole('heading', { name: '编辑时间点', exact: true }).count(), 1);
        assert.equal(await page.getByLabel('名称', { exact: true }).inputValue(), 'Clinician-defined scan name');
        assert.equal(await page.getByLabel('阶段', { exact: true }).locator('option').first().innerText(), '术前');
        assert.equal(await page.getByRole('button', { name: '保存', exact: true }).count(), 1);
        await page.evaluate(() => { _i18nLang = 'en'; dispatchEvent(new CustomEvent('i18nchange')); });
        assert.equal(await page.getByLabel('Title', { exact: true }).inputValue(), 'Clinician-defined scan name');
        await page.keyboard.press('Escape'); await page.evaluate(() => openLanguageForm);
        check('An open form follows global language without losing custom titles, values or focus behavior');

        await page.evaluate(async () => { _i18nLang = 'en'; dispatchEvent(new CustomEvent('i18nchange')); await BrachyBotTimepoints.select('deleted-c'); blockDelete = false; });
        await page.getByRole('button', { name: 'Manage', exact: true }).click();
        await page.getByRole('button', { name: 'Delete', exact: true }).click();
        await page.evaluate(() => { _i18nLang = 'zh'; dispatchEvent(new CustomEvent('i18nchange')); });
        assert.equal(await page.locator('#_confirmYes').innerText(), '删除');
        assert.equal(await page.locator('#_confirmNo').innerText(), '取消');
        assert.match(await page.locator('#timepointConfirmationMessage').innerText(), /Old scan/);
        await page.evaluate(() => { _i18nLang = 'en'; dispatchEvent(new CustomEvent('i18nchange')); });
        await page.locator('#_confirmYes').click();
        await page.waitForFunction(() => BrachyBotTimepoints.getCatalog().timepoints.find(r => r.id === 'deleted-c').deleted === true
            && document.querySelector('#timepointStrip').getAttribute('aria-busy') === 'false');
        assert.equal(await page.locator('[data-timepoint-id="deleted-c"]').count(), 0);
        const deletion = await page.evaluate(() => calls.find(c => c.method === 'DELETE'));
        assert.equal(deletion.headers['x-brachybot-timepoint'], 'deleted-c');
        assert.equal(deletion.headers['x-brachybot-session'], SID);
        assert.deepEqual(Object.keys(deletion.body), ['expected_revision']);
        check('Confirmed deletion saves the outgoing state, uses the explicit target header and retains a restorable catalog entry');

        await page.evaluate(async A => { await BrachyBotTimepoints.select(A); window.badWorkspaceScope = true; }, A);
        const beforeBadScope = await page.evaluate(() => paints.length);
        assert.equal(await page.evaluate(async B => BrachyBotTimepoints.select(B), B), false);
        assert.equal(await page.evaluate(() => paints.length), beforeBadScope);
        assert.match(await page.locator('#timepointStatus').innerText(), /workspace belongs to a different timepoint/);
        await page.evaluate(() => { badWorkspaceScope = false; });
        assert.equal(await page.evaluate(async B => BrachyBotTimepoints.select(B), B), true);
        assert.equal(await page.evaluate(() => mounted.report), 'Report B');
        check('A mismatched workspace identity cannot paint; retry succeeds without saving the cleared scene');

        await page.evaluate(() => { deferCatalog = true; window.oldCatalogPromise = BrachyBotTimepoints.refresh({ activate: false }); });
        await page.waitForFunction(() => !!window.finishCatalog);
        await page.evaluate(async () => { catalog.catalog_revision++; catalog.timepoints[0].title = 'Newest title'; deferCatalog = false;
            await BrachyBotTimepoints.refresh({ activate: false }); finishCatalog(); await oldCatalogPromise; });
        assert.equal(await page.evaluate(A => BrachyBotTimepoints.getCatalog().timepoints.find(r => r.id === A).title, A), 'Newest title');
        check('A delayed older catalog cannot revert a newer title or catalog revision');

        // A delayed hydration from the old Session must never commit after a Session switch.
        await page.evaluate(A => { deferPrepare = A; window.delayedSelect = BrachyBotTimepoints.select(A); }, A);
        await page.waitForFunction(() => !!window.finishPrepare);
        const paintsBefore = await page.evaluate(() => paints.length);
        await page.evaluate(async () => { activeSessionId = '22222222222222222222222222222222'; failCatalog = true; await BrachyBotTimepoints.refresh(); finishPrepare(); await delayedSelect; });
        assert.equal(await page.evaluate(() => paints.length), paintsBefore);
        assert.equal(await page.evaluate(() => disposals), 1);
        assert.equal(await page.evaluate(() => BrachyBotTimepoints.enabled()), false);
        assert.equal(await page.locator('#chatMessages').innerText(), 'Shared conversation sentinel');
        check('Session switch discards delayed prepared resources without painting or clearing shared chat');

        await page.evaluate(async SID => { activeSessionId = SID; failCatalog = false; deferPrepare = null; await BrachyBotTimepoints.refresh(); }, SID);
        const lastPatch = await page.evaluate(() => calls.filter(c => c.method === 'PATCH' && c.path.endsWith('/workspace')).at(-1));
        assert.equal(lastPatch.body.expected_state_revision !== undefined, true);
        assert.deepEqual(Object.keys(lastPatch.body.patch).sort(), ['report', 'ui']);
        assert.equal(Object.hasOwn(lastPatch.body, 'chat'), false);
        assert.equal(Object.hasOwn(lastPatch.body, 'agent'), false);
        await page.evaluate(async () => { failCatalog = true; await BrachyBotTimepoints.refresh(); });
        assert.equal(await page.locator('#timepointAdd').isDisabled(), true);
        assert.equal(await page.evaluate(() => BrachyBotTimepoints.enabled()), false);
        assert.deepEqual(errors, []);
        check('Presentation PATCH excludes shared chat/Agent snapshots and capability loss locks the strip');
        console.log(`${scenarios} synthetic timepoint browser scenarios passed.`);
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
