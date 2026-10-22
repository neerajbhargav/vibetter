"""The codebase index: which files VIBETTER reads, and how it keeps them fresh.

In a git repo the file list comes from `git ls-files -co --exclude-standard`,
so .gitignore rules apply exactly as git applies them. Outside git, a walk
honors each directory's .gitignore. Lockfiles, minified bundles, binaries,
files over 1 MB and secret files (see redact.py) are skipped with a reason.

The index is built on first use, not at import. A watchdog observer feeds
created, modified, deleted and moved events into a trailing-edge debounce;
each flush re-reads only the files that changed.
"""

from __future__ import annotations

import difflib
import os
import posixpath
import subprocess
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pathspec
from watchdog.events import FileSystemEvent, FileSystemEventHandler

from .config import VibetterError
from .redact import is_secret_path

MAX_FILE_BYTES = 1_000_000
SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".next",
        ".nuxt",
        "dist",
        "build",
        "out",
        ".idea",
        ".vscode",
        "coverage",
        ".gradle",
        "target",
    }
)
LOCKFILES = frozenset(
    {
        "package-lock.json",
        "npm-shrinkwrap.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lock",
        "bun.lockb",
        "poetry.lock",
        "uv.lock",
        "pdm.lock",
        "pipfile.lock",
        "cargo.lock",
        "gemfile.lock",
        "composer.lock",
        "go.sum",
        "flake.lock",
        "podfile.lock",
        "pubspec.lock",
        "mix.lock",
        "packages.lock.json",
    }
)
SKIP_SUFFIXES = (".svg", ".map", ".snap")


class NotIndexed(VibetterError):
    pass


def _in_skip_dir(rel: str) -> bool:
    return any(part in SKIP_DIRS for part in rel.split("/")[:-1])


def _looks_minified(text: str) -> bool:
    # ponytail: average line length heuristic; a tokenizer-based check if it misfires.
    return len(text) > 1000 and len(text) / (text.count("\n") + 1) > 300


def read_indexable(root: Path, rel: str) -> tuple[str | None, str | None]:
    """Return (skip_reason, text). Both are None when the file is gone."""
    name = posixpath.basename(rel).lower()
    if is_secret_path(rel):
        return "secret", None
    if name in LOCKFILES:
        return "lockfile", None
    if ".min." in name:
        return "minified", None
    if name.endswith(SKIP_SUFFIXES):
        return "asset", None
    path = root / rel
    try:
        if not path.is_file():
            return None, None
        if path.is_symlink() and not path.resolve().is_relative_to(root):
            return "outside root", None
        if path.stat().st_size > MAX_FILE_BYTES:
            return "too large", None
        data = path.read_bytes()
    except OSError:
        return "unreadable", None
    if b"\0" in data[:8192]:
        return "binary", None
    text = data.decode("utf-8", errors="replace")
    if _looks_minified(text):
        return "minified", None
    return None, text


def render(rel: str, text: str, label: str = "FILE", budget: int | None = None) -> str:
    """A file with a header and right-aligned line numbers: `  7| code`.

    With a budget, whole lines are kept until the budget is reached.
    Returns "" when not even the header fits.
    """
    lines = text.splitlines()
    width = len(str(len(lines))) if lines else 1
    header = f"--- {label}: {rel} ({len(lines)} lines) ---\n"
    body = [f"{n:>{width}}| {line}\n" for n, line in enumerate(lines, 1)]
    full = header + "".join(body)
    if budget is None or len(full) <= budget:
        return full
    note = f"... truncated after line {{}} of {len(lines)}\n"
    reserve = len(note) + width
    if len(header) + reserve > budget:
        return ""
    out, used = [header], len(header)
    for kept, line in enumerate(body):
        if used + len(line) + reserve > budget:
            out.append(note.format(kept))
            break
        out.append(line)
        used += len(line)
    return "".join(out)


