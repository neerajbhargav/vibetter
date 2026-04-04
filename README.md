# VIBETTER: Cognitive Codebase Blueprint

Welcome to the future of vibe-coding infrastructure! VIBETTER acts as a massive 2M+ Context Bridge between your codebase and Gemini 3.1 Pro, providing Interactive Vue Flow architectures and Multimodal Audio codebase podcasts natively inside your IDE.

## The "One-Command" Seamless Install

Forget downloading zip files or debugging Docker containers. Just paste this one command into your terminal to instantly install and configure VIBETTER. It will download to a hidden background system path (`~/.vibetter`) and prompt you intuitively!

### Mac & Linux
```bash
curl -fsSL https://raw.githubusercontent.com/neerajbhargav/vibetter/main/install.sh | bash
```

### Windows (PowerShell)
```powershell
iwr -useb https://raw.githubusercontent.com/neerajbhargav/vibetter/main/install.ps1 | iex
```

## What Happens During Install?
1. **Hidden Install**: The repository clone happens entirely in the background into `~/.vibetter` or `%USERPROFILE%\.vibetter`.
2. **Wizard Prompt**: It will ask for your Google Gemini (AI Studio) API Key and securely sandbox it inside an ignored `.env` file.
3. **IDE Magic**: The script automatically injects the exact FastMCP configuration JSON mapping directly into Claude Desktop or tells you the one-liner for Claude Code/Cursor.
4. **Lightning Fast VENV**: Auto builds an isolated Python `venv` environment safely for dependencies without messing with your OS global interpreter. No Docker. No global installs. No NPM builds required (the frontend is pre-compiled).

## Features Included

- **Native Tooling (`ui://blueprint`)**: Connects an interactive map of your active repository directly from the MCP Server to the IDE.
- **Multimodal Podcasts**: Call the `generate_audio_overview` tool and VIBETTER processes your complex codebase, generating a `.mp3` audio transcript directly to your local file system for playback!
