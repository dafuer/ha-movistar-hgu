"""Capture raw responses from a Movistar Askey HGU for offline tests.

Reads the admin password from the macOS keychain (service ``hgu-movistar``)
so it never appears in argv, environment or logs. Only read endpoints
(cbGet*) and page GETs are requested. Output goes to ``captures/`` (git
ignored); sanitize with ``tools/sanitize.py`` before committing anything.
"""

from __future__ import annotations

import http.cookiejar
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HOST = "http://192.168.1.1"
OUT = Path(__file__).resolve().parent.parent / "captures"


def keychain_password() -> str:
    return subprocess.run(
        ["security", "find-generic-password", "-s", "hgu-movistar", "-a", "1234", "-w"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.rstrip("\n")


def xor(value: str) -> str:
    return "".join(chr(ord(c) ^ 0x1F) for c in value)


def main(names: list[str]) -> None:
    OUT.mkdir(exist_ok=True)
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.open(HOST + "/", timeout=10).read()
    data = urllib.parse.urlencode(
        {"loginUsername": xor("1234"), "loginPassword": xor(keychain_password())}
    ).encode()
    login = opener.open(HOST + "/cgi-bin/te_acceso_router.cgi", data=data, timeout=10)
    (OUT / "login_response.html").write_bytes(login.read())
    print("cookies:", sorted(c.name for c in jar))
    for name in names:
        if name.endswith(".asp"):
            req = urllib.request.Request(f"{HOST}/{name}")
        else:
            # "cbGetWifi:dpm_cfg_wifi_0i=1" -> POST with that form field.
            endpoint, _, param = name.partition(":")
            assert endpoint.startswith("cbGet"), f"refusing non-read endpoint {name}"
            payload = param.encode() if param else b""
            req = urllib.request.Request(
                f"{HOST}/cgi-bin/{endpoint}.xml", data=payload, method="POST"
            )
        body = opener.open(req, timeout=15).read()
        suffix = "" if name.endswith(".asp") else ".xml"
        safe = name.replace(":", "__").replace("=", "-")
        (OUT / f"{safe}{suffix}").write_bytes(body)
        print(f"{name}: {len(body)} bytes")
    opener.open(HOST + "/cgi-bin/te_logout.cgi", timeout=10).read()
    print("logged out")


if __name__ == "__main__":
    main(sys.argv[1:])
