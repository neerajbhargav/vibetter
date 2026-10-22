"""MCP tool surface, exercised through the in-memory fastmcp Client."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from conftest import (
    CALC_PY,
    FakeLLM,
    call_tool,
    git,
    read_resource,
    text_of,
    wait_until,
    write,
)

from vibetter.server import Vibetter, build_mcp, create_server

GRAPH = {
    "nodes": [{"id": "1", "position": {"x": 0, "y": 0}, "data": {"label": "calc.py"}}],
    "edges": [],
}


def test_lists_five_tools_and_blueprint_resource(repo: Path, llm: FakeLLM):
    import asyncio

    from fastmcp import Client

    async def go():
        async with Client(create_server(repo, llm)) as client:
            tools = {t.name for t in await client.list_tools()}
            resources = {str(r.uri) for r in await client.list_resources()}
            return tools, resources

    tools, resources = asyncio.run(go())
    assert tools == {
        "scholar_explain",
        "generate_blueprint",
        "generate_audio_overview",
        "explain_last_change",
        "debug_error_in_context",
    }
    assert "ui://blueprint" in resources


def test_scholar_explain_sends_target_file_and_question(repo: Path, llm: FakeLLM):
    result = call_tool(
        create_server(repo, llm),
        "scholar_explain",
        {"file_path": "src/calc.py", "question": "Why check b?"},
    )
    assert not result.is_error
    assert text_of(result) == "fake answer"
    assert "TARGET FILE: src/calc.py" in llm.last
    assert "Why check b?" in llm.last


def test_regression_dot_slash_target_path_found(repo: Path, llm: FakeLLM):
    result = call_tool(
        create_server(repo, llm), "scholar_explain", {"file_path": "./src/calc.py", "question": "q"}
    )
    assert not result.is_error
    assert "TARGET FILE: src/calc.py" in llm.last


def test_regression_missing_target_is_tool_error(repo: Path, llm: FakeLLM):
    result = call_tool(
        create_server(repo, llm), "scholar_explain", {"file_path": "src/calcc.py", "question": "q"}
    )
    assert result.is_error
    assert "not found" in text_of(result).lower()
    assert "src/calc.py" in text_of(result)  # suggests the close match
    assert llm.prompts == []


def test_regression_context_has_line_numbers(repo: Path, llm: FakeLLM):
    call_tool(
        create_server(repo, llm), "scholar_explain", {"file_path": "src/calc.py", "question": "q"}
    )
    assert re.search(r"^\s*1\| def add\(a, b\):$", llm.last, re.MULTILINE)
    assert re.search(r"^\s*7\|         raise ZeroDivisionError", llm.last, re.MULTILINE)


def test_regression_secrets_redacted_in_prompt(repo: Path, llm: FakeLLM):
    call_tool(
        create_server(repo, llm),
        "scholar_explain",
        {"file_path": "app/settings.py", "question": "q"},
    )
    assert "AKIAABCDEFGHIJKLMNOP" not in llm.last
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in llm.last
    assert "[REDACTED" in llm.last
    assert "TIMEOUT = 30" in llm.last


def test_regression_secret_files_never_sent(repo: Path, llm: FakeLLM):
    call_tool(create_server(repo, llm), "generate_blueprint")
    for leaked in ("sk-test-not-a-real-key", "hunter2hunter2", "BEGIN PRIVATE KEY"):
        assert leaked not in llm.last


def test_regression_blueprint_context_skips_lockfile(repo: Path):
    llm = FakeLLM(json.dumps(GRAPH))
    call_tool(create_server(repo, llm), "generate_blueprint")
    for source in ("src/calc.py", "src/util.py", "app/main.py"):
        assert f"FILE: {source}" in llm.last
    for noise in (
        "package-lock.json",
        "web/app.min.js",
        "web/bundle.js",
        "node_modules/dep/index.js",
        "big.txt",
        "data.bin",
        "ignored.txt",
    ):
        assert f"FILE: {noise}" not in llm.last


def test_regression_blueprint_parse_failure_is_tool_error(repo: Path):
    result = call_tool(create_server(repo, FakeLLM("this is not json")), "generate_blueprint")
    assert result.is_error
    assert "json" in text_of(result).lower()


def test_blueprint_resource_injects_cached_graph(repo: Path):
    server = create_server(repo, FakeLLM("```json\n" + json.dumps(GRAPH) + "\n```"))
    result = call_tool(server, "generate_blueprint")
    assert not result.is_error
    html = read_resource(server, "ui://blueprint")
    assert "window.__VIBETTER_BLUEPRINT__ = " in html
    assert '"label": "calc.py"' in html
    assert 'src="/assets/' not in html  # assets are inlined


def test_regression_provider_failure_is_tool_error(repo: Path, monkeypatch: pytest.MonkeyPatch):
    # No llm injected: the real provider layer runs and fails before any network call.
    monkeypatch.setenv("VIBETTER_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = call_tool(
        create_server(repo), "scholar_explain", {"file_path": "src/calc.py", "question": "q"}
    )
    assert result.is_error
    assert "ANTHROPIC_API_KEY" in text_of(result)


def test_debug_error_includes_error_and_file(repo: Path, llm: FakeLLM):
    result = call_tool(
        create_server(repo, llm),
        "debug_error_in_context",
        {"error_message": "ZeroDivisionError: b must not be zero", "file_path": "src/calc.py"},
    )
    assert not result.is_error
    assert "ZeroDivisionError: b must not be zero" in llm.last
    assert "TARGET FILE: src/calc.py" in llm.last


def test_audio_overview_writes_mp3(repo: Path, llm: FakeLLM, monkeypatch: pytest.MonkeyPatch):
    import gtts

    class FakeTTS:
        def __init__(self, text: str, **kwargs):
            self.text = text

        def save(self, path: str) -> None:
            Path(path).write_bytes(b"ID3fake")

    monkeypatch.setattr(gtts, "gTTS", FakeTTS)
    result = call_tool(
        create_server(repo, llm), "generate_audio_overview", {"question": "How does divide work?"}
    )
    assert not result.is_error
    match = re.search(r"Audio saved to: (\S+\.mp3)", text_of(result))
    assert match and Path(match.group(1)).read_bytes() == b"ID3fake"


# --- explain_last_change ------------------------------------------------------


def test_regression_untracked_file_in_last_change(repo: Path, llm: FakeLLM):
    write(repo, "src/new_feature.py", "def shiny():\n    return 42\n")
    result = call_tool(create_server(repo, llm), "explain_last_change")
    assert not result.is_error
    assert "src/new_feature.py" in llm.last
    assert "+    return 42" in llm.last


def test_regression_root_commit_is_explained(repo: Path, llm: FakeLLM):
    result = call_tool(create_server(repo, llm), "explain_last_change")
    assert not result.is_error, text_of(result)
    assert "src/calc.py" in llm.last
    assert "+def add(a, b):" in llm.last
    # the 1.1 MB file is summarized instead of filling the whole budget
    assert re.search(r"diff --git a/big.txt b/big.txt\n\(omitted: \d+ diff lines", llm.last)


def test_staged_and_unstaged_changes_both_included(repo: Path, llm: FakeLLM):
    write(repo, "src/calc.py", CALC_PY + "\n\ndef staged():\n    return 1\n")
    git(repo, "add", "src/calc.py")
    write(repo, "src/util.py", "def unstaged():\n    return 2\n")
    call_tool(create_server(repo, llm), "explain_last_change")
    assert "+def staged():" in llm.last
    assert "+def unstaged():" in llm.last


def test_last_change_before_first_commit(tmp_path: Path, llm: FakeLLM):
    root = tmp_path / "fresh"
    root.mkdir()
    git(root, "init", "-q")
    write(root, "hello.py", "print('hi')\n")
    git(root, "add", "hello.py")
    write(root, "draft.py", "x = 1\n")
    result = call_tool(create_server(root, llm), "explain_last_change")
    assert not result.is_error, text_of(result)
    assert "+print('hi')" in llm.last
    assert "+x = 1" in llm.last


def test_regression_secret_file_changes_not_in_diff(repo: Path, llm: FakeLLM):
    write(repo, ".env", "OPENAI_API_KEY=sk-test-changed-secret-999999\n")
    write(repo, "src/calc.py", CALC_PY + "# touched\n")
    call_tool(create_server(repo, llm), "explain_last_change")
    assert "# touched" in llm.last
    assert "sk-test-changed-secret" not in llm.last


def test_last_change_outside_git_is_tool_error(plain_dir: Path, llm: FakeLLM):
    result = call_tool(create_server(plain_dir, llm), "explain_last_change")
    assert result.is_error
    assert "not a git repository" in text_of(result).lower()


# --- file watcher -------------------------------------------------------------


@pytest.fixture
def watched(repo: Path):
    """A server whose index watches the repo; the observer stops after the test."""
    apps: list[Vibetter] = []

    def make(llm: FakeLLM):
        app = Vibetter(repo, llm, watch=True)
        apps.append(app)
        return build_mcp(app)

    yield make
    for app in apps:
        app.index().stop()


def _explain_prompt(server, llm: FakeLLM, path: str = "src/calc.py") -> str:
    call_tool(server, "scholar_explain", {"file_path": path, "question": "q"})
    return llm.last


def test_regression_trailing_save_not_dropped(repo: Path, llm: FakeLLM, watched):
    import time

    server = watched(llm)
    _explain_prompt(server, llm)  # builds the index and starts the watcher
    time.sleep(0.3)
    write(repo, "src/calc.py", CALC_PY + "# second save\n")
    time.sleep(0.6)
    write(repo, "src/calc.py", CALC_PY + "# third save\n")
    assert wait_until(lambda: "# third save" in _explain_prompt(server, llm))


def test_watcher_drops_deleted_file(repo: Path, watched):
    import time

    llm = FakeLLM(json.dumps(GRAPH))
    server = watched(llm)
    call_tool(server, "generate_blueprint")
    assert "FILE: src/util.py" in llm.last
    time.sleep(0.3)
    (repo / "src/util.py").unlink()

    def gone() -> bool:
        call_tool(server, "generate_blueprint")
        return "FILE: src/util.py" not in llm.last

    assert wait_until(gone)


def test_watcher_reindexes_moved_file(repo: Path, watched):
    import time

    llm = FakeLLM(json.dumps(GRAPH))
    server = watched(llm)
    call_tool(server, "generate_blueprint")
    time.sleep(0.3)
    (repo / "src/util.py").rename(repo / "src/helpers.py")

    def moved() -> bool:
        call_tool(server, "generate_blueprint")
        return "FILE: src/helpers.py" in llm.last and "FILE: src/util.py" not in llm.last

    assert wait_until(moved)
