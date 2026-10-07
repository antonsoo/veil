/// <reference lib="webworker" />
import { MAX_NAMES_LENGTH, MAX_PROMPT_LENGTH } from "./protocol";
import type { MaskResult, Reply, Request } from "./protocol";

interface PythonFunction {
  (...args: unknown[]): string;
  destroy(): void;
}
interface Python {
  runPythonAsync(code: string): Promise<unknown>;
  globals: { get(name: string): PythonFunction };
  FS: { mkdirTree(path: string): void; writeFile(path: string, data: string): void };
}

const runtimeUrl = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";
let runtime: Promise<Python> | null = null;
const send = (message: Reply) => self.postMessage(message);

async function bootstrap(manifestUrl: string): Promise<Python> {
  const { loadPyodide } = await import(/* @vite-ignore */ `${runtimeUrl}pyodide.mjs`);
  const python = await loadPyodide({ indexURL: runtimeUrl }) as Python;
  const response = await fetch(manifestUrl, { redirect: "error" });
  if (!response.ok) throw new Error("source unavailable");
  const manifest = await response.json() as Record<string, string>;
  for (const [path, contents] of Object.entries(manifest)) {
    const fullPath = `/veil_src/${path}`;
    python.FS.mkdirTree(fullPath.slice(0, fullPath.lastIndexOf("/")));
    python.FS.writeFile(fullPath, contents);
  }
  await python.runPythonAsync(`
import sys, json
sys.path.insert(0, "/veil_src")
from veil import Masker
from veil.backends.known_entities import KnownEntitiesBackend
from veil.restore import Restorer

masker = None

def do_mask(text, names):
    global masker
    persons = [name.strip() for name in names.split(",") if name.strip()]
    candidate = Masker(name_backends=[KnownEntitiesBackend(persons=persons)])
    masked = candidate.mask(text)
    result = json.dumps({"masked": masked, "mappings": candidate.vault.to_dict()["mappings"]})
    masker = candidate
    return result

def restore_chunks(chunks_json):
    if masker is None:
        raise ValueError("mask a prompt first")
    restorer = Restorer(masker.vault)
    chunks = [restorer.feed(chunk) for chunk in json.loads(chunks_json)]
    chunks.append(restorer.flush())
    return json.dumps(chunks)
`);
  return python;
}

function call(python: Python, name: string, ...args: unknown[]): string {
  const fn = python.globals.get(name);
  try {
    return fn(...args);
  } finally {
    fn.destroy();
  }
}

self.onmessage = async (event: MessageEvent<Request>) => {
  const request = event.data;
  let loaded = false;
  try {
    if (request.kind === "mask") {
      if (request.prompt.length > MAX_PROMPT_LENGTH || request.names.length > MAX_NAMES_LENGTH) {
        send({ id: request.id, kind: "error", message: "Input exceeds the demo limits. Shorten it and try again." });
        return;
      }
      if (!runtime) {
        send({ id: request.id, kind: "status", message: "Loading Python for this tab… You can cancel." });
        runtime = bootstrap(request.manifestUrl);
      }
      const python = await runtime;
      loaded = true;
      send({ id: request.id, kind: "status", message: "Masking locally…" });
      const result = JSON.parse(call(python, "do_mask", request.prompt, request.names)) as MaskResult;
      send({ id: request.id, kind: "masked", result });
    } else {
      if (!runtime) throw new Error("missing session");
      const python = await runtime;
      loaded = true;
      const chunks = JSON.parse(call(python, "restore_chunks", JSON.stringify(request.chunks))) as string[];
      send({ id: request.id, kind: "restored", chunks });
    }
  } catch {
    // Python exception text may quote private input. Give an actionable public
    // error without returning a traceback or any prompt data to console logs.
    send({ id: request.id, kind: "error", message: loaded
      ? "Couldn't process this input. Shorten it or clear the session, then try again."
      : "Couldn't load Python. Check your connection and select Mask it to retry." });
  }
};
