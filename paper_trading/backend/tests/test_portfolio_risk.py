"""
Unit tests for portfolio-level risk checks.

Tests check_portfolio_risk() and get_portfolio_state() from
app.trading.portfolio_risk using an isolated in-memory SQLite DB.

Run:
  cd paper_trading/backend
  pytest tests/test_portfolio_risk.py -v
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.database import Trade

# ---------------------------------------------------------------------------
# Helper — insert Trade rows directly
# ---------------------------------------------------------------------------

def _add_trade(
    db,
    strategy_name: str = "N3_DVOL_LONG",
    market: str = "BTCUSDT",
    side: str = "long",
    status: str = "open",
    net_pnl_bp: float | None = None,
    notional_usd: float = 10_000.0,
    exit_timestamp: datetime | None = None,
) -> Trade:
    """Insert a Trade row directly and flush (no commit, so rollback works)."""
    now = datetime.now(timezone.utc)
    trade = Trade(
        market=market,
        strategy_name=strategy_name,
        status=status,
        side=side,
        notional_usd=notional_usd,
        entry_timestamp=now,
        entry_price=50_000.0,
        planned_exit_timestamp=now + timedelta(hours=24),
        exit_timestamp=exit_timestamp if exit_timestamp is not None else (now if status == "closed" else None),
        exit_price=51_000.0 if status == "closed" else None,
        net_pnl_bp=net_pnl_bp,
        net_pnl=(net_pnl_bp / 10_000.0) if net_pnl_bp is not None else None,
        fees=0.0006,
    )
    db.add(trade)
    db.flush()
    return trade


# ---------------------------------------------------------------------------
# check_portfolio_risk — passes cleanly on empty DB
# ---------------------------------------------------------------------------

def test_check_portfolio_risk_passes_on_empty_db(seeded_db):
    from app.trading.portfolio_risk import check_portfolio_risk

    result = check_portfolio_risk(seeded_db, "N3_DVOL_LONG", "BTCUSDT")

    assert result["allowed"] is True
    assert result["total_open"] == 0
    assert result["market_open"] == 0


# ---------------------------------------------------------------------------
# Total open position cap
# ---------------------------------------------------------------------------

def test_raises_when_total_open_reaches_cap(seeded_db, monkeypatch):
    """With cap=2, opening 2 trades should trigger PortfolioRiskBlocked on the next check."""
    from app.trading.portfolio_risk import PortfolioRiskBlocked, check_portfolio_risk

    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_OPEN_POSITIONS", 2)

    _add_trade(seeded_db, strategy_name="STRAT_A", market="BTCUSDT", status="open")
    _add_trade(seeded_db, strategy_name="STRAT_B", market="BTCUSDT", status="open")

    with pytest.raises(PortfolioRiskBlocked, match="position"):
        check_portfolio_risk(seeded_db, "STRAT_C", "BTCUSDT")


def test_passes_when_total_open_below_cap(seeded_db, monkeypatch):
    """With cap=3, opening 2 trades on different markets should still pass."""
    from app.trading.portfolio_risk import check_portfolio_risk

    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_OPEN_POSITIONS", 3)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_SAME_MARKET", 10)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_GROSS_NOTIONAL_USD", 0)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_DAILY_LOSS_BP", -500.0)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_CONSECUTIVE_LOSSES", 0)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_STRATEGY_DD_PCT", -0.20)

    _add_trade(seeded_db, strategy_name="STRAT_A", market="BTCUSDT", status="open")
    _add_trade(seeded_db, strategy_name="STRAT_B", market="ETHUSDT", status="open")

    result = check_portfolio_risk(seeded_db, "STRAT_C", "SOLUSDT")
    assert result["allowed"] is True


# ---------------------------------------------------------------------------
# Same-market concentration limit
# ---------------------------------------------------------------------------

def test_raises_when_same_market_concentration_exceeded(seeded_db, monkeypatch):
    """With same-market limit=1, a second BTCUSDT position blocks entry."""
    from app.trading.portfolio_risk import PortfolioRiskBlocked, check_portfolio_risk

    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_OPEN_POSITIONS", 10)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_SAME_MARKET", 1)

    _add_trade(seeded_db, strategy_name="STRAT_A", market="BTCUSDT", status="open")

    with pytest.raises(PortfolioRiskBlocked, match="BTCUSDT"):
        check_portfolio_risk(seeded_db, "STRAT_B", "BTCUSDT")


def test_different_market_passes_same_market_limit(seeded_db, monkeypatch):
    """Open BTCUSDT + ETHUSDT should pass a per-market limit of 1."""
    from app.trading.portfolio_risk import check_portfolio_risk

    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_OPEN_POSITIONS", 10)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_SAME_MARKET", 1)

    _add_trade(seeded_db, strategy_name="STRAT_A", market="BTCUSDT", status="open")

    # Checking for ETHUSDT should pass — different market
    result = check_portfolio_risk(seeded_db, "STRAT_B", "ETHUSDT")
    assert result["allowed"] is True


# ---------------------------------------------------------------------------
# Daily PnL loss limit
# ---------------------------------------------------------------------------

def test_raises_when_daily_pnl_hits_loss_limit(seeded_db, monkeypatch):
    """Daily PnL <= -500 bp triggers PortfolioRiskBlocked."""
    from app.trading.portfolio_risk import PortfolioRiskBlocked, check_portfolio_risk

    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_OPEN_POSITIONS", 10)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_SAME_MARKET", 10)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_DAILY_LOSS_BP", -500.0)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_GROSS_NOTIONAL_USD", 0)

    today = datetime.now(timezone.utc)
    _add_trade(
        seeded_db,
        strategy_name="N3_DVOL_LONG",
        market="BTCUSDT",
        status="closed",
        net_pnl_bp=-600.0,
        exit_timestamp=today,
    )

    with pytest.raises(PortfolioRiskBlocked, match="loss"):
        check_portfolio_risk(seeded_db, "N3_DVOL_LONG", "BTCUSDT")


def test_passes_when_daily_pnl_above_loss_limit(seeded_db, monkeypatch):
    """Daily PnL of -499 bp should pass the -500 bp limit."""
    from app.trading.portfolio_risk import check_portfolio_risk

    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_OPEN_POSITIONS", 10)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_SAME_MARKET", 10)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_DAILY_LOSS_BP", -500.0)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_GROSS_NOTIONAL_USD", 0)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_CONSECUTIVE_LOSSES", 0)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_STRATEGY_DD_PCT", -0.20)

    today = datetime.now(timezone.utc)
    _add_trade(
        seeded_db,
        strategy_name="N3_DVOL_LONG",
        market="BTCUSDT",
        status="closed",
        net_pnl_bp=-499.0,
        exit_timestamp=today,
    )

    result = check_portfolio_risk(seeded_db, "N3_DVOL_LONG", "BTCUSDT")
    assert result["allowed"] is True


def test_yesterday_losses_do_not_count_toward_daily_limit(seeded_db, monkeypatch):
    """A large loss from yesterday must not trigger today's loss limit."""
    from app.trading.portfolio_risk import check_portfolio_risk

    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_OPEN_POSITIONS", 10)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_SAME_MARKET", 10)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_DAILY_LOSS_BP", -500.0)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_GROSS_NOTIONAL_USD", 0)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_CONSECUTIVE_LOSSES", 0)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_STRATEGY_DD_PCT", -0.20)

    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    _add_trade(
        seeded_db,
        strategy_name="N3_DVOL_LONG",
        market="BTCUSDT",
        status="closed",
        net_pnl_bp=-1000.0,
        exit_timestamp=yesterday,
    )

    result = check_portfolio_risk(seeded_db, "N3_DVOL_LONG", "BTCUSDT")
    assert result["allowed"] is True


