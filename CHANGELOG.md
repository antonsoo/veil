# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## Unreleased

### Combining marks at fuzzy restoration boundaries

- Keep Unicode nonspacing, spacing and enclosing marks attached to adjoining
  words in tolerant matching. A recased NFD accented name could previously
  restore its unaccented surrogate prefix and attach the remaining accent to
  a private original. Preserve input spelling without accent normalization.
- Keep exact substring restoration and exact streaming unchanged. This is a
  conservative boundary correction, not full Unicode word segmentation.
  Retain authored native CLI and real SDK transport controls under
  `studies/restore-marks`; no live provider call or registry release is included.

### Header context without synthesized source

- Supply Authorization/Proxy-Authorization names through field context instead
  of prepending and trimming a label. A configured name backend could consume
  that synthetic prefix, drop Basic/Bearer schemes and create an invented vault
  entry. Detector spans now refer to the original value. Preserve existing
  credential grammar, sensitive-key rejection and raw-header behavior.
- Retain six direct/native controls and 24 real SDK serialization/restoration
  paths, including asynchronous, streamed and tool replies, under
  `studies/header-field-context`. No provider calls or PyPI release are included.

### Complete YAML flow scalars

- Protect complete quoted and plain credential values at supported YAML mapping
  keys. Doubled apostrophes, literal backslashes, plain phrases and wrapped
  continuations previously exposed suffixes or passed through unchanged.
- Keep raw value spelling and source line breaks in one vault entry. Comments,
  neighboring mappings and empty/structured values retain their boundaries;
  malformed quotes stop before a sibling field. No YAML runtime dependency
  was added. This remains a bounded text recognizer with documented ambiguity.
- Retain native PyYAML/ruamel.yaml emissions, independent loader checks, actual
  SDK requests and offline browser downloads in `studies/yaml-flow-credentials/`.
  These are local source changes, separate from the hosted demo and PyPI.

### YAML block credentials

- Recognize indented literal/folded bodies for supported credential mapping
  keys. Literal indicators such as `|` were previously masked as passwords
  while their body stayed visible; folded bodies were left unchanged.
- Keep block headers, required indentation, line breaks at the boundary and
  neighboring configuration readable. Internal text, extra indentation and
  nested PII are one opaque raw span, with exact restoration.
- Support automatic or explicit indentation, either chomping-indicator order,
  compact sequences, BOM-prefixed input and LF/CRLF/CR. Recognized empty block
  headers no longer masquerade as protected values. Native emitter, parser,
  transport and collateral evidence is retained in `studies/yaml-credentials/`.
  No runtime dependency was added; this remains a bounded recognizer.

### Opaque private-key blocks

- Give an explicitly recognized private-key block the same enclosing-value
  priority as JWTs and HTTP credentials. A higher-confidence email/card/IBAN/IP
  fragment previously displaced the block in the default pipeline while its
  body remained visible. Native GnuPG could import and sign with one such
  masked export.
- Preserve OpenPGP armor metadata before the base64 body of a truncated export.
  Comments can contain arbitrary text; they no longer stop the body scan at an
  email's `@`, Unicode or punctuation. Existing non-PGP body handling remains.
- Retain native key-recovery/signature oracles, actual SDK transport summaries,
  CLI/restoration and compatibility evidence in `studies/private-key-blocks/`.
  Generated private keys and baseline request bodies remain local; published
  receipts contain hashes and outcomes. No runtime dependency was added.

### Explicit credential fields

- Recognize complete values in supported password, API-key, client-secret and
  OAuth-token assignments without entropy or provider-prefix requirements.
  Quoted values preserve raw escapes and phrases; bounded unquoted values
  preserve field names and delimiters. Explicit Authorization handling and
  enclosing private-key blocks retain their previous coverage.
- Add an optional `field_name` hint to `Masker.mask` and `find_entities`, and a
  `FieldDetector` protocol for opt-in contextual candidates. SDK tool histories
  retain immediate decoded string keys, without changing numeric values,
  duplicate JSON fields or unrelated argument spelling. Configured detectors,
  source reservations, vault rollback and restoration checks still apply.
