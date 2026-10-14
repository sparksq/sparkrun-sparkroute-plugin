# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
# Additional permission under AGPLv3 section 7: see src/sparkrun/plugins/sparkroute/LICENSE_EXCEPTION.

"""Version 1 SparkRoute projections; domain workflows remain host APIs."""

from sparkrun.api._wire import object_schema

S = {"type": "string"}
B = {"type": "boolean"}
A = {"type": "array", "items": S}
ENDPOINT = object_schema(
    {
        "state": {"type": "string", "enum": ["ready"]},
        "workload_id": S,
        "job_id": S,
        "cluster_name": S,
        "host": S,
        "port": {"type": "integer"},
        "protocol": {"type": "string", "enum": ["openai"]},
        "served_models": A,
        "recipe": S,
        "recipe_revision": S,
        "runtime": S,
        "owned": B,
        "plugins_in_use": A,
        "lifecycle_actions": A,
        "model_metadata": {"type": "object", "additionalProperties": {"type": "object"}},
        "observed_at": {"type": "number", "minimum": 0.001},
    },
    ["state", "workload_id", "job_id", "host", "port", "protocol", "served_models", "recipe_revision", "owned", "observed_at"],
)
RESULTS = {
    "endpoints.metadata": object_schema(
        {"model_metadata": {"type": "object", "additionalProperties": {"type": "object"}}}, ["model_metadata"]
    ),
    "endpoints.discover": object_schema({"endpoints": {"type": "array", "items": ENDPOINT}}, ["endpoints"]),
    "endpoints.status": object_schema({"state": S, "endpoint": {"anyOf": [ENDPOINT, {"type": "null"}]}}, ["state", "endpoint"]),
}
