"""Base entities and helpers for the my-PV integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import MyPVCoordinator

# Map the device unit to a Home Assistant sensor device class.
UNIT_DEVICE_CLASS: dict[str, SensorDeviceClass | None] = {
    "°C": SensorDeviceClass.TEMPERATURE,
    "W": SensorDeviceClass.POWER,
    "kW": SensorDeviceClass.POWER,
    "V": SensorDeviceClass.VOLTAGE,
    "A": SensorDeviceClass.CURRENT,
    "Hz": SensorDeviceClass.FREQUENCY,
    "dBm": SensorDeviceClass.SIGNAL_STRENGTH,
    "kWh": SensorDeviceClass.ENERGY,
    "Wh": SensorDeviceClass.ENERGY,
    "h": SensorDeviceClass.DURATION,
}

# Units that represent a cumulative value.
CUMULATIVE_UNITS = {"kWh", "Wh", "h"}


def unit_to_device_class(unit: str | None) -> SensorDeviceClass | None:
    """Return the sensor device class for a device unit."""
    if unit is None:
        return None
    return UNIT_DEVICE_CLASS.get(unit)


def description_name_kwargs(key: str, config: dict[str, Any]) -> dict[str, Any]:
    """Return the name kwargs for an entity description.

    Translated fields use a translation key, while auto-generated fields for
    unknown device values use the humanized name directly.
    """
    if config.get("synthetic"):
        return {"name": config.get("name", key)}
    return {"translation_key": key}


class MyPVBaseEntity(CoordinatorEntity[MyPVCoordinator]):
    """The my-PV base entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MyPVCoordinator,
        entity_description: EntityDescription,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)

        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = (
            f"{coordinator.device.serial_number}-{entity_description.key}"
        )
        self.entity_description = entity_description

    @property
    def available(self) -> bool:
        """Return True when the entity is available."""
        return super().available and self.coordinator.device.connected


class MyPVDataEntity(MyPVBaseEntity):
    """A my-PV entity backed by a data value."""

    @property
    def available(self) -> bool:
        """Return True when the data value is present."""
        if not super().available:
            return False
        try:
            return (
                self.coordinator.device.get_data_value(self.entity_description.key)
                is not None
            )
        except Exception:  # noqa: BLE001 - device may be mid-reconnect
            return False


class MyPVSetupEntity(MyPVBaseEntity):
    """A my-PV entity backed by a setup value."""

    @property
    def available(self) -> bool:
        """Return True when the setup value is present."""
        if not super().available:
            return False
        try:
            return (
                self.coordinator.device.get_setup_value(self.entity_description.key)
                is not None
            )
        except Exception:  # noqa: BLE001 - device may be mid-reconnect
            return False
