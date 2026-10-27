"""`vibetter` console script.

vibetter                      run the MCP server on stdio (same as `vibetter serve`)
vibetter ask "question"       answer in the terminal and check its citations
vibetter search "query"       show the chunks retrieval picks (no LLM, no key)
vibetter verify [FILE]        check the path:line citations in a text (stdin by default)
vibetter index --stats        show what the index contains and skips
"""

from __future__ import annotations

import argparse
import asyncio
import re
import shutil
import sys
import textwrap
import threading

from . import __version__
from .config import VibetterError, load_env


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vibetter", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--version", action="version", version=f"vibetter {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="run the MCP server on stdio (the default)")
    root_help = "codebase directory (default: VIBETTER_CODEBASE_PATH or cwd)"
    ask = sub.add_parser("ask", help="ask a question about the codebase")
    ask.add_argument("question")
    ask.add_argument("--file", help="focus on this file (relative to the root)")
    ask.add_argument("--strict", action="store_true", help="remove claims whose citation fails")
    ask.add_argument("--root", help=root_help)
    search = sub.add_parser("search", help="rank code chunks for a query, without an LLM")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--file", help="search within this file only")
    search.add_argument("--root", help=root_help)
    verify = sub.add_parser("verify", help="check the citations in a text, without an LLM")
    verify.add_argument("path", nargs="?", default="-", help="text file to check (default: stdin)")
    verify.add_argument("--root", help=root_help)
    index = sub.add_parser("index", help="list indexed files, or --stats for a summary")
    index.add_argument("--stats", action="store_true", help="print counts instead of paths")
    index.add_argument("--root", help=root_help)
    return parser


def serve() -> None:
    from .server import Vibetter, build_mcp

    app = Vibetter(watch=True)

    def warm() -> None:
        try:
            stats = app.index().stats()
            print(
                f"vibetter: indexed {stats['files']} files from {stats['root']} "
                f"in {stats['build_seconds']} s",
                file=sys.stderr,
            )
        except VibetterError as e:
            print(f"vibetter: {e}", file=sys.stderr)

    threading.Thread(target=warm, daemon=True).start()
    build_mcp(app).run(show_banner=False)


def _wrap(text: str) -> str:
    """Fit prose to the terminal, never splitting a word (or a citation) or touching code."""
    if not sys.stdout.isatty():
        return text
    width = shutil.get_terminal_size().columns
    out, fenced = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            out.append(line)
            continue
        if fenced or len(line) <= width:
            out.append(line)
            continue
        lead = re.match(r"\s*(?:[-*+] |\d+\. )?", line)
        indent = " " * len(lead.group() if lead else "")
        out.append(
            textwrap.fill(
                line,
                width,
                subsequent_indent=indent,
                break_long_words=False,
                break_on_hyphens=False,
            )
        )
    return "\n".join(out)


def _print_citations(answer) -> None:
    counts = answer.stats.get("citations", {})
    grounded = any(c.grounded is not None for c in answer.citations)
    total = counts.get("total", 0)
    detail = f"{counts.get('valid', 0)} valid" + (
        f", {counts.get('grounded', 0)} grounded" if grounded else ""
    )
    print(f"\ncitations: {total} found, {total - counts.get('unverified', 0)} verified ({detail})")
    for c in answer.citations:
        mark = "ok" if c.verified else "!!"
        line = f"L{c.start}" if c.start == c.end else f"L{c.start}-L{c.end}"
        note = "" if c.verified else f"  ({c.reason})"
        print(f"  {mark} {c.path}:{line}{note}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    load_env()
    try:
        if args.command in (None, "serve"):
            serve()
            return 0
        from .server import Vibetter

        app = Vibetter(args.root, progress=lambda line: print(line, file=sys.stderr, flush=True))
        if args.command == "ask":
            answer = asyncio.run(app.explain(args.question, args.file, args.strict or None))
            print(_wrap(answer.answer))
            _print_citations(answer)
        elif args.command == "search":
            result = asyncio.run(app.search(args.query, args.limit, args.file))
            for hit in result.hits:
                print(f"[{hit.score:.4f} {'+'.join(hit.arms) or 'file order'}]\n{hit.text}")
        elif args.command == "verify":
            if args.path == "-":
                text = sys.stdin.read()
            else:
                with open(args.path, encoding="utf-8") as f:
                    text = f.read()
            answer = asyncio.run(app.verify(text))
            _print_citations(answer)
            return 0 if all(c.verified for c in answer.citations) else 2
        elif args.command == "index":
            index = app.index()
            if args.stats:
                stats = index.stats()
                print(
                    f"root: {stats['root']}\nmode: {stats['mode']}\n"
                    f"files indexed: {stats['files']}\nlines: {stats['lines']}\n"
                    f"chars: {stats['chars']}\nbuild seconds: {stats['build_seconds']}"
                )
                print("skipped:" + ("" if stats["skipped"] else " none"))
                for reason, count in stats["skipped"].items():
                    print(f"  {reason}: {count}")
            else:
                print("\n".join(index.files))
    except (VibetterError, OSError) as e:
        print(f"vibetter: {e}", file=sys.stderr)
        return 1
    return 0
