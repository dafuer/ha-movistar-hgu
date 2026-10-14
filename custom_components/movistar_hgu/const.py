"""Constants for the Movistar HGU integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "movistar_hgu"

DEFAULT_HOST: Final = "192.168.1.1"
MANUFACTURER: Final = "Askey"

CONF_SSH_ENABLED: Final = "ssh_enabled"
CONF_SSH_PORT: Final = "ssh_port"
CONF_SSH_HOST_KEY: Final = "ssh_host_key"
DEFAULT_SSH_PORT: Final = 22

# Polling tiers. Traffic needs 30 s: the WAN byte counters are 32-bit and a
# second wrap between two polls would need > 1.1 Gbit/s sustained.
FAST_INTERVAL: Final = timedelta(seconds=30)
SLOW_INTERVAL: Final = timedelta(minutes=5)
CONFIG_INTERVAL: Final = timedelta(hours=1)

# Upper bound used to discard impossible counter jumps (10G port).
MAX_LINK_BPS: Final = 10_000_000_000

IOT_INSTALL_SECONDS: Final = 600
GUEST_ACCESS_POINT: Final = 2
