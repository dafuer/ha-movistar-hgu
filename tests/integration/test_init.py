"""Setup, entities, traffic, controls and diagnostics (S4-S9, S11)."""

from __future__ import annotations

import dataclasses
import json
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.movistar_hgu.diagnostics import async_get_config_entry_diagnostics
from custom_components.movistar_hgu.hgu.errors import HguAuthError
from custom_components.movistar_hgu.hgu.models import Statistics

from .conftest import SERIAL


def _entity(hass: HomeAssistant, key: str, domain: str = "sensor") -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, "movistar_hgu", f"{SERIAL}_{key}")
    assert entity_id, key
    return entity_id


async def test_setup_and_core_values(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    assert setup_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(_entity(hass, "voice_ip")).state == "10.22.195.244"
    assert float(hass.states.get(_entity(hass, "optical_rx_power")).state) == pytest.approx(
        -18.33, abs=0.01
    )
    assert hass.states.get(_entity(hass, "onu_state")).state == "o5"
    assert hass.states.get(_entity(hass, "wan_voice", "binary_sensor")).state == "on"
    assert hass.states.get(_entity(hass, "connected_clients")).state == "2"
    assert hass.states.get(_entity(hass, "guest_wifi", "switch")).state == "off"
    assert hass.states.get(_entity(hass, "port_mappings")).state == "1"


async def test_unload_logs_out(
    hass: HomeAssistant, setup_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    assert await hass.config_entries.async_unload(setup_entry.entry_id)
    mock_client.async_logout.assert_awaited()
    assert setup_entry.state is ConfigEntryState.NOT_LOADED


async def test_auth_failure_starts_reauth(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.async_get_summary.side_effect = HguAuthError("bad")
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.state is ConfigEntryState.SETUP_ERROR
    assert any(
        f["context"]["source"] == "reauth" for f in hass.config_entries.flow.async_progress()
    )


async def test_traffic_rate_and_wrap(
    hass: HomeAssistant, setup_entry: MockConfigEntry, mock_client: MagicMock, freezer
) -> None:
    stats: Statistics = mock_client.async_get_statistics.return_value
    ip2 = next(c for c in stats.ip_interfaces if c.name == "ip2")

    def with_ip2(rx: int) -> Statistics:
        new_ip = [
            dataclasses.replace(c, rx_bytes=rx) if c.name == "ip2" else c
            for c in stats.ip_interfaces
        ]
        return dataclasses.replace(stats, ip_interfaces=new_ip)

    # +75 MB in the 30 s tick: 20 Mbit/s.
    mock_client.async_get_statistics.return_value = with_ip2(ip2.rx_bytes + 75_000_000)
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    total = float(hass.states.get(_entity(hass, "internet_download_total")).state)
    assert total == pytest.approx(0.075, abs=0.001)  # GB
    assert float(hass.states.get(_entity(hass, "internet_download_rate")).state) > 0

    # 32-bit wrap: raw goes down without a reboot (Ethernet counters unchanged).
    mock_client.async_get_statistics.return_value = with_ip2(1_000)
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    wrapped = float(hass.states.get(_entity(hass, "internet_download_total")).state)
    expected = 0.075 + (2**32 - (ip2.rx_bytes + 75_000_000) + 1_000) / 1e9
    assert wrapped == pytest.approx(expected, abs=0.001)


async def test_buttons_and_switch(
    hass: HomeAssistant, setup_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: _entity(hass, "reboot", "button")}, blocking=True
    )
    mock_client.async_reboot.assert_awaited_once()
    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: _entity(hass, "iot_install_start", "button")},
        blocking=True,
    )
    mock_client.async_start_iot_install.assert_awaited_once_with(600)
    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: _entity(hass, "guest_wifi", "switch")}, blocking=True
    )
    mock_client.async_set_guest_wifi.assert_awaited_once_with(True)


async def test_controls_not_exposed_to_assist(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    registry = er.async_get(hass)
    for key, domain in (("reboot", "button"), ("guest_wifi", "switch")):
        entry = registry.async_get(_entity(hass, key, domain))
        assert entry.entity_category is not None


async def test_diagnostics_redacted(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    diag = await async_get_config_entry_diagnostics(hass, setup_entry)
    text = json.dumps(diag, default=str)
    for secret in ("router-pass", SERIAL, "10.22.195.244", "02:00:00:00:00", "Archer_C9"):
        assert secret not in text, secret
    assert diag["slow"]["fiber"]["onu_state"] == 5


async def test_button_error_is_reported(
    hass: HomeAssistant, setup_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.movistar_hgu.hgu.errors import HguResponseError

    mock_client.async_reboot = AsyncMock(side_effect=HguResponseError("nope"))
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button", "press", {ATTR_ENTITY_ID: _entity(hass, "reboot", "button")}, blocking=True
        )


async def test_wan_ip_change_event_survives_gaps_and_reloads(
    hass: HomeAssistant, setup_entry: MockConfigEntry, mock_client: MagicMock, freezer
) -> None:
    from homeassistant.core import Event

    from custom_components.movistar_hgu.const import EVENT_WAN_IP_CHANGED
    from custom_components.movistar_hgu.hgu.errors import HguConnectionError
    from custom_components.movistar_hgu.hgu.models import WanRole

    events: list[Event] = []
    hass.bus.async_listen(EVENT_WAN_IP_CHANGED, events.append)
    wans = mock_client.async_get_wan_interfaces.return_value

    def with_voice_ip(ip: str) -> list:
        return [dataclasses.replace(w, ipv4=ip) if w.role is WanRole.VOICE else w for w in wans]

    async def tick() -> None:
        freezer.tick(timedelta(seconds=31))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    # Same IP: nothing. The first sample after setup only records the IP.
    await tick()
    assert events == []

    # A plain change between two polls.
    mock_client.async_get_wan_interfaces.return_value = with_voice_ip("10.22.200.1")
    await tick()
    assert [e.data for e in events] == [
        {
            "entry_id": setup_entry.entry_id,
            "role": "voice",
            "previous": "10.22.195.244",
            "current": "10.22.200.1",
        }
    ]

    # The router goes away (entities unavailable) and comes back with a new IP:
    # the change is still reported against the last IP seen before the gap.
    mock_client.async_get_wan_interfaces.side_effect = HguConnectionError("rebooting")
    await tick()
    mock_client.async_get_wan_interfaces.side_effect = None
    mock_client.async_get_wan_interfaces.return_value = with_voice_ip("10.22.201.2")
    await tick()
    assert events[-1].data["previous"] == "10.22.200.1"
    assert events[-1].data["current"] == "10.22.201.2"

    # The last IP is remembered across a reload (HA restart).
    await tick()  # let the delayed store save run
    freezer.tick(timedelta(seconds=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(setup_entry.entry_id)
    await hass.async_block_till_done()
    assert len(events) == 2
    mock_client.async_get_wan_interfaces.return_value = with_voice_ip("10.22.202.3")
    await tick()
    assert events[-1].data["previous"] == "10.22.201.2"


async def test_unload_logs_out_then_closes_its_own_http_session(
    hass: HomeAssistant, setup_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    session = setup_entry.runtime_data.session
    assert not session.closed
    assert await hass.config_entries.async_unload(setup_entry.entry_id)
    mock_client.async_logout.assert_awaited()
    assert session.closed
