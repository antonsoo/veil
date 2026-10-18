// Native browser HARs of authored loopback query/form credentials. No real account.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { connect, createServer as createPortServer } from 'node:net';
import { mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(join(here, '../../web/package.json'));
const { chromium, firefox } = require('playwright');
const output = resolve(process.argv[2] ?? join(here, 'fixtures'));
const mitmdump = process.argv[3];
assert.ok(mitmdump, 'Usage: node capture.mjs OUTPUT /path/to/mitmdump (12.2.3)');
await mkdir(output, { recursive: false });
const credentials = { password: 'cat', access_token: 'loopback-session', client_secret: 'local&proof+pass' };
const apiKey = 'local-api';
const requests = [];
const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url, 'http://localhost');
    if (url.pathname === '/') {
      response.writeHead(200, { 'Content-Type': 'text/html' });
      response.end('<!doctype html><html lang="en"><title>Local HAR capture</title><p>Authored credentials</p></html>');
      return;
    }
    if (url.pathname === '/api') {
      const accepted = request.headers['x-api-key'] === apiKey;
      requests.push({ path: '/api', method: request.method, accepted, contentType: null });
      response.writeHead(accepted ? 200 : 401); response.end('local API-key control'); return;
    }
    if (!['/query', '/form', '/multipart'].includes(url.pathname)) { response.writeHead(404); response.end(); return; }
    const chunks = []; for await (const chunk of request) chunks.push(chunk);
    const params = request.method === 'GET' ? url.searchParams : await new Response(Buffer.concat(chunks), {
      headers: { 'Content-Type': request.headers['content-type'] },
    }).formData();
    const accepted = Object.entries(credentials).every(([key, value]) => params.get(key) === value);
    requests.push({ path: url.pathname, method: request.method, accepted,
      contentType: request.headers['content-type'] ?? null });
    response.writeHead(accepted ? 200 : 401, { 'Content-Type': 'text/plain' });
    response.end(accepted ? 'local accepted control' : 'unexpected credential');
  } catch { response.writeHead(500); response.end('capture error'); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const reserve = createPortServer();
await new Promise(resolve => reserve.listen(0, '127.0.0.1', resolve));
const proxyPort = reserve.address().port;
await new Promise(resolve => reserve.close(resolve));
const confdir = await mkdtemp('/tmp/claude-1000/veil-har-proxy-');
const proxy = spawn(mitmdump, ['--listen-host', '127.0.0.1', '--listen-port', String(proxyPort),
  '--set', `confdir=${confdir}`, '--set', 'flow_detail=0', '--set', `hardump=${join(output, 'mitmproxy.har')}`],
{ env: { ...process.env, PYTHONUNBUFFERED: '1' }, stdio: ['ignore', 'pipe', 'pipe'] });
let proxyLog = '', proxyStopped = false;
proxy.stdout.on('data', bytes => { proxyLog += bytes; });
proxy.stderr.on('data', bytes => { proxyLog += bytes; });
const proxyClosed = new Promise((resolve, reject) => {
  proxy.once('error', reject);
  proxy.once('close', code => { proxyStopped = true; resolve(code); });
});
async function ready() {
  const deadline = Date.now() + 60000;
  while (Date.now() < deadline && !proxyStopped) {
    const listening = await new Promise(resolve => {
      const socket = connect(proxyPort, '127.0.0.1');
      socket.once('connect', () => { socket.destroy(); resolve(true); });
      socket.once('error', () => { socket.destroy(); resolve(false); });
    });
    if (listening) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('Local proxy did not become ready: ' + proxyLog);
}
const rows = [];
async function retain(engine, file, browserVersion) {
  const bytes = await readFile(join(output, file));
  const har = JSON.parse(bytes), surfaces = [];
  for (const [i, entry] of har.log.entries.entries()) {
    const request = entry.request, path = new URL(request.url).pathname;
    if (!['/api', '/query', '/form', '/multipart'].includes(path)) continue;
    const record = (suffix, source, values) => surfaces.push({ path: `/log/entries/${i}/request/${suffix}`, source, values });
    for (const [j, header] of request.headers.entries()) if (header.name.toLowerCase() === 'x-api-key') {
      assert.equal(header.value, apiKey); record(`headers/${j}/value`, header.value, [apiKey]);
    }
    if (path === '/query') record('url', request.url, Object.values(credentials));
    for (const [kind, params] of [['queryString', request.queryString], ['postData/params', request.postData?.params]]) {
      for (const [j, param] of (params ?? []).entries()) if (Object.hasOwn(credentials, param.name)) {
        assert.equal(param.value, credentials[param.name]);
        record(`${kind}/${j}/value`, param.value, [param.value]);
      }
    }
    if (path === '/form' || path === '/multipart') {
      assert.ok(request.postData.text.length);
      record('postData/text', request.postData.text, Object.values(credentials));
    }
  }
  assert.equal(surfaces.length, engine === 'mitmproxy' ? 20 : 7);
  rows.push({ engine, browserVersion, creator: har.log.creator, file,
    bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), surfaces });
}
try {
  await ready();
  for (const [engine, launcher] of [['chromium', chromium], ['firefox', firefox]]) {
    const browser = await launcher.launch();
    try {
      const file = `${engine}.har`;
      const context = await browser.newContext({ proxy: { server: `http://127.0.0.1:${proxyPort}` },
        recordHar: { path: join(output, file), mode: 'full', content: 'embed' } });
      try {
        const page = await context.newPage();
        await page.goto(`http://127.0.0.1:${server.address().port}/`);
        const statuses = await page.evaluate(async credentials => {
          const fields = { ...credentials, format: 'json' };
          const form = new FormData(); for (const [key, value] of Object.entries(fields)) form.append(key, value);
          const responses = [await fetch('/api', { headers: { 'X-Api-Key': 'local-api' } }),
            await fetch('/query?' + new URLSearchParams(fields)),
            await fetch('/form', { method: 'POST', body: new URLSearchParams(fields) }),
            await fetch('/multipart', { method: 'POST', body: form })];
          await Promise.all(responses.map(response => response.text()));
          return responses.map(response => response.status);
        }, credentials);
        assert.deepEqual(statuses, [200, 200, 200, 200]);
      } finally { await context.close(); }
      await retain(engine, file, browser.version());
    } finally { await browser.close(); }
  }
} finally {
  proxy.kill('SIGINT');
  const timeout = setTimeout(() => proxy.kill('SIGKILL'), 30000);
  try { assert.equal(await proxyClosed, 0, proxyLog); }
  finally { clearTimeout(timeout); await new Promise(resolve => server.close(resolve)); }
}
await retain('mitmproxy', 'mitmproxy.har', null);
assert.equal(requests.length, 8); assert.ok(requests.every(request => request.accepted));
await writeFile(join(output, 'oracle.json'), JSON.stringify({
  scope: 'Unmodified Playwright and mitmproxy 12.2.3 HARs of actual Chromium/Firefox API-header, query, URL-encoded POST and multipart POST requests. Credentials and acceptance logic are authored local controls, never real accounts.',
  credentials: { ...credentials, api_key: apiKey }, requests, rows,
}, null, 2) + '\n');
console.log(JSON.stringify(rows.map(({ engine, surfaces }) => ({ engine, credentialSurfaces: surfaces.length }))));
