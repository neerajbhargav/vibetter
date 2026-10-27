"""Run the eval.

uv run python -m eval.run --retrieval           all arms; writes results/retrieval-<date>.json
uv run python -m eval.run --retrieval --gate    arms A-C; fails if arm C recall drops (CI)
uv run python -m eval.run --retrieval --set-baseline   also rewrites the committed baseline
uv run python -m eval.run --retrieval --file-given     the question's file given, v1 and v2;
                                                writes results/retrieval-file-given-<date>.json
uv run python -m eval.run --llm                 local Ollama, 3 runs; writes results/llm-<date>.json
uv run python -m eval.run --llm --rescore eval/results/llm-2026-10-23.json
                                                no model call: scores the committed replies
                                                again; writes results/<name>-rescored.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from .common import RESULTS


def write(result: dict, name: str) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / name
    path.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(RESULTS.parent.parent)}")
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m eval.run", description="Run the vibetter eval.")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--retrieval", action="store_true", help="deterministic retrieval eval")
    mode.add_argument("--llm", action="store_true", help="model-backed eval with local Ollama")
    p.add_argument("--gate", action="store_true", help="fail if arm C recall drops (no file)")
    p.add_argument("--set-baseline", action="store_true", help="rewrite the retrieval baseline")
    p.add_argument("--file-given", action="store_true", help="give each question its gold file")
    p.add_argument("--arms", default=None, help="comma-separated arms, for example A,B,C")
    p.add_argument("--runs", type=int, default=3, help="LLM runs per arm (default 3)")
    p.add_argument("--limit", type=int, default=None, help="LLM: first N questions per repo")
    p.add_argument("--model", default="qwen2.5-coder:7b", help="Ollama model")
    p.add_argument("--out", default=None, help="results file name under eval/results/")
    p.add_argument("--rescore", default=None, help="LLM: score the replies in this result file")
    args = p.parse_args(argv)
    today = dt.date.today().isoformat()

    if args.llm:
        from . import llm

        if args.rescore:
            source = Path(args.rescore)
            result = llm.rescore(source)
            print(llm.table(result))
            write(result, args.out or f"{source.stem}-rescored.json")
            return 0
        result = llm.run(runs=args.runs, limit=args.limit, model=args.model)
        print(llm.table(result))
        write(result, args.out or f"llm-{today}.json")
        return 0

    from . import retrieval

    if args.file_given:
        result = retrieval.file_given()
        for name, s in result["summary"].items():
            lo, hi = s["recall_ci95"]
            print(
                f"{name:<14} recall {s['recall']:.3f} [{lo:.3f}, {hi:.3f}]  any gold "
                f"{s['any_gold_in_context']:.3f}"
            )
        write(result, args.out or f"retrieval-file-given-{today}.json")
        return 0
    arms = args.arms.split(",") if args.arms else (["A", "B", "C"] if args.gate else None)
    result = retrieval.run(arms) if arms else retrieval.run()
    print(retrieval.table(result))
    if args.gate:
        return 1 if retrieval.gate(result) else 0
    path = write(result, args.out or f"retrieval-{today}.json")
    if args.set_baseline:
        write(retrieval.baseline_from(result, path.name), retrieval.BASELINE.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
