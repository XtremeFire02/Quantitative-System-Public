"""PnL calculation for closed paper trades."""
from app.config import ONE_WAY_COST
import math


def calculate_pnl(
    side: str,
    entry_price: float,
    exit_price: float,
    funding_rates: list[float],
    position_size: float = 1.0,
) -> dict:
    """
    Compute net PnL for a closed trade.

    funding_rates: list of 8h settlement rates that occurred during the hold window
                  Positive rate = longs pay shorts.
    Returns dict with gross_price_return, funding_pnl, fees, slippage, net_pnl, net_pnl_bp
    """
    direction = 1.0 if side == "long" else -1.0

    # Price return (log approx for small moves, exact for large)
    if entry_price > 0 and exit_price > 0:
        gross_price_return = direction * math.log(exit_price / entry_price)
    else:
        gross_price_return = 0.0

    # Funding: longs pay positive rate, shorts receive it
    funding_pnl = direction * (-sum(funding_rates)) * position_size

    # Costs: entry + exit one-way cost each
    fees = 2 * ONE_WAY_COST * position_size
    slippage = 0.0  # already embedded in ONE_WAY_COST

    net_pnl = gross_price_return + funding_pnl - fees
    net_pnl_bp = net_pnl * 10000

    return {
        "gross_price_return": gross_price_return,
        "funding_pnl": funding_pnl,
        "fees": fees,
        "slippage": slippage,
        "net_pnl": net_pnl,
        "net_pnl_bp": net_pnl_bp,
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
