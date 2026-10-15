"""Web client tests against the fake router (S1, S2, S3, S9)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import aiohttp
import pytest
from aiohttp.test_utils import TestServer

from custom_components.movistar_hgu.hgu.client import HguClient
from custom_components.movistar_hgu.hgu.errors import HguAuthError, HguForbiddenCommand
from custom_components.movistar_hgu.hgu.models import WanRole

from .fake_router import GUEST_KEY, PASSWORD, FakeRouter


@pytest.fixture
async def router() -> AsyncIterator[tuple[FakeRouter, str]]:
    fake = FakeRouter()
    server = TestServer(fake.app())
    await server.start_server()
    yield fake, f"{server.host}:{server.port}"
    await server.close()


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as s:
        yield s


async def test_login_reuses_session(router, session) -> None:
    fake, host = router
    client = HguClient(session, host, PASSWORD)
    info = await client.async_get_summary()
    await client.async_get_gpon()
    assert info.model == "RTF8316VW"
    assert fake.logins == 1


async def test_relogin_once_when_session_expires(router, session) -> None:
    fake, host = router
    client = HguClient(session, host, PASSWORD)
    await client.async_get_summary()
    fake.expire_sessions()
    wans = await client.async_get_wan_interfaces()
    assert {w.role for w in wans} >= {WanRole.VOICE}
    assert fake.logins == 2


async def test_page_redirect_triggers_relogin(router, session) -> None:
    fake, host = router
    client = HguClient(session, host, PASSWORD)
    await client.async_get_summary()
    fake.expire_sessions()
    iot = await client.async_get_iot_install()
    assert iot.active is False
    assert fake.logins == 2


async def test_wrong_password(router, session) -> None:
    _, host = router
    client = HguClient(session, host, "nope")
    with pytest.raises(HguAuthError):
        await client.async_get_summary()


async def test_logout(router, session) -> None:
    fake, host = router
    client = HguClient(session, host, PASSWORD)
    await client.async_get_summary()
    await client.async_logout()
    assert fake.logouts == 1 and not fake.sessions
    await client.async_logout()  # idempotent: nothing to close
    assert fake.logouts == 1


async def test_reader_refuses_write_endpoints(router, session) -> None:
    _, host = router
    client = HguClient(session, host, PASSWORD)
    for name in ("cbSetWifi", "cbReboot", "cbAddUser", "cbDeleteUser", "te_x"):
        with pytest.raises(HguForbiddenCommand):
            await client.async_read_xml(name)


async def test_only_cbget_posted_while_polling(router, session) -> None:
    fake, host = router
    client = HguClient(session, host, PASSWORD)
    await client.async_get_summary()
    await client.async_get_statistics()
    await client.async_get_hosts()
    await client.async_get_wifi_radio(1)
    await client.async_get_access_point(2)
    posted = {r.path for r in fake.requests if r.path.endswith(".xml")}
    assert posted and all(p.startswith("/cgi-bin/cbGet") for p in posted)


async def test_reboot_sends_session_key(router, session) -> None:
    fake, host = router
    client = HguClient(session, host, PASSWORD)
    await client.async_reboot()
    assert fake.rebooted


async def test_iot_install_start_and_cancel(router, session) -> None:
    fake, host = router
    client = HguClient(session, host, PASSWORD)
    await client.async_start_iot_install(600)
    assert fake.iot_remaining == 600
    assert (await client.async_get_iot_install()).active
    await client.async_cancel_iot_install()
    assert fake.iot_remaining == 0


async def test_iot_install_duration_bounds(router, session) -> None:
    _, host = router
    client = HguClient(session, host, PASSWORD)
    for seconds in (0, 59, 1801):
        with pytest.raises(ValueError):
            await client.async_start_iot_install(seconds)


async def test_guest_wifi_keeps_key(router, session) -> None:
    fake, host = router
    client = HguClient(session, host, PASSWORD)
    await client.async_set_guest_wifi(True)
    assert fake.guest_enabled
    await client.async_set_guest_wifi(False)
    assert not fake.guest_enabled
    sent = [r for r in fake.requests if r.path.endswith("te_wifi_guest.wl")]
    assert sent[-1].query["wlSsid"] == "MOVISTAR-0000-INV-WIFI7"
    assert sent[-1].query["wlAuthMode"] == "B4"
    assert GUEST_KEY not in repr(client.__dict__)


async def test_recovers_by_itself_after_router_reboot() -> None:
    """A reboot kills every open connection and the router-side session.

    Seen live on 2026-10-15: with pooled keep-alive connections the client kept
    failing in milliseconds after the router (and the NAT in between) came back,
    until the integration was reloaded by hand.
    """
    from custom_components.movistar_hgu.hgu.client import new_session
    from custom_components.movistar_hgu.hgu.errors import HguConnectionError

    fake = FakeRouter()
    server = TestServer(fake.app())
    await server.start_server()
    port = server.port
    async with new_session() as session:
        client = HguClient(session, f"{server.host}:{port}", PASSWORD)
        await client.async_get_summary()

        await server.close()  # the router goes away...
        with pytest.raises(HguConnectionError):
            await client.async_get_summary()

        fake.expire_sessions()  # ...and comes back on the same address, sessions lost
        server = TestServer(fake.app(), port=port)
        await server.start_server()
        try:
            info = await client.async_get_summary()
        finally:
            await server.close()
    assert info.model == "RTF8316VW"
    assert fake.logins == 2


async def test_login_after_reboot_starts_without_the_stale_cookie(router, session) -> None:
    fake, host = router
    client = HguClient(session, host, PASSWORD)
    await client.async_get_summary()
    old = {c.key: c.value for c in session.cookie_jar}["_httpdSessionId_"]
    fake.expire_sessions()
    await client.async_get_summary()
    login_get = [r for r in fake.requests if r.method == "GET" and r.path == "/"][-1]
    assert login_get is not None
    new = {c.key: c.value for c in session.cookie_jar}["_httpdSessionId_"]
    assert new != old
