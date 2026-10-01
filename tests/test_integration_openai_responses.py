"""The Responses API path, tested against the real ``openai`` SDK types
(``openai.types.responses``): responses and stream events are built with
``model_validate``, so a field the wrapper reads or writes that the SDK doesn't
have fails here. No network calls, no API key.
"""

from __future__ import annotations

import json
from typing import Any

from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseTextDeltaEvent,
    ResponseTextDoneEvent,
)

from veil.integrations._common import get_field
from veil.integrations.openai import OpenAIVeil
from veil.masker import Masker

EMAIL = "alice@example.com"


class FakeResponses:
    def __init__(self, response: Any = None, events: list[Any] | None = None) -> None:
        self.response = response
        self.events = events or []
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return iter(self.events)
        return self.response


class FakeClient:
    def __init__(self, response: Any = None, events: list[Any] | None = None) -> None:
        self.responses = FakeResponses(response, events)


def make_response(output: list[dict[str, Any]]) -> Response:
    return Response.model_validate(
        {
            "id": "resp_1",
            "object": "response",
            "created_at": 1_790_000_000,
            "model": "gpt-6-sol",
            "output": output,
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": [],
        }
    )


def message(text: str, item_id: str = "msg_1") -> dict[str, Any]:
    return {
        "type": "message",
        "id": item_id,
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def function_call(arguments: str) -> dict[str, Any]:
    return {
        "type": "function_call",
        "id": "fc_1",
        "call_id": "call_1",
        "name": "send_email",
        "arguments": arguments,
    }


def test_input_items_and_instructions_are_masked() -> None:
    veil = OpenAIVeil(FakeClient(make_response([])))
    reasoning = {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "opaque"}
    image = {"type": "input_image", "image_url": "https://example.org/x.png", "detail": "auto"}
    veil.create_response(
        model="gpt-6-sol",
        instructions=f"Escalations go to {EMAIL}.",
        input=[
            {"role": "user", "content": f"Write to {EMAIL}"},
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": EMAIL}, image],
            },
            reasoning,
            function_call(json.dumps({"to": EMAIL})),
            {"type": "function_call_output", "call_id": "call_1", "output": f"sent to {EMAIL}"},
            {
                "type": "function_call_output",
                "call_id": "call_2",
                "output": [{"type": "input_text", "text": EMAIL}],
            },
        ],
    )
    sent = veil.client.responses.calls[0]
    assert EMAIL not in json.dumps(sent)
    assert "⟨EMAIL_1⟩" in sent["instructions"]
    assert sent["input"][1]["content"][1] == image
    assert sent["input"][2] == reasoning  # no summary text to mask; encrypted content untouched
    assert json.loads(sent["input"][3]["arguments"]) == {"to": "⟨EMAIL_1⟩"}


def test_string_input_is_masked() -> None:
    veil = OpenAIVeil(FakeClient(make_response([])))
    veil.create_response(model="gpt-6-sol", input=f"Email {EMAIL}")
    assert veil.client.responses.calls[0]["input"] == "Email ⟨EMAIL_1⟩"


def test_output_is_restored_on_the_real_response_model() -> None:
    masker = Masker()
    surrogate = masker.mask(EMAIL)
    # The model may write the surrogate's brackets as JSON escapes inside arguments.
    escaped_args = json.dumps({"to": surrogate}, ensure_ascii=True)
    response = make_response(
        [
            message(f"I wrote to {surrogate}."),
            function_call(escaped_args),
            {
                "type": "reasoning",
                "id": "rs_1",
                "summary": [{"type": "summary_text", "text": f"User wants {surrogate} emailed"}],
            },
        ]
    )
    veil = OpenAIVeil(FakeClient(response), masker=masker)
    restored = veil.create_response(model="gpt-6-sol", input="go")
    assert isinstance(restored, Response)
    assert restored.output_text == f"I wrote to {EMAIL}."  # the SDK's own aggregate
    call = restored.output[1]
    assert json.loads(get_field(call, "arguments")) == {"to": EMAIL}
    assert EMAIL in restored.output[2].summary[0].text


