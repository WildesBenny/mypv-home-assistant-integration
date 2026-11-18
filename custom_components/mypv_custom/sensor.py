"""Sensor platform for the my-PV integration."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import MyPVConfigEntry
from .entity import (
    CUMULATIVE_UNITS,
    MyPVDataEntity,
    description_name_kwargs,
    unit_to_device_class,
)

PARALLEL_UPDATES = 0

_DISPLAY_PRECISION: dict[str, int] = {
    "°C": 1,
    "V": 1,
    "A": 1,
    "Hz": 2,
    "%": 1,
    "W": 0,
}


def _build_description(
    key: str, config: dict[str, Any]
) -> SensorEntityDescription:
    """Build a sensor description from a device data configuration."""
    value_type = config.get("type")
    unit = config.get("unit")

    device_class = unit_to_device_class(unit)
    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT
    options: list[str] | None = None

    if value_type == "enumeration":
        device_class = SensorDeviceClass.ENUM
        options = list((config.get("options") or {}).keys())
        state_class = None
        unit = None
    elif value_type == "string":
        device_class = None
        state_class = None
    elif unit in CUMULATIVE_UNITS:
        state_class = SensorStateClass.TOTAL_INCREASING

    return SensorEntityDescription(
        key=key,
        **description_name_kwargs(key, config),
        device_class=device_class,
        native_unit_of_measurement=unit,
        state_class=state_class,
        options=options,
        suggested_display_precision=_DISPLAY_PRECISION.get(unit or ""),
        entity_category=(
            EntityCategory.DIAGNOSTIC if config.get("advanced") else None
        ),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: MyPVConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the my-PV sensors."""
    coordinator = config_entry.runtime_data

    entities: list[MyPVSensor] = []
    for key, config in coordinator.device.get_data_configurations().items():
        if config.get("type") == "boolean":
            continue
        if config.get("type") == "enumeration" and not config.get("options"):
            continue
        entities.append(MyPVSensor(coordinator, _build_description(key, config)))

    async_add_entities(entities)


class MyPVSensor(MyPVDataEntity, SensorEntity):
    """A my-PV sensor."""

    @property
    def native_value(self) -> StateType | date | datetime | Decimal:
        """Return the value reported by the sensor."""
        return self.coordinator.device.get_data_value(self.entity_description.key)
