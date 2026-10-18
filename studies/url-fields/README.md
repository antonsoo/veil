# Short credentials in ordinary URLs

The URL detector previously recognized `access_token` but left a complete URL
containing `client_secret=wordlike`, `refresh_token=wordlike`, `passwd=wordlike`
or `SERVICE_PASSWORD=wordlike` visible. These are explicit credential labels
already used by Veil's field policy. Entropy cannot identify such short values.

The detector now reuses that policy for query and fragment parameter names,
including router fragments. It masks the complete original URL and restores
its exact spelling. Names are percent-decoded once; values are not interpreted
as more parameters. Empty values and lowercase environment-style names retain
the existing policy. The prior signing and URL-specific aliases still apply.

## Actual client requests

[`capture.py`](capture.py) uses HTTPX2 2.13.1 and Python's urllib against a
short-lived loopback server. Four field names, two clients and a valid/incorrect
value produce 16 real requests: eight HTTP 200 and eight HTTP 401. These are
synthetic controls authored for this server, never external credentials.
[`capture.json`](capture.json) retains the clients' actual URL strings and
received request targets. HTTP acceptance is independent of masking policy:
incorrect credentials must be hidden too.

[`replay.py`](replay.py) exercises each URL as text, a JSON argument string and
a typed tree, with exact restoration. JSON argument spelling, duplicate unrelated
members and large exponents remain intact; text also restores one character at
a time. Against `d03e14b4b764e5809f3f84667e58bc842c2e98f0` all 48 privacy
checks fail. The corrected source protects all 48 with one complete URL mapping.

The existing public technical corpus has 1,483 files and 32,925,796 bytes.
Before/after replay retains exactly the same 1,600 mappings, no refusals and no
changed restorations; both output ledgers hash to
`e34ff91d00680fa18a57966327929cd528a7401e4b417f50af2d4903cd8244a8`.
This corpus comparison does not measure general secret-detection accuracy.

```sh
uv run studies/url-fields/capture.py  # optional new loopback capture
uv run python studies/url-fields/replay.py --src src --out /tmp/url-after.json
uv run python studies/url-fields/replay.py --src /path/to/baseline/src --out /tmp/url-before.json --observe-only
```

Replay uses the retained capture without networking. Source, installed wheel,
served browser runtime and registry release are separate claims. No PyPI
release or tag is created by this work.

## Installed and public results

Source `ce74b2f1c84b124d703d0f2d9123517963732c27` passes lint, formatting,
types and 1,728 checks in a clean archive; one optional spaCy module is skipped.
The [artifact receipt](results/artifacts.json) compares all 40 runtime files
in the wheel, sdist and two fresh wheel installations. Python 3.10.21 with
Anthropic 0.40.0/OpenAI 1.66.0 and Python 3.14.7 with Anthropic 1.15.0/OpenAI
3.35.1 each protect all 48 native URL workflows. All 39 browser Python modules
match the same source. The [documented Git installation](results/git-origin.json)
was actually forced over an existing same-version installation and reproduces
all runtime bytes and URL results.

The previous HAR correction is also replayed against this final source and
both installed environments: nine direct workflows and 36 real SDK tool
serialization/restoration workflows each retain zero failures. See
[clean](results/har-clean.json), [floor](results/har-installed-floor.json) and
[current](results/har-installed-current.json) receipts. No provider is called.

Pages commit `4011db5` deploys the combined engine. All 27 canonical responses
match the [clean-build bytes](results/hosted-bytes.json), with no cache-busting
URLs. [`browser.mjs`](browser.mjs) exercises four actual client URLs in both
browser engines at desktop and 375 pixels, before and after publication:
16 inputs and 32 actual masked/vault downloads per phase. Each downloaded
vault restores the exact URL. All corrected masks contain one complete URL
surrogate, with zero post-bootstrap requests and zero page errors. Retained
screenshots were inspected. [Before](results/public-before/browser.json) and
[after](results/public-after/browser.json) establish browser behavior separately
from file delivery. The registry version remains unchanged.
