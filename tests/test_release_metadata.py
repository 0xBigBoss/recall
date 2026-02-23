from __future__ import annotations

import json
import tomllib
from pathlib import Path


def test_package_and_plugin_versions_are_in_sync() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    package_pyproject = repo_root / "packages" / "recall" / "pyproject.toml"
    plugin_manifest = repo_root / ".claude-plugin" / "plugin.json"

    package_data = tomllib.loads(package_pyproject.read_text(encoding="utf-8"))
    plugin_data = json.loads(plugin_manifest.read_text(encoding="utf-8"))

    package_version = package_data["project"]["version"]
    plugin_version = plugin_data["version"]

    assert plugin_version == package_version
