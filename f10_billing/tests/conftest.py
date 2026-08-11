"""Offline enforcement for the F10-2 analysis-function suite.

These tests exercise the pure analysis half of `f10_billing/01_text_units.py` — the
functions that turn trial rows into the SCALING and MATCHING verdicts — against
hand-built rows. Loading the module must not require credentials and must not reach the
network: the case's whole value is that its verdict is a function of recorded evidence,
so a test that could silently depend on a live call would be testing something else.

The `no_aws` fixture is a copy of `lib/tests/conftest.py`'s and is autouse for the same
reason: a stray socket here would fail loudly rather than pass on a cached credential.

The path insertion is two entries because the case script imports from `lib/` (`phase1`,
`oracle`, `arms`, `awsclients`) as top-level modules, exactly as it does when run from
the project root.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "f10_billing"))

_AWS_ENV = (
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_DEFAULT_REGION", "AWS_REGION",
    "AWS_SHARED_CREDENTIALS_FILE", "AWS_CONFIG_FILE",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_ROLE_ARN",
)


@pytest.fixture(autouse=True)
def no_aws(monkeypatch):
    """Null AWS credentials and block outbound sockets for the whole suite."""
    for var in _AWS_ENV:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/dev/null/nonexistent")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/dev/null/nonexistent")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")

    def _blocked(self, address):  # noqa: ANN001
        raise RuntimeError(
            f"network access blocked in the F10-2 test suite (attempted {address!r})")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    yield
