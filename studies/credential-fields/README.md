# Labelled credentials that entropy cannot recognize

At baseline `151b86a`, a support paste containing `{"password":"river stone"}`,
`API_KEY=small-key` or `x-api-key: header-token` reached the model unchanged.
The values lack both a provider prefix and the randomness/length required by
the generic secret heuristic. A tool history lost the same context when its
string values were inspected separately from their keys.

The new rule uses the explicit label to select a complete value as a reversible
`SECRET`. It preserves keys, quotes, delimiters and surrounding diagnostic text.
All credentials in this study are synthetic; no provider/account was contacted.

```text
{"password":"river stone","status":"denied"}
                      |
                      v
{"password":"<one SECRET>","status":"denied"}
```

| Controlled workflow | Baseline | Corrected source |
| --- | ---: | ---: |
| Supported raw credentials masked completely | 0/25 | 25/25 |
| Syntax/prose controls unchanged | 20/20 | 20/20 |
| Actual SDK text requests with expected masking | 0/12 | 12/12 |
| Actual SDK tool-history requests with expected masking | 0/12 | 12/12 |
| CLI vault and exact restoration | 45/45 | 45/45 |
| Incremental restoration at four chunk sizes | 180/180 | 180/180 |

[Before](results/before.json) and [after](results/after.json) retain actual
masked text, vault originals, request bodies, SDK versions and runtime hashes.
Restoration passed before the correction too; that alone did not establish
that the outgoing prompt protected a credential. These are bounded examples,
not production recall or precision estimates.

## Recognition boundary

Supported labels ignore ASCII case: `password`, `passwd`, `api_key`,
`client_secret`, `access_token`, `refresh_token` and `x-api-key`. The middle four
also accept a hyphen or no separator, including camelCase spelling. Uppercase
environment identifiers can prefix the underscore forms, as in
`DATABASE_PASSWORD` or `SERVICE_API_KEY`. Arbitrary lowercase prefixes and bare
`secret`, `token` and `pwd` do not gain this contextual rule.

Raw recognition requires `:` or `=`, with horizontal spacing. Nonempty single
or double quoted values can contain spaces, Unicode and backslash escapes;
their exact source spelling goes into the vault. Unquoted values stop at
whitespace or structural punctuation. A comment or shell-reference marker at
the start, obvious function-call/escaped expressions, `:=`, `==`, empty fields,
unquoted null/boolean/type markers, arrays and objects are not string
credentials. Matching does not begin inside URL paths or query parameters;
the existing URL detector retains that responsibility. A private-key block
cannot be displaced by a credential label inside it.

This is a bounded text recognizer, not a shell, Python, YAML, dotenv or JSON
parser. It does not interpret arbitrary expressions, interpolation, multiline
raw quoted values or escaped raw key names. A partially pasted/malformed value
can be missed. Punctuation within a supported value is not authenticated or
trimmed as though the detector knew the intended password.

Decoded JSON tool values retain their immediate key. The optional
`Masker.mask(value, field_name="password")` and `find_entities` hint uses the
same mechanism. A supporting `FieldDetector` supplies candidates whose spans
refer directly to the decoded string; no fabricated escaping enters its vault.
The default secret detector masks the whole nonempty decoded string, including
quotes, newlines or a value shaped like another entity. Other configured
detectors still run, and disabling secret detection disables this rule.
Context does not propagate through arrays/objects or rewrite unlabelled copies
of a short value elsewhere. Non-string tool values keep their types.

## Actual request and restoration workflows

[`fixtures.py`](fixtures.py) generates the retained cases, including stdlib
`json.dumps` and `ConfigParser.write` output. Replay requires regeneration to
match [the retained fixtures](cases.json), then checks the public `Masker`,
CLI/vault and incremental `Restorer` at chunk sizes 1, 2, 7 and 31.

Actual OpenAI Chat Completions, Responses and Anthropic SDKs serialize requests
over mock HTTP transports, each sync/async and buffered/streaming. The text
workflow carries a support paste. The tool workflow includes an escaped key,
quoted/newline values, duplicate fields, a uint64-sized integer, decimal
spelling, literal surrogate reservations and arrays/objects that must not
inherit their parent's label. Returned tool arguments exercise JSON-aware
restoration, including one-character chunks. Chat/Responses retain raw argument
syntax; Anthropic checks already decoded values. Caller inputs stay unchanged.

Later cross-message surrogate collisions reject before transport and undo
vault changes. The new contextual path uses the existing reservation and
exact/tolerant restoration checks. No runtime dependency was added.

```sh
uv run python studies/credential-fields/replay.py --sdk --require-fixed --output /tmp/credential-fields.json
uv run pytest tests/test_credential_fields.py tests/test_sdk_credential_fields.py
```

To replay baseline source, archive `151b86a` and set `PYTHONPATH` to its `src/`
when running the current driver without `--require-fixed`. A dependency-free
installed wheel can replay core/CLI cases by omitting `--sdk`.

