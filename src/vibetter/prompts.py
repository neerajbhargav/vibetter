"""Prompt templates. Context blocks are line-numbered (`  7| code`)."""

from __future__ import annotations

CITE = (
    "Cite code as path:line or path:start-end, using the line numbers shown in the context. "
    "Only cite files and lines that appear in the context. "
    "If the context does not contain the answer, say so instead of guessing."
)


def explain(question: str, context: str, target: str | None) -> str:
    return f"""You are VIBETTER. You explain code in a repository, often code an AI agent wrote.
{CITE}

<context>
{context}
</context>
{f"Target file: {target}" if target else ""}

Question: {question}

Answer with three short sections: What it does, How it works, Why it is written this way."""


def blueprint(context: str) -> str:
    return f"""Read this codebase and return its file dependency graph as JSON for Vue Flow.

The JSON object has exactly two keys, "nodes" and "edges".
Each node: {{"id": "1", "position": {{"x": 0, "y": 0}}, "data": {{"label": "path/to/file"}},
"type": "input" | "default" | "output"}}
Each edge: {{"id": "e1-2", "source": "1", "target": "2", "animated": true}}
Add an edge only for an import or call you can see in the context.
Place nodes without overlap within x 0-800 and y 0-600, grouping related files.

<context>
{context}
</context>"""


def audio(question: str, context: str, target: str | None) -> str:
    return f"""You are VIBETTER, recording a short spoken walkthrough of a codebase.
The text will be read aloud: use plain sentences, no markdown, no lists, no symbols.
Keep it under three minutes when spoken. Mention file names where they help.

<context>
{context}
</context>
{f"File: {target}" if target else ""}

Topic: {question}"""


def explain_diff(label: str, diff: str) -> str:
    return f"""You are VIBETTER. Explain a code change, often one an AI agent just made.
The diff below shows {label}. Lines that start with + were added and - were removed.
{CITE} For the diff, cite the new file's line numbers from the @@ hunk headers.

Answer with these sections:
What changed: the files and functions touched.
Intent: what the change is trying to do.
How it works: the key parts of the change.
Risks: bugs, missing tests or edge cases a reviewer should check.

<diff>
{diff}
</diff>"""


def debug(error_message: str, context: str, target: str | None) -> str:
    return f"""You are VIBETTER. Diagnose an error in this codebase.
{CITE}

Error:
<error>
{error_message}
</error>

<context>
{context}
</context>
{f"Relevant file: {target}" if target else ""}

Answer with these sections:
What the error means.
Why it happened: point to the file and line.
How to fix it: the exact change, before and after.
How to avoid it: one practical check."""
