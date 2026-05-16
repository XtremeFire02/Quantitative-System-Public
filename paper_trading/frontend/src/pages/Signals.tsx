import React, { useEffect, useState } from "react";
import { api, SignalRecord } from "../api";

const fmt = (v: number | null, dec = 3) =>
  v == null ? "—" : v.toFixed(dec);

export default function Signals() {
  const [signals, setSignals] = useState<SignalRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.signalHistory(120).then(setSignals).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="loading">Loading signals…</div>;

  const signalDays = signals.filter(s => s.entry_signal).length;
  const filterDays = signals.filter(s => s.dvol_filter_pass).length;

  return (
    <div>
      <div className="page-header">
        <div className="page-title">Signal Log</div>
        <div className="page-subtitle">
          Every daily N3 evaluation · Frozen rule: N3z &gt; 0.75 AND DVOL ≥ 54
        </div>
      </div>

      <div className="cards-grid" style={{ marginBottom: 24 }}>
        <div className="card">
          <div className="card-label">Total Signals</div>
          <div className="card-value">{signals.length}</div>
          <div className="card-sub">Daily evaluations</div>
        </div>
        <div className="card">
          <div className="card-label">DVOL Filter Pass</div>
          <div className="card-value">{filterDays}</div>
          <div className="card-sub">{signals.length > 0 ? `${(filterDays / signals.length * 100).toFixed(0)}% of days` : "—"}</div>
        </div>
        <div className="card">
          <div className="card-label">Entry Signals</div>
          <div className="card-value positive">{signalDays}</div>
          <div className="card-sub">{signals.length > 0 ? `${(signalDays / signals.length * 100).toFixed(0)}% of days` : "—"}</div>
        </div>
      </div>

      {signals.length === 0 ? (
        <div className="card" style={{ color: "#64748b", textAlign: "center", padding: 40 }}>
          No signals recorded yet. Run the daily signal job to start.
        </div>
      ) : (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>DVOL</th>
                <th>30d Mean</th>
                <th>30d Std</th>
                <th>N3 z-score</th>
                <th>DVOL Filter</th>
                <th>Signal</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {[...signals].reverse().map(s => (
                <tr key={s.id}>
                  <td style={{ fontFamily: "monospace", fontSize: 12 }}>
                    {new Date(s.timestamp).toLocaleDateString()}
                  </td>
                  <td>{fmt(s.dvol, 1)}</td>
                  <td style={{ color: "#64748b" }}>{fmt(s.dvol_mean_30d, 1)}</td>
                  <td style={{ color: "#64748b" }}>{fmt(s.dvol_std_30d, 2)}</td>
                  <td style={{ fontWeight: 600, color: s.n3_z > 0.75 ? "#4ade80" : "#e2e8f0" }}>
                    {fmt(s.n3_z, 3)}
                  </td>
                  <td>
                    <span className={`badge ${s.dvol_filter_pass ? "badge-green" : "badge-red"}`}>
                      {s.dvol_filter_pass ? "PASS" : "FAIL"}
                    </span>
                  </td>
                  <td>
                    <span className={`badge ${s.entry_signal ? "badge-green" : "badge-gray"}`}>
                      {s.entry_signal ? "● LONG" : "○ FLAT"}
                    </span>
                  </td>
                  <td style={{ color: "#64748b", fontSize: 11, maxWidth: 300 }}>{s.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
