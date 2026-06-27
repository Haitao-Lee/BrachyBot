#!/usr/bin/env python3
"""Comprehensive Playwright test: upload CT → run planning → test all 4 bugs."""
import time, json, os
from playwright.sync_api import sync_playwright

CT_PATH = "/home/lht/snap/brachyplan/data/RuijinCases/10/CTyuanaju.nii"
BASE = "http://localhost:5000"
SD = "/home/lht/snap/brachyplan/BrachyBot/test_screenshots"
os.makedirs(SD, exist_ok=True)

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        console_logs = []
        page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))

        # === PHASE 1: Upload CT ===
        print("=== PHASE 1: Upload CT ===")
        page.goto(BASE, wait_until="networkidle")
        time.sleep(2)
        file_input = page.query_selector('input[type="file"]')
        if file_input:
            file_input.set_input_files(CT_PATH)
        time.sleep(5)
        ct_loaded = page.evaluate("state?.ctLoaded ?? false")
        print(f"CT loaded: {ct_loaded}")
        assert ct_loaded, "CT failed to load"
        page.screenshot(path=f"{SD}/01_ct_loaded.png")

        # === PHASE 2: Run planning via chat ===
        print("\n=== PHASE 2: Run planning via chat ===")
        chat_input = page.query_selector('#chatInput')
        if chat_input:
            chat_input.fill("Perform brachytherapy planning for a pancreatic tumor patient")
            chat_input.press("Enter")
            print("Sent planning request")
        else:
            print("ERROR: chatInput not found")
            browser.close()
            return

        # Wait for planning to complete (up to 10 minutes)
        # Check for ACTUAL data (has_dose=true), not just success=true
        print("Waiting for planning to complete...")
        for i in range(120):
            time.sleep(5)
            has_results = page.evaluate("""async () => {
                try {
                    const res = await fetch('/api/planning/results');
                    const data = await res.json();
                    return data?.has_dose === true || data?.total_seeds > 0;
                } catch(e) { return false; }
            }""")
            if has_results:
                print(f"  Planning results available after {(i+1)*5}s")
                break
            if i % 6 == 0:
                print(f"  Still waiting... ({(i+1)*5}s)")
        else:
            print("  Planning timed out after 600s")

        time.sleep(5)  # Extra wait for frontend to process

        # Manually trigger refreshPlanningUI if not auto-triggered
        manually_refreshed = page.evaluate("""async () => {
            if (typeof refreshPlanningUI === 'function') {
                try { await refreshPlanningUI(); return true; } catch(e) { return e.message; }
            }
            return 'refreshPlanningUI not found';
        }""")
        print(f"Manual refreshPlanningUI: {manually_refreshed}")
        time.sleep(3)
        page.screenshot(path=f"{SD}/02_planning_done.png")

        # === PHASE 3: Check state after planning ===
        print("\n=== PHASE 3: State after planning ===")
        state = page.evaluate("""() => {
            return {
                ctLoaded: state?.ctLoaded,
                hasDoseOverlay: !!state?.doseOverlay,
                doseOverlayVisible: state?.doseOverlay?.visible,
                doseOverlaySlices: state?.doseOverlay ? Object.keys(state.doseOverlay.slices).length : 0,
                scene3DInitialized: scene3D?.initialized,
                scene3DMeshCount: scene3D ? Object.keys(scene3D.meshes).length : 0,
                scene3DMeshIds: scene3D ? Object.keys(scene3D.meshes) : [],
                dataTreeCTVLoaded: dataTreeState?.ctv?.loaded,
                dataTreeOrgans: dataTreeState?.organs?.length,
                dataTreeSeedsLoaded: dataTreeState?.seeds?.loaded,
                volumeShape: volumeShape,
            };
        }""")
        print(f"State: {json.dumps(state, indent=2)}")

        # === PHASE 4: Bug 2 — DVH tooltip ===
        print("\n=== PHASE 4: Bug 2 — DVH tooltip ===")
        # Switch to metrics panel first
        page.evaluate("switchPanel('metrics', document.querySelectorAll('.panel-tab')[1])")
        time.sleep(1)
        dvh_data = page.evaluate("""() => {
            const chart = document.getElementById('dvhChart');
            const plotDiv = chart?.querySelector('.js-plotly-plot');
            const hoverLayer = chart?.querySelector('.hoverlayer');
            const dvhPanel = document.querySelector('.dvh-panel');
            const dvhContainer = document.querySelector('.dvh-container');
            return {
                chartExists: !!chart,
                plotExists: !!plotDiv,
                hoverLayerExists: !!hoverLayer,
                panelOverflow: dvhPanel ? getComputedStyle(dvhPanel).overflow : 'N/A',
                containerOverflow: dvhContainer ? getComputedStyle(dvhContainer).overflow : 'N/A',
                hoverLayerOverflow: hoverLayer ? getComputedStyle(hoverLayer).overflow : 'N/A',
                hasData: typeof state !== 'undefined' && state.dvhData && Object.keys(state.dvhData).length > 0,
                dvhDataKeys: typeof state !== 'undefined' && state.dvhData ? Object.keys(state.dvhData).length : 0,
            };
        }""")
        print(f"DVH: {json.dumps(dvh_data, indent=2)}")
        page.screenshot(path=f"{SD}/03_dvh_panel.png")

        # Try hovering over DVH chart to trigger tooltip
        if dvh_data.get('plotExists'):
            plot_box = page.query_selector('#dvhChart .js-plotly-plot')
            if plot_box:
                box = plot_box.bounding_box()
                if box:
                    # Hover over the middle of the chart
                    page.mouse.move(box['x'] + box['width'] * 0.3, box['y'] + box['height'] * 0.5)
                    time.sleep(1)
                    page.screenshot(path=f"{SD}/04_dvh_hover.png")

                    # Check hoverlabel
                    hover_state = page.evaluate("""() => {
                        const hoverLabel = document.querySelector('.hoverlayer .hovertext');
                        if (!hoverLabel) return 'No hover label visible';
                        const bgRect = hoverLabel.querySelector('rect');
                        const texts = hoverLabel.querySelectorAll('text');
                        return {
                            exists: true,
                            rectBBox: bgRect ? {
                                x: bgRect.getAttribute('x'),
                                y: bgRect.getAttribute('y'),
                                width: bgRect.getAttribute('width'),
                                height: bgRect.getAttribute('height'),
                            } : null,
                            textCount: texts.length,
                            textPositions: Array.from(texts).map(t => ({
                                x: t.getAttribute('x'),
                                y: t.getAttribute('y'),
                                text: t.textContent?.substring(0, 40),
                            })),
                            hoverLabelTransform: hoverLabel.getAttribute('transform'),
                        };
                    }""")
                    print(f"Hover state: {json.dumps(hover_state, indent=2)}")

        # === PHASE 5: Bug 3 — 2D dose map ===
        print("\n=== PHASE 5: Bug 3 — 2D dose map ===")
        page.evaluate("switchPanel('viewers', document.querySelectorAll('.panel-tab')[2])")
        time.sleep(2)

        # Check dose overlay state
        dose_state = page.evaluate("""() => {
            if (!state?.doseOverlay) return 'No dose overlay';
            return {
                visible: state.doseOverlay.visible,
                shape: state.doseOverlay.shape,
                slicesCached: Object.keys(state.doseOverlay.slices).length,
                doseMax: state.doseOverlay.doseMax,
                doseMin: state.doseOverlay.doseMin,
                opacity: state.doseOverlay.opacity,
            };
        }""")
        print(f"Dose state: {json.dumps(dose_state, indent=2) if isinstance(dose_state, dict) else dose_state}")

        # Check dose canvas
        for axis in ['Axial', 'Sagittal', 'Coronal']:
            canvas_info = page.evaluate(f"""() => {{
                const canvas = document.getElementById('doseOverlayCanvas{axis}');
                if (!canvas) return {{ exists: false }};
                const ctx = canvas.getContext('2d');
                const sampleSize = 50;
                const imageData = ctx.getImageData(0, 0, Math.min(canvas.width, sampleSize), Math.min(canvas.height, sampleSize));
                let nonZero = 0;
                for (let i = 0; i < imageData.data.length; i += 4) {{
                    if (imageData.data[i] > 0 || imageData.data[i+1] > 0 || imageData.data[i+2] > 0) nonZero++;
                }}
                const sliceCanvas = document.getElementById('sliceCanvas{axis}');
                return {{
                    exists: true,
                    pixelW: canvas.width,
                    pixelH: canvas.height,
                    displayW: canvas.style.width,
                    displayH: canvas.style.height,
                    displayLeft: canvas.style.left,
                    displayTop: canvas.style.top,
                    display: getComputedStyle(canvas).display,
                    zIndex: getComputedStyle(canvas).zIndex,
                    position: getComputedStyle(canvas).position,
                    nonZeroPixels: nonZero,
                    sliceCanvasExists: !!sliceCanvas,
                    sliceCanvasDisplay: sliceCanvas?.style?.display,
                }};
            }}""")
            print(f"  {axis} dose canvas: {json.dumps(canvas_info, indent=2)}")

        page.screenshot(path=f"{SD}/05_dose_initial.png")

        # Change slice and check if dose disappears
        print("\n--- Changing axial slice to 10 ---")
        page.evaluate("updateSlice('axial', 10)")
        time.sleep(2)
        dose_after = page.evaluate("""() => {
            const canvas = document.getElementById('doseOverlayCanvasAxial');
            if (!canvas) return 'Canvas not found!';
            const ctx = canvas.getContext('2d');
            const imageData = ctx.getImageData(0, 0, Math.min(canvas.width, 50), Math.min(canvas.height, 50));
            let nonZero = 0;
            for (let i = 0; i < imageData.data.length; i += 4) {
                if (imageData.data[i] > 0 || imageData.data[i+1] > 0 || imageData.data[i+2] > 0) nonZero++;
            }
            return { nonZeroPixels: nonZero, sliceIndex: 10 };
        }""")
        print(f"Dose at slice 10: {json.dumps(dose_after, indent=2) if isinstance(dose_after, dict) else dose_after}")
        page.screenshot(path=f"{SD}/06_dose_slice_10.png")

        print("\n--- Changing axial slice to 30 ---")
        page.evaluate("updateSlice('axial', 30)")
        time.sleep(2)
        dose_after2 = page.evaluate("""() => {
            const canvas = document.getElementById('doseOverlayCanvasAxial');
            if (!canvas) return 'Canvas not found!';
            const ctx = canvas.getContext('2d');
            const imageData = ctx.getImageData(0, 0, Math.min(canvas.width, 50), Math.min(canvas.height, 50));
            let nonZero = 0;
            for (let i = 0; i < imageData.data.length; i += 4) {
                if (imageData.data[i] > 0 || imageData.data[i+1] > 0 || imageData.data[i+2] > 0) nonZero++;
            }
            return { nonZeroPixels: nonZero, sliceIndex: 30 };
        }""")
        print(f"Dose at slice 30: {json.dumps(dose_after2, indent=2) if isinstance(dose_after2, dict) else dose_after2}")
        page.screenshot(path=f"{SD}/07_dose_slice_30.png")

        # Rapid slice changes (stress test)
        print("\n--- Rapid slice changes (stress test) ---")
        for s in [5, 15, 25, 35, 45]:
            page.evaluate(f"updateSlice('axial', {s})")
            time.sleep(0.3)
        time.sleep(2)
        dose_rapid = page.evaluate("""() => {
            const canvas = document.getElementById('doseOverlayCanvasAxial');
            if (!canvas) return 'Canvas not found!';
            const ctx = canvas.getContext('2d');
            const imageData = ctx.getImageData(0, 0, Math.min(canvas.width, 50), Math.min(canvas.height, 50));
            let nonZero = 0;
            for (let i = 0; i < imageData.data.length; i += 4) {
                if (imageData.data[i] > 0 || imageData.data[i+1] > 0 || imageData.data[i+2] > 0) nonZero++;
            }
            return { nonZeroPixels: nonZero, currentSlice: 45 };
        }""")
        print(f"Dose after rapid: {json.dumps(dose_rapid, indent=2) if isinstance(dose_rapid, dict) else dose_rapid}")
        page.screenshot(path=f"{SD}/08_dose_rapid.png")

        # === PHASE 6: Bug 4 — 3D viewer ===
        print("\n=== PHASE 6: Bug 4 — 3D viewer ===")
        scene3d = page.evaluate("""() => {
            return {
                initialized: scene3D?.initialized,
                meshCount: scene3D ? Object.keys(scene3D.meshes).length : 0,
                meshIds: scene3D ? Object.keys(scene3D.meshes) : [],
                hasScene: !!scene3D?.scene,
                hasCamera: !!scene3D?.camera,
                hasRenderer: !!scene3D?.renderer,
                canvasExists: !!document.getElementById('canvas3D'),
                canvasSize: {
                    w: document.getElementById('canvas3D')?.clientWidth,
                    h: document.getElementById('canvas3D')?.clientHeight,
                },
            };
        }""")
        print(f"3D scene: {json.dumps(scene3d, indent=2)}")
        page.screenshot(path=f"{SD}/09_3d_viewer.png")

        # === PHASE 7: Console logs ===
        print("\n=== PHASE 7: Console logs ===")
        relevant = [l for l in console_logs if any(k in l.lower() for k in ['dose', 'dvh', '3d', 'mesh', 'ctv', 'oar', 'overlay', 'error', 'fail', 'warn', 'hard-block', 'dedup'])]
        print(f"Total: {len(console_logs)}, Relevant: {len(relevant)}")
        for log in relevant[-30:]:
            print(f"  {log}")
        with open(f"{SD}/console_logs.txt", "w") as f:
            for log in console_logs:
                f.write(log + "\n")

        browser.close()
        print("\n=== DONE ===")

if __name__ == "__main__":
    run()
