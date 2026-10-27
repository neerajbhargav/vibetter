"""Model-backed eval with a local Ollama model: does the answer cite real, shown, gold lines?

Arms, at the same 24k-character context budget:
  v1         v1's context (walk order, first N characters, no line numbers) and v1's prompt
  v2         line-numbered retrieved context and the v2 prompt, with no file given
             (`vibetter ask` without --file; the scholar_explain tool requires a file)
  v2-strict  the v2 replies after strict verification, which drops each sentence whose
             citation fails; strict mode changes no prompt, so it reuses the v2 replies

Every reply is scored by the same deterministic checker (vibetter.cite). Replies are
cached under eval/.cache/llm, so an interrupted run resumes where it stopped.

rescore() scores the replies stored in a committed result file again, with no model
call, so the committed numbers can be reproduced in seconds and a change to the
checker can be measured on the same replies.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import platform
import time
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from vibetter import cite, prompts, providers
from vibetter.redact import redact
from vibetter.server import EXPLAIN_CHARS, Vibetter

from .common import (
    CACHE,
    EVAL_DIR,
    Question,
    bootstrap,
    checkouts,
    git_dirty,
    git_head,
    hits_gold,
    load_questions,
    load_repos,
    mean,
    v1_context,
    v1_files,
)

OLLAMA = "http://127.0.0.1:11434"
BUDGET = EXPLAIN_CHARS
ARMS = ("v1", "v2", "v2-strict")
STRICT_NOTE = "\n\n[vibetter strict:"
NARROW = 30  # gold_hit_narrow counts only citations of at most this many lines


def v1_prompt(question: str, context: str) -> str:
    """ask_gemini_with_context() from v1.0.0 (backend/src/brain/scholar.py), no target file.

    Copied verbatim. The em-dashes are written as escapes, so the string is the same.
    """
    return f"""You are VIBETTER, an expert coding mentor for people learning to code with AI tools (vibe coding).

Your job is to explain code clearly so the user actually understands it \u2014 not just copy-paste it.

Rules:
- Always cite exact file:line when referencing code
- Explain *why* the code works, not just *what* it does
- Use simple analogies for complex concepts
- Be encouraging \u2014 this person is learning

Codebase:
<context>
{context}
</context>


Question: {question}

Answer with clear sections: **What it does**, **How it works**, **Why it's written this way**."""  # noqa: E501


def without_note(text: str) -> str:
    """Strict mode appends a note that lists the removed citations; it is not part of the answer."""
    return text.split(STRICT_NOTE, 1)[0]


def score(
    q: Question, text: str, files: dict[str, str], shown: cite.Spans, root: Path
) -> dict[str, Any]:
    checks = cite.unique(cite.check(text, files, shown, root))
    lowered = text.lower()
    return {
        "citations": len(checks),
        "valid": sum(c.valid for c in checks),
        "grounded": sum(c.valid and c.grounded is True for c in checks),
        "gold_hit": any(c.valid and hits_gold(q, c.path, c.start, c.end) for c in checks),
        "gold_hit_narrow": any(
            c.valid and c.end - c.start < NARROW and hits_gold(q, c.path, c.start, c.end)
            for c in checks
        ),
        "term_recall": sum(t.lower() in lowered for t in q.terms) / len(q.terms),
        "chars": len(text.strip()),
    }


def score_reply(
    q: Question, base: dict[str, Any], arm: str, reply: str, ctx: dict[str, Any], root: Path
) -> list[dict[str, Any]]:
    """Rows for one reply: the v1 row, or the v2 row and its v2-strict row."""
    if arm == "v1":
        return [{**base, "arm": "v1", **score(q, reply, ctx["files_v1"], ctx["shown_v1"], root)}]
    files, shown = ctx["files"], ctx["shown"][q.id]
    strict = without_note(cite.strip_unverified(reply, cite.check(reply, files, shown, root)))
    return [
        {**base, "arm": "v2", **score(q, reply, files, shown, root)},
        {**base, "arm": "v2-strict", **score(q, strict, files, shown, root), "reply": strict},
    ]


def contexts(root: Path, questions: Sequence[Question]) -> dict[str, Any]:
    """What each arm showed the model for one repo: files, shown spans and prompts."""
    app = Vibetter(root, embedder=False)
    files = dict(app.index().files)
    old = v1_files(root)
    context_v1, shown_v1 = v1_context(old, BUDGET)
    ctx: dict[str, Any] = {
        "files": files,
        "files_v1": {**dict(old), **files},
        "shown_v1": shown_v1,
        "shown": {},
        "prompts": {},
    }
    for q in questions:
        _, context, shown = app._gather(q.question, None, BUDGET)
        ctx["shown"][q.id] = shown
        ctx["prompts"][q.id] = {
            "v1": v1_prompt(q.question, context_v1),
            "v2": redact(prompts.explain(q.question, context, None)),
        }
    return ctx


