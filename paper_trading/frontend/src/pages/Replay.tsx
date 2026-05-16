import React, { useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";
import { api } from "../api";
import type { ReplayResponse } from "../api";

const pct = (v: number | null | undefined) =>
  v == null ? "—" : `${(v * 100).toFixed(1)}%`;

const bp = (v: number | null | undefined) => {
  if (v == null) return "—";
  return `${v > 0 ? "+" : ""}${v.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })} bp`;
};

function MatchBadge({ actual, target, tolerance = 0.15 }: {
  actual: number | null | undefined;
  target: number;
  tolerance?: number;
}) {
  if (actual == null) return <span style={{ color: "#64748b" }}>—</span>;
  const delta = Math.abs(actual - target) / Math.abs(target);
  const pass = delta <= tolerance;
  return (
    <span style={{
      fontSize: 10,
      padding: "2px 6px",
      borderRadius: 4,
      background: pass ? "#166534" : "#7f1d1d",
      color: pass ? "#4ade80" : "#f87171",
      marginLeft: 8,
    }}>
      {pass ? "MATCH" : "DIFF"}
    </span>
  );
}

export default function Replay() {
  const [data, setData] = useState<ReplayResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [includeTrain, setIncludeTrain] = useState(false);

  const runReplay = () => {
    setLoading(true);
    setError(null);
    setData(null);
    api.replay("2024-01-01", includeTrain)
      .then(setData)
      .catch(e => {
        const msg = e?.message ?? String(e);
        setError(msg.includes("503") || msg.includes("not found")
          ? "Parquet data files not found. Run data/download.py and data/download_phase2.py to fetch historical data."
          : msg);
      })
      .finally(() => setLoading(false));
  };

  const target = data?.reference_targets;
  const summary = data?.summary;

  return (
    <div>
      <div className="page-header">
        <div className="page-title">Historical Replay</div>
        <div className="page-subtitle">
          Verify live implementation matches research/21_strategy_backtest.py
        </div>
      </div>

      {/* Setup card */}
      <div className="card" style={{ marginBottom: 20 }}>
        <div style={{ marginBottom: 12, color: "#94a3b8", fontSize: 13, lineHeight: 1.6 }}>
          Runs the frozen strategy rule against stored parquet files (excluded from repo).
          The replay uses identical logic to the research backtest: 30d DVOL z-score,
          DVOL ≥ 54 regime filter, daily sampling, maker cost model (6bp RT).
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, color: "#94a3b8", fontSize: 13, cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={includeTrain}
              onChange={e => setIncludeTrain(e.target.checked)}
              style={{ accentColor: "#6366f1" }}
            />
            Include 2023 training period
          </label>
          <button
            onClick={runReplay}
            disabled={loading}
            style={{
              background: loading ? "#1e1e2e" : "#6366f1",
              color: loading ? "#64748b" : "white",
              border: "none",
              borderRadius: 6,
              padding: "8px 20px",
              cursor: loading ? "not-allowed" : "pointer",
              fontSize: 13,
              fontWeight: 600,
            }}
          >
            {loading ? "Running replay… (may take 5–10s)" : "Run Replay"}
          </button>
        </div>
        {loading && (
          <div style={{ marginTop: 10, color: "#64748b", fontSize: 12 }}>
            Loading 1.7M bar parquet and computing signals…
          </div>
        )}
      </div>

      {error && (
        <div className="card" style={{ borderColor: "#7f1d1d", color: "#f87171", marginBottom: 20 }}>
          {error}
        </div>
      )}

      {data && summary && target && (
        <>
          {/* Reference targets */}
          <div className="section-title" style={{ marginBottom: 8 }}>
            OOS 2024–2026 vs Research Report Targets
          </div>

          <div className="cards-grid" style={{ marginBottom: 24 }}>
            <div className="card">
              <div className="card-label">Trades</div>
              <div className="card-value" style={{ fontSize: 22 }}>
                {summary.n_trades}
                <MatchBadge actual={summary.n_trades} target={target.n_trades} tolerance={0.05} />
              </div>
              <div className="card-sub">Target: {target.n_trades}</div>
            </div>
            <div className="card">
              <div className="card-label">Sharpe</div>
              <div className="card-value" style={{ color: (summary.sharpe ?? 0) > 2 ? "#4ade80" : "#e2e8f0" }}>
                {summary.sharpe != null ? `${summary.sharpe > 0 ? "+" : ""}${summary.sharpe.toFixed(2)}` : "—"}
                <MatchBadge actual={summary.sharpe} target={target.sharpe} />
              </div>
              <div className="card-sub">Target: +{target.sharpe.toFixed(2)}</div>
            </div>
            <div className="card">
              <div className="card-label">Net PnL</div>
              <div className="card-value" style={{ fontSize: 18 }}>
                <span className={summary.total_pnl_bp > 0 ? "positive" : "negative"}>
                  {bp(summary.total_pnl_bp)}
                </span>
                <MatchBadge actual={summary.total_pnl_bp} target={target.total_pnl_bp} />
              </div>
              <div className="card-sub">Target: +{target.total_pnl_bp.toLocaleString()} bp</div>
            </div>
            <div className="card">
              <div className="card-label">Max Drawdown</div>
              <div className="card-value" style={{ fontSize: 18, color: "#f87171" }}>
                {bp(summary.max_dd_bp)}
                <MatchBadge actual={summary.max_dd_bp} target={target.max_dd_bp} />
              </div>
              <div className="card-sub">Target: {target.max_dd_bp.toLocaleString()} bp</div>
            </div>
            <div className="card">
              <div className="card-label">Win Rate</div>
              <div className="card-value">
                {pct(summary.win_rate)}
                <MatchBadge actual={summary.win_rate} target={target.win_rate} />
              </div>
              <div className="card-sub">Target: {pct(target.win_rate)}</div>
            </div>
            <div className="card">
              <div className="card-label">Avg Win</div>
              <div className="card-value positive" style={{ fontSize: 18 }}>
                {bp(summary.avg_win_bp)}
              </div>
            </div>
            <div className="card">
              <div className="card-label">Avg Loss</div>
              <div className="card-value negative" style={{ fontSize: 18 }}>
                {bp(summary.avg_loss_bp)}
              </div>
            </div>
            <div className="card">
              <div className="card-label">Data Range</div>
              <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 6 }}>
                {data.data_range.start} → {data.data_range.end}
              </div>
              <div className="card-sub">
                Computed {new Date(data.computed_at).toLocaleTimeString()}
              </div>
            </div>
          </div>

          {/* Cumulative PnL chart */}
          {data.trades.length > 1 && (
            <div className="chart-container" style={{ marginBottom: 24 }}>
              <div className="chart-title">Cumulative Net PnL (bp) — Replay</div>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={data.trades}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e1e2e" />
                  <XAxis
                    dataKey="date"
                    tickFormatter={v => v.slice(0, 7)}
                    tick={{ fill: "#64748b", fontSize: 10 }}
                    interval={Math.floor(data.trades.length / 8)}
                  />
                  <YAxis tick={{ fill: "#64748b", fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{ background: "#111118", border: "1px solid #1e1e2e", borderRadius: 6 }}
                    formatter={(v: any) => [
                      `${Number(v) > 0 ? "+" : ""}${Number(v).toFixed(0)} bp`,
                      "Cumulative PnL",
                    ]}
                  />
                  <ReferenceLine y={0} stroke="#2d2d3e" />
                  <Line
                    type="monotone"
                    dataKey="cumulative_pnl_bp"
                    stroke="#6366f1"
                    dot={false}
                    strokeWidth={2}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Period breakdown */}
          {data.period_breakdown.length > 0 && (
            <div className="section" style={{ marginBottom: 24 }}>
              <div className="section-title">Period Breakdown</div>
              <div className="table-wrapper">
                <table>
                  <thead>
                    <tr>
                      <th>Period</th>
                      <th>n</th>
                      <th>Sharpe</th>
                      <th>Net PnL (bp)</th>
                      <th>Max DD (bp)</th>
                      <th>Win %</th>
                      <th>L / S</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.period_breakdown.map(p => (
                      <tr key={p.label} style={{ opacity: p.is_oos ? 1 : 0.6 }}>
                        <td>
                          {p.label}
                          {!p.is_oos && (
                            <span style={{ fontSize: 10, color: "#64748b", marginLeft: 6 }}>train</span>
                          )}
                        </td>
                        <td>{p.n_trades}</td>
                        <td style={{ color: (p.sharpe ?? 0) > 2 ? "#4ade80" : (p.sharpe ?? 0) > 0 ? "#e2e8f0" : "#f87171" }}>
                          {p.sharpe != null ? `${p.sharpe > 0 ? "+" : ""}${p.sharpe.toFixed(2)}` : "—"}
                        </td>
                        <td>
                          <span className={p.total_pnl_bp > 0 ? "positive" : "negative"}>
                            {bp(p.total_pnl_bp)}
                          </span>
                        </td>
                        <td style={{ color: "#f87171" }}>{bp(p.max_dd_bp)}</td>
                        <td>{pct(p.win_rate)}</td>
                        <td style={{ color: "#64748b", fontSize: 12 }}>
                          {p.longs}L / {p.shorts}S
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Trade log */}
          {data.trades.length > 0 && (
            <div className="section">
              <div className="section-title">
                Trade Log ({data.trades.length} trades)
              </div>
              <div className="table-wrapper" style={{ maxHeight: 400, overflowY: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Side</th>
                      <th>N3z</th>
                      <th>DVOL</th>
                      <th>Price Rtn</th>
                      <th>Funding</th>
                      <th>Net PnL</th>
                      <th>Cumulative</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.trades.map((t, i) => (
                      <tr key={i}>
                        <td style={{ fontSize: 12 }}>{t.date}</td>
                        <td>
                          <span style={{
                            fontSize: 10,
                            padding: "2px 6px",
                            borderRadius: 4,
                            background: t.side === "long" ? "#164e63" : "#4a044e",
                            color: t.side === "long" ? "#67e8f9" : "#f0abfc",
                          }}>
                            {t.side.toUpperCase()}
                          </span>
                        </td>
                        <td style={{ fontSize: 12 }}>{t.n3z.toFixed(2)}</td>
                        <td style={{ fontSize: 12 }}>{t.dvol.toFixed(1)}</td>
                        <td>
                          <span className={t.r24h_bp > 0 ? "positive" : "negative"} style={{ fontSize: 12 }}>
                            {t.r24h_bp > 0 ? "+" : ""}{t.r24h_bp.toFixed(0)}
                          </span>
                        </td>
                        <td style={{ fontSize: 12, color: t.fund_24h_bp > 0 ? "#f87171" : "#64748b" }}>
                          {t.fund_24h_bp.toFixed(0)}
                        </td>
                        <td>
                          <span className={t.net_pnl_bp > 0 ? "positive" : "negative"} style={{ fontSize: 12 }}>
                            {t.net_pnl_bp > 0 ? "+" : ""}{t.net_pnl_bp.toFixed(0)}
                          </span>
                        </td>
                        <td>
                          <span className={t.cumulative_pnl_bp > 0 ? "positive" : "negative"} style={{ fontSize: 12 }}>
                            {t.cumulative_pnl_bp > 0 ? "+" : ""}{t.cumulative_pnl_bp.toFixed(0)}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