- Retain synthetic before/after SDK, CLI and browser evidence, scaling costs
  and a complete collateral review in `studies/credential-fields/`. Raw source
  variable assignments remain ambiguous; the study records seven such false
  positives rather than presenting all new detections as secrets.

### Known-value audit boundaries

- Keep detected fragments wholly inside exact known original/surrogate
  occurrences out of new-PII findings. Restored credential URLs no longer invent
  new mailbox/IP findings; known-original leaks remain reported. Partial overlaps,
  outside occurrences and candidates spanning multiple known literals remain
  eligible. Containment includes overlapping occurrences of each literal without
  changing the leak report's established repetition policy.
- Honor `detectors=[]` as an empty new-PII selection. Omitted/None still selects
  defaults, and original-value checks remain active.
- Retain native public-API/CLI before/after evidence, boundary controls and fresh
  dependency-free wheel installations in `studies/audit-boundaries/`.

### Original-value audit responsiveness

- Index long originals by a bounded prefix before checking their complete value.
  Varied-length credential URLs no longer trigger large substring copies at
  every potential starting character. Equal-length prefix collisions share an
  exact hash lookup. Matching, offsets, ordering and per-value overlap semantics
  stay exact; cached indexes follow additions and transaction rollback.
- Retain controlled baseline/current CLI and installed-wheel replays in
  `studies/leak-audit/`, including shared-prefix and ordinary email controls.
  The core gains no runtime dependency.

### Explicit HTTP authorization credentials

- Mask complete Basic/Bearer token values in `Authorization` and
  `Proxy-Authorization` fields independently of entropy, length and word
  heuristics. Preserve padding and token punctuation in the vault; leave field
  names and schemes readable. Raw, quoted JSON/dict and curl header spellings
  use the same rule.
- Preserve an immediate header key's context in structured tool input and
  JSON-string function arguments, including escaped key names. Raw argument
  numbers, duplicate keys and unrelated spelling remain unchanged. Source
  reservations, failed-request rollback and exact restoration still apply.
- Retain native HTTPX BasicAuth captures, actual SDK transports, installed
  packages, corpus review and offline browser evidence in
  `studies/http-authorization/`. Credentials are synthetic; the rule does not
  authenticate them. No runtime dependency was added.

### Whole compact JWT masking

- Mask supported compact JWTs as one credential. Generic entropy detection
  previously replaced header/signature fragments while leaving base64-encoded
  customer names, emails and other identity claims visible.
- Decode only a bounded JOSE header. Claims remain opaque; signature validity,
  expiration and external key services do not affect masking. Signed and
  unsecured forms, optional `typ`, padded compatibility spellings and trailing
  sentence punctuation retain exact restoration.
- Retain native PyJWT/signature oracles, actual SDK captures, CLI vaults,
  malformed/large-input checks and corpus evidence in `studies/jwt-claims/`.
  The core remains dependency-free; PyJWT is a development-only oracle.

### Temporary AWS access key IDs

- Recognize `ASIA` STS access key IDs alongside `AKIA`, with the existing
  20-character shape and whole-token boundaries. Temporary IDs previously
  depended on generic entropy/word heuristics and could leave the prompt intact.
- Retain seeded key-shape coverage, CLI/vault restoration and real SDK request
  captures in `studies/sts-key-ids/`. Recognition does not validate a credential
  or guarantee coverage of session tokens or other unrecognized formats.

### IDNA mailbox domain boundaries

- Consume all four IDNA label separators before validating a mailbox domain.
  Ideographic, fullwidth and halfwidth dots previously caused missed addresses
  or left a private domain suffix visible after a partial replacement.
- Preserve original Unicode spelling in entities and vaults. Equivalent domain
  spellings remain distinct reversible values; terminal separators stay prose
  punctuation. Invalid suffixes cannot turn into shorter mailbox matches.
- Retain actual SDK request, CLI/vault and offline browser reproductions in
  `studies/idna-mailboxes/`. This is syntactic recognition, without DNS or
  deliverability checks; adjacent prose can still be ambiguous.

### Anthropic retrieved search results

- Mask `search_result` source labels, titles and each inline text block,
  directly in messages and inside tool results. Previously this retrieval
  form bypassed masking even for recognized sensitive values.
