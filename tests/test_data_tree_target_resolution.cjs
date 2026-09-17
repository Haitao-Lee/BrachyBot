// Run: node tests/test_data_tree_target_resolution.cjs [repository root]
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = process.argv[2];
const dir = root ? path.join(root, 'web/app/static/js') : __dirname;
const api = fs.readFileSync(path.join(dir, 'brachybot-ui-api.js'), 'utf8');
const annotation = fs.readFileSync(path.join(dir, 'brachybot-visual-annotation.js'), 'utf8');
let rows = [];
const document = {
  querySelector: selector => selector === '#dataTreeBody' ? {querySelectorAll: () => rows} : null,
  querySelectorAll: () => rows,
};
const context = vm.createContext({document, window: {}, text: v => String(v || '').trim()});
vm.runInContext(api.slice(api.indexOf('function _dataTreeRowSemanticIdentity('), api.indexOf('function _dataTreeEvidenceRows(')), context);
vm.runInContext(annotation.slice(annotation.indexOf('    function semanticDataTreeTarget('), annotation.indexOf('    function currentDomTarget(')), context);
const row = (dataset, label = '') => ({
  dataset, textContent: label,
  classList: {contains: name => name === 'planning-history-artifact' && dataset.source === 'planning_history'},
  closest: () => null,
  getBoundingClientRect: () => ({width: 100, height: 24}),
});
const history = row({nodeId: 'planning:old:surgical_guide', nodeType: 'planning_artifact', source: 'planning_history', status: 'ready'}, 'Surgical Guide');
const guide = row({objectId: 'surgical_guide:active', nodeId: 'patient_specific_puncture_guide', nodeType: 'surgical_guide', status: 'stale', visible: 'false'}, 'Renamed guide');
rows = [history, row({nodeType: 'skin'}, 'Surgical Guide'), guide];
const resolve = context.window.resolveDataTreeRowTargetRef;
assert.equal(resolve('surgical_guide:active'), guide);
assert.equal(context.semanticDataTreeTarget('surgical_guide:active').element, guide);
assert.equal(context.semanticDataTreeTarget('surgical_guide:active').status, 'stale');
assert.equal(guide.dataset.visible, 'false');
assert.equal(resolve('planning:old:surgical_guide'), null);
assert.equal(resolve('surgical_guide:missing'), null);
assert.equal(resolve('surgical_guide'), guide);
rows = [history];
assert.equal(resolve('surgical_guide:active'), null);
assert.equal(context.semanticDataTreeTarget('surgical_guide:active'), null);
assert.equal(resolve('planning:old:surgical_guide', {allowHistorical: true}), null);
for (const type of ['seed', 'trajectory', 'dvh', 'dose', 'report', 'segmentation']) {
  const real = row({objectId: `${type}:active`, nodeType: type, liveNode: 'true'});
  rows = [row({objectId: `${type}:active`, nodeType: 'planning_artifact', liveNode: 'false'}), real];
  assert.equal(resolve(`${type}:active`), real);
  assert.equal(context.semanticDataTreeTarget(`${type}:active`).element, real);
}
rows = [row({nodeId: 'old:seed_1'}), row({nodeId: 'seed_11'})];
assert.equal(resolve('seed_1'), null);
assert.ok(api.includes('window.matchDataTreeRowTargetRef = _dataTreeRowMatchesTargetRef'));
assert.match(api, /function _dataTreeRowForTargetRef[\s\S]*?return window\.resolveDataTreeRowTargetRef\(ref\)/);
console.log('PASS: live identity grounding, history exclusion, aliases, missing targets, status and six data types');
