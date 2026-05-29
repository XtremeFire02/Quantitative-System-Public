import React, { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import { api } from "../api";
import type { IVSurfaceData, IVSurfaceRow } from "../api";

const tt = { background: "#0d0d0d", border: "1px solid #2a2a2a", color: "#cccccc" };

// ── IV colour scale ───────────────────────────────────────────────────────────

function ivColor(iv: number | null): string {
  if (iv == null) return "#111111";
  // Map 30–200 IV to a colour gradient: blue → green → yellow → red
  const lo = 30, hi = 150;
  const t = Math.min(1, Math.max(0, (iv - lo) / (hi - lo)));
  if (t < 0.33) {
    // blue → green
    const s = t / 0.33;
    const r = Math.round(0 + s * 0);
    const g = Math.round(100 + s * 100);
    const b = Math.round(200 - s * 100);
    return `rgb(${r},${g},${b})`;
  } else if (t < 0.66) {
    const s = (t - 0.33) / 0.33;
    return `rgb(${Math.round(s * 200)},${Math.round(200 - s * 60)},0)`;
  } else {
    const s = (t - 0.66) / 0.34;
    return `rgb(${Math.round(200 + s * 55)},${Math.round(140 - s * 140)},0)`;
  }
}

function ivTextColor(iv: number | null): string {
  if (iv == null) return "#333";
  return iv > 80 ? "#000" : "#e0e0e0";
}

// ── Surface heatmap ───────────────────────────────────────────────────────────

function SurfaceHeatmap({
  surface, expiries, strikes, useCall,
}: {
  surface: IVSurfaceRow[];
  expiries: string[];
  strikes: number[];
  useCall: boolean;
}) {
  // Build lookup map
  const lookup = new Map<string, IVSurfaceRow>();
  surface.forEach(r => lookup.set(`${r.expiry}|${r.strike}`, r));

  const cellSize = Math.max(32, Math.min(60, Math.floor(900 / expiries.length)));

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ borderCollapse: "collapse", tableLayout: "fixed" }}>
        <thead>
          <tr>
            <th style={{ padding: "4px 8px", color: "#ff6600", fontSize: 9, textAlign: "left", width: 80 }}>
              STRIKE
            </th>
            {expiries.map(e => (
              <th key={e} style={{
                padding: "4px 4px", color: "#555", fontSize: 8,
                textAlign: "center", width: cellSize, fontFamily: "Courier New",
              }}>
                {e}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {[...strikes].reverse().map(strike => (
            <tr key={strike}>
              <td style={{
                padding: "2px 8px", fontSize: 9, fontFamily: "Courier New",
                color: "#666", textAlign: "right",
              }}>
                ${strike >= 1000 ? `${(strike / 1000).toFixed(0)}K` : strike}
              </td>
              {expiries.map(expiry => {
                const row = lookup.get(`${expiry}|${strike}`);
                const iv = useCall ? row?.call_iv : row?.put_iv;
                return (
                  <td
                    key={expiry}
                    title={iv != null ? `${expiry} / $${strike} — IV: ${iv.toFixed(1)}%` : "—"}
                    style={{
                      background: ivColor(iv ?? null),
                      color: ivTextColor(iv ?? null),
                      textAlign: "center",
                      fontFamily: "Courier New",
                      fontSize: 9,
                      padding: "3px 2px",
                      height: 24,
                      borderRight: "1px solid #0a0a0a",
                      borderBottom: "1px solid #0a0a0a",
                    }}
                  >
                    {iv != null ? iv.toFixed(0) : ""}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── IV Term structure by moneyness ────────────────────────────────────────────

function TermIVChart({ surface, strikes, spotPrice }: {
  surface: IVSurfaceRow[];
  strikes: number[];
  spotPrice: number | null;
}) {
  if (!spotPrice) return null;

  // Pick ATM and wings: 0%, ±5%, ±10%
  const targets = [-0.10, -0.05, 0.0, 0.05, 0.10];
  const colors = ["#3399ff", "#00cc44", "#ff6600", "#ffcc00", "#ff3333"];
  const labels = ["-10%", "-5%", "ATM", "+5%", "+10%"];

  const nearestStrike = (target: number) => {
    const targetStrike = spotPrice * (1 + target);
    return strikes.reduce((a, b) =>
      Math.abs(b - targetStrike) < Math.abs(a - targetStrike) ? b : a
    );
  };

  const groups = targets.map((t, i) => ({
    label: labels[i],
    color: colors[i],
    strike: nearestStrike(t),
  }));

  // Unique expiries with at least one IV value
  const expiriesWithData = Array.from(new Set(surface.map(r => r.expiry)));

  const chartData = expiriesWithData.map(exp => {
    const entry: Record<string, string | number | null> = { expiry: exp };
    groups.forEach(g => {
      const row = surface.find(r => r.expiry === exp && r.strike === g.strike);
      entry[g.label] = row?.call_iv ?? null;
    });
    return entry;
  });

  return (
    <div className="chart-container">
      <div className="chart-title">IV Term Structure by Moneyness</div>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" />
          <XAxis dataKey="expiry" tick={{ fill: "#555", fontSize: 9 }} />
          <YAxis tick={{ fill: "#555", fontSize: 9 }} tickFormatter={v => `${v.toFixed(0)}%`} />
          <Tooltip contentStyle={tt} formatter={(v: any, name: any) => [`${Number(v)?.toFixed(1)}%`, name]} />
          <Legend wrapperStyle={{ fontSize: 10, color: "#555" }} />
          {groups.map(g => (
            <Line key={g.label} type="monotone" dataKey={g.label} stroke={g.color}
              dot={true} strokeWidth={1.5} connectNulls />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── DVOL history chart ────────────────────────────────────────────────────────

function DVOLHistoryChart({ currency }: { currency: string }) {
  const [history, setHistory] = useState<{ date: string; dvol: number | null }[]>([]);

  useEffect(() => {
    // Re-use the existing deribit client via the backend signal history
    // We approximate with signals history which includes dvol
    api.signalHistory(90)
      .then(signals => {
        const data = signals
          .filter(s => s.strategy_name.includes("N3") && s.dvol != null)
          .map(s => ({ date: s.timestamp.slice(0, 10), dvol: s.dvol }))
          .slice(-60);
        setHistory(data);
      })
      .catch(() => {});
  }, [currency]);

  if (!history.length) return null;

  return (
    <div className="chart-container">
      <div className="chart-title">BTC DVOL History (from signal log)</div>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={history}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" />
          <XAxis dataKey="date" tick={{ fill: "#555", fontSize: 9 }}
            tickFormatter={v => v.slice(5)} />
          <YAxis tick={{ fill: "#555", fontSize: 9 }} domain={["auto", "auto"]} />
          <Tooltip contentStyle={tt} formatter={(v: any) => [Number(v).toFixed(1), "DVOL"]} />
          <Line type="monotone" dataKey="dvol" stroke="#3399ff" dot={false} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function VolSurface() {
  const [currency, setCurrency] = useState<"BTC" | "ETH">("BTC");
  const [surface, setSurface] = useState<IVSurfaceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [optType, setOptType] = useState<"call" | "put">("call");
  const [strikeWindow, setStrikeWindow] = useState(20);

  const load = (cur = currency) => {
    setLoading(true);
    setError(null);
    api.optionsSurface(cur)
      .then(setSurface)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(currency); }, [currency]);

  // Filter to N strikes around ATM
  const filteredSurface = (() => {
    if (!surface) return null;
    const spotPrices = surface.surface.map(r => r.underlying_price).filter(v => v != null) as number[];
    const spotPrice = spotPrices[0] ?? null;
    if (!spotPrice || strikeWindow === 0) return surface;

    const sorted = [...surface.strikes].sort((a, b) => Math.abs(a - spotPrice) - Math.abs(b - spotPrice));
    const nearStrikes = new Set(sorted.slice(0, strikeWindow));
    return {
      ...surface,
      strikes: surface.strikes.filter(s => nearStrikes.has(s)),
      surface: surface.surface.filter(r => nearStrikes.has(r.strike)),
    };
  })();

  const spotPrice = surface?.surface.find(r => r.underlying_price != null)?.underlying_price ?? null;

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="page-title">Vol Surface</div>
          <div className="page-subtitle">
            {surface
              ? `${currency} · ${surface.expiries.length} expiries · ${surface.strikes.length} strikes · Deribit`
              : "IV surface heatmap · Term structure · Deribit options"}
          </div>
        </div>
        <button className="btn btn-ghost" onClick={() => load(currency)}>↻ Refresh</button>
      </div>

      {error && <div className="error-msg" style={{ marginBottom: 12 }}>{error}</div>}

      <div className="btn-row" style={{ marginBottom: 16 }}>
        <button className={`btn ${currency === "BTC" ? "btn-primary" : "btn-ghost"}`} onClick={() => setCurrency("BTC")}>BTC</button>
        <button className={`btn ${currency === "ETH" ? "btn-primary" : "btn-ghost"}`} onClick={() => setCurrency("ETH")}>ETH</button>

        <div style={{ borderLeft: "1px solid #2a2a2a", marginLeft: 4, paddingLeft: 8, display: "flex", gap: 4 }}>
          <button className={`btn ${optType === "call" ? "btn-secondary" : "btn-ghost"}`} onClick={() => setOptType("call")}>Calls</button>
          <button className={`btn ${optType === "put" ? "btn-secondary" : "btn-ghost"}`} onClick={() => setOptType("put")}>Puts</button>
        </div>

        <div style={{ borderLeft: "1px solid #2a2a2a", marginLeft: 4, paddingLeft: 8, display: "flex", gap: 4 }}>
          {[10, 20, 40, 0].map(n => (
            <button key={n} className={`btn ${strikeWindow === n ? "btn-secondary" : "btn-ghost"}`}
              style={{ fontSize: 9, padding: "0 8px" }}
              onClick={() => setStrikeWindow(n)}>
              {n === 0 ? "All" : `±${n / 2}`}
            </button>
          ))}
        </div>
      </div>

      {loading && <div className="loading">Loading IV surface…</div>}

      {!loading && filteredSurface && (
        <>
          {/* Colour legend */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, fontSize: 10, fontFamily: "Courier New", color: "#555" }}>
            <span>Low IV</span>
            <div style={{
              width: 200, height: 12, borderRadius: 2,
              background: "linear-gradient(to right, rgb(0,100,200), rgb(0,200,100), rgb(200,140,0), rgb(255,0,0))",
            }} />
            <span>High IV</span>
            {spotPrice && <span style={{ marginLeft: "auto" }}>Spot: ${spotPrice.toLocaleString("en-US", { maximumFractionDigits: 0 })}</span>}
          </div>

          {/* Heatmap */}
          <div className="chart-container" style={{ padding: 12 }}>
            <div className="chart-title">
              {optType === "call" ? "Call" : "Put"} IV Surface (%)
            </div>
            <SurfaceHeatmap
              surface={filteredSurface.surface}
              expiries={filteredSurface.expiries}
              strikes={filteredSurface.strikes}
              useCall={optType === "call"}
            />
          </div>

          {/* IV term structure by moneyness */}
          {spotPrice && (
            <div style={{ marginTop: 16 }}>
              <TermIVChart surface={filteredSurface.surface} strikes={filteredSurface.strikes} spotPrice={spotPrice} />
            </div>
          )}

          {/* DVOL history */}
          <div style={{ marginTop: 16 }}>
            <DVOLHistoryChart currency={currency} />
          </div>
        </>
      )}

      {!loading && !surface && !error && (
        <div className="card" style={{ color: "#555" }}>
          No IV surface data available. Deribit options may be unavailable.
        </div>
      )}
    </div>
  );
}
