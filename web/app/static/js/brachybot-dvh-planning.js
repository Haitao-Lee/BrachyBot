async function render3D() {
    // LEGACY function — now delegates to the modern scene3D system.
    // The old implementation created a brand-new THREE.Scene/renderer
    // on every call, which wiped out all meshes loaded by
    // loadCTVAndObstacleMeshes, loadSeeds3D, and loadAllIsoSurfaces.
    // Now we just init (idempotent) and force a resize+fit.
    const canvas = document.getElementById('canvas3D');
    if (!canvas) return;
    if (!state.ctLoaded) {
        canvas.innerHTML = '<div class="viewer-no-data"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg><span>Load CT first</span></div>';
        return;
    }
    init3DScene();
    forceRender3DViewer();
    window.dose3D = true;
}

/******** DVH CHART ********/

// Pick a clean tick step (in "1, 2, 5 × 10^n" family, optionally also
// divisible by 2 for nicer dose-axis labels) so the axis shows
// ~targetCount major ticks across the given [min, max] range. Avoids
// overcrowded axes when the user zooms in and stale 50Gy/20% dticks.
function _pickTickStep(span, targetCount = 8, preferDivisibleBy2 = false) {
    if (span <= 0 || !isFinite(span)) return 1;
    const raw = span / targetCount;
    const exp = Math.floor(Math.log10(raw));
    const base = Math.pow(10, exp);
    const norm = raw / base;       // 1..10
    let step;
    if (norm < 1.5) step = 1;
    else if (norm < 3) step = 2;
    else if (norm < 7) step = 5;
    else step = 10;
    let result = step * base;
    // For dose axis: prefer ticks that are multiples of 2 (so 20, 40, ...
    // instead of 25, 50, 100). If the result is 5 × 10^n, halve to 2.5 ×
    // 10^n then ×2 = 5×10^n — but we want 2 × 10^(n+1) when zoomed out
    // enough. 5*10^n is divisible by 5 but not 2, so we let the caller
    // adjust if needed. For now, if not divisible by 2, try the next
    // power-of-2 step up.
    if (preferDivisibleBy2 && (result % 2 !== 0)) {
        // Round up to the nearest power of 2 × 10^n
        const exp2 = Math.ceil(Math.log2(result));
        result = Math.pow(2, exp2);
    }
    return result;
}

// Pin a sensible default dtick for the given axis span so the chart
// always shows a usable grid even when Plotly's autorange kicks in.
// Bug fix 2026-06-16: user complained that the y-axis tick spacing
// "reset" to 1 (way too dense) after picking a point. Plotly's
// autorange sometimes overrides dtick to its default of 1. We
// explicitly compute and set dtick from the visible span.
function _dvhDefaultDticks(xRange, yRange) {
    // Dose axis (x): 0-600 default → 30 ticks @ 20 Gy each (or
    // proportional on zoom).
    let xTick = 20;
    if (Array.isArray(xRange) && xRange.length === 2) {
        const xSpan = xRange[1] - xRange[0];
        xTick = _pickTickStep(xSpan, 12, true);
        // Sanity floor: never go below 1 Gy tick spacing.
        if (xTick < 1) xTick = 1;
    }
    // Volume axis (y): 0-100 default → 10 ticks @ 10% each (or
    // proportional on zoom).
    let yTick = 10;
    if (Array.isArray(yRange) && yRange.length === 2) {
        const ySpan = yRange[1] - yRange[0];
        yTick = _pickTickStep(ySpan, 10, false);
        // Sanity floor: at least 1% tick spacing (don't go below).
        if (yTick < 1) yTick = 1;
    }
    return { xTick, yTick };
}

function _resizeDVHChartSoon() {
    const dvhEl = document.getElementById('dvhChart');
    if (!dvhEl || typeof Plotly === 'undefined' || !Plotly.Plots) return;
    dvhEl.style.width = '100%';
    dvhEl.style.height = '100%';
    const run = () => {
        try {
            if (dvhEl.data && dvhEl.data.length && Plotly.relayout) {
                Plotly.relayout(dvhEl, _getDvhResponsiveRelayout(dvhEl));
            }
            Plotly.Plots.resize(dvhEl);
        } catch (_) {}
    };
    requestAnimationFrame(run);
    setTimeout(run, 80);
    setTimeout(run, 250);
    setTimeout(run, 600);
}

function _getDvhResponsiveRelayout(dvhEl) {
    const w = dvhEl?.clientWidth || 900;
    if (w < 680) {
        return {
            margin: { l: 50, r: 14, t: 12, b: 104 },
            legend: {
                orientation: 'h', x: 0, y: -0.24, xanchor: 'left', yanchor: 'top',
                bgcolor: 'rgba(15,23,42,0.62)', bordercolor: 'rgba(148,163,184,0.18)',
                borderwidth: 1, font: { size: 8, color: '#cbd5e1' },
                tracegroupgap: 0, itemwidth: 30,
            },
        };
    }
    return {
        margin: { l: 55, r: 18, t: 10, b: 42 },
        legend: {
            orientation: 'v', x: 0.995, y: 0.995, xanchor: 'right', yanchor: 'top',
            bgcolor: 'rgba(15,23,42,0.72)', bordercolor: 'rgba(148,163,184,0.22)',
            borderwidth: 1, font: { size: 9, color: '#cbd5e1' },
            tracegroupgap: 0, itemwidth: 30,
        },
    };
}

function _setupDvhResponsiveResize(dvhEl) {
    if (!dvhEl || typeof ResizeObserver === 'undefined' || typeof Plotly === 'undefined') return;
    if (dvhEl._dvhResizeObserver) {
        try { dvhEl._dvhResizeObserver.disconnect(); } catch (_) {}
    }
    let timer = null;
    dvhEl._dvhResizeObserver = new ResizeObserver(() => {
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => {
            try {
                if (dvhEl.data && dvhEl.data.length && Plotly.relayout) {
                    Plotly.relayout(dvhEl, _getDvhResponsiveRelayout(dvhEl));
                }
                if (Plotly.Plots) Plotly.Plots.resize(dvhEl);
            } catch (_) {}
        }, 40);
    });
    dvhEl._dvhResizeObserver.observe(dvhEl);
}

function _setupDvhCustomTooltip(dvhEl) {
    if (!dvhEl) return;
    if (dvhEl._dvhTooltipCleanup) {
        try { dvhEl._dvhTooltipCleanup(); } catch (_) {}
        dvhEl._dvhTooltipCleanup = null;
    }
    let tip = dvhEl.querySelector('.dvh-custom-tooltip');
    if (!tip) {
        tip = document.createElement('div');
        tip.className = 'dvh-custom-tooltip';
        dvhEl.appendChild(tip);
    }
    tip.style.cssText = 'position:absolute;display:none;pointer-events:none;z-index:50;' +
        'background:rgba(15,23,42,0.96);border:1px solid rgba(148,163,184,0.55);border-radius:6px;' +
        'padding:6px 9px;font-size:11px;line-height:1.35;color:#e2e8f0;font-family:Inter,system-ui,sans-serif;' +
        'white-space:nowrap;box-shadow:0 8px 18px rgba(0,0,0,0.35);max-width:240px;';

    const onHover = (eventdata) => {
        const points = eventdata.points;
        if (!points || !points.length) { tip.style.display = 'none'; return; }
        const ev = eventdata.event;
        if (!ev) { tip.style.display = 'none'; return; }
        const layout = dvhEl._fullLayout;
        if (!layout || !layout.xaxis || !layout.yaxis) { tip.style.display = 'none'; return; }
        const box = dvhEl.getBoundingClientRect();
        // Plotly's _size is in SVG pixels, while the container may be CSS
        // scaled by the panel splitter. Use the rendered plot overlay rect
        // so the mouse and axis conversion share one viewport coordinate
        // system. This removes the persistent horizontal tooltip offset.
        const plotNode = dvhEl.querySelector('.nsewdrag')
            || dvhEl.querySelector('g.plot')
            || dvhEl.querySelector('.plot');
        const plotBox = plotNode?.getBoundingClientRect?.();
        const hasPlotRect = plotBox && plotBox.width > 1 && plotBox.height > 1;
        const size = layout._size || {};
        const sx = box.width > 0 && dvhEl.clientWidth > 0 ? box.width / dvhEl.clientWidth : 1;
        const sy = box.height > 0 && dvhEl.clientHeight > 0 ? box.height / dvhEl.clientHeight : 1;
        const mx = Number.isFinite(ev.clientX) ? ev.clientX - box.left
            : Number(ev.pageX) - window.scrollX - box.left;
        const my = Number.isFinite(ev.clientY) ? ev.clientY - box.top
            : Number(ev.pageY) - window.scrollY - box.top;
        const plotLeft = hasPlotRect ? plotBox.left - box.left : (size.l || 0) * sx;
        const plotWidth = Math.max(1, hasPlotRect ? plotBox.width : (size.w || 1) * sx);
        const plotTop = hasPlotRect ? plotBox.top - box.top : (size.t || 0) * sy;
        const plotH = Math.max(1, hasPlotRect ? plotBox.height : (size.h || 1) * sy);
        if (mx < plotLeft || mx > plotLeft + plotWidth || my < plotTop || my > plotTop + plotH) {
            tip.style.display = 'none';
            return;
        }
        const xRange = Array.isArray(layout.xaxis.range) && layout.xaxis.range.length >= 2
            ? layout.xaxis.range : [0, 600];
        const xSpan = Number(xRange[1]) - Number(xRange[0]);
        const cursorDose = Number.isFinite(xSpan) && Math.abs(xSpan) > 1e-9
            ? Number(xRange[0]) + ((mx - plotLeft) / plotWidth) * xSpan
            : null;

        let best = null;
        let bestDy = Infinity;
        for (const p of points) {
            if (!p || !Number.isFinite(p.y) || !p.fullData) continue;
            if (p.fullData.visible === false || p.fullData.visible === 'legendonly') continue;
            const yRange = Array.isArray(layout.yaxis.range) && layout.yaxis.range.length >= 2
                ? layout.yaxis.range : [0, 100];
            const ySpan = Number(yRange[1]) - Number(yRange[0]);
            const pyViewport = plotTop + (Number.isFinite(ySpan) && Math.abs(ySpan) > 1e-9
                ? (Number(yRange[1]) - p.y) / ySpan * plotH
                : plotH / 2);
            const dy = Math.abs(pyViewport - my);
            if (dy < bestDy) {
                bestDy = dy;
                best = {
                    name: p.fullData.name || '',
                    x: p.x,
                    y: p.y,
                    color: p.fullData.line?.color || '#e2e8f0',
                    traceX: p.fullData.x,
                    traceY: p.fullData.y,
                };
            }
        }
        if (!best || bestDy > 40) { tip.style.display = 'none'; return; }
        // Plotly's hover point is the nearest sampled vertex, not the
        // physical x-coordinate under the cursor. Interpolate the displayed
        // trace at the cursor's axis value so the tooltip and mouse agree.
        const displayDose = Number.isFinite(cursorDose) ? cursorDose : Number(best.x);
        const interpolatedVolume = _interpolateDvhAtDose(best.traceX, best.traceY, displayDose);
        const displayVolume = Number.isFinite(interpolatedVolume) ? interpolatedVolume : Number(best.y);
        const safeColor = /^#[0-9a-f]{3,8}$/i.test(best.color) || /^rgba?\([0-9.,\s%]+\)$/i.test(best.color) ? best.color : '#e2e8f0';
        tip.innerHTML = `<div style="color:${safeColor};font-weight:700;margin-bottom:2px">${escHtml(best.name)}</div>` +
            `<div>Dose: ${displayDose.toFixed(2)} Gy</div><div>Volume: ${displayVolume.toFixed(1)}%</div>`;
        tip.style.display = 'block';
        const pad = 8, off = 14;
        const tw = tip.offsetWidth || 140, th = tip.offsetHeight || 54;
        let left = mx + off, top2 = my - th / 2;
        if (left + tw + pad > box.width)  left = mx - tw - off;
        if (top2 + th + pad > box.height) top2 = my - th - off;
        tip.style.left = Math.max(pad, Math.min(left, box.width - tw - pad)) + 'px';
        tip.style.top  = Math.max(pad, Math.min(top2, box.height - th - pad)) + 'px';
    };
    const onLeave = () => { tip.style.display = 'none'; };
    dvhEl.addEventListener('mouseleave', onLeave);
    // Use Plotly's native hover to get exact data coordinates (no manual conversion).
    if (typeof dvhEl.on === 'function') {
        dvhEl.on('plotly_hover', onHover);
    }
    dvhEl._dvhTooltipCleanup = () => {
        dvhEl.removeEventListener('mouseleave', onLeave);
        if (typeof dvhEl.removeListener === 'function') {
            try { dvhEl.removeListener('plotly_hover', onHover); } catch (_) {}
        }
        tip.style.display = 'none';
    };
}

