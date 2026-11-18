"""Climate platform for the my-PV integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ClimateEntity,
    ClimateEntityDescription,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE
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
    """Set up the my-PV climate entity."""
    coordinator = config_entry.runtime_data

    if (
        coordinator.device.primary_mode == MyPVDeviceMainMode.SPACE_HEATING
        and coordinator.device.current_temperature is not None
        and (configuration := coordinator.device.get_setup_configuration("rh1_target"))
    ):
        async_add_entities(
            [
                MyPVClimate(
                    coordinator,
                    ClimateEntityDescription(key="rh1_target"),
                    configuration=configuration,
                )
            ]
        )


class MyPVClimate(MyPVBaseEntity, ClimateEntity):
    """A my-PV climate entity."""

    _attr_name = None
    _attr_supported_features = (
        ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TARGET_TEMPERATURE
    )
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]

    def __init__(
        self,
        coordinator: MyPVCoordinator,
        entity_description: ClimateEntityDescription,
        configuration: dict[str, Any],
    ) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator, entity_description)

        self._attr_target_temperature_step = configuration.get("step", 0.1)
        self._attr_temperature_unit = configuration.get("unit")
        self._attr_native_temperature_unit = configuration.get("unit")
        self._attr_min_temp = configuration.get("min")
        self._attr_max_temp = configuration.get("max")

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return the current HVAC mode."""
        is_on = self.coordinator.device.is_on
        if is_on is None:
            return None
        return HVACMode.HEAT if is_on else HVACMode.OFF

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

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode."""
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
        else:
            await self.async_turn_on()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature."""
        if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            await self.async_set_hvac_mode(hvac_mode)

        if not await self.coordinator.set_target_temperature(
            float(kwargs[ATTR_TEMPERATURE])
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="unknown_error"
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the climate entity on."""
        if not await self.coordinator.turn_on():
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="unknown_error"
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the climate entity off."""
        if not await self.coordinator.turn_off():
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="unknown_error"
            )
