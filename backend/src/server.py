import os
import re
import json
from fastmcp import FastMCP
from typing import Dict, Any
from brain.scholar import (
    ask_gemini_with_context,
    generate_architecture_json,
    generate_audio_explanation,
    explain_diff,
    debug_error,
    _blueprint_cache,
)

mcp = FastMCP("VIBETTER Cognitive Bridge", version="1.1.0")


@mcp.tool()
async def scholar_explain(file_path: str, question: str) -> str:
    """
    Explains any file or function in your codebase in plain English.
    Perfect for understanding what AI-generated code actually does.
    Example: file_path="src/api.js", question="Why is async/await used here?"
    """
    return await ask_gemini_with_context(question, target_file=file_path)


@mcp.tool()
async def generate_blueprint() -> Dict[str, Any]:
    """
    Generates an interactive dependency graph of your entire codebase.
    Shows how all files connect to each other. Open ui://blueprint to visualize it.
    """
    return await generate_architecture_json()


@mcp.tool()
async def generate_audio_overview(question: str, file_path: str = None) -> str:
    """
    Creates an MP3 audio walkthrough explaining your codebase like a podcast.
    Great for understanding architecture while away from your screen.
    Example: question="How does authentication work in this app?"
    """
    return await generate_audio_explanation(question, target_file=file_path)


@mcp.tool()
async def explain_last_change() -> str:
    """
    Explains what your AI tool just changed in plain English so you can learn from it.
    Run this immediately after Claude, Cursor, or Copilot makes edits to your code.
    No arguments needed — it reads your git diff automatically.
    """
    return await explain_diff()


@mcp.tool()
async def debug_error_in_context(error_message: str, file_path: str = None) -> str:
    """
    Paste any error message and get a plain-English explanation + exact fix.
    Understands your specific codebase to give precise, actionable answers.
    Example: error_message="TypeError: Cannot read properties of undefined (reading 'map')"
    """
    return await debug_error(error_message, file_path=file_path)


@mcp.resource("ui://blueprint")
async def get_blueprint_ui() -> str:
    """
    Interactive Vue Flow map of your codebase dependency graph.
    Call generate_blueprint first, then open this resource to visualize it.
    """
    dist_dir = os.path.join(
        os.path.dirname(__file__), "..", "..", "frontend", "dist"
    )
    index_path = os.path.join(dist_dir, "index.html")

    if not os.path.exists(index_path):
        return "<h1>Frontend build missing.</h1><p>Run <code>npm run build</code> in the /frontend directory.</p>"

    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Inline CSS assets so the HTML is fully self-contained (MCP resources
    # are served as raw strings — external file references won't resolve).
    for css_match in re.finditer(r'<link[^>]+href="(/assets/[^"]+\.css)"[^>]*>', html):
        css_file = os.path.join(dist_dir, css_match.group(1).lstrip("/"))
        if os.path.exists(css_file):
            with open(css_file, "r", encoding="utf-8") as f:
                html = html.replace(css_match.group(0), f"<style>{f.read()}</style>")

    # Inline JS assets
    for js_match in re.finditer(r'<script[^>]+src="(/assets/[^"]+\.js)"[^>]*></script>', html):
        js_file = os.path.join(dist_dir, js_match.group(1).lstrip("/"))
        if os.path.exists(js_file):
            with open(js_file, "r", encoding="utf-8") as f:
                html = html.replace(js_match.group(0), f'<script type="module">{f.read()}</script>')

    # Inject the latest blueprint data so the UI doesn't need a network call
    import brain.scholar as scholar_module
    cached = scholar_module._blueprint_cache
    blueprint_json = json.dumps(cached) if cached else "null"
    injection = f"<script>window.__VIBETTER_BLUEPRINT__ = {blueprint_json};</script>"
    html = html.replace("</head>", f"{injection}\n</head>", 1)

    return html


if __name__ == "__main__":
    mcp.run()
