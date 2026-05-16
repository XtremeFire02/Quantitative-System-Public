"""
Execution quality simulator for paper trades.

Models three cost layers for a 24h maker order on BTCUSDT perp:
  1. Spread + market impact (taker path) or passive rest (maker path)
  2. Adverse selection: DVOL spikes after entry → mark price moves against you
     before your limit rests. Modelled as fraction of DVOL-implied daily range.
  3. Latency: signal-to-order delay (API round-trip ~40 ms typical). In fast
     markets each millisecond of delay is ~0.01 bp of additional slippage.

All figures are illustrative — paper trading has no real order book — but they
bound expected execution cost and help calibrate live-readiness expectations.
"""
from dataclasses import dataclass, asdict

# Binance BTCUSDT perp typical parameters (maker/taker VIP0)
HALF_SPREAD_BP    = 1.0     # half of typical bid-ask spread
MARKET_IMPACT_BP  = 0.5     # taker book-walking slippage at our size (~$1k notional)
MAKER_FEE_BP      = 2.0     # Binance maker fee (0.02%)
TAKER_FEE_BP      = 5.0     # Binance taker fee (0.05%)

# Adverse selection parameters
# BTC daily vol ≈ DVOL / sqrt(365) in pct; a 1% daily move → ~100 bp.
# We model that ~5% of the daily range is captured as adverse selection at entry.
_ADVERSE_SELECTION_FRACTION = 0.05   # of implied daily range
_DVOL_ANNUAL_TO_DAILY       = 1.0 / (365 ** 0.5)

# Latency model
# Typical Binance REST round-trip: 30–60 ms from EU/US; assume 40 ms.
# At DVOL=54, BTC moves ~0.036% per minute → 0.0006% per ms.
_LATENCY_MS    = 40.0       # assumed signal-to-order delay in milliseconds
_BP_PER_MS_AT_DVOL54 = 0.006  # bp of price move per ms at DVOL=54

# Maker fill probability baseline at DVOL=54
_MAKER_FILL_BASE      = 0.80
_MAKER_FILL_VOL_SLOPE = 0.10  # subtract this per 10-point DVOL above 54


@dataclass
class ExecutionEstimate:
    signal_price: float
    estimated_maker_price: float
    estimated_taker_price: float
    slippage_bp: float              # spread + impact for taker path
    adverse_selection_bp: float     # expected mark-price drift between signal and fill
    latency_bp: float               # price move during API round-trip
    fee_bp: float                   # blended fee (maker_prob × maker_fee + (1-p) × taker_fee)
    total_cost_bp: float            # slippage + adverse + latency + fee (taker scenario)
    maker_fill_probability: float
    execution_quality_score: float  # 0–10 (10 = clean maker fill at signal price)

    def to_dict(self) -> dict:
        return asdict(self)


def estimate_execution(
    signal_price: float,
    dvol: float | None,
    side: str,
) -> ExecutionEstimate:
    """
    Estimate execution cost and fill quality for a single entry.

    Parameters
    ----------
    signal_price : float  Current mark price at signal evaluation time.
    dvol         : float  Deribit DVOL index (annualised implied vol, e.g. 54).
    side         : str    "long" or "short".
    """
    dvol = dvol or 54.0
    sign = 1.0 if side == "long" else -1.0

    # ── Spread and market impact ──────────────────────────────────────────────
    dvol_excess  = max(dvol - 54.0, 0.0)
    half_spread  = HALF_SPREAD_BP * (1.0 + dvol_excess / 54.0)   # widens with vol
    impact       = MARKET_IMPACT_BP

    maker_price  = signal_price * (1.0 + sign * half_spread / 10_000)
    taker_price  = signal_price * (1.0 + sign * (half_spread + impact) / 10_000)
    slippage_bp  = (half_spread + impact)  # taker worst case

    # ── Adverse selection ─────────────────────────────────────────────────────
    # Implied daily range = DVOL% / sqrt(365), converted to bp
    daily_range_bp      = (dvol / 100.0) * _DVOL_ANNUAL_TO_DAILY * 10_000
    adverse_selection_bp = daily_range_bp * _ADVERSE_SELECTION_FRACTION

    # ── Latency ───────────────────────────────────────────────────────────────
    # Price move scales with vol relative to DVOL=54 baseline
    vol_scalar  = dvol / 54.0
    latency_bp  = _LATENCY_MS * _BP_PER_MS_AT_DVOL54 * vol_scalar

    # ── Maker fill probability ────────────────────────────────────────────────
    maker_prob  = max(0.30, _MAKER_FILL_BASE - _MAKER_FILL_VOL_SLOPE * (dvol_excess / 10.0))

    # ── Blended fee ──────────────────────────────────────────────────────────
    fee_bp      = maker_prob * MAKER_FEE_BP + (1.0 - maker_prob) * TAKER_FEE_BP

    # ── Total cost (taker scenario includes all layers) ───────────────────────
    total_cost_bp = slippage_bp + adverse_selection_bp + latency_bp + fee_bp

    # ── Quality score: 10 = perfect maker fill, penalise vol + adverse sel ───
    quality = round(max(0.0, 10.0 * maker_prob * (1.0 - adverse_selection_bp / 100.0)), 1)

    return ExecutionEstimate(
        signal_price=round(signal_price, 2),
        estimated_maker_price=round(maker_price, 2),
        estimated_taker_price=round(taker_price, 2),
        slippage_bp=round(slippage_bp, 2),
        adverse_selection_bp=round(adverse_selection_bp, 2),
        latency_bp=round(latency_bp, 3),
        fee_bp=round(fee_bp, 2),
        total_cost_bp=round(total_cost_bp, 2),
        maker_fill_probability=round(maker_prob, 3),
        execution_quality_score=quality,
    )
