# A masked HTTP log must not retain its session cookie

The baseline `6d2ab6a` leaves explicit `Cookie` and `Set-Cookie` fields intact.
Short tokens lack entropy; hex-only session IDs resemble hashes and deliberately
do not qualify for the generic entropy heuristic. A cookie's header context
supplies information that its name or character distribution cannot.

The retained [native capture](fixtures/oracle.json) uses the Python standard
library's HTTP server and `CookieJar`. The server issues a fresh random 128-bit
hex session and a theme preference. The jar consumes both `Set-Cookie` fields,
then automatically sends the combined `Cookie` header to retrieve a local
private document. Header-object serialization is retained, not a packet capture.
All values are synthetic; that server is closed after capture.

| Retained native input | Baseline session visible | Corrected session visible | Exact and one-character restoration |
| --- | --- | --- | --- |
| Request header text | Yes | No | Exact |
| Response header text, two Set-Cookie fields | Yes | No | Exact |
| Request header mapping as JSON | Yes | No | Exact |

A separate loopback server deliberately recognizes the retained synthetic
session. It returns 200 for the original and restored header. The baseline's
"masked" header also returns 200; the correction's masked header returns 401.
That rejection control sends surrogate UTF-8 bytes explicitly; it does not
claim placeholders are usable HTTP credentials. Veil masks data for an LLM.
The decisive privacy check is that the original session is absent from the
masked prompt. The local vault still contains it for restoration.

[Before](results/before.json) and [after](results/after.json) retain all three
native forms, exact CLI mask/restore agreement, loopback outcomes and 24 actual
SDK paths. Chat Completions, Responses and Anthropic Messages each run in sync
and async modes, buffered and one-character streaming, with text and tool
replies. The SDKs serialize through mock transports; no provider, model or real
account is used. All 24 outgoing requests expose the cookie before and protect
it after, with exact restored values.

The [RFC's cookie format](https://www.rfc-editor.org/rfc/rfc6265#section-4.1)
allows multiple cookie members and expiry dates containing commas. The masker
therefore keeps the complete explicit header value together, including cookie
names, preferences and attributes. Each physical `Set-Cookie` field receives
its own secret. Header labels, enclosing quotes and line breaks remain intact.
Nested passwords, card-like values or other PII cannot displace their enclosing
secret and expose the remaining header members.

```sh
uv sync --locked
uv run --locked python studies/http-cookies/replay.py --src src --out /tmp/cookies.json --sdk
```

Use `--src BASELINE/src --observe-only` to retain old failures. Omit `--src`
when checking a separate installed environment. Capture a new native exchange
in a new directory with `capture.py --out DIRECTORY`; ports, dates and sessions
vary, and the retained native capture is not a deterministic byte fixture.

Recognition is deliberately bounded:

- Explicit raw header lines, quoted JSON/dict header values and quoted curl
  header arguments are covered. No arbitrary bare `sid` or `session` guess is
  added. A complete immediate decoded `Cookie`/`Set-Cookie` string field uses
  the existing field-context API without synthesizing source text.
- Quoted source escapes remain source spelling; decoded tool data retains its
  original value. Existing JSON argument handling supports escaped header keys.
- Unquoted raw values end at the physical line. Obsolete folded headers,
  shell concatenation and multi-layer serialized strings are outside this
  grammar. A missing closing quote stops at its first line.
- At the original capture, HAR arrays of `{name, value}` records did not supply
  immediate header-key context. The subsequent [HAR 1.2 correction](../har-headers/README.md)
  recognizes qualified header/cookie records. Arbitrary record trees outside
  that declared format still require the caller's explicit field context.
- This conservative policy also masks non-authentication preferences and
  Set-Cookie metadata. It does not validate cookies, identify which member
  authorizes access, or provide complete DLP coverage.

The source suite passes 1,645 checks, Ruff and strict mypy. Package and public
demo verification are recorded separately when available; package metadata
0.4.4 is unchanged and does not identify a PyPI release of this correction.

## Clean package and browser verification

The clean archive `389052b` passes Ruff, format, strict mypy and the full
coverage command: 1,642 passed and one explicit optional spaCy skip. The original
development environment also runs that backend and passes 1,645 checks.
The clean web install passes types, production build and all 16 existing browser
scenarios.

The [artifact receipt](results/artifacts.json) checks all 38 Python modules
against the wheel, sdist and two separate non-editable wheel installations.
Both [Python 3.14.7 with current SDKs](results/installed-current.json) and
[Python 3.10.21 with OpenAI 1.66.0 / Anthropic 0.40.0](results/installed-minimum.json)
repeat the native forms, CLI round trips, controlled authentication outcome and
all 24 SDK paths without failures. The minimum environment also passes 207
relevant HTTP, credential-field and private-key checks.

The [real browser receipt](results/browser.json) records four prompts and eight
actual downloads in each Chromium/Firefox desktop/375px context. It executes
the real Python worker, disconnects after bootstrap, then checks exact masked
prompt bytes, complete vault originals and explicit local restoration from
those downloads. Its canned simulated reply does not echo cookie data, so no
UI feature is invented for that check. No request is made by the subsequent
prompts or downloads. Firefox's later accessibility diagnostic attempts one
local font GET; it contains no prompt data and is recorded separately.

[Desktop screenshot](../../docs/assets/http-cookies/chromium-1280.png) and
[phone screenshot](../../docs/assets/http-cookies/firefox-375.png) were opened
and inspected, along with the other two engine/width combinations. All four
accessibility audits pass without horizontal page overflow. These local checks
do not alone establish a hosted deployment or PyPI release.

## Public delivery

Source `389052b` and verification `cffb96e` were pushed to main. Deployment
`f73cd67` updates only the served Python manifest; all existing static assets
remain available. The [canonical byte receipt](results/hosted-bytes.json)
checks the complete clean web build, and the [public browser replay](results/hosted-browser.json)
repeats all four cookie prompts and eight actual downloads in each engine/width
context against `https://antonsoo.github.io/veil/`. The corrected Python runs
in the actual worker, with no subsequent prompt/download requests and no
accessibility violations or page overflow. Initial runtime downloads and the
separate audit font attempt remain explicitly recorded.

The source, local package and public demo are verified separately. No PyPI
release, provider call or production account session is included.
