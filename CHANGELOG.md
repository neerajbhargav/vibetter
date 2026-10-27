# Changelog

## 2.0.0 (unreleased)

v2 turns VIBETTER from a prompt wrapper into a grounded Q&A server: answers come from retrieved,
line-numbered code, and every `path:line` citation in an answer is checked. Measured results
and their caveats are in [eval/README.md](eval/README.md).

### Added

- Line-aware chunking: about 60 lines per chunk, at most 120, cut at Python `def` and `class`
  lines or at blank lines outside braces.
- Retrieval: BM25 over a code-aware tokenizer and a symbol and path index, fused by reciprocal
  rank fusion. An optional dense arm (`vibetter[dense]`, fastembed) is off unless
  `VIBETTER_DENSE=1`, because it lowered recall in the eval.
- A citation parser and checker. Each citation comes back valid (the file and lines exist),
  grounded (the model was shown those lines) and quote-matched (a quoted snippet appears in
  the cited lines). `strict=true` removes sentences whose citation fails.
- Structured tool output: `{answer, citations, stats}` from `scholar_explain`,
  `debug_error_in_context` and `explain_last_change`.
- Two tools with no LLM call: `search_code` and `verify_citations`.
- The `vibetter` command: `serve`, `ask`, `search`, `verify` (exit status 2 when a citation
  fails) and `index --stats`.
- A dependency graph built from static imports (Python `ast`, JS, TS and Vue import parsing)
  with a deterministic layout. `labels=true` asks the model only to name groups of files.
  `generate_blueprint` links `ui://blueprint` for MCP Apps hosts.
- Secret redaction on every outgoing prompt and on `search_code` hits, and a list of secret
  files that are never read.
- JSONL traces per tool call, with optional OpenTelemetry export (`vibetter[otel]`).
- An offline test suite (fake LLM, in-memory MCP client, synthetic fixture repo) and CI: ruff,
  pyright, pytest on Python 3.10 to 3.13, the wheel build, the frontend build check and
  installer syntax checks.
- A public eval: 66 questions with gold line spans over click 8.5.0, requests v2.34.2 and
  ky v2.2.0. The retrieval eval runs in CI as a recall gate against a committed baseline; the
  answer eval runs locally on Ollama, 3 runs per arm. Raw results are in `eval/results/`.
- A demo recording (`docs/demo.tape`, `docs/demo.gif`) and `docs/ARCHITECTURE.md`.

### Changed

- The server is an installable package, `src/vibetter`, with `pyproject.toml`, bounded
  dependency ranges and `uv.lock`. Provider SDKs are extras. The built UI ships as package data.
- Settings load from `~/.vibetter/.env`. The installers store the API key there once and give
  IDE configs only the `vibetter` command.
- The index uses `git ls-files`, so `.gitignore` applies, and skips lockfiles, minified
  bundles, binaries, files over 1 MB and secret files, with reasons.
- The index is built on the first tool call instead of at import, so the MCP handshake does
  not wait for it. The watcher re-reads only the files that changed.
- `explain_last_change` includes untracked files, works before the first commit, numbers each
  diff line, and checks citations against the hunks shown.
- Provider model IDs were updated (checked 2026-10-21). Ollama defaults to qwen2.5-coder:7b.
  Provider errors are classified by exception type and HTTP status and reach the host as MCP
  tool errors.
- The prompts' citation examples use placeholders, because a small model copied a numeric
  example word for word and the copy passed the check.

### Fixed

- Ollama requests set `num_ctx` to fit the prompt. Before, Ollama kept its small default window
  and dropped the start of a long prompt, where the code sits, without an error.
- The JSON config registration backs up each file and leaves a config it cannot parse
  unchanged, instead of replacing it. Re-running the installer keeps an entry's `env`
  (such as `VIBETTER_CODEBASE_PATH`) minus any API key, writes through a symlinked config,
  never overwrites the first backup, and warns when Claude Desktop has no project path.
- The frontend lockfile works with `npm ci` again, and the build reproduces the committed UI.
- Citations written with spaces (`path L12-L20`) and quotes after a bracketed citation are
  parsed. Mixed Python from-imports keep the package edge in the graph.

### Removed

- The model-drawn dependency graph: edges now come only from static imports.
- The `~/.vscode/mcp.json` write in the installers. VS Code does not read MCP servers from
  that file. The installers now delete a v1 entry there, because it held the API key.
- Unused Vite template files, the unused `icons.svg` and a `.dockerignore` with no Dockerfile.

## 1.x

The `main` branch before v2: five tools that sent a character-truncated slice of the repo to
the chosen provider, with no citation checks.
