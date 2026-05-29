import React, { useState, useEffect, useCallback } from "react";
import { api } from "../api";
import type { AvailableConfig, ActiveBotConfig } from "../api";
import { toast } from "./Toast";

// ── Gear icon (inline SVG, no external dep) ──────────────────────────────────
function GearIcon({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06
               a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09
               A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83
               l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09
               A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83
               l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09
               a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83
               l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09
               a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

// ── Colours — Bloomberg dark theme ───────────────────────────────────────────
const C = {
  bg:           "#000000",
  surface:      "#111111",
  border:       "#2a2a2a",
  text:         "#e0e0e0",
  muted:        "#666666",
  accent:       "#ff6600",
  accentHover:  "#cc5200",
  danger:       "#ff3333",
  dangerBg:     "#1a0000",
  green:        "#00cc44",
  tag:          "#1a0a00",
  orange:       "#ff6600",
  orangeBg:     "#1a0a00",
};

// ── Status badge ──────────────────────────────────────────────────────────────
const STATUS_BADGE: Record<string, { label: string; color: string; bg: string }> = {
  validated:      { label: "validated",    color: "#00cc44", bg: "#001a0d" },
  experimental:   { label: "experimental", color: "#ff6600", bg: "#1a0a00" },
  shadow:         { label: "shadow",       color: "#ffcc00", bg: "#1a1400" },
  execution_test: { label: "exec test",    color: "#3399ff", bg: "#001433" },
  coming_soon:    { label: "coming soon",  color: "#666666", bg: "#1a1a1a" },
};

function StatusBadge({ status }: { status: string }) {
  const s = STATUS_BADGE[status] ?? STATUS_BADGE.experimental;
  return (
    <span style={{
      fontSize: 10, padding: "1px 6px",
      background: s.bg, color: s.color, fontWeight: 600,
      border: `1px solid ${s.color}44`,
      letterSpacing: "0.03em",
    }}>
      {s.label}
    </span>
  );
}

// ── Tag badge ─────────────────────────────────────────────────────────────────
function Tag({ label }: { label: string }) {
  return (
    <span style={{
      fontSize: 10, padding: "1px 6px",
      background: C.tag, color: C.accent, marginRight: 4,
      border: `1px solid ${C.accent}44`,
    }}>
      {label}
    </span>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export default function BotConfigPanel() {
  const [open, setOpen] = useState(false);
  const [available, setAvailable] = useState<AvailableConfig | null>(null);
  const [active, setActive] = useState<ActiveBotConfig[]>([]);
  const [selectedMarket, setSelectedMarket] = useState<string | null>(null);
  const [selectedStrategy, setSelectedStrategy] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    Promise.all([api.configAvailable(), api.configActive()])
      .then(([avail, act]) => {
        setAvailable(avail);
        setActive(act);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (open) refresh();
  }, [open, refresh]);

  const handleAdd = () => {
    if (!selectedMarket || !selectedStrategy) return;
    setLoading(true);
    setError(null);
    api.configAdd(selectedMarket, selectedStrategy)
      .then(() => {
        toast.success(`Bot added: ${selectedStrategy} on ${selectedMarket}`);
        setSelectedMarket(null);
        setSelectedStrategy(null);
        refresh();
      })
      .catch(e => {
        const msg = e?.message ?? "Failed to add bot";
        setError(msg);
        toast.error(msg);
      })
      .finally(() => setLoading(false));
  };

  const handleRemove = (market: string, strategy: string) => {
    api.configRemove(market, strategy)
      .then(() => {
        toast.info(`Bot removed: ${strategy} on ${market}`);
        refresh();
      })
      .catch(e => {
        const msg = e?.message ?? "Failed to remove bot";
        setError(msg);
        toast.error(msg);
      });
  };

  const handleMarketSelect = (m: string) => {
    setSelectedMarket(prev => prev === m ? null : m);
    setSelectedStrategy(null);
  };

  const compatibleStrategies = available && selectedMarket
    ? Object.entries(available.strategies).filter(([, s]) =>
        s.compatible_markets.includes(selectedMarket))
    : [];

  const isAlreadyActive = (market: string, strategy: string) =>
    active.some(a => a.market === market && a.strategy_name === strategy);

  return (
    <>
      {/* Trigger button */}
      <button
        onClick={() => setOpen(o => !o)}
        title="Configure markets & bots"
        style={{
          background: open ? C.accent : "transparent",
          border: `1px solid ${open ? C.accent : "#444444"}`,
          color: open ? "white" : "#999999",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "5px 7px",
          transition: "all 0.15s",
        }}
      >
        <GearIcon size={17} />
      </button>

      {/* Backdrop */}
      {open && (
        <div
          onClick={() => setOpen(false)}
          style={{
            position: "fixed", inset: 0,
            background: "rgba(0,0,0,0.6)",
            zIndex: 999,
          }}
        />
      )}

      {/* Slide-out panel */}
      <div style={{
        position: "fixed",
        top: 0,
        right: open ? 0 : -380,
        width: 360,
        height: "100vh",
        background: C.bg,
        borderLeft: `2px solid ${C.border}`,
        borderTop: `3px solid ${C.accent}`,
        zIndex: 1000,
        display: "flex",
        flexDirection: "column",
        transition: "right 0.25s cubic-bezier(0.4,0,0.2,1)",
        boxShadow: open ? "-4px 0 24px rgba(255,102,0,0.08)" : "none",
      }}>
        {/* Header */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "16px 20px",
          borderBottom: `1px solid ${C.border}`,
          flexShrink: 0,
        }}>
          <div>
            <div style={{ color: C.text, fontWeight: 700, fontSize: 13, fontFamily: "Arial", textTransform: "uppercase", letterSpacing: 1 }}>
              Markets &amp; Bots
            </div>
            <div style={{ color: C.muted, fontSize: 11, marginTop: 2, fontFamily: "Courier New" }}>
              {active.length} active bot{active.length !== 1 ? "s" : ""}
            </div>
          </div>
          <button onClick={() => setOpen(false)} style={{
            background: "transparent", border: "none", color: C.muted,
            cursor: "pointer", fontSize: 18, lineHeight: 1, padding: "2px 6px",
          }}>✕</button>
        </div>

        {/* Scrollable body */}
        <div style={{ flex: 1, overflowY: "auto", padding: "16px 20px" }}>

          {/* ── Active bots ── */}
          <div style={{ marginBottom: 24 }}>
            <div style={{
              color: C.muted, fontSize: 10, fontWeight: 700,
              letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 10,
              fontFamily: "Arial",
            }}>
              Active Bots
            </div>

            {active.length === 0 ? (
              <div style={{
                color: C.muted, fontSize: 13, textAlign: "center",
                padding: "20px 0", border: `1px dashed ${C.border}`,
              }}>
                No active bots. Add one below.
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {active.map(bot => {
                  const mkt = available?.markets[bot.market];
                  const strat = available?.strategies[bot.strategy_name];
                  return (
                    <div key={bot.id} style={{
                      background: C.surface,
                      border: `1px solid ${C.border}`,
                      padding: "10px 12px",
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                    }}>
                      <span style={{ fontSize: 18, width: 28, textAlign: "center", flexShrink: 0 }}>
                        {mkt?.icon ?? "?"}
                      </span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ color: C.text, fontSize: 13, fontWeight: 600, fontFamily: "Courier New", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                          {strat?.display_name ?? bot.strategy_name}
                        </div>
                        <div style={{ color: C.muted, fontSize: 11, marginTop: 1 }}>
                          {bot.market}
                        </div>
                      </div>
                      <button
                        onClick={() => handleRemove(bot.market, bot.strategy_name)}
                        title="Remove bot"
                        style={{
                          background: "transparent", border: "none",
                          color: C.muted, cursor: "pointer",
                          fontSize: 16, padding: "2px 4px", flexShrink: 0,
                        }}
                        onMouseEnter={e => (e.currentTarget.style.color = C.danger)}
                        onMouseLeave={e => (e.currentTarget.style.color = C.muted)}
                      >
                        ×
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Divider */}
          <div style={{ borderTop: `1px solid ${C.border}`, marginBottom: 20 }} />

          {/* ── Add new bot ── */}
          <div>
            <div style={{
              color: C.muted, fontSize: 10, fontWeight: 700,
              letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 12,
              fontFamily: "Arial",
            }}>
              Add New Bot
            </div>

            {/* Market list */}
            <div style={{ marginBottom: 16 }}>
              <div style={{ color: C.muted, fontSize: 12, marginBottom: 8 }}>
                1. Select market
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {available ? Object.entries(available.markets).map(([key, mkt]) => (
                  <button
                    key={key}
                    onClick={() => handleMarketSelect(key)}
                    style={{
                      background: selectedMarket === key ? C.accent : C.surface,
                      border: `1px solid ${selectedMarket === key ? C.accent : C.border}`,
                      color: selectedMarket === key ? "white" : C.text,
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      padding: "9px 12px",
                      textAlign: "left",
                      transition: "all 0.12s",
                    }}
                  >
                    <span style={{ fontSize: 18, width: 28, textAlign: "center" }}>
                      {mkt.icon}
                    </span>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600, fontFamily: "Courier New" }}>{mkt.display_name}</div>
                      <div style={{ fontSize: 11, opacity: 0.65, marginTop: 1 }}>{mkt.exchange}</div>
                    </div>
                  </button>
                )) : (
                  <div style={{ color: C.muted, fontSize: 13 }}>Loading…</div>
                )}
              </div>
            </div>

            {/* Strategy list — only shown after market is selected */}
            {selectedMarket && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ color: C.muted, fontSize: 12, marginBottom: 8 }}>
                  2. Select strategy
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {compatibleStrategies.length === 0 ? (
                    <div style={{ color: C.muted, fontSize: 13 }}>
                      No strategies available for this market.
                    </div>
                  ) : compatibleStrategies.map(([key, strat]) => {
                    const alreadyActive = isAlreadyActive(selectedMarket, key);
                    const isComingSoon = strat.status === "coming_soon";
                    const disabled = alreadyActive || isComingSoon;
                    const selected = selectedStrategy === key;
                    return (
                      <button
                        key={key}
                        onClick={() => !disabled && setSelectedStrategy(prev => prev === key ? null : key)}
                        disabled={disabled}
                        style={{
                          background: selected ? C.orangeBg : C.surface,
                          border: `1px solid ${selected ? C.accent : C.border}`,
                          color: disabled ? C.muted : C.text,
                          cursor: disabled ? "not-allowed" : "pointer",
                          padding: "10px 12px",
                          textAlign: "left",
                          opacity: disabled ? 0.5 : 1,
                          transition: "all 0.12s",
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 }}>
                          <div style={{ fontSize: 13, fontWeight: 600, fontFamily: "Courier New" }}>{strat.display_name}</div>
                          <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                            <StatusBadge status={strat.status} />
                            {alreadyActive && (
                              <span style={{
                                fontSize: 10, padding: "1px 6px",
                                background: "#001a0d", color: C.green, fontWeight: 600,
                                border: "1px solid #004422",
                              }}>active</span>
                            )}
                          </div>
                        </div>
                        <div style={{ color: C.muted, fontSize: 11, marginTop: 4, lineHeight: 1.4 }}>
                          {strat.description}
                        </div>
                        <div style={{ marginTop: 6 }}>
                          {strat.tags.map(t => <Tag key={t} label={t} />)}
                          <Tag label={`${strat.hold_hours}h hold`} />
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Error */}
            {error && (
              <div style={{
                color: C.danger, fontSize: 12, background: C.dangerBg,
                border: `1px solid ${C.danger}`,
                padding: "8px 12px", marginBottom: 12,
              }}>
                {error}
              </div>
            )}

            {/* Add button */}
            {selectedMarket && selectedStrategy && (
              <button
                onClick={handleAdd}
                disabled={loading}
                className={`btn ${loading ? "btn-ghost" : "btn-primary"}`}
                style={{ width: "100%", justifyContent: "center" }}
              >
                {loading ? "Adding…" : "+ Add Bot"}
              </button>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
