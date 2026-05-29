"""Execution test evaluator — fires every Monday to keep the system exercised."""
from datetime import datetime, timezone

from app.signals.base import SignalResult

HOLD_HOURS = 24
_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class ExecutionTestEvaluator:
    """
    Opens a LONG paper trade every Monday (UTC) and holds for 24h.

    Purpose: verify that the full trade lifecycle (open → funding → close → PnL →
    equity update → frontend display) works correctly during low-DVOL periods when
    the official N3 strategy is flat. This is NOT an alpha strategy.

    The trade is tagged with strategy_name="EXECUTION_TEST" so it is trivially
    separable from official N3 trades in the database and frontend.
    """

    def __init__(self, strategy_name: str = "EXECUTION_TEST"):
        self.strategy_name = strategy_name

    async def evaluate(self, market: str) -> SignalResult:
        now = datetime.now(timezone.utc)
        weekday = now.weekday()   # 0 = Monday … 6 = Sunday
        is_monday = weekday == 0

        if is_monday:
            reason = (
                f"EXECUTION TEST: Monday {now.strftime('%Y-%m-%d')} → open LONG "
                f"(system mechanics test, not alpha)"
            )
        else:
            reason = (
                f"EXECUTION TEST: {_WEEKDAY_NAMES[weekday]} → flat "
                f"(fires on Monday only)"
            )

        return SignalResult(
            strategy_name=self.strategy_name,
            market=market,
            entry_signal=is_monday,
            side="long",
            reason=reason,
            hold_hours=HOLD_HOURS,
            metadata={
                "weekday": _WEEKDAY_NAMES[weekday],
                "is_monday": is_monday,
                "purpose": "execution_test",
            },
        )
