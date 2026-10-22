"""The citation contract: parse file:line references and check them.

The prompts ask for `path:L<first>-L<last>`, such as `path:L12-L20` (or
`path:L12`). The parser also accepts the variants models write anyway:
`path:12-20`, `path#L12-L20`, `path:12:5`, `path, lines 12-20`,
`path (line 12)` and traceback `File "path", line 12`.

A citation is
- valid when the file is indexed and the lines exist,
- grounded when the range overlaps context the model was actually shown,
- quote-matched when a code quote placed right after it (`path:L7 `code``)
  appears in the cited lines.
No LLM is involved; every check is a lookup.
"""

from __future__ import annotations

import os
import posixpath
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .chunk import split_lines

Spans = Mapping[str, list[tuple[int, int]]]

_PATH = r"/?(?:\.{1,2}/)?[\w@~+-][\w.@~+-]*(?:[/\\][\w.@~+-]+)*"
_DASH = r"(?:-|\u2013|\u2014|\.\.)"
_REF = re.compile(
    r'File "(?P<tb_path>[^"\n]+)", line (?P<tb_line>\d+)'
    rf"|(?P<path>{_PATH})"
    rf"(?:[:#]L?(?P<start>\d+)(?::\d+)?(?:{_DASH}L?(?P<end>\d+)(?::\d+)?)?"
    r"|[`'\"]?,?[ \t]*\(?[ \t]*lines?[ \t]+(?P<wstart>\d+)"
    r"(?:[ \t]*(?:-|\u2013|\u2014|to|through)[ \t]*(?P<wend>\d+))?)"
)
_QUOTE = re.compile(r"[ \t]*(?:[:\-\u2013\u2014][ \t]*)?(?:`([^`\n]+)`|\"([^\"\n]+)\")")
_NOT_FILES = frozenset({"com", "org", "net", "io", "dev", "ai"})  # host:port, not path:line


@dataclass
class Ref:
    """One citation as written in the text."""

    cited: str
    path: str
    start: int
    end: int
    offset: tuple[int, int]
    quote: str | None = None


@dataclass
class CitationCheck:
    cited: str
    path: str
    start: int
    end: int
    valid: bool
    grounded: bool | None
    quote_match: bool | None
    reason: str

    @property
    def verified(self) -> bool:
        return self.valid and self.grounded is not False and self.quote_match is not False


def _looks_like_path(path: str) -> bool:
    if "/" in path.lstrip("/") or "\\" in path:
        return True
    ext = path.rsplit(".", 1)[-1] if "." in path else ""
    return bool(ext) and ext[0].isalpha() and ext.lower() not in _NOT_FILES


def parse(text: str) -> list[Ref]:
    refs: list[Ref] = []
    for m in _REF.finditer(text):
        if m.group("tb_path"):
            path, start, end = m.group("tb_path"), int(m.group("tb_line")), None
        else:
            path = m.group("path")
            raw_start = m.group("start") or m.group("wstart")
            raw_end = m.group("end") or m.group("wend")
            if not _looks_like_path(path) or text[m.start() - 1 : m.start()] in ("/", ":"):
                continue  # part of a URL such as https://host/x.py:12
            start, end = int(raw_start), int(raw_end) if raw_end else None
        after = m.end()
        # Skip the closing mark of a wrapped citation such as `path:12`.
        if (
            after < len(text)
            and text[after] in "`'\""
            and text[m.start() - 1 : m.start()] == text[after]
        ):
            after += 1
        # A quote may follow the bracket around a citation, as in (path:L12) `code`.
        while after < len(text) and text[after] in ")]":
            after += 1
        q = _QUOTE.match(text, after)
        refs.append(
            Ref(
                cited=m.group(0),
                path=path,
                start=start,
                end=end if end is not None else start,
                offset=(m.start(), after),
                quote=(q.group(1) or q.group(2)) if q else None,
            )
        )
    return refs


