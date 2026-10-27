# VIBETTER

**Questions about AI-written code, answered from your repo, with every file:line citation it parses checked.**

VIBETTER is an MCP server for Claude Code, Cursor, Claude Desktop and Windsurf. It splits your
repo into line-numbered chunks, retrieves the ones a question needs, and asks the model you
choose to cite `path:L12-L20`. Then it checks each citation without a second model call: the
file must be indexed, the lines must exist, and every cited line must be in the context the
model was shown. It also explains the latest change, diagnoses errors, and draws a dependency graph from
static imports.

[![CI](https://github.com/neerajbhargav/vibetter/actions/workflows/ci.yml/badge.svg)](https://github.com/neerajbhargav/vibetter/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/github/license/neerajbhargav/vibetter)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)

![vibetter ask on ky v2.2.0 with qwen2.5-coder:7b: six citations, each checked](docs/demo.gif)

*A real, uncut recording made with [VHS](https://github.com/charmbracelet/vhs) from [docs/demo.tape](docs/demo.tape): `vibetter ask` on ky v2.2.0 with `--file source/utils/is-network-error.ts`, answered by qwen2.5-coder:7b in local Ollama on an Apple M4 Pro, with the model already loaded. Answers differ between runs. Of 12 takes recorded on 2026-10-26, 8 had citations and all 25 of those verified; 4 had none. This take has the most. The quickstart below shows a failed check. Latency is not benchmarked (see [eval/README.md](eval/README.md)).*

## The problem

AI coding tools ship code faster than you can read it. You accept a diff, the tests pass, and
six weeks later nobody on the team can explain why that file exists.

VIBETTER runs inside the same IDE session, reads the same repo, and gives the model the source
itself rather than a summary. Ask it what changed and why, then check the cited lines.

## Results

The public eval asks 66 questions about three pinned repos (click 8.5.0, requests v2.34.2,
ky v2.2.0), each with gold line spans. Caveats first: the labels come from one pass with no
held-out set; the symbol-matching rule was changed after this set exposed a problem; and the
answer eval uses one small local model, whose memory of these popular repos can help its
key-term recall. Method, all arms and raw results: [eval/README.md](eval/README.md).

The v1 baseline is the `v1.0.0` tag. v1's `scholar_explain` required a file and put it
first. With no file, v1 fell back to the start of the repo walk (60,000 characters for a
question, 30,000 for `debug_error_in_context`), which the "no file" rows reproduce; in all
three repos a changelog or readme filled that before any source file. With the file given,
both versions show most gold lines. So v2's measured gain is for questions asked without a
file, as `vibetter ask` with no `--file` does, and the answer rows below are that case.

| Metric | v1 [95% CI] | v2 [95% CI] | n | Setup | Reproduce |
|---|---|---|---|---|---|
| Gold lines in the context, no file, 24k chars (v2's budget) | 0.000 | 0.542 [0.429, 0.657] | 66 questions | retrieval only, no LLM, commit `c4eb002` | `uv run python -m eval.run --retrieval` |
| Gold lines in the context, no file, 60k chars (v1's budget) | 0.000 | 0.798 [0.706, 0.884] | 66 questions | same | same |
| Gold lines in the context, the question's file given | 0.972 [0.946, 0.993] at 40k | 0.907 [0.842, 0.962] at 24k | 66 questions | file = first gold file (an oracle), commit `35426f1` | `uv run python -m eval.run --retrieval --file-given` |
| Citations that name real lines | 0.669 [0.375, 0.867] | 0.923 [0.885, 0.956] | v1 19 citations, v2 375 (198 answers each) | no file; qwen2.5-coder:7b Q4_K_M, Ollama 0.40.8, 3 runs, re-scored at `35426f1` | `uv run python -m eval.run --llm --rescore eval/results/llm-2026-10-23.json` |
| Citations whose lines the model was all shown | 0.000 | 0.827 [0.767, 0.882] | same | same | same |
| Answers that cite a gold span | 0.000 | 0.353 [0.268, 0.450] | 198 answers per arm | same | same |
| Same, counting only citations of 30 lines or fewer | 0.000 | 0.192 [0.121, 0.268] | 198 answers per arm | same | same |

Retrieval measured 2026-10-23 (no file) and 2026-10-26 (file given). The answers were sampled
on 2026-10-23 (the run started at commit `47bcbf8`; the file records `fccae99`, which differs
only in README files) and re-scored on 2026-10-26 by the current checker, with no model call.
Answer metrics are means of the 3 per-run values; each interval is a bootstrap of the value
pooled over runs, which differs only for v1 validity (pooled 12/19 = 0.632). v1's validity
rests on 19 citations, because v1 cited in 9% of its answers.

What the parts add: BM25 over line-aware chunks alone gets 0.535 at 24k and 0.757 at 60k.
Adding the symbol and path index (the v2 default) changes that by +0.007 [-0.053, 0.068] and
+0.041 [0.000, 0.094]. Most of the gain over v1 comes from retrieving chunks at all. A gold hit
needs only one overlapping line, and many citations name a whole chunk of about 60 lines,
hence the narrower row. With `strict=true`, every remaining parsed citation names shown lines;
the gold-hit rate stays 0.353 and 11% of answers lose all their citations. CI re-runs the
retrieval eval on every push and fails if v2's recall drops more than one point below the
committed baseline.

## Quickstart

Install it and register it with every IDE it finds (Mac and Linux):

```bash
curl -fsSL https://raw.githubusercontent.com/neerajbhargav/vibetter/main/install.sh | bash
```

On Windows, run `iwr -useb https://raw.githubusercontent.com/neerajbhargav/vibetter/main/install.ps1 | iex`
in PowerShell. The installer asks for a provider (local Ollama needs no key), then registers
the server with Claude Code, Cursor, Claude Desktop and Windsurf. Restart the IDE and ask,
for example, "Use vibetter to explain the last change."

No install and no key: `search_code` and `verify_citations` make no model call, and both have
terminal commands. Try them on the test fixture, a small synthetic bookshop (needs
[uv](https://docs.astral.sh/uv/)):

```bash
git clone https://github.com/neerajbhargav/vibetter && cd vibetter/tests/fixtures/shop
uv run vibetter search "how is a discount code applied" --limit 1
printf 'Big discounts raise at shop/cart.py:L24-L25 `raise ValueError`.\nCoupons expire in shop/coupons.py:L12.\n' | uv run vibetter verify
```

The search prints the best chunk, `--- shop/cart.py:L1-L31 ---`, with numbered lines. The
verify command prints the following and exits with status 2, because one citation failed:

```
citations: 2 found, 1 verified (1 valid)
  ok shop/cart.py:L24-L25
  !! shop/coupons.py:L12  (file not indexed)
```

## Connect your IDE

The installer writes these entries for you. To add VIBETTER by hand, or to run it with `uvx`
and no install, use the snippets below. They use local Ollama, which needs no key. For a cloud
provider, swap the extra (`gemini`, `openai` or `anthropic`) and put the key in
`~/.vibetter/.env` (see [.env.example](.env.example)), never in the IDE config.

Claude Code starts the server in your project folder:

```bash
claude mcp add vibetter -s user -e VIBETTER_PROVIDER=ollama -- uvx --from "vibetter[ollama] @ git+https://github.com/neerajbhargav/vibetter" vibetter
```

Cursor (`~/.cursor/mcp.json`, or `.cursor/mcp.json` in a project) and Claude Desktop
(`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS,
`%APPDATA%\Claude\claude_desktop_config.json` on Windows) take the same JSON:

```json
{
  "mcpServers": {
    "vibetter": {
      "command": "uvx",
      "args": ["--from", "vibetter[ollama] @ git+https://github.com/neerajbhargav/vibetter", "vibetter"],
      "env": {
        "VIBETTER_PROVIDER": "ollama",
        "VIBETTER_CODEBASE_PATH": "/path/to/your/project"
      }
    }
  }
}
```

Claude Desktop is not tied to a project, so it needs `VIBETTER_CODEBASE_PATH`. Without it,
VIBETTER refuses to index `/` or your home directory and says so. The installer warns when the
entry has no such path, and keeps the `env` block when you run it again to update. If the app cannot find
`uvx`, use its full path (`which uvx`). After the installer, the command is
`~/.vibetter/venv/bin/vibetter` with no arguments.

---

## Supported providers

| Provider | API key | Default model chain (tried in order) |
|----------|---------|--------------------------------------|
| Google Gemini | Yes ([get key](https://aistudio.google.com/apikey)) | gemini-3.5-flash-lite, gemini-3.8-flash, gemini-3.6-flash |
| OpenAI | Yes ([get key](https://platform.openai.com/api-keys)) | gpt-6-luna, gpt-6.1-sol |
| Anthropic Claude | Yes ([get key](https://console.anthropic.com/settings/keys)) | claude-haiku-5-5, claude-sonnet-5-5 |
| Ollama (local) | No | qwen2.5-coder:7b (`ollama pull qwen2.5-coder:7b` first) |

These are the model IDs as of 2026-10-21; no script in this repo re-checks them. Set `VIBETTER_MODEL`
in `~/.vibetter/.env` to try another model first. A rate limit, server error, connection error
or missing model moves to the next model in the chain; an authentication or request error stops
at once and comes back to the IDE as a tool error.

## Tools

The question tools return structured output: the answer, a checked list of its citations, and
retrieval stats. `strict=true` (or `VIBETTER_STRICT=1`) removes each sentence whose citation
fails and says what it removed.

### `explain_last_change(strict?)`
Explains the latest change: staged and unstaged edits plus new untracked files (what an AI agent
usually creates). On a clean tree it explains the last commit, including a repo's first commit.
Secret files and lockfiles are left out of the diff. Each diff line carries its new-file line
number, and citations are checked against the hunks that were shown.

### `scholar_explain(file_path, question, strict?)`
Answers a question about one file. The context holds that file first, then the chunks of the
rest of the repo that rank best for the question, within a 24,000-character budget. A path that
is not in the index returns an error with the closest matches.
```
scholar_explain("src/auth.js", "Why is the token stored in httpOnly cookies instead of localStorage?")
```

### `debug_error_in_context(error_message, file_path?, strict?)`
Paste an error message. Traceback frames such as `File "app/db.py", line 41` put those exact
chunks first in the context. The model returns the cause and a concrete fix, with checked citations.
```
debug_error_in_context("TypeError: Cannot read properties of undefined (reading 'map')")
```

### `search_code(query, limit?, file_path?)`
Retrieval only, no LLM call and no key. Returns the best chunks with `path:Lstart-Lend` headers
and numbered lines, so a host agent can read and cite them.

### `verify_citations(text, strict?)`
No LLM call. Checks every `path:line` reference it parses in a text against the index: the file exists,
the lines exist, and a code quote placed right after the citation matches those lines. Host
agents can run it on their own answers.

### `generate_blueprint(labels?)`
Builds the file dependency graph from static imports: Python `ast`, plus `import`, `export
... from`, `require()` and `import()` in JS, TS and Vue. The layout is deterministic, so the
same files give the same graph. `labels=true` asks the model to name groups of files; the
edges never come from the model. MCP Apps hosts render `ui://blueprint` inline; other hosts can
open the resource.

### `generate_audio_overview(question, file_path?)`
Writes a spoken MP3 walkthrough to `~/.vibetter/outputs`. It uses gTTS, which sends the
transcript to Google's text-to-speech service.

### From a terminal

```bash
vibetter ask "What does divide() do?" --file src/calc.py   # prints checked citations
vibetter search "where are tokens refreshed"               # no LLM call
vibetter verify answer.md                                  # exit 2 if a citation fails
vibetter index --stats                                     # what is indexed and skipped
```

---

## How it works

```mermaid
flowchart TD
    Q[question or error] --> R
    subgraph local [on your machine]
        I[index: git ls-files, secrets skipped] --> C[line-aware chunks]
        C --> R[BM25 + symbol/path index, fused by RRF, + optional dense arm]
        R --> X[budgeted context: path:L headers, numbered lines]
        P[citation parser] --> V[verifier: file, lines, shown context, quote]
    end
    X -- redacted prompt --> M[model: Ollama or a hosted API]
    M --> P
    V --> O[structured answer: text, checked citations, stats]
```

VIBETTER indexes the files git tracks and splits them into chunks of about 60 lines that end
at function or block boundaries. A question runs through BM25 and a symbol and path index,
and reciprocal rank fusion merges the two rankings, plus a dense ranking when that extra is
installed and `VIBETTER_DENSE=1` is set. The best chunks are packed into a fixed character budget, each line prefixed with
its number, and VIBETTER records exactly which lines it packed. The model's reply goes through
a parser that finds every `path:line` citation, and a verifier that checks each one against
the index and against the packed lines, with no model call. The tool returns the answer with
one verdict per citation. Module-level detail and the full verifier contract are in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Design decisions

- Chose lookup-based citation checks over an LLM judge, because a lookup costs no tokens, gives
  the same verdict on every run, and cannot be argued out of it.
- Chose BM25 plus a symbol and path index over embeddings by default, because the dense arm
  did not help at the 24k budget v2 uses (-0.028, 95% CI -0.154 to +0.097) and lowered recall
  at 60k (-0.162, CI -0.299 to -0.027), on 66 questions
  ([eval/results/retrieval-2026-10-23.json](eval/results/retrieval-2026-10-23.json)). It also
  downloads a model of about 64 MB. Dense is opt-in: the `dense` extra plus `VIBETTER_DENSE=1`.
- Chose line-numbered context with recorded spans over raw file text, because a model cites
  lines reliably only when it sees them numbered (v1 cited in 9% of answers, v2 in 81%), and
  the spans let the verifier tell real lines from lines the model was actually shown.
- Chose static imports over a model-drawn graph, because v1 asked the model for edges and
  positions, which it could invent, while static analysis gives the same graph for the same
  files.
- Chose placeholder citation examples in the prompt over numeric ones, because
  qwen2.5-coder:7b copied a numeric example word for word, and a copied range of real lines
  passes the check.
- Chose one key file, `~/.vibetter/.env` (mode 600), over keys in IDE configs, because IDE
  configs get synced, shared and pasted into bug reports.

## What leaves your machine

The prompt goes to the provider you chose: the prompt template, your question or error
message, and the line-numbered context or diff. With Ollama on localhost, no prompt leaves.
The one exception is `generate_audio_overview`, which sends its transcript to Google's
text-to-speech service. Before sending, VIBETTER skips `.env*`, `*.pem`, `*.key`,
`*credentials*.json`, `id_rsa*` and similar files, and redacts AWS key ids, GitHub tokens,
OpenAI, Anthropic and Google keys, JWTs, private key blocks and
`api_key`/`secret`/`token`/`password` assignments in the remaining text. Redaction is
pattern-based, so treat it as a safety net, not a guarantee. `search_code` hits are redacted
the same way, because the host agent sends them to its own model. Traces stay in
`~/.vibetter/traces.jsonl`; with `VIBETTER_OTEL=1` they also go to the OTLP endpoint you set.

## Limitations

- The check proves that a citation points at real lines the model saw. It does not prove that
  the sentence around it is true. A claim with no citation is not checked; strict mode only
  flags an answer that has no citations at all.
- Small local models do not always cite. In the answer eval, qwen2.5-coder:7b cited in 0.808
  of v2 answers (198 answers), so about one answer in five has nothing to check.
- Only citations the parser finds are checked. It reads `path:L12-L20` and the common variants
  (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)), but not a bare range with no path, such
  as "and L43-L46" after a citation, nor a file named only in prose. A file name with spaces is
  read from its last word. A shorter path completes to the one indexed file that ends with it
  (`cart.py` to `shop/cart.py`), and an invented directory never does; an absolute path from
  another checkout (a traceback) is accepted when its tail names exactly one indexed file.
- Repo text goes into the prompt as data. A file that contains instructions can steer the
  model's answer; the verifier still checks its citations, but not its prose.
- JS, TS and Vue imports come from a regex, not a parser. Imports built at runtime, path
  aliases other than `@/` and `~/`, and other languages are not in the graph. Graphs over 150
  files keep the 150 best connected.
- Retrieval is measured on 66 questions about three repos, labeled once, with no held-out set
  (see [eval/README.md](eval/README.md)). Expect different numbers on your code.

## Development

```bash
uv sync                                          # Python 3.10+, dev tools, provider SDKs
uv run pytest                                    # offline: fake LLM, in-memory MCP client, no keys
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run python -m eval.run --retrieval --gate     # deterministic retrieval eval, no LLM
cd frontend && npm ci && npm run build           # rebuilds src/vibetter/ui
```

CI runs ruff and pyright, builds the wheel, runs pytest on Python 3.10 to 3.14 on Ubuntu and
3.13 on macOS, rebuilds the frontend (which must reproduce the committed `src/vibetter/ui`),
runs `install.sh` twice in a throwaway HOME on Ubuntu and macOS (`tests/installer_smoke.sh`),
parses `install.ps1`, and runs the eval job: the label check plus a retrieval recall gate that
fails if v2's recall drops more than one point below the committed baseline. The answer eval
needs a local Ollama and runs by hand: `uv run python -m eval.run --llm` samples new answers
(about 3 hours), and `--rescore` scores the committed ones again in seconds.
`vhs docs/demo.tape` re-records the demo.

| Path | What it holds |
|---|---|
| `src/vibetter/server.py` | the MCP tools |
| `src/vibetter/index.py`, `chunk.py` | the file index and watcher; line-aware chunks |
| `src/vibetter/retrieve.py` | BM25, symbols, the dense arm, RRF and context assembly |
| `src/vibetter/cite.py` | the citation parser and checker |
| `src/vibetter/graph.py`, `gitdiff.py` | the static import graph; change collection |
| `src/vibetter/providers.py`, `redact.py`, `trace.py` | LLM providers; secret handling; traces |
| `src/vibetter/ide.py`, `cli.py` | IDE config registration; the `vibetter` command |
| `frontend/` | the Vue Flow blueprint UI |
| `tests/` | the offline suite; `tests/fixtures/shop` is a synthetic Python and Vue repo |
| `eval/` | the public eval: datasets, scripts and raw results |
| `docs/` | the architecture notes and the demo |

Changes are listed in [CHANGELOG.md](CHANGELOG.md).

---

## License

MIT. See [LICENSE](LICENSE).

## Author

Built by [Neeraj Bhargav Rondla](https://neerajbhargav.com), applied AI engineer.
More MCP and agent tooling: [context-refinery](https://github.com/neerajbhargav/context-refinery).
