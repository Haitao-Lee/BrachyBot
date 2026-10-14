// Software restoration contracts. Declared HTTP/DOM fixtures are not clinical
// evidence; the tests execute the production Input helper, Apply and bridge.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../web/app/static/js');
const source = name => fs.readFileSync(path.join(root, `brachybot-${name}.js`), 'utf8');
const defaults = JSON.parse(fs.readFileSync(path.resolve(root, '../../../../config/default_params.json'), 'utf8'));
const plain = value => JSON.parse(JSON.stringify(value));
const response = (data, headers = {}, status = 200) => new Response(JSON.stringify(data), {status, headers});
const deferred = () => { let resolve; const promise = new Promise(done => {resolve = done;}); return {promise, resolve}; };
const owned = {
    tumor_type:'nnunet_nasopharynx_cect', mode:'rl', seed_info:{radius:0.55,length:6.2,margin_rate:1.2},
    radiation_array_params:{backlit_angle:0.75,maximum_candidate_trajectories:321},
    ref_direc_auto:false, reference_direc_mode:'manual', reference_direc:[1,-2,3],
    dose_value_unit:'gy', in_lowest_energy:1, in_lowest_dose_gy:145.5,
    out_highest_energy:120, out_highest_dose_gy:0, DVH_rate:0.93,max_iter:7,iter_rate:3,replan_rate:0.4,
    distance_filter:{lower_bound:0.9,upper_bound:9,distance_rate:0.7,interval_rate:4},
    rf_params:{max_episodes:350,bandwidth:77},
};
function context() {
    const elements = new Map(), calls = [];
    const c = {API:'/api', activeSessionId:'s', DEFAULT_PRESCRIPTION_GY:120, DEFAULT_DOSE_MODEL_SCALE_GY:190.8,
        Headers, Response, AbortController, setTimeout, clearTimeout, console,
        selected:{sessionId:'s',timepointId:'A',generation:1}, enabled:true,
        document:{addEventListener(){}, getElementById(id) {
            if (!elements.has(id)) elements.set(id,{id,value:'previous',checked:false});
            return elements.get(id);
        }}, elements, calls, _syncTumorTypeSelectorAppearance(){},
        _activeApiSessionId:() => c.activeSessionId,
    };
    c.window = c;
    c.BrachyBotTimepoints = {enabled:() => c.enabled};
    c.BrachyBotTimepointWorkspace = {
        captureRequestScope:() => c.selected && {...c.selected},
        scopeIsCurrent:s => !!c.selected && s.sessionId === c.selected.sessionId
            && s.timepointId === c.selected.timepointId && s.generation === c.selected.generation,
        headers:(s, h) => ({...h,...s ? {'X-BrachyBot-Timepoint':s.timepointId,'X-BrachyBot-Language':'en'} : {}}),
        acceptPlanningConfig:(s, config) => calls.push({accepted:plain(config),scope:s}),
    };
    c.fetch = async (url, init) => {
        calls.push({url,headers:plain(init.headers)});
        return response({success:true,defaults,config:owned,dose_scale_gy:190.8});
    };
    vm.createContext(c);
    const api = source('ui-api'), start = api.indexOf('function planningDoseValueToGy(');
    vm.runInContext('function prescriptionMultiplierToGy(value) { return value * 120; }'
        + api.slice(start, api.indexOf('\n}',start)+2) + source('input-actions'), c);
    c.helper = c.BrachyBotInputPlanningConfig;
    return c;
}
test('every editable Apply field maps to the accepted config, preserving zero and physical Gy', () => {
    const c = context(), controls = plain(c.helper.configControls(owned));
    assert.deepEqual(controls, {
        seedRadius:{value:'0.55'},seedLength:{value:'6.2'},seedMarginRate:{value:'1.2'},
        backlitAngle:{value:'0.75'},maxCandiTraj:{value:'321'},
        inLowestEnergy:{value:'145.5'},outHighestEnergy:{value:'0'},dvhRate:{value:'0.93'},
        maxIter:{value:'7'},iterRate:{value:'3'},replanRate:{value:'0.4'},
        distLowerBound:{value:'0.9'},distUpperBound:{value:'9'},distRate:{value:'0.7'},intervalRate:{value:'4'},
        rfMaxEpisodes:{value:'350'},rfBandwidth:{value:'77'},useRLToggle:{checked:true},refDirecAuto:{checked:false},
        refDirecX:{value:'1'},refDirecY:{value:'-2'},refDirecZ:{value:'3'},ctvModelSelect:{value:'nnunet_nasopharynx_cect'},
    });
    assert.equal(c.helper.configControls({in_lowest_energy:1}).inLowestEnergy.value,'120');
    assert.equal(c.helper.configControls({out_highest_energy:0,dose_value_unit:'gy'}).outHighestEnergy.value,'0');
});
test('owned auto/manual direction and mode never inherit the preceding timepoint', async () => {
    const c = context(); await c.helper.loadCurrent();
    c.fetch = async () => response({success:true,defaults,config:{...owned,mode:'rule_based',
        ref_direc_auto:true,reference_direc_mode:'auto',reference_direc:'auto'}});
    await c.helper.loadCurrent();
    assert.equal(c.elements.get('useRLToggle').checked,false);
    assert.equal(c.elements.get('refDirecAuto').checked,true);
    assert.deepEqual(['refDirecX','refDirecY','refDirecZ'].map(id=>c.elements.get(id).value),['0','1','0']);
});
test('clinical memory beats legacy config and unsaved UI; unrelated controls and input are preserved', () => {
    const c = context(), snapshot = {agent:{config:{...owned,mode:'rule_based',API_KEY:'must-not-project'},
        planning_results:{timepoint_planning_config:{...owned,max_iter:11}}},
        ui:{state:{dose_value_unit:'model',controls:{maxIter:{value:'99'},ctPath:{value:'owned.nii.gz'},guideThickness:{value:'8'}}}}};
    const before = JSON.stringify(snapshot), config = c.helper.snapshotConfig(snapshot);
    const projected = c.helper.projectSnapshot(snapshot,config,defaults);
    assert.equal(projected.ui.state.controls.maxIter.value,'11');
    assert.equal(projected.ui.state.controls.useRLToggle.checked,true);
    assert.equal(projected.ui.state.controls.guideThickness.value,'8');
    assert.equal(projected.ui.state.controls.ctPath.value,'owned.nii.gz');
    assert.equal(projected.ui.state.dose_value_unit,'gy');
    assert.equal(config.API_KEY,undefined);
    assert.equal(JSON.stringify(snapshot),before);
});
test('cold GET captures session/timepoint headers and overlays runtime config without changing defaults', async () => {
    const c = context(), before = JSON.stringify(defaults);
    assert.equal(await c.helper.loadCurrent(),true);
    assert.equal(c.calls[0].headers['X-BrachyBot-Session'],'s');
    assert.equal(c.calls[0].headers['X-BrachyBot-Timepoint'],'A');
    assert.equal(c.elements.get('seedLength').value,'6.2');
    assert.equal(c.elements.get('inLowestEnergy').value,'145.5');
    assert.equal(c.elements.get('maxIter').value,'7');
    assert.equal(JSON.stringify(defaults),before);
});
test('late GET cannot paint another timepoint or a remount of the same timepoint', async () => {
    for (const next of [{sessionId:'s',timepointId:'B',generation:2},{sessionId:'s',timepointId:'A',generation:2}]) {
        const c = context(), wait = deferred(); c.fetch = () => wait.promise;
        const request = c.helper.loadCurrent(); c.selected = next;
        wait.resolve(response({success:true,defaults,config:owned}));
        assert.equal(await request,false); assert.equal(c.elements.size,0);
    }
});
test('late GET cannot overwrite a new session or accepted Apply response', async () => {
    const c = context(), wait = deferred(); c.fetch = () => wait.promise;
    const request = c.helper.loadCurrent(), owner = {timepointScope:c.selected,current:() => true};
    c.helper.accepted({...owned,max_iter:13},owner);
    wait.resolve(response({success:true,defaults,config:owned}));
    assert.equal(await request,false); assert.equal(c.elements.get('maxIter').value,'13');
    assert.equal(c.calls[0].accepted.max_iter,13);
    const session = context(), delayed = deferred(); session.fetch = () => delayed.promise;
    const cold = session.helper.loadCurrent(); session.activeSessionId = 'another';
    delayed.resolve(response({success:true,defaults,config:owned}));
    assert.equal(await cold,false); assert.equal(session.elements.size,0);
});
test('switching and an obsolete Apply owner never paint parameters', async () => {
    const c = context(); c.BrachyBotTimepointWorkspace.captureRequestScope = () => {throw Error('switching');};
    assert.equal(await c.helper.loadCurrent(),false); assert.equal(c.calls.length,0);
    assert.equal(c.helper.accepted(owned,{current:()=>false}),false); assert.equal(c.elements.size,0);
});
test('prepare creates a metadata projection without paint; snapshot precedence and legacy fallback are exact', async () => {
    const c = context(), scope = {...c.selected}, snapshot = {session_id:'s',timepoint_id:'A',
        agent:{config:{...owned,max_iter:8},planning_results:{timepoint_planning_config:{...owned,max_iter:9}}},
        ui:{state:{controls:{maxIter:{value:'999'}}}}};
    const projected = await c.helper.prepareSnapshot(snapshot,scope,()=>true);
    assert.equal(c.elements.size,0); assert.equal(projected.ui.state.controls.maxIter.value,'9');
    delete snapshot.agent.planning_results;
    assert.equal((await c.helper.prepareSnapshot(snapshot,scope,()=>true)).ui.state.controls.maxIter.value,'8');
    delete snapshot.agent;
    assert.equal((await c.helper.prepareSnapshot(snapshot,scope,()=>true)).ui.state.controls.maxIter.value,'7');
});
test('stale prepare and mismatched response ownership cannot produce a projection', async () => {
    const c = context(), wait = deferred(); let current = true; c.fetch = () => wait.promise;
    const work = c.helper.prepareSnapshot({},c.selected,()=>current); current = false;
    wait.resolve(response({success:true,defaults,config:owned})); assert.equal(await work,null);
    c.fetch = async () => response({success:true,defaults,config:owned},{'X-BrachyBot-Timepoint':'B'});
    await assert.rejects(c.helper.prepareSnapshot({},c.selected,()=>true),/scope_mismatch/);
    assert.equal(c.elements.size,0);
});
test('actual Apply uses the accepted response rather than echoing the requested values', async () => {
    const c = context(), manual = source('manual-annotation');
    vm.runInContext(manual.slice(manual.indexOf('function _num('),manual.indexOf('async function runPlanning(')),c);
    const owner = {timepointScope:c.selected,current:()=>true,finish(){}};
    Object.assign(c,{_inputButtonProgress(){},addChat(){},reportUIEvent(){},_manualWorkflowLabel:(_zh,en)=>en,
        fetchInputJson:async () => ({success:true,config:{...owned,max_iter:14,reference_direc:'auto',ref_direc_auto:true}})});
    const result = await c.applyHyperparams(owner);
    assert.equal(result.config.max_iter,14); assert.equal(c.elements.get('maxIter').value,'14');
    assert.equal(c.elements.get('refDirecAuto').checked,true);
});
test('restored editable controls round-trip through the actual Apply serializer without default substitution', async () => {
    const c = context(), manual = source('manual-annotation');
    await c.helper.loadCurrent();
    vm.runInContext(manual.slice(manual.indexOf('function _num('),manual.indexOf('async function runPlanning(')),c);
    Object.assign(c,{_inputButtonProgress(){},addChat(){},reportUIEvent(){},_manualWorkflowLabel:(_zh,en)=>en,
        fetchInputJson:async (_owner, url, config) => {
            assert.equal(url,'/config'); c.submitted=plain(config); return {success:true,config};
        }});
    await c.applyHyperparams({timepointScope:c.selected,current:()=>true});
    assert.deepEqual(c.submitted,{...owned,in_lowest_energy:owned.in_lowest_dose_gy,out_highest_energy:owned.out_highest_dose_gy});
});
test('a rejected config GET does not paint defaults over the existing controls', async () => {
    const c = context(); c.console = {...console,warn(){}};
    c.fetch = async () => response({success:false,error:'not available'}, {}, 503);
    assert.equal(await c.helper.loadCurrent(),false); assert.equal(c.elements.size,0);
    await assert.rejects(c.helper.prepareSnapshot({},c.selected,()=>true),/not available/);
});
test('legacy session hydration is explicitly scoped and is discarded when timepoints become enabled', async () => {
    const c = context(); c.selected=null; c.enabled=false;
    assert.equal(await c.helper.loadCurrent(),true);
    assert.equal(c.calls[0].headers['X-BrachyBot-Session'],'s');
    assert.equal(c.calls[0].headers['X-BrachyBot-Timepoint'],undefined);
    const delayed = deferred(); c.fetch=()=>delayed.promise;
    const request=c.helper.loadCurrent(); c.enabled=true;
    delayed.resolve(response({success:true,defaults,config:{...owned,max_iter:21}}));
    assert.equal(await request,false); assert.equal(c.elements.get('maxIter').value,'7');
});
test('production bridge commits the projected config and passes that same snapshot to resource hydration', async () => {
    const c = context(), bridge = source('timepoint-workspace');
    c.snapshot = {session_id:'s',timepoint_id:'A',agent:{planning_results:{timepoint_planning_config:owned}},
        ui:{state:{controls:{maxIter:{value:'999'}}}}};
    c.context = {...c.selected,isCurrent:()=>true};
    Object.assign(c,{assertOwner(){},imagesPacket:v=>v,json:async()=>({images:[]}),imageUrl:()=>'/images',
        copy:plain,modes:['planned'],records:new Map(),key:s=>s.timepointId,
        fail:code=>Error(code),renderImages(){},renderDoseControls(){},renderStatus(){},mountGuideReview(){},
        scopeIsCurrent:()=>true,queueMicrotask:fn=>c.queued=fn,
        applyTimepointWorkspaceSnapshot(snapshot) {c.committed=plain(snapshot);return true;},
        hydrate:item=>c.hydrated=plain(item.workspace)});
    vm.runInContext('let mounted=null,suspended=true;'
        +bridge.slice(bridge.indexOf('    async function prepare('),bridge.indexOf('    async function hydrate(')),c);
    const prepared = await c.prepare(c.snapshot,c.context);
    assert.equal(c.committed,undefined); assert.equal(prepared.commit(),true); c.queued();
    assert.equal(c.committed.ui.state.controls.maxIter.value,'7');
    assert.deepEqual(c.hydrated,c.committed);
});
test('same-revision production restore retry also projects config before resource replay', async () => {
    const c = context(), bridge = source('timepoint-workspace');
    const workspace = {session_id:'s',timepoint_id:'A',timepoint_clinical_revision:4,timepoint:{lifecycle_revision:1},
        agent:{planning_results:{timepoint_planning_config:owned}},ui:{state:{controls:{maxIter:{value:'999'}}}}};
    c.item = {scope:c.selected,workspace};
    Object.assign(c,{mounted:c.selected,scopeIsCurrent:()=>true,entry:()=>c.item,assertOwner(){},copy:plain,
        controller:()=>({enabled:()=>true,observeWorkspace(){}}),json:async()=>({workspace}),
        hydrate:item=>{c.hydrated=plain(item.workspace);return true;}});
    vm.runInContext(bridge.slice(bridge.indexOf('    async function restoreActiveResources('),
        bridge.indexOf('    async function observeCommittedState(')),c);
    assert.equal(await c.restoreActiveResources(),true);
    assert.equal(c.hydrated.ui.state.controls.maxIter.value,'7');
});
test('startup entry delegates to the bounded production loader', async () => {
    const c = context(), api = source('ui-api'), start = api.indexOf('async function loadDefaultParams(');
    vm.runInContext(api.slice(start,api.indexOf('\n}',start)+2),c);
    assert.equal(await c.loadDefaultParams(),true);
    assert.equal(c.elements.get('maxIter').value,'7');
});

