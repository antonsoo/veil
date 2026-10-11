# A content match must preserve its source

Veil's source checkout fixes four related integration errors found at
`7bec64d6bd76a19cf37a9bb3b56e6e77c1bd533b`. The retained
[before](results/before.json) and [after](results/after.json) files contain
synthetic responses, actual SDK output and outgoing HTTP request content.
All contacts are fictional. There are no provider calls or real credentials.
These are local source changes, not a PyPI release or a live-provider result.

## What failed

| Workflow | Before | After |
| --- | --- | --- |
| Anthropic text helpers, placeholder fragments in separate blocks | Invented a restored email absent from either block | Restores each block independently, then joins |
| Two assistant replies with different placeholder casing but identical restored text | Replayed both as the second reply | Retained objects replay their own originals; ambiguous copies fail before transport |
| Removing/adding `null` in an Anthropic tool input | Replayed the old input, discarding the edit | Sends the edited, masked input |
| A user message repeating a provider-generated contact | Assistant replay bypassed masking | User content is masked |

There are 16 controlled scenarios. Four streaming cases run synchronously and
asynchronously; two history storage forms run through Anthropic and Chat
Completions; two JSON-null edits and two user-content forms complete the set.
Fourteen disagreed with their independent expected outputs before the fix;
none disagree afterward. These deliberately selected counterexamples measure
the demonstrated failures, not their frequency in production.

## The two different boundaries

