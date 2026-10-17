# Keep the whole YAML credential together

At baseline `c1ecfcb`, a valid YAML password containing an apostrophe became:

```yaml
password: '⟨SECRET_1⟩''rise'
```

Only `sun` was protected from the original `sun'rise` password. Quoted multiline
values passed through unchanged. Default serializer output failed too:

```yaml
password: ⟨SECRET_1⟩
  stone quiet meadow
```

The remainder of the plain password was still visible. Source `e5e2363` keeps
each supported scalar body in one opaque raw span. It preserves outer quotes,
comments, neighboring fields and exact source spelling on restoration. The
core still has no runtime dependencies. This is a local correction: no push,
hosted deployment, package version change or registry release is part of this
work.

## Native writers and outgoing requests

[`capture.py`](capture.py) retains 120 actual outputs from **PyYAML 6.0.3** and
**ruamel.yaml 0.18.16**, using default, single-quoted and double-quoted emission
in nested mappings and compact sequences. Both loaders agree with the original
controlled values. Native scalar tokens establish the source bounds; the input
is not rewritten to fit Veil. The values include apostrophes, literal
backslashes, wrapped phrases, blank lines, Unicode, assignments and nested PII.
[Inputs and native bounds](fixtures/native.json).

| Workflow | Baseline protected completely | Corrected |
|---|---:|---:|
| Actual native writer outputs | 12/120 | 120/120 |
| Actual serialized SDK requests | 0/12 | 12/12 |

[`replay.py`](replay.py) retains the [before](results/before.json) and
[after](results/after.json) outputs, vault originals, runtime hashes and actual
SDK request bodies. OpenAI Chat/Responses and Anthropic clients use mock HTTP
echo responses, sync/async and buffered/streaming. No model service is called.
Every native input also goes through the actual CLI/vault and four streaming
chunk sizes. Baseline restoration succeeds too: that did not establish
outgoing protection. All credential values in this study are synthetic.

[`oracle.py`](oracle.py) checks 2,160 additional documents in both YAML loaders:
three scalar styles, four mapping/sequence contexts, three key spellings,
three line-ending styles, five bodies, an optional final newline and a scalar
starting on the key's line or the following indented line. Exact masked source
must match the independently constructed single replacement. Both loaders
also parse the corrected result. [Before](results/oracle-before.json) and
[after](results/oracle-after.json) retain matching input-ledger hashes and
explicit failure counts. This is a syntax check, not a production recall study.

```sh
uv run --locked --with PyYAML==6.0.3 --with ruamel.yaml==0.18.16 python studies/yaml-flow-credentials/capture.py
uv run --locked python studies/yaml-flow-credentials/replay.py --sdk --require-fixed --output /tmp/yaml-flow.json
uv run --locked --with PyYAML==6.0.3 --with ruamel.yaml==0.18.16 python studies/yaml-flow-credentials/oracle.py --require-fixed --output /tmp/yaml-flow-oracle.json
```

For baseline replay, archive `c1ecfcb`, point `PYTHONPATH` to that archive's
`src/` and omit `--require-fixed`. YAML libraries are study dependencies only.
The installed core can run `replay.py` without `--sdk` or a YAML library.

## Recognition and ambiguity

