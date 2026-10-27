"""Deterministic retrieval eval: how much of the gold code each arm puts in the context.

Arms, all packed into the same character budget:
  A  v1 with no file given: files in walk order, the first `budget` characters
     (v1.0.0's fallback when scholar_explain got no file; see file_given() for the rest)
  B  BM25 over line-aware chunks
  C  BM25 + symbol/path index, fused by RRF (what v2 ships)
  D  C + the dense arm, only when the `dense` extra is installed

B, C and D append the first chunk of every file after the ranked chunks, as
the server does, so they differ only in ranking. No LLM is called.
"""

from __future__ import annotations

import json
import platform
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from vibetter.index import CodebaseIndex
from vibetter.retrieve import (
    Chunk,
    Embedder,
    Retriever,
    _ranked,
    assemble,
    fastembed_embedder,
    tokenize,
)
from vibetter.server import Vibetter

from .common import (
    EVAL_DIR,
    RESULTS,
    Question,
    Span,
    bootstrap,
    checkouts,
    git_dirty,
    git_head,
    gold_recall,
    hits_gold,
    load_questions,
    load_repos,
    mean,
    v1_context,
    v1_files,
    v1_targeted_context,
)

BUDGETS = (24_000, 60_000)
V1_TARGET_CHARS = 40_000  # v1's get_targeted_context() default
ARMS = {
    "A": "v1: walk order, first N characters, no line numbers",
    "B": "BM25 over line-aware chunks",
    "C": "BM25 + symbol/path index, RRF (v2 default)",
    "D": "C + dense embeddings (fastembed BAAI/bge-small-en-v1.5)",
}
BASELINE = RESULTS / "retrieval-baseline.json"
TOLERANCE = 0.01  # recall may fall by at most one point before the gate fails


def first_gold_rank(q: Question, blocks: Sequence[tuple[str, int, int]]) -> int | None:
    """1-based position of the first context block that overlaps a gold span."""
    for rank, (path, start, end) in enumerate(blocks, 1):
        if hits_gold(q, path, start, end):
            return rank
    return None


def packed(chunks: Sequence[Chunk], shown: dict[str, list[Span]]) -> list[tuple[str, int, int]]:
    """The chunks that made it into the context, in ranked order.

    assemble() packs whole chunks or skips them, so a chunk is in the context
    exactly when one shown span of its file contains it.
    """
    out, seen = [], set()
    for c in chunks:
        key = (c.path, c.start, c.end)
        if key in seen:
            continue
        if any(s <= c.start and c.end <= e for s, e in shown.get(c.path, ())):
            out.append(key)
            seen.add(key)
    return out


def ranked_context(
    r: Retriever, ranked: list[Chunk], budget: int
) -> tuple[dict[str, list[Span]], list[tuple[str, int, int]], int]:
    chunks = ranked + r.heads()
    context, shown, _ = assemble(r.files, chunks, budget)
    return shown, packed(chunks, shown), len(context)


def run_repo(
    root: Path,
    questions: list[Question],
    arms: Sequence[str],
    budgets: Sequence[int],
    embedder: Embedder | None = None,
) -> list[dict[str, Any]]:
    index = CodebaseIndex(root)
    index.build()
    lexical = Retriever(index.files)
    dense = Retriever(index.files, embedder=embedder) if "D" in arms else lexical
    retriever = {"B": lexical, "C": lexical, "D": dense}

    def by_bm25(q: str) -> list[Chunk]:
        return [lexical.chunks[i] for i in _ranked(lexical.bm25.scores(tokenize(q)))]

    rankers: dict[str, Callable[[str], list[Chunk]]] = {
        "B": by_bm25,
        "C": lambda q: [h.chunk for h in lexical.search(q)],
        "D": lambda q: [h.chunk for h in dense.search(q)],
    }
    old = v1_files(root) if "A" in arms else []

    rows: list[dict[str, Any]] = []
    for q in questions:
        ranked = {arm: rankers[arm](q.question) for arm in arms if arm != "A"}
        for budget in budgets:
            for arm in arms:
                if arm == "A":
                    context, shown = v1_context(old, budget)
                    blocks = [(p, s, e) for p, spans in shown.items() for s, e in spans]
                    chars = len(context)
                else:
                    shown, blocks, chars = ranked_context(retriever[arm], ranked[arm], budget)
                rank = first_gold_rank(q, blocks)
                rows.append(
                    {
                        "id": q.id,
                        "repo": q.repo,
                        "arm": arm,
                        "budget": budget,
                        "recall": round(gold_recall(q, shown), 6),
                        "rank": rank,
                        "blocks": len(blocks),
                        "context_chars": chars,
                    }
                )
    return rows