function _clampDvhVolume(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return 0;
    return Math.max(0, Math.min(100, n));
}

function _getCurrentPrescriptionGyForDvh() {
    return typeof _getCurrentPrescriptionGy === 'function'
        ? _getCurrentPrescriptionGy()
        : 120;
}

function _buildDvhSignature(dvhData, rxGy) {
    if (!dvhData || typeof dvhData !== 'object') return '';
    const sortedNames = Object.keys(dvhData).sort();
    return sortedNames.map(name => {
        const dvh = dvhData[name] || {};
        return JSON.stringify([
            name,
            dvh.dose_bins || [],
            dvh.volume_pcts || [],
        ]);
    }).join('|') + `|rx:${Number(rxGy || 0).toFixed(4)}`;
}

function _interpolateDvhAtDose(xs, ys, dose) {
    const target = Number(dose);
    if (!Array.isArray(xs) || !Array.isArray(ys) || !Number.isFinite(target)) return null;
    const pairs = [];
    const n = Math.min(xs.length, ys.length);
    for (let i = 0; i < n; i++) {
        const x = Number(xs[i]);
        const y = Number(ys[i]);
        if (Number.isFinite(x) && Number.isFinite(y)) pairs.push([x, _clampDvhVolume(y)]);
    }
    if (!pairs.length) return null;
    pairs.sort((a, b) => a[0] - b[0]);
    if (target <= pairs[0][0]) return pairs[0][1];
    for (let i = 0; i < pairs.length - 1; i++) {
        const [x1, y1] = pairs[i];
        const [x2, y2] = pairs[i + 1];
        if (target <= x2) {
            if (Math.abs(x2 - x1) < 1e-9) return _clampDvhVolume(y2);
            const t = (target - x1) / (x2 - x1);
            return _clampDvhVolume(y1 + t * (y2 - y1));
        }
    }
    return pairs[pairs.length - 1][1];
}

