#!/usr/bin/env bash
set -e

# --- Colors --------------------------------------------------------------------
CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${CYAN}$1${NC}"; }
success() { echo -e "${GREEN}[OK] $1${NC}"; }
warn()    { echo -e "${YELLOW}[WARN] $1${NC}"; }
error()   { echo -e "${RED}[ERR] $1${NC}"; }

echo ""
echo -e "${CYAN}+------------------------------------------+${NC}"
echo -e "${CYAN}|        VIBETTER - One-Line Install       |${NC}"
echo -e "${CYAN}|   Cognitive Codebase Bridge for AI IDEs  |${NC}"
echo -e "${CYAN}+------------------------------------------+${NC}"
echo ""

# --- 1. Install/Update ---------------------------------------------------------
INSTALL_DIR="$HOME/.vibetter"

if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing installation..."
    ENV_BACKUP=""
    [ -f "$INSTALL_DIR/backend/.env" ] && ENV_BACKUP=$(cat "$INSTALL_DIR/backend/.env")
    git -C "$INSTALL_DIR" fetch origin -q 2>/dev/null || true
    git -C "$INSTALL_DIR" reset --hard origin/main 2>/dev/null || true
    [ -n "$ENV_BACKUP" ] && printf '%s' "$ENV_BACKUP" > "$INSTALL_DIR/backend/.env"
else
    info "Installing VIBETTER to ~/.vibetter..."
    git clone -q https://github.com/neerajbhargav/vibetter.git "$INSTALL_DIR"
fi

# --- 2. Python venv ------------------------------------------------------------
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

# --- 3. AI Provider Selection --------------------------------------------------
echo ""
info "Which AI provider do you want to use?"
echo ""
echo "  1) Google Gemini  (free tier: https://aistudio.google.com/apikey)"
echo "  2) OpenAI/ChatGPT (https://platform.openai.com/api-keys)"
echo "  3) Anthropic Claude (https://console.anthropic.com/settings/keys)"
echo "  4) Ollama - local models, no API key (https://ollama.ai)"
echo ""
read -rp "$(echo -e "${CYAN}Choose [1-4, default=1]: ${NC}")" PROVIDER_CHOICE

case "${PROVIDER_CHOICE:-1}" in
    1) PROVIDER="gemini";    KEY_VAR="GEMINI_API_KEY";    KEY_URL="https://aistudio.google.com/apikey";            SDK="google-genai" ;;
    2) PROVIDER="openai";    KEY_VAR="OPENAI_API_KEY";    KEY_URL="https://platform.openai.com/api-keys";          SDK="openai" ;;
    3) PROVIDER="anthropic"; KEY_VAR="ANTHROPIC_API_KEY"; KEY_URL="https://console.anthropic.com/settings/keys";   SDK="anthropic" ;;
    4) PROVIDER="ollama";    KEY_VAR="";                  KEY_URL="";                                               SDK="ollama" ;;
    *) error "Invalid choice."; exit 1 ;;
esac

# Install the chosen provider SDK
info "Installing $PROVIDER SDK..."
"$PYTHON_BIN" -m pip install "$SDK" -q
success "$PROVIDER SDK installed"

