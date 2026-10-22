"""Register VIBETTER in an IDE's JSON MCP config. The installers call this.

  python -m vibetter.ide <config.json> <command> [args...]

The entry holds only the command: the API key stays in ~/.vibetter/.env.
A config that does not parse (JSONC comments, trailing commas) is left
unchanged; the installer then prints manual steps.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from .config import VibetterError


class IdeConfigError(VibetterError):
    pass


def register(
    path: str | os.PathLike[str],
    command: str,
    args: list[str] | None = None,
    key: str = "mcpServers",
) -> None:
    path = Path(path)
    data: object = {}
    if path.exists():
        backup = path.with_name(path.name + ".vibetter.bak")
        shutil.copy2(path, backup)
        raw = path.read_text(encoding="utf-8")
        if raw.strip():
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                raise IdeConfigError(
                    f"could not parse {path} ({e}). It was not changed; a copy is at {backup}."
                ) from None
    if not isinstance(data, dict) or not isinstance(data.setdefault(key, {}), dict):
        raise IdeConfigError(f"could not parse {path}: expected an object with a '{key}' object.")
    entry: dict[str, object] = {"command": command}
    if args:
        entry["args"] = args
    data[key]["vibetter"] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".vibetter.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    if path.exists():
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print("usage: python -m vibetter.ide <config.json> <command> [args...]", file=sys.stderr)
        return 2
    try:
        register(argv[0], argv[1], argv[2:])
    except IdeConfigError as e:
        print(f"vibetter: {e}", file=sys.stderr)
        return 2
    print(f"registered vibetter in {argv[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
