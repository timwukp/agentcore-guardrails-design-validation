"""Offline enforcement for the Phase 2 infrastructure suite.

Same shape and same reason as `lib/tests/conftest.py` and `f3_efficacy/tests/conftest.py`. The
stake is higher here than in the analysis suites: these tests exercise the modules whose job is
to **create and delete AWS resources**, in an account holding six live gateways and ~$27k/mo of
unrelated spend. A test that reached the network could delete something.

So the network block is not a hygiene measure, it is the isolation rule enforced at the only
level that cannot be forgotten: `socket.socket.connect` raises, credentials are unset, and the
credential files point at a path that cannot exist. Every test below either calls a pure
function or exercises a script's `--dry-run` path in a subprocess that inherits this
environment.

The `infra/` scripts are imported **by path** because their names start with digits.
`lib/tests/test_module_name_collisions.py` is the static gate that keeps those by-path module
names from shadowing anything `lib/` owns, which is why each `spec_from_file_location` below
uses an `_infra`-prefixed name.
"""

from __future__ import annotations

import importlib.util
import os
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "infra"))

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
            f"network access blocked in the infra test suite (attempted {address!r}). These "
            f"tests exercise resource CREATION and DELETION code against an account with six "
            f"live gateways; a test that reached the network could delete something.")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    yield


def load_infra(stem: str):
    """Import an `infra/NN_name.py` script by path under an `_infra`-prefixed module name."""
    path = ROOT / "infra" / f"{stem}.py"
    name = f"_infra_{stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def offline_env() -> dict:
    """An environment for subprocess `--dry-run` invocations, with credentials removed.

    A subprocess does not inherit the monkeypatched socket, so the guarantee for those tests is
    weaker by construction: it rests on the script's own `--dry-run` contract ("no AWS call
    made") plus unset credentials. That is stated rather than glossed, and it is why the
    subprocess tests assert on the dry-run banner — the banner is the script's claim, and the
    test's job is to hold it to it.
    """
    env = dict(os.environ)
    for var in _AWS_ENV:
        env.pop(var, None)
    env["AWS_SHARED_CREDENTIALS_FILE"] = "/dev/null/nonexistent"
    env["AWS_CONFIG_FILE"] = "/dev/null/nonexistent"
    env["AWS_EC2_METADATA_DISABLED"] = "true"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env
