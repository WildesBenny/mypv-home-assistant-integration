"""The my-PV integration for Home Assistant."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    MyPVAuthenticationError,
    MyPVDevice,
    MyPVDeviceNotSupportedError,
    MyPVLocalDevice,
    MyPVMeterDevice,
)
from .const import (
    CONF_ADVANCED,
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_METER,
    DOMAIN,
)
from .coordinator import MyPVConfigEntry, MyPVCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
    Platform.WATER_HEATER,
]


def create_device(
    hass: HomeAssistant, entry: MyPVConfigEntry
) -> MyPVDevice:
    """Create the correct device object for a config entry."""
    advanced = entry.options.get(CONF_ADVANCED, False)
    session = async_get_clientsession(hass)

    if entry.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_METER:
        return MyPVMeterDevice(
            entry.data[CONF_HOST], advanced=advanced, session=session
        )

    return MyPVLocalDevice(
        entry.data[CONF_HOST],
        entry.data.get(CONF_PASSWORD),
        advanced=advanced,
        session=session,
    )


async def async_setup_entry(hass: HomeAssistant, entry: MyPVConfigEntry) -> None:
    """Set up my-PV from a config entry."""
    device = create_device(hass, entry)

    try:
        if not await device.connect():
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
            )
    except MyPVAuthenticationError as exc:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="auth_error",
        ) from exc
    except MyPVDeviceNotSupportedError as exc:
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="unsupported_device",
        ) from exc

    coordinator = MyPVCoordinator(hass, entry, device)

    try:
        await coordinator.async_config_entry_first_refresh()
    except (ConfigEntryNotReady, ConfigEntryAuthFailed):
        await coordinator.async_disconnect()
        raise

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: MyPVConfigEntry
) -> None:
    """Reload the entry when the options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: MyPVConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_disconnect()
    return unloaded
