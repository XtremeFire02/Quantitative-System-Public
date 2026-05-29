import React, { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";
import { SkeletonCards } from "../components/Skeleton";
import { api, PerformanceData, PerformanceByStrategyResponse } from "../api";

const fmt = (v: number | null, dec = 2) =>
  v == null ? "—" : v.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });

const pct = (v: number | null, dec = 1) =>
  v == null ? "—" : `${(v * 100).toFixed(dec)}%`;

const tooltipStyle = { background: "#0d0d0d", border: "1px solid #2a2a2a", color: "#cccccc" };

export default function Performance() {
  const [data, setData] = useState<PerformanceData | null>(null);
  const [byStrat, setByStrat] = useState<PerformanceByStrategyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.allSettled([api.performance(), api.performanceByStrategy()])
      .then(([perfRes, stratRes]) => {
        if (perfRes.status === "fulfilled") setData(perfRes.value);
        else setError((perfRes.reason as Error).message);
        if (stratRes.status === "fulfilled") setByStrat(stratRes.value);
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <><div className="page-header"><div className="page-title">Performance</div></div><SkeletonCards n={8} /></>;
  if (error) return <div className="error-msg">Error: {error}</div>;
  if (!data) return <div className="error-msg">Failed to load performance data.</div>;
  if (data.total_trades === 0) {
    return (
      <div>
        <div className="page-header">
          <div className="page-title">Performance</div>
        </div>
        <div className="card" style={{ color: "#555555", textAlign: "center", padding: 40 }}>
          No closed trades yet. Performance metrics will appear here once trades complete.
        </div>
      </div>
    );
  }

  const eqHistory = data.equity_history ?? [];
  const ddHistory = eqHistory.map(p => ({ ...p, drawdown_pct: p.drawdown * 100 }));

  return (
    <div>
      <div className="page-header">
        <div className="page-title">Performance</div>
        <div className="page-subtitle">N3_DVOL_Fear_Resolution_v1 · Paper trading results</div>
      </div>

      <div className="cards-grid">
        <div className="card">
          <div className="card-label">Sharpe</div>
          <div className="card-value" style={{ color: (data.sharpe ?? 0) > 2 ? "#00cc44" : "#cccccc" }}>
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
          <div className="card-value" style={{ fontSize: 18, color: "#ff3333" }}>
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

      {eqHistory.length > 1 && (
        <div className="chart-container" style={{ marginTop: 24 }}>
          <div className="chart-title">Equity Curve</div>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={eqHistory}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" />
              <XAxis dataKey="timestamp"
                tickFormatter={v => new Date(v).toLocaleDateString()}
                tick={{ fill: "#555555", fontSize: 10 }} />
              <YAxis tick={{ fill: "#555555", fontSize: 10 }} domain={["auto", "auto"]} />
              <Tooltip contentStyle={tooltipStyle}
                labelFormatter={(v: any) => new Date(v).toLocaleString()}
                formatter={(v: any) => [`$${Number(v).toFixed(2)}`, "Equity"]} />
              <ReferenceLine y={10000} stroke="#2a2a2a" strokeDasharray="4 4" />
              <Line type="monotone" dataKey="equity" stroke="#ff6600" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {ddHistory.length > 1 && (
        <div className="chart-container">
          <div className="chart-title">Drawdown</div>
          <ResponsiveContainer width="100%" height={160}>
            <LineChart data={ddHistory}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" />
              <XAxis dataKey="timestamp"
                tickFormatter={v => new Date(v).toLocaleDateString()}
                tick={{ fill: "#555555", fontSize: 10 }} />
              <YAxis tick={{ fill: "#555555", fontSize: 10 }}
                tickFormatter={v => `${v.toFixed(1)}%`} />
              <Tooltip contentStyle={tooltipStyle}
                formatter={(v: any) => [`${Number(v).toFixed(2)}%`, "Drawdown"]} />
              <ReferenceLine y={0} stroke="#2a2a2a" />
              <Line type="monotone" dataKey="drawdown_pct" stroke="#ff3333" dot={false} strokeWidth={1.5} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {(data.yearly_breakdown ?? []).length > 0 && (
        <div className="section">
          <div className="section-title">Year-by-Year</div>
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Year</th><th>Trades</th><th>Net PnL (bp)</th><th>Sharpe</th><th>Win Rate</th>
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
                    <td style={{ color: (y.sharpe ?? 0) > 2 ? "#00cc44" : "#cccccc" }}>
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

      {byStrat && (byStrat.strategies.length > 0 || byStrat.combinations.length > 0) && (
        <div className="section">
          <div className="section-title">Per-Strategy Breakdown</div>
          {byStrat.strategies.length > 0 && (
            <div className="table-wrapper" style={{ marginBottom: 20 }}>
              <table>
                <thead>
                  <tr>
                    <th>Strategy</th><th>Trades</th><th>Total PnL (bp)</th>
                    <th>Sharpe</th><th>Win Rate</th><th>Avg Win (bp)</th><th>Avg Loss (bp)</th>
                  </tr>
                </thead>
                <tbody>
                  {byStrat.strategies.map(s => (
                    <tr key={s.strategy_name}>
                      <td style={{ fontFamily: "monospace", fontSize: 12 }}>{s.strategy_name}</td>
                      <td>{s.n_trades}</td>
                      <td>
                        <span className={s.total_pnl_bp > 0 ? "positive" : "negative"}>
                          {s.total_pnl_bp > 0 ? "+" : ""}{fmt(s.total_pnl_bp, 0)} bp
                        </span>
                      </td>
                      <td style={{ color: (s.sharpe ?? 0) > 2 ? "#00cc44" : "#cccccc" }}>
                        {s.sharpe != null ? (s.sharpe > 0 ? "+" : "") + fmt(s.sharpe, 2) : "—"}
                      </td>
                      <td>{pct(s.win_rate)}</td>
                      <td className="positive">{s.avg_win_bp != null ? `+${fmt(s.avg_win_bp, 0)} bp` : "—"}</td>
                      <td className="negative">{s.avg_loss_bp != null ? `${fmt(s.avg_loss_bp, 0)} bp` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {byStrat.combinations.length > 0 && (
            <>
              <div className="section-title" style={{ fontSize: 12, marginBottom: 8 }}>Cross-Strategy Combinations</div>
              <div className="table-wrapper">
                <table>
                  <thead>
                    <tr>
                      <th>Combination</th><th>Trades</th><th>Total PnL (bp)</th>
                      <th>Sharpe</th><th>Win Rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {byStrat.combinations.map(c => (
                      <tr key={c.label}>
                        <td style={{ color: "#666666", fontSize: 12 }}>{c.label}</td>
                        <td>{c.n_trades}</td>
                        <td>
                          <span className={c.total_pnl_bp > 0 ? "positive" : "negative"}>
                            {c.total_pnl_bp > 0 ? "+" : ""}{fmt(c.total_pnl_bp, 0)} bp
                          </span>
                        </td>
                        <td style={{ color: (c.sharpe ?? 0) > 2 ? "#00cc44" : "#cccccc" }}>
                          {c.sharpe != null ? (c.sharpe > 0 ? "+" : "") + fmt(c.sharpe, 2) : "—"}
                        </td>
                        <td>{pct(c.win_rate)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
