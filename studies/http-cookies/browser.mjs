// Real Pyodide UI imports and downloads. URL can be local or canonical hosted.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const [url, outputArg] = process.argv.slice(2);
assert.ok(url && outputArg, 'URL OUTPUT');
const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(join(here, '../../web/package.json'));
const { chromium, firefox } = require('playwright');
const axe = await readFile(require.resolve('axe-core/axe.min.js'), 'utf8');
const output = resolve(outputArg); await mkdir(output, { recursive: true });
const oracle = JSON.parse(await readFile(join(here, 'fixtures/oracle.json'), 'utf8'));
const cases = [];
for (const file of oracle.files) {
  const source = await readFile(join(here, 'fixtures', file.file), 'utf8');
  const originals = file.file.startsWith('response') ? oracle.setCookies : [oracle.cookie];
  let expected = source;
  for (const [i, original] of originals.entries()) expected = expected.replace(original, `⟨SECRET_${i + 1}⟩`);
  cases.push({ name: file.file, source, originals, expected });
}
cases.push({ name: 'short-and-expiry-control', source: 'Cookie: sid=s1; theme=dark\nSet-Cookie: refresh=r1; Expires=Wed, 09 Jun 2027 10:18:14 GMT\n', originals: ['sid=s1; theme=dark', 'refresh=r1; Expires=Wed, 09 Jun 2027 10:18:14 GMT'], expected: 'Cookie: ⟨SECRET_1⟩\nSet-Cookie: ⟨SECRET_2⟩\n' });
const rows = [];
const sha = value => createHash('sha256').update(value).digest('hex');
for (const [engine, launcher] of [['chromium', chromium], ['firefox', firefox]]) {
  const browser = await launcher.launch();
  try {
    for (const width of [1280, 375]) {
      const context = await browser.newContext({ viewport: { width, height: 1000 }, reducedMotion: 'reduce', colorScheme: width === 375 ? 'light' : 'dark' });
      try {
        const requests = [], errors = [];
        context.on('request', r => requests.push({ url: r.url(), method: r.method(), body: r.postData() }));
        const page = await context.newPage(); page.on('pageerror', e => errors.push(e.message));
        await page.goto(url);
        assert.ok(requests.every(r => new URL(r.url).origin === new URL(url).origin), 'no Python runtime request before user action');
        await page.locator('#mask-btn').click();
        await page.waitForFunction(() => document.querySelector('#load-status').textContent.includes('Masked this prompt'), null, { timeout: 90000 });
        await page.evaluate(() => document.fonts.ready);
        await page.waitForLoadState('networkidle');
        await page.locator('#known-persons').fill('');
        await context.setOffline(true);
        const count = requests.length, outcomes = [];
        for (const item of cases) {
          await page.locator('#prompt').fill(item.source);
          await page.locator('#mask-btn').click();
          await page.waitForFunction(() => document.querySelector('#load-status').textContent.includes('Masked this prompt'));
          assert.equal(await page.locator('#masked-output').textContent(), item.expected);
          const downloads = {};
          for (const [selector, key] of [['#download-masked', 'masked'], ['#download-vault', 'vault']]) {
            const pending = page.waitForEvent('download'); await page.locator(selector).click();
            downloads[key] = await readFile(await (await pending).path(), 'utf8');
          }
          assert.equal(downloads.masked, item.expected);
          assert.ok(!downloads.masked.includes(oracle.session));
          const vault = JSON.parse(downloads.vault);
          assert.deepEqual(vault.mappings.map(m => m.original), item.originals);
          assert.ok(vault.mappings.every(m => m.type === 'SECRET'));
          // Restore only in this explicit diagnostic from the actual UI vault;
          // the demo's canned reply does not echo arbitrary cookie prompts.
          let restored = downloads.masked;
          for (const mapping of vault.mappings) restored = restored.replaceAll(mapping.surrogate, mapping.original);
          assert.equal(restored, item.source);
          outcomes.push({ name: item.name, maskedSha256: sha(downloads.masked), vaultSha256: sha(downloads.vault), completeValues: item.originals.length, sessionAbsent: true, downloadRestoresExactly: true });
        }
        assert.deepEqual(requests.slice(count), [], 'no network for subsequent prompts or downloads');
        await page.evaluate(axe); const violations = (await page.evaluate(() => axe.run())).violations;
        assert.deepEqual(violations, []); assert.deepEqual(errors, []);
        const auditRequests = requests.slice(count);
        for (const r of auditRequests) {
          assert.equal(new URL(r.url).origin, new URL(url).origin);
          assert.ok(new URL(r.url).pathname.endsWith('.woff2'));
          assert.equal(r.method, 'GET'); assert.equal(r.body, null);
        }
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
        for (const request of requests) if (new URL(request.url).origin !== new URL(url).origin) {
          assert.equal(new URL(request.url).origin, 'https://cdn.jsdelivr.net');
          assert.ok(new URL(request.url).pathname.startsWith('/pyodide/v0.26.4/full/'));
          assert.equal(request.method, 'GET'); assert.equal(request.body, null);
        }
        await page.screenshot({ path: join(output, `${engine}-${width}.png`), fullPage: true });
        rows.push({ engine, version: browser.version(), width, cases: outcomes, offlineAfterBootstrap: true, subsequentPromptRequests: 0, auditFontRequests: auditRequests, errors, accessibilityViolations: [], horizontalOverflow: false });
        console.log(`${engine}/${width}: four cookie prompts and eight actual offline downloads`);
      } finally { await context.close(); }
    }
  } finally { await browser.close(); }
}
await writeFile(join(output, 'browser.json'), JSON.stringify({ url, scope: 'Actual Python worker in the demo UI; retained native header values, explicit short/expiry control, offline masked-prompt and vault downloads. Vault substitution is an explicit local diagnostic; the canned reply does not echo cookies.', rows }, null, 2) + '\n');
