"""Retrieval: which chunks of the codebase a question should see.

Three ranked arms, fused by reciprocal rank fusion (RRF, k=60):
- BM25 over a code-aware tokenizer (camelCase, snake_case and path segments
  are split; the whole identifier is kept as well),
- a symbol and path index (definitions from `ast` for Python and from
  regexes for JS, TS and Vue; file names; file:line references such as
  traceback frames), matched only by identifiers written as code. A chunk at
  a file:line the query names is ranked first,
- optionally a dense arm (`pip install 'vibetter[dense]'`: fastembed with
  BAAI/bge-small-en-v1.5).

assemble() packs ranked chunks into a character budget. Each block has a
`--- path:Lstart-Lend ---` header and `NNN| ` line prefixes, and the spans
it shows are returned so citations can be checked against them.
"""

from __future__ import annotations

import ast
import math
import os
import posixpath
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from . import cite
from .chunk import chunk_lines, split_lines
from .config import vibetter_home

Embedder = Callable[[list[str], bool], Sequence[Sequence[float]]]
DENSE_MODEL = "BAAI/bge-small-en-v1.5"
RRF_K = 60
DENSE_TOP = 50

_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_PARTS = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
STOP = frozenset(
    """a an and are as at be by can do does did for from has have how i if in into is it
    its of on or that the their then there these this to was what when where which who
    why will with you your me my we our explain show tell find code file files work works
    def class return self import none true false null const let var function new
    """.split()
)
JS_LIKE = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte")
_JS_DEFS = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?(?:async\s+)?"
    r"(?:function\s*\*?|class|interface|type|enum|const|let|var)\s+([A-Za-z_$][\w$]*)",
    re.MULTILINE,
)
_JS_METHOD = re.compile(r"^\s+(?:async\s+)?(?:static\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{")
_GENERIC_DEFS = re.compile(
    r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:func|fn|def|class|struct|trait|interface|module)\s+"
    r"([A-Za-z_]\w*)",
    re.MULTILINE,
)
_KEYWORDS = frozenset({"if", "for", "while", "switch", "catch", "function", "return", "with"})
_CAMEL = re.compile(r"[a-z][A-Z]|[A-Z]{2}[a-z]")


def split_identifier(ident: str) -> list[str]:
    """camelCase, PascalCase and snake_case parts, lowercased."""
    return [p.lower() for p in _PARTS.findall(ident)]


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    for ident in _IDENT.findall(text):
        whole = ident.lower().strip("_$")
        if len(whole) < 2 or whole in STOP:
            continue
        out.append(whole)
        parts = split_identifier(ident)
        if len(parts) > 1:
            out.extend(p for p in parts if len(p) > 1 and p not in STOP)
    return out


def code_words(query: str) -> set[str]:
    """The query's identifiers that are written as code, lowercased.

    snake_case, camelCase, dotted names (click.File, cart.py), calls (extend()),
    keyword arguments (json=) and `backticked` names count. Plain English words
    are left to BM25: matched against definition names, words such as
    "redirect" pulled in every test_redirect_* function (see eval/README.md).
    """
    words: set[str] = set()
    for m in _IDENT.finditer(query):
        ident, start, end = m.group(), m.start(), m.end()
        before, after = query[start - 1 : start], query[end : end + 1]
        dotted = (before == "." and query[start - 2 : start - 1].isalnum()) or (
            after == "." and query[end + 1 : end + 2].isalnum()
        )
        if (
            "_" in ident.strip("_")
            or "$" in ident
            or _CAMEL.search(ident)
            or dotted
            or before == "`"
            or after in ("`", "(", "=")
        ):
            words.add(ident.lower())
    return {w for w in words if len(w) > 2} - STOP


def definitions(path: str, text: str) -> list[tuple[str, int]]:
    """(name, line) for each function, class and top-level name defined in the file."""
    found: list[tuple[str, int]] = []
    if path.endswith((".py", ".pyi")):
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    found.append((node.name, node.lineno))
            for node in tree.body:
                targets = node.targets if isinstance(node, ast.Assign) else []
                if isinstance(node, ast.AnnAssign):
                    targets = [node.target]
                found += [(t.id, node.lineno) for t in targets if isinstance(t, ast.Name)]
            return found
    pattern = _JS_DEFS if path.endswith(JS_LIKE) else _GENERIC_DEFS
    for m in pattern.finditer(text):
        found.append((m.group(1), text.count("\n", 0, m.start(1)) + 1))
    if path.endswith(JS_LIKE):
        for n, line in enumerate(split_lines(text), 1):
            m = _JS_METHOD.match(line)
            if m and m.group(1) not in _KEYWORDS:
                found.append((m.group(1), n))
    return found


@dataclass(frozen=True)
class Chunk:
    path: str
    start: int
    end: int


