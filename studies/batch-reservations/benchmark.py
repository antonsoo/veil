"""Measure real masking calls on constructed batches; no model or network calls.

Run with --source CHECKOUT, or omit it to exercise an installed wheel.
Every timed repetition also verifies both restoration modes outside the timer.
"""

from __future__ import annotations

import argparse
import copy
import gc
import hashlib
import importlib
import json
import os
import platform
import resource
import statistics
import sys
import time
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path)
parser.add_argument(
    "--case",
    required=True,
    choices=[
        "batch-500",
        "batch-2000",
        "batch-8000",
        "literal-8000",
        "single-8000",
        "shared-delimiter-1000",
        "realistic-1000",
        "custom-1000",
        "sdk-4000",
    ],
)
parser.add_argument("--repeats", type=int, default=3)
args = parser.parse_args()
if args.source:
    sys.path.insert(0, str(args.source.resolve() / "src"))

from veil import Masker, PlaceholderSurrogates, RealisticSurrogates  # noqa: E402


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


count = int(args.case.rsplit("-", 1)[1])
texts = [f"Please review ticket {i}: contact person{i}@example.org." for i in range(count)]
if args.case.startswith("literal-"):
    texts.append("Keep this literal example: ⟨eMaIl_1⟩.")
elif args.case.startswith("shared-delimiter-"):
    texts = [text + " Marker ⟨unrelated⟩." for text in texts]
elif args.case.startswith("single-"):
    texts = ["\n".join(texts)]
generator = (
    RealisticSurrogates()
    if args.case.startswith("realistic-")
    else PlaceholderSurrogates(template="[MASK_{type}_{n}]")
    if args.case.startswith("custom-")
    else PlaceholderSurrogates()
)

# Use the installed SDK's HTTP serialization, with a local mock transport.
# The wrapper encounters the document blocks one at a time inside its batch.
sdk_version = None
if args.case.startswith("sdk-"):
    import anthropic

    from veil.integrations.anthropic import AnthropicVeil

    sdk_version = anthropic.__version__
    # The locked SDK uses httpx2; older supported SDKs used httpx.
    httpx = importlib.import_module(
        next(
            base.__module__.split(".")[0]
            for base in anthropic.DefaultHttpxClient.__mro__[1:]
            if base.__module__.startswith("httpx")
        )
    )


def run():
    masker = Masker(surrogate_generator=generator)
    request_hash = None
    if args.case.startswith("sdk-"):
        requests = []
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "content",
                            "content": [{"type": "text", "text": text} for text in texts],
                        },
                    }
                ],
            }
        ]
        original = copy.deepcopy(messages)

        def reply(request):
            body = json.loads(request.content)
            requests.append(body)
            text = body["messages"][0]["content"][0]["source"]["content"][0]["text"]
            return httpx.Response(
                200,
                json={
                    "id": "msg_synthetic",
                    "type": "message",
                    "role": "assistant",
                    "model": "synthetic-offline",
                    "content": [{"type": "text", "text": text}],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            )

        with anthropic.Anthropic(
            api_key="synthetic-local-only",
            max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(reply)),
        ) as sdk:
            wrapped = AnthropicVeil(sdk, masker=masker)
            started = time.perf_counter()
            answer = wrapped.create(model="synthetic-offline", max_tokens=128, messages=messages)
            elapsed = time.perf_counter() - started
        assert len(requests) == 1 and messages == original
        assert answer.content[0].text == texts[0]
        masked = [
            block["text"] for block in requests[0]["messages"][0]["content"][0]["source"]["content"]
        ]
        request_hash = digest(requests[0])
    else:
        started = time.perf_counter()
        masked = masker.mask_many(texts)
        elapsed = time.perf_counter() - started
    assert len(masker.vault) == count
    assert [masker.restore(text) for text in masked] == texts
    assert [masker.restore(text, tolerant=False) for text in masked] == texts
    return elapsed, {
        "mappings": len(masker.vault),
        "maskedSha256": digest(masked),
        "vaultSha256": digest(masker.vault.to_dict()),
        "requestSha256": request_hash,
        "exactAndTolerantRoundtrips": True,
    }


samples, evidence = [], None
for _ in range(args.repeats):
    gc.collect()
    seconds, found = run()
    assert evidence is None or evidence == found
    evidence = found
    samples.append(seconds)
print(
    json.dumps(
        {
            "case": args.case,
            "texts": len(texts),
            "inputBytes": sum(len(s.encode()) for s in texts),
            "inputSha256": digest(texts),
            "seconds": samples,
            "medianSeconds": statistics.median(samples),
            "peakRssKiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "availableCpus": len(os.sched_getaffinity(0)),
            "anthropic": sdk_version,
            "scope": "Constructed inputs; masking plus its internal integrity checks timed. Restoration verification outside timer. SDK uses only a local mock HTTP transport.",
            **evidence,
        },
        indent=2,
    )
)
