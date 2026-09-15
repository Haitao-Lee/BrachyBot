/* Per-pixel front-to-back depth peeling for intersecting clinical surfaces. */
(function (root) {
    'use strict';
    class BrachyDepthPeeling {
        constructor(renderer) {
            this.renderer = renderer;
            this.supported = renderer.capabilities.isWebGL2
                || !!renderer.extensions.get('WEBGL_depth_texture');
            this.materials = new Map();
            this.targets = [];
            this.hiddenMaterial = new THREE.MeshBasicMaterial({visible: false});
            this.queryBatch = null;
            this.layerEstimate = null;
            this.size = new THREE.Vector2();
            this.uniforms = {
                peelPrevious: {value: null}, peelOpaque: {value: null},
                peelSize: {value: this.size}, peelFirst: {value: true},
            };
            this.quadScene = new THREE.Scene();
            this.quadCamera = new THREE.Camera();
            this.quad = new THREE.Mesh(new THREE.PlaneBufferGeometry(2, 2));
            this.quad.frustumCulled = false;
            this.quadScene.add(this.quad);
            const vertexShader = 'varying vec2 uvScreen; void main(){uvScreen=uv;gl_Position=vec4(position.xy,0.,1.);}';
            this.accumulate = new THREE.ShaderMaterial({
                uniforms: {layer: {value: null}}, vertexShader,
                fragmentShader: 'uniform sampler2D layer; varying vec2 uvScreen; void main(){vec4 c=texture2D(layer,uvScreen);gl_FragColor=vec4(c.rgb*c.a,c.a);}',
                transparent: true, depthTest: false, depthWrite: false,
                blending: THREE.CustomBlending, blendEquation: THREE.AddEquation,
                blendSrc: THREE.OneMinusDstAlphaFactor, blendDst: THREE.OneFactor,
                blendEquationAlpha: THREE.AddEquation,
                blendSrcAlpha: THREE.OneMinusDstAlphaFactor, blendDstAlpha: THREE.OneFactor,
            });
            this.resolve = new THREE.ShaderMaterial({
                uniforms: {opaque: {value: null}, accumulated: {value: null}}, vertexShader,
                fragmentShader: 'uniform sampler2D opaque; uniform sampler2D accumulated; varying vec2 uvScreen; void main(){vec4 a=texture2D(accumulated,uvScreen);vec4 o=texture2D(opaque,uvScreen);gl_FragColor=a+(1.-a.a)*vec4(o.rgb*o.a,o.a);}',
                depthTest: false, depthWrite: false, blending: THREE.NoBlending,
            });
        }
        resize(width, height) {
            if (this.size.x === width && this.size.y === height) return;
            this.targets.forEach(t => { if (t.depthTexture) t.depthTexture.dispose(); t.dispose(); });
            this.size.set(width, height);
            this.targets = Array.from({length: 4}, (_, i) => {
                const target = new THREE.WebGLRenderTarget(width, height, {
                    minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter,
                    format: THREE.RGBAFormat, depthBuffer: i < 3, stencilBuffer: false,
                });
                if (i < 3) target.depthTexture = new THREE.DepthTexture(width, height, THREE.UnsignedIntType);
                return target;
            });
        }
        peeledMaterial(original) {
            let cached = this.materials.get(original);
            if (!cached || cached.version !== original.version) {
                if (cached) cached.material.dispose();
                const material = original.clone();
                const before = original.onBeforeCompile;
                material.onBeforeCompile = (shader, renderer) => {
                    before.call(material, shader, renderer);
                    Object.assign(shader.uniforms, this.uniforms);
                    shader.fragmentShader = 'uniform sampler2D peelPrevious; uniform sampler2D peelOpaque; uniform vec2 peelSize; uniform bool peelFirst;\n'
                        + shader.fragmentShader.replace(/void\s+main\s*\(\s*\)\s*\{/, `void main() {
                            vec2 peelUV=gl_FragCoord.xy/peelSize;
                            float peelZ=gl_FragCoord.z;
                            if(peelZ>=texture2D(peelOpaque,peelUV).r) discard;
                            if(!peelFirst && peelZ<=texture2D(peelPrevious,peelUV).r+0.0000001) discard;
                        `);
                };
                material.customProgramCacheKey = () => 'brachy-peel-v1:' + original.customProgramCacheKey();
                // Disabling blending selects the nearest remaining fragment;
                // keep transparent=true so lighting shaders retain its alpha.
                material.transparent = true;
                material.blending = THREE.NoBlending;
                material.depthWrite = true;
                material.depthTest = true;
                cached = {material, version: original.version};
                this.materials.set(original, cached);
            }
            cached.material.opacity = original.opacity;
            if (original.color) cached.material.color.copy(original.color);
            if (original.emissive) cached.material.emissive.copy(original.emissive);
            cached.material.visible = original.visible;
            return cached.material;
        }
        render(scene, camera, {interactive = false, capture = false} = {}) {
            const renderer = this.renderer;
            if (!this.supported) {
                if (!this.warnedUnsupported) console.warn('[3D transparency] Depth textures unavailable; using standard alpha rendering.');
                this.warnedUnsupported = true;
                renderer.render(scene, camera); return false;
            }
            const objects = [];
            scene.traverseVisible(object => {
                if (object.material) objects.push({object, material: object.material});
            });
            const isTranslucent = material => material.visible && material.transparent && material.opacity > 0 && material.opacity < 0.999;
            if (!objects.some(e => (Array.isArray(e.material) ? e.material : [e.material]).some(isTranslucent))) {
                renderer.render(scene, camera); return true;
            }
            const buffer = renderer.getDrawingBufferSize(new THREE.Vector2());
            scene.updateMatrixWorld(); camera.updateMatrixWorld();
            const fingerprint = JSON.stringify([
                camera.matrixWorld.elements, camera.projectionMatrix.elements,
                objects.map(({object, material}) => [object.id, object.matrixWorld.elements,
                    object.geometry?.id, object.geometry?.attributes?.position?.version,
                    (Array.isArray(material) ? material : [material]).map(m =>
                        [m.id, m.version, m.opacity, m.visible, m.color?.getHex(), m.map?.id])]),
            ]);
            const gl = renderer.getContext();
            // Query results are consumed on a later frame, without a GPU
            // readback stall. An empty peel bounds the depth complexity for
            // this exact camera/geometry/material state.
            if (this.queryBatch && this.queryBatch.queries.every(q => gl.getQueryParameter(q, gl.QUERY_RESULT_AVAILABLE))) {
                const samples = this.queryBatch.queries.map(q => gl.getQueryParameter(q, gl.QUERY_RESULT));
                const empty = samples.findIndex(value => !value);
                this.layerEstimate = {key: this.queryBatch.key, complete: empty >= 0,
                    count: empty >= 0 ? Math.max(1, empty + 1) : Math.min(64, samples.length * 2)};
                this.queryBatch.queries.forEach(q => gl.deleteQuery(q));
                this.queryBatch = null;
            }
            // Keep the peeling target at the drawing-buffer resolution during
            // orbiting as well as at rest. Downscaling this target makes the
            // viewer visibly soft while the pointer is down. Interactive
            // pressure is controlled by the smaller peel budget below; idle
            // and capture can still use the estimated/full layer budget.
            const scale = 1;
            this.resize(Math.max(1, Math.floor(buffer.x * scale)), Math.max(1, Math.floor(buffer.y * scale)));
            const [opaque, ping, pong, accumulated] = this.targets;
            const saved = {target: renderer.getRenderTarget(), color: renderer.getClearColor(new THREE.Color()),
                alpha: renderer.getClearAlpha(), autoClear: renderer.autoClear,
                viewport: renderer.getViewport(new THREE.Vector4()), scissor: renderer.getScissor(new THREE.Vector4()),
                scissorTest: renderer.getScissorTest(), background: scene.background};
            const hidden = this.hiddenMaterial;
            const activeMaterials = new Set();
            const assign = peel => objects.forEach(({object, material}) => {
                const convert = m => {
                    if (!m.visible || m.opacity <= 0) return hidden;
                    if (isTranslucent(m)) { activeMaterials.add(m); return peel ? this.peeledMaterial(m) : hidden; }
                    return peel ? hidden : m;
                };
                object.material = Array.isArray(material) ? material.map(convert) : convert(material);
            });
            try {
                renderer.setScissorTest(false);
                renderer.autoClear = true;
                assign(false);
                renderer.setRenderTarget(opaque);
                renderer.render(scene, camera);
                scene.background = null;
                renderer.setClearColor(0, 0);
                renderer.setRenderTarget(accumulated); renderer.clear();
                assign(true);
                this.uniforms.peelOpaque.value = opaque.depthTexture;
                const estimated = this.layerEstimate?.key === fingerprint ? this.layerEstimate.count : 24;
                const completeEstimate = this.layerEstimate?.key === fingerprint && this.layerEstimate.complete;
                const layers = capture ? (completeEstimate ? estimated : 64) : interactive ? 6 : estimated;
                const batch = renderer.capabilities.isWebGL2 && !interactive && !this.queryBatch
                    ? {key: fingerprint, queries: []} : null;
                if (batch) this.queryBatch = batch;
                let previous = pong;
                for (let layer = 0; layer < layers; layer++) {
                    const current = layer % 2 === 0 ? ping : pong;
                    this.uniforms.peelFirst.value = layer === 0;
                    this.uniforms.peelPrevious.value = previous.depthTexture;
                    renderer.autoClear = true;
                    renderer.setRenderTarget(current);
                    const query = batch ? gl.createQuery() : null;
                    if (query) gl.beginQuery(gl.ANY_SAMPLES_PASSED, query);
                    try { renderer.render(scene, camera); }
                    finally { if (query) { gl.endQuery(gl.ANY_SAMPLES_PASSED); batch.queries.push(query); } }
                    renderer.autoClear = false;
                    renderer.setRenderTarget(accumulated);
                    this.accumulate.uniforms.layer.value = current.texture;
                    this.quad.material = this.accumulate;
                    renderer.render(this.quadScene, this.quadCamera);
                    previous = current;
                }
                if (batch) this.queryBatch = batch;
                renderer.setRenderTarget(saved.target);
                renderer.setViewport(saved.viewport);
                this.resolve.uniforms.opaque.value = opaque.texture;
                this.resolve.uniforms.accumulated.value = accumulated.texture;
                this.quad.material = this.resolve;
                renderer.autoClear = true;
                renderer.render(this.quadScene, this.quadCamera);
                if (batch) gl.flush(); // submit queries without waiting for GPU completion
                this.lastFrame = {layers, width: this.size.x, height: this.size.y, interactive, capture};
            } finally {
                objects.forEach(e => { e.object.material = e.material; });
                scene.background = saved.background;
                renderer.setRenderTarget(saved.target);
                renderer.setClearColor(saved.color, saved.alpha);
                renderer.autoClear = saved.autoClear;
                renderer.setViewport(saved.viewport); renderer.setScissor(saved.scissor);
                renderer.setScissorTest(saved.scissorTest);
                for (const [original, cached] of this.materials) {
                    if (!activeMaterials.has(original)) { cached.material.dispose(); this.materials.delete(original); }
                }
            }
            return true;
        }
        dispose() {
            if (this.queryBatch) this.queryBatch.queries.forEach(q => this.renderer.getContext().deleteQuery(q));
            this.queryBatch = null;
            this.targets.forEach(t => { if (t.depthTexture) t.depthTexture.dispose(); t.dispose(); });
            this.targets = [];
            this.size.set(0, 0);
            this.materials.forEach(c => c.material.dispose()); this.materials.clear();
            this.quad.geometry.dispose(); this.accumulate.dispose(); this.resolve.dispose();
            this.hiddenMaterial.dispose();
        }
    }
    root.BrachyDepthPeeling = BrachyDepthPeeling;
})(window);
