// Unit exercise of the production scheduler, not a GPU/image correctness test.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../web/app/static/js/brachybot-3d-manual.js'),'utf8');
const code=source.slice(source.indexOf('    function requestRender(frameBudget'),source.indexOf('    // Called by layout/fullscreen restoration'));
const callbacks=[],timeouts=[];let geometry=null,renders=0,capture=false;
const noop=()=>{};
const scene3D={renderer:{setViewport:noop,setScissor:noop,setScissorTest:noop},camera:{quaternion:{}},
 controls:{update:()=>false},scene:{},depthPeeling:{render(_s,_c,options){renders++;capture=options.capture;}}};
scene3D.renderer.render=noop;
const sandbox={scene3D,document:{hidden:false},window:{},pendingFrames:0,renderFrameId:0,drawingFrame:false,
 axesGroup:{quaternion:{copy:noop}},axesScene:{},axesCamera:{},updateCameraClipRange:noop,
 syncViewer3DSize:()=>geometry,requestAnimationFrame:fn=>{callbacks.push(fn);return callbacks.length;},
 setTimeout:fn=>timeouts.push(fn)};
vm.createContext(sandbox);vm.runInContext(code,sandbox);
sandbox.requestRender(2);callbacks.shift()();
assert.equal(renders,0);assert.equal(timeouts.length,0);assert.equal(callbacks.length,0);
assert.equal(sandbox.pendingFrames,2);
geometry={cssWidth:800,cssHeight:600};sandbox.resizeViewer3D();callbacks.shift()();
assert.equal(renders,1);assert.equal(capture,false);
sandbox.renderSceneNow();assert.equal(renders,2);assert.equal(capture,true);
sandbox.document.hidden=true;const before=callbacks.length;sandbox.requestRender(2);
assert.equal(callbacks.length,before);
console.log('PASS hidden canvas keeps pending budget without polling, resize resumes, capture stays full quality');
