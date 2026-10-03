const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

// Regression: a live Data Tree colour/opacity edit used to be reverted the
// next time the 3D appearance reconciler ran (for example after clicking
// "Dose Surface"). The session presentation registry stays readable for the
// whole case, so the reconciler re-applies the registry over the live node.
// A live edit must therefore mirror itself into that registry record.
//
// This test loads the real viewer helpers with a stubbed registry and proves
// that a colour/opacity edit routed through `_scheduleDataTreeSave(reason, id)`
// is what `getDataTreeAppearanceForMesh` subsequently resolves.

const root = process.argv[2];
assert(root, 'pass the repository root');
const viewerRel = fs.existsSync(path.join(root, 'web/app/static/js/brachybot-viewer-volume.js'))
    ? 'web/app/static/js/brachybot-viewer-volume.js' : 'brachybot-viewer-volume.js';
const viewer = fs.readFileSync(path.join(root, viewerRel), 'utf8');

function topLevelFunction(source, declaration) {
    const start = source.indexOf(declaration);
    assert(start >= 0, `${declaration} exists`);
    let end = source.indexOf('\nfunction ', start + declaration.length);
    if (end < 0) end = source.length;
    return source.slice(start, end).trim();
}

const liveMask = { id: 'upload_mask_label_2', color: '#00ff00', opacity: 0.9, visible: true, visible3D: true };
const registry = { id: 'upload_mask_label_2', color: '#f08a5d', opacity: 0.42, visible: true };

const context = vm.createContext({
    console,
    dataTreeState: {
        ctv: {}, skin: {}, ctvLabels: {}, organs: [],
        planning: { trajectories: [], seeds: [], needles: [], doseLevels: [], meshes: [] },
    },
    state: { maskLabels: { upload_mask_label_2: liveMask } },
    scene3D: { meshes: {} },
    _findDataTreeNode: id => (String(id).includes('upload_mask_label_2') ? liveMask : null),
    _isDataTreeMaskId: id => String(id).includes('upload_mask_label_2') || String(id).startsWith('mask'),
    _maskStateEntry: () => liveMask,
    _maskSceneMeshId: () => 'upload_mask_label_2',
    _planningItems: () => [],
    getSelectableIds: () => ['upload_mask_label_2'],
    isDataTreeNodeVisible3D: () => true,
    window: {
        // The registry stays "finalized" after a restore, which makes
        // `isWorkspacePresentationRestoreActive()` true for the whole case.
        isWorkspacePresentationRestoreActive: () => true,
        getWorkspacePresentationForNode: () => ({ ...registry }),
        updateWorkspacePresentationForNode: (criteria, changes) => {
            Object.assign(registry, changes);
            return true;
        },
        scheduleWorkspaceSave: reason => { context.__lastSaveReason = reason; },
    },
});

vm.runInContext([
    topLevelFunction(viewer, 'function _dataTreePresentationRef('),
    topLevelFunction(viewer, 'function _recordDataTreePresentation('),
    topLevelFunction(viewer, 'function _syncAllDataTreePresentation('),
    topLevelFunction(viewer, 'function _scheduleDataTreeSave('),
    topLevelFunction(viewer, 'function getDataTreeAppearanceForMesh('),
].join('\n'), context);

const before = context.getDataTreeAppearanceForMesh('upload_mask_label_2', { userData: {} });
assert.equal(before.color, '#f08a5d', 'stale registry wins before any live edit');

// Simulate the real setter path: mutate the live node, then save with its id.
liveMask.color = '#00ff00';
liveMask.opacity = 0.9;
context._scheduleDataTreeSave('viewer.color:upload_mask_label_2', 'upload_mask_label_2');

assert.equal(registry.color, '#00ff00', 'live colour is mirrored into the registry');
assert.equal(registry.opacity, 0.9, 'live opacity is mirrored into the registry');

const after = context.getDataTreeAppearanceForMesh('upload_mask_label_2', { userData: {} });
assert.equal(after.color, '#00ff00', 'reconciler keeps the live colour');
assert.equal(after.opacity, 0.9, 'reconciler keeps the live opacity');

// A group/batch edit uses the '*' sentinel to resync every selectable leaf.
registry.color = '#f08a5d';
registry.opacity = 0.42;
context._scheduleDataTreeSave('viewer.group_color:upload_masks', '*');
assert.equal(registry.color, '#00ff00', 'group save resyncs the leaf record');
assert.equal(registry.opacity, 0.9, 'group save resyncs the leaf opacity');

console.log('PASS: live Data Tree appearance edits update the presentation registry so Dose Surface no longer reverts them');
