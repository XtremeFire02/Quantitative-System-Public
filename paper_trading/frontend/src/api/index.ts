import { apiFetch, apiPost, apiPostBody, apiDelete, apiPatch } from "./client";
import type {
  DashboardData, SignalRecord, TradeRecord, PerformanceData,
  SystemHealth, SystemLog, ReplayResponse,
  AvailableConfig, ActiveBotConfig,
  PortfolioState, RiskLimits,
  StrategyPipelineRow, PromotionRules,
  DataQualityReport,
  AlertRecord, AlertSummary,
  ForwardLogResponse,
  ExperimentRun,
} from "./types";

export const api = {
  dashboard: () => apiFetch<DashboardData>("/dashboard"),
  latestSignal: () => apiFetch<SignalRecord>("/signals/latest"),
  signalHistory: (limit = 90) => apiFetch<SignalRecord[]>(`/signals/history?limit=${limit}`),
  trades: (status?: "open" | "closed") =>
    apiFetch<TradeRecord[]>(status ? `/trades?status=${status}` : "/trades"),
  openTrades: () => apiFetch<TradeRecord[]>("/trades/open"),
  trade: (id: number) => apiFetch<TradeRecord>(`/trades/${id}`),
  performance: () => apiFetch<PerformanceData>("/performance"),
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

  // Experiments
  experiments: () => apiFetch<ExperimentRun[]>("/experiments"),
  experiment: (runId: string) => apiFetch<ExperimentRun>(`/experiments/${runId}`),
  experimentCreate: (body: Partial<ExperimentRun>) =>
    apiPostBody<ExperimentRun>("/experiments", body),
  experimentVerdict: (runId: string, verdict: string, notes?: string) =>
    apiPatch<ExperimentRun>(`/experiments/${runId}`, { verdict, notes }),
};

export type {
  DashboardData, SignalRecord, TradeRecord, PerformanceData,
  SystemHealth, SystemLog, EquityPoint, YearlyBreakdown,
  ReplayResponse, ReplayTrade, ReplayPeriod, ReplaySummary,
  AvailableConfig, ActiveBotConfig, MarketInfo, StrategyInfo,
  PortfolioState, RiskLimits, RiskPosition,
  StrategyPipelineRow, PromotionRules, StrategyLiveStats,
  DataQualityReport, DataQualityCheck,
  AlertRecord, AlertSummary,
  ForwardLogResponse, ForwardLogRow, ForwardLogStats, ForwardLogSummary,
  ExperimentRun,
} from "./types";
