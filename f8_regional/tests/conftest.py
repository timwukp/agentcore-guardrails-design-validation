"""Offline enforcement for the F8-family analysis-function suite.

Same shape and same reason as `lib/tests/conftest.py`. F8's helpers parse ARNs, split arms into
strata, and build the probe ids the resume logic keys on — all pure functions whose defects would
surface only mid-run, after the spend. They must be testable with no credentials and provably
no network.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "f8_regional"))

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
            f"network access blocked in the F8 test suite (attempted {address!r})")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    yield
