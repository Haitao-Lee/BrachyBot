const fs = require('node:fs');
const vm = require('node:vm');
// Non-strict: the functions run in a vm realm, so their objects have a
// different Object.prototype and deepStrictEqual would reject equal shapes.
const assert = require('node:assert');
const path = require('node:path');

const source = fs.readFileSync(
    process.argv[2] || path.resolve(__dirname, '../web/app/static/js/brachybot-workspace.js'),
    'utf8',
);

function extractFunction(name) {
    const start = source.indexOf(`function ${name}(`);
    assert(start >= 0, `missing ${name}`);
    let depth = 0;
    let opened = false;
    for (let index = start; index < source.length; index += 1) {
        const char = source[index];
        if (char === '{') {
            depth += 1;
            opened = true;
        } else if (char === '}') {
            depth -= 1;
            if (opened && depth === 0) return source.slice(start, index + 1);
        }
    }
    throw new Error(`unterminated ${name}`);
}

const ctx = vm.createContext({ window: {} });
vm.runInContext(
    `${extractFunction('mergePresentationNode')}\n${extractFunction('workspacePresentationTree')}`,
    ctx,
);

const base = {
    structurePaletteVersion: 2,
    ct: { id: 'ct', color: '#888', opacity: 1 },
    organs: [
        { id: 'oar_a', color: '#f00', opacity: 0.4 },
        { id: 'oar_b', color: '#0f0', opacity: 0.5 },
        { id: 'oar_c', color: '#00f', opacity: 0.6 },
    ],
    ctvLabels: { ctv_1: { color: '#fff', opacity: 0.9 } },
};
const override = {
    ct: { id: 'ct', color: '#111', opacity: 0.2 },
    organs: [{ id: 'oar_a', opacity: 0.75 }],
};

const merged = ctx.workspacePresentationTree({
    ui: { state: { data_tree: override } },
    agent: { ui_state: { data_tree: base } },
});

// Override wins per field, but the Agent copy fills every node the browser
// projection omitted. This is what restores dormant-case label colours.
assert.equal(merged.ct.color, '#111');
assert.equal(merged.ct.opacity, 0.2);
assert.equal(merged.ct.id, 'ct');
const byId = Object.fromEntries(merged.organs.map(item => [item.id, item]));
assert.equal(Object.keys(byId).length, 3, 'agent-only OAR rows are retained');
assert.equal(byId.oar_a.opacity, 0.75, 'browser override wins for shared rows');
assert.equal(byId.oar_a.color, '#f00', 'missing fields fall back to the agent copy');
assert.equal(byId.oar_b.color, '#0f0');
assert.equal(byId.oar_c.opacity, 0.6);
assert.equal(merged.ctvLabels.ctv_1.opacity, 0.9);

// A bare tree passed by callers must pass through unchanged.
const bare = { organs: [{ id: 'x', color: '#abc' }] };
assert.deepEqual(ctx.workspacePresentationTree(bare), bare);

// A browser-only snapshot is unchanged when the Agent has no tree.
const browserOnly = { ui: { state: { data_tree: override } } };
assert.deepEqual(
    ctx.workspacePresentationTree(browserOnly),
    override,
);

console.log('PASS: presentation tree merges agent colours/opacity with the browser projection.');
