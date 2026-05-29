import React, { useEffect, useState } from "react";
import { api, PortfolioState } from "../api";

function GaugeBar({ used, label }: { used: number; label: string }) {
  const pct = Math.min(Math.max(used, 0), 100);
  const color = pct >= 80 ? "#ff3333" : pct >= 50 ? "#ffcc00" : "#00cc44";
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#666666", marginBottom: 4 }}>
        <span>{label}</span>
        <span style={{ color }}>{pct.toFixed(0)}%</span>
      </div>
      <div style={{ background: "#1a1a1a", height: 6, border: "1px solid #2a2a2a" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, transition: "width 0.3s" }} />
      </div>
    </div>
  );
}

function LimitRow({ label, value, limit, unit = "" }: { label: string; value: number; limit: number; unit?: string }) {
  const ok = value < limit;
  return (
    <tr>
      <td style={{ color: "#666666" }}>{label}</td>
      <td style={{ fontFamily: "monospace" }}>{value}{unit}</td>
      <td style={{ color: "#555555" }}>{limit}{unit}</td>
      <td><span className={`badge ${ok ? "badge-green" : "badge-red"}`}>{ok ? "OK" : "BREACH"}</span></td>
    </tr>
  );
}

export default function RiskDashboard() {
  const [state, setState] = useState<PortfolioState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    api.riskState().then(setState).catch(e => setError(e.message)).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading) return <div className="loading">Loading…</div>;
  if (error) return <div className="card" style={{ color: "#ff3333" }}>Error: {error}</div>;
  if (!state) return null;

  const dailyLossUsed = (state.daily_pnl_bp < 0 && state.daily_loss_limit_bp !== 0)
    ? Math.abs(state.daily_pnl_bp / state.daily_loss_limit_bp) * 100 : 0;
  const positionUsed = (state.total_open / state.max_total_open) * 100;

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="page-title">Portfolio Risk</div>
          <div className="page-subtitle">Live exposure and hard limits</div>
        </div>
        <button className="btn btn-ghost" onClick={load}>↻ Refresh</button>
      </div>

      <div className="card" style={{ marginBottom: 20 }}>
        <div className="card-label" style={{ marginBottom: 16 }}>Limit Usage</div>
        <GaugeBar used={positionUsed} label={`Open positions: ${state.total_open}/${state.max_total_open}`} />
        <GaugeBar used={dailyLossUsed} label={`Daily loss: ${state.daily_pnl_bp?.toFixed(1) ?? "—"} / ${state.daily_loss_limit_bp?.toFixed(0) ?? "—"} bp`} />
        {state.limits.max_gross_notional_usd > 0 && (
          <GaugeBar used={state.notional_limit_used_pct} label={`Gross notional: $${(state.gross_notional_usd / 1000).toFixed(0)}K / $${(state.limits.max_gross_notional_usd / 1000).toFixed(0)}K`} />
        )}
      </div>

      <div className="section-title">Hard Limits</div>
      <div className="table-wrapper" style={{ marginBottom: 24 }}>
        <table>
          <thead>
            <tr><th>Limit</th><th>Current</th><th>Max</th><th>Status</th></tr>
          </thead>
          <tbody>
            <LimitRow label="Total open positions" value={state.total_open} limit={state.max_total_open} />
            <LimitRow label="Daily PnL (bp)" value={state.daily_pnl_bp} limit={state.daily_loss_limit_bp} unit=" bp" />
          </tbody>
        </table>
      </div>

      <div className="section-title">Open Positions</div>
      {state.positions.length === 0 ? (
        <div className="card" style={{ color: "#555555" }}>No open positions.</div>
      ) : (
        <div className="table-wrapper" style={{ marginBottom: 24 }}>
          <table>
            <thead>
              <tr>
                <th>Trade #</th><th>Strategy</th><th>Market</th><th>Side</th>
                <th>Entry Price</th><th>DVOL</th><th>Planned Exit</th>
              </tr>
            </thead>
            <tbody>
              {state.positions.map(p => (
                <tr key={p.trade_id}>
                  <td style={{ fontFamily: "monospace", color: "#555555" }}>#{p.trade_id}</td>
                  <td>{p.strategy}</td>
                  <td>{p.market}</td>
                  <td>
                    <span className={`badge ${p.side === "long" ? "badge-green" : "badge-red"}`}>
                      {p.side.toUpperCase()}
                    </span>
                  </td>
                  <td style={{ fontFamily: "monospace" }}>${p.entry_price?.toLocaleString()}</td>
                  <td style={{ fontFamily: "monospace" }}>{p.entry_dvol?.toFixed(1) ?? "—"}</td>
                  <td style={{ fontSize: 11, color: "#555555" }}>
                    {p.planned_exit ? new Date(p.planned_exit).toLocaleString() : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {Object.keys(state.strategy_drawdowns).length > 0 && (
        <>
          <div className="section-title">Strategy Trailing Drawdowns (last 20 trades)</div>
          <div className="table-wrapper" style={{ marginBottom: 24 }}>
            <table>
              <thead>
                <tr><th>Strategy</th><th>Trailing DD</th><th>Limit</th><th>Consec. Losses</th><th>Status</th></tr>
              </thead>
              <tbody>
                {Object.entries(state.strategy_drawdowns).map(([name, dd]) => {
                  const ddPct = dd !== null ? dd * 100 : null;
                  const limitPct = state.limits.max_strategy_drawdown_pct * 100;
                  const consec = state.strategy_consecutive_losses?.[name] ?? 0;
                  const maxConsec = state.limits.max_consecutive_losses;
                  const ddOk = ddPct === null || ddPct > limitPct;
                  const consecOk = maxConsec === 0 || consec < maxConsec;
                  const ok = ddOk && consecOk;
                  return (
                    <tr key={name}>
                      <td>{name}</td>
                      <td style={{ fontFamily: "monospace" }}>
                        {ddPct !== null ? `${ddPct.toFixed(2)}%` : "< 5 trades"}
                      </td>
                      <td style={{ color: "#555555" }}>{limitPct.toFixed(0)}%</td>
                      <td style={{ fontFamily: "monospace", color: consec > 0 ? "#ffcc00" : "#555555" }}>
                        {consec}{maxConsec > 0 ? ` / ${maxConsec}` : ""}
                      </td>
                      <td>
                        <span className={`badge ${ok ? "badge-green" : "badge-red"}`}>
                          {ok ? "OK" : "TRIPPED"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
