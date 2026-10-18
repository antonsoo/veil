// Native browser HAR recording of a synthetic loopback session. No remote sites.
import assert from 'node:assert/strict';
import { createHash, randomBytes } from 'node:crypto';
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
const rows = [], requests = [];
let session = '';
const server = createServer((request, response) => {
  const cookie = request.headers.cookie ?? '';
  requests.push({ path: request.url, cookie });
  if (request.url === '/login') {
    response.writeHead(200, { 'Content-Type': 'text/plain', 'Set-Cookie': [`sid=${session}; HttpOnly; Path=/; SameSite=Lax`, 'theme=dark; Path=/'] });
    response.end('local login');
  } else if (request.url === '/private') {
    const accepted = cookie.split(';').some(part => part.trim() === `sid=${session}`);
    response.writeHead(accepted ? 200 : 401, { 'Content-Type': 'text/plain' });
    response.end(accepted ? 'local private document' : 'unauthorized');
  } else { response.writeHead(204); response.end(); }
});
await new Promise(done => server.listen(0, '127.0.0.1', done));
const origin = `http://127.0.0.1:${server.address().port}`;
try {
  for (const [engine, launcher] of [['chromium', chromium], ['firefox', firefox]]) {
    session = randomBytes(16).toString('hex');
    const start = requests.length, file = `${engine}.har`;
    const browser = await launcher.launch();
    let cookieJar, status;
    try {
      const context = await browser.newContext({ recordHar: { path: join(output, file), mode: 'full', content: 'omit' } });
      try {
        const page = await context.newPage();
        await page.goto(origin + '/login');
        const response = await page.goto(origin + '/private');
        status = response.status(); assert.equal(status, 200);
        assert.equal(await page.locator('body').textContent(), 'local private document');
        cookieJar = await context.cookies();
        assert.equal(cookieJar.find(cookie => cookie.name === 'sid').value, session);
      } finally { await context.close(); }
    } finally { await browser.close(); }
    const text = await readFile(join(output, file), 'utf8'), har = JSON.parse(text);
    assert.ok(har.log.entries.every(entry => new URL(entry.request.url).origin === origin));
    const surfaces = [];
    for (const [index, entry] of har.log.entries.entries()) for (const side of ['request', 'response']) {
      for (const [i, header] of entry[side].headers.entries()) if (header.value.includes(session)) surfaces.push({ path: `/log/entries/${index}/${side}/headers/${i}/value`, kind: 'header', name: header.name, value: header.value });
      for (const [i, cookie] of entry[side].cookies.entries()) if (cookie.value.includes(session)) surfaces.push({ path: `/log/entries/${index}/${side}/cookies/${i}/value`, kind: 'cookie', name: cookie.name, value: cookie.value });
    }
    assert.ok(surfaces.some(row => row.kind === 'cookie') && surfaces.some(row => row.kind === 'header'));
    rows.push({ engine, browserVersion: har.log.browser, file, sha256: createHash('sha256').update(text).digest('hex'), session, authenticatedStatus: status, cookieJar, requests: requests.slice(start), secretSurfaces: surfaces, occurrences: text.split(session).length - 1 });
    console.log(`${engine}: native authenticated HAR, ${surfaces.length} credential surfaces`);
  }
} finally { await new Promise(done => server.close(done)); }
await writeFile(join(output, 'oracle.json'), JSON.stringify({ scope: 'Native Playwright full HAR recording of loopback login and authenticated navigation. Cookies are local synthetic sessions, the server is closed after capture, and response bodies are omitted. This is not a claim about a browser GUI sanitized-HAR export.', playwright: require('playwright/package.json').version, captureSha256: createHash('sha256').update(await readFile(fileURLToPath(import.meta.url))).digest('hex'), rows }, null, 2) + '\n');
