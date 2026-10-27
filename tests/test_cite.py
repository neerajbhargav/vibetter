"""The citation parser, verifier and strict mode."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from conftest import CALC_PY

from vibetter.cite import check, counts, parse, strip_unverified, unique

FILES = {"src/calc.py": CALC_PY, "src/util.py": "a\nb\n", "lib/util.py": "c\n"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("see src/calc.py:L5-L8.", ("src/calc.py", 5, 8)),
        ("see src/calc.py:5-8", ("src/calc.py", 5, 8)),
        ("see src/calc.py:L5-8", ("src/calc.py", 5, 8)),
        ("see src/calc.py:L5\u2013L8", ("src/calc.py", 5, 8)),
        ("see src/calc.py:7", ("src/calc.py", 7, 7)),
        ("see src/calc.py:L7", ("src/calc.py", 7, 7)),
        ("see src/calc.py:7:12", ("src/calc.py", 7, 7)),
        ("see src/calc.py#L5-L8", ("src/calc.py", 5, 8)),
        ("see `src/calc.py:7`", ("src/calc.py", 7, 7)),
        ("see src/calc.py, lines 5-8", ("src/calc.py", 5, 8)),
        ("see src/calc.py (line 7)", ("src/calc.py", 7, 7)),
        ("see `src/calc.py` lines 5 to 8", ("src/calc.py", 5, 8)),
        ('File "src/calc.py", line 7, in divide', ("src/calc.py", 7, 7)),
        ("see ./src/calc.py:7", ("./src/calc.py", 7, 7)),
        # Missed until 2026-10-22; the claim next to each one went unchecked.
        ("see src/calc.py L5-L8 here", ("src/calc.py", 5, 8)),
        ("see src/calc.py: L7", ("src/calc.py", 7, 7)),
        ("see `src/calc.py`: lines 5-8", ("src/calc.py", 5, 8)),
        ("see src/calc.py:L5 - L8", ("src/calc.py", 5, 8)),
        ("see src/calc.py:7 - 3 more lines", ("src/calc.py", 7, 7)),
    ],
)
def test_parses_citation_variants(text: str, expected: tuple[str, int, int]):
    refs = parse(text)
    assert [(r.path, r.start, r.end) for r in refs] == [expected]


@pytest.mark.parametrize(
    "text",
    [
        "served on http://localhost:8080 and example.com:443",
        "a ratio of 3:4 and version 3.11:2",
        "see the README for details",
        "https://github.com/x/y.git:22",
        "setup.py 2 times, and main.py: 3 options",
    ],
)
def test_ignores_things_that_are_not_citations(text: str):
    assert parse(text) == []


def verdict(text: str, shown=None) -> dict:
    (_, c), *_ = check(text, FILES, shown)
    return {"path": c.path, "valid": c.valid, "grounded": c.grounded, "reason": c.reason}


def test_real_span_is_valid():
    v = verdict("divide is at src/calc.py:L5-L8")
    assert v["valid"] and v["grounded"] is None and v["reason"] == "ok"


def test_invented_path_is_invalid():
    v = verdict("see src/nope.py:3")
    assert not v["valid"] and v["reason"] == "file not indexed"


def test_out_of_range_line_is_invalid():
    v = verdict("see src/calc.py:L40")
    assert not v["valid"] and "out of range" in v["reason"]


def test_reversed_range_is_invalid():
    assert not verdict("see src/calc.py:8-5")["valid"]


def test_grounded_only_when_shown():
    shown = {"src/calc.py": [(1, 4)]}
    assert verdict("src/calc.py:L2", shown)["grounded"] is True
    v = verdict("src/calc.py:L7", shown)
    assert v["valid"] and v["grounded"] is False
    assert "not in the context" in v["reason"]


def test_partial_path_completed_from_unique_suffix():
    v = verdict("see calc.py:7")
    assert v["valid"] and v["path"] == "src/calc.py" and "suffix" in v["reason"]


def test_ambiguous_partial_path_is_invalid():
    v = verdict("see util.py:1")
    assert not v["valid"] and "ambiguous" in v["reason"]


def test_absolute_path_inside_root(tmp_path: Path):
    (_, c), *_ = check(f"see {tmp_path}/src/calc.py:7", FILES, None, tmp_path)
    assert c.valid and c.path == "src/calc.py"


def test_quote_must_match_cited_lines():
    (_, good), *_ = check("src/calc.py:L7 `raise ZeroDivisionError(...)`", FILES)
    assert good.quote_match is True and good.verified
    (_, bad), *_ = check('src/calc.py:L7 "return a * b"', FILES)
    assert bad.valid and bad.quote_match is False and not bad.verified
    # A quote further away is not treated as a quote of the citation.
    (_, loose), *_ = check("src/calc.py:L7 changes to `return a * b`", FILES)
    assert loose.quote_match is None


@pytest.mark.parametrize("wrap", ["({})", "[{}]", "({}):", "(see {})"])
def test_regression_quote_after_bracketed_citation_is_checked(wrap: str):
    # The prompt's example wraps the citation in parentheses, so models put the quote after ")".
    # The parser stopped at ")" and skipped the quote check without saying so.
    (_, good), *_ = check(wrap.format("src/calc.py:L7") + " `raise ZeroDivisionError(...)`", FILES)
    assert good.quote_match is True
    (_, bad), *_ = check(wrap.format("src/calc.py:L7") + " `return a * b`", FILES)
    assert bad.quote_match is False and not bad.verified


def test_unique_and_counts():
    pairs = check("src/calc.py:7 and again src/calc.py:L7, and src/nope.py:1", FILES)
    checks = unique(pairs)
    assert len(checks) == 2
    assert counts(checks) == {"total": 2, "valid": 1, "grounded": 0, "unverified": 1}


def test_strict_strips_only_unverified_claims():
    text = (
        "Divide guards zero at src/calc.py:L6-L7. It also logs to src/log.py:3. "
        "Add is at src/calc.py:1.\n- A bullet citing src/calc.py:L99.\n- A clean bullet."
    )
    out = strip_unverified(text, check(text, FILES))
    assert "Divide guards zero at src/calc.py:L6-L7." in out
    assert "Add is at src/calc.py:1." in out
    assert "logs to" not in out
    assert "A bullet citing" not in out
    assert "- A clean bullet." in out
    assert "removed claims citing src/log.py:3 (file not indexed)" in out


def test_strict_flags_an_answer_without_citations():
    assert "no citations" in strip_unverified("It just works.", [])


def test_invented_prefix_is_not_completed_but_foreign_absolute_path_is():
    assert verdict("see backend/src/calc.py:7")["reason"] == "file not indexed"
    v = verdict('File "/srv/other-checkout/src/calc.py", line 7')
    assert v["valid"] and v["path"] == "src/calc.py"


# --- path grammar (2026-10-26) ----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # A leading dot was dropped, so dotfiles came back "file not indexed" or unparsed.
        ("see .github/workflows/ci.yml:L3", (".github/workflows/ci.yml", 3, 3)),
        ("in `.gitignore:L2`", (".gitignore", 2, 2)),
        # Next.js segments: the parser stopped at "[" and "(".
        ("see app/blog/[slug]/page.tsx:L2", ("app/blog/[slug]/page.tsx", 2, 2)),
        ("(app/(auth)/login/page.tsx:L2)", ("app/(auth)/login/page.tsx", 2, 2)),
        ("cafe\u0301.py:L1", ("cafe\u0301.py", 1, 1)),  # NFD name with a combining mark
        # Forms found unchecked in the committed eval replies.
        ("(path:src/calc.py:L5-L8)", ("src/calc.py", 5, 8)),
        ("as lines 5-8 of `src/calc.py` show", ("src/calc.py", 5, 8)),
        ("Lines 5 to 8 in src/calc.py do it", ("src/calc.py", 5, 8)),
        ("in `calc.py` at line 7", ("calc.py", 7, 7)),
        ("see src/calc.py on line 7", ("src/calc.py", 7, 7)),
        # A name with spaces is read from its last word; prose gives no way to tell.
        ("my file.py:L2", ("file.py", 2, 2)),
    ],
)
def test_regression_path_grammar(text: str, expected: tuple[str, int, int]):
    assert [(r.path, r.start, r.end) for r in parse(text)] == [expected]


def test_regression_path_never_starts_inside_a_word():
    # "app/shop/[id]/page.tsx" was read as "/page.tsx" and completed to app/page.tsx.
    files = {"app/page.tsx": "a\nb\n"}
    (_, c), *_ = check("see app/shop/[id]/page.tsx:L2", files)
    assert c.path == "app/shop/[id]/page.tsx" and not c.valid
    assert parse("foo/bar.py:L2")[0].path == "foo/bar.py"
    assert parse("xbar.py:L2")[0].path == "xbar.py"


def test_unicode_digits_are_not_line_numbers():
    assert parse("src/calc.py:L\u0667 and src/calc.py:L\uff17") == []


@pytest.mark.parametrize(
    "text",
    [
        "a" * 50_000,
        "(a)" * 16_000,
        "a." * 25_000,
        "x.py" + " " * 50_000 + "L",
        "lines 1" + " " * 50_000,
        'File "' + "a" * 50_000,
        "x.py:L1 `a` " * 4_000,
    ],
    ids=["word", "groups", "dotted", "spaces", "lines", "traceback", "many"],
)
def test_regression_parse_is_linear(text: str):
    # parse("a" * 40_000) took 57 s and blocked the MCP server's event loop.
    start = time.perf_counter()
    pairs = check(text, FILES)
    strip_unverified(text, pairs)
    assert time.perf_counter() - start < 0.5


# --- quotes and verdicts ---------------------------------------------------------


def test_regression_next_citation_is_not_a_quote():
    # The second citation was read as the first one's quote, which then "did not appear".
    refs = parse("`src/calc.py:L1` `src/calc.py:L7`")
    assert [(r.start, r.quote) for r in refs] == [(1, None), (7, None)]


def test_trivial_quote_checks_nothing():
    (_, c), *_ = check("src/calc.py:L7 `...`", FILES)
    assert c.quote_match is None


def test_unique_keeps_the_worse_of_two_quotes():
    text = "src/calc.py:L7 `raise ZeroDivisionError` and src/calc.py:L7 `return a * b`"
    (c,) = unique(check(text, FILES))
    assert c.quote_match is False and not c.verified


def test_regression_grounded_needs_the_whole_range_shown():
    # Overlap was enough: L1-L162 counted as grounded when 5 lines were shown.
    shown = {"src/calc.py": [(1, 4)]}
    v = verdict("src/calc.py:L3-L6", shown)
    assert v["valid"] and v["grounded"] is False
    assert v["reason"] == "only part of the range was in the context shown to the model"
    assert verdict("src/calc.py:L2-L4", shown)["grounded"] is True


def test_grounded_only_by_the_cited_file():
    shown = {"src/util.py": [(1, 2)], "lib/util.py": [(1, 1)]}
    assert verdict("src/util.py:L1", shown)["grounded"] is True
    assert verdict("src/calc.py:L1", shown)["grounded"] is False
