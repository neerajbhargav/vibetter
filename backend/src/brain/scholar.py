import os
import time
import json
import asyncio
import subprocess
from gtts import gTTS
from typing import Dict, Any, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from google import genai
from google.genai import types as genai_types
import sys
import os.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import GEMINI_API_KEY, VIBETTER_CODEBASE_PATH

# Model fallback chain — tries each in order on quota/rate/availability errors
FALLBACK_MODELS = [
    os.getenv("VIBETTER_MODEL", "gemini-2.0-flash-lite"),
    "gemini-2.5-flash",
    "gemini-1.5-flash",
]

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


class MasterContextManager(FileSystemEventHandler):
    def __init__(self, codebase_path: str):
        self.codebase_path = os.path.abspath(codebase_path)
        self.master_context = ""
        self._file_contents: Dict[str, str] = {}
        self.build_context()

        # Watchdog auto-syncs context on file save
        self.observer = Observer()
        self.observer.schedule(self, self.codebase_path, recursive=True)
        self.observer.start()

    def build_context(self):
        """Recursively parses text-based code files into one context payload."""
        parts = []
        self._file_contents = {}
        for root, dirs, files in os.walk(self.codebase_path):
            dirs[:] = [d for d in dirs if d not in (
                'node_modules', '.git', '__pycache__', 'dist', '.venv', 'venv', '.next', 'build', 'out'
            )]
            for file in files:
                if file.endswith(('.py', '.js', '.jsx', '.ts', '.tsx', '.vue', '.md', '.json',
                                  '.html', '.css', '.env.example', '.yaml', '.yml', '.toml')):
                    filepath = os.path.join(root, file)
                    try:
                        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            self._file_contents[filepath] = content
                            rel = os.path.relpath(filepath, self.codebase_path)
                            parts.append(f"--- FILE: {rel} ---\n{content}\n")
                    except Exception:
                        pass
        self.master_context = "\n".join(parts)

    def get_targeted_context(self, file_path: str, max_chars: int = 40000) -> str:
        """Returns context focused on a specific file + closely related files."""
        target_abs = os.path.join(self.codebase_path, file_path) if not os.path.isabs(file_path) else file_path
        parts = []

        # Always include the target file first
        if target_abs in self._file_contents:
            rel = os.path.relpath(target_abs, self.codebase_path)
            parts.append(f"--- TARGET FILE: {rel} ---\n{self._file_contents[target_abs]}\n")

        # Fill remaining budget with the rest of the codebase
        budget = max_chars - sum(len(p) for p in parts)
        for path, content in self._file_contents.items():
            if path == target_abs:
                continue
            chunk = f"--- FILE: {os.path.relpath(path, self.codebase_path)} ---\n{content}\n"
            if budget - len(chunk) < 0:
                break
            parts.append(chunk)
            budget -= len(chunk)

        return "\n".join(parts)

    def on_modified(self, event):
        if not event.is_directory and not event.src_path.endswith('.tmp'):
            self.build_context()


context_manager = MasterContextManager(VIBETTER_CODEBASE_PATH)

# Shared cache for the last generated blueprint (used by ui://blueprint resource)
_blueprint_cache: Optional[Dict[str, Any]] = None


async def _call_gemini(prompt: str, json_mode: bool = False) -> str:
    """
    Calls Gemini with automatic model fallback on quota/rate errors.
    Tries gemini-2.0-flash → gemini-1.5-flash → gemini-1.5-pro.
    """
    if not client:
        return "Error: GEMINI_API_KEY is not set. Add it to backend/.env"

    config = genai_types.GenerateContentConfig(response_mime_type="application/json") if json_mode else None
    last_error = None

    for model in FALLBACK_MODELS:
        try:
            kwargs = {"model": model, "contents": prompt}
            if config:
                kwargs["config"] = config
            response = await asyncio.to_thread(client.models.generate_content, **kwargs)
            return response.text
        except Exception as e:
            err = str(e)
            # Catch quota, rate limit, and model availability errors — try next model
            if any(x in err for x in ("429", "404", "NOT_FOUND", "RESOURCE_EXHAUSTED")) \
               or any(x in err.lower() for x in ("quota", "rate", "no longer available", "deprecated")):
                last_error = e
                continue
            raise  # non-transient errors bubble up immediately

    return f"Error: All Gemini models hit quota limits. Try again later or enable billing at console.cloud.google.com/billing\n\nDetails: {last_error}"


# ─── Core Tools ────────────────────────────────────────────────────────────────

async def ask_gemini_with_context(question: str, target_file: str = None) -> str:
    """Explains code with mandatory source-grounding, tuned for vibe coder learners."""
    if target_file:
        context = context_manager.get_targeted_context(target_file)
    else:
        context = context_manager.master_context[:60000]

    prompt = f"""You are VIBETTER, an expert coding mentor for people learning to code with AI tools (vibe coding).

Your job is to explain code clearly so the user actually understands it — not just copy-paste it.

Rules:
- Always cite exact file:line when referencing code
- Explain *why* the code works, not just *what* it does
- Use simple analogies for complex concepts
- Be encouraging — this person is learning

Codebase:
<context>
{context}
</context>
{"Target file: " + target_file if target_file else ""}

Question: {question}

Answer with clear sections: **What it does**, **How it works**, **Why it's written this way**."""

    return await _call_gemini(prompt)


