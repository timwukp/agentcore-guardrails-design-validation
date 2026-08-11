"""Offline enforcement for the stats-layer test suite.

``lib/stats.py`` must be provably incapable of touching AWS: it is the layer that
turns evidence into published numbers, so a stray network call there would mean a
figure could depend on something outside the recorded evidence store.

The ``no_aws`` fixture is autouse, so every test in this directory runs with
credentials nulled and ``socket.socket.connect`` monkeypatched to raise. A test
that tries to reach the network fails loudly rather than silently succeeding on a
cached credential.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

# lib/ is the package root for these tests; add its parent so `import stats` works
# without requiring an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
    # Point the credential resolution chain at a path that cannot exist.
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/dev/null/nonexistent")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/dev/null/nonexistent")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")

    def _blocked(self, address):  # noqa: ANN001
        raise RuntimeError(
            f"network access blocked in the stats test suite (attempted {address!r})"
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    yield
