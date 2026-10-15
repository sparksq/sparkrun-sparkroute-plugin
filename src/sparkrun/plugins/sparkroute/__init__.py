# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
# Additional permission under AGPLv3 section 7: see src/sparkrun/plugins/sparkroute/LICENSE_EXCEPTION.

"""LLM Gateway integration — sparkrun-supervised Go gateway, both directions.

An external plugin (see :mod:`sparkrun.plugins`) contributing:

* **Outbound** — :class:`~.engine.SparkrouteEngine`, registered as the
  SparkRoute gateway. Sparkrun acquires the pinned release binary
  (:mod:`.release`), manages private live admin/caller token files
  (:mod:`.credentials`), starts the gateway in SQLite configuration mode, and
  replaces its managed set through the admin API (:mod:`.admin`) from a
  projection of the binding catalog (:mod:`.projection`).
* **Inbound** — the hidden ``sparkrun gateway-bridge`` command
  (:mod:`.cli`), a one-shot JSON stdio protocol (:mod:`.protocol`,
  :mod:`.bridge`, :mod:`.operations`) the gateway drives as a child process to
  discover, activate and stop workloads.

Plugin loading is controlled by ``sparkrun plugins enable/disable sparkroute``.
The ``gateway.sparkroute`` capability controls gateway and bridge registration;
the default-on ``gateway`` feature controls shared gateway support. Explicitly
enabling the capability also selects SparkRoute for subsequent proxy starts.
Disabling the plugin preserves settings and generic process status/stop recovery.

"""

from __future__ import annotations

__version__ = "0.3.3"

import logging

SPARKRUN_PLUGIN_API_VERSION = 1
SPARKRUN_PLUGIN_MANIFEST = {
    "api": 1,
    "features": {
        "gateway.sparkroute": {"description": "SparkRoute gateway and workload bridge", "default": False},
    },
    "hooks": {"feature.enable": "sparkrun.plugins.sparkroute.lifecycle:enable_feature"},
}

logger = logging.getLogger(__name__)

#: Selector for this gateway (``proxy.gateway`` in ``proxy.yaml``).
GATEWAY_NAME = "sparkroute"

#: Flag gating both halves of the integration.
FEATURE_FLAG = "gateway.sparkroute"

#: Name of the hidden bridge command this plugin contributes.
BRIDGE_COMMAND = "gateway-bridge"


def _load_engine() -> type:
    """Deferred import of the engine class for the gateway registry."""
    from sparkrun.plugins.sparkroute.engine import SparkrouteEngine

    return SparkrouteEngine


def _load_bridge_command():
    """Build the Click command, only when the CLI actually attaches it.

    Registered as a loader rather than a built command because this plugin also
    loads on the console-free ``sparkrun.api`` path, where importing Click
    would be a layering violation. See :mod:`.cli` — the import lives inside
    the builder, since plugin scanning imports every submodule regardless.
    """
    from sparkrun.plugins.sparkroute.cli import build_gateway_bridge_command

    return build_gateway_bridge_command()


def register(v) -> None:
    """Plugin entry point, invoked by the shared plugin loader.

    Registers the recipe item, gateway implementation and hidden bridge command.
    These registrations are cheap and import nothing heavy — the engine arrives
    through a deferred loader, and the Click command imports its runner only
    when invoked — so a stock install that never touches this gateway pays
    almost nothing for it being here.
    """
    from sparkrun.plugins import feature_gate_enabled

    if not feature_gate_enabled("gateway", v) or not feature_gate_enabled(FEATURE_FLAG, v):
        return
    # This integration now shares recovery logic even in bridge fallback mode.
    # Fail before partial registration when an old 0.4 alpha pin lacks it.
    from sparkrun import api as host_api

    if not hasattr(host_api, "workloads"):
        raise RuntimeError(
            "SparkRoute requires a Sparkrun host with the shared workload/daemon APIs; "
            "use the coordinated migration build and update compat/host.toml before release"
        )
    from sparkrun.plugins import register_cli_command
    from sparkrun.plugins import register_recipe_item
    from sparkrun.plugins import register_gateway
    from .recipe_config import RECIPE_HANDLER

    register_recipe_item("sparkroute", RECIPE_HANDLER, owner=__name__, affects_fingerprint=False)
    register_gateway(GATEWAY_NAME, feature_flag=FEATURE_FLAG, loader=_load_engine)
    register_cli_command(_load_bridge_command, name=BRIDGE_COMMAND)
    from .daemon import register as register_daemon

    register_daemon()
    logger.debug("Registered the %s gateway and its bridge command", GATEWAY_NAME)


__all__ = ["BRIDGE_COMMAND", "FEATURE_FLAG", "GATEWAY_NAME", "register"]
