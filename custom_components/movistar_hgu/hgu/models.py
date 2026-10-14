"""Typed snapshots of what the router reports.

Models deliberately have no fields for secrets (Wi-Fi keys, PPPoE or SIP
credentials, serial-number passwords): parsers drop them on the floor, so they
cannot leak into Home Assistant state, attributes, logs or diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class WanRole(StrEnum):
    """What a WAN VLAN carries on Movistar FTTH."""

    INTERNET = "internet"
    VOICE = "voice"
    IPTV = "iptv"
    OTHER = "other"


# Movistar FTTH VLAN plan: 6 internet (PPPoE), 3 VoIP, 2 IPTV.
VLAN_ROLES = {6: WanRole.INTERNET, 3: WanRole.VOICE, 2: WanRole.IPTV}


@dataclass(frozen=True, slots=True)
class SystemInfo:
    model: str
    manufacturer: str
    hardware_version: str
    firmware: str
    firmware_backup: str
    uptime_s: int
    cpu_pct: int
    memory_pct: int
    load: tuple[float, float, float]
    total_ram_kb: int
    free_ram_kb: int
    onu_state: int


@dataclass(frozen=True, slots=True)
class FiberInfo:
    rx_power_dbm: float
    tx_power_dbm: float
    temperature_c: float
    voltage_v: float
    bias_current_ma: float
    onu_state: int
    pon_uptime_s: int
    rx_power_low_dbm: float | None
    rx_power_high_dbm: float | None


@dataclass(frozen=True, slots=True)
class WanInterface:
    name: str
    vlan: int
    role: WanRole
    connected: bool
    ipv4: str | None
    gateway: str | None


@dataclass(frozen=True, slots=True)
class InterfaceCounters:
    name: str
    up: bool
    rx_bytes: int
    tx_bytes: int
    rx_packets: int
    tx_packets: int
    rx_errors: int
    tx_errors: int
    rx_drops: int
    tx_drops: int


@dataclass(frozen=True, slots=True)
class Statistics:
    ethernet: list[InterfaceCounters] = field(default_factory=list)
    ip_interfaces: list[InterfaceCounters] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Host:
    mac: str
    ip: str | None
    hostname: str | None
    active: bool
    wired: bool
    lease_remaining_s: int | None


@dataclass(frozen=True, slots=True)
class WifiRadio:
    index: int
    enabled: bool
    up: bool
    channel: int
    auto_channel: bool


@dataclass(frozen=True, slots=True)
class AccessPoint:
    index: int
    radio: int
    ssid: str
    enabled: bool
    up: bool
    hidden: bool
    isolated: bool


@dataclass(frozen=True, slots=True)
class PortMapping:
    description: str
    enabled: bool
    internal_ip: str
    external_port_min: int
    external_port_max: int
    protocol: int


@dataclass(frozen=True, slots=True)
class SyslogConfig:
    enabled: bool
    mode: int
    remote_server: str
    remote_port: int
    remote_severity: int
    bind_interface: int


@dataclass(frozen=True, slots=True)
class VoiceLine:
    enabled: bool
    status: str
    call_status: str


@dataclass(frozen=True, slots=True)
class IotInstall:
    active: bool
    remaining_s: int


@dataclass(frozen=True, slots=True)
class CliExtras:
    """Data only the SSH console offers."""

    temperatures_c: dict[str, float] = field(default_factory=dict)
    tr069_status: str | None = None
