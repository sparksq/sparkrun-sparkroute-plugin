# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
# Additional permission under AGPLv3 section 7: see src/sparkrun/plugins/sparkroute/LICENSE_EXCEPTION.

"""Explicit transport admission and conservative legacy receipt migration."""

from __future__ import annotations

import json
from .protocol import ProtocolError


def require_transport(db, expected):
    db.execute("CREATE TABLE IF NOT EXISTS transport (id INTEGER PRIMARY KEY, name TEXT)")
    row = db.execute("SELECT name FROM transport WHERE id=1").fetchone()
    if row and row[0] != expected:
        raise ProtocolError("transport_changed", "Gateway transport changed; use the selected backend instead of retrying here")


def select_transport(transport, *, sctx, provision=None):
    from sparkrun.utils.fs import file_lock
    from .jobs import _path

    from sparkrun.daemon.state import private_directory

    private_directory(_path(sctx).parent)
    with file_lock(_path(sctx).with_suffix(".transport.lock")):
        _select_transport(transport, sctx=sctx)
        if provision is not None:
            provision()


def _select_transport(transport, *, sctx):
    if transport not in {"bridge", "daemon"}:
        raise ValueError("Gateway transport must be bridge or daemon")
    from contextlib import nullcontext
    from sparkrun.daemon.auth import TokenStore
    from sparkrun.daemon.state import Binding
    from sparkrun.api.workloads import Receipts
    from .jobs import _connect, _path, _alive

    binding = Binding.from_config(sctx.config)
    retirement = TokenStore(binding).retire_manager("sparkroute") if transport == "bridge" else nullcontext()
    with retirement, _connect(_path(sctx)) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS transport (id INTEGER PRIMARY KEY, name TEXT)")
        selected = db.execute("SELECT name FROM transport WHERE id=1").fetchone()
        if selected and selected[0] == transport and transport == "daemon":
            return
        if transport == "daemon":
            rows = db.execute("SELECT * FROM operations").fetchall()
            if any(row["state"] == "running" and (not row["pid"] or _alive(row["pid"])) for row in rows):
                raise ProtocolError(
                    "legacy_workers_active", "Drain the existing SparkRoute bridge workers before enabling daemon transport"
                )
            journal = Receipts(sctx)
            for row in rows:
                if not row["placement"]:
                    continue
                request = json.loads(row["request"])
                revision = (request.get("binding") or {}).get("recipe_revision")
                if not revision:
                    raise ProtocolError("legacy_receipt_unresolved", "Resolve legacy placement revision before switching transport")
                placement = json.loads(row["placement"])
                # Old workers did not durably distinguish post-launch effects.
                phase = "ready" if row["state"] == "succeeded" else "hooks_started"
                identifier = "bridge-" + row["id"]
                # A reconciled/stopped core receipt supersedes this old record.
                if not any(item["id"] == identifier for item in journal.placements(revision, "sparkroute")):
                    journal.save(identifier, revision, "sparkroute", placement, phase)
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='workload_states'").fetchone():
                for row in db.execute("SELECT * FROM workload_states"):
                    if journal.state(row["job_id"]) is None:
                        journal.state(row["job_id"], row["state"])
        else:
            from sparkrun.daemon.jobs import JobStore, TERMINAL

            if (binding.directory / "jobs.sqlite3").exists():
                with JobStore.from_config(binding.directory, sctx.config).transaction() as jobs:
                    active = jobs.execute(
                        "SELECT operation,state FROM jobs WHERE manager='sparkroute' OR operation LIKE 'plugins.sparkroute.%'"
                    ).fetchall()
                    if any(row["state"] not in TERMINAL for row in active):
                        raise ProtocolError("daemon_jobs_active", "Drain SparkRoute daemon jobs before switching transport")
        db.execute("INSERT OR REPLACE INTO transport VALUES(1,?)", (transport,))
