#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
"""Prepare the commit-pinned development gateway; stdout is its absolute path.

Development trusts the operator's authenticated GitHub access or local Git
objects. This does not supply or relax the production release checksum pins.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile

from sparkrun.plugins.sparkroute import release

ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_ERRORS = (OSError, ValueError, subprocess.SubprocessError, release.GatewayReleaseError, tarfile.TarError, zipfile.BadZipFile)


def log(message: str) -> None:
    print("[sparkroute-dev] " + message, file=sys.stderr, flush=True)


def run(command: list[str], **kwargs) -> str:
    """Never let child output pollute the path returned to the sourcing shell."""
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=sys.stderr, text=True, check=True, **kwargs)
    return result.stdout.strip()


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_identity(info: dict, version: str, commit: str) -> None:
    if not isinstance(info, dict) or any(
        info.get(key) != value
        for key, value in {
            "name": "sparkroute",
            "version": version,
            "commit": commit,
            "license": "AGPL-3.0-only",
            "source": "https://github.com/sparksq/sparkroute/tree/" + commit,
        }.items()
    ):
        raise ValueError("gateway build identity does not match compat/gateway.toml")


def check_binary(binary: Path, version: str, commit: str) -> None:
    check_identity(json.loads(run([str(binary), "--build-info"], timeout=30)), version, commit)


def unpack_download(directory: Path, binary: Path, version: str, commit: str, target: tuple[str, str]) -> None:
    asset = release.asset_name(version, *target)
    archive = directory / asset
    if archive.stat().st_size > release.MAX_DOWNLOAD_BYTES:
        raise ValueError("gateway archive exceeds download size limit")
    checksums = (directory / "checksums.txt").read_text(encoding="utf-8").splitlines()
    matches = [line.split() for line in checksums if len(line.split()) == 2 and line.split()[1] == asset]
    if len(matches) != 1 or not re.fullmatch(r"[0-9a-f]{64}", matches[0][0]) or digest(archive) != matches[0][0]:
        raise ValueError("gateway archive checksum mismatch or missing/duplicate checksum")
    opener = release._open_zip_member if target[0] == "windows" else release._open_tar_member
    with opener(archive, "build-info.json") as stream:
        info = json.loads(stream.read(65537))
    # Check archive identity before extracting or executing its binary.
    check_identity(info, version, commit)
    release._extract_binary(archive, target[0], binary)
    check_binary(binary, version, commit)


def github_binary(directory: Path, binary: Path, version: str, commit: str, target: tuple[str, str]) -> str | None:
    if not shutil.which("gh"):
        log("GitHub CLI is unavailable; trying the pinned source build.")
        return None
    repo = release.SPARKROUTE_REPO
    asset = release.asset_name(version, *target)
    # A tag can move independently of the source pin. Require both the resolved
    # tag commit and the archived build identity to agree with that pin.
    try:
        tag_commit = run(["gh", "api", f"repos/{repo}/commits/v{version}", "--jq", ".sha"], timeout=60)
        if tag_commit == commit:
            release_dir = directory / "release"
            release_dir.mkdir()
            log(f"Trying GitHub release v{version} for {commit[:12]} ...")
            run(
                [
                    "gh",
                    "release",
                    "download",
                    f"v{version}",
                    "--repo",
                    repo,
                    "--dir",
                    str(release_dir),
                    "--pattern",
                    asset,
                    "--pattern",
                    "checksums.txt",
                ],
                timeout=180,
            )
            unpack_download(release_dir, binary, version, commit, target)
            return f"github-release:v{version}"
    except DOWNLOAD_ERRORS as error:
        log(f"Matching release unavailable: {error}")
    try:
        runs = json.loads(
            run(
                [
                    "gh",
                    "run",
                    "list",
                    "--repo",
                    repo,
                    "--workflow",
                    "publish-go.yml",
                    "--commit",
                    commit,
                    "--status",
                    "success",
                    "--json",
                    "databaseId,headSha",
                    "--limit",
                    "5",
                ],
                timeout=60,
            )
        )
        for workflow in runs:
            if workflow["headSha"] != commit:
                continue
            run_id = str(int(workflow["databaseId"]))
            artifact_dir = directory / ("run-" + run_id)
            artifact_dir.mkdir()
            try:
                log(f"Trying GitHub Actions distributions from run {run_id} ...")
                run(
                    ["gh", "run", "download", run_id, "--repo", repo, "--name", "sparkroute-distributions", "--dir", str(artifact_dir)],
                    timeout=180,
                )
                unpack_download(artifact_dir, binary, version, commit, target)
                return "github-actions:" + run_id
            except DOWNLOAD_ERRORS as error:
                log(f"Actions distributions unavailable: {error}")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        log(f"GitHub artifact lookup unavailable: {error}")
    log("No usable GitHub binary for the pinned commit; building from source.")
    return None


def source_snapshot(root: Path, directory: Path, repository: str, commit: str, source: Path | None) -> Path:
    """Export committed files only; never build dirty/untracked local content."""
    candidates = [source.expanduser().resolve()] if source else [root / ".dev/sparkroute-public", root.parent / "sparkroute"]
    checkout = None
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        try:
            if run(["git", "-C", str(candidate), "rev-parse", "--verify", commit + "^{commit}"], timeout=30) == commit:
                checkout = candidate
                break
        except subprocess.SubprocessError:
            pass
    if source and checkout is None:
        raise ValueError("SPARKROUTE_CHECKOUT must contain the commit in compat/gateway.toml")
    if checkout is None:
        checkout = directory / "checkout"
        run(["git", "init", "--quiet", str(checkout)], timeout=30)
        base = ["git", "-C", str(checkout)]
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        fetch = ["fetch", "--quiet", "--depth=1", repository, commit]
        log("Fetching pinned SparkRoute source (using GitHub CLI credentials when available) ...")
        if shutil.which("gh"):
            try:
                run(
                    [
                        *base,
                        "-c",
                        "credential.https://github.com.helper=",
                        "-c",
                        "credential.https://github.com.helper=!gh auth git-credential",
                        *fetch,
                    ],
                    env=env,
                    timeout=180,
                )
            except subprocess.SubprocessError:
                run([*base, *fetch], env=env, timeout=180)
        else:
            run([*base, *fetch], env=env, timeout=180)
    log(f"Exporting source commit {commit[:12]} from {checkout}")
    archive = directory / "source.tar"
    run(["git", "-C", str(checkout), "archive", "--format=tar", "--output", str(archive), commit], timeout=60)
    snapshot = directory / "source"
    snapshot.mkdir()
    with tarfile.open(archive) as stream:
        members = stream.getmembers()
        if any(not (item.isfile() or item.isdir()) for item in members):
            raise ValueError("source archive contains unsupported links or special files")
        if sum(item.size for item in members) > release.MAX_DOWNLOAD_BYTES:
            raise ValueError("source archive is too large")
        stream.extractall(snapshot, members=members, filter="data")
    return snapshot


def build_binary(source: Path, binary: Path, cache: Path, version: str, commit: str, target: tuple[str, str], builder: str, go: str) -> str:
    go_match = re.search(r"^go ([0-9]+\.[0-9]+\.[0-9]+)$", (source / "go.mod").read_text(), re.MULTILINE)
    if not go_match:
        raise ValueError("source go.mod must pin a Go patch version")
    if not re.search(r"^sparkroute: " + re.escape(version) + "$", (source / "versions.yaml").read_text(), re.MULTILINE):
        raise ValueError("source gateway version differs from the plugin version")
    flags = (
        "-s -w -buildid= -X github.com/sparksq/sparkroute/pkg/version.Version="
        + version
        + " -X github.com/sparksq/sparkroute/pkg/version.Commit="
        + commit
    )
    args = ["build", "-mod=readonly", "-trimpath", "-buildvcs=false", "-ldflags", flags]
    environment = {"GOWORK": "off", "CGO_ENABLED": "0", "GOOS": target[0], "GOARCH": target[1]}
    if builder in ("auto", "docker") and shutil.which("docker"):
        image = f"golang:{go_match[1]}-bookworm"
        cache.mkdir(parents=True, exist_ok=True)
        command = ["docker", "run", "--rm"]
        if hasattr(os, "getuid"):
            command += ["--user", f"{os.getuid()}:{os.getgid()}"]
        command += [
            "--mount",
            f"type=bind,source={source},target=/src,readonly",
            "--mount",
            f"type=bind,source={binary.parent},target=/out",
            "--mount",
            f"type=bind,source={cache},target=/cache",
            "--workdir",
            "/src",
        ]
        for key, value in {
            **environment,
            "GOTOOLCHAIN": "local",
            "GOCACHE": "/cache/build",
            "GOMODCACHE": "/cache/mod",
            "GOPATH": "/cache/gopath",
        }.items():
            command += ["--env", key + "=" + value]
        command += [image, "go", *args, "-o", "/out/" + binary.name, "./cmd/sparkroute"]
        try:
            log(f"Building {target[0]}/{target[1]} with Docker ({image}); the first build may take a few minutes ...")
            run(command)
            return "docker:" + image
        except (OSError, subprocess.SubprocessError) as error:
            if builder == "docker":
                raise
            log(f"Docker build unavailable; trying local Go: {error}")
    elif builder == "docker":
        raise ValueError("Docker is not installed; install Docker or select SPARKROUTE_DEV_BUILDER=go")
    if not shutil.which(go):
        raise ValueError(
            "No working builder. Start Docker or install Go "
            + go_match[1]
            + "; source acquisition requires network access or SPARKROUTE_CHECKOUT."
        )
    log(f"Building {target[0]}/{target[1]} with local Go (requires {go_match[1]} or newer) ...")
    run([go, *args, "-o", str(binary), "./cmd/sparkroute"], cwd=source, env={**os.environ, **environment})
    return "local-go"


def prepare(root: Path, *, builder: str = "auto", go: str = "go", source: Path | None = None, force: bool = False) -> Path:
    if builder not in ("auto", "docker", "go"):
        raise ValueError("SPARKROUTE_DEV_BUILDER must be auto, docker, or go")
    pin = tomllib.loads((root / "compat/gateway.toml").read_text())
    commit = pin["commit"]
    repository = pin["repository"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or repository != "https://github.com/" + release.SPARKROUTE_REPO + ".git":
        raise ValueError("compat/gateway.toml must pin a full commit in the SparkRoute GitHub repository")
    version = release.SPARKROUTE_VERSION
    target = release.platform_target()
    identity = {"commit": commit, "version": version, "os": target[0], "arch": target[1], "schema": 1}
    destination = root / ".dev/gateway" / commit / (target[0] + "-" + target[1])
    destination.mkdir(parents=True, exist_ok=True)
    binary = destination / release.binary_name(target[0])
    receipt = destination / "receipt.json"
    if not force and binary.is_file() and receipt.is_file():
        try:
            cached = json.loads(receipt.read_text())
            if (
                isinstance(cached, dict)
                and all(cached.get(key) == value for key, value in identity.items())
                and cached.get("sha256") == digest(binary)
            ):
                check_binary(binary, version, commit)
                log(f"Using cached development gateway ({commit[:12]}, {target[0]}/{target[1]}).")
                return binary
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        log("Development cache failed validation; preparing it again.")
    # Build/download into a private sibling; a failed attempt never replaces the
    # last usable binary. The receipt is written last, after atomic installation.
    with tempfile.TemporaryDirectory(prefix=".prepare-", dir=destination) as temporary:
        staging = Path(temporary)
        candidate = staging / binary.name
        method = github_binary(staging, candidate, version, commit, target) if builder == "auto" else None
        if method is None:
            snapshot = source_snapshot(root, staging, repository, commit, source)
            method = build_binary(snapshot, candidate, root / ".dev/go-cache", version, commit, target, builder, go)
            candidate.chmod(0o700)
            check_binary(candidate, version, commit)
        metadata = {**identity, "method": method, "sha256": digest(candidate)}
        # Retain downloaded archives/checksums (including license and provenance).
        if method.startswith("github-"):
            name = "release" if method.startswith("github-release:") else "run-" + method.split(":", 1)[1]
            shutil.copytree(staging / name, destination / name, dirs_exist_ok=True)
        candidate.replace(binary)
        staged_receipt = staging / "receipt.json"
        staged_receipt.write_text(json.dumps(metadata, indent=2) + "\n")
        staged_receipt.replace(receipt)
    log(f"Development gateway ready ({method}): {binary}")
    return binary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=os.environ.get("SPARKROUTE_CHECKOUT"))
    parser.add_argument("--builder", choices=("auto", "docker", "go"), default=os.environ.get("SPARKROUTE_DEV_BUILDER", "auto"))
    parser.add_argument("--go", default=os.environ.get("SPARKROUTE_DEV_GO", "go"))
    parser.add_argument("--force", action="store_true", help="ignore the prepared binary cache")
    args = parser.parse_args()
    try:
        print(prepare(ROOT, builder=args.builder, go=args.go, source=args.source, force=args.force))
    except DOWNLOAD_ERRORS as error:
        parser.exit(1, f"SparkRoute development setup failed: {error}\n")


if __name__ == "__main__":
    main()
