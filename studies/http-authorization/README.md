# Explicit authorization headers cannot depend on entropy

At baseline `84567c2`, a native HTTPX request using username `user` and password
`pass` produced `Authorization: Basic dXNlcjpwYXNz`. Veil sent that entire
credential unchanged in the prompt. Base64 decoding recovers the username and
password without a key. Longer values sometimes became several partial secrets
or left padding visible. An opaque Bearer token could also pass through because
it was short, hexadecimal or word-shaped.

The corrected source recognizes the explicit header and masks its complete
token as one `SECRET`, preserving the field name and authentication scheme.
It also preserves the key's context when traversing structured tool input or
JSON-string function arguments. Otherwise the separately visited string
`"Bearer abc"` loses the `Authorization` key that identifies its purpose.

```text
Authorization: Basic dXNlcjpwYXNz
                  |
                  v
Authorization: Basic <one reversible SECRET>
```

| Controlled workflow | Baseline | Corrected source |
| --- | ---: | ---: |
| Complete credential masking | 1/14 | 14/14 |
| Actual SDK text requests with every credential wholly masked | 0/12 | 12/12 |
| Actual SDK tool-history requests with both headers wholly masked | 0/12 | 12/12 |
| CLI vault and exact restoration | 14/14 | 14/14 |
| Streaming restoration at four chunk sizes | 56/56 | 56/56 |

[Before](results/before.json) and [after](results/after.json) retain complete
masked text, actual SDK request bodies, native-producer versions and runtime
source hashes. Every credential and identity in these captures is synthetic.
HTTPX and the model SDKs use mock transports; no request went to a real service.
These counts are controlled examples, not a production detection rate.

## Native producer and independent checks

Seven cases were captured from **HTTPX BasicAuth**: short credentials, an empty
username, an empty password, a password containing a colon, a longer phrase,
Unicode and a username shaped like an email address. Independent stdlib Base64
decoding checks each actual HTTP header against its original UTF-8 user/password
pair. [`cases.json`](cases.json) retains those exact bytes and seven constructed
Bearer/proxy/JSON/curl/case controls. The `--native` replay generates the native
cases again and requires equality with the retained fixtures.

