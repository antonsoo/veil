// Bundles the real `veil` Python package source into a single JSON manifest
// the browser can fetch and write into Pyodide's virtual filesystem. This
// is what lets the demo run the *actual* library, not a JS reimplementation
// - veil's core has zero runtime dependencies, so plain source files are
// enough (no wheel build / micropip needed).
import { readdirSync, readFileSync, statSync, writeFileSync, mkdirSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));
const srcRoot = join(here, "..", "..", "src", "veil");
const outDir = join(here, "..", "public");
const outFile = join(outDir, "veil-src.json");

function walk(dir, base, out) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const stat = statSync(full);
    if (stat.isDirectory()) {
      walk(full, base, out);
    } else if (entry.endsWith(".py")) {
      const rel = relative(base, full).split(/[/\\]/).join("/");
      out[`veil/${rel}`] = readFileSync(full, "utf-8");
    }
  }
}

const manifest = {};
walk(srcRoot, srcRoot, manifest);

mkdirSync(outDir, { recursive: true });
writeFileSync(outFile, JSON.stringify(manifest));
console.log(`wrote ${Object.keys(manifest).length} files to ${outFile}`);
