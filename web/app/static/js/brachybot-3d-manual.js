function _syncTrajectoryChildren() {
    if (!dataTreeState?.planning) return;
    const grouped = {};
    (dataTreeState.planning.seeds || []).forEach(seed => {
        const tid = seed.trajectory_id || 'manual_traj_1';
        if (!grouped[tid]) grouped[tid] = [];
        grouped[tid].push(seed);
    });
    (dataTreeState.planning.trajectories || []).forEach(traj => {
        traj.seeds = grouped[traj.id] || [];
    });
    dataTreeState.planning.trajectoriesLoaded = (dataTreeState.planning.trajectories || []).length > 0;
}

function _syncSeedsOverlayFromDataTree() {
    _syncTrajectoryChildren();
    const seeds = (dataTreeState.planning.seeds || []).map(s => ({
        id: s.id,
        position: _vec3Array(s.position || s.pos),
        direction: _normalizeArray3(s.direction || [0, 0, 1]),
        trajectory_id: s.trajectory_id,
        visible: s.visible !== false,
        opacity: s.opacity ?? 1.0,
        color: s.color || '#ffcc00',
    }));
    const needles = (dataTreeState.planning.needles || []).map(n => ({
        id: n.id,
        points: (n.points || []).map(p => _vec3Array(p)),
        trajectory_id: n.trajectory_id,
        visible: n.visible !== false,
        opacity: n.opacity ?? 0.8,
        color: n.color || '#ff2266',
    }));
    state.seedsOverlay = { seeds, needles };
    state.seeds = seeds.map(s => ({ ...s, pos: s.position }));
    dataTreeState.seeds.loaded = seeds.length > 0;
    dataTreeState.needles.loaded = needles.length > 0;
    redrawSeedNeedleOverlays();
}

function _manualPayload() {
    _syncSeedsOverlayFromDataTree();
    return {
        session_id: _activeApiSessionId(),
        seeds: state.seedsOverlay.seeds.map(s => ({
            id: s.id,
            position: _vec3Array(s.position),
            direction: _normalizeArray3(s.direction),
            trajectory_id: s.trajectory_id,
        })),
        needles: state.seedsOverlay.needles.map(n => ({
            id: n.id,
            points: (n.points || []).map(p => _vec3Array(p)),
            trajectory_id: n.trajectory_id,
        })),
        dose_engine: 'myDoseNet',
    };
}

function addManualNeedle() {
    init3DScene();
    const center = new THREE.Vector3(..._planningCenterWorld());
    const dir = new THREE.Vector3();
    if (scene3D.camera) scene3D.camera.getWorldDirection(dir);
    if (dir.length() < 1e-6) dir.set(0, 0, 1);
    dir.normalize();
    manualPlanningState.needleCounter += 1;
    const id = `needle_manual_${manualPlanningState.needleCounter}`;
    const trajId = `manual_traj_${manualPlanningState.needleCounter}`;
    const start = center.clone().sub(dir.clone().multiplyScalar(80));
    const end = center.clone().add(dir.clone().multiplyScalar(25));
    const needle = {
        id,
        points: [[end.x, end.y, end.z], [start.x, start.y, start.z]],
        trajectory_id: trajId,
        visible: true,
        opacity: 0.75,
        color: '#ff2266',
    };
    dataTreeState.planning.needles.push(needle);
    dataTreeState.planning.trajectories.push({
        id: trajId,
        index: dataTreeState.planning.trajectories.length,
        entry: needle.points[1],
        target: needle.points[0],
        visible: true,
        opacity: 0.8,
        color: '#88ccff',
        seeds: [],
    });
    dataTreeState.planning.trajectoriesLoaded = true;
    manualPlanningState.activeNeedleId = id;
    _upsertSceneMesh(id, _makeNeedleMesh(needle));
    _syncNeedleHandles(needle);
    _syncSeedsOverlayFromDataTree();
    renderDataTree();
    fitCameraToScene();
    addChat('system', `Manual needle added: ${id}. Drag the two endpoint spheres in 3D, then add seeds or recompute dose.`);
    reportUIEvent('manual.needle.add', id, { points: needle.points });
}

async function addManualSeed() {
    init3DScene();
    let needle = dataTreeState.planning.needles.find(n => n.id === manualPlanningState.activeNeedleId);
    if (!needle && dataTreeState.planning.needles.length > 0) {
        needle = dataTreeState.planning.needles[dataTreeState.planning.needles.length - 1];
        manualPlanningState.activeNeedleId = needle.id;
    }
    if (!needle) {
        addManualNeedle();
        needle = dataTreeState.planning.needles[dataTreeState.planning.needles.length - 1];
    }
    const p0 = new THREE.Vector3(..._vec3Array(needle.points[0]));
    const p1 = new THREE.Vector3(..._vec3Array(needle.points[1]));
    const dir = new THREE.Vector3().subVectors(p0, p1).normalize();
    const existing = dataTreeState.planning.seeds.filter(s => s.trajectory_id === needle.trajectory_id).length;
    const frac = Math.max(0.12, Math.min(0.88, 0.22 + existing * 0.10));
    const pos = new THREE.Vector3().lerpVectors(p1, p0, frac);
    manualPlanningState.seedCounter += 1;
    const seed = {
        id: `seed_manual_${manualPlanningState.seedCounter}`,
        position: [pos.x, pos.y, pos.z],
        direction: [dir.x, dir.y, dir.z],
        trajectory_id: needle.trajectory_id,
        visible: true,
        opacity: 1.0,
        color: '#ffcc00',
    };
    dataTreeState.planning.seeds.push(seed);
    const traj = dataTreeState.planning.trajectories.find(t => t.id === needle.trajectory_id);
    if (traj) traj.seeds = dataTreeState.planning.seeds.filter(s => s.trajectory_id === traj.id);
    _upsertSceneMesh(seed.id, _makeSeedMesh(seed));
    _syncSeedsOverlayFromDataTree();
    renderDataTree();
    reportUIEvent('manual.seed.add', seed.id, { position: seed.position, trajectory_id: seed.trajectory_id });
    await recomputeManualDose('seed_add');
}

async function recomputeManualDose(reason = 'manual_update') {
    const payload = _manualPayload();
    payload.reason = reason;
    if (!payload.seeds.length) {
        addChat('error', 'No manual seeds available. Add at least one seed before recomputing dose.');
        return null;
    }
    // Save dose texture state before recompute so it can be restored after
    // refreshPlanningUI reloads all meshes.
    const wasDoseTextureEnabled = !!(state && state.doseTexture && state.doseTexture.enabled);
    addChat('system', 'Manual AI dose recomputing...');
    try {
        const res = await fetch(API + '/manual_planning/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => null);
        if (!res.ok || !data || !data.success) throw new Error((data && data.error) || `HTTP ${res.status}`);
        state.doseOverlay = null;
        state.dvhData = null;
        state.doseTexture.enabled = false;  // Reset so refreshPlanningUI loads meshes without dose
        if (typeof refreshPlanningUI === 'function') await refreshPlanningUI();
        // Restore dose texture mode if it was active before recompute
        if (wasDoseTextureEnabled && typeof setDoseTextureMode === 'function') {
            try { await setDoseTextureMode(true, { silent: true }); } catch (_) {}
        }
        const m = data.metrics || {};
        const v100 = Number.isFinite(m.v100) ? `${(m.v100 * 100).toFixed(1)}%` : '--';
        const d90 = Number.isFinite(m.d90) ? `${m.d90.toFixed(1)} Gy` : '--';
        addChat('system', `Manual AI dose updated: ${data.total_seeds} seeds, V100=${v100}, D90=${d90}.`);
        if (data.advice && data.advice.advice && trainingMonitorState.active) {
            addChat('system', 'Monitor advice: ' + data.advice.advice.slice(0, 2).join(' '));
        }
        return data;
    } catch (e) {
        addChat('error', `Manual AI dose failed: ${e.message}`);
        return null;
    }
}

async function onManualSeedEdited(seedId, position) {
    const seed = dataTreeState.planning.seeds.find(s => s.id === seedId);
    if (seed) seed.position = _vec3Array(position);
    _syncSeedsOverlayFromDataTree();
    reportUIEvent('manual.seed.drag', seedId, { position: _vec3Array(position) });
    await recomputeManualDose('seed_drag');
}

async function onManualNeedleHandleEdited(handle) {
    const needleId = handle?.userData?.needleId;
    const pointIndex = handle?.userData?.pointIndex;
    const needle = dataTreeState.planning.needles.find(n => n.id === needleId);
    if (!needle || pointIndex === undefined) return;
    needle.points[pointIndex] = [handle.position.x, handle.position.y, handle.position.z];
    _upsertSceneMesh(needle.id, _makeNeedleMesh(needle));
    _syncNeedleHandles(needle);
    _syncSeedsOverlayFromDataTree();
    renderDataTree();
    reportUIEvent('manual.needle.drag', needleId, { point_index: pointIndex, points: needle.points });
    const hasSeeds = dataTreeState.planning.seeds.some(s => s.trajectory_id === needle.trajectory_id);
    if (hasSeeds) await recomputeManualDose('needle_drag');
}

async function startTrainingMode(goal = 'Monitor planning workflow') {
    trainingMonitorState.sessionId = _activeApiSessionId();
    trainingMonitorState.goal = goal;
    try {
        const res = await fetch(API + '/training/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: trainingMonitorState.sessionId, goal }),
        });
        const data = await res.json().catch(() => null);
        if (!res.ok || !data || !data.success) throw new Error((data && data.error) || `HTTP ${res.status}`);
        trainingMonitorState.active = true;
        addChat('system', 'Monitor mode started. I will track planning actions and provide live feedback. Use Detailed Advice or Finish Monitor for a full report.');
        await syncUIBridgeState('training_start');
        return data;
    } catch (e) {
        addChat('error', `Monitor mode failed to start: ${e.message}`);
        return null;
    }
}

async function stopTrainingMode() {
    try {
        const res = await fetch(API + '/training/stop', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: _activeApiSessionId() }),
        });
        const data = await res.json().catch(() => null);
        if (!res.ok || !data || !data.success) throw new Error((data && data.error) || `HTTP ${res.status}`);
        trainingMonitorState.active = false;
        addChat('bot-response', _formatAdviceReport(data.advice, data.summary));
        return data;
    } catch (e) {
        addChat('error', `Monitor mode failed to stop: ${e.message}`);
        return null;
    }
}

function _formatAdviceReport(advice, prefix = '') {
    if (!advice) return prefix || 'No advice available yet.';
    const lines = [];
    if (prefix) lines.push(prefix);
    if (advice.strengths && advice.strengths.length) {
        lines.push('**Strengths**');
        advice.strengths.forEach(x => lines.push(`- ${x}`));
    }
    if (advice.issues && advice.issues.length) {
        lines.push('**Issues**');
        advice.issues.forEach(x => lines.push(`- ${x}`));
    }
    if (advice.advice && advice.advice.length) {
        lines.push('**Recommendations**');
        advice.advice.forEach(x => lines.push(`- ${x}`));
    }
    return lines.join('\n');
}

async function requestPlanningAdvice() {
    try {
        const res = await fetch(API + '/training/advice', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: _activeApiSessionId(), ui_state: collectUIState() }),
        });
        const data = await res.json().catch(() => null);
        if (!res.ok || !data || !data.success) throw new Error((data && data.error) || `HTTP ${res.status}`);
        addChat('bot-response', _formatAdviceReport(data, 'Detailed plan advice based on current metrics and UI state:'));
        reportUIEvent('training.advice', 'Detailed advice requested', {});
        return data;
    } catch (e) {
        addChat('error', `Detailed advice failed: ${e.message}`);
        return null;
    }
}

function _formatReadinessReport(data) {
    if (!data) return 'System readiness is not available.';
    const lines = [];
    lines.push(`**System Readiness: ${data.ready ? 'Ready for operator review' : 'Not ready'}**`);
    if (data.blockers && data.blockers.length) {
        lines.push('');
        lines.push('**Blocking items**');
        data.blockers.forEach(x => {
            if (typeof x === 'string') lines.push(`- ${x}`);
            else lines.push(`- ${x.label || x.key}: ${x.detail || ''}${x.action ? ` Next: ${x.action}` : ''}`);
        });
    }
    if (data.items && data.items.length) {
        lines.push('');
        lines.push('| Area | Status | Detail | Next action |');
        lines.push('|---|---|---|---|');
        data.items.forEach(item => {
            const status = item.passed ? 'OK' : 'Needs action';
            lines.push(`| ${item.label || item.key} | ${status} | ${item.detail || ''} | ${item.action || ''} |`);
        });
    }
    if (data.execution_tools) {
        const tools = data.execution_tools;
        lines.push('');
        lines.push('**Execution Tools**');
        lines.push(`- Code execution: ${tools.code_executor_enabled ? 'enabled' : 'disabled by policy'}`);
        lines.push(`- Shell execution: ${tools.shell_executor_enabled ? 'enabled' : 'disabled by policy'}`);
        if (tools.note) lines.push(`- ${tools.note}`);
    }
    if (data.clinical_governance) {
        const governance = data.clinical_governance;
        lines.push('');
        lines.push('**Clinical Governance**');
        lines.push(`- ${governance.clinical_kb_required ? 'Clinical KB evidence is required for clinical claims.' : 'Clinical KB evidence is optional.'}`);
        lines.push(`- ${governance.constraint_policy || governance.threshold_policy || 'Dose constraints must be source-backed.'}`);
    }
    return lines.join('\n');
}

