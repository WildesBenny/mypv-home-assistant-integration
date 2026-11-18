"""pytest configuration for the my-PV integration tests."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from pytest_homeassistant_custom_component.common import get_test_config_dir

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def hass_config_dir(tmp_path: Path) -> str:
    """Return a config dir with the my-PV integration available."""
    shutil.copytree(get_test_config_dir(), tmp_path, dirs_exist_ok=True, symlinks=True)
    target = tmp_path / "custom_components" / "mypv_custom"
    if target.exists():
        shutil.rmtree(target)
    target.symlink_to(REPO_ROOT / "custom_components" / "mypv_custom")
    return str(tmp_path)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of the custom integration."""
    yield


@pytest.fixture(autouse=True)
def allow_sockets(socket_enabled):
    """Allow opening sockets for the mock device server."""
    yield
