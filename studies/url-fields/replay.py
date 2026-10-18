"""Replay actual client URL strings; HTTP acceptance never determines masking."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--observe-only", action="store_true")
    args = parser.parse_args()
    if args.src:
        sys.path.insert(0, str(args.src.resolve()))
    import veil
    from veil import Masker, Restorer
    from veil.integrations._common import mask_value, restore_value
    from veil.integrations._json_arguments import mask_arguments, restore_arguments

    package = Path(veil.__file__).resolve().parent
    assert package.is_relative_to(args.src.resolve() if args.src else Path(sys.prefix).resolve())
    capture_bytes = (HERE / "capture.json").read_bytes()
    capture = json.loads(capture_bytes)
    rows = []
    for item in capture["cases"]:
        for mode in ["text", "arguments", "typed"]:
            masker = Masker()
            source = item["url"]
            if mode == "text":
                masked = masker.mask(source)
                assert masker.restore(masked, tolerant=False) == source
                restorer = Restorer(masker.vault)
                assert "".join(restorer.feed(c) for c in masked) + restorer.flush() == source
            elif mode == "arguments":
                argument = '{ "uri":' + json.dumps(source) + ', "n":1.2300e+40, "n":2 }'
                result = mask_arguments(argument, masker)
                assert restore_arguments(result, masker) == argument
                masked = json.loads(result)["uri"]
            else:
                result2 = mask_value({"uri": source}, masker)
                assert restore_value(result2, masker) == {"uri": source}
                masked = result2["uri"]
            private = masked == "⟨URL_CREDENTIAL_1⟩"
            if private:
                assert len(masker.vault) == 1
                assert list(masker.vault.mappings())[0].original == source
            rows.append(
                {
                    "producer": item["producer"],
                    "field": item["field"],
                    "httpStatus": item["status"],
                    "mode": mode,
                    "protectedWholeUrl": private,
                    "exactRestoration": True,
                    "masked": masked,
                }
            )
    receipt = {
        "scope": __doc__,
        "python": platform.python_version(),
        "captureSha256": hashlib.sha256(capture_bytes).hexdigest(),
        "runtimeFiles": {
            str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(package.rglob("*.py"))
        },
        "failures": sum(not row["protectedWholeUrl"] for row in rows),
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"workflows": len(rows), "failures": receipt["failures"]}))
    if not args.observe_only:
        assert receipt["failures"] == 0


if __name__ == "__main__":
    main()
