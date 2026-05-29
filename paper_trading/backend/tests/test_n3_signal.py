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
    """n3_z > 0.75 AND dvol >= 54 → entry_signal=True, side='long'."""
    # dvol=60, mean=50, std=10  →  n3_z = (60-50)/10 = 1.0  > 0.75 ✓
    # dvol=60 >= 54 ✓
    sig = _eval(dvol=60.0, dvol_mean_30d=50.0, dvol_std_30d=10.0)

    assert sig.entry_signal is True
    assert sig.side == "long"


def test_no_signal_when_dvol_below_threshold():
    """dvol < 54 blocks signal regardless of n3_z value."""
    # dvol=53, mean=40, std=5  →  n3_z = (53-40)/5 = 2.6  > 0.75 ✓
    # but dvol=53 < 54 → regime filter blocks
    sig = _eval(dvol=53.0, dvol_mean_30d=40.0, dvol_std_30d=5.0)

    assert sig.entry_signal is False


def test_no_signal_when_n3z_at_or_below_threshold_even_if_dvol_passes():
    """n3_z <= 0.75 with dvol >= 54 → no signal."""
    # dvol=60, mean=52.5, std=10  →  n3_z = (60-52.5)/10 = 0.75  NOT > 0.75 (strict)
    sig = _eval(dvol=60.0, dvol_mean_30d=52.5, dvol_std_30d=10.0)

    assert sig.entry_signal is False


# ---------------------------------------------------------------------------
# Boundary: dvol threshold
# ---------------------------------------------------------------------------

def test_dvol_exactly_54_fires():
    """Boundary: dvol == 54.0 (>= threshold) should fire if n3_z > 0.75."""
    # n3_z = (54 - 40) / 10 = 1.4 > 0.75 ✓
    sig = _eval(dvol=54.0, dvol_mean_30d=40.0, dvol_std_30d=10.0)

    assert sig.entry_signal is True


def test_dvol_53_9_does_not_fire():
    """Boundary: dvol = 53.9 < 54 → regime filter blocks."""
    # n3_z = (53.9 - 40) / 10 = 1.39 > 0.75 ✓ but dvol fails filter
    sig = _eval(dvol=53.9, dvol_mean_30d=40.0, dvol_std_30d=10.0)

    assert sig.entry_signal is False


# ---------------------------------------------------------------------------
# Boundary: n3_z threshold (strict >)
# ---------------------------------------------------------------------------

def test_n3z_exactly_0_75_does_not_fire():
    """n3_z = 0.75 exactly does NOT fire (strict > comparison)."""
    # dvol=57.5, mean=50, std=10  →  n3_z = 7.5/10 = 0.75  (not > 0.75)
    sig = _eval(dvol=57.5, dvol_mean_30d=50.0, dvol_std_30d=10.0)

    assert sig.entry_signal is False
    assert sig.metadata["n3_z"] == pytest.approx(0.75, abs=1e-9)


def test_n3z_0_76_fires():
    """n3_z = 0.76 > 0.75 → fires when dvol >= 54."""
    # dvol=57.6, mean=50, std=10  →  n3_z = 7.6/10 = 0.76  > 0.75 ✓
    sig = _eval(dvol=57.6, dvol_mean_30d=50.0, dvol_std_30d=10.0)

    assert sig.entry_signal is True


# ---------------------------------------------------------------------------
# Zero dvol_std_30d — should not crash, n3_z = 0.0
# ---------------------------------------------------------------------------

def test_zero_dvol_std_30d_yields_n3z_zero_and_no_crash():
    """With dvol_std_30d=0, n3_z must be 0.0 (not a ZeroDivisionError)."""
    sig = _eval(dvol=60.0, dvol_mean_30d=50.0, dvol_std_30d=0.0)

    assert sig.n3_z == 0.0
    assert sig.metadata["n3_z"] == 0.0
    # n3_z=0.0 is not > 0.75, so no entry even if dvol filter passes
    assert sig.entry_signal is False


# ---------------------------------------------------------------------------
# Custom threshold overrides
# ---------------------------------------------------------------------------

def test_custom_n3z_threshold_overrides_default():
    """n3z_threshold=0.5 fires at n3_z=0.6 which would be blocked at default 0.75."""
    # dvol=56, mean=50, std=10  →  n3_z = 0.6  > 0.5 ✓  but < 0.75 (default)
    sig_default = _eval(dvol=56.0, dvol_mean_30d=50.0, dvol_std_30d=10.0)
    assert sig_default.entry_signal is False

    sig_custom = _eval(dvol=56.0, dvol_mean_30d=50.0, dvol_std_30d=10.0, n3z_threshold=0.5)
    assert sig_custom.entry_signal is True
    assert sig_custom.metadata["n3z_threshold"] == 0.5


def test_custom_dvol_threshold_overrides_default():
    """dvol_threshold=57 blocks dvol=56 which would pass at default 54."""
    # n3_z = (56-40)/10 = 1.6 > 0.75 ✓, but dvol=56 < custom threshold 57
    sig = _eval(dvol=56.0, dvol_mean_30d=40.0, dvol_std_30d=10.0, dvol_threshold=57.0)

    assert sig.entry_signal is False
    assert sig.metadata["dvol_threshold"] == 57.0


# ---------------------------------------------------------------------------
# Long-only mode
# ---------------------------------------------------------------------------

def test_long_only_true_negative_n3z_never_fires():
    """long_only=True: very negative n3_z must never produce an entry signal."""
    # dvol=60, mean=80, std=10  →  n3_z = -2.0  <  -0.75  but long_only=True
    sig = _eval(dvol=60.0, dvol_mean_30d=80.0, dvol_std_30d=10.0, long_only=True)

    assert sig.entry_signal is False


def test_long_only_false_very_negative_n3z_fires_short():
    """long_only=False: n3_z < -0.75 with dvol >= 54 → fires a short signal."""
    # dvol=60, mean=80, std=10  →  n3_z = -2.0  <  -0.75 ✓
    sig = _eval(dvol=60.0, dvol_mean_30d=80.0, dvol_std_30d=10.0, long_only=False)

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
    assert sig.metadata["dvol_threshold"] == 54.0   # frozen default
    assert sig.metadata["n3z_threshold"] == 0.75    # frozen default
