# Phase 4 Research — `p4/`

**Status: COMPLETE — Q5c SHADOW**  
**Started: 2026-05-15**  
**Completed: 2026-05-15**  
**Forward review due: >= 2026-11-15**

---

## Hypothesis

Three genuinely new signals, each testing a different mechanism of market stress resolution.
Phases 1–3 established that high DVOL regimes predict positive BTC returns (N3) and that
OI-price divergence in those regimes adds independent predictive power (P3). Phase 4 probes
three additional dimensions that were never screened:

| Signal | Mechanism | Data source |
|--------|-----------|-------------|
| Q4 Mark-Index Basis | Perp trades at discount to spot → short squeeze risk → LONG | `BTCUSDT_premium_index_1m.parquet` (already in repo) |
| Q5 ETH-BTC Cross-DVOL | ETH implied vol z-score as a leading or confirming fear indicator for BTC | `ETH_deribit_dvol_1h.parquet` (download via `data/download_phase4.py`) |
| Q6 Liquidation Exhaustion | Spike in daily forced long-selling → capitulation bottom → LONG | `BTCUSDT_liquidations_daily.parquet` (download via `data/download_phase4.py`) |

---

## Why these three

**Q4 (Basis):** The mark-index premium is the real-time anchor for the funding rate.
When the basis is deeply negative, shorts are earning a premium that longs have to pay at
the next 8h settlement — but the *instantaneous* basis is a sharper and earlier signal than
the 8h-averaged funding rate (Signals H1/H2) which were killed in Phase 1. Different enough
to merit an independent screen.

**Q5 (Cross-DVOL):** Cross-asset volatility spillover is a well-documented phenomenon in
equity markets (Diebold & Yilmaz, 2012). In crypto, ETH vol tends to amplify and lead BTC
vol dynamics. Two variants are tested: (a) ETH N3z alone as a predictor of BTC returns,
and (b) the product BTC_N3z × ETH_N3z as a joint confirmation. Independent data source
gives clean incremental IC measurement.

**Q6 (Liquidations):** Forced liquidation cascades are a crypto-specific fear mechanism with
no close equity analogue. A spike in long liquidation notional marks the moment where
leveraged buyers are forcibly removed — historically the final stage of a sell-off. Combined
with the DVOL ≥ 54 regime filter (which already proved necessary for N3 and P3), this may
identify capitulation bottoms with higher precision.

---

## Research trail

| Script | Status | Purpose |
|--------|--------|---------|
| `25_phase4_ic_screen.py` | DONE | IC screen — Q5c advanced; Q4a/Q4b/Q5a/Q5b killed; Q6 untestable |
| `26_q5c_deep_dive.py` | DONE | Kill attempt, DVOL grid (best=52), entry threshold grid, position backtest |

---

## How to run

```bash
# Step 1: Download new data (ETH DVOL + daily liquidations)
python data/download_phase4.py --all

# Step 2: Run the IC screen
python research/active/p4/25_phase4_ic_screen.py
```

Basis data (`BTCUSDT_premium_index_1m.parquet`) is already in the repo — Q4 runs
without any additional download.

---

## Pass criteria (consistent with N3 and P3)

| Gate | Threshold |
|------|-----------|
| Unfiltered IC/IC* ratio | > 0.5 |
| DVOL ≥ 54 filtered ratio | > 1.0 |
| Bootstrap p (one-sided) | ≤ 0.05 |
| Sub-period direction stability | ≥ 3 of 5 OOS half-years |
| Independence from N3z | \|corr\| < 0.5 or incremental ratio > 0.5 |

Signals that pass advance to a full deep dive (kill attempt, regime filter selection,
position-level backtest). Signals that fail are killed and documented in the kill log.

---

## Prior kills relevant to this phase

| Signal | Phase | Why killed | Why Q4/Q5/Q6 are different |
|--------|-------|-----------|---------------------------|
| H1 Funding 1h | 1 | No edge after 2024 bull run | Q4 uses instantaneous basis, not 8h-average |
| P1 VRP | 3 | IC < IC*, no DVOL filter saved it | Q5 uses cross-asset vol, Q6 uses liquidation vol |
| P2 TAR | 3 | Low IC, regime-unstable | Q6 uses forced volume (liquidations), not taker aggression |
| N1 DVOL level | 2 | Weaker than z-score (N3) | Q5 adds ETH dimension, not just BTC level |