@dataclass
class Hit:
    chunk: Chunk
    score: float
    arms: list[str] = field(default_factory=list)


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.75):
        self.k1, self.b = k1, b
        self.n = len(docs)
        self.lens = [len(d) for d in docs]
        self.avg = (sum(self.lens) / self.n) if self.n else 1.0
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, doc in enumerate(docs):
            for term, tf in Counter(doc).items():
                self.postings[term].append((i, tf))

    def scores(self, terms: Iterable[str]) -> dict[int, float]:
        out: dict[int, float] = defaultdict(float)
        for term in set(terms):
            posting = self.postings.get(term)
            if not posting:
                continue
            df = len(posting)
            idf = math.log(1 + (self.n - df + 0.5) / (df + 0.5))
            for i, tf in posting:
                norm = self.k1 * (1 - self.b + self.b * self.lens[i] / (self.avg or 1.0))
                out[i] += idf * tf * (self.k1 + 1) / (tf + norm)
        return out


def _ranked(scores: Mapping[int, float]) -> list[int]:
    return sorted((i for i, s in scores.items() if s > 0), key=lambda i: (-scores[i], i))


def rrf(rankings: Iterable[list[int]], k: int = RRF_K) -> dict[int, float]:
    fused: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for rank, i in enumerate(ranking, 1):
            fused[i] += 1.0 / (k + rank)
    return fused


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class Retriever:
    """An immutable search index over one snapshot of the codebase's files."""

    def __init__(
        self,
        files: Mapping[str, str],
        previous: Retriever | None = None,
        embedder: Embedder | None = None,
    ):
        self.files = dict(files)
        self.embedder = embedder
        old = previous._per_file if previous is not None else {}
        self._vectors: dict[str, Sequence[float]] = previous._vectors if previous else {}
        self._per_file: dict[str, tuple[str, list[tuple[int, int]], list[list[str]]]] = {}
        self.chunks: list[Chunk] = []
        self.by_path: dict[str, list[int]] = {}
        docs: list[list[str]] = []
        self.defs: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for path in sorted(self.files):
            text = self.files[path]
            cached = old.get(path)
            if cached is not None and cached[0] == text:
                entry = cached
            else:
                lines = split_lines(text)
                spans = chunk_lines(path, text)
                path_tokens = tokenize(path.replace("/", " "))
                tokens = [path_tokens + tokenize("\n".join(lines[s - 1 : e])) for s, e in spans]
                entry = (text, spans, tokens)
            self._per_file[path] = entry
            ids = []
            for (s, e), toks in zip(entry[1], entry[2], strict=True):
                ids.append(len(self.chunks))
                self.chunks.append(Chunk(path, s, e))
                docs.append(toks)
            self.by_path[path] = ids
            for name, line in definitions(path, text):
                self.defs[name.lower()].append((path, line))
        self.bm25 = BM25(docs)
        self.parts: dict[str, set[str]] = defaultdict(set)
        for name in self.defs:
            parts = split_identifier(name)
            for part in parts if len(parts) > 1 else ():
                self.parts[part].add(name)

    def chunk_at(self, path: str, line: int) -> int | None:
        for i in self.by_path.get(path, ()):
            if self.chunks[i].start <= line <= self.chunks[i].end:
                return i
        return None

    def text(self, chunk: Chunk) -> str:
        lines = split_lines(self.files[chunk.path])
        return "\n".join(lines[chunk.start - 1 : chunk.end])

    def _symbol_scores(self, query: str) -> dict[int, float]:
        scores: dict[int, float] = defaultdict(float)
        words = code_words(query)

        def add(path: str, line: int, weight: float) -> None:
            i = self.chunk_at(path, line)
            if i is not None:
                scores[i] += weight

        for word in words:
            for path, line in self.defs.get(word, ()):
                add(path, line, 3.0)  # the definition itself
            for name in self.parts.get(word, ()):
                for path, line in self.defs[name]:
                    add(path, line, 1.0)  # a definition whose name contains the word
        lowered = query.lower()
        for path, ids in self.by_path.items():
            stem = posixpath.splitext(posixpath.basename(path))[0].lower()
            if stem in words or path.lower() in lowered:
                for i in ids:
                    scores[i] += 2.0
        for i in self._named(query):
            scores[i] += 5.0
        return scores

    def _named(self, query: str) -> set[int]:
        """Chunks at a file:line the query names, such as a traceback frame."""
        named: set[int] = set()
        for ref in cite.parse(query):
            path, _ = cite.resolve(ref.path, self.files)
            for i in self.by_path.get(path or "", ()):
                c = self.chunks[i]
                if c.start <= ref.end and ref.start <= c.end:
                    named.add(i)
        return named

    def _dense_scores(self, query: str) -> dict[int, float]:
        if self.embedder is None or not self.chunks:
            return {}
        texts = [self.text(c) for c in self.chunks]
        missing = [t for t in dict.fromkeys(texts) if t not in self._vectors]
        if missing:
            for t, v in zip(missing, self.embedder(missing, False), strict=True):
                self._vectors[t] = v
        q = self.embedder([query], True)[0]
        # ponytail: brute-force cosine in Python; numpy or an ANN index past ~50k chunks.
        sims = {i: _cosine(q, self._vectors[t]) for i, t in enumerate(texts)}
        return {i: sims[i] for i in _ranked(sims)[:DENSE_TOP]}

    def search(self, query: str, within: str | None = None, limit: int | None = None) -> list[Hit]:
        """Chunks ranked for the query. With `within`, every chunk of that file,
        ranked first by relevance, then the rest in line order."""
        arms = {
            "bm25": _ranked(self.bm25.scores(tokenize(query))),
            "symbol": _ranked(self._symbol_scores(query)),
            "dense": _ranked(self._dense_scores(query)),
        }
        fused = rrf(arms.values())
        which: dict[int, list[str]] = defaultdict(list)
        for name, ranking in arms.items():
            for i in ranking:
                which[i].append(name)
        order = sorted(fused, key=lambda i: (-fused[i], i))
        # A line the query names is the strongest signal, so it goes first, not just
        # one rank up: in a fused ranking, BM25 alone can outvote it.
        named = self._named(query)
        order = [i for i in order if i in named] + [i for i in order if i not in named]
        if within is not None:
            mine = set(self.by_path.get(within, ()))
            order = [i for i in order if i in mine]
            order += [i for i in self.by_path.get(within, ()) if i not in fused]
        hits = [Hit(self.chunks[i], round(fused.get(i, 0.0), 6), which[i]) for i in order]
        return hits[:limit] if limit is not None else hits

    def heads(self) -> list[Chunk]:
        """The first chunk of every file, READMEs first: the fallback for broad questions."""

        def key(path: str) -> tuple[bool, int, str]:
            readme = posixpath.basename(path).lower().startswith("readme")
            return (not readme, path.count("/"), path)

        return [
            self.chunks[self.by_path[p][0]]
            for p in sorted(self.by_path, key=key)
            if self.by_path[p]
        ]


