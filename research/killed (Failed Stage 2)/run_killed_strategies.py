"""
Run Signal C and Signal E strategies over train / val / test splits.
Sweeps entry thresholds and reports full metrics table.
"""
import sys, warnings
import pandas as pd
import numpy as np
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
from framework.splits import split, get_split
from framework.costs import TAKER, MAKER
from archive.strategies.cvd_strategy import CVDDivergenceStrategy
from archive.strategies.vpin_strategy import VPINRegimeStrategy
from backtest.engine import BacktestEngine, BacktestResult

PROC    = Path("data/processed")
RESULTS = Path("results/killed")
RESULTS.mkdir(parents=True, exist_ok=True)

print("Loading 1m data...")
df = pd.read_parquet(PROC / "ofi.parquet")

SPLITS   = ["train", "val", "test"]
ENTRY_PERCS = [0.75, 0.80, 0.85]
HOLD_BARS   = [30, 60]

all_metrics = []
equity_store = {}

BORDER = "=" * 72

print(BORDER)
print("BACKTEST: CVD DIVERGENCE (SIGNAL C)")
print(BORDER)

for split_name in SPLITS:
    sub = get_split(df, split_name)
    print(f"\n--- {split_name.upper()} "
          f"({sub.index.min().date()} to {sub.index.max().date()}, "
          f"{len(sub):,} bars) ---")

    for ep in ENTRY_PERCS:
        for hb in HOLD_BARS:
            for cost_model, cost_label in [(TAKER, "taker"), (MAKER, "maker")]:
                strat  = CVDDivergenceStrategy(entry_pct=ep, hold_bars=hb)
                engine = BacktestEngine(strat, cost_model=cost_model)
                result = engine.run(sub)
                m      = result.metrics
                m.update({"split": split_name, "strategy": "CVD",
                           "entry_pct": ep, "hold_bars": hb,
                           "cost_model": cost_label})
                all_metrics.append(m)
                key = ("CVD", split_name, cost_label, ep, hb)
                equity_store[key] = result.equity

                if cost_label == "taker":
                    print(f"  ep={ep}  hold={hb}m  "
                          f"n={m['n_trades']:>4}  "
                          f"Sharpe={m.get('sharpe', float('nan')):+.3f}  "
                          f"Ann={m.get('ann_return', 0)*100:+.1f}%  "
                          f"MDD={m.get('max_drawdown', 0)*100:.1f}%  "
                          f"Hit={m.get('hit_rate', 0)*100:.0f}%")

print(f"\n{BORDER}")
print("BACKTEST: VPIN REGIME STRATEGY (SIGNAL E + C COMBINED)")
print(BORDER)

VPIN_PCTS = [0.33, 0.40, 0.50]

for split_name in SPLITS:
    sub = get_split(df, split_name)
    print(f"\n--- {split_name.upper()} ---")

    for vp in VPIN_PCTS:
        for ep in [0.80, 0.85]:
            for cost_model, cost_label in [(TAKER, "taker"), (MAKER, "maker")]:
                strat  = VPINRegimeStrategy(vpin_regime_pct=vp, cvd_entry_pct=ep)
                engine = BacktestEngine(strat, cost_model=cost_model)
                result = engine.run(sub)
                m      = result.metrics
                m.update({"split": split_name, "strategy": "VPIN_CVD",
                           "vpin_regime_pct": vp, "entry_pct": ep,
                           "cost_model": cost_label})
                all_metrics.append(m)
                key = ("VPIN_CVD", split_name, cost_label, vp, ep)
                equity_store[key] = result.equity

                if cost_label == "taker":
                    print(f"  vpin_pct={vp}  ep={ep}  "
                          f"n={m['n_trades']:>4}  "
                          f"Sharpe={m.get('sharpe', float('nan')):+.3f}  "
                          f"Ann={m.get('ann_return', 0)*100:+.1f}%  "
                          f"MDD={m.get('max_drawdown', 0)*100:.1f}%  "
                          f"Hit={m.get('hit_rate', 0)*100:.0f}%")

# ── Best per strategy per split ───────────────────────────────────────────────
print(f"\n{BORDER}")
print("BEST CONFIGURATION PER STRATEGY (taker costs, by Sharpe)")
print(BORDER)

metrics_df = pd.DataFrame(all_metrics)
metrics_df.to_csv(RESULTS / "backtest_metrics.csv", index=False)

taker = metrics_df[metrics_df["cost_model"] == "taker"].copy()
for strat_name in ["CVD", "VPIN_CVD"]:
    print(f"\nStrategy: {strat_name}")
    sub_m = taker[taker["strategy"] == strat_name]
    for split_name in SPLITS:
        s = sub_m[sub_m["split"] == split_name]
        if s.empty or s["n_trades"].max() == 0:
            print(f"  {split_name:5s}: no trades")
            continue
        s = s[s["n_trades"] >= 10]
        if s.empty:
            print(f"  {split_name:5s}: insufficient trades")
            continue
        best = s.loc[s["sharpe"].idxmax()]
        print(
            f"  {split_name:5s}: Sharpe={best['sharpe']:+.3f}  "
            f"Ann={best.get('ann_return', 0)*100:+.1f}%  "
            f"MDD={best.get('max_drawdown', 0)*100:.1f}%  "
            f"n={best['n_trades']:.0f}  "
            f"hit={best.get('hit_rate', 0)*100:.0f}%"
        )

# Save equity curves
equity_frames = []
for key, eq in equity_store.items():
    strat_n, split_n, cost_l = key[0], key[1], key[2]
    params = "_".join(str(x) for x in key[3:])
    frame = eq.rename("equity").to_frame()
    frame["strategy"] = strat_n
    frame["split"]    = split_n
    frame["cost"]     = cost_l
    frame["params"]   = params
    equity_frames.append(frame)

pd.concat(equity_frames).to_parquet(RESULTS / "equity_curves.parquet")
print(f"\nSaved: results/killed/backtest_metrics.csv  results/killed/equity_curves.parquet")
