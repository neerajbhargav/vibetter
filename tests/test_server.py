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
    data_of,
    git,
    line_of,
    read_resource,
    text_of,
    wait_until,
    write,
)

from vibetter import server as server_module
from vibetter.server import Vibetter, build_mcp, create_server


def test_lists_seven_tools_and_blueprint_resource(repo: Path, llm: FakeLLM):
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
        "search_code",
        "verify_citations",
    }
    assert "ui://blueprint" in resources


def test_scholar_explain_sends_target_file_and_question(repo: Path, llm: FakeLLM):
    result = call_tool(
        create_server(repo, llm),
        "scholar_explain",
        {"file_path": "src/calc.py", "question": "Why check b?"},
    )
    assert not result.is_error
    data = data_of(result)
    assert data["answer"] == "fake answer"
    assert data["citations"] == []
    assert data["stats"]["provider"] == "injected"
    assert data["stats"]["chunks_in_context"] >= 1
    assert "--- src/calc.py:L1-L8 ---" in llm.last
    assert "Target file: src/calc.py" in llm.last
    assert "Why check b?" in llm.last


def test_regression_dot_slash_target_path_found(repo: Path, llm: FakeLLM):
    result = call_tool(
        create_server(repo, llm), "scholar_explain", {"file_path": "./src/calc.py", "question": "q"}
    )
    assert not result.is_error
    assert "--- src/calc.py:L1-L8 ---" in llm.last


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


def test_regression_search_code_output_redacted(repo: Path, llm: FakeLLM):
    # The host agent forwards search hits to its own model, so they leave the machine too.
    data = data_of(
        call_tool(
            create_server(repo, llm),
            "search_code",
            {"query": "settings", "file_path": "app/settings.py"},
        )
    )
    text = "".join(hit["text"] for hit in data["hits"])
    assert "AKIAABCDEFGHIJKLMNOP" not in text
    assert "[REDACTED" in text
    assert "TIMEOUT = 30" in text


def _overview_prompt(root: Path, llm: FakeLLM) -> str:
    """A broad question with no target file: the context is every file's first chunk."""
    call_tool(create_server(root, llm), "debug_error_in_context", {"error_message": "it broke"})
    return llm.last


def test_regression_secret_files_never_sent(repo: Path, llm: FakeLLM):
    prompt = _overview_prompt(repo, llm)
    assert "--- src/calc.py:" in prompt
    for leaked in ("sk-test-not-a-real-key", "hunter2hunter2", "BEGIN PRIVATE KEY"):
        assert leaked not in prompt


def test_regression_context_skips_noise_files(repo: Path, llm: FakeLLM):
    prompt = _overview_prompt(repo, llm)
    for source in ("src/calc.py", "src/util.py", "app/main.py"):
        assert f"--- {source}:" in prompt
    for noise in (
        "package-lock.json",
        "web/app.min.js",
        "web/bundle.js",
        "node_modules/dep/index.js",
        "big.txt",
        "data.bin",
        "ignored.txt",
    ):
        assert f"--- {noise}:" not in prompt


def test_blueprint_is_static_and_needs_no_model(shop: Path, llm: FakeLLM):
    first = data_of(call_tool(create_server(shop, llm), "generate_blueprint"))
    second = data_of(call_tool(create_server(shop, llm), "generate_blueprint"))
    assert first == second
    assert llm.prompts == []
    edges = {(e["source"], e["target"]) for e in first["edges"]}
    assert ("shop/api.py", "shop/cart.py") in edges
    assert first["stats"]["method"].startswith("static imports")


def test_blueprint_tool_links_its_ui_resource(shop: Path, llm: FakeLLM):
    import asyncio

    from fastmcp import Client

    async def go():
        async with Client(create_server(shop, llm)) as client:
            tools = {t.name: t for t in await client.list_tools()}
            resources = {str(r.uri): r for r in await client.list_resources()}
            return tools["generate_blueprint"], resources["ui://blueprint"]

    tool, resource = asyncio.run(go())
    assert (tool.meta or {})["ui"]["resourceUri"] == "ui://blueprint"
    assert resource.mime_type == "text/html;profile=mcp-app"


