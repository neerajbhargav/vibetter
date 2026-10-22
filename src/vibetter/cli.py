"""`vibetter` console script.

vibetter                      run the MCP server on stdio (same as `vibetter serve`)
vibetter ask "question"       answer in the terminal, with optional --file
vibetter index --stats        show what the index contains and skips
"""

from __future__ import annotations

import argparse
import asyncio
import sys
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
    ask = sub.add_parser("ask", help="ask a question about the codebase")
    ask.add_argument("question")
    ask.add_argument("--file", help="focus on this file (relative to the root)")
    ask.add_argument("--root", help="codebase directory (default: VIBETTER_CODEBASE_PATH or cwd)")
    index = sub.add_parser("index", help="list indexed files, or --stats for a summary")
    index.add_argument("--stats", action="store_true", help="print counts instead of paths")
    index.add_argument("--root", help="codebase directory (default: VIBETTER_CODEBASE_PATH or cwd)")
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


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    load_env()
    try:
        if args.command in (None, "serve"):
            serve()
        elif args.command == "ask":
            from .server import Vibetter

            print(asyncio.run(Vibetter(args.root).explain(args.question, args.file)))
        elif args.command == "index":
            from .server import Vibetter

            index = Vibetter(args.root).index()
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
    except VibetterError as e:
        print(f"vibetter: {e}", file=sys.stderr)
        return 1
    return 0
