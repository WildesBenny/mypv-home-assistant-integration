"""Diagnostics support for the my-PV integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .coordinator import MyPVConfigEntry

TO_REDACT = {CONF_PASSWORD}


def _collect(device: Any) -> dict[str, Any]:
    """Collect the supported setup and data values from a device."""
    setup: dict[str, Any] = {}
    data: dict[str, Any] = {}

    for key in device.get_setup_configurations():
        try:
            setup[key] = device.get_setup_value(key)
        except Exception:  # noqa: BLE001 - diagnostics must never fail
            setup[key] = None

    for key in device.get_data_configurations():
        try:
            data[key] = device.get_data_value(key)
        except Exception:  # noqa: BLE001 - diagnostics must never fail
            data[key] = None

    return {"setup": setup, "data": data}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MyPVConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    device = coordinator.device

    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "device": {
            "model": device.model,
            "serial_number": device.serial_number,
            "firmware_version": device.firmware_version,
            "hardware_version": device.hardware_version,
            "mac_address": device.mac_address,
            "uri": device.uri,
            "connected": device.connected,
        },
        "values": _collect(device),
    }
