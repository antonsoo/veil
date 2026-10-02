import { defineConfig } from "vite";
import { contentSecurityPolicy } from "./vite.csp";

export default defineConfig({
  base: "/veil/",
  plugins: [
    contentSecurityPolicy({
      // Pyodide, the Python runtime, comes from its CDN and compiles WebAssembly.
      "script-src": ["'wasm-unsafe-eval'", "https://cdn.jsdelivr.net"],
      "connect-src": ["https://cdn.jsdelivr.net"],
    }),
  ],
  build: {
    target: "es2022",
  },
});
