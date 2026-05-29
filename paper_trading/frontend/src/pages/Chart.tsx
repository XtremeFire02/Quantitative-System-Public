import React, { useEffect, useRef, useState, useCallback } from "react";
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";
import { api } from "../api";
import type { OHLCVBar, OrderBook } from "../api";

const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "AVAXUSDT"];
const INTERVALS = [
  { label: "1m",  v: "1m"  },
  { label: "5m",  v: "5m"  },
  { label: "15m", v: "15m" },
  { label: "1h",  v: "1h"  },
  { label: "4h",  v: "4h"  },
  { label: "1d",  v: "1d"  },
  { label: "1w",  v: "1w"  },
];

const tt = { background: "#0d0d0d", border: "1px solid #2a2a2a", color: "#cccccc" };
const fmt = (v: number, d = 2) => v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

// ── SVG Candlestick chart ────────────────────────────────────────────────────

interface CandleProps {
  bars: OHLCVBar[];
  width: number;
  height: number;
  showBB: boolean;
  showEMA: boolean;
}

function CandleChart({ bars, width, height, showBB, showEMA }: CandleProps) {
  const [tooltip, setTooltip] = useState<{ i: number; x: number; y: number } | null>(null);

  const PAD_L = 10, PAD_R = 60, PAD_T = 10, PAD_B = 30;
  const chartW = width - PAD_L - PAD_R;
  const chartH = height - PAD_T - PAD_B;

  if (!bars.length || chartW <= 0) return null;

  const visibleBars = bars.slice(-Math.min(bars.length, Math.floor(chartW / 6)));
  const n = visibleBars.length;
  const barW = Math.max(1, Math.floor(chartW / n) - 1);

  const highs = visibleBars.map(b => b.h);
  const lows = visibleBars.map(b => b.l);
  const bbUppers = visibleBars.map(b => b.bb_upper).filter(v => v != null) as number[];
  const bbLowers = visibleBars.map(b => b.bb_lower).filter(v => v != null) as number[];
  const ema20s = visibleBars.map(b => b.ema20).filter(v => v != null) as number[];
  const ema50s = visibleBars.map(b => b.ema50).filter(v => v != null) as number[];

  const allPrices = [
    ...highs, ...lows,
    ...(showBB ? [...bbUppers, ...bbLowers] : []),
    ...(showEMA ? [...ema20s, ...ema50s] : []),
  ];
  const minP = allPrices.length > 0 ? Math.min(...allPrices) : 0;
  const maxP = allPrices.length > 0 ? Math.max(...allPrices) : 1;
  const priceRange = maxP - minP || 1;
  const py = (p: number) => PAD_T + ((maxP - p) / priceRange) * chartH;
  const bx = (i: number) => PAD_L + (i + 0.5) * (chartW / n);

  // Price Y axis ticks
  const nTicks = 5;
  const yTicks = Array.from({ length: nTicks }, (_, i) => minP + (priceRange * i) / (nTicks - 1));

  // Build SVG path for a series (skipping nulls)
  const linePath = (series: (number | null)[]) => {
    let d = "";
    series.forEach((v, i) => {
      if (v == null) return;
      const x = bx(i);
      const y = py(v);
      d += d ? ` L ${x} ${y}` : `M ${x} ${y}`;
    });
    return d;
  };

  const ttBar = tooltip ? visibleBars[tooltip.i] : null;

  return (
    <svg
      width={width}
      height={height}
      style={{ display: "block", cursor: "crosshair" }}
      onMouseMove={e => {
        const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
        const mx = e.clientX - rect.left - PAD_L;
        const i = Math.max(0, Math.min(n - 1, Math.floor(mx / (chartW / n))));
        setTooltip({ i, x: e.clientX - rect.left, y: e.clientY - rect.top });
      }}
      onMouseLeave={() => setTooltip(null)}
    >
      {/* Grid lines */}
      {yTicks.map((v, i) => (
        <g key={i}>
          <line x1={PAD_L} y1={py(v)} x2={PAD_L + chartW} y2={py(v)} stroke="#1a1a1a" />
          <text x={PAD_L + chartW + 4} y={py(v) + 4} fill="#555" fontSize={9} textAnchor="start">
            {v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(1)}
          </text>
        </g>
      ))}

      {/* Bollinger Bands */}
      {showBB && (
        <>
          <path d={linePath(visibleBars.map(b => b.bb_upper))} fill="none" stroke="#3399ff" strokeWidth={1} opacity={0.5} />
          <path d={linePath(visibleBars.map(b => b.bb_mid))}   fill="none" stroke="#3399ff" strokeWidth={0.5} opacity={0.4} strokeDasharray="3,3" />
          <path d={linePath(visibleBars.map(b => b.bb_lower))} fill="none" stroke="#3399ff" strokeWidth={1} opacity={0.5} />
        </>
      )}

      {/* EMA lines */}
      {showEMA && (
        <>
          <path d={linePath(visibleBars.map(b => b.ema20))} fill="none" stroke="#ffcc00" strokeWidth={1} opacity={0.8} />
          <path d={linePath(visibleBars.map(b => b.ema50))} fill="none" stroke="#ff6600" strokeWidth={1} opacity={0.8} />
        </>
      )}

      {/* Candles */}
      {visibleBars.map((bar, i) => {
        const x = bx(i);
        const isGreen = bar.c >= bar.o;
        const color = isGreen ? "#00cc44" : "#ff3333";
        const bodyTop = py(Math.max(bar.o, bar.c));
        const bodyBot = py(Math.min(bar.o, bar.c));
        const bodyH = Math.max(1, bodyBot - bodyTop);
        return (
          <g key={bar.t}>
            <line x1={x} y1={py(bar.h)} x2={x} y2={py(bar.l)} stroke={color} strokeWidth={1} />
            <rect
              x={x - barW / 2} y={bodyTop} width={barW} height={bodyH}
              fill={isGreen ? color : "transparent"} stroke={color} strokeWidth={1}
            />
          </g>
        );
      })}

      {/* Crosshair + tooltip */}
      {tooltip && ttBar && (
        <>
          <line x1={tooltip.x} y1={PAD_T} x2={tooltip.x} y2={PAD_T + chartH} stroke="#444" strokeWidth={0.5} strokeDasharray="3,3" />
          <foreignObject x={Math.min(tooltip.x + 8, width - 180)} y={PAD_T + 4} width={170} height={130}>
            <div style={{
              background: "#0d0d0d", border: "1px solid #2a2a2a", padding: "6px 8px",
              fontFamily: "Courier New", fontSize: 10, color: "#ccc", lineHeight: 1.6,
            }}>
              <div style={{ color: "#555" }}>{new Date(ttBar.t).toLocaleString()}</div>
              <div>O: <strong>${fmt(ttBar.o)}</strong></div>
              <div>H: <strong style={{ color: "#00cc44" }}>${fmt(ttBar.h)}</strong></div>
              <div>L: <strong style={{ color: "#ff3333" }}>${fmt(ttBar.l)}</strong></div>
              <div>C: <strong style={{ color: ttBar.c >= ttBar.o ? "#00cc44" : "#ff3333" }}>${fmt(ttBar.c)}</strong></div>
              <div>Vol: <strong>{(ttBar.v / 1000).toFixed(1)}K</strong></div>
              {ttBar.rsi != null && <div>RSI: <strong>{ttBar.rsi.toFixed(1)}</strong></div>}
            </div>
          </foreignObject>
        </>
      )}

      {/* X axis time labels (every ~10% of bars) */}
      {visibleBars
        .filter((_, i) => i % Math.max(1, Math.floor(n / 8)) === 0)
        .map((bar, _, arr) => {
          const i = visibleBars.indexOf(bar);
          return (
            <text key={bar.t} x={bx(i)} y={PAD_T + chartH + 16} fill="#555" fontSize={9} textAnchor="middle">
              {new Date(bar.t).toLocaleDateString()}
            </text>
          );
        })}
    </svg>
  );
}

