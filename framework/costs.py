"""
Transaction cost model for Binance USDT-M perpetuals.

Usage:
    from framework.costs import CostModel
    model = CostModel()
    net_ret = model.apply(gross_log_return, side, notional_usd)
"""
from dataclasses import dataclass, field
import numpy as np


@dataclass
class CostModel:
    """
    All costs expressed as fractions of notional.

    Binance USDT-M perpetual defaults (VIP0):
      taker fee : 0.040%
      maker fee : 0.020%
      slippage  : 0.010%  (half-spread estimate for BTC at ~$100k, $10k notional)
      funding   : paid/received at 8h settlement — handled separately in PnL

    Set use_maker=True when your strategy can consistently post limit orders.
    """
    taker_fee:   float = 0.0004    # 4 bps
    maker_fee:   float = 0.0002    # 2 bps
    slippage:    float = 0.0001    # 1 bp  (one-way; applied on entry AND exit)
    use_maker:   bool  = False

    @property
    def fee(self) -> float:
        return self.maker_fee if self.use_maker else self.taker_fee

    def round_trip_cost(self) -> float:
        """Total cost fraction for one complete round-trip (entry + exit)."""
        return 2 * (self.fee + self.slippage)

    def one_way_cost(self) -> float:
        return self.fee + self.slippage

    def apply_log(self, gross_log_ret: np.ndarray, n_trades: int = 1) -> np.ndarray:
        """
        Subtract round-trip costs from gross log returns.
        n_trades: number of round-trips embedded in the return series element.
        """
        return gross_log_ret - n_trades * self.round_trip_cost()

    def breakeven_move(self) -> float:
        """Minimum gross move (one-way) needed to cover costs on entry."""
        return self.one_way_cost()

    def __str__(self) -> str:
        mode = "maker" if self.use_maker else "taker"
        return (
            f"CostModel({mode}: fee={self.fee*1e4:.1f}bps  "
            f"slip={self.slippage*1e4:.1f}bps  "
            f"round-trip={self.round_trip_cost()*1e4:.1f}bps)"
        )


# Convenience instances
TAKER = CostModel(use_maker=False)
MAKER = CostModel(use_maker=True)


if __name__ == "__main__":
    for m in [TAKER, MAKER]:
        print(m)
        print(f"  round-trip cost : {m.round_trip_cost()*100:.4f}%")
        print(f"  breakeven move  : {m.breakeven_move()*100:.4f}%")
        gross = np.array([0.005, 0.001, -0.002])
        print(f"  gross returns   : {gross*100}")
        print(f"  net returns     : {m.apply_log(gross)*100}")
        print()
