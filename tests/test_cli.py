"""The vibetter console script."""

from __future__ import annotations

import io
import os
import re
from pathlib import Path

import pytest
from conftest import FakeLLM

from vibetter import cli, providers
from vibetter.providers import ProviderError


def test_index_stats(repo: Path, capsys: pytest.CaptureFixture[str]):
    assert cli.main(["index", "--stats", "--root", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "files indexed:" in out
    assert "secret: 4" in out
    assert "mode: git" in out


def test_ask_prints_answer_and_checked_citations(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    fake = FakeLLM("divide raises on zero (src/calc.py:7)")
    monkeypatch.setattr(providers, "call_llm", fake)
    code = cli.main(["ask", "What does divide do?", "--file", "src/calc.py", "--root", str(repo)])
    assert code == 0
    out = capsys.readouterr().out
    assert "divide raises on zero (src/calc.py:7)" in out
    assert "citations: 1 found, 1 verified (1 valid, 1 grounded)" in out
    assert "ok src/calc.py:L7" in out
    assert "What does divide do?" in fake.last


def test_ask_failure_exits_nonzero(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(providers, "call_llm", FakeLLM(error=ProviderError("no key")))
    assert cli.main(["ask", "q", "--root", str(repo)]) == 1
    assert "no key" in capsys.readouterr().err


def test_search_prints_numbered_chunks(shop: Path, capsys: pytest.CaptureFixture[str]):
    assert cli.main(["search", "formatPrice", "--limit", "1", "--root", str(shop)]) == 0
    out = capsys.readouterr().out
    assert "--- web/src/lib/format.ts:L1-" in out
    assert "| export function formatPrice" in out


def test_verify_exit_code_reflects_citations(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    good = tmp_path / "good.md"
    good.write_text("See src/calc.py:L1-L2.")
    bad = tmp_path / "bad.md"
    bad.write_text("See src/calc.py:L1 and src/ghost.py:4.")
    assert cli.main(["verify", str(good), "--root", str(repo)]) == 0
    assert cli.main(["verify", str(bad), "--root", str(repo)]) == 2
    out = capsys.readouterr().out
    assert "!! src/ghost.py:L4  (file not indexed)" in out


def test_ask_reports_its_context_on_stderr(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(providers, "call_llm", FakeLLM("ok"))
    assert cli.main(["ask", "q", "--file", "src/calc.py", "--root", str(repo)]) == 0
    err = capsys.readouterr().err
    assert re.search(r"^context: \d+ chunks, [\d,]+ characters from \d+ files", err, re.M)


def test_regression_summary_counts_verified_not_just_valid(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    # "1 found, 1 valid" sat next to "!!" when the quote did not match.
    monkeypatch.setattr("sys.stdin", io.StringIO("src/calc.py:L1 `return 42`."))
    assert cli.main(["verify", "--root", str(repo)]) == 2
    out = capsys.readouterr().out
    assert "citations: 1 found, 0 verified (1 valid)" in out


def test_wrap_keeps_citations_and_code_whole(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setattr("shutil.get_terminal_size", lambda: os.terminal_size((40, 24)))
    long = "x" * 30 + " source/utils/is-network-error.ts:L4-L11 and more words here"
    code = "```\n" + "y" * 60 + "\n```"
    out = cli._wrap(f"- {long}\n{code}")
    assert "source/utils/is-network-error.ts:L4-L11" in out.splitlines()[1]
    assert out.splitlines()[1].startswith("  ")
    assert "y" * 60 in out.splitlines()
