// Native HARs of synthetic authenticated loopback requests. No remote service.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createServer } from 'node:http';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(join(here, '../../web/package.json'));
const { chromium, firefox } = require('playwright');
const output = resolve(process.argv[2] ?? join(here, 'fixtures'));
await mkdir(output, { recursive: false });
const credentials = { bearer: 'local-session-42', basic: Buffer.from('local:pass').toString('base64') };
const expected = { '/bearer': `Bearer ${credentials.bearer}`, '/basic': `Basic ${credentials.basic}` };
const requests = [];
const server = createServer((request, response) => {
  const auth = request.headers.authorization;
  const authenticated = auth === expected[request.url];
  requests.push({ path: request.url, authorization: auth, authenticated });
  response.writeHead(authenticated ? 200 : 401, { 'Content-Type': 'text/plain' });
  response.end(authenticated ? 'local authenticated document' : 'authentication required');
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const rows = [];
try {
  for (const [engine, launcher] of [['chromium', chromium], ['firefox', firefox]]) {
    const browser = await launcher.launch();
    try {
      const file = `${engine}.har`;
      const context = await browser.newContext({ recordHar: { path: join(output, file), content: 'omit', mode: 'full' } });
      try {
        const page = await context.newPage();
        for (const [path, authorization] of Object.entries(expected)) {
          await context.setExtraHTTPHeaders({ Authorization: authorization });
          const response = await page.goto(`http://127.0.0.1:${server.address().port}${path}`);
          assert.equal(response.status(), 200);
        }
      } finally { await context.close(); }
      const bytes = await readFile(join(output, file));
      const har = JSON.parse(bytes);
      const surfaces = [];
      for (const [i, entry] of har.log.entries.entries()) {
        for (const [j, header] of entry.request.headers.entries()) {
          if (header.name.toLowerCase() === 'authorization') {
            const path = new URL(entry.request.url).pathname;
            assert.equal(header.value, expected[path]);
            surfaces.push({ path: `/log/entries/${i}/request/headers/${j}/value`, value: header.value });
          }
        }
      }
      assert.equal(surfaces.length, 2);
      rows.push({ engine, browserVersion: browser.version(), file, sha256: createHash('sha256').update(bytes).digest('hex'), surfaces });
    } finally { await browser.close(); }
  }
} finally { await new Promise(resolve => server.close(resolve)); }
assert.equal(requests.filter(r => r.authenticated).length, 4);
await writeFile(join(output, 'oracle.json'), JSON.stringify({ scope: 'Unmodified full Playwright HARs from actual Chromium/Firefox requests to a synthetic local authenticated server. Credentials are deliberately short and never valid outside this capture.', credentials, requests, rows }, null, 2) + '\n');
console.log(JSON.stringify(rows.map(({ engine, file, surfaces }) => ({ engine, file, authorizationHeaders: surfaces.length }))));
