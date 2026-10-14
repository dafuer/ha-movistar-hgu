"""Read-only live check of the library against the real router.

Password comes from the macOS keychain (service ``hgu-movistar``). Prints
parsed models only; models carry no secrets by construction.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from custom_components.movistar_hgu.hgu.client import HguClient  # noqa: E402


def keychain_password() -> str:
    return subprocess.run(
        ["security", "find-generic-password", "-s", "hgu-movistar", "-a", "1234", "-w"],
        check=True, capture_output=True, text=True,
    ).stdout.rstrip("\n")


async def main() -> None:
    jar = aiohttp.CookieJar(unsafe=True)
    async with aiohttp.ClientSession(cookie_jar=jar) as session:
        client = HguClient(session, "192.168.1.1", keychain_password())
        t = time.monotonic()
        print(await client.async_get_summary())
        print(await client.async_get_gpon())
        for w in await client.async_get_wan_interfaces():
            print(w)
        stats = await client.async_get_statistics()
        print([(c.name, c.up, c.rx_bytes, c.tx_bytes) for c in stats.ip_interfaces])
        print([h.hostname for h in await client.async_get_hosts()])
        print(await client.async_get_wifi_radio(0), await client.async_get_wifi_radio(1))
        print(await client.async_get_access_point(2))
        print(await client.async_get_port_mappings())
        print(await client.async_get_upnp_enabled(), await client.async_get_syslog())
        print(await client.async_get_voice_line(), await client.async_get_iot_install())
        print(f"13 reads in {time.monotonic() - t:.2f}s")
        await client.async_logout()


asyncio.run(main())
