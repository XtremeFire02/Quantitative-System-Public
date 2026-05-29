import React, { useEffect, useState } from "react";
import { api, DataQualityReport, DataQualityCheck } from "../api";

function CheckRow({ check }: { check: DataQualityCheck }) {
  const badgeClass = check.status === "ok" ? "badge-green" : check.status === "warn" ? "badge-yellow" : "badge-red";
  return (
    <tr>
      <td style={{ fontFamily: "monospace", fontSize: 11, color: "#555555" }}>{check.name}</td>
      <td style={{ fontSize: 13 }}>{check.detail}</td>
      <td style={{ fontFamily: "monospace", fontSize: 12 }}>{check.value ?? "—"}</td>
      <td style={{ fontFamily: "monospace", fontSize: 12, color: "#555555" }}>{check.expected}</td>
      <td><span className={`badge ${badgeClass}`}>{check.status.toUpperCase()}</span></td>
    </tr>
  );
}

export default function DataQuality() {
  const [report, setReport] = useState<DataQualityReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    api.dataQuality().then(setReport).catch(e => setError(e.message)).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading) return <div className="loading">Loading…</div>;
  if (error) return <div className="card" style={{ color: "#ff3333" }}>Error: {error}</div>;
  if (!report) return null;

  const overallBadge = report.status === "ok" ? "badge-green" : report.status === "warn" ? "badge-yellow" : "badge-red";

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="page-title">Data Quality</div>
          <div className="page-subtitle">Feed completeness, freshness, and anomaly checks</div>
        </div>
        <button className="btn btn-ghost" onClick={load}>↻ Refresh</button>
      </div>

      <div className="cards-grid" style={{ marginBottom: 20 }}>
        <div className="card">
          <div className="card-label">Overall</div>
          <div className="card-value" style={{ marginTop: 6 }}>
            <span className={`badge ${overallBadge}`}>{report.status.toUpperCase()}</span>
          </div>
          <div className="card-sub">{new Date(report.checked_at).toLocaleString()}</div>
        </div>
        <div className="card">
          <div className="card-label">Total Checks</div>
          <div className="card-value">{report.n_checks}</div>
        </div>
        <div className="card">
          <div className="card-label">Warnings</div>
          <div className="card-value" style={{ color: report.n_warn > 0 ? "#ffcc00" : "#00cc44" }}>
            {report.n_warn}
          </div>
        </div>
        <div className="card">
          <div className="card-label">Errors</div>
          <div className="card-value" style={{ color: report.n_error > 0 ? "#ff3333" : "#00cc44" }}>
            {report.n_error}
          </div>
        </div>
      </div>

      <div className="table-wrapper">
        <table>
          <thead>
            <tr><th>Check</th><th>Detail</th><th>Value</th><th>Expected</th><th>Status</th></tr>
          </thead>
          <tbody>
            {report.checks.map(c => <CheckRow key={c.name} check={c} />)}
          </tbody>
        </table>
      </div>
    </div>
  );
}
