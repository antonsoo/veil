/// <reference types="vite/client" />
// veil demo — runs the real `veil` Python package in the browser via
// Pyodide (see scripts/copy-veil-src.mjs for how the source gets here).
// Nothing on this page ever leaves the browser: no network calls happen
// after Pyodide and the package source finish loading.
import "./style.css";

// Pyodide's own types aren't bundled; this is the small slice of its API
// this file actually touches.
interface PyProxyCallable {
  (...args: unknown[]): unknown;
}
interface PyodideInterface {
  runPythonAsync(code: string): Promise<unknown>;
  runPython(code: string): unknown;
  globals: { get(name: string): PyProxyCallable };
  FS: {
    mkdirTree(path: string): void;
    writeFile(path: string, data: string): void;
  };
}
declare function loadPyodide(config: { indexURL: string }): Promise<PyodideInterface>;

const PYODIDE_VERSION = "0.26.4";
const PYODIDE_CDN = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;

interface VaultMapping {
  type: string;
  surrogate: string;
  original: string;
}
interface MaskResult {
  masked: string;
  mappings: VaultMapping[];
}

const app = document.getElementById("app");
if (!app) throw new Error("missing #app root");

app.innerHTML = `
  <header class="topbar">
    <div class="wordmark">veil <span class="eyebrow">reversible PII masking</span></div>
    <button class="theme-toggle" id="theme-toggle" type="button">dark / light</button>
  </header>

  <section class="intro">
    <h1>Watch a prompt get <span class="accent">veiled</span>.</h1>
    <p class="lede">
      Paste text with personal data below. Everything runs locally, in this
      tab, using the real <code>veil</code> Python package compiled to
      WebAssembly via Pyodide — nothing is sent anywhere.
    </p>
  </section>

  <section class="stage" data-stage="input">
    <label for="prompt">Your prompt</label>
    <textarea id="prompt" spellcheck="false"></textarea>

    <label for="known-persons">Known entities <span class="hint">(names your app already knows — from your CRM or user record)</span></label>
    <input id="known-persons" type="text" spellcheck="false" />
    <p class="note">
      veil detects emails, phones, cards, and the like by pattern — an
      arbitrary <em>name</em> needs a backend like this one, or an NER
      model. <a href="https://github.com/antonsoo/veil#names-orgs-and-locations" target="_blank" rel="noreferrer">More in the README →</a>
    </p>

    <button id="mask-btn" type="button">Mask it</button>
    <div class="status" id="load-status">Loading Pyodide…</div>
  </section>

  <section class="stage" data-stage="masked" hidden>
    <h2><span class="step-label">masked prompt</span> what the model actually sees</h2>
    <pre class="panel" id="masked-output"></pre>
  </section>

  <section class="stage" data-stage="vault" hidden>
    <h2><span class="step-label">vault</span> kept in this tab only</h2>
    <table class="panel" id="vault-table" data-revealed="false">
      <thead>
        <tr><th>Type</th><th>Surrogate</th><th>Original</th></tr>
      </thead>
      <tbody></tbody>
    </table>
    <button class="secondary" id="reveal-btn" type="button">Reveal originals</button>
    <button id="simulate-btn" type="button">Simulate a model reply</button>
  </section>

  <section class="stage" data-stage="reply" hidden>
    <h2><span class="step-label">restored reply</span> streamed back through <code>Restorer</code></h2>
    <pre class="panel" id="reply-output"></pre>
  </section>

  <footer>
    Runs entirely client-side via <a href="https://pyodide.org" target="_blank" rel="noreferrer">Pyodide</a>.
    No prompt, reply, or vault ever leaves this browser tab.
    <a href="https://github.com/antonsoo/veil" target="_blank" rel="noreferrer">Source on GitHub →</a>
  </footer>
`;

const el = <T extends HTMLElement>(id: string): T => {
  const found = document.getElementById(id);
  if (!found) throw new Error(`missing #${id}`);
  return found as T;
};

