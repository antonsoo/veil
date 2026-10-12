// Real production UI, Pyodide and downloads; synthetic strings only.
// node browser.mjs <web-root> <output-dir> [--baseline] [--screenshots <dir>]
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const [webArg, outputArg, ...flags] = process.argv.slice(2);
assert.ok(webArg && outputArg, "web root and output directory required");
const web = resolve(webArg), output = resolve(outputArg), dist = join(web, "dist");
const baseline = flags.includes("--baseline");
const shotIndex = flags.indexOf("--screenshots");
const shots = shotIndex < 0 ? null : resolve(flags[shotIndex + 1]);
const require = createRequire(join(web, "package.json"));
const { chromium, firefox } = require("playwright");
const here = dirname(fileURLToPath(import.meta.url));
const cases = JSON.parse(execFileSync(process.env.PYTHON ?? "python3", [
  "-c", "import json; from cases import cases; print(json.dumps(cases()))",
], { cwd: here, encoding: "utf8" }));
const hash = (body) => createHash("sha256").update(body).digest("hex");
await mkdir(output, { recursive: true });
if (shots) await mkdir(shots, { recursive: true });
const mime = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".woff2": "font/woff2" };
const served = new Map();
const server = createServer(async (request, response) => {
  try {
    const pathname = new URL(request.url, "http://localhost").pathname.replace(/^\/veil\//, "");
    const target = resolve(dist, pathname || "index.html");
    if (!target.startsWith(dist + "/")) throw new Error("outside build");
    const body = await readFile(target);
    served.set(target.slice(dist.length + 1), { bytes: body.length, sha256: hash(body) });
    response.writeHead(200, { "Content-Type": mime[extname(target)] ?? "application/octet-stream" });
    response.end(body);
  } catch { response.writeHead(404); response.end(); }
});
await new Promise((done) => server.listen(0, "127.0.0.1", done));
const origin = `http://127.0.0.1:${server.address().port}`;
const results = [];
const captured = new Map();
const status = (page, expected) => page.waitForFunction(
  (value) => document.querySelector("#load-status").textContent.includes(value),
  expected, { timeout: 60_000 },
);
const mask = async (page) => {
  await page.locator("#mask-btn").click();
  await status(page, "Masked this prompt");
};
const download = async (page, selector) => {
  const pending = page.waitForEvent("download");
  await page.locator(selector).click();
  return readFile(await (await pending).path(), "utf8");
};
try {
  for (const [engine, launcher] of [["chromium", chromium], ["firefox", firefox]]) {
    const browser = await launcher.launch();
    try {
      for (const width of [375, 1280]) {
        const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: "reduce", colorScheme: "light" });
        try {
          const errors = [], requests = [], pendingResponses = [];
          await context.addInitScript(() => {
            globalThis.policyViolations = [];
            addEventListener("securitypolicyviolation", (event) => globalThis.policyViolations.push(event.violatedDirective));
          });
          context.on("request", (r) => requests.push({ url: r.url(), method: r.method(), body: r.postData() }));
          context.on("response", (response) => {
            if (!response.url().startsWith(origin)) return;
            pendingResponses.push((async () => {
              const name = new URL(response.url()).pathname.replace(/^\/veil\//, "") || "index.html";
              const body = await response.body();
              assert.deepEqual(body, await readFile(join(dist, name)), `served bytes: ${name}`);
              captured.set(name, { bytes: body.length, sha256: hash(body) });
            })());
          });
          const page = await context.newPage();
          page.on("pageerror", (error) => errors.push(error.message));
          await page.goto(`${origin}/veil/`);
          assert.ok(requests.every((r) => r.url.startsWith(origin)), "no runtime request before first mask");
          await mask(page); // Warm the real runtime and UI fonts using the default example.
          await page.evaluate(() => document.fonts.ready);
          await Promise.all(pendingResponses);
          await context.setOffline(true);
          const requestCount = requests.length;
          const rows = [];
          for (const c of cases) {
            const source = `Use "${c.token}" once; leave this sentence.`;
            const expected = 'Use "⟨SECRET_1⟩" once; leave this sentence.';
            await page.locator("#prompt").fill(source);
            await page.locator("#known-persons").fill("");
            await mask(page);
            const masked = await download(page, "#download-masked");
            const vault = JSON.parse(await download(page, "#download-vault"));
            const row = {
              id: c.id, sourceSha256: hash(source), maskedSha256: hash(masked),
              fullyMasked: masked === expected,
              wholeTokenMapping: vault.mappings.length === 1 && vault.mappings[0].original === c.token,
              mappingCount: vault.mappings.length,
            };
            // Preview and actual export must agree even when baseline coverage fails.
            assert.equal(await page.locator("#masked-output").textContent(), masked);
            if (!baseline) assert.ok(row.fullyMasked && row.wholeTokenMapping, c.id);
            assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), "page overflow");
            if (shots && c.id === "proj-alphanumeric-156") {
              await page.locator("#mask-btn").scrollIntoViewIfNeeded();
              await page.screenshot({ path: join(shots, `${engine}-${width}.png`), fullPage: true });
            }
            rows.push(row);
          }
          assert.equal(requests.length, requestCount, "no requests after switching offline");
          assert.deepEqual(errors, []);
          assert.deepEqual(await page.evaluate(() => globalThis.policyViolations), []);
          const external = requests.filter((r) => !r.url.startsWith(origin));
          for (const r of external) {
            const url = new URL(r.url);
            assert.equal(url.origin, "https://cdn.jsdelivr.net");
            assert.ok(url.pathname.startsWith("/pyodide/v0.26.4/full/"));
            assert.equal(url.search, "");
            assert.equal(r.method, "GET");
            assert.equal(r.body, null);
          }
          results.push({ engine, version: browser.version(), width, cases: rows.length,
            fullyMasked: rows.filter((r) => r.fullyMasked).length,
            offlineRequests: requests.length - requestCount, pageErrors: errors,
            runtimeAssetRequests: external.length, rows });
          console.log(`${engine} ${width}: ${rows.filter((r) => r.fullyMasked).length}/${rows.length} complete masks, offline downloads verified`);
        } finally { await context.close(); }
      }
    } finally { await browser.close(); }
  }
  assert.ok(captured.has("veil-src.json"), "browser received the actual Python source manifest");
  for (const [name, entry] of served) {
    assert.deepEqual(entry, captured.get(name), `browser captured served asset: ${name}`);
  }
  await writeFile(join(output, "browser.json"), JSON.stringify({
    baseline, driverSha256: hash(await readFile(fileURLToPath(import.meta.url))),
    casesSha256: hash(await readFile(join(here, "cases.py"))),
    cases: results.reduce((n, r) => n + r.cases, 0),
    fullyMasked: results.reduce((n, r) => n + r.fullyMasked, 0),
    downloads: results.reduce((n, r) => n + 2 * r.cases, 0),
    servedAssets: Object.fromEntries([...captured].sort()), results,
  }, null, 2) + "\n");
} finally { await new Promise((done) => server.close(done)); }
