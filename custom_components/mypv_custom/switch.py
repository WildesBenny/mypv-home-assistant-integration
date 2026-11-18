"""Switch platform for the my-PV integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import MyPVConfigEntry
from .entity import MyPVSetupEntity, description_name_kwargs

PARALLEL_UPDATES = 0

# Primary controls that should not be tucked away in the configuration section.
PRIMARY_KEYS = {"devmode", "bstmode"}


def _entity_category(key: str, config: dict[str, Any]) -> EntityCategory | None:
    """Return the entity category for a setup switch."""
    if config.get("advanced"):
        return EntityCategory.DIAGNOSTIC
    if key in PRIMARY_KEYS:
        return None
    return EntityCategory.CONFIG


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: MyPVConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the my-PV switches."""
    coordinator = config_entry.runtime_data

    entities = [
        MyPVSwitch(
            coordinator,
            SwitchEntityDescription(
                key=key,
                **description_name_kwargs(key, config),
                device_class=SwitchDeviceClass.SWITCH,
                entity_category=_entity_category(key, config),
            ),
        )
        for key, config in coordinator.device.get_setup_configurations().items()
        if config.get("type") == "boolean"
    ]

    async_add_entities(entities)


class MyPVSwitch(MyPVSetupEntity, SwitchEntity):
    """A my-PV switch."""

    @property
    def is_on(self) -> bool | None:
        """Return True when the switch is on."""
        value = self.coordinator.device.get_setup_value(self.entity_description.key)
        return bool(value) if value is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        if not await self.coordinator.set_setup_value(
            self.entity_description.key, True
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="unknown_error"
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        if not await self.coordinator.set_setup_value(
            self.entity_description.key, False
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="unknown_error"
            )