# ---------------------------------------------------------------------------
# Gross notional exposure limit
# ---------------------------------------------------------------------------

def test_raises_when_gross_notional_exceeded(seeded_db, monkeypatch):
    """Gross notional >= limit triggers PortfolioRiskBlocked."""
    from app.trading.portfolio_risk import PortfolioRiskBlocked, check_portfolio_risk

    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_OPEN_POSITIONS", 10)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_SAME_MARKET", 10)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_GROSS_NOTIONAL_USD", 15_000.0)
    monkeypatch.setattr("app.trading.portfolio_risk.POSITION_NOTIONAL_USD", 10_000.0)

    # Two trades × $10,000 = $20,000 >= $15,000 limit
    _add_trade(seeded_db, strategy_name="STRAT_A", market="BTCUSDT", notional_usd=10_000.0)
    _add_trade(seeded_db, strategy_name="STRAT_B", market="ETHUSDT", notional_usd=10_000.0)

    with pytest.raises(PortfolioRiskBlocked, match="notional"):
        check_portfolio_risk(seeded_db, "STRAT_C", "SOLUSDT")


def test_gross_notional_disabled_when_zero(seeded_db, monkeypatch):
    """PORTFOLIO_MAX_GROSS_NOTIONAL_USD=0 means the notional check is disabled."""
    from app.trading.portfolio_risk import check_portfolio_risk

    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_OPEN_POSITIONS", 10)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_SAME_MARKET", 10)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_GROSS_NOTIONAL_USD", 0)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_DAILY_LOSS_BP", -500.0)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_CONSECUTIVE_LOSSES", 0)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_STRATEGY_DD_PCT", -0.20)

    # Large notional — should be ignored when limit is 0
    _add_trade(seeded_db, strategy_name="STRAT_A", market="BTCUSDT", notional_usd=1_000_000.0)

    result = check_portfolio_risk(seeded_db, "STRAT_B", "ETHUSDT")
    assert result["allowed"] is True


