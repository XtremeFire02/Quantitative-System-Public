"""Generic signal result shared by all strategy evaluators."""
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class SignalResult:
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
    async def evaluate(self, market: str) -> SignalResult: ...