def test_blueprint_labels_come_from_the_model(shop: Path):
    reply = json.dumps({"groups": {"Checkout": ["shop/api.py", "shop/cart.py"], "Web": []}})
    llm = FakeLLM(reply)
    data = data_of(call_tool(create_server(shop, llm), "generate_blueprint", {"labels": True}))
    groups = {n["id"]: n["data"]["group"] for n in data["nodes"]}
    assert groups["shop/api.py"] == "Checkout"
    assert groups["web/src/main.ts"] == "web"  # unlabelled files keep their directory
    assert "shop/pricing.py" in llm.last


def test_regression_blueprint_parse_failure_is_tool_error(shop: Path):
    result = call_tool(
        create_server(shop, FakeLLM("this is not json")), "generate_blueprint", {"labels": True}
    )
    assert result.is_error
    assert "json" in text_of(result).lower()


def test_blueprint_resource_renders_graph_without_a_tool_call(shop: Path, llm: FakeLLM):
    html = read_resource(create_server(shop, llm), "ui://blueprint")
    assert "window.__VIBETTER_BLUEPRINT__ = " in html
    assert '"id": "shop/cart.py"' in html
    assert 'src="/assets/' not in html  # assets are inlined
    assert "ui/notifications/tool-result" in html  # the MCP Apps bridge is in the bundle
    assert llm.prompts == []


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
    assert "--- src/calc.py:L1-L8 ---" in llm.last


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


def _graph_nodes(server) -> set[str]:
    return {n["id"] for n in data_of(call_tool(server, "generate_blueprint"))["nodes"]}


def test_watcher_drops_deleted_file(repo: Path, llm: FakeLLM, watched):
    import time

    server = watched(llm)
    assert "src/util.py" in _graph_nodes(server)
    time.sleep(0.3)
    (repo / "src/util.py").unlink()
    assert wait_until(lambda: "src/util.py" not in _graph_nodes(server))


def test_watcher_reindexes_moved_file(repo: Path, llm: FakeLLM, watched):
    import time

    server = watched(llm)
    _graph_nodes(server)
    time.sleep(0.3)
    (repo / "src/util.py").rename(repo / "src/helpers.py")

    def moved() -> bool:
        nodes = _graph_nodes(server)
        return "src/helpers.py" in nodes and "src/util.py" not in nodes

    assert wait_until(moved)


def test_watcher_change_reaches_search(repo: Path, llm: FakeLLM, watched):
    import time

    server = watched(llm)
    call_tool(server, "search_code", {"query": "clamp"})
    time.sleep(0.3)
    write(repo, "src/util.py", "def brand_new_helper():\n    return 7\n")

    def found() -> bool:
        hits = data_of(call_tool(server, "search_code", {"query": "brand_new_helper"}))["hits"]
        return bool(hits) and hits[0]["path"] == "src/util.py"

    assert wait_until(found)


# --- citations ------------------------------------------------------------------


def test_citations_are_checked(repo: Path):
    reply = (
        "divide raises at src/calc.py:L6-L7 `raise ZeroDivisionError`. "
        "The cache lives in src/cache.py:3. Line src/calc.py:L99 does not exist."
    )
    data = data_of(
        call_tool(
            create_server(repo, FakeLLM(reply)),
            "scholar_explain",
            {"file_path": "src/calc.py", "question": "q"},
        )
    )
    by_path = {(c["path"], c["start"]): c for c in data["citations"]}
    good = by_path[("src/calc.py", 6)]
    assert good["valid"] and good["grounded"] and good["quote_match"]
    assert not by_path[("src/cache.py", 3)]["valid"]
    assert "out of range" in by_path[("src/calc.py", 99)]["reason"]
    assert data["stats"]["citations"] == {"total": 3, "valid": 1, "grounded": 1, "unverified": 2}
    assert data["answer"] == reply  # not strict: the answer is untouched


