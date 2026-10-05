// Immutable capture identity can change a label/color, never target geometry.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=process.argv[2] || path.resolve(__dirname,'../web/app/static/js');
const source=fs.readFileSync(path.join(root,'brachybot-visual-annotation.js'),'utf8');
function extract(name){const start=source.indexOf(`    function ${name}(`),end=source.indexOf('\n    function ',start+14);
    assert(start>=0 && end>start,name);return source.slice(start,end);}
const ctx={text:(value,limit=400)=>String(value??'').trim().slice(0,limit),metadataFor:a=>a.view_metadata || {},
    languageFor:(_a,c)=>c.language || 'en',annotationSemanticKind:()=> 'needle',annotationOrdinal:()=> '23',annotationVersion:()=> '',hasCjk:v=>/[\u4e00-\u9fff]/.test(v)};
vm.createContext(ctx);vm.runInContext(extract('monitorCaptureIdentity')+'\n'+extract('localizedAnnotationLabel'),ctx);
const target={target_ref:'needle_23'},mark={target_ref:'needle_23',label:'Needle 23'};
const attachment={mode:'monitor',view_metadata:{monitor_spatial_labels:[{ref:'needle_23',letter:'A',role:'edited',kind:'needles'},
    {ref:'seed_1_4',letter:'B',role:'spacing',kind:'seeds'}]}};
const before=JSON.stringify([mark,target,attachment]);
assert.equal(ctx.localizedAnnotationLabel(mark,target,attachment,{language:'zh'}),'A · 刚编辑的针道');
assert.equal(ctx.localizedAnnotationLabel(mark,target,attachment,{language:'en'}),'A · Edited needle');
assert.equal(ctx.localizedAnnotationLabel({target_ref:'seed_1_4'},{target_ref:'seed_1_4'},attachment,{language:'zh'}),'B · 间距检查对象');
assert.equal(JSON.stringify([mark,target,attachment]),before,'letter labeling does not change bounds, refs or snapshots');
assert.equal(ctx.monitorCaptureIdentity({target_ref:'other'},target,attachment),null,'label cannot retarget a mark');
assert.equal(ctx.monitorCaptureIdentity(mark,target,{...attachment,mode:'report'}),null,'ordinary reports keep their existing semantic captions');
assert.equal(ctx.monitorCaptureIdentity(mark,target,{...attachment,view_metadata:{}}),null,'no snapshot means no invented letters');
for(const rows of [
    [{ref:'needle_23',letter:'A',role:'edited',kind:'needles'},{ref:'needle_23',letter:'B',role:'spacing',kind:'seeds'}],
    [{ref:'needle_23',letter:'A',role:'edited',kind:'needles'},{ref:'seed_1_4',letter:'A',role:'spacing',kind:'seeds'}],
    [{ref:'needle_23',letter:'Z',role:'edited',kind:'needles'}],
    [{ref:'needle_23',letter:'A',role:'optimized',kind:'needles'}],
])assert.equal(ctx.monitorCaptureIdentity(mark,target,{...attachment,view_metadata:{monitor_spatial_labels:rows}}),null,'ambiguous or invented roles fail closed');
assert.equal(ctx.localizedAnnotationLabel(mark,target,{mode:'chat'},{language:'zh'}),'针道 23','non-monitor localization remains unchanged');
const pipeline=fs.readFileSync(path.join(root,'brachybot-ui-api.js'),'utf8');
assert.equal((pipeline.match(/monitor_spatial_labels:options.monitorOnly/g)||[]).length,2,'upload and returned attachment share the frozen identity');
assert(pipeline.indexOf('const restoreMonitorAnnotations=')<pipeline.indexOf('const evidenceBundle = await _captureScreenshotEvidenceBundle('));
assert(pipeline.includes('restoreMonitorAnnotations?.();'),'all capture outcomes restore the live helper');
console.log('Capture identity: bilingual snapshot letters, exact-ref and mode boundaries, duplicate/unknown rejection, unchanged grounding and ordinary report labels passed.');
