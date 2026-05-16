import React, { useEffect, useState } from "react";
import { api, ForwardLogResponse, ForwardLogRow, ForwardLogStats } from "../api";

function StatBox({ label, stats }: { label: string; stats: ForwardLogStats }) {
  return (
    <div className="card" style={{ minWidth: 160 }}>
      <div className="card-label">{label}</div>
      <div style={{ marginTop: 8, fontSize: 12, lineHeight: 1.8 }}>
        <div>n = <strong>{stats.n}</strong></div>
        <div>Sharpe = <strong style={{ color: stats.sharpe !== null && stats.sharpe > 0 ? "#4ade80" : "#f87171" }}>
          {stats.sharpe !== null ? stats.sharpe.toFixed(2) : "—"}
        </strong></div>
        <div>PnL = <strong style={{ color: stats.total_pnl_bp >= 0 ? "#4ade80" : "#f87171" }}>
          {stats.total_pnl_bp >= 0 ? "+" : ""}{stats.total_pnl_bp.toFixed(0)} bp
        </strong></div>
        <div>Win rate = <strong>
          {stats.win_rate !== null ? `${(stats.win_rate * 100).toFixed(0)}%` : "—"}
        </strong></div>
      </div>
    </div>
  );
}

function PnLCell({ val }: { val: number | null }) {
  if (val === null) return <td style={{ color: "#64748b" }}>—</td>;
  const color = val >= 0 ? "#4ade80" : "#f87171";
  return <td style={{ fontFamily: "monospace", color }}>{val >= 0 ? "+" : ""}{val.toFixed(1)}</td>;
}

export default function ForwardLog() {
  const [data, setData] = useState<ForwardLogResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  const load = () => {
    setLoading(true);
    api.forwardLog("P3_OIPD_DD", 500)
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading) return <div className="loading">Loading…</div>;
  if (error) return <div className="card" style={{ color: "#f87171" }}>Error: {error}</div>;
  if (!data) return null;

  const summary = data.summary ?? {
    all_trades: { n: 0, sharpe: null, total_pnl_bp: 0, win_rate: null },
    exclusive_trades: { n: 0, sharpe: null, total_pnl_bp: 0, win_rate: null },
    overlap_trades: { n: 0, sharpe: null, total_pnl_bp: 0, win_rate: null },
  };

  const rows = showAll ? data.rows : data.rows.filter(r => r.signal_fired);

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="page-title">P3 Forward Log</div>
          <div className="page-subtitle">
            Shadow evaluations — one row per day including no-signal days.
            Independence key metric: exclusive-trade Sharpe (OOS baseline: +5.18, p=0.007).
          </div>
        </div>
        <button className="btn btn-ghost" onClick={load}>↻ Refresh</button>
      </div>

      {/* Summary stats */}
      <div style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap" }}>
        <StatBox label="All trades" stats={summary.all_trades} />
        <StatBox label="P3-exclusive (independence monitor)" stats={summary.exclusive_trades} />
        <StatBox label="N3 overlap" stats={summary.overlap_trades} />
        <div className="card" style={{ minWidth: 140 }}>
          <div className="card-label">Evaluations</div>
          <div style={{ marginTop: 8, fontSize: 12, lineHeight: 1.8 }}>
            <div>Total: <strong>{data.n_evaluations}</strong></div>
            <div>Traded: <strong>{data.n_trades}</strong></div>
            <div>Exclusive: <strong>{data.n_exclusive}</strong></div>
            <div>Overlap: <strong>{data.n_overlap}</strong></div>
          </div>
        </div>
      </div>

      {/* Filter toggle */}
      <div style={{ marginBottom: 12 }}>
        <button
          className={`btn ${showAll ? "btn-secondary" : "btn-ghost"}`}
          onClick={() => setShowAll(s => !s)}
        >
          {showAll ? "Show signals only" : "Show all evaluations"}
        </button>
      </div>

      {/* Table */}
      <div className="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>DVOL</th>
              <th>Regime</th>
              <th>ΔP 24h</th>
              <th>ΔOI 24h</th>
              <th>Signal</th>
              <th>Exclusive</th>
              <th>N3?</th>
              <th>Status</th>
              <th>Net PnL (bp)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.date} style={{ opacity: r.signal_fired ? 1 : 0.5 }}>
                <td style={{ fontFamily: "monospace", fontSize: 11 }}>{r.date}</td>
                <td style={{ fontFamily: "monospace" }}>{r.dvol?.toFixed(1) ?? "—"}</td>
                <td style={{ fontFamily: "monospace", fontSize: 11, color: "#64748b" }}>{r.regime ?? "—"}</td>
                <td style={{ fontFamily: "monospace", fontSize: 12, color: (r.dp_pct ?? 0) < 0 ? "#f87171" : "#4ade80" }}>
                  {r.dp_pct !== null ? `${r.dp_pct >= 0 ? "+" : ""}${r.dp_pct.toFixed(2)}%` : "—"}
                </td>
                <td style={{ fontFamily: "monospace", fontSize: 12, color: (r.doi_pct ?? 0) < 0 ? "#f87171" : "#4ade80" }}>
                  {r.doi_pct !== null ? `${r.doi_pct >= 0 ? "+" : ""}${r.doi_pct.toFixed(2)}%` : "—"}
                </td>
                <td>
                  {r.signal_fired
                    ? <span className="badge badge-green">YES</span>
                    : <span className="badge badge-gray">no</span>}
                </td>
                <td>
                  {r.p3_exclusive
                    ? <span className="badge badge-green">EXCL</span>
                    : r.signal_fired
                      ? <span className="badge badge-yellow">OVERLAP</span>
                      : <span style={{ color: "#334155" }}>—</span>}
                </td>
                <td style={{ fontSize: 11, color: r.n3_also_fired ? "#60a5fa" : "#334155" }}>
                  {r.n3_also_fired ? "✓" : "—"}
                </td>
                <td style={{ fontSize: 11, color: "#64748b" }}>{r.trade_status ?? "—"}</td>
                <PnLCell val={r.net_pnl_bp} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {rows.length === 0 && (
        <div className="card" style={{ color: "#64748b", marginTop: 12 }}>No rows to display.</div>
      )}
    </div>
  );
}