- Visit list, tuple and generator content before transport. Keep result and
  block order, citation/cache settings, source-space citation quotes and
  exact retained assistant replay. Collisions and iterator failures use
  request-level vault rollback.
- Retain the 36-workflow actual SDK/mock HTTP reproduction in
  `studies/search-results/`. No live provider call or package release.

### Complete mailbox masking

- Mask complete dot-atom local parts containing valid ASCII punctuation,
  supported international local parts, quoted local parts and Unicode or
  punycode domains. The previous detector could leave an identity prefix in
  outgoing prompts or pass the entire address through unchanged.
- Bound candidate scans and check full local/domain lengths. Invalid long
  tokens cannot become shorter mailbox matches; quoted internal `@` characters
  stay inside the local part. Retain original spelling for exact restoration.
- Keep real SDK, CLI, retained contact/log/code corpus and offline Pyodide
  evidence in `studies/email-boundaries/`. Detection remains syntactic:
  templates and adjacent code can be ambiguous, and this is not a complete
  RFC parser or a deliverability check.

### OpenAI iterable inline text

- Visit tuple and generator content parts before SDK serialization can expose
  unmasked text. Cover Chat text/refusals, Responses input items, message and
  tool-output parts, and reasoning summaries while retaining opaque references
  and encrypted reasoning content.
- Materialize Responses input iterators before the SDK call. Top-level
  generators were previously rejected by the SDK; this supported lowering is
  distinct from the reproduced privacy bypasses in other non-list arrays.
- Keep request-wide surrogate collision checks, vault rollback on failed
  iteration and exact retained provider-item replay. One-shot iterator
  consumption cannot be undone. Retain actual SDK captures and reproduction
  commands in `studies/iterable-text/`.

### Anthropic tool-input serialization

- Mask strings inside tuples before the SDK serializes them as JSON arrays.
  Preserve ordinary JSON primitive values and caller-owned input objects.
- Reject detected sensitive keys, non-string object keys, nonfinite numbers
  and opaque custom values during fresh tool-input preparation. Domain models
  must be explicitly serialized to plain JSON before masking; passing them
  untouched allowed the SDK to expose their hidden strings later.
- Keep tuple literals inside request-wide collision checks and roll back failed
  preparation before transport. Retained provider-owned input still replays
  exactly; edited keys are checked as fresh input. Real SDK/mock-transport
  captures and installed-package evidence are in `studies/tool-input-trees/`.

### Chat Completions history text

- Mask outgoing refusal fields and refusal content parts, legacy function-call
  JSON arguments, and custom-tool input. These previously bypassed masking and
  could put detected raw contacts into the SDK's request body, including when
  edited or reconstructed assistant history was resent.
- Restore refusal, legacy function-call arguments and custom-tool input in
  complete replies, retaining exact unchanged provider history for replay.
  Newly covered input text participates in request-level collision detection
  and rollback before transport. Legacy arguments reuse the JSON path that
  preserves number precision, duplicate keys and unrelated syntax.
- Retain 54 before/after real SDK transport workflows using synthetic replies
  and contacts in [the reproduction study](studies/chat-text-fields/README.md).


### Batch reservation performance

- Index reserved source text by its characters so each candidate surrogate only
  searches sources that could contain it. Preserve normalized literal matching,
  source boundaries, late nested reservations and failed-batch rollback.
- Retain before/after timings, exact output/vault comparisons and actual SDK
  serialization checks in `studies/batch-reservations`. The constructed
  8,000-message batch improves from 9.87 s to 0.51 s on the recorded host;
  this is not a general linear-time or detector-accuracy claim.

### Anthropic inline documents

- Mask document titles, context, plain-text sources and custom-content text,
  including documents nested inside tool results. Traverse SDK-supported content
  iterables without changing binary sources, references or citation/cache controls.
- Preserve provider citation quotes and locations in masked-source coordinates;
  answer text remains restored and retained assistant history replays unchanged.
- Retain 36 actual SDK before/after request captures with synthetic contacts,
  across sync/async calls and both streaming interfaces, in `studies/anthropic-documents`.

### Complete IPv6 literals

- Mask IPv6 addresses with embedded IPv4 notation and scope IDs as one value;
  do not expose the dotted suffix or interface name after masking a prefix.
  Preserve the complete original spelling for exact restoration.
