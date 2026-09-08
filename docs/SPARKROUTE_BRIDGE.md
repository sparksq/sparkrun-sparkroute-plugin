# LLM Gateway bridge

sparkrun ships a hidden, machine-oriented command used by SparkRoute, the OSS
LLM gateway formed by converging the Scitrera LLM Gateway execution engine with
Fox SparkRoute's model-policy engine:

```text
sparkrun gateway-bridge
```

It is a one-shot child process, not a daemon. The caller writes one bounded JSON
object to standard input and reads one JSON object from standard output. Human
diagnostics and logging use standard error. The command is intentionally omitted
from `sparkrun --help`; its versioned JSON schema, rather than Click's command
presentation, is the compatibility boundary.

Schema version 4 supports `capabilities`, `resolve`, `ensure_ready`, `discover`,
`status`, `stop`, `workloads`, `sleep`, `wake`, `workload_status`, and the catalog operations below. Requests carry a
caller-generated `request_id`; every response repeats it. Both sides use strict
schema decoding. Update the plugin and gateway together; earlier schemas are
not accepted.

A binding contains a configured recipe reference, its sparkrun fingerprint,
named cluster candidates, and bounded recipe overrides. Discovery, adoption,
registration, and shutdown all enforce the selected cluster using authoritative
job metadata. A job with an unknown cluster cannot satisfy a cluster restriction.

## Catalog and configuration

SparkRoute requires `-sparkrun` to enable these admin routes and its workload
controller. The plugin adds the flag automatically. `-sparkrun-command` chooses
the bridge executable but does not opt in by itself. Shared admin/inference
listeners classify `/v1/sparkrun/*` as admin traffic.

The bridge delegates to the public `sparkrun.api` catalog helpers:

| Operation | Arguments / result |
| --- | --- |
| `catalog_registries` | Configured registry availability, visibility, and trust; no refresh. |
| `catalog_clusters` | Named clusters, host counts, and the current default; no SSH. |
| `catalog_search` | `query`, `registry`, `runtime`, `local_only`, `filters`, `offset`, `limit`; cached results with exact source references and pagination. |
| `catalog_resolve` | `reference`, optional `overrides`; model, native protocols, revision, plugin requirements, and validation issues. |
| `catalog_import` | Bounded single-document YAML `content`; returns an untrusted managed import preview. |
| `catalog_retain` | `reference`; retains a saved import. |
| `catalog_refresh` | Starts a durable registry refresh; returns an operation ID. |
| `operation_status` | `operation_id`; progress or a persisted result. Never starts a worker. |

Canonical `catalog:<id>` references preserve exact file/registry identity,
including duplicate recipe names and paths containing spaces. Search reads
registry caches and the control node's configuration-directory `recipes/` and
`recipe-catalog/imports/` roots. It never relies on the gateway's working
directory. Explicit local paths refer to the control node, not the browser.
Uploads are limited to 256 KiB. Unused staged uploads expire after seven days;
saved imports remain available. Uploading does not grant trust or import
auxiliary build files. Registry trust requires an explicit acknowledgement in the UI or CLI.

SparkRoute exposes these through authenticated `POST /v1/sparkrun/catalog` and
prepares an operator draft through `POST /v1/sparkrun/recipe-draft`. Read roles
can browse; writer roles are required for upload/refresh/draft preparation.
The existing managed-set Validate and Save endpoints recheck recipe revisions
and clusters against the merged operator/generated configuration. Preparation,
validation, and saving do not start models. An unavailable catalog leaves
cloud-only provider configuration usable.

## Ownership

A recipe fingerprint identifies a serve *configuration*, not a *workload
instance*: an operator running the same recipe by hand produces the same digest
as the gateway does. Adoption and teardown therefore have deliberately different
rules. Every workload the bridge launches is tagged `owner: sparkroute` in
Sparkrun job metadata.

`ensure_ready` may adopt a healthy endpoint matching the fingerprint and selected cluster,
preferring an owned one — routing to a workload someone else started is
harmless and avoids a duplicate launch. `stop` refuses anything the bridge did
not launch (`job_not_owned`); with no `cluster_id` it tears down only the owned
matches. Killing a workload a human is using is not recoverable by retrying, so
the destructive direction fails closed.

Endpoint projections include `owned` and `cluster_name`. Private API keys and
raw job metadata stay on the control node. Idle shutdown is available only for
owned workloads; shared request leases span gateway configuration generations.
Deleting a route disables its idle policy without stopping the job.

## Durable activation and timing

`ensure_ready` admits a detached controller-local worker before returning when
`wait` is false. Poll `operation_status` for `running`, `succeeded`, or `failed`,
its phase, and the eventual endpoint result. Synchronous callers wait on the
same durable operation. Aliases of the same recipe revision and cluster share
one worker. Different recipes can activate independently.