The encoding follows [RFC 7617 section 2](https://www.rfc-editor.org/rfc/rfc7617.html#section-2).
Bearer syntax follows [RFC 6750 section 2.1](https://www.rfc-editor.org/rfc/rfc6750.html#section-2.1).
Neither case requires testing whether the credential authenticates successfully.

The actual SDK replay covers Chat Completions, Responses and Anthropic, each
sync/async and buffered/streaming. The text capture carries all 14 examples in
one request, checking repeated values reuse their surrogate. The separate tool
capture carries nested authorization fields, an escaped key name and an
unrelated `"Bearer xyz"` string. Chat/Responses retain the original argument
syntax, including duplicate fields, a uint64-sized integer and a decimal's
spelling. Anthropic has an already structured input and checks decoded values
and caller-input immutability instead. Echoed replies restore the originals.
The streaming shapes are documented in the
[official OpenAI streaming guide](https://developers.openai.com/api/docs/guides/streaming-responses).

```sh
uv run python studies/http-authorization/replay.py --native --sdk --require-fixed --output /tmp/http-auth.json
uv run pytest tests/test_http_authorization.py tests/test_sdk_http_authorization.py
```

A bare installed wheel can replay the retained core/CLI cases without optional
packages by omitting `--native` and `--sdk`. To reproduce the baseline, archive
`84567c2`, set `PYTHONPATH` to that archive's `src/`, and run the current driver
without `--require-fixed`. The driver still checks restoration; restoration
alone did not mean that the credential was protected.

## Scope and collateral behavior

The contextual rule accepts nonempty token68-shaped values after Basic or
Bearer in exactly `Authorization` or `Proxy-Authorization`, ignoring ASCII
case. It retains `-._~+/` and trailing `=` as credential characters. Basic's
payload is deliberately opaque; a malformed or dummy credential can still be
private. Tokens are not decoded, authenticated, checked for expiry or sent to
an external service. The enclosing value wins over detected fragments inside it.

An explicit field is required: ordinary prose and bare `Bearer abc` remain
outside this new rule. Other auth schemes, environment-variable conventions,
header arrays and nested non-string header values are not added here. The
existing detectors continue to inspect their text independently. The header
name applies only to its immediate string value, never to a descendant. A
glued unsupported suffix does not become a shorter contextual token. Horizontal
spacing cannot bridge an empty field to the next log line. Token punctuation
such as a final dot is not trimmed; exact restoration retains it.

Literal surrogate reservations and transaction rollback apply to the new
contextual path. Actual SDK collision checks confirm no HTTP request is made
when a later literal conflicts, and the vault returns to its prior contents.
No runtime dependency was added.

The retained public technical corpus contains **1,483 files, 32,925,796 bytes and
2,616,034 words**. Resolved detections rose from 10,372 to 10,380. Every change
was reviewed: eight explicit authorization examples in five Requests, Fastify
and Axios test/documentation files. The other 1,478 files have identical type,
span, value, detector and confidence hashes. These public examples are dummy
values; this is a collateral-behavior check, not evidence of real leaked keys.
[Before](results/corpus-before.json), [after](results/corpus-after.json) and
[review](results/corpus-review.json) retain source hashes and exact locations.

`scaling.py` measures 10,000, 100,000 and 1,000,000-character size parameters
for long opaque credentials, ordinary prose, repeated headers, empty fields
and glued unsupported suffixes. Each case has one warmup and three measured
repeats. [Before](results/scaling-before.json) and [after](results/scaling-after.json)
retain actual byte counts, hashes and timings. These are controlled local
measurements, not a worst-case latency guarantee.

## Offline browser

```sh
cd web && npm ci && npm run lint && npm run build
cd ..
node studies/email-boundaries/check-browser.mjs web/dist studies/http-authorization/results/browser studies/http-authorization/browser-cases.json
```

The actual bundled Python/Pyodide passes eight credential/control cases in
Chromium and Firefox at 375 and 1280 pixels. Each fresh context initializes the
runtime on neutral text, disconnects, then performs its first credential masking,
masked/vault downloads and exact restoration without further requests.
[The receipt](results/browser/receipt.json) hashes downloaded artifacts and
served build assets. All four screenshots were inspected, including
[mobile Chromium](results/browser/chromium-375.png) and
[desktop Firefox](results/browser/firefox-1280.png): no horizontal overflow or
page errors occurred. The canned reply does not exercise auth restoration;
the real SDK echo/stream capture does.

## Clean package verification

A clean archive of `75a7f44` was installed on Python 3.14.7 with locked
development and spaCy dependencies. Ruff, formatting, mypy, **1,168 tests without
skips**, sdist and wheel builds passed. The
[command receipt](results/clean-checks.json) links the retained command logs;
machine paths are replaced with placeholders. Its 14-case/24-request replay
matches the working-source replay exactly. The working checkout also passed
all 1,168 tests on Python 3.12.12.

The built wheel was installed separately in three new environments:

| Installation | Python | OpenAI / Anthropic SDK | Result |
| --- | --- | --- | --- |
| Current SDKs | 3.14.7 | 3.31.0 / 1.14.0 | 14 cases, 24 SDK requests |
| Supported SDK floors | 3.10.21 | 1.66.0 / 0.40.0 | 14 cases, 24 SDK requests |
| Core only | 3.12.12 | Neither installed | 14 core/CLI cases |

The [artifact receipt](results/verification.json) verifies all **37 runtime
files**, including the typing marker, byte for byte across the clean source,
sdist, wheel and each installation. The bare core installation has no HTTPX,
OpenAI, Anthropic or cryptography package. Retained installed replays are
[current](results/installed-current.json), [floor](results/installed-floor.json)
and [core](results/installed-core.json).

A separate `npm ci`, typecheck and production build passed all 16 existing
browser scenarios. The new offline auth checks above were repeated on this
clean build; its Python manifest matches all 36 Python runtime files. The
[existing eight JWT browser cases](results/jwt-browser/receipt.json) also pass
in all four engine/width combinations after the shared study harness change.
All eight new screenshots were inspected. The build command is
`cd web && npm run build`, with output in `web/dist/`; the artifact receipt
retains sizes and hashes for all 27 build files.

## Public source

Source/evidence revision `9f309dc3fb4ceb51a5adfdac5696f2644e98cb55` was pushed
to `main`. The [public-source receipt](results/public-source.json) verifies
all 61 changed files against pinned GitHub raw URLs, with byte counts and
SHA-256 hashes. The remote branch matched the clean local source at capture.

No package release or manual hosted deployment is included.
