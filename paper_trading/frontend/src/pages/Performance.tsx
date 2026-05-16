import React, { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";
import { api, PerformanceData } from "../api";

const fmt = (v: number | null, dec = 2) =>
  v == null ? "—" : v.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });

const pct = (v: number | null, dec = 1) =>
  v == null ? "—" : `${(v * 100).toFixed(dec)}%`;

export default function Performance() {
  const [data, setData] = useState<PerformanceData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.performance().then(setData).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="loading">Loading performance…</div>;
  if (!data) return null;
  if (data.total_trades === 0) {
    return (
      <div>
        <div className="page-header">
          <div className="page-title">Performance</div>
        </div>
        <div className="card" style={{ color: "#64748b", textAlign: "center", padding: 40 }}>
          No closed trades yet. Performance metrics will appear here once trades complete.
        </div>
      </div>
    );
  }

  const eqHistory = data.equity_history ?? [];
  const ddHistory = eqHistory.map(p => ({
    ...p,
    drawdown_pct: (p.drawdown * 100),
  }));

  return (
    <div>
      <div className="page-header">
        <div className="page-title">Performance</div>
        <div className="page-subtitle">Paper trading equity curve and strategy metrics</div>
      </div>

      {/* Summary stats */}
      <div className="cards-grid">
        <div className="card">
          <div className="card-label">Sharpe</div>
          <div className="card-value" style={{ color: (data.sharpe ?? 0) > 2 ? "#4ade80" : "#e2e8f0" }}>
            {data.sharpe != null ? (data.sharpe > 0 ? "+" : "") + fmt(data.sharpe, 2) : "—"}
          </div>
          <div className="card-sub">Annualised</div>
        </div>
        <div className="card">
          <div className="card-label">Total PnL</div>
          <div className="card-value" style={{ fontSize: 18 }}>
            <span className={((data.total_pnl_bp ?? 0) > 0) ? "positive" : "negative"}>
              {(data.total_pnl_bp ?? 0) > 0 ? "+" : ""}{fmt(data.total_pnl_bp ?? null, 0)} bp
            </span>
          </div>
          <div className="card-sub">{data.total_trades} closed trades</div>
        </div>
        <div className="card">
          <div className="card-label">Max Drawdown</div>
          <div className="card-value" style={{ fontSize: 18, color: "#f87171" }}>
            {pct(data.max_drawdown ?? null)}
          </div>
        </div>
        <div className="card">
          <div className="card-label">Win Rate</div>
          <div className="card-value">{pct(data.win_rate ?? null)}</div>
        </div>
        <div className="card">
          <div className="card-label">Avg Win</div>
          <div className="card-value positive" style={{ fontSize: 18 }}>
            +{fmt(data.average_win_bp ?? null, 0)} bp
          </div>
        </div>
        <div className="card">
          <div className="card-label">Avg Loss</div>
          <div className="card-value negative" style={{ fontSize: 18 }}>
            {fmt(data.average_loss_bp ?? null, 0)} bp
          </div>
        </div>
        <div className="card">
          <div className="card-label">Profit Factor</div>
          <div className="card-value">{fmt(data.profit_factor ?? null, 2)}</div>
          <div className="card-sub">Win PnL / |Loss PnL|</div>
        </div>
      </div>

      {/* Equity curve */}
      {eqHistory.length > 1 && (
        <div className="chart-container" style={{ marginTop: 24 }}>
          <div className="chart-title">Equity Curve</div>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={eqHistory}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e1e2e" />
              <XAxis dataKey="timestamp"
                tickFormatter={v => new Date(v).toLocaleDateString()}
                tick={{ fill: "#64748b", fontSize: 10 }} />
              <YAxis tick={{ fill: "#64748b", fontSize: 10 }} domain={["auto", "auto"]} />
              <Tooltip
                contentStyle={{ background: "#111118", border: "1px solid #1e1e2e", borderRadius: 6 }}
                labelFormatter={v => new Date(v).toLocaleString()}
                formatter={(v: any) => [`$${Number(v).toFixed(2)}`, "Equity"]} />
              <ReferenceLine y={10000} stroke="#2d2d3e" strokeDasharray="4 4" />
              <Line type="monotone" dataKey="equity" stroke="#6366f1"
                dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Drawdown chart */}
      {ddHistory.length > 1 && (
        <div className="chart-container">
          <div className="chart-title">Drawdown</div>
          <ResponsiveContainer width="100%" height={160}>
            <LineChart data={ddHistory}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e1e2e" />
              <XAxis dataKey="timestamp"
                tickFormatter={v => new Date(v).toLocaleDateString()}
                tick={{ fill: "#64748b", fontSize: 10 }} />
              <YAxis tick={{ fill: "#64748b", fontSize: 10 }}
                tickFormatter={v => `${v.toFixed(1)}%`} />
              <Tooltip
                contentStyle={{ background: "#111118", border: "1px solid #1e1e2e", borderRadius: 6 }}
                formatter={(v: any) => [`${Number(v).toFixed(2)}%`, "Drawdown"]} />
              <ReferenceLine y={0} stroke="#2d2d3e" />
              <Line type="monotone" dataKey="drawdown_pct" stroke="#f87171"
                dot={false} strokeWidth={1.5} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Yearly breakdown */}
      {(data.yearly_breakdown ?? []).length > 0 && (
        <div className="section">
          <div className="section-title">Year-by-Year</div>
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Year</th>
                  <th>Trades</th>
                  <th>Net PnL (bp)</th>
                  <th>Sharpe</th>
                  <th>Win Rate</th>
                </tr>
              </thead>
              <tbody>
                {data.yearly_breakdown!.map(y => (
                  <tr key={y.year}>
                    <td>{y.year}</td>
                    <td>{y.n_trades}</td>
                    <td>
                      <span className={y.total_pnl_bp > 0 ? "positive" : "negative"}>
                        {y.total_pnl_bp > 0 ? "+" : ""}{fmt(y.total_pnl_bp, 0)} bp
                      </span>
                    </td>
                    <td style={{ color: (y.sharpe ?? 0) > 2 ? "#4ade80" : "#e2e8f0" }}>
                      {y.sharpe != null ? (y.sharpe > 0 ? "+" : "") + fmt(y.sharpe, 2) : "—"}
                    </td>
                    <td>{pct(y.win_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
