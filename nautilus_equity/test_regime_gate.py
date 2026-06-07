"""Unit tests for the regime/sentiment gate (FNG→VIX replacement)."""

from __future__ import annotations

import datetime as dt

import pytest

from regime_gate import RegimeGate


def _write_csv(tmp_path, rows):
    p = tmp_path / "regime.csv"
    lines = ["date,value"] + [f"{d},{v}" for d, v in rows]
    p.write_text("\n".join(lines))
    return str(p)


def test_disabled_when_no_csv_allows_everything():
    g = RegimeGate(csv_path=None)
    assert g.enabled is False
    assert g.allow(dt.date(2024, 1, 1)) is True


def test_block_above_threshold(tmp_path):
    csv = _write_csv(tmp_path, [("2024-01-01", 85), ("2024-01-02", 70)])
    g = RegimeGate(csv_path=csv, threshold=80, mode="block_above")
    assert g.allow(dt.date(2024, 1, 1)) is False  # 85 >= 80 → blocked
    assert g.allow(dt.date(2024, 1, 2)) is True  # 70 < 80 → allowed


def test_block_below_threshold(tmp_path):
    # e.g. "only trade when VIX is above X" style gate
    csv = _write_csv(tmp_path, [("2024-01-01", 12), ("2024-01-02", 25)])
    g = RegimeGate(csv_path=csv, threshold=20, mode="block_below")
    assert g.allow(dt.date(2024, 1, 1)) is False  # 12 <= 20 → blocked
    assert g.allow(dt.date(2024, 1, 2)) is True  # 25 > 20 → allowed


def test_missing_date_uses_default(tmp_path):
    csv = _write_csv(tmp_path, [("2024-01-01", 85)])
    g = RegimeGate(csv_path=csv, threshold=80, mode="block_above", default_value=50)
    assert g.allow(dt.date(2030, 6, 1)) is True  # default 50 < 80 → allowed


def test_invalid_mode_raises():
    with pytest.raises(ValueError):
        RegimeGate(csv_path=None, mode="nonsense")


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        RegimeGate(csv_path=str(tmp_path / "nope.csv"))
