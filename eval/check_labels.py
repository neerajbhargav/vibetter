"""Check the eval labels against the pinned checkouts.

Asserts that each repo's tag still points at its pinned SHA, that every gold
span exists at that SHA, and that the question's key terms appear in its gold
lines. Run: uv run python -m eval.check_labels
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections import Counter

from .common import checkout, load_questions, load_repos, read_lines

MIN_PER_REPO = 20


def tag_sha(url: str, ref: str) -> str | None:
    out = subprocess.run(
        ["git", "ls-remote", url + ".git", f"refs/tags/{ref}", f"refs/tags/{ref}^{{}}"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    shas = dict(line.split("\t")[::-1] for line in out.stdout.splitlines() if "\t" in line)
    # An annotated tag lists the tag object and, with ^{}, the commit it points at.
    return shas.get(f"refs/tags/{ref}^{{}}") or shas.get(f"refs/tags/{ref}")


def problems(check_tags: bool = True) -> list[str]:
    errors: list[str] = []
    repos = {r["name"]: r for r in load_repos()}
    roots = {name: checkout(r) for name, r in repos.items()}
    if check_tags:
        for name, r in repos.items():
            sha = tag_sha(r["url"], r["ref"])
            if sha != r["sha"]:
                errors.append(f"{name}: tag {r['ref']} is {sha}, repos.json pins {r['sha']}")
    questions = load_questions()
    ids = Counter(q.id for q in questions)
    errors += [f"duplicate question id {i}" for i, n in ids.items() if n > 1]
    per_repo = Counter(q.repo for q in questions)
    for name in repos:
        if per_repo[name] < MIN_PER_REPO:
            errors.append(f"{name}: {per_repo[name]} questions, need {MIN_PER_REPO}")
    for q in questions:
        if q.repo not in roots:
            errors.append(f"{q.id}: unknown repo {q.repo}")
            continue
        if not 1 <= len(q.terms) <= 3:
            errors.append(f"{q.id}: needs 1 to 3 key terms, has {len(q.terms)}")
        if not q.gold:
            errors.append(f"{q.id}: no gold span")
        text = []
        for g in q.gold:
            path = roots[q.repo] / g.path
            if not path.is_file():
                errors.append(f"{q.id}: {g.path} does not exist at the pinned SHA")
                continue
            lines = read_lines(roots[q.repo], g.path)
            if not 1 <= g.start <= g.end <= len(lines):
                errors.append(f"{q.id}: {g.path}:{g.start}-{g.end} is outside 1-{len(lines)}")
                continue
            text.append("\n".join(lines[g.start - 1 : g.end]))
        joined = "\n".join(text)
        for term in q.terms:
            if term not in joined:
                errors.append(f"{q.id}: key term {term!r} is not in the gold lines")
    return errors


def main() -> int:
    errors = problems(check_tags="--no-tags" not in sys.argv)
    questions = load_questions()
    for e in errors:
        print(f"FAIL {e}")
    if errors:
        print(f"{len(errors)} label problems")
        return 1
    print(f"ok: {len(questions)} questions, {sum(len(q.gold) for q in questions)} gold spans")
    return 0


if __name__ == "__main__":
    sys.exit(main())
