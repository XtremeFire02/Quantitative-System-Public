"""
Paper Trading System — FastAPI backend
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.database import init_db
from app.config import DAILY_JOB_HOUR_UTC, EXIT_CHECK_INTERVAL_MINUTES
from app.api import dashboard, signals, trades, performance, system_health, config
from app.api import alerts as alerts_api, forward_log
from app.api import portfolio_risk, strategy_pipeline, data_quality, experiments
from app.api import kill_switch as kill_switch_api
from app.api import audit as audit_api
from app.jobs.daily_signal_job import run_daily_signal_job
from app.jobs.exit_trade_job import run_exit_trade_job


scheduler = AsyncIOScheduler(timezone="UTC")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    # Daily signal job at 00:00 UTC
    scheduler.add_job(
        run_daily_signal_job,
        CronTrigger(hour=DAILY_JOB_HOUR_UTC, minute=0, timezone="UTC"),
        id="daily_signal_job",
        replace_existing=True,
    )

    # Exit check every 15 minutes
    scheduler.add_job(
        run_exit_trade_job,
        IntervalTrigger(minutes=EXIT_CHECK_INTERVAL_MINUTES),
        id="exit_trade_job",
        replace_existing=True,
    )

    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(
    title="Paper Trading System",
    description="Paper trading validation system for quantitative strategies",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router, prefix="/api", tags=["dashboard"])
app.include_router(signals.router, prefix="/api", tags=["signals"])
app.include_router(trades.router, prefix="/api", tags=["trades"])
app.include_router(performance.router, prefix="/api", tags=["performance"])
app.include_router(system_health.router, prefix="/api", tags=["system"])
app.include_router(config.router,      prefix="/api", tags=["config"])
app.include_router(alerts_api.router,       prefix="/api", tags=["alerts"])
app.include_router(forward_log.router,      prefix="/api", tags=["forward-log"])
app.include_router(portfolio_risk.router,   prefix="/api", tags=["risk"])
app.include_router(strategy_pipeline.router, prefix="/api", tags=["pipeline"])
app.include_router(data_quality.router,     prefix="/api", tags=["data-quality"])
app.include_router(experiments.router,      prefix="/api", tags=["experiments"])
app.include_router(kill_switch_api.router,  prefix="/api", tags=["risk"])
app.include_router(audit_api.router,        prefix="/api", tags=["audit"])


# Manual trigger endpoints for testing
@app.post("/api/jobs/run-daily-signal", tags=["jobs"])
async def trigger_daily_signal():
    result = await run_daily_signal_job()
    return result


@app.post("/api/jobs/check-exits", tags=["jobs"])
async def trigger_exit_check():
    result = await run_exit_trade_job()
    return result


@app.get("/api/health", tags=["health"])
def health():
    return {"status": "ok"}
