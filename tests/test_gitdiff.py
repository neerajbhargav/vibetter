"""Diff line numbering and the spans a diff shows."""

from __future__ import annotations

from vibetter.gitdiff import number_lines, shown_spans

DIFF = """\
diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -10,4 +10,5 @@ def f():
 keep = 1
-old = 2
+new = 2
++++ looks like a header but is content
 tail = 3
\\ No newline at end of file
diff --git a/gone.py b/gone.py
--- a/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-x = 1
-y = 2
diff --git a/new.py b/new.py
new untracked file
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+a = 1
+b = 2
"""


def test_hunk_lines_get_new_file_numbers():
    out = number_lines(DIFF).splitlines()
    assert "   10|  keep = 1" in out
    assert "     | -old = 2" in out
    assert "   11| +new = 2" in out
    assert "   12| ++++ looks like a header but is content" in out
    assert "   13|  tail = 3" in out
    assert "    1| +a = 1" in out
    assert "+++ b/src/a.py" in out  # headers are left alone


def test_shown_spans_follow_the_new_side():
    assert shown_spans(DIFF) == {"src/a.py": [(10, 13)], "new.py": [(1, 2)]}
