"""IDE config registration used by both installers."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from vibetter.ide import IdeConfigError, main, register, remove_v1

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


def test_regression_rerun_keeps_the_entry_env_but_never_a_key(tmp_path: Path):
    # Re-running the installer replaced the entry, so the VIBETTER_CODEBASE_PATH that
    # Claude Desktop needs was deleted on every update.
    path = tmp_path / "claude_desktop_config.json"
    env = {"VIBETTER_CODEBASE_PATH": "/home/dev/app", "OPENAI_API_KEY": "sk-test-not-real"}
    path.write_text(json.dumps({"mcpServers": {"vibetter": {"command": "uvx", "env": env}}}))
    register(path, COMMAND)
    entry = json.loads(path.read_text())["mcpServers"]["vibetter"]
    assert entry == {"command": COMMAND, "env": {"VIBETTER_CODEBASE_PATH": "/home/dev/app"}}


V1_ENTRY = {
    "command": "/home/dev/.vibetter/venv/bin/python",
    "args": ["-u", "/home/dev/.vibetter/backend/src/server.py"],
    "env": {"VIBETTER_PROVIDER": "gemini", "GEMINI_API_KEY": "AIza-test-not-real"},
}


def test_v1_entry_is_replaced_whole(tmp_path: Path):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"vibetter": V1_ENTRY}}))
    register(path, COMMAND)
    assert json.loads(path.read_text())["mcpServers"]["vibetter"] == {"command": COMMAND}


def test_regression_v1_vscode_entry_is_removed(tmp_path: Path):
    # v1 wrote the key into ~/.vscode/mcp.json, and v2 never touched that file.
    path = tmp_path / "mcp.json"
    other = {"command": "gh-mcp"}
    path.write_text(json.dumps({"mcpServers": {"vibetter": V1_ENTRY, "github": other}}))
    assert remove_v1(path) is True
    assert json.loads(path.read_text()) == {"mcpServers": {"github": other}}
    assert "AIza-test" not in path.read_text()
    assert remove_v1(path) is False
    assert remove_v1(tmp_path / "missing.json") is False


def test_regression_symlinked_config_is_written_through_the_link(tmp_path: Path):
    real = tmp_path / "dotfiles" / "mcp_config.json"
    real.parent.mkdir()
    real.write_text("{}")
    link = tmp_path / "windsurf" / "mcp_config.json"
    link.parent.mkdir()
    link.symlink_to(real)
    register(link, COMMAND)
    assert link.is_symlink()
    assert json.loads(real.read_text())["mcpServers"]["vibetter"]["command"] == COMMAND


def test_regression_first_backup_kept_and_text_preserved(tmp_path: Path):
    path = tmp_path / "mcp.json"
    original = '﻿{"name": "café", "mcpServers": {}}'
    path.write_text(original, encoding="utf-8")
    register(path, COMMAND)
    register(path, "/other/vibetter")
    assert (tmp_path / "mcp.json.vibetter.bak").read_text(encoding="utf-8") == original
    assert '"café"' in path.read_text(encoding="utf-8")


def test_desktop_without_a_codebase_path_exits_3(tmp_path: Path):
    path = tmp_path / "claude_desktop_config.json"
    assert main(["--desktop", str(path), COMMAND]) == 3
    entry = {"command": COMMAND, "env": {"VIBETTER_CODEBASE_PATH": "/home/dev/app"}}
    path.write_text(json.dumps({"mcpServers": {"vibetter": entry}}))
    assert main(["--desktop", str(path), COMMAND]) == 0
    assert main([str(tmp_path / "cursor.json"), COMMAND]) == 0
