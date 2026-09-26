// Synthetic Viewer test: no case files, clinical operations or network calls.
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const root = process.argv[2] || path.resolve(__dirname, '../web/app/static/js');
const source = fs.readFileSync(path.join(root, 'brachybot-3d-manual.js'), 'utf8');
function extract(name) {
    const start = source.indexOf(`function ${name}(`);
    assert(start >= 0, name);
    const end = source.indexOf('\nfunction ', start + 12);
    assert(end > start, name);
    return source.slice(start, end);
}
const stageStart = source.indexOf('const _planningPreviewState = {');
const stageEnd = source.indexOf('\nfunction _planningPreviewCurrentSession()', stageStart);
assert(stageStart >= 0 && stageEnd > stageStart);

(async () => {
    const browser = await chromium.launch({headless: true, executablePath: process.env.CHROME_PATH
        || (process.platform === 'win32' ? 'C:/Program Files/Google/Chrome/Application/chrome.exe' : undefined),
        args: ['--enable-webgl', '--enable-unsafe-swiftshader']});
    try {
        const page = await browser.newPage();
        await page.setContent('<div id="planningPreviewStatus" hidden></div><div id="dvhChart"></div><div id="testTree"></div>');
        await page.addScriptTag({path: path.join(root, 'three.min.js')});
        await page.addScriptTag({content: `
            window.activeSessionId = 'case-a'; window.state = {sessionId:'case-a'};
            window.dataTreeState = {planning:{visible:true}};
            window.scene3D = {scene:new THREE.Scene(), camera:new THREE.PerspectiveCamera(50,1,0.01,5000),
                controls:{target:new THREE.Vector3(),minDistance:1}, meshes:{}, requestRender(){}};
            scene3D.camera.position.set(0,0,100);
            window.init3DScene=()=>{}; window.renderDataTree=()=>{};
            window.manualPlanningMasterVisible=true;
            window._planningMasterVisible=()=>window.manualPlanningMasterVisible;
            window._planningViewVisible=()=>window.manualPlanningMasterVisible;
            window.uiDebugLog=()=>{}; window._showPlanningPreviewStatus=()=>{};
            window.sync3DCameraPose=pose=>{
                scene3D.camera.position.copy(pose.position);scene3D.controls.target.copy(pose.target);
                scene3D.camera.up.copy(pose.up);scene3D.camera.lookAt(pose.target);
                scene3D.camera.updateProjectionMatrix();
            };
        `});
        const functions = [
            '_setPlanningPreviewClosePoints', '_planningPreviewCurrentSession',
            '_hidePlanningPreviewStatus', '_planningPreviewLine', '_ensurePlanningPreviewLayer',
            '_setPlanningPreviewLine', '_setPlanningPreviewSeeds', '_emptyPlanningPreviewLayer',
            '_disposePlanningPreviewLayer', 'clearPlanningPreview', '_renderPlanningPreviewFrame',
        ];
        await page.addScriptTag({content: source.slice(stageStart, stageEnd)
            + '\n' + functions.map(extract).join('\n')});
        await page.addScriptTag({path:path.join(root, 'brachybot-manual-step-results.js')});
        const treeSource = fs.readFileSync(path.join(root, 'brachybot-viewer-volume.js'), 'utf8');
        const rowsStart = treeSource.indexOf('for (const manualStage of window.manualStepPresentations');
        const rowsEnd = treeSource.indexOf('// Trajectories group', rowsStart);
        assert(rowsStart > 0 && rowsEnd > rowsStart);
        await page.addScriptTag({content: `
            window.escHtml=value=>String(value).replace(/&/g,'&amp;').replace(/</g,'&lt;');
            window._dtText=(zh,en)=>en;
            window.renderDataTree=()=>{let html=''; const planningMasterVisible=true;
                ${treeSource.slice(rowsStart, rowsEnd)}
                document.getElementById('testTree').innerHTML=html;
            };
        `});
        const result = await page.evaluate(() => {
            publishManualStepPresentation('trajectory_init', 'case-a', {
                trajectory_count: 1, shown_trajectories: 1, close_point_count: 1,
                geometry: {trajectories: [{points: [[0,0,0],[20,0,0]]}],
                    close_points: [{position:[10,0,0]}]},
            });
            const group = scene3D.scene.children.find(object => object.userData.renderRole === 'manual_step_result');
            const sharedRow = document.querySelectorAll('.manual-step-result').length === 1
                && document.getElementById('testTree').textContent.includes('close points');
            document.querySelector('.manual-step-result button').click();
            const eyeHidesBoth = !group.visible;
            document.querySelector('.manual-step-result button').click();
            const renderer = new THREE.WebGLRenderer({preserveDrawingBuffer:true});
            renderer.setSize(320,320);
            document.body.appendChild(renderer.domElement);
            renderer.render(scene3D.scene, scene3D.camera);
            const gl = renderer.getContext();
            const pixels = new Uint8Array(320 * 320 * 4);
            gl.readPixels(0,0,320,320,gl.RGBA,gl.UNSIGNED_BYTE,pixels);
            const painted = pixels.some((value,index) => index % 4 !== 3 && value > 20);
            clearPlanningPreview('stream-complete');
            const shown = {
                treeStep: currentManualStepPresentation()?.step,
                group: group.visible,
                path: group.children.some(object => object.isLineSegments && object.visible),
                closePoints: group.children.find(object => object.isInstancedMesh)?.count,
                readOnly: group.userData.readOnly === true, painted, sharedRow, eyeHidesBoth,
                cameraTarget: scene3D.controls.target.toArray(),
            };
            manualPlanningMasterVisible = false;
            syncManualStepPresentationVisibility();
            const hiddenWithMaster = group.visible;
            manualPlanningMasterVisible = true;
            syncManualStepPresentationVisibility();
            const restoredWithMaster = group.visible;
            const token = beginManualStepPresentation('trajectory_refine','case-a');
            const hiddenOnNext = !group.visible;
            const keptRow = manualStepPresentations().length === 1;
            finishManualStepPresentation(token, false);
            const failureRestored = group.visible;
            clearManualStepPresentation('workspace-transition');
            renderer.dispose();
            return {...shown, afterGroup: !!group.parent,
                afterTree: currentManualStepPresentation() || null, hiddenWithMaster, restoredWithMaster,
                hiddenOnNext, keptRow, failureRestored};
        });
        assert.equal(result.treeStep, 'trajectory_init');
        assert.equal(result.group, true);
        assert.equal(result.path, true);
        assert.equal(result.closePoints, 1);
        assert.equal(result.readOnly, true);
        assert.equal(result.painted, true, 'real WebGL buffer contains result pixels');
        assert.equal(result.sharedRow, true, 'paths and close points share one real Data Tree row');
        assert.equal(result.eyeHidesBoth, true, 'the DOM eye controls both objects');
        assert.equal(result.hiddenOnNext, true);
        assert.equal(result.keptRow, true);
        assert.equal(result.failureRestored, true);
        assert.equal(result.hiddenWithMaster, false);
        assert.equal(result.restoredWithMaster, true);
        assert.equal(result.afterGroup, false);
        assert.equal(result.afterTree, null);
        assert(Math.abs(result.cameraTarget[0] - 10) < 1);
        console.log('Real WebGL rendering: paths + close points, chat cleanup isolation, next-stage hiding and failure rollback passed.');
    } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
