<!--
SPDX-FileCopyrightText: 2026 Scitrera LLC
SPDX-FileCopyrightText: 2026 Fox Engine Ltd
SPDX-License-Identifier: AGPL-3.0-only
-->

# Publication and vendoring

This repository is the canonical source of the SparkRoute plugin. GitHub
releases contain a wheel and source distribution for inspection and vendoring.
There is no PyPI or npm publishing job. Publishing a plugin artifact does not
add it to a Sparkrun distribution: the host must vendor the snapshot, register
the `gateway.sparkroute` feature, and include the generic compatibility hooks.
Published Sparkrun 0.3.8 does not yet include this integration. See the
[development setup](../DEV_PREVIEW.md) for the tested assembly.

## Release checks

1. Update the plugin version through `versions.yaml` and
   `python scripts/update-versions.py`. When updating SparkRoute, verify its
   published archives and update both the gateway version and every supported
   platform's SHA-256 in `src/sparkrun/plugins/sparkroute/release.py`.
   `compat/gateway.toml` must identify the source tested with the plugin.
2. Run the Python suite in the assembled host and the native control matrix.
   The latter exercises a real gateway and bridge on Linux, macOS, and Windows,
   each on amd64 and arm64. Tests do not start GPU workloads.
3. Check the source and history, then build and inspect the actual artifacts:

   ```sh
   uvx --from reuse==6.2.0 reuse lint
   gitleaks git --redact --log-opts=--all .
   uv build --no-sources
   uvx --from twine==6.2.0 twine check --strict dist/*
   python scripts/check-distributions.py dist
   ```

   Use Gitleaks 8.30.1 or later. Investigate findings before adding narrowly
   scoped exceptions. Keep reports, credentials, development assemblies, and
   planning notes outside the tracked tree and distribution manifests.
4. Run the **Release** workflow manually on the proposed commit. It checks
   licensing, versions, distributions, Python tests, and native controls;
   manual runs do not publish. Verify all jobs before creating a matching
   `v<plugin version>` tag. A tag reruns the checks and publishes only after
   they all pass.

## License material

The plugin is AGPL-3.0-only with the existing sparkrun combination permission
in `LICENSE_EXCEPTION`. Preserve both texts when vendoring the package; they
are duplicated inside the package so a source-only vendor operation carries
them. Repository tooling and host patches retain their BSD-3-Clause and
Apache-2.0 licenses, respectively. `NOTICE`, `REUSE.toml`, and `LICENSES/`
identify those exceptions. Dependencies and the separately downloaded gateway
retain their own notices.
