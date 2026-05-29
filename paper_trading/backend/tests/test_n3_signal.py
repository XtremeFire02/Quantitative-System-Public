"""
Unit tests for the N3 DVOL z-score signal evaluator.

Tests the pure synchronous `evaluate_signal()` function from app.signals.n3_signal.
All tests are deterministic — no external I/O is required.

Run:
  cd paper_trading/backend
  pytest tests/test_n3_signal.py -v
"""
from __future__ import annotations

import pytest

from app.signals.n3_signal import evaluate_signal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _eval(
    dvol: float = 60.0,
    dvol_mean_30d: float = 50.0,
    dvol_std_30d: float = 10.0,
    long_only: bool = True,
    n3z_threshold: float | None = None,
    dvol_threshold: float | None = None,
):
    """Convenience wrapper with sensible defaults."""
    return evaluate_signal(
        dvol=dvol,
        dvol_mean_30d=dvol_mean_30d,
        dvol_std_30d=dvol_std_30d,
        long_only=long_only,
        n3z_threshold=n3z_threshold,
        dvol_threshold=dvol_threshold,
    )


# ---------------------------------------------------------------------------
# Core signal conditions
# ---------------------------------------------------------------------------

def test_long_signal_fires_when_n3z_above_threshold_and_dvol_above_threshold():
    """Both z-score and DVOL filters pass → entry_signal=True, side='long'."""
    # n3_z = (60-50)/10 = 1.0 above threshold; dvol=60 above regime filter
    sig = _eval(dvol=60.0, dvol_mean_30d=50.0, dvol_std_30d=10.0,
                n3z_threshold=0.5, dvol_threshold=55.0)

    assert sig.entry_signal is True
    assert sig.side == "long"


def test_no_signal_when_dvol_below_threshold():
    """DVOL below regime filter blocks signal regardless of n3_z."""
    # n3_z = (53-40)/5 = 2.6 — z-score passes; dvol=53 < regime filter blocks
    sig = _eval(dvol=53.0, dvol_mean_30d=40.0, dvol_std_30d=5.0,
                n3z_threshold=0.5, dvol_threshold=55.0)

    assert sig.entry_signal is False


def test_no_signal_when_n3z_at_or_below_threshold_even_if_dvol_passes():
    """n3_z at or below threshold with DVOL above filter → no signal."""
    # n3_z = (60-55)/10 = 0.5 — exactly at threshold, not strictly greater
    sig = _eval(dvol=60.0, dvol_mean_30d=55.0, dvol_std_30d=10.0,
                n3z_threshold=0.5, dvol_threshold=55.0)

    assert sig.entry_signal is False


# ---------------------------------------------------------------------------
# Boundary: dvol threshold (explicit thresholds, tests the >= logic)
# ---------------------------------------------------------------------------

def test_dvol_exactly_at_threshold_fires():
    """Boundary: dvol == threshold (>= is inclusive) → fires when n3_z > threshold."""
    # n3_z = (65 - 40) / 10 = 2.5; dvol=65 >= 65 ✓
    sig = _eval(dvol=65.0, dvol_mean_30d=40.0, dvol_std_30d=10.0,
                n3z_threshold=0.5, dvol_threshold=65.0)

    assert sig.entry_signal is True


def test_dvol_one_below_threshold_does_not_fire():
    """Boundary: dvol just below threshold → regime filter blocks."""
    # n3_z high enough; dvol=64.9 < 65 → blocks
    sig = _eval(dvol=64.9, dvol_mean_30d=40.0, dvol_std_30d=10.0,
                n3z_threshold=0.5, dvol_threshold=65.0)

    assert sig.entry_signal is False


# ---------------------------------------------------------------------------
# Boundary: n3_z threshold (strict >)
# ---------------------------------------------------------------------------

def test_n3z_exactly_at_threshold_does_not_fire():
    """n3_z exactly at threshold does NOT fire (strict > comparison)."""
    # n3_z = 5.0/10 = 0.5 exactly at threshold=0.5 → not strictly greater
    sig = _eval(dvol=60.0, dvol_mean_30d=55.0, dvol_std_30d=10.0,
                n3z_threshold=0.5, dvol_threshold=55.0)

    assert sig.entry_signal is False
    assert sig.metadata["n3_z"] == pytest.approx(0.5, abs=1e-9)


def test_n3z_above_threshold_fires():
    """n3_z just above threshold → fires when dvol passes filter."""
    # n3_z = 5.1/10 = 0.51 > 0.5 ✓
    sig = _eval(dvol=60.0, dvol_mean_30d=54.9, dvol_std_30d=10.0,
                n3z_threshold=0.5, dvol_threshold=55.0)

    assert sig.entry_signal is True


# ---------------------------------------------------------------------------
# Zero dvol_std_30d — should not crash, n3_z = 0.0
# ---------------------------------------------------------------------------

def test_zero_dvol_std_30d_yields_n3z_zero_and_no_crash():
    """With dvol_std_30d=0, n3_z must be 0.0 (not a ZeroDivisionError)."""
    sig = _eval(dvol=60.0, dvol_mean_30d=50.0, dvol_std_30d=0.0,
                n3z_threshold=0.5, dvol_threshold=55.0)

    assert sig.n3_z == 0.0
    assert sig.metadata["n3_z"] == 0.0
    # n3_z=0.0 is not > threshold, so no entry
    assert sig.entry_signal is False


