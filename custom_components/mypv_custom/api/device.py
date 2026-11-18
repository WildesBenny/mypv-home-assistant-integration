"""Device model for my-PV devices.

This is a self-contained implementation of the local my-PV protocol. It merges
the static per-product configuration with the values returned by the device so
that every value and setting the device exposes can be surfaced.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from enum import StrEnum
from typing import Any, Final

from aiohttp import ClientSession

from .configs import read_config
from .connection import (
    MyPVConnection,
    MyPVHTTPConnection,
    MyPVHTTPSConnection,
    _MyPVRequestCancelledError,
)
from .exceptions import (
    MyPVAuthenticationError,
    MyPVConnectionError,
    MyPVException,
    MyPVNotSupportedError,
    MyPVTooManyRequestsError,
)

_LOGGER = logging.getLogger(__name__)

# Keys that only carry static device information and are not exposed as entities.
_IGNORED_SETUP_KEYS: Final[list[str]] = [
    "fwversion",
    "psversion",
    "hwvers",
    "serialno",
    "macadr",
]
_IGNORED_DATA_KEYS: Final[list[str]] = ["device"]

# Boost related setup keys that are only relevant when boost mode is enabled.
_BOOST_SETUP_KEYS: Final[list[str]] = [
    "boostactive",
    "bsttof1",
    "bsttof2",
    "bstton1",
    "bstton2",
    "bstwd1",
    "bstwd2",
    "bstwd3",
    "bstwd4",
    "bstwd5",
    "bstwd6",
    "bstwd7",
    "ww1boost",
]

# The setup values are refreshed every N polls to reduce device load.
_SETUP_REFRESH_EVERY: Final = 6

_FW_VERSION_COMPARE_RE = re.compile("([<>=]*)[a-z]([0-9]*)")


def _to_int(value: Any, default: int | None = None) -> int | None:
    """Convert a device value to int, tolerating strings."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _synth_config(key: str, value: Any) -> dict[str, Any]:
    """Build a read-only advanced config for a field unknown to the config."""
    if isinstance(value, bool):
        value_type = "boolean"
    elif isinstance(value, (int, float)):
        value_type = "number"
    else:
        value_type = "string"

    name = key.replace("_", " ").strip()
    return {
        "name": name[:1].upper() + name[1:] if name else key,
        "type": value_type,
        "advanced": True,
        "readonly": True,
        "synthetic": True,
    }


class MyPVDeviceMainMode(StrEnum):
    """The main operating modes a my-PV device can support."""

    HOT_WATER = "boiler"
    SPACE_HEATING = "space_heating"
    HEATPUMP = "heatpump"
    PWM = "pwm"


