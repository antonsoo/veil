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
- HAR arrays of `{name, value}` records and arbitrary cookie-jar object trees
  do not supply immediate header-key context. Extract the actual header value
  and pass `field_name="Cookie"` when that schema is known to the caller.
- This conservative policy also masks non-authentication preferences and
  Set-Cookie metadata. It does not validate cookies, identify which member
  authorizes access, or provide complete DLP coverage.

The source suite passes 1,645 checks, Ruff and strict mypy. Package and public
demo verification are recorded separately when available; package metadata
0.4.4 is unchanged and does not identify a PyPI release of this correction.
