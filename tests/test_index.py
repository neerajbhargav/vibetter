"""CodebaseIndex: file selection, path lookup and change tracking.

Context assembly moved to retrieve.py; its regression tests live in test_retrieve.py.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import git, write
from watchdog.events import FileDeletedEvent, FileModifiedEvent, FileMovedEvent

from vibetter.config import ConfigError, resolve_root
from vibetter.index import CodebaseIndex, NotIndexed

SOURCES = {"src/calc.py", "src/util.py", "app/main.py", "app/settings.py", "README.md"}


def built(root: Path) -> CodebaseIndex:
    index = CodebaseIndex(root)
    index.build()
    return index


def test_regression_fixture_repo_has_no_background_maintenance(repo: Path):
    # Background maintenance raced the per-test copy of the fixture repo in CI.
    assert git(repo, "config", "--get", "maintenance.auto").strip() == "false"
    assert git(repo, "config", "--get", "gc.auto").strip() == "0"


def test_indexes_tracked_and_untracked_source_files(repo: Path):
    write(repo, "src/brand_new.py", "x = 1\n")
    index = built(repo)
    assert SOURCES | {"src/brand_new.py"} <= set(index.files)


def test_regression_gitignore_respected(repo: Path):
    index = built(repo)
    assert "ignored.txt" not in index.files
    assert not any(p.startswith("node_modules/") for p in index.files)


def test_skips_noise_with_a_reason(repo: Path):
    skipped = built(repo).skipped
    assert skipped["package-lock.json"] == "lockfile"
    assert skipped["web/app.min.js"] == "minified"
    assert skipped["web/bundle.js"] == "minified"
    assert skipped["data.bin"] == "binary"
    assert skipped["big.txt"] == "too large"


def test_regression_secret_files_excluded_by_default(repo: Path):
    index = built(repo)
    for secret in (".env", "config/credentials.json", "certs/server.pem", "id_rsa"):
        assert secret not in index.files
        assert index.skipped[secret] == "secret"


def test_regression_symlink_outside_root_is_skipped(repo: Path, tmp_path: Path):
    outside = tmp_path / "outside.py"
    outside.write_text("OUTSIDE_THE_REPO = 1\n")
    (repo / "src/link.py").symlink_to(outside)
    (repo / "src/inside.py").symlink_to(repo / "src/calc.py")
    index = built(repo)
    assert "src/link.py" not in index.files
    assert index.skipped["src/link.py"] == "outside root"
    assert "src/inside.py" in index.files


def test_walk_fallback_honors_gitignore(plain_dir: Path):
    write(plain_dir, "pkg/.gitignore", "generated.py\n")
    write(plain_dir, "pkg/generated.py", "AUTO = 1\n")
    write(plain_dir, "pkg/kept.py", "KEPT = 1\n")
    index = built(plain_dir)
    assert SOURCES <= set(index.files)
    assert "pkg/kept.py" in index.files
    assert "pkg/generated.py" not in index.files
    assert "ignored.txt" not in index.files
    assert not any(p.startswith("node_modules/") for p in index.files)
    assert index.skipped[".env"] == "secret"


@pytest.mark.parametrize(
    "given", ["src/calc.py", "./src/calc.py", "src/../src/calc.py", "src\\calc.py"]
)
def test_regression_paths_normalized(repo: Path, given: str):
    assert built(repo).resolve(given) == "src/calc.py"


def test_absolute_path_inside_root_resolves(repo: Path):
    assert built(repo).resolve(str(repo / "src" / "calc.py")) == "src/calc.py"


def test_regression_missing_file_is_explicit(repo: Path):
    index = built(repo)
    with pytest.raises(NotIndexed, match=r"not found.*src/calc\.py"):
        index.resolve("src/calcc.py")
    with pytest.raises(NotIndexed, match=r"excluded.*secret"):
        index.resolve(".env")
    with pytest.raises(NotIndexed, match="outside"):
        index.resolve("../elsewhere.py")


def test_stats_counts_files_lines_and_skips(repo: Path):
    stats = built(repo).stats()
    assert stats["files"] == len(built(repo).files)
    assert stats["lines"] > 0
    assert stats["skipped"]["secret"] == 4
    assert stats["mode"] == "git"


def test_regression_refuses_home_and_filesystem_root(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(isolated_env)
    with pytest.raises(ConfigError, match="VIBETTER_CODEBASE_PATH"):
        resolve_root()
    monkeypatch.chdir("/")
    with pytest.raises(ConfigError, match="VIBETTER_CODEBASE_PATH"):
        resolve_root()


def test_explicit_root_wins(repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VIBETTER_CODEBASE_PATH", str(repo / "src"))
    assert resolve_root() == (repo / "src").resolve()
    assert resolve_root(repo) == repo.resolve()


def _rapid(index: CodebaseIndex, root: Path, rel: str, content: str) -> None:
    write(root, rel, content)
    index.dispatch(FileModifiedEvent(str(root / rel)))


def test_regression_rapid_saves_keep_the_last_one(repo: Path):
    index = built(repo)
    _rapid(index, repo, "src/calc.py", "first = 1\n")
    _rapid(index, repo, "src/calc.py", "second = 2\n")
    index.flush()
    assert index.files["src/calc.py"] == "second = 2\n"


def test_regression_deleted_event_removes_file(repo: Path):
    # inotify (Linux) reports only a delete; the old handler ignored it.
    index = built(repo)
    (repo / "src/util.py").unlink()
    index.dispatch(FileDeletedEvent(str(repo / "src/util.py")))
    index.flush()
    assert "src/util.py" not in index.files


def test_regression_moved_event_reindexes_file(repo: Path):
    index = built(repo)
    (repo / "src/util.py").rename(repo / "src/helpers.py")
    index.dispatch(FileMovedEvent(str(repo / "src/util.py"), str(repo / "src/helpers.py")))
    index.flush()
    assert "src/util.py" not in index.files
    assert "src/helpers.py" in index.files


def test_new_file_in_ignored_location_stays_out(repo: Path):
    index = built(repo)
    _rapid(index, repo, "node_modules/dep/new.js", "x = 1\n")
    _rapid(index, repo, "ignored.txt", "changed\n")
    _rapid(index, repo, "src/fresh.py", "y = 2\n")
    index.flush()
    assert "src/fresh.py" in index.files
    assert "ignored.txt" not in index.files
    assert "node_modules/dep/new.js" not in index.files


def test_regression_import_does_not_build_index(tmp_path: Path):
    """The MCP handshake must not wait for indexing (it used to walk at import)."""
    env = dict(os.environ, VIBETTER_CODEBASE_PATH=str(tmp_path / "does-not-exist"))
    code = (
        "import threading, vibetter.server as s; s.create_server();print(threading.active_count())"
    )
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "1"  # no watcher thread started


def test_version_bumps_on_build_and_on_each_applied_change(repo: Path):
    index = built(repo)
    assert index.version == 1
    _rapid(index, repo, "src/calc.py", "changed = 1\n")
    index.flush()
    assert index.version == 2
    index.flush()  # nothing pending
    assert index.version == 2
