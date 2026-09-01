import os
from pathlib import Path

import pytest

# Tests spawn `uv run --frozen python …` subprocesses to exercise public
# entrypoints. Under parallel workers dozens of those validate the same
# environment at once and fight over uv's lock (measured: cascading
# returncode-2 timeouts). The gate syncs the environment before pytest runs,
# so children can skip re-syncing. Overridable with UV_NO_SYNC=0.
os.environ.setdefault("UV_NO_SYNC", "1")


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]

