#!/usr/bin/env bash
set -e

# ─── Colors ────────────────────────────────────────────────────────────────────
CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${CYAN}$1${NC}"; }
success() { echo -e "${GREEN}✅ $1${NC}"; }
warn()    { echo -e "${YELLOW}⚠️  $1${NC}"; }
error()   { echo -e "${RED}❌ $1${NC}"; }

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║        VIBETTER - One-Line Install       ║${NC}"
echo -e "${CYAN}║   Cognitive Codebase Bridge for Gemini   ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""

# ─── 1. Install/Update ─────────────────────────────────────────────────────────
INSTALL_DIR="$HOME/.vibetter"

if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing installation..."
    # Preserve .env, fetch remote, force-reset to origin/main (no merge = no conflicts)
    ENV_BACKUP=""
    [ -f "$INSTALL_DIR/backend/.env" ] && ENV_BACKUP=$(cat "$INSTALL_DIR/backend/.env")
    git -C "$INSTALL_DIR" fetch origin -q 2>/dev/null || true
    git -C "$INSTALL_DIR" reset --hard origin/main 2>/dev/null || true
    [ -n "$ENV_BACKUP" ] && printf '%s' "$ENV_BACKUP" > "$INSTALL_DIR/backend/.env"
else
    info "Installing VIBETTER to ~/.vibetter..."
    git clone -q https://github.com/neerajbhargav/vibetter.git "$INSTALL_DIR"
fi

# ─── 2. Python venv ────────────────────────────────────────────────────────────
info "Setting up Python environment..."

PYTHON_CMD=""
for cmd in python3 python python3.11 python3.10 python3.9; do
    if command -v "$cmd" &>/dev/null && "$cmd" -c "import sys; exit(0 if sys.version_info >= (3,9) else 1)" 2>/dev/null; then
        PYTHON_CMD="$cmd"
        break
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    error "Python 3.9+ is required. Install it from https://python.org and re-run."
    exit 1
fi

PYTHON_BIN="$INSTALL_DIR/venv/bin/python"

if [ ! -f "$PYTHON_BIN" ]; then
    "$PYTHON_CMD" -m venv "$INSTALL_DIR/venv"
fi

"$PYTHON_BIN" -m pip install --upgrade pip -q
"$PYTHON_BIN" -m pip install -r "$INSTALL_DIR/backend/requirements.txt" -q
success "Python environment ready"

# ─── 3. Gemini API Key ─────────────────────────────────────────────────────────
echo ""
info "Get a free Gemini API key at: https://aistudio.google.com/apikey"
echo ""
read -rp "$(echo -e "${CYAN}Enter your Gemini API Key: ${NC}")" API_KEY

if [ -z "$API_KEY" ]; then
    error "API key cannot be empty."
    exit 1
fi

