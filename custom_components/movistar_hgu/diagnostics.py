"""Diagnostics with everything identifying or secret redacted."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import CONF_SSH_HOST_KEY
from .coordinator import HguConfigEntry

TO_REDACT = {
    CONF_PASSWORD,
    CONF_HOST,
    CONF_SSH_HOST_KEY,
    "unique_id",
    "serial_number",
    "ipv4",
    "gateway",
    "mac",
    "ip",
    "hostname",
    "ssid",
    "internal_ip",
    "title",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HguConfigEntry
) -> dict[str, Any]:
    runtime = entry.runtime_data

    def dump(coordinator: Any) -> Any:
        return asdict(coordinator.data) if coordinator.data is not None else None

    return async_redact_data(
        {
            "entry": entry.as_dict(),
            "ssh_enabled": runtime.cli is not None,
            "fast": dump(runtime.fast),
            "slow": dump(runtime.slow),
            "config": dump(runtime.config),
        },
        TO_REDACT,
    )
