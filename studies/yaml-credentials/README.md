# Mask the YAML credential body, not its indicator

At baseline `b00ff73`, a native PyYAML password block became:

```yaml
password: ⟨SECRET_1⟩
  river
  stone
```

The password remained visible. A folded `client_secret: >-` stayed unchanged.
With a header comment, replacing the literal marker could also make valid YAML
invalid. The corrected source produces:

```yaml
password: |
  ⟨SECRET_1⟩
```

The header and neighboring configuration remain readable. The vault stores the
raw body span, including internal newlines and extra indentation. Restoration
recovers the exact original source. This study uses controlled dummy values;
it does not establish production detection recall. No runtime dependency was
added. This is source work, with no registry release or deployment yet.

## Reproduced behavior

[`capture.py`](capture.py) retained 16 actual **PyYAML 6.0.3** writer outputs,
covering literal/folded styles, strip/keep chomping, blank lines, extra
indentation, assignment-looking text, nested PII and Unicode. The native loader
and scalar tokens verify each original value and its source bounds. No native
output is rewritten. [Retained inputs](fixtures/native.json).

| Workflow | Baseline protected | Corrected protected |
|---|---:|---:|
| Native writer values | 0/16 | 16/16 |
| Actual SDK text requests | 0/12 | 12/12 |
| Shared-valid YAML syntax matrix | 0/6,912 | 6,912/6,912 |

[Before](results/before.json) and [after](results/after.json) retain actual
output, vault originals, module hashes and serialized SDK requests. Both
versions restore all 16 native sources through the CLI and four stream chunk
sizes; restoration alone did not establish outgoing protection. Actual OpenAI
Chat/Responses and Anthropic SDKs use local mock HTTP transports, sync/async
and buffered/streaming. The echo replies restore exactly. No model service is
called, and all retained credential values are synthetic.

[`oracle.py`](oracle.py) generates 6,912 documents: two styles, 48 indicator
spellings, four mapping/sequence contexts, six body shapes and three line
breaks. PyYAML 6.0.3 and ruamel.yaml 0.18.16 agree on every original document.
They also agree on every corrected masked document; only the credential's
parsed value changes. Baseline leaves every body visible and produces 3,456
masked parse failures. [Baseline matrix](results/oracle-before.json),
[corrected matrix](results/oracle-after.json). Input-ledger hashes match.

## Recognition boundary

The existing explicit credential labels apply, including supported quoted keys
and uppercase environment-style prefixes. A block header must start a mapping
entry, optionally in compact sequences. `|` and `>` accept automatic indentation
or a digit 1-9, and `+`/`-` in either valid order. Header comments, required
indentation, edge blank lines and final line breaks stay in place. LF, CRLF, CR,
a leading BOM and no final newline are covered. The raw nonblank body is one
credential even when it contains another assignment, email or card number.
Dedented entries/comments and following ordinary blocks remain outside it.

This is not a YAML parser. Tags/anchors before the style indicator, explicit
mapping keys, escaped key names, log prefixes before a mapping entry, multiline
quoted/plain scalars and arbitrary malformed/partial YAML remain unsupported.
Whitespace-only bodies are not new credential matches. Auto-indented content
beginning with a tab is parser-dependent and outside the shared-valid matrix;
its tab cases use explicit indentation or a tab after ordinary content. The
rule does not decode/fold values or equate different YAML spellings. Existing
unlabelled short-secret and source-variable ambiguity still apply.
Bare pipes retain their prior meaning: `password=river|stone` and
`password=|river` are complete values, not truncated at the pipe. The YAML
exception applies only to a standalone block marker after `:`. A separate
credential assignment in a header comment still receives its own protection.

```sh
uv run --locked --with PyYAML==6.0.3 python studies/yaml-credentials/capture.py
uv run --locked python studies/yaml-credentials/replay.py --sdk --require-fixed --output /tmp/yaml-credentials.json
uv run --locked --with PyYAML==6.0.3 --with ruamel.yaml==0.18.16 python studies/yaml-credentials/oracle.py --require-fixed --output /tmp/yaml-oracle.json
```

Omit `--sdk` to replay the native fixtures with a core-only installation. To
compare baseline, archive `b00ff73`, set `PYTHONPATH` to that archive's `src/`,
and omit `--require-fixed`. Native generation is a study-only dependency;
neither YAML library enters the installed core.

## Collateral review and bounded cost

The [retained technical corpus replay](results/corpus.json) hash-checks all
1,483 files against the earlier public-source manifests: 32,925,796 bytes and
2,616,034 whitespace-separated words. All 10,407 resolved detections retain
their complete type, span, value, provenance and confidence; every file's
detection hash is unchanged. This corpus adds no in-the-wild block leak case.
It is a replay of retained sources, not a fresh collection or precision estimate.
The native writer inputs above establish the failure.

[`scaling.py`](scaling.py) measures literal/folded blocks, empty blocks,
assignment-looking header comments and bare pipe values at 100, 1,000 and
10,000 repetitions. [Before](results/blocks-scaling-before.json) and
[after](results/blocks-scaling-after.json) retain input/module hashes, sizes,
detection counts, one warmup and three measurements. Maximum detector medians
were 0.413 and 0.669 seconds respectively. This adds recognition work; it is
not a speedup or a worst-case latency bound. The shared host was also running
browser verification. Machine: 14 vCPU WSL2 Linux, 48 GB RAM; Python 3.12.12.
The earlier 24-case assignment timings in `results/scaling-*.json` describe
the intermediate source `425dd6b`, before the bare-pipe review correction;
the block-specific measurements identify the final runtime hash.
