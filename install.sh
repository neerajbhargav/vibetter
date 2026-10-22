#!/usr/bin/env bash
# VIBETTER installer for macOS and Linux.
#
#   curl -fsSL https://raw.githubusercontent.com/neerajbhargav/vibetter/main/install.sh | bash
#
# Non-interactive use: set VIBETTER_PROVIDER (gemini, openai, anthropic or ollama) and, for a
# cloud provider, its key variable (GEMINI_API_KEY, OPENAI_API_KEY or ANTHROPIC_API_KEY).
# The key is stored once, in ~/.vibetter/.env (mode 600). IDE configs only get the command.
# VIBETTER_REPO and VIBETTER_REF pick another clone source or branch (used for testing).
set -euo pipefail

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${CYAN}$1${NC}"; }
success() { echo -e "${GREEN}[OK] $1${NC}"; }
warn()    { echo -e "${YELLOW}[WARN] $1${NC}"; }
error()   { echo -e "${RED}[ERR] $1${NC}" >&2; }

REPO="${VIBETTER_REPO:-https://github.com/neerajbhargav/vibetter.git}"
REF="${VIBETTER_REF:-main}"
INSTALL_DIR="${VIBETTER_HOME:-$HOME/.vibetter}"
ENV_FILE="$INSTALL_DIR/.env"
PYTHON_BIN="$INSTALL_DIR/venv/bin/python"
VIBETTER_BIN="$INSTALL_DIR/venv/bin/vibetter"

# Read from the terminal, not stdin: under `curl | bash`, stdin is this script.
has_tty() { (: < /dev/tty) 2>/dev/null; }
read_tty() {
    local answer="" flags="-r"
    [ "${2:-}" = "secret" ] && flags="-rs"
    if ! { printf '%s' "$1" > /dev/tty && IFS= read $flags answer < /dev/tty; } 2>/dev/null; then
        error "No terminal to read from. Set VIBETTER_PROVIDER (and the API key) in the environment."
        exit 1
    fi
    [ "${2:-}" = "secret" ] && printf '\n' > /dev/tty
    printf '%s' "$answer"
}

echo ""
info "VIBETTER installer"
echo ""

# --- 1. Get the code -------------------------------------------------------------
command -v git >/dev/null 2>&1 || { error "git is required. Install it and re-run."; exit 1; }
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating $INSTALL_DIR ..."
    git -C "$INSTALL_DIR" fetch -q "$REPO" "$REF"
    git -C "$INSTALL_DIR" reset -q --hard FETCH_HEAD
else
    info "Installing to $INSTALL_DIR ..."
    git clone -q --branch "$REF" "$REPO" "$INSTALL_DIR"
fi
# Installs before v2 kept settings in backend/.env.
if [ -f "$INSTALL_DIR/backend/.env" ] && [ ! -f "$ENV_FILE" ]; then
    mv "$INSTALL_DIR/backend/.env" "$ENV_FILE"
fi

# --- 2. Python environment -----------------------------------------------------------
PYTHON_CMD=""
for cmd in python3.14 python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cmd" >/dev/null 2>&1 &&
        "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
        PYTHON_CMD="$cmd"
        break
    fi
done
if [ -z "$PYTHON_CMD" ]; then
    error "Python 3.10 or newer is required. Install it from https://python.org and re-run."
    exit 1
fi
[ -x "$PYTHON_BIN" ] || "$PYTHON_CMD" -m venv "$INSTALL_DIR/venv"

# --- 3. Provider and key ------------------------------------------------------------
PROVIDER="${VIBETTER_PROVIDER:-}"
if [ -z "$PROVIDER" ]; then
    echo "Which AI provider do you want to use?"
    echo "  1) Google Gemini     (key: https://aistudio.google.com/apikey)"
    echo "  2) OpenAI            (key: https://platform.openai.com/api-keys)"
    echo "  3) Anthropic Claude  (key: https://console.anthropic.com/settings/keys)"
    echo "  4) Ollama            (local, no key: https://ollama.com)"
    CHOICE="$(read_tty "Choose [1-4, default 1]: ")"
    case "$CHOICE" in
        ""|1) PROVIDER="gemini" ;;
        2) PROVIDER="openai" ;;
        3) PROVIDER="anthropic" ;;
        4) PROVIDER="ollama" ;;
        *) error "Invalid choice."; exit 1 ;;
    esac
fi
case "$PROVIDER" in
    gemini)    KEY_VAR="GEMINI_API_KEY" ;;
    openai)    KEY_VAR="OPENAI_API_KEY" ;;
    anthropic) KEY_VAR="ANTHROPIC_API_KEY" ;;
    ollama)    KEY_VAR="" ;;
    *) error "Unknown provider '$PROVIDER'. Use gemini, openai, anthropic or ollama."; exit 1 ;;
esac

