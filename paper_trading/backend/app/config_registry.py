"""Registry of all markets and strategies available in the paper trading system."""

AVAILABLE_MARKETS: dict = {
    "BTCUSDT": {
        "display_name": "BTC/USDT Perpetual",
        "exchange": "Binance USDT-M",
        "base_asset": "BTC",
        "requires_dvol": True,
        "icon": "₿",
    },
    "ETHUSDT": {
        "display_name": "ETH/USDT Perpetual",
        "exchange": "Binance USDT-M",
        "base_asset": "ETH",
        "requires_dvol": False,
        "icon": "Ξ",
    },
    "SOLUSDT": {
        "display_name": "SOL/USDT Perpetual",
        "exchange": "Binance USDT-M",
        "base_asset": "SOL",
        "requires_dvol": False,
        "icon": "◎",
    },
    "BNBUSDT": {
        "display_name": "BNB/USDT Perpetual",
        "exchange": "Binance USDT-M",
        "base_asset": "BNB",
        "requires_dvol": False,
        "icon": "B",
    },
}

AVAILABLE_STRATEGIES: dict = {
    # ── Official validated strategies (parameters private) ────────────────────
    "N3_DVOL_LONG": {
        "display_name": "N3 DVOL — Long Only",
        "description": "Validated volatility-regime long signal on BTCUSDT perpetual. Strategy parameters are private.",
        "compatible_markets": ["BTCUSDT"],
        "hold_hours": 24,
        "requires_dvol": True,
        "tags": ["mean-reversion", "vol-signal"],
        "status": "validated",
    },
    "N3_DVOL_LONGSHORT": {
        "display_name": "N3 DVOL — Long + Short",
        "description": "Long + short variant of N3 DVOL. Strategy parameters are private.",
        "compatible_markets": ["BTCUSDT"],
        "hold_hours": 24,
        "requires_dvol": True,
        "tags": ["mean-reversion", "vol-signal"],
        "status": "validated",
    },

    # ── Shadow research variants ───────────────────────────────────────────────
    "N3_SHADOW_050_51": {
        "display_name": "N3 Shadow — variant A",
        "description": "Shadow variant with relaxed thresholds. Fires more often than official. Shadow research only — do not compare to validated results.",
        "compatible_markets": ["BTCUSDT"],
        "hold_hours": 24,
        "requires_dvol": True,
        "tags": ["shadow", "mean-reversion", "vol-signal"],
        "status": "shadow",
    },
    "N3_SHADOW_075_51": {
        "display_name": "N3 Shadow — variant B",
        "description": "Shadow variant with relaxed DVOL filter. Tests whether lower-DVOL days have edge.",
        "compatible_markets": ["BTCUSDT"],
        "hold_hours": 24,
        "requires_dvol": True,
        "tags": ["shadow", "mean-reversion", "vol-signal"],
        "status": "shadow",
    },
    "N3_SHADOW_050_46": {
        "display_name": "N3 Shadow — variant C",
        "description": "Shadow variant: both thresholds relaxed. Fires in low-IV environments. Confirms regime dependence in live data.",
        "compatible_markets": ["BTCUSDT"],
        "hold_hours": 24,
        "requires_dvol": True,
        "tags": ["shadow", "mean-reversion", "vol-signal"],
        "status": "shadow",
    },

    # ── Shadow — second validated signal ─────────────────────────────────────
    "P3_OIPD_DD": {
        "display_name": "P3 OI-Price Divergence — DD Regime",
        "description": "Shadow-deployment second signal. Strategy parameters are private.",
        "compatible_markets": ["BTCUSDT"],
        "hold_hours": 24,
        "requires_dvol": True,
        "tags": ["order-flow", "regime", "shadow"],
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
        "description": "Opens a paper LONG every Monday and holds 24h. Not alpha — tests that trade open/close/funding/PnL/frontend all work correctly.",
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
