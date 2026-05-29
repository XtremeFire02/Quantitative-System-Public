"""Alert system for paper trading — stores alerts in DB, optionally emails."""
import json
import logging
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

import httpx
from sqlalchemy.orm import Session

from app.database import Alert, SessionLocal

logger = logging.getLogger(__name__)

# Optional email config from environment variables
_SMTP_HOST = os.getenv("ALERT_SMTP_HOST", "")
_SMTP_PORT = int(os.getenv("ALERT_SMTP_PORT", "587"))
_SMTP_USER = os.getenv("ALERT_SMTP_USER", "")
_SMTP_PASS = os.getenv("ALERT_SMTP_PASS", "")
_ALERT_TO   = os.getenv("ALERT_EMAIL_TO", "")

# Optional Telegram config from environment variables
_TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")


def fire(
    category: str,
    title: str,
    body: str,
    db: Session | None = None,
    strategy: str | None = None,
    market: str | None = None,
    exposure: dict | None = None,
    action_taken: str | None = None,
) -> None:
    """Persist an alert and optionally send an email.

    category: signal_fired | trade_closed | data_failed | scheduler_missed | risk_blocked
    """
    _store(category, title, body, db, strategy=strategy, market=market,
           exposure=exposure, action_taken=action_taken)
    _maybe_email(title, body)
    _maybe_telegram(title, body)


def fire_p3_signal(
    market: str,
    dp: float,
    doi: float,
    dvol: float,
    db: Session | None = None,
) -> None:
    title = f"P3 DD signal fired — {market}"
    body = (
        f"Market: {market}\n"
        f"Price change 24h: {dp:+.2%}\n"
        f"OI change 24h:    {doi:+.2%}\n"
        f"DVOL:             {dvol:.1f}\n"
        f"Entry side:       long\n"
        f"Planned hold:     24h\n"
        f"Time (UTC):       {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    )
    fire("signal_fired", title, body, db, strategy="P3_OIPD_DD", market=market,
         action_taken="trade_opened")


def fire_trade_closed(
    trade_id: int,
    strategy: str,
    net_pnl_bp: float,
    db: Session | None = None,
) -> None:
    direction = "+" if net_pnl_bp >= 0 else ""
    title = f"{strategy} trade #{trade_id} closed — {direction}{net_pnl_bp:.1f} bp"
    body = (
        f"Strategy:  {strategy}\n"
        f"Trade ID:  {trade_id}\n"
        f"Net PnL:   {direction}{net_pnl_bp:.1f} bp\n"
        f"Time (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    )
    fire("trade_closed", title, body, db)


def fire_data_failed(component: str, error: str, db: Session | None = None) -> None:
    title = f"Data fetch failed — {component}"
    body = f"Component: {component}\nError: {error}"
    fire("data_failed", title, body, db)


def fire_scheduler_missed(job_id: str, db: Session | None = None) -> None:
    title = f"Scheduler missed daily evaluation — {job_id}"
    body = (
        f"Job:       {job_id}\n"
        f"Time (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}\n"
        "Check that the process is running and 00:00 UTC cron fired."
    )
    fire("scheduler_missed", title, body, db)


def fire_risk_blocked(
    strategy: str,
    market: str,
    reason: str,
    db: Session | None = None,
) -> None:
    title = f"Portfolio risk blocked {strategy} entry"
    body = (
        f"Strategy:    {strategy}\n"
        f"Market:      {market}\n"
        f"Reason:      {reason}\n"
        f"Action:      No trade opened\n"
        f"Time (UTC):  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    )
    fire("risk_blocked", title, body, db, strategy=strategy, market=market,
         action_taken="no_trade_portfolio_limit")


def fire_oi_stale(last_ts: datetime, db: Session | None = None) -> None:
    age_min = int((datetime.now(timezone.utc) - last_ts.replace(tzinfo=timezone.utc)).total_seconds() // 60)
    title = "OI data stale"
    body = (
        f"Last OI timestamp: {last_ts.isoformat()}\n"
        f"Age: {age_min} minutes\n"
        "P3 evaluator may be using stale open interest data."
    )
    fire("data_failed", title, body, db)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _store(
    category: str,
    title: str,
    body: str,
    db: Session | None,
    strategy: str | None = None,
    market: str | None = None,
    exposure: dict | None = None,
    action_taken: str | None = None,
) -> None:
    own_db = db is None
    if own_db:
        db = SessionLocal()
    try:
        db.add(Alert(
            timestamp=datetime.now(timezone.utc),
            category=category,
            title=title,
            body=body,
            strategy=strategy,
            market=market,
            exposure=json.dumps(exposure) if exposure else None,
            action_taken=action_taken,
            is_read=False,
        ))
        db.commit()
    except Exception as exc:
        logger.error("Failed to store alert: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        if own_db:
            db.close()


def _maybe_telegram(title: str, body: str) -> None:
    if not _TELEGRAM_BOT_TOKEN or not _TELEGRAM_CHAT_ID:
        return
    try:
        text = f"<b>[Paper Trading] {title}</b>\n\n{body}"
        url = f"https://api.telegram.org/bot{_TELEGRAM_BOT_TOKEN}/sendMessage"
        with httpx.Client(timeout=5.0) as client:
            client.post(url, json={
                "chat_id": _TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
            })
    except Exception as exc:
        logger.warning("Telegram alert failed (non-fatal): %s", exc)


def _maybe_email(title: str, body: str) -> None:
    if not all([_SMTP_HOST, _SMTP_USER, _SMTP_PASS, _ALERT_TO]):
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = f"[Paper Trading] {title}"
        msg["From"] = _SMTP_USER
        msg["To"] = _ALERT_TO
        msg.set_content(body)
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT) as s:
            s.starttls()
            s.login(_SMTP_USER, _SMTP_PASS)
            s.send_message(msg)
    except Exception as exc:
        logger.warning("Email alert failed (non-fatal): %s", exc)