const promptEl = el<HTMLTextAreaElement>("prompt");
const knownPersonsEl = el<HTMLInputElement>("known-persons");
const maskBtn = el<HTMLButtonElement>("mask-btn");
const loadStatus = el<HTMLDivElement>("load-status");
const maskedStage = el<HTMLElement>("masked-output").closest(".stage") as HTMLElement;
const maskedOutput = el<HTMLPreElement>("masked-output");
const vaultStage = el<HTMLElement>("vault-table").closest(".stage") as HTMLElement;
const vaultTable = el<HTMLTableElement>("vault-table");
const vaultBody = vaultTable.querySelector("tbody") as HTMLTableSectionElement;
const revealBtn = el<HTMLButtonElement>("reveal-btn");
const simulateBtn = el<HTMLButtonElement>("simulate-btn");
const replyStage = el<HTMLElement>("reply-output").closest(".stage") as HTMLElement;
const replyOutput = el<HTMLPreElement>("reply-output");
const themeToggle = el<HTMLButtonElement>("theme-toggle");

promptEl.value =
  "Hi, this is Jordan Alvarez. My email is jordan.alvarez@example.com and " +
  "my phone is 415-555-0132. Please charge card 4111 1111 1111 1111 for " +
  "the renewal.";
knownPersonsEl.value = "Jordan Alvarez";

function knownPersons(): string[] {
  return knownPersonsEl.value
    .split(",")
    .map((name) => name.trim())
    .filter((name) => name.length > 0);
}

// ---- Theme -----------------------------------------------------------

function applyStoredTheme(): void {
  const saved = localStorage.getItem("veil-theme");
  if (saved === "light" || saved === "dark") {
    document.documentElement.dataset.theme = saved;
  }
}
applyStoredTheme();
themeToggle.addEventListener("click", () => {
  const current =
    document.documentElement.dataset.theme ??
    (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("veil-theme", next);
});

// ---- Pyodide bootstrap -------------------------------------------------

let pyodideReady: Promise<PyodideInterface> | null = null;

async function getPyodide(): Promise<PyodideInterface> {
  if (!pyodideReady) {
    pyodideReady = bootstrap();
  }
  return pyodideReady;
}

async function bootstrap(): Promise<PyodideInterface> {
  const script = document.createElement("script");
  script.src = `${PYODIDE_CDN}pyodide.js`;
  const loaded = new Promise<void>((resolve, reject) => {
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("failed to load Pyodide from CDN"));
  });
  document.head.appendChild(script);
  await loaded;

  const pyodide = await loadPyodide({ indexURL: PYODIDE_CDN });

  loadStatus.textContent = "Fetching veil source…";
  const manifestUrl = `${import.meta.env.BASE_URL}veil-src.json`;
  const manifest: Record<string, string> = await (await fetch(manifestUrl)).json();
  for (const [path, contents] of Object.entries(manifest)) {
    const fullPath = `/veil_src/${path}`;
    const dir = fullPath.slice(0, fullPath.lastIndexOf("/"));
    pyodide.FS.mkdirTree(dir);
    pyodide.FS.writeFile(fullPath, contents);
  }

  await pyodide.runPythonAsync(`
import sys, json
sys.path.insert(0, "/veil_src")
from veil import Masker
from veil.backends.known_entities import KnownEntitiesBackend
from veil.restore import Restorer

# The known-entities backend is the first-class way veil finds names: the
# application (here, the demo page) supplies identities it already knows,
# rather than guessing from free text. See do_mask() below for how the
# "Known entities" field feeds this on every call.
known = KnownEntitiesBackend()
masker = Masker(name_backends=[known])

def do_mask(text, persons_json):
    known.persons = json.loads(persons_json)
    masked = masker.mask(text)
    mappings = [
        {"type": m.type.value, "surrogate": m.surrogate, "original": m.original}
        for m in masker.vault.mappings()
    ]
    return json.dumps({"masked": masked, "mappings": mappings})

def make_restorer():
    return Restorer(masker.vault)
`);

  loadStatus.textContent = "";
  maskBtn.disabled = false;
  return pyodide;
}

maskBtn.disabled = true;
getPyodide()
  .then(() => {
    maskBtn.disabled = false;
  })
  .catch((err: unknown) => {
    loadStatus.textContent = `Couldn't load Pyodide: ${String(err)}`;
  });

// ---- Masking -----------------------------------------------------------

