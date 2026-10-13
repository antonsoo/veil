# Many short texts should not repeatedly search unrelated sources

Baseline `7114765940556e43101de8fa44e53c5eb96404db` already protected literal
surrogates across a complete masking batch. Its reservation lookup checked each
candidate against every source. A 4,000-message profile made 32 million
candidate/source checks; reservation lookup consumed 5.59 of 6.33 profiled
seconds. Profiling overhead is excluded from the measurements below.

The source checkout indexes normalized source text by the characters it
contains. A candidate only searches sources containing its first character.
Most ordinary text does not contain the default placeholder delimiter. Later
nested sources update the same index, so the final batch check still catches a
literal introduced after an earlier replacement was selected. Each source
remains separate; the index cannot invent a literal across message boundaries.

```text
Before: candidate -> every reserved source -> substring check when plausible
After:  candidate -> sources containing its first character -> substring check
        final batch verification and rollback remain in place
```

## Measured complete operations

All inputs are **constructed**, with fictitious identities. Three repetitions
per case, per version, run in fresh case processes; before/after order alternates
between cases. These are medians, with every individual measurement in
[before](results/before.json), [after](results/after.json) and the
[comparison](results/comparison.json). The host was Python 3.12.12 on WSL2,
Ryzen 7 7800X3D, with 14 CPUs available to the process. [Host receipt](results/host.json).

| Input | UTF-8 bytes | Before | After |
| --- | ---: | ---: | ---: |
| 500 short messages | 27,780 | 0.061 s | 0.027 s |
| 2,000 short messages | 113,780 | 0.678 s | 0.121 s |
| 8,000 short messages | 461,780 | 9.866 s | 0.509 s |
| Same batch plus one literal placeholder | 461,821 | 8.909 s | 0.495 s |
| Same 8,000 messages joined into one text | 469,779 | 0.420 s | 0.431 s |
| 1,000 messages all containing the delimiter | 79,780 | 0.321 s | 0.205 s |
| 1,000 messages with realistic email replacements | 55,780 | 0.155 s | 0.062 s |
| 1,000 messages with a custom template | 55,780 | 0.166 s | 0.068 s |
| 4,000 document blocks through the actual SDK | 229,780 | 2.784 s | 0.565 s |

The 8,000-message case's whole-process peak RSS fell from 55,884 to 43,108 KiB.
RSS includes imports, repeats and correctness checks; it does not isolate the
index. These timings include masking's own round-trip verification. Additional
exact/tolerant restoration checks run outside the timer. Every repetition and
both versions produce identical masked text, complete vault and, for the SDK
case, serialized request hashes.

The SDK measurement uses Anthropic 1.11.0 and its own HTTP serialization with a
local mock transport. It includes request preparation, serialization and a
controlled restored reply. It measures neither provider latency nor acceptance
of that document by a live service. An initial harness assumed the older
`httpx` module; the corrected harness selects the SDK's installed HTTP module
(`httpx2` here). No application dependency changed for that correction.

```sh
uv sync --frozen --group dev
uv run python studies/batch-reservations/benchmark.py --source . --case batch-8000
uv run python studies/batch-reservations/benchmark.py --source . --case sdk-4000
```

To reproduce before, provide an archive/checkout of the recorded baseline to
`--source`. Run the same commands without `--source` using an installed wheel's
Python to exercise that installation. Each invocation prints full timing samples
and integrity hashes. No credential or live API is needed.

## Preserve the safety behavior

[Compatibility evidence](results/compatibility.json) compares complete results,
not just success codes:

- All 23 existing collision/CLI cases stay identical, including rollback,
  refused reused literals, realistic replacements and single-character streams.
  [Retained case records](results/collision-cases.json).
- All 36 actual SDK document captures stay identical across sync/async,
  buffered/streaming, plain/custom content and documents inside tool results.
  [Retained requests and checks](results/sdk-captures.json).
- The existing 240-document synthetic corpus preserves all masked outputs and
  its 503 mappings. Both restoration modes recover every source exactly.
  [Corpus hashes](results/corpus.json).
- An independent direct substring lookup agrees with the indexed lookup on
  20,000 deterministic checks. It interleaves source additions and queries,
  including whitespace, Unicode case folding, empty values and reserved
  originals. The reference has no character index.

```sh
uv run python studies/batch-reservations/oracle.py --source .
uv run python studies/surrogate-collisions/replay.py --source .
uv run python studies/anthropic-documents/capture.py --source . --check
```

## Clean and installed artifacts

[Verification](results/verification.json) archives implementation `115eefe`,
installs the committed lock on Python 3.12.12, and runs lint, formatting, strict
types and the complete native suite: 639 passed, with one optional spaCy test
skipped because that extra is not installed. The source distribution builds
successfully, then supplies the wheel used in two fresh installations.

| Installed interpreter | Matching package files | Batch cases | Reservation oracle | Collision cases | SDK captures |
| --- | ---: | ---: | ---: | ---: | ---: |
| Python 3.10.21 | 35 | 9 | 20,000 | 23 | 36 |
| Python 3.14.7 | 35 | 9 | 20,000 | 23 | 36 |

Both installations preserve every masked-output, vault and SDK-request hash,
all collision outcomes and the full reservation-oracle result. The benchmark
cases run once per installed interpreter to verify behavior; they are not a
cross-version performance comparison. [Python 3.10 records](results/python310-benchmarks.json),
[Python 3.14 records](results/python314-benchmarks.json). The 89,384-byte wheel
has SHA-256 `10e521b305ce68d00e6a5cd548b24f11c6dcf90b016643b1ca25febb2838222a`.

The initial installed-file checker included test-generated Python 3.12 bytecode
and stopped on the Python 3.10 installation. Excluding `__pycache__` corrected
that harness; completed clean checks were retained and installed verification
resumed. Application source and built artifacts did not change. All 298 tracked
archive files match the implementation commit. These are source/package checks,
not a hosted browser or deployment verification.

## Limits

This is an optimization of the existing reservation rule. If every source
contains a candidate's first character, substring checks still scan every
source. It is not a general linear-time guarantee, and the nearly unchanged
single-text measurement is an intentional control. The index retains references
to source text only for the current batch, as before. Detector accuracy,
restoration semantics and the documented need to supply complete related raw
texts are unchanged. Nothing here establishes production privacy or model
behavior. No UI, package version or dependency changed.
