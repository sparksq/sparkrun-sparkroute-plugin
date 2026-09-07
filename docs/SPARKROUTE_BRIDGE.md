# LLM Gateway bridge

Sparkrun ships a hidden, machine-oriented command used by SparkRoute, the OSS
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

Schema version 1 supports `capabilities`, `resolve`, `ensure_ready`, `discover`,
`status`, and `stop`. Requests carry a caller-generated `request_id`; every
response repeats it. A binding can contain only a configured recipe reference,
its Sparkrun recipe fingerprint, ordered cluster candidates, and bounded recipe
overrides. `ensure_ready` adopts a healthy matching workload before launching a
new one, tries cluster candidates in order when capacity is unavailable, and
waits for an authenticated `/v1/models` health check.

## Ownership

A recipe fingerprint identifies a serve *configuration*, not a *workload
instance*: an operator running the same recipe by hand produces the same digest
as the gateway does. Adoption and teardown therefore have deliberately different
rules. Every workload the bridge launches is tagged `owner: sparkroute` in
Sparkrun job metadata.

`ensure_ready` may adopt any healthy endpoint matching the fingerprint,
preferring an owned one — routing to a workload someone else started is
harmless and avoids a duplicate launch. `stop` refuses anything the bridge did
not launch (`job_not_owned`); with no `cluster_id` it tears down only the owned
matches. Killing a workload a human is using is not recoverable by retrying, so
the destructive direction fails closed.

Ownership is *not* reported on the wire. The gateway decodes results with Go's
`DisallowUnknownFields`, so each result's key set is a hard contract and an
extra field fails the whole decode; the marker is stripped at the response
boundary. Exposing it means adding the field to the gateway's `Endpoint` struct
first.

## Timing

`ensure_ready` is synchronous through the whole launch — model download and
image distribution included — and `timeout_seconds` bounds the operation from
the moment the request is accepted, but is only *checked* at phase boundaries;
nothing interrupts a launch in flight. Send `"wait": false` to return in state
`activating` as soon as the launch call returns, then poll `status`. That does not make the call cheap, only shorter: the launch
itself is synchronous either way.

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
{"schema_version":1,"request_id":"resolve-1","operation":"resolve","binding":{"recipe":"@local/qwen","cluster_candidates":["spark-a"],"overrides":{"tensor_parallel":"2"}}}
```

The returned `result.recipe_revision` is the value pinned in the gateway's
`endpoint_source.recipe_revision`.

The bridge calls the console-free `sparkrun.api` surface directly. Request data
is never interpolated into a shell command, and recipes that require interactive
trust are rejected instead of prompting. The intended deployment is a single
local OSS gateway, normally on the cluster head node. It does not provide
multi-replica coordination; that remains outside Sparkrun's local bridge.
