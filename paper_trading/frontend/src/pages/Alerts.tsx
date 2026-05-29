import React, { useEffect, useState } from "react";
import { api, AlertRecord, AlertSummary } from "../api";

const CATEGORY_COLORS: Record<string, string> = {
  signal_fired:     "#00cc44",
  trade_closed:     "#3399ff",
  data_failed:      "#ff3333",
  scheduler_missed: "#ffcc00",
  risk_blocked:     "#ff6600",
};

function CategoryBadge({ cat }: { cat: string }) {
  const color = CATEGORY_COLORS[cat] ?? "#666666";
  const label = cat.replace(/_/g, " ");
  return (
    <span style={{
      display: "inline-block", padding: "1px 7px",
      fontSize: 10, fontWeight: 700, background: `${color}18`, color,
      border: `1px solid ${color}44`, whiteSpace: "nowrap",
    }}>
      {label}
    </span>
  );
}

export default function Alerts() {
  const [alerts, setAlerts] = useState<AlertRecord[]>([]);
  const [summary, setSummary] = useState<AlertSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [filterCat, setFilterCat] = useState<string>("all");

  const load = () => {
    setLoading(true);
    Promise.all([api.alerts(200), api.alertSummary()])
      .then(([a, s]) => { setAlerts(a); setSummary(s); })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const markAll = () => api.alertReadAll().then(load);
  const markOne = (id: number) => api.alertRead(id).then(load);

  const cats = ["all", ...Object.keys(CATEGORY_COLORS)];
  const filtered = filterCat === "all" ? alerts : alerts.filter(a => a.category === filterCat);

  if (loading) return <div className="loading">Loading…</div>;

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="page-title">Alerts</div>
          <div className="page-subtitle">Signal events, trade closes, data failures, risk blocks</div>
        </div>
        <div className="btn-row" style={{ marginBottom: 0 }}>
          <button className="btn btn-ghost" onClick={load}>↻ Refresh</button>
          {summary && summary.total_unread > 0 && (
            <button className="btn btn-secondary" onClick={markAll}>
              Mark all read ({summary.total_unread})
            </button>
          )}
        </div>
      </div>

      {summary && (
        <div style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap" }}>
          {Object.entries(summary.by_category).map(([cat, n]) => n > 0 && (
            <div key={cat} className="card" style={{ padding: "8px 14px", cursor: "pointer" }}
              onClick={() => setFilterCat(cat === filterCat ? "all" : cat)}>
              <CategoryBadge cat={cat} />
              <div style={{ fontSize: 20, fontWeight: 700, marginTop: 4 }}>{n}</div>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: "flex", gap: 6, marginBottom: 16, flexWrap: "wrap" }}>
        {cats.map(c => (
          <button key={c} onClick={() => setFilterCat(c)}
            className={`btn ${filterCat === c ? "btn-primary" : "btn-ghost"}`}
            style={{ fontSize: 10, padding: "2px 8px", height: 22 }}>
            {c.replace(/_/g, " ")}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="card" style={{ color: "#555555" }}>No alerts.</div>
      ) : (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th></th><th>Time</th><th>Category</th><th>Title</th>
                <th>Strategy</th><th>Action</th><th></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(a => (
                <React.Fragment key={a.id}>
                  <tr style={{ opacity: a.is_read ? 0.5 : 1, cursor: "pointer" }}
                    onClick={() => setExpandedId(expandedId === a.id ? null : a.id)}>
                    <td style={{ width: 6 }}>
                      {!a.is_read && (
                        <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#ff6600", margin: "0 auto" }} />
                      )}
                    </td>
                    <td style={{ fontSize: 11, fontFamily: "monospace", color: "#555555", whiteSpace: "nowrap" }}>
                      {new Date(a.timestamp).toLocaleString()}
                    </td>
                    <td><CategoryBadge cat={a.category} /></td>
                    <td style={{ fontSize: 13 }}>{a.title}</td>
                    <td style={{ color: "#666666", fontSize: 12 }}>{a.strategy ?? "—"}</td>
                    <td style={{ color: "#555555", fontSize: 11 }}>{a.action_taken ?? "—"}</td>
                    <td>
                      {!a.is_read && (
                        <button className="btn btn-ghost" style={{ fontSize: 10, padding: "1px 6px" }}
                          onClick={e => { e.stopPropagation(); markOne(a.id); }}>
                          ✓
                        </button>
                      )}
                    </td>
                  </tr>
                  {expandedId === a.id && (
                    <tr>
                      <td colSpan={7} style={{ background: "#0a0a0a", padding: "12px 16px" }}>
                        <pre style={{ fontSize: 12, color: "#888888", whiteSpace: "pre-wrap", margin: 0 }}>
                          {a.body}
                        </pre>
                        {a.market && (
                          <div style={{ fontSize: 11, color: "#555555", marginTop: 8 }}>
                            Market: {a.market}
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
