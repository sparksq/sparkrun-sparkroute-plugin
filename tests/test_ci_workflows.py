# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
# Additional permission under AGPLv3 section 7: see src/sparkrun/plugins/sparkroute/LICENSE_EXCEPTION.

from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _workflow(name: str) -> dict:
    # BaseLoader preserves GitHub's YAML 1.2 `on` key instead of treating it as
    # the YAML 1.1 boolean True. The assertions below use its string scalars.
    return yaml.load((WORKFLOWS / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_repo_tools_shims_and_generated_workflows_use_the_catalog_pin():
    catalog = yaml.safe_load((ROOT / "versions.yaml").read_text(encoding="utf-8"))
    source = catalog["ci"]["repo_tools_source"]
    assert len(source.rsplit("@", 1)[1]) == 40
    for name in ("update-versions.py", "generate-ci-gha.py"):
        module = ast.parse((ROOT / "scripts" / name).read_text(encoding="utf-8"))
        pin = next(
            ast.literal_eval(node.value)
            for node in module.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "DEFAULT_SOURCE" for target in node.targets)
        )
        assert pin == source
    assert source in (WORKFLOWS / "version-check.yml").read_text(encoding="utf-8")


def test_sdist_manifest_includes_the_support_files_needed_to_run_its_tests():
    manifest = set((ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines())
    assert {
        "include .gitattributes",
        "include DEV_PREVIEW.md",
        "recursive-include scripts *.py",
        "recursive-include tests *.py",
        "recursive-include .github/workflows *.yml",
    } <= manifest


def test_release_reuses_the_complete_test_matrix_and_limits_write_access():
    workflow = _workflow("test-python.yml")
    assert "workflow_call" in workflow["on"]
    assert workflow["on"]["push"]["branches"] == ["main"]
    assert workflow["on"]["pull_request"]["branches"] == ["main"]
    job = workflow["jobs"]["test-sparkrun-sparkroute-plugin"]
    assert job["strategy"]["matrix"]["python-version"] == ["3.12", "3.13"]
    commands = [step.get("run", "").strip() for step in job["steps"]]
    assert "python -m pytest -v" in commands
    assert "python scripts/update-versions.py --check" in commands
    assert "python scripts/generate-ci-gha.py --check" in commands

    release = _workflow("release.yml")
    assert release["on"] == {"push": {"tags": ["v*.*.*"]}}
    assert release["permissions"] == {"contents": "read"}
    assert release["jobs"]["tests"]["uses"] == "./.github/workflows/test-python.yml"
    publish = release["jobs"]["github-release"]
    assert set(publish["needs"]) == {"tests", "controls", "build"}
    assert publish["if"] == "github.ref_type == 'tag' && github.repository == 'sparksq/sparkrun-sparkroute-plugin'"
    assert publish["permissions"] == {"contents": "write"}
    assert "permissions" not in release["jobs"]["build"]
    assert "publish-python.yml" not in {path.name for path in WORKFLOWS.glob("*.yml")}
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert "pypa/gh-action-pypi-publish" not in text
    assert "id-token:" not in text
    assert release["jobs"]["controls"]["secrets"] == {
        "SPARKROUTE_CI_SSH_KEY": "${{ secrets.SPARKROUTE_CI_SSH_KEY }}",
    }
    assert all("secrets" not in job for name, job in release["jobs"].items() if name != "controls")


@pytest.mark.parametrize("tag", ["v0.1.1", "v0.1.0", "v0.3.20", "0.1.1", "v0.1.1-extra"])
def test_release_tag_gate_rejects_mismatched_versions(tmp_path: Path, tag: str):
    workflow = _workflow("release.yml")
    script = next(step["run"] for step in workflow["jobs"]["build"]["steps"] if step.get("name") == "Compare tag against versions.yaml")
    # Execute the actual workflow's shell gate, without fetching repo-tools.
    # The fake version command has no side effects and verifies its arguments.
    fake_python = tmp_path / "python"
    fake_python.write_text(
        '#!/bin/sh\n[ "$*" = "scripts/update-versions.py --print-version sparkrun-sparkroute-plugin" ] || exit 2\n'
        "printf '%s\\n' '0.1.1'\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", script],
        env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"], "GITHUB_REF_NAME": tag},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) == (tag == "v0.1.1"), result.stdout + result.stderr


def test_native_controls_cover_every_release_platform_and_gate_publication():
    native = _workflow("native-controls.yml")
    assert set(native["jobs"]["control"]["strategy"]["matrix"]["runner"]) == {
        "ubuntu-24.04",
        "ubuntu-24.04-arm",
        "macos-15-intel",
        "macos-15",
        "windows-2025",
        "windows-11-arm",
    }
    release = _workflow("release.yml")
    assert release["jobs"]["controls"]["uses"] == "./.github/workflows/native-controls.yml"
    commands = "\n".join(step.get("run", "") for step in native["jobs"]["control"]["steps"])
    assert "scripts/prepare-ci-host.py" in commands
    assert "scripts/prepare-ci-gateway.py" in commands
    assert "tests/test_sparkroute_live.py" in commands


def test_private_gateway_checkout_uses_scoped_credentials_and_the_catalog_pin():
    workflow = _workflow("native-controls.yml")
    assert set(workflow["on"]["workflow_call"]["secrets"]) == {"SPARKROUTE_CI_SSH_KEY"}
    assert workflow["on"]["workflow_call"]["secrets"]["SPARKROUTE_CI_SSH_KEY"]["required"] == "false"
    steps = workflow["jobs"]["control"]["steps"]
    checkout = next(step for step in steps if step.get("with", {}).get("path") == ".dev/ci-gateway")
    assert checkout["with"]["repository"] == "${{ steps.gateway.outputs.repository }}"
    assert checkout["with"]["ref"] == "${{ steps.gateway.outputs.commit }}"
    assert checkout["with"]["ssh-key"] == "${{ secrets.SPARKROUTE_CI_SSH_KEY }}"
    assert checkout["with"]["persist-credentials"] == "false"
    commands = [step.get("run", "") for step in steps]
    assert "python scripts/prepare-ci-gateway.py --source .dev/ci-gateway" in commands
    assert any("compat/gateway.toml" in command for command in commands)
