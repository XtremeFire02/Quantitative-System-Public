import React, { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { api } from "../api";
import type { MarketMonitorData, TermStructureData, CorrelationMatrix, LiquidationsSummary } from "../api";

const tt = { background: "#0d0d0d", border: "1px solid #2a2a2a", color: "#cccccc" };
const fmt = (v: number | null, d = 2) =>
  v == null ? "—" : v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

function pct(v: number | null, d = 2) {
  return v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(d)}%`;
}

function fundingColor(r: number | null): string {
  if (r == null) return "#666";
  if (r > 0.0005) return "#ff6600";
  if (r > 0) return "#00cc44";
  return "#ff3333";
}

// ── Asset card ────────────────────────────────────────────────────────────────

function AssetCard({ asset }: { asset: MarketMonitorData["assets"][0] }) {
  const chg = asset.price_change_pct;
  const fRate = asset.funding_rate;

  return (
    <div className="card" style={{ minWidth: 200 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <span style={{ fontFamily: "Courier New", fontWeight: 700, fontSize: 13 }}>{asset.base}</span>
        {chg != null && (
          <span style={{ color: chg >= 0 ? "#00cc44" : "#ff3333", fontSize: 11, fontWeight: 700 }}>
            {pct(chg)}
          </span>
        )}
      </div>

      <div style={{ fontFamily: "Courier New", fontSize: 18, fontWeight: 700, color: "#e0e0e0", marginBottom: 4 }}>
        ${asset.price != null ? asset.price.toLocaleString("en-US", { maximumFractionDigits: 2 }) : "—"}
      </div>

      <div style={{ fontSize: 10, fontFamily: "Courier New", lineHeight: 1.8, color: "#555" }}>
        <div>Mark: <span style={{ color: "#ccc" }}>${fmt(asset.mark_price)}</span></div>
        <div>
          Funding:{" "}
          <span style={{ color: fundingColor(fRate), fontWeight: 700 }}>
            {fRate != null ? `${(fRate * 100).toFixed(4)}%` : "—"}
          </span>
        </div>
        {asset.open_interest != null && (
          <div>OI: <span style={{ color: "#ccc" }}>${(asset.open_interest / 1e9).toFixed(2)}B</span></div>
        )}
        {asset.dvol != null && (
          <div>DVOL: <span style={{ color: "#3399ff" }}>{asset.dvol.toFixed(1)}</span></div>
        )}
        {asset.volume != null && asset.quote_volume != null && (
          <div>Vol: <span style={{ color: "#ccc" }}>${(asset.quote_volume / 1e9).toFixed(2)}B</span></div>
        )}
        <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
          <span style={{ color: "#555" }}>L: ${fmt(asset.low_24h, 0)}</span>
          <span style={{ color: "#555" }}>H: ${fmt(asset.high_24h, 0)}</span>
        </div>
      </div>
    </div>
  );
}

// ── Term structure chart ──────────────────────────────────────────────────────

function TermStructureChart({ data }: { data: TermStructureData }) {
  const chartData = data.contracts.map(c => ({
    label: c.contract_type === "PERPETUAL" ? "PERP" : c.delivery_date ? c.delivery_date.slice(0, 10) : c.symbol,
    mark: c.mark_price,
    basis: c.basis_pct,
    funding: c.funding_rate * 100,
  }));

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      <div>
        <div className="chart-title">Mark Price ({data.base})</div>
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" />
            <XAxis dataKey="label" tick={{ fill: "#555", fontSize: 9 }} />
            <YAxis tick={{ fill: "#555", fontSize: 9 }} domain={["auto", "auto"]} />
            <Tooltip contentStyle={tt} formatter={(v: any) => [`$${Number(v).toFixed(2)}`, "Mark"]} />
            <Line type="monotone" dataKey="mark" stroke="#ff6600" dot={true} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div>
        <div className="chart-title">Basis % vs Perpetual</div>
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" />
            <XAxis dataKey="label" tick={{ fill: "#555", fontSize: 9 }} />
            <YAxis tick={{ fill: "#555", fontSize: 9 }} tickFormatter={v => `${v.toFixed(2)}%`} />
            <Tooltip contentStyle={tt} formatter={(v: any) => [`${Number(v).toFixed(4)}%`, "Basis"]} />
            <Line type="monotone" dataKey="basis" stroke="#3399ff" dot={true} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── Correlation matrix ────────────────────────────────────────────────────────

function CorrelationHeatmap({ corr }: { corr: CorrelationMatrix }) {
  const { labels, matrix } = corr;

  const corColor = (v: number | null): string => {
    if (v == null) return "#111";
    const abs = Math.abs(v);
    if (abs >= 0.9) return v > 0 ? "#ff6600" : "#3399ff";
    if (abs >= 0.7) return v > 0 ? "#cc5200" : "#0077cc";
    if (abs >= 0.5) return v > 0 ? "#884400" : "#004488";
    return "#2a2a2a";
  };

  const fgColor = (v: number | null): string => {
    if (v == null) return "#444";
    return Math.abs(v) >= 0.5 ? "#ffffff" : "#777";
  };

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ borderCollapse: "collapse", fontFamily: "Courier New", fontSize: 11 }}>
        <thead>
          <tr>
            <th style={{ padding: "4px 8px", color: "#555", textAlign: "left" }}></th>
            {labels.map(l => (
              <th key={l} style={{ padding: "4px 8px", color: "#ff6600", fontSize: 9, textAlign: "center" }}>{l}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, i) => (
            <tr key={labels[i]}>
              <td style={{ padding: "4px 8px", color: "#ff6600", fontSize: 9, fontWeight: 700 }}>{labels[i]}</td>
              {row.map((v, j) => (
                <td
                  key={j}
                  style={{
                    padding: "6px 12px",
                    background: corColor(v),
                    color: fgColor(v),
                    textAlign: "center",
                    fontWeight: i === j ? 700 : 400,
                  }}
                >
                  {v != null ? v.toFixed(2) : "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ fontSize: 10, color: "#444", marginTop: 6, fontFamily: "Courier New" }}>
        Pearson correlation of {corr.period_days}d daily log returns · Updated {new Date(corr.fetched_at).toLocaleString()}
      </div>
    </div>
  );
}

// ── Liquidation heatmap ───────────────────────────────────────────────────────

function LiquidationHeatmap({ data }: { data: LiquidationsSummary }) {
  const maxUsd = Math.max(...data.assets.map(a => a.total_usd || 0)) || 1;
  return (
    <div className="table-wrapper">
      <table>
        <thead>
          <tr>
            <th>Symbol</th><th>Long Liq (USD)</th><th>Short Liq (USD)</th>
            <th>Total</th><th>Dominant Side</th><th>Events</th>
          </tr>
        </thead>
        <tbody>
          {data.assets.map(a => {
            if ("error" in a) return (
              <tr key={a.symbol}>
                <td style={{ fontFamily: "monospace" }}>{a.symbol}</td>
                <td colSpan={5} style={{ color: "#ff3333", fontSize: 10 }}>Error</td>
              </tr>
            );
            const longBar = (a.long_liquidated_usd / maxUsd) * 80;
            const shortBar = (a.short_liquidated_usd / maxUsd) * 80;
            return (
              <tr key={a.symbol}>
                <td style={{ fontFamily: "monospace", fontSize: 12 }}>{a.symbol}</td>
                <td>
                  <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                    <div style={{ width: `${longBar}px`, height: 12, background: "#ff333344", border: "1px solid #ff333366", minWidth: 2 }} />
                    <span style={{ color: "#ff3333", fontSize: 11, fontFamily: "monospace" }}>
                      ${(a.long_liquidated_usd / 1e6).toFixed(2)}M
                    </span>
                  </div>
                </td>
                <td>
                  <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                    <div style={{ width: `${shortBar}px`, height: 12, background: "#00cc4444", border: "1px solid #00cc4466", minWidth: 2 }} />
                    <span style={{ color: "#00cc44", fontSize: 11, fontFamily: "monospace" }}>
                      ${(a.short_liquidated_usd / 1e6).toFixed(2)}M
                    </span>
                  </div>
                </td>
                <td style={{ fontFamily: "monospace", fontSize: 11 }}>
                  ${(a.total_usd / 1e6).toFixed(2)}M
                </td>
                <td>
                  <span className={`badge ${a.dominant_side === "long" ? "badge-red" : a.dominant_side === "short" ? "badge-green" : "badge-gray"}`}>
                    {a.dominant_side.toUpperCase()}
                  </span>
                </td>
                <td style={{ color: "#555", fontSize: 11 }}>{a.n_events}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function MarketMonitor() {
  const [monitor, setMonitor] = useState<MarketMonitorData | null>(null);
  const [termBase, setTermBase] = useState("BTC");
  const [termData, setTermData] = useState<TermStructureData | null>(null);
  const [corr, setCorr] = useState<CorrelationMatrix | null>(null);
  const [corrPeriod, setCorrPeriod] = useState(30);
  const [liqs, setLiqs] = useState<LiquidationsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [errors, setErrors] = useState<string[]>([]);

  const load = () => {
    setLoading(true);
    setErrors([]);
    Promise.allSettled([
      api.marketMonitor(),
      api.termStructure(termBase),
      api.correlations(corrPeriod),
      api.liquidationsSummary(),
    ]).then(([monRes, termRes, corrRes, liqRes]) => {
      const errs: string[] = [];
      if (monRes.status === "fulfilled") setMonitor(monRes.value);
      else errs.push(`Monitor: ${(monRes.reason as Error).message}`);
      if (termRes.status === "fulfilled") setTermData(termRes.value);
      else errs.push(`Term structure: ${(termRes.reason as Error).message}`);
      if (corrRes.status === "fulfilled") setCorr(corrRes.value);
      else errs.push(`Correlations: ${(corrRes.reason as Error).message}`);
      if (liqRes.status === "fulfilled") setLiqs(liqRes.value);
      setErrors(errs);
    }).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [termBase, corrPeriod]);

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="page-title">Market Monitor</div>
          <div className="page-subtitle">
            Multi-asset prices · Funding rates · Term structure · Correlations
          </div>
        </div>
        <button className="btn btn-ghost" onClick={load}>↻ Refresh</button>
      </div>

      {errors.map((e, i) => <div key={i} className="error-msg" style={{ marginBottom: 8 }}>{e}</div>)}
      {loading && <div className="loading">Loading market data…</div>}

      {/* Asset grid */}
      {monitor && (
        <div className="cards-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", marginBottom: 20 }}>
          {monitor.assets.map(a => <AssetCard key={a.symbol} asset={a} />)}
        </div>
      )}

      {/* Term structure */}
      <div className="section-title" style={{ marginBottom: 12 }}>
        Futures Term Structure
        <span style={{ marginLeft: 12, fontWeight: 400 }}>
          {["BTC", "ETH", "SOL", "BNB"].map(b => (
            <button
              key={b}
              className={`btn ${termBase === b ? "btn-primary" : "btn-ghost"}`}
              style={{ marginLeft: 4, height: 20, padding: "0 8px", fontSize: 9 }}
              onClick={() => setTermBase(b)}
            >
              {b}
            </button>
          ))}
        </span>
      </div>

      {termData && (
        <div className="chart-container" style={{ marginBottom: 20 }}>
          <TermStructureChart data={termData} />
          <div style={{ marginTop: 12 }}>
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Contract</th><th>Type</th><th>Mark Price</th>
                    <th>Index Price</th><th>Basis %</th><th>Funding</th><th>Delivery</th>
                  </tr>
                </thead>
                <tbody>
                  {termData.contracts.map(c => (
                    <tr key={c.symbol}>
                      <td style={{ fontFamily: "monospace", fontSize: 11 }}>{c.symbol}</td>
                      <td><span className={`badge ${c.contract_type === "PERPETUAL" ? "badge-blue" : "badge-gray"}`}>{c.contract_type.replace("_", " ")}</span></td>
                      <td style={{ fontFamily: "monospace" }}>${fmt(c.mark_price)}</td>
                      <td style={{ fontFamily: "monospace" }}>${fmt(c.index_price)}</td>
                      <td style={{ fontFamily: "monospace", color: c.basis_pct >= 0 ? "#00cc44" : "#ff3333" }}>
                        {c.basis_pct === 0 ? "—" : `${c.basis_pct >= 0 ? "+" : ""}${c.basis_pct.toFixed(4)}%`}
                      </td>
                      <td style={{ fontFamily: "monospace", color: fundingColor(c.funding_rate) }}>
                        {(c.funding_rate * 100).toFixed(4)}%
                      </td>
                      <td style={{ color: "#555", fontSize: 11 }}>{c.delivery_date ? c.delivery_date.slice(0, 10) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Correlation matrix */}
      <div className="section-title" style={{ marginBottom: 12 }}>
        Return Correlations
        <span style={{ marginLeft: 12, fontWeight: 400 }}>
          {[7, 14, 30, 60, 90].map(p => (
            <button
              key={p}
              className={`btn ${corrPeriod === p ? "btn-primary" : "btn-ghost"}`}
              style={{ marginLeft: 4, height: 20, padding: "0 8px", fontSize: 9 }}
              onClick={() => setCorrPeriod(p)}
            >
              {p}D
            </button>
          ))}
        </span>
      </div>

      {corr && (
        <div className="chart-container">
          <CorrelationHeatmap corr={corr} />
        </div>
      )}

      {/* Liquidations */}
      {liqs && (
        <>
          <div className="section-title" style={{ marginTop: 20, marginBottom: 12 }}>
            Liquidation Heatmap
            <span style={{ fontWeight: 400, marginLeft: 8, fontSize: 10, color: "#555" }}>
              recent forced orders · long = buyers liquidated (short squeeze fuel) · short = sellers liquidated
            </span>
          </div>
          <LiquidationHeatmap data={liqs} />
        </>
      )}
    </div>
  );
}