# ---------------------------------------------------------------------------
# Consecutive losses circuit breaker
# ---------------------------------------------------------------------------

def test_circuit_breaker_fires_after_n_consecutive_losses(seeded_db, monkeypatch):
    """After N consecutive losses the circuit breaker blocks further entries."""
    from app.trading.portfolio_risk import PortfolioRiskBlocked, check_portfolio_risk

    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_OPEN_POSITIONS", 10)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_SAME_MARKET", 10)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_GROSS_NOTIONAL_USD", 0)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_DAILY_LOSS_BP", -5000.0)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_CONSECUTIVE_LOSSES", 3)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_STRATEGY_DD_PCT", -0.20)

    strategy = "CB_TEST"
    now = datetime.now(timezone.utc)
    for i in range(3):
        _add_trade(
            seeded_db,
            strategy_name=strategy,
            market="BTCUSDT",
            status="closed",
            net_pnl_bp=-100.0,
            exit_timestamp=now - timedelta(hours=3 - i),
        )

    with pytest.raises(PortfolioRiskBlocked, match="Circuit breaker"):
        check_portfolio_risk(seeded_db, strategy, "BTCUSDT")


def test_circuit_breaker_resets_after_winning_trade(seeded_db, monkeypatch):
    """3 consecutive losses followed by 1 winner resets the circuit breaker."""
    from app.trading.portfolio_risk import check_portfolio_risk

    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_OPEN_POSITIONS", 10)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_SAME_MARKET", 10)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_GROSS_NOTIONAL_USD", 0)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_DAILY_LOSS_BP", -5000.0)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_CONSECUTIVE_LOSSES", 3)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_STRATEGY_DD_PCT", -0.20)

    strategy = "CB_RESET_TEST"
    now = datetime.now(timezone.utc)

    # 3 losses (oldest)
    for i in range(3):
        _add_trade(
            seeded_db,
            strategy_name=strategy,
            market="BTCUSDT",
            status="closed",
            net_pnl_bp=-100.0,
            exit_timestamp=now - timedelta(hours=5 - i),
        )
    # 1 winner (most recent — resets streak)
    _add_trade(
        seeded_db,
        strategy_name=strategy,
        market="BTCUSDT",
        status="closed",
        net_pnl_bp=50.0,
        exit_timestamp=now - timedelta(hours=1),
    )

    result = check_portfolio_risk(seeded_db, strategy, "BTCUSDT")
    assert result["allowed"] is True


def test_circuit_breaker_disabled_when_zero(seeded_db, monkeypatch):
    """PORTFOLIO_MAX_CONSECUTIVE_LOSSES=0 disables the circuit breaker.

    Disable the strategy drawdown check too (set to a very negative value so
    it never triggers) to isolate just the consecutive-losses logic.
    """
    from app.trading.portfolio_risk import check_portfolio_risk

    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_OPEN_POSITIONS", 10)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_SAME_MARKET", 10)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_GROSS_NOTIONAL_USD", 0)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_DAILY_LOSS_BP", -5000.0)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_CONSECUTIVE_LOSSES", 0)
    # Set strategy DD limit extremely negative so it never triggers
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_STRATEGY_DD_PCT", -99.0)

    strategy = "CB_DISABLED_TEST"
    now = datetime.now(timezone.utc)
    for i in range(10):
        _add_trade(
            seeded_db,
            strategy_name=strategy,
            market="BTCUSDT",
            status="closed",
            net_pnl_bp=-200.0,
            exit_timestamp=now - timedelta(hours=10 - i),
        )

    result = check_portfolio_risk(seeded_db, strategy, "BTCUSDT")
    assert result["allowed"] is True


