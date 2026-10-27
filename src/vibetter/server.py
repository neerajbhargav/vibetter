"""The MCP server: seven tools and the ui://blueprint resource.

Q&A tools retrieve line-numbered chunks, ask the model, then check each
path:Lstart-Lend citation found in the reply against the index and against the
context the model was shown. search_code and verify_citations make no LLM
call, so a host agent such as Claude Code can use them freely.

Importing this module does no I/O. The codebase is resolved and indexed on
the first tool call (or by `vibetter serve` in a background thread), so the
MCP handshake does not wait for indexing.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from . import __version__, cite, prompts, providers, trace
from .cite import CitationCheck, Spans
from .config import VibetterError, resolve_root, vibetter_home
from .gitdiff import collect_changes, number_lines, shown_spans
from .graph import blueprint
from .index import CodebaseIndex
from .redact import redact
from .retrieve import (
    Embedder,
    Retriever,
    assemble,
    dense_requested,
    fastembed_embedder,
    render,
)
from .trace import traced

LLM = Callable[[str, bool], Awaitable[str]]
UI_DIR = Path(__file__).parent / "ui"
UI_MIME = "text/html;profile=mcp-app"

EXPLAIN_CHARS = 24_000
DEBUG_CHARS = 24_000
AUDIO_CHARS = 16_000
DIFF_CHARS = 40_000
SEARCH_CHARS = 16_000


@dataclass
class Answer:
    answer: str
    citations: list[CitationCheck] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchHit:
    path: str
    start: int
    end: int
    score: float
    arms: list[str]
    text: str


@dataclass
class SearchResult:
    hits: list[SearchHit]
    stats: dict[str, Any] = field(default_factory=dict)


def _strict(value: bool | None) -> bool:
    if value is not None:
        return value
    return os.getenv("VIBETTER_STRICT", "").strip().lower() in ("1", "true", "on", "yes")


def _stats() -> dict[str, Any]:
    return {k: v for k, v in trace.current().items() if k != "tool"}


class Vibetter:
    """Tool logic, shared by the MCP server and the `vibetter` command."""

    def __init__(
        self,
        root: str | Path | None = None,
        llm: LLM | None = None,
        *,
        watch: bool = False,
        debounce: float = 0.3,
        embedder: Embedder | bool = True,
        progress: Callable[[str], None] | None = None,
    ):
        self._root = root
        self._progress = progress
        self._llm = llm
        self._watch = watch
        self._debounce = debounce
        self._embedder: Embedder | bool | None = embedder
        self._index: CodebaseIndex | None = None
        self._retriever: Retriever | None = None
        self._retriever_version = -1
        self._lock = threading.Lock()
        self.blueprint: dict[str, Any] | None = None

    def index(self) -> CodebaseIndex:
        with self._lock:
            if self._index is None:
                index = CodebaseIndex(resolve_root(self._root), debounce=self._debounce)
                index.build()
                if self._watch:
                    index.start_watching()
                self._index = index
            return self._index

    def retriever(self) -> Retriever:
        """The search index for the current files, rebuilt after the files change."""
        index = self.index()
        with self._lock:
            version = index.version
            if self._retriever is None or self._retriever_version != version:
                if self._embedder is True:
                    self._embedder = fastembed_embedder() if dense_requested() else None
                embedder = self._embedder if callable(self._embedder) else None
                self._retriever = Retriever(index.files, self._retriever, embedder)
                self._retriever_version = version
            return self._retriever

    def _gather(self, query: str, target: str | None, budget: int) -> tuple[Retriever, str, Spans]:
        """Retrieve and pack context: the target file first, then the best chunks,
        then the first chunk of each file as a fallback for broad questions."""
        r = self.retriever()
        rel = self.index().resolve(target) if target else None
        hits = r.search(query, within=rel) if rel else []
        hits += [h for h in r.search(query) if h.chunk.path != rel]
        context, shown, used = assemble(r.files, [h.chunk for h in hits] + r.heads(), budget)
        trace.note(
            retrieval="bm25+symbol" + ("+dense" if r.embedder else ""),
            chunks_retrieved=len(hits),
            chunks_in_context=used,
            context_chars=len(context),
        )
        if self._progress is not None:
            self._progress(
                f"context: {used} chunks, {len(context):,} characters from {len(shown)} files;"
                " asking the model"
            )
        return r, context, shown

    async def ask_llm(self, prompt: str, json_mode: bool = False) -> str:
        """The one exit point for text leaving the machine: always redacted."""
        text = redact(prompt)
        trace.note(prompt_chars=len(text))
        if self._llm is not None:
            trace.note(provider="injected")
            return await self._llm(text, json_mode)
        return await providers.call_llm(text, json_mode)

    def _verified(
        self, reply: str, files: Mapping[str, str], shown: Spans | None, strict: bool | None
    ) -> Answer:
        pairs = cite.check(reply, files, shown, self.index().root)
        checks = cite.unique(pairs)
        trace.note(citations=cite.counts(checks))
        if _strict(strict):
            reply = cite.strip_unverified(reply, pairs)
            trace.note(strict=True)
        return Answer(reply, checks, _stats())

    @traced("scholar_explain")
    async def explain(
        self, question: str, file_path: str | None = None, strict: bool | None = None
    ) -> Answer:
        r, context, shown = await asyncio.to_thread(
            self._gather, question, file_path, EXPLAIN_CHARS
        )
        reply = await self.ask_llm(prompts.explain(question, context, file_path))
        return await asyncio.to_thread(self._verified, reply, r.files, shown, strict)

    @traced("debug_error_in_context")
    async def debug(
        self, error_message: str, file_path: str | None = None, strict: bool | None = None
    ) -> Answer:
        r, context, shown = await asyncio.to_thread(
            self._gather, error_message, file_path, DEBUG_CHARS
        )
        reply = await self.ask_llm(prompts.debug(error_message, context, file_path))
        return await asyncio.to_thread(self._verified, reply, r.files, shown, strict)

    @traced("explain_last_change")
    async def explain_changes(self, strict: bool | None = None) -> Answer:
        index = await asyncio.to_thread(self.index)
        label, diff = await asyncio.to_thread(collect_changes, index.root, DIFF_CHARS)
        numbered, shown = number_lines(diff), shown_spans(diff)
        trace.note(context_chars=len(numbered))
        reply = await self.ask_llm(prompts.explain_diff(label, numbered))
        # The diff is read from git now, and the watcher may not have caught up yet.
        await asyncio.to_thread(index.refresh, shown)
        return await asyncio.to_thread(self._verified, reply, index.files, shown, strict)

    @traced("search_code")
    async def search(
        self, query: str, limit: int = 8, file_path: str | None = None
    ) -> SearchResult:
        r = await asyncio.to_thread(self.retriever)
        rel = self.index().resolve(file_path) if file_path else None
        limit = max(1, min(limit, 50))
        hits = await asyncio.to_thread(r.search, query, rel, limit)
        out: list[SearchHit] = []
        used = 0
        for h in hits:
            # The host agent sends these hits to its own model, so they leave the machine too.
            text = redact(render(r.files, h.chunk))
            if out and used + len(text) > SEARCH_CHARS:
                break
            out.append(SearchHit(h.chunk.path, h.chunk.start, h.chunk.end, h.score, h.arms, text))
            used += len(text)
        trace.note(
            retrieval="bm25+symbol" + ("+dense" if r.embedder else ""),
            chunks_retrieved=len(out),
            context_chars=used,
        )
        return SearchResult(out, _stats())

    @traced("verify_citations")
    async def verify(self, text: str, strict: bool | None = None) -> Answer:
        index = await asyncio.to_thread(self.index)
        return await asyncio.to_thread(self._verified, text, index.files, None, strict)

    @traced("generate_blueprint")
    async def make_blueprint(self, labels: bool = False) -> dict[str, Any]:
        index = await asyncio.to_thread(self.index)
        graph = await asyncio.to_thread(blueprint, index.files)
        if labels and graph["nodes"]:
            reply = await self.ask_llm(
                prompts.blueprint_labels(
                    [n["id"] for n in graph["nodes"]],
                    [(e["source"], e["target"]) for e in graph["edges"]],
                ),
                json_mode=True,
            )
            groups = parse_json(reply).get("groups")
            if not isinstance(groups, dict):
                raise VibetterError("The model's label JSON needs a 'groups' object.")
            label_of = {
                path: str(name)
                for name, paths in groups.items()
                if isinstance(paths, list)
                for path in paths
                if isinstance(path, str)
            }
            for node in graph["nodes"]:
                if node["id"] in label_of:
                    node["data"]["group"] = label_of[node["id"]]
            graph["stats"]["labels"] = "model-assigned groups"
        trace.note(graph={k: v for k, v in graph["stats"].items() if isinstance(v, int)})
        self.blueprint = graph
        return graph

    @traced("generate_audio_overview")
    async def audio(self, question: str, file_path: str | None = None) -> str:
        import gtts

        _, context, _ = await asyncio.to_thread(self._gather, question, file_path, AUDIO_CHARS)
        transcript = await self.ask_llm(prompts.audio(question, context, file_path))
        out_dir = vibetter_home() / "outputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"vibetter_{time.time_ns()}.mp3"
        try:
            await asyncio.to_thread(gtts.gTTS(text=transcript, lang="en").save, str(path))
        except (gtts.gTTSError, OSError) as e:
            raise VibetterError(f"Text-to-speech failed: {e}") from e
        preview = transcript[:400] + ("..." if len(transcript) > 400 else "")
        return f"Audio saved to: {path}\n\nTranscript preview:\n{preview}"


def parse_json(reply: str) -> dict[str, Any]:
    text = reply.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise VibetterError(f"The model did not return valid JSON ({e}).") from e
    if not isinstance(data, dict):
        raise VibetterError("The model returned JSON that is not an object.")
    return data


def blueprint_html(graph: dict[str, Any] | None) -> str:
    index_html = UI_DIR / "index.html"
    if not index_html.is_file():
        return "<h1>Blueprint UI missing.</h1><p>Run <code>npm run build</code> in frontend/.</p>"
    html = index_html.read_text(encoding="utf-8")

    # MCP resources are served as one string, so inline the built assets.
    def inline(match: re.Match[str], tag: str) -> str:
        asset = UI_DIR / match.group(1).lstrip("/")
        if not asset.is_file():
            return match.group(0)
        body = asset.read_text(encoding="utf-8")
        if tag == "style":
            return f"<style>{body}</style>"
        return f'<script type="module">{body}</script>'

    html = re.sub(
        r'<link[^>]+href="(/assets/[^"]+\.css)"[^>]*>', lambda m: inline(m, "style"), html
    )
    html = re.sub(
        r'<script[^>]+src="(/assets/[^"]+\.js)"[^>]*></script>', lambda m: inline(m, "script"), html
    )
    # File paths come from the repo: escape "</" so they cannot close the script tag.
    data = json.dumps(graph, indent=1).replace("</", "<\\/") if graph else "null"
    return html.replace(
        "</head>", f"<script>window.__VIBETTER_BLUEPRINT__ = {data};</script>\n</head>", 1
    )


async def _tool(call: Awaitable[Any]) -> Any:
    try:
        return await call
    except VibetterError as e:
        raise ToolError(str(e)) from e


# MCP Apps hosts render ui://blueprint inline next to the tool result. The
# flat key is the older draft's spelling, kept for hosts that still read it.
BLUEPRINT_META = {"ui": {"resourceUri": "ui://blueprint"}, "ui/resourceUri": "ui://blueprint"}


def build_mcp(app: Vibetter) -> FastMCP:
    mcp = FastMCP("VIBETTER", version=__version__)

    @mcp.tool
    async def scholar_explain(file_path: str, question: str, strict: bool | None = None) -> Answer:
        """Answer a question about one file, from that file and the most relevant
        chunks of the rest of the repo, with checked citations.

        file_path is relative to the project root, for example "src/api.js".
        Each path:Lstart-Lend citation in the answer comes back checked: valid
        (the file and lines exist) and grounded (every cited line was in the
        context the model saw). strict=true removes sentences whose citation fails.
        """
        return await _tool(app.explain(question, file_path, strict))

    @mcp.tool
    async def explain_last_change(strict: bool | None = None) -> Answer:
        """Explain the latest change: uncommitted edits (staged, unstaged and new
        untracked files), or the last commit when the tree is clean. Citations
        are checked against the diff hunks that were shown."""
        return await _tool(app.explain_changes(strict))

    @mcp.tool
    async def debug_error_in_context(
        error_message: str, file_path: str | None = None, strict: bool | None = None
    ) -> Answer:
        """Diagnose an error message against the codebase and propose a fix.
        Traceback frames in the message steer retrieval; citations are checked."""
        return await _tool(app.debug(error_message, file_path, strict))

    @mcp.tool
    async def search_code(query: str, limit: int = 8, file_path: str | None = None) -> SearchResult:
        """Find the code chunks most relevant to a query, with no LLM call.

        Ranks chunks with BM25 and a symbol and file-name index (plus
        embeddings with the dense extra and VIBETTER_DENSE=1), fused by
        reciprocal rank. Each
        hit is line-numbered, so you can cite it as path:Lstart-Lend.
        file_path limits the search to one file.
        """
        return await _tool(app.search(query, limit, file_path))

    @mcp.tool
    async def verify_citations(text: str, strict: bool | None = None) -> Answer:
        """Check each path:line citation found in a text against the indexed files,
        with no LLM call. Reports, per citation, whether the file and lines
        exist and whether a quoted snippet matches. Use it on your own answers."""
        return await _tool(app.verify(text, strict))

    @mcp.tool(meta=BLUEPRINT_META)
    async def generate_blueprint(labels: bool = False) -> dict[str, Any]:
        """Build the file dependency graph from static imports (Python ast, plus
        JS/TS/Vue import parsing) with a deterministic layout. labels=true asks
        the model to name groups of files; the graph itself never comes from the
        model. Hosts with MCP Apps show it inline; otherwise open ui://blueprint."""
        return await _tool(app.make_blueprint(labels))

    @mcp.tool
    async def generate_audio_overview(question: str, file_path: str | None = None) -> str:
        """Write a spoken MP3 walkthrough of a question about the codebase.
        Uses gTTS, which sends the transcript to Google's text-to-speech service."""
        return await _tool(app.audio(question, file_path))

    @mcp.resource("ui://blueprint", mime_type=UI_MIME)
    async def blueprint_ui() -> str:
        """Interactive Vue Flow view of the dependency graph."""
        graph = app.blueprint
        if graph is None:
            try:
                index = await asyncio.to_thread(app.index)
                graph = await asyncio.to_thread(blueprint, index.files)
            except VibetterError:
                graph = None
        return blueprint_html(graph)

    return mcp


def create_server(
    root: str | Path | None = None,
    llm: LLM | None = None,
    *,
    watch: bool = False,
    debounce: float = 0.3,
    embedder: Embedder | bool = False,
) -> FastMCP:
    """The test and eval seam. Dense retrieval is off unless an embedder is given."""
    return build_mcp(Vibetter(root, llm, watch=watch, debounce=debounce, embedder=embedder))
