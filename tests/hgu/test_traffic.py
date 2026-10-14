"""Traffic accumulator tests (S6)."""

from __future__ import annotations

from custom_components.movistar_hgu.hgu.traffic import WRAP_32, TrafficAccumulator


def test_first_sample_counts_nothing() -> None:
    acc = TrafficAccumulator()
    assert acc.update(3_500_000_000, elapsed_s=None, rebooted=False) == 0
    assert acc.total == 0


def test_normal_growth() -> None:
    acc = TrafficAccumulator()
    acc.update(1_000, elapsed_s=None, rebooted=False)
    assert acc.update(1_500, elapsed_s=30, rebooted=False) == 500
    assert acc.total == 500


def test_32bit_wrap_without_reboot() -> None:
    acc = TrafficAccumulator()
    acc.update(WRAP_32 - 100, elapsed_s=None, rebooted=False)
    assert acc.update(50, elapsed_s=30, rebooted=False) == 150
    assert acc.total == 150


def test_reset_after_reboot_counts_from_zero() -> None:
    acc = TrafficAccumulator()
    acc.update(3_000_000_000, elapsed_s=None, rebooted=False)
    assert acc.update(1_000, elapsed_s=30, rebooted=True) == 1_000


def test_impossible_jump_is_discarded() -> None:
    """More than the link can carry in the interval means a glitch, not traffic."""
    acc = TrafficAccumulator(max_bps=10_000_000_000)
    acc.update(0, elapsed_s=None, rebooted=False)
    # 4 GB in 1 s = 32 Gbit/s: impossible on a 10G port.
    assert acc.update(4_000_000_000, elapsed_s=1, rebooted=False) == 0
    assert acc.total == 0
    # The baseline moved, so the next normal sample counts normally.
    assert acc.update(4_000_001_000, elapsed_s=30, rebooted=False) == 1_000


def test_state_roundtrip() -> None:
    acc = TrafficAccumulator()
    acc.update(10, elapsed_s=None, rebooted=False)
    acc.update(20, elapsed_s=30, rebooted=False)
    restored = TrafficAccumulator.from_state(acc.as_state())
    assert restored.total == 10
    assert restored.update(25, elapsed_s=30, rebooted=False) == 5


def test_restored_baseline_after_long_gap_counts_nothing_unknown() -> None:
    """After HA was down, a decrease cannot be told apart from a wrap: skip it."""
    acc = TrafficAccumulator.from_state({"total": 100, "last_raw": 5_000})
    assert acc.update(1_000, elapsed_s=None, rebooted=False) == 0
    assert acc.total == 100
