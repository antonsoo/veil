# Assistant history can carry private text outside `content`

At baseline `e417aa1`, the Chat Completions wrapper masked ordinary text and
modern function-tool arguments, but skipped other documented text fields.
The real OpenAI SDK 3.23.0 serialized raw synthetic email addresses into
request bodies when history put them in an assistant `refusal`, a refusal
content part, legacy `function_call.arguments`, or custom-tool `input`.
Complete replies also left surrogates in refusal, legacy and custom-tool
fields rather than restoring them.

The corrected source handles those input fields before transport, in sync
and async calls and both streaming entrypoints. Complete replies restore
their text and remember the original provider representation. Resending an
unchanged returned SDK message preserves that representation exactly,
including lowercase surrogates that were restored tolerantly. Edited history
is masked again rather than replaying an earlier response.

| Text location | Outgoing history | Complete response |
| --- | --- | --- |
| Message `refusal` | Mask detected string entities | Restore string |
| Content part with `type: refusal` | Mask its `refusal` text | Input representation only |
| Legacy `function_call.arguments` | Mask decoded JSON string values | Restore decoded values |
| Custom `tool_calls[].custom.input` | Mask plain text | Restore plain text |

Legacy JSON arguments use the same syntax-preserving path as modern
function tools. The captured argument document contains a 53-bit-exceeding
integer, duplicate members and whitespace; all unrelated bytes survive.
Custom-tool input is free-form text, not a JSON argument document.

## Reproduction through the real SDK

```bash
uv sync --locked --group dev
uv run python studies/chat-text-fields/replay.py --src src --out /tmp/chat-fields-after.json
```

To inspect baseline behavior without changing the checkout:

```bash
mkdir -p /tmp/claude-1000/veil-chat-fields-before
git archive e417aa1 src | tar -x -C /tmp/claude-1000/veil-chat-fields-before
uv run python studies/chat-text-fields/replay.py \
  --src /tmp/claude-1000/veil-chat-fields-before/src \
  --out /tmp/chat-fields-before.json --observe-only
```

[Before](results/before.json) and [after](results/after.json) preserve 54 SDK
workflows with the exact application input, mocked provider reply, returned
SDK message, request bodies and exception state. They comprise 24 outgoing
masking cases, 24 collision cases, and six complete-reply/replay cases.
Baseline sends raw contacts in all 24 outgoing masking cases and disagrees
with all 54 corrected expectations. The fixed source sends no raw contacts
in the recorded requests and has zero disagreements.

The collision cases put a literal placeholder in a newly covered field
after an earlier message would allocate that same placeholder. They now
reject before any request, retain the input and leave the vault empty. They
check a consequential ambiguity boundary, not just successful string replacement.
The regression suite also resends edited SDK messages and confirms that the
new contact is masked without mutating the original.

The [official Chat Completions schema](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
declares these input fields and complete-message outputs. The SDK is real;
the HTTP transport and every provider reply in this study are controlled
fixtures. No key, live model response or network API request is used.
The two email addresses are synthetic examples, not personal data. This
study establishes handling of these protocol fields, not general detector
accuracy or production server behavior.

## Boundaries

The correction is unreleased. It covers outgoing messages through
`OpenAIVeil` / `AsyncOpenAIVeil`, and complete Chat Completions responses.
Existing streaming output restoration handles ordinary text, refusals and
modern function-tool arguments; this change does not add streaming custom
or deprecated function-call output restoration. It does mask these history
fields before a streamed request.

Unchanged retained provider output deliberately replays exactly, so text
already produced by the provider is not treated as new application input.
Edited or newly supplied text is scanned by the configured detectors.
Binary content, references, metadata, and numeric values are outside this
text-field change. JSON keys containing detected sensitive values reject
legacy arguments just as they reject modern function arguments.
The name of a tool or function is not renamed. Existing replay-cache capacity
and ambiguity limits still apply.
