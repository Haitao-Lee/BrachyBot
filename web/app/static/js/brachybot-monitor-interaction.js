/* One edit, one evolving card. Only server-committed evidence enters here. */
(() => {
    const cards = new Map();
    let owner = '';
    let autoCompare = false, compareTimer = null;
    const timers = new Map();
    let announcementTimer=null, announcementKey='', resourceTimer=null, visualTimer=null;
    const samples = [];
    const timing = (name, milliseconds) => {
        if (!Number.isFinite(milliseconds) || milliseconds < 0) return;
        samples.push({name, milliseconds}); if (samples.length > 256) samples.shift();
    };
    window.getMonitorUXMetrics = () => {
        const result = {};
        for (const name of new Set(samples.map(item => item.name))) {
            const values = samples.filter(item => item.name === name).map(item => item.milliseconds).sort((a,b)=>a-b);
            result[name] = {count:values.length, p50_ms:values[Math.ceil(values.length*.5)-1], p95_ms:values[Math.ceil(values.length*.95)-1]};
        }
        return result; // aggregate timings only, no patient/object identifiers
    };
    const cancelRetry = card => {
        if (timers.has(card.id)) clearTimeout(timers.get(card.id));
        timers.delete(card.id);
    };
    const publish = () => window.renderMonitorDashboard?.([...cards.values()], {autoCompare});
    const text = (card, zh, en) => {
        // Retain explicit bilingual copies for transient asynchronous states.
        // Switching while "Computing" is pending must not strand old text.
        card.localePairs ||= new Map();
        card.localePairs.set(zh,[zh,en]);card.localePairs.set(en,[zh,en]);
        const language=monitorConversationLanguage(card.sessionId);
        return language === 'zh' ? zh : en;
    };
    const safe = value => String(value ?? '').replace(/[\\`*_{}\[\]<>|]/g, ' ');
    function announce(card){
        if(!document.body || typeof document.createElement!=='function' || !latest(card))return;
        const key=`${card.sessionId}:${card.runId}:${card.lastEventId}`;
        if(key===announcementKey)return;
        announcementKey=key;if(announcementTimer)clearTimeout(announcementTimer);
        // Coalesce rapid saves for assistive technology; do not read a full
        // report or move keyboard focus to each new background notification.
        announcementTimer=setTimeout(()=>{
            announcementTimer=null;if(!latest(card) || key!==announcementKey)return;
            let live=document.getElementById('monitorLiveAnnouncement');
            if(!live){live=document.createElement('div');live.id='monitorLiveAnnouncement';live.className='monitor-sr-only';
                live.setAttribute('role','status');live.setAttribute('aria-live','polite');live.setAttribute('aria-atomic','true');document.body.appendChild(live);}
            const counts=card.data.interaction?.conflict_counts || {};
            live.textContent=card.data.interaction?.dose_current
                ? text(card,'当前编辑的剂量反馈已更新。','Dose feedback for the current edit has updated.')
                : text(card,`编辑已保存。新增 ${counts.new || 0} 组、加重 ${counts.worsened || 0} 组相关间距问题。`,
                    `Edit saved. ${counts.new || 0} new and ${counts.worsened || 0} worsened related spacing conflicts.`);
        },180);
    }
    window.monitorGuidanceFor = (info, language) => info?.guidance?.localized?.[language]
        || (info?.guidance && info.language === language ? info.guidance : null);
    window.monitorInteractionFor = (info, language) => {
        if (!info) return info;
        if (info.localized?.[language]) return {...info,...info.localized[language],language};
        if (info.language === language) return info;
        // Compatibility with an already-running server: bilingual guidance is
        // authoritative wording, never a guess/LLM translation of old prose.
        const guide=window.monitorGuidanceFor(info,language),zh=language==='zh';
        return {...info,language,headline:guide?.title || (zh?'已保存的编辑记录':'Saved edit record'),
            assessment:{...info.assessment,title:guide?.title || (zh?'已保存的编辑记录':'Saved edit record')},
            dose_note:guide?.meaning || (zh?'切换语言不会重新计算剂量。':'A language change does not recompute dose.'),
            next_step:guide?.recommendation || '',
            metric_rows:(info.metric_rows || []).map(row=>({...row,
                metric:row.key==='plan_score' ? (zh?'评分':'Score') : /^v\d+|^d\d+/.test(row.key || '') ? row.key.toUpperCase() : row.metric,
                unit:['pp','百分点'].includes(row.unit) ? (zh?'百分点':'pp') : ['points','分'].includes(row.unit) ? (zh?'分':'points') : row.unit}))};
    };
    // Lettered references join prose, controls and actual Viewer annotations.
    // Internal IDs remain in the audit record, not the user's navigation task.
    window.monitorSpatialGuide = (info, evidence, language) => {
        const zh = language === 'zh', allowed = info?.spatial_refs || [];
        const changes = (evidence?.changed_objects || info?.objects || []).filter(item =>
            !item.dependent_on_needle && !item.derived_from_normalization && item.operation !== 'deleted');
        const pair = info?.assessment?.primary_pair || (info?.conflicts || []).find(item =>
            ['new','worsened','improved'].includes(item.change)) || info?.conflicts?.[0];
        const priority = info?.guidance?.focus_refs?.length ? info.guidance.focus_refs
            : pair ? [pair.first_id,pair.second_id] : [];
        const refs = [...new Set([...changes.slice(0,1).map(item=>String(item.id)),...priority,...changes.map(item=>String(item.id)),...allowed])]
            .filter(ref=>allowed.includes(ref)).slice(0,3);
        return refs.map((ref,index) => {
            const change = changes.find(item=>String(item.id)===ref);
            const kind = change?.kind || (pair && [pair.first_id,pair.second_id].includes(ref)
                ? pair.kind === 'needle_pairs' ? 'needles' : pair.kind === 'seed_pairs' ? 'seeds' : null : null);
            const noun = kind === 'needles' ? (zh?'针道':'needle') : kind === 'seeds' ? (zh?'粒子':'seed') : (zh?'对象':'object');
            const role = change ? (zh?`刚编辑的${noun}`:`Edited ${noun}`)
                : priority.includes(ref) ? (zh?'间距检查对象':'Spacing reference') : (zh?'相关对象':'Related object');
            return {ref,letter:String.fromCharCode(65+index),label:role,kind,role:change?'edited':priority.includes(ref)?'spacing':'related'};
        });
    };
    // Preserve reading and keyboard position across asynchronous view updates.
    // Removed/stale actions never regain focus as executable controls.
    window.preserveMonitorPresentation = root => {
        if (!root?.querySelectorAll) return () => {};
        const states = [...root.querySelectorAll('details')].map((node,index)=>({
            key:node.dataset.monitorSection || node.className || `details:${index}`,open:node.open}));
        const focused = document.activeElement, focusOwned = root.contains?.(focused);
        const owner=root.dataset?.monitorOwner;
        const key = focusOwned ? focused?.dataset?.brachyControlRef : null;
        const scrolls = []; let node = root;
        while (node) { if (node.scrollHeight > node.clientHeight) scrolls.push([node,node.scrollTop,node.scrollLeft]); node=node.parentElement; }
        return () => {
            if(owner!==root.dataset?.monitorOwner)return;
            [...root.querySelectorAll('details')].forEach((detail,index)=>{
                const saved=states.find(item=>item.key===(detail.dataset.monitorSection || detail.className || `details:${index}`));
                if(saved) detail.open=saved.open;
            });
            if (focusOwned && key) {
                const control=[...root.querySelectorAll('[data-brachy-control-ref]')].find(item=>item.dataset.brachyControlRef===key && !item.disabled);
                if (control) control.focus?.({preventScroll:true});
                else { const anchor=root.querySelector('.monitor-guidance-title') || root.querySelector('summary');
                    if(anchor){anchor.tabIndex=-1;anchor.focus?.({preventScroll:true});} }
            }
            for (const [element,top,left] of scrolls) {element.scrollTop=top;element.scrollLeft=left;}
        };
    };
    // Both chat and the resident panel render the same server-owned coaching
    // copy. Text nodes only: object names and advice can never inject markup.
    window.createMonitorGuidancePanel = (info, language, historical = false, context = null) => {
        const guide = window.monitorGuidanceFor(info, language);
        if (!guide || typeof document.createElement !== 'function') return null;
        const zh = language === 'zh', panel = document.createElement('section');
        panel.className = 'monitor-guidance'; panel.dataset.state = historical ? 'historical' : guide.state;
        const spatial = window.monitorSpatialGuide(info,context?.evidence,language);
        const readable = value => {
            let copy=String(value || '');
            for (const item of [...spatial].sort((a,b)=>b.ref.length-a.ref.length)) {
                // Match whole identifiers, never substrings of ordinary prose
                // (e.g. an ID "a" must not corrupt "Locate" or the article a).
                if(item.ref.length<2)continue;
                const escaped=item.ref.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
                copy=copy.replace(new RegExp(`(^|[^A-Za-z0-9_-])${escaped}(?=$|[^A-Za-z0-9_-])`,'g'),
                    (_match,prefix)=>`${prefix}${item.letter}`);
            }
            return copy;
        };
        const firstSentence=value=>{const copy=String(value || ''),match=copy.match(/[。！？]|[.!?](?=\s+[A-Z]|$)/);
            const end=match ? match.index+1 : copy.length;return [copy.slice(0,end),copy.slice(end).trim()];};
        const heading = document.createElement('p'); heading.className = 'monitor-guidance-title';
        heading.tabIndex=-1;
        heading.textContent = historical ? (zh ? '这条反馈是较早记录，请查看最新编辑。' : 'This feedback is historical; use the latest edit.') : readable(guide.title);
        panel.appendChild(heading);
        const field = (label, content, name, parent = panel) => {
            if (!content) return;
            const row = document.createElement('div'); row.className = `monitor-guide-${name}`;
            const term = document.createElement('strong'); term.textContent = label;
            const detail = document.createElement('p'); detail.textContent = readable(content);
            row.append(term,detail); parent.appendChild(row);
        };
        field(zh ? '你这一步' : 'Your edit', guide.observation, 'observation');
        if(historical)return panel;
        // A compact status ledger distinguishes saved geometry from a current
        // dose. Neither a successful save nor a kept edit is a safety verdict.
        const ledger=document.createElement('div');ledger.className='monitor-guide-ledger';
        const saved=document.createElement('span');saved.textContent=zh?'编辑已保存':'Edit saved';
        const dose=document.createElement('span');dose.textContent=info.dose_current
            ? (zh?'剂量已更新':'Dose current') : (zh?'剂量待更新':'Dose stale');
        dose.dataset.state=info.dose_current?'current':'pending';ledger.append(saved,dose);panel.insertBefore(ledger,heading);
        const editCount=info.assessment?.edit_count || context?.evidence?.dose?.edit_count;
        if(info.dose_comparable && Number.isInteger(editCount) && editCount>1){const scope=document.createElement('span');
            scope.textContent=zh?`${editCount} 次编辑的合计影响`:`Combined effect of ${editCount} edits`;
            scope.dataset.state='sequence';ledger.appendChild(scope);}
        const [meaning,meaningDetails]=firstSentence(guide.meaning);
        field(zh ? '意味着什么' : 'What it means', meaning, 'meaning');
        if(info.dose_comparable){
            const rows=(info.metric_rows || []).filter(row=>[row.before,row.after,row.delta].every(Number.isFinite));
            const key=row=>String(row.key || row.metric || '').toLowerCase();
            const selected=['v100','d90','v200'].map(name=>rows.find(row=>key(row)===name)).filter(Boolean);
            if(!selected.some(row=>key(row)==='v200')){const hot=rows.find(row=>key(row)==='v150');if(hot)selected.push(hot);}
            const organ=rows.find(row=>key(row).startsWith('oar:'));if(organ)selected.push(organ);
            if(selected.length){
                const table=document.createElement('table');table.className='monitor-key-changes';
                const caption=document.createElement('caption');caption.textContent=zh?'可比剂量的实测差值（节选）':'Measured comparable dose changes (selected)';table.appendChild(caption);
                const head=document.createElement('thead'),tr=document.createElement('tr');
                for(const label of [zh?'指标':'Metric',zh?'前 → 后':'Before → after',zh?'变化':'Change']){
                    const cell=document.createElement('th');cell.scope='col';cell.textContent=label;tr.appendChild(cell);}
                head.appendChild(tr);table.appendChild(head);
                const body=document.createElement('tbody');
                for(const row of selected){const tr=document.createElement('tr');
                    const delta=Math.abs(row.delta)<.005 ? (zh?'<0.01（显示精度）':'<0.01 (display precision)')
                        : `${row.delta>0?'+':''}${row.delta.toFixed(2)} ${row.unit || ''}`;
                    for(const value of [row.metric,`${row.before.toFixed(2)} → ${row.after.toFixed(2)}`,delta]){
                        const cell=document.createElement('td');cell.textContent=String(value);tr.appendChild(cell);}body.appendChild(tr);}
                table.appendChild(body);panel.appendChild(table);
            }
        }
        if (!historical) {
            if (spatial.length && context) {
                const location = document.createElement('div'); location.className='monitor-location';
                const status = window.getMonitorSpatialState?.(context.evidence);
                location.dataset.state=status?.status || 'unavailable';
                const located = status?.status==='located' && spatial.some(item=>status.refs.includes(item.ref));
                const note=document.createElement('p'); note.className='monitor-location-status';
                const visibleLetters=spatial.filter(item=>status?.refs?.includes(item.ref)).map(item=>item.letter).join(' / ');
                const missingLetters=spatial.filter(item=>!status?.refs?.includes(item.ref)).map(item=>item.letter).join(' / ');
                note.textContent=located ? (zh?`Viewer 已标出 ${visibleLetters}。点击字母可单独查看。`:`Viewer marks ${visibleLetters}. Select a letter to inspect it.`)
                    : (zh?'对象尚未在当前画面定位。点击下方字母查看。':'Objects are not located in this view. Select a letter to inspect.');
                if(located && missingLetters) note.textContent+=zh?` ${missingLetters} 未在当前画面中定位。`:` ${missingLetters} is not located in the current view.`;
                location.appendChild(note);
                const legend=document.createElement('div');legend.className='monitor-location-legend';
                const availability=window.getMonitorTargetAvailability?.(spatial.map(item=>item.ref),context.evidence) || [];
                const availabilityLabels=zh ? {hidden:'已隐藏',loading:'加载中',not_loaded:'尚未加载',not_renderable:'不可见',unavailable:'不可用'}
                    : {hidden:'Hidden',loading:'Loading',not_loaded:'Not loaded',not_renderable:'Not visible',unavailable:'Unavailable'};
                const captureBusy=!!(typeof trainingMonitorState!=='undefined' && trainingMonitorState.screenshotPendingRunId || window.__reportCaptureActive);
                for(const item of spatial){const button=document.createElement('button');button.type='button';button.className='btn btn-sm monitor-location-chip';
                    const target=availability.find(target=>target.ref===item.ref);
                    button.dataset.letter=item.letter;button.textContent=`${item.letter} · ${item.label}${availabilityLabels[target?.state] ? ` · ${availabilityLabels[target.state]}` : ''}`;button.title=item.ref;
                    button.dataset.brachyControlRef=`monitor:${context.runId}:${context.id}:locate:${item.ref}`;
                    button.disabled=!context.current || !!context.busy || captureBusy;
                    button.addEventListener('click',()=>window.runMonitorCheckpointAction(context.id,'focus',{refs:[item.ref]}));legend.appendChild(button);}
                location.appendChild(legend);panel.appendChild(location);
                const blocked=availability.filter(item=>item.state!=='visible');
                if(blocked.length && context.current){
                    const recovery=document.createElement('div');recovery.className='monitor-location-recovery';
                    const message=document.createElement('p');
                    message.textContent=zh?'定位不会自动改动显示设置。可直接找到对应数据；仅在你点击后显示隐藏对象。'
                        :'Locating does not change display settings. Find the exact data row; hidden objects are shown only on your request.';
                    recovery.appendChild(message);
                    for(const target of blocked){const item=spatial.find(item=>item.ref===target.ref);
                        if(target.state==='unavailable')continue;
                        const add=(action,label)=>{const button=document.createElement('button');button.type='button';button.className='btn btn-sm';
                            button.textContent=label;button.disabled=!!context.busy || captureBusy;
                            button.dataset.brachyControlRef=`monitor:${context.runId}:${context.id}:${action}:${target.ref}`;
                            button.addEventListener('click',()=>window.runMonitorCheckpointAction(context.id,action,{refs:[target.ref]}));recovery.appendChild(button);};
                        if(target.revealable)add('show_target',zh?`显示 ${item.letter} 并定位`:`Show and locate ${item.letter}`);
                        add('tree',zh?`在数据树定位 ${item.letter}`:`Find ${item.letter} in Data Tree`);
                    }
                    location.appendChild(recovery);
                }
                if(captureBusy){const waiting=document.createElement('small');waiting.textContent=zh?'正在准备证据图；完成后可定位，当前显示不会被争用。'
                    :'Preparing evidence images; location controls resume afterward without competing for the view.';location.appendChild(waiting);}
                if(status?.canRestore){const back=document.createElement('button');back.type='button';back.className='btn btn-sm monitor-return-view';
                    back.textContent=zh?'返回我的视角':'Return to my view';back.disabled=!context.current || !!context.busy;
                    back.dataset.brachyControlRef=`monitor:${context.runId}:${context.id}:return-view`;
                    back.addEventListener('click',()=>window.runMonitorCheckpointAction(context.id,'clear_focus'));location.appendChild(back);}
                if(located && context.evidence?.changed_objects?.some(obj=>obj.operation==='moved' && !obj.dependent_on_needle && !obj.derived_from_normalization)){
                    const key=document.createElement('small');key.textContent=context.preview
                        ? (zh?'蓝/橙/粉箭头记录刚才的移动；紫色箭头指向只读预览位置，都不是剂量最优方向。':'Blue/amber/pink arrows record the last move; purple arrows indicate the read-only preview, not dose-optimal directions.')
                        : (zh?'彩色箭头记录刚才的移动，不是建议下一步拖动方向。':'Colored arrows record the last move, not a recommended next direction.');location.appendChild(key);
                }
            }
            const [recommendation,choices]=firstSentence(guide.recommendation);
            field(zh ? '建议先做' : 'Recommended next step', recommendation, 'recommendation');
            const secondary=document.createElement('details');secondary.className='monitor-guide-followup';secondary.dataset.monitorSection='guide-followup';
            const summary=document.createElement('summary');summary.textContent=zh?'其他选择与验证方法':'Other options and verification';
            summary.dataset.brachyControlRef=`monitor:${context?.runId}:${context?.id}:guide-followup`;secondary.appendChild(summary);
            field(zh?'为什么':'Why',meaningDetails,'reason',secondary);
            field(zh?'其他选择':'Other options',choices,'choices',secondary);
            if (context && Array.isArray(guide.steps)) {
                const actions = document.createElement('div'); actions.className = 'monitor-guide-actions';
                const alternatives=document.createElement('div');alternatives.className='monitor-guide-actions';
                let primaryAdded=false;
                const previewStep=context.preview && context.canConfirmPreview ? {
                    action:context.candidateId?'apply':'restore',label:context.candidateId
                        ? (zh?'确认应用候选位置':'Confirm candidate position') : (zh?'确认恢复编辑前位置':'Confirm pre-edit restoration')
                } : null;
                for (const step of [...(previewStep?[previewStep]:[]),...guide.steps.slice(0,3)]) {
                    if ((!['focus','dose','details','preview','spacing'].includes(step.action)
                        && step!==previewStep) || (['preview','spacing'].includes(step.action) && info.schema_version !== 3)) continue;
                    const button = document.createElement('button'); button.type='button'; button.className='btn btn-sm';
                    const primary=!primaryAdded && (step===previewStep || !previewStep && step.action===info.primary_action);
                    if(primary){button.className += ' monitor-primary-action';primaryAdded=true;}
                    button.textContent=step.label; button.disabled=!context.current || !!context.busy;
                    button.dataset.guideAction=step.action;
                    button.dataset.brachyControlRef=`monitor:${context.runId}:${context.id}:guide:${step.action}`;
                    button.addEventListener('click',()=>window.runMonitorCheckpointAction(context.id,step.action,
                        {refs:step.refs,objectId:step.object_id,candidateId:context.candidateId,surface:context.surface}));
                    (primary ? actions : alternatives).appendChild(button);
                }
                if (actions.childNodes.length || context.preview) panel.appendChild(actions);
                if (alternatives.childNodes.length) secondary.appendChild(alternatives);
                if(context.preview){const close=document.createElement('button');close.type='button';close.className='btn btn-sm';
                    close.textContent=zh?'关闭预览，不修改':'Close preview, no change';close.disabled=!!context.busy;
                    close.dataset.brachyControlRef=`monitor:${context.runId}:${context.id}:dismiss-preview`;
                    close.addEventListener('click',()=>window.runMonitorCheckpointAction(context.id,'dismiss_preview'));actions.appendChild(close);
                    const note=document.createElement('p');note.className='monitor-preview-note';
                    note.textContent=zh?'紫色是预览位置，尚未修改；确认后仍需安全检查和剂量重算。':'Purple geometry is a preview, not a change. Confirmation still requires safety checks and dose recomputation.';
                    panel.insertBefore(note,actions);}
            }
            const location=panel.querySelector('.monitor-location');
            if(location)panel.appendChild(location);
            field(zh ? '如何确认' : 'How to verify', guide.verification, 'verification', secondary);
            if (guide.findings?.length) {
                const list=document.createElement('ul');list.className='monitor-guide-findings';
                for(const finding of guide.findings.slice(0,4)){const item=document.createElement('li');item.textContent=readable(finding);list.appendChild(item);}secondary.appendChild(list);
            }
            if(guide.limitation){const note=document.createElement('small');note.className='monitor-guide-limit';note.textContent=guide.limitation;secondary.appendChild(note);}
            if(spatial.length){const note=document.createElement('small');note.className='monitor-guide-limit';
                note.textContent=zh?'定位仅调整取景，不改几何或配色；轮廓可透过遮挡显示，不表示遮挡已消除。':'Locate only frames the view, without changing geometry or colors. Outlines may show through occluders; they do not remove them.';secondary.appendChild(note);}
            panel.appendChild(secondary);
        }
        if (historical && guide.findings?.length) {
            const list = document.createElement('ul'); list.className = 'monitor-guide-findings';
            for (const finding of guide.findings.slice(0,4)) { const item = document.createElement('li'); item.textContent = finding; list.appendChild(item); }
            panel.appendChild(list);
        }
        if (historical && guide.limitation) { const note = document.createElement('small'); note.className = 'monitor-guide-limit'; note.textContent = guide.limitation; panel.appendChild(note); }
        return panel;
    };
    // One measurement vocabulary for chat and the resident workspace. Never
    // call a finite-surface clearance an axis distance, or missing data zero.
    window.monitorConflictText = (pair, language = 'en') => {
        const zh = language === 'zh', needle = pair.kind === 'needle_pairs';
        const exact = pair.clearance_basis === 'finite_parallel_cylinders';
        const gap = pair.surface_clearance_mm;
        const value = Number.isFinite(gap) ? gap : pair.distance_mm;
        const label = Number.isFinite(gap)
            ? exact ? (zh ? '实体表面间隙' : 'finite surface gap')
                : (zh ? '轴线模型间隙下界' : 'axis-model clearance bound')
            : (zh ? '轴线距离' : 'axis distance');
        const status = {new:zh?'新增':'new', worsened:zh?'加重':'worsened',
            improved:zh?'改善但仍需复核':'improved, still needs review', existing:zh?'原有':'pre-existing'}[pair.change];
        const minimum = pair.minimum_clearance_mm;
        return [status, `${needle ? (zh?'针道':'needle ') : ''}${label} ${Number.isFinite(value) ? value.toFixed(2) + ' mm' : (zh?'未核实':'unverified')}`,
            Number.isFinite(minimum) ? (zh ? `配置间隙要求 ${minimum.toFixed(2)} mm` : `configured gap ${minimum.toFixed(2)} mm`) : '',
            exact && Number.isFinite(gap) && Number.isFinite(minimum)
                ? (zh ? `尚差 ${Math.max(0, minimum-gap).toFixed(2)} mm（不是建议移动量）`
                    : `gap shortfall ${Math.max(0, minimum-gap).toFixed(2)} mm (not a movement prescription)`) : '']
            .filter(Boolean).join(' · ');
    };
    const current = card => typeof trainingMonitorState !== 'undefined'
        && trainingMonitorState.active && trainingMonitorState.runId === card.runId
        && _activeApiSessionId() === card.sessionId;
    const latest = card => current(card) && !card.superseded
        && (typeof manualPlanningState === 'undefined'
            || (!manualPlanningState.monitorInteractionActive
                && Number(manualPlanningState.planningVersion) === Number(card.evidence.after_version)
                && String(manualPlanningState.planningId) === String(card.evidence.planning_id)))
        && (typeof _monitorEvidenceMatchesLiveGeometry !== 'function'
            || _monitorEvidenceMatchesLiveGeometry(card.evidence));
    const errorText = (card, code) => {
        if (code === 'monitor_stopped') return text(card,
            '监测已停止，本检查点未完成截图；已记录的文字结果仍保留。',
            'Monitoring stopped before this image completed; recorded text is retained.');
        if (code === 'monitor_checkpoint_superseded') return text(card,
            '后续编辑已改变几何，旧检查点不再补拍；请查看最新编辑卡片。',
            'A newer edit changed the geometry; use the latest card for images.');
        if (code === 'viewer_tab_hidden') return text(card,
            '页面在后台，截图已暂缓；返回页面后会自动核对版本并补拍。',
            'Capture deferred in the background; returning will recheck the revision before retrying.');
        const reasons = {
            monitor_interaction_busy: ['用户仍在操作，截图等待空闲', 'capture is waiting until the interaction is idle'],
            monitor_targets_unavailable: ['当前 Viewer 尚无可核验的编辑对象', 'edited objects are not yet verifiable in the Viewer'],
            target_object_not_loaded_in_live_data_tree: ['目标数据节点尚未加载', 'target data nodes have not loaded'],
            workspace_visual_restore_incomplete: ['Viewer 资源仍在恢复', 'Viewer resources are still restoring'],
            attachment_not_rendered: ['图像没有写入对话附件', 'images were not delivered to chat attachments'],
            target_not_verified_visible_in_viewer: ['图中目标位置不可核验', 'target positions could not be verified in the image'],
            capture_unavailable: ['截图执行入口不可用', 'the capture executor is unavailable'],
        };
        if (reasons[code]) return text(card,
            `未完成截图：${reasons[code][0]}。文字仍来自已保存的编辑；可在资源就绪后重试。`,
            `Image not captured: ${reasons[code][1]}. Text reflects the saved edit; retry when ready.`);
        return text(card, '本次截图尚未完成；可以重试，以下文字仍是已保存的编辑结果。',
            'Image not captured yet. Retry below; the text still describes the saved edit.');
    };

    function render(card, notify = true) {
        if (card.sessionId !== _activeApiSessionId() || card.runId !== trainingMonitorState.runId) return;
        window.reconcileMonitorSpatialVisibility?.();
        if(card.displayNotice && window.getMonitorTargetAvailability){
            const signature=JSON.stringify(window.getMonitorTargetAvailability(card.displayNotice.refs,card.evidence));
            if(signature!==card.displayNotice.signature){card.notice='';card.displayNotice=null;}
        }
        card.language=monitorConversationLanguage(card.sessionId);
        for(const field of ['busy','notice','decision']){
            const pair=card.localePairs?.get(card[field]);
            if(pair)card[field]=pair[card.language==='zh'?0:1];
        }
        const info = window.monitorInteractionFor(card.data.interaction && {...card.data.interaction,
            language:card.data.interaction.language || card.data.language},card.language);
        const lines = [text(card, '**这次编辑的反馈**', '**Feedback on this edit**')];
        if (card.superseded) lines.push(text(card, '此卡片记录较早的编辑；操作入口已关闭。',
            'This card records an earlier edit; its actions are no longer available.'));
        if (info) {
            const guide = window.monitorGuidanceFor(info,card.language);
            if (guide) {
                lines.push(guide.title, guide.observation, guide.meaning);
                if (!card.superseded) lines.push(`**${text(card,'建议先做','Recommended next step')}**`,guide.recommendation,
                    `**${text(card,'如何确认','How to verify')}**`,guide.verification);
            } else lines.push(info.assessment?.title || info.headline);
            for (const obj of info.objects || []) {
                const verb = obj.operation === 'moved'
                    ? text(card, `移动 ${Number(obj.distance_mm).toFixed(2)} mm`, `moved ${Number(obj.distance_mm).toFixed(2)} mm`)
                    : text(card, ({added:'新增', deleted:'删除', reoriented:'方向或归属改变'})[obj.operation] || obj.operation, obj.operation);
                lines.push(`- **${safe(obj.id)}**：${verb}`);
            }
            for (const pair of info.conflicts || []) {
                lines.push(`- ${safe(pair.first_id)} ↔ ${safe(pair.second_id)}：${window.monitorConflictText(pair, card.language)}`);
            }
            const counts = info.conflict_counts || {};
            if (counts.resolved) lines.push(text(card, `已消除 ${counts.resolved} 组相关间距问题。`, `${counts.resolved} related spacing conflicts resolved.`));
            if (counts.existing) lines.push(text(card, `另有 ${counts.existing} 组在编辑前已存在，不归因于这次操作。`, `${counts.existing} conflicts predated this edit and are not attributed to it.`));
            const related = info.related_object_counts || {};
            if (related.dependent) lines.push(text(card, `${related.dependent} 个关联粒子随针道更新，并非独立拖动。`, `${related.dependent} associated seeds followed the needle update, not independent drags.`));
            if (related.normalized) lines.push(text(card, `${related.normalized} 个粒子仅在保存时刷新方向或归属。`, `${related.normalized} seeds only had orientation or ownership normalized on save.`));
            for (const move of info.return_movements || []) {
                if (!Array.isArray(move.vector_mm) || move.vector_mm.length !== 3 || !move.vector_mm.every(Number.isFinite)) continue;
                const label = `${safe(move.object_id)}${move.endpoint ? text(card, ` 端点 ${move.endpoint}`, ` endpoint ${move.endpoint}`) : ''}`;
                lines.push(text(card, `${label} 返回编辑前位置的患者坐标位移：[${move.vector_mm.map(v=>`${v>=0?'+':''}${v.toFixed(2)}`).join(', ')}] mm。`,
                    `${label} pre-edit return displacement in patient coordinates: [${move.vector_mm.map(v=>`${v>=0?'+':''}${v.toFixed(2)}`).join(', ')}] mm.`));
            }
            if (info.return_movements?.length) lines.push(text(card, '上述向量不是屏幕拖动方向，也不是剂量最优方向；恢复操作仍需通过安全检查。', 'These vectors are not screen or dose-optimal directions; restoration still requires safety validation.'));
            lines.push(`**${text(card, '剂量对比', 'Dose comparison')}**`, info.dose_note);
            if (info.metric_rows?.length) {
                lines.push(text(card, '| 指标 | 编辑前 | 编辑后 | 差值 |', '| Metric | Before | After | Change |'),
                    '|---|---:|---:|---:|');
                for (const row of info.metric_rows) lines.push(`| ${safe(row.metric)} | ${Number(row.before).toFixed(2)} | ${Number(row.after).toFixed(2)} | ${row.delta >= 0 ? '+' : ''}${Number(row.delta).toFixed(2)} ${safe(row.unit)} |`);
            }
            lines.push(`**${text(card, '下一步', 'Next step')}**`, info.next_step);
        } else lines.push(card.data.language===card.language ? card.data.feedback_localized || card.data.feedback || ''
            : text(card,'此旧记录未保存双语版本；原始记录仍保留，未重新分析或改变事实。',
                'This older record has no bilingual projection. Its original record is retained; no reanalysis or fact change was performed.'));
        if (card.busy) lines.push(card.busy);
        if (card.notice) lines.push(card.notice);
        if (card.decision) lines.push(card.decision);
        const captureText = ['ready', 'partial'].includes(card.captureState) ? text(card,
            '已核验的图像附在本卡片下方。若图中有紫色箭头，它表示返回编辑前位置的方向，不表示计算得到的最优位置。',
            'Verified images are attached below. Purple arrows, when present, indicate the pre-edit position, not an optimized destination.')
            : ['failed', 'deferred'].includes(card.captureState) ? errorText(card, card.captureError)
                : card.data.suggested_screenshot ? text(card, '正在准备本次编辑的定位截图…', 'Preparing location images for this edit…') : '';
        if (captureText) lines.push(captureText);
        if (card.captureState === 'partial') lines.push(text(card,
            `仅部分图像已交付${card.omittedRefs?.length ? `；未核验对象：${card.omittedRefs.map(safe).join('、')}` : ''}。不能据缺失图像判断位置。`,
            `Only partial images were delivered${card.omittedRefs?.length ? `; unverified objects: ${card.omittedRefs.map(safe).join(', ')}` : ''}. Missing images establish no location.`));
        if (card.captureRecords?.length && !['ready','partial'].includes(card.captureState)) lines.push(text(card,
            '此卡片下方还保留先前检查点的图像；它们不是本次待完成截图的结果。', 'Earlier checkpoint images remain below; they are not evidence of this pending capture.'));
        const existing=typeof document.querySelectorAll==='function' ? [...document.querySelectorAll('[data-message-id]')]
            .find(node=>node.dataset.messageId===card.messageId) : null;
        const restorePresentation=window.preserveMonitorPresentation(existing);
        const content=lines.join('\n\n').replace(/\|\n\n\|/g, '|\n|');
        // Capture outcomes change the status strip, not the user's open record
        // or selected text. Only replace persisted content when it changed.
        if(content!==card.renderedContent || !existing) addChat('bot-response', content, false,
            card.createdAt, false, card.sessionId, {requestId: card.requestId,
                messageId: card.messageId, messageKind:'monitor_feedback', responseLanguage: card.language});
        card.renderedContent=content;
        attachActions(card);
        restorePresentation();
        if (notify) {publish();announce(card);}
    }

    async function capture(card) {
        if (!current(card) || card.superseded || card.captureState === 'pending') return;
        if (manualPlanningState.monitorInteractionActive || window.__monitorCameraInteracting || window.__reportCaptureActive) {
            card.captureState = 'deferred'; card.captureError = 'monitor_interaction_busy'; render(card); return;
        }
        if (!latest(card)) return;
        cancelRetry(card);
        card.resourceSignature=resourceSignature(card);
        card.captureState = 'pending'; render(card);
        await reportUIEvent(card.data.event?.type || 'manual.edit', '', {}, {cachedCheckpoint: card.data});
    }

    function resourceSignature(card) {
        const refs=window.monitorSpatialGuide(card.data.interaction,card.evidence,card.language).map(item=>item.ref);
        const targets=window.getMonitorTargetAvailability?.(refs,card.evidence) || [];
        // Loaded hidden geometry can be revealed by the existing temporary
        // capture transaction. Loading flags alone never establish readiness.
        return targets.filter(item=>item.loaded && ['visible','hidden','not_renderable'].includes(item.state))
            .map(item=>item.ref).sort().join('|');
    }
    window.notifyMonitorResourcesReady = detail => {
        if(detail && (detail.session_id!==_activeApiSessionId()
            || detail.planning_id && String(detail.planning_id)!==String(manualPlanningState.planningId)
            || detail.planning_version!=null && Number(detail.planning_version)!==Number(manualPlanningState.planningVersion)))return;
        if(resourceTimer)clearTimeout(resourceTimer);
        const owned=`${_activeApiSessionId()}:${trainingMonitorState.runId}`;
        resourceTimer=setTimeout(()=>{
            resourceTimer=null;if(owned!==`${_activeApiSessionId()}:${trainingMonitorState.runId}`)return;
            const card=[...cards.values()].reverse().find(latest);
            if(!card)return;
            // Readiness may arrive after the bounded timer retries expired.
            // Resume only on actual new exact-target geometry, at most twice
            // per checkpoint; no polling, regeneration or hidden dose job.
            const signature=resourceSignature(card);
            if(!window.__monitorCameraInteracting && !document.hidden)window.resumeMonitorSpatialAssistance?.();
            if(!signature || signature===card.resourceSignature || !card.data.suggested_screenshot
                || !['failed','deferred','partial'].includes(card.captureState)
                || (card.resourceRetries || 0)>=2 || trainingMonitorState.screenshotPendingRunId
                || window.__reportCaptureActive
                || window.isWorkspacePresentationWriteLocked?.(card.sessionId))return;
            const previous=new Set((card.resourceSignature || '').split('|').filter(Boolean));
            if(!signature.split('|').some(ref=>!previous.has(ref)))return;
            if(document.hidden || window.__monitorCameraInteracting){
                card.captureState='deferred';card.captureError=document.hidden ? 'viewer_tab_hidden' : 'monitor_interaction_busy';
                render(card,false);return;
            }
            card.resourceRetries=(card.resourceRetries || 0)+1;
            void capture(card);
        },120);
    };
    window.addEventListener?.('brachybot:monitor-resources-ready',event=>window.notifyMonitorResourcesReady(event.detail));

    function retryCapture(card) {
        cancelRetry(card);
        if (!current(card) || card.superseded || ['monitor_checkpoint_superseded', 'monitor_stopped'].includes(card.captureError)) return;
        if (manualPlanningState.monitorInteractionActive) { card.captureState = 'deferred'; return; }
        if (!latest(card)) return;
        // Hidden pages wait for visibility, not a timer loop. Permanent
        // grounding failures retain text; transient failures have two retries.
        if (document.hidden) { card.captureState = 'deferred'; return; }
        if (!['monitor_interaction_busy', 'viewer_tab_hidden', 'capture_failed', 'workspace_visual_restore_incomplete',
            'attachment_not_rendered', 'monitor_targets_unavailable'].includes(card.captureError)) return;
        if ((card.retryCount || 0) >= 2 || typeof setTimeout !== 'function') return;
        const revision = card.lastEventId;
        card.retryCount = (card.retryCount || 0) + 1;
        card.captureState = 'deferred';
        timers.set(card.id, setTimeout(() => {
            timers.delete(card.id);
            if (revision === card.lastEventId && latest(card)) void capture(card);
        }, card.retryCount * 1500));
    }

    window.runMonitorCheckpointAction = async (id, action, options = {}) => {
        const card = cards.get(id);
        if (!card || !latest(card) || card.busy) return false;
        if (action === 'capture') { card.retryCount = 0; await capture(card); return true; }
        if (action === 'details') {
            card.detailsOpen=!card.detailsOpen;
            if(typeof document.querySelectorAll==='function'){
                const row=[...document.querySelectorAll('[data-message-id]')].find(item=>item.dataset.messageId===card.messageId);
                const detail=row?.querySelector('.monitor-feedback-details');if(detail)detail.open=!!card.detailsOpen;
                if(detail && card.detailsOpen)detail.querySelector('summary')?.focus?.({preventScroll:true});
            }
            publish();
            if(options.surface==='dashboard' && card.detailsOpen){
                const record=document.querySelector?.('#monitorDashboard .monitor-object-record');
                if(record){record.open=true;record.querySelectorAll('details').forEach(item=>item.open=true);
                    record.querySelector('summary')?.focus?.({preventScroll:true});record.scrollIntoView?.({block:'nearest',behavior:'auto'});}
            }
            return true;
        }
        if(action==='dismiss_preview' || action==='clear_focus'){
            card.previewGeometry=null;card.previewCandidate=null;card.previewCandidates=[];
            window.clearMonitorFocus?.(true);card.notice='';render(card);return true;
        }
        if (action === 'select_candidate') {
            const candidate = (card.previewCandidates || []).find(item=>item.candidate_id === options.candidateId);
            const geometry = {seeds:[{id:candidate?.object_id,position:candidate?.position,direction:candidate?.direction}],needles:[]};
            if (!candidate || !window.previewMonitorGeometry?.(geometry,card.evidence)) return false;
            card.previewGeometry = geometry;
            card.previewCandidate = candidate; render(card); return true;
        }
        if (action === 'preview' || action === 'spacing' || action === 'apply') {
            if (card.data.interaction?.schema_version !== 3) {
                card.notice = text(card,'当前服务尚未载入新版预览端点；原有监测仍可使用。请在安排后端重启后再试。',
                    'This server has not loaded the new preview endpoints; existing monitoring remains available. Retry after the backend restart.');
                render(card); return false;
            }
            if (card.previewBusy || (action === 'apply' && (!card.previewCandidate || options.candidateId !== card.previewCandidate.candidate_id))) return false;
            const requestEvent = card.lastEventId, started = Date.now();
            card.previewAbort?.abort();
            const abort = new AbortController(); card.previewAbort = abort;
            const timeout = setTimeout(() => abort.abort(), 15000);
            card.previewBusy = true; card.notice = text(card, '正在核对当前几何…', 'Checking current geometry…'); render(card);
            try {
                const response = await fetch(API + (action === 'apply' ? '/training/apply_candidate' : '/training/edit_preview'), {
                    signal:abort.signal, method:'POST', headers:{'Content-Type':'application/json','X-BrachyBot-Session':card.sessionId},
                    body:JSON.stringify({session_id:card.sessionId, monitor_run_id:card.runId, planning_id:card.evidence.planning_id,
                        planning_version:card.evidence.after_version, geometry_key:card.evidence.geometry_key, checkpoint_id:card.id,
                        mode:action === 'preview' ? 'previous' : 'spacing', token:card.evidence.restore_token,
                        object_id:options.objectId, candidate_id:options.candidateId, confirm:action === 'apply'})});
                const data = await response.json();
                if (!latest(card) || requestEvent !== card.lastEventId) return false;
                if (!response.ok || !data.success) throw Object.assign(new Error(data.code),{code:data.code});
                if (action === 'apply') {
                    _applyAuthoritativeManualSeeds(data);
                    window.clearMonitorFocus?.();
                    window.invalidateSurgicalGuidePresentation?.();
                    window.scheduleWorkspaceSave?.('monitor.candidate.applied');
                    if (data.monitor_checkpoint) void window.receiveMonitorCheckpoint?.(data.monitor_checkpoint);
                    return true;
                }
                card.previewCandidates = data.candidates || [];
                card.previewCandidate = null;
                if (action === 'preview') {
                    const ok = window.previewMonitorGeometry?.(data.geometry, card.evidence);
                    card.previewGeometry = ok ? data.geometry : null;
                    card.notice = ok ? text(card, '紫色虚线是编辑前位置的只读预览；未改动规划，也未证明原位置安全。',
                        'Purple dashed geometry previews the pre-edit position only; the plan is unchanged and its safety is not established.')
                        : text(card, '对象尚不可定位，未显示位置预览；规划未改动。', 'Objects cannot be located; no position preview or plan change was made.');
                } else card.notice = card.previewCandidates.length
                    ? text(card, '已找到仅通过局部间距和靶区采样检查的几何候选；未计算剂量。先预览，再决定是否应用。',
                        'Local spacing and sampled-target candidates found; dose was not computed. Preview before deciding whether to apply.')
                    : text(card, '有限搜索范围内未找到可验证候选；这不代表不存在解。可查看冲突、预览原位置或继续手动调整。',
                        'No verified candidate in this bounded search; this does not prove infeasibility. Inspect spacing, preview the prior position or adjust manually.');
                timing('preview_response', Date.now()-started);
                return true;
            } catch (error) {
                if (latest(card) && requestEvent === card.lastEventId) card.notice = error?.code === 'monitor_plan_busy'
                    ? text(card, '规划正在更新，未执行操作；完成后可重试。', 'Plan is updating; no action applied. Retry when ready.')
                    : text(card, '此次预览或应用未完成（状态过期、资源未就绪或请求取消）；未确认任何几何修改。',
                        'Preview/apply did not complete (stale state, missing resources or cancellation); no geometry change is confirmed.');
                return false;
            } finally {
                clearTimeout(timeout); if (card.previewAbort === abort) { card.previewAbort = null; card.previewBusy = false; render(card); }
            }
        }
        if (['focus','tree','show_target'].includes(action)) {
            const allowed = card.data.interaction?.spatial_refs || card.data.suggested_screenshot?.object_ids || [];
            const pair = card.data.interaction?.assessment?.primary_pair;
            const guidedRefs = card.data.interaction?.guidance?.focus_refs;
            const refs = options.refs || (guidedRefs?.length ? guidedRefs : pair ? [pair.first_id,pair.second_id] : allowed);
            if (!Array.isArray(refs) || !refs.length || !refs.every(ref => allowed.includes(ref))) return false;
            if (trainingMonitorState.screenshotPendingRunId || window.__reportCaptureActive
                || window.isWorkspacePresentationWriteLocked?.(card.sessionId)) {
                card.notice=text(card,'证据图或病例资源正在准备，显示操作暂缓；完成后可直接重试。',
                    'Evidence images or case resources are being prepared. Retry the display action when ready.');render(card);return false;
            }
            if(action==='tree'){
                const ok=refs.length===1 && !!window.locateMonitorDataTreeTarget?.(refs[0],card.evidence);
                card.notice=ok ? text(card,'已在数据树定位对应对象，未改变三维显示或规划。',
                    'The exact object is focused in Data Tree; 3D visibility and the plan are unchanged.')
                    : text(card,'对应数据行尚未就绪，未跳转到其他同名对象；加载完成后可重试。',
                        'The exact data row is not ready. No similarly named object was selected; retry after loading.');
                render(card);return !!ok;
            }
            if(action==='show_target'){
                const target=window.getMonitorTargetAvailability?.(refs,card.evidence)?.[0];
                if(refs.length!==1 || !target?.revealable || typeof executeUIContextAction!=='function')return false;
                const event=card.lastEventId;
                card.busy=text(card,'正在显示该对象…','Showing this object…');render(card);
                try{
                    for(const action_id of ['node_show','node_show_3d']){
                        if(!latest(card) || event!==card.lastEventId)return false;
                        const result=await executeUIContextAction({action_id,object_id:target.nodeId});
                        if(result?.success!==true)throw new Error('display_unconfirmed');
                    }
                    if(!latest(card) || event!==card.lastEventId)return false;
                    const verified=window.getMonitorTargetAvailability?.(refs,card.evidence)?.[0]?.state==='visible';
                    if(!verified)throw new Error('display_unconfirmed');
                    const located=window.focusMonitorCheckpoint?.(refs,card.evidence,
                        {labels:window.monitorSpatialGuide(card.data.interaction,card.evidence,card.language)});
                    if(located){card.previewGeometry=null;card.previewCandidate=null;card.previewCandidates=[];}
                    card.notice=located ? text(card,'已显示并定位该对象；保留原配色与透明度，未改变规划。',
                        'Object shown and located; its color, opacity and plan geometry are unchanged.')
                        : text(card,'该对象已显示；当前取景尚未完成，未声称已定位。',
                            'Object visibility is verified, but framing is incomplete; no location is claimed.');
                    card.displayNotice={refs,signature:JSON.stringify(window.getMonitorTargetAvailability(refs,card.evidence))};
                    return !!located;
                }catch(_){if(latest(card) && event===card.lastEventId)card.notice=text(card,
                    '尚未核验对象可见；请在对应数据行检查分组显示或透明度，未修改规划。',
                    'Visibility is not verified. Check the exact row for group visibility or opacity; the plan is unchanged.');return false;
                }finally{card.busy='';render(card);}
            }
            const ok = window.focusMonitorCheckpoint?.(refs, card.evidence,
                {labels:window.monitorSpatialGuide(card.data.interaction,card.evidence,card.language)});
            if(ok && card.previewGeometry){card.previewGeometry=null;card.previewCandidate=null;card.notice='';}
            if (ok) card.notice='';
            if (!ok) {const targets=window.getMonitorTargetAvailability?.(refs,card.evidence) || [];
                card.notice=targets.some(target=>target.state==='hidden' && target.revealable) ? text(card,
                    '对应对象已隐藏；使用字母下的“显示并定位”或“在数据树定位”，无需在全部针道中手动寻找。',
                    'The requested object is hidden. Use Show and locate or Find in Data Tree below its letter; no manual search through all needles is needed.')
                    : targets.some(target=>target.state==='hidden') ? text(card,
                        '对应对象或所在分组已隐藏；可直接在数据树定位，不会自动打开整组对象。',
                        'The object or its parent group is hidden. Find the exact row in Data Tree; the whole group will not be revealed automatically.')
                    : targets.some(target=>['loading','not_loaded'].includes(target.state)) ? text(card,
                        '对应对象尚在加载；文字反馈保留，资源就绪后会核对当前版本并续接证据。',
                        'The object is still loading. Feedback is retained; readiness will recheck the current revision and resume evidence.')
                    : text(card,'当前对象未完成可核验定位；可用字母下的入口找到对应数据行。',
                        'The object is not yet verifiably located. Use the control below its letter to find the exact data row.');}
            render(card);return !!ok;
        }
        if (action === 'dose') {
            if (typeof recomputeManualDose !== 'function' || manualPlanningState.doseRecomputeRunning
                || card.data.interaction?.dose_current) return false;
            card.busy = text(card, '剂量计算中；完成后会更新这里的对比结果。', 'Computing dose; this comparison will update when ready.');
            render(card);
            try {
                const result = await recomputeManualDose('monitor_compare');
                if (!result?.success) card.notice = text(card, '剂量重算未完成，请查看计算错误后重试。', 'Dose recomputation did not complete; review the error and retry.');
                return !!result?.success;
            } catch (_) {
                card.notice = text(card, '剂量重算未完成，请稍后重试。', 'Dose recomputation did not complete; retry shortly.');
                return false;
            } finally { card.busy = ''; render(card); }
        }
        if (!['keep', 'restore'].includes(action) || !card.evidence.restore_token || card.decision) return false;
        card.busy = text(card, '正在提交操作…', 'Applying decision…'); render(card);
        try {
            const result = await window.performMonitorEditDecision(card.evidence.restore_token, action === 'keep',
                {sessionId: card.sessionId, runId: card.runId, language: card.language});
            if(result?.success!==true)card.notice=text(card,'服务器尚未确认这次选择；规划修改不能视为完成。请核对状态后重试。',
                'The server has not confirmed this choice. Do not treat a plan change as completed; verify the state and retry.');
            return result?.success === true;
        } catch (error) {
            card.notice = error?.code === 'monitor_plan_busy'
                ? text(card, '规划仍在更新，未执行本次操作；完成后可重试。', 'Planning is updating; this action was not applied. Retry when ready.')
                : text(card, '操作未确认。请核对最新检查点后重试。', 'Action unconfirmed. Check the latest checkpoint before retrying.');
            return false;
        } finally { card.busy = ''; render(card); }
    };

    function scheduleCompare() {
        if (compareTimer) clearTimeout(compareTimer);
        if (!autoCompare || typeof setTimeout !== 'function') return;
        const card = [...cards.values()].reverse().find(item => current(item) && !item.superseded);
        if (!card || card.data.interaction?.dose_current || card.autoAttempt === card.lastEventId) return;
        compareTimer = setTimeout(async () => {
            compareTimer = null;
            if (!autoCompare || !current(card) || card.superseded) return;
            // No GPU work during a drag, another job, or an evidence capture.
            if (document.hidden || manualPlanningState.monitorInteractionActive || window.__monitorCameraInteracting || window.__reportCaptureActive
                || card.busy || manualPlanningState.doseRecomputeRunning || trainingMonitorState.screenshotPendingRunId) {
                scheduleCompare(); return;
            }
            if (!latest(card)) return;
            card.autoAttempt = card.lastEventId;
            await window.runMonitorCheckpointAction(card.id, 'dose');
            scheduleCompare();
        }, 1800);
    }
    window.setMonitorAutoCompare = enabled => { autoCompare = enabled === true; scheduleCompare(); publish(); };
    window.resumeMonitorInteraction = () => {
        if (manualPlanningState.monitorInteractionActive || window.__monitorCameraInteracting) {
            window.clearMonitorFocus?.();window.refreshMonitorSpatialPresentation?.();return;
        }
        scheduleCompare();
        for (const card of cards.values()) if (card.captureState === 'deferred' && latest(card)) void capture(card);
    };
    window.refreshMonitorSpatialPresentation = () => {
        const card=[...cards.values()].reverse().find(item=>current(item) && !item.superseded);
        if(card)render(card);
    };
    window.monitorVisualStateChanged = () => {
        if(!trainingMonitorState.active || visualTimer || trainingMonitorState.screenshotPendingRunId
            || window.__reportCaptureActive)return;
        const owned=`${_activeApiSessionId()}:${trainingMonitorState.runId}`;
        const schedule=typeof requestAnimationFrame==='function' ? requestAnimationFrame : fn=>setTimeout(fn,0);
        visualTimer=schedule(()=>{visualTimer=null;
            if(trainingMonitorState.active && owned===`${_activeApiSessionId()}:${trainingMonitorState.runId}`)
                window.refreshMonitorSpatialPresentation?.();});
    };
    window.resumeMonitorSpatialAssistance = (options = {}) => {
        const card = [...cards.values()].reverse().find(latest);
        if (!card) return false;
        if (card.previewGeometry) return !!window.previewMonitorGeometry?.(card.previewGeometry,card.evidence);
        const labels = window.monitorSpatialGuide(card.data.interaction,card.evidence,card.language);
        const requested = labels.map(item=>item.ref);
        const available = window.getMonitorTargetAvailability?.(requested,card.evidence);
        const refs = available ? available.filter(item=>item.state==='visible').map(item=>item.ref) : requested;
        const ok=!!(refs.length && window.focusMonitorCheckpoint?.(refs,card.evidence,{reframe:false,labels}));
        if(options.render!==false)render(card);return ok;
    };
    document.addEventListener?.('visibilitychange', () => {
        if (!document.hidden) { scheduleCompare(); for (const card of cards.values()) {
            if (card.captureState === 'deferred' && latest(card)) void capture(card);
        } }
    });

    function attachActions(card) {
        if (typeof document.querySelectorAll !== 'function') return;
        const row = Array.from(document.querySelectorAll('[data-message-id]'))
            .find(node => node.dataset.messageId === card.messageId);
        if (!row) return;
        const response = row.querySelector('.chat-msg.bot-response');
        if (response && !response.querySelector('.monitor-feedback-details')) {
            const detail = document.createElement('details'); detail.className = 'monitor-feedback-details'; detail.open = !!card.detailsOpen;
            const summary = document.createElement('summary'); summary.textContent = text(card,'展开完整对象、间距和指标记录','Full object, spacing and metric record');
            summary.dataset.brachyControlRef = `monitor:${card.runId}:${card.id}:details`;
            detail.appendChild(summary);
            const content = document.createElement('div'); while (response.firstChild) content.appendChild(response.firstChild);
            detail.appendChild(content);
            detail.addEventListener('toggle',()=>{card.detailsOpen=detail.open;});
            const compact = document.createElement('div'); compact.className = 'monitor-compact-summary';
            response.append(compact,detail);
        }
        const compact = response?.querySelector('.monitor-compact-summary');
        if (compact) {
            compact.replaceChildren();
            compact.setAttribute('aria-busy',String(!!(card.busy || card.previewBusy)));
            const info = window.monitorInteractionFor(card.data.interaction,card.language) || {};
            const panel = window.createMonitorGuidancePanel(info,card.language,card.superseded,
                {id:card.id,runId:card.runId,evidence:card.evidence,preview:!!card.previewGeometry,
                    canConfirmPreview:!!card.previewCandidate || !!card.evidence.restore_token && !card.decision,
                    candidateId:card.previewCandidate?.candidate_id,current:latest(card),busy:card.busy || card.previewBusy});
            if (panel && document.getElementById('monitorDashboard')) {
                // Chat is the durable receipt; the resident workspace is the
                // current coach. Do not print the same full toolbar twice.
                const receipt=document.createElement('section');receipt.className='monitor-edit-receipt';
                const heading=document.createElement('p');heading.className='monitor-receipt-title';
                heading.textContent=panel.querySelector('.monitor-guidance-title')?.textContent || '';
                const observation=document.createElement('p');observation.textContent=panel.querySelector('.monitor-guide-observation p')?.textContent || '';
                receipt.append(heading,observation);
                if(latest(card)){const open=document.createElement('button');open.type='button';open.className='btn btn-sm monitor-open-coach';
                    open.textContent=text(card,'查看建议与下一步','Review guidance and next step');
                    open.dataset.brachyControlRef=`monitor:${card.runId}:${card.id}:open-coach`;
                    open.addEventListener('click',()=>window.openMonitorGuidance?.(card.id));receipt.appendChild(open);}
                const full=document.createElement('details');full.className='monitor-receipt-guidance';full.dataset.monitorSection='receipt-guidance';
                const summary=document.createElement('summary');summary.textContent=text(card,'展开这一步的完整建议','Full guidance for this edit');
                summary.dataset.brachyControlRef=`monitor:${card.runId}:${card.id}:receipt-guidance`;full.append(summary,panel);
                compact.append(receipt,full);
            } else if (panel) compact.appendChild(panel);
            else {
                const headline = document.createElement('p'); headline.textContent = info.assessment?.title || info.headline || '';
                const next = document.createElement('p'); next.textContent = card.superseded ? '' : info.next_step || '';
                const stage = document.createElement('small'); stage.textContent = info.dose_note || '';
                compact.append(headline,next,stage);
            }
            // Action outcomes and image failures must not disappear inside the
            // collapsed technical record when the user needs to respond.
            const notice = document.createElement('p'); notice.className = 'monitor-guidance-live-status'; notice.setAttribute('role','status');
            notice.textContent = [card.busy,card.notice,card.decision,
                ['failed','deferred'].includes(card.captureState) ? errorText(card,card.captureError) : '',
                card.captureRecords?.some(record=>record.eventId!==card.lastEventId) ? text(card,
                    '下方保留较早检查点的图片；请核对图片版本，不能将旧图当作当前几何或剂量的证据。',
                    'Earlier checkpoint images remain below. Check their revisions; old images do not establish current geometry or dose.') : ''].filter(Boolean).join(' ');
            if (notice.textContent) compact.appendChild(notice);
        }
        row.querySelector('.monitor-checkpoint-actions')?.remove();
        row.querySelector('.monitor-command-options')?.remove();
        row.querySelector('.monitor-preview-actions')?.remove();
        const actions = document.createElement('div');
        actions.className = 'monitor-checkpoint-actions';
        actions.style.cssText = 'display:flex;gap:8px;flex-wrap:wrap;margin-top:10px';
        const guide = window.monitorGuidanceFor(card.data.interaction,card.language);
        const add = (zh, en, handler, disabled = false, action = null) => {
            if (action && response?.querySelector(`.monitor-guide-actions [data-guide-action="${action}"]`)) return;
            const button = document.createElement('button');
            button.type = 'button'; button.className = 'btn btn-sm';
            button.textContent = guide?.steps?.find(step=>step.action === action)?.label || text(card, zh, en);
            if (action && card.data.interaction?.primary_action === action)
                button.className += ' monitor-primary-action';
            button.dataset.brachyControlRef = `monitor:${card.runId}:${card.id}:${action || en}`;
            button.disabled = disabled || !!card.busy || !latest(card);
            button.addEventListener('click', async () => {
                if (!latest(card) || card.busy) return;
                await handler();
            });
            actions.appendChild(button);
        };
        add('定位编辑对象', 'Locate edited objects', () => window.runMonitorCheckpointAction(card.id, 'focus'),false,'focus');
        if (card.data.interaction?.primary_action === 'details') add('查看本次指标取舍','Review measured trade-offs',
            () => window.runMonitorCheckpointAction(card.id,'details'),false,'details');
        if (['failed','deferred','partial'].includes(card.captureState)) add('重试截图', 'Retry image', () => window.runMonitorCheckpointAction(card.id, 'capture'));
        if (!card.data.interaction?.dose_current) add('重算剂量并比较', 'Recompute and compare', () => window.runMonitorCheckpointAction(card.id, 'dose'),false,'dose');
        if (card.evidence.restore_token && !card.decision) {
            if (card.data.interaction?.schema_version === 3)
                add('预览编辑前位置（不修改）', 'Preview pre-edit position (read only)', () => window.runMonitorCheckpointAction(card.id, 'preview'),false,'preview');
            for (const keep of [false, true]) add(keep ? '保留这次编辑' : '恢复编辑前位置',
                keep ? 'Keep this edit' : 'Restore pre-edit position', async () => {
                    await window.runMonitorCheckpointAction(card.id, keep ? 'keep' : 'restore');
                });
        }
        if (card.data.interaction?.decision_required === false) {
            const more = document.createElement('details'); more.className = 'monitor-secondary-actions';
            const summary = document.createElement('summary'); summary.textContent = text(card,'更多操作（无需每次确认保留）','More actions (no routine keep confirmation required)');
            summary.dataset.brachyControlRef = `monitor:${card.runId}:${card.id}:more-chat`;
            more.appendChild(summary);
            for (const button of [...actions.children]) if (/恢复编辑前|保留这次|Restore pre-edit|Keep this/.test(button.textContent)) more.appendChild(button);
            actions.appendChild(more);
        }
        for (const object of card.data.interaction?.objects || []) if (card.data.interaction?.schema_version === 3 && object.kind === 'seeds'
            && card.data.interaction?.decision_required && object.operation !== 'deleted') {
            add(`寻找 ${object.id} 间距修正候选`, `Find spacing candidates for ${object.id}`,
                () => window.runMonitorCheckpointAction(card.id, 'spacing', {objectId:object.id}),false,
                guide?.steps?.some(step=>step.action === 'spacing' && step.object_id === object.id) ? 'spacing' : null);
        }
        const preview = document.createElement('div'); preview.className = 'monitor-preview-actions';
        for (const candidate of card.previewCandidates || []) {
            const button = document.createElement('button'); button.type = 'button'; button.className = 'btn btn-sm';
            button.textContent = text(card, `预览 ${candidate.object_id} 候选 · ${candidate.distance_mm.toFixed(2)} mm（未算剂量）`,
                `Preview ${candidate.object_id} candidate · ${candidate.distance_mm.toFixed(2)} mm (no dose)`);
            button.disabled = !latest(card) || !!card.previewBusy;
            button.addEventListener('click', () => {
                void window.runMonitorCheckpointAction(card.id,'select_candidate',{candidateId:candidate.candidate_id});
            }); preview.appendChild(button);
        }
        if (card.previewCandidate) {
            const button = document.createElement('button'); button.type = 'button'; button.className = 'btn btn-sm';
            button.textContent = text(card, '确认应用此几何候选（剂量待重算）', 'Confirm this geometric candidate (dose needs updating)');
            button.dataset.brachyControlRef = `monitor:${card.runId}:${card.id}:apply-candidate`;
            button.disabled = !latest(card) || !!card.previewBusy;
            button.addEventListener('click', () => window.runMonitorCheckpointAction(card.id,'apply',{candidateId:card.previewCandidate.candidate_id}));
            preview.appendChild(button);
        }
        if(card.previewGeometry && !card.previewCandidate && card.evidence.restore_token && !card.decision
            && !response?.querySelector('.monitor-guide-actions [data-guide-action="restore"]')){
            const confirm=document.createElement('button');confirm.type='button';confirm.className='btn btn-sm';
            confirm.textContent=text(card,'确认恢复编辑前位置','Confirm restore pre-edit position');
            confirm.disabled=!latest(card) || !!card.busy;
            confirm.dataset.brachyControlRef=`monitor:${card.runId}:${card.id}:confirm-restore`;
            confirm.addEventListener('click',()=>window.runMonitorCheckpointAction(card.id,'restore'));preview.appendChild(confirm);
        }
        if((card.previewGeometry || card.previewCandidate) && !guide){
            const close=document.createElement('button');close.type='button';close.className='btn btn-sm';
            close.textContent=text(card,'关闭预览（不改动）','Close preview (no change)');
            close.dataset.brachyControlRef=`monitor:${card.runId}:${card.id}:dismiss-preview`;
            close.addEventListener('click',()=>window.runMonitorCheckpointAction(card.id,'dismiss_preview'));preview.appendChild(close);
        }
        if (guide) {
            // The visible guide owns the primary action. All other commands
            // remain reachable without turning the chat bubble into a toolbar.
            const more=document.createElement('details');more.className='monitor-command-options';more.dataset.monitorSection='commands';
            const summary=document.createElement('summary');summary.textContent=text(card,'定位、撤销与其他操作','Location, undo and other actions');
            summary.dataset.brachyControlRef=`monitor:${card.runId}:${card.id}:commands`;more.append(summary,actions);
            response?.appendChild(more);
        } else (row.querySelector('.chat-msg-wrapper') || row).appendChild(actions);
        if (preview.childNodes.length) (row.querySelector('.chat-msg-wrapper') || row).appendChild(preview);
    }

    window.receiveMonitorCheckpoint = async data => {
        const evidence = data?.event?.detail?.edit_evidence;
        if (!evidence || !trainingMonitorState.active || data.monitor_run_id !== trainingMonitorState.runId) return null;
        const sessionId = _activeApiSessionId();
        if (data.session_id && data.session_id !== sessionId) return null;
        const runId = data.monitor_run_id;
        const owned = `${sessionId}:${runId}`;
        if (owner !== owned) {
            for (const previous of cards.values()) cancelRetry(previous);
            cards.clear(); samples.length = 0; owner = owned;
        }
        const id = evidence.geometry_event_id || evidence.event_id;
        if (!id) return null;
        let card = cards.get(id);
        if (card && Number(evidence.after_version) < Number(card.evidence.after_version)) return null;
        if (card?.lastEventId === evidence.event_id) return card;
        for (const prior of cards.values()) {
            if (prior.id !== id && !prior.superseded && Number(prior.evidence.after_version) <= Number(evidence.after_version)) {
                prior.superseded = true; cancelRetry(prior);
                prior.previewAbort?.abort(); prior.previewCandidates = []; prior.previewCandidate = null; prior.previewGeometry = null;
                if (['pending','deferred'].includes(prior.captureState)) {
                    prior.captureState = 'failed'; prior.captureError = 'monitor_checkpoint_superseded';
                }
                render(prior, false);
            }
        }
        const newer = [...cards.values()].some(prior => Number(prior.evidence.after_version) > Number(evidence.after_version));
        if (!card) {
            card = {id, sessionId, runId, createdAt:Date.now(), requestId:`monitor-${runId}`,
                messageId:`assistant-monitor-${runId}-edit-${id}`, captureState:'pending', receivedAt:Date.now()};
            cards.set(id, card);
            if (cards.size > 40) { const oldest = cards.values().next().value; cancelRetry(oldest); cards.delete(oldest.id); }
        }
        Object.assign(card, {data, evidence, lastEventId:evidence.event_id,
            language: monitorConversationLanguage(sessionId), superseded:newer, eventReceivedAt:Date.now()});
        cancelRetry(card); card.retryCount = 0;
        card.resourceRetries=0;card.resourceSignature=resourceSignature(card);
        card.captureState = newer ? 'failed' : data.suggested_screenshot ? 'pending' : 'none';
        if (newer) card.captureError = 'monitor_checkpoint_superseded';
        card.notice = '';
        card.displayNotice=null;
        card.previewAbort?.abort(); card.previewCandidates = []; card.previewCandidate = null; card.previewGeometry = null;
        if (['kept','restored'].includes(evidence.decision)) card.decision = text(card,
            evidence.decision === 'kept' ? '已保留这次编辑。' : '已恢复编辑前位置；剂量仍需更新。',
            evidence.decision === 'kept' ? 'This edit was kept.' : 'Pre-edit position restored; dose requires updating.');
        // Screenshots and their later outcomes use exactly this same message.
        data.monitor_card_id = card.messageId;
        window.clearMonitorFocus?.();
        // Automatic marks do not reframe, recolor or hide clinical meshes.
        const labels=window.monitorSpatialGuide(data.interaction,evidence,card.language);
        const requested=labels.map(item=>item.ref);
        const available=window.getMonitorTargetAvailability?.(requested,evidence);
        const refs=available ? available.filter(item=>item.state==='visible').map(item=>item.ref) : requested;
        if (!newer && latest(card) && refs.length) window.focusMonitorCheckpoint?.(refs, evidence, {reframe:false,labels});
        render(card);
        timing('checkpoint_to_feedback',Date.now()-card.eventReceivedAt);
        scheduleCompare();
        if (!newer && data.suggested_screenshot) void reportUIEvent(data.event.type, data.event.label, {}, {cachedCheckpoint:data});
        return card;
    };
    window.updateMonitorCheckpointCapture = (data, result) => {
        const card = [...cards.values()].find(item => item.messageId === data?.monitor_card_id);
        if (!card || !current(card)) return false;
        if (data.event?.event_id !== card.lastEventId) return true;
        card.captureState = result.success ? 'ready' : 'failed';
        card.captureError = result.error || '';
        if (result.success && !Array.isArray(result.attachments)) {
            card.captureState = 'failed'; card.captureError = 'attachment_not_rendered';
        } else if (result.success && !result.attachments.length) {
            card.captureState = 'failed'; card.captureError = 'attachment_not_rendered';
        } else if (result.success) {
            card.omittedRefs = result.omittedTargetRefs || [];
            card.captureState = result.error || card.omittedRefs.length ? 'partial' : 'ready';
            card.captureRecords ||= [];
            const priorCapture=card.captureRecords.find(record=>record.eventId===card.lastEventId);
            if(priorCapture){priorCapture.views=[...new Set([...priorCapture.views,...result.attachments.map(item=>item.target).filter(Boolean)])];}
            else {
                timing('checkpoint_to_image_delivery', Date.now()-card.eventReceivedAt);
                card.captureRecords.push({eventId:card.lastEventId, version:card.evidence.after_version,
                    views:[...new Set(result.attachments.map(item=>item.target).filter(Boolean))]});
            }
        }
        if (card.captureState === 'failed') retryCapture(card);
        if (!window.getMonitorSpatialState?.(card.evidence) && latest(card)) {
            window.resumeMonitorSpatialAssistance?.({render:false});
        }
        render(card);
        return true;
    };
    window.markMonitorEvidenceViewed = id => {
        const card = cards.get(id);
        if (!card || !current(card) || !['ready','partial'].includes(card.captureState)) return false;
        card.viewedCaptureEventId = card.lastEventId; publish(); return true;
    };
    window.resolveMonitorCheckpointDecision = (token, kept) => {
        for (const card of cards.values()) {
            if (card.evidence.restore_token !== token) continue;
            delete card.evidence.restore_token;
            card.decision = text(card, kept ? '已保留这次编辑。' : '已恢复编辑前位置；剂量仍需更新。',
                kept ? 'This edit was kept.' : 'Pre-edit position restored; dose requires updating.');
            render(card, false);
        }
        publish();
    };
    window.refreshMonitorCheckpointPresentation = phase => {
        if(phase!=='active' && resourceTimer){clearTimeout(resourceTimer);resourceTimer=null;}
        if (phase === 'active' && owner !== `${_activeApiSessionId()}:${trainingMonitorState.runId}`) {
            for (const card of cards.values()) cancelRetry(card);
            cards.clear(); autoCompare = false;
            owner = `${_activeApiSessionId()}:${trainingMonitorState.runId}`;
        }
        if (phase !== 'active') {
            if(announcementTimer)clearTimeout(announcementTimer);announcementTimer=null;announcementKey='';
            const live=document.getElementById?.('monitorLiveAnnouncement');if(live)live.textContent='';
            autoCompare = false;
            if (compareTimer) clearTimeout(compareTimer);
            for (const card of cards.values()) card.previewAbort?.abort();
            window.clearMonitorFocus?.();
        }
        for (const card of cards.values()) {
            if (phase !== 'active') cancelRetry(card);
            if (phase !== 'active' && ['pending', 'deferred'].includes(card.captureState)) {
                card.captureState = 'failed'; card.captureError = 'monitor_stopped';
            }
            render(card, false);
        }
        publish();
        window.monitorDashboardPhase?.(phase);
    };
    window.addEventListener?.('i18nchange', () => {
        if(announcementTimer)clearTimeout(announcementTimer);announcementTimer=null;
        announcementKey='';const live=document.getElementById?.('monitorLiveAnnouncement');if(live)live.textContent='';
        // Display-only update. Keep card identity, actions, retries, evidence,
        // camera ownership and user-open disclosures unchanged.
        for(const card of cards.values())render(card,false);
        publish();
    });
})();
