"""Collect "what just changed" for explain_last_change.

Order of preference:
1. Uncommitted work: staged and unstaged changes (`git diff HEAD`, or the
   index and worktree before the first commit) plus untracked files, which
   is what an AI agent usually creates.
2. Otherwise the last commit (`git show HEAD`), which also works for the
   root commit.

Secret files, lockfiles and minified files are left out of the diff.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .config import VibetterError
from .index import LOCKFILES, SKIP_DIRS, read_indexable
from .redact import SECRET_FILE_GLOBS


class GitError(VibetterError):
    pass


_EXCLUDES = [
    f":(exclude,glob)**/{g}"
    for g in (*SECRET_FILE_GLOBS, *sorted(LOCKFILES), "*.min.js", "*.min.css")
]
_PATHSPEC = ["--", ".", *_EXCLUDES]


def _git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    if out.returncode != 0:
        stderr = out.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(f"git {args[0]} failed: {stderr}")
    return out.stdout.decode("utf-8", errors="replace")


def _new_file_patch(root: Path, rel: str) -> str:
    reason, text = read_indexable(root, rel)
    if reason == "secret" or (reason is None and text is None):
        return ""
    if text is None:
        return f"diff --git a/{rel} b/{rel}\nnew untracked file, not shown ({reason})\n"
    lines = text.splitlines()
    body = "".join(f"+{line}\n" for line in lines)
    return (
        f"diff --git a/{rel} b/{rel}\nnew untracked file\n--- /dev/null\n+++ b/{rel}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n{body}"
    )


def collect_changes(root: Path, max_chars: int = 40_000) -> tuple[str, str]:
    """Return (what was diffed, unified diff text)."""
    if shutil.which("git") is None:
        raise GitError("git is not installed or not on PATH.")
    try:
        _git(root, "rev-parse", "--is-inside-work-tree")
    except GitError:
        raise GitError(
            f"{root} is not a git repository, so there is no change to explain."
        ) from None

    has_head = (
        subprocess.run(
            ["git", "rev-parse", "--verify", "-q", "HEAD"],
            cwd=root,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )
    diff_args = ["diff", "--relative", "--no-color", "--no-ext-diff"]
    if has_head:
        tracked = _git(root, *diff_args, "HEAD", *_PATHSPEC)
    else:
        tracked = _git(root, *diff_args, "--cached", *_PATHSPEC) + _git(
            root, *diff_args, *_PATHSPEC
        )

    untracked = [
        p
        for p in _git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
        if p and not any(part in SKIP_DIRS for part in p.split("/"))
    ]
    new_files = "".join(_new_file_patch(root, rel) for rel in untracked)

    if tracked.strip() or new_files:
        label = "uncommitted changes (staged and unstaged"
        label += f", plus {len(untracked)} untracked file(s))" if untracked else ")"
        diff = tracked + new_files
    elif has_head:
        diff = _git(
            root,
            "show",
            "--relative",
            "--no-color",
            "--no-ext-diff",
            "--format=commit %h%nSubject: %s%n",
            "HEAD",
            *_PATHSPEC,
        )
        first = diff.splitlines()[0] if diff else "commit HEAD"
        label = f"the last commit ({first.removeprefix('commit ')})"
    else:
        raise GitError("This repository has no commits and no changes yet.")

    return label, fit(diff, max_chars)


def fit(diff: str, max_chars: int) -> str:
    """Keep whole per-file sections while they fit; summarize the rest.

    One huge file (a generated blob, a data dump) no longer pushes every
    other change out of the budget.
    """
    out: list[str] = []
    used = 0
    for section in re.split(r"(?m)^(?=diff --git )", diff):
        if not section:
            continue
        if used + len(section) > max_chars:
            header = section.splitlines()[0]
            lines = section.count("\n")
            section = f"{header}\n(omitted: {lines} diff lines do not fit the budget)\n"
            if used + len(section) > max_chars:
                continue
        out.append(section)
        used += len(section)
    return "".join(out)