async function checkSystemReadiness() {
    try {
        const res = await fetch(API + '/readiness', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: _activeApiSessionId(), ui_state: collectUIState() }),
        });
        const data = await res.json().catch(() => null);
        if (!res.ok || !data || !data.success) throw new Error((data && data.error) || `HTTP ${res.status}`);
        addChat('bot-response', _formatReadinessReport(data));
        reportUIEvent('system.readiness', 'System readiness checklist requested', { ready: !!data.ready });
        return data;
    } catch (e) {
        addChat('error', `System readiness check failed: ${e.message}`);
        return null;
    }
}

function init3DScene() {
    const canvas = document.getElementById('canvas3D');
    if (!canvas || scene3D.initialized) return;

    // Hide placeholder
    const placeholder = canvas.querySelector('.viewer-no-data');
    if (placeholder) placeholder.style.display = 'none';

    scene3D.scene = new THREE.Scene();
    // No background - use canvas CSS background (#000) for consistency with 2D viewers

    // Fallback size if canvas not visible
    const w = canvas.clientWidth || 400;
    const h = canvas.clientHeight || 300;

    scene3D.camera = new THREE.PerspectiveCamera(50, w / h, 0.1, 5000);
    scene3D.camera.position.set(0, 0, 300);

    scene3D.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    scene3D.renderer.setSize(w, h);
    scene3D.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    scene3D.renderer.shadowMap.enabled = false;
    scene3D.renderer.setClearColor(0x000000, 0);
    canvas.appendChild(scene3D.renderer.domElement);

    // OrbitControls: 3D Slicer style — left=rotate, right=pan, scroll=zoom
    scene3D.controls = new THREE.OrbitControls(scene3D.camera, scene3D.renderer.domElement);
    // 3D Slicer-like interaction: responsive rotation, low inertia, fast zoom
    scene3D.controls.enableDamping = true;
    scene3D.controls.dampingFactor = 0.08;     // Low inertia — more direct response
    scene3D.controls.rotateSpeed = 1.2;        // Fast rotation
    scene3D.controls.zoomSpeed = 2.0;          // Fast zoom
    scene3D.controls.panSpeed = 1.5;           // Fast pan
    scene3D.controls.screenSpacePanning = true;
    scene3D.controls.enablePan = true;
    scene3D.controls.enableZoom = true;
    scene3D.controls.enableRotate = true;
    scene3D.controls.minDistance = 5;
    scene3D.controls.maxDistance = 3000;
    scene3D.controls.mouseButtons = {
        LEFT: THREE.MOUSE.ROTATE,
        MIDDLE: THREE.MOUSE.DOLLY,
        RIGHT: THREE.MOUSE.PAN
    };
    scene3D.controls.touches = {
        ONE: THREE.TOUCH.ROTATE,
        TWO: THREE.TOUCH.DOLLY_PAN
    };

    // Lighting — brighter for better visibility
    scene3D.scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const dir1 = new THREE.DirectionalLight(0xffffff, 0.8);
    dir1.position.set(200, 200, 200);
    scene3D.scene.add(dir1);
    const dir2 = new THREE.DirectionalLight(0xffffff, 0.4);
    dir2.position.set(-200, -100, -200);
    scene3D.scene.add(dir2);
    const dir3 = new THREE.DirectionalLight(0xffffff, 0.2);
    dir3.position.set(0, -200, 100);
    scene3D.scene.add(dir3);

    // Axis indicator
    // Orientation axes (bottom-left corner, like 3D Slicer)
    const axesScene = new THREE.Scene();
    const axesCamera = new THREE.OrthographicCamera(-2.5, 2.5, 2.5, -2.5, 0.1, 100);
    axesCamera.position.set(0, 0, 5);
    axesCamera.lookAt(0, 0, 0);

    // Create polished axes with cylinders + cones
    const axesGroup = new THREE.Group();
    const axisLen = 1.0;
    const shaftRadius = 0.06;
    const headRadius = 0.15;
    const headLen = 0.3;

    function makeAxis(direction, color) {
        const group = new THREE.Group();
        // Shaft (cylinder)
        const shaftGeo = new THREE.CylinderGeometry(shaftRadius, shaftRadius, axisLen - headLen, 12);
        const shaftMat = new THREE.MeshPhongMaterial({ color, shininess: 60 });
        const shaft = new THREE.Mesh(shaftGeo, shaftMat);
        shaft.position.y = (axisLen - headLen) / 2;
        group.add(shaft);
        // Head (cone)
        const headGeo = new THREE.ConeGeometry(headRadius, headLen, 16);
        const headMat = new THREE.MeshPhongMaterial({ color, shininess: 60 });
        const head = new THREE.Mesh(headGeo, headMat);
        head.position.y = axisLen - headLen / 2;
        group.add(head);
        // Rotate to point in correct direction
        if (direction === 'x') group.rotation.z = -Math.PI / 2;
        else if (direction === 'z') group.rotation.x = Math.PI / 2;
        return group;
    }

    // X = Red (Right), Y = Green (Anterior), Z = Blue (Superior)
    axesGroup.add(makeAxis('x', 0xff4444));
    axesGroup.add(makeAxis('y', 0x44dd44));
    axesGroup.add(makeAxis('z', 0x4488ff));

    // Small sphere at origin
    const originGeo = new THREE.SphereGeometry(0.1, 16, 16);
    const originMat = new THREE.MeshPhongMaterial({ color: 0xffffff, shininess: 80 });
    axesGroup.add(new THREE.Mesh(originGeo, originMat));

    // Text labels using sprites
    function makeLabel(text, pos, color) {
        const canvas = document.createElement('canvas');
        canvas.width = 64;
        canvas.height = 64;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = color;
        ctx.font = 'bold 40px Arial';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(text, 32, 32);
        const tex = new THREE.CanvasTexture(canvas);
        const mat = new THREE.SpriteMaterial({ map: tex, transparent: true });
        const sprite = new THREE.Sprite(mat);
        sprite.position.copy(pos);
        sprite.scale.set(0.5, 0.5, 1);
        return sprite;
    }

    axesGroup.add(makeLabel('R', new THREE.Vector3(1.5, 0, 0), '#ff4444'));
    axesGroup.add(makeLabel('A', new THREE.Vector3(0, 1.5, 0), '#44dd44'));
    axesGroup.add(makeLabel('S', new THREE.Vector3(0, 0, 1.5), '#4488ff'));

    axesScene.add(axesGroup);
    axesScene.add(new THREE.AmbientLight(0xffffff, 0.8));
    const axLight = new THREE.DirectionalLight(0xffffff, 0.6);
    axLight.position.set(2, 3, 4);
    axesScene.add(axLight);

    // Render on demand. OrbitControls emits `change` while the user moves the
    // camera and while damping settles; static scenes no longer consume a GPU
    // frame at 60 Hz indefinitely.
    let renderFrameId = 0;
    let pendingFrames = 0;
    let drawingFrame = false;

    function requestRender(frameBudget = 2) {
        pendingFrames = Math.max(pendingFrames, Math.max(1, frameBudget));
        if (!renderFrameId && !drawingFrame && !document.hidden) {
            renderFrameId = requestAnimationFrame(drawFrame);
        }
    }

    function drawFrame() {
        renderFrameId = 0;
        if (document.hidden || !scene3D.renderer) return;
        drawingFrame = true;
        const controlsChanged = scene3D.controls.update();

        // Sync axes orientation with main camera
        axesGroup.rotation.copy(scene3D.camera.rotation);

        // BUG FIX 2026-06-17 (3D viewer empty after planning):
        // If the canvas was 0×0 at init time (panel not visible),
        // the renderer viewport is still 0×0 even after the panel
        // becomes visible. Detect dimension changes and re-size.
        const curW = canvas.clientWidth || 400;
        const curH = canvas.clientHeight || 300;
        if (scene3D.renderer && (scene3D.renderer.domElement.width !== curW * Math.min(window.devicePixelRatio, 2)
            || scene3D.renderer.domElement.height !== curH * Math.min(window.devicePixelRatio, 2))) {
            scene3D.camera.aspect = curW / curH;
            scene3D.camera.updateProjectionMatrix();
            scene3D.renderer.setSize(curW, curH);
        }

        // Render main scene
        scene3D.renderer.render(scene3D.scene, scene3D.camera);

        // Render axes in bottom-left corner (transparent background)
        const w = canvas.clientWidth, h = canvas.clientHeight;
        const size = Math.min(100, Math.min(w, h) * 0.2);
        scene3D.renderer.setViewport(8, 8, size, size);
        scene3D.renderer.setScissor(8, 8, size, size);
        scene3D.renderer.setScissorTest(true);
        scene3D.renderer.autoClear = false;
        scene3D.renderer.render(axesScene, axesCamera);
        scene3D.renderer.autoClear = true;
        scene3D.renderer.setScissorTest(false);
        scene3D.renderer.setViewport(0, 0, w, h);

        drawingFrame = false;
        pendingFrames = Math.max(0, pendingFrames - 1);
        if (controlsChanged || pendingFrames > 0) requestRender(pendingFrames || 1);
    }
    scene3D.requestRender = requestRender;
    scene3D.controls.addEventListener('change', () => requestRender(8));
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) requestRender(2);
    });
    requestRender(2);
    scene3D.initialized = true;

    // Resize handler for 3D viewer — also re-fit camera so meshes
    // become visible when the panel transitions from hidden to shown.
    const resizeObserver3D = new ResizeObserver(() => {
        if (!scene3D.renderer || !scene3D.camera) return;
        const newW = canvas.clientWidth || 400;
        const newH = canvas.clientHeight || 300;
        if (newW < 10 || newH < 10) return;  // skip if still hidden
        scene3D.camera.aspect = newW / newH;
        scene3D.camera.updateProjectionMatrix();
        scene3D.renderer.setSize(newW, newH);
        // Re-fit camera to scene when panel becomes visible
        if (Object.keys(scene3D.meshes).length > 0) {
            fitCameraToScene();
        }
        requestRender(2);
    });
    resizeObserver3D.observe(canvas);

    // ==================== 3D PICKING / INTERACTION ====================
    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    let selectedObject = null;
    let isDragging = false;
    let dragPlane = new THREE.Plane();
    let dragOffset = new THREE.Vector3();

    // Mouse down - start drag or select
    canvas.addEventListener('mousedown', (event) => {
        if (event.button !== 0) return; // Only left click

        const rect = canvas.getBoundingClientRect();
        mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

        raycaster.setFromCamera(mouse, scene3D.camera);
        const intersects = raycaster.intersectObjects(Object.values(scene3D.meshes), true);

        if (intersects.length > 0) {
            let obj = intersects[0].object;
            // Find parent group if it's a child
            while (obj.parent && !obj.userData.type) {
                obj = obj.parent;
            }

            if (obj.userData.type === 'seed' || obj.userData.type === 'needle' || obj.userData.type === 'needle_handle') {
                // Select this object
                if (selectedObject) {
                    // Deselect previous
                    if (selectedObject.material && selectedObject.material.emissive) {
                        selectedObject.material.emissive.setHex(selectedObject.userData.originalEmissive || 0x332200);
                    }
                }

                selectedObject = obj;
                obj.userData.originalEmissive = obj.userData.originalEmissive || obj.material?.emissive?.getHex() || 0x332200;
                if (obj.material && obj.material.emissive) {
                    obj.material.emissive.setHex(0xff0000);
                }
                requestRender(2);

                // Highlight in data tree
                if (obj.userData.type === 'seed') highlightSeed(obj.userData.id);

                // Start drag for editable planning handles
                if (obj.userData.type === 'seed' || obj.userData.type === 'needle_handle') {
                    isDragging = true;
                    scene3D.controls.enabled = false;

                    // Create drag plane perpendicular to camera
                    const cameraDir = new THREE.Vector3();
                    scene3D.camera.getWorldDirection(cameraDir);
                    dragPlane.setFromNormalAndCoplanarPoint(cameraDir, obj.position);

                    // Calculate offset
                    const intersection = new THREE.Vector3();
                    raycaster.ray.intersectPlane(dragPlane, intersection);
                    dragOffset.copy(obj.position).sub(intersection);
                }

                // Show info
                const info = obj.userData.type === 'seed'
                    ? `Seed ${obj.userData.id} | Trajectory ${obj.userData.trajectoryId}`
                    : obj.userData.type === 'needle_handle'
                        ? `Needle endpoint ${obj.userData.pointIndex + 1} | ${obj.userData.needleId}`
                        : `Needle ${obj.userData.id} | Trajectory ${obj.userData.trajectoryId}`;
                addChat('system', `Selected: ${info}`);
            }
        } else {
            // Deselect
            if (selectedObject && selectedObject.material && selectedObject.material.emissive) {
                selectedObject.material.emissive.setHex(selectedObject.userData.originalEmissive || 0x332200);
            }
            selectedObject = null;
            requestRender(2);
        }
    });

    // Mouse move - drag seed
    canvas.addEventListener('mousemove', (event) => {
        if (!isDragging || !selectedObject) return;

        const rect = canvas.getBoundingClientRect();
        mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

        raycaster.setFromCamera(mouse, scene3D.camera);
        const intersection = new THREE.Vector3();
        raycaster.ray.intersectPlane(dragPlane, intersection);

        selectedObject.position.copy(intersection.add(dragOffset));
        requestRender(1);
    });

    // Mouse up - end drag
    canvas.addEventListener('mouseup', () => {
        if (isDragging) {
            isDragging = false;
            scene3D.controls.enabled = true;
            requestRender(4);

            if (selectedObject && selectedObject.userData.type === 'seed') {
                // Update seed position in data tree state
                const seedId = selectedObject.userData.id;
                const seed = dataTreeState.planning.seeds.find(s => s.id === seedId);
                if (seed) {
                    seed.position = [selectedObject.position.x, selectedObject.position.y, selectedObject.position.z];
                }
                addChat('system', `Seed ${seedId} repositioned to [${selectedObject.position.x.toFixed(1)}, ${selectedObject.position.y.toFixed(1)}, ${selectedObject.position.z.toFixed(1)}]`);
                if (typeof onManualSeedEdited === 'function') {
                    onManualSeedEdited(seedId, selectedObject.position).catch(e => console.warn('manual seed edit failed:', e));
                }
            } else if (selectedObject && selectedObject.userData.type === 'needle_handle') {
                addChat('system', `Needle endpoint updated for ${selectedObject.userData.needleId}.`);
                if (typeof onManualNeedleHandleEdited === 'function') {
                    onManualNeedleHandleEdited(selectedObject).catch(e => console.warn('manual needle edit failed:', e));
                }
            }
        }
    });

    // Right-click context menu for 3D objects
    canvas.addEventListener('contextmenu', (event) => {
        event.preventDefault();

        const rect = canvas.getBoundingClientRect();
        mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

        raycaster.setFromCamera(mouse, scene3D.camera);
        const intersects = raycaster.intersectObjects(Object.values(scene3D.meshes), true);

        if (intersects.length > 0) {
            let obj = intersects[0].object;
            while (obj.parent && !obj.userData.type) {
                obj = obj.parent;
            }

            if (obj.userData.type === 'seed' || obj.userData.type === 'needle') {
                show3DContextMenu(event.clientX, event.clientY, obj);
            }
        }
    });

    function show3DContextMenu(x, y, obj) {
        hideContextMenu();
        const menu = document.createElement('div');
        menu.className = 'ctx-menu';
        menu.id = 'ctxMenu';
        menu.style.left = x + 'px';
        menu.style.top = y + 'px';

        const type = obj.userData.type;
        const id = obj.userData.id;

        let items = `<div class="ctx-menu-item" style="opacity:0.5;cursor:default;font-size:0.6rem;">
            <span class="ctx-icon">${type === 'seed' ? '💊' : '📍'}</span> ${type}: ${id}</div>`;
        items += `<div class="ctx-menu-sep"></div>`;

        // Highlight
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();highlightSeed('${id}')">
            <span class="ctx-icon">&#127912;</span> Highlight</div>`;

        if (type === 'seed') {
            // Show dose at seed position
            items += `<div class="ctx-menu-item" onclick="hideContextMenu();showSeedDose('${id}')">
                <span class="ctx-icon">&#9889;</span> Show Dose</div>`;

            // Delete seed
            items += `<div class="ctx-menu-item" onclick="hideContextMenu();deleteSeed3D('${id}')">
                <span class="ctx-icon">&#128465;</span> Delete</div>`;
        }

        if (type === 'needle') {
            // Show seeds on needle
            items += `<div class="ctx-menu-item" onclick="hideContextMenu();showNeedleSeeds('${id}')">
                <span class="ctx-icon">&#128167;</span> Show Seeds</div>`;

            // Delete needle
            items += `<div class="ctx-menu-item" onclick="hideContextMenu();deleteNeedle3D('${id}')">
                <span class="ctx-icon">&#128465;</span> Delete</div>`;
        }

        items += `<div class="ctx-menu-sep"></div>`;
        items += `<div class="ctx-menu-item" onclick="hideContextMenu();clearSelection()">
            <span class="ctx-icon">&#10005;</span> Deselect</div>`;

        menu.innerHTML = items;
        document.body.appendChild(menu);

        const menuRect = menu.getBoundingClientRect();
        if (menuRect.right > window.innerWidth) menu.style.left = (x - menuRect.width) + 'px';
        if (menuRect.bottom > window.innerHeight) menu.style.top = (y - menuRect.height) + 'px';

        setTimeout(() => {
            document.addEventListener('click', hideContextMenu, { once: true });
            document.addEventListener('contextmenu', hideContextMenu, { once: true });
        }, 0);
    }

    function clearSelection() {
        if (selectedObject && selectedObject.material && selectedObject.material.emissive) {
            selectedObject.material.emissive.setHex(selectedObject.userData.originalEmissive || 0x332200);
        }
        selectedObject = null;
    }

}

