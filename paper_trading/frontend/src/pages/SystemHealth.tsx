import React, { useEffect, useState } from "react";
import { api, SystemHealth as HealthData, SystemLog, ConnectivityStatus } from "../api";

function StatusRow({ label, value, ok }: { label: string; value: string; ok: boolean }) {
  return (
    <tr>
      <td style={{ color: "#666666" }}>{label}</td>
      <td style={{ color: ok ? "#00cc44" : "#ff3333" }}>{value}</td>
      <td><span className={`badge ${ok ? "badge-green" : "badge-red"}`}>{ok ? "OK" : "WARN"}</span></td>
    </tr>
  );
}

const LEVEL_COLOR: Record<string, string> = { ok: "#00cc44", warn: "#ffcc00", critical: "#ff3333" };

export default function SystemHealth() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [logs, setLogs] = useState<SystemLog[]>([]);
  const [logsError, setLogsError] = useState<string | null>(null);
  const [connectivity, setConnectivity] = useState<ConnectivityStatus | null>(null);
  const [connError, setConnError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    Promise.allSettled([api.systemHealth(), api.systemLogs(60), api.connectivity()])
      .then(([h, l, c]) => {
        if (h.status === "fulfilled") { setHealth(h.value); setHealthError(null); }
        else setHealthError((h.reason as Error).message);
        if (l.status === "fulfilled") { setLogs(l.value); setLogsError(null); }
        else setLogsError((l.reason as Error).message);
        if (c.status === "fulfilled") { setConnectivity(c.value); setConnError(null); }
        else setConnError((c.reason as Error).message);
      })
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

      {healthError && (
        <div className="card" style={{ color: "#ff3333", marginBottom: 16 }}>
          Health check failed: {healthError}
        </div>
      )}

      {health && (
        <>
          <div className="cards-grid" style={{ marginBottom: 20 }}>
            <div className="card">
              <div className="card-label">Overall Status</div>
              <div className="card-value" style={{ fontSize: 16, marginTop: 6 }}>
                <span className={`badge ${health.status === "healthy" ? "badge-green" : "badge-red"}`}>
                  {health.status === "healthy" ? "● Healthy" : "⚠ Degraded"}
                </span>
              </div>
              <div className="card-sub">Checked at: {new Date(health.checked_at).toLocaleString()}</div>
            </div>
            <div className="card">
              <div className="card-label">Trades</div>
              <div className="card-value" style={{ fontSize: 16 }}>{health.total_trade_count ?? "—"}</div>
              <div className="card-sub">{health.open_position_count} open · {health.closed_trade_count ?? "—"} closed</div>
            </div>
            <div className="card">
              <div className="card-label">Errors (24h)</div>
              <div className="card-value" style={{ fontSize: 16, color: (health.recent_errors_24h ?? 0) > 0 ? "#ff3333" : "#00cc44" }}>
                {health.recent_errors_24h ?? "—"}
              </div>
              <div className="card-sub">System log errors</div>
            </div>
          </div>

          <div className="table-wrapper" style={{ marginBottom: 24 }}>
            <table>
              <thead>
                <tr><th>Component</th><th>Last Update / Value</th><th>Status</th></tr>
              </thead>
              <tbody>
                <StatusRow label="Binance Market Data"
                  value={health.last_binance_update ? new Date(health.last_binance_update).toLocaleString() : "Never"}
                  ok={!health.market_data_stale} />
                <StatusRow label="Signal Calculation"
                  value={health.last_signal_calculation ? new Date(health.last_signal_calculation).toLocaleString() : "Never"}
                  ok={!health.signal_data_stale} />
                <StatusRow label="Daily Signal Job"
                  value={health.last_daily_job_run ? new Date(health.last_daily_job_run).toLocaleString() : "No record"}
                  ok={health.last_daily_job_run != null} />
                <StatusRow label="Exit Check Job"
                  value={health.last_exit_job_run ? new Date(health.last_exit_job_run).toLocaleString() : "No record"}
                  ok={health.last_exit_job_run != null} />
                <StatusRow label="Database" value={health.database_status} ok={health.database_status === "ok"} />
                <StatusRow label="Open Positions" value={`${health.open_position_count} position(s)`} ok={true} />
                {health.next_scheduled_exit && (
                  <StatusRow label="Next Scheduled Exit"
                    value={`${new Date(health.next_scheduled_exit).toLocaleString()} (${health.hours_to_exit?.toFixed(1) ?? "?"} h)`}
                    ok={(health.hours_to_exit ?? 0) > 0} />
                )}
                <StatusRow label="Next Daily Signal Job" value={new Date(health.next_daily_job_utc).toLocaleString()} ok={true} />
              </tbody>
            </table>
          </div>
        </>
      )}

      {connError && (
        <div className="card" style={{ color: "#ff3333", marginBottom: 16 }}>
          Connectivity probe failed: {connError}
        </div>
      )}

      {connectivity && (
        <>
          <div className="section-title" style={{ marginBottom: 12 }}>
            Exchange Connectivity
            <span style={{ marginLeft: 10, fontSize: 11, fontWeight: 400, color: LEVEL_COLOR[connectivity.overall] ?? "#666666" }}>
              ● {connectivity.overall.toUpperCase()} · max {connectivity.max_latency_ms != null ? connectivity.max_latency_ms.toFixed(0) : "—"} ms
            </span>
          </div>
          <div className="table-wrapper" style={{ marginBottom: 24 }}>
            <table>
              <thead>
                <tr><th>Feed</th><th>Endpoint</th><th>Latency</th><th>Status</th><th>Detail</th></tr>
              </thead>
              <tbody>
                {connectivity.probes.map(p => {
                  const c = LEVEL_COLOR[p.level] ?? "#666666";
                  return (
                    <tr key={p.name}>
                      <td style={{ fontFamily: "monospace", fontSize: 12 }}>{p.name}</td>
                      <td style={{ fontSize: 11, color: "#555555" }}>{p.feed}</td>
                      <td style={{ fontFamily: "monospace", fontSize: 12 }}>
                        {p.latency_ms != null ? `${p.latency_ms.toFixed(0)} ms` : "—"}
                      </td>
                      <td>
                        <span style={{
                          display: "inline-block", padding: "2px 8px",
                          fontSize: 11, fontWeight: 700,
                          background: `${c}22`, color: c, border: `1px solid ${c}44`,
                        }}>
                          {p.level.toUpperCase()}
                        </span>
                      </td>
                      <td style={{ fontSize: 11, color: "#555555" }}>
                        {p.error ?? (p.status_code ? `HTTP ${p.status_code}` : "—")}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {logsError && (
        <div className="card" style={{ color: "#ff3333", marginBottom: 16 }}>
          Logs failed to load: {logsError}
        </div>
      )}

      <div className="section-title">System Logs</div>
      {logs.length === 0 ? (
        <div className="card" style={{ color: "#555555", padding: 20 }}>No logs yet.</div>
      ) : (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr><th>Time</th><th>Level</th><th>Component</th><th>Message</th></tr>
            </thead>
            <tbody>
              {logs.map(log => (
                <tr key={log.id}>
                  <td style={{ fontSize: 11, fontFamily: "monospace", color: "#555555" }}>
                    {new Date(log.timestamp).toLocaleString()}
                  </td>
                  <td>
                    <span className={`badge ${log.level === "ERROR" ? "badge-red" : log.level === "WARNING" ? "badge-yellow" : "badge-gray"}`}>
                      {log.level}
                    </span>
                  </td>
                  <td style={{ color: "#666666", fontSize: 12 }}>{log.component}</td>
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
