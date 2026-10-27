"""Register VIBETTER in an IDE's JSON MCP config. The installers call this.

  python -m vibetter.ide [--desktop] <config.json> <command> [args...]
  python -m vibetter.ide --remove-v1 <config.json>

The entry holds the command; the API key stays in ~/.vibetter/.env. An
existing vibetter entry keeps its env (VIBETTER_CODEBASE_PATH and the like)
minus any *_API_KEY, so re-running the installer is safe. --desktop exits 3
when the entry has no VIBETTER_CODEBASE_PATH, which Claude Desktop needs.
--remove-v1 deletes a v1 entry, which held the API key in plain text.

A config that does not parse (JSONC comments, trailing commas) is left
unchanged; the installer then prints manual steps. A symlinked config is
written through the link, and the first backup is never overwritten.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from .config import VibetterError

NEEDS_ROOT = 3
V1_SERVER = "backend/src/server.py"


class IdeConfigError(VibetterError):
    pass


def _load(path: Path, key: str) -> dict[str, Any]:
    data: object = {}
    if path.exists():
        backup = path.with_name(path.name + ".vibetter.bak")
        if not backup.exists():  # the first copy is the config from before VIBETTER
            shutil.copy2(path, backup)
        raw = path.read_text(encoding="utf-8-sig")
        if raw.strip():
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                raise IdeConfigError(
                    f"could not parse {path} ({e}). It was not changed; a copy is at {backup}."
                ) from None
    if not isinstance(data, dict) or not isinstance(data.setdefault(key, {}), dict):
        raise IdeConfigError(f"could not parse {path}: expected an object with a '{key}' object.")
    return data


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".vibetter.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if path.exists():
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


def _is_v1(entry: object) -> bool:
    return isinstance(entry, dict) and any(V1_SERVER in str(a) for a in entry.get("args") or [])


def register(
    path: str | os.PathLike[str],
    command: str,
    args: list[str] | None = None,
    key: str = "mcpServers",
) -> dict[str, Any]:
    """Write the vibetter entry and return it."""
    path = Path(path).resolve()  # through a symlink into a dotfiles repo
    data = _load(path, key)
    old = data[key].get("vibetter")
    entry: dict[str, Any] = dict(old) if isinstance(old, dict) else {}
    env = entry.get("env")
    env = env if isinstance(env, dict) else {}
    # v1 wrote the provider into each IDE config; the installer now keeps it in .env.
    drop = {"VIBETTER_PROVIDER"} if _is_v1(old) else set()
    env = {k: v for k, v in env.items() if not k.endswith("_API_KEY") and k not in drop}
    entry["command"] = command
    if args:
        entry["args"] = args
    else:
        entry.pop("args", None)
    if env:
        entry["env"] = env
    else:
        entry.pop("env", None)
    data[key]["vibetter"] = entry
    _save(path, data)
    return entry


def remove_v1(path: str | os.PathLike[str], key: str = "mcpServers") -> bool:
    """Delete a v1 vibetter entry (it points at a deleted file and holds the key)."""
    path = Path(path).resolve()
    if not path.exists():
        return False
    data = _load(path, key)
    if not _is_v1(data[key].get("vibetter")):
        return False
    del data[key]["vibetter"]
    _save(path, data)
    return True


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv[:1] == ["--remove-v1"] and len(argv) == 2:
            if remove_v1(argv[1]):
                print(f"removed the v1 vibetter entry, and the API key in it, from {argv[1]}")
            return 0
        desktop = argv[:1] == ["--desktop"]
        argv = argv[1:] if desktop else argv
        if len(argv) < 2:
            print(
                "usage: python -m vibetter.ide [--desktop] <config.json> <command> [args...]\n"
                "       python -m vibetter.ide --remove-v1 <config.json>",
                file=sys.stderr,
            )
            return 2
        entry = register(argv[0], argv[1], argv[2:])
    except IdeConfigError as e:
        print(f"vibetter: {e}", file=sys.stderr)
        return 2
    print(f"registered vibetter in {argv[0]}")
    if desktop and "VIBETTER_CODEBASE_PATH" not in entry.get("env", {}):
        return NEEDS_ROOT
    return 0


if __name__ == "__main__":
    sys.exit(main())
