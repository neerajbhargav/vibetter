"""Static checks on the installers (they run on users' machines)."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SH = (ROOT / "install.sh").read_text()
PS1 = (ROOT / "install.ps1").read_text()


def test_regression_install_sh_never_evals_or_inlines_the_key():
    assert not re.search(r"^\s*eval\b", SH, re.MULTILINE)
    assert "$API_KEY'" not in SH  # the key was pasted into python -c source
    assert not re.search(r"-e \"?\$KEY_VAR=\$API_KEY", SH)  # or into argv


def test_regression_install_ps1_never_evals_or_inlines_the_key():
    assert "Invoke-Expression" not in PS1
    assert "'$ApiKey'" not in PS1
    assert not re.search(r"'-e',\s*\"\$KeyVar=\$ApiKey\"", PS1)  # key in argv


def test_installers_register_the_packaged_command():
    assert "backend/src/server.py" not in SH
    assert "backend\\src\\server.py" not in PS1
    assert "vibetter.ide" in SH and "vibetter.ide" in PS1


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
def test_install_sh_parses():
    subprocess.run(["bash", "-n", str(ROOT / "install.sh")], check=True)
