"""Prompt details that change how well models cite."""

from __future__ import annotations

from pathlib import Path

import pytest

from vibetter import prompts
from vibetter.cite import check
from vibetter.gitdiff import number_lines
from vibetter.index import CodebaseIndex
from vibetter.retrieve import Retriever, assemble


def test_citation_example_uses_a_real_path():
    # In one local run with a made-up example path, qwen2.5-coder:7b cited that path.
    context = "--- shop/cart.py:L1-L31 ---\n  1| x\n"
    assert "(shop/cart.py:L<first>-L<last>)" in prompts.cite_again(context)
    assert "(web/a.ts:L<first>-L<last>)" in prompts.cite_again(context, "web/a.ts")
    assert "(new.py:L<first>-L<last>)" in prompts.cite_again(
        "diff --git a/new.py b/new.py\n--- /dev/null\n+++ b/new.py\n"
    )
    assert "(path/to/file.py:L<first>-L<last>)" in prompts.cite_again("")


def test_citation_rule_comes_after_the_context():
    prompt = prompts.explain("q", "--- a.py:L1-L1 ---\n  1| x\n", None)
    assert prompt.rindex("(a.py:L<first>-L<last>)") > prompt.index("</context>")


@pytest.mark.parametrize("target", [None, "shop/cart.py"])
def test_regression_copied_example_citation_never_verifies(shop: Path, target: str | None):
    # qwen2.5-coder:7b copied the example "(shop/cart.py:L12-L20)" word for word. With a real
    # path and real line numbers, the copy passed as valid and grounded. Whatever the model
    # copies from the instructions must fail the check.
    files = CodebaseIndex(shop).files
    r = Retriever(files)
    context, shown, _ = assemble(files, [h.chunk for h in r.search("discount")], 20_000)
    diff = number_lines(
        "diff --git a/shop/cart.py b/shop/cart.py\n--- a/shop/cart.py\n+++ b/shop/cart.py\n"
        "@@ -20,2 +20,3 @@\n x\n+y\n z\n"
    )
    built = [
        prompts.explain("q", context, target).replace(context, ""),
        prompts.debug("e", context, target).replace(context, ""),
        prompts.explain_diff("a change", diff).replace(diff, ""),
    ]
    for instructions in built:
        copied = [c for _, c in check(instructions, files, shown)]
        assert not any(c.valid for c in copied), copied
        assert "L<first>" in instructions
