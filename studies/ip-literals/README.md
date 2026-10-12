# Complete IPv6 literal masking

The baseline `33992a7b59f23cb158c17215f76de06604ef95d4` accepted a valid
hexadecimal prefix of a mixed IPv6 address. Overlap resolution then discarded
its embedded IPv4 detection, leaving a suffix in the outgoing text:

| Synthetic input | Baseline masked value | Corrected masked value |
| --- | --- | --- |
| `2001:db8::192.0.2.33` | `⟨IPV6_1⟩.0.2.33` | `⟨IPV6_1⟩` |
| `::ffff:192.0.2.33` | `::ffff:⟨IPV4_1⟩` | `⟨IPV6_1⟩` |
| `fe80::1%en0` | `⟨IPV6_1⟩%en0` | `⟨IPV6_1⟩` |

These are constructed examples, not production privacy incidents. The change
is in source; it does not update the published package or hosted demo.

## Recognition policy

The scanner consumes the address and optional scope before validating the
address with `ipaddress.IPv6Address`. A complete mixed literal gets one `IPV6`
entity. Embedded IPv4 matching cannot salvage a fragment from an already
scanned IPv6-shaped token, including a rejected token. A colon is required
before a dotted tail; scanning cannot restart inside that tail.

- Ordinary IPv4, CIDR suffixes, bracketed ports and sentence punctuation keep
  their existing behavior. Port numbers and prefix lengths remain visible.
- Scope IDs are opaque text: word characters, `.`, `~`, `-`, and percent-encoded
  octets. Numeric scopes, `%en0`, `%eth0.100` and URI spelling `%25eth0%2D1` are
  retained and restored byte for byte. No interface, DNS or network lookup is
  performed. The scanner does not blanket-decode `%13`, which can be a raw
  numeric scope. Trailing periods are treated as prose punctuation.
- Unspecified and loopback addresses remain excluded. IPv4-mapped IPv6 follows
  the embedded IPv4 classification in both dotted and hex notation. A global
  IPv6 address ending in `127.0.0.1` is not itself IPv6 loopback.
- The existing reserved-space filter remains, with explicit exceptions for
  `64:ff9b::/96`, `64:ff9b:1::/48` and `5f00::/16`: assigned NAT64/SRv6 prefixes.
  For otherwise excluded reserved space, a valid explicit dotted tail that
  the old detector protected now causes the whole literal to be protected.
  This preserves recognition of deprecated `::192.0.2.33`; its pure-hex form
  `::c000:221` is still excluded by the reserved-space policy. The detector is
  intentionally not a recognizer for every syntactically valid IPv6 address:
  `be::` and Python slices such as `1::2` remain readable.
- Malformed candidates and unsupported scope punctuation are left alone.
  This is not endpoint validation, interface existence checking or a guarantee
  that every address-like string will be masked.

The mixed representation is specified in
[RFC 4291 section 2.2](https://www.rfc-editor.org/rfc/rfc4291.html#section-2.2).
The address/scope notation and local nature of zone IDs are described in
[RFC 4007 section 11](https://www.rfc-editor.org/rfc/rfc4007.html#section-11).
Assigned translation/routing prefixes are listed by
[IANA's IPv6 Special-Purpose Address Registry](https://www.iana.org/assignments/iana-ipv6-special-registry/iana-ipv6-special-registry.xhtml).
Python documents its address classification and scope handling in
[`ipaddress`](https://docs.python.org/3/library/ipaddress.html).

## Reproduction and results

`generate.py` constructs 150 cases, including 127 complete-literal expectations
and 23 exclusion/malformed controls. Each positive address is checked against
libc's `inet_pton(AF_INET6, ...)`; alternate spellings must yield the same 16
bytes. This is an independent parser for the address part, not an independent
oracle for Veil's privacy policy or scope syntax. Interface names are fixtures.

| Workflow | Baseline | Corrected |
| --- | ---: | ---: |
| Complete expected detection and masking | 28/150 | 150/150 |
| Exact restoration | 150/150 | 150/150 |
| Streaming restoration, four chunk sizes | 600/600 | 600/600 |
| CLI file/vault workflows, text + JSON + JSONL | 0/21 | 21/21 |
| SDK requests with the complete expected mask | 0/21 | 21/21 |

CLI JSON/JSONL inputs are ordinary text files, not a new structured CLI mode.
Every CLI flow restores the original bytes, including CRLF. SDK replay uses the
real OpenAI Chat Completions/Responses and Anthropic SDK serializers with a
local echo HTTP transport. It makes no API calls; all 21 replies restore exactly.

```sh
uv run python studies/ip-literals/generate.py
uv run python studies/ip-literals/replay.py --source . --sdk --output /tmp/ip-after.json
uv run python studies/ip-literals/replay.py --source /path/to/baseline --baseline --sdk --output /tmp/ip-before.json
```

The receipts are in [`results/before.json`](results/before.json) and
[`results/after.json`](results/after.json). To test an installed package, invoke
`replay.py` with that environment's Python and omit `--source`.

A fresh replay of the retained, hash-checked public technical corpus has
**zero changed detections** across 1,483 files, 32,925,796 bytes and 2,616,034
words: all 10,339 resolved entities have identical type, span, value, detector
and confidence. [`results/corpus.json`](results/corpus.json) references the
identical per-file rows already retained in the credential-URL study, avoiding
another copy. This corpus checks collateral changes; it is not evidence of
IPv6 recall in production logs.

```sh
PYTHONPATH=/path/to/baseline/src uv run python studies/secret-formats/corpus.py studies/real-text/cache /tmp/ip-corpus-before.json
PYTHONPATH=src uv run python studies/secret-formats/corpus.py studies/real-text/cache /tmp/ip-corpus-after.json
cmp /tmp/ip-corpus-before.json /tmp/ip-corpus-after.json
PYTHONPATH=src uv run python studies/ip-literals/scaling.py /tmp/ip-scaling.json
```

The synthetic scaling probe covers five malformed token shapes at roughly
10,000, 100,000 and 1,000,000 characters. Five-call medians on shared
14-vCPU WSL2/Python 3.12.12 range from 36.8 to 136.9 ms at the largest size.
See [`results/scaling.json`](results/scaling.json) for every timing and source
hash. This measures `IpDetector.find`, not total masking throughput; no timing
threshold is used as a correctness test.

`browser.mjs` selects 37 cases covering the original failure, scopes, assigned
prefixes, mapped-address policy and malformed controls. It exercises the real
Pyodide package, preview and downloaded text/vault at 375 and 1280 pixels in
Chromium and Firefox, offline after loading the runtime. Its receipts include
served-asset hashes. Complete expected outcomes improve from **40/148 to
148/148**, with 296 real downloads per run and zero requests after going
offline. Four before/after screenshots at desktop Chromium and phone Firefox
were inspected in `docs/assets/ip-literals/`. Run it after `npm --prefix web ci` and
`npm --prefix web run build`:

```sh
node studies/ip-literals/browser.mjs web /tmp/ip-browser
```