class CodebaseIndex(FileSystemEventHandler):
    def __init__(self, root: str | os.PathLike[str], debounce: float = 0.3, max_wait: float = 5.0):
        self.root = Path(root).resolve()
        self.debounce = debounce
        self.max_wait = max_wait
        self.mode = "unbuilt"
        self.build_seconds = 0.0
        self._files: dict[str, str] = {}
        self._skipped: dict[str, str] = {}
        self._lock = threading.RLock()
        self._built = False
        self._pending: set[str] = set()
        self._rescan = False
        self._first_pending: float | None = None
        self._timer: threading.Timer | None = None
        self._pending_lock = threading.Lock()
        self._observer: Any = None

    # --- reading -------------------------------------------------------------

    @property
    def files(self) -> dict[str, str]:
        self.ensure_built()
        with self._lock:
            return dict(self._files)

    @property
    def skipped(self) -> dict[str, str]:
        self.ensure_built()
        with self._lock:
            return dict(self._skipped)

    def ensure_built(self) -> None:
        with self._lock:
            if not self._built:
                self.build()

    def build(self) -> None:
        start = time.perf_counter()
        rels, mode = self._list_files()
        files: dict[str, str] = {}
        skipped: dict[str, str] = {}
        for rel in rels:
            reason, text = read_indexable(self.root, rel)
            if text is not None:
                files[rel] = text
            elif reason:
                skipped[rel] = reason
        with self._lock:
            self._files, self._skipped = files, skipped
            self.mode, self._built = mode, True
            self.build_seconds = time.perf_counter() - start

    def stats(self) -> dict[str, Any]:
        files, skipped = self.files, self.skipped
        return {
            "root": str(self.root),
            "mode": self.mode,
            "files": len(files),
            "lines": sum(len(t.splitlines()) for t in files.values()),
            "chars": sum(len(t) for t in files.values()),
            "skipped": dict(sorted(Counter(skipped.values()).items())),
            "build_seconds": round(self.build_seconds, 3),
        }

    def resolve(self, path: str) -> str:
        """Map a user-supplied path to an indexed relative path, or explain why not."""
        given = path.strip().replace("\\", "/")
        if not given:
            raise NotIndexed("No file path given.")
        if os.path.isabs(given):
            try:
                rel = Path(given).resolve().relative_to(self.root).as_posix()
            except ValueError:
                raise NotIndexed(f"{path} is outside the indexed codebase {self.root}.") from None
        else:
            rel = posixpath.normpath(given)
            if rel == ".." or rel.startswith("../"):
                raise NotIndexed(f"{path} is outside the indexed codebase {self.root}.")
        files, skipped = self.files, self.skipped
        if rel in files:
            return rel
        if rel in skipped:
            raise NotIndexed(f"{path} is excluded from the index ({skipped[rel]}).")
        close = difflib.get_close_matches(rel, list(files), n=3, cutoff=0.6)
        hint = f" Did you mean: {', '.join(close)}?" if close else ""
        raise NotIndexed(
            f"File not found in the index: {path} (paths are relative to {self.root}).{hint}"
        )

    def context(self, target: str | None = None, max_chars: int = 40_000) -> str:
        """Line-numbered files within max_chars: the target first, then its
        directory, then the rest by path. Files that do not fit are skipped."""
        files = self.files
        out: list[str] = []
        used = 0
        rel = None
        if target:
            rel = self.resolve(target)
            chunk = render(rel, files[rel], "TARGET FILE", budget=max_chars)
            out.append(chunk)
            used = len(chunk)
        here = posixpath.dirname(rel) if rel else None
        for path in sorted(files, key=lambda p: (posixpath.dirname(p) != here, p)):
            if path == rel:
                continue
            chunk = render(path, files[path]) + "\n"
            if used + len(chunk) > max_chars:
                continue
            out.append(chunk)
            used += len(chunk)
        return "".join(out)

    # --- listing -------------------------------------------------------------

    def _git(self, *args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", *args], cwd=self.root, input=stdin, capture_output=True, check=False
        )

    def _list_files(self) -> tuple[list[str], str]:
        try:
            out = self._git("ls-files", "-co", "--exclude-standard", "-z")
        except OSError:  # git is not installed
            out = None
        if out is None or out.returncode != 0:
            return self._walk(), "walk"
        rels = {p for p in os.fsdecode(out.stdout).split("\0") if p}
        return sorted(r for r in rels if not _in_skip_dir(r)), "git"

    def _walk(self) -> list[str]:
        specs: dict[str, pathspec.PathSpec | None] = {}
        found: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            here = Path(dirpath).relative_to(self.root).as_posix()
            here = "" if here == "." else here
            dirnames[:] = sorted(
                d
                for d in dirnames
                if d not in SKIP_DIRS
                and not self._walk_ignored(posixpath.join(here, d), True, specs)
            )
            for name in filenames:
                rel = posixpath.join(here, name)
                if not self._walk_ignored(rel, False, specs):
                    found.append(rel)
        return sorted(found)

    def _walk_ignored(
        self, rel: str, is_dir: bool, specs: dict[str, pathspec.PathSpec | None]
    ) -> bool:
        # ponytail: any matching .gitignore ignores the path; a deeper "!pattern"
        # does not re-include. Use git for exact semantics.
        parts = rel.split("/")
        for depth in range(len(parts)):
            base = "/".join(parts[:depth])
            if base not in specs:
                gitignore = self.root / base / ".gitignore"
                specs[base] = (
                    pathspec.GitIgnoreSpec.from_lines(
                        gitignore.read_text(errors="replace").splitlines()
                    )
                    if gitignore.is_file()
                    else None
                )
            spec = specs[base]
            sub = "/".join(parts[depth:]) + ("/" if is_dir else "")
            if spec is not None and spec.match_file(sub):
                return True
        return False

    def _ignored(self, rels: set[str]) -> set[str]:
        if self.mode == "git":
            out = self._git("check-ignore", "-z", "--stdin", stdin="\0".join(rels).encode())
            return {p for p in os.fsdecode(out.stdout).split("\0") if p}
        specs: dict[str, pathspec.PathSpec | None] = {}
        return {r for r in rels if self._walk_ignored(r, False, specs)}

    # --- watching ------------------------------------------------------------

    def start_watching(self) -> None:
        from watchdog.observers import Observer

        with self._lock:
            if self._observer is not None:
                return
            observer = Observer()
            observer.schedule(self, str(self.root), recursive=True)
            observer.daemon = True
            observer.start()
            self._observer = observer

    def stop(self) -> None:
        with self._pending_lock:
            if self._timer is not None:
                self._timer.cancel()
        if self._observer is not None:
            self._observer.stop()
            self._observer = None

    def _rel(self, raw: str | bytes) -> str | None:
        rel = os.path.relpath(os.path.realpath(os.fsdecode(raw)), self.root).replace(os.sep, "/")
        if rel == "." or rel.startswith("../") or rel == ".." or _in_skip_dir(rel + "/x"):
            return None
        return rel

    def on_any_event(self, event: FileSystemEvent) -> None:
        kind = event.event_type
        if kind not in ("created", "modified", "deleted", "moved", "closed"):
            return
        raw = [event.src_path] + ([event.dest_path] if kind == "moved" else [])
        rels = [r for r in map(self._rel, raw) if r is not None]
        if not rels or (event.is_directory and kind == "modified"):
            return
        with self._pending_lock:
            if event.is_directory or any(posixpath.basename(r) == ".gitignore" for r in rels):
                self._rescan = True
            else:
                self._pending.update(rels)
            now = time.monotonic()
            if self._first_pending is None:
                self._first_pending = now
            if self._timer is not None:
                self._timer.cancel()
            # Trailing edge: wait for quiet, but never longer than max_wait.
            waited = now - self._first_pending
            delay = 0.0 if waited >= self.max_wait else self.debounce
            self._timer = threading.Timer(delay, self.flush)
            self._timer.daemon = True
            self._timer.start()

    def flush(self) -> None:
        """Apply pending events now. The debounce timer calls this."""
        with self._pending_lock:
            pending, rescan = self._pending, self._rescan
            self._pending, self._rescan, self._first_pending = set(), False, None
            self._timer = None
        if rescan:
            self.build()
            return
        if not pending:
            return
        ignored = self._ignored(pending)
        loaded = {rel: read_indexable(self.root, rel) for rel in pending - ignored}
        with self._lock:
            for rel in pending:
                self._files.pop(rel, None)
                self._skipped.pop(rel, None)
                reason, text = loaded.get(rel, (None, None))
                if text is not None:
                    self._files[rel] = text
                elif reason:
                    self._skipped[rel] = reason
