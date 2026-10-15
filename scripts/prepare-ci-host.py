#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only

"""Check out the commit-pinned sparkrun host for CI.

CI runs against this stock host with the plugin installed beside it, the way
users get it. The dev.sh assembly puts SparkRoute in-tree instead, where the
host refuses the managed install the gateway integration tests depend on.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    pin = tomllib.loads((ROOT / "compat/host.toml").read_text())
    checkout = ROOT / ".dev/ci-sparkrun"
    if checkout.exists():
        raise SystemExit("CI host already exists; use a fresh checkout")
    checkout.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--quiet", str(checkout)], check=True)
    subprocess.run(["git", "-C", str(checkout), "fetch", "--depth=1", pin["repository"], pin["commit"]], check=True)
    subprocess.run(["git", "-C", str(checkout), "-c", "core.autocrlf=false", "checkout", "--detach", "FETCH_HEAD"], check=True)
    actual = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    if actual != pin["commit"]:
        raise SystemExit("CI host commit differs from the configured pin")


if __name__ == "__main__":
    main()
