"""Prompt templates. Context blocks have `--- path:L1-L60 ---` headers and `  7| code` lines."""

from __future__ import annotations

import re

# Examples hold placeholders, never line numbers. qwen2.5-coder:7b copied a numeric example
# word for word, and a copy with real numbers can pass the citation check.
CITE = (
    "Cite each claim about the code with its file path and the line numbers printed at the "
    "left of the context, as path:L<first>-L<last>, or path:L<line> for one line. "
    "Cite only lines that appear in the context. "
    "To quote code, put it in backticks right after the citation, copied exactly. "
    "If the context does not contain the answer, say so instead of guessing."
)


def cite_again(text: str, target: str | None = None) -> str:
    """The citation rule again, after the context: small local models forget
    instructions that come before a long context. The example uses a real path
    from the context, because a model can copy a made-up example path."""
    m = re.search(r"^(?:--- (\S+):L\d+|\+\+\+ b/(\S+))", text, re.MULTILINE)
    path = target or ((m.group(1) or m.group(2)) if m else "path/to/file.py")
    return (
        f"After every claim about the code, add a citation such as ({path}:L<first>-L<last>), "
        "with <first> and <last> replaced by the line numbers of the lines that support it."
    )


def explain(question: str, context: str, target: str | None) -> str:
    return f"""You are VIBETTER. You explain code in a repository, often code an AI agent wrote.
{CITE}

<context>
{context}
</context>
{f"Target file: {target}" if target else ""}

Question: {question}

Answer with three short sections: What it does, How it works, Why it is written this way.
{cite_again(context, target)}"""


def blueprint_labels(paths: list[str], edges: list[tuple[str, str]]) -> str:
    listing = "\n".join(paths)
    imports = "\n".join(f"{a} -> {b}" for a, b in edges) or "(none)"
    return f"""Group the source files of one codebase into 2 to 8 named parts, such as "API",
"storage" or "UI". Use only the paths listed, and put each path in one group.
Return JSON: {{"groups": {{"part name": ["path", "path"]}}}}

Files:
{listing}

Imports (importer -> imported):
{imports}"""


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
The diff below shows {label}. Lines with + were added and - were removed.
Each line inside a hunk starts with its line number in the new file; removed lines have none.
{CITE}

Answer with these sections:
What changed: the files and functions touched.
Intent: what the change is trying to do.
How it works: the key parts of the change.
Risks: bugs, missing tests or edge cases a reviewer should check.

<diff>
{diff}
</diff>
{cite_again(diff)}"""


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
How to avoid it: one practical check.
{cite_again(context, target)}"""
