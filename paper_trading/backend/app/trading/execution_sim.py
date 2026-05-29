"""
Execution quality simulator for paper trades.

Models three cost layers for a maker order on any supported perp market:
  1. Spread + market impact — widens with volatility and notional size.
     Impact follows Almgren-Chriss: impact_bp ∝ sqrt(notional / ADV).
     typical_impact_bp is calibrated at $10k notional per market; the
     sqrt formula extrapolates to other sizes correctly.
  2. Adverse selection — fraction of the DVOL-implied daily range captured
     by market participants between signal evaluation and order resting.
     Zero for scheduled (time-based) exits.
  3. Latency — price drift during the signal-to-order API round-trip.

All figures are illustrative (paper trading has no real order book), but
they bound expected execution cost and help calibrate live-readiness.

Parameters are sourced from the market registry so the model automatically
adapts when applied to markets other than BTCUSDT-PERP.

Usage:
    from app.trading.execution_sim import estimate_execution, estimate_exit_execution
    est = estimate_execution("BTCUSDT-PERP", signal_price=95000.0, dvol=58.0, side="long")
    exit_est = estimate_exit_execution("BTCUSDT-PERP", signal_price=96000.0, dvol=58.0, side="long")
    print(est.total_cost_bp, exit_est.total_cost_bp)
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass

# Adverse selection and latency model constants (market-independent)
_ADVERSE_SELECTION_FRACTION = 0.05    # fraction of implied daily range captured at entry
_DVOL_ANNUAL_TO_DAILY = 1.0 / (365 ** 0.5)

# Latency baseline at elevated DVOL for a typical datacenter connection (~2 ms).
# Set via environment or overridden by the network simulator in tests.
_LATENCY_MS_DEFAULT = float(os.getenv("ASSUMED_LATENCY_MS", "40.0"))
_BP_PER_MS_AT_DVOL_REF = 0.006  # bp of price move per ms at reference DVOL level

# Maker fill probability decays above the reference DVOL level
_MAKER_FILL_BASE = 0.80
_MAKER_FILL_VOL_SLOPE = 0.10     # subtract per 10-pt DVOL above reference
_DVOL_MAKER_REFERENCE = float(os.getenv("DVOL_MAKER_REFERENCE", "50.0"))


@dataclass
class ExecutionEstimate:
    market_id: str
    signal_price: float
    estimated_maker_price: float
    estimated_taker_price: float
    half_spread_bp: float
    impact_bp: float
    adverse_selection_bp: float
    latency_bp: float
    fee_bp: float
    total_cost_bp: float             # all-in taker scenario
    maker_fill_probability: float
    execution_quality_score: float   # 0–10 (10 = clean maker fill at signal price)
    latency_assumed_ms: float

    def to_dict(self) -> dict:
        return asdict(self)


def estimate_execution(
    market_id: str,
    signal_price: float,
    dvol: float | None,
    side: str,
    notional_usd: float = 10_000.0,
    latency_ms: float | None = None,
) -> ExecutionEstimate:
    """
    Estimate execution cost and fill quality for a single entry.

    Parameters
    ----------
    market_id    : Canonical market ID (e.g. "BTCUSDT-PERP"). Must be in the
                   market registry — this drives fee and spread parameters.
    signal_price : Current mark price at evaluation time.
    dvol         : Deribit DVOL index; falls back to reference level if None.
    side         : "long" or "short".
    notional_usd : Order size in USD (affects market impact estimate).
    latency_ms   : Signal-to-order round-trip in ms. Defaults to
                   ASSUMED_LATENCY_MS env var (default 40 ms).
    """
    from app.markets import get_market

    market = get_market(market_id)
    dvol = dvol or _DVOL_MAKER_REFERENCE
    lat = latency_ms if latency_ms is not None else _LATENCY_MS_DEFAULT
    sign = 1.0 if side == "long" else -1.0

    # ── Spread and market impact ──────────────────────────────────────────────
    dvol_excess = max(dvol - _DVOL_MAKER_REFERENCE, 0.0)
    # Spread widens with volatility; impact follows Almgren-Chriss sqrt(notional/ADV).
    # typical_impact_bp is calibrated at $10k notional, so: size_factor = sqrt(notional/10k).
    half_spread = market.typical_half_spread_bp * (1.0 + dvol_excess / _DVOL_MAKER_REFERENCE)
    size_factor = (notional_usd / 10_000.0) ** 0.5
    impact = market.typical_impact_bp * size_factor

    maker_price = signal_price * (1.0 + sign * half_spread / 10_000)
    taker_price = signal_price * (1.0 + sign * (half_spread + impact) / 10_000)

    # ── Adverse selection ─────────────────────────────────────────────────────
    daily_range_bp = (dvol / 100.0) * _DVOL_ANNUAL_TO_DAILY * 10_000
    adverse_bp = daily_range_bp * _ADVERSE_SELECTION_FRACTION

    # ── Latency ───────────────────────────────────────────────────────────────
    vol_scalar = dvol / _DVOL_MAKER_REFERENCE
    latency_bp = lat * _BP_PER_MS_AT_DVOL_REF * vol_scalar

    # ── Maker fill probability ────────────────────────────────────────────────
    maker_prob = max(0.30, _MAKER_FILL_BASE - _MAKER_FILL_VOL_SLOPE * (dvol_excess / 10.0))

    # ── Blended fee ──────────────────────────────────────────────────────────
    fee_bp = maker_prob * market.maker_fee_bp + (1.0 - maker_prob) * market.taker_fee_bp

    # ── Total cost ────────────────────────────────────────────────────────────
    total_bp = (half_spread + impact) + adverse_bp + latency_bp + fee_bp

    # ── Quality score ─────────────────────────────────────────────────────────
    quality = round(min(10.0, max(0.0, 10.0 * maker_prob * (1.0 - adverse_bp / 100.0))), 1)

    return ExecutionEstimate(
        market_id=market_id,
        signal_price=round(signal_price, 4),
        estimated_maker_price=round(maker_price, 4),
        estimated_taker_price=round(taker_price, 4),
        half_spread_bp=round(half_spread, 3),
        impact_bp=round(impact, 3),
        adverse_selection_bp=round(adverse_bp, 3),
        latency_bp=round(latency_bp, 4),
        fee_bp=round(fee_bp, 3),
        total_cost_bp=round(total_bp, 3),
        maker_fill_probability=round(maker_prob, 4),
        execution_quality_score=quality,
        latency_assumed_ms=round(lat, 2),
    )


def estimate_exit_execution(
    market_id: str,
    signal_price: float,
    dvol: float | None,
    side: str,
    notional_usd: float = 10_000.0,
    latency_ms: float | None = None,
) -> ExecutionEstimate:
    """
    Estimate execution cost for closing a position.

    Exit direction is opposite to entry: long positions sell at bid,
    short positions buy at ask.  Adverse selection is zero for scheduled
    (time-based) exits — there is no information asymmetry at close.
    Latency defaults to 10 ms (smaller than entry; exit can be pre-staged).

    Parameters match estimate_execution(); side is the original position side.
    """
    from app.markets import get_market

    market = get_market(market_id)
    dvol = dvol or _DVOL_MAKER_REFERENCE
    lat = latency_ms if latency_ms is not None else 10.0  # pre-staged exit
    # Exit direction opposes position side: long → sell (-1), short → buy (+1)
    sign = -1.0 if side == "long" else 1.0

    dvol_excess = max(dvol - _DVOL_MAKER_REFERENCE, 0.0)
    half_spread = market.typical_half_spread_bp * (1.0 + dvol_excess / _DVOL_MAKER_REFERENCE)
    size_factor = (notional_usd / 10_000.0) ** 0.5
    impact = market.typical_impact_bp * size_factor

    maker_price = signal_price * (1.0 + sign * half_spread / 10_000)
    taker_price = signal_price * (1.0 + sign * (half_spread + impact) / 10_000)

    # No adverse selection at exit (scheduled, not reactive)
    adverse_bp = 0.0

    vol_scalar = dvol / _DVOL_MAKER_REFERENCE
    latency_bp = lat * _BP_PER_MS_AT_DVOL_REF * vol_scalar

    maker_prob = max(0.30, _MAKER_FILL_BASE - _MAKER_FILL_VOL_SLOPE * (dvol_excess / 10.0))
    fee_bp = maker_prob * market.maker_fee_bp + (1.0 - maker_prob) * market.taker_fee_bp

    total_bp = (half_spread + impact) + adverse_bp + latency_bp + fee_bp

    # Exit quality: cleaner than entry (no adverse selection); penalise only spread/impact
    quality = round(max(0.0, 10.0 * maker_prob * (1.0 - (half_spread + impact) / 20.0)), 1)

    return ExecutionEstimate(
        market_id=market_id,
        signal_price=round(signal_price, 4),
        estimated_maker_price=round(maker_price, 4),
        estimated_taker_price=round(taker_price, 4),
        half_spread_bp=round(half_spread, 3),
        impact_bp=round(impact, 3),
        adverse_selection_bp=0.0,
        latency_bp=round(latency_bp, 4),
        fee_bp=round(fee_bp, 3),
        total_cost_bp=round(total_bp, 3),
        maker_fill_probability=round(maker_prob, 4),
        execution_quality_score=quality,
        latency_assumed_ms=round(lat, 2),
    )
