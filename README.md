# VIBETTER

**Understand the code your AI just wrote.**

VIBETTER is an MCP server for Claude Code, Cursor, Claude Desktop and Windsurf. It indexes your
repo, sends line-numbered source to the model you choose, and asks for answers that cite
`path:line`. It explains the latest change (including new untracked files), answers questions
about a file, diagnoses errors in context, and draws a model-inferred dependency graph.
The citations are requested in the prompt and the model sees real line numbers, but VIBETTER
does not yet check them. Verify them against the source.

[![CI](https://github.com/neerajbhargav/vibetter/actions/workflows/ci.yml/badge.svg)](https://github.com/neerajbhargav/vibetter/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/github/license/neerajbhargav/vibetter)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)

## The problem

AI coding tools ship code faster than you can read it. You accept a diff, the tests pass, and
six weeks later nobody on the team can explain why that file exists.

VIBETTER runs inside the same IDE session, reads the same repo, and gives the model the source
itself rather than a summary. Ask it what changed and why, then check the cited lines.

---

## Install

### Mac and Linux
```bash
curl -fsSL https://raw.githubusercontent.com/neerajbhargav/vibetter/main/install.sh | bash
```

### Windows (PowerShell)
```powershell
iwr -useb https://raw.githubusercontent.com/neerajbhargav/vibetter/main/install.ps1 | iex
```

The installer:
1. Clones VIBETTER to `~/.vibetter` and installs it into its own virtualenv (`~/.vibetter/venv`).
2. Asks for a provider (Gemini, OpenAI, Anthropic or local Ollama) and, for a cloud provider,
   the API key. Input is hidden.
3. Stores the key once, in `~/.vibetter/.env` (mode 600 on Mac and Linux). IDE configs get only
   the `vibetter` command, never the key.
4. Registers the server with Claude Code (`claude mcp add`), Cursor, Claude Desktop and Windsurf
   when it finds them. It backs up each JSON config first. A config it cannot parse (for example
   one with comments) is left unchanged, and the installer prints the manual step instead.

For a non-interactive install, set `VIBETTER_PROVIDER` and the key variable first, for example
`VIBETTER_PROVIDER=ollama`, or `VIBETTER_PROVIDER=openai OPENAI_API_KEY=...`.

### With uv
```bash
uvx --from "vibetter[openai] @ git+https://github.com/neerajbhargav/vibetter" vibetter --version
```
Put the provider settings in `~/.vibetter/.env` (see `.env.example`). In the IDE config, the
command is `uvx` with the arguments `--from`, `vibetter[openai] @ git+https://github.com/neerajbhargav/vibetter`
and `vibetter`.

---

## Supported providers

| Provider | API key | Default model chain (tried in order) |
|----------|---------|--------------------------------------|
| Google Gemini | Yes ([get key](https://aistudio.google.com/apikey)) | gemini-3.5-flash-lite, gemini-3.8-flash, gemini-3.6-flash |
| OpenAI | Yes ([get key](https://platform.openai.com/api-keys)) | gpt-6-luna, gpt-6.1-sol |
| Anthropic Claude | Yes ([get key](https://console.anthropic.com/settings/keys)) | claude-haiku-5-5, claude-sonnet-5-5 |
| Ollama (local) | No | qwen2.5-coder:7b (`ollama pull qwen2.5-coder:7b` first) |

Model IDs were checked against each provider's model list on 2026-10-21. Set `VIBETTER_MODEL`
in `~/.vibetter/.env` to try another model first. A rate limit, server error, connection error
or missing model moves to the next model in the chain; an authentication or request error stops
at once and comes back to the IDE as a tool error.

---

## Tools

### `explain_last_change()`
Explains the latest change: staged and unstaged edits plus new untracked files (what an AI agent
usually creates). On a clean tree it explains the last commit, including a repo's first commit.
Secret files and lockfiles are left out of the diff.

### `scholar_explain(file_path, question)`
Answers a question about one file. The file comes first in the context, then files in the same
directory, then the rest of the repo by path, all line-numbered, within a 40,000-character budget.
A path that is not in the index returns an error with the closest matches.
```
scholar_explain("src/auth.js", "Why is the token stored in httpOnly cookies instead of localStorage?")
```

### `debug_error_in_context(error_message, file_path?)`
Paste an error message. VIBETTER supplies codebase context and asks the model for the cause and
a concrete fix. Verify the diagnosis and the cited lines.
```
debug_error_in_context("TypeError: Cannot read properties of undefined (reading 'map')")
```

### `generate_blueprint()`
Asks the model for a file dependency graph from the first 50,000 characters of line-numbered
context. The graph is model-inferred, not static analysis. Open `ui://blueprint` in your IDE to
view it.

### `generate_audio_overview(question, file_path?)`
Writes a spoken MP3 walkthrough to `~/.vibetter/outputs`. It uses gTTS, which sends the
transcript to Google's text-to-speech service.

---

## How it works

- **Index.** In a git repo the file list comes from `git ls-files -co --exclude-standard`, so
  `.gitignore` applies. Outside git, a walk honors each directory's `.gitignore`. Lockfiles,
  minified bundles, binaries, files over 1 MB and secret files are skipped; `vibetter index
  --stats` shows what was skipped and why.
- **Startup.** The index is built on the first tool call (or in a background thread when the
  server starts), not at import, so the MCP handshake does not wait for it.
- **Freshness.** A file watcher waits until saves stop for 0.3 s (at most 5 s), then re-reads
  only the files that were created, modified, deleted or moved.
- **Codebase root.** `VIBETTER_CODEBASE_PATH`, else the directory the IDE starts the server in.
  If that is `/` or your home directory, VIBETTER refuses to index it and tells you to set
  `VIBETTER_CODEBASE_PATH` in the server config.
- **Errors.** Provider and lookup failures are MCP tool errors (`isError`), not answer text.

## What leaves your machine

The prompt goes to the provider you chose: the prompt template, your question or error
message, and the line-numbered context or diff. With Ollama on localhost, nothing leaves. Before sending, VIBETTER
skips `.env*`, `*.pem`, `*.key`, `*credentials*.json`, `id_rsa*` and similar files, and
redacts AWS key ids, GitHub tokens, OpenAI, Anthropic and Google keys, JWTs, private key blocks
and `api_key`/`secret`/`token`/`password` assignments in the remaining text. Redaction is
pattern-based, so treat it as a safety net, not a guarantee. Repo text goes into the prompt as
data; a file that contains instructions can still steer the model's answer.

---

## Requirements

- Python 3.10 or newer, and git
- An API key for your chosen provider, or Ollama installed locally
- An MCP client: Claude Code, Cursor, Claude Desktop, Windsurf, or any other MCP host

## Manual setup

```bash
git clone https://github.com/neerajbhargav/vibetter.git ~/.vibetter
python3 -m venv ~/.vibetter/venv
~/.vibetter/venv/bin/pip install -e "$HOME/.vibetter[openai]"   # or gemini, anthropic, ollama
printf 'VIBETTER_PROVIDER=openai\nOPENAI_API_KEY=your_key_here\n' > ~/.vibetter/.env
chmod 600 ~/.vibetter/.env
claude mcp add vibetter -s user -- ~/.vibetter/venv/bin/vibetter
```

For Cursor, Claude Desktop or Windsurf, add this to the IDE's MCP JSON config, with the full
path to the command:
```json
{
  "mcpServers": {
    "vibetter": {
      "command": "/Users/you/.vibetter/venv/bin/vibetter"
    }
  }
}
```

From a terminal:
```bash
vibetter ask "What does divide() do?" --file src/calc.py
vibetter index --stats
```

## Development

```bash
uv sync                      # Python 3.10+, dev tools and all provider SDKs
uv run pytest                # offline: fake LLM, in-memory MCP client, no keys
uv run ruff check . && uv run ruff format --check . && uv run pyright
cd frontend && npm ci && npm run build   # rebuilds src/vibetter/ui
```

CI runs ruff and pyright, pytest on Python 3.10 to 3.13, the frontend build (which must
reproduce the committed `src/vibetter/ui`), and syntax checks for both installers.

Repo map: `src/vibetter/` is the package (`server.py` tools, `index.py` file index and
watcher, `gitdiff.py` change collection, `providers.py` LLM providers, `redact.py` secret
handling, `ide.py` IDE config registration, `cli.py` the `vibetter` command). `frontend/` is
the Vue Flow blueprint UI. `tests/` holds the offline suite.

---

## License

MIT. See [LICENSE](LICENSE).

## Author

Built by [Neeraj Bhargav Rondla](https://neerajbhargav.com), applied AI engineer.
More MCP and agent tooling: [omni-context](https://github.com/neerajbhargav/omni-context),
[context-refinery](https://github.com/neerajbhargav/context-refinery).
