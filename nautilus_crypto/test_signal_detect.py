"""Unit tests for the pure spike/dip detectors ported from the retired daemons.

Pure (no Nautilus, no network), so they run in any venv with pytest.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from signal_detect import DipDetector, SpikeDetector  # noqa: E402


# --------------------------------------------------------------------------- spike
def test_spike_fires_on_pump():
    d = SpikeDetector(threshold=0.015, window_sec=300, cooldown_sec=600)
    assert d.update(0, 100.0) is None       # first tick — no reference yet
    assert d.update(60, 100.5) is None      # +0.5% < 1.5%
    ev = d.update(120, 102.0)               # +2.0% vs 100 → PUMP
    assert ev is not None and ev["kind"] == "PUMP"
    assert ev["change_pct"] > 0.015
    assert ev["from_price"] == 100.0


def test_spike_fires_on_dump():
    d = SpikeDetector()
    d.update(0, 100.0)
    ev = d.update(120, 98.0)                # -2.0% → DUMP
    assert ev is not None and ev["kind"] == "DUMP"
    assert ev["change_pct"] < 0


def test_spike_cooldown_suppresses_repeat():
    d = SpikeDetector(cooldown_sec=600)
    d.update(0, 100.0)
    assert d.update(120, 102.0)["kind"] == "PUMP"
    # a second qualifying move inside the cooldown window is suppressed
    assert d.update(200, 104.0) is None


def test_spike_window_evicts_old_reference():
    d = SpikeDetector(threshold=0.015, window_sec=300)
    d.update(0, 100.0)
    d.update(350, 101.0)                    # 100.0 now outside 300s window → evicted
    assert d.update(400, 101.2) is None     # +0.2% vs 101 → no spike


# --------------------------------------------------------------------------- dip
def test_dip_flash_fires_on_fast_drop():
    d = DipDetector(flash_pct=0.03, flash_sec=60, fast_pct=0.05, fast_sec=300)
    d.update(0, 100.0)
    ev = d.update(50, 96.5)                 # -3.5% within 60s → FLASH (FAST not yet hit)
    assert ev is not None and ev["kind"] == "FLASH"


def test_dip_fast_takes_priority():
    d = DipDetector()
    d.update(0, 100.0)
    d.update(30, 99.0)
    ev = d.update(250, 94.0)                # -6% over 250s (≥5% FAST) → FAST
    assert ev is not None and ev["kind"] == "FAST"


def test_dip_ignores_rise():
    d = DipDetector()
    d.update(0, 100.0)
    assert d.update(50, 103.0) is None


def test_dip_cooldown_suppresses_repeat():
    d = DipDetector(cooldown_sec=600)
    d.update(0, 100.0)
    assert d.update(50, 96.0)["kind"] == "FLASH"
    assert d.update(80, 92.0) is None       # within cooldown → suppressed


def test_dip_no_signal_on_shallow_drop():
    d = DipDetector(flash_pct=0.03, flash_sec=60, fast_pct=0.05, fast_sec=300)
    d.update(0, 100.0)
    assert d.update(40, 98.5) is None       # -1.5% < both thresholds
