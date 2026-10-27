#!/usr/bin/env bash
# Run install.sh twice in a throwaway HOME and check every file it wrote. CI runs this.
#
#   tests/installer_smoke.sh
#
# It installs the committed HEAD of this clone (uncommitted edits are not included) with
# the Ollama provider, so it needs no key, but pip needs network access. A fake `claude`
# records the Claude Code registration. The fixtures are the cases that broke before:
# a JSONC Cursor config, a symlinked Windsurf config, a Claude Desktop entry with an env
# block, and a v1 entry with an API key in ~/.vscode/mcp.json.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SANDBOX="$(mktemp -d)"
BRANCH="installer-smoke-$$"
git -C "$ROOT" branch -q "$BRANCH" HEAD # install.sh clones a branch, and CI has a detached HEAD
trap 'git -C "$ROOT" branch -q -D "$BRANCH"; rm -rf "$SANDBOX"' EXIT

export HOME="$SANDBOX/home"
mkdir -p "$HOME/bin" "$HOME/.cursor" "$HOME/.codeium/windsurf" "$HOME/dotfiles" "$HOME/.vscode"
if [ "$(uname)" = "Darwin" ]; then
    DESKTOP_DIR="$HOME/Library/Application Support/Claude"
else
    DESKTOP_DIR="$HOME/.config/Claude"
fi
mkdir -p "$DESKTOP_DIR"

printf '#!/bin/sh\necho "$*" >> "$HOME/claude.log"\n' > "$HOME/bin/claude"
chmod +x "$HOME/bin/claude"
export PATH="$HOME/bin:$PATH"

printf '{\n  // my servers\n  "mcpServers": {"github": {"command": "gh-mcp"},},\n}\n' \
    > "$HOME/.cursor/mcp.json"
echo '{"mcpServers": {}}' > "$HOME/dotfiles/windsurf.json"
ln -s "$HOME/dotfiles/windsurf.json" "$HOME/.codeium/windsurf/mcp_config.json"
cat > "$DESKTOP_DIR/claude_desktop_config.json" <<'JSON'
{"mcpServers": {"vibetter": {"command": "uvx", "env": {"VIBETTER_CODEBASE_PATH": "/srv/app", "GEMINI_API_KEY": "AIza-test-not-real"}}}}
JSON
cat > "$HOME/.vscode/mcp.json" <<'JSON'
{"mcpServers": {"vibetter": {"command": "python", "args": ["-u", "/x/backend/src/server.py"], "env": {"GEMINI_API_KEY": "AIza-test-not-real"}}}}
JSON
cp "$DESKTOP_DIR/claude_desktop_config.json" "$SANDBOX/desktop-before.json"
cp "$HOME/.cursor/mcp.json" "$SANDBOX/cursor-before.json"

for run in 1 2; do # the second run is the documented update path
    echo "--- install.sh, run $run"
    VIBETTER_REPO="$ROOT" VIBETTER_REF="$BRANCH" VIBETTER_PROVIDER=ollama VIBETTER_SKIP_VERIFY=1 \
        bash "$ROOT/install.sh" < /dev/null
done

python3 - "$HOME" "$DESKTOP_DIR" "$SANDBOX" <<'PY'
import json, os, stat, sys
from pathlib import Path

home, desktop, sandbox = (Path(p) for p in sys.argv[1:])
cmd = str(home / ".vibetter/venv/bin/vibetter")

def entry(path):
    return json.loads(path.read_text())["mcpServers"].get("vibetter")

cursor = home / ".cursor/mcp.json"
assert cursor.read_bytes() == (sandbox / "cursor-before.json").read_bytes(), "JSONC changed"

link = home / ".codeium/windsurf/mcp_config.json"
assert link.is_symlink(), "the Windsurf symlink was replaced"
assert entry(home / "dotfiles/windsurf.json") == {"command": cmd}

config = desktop / "claude_desktop_config.json"
assert entry(config) == {"command": cmd, "env": {"VIBETTER_CODEBASE_PATH": "/srv/app"}}, entry(config)
backup = desktop / "claude_desktop_config.json.vibetter.bak"
assert backup.read_bytes() == (sandbox / "desktop-before.json").read_bytes(), "first backup lost"

vscode = (home / ".vscode/mcp.json").read_text()
assert "vibetter" not in json.loads(vscode)["mcpServers"] and "AIza" not in vscode

log = (home / "claude.log").read_text()
assert f"mcp add vibetter -s user -- {cmd}" in log, log

env = home / ".vibetter/.env"
assert "VIBETTER_PROVIDER=ollama" in env.read_text().splitlines()
assert stat.S_IMODE(env.stat().st_mode) == 0o600
print("all installer checks passed")
PY
"$HOME/.vibetter/venv/bin/vibetter" --version
