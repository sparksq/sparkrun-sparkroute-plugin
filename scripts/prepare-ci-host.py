#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only

"""Prepare a commit-pinned host for the integration's source-development CI."""

from __future__ import annotations

import subprocess
import sys
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
    subprocess.run(["git", "-C", str(checkout), "checkout", "--detach", "FETCH_HEAD"], check=True)
    actual = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    if actual != pin["commit"]:
        raise SystemExit("CI host commit differs from the configured pin")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/assemble-dev-host.py"), "--host", str(checkout),
         "--destination", str(ROOT / ".dev/sparkrun-with-sparkroute")],
        check=True,
    )


if __name__ == "__main__":
    main()
