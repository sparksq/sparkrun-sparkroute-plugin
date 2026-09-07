# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
# Additional permission under AGPLv3 section 7: see src/sparkrun/plugins/sparkroute/LICENSE_EXCEPTION.

from pathlib import Path
import tomllib

import yaml

from sparkrun.plugins.sparkroute import __version__
from sparkrun.plugins.sparkroute.release import SPARKROUTE_VERSION


def test_versions_and_host_compatibility_match_the_catalog():
    root = Path(__file__).resolve().parents[1]
    catalog = yaml.safe_load((root / "versions.yaml").read_text())
    project = tomllib.loads((root / "pyproject.toml").read_text())
    manifest = tomllib.loads((root / "plugin.toml").read_text())
    assert str(catalog["sparkrun-sparkroute-plugin"]) == project["project"]["version"] == __version__
    assert str(catalog["sparkroute"]) == SPARKROUTE_VERSION
    assert project["project"]["dependencies"] == ["sparkrun" + manifest["sparkrun"]]
    assert "version" not in manifest
