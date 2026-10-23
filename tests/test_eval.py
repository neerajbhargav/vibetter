"""The eval harness: v1 context, arm packing and metrics, offline on the shop fixture."""

from __future__ import annotations

from pathlib import Path

from conftest import line_of

from eval.common import Gold, Question, gold_recall, v1_context, v1_files
from eval.retrieval import first_gold_rank, ranked_context
from vibetter.index import CodebaseIndex
from vibetter.retrieve import Retriever
from vibetter.server import Vibetter


def test_v1_context_cuts_at_the_budget_and_reports_only_complete_lines(shop: Path):
    files = v1_files(shop)
    # os.walk order with names sorted per level: root files first, then each directory.
    assert [p for p, _ in files][:3] == ["README.md", "cli.py", "shop/__init__.py"]
    context, shown = v1_context(files, 1_500)
    assert len(context) <= 1_500
    text = dict(files)
    for path, spans in shown.items():
        start, end = spans[0]
        assert start == 1
        body = "\n".join(text[path].split("\n")[:end])
        assert f"--- FILE: {path} ---\n{body}" in context


def test_metrics_count_gold_lines_and_rank():
    q = Question("q", "r", "?", (Gold("a.py", 10, 19),), ("x",))
    assert gold_recall(q, {"a.py": [(1, 14)]}) == 0.5
    assert gold_recall(q, {"b.py": [(1, 99)]}) == 0.0
    assert first_gold_rank(q, [("b.py", 1, 50), ("a.py", 15, 30)]) == 2
    assert first_gold_rank(q, [("a.py", 20, 30)]) is None


def test_arm_c_packs_the_same_context_as_the_server(shop: Path):
    question = "how is a discount code applied to the cart?"
    index = CodebaseIndex(shop)
    index.build()
    r = Retriever(index.files)
    shown, blocks, _ = ranked_context(r, [h.chunk for h in r.search(question)], 4_000)
    _, _, server_shown = Vibetter(shop, embedder=False)._gather(question, None, 4_000)
    assert shown == server_shown
    first = blocks[0]
    assert first[0] == "shop/cart.py"
    assert first[1] <= line_of(shop, "shop/cart.py", "def apply_discount") <= first[2]
