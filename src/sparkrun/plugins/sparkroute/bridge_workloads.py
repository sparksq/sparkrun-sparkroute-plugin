# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
# Additional permission under AGPLv3 section 7: see src/sparkrun/plugins/sparkroute/LICENSE_EXCEPTION.

"""Released stdio bridge DTO adapters over the shared workload API.

These helpers register no daemon operations.
"""

from __future__ import annotations


OWNER = "sparkroute"


def _binding(value):
    from sparkrun.api.workloads import WorkloadBinding

    return WorkloadBinding(**{**value, "cluster_candidates": tuple(value.get("cluster_candidates", ()))})


def _workload(row):
    return {
        "job_id": row["workload_id"],
        "cluster_name": row["cluster_name"] or "",
        "recipe_revision": row["recipe_revision"],
        "owned": row["owned"],
        "plugins_in_use": [row["provider"]] if row["provider"] else [],
        "lifecycle_actions": row["actions"],
        "lifecycle_state": row["state"],
    }


def _project(endpoint, sctx, observed_at, *, owner=OWNER):
    from sparkrun import api
    from .metadata import build_model_metadata
    from .operations import _recipe_of

    job = next((j for j in api.list_jobs(sctx=sctx) if j.workload_id == endpoint["workload_id"]), None)
    metadata = build_model_metadata(_recipe_of(job), endpoint["actual_models"])
    if endpoint.get("max_model_len"):
        for model in endpoint["actual_models"]:
            metadata.setdefault(model, {})["context"] = endpoint["max_model_len"]
    info = next(
        (row for row in api.workloads.inventory(owner=owner, sctx=sctx)["workloads"] if row["workload_id"] == endpoint["workload_id"]),
        None,
    )
    return {
        "state": "ready",
        "workload_id": endpoint["workload_id"],
        "job_id": endpoint["workload_id"],
        "cluster_name": endpoint.get("cluster_name") or "",
        "host": endpoint["host"],
        "port": endpoint["port"],
        "protocol": "openai",
        "served_models": endpoint["actual_models"],
        "recipe": (job.recipe if job else "") or "",
        "recipe_revision": endpoint["recipe_revision"],
        "runtime": endpoint["runtime"],
        "owned": bool(owner and endpoint["owner"] == owner),
        "plugins_in_use": [info["provider"]] if info and info["provider"] else [],
        "lifecycle_actions": info["actions"] if info else [],
        "model_metadata": metadata,
        "observed_at": observed_at,
    }


def invoke(name, arguments, sctx, prompt=None, *, legacy=True):
    """Keep expected failures typed across either selected transport."""
    from sparkrun.api.workloads import WorkloadError
    from sparkrun.api import RecipeNotFound, SparkrunError
    from .protocol import ProtocolError

    try:
        return _invoke(name, arguments, sctx, prompt, legacy=legacy)
    except ProtocolError as exc:
        if legacy:
            raise
        raise WorkloadError(exc.code, exc.message, retryable=exc.retryable) from exc
    except WorkloadError as exc:
        if not legacy:
            raise
        raise ProtocolError(exc.code, str(exc), retryable=exc.retryable) from exc
    except RecipeNotFound as exc:
        if not legacy:
            raise
        raise ProtocolError("recipe_not_found", "configured recipe could not be resolved") from exc
    except SparkrunError as exc:
        if not legacy:
            raise
        raise ProtocolError("resolve_failed", "configured recipe could not be resolved") from exc


def _invoke(name, arguments, sctx, prompt=None, *, legacy=False):
    from sparkrun.api import workloads

    binding = _binding(arguments["binding"]) if arguments.get("binding") else None
    if name == "workloads.inventory":
        result = workloads.inventory(owner=OWNER, sctx=sctx)
        return {
            "workloads": [_workload(row) for row in result["workloads"]],
            "plugins": _plugins(sctx),
            "complete": result.get("complete", False),
        }
    if name == "capabilities":
        return {"integration_version": 1, "plugins": _plugins(sctx)}
    if name.startswith("endpoints."):
        revision = (binding.recipe_revision or workloads.resolve_binding(binding, sctx=sctx)[1]) if binding else ""
        result = workloads.endpoints(
            recipe_revision=revision,
            cluster_candidates=binding.cluster_candidates if binding else (),
            workload_id=arguments.get("workload_id", ""),
            sctx=sctx,
        )
        endpoints = [_project(ep, sctx, result["observed_at"]) for ep in result["endpoints"][:256]]
        if name == "endpoints.status":
            return {"state": "ready" if endpoints else "offline", "endpoint": endpoints[0] if endpoints else None}
        return {"endpoints": endpoints}
    if binding is None:
        raise ValueError("A recipe binding is required")
    if name == "bindings.resolve":
        recipe, revision, _ = workloads.resolve_binding(binding, sctx=sctx)
        return {"recipe": recipe.qualified_name, "recipe_revision": revision, "model": recipe.model, "runtime": recipe.runtime}
    if name == "workloads.ensure_ready":
        result = workloads.ensure_ready(binding, owner=OWNER, timeout=arguments.get("timeout", 900), sctx=sctx)
        return {
            "state": result["state"],
            "adopted": result["adopted"],
            "endpoint": _project(result["endpoint"], sctx, result["observed_at"]),
        }
    if name == "workloads.reconcile":
        return workloads.reconcile(
            binding, arguments["workload_id"], owner=OWNER, acknowledge_effects=arguments.get("acknowledge_effects", False), sctx=sctx
        )
    if name == "workloads.stop":
        return workloads.stop(binding, arguments["workload_id"], owner=OWNER, sctx=sctx)
    action = name.rsplit(".", 1)[-1]
    result = workloads.control(binding, arguments["workload_id"], action, owner=OWNER, sctx=sctx)
    row = next(row for row in workloads.inventory(owner=OWNER, sctx=sctx)["workloads"] if row["workload_id"] == result["workload_id"])
    return {**_workload(row), "state": result["state"]}


def _plugins(sctx):
    from sparkrun.api import workloads

    return [
        {
            "name": row["plugin_id"] or row["name"],
            "installed": True,
            "enabled": row["enabled"] and row["loaded"],
            "lifecycle": bool(row["lifecycle"]),
        }
        for row in workloads.plugins(sctx=sctx)
    ]
