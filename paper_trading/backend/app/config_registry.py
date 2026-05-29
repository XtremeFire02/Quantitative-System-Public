"""
Registry of all markets and strategies available in the paper trading system.

Source-of-truth ownership
-------------------------
  AVAILABLE_MARKETS   — derived from markets.py REGISTRY (single source of truth).
                        Add a new market there; it appears here automatically.
                        UI-only fields (icon) are defined in _MARKET_ICONS below.

  AVAILABLE_STRATEGIES — static UI catalog. Execution parameters (thresholds,
                         hold periods) live in app/signals/<name>_signal.py.
                         Lifecycle status (shadow/validated/killed) is authoritative
                         in the StrategyStatus DB table; the "status" field here is
                         the initial seed value only.
"""
from app.markets import REGISTRY as _MARKET_REGISTRY

_EXCHANGE_DISPLAY = {
    "binance": "Binance USDT-M",
}

_MARKET_ICONS: dict[str, str] = {
    "BTC": "₿",
    "ETH": "Ξ",
    "SOL": "◎",
    "BNB": "B",
}

def _build_available_markets() -> dict:
    out: dict = {}
    for market in _MARKET_REGISTRY.values():
        symbol = market.symbol   # e.g. "BTCUSDT"
        out[symbol] = {
            "display_name": f"{market.base_currency}/{market.quote_currency} Perpetual",
            "exchange": _EXCHANGE_DISPLAY.get(market.exchange, market.exchange),
            "base_asset": market.base_currency,
            "requires_dvol": market.has_dvol,
            "icon": _MARKET_ICONS.get(market.base_currency, market.base_currency[:1]),
        }
    return out

AVAILABLE_MARKETS: dict = _build_available_markets()

AVAILABLE_STRATEGIES: dict = {
    # ── Official validated strategies ─────────────────────────────────────────
    "N3_DVOL_LONG": {
        "display_name": "N3 DVOL — Long Only",
        "description": "DVOL 30-day z-score signal with volatility-regime filter. Long-only, 24h hold. OOS 2024–2026: Sharpe +2.95, n=199 trades. Entry thresholds are private.",
        "compatible_markets": ["BTCUSDT"],
        "hold_hours": 24,
        "requires_dvol": True,
        "tags": ["mean-reversion", "vol-signal"],
        "status": "validated",
    },
    "N3_DVOL_LONGSHORT": {
        "display_name": "N3 DVOL — Long + Short",
        "description": "N3 DVOL with both long and short legs using symmetric z-score thresholds and DVOL regime filter. Short leg Sharpe +0.81 — lower edge than long-only.",
        "compatible_markets": ["BTCUSDT"],
        "hold_hours": 24,
        "requires_dvol": True,
        "tags": ["mean-reversion", "vol-signal"],
        "status": "validated",
    },

    # ── Shadow research variants ───────────────────────────────────────────────
    # Relaxed threshold variants accumulate more live observations for faster
    # forward IC estimation. Results must NOT be merged with the official N3 record.
    "N3_SHADOW_A": {
        "display_name": "N3 Shadow — Variant A",
        "description": "Shadow variant with relaxed z-score and DVOL thresholds. Fires more often than official N3. Shadow research only.",
        "compatible_markets": ["BTCUSDT"],
        "hold_hours": 24,
        "requires_dvol": True,
        "tags": ["shadow", "mean-reversion", "vol-signal"],
        "status": "shadow",
    },
    "N3_SHADOW_B": {
        "display_name": "N3 Shadow — Variant B",
        "description": "Shadow variant with same z-score threshold as official N3 but relaxed DVOL filter. Tests whether lower-fear days carry edge.",
        "compatible_markets": ["BTCUSDT"],
        "hold_hours": 24,
        "requires_dvol": True,
        "tags": ["shadow", "mean-reversion", "vol-signal"],
        "status": "shadow",
    },
    "N3_SHADOW_C": {
        "display_name": "N3 Shadow — Variant C",
        "description": "Shadow variant with both thresholds relaxed. Expected to show weaker edge based on backtest — confirms regime dependence in live data.",
        "compatible_markets": ["BTCUSDT"],
        "hold_hours": 24,
        "requires_dvol": True,
        "tags": ["shadow", "mean-reversion", "vol-signal"],
        "status": "shadow",
    },

    # ── P3 OI-Price Divergence shadow variants ────────────────────────────────
    "P3_OIPD_DD": {
        "display_name": "P3 OI-Price Divergence (DD)",
        "description": "OI-Price divergence, DD-regime (simultaneous price decline + OI contraction) with DVOL filter. Shadow research.",
        "compatible_markets": ["BTCUSDT"],
        "hold_hours": 24,
        "requires_dvol": True,
        "tags": ["shadow", "oi-divergence", "vol-signal"],
        "status": "shadow",
    },
    "P3_OIPD_DD_B": {
        "display_name": "P3 OI-Price Divergence (DD — Variant B)",
        "description": "P3 OI-Price divergence with elevated DVOL threshold sensitivity variant.",
        "compatible_markets": ["BTCUSDT"],
        "hold_hours": 24,
        "requires_dvol": True,
        "tags": ["shadow", "oi-divergence", "vol-signal"],
        "status": "shadow",
    },
    "P3_OIPD_DD_C": {
        "display_name": "P3 OI-Price Divergence (DD — Variant C)",
        "description": "P3 OI-Price divergence with highest DVOL threshold sensitivity variant.",
        "compatible_markets": ["BTCUSDT"],
        "hold_hours": 24,
        "requires_dvol": True,
        "tags": ["shadow", "oi-divergence", "vol-signal"],
        "status": "shadow",
    },

    # ── Experimental (not kill-attempt validated) ─────────────────────────────
    "FUNDING_CARRY": {
        "display_name": "Funding Rate Carry",
        "description": "Short when funding rate is persistently elevated (longs overpaying carry). Not yet through the kill-attempt validation pipeline.",
        "compatible_markets": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
        "hold_hours": 8,
        "requires_dvol": False,
        "tags": ["carry", "funding"],
        "status": "experimental",
    },

    # ── Utility ───────────────────────────────────────────────────────────────
    "EXECUTION_TEST": {
        "display_name": "Execution Test Bot",
        "description": "Opens a paper LONG every Monday and holds 24h. Not alpha — tests that trade open/close/funding/PnL/frontend all work correctly during low-DVOL periods.",
        "compatible_markets": ["BTCUSDT"],
        "hold_hours": 24,
        "requires_dvol": False,
        "tags": ["utility", "test"],
        "status": "execution_test",
    },

    # ── Coming soon ───────────────────────────────────────────────────────────
    "CVD_DIVERGENCE": {
        "display_name": "CVD Divergence",
        "description": "Enter when cumulative volume delta diverges from short-term price trend. Requires a live WebSocket OFI feed — not yet implemented.",
        "compatible_markets": ["BTCUSDT", "ETHUSDT"],
        "hold_hours": 1,
        "requires_dvol": False,
        "tags": ["order-flow", "divergence"],
        "status": "coming_soon",
    },
}
