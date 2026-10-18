// Actual URL masking and vault downloads from the browser's Python runtime.
/* global document, innerWidth */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
const require = createRequire(new URL('../../web/package.json', import.meta.url));
const { chromium, firefox } = require('playwright');
const [url, outArg, phase = 'after'] = process.argv.slice(2);
assert.ok(url && outArg && ['before', 'after'].includes(phase));
const out = resolve(outArg); await mkdir(out, { recursive: true });
const capture = JSON.parse(await readFile(new URL('capture.json', import.meta.url)));
const cases = capture.cases.filter(c => c.producer === 'httpx2' && c.accepted);
assert.equal(cases.length, 4);
const sha = text => createHash('sha256').update(text).digest('hex'), results = [];
for (const [engine, launcher] of Object.entries({ chromium, firefox })) {
  const browser = await launcher.launch();
  try {
    for (const width of [1280, 375]) {
      const context = await browser.newContext({ viewport: { width, height: 1000 } });
      try {
        const page = await context.newPage(), errors = [], requests = [];
        page.on('pageerror', e => errors.push(e.message));
        await page.goto(url); await page.locator('#mask-btn').click();
        const done = () => page.waitForFunction(() => document.querySelector('#load-status').textContent.includes('Masked this prompt'), null, { timeout: 90000 });
        await done(); await page.evaluate(() => document.fonts.ready); await page.waitForLoadState('networkidle');
        await page.locator('#known-persons').fill(''); await context.setOffline(true);
        context.on('request', request => requests.push(request.url()));
        const rows = [];
        for (const item of cases) {
          await page.locator('#prompt').fill(item.url); await page.locator('#mask-btn').click(); await done();
          const downloads = {};
          for (const [id, key] of [['#download-masked', 'masked'], ['#download-vault', 'vault']]) {
            const pending = page.waitForEvent('download'); await page.locator(id).click();
            downloads[key] = await readFile(await (await pending).path(), 'utf8');
          }
          assert.equal(downloads.masked, phase === 'before' ? item.url : '⟨URL_CREDENTIAL_1⟩');
          const vault = JSON.parse(downloads.vault); let restored = downloads.masked;
          for (const m of vault.mappings) restored = restored.replaceAll(m.surrogate, m.original);
          assert.equal(restored, item.url);
          if (phase === 'after') { assert.equal(vault.mappings.length, 1); assert.equal(vault.mappings[0].original, item.url); }
          rows.push({ field: item.field, sourceSha256: sha(item.url), maskedSha256: sha(downloads.masked),
            vaultSha256: sha(downloads.vault), protectedWholeUrl: phase === 'after', exactDownloadRestoration: true });
        }
        await page.evaluate(() => globalThis.scrollTo(0, 0));
        await page.screenshot({ path: resolve(out, `${engine}-${width}.png`) });
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
        assert.deepEqual(errors, []); assert.deepEqual(requests, []);
        results.push({ engine, version: browser.version(), width, phase, rows, offlineAfterBootstrap: true, errors, requests });
        console.log(JSON.stringify({ engine, width, phase, cases: rows.length }));
      } finally { await context.close(); }
    }
  } finally { await browser.close(); }
}
await writeFile(resolve(out, 'browser.json'), JSON.stringify({ url, results }, null, 2) + '\n');
