import os
from fastmcp import FastMCP
from typing import Dict, Any
from brain.scholar import ask_gemini_with_context, generate_architecture_json, generate_audio_explanation

# Initialize FastMCP Server exposing protocol standard tools and resources
mcp = FastMCP("VIBETTER Cognitive Bridge", version="1.0.0")

@mcp.tool()
async def scholar_explain(file_path: str, question: str) -> str:
    """
    Answers "Why" questions about a file/function with mandatory source-grounding.
    Uses Gemini 3.1 Pro's 2M+ context window.
    """
    return await ask_gemini_with_context(question, target_file=file_path)

@mcp.tool()
async def generate_blueprint() -> Dict[str, Any]:
    """
    Uses Gemini's Structured Output to return a dependency graph JSON for Vue Flow.
    """
    return await generate_architecture_json()

@mcp.tool()
async def generate_audio_overview(question: str, file_path: str = None) -> str:
    """
    Multimodal Code Podcast generator! Creates an engaging MP3 audio walkthrough of an architectural question.
    """
    return await generate_audio_explanation(question, target_file=file_path)

@mcp.resource("ui://blueprint")
async def get_blueprint_ui() -> str:
    """
    SEP-1865 Compliant UI resource.
    When an MCP-compatible IDE (like Cursor/Claude Desktop) queries this, it will fetch the compiled Vue HTML and render it.
    """
    # Look for the compiled Vue static assets
    dist_path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist", "index.html")
    if os.path.exists(dist_path):
        with open(dist_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Frontend build missing. Please run `npm run build` in the /frontend directory to generate the Vue Blueprint map.</h1>"

if __name__ == "__main__":
    # Start standard I/O serving loop for MCP protocol
    mcp.run()
