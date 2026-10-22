"""Secret handling: files that are never read, and redaction of prompt text.

Every prompt passes through redact() before it goes to a provider. The
replacements keep the line count, so file:line references stay valid.
"""

from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import PurePosixPath

# Matched against the file name. These files are never indexed or diffed.
SECRET_FILE_GLOBS = (
    ".env",
    ".env.*",
    "*.env",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.keystore",
    "*.jks",
    "*credentials*.json",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    ".netrc",
    ".npmrc",
    ".pypirc",
)

_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.DOTALL
)
_TOKENS = re.compile(
    r"\b(?:"
    r"(?:AKIA|ASIA)[0-9A-Z]{16}"  # AWS access key id
    r"|gh[pousr]_[A-Za-z0-9]{36,}"  # GitHub tokens
    r"|github_pat_[A-Za-z0-9_]{22,}"
    r"|sk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"  # OpenAI and Anthropic keys
    r"|AIza[0-9A-Za-z_-]{35}"  # Google API keys
    r"|xox[abposr]-[A-Za-z0-9-]{10,}"  # Slack tokens
    r"|eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"  # JWT
    r")"
)
_SECRET_NAME = r"[A-Za-z0-9_.-]*(?:api[_-]?key|secret|token|passw(?:or)?d|credential)[A-Za-z0-9_]*"
# name = "value" / name: 'value' in code and config, with a quoted value.
_QUOTED_ASSIGNMENT = re.compile(rf"(?i)(\b{_SECRET_NAME}[\"']?\s*[:=]\s*)([\"'])([^\"'\s]{{8,}})\2")
# NAME=value in dotenv and shell files, at the start of a line.
_DOTENV_ASSIGNMENT = re.compile(rf"(?im)^(\s*(?:export\s+)?{_SECRET_NAME}=)([^\s#\"']{{8,}})")


def is_secret_path(rel_path: str) -> bool:
    name = PurePosixPath(rel_path.replace("\\", "/")).name.lower()
    return any(fnmatch(name, glob) for glob in SECRET_FILE_GLOBS)


def _private_key(match: re.Match[str]) -> str:
    return "[REDACTED PRIVATE KEY]" + "\n" * match.group(0).count("\n")


def redact(text: str) -> str:
    text = _PRIVATE_KEY.sub(_private_key, text)
    text = _TOKENS.sub("[REDACTED]", text)
    text = _QUOTED_ASSIGNMENT.sub(r"\1\2[REDACTED]\2", text)
    return _DOTENV_ASSIGNMENT.sub(r"\1[REDACTED]", text)
