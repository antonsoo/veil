# IPv6 literal verification, 2026-10-12

Source change: `838f22ed23d856e70621737c69f189ae2b47fcf4`.
Baseline: `33992a7b59f23cb158c17215f76de06604ef95d4`.
This is source verification. Package version 0.4.4, registry releases, tags and
the hosted demo are not updated by this work.

The defect and recognition boundaries are described in the
[study](../studies/ip-literals/README.md). The
[machine-readable receipt](../studies/ip-literals/results/verification.json)
contains source, artifact and served-asset hashes.

## User-visible result

| Check | Before | After |
| --- | ---: | ---: |
| Synthetic literal/control outcomes | 28/150 | 150/150 |
| CLI complete redaction, text/JSON/JSONL | 0/21 | 21/21 |
| Complete redaction in captured SDK requests | 0/21 | 21/21 |
| Offline browser outcomes, two engines/two widths | 40/148 | 148/148 |

The baseline left `.0.2.33` visible after redacting
`2001:db8::192.0.2.33`. Complete mixed and scoped literals now map to one
surrogate. All ordinary and streamed restoration checks remain exact.
The generated positive addresses were independently parsed by libc
`inet_pton`; scope names and the masking policy are explicit fixtures.

All 10,339 resolved detections across the retained public corpus are unchanged
(1,483 files, 32,925,796 bytes, 2,616,034 words). This is a collateral-change
check, not a production IPv6 recall estimate.

## Clean checkout and installed artifacts

The source was exported with `git archive`, installed with `uv sync --locked`
on Python 3.12.12, and checked with Ruff, Ruff formatting, mypy and pytest.
The sdist was built from that archive, then the wheel was built from the sdist.
Separate Python 3.10.21 and 3.14.7 environments installed the wheel and the
locked development requirements. They ran the entire test suite and the
150-case replay, 21 CLI flows and 21 SDK transport requests.

| Environment | Tests | Targeted replay |
| --- | --- | --- |
| Clean archive, Python 3.12.12 | 627 passed, 1 skipped | Source replay retained separately |
| Installed wheel, Python 3.10.21 | 627 passed, 1 skipped | All expected outputs and restoration pass |
| Installed wheel, Python 3.14.7 | 627 passed, 1 skipped | All expected outputs and restoration pass |

The skip is the optional real spaCy backend, which is not installed. Ruff and
mypy were run on the clean 3.12 environment; the two wheel environments ran
pytest and the application replays. Their replay rows match the source replay,
including captured request hashes. SDK versions were OpenAI 3.23.0,
Anthropic 1.11.0 and HTTPX2 2.13.1; transport was local, without provider calls.

All 120 tracked source/test/web/configuration inputs match the archive.
All 35 package files match across source, sdist, wheel and both installed
environments. The wheel import paths were checked to be inside those new
environments, without an editable checkout on `PYTHONPATH`.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `veil_pii-0.4.4.tar.gz` | 93,746 | `5d154ba35704e099ce093c3f972d9c94c82b089a96cae337456ecd1ddc9b5b63` |
| `veil_pii-0.4.4-py3-none-any.whl` | 88,402 | `873d39a124d0e18138ba866b1500ab899880db8bb46e9fcc2239a29e4298d6c0` |

Reproduction from an exported checkout:

```sh
uv sync --locked --python 3.12
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -q
uv build --sdist --out-dir dist
uv build dist/veil_pii-0.4.4.tar.gz --wheel --out-dir dist
uv export --locked --only-group dev --no-emit-project --format requirements-txt -o /tmp/veil-dev.txt
uv venv --python 3.10 /tmp/veil-wheel
uv pip install --python /tmp/veil-wheel/bin/python --require-hashes -r /tmp/veil-dev.txt
uv pip install --python /tmp/veil-wheel/bin/python dist/veil_pii-0.4.4-py3-none-any.whl
env -u PYTHONPATH /tmp/veil-wheel/bin/python -m pytest tests -q
env -u PYTHONPATH /tmp/veil-wheel/bin/python studies/ip-literals/replay.py --sdk --output /tmp/ip-installed.json
```

Use a second fresh environment for Python 3.14.

## Browser and runtime

A clean Node 24.21.0 install passed web lint, build and all 16 existing browser
scenarios. The targeted driver exercises 37 cases in each of Chromium and
Firefox at 375 and 1280 pixels. It checks real Pyodide results, previews and
296 downloaded text/vault files per run, with no requests after switching
offline. All ten assets received by the targeted browser run match the clean
Node 24 build byte for byte. There were no page errors, CSP violations or
horizontal page overflow in that run.

Four screenshots were visually inspected:

| Browser/width | Before | After |
| --- | --- | --- |
| Chromium, 1280 | [Screenshot](assets/ip-literals/before/chromium-1280.png) | [Screenshot](assets/ip-literals/after/chromium-1280.png) |
| Firefox, 375 | [Screenshot](assets/ip-literals/before/firefox-375.png) | [Screenshot](assets/ip-literals/after/firefox-375.png) |

The scaling receipt measures five synthetic malformed-token shapes through
one million characters. It covers only the IP scanner on a shared 14-vCPU
WSL2 host, not overall masking throughput or a worst-case guarantee.
