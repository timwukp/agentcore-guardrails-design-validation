"""The by-path loader for `infra/NN_name.py` scripts, under a repo-unique module name.

This function lived in `infra/tests/conftest.py`, and two test modules imported it with
`from conftest import load_infra`. That worked for as long as `infra/tests` ran alone or with
directories whose `conftest.py` pytest happened to register later: `conftest` is a BASENAME, one
`sys.modules` slot, and eight test directories each have one. The first combined run to put
`f1_config/tests` in the same process as `infra/tests` (2026-08-13, when `verify_phase0.sh`
gained the three directories it had drifted past) resolved `from conftest import load_infra`
against f1_config's conftest and failed collection — while every per-directory run stayed green,
which is exactly the blindness `lib/tests/test_module_name_collisions.py` documents for by-path
loaders.

So the helper moves to a module whose stem is unique in the repository, and `conftest` is never
an import target again. The fixtures stay in conftest, where pytest wires them by mechanism
rather than by name.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_infra(stem: str):
    """Import an `infra/NN_name.py` script by path under an `_infra`-prefixed module name.

    The `_infra_` prefix is what `lib/tests/test_module_name_collisions.py` checks: scripts named
    `99_teardown.py` cannot be imported by name (digit-leading), and the prefixed registration
    must not shadow anything `lib/` owns.
    """
    path = ROOT / "infra" / f"{stem}.py"
    spec = importlib.util.spec_from_file_location(f"_infra_{stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
