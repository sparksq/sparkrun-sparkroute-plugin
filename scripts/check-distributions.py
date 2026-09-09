#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only

"""Check built artifacts for complete source, preserved notices, and extra files."""

from __future__ import annotations

import argparse
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
import tarfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "sparkrun/plugins/sparkroute/"
LEGAL = ("LICENSE", "LICENSE_EXCEPTION", "NOTICE", "LICENSES/AGPL-3.0-only.txt", "LICENSES/Apache-2.0.txt", "LICENSES/BSD-3-Clause.txt")
ROOT_FILES = {
    ".pre-commit-config.yaml",
    ".gitattributes",
    ".gitleaksignore",
    "DEV_PREVIEW.md",
    "dev.sh",
    "plugin.toml",
    "versions.yaml",
    "REUSE.toml",
    "README.md",
    "pyproject.toml",
    "MANIFEST.in",
}
SOURCE_PATTERNS = ("scripts/*.py", "tests/*.py", ".github/workflows/*.yml", "compat/*.patch", "compat/*.toml")
DOCS = {"docs/SPARKROUTE_BRIDGE.md", "docs/RELEASING.md"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def check_metadata(data: bytes) -> None:
    metadata = BytesParser().parsebytes(data)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    require(metadata["Name"] == project["name"], "distribution name mismatch")
    require(metadata["Version"] == project["version"], "distribution version mismatch")
    require(metadata["License-Expression"] == "AGPL-3.0-only", "missing license expression")
    require(set(metadata.get_all("License-File", [])) == set(LEGAL), "incomplete license-file metadata")


def check_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "duplicate wheel members")
        roots = {name.split("/")[0] for name in names if name.split("/")[0].endswith(".dist-info")}
        require(len(roots) == 1, "wheel must have one metadata directory")
        info = next(iter(roots)) + "/"
        package = ROOT / "src" / PACKAGE
        paths = list(package.glob("*.py")) + [package / name for name in ("LICENSE", "LICENSE_EXCEPTION", "README.md")]
        source = {PACKAGE + p.name: p for p in paths}
        legal = {info + "licenses/" + name: ROOT / name for name in LEGAL}
        expected = set(source) | set(legal) | {info + name for name in ("METADATA", "WHEEL", "top_level.txt", "RECORD")}
        require(set(names) == expected, f"unexpected or missing wheel files: {set(names) ^ expected}")
        for name, original in (source | legal).items():
            require(archive.read(name) == original.read_bytes(), f"wheel content differs: {name}")
        check_metadata(archive.read(info + "METADATA"))
    print(f"PASS {path.name}: runtime package and all license notices verified")


def check_sdist(path: Path) -> None:
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        roots = {PurePosixPath(member.name).parts[0] for member in members}
        require(len(roots) == 1, "sdist must have one root directory")
        prefix = next(iter(roots)) + "/"
        files = {}
        for member in members:
            require(member.isdir() or member.isfile(), f"non-regular sdist member: {member.name}")
            require(".." not in PurePosixPath(member.name).parts and not member.name.startswith("/"), "unsafe sdist path")
            if member.isfile():
                name = member.name.removeprefix(prefix)
                require(name not in files, f"duplicate sdist member: {name}")
                files[name] = member
        expected = ROOT_FILES | DOCS | set(LEGAL)
        for pattern in SOURCE_PATTERNS:
            expected |= {p.relative_to(ROOT).as_posix() for p in ROOT.glob(pattern)}
        expected |= {p.relative_to(ROOT).as_posix() for p in (ROOT / "src" / PACKAGE).glob("*.py")}
        expected |= {"src/" + PACKAGE + name for name in ("LICENSE", "LICENSE_EXCEPTION", "README.md")}
        generated = {"PKG-INFO", "setup.cfg"} | {
            "src/sparkrun_sparkroute_plugin.egg-info/" + name
            for name in ("PKG-INFO", "SOURCES.txt", "dependency_links.txt", "requires.txt", "top_level.txt")
        }
        require(set(files) == expected | generated, f"unexpected or missing sdist files: {set(files) ^ (expected | generated)}")
        for name in expected:
            require(archive.extractfile(files[name]).read() == (ROOT / name).read_bytes(), f"sdist content differs: {name}")
        check_metadata(archive.extractfile(files["PKG-INFO"]).read())
    print(f"PASS {path.name}: complete source, notices, and public documentation verified")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    wheels = list(args.directory.glob("*.whl"))
    sdists = list(args.directory.glob("*.tar.gz"))
    require(len(wheels) == len(sdists) == 1, "expected exactly one wheel and one sdist")
    check_wheel(wheels[0])
    check_sdist(sdists[0])


if __name__ == "__main__":
    main()
