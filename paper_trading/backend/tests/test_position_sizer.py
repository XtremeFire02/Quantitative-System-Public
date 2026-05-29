"""
Unit tests for the position sizing engine.

Tests compute_size() and _confidence_weight() from app.trading.position_sizer.
Uses monkeypatch to switch between fixed and vol_target modes by patching
module-level constants directly on the position_sizer module.

Run:
  cd paper_trading/backend
  pytest tests/test_position_sizer.py -v
"""
from __future__ import annotations

import pytest

from app.trading.position_sizer import SizingInput, _confidence_weight, compute_size

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inp(
    signal_strength: float = 1.0,
    asset_vol_ann: float = 0.50,
    available_capital: float = 100_000.0,
    strategy_name: str = "N3_DVOL_LONG",
) -> SizingInput:
    return SizingInput(
        signal_strength=signal_strength,
        asset_vol_ann=asset_vol_ann,
        available_capital=available_capital,
        strategy_name=strategy_name,
    )


# ---------------------------------------------------------------------------
# _confidence_weight unit tests (pure function, no monkeypatching needed)
# ---------------------------------------------------------------------------

def test_confidence_weight_zero_maps_to_half():
    """signal_strength=0.0 → weight=0.5 (minimum deployment)."""
    assert _confidence_weight(0.0) == pytest.approx(0.5, abs=1e-9)


def test_confidence_weight_one_maps_to_one():
    """signal_strength=1.0 → weight=1.0 (full deployment)."""
    assert _confidence_weight(1.0) == pytest.approx(1.0, abs=1e-9)


def test_confidence_weight_half_maps_to_three_quarters():
    """signal_strength=0.5 → weight=0.75."""
    assert _confidence_weight(0.5) == pytest.approx(0.75, abs=1e-9)


def test_confidence_weight_clamps_below_zero():
    """signal_strength < 0 is treated as 0 → weight=0.5."""
    assert _confidence_weight(-1.0) == pytest.approx(0.5, abs=1e-9)


def test_confidence_weight_clamps_above_one():
    """signal_strength > 1 is treated as 1 → weight=1.0."""
    assert _confidence_weight(2.0) == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Fixed mode
# ---------------------------------------------------------------------------

def test_fixed_mode_returns_position_notional_usd(monkeypatch):
    """In fixed mode, notional_usd always equals POSITION_NOTIONAL_USD."""
    import app.trading.position_sizer as sizer

    monkeypatch.setattr(sizer, "POSITION_SIZING_MODE", "fixed")
    monkeypatch.setattr(sizer, "POSITION_NOTIONAL_USD", 10_000.0)

    out = compute_size(_inp(signal_strength=0.5, asset_vol_ann=0.80))

    assert out.notional_usd == pytest.approx(10_000.0, abs=0.01)


def test_fixed_mode_ignores_signal_strength(monkeypatch):
    """Signal strength has no effect in fixed mode."""
    import app.trading.position_sizer as sizer

    monkeypatch.setattr(sizer, "POSITION_SIZING_MODE", "fixed")
    monkeypatch.setattr(sizer, "POSITION_NOTIONAL_USD", 10_000.0)

    out_low = compute_size(_inp(signal_strength=0.0))
    out_high = compute_size(_inp(signal_strength=1.0))

    assert out_low.notional_usd == out_high.notional_usd


def test_fixed_mode_ignores_asset_vol(monkeypatch):
    """Asset volatility has no effect in fixed mode."""
    import app.trading.position_sizer as sizer

    monkeypatch.setattr(sizer, "POSITION_SIZING_MODE", "fixed")
    monkeypatch.setattr(sizer, "POSITION_NOTIONAL_USD", 10_000.0)

    out_low_vol = compute_size(_inp(asset_vol_ann=0.10))
    out_high_vol = compute_size(_inp(asset_vol_ann=2.00))

    assert out_low_vol.notional_usd == out_high_vol.notional_usd


