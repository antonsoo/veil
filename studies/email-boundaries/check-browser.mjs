// Run from any cwd after building web/. Uses the actual bundled Python in Pyodide.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, firefox } from "../../web/node_modules/playwright/index.mjs";

const here = fileURLToPath(new URL(".", import.meta.url));
const dist = resolve(process.argv[2] ?? join(here, "../../web/dist"));
const out = resolve(process.argv[3] ?? join(here, "results/browser"));
await mkdir(out, { recursive: true });
const cases = JSON.parse(await readFile(join(here, "cases.json"), "utf8")).cases;
const source = cases.map(c => `Contact <${c.address}> today.`).join("\n");
let next = 0;
const expected = cases.map(c => c.mask ? `Contact <⟨EMAIL_${++next}⟩> today.` : `Contact <${c.address}> today.`).join("\n");
const hash = bytes => createHash("sha256").update(bytes).digest("hex");
const mime = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".woff2": "font/woff2" };
const served = new Map();
const server = createServer(async (request, response) => {
  try {
    const path = new URL(request.url, "http://localhost").pathname.replace(/^\/veil\//, "");
    const target = resolve(dist, path || "index.html");
    assert.ok(target.startsWith(dist + "/"));
    const bytes = await readFile(target);
    served.set(new URL(request.url, "http://localhost").pathname, hash(bytes));
    response.writeHead(200, { "Content-Type": mime[extname(target)] ?? "application/octet-stream" });
    response.end(bytes);
  } catch { response.writeHead(404); response.end(); }
});
await new Promise(done => server.listen(0, "127.0.0.1", done));
const origin = `http://127.0.0.1:${server.address().port}`;
const status = (page, wanted) => page.waitForFunction(text => document.querySelector("#load-status").textContent.includes(text), wanted, { timeout: 60_000 });
const download = async (page, selector) => {
  const event = page.waitForEvent("download");
  await page.locator(selector).click();
  return readFile(await (await event).path(), "utf8");
};
const rows = [];
const received = new Map();
const reads = [];
try {
  for (const [engine, launcher] of [["chromium", chromium], ["firefox", firefox]]) {
    const browser = await launcher.launch();
    try {
      for (const width of [375, 1280]) {
        const context = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: "dark", reducedMotion: "reduce" });
        try {
          const page = await context.newPage();
          const errors = [];
          const requests = [];
          page.on("pageerror", error => errors.push(error.message));
          context.on("request", request => requests.push({ url: request.url(), method: request.method(), body: request.postData() }));
          context.on("response", response => {
            if (response.url().startsWith(origin)) reads.push((async () => {
              received.set(new URL(response.url()).pathname, hash(await response.body()));
            })());
          });
          await page.goto(`${origin}/veil/`);
          await page.locator("#known-persons").fill("");
          // Load Python on a neutral prompt. The first Unicode/quoted mailbox
          // operation and every download/simulation occur after disconnection.
          await page.locator("#prompt").fill("Initialize the local Python runtime.");
          await page.locator("#mask-btn").click();
          await status(page, "Masked this prompt");
          await context.setOffline(true);
          const requestCount = requests.length;
          await page.locator("#prompt").fill(source);
          await page.locator("#mask-btn").focus();
          await page.keyboard.press("Enter");
          await status(page, "Masked this prompt");
          assert.equal(await page.locator("#masked-output").textContent(), expected);
          const maskedFile = await download(page, "#download-masked");
          const vaultFile = await download(page, "#download-vault");
          assert.equal(maskedFile, expected);
          const vault = JSON.parse(vaultFile);
          assert.deepEqual(vault.mappings.map(m => m.original), cases.filter(c => c.mask).map(c => c.address));
          let restored = maskedFile;
          for (const m of vault.mappings) restored = restored.replaceAll(m.surrogate, m.original);
          assert.equal(restored, source);
          await page.locator("#simulate-btn").click();
          await status(page, "Fictional reply restored");
          assert.ok((await page.locator("#reply-output").textContent()).includes(cases[0].address));
          await writeFile(join(out, `${engine}-${width}-masked.txt`), maskedFile);
          await writeFile(join(out, `${engine}-${width}-vault.json`), vaultFile);
          const screenshotSource = cases.slice(0, 2).concat(cases.filter(c => ["unicode-local", "quoted-space", "unicode-domain"].includes(c.id)));
          await page.locator("#prompt").fill(screenshotSource.map(c => `Contact <${c.address}>.`).join("\n"));
          await page.locator("#mask-btn").click();
          await status(page, "Masked this prompt");
          await page.locator("#reveal-btn").click();
          await page.locator("#prompt").evaluate(element => { element.scrollTop = 0; });
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
          await page.screenshot({ path: join(out, `${engine}-${width}.png`), fullPage: true });
          assert.deepEqual(errors, []);
          assert.equal(requests.length, requestCount, "offline mailbox actions needed no new assets");
          const external = requests.filter(request => !request.url.startsWith(origin));
          assert.ok(external.every(request => request.url.startsWith("https://cdn.jsdelivr.net/pyodide/v0.26.4/full/") && request.method === "GET" && !request.body));
          rows.push({ engine, width, cases: cases.length, completeMailboxes: next,
            maskedDownloadSha256: hash(maskedFile), vaultDownloadSha256: hash(vaultFile),
            exactRestore: restored === source, offlineRequests: requests.length - requestCount,
            errors, noOverflow: true, runtime: "Actual bundled Python via Pyodide; initialized online with a neutral prompt." });
          console.log(`PASS ${engine} ${width}px: ${cases.length} offline mailbox cases and exact downloads`);
        } finally { await context.close(); }
      }
    } finally { await browser.close(); }
  }
  await Promise.all(reads);
  for (const [path, digest] of received) assert.equal(digest, served.get(path), path);
  const manifest = JSON.parse(await readFile(join(dist, "veil-src.json"), "utf8"));
  const email = await readFile(join(here, "../../src/veil/detectors/email.py"));
  assert.equal(hash(manifest["veil/detectors/email.py"]), hash(email));
  await writeFile(join(out, "receipt.json"), JSON.stringify({ rows, sourceSha256: hash(email),
    manifestSha256: hash(await readFile(join(dist, "veil-src.json"))),
    receivedAssets: Object.fromEntries(received), servedAssetsMatch: true }, null, 2) + "\n");
} finally { await new Promise(done => server.close(done)); }
