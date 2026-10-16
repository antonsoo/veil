"""Compare built/installed runtime bytes and retained replay behavior to source."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scratch", type=Path)
    parser.add_argument("--source-revision", required=True)
    args = parser.parse_args()
    scratch = args.scratch
    root = scratch / "clean/src/veil"
    runtime = {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and (p.suffix == ".py" or p.name == "py.typed")
    }
    hashes = {name: digest(raw) for name, raw in runtime.items()}
    artifacts = []
    for path in sorted((scratch / "artifacts").iterdir()):
        if not (path.name.endswith(".tar.gz") or path.suffix == ".whl"):
            continue
        if path.suffix == ".whl":
            with zipfile.ZipFile(path) as wheel:
                found = {
                    n.removeprefix("veil/"): wheel.read(n)
                    for n in wheel.namelist()
                    if n.startswith("veil/")
                }
        else:
            with tarfile.open(path) as sdist:
                found = {}
                for member in sdist.getmembers():
                    if "/src/veil/" in member.name and member.isfile():
                        stream = sdist.extractfile(member)
                        assert stream is not None
                        found[member.name.split("/src/veil/", 1)[1]] = stream.read()
        assert found == runtime, path.name
        artifacts.append(
            {
                "file": path.name,
                "bytes": path.stat().st_size,
                "sha256": digest(path.read_bytes()),
                "runtimeFilesMatch": len(runtime),
            }
        )
    assert len(artifacts) == 2
    expected = json.loads((HERE / "results/after.json").read_text())
    assert expected["runtimeFiles"] == hashes
    installed = []
    for name in ("clean-replay", "installed-current", "installed-floor", "installed-core"):
        report = json.loads((scratch / f"{name}.json").read_text())
        assert report["runtimeFiles"] == hashes
        assert report["cases"] == expected["cases"]
        if name != "installed-core":
            assert report["sdk"] == expected["sdk"]
            assert report["sdkTools"] == expected["sdkTools"]
        installed.append(
            {
                "label": name,
                "python": report["python"],
                "versions": report["versions"],
                "coreCases": len(report["cases"]),
                "sdkRequests": len(report["sdk"]) + len(report["sdkTools"]),
                "runtimeFilesMatch": len(runtime),
                "replayMatches": True,
            }
        )
    dist = scratch / "clean/web/dist"
    manifest = json.loads((dist / "veil-src.json").read_text())
    expected_manifest = {
        f"veil/{name}": raw.decode() for name, raw in runtime.items() if name.endswith(".py")
    }
    assert manifest == expected_manifest
    report = {
        "scope": __doc__,
        "sourceRevision": args.source_revision,
        "runtimeFiles": hashes,
        "artifacts": artifacts,
        "installed": installed,
        "browserPythonFilesMatch": len(manifest),
        "buildFiles": [
            {
                "file": str(p.relative_to(dist)),
                "bytes": p.stat().st_size,
                "sha256": digest(p.read_bytes()),
            }
            for p in sorted(dist.rglob("*"))
            if p.is_file()
        ],
    }
    (HERE / "results/verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"{len(runtime)} runtime files match source, sdist, wheel and all installations; {len(manifest)} Python modules match browser manifest"
    )


if __name__ == "__main__":
    main()
