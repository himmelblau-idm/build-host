"""Provide the build script as a module fixture (its filename is hyphenated,
so it cannot be imported normally)."""
import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "himmelblau-auto-build.py"


@pytest.fixture(scope="session")
def hab():
    spec = importlib.util.spec_from_file_location("himmelblau_auto_build", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
