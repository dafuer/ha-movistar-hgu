"""Async client for the Askey RTF8316VW («Router Movistar WiFi 7») web UI.

Reads go through the XML API the router's own advanced UI uses
(``POST /cgi-bin/cbGet<Name>.xml``). A handful of writes the integration needs
(reboot, IoT install window, guest Wi-Fi) are explicit methods; nothing else
can be written through this class.

The session is a cookie (``_httpdSessionId_``). It is kept between calls,
re-established once when the router says it expired, and closed on
``async_logout``. All requests are serialized: the router's web server is
small and single sessions are what its UI does.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final
from urllib.parse import quote

import aiohttp

from . import parsers
from .errors import (
    HguAuthError,
    HguConnectionError,
    HguForbiddenCommand,
    HguResponseError,
    HguSessionExpired,
)
from .models import (
    AccessPoint,
    FiberInfo,
    Host,
    IotInstall,
    PortMapping,
    Statistics,
    SyslogConfig,
    SystemInfo,
    VoiceLine,
    WanInterface,
    WifiRadio,
)

_LOGGER = logging.getLogger(__name__)

ADMIN_USER: Final = "1234"
LOGIN_PAGE: Final = "te_acceso_router"
IOT_MIN_S: Final = 60
IOT_MAX_S: Final = 1800
GUEST_ACCESS_POINT: Final = 2


def encode(value: str) -> str:
    """Reversible XOR 0x1F the web UI applies to credentials and Wi-Fi keys."""
    return "".join(chr(ord(c) ^ 0x1F) for c in value)


def _uri_component(value: str) -> str:
    """Python twin of JavaScript ``encodeURIComponent``."""
    return quote(value, safe="-_.!~*'()")


def new_session() -> aiohttp.ClientSession:
    """The HTTP session the client expects; the caller owns and closes it.

    * ``force_close``: one TCP connection per request, no keep-alive pool. A
      router reboot (or a NAT box in between restarting) leaves pooled
      connections dead, and reusing them kept the client failing after the
      router was back. On a LAN a fresh connection costs nothing.
    * ``unsafe`` cookie jar: the router sets its session cookie on a bare IP,
      which aiohttp's default jar drops.
    """
    return aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(force_close=True),
        cookie_jar=aiohttp.CookieJar(unsafe=True),
    )


class HguClient:
    """One authenticated web session against the router."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        password: str,
        *,
        timeout: float = 15,
    ) -> None:
        self._session = session
        self._base = f"http://{host.strip().rstrip('/')}"
        self._password = password
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._lock = asyncio.Lock()
        self._logged_in = False

    @property
    def host_url(self) -> str:
        return self._base

    # --- session ------------------------------------------------------------

    async def async_login(self) -> None:
        async with self._lock:
            await self._login()

    async def _login(self) -> None:
        self._logged_in = False
        # The router only hands out a session cookie to a client that has
        # none, and forgets all of them when it reboots: start clean.
        self._session.cookie_jar.clear()
        await self._raw("GET", "/")  # the router hands out the session cookie here
        text = await self._raw(
            "POST",
            "/cgi-bin/te_acceso_router.cgi",
            data={"loginUsername": encode(ADMIN_USER), "loginPassword": encode(self._password)},
        )
        if "user = 'xxx'" in text or LOGIN_PAGE in text:
            raise HguAuthError("The router rejected the admin password")
        self._logged_in = True
        _LOGGER.debug("Logged in to %s", self._base)

    async def async_logout(self) -> None:
        async with self._lock:
            if not self._logged_in:
                return
            self._logged_in = False
            try:
                await self._raw("GET", "/cgi-bin/te_logout.cgi")
            except HguConnectionError:
                _LOGGER.debug("Logout failed; the session will expire on its own")

    async def _raw(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, str] | None = None,
        expect_session: bool = False,
    ) -> str:
        """Send one request. With ``expect_session``, detect a dead session."""
        try:
            async with self._session.request(
                method, self._base + path, data=data, timeout=self._timeout
            ) as resp:
                text = await resp.text(errors="replace")
                if expect_session:
                    if resp.status == 400 and path.endswith(".xml"):
                        raise HguSessionExpired(path)
                    if LOGIN_PAGE in str(resp.url) or any(
                        LOGIN_PAGE in str(h.url) for h in resp.history
                    ):
                        raise HguSessionExpired(path)
                if resp.status >= 400:
                    raise HguResponseError(f"{method} {path} returned HTTP {resp.status}")
                return text
        except (aiohttp.ClientError, TimeoutError, OSError) as err:
            raise HguConnectionError(f"{method} {path}: {err}") from err

    async def _authed(self, method: str, path: str, *, data: dict[str, str] | None = None) -> str:
        """Request needing a session: log in if needed, retry once if it expired."""
        async with self._lock:
            if not self._logged_in:
                await self._login()
            try:
                return await self._raw(method, path, data=data, expect_session=True)
            except HguConnectionError:
                # Unreachable usually means rebooting: its session is gone too.
                self._logged_in = False
                raise
            except HguSessionExpired:
                _LOGGER.debug("Session expired on %s; logging in again", path)
                await self._login()
                return await self._raw(method, path, data=data, expect_session=True)

    # --- generic readers ----------------------------------------------------

    async def async_read_xml(self, name: str, params: dict[str, str] | None = None) -> str:
        """POST to a read-only ``cbGet*`` endpoint. Anything else is refused."""
        if not name.startswith("cbGet") or not name.isalnum():
            raise HguForbiddenCommand(f"{name} is not a read endpoint")
        return await self._authed("POST", f"/cgi-bin/{name}.xml", data=params or {})

    async def async_read_page(self, page: str) -> str:
        if not page.endswith(".asp") or "/" in page:
            raise HguForbiddenCommand(f"{page} is not a page")
        return await self._authed("GET", f"/{page}")

    # --- typed readers ------------------------------------------------------

    async def async_get_summary(self) -> SystemInfo:
        return parsers.parse_summary(await self.async_read_xml("cbGetSummary"))

    async def async_get_gpon(self) -> FiberInfo:
        return parsers.parse_gpon(await self.async_read_xml("cbGetGPONInfo"))

    async def async_get_wan_interfaces(self) -> list[WanInterface]:
        return parsers.parse_wan_interfaces(await self.async_read_xml("cbGetWanIPIntf"))

    async def async_get_statistics(self) -> Statistics:
        return parsers.parse_statistics(await self.async_read_xml("cbGetStatistic"))

    async def async_get_hosts(self) -> list[Host]:
        return parsers.parse_hosts(await self.async_read_xml("cbGetLanHostList"))

    async def async_get_wifi_radio(self, index: int) -> WifiRadio:
        text = await self.async_read_xml("cbGetWifi", {"dpm_cfg_wifi_0i": str(index)})
        return parsers.parse_wifi_radio(text)

    async def async_get_access_point(self, index: int) -> AccessPoint:
        # The response carries the Wi-Fi key; the parser never copies it out.
        text = await self.async_read_xml("cbGetWifiAccPt", {"dpm_cfg_wifi_acc_pt_0i": str(index)})
        return parsers.parse_access_point(text)

    async def async_get_port_mappings(self) -> list[PortMapping]:
        return parsers.parse_port_mappings(await self.async_read_xml("cbGetNatPortMapping"))

    async def async_get_upnp_enabled(self) -> bool:
        return parsers.parse_upnp(await self.async_read_xml("cbGetUpnpCfg"))

    async def async_get_syslog(self) -> SyslogConfig:
        return parsers.parse_syslog(await self.async_read_xml("cbGetSyslog"))

    async def async_get_voice_line(self) -> VoiceLine:
        return parsers.parse_voice_line(await self.async_read_xml("cbGetVoiceLine"))

    async def async_get_iot_install(self) -> IotInstall:
        return parsers.parse_iot_install(await self.async_read_page("te_wifi.asp"))

    # --- controls -----------------------------------------------------------

    async def _session_key(self, page: str) -> tuple[str, str]:
        text = await self.async_read_page(page)
        key = parsers.page_var(text, "sessionKey")
        if not key:
            raise HguResponseError(f"No sessionKey in {page}")
        return key, text

    async def async_reboot(self) -> None:
        """Reboot the router. The session dies with it."""
        key, _ = await self._session_key("te_wifi.asp")
        text = await self._authed("POST", "/cgi-bin/cbReboot.xml", data={"sessionKey": key})
        if "<Result>0</Result>" not in text.replace(" ", ""):
            raise HguResponseError("cbReboot did not confirm")
        self._logged_in = False

    async def _wifi_wl(self, script: str, query: list[tuple[str, str]]) -> None:
        path = f"/cgi-bin/{script}?" + "&".join(f"{k}={v}" for k, v in query)
        await self._authed("GET", path)

    async def async_start_iot_install(self, seconds: int = 600) -> None:
        """Open the router's IoT pairing window (1-30 minutes, like the web UI)."""
        if not IOT_MIN_S <= seconds <= IOT_MAX_S:
            raise ValueError(f"IoT install window must be {IOT_MIN_S}-{IOT_MAX_S} s")
        await self._set_iot(1, seconds)

    async def async_cancel_iot_install(self) -> None:
        await self._set_iot(0, 0)

    async def _set_iot(self, state: int, seconds: int) -> None:
        key, page = await self._session_key("te_wifi.asp")
        await self._wifi_wl(
            "te_wifi.wl",
            [
                ("wlSsidIdx", "0"),
                ("tef_assoc_state", str(state)),
                ("tef_assoc_timeout_sec", str(seconds)),
                ("unitNum", parsers.page_var(page, "unitNum") or "0"),
                ("sessionKey", key),
                ("curWebPage", "/te_wifi.asp"),
            ],
        )

    async def async_set_guest_wifi(self, enabled: bool) -> None:
        """Turn the guest network on/off, re-sending its current name and key.

        The web UI always submits SSID, security and key together; sending a
        partial form would wipe the key. Only WPA modes are supported (WEP
        guest networks are refused rather than risked).
        """
        key, page = await self._session_key("te_wifi_guest.asp")
        ssid = parsers.page_var(page, "wifiSSIDName")
        auth = parsers.page_var(page, "wifiAuthMode")
        psk = parsers.page_var(page, "wpaPskKey")
        if not ssid or not auth:
            raise HguResponseError("Guest Wi-Fi page without SSID or security mode")
        if auth in ("00", "02"):
            raise HguForbiddenCommand(f"Guest security mode {auth} is not supported")
        if not psk or not 8 <= len(psk) <= 63:
            raise HguResponseError("Guest Wi-Fi key missing; refusing to overwrite it")
        query = [
            ("wlSsidIdx", "1"),
            ("ssid_id", parsers.page_var(page, "ssid_id") or str(GUEST_ACCESS_POINT)),
            ("acc_pt_id", parsers.page_var(page, "acc_pt_id") or str(GUEST_ACCESS_POINT)),
            ("wlSsid", _uri_component(ssid)),
            ("wlAuthMode", auth),
            ("wlWpaPsk", _uri_component(encode(psk))),
            ("wlEnbl", "1" if enabled else "0"),
            ("wlSyncNvram", "1"),
            ("unitNum", parsers.page_var(page, "unitNum") or "0"),
            ("sessionKey", key),
            ("curWebPage", "/te_wifi_guest.asp"),
        ]
        del psk, page
        await self._wifi_wl("te_wifi_guest.wl", query)
