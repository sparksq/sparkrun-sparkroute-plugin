<!--
SPDX-FileCopyrightText: 2026 Scitrera LLC
SPDX-FileCopyrightText: 2026 Fox Engine Ltd
SPDX-License-Identifier: AGPL-3.0-only
-->

# SparkRoute plugin for sparkrun

This is the independent development home of sparkrun's SparkRoute integration.
sparkrun distributions vendor an immutable source snapshot as
`sparkrun.plugins.sparkroute`. Building or installing sparkrun does not clone
this repository or acquire a gateway binary.

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

The initial extraction is a source-development preview. The default gateway
version is recorded in `versions.yaml`, but verified public release archive
digests must be added before normal binary acquisition can succeed. `dev.sh`
prepares a separate development binary, including while the repository is
private. See [DEV_PREVIEW.md](DEV_PREVIEW.md) for acquisition and build controls.

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
Go checkout; it is separate from the eventual verified release archive pins.

## Configuration ownership

sparkrun's `proxy.yaml` bindings project into the gateway's `sparkrun` managed
configuration set. The `operator` set remains independently editable through
the SparkRoute console. Reconciliation replaces only the sparkrun set under
revision checks and applies without a gateway restart. The console presents both
sets in the same lists, with generated entries grayed out and read-only.

Generated deployments have display titles such as `sparkrun:spark-a:Qwen3-8B`,
while their existing hashed `name` IDs remain unchanged. Recipe bindings use their
observed named clusters, matched by launch recipe fingerprint, then configured
cluster candidates (or `unassigned`). Discovery uses healthy endpoint cluster IDs
to look up named clusters locally, falling back to the cluster ID or `discovered`.
Multiple clusters are comma-separated. An optional local display cache preserves
discovery labels across CLI invocations; it never controls routing or workload
identity. Existing discovery snapshots get cluster labels on the next sync.

The durable bindings remain present while their models are offline. The
separate discovery snapshot supplies routes for already-running workloads.
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

The default cold-start wait is 15 minutes; client timeouts may need to be longer
than a model's first download/load. Idle shutdown is off by default (30 minutes
is suggested when enabled). Aliases share one deployment and its lifecycle
policy. Idle time begins after the last request finishes, including streams.
Workloads launched by someone else can be adopted but are never stopped by
SparkRoute's idle policy. The Runtime page shows launch phase, cluster, job,
and ownership.

Registry search is cache-only; **Refresh registries** is explicit and reports
partial failures. Local paths belong to the control node. Uploads do not grant
trust or include referenced auxiliary files. Validation and activation check
pinned recipe contents; changed recipes require a fresh preview. Unknown API
model names never trigger an inferred registry search or launch.

This flow requires the catalog API in the sparkrun core commit pinned in
`compat/host.toml`. The bridge uses strict schema v3; update the plugin and
pinned SparkRoute binary together. Named cluster metadata controls placement
and adoption. Older job records without it remain unknown; overlapping host
sets are not used to guess a cluster. See [the bridge contract](docs/SPARKROUTE_BRIDGE.md)
for durable launch recovery. Request profiles and ColdSnap sleep/wake remain
subsequent work.

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
