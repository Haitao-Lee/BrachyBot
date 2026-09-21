const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert');
const path = require('node:path');

const source = fs.readFileSync(
    process.argv[2] || path.resolve(__dirname, '../web/app/static/js/brachybot-viewer-volume.js'),
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

const ctx = vm.createContext({
    window: {
        _normalizeTrajectoryId: tid => {
            if (tid === null || tid === undefined || tid === '') return 'unassigned';
            if (typeof tid === 'number' && Number.isFinite(tid)) return `traj_${tid + 1}`;
            const value = String(tid);
            return /^\d+$/.test(value) ? `traj_${Number(value) + 1}` : value;
        },
    },
});
vm.runInContext(extractFunction('_trajectoryContains'), ctx);
const contains = (item, trajectory) => vm.runInContext('_trajectoryContains', ctx)(item, trajectory);

// The server builds algorithm plans with id = `traj_{index + 1}` (1-based) and
// index = i (0-based), and names each seed `seed_{i+1}_{j+1}`. A trajectory
// must only claim its own seeds: the old fuzzy matcher folded the previous
// trajectory's seeds into the current one, so the Data Tree showed extra
// duplicated `Seed 1, Seed 2, ...` rows the 3D Viewer never rendered.
for (const index of [0, 1, 21, 22, 23, 263]) {
    const trajectory = { id: `traj_${index + 1}`, index };
    assert.equal(contains({ trajectory_id: `traj_${index + 1}` }, trajectory), true,
        `traj_${index + 1} owns its seeds`);
    assert.equal(contains({ trajectory_id: `traj_${index}` }, trajectory), false,
        `traj_${index + 1} must not absorb traj_${index}`);
    assert.equal(contains({ trajectory_id: `traj_${index + 2}` }, trajectory), false,
        `traj_${index + 1} must not absorb traj_${index + 2}`);
}

// Legacy zero-based numeric seed ids keep resolving through the shared helper.
assert.equal(contains({ trajectory_id: 22 }, { id: 'traj_23', index: 22 }), true);
assert.equal(contains({ trajectory_id: 21 }, { id: 'traj_23', index: 22 }), false);

// Manual planning uses opaque ids and must group exactly.
assert.equal(contains({ trajectory_id: 'manual_traj_2' }, { id: 'manual_traj_2', index: 1 }), true);
assert.equal(contains({ trajectory_id: 'manual_traj_1' }, { id: 'manual_traj_2', index: 1 }), false);

// A missing owner never matches.
assert.equal(contains({}, { id: 'traj_1', index: 0 }), false);

console.log('PASS: trajectory seed grouping resolves one canonical identity, no adjacent-trajectory bleed.');
