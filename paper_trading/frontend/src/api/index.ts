import { apiFetch, apiPost, apiPostBody, apiDelete, apiPatch } from "./client";
import type {
  DashboardData, SignalRecord, TradeRecord, PerformanceData,
  SystemHealth, SystemLog, ReplayResponse,
  AvailableConfig, ActiveBotConfig,
  PortfolioState, RiskLimits,
  StrategyPipelineRow, PromotionRules,
  DataQualityReport,
  AlertRecord, AlertSummary,
  ForwardLogResponse, ForwardSummaryData,
  ExperimentRun,
  FwdValidationReport,
  PortfolioAttribution,
  ConnectivityStatus,
  PerformanceByStrategyResponse,
  ChartData, OrderBook,
  MarketMonitorData, TermStructureData, CorrelationMatrix,
  IVSurfaceData, OptionsChainRow,
  NewsData,
  LiquidationsData, LiquidationsSummary,
  DeepAnalytics,
} from "./types";

export const api = {
  dashboard: () => apiFetch<DashboardData>("/dashboard"),
  latestSignal: () => apiFetch<SignalRecord>("/signals/latest"),
  signalHistory: (limit = 90) => apiFetch<SignalRecord[]>(`/signals/history?limit=${limit}`),
  trades: (status?: "open" | "closed") =>
    apiFetch<TradeRecord[]>(status ? `/trades?status=${status}` : "/trades"),
  openTrades: () => apiFetch<TradeRecord[]>("/trades/open"),
  trade: (id: number) => apiFetch<TradeRecord>(`/trades/${id}`),
  closeTrade: (id: number) => apiPost<{ status: string; trade_id: number; net_pnl_bp: number | null }>(`/trades/${id}/close`),
  performance: () => apiFetch<PerformanceData>("/performance"),
  performanceByStrategy: (strategy?: string) =>
    apiFetch<PerformanceByStrategyResponse>(
      strategy ? `/performance/by-strategy?strategy=${strategy}` : "/performance/by-strategy"
    ),
  systemHealth: () => apiFetch<SystemHealth>("/system/health"),
  systemLogs: (limit = 50) => apiFetch<SystemLog[]>(`/system/logs?limit=${limit}`),
  runDailySignal: () => apiPost<unknown>("/jobs/run-daily-signal"),
  checkExits: () => apiPost<unknown>("/jobs/check-exits"),
  replay: (start = "2024-01-01", includeTrain = false) =>
    apiFetch<ReplayResponse>(`/replay?start=${start}&include_train=${includeTrain}`),

  // Bot configuration
  configAvailable: () => apiFetch<AvailableConfig>("/config/available"),
  configActive: () => apiFetch<ActiveBotConfig[]>("/config/active"),
  configAdd: (market: string, strategy_name: string) =>
    apiPostBody<unknown>("/config/active", { market, strategy_name }),
  configRemove: (market: string, strategy_name: string) =>
    apiDelete<unknown>(`/config/active/${market}/${strategy_name}`),

  // Portfolio risk
  riskState: () => apiFetch<PortfolioState>("/risk/state"),
  riskLimits: () => apiFetch<RiskLimits>("/risk/limits"),

  // Strategy pipeline
  strategies: () => apiFetch<StrategyPipelineRow[]>("/strategies"),
  strategy: (name: string) => apiFetch<StrategyPipelineRow>(`/strategies/${name}`),
  strategyUpdateStatus: (name: string, status: string, note = "", promoted_by = "manual") =>
    apiPostBody<StrategyPipelineRow>(`/strategies/${name}/status`, { status, note, promoted_by }),
  promotionRules: () => apiFetch<PromotionRules>("/strategies/meta/rules"),

  // Data quality
  dataQuality: () => apiFetch<DataQualityReport>("/system/data-quality"),

  // Alerts
  alerts: (limit = 100) => apiFetch<AlertRecord[]>(`/alerts?limit=${limit}`),
  alertSummary: () => apiFetch<AlertSummary>("/alerts/summary"),
  alertRead: (id: number) => apiPost<unknown>(`/alerts/${id}/read`),
  alertReadAll: () => apiPost<unknown>("/alerts/mark-all-read"),

  // Forward log
  forwardLog: (strategy = "P3_OIPD_DD", limit = 500) =>
    apiFetch<ForwardLogResponse>(`/forward-log/p3?strategy=${strategy}&limit=${limit}`),
  forwardLogN3: (limit = 500) =>
    apiFetch<ForwardLogResponse>(`/forward-log/n3?limit=${limit}`),
  forwardLogSummary: () =>
    apiFetch<ForwardSummaryData>("/forward-log/summary"),

  // Experiments
  experiments: () => apiFetch<ExperimentRun[]>("/experiments"),
  experiment: (runId: string) => apiFetch<ExperimentRun>(`/experiments/${runId}`),
  experimentCreate: (body: Partial<ExperimentRun>) =>
    apiPostBody<ExperimentRun>("/experiments", body),
  experimentVerdict: (runId: string, verdict: string, notes?: string) =>
    apiPatch<ExperimentRun>(`/experiments/${runId}`, { verdict, notes }),

  // Forward-validation report
  fwdValidation: () => apiFetch<FwdValidationReport>("/forward-validation/report"),
  refreshFwdValidation: () => apiPost<FwdValidationReport>("/forward-validation/report/refresh"),

  // Portfolio attribution
  portfolio: () => apiFetch<PortfolioAttribution>("/portfolio/attribution"),

  // Connectivity probes
  connectivity: () => apiFetch<ConnectivityStatus>("/connectivity"),

  // Chart
  chartOHLCV: (symbol = "BTCUSDT", interval = "1h", limit = 500) =>
    apiFetch<ChartData>(`/chart/ohlcv?symbol=${symbol}&interval=${interval}&limit=${limit}`),
  chartOrderbook: (symbol = "BTCUSDT", depth = 20) =>
    apiFetch<OrderBook>(`/chart/orderbook?symbol=${symbol}&depth=${depth}`),

  // Market monitor
  marketMonitor: () => apiFetch<MarketMonitorData>("/market/monitor"),
  termStructure: (base = "BTC") => apiFetch<TermStructureData>(`/market/term-structure?base=${base}`),
  correlations: (period = 30) => apiFetch<CorrelationMatrix>(`/market/correlations?period=${period}`),

  // Options / volatility
  optionsExpiries: (currency = "BTC") => apiFetch<{ currency: string; expiries: string[] }>(`/options/expiries?currency=${currency}`),
  optionsChain: (currency = "BTC", expiry?: string) =>
    apiFetch<{ currency: string; expiry: string | null; rows: OptionsChainRow[] }>(
      expiry ? `/options/chain?currency=${currency}&expiry=${expiry}` : `/options/chain?currency=${currency}`
    ),
  optionsSurface: (currency = "BTC") => apiFetch<IVSurfaceData>(`/options/surface?currency=${currency}`),

  // News
  news: (limit = 40, source?: string) =>
    apiFetch<NewsData>(source ? `/news?limit=${limit}&source=${encodeURIComponent(source)}` : `/news?limit=${limit}`),

  // Liquidations
  liquidations: (symbol?: string, limit = 50, minUsd = 0) =>
    apiFetch<LiquidationsData>(
      `/market/liquidations?limit=${limit}&min_usd=${minUsd}${symbol ? `&symbol=${symbol}` : ""}`
    ),
  liquidationsSummary: () => apiFetch<LiquidationsSummary>("/market/liquidations/summary"),

  // Deep analytics
  deepAnalytics: (strategy?: string) =>
    apiFetch<DeepAnalytics>(strategy ? `/analytics/deep?strategy=${strategy}` : "/analytics/deep"),
};

