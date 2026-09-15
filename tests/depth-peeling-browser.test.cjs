const {chromium} = require('playwright');
const path = require('node:path');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const assets = fs.existsSync(path.join(__dirname, '../web/app/static/js/three.min.js'))
 ? path.join(__dirname, '../web/app/static/js') : __dirname;
(async () => {
 const browser = await chromium.launch({executablePath: process.env.CHROME_PATH || (process.platform === 'win32' ? 'C:/Program Files/Google/Chrome/Application/chrome.exe' : undefined),
   headless: true, args: ['--enable-webgl', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
 try {
 const page = await browser.newPage({viewport: {width: 600, height: 600}});
 const errors = [];
 page.on('pageerror', e => errors.push(String(e)));
 page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
 await page.setContent('<body style="margin:0;background:black"></body>');
 await page.addScriptTag({path: path.join(assets, 'three.min.js')});
 await page.addScriptTag({path: path.join(assets, 'brachybot-depth-peeling.js')});
 const result = await page.evaluate(async () => {
  const r = new THREE.WebGLRenderer({preserveDrawingBuffer: true, alpha: true});
  r.setSize(256,256); r.setClearColor(0,1); r.sortObjects=false;
  document.body.appendChild(r.domElement);
  const scene=new THREE.Scene(), camera=new THREE.PerspectiveCamera(45,1,.1,100);
  camera.position.set(0,0,5); camera.lookAt(0,0,0);
  const red=new THREE.Mesh(new THREE.PlaneBufferGeometry(3,3), new THREE.MeshBasicMaterial({color:0xff0000,transparent:true,opacity:.5,side:THREE.DoubleSide,depthWrite:false}));
  const blue=new THREE.Mesh(new THREE.PlaneBufferGeometry(3,3), new THREE.MeshBasicMaterial({color:0x0000ff,transparent:true,opacity:.5,side:THREE.DoubleSide,depthWrite:false}));
  red.rotation.y=.55; blue.rotation.y=-.55; scene.add(red,blue);
  const peel=new BrachyDepthPeeling(r);
  if(!peel.supported) throw Error('Depth texture support unavailable');
  const originalRed=red.material, originalBlue=blue.material;
  const pixels=()=>{const data=new Uint8Array(256*256*4);r.getContext().readPixels(0,0,256,256,r.getContext().RGBA,r.getContext().UNSIGNED_BYTE,data);return data;};
  const sample=(data,x,y)=>Array.from(data.slice((y*256+x)*4,(y*256+x)*4+4));
  let maximumOrderDifference=0; const frames=[];
  for(const angle of [0,.4,-.4,Math.PI]) {
   camera.position.set(Math.sin(angle)*5,0,Math.cos(angle)*5);camera.lookAt(0,0,0);
   const begin=performance.now();peel.render(scene,camera);const a=pixels();
   scene.remove(red,blue);scene.add(blue,red);peel.render(scene,camera);const b=pixels();
   for(let i=0;i<a.length;i++) maximumOrderDifference=Math.max(maximumOrderDifference,Math.abs(a[i]-b[i]));
   frames.push({angle,ms:performance.now()-begin,left:sample(a,96,128),right:sample(a,160,128)});
   scene.remove(red,blue);scene.add(red,blue);
  }
  camera.position.set(0,0,5);camera.lookAt(0,0,0);
  const green=new THREE.Mesh(new THREE.PlaneBufferGeometry(.6,.6),new THREE.MeshBasicMaterial({color:0x00ff00}));
  green.position.z=1;scene.add(green);peel.render(scene,camera,{capture:true});
  const opaqueCenter=sample(pixels(),128,128);
  const restored=red.material===originalRed&&blue.material===originalBlue;
  peel.render(scene,camera,{interactive:true});const interactive={...peel.lastFrame};
  peel.render(scene,camera,{capture:true});const capture={...peel.lastFrame};
  const physical=new THREE.Mesh(new THREE.SphereBufferGeometry(.5,16,12),new THREE.MeshPhysicalMaterial({color:0xffff00,opacity:.4,transparent:true,side:THREE.DoubleSide}));
  scene.add(physical,new THREE.AmbientLight(0xffffff));
  peel.render(scene,camera);
  physical.visible=false;
  peel.render(scene,camera);
  const hiddenUnchanged=physical.visible===false;
  const originalRender=r.render.bind(r);let thrown=false;
  let calls=0;
  r.render=(...args)=>{if(++calls===3)throw Error('injected render failure');return originalRender(...args);};
  try{peel.render(scene,camera);}catch(e){thrown=true;}finally{r.render=originalRender;}
  const failureRestored=red.material===originalRed && blue.material===originalBlue && r.getRenderTarget()===null;
  peel.render(scene,camera);
  // Give asynchronous GPU queries a later event-loop turn to complete.
  for(let i=0;i<6;i++){await new Promise(resolve=>setTimeout(resolve,200));peel.render(scene,camera);}
  const settledLayers=peel.lastFrame.layers;
  return {maximumOrderDifference,frames,opaqueCenter,restored,interactive,capture,hiddenUnchanged,thrown,failureRestored,settledLayers};
 });
 assert.deepEqual(errors, [], 'browser shader/runtime errors');
 assert.equal(result.maximumOrderDifference,0);
 assert.equal(result.restored,true);
 assert.ok(result.frames[0].left[0] > result.frames[0].left[2]);
 assert.ok(result.frames[0].right[2] > result.frames[0].right[0]);
 assert.deepEqual(result.opaqueCenter,[0,255,0,255]);
 assert.equal(result.interactive.width, result.capture.width);
 assert.equal(result.interactive.height, result.capture.height);
 assert.equal(result.capture.layers,64);
 assert.equal(result.hiddenUnchanged,true);
 assert.equal(result.thrown,true);
 assert.equal(result.failureRestored,true);
 assert.ok(result.settledLayers <= 4, 'empty layers should be skipped after asynchronous queries');
 await page.screenshot({path:path.join(__dirname,'depth-peeling-test.png')});
 console.log(JSON.stringify(result,null,2));
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
