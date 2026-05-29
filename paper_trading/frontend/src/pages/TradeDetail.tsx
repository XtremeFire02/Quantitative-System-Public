import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, TradeRecord } from "../api";

const fmt = (v: number | null, dec = 2) =>
  v == null ? "—" : v.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <tr>
      <td style={{ color: "#555555", width: 200, paddingRight: 12 }}>{label}</td>
      <td>{value}</td>
    </tr>
  );
}

function PnlBp({ bp }: { bp: number | null }) {
  if (bp == null) return <span style={{ color: "#444444" }}>—</span>;
  const color = bp > 0 ? "#00cc44" : bp < 0 ? "#ff3333" : "#666666";
  return <span style={{ color, fontWeight: 700, fontFamily: "monospace" }}>
    {bp > 0 ? "+" : ""}{fmt(bp, 1)} bp
  </span>;
}

function QualityBar({ score }: { score: number | null }) {
  if (score == null) return <span style={{ color: "#444444" }}>—</span>;
  const color = score >= 7 ? "#00cc44" : score >= 4 ? "#ffcc00" : "#ff3333";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ width: 80, background: "#1a1a1a", height: 8, border: "1px solid #2a2a2a" }}>
        <div style={{ width: `${score * 10}%`, height: "100%", background: color }} />
      </div>
      <span style={{ fontFamily: "monospace", color, fontSize: 13, fontWeight: 600 }}>
        {score.toFixed(1)}/10
      </span>
    </div>
  );
}

