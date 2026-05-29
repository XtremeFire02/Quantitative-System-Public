import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, TradeRecord } from "../api";
import { SkeletonTable } from "../components/Skeleton";
import { toast } from "../components/Toast";

const fmt = (v: number | null, dec = 2) =>
  v == null ? "—" : v.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });

function PnlCell({ bp }: { bp: number | null }) {
  if (bp == null) return <span className="neutral">—</span>;
  const cls = bp > 0 ? "positive" : bp < 0 ? "negative" : "neutral";
  return <span className={cls}>{bp > 0 ? "+" : ""}{fmt(bp, 1)} bp</span>;
}

function CloseButton({ trade, onClosed }: { trade: TradeRecord; onClosed: () => void }) {
  const [closing, setClosing] = useState(false);

  const handleClose = async () => {
    if (!window.confirm(`Close trade #${trade.id} (${trade.market ?? "BTCUSDT"}) at market now?`)) return;
    setClosing(true);
    try {
      const res = await api.closeTrade(trade.id);
      toast.success(`Trade #${trade.id} closed — ${res.net_pnl_bp != null ? `${res.net_pnl_bp > 0 ? "+" : ""}${res.net_pnl_bp.toFixed(1)} bp` : "PnL pending"}`);
      onClosed();
    } catch (e: any) {
      toast.error(`Failed to close trade #${trade.id}: ${e.message}`);
    } finally {
      setClosing(false);
    }
  };

  return (
    <button
      className="btn btn-ghost"
      style={{ fontSize: 9, padding: "0 6px", height: 20, color: "#ff3333", borderColor: "#3a1a1a" }}
      onClick={handleClose}
      disabled={closing}
    >
      {closing ? "…" : "✕ Close"}
    </button>
  );
}

export default function Trades() {
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [filter, setFilter] = useState<"all" | "open" | "closed">("all");
  const [loading, setLoading] = useState(true);

  const reload = () => {
    setLoading(true);
    api.trades(filter === "all" ? undefined : filter)
      .then(setTrades)
      .finally(() => setLoading(false));
  };

  useEffect(() => { reload(); }, [filter]);

  const closed = trades.filter(t => t.status === "closed");
  const wins = closed.filter(t => (t.net_pnl ?? 0) > 0).length;
  const totalPnlBp = closed.reduce((s, t) => s + (t.net_pnl_bp ?? 0), 0);

  return (
    <div>
      <div className="page-header">
        <div className="page-title">Trade Journal</div>
        <div className="page-subtitle">All paper trades with full PnL attribution</div>
      </div>

      {closed.length > 0 && (
        <div className="cards-grid" style={{ marginBottom: 20 }}>
          <div className="card">
            <div className="card-label">Total Trades</div>
            <div className="card-value">{closed.length}</div>
          </div>
          <div className="card">
            <div className="card-label">Net PnL</div>
            <div className="card-value" style={{ fontSize: 18 }}>
              <PnlCell bp={totalPnlBp} />
            </div>
          </div>
          <div className="card">
            <div className="card-label">Win Rate</div>
            <div className="card-value">{closed.length > 0 ? `${(wins / closed.length * 100).toFixed(0)}%` : "—"}</div>
          </div>
        </div>
      )}

      <div className="btn-row">
        {(["all", "open", "closed"] as const).map(f => (
          <button key={f} className={`btn ${filter === f ? "btn-primary" : "btn-secondary"}`}
            onClick={() => setFilter(f)}>
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      {loading ? (
        <SkeletonTable rows={6} cols={9} />
      ) : trades.length === 0 ? (
        <div className="card" style={{ color: "#555555", textAlign: "center", padding: 40 }}>
          No trades yet.
        </div>
      ) : (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Status</th>
                <th>Entry Date</th>
                <th>Exit Date</th>
                <th>Entry $</th>
                <th>Exit $</th>
                <th>Entry DVOL</th>
                <th>Entry N3z</th>
                <th>Price PnL</th>
                <th>Funding</th>
                <th>Fees</th>
                <th>Net PnL</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {trades.map(t => (
                <tr key={t.id}>
                  <td><Link to={`/trades/${t.id}`} className="trade-link">#{t.id}</Link></td>
                  <td>
                    <span className={`badge ${t.status === "open" ? "badge-blue" : "badge-gray"}`}>
                      {t.status}
                    </span>
                  </td>
                  <td style={{ fontSize: 12 }}>{new Date(t.entry_timestamp).toLocaleDateString()}</td>
                  <td style={{ fontSize: 12, color: "#555555" }}>
                    {t.exit_timestamp ? new Date(t.exit_timestamp).toLocaleDateString() : "—"}
                  </td>
                  <td>${fmt(t.entry_price, 0)}</td>
                  <td style={{ color: "#555555" }}>{t.exit_price ? `$${fmt(t.exit_price, 0)}` : "—"}</td>
                  <td>{fmt(t.entry_dvol, 1)}</td>
                  <td style={{ fontWeight: 600 }}>{fmt(t.entry_n3_z, 3)}</td>
                  <td><PnlCell bp={t.gross_price_return_bp} /></td>
                  <td><PnlCell bp={t.funding_pnl_bp} /></td>
                  <td style={{ color: "#ff3333" }}>{t.fees_bp != null ? `-${fmt(t.fees_bp, 1)} bp` : "—"}</td>
                  <td style={{ fontWeight: 700 }}><PnlCell bp={t.net_pnl_bp} /></td>
                  <td>
                    {t.status === "open" && (
                      <CloseButton trade={t} onClosed={reload} />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
