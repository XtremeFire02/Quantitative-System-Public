"""
Quantitative Paper Trading System — FastAPI backend
"""
import asyncio
import logging #Library to write logs like info, warning, error, critical etc. It helps in debugging and monitoring the application.
import logging.config # To config log behaviour
from contextlib import asynccontextmanager # Helper for startup and shutdown events in async programs

from apscheduler.schedulers.asyncio import AsyncIOScheduler #Library for scheduling tasks
from apscheduler.triggers.cron import CronTrigger #Library to trigger jobs periodically at certain times, dates, or intervals. Here we use it to schedule daily and periodic tasks.
from apscheduler.triggers.interval import IntervalTrigger #Library to trigger jobs at fixed intervals, e.g., every 15 minutes.
from fastapi import Depends, FastAPI #Web framework for building API servers with Python. It provides tools for routing, dependency injection, and more.
from fastapi.middleware.cors import CORSMiddleware #Middleware to handle Cross-Origin Resource Sharing (CORS), allowing the API to be accessed from different origins (e.g., frontend apps running on different domains or ports).

from app.config import ENV

# ── Logging ───────────────────────────────────────────────────────────────────
_LOG_LEVEL = logging.DEBUG if ENV == "development" else logging.INFO
logging.basicConfig(
    level=_LOG_LEVEL,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # replaced by our middleware

from app.api import alerts as alerts_api
from app.api import analytics as analytics_api
from app.api import audit as audit_api
from app.api import chart as chart_api
from app.api import (
    config,
    dashboard,
    data_quality,
    experiments,
    forward_log,
    metrics,
    p3_replay,
    performance,
    portfolio_risk,
    replay,
    signals,
    strategy_pipeline,
    system_health,
    trades,
)
from app.api import connectivity as connectivity_api
from app.api import fwd_report as fwd_report_api
from app.api import kill_switch as kill_switch_api
from app.api import liquidations as liquidations_api
from app.api import market_monitor as market_monitor_api
from app.api import news as news_api
from app.api import options as options_api
from app.api import portfolio as portfolio_api
from app.api import report as report_api
from app.config import API_KEY, CORS_ORIGINS, DAILY_JOB_HOUR_UTC, ENV, EXIT_CHECK_INTERVAL_MINUTES
from app.data.ws_market_data import run_ws_feed
from app.database import init_db
from app.jobs.daily_signal_job import run_daily_signal_job
from app.jobs.exit_trade_job import run_exit_trade_job
from app.jobs.fwd_validation_report_job import run_fwd_validation_report
from app.middleware.auth import require_api_key
from app.middleware.logging import RequestLoggingMiddleware

logger = logging.getLogger(__name__) #Creates a logger object for this file, which can be used to write log messages with the module name included.
scheduler = AsyncIOScheduler(timezone="UTC") #


#the app refuses to start if important security settings are missing.
def _validate_config() -> None:
    """Fail fast in paper_prod if security-critical variables are missing."""
    if ENV != "paper_prod":
        return
    errors: list[str] = []
    if not API_KEY:
        errors.append("API_KEY must be set in paper_prod (generate: python -c \"import secrets; print(secrets.token_hex(32))\")")
    if errors:
        for e in errors:
            logger.critical("CONFIG ERROR: %s", e)
        raise RuntimeError(f"Startup aborted: {len(errors)} configuration error(s). See logs.")

#lifespan() says:
#on startup:
#   validate config,
#   init DB,
#   start feed,
#   start scheduler
#on shutdown:
#   stop scheduler,
#   stop feed
@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_config()
    logger.info("Starting paper trading backend  env=%s", ENV)
    init_db()

    _ws_task = asyncio.create_task(run_ws_feed())

    # max_instances=1 + coalesce=True: if a previous run is still in flight
    # when the next tick fires (e.g. slow API call on exit_trade_job's 15min
    # interval), the scheduler drops the duplicate rather than launching it
    # concurrently. Without this, overlapping runs can race on the same Trade
    # rows and produce duplicate opens or double closes.
    scheduler.add_job(
        run_daily_signal_job,
        CronTrigger(hour=DAILY_JOB_HOUR_UTC, minute=0, timezone="UTC"),
        id="daily_signal_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        run_exit_trade_job,
        IntervalTrigger(minutes=EXIT_CHECK_INTERVAL_MINUTES),
        id="exit_trade_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        run_fwd_validation_report,
        CronTrigger(hour=1, minute=0, timezone="UTC"),
        id="fwd_validation_report_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    scheduler.start()
    yield
    scheduler.shutdown()

    _ws_task.cancel()
    try:
        await _ws_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Quantitative Paper Trading System",
    description="Signal validation via live paper trading. Read-only endpoints are open; write endpoints require X-Api-Key.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    # Explicit origins from env (prod); localhost regex always included for dev
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=r"http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router,          prefix="/api", tags=["dashboard"])
app.include_router(signals.router,            prefix="/api", tags=["signals"])
app.include_router(trades.router,             prefix="/api", tags=["trades"])
app.include_router(performance.router,        prefix="/api", tags=["performance"])
app.include_router(system_health.router,      prefix="/api", tags=["system"])
app.include_router(metrics.router,            prefix="/api", tags=["metrics"])
app.include_router(replay.router,             prefix="/api", tags=["replay"])
app.include_router(p3_replay.router,          prefix="/api", tags=["replay"])
app.include_router(config.router,             prefix="/api", tags=["config"])
app.include_router(alerts_api.router,         prefix="/api", tags=["alerts"])
app.include_router(forward_log.router,        prefix="/api", tags=["forward-log"])
app.include_router(portfolio_risk.router,     prefix="/api", tags=["risk"])
app.include_router(strategy_pipeline.router,  prefix="/api", tags=["pipeline"])
app.include_router(data_quality.router,       prefix="/api", tags=["data-quality"])
app.include_router(experiments.router,        prefix="/api", tags=["experiments"])
app.include_router(kill_switch_api.router,    prefix="/api", tags=["risk"])
app.include_router(audit_api.router,          prefix="/api", tags=["audit"])
app.include_router(connectivity_api.router,   prefix="/api", tags=["connectivity"])
app.include_router(portfolio_api.router,      prefix="/api", tags=["portfolio"])
app.include_router(report_api.router,         prefix="/api", tags=["report"])
app.include_router(fwd_report_api.router,     prefix="/api", tags=["forward-validation"])
app.include_router(chart_api.router,          prefix="/api", tags=["chart"])
app.include_router(market_monitor_api.router, prefix="/api", tags=["market"])
app.include_router(options_api.router,        prefix="/api", tags=["options"])
app.include_router(news_api.router,           prefix="/api", tags=["news"])
app.include_router(analytics_api.router,      prefix="/api", tags=["analytics"])
app.include_router(liquidations_api.router,   prefix="/api", tags=["market"])


# Manual job triggers — authenticated write endpoints
@app.post("/api/jobs/run-daily-signal", tags=["jobs"],
          dependencies=[Depends(require_api_key)])
async def trigger_daily_signal():
    return await run_daily_signal_job()


@app.post("/api/jobs/check-exits", tags=["jobs"],
          dependencies=[Depends(require_api_key)])
async def trigger_exit_check():
    return await run_exit_trade_job()


@app.get("/api/health", tags=["health"])
def health():
    from datetime import datetime, timezone

    jobs = []
    for job in scheduler.get_jobs():
        nf = job.next_run_time
        jobs.append({
            "id": job.id,
            "next_run": nf.isoformat() if nf else None,
        })

    return {
        "status": "ok",
        "env": ENV,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scheduler": {"running": scheduler.running, "jobs": jobs},
    }