function _smoothDvhCurveForDisplay(doseBins, volPcts, maxSmoothDose = 600) {
    const pairs = [];
    for (let i = 0; i < Math.min(doseBins.length, volPcts.length); i++) {
        const x = Number(doseBins[i]);
        const y = Number(volPcts[i]);
        if (Number.isFinite(x) && Number.isFinite(y)) pairs.push([x, _clampDvhVolume(y)]);
    }
    if (pairs.length < 2) return { x: pairs.map(p => p[0]), y: pairs.map(p => p[1]) };
    pairs.sort((a, b) => a[0] - b[0]);

    const outX = [pairs[0][0]];
    const outY = [pairs[0][1]];
    const appendPoint = (x, y) => {
        const bounded = _clampDvhVolume(y);
        outX.push(x);
        // A cumulative DVH cannot increase with dose. Cubic interpolation can
        // otherwise create small upward overshoots even when values stay <=100.
        outY.push(Math.min(outY[outY.length - 1], bounded));
    };
    const hermite = (p0, p1, p2, p3, t) => {
        const t2 = t * t, t3 = t2 * t;
        return 0.5 * ((2 * p1) +
            (-p0 + p2) * t +
            (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
            (-p0 + 3 * p1 - 3 * p2 + p3) * t3);
    };

    for (let i = 0; i < pairs.length - 1; i++) {
        const [x1, y1] = pairs[i];
        const [x2, y2] = pairs[i + 1];
        const smoothThisSegment = x1 < maxSmoothDose && x2 <= maxSmoothDose && pairs.length >= 4;
        const samples = smoothThisSegment
            ? Math.max(2, Math.min(8, Math.ceil(Math.abs(x2 - x1) / 5)))
            : 1;
        for (let s = 1; s < samples; s++) {
            const t = s / samples;
            appendPoint(x1 + t * (x2 - x1), hermite(
                pairs[Math.max(0, i - 1)][1],
                y1,
                y2,
                pairs[Math.min(pairs.length - 1, i + 2)][1],
                t,
            ));
        }
        appendPoint(x2, y2);
    }
    return { x: outX, y: outY };
}

function drawDVH() {
    uiDebugLog('[drawDVH] called, dvhData:', !!state.dvhData, 'keys:', state.dvhData ? Object.keys(state.dvhData).length : 0);
    const placeholder = document.getElementById('dvhPlaceholder');
    if (!state.dvhData || Object.keys(state.dvhData).length === 0) { uiDebugLog('[drawDVH] NO DATA, returning'); return; }
    placeholder.style.display = 'none';

    // Skip re-render if the data hasn't actually changed. This prevents
    // Plotly's built-in transition animation from "flashing" the curves
    // when refreshPlanningUI fires multiple times in quick succession
    // (e.g. once per SSE step event during planning).
    const rxGy = _getCurrentPrescriptionGyForDvh();
    const _newSig = _buildDvhSignature(state.dvhData, rxGy);
    if (drawDVH._lastSig === _newSig) {
        uiDebugLog('[drawDVH] Same signature, skipping');
        _setupDvhResponsiveResize(document.getElementById('dvhChart'));
        _setupDvhCustomTooltip(document.getElementById('dvhChart'));
        _resizeDVHChartSoon();
        return;
    }
    uiDebugLog('[drawDVH] Rendering DVH with keys:', Object.keys(state.dvhData).slice(0, 5));
    // Render every available structure. Plotly's scrollable legend and the
    // data-tree visibility controls keep large TotalSegmentator cases usable.
    const allEntries = Object.entries(state.dvhData);
    const sorted = allEntries.sort((a, b) => {
        const va = (a[1].volume_pcts && a[1].volume_pcts[0]) || 0;
        const vb = (b[1].volume_pcts && b[1].volume_pcts[0]) || 0;
        return vb - va;
    });
    // Always put CTV/PTV/GTV at index 0 (it owns the fill), then the
    // remaining entries by volume.
    const ctvFirst = sorted.find(([n]) => /^(CTV|PTV|GTV)$/i.test(n));
    const ctvName = ctvFirst ? ctvFirst[0] : null;
    const ctvEntry = ctvFirst;
    const topOthers = sorted.filter(([n]) => !/^(CTV|PTV|GTV)$/i.test(n));
    const picked = ctvFirst ? [ctvFirst, ...topOthers] : topOthers;

    const traces = [];
    let ctvDisplayTrace = null;
    // Fallback palette used only when an organ is NOT in the data tree
    // (rare — usually the data tree is loaded first). Matches the same
    // palette used elsewhere for visual consistency. Extended to 16
    // colors so 30+ organ curves still get visually distinct hues.
    const fallbackColors = [
        '#0ea5e9', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6', '#06b6d4',
        '#f97316', '#ec4899', '#84cc16', '#14b8a6', '#a855f7', '#facc15',
        '#fb7185', '#34d399', '#60a5fa', '#fbbf24',
    ];
    let i = 0;
    for (const [name, dvh] of picked) {
        const doseBins = dvh.dose_bins || [];
        const volPcts = dvh.volume_pcts || [];
        // Use the SAME color as the data tree (and OAR Dose Metrics
        // table) so the user can visually trace an OAR across panels.
        const treeColor = _getOrganColor(name);
        const color = treeColor || fallbackColors[i % fallbackColors.length];
        // Use legendgroup = name so Plotly's legend click toggles
        // the trace visibility (the data tree can also call
        // setGroupVisibility for the same effect).
        // Interpolate only within 0-600 Gy and clamp every generated value to
        // the physically valid 0-100% interval.
        const displaySmooth = _smoothDvhCurveForDisplay(doseBins, volPcts, 600);
        const smoothX = displaySmooth.x;
        const smoothY = displaySmooth.y;
        if (name === ctvName) {
            ctvDisplayTrace = { x: smoothX.slice(), y: smoothY.slice() };
        }
        traces.push({
            x: smoothX,
            y: smoothY,
            type: 'scatter', mode: 'lines', name: name,
            line: { color, width: name === ctvName ? 2.6 : 1.4, shape: 'linear' },
            fill: name === ctvName ? 'tozeroy' : 'none',
            fillcolor: name === ctvName ? 'rgba(14,165,233,0.10)' : undefined,
            hoverinfo: 'none',
            legendgroup: name,
            showlegend: true,
        });
        i++;
    }

    const dvhEl = document.getElementById('dvhChart');
    dvhEl.style.width = '100%';
    dvhEl.style.height = '100%';

    // BUG FIX 2026-06-16: user asked for the DVH chart to default
    // to a FIXED 0–600 Gy x-range (the brachytherapy planning view
    // is typically ≤200 Gy, but the user wants consistent axis
    // comparison across plans). The previous "adaptive" range that
    // snapped to actual data max made the chart look different every
    // time and the Rx line moved around. The reset button restores
    // this 0–600 Gy default.
    const xRange = [0, 600];
    // BUG FIX 2026-06-16: user wants x-axis to default to 20 Gy
    // tick spacing (so 0, 20, 40, 60, ..., 600 — 31 ticks) and
    // y-axis to default to 10% (0, 10, 20, ..., 100 — 11 ticks).
    // The previous 50 Gy / 10% defaults left the y-axis correct
    // but the x-axis too sparse. On zoom, the relayout handler
    // adapts automatically.
    const xTick = 20;

    // PRESCRIPTION REFERENCE MARKER (2026-06-16, user request):
    // Draw a vertical dashed line at the prescription dose and label
    // the CTV coverage AT that dose (i.e. V_Rx = volume of CTV that
    // receives >= Rx Gy). This is the single most important DVH
    // data point for brachytherapy QA — it tells the user "if 120 Gy
    // is your prescription, 97.6% of the CTV is covered".
    //
    // Source: reportForm.planning.prescriptionGy (user-editable in
    // the Report panel) or state.metrics.prescribed_dose * 120 (the
    // DOSE_SCALE constant from planning_pipeline.py). The fallback
    // order is: explicit report form > metrics > 120 Gy default.
    // Compute CTV coverage at Rx on the same displayed curve used by
    // the tooltip, so the fixed Rx marker and hover values agree.
    let ctvRxCoverage = null;
    if (ctvDisplayTrace) {
        ctvRxCoverage = _interpolateDvhAtDose(ctvDisplayTrace.x, ctvDisplayTrace.y, rxGy);
    } else if (ctvEntry && Array.isArray(ctvEntry[1].dose_bins) && Array.isArray(ctvEntry[1].volume_pcts)) {
        ctvRxCoverage = _interpolateDvhAtDose(ctvEntry[1].dose_bins, ctvEntry[1].volume_pcts, rxGy);
    }
    // Build the shapes/annotations arrays. The vertical line is a
    // vertical dashed line at x = rxGy, full height. The marker
    // annotation is at (rxGy, ctvRxCoverage) on the CTV curve so
    // the user sees both the dose and the volume in one label.
    const shapes = [];
    const annotations = [];
    if (rxGy > 0 && rxGy <= xRange[1] * 1.5) {
        shapes.push({
            type: 'line', x0: rxGy, x1: rxGy, y0: 0, y1: 100,
            xref: 'x', yref: 'y',
            line: { color: '#facc15', width: 1.5, dash: 'dash' },
        });
        annotations.push({
            x: rxGy, y: 99,
            xref: 'x', yref: 'y',
            text: `Rx ${rxGy.toFixed(1)} Gy`,
            showarrow: false,
            yanchor: 'bottom',
            xanchor: 'left',
            xshift: 4, yshift: -2,
            font: { color: '#facc15', size: 10, family: 'Inter, sans-serif' },
            bgcolor: 'rgba(15,23,42,0.6)',
        });
        if (ctvRxCoverage !== null && Number.isFinite(ctvRxCoverage)) {
            // Small dot + label at the (Rx, V_Rx) point on the CTV
            // curve. 2026-06-16 user feedback: the dot was too big
            // (6px diameter) and visually competed with the CTV
            // curve itself. Reduced to 4px diameter (±2) so it
            // reads as a clear marker without obscuring the line.
            shapes.push({
                type: 'circle', x0: rxGy - 2, x1: rxGy + 2,
                y0: Math.max(0, ctvRxCoverage - 2), y1: Math.min(100, ctvRxCoverage + 2),
                xref: 'x', yref: 'y',
                fillcolor: '#facc15', line: { color: '#facc15' },
            });
            annotations.push({
                x: rxGy, y: ctvRxCoverage,
                xref: 'x', yref: 'y',
                text: `CTV V${rxGy.toFixed(0)} = ${ctvRxCoverage.toFixed(1)}%`,
                showarrow: true, arrowhead: 2, arrowcolor: '#facc15', arrowwidth: 1,
                ax: 18, ay: -22,
                font: { color: '#facc15', size: 10, family: 'Inter, sans-serif' },
                bgcolor: 'rgba(15,23,42,0.78)',
                bordercolor: '#facc15', borderwidth: 1, borderpad: 3,
            });
        }
    }

    const responsiveLayout = _getDvhResponsiveRelayout(dvhEl);
    return Plotly.react(dvhEl, traces, {
        paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
        font: { color: '#cbd5e1', size: 11, family: 'Inter, sans-serif' },
        margin: responsiveLayout.margin,
        xaxis: {
            title: 'Dose (Gy)',
            gridcolor: '#334155', linecolor: '#475569', tickcolor: '#475569',
            titlefont: { color: '#cbd5e1', size: 10 },
            tickfont: { size: 9, color: '#cbd5e1' },
            zeroline: false,
            range: xRange,
            dtick: xTick,
            tick0: 0,           /* always start ticks at a clean multiple of dtick */
            ticks: 'outside',
            ticklen: 4,
        },
        yaxis: {
            title: 'Volume (%)',
            gridcolor: '#334155', linecolor: '#475569', tickcolor: '#475569',
            titlefont: { color: '#cbd5e1', size: 10 },
            tickfont: { size: 9, color: '#cbd5e1' },
            range: [0, 100],
            // User requested 10% ticks (0, 10, 20, ..., 100). The
            // adaptive relayout handler will only adjust this when the
            // user zooms the y-axis (so the ticks stay 10% at the
            // default 0-100% range).
            dtick: 10,
            zeroline: false,
        },
        showlegend: true,
        // Right-side column legend: 30+ entries arranged in 3 columns
        // so the user can scan all OAR names without the legend
        // wrapping over the plot area. The CTV (first entry) is
        // bolded by a wider line width in the trace itself.
        legend: responsiveLayout.legend,
        shapes, annotations,
        // BUG FIX 2026-06-16 (DVH hover): user complained that the
        // unified hover tooltip showed ALL 30+ legend entries at
        // once (couldn't fit on screen, unreadable). Changed to
        // 'closest' so only the single nearest curve shows its
        // tooltip. This also doubles as the "coordinate readout"
        // the user wants — hover continuously to read off
        // (dose, volume) values for any curve, with no need for
        // the click-to-pick flow.
        hovermode: 'closest',
        hoverdistance: 100,
        dragmode: 'zoom',
    }, {
        responsive: true,
        displayModeBar: true,
        modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d', 'toggleSpikelines'],
        displaylogo: false,
    }).then(() => {
        drawDVH._lastSig = _newSig;
        // Force Plotly to re-measure container after render completes
        _setupDvhResponsiveResize(dvhEl);
        _setupDvhCustomTooltip(dvhEl);
        _resizeDVHChartSoon();
    }).catch(error => {
        drawDVH._lastSig = '';
        console.warn('[drawDVH] Plotly render failed:', error);
    });
}

// ----- refreshPlanningUI -----
// Pull the latest plan summary from the server and re-render every
// downstream view: metrics cards, DVH chart, OAR dose table, data tree,
// dose overlay on slice canvases, 3D seed/dose meshes.
//
// Call this after any planning step finishes (via SSE planning_pipeline
// tool completion, after `runPlanningStep`, after the user explicitly
// clears results, etc.).
//
// IMPORTANT: this function is internally debounced. Even if it's called
// 5 times in 200ms (which happens when the SSE stream emits 5 step
// events for one logical planning_pipeline call), only ONE network
// fetch + render will actually run. This prevents the DVH "flashing"
// and 3D viewer "sinking" effects.
let _refreshDebounce = null;
let _refreshInflight = null;
let _refreshGeneration = 0;
// DEBUG: global diagnostic function — call from browser console
window._debugBrachy = function() {
    const canvas = document.getElementById('canvas3D');
    const dvhEl = document.getElementById('dvhChart');
    const panels = document.querySelectorAll('.panel-content');
    const activePanel = document.querySelector('.panel-content.active');
    uiDebugLog('=== BrachyBot Debug ===');
    uiDebugLog('3D canvas:', canvas ? `${canvas.clientWidth}x${canvas.clientHeight}` : 'NOT FOUND');
    uiDebugLog('3D canvas display:', canvas ? getComputedStyle(canvas).display : 'N/A');
    uiDebugLog('3D canvas parent display:', canvas ? getComputedStyle(canvas.parentElement).display : 'N/A');
    uiDebugLog('scene3D initialized:', scene3D.initialized);
    uiDebugLog('scene3D meshes:', Object.keys(scene3D.meshes));
    uiDebugLog('scene3D renderer:', scene3D.renderer ? `${scene3D.renderer.domElement.width}x${scene3D.renderer.domElement.height}` : 'NONE');
    uiDebugLog('Active panel:', activePanel ? activePanel.id : 'NONE');
    uiDebugLog('Panel tabs:', [...document.querySelectorAll('.panel-tab')].map((t,i) => `[${i}]${t.classList.contains('active')?'*':''} ${t.textContent.trim()}`));
    uiDebugLog('DVH container:', dvhEl ? `${dvhEl.clientWidth}x${dvhEl.clientHeight}` : 'NOT FOUND');
    uiDebugLog('DVH overflow:', dvhEl ? getComputedStyle(dvhEl).overflow : 'N/A');
    const hl = dvhEl?.querySelector('.hoverlayer');
    uiDebugLog('DVH hoverlayer:', hl ? `overflow=${getComputedStyle(hl).overflow}` : 'NOT FOUND');
    uiDebugLog('state.ctPath:', state.ctPath);
    uiDebugLog('state.ctLoaded:', state.ctLoaded);
    uiDebugLog('state.metrics keys:', state.metrics ? Object.keys(state.metrics) : 'null');
    return { canvas, scene3D, activePanel, dvhEl };
};

async function refreshPlanningUI(options = {}) {
    uiDebugLog('[refreshPlanningUI] CALLED, ctLoaded:', state.ctLoaded, 'stack:', new Error().stack?.split('\n').slice(1,3).join(' | '));
    const generation = ++_refreshGeneration;
    // Cancel any in-flight fetch — we'll issue a fresh one.
    if (_refreshInflight) { try { _refreshInflight.abort(); } catch (_) {} }
    if (_refreshDebounce) clearTimeout(_refreshDebounce);
    return new Promise((resolve) => {
        _refreshDebounce = setTimeout(async () => {
            _refreshDebounce = null;
            if (generation !== _refreshGeneration) return resolve();
            try {
                const ctrl = new AbortController();
                _refreshInflight = ctrl;
                const res = await fetch(API + '/planning/results', { signal: ctrl.signal });
                if (!res.ok) { console.warn('[refreshPlanningUI] /planning/results failed:', res.status); _refreshInflight = null; return resolve(); }
                const data = await res.json();
                _refreshInflight = null;
                if (generation !== _refreshGeneration) return resolve();
                if (!data || !data.success) { console.warn('[refreshPlanningUI] data not success:', data); return resolve(); }
                uiDebugLog('[refreshPlanningUI] data received, has_dose:', data.has_dose, 'seeds:', data.seeds?.length, 'has_dvh:', !!data.dvh, 'dvh_keys:', data.dvh ? Object.keys(data.dvh).length : 0, 'metrics_keys:', data.metrics ? Object.keys(data.metrics).length : 0);

                // 1. Metrics cards (V100, D90, etc.) + summary
                if (data.metrics && Object.keys(data.metrics).length > 0) {
                    updateMetrics(data.metrics);
                }
                // Merge top-level planning fields into state.metrics so
                // reportAutoFill and other consumers can read them.
                // total_seeds and num_trajectories are returned at the
                // top level of /api/planning/results, not inside dose_metrics.
                if (data.total_seeds !== undefined) state.metrics.total_seeds = data.total_seeds;
                if (data.num_trajectories !== undefined) state.metrics.num_trajectories = data.num_trajectories;

                // 2. DVH — store data and re-draw chart
                uiDebugLog('[refreshPlanningUI] DVH check:', !!data.dvh, 'keys:', data.dvh ? Object.keys(data.dvh).length : 0);
                if (data.dvh && Object.keys(data.dvh).length > 0) {
                    state.dvhData = data.dvh;
                    uiDebugLog('[refreshPlanningUI] Calling drawDVH()');
                    try {
                        const _dvhPromise = drawDVH();
                        if (_dvhPromise && typeof _dvhPromise.then === 'function') {
                            await _dvhPromise;
                        }
                    } catch (e) { console.warn('[refreshPlanningUI] drawDVH failed:', e); }
                } else {
                    console.warn('[refreshPlanningUI] NO DVH data received');
                }

        // 1b. Re-fetch the IMAGE ANALYSIS panel from /api/header/info.
        // The analysis panel was previously only populated at CT
        // load time, so planning / OAR seg events never refreshed
        // it. Re-pull the header on every planning refresh so the
        // panel shows fresh HU stats, slice counts, and source
        // metadata.
        try {
            const headerResp = await fetch(API + '/header/info', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ct_path: state.ctPath || '' }),
            });
            if (headerResp.ok) {
                const hdata = await headerResp.json();
                if (hdata && hdata.success) {
                    // Mirror into state + imageAnalysisData
                    if (typeof state !== 'undefined') {
                        state.ctDicomTags = hdata.tags || {};
                        state.ctSourceKind = hdata.kind || state.ctSourceKind;
                        state.ctSourceMeta = hdata.meta || {};
                    }
                    // Force the analysis panel to re-render. The
                    // helper handles null-safe updates.
                    try { pullHeaderInfo(state.ctPath || ''); } catch (e) { /* tolerate */ }
                }
            }
        } catch (_) { /* analysis is best-effort */ }

        // 1c. Re-load CTV/OAR LABEL VOLUMES (the masks). The
        // server stores them in agent memory when the
        // segmentation tools run; loadLabelVolumes() reads them
        // back and writes to ctvLabelData/oarLabelData, which
        // the slice overlays + data tree + 3D rendering depend
        // on. Without this re-fetch, the CTV/OAR masks from a
        // chat-triggered planning flow never appear on the
        // viewers and the data tree never marks them loaded.
        if (typeof loadLabelVolumes === 'function') {
            try { await loadLabelVolumes(); } catch (e) { console.warn('loadLabelVolumes failed:', e); }
        }
        // Make sure the data tree reflects whatever labels we
        // now have. Don't clobber the analysis content with a
        // re-render here — that helper handles its own state.

        // 3. OAR dose table (uses metrics.oar_metrics)
        if (data.metrics && data.metrics.oar_metrics) {
            try { updateOARTable(data.metrics.oar_metrics); } catch (e) { console.warn('updateOARTable failed:', e); }
        }

        // 4. Seeds (state.seeds) + 3D mesh re-render + dose overlay
        if (data.seeds) {
            updateSeeds(data.seeds);
        }

        // 4b. Trajectories (parent of seeds in the data tree) — only run
        //     if the server returned the new "trajectories" array. Older
        //     server responses will be ignored (data.tree falls back to
        //     the existing per-seed representation).
        if (data.trajectories) {
            try { updateTrajectories(data.trajectories); } catch (e) { console.warn('updateTrajectories failed:', e); }
        }

        // ═══════════════════════════════════════════════════════════
        // CRITICAL: Switch to viewers panel FIRST so canvas has
        // proper dimensions. Everything below depends on a visible
        // canvas (CT rendering, dose overlay, 3D meshes).
        // ═══════════════════════════════════════════════════════════
        try {
            const viewersTab = document.querySelectorAll('.panel-tab')[2];
            if (options.switchToViewers !== false && viewersTab && !viewersTab.classList.contains('active')) {
                switchPanel('viewers', viewersTab);
                await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
            }
        } catch (e) { console.warn('[refreshPlanningUI] switchPanel FAILED:', e); }

        // ═══════════════════════════════════════════════════════════
        // DOSE OVERLAY: fire-and-forget (non-blocking). The dose
        // data loads asynchronously; the user can start dragging
        // slices immediately — the overlay appears once loaded.
        // ═══════════════════════════════════════════════════════════
        if (data.has_dose) {
            loadDoseOverlay().then(ov => {
                if (ov && ov.shape) {
                    if (state.viewerSettings) {
                        state.viewerSettings.displayMode = 'overlay';
                        state.viewerSettings.showCTV = true;
                        state.viewerSettings.showOAR = true;
                    }
                    if (dataTreeState) {
                        dataTreeState.ctv.visible = true;
                        // OAR group stays visible but all individual organs
                        // are invisible by default (set in updateOrganList).
                        // Users enable specific organs via data tree toggles.
                    }
                    const dm = document.getElementById('displayMode');
                    if (dm) dm.value = 'overlay';
                    const oarCb = document.getElementById('overlayOAR');
                    if (oarCb) oarCb.checked = true;
                    const ctvCb = document.getElementById('overlayCTV');
                    if (ctvCb) ctvCb.checked = true;
                }
            }).catch(e => console.warn('Dose overlay auto-load failed:', e));
        }

        // ═══════════════════════════════════════════════════════════
        // 3D MESHES: run ALL in parallel. Progress is represented by the
        // execution trace/todo list; do not add a second floating spinner.
        // ═══════════════════════════════════════════════════════════
        const _3dStatusBar = document.getElementById('meshPrewarmStatus')
            || document.getElementById('auto3DStatusBar');
        if (_3dStatusBar) _3dStatusBar.remove();

        function _withTimeout(promise, name, ms = 60000) {
            return Promise.race([
                promise,
                new Promise((_, reject) => setTimeout(() => reject(new Error(`${name} timeout after ${ms/1000}s`)), ms))
            ]).catch(e => console.warn(`[3D auto-load] ${name}:`, e.message));
        }

        const _meshPromises = [];
        // Isodose surfaces
        if (data.has_dose) {
            _meshPromises.push(_withTimeout(loadAllIsoSurfaces(), 'Isosurfaces'));
        }
        // CTV + OAR meshes
        _meshPromises.push(
            _withTimeout(loadCTVAndObstacleMeshes(), 'CTV/OAR meshes', 300000)
                .then(() => uiDebugLog('[3D auto-load] CTV/obstacle done. Meshes:', Object.keys(scene3D.meshes).length))
        );
        // Seeds + needles. The authoritative 3D geometry lives behind
        // /planning/seeds_3d, while /planning/results may omit the flat
        // seeds array. Load geometry whenever the result indicates any
        // trajectories or seeds exist.
        const shouldLoadSeedGeometry = ((data.seeds || []).length > 0)
            || ((data.total_seeds || 0) > 0)
            || ((data.num_trajectories || 0) > 0)
            || ((data.trajectories || []).length > 0);
        if (shouldLoadSeedGeometry) {
            _meshPromises.push(
                _withTimeout(loadSeeds3D(), 'Seeds')
                    .then(() => uiDebugLog('[3D auto-load] Seeds done. Meshes:', Object.keys(scene3D.meshes).length))
            );
        }

        // Wait for all 3D mesh loads to complete
        try { if (typeof reportAutoFill === 'function') reportAutoFill(); } catch (_) {}

        await Promise.all(_meshPromises);
        if (generation !== _refreshGeneration) return resolve();
        uiDebugLog('[refreshPlanningUI] Mesh promises done. scene3D.meshes:', Object.keys(scene3D.meshes));
        // No floating indicator to remove; the trace/todo lifecycle remains
        // the single progress surface for this asynchronous work.

        // 4f-2. Re-capture 3D figures AFTER meshes are loaded.
        // autoCaptureReportFigures ran before mesh promises resolved,
        // so the 3D canvas was empty. Now that meshes are in the
        // scene, re-capture both CTV-zoomed and seeds-overview.
        try {
            if (generation !== _refreshGeneration) return resolve();
            const _hasFigures = window.reportForm && window.reportForm.figures;
            const _replaceOrCreate = (axis, title, caption, dataUrl) => {
                if (!_hasFigures || !dataUrl || dataUrl.length < 5000) return;
                const idx = window.reportForm.figures.findIndex(f => f && f.axis === axis);
                const entry = { type: 'screenshot', title, dataUrl, axis, sliceIdx: null, caption, capturedAt: new Date().toISOString() };
                if (idx >= 0) {
                    window.reportForm.figures[idx].dataUrl = dataUrl;
                    window.reportForm.figures[idx].capturedAt = entry.capturedAt;
                } else {
                    window.reportForm.figures.push(entry);
                }
            };
            const lang = (typeof window._i18nLang === 'string') ? window._i18nLang : 'en';
            const _ctvTitle = lang === 'zh' ? '三维靶区重建' : '3D CTV Reconstruction';
            const _ctvCap = lang === 'zh' ? 'CTV 靶区（红色）三维表面重建' : 'CTV tumor (red) 3D surface reconstruction';
            const _seedTitle = lang === 'zh' ? '粒子植入方案' : 'Seed Implant Plan';
            const _seedCap = lang === 'zh' ? '穿刺针道（红色）、放射性粒子（黄色）与 CTV（半透明红色）三维重建' : 'Needle paths (red), radioactive seeds (yellow), and CTV (translucent red) 3D view';

            forceRender3DViewer();

            // 4f-2a. CTV zoomed capture (hide non-CTV meshes)
            const ctvMesh = scene3D.meshes['ctv'] || Object.values(scene3D.meshes).find(m => m?.userData?.type === 'ctv');
            const _savedVis = {};
            try {
                if (ctvMesh && scene3D.camera && scene3D.controls) {
                    for (const [id, mesh] of Object.entries(scene3D.meshes)) {
                        if (!mesh || id === 'ctv') continue;
                        _savedVis[id] = mesh.visible;
                        mesh.visible = false;
                    }
                    if (scene3D.skinMesh) { _savedVis['__skin__'] = scene3D.skinMesh.visible; scene3D.skinMesh.visible = false; }

                    const box = new THREE.Box3().setFromObject(ctvMesh);
                    const center = box.getCenter(new THREE.Vector3());
                    const size = box.getSize(new THREE.Vector3());
                    const maxDim = Math.max(size.x, size.y, size.z);
                    const dist = maxDim * 2.5;
                    scene3D.controls.target.copy(center);
                    scene3D.camera.position.set(center.x + dist * 0.6, center.y + dist * 0.4, center.z + dist * 0.7);
                    scene3D.camera.updateProjectionMatrix();
                    scene3D.controls.update();
                    await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
                    scene3D.renderer.render(scene3D.scene, scene3D.camera);
                    await new Promise(r => requestAnimationFrame(r));
                    const c = document.querySelector('#canvas3D canvas');
                    if (c) _replaceOrCreate('3d_ctv', _ctvTitle, _ctvCap, c.toDataURL('image/png'));
                }
            } finally {
                for (const [id, vis] of Object.entries(_savedVis)) {
                    if (id === '__skin__') { if (scene3D.skinMesh) scene3D.skinMesh.visible = vis; continue; }
                    const mesh = scene3D.meshes[id];
                    if (mesh) mesh.visible = vis;
                }
            }

            // 4f-2b. Seeds overview capture
            fitCameraToScene();
            await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
            scene3D.renderer.render(scene3D.scene, scene3D.camera);
            await new Promise(r => requestAnimationFrame(r));
            const c2 = document.querySelector('#canvas3D canvas');
            if (c2) _replaceOrCreate('3d_seeds', _seedTitle, _seedCap, c2.toDataURL('image/png'));

            // Restore overview camera
            fitCameraToScene();
            uiDebugLog('[3D re-capture] Re-captured CTV + seeds figures');
        } catch (e) { console.warn('[3D re-capture] failed:', e); }

        // 5. Data tree badges ("V100: 91.0%" / "13 seeds") — updateSeeds
        //    + updateMetrics already push the right state; this just
        //    re-renders the tree. Called once more after dose/iso loaded.
        try { renderDataTree(); } catch (e) { /* tree may not be ready */ }

        // 6. Dose overlay on slice canvases — always redraw the 3 slices
        //    after labels + dose are loaded so the masks/dose appear
        //    together (the inline compositing path re-runs on every call).
        if (state.ctLoaded && (ctvLabelData || oarLabelData)) {
            try { loadAllSlices(); } catch (e) { console.warn('loadAllSlices (post-dose) failed:', e); }
        }

        // 6b. Re-capture 2D dose figures at peak dose voxel after dose
        //     overlay is loaded (autoCaptureReportFigures may have run
        //     before dose data was available).
        if (state.doseOverlay && state.doseOverlay.visible && window.reportForm && window.reportForm.figures) {
            try {
                const lang = (typeof window._i18nLang === 'string') ? window._i18nLang : 'en';
                const pv = state.doseOverlay.peakVoxel;
                if (pv) {
                    const axesCfg = [
                        { ax: 'axial', slice: pv.z, axis: 'dose_axial', titleKey: 'doseAxial', capKey: 'doseAxialCap' },
                        { ax: 'sagittal', slice: pv.x, axis: 'dose_sagittal', titleKey: 'doseSagittal', capKey: 'doseSagittalCap' },
                        { ax: 'coronal', slice: pv.y, axis: 'dose_coronal', titleKey: 'doseCoronal', capKey: 'doseCoronalCap' },
                    ];
                    const labels = (lang === 'zh') ? {
                        doseAxial: '轴位剂量分布', doseAxialCap: '最大剂量层面的轴位 CT 叠加剂量热图',
                        doseSagittal: '矢状位剂量分布', doseSagittalCap: '最大剂量层面的矢状位 CT 叠加剂量热图',
                        doseCoronal: '冠状位剂量分布', doseCoronalCap: '最大剂量层面的冠状位 CT 叠加剂量热图',
                    } : {
                        doseAxial: 'Axial Dose Distribution', doseAxialCap: 'Axial CT with dose heatmap at peak dose slice',
                        doseSagittal: 'Sagittal Dose Distribution', doseSagittalCap: 'Sagittal CT with dose heatmap at peak dose slice',
                        doseCoronal: 'Coronal Dose Distribution', doseCoronalCap: 'Coronal CT with dose heatmap at peak dose slice',
                    };

                    const origSlices = { axial: state.slices.axial, sagittal: state.slices.sagittal, coronal: state.slices.coronal };
                    const origOpacity = state.doseOverlay.opacity;
                    state.doseOverlay.opacity = 0.75;

                    for (const cfg of axesCfg) {
                        const slider = document.getElementById('slider' + cfg.ax.charAt(0).toUpperCase() + cfg.ax.slice(1));
                        const maxVal = slider ? parseInt(slider.max) : 200;
                        const clampedSlice = Math.max(0, Math.min(maxVal, Math.round(cfg.slice)));
                        if (slider) slider.value = clampedSlice;
                        updateSlice(cfg.ax, clampedSlice);
                    }
                    await new Promise(r => setTimeout(r, 400));

                    for (const cfg of axesCfg) {
                        const composite = _composite2DViewerCanvas(cfg.ax);
                        if (composite && composite.length > 1000) {
                            const idx = window.reportForm.figures.findIndex(f => f && f.axis === cfg.axis);
                            const entry = { type: 'screenshot', title: labels[cfg.titleKey], dataUrl: composite, axis: cfg.axis, sliceIdx: Math.round(cfg.slice), caption: labels[cfg.capKey], capturedAt: new Date().toISOString() };
                            if (idx >= 0) {
                                window.reportForm.figures[idx].dataUrl = composite;
                                window.reportForm.figures[idx].capturedAt = entry.capturedAt;
                                window.reportForm.figures[idx].sliceIdx = entry.sliceIdx;
                            } else {
                                window.reportForm.figures.push(entry);
                            }
                        }
                    }

                    state.doseOverlay.opacity = origOpacity;
                    for (const [ax, sl] of Object.entries(origSlices)) {
                        const slider = document.getElementById('slider' + ax.charAt(0).toUpperCase() + ax.slice(1));
                        if (slider) slider.value = sl;
                        updateSlice(ax, sl);
                    }
                    await new Promise(r => setTimeout(r, 100));
                }

                // Also re-capture DVH if available
                const dvhEl = document.getElementById('dvhChart');
                if (dvhEl && typeof Plotly !== 'undefined' && typeof Plotly.toImage === 'function') {
                    const imgData = await Plotly.toImage(dvhEl, { format: 'png', width: 900, height: 450 });
                    if (imgData && imgData.length > 1000) {
                        const dvhIdx = window.reportForm.figures.findIndex(f => f && f.axis === 'dvh');
                        const dvhEntry = { type: 'screenshot', title: lang === 'zh' ? 'DVH 剂量体积直方图' : 'DVH — Dose Volume Histogram', dataUrl: imgData, axis: 'dvh', sliceIdx: null, caption: lang === 'zh' ? 'CTV 及各 OAR 的剂量-体积曲线' : 'Dose–volume curves for CTV and all OARs', capturedAt: new Date().toISOString() };
                        if (dvhIdx >= 0) {
                            window.reportForm.figures[dvhIdx].dataUrl = imgData;
                            window.reportForm.figures[dvhIdx].capturedAt = dvhEntry.capturedAt;
                        } else {
                            window.reportForm.figures.push(dvhEntry);
                        }
                    }
                }
                // Re-render report if figures changed
                if (typeof renderReportEditor === 'function') renderReportEditor();
                if (typeof _updateReportPreview === 'function') _updateReportPreview();
            } catch (e) { console.warn('[Report] 2D/DVH re-capture failed:', e); }
        }

        // 7. 3D viewer force-re-size + camera-fit. The previous version
        //    called `render3D()` (a LEGACY function that does
        //    `canvas.innerHTML = ''` and creates a brand-new scene) —
        //    which clobbered the modern scene3D that addMeshToScene,
        //    loadSeeds3D, and loadDoseIsosurface had been populating.
        //    That's why the user saw "no seeds, no needles, no CTV,
        //    no isosurface" in the 3D viewer after a chat-driven
        //    planning run, even though all the auto-load calls had
        //    returned data successfully. forceRender3DViewer is the
        //    correct call: it just re-sizes the renderer and fits the
        //    camera to whatever meshes are already in scene3D.
        //
        // 2026-06-16 fix: previously gated on `state.ctLoaded`. After
        // a page refresh, ctLoaded starts at false but the server
        // already has seeds/needles/iso meshes in memory, and
        // `loadSeeds3D` + `loadAllIsoSurfaces` repopulate scene3D on
        // this same refresh pass. Forcing a render WITHOUT the
        // ctLoaded gate means the 3D viewer immediately shows the
        // meshes that were just loaded, even before the user
        // re-loads the CT client-side. Same pattern as the dose
        // overlay fix above.
        try {
            uiDebugLog('[3D auto-load] forceRender3DViewer... initialized:', scene3D.initialized, 'meshes:', Object.keys(scene3D.meshes).length);
            forceRender3DViewer();
        } catch (e) { console.warn('[3D auto-load] forceRender3DViewer FAILED:', e); }

        // 9. Refresh the Image Analysis panel so the new metrics,
        //    CTV/OAR label counts, and per-label volumes show up.
        //    Without this, the panel only updated at CT load time and
        //    stayed stale through the entire planning run. The panel
        //    reads from state.metrics and ctvLabelData/oarLabelData,
        //    both of which were refreshed in steps 1c and 1d above.
        try { if (typeof updateImageAnalysis === 'function') updateImageAnalysis(); } catch (_) {}

        // 10. Build the Clinical Evaluation panel with the full
        //     metrics grid + flagged issues list + clickable references
        //     to TG-43 / GEC-ESTRO / ICRU / ABS / NCCN / PICC. This
        //     is the "show me every metric + every problem + every
        //     authoritative citation" panel the user asked for; the
        //     LLM final reply still exists but now points at this
        //     panel for the structured data.
        try { if (typeof updateClinicalEvaluation === 'function') updateClinicalEvaluation(); } catch (_) {}

        // 11. Auto-capture report figures (DVH, 3D, segmentation)
        //    AFTER all meshes are loaded and DVH is drawn. Without
        //    this, the report only gets figures when the user opens
        //    the report panel or exports PDF.
        //    WAIT for dose overlay to load first (fire-and-forget above).
        try {
            if (typeof loadDoseOverlay === 'function' && data.has_dose && !state.doseOverlay) {
                await loadDoseOverlay();
            }
        } catch (_) {}
        try {
            if (generation !== _refreshGeneration) return resolve();
            if (typeof autoCaptureReportFigures === 'function') {
                await autoCaptureReportFigures();
            }
        } catch (_) {}

        // 12. Auto-fill report form with planning data.
        //     Previously the user had to manually click "Auto-fill"
        //     after every planning run. Now we trigger it automatically.
        try {
            if (typeof Report !== 'undefined' && Report.autoFill && Report.autoFill.fromAll) {
                Report.autoFill.fromAll();
            }
        } catch (_) {}

            } catch (e) {
                if (e && e.name !== 'AbortError') console.warn('refreshPlanningUI failed:', e);
            } finally {
                resolve();
            }
        }, 80);  // 80ms debounce: enough to coalesce 5-10 SSE step events into one fetch
    });
}

