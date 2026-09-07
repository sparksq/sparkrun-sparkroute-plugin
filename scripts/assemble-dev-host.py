#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only

"""Assemble a disposable sparkrun tree with the live SparkRoute source in-tree."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
ASSEMBLY_NAME = "sparkrun-with-sparkroute"
PLUGIN_MODULE_PATH = Path("src/sparkrun/plugins/sparkroute")
FEATURES_PATH = Path("src/sparkrun/core/features.py")
IN_TREE_PLUGINS_PATH = Path("src/sparkrun/core/in_tree_plugins.py")
_IGNORED_NAMES = {
    ".dev",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".slop",
    "__pycache__",
}
_FEATURE_PATTERN = re.compile(r"name\s*=\s*['\"]gateway\.sparkroute['\"]")
_BINDING_PATTERN = re.compile(
    r"(?:['\"]sparkroute['\"]\s*:|IN_TREE_PLUGIN_FEATURES\s*\[\s*['\"]sparkroute['\"]\s*\]\s*=)"
    r"\s*['\"]gateway\.sparkroute['\"]"
)

_FEATURE_BINDING = """

# BEGIN sparkrun-sparkroute development binding
# Added only to the disposable tree assembled by the plugin's dev.sh. The
# selected upstream checkout is never modified.
FEATURE_PLUGIN_SPARKROUTE = register_feature(
    FeatureFlag(
        name="gateway.sparkroute",
        description="SparkRoute gateway integration and workload bridge",
        default=False,
    )
)
# END sparkrun-sparkroute development binding
"""

_LOADER_BINDING = """

# BEGIN sparkrun-sparkroute development binding
# Added only to the disposable tree assembled by the plugin's dev.sh.
IN_TREE_PLUGIN_FEATURES["sparkroute"] = "gateway.sparkroute"
# END sparkrun-sparkroute development binding
"""


class AssemblyError(RuntimeError):
    """The selected host cannot be assembled safely."""


def _apply_host_seams(host: Path, plugin_root: Path) -> None:
    """Apply the reviewed, temporary host patch only to the disposable copy."""
    patch = plugin_root / "compat/sparkrun-host-seams.patch"
    if not patch.is_file():
        return
    config = host / "src/sparkrun/proxy/config.py"
    api = host / "src/sparkrun/api/proxy/_ops.py"
    if config.is_file() and api.is_file():
        if "def bindings(" in config.read_text() and "def ui(" in api.read_text():
            return
    # A temporary Git root prevents git apply from discovering the plugin's
    # parent repository and interpreting paths relative to that checkout.
    try:
        for command in (["init", "--quiet"], ["apply", "--check", str(patch)], ["apply", str(patch)]):
            subprocess.run(["git", "-C", str(host), *command], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        raise AssemblyError(
            "host compatibility patch does not apply; select the commit in compat/host.toml "
            "or a host with the SparkRoute proxy hooks already integrated: %s" % error.stderr.strip()
        ) from error
    finally:
        _remove_path(host / ".git")


def _ignore(_directory: str, names: list[str]) -> set[str]:
    return set(names).intersection(_IGNORED_NAMES)


def _append_if_missing(path: Path, pattern: re.Pattern[str], addition: str) -> None:
    contents = path.read_text(encoding="utf-8")
    if pattern.search(contents):
        return
    path.write_text(contents.rstrip() + addition + "\n", encoding="utf-8")


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def assemble(*, host: Path, plugin_root: Path, destination: Path) -> Path:
    """Build and return the disposable in-tree development checkout."""
    host = host.expanduser().resolve()
    plugin_root = plugin_root.expanduser().resolve()
    destination = destination.expanduser().resolve()
    expected_destination = (plugin_root / ".dev" / ASSEMBLY_NAME).resolve()
    if destination != expected_destination:
        raise AssemblyError("refusing to replace unexpected assembly destination: %s" % destination)
    if host == destination:
        raise AssemblyError("the source checkout and assembly destination must differ")

    plugin_source = plugin_root / PLUGIN_MODULE_PATH
    required = [
        host / "pyproject.toml",
        host / "src/sparkrun/__init__.py",
        host / FEATURES_PATH,
        host / IN_TREE_PLUGINS_PATH,
        plugin_root / "plugin.toml",
        plugin_source / "__init__.py",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise AssemblyError(
            "the selected checkout does not expose the sparkrun in-tree plugin seams; "
            "select a compatible branch such as develop-next (missing: %s)" % ", ".join(missing)
        )

    temporary = destination.with_name(".%s.tmp" % destination.name)
    _remove_path(temporary)
    try:
        shutil.copytree(host, temporary, symlinks=True, ignore=_ignore)

        _apply_host_seams(temporary, plugin_root)

        assembled_plugin = temporary / PLUGIN_MODULE_PATH
        _remove_path(assembled_plugin)
        assembled_plugin.parent.mkdir(parents=True, exist_ok=True)
        assembled_plugin.symlink_to(plugin_source, target_is_directory=True)

        _append_if_missing(temporary / FEATURES_PATH, _FEATURE_PATTERN, _FEATURE_BINDING)
        _append_if_missing(temporary / IN_TREE_PLUGINS_PATH, _BINDING_PATTERN, _LOADER_BINDING)

        _remove_path(destination)
        temporary.rename(destination)
    except Exception:
        _remove_path(temporary)
        raise

    return destination


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", type=Path, required=True, help="base sparkrun checkout to copy")
    parser.add_argument("--destination", type=Path, required=True, help="disposable assembled checkout")
    parser.add_argument("--plugin-root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        destination = assemble(host=args.host, plugin_root=args.plugin_root, destination=args.destination)
    except (AssemblyError, OSError) as error:
        print("error: %s" % error, file=sys.stderr)
        return 1
    print("Assembled in-tree SparkRoute development host: %s" % destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
