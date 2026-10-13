# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
# Additional permission under AGPLv3 section 7: see src/sparkrun/plugins/sparkroute/LICENSE_EXCEPTION.

"""Feature activation uses the shared host lifecycle, independently of loading."""

from types import SimpleNamespace

import pytest


def test_declarations_are_static_and_owned():
    from sparkrun.core.plugin_manifest import read_declarations
    from sparkrun.plugins import sparkroute

    declaration = read_declarations(sparkroute.__file__, sparkroute.__name__)
    assert declaration["features"]["gateway.sparkroute"]["default"] is False
    assert declaration["hooks"] == {"feature.enable": "sparkrun.plugins.sparkroute.lifecycle:enable_feature"}


def test_enable_feature_delegates_to_shared_gateway_policy(monkeypatch):
    from sparkrun.plugins.sparkroute import lifecycle

    calls = []
    sentinel = object()
    monkeypatch.setattr(lifecycle, "select_gateway", lambda context, name: calls.append((context, name)) or sentinel)
    context = SimpleNamespace(feature="gateway.sparkroute")
    assert lifecycle.enable_feature(context) is sentinel
    assert calls == [(context, "sparkroute")]
    assert lifecycle.enable_feature(SimpleNamespace(feature="another.feature")) is None


def test_gateway_support_and_capability_gate_registration(monkeypatch):
    from sparkrun.plugins import sparkroute
    from sparkrun.proxy import gateway

    monkeypatch.setenv("SPARKRUN_FEATURE_GATEWAY", "0")
    monkeypatch.setenv("SPARKRUN_FEATURE_GATEWAY_SPARKROUTE", "1")
    monkeypatch.setattr(gateway, "register_gateway", lambda *args, **kwargs: pytest.fail("gateway registered while support disabled"))
    sparkroute.register(None)


def test_managed_feature_activation_selects_gateway_and_preserves_other_settings(managed_plugin):
    from pathlib import Path
    import sparkrun.plugins
    from sparkrun.core.plugin_lifecycle import change_feature, change_plugin
    from sparkrun.core.config import SparkrunConfig
    from sparkrun.proxy.config import ProxyConfig

    config = managed_plugin.config
    proxy = ProxyConfig(config.config_path.parent / "proxy.yaml")
    proxy.set_proxy(gateway="litellm", port=7189)
    proxy.save()
    original = list(sparkrun.plugins.__path__)
    checkout = Path(__file__).resolve().parents[1] / "src/sparkrun/plugins"
    try:
        # Match the actual source-copy installation: it is not also pip-installed.
        sparkrun.plugins.__path__[:] = [p for p in original if Path(p).resolve() != checkout]
        result = change_feature(config, "gateway.sparkroute", True)
        assert result["status"] == "enabled"
        assert ProxyConfig(proxy.config_path).gateway == "sparkroute"
        assert ProxyConfig(proxy.config_path).port == 7189
        assert SparkrunConfig(config.config_path).feature_override("gateway.litellm") is None
        change_plugin(config, "sparkroute", False)
        assert ProxyConfig(proxy.config_path).gateway == "sparkroute"
    finally:
        sparkrun.plugins.__path__[:] = original