export type {
  DashboardData, OpenTradeSummary, SignalRecord, TradeRecord, PerformanceData,
  SystemHealth, SystemLog, EquityPoint, YearlyBreakdown,
  ReplayResponse, ReplayTrade, ReplayPeriod, ReplaySummary,
  AvailableConfig, ActiveBotConfig, MarketInfo, StrategyInfo,
  PortfolioState, RiskLimits, RiskPosition,
  StrategyPipelineRow, PromotionRules, StrategyLiveStats,
  DataQualityReport, DataQualityCheck,
  AlertRecord, AlertSummary,
  ForwardLogResponse, ForwardLogRow, ForwardLogStats, ForwardLogSummary,
  ForwardSummaryData, ForwardSummaryStratStats, ForwardSummaryRegime,
  ExperimentRun,
  FwdValidationReport, FwdValidationStrategy, FwdValidationComparison,
  PortfolioAttribution, PortfolioStrategyStats,
  ConnectivityStatus, ConnectivityProbe,
  PerformanceByStrategyResponse, StrategyPerfStats, PerfCombinationRow,
  OHLCVBar, ChartData, OrderBook,
  MonitorAsset, MarketMonitorData, TermStructureContract, TermStructureData, CorrelationMatrix,
  OptionsChainRow, OptionsChainRowWithGreeks, IVSurfaceRow, IVSurfaceData,
  NewsItem, NewsData,
  LiquidationEvent, LiquidationsData, LiquidationAssetSummary, LiquidationsSummary,
  DeepAnalytics, SharpeWithCI,
} from "./types";