The [YAML 1.2.2 flow-scalar rules](https://yaml.org/spec/1.2.2/#73-flow-scalar-styles)
define the distinction: apostrophes double inside single quotes, backslashes
are literal there, and quoted/plain scalars can span lines. The source
recognizer deliberately covers a smaller scope:

- A supported credential key starts a block mapping entry, optionally after
  compact sequence markers. A colon has following horizontal space or a line
  break. Quoted keys, uppercase environment prefixes and a leading BOM work.
- Quoted bodies keep raw escapes, doubled apostrophes, internal line breaks
  and indentation together. Wrapped nonblank lines must be indented farther
  than the key. A malformed quote stops before a sibling mapping.
- Plain bodies retain phrases, quotes, punctuation and wrapped text. Inline
  comments, dedented lines and mapping syntax end their span. Blank internal
  lines stay part of a continued value. An indented first scalar line can
  follow an otherwise empty key line; an empty field cannot absorb its sibling.
- Collections, aliases, anchors and tags do not become string credentials.
  Existing non-string/type-word and shell-reference exclusions remain.
  Block-looking text inside a recognized scalar cannot fragment its body.

Raw text does not establish its format. `client_secret: short, status=error`
can be a log record or one legal YAML string. The recognizer retains the
existing comma/semicolon-plus-field convention and masks `short` in that
spelling; a YAML password containing that exact field-like suffix is therefore
not completely protected. Type-word exclusions also apply to raw type
annotations such as `password: string;`. Use quoted values or decoded
`field_name` context when these conventions conflict with the actual credential.
Arbitrary flow collections, escaped key names, unindented continuations,
comments before a next-line scalar, explicit mapping keys and malformed YAML
remain outside the coverage established here. This is not a general YAML
parser, a guarantee of anonymization or credential authentication.

## Collateral checks and cost

The [technical corpus receipt](results/corpus.json) compares complete resolved
detections, including span, original value, type, detector and confidence,
over the retained public technical corpus. All input bytes are checked against
its existing pinned manifests. All **10,407** detections over **1,483 files**,
**32,925,796 bytes** and **2,616,034 words** are unchanged. The complete before/after
receipts are byte-identical. This is retained-source replay, not fresh
collection or a new precision estimate.

[`scaling.py`](scaling.py) measures quoted values, plain values, delayed starts,
block-looking contents, malformed tails and long single lines at 100, 1,000
and 10,000 repetitions, with one warmup and three timed measurements.
[Before](results/scaling-before.json) and [after](results/scaling-after.json)
retain input/runtime hashes, detection counts and each measurement. Recognition
adds work; these observations are not a worst-case latency bound or a speedup
claim. Maximum detector medians were 0.320 seconds before and 0.366 seconds after.
Machine: 14 vCPU WSL2 Linux, 48 GB RAM; Python 3.12.12.

## Packages and the browser

The [verification receipt](results/verification.json) records clean archive
installation, lint/format/type checks, the Python suite, wheel/sdist builds,
fresh installed-package replays and the browser build. Package versions stay
unchanged. To use the local source rather than the older published package,
install this checkout with `python -m pip install --force-reinstall .`.

The clean archive passes all **1,574 Python tests with no skips**, including
the optional spaCy backend, plus all **16 existing browser scenarios**. Wheel
and sdist contain the same **38 runtime files** as source `e5e2363`. Fresh
Python **3.10.21** and **3.14.7** wheel installations and a **3.14.7** sdist
installation replay all 120 native inputs through the CLI/vault and streaming
restorer. Core-only environments have no installed runtime dependency. The
3.14 wheel also replays all 12 SDK requests with OpenAI 3.23.0 and Anthropic
1.11.0. Imports come from `site-packages`; all runtime bytes match. All 37
Python files embedded in the clean browser build match the same source, and
that complete build matches the one used for the retained offline checks.

The [baseline browser record](results/browser-before/receipt.json) and
[corrected record](results/browser-after/receipt.json) use actual bundled
Python in Pyodide, offline after neutral initialization, in Chromium/Firefox
at 375/1280 pixels. They inspect the same input text, complete masked/vault
downloads, exact restoration, request counts and page errors. The browser's
canned reply does not exercise these credentials; native SDK echoes above
establish reply restoration separately.

| Actual build | Mobile Chromium | Desktop Firefox |
|---|---|---|
| Baseline | [Capture](results/browser-before/chromium-375.png) | [Capture](results/browser-before/firefox-1280.png) |
| Corrected | [Capture](results/browser-after/chromium-375.png) | [Capture](results/browser-after/firefox-1280.png) |

```sh
cd web && npm ci && npm run build  # -> web/dist/, base /veil/
cd ..
node studies/email-boundaries/check-browser.mjs web/dist /tmp/yaml-flow-browser studies/yaml-flow-credentials/browser-cases.json
```

All eight before/after captures were inspected. The existing layout keeps
neighboring fields readable and the complete raw originals inside the vault,
including narrow displays. These checks establish local browser behavior;
they do not establish the current hosted demo's bytes or a registry release.