# ---------------------------------------------------------------------------
# get_portfolio_state — correct counts
# ---------------------------------------------------------------------------

def test_get_portfolio_state_zero_trades(seeded_db):
    from app.trading.portfolio_risk import get_portfolio_state

    state = get_portfolio_state(seeded_db)

    assert state["total_open"] == 0
    assert state["daily_pnl_bp"] == 0.0
    assert state["open_by_strategy"] == {}
    assert state["open_by_market"] == {}
    assert state["positions"] == []


def test_get_portfolio_state_one_open_trade(seeded_db):
    from app.trading.portfolio_risk import get_portfolio_state

    _add_trade(seeded_db, strategy_name="N3_DVOL_LONG", market="BTCUSDT", status="open")

    state = get_portfolio_state(seeded_db)

    assert state["total_open"] == 1
    assert state["open_by_strategy"] == {"N3_DVOL_LONG": 1}
    assert state["open_by_market"] == {"BTCUSDT": 1}
    assert len(state["positions"]) == 1


def test_get_portfolio_state_two_open_trades(seeded_db):
    from app.trading.portfolio_risk import get_portfolio_state

    _add_trade(seeded_db, strategy_name="N3_DVOL_LONG", market="BTCUSDT", status="open")
    _add_trade(seeded_db, strategy_name="P3_OIPD_DD", market="BTCUSDT", status="open")

    state = get_portfolio_state(seeded_db)

    assert state["total_open"] == 2
    assert state["open_by_strategy"]["N3_DVOL_LONG"] == 1
    assert state["open_by_strategy"]["P3_OIPD_DD"] == 1
    assert state["open_by_market"]["BTCUSDT"] == 2
    assert len(state["positions"]) == 2


def test_get_portfolio_state_daily_pnl_from_today_closed_trades(seeded_db):
    """daily_pnl_bp is the sum of net_pnl_bp for today's closed trades."""
    from app.trading.portfolio_risk import get_portfolio_state

    today = datetime.now(timezone.utc)
    _add_trade(
        seeded_db,
        strategy_name="N3_DVOL_LONG",
        market="BTCUSDT",
        status="closed",
        net_pnl_bp=150.0,
        exit_timestamp=today,
    )
    _add_trade(
        seeded_db,
        strategy_name="N3_DVOL_LONG",
        market="BTCUSDT",
        status="closed",
        net_pnl_bp=-75.0,
        exit_timestamp=today,
    )

    state = get_portfolio_state(seeded_db)

    assert state["daily_pnl_bp"] == pytest.approx(75.0, abs=1e-6)


def test_get_portfolio_state_excludes_yesterday_from_daily_pnl(seeded_db):
    """Yesterday's closed trades must not appear in daily_pnl_bp."""
    from app.trading.portfolio_risk import get_portfolio_state

    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    _add_trade(
        seeded_db,
        strategy_name="N3_DVOL_LONG",
        market="BTCUSDT",
        status="closed",
        net_pnl_bp=-999.0,
        exit_timestamp=yesterday,
    )

    state = get_portfolio_state(seeded_db)

    assert state["daily_pnl_bp"] == pytest.approx(0.0, abs=1e-6)


def test_get_portfolio_state_gross_notional_sum(seeded_db):
    """gross_notional_usd sums notional across all open positions."""
    from app.trading.portfolio_risk import get_portfolio_state

    _add_trade(seeded_db, strategy_name="STRAT_A", market="BTCUSDT", notional_usd=10_000.0)
    _add_trade(seeded_db, strategy_name="STRAT_B", market="ETHUSDT", notional_usd=5_000.0)

    state = get_portfolio_state(seeded_db)

    assert state["gross_notional_usd"] == pytest.approx(15_000.0, abs=0.01)


def test_get_portfolio_state_limits_block_preserved(seeded_db, monkeypatch):
    """get_portfolio_state() returns limits from config constants."""
    from app.trading.portfolio_risk import get_portfolio_state

    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_OPEN_POSITIONS", 7)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_SAME_MARKET", 3)
    monkeypatch.setattr("app.trading.portfolio_risk.PORTFOLIO_MAX_DAILY_LOSS_BP", -300.0)

    state = get_portfolio_state(seeded_db)

    assert state["limits"]["max_open_positions"] == 7
    assert state["limits"]["max_same_market_positions"] == 3
    assert state["limits"]["max_daily_loss_bp"] == -300.0