/******** METRICS ********/
function updateMetrics(metrics) {
    state.metrics = metrics || {};

    const setMetric = (id, val, displayMax, suffix = '') => {
        const el = document.getElementById('val' + id);
        const card = document.getElementById('card' + id);
        const bar = document.getElementById('bar' + id);
        if (!el) return;
        // Treat undefined / null / NaN as "no data" → render "--".
        // Also reset bar to 0% and clear the status classes so a stale
        // good/warn/bad tint from a previous plan doesn't linger.
        if (val === undefined || val === null || Number.isNaN(val)) {
            el.textContent = '--';
            if (bar) { bar.style.width = '0%'; bar.className = 'metric-bar-fill'; }
            if (card) { card.className = 'metric-card'; }
            return;
        }
        el.textContent = (typeof val === 'number' ? (Number.isInteger(val) ? val : val.toFixed(1)) : val) + suffix;
        if (Number.isFinite(displayMax) && displayMax > 0 && bar) {
            const pct = Math.min(100, Math.max(0, (val / displayMax) * 100));
            bar.style.width = pct + '%';
            bar.className = 'metric-bar-fill';
            if (card) card.className = 'metric-card';
        }
    };

    const m = state.metrics;
    // Reference: Zhiyuan BrachyPlan metrics.
    // Pass the raw value (don't `|| 0` first) so setMetric can detect
    // "no data" via undefined/NaN and render "--" instead of "0%".
    setMetric('V100', m.v100 !== undefined ? m.v100 * 100 : undefined, 100, '%');
    setMetric('V150', m.v150 !== undefined ? m.v150 * 100 : undefined, 100, '%');
    setMetric('V200', m.v200 !== undefined ? m.v200 * 100 : undefined, 100, '%');
    const fallbackDoseScale = typeof DEFAULT_DOSE_SCALE_GY === 'number' ? DEFAULT_DOSE_SCALE_GY : 1;
    const doseDisplayMax = Math.max(1, (typeof _getDoseScaleGy === 'function' ? _getDoseScaleGy() : fallbackDoseScale) * 2);
    setMetric('D90', m.d90, doseDisplayMax, ' Gy');
    setMetric('D95', m.d95, doseDisplayMax, ' Gy');
    setMetric('Score', m.plan_score, 100, '');

    document.getElementById('sumSeeds').textContent = m.total_seeds != null ? m.total_seeds : '--';
    // Planning voxel counts can belong to a resampled dose grid. Never combine
    // them with the original CT spacing; use segmentation volume metadata only.
    const ctvVolumeCm3 = m.ctv_volume_mm3 != null ? Number(m.ctv_volume_mm3) / 1000 : NaN;
    document.getElementById('sumCTV').textContent = Number.isFinite(ctvVolumeCm3) ? ctvVolumeCm3.toFixed(1) + ' cm³' : '--';
    document.getElementById('sumD90').textContent = m.d90 != null ? Number(m.d90).toFixed(1) + ' Gy' : '--';
    document.getElementById('sumV100').textContent = m.v100 != null ? (Number(m.v100) * 100).toFixed(1) + '%' : '--';
}

