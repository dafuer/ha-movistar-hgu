"""Sensors for the Movistar HGU integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfDataRate,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfInformation,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import (
    ConfigData,
    FastData,
    HguConfigEntry,
    SlowData,
)
from .entity import HguEntity
from .hgu.models import WanRole

ONU_STATES = ["o1", "o2", "o3", "o4", "o5", "o6", "o7"]
TEMPERATURE_SOURCES = {"main_soc": "soc", "wifi": "wifi_24", "wifi_plus": "wifi_5"}

Value = str | int | float | datetime | None


@dataclass(frozen=True, kw_only=True)
class SlowSensorDescription(SensorEntityDescription):
    value_fn: Callable[[SlowData], Value]
    attrs_fn: Callable[[SlowData], dict[str, Any]] | None = None
    available_fn: Callable[[SlowData], bool] = lambda d: True


@dataclass(frozen=True, kw_only=True)
class FastSensorDescription(SensorEntityDescription):
    value_fn: Callable[[FastData], Value]


@dataclass(frozen=True, kw_only=True)
class ConfigSensorDescription(SensorEntityDescription):
    value_fn: Callable[[ConfigData], Value]
    attrs_fn: Callable[[ConfigData], dict[str, Any]] | None = None


def _onu(state: int) -> str | None:
    return f"o{state}" if 1 <= state <= 7 else None


def _clients(data: SlowData, wired: bool | None) -> int:
    return sum(1 for h in data.hosts if h.active and (wired is None or h.wired is wired))


SLOW_SENSORS: tuple[SlowSensorDescription, ...] = (
    SlowSensorDescription(
        key="last_boot",
        translation_key="last_boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.last_boot,
    ),
    SlowSensorDescription(
        key="cpu_usage",
        translation_key="cpu_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.system.cpu_pct,
    ),
    SlowSensorDescription(
        key="memory_usage",
        translation_key="memory_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.system.memory_pct,
    ),
    *(
        SlowSensorDescription(
            key=f"load_{minutes}",
            translation_key=f"load_{minutes}",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            suggested_display_precision=2,
            value_fn=lambda d, i=index: d.system.load[i],
        )
        for index, minutes in enumerate((1, 5, 15))
    ),
    SlowSensorDescription(
        key="optical_rx_power",
        translation_key="optical_rx_power",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.fiber.rx_power_dbm,
        attrs_fn=lambda d: {
            "low_threshold_dbm": d.fiber.rx_power_low_dbm,
            "high_threshold_dbm": d.fiber.rx_power_high_dbm,
        },
    ),
    SlowSensorDescription(
        key="optical_tx_power",
        translation_key="optical_tx_power",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.fiber.tx_power_dbm,
    ),
    SlowSensorDescription(
        key="optical_temperature",
        translation_key="optical_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.fiber.temperature_c,
    ),
    SlowSensorDescription(
        key="optical_voltage",
        translation_key="optical_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=3,
        value_fn=lambda d: d.fiber.voltage_v,
    ),
    SlowSensorDescription(
        key="optical_bias_current",
        translation_key="optical_bias_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=2,
        value_fn=lambda d: d.fiber.bias_current_ma,
    ),
    SlowSensorDescription(
        key="onu_state",
        translation_key="onu_state",
        device_class=SensorDeviceClass.ENUM,
        options=ONU_STATES,
        value_fn=lambda d: _onu(d.fiber.onu_state),
    ),
    SlowSensorDescription(
        key="pon_up_since",
        translation_key="pon_up_since",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.pon_up_since,
    ),
    SlowSensorDescription(
        key="connected_clients",
        translation_key="connected_clients",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _clients(d, None),
        attrs_fn=lambda d: {
            "clients": [
                {
                    "name": h.hostname,
                    "ip": h.ip,
                    "mac": h.mac,
                    "connection": "ethernet" if h.wired else "wifi",
                }
                for h in sorted(d.hosts, key=lambda h: (h.hostname or h.mac).casefold())
                if h.active
            ]
        },
    ),
    SlowSensorDescription(
        key="wired_clients",
        translation_key="wired_clients",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _clients(d, True),
    ),
    SlowSensorDescription(
        key="wifi_clients",
        translation_key="wifi_clients",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _clients(d, False),
    ),
    SlowSensorDescription(
        key="iot_install_remaining",
        translation_key="iot_install_remaining",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.iot.remaining_s,
    ),
    SlowSensorDescription(
        key="router_voice_line",
        translation_key="router_voice_line",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.voice_line.status or None,
    ),
)

CLI_SENSORS: tuple[SlowSensorDescription, ...] = (
    *(
        SlowSensorDescription(
            key=f"temperature_{suffix}",
            translation_key=f"temperature_{suffix}",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            suggested_display_precision=1,
            value_fn=lambda d, s=source: d.cli.temperatures_c.get(s) if d.cli else None,
            available_fn=lambda d: d.cli is not None,
        )
        for source, suffix in TEMPERATURE_SOURCES.items()
    ),
    SlowSensorDescription(
        key="tr069_status",
        translation_key="tr069_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.cli.tr069_status if d.cli else None,
        available_fn=lambda d: d.cli is not None,
    ),
)


def _wan_ip(role: WanRole) -> Callable[[FastData], Value]:
    return lambda d: d.wans[role].ipv4 if role in d.wans else None


FAST_SENSORS: list[FastSensorDescription] = [
    FastSensorDescription(
        key="public_ip",
        translation_key="public_ip",
        value_fn=_wan_ip(WanRole.INTERNET),
    ),
    FastSensorDescription(
        key="voice_ip",
        translation_key="voice_ip",
        value_fn=_wan_ip(WanRole.VOICE),
    ),
    FastSensorDescription(
        key="iptv_ip",
        translation_key="iptv_ip",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_wan_ip(WanRole.IPTV),
    ),
]
for _role in (WanRole.INTERNET, WanRole.VOICE, WanRole.IPTV):
    _main = _role is WanRole.INTERNET
    FAST_SENSORS += [
        FastSensorDescription(
            key=f"{_role}_{direction}_total",
            translation_key=f"{_role}_{direction}_total",
            device_class=SensorDeviceClass.DATA_SIZE,
            native_unit_of_measurement=UnitOfInformation.BYTES,
            suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
            suggested_display_precision=2,
            state_class=SensorStateClass.TOTAL_INCREASING,
            entity_registry_enabled_default=_main,
            value_fn=lambda d, r=_role, a=attr: getattr(d.traffic[r], a),
        )
        for direction, attr in (("download", "rx_total"), ("upload", "tx_total"))
    ]
    FAST_SENSORS += [
        FastSensorDescription(
            key=f"{_role}_{direction}_rate",
            translation_key=f"{_role}_{direction}_rate",
            device_class=SensorDeviceClass.DATA_RATE,
            native_unit_of_measurement=UnitOfDataRate.BITS_PER_SECOND,
            suggested_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
            suggested_display_precision=2,
            state_class=SensorStateClass.MEASUREMENT,
            entity_registry_enabled_default=_main,
            value_fn=lambda d, r=_role, a=attr: getattr(d.traffic[r], a),
        )
        for direction, attr in (("download", "rx_bps"), ("upload", "tx_bps"))
    ]

CONFIG_SENSORS: tuple[ConfigSensorDescription, ...] = (
    *(
        ConfigSensorDescription(
            key=f"wifi_{band}_channel",
            translation_key=f"wifi_{band}_channel",
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda d, i=index: d.radios[i].channel if i in d.radios else None,
        )
        for index, band in ((0, "24"), (1, "5"))
    ),
    ConfigSensorDescription(
        key="port_mappings",
        translation_key="port_mappings",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: sum(1 for m in d.port_mappings if m.enabled),
        attrs_fn=lambda d: {
            "mappings": [
                {
                    "description": m.description,
                    "internal_ip": m.internal_ip,
                    "external_ports": f"{m.external_port_min}-{m.external_port_max}",
                    "enabled": m.enabled,
                }
                for m in d.port_mappings
            ]
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HguConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    entities: list[SensorEntity] = [HguSlowSensor(runtime.slow, entry, d) for d in SLOW_SENSORS]
    if runtime.cli is not None:
        entities += [HguSlowSensor(runtime.slow, entry, d) for d in CLI_SENSORS]
    entities += [HguFastSensor(runtime.fast, entry, d) for d in FAST_SENSORS]
    entities += [HguConfigSensor(runtime.config, entry, d) for d in CONFIG_SENSORS]
    async_add_entities(entities)


class HguSlowSensor(HguEntity, SensorEntity):
    entity_description: SlowSensorDescription
    # The client list changes often and is only useful live: keep it out of history.
    _unrecorded_attributes = frozenset({"clients"})

    def __init__(self, coordinator, entry: HguConfigEntry, description) -> None:  # type: ignore[no-untyped-def]
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return super().available and self.entity_description.available_fn(self.coordinator.data)

    @property
    def native_value(self) -> Value:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attrs_fn
        return fn(self.coordinator.data) if fn else None


class HguFastSensor(HguEntity, SensorEntity):
    entity_description: FastSensorDescription

    def __init__(self, coordinator, entry: HguConfigEntry, description) -> None:  # type: ignore[no-untyped-def]
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Value:
        return self.entity_description.value_fn(self.coordinator.data)


class HguConfigSensor(HguEntity, SensorEntity):
    entity_description: ConfigSensorDescription

    def __init__(self, coordinator, entry: HguConfigEntry, description) -> None:  # type: ignore[no-untyped-def]
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Value:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attrs_fn
        return fn(self.coordinator.data) if fn else None
