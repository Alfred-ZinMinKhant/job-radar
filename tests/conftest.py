from pathlib import Path

import pytest

from jobradar.config import load_config

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def cfg():
    return load_config(ROOT / "config.yaml")