// Look up the data-tree color for an organ by name. Falls back to a
// muted gray if the organ isn't in the data tree. The returned color is
// a CSS color string (hex like "#ff6644" or rgb(...)) so it can be used
// directly in inline styles.
const _FALLBACK_OAR_LABEL_NAMES = {
    201: 'artery',
    202: 'vein',
    203: 'pancreas',
};

function _extractGenericOARLabelId(name) {
    const s = String(name || '').trim().toLowerCase().replace(/[-\s]+/g, '_');
    const m = s.match(/^(oar|organ|label)_(\d+)$/);
    return m ? parseInt(m[2], 10) : null;
}

function _resolveOARDisplayName(name, metric = {}) {
    const metricLabel = metric && (metric.label_id ?? metric.labelId ?? metric.organ_label ?? metric.organLabel);
    const labelId = Number.isFinite(Number(metricLabel))
        ? Number(metricLabel)
        : _extractGenericOARLabelId(name);

    if (labelId !== null && Number.isFinite(labelId)) {
        const meta = organMetaFromServer && (organMetaFromServer[labelId] || organMetaFromServer[String(labelId)]);
        if (meta && meta.name && !/^(oar|organ|label)[_\s-]?\d+$/i.test(meta.name)) return meta.name;
        const fallback = _FALLBACK_OAR_LABEL_NAMES[labelId];
        if (fallback) return fallback;
        if (dataTreeState && dataTreeState.organs) {
            const match = dataTreeState.organs.find(o =>
                Number(o.labelId) === labelId ||
                Number(String(o.id || '').replace(/\D+/g, '')) === labelId
            );
            if (match && match.label && !/^(oar|organ|label)[_\s-]?\d+$/i.test(match.label)) return match.label;
        }
        return `Organ ${labelId}`;
    }

    return String(name || '');
}

function _getOrganColor(name) {
    if (!dataTreeState || !dataTreeState.organs) return null;
    const displayName = _resolveOARDisplayName(name);
    // Direct match (label may be canonical)
    for (const o of dataTreeState.organs) {
        if (o.label === displayName || o.label === name) return o.color;
    }
    // Fuzzy match: data tree names sometimes have "(...)" suffixes or
    // differ by case from DVH/OAR names.
    const ln = displayName.toLowerCase().replace(/[^a-z0-9]/g, '');
    for (const o of dataTreeState.organs) {
        const lo = (o.label || '').toLowerCase().replace(/[^a-z0-9]/g, '');
        if (lo === ln) return o.color;
        if (lo.includes(ln) || ln.includes(lo)) return o.color;
    }
    return null;
}