- Treat mapped IPv4 loopback/reserved addresses consistently in dotted and
  hexadecimal spelling. Recognize assigned NAT64 and SRv6 prefixes that fall
  inside the standard library's broad reserved-space classification.
- Validate the complete candidate before accepting it. Reject malformed
  dotted tails/scopes without extracting an embedded IPv4 fragment.
- Retain native-parser checks, public-text replay and actual CLI, SDK and
  browser evidence in `studies/ip-literals`. Recognition is lexical; scope IDs
  are not resolved against the host's interfaces.

### Credential-bearing URLs

- Mask complete AWS/GCS signed URLs, Azure Storage SAS links and CloudFront
  signed links, including custom domains. Recognize OAuth fragment tokens and
  sensitive parameter names after one percent-decoding pass. Preserve the
  original URL spelling for exact restoration.
- Require companion fields for generic `sig`/`Signature` parameters. Ordinary
  signature parameters and empty credential fields do not match the new rules.
- Retain offline SDK-generated synthetic examples, before/after CLI and SDK
  transport captures, ordinary-link controls and browser evidence in
  `studies/credential-urls`. This recognizes formats; it does not authenticate
  links or establish coverage of every credential scheme.

### Complete project-key masking

- Recognize complete `sk-proj-` and `sk-svcacct-` shaped secrets, including
  long URL-safe bodies and internal dashes/underscores. Previously the generic
  entropy fallback could miss them or mask only a fragment. Enclosing tokens
  take priority over supported key prefixes nested in their bodies.
- Retain synthetic before/after SDK request checks and a public-text
  compatibility replay in `studies/secret-formats`. Recognition is a masking
  heuristic, not credential validation or a provider key-format guarantee.

### Message boundaries and history identity

- Restore Anthropic text helpers per content block, including asynchronous
  streams and partial consumption. Fragments in separate blocks cannot combine
  into a restored private value.
- Preserve each retained content/message object's original provider reply when
  different replies restore to the same content. Reject ambiguous reconstructed
  history before transport, with request masking rolled back.
- Retain JSON nulls in replay fingerprints, mask user messages independently of
  assistant history, and snapshot originals so callers cannot mutate the cache.
- Keep synthetic before/after SDK HTTP captures in `studies/message-boundaries`.
- Refuse content-only replay once cache eviction has removed the evidence of
  uniqueness. An old turn cannot silently inherit a later equal turn's original.
  Retained unchanged objects, including blocks in rebuilt content lists, still
  replay their own originals.

### JSON tool history

- Restore complete tool replies by rewriting only changed string values. Numeric
  precision, large exponents, duplicate members and untouched spelling are no
  longer lost when another argument contains a surrogate. Tolerant restoration,
  best effort for malformed replies and exact provider-history replay remain.
- Decode JSON string values before masking OpenAI Chat Completions and Responses
  function-call arguments. Unicode escapes can no longer conceal a detected
  email or known name from the outbound masking pass.
- Preserve unrelated JSON spelling and numeric precision; reserve decoded
  placeholder literals together. Reject malformed arguments and detected
  sensitive object keys before transport, rolling back request preparation.
  Numeric values retain their types and remain outside string masking.
- Retain real SDK before/after captures with synthetic contacts in
  `studies/json-tool-arguments`. Existing provider-history replay stays exact.

### Surrogate identity

- Reserve literal source tokens, case/whitespace variants and known original
  values during replacement allocation. A documented placeholder no longer
  becomes an email address during restoration, and a realistic fake does not
  reuse another address or name present in the supplied source.
- Add `Masker.mask_many` for related raw texts. Rejected batches roll back vault
  mappings, counters and restore caches. Exact and tolerant restoration check
  the complete prepared batch; established mappings are never reassigned.
- Validate SDK request preparation before transport, across separate fields,
  for sync and async create/stream entry points. Attribute-based input objects
  are copied when updated so rejection leaves their source text available.
- Retain before/after CLI and SDK captures, public-corpus compatibility and
  actual browser downloads in `studies/surrogate-collisions`.

### Measured on real text

