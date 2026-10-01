# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