function updateOARTable(oarMetrics) {
    const tbody = document.getElementById('oarTableBody');
    if (!oarMetrics || Object.keys(oarMetrics).length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-dim);padding:0.75rem;">No OAR data</td></tr>';
        return;
    }
    tbody.innerHTML = Object.entries(oarMetrics).map(([name, m]) => {
        const displayName = _resolveOARDisplayName(name, m);
        const d01 = m.d0_1cc || 0;
        const d1 = m.d1cc || 0;
        const d2 = m.d2cc || 0;
        const d90 = m.d90 || 0;
        const d95 = m.d95 || 0;
        const v100 = m.v100 || 0;
        const vol = m.volume_cm3 ?? null;
        // Color code: highlight high dose values
        const d2ccClass = d2 > 100 ? 'style="color:var(--danger);font-weight:600;"' : '';
        // Color the organ name with the SAME color used in the data tree
        // and DVH curve, so the user can visually trace each OAR across
        // all 3 panels.
        const organColor = _getOrganColor(displayName);
        const nameStyle = organColor
            ? `style="max-width:60px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600;border-left:3px solid ${organColor};padding-left:6px;color:${organColor};"`
            : `style="max-width:60px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"`;
        return `<tr>
            <td ${nameStyle} title="${escHtml(displayName)}">${escHtml(displayName)}</td>
            <td>${d01.toFixed(1)}</td>
            <td>${d1.toFixed(1)}</td>
            <td ${d2ccClass}>${d2.toFixed(1)}</td>
            <td>${d90.toFixed(1)}</td>
            <td>${d95.toFixed(1)}</td>
            <td>${v100.toFixed(1)}</td>
            <td style="color:var(--text-dim);">${typeof vol === 'number' ? vol.toFixed(1) : vol}</td>
        </tr>`;
    }).join('');
}

// Build a structured clinical evaluation panel with all metrics,
// flagged issues, and authoritative references. 2026-06-16:
// replaces the user complaint that the LLM final response was too
// terse and lacked citation links.
//
// BUG FIX 2026-06-17: URLs were wrong (TG-43 linked to TG-229's
// Wiley page, GEC-ESTRO linked to committee page not handbook).
// Now uses the correct authoritative URLs, consistent with
// REPORT_REFERENCES defined below.
const _GUIDELINE_REFS = {
    'TG43':     { name: 'AAPM TG-229 / TG-43 Update — Brachytherapy Source Dosimetry', url: 'https://www.aapm.org/pubs/reports/RPT_229.pdf', year: 2020 },
    'GEC_ESTRO':{ name: 'GEC-ESTRO Handbook of Brachytherapy (2nd ed.)', url: 'https://www.estro.org/Science/Guidelines', year: 2022 },
    'ABS':      { name: 'ABS Brachytherapy Consensus Guidelines', url: 'https://www.americanbrachytherapy.org/guidelines', year: 2023 },
    'ICRU89':   { name: 'ICRU Report 89 — Prescribing, Recording, and Reporting Brachytherapy', url: 'https://www.icru.org/report/icru-report-89-prescribing-recording-and-reporting-brachytherapy-for-cancer-of-the-cervix/', year: 2016 },
    'NCCN_PANC': { name: 'NCCN Clinical Practice Guidelines — Pancreatic Adenocarcinoma', url: 'https://www.nccn.org/guidelines', year: 2024 },
    'PICC':     { name: 'Chinese Expert Consensus on CT-guided ¹²⁵I Seed Implantation (PICC, 2018)', url: 'https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5988490/', year: 2018 },
};

function _refLinkHtml(key) {
    const r = _GUIDELINE_REFS[key];
    if (!r) return '';
    // The href is a clickable link so the user can jump to the
    // source. target="_blank" opens in a new tab; rel=noopener is
    // the modern security minimum.
    return `<a href="${r.url}" target="_blank" rel="noopener" style="color:var(--primary);text-decoration:underline;margin-left:4px;">${key}${r.year ? ` (${r.year})` : ''}</a>`;
}

// Build the clinical evaluation HTML from the latest metrics. Called
// after each refreshPlanningUI() pass so the panel stays current.
function updateClinicalEvaluation() {
    const host = document.getElementById('clinicalEvaluationContent');
    if (!host) return;
    const metrics = state.metrics || {};
    const oarMetrics = metrics.oar_metrics || {};
    const rxGy = _getCurrentPrescriptionGyForDvh();
    const h = (typeof escHtml === 'function')
        ? escHtml
        : (s) => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

    if (!metrics.v100 && !metrics.d90 && !Object.keys(oarMetrics).length) {
        host.innerHTML = '<div style="color:var(--text-dim);font-style:italic;">Detailed evaluation will appear here after planning completes.</div>';
        return;
    }

    const fmt = (value, digits = 1, suffix = '') => {
        if (value === null || value === undefined || Number.isNaN(Number(value))) return '--';
        return `${Number(value).toFixed(digits)}${suffix}`;
    };
    const headline = [
        ['Plan Score', metrics.plan_score != null ? `${Number(metrics.plan_score).toFixed(0)} / 100` : '--'],
        ['D90', metrics.d90 != null ? `${Number(metrics.d90).toFixed(2)} Gy` : '--'],
        ['V100', metrics.v100 != null ? `${(Number(metrics.v100) * 100).toFixed(1)} %` : '--'],
        ['V150', metrics.v150 != null ? `${(Number(metrics.v150) * 100).toFixed(1)} %` : '--'],
        ['V200', metrics.v200 != null ? `${(Number(metrics.v200) * 100).toFixed(1)} %` : '--'],
        ['D2 (max)', metrics.d2 != null ? `${Number(metrics.d2).toFixed(2)} Gy` : '--'],
        ['Dmean', metrics.dmean != null ? `${Number(metrics.dmean).toFixed(2)} Gy` : '--'],
        ['CI', metrics.ci != null ? Number(metrics.ci).toFixed(2) : '--'],
        ['HI', metrics.hi != null ? Number(metrics.hi).toFixed(2) : '--'],
        ['Seeds', state.seeds ? state.seeds.length : '--'],
        ['Prescription', `${Number(rxGy).toFixed(0)} Gy`],
    ];

    const observations = [];
    if (metrics.v100 != null) observations.push(`CTV V100 observed at ${(Number(metrics.v100) * 100).toFixed(1)}%. Compare against source-backed criteria for this tumor site.`);
    if (metrics.d90 != null) observations.push(`CTV D90 observed at ${Number(metrics.d90).toFixed(2)} Gy. Current report prescription is ${Number(rxGy).toFixed(0)} Gy.`);
    if (metrics.v200 != null) observations.push(`CTV V200 observed at ${(Number(metrics.v200) * 100).toFixed(1)}%. Inspect corresponding hot spots in 2D/3D before changing seeds.`);
    if (metrics.plan_score != null) observations.push(`Plan score is ${Number(metrics.plan_score).toFixed(0)}/100. Treat this as an advisory QA ranking signal only.`);

    const topOars = Object.entries(oarMetrics)
        .filter(([_, m]) => m)
        .sort((a, b) => ((b[1].d2cc || b[1].dmax || b[1].max_dose || 0) - (a[1].d2cc || a[1].dmax || a[1].max_dose || 0)))
        .slice(0, 8);
    topOars.forEach(([rawName, m]) => {
        const name = _resolveOARDisplayName(rawName, m);
        const dmax = Number(m.dmax || m.max_dose || m.Dmax || 0);
        const d2cc = Number(m.d2cc || 0);
        observations.push(`${name}: Dmax ${fmt(dmax, 2, ' Gy')}, D2cc ${fmt(d2cc, 2, ' Gy')}. Interpret using clinical_kb/plan_config OAR limits.`);
    });
    if (!topOars.length) observations.push('No OAR dose metrics are available yet. Run OAR segmentation and dose evaluation before OAR review.');

    const headlineHtml = `
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:6px;margin-bottom:10px;">
            ${headline.map(([k, v]) => `
                <div style="background:var(--bg-2);border:1px solid var(--border-hairline);border-radius:6px;padding:6px 8px;">
                    <div style="font-size:0.58rem;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.05em;">${h(k)}</div>
                    <div style="font-size:0.86rem;color:var(--text);font-weight:600;">${h(v)}</div>
                </div>
            `).join('')}
        </div>
    `;
    const observationsHtml = `
        <div style="margin-bottom:10px;">
            <div style="font-weight:600;color:var(--text);margin-bottom:4px;">Planning Review Items (${observations.length})</div>
            <ul style="margin:0;padding-left:16px;line-height:1.6;">
                ${observations.map(msg => `<li><span>${h(msg)}</span></li>`).join('')}
            </ul>
        </div>
    `;
    const refsHtml = `
        <div style="border-top:1px solid var(--border-hairline);padding-top:8px;">
            <div style="font-weight:600;color:var(--text);margin-bottom:4px;">Source policy</div>
            <div style="line-height:1.7;font-size:0.66rem;color:var(--text-secondary);">
                <div>Clinical pass/fail labels require retrieved <code>clinical_kb</code> evidence or explicit <code>plan_config</code> constraints.</div>
                <div>General references: AAPM TG-43/TG-229 ${_refLinkHtml('TG43')}, ICRU Report 89 ${_refLinkHtml('ICRU89')}, ABS ${_refLinkHtml('ABS')}, NCCN ${_refLinkHtml('NCCN_PANC')}.</div>
            </div>
        </div>
    `;
    host.innerHTML = headlineHtml + observationsHtml + refsHtml;
}

function updateSeeds(seeds) {
    state.seeds = (seeds || []).map(seed => ({
        ...seed,
        trajectory_id: _normalizeTrajectoryId(seed.trajectory_id),
    }));
    if (typeof dataTreeState !== 'undefined' && dataTreeState.seeds) {
        dataTreeState.seeds.loaded = !!(state.seeds && state.seeds.length > 0);
        dataTreeState.seeds.visible = dataTreeState.seeds.loaded;
    }
    // Populate planning-level seeds so renderDataTree() shows them in
    // the Planning group (either under Trajectories or as a flat list).
    if (typeof dataTreeState !== 'undefined' && dataTreeState.planning) {
        dataTreeState.planning.seeds = (state.seeds || []).map(s => ({
            id: s.id || s._id || `seed_${Math.random().toString(36).slice(2, 8)}`,
            position: s.pos || s.position,
            trajectory_id: s.trajectory_id,
            direction: s.direction,
            visible: true,
            opacity: 1.0,
            color: '#ffcc00',
        }));
    }
}

// Update planning trajectories (parent nodes for seeds in the data tree).
// Each trajectory is a needle path with one or more seeds along it. The
// data tree will render: Planning → Trajectories → [Trajectory 1 → Seed 1.1,
// Seed 1.2, ...] → [Trajectory 2 → ...] → Isosurfaces, Dose Overlay.
function updateTrajectories(trajectories) {
    state.trajectories = trajectories || [];
    if (typeof dataTreeState === 'undefined' || !dataTreeState.planning) return;
    // Group seeds by trajectory_id so the tree builder can do a single
    // groupChildren() call per trajectory.
    const grouped = {};
    (state.seeds || []).forEach(s => {
        const t = _normalizeTrajectoryId(s.trajectory_id);
        if (!grouped[t]) grouped[t] = [];
        grouped[t].push(s);
    });
    dataTreeState.planning.trajectories = (trajectories || []).map(t => {
        const trajId = _normalizeTrajectoryId(t.id);
        const childSeeds = grouped[trajId] || [];
        return {
            id: trajId,
            index: t.index,
            entry: t.entry,
            target: t.target,
            visible: true,
            opacity: 0.8,
            color: '#88ccff',
            seeds: childSeeds,
        };
    });
    dataTreeState.planning.trajectoriesLoaded = (trajectories || []).length > 0;
}

/******** FINAL REPORT ********/