class MyPVDevice:
    """Base class for interfacing with my-PV devices."""

    advanced: bool = False

    _serial_number: str = ""
    _model: str = ""
    _hardware_version: str | None = None
    _firmware_version: str | None = None
    _mac_address: str | None = None

    _connection: MyPVConnection | None = None
    _uri: str = ""
    _setup_uri: str | None = None

    _setup_values: dict[str, Any]
    _cached_setup_values: dict[str, Any]
    _data_values: dict[str, Any]
    _cached_data_values: dict[str, Any]
    _device_config: dict[str, Any]

    _main_modes: tuple[MyPVDeviceMainMode, ...] | None = None

    _firmware_update_lock: asyncio.Lock
    _next_check_fwupd: float | None = None

    _poll_count: int = 0
    _pending_writes: dict[str, asyncio.Event]

    def __init__(self, advanced: bool = False) -> None:
        """Initialize a my-PV device."""
        self.advanced = advanced

        self._setup_values = {}
        self._cached_setup_values = {}
        self._data_values = {}
        self._cached_data_values = {}
        self._device_config = {"setup": {}, "data": {}, "commands": {}}

        self._firmware_update_lock = asyncio.Lock()
        self._pending_writes = {}

    async def connect(self) -> bool:
        """Connect to the device; implemented by subclasses."""
        raise NotImplementedError

    def _init_device(
        self, setup_values: dict[str, Any], data_values: dict[str, Any]
    ) -> None:
        """Derive device metadata and available modes from the device values."""
        self._hardware_version = setup_values.get("hwvers")
        self._firmware_version = setup_values.get("fwversion")

        mac_address = setup_values.get("macadr")
        if mac_address:
            mac_address = re.sub("[^0-9a-f]", "", str(mac_address).lower())
            if len(mac_address) == 12:
                self._mac_address = ":".join(
                    mac_address[i : i + 2] for i in range(0, 12, 2)
                )

        match _to_int(setup_values.get("mainmode")):
            case 4:
                self._main_modes = (
                    MyPVDeviceMainMode.HOT_WATER,
                    MyPVDeviceMainMode.HEATPUMP,
                )
            case 5:
                self._main_modes = (
                    MyPVDeviceMainMode.HOT_WATER,
                    MyPVDeviceMainMode.SPACE_HEATING,
                )
            case 6:
                self._main_modes = (MyPVDeviceMainMode.SPACE_HEATING,)
            case 7:
                self._main_modes = (
                    MyPVDeviceMainMode.HOT_WATER,
                    MyPVDeviceMainMode.PWM,
                )
            case _:
                self._main_modes = (MyPVDeviceMainMode.HOT_WATER,)

        setup_config = self._device_config["setup"]

        # Boost mode on the AC ELWA 2 depends on the main mode.
        if (
            self.serial_number.startswith(("160150", "160151", "160152"))
            and _to_int(setup_values.get("mainmode")) == 1
            and "bstmode" in setup_config
        ):
            setup_config["bstmode"].get("options", {}).pop("5", None)

        # Disable boost settings when no temperature sensor is connected.
        if data_values.get("temp1") in (None, 0):
            for key in (
                "bstmode",
                "bsttemp",
                "ww1boost",
                "ww_boost_h",
                "ww_targ_h",
            ):
                setup_config.pop(key, None)

        # Disable maximum power for the AC ELWA 2 in the combined 3.5 + 3 kW mode.
        if (
            self.serial_number.startswith(("160150", "160151"))
            and _to_int(setup_values.get("mainmode")) == 3
        ):
            setup_config.pop("maxpwr", None)

        # Disable warm water related settings on AC THOR devices in modes 5 and 6.
        if self.serial_number.startswith(
            ("200100", "200103", "200110", "200113", "200300", "200310")
        ) and _to_int(setup_values.get("mainmode")) in [5, 6]:
            for key in ("bstmode", "bststrt", "ww_boost_h", "ww_targ_h", *_BOOST_SETUP_KEYS):
                setup_config.pop(key, None)
                self._device_config["data"].pop(key, None)
                self._device_config["commands"].pop(key, None)

    # -- connection state -------------------------------------------------

    @property
    def connected(self) -> bool:
        """Return True when the connection is established."""
        if self._connection:
            return self._connection.is_open()
        return False

    @property
    def setup_uri(self) -> str | None:
        """Return the location of the device setup web interface."""
        return self._setup_uri

    @property
    def uri(self) -> str:
        """Return the underlying connection URI."""
        return self._uri

    async def disconnect(self) -> bool:
        """Disconnect from the device."""
        if self._connection is None:
            return True
        return await self._connection.close()

    # -- device metadata --------------------------------------------------

    @property
    def serial_number(self) -> str:
        """Return the device serial number."""
        return self._serial_number

    @property
    def model(self) -> str:
        """Return the device model."""
        return self._model

    @property
    def hardware_version(self) -> str | None:
        """Return the device hardware version."""
        return self._hardware_version

    @property
    def firmware_version(self) -> str | None:
        """Return the device firmware version."""
        return self._firmware_version

    @property
    def mac_address(self) -> str | None:
        """Return the device MAC address."""
        return self._mac_address

    @property
    def latest_firmware_version(self) -> str | None:
        """Return the latest available firmware version."""
        value = self._get_data_value("fwversionlatest")
        return str(value) if value is not None else None

    @property
    def firmware_update_available(self) -> bool:
        """Return True when a firmware update is available."""
        if (
            not self.supports_command("firmware_update")
            or not self.firmware_version
            or not self.latest_firmware_version
        ):
            return False
        return self._get_data_value("upd_state") not in [None, "0"]

    @property
    def firmware_update_progress(self) -> int | None:
        """Return the firmware update progress in percent, or None."""
        if self._get_data_value("upd_state") != "3":
            return None
        for key in ("upd_percentage", "upd_pct"):
            if self.supports_data(key):
                value = self._get_data_value(key)
                return int(value) if value is not None else None
        return None

    async def update_firmware(self) -> bool:
        """Update the firmware on the device."""
        if self._get_data_value("upd_state") in [None, "0"]:
            return False

        if self._firmware_update_lock.locked():
            return False

        async with self._firmware_update_lock:
            if (
                self.supports_command("firmware_download")
                and self._get_data_value("upd_state") == "1"
            ):
                await self.send_command("firmware_download")

            if self._get_data_value("upd_state") in [str(x) for x in range(1, 10)]:
                timeout = time.monotonic() + 300
                while True:
                    if self._get_data_value("upd_state") == "10":
                        break
                    if self._get_data_value("upd_state") == "99":
                        break
                    if time.monotonic() > timeout:
                        return False
                    await asyncio.sleep(1)
                    with contextlib.suppress(MyPVTooManyRequestsError):
                        await self.fetch_data()

            if (
                self.supports_command("firmware_update")
                and self._get_data_value("upd_state") == "10"
            ):
                await self.send_command("firmware_update")

            timeout = time.monotonic() + 300
            while True:
                if self._get_data_value("upd_state") == "0":
                    return True
                if self._get_data_value("upd_state") == "99":
                    return False
                if time.monotonic() > timeout:
                    return False
                await asyncio.sleep(1)
                if not self.connected:
                    with contextlib.suppress(MyPVConnectionError):
                        await self.connect()
                with contextlib.suppress(MyPVConnectionError):
                    await self.fetch_data()

    # -- config -----------------------------------------------------------

    def _read_config(self) -> None:
        """Read the static configuration for this device."""
        self._device_config = read_config(self.serial_number)

    def _update_values(
        self,
        setup_values: dict[str, Any] | None,
        data_values: dict[str, Any] | None,
    ) -> None:
        """Merge new values into the cached setup and data values."""
        if setup_values is not None:
            for key, val in setup_values.items():
                if key in _IGNORED_SETUP_KEYS or key in self._pending_writes:
                    continue
                if val in [None, "null"]:
                    self._cached_setup_values.pop(key, None)
                else:
                    self._cached_setup_values[key] = val

        if data_values is not None:
            self._cached_data_values = {
                key: val
                for key, val in data_values.items()
                if key not in _IGNORED_DATA_KEYS
                and val not in [None, "null"]
                and not (
                    key in self._device_config["data"]
                    and self._device_config["data"][key].get("type") == "number"
                    and self._device_config["data"][key].get("unit") == "°C"
                    and _to_int(val) == 0
                )
            }

        setup = self._cached_setup_values
        data = self._cached_data_values

        self._setup_values = {
            key: setup[key]
            for key, config in self._device_config["setup"].items()
            if key in setup and not config.get("readonly", False)
        } | {
            key: data[key]
            for key, config in self._device_config["data"].items()
            if key in data and not config.get("readonly", True)
        }

        self._data_values = {
            key: setup[key]
            for key, config in self._device_config["setup"].items()
            if key in setup and config.get("readonly", False)
        } | {
            key: data[key]
            for key, config in self._device_config["data"].items()
            if key in data and config.get("readonly", True)
        }

        self._add_unknown_configs()

    def _add_unknown_configs(self) -> None:
        """Expose fields returned by the device that are not in the config.

        Unknown fields are added as read-only diagnostic values so that no
        value the device reports is silently dropped. They are only shown when
        advanced mode is enabled.
        """
        known = set(self._device_config["setup"]) | set(self._device_config["data"])

        for key, value in self._cached_setup_values.items():
            if key in known:
                continue
            self._device_config["setup"][key] = _synth_config(key, value)
            known.add(key)

        for key, value in self._cached_data_values.items():
            if key in known:
                continue
            self._device_config["data"][key] = _synth_config(key, value)
            known.add(key)

    async def fetch_data(self) -> bool:
        """Fetch data from the device."""
        if not self._connection or not self.connected:
            return False

        setup_values = None
        if self._poll_count % _SETUP_REFRESH_EVERY == 0:
            setup_values = await self._connection.fetch_setup()
            if not setup_values:
                return False

        data_values = await self._connection.fetch_data()
        if not data_values:
            return False

        self._update_values(setup_values, data_values)

        if self.supports_command("check_fwupd") and (
            not self._next_check_fwupd or time.monotonic() > self._next_check_fwupd
        ):
            with contextlib.suppress(MyPVConnectionError):
                await self.send_command("check_fwupd")
            self._next_check_fwupd = time.monotonic() + 24 * 60 * 60

        self._poll_count += 1
        return True

    # -- setup values -----------------------------------------------------

    def supports_setup(self, key: str) -> bool:
        """Return True when the device supports the given setup parameter."""
        if key not in self._setup_values:
            return False
        if (
            key in self._device_config["setup"]
            and not self._device_config["setup"][key].get("readonly", False)
            and self._device_config["setup"][key].get("advanced", False)
            in [False, self.advanced]
        ):
            return True
        return (
            key in self._device_config["data"]
            and not self._device_config["data"][key].get("readonly", True)
            and self._device_config["data"][key].get("advanced", False)
            in [False, self.advanced]
        )

    def get_setup_configurations(self) -> dict[str, dict[str, Any]]:
        """Return the configuration of the available setup parameters."""
        setup_keys = self._setup_values.keys()
        return {
            key: val
            for key, val in self._device_config["setup"].items()
            if key in setup_keys
            and not val.get("readonly", False)
            and val.get("advanced", False) in [False, self.advanced]
        } | {
            key: val
            for key, val in self._device_config["data"].items()
            if key in setup_keys
            and not val.get("readonly", True)
            and val.get("advanced", False) in [False, self.advanced]
        }

    def get_setup_configuration(self, key: str) -> dict[str, Any] | None:
        """Return the configuration of the given setup parameter."""
        return self.get_setup_configurations().get(key)

    def get_setup_value(self, key: str) -> bool | int | float | str | None:
        """Return the value of the given setup parameter."""
        if not self.connected:
            raise MyPVConnectionError("Device not connected")

        if not self.supports_setup(key):
            raise MyPVNotSupportedError(key)

        # Only the device mode and target temperatures stay available when off.
        if (
            key
            not in ["devmode", "ww1target", "rh1_target", "rh2_target", "rh3_target"]
            and _to_int(self._setup_values.get("devmode")) == 0
        ):
            return None

        if key in _BOOST_SETUP_KEYS and _to_int(self._setup_values.get("bstmode"), 0) == 0:
            return None

        return self._convert_value(
            self.get_setup_configuration(key), self._setup_values.get(key)
        )

    async def set_setup_value(self, key: str, value: Any) -> bool:
        """Set the value of the given setup parameter."""
        if not self._connection or not self.connected:
            raise MyPVConnectionError("Device not connected")

        if not self.supports_setup(key):
            raise MyPVNotSupportedError(key)

        if (
            key
            not in ["devmode", "ww1target", "rh1_target", "rh2_target", "rh3_target"]
            and _to_int(self._setup_values.get("devmode")) == 0
        ):
            return False

        if key in _BOOST_SETUP_KEYS and _to_int(self._setup_values.get("bstmode"), 0) == 0:
            return False

        config = self.get_setup_configuration(key)
        if config:
            command = config.get("command")
            if command:
                result = await self.send_command(command, value)
                if result:
                    self._cached_data_values[key] = value
                    self._update_values(None, None)
                return result

            match config.get("type"):
                case "boolean":
                    value = int(value)
                case "number":
                    if not config.get("min", 0) <= value <= config.get("max", 0):
                        return False
                    if divider := config.get("divider"):
                        value = value * divider
                    if multiplier := config.get("multiplier"):
                        value = value / multiplier
                    value = round(value)
                case "enumeration":
                    if value not in config.get("options", {}):
                        return False
                    value = int(value)

        if previous := self._pending_writes.get(key):
            previous.set()
        cancel = asyncio.Event()
        self._pending_writes[key] = cancel

        self._cached_setup_values[key] = value
        self._update_values(None, None)

        try:
            response = await self._connection.set_setup_value(key, value, cancel=cancel)
        except _MyPVRequestCancelledError:
            return True
        except MyPVException:
            self._poll_count = 0
            raise
        finally:
            if self._pending_writes.get(key) is cancel:
                del self._pending_writes[key]

        if not response:
            self._poll_count = 0
            return False

        self._update_values(response, None)
        return str(response.get(key)) == str(value)

    # -- data values ------------------------------------------------------

    def supports_data(self, key: str) -> bool:
        """Return True when the given data key is supported by the device."""
        if key not in self._data_values:
            return False
        if (
            key in ["wifi_signal", "wifi_signal_strength"]
            and self._data_values.get("cur_eth_mode") == 0
        ):
            return False
        if (
            key in self._device_config["data"]
            and self._device_config["data"][key].get("readonly", True)
            and self._device_config["data"][key].get("advanced", False)
            in [False, self.advanced]
        ):
            return True
        return (
            key in self._device_config["setup"]
            and self._device_config["setup"][key].get("readonly", False)
            and self._device_config["setup"][key].get("advanced", False)
            in [False, self.advanced]
        )

    def get_data_configurations(self) -> dict[str, dict[str, Any]]:
        """Return the configuration of the available data keys."""
        data_keys = self._data_values.keys()
        data_configurations = {
            key: val
            for key, val in self._device_config["setup"].items()
            if key in data_keys
            and val.get("readonly", False)
            and val.get("advanced", False) in [False, self.advanced]
        } | {
            key: val
            for key, val in self._device_config["data"].items()
            if key in data_keys
            and val.get("readonly", True)
            and val.get("advanced", False) in [False, self.advanced]
        }

        if self._data_values.get("cur_eth_mode") == 0:
            data_configurations.pop("wifi_signal", None)
            data_configurations.pop("wifi_signal_strength", None)

        return data_configurations

    def get_data_configuration(self, key: str) -> dict[str, Any] | None:
        """Return the configuration of the given data key."""
        return self.get_data_configurations().get(key)

    def _convert_value(
        self, config: dict[str, Any] | None, value: Any
    ) -> bool | int | float | str | None:
        """Convert a raw device value to its typed value."""
        if config and value is not None:
            match config.get("type"):
                case "boolean":
                    value = bool(value)
                case "number":
                    value = float(value)
                    if divider := config.get("divider"):
                        value = value / divider
                    if multiplier := config.get("multiplier"):
                        value = value * multiplier
                case "enumeration":
                    value = str(value)
                case "string":
                    value = str(value)
        return value

    def _get_data_value(self, key: str) -> bool | int | float | str | None:
        """Return the value of the given data key or None."""
        return self._convert_value(
            self.get_data_configuration(key), self._data_values.get(key)
        )

    def get_data_value(self, key: str) -> bool | int | float | str | None:
        """Return the value of the given data key."""
        if not self.connected:
            raise MyPVConnectionError("Device not connected")
        if not self.supports_data(key):
            raise MyPVNotSupportedError(key)
        return self._get_data_value(key)

    # -- commands ---------------------------------------------------------

    def supports_command(self, command: str) -> bool:
        """Return True when the command is supported by the device."""
        return command in self._device_config["commands"] and self._device_config[
            "commands"
        ][command].get("advanced", False) in [False, self.advanced]

    def get_command_configurations(self) -> dict[str, dict[str, Any]]:
        """Return the configuration of the available commands."""
        return {
            key: val
            for key, val in self._device_config["commands"].items()
            if val.get("advanced", False) in [False, self.advanced]
        }

    def get_command_configuration(self, command: str) -> dict[str, Any] | None:
        """Return the configuration for a command."""
        return self.get_command_configurations().get(command)

    async def send_command(self, command: str, value: Any = None) -> bool:
        """Send a command to the device."""
        if not self._connection or not self.connected:
            raise MyPVConnectionError("Device not connected")

        if not self.supports_command(command):
            raise MyPVNotSupportedError(command)

        config = self.get_command_configuration(command)
        if config:
            if value is None and config.get("type") in ("boolean", "number"):
                return False
            match config.get("type"):
                case "boolean":
                    value = int(value)
                case "number":
                    if not config.get("min", 0) <= value <= config.get("max", 0):
                        return False
                    if divider := config.get("divider"):
                        value = value * divider
                    if multiplier := config.get("multiplier"):
                        value = value / multiplier
                    value = round(value)
                case "fixed":
                    value = config.get("value")
                case "any":
                    value = 1

        return await self._connection.send_command(command, value)

    # -- modes and convenience -------------------------------------------

    def supports_main_mode(self, mode: MyPVDeviceMainMode) -> bool:
        """Return True when the device supports the given main mode."""
        if not self._main_modes:
            return False
        return mode in self._main_modes

    @property
    def primary_mode(self) -> MyPVDeviceMainMode | None:
        """Return the primary mode of the device."""
        if self._main_modes:
            return self._main_modes[0]
        return None

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        value = self.get_data_value("temp1") if self.supports_data("temp1") else None
        return float(value) if value is not None else None

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        if _to_int(self._setup_values.get("mainmode")) == 6:
            value = self.get_setup_value("rh1_target")
        else:
            value = self.get_setup_value("ww1target")
        return float(value) if value is not None else None

    async def set_target_temperature(self, temperature: float) -> bool:
        """Set the device target temperature."""
        if _to_int(self._setup_values.get("mainmode")) == 6:
            return await self.set_setup_value("rh1_target", temperature)
        return await self.set_setup_value("ww1target", temperature)

    @property
    def is_on(self) -> bool | None:
        """Return True when the device is on."""
        value = self.get_setup_value("devmode")
        return None if value is None else bool(value)

    async def turn_on(self) -> bool:
        """Turn the device on."""
        return await self.set_setup_value("devmode", True)

    async def turn_off(self) -> bool:
        """Turn the device off."""
        return await self.set_setup_value("devmode", False)


