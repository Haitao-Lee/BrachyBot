/* Completed manual results have a lifecycle independent of chat/SSE previews.
 * Candidate geometry is read-only; clinical seeds/dose keep their canonical
 * objects, colours and individual visibility preferences. */
(function () {
    'use strict';
    const order = ['trajectory_init', 'trajectory_refine', 'seed_planning', 'dose_calc', 'dose_eval'];
    const labels = [
        ['轨迹初始化：轨迹及 Close Points', 'Trajectory init: paths and close points'],
        ['轨迹优化结果', 'Refined trajectories'], ['粒子布源结果', 'Seed planning result'],
        ['剂量计算结果', 'Dose calculation result'], ['剂量评估结果', 'Dose evaluation result'],
    ];
    let catalog = null;
    let pending = null;
    const layers = new Map();
    const session = () => String(typeof _activeApiSessionId === 'function' ? _activeApiSessionId() || ''
        : typeof activeSessionId !== 'undefined' ? activeSessionId || '' : state?.sessionId || '');
    const entries = () => catalog?.sessionId === session() ? catalog.stages : [];

    function dispose(step) {
        const layer = layers.get(step);
        if (!layer) return;
        layer.parent?.remove(layer);
        layer.traverse(object => {
            object.geometry?.dispose();
            const materials = Array.isArray(object.material) ? object.material : [object.material];
            materials.forEach(material => material?.dispose());
        });
        layers.delete(step);
    }

    function buildLayer(entry) {
        if (!scene3D?.scene && typeof init3DScene === 'function') init3DScene();
        if (!entry.geometry || !scene3D?.scene || typeof THREE === 'undefined') return;
        const existing = layers.get(entry.step);
        if (existing?.userData.revision === entry.revision && existing.parent === scene3D.scene) return;
        dispose(entry.step);
        const group = new THREE.Group();
        group.userData = {renderRole: 'manual_step_result', revision: entry.revision, readOnly: true};
        const positions = [];
        for (const path of entry.geometry.trajectories || []) {
            const points = (path.points || []).filter(validPoint);
            for (let i = 1; i < points.length; i++) positions.push(...points[i - 1], ...points[i]);
        }
        if (positions.length) {
            const geometry = new THREE.BufferGeometry();
            geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
            group.add(new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({color: 0x43d8ff})));
        }
        // One instanced draw call, sized to the completed output, not the
        // 256-point cap of transient optimizer previews.
        const points = (entry.geometry.close_points || []).filter(item => validPoint(item.position));
        if (points.length) {
            const mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(0.7, 8, 6),
                new THREE.MeshBasicMaterial({color: 0xffc857}), points.length);
            const matrix = new THREE.Matrix4();
            points.forEach((item, i) => mesh.setMatrixAt(i, matrix.makeTranslation(...item.position)));
            mesh.instanceMatrix.needsUpdate = true;
            mesh.frustumCulled = false;
            group.add(mesh);
        }
        scene3D.scene.add(group);
        layers.set(entry.step, group);
    }

    function validPoint(point) {
        return Array.isArray(point) && point.length === 3 && point.every(Number.isFinite);
    }

    function focus(entry) {
        if (!scene3D?.camera || !scene3D.controls || typeof sync3DCameraPose !== 'function') return;
        const geometry = entry.geometry || {
            trajectories: dataTreeState?.planning?.needles || [],
            seeds: dataTreeState?.planning?.seeds || [],
        };
        const box = new THREE.Box3();
        const add = point => { if (validPoint(point)) box.expandByPoint(new THREE.Vector3(...point)); };
        (geometry.trajectories || []).forEach(path => (path.points || []).forEach(add));
        (geometry.close_points || []).concat(geometry.seeds || []).forEach(item => add(item.position));
        if (box.isEmpty()) return;
        const camera = scene3D.camera;
        const center = box.getCenter(new THREE.Vector3());
        const radius = Math.max(1, box.getBoundingSphere(new THREE.Sphere()).radius);
        const halfY = (Number(camera.fov) || 50) * Math.PI / 360;
        const halfFov = Math.max(0.01, Math.min(halfY, Math.atan(Math.tan(halfY) * (camera.aspect || 1))));
        const distance = Math.max(radius / Math.sin(halfFov) * 1.15, (scene3D.controls.minDistance || 0) * 1.05);
        const direction = camera.position.clone().sub(scene3D.controls.target);
        if (direction.lengthSq() < 1e-8) direction.set(0.5, 0.5, 0.5);
        sync3DCameraPose({position: center.clone().add(direction.normalize().multiplyScalar(distance)),
            target: center, up: camera.up.clone(), near: 0.01, far: Math.max(5000, distance + radius * 4), saveState: true});
    }

    function nodeStep(node) {
        const id = String(node?.id || node?.nodeId || '');
        if (/^(seed_|needle_|traj_|trajectory_)/.test(id) || ['seeds', 'needles'].includes(id)) return 'seed_planning';
        if (/^dose(?:_|$)/.test(id)) return 'dose_calc';
        if (['dvh', 'evaluation'].includes(id)) return 'dose_eval';
        return null;
    }

    function nodeVisible(node) {
        // Report capture already owns a save/restore display transaction.
        if (window.__reportCaptureActive || (!catalog && !pending)) return true;
        if (catalog && catalog.sessionId !== session()) return true;
        const step = nodeStep(node);
        return !step || entries().some(entry => entry.step === step && entry.visible);
    }

    function reveal(nodes) {
        const saved = [];
        for (const node of nodes) {
            const entry = entries().find(item => item.step === nodeStep(node));
            if (entry && !entry.visible) { saved.push(entry); entry.visible = true; }
        }
        const restore = () => { saved.forEach(entry => { entry.visible = false; }); };
        restore.changed = saved.length > 0;
        return restore;
    }

    function sync() {
        const master = typeof _planningViewVisible === 'function'
            ? _planningViewVisible('3d') : dataTreeState?.planning?.visible !== false;
        for (const entry of entries()) {
            buildLayer(entry);
            const layer = layers.get(entry.step);
            if (layer) layer.visible = entry.visible && master && !window.__reportCaptureActive;
        }
        const dvh = document.getElementById('dvhChart');
        if (dvh) {
            const planning = dataTreeState?.planning;
            dvh.hidden = !window.__reportCaptureActive && (!nodeVisible({id: 'dvh'})
                || planning?.visible === false || planning?.dvh?.visible === false);
            // Keep chart dimensions available for Plotly; author display:flex
            // rules can override the browser's default [hidden] styling.
            if (dvh.style) dvh.style.visibility = dvh.hidden ? 'hidden' : '';
        }
        scene3D?.requestRender?.(2);
    }

    function refresh() {
        sync();
        if (typeof applyDataTreeViewVisibility === 'function') applyDataTreeViewVisibility();
        if (typeof renderDataTree === 'function') renderDataTree();
    }

    function clear() {
        catalog = null;
        pending = null; // also invalidates late completions, including A -> B -> A
        [...layers.keys()].forEach(dispose);
        sync();
    }

    function hydrate(value, owner, force = false) {
        if (String(owner || '') !== session() || (pending && !force)) return false;
        if (!value?.stages?.length) { clear(); return true; }
        const samePlan = catalog?.sessionId === session() && catalog.planning_id === value.planning_id;
        const old = new Map((samePlan ? entries() : []).map(entry => [entry.revision, entry.visible]));
        const stages = value.stages.filter(entry => order.includes(entry.step)).map(entry => ({
            ...entry, labels: labels[order.indexOf(entry.step)],
            visible: force ? entry.step === value.active_step
                : old.has(entry.revision) ? old.get(entry.revision) : entry.step === value.active_step,
            trajectoryCount: entry.trajectory_count || 0, shownTrajectories: entry.shown_trajectories || 0,
            closePointCount: entry.close_point_count || 0, seedCount: entry.seed_count || 0,
            hasDose: entry.has_dose === true, hasDvh: entry.has_dvh === true,
        }));
        for (const key of layers.keys()) if (!stages.some(entry => entry.step === key)) dispose(key);
        catalog = {...value, sessionId: session(), stages};
        sync();
        return true;
    }

    function begin(step, owner) {
        if (pending || !order.includes(step) || String(owner || '') !== session()) return null;
        const token = {step, sessionId: session(), visibility: entries().map(entry => [entry.revision, entry.visible])};
        pending = token;
        entries().forEach(entry => { entry.visible = false; });
        refresh();
        return token;
    }

    function finish(token, committed) {
        if (pending !== token || token.sessionId !== session()) return;
        if (!committed) {
            const previous = new Map(token.visibility);
            entries().forEach(entry => { entry.visible = previous.get(entry.revision) === true; });
        }
        pending = null;
        refresh();
    }

    function publish(step, owner, visualization, outcome = {}, outputs = null) {
        const value = outputs || {planning_id: outcome.planningId, active_step: step,
            stages: entries().filter(entry => order.indexOf(entry.step) < order.indexOf(step)).concat({
                ...visualization, step, revision: visualization?.revision || `${Date.now()}:${step}`,
                seed_count: outcome.seedCount, has_dose: outcome.hasDose, has_dvh: outcome.hasDvh,
            })};
        if (!hydrate(value, owner, true)) return false;
        const entry = entries().find(item => item.step === step);
        if (entry && step !== 'dose_eval') focus(entry);
        refresh();
        return true;
    }

    function toggle(step) {
        if (pending) return;
        const entry = entries().find(item => item.step === step);
        if (!entry) return;
        entry.visible = !entry.visible;
        refresh();
        if (entry.step === 'dose_eval' && entry.visible && typeof _resizeDVHChartSoon === 'function') _resizeDVHChartSoon();
    }

    Object.assign(window, {
        manualStepPresentations: entries,
        currentManualStepPresentation: () => entries().find(entry => entry.step === catalog?.active_step),
        clearManualStepPresentation: clear, hydrateManualStepPresentations: hydrate,
        beginManualStepPresentation: begin, finishManualStepPresentation: finish,
        isCurrentManualStepRequest: token => pending === token && token?.sessionId === session(),
        manualStepRequestPending: () => pending?.sessionId === session(),
        publishManualStepPresentation: publish, toggleManualStepPresentation: toggle,
        syncManualStepPresentationVisibility: sync, manualStepNodeVisible: nodeVisible,
        revealManualStepNodes: reveal,
    });
})();
