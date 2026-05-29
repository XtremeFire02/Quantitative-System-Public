import React, { useEffect, useState } from "react";
import { api, ForwardLogResponse, ForwardLogStats, ForwardSummaryData } from "../api";

const TABS = [
  { label: "P3 Log", strategy: "P3_OIPD_DD" },
  { label: "N3 Log", strategy: "N3_DVOL_LONG" },
] as const;

function StatBox({ label, stats }: { label: string; stats: ForwardLogStats }) {
  return (
    <div className="card" style={{ minWidth: 160 }}>
      <div className="card-label">{label}</div>
      <div style={{ marginTop: 8, fontSize: 12, lineHeight: 1.8, fontFamily: "Courier New" }}>
        <div>n = <strong>{stats.n}</strong></div>
        <div>Sharpe = <strong style={{ color: stats.sharpe !== null && stats.sharpe > 0 ? "#00cc44" : "#ff3333" }}>
          {stats.sharpe !== null ? stats.sharpe.toFixed(2) : "—"}
        </strong></div>
        <div>PnL = <strong style={{ color: stats.total_pnl_bp >= 0 ? "#00cc44" : "#ff3333" }}>
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
  if (val === null) return <td style={{ color: "#444444" }}>—</td>;
  const color = val >= 0 ? "#00cc44" : "#ff3333";
  return (
    <td style={{ fontFamily: "monospace", color }}>
      {val >= 0 ? "+" : ""}{val.toFixed(1)}
    </td>
  );
}

function P3Table({ data, showAll }: { data: ForwardLogResponse; showAll: boolean }) {
  const rows = showAll ? data.rows : data.rows.filter(r => r.signal_fired);
  return (
    <div className="table-wrapper">
      <table>
        <thead>
          <tr>
            <th>Date</th><th>DVOL</th><th>Regime</th><th>ΔP 24h</th><th>ΔOI 24h</th>
            <th>Signal</th><th>Exclusive</th><th>N3?</th><th>Status</th><th>Net PnL (bp)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.date} style={{ opacity: r.signal_fired ? 1 : 0.4 }}>
              <td style={{ fontFamily: "monospace", fontSize: 11 }}>{r.date}</td>
              <td style={{ fontFamily: "monospace" }}>{r.dvol?.toFixed(1) ?? "—"}</td>
              <td style={{ fontFamily: "monospace", fontSize: 11, color: "#555555" }}>{r.regime ?? "—"}</td>
              <td style={{ fontFamily: "monospace", fontSize: 12, color: (r.dp_pct ?? 0) < 0 ? "#ff3333" : "#00cc44" }}>
                {r.dp_pct !== null ? `${r.dp_pct >= 0 ? "+" : ""}${r.dp_pct.toFixed(2)}%` : "—"}
              </td>
              <td style={{ fontFamily: "monospace", fontSize: 12, color: (r.doi_pct ?? 0) < 0 ? "#ff3333" : "#00cc44" }}>
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
                    : <span style={{ color: "#333333" }}>—</span>}
              </td>
              <td style={{ fontSize: 11, color: r.n3_also_fired ? "#3399ff" : "#333333" }}>
                {r.n3_also_fired ? "✓" : "—"}
              </td>
              <td style={{ fontSize: 11, color: "#555555" }}>{r.trade_status ?? "—"}</td>
              <PnLCell val={r.net_pnl_bp} />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function N3Table({ data, showAll }: { data: ForwardLogResponse; showAll: boolean }) {
  const rows = showAll ? data.rows : data.rows.filter(r => r.signal_fired);
  return (
    <div className="table-wrapper">
      <table>
        <thead>
          <tr>
            <th>Date</th><th>DVOL</th><th>N3z</th><th>Signal</th>
            <th>Signal Price</th><th>Fill</th><th>Quality</th><th>Status</th><th>Net PnL (bp)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.date} style={{ opacity: r.signal_fired ? 1 : 0.4 }}>
              <td style={{ fontFamily: "monospace", fontSize: 11 }}>{r.date}</td>
              <td style={{ fontFamily: "monospace" }}>{r.dvol?.toFixed(1) ?? "—"}</td>
              <td style={{ fontFamily: "monospace", color: "#00cc44" }}>
                {r.n3_z != null ? r.n3_z.toFixed(3) : "—"}
              </td>
              <td>
                {r.signal_fired
                  ? <span className="badge badge-green">YES</span>
                  : <span className="badge badge-gray">no</span>}
              </td>
              <td style={{ fontFamily: "monospace", fontSize: 12 }}>
                {r.entry_price != null ? `$${r.entry_price.toFixed(2)}` : "—"}
              </td>
              <td style={{ fontSize: 11 }}>
                {r.fill_type
                  ? <span className={`badge ${r.fill_type === "maker" ? "badge-green" : "badge-yellow"}`}>
                      {r.fill_type}
                    </span>
                  : <span style={{ color: "#333333" }}>—</span>}
              </td>
              <td style={{ fontFamily: "monospace", fontSize: 11 }}>
                {r.entry_quality != null ? `${r.entry_quality.toFixed(1)}/10` : "—"}
              </td>
              <td style={{ fontSize: 11, color: "#555555" }}>{r.trade_status ?? "—"}</td>
              <PnLCell val={r.net_pnl_bp} />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ForwardLog() {
  const [activeTab, setActiveTab] = useState<typeof TABS[number]>(TABS[0]);
  const [data, setData] = useState<ForwardLogResponse | null>(null);
  const [summary, setSummary] = useState<ForwardSummaryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  const load = (strategy = activeTab.strategy) => {
    setLoading(true);
    setError(null);
    const req = strategy.startsWith("P3") ? api.forwardLog(strategy, 500) : api.forwardLogN3(500);
    req.then(setData).catch(e => setError(e.message)).finally(() => setLoading(false));
  };

  useEffect(() => {
    api.forwardLogSummary().then(setSummary).catch(() => {});
  }, []);

  useEffect(() => { load(activeTab.strategy); }, [activeTab]);

  const switchTab = (tab: typeof TABS[number]) => {
    setData(null);
    setActiveTab(tab);
  };

  const tabStats = data?.summary ?? {
    all_trades:       { n: 0, sharpe: null, total_pnl_bp: 0, win_rate: null },
    exclusive_trades: { n: 0, sharpe: null, total_pnl_bp: 0, win_rate: null },
    overlap_trades:   { n: 0, sharpe: null, total_pnl_bp: 0, win_rate: null },
  };

  const isP3 = activeTab.strategy.startsWith("P3");

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="page-title">Forward Log</div>
          <div className="page-subtitle">
            {isP3
              ? "P3 shadow evaluations — independence key metric: exclusive-trade Sharpe"
              : "N3 live evaluations — execution quality and fill attribution"}
          </div>
        </div>
        <button className="btn btn-ghost" onClick={() => load(activeTab.strategy)}>↻ Refresh</button>
      </div>

      {summary && (
        <div className="card" style={{ marginBottom: 20 }}>
          <div className="card-label" style={{ marginBottom: 12 }}>Combined Summary</div>
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap", fontSize: 12, fontFamily: "Courier New" }}>
            <div>
              <div style={{ color: "#666", marginBottom: 4 }}>N3 DVOL LONG</div>
              <div>trades: <strong>{summary.n3.n}</strong></div>
              <div>Sharpe: <strong style={{ color: summary.n3.sharpe != null && summary.n3.sharpe > 0 ? "#00cc44" : "#ff3333" }}>
                {summary.n3.sharpe != null ? summary.n3.sharpe.toFixed(2) : "—"}
              </strong></div>
              <div>PnL: <strong style={{ color: summary.n3.total_pnl_bp >= 0 ? "#00cc44" : "#ff3333" }}>
                {summary.n3.total_pnl_bp >= 0 ? "+" : ""}{summary.n3.total_pnl_bp.toFixed(0)} bp
              </strong></div>
              <div style={{ color: "#555" }}>{summary.n3.open_positions} open</div>
            </div>
            <div style={{ borderLeft: "1px solid #2a2a2a", paddingLeft: 24 }}>
              <div style={{ color: "#666", marginBottom: 4 }}>P3 OI-Price Divergence</div>
              <div>trades: <strong>{summary.p3.n}</strong></div>
              <div>Sharpe: <strong style={{ color: summary.p3.sharpe != null && summary.p3.sharpe > 0 ? "#00cc44" : "#ff3333" }}>
                {summary.p3.sharpe != null ? summary.p3.sharpe.toFixed(2) : "—"}
              </strong></div>
              <div>PnL: <strong style={{ color: summary.p3.total_pnl_bp >= 0 ? "#00cc44" : "#ff3333" }}>
                {summary.p3.total_pnl_bp >= 0 ? "+" : ""}{summary.p3.total_pnl_bp.toFixed(0)} bp
              </strong></div>
              <div style={{ color: "#555" }}>{summary.p3.open_positions} open</div>
            </div>
            <div style={{ borderLeft: "1px solid #2a2a2a", paddingLeft: 24 }}>
              <div style={{ color: "#666", marginBottom: 4 }}>Regime</div>
              <div>DVOL: <strong>{summary.current_regime.dvol?.toFixed(1) ?? "—"}</strong></div>
              <div>N3z: <strong style={{ color: "#00cc44" }}>{summary.current_regime.n3_z?.toFixed(3) ?? "—"}</strong></div>
              <div>Filter: <strong style={{ color: summary.current_regime.dvol_filter_pass ? "#00cc44" : "#ff3333" }}>
                {summary.current_regime.dvol_filter_pass == null ? "—" : summary.current_regime.dvol_filter_pass ? "PASS" : "FAIL"}
              </strong></div>
              <div style={{ color: "#555" }}>
                {summary.current_regime.last_evaluated ? new Date(summary.current_regime.last_evaluated).toLocaleString() : "—"}
              </div>
            </div>
            {summary.blocked_trades > 0 && (
              <div style={{ borderLeft: "1px solid #2a2a2a", paddingLeft: 24 }}>
                <div style={{ color: "#666", marginBottom: 4 }}>Blocked Trades</div>
                <div style={{ color: "#ffcc00", fontWeight: 700, fontSize: 18 }}>{summary.blocked_trades}</div>
                <div style={{ color: "#555", fontSize: 11 }}>by risk gates</div>
              </div>
            )}
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
        {TABS.map(tab => (
          <button key={tab.strategy}
            className={`btn ${activeTab.strategy === tab.strategy ? "btn-primary" : "btn-ghost"}`}
            onClick={() => switchTab(tab)}>
            {tab.label}
          </button>
        ))}
      </div>

      {loading && <div className="loading">Loading…</div>}
      {error && <div className="card" style={{ color: "#ff3333" }}>Error: {error}</div>}

      {data && !loading && (
        <>
          <div style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap" }}>
            <StatBox label="All trades" stats={tabStats.all_trades} />
            {isP3 && (
              <>
                <StatBox label="P3-exclusive (independence monitor)" stats={tabStats.exclusive_trades} />
                <StatBox label="N3 overlap" stats={tabStats.overlap_trades} />
              </>
            )}
            <div className="card" style={{ minWidth: 140 }}>
              <div className="card-label">Evaluations</div>
              <div style={{ marginTop: 8, fontSize: 12, lineHeight: 1.8, fontFamily: "Courier New" }}>
                <div>Total: <strong>{data.n_evaluations}</strong></div>
                <div>Traded: <strong>{data.n_trades}</strong></div>
                {isP3 && (
                  <>
                    <div>Exclusive: <strong>{data.n_exclusive}</strong></div>
                    <div>Overlap: <strong>{data.n_overlap}</strong></div>
                  </>
                )}
              </div>
            </div>
          </div>

          <div style={{ marginBottom: 12 }}>
            <button className={`btn ${showAll ? "btn-secondary" : "btn-ghost"}`}
              onClick={() => setShowAll(s => !s)}>
              {showAll ? "Signals only" : "All evaluations"}
            </button>
          </div>

          {isP3
            ? <P3Table data={data} showAll={showAll} />
            : <N3Table data={data} showAll={showAll} />}

          {data.rows.filter(r => showAll || r.signal_fired).length === 0 && (
            <div className="card" style={{ color: "#555555", marginTop: 12 }}>No rows to display.</div>
          )}
        </>
      )}
    </div>
  );
}
