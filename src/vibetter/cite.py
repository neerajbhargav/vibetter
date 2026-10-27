"""The citation contract: parse file:line references and check them.

The prompts ask for `path:L<first>-L<last>`, such as `path:L12-L20` (or
`path:L12`). The parser also accepts the variants models write anyway:
`path:12-20`, `path#L12-L20`, `path:12:5`, `path, lines 12-20`,
`path (line 12)`, `path at line 12`, `path:path/x.py:L12`, `lines 12-20 of path`
and traceback `File "path", line 12`.

A path starts at a token boundary (start of text, whitespace, a quote or
backtick, `(`, `[` and similar), may start with a dot (`.github/ci.yml`) and
may hold `[slug]` and `(group)` segments. It never starts inside a word, so
`app/shop/[id]/page.tsx` is not read as `/page.tsx`, and the scan stays linear.

A citation is
- valid when the file is indexed and the lines exist,
- grounded when every cited line was in the context the model was shown,
- quote-matched when a code quote placed right after it (`path:L7 `code``)
  appears in the cited lines.
No LLM is involved; every check is a lookup.
"""

from __future__ import annotations

import bisect
import os
import posixpath
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .chunk import split_lines

Spans = Mapping[str, list[tuple[int, int]]]

# Path characters: word characters, combining marks (NFD names) and .@~+-. A segment may
# also hold a whole [slug] or (group). A match may start only after a boundary, and no two
# adjacent repeats can trade characters, so a failed match costs time linear in the text.
_CH = r"[\w\u0300-\u036f.@~+-]"
_SEG = rf"(?:{_CH}|\[{_CH}+\]|\({_CH}+\))+"
_PATH = rf"/?{_SEG}(?:[/\\]{_SEG})*"
# A path starts at the start of the text or after one of these, never inside a word.
_START = r"(?<![^\s`'\"(\[*<>{,;|])"
_DASH = r"(?:-|\u2013|\u2014|\.\.)"
_N = r"[0-9]+"
# Spaces are allowed before an L-prefixed line ("path L5", "path: L5", "L5 - L8"),
# never before a bare number, so "main.py 2 times" stays prose.
_LINE_SEP = r"(?:[:#]|:?[ \t]+(?=L[0-9]))"
_RANGE_DASH = rf"(?:{_DASH}|[ \t]*{_DASH}[ \t]*(?=L[0-9]))"
_WORD_DASH = r"[ \t]*(?:-|\u2013|\u2014|to|through)[ \t]*"
_REF = re.compile(
    rf'File "(?P<tb_path>[^"\n]+)", line (?P<tb_line>{_N})'
    # lines 12-20 of `path`
    rf"|{_START}[Ll]ines?[ \t]+(?P<rstart>{_N})(?:{_WORD_DASH}(?P<rend>{_N}))?"
    rf"[ \t]+(?:of|in)[ \t]+[`'\"]?(?P<rpath>{_PATH})"
    # path:L12-L20 and its variants; "path:" is a prefix some models add
    rf"|{_START}(?:path:[ \t]*)?(?P<path>{_PATH})"
    rf"(?:{_LINE_SEP}L?(?P<start>{_N})(?::{_N})?(?:{_RANGE_DASH}L?(?P<end>{_N})(?::{_N})?)?"
    rf"|[`'\"]?[,:]?[ \t]*(?:\([ \t]*)?(?:(?:at|on)[ \t]+)?[Ll]ines?[ \t]+(?P<wstart>{_N})"
    rf"(?:{_WORD_DASH}(?P<wend>{_N}))?)"
)
_QUOTE = re.compile(r"[ \t]*(?:[:\-\u2013\u2014][ \t]*)?(?:`([^`\n]+)`|\"([^\"\n]+)\")")
_MIN_QUOTE = 3  # non-space characters; a shorter quote (`...`, `x`) checks nothing
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


def _quote_after(text: str, after: int) -> str | None:
    q = _QUOTE.match(text, after)
    if q is None:
        return None
    quote = q.group(1) or q.group(2)
    # The next citation in backticks is not a quote of this one.
    if _REF.search(quote):
        return None
    parts = re.split(r"\.\.\.|\u2026", quote)
    return quote if max(len("".join(p.split())) for p in parts) >= _MIN_QUOTE else None


def parse(text: str) -> list[Ref]:
    refs: list[Ref] = []
    pos = 0
    while (m := _REF.search(text, pos)) is not None:
        pos = m.end()
        opened = m.start()
        if m.group("tb_path"):
            path, start, end = m.group("tb_path"), int(m.group("tb_line")), None
        else:
            path = m.group("path") or m.group("rpath")
            raw_start = m.group("start") or m.group("wstart") or m.group("rstart")
            raw_end = m.group("end") or m.group("wend") or m.group("rend")
            if not _looks_like_path(path):
                # A word, not a path: "as lines 5-8 of x.py" holds a citation after it.
                pos = m.end("path") if m.group("path") else pos
                continue
            start, end = int(raw_start), int(raw_end) if raw_end else None
            if m.group("rpath"):
                opened = m.start("rpath")
        after = m.end()
        # Skip the closing mark of a wrapped citation such as `path:12`.
        if after < len(text) and text[after] in "`'\"" and text[opened - 1 : opened] == text[after]:
            after += 1
        # A quote may follow the bracket around a citation, as in (path:L12) `code`.
        while after < len(text) and text[after] in ")]":
            after += 1
        refs.append(
            Ref(
                cited=m.group(0),
                path=path,
                start=start,
                end=end if end is not None else start,
                offset=(m.start(), after),
                quote=_quote_after(text, after),
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
        spans = shown.get(path, ())
        grounded = any(s <= ref.start and ref.end <= e for s, e in spans)
        if not grounded:
            partly = any(s <= ref.end and ref.start <= e for s, e in spans)
            reason = (
                "only part of the range was in the context shown to the model"
                if partly
                else "lines exist but were not in the context shown to the model"
            )
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


def _sentences(text: str) -> Callable[[int, int], tuple[int, int]]:
    """A lookup of the sentence (or line) around a character range, built in one pass."""
    marks = list(re.finditer(r"[.!?](?=\s|$)|\n", text))
    starts, ends = [m.start() for m in marks], [m.end() for m in marks]

    def around(start: int, end: int) -> tuple[int, int]:
        i = bisect.bisect_right(ends, start) - 1
        j = bisect.bisect_left(starts, end)
        left = ends[i] if i >= 0 else 0
        if j == len(marks):
            return left, len(text)
        m = marks[j]
        return left, m.start() if m.group() == "\n" else m.end()

    return around


def strip_unverified(text: str, pairs: list[tuple[Ref, CitationCheck]]) -> str:
    """Strict mode: drop each sentence that rests on a citation that did not verify."""
    if not pairs:
        return text + "\n\n[vibetter strict: the answer has no citations to verify.]"
    bad = [(ref, c) for ref, c in pairs if not c.verified]
    if not bad:
        return text
    around = _sentences(text)
    spans = sorted(around(*ref.offset) for ref, _ in bad)
    out, pos = [], 0
    for left, right in spans:
        if right <= pos:
            continue
        out.append(text[pos : max(pos, left)])
        pos = right
    out.append(text[pos:])
    notes = "; ".join(f"{c.cited} ({c.reason})" for c in unique(bad))
    return "".join(out).rstrip() + f"\n\n[vibetter strict: removed claims citing {notes}.]"
