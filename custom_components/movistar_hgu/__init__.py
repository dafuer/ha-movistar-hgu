"""The Movistar HGU (Askey RTF8316VW) integration."""

from __future__ import annotations

import aiohttp
from homeassistant.const import CONF_HOST, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import (
    CONF_SSH_ENABLED,
    CONF_SSH_HOST_KEY,
    CONF_SSH_PORT,
    DEFAULT_SSH_PORT,
    DOMAIN,
)
from .coordinator import (
    HguConfigCoordinator,
    HguConfigEntry,
    HguFastCoordinator,
    HguRuntime,
    HguSlowCoordinator,
)
from .hgu.cli import HguCli
from .hgu.client import HguClient

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
    Platform.SWITCH,
]


def router_session(hass: HomeAssistant) -> aiohttp.ClientSession:
    """One HTTP session for the integration, reused across reloads.

    The router sets its session cookie on a bare IP, which aiohttp's default
    cookie jar drops; hence the ``unsafe`` jar (and not the shared HA session).
    """
    store = hass.data.setdefault(DOMAIN, {})
    if (session := store.get("session")) is None or session.closed:
        session = store["session"] = async_create_clientsession(
            hass, cookie_jar=aiohttp.CookieJar(unsafe=True)
        )
    return session


async def async_setup_entry(hass: HomeAssistant, entry: HguConfigEntry) -> bool:
    """Set up the router from a config entry."""
    client = HguClient(router_session(hass), entry.data[CONF_HOST], entry.data[CONF_PASSWORD])

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

    # Close the router-side session; the HTTP session itself is shared and
    # closed by Home Assistant on shutdown.
    entry.async_on_unload(client.async_logout)

    await fast.async_load_traffic()
    await slow.async_config_entry_first_refresh()
    await fast.async_config_entry_first_refresh()
    await config.async_config_entry_first_refresh()

    entry.runtime_data = HguRuntime(
        client=client,
        fast=fast,
        slow=slow,
        config=config,
        cli=cli,
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
