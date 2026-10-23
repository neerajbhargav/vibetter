# VIBETTER eval

This eval asks two questions about code you did not write:

1. Retrieval: does the context that VIBETTER builds contain the lines that answer the question?
2. Answers: when a local model answers from that context, do its `path:line` citations point at
   real lines, lines it was shown, and the lines that answer the question?

The retrieval eval calls no model and runs in CI as a gate. The answer eval calls a local Ollama
model only. Nothing here calls a paid API.

## Data

Three public repos, pinned by tag and commit. The eval fetches each one at its SHA into
`eval/.cache/` (gitignored) and reads the files as data. Nothing in a checkout is run.

| Repo | Tag | Commit | Language | License |
|---|---|---|---|---|
| [pallets/click](https://github.com/pallets/click) | 8.5.0 | `8b19813f2bfca99f1018a587a8cf54fc959f2e5d` | Python | BSD-3-Clause |
| [psf/requests](https://github.com/psf/requests) | v2.34.2 | `6e83187b8feb273ed4c6cdab5efd8d54901dfab3` | Python | Apache-2.0 |
| [sindresorhus/ky](https://github.com/sindresorhus/ky) | v2.2.0 | `3541888878c4d303a8bc2ad61815f4e048f55a5d` | TypeScript | MIT |

`datasets/questions.jsonl` holds 66 questions, 22 per repo, written by reading the code at these
SHAs. Each question has 1 to 3 gold spans (`path`, `start`, `end`, 1-based and inclusive; 84 in
all) and 1 to 3 key terms that the gold lines contain. The questions are in plain English, the
way a developer asks about code they are reading, for example "What stops requests from
following redirects forever?".

`python -m eval.check_labels` asserts that each tag still resolves to its pinned SHA, that every
gold span exists at that SHA, and that every key term appears in its gold lines. CI runs it.

## Retrieval eval

Each arm packs context into the same character budget. Two budgets: 24,000 characters (what
`scholar_explain` uses) and 60,000 (what v1 used for a question with no target file).

| Arm | Context |
|---|---|
| A | v1 behaviour from `main`: every file with an allowed suffix in walk order, cut at the budget, no line numbers |
| B | BM25 over line-aware chunks |
| C | BM25 + symbol/path index, fused by reciprocal rank fusion (the v2 default) |
| D | C + dense embeddings (`fastembed`, `BAAI/bge-small-en-v1.5`), only when the `dense` extra is installed |

B, C and D add the first chunk of every file after the ranked chunks, as the server does, so
they differ only in ranking.

Metrics, per question, then averaged:

- **Recall**: the share of gold lines that appear complete in the context.
- **MRR**: 1/rank of the first context block that overlaps a gold span, 0 if none. A block is a
  file for arm A and a chunk for B, C and D.
- **Any gold**: the share of questions with at least one gold line in the context.

95% CIs are percentile bootstrap intervals over questions (10,000 resamples, seed 0). Arm
differences are paired over the same questions.

### Results

66 questions, 3 repos, `eval/results/retrieval-2026-10-23.json`, vibetter commit `c4eb002`,
2026-10-23. Deterministic: the same command gives the same numbers.

| Arm | Budget | Recall [95% CI] | MRR [95% CI] | Any gold |
|---|---|---|---|---|
| A (v1) | 24k | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 |
| B | 24k | 0.535 [0.421, 0.650] | 0.274 [0.194, 0.361] | 0.576 |
| C (v2) | 24k | 0.542 [0.429, 0.657] | 0.287 [0.204, 0.376] | 0.591 |
| D | 24k | 0.514 [0.397, 0.628] | 0.302 [0.212, 0.394] | 0.561 |
| A (v1) | 60k | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 |
| B | 60k | 0.757 [0.655, 0.851] | 0.288 [0.212, 0.374] | 0.788 |
| C (v2) | 60k | 0.798 [0.706, 0.884] | 0.304 [0.225, 0.391] | 0.833 |
| D | 60k | 0.636 [0.520, 0.748] | 0.309 [0.220, 0.400] | 0.667 |

Paired recall differences: C minus B is +0.007 [-0.053, 0.068] at 24k and +0.041
[0.000, 0.094] at 60k. D minus C is -0.028 [-0.154, 0.097] at 24k and -0.162 [-0.299, -0.027]
at 60k.

What the numbers say:

- v1 shows no gold line at either budget. Its walk reaches the root files first, and in all
  three repos a changelog or readme fills the budget before any source file
  (`CHANGES.md`, `HISTORY.md`, `readme.md`).
- Retrieval puts at least one gold line in the 24k context for 59% of questions, and in the
  60k context for 83%.
- The dense arm does not help on this set. At 60k it lowers recall by 16 points against C.
  It stays optional and off unless installed.

### The symbol arm, before and after

The first run, at commit `e86434e`, found the shipped default (C) worse than BM25 alone:
recall 0.312 [0.206, 0.421] against 0.535 at 24k, and 0.468 against 0.757 at 60k
(`results/retrieval-2026-10-23-before-symbol-fix.json`). English words in a question, such as
"redirect" or "timeout", matched parts of definition names and pulled every `test_redirect_*`
and `test_timeout_*` function into the symbol ranking, which RRF weighs as much as BM25.

The symbol arm now matches only identifiers written as code: snake_case, camelCase, dotted
names, calls, keyword arguments and backticked names. Paths and traceback frames count as
before. That raised C to 0.542 and 0.798. This change was chosen after this set showed the
problem, and there is no held-out set yet, so treat the gain over B as unconfirmed until a new
set measures it.

### CI gate

`python -m eval.run --retrieval --gate` runs arms A to C and fails when arm C recall at either
budget falls more than 0.01 below `results/retrieval-baseline.json`. The CI `eval` job runs it
on every push and pull request, after the label check.

## Commands

```bash
uv sync --locked
uv run python -m eval.check_labels                     # labels against the pinned SHAs
uv run python -m eval.run --retrieval --gate           # arms A-C, the CI gate, about 30 s
uv sync --locked --extra dense                         # optional: arm D
uv run --extra dense python -m eval.run --retrieval    # arms A-D, writes results/retrieval-<date>.json
uv run python -m eval.run --retrieval --set-baseline   # also rewrites the gate baseline
```

The first eval command fetches the three repos at depth 1 (about 13 MB on disk). Arm D
downloads the embedding model (about 64 MB) to `~/.vibetter/models` on first use.

## Caveats

- The questions and gold spans come from one labeling pass. There is no second labeler and no
  agreement score. A gold span marks where the answer is, so a context that answers from other lines
  scores zero.
- The symbol fix was designed after seeing these results (see above).
- v1 walked the file system in whatever order it returned. Arm A sorts names at each level so
  the run is the same on every machine. Another order would show different files, but the
  changelogs and readmes at the root would still come first.
- 66 questions give wide intervals: a difference of a few points is inside the noise.
- Result files record the vibetter commit the run started from, and whether tracked files
  outside `eval/results` differed from it.
