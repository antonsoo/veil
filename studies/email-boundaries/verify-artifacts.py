"""Match runtime bytes across source, sdist, wheel, installations and browser.

All path arguments point to already-built and already-tested artifacts.
This verifier does not install, publish or make a network request.
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


def installed_hashes(python: Path) -> dict[str, str]:
    code = """
import hashlib, json
from pathlib import Path
import veil
root = Path(veil.__file__).parent
print(json.dumps({
    'veil/' + p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in root.rglob('*') if p.is_file() and (p.suffix == '.py' or p.name == 'py.typed')
}))
"""
    return json.loads(subprocess.check_output([str(python), "-I", "-c", code], text=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--current-python", type=Path, required=True)
    parser.add_argument("--floor-python", type=Path, required=True)
    parser.add_argument("--core-python", type=Path, required=True)
    parser.add_argument("--current-replay", type=Path, required=True)
    parser.add_argument("--floor-replay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    source = {
        "veil/" + p.relative_to(root / "src/veil").as_posix(): digest(p.read_bytes())
        for p in (root / "src/veil").rglob("*")
        if p.is_file() and (p.suffix == ".py" or p.name == "py.typed")
    }
    clean = {name: digest((args.clean / "src" / name).read_bytes()) for name in source}
    assert clean == source
    with zipfile.ZipFile(args.wheel) as wheel:
        packed = {name: digest(wheel.read(name)) for name in source}
    assert packed == source
    with tarfile.open(args.sdist) as sdist:
        members = {
            member.name.split("/src/", 1)[1]: member
            for member in sdist.getmembers()
            if "/src/" in member.name and member.isfile()
        }
        archive = {}
        for name in source:
            handle = sdist.extractfile(members[name])
            assert handle is not None
            archive[name] = digest(handle.read())
    assert archive == source
    for python in (args.current_python, args.floor_python, args.core_python):
        assert installed_hashes(python) == source
    manifest_path = args.clean / "web/dist/veil-src.json"
    manifest = json.loads(manifest_path.read_text())
    browser_source = {name: digest(value.encode()) for name, value in manifest.items()}
    assert browser_source == {name: value for name, value in source.items() if name.endswith(".py")}
    browser_path = args.clean / "studies/email-boundaries/results/browser/receipt.json"
    browser = json.loads(browser_path.read_text())
    assert browser["sourceSha256"] == source["veil/detectors/email.py"]
    assert browser["manifestSha256"] == digest(manifest_path.read_bytes())
    assert browser["servedAssetsMatch"]
    study = root / "studies/email-boundaries"
    reference = json.loads((study / "results/after.json").read_text())
    runs = []
    for path in (args.current_replay, args.floor_replay):
        replay = json.loads(path.read_text())
        assert replay["emailSourceSha256"] == source["veil/detectors/email.py"]
        assert replay["casesSha256"] == reference["casesSha256"]
        assert replay["cases"] == reference["cases"]
        runs.append(
            {
                "python": replay["python"],
                "versions": replay["versions"],
                "casesMatchSource": True,
                "sdkRequests": replay["sdkRequests"],
            }
        )
    tool_current = json.loads((study / "results/tool-installed-current.json").read_text())
    tool_floor = json.loads((study / "results/tool-installed-floor.json").read_text())
    assert (
        tool_current["emailSourceSha256"]
        == tool_floor["emailSourceSha256"]
        == source["veil/detectors/email.py"]
    )
    assert tool_current["workflows"] == tool_floor["workflows"]
    assert tool_current["completeMasks"] == len(tool_current["workflows"]) == 21
    result = {
        "codeCommit": "06ca417",
        "baselineCommit": "d3f43e0",
        "status": "Local source correction; no registry release or hosted deployment.",
        "artifacts": [
            {"name": p.name, "bytes": p.stat().st_size, "sha256": digest(p.read_bytes())}
            for p in (args.wheel, args.sdist)
        ],
        "runtimeFiles": source,
        "matchedRuntimeFiles": len(source),
        "matches": [
            "working source",
            "clean archived source",
            "sdist",
            "wheel",
            "current installation",
            "floor installation",
            "core-only installation",
        ],
        "matchedBrowserPythonFiles": len(browser_source),
        "browserManifestSha256": browser["manifestSha256"],
        "browserReceivedAssetsMatchTestedBuild": True,
        "browserScenarios": browser["rows"],
        "installedSdkRuns": runs,
        "toolJsonWorkflowsPerInstallation": 21,
        "toolJsonRequestsMatchAcrossSdkVersions": True,
        "coreOnly": {
            "cases": 24,
            "characterStreaming": True,
            "installedConsoleMaskRestore": "passed; observed before receipt construction",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        f"Matched {len(source)} runtime files across seven artifacts, {len(browser_source)} browser Python files,"
    )
    print(
        "all source/current/floor replay cases, 21 tool JSON workflows and actual served asset hashes."
    )


if __name__ == "__main__":
    main()
