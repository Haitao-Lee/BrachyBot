const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const path = require('node:path');
const productionSource = path.join(__dirname, '..', 'web', 'app', 'static', 'js', 'brachybot-report-editor.js');
const source = fs.readFileSync(
    fs.existsSync(productionSource) ? productionSource : path.join(__dirname, 'brachybot-report-editor.js'),
    'utf8',
);
const start = source.indexOf('renderReport3DFrame = function (focusBox, cameraMargin, readFrame) {');
const end = source.indexOf('\n            };', start) + '\n            };'.length;
assert(start > 0 && end > start, 'report renderer helper is present');

const canvas = {width: 320, height: 240};
const renderer = {
    domElement: canvas, size: {x: 320, y: 240}, ratio: 2,
    viewport: {x: 0, y: 0, z: 320, w: 240},
    scissor: {x: 0, y: 0, z: 320, w: 240},
    scissorTest: true, target: null,
    getSize() { return {...this.size}; },
    getPixelRatio() { return this.ratio; },
    getViewport() { return {...this.viewport}; },
    getScissor() { return {...this.scissor}; },
    getScissorTest() { return this.scissorTest; },
    getRenderTarget() { return this.target; },
    setPixelRatio(value) { this.ratio = value; },
    setSize(x, y) { this.size = {x, y}; canvas.width = x; canvas.height = y; },
    setViewport(...args) { this.viewport = args.length === 1 ? args[0] : {x:args[0],y:args[1],z:args[2],w:args[3]}; },
    setScissor(...args) { this.scissor = args.length === 1 ? args[0] : {x:args[0],y:args[1],z:args[2],w:args[3]}; },
    setScissorTest(value) { this.scissorTest = value; },
    setRenderTarget(value) { this.target = value; },
    getContext() { return {RGBA: 1, UNSIGNED_BYTE: 2, readPixels(_x, _y, _w, _h, _r, _t, sample) { sample[0] = 120; }}; },
};
const camera = {
    aspect: 320 / 240,
    position: {clone() {return {sub() {return {normalize() {return {x:0,y:1,z:0};}};}};}},
    updateProjectionMatrix() {}, updateMatrixWorld() {},
};
let renders = 0;
let fits = 0;
const scene3D = {
    renderer, camera, controls: {target: {}},
    scene: {updateMatrixWorld() {}},
    depthPeeling: {render() {renders++;}},
    requestRender() {},
};
const sandbox = {
    THREE: {Vector2: function() {}, Vector4: function() {}},
    scene3D, renderReport3DFrame: null,
    _frameReportCamera(_box, options) {
        fits++;
        assert.equal(options.targetAspect, 4 / 3);
        assert.equal(options.margin, 1.10);
        return true;
    },
};
vm.createContext(sandbox);
vm.runInContext(source.slice(start, end), sandbox);
const focus = {isEmpty: () => false};
const image = sandbox.renderReport3DFrame(focus, 1.10, captureCanvas => {
    assert.equal(captureCanvas.width, 1280);
    assert.equal(captureCanvas.height, 960);
    assert.equal(camera.aspect, 4 / 3);
    return 'captured';
});
assert.equal(image, 'captured');
assert.equal(renders, 1);
assert.equal(fits, 1);
assert.deepEqual(renderer.size, {x:320,y:240});
assert.equal(renderer.ratio, 2);
assert.equal(renderer.scissorTest, true);
assert.equal(camera.aspect, 320 / 240);
assert.throws(() => sandbox.renderReport3DFrame(focus, 1.10, () => {
    throw Error('readback failed');
}), /readback failed/);
assert.deepEqual(renderer.size, {x:320,y:240});
assert.equal(renderer.ratio, 2);
assert.equal(camera.aspect, 320 / 240);
console.log('PASS: report capture uses a fixed buffer and restores live renderer state after success and failure');
