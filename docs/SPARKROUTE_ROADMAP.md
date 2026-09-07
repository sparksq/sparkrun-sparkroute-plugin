# SparkRoute changes needed for full sparkrun parity

> **The gateway is now SparkRoute**, formed by converging the Scitrera LLM
> Gateway execution engine with Fox SparkRoute's model-policy engine. The argv,
> managed-configuration API and bridge contracts sparkrun drives are unchanged
> by the rename; what moved is the binary name and the release-asset shape
> (archives — see `plugins/sparkroute/release.py`). References to "llm-gateway"
> below are historical.
>
> `SPARKROUTE_REPO` now tracks the upstream rename and is `sparksq/sparkroute`,
> matching the checkout's `module github.com/sparksq/sparkroute`. A module path
> is not by itself a GitHub slug, so confirm it against a real asset URL when
> the first release is pinned.
>
> **Item 4 is DONE** — sparkrun passes `-list-aliases`. **Item 5 is still
> outstanding** and remains gateway-first.

> **Status: items 1–3 are SUPERSEDED — do not implement.** The gateway shipped
> a mutable managed-configuration API backed by SQLite
> (`SPARKRUN_MANAGED_CONFIG_HANDOFF.md` in the llm-gateway repo). Sparkrun owns
> one entity set through authenticated HTTP with CAS, writes no gateway file,
> and never restarts the gateway to apply a change — so config merging (1),
> reload (2) and the health-listener models view (3) are all moot. Its §7
> runtime application also resolves the activation-lease concern that made (2)
> urgent.
>
> **Items 4 and 5 survive unchanged**, as does the wire-contract note: they
> concern the bridge, which is a separate channel in the opposite direction.
>
> See `SPARKROUTE_MANAGED_CONFIG_RESPONSE.md` for the accepted seam and the
> outstanding change requests.

Specification for the Go side of the sparkrun integration. Each item is
independent and stands alone; sparkrun works today without any of them, with
the limitations noted under "Without this".

Sparkrun's half is built and tested. Where sparkrun already has the code but it
is inert pending a gateway change, the constant gating it is named.

---

## 1. Repeatable `-config`, merged

**Why.** Sparkrun has two modes, and today they are mutually exclusive:

| Mode | `proxy.gateway_config` | Sparkrun renders the document | `proxy alias` / `sync` |
|---|---|---|---|
| managed | unset | yes | works |
| external | set | no — the operator's document is authoritative | refused |

A user who wants both the gateway's routing policy *and* sparkrun's alias
commands currently has to choose. Merging lets ownership split by *file*
instead of by field, which is the only clean split available: `config.Decode`
uses `DisallowUnknownFields`, so sparkrun cannot mark the entries it owns
inside a shared document, and round-tripping the operator's YAML would destroy
their comments and key order.

**Change.** Make `-config` repeatable (Go's `flag.Var` with a `[]string`
receiver), or add `-config-dir` reading `*.yaml` in lexical order.

**Semantics.**

- Load each document independently, then concatenate `providers`,
  `deployments` and `virtual_models` before a single `Validate()` over the
  merged result.
- A duplicate `name` within any of the three lists is an **error** naming both
  source files. Silent last-wins would make a sparkrun-generated entry
  shadow an operator's with no signal.
- Cross-file references must resolve: a `deployment.provider` may name a
  provider from another document, and a `pool.targets[].deployment` may name a
  deployment from another document. This is the point of the feature.
- `-config-check` validates the merged result and prints each contributing
  path.
- The `Version` becomes a digest over all documents in order, so a change in
  any of them is observable.

**Without this.** External mode has no model management; sparkrun refuses
`alias`/`sync` with a message pointing here rather than rewriting the
operator's file.

**Sparkrun side.** Already written. `GATEWAY_SUPPORTS_CONFIG_MERGE` in
`src/sparkrun/plugins/sparkroute/engine.py` (superseded — see the status note) was `False`; it would have been flipped with the pinned
version that gains this, and `build_command` starts passing both documents.
It must stay `False` until then — Go's `flag` package keeps only the *last*
value of a repeated string flag, so passing two `-config` flags to a gateway
that cannot merge would silently drop the operator's routing policy.

---

## 2. Reload without restart

**Why.** `configfile.Source` implements `Load` but not the `WatchSource`
interface declared alongside it, and nothing consumes `WatchSource`. So a
config change takes effect only at startup, and sparkrun must bounce the
process to apply an alias.

Sparkrun already restarts LiteLLM for the same reason, so this is *parity* — but
it costs more here, and that difference is the argument. LiteLLM restarts lose
in-flight requests. This gateway additionally holds, in memory, the controller
leases, fencing tokens and cold-start waiter queue for every `activatable`
deployment. Bouncing it to add an alias can orphan or re-activate a workload,
which is a materially worse failure than dropping a request.

**Change.** Either is fine:

- **SIGHUP** — simplest, and sparkrun already has the PID in its state file.
- **`WatchSource` on `configfile.Source`** — poll the existing sha256 `Version`
  and emit on change; no new dependency.

