"""Configuration loading for my-PV devices.

Each product family has a JSON file named after the serial number prefix that
describes the setup values, data values and commands it exposes. Files are
merged from the most generic to the most specific prefix, for example
``000000.json`` + ``20.json`` + ``200.json`` + ``200300.json``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

_CONFIGS_DIR = Path(__file__).parent


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge ``override`` into ``base``; a null value removes the inherited key."""
    for key, value in override.items():
        if value is None:
            base.pop(key, None)
        elif isinstance(value, dict):
            if not isinstance(base.get(key), dict):
                base[key] = {}
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def read_config(serial_number: str) -> dict[str, Any]:
    """Read and merge the configuration for a device serial number."""
    prefix = "".join(
        c if c.isalnum() or c in "._-" else "_" for c in serial_number[:6].lower()
    )

    config_files = ["000000.json"]
    config_files.extend(prefix[:n] + ".json" for n in range(1, 7))

    config: dict[str, Any] = {}
    for config_file in config_files:
        path = _CONFIGS_DIR / config_file
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            _LOGGER.warning("Invalid configuration file %s", config_file)
            continue
        if isinstance(data, dict):
            config = _deep_merge(config, data)

    for section in ("setup", "data", "commands"):
        config.setdefault(section, {})

    return config
