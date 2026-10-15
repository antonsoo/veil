"""Verify an existing clean build, wheel/sdist, installs and browser receipt.

This performs no installation, build, publication or network operation.
Installation and replay arguments use LABEL=PATH (repeat for each environment).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tarfile
import zipfile
from pathlib import Path


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def pairs(values: list[str]) -> dict[str, Path]:
    return {label: Path(path) for label, path in (value.split("=", 1) for value in values)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", type=Path, required=True)
    parser.add_argument("--commit", required=True, help="commit exported into the clean directory")
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--installation", action="append", default=[])
    parser.add_argument("--replay", action="append", default=[])
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--browser", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = {
        "veil/" + path.relative_to(args.clean / "src/veil").as_posix(): digest(path.read_bytes())
        for path in (args.clean / "src/veil").rglob("*")
        if path.is_file() and (path.suffix == ".py" or path.name == "py.typed")
    }
    (wheel,) = args.artifacts.glob("*.whl")
    (sdist,) = args.artifacts.glob("*.tar.gz")
    with zipfile.ZipFile(wheel) as archive:
        assert {name: digest(archive.read(name)) for name in source} == source
    with tarfile.open(sdist) as archive:
        members = {
            m.name.split("/src/", 1)[1]: m
            for m in archive.getmembers()
            if "/src/" in m.name and m.isfile()
        }
        for name, expected in source.items():
            handle = archive.extractfile(members[name])
            assert handle is not None and digest(handle.read()) == expected
    installed = []
    probe = """
import hashlib, json, sys
from pathlib import Path
import veil
root = Path(veil.__file__).parent
print(json.dumps({'python': sys.version.split()[0], 'files': {
    'veil/' + p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in root.rglob('*') if p.is_file() and (p.suffix == '.py' or p.name == 'py.typed')
}}))
"""
    for label, path in pairs(args.installation).items():
        actual = json.loads(
            subprocess.check_output([str(path / "bin/python"), "-I", "-c", probe], text=True)
        )
        assert actual["files"] == source, label
        installed.append({"label": label, "python": actual["python"], "allRuntimeFilesMatch": True})
    reference = json.loads(args.reference.read_text())
    replays = []
    for label, path in pairs(args.replay).items():
        actual = json.loads(path.read_text())
        assert actual["cases"] == reference["cases"], label
        if actual["sdk"]:
            assert actual["sdk"] == reference["sdk"], label
        replays.append(
            {
                "label": label,
                "sha256": digest(path.read_bytes()),
                "python": actual["python"],
                "casesMatchSource": True,
                "sdkRequests": len(actual["sdk"]),
                "sdkVersions": actual["sdkVersions"],
            }
        )
    manifest = args.clean / "web/dist/veil-src.json"
    bundled = {
        name: digest(value.encode()) for name, value in json.loads(manifest.read_text()).items()
    }
    assert bundled == {name: value for name, value in source.items() if name.endswith(".py")}
    browser = json.loads(args.browser.read_text())
    assert browser["sourceSha256"] == source[browser.get("sourceModule", "veil/detectors/email.py")]
    assert browser["manifestSha256"] == digest(manifest.read_bytes())
    assert browser["servedAssetsMatch"]
    for path, expected in browser["receivedAssets"].items():
        relative = path.removeprefix("/veil/") or "index.html"
        assert digest((args.clean / "web/dist" / relative).read_bytes()) == expected
    report = {
        "cleanCommit": args.commit,
        "artifacts": [
            {"name": path.name, "bytes": path.stat().st_size, "sha256": digest(path.read_bytes())}
            for path in (wheel, sdist)
        ],
        "runtimeFiles": source,
        "installations": installed,
        "replays": replays,
        "browser": {
            "sha256": digest(args.browser.read_bytes()),
            "rows": browser["rows"],
            "manifestMatchesCleanSource": True,
            "servedAssetsMatchCleanBuild": True,
        },
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"{len(source)} runtime files match sdist, wheel, {len(installed)} installations and browser; replays match"
    )


if __name__ == "__main__":
    main()
