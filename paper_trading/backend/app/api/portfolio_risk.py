"""
Portfolio risk dashboard API.

GET /api/risk/state  — current portfolio exposure + limit usage
GET /api/risk/limits — the configured hard limits
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import (
    PORTFOLIO_MAX_DAILY_LOSS_BP,
    PORTFOLIO_MAX_OPEN_POSITIONS,
    PORTFOLIO_MAX_SAME_MARKET,
    PORTFOLIO_MAX_STRATEGY_DD_PCT,
)
from app.database import get_db
from app.trading.portfolio_risk import get_portfolio_state

router = APIRouter()


@router.get("/risk/state")
def risk_state(db: Session = Depends(get_db)):
    return get_portfolio_state(db)


@router.get("/risk/limits")
def risk_limits():
    return {
        "max_open_positions": PORTFOLIO_MAX_OPEN_POSITIONS,
        "max_same_market_positions": PORTFOLIO_MAX_SAME_MARKET,
        "max_daily_loss_bp": PORTFOLIO_MAX_DAILY_LOSS_BP,
        "max_strategy_drawdown_pct": PORTFOLIO_MAX_STRATEGY_DD_PCT,
        "description": {
            "max_open_positions": "Hard cap on concurrent open trades across all strategies",
            "max_same_market_positions": "Max concurrent trades in the same underlying market",
            "max_daily_loss_bp": "New entries blocked once today's closed PnL drops below this (bp)",
            "max_strategy_drawdown_pct": "Strategy paused when trailing-20-trade DD exceeds this",
        },
    }
