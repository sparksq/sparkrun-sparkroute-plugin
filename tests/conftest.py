# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
# Additional permission under AGPLv3 section 7: see src/sparkrun/plugins/sparkroute/LICENSE_EXCEPTION.

"""Run the plugin source against an installed or checked-out sparkrun host."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPARKRUN_CHECKOUT = os.environ.get("SPARKRUN_DEV_CHECKOUT") or os.environ.get("SPARKRUN_CHECKOUT")
if SPARKRUN_CHECKOUT:
    host_source = Path(SPARKRUN_CHECKOUT).expanduser().resolve() / "src"
    if not (host_source / "sparkrun" / "__init__.py").is_file():
        raise RuntimeError("SPARKRUN_CHECKOUT does not point to a sparkrun checkout: %s" % SPARKRUN_CHECKOUT)
    sys.path.insert(0, str(host_source))
    # Detached test workers must import the same host as the parent pytest process.
    os.environ["PYTHONPATH"] = os.pathsep.join(filter(None, (str(host_source), os.environ.get("PYTHONPATH"))))

try:
    import sparkrun.plugins
except ImportError as error:
    raise RuntimeError("SparkRoute plugin tests require sparkrun; run 'source dev.sh' or install it explicitly") from error

plugin_parent = str(ROOT / "src" / "sparkrun" / "plugins")
if plugin_parent in sparkrun.plugins.__path__:
    sparkrun.plugins.__path__.remove(plugin_parent)
sparkrun.plugins.__path__.insert(0, plugin_parent)


@pytest.fixture(autouse=True)
def isolate_sparkrun_state(tmp_path: Path, monkeypatch):
    """Keep plugin tests away from developer configuration and network state."""
    monkeypatch.setenv("SPARKRUN_NO_INSTALLED_PLUGINS", "1")
    monkeypatch.delenv("SPARKRUN_APPLICATION_PROFILE", raising=False)
    monkeypatch.delenv("SPARKRUN_APPLICATION_CONFIG", raising=False)
    try:
        from sparkrun.core.application_profile import _reset_application_profile_for_tests
        from sparkrun.core.installed_plugins import reset_installed_plugins
        from sparkrun.core.external_plugins import clear_loaded_plugin_modules
    except ImportError:
        pass
    else:
        _reset_application_profile_for_tests()
        reset_installed_plugins()
        clear_loaded_plugin_modules()
        import sparkrun.core.config as config_module

        monkeypatch.setattr(config_module, "_application_config_path", None)
    monkeypatch.setenv("STATEFUL_ROOT", str(tmp_path / "stateful"))
    monkeypatch.setenv("SPARKRUN_NO_TELEMETRY", "1")
    monkeypatch.setenv("SPARKRUN_NO_EXTERNAL_PLUGINS", "1")

    import sparkrun.core.bootstrap as bootstrap
    import sparkrun.core.config as config
    import sparkrun.core.registry as registry
    import sparkrun.core.recipe_items as recipe_items
    from sparkrun.core.features import FEATURE_FLAGS, FeatureFlag
    from sparkrun.core.in_tree_plugins import IN_TREE_PLUGIN_FEATURES

    try:
        from sparkrun.core.registry_defaults import reset_declared_registries
    except ImportError:
        reset_declared_registries = None

    monkeypatch.setattr(config, "DEFAULT_CONFIG_DIR", tmp_path / "config", raising=False)
    monkeypatch.setattr(config, "DEFAULT_CACHE_DIR", tmp_path / "cache" / "sparkrun", raising=False)
    monkeypatch.setattr(registry, "BOOTSTRAP_REGISTRY_URLS", [], raising=False)
    monkeypatch.setattr(registry.RegistryManager, "_clone_or_pull", lambda self, entry: False, raising=False)
    monkeypatch.setattr(recipe_items, "_RECIPE_ITEMS", dict(recipe_items._RECIPE_ITEMS))
    monkeypatch.setitem(
        FEATURE_FLAGS,
        "gateway.sparkroute",
        FeatureFlag(name="gateway.sparkroute", description="Standalone SparkRoute plugin tests", default=False),
    )
    monkeypatch.setitem(IN_TREE_PLUGIN_FEATURES, "sparkroute", "gateway.sparkroute")
    if reset_declared_registries is not None:
        reset_declared_registries()
    bootstrap._variables = None
    yield
    bootstrap._variables = None
    if reset_declared_registries is not None:
        reset_declared_registries()


@pytest.fixture
def managed_plugin(tmp_path, monkeypatch):
    """A genuine source-copy installation available to separately bootstrapped children."""
    import shutil
    from sparkrun import api
    from sparkrun.core.plugin_manager import PluginManager
    from sparkrun.core.plugin_manifest import read_manifest
    from sparkrun.core.plugin_sources import PluginCandidate

    monkeypatch.delenv("SPARKRUN_NO_EXTERNAL_PLUGINS", raising=False)
    monkeypatch.setenv("SPARKRUN_FEATURE_GATEWAY_SPARKROUTE", "1")
    monkeypatch.setenv("SPARKRUN_CACHE_DIR", str(tmp_path / "cache"))
    ctx = api.default_sctx()
    ctx.config.set("features", {"daemon": True, "core.external_plugins": True, "gateway.sparkroute": True, "plugins.oci_relay": False})
    ctx.config.set("cache_dir", str(tmp_path / "cache"))
    ctx.config.save()
    snapshot = tmp_path / "source-copy"
    snapshot.mkdir()
    for name in ("plugin.toml", "pyproject.toml"):
        shutil.copy2(ROOT / name, snapshot / name)
    shutil.copytree(ROOT / "src", snapshot / "src", ignore=shutil.ignore_patterns("__pycache__"))
    metadata = read_manifest(snapshot)
    candidate = PluginCandidate(
        metadata, snapshot, {"kind": "git", "url": metadata.repository, "ref": "main", "ref_kind": "branch"}, "1" * 40
    )
    original = list(sparkrun.plugins.__path__)
    try:
        sparkrun.plugins.__path__[:] = [p for p in original if Path(p).resolve() != ROOT / "src/sparkrun/plugins"]
        PluginManager(ctx.config).install(candidate, trust=True, enable=True)
    finally:
        sparkrun.plugins.__path__[:] = original
    return ctx