API_KEY=""
if [ -n "$KEY_VAR" ]; then
    API_KEY="${!KEY_VAR:-}"
    if [ -z "$API_KEY" ]; then
        if [ -f "$ENV_FILE" ] && grep -q "^$KEY_VAR=" "$ENV_FILE"; then
            if has_tty; then
                API_KEY="$(read_tty "Enter your $KEY_VAR (Enter keeps the saved key): " secret)"
            fi
        else
            API_KEY="$(read_tty "Enter your $KEY_VAR (input is hidden): " secret)"
            [ -n "$API_KEY" ] || { error "An API key is required for $PROVIDER."; exit 1; }
        fi
    fi
fi

info "Installing the vibetter package with the $PROVIDER SDK ..."
"$PYTHON_BIN" -m pip install -q --upgrade pip
"$PYTHON_BIN" -m pip install -q -e "$INSTALL_DIR[$PROVIDER]"
success "Package installed: $VIBETTER_BIN"

# Write ~/.vibetter/.env: keep other settings, replace the provider and (if given) the key.
(umask 077 && : > "$ENV_FILE.tmp")
DROP="VIBETTER_PROVIDER"
if [ -n "$API_KEY" ]; then DROP="$DROP|$KEY_VAR"; fi
if [ -f "$ENV_FILE" ]; then grep -v -E "^($DROP)=" "$ENV_FILE" >> "$ENV_FILE.tmp" || true; fi
printf 'VIBETTER_PROVIDER=%s\n' "$PROVIDER" >> "$ENV_FILE.tmp"
if [ -n "$API_KEY" ]; then printf '%s=%s\n' "$KEY_VAR" "$API_KEY" >> "$ENV_FILE.tmp"; fi
mv "$ENV_FILE.tmp" "$ENV_FILE"
chmod 600 "$ENV_FILE"
success "Settings saved to $ENV_FILE"

# The check reads the key from .env itself, so it never appears in a command line.
if [ -z "${VIBETTER_SKIP_VERIFY:-}" ]; then
    info "Checking the provider with one short request ..."
    if VERIFY="$("$PYTHON_BIN" -c '
import asyncio
from vibetter import config, providers
config.load_env()
try:
    asyncio.run(providers.call_llm("Reply with the single word OK."))
    print("OK")
except config.VibetterError as e:
    print(e)
' 2>&1)" && [ "$VERIFY" = "OK" ]; then
        success "Provider works"
    else
        warn "Could not verify the provider: $VERIFY"
    fi
fi

# --- 4. Register with IDEs ------------------------------------------------------------
REGISTERED=false
NEED_MANUAL=false
register_json() {
    if "$PYTHON_BIN" -m vibetter.ide "$1" "$VIBETTER_BIN"; then
        success "$2 configured"
        REGISTERED=true
    else
        warn "$2 was not changed. Add the server by hand (see below)."
        NEED_MANUAL=true
    fi
}

if command -v claude >/dev/null 2>&1; then
    claude mcp remove vibetter -s user >/dev/null 2>&1 || true
    if claude mcp add vibetter -s user -- "$VIBETTER_BIN" >/dev/null 2>&1; then
        success "Claude Code registered"
        REGISTERED=true
    else
        warn "Claude Code found, but 'claude mcp add' failed."
    fi
fi
if [ -d "$HOME/.cursor" ] || command -v cursor >/dev/null 2>&1; then
    register_json "$HOME/.cursor/mcp.json" "Cursor"
fi
if [ "$(uname)" = "Darwin" ] && [ -d "$HOME/Library/Application Support/Claude" ]; then
    register_json "$HOME/Library/Application Support/Claude/claude_desktop_config.json" "Claude Desktop"
fi
if [ -d "$HOME/.config/Claude" ]; then
    register_json "$HOME/.config/Claude/claude_desktop_config.json" "Claude Desktop"
fi
if [ -d "$HOME/.codeium/windsurf" ]; then
    register_json "$HOME/.codeium/windsurf/mcp_config.json" "Windsurf"
fi

if [ "$REGISTERED" = false ] || [ "$NEED_MANUAL" = true ]; then
    echo ""
    warn "Add VIBETTER by hand where it was not registered:"
    echo "  Claude Code:  claude mcp add vibetter -s user -- $VIBETTER_BIN"
    echo "  JSON config:  {\"mcpServers\": {\"vibetter\": {\"command\": \"$VIBETTER_BIN\"}}}"
fi

echo ""
success "VIBETTER is ready (provider: $PROVIDER)."
echo "  Tools: explain_last_change, scholar_explain, debug_error_in_context,"
echo "         generate_blueprint, generate_audio_overview"
echo "  Terminal: $VIBETTER_BIN ask \"How does X work?\""
echo "  If your IDE starts servers outside the project, set VIBETTER_CODEBASE_PATH in its config."
echo ""