function addMeshToScene(meshData) {
    init3DScene();
    const id = meshData.organ_id || meshData.source || 'mesh_' + Date.now();

    // Remove existing mesh with same ID
    if (scene3D.meshes[id]) {
        // A reconstruction can replace a mesh while dose mode is active.
        // Discard the old material snapshot so disabling dose mode restores
        // the replacement mesh, not a disposed material from the old one.
        if (typeof state !== 'undefined' && state.doseTexture?.enabled) {
            if (state.doseTexture.originalMaterials) delete state.doseTexture.originalMaterials[id];
            if (state.doseTexture.originalSceneStyle) delete state.doseTexture.originalSceneStyle[id];
        }
        scene3D.scene.remove(scene3D.meshes[id]);
        scene3D.meshes[id].geometry.dispose();
        scene3D.meshes[id].material.dispose();
    }

    const geometry = new THREE.BufferGeometry();
    const vertices = new Float32Array(meshData.vertices.flat());
    const indices = new Uint32Array(meshData.faces.flat());
    // Validate: skip meshes with NaN vertices (corrupted server data)
    let hasNaN = false;
    for (let i = 0; i < vertices.length; i++) { if (isNaN(vertices[i])) { hasNaN = true; break; } }
    if (hasNaN) { console.warn('[addMeshToScene] Skipping mesh with NaN vertices:', id); return; }
    geometry.setAttribute('position', new THREE.BufferAttribute(vertices, 3));
    geometry.setIndex(new THREE.BufferAttribute(indices, 1));
    geometry.computeVertexNormals();

    // Use physical coordinates directly (mm) — no scaling
    const color = meshData.color || 0x0ea5e9;
    // BUG FIX 2026-06-17 (3D opacity source): previously the
    // opacity came only from the meshOpacity3D slider. The user
    // wanted the DEFAULT opacity to come from the display_3d
    // hyperparam config, with per-mesh overrides from the data
    // tree taking precedence. Priority order:
    //   1. meshData.opacity (per-mesh override from the data tree)
    //   2. config-based default keyed by source (ctv/oar/seed/needle/iso)
    //   3. meshOpacity3D slider (user's live tweak)
    //   4. hard-coded fallback (0.7)
    let opacity;
    if (typeof meshData.opacity === 'number' && !isNaN(meshData.opacity)) {
        opacity = meshData.opacity;
    } else if (_3dConfigCache) {
        const src = meshData.source || '';
        if (src === 'ctv') opacity = _3dConfigCache.ctv_opacity;
        else if (src === 'oar') opacity = _3dConfigCache.oar_opacity;
        else if (src === 'seed' || src === 'seeds') opacity = _3dConfigCache.seed_opacity;
        else if (src === 'needle' || src === 'needles') opacity = _3dConfigCache.needle_opacity;
        else opacity = _3dConfigCache.default_opacity;
    } else {
        opacity = parseFloat(document.getElementById('meshOpacity3D')?.value || 70) / 100;
    }

    // Clean surface rendering (like 3D Slicer polydata)
    const surfaceMat = new THREE.MeshPhysicalMaterial({
        color: color,
        transparent: true,
        opacity: opacity,
        side: THREE.DoubleSide,
        roughness: 0.4,
        metalness: 0.1,
        clearcoat: 0.3,
        clearcoatRoughness: 0.2,
        depthWrite: opacity > 0.001,
        depthTest: true,
    });
    const mesh = new THREE.Mesh(geometry, surfaceMat);
    mesh.visible = opacity > 0.001;
    mesh.userData = { type: 'mesh', id, source: meshData.source || 'mesh', labelId: meshData.label_id, organId: id };

    scene3D.scene.add(mesh);
    scene3D.meshes[id] = mesh;
    uiDebugLog('[addMeshToScene] Added mesh:', id, 'vertices:', meshData.vertex_count, 'total meshes:', Object.keys(scene3D.meshes).length);

    // Mirror this mesh into the data tree so the user can see all 3D
    // meshes (CTV/OAR/dose/etc.) listed with their own visibility toggle.
    // Without this, the data tree was empty after 3D reconstruction and
    // the user had no way to know what was actually loaded into the
    // viewer.
    if (dataTreeState && dataTreeState.planning) {
        const colorHex = typeof color === 'number'
            ? '#' + color.toString(16).padStart(6, '0')
            : (typeof color === 'string' ? color : '#0ea5e9');
        const label = (meshData.label || meshData.organ_id || meshData.source || id).toString();
        const existing = dataTreeState.planning.meshes.findIndex(m => m.id === id);
        const entry = {
            id,
            label,
            source: meshData.source || 'mesh',
            labelId: meshData.label_id,
            color: colorHex,
            visible: true,
            opacity,
            vertexCount: meshData.vertex_count || (meshData.vertices ? meshData.vertices.length / 3 : 0),
        };
        if (existing >= 0) dataTreeState.planning.meshes[existing] = entry;
        else dataTreeState.planning.meshes.push(entry);
        if (typeof renderDataTree === 'function') renderDataTree();
    }

    // Keep manual reconstruction consistent with the current surface mode.
    // New CTV/OAR meshes are immediately mapped when dose mode is active.
    if (typeof state !== 'undefined' && state.doseTexture?.enabled &&
        typeof _isDoseTexturableMesh === 'function' &&
        _isDoseTexturableMesh(id, mesh) && typeof _applyDoseTextureToMesh === 'function') {
        _applyDoseTextureToMesh(id, mesh)
            .then(() => {
                if (typeof _prepareDoseTextureSceneVisibility === 'function') {
                    _prepareDoseTextureSceneVisibility();
                }
                if (scene3D.requestRender) scene3D.requestRender(2);
            })
            .catch(e => console.warn('[addMeshToScene] dose remap failed:', e));
    }

    // Fit camera to all meshes
    fitCameraToScene();
    if (scene3D.requestRender) scene3D.requestRender(4);
}

function fitCameraToScene() {
    if (!scene3D.camera || !scene3D.controls) return;
    const box = new THREE.Box3();
    // Skip meshes with NaN in position to prevent camera NaN
    Object.values(scene3D.meshes).forEach(m => {
        if (!m) return;
        const pos = m.geometry?.attributes?.position;
        if (pos) {
            for (let i = 0; i < Math.min(pos.array.length, 100); i++) {
                if (isNaN(pos.array[i])) return; // skip this mesh
            }
        }
        box.expandByObject(m);
    });
    if (scene3D.skinMesh) box.expandByObject(scene3D.skinMesh);
    if (box.isEmpty()) {
        // Default view for empty scene
        scene3D.camera.position.set(200, 150, 200);
        scene3D.controls.target.set(0, 0, 0);
        scene3D.controls.update();
        if (scene3D.requestRender) scene3D.requestRender(4);
        return;
    }
    const center = new THREE.Vector3();
    box.getCenter(center);
    const size = new THREE.Vector3();
    box.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z) || 1;
    const dist = maxDim * 1.8;
    // 3D Slicer-like default view angle (slightly from top-right)
    scene3D.controls.target.copy(center);
    scene3D.camera.position.set(center.x + dist * 0.5, center.y + dist * 0.5, center.z + dist * 0.5);
    scene3D.camera.near = dist * 0.005;
    scene3D.camera.far = dist * 20;
    scene3D.camera.updateProjectionMatrix();
    scene3D.controls.update();
    if (scene3D.requestRender) scene3D.requestRender(8);
}

function render3DMesh(meshData) {
    addMeshToScene(meshData);
    window.dose3D = true;
}

function reset3DView() {
    fitCameraToScene();
}

