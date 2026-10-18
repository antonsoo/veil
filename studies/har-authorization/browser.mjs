// Actual Python worker, native HAR prompts, and masked/vault file downloads.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const [url, outputArg, phase] = process.argv.slice(2);
assert.ok(url && outputArg && ['before', 'after'].includes(phase), 'URL OUTPUT before|after');
const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(join(here, '../../web/package.json'));
const { chromium, firefox } = require('playwright');
const output = resolve(outputArg); await mkdir(output, { recursive: true });
const oracle = JSON.parse(await readFile(join(here, 'fixtures/oracle.json'), 'utf8'));
const cases = await Promise.all(oracle.rows.map(async row => ({ ...row, source: await readFile(join(here, 'fixtures', row.file), 'utf8') })));
const sha = value => createHash('sha256').update(value).digest('hex');
const rows = [];
for (const [engine, launcher] of [['chromium', chromium], ['firefox', firefox]]) {
  const browser = await launcher.launch();
  try {
    for (const width of [1280, 375]) {
      const context = await browser.newContext({ viewport: { width, height: 1000 }, colorScheme: width === 375 ? 'light' : 'dark', reducedMotion: 'reduce' });
      try {
        const requests = [], errors = [];
        context.on('request', r => requests.push({ url: r.url(), method: r.method(), body: r.postData() }));
        const page = await context.newPage(); page.on('pageerror', e => errors.push(e.message));
        await page.goto(url);
        await page.locator('#mask-btn').click();
        await page.waitForFunction(() => document.querySelector('#load-status').textContent.includes('Masked this prompt'), null, { timeout: 90000 });
        await page.evaluate(() => document.fonts.ready); await page.waitForLoadState('networkidle');
        await page.locator('#known-persons').fill('');
        await context.setOffline(true); const initialRequests = requests.length;
        const outcomes = [];
        for (const item of cases) {
          await page.locator('#prompt').fill(item.source); await page.locator('#mask-btn').click();
          await page.waitForFunction(() => document.querySelector('#load-status').textContent.includes('Masked this prompt'));
          const downloads = {};
          for (const [selector, name] of [['#download-masked', 'masked'], ['#download-vault', 'vault']]) {
            const pending = page.waitForEvent('download'); await page.locator(selector).click();
            downloads[name] = await readFile(await (await pending).path(), 'utf8');
          }
          assert.equal(await page.locator('#masked-output').textContent(), downloads.masked);
          const vault = JSON.parse(downloads.vault);
          let restored = downloads.masked;
          for (const mapping of vault.mappings) restored = restored.replaceAll(mapping.surrogate, mapping.original);
          assert.equal(restored, item.source);
          const occurrences = Object.fromEntries(Object.entries(oracle.credentials).map(([name, value]) => [name, downloads.masked.split(value).length - 1]));
          assert.ok(Object.values(occurrences).every(n => n === (phase === 'before' ? 1 : 0)));
          assert.equal(vault.mappings.length, phase === 'before' ? 0 : 2);
          const doc = JSON.parse(downloads.masked);
          for (const surface of item.surfaces) {
            const value = surface.path.split('/').slice(1).reduce((node, key) => node[key], doc);
            assert.equal(value, phase === 'before' ? surface.value : surface.value.split(' ')[0] + ` ⟨SECRET_${item.surfaces.indexOf(surface) + 1}⟩`);
          }
          outcomes.push({ nativeEngine: item.engine, sourceSha256: item.sha256, maskedSha256: sha(downloads.masked), vaultSha256: sha(downloads.vault), remainingCredentials: occurrences, mappings: vault.mappings.length, originalTextRestoredFromDownloads: true });
        }
        await page.screenshot({ path: join(output, `${engine}-${width}.png`), fullPage: true });
        assert.equal(requests.length, initialRequests, 'no requests from native HAR prompts or downloads');
        assert.deepEqual(errors, []);
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
        rows.push({ engine, version: browser.version(), width, phase, nativeCases: outcomes, offlineAfterBootstrap: true, subsequentPromptRequests: 0, errors, horizontalOverflow: false });
        console.log(`${engine}/${width}: ${phase} native auth HAR downloads observed`);
      } finally { await context.close(); }
    }
  } finally { await browser.close(); }
}
await writeFile(join(output, 'browser.json'), JSON.stringify({ url, phase, scope: 'Actual UI Python worker, two unmodified native authenticated HAR prompts, and real masked/vault downloads. Restoration is an explicit local diagnostic from downloaded vaults; the canned reply is not used as evidence.', rows }, null, 2) + '\n');
