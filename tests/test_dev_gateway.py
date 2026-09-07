# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
# Additional permission under AGPLv3 section 7: see src/sparkrun/plugins/sparkroute/LICENSE_EXCEPTION.
"""Development acquisition must stay bound to source identity and fail safely."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dev_gateway", ROOT / "scripts/prepare-dev-gateway.py")
dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev)
COMMIT = "a" * 40
VERSION = dev.release.SPARKROUTE_VERSION


def info(commit=COMMIT):
    return {
        "name": "sparkroute",
        "version": VERSION,
        "commit": commit,
        "license": "AGPL-3.0-only",
        "source": "https://github.com/sparksq/sparkroute/tree/" + commit,
    }


def distributions(directory, target=("linux", "arm64"), commit=COMMIT, checksum=True, link=False):
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / dev.release.asset_name(VERSION, *target)
    files = {"build-info.json": json.dumps(info(commit)).encode(), dev.release.binary_name(target[0]): b"fixture binary"}
    if target[0] == "windows":
        with zipfile.ZipFile(archive, "w") as stream:
            for name, content in files.items():
                stream.writestr(name, content)
    else:
        with tarfile.open(archive, "w:gz") as stream:
            for name, content in files.items():
                entry = tarfile.TarInfo(name)
                if link and name == "sparkroute":
                    entry.type = tarfile.SYMTYPE
                    entry.linkname = "/outside"
                else:
                    entry.size = len(content)
                stream.addfile(entry, io.BytesIO(content))
    (directory / "checksums.txt").write_text((dev.digest(archive) if checksum else "0" * 64) + "  " + archive.name + "\n")
    return archive


@pytest.mark.parametrize("target", [("linux", "arm64"), ("darwin", "amd64"), ("windows", "arm64")])
def test_download_checks_archive_and_binary_identity(tmp_path, monkeypatch, target):
    distributions(tmp_path, target)
    checked = []
    monkeypatch.setattr(dev, "check_binary", lambda *args: checked.append(args))
    binary = tmp_path / "output"
    dev.unpack_download(tmp_path, binary, VERSION, COMMIT, target)
    assert binary.read_bytes() == b"fixture binary"
    assert checked == [(binary, VERSION, COMMIT)]


@pytest.mark.parametrize("kwargs", [{"checksum": False}, {"commit": "b" * 40}, {"link": True}])
def test_reject_download_before_execution(tmp_path, monkeypatch, kwargs):
    distributions(tmp_path, **kwargs)
    monkeypatch.setattr(dev, "check_binary", lambda *_: pytest.fail("untrusted binary was executed"))
    binary = tmp_path / "output"
    with pytest.raises((ValueError, dev.release.GatewayReleaseError)):
        dev.unpack_download(tmp_path, binary, VERSION, COMMIT, ("linux", "arm64"))
    assert not binary.exists()


def test_authenticated_release_is_preferred(tmp_path, monkeypatch):
    monkeypatch.setattr(dev.shutil, "which", lambda _: "/bin/gh")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[1] == "api":
            return COMMIT
        assert command[1:3] == ["release", "download"]
        distributions(Path(command[command.index("--dir") + 1]))
        return ""

    monkeypatch.setattr(dev, "run", run)
    monkeypatch.setattr(dev, "check_binary", lambda *_: None)
    assert dev.github_binary(tmp_path, tmp_path / "binary", VERSION, COMMIT, ("linux", "arm64")) == f"github-release:v{VERSION}"
    assert len(calls) == 2


def test_wrong_release_revision_uses_exact_commit_artifact_and_skips_expired_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(dev.shutil, "which", lambda _: "/bin/gh")
    downloads = []

    def run(command, **kwargs):
        if command[1] == "api":
            return "b" * 40
        if command[1:3] == ["run", "list"]:
            assert command[command.index("--commit") + 1] == COMMIT
            assert command[command.index("--status") + 1] == "success"
            return json.dumps(
                [{"headSha": "b" * 40, "databaseId": 99}, {"headSha": COMMIT, "databaseId": 2}, {"headSha": COMMIT, "databaseId": 1}]
            )
        assert command[1:3] == ["run", "download"]
        downloads.append(command[3])
        if command[3] == "2":
            raise subprocess.CalledProcessError(1, command)
        distributions(Path(command[command.index("--dir") + 1]))
        return ""

    monkeypatch.setattr(dev, "run", run)
    monkeypatch.setattr(dev, "check_binary", lambda *_: None)
    assert dev.github_binary(tmp_path, tmp_path / "binary", VERSION, COMMIT, ("linux", "arm64")) == "github-actions:1"
    assert downloads == ["2", "1"]


def test_unavailable_github_allows_source_build(tmp_path, monkeypatch):
    monkeypatch.setattr(dev.shutil, "which", lambda _: "/bin/gh")
    monkeypatch.setattr(dev, "run", lambda command, **kwargs: (_ for _ in ()).throw(subprocess.CalledProcessError(1, command)))
    assert dev.github_binary(tmp_path, tmp_path / "binary", VERSION, COMMIT, ("linux", "arm64")) is None


def setup_root(tmp_path):
    (tmp_path / "compat").mkdir()
    (tmp_path / "compat/gateway.toml").write_text(f'repository = "https://github.com/sparksq/sparkroute.git"\ncommit = "{COMMIT}"\n')
    return tmp_path


def test_cache_is_offline_and_tampering_rebuilds_without_executing_bad_binary(tmp_path, monkeypatch):
    root = setup_root(tmp_path)
    monkeypatch.setattr(dev.release, "platform_target", lambda: ("linux", "arm64"))
    calls = []
    monkeypatch.setattr(dev, "github_binary", lambda *_: calls.append("github"))
    monkeypatch.setattr(dev, "source_snapshot", lambda *_: tmp_path)

    def build(source, binary, *args):
        calls.append("build")
        binary.write_bytes(b"checked binary")
        return "docker:test"

    monkeypatch.setattr(dev, "build_binary", build)
    monkeypatch.setattr(
        dev, "check_binary", lambda binary, *_: None if binary.read_bytes() == b"checked binary" else pytest.fail("executed tampered cache")
    )
    binary = dev.prepare(root)
    assert calls == ["github", "build"]
    calls.clear()
    assert dev.prepare(root) == binary
    assert not calls
    binary.write_bytes(b"tampered")
    assert dev.prepare(root) == binary
    assert calls == ["github", "build"]
    assert binary.read_bytes() == b"checked binary"
    receipt = json.loads((binary.parent / "receipt.json").read_text())
    assert receipt["sha256"] == dev.digest(binary)
    assert receipt["method"] == "docker:test"
    for malformed in ("[]", "{broken"):
        calls.clear()
        (binary.parent / "receipt.json").write_text(malformed)
        assert dev.prepare(root) == binary
        assert calls == ["github", "build"]


def test_failed_build_preserves_previous_binary(tmp_path, monkeypatch):
    root = setup_root(tmp_path)
    monkeypatch.setattr(dev.release, "platform_target", lambda: ("linux", "arm64"))
    destination = root / ".dev/gateway" / COMMIT / "linux-arm64"
    destination.mkdir(parents=True)
    binary = destination / "sparkroute"
    binary.write_bytes(b"previous good binary")
    monkeypatch.setattr(dev, "github_binary", lambda *_: None)
    monkeypatch.setattr(dev, "source_snapshot", lambda *_: tmp_path)

    def broken_build(source, candidate, *args):
        candidate.write_bytes(b"partial")
        raise ValueError("build failed")

    monkeypatch.setattr(dev, "build_binary", broken_build)
    with pytest.raises(ValueError, match="build failed"):
        dev.prepare(root, force=True)
    assert binary.read_bytes() == b"previous good binary"
    assert not (destination / "receipt.json").exists()
    assert not list(destination.glob(".prepare-*"))


def test_source_export_ignores_uncommitted_and_untracked_content(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    (checkout / "source.txt").write_text("committed")
    subprocess.run(["git", "-C", str(checkout), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    (checkout / "source.txt").write_text("dirty")
    (checkout / "untracked.go").write_text("do not build this")
    staging = tmp_path / "staging"
    staging.mkdir()
    snapshot = dev.source_snapshot(tmp_path, staging, "unused", commit, checkout)
    assert (snapshot / "source.txt").read_text() == "committed"
    assert not (snapshot / "untracked.go").exists()
    assert (checkout / "source.txt").read_text() == "dirty"


@pytest.mark.parametrize("target", [("linux", "arm64"), ("darwin", "amd64"), ("windows", "arm64")])
def test_docker_targets_controller_and_keeps_credentials_outside_container(tmp_path, monkeypatch, target):
    source = tmp_path / "source with spaces"
    source.mkdir()
    (source / "go.mod").write_text("module github.com/sparksq/sparkroute\n\ngo 1.25.14\n")
    (source / "versions.yaml").write_text(f"sparkroute: {VERSION}\n")
    monkeypatch.setenv("GH_TOKEN", "do-not-forward-fixture-token")
    monkeypatch.setattr(dev.shutil, "which", lambda _: "/bin/tool")
    commands = []
    monkeypatch.setattr(dev, "run", lambda command, **kwargs: commands.append(command))
    method = dev.build_binary(source, tmp_path / "sparkroute", tmp_path / "cache", VERSION, COMMIT, target, "auto", "go")
    assert method == "docker:golang:1.25.14-bookworm"
    command = commands[0]
    assert "GOOS=" + target[0] in command and "GOARCH=" + target[1] in command
    assert "CGO_ENABLED=0" in command and "GOTOOLCHAIN=local" in command
    assert f"type=bind,source={source},target=/src,readonly" in command
    assert not any("GH_TOKEN" in value or "do-not-forward-fixture-token" in value for value in command)
    assert "-mod=readonly" in command and "-buildvcs=false" in command


def test_docker_failure_falls_back_to_go_and_forced_docker_reports_failure(tmp_path, monkeypatch):
    (tmp_path / "go.mod").write_text("go 1.25.14\n")
    (tmp_path / "versions.yaml").write_text(f"sparkroute: {VERSION}\n")
    monkeypatch.setattr(dev.shutil, "which", lambda _: "/bin/tool")
    commands = []

    def run(command, **kwargs):
        commands.append(command[0])
        if command[0] == "docker":
            raise subprocess.CalledProcessError(1, command)
        assert kwargs["env"]["GOOS"] == "linux" and kwargs["env"]["CGO_ENABLED"] == "0"

    monkeypatch.setattr(dev, "run", run)
    args = (tmp_path, tmp_path / "binary", tmp_path / "cache", VERSION, COMMIT, ("linux", "arm64"))
    assert dev.build_binary(*args, "auto", "custom-go") == "local-go"
    assert commands == ["docker", "custom-go"]
    with pytest.raises(subprocess.CalledProcessError):
        dev.build_binary(*args, "docker", "custom-go")


def test_no_builder_is_actionable(tmp_path, monkeypatch):
    (tmp_path / "go.mod").write_text("go 1.25.14\n")
    (tmp_path / "versions.yaml").write_text(f"sparkroute: {VERSION}\n")
    monkeypatch.setattr(dev.shutil, "which", lambda _: None)
    with pytest.raises(ValueError, match="Start Docker or install Go 1.25.14"):
        dev.build_binary(tmp_path, tmp_path / "binary", tmp_path / "cache", VERSION, COMMIT, ("linux", "arm64"), "auto", "go")