// Re-initialize / re-size the 3D viewer when entering the viewers panel
// after planning. Without this, the canvas may have been initialized with
// a 0×0 size (because the 3D card was off-screen / not yet laid out when
// init3DScene first ran), and the meshes are loaded into the scene but
// the renderer has nothing to draw into. We force a re-size and a fresh
// fit-camera-to-scene so the user immediately sees the CTV mesh, seeds,
// needles, and dose isosurfaces in the 3D viewer.
function forceRender3DViewer() {
    const canvas = document.getElementById('canvas3D');
    if (!canvas) return;
    init3DScene();
    // Re-measure after layout settles. Use double-rAF to ensure the
    // browser has completed layout before we read clientWidth/Height.
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            if (!scene3D.renderer || !scene3D.camera) return;
            const w = canvas.clientWidth || 400;
            const h = canvas.clientHeight || 300;
            scene3D.camera.aspect = w / h;
            scene3D.camera.updateProjectionMatrix();
            scene3D.renderer.setSize(w, h);
            fitCameraToScene();
            // Re-hide the "No data" placeholder if meshes are present
            const placeholder = canvas.querySelector('.viewer-no-data');
            if (placeholder && Object.keys(scene3D.meshes).length > 0) {
                placeholder.style.display = 'none';
            }
            // If canvas was still 0×0 (panel not yet visible), retry
            // once more after a short delay to catch late layout.
            if ((canvas.clientWidth || 0) < 10 && Object.keys(scene3D.meshes).length > 0) {
                setTimeout(() => {
                    const w2 = canvas.clientWidth || 400;
                    const h2 = canvas.clientHeight || 300;
                    if (w2 > 10 && h2 > 10) {
                        scene3D.camera.aspect = w2 / h2;
                        scene3D.camera.updateProjectionMatrix();
                        scene3D.renderer.setSize(w2, h2);
                        fitCameraToScene();
                    }
                }, 300);
            }
        });
    });
}

function update3DMeshOpacity(val) {
    const opacity = parseInt(val) / 100;
    Object.values(scene3D.meshes).forEach(mesh => {
        if (!mesh) return;
        applyMeshOpacity(mesh, opacity, true);
    });
    if (scene3D.requestRender) scene3D.requestRender(2);
}

function toggle3DWireframe(on) {
    Object.values(scene3D.meshes).forEach(mesh => {
        if (!mesh) return;
        if (mesh.material) {
            // Add wireframe effect by changing material
            if (on) {
                mesh.material.wireframe = true;
                applyMeshOpacity(mesh, 0.8, true);
            } else {
                mesh.material.wireframe = false;
                const opVal = document.getElementById('meshOpacity3D')?.value || 70;
                applyMeshOpacity(mesh, parseInt(opVal) / 100, true);
            }
        }
    });
    if (scene3D.requestRender) scene3D.requestRender(2);
}

async function toggle3DSkin(on) {
    if (!on) {
        if (scene3D.skinMesh) {
            scene3D.scene.remove(scene3D.skinMesh);
            scene3D.skinMesh.geometry.dispose();
            scene3D.skinMesh.material.dispose();
            scene3D.skinMesh = null;
        }
        return;
    }
    // Fetch CT skin mesh from server
    try {
        const res = await fetch(API + '/viewer/3d_skin', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (data.success) {
            init3DScene();
            const geometry = new THREE.BufferGeometry();
            geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(data.vertices.flat()), 3));
            geometry.setIndex(new THREE.BufferAttribute(new Uint32Array(data.faces.flat()), 1));
            geometry.computeVertexNormals();
            const mesh = new THREE.Mesh(geometry, new THREE.MeshPhongMaterial({
                color: 0xcccccc, transparent: true, opacity: 0.15, side: THREE.DoubleSide,
            }));
            scene3D.scene.add(mesh);
            scene3D.skinMesh = mesh;
            if (typeof state !== 'undefined' && state.doseTexture?.enabled &&
                typeof _prepareDoseTextureSceneVisibility === 'function') {
                _prepareDoseTextureSceneVisibility();
            }
            fitCameraToScene();
        }
    } catch (e) {
        console.error('CT skin failed:', e);
    }
}

// ==================== SEED & NEEDLE 3D VISUALIZATION ====================

function _normalizeTrajectoryId(tid) {
    if (tid === null || tid === undefined || tid === '') return 'unassigned';
    if (typeof tid === 'number' && Number.isFinite(tid)) return `traj_${tid + 1}`;
    const s = String(tid);
    if (/^\d+$/.test(s)) return `traj_${Number(s) + 1}`;
    return s;
}

async function loadSeeds3D() {
    try {
        const res = await fetch(API + '/planning/seeds_3d');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Failed to load seeds');

        // Store seed/needle data in state for 2D overlay rendering
        state.seedsOverlay = { seeds: data.seeds || [], needles: data.needles || [] };

        init3DScene();

        // Clear existing seed/needle meshes
        Object.keys(scene3D.meshes).forEach(id => {
            if (id.startsWith('seed_') || id.startsWith('needle_')) {
                scene3D.scene.remove(scene3D.meshes[id]);
                if (scene3D.meshes[id].geometry) scene3D.meshes[id].geometry.dispose();
                if (scene3D.meshes[id].material) scene3D.meshes[id].material.dispose();
                delete scene3D.meshes[id];
            }
        });

        // Update dataTreeState with planning data
        dataTreeState.planning.seeds = data.seeds.map(seed => ({
            id: seed.id,
            position: seed.position,
            voxel_index: seed.voxel_index || null,
            direction: seed.direction,
            trajectory_id: _normalizeTrajectoryId(seed.trajectory_id),
            visible: true,
            opacity: 1.0,
            color: '#ffcc00',
        }));

        dataTreeState.planning.needles = data.needles.map(needle => ({
            id: needle.id,
            points: needle.points,
            trajectory_id: _normalizeTrajectoryId(needle.trajectory_id),
            visible: true,
            opacity: 0.9,
            color: '#ff2266',
        }));

        state.seeds = dataTreeState.planning.seeds.map(seed => ({
            id: seed.id,
            pos: seed.position,
            position: seed.position,
            voxel_index: seed.voxel_index || null,
            direction: seed.direction,
            trajectory_id: seed.trajectory_id,
            visible: seed.visible,
            opacity: seed.opacity,
            color: seed.color,
        }));

        dataTreeState.seeds.loaded = true;
        dataTreeState.seeds.visible = true;
        dataTreeState.needles.loaded = true;
        dataTreeState.needles.visible = true;

        // Render seeds as cylinders (matching Zhiyuan ref.py: length=4.5, radius=0.4, yellow)
        // Slightly enlarged for 3D scene visibility (real brachy seeds are ~0.4mm × 4.5mm,
        // which is hard to spot in a 200-400mm CT volume).
        const seedRadius = 0.8;
        const seedLength = 4.5;
        data.seeds.forEach(seed => {
            const pos = new THREE.Vector3(...seed.position);
            // direction may be [[x,y,z]] (nested) or [x,y,z] (flat) — flatten it
            const rawDir = Array.isArray(seed.direction[0]) ? seed.direction[0] : seed.direction;
            const dir = new THREE.Vector3(...rawDir).normalize();

            const geometry = new THREE.CylinderGeometry(seedRadius, seedRadius, seedLength, 16);
            const material = new THREE.MeshPhysicalMaterial({
                color: 0xe6e64d,  // Zhiyuan yellow: RGB(230, 230, 77)
                metalness: 0.5,
                roughness: 0.3,
                emissive: 0x332200,
                emissiveIntensity: 0.5,
            });
            const mesh = new THREE.Mesh(geometry, material);

            // Orient cylinder along direction (initially Y-axis)
            const axis = new THREE.Vector3(0, 1, 0);
            const quaternion = new THREE.Quaternion().setFromUnitVectors(axis, dir);
            mesh.setRotationFromQuaternion(quaternion);
            mesh.position.copy(pos);

            mesh.userData = { type: 'seed', id: seed.id, trajectoryId: _normalizeTrajectoryId(seed.trajectory_id) };
            scene3D.scene.add(mesh);
            scene3D.meshes[seed.id] = mesh;
        });

        // Render needles as VIVID TUBES (LineBasicMaterial linewidth doesn't work in WebGL).
        // Bright magenta-red for clear visibility against the CTV mesh & dose cloud.
        data.needles.forEach(needle => {
            if (needle.points.length < 2) return;
            let points = needle.points.map(p => new THREE.Vector3(...p));

            try {
                // Filter out NaN points from needle trajectory
                points = points.filter(p => !isNaN(p.x) && !isNaN(p.y) && !isNaN(p.z));
                if (points.length < 2) return;
                let tube;
                if (points.length === 2) {
                    // For 2-point lines, create a CylinderGeometry along
                    // the direction — TubeGeometry with LineCurve3 can fail
                    // in some Three.js builds due to Frenet frame issues.
                    const dir = new THREE.Vector3().subVectors(points[1], points[0]);
                    const length = dir.length();
                    if (length < 0.1) return;
                    dir.normalize();
                    const needleRadius = 0.28;
                    const geo = new THREE.CylinderGeometry(needleRadius, needleRadius, length, 10);
                    const mat = new THREE.MeshPhysicalMaterial({
                        color: 0xff2266, transparent: true, opacity: 0.9,
                        metalness: 0.1, roughness: 0.4,
                        emissive: 0x550011, emissiveIntensity: 0.6,
                    });
                    tube = new THREE.Mesh(geo, mat);
                    // Position at midpoint
                    const mid = new THREE.Vector3().addVectors(points[0], points[1]).multiplyScalar(0.5);
                    tube.position.copy(mid);
                    // Orient along direction
                    const axis = new THREE.Vector3(0, 1, 0);
                    const quat = new THREE.Quaternion().setFromUnitVectors(axis, dir);
                    tube.setRotationFromQuaternion(quat);
                } else {
                    const curve = new THREE.CatmullRomCurve3(points);
                    const tubeGeometry = new THREE.TubeGeometry(curve, 32, 0.28, 10, false);
                    const tubeMaterial = new THREE.MeshPhysicalMaterial({
                        color: 0xff2266, transparent: true, opacity: 0.9,
                        metalness: 0.1, roughness: 0.4,
                        emissive: 0x550011, emissiveIntensity: 0.6,
                    });
                    tube = new THREE.Mesh(tubeGeometry, tubeMaterial);
                }
                tube.userData = { type: 'needle', id: needle.id, trajectoryId: _normalizeTrajectoryId(needle.trajectory_id) };
                scene3D.scene.add(tube);
                scene3D.meshes[needle.id] = tube;
                if (typeof _syncNeedleHandles === 'function') _syncNeedleHandles({
                    id: needle.id,
                    points: needle.points,
                    trajectory_id: _normalizeTrajectoryId(needle.trajectory_id),
                    visible: true,
                    opacity: 0.9,
                });
            } catch (e) {
                // Fallback: render as a simple line
                const lineGeo = new THREE.BufferGeometry().setFromPoints(points);
                const lineMat = new THREE.LineBasicMaterial({ color: 0xff2266, linewidth: 2 });
                const line = new THREE.Line(lineGeo, lineMat);
                line.userData = { type: 'needle', id: needle.id, trajectoryId: _normalizeTrajectoryId(needle.trajectory_id) };
                scene3D.scene.add(line);
                scene3D.meshes[needle.id] = line;
                if (typeof _syncNeedleHandles === 'function') _syncNeedleHandles({
                    id: needle.id,
                    points: needle.points,
                    trajectory_id: _normalizeTrajectoryId(needle.trajectory_id),
                    visible: true,
                    opacity: 0.9,
                });
            }
        });

        // Mirror seeds/needles into the data tree. The user previously
        // saw duplicate listings (2026-06-16 bug): seeds were shown
        // twice — once under Planning → Trajectories → [Trajectory →
        // Seed 1.1, ...] (grouped by trajectory_id) and once again
        // under Planning → 3D Meshes (a flat list). CTV/OAR meshes
        // still go through addMeshToScene, but seeds/needles are
        // already shown in the Trajectories tree, so we no longer
        // push them into planning.meshes. The visibility toggle for
        // seeds/needles is now controlled via the trajectories group.
        if (dataTreeState && dataTreeState.planning) {
            // Remove any prior seed/needle mirror entries from a
            // previous version of this code (in case the user upgrades
            // mid-session and we re-run planning with the old data
            // tree still polluted).
            dataTreeState.planning.meshes = (dataTreeState.planning.meshes || [])
                .filter(m => !m.id.startsWith('seed_') && !m.id.startsWith('needle_'));
        }

        // Update data tree
        if (state.trajectories && state.trajectories.length > 0) {
            updateTrajectories(state.trajectories);
        }
        renderDataTree();
        fitCameraToScene();
        forceRender3DViewer();
        ['axial', 'sagittal', 'coronal'].forEach(axis => {
            if (state.slices && state.slices[axis] !== undefined) {
                try { renderSeedsOverlay(axis, state.slices[axis]); } catch (_) {}
            }
        });

        uiDebugLog(`[loadSeeds3D] Added ${data.seeds.length} seeds + ${data.needles.length} needles to 3D scene (total meshes: ${Object.keys(scene3D.meshes).length})`);

        return { seeds: data.seeds.length, needles: data.needles.length };
    } catch (e) {
        console.error('Load seeds 3D failed:', e);
        return { error: e.message };
    }
}