class Cache:
    def __init__(self, model: str):
        self.dir = CACHE / "llm" / model.replace(":", "_").replace("/", "_")
        self.dir.mkdir(parents=True, exist_ok=True)

    def path(self, arm: str, run: int, qid: str, prompt: str) -> Path:
        digest = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        return self.dir / f"{arm}-run{run}-{qid}-{digest}.json"

    def get(self, *key: Any) -> dict[str, Any] | None:
        p = self.path(*key)
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    def put(self, value: dict[str, Any], *key: Any) -> None:
        p = self.path(*key)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(value), encoding="utf-8")
        tmp.replace(p)


def ollama_info(model: str) -> dict[str, Any]:
    def get(path: str, body: dict | None = None) -> dict[str, Any]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(OLLAMA + path, data=data, method="POST" if data else "GET")
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    tags = {m["name"]: m for m in get("/api/tags")["models"]}
    show = get("/api/show", {"model": model})
    return {
        "version": get("/api/version")["version"],
        "model": model,
        "digest": tags.get(model, {}).get("digest"),
        "quantization": show.get("details", {}).get("quantization_level"),
        "parameters": show.get("parameters") or "Ollama defaults (no seed, no temperature set)",
    }


async def ask(prompt: str, model: str) -> tuple[str, float]:
    start = time.perf_counter()
    reply = await providers.call_llm(prompt, provider="ollama", models=[model])
    return reply, time.perf_counter() - start


def run(runs: int = 3, limit: int | None = None, model: str = "qwen2.5-coder:7b") -> dict:
    return asyncio.run(_run(runs, limit, model))


async def _run(runs: int, limit: int | None, model: str) -> dict:
    vibetter_root = EVAL_DIR.parent
    commit, dirty = git_head(vibetter_root), git_dirty(vibetter_root)  # read before the run
    info = ollama_info(model)
    cache = Cache(model)
    roots = checkouts()
    questions = load_questions()
    if limit is not None:  # the first `limit` questions of each repo, for a quick check
        questions = [
            q for r in load_repos() for q in [x for x in questions if x.repo == r["name"]][:limit]
        ]
    rows: list[dict[str, Any]] = []
    started, calls = time.perf_counter(), 0
    for repo in load_repos():
        root = roots[repo["name"]]
        mine = [q for q in questions if q.repo == repo["name"]]
        ctx = contexts(root, mine)
        for q in mine:
            for run_no in range(1, runs + 1):
                for arm in ("v1", "v2"):
                    prompt = ctx["prompts"][q.id][arm]
                    hit = cache.get(arm, run_no, q.id, prompt)
                    if hit is None:
                        reply, seconds = await ask(prompt, model)
                        hit = {"reply": reply, "seconds": round(seconds, 2)}
                        cache.put(hit, arm, run_no, q.id, prompt)
                        calls += 1
                        print(
                            f"[{time.perf_counter() - started:6.0f}s] call {calls}: {q.id}"
                            f" run {run_no} {arm} took {seconds:.1f}s",
                            flush=True,
                        )
                    base = {"id": q.id, "repo": q.repo, "run": run_no, "seconds": hit["seconds"]}
                    new = score_reply(q, base, arm, hit["reply"], ctx, root)
                    new[0]["reply"] = hit["reply"]
                    rows += new
    return {
        "eval": "llm",
        "vibetter_commit": commit,
        "vibetter_dirty": dirty,
        "python": platform.python_version(),
        "ollama": info,
        "repos": load_repos(),
        "questions": len(questions),
        "runs": runs,
        "budget_chars": BUDGET,
        **_descriptions(),
        "summary": summarize(rows, runs),
        "rows": rows,
    }


