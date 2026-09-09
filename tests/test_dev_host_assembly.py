# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
# Additional permission under AGPLv3 section 7: see src/sparkrun/plugins/sparkroute/LICENSE_EXCEPTION.

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ASSEMBLER = ROOT / "scripts" / "assemble-dev-host.py"
COLDSNAP_REPOSITORY = "https://github.com/sparksq/sparkrun-coldsnap-plugin.git"


@pytest.fixture(autouse=True)
def _isolate_coldsnap_settings(monkeypatch):
    for name in ("SPARKRUN_DEV_COLDSNAP", "SPARKRUN_COLDSNAP_CHECKOUT", "SPARKRUN_COLDSNAP_BRANCH"):
        monkeypatch.delenv(name, raising=False)


def _write_host(host: Path, *, integrated: bool = False) -> None:
    core = host / "src" / "sparkrun" / "core"
    plugins = host / "src" / "sparkrun" / "plugins"
    core.mkdir(parents=True)
    plugins.mkdir(parents=True)
    (host / "pyproject.toml").write_text("[project]\nname = 'sparkrun'\n", encoding="utf-8")
    (host / "src" / "sparkrun" / "__init__.py").write_text("", encoding="utf-8")
    feature = (
        'FEATURE_PLUGIN_SPARKROUTE = register_feature(FeatureFlag(name="gateway.sparkroute", default=True))\n'
        if integrated
        else "FEATURE_EXISTING = object()\n"
    )
    mapping = (
        'IN_TREE_PLUGIN_FEATURES: dict[str, str] = {"sparkroute": "gateway.sparkroute"}\n'
        if integrated
        else "IN_TREE_PLUGIN_FEATURES: dict[str, str] = {}\n"
    )
    (core / "features.py").write_text(feature, encoding="utf-8")
    (core / "in_tree_plugins.py").write_text(mapping, encoding="utf-8")


def _write_plugin(plugin: Path) -> None:
    source = plugin / "src" / "sparkrun" / "plugins" / "sparkroute"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("LIVE_PLUGIN = True\n", encoding="utf-8")
    (plugin / "plugin.toml").write_text('schema = 1\nname = "sparkroute"\n', encoding="utf-8")