// ── Volume bars ──────────────────────────────────────────────────────────────

function VolumeChart({ bars }: { bars: OHLCVBar[] }) {
  const data = bars.slice(-200).map(b => ({
    t: b.t,
    v: b.v,
    up: b.c >= b.o ? b.v : 0,
    dn: b.c < b.o ? b.v : 0,
  }));
  return (
    <ResponsiveContainer width="100%" height={60}>
      <ComposedChart data={data} margin={{ top: 0, right: 60, bottom: 0, left: 10 }}>
        <Bar dataKey="up" fill="#00cc44" opacity={0.5} />
        <Bar dataKey="dn" fill="#ff3333" opacity={0.5} />
        <YAxis tick={{ fill: "#333", fontSize: 8 }} tickFormatter={v => `${(v / 1000).toFixed(0)}K`} width={40} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

// ── RSI panel ────────────────────────────────────────────────────────────────

function RSIChart({ bars }: { bars: OHLCVBar[] }) {
  const data = bars.slice(-200).map(b => ({ t: b.t, rsi: b.rsi }));
  return (
    <ResponsiveContainer width="100%" height={80}>
      <ComposedChart data={data} margin={{ top: 4, right: 60, bottom: 0, left: 10 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#111" />
        <YAxis domain={[0, 100]} tick={{ fill: "#555", fontSize: 8 }} width={30} />
        <Tooltip contentStyle={tt} formatter={(v: any) => [Number(v).toFixed(1), "RSI"]} />
        <ReferenceLine y={70} stroke="#ff333344" />
        <ReferenceLine y={30} stroke="#00cc4444" />
        <Line type="monotone" dataKey="rsi" stroke="#ffcc00" dot={false} strokeWidth={1.5} connectNulls={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

// ── MACD panel ───────────────────────────────────────────────────────────────

function MACDChart({ bars }: { bars: OHLCVBar[] }) {
  const data = bars.slice(-200).map(b => ({
    t: b.t,
    macd: b.macd,
    signal: b.macd_signal,
    hist: b.macd_hist,
  }));
  return (
    <ResponsiveContainer width="100%" height={80}>
      <ComposedChart data={data} margin={{ top: 4, right: 60, bottom: 0, left: 10 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#111" />
        <YAxis tick={{ fill: "#555", fontSize: 8 }} width={40} domain={["auto", "auto"]} />
        <Tooltip contentStyle={tt}
          formatter={(v: any, name: any) => [Number(v)?.toFixed(4), name]}
        />
        <ReferenceLine y={0} stroke="#333" />
        <Bar dataKey="hist" fill="#555" />
        <Line type="monotone" dataKey="macd"   stroke="#3399ff" dot={false} strokeWidth={1.5} connectNulls={false} />
        <Line type="monotone" dataKey="signal" stroke="#ff6600" dot={false} strokeWidth={1}   connectNulls={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

// ── Order book panel ─────────────────────────────────────────────────────────

function OrderBookPanel({ book }: { book: OrderBook }) {
  const maxQty = Math.max(
    1,
    ...book.bids.slice(0, 15).map(b => b[1]),
    ...book.asks.slice(0, 15).map(a => a[1]),
  );

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, fontFamily: "Courier New", fontSize: 11 }}>
      <div>
        <div style={{ color: "#555", fontSize: 9, marginBottom: 4, fontWeight: 700 }}>BIDS</div>
        {book.bids.slice(0, 15).map(([price, qty], i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 1 }}>
            <div style={{
              width: `${(qty / maxQty) * 60}%`, height: 14,
              background: "#00cc4422", border: "1px solid #00cc4444",
              minWidth: 2,
            }} />
            <span style={{ color: "#00cc44" }}>${price.toFixed(1)}</span>
            <span style={{ color: "#555" }}>{qty.toFixed(3)}</span>
          </div>
        ))}
      </div>
      <div>
        <div style={{ color: "#555", fontSize: 9, marginBottom: 4, fontWeight: 700 }}>ASKS</div>
        {book.asks.slice(0, 15).map(([price, qty], i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 1 }}>
            <div style={{
              width: `${(qty / maxQty) * 60}%`, height: 14,
              background: "#ff333322", border: "1px solid #ff333344",
              minWidth: 2,
            }} />
            <span style={{ color: "#ff3333" }}>${price.toFixed(1)}</span>
            <span style={{ color: "#555" }}>{qty.toFixed(3)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function Chart() {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [interval, setInterval] = useState("1h");
  const [bars, setBars] = useState<OHLCVBar[]>([]);
  const [book, setBook] = useState<OrderBook | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showBB, setShowBB] = useState(true);
  const [showEMA, setShowEMA] = useState(true);
  const [showBook, setShowBook] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerW, setContainerW] = useState(900);

  useEffect(() => {
    const obs = new ResizeObserver(entries => {
      setContainerW(entries[0].contentRect.width);
    });
    if (containerRef.current) obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, []);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.allSettled([
      api.chartOHLCV(symbol, interval, 500),
      api.chartOrderbook(symbol, 20),
    ]).then(([chartRes, bookRes]) => {
      if (chartRes.status === "fulfilled") setBars(chartRes.value.bars);
      else setError((chartRes.reason as Error).message);
      if (bookRes.status === "fulfilled") setBook(bookRes.value);
    }).finally(() => setLoading(false));
  }, [symbol, interval]);

  useEffect(() => { load(); }, [load]);

  const last = bars.at(-1);
  const prev = bars.at(-2);
  const change = last && prev ? last.c - prev.c : null;
  const changePct = change && prev ? (change / prev.c) * 100 : null;

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="page-title">Chart</div>
          <div className="page-subtitle">
            {last ? (
              <>
                <span style={{ fontFamily: "Courier New", color: "#e0e0e0" }}>${fmt(last.c)}</span>
                {changePct != null && (
                  <span style={{ marginLeft: 8, color: changePct >= 0 ? "#00cc44" : "#ff3333" }}>
                    {changePct >= 0 ? "+" : ""}{changePct.toFixed(2)}%
                  </span>
                )}
              </>
            ) : "Candlestick · Technical Indicators · Order Book"}
          </div>
        </div>
        <button className="btn btn-ghost" onClick={load}>↻ Refresh</button>
      </div>

      {/* Controls */}
      <div className="btn-row">
        <select
          value={symbol}
          onChange={e => setSymbol(e.target.value)}
          style={{
            background: "#111", color: "#ccc", border: "1px solid #2a2a2a",
            padding: "3px 8px", fontFamily: "Courier New", fontSize: 11, height: 24,
          }}
        >
          {SYMBOLS.map(s => <option key={s} value={s}>{s}</option>)}
        </select>

        {INTERVALS.map(({ label, v }) => (
          <button
            key={v}
            className={`btn ${interval === v ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setInterval(v)}
          >
            {label}
          </button>
        ))}

        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          <button className={`btn ${showBB ? "btn-secondary" : "btn-ghost"}`} onClick={() => setShowBB(s => !s)}>BB</button>
          <button className={`btn ${showEMA ? "btn-secondary" : "btn-ghost"}`} onClick={() => setShowEMA(s => !s)}>EMA</button>
          <button className={`btn ${showBook ? "btn-secondary" : "btn-ghost"}`} onClick={() => setShowBook(s => !s)}>Book</button>
        </div>
      </div>

      {loading && <div className="loading">Loading…</div>}
      {error && <div className="error-msg">{error}</div>}

      {!loading && bars.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: showBook ? "1fr 260px" : "1fr", gap: 8 }}>
          <div>
            {/* Main candle chart */}
            <div ref={containerRef} className="chart-container" style={{ padding: 0, overflow: "hidden" }}>
              <CandleChart bars={bars} width={showBook ? containerW - 280 : containerW} height={320} showBB={showBB} showEMA={showEMA} />
            </div>

            {/* Volume */}
            <div className="chart-container" style={{ marginTop: 4, padding: "4px 0" }}>
              <div className="chart-title" style={{ paddingLeft: 10 }}>Volume</div>
              <VolumeChart bars={bars} />
            </div>

            {/* RSI */}
            <div className="chart-container" style={{ marginTop: 4, padding: "4px 0" }}>
              <div className="chart-title" style={{ paddingLeft: 10 }}>RSI (14)</div>
              <RSIChart bars={bars} />
            </div>

            {/* MACD */}
            <div className="chart-container" style={{ marginTop: 4, padding: "4px 0" }}>
              <div className="chart-title" style={{ paddingLeft: 10 }}>MACD (12/26/9)</div>
              <MACDChart bars={bars} />
            </div>

            {/* Legend */}
            {(showBB || showEMA) && (
              <div style={{ display: "flex", gap: 16, padding: "6px 0", fontSize: 10, fontFamily: "Courier New", color: "#555" }}>
                {showEMA && (
                  <>
                    <span><span style={{ color: "#ffcc00" }}>── </span>EMA-20</span>
                    <span><span style={{ color: "#ff6600" }}>── </span>EMA-50</span>
                  </>
                )}
                {showBB && <span><span style={{ color: "#3399ff" }}>── </span>Bollinger (20, 2σ)</span>}
              </div>
            )}
          </div>

          {/* Order book */}
          {showBook && book && (
            <div className="card" style={{ padding: 12 }}>
              <div className="section-title" style={{ marginBottom: 8 }}>
                Order Book
                {book.spread_bp != null && (
                  <span style={{ fontWeight: 400, marginLeft: 8, color: "#555" }}>
                    {book.spread_bp.toFixed(2)} bp spread
                  </span>
                )}
              </div>
              {book.mid_price && (
                <div style={{ fontFamily: "Courier New", fontSize: 12, color: "#ffcc00", marginBottom: 8 }}>
                  Mid: ${fmt(book.mid_price)}
                </div>
              )}
              <OrderBookPanel book={book} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