async function loadDoseIsosurface(threshold = 1.0, color = 0x00ff88) {
    try {
        const res = await fetch(API + '/planning/dose_isosurface', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ threshold }),
        });
        if (!res.ok) { console.warn(`[loadDoseIsosurface] ${threshold} Gy: HTTP ${res.status}`); return; }
        const data = await res.json();
        if (!data.success) { console.warn(`[loadDoseIsosurface] ${threshold} Gy: ${data.error}`); return; }
        if (!data.vertex_count || data.vertex_count === 0) { uiDebugLog(`[loadDoseIsosurface] ${threshold} Gy: 0 vertices, skipping`); return; }

        init3DScene();

        // Remove existing dose isosurface
        const existingId = `dose_iso_${threshold}`;
        if (scene3D.meshes[existingId]) {
            scene3D.scene.remove(scene3D.meshes[existingId]);
            scene3D.meshes[existingId].geometry.dispose();
            scene3D.meshes[existingId].material.dispose();
            delete scene3D.meshes[existingId];
        }

        if (data.vertex_count === 0) return { vertices: 0, message: 'No isosurface at this threshold' };

        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(data.vertices.flat()), 3));
        geometry.setIndex(new THREE.BufferAttribute(new Uint32Array(data.faces.flat()), 1));
        geometry.computeVertexNormals();

        const material = new THREE.MeshPhysicalMaterial({
            color: color,
            transparent: true,
            opacity: 0.3,
            side: THREE.DoubleSide,
            metalness: 0.1,
            roughness: 0.6,
            depthWrite: true,
        });

        const mesh = new THREE.Mesh(geometry, material);
        mesh.userData = { type: 'dose_isosurface', threshold: threshold };
        scene3D.scene.add(mesh);
        scene3D.meshes[existingId] = mesh;

        // Update dataTreeState — only push the entry here when called
        // from the auto-load path; loadAllIsoSurfaces() already
        // creates a richer entry (with config opacity and absolute Gy
        // label). Without the !window._suppressSingleIsoEntry guard
        // the user would see two entries per level in the data tree
        // (one from this push, one from the post-await push).
        const doseRange = data.dose_range || [0, 1];
        const dMax = doseRange[1] || 1;
        const doseScaleGy = data.dose_scale_gy || _getDoseScaleGy();
        const dMaxGy = dMax * doseScaleGy;
        const pct = dMaxGy > 0 ? Math.round((threshold / dMaxGy) * 100) : 0;
        const existingLevel = dataTreeState.planning.doseLevels.find(d => Math.abs(d.threshold - threshold) < 1e-6);
        // BUG FIX 2026-06-16: detect whether `threshold` is already
        // in absolute Gy (called from loadAllIsoSurfaces with v in Gy)
        // or a relative multiplier (called directly with 1.0, 1.5, etc.).
        // Multiplying an already-Gy value by rxGy again produced labels
        // like "14400 Gy" — the "extra 120" the user saw.
        const rxGy = _getCurrentPrescriptionGy();
        const isAlreadyGy = threshold > 5;  // 1.0×/1.5×/2.0×/4.0× are all < 5; real Gy is 50+
        const absGy = isAlreadyGy ? threshold.toFixed(0) : (threshold * rxGy).toFixed(0);
        if (!existingLevel && !window._suppressSingleIsoEntry) {
            dataTreeState.planning.doseLevels.push({
                threshold: threshold,
                thresholdGy: parseFloat(absGy),
                visible: true,
                opacity: 0.3,
                color: '#' + color.toString(16).padStart(6, '0'),
                pctLabel: `${absGy} Gy`,
            });
        }
        renderDataTree();
        fitCameraToScene();

        return { vertices: data.vertex_count, faces: data.face_count, threshold };
    } catch (e) {
        console.error('Dose isosurface failed:', e);
        return { error: e.message };
    }
}

// Load ALL isodose surface levels in one call.
// Uses config/default_params.json → display_3d.iso_dose_values_gy for
// absolute Gy thresholds (e.g. [50, 100, 145, 200, 300] Gy).
// These are the actual dose levels the user sees in the 3D viewer.
async function loadAllIsoSurfaces() {
    // Fetch config once and cache
    let display3d = window._display3dConfig;
    if (!display3d) {
        try {
            const r = await fetch(API + '/planning/config');
            if (r.ok) {
                const data = await r.json();
                display3d = data.display_3d || {};
                window._display3dConfig = display3d;
            }
        } catch (e) {
            console.warn('loadAllIsoSurfaces: failed to fetch config, using defaults', e);
        }
    }
    display3d = display3d || {};

    // iso_dose_values are RELATIVE multipliers (e.g. [1.0, 1.5, 2.0, 4.0]).
    // Multiply by prescription dose to get Gy thresholds.
    // ref.py: args.iso_dose_params['iso_dose_values'] = inLowestEnergy * np.array(iso_dose_values)
    const relValues = display3d.iso_dose_values || [1.0, 1.5, 2.0, 4.0];
    // Colors now match the 2D contour colors and the colorbar (petRainbow2 colormap).
    // 1.0×Rx (120 Gy) = green, 1.5×Rx (180 Gy) = yellow-green,
    // 2.0×Rx (240 Gy) = yellow, 4.0×Rx (480 Gy) = orange.
    const hexColors = display3d.iso_surface_colors || ['#00ff00', '#88ff00', '#ffff00', '#ff8800'];
    const opacities = display3d.iso_surface_opacities || [0.15, 0.25, 0.35, 0.45];
    const rxGy = _getCurrentPrescriptionGy();

    // Wipe any prior isosurface meshes
    Object.keys(scene3D.meshes || {}).forEach(id => {
        if (id.startsWith('dose_iso_')) {
            try {
                scene3D.scene.remove(scene3D.meshes[id]);
                scene3D.meshes[id].geometry.dispose();
                scene3D.meshes[id].material.dispose();
            } catch (_) {}
            delete scene3D.meshes[id];
        }
    });
    if (dataTreeState && dataTreeState.planning) {
        dataTreeState.planning.doseLevels = [];
    }

    // Convert relative multipliers → Gy (e.g. 1.0×120=120, 1.5×120=180)
    for (let i = 0; i < relValues.length; i++) {
        const v = parseFloat((relValues[i] * rxGy).toFixed(2));
        const absGy = v.toFixed(0);
        // Parse hex color string to RGB int
        const hexStr = hexColors[i] || hexColors[hexColors.length - 1] || '#22c55e';
        const r = parseInt(hexStr.slice(1, 3), 16);
        const g = parseInt(hexStr.slice(3, 5), 16);
        const b = parseInt(hexStr.slice(5, 7), 16);
        const color = (r << 16) | (g << 8) | b;
        const opacity = (opacities[i] !== undefined) ? opacities[i] : 0.3;
        try {
            uiDebugLog(`[IsoSurf] Loading ${v} Gy (color=${hexStr}, opacity=${opacity})...`);
            await loadDoseIsosurface(v, color);
            uiDebugLog(`[IsoSurf] ${v} Gy: mesh=${scene3D.meshes['dose_iso_'+v] ? 'loaded' : 'FAILED'}`);
            // Override the just-added mesh's opacity with the per-level
            // config value (loadDoseIsosurface uses a hard-coded 0.3).
            const mesh = scene3D.meshes[`dose_iso_${v}`];
            if (mesh) applyMeshOpacity(mesh, opacity, true);
            // Mirror into data tree with the config opacity.
            if (dataTreeState && dataTreeState.planning) {
                const existing = dataTreeState.planning.doseLevels
                    .find(d => Math.abs(d.threshold - v) < 1e-6);
                if (!existing) {
                    dataTreeState.planning.doseLevels.push({
                        threshold: v,
                        thresholdGy: parseFloat(absGy),
                        visible: true,
                        opacity,
                        color: '#' + color.toString(16).padStart(6, '0'),
                        pctLabel: `${absGy} Gy`,
                    });
                } else {
                    // Update opacity/color on the existing entry so
                    // re-running planning refreshes them.
                    existing.opacity = opacity;
                    existing.color = '#' + color.toString(16).padStart(6, '0');
                    existing.thresholdGy = parseFloat(absGy);
                    existing.pctLabel = `${absGy} Gy`;
                }
            }
        } catch (e) {
            console.warn(`loadAllIsoSurfaces: level ${v}× failed:`, e);
        }
    }
    try { renderDataTree(); } catch (_) {}
}

// Load the CTV tumor mesh + any non-traversable OAR meshes into the
// 3D viewer, in parallel. The user explicitly wants these visible
// after planning so they have a target volume to compare the
// isosurface cloud against. Uses the modern addMeshToScene path
// (addMeshToScene initializes the scene if needed and mirrors into
// the data tree).
const _segmentationMeshPrewarm = {
    tasks: new Map(),
    statusEl: null,
    activeRuns: 0,
};

function _meshTaskKey(source, labelId, smoothing = 1) {
    return `${source}:${labelId}:${smoothing}`;
}

function _sceneHasMesh(id) {
    return !!(typeof scene3D !== 'undefined' && scene3D.meshes && scene3D.meshes[id]);
}

function _parseTreeColorValue(color, fallback = 0xff4444) {
    if (!color) return fallback;
    if (typeof color === 'number') return color;
    const c = String(color);
    if (c.startsWith('#') && (c.length === 7 || c.length === 4)) {
        if (c.length === 7) return parseInt(c.slice(1), 16);
        return parseInt(c.slice(1).split('').map(ch => ch + ch).join(''), 16);
    }
    const m = c.match(/(\d+)/g);
    if (m && m.length >= 3) return (parseInt(m[0]) << 16) | (parseInt(m[1]) << 8) | parseInt(m[2]);
    return fallback;
}

function _getNonTraversableOarMeshIds(ctvLabelIds) {
    const ctvIdSet = new Set(ctvLabelIds || []);
    const ids = new Set();
    if (dataTreeState && Array.isArray(dataTreeState.organs)) {
        dataTreeState.organs
            .filter(o => o.category === 'non_traversable'
                && o.labelId !== undefined
                && !ctvIdSet.has(o.labelId)
                && !(o.source === 'ctv'))
            .forEach(o => ids.add(o.labelId));
    }
    if (ids.size === 0) {
        console.warn('[3D meshes] No non-traversable OARs found in dataTreeState.organs — skipping OAR mesh loading');
    }
    return [...ids];
}

function _setMeshPrewarmStatus(text, show = true) {
    let el = _segmentationMeshPrewarm.statusEl;
    if (!show) {
        if (el) {
            try { el.remove(); } catch (_) {}
            _segmentationMeshPrewarm.statusEl = null;
        }
        return;
    }
    if (!el) {
        el = document.createElement('div');
        el.id = 'meshPrewarmStatus';
        el.style.cssText = 'position:fixed;bottom:60px;right:20px;background:rgba(15,23,42,0.9);color:#94a3b8;padding:8px 16px;border-radius:8px;font-size:0.75rem;z-index:9999;display:flex;align-items:center;gap:8px;';
        el.innerHTML = '<div class="spinner-ring" style="width:12px;height:12px;border-width:2px;"></div><span></span>';
        document.body.appendChild(el);
        _segmentationMeshPrewarm.statusEl = el;
    }
    const span = el.querySelector('span');
    if (span) span.textContent = text || '3D reconstruction running...';
}

// Check whether a label ID exists in the currently loaded segmentation mask.
// Uses a cached Set attached to the typed array for O(1) repeat lookups.
function _labelIdInMask(labelData, labelId) {
    if (!labelData || labelData.length === 0) return false;
    if (!labelData._uniqueLabelSet) {
        labelData._uniqueLabelSet = new Set(labelData);
    }
    return labelData._uniqueLabelSet.has(labelId);
}

async function _fetchAndAddOrganMesh({ labelId, source, organId, label, color, opacity, force = false, smoothing = 1 }) {
    if (labelId === undefined || labelId === null || !source || !organId) return { status: 'invalid' };
    if (!force && _sceneHasMesh(organId)) return { status: 'exists', id: organId };

    // Validate the requested label exists in the currently loaded segmentation mask.
    // This prevents 400 errors from the backend when the data tree contains organs
    // whose label IDs are not present in the actual volume.
    const labelData = source === 'ctv' ? ctvLabelData : oarLabelData;
    if (!_labelIdInMask(labelData, labelId)) {
        return { status: 'missing_label', id: organId };
    }

    const key = _meshTaskKey(source, labelId, smoothing);
    if (_segmentationMeshPrewarm.tasks.has(key)) {
        return _segmentationMeshPrewarm.tasks.get(key);
    }

    const task = (async () => {
        try {
            const res = await fetch(API + '/viewer/3d_mask', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ label_id: labelId, source, smoothing }),
            });
            if (!res.ok) return { status: 'http', code: res.status, id: organId };
            const data = await res.json();
            if (!data || !data.success || !data.vertex_count) return { status: 'empty', id: organId };
            if (data.face_count > 500000) {
                console.warn(`[3D mesh] ${organId}: skipping (${data.face_count} faces > 100K limit)`);
                return { status: 'too_large', id: organId };
            }
            data.color = color;
            data.organ_id = organId;
            data.label = label || organId;
            data.source = source;
            if (typeof opacity === 'number') data.opacity = opacity;
            addMeshToScene(data);
            return { status: data.cached ? 'cached' : 'loaded', id: organId };
        } catch (e) {
            console.warn(`[3D mesh] ${organId} failed:`, e);
            return { status: 'error', id: organId, error: e };
        } finally {
            _segmentationMeshPrewarm.tasks.delete(key);
        }
    })();
    _segmentationMeshPrewarm.tasks.set(key, task);
    return task;
}