Either way the handler re-reads, `routing.Compile`s a new `*Snapshot`, and swaps
it atomically. `Compile` is already a pure `Document -> *Snapshot` function, so
this is mostly wiring.

**Semantics.**

- A document that fails to load or validate leaves the running snapshot in
  place and logs; a bad edit must never take the gateway down.
- In-flight requests finish against the snapshot they started on.
- Lifecycle targets are re-derived via `TargetsFromDocument`; an `activatable`
  deployment whose binding is unchanged must keep its lease and registered
  endpoint rather than being torn down and re-activated. This is the whole
  point — see the failure above.
- Log the old and new `Version`.

**Without this.** `sparkrun proxy alias add` restarts the gateway. Sparkrun
warns explicitly that in-flight requests and activation state are lost.

**Sparkrun side.** `SparkrouteEngine._apply_config_change()` is the single
place to switch from stop/start to a signal.

---

## 3. Models view on the operations listener

**Why.** `sparkrun proxy models` needs to read what the gateway is serving. The
data listener's `GET /v1/models` sits behind `-caller-auth-mode`, and sparkrun
holds no client credential; the admin listener is off unless `-admin-address`
is set. The operations listener (`127.0.0.1:9090` by default) already serves
`/health/live`, `/health/ready`, `/health/targets` and `/health/credentials`
unauthenticated on loopback, which is the right place for introspection that
is neither inference nor administration.

**Change.** Add `GET /health/models` to `gateway.Health.Handler()`, returning
the compiled snapshot's virtual models — name, aliases, visibility, and the
deployments backing each — plus the active config `Version`.

**Without this.** `SparkrouteEngine.list_models_via_api()` reports the
*configured* document rather than a live readback. Accurate in managed mode
(sparkrun wrote it) and honest in its docstring, but it cannot show drift
between the file and what the process actually compiled.

---

## 4. `-list-aliases` default when driven by sparkrun — **DONE**

> Resolved on the sparkrun side: `SparkrouteEngine.build_command` passes
> `-list-aliases`, which was the smaller of the two changes and leaves the
> gateway's own default alone. It should still be documented gateway-side as
> expected-on for the OSS single-node composition.

**Why.** `GET /v1/models` omits aliases unless `-list-aliases` is passed. Under
LiteLLM an alias is an ordinary `model_name` entry and always appears, so a
client enumerating models sees it. Diverging here breaks the drop-in promise
for clients that discover models rather than being told them.

**Change.** Either default it on, or leave the default and let sparkrun pass
the flag. Sparkrun passing it is the smaller change and keeps the gateway's own
default alone — but the flag should then be documented as expected-on for the
OSS single-node composition.

**Without this.** Aliases are addressable but not discoverable.

---

## 5. Bridge protocol version negotiation

**Why.** Sparkrun's half is fixed; the Go client is still the constraining half.

`pkg/sparkrun/bridge.go` pins `ProtocolVersion = 1`, sends exactly that, and
rejects any response whose `schema_version` differs as a correlation failure.
Sparkrun now accepts a *range* (`SUPPORTED_VERSIONS`) and replies in the version
it was asked for, including for the `unsupported_version` refusal — so a client
that asks for a version sparkrun does not serve gets a correlated, readable
error instead of an unexplained mismatch. The Go client cannot yet act on it.

**Change.**

- Replace the constant with a supported range, and treat a response whose
  version is *within* that range as valid rather than requiring equality with
  the request.
- On `unsupported_version`, retry once at the highest version sparkrun reports
  it serves.
- Add `supported_versions []int` to the `Capabilities` struct so
  `Capabilities()` at the floor version discovers the ceiling. Note this is
  additive to a struct decoded with `DisallowUnknownFields`, so sparkrun cannot
  send the field until the Go struct has it — the Go change must land first.

**Without this.** Both sides speak v1 and work. The cost is only paid at the
first bump, which is exactly when it is most expensive to fix.

---

## Wire-contract note

`decodeStrict` applies `DisallowUnknownFields` to every bridge result, so each
result's key set is a hard contract: an extra field fails the whole decode
rather than being ignored. Any field added to a bridge response requires the
corresponding Go struct to gain it **first**.

Sparkrun pins the current key sets against the Go struct names in
`tests/test_gateway_bridge.py`.

`model_metadata` is the worked example of doing this in the right order: the Go
`Endpoint` gained the optional field first (with `ModelMetadata`), so sparkrun
could then start emitting it without a protocol bump, and an older sparkrun
that omits it stays valid. See `docs/SPARKROUTE_BRIDGE.md`.

Two fields are still tracked internally and stripped at the response boundary
because the structs lack them:

| Field | Struct that would need it | What it carries |
|---|---|---|
| `owned` | `Endpoint` | Whether the bridge launched this workload. Sparkrun enforces ownership on `stop` regardless; exposing it would let the gateway show it. |
| `cluster_id` | `EnsureResult` | The launched cluster when `wait: false` returns `activating` with no endpoint yet. Without it that reply cannot be correlated to a workload — which is why `wait: false` is currently unusable by the Go client. |
