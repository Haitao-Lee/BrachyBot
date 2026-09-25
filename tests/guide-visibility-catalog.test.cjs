const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
    process.env.BRACHYBOT_UI_API_SOURCE
        || path.join(__dirname, '..', 'web', 'app', 'static', 'js', 'brachybot-ui-api.js'),
    'utf8',
);
function definition(start, end) {
    const from = source.indexOf(start);
    const to = source.indexOf(end, from + start.length);
    assert.ok(from >= 0 && to > from, `Could not find ${start}`);
    return source.slice(from, to);
}

const context = {
    _dataTreeGroupObjectIds: () => ['guide_mesh_v1'],
};
vm.createContext(context);
vm.runInContext(
    definition('function _visualCatalogFamily(', 'const visualTargetProviders')
    + definition('function _uiOperationVirtualTreeActions(', 'function _uiOperationSceneActions('),
    context,
);

const catalog = context._uiOperationVirtualTreeActions([{
    id: 'guide_mesh_v1',
    objectId: 'surgical_guide:active',
    source: 'surgical_guide',
    label: 'Puncture guide v1',
    parentId: 'planning_meshes',
    visible: false,
    status: 'stale',
}]);
const visibility = catalog.find(item => item.ref === 'data-tree:guide_mesh_v1:visibility');
assert.ok(visibility, 'hidden guide must still publish its Data Tree eye capability');
assert.equal(visibility.visible, true, 'the row, not the mesh, is actionable');
assert.equal(visibility.object_visible, false);
assert.equal(visibility.available, true, 'stale does not mean the saved mesh is absent');
assert.equal(visibility.action.target, 'tree.visibility');
assert.ok(visibility.aliases.includes('导板'));
assert.ok(visibility.aliases.includes('puncture guide'));

const group = catalog.find(item => item.ref === 'data-tree-group:planning_meshes:visibility');
assert.ok(group);
assert.equal(group.action.target, 'tree.group.visibility');
assert.notEqual(visibility.action.target, group.action.target);

console.log('guide visibility catalogue: passed');
