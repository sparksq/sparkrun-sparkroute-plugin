# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
# Additional permission under AGPLv3 section 7: see src/sparkrun/plugins/sparkroute/LICENSE_EXCEPTION.

"""Gateway-specific endpoint metadata projections; lifecycle belongs to core."""

from functools import partial


def invoke(name, arguments, sctx, prompt=None):
    from sparkrun.api import workloads
    from .bridge_workloads import _binding, _project

    if name == "endpoints.metadata":
        from sparkrun import api
        from .metadata import build_model_metadata
        from .operations import _recipe_of

        job = next((j for j in api.list_jobs(sctx=sctx) if j.cluster_id == arguments["cluster_id"]), None)
        if job is None or (job.metadata or {}).get("recipe_fingerprint") != arguments["recipe_revision"]:
            return {"model_metadata": {}}
        return {"model_metadata": build_model_metadata(_recipe_of(job), arguments["served_models"])}
    binding = _binding(arguments["binding"]) if arguments.get("binding") else None
    revision = workloads.resolve_binding(binding, sctx=sctx)[1] if binding else ""
    result = workloads.endpoints(
        recipe_revision=revision,
        cluster_candidates=binding.cluster_candidates if binding else (),
        cluster_id=arguments.get("cluster_id", ""),
        sctx=sctx,
    )
    endpoints = [_project(ep, sctx, result["observed_at"], owner=sctx.operation.manager) for ep in result["endpoints"][:256]]
    if name == "endpoints.status":
        return {"state": "ready" if endpoints else "offline", "endpoint": endpoints[0] if endpoints else None}
    return {"endpoints": endpoints}


def _load(name):
    return partial(invoke, name)


def register():
    from sparkrun.plugins import DaemonOp, register_plugin_daemon_op
    from sparkrun.api._wire import object_schema
    from .daemon_schemas import RESULTS

    binding = object_schema(
        {
            "recipe": {"type": "string", "maxLength": 4096},
            "recipe_revision": {"type": "string", "maxLength": 1024},
            "overrides": {"type": "object", "additionalProperties": {"type": "string", "maxLength": 4096}},
            "cluster_candidates": {"type": "array", "items": {"type": "string", "maxLength": 1024}, "maxItems": 64},
        },
        ["recipe"],
    )
    for name in ("endpoints.discover", "endpoints.status", "endpoints.metadata"):
        fields, required = {"binding": binding}, []
        if name == "endpoints.status":
            fields["cluster_id"] = {"type": "string", "maxLength": 1024}
            fields["binding"] = {**binding, "required": ["recipe", "recipe_revision"]}
            required = ["binding", "cluster_id"]
        if name == "endpoints.metadata":
            fields = {
                "cluster_id": {"type": "string", "maxLength": 1024},
                "recipe_revision": {"type": "string", "maxLength": 1024},
                "served_models": {"type": "array", "items": {"type": "string", "maxLength": 1024}, "maxItems": 256},
            }
            required = list(fields)
        register_plugin_daemon_op(
            DaemonOp(
                name,
                partial(_load, name),
                object_schema(fields, required),
                result_schema=RESULTS[name],
                kind="query" if name == "endpoints.metadata" else "job",
                scope="read",
                resources="none",
                feature_flag="gateway.sparkroute",
                description="Project verified workload endpoints into SparkRoute model cards and routing metadata.",
            )
        )
