"""The vibetter console script."""

from __future__ import annotations

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
    assert "citations: 1 found, 1 valid, 1 grounded" in out
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
