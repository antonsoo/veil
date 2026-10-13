# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## Unreleased

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
