# Keep credential names with HAR values and form bodies

A browser/proxy HAR can mask a credential in its URL or encoded POST body and
still expose the same value in `queryString[].value` or `postData.params[].value`.
Short API keys in header name/value records also lost their field context.
Multipart bodies introduce another copy: their field names and values live on
different physical lines, outside the ordinary assignment recognizer.

The correction shares the existing explicit credential-name policy across HAR
headers, query records and form parameters. A credential-bearing URL or
serialized form body stays opaque. Individual parameter records retain their
names and protect their values. Ordinary parameter records remain readable.
This preserves privacy across the redundant representations without trying to
edit MIME payloads or signed/encoded URLs in place.

## Real HTTP and native producers

[`capture.mjs`](capture.mjs) makes actual Chromium/Firefox requests through
mitmproxy 12.2.3 to a loopback server. Each browser sends an API-key header,
query credentials, a URL-encoded POST and a multipart POST. The server accepts
all eight requests after comparing the received fields with authored controls.
These are deliberately short synthetic credentials, never real accounts.

Both Playwright HAR recording and mitmproxy's native `hardump` exporter retain
their original files. The [oracle](fixtures/oracle.json) pins file hashes,
browser/producer versions, acceptance outcomes and 34 sensitive JSON paths.
Playwright retains the form text with empty `params`; mitmproxy additionally
produces the URL-encoded parameter records. This distinction is part of the
reproduction rather than being filled in by a fixture editor.

The native formats follow [Playwright's HAR recording](https://playwright.dev/docs/api/class-browser#browser-new-context-option-record-har)
and [mitmproxy's HAR exporter](https://github.com/mitmproxy/mitmproxy/blob/v12.2.3/mitmproxy/addons/savehar.py).
No HTTP response body echoes the controls. No model/provider is contacted by
HTTP capture. Proxy configuration and generated local certificate material
stay outside the retained fixture directory.

```text
browser HTTP -> loopback proxy -> accepting local server
    |                 |
    v                 v
Playwright HAR   mitmproxy HAR
    |                 |
    +---- names and serialized form bodies ----+
                                              v
                                  shared field context
                                              |
                         raw JSON / arguments / typed trees
```

## Reproduced change

Baseline source is `35a8264d6e29944384dda27af6a5d165b788dcf1`.

| Native file | Credential-bearing fields/containers | Exposed before | Exposed after |
| --- | ---: | ---: | ---: |
| Chromium | 7 | 5 | 0 |
| Firefox | 7 | 5 | 0 |
| mitmproxy, both browsers | 20 | 16 | 0 |

The exposure oracle checks actual retained values, complete MIME value lines
and decoded form/query values. It avoids counting incidental letters such as
`cat` inside `application`. The encoded POST body could already protect its
values while its parameter records remained exposed. The changed policy makes
credential-bearing serialized containers fully opaque too.

[`replay.py`](replay.py) checks native hashes and exercises raw text, decoded
JSON arguments and typed trees: nine direct workflows. It also invokes the
real Anthropic Messages, OpenAI Chat Completions and Responses SDK serializers
over MockTransport: three files, sync/async, buffered/one-character streamed
tool replies, 36 workflows. The baseline fails all nine direct and 36 SDK
privacy checks. The corrected source has zero failures. Caller data remains
unchanged. Raw/argument text and actual CLI mask/vault/restore operations retain
the complete original source; typed SDK replies retain the original data.

SDK replies are authored echo controls. They establish actual local SDK
serialization and restoration, not provider acceptance or model behavior.
Echoes use JSON tool channels so restored quotes and MIME line breaks remain
valid JSON. Ordinary assistant text retains literal restoration; applications
returning serialized JSON as text must use JSON restoration explicitly.

## Scope and refusal behavior

Context applies inside a declared HAR 1.2 request/response structure. Supported
credential names use the existing password, API-key, client-secret and OAuth
token rules. Bare `token`, unrelated name/value records and form fields named
`Cookie` or `Authorization` do not become HTTP headers.

The standard MIME parser reads field names without rewriting the body. It has
a 10,000-message allocation/inspection budget; URL-encoded forms and queries
have a 10,000-field budget. Missing or incomplete multipart framing, ambiguous
MIME headers and duplicate routing fields refuse before vault changes. This
is a bounded supported-format recognizer, not general HAR or MIME validation.

Whole-container masking also hides benign fields inside that serialized URL
or form. Separate public query/parameter records stay inspectable. JSON
numeric spelling, unrelated duplicate fields and untouched escapes keep the
existing preservation contract. Explicitly disabling field detection keeps
its previous scope.

## Reproduction

```sh
# Install mitmproxy==12.2.3 separately for optional fresh HTTP capture.
node studies/har-parameters/capture.mjs /tmp/har-parameters /path/to/mitmdump
uv run python studies/har-parameters/replay.py --src src --out /tmp/har-after --sdk
uv run python studies/har-parameters/replay.py --src /path/to/baseline/src --out /tmp/har-before --observe-only --sdk
```

The retained fixtures let replay run without a proxy or any network. SDK
extras are needed only for `--sdk`. A fresh capture is a separate native input;
copy its complete fixture directory when deliberately refreshing this study.

The [browser program](browser.mjs) uses the actual Python worker, three native
HARs, and complete masked/vault downloads after disconnecting. It compares
every masked download with the CLI, restores the exact source from the actual
downloaded vault, and checks the supported credential paths. The 20,000-unit
preview remains bounded while the full mitmproxy HAR stays in the download.
The canned reply is not used as restoration evidence.

```sh
node studies/har-parameters/browser.mjs URL /tmp/har-browser /tmp/har-after after
```

Source, installed package and public delivery are separate claims. This study
does not create a PyPI release or tag.

## Clean artifact and delivery evidence

Core source `d03e14b4b764e5809f3f84667e58bc842c2e98f0` was verified from a
fresh Git archive: lint, formatting, types, 1,712 unit checks (one optional
spaCy module skipped), and all 16 existing browser scenarios passed. The
[artifact receipt](results/artifacts.json) matches all 40 runtime files across
wheel, sdist and two installed environments, and all 39 Python modules in the
browser manifest. Python 3.10 with Anthropic 0.40.0/OpenAI 1.66.0 and Python
3.14 with Anthropic 1.15.0/OpenAI 3.35.1 each replay nine direct and 36 actual
SDK tool workflows with zero failures. Provider responses are authored locally.

Pages commit `2bd509a` deployed this HAR correction. All 27 canonical served
files match the [captured build inventory](results/hosted-bytes.json). Browser
behavior and the subsequent ordinary-URL alias update are verified separately.
The later URL detector revision does not change this historical artifact.

[`transaction_views.py`](transaction_views.py) derives 16 complete, compact
single-entry HAR views for a workbench's 12,000-character source limit. It
preserves every selected JSON value and records parent hashes and entry
indices. These are derived transactions, not producer-byte-identical files or
16 independent HTTP requests: the eight actual requests were observed by two
producers. The original three HAR files remain the native-input evidence.

The combined URL/HAR engine is subsequently served at Pages `4011db5`.
[Public browser replay](results/public-after/browser.json) opens all three
native files in Chromium and Firefox at desktop and 375 pixels: 12 imports
and 24 actual masked/vault downloads. Every masked byte matches the final
CLI, all 34 credential-bearing fields/containers are opaque, and each vault
restores the complete source. It runs offline after bootstrap with no page
errors or subsequent requests. The complete 53 KB proxy file remains in the
download even when its preview is bounded. All eight retained viewport/vault
screenshots were inspected. This does not create a package-registry release.
