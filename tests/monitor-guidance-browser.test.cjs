// Real DOM coaching regression with synthetic events, no patient or model job.
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=process.argv[2]||path.resolve(__dirname,'../web/app/static/js');
(async()=>{
    const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH});
    try{
        const page=await browser.newPage({viewport:{width:1050,height:950}}),errors=[];
        page.on('pageerror',error=>errors.push(String(error)));
        await page.setContent('<details id="monitorDashboard" open><summary></summary><div class="monitor-dashboard-body"></div></details><div id="chatMessages"></div>');
        await page.addStyleTag({path:path.resolve(root,'../css/brachybot-monitor-dashboard.css')});
        await page.addScriptTag({content:`
            window.trainingMonitorState={active:true,phase:'active',runId:'r'};
            window.manualPlanningState={planningId:'p',planningVersion:1};
            window.language='zh';window._activeApiSessionId=()=> 'c';window.monitorConversationLanguage=()=>language;window.API='/api';
            window._monitorEvidenceMatchesLiveGeometry=()=>true;
            window.reportUIEvent=async()=>{};window.stopTrainingMode=async()=>({success:true});
            window.addChat=(_t,content,_scroll,_time,_restore,_sid,meta)=>{
                let row=document.querySelector('[data-message-id="'+meta.messageId+'"]');
                if(!row){row=document.createElement('section');row.dataset.messageId=meta.messageId;row.innerHTML='<div class="chat-msg-wrapper"><div class="chat-msg bot-response"></div></div>';chatMessages.append(row);}
                row.querySelector('.bot-response').textContent=content;
            };
            window.fetch=async()=>({ok:true,json:async()=>({success:true,active:true,monitor_run_id:'r',overview:{},events:[]})});
            window.guidance={schema_version:1,focus_refs:['a','b'],localized:{
                zh:{state:'geometry_review',title:'先处理 a 与 b 的间距',observation:'b 位移 3.00 mm',meaning:'间隙 -0.40 mm，要求 0.50 mm',recommendation:'先查看间距；误拖时先预览原位，再决定恢复。',verification:'修正后复核间距，再重算剂量。',limitation:'间隙不足量不是建议移动量。',findings:[],steps:[{action:'focus',label:'查看这对对象的间距',refs:['a','b']}]},
                en:{state:'geometry_review',title:'Check a and b spacing first',observation:'b displacement 3.00 mm',meaning:'Gap -0.40 mm; configured minimum 0.50 mm',recommendation:'Locate the pair; preview the prior position before restoring an unintended drag.',verification:'Review spacing after correction, then recompute dose.',limitation:'A gap shortfall is not a movement prescription.',findings:[],steps:[{action:'focus',label:'Locate this spacing issue',refs:['a','b']}]}
            }};
            window.packet={session_id:'c',monitor_run_id:'r',language:'zh',event:{type:'manual.seed.drag',event_id:'e1',detail:{edit_evidence:{geometry_event_id:'edit',event_id:'e1',planning_id:'p',after_version:1,geometry_key:'g'}}},
                interaction:{schema_version:3,language:'zh',headline:'旧数字摘要',next_step:'旧泛泛下一步',dose_note:'待重算',decision_required:false,dose_current:false,primary_action:'focus',spatial_refs:['a','b'],objects:[],guidance},suggested_screenshot:null};
        `});
        await page.addScriptTag({path:path.join(root,'brachybot-monitor-interaction.js')});
        await page.addScriptTag({path:path.join(root,'brachybot-monitor-dashboard.js')});
        await page.evaluate(()=>receiveMonitorCheckpoint(packet));
        assert.equal(await page.locator('.monitor-guidance').count(),2,'chat and dashboard use the same coaching contract');
        assert.equal(await page.locator('.monitor-receipt-guidance').getAttribute('open'),null,'chat is a concise receipt, not a second full toolbar');
        await page.locator('.monitor-receipt-guidance > summary').click();
        for(const selector of ['#monitorDashboard','.chat-msg.bot-response']){
            assert.match(await page.locator(selector+' .monitor-guidance').innerText(),/建议先做/);
            assert.equal(await page.locator(selector+' .monitor-guide-followup').getAttribute('open'),null,'verification stays reachable without cluttering the first view');
            await page.locator(selector+' .monitor-guide-followup > summary').click();
            assert.match(await page.locator(selector+' .monitor-guidance').innerText(),/如何确认/);
            await page.locator(selector+' .monitor-guide-followup > summary').click();
            assert.match(await page.locator(selector+' .monitor-guidance').innerText(),/3.00 mm/);
            assert.equal(await page.locator(selector+' .monitor-guide-recommendation').isVisible(),true);
        }
        assert.equal(await page.locator('.monitor-feedback-details').getAttribute('open'),null,'technical dump stays secondary');
        assert.equal(await page.getByRole('button',{name:'查看这对对象的间距',exact:true}).count(),2);
        assert.equal(await page.locator('.monitor-guidance .monitor-guide-actions button').count(),2,'recommended actions are next to the advice, not duplicated below');
        await page.evaluate(()=>{
            window.marked=[];window.focusMonitorCheckpoint=(refs)=>{marked.push(refs);return true;};
        });
        await page.getByRole('button',{name:'查看这对对象的间距',exact:true}).first().click();
        assert.deepEqual(await page.evaluate(()=>marked[0]),['a','b'],'recommended action targets the stated pair');
        await page.evaluate(()=>{
            language='en';renderMonitorDashboard([{id:'edit',sessionId:'c',runId:'r',createdAt:Date.now(),lastEventId:'e1',captureState:'none',evidence:packet.event.detail.edit_evidence,data:packet}],{});
        });
        assert.match(await page.locator('#monitorDashboard .monitor-guidance').innerText(),/Recommended next step/);
        assert.match(await page.locator('#monitorDashboard .monitor-guide-recommendation').innerText(),/Locate the pair/,
            'single-letter IDs must not corrupt ordinary English prose');
        assert.doesNotMatch(await page.locator('#monitorDashboard .monitor-guidance').innerText(),/建议先做/);
        await page.evaluate(()=>{
            language='zh';
            packet.event.event_id='e2';packet.event.detail.edit_evidence.event_id='e2';
            packet.interaction.guidance.localized.zh.recommendation='新建议 <img src=x onerror="window.injected=true">';
            return receiveMonitorCheckpoint(packet);
        });
        assert.match(await page.locator('.chat-msg.bot-response .monitor-guide-recommendation').innerText(),/新建议/);
        assert.equal(await page.locator('.monitor-guidance img').count(),0,'advice and object names render as text, not HTML');
        assert.equal(await page.evaluate(()=>window.injected),undefined);
        await page.evaluate(()=>{
            const card={id:'old',sessionId:'c',runId:'r',createdAt:Date.now(),superseded:true,detailsOpen:false,
                evidence:packet.event.detail.edit_evidence,data:packet};
            document.body.append(createMonitorGuidancePanel(packet.interaction,'en',true));
        });
        assert.equal(await page.locator('.monitor-guidance[data-state=historical] .monitor-guide-recommendation').count(),0,'historical feedback has no current recommendation');
        await page.evaluate(()=>{
            document.querySelector('.monitor-guidance[data-state=historical]').remove();
            language='zh';packet.interaction.guidance.localized.zh.recommendation='先查看间距；误拖时先预览原位，再决定恢复。';
            packet.event.event_id='e3';packet.event.detail.edit_evidence.event_id='e3';
            return receiveMonitorCheckpoint(packet);
        });
        await page.screenshot({path:path.join(__dirname,'monitor-guidance-qa.png')});
        await page.setViewportSize({width:390,height:900});
        const widths=await page.evaluate(()=>[document.documentElement.scrollWidth,window.innerWidth]);
        assert(widths[0]<=widths[1]+1,'guide fits a narrow screen');
        assert.deepEqual(errors,[]);
        console.log('Browser coaching: visible explanation/recommendation/verification, shared chat/HUD copy, exact pair action, live revision updates, bilingual copy, historical suppression, safe text and narrow layout passed.');
    }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
