from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    text,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATABASE_URL

# SQLite needs check_same_thread=False; PostgreSQL uses connection pooling instead.
_is_sqlite = DATABASE_URL.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}
_engine_kwargs = (
    {}
    if _is_sqlite
    else {"pool_size": 5, "max_overflow": 10, "pool_pre_ping": True}
)

engine = create_engine(DATABASE_URL, connect_args=_connect_args, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class MarketData(Base):
    __tablename__ = "market_data"
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True)                  # e.g. "BTCUSDT"
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    price = Column(Float)
    mark_price = Column(Float)
    funding_rate = Column(Float)
    dvol = Column(Float)
    open_interest = Column(Float)
    price_event_time = Column(DateTime(timezone=True))   # exchange server timestamp for price
    dvol_event_time = Column(DateTime(timezone=True))    # exchange server timestamp for DVOL
    oi_event_time = Column(DateTime(timezone=True))      # exchange server timestamp for OI
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Signal(Base):
    __tablename__ = "signals"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    strategy_name = Column(String, nullable=False)
    market = Column(String, default="BTCUSDT")
    dvol = Column(Float)
    dvol_mean_30d = Column(Float)
    dvol_std_30d = Column(Float)
    n3_z = Column(Float)
    dvol_filter_pass = Column(Boolean)
    entry_signal = Column(Boolean)
    reason = Column(Text)
    signal_metadata = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, index=True)
    market = Column(String, default="BTCUSDT")
    strategy_name = Column(String, nullable=False)
    # Status lifecycle: open → closed | rejected (risk-blocked after signal fired)
    status = Column(String, default="open")
    side = Column(String, default="long")
    # Position sizing — notional USD determines execution impact and absolute P&L
    notional_usd = Column(Float, default=10000.0)
    entry_timestamp = Column(DateTime(timezone=True))
    entry_price = Column(Float)
    entry_dvol = Column(Float)
    entry_n3_z = Column(Float)
    # Execution quality at entry — from execution_sim, recorded for post-trade attribution
    entry_half_spread_bp = Column(Float, nullable=True)
    entry_impact_bp = Column(Float, nullable=True)
    entry_maker_prob = Column(Float, nullable=True)
    entry_quality_score = Column(Float, nullable=True)
    # Simulated fill — signal_price is the evaluation price; entry_price is the fill
    signal_price = Column(Float, nullable=True)       # price at signal evaluation
    fill_type = Column(String, nullable=True)         # "maker" or "taker"
    # Exit simulated fill — exit_signal_price is the raw market price at exit
    exit_signal_price = Column(Float, nullable=True)  # raw market price at exit
    # Execution quality at exit — from estimate_exit_execution, recorded for post-trade attribution
    exit_half_spread_bp = Column(Float, nullable=True)
    exit_impact_bp = Column(Float, nullable=True)
    exit_quality_score = Column(Float, nullable=True)
    planned_exit_timestamp = Column(DateTime(timezone=True))
    exit_timestamp = Column(DateTime(timezone=True), nullable=True)
    exit_price = Column(Float, nullable=True)
    gross_price_return = Column(Float, nullable=True)
    funding_pnl = Column(Float, nullable=True)
    fees = Column(Float, nullable=True)
    # Slippage: spread + market impact (from execution sim) — separate from exchange fees
    slippage = Column(Float, nullable=True)
    net_pnl = Column(Float, nullable=True)
    net_pnl_bp = Column(Float, nullable=True)
    exit_reason = Column(String, nullable=True)
    entry_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class EquityCurve(Base):
    __tablename__ = "equity_curve"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    equity = Column(Float, default=10000.0)
    realised_pnl = Column(Float, default=0.0)
    unrealised_pnl = Column(Float, default=0.0)
    drawdown = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class SystemLog(Base):
    __tablename__ = "system_logs"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    level = Column(String)
    component = Column(String)
    message = Column(Text)


