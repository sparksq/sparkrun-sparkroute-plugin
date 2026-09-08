# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
# Additional permission under AGPLv3 section 7: see src/sparkrun/plugins/sparkroute/LICENSE_EXCEPTION.

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/spark-arena/sparkrun.git"


def _executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _checkout(path: Path) -> None:
    (path / ".git").mkdir(parents=True)
    (path / "src" / "sparkrun").mkdir(parents=True)
    (path / "pyproject.toml").write_text("[project]\nname = 'sparkrun'\n", encoding="utf-8")
    (path / "src" / "sparkrun" / "__init__.py").write_text("", encoding="utf-8")
    (path / "src/sparkrun/runtimes").mkdir()
    (path / "src/sparkrun/runtimes/base.py").write_text("def native_api_options(): pass\n")
    (path / "src/sparkrun/api").mkdir()
    (path / "src/sparkrun/api/proxy").mkdir()
    (path / "src/sparkrun/api/proxy/_ops.py").write_text("engine._await_exit(pid, RESTART_WAIT_SECONDS)\n")
    (path / "src/sparkrun/api/_catalog.py").write_text("def catalog_cluster_capacity(): pass\n")
    (path / "src/sparkrun/core").mkdir()
    (path / "src/sparkrun/core/readiness.py").write_text('OPENAI_RESPONSES_STREAM = "openai-responses-stream-v1"\n')
    (path / "src/sparkrun/core/recipe.py").write_text("def export_plugin_items(): pass\n")
    (path / "src/sparkrun/core/recipe_items.py").write_text("affects_fingerprint: bool = True\n")


