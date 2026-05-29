import React, { useState, useEffect, useCallback } from "react";
import { BrowserRouter, Routes, Route, NavLink, useNavigate } from "react-router-dom";
import { api } from "./api";
import type { ActiveBotConfig, SystemHealth as HealthData } from "./api";
import Dashboard from "./pages/Dashboard";
import Signals from "./pages/Signals";
import Trades from "./pages/Trades";
import TradeDetail from "./pages/TradeDetail";
import Performance from "./pages/Performance";
import SystemHealth from "./pages/SystemHealth";
import Replay from "./pages/Replay";
import RiskDashboard from "./pages/RiskDashboard";
import DataQuality from "./pages/DataQuality";
import StrategyPipeline from "./pages/StrategyPipeline";
import Alerts from "./pages/Alerts";
import ForwardLog from "./pages/ForwardLog";
import ForwardValidation from "./pages/ForwardValidation";
import Portfolio from "./pages/Portfolio";
import Experiments from "./pages/Experiments";
import BotConfigPanel from "./components/BotConfigPanel";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ToastContainer } from "./components/Toast";
import Chart from "./pages/Chart";
import MarketMonitor from "./pages/MarketMonitor";
import Options from "./pages/Options";
import VolSurface from "./pages/VolSurface";
import News from "./pages/News";
import Analytics from "./pages/Analytics";
import "./App.css";

// ── Nav items with F-key bindings ────────────────────────────────────────────

const NAV_ITEMS = [
  { to: "/",                   label: "DASH",     key: "F1",  end: true  },
  { to: "/chart",              label: "CHART",    key: "F2",  end: false },
  { to: "/monitor",            label: "MONI",     key: "F3",  end: false },
  { to: "/options",            label: "OMON",     key: "F4",  end: false },
  { to: "/vol-surface",        label: "OVDV",     key: "F5",  end: false },
  { to: "/news",               label: "NEWS",     key: "F6",  end: false },
  { to: "/analytics",          label: "ANLYT",    key: "F7",  end: false },
  { to: "/signals",            label: "SIGS",     key: "F8",  end: false },
  { to: "/trades",             label: "TRADES",   key: "",    end: false },
  { to: "/performance",        label: "PERF",     key: "F9",  end: false },
  { to: "/forward-log",        label: "FWD",      key: "F10", end: false },
  { to: "/portfolio",          label: "PORTF",    key: "F11", end: false },
  { to: "/risk",               label: "RISK",     key: "F12", end: false },
  { to: "/pipeline",           label: "PIPE",     key: "",    end: false },
  { to: "/alerts",             label: "ALERTS",   key: "",    end: false },
  { to: "/replay",             label: "REPLAY",   key: "",    end: false },
  { to: "/forward-validation", label: "FWDVAL",   key: "",    end: false },
  { to: "/data-quality",       label: "DATA",     key: "",    end: false },
  { to: "/experiments",        label: "EXP",      key: "",    end: false },
  { to: "/health",             label: "SYS",      key: "",    end: false },
] as const;

// Map F1-F12 to routes for keyboard navigation
const FKEY_MAP: Record<string, string> = {};
NAV_ITEMS.forEach(({ key, to }) => { if (key) FKEY_MAP[key] = to; });

// ── Status bar ────────────────────────────────────────────────────────────────

