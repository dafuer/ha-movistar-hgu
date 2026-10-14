"""Base entity for the Movistar HGU integration."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DOMAIN, MANUFACTURER
from .coordinator import HguConfigEntry


def router_device_info(entry: HguConfigEntry) -> DeviceInfo:
    runtime = entry.runtime_data
    system = runtime.slow.data.system if runtime.slow.data else None
    return DeviceInfo(
        identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        name="Router Movistar",
        manufacturer=MANUFACTURER,
        model=system.model if system else None,
        model_id=system.model if system else None,
        hw_version=system.hardware_version if system else None,
        sw_version=system.firmware if system else None,
        configuration_url=runtime.client.host_url,
    )


class HguEntity[CoordinatorT: DataUpdateCoordinator[Any]](CoordinatorEntity[CoordinatorT]):
    """Entity attached to the router device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CoordinatorT, entry: HguConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{key}"
        self._attr_device_info = router_device_info(entry)
