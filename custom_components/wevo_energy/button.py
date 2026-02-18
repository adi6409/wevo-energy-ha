from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WevoAuthorizeButton(coordinator, entry)])


class WevoAuthorizeButton(CoordinatorEntity, ButtonEntity):
    _attr_name = "Wevo Authorize Charging"
    _attr_icon = "mdi:ev-plug-type2"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_authorize_charging"

    async def async_press(self) -> None:
        await self.coordinator.authorize()
