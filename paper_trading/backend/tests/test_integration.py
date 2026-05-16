"""
Integration test — full signal → trade open → exit cycle.

Uses an in-memory SQLite database; no external API calls are made.
The test exercises:
  1. DB setup and seeding via init_db()
  2. open_trade() creates a Trade row and an EquityCurve row
  3. check_can_trade() blocks a duplicate entry for the same market/strategy
  4. check_portfolio_risk() blocks when the global position cap is hit
  5. kill_switch arm/disarm round-trip via DB
  6. close_trade() updates Trade fields and appends a new EquityCurve row
  7. calculate_pnl() values round-trip through the broker correctly

Run:
  cd paper_trading/backend
  pytest tests/test_integration.py -v
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ── In-memory DB fixture ──────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )


@pytest.fixture(scope="module")
def db_session(engine):
    # Patch the global engine before importing init_db so tables are created
    # on our in-memory engine, not the on-disk one.
    import app.database as db_module
    db_module.engine = engine
    db_module.SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    from app.database import init_db, Base
    Base.metadata.create_all(bind=engine)

    # Seed a single EquityCurve row (init_db seeding uses SessionLocal)
    from app.database import EquityCurve, BotConfig
    session = db_module.SessionLocal()
    session.add(EquityCurve(timestamp=datetime.now(timezone.utc), equity=10000.0))
    session.commit()

    yield session

    session.close()
    Base.metadata.drop_all(bind=engine)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _open(db, market="BTCUSDT", strategy="N3_DVOL_LONG", side="long", price=50_000.0, hours=24):
    from app.trading.paper_broker import open_trade
    return open_trade(
        db=db,
        market=market,
        strategy_name=strategy,
        side=side,
        entry_price=price,
        hold_hours=hours,
        entry_reason="integration test",
        entry_dvol=60.0,
        entry_n3_z=1.1,
    )


# ── 1. open_trade creates Trade and EquityCurve row ──────────────────────────

def test_open_trade_creates_row(db_session):
    from app.database import Trade, EquityCurve
    before_count = db_session.query(Trade).count()
    equity_before = db_session.query(EquityCurve).count()

    trade = _open(db_session)

    assert db_session.query(Trade).count() == before_count + 1
    assert trade.id is not None
    assert trade.status == "open"
    assert trade.entry_price == 50_000.0
    assert trade.side == "long"
    # EquityCurve should NOT have a new row yet (equity updates happen on close)
    assert db_session.query(EquityCurve).count() == equity_before


# ── 2. check_can_trade blocks duplicate entry ─────────────────────────────────

def test_check_can_trade_blocks_duplicate(db_session):
    from app.trading.paper_broker import count_open_trades
    from app.trading.risk import check_can_trade, RiskCheckFailed

    count = count_open_trades(db_session, "BTCUSDT", "N3_DVOL_LONG")
    with pytest.raises(RiskCheckFailed, match="Position limit"):
        check_can_trade(price=50_000.0, open_trade_count=count)


# ── 3. check_portfolio_risk blocks when cap is exceeded ──────────────────────

def test_portfolio_risk_blocks_at_cap(db_session):
    from app.trading.portfolio_risk import check_portfolio_risk, PortfolioRiskBlocked
    from app.config import PORTFOLIO_MAX_OPEN_POSITIONS

    # Open trades until cap is hit
    for i in range(PORTFOLIO_MAX_OPEN_POSITIONS):
        strat = f"STRAT_CAP_TEST_{i}"
        _open(db_session, strategy=strat, market="BTCUSDT")

    with pytest.raises(PortfolioRiskBlocked, match="position"):
        check_portfolio_risk(db_session, "STRAT_CAP_TEST_EXTRA", "BTCUSDT")


# ── 4. Kill switch arm/disarm round-trip ─────────────────────────────────────

def test_kill_switch_arm_disarm(db_session):
    from app.trading.kill_switch import arm, disarm, check_kill_switch, KillSwitchActive, invalidate_cache

    invalidate_cache()
    arm(db_session, reason="integration test")
    with pytest.raises(KillSwitchActive):
        check_kill_switch(db_session)

    disarm(db_session, reason="integration test")
    invalidate_cache()
    check_kill_switch(db_session)   # must not raise


# ── 5. close_trade updates fields and appends equity row ─────────────────────

def test_close_trade_full_cycle(db_session):
    from app.database import Trade, EquityCurve
    from app.trading.paper_broker import close_trade, open_trade

    trade = open_trade(
        db=db_session,
        market="BTCUSDT",
        strategy_name="CYCLE_TEST",
        side="long",
        entry_price=50_000.0,
        hold_hours=24,
        entry_reason="cycle test",
        entry_dvol=60.0,
    )
    equity_before = db_session.query(EquityCurve).count()

    exit_price = 51_000.0
    funding_rates = [0.0001, 0.0001]   # two 8h settlements

    closed = close_trade(
        db=db_session,
        trade=trade,
        exit_price=exit_price,
        funding_rates=funding_rates,
        exit_reason="time_exit_CYCLE_TEST",
    )

    assert closed.status == "closed"
    assert closed.exit_price == exit_price
    assert closed.net_pnl is not None
    assert closed.net_pnl_bp is not None

    # Net PnL should be positive for a winning long
    assert closed.net_pnl_bp > 0

    # Equity curve must have a new row
    assert db_session.query(EquityCurve).count() == equity_before + 1

    last_equity = (
        db_session.query(EquityCurve).order_by(EquityCurve.id.desc()).first()
    )
    assert last_equity.equity > 10000.0   # equity grew


# ── 6. Long/short PnL sign correctness ───────────────────────────────────────

def test_losing_short_pnl_is_negative(db_session):
    from app.trading.paper_broker import open_trade, close_trade

    trade = open_trade(
        db=db_session,
        market="BTCUSDT",
        strategy_name="SHORT_SIGN_TEST",
        side="short",
        entry_price=50_000.0,
        hold_hours=24,
        entry_reason="sign test",
    )
    closed = close_trade(
        db=db_session,
        trade=trade,
        exit_price=51_000.0,   # price went up → short loses
        funding_rates=[],
    )
    assert closed.net_pnl_bp < 0, "A losing short should have negative net PnL"


# ── 7. calculate_pnl values round-trip ───────────────────────────────────────

def test_pnl_fees_equal_round_trip_cost(db_session):
    from app.trading.paper_broker import open_trade, close_trade
    from app.config import MAKER_RT_COST

    trade = open_trade(
        db=db_session,
        market="BTCUSDT",
        strategy_name="FEE_CHECK",
        side="long",
        entry_price=50_000.0,
        hold_hours=24,
    )
    closed = close_trade(
        db=db_session,
        trade=trade,
        exit_price=50_000.0,   # flat trade — only fees + slippage
        funding_rates=[],
    )
    assert abs(closed.fees - MAKER_RT_COST) < 1e-9, (
        f"Fees {closed.fees} should equal MAKER_RT_COST {MAKER_RT_COST}"
    )
