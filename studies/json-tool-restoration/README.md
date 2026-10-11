# Restore the address, preserve the tool's other arguments

Veil's complete OpenAI tool replies used `json.loads`, recursively restored
strings, then serialized the whole tree. Restoring one email could change an
unrelated amount or discard a repeated member. A valid large exponent could
become `Infinity`, which is not a JSON number. The streaming restorer already
preserved those tokens.

| Provider arguments (address omitted here) | Previous complete reply | Corrected complete reply |
| --- | --- | --- |
| `"amount":0.12345678901234567890` | `"amount": 0.12345678901234568` | Original decimal retained |
| `"n":1e309` | `"n": Infinity` | Original exponent retained |
| `"n":1,"n":2` | `"n": 2` | Both members retained |
| `"n":-0.00E-03` | `"n": -0.0` | Original numeric spelling retained |

The correction shares the validated string-token scanner used for outgoing
argument masking. It restores decoded **value** strings and re-encodes only
changed tokens. Keys, numbers, whitespace and unrelated escapes remain as the
provider produced them. Tolerant matching of complete surrogate values remains
available. Invalid or truncated model output still uses the existing best-effort
streaming lexer; it is not repaired into a valid document. Exact replay sends
the original provider arguments, rather than the application's restored copy.

`capture.py` records the actual Chat Completions and Responses SDK objects and
replayed requests using an in-process mock HTTP transport. All contacts are
synthetic; no provider is contacted. [Before](results/before.json), 12 of 16
captures changed tokens outside the restored value. [After](results/after.json),
all 16 preserve the expected text and replay the original arguments. The counts
cover eight explicit cases in each API, not a population accuracy estimate.
The unchanged controls include a reply without a surrogate and truncated JSON.
Both captures use Python 3.12.12 and OpenAI 3.23.0; the baseline is `466d990`.

```sh
uv sync --locked --group dev
uv run python studies/json-tool-restoration/capture.py --source . --check
uv run pytest -q tests/test_json_argument_restoration.py tests/test_sdk_json_arguments.py
```

To check an installed package, run the capture file with its environment's
Python and omit `--source`. `tests/sdk_wire.py` supplies only the mock response
envelopes; the SDK and Veil run from that environment. Unit checks additionally
compare complete and streamed restoration with an independent `Decimal` and
object-pairs oracle, including a 5,000-digit integer and originals containing
quotes, backslashes and control characters.

Preserving duplicate members does not endorse them or establish how a downstream
tool handles them. This correction prevents Veil from silently deciding that
question. Applications remain responsible for schema validation, safe execution
and numeric support. These checks verify local SDK behavior, not provider
acceptance or live model output. The change is not yet in a PyPI release.

## Installed artifact

A fresh archive of `e6b4ab6`, installed with locked dependencies on Python 3.14.7,
passed Ruff lint/format, mypy and 456 tests. The optional spaCy module was skipped.
The wheel was built from the source distribution, then installed separately on
Python 3.10.21 with OpenAI 1.66.0. Its [16 restoration captures](results/installed-minimum.json)
and all 16 earlier masking captures passed. Another 105 targeted tests passed;
one was skipped because the minimum SDK predates reasoning-summary fields.
[verification.json](results/verification.json) retains the artifact hash and scope.
