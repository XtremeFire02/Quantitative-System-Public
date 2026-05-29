import React, { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { api } from "../api";
import type { OptionsChainRow } from "../api";

const tt = { background: "#0d0d0d", border: "1px solid #2a2a2a", color: "#cccccc" };
const fmt = (v: number | null, d = 2) =>
  v == null ? "—" : v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const iv = (v: number | null) => (v == null ? "—" : `${v.toFixed(1)}%`);

// ── IV Smile chart ────────────────────────────────────────────────────────────

function SmileChart({ rows, spotPrice }: { rows: OptionsChainRow[]; spotPrice: number | null }) {
  const data = rows
    .filter(r => r.call_iv != null || r.put_iv != null)
    .map(r => ({
      strike: r.strike,
      call_iv: r.call_iv,
      put_iv: r.put_iv,
      moneyness: spotPrice ? ((r.strike - spotPrice) / spotPrice) * 100 : null,
    }));

  const xKey = spotPrice ? "moneyness" : "strike";
  const xLabel = spotPrice ? "Moneyness (%)" : "Strike";

  return (
    <div className="chart-container">
      <div className="chart-title">IV Smile</div>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" />
          <XAxis
            dataKey={xKey}
            tick={{ fill: "#555", fontSize: 9 }}
            tickFormatter={v => spotPrice ? `${v.toFixed(1)}%` : `${(v / 1000).toFixed(0)}K`}
            label={{ value: xLabel, position: "insideBottom", fill: "#555", fontSize: 9 }}
          />
          <YAxis
            tick={{ fill: "#555", fontSize: 9 }}
            tickFormatter={v => `${v.toFixed(0)}%`}
          />
          <Tooltip
            contentStyle={tt}
            formatter={(v: any, name: any) => [v != null ? `${Number(v).toFixed(1)}%` : "—", name === "call_iv" ? "Call IV" : "Put IV"]}
            labelFormatter={v => spotPrice ? `Moneyness: ${(v as number).toFixed(2)}%` : `Strike: $${v}`}
          />
          <Line type="monotone" dataKey="call_iv" stroke="#00cc44" dot={false} strokeWidth={1.5} connectNulls name="call_iv" />
          <Line type="monotone" dataKey="put_iv"  stroke="#ff3333" dot={false} strokeWidth={1.5} connectNulls name="put_iv" />
        </LineChart>
      </ResponsiveContainer>
      <div style={{ display: "flex", gap: 16, fontSize: 10, fontFamily: "Courier New", color: "#555", marginTop: 4 }}>
        <span><span style={{ color: "#00cc44" }}>── </span>Call IV</span>
        <span><span style={{ color: "#ff3333" }}>── </span>Put IV</span>
        {spotPrice && <span style={{ marginLeft: "auto" }}>Spot: ${spotPrice.toLocaleString("en-US", { maximumFractionDigits: 0 })}</span>}
      </div>
    </div>
  );
}

// ── Options chain table ───────────────────────────────────────────────────────

function ChainTable({ rows, spotPrice }: { rows: OptionsChainRow[]; spotPrice: number | null }) {
  return (
    <div className="table-wrapper">
      <table>
        <thead>
          <tr>
            {/* Call side */}
            <th style={{ textAlign: "right" }}>Vol (USD)</th>
            <th style={{ textAlign: "right" }}>OI</th>
            <th style={{ textAlign: "right" }}>Bid IV</th>
            <th style={{ textAlign: "right" }}>IV</th>
            <th style={{ textAlign: "right" }}>Ask IV</th>
            <th style={{ textAlign: "right" }}>Bid</th>
            <th style={{ textAlign: "right" }}>Ask</th>
            {/* Strike */}
            <th style={{ textAlign: "center", color: "#ffcc00", background: "#1a1400" }}>STRIKE</th>
            {/* Put side */}
            <th>Bid</th>
            <th>Ask</th>
            <th>Bid IV</th>
            <th>IV</th>
            <th>Ask IV</th>
            <th>OI</th>
            <th>Vol (USD)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => {
            const atm = spotPrice != null && Math.abs(r.strike - spotPrice) / spotPrice < 0.02;
            const style = atm
              ? { background: "#1a1400", fontWeight: 700 }
              : {};

            return (
              <tr key={r.strike} style={style}>
                {/* Call side (right-aligned, greens) */}
                <td style={{ textAlign: "right", fontFamily: "monospace", color: "#555", fontSize: 10 }}>
                  {r.call_volume != null ? `$${(r.call_volume / 1000).toFixed(0)}K` : "—"}
                </td>
                <td style={{ textAlign: "right", fontFamily: "monospace", color: "#555", fontSize: 10 }}>
                  {r.call_oi != null ? r.call_oi.toFixed(0) : "—"}
                </td>
                <td style={{ textAlign: "right", fontFamily: "monospace", color: "#00cc44", fontSize: 10 }}>
                  {iv(r.call_bid_iv)}
                </td>
                <td style={{ textAlign: "right", fontFamily: "monospace", fontWeight: 700, color: "#00cc44" }}>
                  {iv(r.call_iv)}
                </td>
                <td style={{ textAlign: "right", fontFamily: "monospace", color: "#00cc44", fontSize: 10 }}>
                  {iv(r.call_ask_iv)}
                </td>
                <td style={{ textAlign: "right", fontFamily: "monospace", color: "#00cc44", fontSize: 10 }}>
                  {r.call_bid != null ? r.call_bid.toFixed(4) : "—"}
                </td>
                <td style={{ textAlign: "right", fontFamily: "monospace", color: "#00cc44", fontSize: 10 }}>
                  {r.call_ask != null ? r.call_ask.toFixed(4) : "—"}
                </td>
                {/* Strike */}
                <td style={{
                  textAlign: "center", fontFamily: "monospace", fontWeight: 700,
                  color: atm ? "#ffcc00" : "#cccccc",
                  background: atm ? "#1a1400" : "var(--surface-2)",
                }}>
                  ${r.strike.toLocaleString("en-US", { maximumFractionDigits: 0 })}
                </td>
                {/* Put side (left-aligned, reds) */}
                <td style={{ fontFamily: "monospace", color: "#ff3333", fontSize: 10 }}>
                  {r.put_bid != null ? r.put_bid.toFixed(4) : "—"}
                </td>
                <td style={{ fontFamily: "monospace", color: "#ff3333", fontSize: 10 }}>
                  {r.put_ask != null ? r.put_ask.toFixed(4) : "—"}
                </td>
                <td style={{ fontFamily: "monospace", color: "#ff3333", fontSize: 10 }}>
                  {iv(r.put_bid_iv)}
                </td>
                <td style={{ fontFamily: "monospace", fontWeight: 700, color: "#ff3333" }}>
                  {iv(r.put_iv)}
                </td>
                <td style={{ fontFamily: "monospace", color: "#ff3333", fontSize: 10 }}>
                  {iv(r.put_ask_iv)}
                </td>
                <td style={{ fontFamily: "monospace", color: "#555", fontSize: 10 }}>
                  {r.put_oi != null ? r.put_oi.toFixed(0) : "—"}
                </td>
                <td style={{ fontFamily: "monospace", color: "#555", fontSize: 10 }}>
                  {r.put_volume != null ? `$${(r.put_volume / 1000).toFixed(0)}K` : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Options() {
  const [currency, setCurrency] = useState<"BTC" | "ETH">("BTC");
  const [expiries, setExpiries] = useState<string[]>([]);
  const [expiry, setExpiry] = useState<string | null>(null);
  const [rows, setRows] = useState<OptionsChainRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [strikeFilter, setStrikeFilter] = useState<"all" | "atm">("atm");

  // Load expiry list when currency changes
  useEffect(() => {
    setLoading(true);
    api.optionsExpiries(currency)
      .then(r => {
        setExpiries(r.expiries);
        setExpiry(r.expiries[0] ?? null);
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [currency]);

  // Load chain when expiry changes
  useEffect(() => {
    if (!expiry) return;
    setLoading(true);
    api.optionsChain(currency, expiry)
      .then(r => setRows(r.rows))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [currency, expiry]);

  const spotPrice = rows[0]?.underlying_price ?? null;

  const displayRows = strikeFilter === "atm" && spotPrice != null
    ? rows.filter(r => r.strike >= spotPrice * 0.7 && r.strike <= spotPrice * 1.5)
    : rows;

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="page-title">Options</div>
          <div className="page-subtitle">
            {spotPrice != null
              ? `${currency} spot $${spotPrice.toLocaleString("en-US", { maximumFractionDigits: 0 })} · ${rows.length} strikes · Deribit`
              : "Options chain · IV smile · Deribit"}
          </div>
        </div>
        <button className="btn btn-ghost" onClick={() => {
          if (expiry) {
            setLoading(true);
            api.optionsChain(currency, expiry).then(r => setRows(r.rows)).finally(() => setLoading(false));
          }
        }}>↻ Refresh</button>
      </div>

      {error && <div className="error-msg" style={{ marginBottom: 12 }}>{error}</div>}

      {/* Controls */}
      <div className="btn-row" style={{ marginBottom: 16 }}>
        <button className={`btn ${currency === "BTC" ? "btn-primary" : "btn-ghost"}`} onClick={() => setCurrency("BTC")}>BTC</button>
        <button className={`btn ${currency === "ETH" ? "btn-primary" : "btn-ghost"}`} onClick={() => setCurrency("ETH")}>ETH</button>

        <div style={{ borderLeft: "1px solid #2a2a2a", marginLeft: 4, paddingLeft: 8, display: "flex", gap: 4, flexWrap: "wrap" }}>
          {expiries.slice(0, 12).map(e => (
            <button
              key={e}
              className={`btn ${expiry === e ? "btn-primary" : "btn-ghost"}`}
              style={{ fontSize: 9, height: 20, padding: "0 6px" }}
              onClick={() => setExpiry(e)}
            >
              {e}
            </button>
          ))}
        </div>

        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          <button className={`btn ${strikeFilter === "atm" ? "btn-secondary" : "btn-ghost"}`}
            onClick={() => setStrikeFilter(s => s === "atm" ? "all" : "atm")}>
            {strikeFilter === "atm" ? "Near ATM" : "All Strikes"}
          </button>
        </div>
      </div>

      {loading && <div className="loading">Loading options data…</div>}

      {!loading && rows.length > 0 && (
        <>
          {/* IV smile */}
          <SmileChart rows={displayRows} spotPrice={spotPrice} />

          {/* Call/Put header labels */}
          <div style={{
            display: "grid", gridTemplateColumns: "1fr auto 1fr",
            textAlign: "center", fontSize: 10, fontWeight: 700,
            color: "#555", marginTop: 16, marginBottom: 4, fontFamily: "Arial",
            textTransform: "uppercase", letterSpacing: 1,
          }}>
            <div style={{ color: "#00cc44" }}>CALLS</div>
            <div></div>
            <div style={{ color: "#ff3333" }}>PUTS</div>
          </div>

          <ChainTable rows={displayRows} spotPrice={spotPrice} />

          {displayRows.length === 0 && (
            <div className="card" style={{ color: "#555", marginTop: 12 }}>No strikes near ATM.</div>
          )}
        </>
      )}

      {!loading && rows.length === 0 && !error && (
        <div className="card" style={{ color: "#555" }}>
          No options data available. Deribit may be unavailable or the currency has no listed options.
        </div>
      )}
    </div>
  );
}
