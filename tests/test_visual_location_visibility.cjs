// Run with node against the local staging files or the repository JS folder.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = process.argv[2] || path.join(__dirname, '..', 'web', 'app', 'static', 'js');
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
vm.runInContext(extract('brachybot-chat-todo.js', '_visualTurnRequiresExplanation'), ctx);
vm.runInContext(extract('brachybot-chat-todo.js', '_visualEvidenceDescriptor'), ctx);
assert.equal(ctx._visualTurnRequiresExplanation({ text_required: true, act: 'question' }), true);
assert.equal(ctx._visualTurnRequiresExplanation({ text_required: true, act: 'mixed' }), true);
assert.equal(ctx._visualTurnRequiresExplanation({
    text_required: true, act: 'command', evidence_supplemental: false,
}), false);
assert.equal(ctx._visualTurnRequiresExplanation(null), false);
const optedOutScreenshot = { url: '/shot.png', target: 'viewer-3d', analysis_required: false };
assert.equal(ctx._visualEvidenceDescriptor(optedOutScreenshot), null);
const forcedEvidence = ctx._visualEvidenceDescriptor(optedOutScreenshot, 0, false, true);
assert.equal(forcedEvidence.analysis_required, true);
assert.equal(forcedEvidence.url, '/shot.png');
for (const name of ['_revealScreenshotNodes', '_screenshotNeeds3DReframe', '_orderLocateCaptureViews', '_screenshotPlanIdentity']) {
    vm.runInContext(extract('brachybot-ui-api.js', name), ctx);
}
vm.runInContext(extract('brachybot-ui-api.js', '_hideGuideOccludingCtvCapture'), ctx);
const occludingGuide = { id: 'guide-mesh', source: 'surgical_guide', visible: true, opacity: .37 };
const untouchedMesh = { id: 'other-mesh', source: 'planning', visible: true, visible3D: true };
ctx.dataTreeState = { planning: { meshes: [occludingGuide, untouchedMesh] } };
ctx.window = { get3DScreenshotGroundingManifest: refs => ({ targets: refs.map(ref => ({
    target_ref: ref,
    normalized_bounds: ref === 'surgical_guide:active'
        ? [0.2, 0.2, 0.45, 0.45] : [0.3, 0.3, 0.2, 0.2],
})) }) };
const originalGuideState = JSON.stringify(occludingGuide);
const restoreCtvCapture = ctx._hideGuideOccludingCtvCapture({
    target_refs: ['structure:ctv:active'],
});
assert.equal(occludingGuide.visible3D, false, 'guide is hidden only in the CTV capture');
assert.equal(occludingGuide.opacity, .37, 'guide appearance is not changed');
assert.equal(untouchedMesh.visible3D, true);
assert.deepEqual([...restoreCtvCapture.occluders], ['surgical_guide:active']);
restoreCtvCapture();
assert.equal(JSON.stringify(occludingGuide), originalGuideState, 'guide visibility is exactly restored');
assert.equal(ctx._hideGuideOccludingCtvCapture({ target_refs: ['surgical_guide:active'] }), null);
ctx.window.get3DScreenshotGroundingManifest = refs => ({ targets: refs.map(ref => ({
    target_ref: ref,
    normalized_bounds: ref === 'surgical_guide:active'
        ? [0.7, 0.7, 0.2, 0.2] : [0.1, 0.1, 0.2, 0.2],
})) });
assert.equal(ctx._hideGuideOccludingCtvCapture({ target_refs: ['structure:ctv:active'] }), null,
    'a guide elsewhere in the current camera should retain its visibility');
ctx.window.get3DScreenshotGroundingManifest = refs => ({ targets: refs.map(ref => ({
    target_ref: ref,
    normalized_bounds: ref === 'surgical_guide:active'
        ? [0.2, 0.2, 0.45, 0.45] : [0.3, 0.3, 0.2, 0.2],
})) });
const refreshVisibility = ctx.applyDataTreeViewVisibility;
ctx.applyDataTreeViewVisibility = () => { throw new Error('render failed'); };
assert.throws(() => ctx._hideGuideOccludingCtvCapture({
    target_refs: ['structure:ctv:active'],
}), /render failed/);
assert.equal(JSON.stringify(occludingGuide), originalGuideState,
    'an early Viewer refresh error must restore guide visibility');
