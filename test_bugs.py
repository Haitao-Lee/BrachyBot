#!/usr/bin/env python3
"""Playwright test to diagnose all 4 bugs."""
import time, json, os
from playwright.sync_api import sync_playwright

CT_PATH = "/home/lht/snap/brachyplan/data/RuijinCases/10/CTyuanaju.nii"
BASE = "http://localhost:5000"
SCREENSHOTS_DIR = "/home/lht/snap/brachyplan/BrachyBot/test_screenshots"
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        # Collect ALL console logs
        console_logs = []
        page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))

        print("=== Step 1: Open page ===")
        page.goto(BASE, wait_until="networkidle")
        time.sleep(2)
        page.screenshot(path=f"{SCREENSHOTS_DIR}/01_initial.png")
        print(f"Page title: {page.title()}")

        # Check if page loaded correctly
        body_text = page.inner_text("body")
        print(f"Body contains 'BrachyBot': {'BrachyBot' in body_text}")

        print("\n=== Step 2: Upload CT file ===")
        # Find the file input
        file_input = page.query_selector('input[type="file"]')
        if file_input:
            file_input.set_input_files(CT_PATH)
            print(f"Uploaded: {CT_PATH}")
            time.sleep(3)
            page.screenshot(path=f"{SCREENSHOTS_DIR}/02_after_upload.png")
        else:
            print("ERROR: No file input found!")
            # Try clicking browse button
            browse_btn = page.query_selector('text=Browse')
            if browse_btn:
                print("Found Browse button, trying file chooser...")
                with page.expect_file_chooser() as fc_info:
                    browse_btn.click()
                file_chooser = fc_info.value
                file_chooser.set_files(CT_PATH)
                time.sleep(3)
                page.screenshot(path=f"{SCREENSHOTS_DIR}/02_after_upload.png")

        print("\n=== Step 3: Wait for CT to load ===")
        # Wait for CT to be loaded (look for canvas or viewer)
        for i in range(30):
            time.sleep(2)
            has_canvas = page.query_selector('canvas#sliceCanvasAxial')
            if has_canvas:
                is_visible = page.evaluate("document.getElementById('sliceCanvasAxial')?.style.display !== 'none'")
                print(f"  Attempt {i+1}: Canvas found, visible={is_visible}")
                if is_visible:
                    break
            else:
                print(f"  Attempt {i+1}: No canvas yet")
        page.screenshot(path=f"{SCREENSHOTS_DIR}/03_ct_loaded.png")

        print("\n=== Step 4: Check initial state ===")
        # Check what's in memory
        state_check = page.evaluate("""() => {
            const result = {};
            result.ctLoaded = typeof state !== 'undefined' ? state.ctLoaded : 'N/A';
            result.hasDoseOverlay = typeof state !== 'undefined' ? !!state.doseOverlay : false;
            result.doseOverlayVisible = typeof state !== 'undefined' ? state.doseOverlay?.visible : false;
            result.hasCtvLabelData = typeof ctvLabelData !== 'undefined' ? !!ctvLabelData : false;
            result.hasOarLabelData = typeof oarLabelData !== 'undefined' ? !!oarLabelData : false;
            result.scene3DInitialized = typeof scene3D !== 'undefined' ? scene3D.initialized : false;
            result.scene3DMeshCount = typeof scene3D !== 'undefined' ? Object.keys(scene3D.meshes).length : 0;
            result.volumeDataExists = typeof volumeData !== 'undefined' ? !!volumeData : false;
            result.volumeShape = typeof volumeShape !== 'undefined' ? JSON.stringify(volumeShape) : 'N/A';
            return result;
        }""")
        print(f"State: {json.dumps(state_check, indent=2)}")

        print("\n=== Step 5: Test DVH tooltip (Bug 2) ===")
        # First check if DVH chart exists
        dvh_exists = page.evaluate("!!document.getElementById('dvhChart')")
        print(f"DVH chart exists: {dvh_exists}")
        if dvh_exists:
            # Check DVH panel overflow CSS
            dvh_overflow = page.evaluate("""() => {
                const panel = document.querySelector('.dvh-panel');
                const container = document.querySelector('.dvh-container');
                return {
                    panelOverflow: panel ? getComputedStyle(panel).overflow : 'N/A',
                    containerOverflow: container ? getComputedStyle(container).overflow : 'N/A',
                    panelOverflowY: panel ? getComputedStyle(panel).overflowY : 'N/A',
                    containerOverflowY: container ? getComputedStyle(container).overflowY : 'N/A',
                };
            }""")
            print(f"DVH CSS: {json.dumps(dvh_overflow, indent=2)}")
            page.screenshot(path=f"{SCREENSHOTS_DIR}/04_dvh_panel.png")

        print("\n=== Step 6: Test 2D dose overlay (Bug 3) ===")
        # Check dose overlay state
        dose_state = page.evaluate("""() => {
            if (typeof state === 'undefined' || !state.doseOverlay) return 'No dose overlay';
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

        # Check if dose canvas exists
        dose_canvas_exists = page.evaluate("""() => {
            const axes = ['Axial', 'Sagittal', 'Coronal'];
            const result = {};
            for (const axis of axes) {
                const canvas = document.getElementById('doseOverlayCanvas' + axis);
                result[axis] = canvas ? {
                    exists: true,
                    width: canvas.width,
                    height: canvas.height,
                    display: canvas.style.display,
                    visible: canvas.offsetWidth > 0,
                } : { exists: false };
            }
            return result;
        }""")
        print(f"Dose canvases: {json.dumps(dose_canvas_exists, indent=2)}")

        # Try changing axial slice and check if dose disappears
        print("\n--- Testing slice change ---")
        slice_before = page.evaluate("state?.slices?.axial ?? 'N/A'")
        print(f"Current axial slice: {slice_before}")

        # Change slice
        page.evaluate("updateSlice('axial', 20)")
        time.sleep(1)
        page.screenshot(path=f"{SCREENSHOTS_DIR}/05_after_slice_change.png")

        # Check dose canvas after slice change
        dose_after = page.evaluate("""() => {
            const canvas = document.getElementById('doseOverlayCanvasAxial');
            if (!canvas) return 'Canvas not found';
            const ctx = canvas.getContext('2d');
            const imageData = ctx.getImageData(0, 0, Math.min(canvas.width, 100), Math.min(canvas.height, 100));
            let nonZeroPixels = 0;
            for (let i = 0; i < imageData.data.length; i += 4) {
                if (imageData.data[i] > 0 || imageData.data[i+1] > 0 || imageData.data[i+2] > 0) {
                    nonZeroPixels++;
                }
            }
            return {
                width: canvas.width,
                height: canvas.height,
                display: canvas.style.display,
                styleWidth: canvas.style.width,
                styleHeight: canvas.style.height,
                styleLeft: canvas.style.left,
                styleTop: canvas.style.top,
                nonZeroPixels: nonZeroPixels,
                parentElement: canvas.parentElement?.id || canvas.parentElement?.className,
            };
        }""")
        print(f"Dose canvas after slice change: {json.dumps(dose_after, indent=2)}")

        # Change to another slice
        page.evaluate("updateSlice('axial', 30)")
        time.sleep(1)
        dose_after2 = page.evaluate("""() => {
            const canvas = document.getElementById('doseOverlayCanvasAxial');
            if (!canvas) return 'Canvas not found';
            const ctx = canvas.getContext('2d');
            const imageData = ctx.getImageData(0, 0, Math.min(canvas.width, 100), Math.min(canvas.height, 100));
            let nonZeroPixels = 0;
            for (let i = 0; i < imageData.data.length; i += 4) {
                if (imageData.data[i] > 0 || imageData.data[i+1] > 0 || imageData.data[i+2] > 0) {
                    nonZeroPixels++;
                }
            }
            return { nonZeroPixels, sliceIndex: 30 };
        }""")
        print(f"Dose canvas at slice 30: {json.dumps(dose_after2, indent=2)}")
        page.screenshot(path=f"{SCREENSHOTS_DIR}/06_slice_30.png")

        print("\n=== Step 7: Test 3D viewer (Bug 4) ===")
        # Switch to viewers panel
        page.evaluate("switchPanel('viewers', document.querySelectorAll('.panel-tab')[2])")
        time.sleep(2)

        scene3d_state = page.evaluate("""() => {
            if (typeof scene3D === 'undefined') return 'scene3D not defined';
            return {
                initialized: scene3D.initialized,
                meshCount: Object.keys(scene3D.meshes).length,
                meshIds: Object.keys(scene3D.meshes),
                hasScene: !!scene3D.scene,
                hasCamera: !!scene3D.camera,
                hasRenderer: !!scene3D.renderer,
            };
        }""")
        print(f"3D scene: {json.dumps(scene3d_state, indent=2)}")
        page.screenshot(path=f"{SCREENSHOTS_DIR}/07_3d_viewer.png")

        # Check data tree state
        data_tree = page.evaluate("""() => {
            if (typeof dataTreeState === 'undefined') return 'dataTreeState not defined';
            return {
                ctvLoaded: dataTreeState.ctv?.loaded,
                ctvVisible: dataTreeState.ctv?.visible,
                oarLoaded: dataTreeState.oar?.loaded,
                oarVisible: dataTreeState.oar?.visible,
                seedsLoaded: dataTreeState.seeds?.loaded,
                seedsVisible: dataTreeState.seeds?.visible,
                needlesLoaded: dataTreeState.needles?.loaded,
                planningMeshCount: dataTreeState.planning?.meshes?.length,
                organsCount: dataTreeState.organs?.length,
            };
        }""")
        print(f"Data tree: {json.dumps(data_tree, indent=2)}")

        print("\n=== Step 8: Dump console logs ===")
        # Filter for dose/dvh/3d related logs
        relevant_logs = [l for l in console_logs if any(k in l.lower() for k in ['dose', 'dvh', '3d', 'mesh', 'ctv', 'oar', 'overlay', 'error', 'fail', 'warn'])]
        print(f"Total console logs: {len(console_logs)}")
        print(f"Relevant logs ({len(relevant_logs)}):")
        for log in relevant_logs[-50:]:
            print(f"  {log}")

        # Save all logs to file
        with open(f"{SCREENSHOTS_DIR}/console_logs.txt", "w") as f:
            for log in console_logs:
                f.write(log + "\n")
        print(f"\nAll logs saved to {SCREENSHOTS_DIR}/console_logs.txt")

        browser.close()
        print("\n=== Test complete ===")

if __name__ == "__main__":
    run()
