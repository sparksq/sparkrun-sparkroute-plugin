# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
# Additional permission under AGPLv3 section 7: see src/sparkrun/plugins/sparkroute/LICENSE_EXCEPTION.

from copy import deepcopy

import pytest
import yaml

from sparkrun.plugins import GatewayOperationError
from sparkrun.plugins.sparkroute.config import SparkrouteConfig
from sparkrun.plugins.sparkroute.engine import SparkrouteEngine
from sparkrun.proxy.config import ProxyConfig


def seed(tmp_path, document):
    path = tmp_path / "proxy.yaml"
    path.write_text(yaml.safe_dump(document))
    return path, SparkrouteConfig(ProxyConfig(path))


def read(path):
    return yaml.safe_load(path.read_text())


def test_namespaced_settings_and_state_preserve_other_configuration(tmp_path):
    settings = {
        "transport": "daemon",
        "config": "seed.yaml",
        "admin_host": "127.0.0.2",
        "admin_port": 8083,
        "allow_insecure_admin_nonloopback": True,
        "capability_policy": "strict",
        "bindings": [{"recipe": "@local/model", "overrides": {"model": "test"}}],
        "discovered_models": ["warm"],
        "future": {"nested": 1},
    }
    document = {
        "proxy": {"gateway": "sparkroute", "port": 4001, "master_key": "keep-private"},
        "aliases": {"alias": "warm"},
        "gateways": {
            "sparkroute": settings,
            "litellm": {"router_settings": {"routing_strategy": "least-busy"}},
            "another": {"future": 1},
        },
        "custom": {"keep": True},
    }
    path, cfg = seed(tmp_path, document)
    before = path.read_bytes()
    assert cfg.gateway_config == "seed.yaml"
    assert cfg.gateway_transport == "daemon"
    assert cfg.gateway_admin_host == "127.0.0.2" and cfg.gateway_admin_port == 8083
    assert cfg.gateway_admin_configured and cfg.gateway_allow_insecure_admin_nonloopback
    assert cfg.capability_policy == "strict"
    assert cfg.bindings == settings["bindings"] and cfg.discovered_models == ["warm"]
    assert cfg.aliases == document["aliases"] and cfg.port == 4001
    assert cfg.proxy.discovery_backend == "daemon"
    assert path.read_bytes() == before
    cfg.set_discovered_models(["new"])
    cfg.save()
    expected = deepcopy(document)
    expected["gateways"]["sparkroute"]["discovered_models"] = ["new"]
    assert read(path) == expected
    previous = path.stat().st_mtime_ns
    cfg.save()
    assert path.stat().st_mtime_ns == previous


def test_legacy_keys_are_ignored_and_not_migrated(tmp_path):
    document = {
        "proxy": {
            "gateway_config": "old.yaml",
            "gateway_transport": "daemon",
            "gateway_admin_host": "127.0.0.2",
            "gateway_admin_port": 8001,
            "gateway_allow_insecure_admin_nonloopback": True,
            "capability_policy": "strict",
        },
        "bindings": [{"recipe": "old"}],
        "discovered_models": ["old"],
    }
    path, cfg = seed(tmp_path, document)
    assert cfg.gateway_config is None and cfg.gateway_transport == "bridge"
    assert cfg.gateway_admin_host == "127.0.0.1" and cfg.gateway_admin_port == 8081
    assert not cfg.gateway_admin_configured and not cfg.gateway_allow_insecure_admin_nonloopback
    assert cfg.capability_policy == "permissive"
    assert cfg.bindings == [] and cfg.discovered_models == []
    cfg.set_discovered_models(["new"])
    cfg.save()
    assert read(path) == {**document, "gateways": {"sparkroute": {"discovered_models": ["new"]}}}


def test_discovery_merges_latest_gateway_alias_and_listener_edits(tmp_path):
    path, discovery = seed(tmp_path, {"proxy": {"port": 4000}, "gateways": {"sparkroute": {"bindings": [{"recipe": "old"}]}}})
    bindings = SparkrouteConfig(ProxyConfig(path))
    alias = ProxyConfig(path)
    discovery.set_discovered_models(["b", "a", "a"])
    bindings.set_bindings([{"recipe": "new"}])
    bindings.save()
    alias.add_alias("alias", "a")
    alias.set_proxy(port=4002)
    alias.save()
    data = read(path)
    data["gateways"]["sparkroute"]["admin_port"] = 9081
    data["gateways"]["litellm"] = {"router_settings": {"routing_strategy": "least-busy"}}
    path.write_text(yaml.safe_dump(data))
    discovery.save()
    result = read(path)
    assert result["proxy"]["port"] == 4002 and result["aliases"] == {"alias": "a"}
    assert result["gateways"]["sparkroute"] == {"bindings": [{"recipe": "new"}], "discovered_models": ["a", "b"], "admin_port": 9081}
    assert result["gateways"]["litellm"]["router_settings"]["routing_strategy"] == "least-busy"
    discovery.set_discovered_models([])
    discovery.save()
    assert read(path)["gateways"]["sparkroute"]["discovered_models"] == []
    assert discovery.bindings == [{"recipe": "new"}]


