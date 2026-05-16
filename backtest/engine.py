"""
Event-driven backtest engine.

Feeds historical 1m bars one at a time into any Strategy that implements
on_bar(bar) -> Optional[Signal]. Handles position lifecycle, costs, and
produces a full trade log and equity curve.

Key design choices
------------------
- One position open at a time per strategy instance.
- Position closes after `hold_bars` bars (time-based exit).
- Costs subtracted on close (round-trip).
- Equity is tracked in log-return space; final equity = exp(cumsum).
- Compatible with the live VirtualExchange interface.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Dict
import numpy as np
import pandas as pd

from strategies.base import Bar, Signal, Strategy
from framework.costs import CostModel, TAKER


@dataclass
class Trade:
    entry_bar:   int
    entry_time:  object
    entry_price: float
    direction:   int
    hold_bars:   int
    exit_bar:    int    = -1
    exit_time:   object = None
    exit_price:  float  = 0.0
    gross_log_ret: float = 0.0
    net_log_ret:   float = 0.0
    strategy_id:   str   = ""
    features:      dict  = field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        return self.exit_bar < 0


@dataclass
class BacktestResult:
    trades:       pd.DataFrame
    equity:       pd.Series        # cumulative log-return indexed by timestamp
    metrics:      dict
    strategy_id:  str


def compute_metrics(trades: pd.DataFrame, equity: pd.Series,
                    label: str = "") -> dict:
    if trades.empty:
        return {"label": label, "n_trades": 0, "sharpe": np.nan,
                "ann_return": 0.0, "max_drawdown": 0.0}
    rets = trades["net_log_ret"]
    n    = len(rets)

    # Annualised return from equity curve (handles variable hold periods)
    if len(equity) >= 2:
        total_log = float(equity.iloc[-1] - equity.iloc[0])
        n_years   = (equity.index[-1] - equity.index[0]).total_seconds() / (365.25 * 86400)
        ann       = total_log / max(n_years, 1 / 365.25)
    else:
        ann = 0.0

    # Sharpe on daily equity changes (annualised with sqrt(252))
    try:
        eq_daily  = equity.resample("D").last().dropna()
        d_rets    = eq_daily.diff().dropna()
        sharpe    = (d_rets.mean() / d_rets.std() * np.sqrt(252)
                     if d_rets.std() > 0 else np.nan)
    except Exception:
        sharpe = np.nan

    # Drawdown
    eq_exp  = np.exp(equity)
    peak    = eq_exp.cummax()
    mdd     = float(((eq_exp - peak) / peak).min())
    calmar  = ann / abs(mdd) if mdd != 0 else np.nan

    return {
        "label":         label,
        "n_trades":      n,
        "total_ret":     float(rets.sum()),
        "ann_return":    ann,
        "sharpe":        sharpe,
        "max_drawdown":  mdd,
        "calmar":        calmar,
        "hit_rate":      float((rets > 0).mean()),
        "avg_win":       float(rets[rets > 0].mean()) if (rets > 0).any() else np.nan,
        "avg_loss":      float(rets[rets < 0].mean()) if (rets < 0).any() else np.nan,
        "profit_factor": (float(abs(rets[rets > 0].sum()) / abs(rets[rets < 0].sum()))
                          if (rets < 0).any() else np.nan),
    }


class BacktestEngine:
    """
    Run a strategy over a list (or DataFrame) of 1m bars.

    Parameters
    ----------
    strategy    : Strategy instance (will be reset before running)
    cost_model  : CostModel (default: TAKER = 10bps round-trip)
    max_positions : max simultaneous open positions (1 = no pyramiding)
    """

    def __init__(
        self,
        strategy:       Strategy,
        cost_model:     CostModel = TAKER,
        max_positions:  int = 1,
    ):
        self.strategy      = strategy
        self.cost_model    = cost_model
        self.max_positions = max_positions

    # ── main entry point ──────────────────────────────────────────────────────
    def run(self, df: pd.DataFrame) -> BacktestResult:
        """
        Parameters
        ----------
        df : DataFrame with columns open/high/low/close/volume/
             taker_buy_base_volume/trade_count, indexed by timestamp.
        """
        self.strategy.reset()
        open_positions: List[Trade] = []
        closed_trades:  List[Trade] = []
        equity_log:     Dict        = {}
        realised_pnl    = 0.0   # running sum — avoids O(n_trades) per bar

        # Pre-extract arrays for fast bar construction (avoids iterrows overhead)
        idx     = df.index
        opens   = df["open"].to_numpy(dtype=float)
        highs   = df["high"].to_numpy(dtype=float)
        lows    = df["low"].to_numpy(dtype=float)
        closes  = df["close"].to_numpy(dtype=float)
        vols    = df["volume"].to_numpy(dtype=float)
        tbvs    = df["taker_buy_base_volume"].to_numpy(dtype=float) if "taker_buy_base_volume" in df.columns else np.zeros(len(df))
        tcs     = df["trade_count"].to_numpy(dtype=float) if "trade_count" in df.columns else np.zeros(len(df))
        qvs     = df["quote_volume"].to_numpy(dtype=float) if "quote_volume" in df.columns else np.zeros(len(df))
        tbqvs   = df["taker_buy_quote_volume"].to_numpy(dtype=float) if "taker_buy_quote_volume" in df.columns else np.zeros(len(df))

        for i in range(len(df)):
            ts  = idx[i]
            bar = Bar(
                timestamp              = ts,
                open                   = opens[i],
                high                   = highs[i],
                low                    = lows[i],
                close                  = closes[i],
                volume                 = vols[i],
                taker_buy_volume       = tbvs[i],
                trade_count            = int(tcs[i]),
                quote_volume           = qvs[i],
                taker_buy_quote_volume = tbqvs[i],
            )

            # ── close expired positions ────────────────────────────────────
            for pos in open_positions[:]:
                if i - pos.entry_bar >= pos.hold_bars:
                    pos.exit_bar    = i
                    pos.exit_time   = ts
                    pos.exit_price  = bar.close
                    pos.gross_log_ret = pos.direction * np.log(
                        bar.close / pos.entry_price)
                    pos.net_log_ret = (pos.gross_log_ret
                                       - self.cost_model.round_trip_cost())
                    realised_pnl += pos.net_log_ret   # O(1) update
                    open_positions.remove(pos)
                    closed_trades.append(pos)

            # ── mark-to-market open positions ─────────────────────────────
            mtm = sum(p.direction * np.log(bar.close / p.entry_price)
                      for p in open_positions)
            equity_log[ts] = mtm + realised_pnl

            # ── get signal ────────────────────────────────────────────────
            sig: Optional[Signal] = self.strategy.on_bar(bar)

            # open new position if allowed
            if sig is not None and len(open_positions) < self.max_positions:
                open_positions.append(Trade(
                    entry_bar   = i,
                    entry_time  = ts,
                    entry_price = bar.close,
                    direction   = sig.direction,
                    hold_bars   = sig.hold_bars,
                    strategy_id = sig.strategy_id,
                    features    = sig.feature_values,
                ))

        # close any remaining open positions at last price
        last_row = df.iloc[-1]
        last_ts  = df.index[-1]
        for pos in open_positions:
            pos.exit_bar    = len(df) - 1
            pos.exit_time   = last_ts
            pos.exit_price  = float(last_row["close"])
            pos.gross_log_ret = pos.direction * np.log(
                pos.exit_price / pos.entry_price)
            pos.net_log_ret = (pos.gross_log_ret
                               - self.cost_model.round_trip_cost())
            closed_trades.append(pos)

        trades_df = pd.DataFrame([vars(t) for t in closed_trades])
        if not trades_df.empty:
            trades_df = trades_df.set_index("entry_time")

        equity = pd.Series(equity_log)
        metrics = compute_metrics(
            trades_df, equity,
            label=self.strategy.strategy_id,
        )
        return BacktestResult(
            trades=trades_df,
            equity=equity,
            metrics=metrics,
            strategy_id=self.strategy.strategy_id,
        )

    # ── reporting ─────────────────────────────────────────────────────────────
    @staticmethod
    def print_result(result: BacktestResult) -> None:
        m = result.metrics
        print(f"\nStrategy: {result.strategy_id}")
        print(f"  Trades:        {m.get('n_trades', 0)}")
        print(f"  Total return:  {m.get('total_ret', 0)*100:.2f}%")
        print(f"  Ann. return:   {m.get('ann_return', 0)*100:.2f}%")
        print(f"  Sharpe:        {m.get('sharpe', float('nan')):.3f}")
        print(f"  Max drawdown:  {m.get('max_drawdown', 0)*100:.2f}%")
        print(f"  Calmar:        {m.get('calmar', float('nan')):.3f}")
        print(f"  Hit rate:      {m.get('hit_rate', 0)*100:.1f}%")
        print(f"  Profit factor: {m.get('profit_factor', float('nan')):.3f}")
