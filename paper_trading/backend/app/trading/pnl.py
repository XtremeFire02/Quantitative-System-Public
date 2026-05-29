"""
P&L calculation for closed paper trades.

Attribution breakdown:
    gross_price_return  — pure price move (direction × log(exit/entry))
    funding_pnl         — 8h settlement funding received/paid
    slippage            — always 0 (see note below)
    fees                — exchange maker/taker fees, round-trip = ONE_WAY_COST × 2
    net_pnl             — gross + funding − fees

Net formula (all modes): net = gross + funding − fees
This matches the research baseline: net = gross + funding − MAKER.round_trip_cost()
where MAKER.round_trip_cost() = ONE_WAY_COST × 2 = 0.0006.

ONE_WAY_COST already bundles the 1 bp/leg spread estimate, so charging a separate
slippage term on top is double-counting. Slippage is kept as a field (= 0) in the
returned dict for API attribution display without affecting the net calculation.

When fills are simulated (signal_price / exit_signal_price provided), the spread
cost is captured directly in gross_price_return via the fill price delta; the
net formula remains the same.
"""
import math

from app.config import ONE_WAY_COST


def calculate_pnl(
    side: str,
    entry_price: float,
    exit_price: float,
    funding_rates: list[float],
    notional_usd: float = 10_000.0,
    entry_half_spread_bp: float | None = None,
    entry_impact_bp: float | None = None,
    signal_price: float | None = None,
    exit_signal_price: float | None = None,
) -> dict:
    """
    Compute net PnL for a closed trade.

    funding_rates     : list of 8h settlement rates during hold. Positive = longs pay.
    entry_half_spread_bp / entry_impact_bp : from ExecutionEstimate at open (unused in net calc).
    signal_price      : evaluation price at entry. When provided, entry_price is a
                        simulated fill — the spread cost is in gross_price_return.
    exit_signal_price : raw market price at exit for audit trail.

    Net formula (all modes): net = gross + funding − fees
    """
    direction = 1.0 if side == "long" else -1.0

    # Price return — log-return is additive and handles large moves correctly
    if entry_price > 0 and exit_price > 0:
        gross_price_return = direction * math.log(exit_price / entry_price)
    else:
        gross_price_return = 0.0

    # Funding — longs pay positive rate, receive negative rate
    funding_pnl = direction * (-sum(funding_rates))

    # Slippage is always 0: ONE_WAY_COST already bundles the per-leg spread estimate.
    # Charging additional slippage here would double-count against the research formula.
    # When fills are simulated, spread cost is already in gross_price_return anyway.
    slippage = 0.0

    # Exchange fees — round-trip maker cost; matches MAKER.round_trip_cost() = 0.0006
    fees = ONE_WAY_COST * 2

    net_pnl = gross_price_return + funding_pnl - slippage - fees
    net_pnl_bp = net_pnl * 10_000

    return {
        "gross_price_return": gross_price_return,
        "funding_pnl":        funding_pnl,
        "slippage":           slippage,
        "fees":               fees,
        "net_pnl":            net_pnl,
        "net_pnl_bp":         net_pnl_bp,
    }


def calculate_unrealised_pnl(
    side: str,
    entry_price: float,
    current_price: float,
) -> float:
    direction = 1.0 if side == "long" else -1.0
    if entry_price > 0 and current_price > 0:
        return direction * math.log(current_price / entry_price)
    return 0.0
