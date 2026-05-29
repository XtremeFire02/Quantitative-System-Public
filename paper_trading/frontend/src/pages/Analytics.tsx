import React, { useEffect, useState } from "react";
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine, Cell,
} from "recharts";
import { api } from "../api";
import type { DeepAnalytics } from "../api";

const tt = { background: "#0d0d0d", border: "1px solid #2a2a2a", color: "#cccccc" };
const fmt = (v: number | null, d = 2) =>
  v == null ? "—" : v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

// ── Sharpe CI bar ─────────────────────────────────────────────────────────────

function SharpeCI({ sharpe }: { sharpe: DeepAnalytics["sharpe"] }) {
  if (!sharpe || sharpe.value == null) return <span style={{ color: "#444" }}>—</span>;
  const { value, ci_lo, ci_hi, n, significant, min_n_for_significance } = sharpe;

  const barMax = Math.max(Math.abs(ci_lo ?? 0), Math.abs(ci_hi ?? 0), Math.abs(value)) * 1.3 || 3;
  const pct = (v: number) => `${((v / barMax) * 50 + 50).toFixed(1)}%`;

  return (
    <div>
      <div style={{ fontFamily: "Courier New", fontSize: 22, fontWeight: 700,
        color: value > 0 ? "#00cc44" : "#ff3333" }}>
        {value > 0 ? "+" : ""}{value.toFixed(2)}
      </div>
      <div style={{ marginTop: 8, marginBottom: 4, position: "relative", height: 20, background: "#111", border: "1px solid #222" }}>
        {/* Zero line */}
        <div style={{ position: "absolute", left: "50%", top: 0, bottom: 0, width: 1, background: "#333" }} />
        {/* CI band */}
        {ci_lo != null && ci_hi != null && (
          <div style={{
            position: "absolute",
            left: pct(ci_lo), right: `${100 - parseFloat(pct(ci_hi))}%`,
            top: 4, bottom: 4,
            background: significant ? "#00cc4433" : "#ff333333",
            border: `1px solid ${significant ? "#00cc44" : "#ff3333"}`,
          }} />
        )}
        {/* Point estimate */}
        <div style={{
          position: "absolute", left: pct(value),
          top: 0, bottom: 0, width: 2,
          background: significant ? "#00cc44" : "#ff3333",
          transform: "translateX(-50%)",
        }} />
      </div>
      <div style={{ fontSize: 10, color: "#555", fontFamily: "Courier New" }}>
        95% CI: [{fmt(ci_lo, 2)}, {fmt(ci_hi, 2)}]
        {significant
          ? <span style={{ color: "#00cc44", marginLeft: 8 }}>✓ statistically significant</span>
          : <span style={{ color: "#ffcc00", marginLeft: 8 }}>
              ⚠ not yet significant · need {min_n_for_significance ?? "?"} trades
            </span>}
      </div>
      <div style={{ fontSize: 10, color: "#444", fontFamily: "Courier New", marginTop: 2 }}>
        n={n} trades · SE={sharpe.se?.toFixed(4)}
      </div>
    </div>
  );
}

// ── VaR / CVaR panel ──────────────────────────────────────────────────────────

function RiskPanel({ risk, dist }: { risk: DeepAnalytics["risk"]; dist: DeepAnalytics["distribution"] }) {
  const rows = [
    { label: "VaR 95%",  value: risk?.var_95,  color: "#ffcc00" },
    { label: "CVaR 95%", value: risk?.cvar_95, color: "#ff6600" },
    { label: "VaR 99%",  value: risk?.var_99,  color: "#ff6600" },
    { label: "CVaR 99%", value: risk?.cvar_99, color: "#ff3333" },
    { label: "Max loss", value: dist?.max_loss_bp, color: "#ff3333" },
  ];
  const worst = Math.abs(dist?.max_loss_bp ?? 0) || 1;

  return (
    <div style={{ fontFamily: "Courier New", fontSize: 11 }}>
      {rows.map(({ label, value, color }) => (
        <div key={label} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
          <div style={{ width: 80, color: "#555", fontSize: 10 }}>{label}</div>
          <div style={{
            width: `${(Math.abs(value ?? 0) / worst) * 120}px`,
            height: 14, background: `${color}33`, border: `1px solid ${color}66`,
            minWidth: 2,
          }} />
          <span style={{ color, fontWeight: 700 }}>{fmt(value, 1)} bp</span>
        </div>
      ))}
    </div>
  );
}

