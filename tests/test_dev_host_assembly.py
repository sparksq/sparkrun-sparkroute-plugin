# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
# Additional permission under AGPLv3 section 7: see src/sparkrun/plugins/sparkroute/LICENSE_EXCEPTION.

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSEMBLER = ROOT / "scripts" / "assemble-dev-host.py"


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


def _assemble(host: Path, plugin: Path) -> subprocess.CompletedProcess[str]:
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


def _write_run_path_patch(plugin: Path) -> None:
    patch = plugin / "compat/sparkrun-run-path.patch"
    patch.parent.mkdir(exist_ok=True)
    patch.write_text("--- a/run-path.txt\n+++ b/run-path.txt\n@@ -1 +1 @@\n-old launch\n+shared run\n", encoding="utf-8")


def test_run_path_fix_is_applied_even_when_host_hooks_are_integrated(tmp_path: Path):
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _write_host(host, integrated=True)
    _write_plugin(plugin)
    _write_run_path_patch(plugin)
    (host / "run-path.txt").write_text("old launch\n", encoding="utf-8")
    result = _assemble(host, plugin)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (plugin / ".dev/sparkrun-with-sparkroute/run-path.txt").read_text() == "shared run\n"
    assert (host / "run-path.txt").read_text() == "old launch\n"


def test_run_path_fix_skips_an_already_fixed_host(tmp_path: Path):
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _write_host(host, integrated=True)
    _write_plugin(plugin)
    _write_run_path_patch(plugin)
    (host / "run-path.txt").write_text("shared run\n", encoding="utf-8")
    for _ in range(2):
        result = _assemble(host, plugin)
        assert result.returncode == 0, result.stdout + result.stderr
    assert (plugin / ".dev/sparkrun-with-sparkroute/run-path.txt").read_text() == "shared run\n"


def test_incompatible_run_path_fix_preserves_previous_assembly(tmp_path: Path):
    host, plugin = tmp_path / "host", tmp_path / "plugin"
    _write_host(host)
    _write_plugin(plugin)
    _write_run_path_patch(plugin)
    (host / "run-path.txt").write_text("old launch\n", encoding="utf-8")
    assert _assemble(host, plugin).returncode == 0
    (host / "run-path.txt").write_text("different launch\n", encoding="utf-8")
    result = _assemble(host, plugin)
    assert result.returncode != 0
    assert "shared run-path compatibility patch does not apply" in result.stderr
    assert (plugin / ".dev/sparkrun-with-sparkroute/run-path.txt").read_text() == "shared run\n"
    assert (host / "run-path.txt").read_text() == "different launch\n"
    assert not (plugin / ".dev/.sparkrun-with-sparkroute.tmp").exists()
