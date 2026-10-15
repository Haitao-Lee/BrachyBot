const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = process.argv[2];
const viewer = fs.readFileSync(path.join(root, 'web/app/static/js/brachybot-viewer-volume.js'), 'utf8');
const layout = fs.readFileSync(path.join(root, 'web/app/static/js/brachybot-viewer-layout.js'), 'utf8');
function fn(source, name) {
    const match = new RegExp(`^(?:async )?function ${name}\\(`, 'm').exec(source);
    assert(match, name);
    const tail = source.slice(match.index);
    return tail.slice(0, /^}/m.exec(tail).index + 1);
}
const controls = {labelShow3d: {checked: false}, labelOp3d: {value: '60'}};
const parent = {id: 'oar', visible: true, visible3D: false};
const organs = [{id: 'organ_1', parentId: 'oar', visible: true, visible3D: true, opacity: .5},
    {id: 'organ_2', parentId: 'oar', visible: true, visible3D: false, opacity: .4}];
let saved = 0, renders = 0;
const ctx = vm.createContext({
    console, Map, Set, Number, String,
    window: {scheduleWorkspaceSave: () => saved++},
    document: {getElementById: id => controls[id]},
    capitalize: s => s[0].toUpperCase() + s.slice(1),
    state: {labelImage: {'3d': {configured: true, visible: false, opacity: .6}}, maskLabels: {}},
    dataTreeState: {ctv: {id: 'ctv'}, oar: parent, organs},
    scene3D: {meshes: Object.fromEntries(organs.map(n => [n.id,
        {visible: false, userData: {id: n.id}, material: {opacity: 0}}])), requestRender: () => renders++},
    _isDataTreeMaskId: id => id.startsWith('upload_'),
    _forEachMaterial: (mesh, f) => f(mesh.material), getMeshSurface: m => m,
    _enableSegmentation2DForNodes: () => {throw Error('must not change 2D');},
    renderDataTree: () => {}, _scheduleDataTreeSave: () => saved++,
    _groupViewScopeNodes: () => [parent],
    _findDataTreeNode: id => organs.find(n => n.id === id),
    getSelectedOrganIds: () => ['organ_1'],
});
ctx.window.getDataTreeAppearanceForMesh = id => {
    const n = organs.find(n => n.id === id);
    return {visible: n.visible !== false && n.visible3D !== false
        && parent.visible !== false && parent.visible3D !== false, opacity: n.opacity};
};
ctx.applyDataTreeViewVisibility = () => {
    for (const [id, mesh] of Object.entries(ctx.scene3D.meshes)) {
        const a = ctx.window.getDataTreeAppearanceForMesh(id);
        ctx.applyMeshVisibility(mesh, a.visible, a.opacity);
    }
};
for (const n of ['applyMeshVisibility', 'applyMeshOpacity']) vm.runInContext(fn(layout,n),ctx);
for (const n of ['updateLabelImage', 'enableSegmentation3DForNodes', '_setNodeViewVisibility',
    'setGroupViewVisibility', 'batchSetViewVisibility']) vm.runInContext(fn(viewer,n),ctx);
ctx.window.enableSegmentation3DForNodes = ctx.enableSegmentation3DForNodes;
let passed = 0;
async function test(name, f) {await f(); console.log('PASS: '+name); passed++;}
(async () => {
    await test('group right-click opens LABEL and paints loaded OAR without revealing hidden sibling', () => {
        ctx.setGroupViewVisibility('oar','3d',true);
        assert.equal(controls.labelShow3d.checked,true);
        assert.equal(ctx.state.labelImage['3d'].visible,true);
        assert.equal(ctx.scene3D.meshes.organ_1.visible,true);
        assert.equal(ctx.scene3D.meshes.organ_1.material.opacity,.3);
        assert.equal(ctx.scene3D.meshes.organ_2.visible,false);
        assert.equal(organs[1].visible3D,false);
    });
    await test('late mesh obeys opened gate; ordinary reconciliation still obeys a saved hide', () => {
        const late = {userData:{id:'organ_3'},material:{}};
        ctx.applyMeshOpacity(late,.5,true); assert.equal(late.visible,true);
        controls.labelShow3d.checked=false; ctx.updateLabelImage('3d');
        ctx.applyMeshVisibility(late,true,.5); assert.equal(late.visible,false);
    });
    await test('leaf right-click opens LABEL and restores nonzero opacity after global zero', () => {
        controls.labelOp3d.value='0'; ctx.updateLabelImage('3d');
        ctx.batchSetViewVisibility('3d',true);
        assert.equal(controls.labelOp3d.value,'60');
        assert.equal(ctx.scene3D.meshes.organ_1.visible,true);
        assert.equal(ctx.scene3D.meshes.organ_1.material.opacity,.3);
        assert.equal(ctx.scene3D.meshes.organ_2.visible,false);
    });
    await test('hide actions keep LABEL unchanged and prevent later reconciliation from showing target', () => {
        ctx.batchSetViewVisibility('3d',false); ctx.applyDataTreeViewVisibility();
        assert.equal(controls.labelShow3d.checked,true);
        assert.equal(ctx.scene3D.meshes.organ_1.visible,false);
    });
    await test('non-label nodes do not open LABEL and per-node zero opacity remains intentional', () => {
        controls.labelShow3d.checked=false; ctx.updateLabelImage('3d');
        assert.equal(ctx.enableSegmentation3DForNodes([{id:'seed_1'}]),false);
        assert.equal(controls.labelShow3d.checked,false);
        organs[0].opacity=0; ctx.batchSetViewVisibility('3d',true);
        assert.equal(organs[0].opacity,0); assert.equal(ctx.scene3D.meshes.organ_1.visible,false);
        assert(saved>0 && renders>0);
    });
    await test('explicit reconstruction opens LABEL even when joining an existing request; silent restore does not', async () => {
        const scope={sessionId:'synthetic'}, flight=new Map();
        const request=Promise.resolve({success:true});
        flight.set('synthetic:organ_1',{scope,promise:request});
        Object.assign(ctx, {_captureViewer3DRequestScope:()=>scope, _viewer3DRequestScopeIsCurrent:()=>true,
            _viewer3DNodeForId:()=>organs[0], _organ3DReconstructionInFlight:flight});
        vm.runInContext(fn(layout,'reconstructOrgan3D'),ctx);
        controls.labelShow3d.checked=false; ctx.updateLabelImage('3d');
        await ctx.reconstructOrgan3D('organ_1',true); assert.equal(controls.labelShow3d.checked,false);
        await ctx.reconstructOrgan3D('organ_1',false); assert.equal(controls.labelShow3d.checked,true);
    });
    await test('explicit group reconstruction opens LABEL before its silent surface workers finish', async () => {
        controls.labelShow3d.checked=false;ctx.updateLabelImage('3d');
        let release; const held=new Promise(r=>release=r);
        Object.assign(ctx,{_captureViewerDataScope:()=>({sessionId:'synthetic'}),
            _viewerDataScopeIsCurrent:()=>true,_dtText:(zh,en)=>en,addChat:()=>{},
            reconstructOrgan3D:async()=>{assert.equal(controls.labelShow3d.checked,true);await held;return {success:true};}});
        vm.runInContext(fn(viewer,'groupReconstruct3D'),ctx);
        const pending=ctx.groupReconstruct3D('oar');
        assert.equal(controls.labelShow3d.checked,true);release();
        assert.equal((await pending).reconstructed,2);
    });
    console.log(`${passed} passed`);
})().catch(e=>{console.error(e);process.exitCode=1;});
