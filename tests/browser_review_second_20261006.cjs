/* Synthetic browser-component regression; never connects to the product server. */
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.REVIEW_PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const cacheSource = fs.readFileSync(path.join(root, 'web/app/static/js/brachybot-session-cache.js'), 'utf8');
const uiSource = fs.readFileSync(path.join(root, 'web/app/static/js/brachybot-ui-api.js'), 'utf8');
const server = http.createServer((req, res) => {
  if (req.url === '/cache.js') {
    res.writeHead(200, {'Content-Type': 'text/javascript'}); res.end(cacheSource);
  } else {
    res.writeHead(200, {'Content-Type': 'text/html'});
    res.end('<!doctype html><title>Synthetic component fixture</title><script src="/cache.js"></script>');
  }
});
const rows = [];
(async () => {
  let browser;
  try {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    browser = await chromium.launch({headless: true, executablePath: process.env.REVIEW_CHROME_PATH});
    const page = await browser.newPage();
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    async function check(name, callback) { await callback(); rows.push({name, status: 'passed'}); }
    await check('native_array_cursor_is_an_exact_key_not_a_suffix_range', async () => {
      const keys = await page.evaluate(async () => {
        const db = await new Promise((resolve, reject) => {
          const req = indexedDB.open('synthetic-cursor-review', 1);
          req.onupgradeneeded = () => req.result.createObjectStore('items');
          req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error);
        });
        await new Promise((resolve, reject) => {
          const tx = db.transaction('items', 'readwrite');
          ['a', 'b', 'c'].forEach(key => tx.objectStore('items').put(key, ['case', key]));
          tx.oncomplete = resolve; tx.onerror = () => reject(tx.error);
        });
        await new Promise((resolve, reject) => {
          const tx = db.transaction('items', 'readwrite');
          tx.objectStore('items').openCursor(['case', 'b']).onsuccess = event => {
            const c = event.target.result; if (c) { c.delete(); c.continue(); }
          };
          tx.oncomplete = resolve; tx.onerror = () => reject(tx.error);
        });
        return new Promise(resolve => {
          db.transaction('items').objectStore('items').getAllKeys().onsuccess = e => resolve(e.target.result);
        });
      });
      assert.deepEqual(keys, [['case', 'a'], ['case', 'c']]);
    });
    await check('one_key_invalidation_preserves_neighbors', async () => {
      const result = await page.evaluate(async () => {
        await SessionCache.put('case', 'mesh', 'a', new Uint8Array([1]).buffer);
        await SessionCache.put('case', 'mesh', 'b', new Uint8Array([2]).buffer);
        await SessionCache.put('case', 'mesh', 'c', new Uint8Array([3]).buffer);
        await SessionCache.invalidate('case', 'mesh', 'b');
        return Promise.all(['a','b','c'].map(async key => {
          const v = await SessionCache.get('case', 'mesh', key); return v ? [...new Uint8Array(v)] : null;
        }));
      });
      assert.deepEqual(result, [[1], null, [3]]);
    });
    await check('clear_fences_old_operations_and_allows_a_new_session', async () => {
      const result = await page.evaluate(async () => {
        const staleGet = SessionCache.get('case', 'mesh', 'a');
        const stalePut = SessionCache.put('case', 'mesh', 'late', new Uint8Array([9]).buffer);
        await Promise.all([SessionCache.closeAndClear(), SessionCache.closeAndClear()]);
        const old = await staleGet; await stalePut;
        const late = await SessionCache.get('case', 'mesh', 'late');
        await SessionCache.put('new-case', 'mesh', 'new', new Uint8Array([4]).buffer);
        const fresh = await SessionCache.get('new-case', 'mesh', 'new');
        return {old: old === null, late: late === null, fresh: [...new Uint8Array(fresh)]};
      });
      assert.deepEqual(result, {old: true, late: true, fresh: [4]});
    });
    await check('eviction_keeps_total_below_cap_even_with_fewer_than_four_items', async () => {
      await page.evaluate(async () => {
        await SessionCache.closeAndClear();
        // Tiny cloned objects with synthetic byteLength exercise accounting
        // without allocating patient data or multi-gigabyte browser storage.
        for (let i = 0; i < 6; i++) await SessionCache.put('large', 'mesh', String(i), {byteLength: 300 * 1024**2});
        await SessionCache.put('large', 'mesh', 'oversized', {byteLength: 900 * 1024**2});
      });
      await page.waitForTimeout(5500);
      const result = await page.evaluate(async () => ({
        size: SessionCache.estimatedSize(), oversized: await SessionCache.get('large', 'mesh', 'oversized'),
        kept: (await Promise.all(Array.from({length: 6}, (_, i) => SessionCache.get('large', 'mesh', String(i))))).filter(Boolean).length,
      }));
      assert.ok(result.size <= 800 * 1024**2); assert.equal(result.oversized, null); assert.ok(result.kept <= 2);
    });
    await page.addScriptTag({content: uiSource.slice(0, uiSource.indexOf('// Keep this compatibility helper'))});
    await check('inline_argument_survives_html_and_javascript_contexts_without_execution', async () => {
      const id = `needle');window.syntheticAttack=true;//"<&`;
      const result = await page.evaluate(id => {
        window.capture = value => { window.captured = value; };
        document.body.innerHTML = `<button onclick="capture(${brachybotInlineArgument(id)})">Synthetic</button>`;
        document.querySelector('button').click();
        return {captured: window.captured, attack: !!window.syntheticAttack};
      }, id);
      assert.deepEqual(result, {captured: id, attack: false});
    });
    await check('legacy_toast_is_a_text_only_notification', async () => {
      const result = await page.evaluate(() => {
        const text = '<img src=x onerror="window.syntheticAttack=true">';
        showToast(text, 'error', 10000);
        return {text: document.getElementById('brachybotNoticeStack').textContent, images: document.querySelectorAll('#brachybotNoticeStack img').length};
      });
      assert.ok(result.text.includes('<img')); assert.equal(result.images, 0);
    });
    const evidence = {scope: 'synthetic developer browser components only; no authenticated product or patient case',
      browser: browser.version(), tests: rows, cache_sha256: crypto.createHash('sha256').update(cacheSource).digest('hex'),
      ui_sha256: crypto.createHash('sha256').update(uiSource).digest('hex')};
    const output = path.join(root, 'docs/benchmarks/browser_review_second_2026-10-06.json');
    fs.writeFileSync(output, JSON.stringify(evidence, null, 2) + '\n');
    process.stdout.write(JSON.stringify(evidence) + '\n');
  } finally { if (browser) await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