# Collect API key (skip for Ollama)
API_KEY=""
if [ -n "$KEY_VAR" ]; then
    echo ""
    info "Get your API key at: $KEY_URL"
    echo ""
    read -rp "$(echo -e "${CYAN}Enter your $KEY_VAR: ${NC}")" API_KEY

    if [ -z "$API_KEY" ]; then
        error "API key cannot be empty."
        exit 1
    fi

    # Verify the key works
    info "Verifying API key..."
    VERIFY=$("$PYTHON_BIN" -c "
try:
    if '$PROVIDER' == 'gemini':
        from google import genai
        c = genai.Client(api_key='$API_KEY')
        r = c.models.generate_content(model='gemini-2.0-flash-lite', contents='Say: OK')
    elif '$PROVIDER' == 'openai':
        import openai
        c = openai.OpenAI(api_key='$API_KEY')
        r = c.chat.completions.create(model='gpt-4o-mini', messages=[{'role':'user','content':'Say: OK'}], max_tokens=5)
    elif '$PROVIDER' == 'anthropic':
        import anthropic
        c = anthropic.Anthropic(api_key='$API_KEY')
        r = c.messages.create(model='claude-haiku-4-20250414', max_tokens=5, messages=[{'role':'user','content':'Say: OK'}])
    print('OK')
except Exception as e:
    print(f'FAIL:{e}')
" 2>/dev/null)

    if [[ "$VERIFY" == "OK" ]]; then
        success "API key verified!"
    else
        warn "Could not verify key right now (may be a quota issue). Proceeding anyway."
        warn "Details: $VERIFY"
    fi
fi

# Write .env
mkdir -p "$INSTALL_DIR/backend"
{
    echo "VIBETTER_PROVIDER=$PROVIDER"
    [ -n "$API_KEY" ] && echo "$KEY_VAR=$API_KEY"
} > "$INSTALL_DIR/backend/.env"

# --- 4. Auto-detect and register IDEs -----------------------------------------
echo ""
info "Detecting installed IDEs..."
REGISTERED=false

# Build the env block for MCP configs
if [ -n "$KEY_VAR" ]; then
    ENV_JSON="\"$KEY_VAR\": \"$API_KEY\""
else
    ENV_JSON=""
fi

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

env_block = {'VIBETTER_PROVIDER': '$PROVIDER'}
if '$KEY_VAR':
    env_block['$KEY_VAR'] = '$API_KEY'

data.setdefault('mcpServers', {})['vibetter'] = {
    'command': '$PYTHON_BIN',
    'args': ['-u', '$INSTALL_DIR/backend/src/server.py'],
    'env': env_block
}
json.dump(data, open(path, 'w'), indent=2)
" && success "$ide_name configured!" || warn "Failed to write $ide_name config"
}

# Claude Code (auto-register via CLI)
if command -v claude &>/dev/null; then
    claude mcp remove vibetter -s user 2>/dev/null || true
    ENV_ARGS="-e VIBETTER_PROVIDER=$PROVIDER"
    [ -n "$KEY_VAR" ] && ENV_ARGS="$ENV_ARGS -e $KEY_VAR=$API_KEY"
    eval claude mcp add vibetter -s user $ENV_ARGS \
        -- "$PYTHON_BIN" -u "$INSTALL_DIR/backend/src/server.py" 2>/dev/null \
        && success "Claude Code - auto-registered (no restart needed)" \
        && REGISTERED=true \
        || warn "Claude Code detected but auto-registration failed."
fi

# Cursor
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

# Windsurf
if [ -d "$HOME/.codeium/windsurf" ]; then
    register_mcp_json "$HOME/.codeium/windsurf/mcp_config.json" "Windsurf"
    REGISTERED=true
fi

# VS Code (Roo/Cline)
if command -v code &>/dev/null; then
    register_mcp_json "$HOME/.vscode/mcp.json" "VS Code (Roo/Cline)"
    REGISTERED=true
fi

if [ "$REGISTERED" = false ]; then
    echo ""
    warn "No supported IDE auto-detected. Add VIBETTER manually:"
    echo ""
    echo "  Claude Code:"
    ENV_ARGS="-e VIBETTER_PROVIDER=$PROVIDER"
    [ -n "$KEY_VAR" ] && ENV_ARGS="$ENV_ARGS -e $KEY_VAR=\$YOUR_KEY"
    echo "    claude mcp add vibetter -s user $ENV_ARGS -- $PYTHON_BIN -u $INSTALL_DIR/backend/src/server.py"
fi

# --- 5. Done -------------------------------------------------------------------
echo ""
echo -e "${GREEN}+------------------------------------------+${NC}"
echo -e "${GREEN}|         VIBETTER is ready to use!        |${NC}"
echo -e "${GREEN}|    Provider: $(printf '%-27s' "$PROVIDER")  |${NC}"
echo -e "${GREEN}+------------------------------------------+${NC}"
echo ""
echo "  Open any project in your IDE and use these tools:"
echo ""
echo -e "  ${CYAN}explain_last_change()${NC}        - understand what AI just generated"
echo -e "  ${CYAN}scholar_explain(file, q)${NC}     - explain any file or function"
echo -e "  ${CYAN}debug_error_in_context(err)${NC}  - paste an error, get a fix"
echo -e "  ${CYAN}generate_blueprint()${NC}         - visualize your codebase map"
echo -e "  ${CYAN}generate_audio_overview(q)${NC}   - listen to a code walkthrough"
echo ""