def test_fixed_mode_output_fields(monkeypatch):
    """Fixed mode output must have specific field values."""
    import app.trading.position_sizer as sizer

    monkeypatch.setattr(sizer, "POSITION_SIZING_MODE", "fixed")
    monkeypatch.setattr(sizer, "POSITION_NOTIONAL_USD", 10_000.0)

    out = compute_size(_inp())

    assert out.vol_target_raw is None
    assert out.signal_weight == pytest.approx(1.0, abs=1e-9)
    assert out.concentration_cap_applied is False
    assert out.min_max_clipped is False
    assert out.sizing_mode == "fixed"


# ---------------------------------------------------------------------------
# Vol-target mode — raw sizing formula
# ---------------------------------------------------------------------------

def test_vol_target_raw_notional_formula(monkeypatch):
    """
    raw_notional = (VOL_TARGET / asset_vol_ann) × capital
    With VOL_TARGET=0.10, capital=100_000, asset_vol=0.50:
        raw = (0.10 / 0.50) × 100_000 = 20_000
    signal_strength=1.0 → weight=1.0 → final = 20_000
    (No concentration cap: 20_000 < 25_000 = 0.25 × 100_000)
    """
    import app.trading.position_sizer as sizer

    monkeypatch.setattr(sizer, "POSITION_SIZING_MODE", "vol_target")
    monkeypatch.setattr(sizer, "PORTFOLIO_VOL_TARGET", 0.10)
    monkeypatch.setattr(sizer, "POSITION_CONCENTRATION_CAP", 0.25)
    monkeypatch.setattr(sizer, "POSITION_MIN_USD", 1_000.0)
    monkeypatch.setattr(sizer, "POSITION_MAX_USD", 100_000.0)

    out = compute_size(_inp(signal_strength=1.0, asset_vol_ann=0.50, available_capital=100_000.0))

    assert out.vol_target_raw == pytest.approx(20_000.0, abs=0.01)
    assert out.notional_usd == pytest.approx(20_000.0, abs=0.01)
    assert out.sizing_mode == "vol_target"


def test_vol_target_signal_strength_zero_applies_half_weight(monkeypatch):
    """
    signal_strength=0.0 → weight=0.5.
    raw = 20_000 × 0.5 = 10_000 (within min/max/cap)
    """
    import app.trading.position_sizer as sizer

    monkeypatch.setattr(sizer, "POSITION_SIZING_MODE", "vol_target")
    monkeypatch.setattr(sizer, "PORTFOLIO_VOL_TARGET", 0.10)
    monkeypatch.setattr(sizer, "POSITION_CONCENTRATION_CAP", 0.25)
    monkeypatch.setattr(sizer, "POSITION_MIN_USD", 1_000.0)
    monkeypatch.setattr(sizer, "POSITION_MAX_USD", 100_000.0)

    out = compute_size(_inp(signal_strength=0.0, asset_vol_ann=0.50, available_capital=100_000.0))

    assert out.signal_weight == pytest.approx(0.5, abs=1e-4)
    assert out.notional_usd == pytest.approx(10_000.0, abs=0.01)


def test_vol_target_signal_strength_one_applies_full_weight(monkeypatch):
    """signal_strength=1.0 → weight=1.0 → full raw notional."""
    import app.trading.position_sizer as sizer

    monkeypatch.setattr(sizer, "POSITION_SIZING_MODE", "vol_target")
    monkeypatch.setattr(sizer, "PORTFOLIO_VOL_TARGET", 0.10)
    monkeypatch.setattr(sizer, "POSITION_CONCENTRATION_CAP", 0.25)
    monkeypatch.setattr(sizer, "POSITION_MIN_USD", 1_000.0)
    monkeypatch.setattr(sizer, "POSITION_MAX_USD", 100_000.0)

    out = compute_size(_inp(signal_strength=1.0, asset_vol_ann=0.50, available_capital=100_000.0))

    assert out.signal_weight == pytest.approx(1.0, abs=1e-4)
    assert out.notional_usd == pytest.approx(20_000.0, abs=0.01)