// Reference materials and authoritative sources for the final report.
// These are real public references to GB (national standard) and
// international brachytherapy guidelines. When the LLM cites a claim,
// it must reference at least one of these so the user can verify the
// source via the embedded hyperlink.
const REPORT_REFERENCES = {
    // National (Chinese) standards
    GBZ_T2017: {
        title: 'GBZ/T 201.7-2015 — Radiation therapy planning — Part 7: Brachytherapy',
        publisher: 'National Health Commission of the PRC (NHFPC)',
        url: 'http://www.nhc.gov.cn/wjw/s9492/201503/9c8f9c14a3d348508ae84e0a12fb12fe.shtml',
        year: 2015,
        jurisdiction: 'CN',
    },
    // International guidelines
    ABS_ABS: {
        title: 'American Brachytherapy Society (ABS) Consensus Guidelines',
        publisher: 'American Brachytherapy Society',
        url: 'https://www.americanbrachytherapy.org/guidelines',
        year: 2023,
        jurisdiction: 'INTL',
    },
    ESTRO: {
        title: 'ESTRO/ESGO/ESP Guidelines on brachytherapy in gynecological cancers',
        publisher: 'European Society for Radiotherapy & Oncology',
        url: 'https://www.estro.org/Science/Guidelines',
        year: 2023,
        jurisdiction: 'INTL',
    },
    GEC_ESTRO: {
        title: 'GEC-ESTRO Handbook of Brachytherapy (2nd ed.)',
        publisher: 'GEC-ESTRO',
        url: 'https://www.estro.org/About/ESTRO-organisation/Groups/GEC-ESTRO',
        year: 2022,
        jurisdiction: 'INTL',
    },
    AAPM_TG43: {
        title: 'AAPM Task Group Report 229 / TG-43 Update — Dosimetry of Brachytherapy Sources',
        publisher: 'American Association of Physicists in Medicine',
        url: 'https://www.aapm.org/pubs/reports/RPT_229.pdf',
        year: 2020,
        jurisdiction: 'INTL',
    },
    ICRU_89: {
        title: 'ICRU Report 89 — Prescribing, Recording, and Reporting Brachytherapy',
        publisher: 'International Commission on Radiation Units & Measurements',
        url: 'https://www.icru.org/report/icru-report-89-prescribing-recording-and-reporting-brachytherapy-for-cancer-of-the-cervix/',
        year: 2016,
        jurisdiction: 'INTL',
    },
    NCCN: {
        title: 'NCCN Clinical Practice Guidelines in Oncology — various cancer types',
        publisher: 'National Comprehensive Cancer Network',
        url: 'https://www.nccn.org/guidelines',
        year: 2024,
        jurisdiction: 'INTL',
    },
    PANCR_ASCO: {
        title: 'ASCO Guidelines — Treatment of Pancreatic Cancer',
        publisher: 'American Society of Clinical Oncology',
        url: 'https://ascopubs.org/journal/jco',
        year: 2024,
        jurisdiction: 'INTL',
    },
    IAEA_HB: {
        title: 'IAEA Human Health Series No. 30 — Brachytherapy',
        publisher: 'International Atomic Energy Agency',
        url: 'https://www.iaea.org/publications/8756/the-transition-from-2d-brachytherapy-to-3d-high-dose-rate-brachytherapy',
        year: 2015,
        jurisdiction: 'INTL',
    },
};

// All references used in the report, with a short citation tag.
// Each anchor is referenced as [ref:KEY] inline in the report body.
const REPORT_CITATIONS = {
    GYN_GUIDE: 'ABS Consensus Guidelines for interstitial HDR brachytherapy for gynecologic and other pelvic cancers (2020).',
    PANCREAS_TRIAL: 'ASCO Guidelines 2024 — systemic therapy for metastatic pancreatic adenocarcinoma.',
    PROSTATE: 'ABS Consensus Guideline on permanent prostate brachytherapy (2017).',
    HEAD_NECK: 'ABS Head & Neck Brachytherapy Consensus Guidelines (2018).',
    ICRU_DOSE: 'ICRU Report 89 (2016) — Prescribing, Recording, and Reporting Brachytherapy.',
    AAPM_DOSE: 'AAPM Task Group Report 229 (2020) — Dose calculation formalisms for brachytherapy sources.',
    GBZ_DOSE: 'GBZ/T 201.7-2015 — Treatment planning for brachytherapy (PRC National Health Commission).',
    IAEA_SAFETY: 'IAEA SRS No. 60 — Radiation Protection and Safety in Medical Uses of Ionizing Radiation.',
    ESTRO_DVH: 'GEC-ESTRO recommendations on DVH parameters for plan comparison (2018).',
    NCCN_PANC: 'NCCN Guidelines for Pancreatic Adenocarcinoma, version 2.2024.',
};

// Build a single combined "References" list for the report appendix, in
// the order citations first appear in the body. Returns an array of
// {key, citation, url, title, publisher, year} objects, deduped.
function _buildReportReferenceList(usedKeys) {
    const seen = new Set();
    const out = [];
    // Map from CITATIONS key to underlying REFERENCE key (some cite the
    // same source multiple ways).
    const link = {
        GYN_GUIDE: 'ABS_ABS',
        PANCREAS_TRIAL: 'PANCR_ASCO',
        PROSTATE: 'ABS_ABS',
        HEAD_NECK: 'ABS_ABS',
        ICRU_DOSE: 'ICRU_89',
        AAPM_DOSE: 'AAPM_TG43',
        GBZ_DOSE: 'GBZ_T2017',
        IAEA_SAFETY: 'IAEA_HB',
        ESTRO_DVH: 'GEC_ESTRO',
        NCCN_PANC: 'NCCN',
    };
    usedKeys.forEach(k => {
        if (seen.has(k)) return;
        const refKey = link[k] || k;
        const ref = REPORT_REFERENCES[refKey];
        if (!ref) return;
        seen.add(k);
        out.push({ citeKey: k, refKey, ...ref });
    });
    return out;
}

// ============== REPORT EDITOR + LIVE PREVIEW (PM-grade) ==============
//
// Architecture: two-pane editor (left = editable form, right = live
// PDF-style preview). Both panes read from a single `reportForm` object
// (defined below) and re-render when fields change. The form supports:
//   - Auto-fill from NIfTI metadata + planning data
//   - Manual editing of any field
//   - Bilingual UI (zh / en) with auto-detect from user input
//   - Tumor-site templates (pancreas, prostate, head_neck, gynecology, liver)
//   - Reference manager (add/edit/delete external sources)
//   - Figure/screenshot manager (insert viewer screenshots + file uploads)
//   - Markdown text fields for narrative sections (interpretation, safety, etc.)
//   - Validation: required fields highlighted, missing list shown in status bar
//   - Auto-save to localStorage every 5s
//   - Export: PDF (browser print), HTML (standalone), Markdown, JSON
//   - Import JSON form state for re-editing later
//   - Shareable URL: form state encoded in URL hash
//   - Chat commands: "/report zh", "/report en", "/report add reference ..."
//
// The system is fully self-contained — no server roundtrip needed after
// the initial auto-fill. PM note: every field the user could conceivably
// want to edit is editable; nothing is "view-only" in the form.

// ----- 1. Static reference catalog (default citations) -----
const REPORT_REFERENCES_CATALOG = {
    GYN_GUIDE:    { citeKey: 'GYN_GUIDE',    title: 'ABS Consensus Guidelines for interstitial HDR brachytherapy for gynecologic and other pelvic cancers (2020)', publisher: 'American Brachytherapy Society', url: 'https://www.americanbrachytherapy.org/guidelines', year: 2020, jurisdiction: 'INTL' },
    PANCREAS_TRIAL: { citeKey: 'PANCREAS_TRIAL', title: 'ASCO Guidelines 2024 — systemic therapy for metastatic pancreatic adenocarcinoma', publisher: 'American Society of Clinical Oncology', url: 'https://ascopubs.org/journal/jco', year: 2024, jurisdiction: 'INTL' },
    PROSTATE:     { citeKey: 'PROSTATE',     title: 'ABS Consensus Guideline on permanent prostate brachytherapy (2017)', publisher: 'American Brachytherapy Society', url: 'https://www.americanbrachytherapy.org/guidelines', year: 2017, jurisdiction: 'INTL' },
    HEAD_NECK:    { citeKey: 'HEAD_NECK',    title: 'ABS Head & Neck Brachytherapy Consensus Guidelines (2018)', publisher: 'American Brachytherapy Society', url: 'https://www.americanbrachytherapy.org/guidelines', year: 2018, jurisdiction: 'INTL' },
    ICRU_DOSE:    { citeKey: 'ICRU_DOSE',    title: 'ICRU Report 89 — Prescribing, Recording, and Reporting Brachytherapy', publisher: 'International Commission on Radiation Units & Measurements', url: 'https://www.icru.org/report/icru-report-89-prescribing-recording-and-reporting-brachytherapy-for-cancer-of-the-cervix/', year: 2016, jurisdiction: 'INTL' },
    AAPM_DOSE:    { citeKey: 'AAPM_DOSE',    title: 'AAPM Task Group Report 229 — Dose calculation formalisms for brachytherapy sources', publisher: 'American Association of Physicists in Medicine', url: 'https://www.aapm.org/pubs/reports/RPT_229.pdf', year: 2020, jurisdiction: 'INTL' },
    GBZ_DOSE:     { citeKey: 'GBZ_DOSE',     title: 'GBZ/T 201.7-2015 — 放射治疗计划 第7部分：近距离治疗', publisher: '国家卫生和计划生育委员会 (NHFPC)', url: 'http://www.nhc.gov.cn/wjw/s9492/201503/9c8f9c14a3d348508ae84e0a12fb12fe.shtml', year: 2015, jurisdiction: 'CN' },
    IAEA_SAFETY:  { citeKey: 'IAEA_SAFETY',  title: 'IAEA SRS No. 60 — Radiation Protection and Safety in Medical Uses of Ionizing Radiation', publisher: 'International Atomic Energy Agency', url: 'https://www.iaea.org/publications/1110/radiation-protection-and-safety-in-medical-uses-of-ionizing-radiation', year: 2014, jurisdiction: 'INTL' },
    ESTRO_DVH:    { citeKey: 'ESTRO_DVH',    title: 'GEC-ESTRO recommendations on DVH parameters for plan comparison', publisher: 'GEC-ESTRO', url: 'https://www.estro.org/About/ESTRO-organisation/Groups/GEC-ESTRO', year: 2018, jurisdiction: 'INTL' },
    NCCN_PANC:    { citeKey: 'NCCN_PANC',    title: 'NCCN Guidelines for Pancreatic Adenocarcinoma, version 2.2024', publisher: 'National Comprehensive Cancer Network', url: 'https://www.nccn.org/guidelines', year: 2024, jurisdiction: 'INTL' },
    ASTRO:        { citeKey: 'ASTRO',        title: 'ASTRO Clinical Practice Guideline — Brachytherapy for locally advanced / recurrent gynecologic cancers', publisher: 'American Society for Radiation Oncology', url: 'https://www.astro.org/Patient-Care-and-Research/Clinical-Practice-Statements', year: 2024, jurisdiction: 'INTL' },
    GBZ_PRO:      { citeKey: 'GBZ_PRO',      title: 'GBZ 121-2002 — 后装γ源近距离治疗卫生防护标准', publisher: '中华人民共和国卫生部', url: 'http://www.nhc.gov.cn/wjw/c100051/list.shtml', year: 2002, jurisdiction: 'CN' },
};

