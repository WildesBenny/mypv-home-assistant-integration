"""Water heater platform for the my-PV integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.water_heater import (
    STATE_ELECTRIC,
    WaterHeaterEntity,
    WaterHeaterEntityDescription,
    WaterHeaterEntityFeature,
)
from homeassistant.const import ATTR_TEMPERATURE, STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import MyPVDeviceMainMode
from .const import DOMAIN
from .coordinator import MyPVConfigEntry, MyPVCoordinator
from .entity import MyPVBaseEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: MyPVConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the my-PV water heater entity."""
    coordinator = config_entry.runtime_data

    if (
        coordinator.device.primary_mode == MyPVDeviceMainMode.HOT_WATER
        and coordinator.device.current_temperature is not None
        and (configuration := coordinator.device.get_setup_configuration("ww1target"))
    ):
        async_add_entities(
            [
                MyPVWaterHeater(
                    coordinator,
                    WaterHeaterEntityDescription(key="ww1target"),
                    configuration=configuration,
                )
            ]
        )


class MyPVWaterHeater(MyPVBaseEntity, WaterHeaterEntity):
    """A my-PV water heater entity."""

    _attr_name = None
    _attr_operation_list = [STATE_OFF, STATE_ELECTRIC]
    _attr_supported_features = (
        WaterHeaterEntityFeature.ON_OFF
        | WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
    )

    def __init__(
        self,
        coordinator: MyPVCoordinator,
        entity_description: WaterHeaterEntityDescription,
        configuration: dict[str, Any],
    ) -> None:
        """Initialize the water heater entity."""
        super().__init__(coordinator, entity_description)

        self._attr_target_temperature_step = configuration.get("step", 0.1)
        self._attr_temperature_unit = configuration.get("unit")
        self._attr_native_temperature_unit = configuration.get("unit")
        self._attr_min_temp = configuration.get("min")
        self._attr_max_temp = configuration.get("max")

    @property
    def current_operation(self) -> str | None:
        """Return the current operation."""
        is_on = self.coordinator.device.is_on
        if is_on is None:
            return None
        return STATE_ELECTRIC if is_on else STATE_OFF

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self.coordinator.device.current_temperature

    @property
    def native_current_temperature(self) -> float | None:
        """Return the current temperature (legacy API)."""
        return self.coordinator.device.current_temperature

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        return self.coordinator.device.target_temperature

    @property
    def native_target_temperature(self) -> float | None:
        """Return the target temperature (legacy API)."""
        return self.coordinator.device.target_temperature

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new target temperature."""
        if not await self.coordinator.set_target_temperature(
            float(kwargs[ATTR_TEMPERATURE])
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="unknown_error"
            )

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set a new operation mode."""
        if operation_mode == STATE_OFF:
            await self.async_turn_off()
        else:
            await self.async_turn_on()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the water heater on."""
        if not await self.coordinator.turn_on():
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="unknown_error"
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the water heater off."""
        if not await self.coordinator.turn_off():
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="unknown_error"
            )
