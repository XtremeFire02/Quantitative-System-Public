"""Unit tests for P3 OI-Price Divergence signal evaluator.

Run with:  cd paper_trading/backend && pytest tests/test_p3_signal.py -v

Tests verify that the live evaluator implements the frozen research rule:
  DD regime (dp<0 AND doi<0) AND DVOL >= 54 => LONG, 24h hold.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.signals.p3_oipd_signal import P3OIPDEvaluator, _classify

# ── Regime classifier unit tests ─────────────────────────────────────────────

def test_classify_dd():
    assert _classify(-0.01, -0.02) == "DD"

def test_classify_uu():
    assert _classify(0.01, 0.02) == "UU"

def test_classify_du():
    assert _classify(-0.01, 0.02) == "DU"

def test_classify_ud():
    assert _classify(0.01, -0.02) == "UD"

def test_classify_zero_price_is_not_negative():
    # dp == 0.0 is treated as non-negative: not DD/DU
    assert _classify(0.0, -0.01) == "UD"

def test_classify_zero_oi_is_not_negative():
    # doi == 0.0 is treated as non-negative: not DD/UD
    assert _classify(-0.01, 0.0) == "DU"

def test_classify_both_zero():
    assert _classify(0.0, 0.0) == "UU"

# ── Shared fixtures ───────────────────────────────────────────────────────────

_DVOL_58 = {
    "dvol": 58.0,
    "dvol_mean_30d": 52.0,
    "dvol_std_30d": 4.0,
    "n_bars_used": 720,
    "timestamp": datetime(2026, 5, 14, 0, 0, tzinfo=timezone.utc),
}
_DVOL_50 = {**_DVOL_58, "dvol": 50.0}
_DVOL_54 = {**_DVOL_58, "dvol": 54.0}


def _klines(price_prev: float, price_yest: float, price_today: float | None = None) -> list[dict]:
    """3-bar kline list: [completed_prev, completed_yest, in_progress_today]."""
    return [
        {"open_time": 0,          "close": price_prev},
        {"open_time": 86_400_000, "close": price_yest},
        {"open_time": 172_800_000, "close": price_today if price_today is not None else price_yest},
    ]


def _oi(oi_prev: float, oi_yest: float, oi_today: float | None = None) -> list[dict]:
    """3-bar OI list: [completed_prev, completed_yest, in_progress_today]."""
    return [
        {"timestamp": 0,          "open_interest": oi_prev,  "open_interest_value": oi_prev  * 60_000},
        {"timestamp": 86_400_000, "open_interest": oi_yest,  "open_interest_value": oi_yest  * 60_000},
        {"timestamp": 172_800_000,"open_interest": oi_today if oi_today is not None else oi_yest,
                                   "open_interest_value": (oi_today or oi_yest) * 60_000},
    ]


# ── Signal evaluation tests ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dd_dvol_above_threshold_fires_long():
    """Core happy-path: price down, OI down, DVOL 58 >= 54 → LONG."""
    ev = P3OIPDEvaluator()
    with (
        patch("app.signals.p3_oipd_signal.get_dvol_snapshot", new_callable=AsyncMock, return_value=_DVOL_58),
        patch("app.signals.p3_oipd_signal.fetch_klines_close", new_callable=AsyncMock,
              return_value=_klines(65_000, 63_000)),
        patch("app.signals.p3_oipd_signal.fetch_oi_history", new_callable=AsyncMock,
              return_value=_oi(50_000, 48_000)),
    ):
        sig = await ev.evaluate("BTCUSDT")

    assert sig.entry_signal is True
    assert sig.side == "long"
    assert sig.metadata["regime"] == "DD"


@pytest.mark.asyncio
async def test_du_regime_no_signal():
    """Price down, OI UP → DU regime → no trade."""
    ev = P3OIPDEvaluator()
    with (
        patch("app.signals.p3_oipd_signal.get_dvol_snapshot", new_callable=AsyncMock, return_value=_DVOL_58),
        patch("app.signals.p3_oipd_signal.fetch_klines_close", new_callable=AsyncMock,
              return_value=_klines(65_000, 63_000)),
        patch("app.signals.p3_oipd_signal.fetch_oi_history", new_callable=AsyncMock,
              return_value=_oi(48_000, 50_000)),
    ):
        sig = await ev.evaluate("BTCUSDT")

    assert sig.entry_signal is False
    assert sig.metadata["regime"] == "DU"


@pytest.mark.asyncio
async def test_ud_regime_no_signal():
    """Price UP, OI down → UD regime → no trade."""
    ev = P3OIPDEvaluator()
    with (
        patch("app.signals.p3_oipd_signal.get_dvol_snapshot", new_callable=AsyncMock, return_value=_DVOL_58),
        patch("app.signals.p3_oipd_signal.fetch_klines_close", new_callable=AsyncMock,
              return_value=_klines(63_000, 65_000)),
        patch("app.signals.p3_oipd_signal.fetch_oi_history", new_callable=AsyncMock,
              return_value=_oi(50_000, 48_000)),
    ):
        sig = await ev.evaluate("BTCUSDT")

    assert sig.entry_signal is False
    assert sig.metadata["regime"] == "UD"


@pytest.mark.asyncio
async def test_uu_regime_no_signal():
    """Price UP, OI UP → UU regime → no trade."""
    ev = P3OIPDEvaluator()
    with (
        patch("app.signals.p3_oipd_signal.get_dvol_snapshot", new_callable=AsyncMock, return_value=_DVOL_58),
        patch("app.signals.p3_oipd_signal.fetch_klines_close", new_callable=AsyncMock,
              return_value=_klines(63_000, 65_000)),
        patch("app.signals.p3_oipd_signal.fetch_oi_history", new_callable=AsyncMock,
              return_value=_oi(48_000, 50_000)),
    ):
        sig = await ev.evaluate("BTCUSDT")

    assert sig.entry_signal is False
    assert sig.metadata["regime"] == "UU"


@pytest.mark.asyncio
async def test_dvol_below_threshold_blocks_dd():
    """DD regime but DVOL 50 < 54 → no trade (regime filter)."""
    ev = P3OIPDEvaluator()
    with (
        patch("app.signals.p3_oipd_signal.get_dvol_snapshot", new_callable=AsyncMock, return_value=_DVOL_50),
        patch("app.signals.p3_oipd_signal.fetch_klines_close", new_callable=AsyncMock,
              return_value=_klines(65_000, 63_000)),
        patch("app.signals.p3_oipd_signal.fetch_oi_history", new_callable=AsyncMock,
              return_value=_oi(50_000, 48_000)),
    ):
        sig = await ev.evaluate("BTCUSDT")

    assert sig.entry_signal is False
    assert sig.metadata["regime"] == "DD"
    assert "DVOL" in sig.reason


@pytest.mark.asyncio
async def test_dvol_exactly_at_threshold_fires():
    """Boundary: DVOL == 54.0 (>= threshold) → should fire."""
    ev = P3OIPDEvaluator()
    with (
        patch("app.signals.p3_oipd_signal.get_dvol_snapshot", new_callable=AsyncMock, return_value=_DVOL_54),
        patch("app.signals.p3_oipd_signal.fetch_klines_close", new_callable=AsyncMock,
              return_value=_klines(65_000, 63_000)),
        patch("app.signals.p3_oipd_signal.fetch_oi_history", new_callable=AsyncMock,
              return_value=_oi(50_000, 48_000)),
    ):
        sig = await ev.evaluate("BTCUSDT")

    assert sig.entry_signal is True


@pytest.mark.asyncio
async def test_incomplete_bar_not_used():
    """In-progress bar (index 2) must NOT influence regime.

    Rows[0] and [1]: DD (price down, OI down).
    Row[2]: opposite direction (price up, OI up) — in-progress, must be skipped.
    Expected: still fires because classification uses rows[0] and [1] only.
    """
    ev = P3OIPDEvaluator()
    klines_data = _klines(65_000, 63_000, price_today=70_000)   # row[2] price UP
    oi_data     = _oi(50_000, 48_000, oi_today=60_000)           # row[2] OI UP
    with (
        patch("app.signals.p3_oipd_signal.get_dvol_snapshot", new_callable=AsyncMock, return_value=_DVOL_58),
        patch("app.signals.p3_oipd_signal.fetch_klines_close", new_callable=AsyncMock, return_value=klines_data),
        patch("app.signals.p3_oipd_signal.fetch_oi_history",   new_callable=AsyncMock, return_value=oi_data),
    ):
        sig = await ev.evaluate("BTCUSDT")

    assert sig.entry_signal is True, "In-progress bar incorrectly influenced regime"
    assert sig.metadata["regime"] == "DD"


@pytest.mark.asyncio
async def test_reason_contains_required_fields():
    """Reason string must record dp, doi, regime, and DVOL for the log."""
    ev = P3OIPDEvaluator()
    with (
        patch("app.signals.p3_oipd_signal.get_dvol_snapshot", new_callable=AsyncMock, return_value=_DVOL_58),
        patch("app.signals.p3_oipd_signal.fetch_klines_close", new_callable=AsyncMock,
              return_value=_klines(65_000, 63_000)),
        patch("app.signals.p3_oipd_signal.fetch_oi_history", new_callable=AsyncMock,
              return_value=_oi(50_000, 48_000)),
    ):
        sig = await ev.evaluate("BTCUSDT")

    assert "DD" in sig.reason
    assert "dp=" in sig.reason
    assert "doi=" in sig.reason
    assert "DVOL=" in sig.reason


@pytest.mark.asyncio
async def test_metadata_has_all_diagnostic_fields():
    """All fields needed for post-hoc analysis must be in signal_metadata."""
    ev = P3OIPDEvaluator()
    with (
        patch("app.signals.p3_oipd_signal.get_dvol_snapshot", new_callable=AsyncMock, return_value=_DVOL_58),
        patch("app.signals.p3_oipd_signal.fetch_klines_close", new_callable=AsyncMock,
              return_value=_klines(65_000, 63_000)),
        patch("app.signals.p3_oipd_signal.fetch_oi_history", new_callable=AsyncMock,
              return_value=_oi(50_000, 48_000)),
    ):
        sig = await ev.evaluate("BTCUSDT")

    required = {"regime", "dp", "doi", "price_prev", "price_yest",
                "oi_prev", "oi_yest", "dvol", "dvol_threshold", "dvol_mean_30d"}
    missing = required - set(sig.metadata)
    assert not missing, f"Missing metadata fields: {missing}"


@pytest.mark.asyncio
async def test_hold_hours_frozen_at_24():
    """hold_hours must be exactly 24 — frozen rule, must not drift."""
    ev = P3OIPDEvaluator()
    with (
        patch("app.signals.p3_oipd_signal.get_dvol_snapshot", new_callable=AsyncMock, return_value=_DVOL_58),
        patch("app.signals.p3_oipd_signal.fetch_klines_close", new_callable=AsyncMock,
              return_value=_klines(65_000, 63_000)),
        patch("app.signals.p3_oipd_signal.fetch_oi_history", new_callable=AsyncMock,
              return_value=_oi(50_000, 48_000)),
    ):
        sig = await ev.evaluate("BTCUSDT")

    assert sig.hold_hours == 24


@pytest.mark.asyncio
async def test_side_is_always_long():
    """P3_OIPD_DD is long-only — side must never be 'short'."""
    ev = P3OIPDEvaluator()
    # Test with no-signal case (UU regime)
    with (
        patch("app.signals.p3_oipd_signal.get_dvol_snapshot", new_callable=AsyncMock, return_value=_DVOL_58),
        patch("app.signals.p3_oipd_signal.fetch_klines_close", new_callable=AsyncMock,
              return_value=_klines(63_000, 65_000)),
        patch("app.signals.p3_oipd_signal.fetch_oi_history", new_callable=AsyncMock,
              return_value=_oi(48_000, 50_000)),
    ):
        sig = await ev.evaluate("BTCUSDT")

    assert sig.side == "long"
    assert sig.entry_signal is False


@pytest.mark.asyncio
async def test_custom_dvol_threshold():
    """dvol_threshold override works — P3_OIPD_DD_57 variant."""
    ev = P3OIPDEvaluator(strategy_name="P3_OIPD_DD_57", dvol_threshold=57.0)
    dvol_55 = {**_DVOL_58, "dvol": 55.0}   # below 57 → should not fire
    with (
        patch("app.signals.p3_oipd_signal.get_dvol_snapshot", new_callable=AsyncMock, return_value=dvol_55),
        patch("app.signals.p3_oipd_signal.fetch_klines_close", new_callable=AsyncMock,
              return_value=_klines(65_000, 63_000)),
        patch("app.signals.p3_oipd_signal.fetch_oi_history", new_callable=AsyncMock,
              return_value=_oi(50_000, 48_000)),
    ):
        sig = await ev.evaluate("BTCUSDT")

    assert sig.entry_signal is False
    assert sig.strategy_name == "P3_OIPD_DD_57"
