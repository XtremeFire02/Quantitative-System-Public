import React, { useEffect, useState } from "react";
import { api, ExperimentRun } from "../api";

const VERDICT_COLORS: Record<string, string> = {
  passed:  "#4ade80",
  failed:  "#f87171",
  killed:  "#f97316",
  pending: "#64748b",
};

function VerdictBadge({ verdict }: { verdict: string }) {
  const color = VERDICT_COLORS[verdict] ?? "#64748b";
  return (
    <span style={{
      display: "inline-block", padding: "1px 7px", borderRadius: 4,
      fontSize: 11, fontWeight: 700, background: `${color}22`, color,
      border: `1px solid ${color}44`,
    }}>
      {verdict.toUpperCase()}
    </span>
  );
}

function MetricPill({ k, v }: { k: string; v: unknown }) {
  if (v === null || v === undefined) return null;
  return (
    <span style={{
      display: "inline-block", marginRight: 6, marginBottom: 4,
      padding: "1px 7px", borderRadius: 3, background: "#1e293b",
      border: "1px solid #334155", fontSize: 11, fontFamily: "monospace",
      color: "#94a3b8",
    }}>
      {k}: <strong style={{ color: "#e2e8f0" }}>{String(v)}</strong>
    </span>
  );
}

export default function Experiments() {
  const [runs, setRuns] = useState<ExperimentRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    api.experiments()
      .then(setRuns)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading) return <div className="loading">Loading…</div>;
  if (error) return <div className="card" style={{ color: "#f87171" }}>Error: {error}</div>;

  const verdictCounts = runs.reduce<Record<string, number>>((acc, r) => {
    acc[r.verdict] = (acc[r.verdict] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="page-title">Experiments</div>
          <div className="page-subtitle">Per-run research log with parameters, metrics, and decisions</div>
        </div>
        <button className="btn btn-ghost" onClick={load}>↻ Refresh</button>
      </div>

      {/* Verdict summary */}
      <div style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap" }}>
        {Object.entries(verdictCounts).map(([v, n]) => (
          <div key={v} className="card" style={{ padding: "8px 14px" }}>
            <VerdictBadge verdict={v} />
            <div style={{ fontSize: 20, fontWeight: 700, marginTop: 4 }}>{n}</div>
          </div>
        ))}
      </div>

      {runs.length === 0 ? (
        <div className="card" style={{ color: "#64748b" }}>
          No experiments logged yet. POST to /api/experiments to record a run.
        </div>
      ) : (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Run ID</th>
                <th>Strategy</th>
                <th>Script</th>
                <th>Data Range</th>
                <th>Commit</th>
                <th>Verdict</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {runs.map(r => (
                <React.Fragment key={r.run_id}>
                  <tr
                    style={{ cursor: "pointer" }}
                    onClick={() => setExpandedId(expandedId === r.run_id ? null : r.run_id)}
                  >
                    <td style={{ fontFamily: "monospace", fontSize: 12 }}>{r.run_id}</td>
                    <td style={{ fontSize: 12 }}>{r.strategy_name ?? "—"}</td>
                    <td style={{ color: "#64748b", fontSize: 11 }}>{r.script_name ?? "—"}</td>
                    <td style={{ fontFamily: "monospace", fontSize: 11, color: "#64748b" }}>
                      {r.data_range_start && r.data_range_end
                        ? `${r.data_range_start} → ${r.data_range_end}`
                        : "—"}
                    </td>
                    <td style={{ fontFamily: "monospace", fontSize: 11, color: "#64748b" }}>
                      {r.commit_hash ? r.commit_hash.slice(0, 8) : "—"}
                    </td>
                    <td><VerdictBadge verdict={r.verdict} /></td>
                    <td style={{ fontSize: 11, color: "#64748b" }}>
                      {r.created_at ? new Date(r.created_at).toLocaleDateString() : "—"}
                    </td>
                  </tr>
                  {expandedId === r.run_id && (
                    <tr>
                      <td colSpan={7} style={{ background: "#0f172a", padding: "14px 16px" }}>
                        {r.metrics && (
                          <div style={{ marginBottom: 10 }}>
                            <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6 }}>METRICS</div>
                            <div>
                              {Object.entries(r.metrics).map(([k, v]) => (
                                <MetricPill key={k} k={k} v={v} />
                              ))}
                            </div>
                          </div>
                        )}
                        {r.parameters && (
                          <div style={{ marginBottom: 10 }}>
                            <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6 }}>PARAMETERS</div>
                            <div>
                              {Object.entries(r.parameters).map(([k, v]) => (
                                <MetricPill key={k} k={k} v={v} />
                              ))}
                            </div>
                          </div>
                        )}
                        {r.notes && (
                          <div>
                            <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>NOTES</div>
                            <div style={{ fontSize: 12, color: "#94a3b8" }}>{r.notes}</div>
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
