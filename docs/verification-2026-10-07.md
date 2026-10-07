# Local verification: 2026-10-07

Verified implementation commit `422c02b` from a fresh detached checkout. These
changes are local and have not been pushed, released or deployed. Artifact hashes
and counts are in [the verification record](verification-2026-10-07.json).

| Environment | Result |
| --- | --- |
| Python 3.12.12, locked dependencies, real spaCy backend | 329 passed |
| Python 3.14.7, locked dependencies, real spaCy backend | 329 passed |
| Python 3.10.21, lowest direct dependencies | 320 passed, 7 skipped |
| Ruff lint and format, strict mypy | Passed; 30 source files typechecked |
| Source distribution and wheel | Built from the fresh checkout |
| Standalone Python 3.10 wheel, no runtime dependencies | CLI round trip, audit exits 0/1, alias protection, vault reload, pool exhaustion, escaped JSON passed |
| Node 24.21.0, `npm ci`, typecheck and production build | Passed; npm audit reported zero advisories |
| Real Pyodide in Chromium and Firefox | 12 scenarios passed |

The minimum environment used OpenAI 1.66.0, Anthropic 0.40.0 and cryptography
50.0.0. Six tests skip features absent from those older SDK models; the seventh
skip is the optional spaCy backend. Both locked full-extra environments run every
test. SDK tests use local fake transports; no model API calls were made.

Browser checks cover 320px and 1280px, light and dark, keyboard activation,
zero axe findings, zero page errors or CSP violations, unrelated-prompt isolation,
offline reuse after loading, clearing during a reply, blocked storage, failed
worker loading, cancellation, recovery, large previews and complete downloads.
Only five fixed Pyodide asset GET requests go off origin per ordinary scenario;
no prompt, vault or reply appears in a network request. Detailed scenario results
are in [the browser record](verification-browser-2026-10-07.json).

The independently decoded JSON oracle exercises mixed escape spellings and
arbitrary chunk boundaries. The existing detector smoke corpus also ran:
60 synthetic documents, 140 correctly detected entities, no misses or false
positives. That is a fixture check, not a real-world detection accuracy estimate.

Reproduce with the commands in [session integrity](session-integrity.md#checks)
and the project's CI workflow. The production site is `web/dist`, built with
`cd web && npm ci && npm run build`. The optional runtime still downloads from
the pinned Pyodide CDN on first use; offline first use is not supported.

Screenshots were opened and inspected. The existing typography and palette are
preserved, the three-column vault fits at 320px, and hidden originals read as
Hidden rather than blurred private text:

- [320px light](assets/session-mobile-2026-10-07.png)
- [1280px dark](assets/session-desktop-2026-10-07.png)
