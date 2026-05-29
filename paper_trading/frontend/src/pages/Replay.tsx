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

const tooltipStyle = { background: "#0d0d0d", border: "1px solid #2a2a2a", color: "#cccccc" };

function MatchBadge({ actual, target, tolerance = 0.15 }: {
  actual: number | null | undefined;
  target: number;
  tolerance?: number;
}) {
  if (actual == null) return <span style={{ color: "#555555" }}>—</span>;
  const delta = Math.abs(target) === 0 ? 0 : Math.abs(actual - target) / Math.abs(target);
  const pass = delta <= tolerance;
  return (
    <span style={{
      fontSize: 10, padding: "2px 6px",
      background: pass ? "#001a0d" : "#1a0000",
      color: pass ? "#00cc44" : "#ff3333",
      border: `1px solid ${pass ? "#004422" : "#440000"}`,
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

      <div className="card" style={{ marginBottom: 20 }}>
        <div style={{ marginBottom: 12, color: "#777777", fontSize: 13, lineHeight: 1.6, fontFamily: "Courier New" }}>
          Runs the frozen strategy rule against stored parquet files (excluded from repo).
          The replay uses identical logic to the research backtest: 30d DVOL z-score,
          DVOL ≥ δ regime filter, daily sampling, maker cost model (6bp RT).
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, color: "#777777", fontSize: 13, cursor: "pointer" }}>
            <input type="checkbox" checked={includeTrain}
              onChange={e => setIncludeTrain(e.target.checked)}
              style={{ accentColor: "#ff6600" }}
            />
            Include 2023 training period
          </label>
          <button className={`btn ${loading ? "btn-ghost" : "btn-primary"}`}
            onClick={runReplay} disabled={loading}>
            {loading ? "Running replay… (may take 5–10s)" : "▶ Run Replay"}
          </button>
        </div>
        {loading && (
          <div style={{ marginTop: 10, color: "#555555", fontSize: 12, fontFamily: "Courier New" }}>
            Loading 1.7M bar parquet and computing signals…
          </div>
        )}
      </div>

      {error && <div className="error-msg" style={{ marginBottom: 20 }}>{error}</div>}

      {data && summary && target && (
        <>
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
              <div className="card-value" style={{ color: (summary.sharpe ?? 0) > 2 ? "#00cc44" : "#cccccc" }}>
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
              <div className="card-value" style={{ fontSize: 18, color: "#ff3333" }}>
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
              <div className="card-value positive" style={{ fontSize: 18 }}>{bp(summary.avg_win_bp)}</div>
            </div>
            <div className="card">
              <div className="card-label">Avg Loss</div>
              <div className="card-value negative" style={{ fontSize: 18 }}>{bp(summary.avg_loss_bp)}</div>
            </div>
            <div className="card">
              <div className="card-label">Data Range</div>
              <div style={{ fontSize: 12, color: "#777777", marginTop: 6, fontFamily: "Courier New" }}>
                {data.data_range.start} → {data.data_range.end}
              </div>
              <div className="card-sub">Computed {new Date(data.computed_at).toLocaleTimeString()}</div>
            </div>
          </div>

          {data.trades.length > 1 && (
            <div className="chart-container" style={{ marginBottom: 24 }}>
              <div className="chart-title">Cumulative Net PnL (bp) — Replay</div>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={data.trades}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" />
                  <XAxis dataKey="date" tickFormatter={v => v.slice(0, 7)}
                    tick={{ fill: "#555555", fontSize: 10 }}
                    interval={Math.max(1, Math.floor(data.trades.length / 8))} />
                  <YAxis tick={{ fill: "#555555", fontSize: 10 }} />
                  <Tooltip contentStyle={tooltipStyle}
                    formatter={(v: any) => [`${Number(v) > 0 ? "+" : ""}${Number(v).toFixed(0)} bp`, "Cumulative PnL"]} />
                  <ReferenceLine y={0} stroke="#2a2a2a" />
                  <Line type="monotone" dataKey="cumulative_pnl_bp" stroke="#ff6600" dot={false} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {data.period_breakdown.length > 0 && (
            <div className="section" style={{ marginBottom: 24 }}>
              <div className="section-title">Period Breakdown</div>
              <div className="table-wrapper">
                <table>
                  <thead>
                    <tr>
                      <th>Period</th><th>n</th><th>Sharpe</th>
                      <th>Net PnL (bp)</th><th>Max DD (bp)</th><th>Win %</th><th>L / S</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.period_breakdown.map(p => (
                      <tr key={p.label} style={{ opacity: p.is_oos ? 1 : 0.5 }}>
                        <td>
                          {p.label}
                          {!p.is_oos && <span style={{ fontSize: 10, color: "#444444", marginLeft: 6 }}>train</span>}
                        </td>
                        <td>{p.n_trades}</td>
                        <td style={{ color: (p.sharpe ?? 0) > 2 ? "#00cc44" : (p.sharpe ?? 0) > 0 ? "#cccccc" : "#ff3333" }}>
                          {p.sharpe != null ? `${p.sharpe > 0 ? "+" : ""}${p.sharpe.toFixed(2)}` : "—"}
                        </td>
                        <td><span className={p.total_pnl_bp > 0 ? "positive" : "negative"}>{bp(p.total_pnl_bp)}</span></td>
                        <td style={{ color: "#ff3333" }}>{bp(p.max_dd_bp)}</td>
                        <td>{pct(p.win_rate)}</td>
                        <td style={{ color: "#555555", fontSize: 12 }}>{p.longs}L / {p.shorts}S</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {data.trades.length > 0 && (
            <div className="section">
              <div className="section-title">Trade Log ({data.trades.length} trades)</div>
              <div className="table-wrapper" style={{ maxHeight: 400, overflowY: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Date</th><th>Side</th><th>N3z</th><th>DVOL</th>
                      <th>Price Rtn</th><th>Funding</th><th>Net PnL</th><th>Cumulative</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.trades.map((t, i) => (
                      <tr key={i}>
                        <td style={{ fontSize: 12 }}>{t.date}</td>
                        <td>
                          <span className={`badge ${t.side === "long" ? "badge-blue" : "badge-red"}`}>
                            {t.side.toUpperCase()}
                          </span>
                        </td>
                        <td style={{ fontSize: 12 }}>{t.n3z.toFixed(2)}</td>
                        <td style={{ fontSize: 12 }}>{t.dvol.toFixed(1)}</td>
                        <td><span className={t.r24h_bp > 0 ? "positive" : "negative"} style={{ fontSize: 12 }}>
                          {t.r24h_bp > 0 ? "+" : ""}{t.r24h_bp.toFixed(0)}
                        </span></td>
                        <td style={{ fontSize: 12, color: t.fund_24h_bp > 0 ? "#ff3333" : "#555555" }}>
                          {t.fund_24h_bp.toFixed(0)}
                        </td>
                        <td><span className={t.net_pnl_bp > 0 ? "positive" : "negative"} style={{ fontSize: 12 }}>
                          {t.net_pnl_bp > 0 ? "+" : ""}{t.net_pnl_bp.toFixed(0)}
                        </span></td>
                        <td><span className={t.cumulative_pnl_bp > 0 ? "positive" : "negative"} style={{ fontSize: 12 }}>
                          {t.cumulative_pnl_bp > 0 ? "+" : ""}{t.cumulative_pnl_bp.toFixed(0)}
                        </span></td>
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
