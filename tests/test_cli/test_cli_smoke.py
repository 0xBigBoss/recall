from __future__ import annotations

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from recall.cli.app import app


def test_cli_smoke(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("RECALL_DATA_DIR", str(tmp_path / ".local/share/recall"))

    claude_target = tmp_path / ".claude" / "projects" / "proj1"
    codex_target = tmp_path / ".codex" / "sessions" / "s1"
    claude_target.mkdir(parents=True)
    codex_target.mkdir(parents=True)

    claude_fixture = (
        Path(__file__).resolve().parents[2] / "fixtures" / "claude_code" / "session1.jsonl"
    )
    codex_fixture = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "codex"
        / "session1"
        / "rollout.jsonl"
    )

    shutil.copy(claude_fixture, claude_target / "session1.jsonl")
    shutil.copy(codex_fixture, codex_target / "rollout.jsonl")

    runner = CliRunner()
    result = runner.invoke(app, ["index", "--full", "--recreate"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["list", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert payload
