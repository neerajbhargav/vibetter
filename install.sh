#!/usr/bin/env bash
set -e

echo "🚀 Welcome to VIBETTER Installer!"

# 1. Download/Update codebase
INSTALL_DIR="$HOME/.vibetter"
if [ -d "$INSTALL_DIR" ]; then
    echo "Updating existing installation in $INSTALL_DIR..."
    cd "$INSTALL_DIR"
    git pull -q
else
    echo "Cloning VIBETTER..."
    git clone -q https://github.com/neerajbhargav/vibetter.git "$INSTALL_DIR"
fi

# 2. Setup Virtual Environment autonomously
echo "Setting up isolated Python environment..."
cd "$INSTALL_DIR"
python3 -m venv venv
PYTHON_BIN="$INSTALL_DIR/venv/bin/python"
$PYTHON_BIN -m pip install --upgrade pip -q
$PYTHON_BIN -m pip install -r backend/requirements.txt -q

# 3. Environment Config
echo ""
read -p "1️⃣ Please enter your Google Gemini (AI Studio) API Key: " API_KEY

mkdir -p "$INSTALL_DIR/backend"
echo "GEMINI_API_KEY=$API_KEY" > "$INSTALL_DIR/backend/.env"
echo "VIBETTER_CODEBASE_PATH=." >> "$INSTALL_DIR/backend/.env"
echo "✅ Saved API Key securely inside ~/.vibetter/backend/.env"

# 4. Native IDE Integration
echo ""
echo "2️⃣ Which IDE are you using?"
echo "   1) Claude Desktop"
echo "   2) Cursor"
echo "   3) Claude Code (Terminal)"
read -p "Select [1-3]: " IDE_CHOICE

if [ "$IDE_CHOICE" = "1" ]; then
    if [ "$(uname)" = "Darwin" ]; then
        CONFIG_PATH="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
    else
        CONFIG_PATH="$HOME/.claude_desktop_config.json"
    fi
    
    mkdir -p "$(dirname "$CONFIG_PATH")"
    if [ ! -f "$CONFIG_PATH" ]; then
        echo '{"mcpServers": {}}' > "$CONFIG_PATH"
    fi
    
    $PYTHON_BIN -c "
import json, os
path = os.path.expanduser('$CONFIG_PATH')
with open(path, 'r') as f:
    data = json.load(f)
if 'mcpServers' not in data:
    data['mcpServers'] = {}
data['mcpServers']['vibetter'] = {
    'command': '$PYTHON_BIN',
    'args': ['-u', '$INSTALL_DIR/backend/src/server.py'],
    'env': {'GEMINI_API_KEY': '$API_KEY'}
}
with open(path, 'w') as f:
    json.dump(data, f, indent=2)
"
    echo "🎉 Claude Desktop configured!"

elif [ "$IDE_CHOICE" = "2" ]; then
    echo "For Cursor, open Settings -> MCP -> Add Command:"
    echo "Name: vibetter"
    echo "Command: $PYTHON_BIN -u \"$INSTALL_DIR/backend/src/server.py\""

elif [ "$IDE_CHOICE" = "3" ]; then
    echo "In your target repository directory, run:"
    echo "claude mcp add vibetter $PYTHON_BIN -u \"$INSTALL_DIR/backend/src/server.py\" -e GEMINI_API_KEY=$API_KEY"
fi

echo ""
echo "🔥 VIBETTER setup is complete! Restart your IDE."
