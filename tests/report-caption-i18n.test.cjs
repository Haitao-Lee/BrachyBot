const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const source = fs.readFileSync(process.argv[2], 'utf8');
const start = source.indexOf('window.reportFigureDisplayText = function reportFigureDisplayText(');
assert(start >= 0, 'reportFigureDisplayText must remain available');
const end = source.indexOf('\n    };', start);
assert(end >= 0, 'reportFigureDisplayText function must terminate');

const context = vm.createContext({
    window: {
        describeReportFigure(figure, language) {
            if (figure?.axis !== 'report_fig1_closeup') return null;
            const zh = String(language).startsWith('zh');
            return {
                title: zh ? 'CTV 粒子分布局部图' : 'CTV seed-distribution close-up',
                caption: zh
                    ? '靶区局部视图；CTV 以半透明方式显示，便于观察粒子分布和针道。'
                    : 'Target close-up with the CTV made translucent to show seed distribution and needle paths.',
            };
        },
    },
});
vm.runInContext(source.slice(start, end + '\n    };'.length), context);

const legacyCapturedFigure = {
    axis: 'report_fig1_closeup',
    title: 'Translucent tumor (seed distribution)',
    caption: 'Target close-up showing seeds and their needle paths inside the translucent CTV.',
};
const chinese = context.window.reportFigureDisplayText(legacyCapturedFigure, 'zh');
assert.equal(chinese.title, 'CTV 粒子分布局部图');
assert.match(chinese.caption, /半透明/);

const english = context.window.reportFigureDisplayText(legacyCapturedFigure, 'en');
assert.equal(english.title, 'CTV seed-distribution close-up');
assert.match(english.caption, /Target close-up/);

const supplementalFigure = {title: 'My uploaded image', caption: 'User-authored caption'};
assert.deepEqual(
    JSON.parse(JSON.stringify(context.window.reportFigureDisplayText(supplementalFigure, 'zh'))),
    {title: 'My uploaded image', caption: 'User-authored caption'},
);

console.log('PASS: legacy standard report captions follow active language; supplemental captions are preserved');
