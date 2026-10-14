"""Shared helpers for library tests (no Home Assistant needed)."""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()
