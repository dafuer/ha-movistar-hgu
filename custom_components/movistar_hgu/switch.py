"""Guest Wi-Fi switch.

``EntityCategory.CONFIG`` keeps it out of Assist's default exposure. Turning it
on or off re-submits the guest network's current name, security and key with
only the enabled flag changed (see ``HguClient.async_set_guest_wifi``).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import HguConfigEntry
from .entity import HguEntity
from .hgu.errors import HguError


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HguConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([HguGuestWifiSwitch(entry)])


class HguGuestWifiSwitch(HguEntity, SwitchEntity):
    _attr_translation_key = "guest_wifi"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: HguConfigEntry) -> None:
        super().__init__(entry.runtime_data.config, entry, "guest_wifi")
        self._client = entry.runtime_data.client

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.guest.enabled

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        guest = self.coordinator.data.guest
        return {"ssid": guest.ssid, "isolated": guest.isolated}

    async def _set(self, enabled: bool) -> None:
        try:
            await self._client.async_set_guest_wifi(enabled)
        except HguError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="action_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
