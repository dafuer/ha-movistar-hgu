"""The Movistar HGU (Askey RTF8316VW) integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_SSH_ENABLED,
    CONF_SSH_HOST_KEY,
    CONF_SSH_PORT,
    DEFAULT_SSH_PORT,
)
from .coordinator import (
    HguConfigCoordinator,
    HguConfigEntry,
    HguFastCoordinator,
    HguRuntime,
    HguSlowCoordinator,
)
from .hgu.cli import HguCli
from .hgu.client import HguClient, new_session

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: HguConfigEntry) -> bool:
    """Set up the router from a config entry."""
    session = new_session()
    client = HguClient(session, entry.data[CONF_HOST], entry.data[CONF_PASSWORD])

    async def _close() -> None:
        # Router-side session first, then the HTTP session it travels on.
        await client.async_logout()
        await session.close()

    cli = None
    if entry.options.get(CONF_SSH_ENABLED, False):
        cli = HguCli(
            entry.data[CONF_HOST],
            entry.data[CONF_PASSWORD],
            port=entry.options.get(CONF_SSH_PORT, DEFAULT_SSH_PORT),
            host_key=entry.data.get(CONF_SSH_HOST_KEY),
        )

    fast = HguFastCoordinator(hass, entry, client)
    slow = HguSlowCoordinator(hass, entry, client, cli)
    config = HguConfigCoordinator(hass, entry, client)

    try:
        await fast.async_load_traffic()
        await slow.async_config_entry_first_refresh()
        await fast.async_config_entry_first_refresh()
        await config.async_config_entry_first_refresh()
    except BaseException:
        await _close()
        raise
    entry.async_on_unload(_close)

    entry.runtime_data = HguRuntime(
        client=client,
        fast=fast,
        slow=slow,
        config=config,
        cli=cli,
        session=session,
        extra={"options": dict(entry.options)},
    )
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: HguConfigEntry) -> None:
    # Data updates (e.g. pinning the SSH host key) must not trigger a reload.
    if dict(entry.options) != entry.runtime_data.extra.get("options"):
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HguConfigEntry) -> bool:
    """Unload a config entry; the session is closed by the unload callback."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
