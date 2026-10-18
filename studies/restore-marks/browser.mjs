// Actual demo downloads plus an explicit diagnostic of its served Python.
// Tolerant restoration is a library API; the demo UI exposes exact streaming.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const [url, outputArg, phase, engineOnly] = process.argv.slice(2);
assert.ok(url && outputArg && ["before", "after"].includes(phase), "URL OUTPUT before|after [chromium|firefox]");
const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(join(here, "../../web/package.json"));
const { chromium, firefox } = require("playwright");
const output = resolve(outputArg);
await mkdir(output, { recursive: true });
const reference = JSON.parse(await readFile(join(here, "results/after.json"), "utf8")).direct.results;
const before = JSON.parse(await readFile(join(here, "results/before.json"), "utf8")).direct.results;
const sha = (data) => createHash("sha256").update(data).digest("hex");
const rows = [];
for (const [engine, launcher] of [["chromium", chromium], ["firefox", firefox]]) {
  if (engineOnly && engineOnly !== engine) continue;
  const browser = await launcher.launch();
  try {
    for (const width of [1280, 375]) {
      const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: "reduce", colorScheme: "light" });
      try {
        const requests = [], errors = [];
        context.on("request", (r) => requests.push({ url: r.url(), method: r.method(), body: r.postData() }));
        const page = await context.newPage();
        page.on("pageerror", (e) => errors.push(e.message));
        await page.goto(url);
        assert.ok(requests.every((r) => new URL(r.url).origin === new URL(url).origin), "no runtime before masking");
        await page.locator("#mask-btn").click();
        await page.waitForFunction(() => document.querySelector("#load-status").textContent.includes("Masked this prompt"), null, { timeout: 60_000 });
        await page.evaluate(() => document.fonts.ready);
        // This second runtime is an explicit diagnostic, not an invented UI
        // feature. It executes the unmodified canonical Python manifest.
        const diagnostic = await page.evaluate(async (reference) => {
          const runtime = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";
          const { loadPyodide } = await import(runtime + "pyodide.mjs");
          const python = await loadPyodide({ indexURL: runtime });
          const response = await fetch(new URL("veil-src.json", location.href));
          if (!response.ok) throw new Error("Python manifest unavailable");
          const manifestText = await response.text(), manifest = JSON.parse(manifestText);
          for (const [path, code] of Object.entries(manifest)) {
            const full = "/veil_src/" + path;
            python.FS.mkdirTree(full.slice(0, full.lastIndexOf("/")));
            python.FS.writeFile(full, code);
          }
          python.globals.set("cases_json", JSON.stringify(reference));
          const result = await python.runPythonAsync(`
import json, sys, unicodedata
sys.path.insert(0, "/veil_src")
from veil import Masker, RealisticSurrogates, Restorer
from veil.types import EntityType
from veil.backends.known_entities import KnownEntitiesBackend
m = Masker(surrogate_generator=RealisticSurrogates(), name_backends=[KnownEntitiesBackend(persons=["Jordan Alvarez"])])
for index in range(1, 48):
    m.vault.get_or_create(EntityType.PERSON, f"Controlled contact {index}", m.surrogate_generator)
assert m.mask("Jordan Alvarez") == "Avery Castillo"
rows = []
for case in json.loads(cases_json):
    text = case["text"]
    r = Restorer(m.vault)
    rows.append({"name": case["name"], "restored": m.restore(text), "exact": m.restore(text, tolerant=False), "streamed": "".join(r.feed(c) for c in text) + r.flush()})
json.dumps({"python": sys.version, "unicodeDatabase": unicodedata.unidata_version, "rows": rows})
`);
          return { ...JSON.parse(result), manifestText, modules: Object.keys(manifest).length };
        }, reference);
        for (const [index, row] of diagnostic.rows.entries()) {
          assert.equal(row.restored, (phase === "before" ? before : reference)[index].restored, row.name);
          assert.equal(row.exact, reference[index].exactExpected);
          assert.equal(row.streamed, reference[index].exactExpected);
        }
        const manifestSha256 = sha(diagnostic.manifestText);
        const manifest = JSON.parse(diagnostic.manifestText);
        for (const request of requests) {
          if (new URL(request.url).origin === new URL(url).origin) continue;
          const external = new URL(request.url);
          assert.equal(external.origin, "https://cdn.jsdelivr.net");
          assert.ok(external.pathname.startsWith("/pyodide/v0.26.4/full/"));
          assert.equal(external.search, "");
          assert.equal(request.method, "GET");
          assert.equal(request.body, null);
        }
        await writeFile(join(output, `${engine}-${width}-manifest.json`), JSON.stringify({ sha256: manifestSha256, modules: Object.fromEntries(Object.entries(manifest).map(([name, contents]) => [name, sha(contents)])) }, null, 2) + "\n");
        delete diagnostic.manifestText;
        await context.setOffline(true);
        const prior = requests.length;
        const prompt = "Jordan Alvarez wrote to jordan@example.org; public note: avery castillo\u0301.";
        await page.locator("#prompt").fill(prompt);
        await page.locator("#known-persons").fill("Jordan Alvarez");
        await page.locator("#mask-btn").click();
        await page.waitForFunction(() => document.querySelector("#load-status").textContent.includes("Masked this prompt"));
        const downloads = {};
        for (const [selector, extension] of [["#download-masked", "txt"], ["#download-vault", "json"]]) {
          const pending = page.waitForEvent("download");
          await page.locator(selector).click();
          const body = await readFile(await (await pending).path(), "utf8");
          await writeFile(join(output, `${engine}-${width}-${extension === "txt" ? "masked.txt" : "vault.json"}`), body);
          downloads[extension] = body;
        }
        assert.equal(downloads.txt, "⟨PERSON_1⟩ wrote to ⟨EMAIL_1⟩; public note: avery castillo\u0301.");
        const vault = JSON.parse(downloads.json);
        assert.deepEqual(vault.mappings.map((m) => m.original).sort(), ["Jordan Alvarez", "jordan@example.org"]);
        await page.locator("#simulate-btn").click();
        await page.waitForFunction(() => document.querySelector("#load-status").textContent.includes("Fictional reply restored"));
        const reply = await page.locator("#reply-output").textContent();
        assert.ok(reply.includes("Jordan Alvarez") && reply.includes("jordan@example.org"));
        assert.equal(requests.length, prior, "no offline requests");
        assert.deepEqual(errors, []);
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
        await page.locator("#mask-btn").scrollIntoViewIfNeeded();
        await page.screenshot({ path: join(output, `${engine}-${width}.png`), fullPage: true });
        rows.push({ engine, version: browser.version(), width, diagnostic, manifestSha256, offlineDownloads: 2, originalPrompt: prompt, reply, offlineRequests: requests.length - prior, errors });
        console.log(`${engine}/${width}: 19 served-Python controls and actual offline UI downloads agree with ${phase}`);
      } finally { await context.close(); }
    }
  } finally { await browser.close(); }
}
await writeFile(join(output, `browser${engineOnly ? "-" + engineOnly : ""}.json`), JSON.stringify({ phase, url, scope: "Unmodified served Python in an explicit Pyodide diagnostic; actual UI uses exact streaming, default placeholders, offline masked/vault downloads.", contexts: rows.length, rows }, null, 2) + "\n");
