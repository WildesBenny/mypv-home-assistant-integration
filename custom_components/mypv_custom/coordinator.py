"""Data update coordinator for the my-PV integration."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable, Coroutine
from typing import Any, Concatenate, Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
)
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    MyPVAuthenticationError,
    MyPVConnectionError,
    MyPVDevice,
    MyPVTooManyRequestsError,
)
from .const import DOMAIN, MANUFACTURER, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


def _handle_device_errors[**P](
    func: Callable[Concatenate[MyPVCoordinator, P], Coroutine[Any, Any, bool]],
) -> Callable[Concatenate[MyPVCoordinator, P], Coroutine[Any, Any, bool]]:
    """Connect if needed and translate device errors to Home Assistant errors."""

    @functools.wraps(func)
    async def wrapper(self: MyPVCoordinator, *args: P.args, **kwargs: P.kwargs) -> bool:
        try:
            if not self.device.connected and not await self.device.connect():
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="cannot_connect",
                )
            return await func(self, *args, **kwargs)
        except MyPVTooManyRequestsError as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="rate_limiting"
            ) from exc
        except MyPVAuthenticationError as exc:
            self.config_entry.async_start_reauth(self.hass)
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_error",
            ) from exc
        except MyPVConnectionError as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_unavailable",
                translation_placeholders={"uri": str(self.device.uri)},
            ) from exc

    return wrapper


type MyPVConfigEntry = ConfigEntry[MyPVCoordinator]


class MyPVCoordinator(DataUpdateCoordinator[None]):
    """my-PV data update coordinator."""

    config_entry: MyPVConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: MyPVConfigEntry,
        device: MyPVDevice,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=config_entry,
            update_interval=UPDATE_INTERVAL,
            always_update=True,
        )

        self.device: Final[MyPVDevice] = device

        connections = set()
        if device.mac_address:
            connections.add((CONNECTION_NETWORK_MAC, device.mac_address))

        model = device.model
        name = model if model.lower().startswith("my-pv") else f"{MANUFACTURER} {model}"

        self.device_info: Final[DeviceInfo] = DeviceInfo(
            configuration_url=device.setup_uri,
            connections=connections,
            identifiers={(DOMAIN, device.serial_number)},
            manufacturer=MANUFACTURER,
            model=model,
            name=name,
            serial_number=device.serial_number,
            sw_version=device.firmware_version,
            hw_version=device.hardware_version,
        )

    async def async_disconnect(self) -> bool:
        """Disconnect from the device."""
        return await self.device.disconnect()

    async def _async_update_data(self) -> None:
        """Fetch data from the device."""
        try:
            if not self.device.connected and not await self.device.connect():
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="cannot_connect",
                )

            if not await self.device.fetch_data():
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="fetch_failed",
                )
        except MyPVTooManyRequestsError:
            # Keep the previous data and poll slower instead of going unavailable.
            _LOGGER.debug("Device is rate limiting, reducing update interval")
            self.update_interval = UPDATE_INTERVAL * 2
        except MyPVAuthenticationError as exc:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_error",
            ) from exc
        except MyPVConnectionError as exc:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="device_unavailable",
                translation_placeholders={"uri": self.device.uri},
            ) from exc

    @_handle_device_errors
    async def set_setup_value(self, key: str, value: Any) -> bool:
        """Set a setup value."""
        result = await self.device.set_setup_value(key, value)
        self.async_update_listeners()
        return result

    @_handle_device_errors
    async def set_target_temperature(self, temperature: float) -> bool:
        """Set the target temperature."""
        result = await self.device.set_target_temperature(temperature)
        self.async_update_listeners()
        return result

    @_handle_device_errors
    async def send_command(self, key: str, value: Any = None) -> bool:
        """Send a command to the device."""
        result = await self.device.send_command(key, value)
        self.async_update_listeners()
        return result

    @_handle_device_errors
    async def turn_on(self) -> bool:
        """Turn the device on."""
        result = await self.device.turn_on()
        self.async_update_listeners()
        return result

    @_handle_device_errors
    async def turn_off(self) -> bool:
        """Turn the device off."""
        result = await self.device.turn_off()
        self.async_update_listeners()
        return result

    @_handle_device_errors
    async def update_firmware(self) -> bool:
        """Update the device firmware."""
        result = await self.device.update_firmware()
        self.async_update_listeners()
        return result
