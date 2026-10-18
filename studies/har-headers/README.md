# Protect every cookie copy in a native HAR

The baseline `eb3242f` protects explicit cookie header strings but misses the
same credentials inside a native browser HAR. Header and cookie collections
store their names and values in separate JSON members. A short or hex-only
session remains readable in four places, even though masking reports success.

[`capture.mjs`](capture.mjs) runs actual Chromium and Firefox contexts with
[Playwright's full HAR recording](https://playwright.dev/docs/api/class-browser#browser-new-context-option-record-har).
A loopback server issues a fresh random 128-bit hex session. Each browser's
cookie jar sends it to retrieve a private document with HTTP 200. Closing the
context flushes the unmodified HAR; the local server is then closed. All
sessions are synthetic, response bodies are omitted and no remote site is used.
This is a native Playwright HAR, rather than a browser GUI sanitized export.

```text
loopback Set-Cookie -> browser cookie jar -> authenticated navigation
                                |
                                v
                              HAR 1.2
                                |
                                +-- response.headers[].value
                                +-- response.cookies[].value
                                +-- request.headers[].value
                                +-- request.cookies[].value
```

The [capture oracle](fixtures/oracle.json) independently records the jar,
actual request cookies, authentication status, exact HAR hashes and each
credential-bearing JSON path.

| Native file | Session copies before | Copies after text masking | Copies after SDK argument masking |
| --- | --- | --- | --- |
| Chromium HAR | 4 | 0 | 0 |
| Firefox HAR | 4 | 0 | 0 |

The masker now recognizes `log.version: "1.2"` and the declared entry,
request/response, header and cookie collections. Every cookie record's value,
including preferences, becomes a complete secret. Cookie/Set-Cookie header
values remain whole opaque fields. Names, other metadata and JSON structure
stay readable. Header/cookie records outside that declared structure do not
inherit context merely because their keys are named `name` and `value`.

## Text and typed SDK inputs need the same context

JSON argument strings retain original string-token positions and object pairs.
Only changed string values are re-encoded; numeric spelling, unsafe integer
tokens and unrelated duplicate members are preserved. Escaped keys and names
are interpreted once. No fabricated header prefix becomes source text.

Anthropic receives an already typed tool-input tree. It uses the same semantic
path discovery directly, without serializing the tree through JSON or rounding
large integers. Tuples retain the existing JSON-array policy. Structural paths
keep context local to the actual occurrence rather than to object identity.
The caller's data stays unchanged.

The expected output in [`replay.py`](replay.py) comes from an independent walk
of the native HAR schema and its cookie fields, not Veil's tokenizer or
detectors. [Before](results/before.json) disagrees on all four text/argument
forms and all 48 real SDK paths. [After](results/after.json) has no disagreement:
Chat Completions, Responses and Anthropic Messages; sync/async; buffered and
one-character streaming; text and tool replies; both native HARs. The SDKs use
their actual serialization over mock HTTP transports, with no provider call.

Text-library restoration reproduces each native HAR exactly, including its
missing final newline. The CLI retains its existing contract of appending a
final newline; mask/restore checks allow that one known formatting addition.
SDK checks restore the original data, with exact argument text for the two
string-argument APIs on these native files. Anthropic serializes typed data.

Ambiguous routing members, wrong record types and missing string names/values
refuse with `VaultError`. Six actual SDK boundary checks confirm no HTTP request,
unchanged caller input and request-vault rollback. Unrelated duplicate JSON
members remain supported. Model reply restoration does not require the reply
to conform to HAR.

## Keep source syntax intact

This work also corrects an overreach in the initial cookie recognizer: a quoted
Cookie key followed by an array or a TypeScript type could be consumed as a bare
header value. A JSON array could become invalid JSON. Context now stays on an
immediate string value, without propagating into collections.

The [public technical-corpus review](results/corpus-review.json) compares all
resolved detections on 1,483 hash-checked files, 32.9 MB and 2.6 million words.
Exactly 1,482 outcomes are identical. The one change removes a false secret
from [Axios's pinned type declaration](https://github.com/axios/axios/blob/v1.7.7/index.d.ts):
`"set-cookie": string[];` is preserved. No new detections or refusals appear.
The [complete masking/restoration replay](results/corpus-after.json) agrees
with that review and restores every file exactly and tolerantly. This does
not establish detection accuracy for the remaining findings.

```sh
uv sync --locked
uv run --locked python studies/har-headers/replay.py --src src --out /tmp/har-after.json --sdk
uv run --locked veil mask studies/har-headers/fixtures/chromium.har --vault /tmp/har-vault.json > /tmp/masked.har
```

Use `--src BASELINE/src --observe-only` to capture the old behavior. Omit
`--src` in a separate installed environment. Recapture into a new directory
with `node studies/har-headers/capture.mjs DIRECTORY`; sessions, clocks, ports
and native browser metadata vary.

## Boundaries

- Complete JSON HAR 1.2 objects are recognized, including nested tool inputs.
  This is cookie-field protection, not a complete HAR sanitizer. Other headers,
  query parameters, bodies and custom extensions retain ordinary detector rules.
- Truncated/malformed JSON, prose-wrapped HARs, unsupported versions and multiple
  serialization layers do not establish this schema context. Arbitrary header
  record lists outside HAR still need explicit caller-supplied field context.
- Cookie names do not establish which value authorizes a session. Preferences
  and cookie metadata inside opaque header values are conservatively protected.
- Default placeholders and detectors are checked here. Name recognition,
  source authenticity, real production sessions and complete DLP are not inferred.
- Source and local verification do not alone identify an installed PyPI release
  or hosted deployment. Package metadata remains 0.4.4; publication checks follow
  separately.

## Avoid repeated scans of a large source

A scaling control repeats retained native entries and optionally adds one
literal placeholder example. Profiling the 1 MB case found 1,756 availability
checks, repeatedly searching the same reserved source. Source absence is now
cached for each surrogate and invalidated whenever new normalized source text
is reserved. Private-original checks still run on every lookup, and later
source collisions still reject the whole request. Duplicate normalized
reservations keep their original per-input restoration checks.

The [complete three-sample comparison](results/performance-comparison.json)
retains all six cases, including smaller cases that vary in either direction.
For the 4.2 MB / 2,000-entry control with a literal example, median masking time
changes from 15.59 s to 6.27 s. Without the literal, the same-size control is
5.33 s before and 6.78 s after in this run. These wall-clock measurements share
a host with other work; they are not an isolated throughput or universal
speed claim. Every output/vault hash and exact/tolerant restoration agrees.
The [baseline](results/performance-before.json), [corrected samples](results/performance-after.json)
and [`benchmark.py`](benchmark.py) preserve the method and boundaries. Native
SDK outcomes also remain byte-for-byte identical after caching.

A [focused alternating follow-up](results/performance-paired.json) repeats
the 4.2 MB control without a literal in before/after/after/before order, two
samples per process. Median wall time is 5.58 s before and 5.63 s after;
process CPU time is 5.58 s and 5.62 s. All source, output and vault hashes agree.
This reduces the uncertainty from the first single-order sequence. Use
`benchmark.py --entries 2000 --literal no --repeat 2` for that focused case.
The original six-case driver and samples are retained at `253639c`.

## Clean installed and browser checks

A fresh archive of `253639c` passes locked installation, Ruff, format, strict
mypy and the complete coverage command: 1,675 passed and one explicit optional
spaCy skip. The development environment runs that optional backend too and
passes all 1,678 checks. The clean Node 24.21.0 web install passes types, build
and all sixteen existing browser scenarios.

The [artifact receipt](results/artifacts.json) checks all 39 Python modules
against the wheel, sdist and two separate non-editable installations. Both
[Python 3.14.7 with current SDKs](results/installed-current.json) and
[Python 3.10.21 with OpenAI 1.66.0 / Anthropic 0.40.0](results/installed-minimum.json)
repeat all four native forms and 48 SDK paths without an incorrect outcome.
The minimum environment also passes 92 focused cookie, HAR, collision and
SDK-boundary checks.

The [canonical pre-change Python](results/hosted-before-source.json) matches
the baseline. The [actual public UI before change](results/hosted-before.json)
retains all four session copies and breaks the authored array control in both
engines and both widths. The [corrected local UI](results/browser-after.json)
removes every copy, downloads complete masked text and vaults, restores the
native source exactly in an explicit local diagnostic, and preserves the
array-valued control. No HAR prompt or download initiates a network request
after bootstrap. The later accessibility audit's font GET is recorded separately.

All four [desktop/phone screenshots](../../docs/assets/har-headers/firefox-375.png)
were opened and inspected; real HAR text is long and wraps without horizontal
page overflow. Each accessibility audit passes. The app's canned simulated
reply does not echo HAR data, so that feature is not used as a restoration
claim. Local/source/package results do not alone establish public delivery.
