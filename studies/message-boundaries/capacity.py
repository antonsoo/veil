"""Retain replay-eviction counterexamples using synthetic responses through the real SDK."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path)
parser.add_argument("--label", default="installed")
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if args.source:
    sys.path.insert(0, str(args.source.resolve() / "src"))

import anthropic  # noqa: E402

from tests.sdk_wire import MODEL, Wire, anthropic_message  # noqa: E402
from veil.integrations._common import ReplayCache  # noqa: E402
from veil.integrations.anthropic import AnthropicVeil  # noqa: E402
from veil.vault import VaultError  # noqa: E402

results: list[dict[str, Any]] = []


def record(case: str, checks: dict[str, bool], **evidence: Any) -> None:
    results.append({"case": case, **evidence, "checks": checks, "agrees": all(checks.values())})


for form in ("old-object", "recent-object", "recent-copy", "recent-blocks"):
    originals = ["Mailing ⟨EMAIL_1⟩.", "Mailing ⟨email_1⟩."]
    texts = iter([originals[0], *(f"Unrelated reply {i}" for i in range(6)), originals[1], "Done"])
    wire = Wire(
        anthropic,
        lambda body, texts=texts: anthropic_message([{"type": "text", "text": next(texts)}]),
    )
    with anthropic.Anthropic(
        api_key="synthetic-local-test", http_client=wire.client(), max_retries=0
    ) as client:
        wrapper = AnthropicVeil(client)
        wrapper.replay = ReplayCache(max_entries=8)
        prompt = [{"role": "user", "content": "Email alice@example.com."}]
        first = wrapper.create(model=MODEL, max_tokens=64, messages=prompt)
        for _ in range(7):
            recent = wrapper.create(model=MODEL, max_tokens=64, messages=prompt)
        content = {
            "old-object": first.content,
            "recent-object": recent.content,
            "recent-copy": deepcopy(recent.content),
            "recent-blocks": list(recent.content),
        }[form]
        error = None
        sent = None
        try:
            wrapper.create(
                model=MODEL,
                max_tokens=64,
                messages=[*prompt, {"role": "assistant", "content": content}],
            )
            sent = wire.requests[-1]["messages"][1]["content"][0]["text"]
        except VaultError as failure:
            error = str(failure)
    should_refuse = form in ("old-object", "recent-copy")
    record(
        f"anthropic/eviction/{form}",
        {
            "retains_source_or_refuses": error is not None and len(wire.requests) == 8
            if should_refuse
            else sent == originals[1]
        },
        original_texts=originals,
        sent_text=sent,
        error=error,
        requests_sent=len(wire.requests),
    )

# Default capacity, without SDK serialization aliases: a forgotten occurrence
# and a newly retained one have equal restored content but different originals.
cache = ReplayCache()
first_value = {"text": "Same restored response"}
cache.remember(first_value, {"text": "First provider spelling"})
for index in range(10_000):
    cache.remember({"text": f"Unique {index}"}, {"text": f"Unique {index}"})
last_value = {"text": "Same restored response"}
cache.remember(last_value, {"text": "Second provider spelling"})
error = None
replayed = None
try:
    replayed = cache.original_for(first_value)
except VaultError as failure:
    error = str(failure)
record(
    "default-capacity/forgotten-original",
    {
        "refuses_lost_identity": error is not None,
        "retains_recent_identity": cache.original_for(last_value)
        == {"text": "Second provider spelling"},
        "bounded": len(cache) == 10_000,
    },
    replayed_old_value=replayed,
    error=error,
    retained_content_entries=len(cache),
)

receipt = {
    "label": args.label,
    "python": platform.python_version(),
    "anthropic_sdk": importlib.metadata.version("anthropic"),
    "scope": "Synthetic local SDK captures and a default-capacity cache control. No provider calls.",
    "cases": len(results),
    "disagreements": sum(not row["agrees"] for row in results),
    "results": results,
}
print(json.dumps(receipt, ensure_ascii=False, indent=2))
if args.check and receipt["disagreements"]:
    raise SystemExit(1)
