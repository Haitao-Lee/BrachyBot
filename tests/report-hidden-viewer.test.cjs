// Synthetic WebGL regression: never opens a patient session or production URL.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
let chromium;
try { ({chromium} = require('playwright')); }
catch { ({chromium} = require('./test-runtime/node_modules/playwright')); }
const root = process.argv[2] || path.resolve(__dirname, '../web/app');
const local = fs.existsSync(path.join(root, 'brachybot-report-editor.js'));
const js = name => fs.readFileSync(path.join(root, local ? '' : 'static/js', name), 'utf8');
const css = name => fs.readFileSync(path.join(root, local ? '' : 'static/css', name), 'utf8');
const extract = (s, name) => { const i=s.indexOf('function '+name+'('); assert(i>=0); return s.slice(i,s.indexOf('\n}',i)+2); };
(async()=>{
 const browser = await chromium.launch({headless:true,
   ...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {}),
   args:['--enable-webgl','--enable-unsafe-swiftshader']});
 try {
  const page=await browser.newPage();
  const html=fs.readFileSync(path.join(root,'index.html'),'utf8')
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'').replace(/<link\b[^>]*>/gi,'');
  await page.setContent(html);
  for(const name of ['brachybot-theme-layout.css','brachybot-panels-viewers.css','brachybot-report-controls.css'])
    await page.addStyleTag({content:css(name)});
  await page.addScriptTag({content:'window.scene3D={resize(){},requestRender(){}};'+extract(js('brachybot-report-editor.js'),'prepareReportCaptureLayout')});
  const result=await page.evaluate(()=>{
   const panel=document.getElementById('panelViewers');
   panel.classList.remove('active');
   const original=panel.getAttribute('style');
   const before=panel.getBoundingClientRect().width;
   let restore=prepareReportCaptureLayout();
   try {
    const host=document.getElementById('canvas3D');
    const r=host.getBoundingClientRect();
    if(r.width<10||r.height<10) throw Error('hidden viewer not laid out: '+JSON.stringify(r.toJSON()));
    const canvas=document.createElement('canvas');canvas.width=64;canvas.height=64;host.append(canvas);
    const gl=canvas.getContext('webgl',{preserveDrawingBuffer:true});
    if(!gl) throw Error('WebGL unavailable');
    gl.clearColor(1,0,0,1);gl.clear(gl.COLOR_BUFFER_BIT);
    const pixel=new Uint8Array(4);gl.readPixels(32,32,1,1,gl.RGBA,gl.UNSIGNED_BYTE,pixel);
    canvas.remove();
    return {before,width:r.width,height:r.height,pixel:[...pixel],original};
   } finally {restore();}
  });
  assert.equal(result.before,0);assert.deepEqual(result.pixel,[255,0,0,255]);
  assert.equal(await page.$eval('#panelViewers',e=>e.getAttribute('style')),result.original);
  assert.equal(await page.$eval('#panelViewers',e=>e.getBoundingClientRect().width),0);
  await page.evaluate(()=>{const restore=prepareReportCaptureLayout();try{throw Error('capture failure');}catch{}finally{restore();}});
  assert.equal(await page.$eval('#panelViewers',e=>e.getAttribute('style')),result.original);
  console.log('PASS hidden viewer: nonzero layout, WebGL pixel readback, exact restoration on success/failure',result);
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
