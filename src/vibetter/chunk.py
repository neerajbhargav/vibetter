"""Split files into line-numbered chunks for retrieval.

A chunk is a span of whole lines, 1-based and inclusive. Chunks aim for
TARGET lines and never exceed MAX_LINES. They end at the best boundary in
range: for Python, a top-level def or class (from `ast`); for other files,
a blank line at brace depth 0. Only a forced cut, where no boundary exists,
repeats OVERLAP lines at the start of the next chunk.
"""

from __future__ import annotations

import ast

TARGET = 60
MAX_LINES = 120
OVERLAP = 5


def split_lines(text: str) -> list[str]:
    """Lines numbered the way git and editors number them.

    str.splitlines() also breaks on form feeds, \\x1c-\\x1e and \\u2028, which
    would shift every later line number away from what the user sees.
    """
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


# Boundary quality before a line (lower is better). None means "not a boundary".
_TOP_DEF, _STATEMENT, _BLANK = 0, 1, 2


def _python_scores(text: str, lines: list[str]) -> list[int | None] | None:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    scores: list[int | None] = [None] * (len(lines) + 1)

    def mark(node: ast.stmt, score: int) -> None:
        decorators = getattr(node, "decorator_list", [])
        start = min([node.lineno] + [d.lineno for d in decorators]) - 1
        if start >= len(lines):  # ast also breaks lines on a lone \r; split_lines does not
            return
        # Comments directly above a definition belong to it.
        while start > 0 and lines[start - 1].lstrip().startswith("#"):
            start -= 1
        current = scores[start]
        scores[start] = score if current is None else min(current, score)

    defs = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in tree.body:
        mark(node, _TOP_DEF if isinstance(node, defs) else _STATEMENT)
    for node in ast.walk(tree):
        if isinstance(node, defs) and node not in tree.body:
            mark(node, _STATEMENT)
    for i in range(1, len(lines)):
        if scores[i] is None and not lines[i - 1].strip():
            scores[i] = _BLANK
    return scores


def _brace_scores(lines: list[str], markdown: bool) -> list[int | None]:
    scores: list[int | None] = [None] * (len(lines) + 1)
    depth = 0
    for i, line in enumerate(lines):
        # ponytail: braces inside strings and comments count too; a tokenizer if it misleads.
        if i > 0:
            blank_before = not lines[i - 1].strip()
            if markdown and line.startswith("#"):
                scores[i] = _TOP_DEF
            elif depth <= 0:
                scores[i] = _TOP_DEF if blank_before else _STATEMENT
            elif blank_before:
                scores[i] = _BLANK
        depth += line.count("{") - line.count("}")
    return scores


def boundary_scores(path: str, text: str, lines: list[str]) -> list[int | None]:
    if path.endswith((".py", ".pyi")):
        scores = _python_scores(text, lines)
        if scores is not None:
            return scores
    return _brace_scores(lines, markdown=path.endswith((".md", ".mdx", ".rst")))


def chunk_lines(
    path: str,
    text: str,
    target: int = TARGET,
    max_lines: int = MAX_LINES,
    overlap: int = OVERLAP,
) -> list[tuple[int, int]]:
    """Return (start, end) line spans, 1-based and inclusive, covering every line."""
    lines = split_lines(text)
    n = len(lines)
    if n == 0:
        return []
    scores = boundary_scores(path, text, lines)
    spans: list[tuple[int, int]] = []
    start = 0  # 0-based index of the chunk's first line
    while start < n:
        if n - start <= target + target // 2:
            spans.append((start + 1, n))
            break
        lo, hi = start + target // 2, min(start + max_lines, n - 1)
        candidates = [
            (score, abs(b - start - target), b)
            for b in range(lo, hi + 1)
            if (score := scores[b]) is not None
        ]
        if candidates:
            cut = min(candidates)[2]
            spans.append((start + 1, cut))
            start = cut
        else:
            cut = start + target
            spans.append((start + 1, cut))
            start = cut - overlap
    return spans