def _development_tree(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    shutil.copy2(ROOT / "dev.sh", plugin / "dev.sh")

    managed = plugin / ".dev" / "sparkrun"
    _checkout(managed)

    venv_bin = plugin / ".venv" / "bin"
    sparkrun_log = tmp_path / "sparkrun.log"
    gateway = plugin / ".dev" / "sparkroute-test-binary"
    _executable(gateway, "exit 0\n")
    _executable(
        venv_bin / "python",
        """if [[ "$1" == *prepare-dev-gateway.py ]]; then
    printf 'prepare\\n' >> "$FAKE_GATEWAY_LOG"
    if [[ "${FAKE_GATEWAY_STATUS:-0}" != 0 ]]; then exit "$FAKE_GATEWAY_STATUS"; fi
    printf '%s\\n' "$FAKE_GATEWAY_BINARY"
fi
exit 0
""",
    )
    _executable(venv_bin / "pre-commit", "exit 0\n")
    _executable(
        venv_bin / "sparkrun",
        """printf '%s\\n' "$*" >> "$FAKE_SPARKRUN_LOG"
exit "${FAKE_SPARKRUN_STATUS:-0}"
""",
    )
    (venv_bin / "activate").write_text(":\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    git_log = tmp_path / "git.log"
    _executable(
        fake_bin / "git",
        """printf '%s\\n' "$*" >> "$FAKE_GIT_LOG"
if [[ "$*" == *"remote get-url origin"* ]]; then
    printf '%s\\n' "$FAKE_GIT_ORIGIN"
fi
exit 0
""",
    )
    _executable(fake_bin / "uv", "exit 0\n")

    env = {
        **os.environ,
        "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
        "FAKE_GIT_LOG": str(git_log),
        "FAKE_GIT_ORIGIN": REPOSITORY,
        "FAKE_SPARKRUN_LOG": str(sparkrun_log),
        "FAKE_GATEWAY_LOG": str(tmp_path / "gateway.log"),
        "FAKE_GATEWAY_BINARY": str(gateway),
    }
    for name in (
        "SPARKRUN_CHECKOUT",
        "SPARKRUN_BRANCH",
        "_SPARKRUN_SPARKROUTE_MANAGED_CHECKOUT",
        "SPARKRUN_SPARKROUTE_BINARY",
        "_SPARKRUN_SPARKROUTE_MANAGED_BINARY",
        "SPARKRUN_FOXSCI_ROUTE_BINARY",
        "SPARKRUN_LLM_GATEWAY_BINARY",
    ):
        env.pop(name, None)
    return plugin, git_log, env


def test_repeated_source_honors_a_changed_managed_branch(tmp_path: Path):
    plugin, git_log, env = _development_tree(tmp_path)

    result = subprocess.run(
        [
            "bash",
            "-c",
            """
set -e
unset _SPARKRUN_SPARKROUTE_MANAGED_CHECKOUT
export SPARKRUN_BRANCH=main
export SPARKRUN_CHECKOUT="$PLUGIN_ROOT/.dev/sparkrun"
source "$PLUGIN_ROOT/dev.sh"
export SPARKRUN_BRANCH=develop-next
source "$PLUGIN_ROOT/dev.sh"
printf 'checkout=%s\\nbranch=%s\\nmarker=%s\\n' \\
    "$SPARKRUN_CHECKOUT" "$SPARKRUN_BRANCH" "$_SPARKRUN_SPARKROUTE_MANAGED_CHECKOUT"
printf 'dev_checkout=%s\\n' "$SPARKRUN_DEV_CHECKOUT"
printf 'binary=%s\\n' "$SPARKRUN_SPARKROUTE_BINARY"
""",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**env, "PLUGIN_ROOT": str(plugin)},
    )

    assert result.returncode == 0, result.stderr
    assert "Using local sparkrun checkout" not in result.stdout
    assert "Updating sparkrun branch main" in result.stdout
    assert "Updating sparkrun branch develop-next" in result.stdout
    assert "branch=develop-next" in result.stdout
    assert "checkout=%s" % (plugin / ".dev" / "sparkrun") in result.stdout
    assert "marker=%s" % (plugin / ".dev" / "sparkrun") in result.stdout
    assert "dev_checkout=%s" % (plugin / ".dev" / "sparkrun-with-sparkroute") in result.stdout
    assert "binary=" + env["FAKE_GATEWAY_BINARY"] in result.stdout
    assert Path(env["FAKE_GATEWAY_LOG"]).read_text().splitlines() == ["prepare", "prepare"]
    calls = git_log.read_text(encoding="utf-8")
    assert "fetch --prune origin main" in calls
    assert "fetch --prune origin develop-next" in calls
    assert Path(env["FAKE_SPARKRUN_LOG"]).read_text(encoding="utf-8").splitlines() == [
        "registry update",
        "registry update",
    ]


def test_a_different_explicit_checkout_still_takes_precedence(tmp_path: Path):
    plugin, git_log, env = _development_tree(tmp_path)
    explicit = tmp_path / "explicit-sparkrun"
    _checkout(explicit)

    result = subprocess.run(
        [
            "bash",
            "-c",
            """
set -e
export SPARKRUN_BRANCH=develop-next
export SPARKRUN_CHECKOUT="$EXPLICIT_CHECKOUT"
export _SPARKRUN_SPARKROUTE_MANAGED_CHECKOUT="$PLUGIN_ROOT/.dev/sparkrun"
source "$PLUGIN_ROOT/dev.sh"
printf 'checkout=%s\\nmarker=%s\\n' \\
    "$SPARKRUN_CHECKOUT" "${_SPARKRUN_SPARKROUTE_MANAGED_CHECKOUT-unset}"
printf 'dev_checkout=%s\\n' "$SPARKRUN_DEV_CHECKOUT"
""",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **env,
            "PLUGIN_ROOT": str(plugin),
            "EXPLICIT_CHECKOUT": str(explicit),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "Using local sparkrun checkout: %s" % explicit in result.stdout
    assert "checkout=%s" % explicit in result.stdout
    assert "marker=unset" in result.stdout
    assert "dev_checkout=%s" % (plugin / ".dev" / "sparkrun-with-sparkroute") in result.stdout
    calls = git_log.read_text(encoding="utf-8") if git_log.exists() else ""
    assert "fetch --prune" not in calls
    assert Path(env["FAKE_SPARKRUN_LOG"]).read_text(encoding="utf-8").splitlines() == ["registry update"]


def test_registry_update_failure_is_nonfatal(tmp_path: Path):
    plugin, _git_log, env = _development_tree(tmp_path)

    result = subprocess.run(
        ["bash", "-c", 'set -e\nsource "$PLUGIN_ROOT/dev.sh"'],
        check=False,
        capture_output=True,
        text=True,
        env={
            **env,
            "PLUGIN_ROOT": str(plugin),
            "FAKE_SPARKRUN_STATUS": "17",
        },
    )

    assert result.returncode == 0
    assert "Warning: registry update failed (non-fatal)." in result.stderr
    assert Path(env["FAKE_SPARKRUN_LOG"]).read_text(encoding="utf-8").splitlines() == ["registry update"]


def test_copied_assembly_preserves_source_and_does_not_require_symlinks(tmp_path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("assembler", ROOT / "scripts/assemble-dev-host.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plugin = tmp_path / "plugin"
    plugin_source = plugin / "src/sparkrun/plugins/sparkroute"
    plugin_source.mkdir(parents=True)
    (plugin_source / "__init__.py").write_text("VERSION = 'test'\n")
    (plugin / "plugin.toml").write_text("name = 'sparkroute'\n")
    host = tmp_path / "host"
    _checkout(host)
    (host / "src/sparkrun/core").mkdir(exist_ok=True)
    (host / module.FEATURES_PATH).write_text("# fixture features\n")
    (host / module.IN_TREE_PLUGINS_PATH).write_text("# fixture loader\n")
    destination = plugin / ".dev" / module.ASSEMBLY_NAME
    module.assemble(host=host, plugin_root=plugin, destination=destination, copy_plugin=True)
    assembled = destination / "src/sparkrun/plugins/sparkroute"
    assert not assembled.is_symlink()
    assert (assembled / "__init__.py").read_bytes() == (plugin_source / "__init__.py").read_bytes()
    (assembled / "__init__.py").write_text("# copied only\n")
    assert (plugin_source / "__init__.py").read_text() == "VERSION = 'test'\n"
    assert not (host / "src/sparkrun/plugins/sparkroute").exists()


def test_explicit_binary_skips_preparation(tmp_path):
    plugin, _, env = _development_tree(tmp_path)
    result = subprocess.run(
        ["bash", "-c", 'source "$PLUGIN_ROOT/dev.sh"'],
        capture_output=True,
        text=True,
        env={**env, "PLUGIN_ROOT": str(plugin), "SPARKRUN_SPARKROUTE_BINARY": env["FAKE_GATEWAY_BINARY"]},
    )
    assert result.returncode == 0, result.stderr
    assert "Using explicit SparkRoute development binary" in result.stdout
    assert not Path(env["FAKE_GATEWAY_LOG"]).exists()


def test_binary_preparation_failure_does_not_report_success(tmp_path):
    plugin, _, env = _development_tree(tmp_path)
    result = subprocess.run(
        ["bash", "-c", 'source "$PLUGIN_ROOT/dev.sh"'],
        capture_output=True,
        text=True,
        env={**env, "PLUGIN_ROOT": str(plugin), "FAKE_GATEWAY_STATUS": "17"},
    )
    assert result.returncode != 0
    assert "Done." not in result.stdout
    assert not Path(env["FAKE_SPARKRUN_LOG"]).exists()


@pytest.mark.parametrize("missing", ["api/_catalog.py", "core/readiness.py", "core/recipe.py", "core/recipe_items.py", "api/proxy/_ops.py"])
def test_old_shared_host_uses_compatible_project_checkout(tmp_path: Path, missing):
    plugin, git_log, env = _development_tree(tmp_path)
    project_api = plugin / ".dev/sparkrun/src/sparkrun/api"
    project_api.mkdir(exist_ok=True)
    (project_api / "_catalog.py").write_text("def catalog_cluster_capacity(): pass\n")
    old = tmp_path / "old-host"
    _checkout(old)
    (old / "src/sparkrun" / missing).unlink()
    result = subprocess.run(
        ["bash", "-c", 'source "$PLUGIN_ROOT/dev.sh" && echo "selected=$SPARKRUN_CHECKOUT"'],
        env={**env, "PLUGIN_ROOT": str(plugin), "SPARKRUN_CHECKOUT": str(old)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Selected host lacks current catalog, recipe, and restart support" in result.stdout
    assert "selected=" + str(plugin / ".dev/sparkrun") in result.stdout


def test_project_worktree_branch_is_not_rewritten(tmp_path: Path):
    plugin, git_log, env = _development_tree(tmp_path)
    git = plugin / ".dev/sparkrun/.git"
    git.rmdir()
    git.write_text("gitdir: /example/worktrees/sparkrun\n")
    result = subprocess.run(
        ["bash", "-c", 'source "$PLUGIN_ROOT/dev.sh"'], env={**env, "PLUGIN_ROOT": str(plugin)}, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "without changing its branch" in result.stdout
    commands = git_log.read_text() if git_log.exists() else ""
    assert "fetch" not in commands and "switch" not in commands