function renderMaskedOutput(masked: string, surrogates: string[]): void {
  maskedOutput.innerHTML = "";
  if (surrogates.length === 0) {
    maskedOutput.textContent = masked;
    return;
  }
  const pattern = new RegExp(`(${surrogates.map(escapeRegExp).join("|")})`, "g");
  const parts = masked.split(pattern);
  for (const part of parts) {
    if (surrogates.includes(part)) {
      const span = document.createElement("span");
      span.className = "tok";
      span.textContent = part;
      maskedOutput.appendChild(span);
    } else {
      maskedOutput.appendChild(document.createTextNode(part));
    }
  }
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function renderVault(mappings: VaultMapping[]): void {
  vaultBody.innerHTML = "";
  for (const m of mappings) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="type-cell">${m.type}</td>
      <td class="surrogate-cell">${m.surrogate}</td>
      <td class="original-cell">${escapeHtml(m.original)}</td>
    `;
    vaultBody.appendChild(tr);
  }
  vaultTable.dataset.revealed = "false";
  revealBtn.textContent = "Reveal originals";
}

function escapeHtml(s: string): string {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

maskBtn.addEventListener("click", () => {
  void (async () => {
    const pyodide = await getPyodide();
    const doMask = pyodide.globals.get("do_mask");
    const resultJson = doMask(promptEl.value, JSON.stringify(knownPersons())) as string;
    const result = JSON.parse(resultJson) as MaskResult;
    const surrogates = result.mappings.map((m) => m.surrogate);

    renderMaskedOutput(result.masked, surrogates);
    renderVault(result.mappings);

    maskedStage.hidden = false;
    vaultStage.hidden = false;
    replyStage.hidden = true;
    replyOutput.textContent = "";
  })();
});

revealBtn.addEventListener("click", () => {
  const revealed = vaultTable.dataset.revealed === "true";
  vaultTable.dataset.revealed = revealed ? "false" : "true";
  revealBtn.textContent = revealed ? "Reveal originals" : "Hide originals";
});

// ---- Simulated streaming reply ------------------------------------------

// This is the point the README makes concretely: a redaction tool would
// force something like "Dear [REDACTED]", but veil's surrogates are
// specific enough that the reply can address the person and refer back to
// their details by name — it just can't say the *real* name or email
// until restore happens. A real support bot also wouldn't echo a whole
// card number back, so the card is acknowledged without naming it.
function cannedReply(mappings: VaultMapping[]): string {
  const surrogateFor = (type: string) => mappings.find((m) => m.type === type)?.surrogate;
  const person = surrogateFor("PERSON");
  const email = surrogateFor("EMAIL");
  const hasCard = mappings.some((m) => m.type === "CARD");

  const greeting = person ? `Hi ${person}, thanks` : "Thanks";
  if (hasCard && email) {
    return `${greeting} — I've updated the card on file and will send a receipt to ${email}.`;
  }
  if (email) {
    return `${greeting} — I've noted your details and will follow up at ${email} shortly.`;
  }
  return `${greeting} — I've noted the details and will follow up shortly.`;
}

simulateBtn.addEventListener("click", () => {
  void (async () => {
    const pyodide = await getPyodide();
    const doMask = pyodide.globals.get("do_mask");
    // Re-run mask on the current prompt to be sure the vault reflects it
    // (a no-op if nothing changed — masking is idempotent per value).
    const resultJson = doMask(promptEl.value, JSON.stringify(knownPersons())) as string;
    const result = JSON.parse(resultJson) as MaskResult;
    const reply = cannedReply(result.mappings);

    replyStage.hidden = false;
    replyOutput.textContent = "";
    simulateBtn.disabled = true;

    const makeRestorer = pyodide.globals.get("make_restorer");
    const restorer = makeRestorer() as { feed(chunk: string): string; flush(): string; destroy(): void };

    let i = 0;
    const rand = (min: number, max: number) => Math.floor(min + Math.random() * (max - min + 1));

    const step = () => {
      if (i >= reply.length) {
        replyOutput.textContent += restorer.flush();
        restorer.destroy();
        simulateBtn.disabled = false;
        return;
      }
      const size = rand(2, 6);
      const chunk = reply.slice(i, i + size);
      i += size;
      replyOutput.textContent += restorer.feed(chunk);
      setTimeout(step, rand(30, 90));
    };
    step();
  })();
});
