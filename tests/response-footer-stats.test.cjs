const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=process.argv[2]||path.join(__dirname,'../web/app/static/js');
const read=name=>fs.readFileSync(path.join(root,name),'utf8');
function extract(s,n,async=false){const start=s.indexOf(`${async?'async ':''}function ${n}(`);assert(start>=0);return s.slice(start,s.indexOf('\n}',start)+2);}
function el(){
    return {className:'',title:'',textContent:'',children:[],
        appendChild(child){this.children.push(child);return child;},
        querySelector(sel){return sel==='.chat-msg-wrapper'?this.wrapper||null:null;},
        querySelectorAll(){return [];}};
}
function context(){
    const c=vm.createContext({
        window:{},
        document:{
            createElement:()=>el(),
            getElementById:()=>null,
        },
        Date,Number,JSON,Math,String,Object,Array,
        _footerI18n:()=>({time:'Time',tokens:'Tokens',input:'In',output:'Out',tools:'Tools',unit_s:'s',unit_times:'x',hint_total:'',hint_input:'',hint_output:''}),
    });
    vm.runInContext(extract(read('brachybot-chat-core.js'),'_buildResponseFooter'),c);
    vm.runInContext(extract(read('brachybot-chat-core.js'),'_appendRestoredFooter'),c);
    return c;
}
async function main(){
    // A message with no turn statistics must not fabricate "0.0s / 0x":
    // the hidden visual-analysis child used to leave exactly that footer.
    let c=context();
    c.window._chatTurnStartTime=null;c.window._todoTurnToolCount=0;
    assert.equal(c._buildResponseFooter(null),null);
    assert.equal(c._buildResponseFooter({usage:{},latency_ms:0,llm_calls:0}),null);

    // Real statistics still render a footer.
    c=context();
    c.window._chatTurnStartTime=Date.now()-1000;c.window._todoTurnToolCount=2;
    const footer=c._buildResponseFooter({usage:{prompt_tokens:10,completion_tokens:5,total_tokens:15},latency_ms:2000,llm_calls:2});
    assert(footer);
    const values=footer.children
        .filter(child=>child.className==='usage-item')
        .map(child=>child.children.map(part=>String(part.textContent||'')).join(''));
    assert(values.some(v=>/Tools/.test(v)&&/2x/.test(v)));

    // Restoring a transcript entry without stats appends nothing.
    c=context();
    const wrapper=el();
    const row=el();row.wrapper=wrapper;
    const rows=[row];
    c.document.getElementById=()=>({querySelectorAll:()=>rows,querySelector:()=>null});
    c._appendRestoredFooter({requestId:'r1'});
    c._appendRestoredFooter({toolCount:0,elapsedSec:null,llmMeta:null});
    assert.equal(wrapper.children.length,0);

    // Restoring a transcript entry with real stats appends its footer.
    c._appendRestoredFooter({toolCount:2,elapsedSec:'24.4',llmMeta:{usage:{prompt_tokens:10,completion_tokens:5,total_tokens:15},llm_calls:2}});
    assert.equal(wrapper.children.length,1);
    console.log('PASS: no fabricated 0.0s/0x footers, real stats still render and restore');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