- A study, `studies/real-text/`: veil on phone numbers and email addresses as
  people typed them into OpenStreetMap in 46 cities, and on 2.6 million words
  of system logs, CI logs and source code. The released 0.4.4 masked 66% of
  phone numbers written with a `+`, and in technical text made 11 false
  maskings per 1,000 words. The detector changes below came out of it.

### Changed

- **Phone.** A number written with a `+` is found in any grouping. The
  detector reads the calling code and checks that the national number has a
  length that country uses (a table generated from libphonenumber's metadata;
  veil still has no dependencies). `+33 1 23 45 67 89`, `+49 30 12345678` and
  `+81 3-1234-5678` were all missed before. A `+` followed by digits that
  start with no assigned code, or have the wrong length, is no longer a
  number; a signed decimal (`m=+32.035815963`) never is.
- **Secrets.** The low-confidence heuristic for random tokens no longer masks
  tokens that read as words: file paths, test names, package paths, request
  ids. Short tokens are held to an entropy their length can reach, so random
  keys of 20 to 24 characters are found far more often.
- **Cards.** The Luhn checksum is no longer enough. A candidate needs an
  issuer's range and length, or a card's printed grouping, and must not be
  part of a longer token. Unformatted digits with no known issuer are no
  longer reported at reduced confidence. The issuer table gains UnionPay,
  Maestro, Mir, RuPay and others.
- **IP addresses.** Loopback, the unspecified address and reserved space
  (`127.0.0.1`, `0.0.0.0`, `::`, `::1`, netmasks) are left alone, and so is the
  version in a browser's product token or a Windows package name.
- **Address (opt-in).** Numbered streets (`38 West 32nd Street`) and a
  compass point after the suffix (`55 Bloor Street West`).
- The synthetic corpus generator keeps to addresses a host can have. Fourteen
  documents change by one IP address each; regenerate `benchmarks/corpus.jsonl`.

### Fixed

- Finite realistic-name, organization, and phone pools now continue with numbered
  placeholders instead of hanging. Allocation rejects an unchanged original and
  bounds retries from custom generators. Failed allocation leaves the vault intact.
- Saved vaults reject conflicting identities, duplicate JSON keys, invalid text,
  and unsupported versions. Mapping objects are immutable so callers cannot
  invalidate restoration indexes. Unversioned legacy vaults remain readable.
- Vault and CLI output writes use temporary sibling files, atomic replacement,
  and owner-only permissions on POSIX. The CLI saves the recovery vault before
  emitting masked text, rejects input/output/vault aliases, and reports I/O errors.
- Streamed tool-argument restoration decodes actual JSON string values, including
  mixed Unicode escapes and surrogate pairs. Literal backslashes, object keys,
  numbers, and unmatched spellings remain intact. Ambiguous tolerant spellings
  are left unchanged instead of choosing an identity.

### Browser demo

- Each prompt gets a fresh vault. Python runs in a cancellable worker; input edits,
  cancellation, and clearing cannot resurrect an earlier reply. Clear removes
  the displayed prompt, vault and reply and terminates the Python worker.
- Runtime-load failures can be retried. Denied browser storage does not prevent
  startup. Hidden originals are omitted from the rendered table, not just blurred.
- Input and DOM previews are bounded, with complete masked-text and vault downloads.
  Added reproducible Chromium/Firefox workflows and corrected light-token and dark
  button-hover contrast. Updated the affected source-map-js development dependency.

### Maintenance

- The uv lock now resolves stable spaCy 3.8.16 and Pydantic 2.13.5 instead of
  development/beta versions selected by a permissive local resolver setting. The
  project explicitly prefers stable releases. A real spaCy pipeline regression runs
  on Python 3.10 and 3.14 without a model download; typechecking also respects the
  optional backend exclusion when the extra is installed.

## [0.4.4] - 2026-10-03

### Compatibility

- Python 3.13 and 3.14 are tested and declared. CI runs the suite on 3.14
  as well, and the package's classifiers list both versions. The code is
  unchanged: with the newest release of every dependency, the tests pass on
  3.14 and on 3.15's release candidate.

The rest of this release is in the web demo; the package is otherwise
unchanged.

### Changed

