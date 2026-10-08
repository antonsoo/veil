"""Collect technical text that holds almost no personal data: logs and source code.

    python3 studies/real-text/collect_technical.py
    python3 studies/real-text/collect_technical.py --held-out

Three bodies of text that people paste into a model every day, and that a
masking proxy in front of a coding agent sees all day:

- Loghub-2k: 2,000 lines of real system log from each of 16 systems
  (https://github.com/logpai/loghub, free for research with attribution).
- 60 console logs of Kubernetes CI builds, from the project's public bucket.
- The source trees of four well-known open-source projects at release tags.

Nothing is committed but manifest-technical.json: every URL and the SHA-256
of what it returned. The files go to studies/real-text/cache/.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import tarfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
USER_AGENT = "veil-study/1.0 (https://github.com/antonsoo/veil)"

LOGHUB_COMMIT = "dd61d0952749ee7963bde24220d1be5ede023033"
LOGHUB_SYSTEMS = (
    "HDFS", "Hadoop", "Spark", "Zookeeper", "OpenStack", "BGL", "HPC", "Thunderbird",
    "Windows", "Linux", "Mac", "Android", "HealthApp", "Apache", "OpenSSH", "Proxifier",
)  # fmt: skip

# The 30 most recent failed builds of each job on 8 October 2026 that also had
# a passing build of the same commit; the list is logdelta's study manifest.
KUBERNETES_BUCKET = "https://storage.googleapis.com/kubernetes-ci-logs/logs"
KUBERNETES_BUILDS = HERE / "kubernetes-builds.json"

# (repository, tag, licence)
REPOSITORIES = (
    ("psf/requests", "v2.32.3", "Apache-2.0"),
    ("pallets/flask", "3.0.3", "BSD-3-Clause"),
    ("expressjs/express", "4.21.0", "MIT"),
    ("gin-gonic/gin", "v1.10.0", "MIT"),
)
# Held out: fetched only after the detectors were changed, and not looked at
# before the numbers were final. Ten recent builds from each of four other CI
# jobs (linters, two end-to-end suites, a release build), four other projects.
HELD_OUT_JOBS = (
    "ci-kubernetes-verify-master",
    "ci-kubernetes-e2e-gci-gce",
    "ci-containerd-e2e-ubuntu-gce",
    "ci-kubernetes-build",
)
HELD_OUT_BUILDS = HERE / "kubernetes-builds-heldout.json"
HELD_OUT_REPOSITORIES = (
    ("pallets/click", "8.1.7", "BSD-3-Clause"),
    ("fastify/fastify", "v4.28.1", "MIT"),
    ("spf13/cobra", "v1.8.1", "Apache-2.0"),
    ("axios/axios", "v1.7.7", "MIT"),
)
MAX_LOG_BYTES = 30_000_000
TEXT_SUFFIXES = {
    ".py", ".js", ".ts", ".go", ".md", ".rst", ".txt", ".json", ".yml", ".yaml",
    ".toml", ".cfg", ".ini", ".sum", ".mod", ".html", ".css", ".sh",
}  # fmt: skip
MAX_FILE_BYTES = 400_000


def get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read()


def cached(target: Path, url: str) -> bytes:
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(get(url))
    return target.read_bytes()


def entry(kind: str, name: str, url: str, raw: bytes, **more: object) -> dict[str, object]:
    return {
        "kind": kind,
        "name": name,
        "url": url,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        **more,
    }


def recent_builds(job: str, count: int) -> list[str]:
    """The newest builds of a job whose console log is there and not enormous."""
    api = "https://storage.googleapis.com/storage/v1/b/kubernetes-ci-logs/o"
    builds: list[str] = []
    token = ""
    while True:
        page = json.loads(
            get(
                f"{api}?prefix=logs/{job}/&delimiter=/&maxResults=1000&fields=prefixes,nextPageToken{token}"
            )
        )
        builds += [prefix.rstrip("/").rsplit("/", 1)[-1] for prefix in page.get("prefixes", [])]
        if "nextPageToken" not in page:
            break
        token = "&pageToken=" + page["nextPageToken"]
    chosen: list[str] = []
    for build in sorted((b for b in builds if b.isdigit()), key=int, reverse=True)[
        1:
    ]:  # the newest may be running
        listing = json.loads(
            get(f"{api}?prefix=logs/{job}/{build}/build-log.txt&fields=items(name,size)")
        )
        sizes = [int(item["size"]) for item in listing.get("items", [])]
        if sizes and 10_000 < sizes[0] <= MAX_LOG_BYTES:
            chosen.append(build)
        if len(chosen) == count:
            break
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--held-out", action="store_true", help="collect the held-out logs and projects instead"
    )
    args = parser.parse_args()

    cache = HERE / "cache"
    files: list[dict[str, object]] = []

    if args.held_out:
        if not HELD_OUT_BUILDS.exists():
            picked = [[job, build] for job in HELD_OUT_JOBS for build in recent_builds(job, 10)]
            HELD_OUT_BUILDS.write_text(json.dumps(picked, indent=0) + "\n")
        builds = json.loads(HELD_OUT_BUILDS.read_text())
        repositories = HELD_OUT_REPOSITORIES
    else:
        for system in LOGHUB_SYSTEMS:
            url = f"https://raw.githubusercontent.com/logpai/loghub/{LOGHUB_COMMIT}/{system}/{system}_2k.log"
            raw = cached(cache / "loghub" / f"{system}_2k.log", url)
            files.append(entry("log", f"loghub/{system}_2k.log", url, raw))
        print(f"loghub: {len(LOGHUB_SYSTEMS)} files")
        builds = json.loads(KUBERNETES_BUILDS.read_text())
        repositories = REPOSITORIES

    for job, build in builds:
        url = f"{KUBERNETES_BUCKET}/{job}/{build}/build-log.txt"
        raw = cached(cache / "kubernetes" / f"{job}-{build}.log", url)
        files.append(entry("ci-log", f"kubernetes/{job}-{build}.log", url, raw))
    print(f"kubernetes: {len(builds)} build logs")

    for repository, tag, licence in repositories:
        url = f"https://codeload.github.com/{repository}/tar.gz/refs/tags/{tag}"
        archive = cached(cache / "tarballs" / f"{repository.replace('/', '-')}-{tag}.tar.gz", url)
        kept = 0
        # Members are read as bytes and written under names this script
        # chooses; nothing in the archive is extracted to a path it names.
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            for member in tar:
                path = Path(member.name)
                if (
                    not member.isfile()
                    or path.suffix not in TEXT_SUFFIXES
                    or member.size > MAX_FILE_BYTES
                ):
                    continue
                handle = tar.extractfile(member)
                if handle is None:
                    continue
                raw = handle.read()
                inner = "/".join(path.parts[1:])
                flat = hashlib.sha256(inner.encode()).hexdigest()[:16] + path.suffix
                target = cache / "code" / repository.replace("/", "-") / flat
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                files.append(
                    entry(
                        "code",
                        f"code/{repository.replace('/', '-')}/{flat}",
                        url,
                        raw,
                        path=inner,
                        repository=repository,
                    )
                )
                kept += 1
        print(
            f"{repository}@{tag} ({licence}): {kept} text files, tarball sha256 {hashlib.sha256(archive).hexdigest()[:16]}"
        )

    manifest = {
        "loghub": None
        if args.held_out
        else {"repository": "logpai/loghub", "commit": LOGHUB_COMMIT},
        "kubernetes": {"bucket": KUBERNETES_BUCKET, "builds": len(builds)},
        "repositories": [{"repository": r, "tag": t, "licence": lic} for r, t, lic in repositories],
        "files": files,
    }
    name = "manifest-technical-heldout.json" if args.held_out else "manifest-technical.json"
    (HERE / name).write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(f"{len(files)} files, {sum(int(f['bytes']) for f in files):,} bytes")  # type: ignore[call-overload]


if __name__ == "__main__":
    main()
