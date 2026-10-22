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


def test_ask_prints_answer(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    fake = FakeLLM("divide raises on zero (src/calc.py:7)")
    monkeypatch.setattr(providers, "call_llm", fake)
    code = cli.main(["ask", "What does divide do?", "--file", "src/calc.py", "--root", str(repo)])
    assert code == 0
    assert "src/calc.py:7" in capsys.readouterr().out
    assert "What does divide do?" in fake.last


def test_ask_failure_exits_nonzero(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(providers, "call_llm", FakeLLM(error=ProviderError("no key")))
    assert cli.main(["ask", "q", "--root", str(repo)]) == 1
    assert "no key" in capsys.readouterr().err
