#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
"""Build the pinned OSS gateway for native integration checks, without GPUs."""
from __future__ import annotations

import argparse
import os
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='use an existing checkout of the exact pinned commit')
    parser.add_argument('--go', default='go')
    args = parser.parse_args()
    pin = tomllib.loads((ROOT / 'compat/gateway.toml').read_text())
    checkout = args.source.resolve() if args.source else ROOT / '.dev/ci-gateway'
    if not args.source:
        if checkout.exists():
            raise SystemExit('CI gateway already exists; use a fresh checkout')
        checkout.parent.mkdir(parents=True, exist_ok=True)
        for command in (
            ['init', '--quiet'], ['fetch', '--depth=1', pin['repository'], pin['commit']],
            ['-c', 'core.autocrlf=false', 'checkout', '--detach', 'FETCH_HEAD'],
        ):
            if command[0] == 'init':
                checkout.mkdir()
            subprocess.run(['git', '-C', str(checkout), *command], check=True)
    actual = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != pin['commit']:
        raise SystemExit('Gateway source differs from compat/gateway.toml')
    if subprocess.check_output(['git', '-C', str(checkout), 'status', '--porcelain', '--untracked-files=no'], text=True).strip():
        raise SystemExit('Gateway source has uncommitted changes')
    binary = ROOT / '.dev' / ('sparkroute-native.exe' if os.name == 'nt' else 'sparkroute-native')
    subprocess.run(
        [args.go, 'build', '-mod=readonly', '-o', str(binary), './cmd/sparkroute'], cwd=checkout,
        env={**os.environ, 'GOWORK': 'off', 'CGO_ENABLED': '0'}, check=True,
    )
    if os.environ.get('GITHUB_ENV'):
        with open(os.environ['GITHUB_ENV'], 'a', encoding='utf-8') as output:
            output.write('SPARKROUTE_TEST_BINARY=' + str(binary) + '\n')
    print('SPARKROUTE_TEST_BINARY=' + str(binary))


if __name__ == '__main__':
    main()
