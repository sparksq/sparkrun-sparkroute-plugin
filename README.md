<!--
SPDX-FileCopyrightText: 2026 Scitrera LLC
SPDX-FileCopyrightText: 2026 Fox Engine Ltd
SPDX-License-Identifier: AGPL-3.0-only
-->

# SparkRoute plugin for sparkrun

This repository provides sparkrun's SparkRoute integration, designed to be
vendored by a compatible sparkrun distribution as `sparkrun.plugins.sparkroute`.
It supervises the gateway and connects model discovery and workload lifecycle
controls to sparkrun.

**Host compatibility:** the published Sparkrun 0.3.8 package does not yet bundle
or discover this plugin. Installing this wheel alone does not enable it. Use
the tested development assembly below, or a host distribution that vendors the
plugin and includes the required compatibility hooks. `compat/host.toml` pins
the tested host source and patches. The commands below require that assembly
or a compatible distribution.

The integration starts SparkRoute with `-sparkrun` to enable the recipe catalog
and lifecycle controller. Standalone SparkRoute leaves this integration disabled
unless that flag is supplied.

The integration supervises a local SparkRoute OSS gateway and contributes the
hidden `sparkrun gateway-bridge` JSON command used for discovery, recipe
resolution, on-demand launch, and ownership-checked shutdown. Enable both
directions with `gateway.sparkroute`; selecting the gateway is a separate step.

```sh
sparkrun setup features enable gateway.sparkroute
sparkrun proxy start --gateway sparkroute --host 127.0.0.1
sparkrun proxy ui
```

## Development preview

The plugin is currently distributed as source for development and vendoring;
GitHub releases can provide source and wheel artifacts. There is no package
registry publisher. The default gateway is SparkRoute v0.0.1, with verified
archive digests for all six controller platforms. A compatible host downloads
the gateway when it starts, without requiring GitHub authentication. Installing
the package does not download or start a gateway.

`dev.sh` prepares a separate development binary. See
[DEV_PREVIEW.md](DEV_PREVIEW.md) for acquisition and build controls.

Use a local sparkrun checkout without modifying it:

```sh
export SPARKRUN_CHECKOUT=/path/to/sparkrun
source dev.sh
pytest
```

`dev.sh` copies the host to `.dev/sparkrun-with-sparkroute`, applies any required
reviewed host compatibility hooks there, and links this checkout's live plugin
source into its in-tree package. `compat/host.toml` records the tested host base;
`compat/sparkrun-host-seams.patch` carries the generic hooks awaiting upstream
integration. `compat/sparkrun-run-path.patch` keeps proxy load on the normal run
API and preserves resolved clusters through run, proxy load, and benchmark.
Each patch is skipped when its changes are already integrated. An
incompatible host fails before replacing the existing development assembly.
The original checkout is never fetched, switched, or edited. The patch is a
development aid; production sparkrun incorporates the host changes itself.

Without `SPARKRUN_CHECKOUT`, the setup script manages a clone of the official
sparkrun repository. `SPARKRUN_BRANCH` selects its branch (currently `develop-next` by default). Until the hooks are
released, use the commit in `compat/host.toml` or the integration host branch.
Setup also updates recipe registries and installs local pre-commit hooks, as
in the ColdSnap plugin workflow.

Gateway setup reuses a checked development cache, then tries GitHub release
assets and successful Actions distributions for the exact `compat/gateway.toml`
commit using your existing `gh` authentication. If none are available, it builds
that commit in Docker using the Go version in the source's `go.mod`, with local
Go as a fallback. Docker builds target the controller's OS and architecture.
Setup exports `SPARKRUN_SPARKROUTE_BINARY`; a binary you explicitly set takes
precedence. No GitHub credentials are forwarded into the build container.

On Windows, run `python scripts/assemble-dev-host.py --host C:/path/to/sparkrun
--destination .dev/sparkrun-with-sparkroute` followed by installation into your
Python environment. The assembler copies plugin source on Windows so it does
not require symlink privileges; rerun it after edits. `dev.sh` is the POSIX shell
convenience entry point.
After installing the packages on Windows, use PowerShell to prepare the gateway:

