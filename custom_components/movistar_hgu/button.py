"""Buttons: reboot and the IoT pairing window.

All of them are ``EntityCategory.CONFIG``, so Home Assistant never exposes
them to Assist by default: a misheard sentence cannot reboot the router.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, IOT_INSTALL_SECONDS
from .coordinator import HguConfigEntry, HguRuntime
from .entity import HguEntity
from .hgu.errors import HguError


@dataclass(frozen=True, kw_only=True)
class HguButtonDescription(ButtonEntityDescription):
    press_fn: Callable[[HguRuntime], Awaitable[None]]
    refresh_slow: bool = False


async def _reboot(runtime: HguRuntime) -> None:
    await runtime.client.async_reboot()


async def _iot_start(runtime: HguRuntime) -> None:
    await runtime.client.async_start_iot_install(IOT_INSTALL_SECONDS)


async def _iot_cancel(runtime: HguRuntime) -> None:
    await runtime.client.async_cancel_iot_install()


BUTTONS = (
    HguButtonDescription(
        key="reboot",
        translation_key="reboot",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.CONFIG,
        press_fn=_reboot,
    ),
    HguButtonDescription(
        key="iot_install_start",
        translation_key="iot_install_start",
        entity_category=EntityCategory.CONFIG,
        press_fn=_iot_start,
        refresh_slow=True,
    ),
    HguButtonDescription(
        key="iot_install_cancel",
        translation_key="iot_install_cancel",
        entity_category=EntityCategory.CONFIG,
        press_fn=_iot_cancel,
        refresh_slow=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HguConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(HguButton(entry, d) for d in BUTTONS)


class HguButton(HguEntity, ButtonEntity):
    entity_description: HguButtonDescription

    def __init__(self, entry: HguConfigEntry, description: HguButtonDescription) -> None:
        super().__init__(entry.runtime_data.slow, entry, description.key)
        self.entity_description = description
        self._runtime = entry.runtime_data

    async def async_press(self) -> None:
        try:
            await self.entity_description.press_fn(self._runtime)
        except HguError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="action_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        if self.entity_description.refresh_slow:
            await self._runtime.slow.async_request_refresh()
