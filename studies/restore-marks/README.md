# An accent is not a fuzzy-restoration boundary

With `Avery Castillo` as a realistic surrogate for fictitious `Jordan Alvarez`,
the former tolerant restorer left `avery castilló` alone in composed Unicode
but restored its decomposed spelling as `Jordan Alvarez` followed by an accent.
The final `o` plus U+0301 was treated as a complete unaccented surrogate and
a separator. Buffered SDK text and tool-input values inherited that behavior.

| Recased reply | Former tolerant result | Corrected result |
| --- | --- | --- |
| `avery castilló` (NFC) | unchanged | unchanged |
| `avery castillo\u0301` (NFD) | `Jordan Alvarez\u0301` | unchanged |
| `avery castillo` | `Jordan Alvarez` | `Jordan Alvarez` |
| `avery castillo's` | `Jordan Alvarez's` | `Jordan Alvarez's` |

These are authored replies, not captured model behavior. The surrogate is
generated through the normal vault path at PERSON index 48 after 47 authored
contacts. The study establishes a reproducible transformation error; it does
not estimate how often a model emits decomposed text or coincidental names.

## Correction and limits

Fuzzy boundaries now keep Unicode nonspacing, spacing and enclosing marks
attached to adjoining word characters. No normalization, accent removal,
transliteration or runtime dependency is added. The
[Unicode text segmentation specification](https://www.unicode.org/reports/tr29/#Word_Boundaries)
provides context for keeping combining characters with text, but this bounded
letter/number/underscore/mark check is **not** the full Unicode word-boundary
algorithm or a locale-specific name matcher. Other format characters and
language-specific segmentation keep their existing behavior.

**Exact restoration still replaces every exact surrogate substring wherever
it appears.** Tolerant restoration retains that exact pass first; streaming
uses exact matching only. Thus an exact-case `Avery Castillo` prefix inside
`Avery Castillo\u0301` still restores by contract. This correction protects the
additional recased/whitespace matching; it does not turn realistic surrogates
into unambiguous tokens. The documented accidental-collision tradeoff remains.

## Reproduction

[Baseline `82f3c83`](results/before.json) and
[corrected source](results/after.json) retain the actual strings, CLI output,
SDK request bodies and restored text/tool objects. Eight of 19 direct controls
fail before and pass after. The same eight fail in the default CLI path; all
19 `--exact` controls retain their behavior. Nonspacing, spacing and enclosing
marks on either boundary are explicit mixed-script stress controls, rather
than claims about ordinary personal-name spelling.

Sixteen real Anthropic SDK paths cover sync/async and buffered/streamed text
and nested tool values over a local mock HTTP transport. Both buffered NFD
cases insert the private original before and preserve the authored reply
after. All exact-stream controls agree. The requests contain the generated
surrogate rather than the original. No provider request, key or model call
is used. Seven newly added boundary assertions fail on the former source.

With the dev dependencies installed:

```sh
uv run python studies/restore-marks/replay.py --source . --label current --sdk --out /tmp/veil-marks.json
```

Use `--source CHECKOUT` at `82f3c83` for the original behavior. Without
`--source`, the script uses the Python environment's installed package;
omit `--sdk` for the dependency-free core and CLI. The CLI's documented final
newline is checked separately from the library string. Every possible single
split of every direct input checks the exact streaming contract.

The existing hash-checked technical corpus also replays unchanged: 1,483 files,
32,925,796 UTF-8 bytes and 1,593 mappings. Every exact and tolerant roundtrip
succeeds, with identical masked-text/vault ledger hashes before and after:
[before](results/corpus-before.json), [after](results/corpus-after.json).
This is a compatibility check, not a detection-accuracy measurement. Cached
source texts are not redistributed; [sources and licences](../real-text/README.md#sources-and-licences)
remain with the original study.

Run the corpus check with its existing local cache:

```sh
uv run python studies/surrogate-collisions/corpus.py --source . --label current
```

Source, installed artifact, browser-served Python and registry release are
separate verification boundaries. PyPI 0.4.4 is not changed by this study.