```powershell
$env:SPARKRUN_SPARKROUTE_BINARY = python scripts/prepare-dev-gateway.py
if ($LASTEXITCODE -ne 0) { throw "SparkRoute development setup failed" }
```

## Controller platforms

SparkRoute release targets are Linux, macOS, and Windows, each on amd64 and
arm64. The GPU hosts can use a different platform from this controller. Windows
archives contain `sparkroute.exe`; Linux/macOS archives contain `sparkroute`.
Native CI exercises both the gateway and the installed sparkrun bridge on all
six combinations. A source pin in `compat/gateway.toml` identifies the paired
Go checkout; it is separate from the verified release archive pins.

## Configuration ownership

sparkrun's `proxy.yaml` bindings project into the gateway's `sparkrun` managed
configuration set. The `operator` set remains independently editable through
the SparkRoute console. Reconciliation replaces only the sparkrun set under
revision checks and applies without a gateway restart. The console presents both
sets in the same lists, with generated entries grayed out and read-only.

Model routing offers strategy guidance, explicit agent-stage model roles, and
switching-sensitivity controls. The preview can simulate tool failures, edits,
passing tests, and compaction without calling or starting models. See the
[routing guide](https://github.com/sparksq/sparkroute/blob/v0.0.1/docs/MODEL_ROUTING.md)
for strategy configuration and examples.

The top-right **Configuration preset** selector shows **Default** or a named
preset. **Save as preset…** copies the saved operator configuration and selects
the new preset; normal configuration saves then update it. Select a preset to
validate and load its configuration, or use **Manage presets…** to rename or
delete named presets. Generated sparkrun entries remain shared. The last selected
preset and its configuration are restored on gateway restart. Loading protects
unsaved drafts and does not issue workload Start or Stop actions.

The lifecycle provider named `sparkrun` is shared by generated deployments and
operator-created on-demand bindings. Saving a recipe before the plugin has
populated it creates the same provider in the read-only sparkrun set; later
syncs reuse it. The gateway reserves this provider's default settings and keeps
it available while a sparkrun deployment references it. On the next Save or
sync, older uncustomized `sparkrun:operator` providers are consolidated into
`sparkrun` without changing deployment IDs, aliases, or binding revisions.
Customized legacy providers retain their settings. This reserved-provider
normalization is committed atomically across the two configuration sets.

Generated deployments have display titles such as `sparkrun:spark-a:Qwen3-8B`,
while their existing hashed `name` IDs remain unchanged. Recipe bindings use their
observed named clusters, matched by launch recipe fingerprint, then configured
cluster candidates (or `unassigned`). Discovery uses healthy endpoint cluster IDs
to look up named clusters locally, falling back to the cluster ID or `discovered`.
Multiple clusters are comma-separated. An optional local display cache preserves
discovery labels across CLI invocations; it never controls routing or workload
identity. Existing discovery snapshots get cluster labels on the next sync.

Explicit on-demand bindings remain present while their models are offline.
Normal `sparkrun run` and `sparkrun proxy load` workloads use discovery only;
loading a model does not create a durable activation binding. The separate
discovery snapshot drops stopped workloads on sync (or after auto-discovery's
configured grace period). `proxy unload` also performs a fresh discovery sync.

Older plugin versions automatically added `proxy load` recipes to `bindings` in
`~/.config/sparkrun/proxy.yaml`. Those existing entries remain explicit desired
state. In the UI, **Remove from sparkroute** beside the generated virtual model or
deployment excludes it and its generated names after Validate and Save, even
while stopped. Operator-created dependencies are identified for repair. The
exclusion survives `proxy sync` and restart; **Excluded sparkrun deployments**
under Model Deployments provides Restore. No manual `proxy.yaml` edit is needed,
and running workloads are left alone. The source binding remains in sparkrun's
configuration, with the exclusion saved in SparkRoute's operator configuration.
Alternatively, remove an unwanted YAML binding and sync, or use
`sparkrun proxy unload <recipe>` (which also stops the workload, if running).
Unload uses sparkrun's shared stop API and still retires the binding when the
workload is already gone. Registry references and their cached file paths match
the same recipe. Failed discovery or teardown keeps the registration intact;
`--dry-run` changes neither workloads nor registration. Existing
bindings are never discarded just because their workload is offline.
Recipe resolution and launch use sparkrun's normal trust checks. Adopting an
endpoint does not grant permission to stop a workload created by someone else.

## Configure an on-demand model

1. Open `sparkrun proxy ui`, then **Configuration → Model Deployments → Add deployment**, then select **sparkrun** as the deployment type.
2. Search cached registries, select a control-node file, or upload a recipe YAML.
   Select a result to preview its model, native protocols, and requirements.
3. Enter a public model name such as `coding`, optional aliases, and a named
   cluster. Set the cold-start wait and optionally enable idle shutdown.
4. Choose **Add to draft → Validate → Save**. Saving does not start the model.
5. Send a request for `coding`. SparkRoute starts or reuses the selected recipe
   on that cluster, waits for readiness, and forwards to its actual assigned port.

Choose **Local** for the ordinary provider/deployment form. Saved sparkrun
deployments have their own recipe summary and **Edit recipe settings** action;
applying settings preserves deployment IDs and virtual-model aliases.

The default cold-start wait is 30 minutes; client timeouts may need to be longer
than a model's first download/load. Idle shutdown is off by default (30 minutes
is suggested when enabled). Aliases share one deployment and its lifecycle
policy. Idle time begins after the last request finishes, including streams.
Workloads launched by someone else can be adopted but are never stopped by
SparkRoute's idle policy. Overview combines running deployments and activatable
workloads in one inventory, with separate lifecycle and routing/circuit state.
Inactive workloads stay visible before their first start and after stopping.
Select a deployment for cluster/job identity, ownership, queue limits, activation
progress, endpoint details, circuit failures, and recent activity.

