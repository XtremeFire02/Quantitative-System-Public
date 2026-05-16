import React from "react";
import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import Signals from "./pages/Signals";
import Trades from "./pages/Trades";
import TradeDetail from "./pages/TradeDetail";
import Performance from "./pages/Performance";
import SystemHealth from "./pages/SystemHealth";
import RiskDashboard from "./pages/RiskDashboard";
import DataQuality from "./pages/DataQuality";
import StrategyPipeline from "./pages/StrategyPipeline";
import Alerts from "./pages/Alerts";
import ForwardLog from "./pages/ForwardLog";
import Experiments from "./pages/Experiments";
import BotConfigPanel from "./components/BotConfigPanel";
import "./App.css";

function Nav() {
  const cls = ({ isActive }: { isActive: boolean }) =>
    `nav-link${isActive ? " active" : ""}`;
  return (
    <nav className="nav">
      <div className="nav-brand">
        <span className="nav-logo">QF</span>
        <span className="nav-title">Paper Trading</span>
      </div>
      <div className="nav-links">
        <NavLink to="/" className={cls} end>Dashboard</NavLink>
        <NavLink to="/signals" className={cls}>Signals</NavLink>
        <NavLink to="/trades" className={cls}>Trades</NavLink>
        <NavLink to="/performance" className={cls}>Performance</NavLink>
        <NavLink to="/forward-log" className={cls}>Shadow Log</NavLink>
        <NavLink to="/risk" className={cls}>Risk</NavLink>
        <NavLink to="/pipeline" className={cls}>Pipeline</NavLink>
        <NavLink to="/alerts" className={cls}>Alerts</NavLink>
        <NavLink to="/data-quality" className={cls}>Data</NavLink>
        <NavLink to="/experiments" className={cls}>Experiments</NavLink>
        <NavLink to="/health" className={cls}>System</NavLink>
        <BotConfigPanel />
      </div>
    </nav>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="app">
        <Nav />
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/signals" element={<Signals />} />
            <Route path="/trades" element={<Trades />} />
            <Route path="/trades/:id" element={<TradeDetail />} />
            <Route path="/performance" element={<Performance />} />
            <Route path="/forward-log" element={<ForwardLog />} />
            <Route path="/risk" element={<RiskDashboard />} />
            <Route path="/pipeline" element={<StrategyPipeline />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/data-quality" element={<DataQuality />} />
            <Route path="/experiments" element={<Experiments />} />
            <Route path="/health" element={<SystemHealth />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
