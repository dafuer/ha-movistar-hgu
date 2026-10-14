"""Per-client presence from the router's host table (opt-in, disabled by default)."""

from __future__ import annotations

from homeassistant.components.device_tracker import ScannerEntity, SourceType
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import HguConfigEntry, HguSlowCoordinator
from .hgu.models import Host


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HguConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.slow
    tracked: set[str] = set()

    @callback
    def _add_new() -> None:
        new = [h for h in coordinator.data.hosts if h.mac not in tracked]
        if new:
            tracked.update(h.mac for h in new)
            async_add_entities(HguClientTracker(coordinator, h) for h in new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class HguClientTracker(CoordinatorEntity[HguSlowCoordinator], ScannerEntity):
    """A LAN client the router has seen. Connected = listed as active."""

    _attr_entity_registry_enabled_default = False
    _attr_source_type = SourceType.ROUTER

    def __init__(self, coordinator: HguSlowCoordinator, host: Host) -> None:
        super().__init__(coordinator)
        self._mac = host.mac
        self._host = host
        self._attr_unique_id = f"{host.mac}_tracker"

    @callback
    def _handle_coordinator_update(self) -> None:
        for host in self.coordinator.data.hosts:
            if host.mac == self._mac:
                self._host = host
                break
        else:
            self._host = Host(self._mac, None, self._host.hostname, False, self._host.wired, None)
        super()._handle_coordinator_update()

    @property
    def name(self) -> str:
        return self._host.hostname or self._mac

    @property
    def is_connected(self) -> bool:
        return self._host.active

    @property
    def mac_address(self) -> str:
        return self._mac

    @property
    def ip_address(self) -> str | None:
        return self._host.ip

    @property
    def hostname(self) -> str | None:
        return self._host.hostname
