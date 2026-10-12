# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
# Additional permission under AGPLv3 section 7: see src/sparkrun/plugins/sparkroute/LICENSE_EXCEPTION.

"""Managed plugin + real daemon + real Go gateway; no GPU or downloaded models."""

import json
import os
from pathlib import Path
import socket
import sys
import time
import urllib.request

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("SPARKROUTE_TEST_BINARY") or not os.environ.get("SPARKRUN_DEV_CHECKOUT"),
    reason="requires a built gateway and the host checkout test helpers",
)


def test_managed_daemon_gateway_and_independent_discovery(tmp_path, monkeypatch, managed_plugin):
    from sparkrun.daemon.state import Binding
    from sparkrun.core.process_identity import alive
    import yaml

    monkeypatch.setenv("SPARKRUN_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("SPARKRUN_NO_EXTERNAL_PLUGINS", raising=False)
    monkeypatch.setenv("SPARKRUN_FEATURE_GATEWAY_SPARKROUTE", "1")
    monkeypatch.setenv("SPARKROUTE_BINARY", os.environ["SPARKROUTE_TEST_BINARY"])
    monkeypatch.setenv("SPARKROUTE_OPERATIONS_ADDRESS", "127.0.0.1:0")
    ctx = managed_plugin
    # Use the local development HTTP helper, which tears down only this binding.
    sys.path.insert(0, str(Path(os.environ["SPARKRUN_DEV_CHECKOUT"]) / "tests"))
    from test_daemon import real_server, wait_state

    binding = Binding.from_config(ctx.config).prepare()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    proxy_path = ctx.config.config_path.parent / "proxy.yaml"
    proxy_path.write_text(
        yaml.safe_dump(
            {
                "proxy": {
                    "gateway": "sparkroute",
                    "gateway_transport": "daemon",
                    "host": "127.0.0.1",
                    "port": port,
                    "master_key": "test-token",
                    "discover_interval": 1,
                }
            }
        )
    )
    with real_server(binding) as (_, client):
        operations = {op["name"] for op in client.request("GET", "/v1/ops")}
        assert "workloads.ensure_ready" in operations
        assert not any(name.startswith("plugins.sparkroute.workloads.") for name in operations)
        start = client.call("proxy.start", {})["job_id"]
        try:
            result = client.wait(start, timeout=60)
            assert result["started"] and result["discovery_backend"] == "daemon"
            from sparkrun.daemon.client import Client, DaemonError

            descriptor = json.loads((tmp_path / "cache/proxy/gateway/daemon-client.json").read_text())
            token = Path(descriptor["token_file"]).read_text()
            server = binding.read_state()
            gateway_client = Client(
                socket_path=server.get("socket"), url=server.get("url") if not server.get("socket") else None, token=token
            )
            assert gateway_client.info()["manager"] == "sparkroute"
            inventory_job = gateway_client.call("workloads.inventory")["job_id"]
            assert isinstance(gateway_client.wait(inventory_job, timeout=20)["workloads"], list)
            assert gateway_client.request("GET", "/v1/jobs/" + inventory_job)["manager"] == "sparkroute"
            with pytest.raises(DaemonError) as stale:
                gateway_client.call("plugins.sparkroute.workloads.ensure_ready", {"binding": {"recipe": "obsolete"}})
            assert stale.value.status == 404
            state = yaml.safe_load((tmp_path / "cache/proxy/state.yaml").read_text())
            request = urllib.request.Request("http://127.0.0.1:%s/v1/models" % port, headers={"Authorization": "Bearer test-token"})
            with urllib.request.urlopen(request, timeout=10) as response:
                assert isinstance(json.load(response)["data"], list)
            # Query through the Go admin catalog: tests the native connection,
            # authorization, envelope adapter, and plugin-installed controller.
            from sparkrun.plugins.sparkroute.credentials import ReconcilerCredential

            credential = ReconcilerCredential(tmp_path / "cache/proxy/gateway")
            admin = urllib.request.Request(
                "http://127.0.0.1:%s/v1/sparkrun/catalog" % port,
                data=json.dumps({"operation": "catalog_registries", "arguments": {}}).encode(),
                headers={"Authorization": "Bearer " + credential.read_admin_token(), "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(admin, timeout=15) as response:
                assert response.status == 200
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                discovery = client.call("proxy.discovery.status")
                if discovery["state"] == "running":
                    break
                time.sleep(0.1)
            assert discovery["state"] == "running"
            client.call("proxy.discovery.stop")
            wait_state(client, discovery["job_id"], {"succeeded", "cancelled"})
            assert alive(state["process"])
        finally:
            job = client.call("proxy.stop", {})["job_id"]
            client.wait(job, timeout=30)
            if "state" in locals():
                wait_state(client, state["service_job"], {"succeeded", "cancelled"})
