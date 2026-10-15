# Whole mailbox domains across IDNA separators

Veil previously stopped scanning an email domain at an ideographic, fullwidth
or halfwidth full stop. A valid-looking prefix could become a surrogate while
the rest of the domain remained visible. An address using only these separators
could pass through unchanged. These are **constructed reproductions**, not
production privacy incidents or registered/deliverable addresses.

| Synthetic input | Baseline `f8a7892` | Corrected source |
| --- | --- | --- |
| `alice@example。org` | unchanged | `⟨EMAIL_1⟩` |
| `alice@example.org。private.example` | `⟨EMAIL_1⟩。private.example` | `⟨EMAIL_1⟩` |
| `alice@example.org．private.example` | `⟨EMAIL_1⟩．private.example` | `⟨EMAIL_1⟩` |
| `alice@example.org｡private.example` | `⟨EMAIL_1⟩｡private.example` | `⟨EMAIL_1⟩` |
| `利用者@例え。テスト` | unchanged | `⟨EMAIL_1⟩` |

[Unicode UTS #46 section 2.3](https://www.unicode.org/reports/tr46/#Notation)
defines four label separators: U+002E, U+3002, U+FF0E and U+FF61.
[RFC 5895 section 2](https://www.rfc-editor.org/rfc/rfc5895.html#section-2)
also explains mapping before label separation. Veil now consumes the complete
candidate before checking labels. A validation copy maps separators to ASCII;
entity spans, vault originals and restored text retain the exact source.
Equivalent spellings receive distinct surrogates, preserving reversibility.
The patch adds no dependency or DNS lookup.

## Reproduced workflows

```sh
uv run python studies/idna-mailboxes/replay.py --sdk --require-fixed --output /tmp/idna-after.json
uv run pytest tests/test_email_idna_separators.py
```

The replay covers all 64 combinations of four separators across three label
boundaries, international and quoted local parts, private suffixes, malformed
suffixes, excessive labels/domains and invisible characters. Python's independent
IDNA codec checks positive domains. It is a structural oracle, not evidence
that a mailbox exists or that every EAI form is supported.

| Observed workflow | Baseline | Corrected source |
| --- | ---: | ---: |
| Complete expected boundary behavior | 4/101 | 101/101 |
| Actual SDK request bodies completely masked | 0/12 | 12/12 |
| Core, CLI/vault and CRLF restoration | 101/101 | 101/101 |
| Stream restoration at four chunk sizes | 404/404 | 404/404 |

[Before](results/before.json) and [after](results/after.json) retain actual
masked strings, synthetic source spellings and SDK request bodies. Each SDK
request contains nine positive examples. The real SDK serializers are exercised
through the existing local HTTP echo transport: Chat Completions, Responses and
Anthropic, each sync/async and buffered/streaming. No provider is called.

To replay the baseline, export `f8a7892` to a scratch directory, set `PYTHONPATH`
to its `src/`, and use the current replay script without `--require-fixed`.
The receipt records the loaded detector hash and SDK versions.

## Collateral checks and limits

The [corpus receipt](results/corpus.json) verifies the retained contact corpus
and every resolved detection in 1,483 technical files, 32,925,796 bytes and
2,616,034 words. All 10,372 resolved detections keep identical type, span,
value, detector and confidence. Contact coverage is unchanged in both retained
OSM sets. The earlier email study's identical baseline receipt is referenced
by hash rather than copied. Raw contacts remain in the ignored cache and
retain the original manifests' provenance/licenses.

This corpus does not establish improved real-world recall for the new
spellings. The improvement is demonstrated on the controlled boundary cases
and outgoing SDK bytes.

A final full stop remains punctuation. Adjacent prose that also forms valid
domain labels can be ambiguous, just as with ASCII dots: the detector consumes
the complete syntactic candidate. Local parts are not normalized. An invalid
complete candidate is rejected rather than shortened to a different mailbox;
unsupported email-like text may therefore remain unmasked. Existing local-only
domain and full RFC parser limitations still apply.

For the browser demo, `cd web && npm ci && npm run build` produces `web/dist/`.
The existing real-Python browser harness accepts this study's cases:

```sh
node studies/email-boundaries/check-browser.mjs web/dist studies/idna-mailboxes/results/browser studies/idna-mailboxes/browser-cases.json
```

This correction is local and unreleased. It does not update PyPI or the hosted
demo. The project description and topics remain unchanged.
