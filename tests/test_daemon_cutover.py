# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
# Additional permission under AGPLv3 section 7: see src/sparkrun/plugins/sparkroute/LICENSE_EXCEPTION.

"""Transport admission and one-way import of legacy uncertainty."""

import json
import os
from unittest.mock import Mock

import pytest
from sparkrun import api
from sparkrun.api.workloads import Receipts
from sparkrun.plugins.sparkroute import cutover, jobs, bridge_workloads
from sparkrun.plugins.sparkroute.protocol import ProtocolError


def legacy(ctx, *, state="failed", revision="rev", pid=None):
    # Simulates a placement recorded by a pre-rename bridge worker, which wrote
    # ``cluster_id``; sparkrun's Receipts journal decodes it to ``workload_id``
    # on read (see sparkrun.api.workloads._placement).
    placement = {"cluster_id": "workload", "cluster": "lab", "hosts": ["host"]}
    with jobs._connect(jobs._path(ctx)) as db:
        db.execute(
            "INSERT INTO operations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "a" * 32,
                "key",
                json.dumps({"binding": {"recipe_revision": revision}}),
                state,
                "launch",
                pid,
                1,
                None,
                None,
                json.dumps(placement),
            ),
        )
    return placement


def test_live_or_unclaimed_legacy_worker_blocks_daemon():
    ctx = api.default_sctx()
    legacy(ctx, state="running", pid=os.getpid())
    for pid in (os.getpid(), None):
        with jobs._connect(jobs._path(ctx)) as db:
            db.execute("UPDATE operations SET pid=?", (pid,))
        with pytest.raises(ProtocolError, match="Drain"):
            cutover.select_transport("daemon", sctx=ctx)
        with jobs._connect(jobs._path(ctx)) as db:
            cutover.require_transport(db, "bridge")


def test_import_retains_uncertainty_and_never_overwrites_reconciliation():
    ctx = api.default_sctx()
    placement = legacy(ctx)
    with jobs._connect(jobs._path(ctx)) as db:
        db.execute("CREATE TABLE workload_states (job_id TEXT, state TEXT)")
        db.execute("INSERT INTO workload_states VALUES ('workload', 'sleeping')")
    cutover.select_transport("daemon", sctx=ctx)
    journal = Receipts(ctx)
    (row,) = journal.placements("rev", "sparkroute")
    # Receipts decodes the legacy ``cluster_id`` key to ``workload_id`` on read.
    decoded = {**placement, "workload_id": placement["cluster_id"]}
    del decoded["cluster_id"]
    assert row["phase"] == "hooks_started" and row["placement"] == decoded
    assert journal.state("workload") == "sleeping"
    journal.save(row["id"], "rev", "sparkroute", placement, "stopped")
    journal.state("workload", "stopped")
    cutover.select_transport("bridge", sctx=ctx)
    cutover.select_transport("daemon", sctx=ctx)
    (row,) = journal.placements("rev", "sparkroute")
    assert row["phase"] == "stopped" and journal.state("workload") == "stopped"


def test_missing_revision_blocks_import_without_switching_transport():
    ctx = api.default_sctx()
    legacy(ctx, revision="")
    with pytest.raises(ProtocolError, match="revision"):
        cutover.select_transport("daemon", sctx=ctx)
    with jobs._connect(jobs._path(ctx)) as db:
        cutover.require_transport(db, "bridge")


def test_selected_daemon_rejects_legacy_admission():
    ctx = api.default_sctx()
    cutover.select_transport("daemon", sctx=ctx)
    with jobs._connect(jobs._path(ctx)) as db:
        cutover.require_transport(db, "daemon")
        with pytest.raises(ProtocolError, match="transport changed"):
            cutover.require_transport(db, "bridge")
    with pytest.raises(ValueError, match="bridge or daemon"):
        cutover.select_transport("anything", sctx=ctx)


def test_reverse_cutover_drains_core_jobs_and_retires_manager_credentials():
    from sparkrun.core.daemon_registry import get_daemon_op
    from sparkrun.daemon.ops import register_core_ops
    from sparkrun.daemon.jobs import JobStore
    from sparkrun.daemon.state import Binding
    from sparkrun.daemon.auth import TokenStore

    ctx = api.default_sctx()
    register_core_ops()
    cutover.select_transport("daemon", sctx=ctx)
    binding = Binding.from_config(ctx.config)
    tokens = TokenStore(binding)
    _, token = tokens.create("gateway", manager="sparkroute")
    store = JobStore(binding.directory)
    job = store.submit(get_daemon_op("workloads.ensure_ready"), {"recipe": "r"}, "gateway", "", {}, manager="sparkroute")
    with pytest.raises(ProtocolError, match="Drain"):
        cutover.select_transport("bridge", sctx=ctx)
    assert tokens.authenticate(token).manager == "sparkroute"
    with store.transaction() as db:
        db.execute("UPDATE jobs SET state='succeeded' WHERE id=?", (job,))
    cutover.select_transport("bridge", sctx=ctx)
    with pytest.raises(PermissionError):
        tokens.authenticate(token)


def test_daemon_registrations_only_expose_gateway_projections(monkeypatch):
    from sparkrun.core import daemon_registry
    from sparkrun.core.plugin_identity import PluginIdentity, plugin_registration
    from sparkrun.plugins.sparkroute.daemon import register

    monkeypatch.setattr(daemon_registry, "_OPERATIONS", {})
    with plugin_registration(PluginIdentity("sparkroute", "sparkrun.plugins.sparkroute", ("external", "fixture", None))):
        register()
    names = {op.name for op in daemon_registry.registered_daemon_ops() if op.owner == "sparkroute"}
    assert names == {"plugins.sparkroute.endpoints." + name for name in ("discover", "status", "metadata")}


def test_bridge_preserves_nonretryable_uncertain_hooks(monkeypatch):
    ctx = api.default_sctx()
    monkeypatch.setattr(
        api.workloads,
        "ensure_ready",
        Mock(side_effect=api.workloads.WorkloadError("recovery_requires_operator", "Inspect interrupted hooks")),
    )
    with pytest.raises(ProtocolError) as caught:
        bridge_workloads.invoke("workloads.ensure_ready", {"binding": {"recipe": "test", "recipe_revision": "rev"}}, ctx, legacy=True)
    assert caught.value.code == "recovery_requires_operator" and not caught.value.retryable
