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

## Answer eval (local model)

The same 66 questions, answered by `qwen2.5-coder:7b` (Q4_K_M, digest `dae161e27b0e`) on
Ollama 0.40.8 with its default sampling (no seed), 3 runs per arm. Every arm gets a
24,000-character context.

| Arm | Context and prompt |
|---|---|
| v1 | v1's context (arm A, no line numbers) and v1's `scholar_explain` prompt, copied verbatim from `main` |
| v2 | the `scholar_explain` path: line-numbered retrieved context (arm C) and the v2 prompt |
| v2-strict | the v2 replies after strict verification, which drops each sentence whose citation fails |

Strict mode changes no prompt, so v2-strict scores the same replies as v2 after the strict
filter and adds no model call. Both v1 and v2 go through `vibetter.providers`, which sizes
Ollama's `num_ctx` to the prompt. v1 sent no `num_ctx`, so Ollama would have cut the start of
its prompt; the eval does not reproduce that bug.

`vibetter.cite` scores every reply, with no model in the loop:

- **Citation validity**: valid citations / all citations. Valid means the file exists in the
  repo and the cited lines exist.
- **Groundedness**: valid citations whose lines were in the context the model saw / all
  citations.
- **Gold-hit rate**: the share of answers with a valid citation that overlaps a gold span.
- **Key-term recall**: the mean share of the question's key terms that appear in the answer.
- **Cited answers**: the share of answers with at least one citation.

### Results

66 questions x 3 runs = 198 answers per arm, `eval/results/llm-2026-10-23.json`, 2026-10-23.
The run started at vibetter commit `47bcbf8`; the file records `fccae99`, read when the run
ended, which differs only in README files. Each cell is the mean over 3 runs with a bootstrap
95% CI over questions; the per-run values are in the file.

| Metric | v1 | v2 | v2-strict |
|---|---|---|---|
| Citation validity | 0.653 [0.357, 0.850] | 0.922 [0.884, 0.955] | 1.000 (by construction) |
| Groundedness | 0.000 [0.000, 0.000] | 0.837 [0.778, 0.890] | 1.000 (by construction) |
| Gold-hit rate | 0.000 [0.000, 0.000] | 0.343 [0.258, 0.434] | 0.343 [0.258, 0.434] |
| Key-term recall | 0.264 [0.200, 0.327] | 0.455 [0.375, 0.536] | 0.450 [0.369, 0.531] |
| Cited answers | 0.086 [0.045, 0.131] | 0.798 [0.737, 0.859] | 0.707 [0.636, 0.773] |
| Citations per answer | 0.09 | 1.88 | 1.58 |

What the numbers say:

- v1 rarely cites (9% of answers), and none of its citations point at lines it was shown:
  its context holds no source code, so the few file:line references are recalled or guessed.
  Its validity of 0.653 rests on about 6 citations per run, hence the wide interval.
- v2 cites in 80% of answers. 92% of its citations name real lines and 84% name lines it
  was shown. One answer in three cites a gold span.
- Strict mode removes every citation that fails, at a small cost: the gold-hit rate is
  unchanged, key-term recall falls by half a point, and 9% of answers lose all their
  citations.
- Run-to-run spread is large. The v2 gold-hit rate was 0.273, 0.348 and 0.409 on the three
  runs, so a single run can mislead by several points.

## Commands

```bash
uv sync --locked
uv run python -m eval.check_labels                     # labels against the pinned SHAs
uv run python -m eval.run --retrieval --gate           # arms A-C, the CI gate, about 30 s
uv sync --locked --extra dense                         # optional: arm D
uv run --extra dense python -m eval.run --retrieval    # arms A-D, writes results/retrieval-<date>.json
uv run python -m eval.run --retrieval --set-baseline   # also rewrites the gate baseline
ollama pull qwen2.5-coder:7b                           # the answer eval needs a local Ollama
uv run python -m eval.run --llm                        # 3 runs x 2 arms x 66 questions, writes results/llm-<date>.json
uv run python -m eval.run --llm --runs 1 --limit 1     # a quick check: 3 questions, 6 model calls
```

The first eval command fetches the three repos at depth 1 (about 13 MB on disk). Arm D
downloads the embedding model (about 64 MB) to `~/.vibetter/models` on first use. The answer
eval made 390 model calls in about 3 hours on an Apple M4 Pro that was also running other
work (the other 6 replies came from the cache of a smoke test with the same prompts). Replies
are cached under `eval/.cache/llm`, so an interrupted run resumes.

## Caveats

- The questions and gold spans come from one labeling pass. There is no second labeler and no
  agreement score. A gold span marks where the answer is, so a context that answers from other lines
  scores zero.
- The symbol fix was designed after seeing these results (see above).
- v1 walked the file system in whatever order it returned. Arm A sorts names at each level so
  the run is the same on every machine. The order does not change the result here: `os.walk`
  lists the root's files first, and in each repo those alone exceed 60,000 characters.
- These repos are popular, so the model may know them from training. Key-term recall can
  come from that memory; groundedness and gold hits cannot, because they check lines.
- A gold hit needs only an overlap. Some v2 citations name a whole chunk (about 60 lines), so
  a hit says the model pointed at the right region, not at the exact lines.
- Groundedness checks that cited lines were shown, not that the sentence is true. No metric
  here judges correctness of the prose.
- One 7B model, quantized, on one machine. Larger or hosted models will score differently.
  The timings in the results file reflect a shared machine and are not a latency benchmark.
- 66 questions give wide intervals: a difference of a few points is inside the noise.
- Result files record the vibetter commit the run started from, and whether tracked files
  outside `eval/results` differed from it.