ctx.applyDataTreeViewVisibility = refreshVisibility;
refreshed = 0;
const before = JSON.stringify([guide, parent, sibling]);
const restore = ctx._revealScreenshotNodes({ target_refs: ['guide'] });
assert.equal(guide.visible, true);
assert.equal(guide.visible3D, true);
assert.equal(guide.opacity, 0, 'revealing a node must not silently make it opaque');
assert.equal(parent.visible, true);
assert.equal(sibling.visible, false);
restore();
assert.equal(JSON.stringify([guide, parent, sibling]), before);
assert.equal(refreshed, 2);
const visibleState = JSON.stringify([guide, parent, sibling]);
const refreshCountBeforeVisible = refreshed;
Object.assign(guide, { visible: true, visible3D: true, opacity: .42 });
Object.assign(parent, { visible: true, visible3D: true });
const alreadyVisibleState = JSON.stringify([guide, parent, sibling]);
const noOpRestore = ctx._revealScreenshotNodes({ target_refs: ['guide'] });
assert.equal(noOpRestore.changed, false);
assert.equal(refreshed, refreshCountBeforeVisible, 'visible targets do not trigger redundant tree refreshes');
assert.equal(JSON.stringify([guide, parent, sibling]), alreadyVisibleState);
noOpRestore();
assert.equal(JSON.stringify([guide, parent, sibling]), alreadyVisibleState);
Object.assign(guide, { visible: false, visible3D: false, opacity: 0 });
Object.assign(parent, { visible: false, visible3D: false });
assert.equal(JSON.stringify([guide, parent, sibling]), before);
const plan = { mode: 'chat', visual_purpose: 'locate', target_refs: ['guide'] };
assert.equal(JSON.stringify(ctx._orderLocateCaptureViews(plan, [{ target: 'viewer-3d' }])),
    JSON.stringify([{ target: 'data-tree' }, { target: 'viewer-3d' }]));
assert.equal(ctx._orderLocateCaptureViews({ ...plan, mode: 'report' }, [{ target: 'viewer-3d' }]).length, 1);
assert.equal(ctx._orderLocateCaptureViews(plan, [{ target: 'data-tree' }]).length, 1);
vm.runInContext(extract('brachybot-chat-todo.js', '_visualResponseNeedsGroundedFallback'), ctx);
vm.runInContext(extract('brachybot-chat-todo.js', '_visualEvidenceFallbackResponse'), ctx);
assert.equal(ctx._visualResponseNeedsGroundedFallback('The brown mesh is the guide.', [
    { visual_purpose: 'locate' },
]), true);
assert.equal(ctx._visualResponseNeedsGroundedFallback('The brown mesh is the guide.', [
    { view_metadata: { grounding_manifest: { targets: [{ visible: false }] } } },
]), true);