def _assemble(host: Path, plugin: Path, *, copy_plugin: bool = False) -> subprocess.CompletedProcess[str]:
    destination = plugin / ".dev" / "sparkrun-with-sparkroute"
    return subprocess.run(
        [
            sys.executable,
            str(ASSEMBLER),
            "--host",
            str(host),
            "--plugin-root",
            str(plugin),
            "--destination",
            str(destination),
            *(["--copy-plugin"] if copy_plugin else []),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_assembly_links_live_source_and_adds_only_disposable_bindings(tmp_path: Path):
    host = tmp_path / "host"
    plugin = tmp_path / "plugin"
    _write_host(host)
    _write_plugin(plugin)
    (host / "local-host-change.txt").write_text("preserved\n", encoding="utf-8")
    original_features = (host / "src/sparkrun/core/features.py").read_text(encoding="utf-8")
    original_loader = (host / "src/sparkrun/core/in_tree_plugins.py").read_text(encoding="utf-8")

    result = _assemble(host, plugin)

    assert result.returncode == 0, result.stdout + result.stderr
    assembled = plugin / ".dev" / "sparkrun-with-sparkroute"
    linked = assembled / "src/sparkrun/plugins/sparkroute"
    assert linked.is_symlink()
    assert linked.resolve() == (plugin / "src/sparkrun/plugins/sparkroute").resolve()
    assert (assembled / "local-host-change.txt").read_text(encoding="utf-8") == "preserved\n"
    assert 'name="gateway.sparkroute"' in (assembled / "src/sparkrun/core/features.py").read_text(encoding="utf-8")
    assert 'IN_TREE_PLUGIN_FEATURES["sparkroute"] = "gateway.sparkroute"' in (assembled / "src/sparkrun/core/in_tree_plugins.py").read_text(
        encoding="utf-8"
    )
    assert (host / "src/sparkrun/core/features.py").read_text(encoding="utf-8") == original_features
    assert (host / "src/sparkrun/core/in_tree_plugins.py").read_text(encoding="utf-8") == original_loader


def test_assembly_does_not_duplicate_an_upstream_binding(tmp_path: Path):
    host = tmp_path / "host"
    plugin = tmp_path / "plugin"
    _write_host(host, integrated=True)
    _write_plugin(plugin)

    result = _assemble(host, plugin)

    assert result.returncode == 0, result.stdout + result.stderr
    assembled = plugin / ".dev" / "sparkrun-with-sparkroute"
    features = (assembled / "src/sparkrun/core/features.py").read_text(encoding="utf-8")
    loader = (assembled / "src/sparkrun/core/in_tree_plugins.py").read_text(encoding="utf-8")
    assert features.count("gateway.sparkroute") == 1
    assert loader.count("gateway.sparkroute") == 1
    assert "BEGIN sparkrun-sparkroute development binding" not in features
    assert "BEGIN sparkrun-sparkroute development binding" not in loader


def test_host_patch_preserves_lf_with_windows_git_defaults(tmp_path: Path, monkeypatch):
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _write_host(host)
    _write_plugin(plugin)
    (host / "sample.txt").write_bytes(b"before\n")
    patch = plugin / "compat/sparkrun-host-seams.patch"
    patch.parent.mkdir()
    patch.write_bytes(b"--- a/sample.txt\n+++ b/sample.txt\n@@ -1 +1 @@\n-before\n+after\n")
    (plugin / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.autocrlf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    subprocess.run(["git", "init", "--quiet", str(plugin)], check=True)
    subprocess.run(["git", "-C", str(plugin), "add", ".gitattributes", "compat"], check=True)
    patch.unlink()
    subprocess.run(["git", "-C", str(plugin), "checkout", "--", "compat"], check=True)
    assert b"\r\n" not in patch.read_bytes()

    result = _assemble(host, plugin)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (plugin / ".dev/sparkrun-with-sparkroute/sample.txt").read_bytes() == b"after\n"
    assert (host / "sample.txt").read_bytes() == b"before\n"


def _write_run_path_patch(plugin: Path, name: str = "sparkrun-run-path.patch") -> None:
    patch = plugin / "compat" / name
    patch.parent.mkdir(exist_ok=True)
    patch.write_text("--- a/run-path.txt\n+++ b/run-path.txt\n@@ -1 +1 @@\n-old launch\n+shared run\n", encoding="utf-8")


@pytest.mark.parametrize("patch_name", ["sparkrun-run-path.patch", "sparkrun-proxy-unload.patch"])
def test_run_path_fix_is_applied_even_when_host_hooks_are_integrated(tmp_path: Path, patch_name: str):
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _write_host(host, integrated=True)
    _write_plugin(plugin)
    _write_run_path_patch(plugin, patch_name)
    (host / "run-path.txt").write_text("old launch\n", encoding="utf-8")
    result = _assemble(host, plugin)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (plugin / ".dev/sparkrun-with-sparkroute/run-path.txt").read_text() == "shared run\n"
    assert (host / "run-path.txt").read_text() == "old launch\n"


@pytest.mark.parametrize("patch_name", ["sparkrun-run-path.patch", "sparkrun-proxy-unload.patch"])
def test_run_path_fix_skips_an_already_fixed_host(tmp_path: Path, patch_name: str):
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _write_host(host, integrated=True)
    _write_plugin(plugin)
    _write_run_path_patch(plugin, patch_name)
    (host / "run-path.txt").write_text("shared run\n", encoding="utf-8")
    for _ in range(2):
        result = _assemble(host, plugin)
        assert result.returncode == 0, result.stdout + result.stderr
    assert (plugin / ".dev/sparkrun-with-sparkroute/run-path.txt").read_text() == "shared run\n"


@pytest.mark.parametrize("patch_name", ["sparkrun-run-path.patch", "sparkrun-proxy-unload.patch"])
def test_incompatible_run_path_fix_preserves_previous_assembly(tmp_path: Path, patch_name: str):
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _write_host(host)
    _write_plugin(plugin)
    _write_run_path_patch(plugin, patch_name)
    (host / "run-path.txt").write_text("old launch\n", encoding="utf-8")
    assert _assemble(host, plugin).returncode == 0
    (host / "run-path.txt").write_text("different launch\n", encoding="utf-8")
    result = _assemble(host, plugin)
    assert result.returncode != 0
    assert "compatibility patch does not apply" in result.stderr
    assert (plugin / ".dev/sparkrun-with-sparkroute/run-path.txt").read_text() == "shared run\n"
    assert (host / "run-path.txt").read_text() == "different launch\n"
    assert not (plugin / ".dev/.sparkrun-with-sparkroute.tmp").exists()


def test_assembly_combines_adjacent_coldsnap_without_changing_host(tmp_path: Path):
    host = tmp_path / "host"
    plugin = tmp_path / "plugin"
    _write_host(host)
    _write_plugin(plugin)
    cold = tmp_path / "sparkrun-coldsnap-plugin/src/sparkrun/plugins/coldsnap"
    cold.mkdir(parents=True)
    (cold / "__init__.py").write_text("LIVE_COLDSNAP = True\n")
    result = _assemble(host, plugin)
    assert result.returncode == 0, result.stderr
    assembled = plugin / ".dev/sparkrun-with-sparkroute"
    assert (assembled / "src/sparkrun/plugins/coldsnap/__init__.py").read_text() == "LIVE_COLDSNAP = True\n"
    assert "plugins.coldsnap" in (assembled / "src/sparkrun/core/features.py").read_text()
    assert not (host / "src/sparkrun/plugins/coldsnap").exists()


def _git(path: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(path), "-c", "user.name=Assembly Test", "-c", "user.email=assembly@example.invalid", *args], text=True
    ).strip()


def _commit_coldsnap(remote: Path, value: str) -> str:
    source = remote / "src/sparkrun/plugins/coldsnap"
    source.mkdir(parents=True, exist_ok=True)
    (source / "__init__.py").write_text("VERSION = %r\n" % value)
    _git(remote, "add", ".")
    _git(remote, "commit", "--quiet", "-m", value)
    return _git(remote, "rev-parse", "HEAD")


def _public_coldsnap_fixture(tmp_path: Path, monkeypatch) -> Path:
    """Exercise real clone/fetch with a local stand-in for the public remote."""
    remote = tmp_path / "public-coldsnap"
    remote.mkdir()
    _git(remote, "init", "--quiet", "--initial-branch=main")
    _commit_coldsnap(remote, "first")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "url.%s.insteadOf" % remote.as_uri())
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", COLDSNAP_REPOSITORY)
    monkeypatch.setenv("SPARKRUN_DEV_COLDSNAP", "1")
    return remote


@pytest.mark.parametrize("copy_plugin", [False, True])
def test_fetched_coldsnap_updates_and_honors_branch_changes(tmp_path: Path, monkeypatch, copy_plugin):
    remote = _public_coldsnap_fixture(tmp_path, monkeypatch)
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _write_host(host)
    _write_plugin(plugin)
    for value in ("first", "updated"):
        if value == "updated":
            _commit_coldsnap(remote, value)
        result = _assemble(host, plugin, copy_plugin=copy_plugin)
        assert result.returncode == 0, result.stderr
        assert "Using fetched coldsnap " + _git(remote, "rev-parse", "HEAD")[:12] in result.stdout
        assert (plugin / ".dev/sparkrun-with-sparkroute/src/sparkrun/plugins/coldsnap/__init__.py").read_text() == "VERSION = %r\n" % value
    _git(remote, "switch", "--quiet", "-c", "combined-testing")
    head = _commit_coldsnap(remote, "branch")
    monkeypatch.setenv("SPARKRUN_COLDSNAP_BRANCH", "combined-testing")
    result = _assemble(host, plugin, copy_plugin=copy_plugin)
    assert result.returncode == 0, result.stderr
    checkout = plugin / ".dev/sparkrun-coldsnap-plugin"
    assert _git(checkout, "rev-parse", "HEAD") == head
    assert _git(checkout, "config", "--get", "remote.origin.url") == COLDSNAP_REPOSITORY
    if copy_plugin:
        assert not (plugin / ".dev/sparkrun-with-sparkroute/src/sparkrun/plugins/coldsnap").is_symlink()
    assert not (host / "src/sparkrun/plugins/coldsnap").exists()


@pytest.mark.parametrize("problem", ["dirty", "wrong-origin", "missing-branch"])
def test_failed_coldsnap_refresh_preserves_previous_assembly(tmp_path: Path, monkeypatch, problem):
    _public_coldsnap_fixture(tmp_path, monkeypatch)
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _write_host(host)
    _write_plugin(plugin)
    assert _assemble(host, plugin).returncode == 0
    checkout = plugin / ".dev/sparkrun-coldsnap-plugin"
    if problem == "dirty":
        (checkout / "local-note.txt").write_text("keep me")
    elif problem == "wrong-origin":
        _git(checkout, "remote", "set-url", "origin", "https://example.invalid/unexpected.git")
    else:
        monkeypatch.setenv("SPARKRUN_COLDSNAP_BRANCH", "missing-branch")
    result = _assemble(host, plugin)
    assert result.returncode != 0
    assert "Assembled in-tree" not in result.stdout
    assert (plugin / ".dev/sparkrun-with-sparkroute/src/sparkrun/plugins/coldsnap/__init__.py").read_text() == "VERSION = 'first'\n"
    if problem == "dirty":
        assert (checkout / "local-note.txt").read_text() == "keep me"
        assert "local changes" in result.stderr
    elif problem == "wrong-origin":
        assert "unexpected origin" in result.stderr


def test_explicit_coldsnap_checkout_precedes_fetch_and_is_not_switched(tmp_path: Path, monkeypatch):
    remote = _public_coldsnap_fixture(tmp_path, monkeypatch)
    _git(remote, "switch", "--quiet", "-c", "local-work")
    head = _commit_coldsnap(remote, "local")
    monkeypatch.setenv("SPARKRUN_COLDSNAP_CHECKOUT", str(remote))
    monkeypatch.setenv("SPARKRUN_COLDSNAP_BRANCH", "missing-branch")
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _write_host(host)
    _write_plugin(plugin)
    result = _assemble(host, plugin)
    assert result.returncode == 0, result.stderr
    assert "Including coldsnap plugin from " + str(remote) in result.stdout
    assert not (plugin / ".dev/sparkrun-coldsnap-plugin").exists()
    assert _git(remote, "branch", "--show-current") == "local-work"
    assert _git(remote, "rev-parse", "HEAD") == head


@pytest.mark.parametrize("setting", ["flag", "checkout"])
def test_explicit_coldsnap_omission_removes_host_copy_and_does_not_fetch(tmp_path: Path, monkeypatch, setting):
    _public_coldsnap_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("SPARKRUN_DEV_COLDSNAP" if setting == "flag" else "SPARKRUN_COLDSNAP_CHECKOUT", "0" if setting == "flag" else "none")
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _write_host(host)
    _write_plugin(plugin)
    original = host / "src/sparkrun/plugins/coldsnap"
    original.mkdir()
    (original / "__init__.py").write_text("ORIGINAL = True\n")
    result = _assemble(host, plugin)
    assert result.returncode == 0, result.stderr
    assert not (plugin / ".dev/sparkrun-coldsnap-plugin").exists()
    assert not (plugin / ".dev/sparkrun-with-sparkroute/src/sparkrun/plugins/coldsnap").exists()
    assert (original / "__init__.py").read_text() == "ORIGINAL = True\n"


def test_invalid_coldsnap_mode_fails_before_assembly(tmp_path: Path, monkeypatch):
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _write_host(host)
    _write_plugin(plugin)
    monkeypatch.setenv("SPARKRUN_DEV_COLDSNAP", "typo")
    result = _assemble(host, plugin)
    assert result.returncode != 0
    assert "SPARKRUN_DEV_COLDSNAP must be" in result.stderr
    assert not (plugin / ".dev/sparkrun-with-sparkroute").exists()
