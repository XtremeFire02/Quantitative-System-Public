"""
Shared pytest fixtures for the paper_trading backend test suite.

The in-memory SQLite engine is patched into app.database BEFORE any
module-level import of models or sessions, so all ORM operations hit the
in-memory store rather than the on-disk production database.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Engine — module-scoped so the schema is created only once per test session
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
    """In-memory SQLite engine shared across all tests in a module."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    # Patch app.database before importing Base / models
    import app.database as db_module
    db_module.engine = eng
    db_module.SessionLocal = sessionmaker(bind=eng, autoflush=False, autocommit=False)

    from app.database import Base
    Base.metadata.create_all(bind=eng)

    yield eng

    Base.metadata.drop_all(bind=eng)


# ---------------------------------------------------------------------------
# db — function-scoped session that rolls back after every test
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(engine):
    """
    Fresh database session per test.

    Uses a savepoint so each test gets a clean slate without recreating tables.
    """
    import app.database as db_module
    # Re-bind SessionLocal to the shared engine in case module order differs
    db_module.engine = engine
    db_module.SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    connection = engine.connect()
    transaction = connection.begin()

    Session = sessionmaker(bind=connection, autoflush=False, autocommit=False)
    session = Session()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# seeded_db — like db but with a starting EquityCurve row (equity=10000.0)
# ---------------------------------------------------------------------------

@pytest.fixture()
def seeded_db(db):
    """db session pre-seeded with a single EquityCurve row (equity=10_000)."""
    from app.database import EquityCurve

    db.add(EquityCurve(
        timestamp=datetime.now(timezone.utc),
        equity=10_000.0,
        realised_pnl=0.0,
        unrealised_pnl=0.0,
        drawdown=0.0,
    ))
    db.flush()

    yield db