def test_refusal_is_restored() -> None:
    masker = Masker()
    surrogate = masker.mask(EMAIL)
    item = message("")
    item["content"] = [{"type": "refusal", "refusal": f"I can't email {surrogate}."}]
    veil = OpenAIVeil(FakeClient(make_response([item])), masker=masker)
    restored = veil.create_response(model="gpt-6-sol", input="go")
    assert restored.output[0].content[0].refusal == f"I can't email {EMAIL}."


def dump(items: list[Any]) -> str:
    return json.dumps([i.model_dump() if hasattr(i, "model_dump") else i for i in items])


def test_restored_output_fed_back_as_input_resends_the_original_items() -> None:
    masker = Masker()
    surrogate = masker.mask(EMAIL)
    original = make_response(
        [message(f"Drafted a note to {surrogate}."), function_call(json.dumps({"to": surrogate}))]
    )
    veil = OpenAIVeil(FakeClient(original), masker=masker)
    first = veil.create_response(model="gpt-6-sol", input=f"Email {EMAIL}")
    assert EMAIL in first.output_text

    # A stateless app appends the output it saw (SDK objects, real values) plus the tool result.
    history = [{"role": "user", "content": f"Email {EMAIL}"}, *first.output]
    history.append({"type": "function_call_output", "call_id": "call_1", "output": "ok"})
    veil.create_response(model="gpt-6-sol", input=history)
    resent = veil.client.responses.calls[1]["input"]
    assert EMAIL not in dump(resent)
    # Exactly the items the model produced, not a re-masked approximation.
    assert resent[1] is original.output[0]
    assert resent[2] is original.output[1]


def test_output_items_resent_as_plain_dicts_are_replayed_too() -> None:
    masker = Masker()
    surrogate = masker.mask(EMAIL)
    original = make_response([message(f"Hi {surrogate}")])
    veil = OpenAIVeil(FakeClient(original), masker=masker)
    first = veil.create_response(model="gpt-6-sol", input="go")
    veil.create_response(model="gpt-6-sol", input=[i.model_dump() for i in first.output])
    assert veil.client.responses.calls[1]["input"][0] is original.output[0]


def text_delta(delta: str, seq: int) -> ResponseTextDeltaEvent:
    return ResponseTextDeltaEvent.model_validate(
        {
            "type": "response.output_text.delta",
            "item_id": "msg_1",
            "output_index": 0,
            "content_index": 0,
            "delta": delta,
            "logprobs": [],
            "sequence_number": seq,
        }
    )


def test_stream_restores_split_surrogates_and_final_response() -> None:
    masker = Masker()
    surrogate = masker.mask(EMAIL)
    text = f"Sent to {surrogate} just now."
    cut = text.index(surrogate) + 4  # split inside the surrogate
    args = json.dumps({"to": surrogate})  # ASCII-escaped: the surrogate's brackets arrive as \u27e8
    args_cut = args.index("\\u27e8") + 3  # split inside the escape sequence
    events = [
        text_delta(text[:cut], 1),
        text_delta(text[cut:], 2),
        ResponseTextDoneEvent.model_validate(
            {
                "type": "response.output_text.done",
                "item_id": "msg_1",
                "output_index": 0,
                "content_index": 0,
                "text": text,
                "logprobs": [],
                "sequence_number": 3,
            }
        ),
        ResponseFunctionCallArgumentsDeltaEvent.model_validate(
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_1",
                "output_index": 1,
                "delta": args[:args_cut],
                "sequence_number": 4,
            }
        ),
        ResponseFunctionCallArgumentsDeltaEvent.model_validate(
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_1",
                "output_index": 1,
                "delta": args[args_cut:],
                "sequence_number": 5,
            }
        ),
        ResponseFunctionCallArgumentsDoneEvent.model_validate(
            {
                "type": "response.function_call_arguments.done",
                "item_id": "fc_1",
                "output_index": 1,
                "arguments": args,
                "sequence_number": 6,
            }
        ),
        ResponseCompletedEvent.model_validate(
            {
                "type": "response.completed",
                "sequence_number": 7,
                "response": make_response([message(text), function_call(args)]).model_dump(),
            }
        ),
    ]
    veil = OpenAIVeil(FakeClient(events=events), masker=masker)
    out = list(veil.stream_response(model="gpt-6-sol", input=f"Email {EMAIL}"))
    deltas = "".join(
        get_field(e, "delta") for e in out if get_field(e, "type") == "response.output_text.delta"
    )
    assert deltas == text.replace(surrogate, EMAIL)
    arg_deltas = "".join(
        get_field(e, "delta")
        for e in out
        if get_field(e, "type") == "response.function_call_arguments.delta"
    )
    assert json.loads(arg_deltas) == {"to": EMAIL}
    done = next(e for e in out if get_field(e, "type") == "response.output_text.done")
    assert done.text == text.replace(surrogate, EMAIL)
    final = out[-1].response
    assert final.output_text == text.replace(surrogate, EMAIL)
    assert EMAIL not in json.dumps(veil.client.responses.calls[0]["input"])


