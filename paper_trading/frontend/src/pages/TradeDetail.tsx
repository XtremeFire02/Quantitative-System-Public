import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, TradeRecord } from "../api";

const fmt = (v: number | null, dec = 2) =>
  v == null ? "—" : v.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });

function Row({ label, value, cls }: { label: string; value: React.ReactNode; cls?: string }) {
  return (
    <tr>
      <td style={{ color: "#64748b", width: 200 }}>{label}</td>
      <td className={cls}>{value}</td>
    </tr>
  );
}

function PnlBp({ bp }: { bp: number | null }) {
  if (bp == null) return <span className="neutral">—</span>;
  const cls = bp > 0 ? "positive" : bp < 0 ? "negative" : "neutral";
  return <span className={cls} style={{ fontWeight: 700 }}>{bp > 0 ? "+" : ""}{fmt(bp, 1)} bp</span>;
}

export default function TradeDetail() {
  const { id } = useParams<{ id: string }>();
  const [trade, setTrade] = useState<TradeRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    api.trade(Number(id)).then(setTrade).catch(e => setError(e.message)).finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div className="loading">Loading…</div>;
  if (error) return <div className="error-msg">{error}</div>;
  if (!trade) return null;

  const isOpen = trade.status === "open";

  return (
    <div>
      <div className="page-header">
        <Link to="/trades" style={{ color: "#64748b", fontSize: 12, textDecoration: "none" }}>← Trades</Link>
        <div className="page-title" style={{ marginTop: 6 }}>Trade #{trade.id}</div>
        <div className="page-subtitle">{trade.strategy_name}</div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        {/* Entry */}
        <div className="card">
          <div className="section-title" style={{ marginBottom: 12 }}>Entry</div>
          <table style={{ width: "100%" }}><tbody>
            <Row label="Status" value={<span className={`badge ${isOpen ? "badge-blue" : "badge-gray"}`}>{trade.status}</span>} />
            <Row label="Side" value={trade.side.toUpperCase()} />
            <Row label="Entry Time" value={new Date(trade.entry_timestamp).toLocaleString()} />
            <Row label="Entry Price" value={`$${fmt(trade.entry_price, 2)}`} />
            <Row label="Entry DVOL" value={fmt(trade.entry_dvol, 1)} />
            <Row label="Entry N3z" value={<span style={{ fontWeight: 700, color: "#4ade80" }}>{fmt(trade.entry_n3_z, 4)}</span>} />
            <Row label="Planned Exit" value={trade.planned_exit_timestamp ? new Date(trade.planned_exit_timestamp).toLocaleString() : "—"} />
          </tbody></table>
        </div>

        {/* Exit / PnL */}
        <div className="card">
          <div className="section-title" style={{ marginBottom: 12 }}>
            {isOpen ? "Position Open" : "Exit & PnL"}
          </div>
          {isOpen ? (
            <div style={{ color: "#64748b", padding: "20px 0" }}>Waiting for 24h exit…</div>
          ) : (
            <table style={{ width: "100%" }}><tbody>
              <Row label="Exit Time" value={trade.exit_timestamp ? new Date(trade.exit_timestamp).toLocaleString() : "—"} />
              <Row label="Exit Price" value={`$${fmt(trade.exit_price, 2)}`} />
              <Row label="Exit Reason" value={trade.exit_reason ?? "—"} />
              <Row label="" value={null} />
              <Row label="Price Return" value={<PnlBp bp={trade.gross_price_return_bp} />} />
              <Row label="Funding PnL" value={<PnlBp bp={trade.funding_pnl_bp} />} />
              <Row label="Fees" value={<span className="negative">-{fmt(trade.fees_bp, 1)} bp</span>} />
              <Row label="Net PnL" value={<PnlBp bp={trade.net_pnl_bp} />} />
            </tbody></table>
          )}
        </div>
      </div>

      {/* Signal context */}
      <div className="section">
        <div className="section-title">Signal Context at Entry</div>
        <div className="card">
          <div style={{ fontSize: 13, color: "#94a3b8", lineHeight: 1.8 }}>
            <div>Strategy: <strong style={{ color: "#e2e8f0" }}>{trade.strategy_name}</strong></div>
            <div>Entry DVOL: <strong style={{ color: "#e2e8f0" }}>{fmt(trade.entry_dvol, 1)}</strong> (threshold: 54)</div>
            <div>Entry N3z: <strong style={{ color: "#4ade80" }}>{fmt(trade.entry_n3_z, 4)}</strong> (threshold: 0.75)</div>
            <div>Rule: <em>N3z &gt; 0.75 AND DVOL ≥ 54 → LONG</em></div>
          </div>
        </div>
      </div>
    </div>
  );
}
