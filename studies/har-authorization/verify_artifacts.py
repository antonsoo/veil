"""Compare reviewed source, built archives, installed runtime bytes and replays."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def hashes(files: dict[str, bytes]) -> dict[str, str]:
    return {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--floor", type=Path, required=True)
    parser.add_argument("--clean-replay", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    runtime = ROOT / "src/veil"
    source = {
        str(p.relative_to(runtime)): p.read_bytes()
        for p in sorted(runtime.rglob("*"))
        if p.is_file() and (p.suffix == ".py" or p.name == "py.typed")
    }
    expected = hashes(source)
    artifacts = []
    for path in sorted((args.clean / "dist").iterdir()):
        if path.suffix == ".whl":
            with zipfile.ZipFile(path) as wheel:
                found = {
                    name.removeprefix("veil/"): wheel.read(name)
                    for name in wheel.namelist()
                    if name.startswith("veil/")
                }
        elif path.name.endswith(".tar.gz"):
            with tarfile.open(path) as sdist:
                found = {}
                for member in sdist.getmembers():
                    if "/src/veil/" in member.name and member.isfile():
                        stream = sdist.extractfile(member)
                        assert stream is not None
                        found[member.name.split("/src/veil/", 1)[1]] = stream.read()
        else:
            continue
        assert found == source, path.name
        artifacts.append(
            {
                "file": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "runtimeFilesMatch": len(source),
            }
        )
    assert len(artifacts) == 2
    probe = """
import hashlib,json
from pathlib import Path
from importlib.metadata import distribution,version
from urllib.parse import unquote,urlparse
import veil
root=Path(veil.__file__).parent
files={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and (p.suffix=='.py' or p.name=='py.typed')}
origin=json.loads(distribution('veil-pii').read_text('direct_url.json'))
print(json.dumps({'runtimeFiles':files,'wheelFile':unquote(urlparse(origin['url']).path),'versions':{name:version(name) for name in ['veil-pii','openai','anthropic']}}))
"""
    installed = []
    wheel_hash = next(a["sha256"] for a in artifacts if a["file"].endswith(".whl"))
    for label, environment in [("current", args.current), ("floor", args.floor)]:
        result = json.loads(
            subprocess.run(
                [str(environment / "bin/python"), "-c", probe],
                check=True,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": ""},
            ).stdout
        )
        assert result.pop("runtimeFiles") == expected
        wheel_file = Path(result.pop("wheelFile"))
        assert wheel_file.resolve().parent == (args.clean / "dist").resolve()
        assert hashlib.sha256(wheel_file.read_bytes()).hexdigest() == wheel_hash
        installed.append(
            {
                "environment": label,
                "runtimeFilesMatch": len(source),
                "sourceWheelSha256": wheel_hash,
                **result,
            }
        )
    replays = []
    for path in [
        args.clean_replay,
        HERE / "results/installed-current.json",
        HERE / "results/installed-floor.json",
    ]:
        replay = json.loads(path.read_text())
        assert replay["sourceHashes"] == {k: v for k, v in expected.items() if k.endswith(".py")}
        assert replay["directFailures"] == replay["sdkFailures"] == 0
        assert len(replay["rows"]) == 6 and len(replay["sdk"]) == 48
        replays.append(
            {"file": path.name, "python": replay["python"], "directCases": 6, "sdkCases": 48}
        )
    manifest = json.loads((args.clean / "web/dist/veil-src.json").read_text())
    assert hashes(
        {key.removeprefix("veil/"): value.encode() for key, value in manifest.items()}
    ) == {key: value for key, value in expected.items() if key.endswith(".py")}
    report = {
        "scope": __doc__,
        "sourceRevision": args.source_revision,
        "runtimeFiles": expected,
        "artifacts": artifacts,
        "installed": installed,
        "replays": replays,
        "browserSourceModulesMatch": len(manifest),
        "published": False,
    }
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Verified {len(source)} runtime files across wheel, sdist and both installations.")


if __name__ == "__main__":
    main()