Overview workload controls include **Start** for inactive recipe deployments and
**Stop** for SparkRoute-owned workloads, with or without ColdSnap. Start waits
for readiness through normal activation admission and does not send an inference
request. Stop requires no active requests and leaves the saved binding in place,
so Start or a later inference request can activate it again. ColdSnap workloads
also show Check status and the appropriate Sleep or Wake control. Adopted jobs
cannot be stopped, slept, or woken through the gateway. Controls explain when
active requests, an ongoing transition, or stale status prevents a change.

Activity and Diagnostics are secondary views within Overview for lifecycle
history, controller health, and endpoint inventory. The former `/admin/runtime`
URL opens Overview. Status refreshes every five seconds; each source retains its
last successful snapshot and reports failures independently. Search and filters
cover deployment/model names, provider, cluster, lifecycle, and circuit state;
activity counters also filter the inventory. Narrow screens show stacked cards
with the same workload controls.

Registry search is cache-only; **Refresh registries** is explicit and reports
partial failures. Local paths belong to the control node. Uploads do not grant
trust or include referenced auxiliary files. Validation and activation check
pinned recipe contents; changed recipes require a fresh preview. Unknown API
model names never trigger an inferred registry search or launch.

This flow requires the catalog API in the sparkrun core commit pinned in
`compat/host.toml`. The bridge uses strict schema v4; update the plugin and
pinned SparkRoute binary together. Named cluster metadata controls placement
and adoption. Older job records without it remain unknown; overlapping host
sets are not used to guess a cluster. See [the bridge contract](docs/SPARKROUTE_BRIDGE.md)
for durable launch recovery. Request profiles and ColdSnap lifecycle controls are described below.

## Versions, tests, and releases

`versions.yaml` controls both the plugin version and the default SparkRoute
version. Version/CI scripts use an immutable scitrera-repo-tools source pin:

```sh
python scripts/update-versions.py --check
python scripts/generate-ci-gha.py --check
```

