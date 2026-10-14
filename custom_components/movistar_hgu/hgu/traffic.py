"""Turn the router's byte counters into a monotonic total.

The per-WAN counters (``rtm_cfg_ip_intf`` in ``cbGetStatistic``) are 32-bit:
they wrap at 4 GiB, which a busy fibre line does in minutes. The accumulator
interprets each new raw value against the previous one:

* growth → the difference;
* a decrease right after a router reboot → the counter restarted at zero;
* a decrease otherwise → one wrap (raw + 2^32 - previous);
* a jump bigger than the link could carry in the interval → glitch, ignored.

With a 30 s poll a second wrap would need > 1.1 Gbit/s sustained, more than
the line carries, so "one wrap at most" holds.
"""

from __future__ import annotations

from typing import Any, Final

WRAP_32: Final = 2**32


class TrafficAccumulator:
    def __init__(
        self,
        *,
        total: int = 0,
        last_raw: int | None = None,
        wrap: int = WRAP_32,
        max_bps: int | None = None,
    ) -> None:
        self.total = total
        self.last_raw = last_raw
        self._wrap = wrap
        self._max_bps = max_bps

    def update(self, raw: int, *, elapsed_s: float | None, rebooted: bool) -> int:
        """Feed a raw counter value; return the bytes added to ``total``.

        ``elapsed_s`` is the time since the previous sample in this process,
        or None for the first sample (including the first after a restore,
        when the gap is unknown and a decrease is ambiguous).
        """
        previous, self.last_raw = self.last_raw, raw
        if previous is None:
            return 0
        if raw >= previous:
            delta = raw - previous
        elif rebooted:
            delta = raw
        elif elapsed_s is None:
            return 0
        else:
            delta = raw + self._wrap - previous
        if elapsed_s and self._max_bps and delta * 8 / elapsed_s > self._max_bps:
            return 0
        self.total += delta
        return delta

    def as_state(self) -> dict[str, Any]:
        return {"total": self.total, "last_raw": self.last_raw}

    @classmethod
    def from_state(cls, state: dict[str, Any], **kwargs: Any) -> TrafficAccumulator:
        return cls(total=int(state.get("total", 0)), last_raw=state.get("last_raw"), **kwargs)
