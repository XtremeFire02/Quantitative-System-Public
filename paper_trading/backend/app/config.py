from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Database
DB_PATH = BASE_DIR / "paper_trading.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

# Strategy parameters — private; not included in this repository.
# The live evaluators that consume these constants are also private.
# See framework/costs.py for the canonical cost model.
MAKER_RT_COST = 0.0006   # 0.06% round-trip (mirrors framework.costs.MAKER)
ONE_WAY_COST  = 0.0003   # 0.03% per leg    (mirrors framework.costs.MAKER)

# API endpoints (public)
BINANCE_FAPI_BASE = "https://fapi.binance.com"
DERIBIT_BASE      = "https://www.deribit.com/api/v2/public"

# Scheduler (UTC times)
DAILY_JOB_HOUR_UTC          = 0   # 00:00 UTC — daily candle close
EXIT_CHECK_INTERVAL_MINUTES = 15

# Stale data threshold (minutes)
DATA_STALE_MINUTES = 120

# Minimum number of lookback days required before a signal can be evaluated
DVOL_LOOKBACK_DAYS = 30

# Portfolio risk limits
PORTFOLIO_MAX_OPEN_POSITIONS  = 3       # across all strategies
PORTFOLIO_MAX_SAME_MARKET     = 2       # per market (e.g. BTCUSDT)
PORTFOLIO_MAX_DAILY_LOSS_BP   = -500.0  # halt new entries if daily PnL <= this
PORTFOLIO_MAX_STRATEGY_DD_PCT = -0.20   # pause strategy if trailing-20-trade DD exceeds this