- The page's fonts are served by the page itself. They came from Google Fonts,
  the one request the page made to another origin; the same font files (every
  subset, as Google serves them to a current browser) are now in
  `web/src/fonts/`, with their SIL Open Font License texts. Nothing looks
  different: screenshots before and after match. The page now loads with
  every other host blocked except the CDN that Pyodide, the Python runtime, comes from.

### Security

- The built page carries a Content-Security-Policy. Scripts, styles, fonts and
  workers load from the page's own origin only, and `connect-src 'self'` has
  the browser refuse to send what you give the page to any other host, even
  for a script injected through a bug in how the page renders a file. Inline
  event handlers and `eval` are not allowed. The one other origin allowed is
  the CDN that Pyodide, the Python runtime, is loaded from. Every control was
  exercised in Chromium and Firefox with a listener for policy violations:
  none.

### Accessibility

- Checked with axe-core (WCAG 2.1 A and AA, and its best-practice rules) in light and dark,
  at desktop and phone widths: no findings now. The hint under the
  input was dimmed by opacity to 3.2:1; the page has a `main` landmark.

## [0.4.3] - 2026-10-02

### Security

- The `vault-crypto` extra accepted `cryptography` from 42.0.0, a release with
  published advisories (as has every release before 50.0.0). An ordinary
  install already got the current version; one held back by another
  package's constraints could get an old one for the code that encrypts the
  vault. The minimum is `cryptography>=50`. `pip-audit` reports nothing for
  the locked versions or for the minimum ones.

## [0.4.2] - 2026-10-02

### Added

- `veil mask --name`, `--org`, `--location` (each repeatable) and
  `--names-file` (one name per line; `org:` and `location:` prefixes). The
  library's most reliable way to mask a name, the names your application
  already knows, had no way in from the command line: `veil mask` on the
  bundled support ticket left "Jordan Alvarez" in the output, and the README's
  sample skipped that line. The sample now shows the whole output.

## [0.4.1] - 2026-10-02

The command line, used the way a shell uses it.

### Fixed

- `veil mask ticket.txt --vault v.json > masked.txt` on Windows. Python
  before 3.15 gives a redirected stdout the system's code page (cp1252 in the
  west), which has no `⟨` or `⟩`, so the command stopped with a
  `UnicodeEncodeError` traceback at the first surrogate; UTF-8 text on stdin
  was read as mojibake for the same reason. Standard input and output are
  UTF-8 now, like the files. (Reproduced on Linux by giving the pipes that
  encoding with `PYTHONIOENCODING`; the tests do the same for cp1252, cp437
  and ASCII.)
- `cat ticket.txt | veil mask --vault v.json`, the pipeline in the CLI's own
  description, failed with "the following arguments are required: input":
  stdin needed an explicit `-`. A command with no file reads stdin.
- Line endings pass through. A CRLF file came out with LF endings.

### Added

- `-o` / `--output FILE` for `mask` and `restore`, for shells whose `>`
  re-encodes program output (Windows PowerShell).

## [0.4.0] - 2026-10-01

The SDK wrappers had only been run against fakes shaped like the SDKs. Run
against the real ones (anthropic 1.8.0, openai 3.19.2) over a mocked HTTP
transport that answers in the APIs' wire format, they masked every request
correctly and let surrogates through in several replies.

### Fixed

- **`create(..., stream=True)` returned the SDK's raw stream, unrestored.**
  That is the usual way to stream Chat Completions and a supported one for
  Messages and Responses. The request was masked and every chunk of the reply
  came back with its surrogates (`'Mail ⟨EM'`, `'AIL_1⟩ now.'`). `create` and
  `create_response` now return the same restored stream as `stream` and
  `stream_response`.
- **Anthropic: iterating a stream's events restored only the API's text
  deltas.** The SDK also yields its own events, and those were passed through:
  `text` (the delta and the text so far, which is what
  `if event.type == "text": print(event.text)` prints), `input_json`, the
  content block on `content_block_stop` and the message on `message_stop`. All
  are restored now, and tool-input JSON is restored as its fragments arrive
  instead of only in the final message.
- **Anthropic: text held back at the end of a stream was dropped from the
  events.** A reply ending on something that could begin a surrogate (`... or
  ⟨EM`) lost those characters when iterating events (`text_stream` had them).
  They are released before the block's `content_block_stop`, as one more
  delta event of the SDK's own type.
