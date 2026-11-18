"""Select platform for the my-PV integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import MyPVConfigEntry
from .entity import MyPVSetupEntity, description_name_kwargs

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: MyPVConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the my-PV selects."""
    coordinator = config_entry.runtime_data

    entities = [
        MyPVSelect(coordinator, _build_description(key, config))
        for key, config in coordinator.device.get_setup_configurations().items()
        if config.get("type") == "enumeration" and config.get("options")
    ]

    async_add_entities(entities)


def _build_description(
    key: str, config: dict[str, Any]
) -> SelectEntityDescription:
    """Build a select description from a device setup configuration."""
    return SelectEntityDescription(
        key=key,
        **description_name_kwargs(key, config),
        options=list((config.get("options") or {}).keys()),
        entity_category=(
            EntityCategory.DIAGNOSTIC if config.get("advanced") else EntityCategory.CONFIG
        ),
    )


class MyPVSelect(MyPVSetupEntity, SelectEntity):
    """A my-PV select."""

    @property
    def current_option(self) -> str | None:
        """Return the current option."""
        value = self.coordinator.device.get_setup_value(self.entity_description.key)
        return str(value) if value is not None else None

    async def async_select_option(self, option: str) -> None:
        """Select an option."""
        if not await self.coordinator.set_setup_value(
            self.entity_description.key, option
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="unknown_error"
            )
