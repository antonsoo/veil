"""Authored Unicode restoration controls, CLI and real SDK wire objects.

All identities and replies are fictitious. The 48th realistic PERSON surrogate
is generated through the ordinary vault path. No model or provider is called.
Use --source CHECKOUT for source, or run with an independently installed Python.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path)
parser.add_argument("--label", required=True)
parser.add_argument("--out", required=True, type=Path)
parser.add_argument("--sdk", action="store_true")
args = parser.parse_args()
if args.source:
    sys.path.insert(0, str(args.source.absolute() / "src"))

from veil import Masker, RealisticSurrogates, Restorer  # noqa: E402
from veil.backends.known_entities import KnownEntitiesBackend  # noqa: E402
from veil.types import EntityType  # noqa: E402

ORIGINAL = "Jordan Alvarez"
SURROGATE = "Avery Castillo"


def masker():
    m = Masker(
        surrogate_generator=RealisticSurrogates(),
        name_backends=[KnownEntitiesBackend(persons=[ORIGINAL])],
    )
    for index in range(1, 48):
        m.vault.get_or_create(
            EntityType.PERSON, f"Controlled contact {index}", m.surrogate_generator
        )
    return m


def cases():
    rows = []

    def add(name, text, expected, exact=None):
        rows.append(
            {
                "name": name,
                "text": text,
                "expected": expected,
                "exactExpected": text if exact is None else exact,
            }
        )

    for normalization in ["NFC", "NFD"]:
        reply = unicodedata.normalize(normalization, "Ask avery castilló about the booking.")
        add(normalization + "-accented-name", reply, reply)
    reply = "avery castillo\u0301's booking"
    add("NFD-accented-possessive", reply, reply)
    for label, mark in [("nonspacing", "\u0301"), ("spacing", "\u093e"), ("enclosing", "\u20dd")]:
        for side, reply in [
            ("right", f"avery castillo{mark}x"),
            ("left", f"x{mark}avery castillo"),
        ]:
            add(f"{label}-{side}-authored-boundary", reply, reply)
    add("recased-name", "avery castillo", ORIGINAL)
    add("recased-possessive", "avery castillo's", ORIGINAL + "'s")
    add("curly-possessive", "AVERY CASTILLO’s", ORIGINAL + "’s")
    add("wrapped-name", "AVERY\n\tCASTILLO", ORIGINAL)
    add("punctuation", "(avery castillo), yes.", f"({ORIGINAL}), yes.")
    for text in ["prefixavery castillo", "avery castillox", "avery castillo_2", "avery castillo7"]:
        add("existing-longer-word-" + text, text, text)
    text = "prefixAvery Castillo\u0301suffix"
    add(
        "exact-substring-contract",
        text,
        "prefix" + ORIGINAL + "\u0301suffix",
        "prefix" + ORIGINAL + "\u0301suffix",
    )
    return rows


m = masker()
masked = m.mask(ORIGINAL)
assert masked == SURROGATE
rows = []
for case in cases():
    text = case["text"]
    restored = m.restore(text)
    exact = m.restore(text, tolerant=False)
    streamed = []
    for cut in range(len(text) + 1):
        r = Restorer(m.vault)
        value = r.feed(text[:cut]) + r.feed(text[cut:]) + r.flush()
        streamed.append(value)
    rows.append(
        case
        | {
            "restored": restored,
            "exact": exact,
            "allSingleCutStreamsAgree": all(value == case["exactExpected"] for value in streamed),
            "streamPartitions": len(streamed),
            "agrees": restored == case["expected"]
            and exact == case["exactExpected"]
            and all(value == exact for value in streamed),
        }
    )

cli = []
with tempfile.TemporaryDirectory(prefix="veil-restore-marks-") as temporary:
    vault = Path(temporary) / "vault.json"
    vault.write_text(m.vault.to_json())
    env = dict(os.environ)
    if args.source:
        env["PYTHONPATH"] = str(args.source.absolute() / "src")
    for case in cases():
        for exact in [False, True]:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "veil.cli",
                    "restore",
                    "--vault",
                    str(vault),
                    *(["--exact"] if exact else []),
                ],
                input=case["text"],
                text=True,
                capture_output=True,
                cwd=temporary,
                env=env,
            )
            expected = case["exactExpected"] if exact else case["expected"]
            expected_stdout = expected if expected.endswith("\n") else expected + "\n"
            cli.append(
                {
                    "name": case["name"],
                    "exact": exact,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "exit": result.returncode,
                    "agrees": result.returncode == 0 and result.stdout == expected_stdout,
                }
            )

sdk = []
versions = {}
if args.sdk:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import anthropic

    from tests.sdk_wire import MODEL, Wire, anthropic_message, anthropic_stream
    from veil.integrations.anthropic import AnthropicVeil, AsyncAnthropicVeil

    versions = {name: importlib.metadata.version(name) for name in ["anthropic"]}

    async def run_sdk():
        for case in [
            row
            for row in cases()
            if row["name"]
            in [
                "NFC-accented-name",
                "NFD-accented-name",
                "recased-name",
                "exact-substring-contract",
            ]
        ]:
            for asynchronous in [False, True]:
                for streaming in [False, True]:
                    text = case["text"]
                    arguments = {"person": text, "nested": [text], "unchanged": 17}
                    blocks = [
                        {"type": "text", "text": text},
                        {
                            "type": "tool_use",
                            "id": "toolu_marks",
                            "name": "send_email",
                            "input": arguments,
                        },
                    ]
                    events = anthropic_stream(
                        [
                            ("text", list(text)),
                            ("tool_use", list(json.dumps(arguments, ensure_ascii=False))),
                        ]
                    )
                    answer = events if streaming else anthropic_message(blocks)
                    wire = Wire(anthropic, lambda body, answer=answer: answer)
                    client = (anthropic.AsyncAnthropic if asynchronous else anthropic.Anthropic)(
                        api_key="authored-local-test",
                        http_client=wire.async_client() if asynchronous else wire.client(),
                        max_retries=0,
                    )
                    wrapped = (AsyncAnthropicVeil if asynchronous else AnthropicVeil)(
                        client, masker=masker()
                    )
                    kwargs = {
                        "model": MODEL,
                        "max_tokens": 64,
                        "messages": [{"role": "user", "content": ORIGINAL}],
                    }
                    try:
                        if streaming:
                            texts, tool_json = [], []
                            if asynchronous:
                                stream = await wrapped.create(**kwargs, stream=True)
                                async with stream as incoming:
                                    async for event in incoming:
                                        if event.type == "content_block_delta":
                                            if event.delta.type == "text_delta":
                                                texts.append(event.delta.text)
                                            elif event.delta.type == "input_json_delta":
                                                tool_json.append(event.delta.partial_json)
                            else:
                                with wrapped.create(**kwargs, stream=True) as incoming:
                                    for event in incoming:
                                        if event.type == "content_block_delta":
                                            if event.delta.type == "text_delta":
                                                texts.append(event.delta.text)
                                            elif event.delta.type == "input_json_delta":
                                                tool_json.append(event.delta.partial_json)
                            reply, tool = "".join(texts), json.loads("".join(tool_json))
                        else:
                            result = (
                                await wrapped.create(**kwargs)
                                if asynchronous
                                else wrapped.create(**kwargs)
                            )
                            reply, tool = result.content[0].text, result.content[1].input
                    finally:
                        if asynchronous:
                            await client.close()
                        else:
                            client.close()
                    expected = case["exactExpected"] if streaming else case["expected"]
                    checks = {
                        "maskedRequest": wire.requests[0]["messages"][0]["content"] == SURROGATE
                        and ORIGINAL not in wire.sent(),
                        "reply": reply == expected,
                        "toolValues": tool
                        == {"person": expected, "nested": [expected], "unchanged": 17},
                    }
                    sdk.append(
                        {
                            "name": case["name"],
                            "async": asynchronous,
                            "stream": streaming,
                            "requests": wire.requests,
                            "providerReply": blocks,
                            "restoredText": reply,
                            "restoredTool": tool,
                            "checks": checks,
                            "agrees": all(checks.values()),
                        }
                    )

    asyncio.run(run_sdk())

payload = {
    "label": args.label,
    "python": platform.python_version(),
    "unicodeDatabase": unicodedata.unidata_version,
    "scope": "Authored inputs, realistic surrogate index 48, native CLI and optional real Anthropic SDK over local mock HTTP. No observed model behavior or provider call.",
    "original": ORIGINAL,
    "generatedSurrogate": masked,
    "direct": {
        "cases": len(rows),
        "disagreements": sum(not row["agrees"] for row in rows),
        "results": rows,
    },
    "cli": {
        "cases": len(cli),
        "disagreements": sum(not row["agrees"] for row in cli),
        "results": cli,
    },
    "sdk": {
        "versions": versions,
        "cases": len(sdk),
        "disagreements": sum(not row["agrees"] for row in sdk),
        "results": sdk,
    },
}
args.out.parent.mkdir(parents=True, exist_ok=True)
args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
print(
    json.dumps(
        {
            key: {k: v for k, v in payload[key].items() if k != "results"}
            for key in ["direct", "cli", "sdk"]
        },
        indent=2,
    )
)