async function prewarmSegmentationMeshes(kind = 'all', opts = {}) {
    if (!state.ctLoaded && !state.ctPath) return;
    init3DScene();

    const includeCTV = kind === 'ctv' || kind === 'oar' || kind === 'all';
    const includeOAR = kind === 'oar' || kind === 'all';
    const showStatus = opts.showStatus !== false;
    const force = opts.force === true;
    const ctvLabelIds = getCtvMeshLabelIds();
    const promises = [];

    _segmentationMeshPrewarm.activeRuns += 1;
    if (showStatus) _setMeshPrewarmStatus(kind === 'ctv' ? '3D CTV reconstruction started...' : '3D OAR reconstruction running...');

    try {
        if (includeCTV && ctvLabelData) {
            for (const lid of ctvLabelIds) {
                const c = labelColorLUT && labelColorLUT[lid];
                promises.push(_fetchAndAddOrganMesh({
                    labelId: lid,
                    source: 'ctv',
                    organId: `ctv_${lid}`,
                    label: (window._ctvLabelMap || {})[lid] || `CTV Label ${lid}`,
                    color: c ? ((c[0] << 16) | (c[1] << 8) | c[2]) : 0xff6b6b,
                    force,
                }));
            }
        }

        if (includeOAR && oarLabelData) {
            const allOarIds = opts.allOAR
                ? [...new Set((dataTreeState.organs || [])
                    .filter(o => o.labelId !== undefined && o.labelId !== null && !ctvLabelIds.includes(o.labelId))
                    .map(o => o.labelId))]
                : [];
            const oarIds = allOarIds.length ? allOarIds : _getNonTraversableOarMeshIds(ctvLabelIds);
            const batchSize = opts.batchSize || 3;
            for (let i = 0; i < oarIds.length; i += batchSize) {
                const batch = oarIds.slice(i, i + batchSize).map(lid => {
                    const organ = (dataTreeState.organs || []).find(o => o.labelId === lid);
                    return _fetchAndAddOrganMesh({
                        labelId: lid,
                        source: 'oar',
                        organId: `organ_${lid}`,
                        label: (organ && (organ.label || organ.name)) || `OAR ${lid}`,
                        color: _parseTreeColorValue(organ && organ.color, 0xff4444),
                        opacity: organ && typeof organ.opacity === 'number' ? organ.opacity : undefined,
                        force,
                    });
                });
                promises.push(Promise.all(batch));
                await Promise.all(batch);
                if (showStatus) _setMeshPrewarmStatus(`3D OAR reconstruction ${Math.min(i + batchSize, oarIds.length)}/${oarIds.length}`);
            }
        }

        await Promise.all(promises);
        if (scene3D.renderer && scene3D.scene && scene3D.camera) fitCameraToScene();
    } finally {
        _segmentationMeshPrewarm.activeRuns = Math.max(0, _segmentationMeshPrewarm.activeRuns - 1);
        if (_segmentationMeshPrewarm.activeRuns === 0) {
            setTimeout(() => {
                if (_segmentationMeshPrewarm.activeRuns === 0) _setMeshPrewarmStatus('', false);
            }, 600);
        }
    }
}

function startSegmentationMeshPrewarm(kind = 'all') {
    if (!state.ctLoaded && !state.ctPath) return;
    setTimeout(() => {
        prewarmSegmentationMeshes(kind, { showStatus: true }).catch(e => {
            console.warn('[3D prewarm] failed:', e);
            _setMeshPrewarmStatus('', false);
        });
    }, 0);
}

async function loadCTVAndObstacleMeshes() {
    await prewarmSegmentationMeshes('all', { showStatus: false, batchSize: 3 });
    uiDebugLog(`[loadCTVAndObstacle] Meshes ready. Total scene meshes: ${Object.keys(scene3D.meshes).length}`);
}

// Load dose distribution as 2D overlay on CT slices
let _doseOverlayData = null;
let _doseOverlayVisible = false;
let _doseOverlayOpacity = 0.5;

// The backend returns the checkpoint calibration with each dose payload. Keep a
// documented fallback for older servers, but never scatter literal conversion
// factors through the viewer code.
const DEFAULT_DOSE_SCALE_GY = 120.0;

function _getDoseScaleGy() {
    const candidates = [
        state?.doseOverlay?.doseScaleGy,
        state?.metrics?.dose_scale_gy,
        window._display3dConfig?._doseScaleGy,
    ];
    for (const value of candidates) {
        const parsed = Number(value);
        if (Number.isFinite(parsed) && parsed > 0) return parsed;
    }
    return DEFAULT_DOSE_SCALE_GY;
}

function _getCurrentPrescriptionGy() {
    const explicitReport = Number(window.reportForm?.planning?.prescriptionGy);
    if (Number.isFinite(explicitReport) && explicitReport > 0) return explicitReport;

    const metricGy = Number(state?.metrics?.prescription_gy);
    if (Number.isFinite(metricGy) && metricGy > 0) return metricGy;

    const configuredGy = Number(window._display3dConfig?._prescriptionGy);
    if (Number.isFinite(configuredGy) && configuredGy > 0) return configuredGy;

    const scale = _getDoseScaleGy();
    const normalizedMetric = Number(state?.metrics?.prescribed_dose);
    if (Number.isFinite(normalizedMetric) && normalizedMetric > 0) return normalizedMetric * scale;

    const normalizedInput = Number(document.getElementById('inLowestEnergy')?.value);
    if (Number.isFinite(normalizedInput) && normalizedInput > 0) return normalizedInput * scale;
    return scale;
}

// Colorbar display range, in Gy. Restored to 0–1000 Gy to match clinical
// dose display (D2 can reach 2500+ Gy in LDR; saturating at 200 Gy made
// most of the colorbar show the same top color).
const COLORBAR_MIN_GY = 0.0;
const COLORBAR_MAX_GY = 1000.0;

// Dose-surface color window used by all colorbars and overlays. This later
// declaration is the canonical colormap for all dose overlays.
function _petRainbow2(val) {
    const v = Math.min(1, Math.max(0, val));
    const stops = [
        [0.000, [0, 0, 0]],         // pure black (near-zero dose)
        [0.030, [10, 0, 25]],       // very dark purple at 30 Gy
        [0.050, [50, 10, 100]],     // dark purple at 50 Gy
        [0.070, [150, 30, 200]],    // vibrant purple at 70 Gy
        [0.080, [30, 50, 220]],     // blue at 80 Gy
        [0.100, [0, 170, 230]],     // cyan at 100 Gy
        [0.150, [30, 200, 80]],     // green at 150 Gy
        [0.200, [240, 220, 0]],     // yellow at 200 Gy
        [0.350, [255, 120, 0]],     // orange at 350 Gy
        [0.550, [220, 0, 0]],       // red at 550 Gy
        [0.750, [130, 0, 0]],       // dark red at 750 Gy
        [1.000, [60, 0, 0]],        // very dark red (top)
    ];
    for (let i = 1; i < stops.length; i++) {
        const [p1, c1] = stops[i];
        const [p0, c0] = stops[i - 1];
        if (v <= p1) {
            const s = (v - p0) / Math.max(0.0001, p1 - p0);
            return [
                Math.round(c0[0] + (c1[0] - c0[0]) * s),
                Math.round(c0[1] + (c1[1] - c0[1]) * s),
                Math.round(c0[2] + (c1[2] - c0[2]) * s),
            ];
        }
    }
    return [255, 255, 255];
}

// Dose-surface variant: clips the black low-dose range so the bottom
// starts at vibrant purple. Used for 3D mesh vertex colors and the
// 3D colorbar, where black would look like missing data.
function _petRainbowDoseSurface(val) {
    const CLIP_T = 0.070; // vibrant purple at 70 Gy — skip black/dark range for dose surface
    return _petRainbow2(CLIP_T + Math.min(1, Math.max(0, val)) * (1 - CLIP_T));
}

function _doseDisplayT(doseGy) {
    return Math.max(0, Math.min(1, (Number(doseGy || 0) - COLORBAR_MIN_GY) / (COLORBAR_MAX_GY - COLORBAR_MIN_GY)));
}

function _doseGyToRgb(doseGy) {
    return _petRainbow2(_doseDisplayT(doseGy));
}

function _doseNormToRgb(doseNorm) {
    return _doseGyToRgb(Number(doseNorm || 0) * _getDoseScaleGy());
}

function _doseColorbarLabelSpecs(pixelHeight = 512) {
    const dense = pixelHeight >= 300;
    const values = dense ? [180, 160, 140, 120, 100, 80, 60, 40, 20] : [150, 100, 50];
    return [
        { pct: 0, label: `>${COLORBAR_MAX_GY.toFixed(1)} Gy`, major: true },
        ...values.map(v => ({
            pct: (1 - _doseDisplayT(v)) * 100,
            label: `${v.toFixed(1)} Gy`,
            major: v % 40 === 0,
        })),
        { pct: 100, label: `<${COLORBAR_MIN_GY.toFixed(1)} Gy`, major: true },
    ];
}

function _drawDoseColorbarGradient(ctx, w, h) {
    for (let y = 0; y < h; y++) {
        const val = 1 - y / Math.max(1, h - 1);
        const [r, g, b] = _petRainbow2(val);
        ctx.fillStyle = `rgb(${r},${g},${b})`;
        ctx.fillRect(0, y, w, 1);
    }
}

function _labelClassForDoseColorbarPosition(pos) {
    return pos === 'top' ? 'doseColorbarMax'
        : pos === 'bottom' ? 'doseColorbarMin'
        : pos === '50%' ? 'doseColorbarMid'
        : pos === '25%' ? 'doseColorbarQ1'
        : 'doseColorbarQ3';
}

// Update all 3 colorbars (axial/sagittal/coronal) in lock-step.
// doseMinNorm, doseMaxNorm: dose range in NORMALIZED units (raw CNN output).
// They are converted to Gy here so the labels show real physical dose.
// The colorbar always spans [COLORBAR_MIN_GY, COLORBAR_MAX_GY] (= 0–1000 Gy).
// Dose values above 1000 Gy are saturated to the top colormap color.
function updateDoseColorbars(visible, doseMinNorm, doseMaxNorm) {
    document.querySelectorAll('.dose-colorbar').forEach(cb => {
        const shouldShow = cb.id === 'doseColorbar3D' ? (visible && !!state.doseTexture?.enabled) : visible;
        cb.style.display = shouldShow ? 'block' : 'none';
    });
    if (!visible) return;

    // Always use the fixed 0-1000 Gy display range.
    const dMinGy = COLORBAR_MIN_GY;
    const dMaxGy = COLORBAR_MAX_GY;

    // Labels every 200 Gy: 0, 200, 400, 600, 800, 1000
    const tickGy = [0, 200, 400, 600, 800, dMaxGy];
    const tickLabels = tickGy.map(v => v.toFixed(0) + ' Gy');
    const tickPos = ['doseColorbarMin', 'doseColorbarTick', 'doseColorbarTick', 'doseColorbarTick', 'doseColorbarTick', 'doseColorbarMax'];

    // Set each label by matching data-value attribute to ensure correct position.
    // Skip the 3D colorbar — it has its own 0-200 Gy labels set by update3DColorbar().
    tickGy.forEach((gy, i) => {
        const cls = tickPos[i];
        if (cls === 'doseColorbarTick') {
            document.querySelectorAll('.dose-colorbar:not(#doseColorbar3D) .doseColorbarTick').forEach(el => {
                if (parseFloat(el.getAttribute('data-value') || '') === gy) {
                    el.textContent = tickLabels[i];
                }
            });
        } else {
            document.querySelectorAll('.dose-colorbar:not(#doseColorbar3D) .' + cls).forEach(el => {
                el.textContent = tickLabels[i];
            });
        }
    });

    // Render PETrainbow2 gradient on 2D viewer colorbar canvases only.
    // The 3D colorbar is handled separately by update3DColorbar() which
    // uses _petRainbowDoseSurface (no black range).
    document.querySelectorAll('.dose-colorbar:not(#doseColorbar3D) .colorbarCanvas').forEach(canvas => {
        const ctx = canvas.getContext('2d');
        const h = canvas.height;
        const w = canvas.width;
        for (let y = 0; y < h; y++) {
            // y=0 (top) → max (val=1); y=h-1 (bottom) → min (val=0)
            const val = 1 - y / (h - 1);
            const [r, g, b] = _petRainbow2(val);
            ctx.fillStyle = `rgb(${r},${g},${b})`;
            ctx.fillRect(0, y, w, 1);
        }
    });
}

