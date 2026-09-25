const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(process.argv[2], 'utf8');
const begin = source.indexOf('function _monitorControlIntent(');
const end = source.indexOf('\n// Tool providers', begin);
assert(begin >= 0 && end > begin, 'monitor intent resolver must exist');
const context = {};
vm.createContext(context);
vm.runInContext(source.slice(begin, end) + '\nthis.resolve = _monitorControlIntent;', context);

for (const [utterance, expected] of [
    ['退出监测', 'stop'],
    ['请退出检测模式', 'stop'],
    ['停止本次监测', 'stop'],
    ['别再监测了', 'stop'],
    ['Please stop monitoring', 'stop'],
    ['finish monitor', 'stop'],
    ['开始监测', 'start'],
    ['请开启监测模式', 'start'],
    ['start monitoring', 'start'],
    ['怎么退出监测', null],
    ['你能退出监测吗？', null],
    ['不要退出监测', null],
    ['他说“退出监测”', null],
    ['退出监测后生成报告', null],
    ['监测建议如何改进', null],
    ['教我规划', null],
    ['开始监测并重新规划', null],
]) {
    assert.equal(context.resolve(utterance), expected, utterance);
}
console.log('Monitor command/mention/negation routing passed.');
