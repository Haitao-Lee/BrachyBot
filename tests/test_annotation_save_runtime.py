"""Execute the real workspace queue/scoped-save bridge without live cases."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / 'web/app/static/js/brachybot-workspace.js'


def run_js(body, *, short_deadline=False):
    if not shutil.which('node'):
        pytest.skip('Node.js is required')
    script = r'''
const assert=require('assert'),fs=require('fs'),vm=require('vm');
global.window={brachybotAuth:{user:{id:'owner'}},addEventListener(){},removeEventListener(){},dispatchEvent(){}};
global.document={body:{classList:{toggle(){},add(){},remove(){}}},getElementById(){return null;},querySelectorAll(){return [];}};
global.activeSessionId='a';global.sessions={a:{id:'a',messages:[]},b:{id:'b',messages:[]}};
global.state={ctLoaded:true,ctPath:'/synthetic/a.nii.gz',annotations:[{id:'a-line',type:'line'}],viewerSettings:{marker:'a'},maskLabels:{}};
global.dataTreeState={annotations:[{id:'a-line',type:'manual_annotation'}],organs:[]};
let source=fs.readFileSync(BRIDGE,'utf8');
if(SHORT_DEADLINE)source=source.replace('const WORKSPACE_REQUEST_TIMEOUT_MS = 15000;','const WORKSPACE_REQUEST_TIMEOUT_MS = 30;');
vm.runInThisContext(source);
(async()=>{ BODY })().then(()=>process.exit(0)).catch(e=>{console.error(e);process.exit(1);});
'''.replace('BRIDGE', json.dumps(str(BRIDGE))).replace('SHORT_DEADLINE', str(short_deadline).lower()).replace('BODY', body)
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr or result.stdout


def test_queued_saves_capture_the_case_before_waiting_and_preserve_order():
    run_js(r'''
let release;const gate=new Promise(r=>release=r),requests=[];
global.fetch=async(url,options)=>{
 const payload=JSON.parse(options.body);requests.push(payload);
 if(requests.length===1)await gate;
 return {ok:true,status:200,json:async()=>({success:true,revision:requests.length,saved_scope:payload.viewer_annotations?'viewer_annotations':undefined})};
};
const first=window.persistWorkspace('first',{skipChat:true});
state.annotations=[];dataTreeState.annotations=[];
const second=window.persistWorkspace('clear',{annotationsOnly:true});
const third=window.persistWorkspace('queued-full',{skipChat:true});
activeSessionId='b';state.annotations=[{id:'b-line'}];state.viewerSettings={marker:'b'};dataTreeState.annotations=[{id:'b-line'}];
release();assert.deepStrictEqual(await Promise.all([first,second,third]),[true,true,true]);
assert.deepStrictEqual(requests.map(x=>x.reason),['first','clear','queued-full']);
assert(requests.every(x=>x.session_id==='a'));
assert.deepStrictEqual(requests[1].viewer_annotations.annotations,[]);
assert.deepStrictEqual(requests[2].ui_state.viewer.annotations,[]);
assert.strictEqual(requests[2].ui_state.viewer.settings.marker,'a');
''')


def test_compact_save_does_not_read_masks_report_or_chat():
    run_js(r'''
Object.defineProperty(state,'maskLabels',{get(){throw Error('must not serialize masks');}});
Object.defineProperty(window,'reportForm',{get(){throw Error('must not read report');}});
Object.defineProperty(sessions.a,'messages',{get(){throw Error('must not read chat');}});
global.fetch=async(url,options)=>{
 const p=JSON.parse(options.body);
 assert.deepStrictEqual(Object.keys(p).sort(),['reason','response_mode','session_id','viewer_annotations']);
 assert(Buffer.byteLength(options.body)<1000);
 return {ok:true,status:200,json:async()=>({success:true,revision:2,saved_scope:'viewer_annotations'})};
};
assert.strictEqual(await window.persistWorkspace('clear',{annotationsOnly:true}),true);
''')


def test_legacy_ack_needs_a_real_fallback_save_not_a_false_success():
    run_js(r'''
const requests=[];
global.fetch=async(url,options)=>{
 const p=JSON.parse(options.body);requests.push(p);
 return {ok:true,status:200,json:async()=>({success:true,revision:requests.length})};
};
assert.strictEqual(await window.persistWorkspace('clear',{annotationsOnly:true}),true);
assert.strictEqual(requests.length,2);
assert(!('report' in requests[1])&&!('chat' in requests[1]));
assert.deepStrictEqual(requests[1].ui_state.viewer.annotations,[{id:'a-line',type:'line'}]);
''')


def test_legacy_fallback_cannot_read_another_case_after_switch():
    run_js(r'''
let calls=0;
global.fetch=async()=>{
 calls++;activeSessionId='b';
 return {ok:true,status:200,json:async()=>({success:true,revision:2})};
};
assert.strictEqual(await window.persistWorkspace('clear',{annotationsOnly:true}),false);
assert.strictEqual(calls,1);
''')


def test_response_body_timeout_releases_the_save_queue():
    run_js(r'''
let calls=0;
global.fetch=async(url,options)=>{
 calls++;
 return {ok:true,status:200,json:()=>calls===1?new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(Error('aborted')),{once:true})):Promise.resolve({success:true,revision:2,saved_scope:'viewer_annotations'})};
};
assert.strictEqual(await window.persistWorkspace('slow-body',{annotationsOnly:true}),false);
assert.strictEqual(await window.persistWorkspace('next',{annotationsOnly:true}),true);
''', short_deadline=True)


def test_scoped_save_rejects_an_inactive_owner_without_a_request():
    run_js(r'''
global.fetch=async()=>{throw Error('must not send');};
assert.strictEqual(await window.persistWorkspace('clear',{sessionId:'b',annotationsOnly:true}),false);
''')


def test_full_save_for_detached_owner_never_serializes_active_viewer():
    run_js(r'''
let payload;
global.fetch=async(url,options)=>{payload=JSON.parse(options.body);return {ok:true,status:200,json:async()=>({success:true,revision:2})};};
activeSessionId='b';
assert.strictEqual(await window.persistWorkspace('detached',{sessionId:'a',skipChat:true}),true);
assert.strictEqual(payload.session_id,'a');assert(!('ui_state' in payload));
''')


def test_capture_error_returns_failure_without_stranding_the_queue():
    run_js(r'''
let failed=true;
Object.defineProperty(state,'annotations',{get(){if(failed)throw Error('capture failed');return [];}});
global.fetch=async()=>({ok:true,status:200,json:async()=>({success:true,revision:2,saved_scope:'viewer_annotations'})});
assert.strictEqual(await window.persistWorkspace('bad-capture',{annotationsOnly:true}),false);
failed=false;
assert.strictEqual(await window.persistWorkspace('good-capture',{annotationsOnly:true}),true);
''')
