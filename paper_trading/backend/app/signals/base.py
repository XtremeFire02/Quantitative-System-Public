"""
Generic signal contract shared by every strategy evaluator.

The daily signal job (jobs/daily_signal_job.py) dispatches dynamically via
`get_evaluator(strategy_name)` and consumes whatever SignalResult comes back,
so every evaluator — current (N3_DVOL_LONG, P3_OIPD_DD) and future — MUST
satisfy this interface. Adding new evaluator-specific telemetry should be
done via the `metadata` dict; only fields used by the OMS or by forward-log
queries belong as first-class attributes.

Flow:
    daily_signal_job
        → get_evaluator(strategy_name)             # registry lookup
        → evaluator.evaluate(market)               # async
        → returns SignalResult
        → persisted as Signal row
        → if entry_signal: paper_broker.open_trade(...)
"""
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class SignalResult:
    """
    Output of a strategy evaluation for one (strategy, market) on one day.

    Every evaluator returns one of these per call to `evaluate()`, regardless
    of whether a trade fires — `entry_signal=False` results are persisted too
    so the forward log can prove the rule stayed frozen on no-signal days.

    Attributes:
        strategy_name: registry key, e.g. "N3_DVOL_LONG".
        market:        market identifier, e.g. "BTCUSDT".
        entry_signal:  True when the rule's entry condition is satisfied.
        side:          "long" or "short" (informational only when entry_signal=False).
        reason:        human-readable explanation, surfaced to the alert + UI layers.
        hold_hours:    planned holding period; the exit job uses this to compute
                       planned_exit_timestamp.
        metadata:      free-form JSON-serializable payload persisted with the signal
                       (e.g. {"regime": "...", "dp": 0.012, "doi": -0.034}).
        dvol*, n3_*:   N3_DVOL_LONG-specific telemetry promoted to first-class fields
                       because the forward log reads them on every row; other
                       evaluators should leave them None.
    """
    strategy_name: str
    market: str
    entry_signal: bool
    side: str            # "long" | "short"
    reason: str
    hold_hours: int
    metadata: dict = field(default_factory=dict)

    # N3-specific convenience fields — None for non-DVOL strategies
    dvol: float | None = None
    dvol_mean_30d: float | None = None
    dvol_std_30d: float | None = None
    n3_z: float | None = None
    dvol_filter_pass: bool | None = None


@runtime_checkable
class SignalEvaluator(Protocol):
    """
    Structural protocol every strategy evaluator must satisfy.

    Implementations live under app/signals/<strategy>.py and are registered
    in app/signals/registry.py. The daily_signal_job awaits `evaluate()` once
    per active (strategy, market) pair per scheduler tick (00:00 UTC).

    Implementations should be deterministic given identical market data —
    the test_parity suite replays research fixtures through evaluators and
    asserts byte-identical outputs against the research backtests.
    """
    async def evaluate(self, market: str) -> SignalResult: ...
