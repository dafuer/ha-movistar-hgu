"""Live, reversible check of the controls (IoT window, guest Wi-Fi).

The guest key is never printed: only a SHA-256 of it is compared before and
after, to prove the toggle did not change it.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import subprocess
import sys
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from custom_components.movistar_hgu.hgu.client import HguClient


def keychain_password() -> str:
    return subprocess.run(
        ["security", "find-generic-password", "-s", "hgu-movistar", "-a", "1234", "-w"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.rstrip("\n")


async def key_digest(client: HguClient, ap: int) -> str:
    raw = await client.async_read_xml("cbGetWifiAccPt", {"dpm_cfg_wifi_acc_pt_0i": str(ap)})
    m = re.search(r"<key_phrase>([^<]*)</key_phrase>", raw)
    return hashlib.sha256((m.group(1) if m else "").encode()).hexdigest()[:12]


async def main(what: str) -> None:
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
        client = HguClient(session, "192.168.1.1", keychain_password())
        if what == "iot":
            print("before:", await client.async_get_iot_install())
            await client.async_start_iot_install(60)
            print("started:", await client.async_get_iot_install())
            await client.async_cancel_iot_install()
            print("cancelled:", await client.async_get_iot_install())
        elif what == "guest":
            before = {ap: await key_digest(client, ap) for ap in (2, 3)}
            print("before:", (await client.async_get_access_point(2)).enabled, before)
            await client.async_set_guest_wifi(True)
            await asyncio.sleep(5)
            on = await client.async_get_access_point(2)
            print("on:", on.enabled, on.up, {ap: await key_digest(client, ap) for ap in (2, 3)})
            await client.async_set_guest_wifi(False)
            await asyncio.sleep(5)
            after = {ap: await key_digest(client, ap) for ap in (2, 3)}
            print("off:", (await client.async_get_access_point(2)).enabled, after)
            print("KEY UNCHANGED" if after == before else "KEY CHANGED!")
        await client.async_logout()


asyncio.run(main(sys.argv[1]))