## Collateral behavior and cost

Both runs hash-checked all 1,483 retained technical files: 32,925,796 bytes and
2,616,034 whitespace-separated words. Resolved detections rose from 10,380 to
10,407. Every earlier detection retains its exact type, span, value, provenance
and confidence. The other 1,467 files have identical complete detection hashes.

All 27 additions in 16 files were read and classified: 20 explicit dummy
credential literals in Requests/Flask/Express/Gin/Fastify/Axios examples and
tests; **seven source-variable references are collateral false positives**.
For example, `password=password` is ambiguous between a source variable and
a weak unquoted credential. The recognizer cannot infer the language/runtime
from that spelling. These counts do not establish live leaked credentials or
a general false-positive rate. [Before](results/corpus-before.json),
[after](results/corpus-after.json) and [complete review](results/corpus-review.json)
retain pinned source URLs, file hashes and exact locations without republishing
credential-like text. [`review-corpus.py`](review-corpus.py) verifies no earlier
detection was removed or changed and requires every new location to have a
recorded manual classification.

[`scaling.py`](scaling.py) measures quoted/bare values, escaped quotes,
unterminated strings, repeated/missing assignments, uppercase identifiers and
ordinary prose at 10,000, 100,000 and 1,000,000-character size parameters.
[Before](results/scaling-before.json) and [after](results/scaling-after.json)
retain exact bytes, input hashes, one warmup and three measured repeats. The
maximum detector median in these local runs rose from 0.215 to 0.650 seconds.
This adds recognition work; it is not a speedup or a worst-case latency claim.
Machine: 14 vCPU WSL2 Linux, 48 GB RAM; Python 3.12.12.

## Offline browser

The actual baseline Python/Pyodide build leaves all eight supported credential
examples visible. Four syntax/prose controls also remain unchanged. Each fresh
Chromium/Firefox context at 375/1280 pixels initializes on neutral text,
disconnects, then masks and downloads the complete prompt and vault with no
additional requests. [Baseline receipt](results/browser-before/receipt.json)
and four inspected screenshots retain that behavior, including
[mobile Chromium](results/browser-before/chromium-375.png).

The [corrected clean build](results/browser-after/receipt.json) masks all eight
credentials and retains all four controls in every engine/width combination.
Complete masked/vault downloads restore exactly; the first credential action
occurs after disconnection. No additional request, page error or horizontal
overflow occurred. All eight before/after screenshots were inspected, including
[corrected mobile Chromium](results/browser-after/chromium-375.png). The canned
reply does not reference these secrets; actual SDK tool/text echoes above
exercise their restoration.

```sh
cd web && npm ci && npm run lint && npm run build
cd ..
node studies/email-boundaries/check-browser.mjs web/dist /tmp/credential-browser studies/credential-fields/browser-cases.json
```

## Clean packages

A fresh archive of `56a2cd2` passed locked Python 3.14.7 installation with the
development and spaCy dependencies, Ruff, formatting, mypy, **1,264 tests with
no skips**, wheel/sdist builds, `npm ci`, web typechecking/build and all 16
existing browser scenarios. The [command receipt](results/clean-checks.json)
retains commands, exit codes and log hashes. No app UI was changed.

Separate wheel installations replayed the public API, real CLI/vault and actual
SDKs. Every case, request body and restored value equals the working-source
replay, including different SDK generations:

| Installation | Python | OpenAI / Anthropic | Replay |
| --- | --- | --- | --- |
| Locked clean source | 3.14.7 | 3.23.0 / 1.11.0 | 45 cases + 24 SDK requests |
| Current SDK wheel | 3.14.7 | 3.31.0 / 1.15.0 | 45 cases + 24 SDK requests |
| Supported SDK floors | 3.10.21 | 1.66.0 / 0.40.0 | 45 cases + 24 SDK requests |
| Core-only wheel | 3.12.12 | Neither installed | 45 core/CLI cases |

Cryptography's declared floor, 50.0.0, is installed in the floor environment;
the core-only environment contains only `veil-pii`. [Artifact verification](results/verification.json)
compares all **38 runtime files** across source, sdist, wheel and installations.
The browser manifest matches all 37 Python modules, and the receipt hashes all
27 static build files. The build command is `cd web && npm run build`; output
is `web/dist/`. Retained installed replays accompany the receipt.

The source addition is not a package release or a verified hosted deployment.

## Public source

Revision `7dc606053d3de4a63d1f7e6a82960164a24fa4fe` was pushed to `main`.
The [public-source receipt](results/public-source.json) compares every one of
the 61 changed files to its immutable GitHub raw URL, with exact bytes, sizes
and SHA-256 hashes. Remote `main` matched the clean local revision before and
after capture. This establishes source publication, not a registry release or
hosted-demo update.
