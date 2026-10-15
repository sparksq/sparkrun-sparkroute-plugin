# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
# Additional permission under AGPLv3 section 7: see src/sparkrun/plugins/sparkroute/LICENSE_EXCEPTION.

"""SparkRoute-owned proxy settings under ``gateways.sparkroute``.

Reads are side-effect free. Writes use the host's proxy lock and atomic writer,
merging the newest document so discovery cannot erase concurrent operator edits.
"""

from __future__ import annotations

from copy import deepcopy

import yaml

from sparkrun.plugins import GatewayOperationError


def _namespace(document):
    gateways = document.get("gateways", {})
    if not isinstance(gateways, dict):
        raise GatewayOperationError("proxy.yaml gateways must be a mapping")
    settings = gateways.get("sparkroute", {})
    if not isinstance(settings, dict):
        raise GatewayOperationError("proxy.yaml gateways.sparkroute must be a mapping")
    return deepcopy(settings)


class SparkrouteConfig:
    """Gateway view over a host ProxyConfig; common settings remain delegated."""

    def __init__(self, proxy):
        self.proxy = proxy
        self._pending = {}

    def __getattr__(self, name):
        return getattr(self.proxy, name)

    def _value(self, key, default=None):
        # Read the host's in-memory document so explicit pending CLI settings
        # retain their normal semantics. Returned nested values are detached.
        return deepcopy(self._pending.get(key, _namespace(self.proxy._data).get(key, default)))

    @property
    def gateway_config(self):
        value = self._value("config")
        return str(value) if value else None

    @property
    def gateway_transport(self):
        value = self._value("transport", "bridge")
        if value not in {"bridge", "daemon"}:
            raise GatewayOperationError("gateways.sparkroute.transport must be bridge or daemon")
        return value

    @property
    def gateway_admin_host(self):
        return str(self._value("admin_host", "127.0.0.1"))

    @property
    def gateway_admin_port(self):
        return int(self._value("admin_port", 8081))

    @property
    def gateway_admin_configured(self):
        settings = _namespace(self.proxy._data)
        return "admin_host" in settings or "admin_port" in settings

    @property
    def gateway_allow_insecure_admin_nonloopback(self):
        return bool(self._value("allow_insecure_admin_nonloopback", False))

    @property
    def capability_policy(self):
        value = str(self._value("capability_policy", "permissive")).strip().lower()
        return value if value in {"permissive", "strict"} else "permissive"

    @property
    def bindings(self):
        value = self._value("bindings", [])
        if not isinstance(value, list) or any(not isinstance(entry, dict) for entry in value):
            raise GatewayOperationError("gateways.sparkroute.bindings must be a list of mappings")
        return value

    @property
    def discovered_models(self):
        value = self._value("discovered_models", [])
        if not isinstance(value, list):
            raise GatewayOperationError("gateways.sparkroute.discovered_models must be a list")
        return sorted({str(model).strip() for model in value if str(model).strip()})

    def set_bindings(self, bindings):
        self._pending["bindings"] = deepcopy(bindings)

    def set_discovered_models(self, models):
        self._pending["discovered_models"] = sorted({str(model).strip() for model in models if str(model).strip()})

    def save(self):
        """Merge only pending gateway keys into the latest document under its lock."""
        from sparkrun.core.config import _lifecycle_snapshot

        if _lifecycle_snapshot is not None:
            raise GatewayOperationError("Lifecycle hooks must return configuration plans")
        with self.proxy._write_lock():
            journal = self.proxy.config_path.parent / "plugins-transaction.yaml"
            if journal.exists():
                transaction = yaml.safe_load(journal.read_text())
                if not isinstance(transaction, dict) or transaction.get("state") != "committed":
                    raise GatewayOperationError("Interrupted plugin activation; run a plugin management command to recover")
            latest = self.proxy._read(strict=True)
            result = deepcopy(latest)
            settings = _namespace(result)
            settings.update(deepcopy(self._pending))
            if settings or "sparkroute" in result.get("gateways", {}):
                result.setdefault("gateways", {})["sparkroute"] = settings
            if result != latest:
                self.proxy._write_atomic(result)
        self._pending.clear()
        # Preserve any unrelated pending host edits; its save still merges
        # just those keys, and must not regain a stale whole-document view.
        self.proxy._data = result


def gateway_config_view(proxy):
    if isinstance(proxy, SparkrouteConfig) or proxy is None:
        return proxy
    # Preserve the documented lightweight provider/config test doubles.
    if hasattr(proxy, "_write_lock") and hasattr(proxy, "_read"):
        return SparkrouteConfig(proxy)
    return proxy
