"""Secret redaction applied to every prompt before it leaves the machine."""

from __future__ import annotations

import time

import pytest

from vibetter.redact import is_secret_path, redact

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("key = AKIAABCDEFGHIJKLMNOP", "AKIAABCDEFGHIJKLMNOP"),
        (
            "token: ghp_abcdefghijklmnopqrstuvwxyz0123456789",
            "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        ),
        (
            "pat=github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz",
            "github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz",
        ),
        (f"Authorization: Bearer {JWT}", JWT),
        ('api_key = "q8Zr2LmN0pXv7Ty4"', "q8Zr2LmN0pXv7Ty4"),
        ("client_secret: 'v3ryS3cretValue!'", "v3ryS3cretValue!"),
        ("DB_PASSWORD=correct-horse-battery", "correct-horse-battery"),
        ("OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuv", "sk-proj-abcdefghijklmnopqrstuv"),
        # The line prefixes added before text leaves: context blocks and numbered diffs.
        # Until 2026-10-26 the ^-anchored rule never matched them, so these values were sent.
        ("  2| export API_TOKEN=tok3nV4lue9999", "tok3nV4lue9999"),
        ("    7| +DB_PASSWORD=hunter2hunter2", "hunter2hunter2"),
        ("     | -DB_PASSWORD=hunter2hunter2", "hunter2hunter2"),
        ("+export API_TOKEN=tok3nV4lue9999", "tok3nV4lue9999"),
        (" 12|     export GH_TOKEN=abcdefgh1234", "abcdefgh1234"),
    ],
)
def test_redacts_known_secret_shapes(text: str, secret: str):
    out = redact(text)
    assert secret not in out
    assert "[REDACTED" in out


def test_private_key_block_redacted_and_line_count_kept():
    text = (
        "before\n-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nIBAAKC\n"
        "-----END RSA PRIVATE KEY-----\nafter\n"
    )
    out = redact(text)
    assert "MIIEow" not in out
    assert out.count("\n") == text.count("\n")
    assert out.startswith("before\n") and out.endswith("after\n")


def test_plain_code_is_left_alone():
    code = 'token = get_token()\npassword_hint = None\nsecret_len = len(x)\nname = "api_key"\n'
    assert redact(code) == code
    code = 'token=get_token()\n  4| API_KEY=os.environ["API_KEY"]\n'
    assert redact(code) == code


@pytest.mark.parametrize(
    "text",
    ["a" * 50_000, "a." * 25_000, "token_" * 8_000, " " * 50_000 + "\nx"],
    ids=["word", "dotted", "names", "spaces"],
)
def test_regression_redaction_is_linear(text: str):
    # An unbounded name scan took 2.7 s on 40k characters of "a.a.a...".
    start = time.perf_counter()
    redact(text)
    assert time.perf_counter() - start < 0.5


@pytest.mark.parametrize(
    ("path", "secret"),
    [
        (".env", True),
        (".env.local", True),
        ("config/prod.env", True),
        ("certs/server.pem", True),
        ("deploy/id_rsa", True),
        ("id_rsa.pub", True),
        ("gcp-credentials.json", True),
        ("app/credentials.json", True),
        ("src/env.py", False),
        ("README.md", False),
        (".env.example", True),
        (".envrc", True),
        ("deploy/prod.envrc", True),
        ("config/PROD.ENV", True),
    ],
)
def test_secret_paths(path: str, secret: bool):
    assert is_secret_path(path) is secret