const treeOnlyAttachment = {
    url: '/tree.png', target: 'data-tree', visual_purpose: 'locate',
    view_metadata: { grounding_manifest: { targets: [{
        target_ref: 'guide', label: 'Puncture guide v2', kind: 'data-tree-row',
        visible: true, in_view: true, annotatable: true,
        scene_visible: false, scene_visibility_known: true,
    }] } },
};
const treeFallback = ctx._visualEvidenceFallbackResponse(
    [treeOnlyAttachment], 'session-a', 'zh', 'locate',
    'Planning_2 completed; Code help is available.',
);
assert.match(treeFallback, /Planning_2 completed/);
assert.match(treeFallback, /Code help is available/);
assert.match(treeFallback, /Data Tree.*Puncture guide v2/);
assert.match(treeFallback, /3D Viewer.*\u672c\u8f6e\u6ca1\u6709\u53d6\u5f97/);
assert.match(treeFallback, /\u9690\u85cf\u72b6\u6001/);
const unknownTreeFallback = ctx._visualEvidenceFallbackResponse([{
    ...treeOnlyAttachment,
    view_metadata: { grounding_manifest: { targets: [{
        ...treeOnlyAttachment.view_metadata.grounding_manifest.targets[0],
        scene_visibility_known: false,
    }] } },
}], 'session-a', 'zh', 'locate');
assert.doesNotMatch(unknownTreeFallback, /\u9690\u85cf\u72b6\u6001/);
assert.match(unknownTreeFallback, /\u65e0\u6cd5\u6838\u9a8c.*\u4e09\u7ef4\u663e\u793a\u72b6\u6001/);
const staleVisualPrelude = [
    '**对象截图/位置**',
    '没有建立与该目标对应的截图任务，因此不对位置作判断。',
    '**对象截图/位置**',
    '没有建立与该目标对应的截图任务，因此不对位置作判断。',
    'Planning_2 is completed.',
].join('\n\n');
const targetManifest = (kind, extra = {}) => ({
    target_ref: 'guide',
    label: 'Puncture guide v2',
    kind,
    visible: true,
    in_view: true,
    annotatable: true,
    scene_visible: true,
    data_tree_visible: true,
    loaded: true,
    status: 'ready',
    ...extra,
});
const visibleGuideAnswer = ctx._visualEvidenceFallbackResponse([
    {
        url: '/tree.png', target: 'data-tree', visual_purpose: 'locate',
        view_metadata: { visual_purpose: 'locate', grounding_manifest: {
            targets: [targetManifest('data-tree-row')],
        } },
    },
    {
        url: '/viewer.png', target: 'viewer-3d', visual_purpose: 'locate',
        annotation: { marks: [{ target_ref: 'guide' }] },
        view_metadata: {
            visual_purpose: 'locate',
            appearance_preserved: true,
            grounding_manifest: { targets: [targetManifest('scene-object')] },
        },
    },
], 'session-a', 'zh', '导板在哪里？', staleVisualPrelude);
assert.equal((visibleGuideAnswer.match(/对象截图\/位置/g) || []).length, 0);
assert.doesNotMatch(visibleGuideAnswer, /没有建立与该目标对应的截图任务/);
assert.match(visibleGuideAnswer, /Planning_2 is completed/);
assert.doesNotMatch(visibleGuideAnswer, /截图沿用了 Viewer 当时的显示内容和配色/);
assert.match(visibleGuideAnswer, /对应截图已核验/);
assert.match(visibleGuideAnswer, /\*\*Puncture guide v2\*\*/);
assert.doesNotMatch(visibleGuideAnswer, /### /);
const contradictedGuideAnswer = ctx._visualEvidenceFallbackResponse([
    {
        url: '/guide.png', target: 'viewer-3d', visual_purpose: 'locate',
        annotation: { marks: [{ target_ref: 'guide' }] },
        view_metadata: { grounding_manifest: { targets: [targetManifest('scene-object')] } },
    },
], 'session-a', 'zh', '导板在哪里？',
'我提交了截图计划，但浏览器端没有把图像回传给我。请重新截图。Planning_2 已完成。');
assert.doesNotMatch(contradictedGuideAnswer, /没有把图像回传|重新截图/);
assert.match(contradictedGuideAnswer, /Planning_2 已完成/);

const ctvBehindGuide = ctx._visualEvidenceFallbackResponse([{
    url: '/ctv-viewer.png', target: 'viewer-3d', visual_purpose: 'locate',
    annotation: { marks: [{ target_ref: 'structure:ctv:active' }] },
    view_metadata: {
        temporary_occluders: ['surgical_guide:active'],
        grounding_manifest: { targets: [{
            ...targetManifest('scene-object'), target_ref: 'structure:ctv:active',
            label: 'Label 2',
        }] },
    },
}], 'session-a', 'zh', '肿瘤在哪里');
assert.match(ctvBehindGuide, /\*\*Label 2\*\*/);
assert.match(ctvBehindGuide, /临时隐藏导板/);
const combinedAnswer = ctx._visualEvidenceFallbackResponse([
    { url: '/guide-tree.png', target: 'data-tree', visual_purpose: 'locate',
        view_metadata: { grounding_manifest: { targets: [targetManifest('data-tree-row')] } } },
    { url: '/guide-viewer.png', target: 'viewer-3d', visual_purpose: 'locate',
        annotation: { marks: [{ target_ref: 'guide' }] },
        view_metadata: { grounding_manifest: { targets: [targetManifest('scene-object')] } } },
    { url: '/ctv-tree.png', target: 'data-tree', visual_purpose: 'locate',
        view_metadata: { grounding_manifest: { targets: [{
            ...targetManifest('data-tree-row'), target_ref: 'structure:ctv:active', label: 'Label 2',
        }] } } },
    { url: '/ctv-viewer.png', target: 'viewer-3d', visual_purpose: 'locate',
        annotation: { marks: [{ target_ref: 'structure:ctv:active' }] },
        view_metadata: { temporary_occluders: ['surgical_guide:active'],
            grounding_manifest: { targets: [{ ...targetManifest('scene-object'),
                target_ref: 'structure:ctv:active', label: 'Label 2' }] } } },
], 'session-a', 'zh', '截图告诉我导板在哪里，肿瘤在哪里',
'我提交了截图计划，但浏览器端没有把图像回传给我。');
assert.equal((combinedAnswer.match(/\*\*Puncture guide v2\*\*/g) || []).length, 1);
assert.equal((combinedAnswer.match(/\*\*Label 2\*\*/g) || []).length, 1);
assert.doesNotMatch(combinedAnswer, /没有把图像回传/);
assert.match(combinedAnswer, /临时隐藏导板/);

const temporarilyRevealedGuideAnswer = ctx._visualEvidenceFallbackResponse([
    {
        url: '/tree-hidden.png', target: 'data-tree', visual_purpose: 'locate',
        view_metadata: { visual_purpose: 'locate', grounding_manifest: {
            targets: [targetManifest('data-tree-row', {
                scene_visible: false, scene_visibility_known: true,
            })],
        } },
    },
    {
        url: '/viewer-revealed.png', target: 'viewer-3d', visual_purpose: 'locate',
        annotation: { marks: [{ target_ref: 'guide' }] },
        view_metadata: {
            visual_purpose: 'locate', temporary_reveal: true,
            appearance_preserved: true,
            grounding_manifest: { targets: [targetManifest('scene-object')] },
        },
    },
], 'session-a', 'zh', '导板在哪里？');
assert.match(temporarilyRevealedGuideAnswer, /Data Tree 截图时该对象原处于隐藏状态/);
assert.match(temporarilyRevealedGuideAnswer, /临时显示，完成后已恢复/);
assert.doesNotMatch(temporarilyRevealedGuideAnswer, /沿用了 Viewer 当时的显示内容和配色/);
console.log('PASS: browser fallback keeps compound answers, verifies Data Tree row, filters duplicate visual placeholders, and reports temporary reveal honestly');

console.log('PASS: reveal/restore, parent scope, sibling isolation, capture order, report isolation, prose guard');

// Exercise the actual async orchestrator, including upload failure cleanup.
let failUpload = false;
let invalidViewer = false;
let unresolvedTree = false;
let captures = [];
let activeSession = 'session-a';
let switchDuringCapture = false;
let uploads = 0;
let uploadPayloads = [];
let framingBounds = [0.2, 0.2, 0.4, 0.4];
Object.assign(ctx, {
    window: {
        get3DScreenshotGroundingManifest: () => ({ targets: [{
            target_ref: 'guide',
            visible: guide.visible === true && guide.visible3D === true,
            scene_visible: guide.visible3D === true,
            data_tree_visible: guide.visible === true,
            loaded: true,
            in_view: true,
            normalized_bounds: framingBounds,
        }] }),
    }, console, document: { body: {} }, API: '/api',
    _activeApiSessionId: () => activeSession,
    _normalizeStructuredScreenshotPlan: (target, question, options) => options.plan,
    _snapshotScreenshotViewerState: () => ({}),
    _prepareScreenshotTarget: async () => ({}),
    _applyStructuredScreenshotPlan: async (spec, target) => ({
        restoreFocus: () => {},
        focusResult: target === 'data-tree'
            ? { status: unresolvedTree ? 'unverified' : 'resolved' }
            : {
                status: 'resolved',
                method: spec.focus?.kind === 'current-view' ? 'current-view' : 'test-camera-focus',
                camera_adjusted: spec.focus?.kind === 'auto',
            },
    }),
    _waitScreenshotFrames: async () => {},
    _captureScreenshotEvidenceBundle: async target => {
        captures.push([target, guide.visible]);
        if (switchDuringCapture && target === 'viewer-3d') activeSession = 'session-b';
        const viewerValid = target !== 'viewer-3d' || !invalidViewer;
        return {
            dataUrl: 'data:image/png;base64,fixture',
            groundingManifest: { targets: [{
                target_ref: 'guide',
                label: 'Puncture guide v2',
                kind: target === 'data-tree' ? 'data-tree-row' : 'scene-object',
                visible: true,
                loaded: true,
                status: 'ready',
                scene_visible: target === 'viewer-3d' ? (viewerValid && guide.visible3D) : false,
                scene_visibility_known: true,
                data_tree_visible: true,
                in_view: true,
                annotatable: viewerValid,
                normalized_bounds: [0.2, 0.2, 0.4, 0.4],
            }] },
        };
    },
    _validateScreenshotDataUrl: async () => true,
    _localizedScreenshotTargetLabel: target => target,
    _localizedScreenshotText: (title, fallback) => title || fallback,
    fetch: async (_url, options = {}) => {
        uploads++;
        try { uploadPayloads.push(JSON.parse(options.body || '{}')); } catch (_) {}
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
        uploadPayloads = [];
        const result = await ctx._interceptScreenshot('viewer-3d', 'locate', {}, {
            sessionId: 'session-a',
            plan: { ...plan, annotation_policy: 'required', views: [{ target: 'viewer-3d' }] },
        });
        assert.equal(JSON.stringify(captures), JSON.stringify([['data-tree', false], ['viewer-3d', true]]));
        assert.equal(JSON.stringify([guide, parent, sibling]), before);
        const treeUpload = uploadPayloads.find(item => item.target === 'data-tree');
        const viewerUpload = uploadPayloads.find(item => item.target === 'viewer-3d');
        assert.equal(treeUpload.view_metadata.temporary_reveal, false);
        assert.equal(viewerUpload.view_metadata.temporary_reveal, true);
        assert.equal(viewerUpload.view_metadata.temporary_camera_reframe, false);
        assert.equal(viewerUpload.view_metadata.appearance_preserved, true);
        assert.equal(viewerUpload.view_metadata.preserve_current_view, true);
        assert.equal(result.success, !fail);
    }
    console.log('PASS: async capture captures hidden row first, reveals before viewer/annotation, restores on success and failure');

    // If the target is already visible and adequately framed, preserve the
    // existing camera and scene rather than creating a special yellow close-up.
    failUpload = false;
    Object.assign(guide, { visible: true, visible3D: true, opacity: .42 });
    Object.assign(parent, { visible: true, visible3D: true });
    const liveVisibleState = JSON.stringify([guide, parent, sibling]);
    uploadPayloads = [];
    captures = [];
    const visibleCapture = await ctx._interceptScreenshot('viewer-3d', 'locate', {}, {
        sessionId: 'session-a',
        plan: { ...plan, annotation_policy: 'required', views: [{ target: 'viewer-3d' }] },
    });
    assert.equal(visibleCapture.success, true);
    assert.equal(JSON.stringify([guide, parent, sibling]), liveVisibleState);
    const visibleUpload = uploadPayloads.find(item => item.target === 'viewer-3d');
    assert.equal(visibleUpload.view_metadata.temporary_reveal, false);
    assert.equal(visibleUpload.view_metadata.temporary_camera_reframe, false);
    assert.equal(visibleUpload.view_metadata.preserve_current_view, true);
    assert.equal(visibleUpload.view_metadata.focus_result.method, 'current-view');
    assert.equal(visibleUpload.view_metadata.focus_result.camera_adjusted, false);
    Object.assign(guide, { visible: false, visible3D: false, opacity: 0 });
    Object.assign(parent, { visible: false, visible3D: false });
    assert.equal(JSON.stringify([guide, parent, sibling]), before);

    // A CTV locate turn takes a normal tree screenshot, then removes only a
    // screen-overlapping guide for the 3D image and restores it on both paths.
    const ctvNode = { id: 'ctv', visible: true, visible3D: true };
    const oldRow = ctx._dataTreeRowForTargetRef;
    const oldFind = ctx._findDataTreeNode;
    const oldManifest = ctx.window.get3DScreenshotGroundingManifest;
    const oldCapture = ctx._captureScreenshotEvidenceBundle;
    const oldAnnotate = ctx._annotateRequiredScreenshotBeforeDisplay;
    ctx._dataTreeRowForTargetRef = ref => ref === 'structure:ctv:active'
        ? { dataset: { item: 'ctv' } } : oldRow(ref);
    ctx._findDataTreeNode = id => id === 'ctv' ? ctvNode : oldFind(id);
    ctx.window.get3DScreenshotGroundingManifest = refs => ({ targets: refs.map(ref => ({
        target_ref: ref, visible: true, scene_visible: true, data_tree_visible: true,
        loaded: true, in_view: true,
        normalized_bounds: ref === 'surgical_guide:active'
            ? [0.2, 0.2, 0.45, 0.45] : [0.3, 0.3, 0.2, 0.2],
    })) });
    const capturedGuideVisibility = [];
    ctx._captureScreenshotEvidenceBundle = async target => {
        captures.push([target, ctvNode.visible]);
        if (target === 'viewer-3d') capturedGuideVisibility.push(occludingGuide.visible3D);
        return { dataUrl: 'data:image/png;base64,fixture', groundingManifest: {
            targets: [{ target_ref: 'structure:ctv:active', label: 'Label 2',
                kind: target === 'viewer-3d' ? 'scene-object' : 'data-tree-row',
                visible: true, scene_visible: true, data_tree_visible: true,
                loaded: true, in_view: true, annotatable: true,
                normalized_bounds: [0.3, 0.3, 0.2, 0.2] }],
        } };
    };
    ctx._annotateRequiredScreenshotBeforeDisplay = async attachment => attachment;
    for (const fail of [false, true]) {
        failUpload = fail;
        captures = [];
        uploadPayloads = [];
        const ctvCapture = await ctx._interceptScreenshot('viewer-3d', 'locate', {}, {
            sessionId: 'session-a',
            plan: { mode: 'chat', visual_purpose: 'locate', annotation_policy: 'required',
                semantic_target: 'ctv', target_refs: ['structure:ctv:active'],
                views: [{ target: 'viewer-3d' }] },
        });
        assert.equal(ctvCapture.success, !fail);
        assert.equal(capturedGuideVisibility.at(-1), false);
        assert.equal(JSON.stringify(occludingGuide), originalGuideState);
        assert.equal(ctvNode.visible3D, true);
        if (!fail) {
            const viewerUpload = uploadPayloads.find(item => item.target === 'viewer-3d');
            assert.deepEqual(viewerUpload.view_metadata.temporary_occluders,
                ['surgical_guide:active']);
            assert.equal(viewerUpload.view_metadata.appearance_preserved, false);
        }
    }
    failUpload = false;
    ctx._dataTreeRowForTargetRef = oldRow;
    ctx._findDataTreeNode = oldFind;
    ctx.window.get3DScreenshotGroundingManifest = oldManifest;
    ctx._captureScreenshotEvidenceBundle = oldCapture;
    ctx._annotateRequiredScreenshotBeforeDisplay = oldAnnotate;
    console.log('PASS: CTV capture hides only overlapping guide and restores it after success or upload failure');

    // Current visible framing is preserved; clipped/tiny framing is the only
    // condition that authorizes a temporary camera change.
    Object.assign(guide, { visible: true, visible3D: true });
    Object.assign(parent, { visible: true, visible3D: true });
    framingBounds = [0.2, 0.2, 0.4, 0.4];
    assert.equal(ctx._screenshotNeeds3DReframe(plan), false);
    framingBounds = [0.01, 0.01, 0.05, 0.05];
    assert.equal(ctx._screenshotNeeds3DReframe(plan), true);
    // A hidden/unloaded sibling must not suppress a precise reframe of the
    // locatable target; a target that is itself hidden still cannot be framed.
    const savedManifest = ctx.window.get3DScreenshotGroundingManifest;
    ctx.window.get3DScreenshotGroundingManifest = () => ({ targets: [
        { target_ref: 'guide', visible: true, scene_visible: true, data_tree_visible: true,
            loaded: true, in_view: true, normalized_bounds: [0.01, 0.01, 0.05, 0.05] },
        { target_ref: 'tumor', visible: false, scene_visible: false, data_tree_visible: false,
            loaded: false, in_view: false, normalized_bounds: null },
    ] });
    assert.equal(ctx._screenshotNeeds3DReframe({ ...plan, target_refs: ['guide', 'tumor'] }), true,
        'a clipped visible target still requests a reframe when a sibling is hidden');
    ctx.window.get3DScreenshotGroundingManifest = () => ({ targets: [
        { target_ref: 'guide', visible: false, scene_visible: false, data_tree_visible: false,
            loaded: true, in_view: false, normalized_bounds: null },
    ] });
    assert.equal(ctx._screenshotNeeds3DReframe(plan), false,
        'a camera move cannot fix a target that is not visible');
    ctx.window.get3DScreenshotGroundingManifest = savedManifest;
    framingBounds = [0.2, 0.2, 0.4, 0.4];
    Object.assign(guide, { visible: false, visible3D: false });
    Object.assign(parent, { visible: false, visible3D: false });

    failUpload = false;
    invalidViewer = true;
    captures = [];
    uploads = 0;
    const ungrounded = await ctx._interceptScreenshot('viewer-3d', 'locate', {}, {
        sessionId: 'session-a',
        plan: { ...plan, annotation_policy: 'required', views: [{ target: 'viewer-3d' }] },
    });
    assert.equal(ungrounded.success, false);
    assert.equal(ungrounded.error, 'target_not_verified_visible_in_viewer');
    assert.deepEqual(Array.from(ungrounded.attachments, item => item.target), ['data-tree']);
    assert.equal(uploads, 1, 'only the independently verified Data Tree evidence is uploaded');
    assert.equal(JSON.stringify([guide, parent, sibling]), before);
    console.log('PASS: unverified Viewer is rejected while the verified Data Tree row is retained');

    invalidViewer = false;
    unresolvedTree = true;
    captures = [];
    uploads = 0;
    const unresolved = await ctx._interceptScreenshot('viewer-3d', 'locate', {}, {
        sessionId: 'session-a',
        plan: { ...plan, annotation_policy: 'required', views: [{ target: 'viewer-3d' }] },
    });
    assert.equal(unresolved.success, false);
    assert.match(unresolved.error, /target_row_not_verified_in_live_data_tree/);
    assert.deepEqual(captures, [], 'do not capture any surface before live target-row verification');
    assert.equal(uploads, 0);
    assert.equal(JSON.stringify([guide, parent, sibling]), before);
    console.log('PASS: unresolved Data Tree focus aborts all capture');

    unresolvedTree = false;
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