# ---------------------------------------------------------------------------
# Vol-target mode — min/max clipping
# ---------------------------------------------------------------------------

def test_vol_target_respects_position_min_usd(monkeypatch):
    """
    High vol → very small raw notional → must be clamped up to POSITION_MIN_USD.
    VOL_TARGET=0.10, asset_vol=2.0, capital=10_000:
        raw = (0.10 / 2.0) × 10_000 = 500  < MIN_USD=1_000
    """
    import app.trading.position_sizer as sizer

    monkeypatch.setattr(sizer, "POSITION_SIZING_MODE", "vol_target")
    monkeypatch.setattr(sizer, "PORTFOLIO_VOL_TARGET", 0.10)
    monkeypatch.setattr(sizer, "POSITION_CONCENTRATION_CAP", 0.25)
    monkeypatch.setattr(sizer, "POSITION_MIN_USD", 1_000.0)
    monkeypatch.setattr(sizer, "POSITION_MAX_USD", 100_000.0)

    out = compute_size(_inp(signal_strength=1.0, asset_vol_ann=2.0, available_capital=10_000.0))

    assert out.notional_usd == pytest.approx(1_000.0, abs=0.01)
    assert out.min_max_clipped is True


def test_vol_target_respects_position_max_usd(monkeypatch):
    """
    Very low vol → huge raw notional → must be clamped down to POSITION_MAX_USD.
    VOL_TARGET=0.10, asset_vol=0.001, capital=10_000_000:
        raw = (0.10 / 0.01) × 10_000_000 = 100_000_000 >> MAX_USD
    """
    import app.trading.position_sizer as sizer

    monkeypatch.setattr(sizer, "POSITION_SIZING_MODE", "vol_target")
    monkeypatch.setattr(sizer, "PORTFOLIO_VOL_TARGET", 0.10)
    monkeypatch.setattr(sizer, "POSITION_CONCENTRATION_CAP", 1.0)   # no cap interference
    monkeypatch.setattr(sizer, "POSITION_MIN_USD", 1_000.0)
    monkeypatch.setattr(sizer, "POSITION_MAX_USD", 100_000.0)

    out = compute_size(_inp(signal_strength=1.0, asset_vol_ann=0.001, available_capital=10_000_000.0))

    assert out.notional_usd == pytest.approx(100_000.0, abs=0.01)
    assert out.min_max_clipped is True


# ---------------------------------------------------------------------------
# Vol-target mode — concentration cap
# ---------------------------------------------------------------------------

def test_vol_target_respects_concentration_cap(monkeypatch):
    """
    raw > CONCENTRATION_CAP × capital → concentration_cap_applied=True.
    VOL_TARGET=0.10, asset_vol=0.05, capital=100_000, cap=0.10:
        raw = (0.10 / 0.05) × 100_000 = 200_000
        cap_limit = 0.10 × 100_000 = 10_000
    Final = clamp(10_000, MIN=1_000, MAX=100_000) = 10_000
    """
    import app.trading.position_sizer as sizer

    monkeypatch.setattr(sizer, "POSITION_SIZING_MODE", "vol_target")
    monkeypatch.setattr(sizer, "PORTFOLIO_VOL_TARGET", 0.10)
    monkeypatch.setattr(sizer, "POSITION_CONCENTRATION_CAP", 0.10)
    monkeypatch.setattr(sizer, "POSITION_MIN_USD", 1_000.0)
    monkeypatch.setattr(sizer, "POSITION_MAX_USD", 100_000.0)

    out = compute_size(_inp(signal_strength=1.0, asset_vol_ann=0.05, available_capital=100_000.0))

    assert out.concentration_cap_applied is True
    assert out.notional_usd == pytest.approx(10_000.0, abs=0.01)


