"""Binary sensor platform for the my-PV integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MyPVConfigEntry
from .entity import MyPVDataEntity, description_name_kwargs

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: MyPVConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the my-PV binary sensors."""
    coordinator = config_entry.runtime_data

    entities = [
        MyPVBinarySensor(
            coordinator,
            BinarySensorEntityDescription(
                key=key,
                **description_name_kwargs(key, config),
                entity_category=(
                    EntityCategory.DIAGNOSTIC if config.get("advanced") else None
                ),
            ),
        )
        for key, config in coordinator.device.get_data_configurations().items()
        if config.get("type") == "boolean"
    ]

    async_add_entities(entities)


class MyPVBinarySensor(MyPVDataEntity, BinarySensorEntity):
    """A my-PV binary sensor."""

    @property
    def is_on(self) -> bool | None:
        """Return True when the binary sensor is on."""
        value = self.coordinator.device.get_data_value(self.entity_description.key)
        return None if value is None else bool(value)