- **OpenAI: `n > 1` choices shared one restorer.** Their chunks interleave, so
  two choices each cut inside a surrogate came out as
  `'First: ⟨EMAILAIL_1⟩.'` and `'⟨EMSecond: _2⟩.'`. Each choice has its own
  restorers now, for content, refusal and every tool call.
- **OpenAI: held-back text arrived after the choice had finished.** It was
  emitted after the `finish_reason` chunk and after the usage chunk of
  `stream_options.include_usage`. It now comes in the chunk that carries the
  `finish_reason`. A stream cut off without one still releases it at the end.
- **Async clients were mishandled silently.** `AnthropicVeil(AsyncAnthropic())`
  masked the request and returned the SDK's coroutine untouched: awaited, a
  reply full of surrogates and no error. `OpenAIVeil(AsyncOpenAI())` failed
  with `AttributeError: 'coroutine' object has no attribute 'choices'`. Each
  wrapper now refuses the other kind of client and names the right one.

### Changed

- The `openai` extra asks for openai 1.66 or newer, the first release with
  the Responses API. 1.50 was declared, and `create_response` failed on it
  with `AttributeError: 'OpenAI' object has no attribute 'responses'`. The
  new SDK tests pass on anthropic 0.40.0 and openai 1.66.0 (the declared
  minimums) as well as on the current releases.

### Added

- `AsyncAnthropicVeil` and `AsyncOpenAIVeil`: the same wrappers for
  `AsyncAnthropic` and `AsyncOpenAI` (`await client.create(...)`,
  `async with client.stream(...)`, `async for`), sharing the event and chunk
  restorers with the sync ones.
- Refusal deltas in a Chat Completions stream are restored like content.
- Stream wrappers are context managers where the SDK's are, add
  `get_final_text()` and `current_message_snapshot` for Anthropic, and hand
  anything they don't wrap (`close()`, `response`) to the SDK object.
- `tests/test_sdk_anthropic.py` and `tests/test_sdk_openai.py`: 30 tests over
  the real SDKs, sync and async, including a property test that cuts a reply
  at arbitrary points.

## [0.3.2] - 2026-10-01

### Fixed

- Large inputs. Masking, restoring and auditing compared every value with
  every other one, so the time grew with the square of the input: a 270 KB
  export holding 16,000 values took 12 s to mask and 35 s to restore. The same
  export now masks in 0.65 s and restores in 0.22 s, and the time grows in
  step with the size.
- Three detectors could stall on long repetitive text. A 40 KB run of `a.a.a.`
  held the URL detector for about 3 s, and four times as long for every doubling;
  a text full of unterminated key headers, or of dates near "born", did the
  same to the secret and date-of-birth detectors. All three are linear now and
  find exactly what they found before.
- `restore_tolerant` scanned text it had already restored. With realistic
  surrogates, a real value that reads like another value's fake (a customer
  really called "Blair Alder" while "Blair Alder" stands in for someone else)
  was restored a second time, into the wrong person. Restoring is one pass
  now.
- Loading a vault file of the wrong shape (a list, a mapping without its
  `original`, a non-string value) raised `AttributeError`, `KeyError` or
  `TypeError`. It raises `VaultError` and says which entry is wrong.

### Changed

- Values are numbered in reading order: the first email address in a text is
  `⟨EMAIL_1⟩`. Until now the last one was. Vaults already saved are unaffected.
- A placeholder the model re-cased is restored even when it touches other
  text (`host=⟨ipv4_1⟩:8080`, `x⟨ipv4_1⟩y`). Fake names still have to stand as
  words of their own, so `Avery Alderman` is never read as `Avery Alder`.

## [0.3.1] - 2026-10-01

### Added

- Published to PyPI as `veil-pii`: `pip install veil-pii`, with the extras
  `veil-pii[anthropic]`, `[openai]`, `[spacy]` and `[vault-crypto]`. The README's
  images and links are rewritten to absolute URLs at build time so they work
  on the project page.
- `veil --version`.

## [0.3.0] - 2026-09-30

### Added