CI assembles the commit-pinned host and runs Python 3.12/3.13 tests, lint,
version checks, and workflow drift checks. Release tags must match the catalog.
The repository-owned release workflow publishes wheels, source distributions,
and checksums to GitHub after its gates pass. It does not publish to PyPI.
The [release checklist](docs/RELEASING.md) covers license and history scans,
artifact inspection, and running the release workflow before tagging.

sparkrun's vendor importer records the exact plugin repository, commit, tree,
version, and content hashes in `vendor/sparkroute.lock` and packaged
`VENDORED.toml`. Edit the canonical plugin here, then update the host's vendor
pin; do not edit its vendored copy directly.

## License and provenance

The integration is AGPL-3.0-only with the additional permission in
[LICENSE_EXCEPTION](LICENSE_EXCEPTION) for combination with sparkrun. The
exception preserves the licensing of sparkrun's Apache-2.0 portions while
retaining the plugin's AGPL obligations. Both notices ship inside the package.
SparkRoute OSS is separately distributed under its own AGPL license.
Repository scripts and host patches retain their BSD-3-Clause and Apache-2.0
licenses; see [NOTICE](NOTICE), [REUSE.toml](REUSE.toml), and [LICENSES](LICENSES).

The initial source was extracted from sparkrun's
`feature/llm-gateway-integration` at
`03c79eff62a36defaf9ac9709021a2b90114829f`. The independent packaging and
development workflow follow `sparkrun-coldsnap-plugin`.

For a real local binary integration check (loopback HTTP, no GPU workload):

```sh
SPARKROUTE_TEST_BINARY=/absolute/path/sparkroute pytest tests/test_sparkroute_live.py
```

Acquired release archives remain beside their executable in the cache, preserving
the AGPL license, notices, and source/build information. Offline reuse verifies
the archive and repairs a modified extracted executable before returning it.

## Runtime APIs, profiles, and lifecycle

The provider type is `sparkrun`; each deployment carries its native APIs. The
recipe editor exposes runtime-family choices: vLLM offers Chat Completions,
Responses, and Anthropic Messages by default, including nightly/custom images;
recognized vLLM versions older than 0.12.0 default to Chat Completions only.
Recipes can narrow or override these defaults with
`metadata.native_apis: [chat_completions, responses, messages]`. Discovered jobs
resolve declarations from their saved recipe, and jobs sharing a model advertise
only their common APIs. Optional model capabilities remain permissive by default.

The same recipe declaration constrains sparkrun readiness. `readiness.inference_style`
can select `openai-chat-stream-v1`, `openai-responses-stream-v1`, or
`anthropic-messages-stream-v1` for vLLM; `auto` prefers Chat when declared.
Readiness checks one selected API, not every advertised API. The UI's deployment
API override affects SparkRoute routing only; configure recipe metadata and
readiness in recipe YAML to change launch behavior. After changing runtime
defaults, re-source `dev.sh` and run `sparkrun proxy sync` to refresh existing
deployments without reloading their workloads.

The recipe's `defaults.served_model_name`, then its Hugging Face model name,
initializes the public name. Advanced launch settings support ordered fallback
clusters. Fallback occurs on insufficient capacity before launch; uncertain
launches require reconciliation rather than starting another copy elsewhere.
The picker includes declared metadata facets, registry enable/add/remove/trust
controls, declared benchmark context, and explicit advisory capacity checks.
Unknown capacity is never presented as free capacity.

Under **Virtual Models / Aliases → Request profiles**, add `low` or `xhigh` and
API-specific JSON overrides. For Chat use `{"reasoning_effort":"xhigh"}`; for
Responses use `{"reasoning":{"effort":"xhigh"}}`. These are explicit public
virtual models sharing the original deployment. Parameters override caller
values before translation; request structure and routing fields are protected.

**Model Deployments → Model metadata** configures size (billions of parameters),
context length, token prices per million tokens, and tags. Model Routing inherits
these fields across each virtual model's targets. Recipe metadata supplies known
size and effective context limits; live discovery can report the actual runtime
context. Unknown values stay blank. Generated deployments remain read-only.

