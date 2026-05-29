"""Funding rate carry signal — short when persistent positive funding."""
from app.data.binance_client import get_market_snapshot
from app.signals.base import SignalResult

HOLD_HOURS = 8
ENTRY_THRESHOLD = 0.0010   # 0.10% per 8h settlement ≈ 110% annualised
EXIT_THRESHOLD = 0.0003    # close if funding drops below this


class FundingCarryEvaluator:
    """
    Enter SHORT when the funding rate exceeds ENTRY_THRESHOLD.
    Longs are overpaying carry; the short position earns the funding payment
    at the next 8h settlement.

    This is a pure carry trade — no directional view on price.
    """

    def __init__(self, strategy_name: str = "FUNDING_CARRY"):
        self.strategy_name = strategy_name

    async def evaluate(self, market: str) -> SignalResult:
        snapshot = await get_market_snapshot(market)
        funding_rate = snapshot["funding_rate"]

        entry_signal = funding_rate > ENTRY_THRESHOLD

        if entry_signal:
            reason = (
                f"SHORT: funding rate = {funding_rate:.4%} > threshold {ENTRY_THRESHOLD:.4%} "
                f"(carry trade: earn funding at next 8h settlement)"
            )
        else:
            reason = (
                f"No trade: funding rate = {funding_rate:.4%} <= threshold {ENTRY_THRESHOLD:.4%}"
            )

        return SignalResult(
            strategy_name=self.strategy_name,
            market=market,
            entry_signal=entry_signal,
            side="short",
            reason=reason,
            hold_hours=HOLD_HOURS,
            metadata={
                "funding_rate": funding_rate,
                "entry_threshold": ENTRY_THRESHOLD,
                "price": snapshot.get("price"),
            },
        )
