"""The citation parser, verifier and strict mode."""

from __future__ import annotations

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
