"""Retrieval: tokenizer, BM25, symbol index, RRF, dense arm and context assembly."""

from __future__ import annotations

import re
from pathlib import Path

from conftest import line_of, write

from vibetter.index import CodebaseIndex
from vibetter.retrieve import BM25, Chunk, Retriever, assemble, definitions, rrf, tokenize


def retriever(root: Path, **kwargs) -> Retriever:
    index = CodebaseIndex(root)
    index.build()
    return Retriever(index.files, **kwargs)


def test_tokenizer_splits_identifiers_and_keeps_them_whole():
    tokens = set(tokenize("parseHTTPResponse(get_user_id) src/lib/format.ts"))
    assert {"parsehttpresponse", "parse", "http", "response"} <= tokens
    assert {"get_user_id", "get", "user", "id"} <= tokens
    assert {"src", "lib", "format", "ts"} <= tokens
    assert "the" not in tokenize("what does the cart do")


def test_definitions_per_language(shop: Path):
    py = dict(definitions("shop/cart.py", (shop / "shop/cart.py").read_text()))
    assert py["Cart"] == line_of(shop, "shop/cart.py", "class Cart")
    assert py["apply_discount"] == line_of(shop, "shop/cart.py", "def apply_discount")
    pricing = dict(definitions("shop/pricing.py", (shop / "shop/pricing.py").read_text()))
    assert pricing["TAX_RATE"] == line_of(shop, "shop/pricing.py", "TAX_RATE =")
    ts = dict(definitions("x/format.ts", (shop / "web/src/lib/format.ts").read_text()))
    assert set(ts) >= {"CURRENCY", "formatPrice", "PriceTag"}
    js = dict(definitions("x/api.js", (shop / "web/src/lib/api.js").read_text()))
    assert "fetchCart" in js


def test_bm25_prefers_rare_terms_and_term_frequency():
    docs = [["cart", "total"], ["cart", "discount", "discount"], ["cart", "tax"]]
    scores = BM25(docs).scores(["discount", "cart"])
    assert max(scores, key=lambda i: scores[i]) == 1


def test_rrf_rewards_agreement():
    fused = rrf([[1, 2, 3], [3, 4, 1]])
    assert sorted(fused, key=lambda i: -fused[i])[:2] == [1, 3]


def test_search_finds_the_discount_code(shop: Path):
    hits = retriever(shop).search("how is a discount code applied to the cart?", limit=3)
    top = hits[0].chunk
    assert top.path == "shop/cart.py"
    assert top.start <= line_of(shop, "shop/cart.py", "def apply_discount") <= top.end


def test_symbol_arm_finds_definitions(shop: Path):
    hit = retriever(shop).search("formatPrice", limit=1)[0]
    assert hit.chunk.path == "web/src/lib/format.ts"
    assert "symbol" in hit.arms


def test_plain_words_do_not_match_definition_names(tmp_path: Path):
    # The eval found the symbol arm ranking test functions such as
    # test_redirect_keeps_auth for an English question that says "redirect".
    write(tmp_path, "src/session.py", "def resolve(response):\n    return response.next\n")
    write(tmp_path, "tests/test_session.py", "def test_redirect_keeps_auth():\n    pass\n")
    r = retriever(tmp_path)
    assert r._symbol_scores("where is a redirect followed after a response?") == {}
    assert r._symbol_scores("what does test_redirect_keeps_auth check?")
    assert r._symbol_scores("what does resolve() return?")
    assert r._symbol_scores("where is session.py used?")


def test_traceback_frame_steers_retrieval(shop: Path):
    line = line_of(shop, "shop/cart.py", "raise ValueError")
    error = (
        f'Traceback (most recent call last):\n  File "/srv/app/shop/cart.py", line {line}, '
        "in apply_discount\nValueError: discounts above 50 percent need a manager"
    )
    top = retriever(shop).search(error, limit=1)[0].chunk
    assert top.path == "shop/cart.py" and top.start <= line <= top.end


def test_regression_traceback_frame_alone_picks_the_chunk(shop: Path):
    # Only the frame names the place: no function name and no words from that code.
    r = retriever(shop)
    line = line_of(shop, "shop/report.py", "def ledger_balance")
    first = r.chunks[r.by_path["shop/report.py"][0]]
    assert line > first.end  # a later chunk, so file order alone cannot pass
    error = f'File "/srv/app/shop/report.py", line {line}\nKeyError: 7'
    top = r.search(error, limit=1)[0].chunk
    assert top.path == "shop/report.py" and top.start <= line <= top.end


def test_file_path_in_query(shop: Path):
    assert retriever(shop).search("what is shop/legacy.py for", limit=1)[0].chunk.path == (
        "shop/legacy.py"
    )


