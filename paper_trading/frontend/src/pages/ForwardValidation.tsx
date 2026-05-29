import React, { useEffect, useState } from "react";
import { api, FwdValidationReport, FwdValidationComparison } from "../api";

const STATUS_COLOR: Record<string, string> = {
  on_track:          "#00cc44",
  drift_detected:    "#ff3333",
  no_baseline:       "#666666",
  insufficient_data: "#ff6600",
};

const STATUS_LABEL: Record<string, string> = {
  on_track:          "On Track",
  drift_detected:    "Drift Detected",
  no_baseline:       "No Baseline",
  insufficient_data: "Insufficient Data",
};

function StatusBadge({ status }: { status: string }) {
  const color = STATUS_COLOR[status] ?? "#666666";
  return (
    <span style={{
      display: "inline-block", padding: "2px 8px",
      fontSize: 11, fontWeight: 700, background: `${color}18`,
      color, border: `1px solid ${color}44`,
    }}>
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

function AchievementBar({ pct }: { pct: number | null }) {
  if (pct === null) return <span style={{ color: "#555555" }}>—</span>;
  const clamped = Math.max(0, Math.min(150, pct));
  const color = pct >= 100 ? "#00cc44" : pct >= 80 ? "#ffcc00" : "#ff3333";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ flex: 1, background: "#1a1a1a", height: 8, maxWidth: 80, border: "1px solid #2a2a2a" }}>
        <div style={{ width: `${Math.min(100, clamped)}%`, height: "100%", background: color, transition: "width 0.3s" }} />
      </div>
      <span style={{ fontFamily: "monospace", fontSize: 12, color }}>{pct.toFixed(0)}%</span>
    </div>
  );
}

function fmt(v: number | null, dec = 2): string {
  if (v == null) return "—";
  return v.toFixed(dec);
}

function ComparisonRow({ label, live, research }: { label: string; live: string; research: string }) {
  return (
    <tr>
      <td style={{ color: "#666666", fontSize: 12 }}>{label}</td>
      <td style={{ fontFamily: "monospace", fontSize: 12 }}>{live}</td>
      <td style={{ fontFamily: "monospace", fontSize: 12, color: "#555555" }}>{research}</td>
    </tr>
  );
}