// Update 3D viewer dose colorbar (shown only when dose surface mode is active)
// This reuses the same gradient and labels as the 2D viewers' colorbars.
function update3DColorbar(visible) {
    const colorbar3D = document.getElementById('doseColorbar3D');
    if (!colorbar3D) return;

    colorbar3D.style.display = visible ? 'block' : 'none';
    if (!visible) return;

    // Render the gradient on the 3D colorbar canvas
    const canvas = colorbar3D.querySelector('.colorbarCanvas');
    if (canvas) {
        const ctx = canvas.getContext('2d');
        const h = canvas.height;
        const w = canvas.width;
        for (let y = 0; y < h; y++) {
            // y=0 (top) → max (val=1); y=h-1 (bottom) → min (val=0)
            const val = 1 - y / (h - 1);
            const [r, g, b] = _petRainbowDoseSurface(val);
            ctx.fillStyle = `rgb(${r},${g},${b})`;
            ctx.fillRect(0, y, w, 1);
        }
    }

    // Set 3D colorbar labels to 0-200 Gy range (independent from 2D colorbars).
    // Match by data-value to avoid overwriting all ticks with the last value.
    const d3DTicks = [
        { pos: 'doseColorbarMax', val: 200 },
        { pos: 'doseColorbarTick', val: 160, dataVal: 160 },
        { pos: 'doseColorbarTick', val: 120, dataVal: 120 },
        { pos: 'doseColorbarTick', val: 80, dataVal: 80 },
        { pos: 'doseColorbarTick', val: 40, dataVal: 40 },
        { pos: 'doseColorbarMin', val: 0 },
    ];
    d3DTicks.forEach(({ pos, val, dataVal }) => {
        const label = val.toFixed(0) + ' Gy';
        if (dataVal !== undefined) {
            colorbar3D.querySelectorAll('.' + pos).forEach(el => {
                if (parseFloat(el.getAttribute('data-value') || '') === dataVal) {
                    el.textContent = label;
                }
            });
        } else {
            colorbar3D.querySelectorAll('.' + pos).forEach(el => {
                el.textContent = label;
            });
        }
    });
}

async function loadDoseOverlay() {
    try {
        const res = await fetch(API + '/planning/dose_overlay');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Failed to load dose overlay');

        // Store metadata; slices will be fetched on demand
        // doseMin / doseMax are in NORMALIZED units (CNN output). They are
        // converted to Gy only for display labels.
        if (state.doseTexture) {
            state.doseTexture.rawAxialSlices = {};
            state.doseTexture.rawAxialSlicePromises = {};
        }
        // Preserve user-set opacity when reloading (e.g. after manual
        // recompute or when Dose Surface triggers a reload). Default to
        // 0.5 only on the very first load.
        const prevOpacity = state.doseOverlay?.opacity;
        state.doseOverlay = {
            shape: data.dose_shape,
            doseMin: data.dose_min,
            doseMax: data.dose_max,
            doseUnits: data.dose_units || 'normalized_model_output',
            doseScaleGy: data.dose_scale_gy || _getDoseScaleGy(),
            visible: true,
            opacity: Number.isFinite(prevOpacity) ? prevOpacity : 0.5,
            slices: {},  // Cache: {axis_index: sliceData}
            maxSlice: {
                axial: (data.dose_shape?.[0] || 200) - 1,
                sagittal: (data.dose_shape?.[2] || 200) - 1,
                coronal: (data.dose_shape?.[1] || 200) - 1,
            },
            peakVoxel: data.peak_voxel ? {
                ...data.peak_voxel,
                raw_z: data.peak_voxel.z,
                z: ((data.dose_shape?.[0] || 0) > 0)
                    ? ((data.dose_shape[0] - 1) - data.peak_voxel.z)
                    : data.peak_voxel.z,
            } : null,
        };

        renderDataTree();

        // Show colorbars in ALL 3 2D viewers (axial, sagittal, coronal).
        // Values are converted with the backend-provided checkpoint scale so labels are
        // linear in real physical dose.
        updateDoseColorbars(true, data.dose_min, data.dose_max);

        // Trigger re-render of current slices to show overlay
        updateSlice('axial', state.slices.axial);
        updateSlice('coronal', state.slices.coronal);
        updateSlice('sagittal', state.slices.sagittal);
        return { shape: data.dose_shape, range: [data.dose_min, data.dose_max] };
    } catch (e) {
        console.error('Dose overlay failed:', e);
        return { error: e.message };
    }
}

// Fetch a dose overlay slice (cached)
// Request-version counter for dose overlay fetches. When the user slides
// quickly, multiple async fetches race; the slower one might come back
// AFTER a faster one and paint stale data on the new slice, causing
// visible flicker. We tag each fetch with a monotonically increasing
// version, and `renderDoseOverlay` only paints if the response's version
// still matches the latest one requested.
let _doseOverlayRequestVersion = 0;
// AbortControllers keyed by cacheKey. Cancelling duplicate requests for the
// same slice prevents browser socket-buffer exhaustion (ERR_NO_BUFFER_SPACE)
// when the user scrolls rapidly, while still allowing concurrent preloads
// for different slices.
const _doseOverlayAbortControllers = new Map();

async function fetchDoseOverlaySlice(axis, sliceIndex) {
    if (!state.doseOverlay) { uiDebugLog('[dose] fetch skipped: no doseOverlay state'); return null; }
    const cacheKey = `${axis}_${sliceIndex}`;
    if (state.doseOverlay.slices[cacheKey]) return state.doseOverlay.slices[cacheKey];

    const myVersion = ++_doseOverlayRequestVersion;
    const existingCtrl = _doseOverlayAbortControllers.get(cacheKey);
    if (existingCtrl) {
        try { existingCtrl.abort(); } catch (_) {}
    }
    const controller = new AbortController();
    _doseOverlayAbortControllers.set(cacheKey, controller);
    try {
        const axialMax = state.doseOverlay.maxSlice?.axial;
        const requestSliceIndex = axis === 'axial' && Number.isFinite(axialMax)
            ? Math.max(0, Math.min(axialMax, axialMax - sliceIndex))
            : sliceIndex;
        const res = await fetch(API + '/planning/dose_overlay_slice', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ axis, slice_index: requestSliceIndex }),
            signal: controller.signal,
        });
        if (controller.signal.aborted) return null;
        if (!res.ok) { uiDebugLog(`[dose] fetch HTTP ${res.status} for ${cacheKey}`); return null; }
        const data = await res.json();
        if (!data.success) { uiDebugLog(`[dose] fetch failed: ${data.error} for ${cacheKey}`); return null; }
        // If a newer request was issued while this one was in flight,
        // cache the data but don't render (stale slice).
        if (myVersion !== _doseOverlayRequestVersion) {
            state.doseOverlay.slices[cacheKey] = data.slice;
            return data.slice;
        }
        state.doseOverlay.slices[cacheKey] = data.slice;
        return data.slice;
    } catch (e) {
        if (e && e.name === 'AbortError') return null;
        return null;
    } finally {
        if (_doseOverlayAbortControllers.get(cacheKey) === controller) {
            _doseOverlayAbortControllers.delete(cacheKey);
        }
    }
}

// Preload adjacent dose slices so scrubbing doesn't flicker.
// Fires-and-forgets ±PRELOAD_RANGE slices around the current position.
let _dosePreloadTimer = null;
function preloadDoseSlices(axis, centerSlice) {
    if (!state.doseOverlay || !state.doseOverlay.visible) return;
    if (_dosePreloadTimer) clearTimeout(_dosePreloadTimer);
    _dosePreloadTimer = setTimeout(() => {
        const PRELOAD_RANGE = 10;
        const maxSlice = state.doseOverlay.maxSlice?.[axis] || 200;
        for (let d = 1; d <= PRELOAD_RANGE; d++) {
            const fwd = centerSlice + d;
            const bwd = centerSlice - d;
            if (fwd <= maxSlice) fetchDoseOverlaySlice(axis, fwd).catch(() => {});
            if (bwd >= 0) fetchDoseOverlaySlice(axis, bwd).catch(() => {});
        }
    }, 30); // debounce: don't fire on every pixel of scrub
}

// Render dose overlay on a canvas for the current slice
// Render dose overlay on top of CT slice canvas
// Render dose overlay onto a SEPARATE canvas layer (not the CT canvas).
// This prevents the CT's putImageData from clearing the old dose.
function renderDoseOverlayOnLayer(doseCanvas, axis, sliceIndex, sliceData) {
    if (!state.doseOverlay || !state.doseOverlay.visible || !sliceData) return;
    // NOTE: staleness guard removed — the caller (renderDoseForCurrentSlice)
    // already ensures sliceIndex matches state.slices[axis]. Keeping the
    // guard caused a race condition where async fetch callbacks were
    // silently skipped when the user scrolled rapidly.

    const ctx = doseCanvas.getContext('2d');
    const w = doseCanvas.width;
    const h = doseCanvas.height;
    const rows = sliceData.length;
    const cols = sliceData[0]?.length || 0;
    if (rows === 0 || cols === 0) return;

    const opacity = state.doseOverlay.opacity;
    const dMinGy = COLORBAR_MIN_GY;
    const dMaxGy = COLORBAR_MAX_GY;

    const tmpCanvas = document.createElement('canvas');
    tmpCanvas.width = w;
    tmpCanvas.height = h;
    const tmpCtx = tmpCanvas.getContext('2d');
    const imageData = tmpCtx.createImageData(w, h);
    const scaleX = w / cols;
    const scaleY = h / rows;
    const colormap = (val) => _petRainbow2(val);

    for (let py = 0; py < h; py++) {
        for (let px = 0; px < w; px++) {
            const sx = Math.min(Math.floor(px / scaleX), cols - 1);
            const sy = Math.min(Math.floor(py / scaleY), rows - 1);
            const val = sliceData[sy][sx];
            const valGy = val * _getDoseScaleGy();
            const normalized = (valGy - dMinGy) / (dMaxGy - dMinGy);
            const [r, g, b] = colormap(Math.min(1, Math.max(0, normalized)));
            const idx = (py * w + px) * 4;
            imageData.data[idx] = r;
            imageData.data[idx + 1] = g;
            imageData.data[idx + 2] = b;
            imageData.data[idx + 3] = Math.floor(opacity * 255);
        }
    }
    tmpCtx.putImageData(imageData, 0, 0);
    // Paint to a temp canvas first, then swap — avoids the brief
    // blank frame that ctx.clearRect alone would cause.
    ctx.clearRect(0, 0, w, h);
    ctx.drawImage(tmpCanvas, 0, 0);
}

function toggleDoseOverlayVisibility() {
    if (!state.doseOverlay) return;
    state.doseOverlay.visible = !state.doseOverlay.visible;
    renderDataTree();

    // Show/hide colorbars in all 3 2D viewers (axial, sagittal, coronal).
    // Labels are in Gy; values are linear (0 → max), 5 evenly-spaced ticks.
    updateDoseColorbars(state.doseOverlay.visible, state.doseOverlay.doseMin, state.doseOverlay.doseMax);

    // Show/hide contour canvases
    ['axial', 'coronal', 'sagittal'].forEach(axis => {
        const contourCanvas = document.getElementById('contourCanvas' + capitalize(axis));
        if (contourCanvas) {
            contourCanvas.style.display = state.doseOverlay.visible ? 'block' : 'none';
            if (!state.doseOverlay.visible) {
                const ctx = contourCanvas.getContext('2d');
                ctx.clearRect(0, 0, contourCanvas.width, contourCanvas.height);
            }
        }
    });

    // Trigger re-render of current slices
    updateSlice('axial', state.slices.axial);
    updateSlice('coronal', state.slices.coronal);
    updateSlice('sagittal', state.slices.sagittal);
}

function setDoseOverlayOpacity(val) {
    if (!state.doseOverlay) return;
    state.doseOverlay.opacity = val / 100;
    // Update label
    const label = document.getElementById('doseOpacityVal');
    if (label) label.textContent = val + '%';
    // Keep the data tree slider in sync so it doesn't jump on the next render.
    const treeSlider = document.querySelector('[data-item="dose_overlay"] .opacity-slider');
    if (treeSlider) treeSlider.value = val;
    // Force re-render by clearing the "last rendered" tracker
    // (otherwise the cache check skips re-render when slice hasn't changed)
    _doseLastRendered.axial = -1;
    _doseLastRendered.sagittal = -1;
    _doseLastRendered.coronal = -1;
    // Re-render current slices
    updateSlice('axial', state.slices.axial);
    updateSlice('coronal', state.slices.coronal);
    updateSlice('sagittal', state.slices.sagittal);
}

// ============ DOSE CONTOUR LINES (iso-dose lines on 2D viewers) ============
// Cache for contour data: { "axis_sliceIndex": contourData }
const _doseContourCache = {};

async function fetchDoseContourSlice(axis, sliceIndex) {
    const cacheKey = `${axis}_${sliceIndex}`;
    if (_doseContourCache[cacheKey]) return _doseContourCache[cacheKey];

    try {
        const axialMax = state.doseOverlay?.maxSlice?.axial;
        const requestSliceIndex = axis === 'axial' && Number.isFinite(axialMax)
            ? Math.max(0, Math.min(axialMax, axialMax - sliceIndex))
            : sliceIndex;
        const res = await fetch(API + '/planning/dose_contour_slice', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ axis, slice_index: requestSliceIndex }),
        });
        if (!res.ok) return null;
        const data = await res.json();
        if (!data.success) return null;
        _doseContourCache[cacheKey] = data;
        return data;
    } catch (e) {
        return null;
    }
}