FILE_ARMS = {
    "A+file": "v1 scholar_explain: the target file whole, then whole files in walk order"
    " up to 40,000 characters",
    "C+file": "v2 scholar_explain: the target file's chunks first, then ranked chunks",
}


def file_given(budgets: Sequence[int] = (24_000, 40_000)) -> dict:
    """Recall when the question comes with its file, as scholar_explain requires.

    The file is the question's first gold file, so this is an oracle: it shows what
    each version does with the right file, not how often a user picks it.
    """
    vibetter_root = EVAL_DIR.parent
    commit, dirty = git_head(vibetter_root), git_dirty(vibetter_root)  # read before the run
    roots, questions = checkouts(), load_questions()
    rows: list[dict[str, Any]] = []
    for repo in load_repos():
        root = roots[repo["name"]]
        old, app = v1_files(root), Vibetter(root, embedder=False)
        for q in (x for x in questions if x.repo == repo["name"]):
            target = q.gold[0].path
            runs = [("A+file", V1_TARGET_CHARS, v1_targeted_context(old, target)[1])]
            runs += [("C+file", b, app._gather(q.question, target, b)[2]) for b in budgets]
            for arm, budget, shown in runs:
                recall = round(gold_recall(q, shown), 6)
                rows.append(
                    {"id": q.id, "repo": q.repo, "arm": arm, "budget": budget, "recall": recall}
                )
    summary: dict[str, Any] = {}
    for arm, budget in dict.fromkeys((r["arm"], r["budget"]) for r in rows):
        mine = [r["recall"] for r in rows if r["arm"] == arm and r["budget"] == budget]
        ci = bootstrap(len(mine), lambda ix, xs=mine: mean([xs[i] for i in ix]))
        summary[f"{arm}@{budget}"] = {
            "n": len(mine),
            "recall": round(mean(mine), 4),
            "recall_ci95": [round(x, 4) for x in ci],
            "any_gold_in_context": round(mean([x > 0 for x in mine]), 4),
        }
    return {
        "eval": "retrieval-file-given",
        "vibetter_commit": commit,
        "vibetter_dirty": dirty,
        "python": platform.python_version(),
        "repos": load_repos(),
        "questions": len(questions),
        "target": "the question's first gold file (an oracle choice)",
        "arms": FILE_ARMS,
        "budgets_chars": {"A+file": V1_TARGET_CHARS, "C+file": list(budgets)},
        "metrics": {
            "recall": "share of gold lines that appear complete in the context",
            "any_gold_in_context": "share of questions with at least one gold line shown",
            "ci95": "percentile bootstrap over questions, 10,000 resamples, seed 0",
        },
        "summary": summary,
        "rows": rows,
    }


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    recalls = [r["recall"] for r in rows]
    rr = [1 / r["rank"] if r["rank"] else 0.0 for r in rows]
    n = len(rows)

    def ci(xs: list[float]) -> list[float]:
        return [round(x, 4) for x in bootstrap(n, lambda ix: mean([xs[i] for i in ix]))]

    return {
        "n": n,
        "recall": round(mean(recalls), 4),
        "recall_ci95": ci(recalls),
        "mrr": round(mean(rr), 4),
        "mrr_ci95": ci(rr),
        "any_gold_in_context": round(mean([r["recall"] > 0 for r in rows]), 4),
    }