def test_vol_target_cap_not_applied_when_within_limit(monkeypatch):
    """
    When raw notional < cap_limit, concentration_cap_applied must be False.
    raw = 20_000, cap = 0.25 × 100_000 = 25_000 → no cap.
    """
    import app.trading.position_sizer as sizer

    monkeypatch.setattr(sizer, "POSITION_SIZING_MODE", "vol_target")
    monkeypatch.setattr(sizer, "PORTFOLIO_VOL_TARGET", 0.10)
    monkeypatch.setattr(sizer, "POSITION_CONCENTRATION_CAP", 0.25)
    monkeypatch.setattr(sizer, "POSITION_MIN_USD", 1_000.0)
    monkeypatch.setattr(sizer, "POSITION_MAX_USD", 100_000.0)

    out = compute_size(_inp(signal_strength=1.0, asset_vol_ann=0.50, available_capital=100_000.0))

    assert out.concentration_cap_applied is False


# ---------------------------------------------------------------------------
# Vol-target mode — zero asset_vol floor
# ---------------------------------------------------------------------------

def test_vol_target_zero_asset_vol_uses_floor(monkeypatch):
    """
    asset_vol_ann=0.0 must not cause division by zero.
    The floor is 0.01.
    With VOL_TARGET=0.10, capital=100_000, floor=0.01, signal_strength=1.0:
        raw = (0.10 / 0.01) × 100_000 = 1_000_000
        cap_limit = 1.0 × 100_000 = 100_000  (cap=1.0 → full capital)
        weighted = 1_000_000 > 100_000 → capped to 100_000
        final = clamp(100_000, 1_000, 100_000) = 100_000
    """
    import app.trading.position_sizer as sizer

    monkeypatch.setattr(sizer, "POSITION_SIZING_MODE", "vol_target")
    monkeypatch.setattr(sizer, "PORTFOLIO_VOL_TARGET", 0.10)
    monkeypatch.setattr(sizer, "POSITION_CONCENTRATION_CAP", 1.0)   # cap = 100% of capital
    monkeypatch.setattr(sizer, "POSITION_MIN_USD", 1_000.0)
    monkeypatch.setattr(sizer, "POSITION_MAX_USD", 100_000.0)

    # Must not raise ZeroDivisionError
    out = compute_size(_inp(signal_strength=1.0, asset_vol_ann=0.0, available_capital=100_000.0))

    # raw uses floor 0.01: (0.10 / 0.01) × 100_000 = 1_000_000
    # → capped to cap_limit=100_000 → then clamped to MAX_USD=100_000
    assert out.notional_usd == pytest.approx(100_000.0, abs=0.01)
    assert out.sizing_mode == "vol_target"


# ---------------------------------------------------------------------------
# Vol-target mode — sizing_mode field on output
# ---------------------------------------------------------------------------

def test_vol_target_output_sizing_mode_field(monkeypatch):
    """SizingOutput.sizing_mode must equal 'vol_target' in vol_target mode."""
    import app.trading.position_sizer as sizer

    monkeypatch.setattr(sizer, "POSITION_SIZING_MODE", "vol_target")
    monkeypatch.setattr(sizer, "PORTFOLIO_VOL_TARGET", 0.10)
    monkeypatch.setattr(sizer, "POSITION_CONCENTRATION_CAP", 0.25)
    monkeypatch.setattr(sizer, "POSITION_MIN_USD", 1_000.0)
    monkeypatch.setattr(sizer, "POSITION_MAX_USD", 100_000.0)

    out = compute_size(_inp())

    assert out.sizing_mode == "vol_target"


# ---------------------------------------------------------------------------
# Non-"vol_target" string falls through to fixed mode
# ---------------------------------------------------------------------------

def test_unknown_sizing_mode_falls_back_to_fixed(monkeypatch):
    """Any POSITION_SIZING_MODE other than 'vol_target' uses fixed sizing."""
    import app.trading.position_sizer as sizer

    monkeypatch.setattr(sizer, "POSITION_SIZING_MODE", "unknown_mode")
    monkeypatch.setattr(sizer, "POSITION_NOTIONAL_USD", 10_000.0)

    out = compute_size(_inp())

    assert out.notional_usd == pytest.approx(10_000.0, abs=0.01)
    assert out.sizing_mode == "fixed"
