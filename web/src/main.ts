/// <reference types="vite/client" />
// veil demo — runs the real `veil` Python package in the browser via
// Pyodide (see scripts/copy-veil-src.mjs for how the source gets here).
// Nothing on this page ever leaves the browser: no network calls happen
// after Pyodide and the package source finish loading.
import "./fonts/fonts.css";
import "./style.css";

import { MAX_NAMES_LENGTH, MAX_PROMPT_LENGTH, PREVIEW_LENGTH, PREVIEW_MAPPINGS } from "./protocol";
import type { MaskResult, Reply, Request, VaultMapping } from "./protocol";

const app = document.getElementById("app");
if (!app) throw new Error("missing #app root");

app.innerHTML = `
  <header class="topbar">
    <div class="wordmark">veil <span class="eyebrow">reversible PII masking</span></div>
    <button class="theme-toggle" id="theme-toggle" type="button">dark / light</button>
  </header>

  <main class="page-main">
  <section class="intro">
    <h1>Watch a prompt get <span class="accent">veiled</span>.</h1>
    <p class="lede">
      Paste text with personal data below. Everything runs locally, in this
      tab. The Python runtime downloads when you select Mask it; your prompt
      and vault stay here. Use fictional data to explore what the detectors catch.
    </p>
  </section>

  <section class="stage" data-stage="input">
    <label for="prompt">Your prompt</label>
    <textarea id="prompt" spellcheck="false" aria-describedby="input-limits"></textarea>

    <label for="known-persons">Known entities <span class="hint">(names your app already knows — from your CRM or user record)</span></label>
    <input id="known-persons" type="text" spellcheck="false" />
    <p class="note">
      veil detects emails, phones, cards, and the like by pattern — an
      arbitrary <em>name</em> needs a backend like this one, or an NER
      model. <a href="https://github.com/antonsoo/veil#features" target="_blank" rel="noreferrer">More in the README →</a>
    </p>

    <p class="note" id="input-limits">Demo limit: 100,000 characters in the prompt and 10,000 in known names; some symbols count twice. Longer input is rejected, never truncated.</p>
    <div class="actions">
      <button id="mask-btn" type="button">Mask it</button>
      <button id="stop-btn" class="secondary" type="button" hidden>Cancel</button>
      <button id="clear-btn" class="secondary" type="button">Clear private data</button>
    </div>
    <div class="status" id="load-status" role="status" aria-live="polite">Ready. Each prompt gets its own vault.</div>
  </section>

  <section class="stage" data-stage="masked" hidden>
    <h2><span class="step-label">masked prompt</span> what this prompt would send</h2>
    <pre class="panel" id="masked-output"></pre>
    <p class="note" id="preview-note"></p>
    <button id="download-masked" class="secondary" type="button">Download complete masked prompt</button>
  </section>

  <section class="stage" data-stage="vault" hidden>
    <h2><span class="step-label">vault</span> kept in this tab only</h2>
    <p class="note" id="vault-count"></p>
    <div class="table-scroll" role="region" aria-label="Vault mappings" tabindex="0">
    <table class="panel" id="vault-table" data-revealed="false">
      <thead>
        <tr><th>Type</th><th>Surrogate</th><th>Original</th></tr>
      </thead>
      <tbody></tbody>
    </table>
    </div>
    <button class="secondary" id="reveal-btn" type="button" aria-pressed="false">Reveal originals</button>
    <button class="secondary" id="download-vault" type="button">Download vault (contains originals)</button>
    <button id="simulate-btn" type="button">Simulate a model reply</button>
  </section>

  <section class="stage" data-stage="reply" hidden>
    <h2><span class="step-label">restored reply</span> streamed back through <code>Restorer</code></h2>
    <p class="note">Fictional reply using this prompt only. No model is called and no action is performed.</p>
    <pre class="panel" id="reply-output"></pre>
  </section>
  </main>

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

const stopBtn = el<HTMLButtonElement>("stop-btn");
const clearBtn = el<HTMLButtonElement>("clear-btn");
const downloadMasked = el<HTMLButtonElement>("download-masked");
const downloadVault = el<HTMLButtonElement>("download-vault");
const previewNote = el<HTMLParagraphElement>("preview-note");
const vaultCount = el<HTMLParagraphElement>("vault-count");

// Storage is optional. A private or sandboxed tab must still work.
try {
  const saved = localStorage.getItem("veil-theme");
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
} catch { /* use the system theme */ }
themeToggle.addEventListener("click", () => {
  const current = document.documentElement.dataset.theme ??
    (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("veil-theme", next); } catch { /* in-memory theme still works */ }
});

let worker: Worker | null = null;
let sequence = 0;
let busy = false;
let sessionReady = false;
let lastResult: MaskResult | null = null;
let lastInput = "";
let revealed = false;
let pending: { id: number; resolve: (reply: Reply) => void; reject: (error: Error) => void; timer: number } | null = null;

const snapshot = () => JSON.stringify([promptEl.value, knownPersonsEl.value]);
function controls(): void {
  maskBtn.disabled = busy;
  stopBtn.hidden = !busy;
  simulateBtn.disabled = busy || !sessionReady || lastResult === null || lastInput !== snapshot();
}

function cancelWork(): void {
  sequence += 1;
  worker?.terminate();
  worker = null;
  sessionReady = false;
  if (pending) {
    clearTimeout(pending.timer);
    pending.reject(new DOMException("Cancelled", "AbortError"));
    pending = null;
  }
  busy = false;
  controls();
}

function request(message: Request): Promise<Reply> {
  if (!worker) {
    worker = new Worker(new URL("./python.worker.ts", import.meta.url), { type: "module" });
    const owner = worker;
    owner.onmessage = (event: MessageEvent<Reply>) => {
      if (worker !== owner || event.data.id !== sequence || pending?.id !== event.data.id) return;
      if (event.data.kind === "status") {
        loadStatus.textContent = event.data.message;
        return;
      }
      clearTimeout(pending.timer);
      pending.resolve(event.data);
      pending = null;
    };
    owner.onerror = (event) => {
      event.preventDefault();
      if (worker !== owner || !pending) return;
      clearTimeout(pending.timer);
      pending.reject(new Error("Couldn't start Python. Select Mask it to retry."));
      pending = null;
    };
  }
  const owner = worker;
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      if (pending?.id !== message.id) return;
      pending = null;
      reject(new Error("Python took too long to respond. Select Mask it to retry."));
    }, 120_000);
    pending = { id: message.id, resolve, reject, timer };
    owner.postMessage(message);
  });
}

function renderMaskedOutput(result: MaskResult): void {
  maskedOutput.replaceChildren();
  let end = Math.min(result.masked.length, PREVIEW_LENGTH);
  if (end < result.masked.length && /[\uD800-\uDBFF]/.test(result.masked[end - 1] ?? "")) end -= 1;
  const preview = result.masked.slice(0, end);
  const surrogates = new Set(result.mappings.map((mapping) => mapping.surrogate));
  let start = 0;
  for (const match of preview.matchAll(/⟨[A-Z]+_\d+⟩/g)) {
    if (!surrogates.has(match[0])) continue;
    maskedOutput.append(document.createTextNode(preview.slice(start, match.index)));
    const span = document.createElement("span");
    span.className = "tok";
    span.textContent = match[0];
    maskedOutput.append(span);
    start = match.index + match[0].length;
  }
  maskedOutput.append(document.createTextNode(preview.slice(start)));
  previewNote.textContent = end < result.masked.length
    ? `Preview shows the first ${end.toLocaleString()} text units. The download contains the complete masked prompt.`
    : "Complete masked prompt. Review it before sharing: detection can miss personal data.";
}

function renderVault(): void {
  vaultBody.replaceChildren();
  if (!lastResult) return;
  const mappings = lastResult.mappings;
  for (const mapping of mappings.slice(0, PREVIEW_MAPPINGS)) {
    const row = document.createElement("tr");
    for (const [className, text] of [
      ["type-cell", mapping.type], ["surrogate-cell", mapping.surrogate],
      ["original-cell", revealed ? mapping.original : "Hidden"],
    ]) {
      const cell = document.createElement("td");
      cell.className = className;
      cell.textContent = text;
      row.append(cell);
    }
    vaultBody.append(row);
  }
  vaultCount.textContent = `${mappings.length.toLocaleString()} ${mappings.length === 1 ? "mapping" : "mappings"} in this prompt.` +
    (mappings.length > PREVIEW_MAPPINGS ? ` Showing the first ${PREVIEW_MAPPINGS}; the vault download includes all mappings.` : "");
  vaultTable.dataset.revealed = String(revealed);
  revealBtn.textContent = revealed ? "Hide originals" : "Reveal originals";
  revealBtn.setAttribute("aria-pressed", String(revealed));
}

function failure(error: unknown, id: number): void {
  if (id !== sequence) return;
  worker?.terminate();
  worker = null;
  sessionReady = false;
  loadStatus.textContent = error instanceof Error ? error.message : "Couldn't process the prompt. Try again.";
}

async function mask(): Promise<void> {
  const prompt = promptEl.value;
  const names = knownPersonsEl.value;
  if (!prompt.trim()) {
    loadStatus.textContent = "Enter a prompt to mask.";
    promptEl.focus();
    return;
  }
  if (prompt.length > MAX_PROMPT_LENGTH || names.length > MAX_NAMES_LENGTH) {
    loadStatus.textContent = "Input exceeds the demo limits. Shorten it and try again; the previous result is unchanged.";
    return;
  }
  const input = snapshot();
  const id = ++sequence;
  busy = true;
  controls();
  loadStatus.textContent = "Preparing to mask locally…";
  try {
    const reply = await request({ id, kind: "mask", prompt, names,
      manifestUrl: new URL(`${import.meta.env.BASE_URL}veil-src.json`, location.href).href });
    if (id !== sequence) return;
    if (reply.kind === "error") throw new Error(reply.message);
    if (reply.kind !== "masked") throw new Error("Unexpected result. Try masking again.");
    lastResult = reply.result;
    lastInput = input;
    sessionReady = true;
    revealed = false;
    renderMaskedOutput(lastResult);
    renderVault();
    maskedStage.hidden = false;
    vaultStage.hidden = false;
    replyStage.hidden = true;
    replyOutput.textContent = "";
    loadStatus.textContent = `Masked this prompt with ${lastResult.mappings.length.toLocaleString()} mappings. Its vault is separate from earlier prompts.`;
  } catch (error) {
    failure(error, id);
  } finally {
    if (id === sequence) { busy = false; controls(); }
  }
}
maskBtn.addEventListener("click", () => { void mask(); });

function inputChanged(): void {
  if (busy) cancelWork();
  replyOutput.textContent = "";
  replyStage.hidden = true;
  loadStatus.textContent = lastResult
    ? "Input changed. The previous result remains below; mask again before simulating a reply."
    : "Input changed. Select Mask it to start.";
  controls();
}
promptEl.addEventListener("input", inputChanged);
knownPersonsEl.addEventListener("input", inputChanged);
stopBtn.addEventListener("click", () => {
  cancelWork();
  replyOutput.textContent = "";
  replyStage.hidden = true;
  loadStatus.textContent = "Cancelled. Select Mask it when you're ready to continue.";
  maskBtn.focus();
});
clearBtn.addEventListener("click", () => {
  cancelWork();
  lastResult = null;
  lastInput = "";
  revealed = false;
  promptEl.value = "";
  knownPersonsEl.value = "";
  maskedOutput.replaceChildren();
  vaultBody.replaceChildren();
  replyOutput.replaceChildren();
  previewNote.textContent = "";
  vaultCount.textContent = "";
  maskedStage.hidden = vaultStage.hidden = replyStage.hidden = true;
  loadStatus.textContent = "Cleared the prompt, vault and reply from this session.";
  controls();
  promptEl.focus();
});
revealBtn.addEventListener("click", () => { revealed = !revealed; renderVault(); });

function download(text: string, name: string, type: string): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
downloadMasked.addEventListener("click", () => {
  if (lastResult) download(lastResult.masked, "veil-masked.txt", "text/plain;charset=utf-8");
});
downloadVault.addEventListener("click", () => {
  if (lastResult) download(JSON.stringify({ version: 1, mappings: lastResult.mappings }, null, 2), "veil-vault.json", "application/json");
});

function cannedReply(mappings: VaultMapping[]): string {
  const surrogateFor = (type: string) => mappings.find((mapping) => mapping.type === type)?.surrogate;
  const person = surrogateFor("PERSON");
  const email = surrogateFor("EMAIL");
  const greeting = person ? `Hi ${person}.` : "Thanks for your message.";
  return email ? `${greeting} The contact email in your message is ${email}.` : `${greeting} I've noted the details in your message.`;
}

async function simulate(): Promise<void> {
  if (!lastResult || simulateBtn.disabled) return;
  const id = ++sequence;
  const characters = Array.from(cannedReply(lastResult.mappings));
  const chunks: string[] = [];
  for (let pos = 0; pos < characters.length; pos += 3) chunks.push(characters.slice(pos, pos + 3).join(""));
  busy = true;
  controls();
  replyOutput.textContent = "";
  replyStage.hidden = false;
  loadStatus.textContent = "Restoring a fictional reply from this prompt…";
  try {
    const reply = await request({ id, kind: "restore", chunks });
    if (id !== sequence) return;
    if (reply.kind === "error") throw new Error(reply.message);
    if (reply.kind !== "restored") throw new Error("Mask this prompt again before simulating.");
    const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
    for (const chunk of reply.chunks) {
      if (!reducedMotion) await new Promise((resolve) => setTimeout(resolve, 45));
      if (id !== sequence) return;
      replyOutput.textContent += chunk;
    }
    loadStatus.textContent = "Fictional reply restored. No model was called.";
  } catch (error) {
    failure(error, id);
  } finally {
    if (id === sequence) { busy = false; controls(); }
  }
}
simulateBtn.addEventListener("click", () => { void simulate(); });
controls();
