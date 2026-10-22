"""IDE config registration used by both installers."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from vibetter.ide import IdeConfigError, register

COMMAND = "/home/dev/.vibetter/venv/bin/vibetter"


def test_creates_new_config(tmp_path: Path):
    path = tmp_path / "Cursor" / "mcp.json"
    register(path, COMMAND)
    assert json.loads(path.read_text()) == {"mcpServers": {"vibetter": {"command": COMMAND}}}


def test_keeps_other_servers_and_writes_backup(tmp_path: Path):
    path = tmp_path / "mcp.json"
    original = {"theme": "dark", "mcpServers": {"github": {"command": "gh-mcp"}}}
    path.write_text(json.dumps(original))
    register(path, COMMAND)
    data = json.loads(path.read_text())
    assert data["theme"] == "dark"
    assert data["mcpServers"]["github"] == {"command": "gh-mcp"}
    assert data["mcpServers"]["vibetter"]["command"] == COMMAND
    assert json.loads((tmp_path / "mcp.json.vibetter.bak").read_text()) == original


def test_regression_unparseable_config_is_not_overwritten(tmp_path: Path):
    path = tmp_path / "mcp.json"
    jsonc = '{\n  // my servers\n  "mcpServers": {"github": {"command": "gh-mcp"},},\n}\n'
    path.write_text(jsonc)
    with pytest.raises(IdeConfigError, match="could not parse"):
        register(path, COMMAND)
    assert path.read_text() == jsonc
    assert (tmp_path / "mcp.json.vibetter.bak").read_text() == jsonc


def test_regression_config_holds_no_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-should-not-be-copied")
    path = tmp_path / "mcp.json"
    register(path, COMMAND)
    assert "sk-test" not in path.read_text()
    assert "env" not in json.loads(path.read_text())["mcpServers"]["vibetter"]


def test_module_entry_point_reports_refusal(tmp_path: Path):
    path = tmp_path / "mcp.json"
    path.write_text("{ not json")
    out = subprocess.run(
        [sys.executable, "-m", "vibetter.ide", str(path), COMMAND], capture_output=True, text=True
    )
    assert out.returncode == 2
    assert "could not parse" in out.stderr
    assert path.read_text() == "{ not json"
