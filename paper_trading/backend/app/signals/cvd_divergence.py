"""CVD Divergence signal — stub until real-time order flow data is wired."""
from app.signals.base import SignalResult

HOLD_HOURS = 1


class CvdDivergenceEvaluator:
    """
    Placeholder. CVD divergence requires a live 1-minute WebSocket feed of
    taker buy/sell volume to compute the running cumulative volume delta.
    That feed is not yet wired into the paper trading backend.

    Returns no signal until implemented.
    """

    def __init__(self, strategy_name: str = "CVD_DIVERGENCE"):
        self.strategy_name = strategy_name

    async def evaluate(self, market: str) -> SignalResult:
        return SignalResult(
            strategy_name=self.strategy_name,
            market=market,
            entry_signal=False,
            side="long",
            reason="CVD_DIVERGENCE not yet implemented: requires live WebSocket OFI feed.",
            hold_hours=HOLD_HOURS,
            metadata={"status": "stub"},
        )
