"""Update platform for the my-PV integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityDescription,
    UpdateEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import MyPVConfigEntry
from .entity import MyPVBaseEntity

PARALLEL_UPDATES = 0

FIRMWARE_UPDATE_DESCRIPTION = UpdateEntityDescription(
    key="firmware_update",
    translation_key="firmware_update",
    device_class=UpdateDeviceClass.FIRMWARE,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: MyPVConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the my-PV firmware update entity."""
    coordinator = config_entry.runtime_data

    if (
        coordinator.device.firmware_version
        and coordinator.device.latest_firmware_version
    ):
        async_add_entities(
            [MyPVFirmwareUpdate(coordinator, FIRMWARE_UPDATE_DESCRIPTION)]
        )


class MyPVFirmwareUpdate(MyPVBaseEntity, UpdateEntity):
    """A my-PV firmware update entity."""

    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
    )

    @property
    def installed_version(self) -> str | None:
        """Return the installed version."""
        return self.coordinator.device.firmware_version

    @property
    def latest_version(self) -> str | None:
        """Return the latest available version."""
        return self.coordinator.device.latest_firmware_version

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install an update."""
        self._attr_in_progress = True
        self._attr_update_percentage = 0
        self.async_write_ha_state()

        if not await self.coordinator.update_firmware():
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="unknown_error"
            )

        self._attr_in_progress = False
        self._attr_update_percentage = None
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """When the entity is added to Home Assistant."""
        await super().async_added_to_hass()
        self._update_progress()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_progress()
        super()._handle_coordinator_update()

    @callback
    def _update_progress(self) -> None:
        """Update the firmware update progress from the device."""
        progress = self.coordinator.device.firmware_update_progress
        if progress is not None:
            self._attr_in_progress = True
            self._attr_update_percentage = progress
        else:
            self._attr_in_progress = False
            self._attr_update_percentage = None
