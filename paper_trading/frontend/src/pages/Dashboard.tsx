import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, DashboardData } from "../api";
import { toast } from "../components/Toast";
import { SkeletonCards } from "../components/Skeleton";

const fmt = (v: number | null, dec = 2) =>
  v == null ? "—" : v.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });

const fmtPct = (v: number | null, dec = 3) =>
  v == null ? "—" : `${(v * 100).toFixed(dec)}%`;

function PnlValue({ bp }: { bp: number }) {
  const cls = bp > 0 ? "positive" : bp < 0 ? "negative" : "neutral";
  return <span className={cls}>{bp > 0 ? "+" : ""}{fmt(bp, 0)} bp</span>;
}

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [triggering, setTriggering] = useState(false);

  const load = () => {
    api.dashboard().then(setData).catch(e => setError(e.message)).finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, []);

  const triggerSignal = async () => {
    setTriggering(true);
    try {
      await api.runDailySignal();
      toast.success("Daily signal job triggered");
      await load();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      toast.error(`Signal job failed: ${msg}`);
    } finally {
      setTriggering(false);
    }
  };

  if (loading) return <><div className="page-header"><div className="page-title">Dashboard</div></div><SkeletonCards n={6} /></>;
  if (error) return <div className="error-msg">Error: {error}</div>;
  if (!data) return null;

  const dvolColor = data.dvol_filter_pass ? "#00cc44" : "#ff3333";

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="page-title">Dashboard</div>
          <div className="page-subtitle">Paper trading · Live signals · {data.open_position ? `${(data.open_trades ?? []).length} open position(s)` : "Flat"}</div>
        </div>
        <div className="btn-row" style={{ marginBottom: 0 }}>
          <button className="btn btn-ghost" onClick={load}>↻ Refresh</button>
          <button className="btn btn-primary" onClick={triggerSignal} disabled={triggering}>
            {triggering ? "Running…" : "▶ Run Signal Now"}
          </button>
        </div>
      </div>

      {/* Market data */}
      <div className="section-title">Market</div>
      <div className="cards-grid">
        <div className="card">
          <div className="card-label">BTC Price</div>
          <div className="card-value">${fmt(data.price, 0)}</div>
          <div className="card-sub">Last update: {data.last_market_update ? new Date(data.last_market_update).toLocaleTimeString() : "—"}</div>
        </div>
        <div className="card">
          <div className="card-label">Funding Rate</div>
          <div className="card-value" style={{ fontSize: 16 }}>{fmtPct(data.funding_rate, 4)}</div>
          <div className="card-sub">Current 8h rate</div>
        </div>
      </div>

      {/* Signal status */}
      <div className="section">
        <div className="section-title">Signal</div>
        <div className="cards-grid">
          <div className="card">
            <div className="card-label">DVOL</div>
            <div className="card-value" style={{ color: dvolColor }}>{fmt(data.dvol, 1)}</div>
            <div className="card-sub">Deribit 30d implied vol</div>
          </div>
          <div className="card">
            <div className="card-label">N3 z-score</div>
            <div className="card-value">{fmt(data.n3_z, 3)}</div>
            <div className="card-sub">vs signal threshold θ</div>
          </div>
          <div className="card">
            <div className="card-label">DVOL Filter</div>
            <div className="card-value" style={{ fontSize: 15 }}>
              {data.dvol_filter_pass == null ? "—" : (
                <span className={`badge ${data.dvol_filter_pass ? "badge-green" : "badge-red"}`}>
                  {data.dvol_filter_pass ? "PASS" : "FAIL"}
                </span>
              )}
            </div>
            <div className="card-sub">Regime gate</div>
          </div>
          <div className="card">
            <div className="card-label">Signal</div>
            <div className="card-value" style={{ fontSize: 15 }}>
              {data.entry_signal == null ? "—" : (
                <span className={`badge ${data.entry_signal ? "badge-green" : "badge-gray"}`}>
                  {data.entry_signal ? "● LONG" : "○ FLAT"}
                </span>
              )}
            </div>
            <div className="card-sub">{data.last_signal_time ? new Date(data.last_signal_time).toLocaleString() : "No signal yet"}</div>
          </div>
        </div>
        {data.signal_reason && (
          <div style={{ marginTop: 10, padding: "10px 14px", background: "#0d0d0d", border: "1px solid #2a2a2a", fontSize: 12, color: "#888888", fontFamily: "Courier New" }}>
            {data.signal_reason}
          </div>
        )}
      </div>

      {/* Positions */}
      <div className="section">
        <div className="section-title">Open Positions</div>
        {data.open_position && (data.open_trades ?? []).length > 0 ? (
          <>
            {(data.open_trades ?? [data.open_trade]).filter(Boolean).map(t => (
              <div key={t!.id} className="card" style={{ marginBottom: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
                  <div>
                    <span className={`badge ${t!.side === "long" ? "badge-blue" : "badge-red"}`}>
                      {t!.side.toUpperCase()}
                    </span>
                    <span style={{ marginLeft: 8, fontSize: 12, color: "#666" }}>
                      {t!.strategy_name} · {t!.market}
                    </span>
                  </div>
                  <Link to={`/trades/${t!.id}`} style={{ fontSize: 11, color: "#555555", textDecoration: "none" }}>
                    Trade #{t!.id} →
                  </Link>
                </div>
                <div className="cards-grid" style={{ margin: 0 }}>
                  <div>
                    <div className="card-label">Entry Price</div>
                    <div className="card-value" style={{ fontSize: 16 }}>${fmt(t!.entry_price, 0)}</div>
                    <div className="card-sub">{new Date(t!.entry_timestamp).toLocaleString()}</div>
                  </div>
                  <div>
                    <div className="card-label">Unrealised PnL</div>
                    <div className="card-value" style={{ fontSize: 16 }}>
                      {t!.unrealised_pnl_bp != null ? <PnlValue bp={t!.unrealised_pnl_bp} /> : "—"}
                    </div>
                    <div className="card-sub">Before costs</div>
                  </div>
                  <div>
                    <div className="card-label">Exit In</div>
                    <div className="card-value" style={{ fontSize: 16 }}>
                      {t!.time_to_exit_hours != null ? `${t!.time_to_exit_hours}h` : "—"}
                    </div>
                    <div className="card-sub">{t!.planned_exit_timestamp ? new Date(t!.planned_exit_timestamp).toLocaleString() : ""}</div>
                  </div>
                </div>
              </div>
            ))}
            <div className="card" style={{ background: "#0a0a0a" }}>
              <div style={{ display: "flex", gap: 24, fontSize: 12, color: "#666" }}>
                <span>Total unrealised: <PnlValue bp={data.unrealised_pnl_bp} /></span>
              </div>
            </div>
          </>
        ) : (
          <div className="card" style={{ color: "#555555" }}>No open positions · Strategy is flat</div>
        )}
      </div>

      {/* Equity */}
      <div className="section">
        <div className="section-title">Equity</div>
        <div className="cards-grid">
          <div className="card">
            <div className="card-label">Equity</div>
            <div className="card-value">${fmt(data.equity, 2)}</div>
            <div className="card-sub">Started at $10,000</div>
          </div>
          <div className="card">
            <div className="card-label">Realised PnL</div>
            <div className="card-value" style={{ fontSize: 18 }}>
              <span className={data.realised_pnl >= 0 ? "positive" : "negative"}>
                {data.realised_pnl >= 0 ? "+" : ""}{(data.realised_pnl * 100).toFixed(2)}%
              </span>
            </div>
            <div className="card-sub">Closed trades only</div>
          </div>
          <div className="card">
            <div className="card-label">Drawdown</div>
            <div className="card-value" style={{ fontSize: 18 }}>
              <span className={data.drawdown < -0.05 ? "negative" : data.drawdown < 0 ? "" : "positive"}>
                {(data.drawdown * 100).toFixed(2)}%
              </span>
            </div>
            <div className="card-sub">From peak equity</div>
          </div>
        </div>
      </div>
    </div>
  );
}
