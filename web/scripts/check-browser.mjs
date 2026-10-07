// Real Python in both browser engines; no substitute detector or mocked result.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, firefox } from "playwright";

const root = fileURLToPath(new URL("../", import.meta.url));
const dist = join(root, "dist");
const evidence = [];
const axe = await readFile(join(root, "node_modules/axe-core/axe.min.js"), "utf8");
const mime = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".woff2": "font/woff2" };
const server = createServer(async (request, response) => {
  try {
    const path = new URL(request.url, "http://localhost").pathname.replace(/^\/veil\//, "");
    const target = resolve(dist, path || "index.html");
    if (!target.startsWith(dist + "/")) throw new Error("outside build");
    const contents = await readFile(target);
    response.writeHead(200, { "Content-Type": mime[extname(target)] ?? "application/octet-stream" });
    response.end(contents);
  } catch {
    response.writeHead(404);
    response.end();
  }
});
await new Promise((done) => server.listen(0, "127.0.0.1", done));
const origin = `http://127.0.0.1:${server.address().port}`;
const status = (page, text) => page.waitForFunction((expected) => document.querySelector("#load-status").textContent.includes(expected), text, { timeout: 60_000 });
const mask = async (page) => {
  await page.locator("#mask-btn").click();
  await status(page, "Masked this prompt");
};
const assertNoOverflow = async (page) => assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), "page overflow");
const assertClean = async (page, errors) => {
  assert.deepEqual(errors, [], "browser errors");
  assert.deepEqual(await page.evaluate(() => globalThis.policyViolations), [], "CSP violations");
};
const audit = async (page) => {
  await page.evaluate(axe);
  const result = await page.evaluate(() => axe.run());
  assert.deepEqual(result.violations.map(({ id, nodes }) => ({ id, targets: nodes.map((node) => node.target) })), [], "axe violations");
  await assertNoOverflow(page);
};

async function pageFor(browser, options = {}) {
  const context = await browser.newContext({ reducedMotion: "reduce", ...options });
  const errors = [];
  const requests = [];
  await context.addInitScript(() => {
    globalThis.policyViolations = [];
    document.addEventListener("securitypolicyviolation", (event) => globalThis.policyViolations.push(event.violatedDirective));
  });
  context.on("request", (request) => {
    if (!request.url().startsWith(origin)) requests.push({ url: request.url(), method: request.method(), body: request.postData() });
  });
  const page = await context.newPage();
  page.on("pageerror", (error) => errors.push(error.message));
  return { context, page, errors, requests };
}