# ---------------------------------------------------------------------------
# Custom threshold overrides
# ---------------------------------------------------------------------------

def test_custom_n3z_threshold_overrides_default():
    """Explicit n3z_threshold=0.5 fires at n3_z=0.6 which is blocked at 0.9."""
    # dvol=60, mean=50, std=10  →  n3_z = 1.0  > 0.5 ✓  but NOT > 0.9
    sig_high_th = _eval(dvol=60.0, dvol_mean_30d=50.0, dvol_std_30d=10.0,
                        n3z_threshold=0.9, dvol_threshold=55.0)
    assert sig_high_th.entry_signal is False

    sig_low_th = _eval(dvol=60.0, dvol_mean_30d=50.0, dvol_std_30d=10.0,
                       n3z_threshold=0.5, dvol_threshold=55.0)
    assert sig_low_th.entry_signal is True


def test_custom_dvol_threshold_overrides_default():
    """Explicit dvol_threshold=65 blocks dvol=60 which passes at dvol_threshold=55."""
    # n3_z = (60-40)/10 = 2.0 — z-score passes both; dvol=60 blocked by threshold 65
    sig_high_th = _eval(dvol=60.0, dvol_mean_30d=40.0, dvol_std_30d=10.0,
                        n3z_threshold=0.5, dvol_threshold=65.0)
    assert sig_high_th.entry_signal is False

    sig_low_th = _eval(dvol=60.0, dvol_mean_30d=40.0, dvol_std_30d=10.0,
                       n3z_threshold=0.5, dvol_threshold=55.0)
    assert sig_low_th.entry_signal is True


# ---------------------------------------------------------------------------
# Long-only mode
# ---------------------------------------------------------------------------

def test_long_only_true_negative_n3z_never_fires():
    """long_only=True: very negative n3_z must never produce an entry signal."""
    # n3_z = -2.0 — below -threshold, but long_only=True suppresses short leg
    sig = _eval(dvol=60.0, dvol_mean_30d=80.0, dvol_std_30d=10.0,
                long_only=True, n3z_threshold=0.5, dvol_threshold=55.0)

    assert sig.entry_signal is False


def test_long_only_false_very_negative_n3z_fires_short():
    """long_only=False: n3_z below -threshold with DVOL above filter → short signal."""
    # n3_z = (60-80)/10 = -2.0 — well below -threshold
    sig = _eval(dvol=60.0, dvol_mean_30d=80.0, dvol_std_30d=10.0,
                long_only=False, n3z_threshold=0.5, dvol_threshold=55.0)

    assert sig.entry_signal is True
    assert sig.side == "short"


# ---------------------------------------------------------------------------
# hold_hours is frozen at 24
# ---------------------------------------------------------------------------

def test_hold_hours_is_always_24():
    """hold_hours must be exactly 24 in all outcomes."""
    sig_long = _eval(dvol=60.0, dvol_mean_30d=50.0, dvol_std_30d=10.0)
    sig_no_signal = _eval(dvol=50.0, dvol_mean_30d=50.0, dvol_std_30d=10.0)

    assert sig_long.hold_hours == 24
    assert sig_no_signal.hold_hours == 24


# ---------------------------------------------------------------------------
# Reason string content
# ---------------------------------------------------------------------------

def test_reason_contains_n3z_and_dvol_on_long_signal():
    """Reason string must mention N3z and DVOL when a long fires."""
    sig = _eval(dvol=60.0, dvol_mean_30d=50.0, dvol_std_30d=10.0)

    assert sig.entry_signal is True
    assert "N3z" in sig.reason
    assert "DVOL" in sig.reason


def test_reason_mentions_regime_filter_when_dvol_too_low():
    """When dvol < threshold, reason must reference the regime/DVOL filter."""
    sig = _eval(dvol=50.0, dvol_mean_30d=50.0, dvol_std_30d=10.0)

    assert sig.entry_signal is False
    assert "DVOL" in sig.reason


# ---------------------------------------------------------------------------
# Metadata keys
# ---------------------------------------------------------------------------

def test_metadata_has_required_keys():
    """metadata dict must contain: n3_z, dvol, n3z_threshold, dvol_threshold."""
    sig = _eval(dvol=60.0, dvol_mean_30d=50.0, dvol_std_30d=10.0)

    required = {"n3_z", "dvol", "n3z_threshold", "dvol_threshold"}
    missing = required - set(sig.metadata)
    assert not missing, f"Missing metadata keys: {missing}"


def test_metadata_values_are_correct():
    """Spot-check that metadata values match what was computed."""
    # n3_z = (60 - 50) / 10 = 1.0
    sig = _eval(dvol=60.0, dvol_mean_30d=50.0, dvol_std_30d=10.0)

    assert sig.metadata["n3_z"] == pytest.approx(1.0, abs=1e-4)
    assert sig.metadata["dvol"] == pytest.approx(60.0, abs=1e-4)
