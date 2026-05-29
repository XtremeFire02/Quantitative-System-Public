import React, { useEffect, useState } from "react";
import { api, PortfolioAttribution } from "../api";
import { SkeletonCards, SkeletonTable } from "../components/Skeleton";

const fmt = (v: number | null, dec = 1): string => (v == null ? "—" : v.toFixed(dec));

function PnlBp({ bp }: { bp: number | null }) {
  if (bp == null) return <span style={{ color: "#444444" }}>—</span>;
  const color = bp > 0 ? "#00cc44" : bp < 0 ? "#ff3333" : "#666666";
  return <span style={{ fontFamily: "monospace", color, fontWeight: 600 }}>
    {bp > 0 ? "+" : ""}{bp.toFixed(1)}
  </span>;
}

function CorrBadge({ r }: { r: number | null }) {
  if (r == null) return <span style={{ color: "#444444" }}>n/a</span>;
  const abs = Math.abs(r);
  const color = abs < 0.2 ? "#00cc44" : abs < 0.4 ? "#ffcc00" : "#ff3333";
  return <span style={{ fontFamily: "monospace", color, fontWeight: 700, fontSize: 20 }}>
    {r >= 0 ? "+" : ""}{r.toFixed(3)}
  </span>;
}

export default function Portfolio() {
  const [data, setData] = useState<PortfolioAttribution | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    api.portfolio().then(setData).catch(e => setError(e.message)).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading) return <><div className="page-header"><div className="page-title">Portfolio Attribution</div></div><SkeletonCards n={4} /><div style={{marginTop:16}}><SkeletonTable rows={4} cols={8} /></div></>;
  if (error) return <div className="card" style={{ color: "#ff3333" }}>Error: {error}</div>;
  if (!data) return null;

  const {
    strategies, portfolio_total_pnl_bp, portfolio_stats,
    n3_p3_correlation, correlation_n_pairs, open_exposure, total_open_notional_usd,
  } = data;
  const stratEntries = [...strategies].sort((a, b) => (b.total_pnl_bp ?? 0) - (a.total_pnl_bp ?? 0));

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="page-title">Portfolio Attribution</div>
          <div className="page-subtitle">PnL decomposition by strategy, regime, and exposure</div>
        </div>
        <button className="btn btn-ghost" onClick={load}>↻ Refresh</button>
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 24, flexWrap: "wrap" }}>
        <div className="card" style={{ minWidth: 130 }}>
          <div className="card-label">Total PnL</div>
          <div className="card-value" style={{ color: portfolio_total_pnl_bp >= 0 ? "#00cc44" : "#ff3333" }}>
            {portfolio_total_pnl_bp >= 0 ? "+" : ""}{portfolio_total_pnl_bp.toFixed(0)}
            <span style={{ fontSize: 14, marginLeft: 4, fontWeight: 400 }}>bp</span>
          </div>
        </div>
        <div className="card" style={{ minWidth: 130 }}>
          <div className="card-label">Portfolio Sharpe</div>
          <div className="card-value" style={{ color: (portfolio_stats.sharpe ?? 0) >= 0 ? "#00cc44" : "#ff3333" }}>
            {fmt(portfolio_stats.sharpe)}
          </div>
        </div>
        <div className="card" style={{ minWidth: 130 }}>
          <div className="card-label">Strategies</div>
          <div className="card-value">{portfolio_stats.n_strategies}</div>
          <div className="card-sub">{portfolio_stats.n_closed_trades} closed trades</div>
        </div>
        <div className="card" style={{ minWidth: 160 }}>
          <div className="card-label">N3 ↔ P3 Correlation</div>
          <div style={{ marginTop: 8 }}>
            <CorrBadge r={n3_p3_correlation} />
          </div>
          <div className="card-sub" style={{ marginTop: 4 }}>{correlation_n_pairs} overlapping dates</div>
          {total_open_notional_usd > 0 && (
            <div style={{ fontSize: 10, color: "#444444", marginTop: 4 }}>
              Open: ${total_open_notional_usd.toLocaleString("en-US", { maximumFractionDigits: 0 })}
            </div>
          )}
        </div>
      </div>

      <div className="section-title" style={{ marginBottom: 12 }}>Strategy Attribution</div>
      {stratEntries.length === 0 ? (
        <div className="card" style={{ color: "#555555" }}>No closed trades yet.</div>
      ) : (
        <div className="table-wrapper" style={{ marginBottom: 24 }}>
          <table>
            <thead>
              <tr>
                <th>Strategy</th><th>N</th><th>Sharpe</th><th>Total (bp)</th>
                <th>Avg (bp)</th><th>Win Rate</th><th>Max DD (bp)</th><th>Contribution</th>
              </tr>
            </thead>
            <tbody>
              {stratEntries.map((s) => (
                <tr key={s.strategy}>
                  <td style={{ fontFamily: "monospace", fontSize: 12 }}>{s.strategy}</td>
                  <td style={{ fontFamily: "monospace" }}>{s.n}</td>
                  <td>
                    <span style={{ fontFamily: "monospace", color: (s.sharpe ?? 0) >= 0 ? "#00cc44" : "#ff3333" }}>
                      {fmt(s.sharpe)}
                    </span>
                  </td>
                  <td><PnlBp bp={s.total_pnl_bp} /></td>
                  <td><PnlBp bp={s.avg_pnl_bp} /></td>
                  <td style={{ fontFamily: "monospace" }}>
                    {s.win_rate != null ? `${(s.win_rate * 100).toFixed(0)}%` : "—"}
                  </td>
                  <td style={{ fontFamily: "monospace", color: "#ff3333" }}>
                    {s.max_dd_bp != null ? s.max_dd_bp.toFixed(0) : "—"}
                  </td>
                  <td>
                    {s.contribution_pct != null ? (
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <div style={{ width: 60, background: "#1a1a1a", height: 6, border: "1px solid #2a2a2a" }}>
                          <div style={{
                            width: `${Math.max(0, Math.min(100, s.contribution_pct))}%`,
                            height: "100%", background: "#ff6600",
                          }} />
                        </div>
                        <span style={{ fontFamily: "monospace", fontSize: 11 }}>
                          {s.contribution_pct.toFixed(0)}%
                        </span>
                      </div>
                    ) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="section-title" style={{ marginBottom: 12 }}>Open Exposure</div>
      {open_exposure.length === 0 ? (
        <div className="card" style={{ color: "#555555" }}>No open positions.</div>
      ) : (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Strategy</th><th>Market</th><th>Side</th>
                <th>Notional (USD)</th><th>Entry</th><th>Planned Exit</th>
              </tr>
            </thead>
            <tbody>
              {open_exposure.map((pos, i) => (
                <tr key={`${pos.strategy}-${pos.market}-${pos.entry_timestamp ?? i}`}>
                  <td style={{ fontSize: 12 }}>{pos.strategy}</td>
                  <td style={{ fontFamily: "monospace", fontSize: 12 }}>{pos.market}</td>
                  <td>
                    <span className={`badge ${pos.side === "long" ? "badge-green" : "badge-red"}`}>
                      {pos.side.toUpperCase()}
                    </span>
                  </td>
                  <td style={{ fontFamily: "monospace" }}>
                    ${pos.notional_usd.toLocaleString("en-US", { maximumFractionDigits: 0 })}
                  </td>
                  <td style={{ fontSize: 11, color: "#555555" }}>
                    {pos.entry_timestamp ? new Date(pos.entry_timestamp).toLocaleString() : "—"}
                  </td>
                  <td style={{ fontSize: 11, color: "#555555" }}>
                    {pos.planned_exit ? new Date(pos.planned_exit).toLocaleString() : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
