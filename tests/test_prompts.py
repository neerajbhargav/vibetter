"""Prompt details that change how well models cite."""

from __future__ import annotations

from vibetter.prompts import cite_again, explain


def test_citation_example_uses_a_real_path():
    # In one local run with a made-up example path, qwen2.5-coder:7b cited that path.
    context = "--- shop/cart.py:L1-L31 ---\n  1| x\n"
    assert "(shop/cart.py:L12-L20)" in cite_again(context)
    assert "(web/a.ts:L12-L20)" in cite_again(context, "web/a.ts")
    assert "(new.py:L12-L20)" in cite_again(
        "diff --git a/new.py b/new.py\n--- /dev/null\n+++ b/new.py\n"
    )
    assert "(path/to/file.py:L12-L20)" in cite_again("")


def test_citation_rule_comes_after_the_context():
    prompt = explain("q", "--- a.py:L1-L1 ---\n  1| x\n", None)
    assert prompt.rindex("(a.py:L12-L20)") > prompt.index("</context>")
