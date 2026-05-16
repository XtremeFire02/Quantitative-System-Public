"""Tests for the paper broker — open/close trades against an in-memory SQLite DB."""
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, Trade, EquityCurve, SystemLog
from app.trading.paper_broker import (
    open_trade, close_trade, get_open_trade, get_all_open_trades, count_open_trades,
)

MKT = "BTCUSDT"
STRAT = "N3_DVOL_LONG"
MKT2 = "ETHUSDT"
STRAT2 = "FUNDING_CARRY"


# ── Test DB fixture ───────────────────────────────────────────────────────────

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(EquityCurve(
        timestamp=datetime.now(timezone.utc),
        equity=10000.0,
        realised_pnl=0.0,
        unrealised_pnl=0.0,
        drawdown=0.0,
    ))
    session.commit()
    yield session
    session.close()


def _open(db, market=MKT, strategy_name=STRAT, side="long",
          entry_price=50000.0, hold_hours=24,
          entry_dvol=56.0, entry_n3_z=1.2, entry_reason=""):
    return open_trade(
        db, market=market, strategy_name=strategy_name, side=side,
        entry_price=entry_price, hold_hours=hold_hours,
        entry_dvol=entry_dvol, entry_n3_z=entry_n3_z, entry_reason=entry_reason,
    )


# ── open_trade ────────────────────────────────────────────────────────────────

def test_open_trade_creates_trade_record(db):
    trade = _open(db)
    assert trade.id is not None
    assert trade.status == "open"
    assert trade.side == "long"
    assert trade.market == MKT
    assert trade.strategy_name == STRAT
    assert trade.entry_price == 50000.0
    assert trade.entry_dvol == 56.0
    assert trade.entry_n3_z == pytest.approx(1.2)


def test_open_trade_stores_entry_reason(db):
    reason = "signal conditions met: z = 1.200, vol_index = 56.0"
    trade = _open(db, entry_reason=reason)
    assert trade.entry_reason == reason


def test_open_trade_sets_planned_exit_from_hold_hours(db):
    before = datetime.now(timezone.utc)
    trade = _open(db, hold_hours=24)
    after = datetime.now(timezone.utc)

    planned = trade.planned_exit_timestamp
    if planned.tzinfo is None:
        planned = planned.replace(tzinfo=timezone.utc)

    assert (before + timedelta(hours=23, minutes=59)) <= planned
    assert planned <= (after + timedelta(hours=24, minutes=1))


def test_open_trade_hold_hours_respected_for_8h(db):
    before = datetime.now(timezone.utc)
    trade = _open(db, strategy_name="FUNDING_CARRY", hold_hours=8)
    after = datetime.now(timezone.utc)

    planned = trade.planned_exit_timestamp
    if planned.tzinfo is None:
        planned = planned.replace(tzinfo=timezone.utc)

    assert (before + timedelta(hours=7, minutes=59)) <= planned
    assert planned <= (after + timedelta(hours=8, minutes=1))


def test_open_trade_logs_to_system_log(db):
    _open(db)
    logs = db.query(SystemLog).all()
    assert any("Opened" in (log.message or "") for log in logs)


def test_two_different_pairs_can_hold_positions_simultaneously(db):
    _open(db, market=MKT, strategy_name=STRAT)
    _open(db, market=MKT2, strategy_name=STRAT2)
    assert count_open_trades(db, MKT, STRAT) == 1
    assert count_open_trades(db, MKT2, STRAT2) == 1
    assert len(get_all_open_trades(db)) == 2


# ── get_open_trade / count_open_trades ────────────────────────────────────────

def test_get_open_trade_returns_none_when_no_trade(db):
    assert get_open_trade(db, MKT, STRAT) is None


def test_get_open_trade_returns_open_trade(db):
    _open(db)
    result = get_open_trade(db, MKT, STRAT)
    assert result is not None
    assert result.status == "open"


def test_get_open_trade_is_isolated_by_market_and_strategy(db):
    _open(db, market=MKT, strategy_name=STRAT)
    assert get_open_trade(db, MKT2, STRAT2) is None


def test_count_open_trades_zero_initially(db):
    assert count_open_trades(db, MKT, STRAT) == 0


def test_count_open_trades_one_after_open(db):
    _open(db)
    assert count_open_trades(db, MKT, STRAT) == 1


def test_count_open_trades_isolated_per_pair(db):
    _open(db, market=MKT, strategy_name=STRAT)
    assert count_open_trades(db, MKT2, STRAT2) == 0


# ── close_trade ───────────────────────────────────────────────────────────────

def test_close_trade_sets_status_to_closed(db):
    trade = _open(db)
    closed = close_trade(db, trade, exit_price=51000.0, funding_rates=[], exit_reason="time_exit_24h")
    assert closed.status == "closed"


def test_close_trade_records_exit_price(db):
    trade = _open(db)
    closed = close_trade(db, trade, exit_price=51000.0, funding_rates=[])
    assert closed.exit_price == 51000.0


def test_close_trade_records_net_pnl(db):
    trade = _open(db)
    closed = close_trade(db, trade, exit_price=51000.0, funding_rates=[])
    assert closed.net_pnl is not None
    assert closed.net_pnl_bp is not None
    assert closed.net_pnl_bp == pytest.approx(closed.net_pnl * 10000, rel=1e-6)


def test_close_trade_positive_pnl_on_rising_price(db):
    trade = _open(db)
    closed = close_trade(db, trade, exit_price=52000.0, funding_rates=[])
    assert closed.net_pnl > 0


def test_close_trade_negative_pnl_on_falling_price(db):
    trade = _open(db)
    closed = close_trade(db, trade, exit_price=48000.0, funding_rates=[])
    assert closed.net_pnl < 0


def test_close_trade_records_exit_reason(db):
    trade = _open(db)
    closed = close_trade(db, trade, exit_price=51000.0, funding_rates=[], exit_reason="time_exit_24h")
    assert closed.exit_reason == "time_exit_24h"


def test_close_trade_updates_equity_curve(db):
    initial_count = db.query(EquityCurve).count()
    trade = _open(db)
    close_trade(db, trade, exit_price=51000.0, funding_rates=[])
    assert db.query(EquityCurve).count() == initial_count + 1


def test_close_trade_equity_increases_on_win(db):
    trade = _open(db)
    close_trade(db, trade, exit_price=52000.0, funding_rates=[])
    rows = db.query(EquityCurve).order_by(EquityCurve.id.asc()).all()
    assert rows[-1].equity > rows[0].equity


def test_can_open_new_trade_after_close(db):
    trade = _open(db)
    close_trade(db, trade, exit_price=51000.0, funding_rates=[])
    assert count_open_trades(db, MKT, STRAT) == 0
    trade2 = _open(db, entry_price=51000.0, entry_dvol=58.0, entry_n3_z=1.4)
    assert trade2.status == "open"
    assert count_open_trades(db, MKT, STRAT) == 1


def test_get_all_open_trades_empty_initially(db):
    assert get_all_open_trades(db) == []


def test_get_all_open_trades_returns_all(db):
    _open(db, market=MKT, strategy_name=STRAT)
    _open(db, market=MKT2, strategy_name=STRAT2)
    all_trades = get_all_open_trades(db)
    assert len(all_trades) == 2
    markets = {t.market for t in all_trades}
    assert MKT in markets and MKT2 in markets
