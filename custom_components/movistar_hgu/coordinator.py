"""Data update coordinators for the Movistar HGU integration.

Three tiers share one ``HguClient`` (requests are serialized inside it):

* ``fast`` (30 s): WAN interfaces + interface statistics → link state, IPs,
  traffic totals and rates.
* ``slow`` (5 min): system summary, fiber, clients, IoT window, router voice
  line and, if enabled, the SSH console extras.
* ``config`` (1 h): Wi-Fi radios, guest network, port mappings, UPnP, syslog.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_SSH_HOST_KEY,
    CONFIG_INTERVAL,
    DOMAIN,
    FAST_INTERVAL,
    GUEST_ACCESS_POINT,
    MAX_LINK_BPS,
    SLOW_INTERVAL,
)
from .hgu.cli import HguCli, parse_temperatures, parse_tr069
from .hgu.client import HguClient
from .hgu.errors import HguAuthError, HguError
from .hgu.models import (
    AccessPoint,
    CliExtras,
    FiberInfo,
    Host,
    InterfaceCounters,
    IotInstall,
    PortMapping,
    SyslogConfig,
    SystemInfo,
    VoiceLine,
    WanInterface,
    WanRole,
    WifiRadio,
)
from .hgu.traffic import TrafficAccumulator

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
TRAFFIC_ROLES = (WanRole.INTERNET, WanRole.VOICE, WanRole.IPTV)


@dataclass(slots=True)
class TrafficSample:
    rx_total: int = 0
    tx_total: int = 0
    rx_bps: float | None = None
    tx_bps: float | None = None


@dataclass(slots=True)
class FastData:
    wans: dict[WanRole, WanInterface]
    ethernet: dict[str, InterfaceCounters]
    traffic: dict[WanRole, TrafficSample]


@dataclass(slots=True)
class SlowData:
    system: SystemInfo
    fiber: FiberInfo
    hosts: list[Host]
    iot: IotInstall
    voice_line: VoiceLine
    last_boot: datetime
    pon_up_since: datetime
    cli: CliExtras | None = None


@dataclass(slots=True)
class ConfigData:
    radios: dict[int, WifiRadio]
    guest: AccessPoint
    port_mappings: list[PortMapping]
    upnp: bool
    syslog: SyslogConfig


@dataclass
class HguRuntime:
    client: HguClient
    fast: HguFastCoordinator
    slow: HguSlowCoordinator
    config: HguConfigCoordinator
    cli: HguCli | None = None
    extra: dict[str, Any] = field(default_factory=dict)


type HguConfigEntry = ConfigEntry[HguRuntime]


class _Base[T](DataUpdateCoordinator[T]):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: HguConfigEntry,
        client: HguClient,
        name: str,
        interval: timedelta,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {name}",
            update_interval=interval,
        )
        self.client = client

    async def _async_update_data(self) -> T:
        try:
            return await self._fetch()
        except HguAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except HguError as err:
            raise UpdateFailed(str(err)) from err

    async def _fetch(self) -> T:
        raise NotImplementedError


class HguFastCoordinator(_Base[FastData]):
    """WAN state, interface counters and the traffic they imply."""

    def __init__(self, hass: HomeAssistant, entry: HguConfigEntry, client: HguClient) -> None:
        super().__init__(hass, entry, client, "fast", FAST_INTERVAL)
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.traffic"
        )
        self._acc: dict[str, TrafficAccumulator] = {}
        self._last_sample: float | None = None
        self._last_eth_total: int | None = None
        self._totals = {role: TrafficSample() for role in TRAFFIC_ROLES}

    async def async_load_traffic(self) -> None:
        stored = await self._store.async_load() or {}
        for key, state in stored.items():
            self._acc[key] = TrafficAccumulator.from_state(state, max_bps=MAX_LINK_BPS)
        for role in TRAFFIC_ROLES:
            sample = self._totals[role]
            sample.rx_total = self._acc.get(f"{role}_rx", TrafficAccumulator()).total
            sample.tx_total = self._acc.get(f"{role}_tx", TrafficAccumulator()).total

    def _accumulator(self, key: str) -> TrafficAccumulator:
        if key not in self._acc:
            self._acc[key] = TrafficAccumulator(max_bps=MAX_LINK_BPS)
        return self._acc[key]

    async def _fetch(self) -> FastData:
        wans = await self.client.async_get_wan_interfaces()
        stats = await self.client.async_get_statistics()
        now = time.monotonic()
        elapsed = None if self._last_sample is None else now - self._last_sample
        self._last_sample = now

        # The Ethernet counters are 64-bit and never wrap: if their sum drops,
        # the router restarted and the 32-bit WAN counters restarted with it.
        eth_total = sum(c.rx_bytes + c.tx_bytes for c in stats.ethernet)
        rebooted = self._last_eth_total is not None and eth_total < self._last_eth_total
        self._last_eth_total = eth_total

        by_name = {c.name: c for c in stats.ip_interfaces}
        wan_by_role = {w.role: w for w in wans if w.role in TRAFFIC_ROLES}
        for role, wan in wan_by_role.items():
            counters = by_name.get(wan.name)
            if counters is None:
                continue
            sample = self._totals[role]
            # rx on the WAN interface is what the house downloads.
            rx_delta = self._accumulator(f"{role}_rx").update(
                counters.rx_bytes, elapsed_s=elapsed, rebooted=rebooted
            )
            tx_delta = self._accumulator(f"{role}_tx").update(
                counters.tx_bytes, elapsed_s=elapsed, rebooted=rebooted
            )
            sample.rx_total = self._acc[f"{role}_rx"].total
            sample.tx_total = self._acc[f"{role}_tx"].total
            sample.rx_bps = rx_delta * 8 / elapsed if elapsed else None
            sample.tx_bps = tx_delta * 8 / elapsed if elapsed else None

        self._store.async_delay_save(lambda: {k: a.as_state() for k, a in self._acc.items()}, 60)
        return FastData(
            wans=wan_by_role,
            ethernet={c.name: c for c in stats.ethernet},
            traffic=dict(self._totals),
        )


class HguSlowCoordinator(_Base[SlowData]):
    """System, fiber, clients and the optional SSH extras."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: HguConfigEntry,
        client: HguClient,
        cli: HguCli | None,
    ) -> None:
        super().__init__(hass, entry, client, "slow", SLOW_INTERVAL)
        self.cli = cli
        self._last_boot: datetime | None = None
        self._pon_up_since: datetime | None = None

    @staticmethod
    def _stable_since(previous: datetime | None, uptime_s: int) -> datetime:
        """Uptime → a start time that does not jitter between polls."""
        since = dt_util.utcnow().replace(microsecond=0) - timedelta(seconds=uptime_s)
        if previous is not None and abs((since - previous).total_seconds()) < 60:
            return previous
        return since

    async def _fetch(self) -> SlowData:
        system = await self.client.async_get_summary()
        fiber = await self.client.async_get_gpon()
        hosts = await self.client.async_get_hosts()
        iot = await self.client.async_get_iot_install()
        voice = await self.client.async_get_voice_line()
        self._last_boot = self._stable_since(self._last_boot, system.uptime_s)
        self._pon_up_since = self._stable_since(self._pon_up_since, fiber.pon_uptime_s)
        return SlowData(
            system=system,
            fiber=fiber,
            hosts=hosts,
            iot=iot,
            voice_line=voice,
            last_boot=self._last_boot,
            pon_up_since=self._pon_up_since,
            cli=await self._cli_extras(),
        )

    async def _cli_extras(self) -> CliExtras | None:
        """SSH is optional: a failure there must not take the web data down."""
        if self.cli is None:
            return None
        known = self.cli.host_key
        try:
            out = await self.cli.async_run(["show temperature", "show tr_status"])
        except HguError as err:
            _LOGGER.warning("SSH console read failed: %s", err)
            return self.data.cli if self.data else None
        if known is None and self.cli.host_key and self.config_entry is not None:
            # First successful connection: pin the router's host key.
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_SSH_HOST_KEY: self.cli.host_key},
            )
        return CliExtras(
            temperatures_c=parse_temperatures(out["show temperature"]),
            tr069_status=parse_tr069(out["show tr_status"]),
        )


class HguConfigCoordinator(_Base[ConfigData]):
    """Settings-like data that rarely changes."""

    def __init__(self, hass: HomeAssistant, entry: HguConfigEntry, client: HguClient) -> None:
        super().__init__(hass, entry, client, "config", CONFIG_INTERVAL)

    async def _fetch(self) -> ConfigData:
        radios = {i: await self.client.async_get_wifi_radio(i) for i in (0, 1)}
        return ConfigData(
            radios=radios,
            guest=await self.client.async_get_access_point(GUEST_ACCESS_POINT),
            port_mappings=await self.client.async_get_port_mappings(),
            upnp=await self.client.async_get_upnp_enabled(),
            syslog=await self.client.async_get_syslog(),
        )
