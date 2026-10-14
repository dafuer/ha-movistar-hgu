"""Config flow tests (S11)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.movistar_hgu.const import CONF_SSH_ENABLED, CONF_SSH_PORT, DOMAIN
from custom_components.movistar_hgu.hgu.errors import HguAuthError, HguConnectionError

from .conftest import SERIAL

INPUT = {CONF_HOST: "192.168.1.1", CONF_PASSWORD: "router-pass"}


async def test_user_flow_creates_entry(hass: HomeAssistant, mock_client: MagicMock) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Router Movistar RTF8316VW"
    assert result["result"].unique_id == SERIAL
    mock_client.async_logout.assert_awaited()


async def test_user_flow_errors_then_recovers(hass: HomeAssistant, mock_client: MagicMock) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    for exc, error in (
        (HguAuthError("x"), "invalid_auth"),
        (HguConnectionError("x"), "cannot_connect"),
    ):
        mock_client.async_get_summary.side_effect = exc
        result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
        assert result["errors"] == {"base": error}
    mock_client.async_get_summary.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_already_configured(
    hass: HomeAssistant, mock_client: MagicMock, mock_entry: MockConfigEntry
) -> None:
    mock_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    result = await setup_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new-pass"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert setup_entry.data[CONF_PASSWORD] == "new-pass"


async def test_reconfigure_new_host_same_router(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    result = await setup_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.0.1", CONF_PASSWORD: "router-pass"}
    )
    assert result["reason"] == "reconfigure_successful"
    assert setup_entry.data[CONF_HOST] == "192.168.0.1"


async def test_reconfigure_other_router_refused(
    hass: HomeAssistant, setup_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    other = mock_client.async_get_summary.return_value
    mock_client.async_get_summary = AsyncMock(
        return_value=type(other)(
            **{**{f: getattr(other, f) for f in other.__dataclass_fields__}, "serial_number": "X"}
        )
    )
    result = await setup_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.0.1", CONF_PASSWORD: "router-pass"}
    )
    assert result["reason"] == "wrong_router"


async def test_options_enable_ssh(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    result = await hass.config_entries.options.async_init(setup_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SSH_ENABLED: False, CONF_SSH_PORT: 22}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup_entry.options == {CONF_SSH_ENABLED: False, CONF_SSH_PORT: 22}
