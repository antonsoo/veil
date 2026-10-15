# Temporary AWS access key IDs must not depend on entropy

The known AWS key detector previously recognized only `AKIA`. Temporary `ASIA`
key IDs went through a generic entropy/word heuristic, which skipped some
complete IDs. The corrected source recognizes both prefixes with the same
20-character shape and whole-token boundaries.

[AWS documents](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_identifiers.html#identifiers-unique-ids)
`ASIA` as the temporary STS access key ID prefix. These IDs alone do not
authenticate: temporary credentials also need the secret access key and session
token. This change protects the recognized identifier; it does not claim to
cover every session-token shape, validate credentials or revoke exposed keys.

## Controlled reproduction

```sh
uv run python studies/sts-key-ids/replay.py --sdk --require-fixed --output /tmp/sts-after.json
uv run pytest tests/test_sts_access_keys.py
```

The replay generates 1,000 distinct 16-character bodies from `A-Z2-7`, using
seed `20261015`, and checks each under both prefixes. This matches the current
body alphabet used in the [Gitleaks AWS rule](https://github.com/gitleaks/gitleaks/blob/master/cmd/generate/config/rules/aws.go).
It is a **synthetic shape sample**, not an empirical distribution of issued
keys or a claim about production leak frequency. No AWS operation is called,
and the examples are not issued credentials.

| Observed behavior | Baseline `67e4100` | Corrected source |
| --- | ---: | ---: |
| `AKIA` IDs completely recognized | 1,000/1,000 | 1,000/1,000 |
| `ASIA` IDs completely recognized | 841/1,000 | 1,000/1,000 |
| `ASIA` IDs recognized by their known prefix | 0/1,000 | 1,000/1,000 |
| Actual SDK requests with every example masked | 0/12 | 12/12 |

[Before](results/before.json) and [after](results/after.json) retain counts,
detector provenance hashes and actual SDK request bodies. Four previously
missed synthetic `ASIA` IDs and one `AKIA` control pass through the real SDK
serializers: Chat Completions, Responses and Anthropic, each sync/async and
buffered/streaming. A local HTTP echo transport checks exact restoration and
makes no model call. The CLI/vault replay separately preserves CRLF bytes and
tests stream restoration at four chunk sizes for each example.

For a baseline replay, export `67e4100`, set `PYTHONPATH` to that archive's
`src/`, then use the current replay script without `--require-fixed`.

The shape rule intentionally keeps `AKIA`'s existing compatibility alphabet
`0-9A-Z`; adding `ASIA` does not change historical `AKIA` acceptance. It does
not recognize shorter/longer IDs or infer validity from the prefix. Glued word
characters cannot produce a shorter known-key match. Generic entropy scanning
remains a separate heuristic and can still find other token-like strings.
Other IAM resource prefixes such as `AIDA` and `AROA` are not newly treated as
known access keys. Higher-confidence whole mailbox and credential-URL
detections continue to enclose key-shaped substrings.

The [retained technical-corpus receipt](results/corpus.json) confirms zero
changed resolved detections across 1,483 files, 32,925,796 bytes and 2,616,034
words: all 10,372 keep their type, span, value, detector and confidence. This
checks collateral behavior on that corpus, not STS-key recall in production.

The change is local and unreleased; PyPI and the hosted demo are unchanged.
Build the browser with `cd web && npm ci && npm run build` (`web/dist/`). The
existing browser harness accepts the retained secret fixture:

```sh
node studies/email-boundaries/check-browser.mjs web/dist studies/sts-key-ids/results/browser studies/sts-key-ids/browser-cases.json
```
