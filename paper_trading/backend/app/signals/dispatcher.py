"""
Signal dispatcher — maps strategy_name strings to evaluator instances.

The concrete evaluator implementations are private and not included in
this repository. Deploying the live system requires the private signal
files to be present alongside this stub.
"""
from app.signals.base import SignalEvaluator


def get_evaluator(strategy_name: str) -> SignalEvaluator:
    raise NotImplementedError(
        f"Signal evaluator for '{strategy_name}' is not included in the public "
        "repository. The live system requires the private signal implementations."
    )