def test_citation_outside_shown_context_is_not_grounded(
    shop: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(server_module, "EXPLAIN_CHARS", 1500)  # room for the target only
    line = line_of(shop, "shop/report.py", "def ledger_balance")
    llm = FakeLLM(f"Totals use shop/pricing.py:L9 and ledgers use shop/report.py:L{line}.")
    data = data_of(
        call_tool(
            create_server(shop, llm),
            "scholar_explain",
            {"file_path": "shop/pricing.py", "question": "How is tax computed?"},
        )
    )
    verdicts = {c["path"]: c for c in data["citations"]}
    assert verdicts["shop/pricing.py"]["grounded"] is True
    assert verdicts["shop/report.py"]["valid"] is True
    assert verdicts["shop/report.py"]["grounded"] is False
    assert "def ledger_balance" not in llm.last


def test_strict_mode_strips_unverified_claims(repo: Path, monkeypatch: pytest.MonkeyPatch):
    reply = "Divide checks b at src/calc.py:L6. It retries in src/retry.py:4."
    args = {"file_path": "src/calc.py", "question": "q"}
    strict = data_of(
        call_tool(create_server(repo, FakeLLM(reply)), "scholar_explain", {**args, "strict": True})
    )
    assert "src/calc.py:L6" in strict["answer"]
    assert "It retries" not in strict["answer"]
    assert "removed claims citing src/retry.py:4" in strict["answer"]
    monkeypatch.setenv("VIBETTER_STRICT", "1")
    by_env = data_of(call_tool(create_server(repo, FakeLLM(reply)), "scholar_explain", args))
    assert by_env["answer"] == strict["answer"]


def test_search_code_needs_no_model(shop: Path, llm: FakeLLM):
    data = data_of(
        call_tool(create_server(shop, llm), "search_code", {"query": "apply discount", "limit": 2})
    )
    assert llm.prompts == []
    assert 1 <= len(data["hits"]) <= 2
    top = data["hits"][0]
    assert top["path"] == "shop/cart.py"
    assert top["text"].startswith(f"--- shop/cart.py:L{top['start']}-L{top['end']} ---\n")
    assert re.search(r"^\s*\d+\| ", top["text"], re.MULTILINE)
    assert data["stats"]["chunks_retrieved"] == len(data["hits"])


def test_search_code_within_a_file(shop: Path, llm: FakeLLM):
    data = data_of(
        call_tool(
            create_server(shop, llm),
            "search_code",
            {"query": "refunds", "file_path": "shop/report.py", "limit": 50},
        )
    )
    assert {h["path"] for h in data["hits"]} == {"shop/report.py"}


def test_verify_citations_needs_no_model(repo: Path, llm: FakeLLM):
    data = data_of(
        call_tool(
            create_server(repo, llm),
            "verify_citations",
            {"text": "See src/calc.py:L1 and app/nowhere.py:2."},
        )
    )
    assert llm.prompts == []
    assert [c["valid"] for c in data["citations"]] == [True, False]
    assert all(c["grounded"] is None for c in data["citations"])


def test_last_change_lines_are_numbered_and_grounded(repo: Path):
    write(repo, "src/calc.py", CALC_PY + "\n\ndef triple(x):\n    return 3 * x\n")
    line = line_of(repo, "src/calc.py", "return 3 * x")
    llm = FakeLLM(f"triple is new at src/calc.py:L{line}; add is unchanged at src/calc.py:L1.")
    data = data_of(call_tool(create_server(repo, llm), "explain_last_change"))
    assert re.search(rf"^\s*{line}\| \+    return 3 \* x$", llm.last, re.MULTILINE)
    verdicts = {c["start"]: c for c in data["citations"]}
    assert verdicts[line]["grounded"] is True
    assert verdicts[1]["valid"] is True and verdicts[1]["grounded"] is False