def test_stream_held_back_text_is_released_before_done() -> None:
    masker = Masker()
    masker.mask(EMAIL)
    # "⟨EM" could begin a surrogate, so the restorer holds it until the text settles.
    events = [
        text_delta("Total: 3 ⟨EM", 1),
        ResponseTextDoneEvent.model_validate(
            {
                "type": "response.output_text.done",
                "item_id": "msg_1",
                "output_index": 0,
                "content_index": 0,
                "text": "Total: 3 ⟨EM",
                "logprobs": [],
                "sequence_number": 2,
            }
        ),
    ]
    out = list(
        OpenAIVeil(FakeClient(events=events), masker=masker).stream_response(model="m", input="x")
    )
    kinds = [get_field(e, "type") for e in out]
    assert kinds == [
        "response.output_text.delta",
        "response.output_text.delta",
        "response.output_text.done",
    ]
    assert "".join(get_field(e, "delta") for e in out[:2]) == "Total: 3 ⟨EM"
    # Released as a copy of the last real delta event, so attribute access keeps working.
    assert isinstance(out[1], ResponseTextDeltaEvent)
    assert (out[1].item_id, out[1].delta) == ("msg_1", "⟨EM")


def test_stream_cut_off_still_flushes() -> None:
    masker = Masker()
    masker.mask(EMAIL)
    out = list(
        OpenAIVeil(FakeClient(events=[text_delta("end ⟨EMA", 1)]), masker=masker).stream_response(
            model="m", input="x"
        )
    )
    assert "".join(get_field(e, "delta") for e in out) == "end ⟨EMA"


def test_readme_loop_reads_every_event_by_attribute() -> None:
    masker = Masker()
    surrogate = masker.mask(EMAIL)
    events = [
        text_delta(f"to {surrogate[:3]}", 1),
        text_delta(surrogate[3:], 2),
        text_delta(" ⟨", 3),
    ]
    printed = ""
    for event in OpenAIVeil(FakeClient(events=events), masker=masker).stream_response(
        model="m", input="x"
    ):
        if event.type == "response.output_text.delta":
            printed += event.delta
    assert printed == f"to {EMAIL} ⟨"


def test_restored_items_resent_without_a_replay_hit_are_masked() -> None:
    # After a restart the replay cache is empty: a restored refusal or reasoning summary
    # holds real values and must be masked like anything else, encrypted content untouched.
    masker = Masker()
    veil = OpenAIVeil(FakeClient(make_response([])), masker=masker)
    veil.create_response(
        model="gpt-6-sol",
        input=[
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "refusal", "refusal": f"I won't email {EMAIL}."}],
            },
            {
                "type": "reasoning",
                "id": "rs_1",
                "encrypted_content": "opaque",
                "summary": [{"type": "summary_text", "text": f"User wants {EMAIL} emailed"}],
            },
        ],
    )
    sent = veil.client.responses.calls[0]["input"]
    assert EMAIL not in json.dumps(sent)
    assert sent[1]["encrypted_content"] == "opaque"
    assert "⟨EMAIL_1⟩" in sent[1]["summary"][0]["text"]