def _width(text: str) -> int:
    return max(3, len(str(text.count("\n") + 1)))


def _block(path: str, lines: list[str], start: int, end: int, width: int) -> str:
    body = "".join(f"{n:>{width}}| {lines[n - 1]}\n" for n in range(start, end + 1))
    return f"--- {path}:L{start}-L{end} ---\n{body}\n"


def render(files: Mapping[str, str], chunk: Chunk) -> str:
    """One chunk as a context block: header plus `NNN| ` numbered lines."""
    text = files[chunk.path]
    return _block(chunk.path, split_lines(text), chunk.start, chunk.end, _width(text))


def assemble(
    files: Mapping[str, str], chunks: Iterable[Chunk], budget: int
) -> tuple[str, dict[str, list[tuple[int, int]]], int]:
    """Pack chunks, in order, into `budget` characters.

    A chunk that does not fit is skipped and packing continues. Spans from one
    file are merged and shown in line order. Returns (context, shown spans,
    number of chunks used).
    """
    picked: dict[str, list[tuple[int, int]]] = {}
    lines_of: dict[str, list[str]] = {}
    used, count = 0, 0
    for c in chunks:
        spans = picked.get(c.path, [])
        if any(s <= c.start and c.end <= e for s, e in spans):
            continue
        lines = lines_of.setdefault(c.path, split_lines(files[c.path]))
        cost = len(_block(c.path, lines, c.start, c.end, _width(files[c.path])))
        if used + cost > budget:
            continue
        picked.setdefault(c.path, []).append((c.start, c.end))
        used += cost
        count += 1
    shown: dict[str, list[tuple[int, int]]] = {}
    out: list[str] = []
    for path, spans in picked.items():
        merged: list[tuple[int, int]] = []
        for s, e in sorted(spans):
            if merged and s <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        shown[path] = merged
        width = _width(files[path])
        out += [_block(path, lines_of[path], s, e, width) for s, e in merged]
    return "".join(out), shown, count


def fastembed_embedder() -> Embedder | None:
    """The dense arm, when the `dense` extra is installed and VIBETTER_DENSE is not 0."""
    if os.getenv("VIBETTER_DENSE", "").strip().lower() in ("0", "false", "off", "no"):
        return None
    try:
        from fastembed import TextEmbedding  # pyright: ignore[reportMissingImports]
    except ImportError:
        return None
    model: list[Any] = []

    def embed(texts: list[str], query: bool) -> list[list[float]]:
        if not model:  # loads (and on first use downloads) the model
            model.append(TextEmbedding(DENSE_MODEL, cache_dir=str(vibetter_home() / "models")))
        vectors = model[0].query_embed(texts) if query else model[0].embed(texts)
        return [[float(x) for x in v] for v in vectors]

    return embed
