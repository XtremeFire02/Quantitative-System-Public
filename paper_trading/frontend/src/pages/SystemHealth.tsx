import React, { useEffect, useState } from "react";
import { api, SystemHealth as HealthData, SystemLog } from "../api";

function StatusRow({ label, value, ok }: { label: string; value: string; ok: boolean }) {
  return (
    <tr>
      <td style={{ color: "#64748b" }}>{label}</td>
      <td style={{ color: ok ? "#4ade80" : "#f87171" }}>{value}</td>
      <td><span className={`badge ${ok ? "badge-green" : "badge-red"}`}>{ok ? "OK" : "WARN"}</span></td>
    </tr>
  );
}

export default function SystemHealth() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [logs, setLogs] = useState<SystemLog[]>([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    Promise.all([api.systemHealth(), api.systemLogs(60)])
      .then(([h, l]) => { setHealth(h); setLogs(l); })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading) return <div className="loading">Loading…</div>;

  const runSignal = () => api.runDailySignal().then(load);
  const checkExit = () => api.checkExits().then(load);

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="page-title">System Health</div>
          <div className="page-subtitle">Data freshness, scheduler status, error logs</div>
        </div>
        <div className="btn-row" style={{ marginBottom: 0 }}>
          <button className="btn btn-ghost" onClick={load}>↻ Refresh</button>
          <button className="btn btn-secondary" onClick={runSignal}>Run Signal Job</button>
          <button className="btn btn-secondary" onClick={checkExit}>Run Exit Check</button>
        </div>
      </div>

      {health && (
        <>
          <div className="cards-grid" style={{ marginBottom: 20 }}>
            <div className="card" style={{ gridColumn: "1 / -1" }}>
              <div className="card-label">Overall Status</div>
              <div className="card-value" style={{ fontSize: 16, marginTop: 6 }}>
                <span className={`badge ${health.status === "healthy" ? "badge-green" : "badge-red"}`}>
                  {health.status === "healthy" ? "● Healthy" : "⚠ Degraded"}
                </span>
              </div>
              <div className="card-sub">Checked at: {new Date(health.checked_at).toLocaleString()}</div>
            </div>
          </div>

          <div className="table-wrapper" style={{ marginBottom: 24 }}>
            <table>
              <thead>
                <tr><th>Component</th><th>Last Update</th><th>Status</th></tr>
              </thead>
              <tbody>
                <StatusRow
                  label="Binance Market Data"
                  value={health.last_binance_update ? new Date(health.last_binance_update).toLocaleString() : "Never"}
                  ok={!health.market_data_stale}
                />
                <StatusRow
                  label="Signal Calculation"
                  value={health.last_signal_calculation ? new Date(health.last_signal_calculation).toLocaleString() : "Never"}
                  ok={!health.signal_data_stale}
                />
                <StatusRow
                  label="Database"
                  value={health.database_status}
                  ok={health.database_status === "ok"}
                />
                <StatusRow
                  label="Open Positions"
                  value={`${health.open_position_count} position(s)`}
                  ok={health.open_position_count <= 1}
                />
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* System logs */}
      <div className="section-title">System Logs</div>
      {logs.length === 0 ? (
        <div className="card" style={{ color: "#64748b", padding: 20 }}>No logs yet.</div>
      ) : (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Level</th>
                <th>Component</th>
                <th>Message</th>
              </tr>
            </thead>
            <tbody>
              {logs.map(log => (
                <tr key={log.id}>
                  <td style={{ fontSize: 11, fontFamily: "monospace", color: "#64748b" }}>
                    {new Date(log.timestamp).toLocaleString()}
                  </td>
                  <td>
                    <span className={`badge ${
                      log.level === "ERROR" ? "badge-red" :
                      log.level === "WARNING" ? "badge-yellow" : "badge-gray"
                    }`}>
                      {log.level}
                    </span>
                  </td>
                  <td style={{ color: "#64748b", fontSize: 12 }}>{log.component}</td>
                  <td style={{ fontSize: 12 }}>{log.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
