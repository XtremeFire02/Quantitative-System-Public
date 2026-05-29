import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Database ──────────────────────────────────────────────────────────────────
# Docker: set DATABASE_URL=sqlite:////app/data/paper_trading.db (volume path)
# Local:  defaults to BASE_DIR/paper_trading.db
_db_default = f"sqlite:///{BASE_DIR / 'paper_trading.db'}"
DATABASE_URL = os.getenv("DATABASE_URL", _db_default)

# ── Environment ───────────────────────────────────────────────────────────────
# development | paper_prod
ENV = os.getenv("ENV", "development")

# ── API authentication ────────────────────────────────────────────────────────
# Required on all write endpoints (kill switch, pipeline, manual job triggers).
# Empty string = auth disabled (development convenience).
# Generate for production: python -c "import secrets; print(secrets.token_hex(32))"
API_KEY = os.getenv("API_KEY", "")

# ── Strategy parameters (private) ─────────────────────────────────────────────
# Entry thresholds and frozen rule parameters are not included in this
# repository. The live signal evaluators load them from environment variables.
# See paper_trading/.env.example for the variable names.
HOLD_HOURS        = int(os.getenv("HOLD_HOURS",        "24"))
DVOL_LOOKBACK_DAYS = int(os.getenv("DVOL_LOOKBACK_DAYS", "30"))

# ── Cost model (mirrors framework/costs.py) ───────────────────────────────────
MAKER_RT_COST = 0.0006   # 0.06% round-trip (3 bp entry + 3 bp exit)
ONE_WAY_COST  = 0.0003   # 0.03% per leg

# ── Position sizing ───────────────────────────────────────────────────────────
POSITION_NOTIONAL_USD = float(os.getenv("POSITION_NOTIONAL_USD", "10000.0"))

# ── CORS ─────────────────────────────────────────────────────────────────────
_cors_raw = os.getenv("CORS_ORIGINS", "")
CORS_ORIGINS: list[str] = [o.strip() for o in _cors_raw.split(",") if o.strip()]

# ── External APIs ─────────────────────────────────────────────────────────────
BINANCE_FAPI_BASE = os.getenv("BINANCE_FAPI_BASE", "https://fapi.binance.com")
DERIBIT_BASE      = os.getenv("DERIBIT_BASE",      "https://www.deribit.com/api/v2/public")

# ── Scheduler ─────────────────────────────────────────────────────────────────
DAILY_JOB_HOUR_UTC          = int(os.getenv("DAILY_JOB_HOUR_UTC",          "0"))
EXIT_CHECK_INTERVAL_MINUTES = int(os.getenv("EXIT_CHECK_INTERVAL_MINUTES", "15"))

# ── Data staleness ────────────────────────────────────────────────────────────
DATA_STALE_MINUTES = int(os.getenv("DATA_STALE_MINUTES", "120"))

# ── Log retention ─────────────────────────────────────────────────────────────
LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "90"))

# ── Portfolio risk limits ─────────────────────────────────────────────────────
PORTFOLIO_MAX_OPEN_POSITIONS      = int(os.getenv("PORTFOLIO_MAX_OPEN_POSITIONS",      "3"))
PORTFOLIO_MAX_SAME_MARKET         = int(os.getenv("PORTFOLIO_MAX_SAME_MARKET",         "2"))
PORTFOLIO_MAX_DAILY_LOSS_BP       = float(os.getenv("PORTFOLIO_MAX_DAILY_LOSS_BP",     "-500.0"))
PORTFOLIO_MAX_STRATEGY_DD_PCT     = float(os.getenv("PORTFOLIO_MAX_STRATEGY_DD_PCT",   "-0.20"))
PORTFOLIO_MAX_CONSECUTIVE_LOSSES  = int(os.getenv("PORTFOLIO_MAX_CONSECUTIVE_LOSSES",  "4"))
PORTFOLIO_MAX_GROSS_NOTIONAL_USD  = float(os.getenv("PORTFOLIO_MAX_GROSS_NOTIONAL_USD","50000.0"))

# ── Position sizing engine ────────────────────────────────────────────────────
POSITION_SIZING_MODE       = os.getenv("POSITION_SIZING_MODE", "fixed")
PORTFOLIO_VOL_TARGET       = float(os.getenv("PORTFOLIO_VOL_TARGET",        "0.10"))
POSITION_CONCENTRATION_CAP = float(os.getenv("POSITION_CONCENTRATION_CAP", "0.25"))
POSITION_MIN_USD           = float(os.getenv("POSITION_MIN_USD",            "1000.0"))
POSITION_MAX_USD           = float(os.getenv("POSITION_MAX_USD",            "100000.0"))
