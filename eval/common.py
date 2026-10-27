"""Shared pieces of the eval: datasets, the pinned checkouts, the v1 context and statistics.

The eval reads third-party repos as data only. Nothing in a checkout is run.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from vibetter.chunk import split_lines

EVAL_DIR = Path(__file__).resolve().parent
DATASETS = EVAL_DIR / "datasets"
RESULTS = EVAL_DIR / "results"
CACHE = Path(os.getenv("VIBETTER_EVAL_CACHE") or EVAL_DIR / ".cache")

Span = tuple[int, int]


@dataclass(frozen=True)
class Gold:
    path: str
    start: int
    end: int


@dataclass(frozen=True)
class Question:
    id: str
    repo: str
    question: str
    gold: tuple[Gold, ...]
    terms: tuple[str, ...]


def load_repos() -> list[dict[str, str]]:
    return json.loads((DATASETS / "repos.json").read_text(encoding="utf-8"))


def load_questions() -> list[Question]:
    out = []
    for line in (DATASETS / "questions.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        q = json.loads(line)
        out.append(
            Question(
                q["id"],
                q["repo"],
                q["question"],
                tuple(Gold(g["path"], g["start"], g["end"]) for g in q["gold"]),
                tuple(q["terms"]),
            )
        )
    return out


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1", "GIT_TERMINAL_PROMPT": "0"}
    out = subprocess.run(
        ["git", "-c", "advice.detachedHead=false", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {out.stderr.strip()}")
    return out.stdout.strip()


def checkout(repo: dict[str, str]) -> Path:
    """The repo at its pinned SHA under the cache, fetched once (shallow, by SHA)."""
    dest = CACHE / repo["name"]
    if (dest / ".git").is_dir():
        try:
            if _git(dest, "rev-parse", "HEAD") == repo["sha"]:
                return dest
        except RuntimeError:
            pass
    dest.mkdir(parents=True, exist_ok=True)
    _git(dest, "init", "-q")
    _git(dest, "fetch", "-q", "--depth", "1", repo["url"] + ".git", repo["sha"])
    _git(dest, "checkout", "-q", "--force", "--detach", "FETCH_HEAD")
    head = _git(dest, "rev-parse", "HEAD")
    if head != repo["sha"]:
        raise RuntimeError(f"{repo['name']}: expected {repo['sha']}, got {head}")
    return dest


def checkouts() -> dict[str, Path]:
    return {r["name"]: checkout(r) for r in load_repos()}


def read_lines(root: Path, rel: str) -> list[str]:
    return split_lines((root / rel).read_text(encoding="utf-8", errors="replace"))


# --- v1 behaviour (tag v1.0.0, backend/src/brain/scholar.py) --------------------------

V1_IGNORED_DIRS = frozenset(
    ("node_modules", ".git", "__pycache__", "dist", ".venv", "venv", ".next", "build", "out")
)
V1_SUFFIXES = (
    ".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".md", ".json",
    ".html", ".css", ".env.example", ".yaml", ".yml", ".toml",
)  # fmt: skip


def v1_files(root: Path) -> list[tuple[str, str]]:
    """(relative path, text) in v1's walk order: os.walk, ignored dirs pruned, suffix allowlist.

    v1 used whatever order the filesystem returned. Names are sorted at each level
    here so the arm gives the same context on every machine.
    """
    out: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in V1_IGNORED_DIRS)
        for name in sorted(filenames):
            if name.endswith(V1_SUFFIXES):
                path = Path(dirpath) / name
                with open(path, encoding="utf-8", errors="ignore") as f:
                    out.append((path.relative_to(root).as_posix(), f.read()))
    return out


def v1_context(files: Sequence[tuple[str, str]], budget: int) -> tuple[str, dict[str, list[Span]]]:
    """v1's master_context[:budget], and the line spans of each file that it shows.

    v1 joined `--- FILE: rel ---\\n{content}\\n` parts with newlines and cut the
    string at the budget. A line counts as shown when it is complete in the cut.
    """
    parts, shown, used = [], {}, 0
    for rel, text in files:
        header = f"--- FILE: {rel} ---\n"
        part = f"{header}{text}\n"
        sep = 1 if parts else 0
        room = budget - used - sep - len(header)
        if room <= 0:
            break
        lines = split_lines(text)
        if len(part) + sep <= budget - used:
            n = len(lines)
        else:
            n, pos = 0, 0  # complete lines that fit in `room` characters
            for raw in text.split("\n")[: len(lines)]:
                pos += len(raw) + 1
                if pos > room:
                    break
                n += 1
        if n:
            shown[rel] = [(1, n)]
        parts.append(part)
        used += sep + len(part)
    context = "\n".join(parts)[:budget]
    return context, shown


def v1_targeted_context(
    files: Sequence[tuple[str, str]], target: str, max_chars: int = 40_000
) -> tuple[str, dict[str, list[Span]]]:
    """v1's get_targeted_context(): what v1's scholar_explain showed for a file.

    The target file whole, then other files in walk order while each fits whole in
    max_chars; the first file that does not fit ends the context.
    """
    text = dict(files)
    parts = [f"--- TARGET FILE: {target} ---\n{text[target]}\n"]
    shown = {target: [(1, len(split_lines(text[target])))]}
    budget = max_chars - len(parts[0])
    for rel, content in files:
        if rel == target:
            continue
        part = f"--- FILE: {rel} ---\n{content}\n"
        if budget - len(part) < 0:
            break
        parts.append(part)
        shown[rel] = [(1, len(split_lines(content)))]
        budget -= len(part)
    return "\n".join(parts), shown


# --- metrics ---------------------------------------------------------------------------


def overlap(spans: Sequence[Span], start: int, end: int) -> int:
    """Number of lines in start..end covered by the (non-overlapping) spans."""
    return sum(max(0, min(e, end) - max(s, start) + 1) for s, e in spans)


def gold_recall(q: Question, shown: Mapping[str, Sequence[Span]]) -> float:
    """Fraction of the question's gold lines that the context shows."""
    total = sum(g.end - g.start + 1 for g in q.gold)
    hit = sum(overlap(shown.get(g.path, []), g.start, g.end) for g in q.gold)
    return hit / total


def hits_gold(q: Question, path: str, start: int, end: int) -> bool:
    return any(g.path == path and g.start <= end and start <= g.end for g in q.gold)


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def bootstrap(
    n: int,
    stat: Callable[[list[int]], float],
    resamples: int = 10_000,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile 95% CI of stat(indices) over questions resampled with replacement."""
    rng = random.Random(seed)
    values = sorted(stat([rng.randrange(n) for _ in range(n)]) for _ in range(resamples))
    return values[int(0.025 * resamples)], values[int(0.975 * resamples) - 1]


def git_head(path: Path) -> str:
    try:
        return _git(path, "rev-parse", "HEAD")
    except RuntimeError:
        return "unknown"


def git_dirty(path: Path) -> bool:
    try:
        # Result files change on every run; only code and data count as dirty.
        return bool(
            _git(path, "status", "--porcelain", "--untracked-files=no", "--", ".", ":!eval/results")
        )
    except RuntimeError:
        return True
