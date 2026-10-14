"""Binary sensors for the Movistar HGU integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ConfigData, FastData, HguConfigEntry
from .entity import HguEntity
from .hgu.models import WanRole


@dataclass(frozen=True, kw_only=True)
class FastBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[FastData], bool | None]


@dataclass(frozen=True, kw_only=True)
class ConfigBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[ConfigData], bool | None]


def _wan(role: WanRole) -> Callable[[FastData], bool | None]:
    return lambda d: d.wans[role].connected if role in d.wans else False


WAN_SENSORS = tuple(
    FastBinaryDescription(
        key=f"wan_{role}",
        translation_key=f"wan_{role}",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_registry_enabled_default=role is not WanRole.IPTV,
        value_fn=_wan(role),
    )
    for role in (WanRole.INTERNET, WanRole.VOICE, WanRole.IPTV)
)

CONFIG_SENSORS = (
    *(
        ConfigBinaryDescription(
            key=f"wifi_{band}",
            translation_key=f"wifi_{band}",
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda d, i=index: d.radios[i].up if i in d.radios else None,
        )
        for index, band in ((0, "24"), (1, "5"))
    ),
    ConfigBinaryDescription(
        key="upnp",
        translation_key="upnp",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.upnp,
    ),
    ConfigBinaryDescription(
        key="remote_syslog",
        translation_key="remote_syslog",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.syslog.enabled and d.syslog.mode in (1, 2),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HguConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        HguFastBinary(runtime.fast, entry, d) for d in WAN_SENSORS
    ]
    entities += [
        HguPortBinary(runtime.fast, entry, name) for name in sorted(runtime.fast.data.ethernet)
    ]
    entities += [HguConfigBinary(runtime.config, entry, d) for d in CONFIG_SENSORS]
    async_add_entities(entities)


class HguFastBinary(HguEntity, BinarySensorEntity):
    entity_description: FastBinaryDescription

    def __init__(self, coordinator, entry: HguConfigEntry, description) -> None:  # type: ignore[no-untyped-def]
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data)


class HguPortBinary(HguEntity, BinarySensorEntity):
    """Link state of one Ethernet port (``eth0.N`` as the router names it)."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "ethernet_port"

    def __init__(self, coordinator, entry: HguConfigEntry, port: str) -> None:  # type: ignore[no-untyped-def]
        super().__init__(coordinator, entry, f"port_{port}")
        self._port = port
        self._attr_translation_placeholders = {"port": port}

    @property
    def is_on(self) -> bool | None:
        counters = self.coordinator.data.ethernet.get(self._port)
        return counters.up if counters else None


class HguConfigBinary(HguEntity, BinarySensorEntity):
    entity_description: ConfigBinaryDescription

    def __init__(self, coordinator, entry: HguConfigEntry, description) -> None:  # type: ignore[no-untyped-def]
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data)
