/* Synthetic HTTP fixture, real DOM/canvas review and late-timepoint fencing. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox'],
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? {executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE} : {})});
  const page = await browser.newPage({viewport: {width: 1100, height: 900}});
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  try {
    await page.route('**/*', route => route.fulfill({contentType: 'text/html', body: '<!doctype html><div id="review"></div>'}));
    await page.goto('http://guide-review.invalid/');
    await page.addScriptTag({path: path.resolve(__dirname, '../web/app/static/js/brachybot-guide-registration.js')});
    await page.evaluate(async () => {
      window.calls = []; window.active = {session_id: 's1', timepoint_id: 't1', mount_generation: 1};
      const identity = {image_id: 'current-ct', image_revision: 'sha-ct', geometry_id: 'physical-grid'};
      window.inventory = {success: true, source_timepoint_id: 'source', state_revision: 2,
        guide_versions: [{guide_version: 1, eligible_bore_count: 5}],
        candidates: [{placement_id: 'p1', qc: {service_scope: {guide_version: 1}}, method: 'image_rigid', review_state: 'pending'}]};
      window.packet = {session_id: 's1', timepoint_id: 't1', source_timepoint_id: 'source', state_revision: 2,clinical_revision:4,
        target_image: identity, placement_id: 'p1', candidate_sha256: 'sha-pose', receipt_token: 'server-receipt',
        source_provenance: {image: {image_id: 'original-A'}, original_acquisition_verified: true},
        review_state: 'pending', vertices_lps_mm: [[0,0,0],[4,0,0],[0,4,0],[0,0,4]], faces: [[0,1,2],[0,1,3],[1,2,3],[2,0,3]],
        current_body_surface: {vertices_lps_mm: [[-4,-4,-4],[8,-4,-4],[-4,8,-4],[-4,-4,8]], faces: [[0,1,2],[0,1,3],[1,2,3],[2,0,3]]},
        qc: {ambiguous: false, fit_failed: false}, bores: [],
        slices: ['sagittal','coronal','axial'].map(name => ({name, index: 2, width: 16, height: 16,
          ct_hu: Array.from({length: 16}, (_, y) => Array.from({length: 16}, (_, x) => x + y > 9 ? 150 : -800)),
          registered_source_hu: Array.from({length: 16}, () => Array(16).fill(50)), guide_segments_pixels: [[[4,4],[10,10]]]}))};
      window.controller = new BrachyGuideRegistration.GuideRegistrationController({container: document.querySelector('#review'),
        getCapture: () => active, language: () => window.lang || 'en',
        request: async (url, options) => {
          calls.push({url, options});
          if (url.includes('/overlay')) {
            if (window.deferOverlay) return new Promise(resolve => {window.finishOverlay = () => resolve({success: true, overlay: structuredClone(packet)});});
            return {success: true, overlay: structuredClone(packet)};
          }
          if (url.endsWith('/review')) return {success: true, placement: {review_state: options.body.decision}};
          return structuredClone(inventory);
        }});
      await controller.mount(active); await controller.showOverlay();
    });
    assert.equal(await page.locator('canvas').count(), 4);
    assert.ok((await page.locator('[data-guide-source-provenance]').textContent()).includes('Original printed-guide acquisition verified · original-A'));
    assert.equal(await page.getByRole('button', {name: 'Confirm guide fit', exact: true}).isEnabled(), true);
    await page.evaluate(() => { controller.fields.profile_id.value = 'phantom-profile'; controller.fields.note.value = 'Current anatomy and printed guide fit reviewed'; });
    await page.getByRole('button', {name: 'Confirm guide fit', exact: true}).click();
    assert.equal(await page.evaluate(() => calls.filter(call => call.url.endsWith('/review')).length), 0);
    await page.locator('input[type=checkbox]').check();
    await page.getByRole('button', {name: 'Confirm guide fit', exact: true}).click();
    const accepted = await page.evaluate(() => calls.find(call => call.url.endsWith('/review')));
    assert.equal(accepted.options.body.candidate_sha256, 'sha-pose');
    assert.deepEqual(accepted.options.body.overlay_receipt.dimensions, ['2d', '3d']);
    assert.equal(accepted.options.body.overlay_receipt.receipt_token, 'server-receipt');
    assert.equal(accepted.options.body.expected_clinical_revision,4);
    assert.equal(accepted.options.body.overlay_receipt.clinical_revision,4);
    console.log('PASS real CT canvases, interactive 3D and explicit review receipt');
    await page.evaluate(async () => { packet.qc.ambiguous = true; await controller.showOverlay(); });
    assert.equal(await page.getByRole('button', {name: 'Confirm guide fit', exact: true}).isEnabled(), false);
    console.log('PASS ambiguous pose cannot be accepted');
    await page.evaluate(() => {window.lang = 'zh'; window.dispatchEvent(new Event('i18nchange'));});
    assert.equal(await page.getByRole('button', {name: '确认导板贴合', exact: true}).count(), 1);
    assert.ok((await page.locator('[role=status]').textContent()).includes('多解'));
    assert.ok((await page.locator('[data-guide-source-provenance]').textContent()).includes('已核验制作打印导板的原始影像 · original-A'));
    await page.evaluate(async () => {packet.source_provenance.original_acquisition_verified = false; await controller.showOverlay();});
    assert.ok((await page.locator('[data-guide-source-provenance]').textContent()).includes('尚未核验'));
    await page.evaluate(async () => {packet.source_provenance = null; await controller.showOverlay();});
    assert.ok((await page.locator('[data-guide-source-provenance]').textContent()).includes('直接导板证据'));
    await page.evaluate(() => {window.lang = 'en'; window.dispatchEvent(new Event('i18nchange'));});
    console.log('PASS global language switch preserves fit state and updates status');
    await page.evaluate(() => { window.deferOverlay = true; window.pendingOverlay = controller.showOverlay(); });
    await page.evaluate(async () => { active = {session_id: 's1', timepoint_id: 't2', mount_generation: 2}; await controller.mount(active); finishOverlay(); await pendingOverlay; });
    assert.equal(await page.locator('canvas').count(), 0);
    assert.equal(await page.evaluate(() => controller.receipt), null);
    assert.ok(!(await page.locator('[data-guide-source-provenance]').textContent()).includes('original-A'));
    console.log('PASS late target-A overlay cannot mount on target-B');
    await page.evaluate(async () => {window.lang = 'zh'; await controller.mount(active);});
    assert.equal(await page.getByRole('button', {name: '确认导板贴合', exact: true}).count(), 1);
    assert.deepEqual(errors, []);
    console.log('PASS bilingual controls without page errors');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
