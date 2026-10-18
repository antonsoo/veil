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
