"""Read-only live check of the SSH console client (password from keychain)."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from custom_components.movistar_hgu.hgu.cli import (
    HguCli,
    parse_temperatures,
    parse_tr069,
)


async def main() -> None:
    pw = subprocess.run(  # noqa: ASYNC221 - one-off dev tool
        ["security", "find-generic-password", "-s", "hgu-movistar", "-a", "1234", "-w"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.rstrip("\n")
    cli = HguCli("192.168.1.1", pw)
    t = time.monotonic()
    out = await cli.async_run(["show temperature", "show tr_status", "show iot_install"])
    print(f"first run {time.monotonic() - t:.2f}s; host key learned: {cli.host_key.split()[0]}")
    print(parse_temperatures(out["show temperature"]), parse_tr069(out["show tr_status"]))
    print(repr(out["show iot_install"]))
    t = time.monotonic()
    pinned = HguCli("192.168.1.1", pw, host_key=cli.host_key)
    await pinned.async_run(["show temperature"])
    print(f"pinned run {time.monotonic() - t:.2f}s OK")


asyncio.run(main())
