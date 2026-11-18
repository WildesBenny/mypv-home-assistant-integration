"""Device model for the my-PV WiFi Meter.

The WiFi Meter is a grid meter with a local Wi-Fi interface. It uses a
different API than the heating devices, so it gets its own connection and a
configuration defined in code.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Final

from aiohttp import ClientSession

from .connection import MyPVMeterConnection
from .device import MyPVDevice
from .exceptions import MyPVConnectionError

_LOGGER = logging.getLogger(__name__)

MODEL_NAME: Final = "my-PV WiFi Meter"

_PHASES: Final = ("l1", "l2", "l3")

_DATA_CONFIG: Final[dict[str, dict[str, Any]]] = {
    **{
        f"volt_{phase}": {
            "name": f"Voltage {phase.upper()}",
            "type": "number",
            "unit": "V",
        }
        for phase in _PHASES
    },
    **{
        f"curr_{phase}": {
            "name": f"Current {phase.upper()}",
            "type": "number",
            "unit": "A",
        }
        for phase in _PHASES
    },
    **{
        f"power_{phase}": {
            "name": f"Power {phase.upper()}",
            "type": "number",
            "unit": "W",
        }
        for phase in _PHASES
    },
    **{
        f"energy_supply_{phase}": {
            "name": f"Grid supply {phase.upper()}",
            "type": "number",
            "unit": "kWh",
        }
        for phase in _PHASES
    },
    **{
        f"energy_feed_{phase}": {
            "name": f"Feed-in {phase.upper()}",
            "type": "number",
            "unit": "kWh",
        }
        for phase in _PHASES
    },
    "freq": {"name": "Mains frequency", "type": "number", "unit": "Hz"},
    "wifi_signal_strength": {
        "name": "Wi-Fi signal strength",
        "type": "number",
        "unit": "dBm",
    },
    "ssid": {"name": "Wi-Fi SSID", "type": "string"},
}

_SETUP_CONFIG: Final[dict[str, dict[str, Any]]] = {
    "ct": {
        "name": "CT clamp ratio",
        "type": "number",
        "min": 1,
        "max": 100,
        "step": 0.5,
    },
}

_COMMAND_CONFIG: Final[dict[str, dict[str, Any]]] = {
    "reboot_device": {"name": "Reboot", "type": "any"},
    "factory_reset": {"name": "Factory reset", "type": "any", "advanced": True},
}


class MyPVMeterDevice(MyPVDevice):
    """my-PV WiFi Meter reached over a local TCP/IP connection."""

    _host: str
    _connection: MyPVMeterConnection

    def __init__(
        self,
        host: str,
        *,
        advanced: bool = False,
        session: ClientSession | None = None,
    ) -> None:
        """Initialize a locally connected WiFi Meter."""
        if not host:
            raise ValueError("host is required")

        super().__init__(advanced=advanced)

        self._host = host
        self._model = MODEL_NAME
        self._connection = MyPVMeterConnection(host, session=session)
        self._setup_uri = f"http://{host}/"
        self._uri = self._connection.uri
        self._main_modes = None

    def _read_config(self) -> None:
        """Load the WiFi Meter configuration."""
        self._device_config = {
            "setup": {key: dict(val) for key, val in _SETUP_CONFIG.items()},
            "data": {key: dict(val) for key, val in _DATA_CONFIG.items()},
            "commands": {key: dict(val) for key, val in _COMMAND_CONFIG.items()},
        }

    async def connect(self) -> bool:
        """Connect to the meter and read its metadata."""
        await self.disconnect()

        connection = self._connection

        try:
            if not await connection.open():
                return False
        except MyPVConnectionError:
            return False
        finally:
            if connection.mypv_dev:
                self._serial_number = str(connection.mypv_dev.get("sn", ""))
                self._firmware_version = connection.mypv_dev.get("fwversion")
                mac = connection.mypv_dev.get("mac") or connection.mypv_dev.get("macadr")
                if mac:
                    mac = re.sub("[^0-9a-f]", "", str(mac).lower())
                    if len(mac) == 12:
                        self._mac_address = ":".join(
                            mac[i : i + 2] for i in range(0, 12, 2)
                        )
            self._read_config()

        try:
            setup_values = await connection.fetch_setup()
            data_values = await connection.fetch_data()
            if not setup_values or not data_values:
                await connection.close()
                return False

            self._update_values(setup_values, data_values)
        except MyPVConnectionError:
            await connection.close()
            return False

        return True

    # -- meter specific convenience --------------------------------------

    @property
    def grid_power(self) -> float | None:
        """Return the total grid power in watts."""
        values = [
            value
            for phase in _PHASES
            if (value := self._get_data_value(f"power_{phase}")) is not None
        ]
        return float(sum(values)) if values else None

    @property
    def primary_mode(self):
        """The meter has no operating mode."""
        return None

    @property
    def current_temperature(self) -> float | None:
        """The meter has no temperature."""
        return None

    @property
    def target_temperature(self) -> float | None:
        """The meter has no target temperature."""
        return None

    @property
    def is_on(self) -> bool | None:
        """The meter has no on/off state."""
        return None