**PII Privacy** and **Guardrails**, after **Model Routing** in Configuration,
contain reusable policy profiles. Assign them from either profile page or the
**Policy profiles** selectors in **Virtual Models / Aliases**, then Validate and
Save. Assignments also work for sparkrun-generated models: they stay in operator
configuration and survive sparkrun refreshes or the model disappearing and
returning. Aliases and request-profile variants use the parent model's assigned
policies unless overridden. Editing a shared policy updates all its assignments.

Standalone PII request scope needs no persistent store; conversation scope uses
encrypted SQLite mappings and requires caller authentication plus
`X-SparkRoute-Thread-Id`. The default store lives beside the gateway configuration
in a `.pii` directory.

For ColdSnap recipes, idle policy can sleep instead of stop. Additional runtime
controls show Status/Sleep/Wake for receipt-backed jobs using an enabled ColdSnap
lifecycle API. Sleep/wake changes require SparkRoute ownership and no active
leases. A request to a sleeping owned workload wakes the same job. Installed,
enabled, recipe-required, and actually-used plugins are reported separately.
ColdSnap's `control_job` API checks the saved job ID, hosts, and capture receipt.
A lost sleep reply blocks cached admission until its state is verified.

To test sparkrun, coldsnap, and SparkRoute together using the public coldsnap
plugin repository:

```sh
export SPARKRUN_DEV_COLDSNAP=1
source dev.sh
```

This clones `https://github.com/sparksq/sparkrun-coldsnap-plugin.git` into
`.dev/sparkrun-coldsnap-plugin`, then includes it in the same in-tree development
host as SparkRoute. Each subsequent `source dev.sh` fetches the selected branch
again; `SPARKRUN_COLDSNAP_BRANCH` defaults to `main`. Setup reports the resolved
commit. The managed clone must be clean and retain its expected origin; a fetch
failure stops setup instead of silently using stale plugin code.

An explicit `SPARKRUN_COLDSNAP_CHECKOUT=/path/to/sparkrun-coldsnap-plugin` takes
precedence and uses that local source without fetching or switching it. The
resolved managed path is not exported as an override, so changing the branch on
a later setup takes effect. If `SPARKRUN_DEV_COLDSNAP` is unset, the existing
adjacent-checkout discovery remains available. Set `SPARKRUN_DEV_COLDSNAP=0` or
`SPARKRUN_COLDSNAP_CHECKOUT=none` to omit coldsnap, including any copy already
vendored in the selected host. These choices change only the disposable assembly.
The normal `plugins.coldsnap` feature flag still controls runtime loading; an
explicit feature override in your configuration or environment is respected.
SparkRoute's workload sleep/wake controls also require the selected coldsnap
checkout to expose its exact-job lifecycle API; the coldsnap CLI can be available
even when that API is absent.

After changing the assembly, restart an already-running proxy with
`sparkrun proxy start --restart` so its bridge subprocesses use the same plugin
set. Setup does not start, stop, sleep, or wake model workloads.

## Trace settings

**Configuration → Advanced Options** configures saved request/response traces
(filesystem or SQLite, path, body limit, queue, overflow policy) and OTLP/HTTP
operational traces (collector URL, service name, sampling, header environment
references). Validate then Save applies settings to new requests; older requests
drain with their original settings. “Use startup settings” follows the existing
CLI/environment configuration. Paths and header variables belong to the gateway
host. Disable does not delete existing trace files.

Saved trace export becomes available with payload capture enabled; refresh the
console after saving to update its navigation. Export
requires the separate `trace_read_all` role, granted to the default local
administrator, not ordinary config/status readers. Collector authentication
values stay in environment variables, outside saved configuration.


Recipes can also provide a top-level `sparkroute` block with deployment
`capabilities` and API-specific `request_profiles`. These defaults flow through
loaded/discovered workloads and the on-demand UI without changing workload
identity. See [recipe defaults](src/sparkrun/plugins/sparkroute/README.md#recipe-defaults)
for the YAML schema, examples, and ownership behavior.