def test_search_within_one_file_returns_all_its_chunks(shop: Path):
    r = retriever(shop)
    hits = r.search("monthly report", within="shop/report.py")
    assert {h.chunk.path for h in hits} == {"shop/report.py"}
    assert len(hits) == len(r.by_path["shop/report.py"])
    assert "report_monthly" in r.text(hits[0].chunk)


class FakeEmbedder:
    """Two-dimensional 'embeddings': does the text talk about refunds?"""

    def __init__(self):
        self.calls: list[tuple[int, bool]] = []

    def __call__(self, texts: list[str], query: bool) -> list[list[float]]:
        self.calls.append((len(texts), query))
        if query:
            return [[1.0, 0.0] for _ in texts]
        return [[1.0, 0.0] if "refund" in t.lower() else [0.0, 1.0] for t in texts]


def test_dense_arm_is_fused_and_cached(shop: Path):
    embed = FakeEmbedder()
    r = retriever(shop, embedder=embed)
    hit = r.search("money back guarantee", limit=1)[0]  # no lexical overlap with "refund"
    assert "dense" in hit.arms
    assert "refund" in r.text(hit.chunk).lower()
    chunk_calls = [n for n, query in embed.calls if not query]
    assert chunk_calls == [len({r.text(c) for c in r.chunks})]
    # A rebuilt retriever reuses the stored vectors: only the query is embedded.
    embed.calls.clear()
    Retriever(r.files, previous=r, embedder=embed).search("money back")
    assert embed.calls == [(1, True)]


def test_rebuild_reuses_unchanged_files(shop: Path):
    r1 = retriever(shop)
    files = dict(r1.files)
    files["shop/cart.py"] += "\n# changed\n"
    r2 = Retriever(files, previous=r1)
    assert r2._per_file["shop/pricing.py"] is r1._per_file["shop/pricing.py"]
    assert r2._per_file["shop/cart.py"] is not r1._per_file["shop/cart.py"]


def test_context_blocks_have_headers_and_numbered_lines(shop: Path):
    r = retriever(shop)
    chunks = [h.chunk for h in r.search("discount", within="shop/cart.py")]
    context, shown, used = assemble(r.files, chunks, 10_000)
    n = len((shop / "shop/cart.py").read_text().splitlines())
    assert context.startswith(f"--- shop/cart.py:L1-L{n} ---\n")
    assert re.search(r"^  1\| \"\"\"The shopping cart\.\"\"\"$", context, re.MULTILINE)
    assert shown == {"shop/cart.py": [(1, n)]}
    assert used == len(chunks)


def test_overlapping_and_adjacent_spans_merge():
    files = {"a.py": "".join(f"line {i}\n" for i in range(1, 41))}
    chunks = [Chunk("a.py", 21, 30), Chunk("a.py", 1, 10), Chunk("a.py", 8, 20)]
    context, shown, _ = assemble(files, chunks, 10_000)
    assert shown == {"a.py": [(1, 30)]}
    assert context.count("--- a.py") == 1


def test_regression_oversized_chunk_skipped_not_stopping_fill(repo: Path):
    write(repo, "src/aaa_huge.py", "# filler line for the budget test\n" * 400)
    r = retriever(repo)
    order = [Chunk("src/aaa_huge.py", 1, 120), Chunk("src/util.py", 1, 2)]
    context, shown, _ = assemble(r.files, order, 1000)
    assert "src/aaa_huge.py" not in shown
    assert "--- src/util.py:L1-L2 ---" in context  # filling continued past the big chunk
    assert len(context) <= 1000


def test_regression_target_file_cut_to_budget(repo: Path):
    write(repo, "src/long.py", "".join(f"value_{i} = {i}\n" for i in range(2000)))
    r = retriever(repo)
    chunks = [h.chunk for h in r.search("value_7", within="src/long.py")]
    context, shown, _ = assemble(r.files, chunks, 2000)
    assert len(context) <= 2000
    assert "--- src/long.py:L" in context
    assert sum(e - s + 1 for s, e in shown["src/long.py"]) < 2000


def test_heads_put_readme_first(shop: Path):
    heads = retriever(shop).heads()
    assert heads[0].path == "README.md"
    assert len(heads) == len({h.path for h in heads})


def test_regression_dense_arm_needs_opt_in(shop: Path, monkeypatch):
    # Installing the extra switched dense on, though the eval measured it lower.
    from vibetter import server

    calls: list[int] = []

    def fake_embedder():
        calls.append(1)
        return lambda texts, query: [[float(len(t)), 1.0] for t in texts]

    monkeypatch.setattr(server, "fastembed_embedder", fake_embedder)
    assert server.Vibetter(shop).retriever().embedder is None
    assert calls == []
    monkeypatch.setenv("VIBETTER_DENSE", "1")
    assert server.Vibetter(shop).retriever().embedder is not None
