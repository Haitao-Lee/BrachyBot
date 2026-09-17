// Run with node against the local staging files or the repository JS folder.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = process.argv[2] || __dirname;
function extract(file, name) {
    const src = fs.readFileSync(path.join(root, file), 'utf8');
    const start = src.indexOf(`function ${name}(`);
    assert(start >= 0, name);
    const end = src.indexOf('\nfunction ', start + 10);
    const asyncEnd = src.indexOf('\nasync function ', start + 10);
    return src.slice(src.slice(start - 6, start) === 'async ' ? start - 6 : start,
        Math.min(...[end, asyncEnd].filter(n => n >= 0)));
}
let refreshed = 0;
const parent = { id: 'planning', visible: false, visible3D: false, opacity: .5 };
const guide = { id: 'guide', visible: false, visible3D: false, opacity: 0, parentId: 'planning' };
const sibling = { id: 'other', visible: false, opacity: .3 };
const ctx = {
    _screenshotTargetRefs: p => p.target_refs || [],
    _dataTreeRowForTargetRef: ref => ref === 'guide' ? { dataset: { item: 'guide' } } : null,
    _dataTreeRowIdentities: row => [row.dataset.item],
    _findDataTreeNode: id => id === 'guide' ? guide : null,
    _dataTreeParentNode: node => node === guide ? parent : null,
    applyDataTreeViewVisibility: () => refreshed++, renderDataTree: () => {},
};
vm.createContext(ctx);
for (const name of ['_revealScreenshotNodes', '_orderLocateCaptureViews']) {
    vm.runInContext(extract('brachybot-ui-api.js', name), ctx);
}
const before = JSON.stringify([guide, parent, sibling]);
const restore = ctx._revealScreenshotNodes({ target_refs: ['guide'] });
assert.equal(guide.visible, true);
assert.equal(guide.visible3D, true);
assert.equal(guide.opacity, 1);
assert.equal(parent.visible, true);
assert.equal(sibling.visible, false);
restore();
assert.equal(JSON.stringify([guide, parent, sibling]), before);
assert.equal(refreshed, 2);
const plan = { mode: 'chat', visual_purpose: 'locate', target_refs: ['guide'] };
assert.equal(JSON.stringify(ctx._orderLocateCaptureViews(plan, [{ target: 'viewer-3d' }])),
    JSON.stringify([{ target: 'data-tree' }, { target: 'viewer-3d' }]));
assert.equal(ctx._orderLocateCaptureViews({ ...plan, mode: 'report' }, [{ target: 'viewer-3d' }]).length, 1);
assert.equal(ctx._orderLocateCaptureViews(plan, [{ target: 'data-tree' }]).length, 1);
vm.runInContext(extract('brachybot-chat-todo.js', '_visualResponseNeedsGroundedFallback'), ctx);
assert.equal(ctx._visualResponseNeedsGroundedFallback('The brown mesh is the guide.', [
    { visual_purpose: 'locate' },
]), true);
assert.equal(ctx._visualResponseNeedsGroundedFallback('The brown mesh is the guide.', [
    { view_metadata: { grounding_manifest: { targets: [{ visible: false }] } } },
]), true);
console.log('PASS: reveal/restore, parent scope, sibling isolation, capture order, report isolation, prose guard');

// Exercise the actual async orchestrator, including upload failure cleanup.
let failUpload = false;
let captures = [];
let activeSession = 'session-a';
let switchDuringCapture = false;
let uploads = 0;
Object.assign(ctx, {
    window: {}, console, document: { body: {} }, API: '/api',
    _activeApiSessionId: () => activeSession,
    _normalizeStructuredScreenshotPlan: (target, question, options) => options.plan,
    _snapshotScreenshotViewerState: () => ({}),
    _prepareScreenshotTarget: async () => ({}),
    _applyStructuredScreenshotPlan: async () => ({ restoreFocus: () => {} }),
    _waitScreenshotFrames: async () => {},
    _captureScreenshotEvidenceBundle: async target => {
        captures.push([target, guide.visible]);
        if (switchDuringCapture && target === 'viewer-3d') activeSession = 'session-b';
        return { dataUrl: 'data:image/png;base64,fixture', groundingManifest: { targets: [] } };
    },
    _validateScreenshotDataUrl: async () => true,
    _localizedScreenshotTargetLabel: target => target,
    _localizedScreenshotText: (title, fallback) => title || fallback,
    fetch: async () => {
        uploads++;
        if (failUpload && captures.length === 2) throw new Error('upload failed');
        return { ok: true, text: async () => JSON.stringify({ url: '/shot.png' }) };
    },
    _annotateRequiredScreenshotBeforeDisplay: async attachment => {
        if (attachment.target === 'viewer-3d') assert.equal(guide.visible, true);
        return attachment;
    },
    _appendScreenshotToGallery: (url, target, question, context, attachment) => ({ ...attachment, url }),
    _restoreScreenshotViewerState: async () => {},
    _screenshotFailureMessage: () => 'capture failed',
});
vm.runInContext(extract('brachybot-ui-api.js', '_interceptScreenshot'), ctx);
(async () => {
    for (const fail of [false, true]) {
        failUpload = fail;
        captures = [];
        const result = await ctx._interceptScreenshot('viewer-3d', 'locate', {}, {
            sessionId: 'session-a',
            plan: { ...plan, annotation_policy: 'required', views: [{ target: 'viewer-3d' }] },
        });
        assert.equal(JSON.stringify(captures), JSON.stringify([['data-tree', false], ['viewer-3d', true]]));
        assert.equal(JSON.stringify([guide, parent, sibling]), before);
        assert.equal(result.success, !fail);
    }
    console.log('PASS: async capture captures hidden row first, reveals before viewer/annotation, restores on success and failure');
    failUpload = false;
    switchDuringCapture = true;
    captures = [];
    uploads = 0;
    const result = await ctx._interceptScreenshot('viewer-3d', 'locate', {}, {
        sessionId: 'session-a',
        plan: { ...plan, annotation_policy: 'required', views: [{ target: 'viewer-3d' }] },
    });
    assert.equal(result.stale, true);
    assert.equal(uploads, 1, 'do not upload a viewer image after case switch');
    assert.equal(JSON.stringify([guide, parent, sibling]), before);
    const count = refreshed;
    const restoreOldCase = ctx._revealScreenshotNodes({ target_refs: ['guide'] }, () => false);
    assert.equal(refreshed, count + 1);
    restoreOldCase();
    assert.equal(refreshed, count + 1, 'restoring old node objects must not redraw the new case');
    console.log('PASS: session switch cancels image delivery and avoids cross-case redraw');
})().catch(error => { console.error(error); process.exitCode = 1; });