async def generate_architecture_json() -> Dict[str, Any]:
    """Generates a Vue Flow dependency graph from the codebase."""
    global _blueprint_cache

    prompt = f"""Analyze this codebase and return a JSON dependency graph for vue-flow visualization.

Requirements:
- JSON with exactly 2 keys: "nodes" and "edges"
- Each node: {{ "id": "1", "position": {{ "x": 0, "y": 0 }}, "data": {{ "label": "filename" }}, "type": "input"|"default"|"output" }}
- Each edge: {{ "id": "e1-2", "source": "1", "target": "2", "animated": true }}
- Space nodes logically (no overlapping). Use x: 0-800, y: 0-600 range.
- Group related files visually

Codebase:
{context_manager.master_context[:50000]}"""

    text = await _call_gemini(prompt, json_mode=True)
    try:
        result = json.loads(text)
        _blueprint_cache = result  # update the UI cache
        return result
    except Exception as e:
        return {"error": "Failed to parse blueprint JSON", "details": str(e), "nodes": [], "edges": []}


async def generate_audio_explanation(question: str, target_file: str = None) -> str:
    """Generates an MP3 audio walkthrough of a codebase question."""
    if target_file:
        context = context_manager.get_targeted_context(target_file)
    else:
        context = context_manager.master_context[:40000]

    prompt = f"""You are VIBETTER, an AI coding mentor hosting a short podcast episode for someone learning to code with AI tools.

Explain the following question in a warm, conversational way — like you're talking to a curious friend, not reading documentation.

Rules:
- No markdown, bullet points, or special characters (this will be read aloud)
- Use natural speech patterns and simple words
- Give one concrete analogy to make the concept click
- Keep it under 3 minutes when spoken aloud

Codebase context:
{context}
{"File: " + target_file if target_file else ""}

Topic: {question}"""

    try:
        transcript = await _call_gemini(prompt)

        output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "outputs")
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, f"vibetter_{int(time.time())}.mp3")

        tts = gTTS(text=transcript, lang='en', slow=False)
        tts.save(filepath)
        return f"Audio saved to: {os.path.abspath(filepath)}\n\nTranscript preview:\n{transcript[:400]}..."
    except Exception as e:
        return f"Error generating audio: {e}"


# ─── New Learning Tools ────────────────────────────────────────────────────────

async def explain_diff() -> str:
    """
    Reads the latest git diff and explains what the AI just generated,
    in plain English for someone learning to code.
    """
    try:
        # Try uncommitted changes first, then last commit
        diff = subprocess.check_output(
            ["git", "diff", "HEAD"],
            cwd=VIBETTER_CODEBASE_PATH, text=True, stderr=subprocess.DEVNULL
        ).strip()

        if not diff:
            diff = subprocess.check_output(
                ["git", "diff", "--staged"],
                cwd=VIBETTER_CODEBASE_PATH, text=True, stderr=subprocess.DEVNULL
            ).strip()

        if not diff:
            # Fall back to the last commit diff
            diff = subprocess.check_output(
                ["git", "diff", "HEAD~1", "HEAD"],
                cwd=VIBETTER_CODEBASE_PATH, text=True, stderr=subprocess.DEVNULL
            ).strip()

        if not diff:
            return "No recent changes found. Make some edits with your AI tool and try again!"

    except Exception as e:
        return f"Could not read git diff. Make sure this is a git repository.\n\nError: {e}"

    prompt = f"""You are VIBETTER, an AI coding mentor. A vibe coder just used an AI tool (like Claude, Cursor, or Copilot) to make changes to their code.

Explain these changes so they actually understand what the AI did — and WHY — so they can learn from it.

Structure your answer as:
## What Changed
(Quick summary of which files and functions were touched)

## What the AI Was Trying to Do
(The intent/goal behind these changes, in plain English)

## How the Key Parts Work
(Walk through the most important code change, line by line if needed, using simple language)

## What You Just Learned
(1-2 programming concepts this change demonstrates. Make it feel like a mini lesson)

Be encouraging. This person is learning. Reference specific line numbers from the diff.

Git diff:
```diff
{diff[:10000]}
```"""

    return await _call_gemini(prompt)


async def debug_error(error_message: str, file_path: str = None) -> str:
    """
    Takes an error message and explains exactly what's wrong and how to fix it,
    in the context of the user's codebase.
    """
    if file_path:
        context = context_manager.get_targeted_context(file_path, max_chars=20000)
    else:
        context = context_manager.master_context[:30000]

    prompt = f"""You are VIBETTER, an AI debugging mentor for someone learning to code with AI tools.

They got this error and don't understand it. Your job: explain it clearly and fix it.

Structure your answer as:
## What This Error Means
(Translate the error into plain English. No jargon.)

## Why It Happened
(Point to the exact line/file causing it. Be specific.)

## How to Fix It
(Give the exact code change needed. Show before and after.)

## How to Avoid It Next Time
(One practical tip for this class of error)

Error:
```
{error_message}
```

Their codebase:
<context>
{context}
</context>
{"Relevant file: " + file_path if file_path else ""}

Be direct and kind. They are learning."""

    return await _call_gemini(prompt)