# Verify the key works
info "Verifying API key..."
VERIFY=$("$PYTHON_BIN" -c "
try:
    from google import genai
    c = genai.Client(api_key='$API_KEY')
    r = c.models.generate_content(model='gemini-2.0-flash', contents='Say: OK')
    print('OK')
except Exception as e:
    print(f'FAIL:{e}')
" 2>/dev/null)

if [[ "$VERIFY" == "OK" ]]; then
    success "API key verified!"
else
    warn "Could not verify key right now (may be a quota issue). Proceeding anyway."
    warn "If tools fail, get a fresh key at: https://aistudio.google.com/apikey"
fi

mkdir -p "$INSTALL_DIR/backend"
echo "GEMINI_API_KEY=$API_KEY" > "$INSTALL_DIR/backend/.env"

# ─── 4. Auto-detect and register IDEs ─────────────────────────────────────────
echo ""
info "Detecting installed IDEs..."
REGISTERED=false

register_mcp_json() {
    local config_path="$1"
    local ide_name="$2"
    mkdir -p "$(dirname "$config_path")"
    "$PYTHON_BIN" -c "
import json, os, sys

path = '$config_path'
data = {}
if os.path.exists(path):
    try:
        data = json.load(open(path))
    except Exception:
        pass

data.setdefault('mcpServers', {})['vibetter'] = {
    'command': '$PYTHON_BIN',
    'args': ['-u', '$INSTALL_DIR/backend/src/server.py'],
    'env': {'GEMINI_API_KEY': '$API_KEY'}
}
json.dump(data, open(path, 'w'), indent=2)
" && success "$ide_name configured!" || warn "Failed to write $ide_name config"
}

# Claude Code (auto-register via CLI - works immediately, no restart needed)
if command -v claude &>/dev/null; then
    # Remove stale entry first, then add fresh
    claude mcp remove vibetter -s user 2>/dev/null || true
    claude mcp add vibetter -s user \
        -e GEMINI_API_KEY="$API_KEY" \
        -- "$PYTHON_BIN" -u "$INSTALL_DIR/backend/src/server.py" 2>/dev/null \
        && success "Claude Code - auto-registered (no restart needed)" \
        && REGISTERED=true \
        || warn "Claude Code detected but auto-registration failed. Run manually: claude mcp add vibetter -s user -e GEMINI_API_KEY=$API_KEY -- $PYTHON_BIN -u $INSTALL_DIR/backend/src/server.py"
fi

# Cursor (~/.cursor/mcp.json)
if [ -d "$HOME/.cursor" ] || command -v cursor &>/dev/null; then
    register_mcp_json "$HOME/.cursor/mcp.json" "Cursor"
    REGISTERED=true
fi

# Claude Desktop (macOS)
if [ "$(uname)" = "Darwin" ] && [ -d "$HOME/Library/Application Support/Claude" ]; then
    register_mcp_json "$HOME/Library/Application Support/Claude/claude_desktop_config.json" "Claude Desktop (Mac)"
    REGISTERED=true
fi

# Claude Desktop (Linux)
if [ -f "$HOME/.config/Claude/claude_desktop_config.json" ] || [ -d "$HOME/.config/Claude" ]; then
    register_mcp_json "$HOME/.config/Claude/claude_desktop_config.json" "Claude Desktop (Linux)"
    REGISTERED=true
fi

# Windsurf (~/.codeium/windsurf/mcp_config.json)
if [ -d "$HOME/.codeium/windsurf" ]; then
    register_mcp_json "$HOME/.codeium/windsurf/mcp_config.json" "Windsurf"
    REGISTERED=true
fi

# VS Code + Roo/Cline (~/.vscode/mcp.json)
if command -v code &>/dev/null; then
    register_mcp_json "$HOME/.vscode/mcp.json" "VS Code (Roo/Cline)"
    REGISTERED=true
fi

# No IDE detected - print manual instructions
if [ "$REGISTERED" = false ]; then
    echo ""
    warn "No supported IDE auto-detected. Add VIBETTER manually:"
    echo ""
    echo "  Claude Code:  claude mcp add vibetter -s user -e GEMINI_API_KEY=$API_KEY -- $PYTHON_BIN -u $INSTALL_DIR/backend/src/server.py"
    echo ""
    echo "  Any IDE with mcp.json support:"
    echo '  {'
    echo '    "mcpServers": {'
    echo '      "vibetter": {'
    echo "        \"command\": \"$PYTHON_BIN\","
    echo "        \"args\": [\"-u\", \"$INSTALL_DIR/backend/src/server.py\"],"
    echo "        \"env\": { \"GEMINI_API_KEY\": \"$API_KEY\" }"
    echo '      }'
    echo '    }'
    echo '  }'
fi

# ─── 5. Done ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         VIBETTER is ready to use!        ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo "  Open any project in your IDE and use these tools:"
echo ""
echo -e "  ${CYAN}explain_last_change()${NC}        - understand what AI just generated"
echo -e "  ${CYAN}scholar_explain(file, q)${NC}     - explain any file or function"
echo -e "  ${CYAN}debug_error_in_context(err)${NC}  - paste an error, get a fix"
echo -e "  ${CYAN}generate_blueprint()${NC}         - visualize your codebase map"
echo -e "  ${CYAN}generate_audio_overview(q)${NC}   - listen to a code walkthrough"
echo ""
