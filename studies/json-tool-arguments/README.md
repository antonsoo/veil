# Escaped tool history at the HTTP boundary

OpenAI Chat Completions and Responses represent function-call arguments as a
[JSON-encoded string](https://developers.openai.com/api/docs/guides/function-calling).
Veil previously ran its detectors on that string's raw spelling. An application
resending `{"to":"alice\u0040example.org"}` sent a readable email to the provider:
decoding the arguments yielded `alice@example.org`, but the vault had no mapping.
The same defect concealed application-supplied names containing escaped letters.

These are **controlled reproductions with synthetic contacts**, not a corpus
accuracy study. `capture.py` uses the actual OpenAI SDK's request serialization
and response parsing, with an in-process mock HTTP transport. It never contacts
a provider. The response envelopes come from `tests/sdk_wire.py`.

| Captured behavior | Before (`4a404a6`) | After |
| --- | --- | --- |
| Escaped address, fully escaped address, nested known person | Readable identity sent | Decoded value masked |
| Escaped literal placeholder beside an escaped address | Address sent | Address masked; literal preserved |
| Literal backslash and unrelated numeric spelling | Preserved | Preserved |
| Truncated JSON, `NaN`, sensitive field name | Request sent | `VaultError`; zero requests; vault unchanged |

The two APIs exercise each case separately: 14 of 16 baseline captures disagree
with the intended boundary; all 16 corrected captures agree. These counts refer
only to the explicit cases, not a general privacy success rate. Full request
bodies, decoded arguments, vault mappings, restored replies and individual checks
are in [before.json](results/before.json) and [after.json](results/after.json).
Both captures used Python 3.12.12 and OpenAI 3.23.0.

The implementation validates the document, decodes its string tokens and masks
value tokens as one batch. It rewrites only changed tokens. This preserves
unrelated escapes, whitespace, duplicate object members and numbers that would
lose precision if converted to floats. Keys with detected sensitive data cannot
be safely renamed without changing the tool's contract, so they reject the
request. Invalid input is not sent through a raw-text fallback.

The existing request transaction covers these values together with other messages
and instructions. For example, a literal placeholder hidden behind JSON escapes
in a later field cannot accidentally reuse an earlier email's mapping. Failure
rolls back the vault before the SDK sees any request. Existing replay of a
provider-produced item still sends its remembered original unchanged.

Reproduce from this repository, after `uv sync --locked --group dev`:

```sh
uv run python studies/json-tool-arguments/capture.py --source . --check
uv run pytest -q tests/test_json_argument_masking.py tests/test_sdk_json_arguments.py
```

To inspect an installed wheel, run the same capture file with that environment's
Python and omit `--source`. To reproduce the baseline, extract commit `4a404a6`
to a separate directory and pass that directory to `--source` without `--check`.

The regression checks inspect the actual SDK transport across both APIs, sync
and async clients, `create`, `create(stream=True)` and `stream`. They also check
caller-input immutability, vault rollback, exact history replay, long numeric
tokens, duplicate members and arbitrary mixtures of Unicode escape spelling.

Limits: detectors still have their documented false positives and misses. Names
require a backend. Non-string JSON values retain their types and are not
anonymized; sensitive identifiers should be strings. Ordinary message text and
custom-tool input are not recursively decoded as JSON. This verifies local SDK
serialization, not remote provider acceptance or a real model's behavior. The
source correction is not yet in a PyPI release.

## Artifact verification

A fresh archive of `01ca618` was installed on Python 3.14.7 with the locked
development dependencies. Ruff lint/format, mypy, all 445 tests and the wheel
build from the source distribution passed. One optional spaCy test module was
skipped because that extra was not installed.

The built wheel was separately installed on Python 3.10.21 with OpenAI 1.66.0,
the declared minimum versions. Its [16 captured cases](results/installed-minimum.json)
all agree with the corrected boundary. The wheel hash and exact verification
scope are retained in [verification.json](results/verification.json).
