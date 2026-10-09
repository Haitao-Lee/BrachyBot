// Version-owned patient-world annotations. No clinical work is initiated here.
(() => {
    'use strict';
    const NS = 'http://www.w3.org/2000/svg';
    const TYPE = 'planning_distance';
    let certified = null, generation = 0, overlay = null, panel = null, focusId = '', layout = [], pendingPacket = null;
    const expanded = new Map();
    const metrics=document.createElement('canvas').getContext('2d');
    const measured=new Map();
    function textWidth(value){
        if(!measured.has(value)){
            metrics.font='700 13px Inter, "Noto Sans SC", system-ui, sans-serif';
            measured.set(value,metrics.measureText(value).width);
            if(measured.size>1024)measured.delete(measured.keys().next().value);
        }
        return measured.get(value);
    }
    const scene = () => typeof scene3D !== 'undefined' ? scene3D : null;
    const tree = () => typeof dataTreeState !== 'undefined' ? dataTreeState : null;
    const app = () => typeof state !== 'undefined' ? state : null;
    const session = () => String(typeof _activeApiSessionId === 'function' ? _activeApiSessionId() || '' : window.activeSessionId || app()?.sessionId || '');
    const context = () => ({session:session(), plan:String(tree()?.planning?.id || tree()?.planning?.activePlanningId || ''), version:Number(tree()?.planning?.version ?? 0)});
    const equalContext = (a,b) => a && b && a.session === b.session && a.plan === b.plan && a.version === b.version;
    const zh = () => window._i18nLang === 'zh';
    const text = (cn,en) => zh() ? cn : en;
    const rows = () => (app()?.annotations || []).filter(r=>r?.type === TYPE);
    const point = p => Array.isArray(p) && p.length === 3 && p.every(v=>typeof v === 'number' && Number.isFinite(v));
    const near = (a,b) => point(a) && point(b) && a.every((v,i)=>Math.abs(v-b[i]) < 1e-4);
    const color = c => /^#[0-9a-f]{6}$/i.test(String(c)) ? c : '#fde68a';
    const ordinal = id => String(id || '').split('_').pop();
    function label(row, full = false) {
        const n = ordinal(row.needle_id), s = ordinal(row.source_object_id);
        const identity = row.kind === 'seed_tip_distance'
            ? text(`针 ${n} · 粒 ${s}`, `N${n} · S${s}`)
            : text(`针 ${n} · 导板入口`, `N${n} · Guide mouth`);
        const caution=(row.geometry_flags||[]).some(f=>['off_axis','outside_insertion_span','beyond_needle_tip'].includes(f)) ? '⚠ ' : '';
        return `${caution}${row.custom_name || identity}${full ? text(' · 距针尖 ', ' · From tip ') : '  '}${Number(row.tip_distance_mm).toFixed(1)} mm`;
    }
    function persist(reason) {
        window.reconcileViewerAnnotationNodes?.();
        window.renderDataTree?.();
        window.scheduleWorkspaceSave?.(reason);
        window.requestRender?.(); scene()?.requestRender?.(1);
        render();
    }
    function accept(packet, expectedSession = session()) {
        const c = context();
        if (!packet || expectedSession !== c.session || String(packet.planning_id || '') !== c.plan
            || Number(packet.planning_version) !== c.version || !Array.isArray(packet.records)) return false;
        if (window.isViewerAnnotationSavePending?.()) {
            pendingPacket={packet,expectedSession}; return false;
        }
        const saved = new Map(rows().map(r=>[r.id,r]));
        const ids = new Set(), accepted = [];
        for (const source of packet.records) {
            if (!source || source.type !== TYPE || typeof source.id !== 'string' || ids.has(source.id)
                || !point(source.anchor_world_mm) || !point(source.tip_world_mm) || !point(source.external_world_mm)
                || !Number.isFinite(source.tip_distance_mm) || source.units !== 'mm'
                || String(source.planning_id) !== c.plan || Number(source.planning_version) !== c.version) continue;
            ids.add(source.id);
            // Workspace indexes every annotation under the shared annotation
            // family. Resolve that authoritative per-case record even when a
            // loader has already inserted a default placeholder. Live edits
            // mirror into this same record, so late loads cannot undo them.
            const local = saved.get(source.id) || {};
            const restored = window.getWorkspacePresentationForNode?.({
                id:source.id,objectId:`annotation:${source.id}`,family:'annotation',sessionId:c.session,
            });
            const previous = restored ? {...local,...restored} : local;
            accepted.push({...source, session_id:c.session,
                visible:previous.visible ?? true, visible3D:previous.visible3D ?? true, visible2D:false,
                opacity:Number.isFinite(previous.opacity) ? Math.max(0,Math.min(1,previous.opacity)) : 1,
                color:color(previous.color || source.color), ...(previous.custom_name ? {custom_name:previous.custom_name} : {})});
        }
        if (JSON.stringify(rows()) === JSON.stringify(accepted)) {certified=c; render(); return true;}
        // Replace this derived family only. Manual Line/Angle/SAT3D records
        // remain in the existing durable annotation transaction unchanged.
        app().annotations = (app().annotations || []).filter(r=>r?.type !== TYPE).concat(accepted);
        certified = c; focusId = ''; panel?.remove(); panel=null;
        persist('viewer.planning_distance_annotations');
        return true;
    }
    async function refresh(options = {}) {
        const c = context(), token = ++generation;
        if (!c.session || options.sessionId && String(options.sessionId) !== c.session) return false;
        try {
            const guideVersion=options.guideVersion ?? tree()?.planning?.meshes?.find(m=>m.id==='patient_specific_puncture_guide')?.dataVersion;
            const suffix=Number.isInteger(Number(guideVersion))&&Number(guideVersion)>0 ? `?guide_version=${Number(guideVersion)}` : '';
            const response = await fetch('/api/planning/distance-annotations'+suffix, {
                credentials:'same-origin', headers:{'X-BrachyBot-Session':c.session},
            });
            const data = await response.json();
            if (token !== generation || !equalContext(c,context()) || !response.ok || !data.success) return false;
            return accept(data.distance_annotations,c.session);
        } catch (_) { return false; }
    }
    function setPresentation(id, patch) {
        const row = rows().find(r=>r.id === String(id));
        if (!row) return false;
        if (typeof patch.visible === 'boolean') row.visible = patch.visible;
        if (typeof patch.visible3D === 'boolean') row.visible3D = patch.visible3D;
        if (Number.isFinite(patch.opacity)) row.opacity = Math.max(0,Math.min(1,patch.opacity));
        if (patch.color && /^#[0-9a-f]{6}$/i.test(patch.color)) row.color = patch.color;
        if (typeof patch.custom_name === 'string') row.custom_name=patch.custom_name.trim().slice(0,80);
        rememberPresentation(row);
        persist('viewer.planning_distance_presentation');
        return true;
    }
    function rememberPresentation(row) {
        window.updateWorkspacePresentationForNode?.({id:row.id,objectId:`annotation:${row.id}`,family:'annotation',sessionId:session()},
            {visible:row.visible,visible3D:row.visible3D,visible2D:false,color:row.color,opacity:row.opacity});
    }
    function batch(kind, needleId, visible) {
        rows().filter(r=>r.kind === kind && (!needleId || r.needle_id === needleId)).forEach(r=>{
            r.visible = visible; rememberPresentation(r);
        });
        persist('viewer.planning_distance_group');
    }
    function focus(id) {
        focusId=rows().some(r=>r.id===id) ? id : '';
        render();
    }
    function effective(row) {
        const c = context(), t = tree(), sc = scene();
        if (!equalContext(certified,c) || row.session_id !== c.session || row.planning_id !== c.plan
            || Number(row.planning_version) !== c.version || row.visible === false || row.visible3D === false || row.opacity <= .001) return false;
        const needle = t?.planning?.needles?.find(n=>n.id === row.needle_id);
        if (!needle || !near(needle.points?.[0], row.tip_world_mm) || !near(needle.points?.at(-1),row.external_world_mm)) return false;
        const node = row.kind === 'seed_tip_distance'
            ? t.planning.seeds?.find(s=>s.id === row.source_object_id)
            : t.planning.meshes?.find(m=>m.id === 'patient_specific_puncture_guide');
        if (!node || node.visible === false || node.visible3D === false
            || (typeof isDataTreeNodeVisible3D === 'function' && !isDataTreeNodeVisible3D(node))) return false;
        const mesh = sc?.meshes?.[row.kind === 'seed_tip_distance' ? row.source_object_id : 'patient_specific_puncture_guide'];
        if (!mesh || mesh.visible === false) return false;
        if (row.kind === 'seed_tip_distance') {
            if (!near(node.position || node.pos,row.anchor_world_mm)) return false;
            // A drag preview can move the mesh before committed state changes.
            if (mesh.position && !near(mesh.position.toArray(),row.anchor_world_mm)) return false;
        } else if (Number(node.dataVersion ?? node.data_version ?? mesh.userData?.dataVersion ?? mesh.userData?.data_version) !== Number(row.guide_version)) return false;
        return true;
    }
    function ensureOverlay() {
        const host = document.getElementById('canvas3D');
        if (!host || !scene()?.camera) return null;
        if (!overlay || overlay.parentNode !== host) {
            overlay?.remove(); panel?.remove();
            overlay = document.createElementNS(NS,'svg'); overlay.classList.add('planning-distance-overlay');
            overlay.setAttribute('aria-label',text('规划距离标注','Planning distance annotations'));
            host.appendChild(overlay); panel = null;
        }
        return host;
    }
    function element(tag, attrs = {}, content = '') {
        if (tag === 'text') attrs={'font-size':13,'font-weight':700,'font-family':'Inter,Noto Sans SC,system-ui,sans-serif',...attrs};
        if (tag === 'rect') attrs={fill:'#080f1b','fill-opacity':.91,stroke:'#64748b','stroke-width':1,...attrs};
        const e = document.createElementNS(NS,tag);
        Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,String(v)));
        if (content) e.textContent = content;
        return e;
    }
    const intersects = (a,b) => a.x < b.x+b.w+4 && a.x+a.w+4 > b.x && a.y < b.y+b.h+3 && a.y+a.h+3 > b.y;
    function openList(needleId) {
        const host = ensureOverlay(); if (!host) return;
        panel?.remove(); panel = document.createElement('div'); panel.className='planning-distance-list';
        const header = document.createElement('div'); header.className='planning-distance-list-header';
        const heading = document.createElement('strong'); heading.textContent=needleId
            ? text(`针道 ${ordinal(needleId)} · 距针尖`, `Needle ${ordinal(needleId)} · From tip`)
            : text('距离明细 · 按针道', 'Distances · By needle');
        const close=document.createElement('button'); close.type='button'; close.textContent='×';
        close.setAttribute('aria-label',text('关闭','Close')); close.onclick=()=>{panel.remove();panel=null;};
        header.append(heading,close); panel.append(header);
        const note=document.createElement('p');note.className='planning-distance-list-note';
        note.textContent=text('针尖为 0；粒子按中心轴向投影计距，导板按外侧孔口轴心计距。','Tip = 0. Seed distances use axial centre projections; guide distances use outer-mouth axis centres.');
        panel.append(note);
        rows().filter(r=>!needleId || r.needle_id === needleId).sort((a,b)=>a.needle_id.localeCompare(b.needle_id,undefined,{numeric:true}) || a.tip_distance_mm-b.tip_distance_mm).forEach(row=>{
            const item=document.createElement('div'); item.className='planning-distance-list-row';
            const check=document.createElement('input'); check.type='checkbox'; check.checked=row.visible !== false;
            check.setAttribute('aria-label',label(row,true)); check.onchange=()=>setPresentation(row.id,{visible:check.checked});
            const select=document.createElement('button'); select.type='button'; select.textContent=label(row,true);
            select.onclick=()=>{focus(row.id);window.handleTreeItemClick?.(row.id,{shiftKey:false,ctrlKey:false,metaKey:false});};
            item.append(check,select);panel.append(item);
        });
        host.append(panel); close.focus();
        panel.onkeydown=e=>{if(e.key==='Escape'){close.click();e.stopPropagation();}};
    }
    function render() {
        const host=ensureOverlay(); if (!host) return;
        const width=host.clientWidth, height=host.clientHeight;
        overlay.setAttribute('viewBox',`0 0 ${width} ${height}`); overlay.replaceChildren(); layout=[];
        if (width < 80 || height < 80 || !equalContext(certified,context())) {panel?.remove();panel=null;return;}
        const camera=scene().camera;
        camera.updateMatrixWorld?.();
        const visible=rows().filter(effective).map(row=>{
            const p=new THREE.Vector3(...row.anchor_world_mm).project(camera);
            return {row,x:(p.x+1)*width/2,y:(1-p.y)*height/2,z:p.z};
        }).filter(p=>p.z>=-1&&p.z<=1&&p.x>=0&&p.x<=width&&p.y>=0&&p.y<=height);
        visible.sort((a,b)=>(b.row.id===focusId)-(a.row.id===focusId)
            || (a.row.kind==='seed_tip_distance')-(b.row.kind==='seed_tip_distance') || a.y-b.y || a.row.id.localeCompare(b.row.id));
        const focused=visible.find(p=>p.row.id===focusId);
        if(focused){
            const project=p=>{const v=new THREE.Vector3(...p).project(camera);return [(v.x+1)*width/2,(1-v.y)*height/2];};
            const a=project(focused.row.tip_world_mm),b=project(focused.row.external_world_mm);
            if([...a,...b].every(Number.isFinite)){
                const line=`M ${a[0]} ${a[1]} L ${b[0]} ${b[1]}`;
                overlay.append(element('path',{d:line,fill:'none',stroke:'#67e8f9','stroke-width':5,opacity:.7,'data-distance-focus':focused.row.needle_id}));
                overlay.append(element('path',{d:line,fill:'none',stroke:'#ffffff','stroke-width':1.5,'stroke-dasharray':'5 4'}));
            }
        }
        // Preserve orientation and dose-scale readability as well as labels.
        const placed=[{x:0,y:height-110,w:110,h:110}], hidden=new Map();
        const bar=document.getElementById('doseColorbar3D');
        if (bar && getComputedStyle(bar).display !== 'none') {
            const b=bar.getBoundingClientRect(), hostBounds=host.getBoundingClientRect();
            if(b.width&&b.height)placed.push({x:b.left-hostBounds.left,y:b.top-hostBounds.top,w:b.width,h:b.height});
        }
        for (const p of visible) {
            let content=label(p.row);
            const w=Math.min(width-16,Math.max(110,Math.ceil(textWidth(content))+20)), h=25;
            if(textWidth(content)>w-20){
                const suffix=` ${Number(p.row.tip_distance_mm).toFixed(1)} mm`;
                let prefix=Array.from(content.slice(0,-suffix.length));
                while(prefix.length && textWidth(prefix.join('')+'…'+suffix)>w-20)prefix.pop();
                content=prefix.length ? prefix.join('')+'…'+suffix : suffix.trim();
            }
            let box=null;
            for (const [dx,dy] of [[10,-32],[10,8],[-w-10,-32],[-w-10,8],[10,-60],[-w-10,36],[10,36],[-w-10,-60]]) {
                const candidate={x:Math.max(8,Math.min(width-w-8,p.x+dx)),y:Math.max(8,Math.min(height-h-40,p.y+dy)),w,h};
                if (!placed.some(b=>intersects(candidate,b))) {box=candidate;break;}
            }
            if (!box) { const list=hidden.get(p.row.needle_id)||[];list.push(p);hidden.set(p.row.needle_id,list);continue; }
            placed.push(box);
            const g=element('g',{class:'planning-distance-tag',role:'button',tabindex:0,'aria-label':label(p.row,true),opacity:p.row.opacity});
            g.append(element('path',{d:`M ${p.x} ${p.y} L ${box.x+box.w/2} ${box.y+box.h/2}`,stroke:color(p.row.color),fill:'none','stroke-width':1.2,opacity:.82,class:'planning-distance-leader'}));
            g.append(element('circle',{cx:p.x,cy:p.y,r:p.row.id===focusId?6:3,fill:color(p.row.color),stroke:p.row.id===focusId?'#fff':'none'}));
            g.append(element('rect',{x:box.x,y:box.y,width:box.w,height:box.h,rx:5,class:'planning-distance-label-bg',stroke:color(p.row.color)}));
            g.append(element('text',{x:box.x+9,y:box.y+17,fill:'#f8fafc'},content));
            const tooltip=element('title',{},label(p.row,true)+(p.row.kind==='guide_entry_tip_distance'
                ? text('；生成套筒外端孔口轴心，非皮肤入点。','; generated sleeve outer-mouth axis centre, not the skin entry.')
                : text(`；粒子中心的轴向投影距离；离轴 ${Number(p.row.axis_offset_mm||0).toFixed(2)} mm。`,
                       `; axial projection to seed centre; axis offset ${Number(p.row.axis_offset_mm||0).toFixed(2)} mm.`)));
            g.append(tooltip);g.onclick=()=>{focus(p.row.id);openList(p.row.needle_id);};g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();focus(p.row.id);openList(p.row.needle_id);}};
            overlay.append(g);layout.push({row:p.row,box,anchor:{x:p.x,y:p.y},text:content});
        }
        // Overflow is explicit and expandable, never silently discarded.
        if (hidden.size) {
            const count=[...hidden.values()].reduce((n,list)=>n+list.length,0), y=height-30, left=Math.max(8,(width-260)/2);
            const g=element('g',{class:'planning-distance-cluster',role:'button',tabindex:0,'aria-label':text(`展开 ${count} 个重叠标注`,`Expand ${count} overlapping labels`)});
            g.append(element('rect',{x:left,y,width:Math.min(260,width-16),height:23,rx:5,class:'planning-distance-label-bg'}));
            g.append(element('text',{x:left+8,y:y+16,fill:'#e2e8f0'},text(`重叠 ${count} 项 · 点击展开`,`+${count} overlapping · Expand`)));
            g.onclick=()=>openList(null);g.onkeydown=e=>{if(e.key==='Enter'){openList(null);e.preventDefault();}};
            overlay.append(g);
        }
        overlay.dataset.enabledCount=String(visible.length);
        overlay.dataset.drawnCount=String(layout.length);
        overlay.dataset.clusteredCount=String(visible.length-layout.length);
    }
    function treeHtml(records, renderItem, escape) {
        const prefs=tree().artifactBrowser || (tree().artifactBrowser={query:'',expansion:{}});
        const durable=prefs.distanceExpansion || (prefs.distanceExpansion={});
        Object.entries(durable).forEach(([k,v])=>{if(!expanded.has(k))expanded.set(k,v);});
        if(!prefs.query)document.querySelectorAll('[data-distance-group]').forEach(e=>expanded.set(e.dataset.distanceGroup,e.open));
        const detail = (key, cls='') => `<details class="${cls}" data-distance-group="${encodeURIComponent(context().session+'|'+context().plan+'|'+key)}" ${expanded.get(encodeURIComponent(context().session+'|'+context().plan+'|'+key)) ? 'open' : ''}>`;
        let html='';
        for (const kind of ['guide_entry_tip_distance','seed_tip_distance']) {
            const family=records.filter(r=>r.kind===kind); if(!family.length)continue;
            const title=kind==='seed_tip_distance'?text('粒子距针尖','Seeds · From needle tip')
                : text('导板入口距针尖','Guide mouths · From needle tip')+` · v${family[0].guide_version}`;
            html+=detail(kind,'planning-distance-tree')+`<summary>${escape(title)} <span>(${family.length})</span></summary><div class="planning-distance-tree-actions">`;
            for(const visible of [true,false])html+=`<button type="button" onclick="setPlanningDistanceAnnotationGroup('${kind}',null,${visible})">${text(visible?'全部显示':'全部隐藏',visible?'Show all':'Hide all')}</button>`;
            html+='</div>';
            for(const needleId of [...new Set(family.map(r=>r.needle_id))]){
                const children=family.filter(r=>r.needle_id===needleId);
                html+=detail(kind+'|'+needleId)+`<summary>${escape(text('针道 ','Needle ')+ordinal(needleId))} <span>(${children.length})</span></summary>`;
                children.forEach(row=>{
                    const name=row.custom_name || (row.kind==='seed_tip_distance' ? text('粒子 ','Seed ')+ordinal(row.source_object_id) : text('导板入口','Guide mouth'));
                    html+=`<div class="artifact-tree-leaf" data-artifact-search="${escape([label(row,true),row.needle_id,row.source_object_id,row.id].join(' ').toLowerCase())}">`
                        +renderItem(row.id,{...row,label:name,fullLabel:label(row,true)},`${Number(row.tip_distance_mm).toFixed(1)} mm`)+`</div>`;
                }); html+='</details>';
            }
            html+='</details>';
        }
        if (expanded.size>512) for(const key of [...expanded.keys()].slice(0,expanded.size-512))expanded.delete(key);
        prefs.distanceExpansion=Object.fromEntries(expanded);
        return html;
    }
    window.acceptPlanningDistanceAnnotations=accept;
    window.refreshPlanningDistanceAnnotations=refresh;
    window.renderPlanningDistanceAnnotations=render;
    window.planningDistanceAnnotationLabel=label;
    window.setPlanningDistanceAnnotationPresentation=setPresentation;
    window.setPlanningDistanceAnnotationGroup=batch;
    window.renderPlanningDistanceAnnotationTree=treeHtml;
    window.isPlanningDistanceAnnotationId=id=>rows().some(r=>r.id===String(id));
    window.getPlanningDistanceAnnotationLayout=()=>layout;
    window.focusPlanningDistanceAnnotation=focus;
    window.flushPendingPlanningDistanceAnnotations=()=>{
        const pending=pendingPacket;pendingPacket=null;
        return pending ? accept(pending.packet,pending.expectedSession) : false;
    };
    window.clearPlanningDistanceAnnotationPresentation=()=>{
        certified=null;generation++;pendingPacket=null;focusId='';layout=[];
        expanded.clear();
        overlay?.replaceChildren();panel?.remove();panel=null;
    };
    window.addEventListener('i18nchange',()=>{panel?.remove();panel=null;window.renderDataTree?.();render();});
    window.addEventListener('resize',render);
    document.fonts?.addEventListener('loadingdone',()=>{measured.clear();render();});
})();