def resolve(
    path: str, files: Mapping[str, str], root: Path | None = None
) -> tuple[str | None, str]:
    """Map a cited path to an indexed path, tolerating ./, absolute and partial paths."""
    p = path.strip().replace("\\", "/")
    if root is not None and os.path.isabs(p):
        try:
            p = Path(p).resolve().relative_to(root).as_posix()
        except ValueError:
            pass
    p = posixpath.normpath(p)
    if p in files:
        return p, "ok"
    tail = p.lstrip("/")
    # A shorter path may name an indexed file; a longer one only if it is absolute
    # (a traceback from another checkout), never an invented relative prefix.
    matches = [
        f for f in files if f.endswith("/" + tail) or (p.startswith("/") and p.endswith("/" + f))
    ]
    if len(matches) == 1:
        return matches[0], "ok (path completed from a unique suffix)"
    if matches:
        return None, f"ambiguous path: {len(matches)} indexed files match"
    return None, "file not indexed"


def _squash(s: str) -> str:
    return " ".join(s.split())


def check_ref(
    ref: Ref, files: Mapping[str, str], shown: Spans | None = None, root: Path | None = None
) -> CitationCheck:
    path, reason = resolve(ref.path, files, root)

    def result(valid: bool, grounded: bool | None, quote: bool | None, why: str) -> CitationCheck:
        return CitationCheck(
            ref.cited, path or ref.path, ref.start, ref.end, valid, grounded, quote, why
        )

    if path is None:
        return result(False, False if shown is not None else None, None, reason)
    lines = split_lines(files[path])
    if ref.start < 1 or ref.end < ref.start:
        return result(False, False if shown is not None else None, None, "malformed line range")
    if ref.end > len(lines):
        why = f"line out of range: the file has {len(lines)} lines"
        return result(False, False if shown is not None else None, None, why)
    grounded = None
    if shown is not None:
        grounded = any(s <= ref.end and ref.start <= e for s, e in shown.get(path, ()))
        if not grounded:
            reason = "lines exist but were not in the context shown to the model"
    quote_match = None
    if ref.quote:
        cited = _squash("\n".join(lines[ref.start - 1 : ref.end]))
        parts = [_squash(p) for p in re.split(r"\.\.\.|\u2026", ref.quote)]
        quote_match = all(part in cited for part in parts if part)
        if not quote_match:
            reason = "quoted code does not appear in the cited lines"
    return result(True, grounded, quote_match, reason)


def check(
    text: str, files: Mapping[str, str], shown: Spans | None = None, root: Path | None = None
) -> list[tuple[Ref, CitationCheck]]:
    return [(ref, check_ref(ref, files, shown, root)) for ref in parse(text)]


def unique(pairs: list[tuple[Ref, CitationCheck]]) -> list[CitationCheck]:
    seen: dict[tuple[str, int, int], CitationCheck] = {}
    for _, c in pairs:
        key = (c.path, c.start, c.end)
        # Keep the worst verdict if the same span is cited twice.
        if key not in seen or (seen[key].verified and not c.verified):
            seen[key] = c
    return list(seen.values())


def counts(checks: list[CitationCheck]) -> dict[str, Any]:
    return {
        "total": len(checks),
        "valid": sum(c.valid for c in checks),
        "grounded": sum(c.grounded is True for c in checks),
        "unverified": sum(not c.verified for c in checks),
    }


def _sentence(text: str, start: int, end: int) -> tuple[int, int]:
    left = 0
    for m in re.finditer(r"[.!?](?=\s)|\n", text[:start]):
        left = m.end()
    m = re.compile(r"[.!?](?=\s|$)|\n").search(text, end)
    right = len(text) if m is None else (m.start() if m.group() == "\n" else m.end())
    return left, right


def strip_unverified(text: str, pairs: list[tuple[Ref, CitationCheck]]) -> str:
    """Strict mode: drop each sentence that rests on a citation that did not verify."""
    if not pairs:
        return text + "\n\n[vibetter strict: the answer has no citations to verify.]"
    bad = [(ref, c) for ref, c in pairs if not c.verified]
    if not bad:
        return text
    spans = sorted(_sentence(text, *ref.offset) for ref, _ in bad)
    out, pos = [], 0
    for left, right in spans:
        if right <= pos:
            continue
        out.append(text[pos : max(pos, left)])
        pos = right
    out.append(text[pos:])
    notes = "; ".join(f"{c.cited} ({c.reason})" for c in unique(bad))
    return "".join(out).rstrip() + f"\n\n[vibetter strict: removed claims citing {notes}.]"
