"""SSH console client tests against an in-process fake console (S3, S10)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import asyncssh
import pytest

from custom_components.movistar_hgu.hgu.cli import (
    FORBIDDEN_PREFIXES,
    HguCli,
    parse_temperatures,
    parse_tr069,
)
from custom_components.movistar_hgu.hgu.errors import (
    HguAuthError,
    HguConnectionError,
    HguForbiddenCommand,
)

USER, PASSWORD = "1234", "router-pass"
OUTPUTS = {
    "show temperature": "wifi 59\r\nwifi_plus 53\r\nmain_soc 75.3\r\n",
    "show tr_status": "TR_status registered\r\n",
}


class _Server(asyncssh.SSHServer):
    def begin_auth(self, username: str) -> bool:
        return True

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        return (username, password) == (USER, PASSWORD)


async def _console(process: asyncssh.SSHServerProcess) -> None:
    """Behave like Reduced_CLI_HGU: echo, output, then ' > '."""
    if process.command:  # non-interactive exec is refused by the real router
        process.stdout.write("Error: Injection command\r\n")
        process.exit(1)
        return
    process.stdout.write(" > ")
    async for line in process.stdin:
        cmd = line.strip()
        if cmd == "exit":
            break
        process.stdout.write(f"{cmd}\r\n" + OUTPUTS.get(cmd, "Invalid command!!!\r\n") + " > ")
    process.exit(0)


@pytest.fixture
async def console() -> AsyncIterator[tuple[int, str]]:
    key = asyncssh.generate_private_key("ssh-ed25519")
    server = await asyncssh.create_server(
        _Server, "127.0.0.1", 0, server_host_keys=[key], process_factory=_console
    )
    port = server.sockets[0].getsockname()[1]
    yield port, key.export_public_key().decode()
    server.close()
    await server.wait_closed()


async def test_runs_allowed_commands(console) -> None:
    port, _ = console
    cli = HguCli("127.0.0.1", PASSWORD, port=port)
    out = await cli.async_run(["show temperature", "show tr_status"])
    assert parse_temperatures(out["show temperature"]) == {
        "wifi": 59.0,
        "wifi_plus": 53.0,
        "main_soc": 75.3,
    }
    assert parse_tr069(out["show tr_status"]) == "registered"


async def test_learns_and_then_pins_host_key(console) -> None:
    port, server_key = console
    cli = HguCli("127.0.0.1", PASSWORD, port=port)
    await cli.async_run(["show tr_status"])
    assert cli.host_key is not None
    assert cli.host_key.split()[1] == server_key.split()[1]
    pinned = HguCli("127.0.0.1", PASSWORD, port=port, host_key=cli.host_key)
    await pinned.async_run(["show tr_status"])


async def test_rejects_wrong_pinned_key(console) -> None:
    port, _ = console
    other = asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode()
    cli = HguCli("127.0.0.1", PASSWORD, port=port, host_key=other)
    with pytest.raises(HguConnectionError):
        await cli.async_run(["show tr_status"])


async def test_wrong_password(console) -> None:
    port, _ = console
    with pytest.raises(HguAuthError):
        await HguCli("127.0.0.1", "nope", port=port).async_run(["show tr_status"])


@pytest.mark.parametrize(
    "command",
    [
        "show wifi_plus",
        "show second_wifi",
        "show second_wifi_plus",
        "show ppp_info",
        "show voip_info",
        "show opah_agent_key",
        "set reboot",
        "set led control_mode",
        "show temperature; set reboot",
        "show tr_status\nset reboot",
    ],
)
async def test_forbidden_commands_never_sent(command: str) -> None:
    cli = HguCli("192.0.2.1", PASSWORD)  # unreachable on purpose: must fail before connecting
    with pytest.raises(HguForbiddenCommand):
        await cli.async_run([command])


def test_forbidden_list_covers_password_dumps() -> None:
    for cmd in ("show wifi_plus", "show second_wifi", "show ppp_info", "show voip_info"):
        assert cmd.startswith(FORBIDDEN_PREFIXES)
