# Masking the email left a usable private key

At baseline `0e3052c`, the default `Masker` replaced an email in a native GnuPG
private-key export's `Comment` header and left its encoded packet body visible.
The masked output imported as the original private key in a separate temporary
keyring. That recovered key signed a challenge, and GnuPG verified its signature
against the expected fingerprint.

The secret detector had recognized the whole block at confidence 0.97, then
suppressed its own nested entropy candidates. Global overlap resolution later
preferred the email at 1.0 and discarded the enclosing block. The remaining body
received no replacement. Testing `SecretDetector.find()` alone missed this;
the failure occurs when composing the default detectors.

```text
BEGIN private key              BEGIN private key
Comment: owner@example.org --> Comment: <EMAIL>
[encoded private packets]     [same usable private packets]
END private key                END private key

Corrected: the entire recognized block becomes one reversible SECRET.
```

The correction gives an explicit private-key block enclosing-value priority,
matching JWTs and explicit HTTP credentials. Equal-confidence candidates prefer
the longer span. It also retains OpenPGP armor headers before scanning a
truncated export's body. Previously an email's `@`, Unicode or punctuation in
that metadata could stop the scan before the body.

## Native evidence

[`generate.py`](generate.py) creates **one unused synthetic Ed25519 signing
key**, exports it with six native GnuPG comments, then derives missing-footer
and partial-body variants. The 18 inputs share that key; they are not 18
independent keys or a production corpus. Comments cover ordinary text, an
email, IPv4, card-shaped digits, an example IBAN and a credential field.

| Native/derived input | Whole mask before | Whole mask after | Usable key from masked text before | After |
| --- | ---: | ---: | ---: | ---: |
| Complete export | 2/6 | 6/6 | 4/6 | 0/6 |
| Footer removed | 2/6 | 6/6 | 2/6 | 0/6 |
| Body cut after three lines | 2/6 | 6/6 | 0/6 | 0/6 |

The independent oracle retains only base64-looking lines from its input,
rewraps them as armor, imports them into a fresh keyring, signs a fixed
challenge, and requires GnuPG's valid-signature status for the original
fingerprint. A changed comment or missing footer therefore cannot hide usable
private packets. All 12 complete-payload source inputs pass that oracle. The
six partial-body sources do not; that is an observation of this GnuPG workflow,
not a claim that every possible partial-key recovery is impossible.

[Before](results/before.json) and [after](results/after.json) retain input hashes,
fingerprints, exact spans/provenance, output hashes, import/sign/verify exit
codes and outcomes. The same input bytes were replayed on both sources.
**No generated private-key body, vault original or baseline model request body
is published.** The native inputs stay in the explicitly chosen local fixture
directory. Regeneration produces a different unused key and equivalent
workflows, rather than identical cryptographic bytes.

The public `Masker`, actual CLI/vault and incremental `Restorer` all restore
the exact input on 18/18 cases, before and after; incremental checks use chunk
sizes 1, 2, 7 and 31. Restoration alone did not prove confidentiality.

Actual Chat Completions, Responses and Anthropic SDKs each exercise sync/async
and buffered/streaming text and tool-history requests. Whole masking changes
from **0/24 to 24/24 requests**. Text replies and returned JSON tool arguments
restore the native export; unchanged tool syntax remains intact. Request hashes
are retained, with no network/provider call. The GnuPG oracle uses only temporary
keyrings, never the user's keyring or a keyserver; its agents are stopped before
their directories are removed.

```sh
uv run python studies/private-key-blocks/generate.py /tmp/veil-native-key-fixtures
uv run python studies/private-key-blocks/replay.py /tmp/veil-native-key-fixtures --native --sdk --require-fixed --output /tmp/veil-key-replay.json
uv run pytest tests/test_private_key_blocks.py
```

GnuPG is required for generation and `--native`, not for Veil's core or ordinary
tests. A core-only wheel can replay retained local inputs and the CLI by
omitting `--native` and `--sdk`. To replay the baseline, archive `0e3052c`, set
`PYTHONPATH` to its `src/`, and omit `--require-fixed` from the current driver.

## Recognition and compatibility boundaries

[RFC 9580 section 6.2.2](https://www.rfc-editor.org/rfc/rfc9580.html#section-6.2.2)
defines armor metadata separately from the encoded message. `Comment` can carry
arbitrary UTF-8 text, and unknown header keys do not imply invalid packet data.
The truncated OpenPGP path recognizes consecutive colon-bearing header lines
after the opening line before applying the existing body scan. Complete-block
recognition still uses matching BEGIN/END labels. LF, CRLF, CR, repeated/unknown
headers and Unicode values preserve their exact source spelling in the vault.

This is privacy recognition, not a key validator or a complete OpenPGP/PEM
parser. Packet signatures, checksums, encryption and usability are not checked
by the detector. Truncated body recognition remains a bounded alphabet heuristic;
following prose made entirely of that alphabet can be absorbed into its span.
Unsupported or malformed encodings can still be missed. An explicit recognized
private-key marker is required; public-key, certificate, message and signature
labels do not gain this rule. Existing independent detectors may still inspect
their contents. Disabling secret detection retains the caller's configuration.

The [compatibility receipt](results/corpus-compatibility.json) compares complete
resolved-detection ledgers on all 1,483 hash-checked technical files: 32,925,796
bytes, 2,616,034 words and 10,407 detections. Before and after are identical in
every type, span, value, provenance and confidence. This does not establish a
general privacy accuracy rate.

The source correction is not a package release or a verified hosted deployment.

## Installed and offline verification

A fresh archive of `0f719f0` passed locked Python 3.14.7 installation with
development/spaCy dependencies, Ruff, formatting, mypy, **1,337 tests with no
skips**, wheel/sdist builds, web installation/typechecking/build and all 16
existing browser scenarios. [Commands, exit codes and log hashes](results/clean-checks.json)
retain the check boundaries.

Three fresh wheel environments replay the same native inputs. Current SDKs
(OpenAI 3.31.0, Anthropic 1.15.0) on Python 3.14.7 and the supported SDK floors
(1.66.0, 0.40.0) on Python 3.10.21 both pass all 18 cases and 24 SDK workflows.
The core-only Python 3.12.12 environment passes all 18 core/CLI/native recovery
cases with no Python SDK or crypto dependency installed. Every verdict,
restoration/recovery outcome and SDK request hash matches the source replay.
[Artifact verification](results/verification.json) compares all 38 runtime files
across source, sdist, wheel and installations, and all 37 Python modules against
the browser manifest. It also hashes the 27-file production build.

The [offline browser replay](results/browser/receipt.json) uses **synthetic
armor-shaped bodies that are not signing keys**, separately from native GnuPG
evidence. All four complete/truncated PII-bearing cases become whole secrets;
a public-key marker control retains its existing behavior. Chromium and Firefox
at 375/1280 pixels initialize on neutral text, disconnect, then perform their
first key masking and complete masked/vault downloads. Exact restoration,
zero additional requests, zero page errors and no document overflow pass.
All four screenshots were inspected, including
[mobile Chromium](results/browser/chromium-375.png).

```sh
cd web && npm ci && npm run lint && npm run build
cd ..
node studies/email-boundaries/check-browser.mjs web/dist /tmp/private-key-browser studies/private-key-blocks/browser-cases.json
```

The build output is `web/dist/`. No app UI was changed.