The [Anthropic streaming protocol](https://platform.claude.com/docs/en/build-with-claude/streaming)
gives each content block its own index, start, deltas and stop. Chunk boundaries
within one block are transport details. A block boundary is part of the message.
Veil used the SDK's flattened text iterator, which erased that distinction.
`get_final_text()` similarly restored the concatenated raw text.

The fix feeds the text iterator from the same indexed event restoration used by
event consumers. Pending text is flushed at the matching block stop. Complete
text is assembled from separately restored blocks. Sync/async helpers retain
one event iterator so switching from partial text consumption to events keeps
pending state. The SDK still owns its raw message accumulation and transport.

For history, restoration can be many-to-one: an exact placeholder and a
case-changed placeholder can both become the same email. A dictionary keyed only
by restored content cannot distinguish the two original turns.

```text
provider turn A ----> restored object A ---+--> next request: original A
                                         |
provider turn B ----> restored object B ---+--> next request: original B
                     (equal contents)

serialized equal contents ------------------> ambiguous: refuse before HTTP
```

The cache now retains object identity separately from content fingerprints. It
checks unchanged objects first; a content-only match must have one known
provider value. String identity is deliberately excluded: Python can reuse the
same string object for multiple occurrences. Ambiguous copied history raises a
`VaultError` that contains no message text. Request preparation is transactional,
so any mappings created before that error are rolled back.

SDK `model_dump()` and `model_dump(exclude_none=True)` forms both work for
unambiguous records. JSON nulls inside application dictionaries remain in both
fingerprints. Saved originals are copied at capture and again for outbound use;
editing either SDK snapshots or prepared requests cannot mutate the cache.

## Reproduce

From this repository:

```bash
uv sync --locked
uv run python studies/message-boundaries/capture.py --source . --label source --check
uv run pytest -q tests/test_anthropic_boundaries.py tests/test_replay_identity.py
```

For the old behavior, archive `7bec64d` into a temporary directory and pass that
directory as `--source`. The script imports Veil from that source tree while using
the same synthetic wire fixtures. Omit `--check` to retain the failing output.
For a wheel installation, run the script using that environment's Python and
omit `--source`; the receipt records its Python and SDK versions.

The script's streaming oracle substitutes known tokens inside each complete
source block before joining. Its history oracle compares the outbound strings
with the two recorded originals, or requires an ambiguity error with no third
request. The null and role checks inspect the actual outgoing request bodies.
Unit regressions additionally cover every internal cut of the placeholder,
partial iterator consumption, empty/tool-only messages, snapshot mutation,
bounded identity retention and masking rollback.

## Clean and installed verification

The [verification receipt](results/verification.json) identifies source commit
`8af48db`, the wheel/sdist SHA-256 hashes, runtime versions and every skip. The
wheel was built from the source distribution in a clean `git archive` of that
commit. Tests in each installed environment imported Veil from its
`site-packages`, outside the source checkout.

| Environment | Python | Anthropic SDK | OpenAI SDK | Full suite | Capture disagreements |
| --- | --- | --- | --- | --- | --- |
| Clean source, locked dependencies | 3.12.12 | 1.11.0 | 3.23.0 | 493 passed, 1 skipped | 0/16 in source replay |
| [Installed wheel, newly resolved SDKs](results/installed-current.json) | 3.14.7 | 1.13.0 | 3.28.0 | 493 passed, 1 skipped | 0/16 |
| [Installed wheel, minimum direct dependencies](results/installed-minimum.json) | 3.10.21 | 0.40.0 | 1.66.0 | 487 passed, 7 skipped | 0/16 |

The clean source commands were `uv sync --locked`, `uv run --locked ruff check .`,
`uv run --locked ruff format --check .`, `uv run --locked mypy`,
`uv run --locked pytest -q` and `uv build`. Each installed environment ran
`python -m pytest -q <clean-archive>/tests` and the capture command above, without
`--source`. The minimum environment used `uv pip install --resolution
lowest-direct <wheel>[anthropic,openai,vault-crypto] --group dev` with this
repository's development dependency declarations.

The optional spaCy backend is absent in all three environments. The minimum
SDKs additionally skip five tests requiring Anthropic thinking blocks and one
requiring an OpenAI reasoning-summary field. All new boundary and replay
regressions run in both installed environments. The installed Python README
example passes, and the support-ticket CLI example masks, audits successfully,
and restores byte-for-byte to the input.

## Scope

### Cache capacity follow-up

A pre-publication long-run check at `ebc64b9` found another source-identity
failure: once the cache forgot turn A, a later turn B with equal restored
content appeared unique. Replaying the old A object then sent B's placeholder
spelling. [Before](results/capacity-before.json) and
[after](results/capacity-after.json) retain the actual SDK request bodies and
a control using the default 10,000-entry capacity.

```text
turn A -> evicted -> equal turn B arrives -> old A is submitted
before: content match chooses B
after:  lost identity causes an error before HTTP
```

Content matching is now disabled permanently after the first content eviction.
An unchanged retained object still identifies its original. A rebuilt list can
also use its retained, unchanged block objects; a deep copy cannot. This is a
deliberate bounded-memory tradeoff: retaining only recent collisions cannot
establish uniqueness over forgotten history. Unrecognized or edited history
still goes through fresh masking; it is not promised exact replay.

Reproduce the five capacity scenarios with:

```bash
uv run python studies/message-boundaries/capacity.py --source . --check
```

Use an archive of `ebc64b9` with `--source` and omit `--check` for the failing
behavior. The four SDK cases use an eight-entry cache to force eviction in
eight replies; this is a deterministic counterexample, not a claim about a
typical conversation length. SDK serialization aliases and individual block
entries also consume capacity.

The follow-up [verification receipt](results/capacity-verification.json) covers
source commit `e7799fd`, built as an sdist and then wheel from a clean archive.
Both installed environments pass all five capacity scenarios and the earlier
16 boundary scenarios. The current SDK environment passes 496 tests with the
optional spaCy test skipped; the minimum SDK environment passes 490 with the
same seven optional/version skips described above. Lint, formatting, type
checking and the clean source suite also pass. Artifact hashes and full capture
links are retained alongside the receipt; these remain synthetic local results.

### Remaining boundaries

The cache is local to one wrapper. It retains at most 10,000 content fingerprints
and 10,000 object identities; SDK serialization aliases count against the
fingerprint limit. Exact replay only applies to retained, unchanged history.
Keep the returned Anthropic content list or Chat Completions message object when
different replies restore to the same value. Reconstructing an ambiguous object
or reducing it to plain text loses the information needed for exact replay.
Persisting that identity across application restarts is outside this cache.

Streaming uses exact matching; complete blocks still allow tolerant restoration.
Thinking/signature blocks remain untouched. This work does not measure detector
recall, validate real provider signatures, or prove live-service compatibility.
