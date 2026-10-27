"""Offline fixtures: a synthetic git repo, a fake LLM, and an isolated HOME."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

CALC_PY = """\
def add(a, b):
    return a + b


def divide(a, b):
    if b == 0:
        raise ZeroDivisionError("b must not be zero")
    return a / b
"""

UTIL_PY = """\
def clamp(value, low, high):
    return max(low, min(value, high))
"""

MAIN_PY = """\
from src.calc import add
from src.util import clamp

print(clamp(add(2, 3), 0, 4))
"""

# Fake credentials, shaped like real ones so the redaction patterns fire.
SETTINGS_PY = """\
DEBUG = True
AWS_ACCESS_KEY_ID = "AKIAABCDEFGHIJKLMNOP"
GITHUB_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
TIMEOUT = 30
"""

PROVIDER_ENV = (
    "VIBETTER_PROVIDER",
    "VIBETTER_MODEL",
    "VIBETTER_CODEBASE_PATH",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OLLAMA_HOST",
    "OLLAMA_BASE_URL",
    "VIBETTER_HOME",
    "VIBETTER_TRACE",
    "VIBETTER_OTEL",
    "VIBETTER_STRICT",
    "VIBETTER_OLLAMA_NUM_CTX",
)
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def _home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # One HOME for the session: on macOS the /usr/bin/git shim (xcrun) pays
    # about half a second the first time it runs under a new HOME.
    home = tmp_path_factory.mktemp("home")
    (home / ".gitconfig").write_text("[user]\n\tname = Test\n\temail = test@example.com\n")
    return home


@pytest.fixture(autouse=True)
def isolated_env(_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep the user's real keys, HOME and git config out of every test."""
    monkeypatch.setenv("HOME", str(_home))
    monkeypatch.setenv("USERPROFILE", str(_home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(_home / ".gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)
    # Never download an embedding model in tests, even if the dense extra is installed.
    monkeypatch.delenv("VIBETTER_DENSE", raising=False)
    # Traces and audio go to a fresh ~/.vibetter per test.
    monkeypatch.setenv("VIBETTER_HOME", str(tmp_path / "vibetter-home"))
    return _home


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def write(root: Path, rel: str, content: str | bytes) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content)
    return path


def populate(root: Path) -> None:
    write(root, "src/calc.py", CALC_PY)
    write(root, "src/util.py", UTIL_PY)
    write(root, "app/main.py", MAIN_PY)
    write(root, "app/settings.py", SETTINGS_PY)
    write(root, "README.md", "# Demo\n\nA tiny calculator.\n")
    write(root, ".gitignore", "node_modules/\nignored.txt\n")
    write(root, "ignored.txt", "this file is gitignored\n")
    write(root, "node_modules/dep/index.js", "module.exports = 1;\n")
    lock = {"name": "demo", "packages": {f"pkg{i}": {"version": "1.0.0"} for i in range(50)}}
    write(root, "package-lock.json", json.dumps(lock, indent=2))
    write(root, "web/app.min.js", "var a=1;" * 400)
    write(root, "web/bundle.js", "function f(){return 1}" * 300)
    write(root, "data.bin", b"\x00\x01\x02binary")
    write(root, "big.txt", "x" * 1_100_000)
    write(root, ".env", "OPENAI_API_KEY=sk-test-not-a-real-key-123456\n")
    write(root, "config/credentials.json", '{"password": "hunter2hunter2"}\n')
    write(root, "certs/server.pem", "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n")
    write(root, "id_rsa", "not a real key\n")


@pytest.fixture(scope="session")
def _templates(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    base = tmp_path_factory.mktemp("templates")
    plain = base / "plain"
    plain.mkdir()
    populate(plain)
    repo = base / "repo"
    shutil.copytree(plain, repo)
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    for args in (
        ["init", "-q", "-b", "main"],
        # A commit can start `git maintenance` in the background. Its lock file then
        # appears and vanishes while a test copies the repo, and copytree fails (CI, 3.12).
        ["config", "maintenance.auto", "false"],
        ["config", "gc.auto", "0"],
        ["add", "-A"],
        [
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-q",
            "-m",
            "initial",
        ],
    ):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)
    return plain, repo


@pytest.fixture
def repo(tmp_path: Path, _templates: tuple[Path, Path]) -> Path:
    """A committed git repo with source, noise and fake secrets (a fresh copy per test)."""
    return Path(shutil.copytree(_templates[1], tmp_path / "repo", symlinks=True))


@pytest.fixture
def plain_dir(tmp_path: Path, _templates: tuple[Path, Path]) -> Path:
    """The same files with no git repository."""
    return Path(shutil.copytree(_templates[0], tmp_path / "plain", symlinks=True))


@pytest.fixture
def shop(tmp_path: Path) -> Path:
    """A copy of tests/fixtures/shop: a synthetic Python + Vue bookshop."""
    return Path(shutil.copytree(FIXTURES / "shop", tmp_path / "shop"))


def line_of(root: Path, rel: str, needle: str) -> int:
    """The 1-based line number of the first line in a file that contains needle."""
    for n, line in enumerate((root / rel).read_text().splitlines(), 1):
        if needle in line:
            return n
    raise AssertionError(f"{needle!r} not in {rel}")


class FakeLLM:
    """Records every prompt and returns a canned reply."""

    def __init__(self, reply: str = "fake answer", error: Exception | None = None):
        self.reply = reply
        self.error = error
        self.prompts: list[str] = []

    async def __call__(self, prompt: str, json_mode: bool = False) -> str:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.reply

    @property
    def last(self) -> str:
        assert self.prompts, "the LLM was never called"
        return self.prompts[-1]


@pytest.fixture
def llm() -> FakeLLM:
    return FakeLLM()


def call_tool(server: Any, name: str, args: dict[str, Any] | None = None) -> Any:
    async def go():
        async with Client(server) as client:
            return await client.call_tool(name, args or {}, raise_on_error=False)

    return asyncio.run(go())


def read_resource(server: Any, uri: str) -> str:
    async def go():
        async with Client(server) as client:
            contents = await client.read_resource(uri)
            return contents[0].text  # type: ignore[union-attr]

    return asyncio.run(go())


def text_of(result: Any) -> str:
    return "\n".join(getattr(block, "text", "") for block in result.content)


def data_of(result: Any) -> dict[str, Any]:
    """The structured content of a tool result."""
    assert result.structured_content is not None, text_of(result)
    return result.structured_content


def wait_until(predicate, timeout: float = 6.0, interval: float = 0.1) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()
