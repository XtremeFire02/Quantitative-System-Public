"""Tests for pre-trade risk checks."""
import pytest
from datetime import datetime, timezone, timedelta
from app.trading.risk import check_can_trade, RiskCheckFailed
from app.config import DVOL_LOOKBACK_DAYS, DATA_STALE_MINUTES

FRESH_TS = datetime.now(timezone.utc) - timedelta(minutes=5)
STALE_TS = datetime.now(timezone.utc) - timedelta(minutes=DATA_STALE_MINUTES + 60)
MIN_BARS = DVOL_LOOKBACK_DAYS * 24  # 720


def _pass(**kwargs):
    """Call check_can_trade with defaults and any overrides. Should not raise."""
    defaults = dict(
        price=50000.0,
        open_trade_count=0,
        dvol=55.0,
        n_dvol_bars=MIN_BARS,
        dvol_timestamp=FRESH_TS,
    )
    defaults.update(kwargs)
    check_can_trade(**defaults)


def _fail(**kwargs) -> str:
    """Call check_can_trade and return the exception message. Must raise."""
    with pytest.raises(RiskCheckFailed) as exc:
        _pass(**kwargs)
    return str(exc.value)


# ── Happy path ────────────────────────────────────────────────────────────────

def test_passes_with_valid_inputs():
    _pass()  # should not raise


# ── Price checks ─────────────────────────────────────────────────────────────

def test_fails_when_price_is_none():
    msg = _fail(price=None)
    assert "price" in msg.lower()


def test_fails_when_price_is_zero():
    msg = _fail(price=0.0)
    assert "price" in msg.lower()


def test_fails_when_price_is_negative():
    msg = _fail(price=-1.0)
    assert "price" in msg.lower()


# ── DVOL checks ───────────────────────────────────────────────────────────────

def test_passes_when_dvol_is_none():
    # dvol=None means the strategy does not require DVOL (e.g. FUNDING_CARRY).
    # The check is intentionally skipped — this must not raise.
    _pass(dvol=None, n_dvol_bars=None, dvol_timestamp=None)


def test_fails_when_dvol_is_zero():
    msg = _fail(dvol=0.0)
    assert "dvol" in msg.lower()


# ── History depth checks ──────────────────────────────────────────────────────

def test_fails_when_insufficient_dvol_bars():
    msg = _fail(n_dvol_bars=MIN_BARS - 1)
    assert "insufficient" in msg.lower() or "bars" in msg.lower()


def test_passes_with_exactly_min_bars():
    _pass(n_dvol_bars=MIN_BARS)  # should not raise


def test_passes_with_more_than_min_bars():
    _pass(n_dvol_bars=MIN_BARS + 100)  # should not raise


# ── Data staleness checks ────────────────────────────────────────────────────

def test_fails_when_dvol_data_is_stale():
    msg = _fail(dvol_timestamp=STALE_TS)
    assert "stale" in msg.lower()


def test_passes_with_fresh_data():
    _pass(dvol_timestamp=FRESH_TS)  # should not raise


# ── Position limit checks ────────────────────────────────────────────────────

def test_fails_when_position_already_open():
    msg = _fail(open_trade_count=1)
    assert "position" in msg.lower() or "open" in msg.lower()


def test_fails_when_multiple_positions_open():
    msg = _fail(open_trade_count=2)
    assert "position" in msg.lower() or "open" in msg.lower()


def test_passes_when_no_open_positions():
    _pass(open_trade_count=0)  # should not raise