test('production config barrier drains old presentation and gates later writes until acknowledgement', async () => {
    const c=context(), bridge=source('timepoint-workspace'), item={workspace:{}}, oldSave=deferred(), committed=deferred();
    const events=[];
    Object.assign(c,{entry:()=>item,assertCurrent(){},scopeIsCurrent:()=>true,
        flush:async()=>events.push('flushed'),capture:()=>({ui:{state:{}}}),
        controller:()=>({savePresentation:()=>{events.push('old_save');return oldSave.promise;}}),
        fail:code=>Error(code)});
    vm.runInContext(bridge.slice(bridge.indexOf('    async function awaitPlanningConfig('),
        bridge.indexOf('    async function restoreActiveResources(')),c);
    const beginning=c.beginPlanningConfig(c.selected);
    await new Promise(resolve=>setImmediate(resolve));
    assert.deepEqual(events,['flushed','old_save']);assert.equal(item.configMutation,undefined);
    oldSave.resolve(true);const release=await beginning;assert.ok(item.configMutation);
    item.configCommit=committed.promise;
    let saved=false;const subsequent=c.waitForClinicalMutation(c.selected).then(()=>{saved=true;});
    await new Promise(resolve=>setImmediate(resolve));assert.equal(saved,false);
    committed.resolve(true);await new Promise(resolve=>setImmediate(resolve));assert.equal(saved,false);
    release();await subsequent;assert.equal(saved,true);assert.equal(item.configCommit,null);
});

test('late production config acknowledgement does not rebase another timepoint', async () => {
    const c=context(), bridge=source('timepoint-workspace'), reply=deferred(), observed=[];
    Object.assign(c,{json:()=>reply.promise,scopeIsCurrent:s=>s.timepointId===c.selected.timepointId,
        entry:()=>({}),copy:plain,assertOwner(){},clearQualityView(){},
        controller:()=>({observeWorkspace:(_s,data)=>observed.push(data),refresh:async()=>true})});
    vm.runInContext(bridge.slice(bridge.indexOf('    async function observeCommittedState('),
        bridge.indexOf('    async function reloadImages(')),c);
    const request=c.observeCommittedState({...c.selected});c.selected={...c.selected,timepointId:'B'};
    reply.resolve({workspace:{session_id:'s',timepoint_id:'A',timepoint_clinical_revision:3}});
    assert.equal(await request,false);assert.deepEqual(observed,[]);
});
