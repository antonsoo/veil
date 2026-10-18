# Authorization credentials in native HAR records

Baseline `bed8288` leaves both of these header values readable in a native HAR:

```json
{"name":"Authorization","value":"Bearer local-session-42"}
{"name":"Authorization","value":"Basic bG9jYWw6cGFzcw=="}
```

These are synthetic credentials. [`capture.mjs`](capture.mjs) starts a loopback
server that accepts exactly those values, then drives actual Chromium and
Firefox navigations. All four requests receive HTTP 200. Closing each browser
context writes its unmodified full Playwright HAR, with response bodies omitted.
The [capture oracle](fixtures/oracle.json) records the server observations,
browser versions, file hashes and credential-bearing source paths.

HAR's [header records](https://w3c.github.io/web-performance/specs/HAR/Overview.html)
separate the name and value. The existing cookie-specific context recognized
that representation, while Authorization kept only ordinary text detection.
Short credentials have no provider prefix or entropy signal to rescue them.

```text
authenticated browser request -> native HAR name/value record
                                           |
                             original header context
                                           |
                          Basic/Bearer credential span
                                           |
                             placeholder + local vault
```

| Observed workflow | Before: incorrect masking | After: incorrect masking |
| --- | ---: | ---: |
| Text, JSON arguments and typed trees, both native files | 6 / 6 | 0 / 6 |
| Real SDK serialization over mock transports | 48 / 48 | 0 / 48 |
| Browser masked downloads, two engines and two widths | 8 / 8 | 0 / 8 |

The corrected text output keeps `Bearer` / `Basic` and masks the credential.
It retains the existing [token grammar](https://www.rfc-editor.org/rfc/rfc6750#section-2.1)
and also handles Proxy-Authorization. Context applies only at recognized HAR
1.2 request/response header paths or explicit immediate JSON field names.
Unrelated `name`/`value` pairs and other schemes do not acquire this context.

Raw text maps decoded credential spans back to their original JSON spelling;
it does not rewrite the document. Auth schemes, escapes outside the selected
span, duplicate unrelated keys and numeric lexemes remain intact. The typed
SDK path shares structural context without a JSON serialization round trip.
Conflicting routing keys still refuse and roll back vault changes.

## Reproduce the before/after result

```sh
uv sync --locked
uv run --locked python studies/har-authorization/replay.py --src src --out /tmp/har-auth.json --sdk
uv run --locked veil mask studies/har-authorization/fixtures/chromium.har --vault /tmp/har-auth-vault.json
```

Use `--src BASELINE/src --observe-only` for the baseline. Omit `--src` in a
separate non-editable installation. Recapture with
`node studies/har-authorization/capture.mjs NEW_DIRECTORY`; native clocks,
ports and browser metadata will differ. The fixed synthetic credentials make
the authentication contract inspectable and are never valid on a remote service.

[`replay.py`](replay.py) derives expected output from the independent capture
paths, without importing the detector or tokenizer. It checks CLI mask/restore,
exact and tolerant library restoration, one-character streaming restoration,
decoded arguments and caller-owned typed data. The CLI's existing final newline
is allowed explicitly. SDK coverage includes Chat Completions, Responses and
Anthropic Messages, sync/async, buffered/streamed and text/tool replies. Their
real serializers use mock HTTP transports; no provider request is made.

The [before](results/before.json) and [after](results/after.json) receipts retain
the actual masked documents, local vaults, runtime hashes and every SDK outcome.
Separate wheel installs repeat the replay on
[Python 3.14 with current SDKs](results/installed-current.json) and
[Python 3.10 with minimum supported SDKs](results/installed-floor.json).

[`browser.mjs`](browser.mjs) checks the actual Pyodide worker in Chromium and
Firefox at 1280 and 375 pixels. Both native files are pasted and their complete
masked-text and vault downloads inspected. Each downloaded vault reconstructs
the exact original HAR in an explicit diagnostic. The canned reply does not
echo this data and is not a restoration oracle. Before/after browser receipts
are [retained](results/browser-after.json); all prompt/download work occurs
offline after bootstrap, with zero subsequent requests or page errors.
All four [screenshots](../../docs/assets/har-authorization/chromium-1280.png)
were opened and inspected: long HAR output wraps, controls remain accessible,
and neither phone layout has horizontal page overflow.

## Clean checkout and compatibility evidence

A fresh archive of implementation `89fd8d3` passes locked installation with
the optional spaCy backend, Ruff, format checks, strict mypy and the complete
coverage run: **1,695 passed**. Its clean web install passes type checks,
production build and all **16** existing browser scenarios. The additional
native HAR download replay above uses that same clean build. The host runs
WSL2 Linux; Python 3.12.12 and Node 26.7.0 were used for the clean checks.

```sh
uv sync --locked --extra spacy --python 3.12
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy
uv run --no-sync pytest --cov=veil --cov-report=term-missing
uv build
cd web && npm ci && npm run lint && npm run build && npm run test:browser
```

The [artifact receipt](results/artifacts.json) compares all 40 runtime files
against the clean wheel, sdist and two non-editable installations, plus all 39
Python modules in the browser source manifest. The installed environments point
to the checked wheel and repeat all six direct and 48 SDK cases without an
incorrect outcome. [`verify_artifacts.py`](verify_artifacts.py) retains those
checks; [clean-replay.json](results/clean-replay.json) retains the clean-source
workflow results.

The existing hash-checked public technical corpus contains 1,483 files and
32,925,796 bytes. Its complete output-and-vault ledger hash is identical
[before](results/corpus-before.json) and [after](results/corpus-after.json),
with no refusals or changed source on exact/tolerant restoration. The replay
uses `studies/surrogate-collisions/corpus.py --source SOURCE --label LABEL`.
This is a compatibility result, not a claim about detection accuracy or all
possible HAR files. Its cached sources and license information are described
in [the original corpus](../real-text/README.md).

## Limits and publication

This is an addition to existing credential detection, not a complete HAR
sanitizer. Other auth schemes, unsupported HAR versions, arbitrary bodies,
query fields and multiple serialization layers retain their existing coverage.
The synthetic local server proves the captured credentials were accepted by
that server; it does not authenticate external source data or real accounts.

The original correction and checks above were local; public delivery is recorded
separately below. No tag or registry publication is included. Package metadata
remains 0.4.4. The web build command is
`cd web && npm ci && npm run build`, producing `web/dist/`.

## Public delivery

Source `39489ed` contains the implementation and clean-install verification.
Deployment `5c162cf` updates only the Python source bundle and preserves earlier
hashed assets. The [canonical HTTP receipt](results/hosted-bytes.json) verifies
all 27 current build files against the exact public URL responses, without
query-string cache bypasses.

The [public browser replay](results/hosted-browser.json) repeats both native
HARs in Chromium and Firefox at desktop and phone widths. All eight actual
masked downloads contain no retained credentials; their downloaded vaults
reconstruct the exact source. All work after bootstrap occurs offline with
zero subsequent requests or page errors. This establishes those public
workflows, separately from the unchanged PyPI release.