class BotConfig(Base):
    __tablename__ = "bot_configs"
    id = Column(Integer, primary_key=True, index=True)
    market = Column(String, nullable=False)
    strategy_name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (UniqueConstraint("market", "strategy_name", name="uq_market_strategy"),)


class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True,
                       default=lambda: datetime.now(timezone.utc))
    category = Column(String, nullable=False)   # signal_fired|trade_closed|data_failed|scheduler_missed|risk_blocked
    title = Column(String, nullable=False)
    body = Column(Text)
    strategy = Column(String, nullable=True)
    market = Column(String, nullable=True)
    exposure = Column(Text, nullable=True)   # JSON blob: current exposure snapshot
    action_taken = Column(String, nullable=True)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class StrategyStatus(Base):
    __tablename__ = "strategy_status"
    id = Column(Integer, primary_key=True, index=True)
    strategy_name = Column(String, unique=True, nullable=False, index=True)
    status = Column(String, default="research")  # research|candidate|shadow|validated|paused|killed
    promoted_at = Column(DateTime(timezone=True), nullable=True)
    promoted_by = Column(String, nullable=True)   # "auto" | "manual:<user>"
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class ExperimentRun(Base):
    __tablename__ = "experiment_runs"
    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String, unique=True, nullable=False, index=True)   # e.g. "25_du_short_20260514"
    script_name = Column(String, nullable=True)
    strategy_name = Column(String, nullable=True, index=True)
    commit_hash = Column(String, nullable=True)
    data_range_start = Column(String, nullable=True)
    data_range_end = Column(String, nullable=True)
    parameters = Column(Text, nullable=True)    # JSON
    metrics = Column(Text, nullable=True)       # JSON
    verdict = Column(String, nullable=True)     # passed|failed|killed|pending
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Order(Base):
    """
    Persistent order record — one row per trade attempt.

    State machine: submitted → acknowledged → partially_filled → filled
                                             ↘ cancelled
                             ↘ rejected

    In paper trading all transitions fire synchronously. In a live adapter
    'submitted → acknowledged' and 'acknowledged → filled' would correspond
    to real exchange round-trip latency.
    """
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    order_ref = Column(String, unique=True, nullable=False, index=True)  # UUID
    run_ref = Column(String, nullable=True)    # optional job run identifier
    market = Column(String, nullable=False)
    strategy_name = Column(String, nullable=False)
    side = Column(String, nullable=False)       # "long" | "short"
    notional_usd = Column(Float, nullable=False)
    requested_price = Column(Float, nullable=True)
    status = Column(String, nullable=False, default="submitted")
    fill_quantity_pct = Column(Float, default=0.0)   # 0.0 – 1.0
    fill_price = Column(Float, nullable=True)
    fill_type = Column(String, nullable=True)          # "maker" | "taker"
    trade_id = Column(Integer, nullable=True)          # set on fill
    rejection_reason = Column(Text, nullable=True)
    exchange_ref = Column(String, nullable=True)       # exchange order ID (live only)
    order_type = Column(String, nullable=False, default="market")    # "market" | "limit" | "post_only"
    time_in_force = Column(String, nullable=False, default="IOC")   # "IOC" | "FOK" | "GTC"
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    filled_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    rejected_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)

    # SQLite-only migrations: PostgreSQL gets all columns from create_all above.
    # These ALTER TABLE statements are safe to run repeatedly on SQLite — each
    # is wrapped in a try/except so "column already exists" is silently skipped.
    if _is_sqlite:
        _migrations = [
            "ALTER TABLE trades ADD COLUMN entry_reason TEXT",
            "ALTER TABLE trades ADD COLUMN market TEXT DEFAULT 'BTCUSDT'",
            "ALTER TABLE signals ADD COLUMN market TEXT DEFAULT 'BTCUSDT'",
            "ALTER TABLE signals ADD COLUMN signal_metadata TEXT",
            # Alert structured fields (v2)
            "ALTER TABLE alerts ADD COLUMN strategy TEXT",
            "ALTER TABLE alerts ADD COLUMN market TEXT",
            "ALTER TABLE alerts ADD COLUMN exposure TEXT",
            "ALTER TABLE alerts ADD COLUMN action_taken TEXT",
            # MarketData base columns (v3a)
            "ALTER TABLE market_data ADD COLUMN price REAL",
            "ALTER TABLE market_data ADD COLUMN mark_price REAL",
            "ALTER TABLE market_data ADD COLUMN funding_rate REAL",
            "ALTER TABLE market_data ADD COLUMN dvol REAL",
            # MarketData feed-quality columns (v3)
            "ALTER TABLE market_data ADD COLUMN symbol TEXT",
            "ALTER TABLE market_data ADD COLUMN open_interest REAL",
            "ALTER TABLE market_data ADD COLUMN price_event_time DATETIME",
            "ALTER TABLE market_data ADD COLUMN dvol_event_time DATETIME",
            "ALTER TABLE market_data ADD COLUMN oi_event_time DATETIME",
            # Trade position sizing + execution quality columns (v4)
            "ALTER TABLE trades ADD COLUMN notional_usd REAL DEFAULT 10000.0",
            "ALTER TABLE trades ADD COLUMN entry_half_spread_bp REAL",
            "ALTER TABLE trades ADD COLUMN entry_impact_bp REAL",
            "ALTER TABLE trades ADD COLUMN entry_maker_prob REAL",
            "ALTER TABLE trades ADD COLUMN entry_quality_score REAL",
            # Simulated fill columns (v5)
            "ALTER TABLE trades ADD COLUMN signal_price REAL",
            "ALTER TABLE trades ADD COLUMN fill_type TEXT",
            # Exit simulated fill columns (v6)
            "ALTER TABLE trades ADD COLUMN exit_signal_price REAL",
            # Exit execution quality columns (v7)
            "ALTER TABLE trades ADD COLUMN exit_half_spread_bp REAL",
            "ALTER TABLE trades ADD COLUMN exit_impact_bp REAL",
            "ALTER TABLE trades ADD COLUMN exit_quality_score REAL",
        ]
        with engine.connect() as conn:
            for stmt in _migrations:
                try:
                    conn.execute(text(stmt))
                    conn.commit()
                except Exception:
                    pass  # Column already exists

    # Seed initial equity curve row if empty
    db = SessionLocal()
    try:
        if db.query(EquityCurve).count() == 0:
            db.add(EquityCurve(
                timestamp=datetime.now(timezone.utc),
                equity=10000.0,
                realised_pnl=0.0,
                unrealised_pnl=0.0,
                drawdown=0.0,
            ))
            db.commit()

        # Seed default bot config (BTCUSDT + N3_DVOL_LONG) if none exist
        if db.query(BotConfig).count() == 0:
            db.add(BotConfig(market="BTCUSDT", strategy_name="N3_DVOL_LONG", is_active=True))
            db.commit()

        # Idempotent: add P3 shadow config if not already present
        p3_exists = (
            db.query(BotConfig)
            .filter(BotConfig.market == "BTCUSDT", BotConfig.strategy_name == "P3_OIPD_DD")
            .first()
        )
        if not p3_exists:
            db.add(BotConfig(market="BTCUSDT", strategy_name="P3_OIPD_DD", is_active=True))
            db.commit()

        # Seed strategy promotion pipeline with known strategies
        _seed_strategy_statuses(db)
    finally:
        db.close()


def _seed_strategy_statuses(db) -> None:
    known = [
        ("N3_DVOL_LONG",    "validated"),
        ("P3_OIPD_DD",      "shadow"),
        ("P3_OIPD_DD_57",   "shadow"),
        ("P3_OIPD_DD_60",   "shadow"),
        ("DU_SHORT",        "killed"),
    ]
    for name, status in known:
        exists = db.query(StrategyStatus).filter(StrategyStatus.strategy_name == name).first()
        if not exists:
            db.add(StrategyStatus(
                strategy_name=name,
                status=status,
                promoted_by="auto",
                note="Seeded at init",
            ))
    db.commit()
