/* State-aware screenshot annotation for BrachyBot visual evidence.
 *
 * The multimodal child decides whether an annotation is useful and names a
 * stable target_ref.  This browser module owns every pixel coordinate and
 * revalidates both the immutable capture manifest and the current UI/Viewer
 * state before drawing.  It never changes Data Tree visibility, scene
 * visibility, camera state, or the original screenshot.
 */
(function brachybotVisualAnnotation() {
    const RESPONSE_TAG = 'BRACHYBOT_VISUAL_RESPONSE_V2';
    const SHAPES = new Set(['box', 'arrow', 'ellipse', 'point']);
    const UNAVAILABLE_STATUSES = new Set([
        'loading', 'error', 'failed', 'not_generated', 'not-generated',
        'unresolved', 'missing', 'deleted',
    ]);
    const OUTDATED_STATUSES = new Set(['stale', 'expired', 'outdated']);
    const MAX_ATTACHMENTS = 4;
    const MAX_MARKS = 3;

    function text(value, limit = 400) {
        return String(value == null ? '' : value).trim().slice(0, limit);
    }

    function metadataFor(attachment) {
        if (attachment?.view_metadata && typeof attachment.view_metadata === 'object') {
            return attachment.view_metadata;
        }
        if (attachment?.viewMetadata && typeof attachment.viewMetadata === 'object') {
            return attachment.viewMetadata;
        }
        return {};
    }

    function readAttachment(attachment, snake, camel, fallback = '') {
        const metadata = metadataFor(attachment);
        return attachment?.[snake] ?? attachment?.[camel]
            ?? metadata?.[snake] ?? metadata?.[camel] ?? fallback;
    }

    function normalizeBounds(value) {
        if (!Array.isArray(value) || value.length !== 4) return null;
        const numbers = value.map(Number);
        if (!numbers.every(Number.isFinite)) return null;
        let [x, y, width, height] = numbers;
        x = Math.max(0, Math.min(1, x));
        y = Math.max(0, Math.min(1, y));
        width = Math.max(0, Math.min(1 - x, width));
        height = Math.max(0, Math.min(1 - y, height));
        if (width <= 0 || height <= 0) return null;
        return [x, y, width, height];
    }

    function parseVisualResponseEnvelope(rawText) {
        const source = String(rawText || '');
        const open = `<${RESPONSE_TAG}>`;
        const close = `</${RESPONSE_TAG}>`;
        const start = source.indexOf(open);
        const end = source.indexOf(close, start + open.length);
        if (start < 0 || end < 0) return null;
        let payload;
        try {
            payload = JSON.parse(source.slice(start + open.length, end).trim());
        } catch (error) {
            console.warn('[visual annotation] invalid response envelope:', error);
            return null;
        }
        if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null;
        const attachments = (Array.isArray(payload.attachments) ? payload.attachments : [])
            .slice(0, MAX_ATTACHMENTS)
            .map(item => {
                if (!item || typeof item !== 'object') return null;
                const attachmentId = text(
                    item.attachment_id ?? item.attachmentId ?? item.id,
                    180,
                );
                if (!attachmentId) return null;
                const marks = (Array.isArray(item.marks) ? item.marks : [])
                    .slice(0, MAX_MARKS)
                    .map(mark => {
                        if (!mark || typeof mark !== 'object') return null;
                        const targetRef = text(mark.target_ref ?? mark.targetRef, 220);
                        if (!targetRef) return null;
                        const requestedShape = text(mark.shape, 24).toLowerCase();
                        return {
                            target_ref: targetRef,
                            shape: SHAPES.has(requestedShape) ? requestedShape : 'box',
                            label: text(mark.label, 120),
                            priority: Math.max(1, Math.min(9, Number(mark.priority) || 1)),
                        };
                    })
                    .filter(Boolean);
                return {
                    attachment_id: attachmentId,
                    annotate: item.annotate === true,
                    marks,
                    no_annotation_reason: text(
                        item.no_annotation_reason ?? item.noAnnotationReason,
                        300,
                    ),
                };
            })
            .filter(Boolean);
        return {
            answer_text: text(payload.answer_text ?? payload.answerText, 30000),
            attachments,
        };
    }

    function activeSessionIdValue() {
        if (typeof window._activeApiSessionId === 'function') {
            return text(window._activeApiSessionId(), 64);
        }
        return text(window.activeSessionId, 64);
    }

    function currentPlanningId() {
        const planning = window.dataTreeState?.planning || {};
        return text(
            planning.activePlanningId
            || planning.planningId
            || planning.planning_id
            || planning.id,
            180,
        );
    }

    function currentDataVersion() {
        const planning = window.dataTreeState?.planning || {};
        // dataVersion is the authoritative active Planning-run generation.
        // `version` is retained for older/manual-planning callers and may lag
        // briefly during an active-run switch.
        const value = planning.dataVersion ?? planning.data_version ?? planning.version ?? '';
        return text(value, 180);
    }

    function captureManifestFor(attachment) {
        const metadata = metadataFor(attachment);
        const manifest = metadata.grounding_manifest || metadata.groundingManifest
            || attachment?.grounding_manifest || attachment?.groundingManifest;
        return manifest && typeof manifest === 'object' ? manifest : null;
    }

    function stateMatchesCapture(attachment, manifest, expectedSessionId) {
        const capture = manifest?.capture_state || manifest?.captureState || {};
        const ownerSession = text(
            attachment?.session_id || attachment?.sessionId
            || capture.session_id || capture.sessionId,
            64,
        );
        if (!expectedSessionId || ownerSession !== expectedSessionId) {
            return { ok: false, reason: 'session_changed' };
        }
        const captureSession = text(capture.session_id || capture.sessionId, 64);
        if (captureSession && captureSession !== expectedSessionId) {
            return { ok: false, reason: 'capture_session_mismatch' };
        }
        const capturedPlanning = text(
            attachment?.planning_id || attachment?.planningId
            || capture.planning_id || capture.planningId,
            180,
        );
        const activePlanning = currentPlanningId();
        if (capturedPlanning && activePlanning && capturedPlanning !== activePlanning) {
            return { ok: false, reason: 'planning_changed' };
        }
        const capturedVersion = text(
            attachment?.data_version || attachment?.dataVersion
            || capture.data_version || capture.dataVersion,
            180,
        );
        const activeVersion = currentDataVersion();
        if (capturedVersion && activeVersion && capturedVersion !== activeVersion) {
            return { ok: false, reason: 'data_version_changed' };
        }
        return { ok: true };
    }

    function capturedTargetFor(manifest, targetRef) {
        const targets = Array.isArray(manifest?.targets) ? manifest.targets : [];
        return targets.find(item => item && text(
            item.target_ref ?? item.targetRef ?? item.ref,
            220,
        ) === targetRef) || null;
    }

    function statusIsCurrent(value) {
        const status = text(value || 'ready', 48).toLowerCase();
        return !UNAVAILABLE_STATUSES.has(status) && !OUTDATED_STATUSES.has(status);
    }

    function statusIsLocatable(value) {
        return !UNAVAILABLE_STATUSES.has(text(value || 'ready', 48).toLowerCase());
    }

    function isLocationEvidence(attachment) {
        return text(readAttachment(
            attachment,
            'visual_purpose',
            'visualPurpose',
            'explain',
        ), 24).toLowerCase() === 'locate';
    }

    function statusAllowedForEvidence(attachment, value) {
        return isLocationEvidence(attachment)
            ? statusIsLocatable(value)
            : statusIsCurrent(value);
    }

    function attributeEscape(value) {
        return String(value || '').replace(/\\/g, '\\\\').replace(/"/g, '\\"');
    }

    function currentDomTarget(targetRef) {
        const escaped = attributeEscape(targetRef);
        const selectors = [
            `[data-object-id="${escaped}"]`,
            `[data-node-id="${escaped}"]`,
            `[data-item="${escaped}"]`,
            `[data-ui-target="${escaped}"]`,
            `[data-action="${escaped}"]`,
            `[data-target="${escaped}"]`,
            `[name="${escaped}"]`,
            `[aria-label="${escaped}"]`,
        ];
        if (typeof CSS !== 'undefined' && typeof CSS.escape === 'function') {
            selectors.unshift(`#${CSS.escape(targetRef)}`);
        }
        for (const selector of selectors) {
            let element = null;
            try { element = document.querySelector(selector); } catch (_) { element = null; }
            if (!element) continue;
            const style = window.getComputedStyle?.(element);
            const rect = element.getBoundingClientRect?.();
            const rendered = style?.display !== 'none' && style?.visibility !== 'hidden'
                && Number(style?.opacity ?? 1) > 0.01
                && Number(rect?.width || 0) > 0 && Number(rect?.height || 0) > 0;
            const status = text(element.dataset?.status || 'ready', 48).toLowerCase();
            return { found: true, rendered, status, element };
        }
        return { found: false, rendered: false, status: 'unresolved', element: null };
    }

    function validateTargetState(attachment, manifest, mark, expectedSessionId) {
        const targetRef = mark.target_ref;
        const captureState = stateMatchesCapture(attachment, manifest, expectedSessionId);
        if (!captureState.ok) return captureState;
        const captured = capturedTargetFor(manifest, targetRef);
        if (!captured) return { ok: false, reason: 'target_not_in_capture_manifest' };
        const bounds = normalizeBounds(
            captured.normalized_bounds ?? captured.normalizedBounds ?? captured.bounds,
        );
        if (captured.annotatable !== true || captured.visible !== true
            || (captured.in_view !== true && captured.inView !== true) || !bounds) {
            return { ok: false, reason: text(captured.reason, 160) || 'target_not_visible_in_capture' };
        }
        if (!statusAllowedForEvidence(attachment, captured.status)) {
            return { ok: false, reason: `capture_status_${text(captured.status, 48)}` };
        }
        const kind = text(captured.kind, 48).toLowerCase();
        if (kind === 'scene-object') {
            const sceneVisible = captured.scene_visible === true || captured.sceneVisible === true;
            const treeVisible = captured.data_tree_visible === true || captured.dataTreeVisible === true;
            if (!sceneVisible || !treeVisible) {
                return { ok: false, reason: 'scene_object_hidden_in_capture' };
            }
            if (captured.loaded === false || captured.generated === false) {
                return { ok: false, reason: 'scene_object_not_loaded_at_capture' };
            }
            if (typeof window.get3DScreenshotGroundingManifest !== 'function') {
                return { ok: false, reason: 'scene_state_unavailable' };
            }
            const currentManifest = window.get3DScreenshotGroundingManifest([targetRef]);
            const current = capturedTargetFor(currentManifest, targetRef);
            // The screenshot transaction restores the operator's camera after
            // capture. Revalidation therefore checks identity, visibility,
            // Data Tree state, and freshness, but intentionally does not
            // require the object to remain inside the restored live camera.
            if (!current || current.visible !== true
                || current.scene_visible !== true || current.data_tree_visible !== true
                || current.loaded === false || current.generated === false
                || !statusAllowedForEvidence(attachment, current.status)) {
                return {
                    ok: false,
                    reason: text(current?.reason, 160) || 'scene_object_currently_hidden_or_unavailable',
                };
            }
        } else if (kind === 'viewer-object-2d') {
            const axis = text(
                captured.axis || String(readAttachment(attachment, 'target', 'target')).replace('viewer-', ''),
                24,
            ).toLowerCase();
            if (typeof window.get2DScreenshotGroundingManifest !== 'function') {
                return { ok: false, reason: 'mpr_state_unavailable' };
            }
            const currentManifest = window.get2DScreenshotGroundingManifest(axis, [targetRef]);
            const current = capturedTargetFor(currentManifest, targetRef);
            // As with 3D, the selected screenshot slice has already been
            // restored. Do not compare current in-view pixels with the
            // immutable capture; only allow a mark while the same real object
            // remains visible and current in the active Session/Planning.
            if (!current || current.visible !== true
                || current.scene_visible !== true || current.data_tree_visible !== true
                || !statusAllowedForEvidence(attachment, current.status)) {
                return {
                    ok: false,
                    reason: text(current?.reason, 160) || 'mpr_object_currently_hidden_or_unavailable',
                };
            }
        } else {
            const current = currentDomTarget(targetRef);
            // Data Tree evidence is captured from the real live sidebar after
            // temporarily expanding/scrolling it. The transaction is restored
            // before annotation, so the same row may now be collapsed and have
            // a zero client rect. Its capture-time live-DOM bounds remain valid
            // as long as the stable node still exists and its status is still
            // compatible. Ordinary UI screenshots still require rendering.
            const liveDataTreeCapture = text(captured.locator, 48).toLowerCase()
                === 'live-data-tree-dom' && captured.captured_from_live_dom === true;
            if (!current.found || (!liveDataTreeCapture && !current.rendered)
                || !statusAllowedForEvidence(attachment, current.status)) {
                return { ok: false, reason: 'ui_target_currently_hidden_or_unavailable' };
            }
        }
        return { ok: true, captured, bounds, kind };
    }

    function loadImage(url) {
        return new Promise((resolve, reject) => {
            const image = new Image();
            let settled = false;
            const timer = setTimeout(() => {
                if (settled) return;
                settled = true;
                reject(new Error('annotation_image_timeout'));
            }, 15000);
            image.onload = () => {
                if (settled) return;
                settled = true;
                clearTimeout(timer);
                resolve(image);
            };
            image.onerror = () => {
                if (settled) return;
                settled = true;
                clearTimeout(timer);
                reject(new Error('annotation_image_unavailable'));
            };
            image.crossOrigin = 'anonymous';
            image.src = url;
        });
    }

    function relativeLuminance(rgb) {
        const channels = rgb.map(value => {
            const normalized = Math.max(0, Math.min(255, value)) / 255;
            return normalized <= 0.03928
                ? normalized / 12.92
                : Math.pow((normalized + 0.055) / 1.055, 2.4);
        });
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    }

    function contrastRatio(left, right) {
        const a = relativeLuminance(left);
        const b = relativeLuminance(right);
        return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    }

    function rgbFromHex(hex) {
        const value = String(hex || '').replace('#', '');
        return [0, 2, 4].map(index => parseInt(value.slice(index, index + 2), 16));
    }

    function sampledBackground(ctx, box, width, height) {
        const [x, y, w, h] = box;
        const samples = [];
        for (let row = 0; row < 5; row += 1) {
            for (let column = 0; column < 5; column += 1) {
                const px = Math.max(0, Math.min(width - 1, Math.round(x + w * column / 4)));
                const py = Math.max(0, Math.min(height - 1, Math.round(y + h * row / 4)));
                try {
                    const pixel = ctx.getImageData(px, py, 1, 1).data;
                    if (pixel[3] > 8) samples.push([pixel[0], pixel[1], pixel[2]]);
                } catch (_) {
                    return [[15, 23, 42]];
                }
            }
        }
        return samples.length ? samples : [[15, 23, 42]];
    }

    function annotationColor(ctx, box, width, height) {
        const palette = ['#ff2d55', '#00e5ff', '#ffd60a', '#7cff00', '#ff4dff'];
        const samples = sampledBackground(ctx, box, width, height);
        let winner = palette[0];
        let winningScore = -1;
        palette.forEach(color => {
            const rgb = rgbFromHex(color);
            const ratios = samples.map(sample => contrastRatio(rgb, sample)).sort((a, b) => a - b);
            const lowPercentile = ratios[Math.floor((ratios.length - 1) * 0.2)] || 0;
            const average = ratios.reduce((sum, value) => sum + value, 0) / Math.max(1, ratios.length);
            const score = lowPercentile * 0.72 + average * 0.28;
            if (score > winningScore) {
                winner = color;
                winningScore = score;
            }
        });
        return winner;
    }

    function pixelBox(bounds, width, height) {
        const [x, y, w, h] = bounds;
        const padding = Math.max(4, Math.min(width, height) * 0.008);
        const left = Math.max(2, x * width - padding);
        const top = Math.max(2, y * height - padding);
        const right = Math.min(width - 2, (x + w) * width + padding);
        const bottom = Math.min(height - 2, (y + h) * height + padding);
        return [left, top, Math.max(2, right - left), Math.max(2, bottom - top)];
    }

    function pathRoundedRect(ctx, x, y, width, height, radius) {
        const r = Math.max(0, Math.min(radius, width / 2, height / 2));
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.lineTo(x + width - r, y);
        ctx.quadraticCurveTo(x + width, y, x + width, y + r);
        ctx.lineTo(x + width, y + height - r);
        ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
        ctx.lineTo(x + r, y + height);
        ctx.quadraticCurveTo(x, y + height, x, y + height - r);
        ctx.lineTo(x, y + r);
        ctx.quadraticCurveTo(x, y, x + r, y);
        ctx.closePath();
    }

    function strokeTwice(ctx, color, lineWidth, pathBuilder) {
        ctx.save();
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';
        pathBuilder();
        ctx.strokeStyle = 'rgba(0,0,0,0.92)';
        ctx.lineWidth = lineWidth + Math.max(4, lineWidth * 0.9);
        ctx.stroke();
        pathBuilder();
        ctx.strokeStyle = color;
        ctx.lineWidth = lineWidth;
        ctx.stroke();
        ctx.restore();
    }

    function drawLabel(ctx, label, color, anchorX, anchorY, width, height, fontSize) {
        const value = text(label, 80);
        if (!value) return;
        ctx.save();
        ctx.font = `700 ${fontSize}px Inter, "Microsoft YaHei", "Segoe UI", sans-serif`;
        ctx.textBaseline = 'middle';
        const padX = Math.max(8, fontSize * 0.55);
        const labelWidth = Math.min(width * 0.62, ctx.measureText(value).width + padX * 2);
        const labelHeight = fontSize * 1.65;
        const x = Math.max(3, Math.min(width - labelWidth - 3, anchorX));
        const y = Math.max(3, Math.min(height - labelHeight - 3, anchorY));
        pathRoundedRect(ctx, x, y, labelWidth, labelHeight, Math.max(5, fontSize * 0.32));
        ctx.fillStyle = color;
        ctx.fill();
        ctx.strokeStyle = 'rgba(0,0,0,0.88)';
        ctx.lineWidth = Math.max(2, fontSize * 0.12);
        ctx.stroke();
        const foreground = relativeLuminance(rgbFromHex(color)) > 0.48 ? '#07111f' : '#ffffff';
        ctx.fillStyle = foreground;
        ctx.fillText(value, x + padX, y + labelHeight / 2, labelWidth - padX * 2);
        ctx.restore();
    }

    function drawArrow(ctx, box, color, lineWidth) {
        const [x, y, w, h] = box;
        const targetX = x + w / 2;
        const targetY = y + h / 2;
        const margin = Math.max(18, Math.min(ctx.canvas.width, ctx.canvas.height) * 0.045);
        const startFromLeft = targetX > ctx.canvas.width * 0.52;
        const startX = startFromLeft ? Math.max(margin, x - margin) : Math.min(ctx.canvas.width - margin, x + w + margin);
        const startY = Math.max(margin, Math.min(ctx.canvas.height - margin, y - margin * 0.35));
        const dx = targetX - startX;
        const dy = targetY - startY;
        const angle = Math.atan2(dy, dx);
        const head = Math.max(13, lineWidth * 3.1);
        const path = () => {
            ctx.beginPath();
            ctx.moveTo(startX, startY);
            ctx.lineTo(targetX, targetY);
            ctx.moveTo(targetX, targetY);
            ctx.lineTo(targetX - head * Math.cos(angle - Math.PI / 6), targetY - head * Math.sin(angle - Math.PI / 6));
            ctx.moveTo(targetX, targetY);
            ctx.lineTo(targetX - head * Math.cos(angle + Math.PI / 6), targetY - head * Math.sin(angle + Math.PI / 6));
        };
        strokeTwice(ctx, color, lineWidth, path);
        return { x: startFromLeft ? startX : Math.max(3, startX - ctx.canvas.width * 0.25), y: startY + lineWidth * 2 };
    }

    function drawMark(ctx, mark, validated, width, height) {
        const box = pixelBox(validated.bounds, width, height);
        const color = annotationColor(ctx, box, width, height);
        const lineWidth = Math.max(4, Math.min(12, Math.min(width, height) * 0.008));
        const fontSize = Math.max(17, Math.min(34, Math.min(width, height) * 0.032));
        let shape = mark.shape;
        if (validated.kind === 'data-tree-row' || validated.kind === 'ui-element') shape = 'box';
        let labelAnchor = { x: box[0], y: box[1] - fontSize * 1.9 };
        if (shape === 'arrow') {
            labelAnchor = drawArrow(ctx, box, color, lineWidth);
        } else if (shape === 'ellipse') {
            const [x, y, w, h] = box;
            strokeTwice(ctx, color, lineWidth, () => {
                ctx.beginPath();
                ctx.ellipse(x + w / 2, y + h / 2, Math.max(2, w / 2), Math.max(2, h / 2), 0, 0, Math.PI * 2);
            });
        } else if (shape === 'point') {
            const [x, y, w, h] = box;
            const radius = Math.max(11, Math.min(34, Math.max(w, h) * 0.35));
            strokeTwice(ctx, color, lineWidth, () => {
                ctx.beginPath();
                ctx.arc(x + w / 2, y + h / 2, radius, 0, Math.PI * 2);
            });
        } else {
            const [x, y, w, h] = box;
            strokeTwice(ctx, color, lineWidth, () => pathRoundedRect(
                ctx, x, y, w, h, Math.max(6, lineWidth * 1.5),
            ));
        }
        drawLabel(ctx, mark.label, color, labelAnchor.x, labelAnchor.y, width, height, fontSize);
        return {
            target_ref: mark.target_ref,
            shape,
            label: mark.label,
            locator: text(validated.captured?.locator, 48),
        };
    }

    async function renderAnnotation(attachment, validMarks) {
        const sourceUrl = text(attachment.original_url || attachment.originalUrl || attachment.url, 1000);
        if (!sourceUrl) throw new Error('annotation_source_missing');
        const image = await loadImage(sourceUrl);
        const width = Number(image.naturalWidth || image.width || 0);
        const height = Number(image.naturalHeight || image.height || 0);
        if (width < 16 || height < 16) throw new Error('annotation_source_invalid');
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d', { willReadFrequently: true });
        if (!ctx) throw new Error('annotation_canvas_unavailable');
        ctx.drawImage(image, 0, 0, width, height);
        const renderedMarks = validMarks
            .sort((left, right) => left.mark.priority - right.mark.priority)
            .map(item => drawMark(ctx, item.mark, item.validated, width, height));
        return {
            image: canvas.toDataURL('image/png'),
            marks: renderedMarks,
            sourceUrl,
        };
    }

    function languageFor(attachment, context = {}) {
        const raw = context.responseLanguage || context.response_language
            || attachment?.response_language || attachment?.responseLanguage
            || (typeof window.conversationLanguageForSession === 'function'
                ? window.conversationLanguageForSession(activeSessionIdValue())
                : '')
            || window._responseLanguage || window._i18nLang || 'en';
        return String(raw).toLowerCase().startsWith('zh') ? 'zh' : 'en';
    }

    function setTileState(attachment, state) {
        const id = text(attachment?.id || attachment?.attachment_id, 180);
        document.querySelectorAll('.chat-gallery-item').forEach(tile => {
            if (id && String(tile.dataset.attachmentId || '') !== id) return;
            tile.classList.toggle('is-annotating', state === 'working');
            tile.classList.toggle('annotation-skipped', state === 'skipped');
        });
    }

    async function uploadAnnotation(attachment, rendered, sessionId) {
        const apiBase = typeof API !== 'undefined' ? API : '/api';
        const response = await fetch(`${apiBase}/screenshot/annotation`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-BrachyBot-Session': sessionId,
            },
            body: JSON.stringify({
                source_attachment_id: attachment.id || attachment.attachment_id,
                source_url: rendered.sourceUrl,
                source_sha256: attachment.sha256 || '',
                planning_id: attachment.planning_id || attachment.planningId || '',
                data_version: attachment.data_version || attachment.dataVersion || '',
                image: rendered.image,
                marks: rendered.marks,
            }),
        });
        const body = await response.text();
        let payload = {};
        try { payload = body ? JSON.parse(body) : {}; } catch (_) {}
        if (!response.ok || !payload?.attachment) {
            throw new Error(payload?.error || `annotation_upload_failed:${response.status}`);
        }
        return payload.attachment;
    }

    function findEvidenceAttachment(evidence, attachmentId) {
        return (Array.isArray(evidence) ? evidence : []).find(item => item && text(
            item.id || item.attachment_id || item.attachmentId,
            180,
        ) === attachmentId) || null;
    }

    async function applyVisualResponseAnnotations(envelope, evidence, context = {}) {
        const sessionId = text(context.sessionId || activeSessionIdValue(), 64);
        const result = { updated: [], skipped: [], requested: 0, notice: '' };
        if (!envelope || !Array.isArray(envelope.attachments) || !sessionId) return result;
        if (sessionId !== activeSessionIdValue()) {
            result.skipped.push({ reason: 'session_changed' });
            return result;
        }

        // The multimodal child normally chooses whether and how to mark each
        // image. For an explicit locate+required contract, deterministically
        // fill only omissions that already have a stable, visible, bounded
        // target in the capture manifest. This is not image guessing: hidden,
        // unloaded, unresolved, or state-mismatched targets still fail the
        // same validation below.
        const decisions = envelope.attachments.map(decision => ({
            ...decision,
            marks: Array.isArray(decision?.marks) ? [...decision.marks] : [],
        }));
        (Array.isArray(evidence) ? evidence : []).forEach(attachment => {
            const policy = text(readAttachment(
                attachment, 'annotation_policy', 'annotationPolicy', 'auto',
            ), 24).toLowerCase();
            const purpose = text(readAttachment(
                attachment, 'visual_purpose', 'visualPurpose', 'explain',
            ), 24).toLowerCase();
            if (policy !== 'required' || purpose !== 'locate') return;
            const attachmentId = text(
                attachment.id || attachment.attachment_id || attachment.attachmentId,
                180,
            );
            const manifest = captureManifestFor(attachment);
            if (!attachmentId || !manifest) return;
            let decision = decisions.find(item => item?.attachment_id === attachmentId);
            if (!decision) {
                decision = { attachment_id: attachmentId, annotate: true, marks: [] };
                decisions.push(decision);
            }
            const existing = new Set(decision.marks.map(mark => text(mark?.target_ref, 220)));
            const eligible = (Array.isArray(manifest.targets) ? manifest.targets : [])
                .filter(target => target?.annotatable === true
                    && target?.visible === true
                    && (target?.in_view === true || target?.inView === true)
                    && normalizeBounds(
                        target?.normalized_bounds ?? target?.normalizedBounds ?? target?.bounds,
                    ))
                .slice(0, MAX_MARKS);
            eligible.forEach(target => {
                const targetRef = text(target.target_ref ?? target.targetRef, 220);
                if (!targetRef || existing.has(targetRef)) return;
                const kind = text(target.kind, 48).toLowerCase();
                decision.marks.push({
                    target_ref: targetRef,
                    shape: kind === 'scene-object' ? 'arrow'
                        : (kind === 'viewer-object-2d' ? 'ellipse' : 'box'),
                    label: text(target.label || targetRef, 120),
                    priority: 1,
                });
                existing.add(targetRef);
            });
            decision.annotate = decision.marks.length > 0;
        });

        const prepared = [];
        decisions.forEach(decision => {
            if (!decision?.annotate || !decision.marks?.length) return;
            result.requested += decision.marks.length;
            const attachment = findEvidenceAttachment(evidence, decision.attachment_id);
            if (!attachment) {
                result.skipped.push({ attachment_id: decision.attachment_id, reason: 'attachment_not_found' });
                return;
            }
            const policy = text(readAttachment(
                attachment, 'annotation_policy', 'annotationPolicy', 'auto',
            ), 24).toLowerCase();
            if (policy === 'none') {
                result.skipped.push({ attachment_id: decision.attachment_id, reason: 'annotation_forbidden' });
                return;
            }
            const manifest = captureManifestFor(attachment);
            if (!manifest) {
                result.skipped.push({ attachment_id: decision.attachment_id, reason: 'grounding_manifest_missing' });
                return;
            }
            const validMarks = [];
            decision.marks.slice(0, MAX_MARKS).forEach(mark => {
                const validated = validateTargetState(attachment, manifest, mark, sessionId);
                if (validated.ok) validMarks.push({ mark, validated });
                else result.skipped.push({
                    attachment_id: decision.attachment_id,
                    target_ref: mark.target_ref,
                    reason: validated.reason,
                });
            });
            if (validMarks.length) prepared.push({ attachment, manifest, validMarks });
        });

        // Decode and draw locally in parallel. Uploads remain serialized so
        // two derived images cannot race while merging the same chat message.
        const rendered = await Promise.all(prepared.map(async item => {
            setTileState(item.attachment, 'working');
            try {
                return Object.assign({}, item, {
                    rendered: await renderAnnotation(item.attachment, item.validMarks),
                });
            } catch (error) {
                result.skipped.push({
                    attachment_id: item.attachment.id,
                    reason: error?.message || 'annotation_render_failed',
                });
                setTileState(item.attachment, 'skipped');
                return null;
            }
        }));

        for (const item of rendered.filter(Boolean)) {
            // Recheck immediately before persistence. Visibility may have
            // changed while the image decoded, especially for guide/Planning
            // nodes toggled from the Data Tree.
            const stillValid = item.validMarks.every(entry =>
                validateTargetState(item.attachment, item.manifest, entry.mark, sessionId).ok
            );
            if (!stillValid || sessionId !== activeSessionIdValue()) {
                result.skipped.push({ attachment_id: item.attachment.id, reason: 'state_changed_during_annotation' });
                setTileState(item.attachment, 'skipped');
                continue;
            }
            try {
                const updated = await uploadAnnotation(item.attachment, item.rendered, sessionId);
                result.updated.push(updated);
                setTileState(item.attachment, 'done');
                if (typeof window.updateAssistantAttachmentVariant === 'function') {
                    window.updateAssistantAttachmentVariant(updated, sessionId);
                }
            } catch (error) {
                console.warn('[visual annotation] persistence failed:', error);
                result.skipped.push({
                    attachment_id: item.attachment.id,
                    reason: error?.message || 'annotation_upload_failed',
                });
                setTileState(item.attachment, 'skipped');
            }
        }

        if (result.requested > 0 && result.skipped.length > 0) {
            const language = languageFor(evidence?.[0], context);
            const partial = result.updated.length > 0;
            result.notice = language === 'zh'
                ? (partial
                    ? '注：部分目标因当前不可见、未加载、不可用、已切换规划，或当前任务要求最新状态但目标已过期，已安全跳过标注。'
                    : '注：目标当前不可见、未加载、不可用、已切换规划，或当前任务要求最新状态但目标已过期，因此未绘制定位标注；原始截图仍保留。')
                : (partial
                    ? 'Note: Some marks were safely omitted because their targets are hidden, unloaded, unavailable, from another plan, or outdated where current evidence is required.'
                    : 'Note: No locating mark was drawn because the target is hidden, unloaded, unavailable, from another plan, or outdated where current evidence is required; the original screenshot is preserved.');
        }
        return result;
    }

    window.parseVisualResponseEnvelope = parseVisualResponseEnvelope;
    window.applyVisualResponseAnnotations = applyVisualResponseAnnotations;
    window.validateVisualAnnotationTargetState = validateTargetState;
})();
