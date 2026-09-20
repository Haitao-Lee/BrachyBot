// Regression coverage for target-aware screenshot deduplication and gallery layout.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = process.argv[2] || path.join(__dirname, '..', 'web', 'app', 'static', 'js');

function extract(file, name) {
    const source = fs.readFileSync(path.join(root, file), 'utf8');
    const marker = 'function ' + name + '(';
    const start = source.indexOf(marker);
    assert(start >= 0, name);
    const nextFunction = source.indexOf('\nfunction ', start + marker.length);
    const nextAsyncFunction = source.indexOf('\nasync function ', start + marker.length);
    const ends = [nextFunction, nextAsyncFunction].filter(index => index >= 0);
    return source.slice(start, ends.length ? Math.min(...ends) : source.length);
}

const rendered = [];
const saved = [];
const shell = { attachments: {}, sessionId: 'session-a' };
const context = {
    window: {
        ensureAssistantReplyContainer: () => shell,
        renderAssistantAttachments: (_shell, attachments, layout) => {
            rendered.push({ ids: attachments.map(item => item.id), layout });
        },
        chatAttachmentTargetIdentity: null,
        chatAttachmentSemanticKey: null,
    },
    _localizedScreenshotTargetLabel: target => String(target),
    _activeApiSessionId: () => 'session-a',
    saveSessionMessage: (...args) => saved.push(args),
    scrollToBottom: () => {},
    Date,
};
vm.createContext(context);

for (const name of [
    '_screenshotTargetRefs',
    '_screenshotPlanIdentity',
]) {
    vm.runInContext(extract('brachybot-ui-api.js', name), context);
}
for (const name of [
    '_cloneChatValue',
    'normalizeChatAttachment',
    'chatAttachmentTargetIdentity',
    'chatAttachmentSemanticKey',
    'normalizeChatAttachments',
]) {
    vm.runInContext(extract('brachybot-chat-core.js', name), context);
}
context.window.chatAttachmentTargetIdentity = context.chatAttachmentTargetIdentity;
context.window.chatAttachmentSemanticKey = context.chatAttachmentSemanticKey;
vm.runInContext(extract('brachybot-ui-api.js', '_appendScreenshotToGallery'), context);

const plan = (ref, semantic) => ({
    target_refs: [ref],
    semantic_target: semantic,
    semantic_targets: [semantic],
    views: [{ target: 'viewer-3d' }],
});
const guidePlan = plan('surgical_guide:active', 'surgical_guide');
const tumorPlan = plan('structure:ctv:active', 'ctv');
assert.notEqual(
    context._screenshotPlanIdentity(guidePlan),
    context._screenshotPlanIdentity(tumorPlan),
    'distinct object references must generate distinct durable capture identities',
);
assert.equal(
    context._screenshotPlanIdentity({ ...guidePlan, target_refs: [...guidePlan.target_refs].reverse() }),
    context._screenshotPlanIdentity(guidePlan),
    'target reference ordering must not perturb the capture identity',
);

const makeAttachment = (id, url, ref, semantic) => ({
    id,
    url,
    target: 'viewer-3d',
    mode: 'chat',
    request_id: 'request-a',
    planning_id: 'planning-a',
    visual_purpose: 'locate',
    view_metadata: {
        index: 0,
        target: 'viewer-3d',
        visual_purpose: 'locate',
        target_refs: [ref],
        semantic_target: semantic,
        semantic_targets: [semantic],
    },
});
const guide = makeAttachment('capture-guide', '/guide.png', 'surgical_guide:active', 'surgical_guide');
const tumor = makeAttachment('capture-tumor', '/tumor.png', 'structure:ctv:active', 'ctv');
const guideKey = context.chatAttachmentSemanticKey(guide);
const tumorKey = context.chatAttachmentSemanticKey(tumor);
assert.ok(guideKey && tumorKey);
assert.notEqual(guideKey, tumorKey, 'same-view captures for different targets must not collide');
assert.equal(
    context.chatAttachmentSemanticKey({ ...guide, id: 'replay-id', url: '/guide-replayed.png' }),
    guideKey,
    'a replay with fresh transport IDs remains semantically deduplicable',
);

assert.equal(context.normalizeChatAttachments('session-a', [guide, tumor]).length, 2);
assert.equal(
    context.normalizeChatAttachments('session-a', [
        guide,
        { ...guide, id: 'replay-id', url: '/guide-replayed.png' },
        tumor,
    ]).length,
    2,
    'Session hydration must retain each target while folding a replay of the same target',
);

const gallery = {
    sessionId: 'session-a',
    requestId: 'request-a',
    messageId: 'assistant-a',
    responseLanguage: 'zh',
    mode: 'chat',
    layout: 'auto',
    items: [],
    keys: new Set(),
    urlKeys: new Set(),
    semanticKeys: new Set(),
};
assert.ok(context._appendScreenshotToGallery('/guide.png', 'viewer-3d', '', gallery, guide));
assert.ok(context._appendScreenshotToGallery('/tumor.png', 'viewer-3d', '', gallery, tumor));
assert.equal(gallery.items.length, 2, 'independent locate targets must both be attached');
assert.equal(gallery.layout, 'side-by-side', 'multi-target location evidence should use parallel layout');
assert.equal(gallery._multiLocateSideBySide, true, 'the aggregate layout must survive subsequent captures');
assert.equal(rendered.length, 2);
assert.deepEqual(rendered.map(item => item.layout), ['auto', 'side-by-side']);
assert.equal(saved.length, 2);
assert.equal(
    context._appendScreenshotToGallery(
        '/guide-replayed.png',
        'viewer-3d',
        '',
        gallery,
        { ...guide, id: 'capture-guide-replay' },
    ),
    null,
    'the same target replay should not create a third tile',
);
assert.equal(gallery.items.length, 2);

const ungroundedLocate = makeAttachment('capture-unknown', '/unknown.png', '', '');
delete ungroundedLocate.view_metadata.target_refs;
delete ungroundedLocate.view_metadata.semantic_target;
delete ungroundedLocate.view_metadata.semantic_targets;
ungroundedLocate.view_metadata.target_query = 'where are the guide and tumor';
ungroundedLocate.question = 'where are the guide and tumor';
assert.equal(
    context.chatAttachmentSemanticKey(ungroundedLocate),
    '',
    'un-grounded locate screenshots must not be collapsed by a guessed semantic identity',
);
console.log('chat attachment identity regression tests passed');
