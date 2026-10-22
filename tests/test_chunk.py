"""The line-aware chunker."""

from __future__ import annotations

from pathlib import Path

from vibetter.chunk import MAX_LINES, OVERLAP, TARGET, chunk_lines, split_lines


def covers_every_line(spans: list[tuple[int, int]], n: int) -> bool:
    covered = set()
    for s, e in spans:
        covered.update(range(s, e + 1))
    return covered == set(range(1, n + 1))


def test_python_chunks_end_at_definitions(shop: Path):
    text = (shop / "shop/report.py").read_text()
    lines = text.splitlines()
    spans = chunk_lines("shop/report.py", text)
    assert len(spans) > 1
    assert covers_every_line(spans, len(lines))
    for s, e in spans:
        assert e - s + 1 <= MAX_LINES
    for s, _ in spans[1:]:
        assert lines[s - 1].startswith("def "), lines[s - 1]
    # No overlap when every cut is at a definition.
    assert all(spans[i][1] + 1 == spans[i + 1][0] for i in range(len(spans) - 1))


def test_comments_and_decorators_stay_with_their_function():
    body = "".join(f"x_{i} = {i}\n" for i in range(50))
    text = body + "\n# explains the helper\n@cache\ndef helper():\n    return 1\n" + body
    lines = text.splitlines()
    spans = chunk_lines("m.py", text)
    starts = {lines[s - 1] for s, _ in spans[1:]}
    assert "# explains the helper" in starts


def test_brace_languages_cut_at_top_level_blank_lines():
    body = "".join(f"  a += {j}\n" for j in range(18))
    functions = [f"function f{i}(a) {{\n{body}}}\n" for i in range(10)]
    text = "\n".join(functions)
    lines = text.splitlines()
    spans = chunk_lines("app.js", text)
    assert covers_every_line(spans, len(lines))
    for s, _ in spans[1:]:
        assert lines[s - 1].startswith("function "), lines[s - 1]


def test_no_boundary_forces_cuts_with_overlap():
    text = "const table = {\n" + "".join(f"  k{i}: {i},\n" for i in range(300)) + "}\n"
    lines = text.splitlines()
    spans = chunk_lines("table.js", text)
    assert covers_every_line(spans, len(lines))
    assert all(e - s + 1 <= MAX_LINES for s, e in spans)
    assert spans[1][0] == spans[0][1] - OVERLAP + 1


def test_small_file_is_one_chunk_and_empty_file_none():
    assert chunk_lines("a.py", "x = 1\ny = 2\n") == [(1, 2)]
    assert chunk_lines("a.py", "") == []
    long_enough = "".join(f"v{i} = {i}\n" for i in range(TARGET + TARGET // 2))
    assert chunk_lines("a.py", long_enough) == [(1, TARGET + TARGET // 2)]


def test_python_syntax_error_falls_back_to_heuristics():
    text = "def broken(:\n" + "".join(f"    line_{i}\n\n" for i in range(150))
    spans = chunk_lines("bad.py", text)
    assert covers_every_line(spans, len(text.splitlines()))


def test_markdown_cuts_at_headings():
    text_lines = "".join(f"text {j}\n" for j in range(25))
    sections = [f"# Part {i}\n{text_lines}" for i in range(6)]
    text = "".join(sections)
    lines = text.splitlines()
    for s, _ in chunk_lines("README.md", text)[1:]:
        assert lines[s - 1].startswith("# Part"), lines[s - 1]


def test_line_numbers_match_git_not_str_splitlines():
    # A form feed or U+2028 is not a line break for git or editors.
    text = "a = 1\n\x0c\nb = '\u2028'\r\nc = 3\n"
    assert split_lines(text) == ["a = 1", "\x0c", "b = '\u2028'", "c = 3"]
    assert len(text.splitlines()) == 6  # what the old code counted


def test_lone_carriage_returns_do_not_crash_the_chunker():
    text = "".join(f"def f{i}():\r    return {i}\r\r" for i in range(100))
    assert chunk_lines("old_mac.py", text) == [(1, 1)]