The worker uses the normal `api.plan` / `api.run` path, automatic port selection,
post-launch hooks, and shared startup-readiness checks. It records planned
placement before launching and the actual assigned port before readiness.
`timeout_seconds` includes launch time but cannot interrupt an in-flight remote
launch. A caller timeout or gateway restart does not kill the worker. Retry
reconciles its recorded placement and persisted jobs before launching again.
An unreachable previous job or uncertain interrupted post-launch hooks fails
with an actionable recovery error instead of risking a duplicate launch.

Operation state lives in `sparkroute/operations.sqlite3` under sparkrun's
configuration directory, with bounded private `<operation-id>.log` files beside
it. Terminal records and their logs expire after seven days. Dead-worker status
is read-only; a new activation request resumes reconciliation. Idle timers are
process-local; after a gateway restart, observed owned workloads begin a new
idle interval. Multi-gateway shared ownership is outside this local bridge's
scope.

Successful endpoint projections contain cluster/job identity, host, port,
protocol, served models, runtime, and recipe fingerprint. They never contain the
upstream API key retained in owner-only Sparkrun job metadata. The Go gateway
constructs and validates the URL, adds its deployment/binding identity and local
fencing token, and authorizes the exact registration before routing.
Authenticated inference therefore requires a separately configured credential
reference on the gateway provider or deployment; job metadata is not a secret
delivery channel.

## Model metadata

`discover` and `ensure_ready` endpoints may carry an optional `model_metadata`
map — the public strategy fields from the model card Sparkrun already has, so
the gateway's `smallest` / `largest` / `lowest_cost` selectors need no
hand-authored duplicates. The contract is SparkRoute's
`docs/SPARKRUN_MODEL_METADATA_CONTRACT.md`; the producer is
`plugins/sparkroute/metadata.py`.

```json
"model_metadata": {
  "Qwen/Qwen3-32B": {
    "size_b": 32.0, "context": 65536,
    "input_price": 0.0, "output_price": 0.0,
    "tags": ["fp8", "local", "vllm"]
  }
}
```

Each key is an exact served model identity that also appears in
`served_models`, and every field inside is optional. Four rules make it safe to
publish:

* **Advisory only.** It cannot register an endpoint, add or enable a logical
  model, change routing weight, or deliver a credential — and it can never make
  a valid inference endpoint ineligible. Every failure path drops the field
  rather than the endpoint.
* **Reported, never inferred.** An unknown value is omitted, because the gateway
  ranks real deployments against these numbers. `size_b` comes from
  `model_params`, present only when a launch estimated VRAM. `context` is the
  *effective* runtime limit from the recipe's config chain, not the model's
  nominal family limit — reporting the larger one would route requests the
  runtime rejects; `auto` is therefore unreportable.
* **Zero is a value.** Local inference has a *known* free price, which is what
  lets a `lowest_cost` selector prefer it; an unknown price is omitted instead.
* **Public and bounded.** Tags are a fixed set (locality, runtime,
  quantization), so no operator free text becomes a tag. Secrets, credential
  references, endpoint URLs, raw model-card JSON and error text never appear.

The map is read from the recipe state persisted in job metadata — the card as
it was *at launch*, which is what the running workload actually serves — so
nothing here reaches the network on the inference path. A job predating recipe
state persistence simply omits the field, which the Go struct treats as an
ordinary `omitempty` absence.

A configuration tool can obtain the exact fingerprint, including overrides, by
sending a `resolve` request. For example:

```json
{"schema_version":4,"request_id":"resolve-1","operation":"resolve","binding":{"recipe":"@local/qwen","cluster_candidates":["spark-a"],"overrides":{"tensor_parallel":"2"}}}
```

The returned `result.recipe_revision` is the value pinned in the gateway's
`endpoint_source.recipe_revision`.

The bridge calls the console-free `sparkrun.api` surface directly. Request data
is never interpolated into a shell command, and recipes that require interactive
trust are rejected instead of prompting. The intended deployment is a single
local OSS gateway, normally on the cluster head node. It does not provide
multi-replica coordination; that remains outside Sparkrun's local bridge.

## Stage 4 operations

`catalog_registry` applies an explicit add/remove/enable/disable/trust/untrust
operation. `trust` requires `acknowledge_trust: true`; adding a registry does not
clone or trust it. `catalog_capacity` starts a durable advisory cluster check.
`catalog_plugins` reports installed/enabled/lifecycle availability without
claiming a workload uses the plugin. Search returns declared metadata facets;
resolve returns `hf_model`, safe `defaults`, metadata, and `native_api_options`
from the runtime family alongside native families and Responses capability.

`workloads` reports bounded receipt identities, plugin use, lifecycle state, and
available actions. `sleep` and `wake` require a binding and exact job in
`cluster_id`; `workload_status` verifies that job without changing its state.
Sleep/wake run in detached workers sharing activation exclusion with
`ensure_ready`, including overlapping candidate cluster sets. Uncertain replies
remain non-ready. SparkRoute exposes these controls through authenticated
`POST /v1/sparkrun/workload`, requiring `config_write` and a configured deployment.
