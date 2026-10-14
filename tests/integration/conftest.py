"""Fixtures for Home Assistant integration tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.movistar_hgu.const import DOMAIN
from custom_components.movistar_hgu.hgu import parsers
from tests.hgu.conftest import fixture

SERIAL = "ASKY0TEST001"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/ in every test."""


def build_client() -> MagicMock:
    client = MagicMock()
    summary = parsers.parse_summary(fixture("cbGetSummary.xml"))
    summary = type(summary)(
        **{
            **{f: getattr(summary, f) for f in summary.__dataclass_fields__},
            "serial_number": SERIAL,
        }
    )
    client.async_get_summary = AsyncMock(return_value=summary)
    client.async_get_gpon = AsyncMock(return_value=parsers.parse_gpon(fixture("cbGetGPONInfo.xml")))
    client.async_get_wan_interfaces = AsyncMock(
        return_value=parsers.parse_wan_interfaces(fixture("cbGetWanIPIntf.xml"))
    )
    client.async_get_statistics = AsyncMock(
        return_value=parsers.parse_statistics(fixture("cbGetStatistic.xml"))
    )
    client.async_get_hosts = AsyncMock(
        return_value=parsers.parse_hosts(fixture("cbGetLanHostList.xml"))
    )
    client.async_get_iot_install = AsyncMock(
        return_value=parsers.parse_iot_install(fixture("te_wifi.asp"))
    )
    client.async_get_voice_line = AsyncMock(
        return_value=parsers.parse_voice_line(fixture("cbGetVoiceLine.xml"))
    )
    radios = {
        0: parsers.parse_wifi_radio(fixture("cbGetWifi.xml")),
        1: parsers.parse_wifi_radio(fixture("cbGetWifi__dpm_cfg_wifi_0i-1.xml")),
    }
    client.async_get_wifi_radio = AsyncMock(side_effect=lambda i: radios[i])
    client.async_get_access_point = AsyncMock(
        return_value=parsers.parse_access_point(
            fixture("cbGetWifiAccPt__dpm_cfg_wifi_acc_pt_0i-2.xml")
        )
    )
    client.async_get_port_mappings = AsyncMock(
        return_value=parsers.parse_port_mappings(fixture("cbGetNatPortMapping.xml"))
    )
    client.async_get_upnp_enabled = AsyncMock(return_value=False)
    client.async_get_syslog = AsyncMock(
        return_value=parsers.parse_syslog(fixture("cbGetSyslog.xml"))
    )
    client.async_logout = AsyncMock()
    client.async_reboot = AsyncMock()
    client.async_start_iot_install = AsyncMock()
    client.async_cancel_iot_install = AsyncMock()
    client.async_set_guest_wifi = AsyncMock()
    client.host_url = "http://192.168.1.1"
    return client


@pytest.fixture
def mock_client() -> Generator[MagicMock]:
    client = build_client()
    with (
        patch("custom_components.movistar_hgu.HguClient", return_value=client),
        patch("custom_components.movistar_hgu.config_flow.HguClient", return_value=client),
    ):
        yield client


@pytest.fixture
def mock_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Router Movistar RTF8316VW",
        unique_id=SERIAL,
        data={CONF_HOST: "192.168.1.1", CONF_PASSWORD: "router-pass"},
    )


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_client: MagicMock
) -> MockConfigEntry:
    mock_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    return mock_entry
