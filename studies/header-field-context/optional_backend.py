"""The same invented-label boundary through the real optional spaCy backend."""

from __future__ import annotations

import argparse
import json
import runpy
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--observe-only", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(args.src.resolve()))
    import spacy

    import veil
    from veil import Masker
    from veil.backends.spacy_backend import SpacyBackend
    from veil.integrations._json_arguments import mask_string_value

    assert Path(veil.__file__).resolve().is_relative_to(args.src.resolve())
    capture = runpy.run_path(str(HERE.parent / "http-authorization/sdk_tools.py"))[
        "sdk_tool_capture"
    ]
    with tempfile.TemporaryDirectory(prefix="veil-header-model-") as temporary:
        nlp = spacy.blank("en")
        ruler = nlp.add_pipe("entity_ruler")
        patterns = [{"label": "ORG", "pattern": "Authorization:"}]
        ruler.add_patterns(patterns)
        nlp.to_disk(temporary)
        backend = SpacyBackend(model=temporary)
        masker = Masker(name_backends=[backend])
        source = "Bearer abc"
        masked = mask_string_value(source, masker, key="Authorization")
        direct = {
            "source": source,
            "masked": masked,
            "restored": masker.restore(masked),
            "vault": json.loads(masker.vault.to_json()),
        }
        raw = '{"Authorization":"Bearer abc"}'
        expected = raw.replace("Bearer abc", "Bearer ⟨SECRET_1⟩")
        sdk = [
            capture(
                api,
                False,
                False,
                source=raw,
                expected=expected,
                tool_reply=True,
                masker=Masker(name_backends=[backend]),
                assert_roundtrip=False,
            )
            for api in ["chat", "responses", "anthropic"]
        ]
        correct = masked == "Bearer ⟨SECRET_1⟩" and direct["restored"] == source
        correct = correct and all(row["correct"] and row["restoresExactly"] for row in sdk)
        args.out.write_text(
            json.dumps(
                {
                    "scope": (
                        "Actual spaCy installation/loading/tokenization/entity ruler and SDK "
                        "mock transports; synthetic rule, no NER accuracy or provider/model calls."
                    ),
                    "spacy": version("spacy"),
                    "patterns": patterns,
                    "direct": direct,
                    "sdk": sdk,
                    "all_correct": correct,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        print(f"Real spaCy backend, one direct and three SDK paths: {correct=}")
        if not args.observe_only:
            assert correct and len(direct["vault"]["mappings"]) == 1


if __name__ == "__main__":
    main()
