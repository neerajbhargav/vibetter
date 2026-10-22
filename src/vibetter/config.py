"""Settings: where VIBETTER keeps its files and which codebase it reads."""

from __future__ import annotations

import os
from pathlib import Path


class VibetterError(Exception):
    """An expected failure with a message that is safe to show the user."""


class ConfigError(VibetterError):
    pass


def vibetter_home() -> Path:
    """~/.vibetter by default: the installer's checkout, .env and audio outputs."""
    return Path(os.getenv("VIBETTER_HOME") or Path.home() / ".vibetter")


def load_env() -> None:
    """Load ~/.vibetter/.env. Real environment variables win.

    The project's own .env is never loaded: it belongs to the user's app.
    """
    from dotenv import load_dotenv

    load_dotenv(vibetter_home() / ".env", override=False)


def resolve_root(explicit: str | os.PathLike[str] | None = None) -> Path:
    """The codebase to index: the argument, VIBETTER_CODEBASE_PATH, or the cwd.

    Some MCP hosts start servers in / or in the home directory. Indexing either
    would read the whole disk, so the cwd fallback refuses them.
    """
    raw = explicit or os.getenv("VIBETTER_CODEBASE_PATH")
    root = Path(raw or os.getcwd()).expanduser().resolve()
    if not root.is_dir():
        raise ConfigError(f"Codebase path is not a directory: {root}")
    if not raw and root in (Path(root.anchor), Path.home().resolve()):
        raise ConfigError(
            f"Refusing to index {root}: the MCP host started VIBETTER outside a project. "
            "Set VIBETTER_CODEBASE_PATH to your project directory in the server config."
        )
    return root
