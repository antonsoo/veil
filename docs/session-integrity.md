# Session and restoration integrity

The core library keeps one vault across a conversation. The browser demo gives
each separately masked prompt a fresh vault, so a second example cannot inherit
the first person's identity. These are different session boundaries by design.

## Allocation and persisted mappings

An original has one surrogate per entity type; every surrogate identifies exactly
one mapping. A loaded vault rejects duplicate original/type pairs and duplicate
surrogates, including identical repeated entries. Duplicate JSON object keys are
also errors. Version 1 and unversioned legacy vaults are supported; other versions
are rejected. Originals and surrogates must be nonempty UTF-8 text and must differ.
Returned mapping objects are immutable.

Realistic generation has 576 names, 72 organization names and 800 fictional phone
numbers. After a pool is exhausted, numbered placeholders continue the sequence.
An unchanged original is skipped. A custom generator gets at most 1,024 attempts
to produce a usable replacement; failure does not advance counters or insert a
partial mapping. This bounds collision retries, not the runtime of arbitrary
user-supplied generator code.

## Persistence

`Vault.save()` and CLI file output write a temporary sibling, flush it, then
replace the destination. A failed write keeps the previous destination intact.
The new file is mode 0600 on POSIX; symlink destinations are refused. The CLI also
checks for resolved-path and hardlink aliases between its inputs, output, names
files and vault. It saves the recovery vault before writing masked output.

These are separate file replacements, not a transaction across two files. If
output writing fails after vault saving, the saved vault still contains the
recovery mappings. This does not lock concurrent writers, encrypt plaintext,
erase old storage blocks, or guarantee durability across a whole-machine power
failure. Use the optional encryption API and application-level locking when needed.

## JSON restoration

Plain-text restoration uses exact surrogate substrings. JSON restoration first
decodes string values, matches the same trie, then escapes restored originals.
It leaves object keys and non-string values alone. A literal backslash plus
`u27e8` stays literal; an actual Unicode escape decodes before matching. Mixed
escape spellings, uppercase hex digits, escaped quotes and surrogate pairs work
across chunk boundaries. Unmatched text retains its original serialized spelling.

Between chunks, retained text is limited to a possible surrogate prefix and an
incomplete escape. Container state takes one flag per nesting level. This is not
a JSON validator: incomplete or malformed input is best effort and is not repaired.
Tolerant plain-text matching handles Unicode case folding but leaves conflicting
folded identities unchanged. Streaming matching remains exact after JSON decoding.

## Browser boundary

The demo loads the pinned Pyodide 0.26.4 runtime from jsDelivr on the first mask.
Its worker follows [Pyodide's worker interface](https://pyodide.org/en/0.26.4/usage/webworker.html).
Package source and fonts come from the site's own origin. Prompts, known names,
vaults and replies are processed locally. Downloads happen only when selected.
The demo's reply is fictional; it does not call a model or perform an action.

The prompt limit is 100,000 UTF-16 code units; known names are limited to 10,000.
Oversize input is rejected before transfer to Python. The display shows at most
20,000 units of masked text and 100 mappings; downloads contain the complete
masked result and vault. Hidden originals are not inserted in the table until
Reveal originals is selected.

Cancel terminates the worker. Clear also removes the displayed input, result and
vault, and releases the application's references to them. It cannot erase files
already downloaded or promise forensic erasure of browser memory. Changing input
stops active work and requires another mask before a reply can be simulated.
A failed replacement preserves the previous displayed result, marked as belonging
to the earlier input.

## Checks

`tests/test_vault_integrity.py` exercises pool exhaustion, malformed saved state,
immutability, write failure and POSIX permissions. `tests/test_cli_persistence.py`
checks alias protection and ordering of writes. `tests/test_json_lexing.py` compares
streamed output against an independently parsed JSON value tree over mixed escape
spellings and arbitrary chunk boundaries.

From `web/`, `npm ci && npm run build && npm run test:browser` runs the real Python
package in Chromium and Firefox. Browser scenarios cover prompt isolation,
offline reuse after loading, clear during streaming, denied storage, failed
worker loading, retry, cancellation, bounded previews, complete downloads,
keyboard activation, accessibility and CSP. They require the pinned runtime CDN
and Playwright's Chromium/Firefox engines. No API credentials or model calls are used.
