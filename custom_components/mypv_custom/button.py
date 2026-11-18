"""Button platform for the my-PV integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import MyPVConfigEntry
from .entity import MyPVBaseEntity, description_name_kwargs

PARALLEL_UPDATES = 0

# Commands that are triggered automatically or by the update entity.
_EXCLUDED_COMMANDS = {"check_fwupd", "firmware_download", "firmware_update"}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: MyPVConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the my-PV buttons."""
    coordinator = config_entry.runtime_data

    entities: list[MyPVCommandButton] = []
    for key, config in coordinator.device.get_command_configurations().items():
        if key in _EXCLUDED_COMMANDS:
            continue
        if config.get("type") not in ("any", "fixed"):
            continue
        entities.append(
            MyPVCommandButton(
                coordinator,
                ButtonEntityDescription(
                    key=key,
                    **description_name_kwargs(key, config),
                    device_class=(
                        ButtonDeviceClass.RESTART if key == "reboot_device" else None
                    ),
                    entity_category=(
                        EntityCategory.DIAGNOSTIC
                        if config.get("advanced") or key == "reboot_device"
                        else EntityCategory.CONFIG
                    ),
                ),
            )
        )

    async_add_entities(entities)


class MyPVCommandButton(MyPVBaseEntity, ButtonEntity):
    """A my-PV command button."""

    async def async_press(self, **kwargs: Any) -> None:
        """Handle the button press."""
        if not await self.coordinator.send_command(self.entity_description.key):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="unknown_error"
            )
