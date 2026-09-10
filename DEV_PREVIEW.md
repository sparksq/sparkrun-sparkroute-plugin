<!--
SPDX-FileCopyrightText: 2026 Scitrera LLC
SPDX-FileCopyrightText: 2026 Fox Engine Ltd
SPDX-License-Identifier: AGPL-3.0-only
-->

# Development setup

`source dev.sh` now prepares both SparkRun and a usable SparkRoute binary:

```sh
export SPARKRUN_CHECKOUT=/path/to/compatible/sparkrun
source dev.sh
sparkrun setup features enable gateway.sparkroute
sparkrun proxy start --gateway sparkroute --host 127.0.0.1
sparkrun proxy ui
```

SparkRoute source and release assets are public. Development setup uses `gh`
for release and Actions discovery; authenticate it with `gh auth login` for that
path. Source builds can use public Git access. No deploy key is required, and
credentials are not forwarded into Docker. Production release acquisition uses
the pinned public archives directly and does not require `gh`.

The development binary is paired to `compat/gateway.toml`. Setup tries:

1. The cached binary in `.dev/gateway/<commit>/<os>-<arch>`, checking its receipt,
   SHA-256, and reported build identity. Changing the source pin selects a new
   cache; repeated setup revalidates the exported managed binary.
2. GitHub release assets whose tag resolves to that commit, then
   `sparkroute-distributions` artifacts from successful `publish-go.yml` runs
   for that commit. Both require a matching archive checksum and build identity
   before the binary is used. Older commits are not substituted.
3. A build of the pinned source using `golang:<go.mod version>-bookworm` in
   Docker, with local Go as a fallback if Docker is unavailable or fails.
   Linux containers cross-compile for Linux, macOS, or Windows on amd64/arm64;
   macOS/Windows Docker installations must support Linux containers.

A source build first checks `.dev/sparkroute-public` and the sibling
`../sparkroute` Git repository for the commit; otherwise it fetches that commit
using GitHub CLI credentials, falling back to normal Git credentials. It
exports only committed files into a temporary tree, leaving existing checkouts
and their local changes untouched. The committed UI assets are included.
Network access is required when no local Git copy contains the pin.
Go modules and build results are cached
under `.dev/go-cache`; the first build can take several minutes.

Development controls:

| Variable | Effect |
| --- | --- |
| `SPARKRUN_SPARKROUTE_BINARY` | Use an explicit executable; skips automatic preparation. Set before sourcing. |
| `SPARKROUTE_CHECKOUT` | Use Git objects from this local repository when a source build is needed. It must contain the pinned commit; uncommitted changes are excluded. |
| `SPARKROUTE_DEV_BUILDER` | `auto` (default), `docker`, or `go`. Explicit builders skip GitHub binary lookup when building. |
| `SPARKROUTE_DEV_GO` | Local Go executable name or absolute path. |

To force a rebuild with a particular builder, ignoring the prepared cache:

```sh
python scripts/prepare-dev-gateway.py --force --builder docker
```

To work on uncommitted SparkRoute changes, build your working tree yourself and
set the explicit binary before sourcing the development environment:

```sh
(cd /path/to/sparkroute && GOWORK=off go build -o /path/to/sparkroute-dev ./cmd/sparkroute)
export SPARKRUN_SPARKROUTE_BINARY=/path/to/sparkroute-dev
source dev.sh
```

Automatic preparation verifies development provenance using your trusted Git
objects or authenticated GitHub access. It exports the existing development
override, which emits a runtime warning because it bypasses production release
pins. Production acquisition verifies the published v0.0.2 archive digests;
installing the package alone does not trigger downloads or development builds.

Use a separate SparkRun configuration/cache for development so proxy state,
credentials, bindings, and workloads are independent of a production setup.
The test suite redirects these paths and disables external plugin loading and
registry fetching.

SparkRoute v0.0.2 adds opt-in automatic recovery in the recipe deployment editor.
Plugin v0.1.1 pins that release and its matching source, so normal development
setup includes recovery. Clear any explicit binary override before sourcing
`dev.sh` to select the pinned build. Recovery uses bridge schema v4 and does not
require a new bridge operation.

`proxy ui` reports the console URL. `proxy admin-token get`, `set`, and `clear`
manage the live admin credential according to the gateway's token-file mode.
An absent admin token permits local administration. Configure exposure and
credentials deliberately before using a nonloopback listener.