class MyPVLocalDevice(MyPVDevice):
    """my-PV device reached over a local TCP/IP connection."""

    _host: str
    _password: str | None
    _connection: MyPVHTTPConnection

    def __init__(
        self,
        host: str,
        password: str | None = None,
        *,
        advanced: bool = False,
        session: ClientSession | None = None,
    ) -> None:
        """Initialize a locally connected my-PV device."""
        if not host:
            raise ValueError("host is required")

        super().__init__(advanced=advanced)

        self._host = host
        self._password = password

        if password:
            self._connection = MyPVHTTPSConnection(host, password, session=session)
            self._setup_uri = f"https://{host}/"
        else:
            self._connection = MyPVHTTPConnection(host, session=session)
            self._setup_uri = f"http://{host}/"
        self._uri = self._connection.uri

    async def connect(self) -> bool:
        """Connect to the device and read its metadata."""
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
                self._read_config()
                if name := self._device_config.get("name"):
                    self._model = name
                else:
                    self._model = str(connection.mypv_dev.get("device", "") or "")

        try:
            setup_values = await connection.fetch_setup()
            data_values = await connection.fetch_data()
            if not setup_values or not data_values:
                await connection.close()
                return False

            self._init_device(setup_values, data_values)
            self._update_values(setup_values, data_values)
        except MyPVConnectionError:
            await connection.close()
            return False
        except (MyPVAuthenticationError, MyPVNotSupportedError):
            await connection.close()
            raise

        return True