// ── Kelly panel ───────────────────────────────────────────────────────────────

function KellyPanel({ kelly }: { kelly: DeepAnalytics["kelly"] }) {
  if (!kelly || kelly.full_kelly_pct == null) {
    return <div style={{ color: "#444", fontFamily: "Courier New" }}>Insufficient data</div>;
  }
  const recs = [
    { label: "Full Kelly",    pct: kelly.full_kelly_pct,    note: "theoretical max, very aggressive" },
    { label: "Half Kelly",    pct: kelly.half_kelly_pct,    note: "common aggressive practice" },
    { label: "Quarter Kelly", pct: kelly.quarter_kelly_pct, note: "institutional standard" },
  ];
  return (
    <div style={{ fontFamily: "Courier New" }}>
      <div style={{ fontSize: 10, color: "#555", marginBottom: 8 }}>
        Payoff ratio: {fmt(kelly.b_ratio, 2)} · Edge: {((kelly.edge ?? 0) * 100).toFixed(2)}%
        {!kelly.positive_edge && <span style={{ color: "#ff3333", marginLeft: 8 }}>negative edge — do not trade</span>}
      </div>
      {recs.map(({ label, pct, note }) => (
        <div key={label} style={{ marginBottom: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
            <span style={{ color: "#ccc" }}>{label}</span>
            <span style={{ color: (pct ?? 0) > 0 ? "#00cc44" : "#ff3333", fontWeight: 700 }}>
              {fmt(pct, 1)}% of capital
            </span>
          </div>
          <div style={{ fontSize: 9, color: "#444", marginTop: 1 }}>{note}</div>
        </div>
      ))}
    </div>
  );
}

// ── Rolling IC chart ──────────────────────────────────────────────────────────

function ICChart({ ic }: { ic: DeepAnalytics["signal_ic"] }) {
  if (!ic || !ic.rolling || ic.rolling.length === 0) {
    return (
      <div style={{ color: "#444", fontFamily: "Courier New", padding: "20px 0" }}>
        Insufficient data for rolling IC. Need at least {ic?.ic_window ?? 10} N3 trades with signal z-score.
      </div>
    );
  }

  const data = ic.rolling.map(r => ({ n: r.trade_n, ic: r.ic }));

  return (
    <div>
      <div style={{ display: "flex", gap: 24, marginBottom: 12, fontFamily: "Courier New", fontSize: 11 }}>
        <div>
          Overall IC: <strong style={{ color: (ic.overall_ic ?? 0) > 0.05 ? "#00cc44" : "#ffcc00" }}>
            {fmt(ic.overall_ic, 4)}
          </strong>
        </div>
        <div style={{ color: "#555" }}>n = {ic.n_pairs} signal trades</div>
        {ic.decaying != null && (
          <div style={{ color: ic.decaying ? "#ff3333" : "#00cc44" }}>
            {ic.decaying ? "⚠ IC declining (alpha decay)" : "✓ IC stable"}
          </div>
        )}
      </div>
      <ResponsiveContainer width="100%" height={160}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" />
          <XAxis dataKey="n" tick={{ fill: "#555", fontSize: 9 }} label={{ value: "Trade #", fill: "#555", fontSize: 9 }} />
          <YAxis tick={{ fill: "#555", fontSize: 9 }} domain={[-1, 1]}
            tickFormatter={v => v.toFixed(2)} />
          <Tooltip contentStyle={tt} formatter={(v: any) => [Number(v)?.toFixed(4), "IC"]} />
          <ReferenceLine y={0} stroke="#333" />
          <ReferenceLine y={0.1} stroke="#00cc4444" strokeDasharray="3 3" />
          <ReferenceLine y={-0.1} stroke="#ff333344" strokeDasharray="3 3" />
          <Line type="monotone" dataKey="ic" stroke="#3399ff" dot={true} strokeWidth={2} connectNulls />
        </LineChart>
      </ResponsiveContainer>
      <div style={{ fontSize: 9, color: "#333", fontFamily: "Courier New", marginTop: 4 }}>
        Rolling {ic.ic_window}-trade IC · {'>'}0.10 = useful signal · below 0 = signal inverting
      </div>
    </div>
  );
}

// ── Return distribution histogram ─────────────────────────────────────────────

function ReturnHistogram({ hist, dist }: {
  hist: DeepAnalytics["histogram"];
  dist: DeepAnalytics["distribution"];
}) {
  if (!hist?.length) return null;
  const maxCount = Math.max(...hist.map(b => b.count));
  return (
    <div>
      {dist && (
        <div style={{ display: "flex", gap: 20, marginBottom: 8, fontFamily: "Courier New", fontSize: 10, color: "#555" }}>
          <span>μ = <strong style={{ color: "#ccc" }}>{fmt(dist.mean_bp, 1)} bp</strong></span>
          <span>σ = <strong style={{ color: "#ccc" }}>{fmt(dist.std_bp, 1)} bp</strong></span>
          <span>Skew = <strong style={{ color: (dist.skewness ?? 0) > 0 ? "#00cc44" : "#ff3333" }}>
            {fmt(dist.skewness, 3)}
          </strong></span>
          <span>Kurtosis = <strong style={{ color: (dist.excess_kurtosis ?? 0) > 0 ? "#ffcc00" : "#ccc" }}>
            {fmt(dist.excess_kurtosis, 3)}
          </strong></span>
        </div>
      )}
      <ResponsiveContainer width="100%" height={150}>
        <BarChart data={hist} margin={{ top: 4, right: 10, bottom: 0, left: 30 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" />
          <XAxis dataKey="bin_lo" tick={{ fill: "#555", fontSize: 8 }} tickFormatter={v => `${v}`} />
          <YAxis tick={{ fill: "#555", fontSize: 8 }} />
          <Tooltip contentStyle={tt}
            formatter={(v: any) => [v, "Trades"]}
            labelFormatter={(v: any) => `${v} bp`}
          />
          <ReferenceLine x={0} stroke="#444" />
          <Bar dataKey="count" radius={0}>
            {hist.map((b, i) => (
              <Cell key={i} fill={b.bin_lo >= 0 ? "#00cc44" : "#ff3333"} opacity={0.7} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Equity curve ──────────────────────────────────────────────────────────────

function EquityCurveChart({ curve }: { curve: number[] }) {
  if (!curve.length) return null;
  const data = curve.map((v, i) => ({ trade: i + 1, cumulative: v }));
  return (
    <ResponsiveContainer width="100%" height={160}>
      <LineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" />
        <XAxis dataKey="trade" tick={{ fill: "#555", fontSize: 9 }} label={{ value: "Trade #", fill: "#555", fontSize: 9 }} />
        <YAxis tick={{ fill: "#555", fontSize: 9 }} tickFormatter={v => `${v.toFixed(0)} bp`} domain={["auto", "auto"]} />
        <Tooltip contentStyle={tt}
          formatter={(v: unknown) => [v != null ? `${Number(v).toFixed(1)} bp` : "—", "Cumulative PnL"]}
        />
        <ReferenceLine y={0} stroke="#333" />
        <Line type="monotone" dataKey="cumulative" stroke="#ff6600" dot={false} strokeWidth={2} />
      </LineChart>
    </ResponsiveContainer>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Analytics() {
  const [data, setData] = useState<DeepAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [strategy, setStrategy] = useState<string>("");

  const load = (strat?: string) => {
    setLoading(true);
    setError(null);
    api.deepAnalytics(strat || undefined)
      .then(setData)
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const minSampleWarning = data?.sharpe && !data.sharpe.significant && data.sharpe.min_n_for_significance != null;

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="page-title">Analytics</div>
          <div className="page-subtitle">
            Sharpe CI · VaR/CVaR · Kelly criterion · Rolling IC · Return distribution
          </div>
        </div>
        <div className="btn-row" style={{ marginBottom: 0 }}>
          <button className={`btn ${!strategy ? "btn-primary" : "btn-ghost"}`}
            onClick={() => { setStrategy(""); load(); }}>All</button>
          <button className={`btn ${strategy === "N3_DVOL_LONG" ? "btn-primary" : "btn-ghost"}`}
            onClick={() => { setStrategy("N3_DVOL_LONG"); load("N3_DVOL_LONG"); }}>N3</button>
          <button className={`btn ${strategy === "P3_OIPD_DD" ? "btn-primary" : "btn-ghost"}`}
            onClick={() => { setStrategy("P3_OIPD_DD"); load("P3_OIPD_DD"); }}>P3</button>
          <button className="btn btn-ghost" onClick={() => load(strategy || undefined)}>↻</button>
        </div>
      </div>

      {loading && <div className="loading">Computing analytics…</div>}
      {error && <div className="error-msg">{error}</div>}

      {data && data.n === 0 && (
        <div className="card" style={{ color: "#555" }}>
          No closed trades yet. Analytics will populate once trades complete.
        </div>
      )}

      {minSampleWarning && (
        <div style={{
          background: "#1a1400", border: "1px solid #443300", color: "#ffcc00",
          fontFamily: "Courier New", fontSize: 11, padding: "8px 12px", marginBottom: 16,
        }}>
          ⚠ Statistical power warning: Sharpe CI includes zero with {data!.n} trades.
          Need {data!.sharpe!.min_n_for_significance} trades for 95% significance at current Sharpe.
          Do not size up until edge is confirmed.
        </div>
      )}

      {data && data.n > 0 && (
        <>
          {/* Top stats grid */}
          <div className="cards-grid" style={{ marginBottom: 20 }}>
            <div className="card">
              <div className="card-label">Sharpe (annualised)</div>
              <div style={{ marginTop: 6 }}>
                <SharpeCI sharpe={data.sharpe} />
              </div>
            </div>
            <div className="card">
              <div className="card-label">Sortino</div>
              <div className="card-value" style={{ color: (data.sortino ?? 0) > 2 ? "#00cc44" : "#cccccc" }}>
                {data.sortino != null ? (data.sortino > 0 ? "+" : "") + fmt(data.sortino, 2) : "—"}
              </div>
              <div className="card-sub">Downside deviation-adjusted</div>
            </div>
            <div className="card">
              <div className="card-label">Calmar</div>
              <div className="card-value" style={{ color: (data.calmar ?? 0) > 2 ? "#00cc44" : "#cccccc" }}>
                {data.calmar != null ? (data.calmar > 0 ? "+" : "") + fmt(data.calmar, 2) : "—"}
              </div>
              <div className="card-sub">Ann. return / max DD</div>
            </div>
            <div className="card">
              <div className="card-label">Win Rate</div>
              <div className="card-value">
                {data.win_rate != null ? `${(data.win_rate * 100).toFixed(1)}%` : "—"}
              </div>
              <div className="card-sub">{data.n} closed trades</div>
            </div>
            <div className="card">
              <div className="card-label">Profit Factor</div>
              <div className="card-value" style={{ color: (data.profit_factor ?? 0) > 1.5 ? "#00cc44" : "#cccccc" }}>
                {fmt(data.profit_factor, 2)}
              </div>
              <div className="card-sub">|wins| / |losses|</div>
            </div>
            <div className="card">
              <div className="card-label">Max Drawdown</div>
              <div className="card-value" style={{ color: "#ff3333", fontSize: 18 }}>
                {fmt(data.max_drawdown_bp, 0)} bp
              </div>
              <div className="card-sub">Trade-level peak-to-trough</div>
            </div>
            <div className="card">
              <div className="card-label">Avg Win / Loss</div>
              <div style={{ fontFamily: "Courier New", marginTop: 6, lineHeight: 1.8 }}>
                <div className="positive">+{fmt(data.avg_win_bp, 1)} bp</div>
                <div className="negative">{fmt(data.avg_loss_bp, 1)} bp</div>
              </div>
            </div>
            <div className="card">
              <div className="card-label">Trade Freq.</div>
              <div className="card-value" style={{ fontSize: 18 }}>
                {data.trades_per_year?.toFixed(1)}
              </div>
              <div className="card-sub">estimated trades/year</div>
            </div>
          </div>

          {/* Two-column panels */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 20 }}>
            <div className="card">
              <div className="section-title" style={{ marginBottom: 12 }}>Risk (VaR / CVaR)</div>
              <RiskPanel risk={data.risk} dist={data.distribution} />
            </div>
            <div className="card">
              <div className="section-title" style={{ marginBottom: 12 }}>Kelly Position Sizing</div>
              <KellyPanel kelly={data.kelly} />
            </div>
          </div>

          {/* IC chart */}
          <div className="chart-container" style={{ marginBottom: 16 }}>
            <div className="chart-title">Rolling IC — Signal (N3z) to Return Correlation</div>
            <ICChart ic={data.signal_ic} />
          </div>

          {/* Distribution + equity curve */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 20 }}>
            <div className="chart-container">
              <div className="chart-title">Return Distribution</div>
              <ReturnHistogram hist={data.histogram} dist={data.distribution} />
            </div>
            <div className="chart-container">
              <div className="chart-title">Cumulative PnL Curve (bp, trade-by-trade)</div>
              <EquityCurveChart curve={data.equity_curve} />
            </div>
          </div>

          {/* Yearly breakdown */}
          {data.yearly_breakdown && data.yearly_breakdown.length > 0 && (
            <div className="section">
              <div className="section-title">Year-by-Year Breakdown</div>
              <div className="table-wrapper">
                <table>
                  <thead>
                    <tr><th>Year</th><th>n</th><th>Total PnL (bp)</th><th>Mean (bp)</th>
                      <th>Sharpe</th><th>Win Rate</th><th>Avg Win</th><th>Avg Loss</th></tr>
                  </thead>
                  <tbody>
                    {data.yearly_breakdown.map(y => (
                      <tr key={y.year}>
                        <td>{y.year}</td>
                        <td>{y.n}</td>
                        <td><span className={y.total_pnl_bp > 0 ? "positive" : "negative"}>
                          {y.total_pnl_bp > 0 ? "+" : ""}{fmt(y.total_pnl_bp, 0)} bp
                        </span></td>
                        <td style={{ fontFamily: "monospace" }}>{fmt(y.mean_pnl_bp, 1)}</td>
                        <td style={{ color: (y.sharpe ?? 0) > 1 ? "#00cc44" : "#ccc" }}>
                          {y.sharpe != null ? (y.sharpe > 0 ? "+" : "") + fmt(y.sharpe, 2) : "—"}
                        </td>
                        <td>{y.win_rate != null ? `${(y.win_rate * 100).toFixed(0)}%` : "—"}</td>
                        <td className="positive">{y.avg_win_bp != null ? `+${fmt(y.avg_win_bp, 1)}` : "—"}</td>
                        <td className="negative">{y.avg_loss_bp != null ? `${fmt(y.avg_loss_bp, 1)}` : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
