"""A small aiohttp app that behaves like the RTF8316VW web server.

It reproduces what the client depends on, as observed on the real router:
the ``_httpdSessionId_`` cookie, the XOR-encoded login form, HTTP 400 on
``cbGet*.xml`` without a session, 302 to ``te_acceso_router.asp`` on pages
without a session, the wrong-password page (``var user = 'xxx'``) and the
write endpoints the integration uses. Every request is recorded.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from urllib.parse import parse_qsl

from aiohttp import web

from .conftest import fixture

COOKIE = "_httpdSessionId_"
PASSWORD = "router-pass"
GUEST_KEY = "guest-key-123456"


def xor(value: str) -> str:
    return "".join(chr(ord(c) ^ 0x1F) for c in value)


@dataclass
class Recorded:
    method: str
    path: str
    query: dict[str, str]
    form: dict[str, str]


@dataclass
class FakeRouter:
    sessions: set[str] = field(default_factory=set)
    requests: list[Recorded] = field(default_factory=list)
    logins: int = 0
    logouts: int = 0
    guest_enabled: bool = False
    iot_remaining: int = 0
    rebooted: bool = False

    def expire_sessions(self) -> None:
        self.sessions.clear()

    def app(self) -> web.Application:
        app = web.Application(middlewares=[self._record])
        app.router.add_get("/", self._root)
        app.router.add_post("/cgi-bin/te_acceso_router.cgi", self._login)
        app.router.add_get("/cgi-bin/te_logout.cgi", self._logout)
        app.router.add_post("/cgi-bin/{name}.xml", self._xml)
        app.router.add_get("/cgi-bin/te_wifi.wl", self._wifi_wl)
        app.router.add_get("/cgi-bin/te_wifi_guest.wl", self._guest_wl)
        app.router.add_get("/{page}.asp", self._page)
        return app

    @web.middleware
    async def _record(self, request: web.Request, handler):  # type: ignore[no-untyped-def]
        form = dict(await request.post()) if request.method == "POST" else {}
        self.requests.append(
            Recorded(
                request.method,
                request.path,
                dict(request.query),
                {k: str(v) for k, v in form.items()},
            )
        )
        return await handler(request)

    def _authed(self, request: web.Request) -> bool:
        return request.cookies.get(COOKIE) in self.sessions

    async def _root(self, request: web.Request) -> web.Response:
        resp = web.Response(text="<html>login</html>", content_type="text/html")
        if COOKIE not in request.cookies:
            resp.set_cookie(COOKIE, secrets.token_hex(8))
        return resp

    async def _login(self, request: web.Request) -> web.Response:
        form = await request.post()
        if (
            xor(str(form.get("loginPassword", ""))) != PASSWORD
            or xor(str(form.get("loginUsername", ""))) != "1234"
        ):
            return web.Response(
                text="<script>var bruteTime = '0'; var user = 'xxx';</script>te_acceso_router",
                content_type="text/html",
            )
        sid = request.cookies.get(COOKIE) or secrets.token_hex(8)
        self.sessions.add(sid)
        self.logins += 1
        resp = web.Response(
            text='<script>location.href = "/te_wifi.asp";</script>', content_type="text/html"
        )
        resp.set_cookie(COOKIE, sid)
        return resp

    async def _logout(self, request: web.Request) -> web.Response:
        self.sessions.discard(request.cookies.get(COOKIE, ""))
        self.logouts += 1
        return web.Response(text="bye")

    async def _xml(self, request: web.Request) -> web.Response:
        if not self._authed(request):
            return web.Response(status=400, text="<HTML>Access Error: 400</HTML>")
        name = request.match_info["name"]
        if name == "cbReboot":
            form = await request.post()
            if form.get("sessionKey") != "0123456789":
                return web.Response(status=400, text="bad key")
            self.rebooted = True
            return web.Response(
                text="<Response><cbReboot><Msg>Rebooting</Msg><Result>0</Result></cbReboot></Response>",
                content_type="text/xml",
            )
        form = await request.post()
        suffix = "".join(f"__{k}-{v}" for k, v in form.items())
        try:
            body = fixture(f"{name}{suffix}.xml")
        except FileNotFoundError:
            return web.Response(status=404)
        return web.Response(text=body, content_type="text/xml")

    async def _page(self, request: web.Request) -> web.Response:
        page = request.match_info["page"] + ".asp"
        if page == "te_acceso_router.asp":
            return web.Response(text="te_acceso_router login form", content_type="text/html")
        if not self._authed(request):
            raise web.HTTPFound("/te_acceso_router.asp")
        if page == "te_wifi.asp":
            text = (
                fixture("te_wifi.asp")
                .replace(
                    "var tef_assoc_time_left = '0'",
                    f"var tef_assoc_time_left = '{self.iot_remaining}'",
                )
                .replace(
                    "var tef_assoc_state = '0'",
                    f"var tef_assoc_state = '{1 if self.iot_remaining else 0}'",
                )
            )
            return web.Response(text=text, content_type="text/html")
        if page == "te_wifi_guest.asp":
            text = (
                fixture("te_wifi_guest.asp")
                .replace("var wpaPskKey = 'REDACTED'", f"var wpaPskKey = '{GUEST_KEY}'")
                .replace("var wifiActive = '0'", f"var wifiActive = '{int(self.guest_enabled)}'")
            )
            return web.Response(text=text, content_type="text/html")
        return web.Response(status=404)

    async def _wifi_wl(self, request: web.Request) -> web.Response:
        if not self._authed(request) or request.query.get("sessionKey") != "0123456789":
            raise web.HTTPFound("/te_acceso_router.asp")
        state = request.query.get("tef_assoc_state")
        self.iot_remaining = (
            int(request.query.get("tef_assoc_timeout_sec", "0")) if state == "1" else 0
        )
        raise web.HTTPFound(request.query.get("curWebPage", "/te_wifi.asp"))

    async def _guest_wl(self, request: web.Request) -> web.Response:
        if not self._authed(request) or request.query.get("sessionKey") != "0123456789":
            raise web.HTTPFound("/te_acceso_router.asp")
        # The real router would overwrite the key with whatever arrives.
        assert xor(request.query["wlWpaPsk"]) == GUEST_KEY, "guest key would be lost"
        self.guest_enabled = request.query.get("wlEnbl") == "1"
        raise web.HTTPFound(request.query.get("curWebPage", "/te_wifi_guest.asp"))


def parse_query(raw: str) -> dict[str, str]:
    return dict(parse_qsl(raw))
