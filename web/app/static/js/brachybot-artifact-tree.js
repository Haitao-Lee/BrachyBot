// Source-owned, searchable presentation of durable artifacts. Files stay put.
(() => {
    'use strict';
    let groups=new Map();
    const tree=()=>typeof dataTreeState!=='undefined'?dataTreeState:null;
    const text=(cn,en)=>window._i18nLang==='zh'?cn:en;
    const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const key=value=>encodeURIComponent(String(value));
    function browserPrefs(){
        const t=tree();
        if(!t.artifactBrowser || typeof t.artifactBrowser!=='object' || Array.isArray(t.artifactBrowser))t.artifactBrowser={query:'',expansion:{}};
        if(!t.artifactBrowser.expansion || typeof t.artifactBrowser.expansion!=='object' || Array.isArray(t.artifactBrowser.expansion))t.artifactBrowser.expansion={};
        return t.artifactBrowser;
    }
    function filename(row){return String(row.objectId||'').split(':').slice(1).join(':');}
    function metadata(row){return row.artifactMetadata || row.viewMetadata || {};}
    function targetName(target){return ({'data-tree':text('数据树','Data Tree'),'viewer-3d':text('三维视图','3D Viewer'),
        'viewer-axial':text('轴向','Axial'),'viewer-sagittal':text('矢状','Sagittal'),'viewer-coronal':text('冠状','Coronal'),
        dvh:'DVH',report:text('报告','Report')})[target] || text('截图','Capture');}
    function timestamp(value){
        if(value===null||value===undefined||value==='')return null;
        const date=new Date(typeof value==='number' ? (value<1e12?value*1000:value) : value);
        return Number.isNaN(date.getTime())?null:date;
    }
    function dateLabel(value){return timestamp(value)?.toLocaleString(window._i18nLang==='zh'?'zh-CN':'en-GB',
        {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) || text('时间未记录','Time not recorded');}
    function group(id,title,children,leaves,defaultOpen=false){
        const scope=key(`${tree()?.sessionId||window.activeSessionId||''}|${id}`);
        groups.set('artifacts:'+id,{title,objectIds:leaves.map(r=>r.objectId).filter(Boolean)});
        const expansion=browserPrefs().expansion;
        const open=Object.prototype.hasOwnProperty.call(expansion,scope)?expansion[scope]:defaultOpen;
        return `<details class="artifact-tree-group" data-artifact-branch="${esc(scope)}" data-artifact-group-id="${esc('artifacts:'+id)}" ${open?'open':''}>
            <summary><span class="artifact-tree-heading">${esc(title)}</span><span class="artifact-tree-count">${leaves.length}</span></summary>
            <div class="artifact-tree-children">${children}</div></details>`;
    }
    function leaf(row,label,render){
        label=row.customLabel || label;
        const m=metadata(row), file=filename(row), owner=String(row.planningId||m.planning_id||'');
        const search=[label,row.label,file,owner,m.target,m.request_id,m.message_id,m.capture_source_id,m.capture_variant,m.axis].filter(Boolean).join(' ').toLowerCase();
        return `<div class="artifact-tree-leaf" data-artifact-search="${esc(search)}">${render({...row,label,
            fullLabel:[label,file,owner?text('规划: ','Planning: ')+owner:''].filter(Boolean).join(' · ')})}</div>`;
    }
    function render(annotations,artifacts,renderManual,renderArtifact){
        const prefs=browserPrefs();
        document.querySelectorAll('[data-artifact-branch]').forEach(e=>{
            if(!prefs.query)prefs.expansion[e.dataset.artifactBranch]=e.open;
        });
        groups=new Map();let content='';
        const generated=annotations.filter(r=>r.annotationType==='planning_distance');
        if(generated.length)content+=group('automatic',text('规划自动标注','Planning annotations'),
            window.renderPlanningDistanceAnnotationTree?.(generated,renderManual,esc)||'',generated,true);
        const manual=annotations.filter(r=>r.annotationType!=='planning_distance');
        if(manual.length){
            let children='';
            for(const [type,title] of [['line',text('线段测距','Line measurements')],['angle',text('角度','Angles')],
                ['rect',text('矩形测量','Rectangle measurements')],['sat3d_prompt',text('SAT3D 提示点','SAT3D prompts')],['other',text('其他手动标注','Other manual annotations')]]){
                const rows=manual.filter(r=>type==='other'?!['line','angle','rect','sat3d_prompt'].includes(r.annotationType):r.annotationType===type);
                if(!rows.length)continue;
                const body=rows.map(r=>leaf(r,r.label,x=>renderManual(x.id,x,text('手动','Manual')))).join('');
                children+=group('manual:'+type,title,body,rows,false);
            }
            content+=group('manual',text('手动测量与提示','Manual measurements & prompts'),children,manual,false);
        }
        const report=artifacts.filter(r=>['report','report_data','report_figure'].includes(r.dataType));
        if(report.length){
            let children='';const documents=report.filter(r=>r.dataType!=='report_figure');
            if(documents.length)children+=group('report:documents',text('报告数据与文件','Report data & files'),documents.map(r=>leaf(r,
                r.dataType==='report_data'?text('报告表单数据','Report form data'):text('已保存 PDF','Saved PDF'),renderArtifact)).join(''),documents,true);
            const figures=report.filter(r=>r.dataType==='report_figure');
            for(const owner of [...new Set(figures.map(r=>String(r.planningId||'')))]){
                const rows=figures.filter(r=>String(r.planningId||'')===owner);
                const active=String(tree()?.planning?.id||tree()?.planning?.activePlanningId||'');
                let body='';
                for(const number of [...new Set(rows.map(r=>metadata(r).view_metadata?.figure_number||r.viewMetadata?.figure_number||''))]){
                    const images=rows.filter(r=>(metadata(r).view_metadata?.figure_number||r.viewMetadata?.figure_number||'')===number)
                        .sort((a,b)=>Number(a.viewMetadata?.sort_order??1e9)-Number(b.viewMetadata?.sort_order??1e9));
                    const title=number?text('图 ','Figure ')+number:text('其他报告插图','Other report figures');
                    body+=group('report:figures:'+owner+':'+number,title,images.map(r=>{
                        const m=r.viewMetadata||{}, sub=number?text('图 ','Fig. ')+number+(m.subfigure?`(${m.subfigure})`:'')+' · ':'';
                        const localized=window.reportFigureDisplayText?.({axis:m.axis,title:r.label},window._i18nLang||'en');
                        return leaf(r,sub+(localized?.title||r.label),renderArtifact);
                    }).join(''),images,true);
                }
                const title=owner?(owner===active?text('当前规划插图','Current planning figures'):text('其他规划插图','Other planning figures'))
                    +` · ${owner.slice(0,12)}`:text('未记录规划归属的插图','Figures with unrecorded planning ownership');
                children+=group('report:figures:'+owner,title,body,rows,owner===active);
            }
            content+=group('report',text('报告与插图','Reports & figures'),children,report,true);
        }
        const screenshots=artifacts.filter(r=>r.dataType==='screenshot');
        const known=screenshots.filter(r=>metadata(r).artifact_family==='chat_capture');
        if(known.length){
            const requests=new Map();
            known.forEach(r=>{const m=metadata(r),id=String(m.request_id||m.message_id||m.capture_source_id||r.objectId);const list=requests.get(id)||[];list.push(r);requests.set(id,list);});
            const sorted=[...requests.entries()].sort((a,b)=>Math.max(...b[1].map(r=>timestamp(metadata(r).created_at)?.getTime()||0))
                -Math.max(...a[1].map(r=>timestamp(metadata(r).created_at)?.getTime()||0)) || a[0].localeCompare(b[0]));
            let body='';
            sorted.forEach(([id,rows],index)=>{
                const captures=new Map();rows.forEach(r=>{const source=String(metadata(r).capture_source_id||r.objectId);const list=captures.get(source)||[];list.push(r);captures.set(source,list);});
                let child='';
                [...captures.entries()].forEach(([source,images],i)=>{
                    const target=targetName(metadata(images[0]).target);
                    images.sort((a,b)=>(metadata(a).capture_variant==='original')-(metadata(b).capture_variant==='original'));
                    child+=group('screenshots:'+id+':'+source,`${target}${captures.size>1?` · ${i+1}`:''}`,images.map(r=>leaf(r,
                        metadata(r).capture_variant==='annotated'?text('已标注图','Annotated image'):text('原始截图','Original capture'),renderArtifact)).join(''),images,false);
                });
                const created=Math.max(...rows.map(r=>timestamp(metadata(r).created_at)?.getTime()||0));
                const label=text('截图记录 ','Capture ')+(sorted.length-index)+' · '+dateLabel(created||null);
                body+=group('screenshots:'+id,label,child,rows,false);
            });
            content+=group('screenshots',text('对话截图 · 按请求','Chat captures · By request'),body,known,false);
        }
        const others=artifacts.filter(r=>!report.includes(r)&&!known.includes(r));
        if(others.length)content+=group('other',text('其他已保存附件','Other saved attachments'),others.map((r,i)=>leaf(r,
            text('已保存图像 ','Saved image ')+(i+1),renderArtifact)).join(''),others,false);
        const input=`<div class="artifact-tree-search"><input type="search" value="${esc(prefs.query||'')}" aria-label="${esc(text('搜索标注与附件','Search annotations & attachments'))}" placeholder="${esc(text('搜索名称、针道、图号或文件名…','Search name, needle, figure or filename…'))}"><span class="artifact-tree-search-result" aria-live="polite"></span></div>`;
        return input+content;
    }
    function filter(host,query){
        query=String(query||'').trim().toLowerCase();let matched=0;
        host.querySelectorAll('.artifact-tree-leaf').forEach(e=>{const show=!query||e.dataset.artifactSearch.includes(query);e.hidden=!show;if(show)matched++;});
        // Generated annotations keep their complete independent visibility tree.
        host.querySelectorAll('[data-artifact-branch]').forEach(e=>{
            const leaves=[...e.querySelectorAll('.artifact-tree-leaf')];
            e.hidden=!!query&&leaves.length>0&&leaves.every(r=>r.hidden);
            if(query&&!e.hidden)e.open=true;
            else if(!query && Object.prototype.hasOwnProperty.call(browserPrefs().expansion,e.dataset.artifactBranch))e.open=browserPrefs().expansion[e.dataset.artifactBranch];
        });
        if(query)host.querySelectorAll('.planning-distance-tree details,.planning-distance-tree').forEach(e=>e.open=true);
        else host.querySelectorAll('[data-distance-group]').forEach(e=>{
            e.open=browserPrefs().distanceExpansion?.[e.dataset.distanceGroup]===true;
        });
        const status=host.querySelector('.artifact-tree-search-result');
        if(status)status.textContent=query?text(`${matched} 项匹配`,`${matched} matches`):'';
    }
    function afterRender(host){
        if(!host)return;const input=host.querySelector('.artifact-tree-search input');if(!input)return;
        filter(host,browserPrefs().query||'');
        input.oninput=()=>{
            browserPrefs().query=input.value.slice(0,160);filter(host,input.value);
            window.scheduleWorkspaceSave?.('viewer.artifact_search');
        };
        host.querySelectorAll('[data-artifact-branch]').forEach(e=>{
            e.querySelector(':scope > summary').addEventListener('click',()=>setTimeout(()=>{
                if(browserPrefs().query)return;
                browserPrefs().expansion[e.dataset.artifactBranch]=e.open;
                const keys=Object.keys(browserPrefs().expansion);if(keys.length>1024)keys.slice(0,keys.length-1024).forEach(k=>delete browserPrefs().expansion[k]);
                window.scheduleWorkspaceSave?.('viewer.artifact_branch');
            },0));
            e.querySelector(':scope > summary').oncontextmenu=event=>{
                event.preventDefault();event.stopPropagation();window.showGroupContextMenu?.(event.clientX,event.clientY,e.dataset.artifactGroupId);
            };
        });
        host.querySelectorAll('[data-distance-group]').forEach(e=>{
            e.querySelector(':scope > summary')?.addEventListener('click',()=>setTimeout(()=>{
                if(browserPrefs().query)return;
                const expansion=browserPrefs().distanceExpansion || (browserPrefs().distanceExpansion={});
                expansion[e.dataset.distanceGroup]=e.open;
                window.scheduleWorkspaceSave?.('viewer.distance_annotation_branch');
            },0));
        });
    }
    window.renderStructuredArtifactTree=render;
    window.bindStructuredArtifactTree=afterRender;
    window.getStructuredArtifactGroup=id=>groups.get(id)||null;
    window.showStructuredArtifactContextMenu=(x,y,id)=>{
        const entry=groups.get(id);if(!entry)return false;
        window.hideContextMenu?.();
        const menu=document.createElement('div');menu.className='ctx-menu';menu.id='ctxMenu';
        menu.style.left=x+'px';menu.style.top=y+'px';
        const heading=document.createElement('div');heading.className='ctx-menu-item';heading.textContent=`${entry.title} (${entry.objectIds.length})`;menu.append(heading);
        const button=(label,action,danger=false)=>{
            const item=document.createElement('button');item.type='button';item.className='ctx-menu-item'+(danger?' ctx-menu-danger':'');item.textContent=label;
            item.onclick=()=>{window.hideContextMenu?.();void window._runDataTreeAction?.(action());};menu.append(item);
        };
        button(text('导出此分组','Export this group'),()=>window.exportDataTreeGroup?.(id));
        const auto=(typeof state!=='undefined'?state.annotations:[]).filter(r=>r.type==='planning_distance')
            .filter(r=>entry.objectIds.includes('annotation:'+r.id));
        if(auto.length){
            button(text('显示此分组标注','Show group annotations'),()=>auto.forEach(r=>window.setPlanningDistanceAnnotationPresentation?.(r.id,{visible:true})));
            button(text('隐藏此分组标注','Hide group annotations'),()=>auto.forEach(r=>window.setPlanningDistanceAnnotationPresentation?.(r.id,{visible:false})));
        }else button(text('删除此分组数据…','Delete group data…'),()=>window.deleteDataTreeGroup?.(id),true);
        document.body.append(menu);return true;
    };
    window.addEventListener('i18nchange',()=>window.renderDataTree?.());
})();
