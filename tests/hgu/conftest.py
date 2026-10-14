"""Shared helpers for library tests (no Home Assistant needed)."""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


try:
    import pytest

    @pytest.fixture(autouse=True)
    def _allow_local_sockets(socket_enabled: None) -> None:
        """Library tests run fake router/console servers on 127.0.0.1.

        The Home Assistant test plugin blocks sockets globally; these tests
        need loopback only (nothing reaches the real network).
        """

except ImportError:  # pragma: no cover
    pass