function renderDoseContourOnCanvas(canvas, axis, sliceIndex) {
    const cacheKey = `${axis}_${sliceIndex}`;
    const data = _doseContourCache[cacheKey];

    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    if (!data || !data.contours || data.contours.length === 0) return;

    // Coordinate mapping from dose slice to canvas.
    // The server returns slice_shape = [rows, cols] in dose volume
    // coordinates. The CT canvas, however, may have a DIFFERENT
    // height: coronal/sagittal views resample Z to match X/Y spacing
    // (Z→displayY = spacingZ / spacingX * Z), so canvas height ≠ Z.
    //
    // For each axis we recompute the dose-slice row count the canvas
    // corresponds to so the scaleY is exact. Without this (2026-06-16
    // user bug) the contour lines landed in the wrong position on
    // coronal/sagittal views because we divided by the un-resampled
    // Z dimension.
    const sliceShape = data.slice_shape || [];
    if (sliceShape.length !== 2 || sliceShape[0] === 0 || sliceShape[1] === 0) return;
    let doseRows, doseCols;
    if (axis === 'axial') {
        doseRows = sliceShape[0];  // = Y
        doseCols = sliceShape[1];  // = X
    } else if (axis === 'coronal') {
        doseRows = sliceShape[0];  // = Z (slice_2d shape [Z, X])
        doseCols = sliceShape[1];  // = X
    } else {  // sagittal
        doseRows = sliceShape[0];  // = Z (slice_2d shape [Z, Y])
        doseCols = sliceShape[1];  // = Y
    }

    const scaleX = w / doseCols;
    const scaleY = h / doseRows;

    // Filter contours based on data tree visibility state.
    // Only draw contours whose corresponding dose level is visible in the data tree.
    const doseLevels = dataTreeState.planning.doseLevels || [];
    const visibleContours = data.contours.filter(contour => {
        // Match contour level (Gy) with doseLevels threshold
        const level = contour.level || contour.level_rel;
        if (!level) return true;  // If no level info, draw it
        const doseLevel = doseLevels.find(d => Math.abs(d.threshold - level) < 1 || Math.abs(d.thresholdGy - level) < 1);
        // If not found in doseLevels, draw it (might be a new level)
        // Otherwise, only draw if visible
        return !doseLevel || doseLevel.visible !== false;
    });

    // Draw contour lines
    visibleContours.forEach(contour => {
        const color = contour.color;
        const opacity = contour.opacity ?? 0.7;
        const r = Math.round(color[0] * 255);
        const g = Math.round(color[1] * 255);
        const b = Math.round(color[2] * 255);

        ctx.strokeStyle = `rgba(${r},${g},${b},${Math.min(1, opacity + 0.2)})`;  // Boost opacity
        ctx.lineWidth = 2.5;  // Increased from 1.5 to 2.5 for better visibility
        ctx.setLineDash([]);

        contour.lines.forEach(line => {
            if (line.length < 2) return;
            ctx.beginPath();
            for (let i = 0; i < line.length; i++) {
                const [row, col] = line[i];
                const x = col * scaleX;
                const y = row * scaleY;
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            }
            ctx.stroke();
        });

        // Add label at the midpoint of the longest line
        let longestLine = contour.lines[0];
        contour.lines.forEach(line => {
            if (line.length > longestLine.length) longestLine = line;
        });
        if (longestLine.length > 10) {
            const midIdx = Math.floor(longestLine.length / 2);
            const [row, col] = longestLine[midIdx];
            const x = col * scaleX;
            const y = row * scaleY;

            ctx.font = '10px Inter, sans-serif';
            ctx.fillStyle = `rgba(${r},${g},${b},0.9)`;
            ctx.strokeStyle = 'rgba(0,0,0,0.6)';
            ctx.lineWidth = 2;
            const label = Number.isFinite(contour.level) ? contour.level.toFixed(1) : '';
            if (!label) return;
            ctx.strokeText(label, x + 3, y - 3);
            ctx.fillText(label, x + 3, y - 3);
        }
    });
}

// Trigger contour rendering when dose overlay is visible
function triggerDoseContourRender(axis, sliceIndex) {
    if (!state.doseOverlay || !state.doseOverlay.visible) return;

    // Create or get the contour canvas up-front (synchronously) so
    // it exists from the first render, even before the async fetch
    // completes. Without this (2026-06-16 user feedback) the contour
    // canvas was created INSIDE the .then() callback, so during the
    // round-trip the user saw a blank slice with the dose contours
    // missing — and the canvas was missing entirely on the very
    // first slider drag.
    const canvasId = 'contourCanvas' + capitalize(axis);
    let canvas = document.getElementById(canvasId);
    if (!canvas) {
        const sliceCanvas = document.getElementById('sliceCanvas' + capitalize(axis));
        if (!sliceCanvas) return;
        const parent = sliceCanvas.parentElement;
        canvas = document.createElement('canvas');
        canvas.id = canvasId;
        canvas.style.cssText = 'position:absolute;inset:0;pointer-events:none;display:block;';
        parent.appendChild(canvas);
    }

    const sliceCanvas = document.getElementById('sliceCanvas' + capitalize(axis));
    if (sliceCanvas) _syncLayerToSliceCanvas(axis, canvas, 7);
    canvas.dataset.axis = axis;
    canvas.dataset.sliceIndex = String(sliceIndex);
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // 1) Synchronous draw if cached. This is the path that fixes
    //    the "drag → blank → wait for fetch → reappear" bug: after
    //    the user has scrubbed past a slice once, the contour is
    //    cached locally and the next visit renders with zero
    //    network latency.
    const cacheKey = `${axis}_${sliceIndex}`;
    const cached = _doseContourCache[cacheKey];
    if (cached) {
        renderDoseContourOnCanvas(canvas, axis, sliceIndex);
        return;
    }

    // 2) Async fetch + draw. The canvas was already cleared for the
    //    requested slice above. Only draw if the user is still on the
    //    same slice when the response returns; otherwise stale contour
    //    lines from a previous slice would remain visible.
    fetchDoseContourSlice(axis, sliceIndex).then(data => {
        // Make sure we're still on the same slice the user requested
        // (the slider may have moved while the fetch was in flight).
        if (state.slices[axis] !== sliceIndex) return;
        if (canvas.dataset.axis !== axis || canvas.dataset.sliceIndex !== String(sliceIndex)) return;
        renderDoseContourOnCanvas(canvas, axis, sliceIndex);
    });
    // 3) Pre-fetch ±N neighbors so scrubbing doesn't keep
    //    triggering round-trips.
    preloadDoseContourSlices(axis, sliceIndex);
}

// Pre-load neighbors of the current contour slice so the slider
// drag is smooth. Mirror of preloadDoseSlices() for the dose
// overlay path. Without this, every slider tick waits ~150 ms for
// a network round-trip and the contour appears to "vanish then
// come back". Fetches are fire-and-forget; failures are silent.
const _doseContourPreloadTimer = { v: null };
function preloadDoseContourSlices(axis, centerSlice) {
    if (!state.doseOverlay || !state.doseOverlay.visible) return;
    if (_doseContourPreloadTimer.v) clearTimeout(_doseContourPreloadTimer.v);
    _doseContourPreloadTimer.v = setTimeout(() => {
        const PRELOAD_RANGE = 8;
        const maxSlice = state.doseOverlay.maxSlice?.[axis] || 200;
        for (let d = 1; d <= PRELOAD_RANGE; d++) {
            const fwd = centerSlice + d;
            const bwd = centerSlice - d;
            const kf = `${axis}_${fwd}`;
            const kb = `${axis}_${bwd}`;
            if (fwd <= maxSlice && !_doseContourCache[kf]) {
                fetchDoseContourSlice(axis, fwd).catch(() => {});
            }
            if (bwd >= 0 && !_doseContourCache[kb]) {
                fetchDoseContourSlice(axis, bwd).catch(() => {});
            }
        }
    }, 50);
}

function highlightSeed(seedId) {
    // Reset all seeds to default color
    Object.entries(scene3D.meshes).forEach(([id, mesh]) => {
        if (id.startsWith('seed_') && mesh.material) {
            mesh.material.emissive.setHex(0x332200);
            mesh.material.emissiveIntensity = 1;
        }
    });
    // Highlight selected seed
    const mesh = scene3D.meshes[seedId];
    if (mesh && mesh.material) {
        mesh.material.emissive.setHex(0xff0000);
        mesh.material.emissiveIntensity = 2;
    }
}

function removeSeed3D(seedId) {
    const mesh = scene3D.meshes[seedId];
    if (mesh) {
        scene3D.scene.remove(mesh);
        if (mesh.geometry) mesh.geometry.dispose();
        if (mesh.material) mesh.material.dispose();
        delete scene3D.meshes[seedId];
    }
}

function clearPlanningVisualization() {
    // Clear 3D meshes
    Object.keys(scene3D.meshes).forEach(id => {
        if (id.startsWith('seed_') || id.startsWith('needle_') || id.startsWith('dose_iso_')) {
            scene3D.scene.remove(scene3D.meshes[id]);
            if (scene3D.meshes[id].geometry) scene3D.meshes[id].geometry.dispose();
            if (scene3D.meshes[id].material) scene3D.meshes[id].material.dispose();
            delete scene3D.meshes[id];
        }
    });
    // Clear dataTreeState
    dataTreeState.planning.seeds = [];
    dataTreeState.planning.needles = [];
    dataTreeState.planning.doseLevels = [];
    dataTreeState.planning.meshes = [];
    dataTreeState.seeds.loaded = false;
    dataTreeState.needles.loaded = false;

    // Clear dose contour cache and canvases
    Object.keys(_doseContourCache).forEach(key => delete _doseContourCache[key]);
    ['axial', 'coronal', 'sagittal'].forEach(axis => {
        const contourCanvas = document.getElementById('contourCanvas' + capitalize(axis));
        if (contourCanvas) {
            const ctx = contourCanvas.getContext('2d');
            ctx.clearRect(0, 0, contourCanvas.width, contourCanvas.height);
        }
    });

    renderDataTree();
}

// Delete a seed from 3D scene and data tree
function deleteSeed3D(seedId) {
    const mesh = scene3D.meshes[seedId];
    if (mesh) {
        scene3D.scene.remove(mesh);
        if (mesh.geometry) mesh.geometry.dispose();
        if (mesh.material) mesh.material.dispose();
        delete scene3D.meshes[seedId];
    }
    // Remove from dataTreeState
    dataTreeState.planning.seeds = dataTreeState.planning.seeds.filter(s => s.id !== seedId);
    renderDataTree();
    addChat('system', `Deleted seed ${seedId}`);
    _syncSeedsOverlayFromDataTree();
    reportUIEvent('manual.seed.delete', seedId, {});
    if (dataTreeState.planning.seeds.length > 0) recomputeManualDose('seed_delete');
}

// Delete a needle from 3D scene and data tree
function deleteNeedle3D(needleId) {
    const mesh = scene3D.meshes[needleId];
    if (mesh) {
        scene3D.scene.remove(mesh);
        if (mesh.geometry) mesh.geometry.dispose();
        if (mesh.material) mesh.material.dispose();
        delete scene3D.meshes[needleId];
    }
    if (typeof _removeNeedleHandles === 'function') _removeNeedleHandles(needleId);
    // Remove from dataTreeState
    const needle = dataTreeState.planning.needles.find(n => n.id === needleId);
    const trajId = needle?.trajectory_id;
    dataTreeState.planning.needles = dataTreeState.planning.needles.filter(n => n.id !== needleId);
    if (trajId) {
        dataTreeState.planning.seeds
            .filter(s => s.trajectory_id === trajId)
            .forEach(s => removeSeed3D(s.id));
        dataTreeState.planning.seeds = dataTreeState.planning.seeds.filter(s => s.trajectory_id !== trajId);
        dataTreeState.planning.trajectories = dataTreeState.planning.trajectories.filter(t => t.id !== trajId);
    }
    renderDataTree();
    addChat('system', `Deleted needle ${needleId}`);
    _syncSeedsOverlayFromDataTree();
    reportUIEvent('manual.needle.delete', needleId, {});
    if (dataTreeState.planning.seeds.length > 0) recomputeManualDose('needle_delete');
}

// Show dose at seed position
function showSeedDose(seedId) {
    const seed = dataTreeState.planning.seeds.find(s => s.id === seedId);
    if (!seed) return;
    addChat('system', `💊 **Seed ${seedId}**\n- Position: [${seed.position.map(v => v.toFixed(1)).join(', ')}]\n- Trajectory: ${seed.trajectory_id}`);
}

// Show seeds on a needle
function showNeedleSeeds(needleId) {
    const needle = dataTreeState.planning.needles.find(n => n.id === needleId);
    if (!needle) return;
    // Find all seeds on this trajectory
    const trajId = needle.trajectory_id;
    const seedsOnNeedle = dataTreeState.planning.seeds.filter(s => s.trajectory_id === trajId);
    addChat('system', `📍 **Needle ${needleId}**\n- Points: ${needle.points.length}\n- Trajectory: ${trajId}\n- Seeds: ${seedsOnNeedle.length}`);

    // Highlight all seeds on this needle
    seedsOnNeedle.forEach(s => highlightSeed(s.id));
}

/******** VIEWER INTERACTIVE TOOLS (Slicer-like) ********/