def test_nested_reads_and_pending_values_are_detached(tmp_path):
    path, cfg = seed(tmp_path, {"gateways": {"sparkroute": {"bindings": [{"recipe": "r", "overrides": {"x": "y"}}]}}})
    before = deepcopy(read(path))
    cfg.bindings[0]["overrides"]["x"] = "mutated"
    assert cfg.bindings[0]["overrides"]["x"] == "y"
    proposed = [{"recipe": "r", "overrides": {"x": "z"}}]
    cfg.set_bindings(proposed)
    proposed[0]["overrides"]["x"] = "mutated"
    assert cfg.bindings[0]["overrides"]["x"] == "z"
    assert read(path) == before


@pytest.mark.parametrize("document", [{"gateways": []}, {"gateways": {"sparkroute": []}}])
def test_malformed_namespaces_are_never_overwritten(tmp_path, document):
    path, cfg = seed(tmp_path, document)
    before = path.read_bytes()
    cfg.set_discovered_models(["warm"])
    with pytest.raises(GatewayOperationError, match="mapping"):
        cfg.save()
    assert path.read_bytes() == before


def test_save_respects_plugin_transaction_and_lifecycle_guards(tmp_path, monkeypatch):
    path, cfg = seed(tmp_path, {})
    cfg.set_discovered_models(["warm"])
    before = path.read_bytes()
    journal = tmp_path / "plugins-transaction.yaml"
    journal.write_text("state: preparing\n")
    with pytest.raises(GatewayOperationError, match="Interrupted plugin activation"):
        cfg.save()
    journal.unlink()
    monkeypatch.setattr("sparkrun.core.config._lifecycle_snapshot", {})
    with pytest.raises(GatewayOperationError, match="Lifecycle hooks"):
        cfg.save()
    assert path.read_bytes() == before


def test_engine_consumes_new_settings_without_writing_during_preview(tmp_path, monkeypatch):
    path, cfg = seed(
        tmp_path,
        {
            "gateways": {
                "sparkroute": {
                    "admin_host": "127.0.0.2",
                    "admin_port": 9001,
                    "transport": "bridge",
                    "capability_policy": "strict",
                    "config": "seed.yaml",
                    "discovered_models": ["stale"],
                }
            },
        },
    )
    engine = SparkrouteEngine(state_dir=tmp_path / "state", proxy_config=cfg.proxy)
    before = path.read_bytes()
    monkeypatch.setattr(engine, "_discovered_cluster_names", lambda *args: ({}, {}))
    engine.prepare_config([], {}, write=False)
    assert path.read_bytes() == before
    assert engine.admin_port == 9001 and engine.admin_bind_host == "127.0.0.2"
    assert engine.admin_separate and not engine._permissive()
    assert engine.proxy_config.gateway_config == "seed.yaml"
    engine._persist_discovered_models([])
    assert read(path)["gateways"]["sparkroute"]["discovered_models"] == []
    assert "discovered_models" not in read(path)


@pytest.mark.parametrize("setting, expected", [({}, True), ({"auto_update_recipes": True}, True), ({"auto_update_recipes": False}, False)])
def test_recipe_auto_update_defaults_on_and_honors_opt_out(tmp_path, setting, expected):
    path, cfg = seed(tmp_path, {"gateways": {"sparkroute": setting}})
    before = path.read_bytes()
    assert cfg.auto_update_recipes is expected
    assert path.read_bytes() == before


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None, [], {}])
def test_recipe_auto_update_requires_yaml_boolean(tmp_path, value):
    _, cfg = seed(tmp_path, {"gateways": {"sparkroute": {"auto_update_recipes": value}}})
    with pytest.raises(GatewayOperationError, match="auto_update_recipes must be true or false"):
        _ = cfg.auto_update_recipes