// ----- 2. Tumor-site templates -----
const REPORT_TEMPLATES = {
    pancreas: {
        i125: true,
        prescriptionGy: 120,
        interpretation: {
            zh: 'Pancreatic seed brachytherapy plan. Observed coverage and OAR metrics must be interpreted with retrieved clinical_kb evidence or explicit plan_config constraints for pancreatic disease.',
            en: 'Pancreatic seed brachytherapy plan. Observed coverage and OAR metrics must be interpreted with retrieved clinical_kb evidence or explicit plan_config constraints for pancreatic disease.',
        },
        defaultReferences: ['NCCN_PANC', 'PANCREAS_TRIAL', 'GBZ_DOSE', 'ICRU_DOSE', 'AAPM_DOSE', 'ESTRO_DVH'],
    },
    prostate: {
        i125: true,
        prescriptionGy: 145,
        interpretation: {
            zh: 'Prostate seed brachytherapy plan. Dose and OAR review require source-backed prostate constraints before any pass/fail statement.',
            en: 'Prostate seed brachytherapy plan. Dose and OAR review require source-backed prostate constraints before any pass/fail statement.',
        },
        defaultReferences: ['PROSTATE', 'ICRU_DOSE', 'AAPM_DOSE', 'ESTRO_DVH'],
    },
    head_neck: {
        i125: false,
        prescriptionGy: 60,
        interpretation: {
            zh: 'Head and neck brachytherapy plan. Critical-structure limits must be retrieved from clinical_kb or supplied in plan_config for this specific site.',
            en: 'Head and neck brachytherapy plan. Critical-structure limits must be retrieved from clinical_kb or supplied in plan_config for this specific site.',
        },
        defaultReferences: ['HEAD_NECK', 'ICRU_DOSE', 'AAPM_DOSE'],
    },
    gynecology: {
        i125: false,
        prescriptionGy: 85,
        interpretation: {
            zh: 'Gynecologic brachytherapy plan. EQD2 and OAR interpretation require protocol-specific, source-backed criteria.',
            en: 'Gynecologic brachytherapy plan. EQD2 and OAR interpretation require protocol-specific, source-backed criteria.',
        },
        defaultReferences: ['GYN_GUIDE', 'ASTRO', 'ICRU_DOSE', 'ESTRO_DVH'],
    },
    liver: {
        i125: true,
        prescriptionGy: 120,
        interpretation: {
            zh: 'Liver seed brachytherapy plan. Coverage and gastrointestinal/biliary OAR constraints require retrieved clinical_kb evidence or explicit plan_config limits.',
            en: 'Liver seed brachytherapy plan. Coverage and gastrointestinal/biliary OAR constraints require retrieved clinical_kb evidence or explicit plan_config limits.',
        },
        defaultReferences: ['ICRU_DOSE', 'AAPM_DOSE', 'ESTRO_DVH'],
    },
};

// ----- 3. Bilingual UI strings (single source of truth) -----
const REPORT_STRINGS = {
    zh: {
        reportTitle: '放射性粒子植入治疗计划报告',
        reportSubtitle: 'Brachytherapy Treatment Plan Report',
        // BUG FIX 2026-06-17 (report header redesign): the previous
        // header showed "Brachybot / Brachybot / Brachytherapy
        // Planning Platform · AI-Assisted" — three lines of redundant
        // marketing copy. Now the header carries real institutional
        // identity: SJTU + Ruijin Hospital (the development partners).
        hospitalName: '上海交通大学医学院附属瑞金医院',
        hospitalNameEn: 'Ruijin Hospital, Shanghai Jiao Tong University School of Medicine',
        hospitalDept: '放射治疗科  ·  AI 辅助近距离治疗规划',
        hospitalDeptEn: 'Department of Radiation Oncology · AI-Assisted Brachytherapy Planning',
        hospitalAddress: '上海市黄浦区瑞金二路 197 号  ·  200025',
        hospitalContact: 'https://github.com/Haitao-Lee/BrachyBot.git',
        editFormTab: '✏️ 编辑表单',
        previewTab: '📄 预览',
        viewHint: '点击 预览 标签查看 A4 多页文档',
        confidentiality: '机密 · Confidential',
        page: '第',
        pageOf: '页 / 共',
        pages: '页',
        noData: '—',
        patientInfo: '患者信息',
        name: '姓名',
        gender: '性别',
        age: '年龄',
        id: '住院号',
        department: '科室',
        ward: '病区',
        bed: '床号',
        modality: '影像模态',
        scanDate: '扫描日期',
        accession: '影像号',
        radiologist: '扫描医师',
        scanner: '扫描设备',
        title: '职称 / 角色',
        planDate: '计划日期',
        notes: '备注',
        tumorType: '肿瘤类型',
        planner: '计划医师',
        prescription: '处方剂量',
        dwellPositions: '驻留位数',
        reviewerName: '审核医师',
        reviewerTitle: '审核医师职称 / 角色',
        diagnosis: '临床诊断',
        clinicalHistory: '简要病史',
        priorTreatment: '既往治疗',
        organ: '器官',
        status: '评价',
        pass: '达标',
        fail: '未达标',
        ctvVolume: 'CTV 体积',
        oarCount: '危及器官数',
        segmentationModel: '分割模型',
        technique: '治疗技术',
        prescriptionDose: '处方剂量',
        totalSeeds: '粒子总数',
        totalActivity: '总活度',
        trajectories: '穿刺路径',
        method: '方法学',
        qaNotes: '质保备注',
        metric: '指标',
        value: '数值',
        reference: '参考',
        figCaption: '图',
        disclaimer: '免责声明',
        disclaimerText: '本报告由 BrachyBot 自动化生成，仅供临床医生参考。最终治疗决策应由多学科会诊（MDT）团队结合患者具体情况、影像学特征和临床判断做出。报告中所有剂量指标均基于 AI 模型预测，需经物理师复核确认。',
        physicianPlanner: '主治医师',
        physicianReviewer: '审核医师',
        stampSuffix: '专用章',
        statusPass: '达标',
        statusWarn: '可接受',
        statusFail: '偏高',
        section1: '一、病例摘要',
        section2: '二、计划质量评估',
        section3: '三、危及器官剂量',
        section4: '四、靶区与处方',
        section5: '五、剂量学评估与临床解读',
        section6: '六、安全与质量控制',
        section7: '七、参考文献',
        section8: '八、声明',
        section9: '九、医师签名',
        sectionN1: '影像学资料',
        sectionN2: '靶区勾画',
        sectionN3: '治疗计划',
        sectionN4: '剂量分布',
        methodSteps: [
            '<b>CT 影像输入</b>：CT 序列重采样到 1 mm³ 等向性体素',
            '<b>CTV/OAR 分割</b>：nnUNet 深度学习模型自动分割',
            '<b>穿刺路径规划</b>：基于 Zhiyuan v2 算法的 candidate-trajectory + 自适应过滤',
            '<b>种子规划</b>：贪心迭代放置策略，每个种子贡献 myDoseNet CNN 剂量分布',
            '<b>剂量计算</b>：基于 myDoseNet CNN 代理模型',
            '<b>DVH 评估</b>：按 ICRU 89 / GEC-ESTRO 标准',
        ],
        units: { Gy: 'Gy', mm3: 'mm³', percent: '%', cc: 'cc', mm: 'mm', MBq: 'MBq' },
        planScoreLabel: '计划评分',
        seedsUnitWord: '颗',
        trajUnitWord: '条',
        defaultGender: '男',
        defaultDepartment: '放射治疗科',
        defaultTechniqueI125: '放射性粒子植入 (¹²⁵I Radioactive Seed Implantation)',
        defaultTechniqueHDR: 'HDR 近距离治疗 (Ir-192)',
        planSectionTitle: '治疗计划',
        imagingSectionTitle: '影像学资料',
        caseSectionTitle: '病例摘要',
        oarSectionTitle: '危及器官剂量',
        addButtonLabel: '+ Add / 添加',
        figuresSectionTitle: '🖼️ Figures / 图片',
        planScoreFormLabel: 'Plan score / 计划评分',
    },
    en: {
        reportTitle: 'Brachytherapy Treatment Plan Report',
        reportSubtitle: 'AI-Assisted Radioactive Seed Implantation Plan',
        hospitalName: 'Ruijin Hospital, SJTU School of Medicine',
        hospitalNameEn: 'Shanghai Jiao Tong University',
        hospitalDept: 'Department of Radiation Oncology · AI-Assisted Brachytherapy Planning',
        hospitalDeptEn: 'Joint Lab: SJTU × Ruijin Hospital',
        hospitalAddress: '197 Ruijin Er Rd, Shanghai 200025, China',
        hospitalContact: 'https://github.com/Haitao-Lee/BrachyBot.git',
        editFormTab: '✏️ Edit Form',
        previewTab: '📄 Preview',
        viewHint: 'Click Preview tab to see the multi-page A4 document',
        confidentiality: 'Confidential',
        page: 'Page',
        pageOf: ' of ',
        pages: '',
        noData: '—',
        patientInfo: 'Patient Information',
        name: 'Name',
        gender: 'Gender',
        age: 'Age',
        id: 'Hospital ID',
        department: 'Department',
        ward: 'Ward',
        bed: 'Bed',
        modality: 'Modality',
        scanDate: 'Scan date',
        accession: 'Accession #',
        radiologist: 'Radiologist',
        scanner: 'Scanner',
        title: 'Role / title',
        planDate: 'Planning date',
        notes: 'Notes',
        tumorType: 'Tumor type',
        planner: 'Planning physician',
        prescription: 'Prescribed dose',
        dwellPositions: 'Dwell positions',
        reviewerName: 'Review physician',
        reviewerTitle: 'Reviewer role / title',
        diagnosis: 'Clinical diagnosis',
        clinicalHistory: 'Brief history',
        priorTreatment: 'Prior treatment',
        organ: 'Organ',
        status: 'Status',
        pass: 'Pass',
        fail: 'Fail',
        ctvVolume: 'CTV volume',
        oarCount: 'OAR count',
        segmentationModel: 'Segmentation model',
        technique: 'Technique',
        prescriptionDose: 'Prescribed dose',
        totalSeeds: 'Total seeds',
        totalActivity: 'Total activity',
        trajectories: 'Trajectories',
        method: 'Methodology',
        qaNotes: 'QA Notes',
        metric: 'Metric',
        value: 'Value',
        reference: 'Reference',
        figCaption: 'Figure',
        disclaimer: 'Disclaimer',
        disclaimerText: 'This report is auto-generated by BrachyBot and is intended for clinical reference only. Final treatment decisions must be made by the MDT team based on the patient\'s specific condition. All dosimetric metrics are based on AI model predictions and require medical physicist verification.',
        physicianPlanner: 'Planning Physician',
        physicianReviewer: 'Review Physician',
        stampSuffix: 'Official Seal',
        statusPass: 'Pass',
        statusWarn: 'Acceptable',
        statusFail: 'Above',
        section1: '1. Patient Summary',
        section2: '2. Plan Quality Assessment',
        section3: '3. Organ-at-Risk Dose',
        section4: '4. Target & Prescription',
        section5: '5. Dosimetric Evaluation & Clinical Interpretation',
        section6: '6. Safety & Quality Control',
        section7: '7. References',
        section8: '8. Disclaimer',
        section9: '9. Physician Signatures',
        sectionN1: 'Imaging Data',
        sectionN2: 'Target Delineation',
        sectionN3: 'Treatment Plan',
        sectionN4: 'Dose Distribution',
        methodSteps: [
            '<b>CT input</b>: resampled to 1 mm³ isotropic voxels',
            '<b>CTV/OAR segmentation</b>: nnUNet deep-learning auto-segmentation',
            '<b>Trajectory planning</b>: Zhiyuan v2 candidate-trajectory + adaptive filter',
            '<b>Seed planning</b>: greedy iterative placement with per-seed myDoseNet CNN dose contributions',
            '<b>Dose calculation</b>: myDoseNet CNN surrogate (checkpoint calibration recorded with the plan)',
            '<b>DVH evaluation</b>: per ICRU 89 / GEC-ESTRO standards',
        ],
        units: { Gy: 'Gy', mm3: 'mm³', percent: '%', cc: 'cc', mm: 'mm', MBq: 'MBq' },
        planScoreLabel: 'Plan score',
        seedsUnitWord: 'seeds',
        trajUnitWord: 'trajectories',
        defaultGender: 'Male',
        defaultDepartment: 'Radiation Oncology',
        defaultTechniqueI125: 'Radioactive Seed Implantation (¹²⁵I)',
        defaultTechniqueHDR: 'HDR Brachytherapy (Ir-192)',
        planSectionTitle: 'Treatment Plan',
        imagingSectionTitle: 'Imaging Data',
        caseSectionTitle: 'Patient Summary',
        oarSectionTitle: 'Organ-at-Risk Dose',
        addButtonLabel: '+ Add',
        figuresSectionTitle: '🖼️ Figures',
        planScoreFormLabel: 'Plan score',
    },
};
