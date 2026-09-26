const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = process.argv[2] || path.resolve(__dirname, '../web/app/static/js');
const THREE = require(path.join(root, 'three.min.js'));
let sessionId = 'case-a';
const dvh = {hidden: false};
const scene3D = {scene: new THREE.Scene(), requestRender() {}, meshes: {}};
const context = vm.createContext({THREE, scene3D, document: {getElementById: () => dvh},
    _activeApiSessionId: () => sessionId, dataTreeState: {planning: {visible: true}},
    renderDataTree() {}, applyDataTreeViewVisibility() {}});
context.window = context;
vm.runInContext(fs.readFileSync(path.join(root, 'brachybot-manual-step-results.js'), 'utf8'), context);
const steps = ['trajectory_init', 'trajectory_refine', 'seed_planning', 'dose_calc', 'dose_eval'];
const geometry = {trajectories: [{points: [[0,0,0],[20,0,0]]}],
    close_points: Array.from({length: 300}, (_, i) => ({position: [i / 10,0,0]}))};
const layer = step => scene3D.scene.children.find(item => item.userData.revision === step);
let catalog = {planning_id: 'p1', stages: []};
for (const step of steps) {
    const token = context.beginManualStepPresentation(step, sessionId);
    assert(token);
    assert.equal(context.beginManualStepPresentation(step, sessionId), null, 'concurrent step rejected');
    assert(context.manualStepPresentations().every(entry => !entry.visible), 'next click hides earlier outputs');
    catalog = {...catalog, active_step: step, stages: catalog.stages.concat({step, revision: step,
        geometry: steps.indexOf(step) < 2 ? geometry : undefined,
        shown_trajectories: 1, trajectory_count: 1, close_point_count: 300,
        seed_count: 181, has_dose: true, has_dvh: true})};
    assert.equal(context.hydrateManualStepPresentations(catalog, sessionId), false, 'background restore cannot interrupt step');
    context.publishManualStepPresentation(step, sessionId, null, {}, catalog);
    context.finishManualStepPresentation(token, true);
    assert.equal(context.manualStepPresentations().length, steps.indexOf(step) + 1);
    assert.equal(context.manualStepPresentations().filter(entry => entry.visible).length, 1);
    assert.equal(context.manualStepNodeVisible({id: 'seed_1_1'}), step === 'seed_planning');
    assert.equal(context.manualStepNodeVisible({id: 'needle_1'}), step === 'seed_planning');
    assert.equal(context.manualStepNodeVisible({id: 'dose_iso_120'}), step === 'dose_calc');
    assert.equal(context.manualStepNodeVisible({id: 'dose_overlay'}), step === 'dose_calc');
    assert.equal(dvh.hidden, step !== 'dose_eval');
    assert.equal(context.manualStepNodeVisible({id: 'ctv_2'}), true, 'anatomy unchanged');
}
assert.equal(layer('trajectory_init').children.find(item => item.isInstancedMesh).count, 300);
context.dataTreeState.planning.dvh = {visible:false};
context.syncManualStepPresentationVisibility();
assert.equal(dvh.hidden, true, 'stage does not override an individually hidden DVH');
context.dataTreeState.planning.dvh.visible = true;
context.syncManualStepPresentationVisibility();
assert.equal(layer('trajectory_init').visible, false);
context.toggleManualStepPresentation('trajectory_init');
assert.equal(layer('trajectory_init').visible, true, 'older stage can be reviewed');
const failed = context.beginManualStepPresentation('trajectory_refine', sessionId);
context.finishManualStepPresentation(failed, false);
assert.equal(layer('trajectory_init').visible, true, 'failure restores exact prior selection');
assert.equal(dvh.hidden, false);
context.__reportCaptureActive = true;
assert.equal(context.manualStepNodeVisible({id:'seed_1'}), true, 'report transaction not suppressed');
context.__reportCaptureActive = false;
const restore = context.revealManualStepNodes([{id:'seed_1'}]);
assert.equal(restore.changed, true);
assert.equal(context.manualStepNodeVisible({id:'seed_1'}), true);
restore();
assert.equal(context.manualStepNodeVisible({id:'seed_1'}), false, 'screenshot transaction restores stage');
context.hydrateManualStepPresentations(catalog, sessionId);
assert.equal(layer('trajectory_init').visible, true, 'refresh preserves local eye choice');
const late = context.beginManualStepPresentation('trajectory_init', sessionId);
context.clearManualStepPresentation();
sessionId = 'case-b';
assert.equal(context.publishManualStepPresentation('dose_calc', 'case-a'), false);
sessionId = 'case-a';
assert.equal(context.isCurrentManualStepRequest(late), false, 'A -> B -> A does not re-authorize old response');
context.hydrateManualStepPresentations(catalog, sessionId);
assert.equal(context.currentManualStepPresentation().step, 'dose_eval', 'restore uses persisted active stage');
assert.equal(layer('trajectory_init').visible, false);
assert.equal(scene3D.scene.children.length, 2, 'only candidate stages own extra geometry');
assert.deepEqual(Object.keys(scene3D.meshes), [], 'candidates never become editable clinical meshes');
// Ordinary chat cleanup is deliberately disjoint from this module.
const source = fs.readFileSync(path.join(root, 'brachybot-3d-manual.js'), 'utf8');
const block = source.split('function clearPlanningPreview(')[1].split('\nfunction ')[0];
assert(!block.includes('clearManualStep') && !block.includes('_manualStepPresentation'));
console.log('Manual outputs: five stages, 300 close points, eye controls, rollback, restore, capture and session fencing passed.');
