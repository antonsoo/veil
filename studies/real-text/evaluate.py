"""Run veil over the collected text and count what it masks.

    uv run python studies/real-text/evaluate.py                # this checkout
    # the released package, from a directory outside the repository:
    uv run --no-project --with veil-pii==0.4.4 python -I \
        /path/to/veil/studies/real-text/evaluate.py --label 0.4.4

Three parts, all through `Masker.find_entities`, which is what `mask()` uses.

Technical text (logs, CI output, source code): every detection is recorded with
its surroundings, and `triage.py` sorts them into what they really are.

OpenStreetMap places: each place is rendered as one GeoJSON feature, the form
an export has. The tag key says which values are phone numbers and which are
email addresses, so for each such value the question is whether veil covered
it, and for every other detection, what it covered instead.

Generated tokens: uniformly random strings of several alphabets and lengths,
which is what an unprefixed API key is; the share masked whole.

Results go to results.json under the label; detections go to
cache/detections-<label>.jsonl for triage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import string
from collections import Counter, defaultdict
from importlib.metadata import version
from pathlib import Path
from typing import Any

from veil.detectors import AddressDetector, default_detectors
from veil.masker import Masker

HERE = Path(__file__).parent
CACHE = HERE / "cache"
PER_CITY = 1000  # places sampled per city, by hash of their id

PHONE_KEY_PARTS = {"phone", "fax", "mobile", "whatsapp", "telephone", "tel", "sms"}
EMAIL_KEY_PARTS = {"email", "mail"}
US_STYLE = {"US", "CA"}  # where an address line is written "<number> <street>"
EXTENSION_RE = re.compile(r"\s*(?:#|;?ext\.?|extension|x|p)\s*\.?\s*\d", re.IGNORECASE)


def words(text: str) -> int:
    return len(text.split())


# --- technical text ---------------------------------------------------------


def corpus_of(name: str) -> str:
    parts = name.split("/")
    return parts[0] if parts[0] != "code" else f"code: {parts[1]}"


def technical(masker: Masker, dump: Any, manifest_name: str, part: str) -> dict[str, Any]:
    manifest = json.loads((HERE / manifest_name).read_text())
    out: dict[str, Any] = defaultdict(
        lambda: {"files": 0, "words": 0, "by_type": Counter(), "by_detector": Counter()}
    )
    for item in manifest["files"]:
        text = (CACHE / item["name"]).read_text(encoding="utf-8", errors="replace")
        corpus = out[corpus_of(item["name"])]
        corpus["files"] += 1
        corpus["words"] += words(text)
        for entity in masker.find_entities(text):
            corpus["by_type"][entity.type.value] += 1
            corpus["by_detector"][entity.detector] += 1
            start, end = entity.span.start, entity.span.end
            dump.write(
                json.dumps(
                    {
                        "part": part,
                        "corpus": corpus_of(item["name"]),
                        "file": item.get("path", item["name"]),
                        "type": entity.type.value,
                        "detector": entity.detector,
                        "value": text[start:end],
                        "before": text[max(0, start - 60) : start],
                        "after": text[end : end + 30],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return {
        name: {
            **corpus,
            "by_type": dict(corpus["by_type"].most_common()),
            "by_detector": dict(corpus["by_detector"].most_common()),
        }
        for name, corpus in out.items()
    }


# --- OpenStreetMap ----------------------------------------------------------


def key_kind(key: str) -> str | None:
    parts = set(re.split(r"[:_]", key.lower()))
    if parts & PHONE_KEY_PARTS or any(p.startswith("phone") for p in parts):
        return "phone"
    if parts & EMAIL_KEY_PARTS:
        return "email"
    return None


def digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def shape(value: str) -> str:
    """The value with every digit written d: its format without the number."""
    return re.sub(r"\d", "d", value)


def render(element: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """One GeoJSON feature on one line, and where each labelled value sits in it."""
    centre = element.get("center") or element
    place = f'"{element["type"]}/{element["id"]}"'
    point = f"[{centre.get('lon')}, {centre.get('lat')}]"
    head = f'{{"type": "Feature", "id": {place}, "geometry": {{"type": "Point", "coordinates": {point}}}, "properties": {{'
    line = head
    gold: list[dict[str, Any]] = []
    first = True
    for key, value in element.get("tags", {}).items():
        if not first:
            line += ", "
        first = False
        line += json.dumps(key, ensure_ascii=False) + ": "
        encoded = json.dumps(value, ensure_ascii=False)
        kind = key_kind(key)
        if kind and encoded[1:-1] == value:  # no escapes, so offsets carry over
            offset = len(line) + 1
            position = 0
            for piece in value.split(";"):
                stripped = piece.strip()
                if stripped:
                    start = offset + position + piece.index(stripped)
                    gold.append(
                        {
                            "kind": kind,
                            "key": key,
                            "value": stripped,
                            "start": start,
                            "end": start + len(stripped),
                        }
                    )
                position += len(piece) + 1
        line += encoded
    return line + "}}", gold


def sample(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(
        elements, key=lambda e: hashlib.sha256(f"{e['type']}/{e['id']}".encode()).hexdigest()
    )
    return ranked[:PER_CITY]


def phone_class(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("+") or stripped.startswith("00"):
        return "international"
    return "national"


def coverage(
    line: str, start: int, end: int, entities: list[Any], want: str
) -> tuple[str, str | None]:
    """How much of a labelled value veil covered: its digits for a phone, all of it for an email."""
    if want == "PHONE":
        wanted = [i for i in range(start, end) if line[i].isdigit()]
    else:
        wanted = list(range(start, end))
    covering = [e for e in entities if e.span.start < end and start < e.span.end]
    covered = [i for i in wanted if any(e.span.start <= i < e.span.end for e in covering)]
    if not covered:
        return "missed", None
    types = sorted({e.type.value for e in covering})
    if len(covered) < len(wanted):
        # "+886 2 2345 6789 #12", "+66 2 214 6630 p 104", "... Ext. 2205": the
        # number is masked and only the extension after it is left.
        extension = EXTENSION_RE.search(line, start, end)
        if (
            want == "PHONE"
            and extension is not None
            and len(covering) == 1
            and covering[0].type.value == want
            and all(i in covered for i in wanted if i < extension.start())
            and not any(i in covered for i in wanted if i >= extension.start())
        ):
            return "found, extension left", want
        return "partly", "+".join(types)
    if len(covering) == 1 and covering[0].type.value == want:
        return "found", want
    if all(e.type.value == want for e in covering):
        return "in pieces", want
    return "as another type", "+".join(types)


def osm(
    masker: Masker, address: AddressDetector, dump: Any, manifest_name: str, part: str
) -> dict[str, Any]:
    manifest = json.loads((HERE / manifest_name).read_text())
    phones: dict[str, Counter[str]] = defaultdict(Counter)
    phone_shapes: dict[str, Counter[str]] = defaultdict(Counter)
    emails: Counter[str] = Counter()
    elsewhere: Counter[str] = Counter()
    elsewhere_keys: dict[str, Counter[str]] = defaultdict(Counter)
    addresses: dict[str, Counter[str]] = defaultdict(Counter)
    places = 0
    total_words = 0
    for city in manifest["cities"]:
        country = city["country"]
        elements = json.loads((CACHE / "osm" / city["file"]).read_text(encoding="utf-8"))[
            "elements"
        ]
        for element in sample(elements):
            line, gold = render(element)
            places += 1
            total_words += words(line)
            entities = masker.find_entities(line)
            for item in gold:
                if item["kind"] == "phone":
                    if len(digits(item["value"])) < 7:
                        phones[country]["not a full number"] += 1
                        continue
                    outcome, types = coverage(line, item["start"], item["end"], entities, "PHONE")
                    cls = phone_class(item["value"])
                    phones[country][f"{cls}: {outcome}"] += 1
                    phone_shapes[f"{country} {cls}: {outcome}"][shape(item["value"])] += 1
                    dump.write(
                        json.dumps(
                            {
                                "part": part + "-phone",
                                "country": country,
                                "class": cls,
                                "outcome": outcome,
                                "as": types,
                                "value": item["value"],
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                else:
                    if "@" not in item["value"]:
                        emails["not an address"] += 1
                        continue
                    outcome, types = coverage(line, item["start"], item["end"], entities, "EMAIL")
                    emails[outcome] += 1
                    if outcome != "found":
                        dump.write(
                            json.dumps(
                                {
                                    "part": part + "-email",
                                    "outcome": outcome,
                                    "as": types,
                                    "value": item["value"],
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
            # Everything veil masked that no phone or email label accounts for.
            spans = [(g["start"], g["end"]) for g in gold]
            for entity in entities:
                if any(entity.span.start < end and start < entity.span.end for start, end in spans):
                    continue
                elsewhere[entity.type.value] += 1
                before = line[: entity.span.start]
                keys = re.findall(r'"([^"]+)": (?:"[^"]*)?$', before)
                key = keys[-1] if keys else "(id or coordinates)"
                elsewhere_keys[entity.type.value][key] += 1
                dump.write(
                    json.dumps(
                        {
                            "part": part + "-other",
                            "country": country,
                            "type": entity.type.value,
                            "detector": entity.detector,
                            "key": key,
                            "value": line[entity.span.start : entity.span.end],
                            "before": line[max(0, entity.span.start - 60) : entity.span.start],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            # The opt-in address detector, on address lines written the way its
            # country writes them, from the place's own house number and street.
            tags = element.get("tags", {})
            if country in US_STYLE and tags.get("addr:housenumber") and tags.get("addr:street"):
                written = f"{tags['addr:housenumber']} {tags['addr:street']}"
                text = f"Deliver to {written}, {tags.get('addr:city', city['city'])}."
                found = [
                    e
                    for e in address.find(text)
                    if e.span.start <= 11 and e.span.end >= 11 + len(written)
                ]
                partial = [
                    e
                    for e in address.find(text)
                    if e.span.start < 11 + len(written) and e.span.end > 11
                ]
                outcome = "found" if found else "partly" if partial else "missed"
                addresses[country][outcome] += 1
                dump.write(
                    json.dumps(
                        {
                            "part": part + "-address",
                            "country": country,
                            "outcome": outcome,
                            "value": written,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    return {
        "places": places,
        "words": total_words,
        "phones": {country: dict(sorted(counts.items())) for country, counts in phones.items()},
        "phone_shapes": {
            group: dict(counts.most_common(12)) for group, counts in sorted(phone_shapes.items())
        },
        "emails": dict(emails),
        "elsewhere": dict(elsewhere.most_common()),
        "elsewhere_keys": {
            kind: dict(counts.most_common(15)) for kind, counts in elsewhere_keys.items()
        },
        "addresses": {country: dict(counts) for country, counts in addresses.items()},
    }


# --- generated tokens -------------------------------------------------------

ALPHABETS = {
    "base32": "abcdefghijklmnopqrstuvwxyz234567",
    "base36": string.ascii_lowercase + string.digits,
    "base62": string.ascii_letters + string.digits,
    "base64url": string.ascii_letters + string.digits + "-_",
}
TOKEN_LENGTHS = (20, 24, 32, 40)
TOKENS_EACH = 2000


def random_tokens(masker: Masker) -> dict[str, dict[str, float]]:
    """Share of uniformly random tokens masked whole, by alphabet and length.

    A key a provider issues is random by construction, so tokens drawn here
    are the real distribution of unprefixed keys, not an imitation of it.
    """
    rng = random.Random(20261008)
    out: dict[str, dict[str, float]] = {}
    for name, alphabet in ALPHABETS.items():
        out[name] = {}
        for length in TOKEN_LENGTHS:
            found = 0
            for _ in range(TOKENS_EACH):
                text = "token " + "".join(rng.choice(alphabet) for _ in range(length)) + " end"
                found += any(
                    e.span.start <= 6 and e.span.end >= 6 + length
                    for e in masker.find_entities(text)
                )
            out[name][str(length)] = round(100 * found / TOKENS_EACH, 1)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--label", default="checkout", help="name for this run in results.json")
    args = parser.parse_args()

    masker = Masker(detectors=default_detectors())
    results_path = HERE / "results.json"
    results = json.loads(results_path.read_text()) if results_path.exists() else {}
    run: dict[str, Any] = {"veil": version("veil-pii")}
    with (CACHE / f"detections-{args.label}.jsonl").open("w", encoding="utf-8") as dump:
        run["technical"] = technical(masker, dump, "manifest-technical.json", "technical")
        run["osm"] = osm(masker, AddressDetector(), dump, "manifest-osm.json", "osm")
        if (HERE / "manifest-technical-heldout.json").exists():
            run["technical_heldout"] = technical(
                masker, dump, "manifest-technical-heldout.json", "technical_heldout"
            )
        if (HERE / "manifest-osm-heldout.json").exists():
            run["osm_heldout"] = osm(
                masker, AddressDetector(), dump, "manifest-osm-heldout.json", "osm_heldout"
            )
    run["random_tokens"] = random_tokens(masker)
    results[args.label] = run
    results_path.write_text(
        json.dumps(results, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )

    for part in ("technical", "technical_heldout"):
        for name, corpus in run.get(part, {}).items():
            rates = ", ".join(f"{kind} {n}" for kind, n in corpus["by_type"].items())
            print(f"{part} / {name}: {corpus['files']} files, {corpus['words']:,} words: {rates}")
    print("random tokens masked whole, %:", run["random_tokens"])
    for part in ("osm", "osm_heldout"):
        if part in run:
            totals: Counter[str] = Counter()
            for counts in run[part]["phones"].values():
                totals.update(counts)
            print(f"{part}: {run[part]['places']:,} places; phones {dict(sorted(totals.items()))}")
            print(
                f"  emails {run[part]['emails']}; elsewhere {run[part]['elsewhere']}; addresses {run[part]['addresses']}"
            )


if __name__ == "__main__":
    main()
