const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=process.argv[2]||path.join(__dirname,'../web/app/static/js');
const read=name=>fs.readFileSync(path.join(root,name),'utf8');
function extract(s,n,async=false){const start=s.indexOf(`${async?'async ':''}function ${n}(`);assert(start>=0);return s.slice(start,s.indexOf('\n}',start)+2);}
function makeStepsDiv(){
    const blocks=[];
    return {
        blocks,
        querySelector(sel){
            const m=/\[data-step-id="([^"]*)"\]/.exec(String(sel));
            if(!m) return null;
            return blocks.find(b=>String(b.dataset.stepId)===m[1])||null;
        },
        querySelectorAll(){return blocks.slice();},
        appendChild(b){blocks.push(b);},
        closest(){return null;},
    };
}
function makeBlock(){
    return {className:'',id:'',dataset:{},innerHTML:'',
        querySelector(){return null;}};
}
async function main(){
    const c=vm.createContext({
        window:{},document:{createElement:()=>makeBlock()},
        activeSessionId:'s',
        escHtml:s=>String(s==null?'':s),
        _localizeStepTitle:t=>t,_localizeStepStatus:s=>s,
        _normalizeTraceLanguage:()=>'',_chatDomKey:()=>'k',
        STEP_ICONS:{},requestChatScrollToBottom:()=>{},
        sanitizeChatErrorContent:s=>s,
    });
    vm.runInContext(extract(read('brachybot-chat-core.js'),'appendStepToChain'),c);

    // Two real calls of the same tool in one turn must keep two rows: the
    // downstream-update plan runs ui_controller twice (report.autofill and
    // viewer.refresh_planning) and the second call used to overwrite the first
    // row's params/result.
    let div=makeStepsDiv();
    c.appendStepToChain(div,{id:4,type:'tool',tool:'ui_controller',status:'done',
        params:{actions:[{target:'report.autofill'}]},result:'report saved'},4);
    c.appendStepToChain(div,{id:6,type:'tool',tool:'ui_controller',status:'done',
        params:{actions:[{target:'viewer.refresh_planning'}]},result:'refreshed'},6);
    assert.equal(div.blocks.length,2,'two completed calls of one tool need two rows');
    assert.match(div.blocks[0].innerHTML,/report\.autofill/);
    assert.match(div.blocks[1].innerHTML,/viewer\.refresh_planning/);

    // A server re-emission under a second id may still update a NON-terminal
    // block of the same (type, tool, parent) in place.
    div=makeStepsDiv();
    c.appendStepToChain(div,{id:8,type:'tool',tool:'oar_segmentation',parent_tool:'',status:'pending'},8);
    c.appendStepToChain(div,{id:12,type:'tool',tool:'oar_segmentation',parent_tool:'',status:'done',result:'ok'},12);
    assert.equal(div.blocks.length,1,'cross-id promotion of an open step stays one row');
    assert.equal(div.blocks[0].dataset.stepStatus,'done');

    // Different parent_tool is a different logical step even when open.
    div=makeStepsDiv();
    c.appendStepToChain(div,{id:2,type:'tool',tool:'oar_segmentation',parent_tool:'ctv_segmentation',status:'pending'},2);
    c.appendStepToChain(div,{id:9,type:'tool',tool:'oar_segmentation',parent_tool:'',status:'pending'},9);
    assert.equal(div.blocks.length,2);

    // Same-id updates always resolve to the same row.
    div=makeStepsDiv();
    c.appendStepToChain(div,{id:5,type:'tool',tool:'dose_evaluation',status:'pending'},5);
    c.appendStepToChain(div,{id:5,type:'tool',tool:'dose_evaluation',status:'done',result:'v100'},5);
    assert.equal(div.blocks.length,1);
    assert.equal(div.blocks[0].dataset.stepStatus,'done');
    assert.match(div.blocks[0].innerHTML,/v100/);
    console.log('PASS: repeated same-tool rows stay separate, cross-id promotion is limited to open steps, parent and id matching remain exact');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
