# SparkRoute daemon transport

The unreleased 0.4 integration supports direct daemon HTTP/SSE for workload
activation, discovery, lifecycle, the admin catalog and request-profile refresh.
The stdio bridge remains an explicitly selectable fallback. Both transports use
the host's shared workload workflow and effect receipts; the daemon path does not
start a bridge subprocess or a second plugin job queue.

## Compatible development builds

This work needs the coordinated Sparkrun host, this plugin and a SparkRoute binary
with `-sparkrun-daemon-connection`. `compat/host.toml` and `compat/gateway.toml`
pin the tested host and gateway commits for this integration. Make both source
commits available before publishing the plugin; the default released gateway may
not yet include daemon transport. During development,
use an explicit matching `SPARKRUN_CHECKOUT` with `dev.sh` and `SPARKROUTE_BINARY`
pointing at the rebuilt Go binary. Tests support `SPARKRUN_DEV_CHECKOUT` and
`SPARKROUTE_TEST_BINARY`. A version string alone does not prove these capabilities.
The engine checks binary support and registered daemon operation version before
starting a native connection.

## Enable

Enable the `daemon`, `core.external_plugins` and `gateway.sparkroute` features in
the same Sparkrun configuration/profile as the gateway. Install the plugin through
the managed plugin loader. In `proxy.yaml`:

```yaml
proxy:
  gateway: sparkroute
  gateway_transport: daemon
  discovery_backend: daemon
  auto_discover: true
  discover_interval: 30
```

Start with `sparkrun proxy start`. A matching local daemon is attached or started;
other CLI commands retain their usual execution mode. The gateway service and
discovery watcher use separate daemon service slots (`max_services`, default 2).
Stopping discovery leaves the gateway serving. Stopping the proxy also stops its
watcher. A foreground CLI waits for the separately supervised gateway without
holding the startup mutation reservation for its entire lifetime.

The engine writes a private `gateway/daemon-client.json` descriptor beneath its
state directory. It follows the daemon’s local address and has a dedicated
`manager: sparkroute` credential. Startup rotates that private token without changing management identity
or the principal used for retained jobs/idempotency. Tokens apply on UDS as well
as TCP. It is not part of gateway exports. For manually managed remote connections, see SparkRoute's `docs/SPARKRUN_DAEMON.md`; TLS/UDS/token policy
is enforced by the daemon independently of gateway management.

## Operations and ownership

Core `workloads.ensure_ready`, `stop`, `inventory`, `status`, `sleep`, `wake`,
`plugins` and `reconcile` serve the native gateway. Their bindings are flat
(`recipe`, `recipe_revision`, `cluster_candidates`, `overrides`), identical to
other daemon clients. Binding/catalog/profile resolution uses core `catalog.*`.

The plugin registers only `plugins.sparkroute.endpoints.discover`,
`endpoints.status` and `endpoints.metadata`, with generated
`/v1/plugins/sparkroute/ops/endpoints/...` aliases. These add gateway model cards;
the metadata-only query checks the saved recipe revision and cannot establish
readiness. It is optional enrichment after activation, without another health
probe or changing the core observation time. Use `/v1/ops` for installed contracts
and the host’s `docs/DAEMON_API.md` for the complete inventory. The previous
plugin lifecycle/binding/capability daemon registrations were removed, without aliases.

Every action binds a recipe revision and selected cluster candidates. The server
authenticates manager `sparkroute` from the provisioned credential; clients cannot
supply an owner in arguments or headers. Job admission snapshots that manager and
workers reuse it. The gateway verifies the manager reported by `/v1/info` before
submitting work. Management ownership is independent of token scope and is not
tenant isolation: gateway admin catalog access still requires admin scope. A healthy external
workload can be adopted for routing without permission to stop/sleep/wake it.
Mutation requires exact workload ID, matching revision/selection and ownership.
ColdSnap contributes the host lifecycle provider contract; no ColdSnap subprocess
or private module discovery is needed in daemon handlers.

Endpoint DTOs contain observed live served-model IDs and original observation
timestamps. Go admission expires stale observations even after a reconnect. A
partial host sweep is not authoritative absence. Provider inventory is recorded
state; `workloads.status` performs a provider observation.

## Cutover and recovery

Stop new legacy submissions and drain bridge workers before switching. Transport
admission is persisted in the plugin's legacy operations store. Active or unclaimed
legacy work blocks switching to daemon; active daemon jobs with manager `sparkroute` block a
switch back. The reverse check and credential retirement share the daemon admission
lock, so a new job cannot slip in during cutover. Completed history stays readable. Existing placements/provider state
are imported into core receipts without replacing a later core reconciliation.

Core receipts live in `<config-root>/workload-receipts.sqlite3`, separate from the
daemon's job queue/history. Placements are saved before launch. A disconnected Go
client preserves its private action intent/key and accepted job ID. Retrying that
intent attaches to the same job; finishing a known terminal action lets the next
intent get a fresh key. Disconnecting does not cancel an accepted workload.

Interrupted post-launch hooks can have uncertain effects. Automatic replay is
blocked. Inspect the actual workload and hooks, then use the admin operation:

```sh
sparkrun daemon --url http://127.0.0.1:8376 --token-file /private/sparkroute.token \
  call workloads.reconcile --data \
  '{"recipe":"@registry/recipe","recipe_revision":"EXACT_REVISION","cluster_candidates":["lab"],"workload_id":"EXACT_WORKLOAD_ID","acknowledge_effects":true}'
```

Reconciliation requires complete placement observations and, for a running
workload, exact ownership/revision plus a healthy live model identity. It records
operator acknowledgement; it does not rerun hooks or silently tear down workloads.
Unknown coverage stays blocked. Resource reservation reconciliation is a separate
admin operation; it does not certify application side effects.

## Validation boundaries

Managed-install tests run a real daemon and real Go gateway on isolated local
ports; they exercise direct catalog traffic and independent discovery lifetime.
Unit tests cover scope, revisions/ownership, uncertain effects, cutover gates,
transport retries, SSE gaps, authorization and freshness. Native macOS/Windows,
systemd service containment and real GPU/ColdSnap restore remain release-matrix
checks. Shared probe caching is deferred until measured duplication justifies it.
