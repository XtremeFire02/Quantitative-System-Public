export interface DashboardData {
  btc_price: number | null;
  funding_rate: number | null;
  dvol: number | null;
  n3_z: number | null;
  dvol_filter_pass: boolean | null;
  entry_signal: boolean | null;
  signal_reason: string | null;
  last_signal_time: string | null;
  open_position: boolean;
  open_trade: OpenTradeSummary | null;
  time_to_exit_hours: number | null;
  equity: number;
  realised_pnl: number;
  unrealised_pnl: number;
  unrealised_pnl_bp: number;
  drawdown: number;
  last_market_update: string | null;
}

export interface OpenTradeSummary {
  id: number;
  side: string;
  entry_price: number;
  entry_dvol: number;
  entry_n3_z: number;
  entry_timestamp: string;
  planned_exit_timestamp: string;
}

export interface SignalRecord {
  id: number;
  timestamp: string;
  strategy_name: string;
  dvol: number;
  dvol_mean_30d: number;
  dvol_std_30d: number;
  n3_z: number;
  dvol_filter_pass: boolean;
  entry_signal: boolean;
  reason: string;
}

export interface TradeRecord {
  id: number;
  strategy_name: string;
  status: "open" | "closed";
  side: string;
  entry_timestamp: string;
  entry_price: number;
  entry_dvol: number;
  entry_n3_z: number;
  entry_reason: string | null;
  planned_exit_timestamp: string;
  exit_timestamp: string | null;
  exit_price: number | null;
  gross_price_return: number | null;
  gross_price_return_bp: number | null;
  funding_pnl: number | null;
  funding_pnl_bp: number | null;
  fees: number | null;
  fees_bp: number | null;
  net_pnl: number | null;
  net_pnl_bp: number | null;
  exit_reason: string | null;
}

export interface PerformanceData {
  total_trades: number;
  total_pnl?: number;
  total_pnl_bp?: number;
  sharpe?: number | null;
  max_drawdown?: number;
  win_rate?: number;
  average_win?: number;
  average_win_bp?: number;
  average_loss?: number;
  average_loss_bp?: number;
  profit_factor?: number | null;
  equity_history?: EquityPoint[];
  yearly_breakdown?: YearlyBreakdown[];
}

export interface EquityPoint {
  timestamp: string;
  equity: number;
  drawdown: number;
  realised_pnl: number;
}

export interface YearlyBreakdown {
  year: number;
  n_trades: number;
  total_pnl_bp: number;
  sharpe: number | null;
  win_rate: number;
}

export interface SystemHealth {
  status: "healthy" | "degraded";
  last_binance_update: string | null;
  market_data_stale: boolean;
  last_signal_calculation: string | null;
  signal_data_stale: boolean;
  open_position_count: number;
  stale_threshold_minutes: number;
  database_status: string;
  checked_at: string;
}

export interface SystemLog {
  id: number;
  timestamp: string;
  level: string;
  component: string;
  message: string;
}

// ── Portfolio risk ──────────────────────────────────────────────────────────

export interface RiskLimits {
  max_open_positions: number;
  max_same_market_positions: number;
  max_daily_loss_bp: number;
  max_strategy_drawdown_pct: number;
}

export interface RiskPosition {
  trade_id: number;
  strategy: string;
  market: string;
  side: string;
  entry_price: number;
  entry_dvol: number | null;
  entry_timestamp: string | null;
  planned_exit: string | null;
}

export interface PortfolioState {
  total_open: number;
  max_total_open: number;
  max_same_market: number;
  daily_pnl_bp: number;
  daily_loss_limit_bp: number;
  daily_limit_used_pct: number;
  open_by_strategy: Record<string, number>;
  open_by_market: Record<string, number>;
  strategy_drawdowns: Record<string, number | null>;
  limits: RiskLimits;
  positions: RiskPosition[];
}

// ── Strategy pipeline ───────────────────────────────────────────────────────

export interface StrategyLiveStats {
  n_evaluations: number;
  n_trades: number;
  n_open: number;
}

export interface StrategyPipelineRow {
  strategy_name: string;
  status: "research" | "candidate" | "shadow" | "validated" | "paused" | "killed";
  status_description: string;
  promoted_at: string | null;
  promoted_by: string | null;
  note: string | null;
  created_at: string | null;
  updated_at: string | null;
  live_stats: StrategyLiveStats;
}

export interface PromotionRules {
  statuses: Record<string, string>;
  promotion_criteria: Record<string, string>;
}

// ── Data quality ────────────────────────────────────────────────────────────

export interface DataQualityCheck {
  name: string;
  status: "ok" | "warn" | "error";
  detail: string;
  value: number | null;
  expected: number | string;
}

export interface DataQualityReport {
  status: "ok" | "warn" | "error";
  checked_at: string;
  n_checks: number;
  n_warn: number;
  n_error: number;
  checks: DataQualityCheck[];
}

// ── Alerts ──────────────────────────────────────────────────────────────────

export interface AlertRecord {
  id: number;
  timestamp: string;
  category: string;
  title: string;
  body: string | null;
  strategy: string | null;
  market: string | null;
  exposure: Record<string, unknown> | null;
  action_taken: string | null;
  is_read: boolean;
}

export interface AlertSummary {
  total_unread: number;
  by_category: Record<string, number>;
}

// ── Forward log ─────────────────────────────────────────────────────────────

export interface ForwardLogRow {
  date: string;
  evaluation_time: string;
  dvol: number | null;
  regime: string | null;
  dp_pct: number | null;
  doi_pct: number | null;
  signal_fired: boolean;
  reason: string | null;
  n3_also_fired: boolean;
  p3_exclusive: boolean;
  entry_price: number | null;
  exit_price: number | null;
  funding_bp: number | null;
  fees_bp: number | null;
  net_pnl_bp: number | null;
  trade_status: string | null;
}

export interface ForwardLogStats {
  n: number;
  sharpe: number | null;
  total_pnl_bp: number;
  win_rate: number | null;
}

export interface ForwardLogSummary {
  all_trades: ForwardLogStats;
  exclusive_trades: ForwardLogStats;
  overlap_trades: ForwardLogStats;
}

export interface ForwardLogResponse {
  strategy: string;
  n_evaluations: number;
  n_trades: number;
  n_exclusive: number;
  n_overlap: number;
  summary: ForwardLogSummary;
  rows: ForwardLogRow[];
}

// ── Experiments ─────────────────────────────────────────────────────────────

export interface ExperimentRun {
  run_id: string;
  script_name: string | null;
  strategy_name: string | null;
  commit_hash: string | null;
  data_range_start: string | null;
  data_range_end: string | null;
  parameters: Record<string, unknown> | null;
  metrics: Record<string, unknown> | null;
  verdict: "passed" | "failed" | "killed" | "pending";
  notes: string | null;
  created_at: string | null;
}

// ── Bot configuration ──────────────────────────────────────────────────────

export interface MarketInfo {
  display_name: string;
  exchange: string;
  base_asset: string;
  requires_dvol: boolean;
  icon: string;
}

export interface StrategyInfo {
  display_name: string;
  description: string;
  compatible_markets: string[];
  hold_hours: number;
  requires_dvol: boolean;
  tags: string[];
  status: "validated" | "experimental" | "shadow" | "execution_test" | "coming_soon";
}

export interface AvailableConfig {
  markets: Record<string, MarketInfo>;
  strategies: Record<string, StrategyInfo>;
}

export interface ActiveBotConfig {
  id: number;
  market: string;
  strategy_name: string;
  is_active: boolean;
  created_at: string | null;
}