- OpenAI Responses API support: `OpenAIVeil.create_response` and
  `stream_response` mask `instructions` and every message, `function_call`,
  `function_call_output` and custom tool item in `input`, and restore message
  text, refusals, tool-call arguments and reasoning summaries in `output`
  (`response.output_text` included). Stream deltas are restored as they
  arrive; output items fed back as `input` are replayed exactly as the model
  produced them. Tested against the `openai` SDK's own response and event
  types.

### Fixed

- At the end of a Chat Completions stream, text held back because it might
  begin a surrogate came out as a plain dict, so code reading
  `chunk.choices[0].delta.content` failed on it. It is now a copy of the last
  real chunk, with only the held-back text in its delta.

## [0.2.0] - 2026-09-30

### Security

- `AnthropicVeil` sent real values back to the API: the `tool_use` input it
  restored for the application to execute was not re-masked when the
  assistant turn was resent as history. `tool_use` input is now masked, and
  both wrappers replay each assistant turn they restored exactly as the model
  produced it (`ReplayCache`), so restored values never leave in a later
  request.

- A PEM private key (`-----BEGIN ... PRIVATE KEY-----` through its END line,
  or through its body when truncated) was not masked at all; it is now one
  `SECRET` entity.
- Credentials in non-HTTP URLs were missed: in
  `postgres://admin:hunter2@db.internal/app` only `hunter2@db.internal` was
  caught, as an email address. Userinfo credentials are now detected in URLs
  of any scheme (`postgres`, `redis`, including the password-only
  `redis://:secret@host`, `mongodb+srv`, `amqp`, ...).

### Fixed

- A dotted quad labelled as a version (`version 10.2.14.3`, `v2.4.1.0`,
  `build 1.0.0.7`) was masked as an IPv4 address.
- Resent assistant turns no longer differ from what the model produced
  (re-masking a restored turn gave model-written, PII-looking text a fresh
  surrogate). A changed earlier turn restarts the prompt cache and, on
  current Claude models, invalidates the signatures of later thinking blocks.
- OpenAI tool-call arguments whose surrogate the model wrote with `\uXXXX`
  escapes were not restored. Complete arguments are parsed and restored value
  by value; streamed fragments go through a JSON-string-mode `Restorer` that
  recognizes the escaped form and escapes restored originals, so the
  arguments stay valid JSON.
- Install hints pointed at `veil-pii` on PyPI, where the package isn't
  published; they now use the Git URL or name the actual dependency.

### Added

- `veil.restore.restore_json_text` and `Restorer(vault, json_string=True)`.
- `veil.integrations._common.ReplayCache` (bounded, 10,000 entries by default).

## [0.1.0] - 2026-09-24

### Added

- Core detectors: email, phone (NANP or `+`-prefixed international only,
  with a context guard against order/invoice/ticket/ZIP numbers), payment
  card (Luhn + issuer ranges), IBAN (mod-97), US SSN (consistent
  separators required, to avoid matching a ZIP+4 code), IPv4/IPv6, URLs
  with embedded credentials, API keys/secrets (known prefixes + entropy
  heuristic), date-of-birth (context-gated), and an opt-in US street
  address heuristic.
- Pluggable name/org/location backends: a first-class "known entities"
  backend and an optional spaCy backend.
- Configurable surrogates: placeholder tokens and realistic
  format-preserving fakes (names, `example.com` emails, 555-01xx phone
  numbers, Luhn-valid test card numbers).
- Exact and tolerant restore, plus a streaming, trie-based `Restorer`
  proven equivalent to non-streamed restore under arbitrary chunking via
  Hypothesis property tests.
- Leak audit: detects original values that leaked into outgoing text and
  new PII a model introduced.
- In-memory vault with JSON serialization and optional Fernet encryption.
- `veil` CLI: `mask`, `restore`, `audit`.
- Thin Anthropic and OpenAI SDK wrapper integrations, including streaming.
- Synthetic, labelled evaluation corpus and per-detector precision/recall
  report, plus a benign-text category measuring false positives per 1,000
  words on ordinary numeric text (dates, order/invoice/ticket IDs, ZIP+4,
  tracking numbers, prices, room/build numbers).
- Browser demo (`web/`, Vite + TypeScript) running the real package via
  Pyodide, deployed to GitHub Pages.
