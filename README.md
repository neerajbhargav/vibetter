# VIBETTER — Cognitive Codebase Bridge

VIBETTER is an MCP server that plugs into your AI coding IDE (Claude Code, Cursor, Claude Desktop, Windsurf) and helps you actually **understand** the code your AI tools are generating — in real time, as you build.

Built for vibe coders who want to learn while doing, not just copy-paste.

---

## One-Command Install

### Mac & Linux
```bash
curl -fsSL https://raw.githubusercontent.com/neerajbhargav/vibetter/release/nbr/install.sh | bash
```

### Windows (PowerShell)
```powershell
iwr -useb https://raw.githubusercontent.com/neerajbhargav/vibetter/release/nbr/install.ps1 | iex
```

The installer will:
1. Clone VIBETTER to `~/.vibetter` in the background
2. Set up an isolated Python environment (no global installs, no Docker)
3. Ask for your [free Gemini API key](https://aistudio.google.com/apikey) and verify it works
4. **Auto-detect and register** with every IDE it finds on your system (Claude Code, Cursor, Claude Desktop, Windsurf, VS Code)
5. No restart needed for Claude Code — works immediately

---

## Tools

### `explain_last_change()`
Run this right after your AI tool makes edits. Reads your git diff and explains exactly what changed, why it works, and what programming concepts it demonstrates.

### `scholar_explain(file_path, question)`
Ask any "why" or "how" question about a specific file. Gets a precise, source-grounded answer with exact file:line citations.
```
scholar_explain("src/auth.js", "Why is the token stored in httpOnly cookies instead of localStorage?")
```

### `debug_error_in_context(error_message, file_path?)`
Paste any error message. VIBETTER reads your codebase, finds the exact cause, and gives you a concrete fix — not a generic Stack Overflow answer.
```
debug_error_in_context("TypeError: Cannot read properties of undefined (reading 'map')")
```

### `generate_blueprint()`
Generates an interactive dependency graph of your entire codebase using Gemini's structured output. Open `ui://blueprint` in your IDE to visualize it.

### `generate_audio_overview(question, file_path?)`
Creates an MP3 podcast-style walkthrough of your codebase. Great for understanding architecture away from your screen.
```
generate_audio_overview("How does data flow from the frontend to the database?")
```

---

## How It Works

- **Master Context Engine**: Recursively parses your codebase into a single context payload on startup. A Watchdog observer auto-refreshes it on every file save — so Gemini always sees your latest code.
- **Model Fallback Chain**: If `gemini-2.0-flash-lite` hits quota limits, automatically retries with `gemini-2.5-flash` then `gemini-1.5-flash`. No crashes.
- **Targeted Context**: For file-specific questions, loads the target file first and fills remaining context budget with related files — faster and cheaper than always sending everything.
- **Blueprint Cache**: `generate_blueprint()` caches its result. Opening `ui://blueprint` immediately serves the visualization without a second Gemini call.

---

## Requirements

- Python 3.9+
- Git
- A [free Gemini API key](https://aistudio.google.com/apikey) (1,500 requests/day free)
- Any MCP-compatible IDE: Claude Code, Cursor, Claude Desktop, Windsurf, or VS Code with Roo/Cline

---

## Manual Setup (if needed)

```bash
# 1. Clone
git clone https://github.com/neerajbhargav/vibetter.git ~/.vibetter

# 2. Install deps
cd ~/.vibetter && python3 -m venv venv && venv/bin/pip install -r backend/requirements.txt -q

# 3. Add your key
echo "GEMINI_API_KEY=your_key_here" > backend/.env

# 4. Register with Claude Code
claude mcp add vibetter -s user \
  -e GEMINI_API_KEY=your_key_here \
  -- ~/.vibetter/venv/bin/python -u ~/.vibetter/backend/src/server.py
```

For Cursor / Claude Desktop / Windsurf, add to your `mcp.json`:
```json
{
  "mcpServers": {
    "vibetter": {
      "command": "~/.vibetter/venv/bin/python",
      "args": ["-u", "~/.vibetter/backend/src/server.py"],
      "env": { "GEMINI_API_KEY": "your_key_here" }
    }
  }
}
```
