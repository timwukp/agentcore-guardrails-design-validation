"""Offline enforcement for the F2-5 analysis-function suite.

Same shape and same reason as `lib/tests/conftest.py`: the fingerprint function is what turns
300 guardrail responses into the single number the oracle reads, so it must be testable without
credentials and provably unable to reach the network.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "f2_determinism"))

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
    for var in _AWS_ENV:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/dev/null/nonexistent")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/dev/null/nonexistent")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")

    def _blocked(self, address):  # noqa: ANN001
        raise RuntimeError(
            f"network access blocked in the F2-5 test suite (attempted {address!r})")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    yield
