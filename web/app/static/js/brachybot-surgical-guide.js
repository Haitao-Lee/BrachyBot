/* Patient-specific puncture guide UI. Kept session-aware to prevent stale meshes. */
(function surgicalGuideUI() {
    const GUIDE_ID = 'patient_specific_puncture_guide';
    const GUIDE_DEFAULTS = Object.freeze({
        skin_threshold_hu: -300,
        skin_clearance_mm: 1,
        plate_thickness_mm: 3,
        patch_margin_mm: 24,
        channel_radius_mm: 1.1,
        sleeve_outer_radius_mm: 3,
        sleeve_outward_mm: 8,
        sleeve_inward_mm: 8,
        geometry_resolution_mm: 1,
    });
    const GUIDE_CONTROLS = Object.freeze({
        skin_threshold_hu: 'guideSkinThreshold',
        skin_clearance_mm: 'guideSkinClearance',
        plate_thickness_mm: 'guidePlateThickness',
        patch_margin_mm: 'guidePatchMargin',
        channel_diameter_mm: 'guideChannelDiameter',
        sleeve_outer_diameter_mm: 'guideSleeveOuterDiameter',
        sleeve_outward_mm: 'guideSleeveOutward',
        sleeve_inward_mm: 'guideSleeveInward',
        geometry_resolution_mm: 'guideGeometryResolution',
    });
    const GUIDE_NEEDLE_SELECTION_ID = 'guideNeedleSelection';
    const GUIDE_VERSION_SELECTION_ID = 'guideVersionSelect';
    const GUIDE_STL_VALIDATION_FILE_ID = 'guideStlValidationFile';
    const GUIDE_STL_VALIDATION_STATUS_ID = 'guideStlValidationStatus';
    let guideLoadGeneration = 0;
    let lastGuideMetadata = { needle_options: [], versions: [], activeVersion: null };

    function t(zh, en) {
        return typeof window._t === 'function'
            ? window._t(zh, en)
            : (window._i18nLang === 'zh' ? zh : en);
    }

    function activeSessionId() {
        return String(window.activeSessionId || window.state?.sessionId || '');
    }

    function notify(message, kind = 'info') {
        if (typeof showToast === 'function') {
            showToast(message, kind);
        } else if (typeof window.addUIEvent === 'function') {
            window.addUIEvent({ type: 'surgical_guide.notice', label: message, level: kind });
        }
    }

    function setValidationStatus(message, kind = 'info') {
        const status = document.getElementById(GUIDE_STL_VALIDATION_STATUS_ID);
        if (!status) return;
        status.textContent = message;
        status.style.color = kind === 'error'
            ? 'var(--danger, #ef4444)'
            : kind === 'success' ? 'var(--success, #22c55e)' : 'var(--text-dim)';
    }

    function setBusy(busy, label) {
        const button = document.getElementById('generateSurgicalGuideButton');
        if (button) {
            button.disabled = !!busy;
            button.classList.toggle('is-loading', !!busy);
            button.textContent = busy
                ? (label || t('正在生成导板...', 'Generating guide...'))
                : t('生成导板', 'Generate guide');
        }
        if (busy && typeof window.reportUIEvent === 'function') {
            window.reportUIEvent(
                'surgical_guide.running',
                label || t('正在生成患者特异性穿刺导板', 'Generating patient-specific puncture guide'),
                { state: 'running' },
            );
        }
    }

    function numericControl(id, fallback) {
        const value = Number(document.getElementById(id)?.value);
        return Number.isFinite(value) ? value : fallback;
    }

    function guideParametersFromControls() {
        // The clinical UI uses diameters because they are the manufactured
        // dimensions clinicians specify. The geometry service deliberately
        // receives radii, its internal primitive convention.
        return {
            skin_threshold_hu: numericControl(GUIDE_CONTROLS.skin_threshold_hu, GUIDE_DEFAULTS.skin_threshold_hu),
            skin_clearance_mm: numericControl(GUIDE_CONTROLS.skin_clearance_mm, GUIDE_DEFAULTS.skin_clearance_mm),
            plate_thickness_mm: numericControl(GUIDE_CONTROLS.plate_thickness_mm, GUIDE_DEFAULTS.plate_thickness_mm),
            patch_margin_mm: numericControl(GUIDE_CONTROLS.patch_margin_mm, GUIDE_DEFAULTS.patch_margin_mm),
            channel_radius_mm: numericControl(GUIDE_CONTROLS.channel_diameter_mm, GUIDE_DEFAULTS.channel_radius_mm * 2) / 2,
            sleeve_outer_radius_mm: numericControl(GUIDE_CONTROLS.sleeve_outer_diameter_mm, GUIDE_DEFAULTS.sleeve_outer_radius_mm * 2) / 2,
            sleeve_outward_mm: numericControl(GUIDE_CONTROLS.sleeve_outward_mm, GUIDE_DEFAULTS.sleeve_outward_mm),
            sleeve_inward_mm: numericControl(GUIDE_CONTROLS.sleeve_inward_mm, GUIDE_DEFAULTS.sleeve_inward_mm),
            geometry_resolution_mm: numericControl(GUIDE_CONTROLS.geometry_resolution_mm, GUIDE_DEFAULTS.geometry_resolution_mm),
        };
    }

    function applyGuideParameters(parameters = {}) {
        const value = (name, fallback) => Number.isFinite(Number(parameters[name]))
            ? Number(parameters[name]) : fallback;
        const setValue = (control, next) => {
            const input = document.getElementById(control);
            if (input) input.value = String(next);
        };
        setValue(GUIDE_CONTROLS.skin_threshold_hu, value('skin_threshold_hu', GUIDE_DEFAULTS.skin_threshold_hu));
        setValue(GUIDE_CONTROLS.skin_clearance_mm, value('skin_clearance_mm', GUIDE_DEFAULTS.skin_clearance_mm));
        setValue(GUIDE_CONTROLS.plate_thickness_mm, value('plate_thickness_mm', GUIDE_DEFAULTS.plate_thickness_mm));
        setValue(GUIDE_CONTROLS.patch_margin_mm, value('patch_margin_mm', GUIDE_DEFAULTS.patch_margin_mm));
        setValue(GUIDE_CONTROLS.channel_diameter_mm, value('channel_radius_mm', GUIDE_DEFAULTS.channel_radius_mm) * 2);
        setValue(GUIDE_CONTROLS.sleeve_outer_diameter_mm, value('sleeve_outer_radius_mm', GUIDE_DEFAULTS.sleeve_outer_radius_mm) * 2);
        setValue(GUIDE_CONTROLS.sleeve_outward_mm, value('sleeve_outward_mm', GUIDE_DEFAULTS.sleeve_outward_mm));
        setValue(GUIDE_CONTROLS.sleeve_inward_mm, value('sleeve_inward_mm', GUIDE_DEFAULTS.sleeve_inward_mm));
        setValue(GUIDE_CONTROLS.geometry_resolution_mm, value('geometry_resolution_mm', GUIDE_DEFAULTS.geometry_resolution_mm));
    }

    function bindGuideControls() {
        const saveParameters = () => {
            // Save edits while the field is being adjusted. Generation still
            // remains explicit, so a validated guide version is never
            // replaced until the clinician chooses Generate guide.
            window.scheduleWorkspaceSave?.('surgical_guide.parameters');
        };
        Object.values(GUIDE_CONTROLS).forEach(id => {
            const control = document.getElementById(id);
            if (!control || control.dataset.surgicalGuideBound === 'true') return;
            control.dataset.surgicalGuideBound = 'true';
            control.addEventListener('input', saveParameters);
            control.addEventListener('change', saveParameters);
        });
        const needleSelection = document.getElementById(GUIDE_NEEDLE_SELECTION_ID);
        if (needleSelection && needleSelection.dataset.surgicalGuideBound !== 'true') {
            needleSelection.dataset.surgicalGuideBound = 'true';
            needleSelection.addEventListener('change', saveParameters);
        }
    }

    function selectedNeedleIds() {
        const control = document.getElementById(GUIDE_NEEDLE_SELECTION_ID);
        return control ? Array.from(control.selectedOptions).map(option => String(option.value)).filter(Boolean) : [];
    }

    function selectedGuideVersion() {
        const raw = document.getElementById(GUIDE_VERSION_SELECTION_ID)?.value;
        const value = Number(raw);
        return Number.isInteger(value) && value > 0 ? value : null;
    }

    function populateNeedleSelection(needles = []) {
        const control = document.getElementById(GUIDE_NEEDLE_SELECTION_ID);
        if (!control) return;
        const previouslySelected = new Set(selectedNeedleIds());
        control.replaceChildren();
        (Array.isArray(needles) ? needles : []).forEach(needle => {
            const id = String(needle?.id || '');
            if (!id) return;
            const option = document.createElement('option');
            option.value = id;
            option.textContent = `${id} (${Number(needle?.seed_count || 0)} seeds)`;
            option.selected = previouslySelected.has(id);
            control.append(option);
        });
    }

    function populateGuideVersions(versions = [], activeVersion = null) {
        const control = document.getElementById(GUIDE_VERSION_SELECTION_ID);
        if (!control) return;
        const desired = Number(activeVersion || control.value);
        control.replaceChildren();
        const items = Array.isArray(versions) ? versions : [];
        if (!items.length) {
            const empty = document.createElement('option');
            empty.value = '';
            empty.textContent = t('暂无已保存导板', 'No saved guide');
            control.append(empty);
            return;
        }
        items.forEach(item => {
            const version = Number(item?.version);
            if (!Number.isInteger(version) || version <= 0) return;
            const option = document.createElement('option');
            option.value = String(version);
            const fallback = t(`导板 v${version}`, `Guide v${version}`);
            const state = item.status === 'ready'
                ? t('可用', 'ready')
                : item.status === 'stale' ? t('已过期', 'stale') : (item.status || t('未知', 'unknown'));
            option.textContent = `${item.label || fallback} - ${state}`;
            option.selected = version === desired;
            control.append(option);
        });
        if (!control.value && control.options.length) control.selectedIndex = 0;
    }

    function applyGuideMetadata(payload, activeGuide = null) {
        lastGuideMetadata = {
            needle_options: payload?.needle_options || [],
            versions: payload?.versions || [],
            activeVersion: activeGuide?.version || null,
        };
        populateNeedleSelection(lastGuideMetadata.needle_options);
        populateGuideVersions(lastGuideMetadata.versions, lastGuideMetadata.activeVersion);
    }

    function removeGuideMesh() {
        if (typeof scene3D === 'undefined' || !scene3D?.meshes?.[GUIDE_ID]) return;
        const mesh = scene3D.meshes[GUIDE_ID];
        scene3D.scene?.remove(mesh);
        mesh.geometry?.dispose?.();
        mesh.material?.dispose?.();
        delete scene3D.meshes[GUIDE_ID];
        if (window.dataTreeState?.planning?.meshes) {
            window.dataTreeState.planning.meshes = window.dataTreeState.planning.meshes
                .filter(item => item.id !== GUIDE_ID);
        }
        window.renderDataTree?.();
        window.requestRender?.();
    }

    function addGuideMesh(guide) {
        if (!guide?.vertices?.length || !guide?.faces?.length || typeof addMeshToScene !== 'function') return false;
        const previous = window.dataTreeState?.planning?.meshes?.find(item => item.id === GUIDE_ID);
        addMeshToScene({
            organ_id: GUIDE_ID,
            source: 'surgical_guide',
            label: guide.label || 'Patient-specific puncture guide',
            vertices: guide.vertices,
            faces: guide.faces,
            vertex_count: guide.vertices.length,
            color: previous?.color || '#2dd4bf',
            opacity: typeof previous?.opacity === 'number' ? previous.opacity : 0.82,
        });
        applyGuideParameters(guide.parameters || {});
        return true;
    }

    async function guideFetch(url, options = {}, sessionId = activeSessionId()) {
        const response = await fetch(url, {
            credentials: 'same-origin',
            ...options,
            headers: {
                ...(options.headers || {}),
                ...(sessionId ? { 'X-BrachyBot-Session': sessionId } : {}),
            },
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.success === false) throw new Error(payload.error || `Guide request failed: HTTP ${response.status}`);
        return payload;
    }

    window.loadSurgicalGuideMesh = async function loadSurgicalGuideMesh(options = {}) {
        const sessionId = String(options.sessionId || activeSessionId());
        if (!sessionId) return false;
        const generation = ++guideLoadGeneration;
        try {
            const version = Number(options.version);
            const suffix = Number.isInteger(version) && version > 0 ? `?version=${encodeURIComponent(version)}` : '';
            const payload = await guideFetch(`/api/surgical-guides/mesh${suffix}`, {}, sessionId);
            if (generation !== guideLoadGeneration || sessionId !== activeSessionId()) return false;
            if (!payload.available || payload.guide?.status !== 'ready') {
                applyGuideMetadata(payload);
                removeGuideMesh();
                return false;
            }
            applyGuideMetadata(payload, payload.guide);
            return addGuideMesh(payload.guide);
        } catch (error) {
            // A new or partially restored case normally has no guide. Do not
            // surface a failure notification while its other assets hydrate.
            if (options.userInitiated) notify(error.message, 'error');
            return false;
        }
    };

    window.generateSurgicalGuide = async function generateSurgicalGuide() {
        const sessionId = activeSessionId();
        if (!sessionId) return;
        setBusy(true, 'Generating guide...');
        try {
            const payload = await guideFetch('/api/surgical-guides/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    parameters: guideParametersFromControls(),
                    needle_ids: selectedNeedleIds(),
                }),
            }, sessionId);
            if (sessionId !== activeSessionId()) return;
            applyGuideMetadata(payload, payload.guide);
            addGuideMesh(payload.guide);
            window.scheduleWorkspaceSave?.('surgical_guide.generated');
            const completed = t(
                `穿刺导板 v${payload.guide.version} 已生成`,
                `Puncture guide v${payload.guide.version} generated`,
            );
            notify(completed, 'success');
            window.reportUIEvent?.('surgical_guide.completed', completed, {
                state: 'completed', version: payload.guide.version,
            });
        } catch (error) {
            notify(error.message, 'error');
        } finally {
            if (sessionId === activeSessionId()) setBusy(false);
        }
    };

    window.exportSurgicalGuideSTL = async function exportSurgicalGuideSTL() {
        const sessionId = activeSessionId();
        try {
            const response = await fetch('/api/surgical-guides/export', {
                method: 'POST', credentials: 'same-origin',
                headers: {
                    ...(sessionId ? { 'X-BrachyBot-Session': sessionId } : {}),
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ version: selectedGuideVersion() }),
            });
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                throw new Error(payload.error || 'Guide export failed');
            }
            const blob = await response.blob();
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = `puncture_guide_${sessionId.slice(0, 8)}.stl`;
            link.click();
            URL.revokeObjectURL(link.href);
            notify(t('已下载通过校验的穿刺导板 STL', 'Validated puncture guide STL downloaded'), 'success');
        } catch (error) {
            notify(error.message, 'error');
        }
    };

    window.invalidateSurgicalGuidePresentation = function invalidateSurgicalGuidePresentation() {
        guideLoadGeneration += 1;
        removeGuideMesh();
    };

    window.resetSurgicalGuideControls = function resetSurgicalGuideControls() {
        applyGuideParameters(GUIDE_DEFAULTS);
        const needleSelection = document.getElementById(GUIDE_NEEDLE_SELECTION_ID);
        if (needleSelection) needleSelection.replaceChildren();
        populateGuideVersions([], null);
        window.scheduleWorkspaceSave?.('surgical_guide.parameters.reset');
    };

    window.loadSelectedSurgicalGuideVersion = function loadSelectedSurgicalGuideVersion() {
        const version = selectedGuideVersion();
        if (!version) {
            notify(t('请先选择已保存的导板版本', 'Choose a saved puncture guide version first'), 'info');
            return;
        }
        return window.loadSurgicalGuideMesh({ version, userInitiated: true });
    };

    window.validateImportedSurgicalGuideSTL = async function validateImportedSurgicalGuideSTL(file) {
        const sessionId = activeSessionId();
        if (!file || !sessionId) return false;
        setValidationStatus(t('正在校验 STL 网格...', 'Validating STL mesh...'));
        try {
            const form = new FormData();
            form.append('file', file, file.name || 'puncture_guide.stl');
            const payload = await guideFetch('/api/surgical-guides/validate', {
                method: 'POST', body: form,
            }, sessionId);
            if (sessionId !== activeSessionId()) return false;
            const validation = payload.validation || {};
            const message = validation.watertight
                ? t(
                    `STL 校验通过：${validation.vertex_count} 个顶点，${validation.face_count} 个三角面，闭合网格。`,
                    `STL validated: ${validation.vertex_count} vertices, ${validation.face_count} triangles, watertight mesh.`,
                )
                : t('STL 未通过闭合网格校验。', 'STL did not pass watertightness validation.');
            setValidationStatus(message, validation.watertight ? 'success' : 'error');
            notify(message, validation.watertight ? 'success' : 'error');
            return !!validation.watertight;
        } catch (error) {
            setValidationStatus(error.message, 'error');
            notify(error.message, 'error');
            return false;
        }
    };

    window.getSurgicalGuideParameters = guideParametersFromControls;
    window.applySurgicalGuideParameters = applyGuideParameters;
    bindGuideControls();
    document.getElementById(GUIDE_STL_VALIDATION_FILE_ID)?.addEventListener('change', event => {
        const file = event.target?.files?.[0];
        if (file) window.validateImportedSurgicalGuideSTL(file);
        // Allow the same STL to be checked again after a corrected export.
        event.target.value = '';
    });
    window.addEventListener('i18nchange', () => {
        const generate = document.getElementById('generateSurgicalGuideButton');
        if (generate && !generate.disabled) generate.textContent = t('生成导板', 'Generate guide');
        populateNeedleSelection(lastGuideMetadata.needle_options);
        populateGuideVersions(lastGuideMetadata.versions, lastGuideMetadata.activeVersion);
    });
}());