try {
  for (const [engine, launcher] of [["chromium", chromium], ["firefox", firefox]]) {
    const browser = await launcher.launch();
    try {
      for (const width of [320, 1280]) for (const colorScheme of ["light", "dark"]) {
        const { context, page, errors, requests } = await pageFor(browser, { viewport: { width, height: 900 }, colorScheme });
        try {
          await page.goto(`${origin}/veil/`);
          assert.equal(requests.length, 0, "no runtime download before the user starts");
          await page.locator("#mask-btn").focus();
          await page.keyboard.press("Enter");
          await status(page, "Masked this prompt");
          assert.equal(await page.locator("#vault-table tbody tr").count(), 4);
          assert.ok(!(await page.locator("#vault-table").textContent()).includes("jordan.alvarez@example.com"));
          await page.locator("#reveal-btn").click();
          assert.ok((await page.locator("#vault-table").textContent()).includes("jordan.alvarez@example.com"));
          await page.locator("#reveal-btn").click();
          assert.ok(!(await page.locator("#vault-table").textContent()).includes("jordan.alvarez@example.com"));
          await page.locator("#simulate-btn").click();
          await status(page, "Fictional reply restored");
          assert.ok((await page.locator("#reply-output").textContent()).includes("Jordan Alvarez"));
          await audit(page);
          if (process.env.VEIL_SCREENSHOTS && width === (colorScheme === "light" ? 320 : 1280) && engine === "chromium") {
            await mkdir(process.env.VEIL_SCREENSHOTS, { recursive: true });
            await page.screenshot({ path: join(process.env.VEIL_SCREENSHOTS, `veil-${width}-${colorScheme}.png`), fullPage: true });
          }
          // With the runtime loaded, even a different prompt needs no network.
          const before = requests.length;
          await context.setOffline(true);
          await page.locator("#prompt").fill('Morgan Rivera at morgan@example.net. Literal <img src=x onerror=alert(1)>');
          await page.locator("#known-persons").fill("Morgan Rivera");
          assert.equal(await page.locator("#simulate-btn").isDisabled(), true);
          await mask(page);
          assert.equal(await page.locator("#vault-table tbody tr").count(), 2);
          await page.locator("#simulate-btn").click();
          await status(page, "Fictional reply restored");
          const reply = await page.locator("#reply-output").textContent();
          assert.ok(reply.includes("Morgan Rivera") && reply.includes("morgan@example.net"));
          assert.ok(!reply.includes("Jordan") && !reply.includes("jordan.alvarez"));
          assert.equal(await page.locator("#masked-output img").count(), 0);
          assert.equal(requests.length, before);
          const download = page.waitForEvent("download");
          await page.locator("#download-vault").click();
          const file = await download;
          const vault = JSON.parse(await readFile(await file.path(), "utf8"));
          assert.deepEqual(vault.mappings.map((m) => m.original).sort(), ["Morgan Rivera", "morgan@example.net"]);
          await page.locator("#clear-btn").click();
          assert.equal(await page.locator("#prompt").inputValue(), "");
          assert.equal(await page.locator("#known-persons").inputValue(), "");
          assert.equal(await page.locator("#vault-table tbody tr").count(), 0);
          assert.equal(await page.locator("#reply-output").textContent(), "");
          assert.equal(await page.locator("#masked-output").textContent(), "");
          assert.equal(await page.locator("#prompt").evaluate((element) => element === document.activeElement), true);
          for (const request of requests) {
            const url = new URL(request.url);
            assert.equal(url.origin, "https://cdn.jsdelivr.net");
            assert.ok(url.pathname.startsWith("/pyodide/v0.26.4/full/"));
            assert.equal(url.search, "");
            assert.equal(request.method, "GET");
            assert.equal(request.body, null);
          }
          await assertClean(page, errors);
          evidence.push({ engine, width, colorScheme, checks: ["real Python", "keyboard", "hidden originals", "prompt isolation", "offline reuse", "inert markup", "complete vault export", "clear", "axe", "CSP", "no overflow"], runtimeAssetRequests: requests.length });
          console.log(`PASS ${engine} ${width}px ${colorScheme}`);
        } finally { await context.close(); }
      }

      const { context, page, errors } = await pageFor(browser, { viewport: { width: 375, height: 900 }, reducedMotion: "no-preference" });
      try {
        await context.addInitScript(() => {
          Object.defineProperty(Storage.prototype, "getItem", { value() { throw new DOMException("denied", "SecurityError"); } });
          Object.defineProperty(Storage.prototype, "setItem", { value() { throw new DOMException("denied", "SecurityError"); } });
        });
        await page.goto(`${origin}/veil/`);
        await page.locator("#theme-toggle").click();
        await mask(page);
        await page.locator("#simulate-btn").click();
        await page.waitForFunction(() => document.querySelector("#reply-output").textContent.length > 0);
        await page.locator("#clear-btn").click();
        await page.waitForTimeout(250);
        assert.equal(await page.locator("#reply-output").textContent(), "");
        assert.equal(await page.locator("#vault-table tbody tr").count(), 0);
        // Large previews are bounded, while both downloads retain every value.
        const prompt = Array.from({ length: 600 }, (_, i) => `Contact person${i}@example.net about a fictional issue.`).join("\n");
        await page.locator("#prompt").fill(prompt);
        await mask(page);
        assert.equal(await page.locator("#vault-table tbody tr").count(), 100);
        assert.ok((await page.locator("#vault-count").textContent()).includes("600 mappings"));
        assert.ok((await page.locator("#preview-note").textContent()).includes("Preview shows"));
        const downloads = [];
        for (const selector of ["#download-masked", "#download-vault"]) {
          const event = page.waitForEvent("download");
          await page.locator(selector).click();
          downloads.push(await readFile(await (await event).path(), "utf8"));
        }
        assert.ok(downloads[0].includes("⟨EMAIL_600⟩"));
        assert.equal(JSON.parse(downloads[1]).mappings.length, 600);
        const prior = await page.locator("#masked-output").textContent();
        await page.locator("#prompt").fill("x".repeat(100_001));
        await page.locator("#mask-btn").click();
        await status(page, "exceeds the demo limits");
        assert.equal(await page.locator("#masked-output").textContent(), prior);
        assert.equal(await page.locator("#simulate-btn").isDisabled(), true);
        await assertNoOverflow(page);
        await assertClean(page, errors);
        evidence.push({ engine, checks: ["denied storage", "clear during streaming", "bounded preview", "full downloads", "oversize rejection preserves previous result"] });
        console.log(`PASS ${engine} recovery and limits`);
      } finally { await context.close(); }

      const recovery = await pageFor(browser);
      try {
        let block = true;
        // Block the worker itself: deterministic in Firefox as well as Chromium,
        // without substituting Python or injecting an implementation-specific error.
        await recovery.context.route("**/assets/python.worker-*.js", (route) => block ? route.abort() : route.continue());
        await recovery.page.goto(`${origin}/veil/`);
        await recovery.page.locator("#mask-btn").click();
        await status(recovery.page, "Couldn't start Python");
        block = false;
        await mask(recovery.page);
        await recovery.page.locator("#clear-btn").click();
        let release;
        const held = new Promise((resolve) => { release = resolve; });
        await recovery.context.unroute("**/assets/python.worker-*.js");
        await recovery.context.route("**/assets/python.worker-*.js", async (route) => {
          await held;
          await route.continue().catch(() => {});
        });
        await recovery.page.locator("#prompt").fill("cancelled@example.net");
        await recovery.page.locator("#mask-btn").click();
        await recovery.page.locator("#stop-btn").click();
        await status(recovery.page, "Cancelled");
        release();
        await recovery.page.waitForTimeout(250);
        assert.equal(await recovery.page.locator("#vault-table tbody tr").count(), 0);
        await recovery.context.unroute("**/assets/python.worker-*.js");
        await mask(recovery.page);
        await assertClean(recovery.page, recovery.errors);
        evidence.push({ engine, checks: ["worker load failure", "retry", "cancellation during load", "stale result suppression", "retry after cancellation"] });
        console.log(`PASS ${engine} load failure and cancellation`);
      } finally { await recovery.context.close(); }
    } finally { await browser.close(); }
  }
  if (process.env.VEIL_BROWSER_EVIDENCE) await writeFile(process.env.VEIL_BROWSER_EVIDENCE, JSON.stringify(evidence, null, 2) + "\n");
  console.log(`${evidence.length} browser scenarios passed.`);
} finally {
  await new Promise((done) => server.close(done));
}
