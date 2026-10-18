// Actual Pyodide worker and native HAR masked/vault downloads, after disconnecting.
/* global document, innerWidth */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const [url, outputArg, referenceArg, phase, selection = 'all'] = process.argv.slice(2);
assert.ok(url && outputArg && referenceArg && ['before', 'after'].includes(phase));
assert.ok(['all', 'last'].includes(selection));
const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(join(here, '../../web/package.json'));
const { chromium, firefox } = require('playwright');
const output = resolve(outputArg), reference = resolve(referenceArg);
await mkdir(output, { recursive: true });
const oracle = JSON.parse(await readFile(join(here, 'fixtures/oracle.json'), 'utf8'));
const cases = await Promise.all(oracle.rows.filter((_, i) => selection === 'all' || i === oracle.rows.length - 1).map(async row => ({ ...row,
  source: await readFile(join(here, 'fixtures', row.file), 'utf8'),
  expected: await readFile(join(reference, row.engine + '.masked.har'), 'utf8'),
})));
const sha = data => createHash('sha256').update(data).digest('hex');
const rows = [];
for (const [engine, launcher] of [['chromium', chromium], ['firefox', firefox]]) {
  const browser = await launcher.launch();
  try {
    for (const width of [1280, 375]) {
      const context = await browser.newContext({ viewport: { width, height: 1000 },
        colorScheme: width === 375 ? 'light' : 'dark', reducedMotion: 'reduce' });
      try {
        const errors = [], requests = [];
        let offline = false;
        context.on('request', request => { if (offline) requests.push(request.url()); });
        const page = await context.newPage(); page.on('pageerror', error => errors.push(error.message));
        await page.goto(url);
        await page.locator('#mask-btn').click();
        await page.waitForFunction(() => document.querySelector('#load-status').textContent.includes('Masked this prompt'), null, { timeout: 90000 });
        await page.evaluate(() => document.fonts.ready); await page.waitForLoadState('networkidle');
        await page.locator('#known-persons').fill('');
        await context.setOffline(true); offline = true;
        const outcomes = [];
        for (const item of cases) {
          await page.locator('#prompt').fill(item.source); await page.locator('#mask-btn').click();
          await page.waitForFunction(() => document.querySelector('#load-status').textContent.includes('Masked this prompt'));
          const downloads = {};
          for (const [selector, name] of [['#download-masked', 'masked'], ['#download-vault', 'vault']]) {
            const pending = page.waitForEvent('download'); await page.locator(selector).click();
            downloads[name] = await readFile(await (await pending).path(), 'utf8');
          }
          assert.equal(downloads.masked, item.expected, 'Actual worker output matches native CLI');
          const preview = await page.locator('#masked-output').textContent();
          assert.equal(preview, downloads.masked.slice(0, 20000));
          if (downloads.masked.length > 20000) {
            assert.match(await page.locator('#preview-note').textContent(), /download contains the complete masked prompt/);
          }
          const vault = JSON.parse(downloads.vault);
          let restored = downloads.masked;
          for (const mapping of vault.mappings) restored = restored.replaceAll(mapping.surrogate, mapping.original);
          assert.equal(restored, item.source);
          const data = JSON.parse(downloads.masked);
          if (phase === 'after') for (const surface of item.surfaces) {
            const value = surface.path.split('/').slice(1).reduce((node, key) => node[key], data);
            assert.match(value, /^⟨(?:SECRET|URL_CREDENTIAL)_\d+⟩$/);
          }
          await writeFile(join(output, `${engine}-${width}-${item.engine}.masked.har`), downloads.masked);
          outcomes.push({ nativeProducer: item.engine, sourceSha256: item.sha256,
            maskedSha256: sha(downloads.masked), vaultSha256: sha(downloads.vault),
            exactCliOutput: true, originalTextRestoredFromDownloads: true,
            credentialSurfaces: item.surfaces.length, allCredentialSurfacesOpaque: phase === 'after' });
        }
        await page.evaluate(() => globalThis.scrollTo(0, 0));
        await page.screenshot({ path: join(output, `${engine}-${width}-view.png`) });
        await page.locator('[data-stage="vault"]').screenshot({ path: join(output, `${engine}-${width}-vault.png`) });
        assert.deepEqual(requests, []); assert.deepEqual(errors, []);
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
        rows.push({ engine, version: browser.version(), width, phase, outcomes,
          offlineAfterBootstrap: true, subsequentPromptRequests: 0, errors, horizontalOverflow: false });
        console.log(JSON.stringify({ engine, width, phase, nativeHars: outcomes.length }));
      } finally { await context.close(); }
    }
  } finally { await browser.close(); }
}
await writeFile(join(output, 'browser.json'), JSON.stringify({ url, phase,
  scope: 'Actual Pyodide worker and three unchanged native browser/proxy HARs. Masked/vault downloads are real; restoration is an explicit local diagnostic, independent of the canned reply.', rows }, null, 2) + '\n');
