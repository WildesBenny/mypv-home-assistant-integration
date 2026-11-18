"""Number platform for the my-PV integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import MyPVConfigEntry, MyPVCoordinator
from .entity import MyPVSetupEntity, description_name_kwargs

PARALLEL_UPDATES = 0

UNIT_NUMBER_DEVICE_CLASS: dict[str, NumberDeviceClass] = {
    "°C": NumberDeviceClass.TEMPERATURE,
    "W": NumberDeviceClass.POWER,
    "V": NumberDeviceClass.VOLTAGE,
    "A": NumberDeviceClass.CURRENT,
    "Hz": NumberDeviceClass.FREQUENCY,
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: MyPVConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the my-PV numbers."""
    coordinator = config_entry.runtime_data

    entities = [
        MyPVNumber(coordinator, _build_description(key, config), config)
        for key, config in coordinator.device.get_setup_configurations().items()
        if config.get("type") == "number"
    ]

    async_add_entities(entities)


def _build_description(
    key: str, config: dict[str, Any]
) -> NumberEntityDescription:
    """Build a number description from a device setup configuration."""
    unit = config.get("unit")
    return NumberEntityDescription(
        key=key,
        **description_name_kwargs(key, config),
        device_class=UNIT_NUMBER_DEVICE_CLASS.get(unit or ""),
        native_unit_of_measurement=unit,
        native_min_value=config.get("min", 0),
        native_max_value=config.get("max"),
        native_step=config.get("step"),
        entity_category=(
            EntityCategory.DIAGNOSTIC if config.get("advanced") else EntityCategory.CONFIG
        ),
    )


class MyPVNumber(MyPVSetupEntity, NumberEntity):
    """A my-PV number."""

    entity_description: NumberEntityDescription

    def __init__(
        self,
        coordinator: MyPVCoordinator,
        entity_description: NumberEntityDescription,
        config: dict[str, Any],
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator, entity_description)
        self._config = config
        if (max_value := config.get("max")) is not None:
            self._attr_native_max_value = max_value

    @property
    def native_value(self) -> float | None:
        """Return the value reported by the number."""
        value = self.coordinator.device.get_setup_value(self.entity_description.key)
        return float(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """Set a new value."""
        if not await self.coordinator.set_setup_value(
            self.entity_description.key, value
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="unknown_error"
            )