export default function TradeDetail() {
  const { id } = useParams<{ id: string }>();
  const [trade, setTrade] = useState<TradeRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [closing, setClosing] = useState(false);
  const [closeResult, setCloseResult] = useState<string | null>(null);

  const reload = () => {
    if (!id) return;
    api.trade(Number(id)).then(setTrade).catch(e => setError(e.message));
  };

  useEffect(() => {
    if (!id) return;
    api.trade(Number(id)).then(setTrade).catch(e => setError(e.message)).finally(() => setLoading(false));
  }, [id]);

  const handleClose = async () => {
    if (!id || !window.confirm("Manually close this trade at the current market price?")) return;
    setClosing(true);
    setCloseResult(null);
    try {
      const res = await api.closeTrade(Number(id));
      setCloseResult(`Closed. Net PnL: ${res.net_pnl_bp != null ? res.net_pnl_bp.toFixed(1) + " bp" : "N/A"}`);
      reload();
    } catch (e: unknown) {
      setCloseResult(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setClosing(false);
    }
  };

  if (loading) return <div className="loading">Loading…</div>;
  if (error) return (
    <div>
      <div className="page-header">
        <Link to="/trades" style={{ color: "#555555", fontSize: 12, textDecoration: "none" }}>← Trades</Link>
        <div className="page-title" style={{ marginTop: 6 }}>Trade not found</div>
      </div>
      <div className="card" style={{ color: "#ff3333" }}>{error}</div>
    </div>
  );
  if (!trade) return (
    <div>
      <div className="page-header">
        <Link to="/trades" style={{ color: "#555555", fontSize: 12, textDecoration: "none" }}>← Trades</Link>
        <div className="page-title" style={{ marginTop: 6 }}>Trade not found</div>
      </div>
      <div className="card" style={{ color: "#555555" }}>No trade data available for this ID.</div>
    </div>
  );

  const isOpen = trade.status === "open";
  const slippageBp = trade.slippage_bp ?? (trade.slippage != null ? trade.slippage * 10000 : null);
  const fillDriftBp = (trade.signal_price != null && trade.entry_price != null && trade.signal_price !== 0)
    ? (trade.entry_price - trade.signal_price) / trade.signal_price * 10000
    : null;

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <Link to="/trades" style={{ color: "#555555", fontSize: 12, textDecoration: "none" }}>← Trades</Link>
          <div className="page-title" style={{ marginTop: 6 }}>Trade #{trade.id}</div>
          <div className="page-subtitle">{trade.strategy_name} · {trade.market ?? "BTCUSDT"}</div>
        </div>
        {isOpen && (
          <div>
            <button className="btn btn-secondary" onClick={handleClose} disabled={closing}>
              {closing ? "Closing…" : "✕ Close Now"}
            </button>
            {closeResult && (
              <div style={{ fontSize: 11, marginTop: 6, color: closeResult.startsWith("Error") ? "#ff3333" : "#00cc44" }}>
                {closeResult}
              </div>
            )}
          </div>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 20 }}>
        <div className="card">
          <div className="section-title" style={{ marginBottom: 12 }}>Entry</div>
          <table style={{ width: "100%" }}><tbody>
            <Row label="Status" value={
              <span className={`badge ${isOpen ? "badge-blue" : "badge-gray"}`}>{trade.status}</span>
            } />
            <Row label="Side" value={
              <span className={`badge ${trade.side === "long" ? "badge-green" : "badge-red"}`}>
                {trade.side.toUpperCase()}
              </span>
            } />
            <Row label="Entry Time" value={new Date(trade.entry_timestamp).toLocaleString()} />
            <Row label="Signal Price" value={
              trade.signal_price != null
                ? <span style={{ fontFamily: "monospace" }}>${fmt(trade.signal_price)}</span>
                : <span style={{ color: "#444444" }}>—</span>
            } />
            <Row label="Fill Price" value={
              <span style={{ fontFamily: "monospace" }}>${fmt(trade.entry_price)}</span>
            } />
            <Row label="Fill Type" value={
              trade.fill_type
                ? <span className={`badge ${trade.fill_type === "maker" ? "badge-green" : "badge-yellow"}`}>
                    {trade.fill_type}
                  </span>
                : <span style={{ color: "#444444" }}>—</span>
            } />
            <Row label="Fill Drift" value={
              fillDriftBp != null
                ? <span style={{ fontFamily: "monospace", color: Math.abs(fillDriftBp) < 1 ? "#00cc44" : "#ffcc00" }}>
                    {fillDriftBp >= 0 ? "+" : ""}{fillDriftBp.toFixed(1)} bp
                  </span>
                : <span style={{ color: "#444444" }}>—</span>
            } />
            <Row label="Notional" value={
              trade.notional_usd != null
                ? <span style={{ fontFamily: "monospace" }}>
                    ${trade.notional_usd.toLocaleString("en-US", { maximumFractionDigits: 0 })}
                  </span>
                : <span style={{ color: "#444444" }}>—</span>
            } />
            <Row label="Planned Exit" value={
              trade.planned_exit_timestamp ? new Date(trade.planned_exit_timestamp).toLocaleString() : "—"
            } />
          </tbody></table>
        </div>

        <div className="card">
          <div className="section-title" style={{ marginBottom: 12 }}>
            {isOpen ? "Position Open" : "Exit & PnL"}
          </div>
          {isOpen ? (
            <div style={{ color: "#444444", padding: "20px 0" }}>Waiting for exit…</div>
          ) : (
            <table style={{ width: "100%" }}><tbody>
              <Row label="Exit Time" value={
                trade.exit_timestamp ? new Date(trade.exit_timestamp).toLocaleString() : "—"
              } />
              {trade.exit_signal_price != null && (
                <Row label="Exit Market Price" value={
                  <span style={{ fontFamily: "monospace" }}>${fmt(trade.exit_signal_price)}</span>
                } />
              )}
              <Row label="Exit Fill Price" value={
                <span style={{ fontFamily: "monospace" }}>${fmt(trade.exit_price)}</span>
              } />
              <Row label="Exit Reason" value={
                <span style={{ fontSize: 12, color: "#666666" }}>{trade.exit_reason ?? "—"}</span>
              } />
              <Row label="" value={null} />
              <Row label="Price Return" value={<PnlBp bp={trade.gross_price_return_bp} />} />
              <Row label="Funding PnL"  value={<PnlBp bp={trade.funding_pnl_bp} />} />
              <Row label="Slippage"     value={
                slippageBp != null && slippageBp !== 0
                  ? <span style={{ fontFamily: "monospace", color: "#ff3333" }}>
                      -{Math.abs(slippageBp).toFixed(1)} bp
                    </span>
                  : <span style={{ color: "#444444" }}>0 bp (in fill)</span>
              } />
              <Row label="Fees" value={
                <span style={{ fontFamily: "monospace", color: "#ff3333" }}>
                  -{fmt(trade.fees_bp, 1)} bp
                </span>
              } />
              <Row label="Net PnL" value={<PnlBp bp={trade.net_pnl_bp} />} />
            </tbody></table>
          )}
        </div>
      </div>

      <div className="card" style={{ marginBottom: 20 }}>
        <div className="section-title" style={{ marginBottom: 12 }}>Execution Quality</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 20 }}>
          <div>
            <div style={{ fontSize: 11, color: "#555555", marginBottom: 6 }}>Entry Quality Score</div>
            <QualityBar score={trade.entry_quality_score} />
          </div>
          <div>
            <div style={{ fontSize: 11, color: "#555555", marginBottom: 6 }}>Entry Half Spread</div>
            <span style={{ fontFamily: "monospace", fontSize: 13 }}>
              {trade.entry_half_spread_bp != null ? `${trade.entry_half_spread_bp.toFixed(2)} bp` : "—"}
            </span>
          </div>
          <div>
            <div style={{ fontSize: 11, color: "#555555", marginBottom: 6 }}>Entry Impact</div>
            <span style={{ fontFamily: "monospace", fontSize: 13 }}>
              {trade.entry_impact_bp != null ? `${trade.entry_impact_bp.toFixed(2)} bp` : "—"}
            </span>
          </div>
          <div>
            <div style={{ fontSize: 11, color: "#555555", marginBottom: 6 }}>Entry DVOL</div>
            <span style={{ fontFamily: "monospace", fontSize: 13 }}>{fmt(trade.entry_dvol, 1)}</span>
          </div>
          <div>
            <div style={{ fontSize: 11, color: "#555555", marginBottom: 6 }}>Maker Fill Prob</div>
            <span style={{ fontFamily: "monospace", fontSize: 13 }}>
              {trade.entry_maker_prob != null ? `${(trade.entry_maker_prob * 100).toFixed(0)}%` : "—"}
            </span>
          </div>
          {!isOpen && (
            <>
              <div>
                <div style={{ fontSize: 11, color: "#555555", marginBottom: 6 }}>Exit Quality Score</div>
                <QualityBar score={trade.exit_quality_score} />
              </div>
              <div>
                <div style={{ fontSize: 11, color: "#555555", marginBottom: 6 }}>Exit Half Spread</div>
                <span style={{ fontFamily: "monospace", fontSize: 13 }}>
                  {trade.exit_half_spread_bp != null ? `${trade.exit_half_spread_bp.toFixed(2)} bp` : "—"}
                </span>
              </div>
              <div>
                <div style={{ fontSize: 11, color: "#555555", marginBottom: 6 }}>Exit Impact</div>
                <span style={{ fontFamily: "monospace", fontSize: 13 }}>
                  {trade.exit_impact_bp != null ? `${trade.exit_impact_bp.toFixed(2)} bp` : "—"}
                </span>
              </div>
            </>
          )}
        </div>
      </div>

      <div className="card">
        <div className="section-title" style={{ marginBottom: 12 }}>Signal Context</div>
        <div style={{ fontSize: 13, color: "#666666", lineHeight: 1.8, fontFamily: "Courier New" }}>
          <div>Strategy: <strong style={{ color: "#cccccc" }}>{trade.strategy_name}</strong></div>
          <div>Entry DVOL: <strong style={{ color: "#cccccc" }}>{fmt(trade.entry_dvol, 1)}</strong></div>
          {trade.entry_n3_z != null && (
            <div>N3z: <strong style={{ color: "#00cc44" }}>{fmt(trade.entry_n3_z, 4)}</strong></div>
          )}
          {trade.entry_reason && (
            <div style={{ marginTop: 8, fontSize: 12, color: "#444444", fontStyle: "italic" }}>
              {trade.entry_reason}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
