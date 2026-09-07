# Local development preview

Build SparkRoute from its standalone OSS tree, then supply the explicit local
binary override. This development path intentionally bypasses release archive
verification and emits a warning whenever the binary is resolved.

```sh
cd /path/to/sparkroute-internal/oss
GOWORK=off go build -o /path/to/sparkroute-dev ./cmd/sparkroute

cd /path/to/sparkrun-sparkroute-plugin
export SPARKRUN_CHECKOUT=/path/to/compatible/sparkrun
source dev.sh
export SPARKRUN_SPARKROUTE_BINARY=/path/to/sparkroute-dev
sparkrun setup features enable gateway.sparkroute
sparkrun proxy start --gateway sparkroute --host 127.0.0.1
sparkrun proxy ui
```

Use a separate SparkRun configuration/cache for development so proxy state,
credentials, bindings, and workloads are independent of a production setup.
The test suite redirects these paths and disables external plugin loading and
registry fetching.

`proxy ui` reports the console URL. `proxy admin-token get`, `set`, and `clear`
manage the live admin credential according to the gateway's token-file mode.
An absent admin token permits local administration. Configure exposure and
credentials deliberately before using a nonloopback listener.

The public binary acquisition path remains unavailable until the first release
archives and their SHA-256 digests have been pinned. There is no unverified
download fallback. Disabling the plugin still permits SparkRun's generic
process supervisor to stop a recorded gateway; plugin-specific management
requires the integration to remain enabled.