function StatusBar({ online }: { online: boolean | null }) {
  const [time, setTime] = useState(new Date());
  const [bots, setBots] = useState<ActiveBotConfig[]>([]);
  const [health, setHealth] = useState<HealthData | null>(null);

  useEffect(() => {
    const tick = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(tick);
  }, []);

  useEffect(() => {
    const load = () => {
      api.configActive().then(setBots).catch(() => {});
      api.systemHealth().then(setHealth).catch(() => {});
    };
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, []);

  const utc = time.toISOString().replace("T", " ").slice(0, 19);
  const stratLabel = bots.length > 0
    ? Array.from(new Set(bots.map(b => b.strategy_name))).join(" · ")
    : "—";
  const mktLabel = bots.length > 0
    ? Array.from(new Set(bots.map(b => b.market))).join(" · ")
    : "—";
  const sysOk = health ? health.status === "healthy" : null;

  return (
    <div className="status-bar">
      <span>
        <span className="status-label">CONN</span>
        {online === null
          ? <span className="status-value">—</span>
          : online
            ? <span className="status-ok">●</span>
            : <span className="status-warn">● OFFLINE</span>}
      </span>
      <span><span className="status-label">ENV</span><span className="status-value">PAPER</span></span>
      <span><span className="status-label">STRAT</span><span className="status-value">{stratLabel}</span></span>
      <span><span className="status-label">MKT</span><span className="status-value">{mktLabel}</span></span>
      <span>
        <span className="status-label">SYS</span>
        {sysOk === null
          ? <span className="status-value">—</span>
          : sysOk
            ? <span className="status-ok">LIVE</span>
            : <span className="status-warn">DEGRADED</span>}
      </span>
      <span className="status-time">{utc} UTC</span>
    </div>
  );
}

// ── Keyboard navigation hook ──────────────────────────────────────────────────

function useKeyboardNav() {
  const navigate = useNavigate();

  const handler = useCallback((e: KeyboardEvent) => {
    // Ignore if focus is on an input, textarea, select, or contenteditable
    const tag = (e.target as HTMLElement)?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    if ((e.target as HTMLElement)?.isContentEditable) return;

    const route = FKEY_MAP[e.key];
    if (route !== undefined) {
      e.preventDefault();
      navigate(route);
    }
  }, [navigate]);

  useEffect(() => {
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handler]);
}

// ── Nav ───────────────────────────────────────────────────────────────────────

function Nav() {
  useKeyboardNav();
  const cls = ({ isActive }: { isActive: boolean }) =>
    `nav-link${isActive ? " active" : ""}`;
  return (
    <nav className="nav">
      <div className="nav-brand">
        <span className="nav-logo">N3·P3</span>
        <span className="nav-title">QUANT PAPER TRADING</span>
      </div>
      <div className="nav-links">
        {NAV_ITEMS.map(({ to, label, key, end }) => (
          <NavLink key={to} to={to} className={cls} end={end} title={key ? `${key} — ${label}` : label}>
            {key && <span className="nav-fkey">{key}</span>}
            {label}
          </NavLink>
        ))}
        <BotConfigPanel />
      </div>
    </nav>
  );
}

// ── Connection health probe ───────────────────────────────────────────────────

function useConnectionHealth(): boolean | null {
  const [online, setOnline] = useState<boolean | null>(null);
  useEffect(() => {
    const check = () => {
      fetch("/api/health", { signal: AbortSignal.timeout(4000) })
        .then(r => setOnline(r.ok))
        .catch(() => setOnline(false));
    };
    check();
    const id = setInterval(check, 30_000);
    return () => clearInterval(id);
  }, []);
  return online;
}

// ── App ───────────────────────────────────────────────────────────────────────

function OfflineBanner({ online }: { online: boolean | null }) {
  if (online !== false) return null;
  return (
    <div style={{
      background: "#1a0000", border: "none", borderBottom: "2px solid #ff3333",
      color: "#ff3333", fontSize: 11, fontFamily: "Courier New",
      padding: "5px 20px", display: "flex", alignItems: "center", gap: 10,
      position: "sticky", top: 58, zIndex: 99,
    }}>
      <span style={{ fontWeight: 700 }}>● BACKEND OFFLINE</span>
      <span style={{ color: "#885555" }}>— cannot reach http://localhost:8000. Start the backend or check Docker.</span>
    </div>
  );
}

function AppShell() {
  const online = useConnectionHealth();

  return (
    <div className="app">
      <StatusBar online={online} />
      <Nav />
      <OfflineBanner online={online} />
      <main className="main-content">
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/chart" element={<Chart />} />
            <Route path="/monitor" element={<MarketMonitor />} />
            <Route path="/options" element={<Options />} />
            <Route path="/vol-surface" element={<VolSurface />} />
            <Route path="/news" element={<News />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/signals" element={<Signals />} />
            <Route path="/trades" element={<Trades />} />
            <Route path="/trades/:id" element={<TradeDetail />} />
            <Route path="/performance" element={<Performance />} />
            <Route path="/replay" element={<Replay />} />
            <Route path="/forward-log" element={<ForwardLog />} />
            <Route path="/forward-validation" element={<ForwardValidation />} />
            <Route path="/portfolio" element={<Portfolio />} />
            <Route path="/risk" element={<RiskDashboard />} />
            <Route path="/pipeline" element={<StrategyPipeline />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/data-quality" element={<DataQuality />} />
            <Route path="/experiments" element={<Experiments />} />
            <Route path="/health" element={<SystemHealth />} />
          </Routes>
        </ErrorBoundary>
      </main>
      <ToastContainer />
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  );
}