def _delta(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> dict[str, Any]:
    """Paired recall difference b - a over the same questions, with a bootstrap CI."""
    diffs = [y["recall"] - x["recall"] for x, y in zip(a, b, strict=True)]
    ci = bootstrap(len(diffs), lambda ix: mean([diffs[i] for i in ix]))
    return {"recall_diff": round(mean(diffs), 4), "ci95": [round(x, 4) for x in ci]}


def summarize(rows: list[dict[str, Any]], arms: Sequence[str], budgets: Sequence[int]) -> dict:
    summary: dict[str, Any] = {}
    for budget in budgets:
        per: dict[str, Any] = {}
        for arm in arms:
            mine = [r for r in rows if r["arm"] == arm and r["budget"] == budget]
            per[arm] = _stats(mine)
            per[arm]["by_repo"] = {
                repo: _stats([r for r in mine if r["repo"] == repo])
                for repo in dict.fromkeys(r["repo"] for r in mine)
            }
        of = {a: [r for r in rows if r["arm"] == a and r["budget"] == budget] for a in arms}
        for i, arm in enumerate(arms):
            for other in arms[:i]:  # every earlier arm, paired by question
                per[arm][f"vs_{other}"] = _delta(of[other], of[arm])
        summary[str(budget)] = per
    return summary


def run(arms: Sequence[str] = ("A", "B", "C", "D"), budgets: Sequence[int] = BUDGETS) -> dict:
    vibetter_root = EVAL_DIR.parent
    commit, dirty = git_head(vibetter_root), git_dirty(vibetter_root)  # read before the run
    arms = list(arms)
    skipped: dict[str, str] = {}
    embedder = fastembed_embedder() if "D" in arms else None
    if "D" in arms and embedder is None:
        arms.remove("D")
        skipped["D"] = "the dense extra is not installed (uv sync --extra dense)"
    roots = checkouts()
    questions = load_questions()
    rows: list[dict[str, Any]] = []
    for repo in load_repos():
        mine = [q for q in questions if q.repo == repo["name"]]
        rows += run_repo(roots[repo["name"]], mine, arms, budgets, embedder)
    return {
        "eval": "retrieval",
        "vibetter_commit": commit,
        "vibetter_dirty": dirty,
        "python": platform.python_version(),
        "repos": load_repos(),
        "questions": len(questions),
        "budgets_chars": list(budgets),
        "arms": {a: ARMS[a] for a in arms},
        "skipped_arms": skipped,
        "metrics": {
            "recall": "share of gold lines that appear complete in the context",
            "mrr": "1/rank of the first context block that overlaps a gold span (0 if none);"
            " a block is a file for arm A and a chunk for B, C and D",
            "any_gold_in_context": "share of questions with at least one gold line shown",
            "ci95": "percentile bootstrap over questions, 10,000 resamples, seed 0",
        },
        "summary": summarize(rows, arms, budgets),
        "rows": rows,
    }


def table(result: dict) -> str:
    lines = ["budget  arm  recall [95% CI]          MRR [95% CI]            any gold"]
    for budget, per in result["summary"].items():
        for arm, s in per.items():
            lo, hi = s["recall_ci95"]
            mlo, mhi = s["mrr_ci95"]
            lines.append(
                f"{int(budget):>6}  {arm:<3}  {s['recall']:.3f} [{lo:.3f}, {hi:.3f}]"
                f"    {s['mrr']:.3f} [{mlo:.3f}, {mhi:.3f}]    {s['any_gold_in_context']:.3f}"
            )
    return "\n".join(lines)


def gate(result: dict) -> list[str]:
    """Arm C recall at each budget must stay within TOLERANCE of the committed baseline."""
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    failures = []
    for budget, want in baseline["recall_C"].items():
        got = result["summary"][budget]["C"]["recall"]
        floor = want - baseline.get("tolerance", TOLERANCE)
        status = "ok" if got >= floor else "FAIL"
        print(f"gate {status}: arm C recall at {budget} chars = {got:.4f} (floor {floor:.4f})")
        if got < floor:
            failures.append(budget)
    return failures


def baseline_from(result: dict, source: str) -> dict:
    return {
        "arm": "C",
        "recall_C": {b: per["C"]["recall"] for b, per in result["summary"].items()},
        "tolerance": TOLERANCE,
        "questions": result["questions"],
        "source": source,
        "vibetter_commit": result["vibetter_commit"],
    }