function StrategyDetail({ name, data }: {
  name: string;
  data: { live: FwdValidationReport["strategies"][string]["live"]; comparison: FwdValidationComparison };
}) {
  const { live, comparison } = data;
  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 14, fontFamily: "Courier New", color: "#e0e0e0" }}>{name}</div>
          {comparison.research_run_id && (
            <div style={{ fontSize: 11, color: "#555555", marginTop: 2 }}>
              Baseline: {comparison.research_run_id}
              {comparison.research_data_range && ` · ${comparison.research_data_range}`}
            </div>
          )}
        </div>
        <StatusBadge status={comparison.status} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div>
          <div style={{ fontSize: 11, color: "#555555", marginBottom: 6 }}>LIVE vs RESEARCH</div>
          <table style={{ width: "100%" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", fontSize: 11, color: "#555555", fontWeight: 400, background: "none", borderBottom: "none", padding: "2px 4px" }}>Metric</th>
                <th style={{ textAlign: "left", fontSize: 11, color: "#555555", fontWeight: 400, background: "none", borderBottom: "none", padding: "2px 4px" }}>Live</th>
                <th style={{ textAlign: "left", fontSize: 11, color: "#555555", fontWeight: 400, background: "none", borderBottom: "none", padding: "2px 4px" }}>Research</th>
              </tr>
            </thead>
            <tbody>
              <ComparisonRow label="Sharpe" live={fmt(comparison.live_sharpe)} research={fmt(comparison.research_sharpe)} />
              <ComparisonRow label="Win Rate"
                live={live.win_rate != null ? `${(live.win_rate * 100).toFixed(0)}%` : "—"}
                research={comparison.research_win_rate != null ? `${(comparison.research_win_rate * 100).toFixed(0)}%` : "—"} />
              <ComparisonRow label="Avg PnL (bp)" live={fmt(comparison.live_avg_pnl_bp, 1)} research={fmt(comparison.research_avg_pnl_bp, 1)} />
              <ComparisonRow label="N Closed" live={String(live.n_closed)} research="—" />
            </tbody>
          </table>
        </div>

        <div>
          <div style={{ fontSize: 11, color: "#555555", marginBottom: 6 }}>SHARPE ACHIEVEMENT</div>
          <div style={{ marginBottom: 12 }}>
            <AchievementBar pct={comparison.sharpe_achievement_pct} />
          </div>
          <div style={{ fontSize: 11, color: "#777777", lineHeight: 1.7 }}>
            {comparison.message}
          </div>
          {live.first_trade && (
            <div style={{ fontSize: 10, color: "#444444", marginTop: 8 }}>
              Period: {new Date(live.first_trade).toLocaleDateString()} →{" "}
              {live.last_trade ? new Date(live.last_trade).toLocaleDateString() : "open"}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ForwardValidation() {
  const [data, setData] = useState<FwdValidationReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = () => {
    setLoading(true);
    api.fwdValidation().then(setData).catch(e => setError(e.message)).finally(() => setLoading(false));
  };

  const refresh = () => {
    setRefreshing(true);
    api.refreshFwdValidation().then(setData).catch(e => setError(e.message)).finally(() => setRefreshing(false));
  };

  useEffect(() => { load(); }, []);

  if (loading) return <div className="loading">Loading…</div>;
  if (error) return <div className="card" style={{ color: "#ff3333" }}>Error: {error}</div>;
  if (!data) return null;

  const { summary, strategies, generated_at } = data;

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="page-title">Forward Validation</div>
          <div className="page-subtitle">
            Live paper-trade performance vs. research expectations.
            Generated: {new Date(generated_at).toLocaleString()}
          </div>
        </div>
        <div className="btn-row" style={{ marginBottom: 0 }}>
          <button className="btn btn-ghost" onClick={load}>↻ Cached</button>
          <button className="btn btn-secondary" onClick={refresh} disabled={refreshing}>
            {refreshing ? "Regenerating…" : "↻ Regenerate"}
          </button>
        </div>
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 24, flexWrap: "wrap" }}>
        {[
          { label: "Strategies",    value: summary.total_strategies, color: "#cccccc" },
          { label: "On Track",      value: summary.on_track,          color: "#00cc44" },
          { label: "Drift",         value: summary.drift_detected,    color: "#ff3333" },
          { label: "No Baseline",   value: summary.no_baseline,       color: "#555555" },
          { label: "Too Few Trades",value: summary.insufficient_data, color: "#ff6600" },
        ].map(({ label, value, color }) => (
          <div key={label} className="card" style={{ minWidth: 110, textAlign: "center" }}>
            <div className="card-label">{label}</div>
            <div style={{ fontSize: 28, fontWeight: 700, color, marginTop: 4, fontFamily: "Courier New" }}>{value}</div>
          </div>
        ))}
      </div>

      {Object.keys(strategies).length === 0 ? (
        <div className="card" style={{ color: "#555555" }}>
          No closed trades yet. Strategies will appear here once they have live paper-trade history.
        </div>
      ) : (
        <>
          {Object.entries(strategies).filter(([, d]) => d.comparison.status === "drift_detected")
            .map(([name, d]) => <StrategyDetail key={name} name={name} data={d} />)}
          {Object.entries(strategies).filter(([, d]) => d.comparison.status === "on_track")
            .map(([name, d]) => <StrategyDetail key={name} name={name} data={d} />)}
          {Object.entries(strategies).filter(([, d]) => !["drift_detected", "on_track"].includes(d.comparison.status))
            .map(([name, d]) => <StrategyDetail key={name} name={name} data={d} />)}
        </>
      )}
    </div>
  );
}
