import React, { useEffect, useState } from "react";
import { api, StrategyPipelineRow } from "../api";

const STATUS_COLORS: Record<string, string> = {
  research:  "#64748b",
  candidate: "#60a5fa",
  shadow:    "#fbbf24",
  validated: "#4ade80",
  paused:    "#f97316",
  killed:    "#f87171",
};

const STATUS_ORDER = ["research", "candidate", "shadow", "validated", "paused", "killed"];

function StatusBadge({ status }: { status: string }) {
  const color = STATUS_COLORS[status] ?? "#64748b";
  return (
    <span style={{
      display: "inline-block", padding: "2px 8px", borderRadius: 4,
      fontSize: 11, fontWeight: 600, background: `${color}22`, color,
      border: `1px solid ${color}44`,
    }}>
      {status.toUpperCase()}
    </span>
  );
}

function StrategyRow({ row, onUpdate }: { row: StrategyPipelineRow; onUpdate: () => void }) {
  const [editing, setEditing] = useState(false);
  const [newStatus, setNewStatus] = useState(row.status);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  const save = () => {
    setSaving(true);
    api.strategyUpdateStatus(row.strategy_name, newStatus, note)
      .then(() => { setEditing(false); onUpdate(); })
      .finally(() => setSaving(false));
  };

  return (
    <>
      <tr>
        <td style={{ fontFamily: "monospace", fontWeight: 600 }}>{row.strategy_name}</td>
        <td><StatusBadge status={row.status} /></td>
        <td style={{ color: "#64748b", fontSize: 12, maxWidth: 260 }}>{row.status_description}</td>
        <td style={{ fontFamily: "monospace", fontSize: 12 }}>{row.live_stats.n_evaluations}</td>
        <td style={{ fontFamily: "monospace", fontSize: 12 }}>{row.live_stats.n_trades}</td>
        <td style={{ color: "#64748b", fontSize: 11 }}>
          {row.promoted_at ? new Date(row.promoted_at).toLocaleDateString() : "—"}
        </td>
        <td style={{ color: "#64748b", fontSize: 11, maxWidth: 200 }}>{row.note ?? "—"}</td>
        <td>
          <button className="btn btn-ghost" style={{ fontSize: 11, padding: "2px 8px" }}
            onClick={() => setEditing(e => !e)}>
            {editing ? "Cancel" : "Edit"}
          </button>
        </td>
      </tr>
      {editing && (
        <tr>
          <td colSpan={8} style={{ background: "#0f172a", padding: "12px 16px" }}>
            <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
              <div>
                <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>New status</div>
                <select
                  value={newStatus}
                  onChange={e => setNewStatus(e.target.value as StrategyPipelineRow["status"])}
                  style={{ background: "#1e293b", color: "#e2e8f0", border: "1px solid #334155", borderRadius: 4, padding: "4px 8px" }}
                >
                  {STATUS_ORDER.map(s => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
              <div style={{ flex: 1, minWidth: 200 }}>
                <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>Note (optional)</div>
                <input
                  value={note}
                  onChange={e => setNote(e.target.value)}
                  placeholder="Reason for change…"
                  style={{ width: "100%", background: "#1e293b", color: "#e2e8f0", border: "1px solid #334155", borderRadius: 4, padding: "4px 8px" }}
                />
              </div>
              <button className="btn btn-secondary" onClick={save} disabled={saving}>
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function StrategyPipeline() {
  const [rows, setRows] = useState<StrategyPipelineRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    api.strategies()
      .then(setRows)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading) return <div className="loading">Loading…</div>;
  if (error) return <div className="card" style={{ color: "#f87171" }}>Error: {error}</div>;

  const byStatus = STATUS_ORDER.reduce<Record<string, number>>((acc, s) => {
    acc[s] = rows.filter(r => r.status === s).length;
    return acc;
  }, {});

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="page-title">Strategy Pipeline</div>
          <div className="page-subtitle">research → candidate → shadow → validated → paused / killed</div>
        </div>
        <button className="btn btn-ghost" onClick={load}>↻ Refresh</button>
      </div>

      {/* Status counts */}
      <div style={{ display: "flex", gap: 12, marginBottom: 24, flexWrap: "wrap" }}>
        {STATUS_ORDER.map(s => byStatus[s] > 0 && (
          <div key={s} className="card" style={{ padding: "8px 16px", minWidth: 80 }}>
            <div style={{ fontSize: 11, color: STATUS_COLORS[s], fontWeight: 600 }}>{s.toUpperCase()}</div>
            <div style={{ fontSize: 22, fontWeight: 700, marginTop: 2 }}>{byStatus[s]}</div>
          </div>
        ))}
      </div>

      <div className="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Strategy</th>
              <th>Status</th>
              <th>Description</th>
              <th>Evaluations</th>
              <th>Trades</th>
              <th>Last Promoted</th>
              <th>Note</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <StrategyRow key={r.strategy_name} row={r} onUpdate={load} />
            ))}
          </tbody>
        </table>
      </div>

      {rows.length === 0 && (
        <div className="card" style={{ color: "#64748b" }}>No strategies in pipeline yet.</div>
      )}
    </div>
  );
}
