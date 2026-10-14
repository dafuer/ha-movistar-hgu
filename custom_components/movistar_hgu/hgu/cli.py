"""Optional SSH access to the router's restricted console (Reduced_CLI_HGU).

The console only works interactively (an exec request answers
``Error: Injection command``): it prints the prompt `` > ``, echoes each
command and answers with ``\\r\\n`` lines. It offers a few things the web UI
does not (SoC and radio temperatures, TR-069 status).

Safety:

* Only commands in ``ALLOWED_COMMANDS`` are ever sent. Several ``show``
  commands print Wi-Fi, PPPoE or SIP passwords in clear and ``set`` changes
  the router, so everything else is refused before connecting.
* The router's host key is learned on first use (``host_key``) and required
  afterwards, so a box impersonating the router cannot collect the password.
"""

from __future__ import annotations

import asyncio
import re
from typing import Final

import asyncssh

from .errors import HguAuthError, HguConnectionError, HguForbiddenCommand

PROMPT: Final = " > "
ALLOWED_COMMANDS: Final = frozenset(
    {
        "show temperature",
        "show tr_status",
        "show uptime",
        "show iot_install",
        "show led",
    }
)
# Documentation of why: these print credentials or act on the router.
FORBIDDEN_PREFIXES: Final = (
    "show wifi_plus",
    "show second_wifi",
    "show ppp_info",
    "show voip_info",
    "show opah_agent_key",
    "show scan_wifi",
    "show primary_diagnosis",
    "set",
    "get",
)


class HguCli:
    def __init__(
        self,
        host: str,
        password: str,
        *,
        port: int = 22,
        username: str = "1234",
        host_key: str | None = None,
        timeout: float = 20,
    ) -> None:
        self._host = host
        self._password = password
        self._port = port
        self._username = username
        self.host_key = host_key
        self._timeout = timeout

    @staticmethod
    def _check(commands: list[str]) -> None:
        for cmd in commands:
            # The allow-list is the guard; FORBIDDEN_PREFIXES documents why it is tight.
            if cmd not in ALLOWED_COMMANDS or cmd.startswith(FORBIDDEN_PREFIXES):
                raise HguForbiddenCommand(f"Console command not allowed: {cmd!r}")

    async def async_run(self, commands: list[str]) -> dict[str, str]:
        """Run allow-listed commands in one session; return output per command."""
        self._check(commands)
        try:
            return await asyncio.wait_for(self._run(commands), self._timeout)
        except asyncssh.PermissionDenied as err:
            raise HguAuthError("The router rejected the SSH password") from err
        except (asyncssh.Error, OSError, TimeoutError) as err:
            raise HguConnectionError(f"SSH to {self._host}: {err}") from err

    async def _run(self, commands: list[str]) -> dict[str, str]:
        known_hosts = (
            ([asyncssh.import_public_key(self.host_key)], [], []) if self.host_key else None
        )
        async with asyncssh.connect(
            self._host,
            port=self._port,
            username=self._username,
            password=self._password,
            known_hosts=known_hosts,
            client_keys=None,
            agent_path=None,
            preferred_auth="password,keyboard-interactive",
        ) as conn:
            if self.host_key is None:
                server_key = conn.get_server_host_key()
                if server_key is not None:
                    self.host_key = server_key.export_public_key().decode().strip()
            process = await conn.create_process(term_type="vt100", encoding="latin-1")
            await process.stdout.readuntil(PROMPT)
            results: dict[str, str] = {}
            for cmd in commands:
                process.stdin.write(cmd + "\n")
                raw = await process.stdout.readuntil(PROMPT)
                results[cmd] = _strip_echo(raw[: -len(PROMPT)], cmd)
            process.stdin.write("exit\n")
            process.close()
            return results


def _strip_echo(raw: str, cmd: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "")
    lines = text.split("\n")
    if lines and lines[0].strip() == cmd:
        lines = lines[1:]
    return "\n".join(lines).strip("\n") + "\n"


def parse_temperatures(text: str) -> dict[str, float]:
    """``show temperature`` → {'wifi': 59.0, 'wifi_plus': 53.0, 'main_soc': 75.3}."""
    temps = {}
    for line in text.splitlines():
        m = re.fullmatch(r"\s*(\w+)\s+(-?\d+(?:\.\d+)?)\s*", line)
        if m:
            temps[m.group(1)] = float(m.group(2))
    return temps


def parse_tr069(text: str) -> str | None:
    m = re.search(r"TR_status\s+(\S+)", text)
    return m.group(1) if m else None
