"""The MCP server: five tools and the ui://blueprint resource.

Importing this module does no I/O. The codebase is resolved and indexed on
the first tool call (or by `vibetter serve` in a background thread), so the
MCP handshake does not wait for indexing.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from . import __version__, prompts, providers
from .config import VibetterError, resolve_root, vibetter_home
from .gitdiff import collect_changes
from .index import CodebaseIndex
from .redact import redact

LLM = Callable[[str, bool], Awaitable[str]]
UI_DIR = Path(__file__).parent / "ui"

EXPLAIN_CHARS = 40_000
OVERVIEW_CHARS = 60_000
BLUEPRINT_CHARS = 50_000
DEBUG_CHARS = 30_000
DIFF_CHARS = 40_000


class Vibetter:
    """Tool logic, shared by the MCP server and the `vibetter ask` command."""

    def __init__(
        self,
        root: str | Path | None = None,
        llm: LLM | None = None,
        *,
        watch: bool = False,
        debounce: float = 0.3,
    ):
        self._root = root
        self._llm = llm
        self._watch = watch
        self._debounce = debounce
        self._index: CodebaseIndex | None = None
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

    async def _context(self, target: str | None, max_chars: int) -> str:
        index = await asyncio.to_thread(self.index)
        return await asyncio.to_thread(index.context, target, max_chars)

    async def ask_llm(self, prompt: str, json_mode: bool = False) -> str:
        """The one exit point for text leaving the machine: always redacted."""
        llm = self._llm or providers.call_llm
        return await llm(redact(prompt), json_mode)

    async def explain(self, question: str, file_path: str | None = None) -> str:
        budget = EXPLAIN_CHARS if file_path else OVERVIEW_CHARS
        context = await self._context(file_path, budget)
        return await self.ask_llm(prompts.explain(question, context, file_path))

    async def debug(self, error_message: str, file_path: str | None = None) -> str:
        context = await self._context(file_path, DEBUG_CHARS)
        return await self.ask_llm(prompts.debug(error_message, context, file_path))

    async def explain_changes(self) -> str:
        root = resolve_root(self._root)
        label, diff = await asyncio.to_thread(collect_changes, root, DIFF_CHARS)
        return await self.ask_llm(prompts.explain_diff(label, diff))

    async def make_blueprint(self) -> dict[str, Any]:
        context = await self._context(None, BLUEPRINT_CHARS)
        reply = await self.ask_llm(prompts.blueprint(context), json_mode=True)
        self.blueprint = parse_graph(reply)
        return self.blueprint

    async def audio(self, question: str, file_path: str | None = None) -> str:
        import gtts

        context = await self._context(file_path, EXPLAIN_CHARS)
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


def parse_graph(reply: str) -> dict[str, Any]:
    text = reply.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        graph = json.loads(text)
    except json.JSONDecodeError as e:
        raise VibetterError(f"The model did not return valid blueprint JSON ({e}).") from e
    if not (
        isinstance(graph, dict)
        and isinstance(graph.get("nodes"), list)
        and isinstance(graph.get("edges"), list)
    ):
        raise VibetterError("The model's blueprint JSON needs 'nodes' and 'edges' lists.")
    return graph


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
    # The graph is model output: escape "</" so it cannot close the script tag.
    data = json.dumps(graph, indent=1).replace("</", "<\\/") if graph else "null"
    return html.replace(
        "</head>", f"<script>window.__VIBETTER_BLUEPRINT__ = {data};</script>\n</head>", 1
    )


async def _tool(call: Awaitable[Any]) -> Any:
    try:
        return await call
    except VibetterError as e:
        raise ToolError(str(e)) from e


def build_mcp(app: Vibetter) -> FastMCP:
    mcp = FastMCP("VIBETTER", version=__version__)

    @mcp.tool
    async def scholar_explain(file_path: str, question: str) -> str:
        """Answer a question about one file, using that file and nearby files as context.

        file_path is relative to the project root, for example "src/api.js".
        The answer cites path:line from line-numbered source.
        """
        return await _tool(app.explain(question, file_path))

    @mcp.tool
    async def explain_last_change() -> str:
        """Explain the latest change: uncommitted edits (staged, unstaged and new
        untracked files), or the last commit when the tree is clean."""
        return await _tool(app.explain_changes())

    @mcp.tool
    async def debug_error_in_context(error_message: str, file_path: str | None = None) -> str:
        """Diagnose an error message against the codebase and propose a fix."""
        return await _tool(app.debug(error_message, file_path))

    @mcp.tool
    async def generate_blueprint() -> dict[str, Any]:
        """Ask the model for a file dependency graph (model-inferred, not static
        analysis). Open the ui://blueprint resource afterwards to view it."""
        return await _tool(app.make_blueprint())

    @mcp.tool
    async def generate_audio_overview(question: str, file_path: str | None = None) -> str:
        """Write a spoken MP3 walkthrough of a question about the codebase.
        Uses gTTS, which sends the transcript to Google's text-to-speech service."""
        return await _tool(app.audio(question, file_path))

    @mcp.resource("ui://blueprint", mime_type="text/html")
    def blueprint_ui() -> str:
        """Interactive Vue Flow view of the last generated blueprint."""
        return blueprint_html(app.blueprint)

    return mcp


def create_server(
    root: str | Path | None = None,
    llm: LLM | None = None,
    *,
    watch: bool = False,
    debounce: float = 0.3,
) -> FastMCP:
    return build_mcp(Vibetter(root, llm, watch=watch, debounce=debounce))
