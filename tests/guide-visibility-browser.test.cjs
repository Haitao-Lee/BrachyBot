const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
    process.env.BRACHYBOT_VIEWER_SOURCE
        || path.join(__dirname, '..', 'web', 'app', 'static', 'js', 'brachybot-viewer-volume.js'),
    'utf8',
);
const start = source.indexOf('function setDataItemVisibility(');
const end = source.indexOf('let _opacityTimer', start);
assert.ok(start >= 0 && end > start);

const guide = { id: 'guide_mesh_v1', source: 'surgical_guide', visible: false };
let toggles = 0;
const context = {
    dataTreeState: { organs: [], ctvLabels: {}, skin: {}, planning: { meshes: [guide] } },
    _planningItems: kind => kind === 'meshes' ? [guide] : [],
    _isDataTreeMaskId: () => false,
    toggleDataVisibility: id => {
        assert.equal(id, guide.id);
        toggles += 1;
        guide.visible = !guide.visible;
    },
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);

assert.equal(context.setDataItemVisibility(guide.id, true), true);
assert.equal(guide.visible, true);
assert.equal(toggles, 1);
assert.equal(context.setDataItemVisibility(guide.id, true), true);
assert.equal(toggles, 1, 'show is idempotent, unlike a blind eye-button toggle');
assert.equal(context.setDataItemVisibility(guide.id, false), true);
assert.equal(guide.visible, false);
assert.equal(toggles, 2);
assert.equal(context.setDataItemVisibility('missing_guide', true), false);
assert.equal(toggles, 2);

console.log('guide visibility browser adapter: passed');
