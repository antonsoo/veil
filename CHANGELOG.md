# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-09-24

### Added

- Core detectors: email, phone (E.164/NANP/international), payment card
  (Luhn + issuer ranges), IBAN (mod-97), US SSN, IPv4/IPv6, URLs with
  embedded credentials, API keys/secrets (known prefixes + entropy
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
  report.