def rescore(source: Path) -> dict:
    """Score the v1 and v2 replies in a result file again with the current checker.

    No model is called. The contexts are rebuilt by the same deterministic retrieval,
    so the shown spans match the run as long as retrieval has not changed (the
    retrieval eval's rows show that). Rows keep no reply text; the source file has it.
    """
    old = json.loads(source.read_text(encoding="utf-8"))
    vibetter_root = EVAL_DIR.parent
    commit, dirty = git_head(vibetter_root), git_dirty(vibetter_root)
    roots = checkouts()
    questions = {q.id: q for q in load_questions()}
    rows: list[dict[str, Any]] = []
    for repo in old["repos"]:
        mine = [r for r in old["rows"] if r["repo"] == repo["name"] and r["arm"] in ("v1", "v2")]
        root = roots[repo["name"]]
        ctx = contexts(root, [questions[i] for i in dict.fromkeys(r["id"] for r in mine)])
        for r in mine:
            base = {k: r[k] for k in ("id", "repo", "run", "seconds")}
            rows += score_reply(questions[r["id"]], base, r["arm"], r["reply"], ctx, root)
    for r in rows:
        r.pop("reply", None)
    return {
        "eval": "llm-rescore",
        "rescored_from": source.name,
        "replies_from_commit": old["vibetter_commit"],
        "vibetter_commit": commit,
        "vibetter_dirty": dirty,
        "python": platform.python_version(),
        "ollama": old["ollama"],
        "repos": old["repos"],
        "questions": old["questions"],
        "runs": old["runs"],
        "budget_chars": old["budget_chars"],
        **_descriptions(),
        "summary": summarize(rows, old["runs"]),
        "rows": rows,
    }


def _descriptions() -> dict[str, Any]:
    return {
        "arms": {
            "v1": "v1 context (walk order, first 24k chars, no line numbers) and v1 prompt",
            "v2": "line-numbered retrieved context (BM25 + symbol RRF) and v2 prompt",
            "v2-strict": "v2 replies after strict verification (no extra model call)",
        },
        "metrics": {
            "citation_validity": "valid citations / all citations (file indexed, lines exist)",
            "groundedness": "valid citations whose lines were in the context shown / all citations",
            "gold_hit_rate": "share of answers with a valid citation that overlaps a gold span",
            "gold_hit_rate_narrow": f"gold_hit_rate, counting only citations of at most {NARROW}"
            " lines",
            "term_recall": "mean share of the question's key terms that appear in the answer",
            "cited_answers": "share of answers with at least one citation",
            "mean": "the mean of the per-run values",
            "pooled": "the value over all runs' answers pooled, which ci95 is built around",
            "ci95": "percentile bootstrap over questions (per-question values pooled over runs),"
            " 10,000 resamples, seed 0",
        },
    }


def _metrics(rows: Sequence[dict[str, Any]]) -> dict[str, float]:
    cites = sum(r["citations"] for r in rows)
    return {
        "citation_validity": sum(r["valid"] for r in rows) / cites if cites else 0.0,
        "groundedness": sum(r["grounded"] for r in rows) / cites if cites else 0.0,
        "gold_hit_rate": mean([float(r["gold_hit"]) for r in rows]),
        "gold_hit_rate_narrow": mean([float(r.get("gold_hit_narrow", False)) for r in rows]),
        "term_recall": mean([r["term_recall"] for r in rows]),
        "cited_answers": mean([float(r["citations"] > 0) for r in rows]),
        "citations_per_answer": cites / len(rows) if rows else 0.0,
    }


def summarize(rows: list[dict[str, Any]], runs: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for arm in ARMS:
        mine = [r for r in rows if r["arm"] == arm]
        per_run = {str(n): _metrics([r for r in mine if r["run"] == n]) for n in range(1, runs + 1)}
        by_q: dict[str, list[dict[str, Any]]] = {}
        for r in mine:
            by_q.setdefault(r["id"], []).append(r)
        groups = list(by_q.values())
        pooled = _metrics(mine)
        stat: dict[str, Any] = {"n_questions": len(groups), "n_answers": len(mine)}
        for name in pooled:
            values = [m[name] for m in per_run.values()]

            def boot(ix: list[int], name: str = name, groups: list = groups) -> float:
                return _metrics([r for i in ix for r in groups[i]])[name]

            stat[name] = {
                "per_run": [round(v, 4) for v in values],
                "mean": round(mean(values), 4),
                "pooled": round(pooled[name], 4),
                "ci95": [round(x, 4) for x in bootstrap(len(groups), boot)],
            }
        stat["median_seconds"] = sorted(r["seconds"] for r in mine)[len(mine) // 2] if mine else 0
        out[arm] = stat
    return out


def table(result: dict) -> str:
    names: Sequence[str] = ("citation_validity", "groundedness", "gold_hit_rate", "term_recall")
    lines = ["arm        " + "".join(f"{n:<30}" for n in names)]
    for arm, s in result["summary"].items():
        cells: list[str] = []
        for n in names:
            m = s[n]
            cells.append(f"{m['mean']:.3f} [{m['ci95'][0]:.3f}, {m['ci95'][1]:.3f}]".ljust(30))
        lines.append(f"{arm:<11}" + "".join(cells))
    return "\n".join(lines)
