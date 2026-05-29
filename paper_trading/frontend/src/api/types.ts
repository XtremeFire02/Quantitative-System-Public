export interface DashboardData {
  price: number | null;
  funding_rate: number | null;
  dvol: number | null;
  n3_z: number | null;
  dvol_filter_pass: boolean | null;
  entry_signal: boolean | null;
  signal_reason: string | null;
  last_signal_time: string | null;
  open_position: boolean;
  open_trade: OpenTradeSummary | null;
  open_trades: OpenTradeSummary[];
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
  market: string;
  strategy_name: string;
  side: string;
  entry_price: number;
  entry_dvol: number;
  entry_n3_z: number;
  entry_timestamp: string;
  planned_exit_timestamp: string;
  unrealised_pnl_bp: number | null;
  time_to_exit_hours: number | null;
}

export interface SignalRecord {
  id: number;
  timestamp: string;
  strategy_name: string;
  dvol: number | null;
  dvol_mean_30d: number | null;
  dvol_std_30d: number | null;
  n3_z: number | null;
  dvol_filter_pass: boolean | null;
  entry_signal: boolean;
  reason: string | null;
  created_at?: string | null;
}

export interface TradeRecord {
  id: number;
  market: string | null;
  strategy_name: string;
  status: "open" | "closed";
  side: string;
  notional_usd: number | null;
  entry_timestamp: string;
  entry_price: number;
  entry_dvol: number;
  entry_n3_z: number;
  entry_reason: string | null;
  // Simulated fill fields
  signal_price: number | null;          // evaluation price at signal time
  fill_type: string | null;             // "maker" | "taker"
  entry_half_spread_bp: number | null;
  entry_impact_bp: number | null;
  entry_maker_prob: number | null;
  entry_quality_score: number | null;   // 0–10
  planned_exit_timestamp: string;
  exit_timestamp: string | null;
  exit_price: number | null;
  exit_signal_price: number | null;     // raw market price at exit
  exit_half_spread_bp: number | null;
  exit_impact_bp: number | null;
  exit_quality_score: number | null;    // 0–10
  gross_price_return: number | null;
  gross_price_return_bp: number | null;
  funding_pnl: number | null;
  funding_pnl_bp: number | null;
  slippage: number | null;
  slippage_bp: number | null;
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
  message?: string;
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
  closed_trade_count: number;
  total_trade_count: number;
  next_scheduled_exit: string | null;
  hours_to_exit: number | null;
  next_daily_job_utc: string;
  last_daily_job_run: string | null;
  last_exit_job_run: string | null;
  recent_errors_24h: number;
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

export interface ReplayTrade {
  date: string;
  side: string;
  n3z: number;
  dvol: number;
  r24h_bp: number;
  fund_24h_bp: number;
  net_pnl_bp: number;
  cumulative_pnl_bp: number;
}

export interface ReplayPeriod {
  label: string;
  start: string;
  end: string;
  n_trades: number;
  sharpe: number | null;
  total_pnl_bp: number;
  max_dd_bp: number;
  win_rate: number | null;
  avg_win_bp: number | null;
  avg_loss_bp: number | null;
  exposure_pct: number | null;
  longs: number;
  shorts: number;
  is_oos: boolean;
}

export interface ReplaySummary {
  n_trades: number;
  sharpe: number | null;
  total_pnl_bp: number;
  max_dd_bp: number;
  win_rate: number | null;
  avg_win_bp: number | null;
  avg_loss_bp: number | null;
}

export interface ReplayTargets {
  n_trades: number;
  sharpe: number;
  total_pnl_bp: number;
  max_dd_bp: number;
  win_rate: number;
  note: string;
}

export interface ReplayResponse {
  status: string;
  computed_at: string;
  data_range: { start: string; end: string };
  query_start: string;
  parameters: Record<string, string | number>;
  reference_targets: ReplayTargets;
  summary: ReplaySummary;
  period_breakdown: ReplayPeriod[];
  trades: ReplayTrade[];
}

// ── Portfolio risk ──────────────────────────────────────────────────────────

export interface RiskLimits {
  max_open_positions: number;
  max_same_market_positions: number;
  max_daily_loss_bp: number;
  max_strategy_drawdown_pct: number;
  max_consecutive_losses: number;
  max_gross_notional_usd: number;
}

export interface RiskPosition {
  trade_id: number;
  strategy: string;
  market: string;
  side: string;
  notional_usd: number | null;
  entry_price: number;
  entry_dvol: number | null;
  entry_quality_score: number | null;
  entry_timestamp: string | null;
  planned_exit: string | null;
}

export interface PortfolioState {
  total_open: number;
  max_total_open: number;
  max_same_market: number;
  gross_notional_usd: number;
  daily_pnl_bp: number;
  daily_loss_limit_bp: number;
  daily_limit_used_pct: number;
  notional_limit_used_pct: number;
  open_by_strategy: Record<string, number>;
  open_by_market: Record<string, number>;
  strategy_drawdowns: Record<string, number | null>;
  strategy_consecutive_losses: Record<string, number>;
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
  // P3 fields
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
  // N3-specific fields (only present on N3 log rows)
  n3_z?: number | null;
  dvol_filter_pass?: boolean | null;
  signal_price?: number | null;
  fill_type?: string | null;
  entry_quality?: number | null;
  slippage_bp?: number | null;
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

// ── Forward-validation report ───────────────────────────────────────────────

export interface FwdValidationComparison {
  status: "on_track" | "drift_detected" | "no_baseline" | "insufficient_data";
  live_sharpe: number | null;
  research_sharpe: number | null;
  sharpe_achievement_pct: number | null;
  live_win_rate: number | null;
  research_win_rate: number | null;
  live_avg_pnl_bp: number | null;
  research_avg_pnl_bp: number | null;
  drift_flag: boolean;
  research_run_id: string | null;
  research_data_range: string | null;
  message: string;
}

export interface FwdValidationStrategy {
  live: {
    n_closed: number;
    sharpe: number | null;
    win_rate: number | null;
    avg_pnl_bp: number | null;
    total_pnl_bp: number | null;
    first_trade: string | null;
    last_trade: string | null;
  };
  comparison: FwdValidationComparison;
}

export interface FwdValidationReport {
  generated_at: string;
  strategies: Record<string, FwdValidationStrategy>;
  summary: {
    total_strategies: number;
    on_track: number;
    drift_detected: number;
    no_baseline: number;
    insufficient_data: number;
  };
}

// ── Portfolio attribution ───────────────────────────────────────────────────

export interface PortfolioStrategyStats {
  strategy: string;
  avg_notional_usd: number;
  n: number;
  sharpe: number | null;
  total_pnl_bp: number;
  avg_pnl_bp: number | null;
  win_rate: number | null;
  max_dd_bp: number | null;
  contribution_pct: number | null;
}

export interface PortfolioAttribution {
  strategies: PortfolioStrategyStats[];
  portfolio_total_pnl_bp: number;
  portfolio_stats: {
    n_strategies: number;
    n_closed_trades: number;
    sharpe: number | null;
  };
  n3_p3_correlation: number | null;
  correlation_n_pairs: number;
  open_exposure: Array<{
    strategy: string;
    market: string;
    side: string;
    notional_usd: number;
    entry_timestamp: string | null;
    planned_exit: string | null;
  }>;
  total_open_notional_usd: number;
  generated_at: string;
}

// ── Connectivity ────────────────────────────────────────────────────────────

export interface ConnectivityProbe {
  name: string;
  feed: string;
  ok: boolean;
  level: "ok" | "warn" | "critical";
  latency_ms: number | null;
  error: string | null;
  status_code: number | null;
}

export interface ConnectivityStatus {
  overall: "ok" | "warn" | "critical";
  max_latency_ms: number;
  probes: ConnectivityProbe[];
  thresholds: { warn_ms: number; critical_ms: number };
  checked_at: string;
}

// ── Forward log summary ─────────────────────────────────────────────────────

export interface ForwardSummaryStratStats {
  n: number;
  sharpe: number | null;
  total_pnl_bp: number;
  win_rate: number | null;
  open_positions: number;
}

export interface ForwardSummaryRegime {
  dvol: number | null;
  n3_z: number | null;
  dvol_filter_pass: boolean | null;
  signal_active: boolean | null;
  last_evaluated: string | null;
}

export interface ForwardSummaryData {
  n3: ForwardSummaryStratStats;
  p3: ForwardSummaryStratStats;
  blocked_trades: number;
  current_regime: ForwardSummaryRegime;
  generated_at: string;
}

// ── Performance by strategy ─────────────────────────────────────────────────

export interface StrategyPerfStats {
  strategy_name: string;
  n_trades: number;
  sharpe: number | null;
  total_pnl_bp: number;
  max_dd_bp: number | null;
  win_rate: number | null;
  avg_win_bp: number | null;
  avg_loss_bp: number | null;
  yearly?: { year: number; n_trades: number; total_pnl_bp: number; sharpe: number | null; win_rate: number }[];
}

export interface PerfCombinationRow extends StrategyPerfStats {
  label: string;
}

export interface PerformanceByStrategyResponse {
  strategies: StrategyPerfStats[];
  combinations: PerfCombinationRow[];
  message?: string;
}

// ── Chart / OHLCV ───────────────────────────────────────────────────────────

export interface OHLCVBar {
  t: number;          // open timestamp ms
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
  rsi: number | null;
  macd: number | null;
  macd_signal: number | null;
  macd_hist: number | null;
  bb_upper: number | null;
  bb_mid: number | null;
  bb_lower: number | null;
  ema20: number | null;
  ema50: number | null;
}

export interface ChartData {
  symbol: string;
  interval: string;
  bars: OHLCVBar[];
}

export interface OrderBook {
  symbol: string;
  last_update_id: number | null;
  bids: [number, number][];   // [price, qty]
  asks: [number, number][];
  mid_price: number | null;
  spread_bp: number | null;
}

// ── Market Monitor ───────────────────────────────────────────────────────────

export interface MonitorAsset {
  symbol: string;
  base: string;
  price: number | null;
  price_change_pct: number | null;
  high_24h: number | null;
  low_24h: number | null;
  volume: number | null;
  quote_volume: number | null;
  mark_price: number | null;
  index_price: number | null;
  funding_rate: number | null;
  next_funding_time: number | null;
  open_interest: number | null;
  dvol: number | null;
}

export interface MarketMonitorData {
  assets: MonitorAsset[];
  fetched_at: string;
}

export interface TermStructureContract {
  symbol: string;
  contract_type: string;
  mark_price: number;
  index_price: number;
  funding_rate: number;
  delivery_date: string | null;
  basis_pct: number;
}

export interface TermStructureData {
  base: string;
  contracts: TermStructureContract[];
}

export interface CorrelationMatrix {
  labels: string[];
  matrix: (number | null)[][];
  period_days: number;
  fetched_at: string;
}

// ── Options ─────────────────────────────────────────────────────────────────

export interface OptionsChainRow {
  strike: number;
  underlying_price: number | null;
  call_iv: number | null;
  call_bid_iv: number | null;
  call_ask_iv: number | null;
  call_bid: number | null;
  call_ask: number | null;
  call_oi: number | null;
  call_volume: number | null;
  put_iv: number | null;
  put_bid_iv: number | null;
  put_ask_iv: number | null;
  put_bid: number | null;
  put_ask: number | null;
  put_oi: number | null;
  put_volume: number | null;
}

export interface IVSurfaceRow {
  expiry: string;
  strike: number;
  underlying_price: number | null;
  call_iv: number | null;
  put_iv: number | null;
}

export interface IVSurfaceData {
  currency: string;
  expiries: string[];
  strikes: number[];
  surface: IVSurfaceRow[];
}

// ── News ─────────────────────────────────────────────────────────────────────

export interface NewsItem {
  source: string;
  title: string;
  url: string;
  published_at: string | null;
  summary: string | null;
}

export interface NewsData {
  items: NewsItem[];
  total: number;
  sources_ok: string[];
  sources_err: string[];
  fetched_at: string;
}

// ── Options chain (with Greeks) ──────────────────────────────────────────────

export interface OptionsChainRowWithGreeks extends OptionsChainRow {
  call_delta: number | null;
  call_gamma: number | null;
  call_theta: number | null;
  call_vega:  number | null;
  put_delta:  number | null;
  put_gamma:  number | null;
  put_theta:  number | null;
  put_vega:   number | null;
}

// ── Liquidations ─────────────────────────────────────────────────────────────

export interface LiquidationEvent {
  symbol: string;
  side: string;
  price: number;
  qty: number;
  notional_usd: number;
  timestamp: number;
  time_utc: string;
}

export interface LiquidationsData {
  symbol: string;
  liquidations: LiquidationEvent[];
  total_long_liquidated_usd: number;
  total_short_liquidated_usd: number;
  total_usd: number;
  fetched_at: string;
}

export interface LiquidationAssetSummary {
  symbol: string;
  long_liquidated_usd: number;
  short_liquidated_usd: number;
  total_usd: number;
  n_events: number;
  dominant_side: "long" | "short" | "neutral";
  error?: string;
}

export interface LiquidationsSummary {
  assets: LiquidationAssetSummary[];
  fetched_at: string;
}

// ── Deep Analytics ────────────────────────────────────────────────────────────

export interface SharpeWithCI {
  value: number | null;
  ci_lo: number | null;
  ci_hi: number | null;
  se: number | null;
  n: number;
  significant: boolean;
  min_n_for_significance: number | null;
}

export interface DeepAnalytics {
  strategy: string;
  n: number;
  trades_per_year: number;
  win_rate: number | null;
  avg_win_bp: number | null;
  avg_loss_bp: number | null;
  profit_factor: number | null;
  max_drawdown_bp: number;
  sharpe: SharpeWithCI;
  sortino: number | null;
  calmar: number | null;
  risk: {
    var_95: number | null;
    var_99: number | null;
    cvar_95: number | null;
    cvar_99: number | null;
  };
  kelly: {
    full_kelly_pct: number | null;
    half_kelly_pct: number | null;
    quarter_kelly_pct: number | null;
    b_ratio: number | null;
    edge: number | null;
    positive_edge: boolean;
  };
  signal_ic: {
    overall_ic: number | null;
    n_pairs: number;
    rolling: { trade_n: number; ic: number | null }[];
    ic_window: number;
    decaying: boolean | null;
  };
  distribution: {
    mean_bp: number;
    std_bp: number;
    skewness: number | null;
    excess_kurtosis: number | null;
    max_win_bp: number;
    max_loss_bp: number;
    positive_skew: boolean;
  };
  histogram: { bin_lo: number; bin_hi: number; count: number }[];
  equity_curve: number[];
  yearly_breakdown: {
    year: number;
    n: number;
    total_pnl_bp: number;
    mean_pnl_bp: number;
    sharpe: number | null;
    win_rate: number;
    avg_win_bp: number | null;
    avg_loss_bp: number | null;
  }[];
  generated_at: string;
  error?: string;
}
