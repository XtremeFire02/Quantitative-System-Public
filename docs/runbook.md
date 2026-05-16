# Operational Runbook — Quantitative Paper Trading System

_Last updated: 2026-05-14_

> **Platform:** Windows 11. All commands are given in **PowerShell** first,
> with a Unix/bash equivalent where they differ. Docker commands are
> identical on both platforms.

---

## Severity Reference

Before any incident section, decide the severity first:

| Severity | Condition | Immediate action |
|----------|-----------|-----------------|
| **S1 — Halt** | Open trade entering incorrect direction; kill switch logic bypassed; DB corrupted | Arm kill switch NOW, then investigate |
| **S2 — Degrade** | Data feed down; scheduler missed; portfolio risk block | Arm kill switch if next signal window is < 2h away, otherwise investigate first |
| **S3 — Monitor** | Single stale data point; alert email not sending; frontend unreachable | Investigate at next convenient time; no trade impact |

When in doubt, arm the kill switch first. It is a no-op if the next signal window is not imminent and costs nothing to disarm.

---

## 1. Starting the System

### Local (development)

```powershell
# Terminal 1 — Backend (port 8000)
cd paper_trading\backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

```powershell
# Terminal 2 — Frontend (port 3000)
cd paper_trading\frontend
npm install; npm start
```

Open `http://localhost:3000` for the dashboard.  
Open `http://localhost:8000/docs` for the interactive API.

### Docker (production-equivalent)

```powershell
cd paper_trading
Copy-Item .env.example .env   # then fill in ALERT_* values if email is wanted
docker compose up --build -d

# Verify both containers are healthy
docker compose ps
docker compose logs backend --tail 50
docker compose logs frontend --tail 20
```

Backend: `http://localhost:8000`  
Frontend: `http://localhost:80`

**Verify startup:** `GET /api/health` should return `{"status": "ok"}` within 10 seconds.

---

## 2. Stopping the System

```powershell
# Docker — keeps the SQLite volume (data preserved)
docker compose down

# Docker — also removes the volume (DESTROYS ALL DATA)
docker compose down -v

# Local — Ctrl+C in each terminal
```

---

## 3. Normal Daily Operations

The system is autonomous after startup. No daily manual action is required.

| Job | Schedule | What it does |
|-----|----------|-------------|
| `daily_signal_job` | 00:00 UTC | Evaluates all active strategies, opens trades if signal fires |
| `exit_trade_job` | Every 15 min | Closes any trade whose 24h hold period has expired |

**Monitoring:**  
- Dashboard: `http://localhost:3000`  
- Alerts page: `/alerts`  
- System health: `GET /api/health`

**Force a manual run** (e.g. if scheduler missed):

```powershell
Invoke-RestMethod -Method POST http://localhost:8000/api/jobs/run-daily-signal
Invoke-RestMethod -Method POST http://localhost:8000/api/jobs/check-exits
```

```bash
# bash equivalent
curl -X POST http://localhost:8000/api/jobs/run-daily-signal
curl -X POST http://localhost:8000/api/jobs/check-exits
```

---

## 4. Kill Switch

Immediately halts **all new trade entries** system-wide. Open trades continue to their planned 24h exit unaffected. State survives process restarts (persisted in DB).

### Arm (halt new entries)

```powershell
Invoke-RestMethod -Method POST http://localhost:8000/api/risk/kill-switch `
    -ContentType "application/json" `
    -Body '{"active": true, "reason": "suspicious market conditions"}'
```

```bash
curl -X POST http://localhost:8000/api/risk/kill-switch \
     -H "Content-Type: application/json" \
     -d '{"active": true, "reason": "suspicious market conditions"}'
```

Or use the dashboard at `/risk` → Kill Switch toggle.

### Disarm (resume trading)

```powershell
Invoke-RestMethod -Method POST http://localhost:8000/api/risk/kill-switch `
    -ContentType "application/json" `
    -Body '{"active": false, "reason": "conditions normalised"}'
```

```bash
curl -X POST http://localhost:8000/api/risk/kill-switch \
     -H "Content-Type: application/json" \
     -d '{"active": false, "reason": "conditions normalised"}'
```

### Verify state

```powershell
Invoke-RestMethod http://localhost:8000/api/risk/kill-switch
```

Expected response when armed: `{"active": true, "checked_at": "..."}`.  
Expected response when disarmed: `{"active": false, "checked_at": "..."}`.

---

## 5. Incident Response

---

### 5.1 Data Staleness Alert  *(Severity: S2)*

**Symptom:** `data_failed` alert on the Alerts page, or `GET /api/system/data-quality` shows a check with `"status": "error"`.

**Triage:**

```powershell
# 1. Check backend logs for the specific error
docker compose logs backend --tail 100 | Select-String "ERROR|DVOL|Deribit|Binance"

# 2. Test Deribit connectivity
Invoke-RestMethod "https://www.deribit.com/api/v2/public/get_index?currency=BTC"

# 3. Test Binance connectivity
Invoke-RestMethod "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"
```

```bash
# bash equivalents
docker compose logs backend --tail 100 | grep -E "ERROR|DVOL|Deribit|Binance"
curl "https://www.deribit.com/api/v2/public/get_index?currency=BTC"
curl "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"
```

**Resolution:**

| Situation | Action |
|-----------|--------|
| API is up, error was transient | Restart backend: `docker compose restart backend` |
| API is down | Arm kill switch if signal window < 2h away; wait for recovery |
| DVOL stale > 2h | `DATA_STALE_MINUTES` gate blocks new entries automatically — no action needed |
| DVOL stale > 24h | Arm kill switch; investigate Deribit API status |

**Verify recovery:**
```powershell
Invoke-RestMethod "http://localhost:8000/api/system/data-quality" |
    Select-Object -ExpandProperty checks |
    Where-Object { $_.status -ne "ok" }
```
Recovery confirmed when the above returns nothing (all checks green).

---

### 5.2 Portfolio Risk Block  *(Severity: S3)*

**Symptom:** `risk_blocked` alert — "Portfolio limit reached", daily loss limit, or strategy drawdown limit.

**Triage:**
```powershell
Invoke-RestMethod http://localhost:8000/api/risk/state   # current exposure
Invoke-RestMethod http://localhost:8000/api/risk/limits  # configured limits
```

**Resolution:**

| Limit triggered | Action | Auto-reset? |
|-----------------|--------|-------------|
| Max open positions (≤ 3) | Wait for a trade to close | Yes — on next exit |
| Same-market cap (≤ 2) | Wait for a trade to close | Yes — on next exit |
| Daily loss (≥ −500 bp) | Wait; can also arm kill switch | Yes — midnight UTC |
| Strategy drawdown (≥ −20%) | Consider setting strategy to `paused` | No — manual review |

**Verify recovery:**
```powershell
(Invoke-RestMethod http://localhost:8000/api/risk/state).open_positions
```
Should show fewer positions or confirm daily PnL has recovered above the limit.

---

### 5.3 Scheduler Missed Fire  *(Severity: S2 if within 2h of midnight UTC, else S3)*

**Symptom:** No new signal row for today on the Signals page; `scheduler_missed` alert.

**Triage:**
```powershell
docker compose logs backend --tail 100 | Select-String "daily_job|scheduler|ERROR"
```

```bash
docker compose logs backend --tail 100 | grep -E "daily_job|scheduler|ERROR"
```

**Resolution:**
1. Trigger manually:
```powershell
Invoke-RestMethod -Method POST http://localhost:8000/api/jobs/run-daily-signal
```
2. If exit job also stalled:
```powershell
Invoke-RestMethod -Method POST http://localhost:8000/api/jobs/check-exits
```
3. If scheduler keeps missing, restart the backend:
```powershell
docker compose restart backend
```

**Verify recovery:**
```powershell
# Confirm a signal row was written for today
Invoke-RestMethod http://localhost:8000/api/signals/latest
```
Response should show `"timestamp"` matching today's date (UTC).

---

### 5.4 Backend Won't Start  *(Severity: S1 if trades are open, else S2)*

**Symptom:** `docker compose ps` shows `unhealthy` or `Exit 1` for the backend container.

**Triage:**
```powershell
docker compose logs backend --tail 100
```

**Common causes and fixes:**

| Cause | How to identify | Fix |
|-------|----------------|-----|
| Port 8000 in use | Logs: "address already in use" | `netstat -ano \| findstr :8000` → kill the PID |
| DB file locked | Logs: "database is locked" | Stop all backend instances; restart |
| Missing dependency | Logs: `ModuleNotFoundError` | `docker compose build --no-cache backend` |
| Bad `.env` value | Logs: `ValueError` or `KeyError` | Check `.env` against `.env.example` |

```powershell
# Find and kill process holding port 8000
$pid = (netstat -ano | Select-String ":8000 ").ToString().Trim().Split()[-1]
if ($pid) { Stop-Process -Id $pid -Force }
```

**Verify recovery:**
```powershell
# Wait for healthy status (retry up to 30s)
$deadline = (Get-Date).AddSeconds(30)
do { Start-Sleep 2 } until (
    (docker compose ps --format json | ConvertFrom-Json).Health -eq "healthy" -or
    (Get-Date) -gt $deadline
)
Invoke-RestMethod http://localhost:8000/api/health
```
Expected: `{"status": "ok"}`.

---

### 5.5 Trade Opened with Wrong Parameters  *(Severity: S1)*

**Symptom:** A trade row shows unexpected side, strategy, or entry price — indicating a logic error.

**Immediate action:** Arm kill switch.

**Triage:**
```powershell
# View the last 10 audit events to trace the decision
Invoke-RestMethod "http://localhost:8000/api/audit?limit=10" |
    Select-Object -ExpandProperty events
```

```powershell
# Inspect the trade directly in SQLite
sqlite3 paper_trading\backend\paper_trading.db "SELECT * FROM trades ORDER BY id DESC LIMIT 3;"
```

**Resolution:**
1. Keep kill switch armed until root cause is identified.
2. Run parity tests — a failure here means the live rule drifted from research:
```powershell
python -m pytest tests/test_parity.py -v
```
3. Fix the offending code, re-run tests, then disarm.

**Verify recovery:** Parity tests all green; audit log shows normal decision flow on next signal evaluation.

---

## 6. Strategy Pipeline Operations

Promote or demote strategy status via the Pipeline page (`/pipeline`) or API:

```powershell
# Promote P3 from shadow to validated
$body = '{"status": "validated", "note": "3-month forward log passed review", "promoted_by": "manual"}'
Invoke-RestMethod -Method POST http://localhost:8000/api/strategies/P3_OIPD_DD/status `
    -ContentType "application/json" -Body $body

# Pause a strategy
$body = '{"status": "paused", "note": "drawdown limit hit — manual review pending"}'
Invoke-RestMethod -Method POST http://localhost:8000/api/strategies/N3_DVOL_LONG/status `
    -ContentType "application/json" -Body $body

# Kill a strategy
$body = '{"status": "killed", "note": "OOS Sharpe -0.44, p=1.000"}'
Invoke-RestMethod -Method POST http://localhost:8000/api/strategies/DU_SHORT/status `
    -ContentType "application/json" -Body $body
```

Valid statuses (in lifecycle order): `research → candidate → shadow → validated → paused → killed`

**Verify:** `GET /api/strategies/{name}` returns the new status.

---

## 7. Database Maintenance

The database is a single SQLite file at `paper_trading\backend\paper_trading.db`.

### Backup

```powershell
$date = Get-Date -Format "yyyyMMdd"
New-Item -ItemType Directory -Force backups | Out-Null
Copy-Item paper_trading\backend\paper_trading.db "backups\paper_trading_$date.db"
Write-Host "Backed up to backups\paper_trading_$date.db"
```

```bash
# bash equivalent
mkdir -p backups
cp paper_trading/backend/paper_trading.db "backups/paper_trading_$(date +%Y%m%d).db"
```

### View recent audit log

```powershell
Invoke-RestMethod "http://localhost:8000/api/audit?limit=50" |
    Select-Object -ExpandProperty events |
    Format-Table timestamp, component, event, -AutoSize
```

### Manual DB inspection

```powershell
sqlite3 paper_trading\backend\paper_trading.db
```

```sql
.tables
SELECT id, strategy_name, side, entry_price, status FROM trades ORDER BY id DESC LIMIT 5;
SELECT timestamp, component, message FROM system_logs
    WHERE component='kill_switch' ORDER BY id DESC LIMIT 10;
.quit
```

---

## 8. Running Tests

```powershell
# Root package tests (parity + unit) — run from repo root
python -m pytest tests/ -v

# Backend tests
cd paper_trading\backend
python -m pytest tests/ -v

# Type-check frontend
cd paper_trading\frontend
npx tsc --noEmit
```

**All tests must be green before disarming the kill switch after any S1 incident.**

---

## 9. P3 Shadow Strategy Review Gate

P3_OIPD_DD is in `shadow` status. Forward review is due **≥ 2026-08-14** (3 months from deployment on 2026-05-14).

### Review checklist

```powershell
# 1. Check forward log stats
Invoke-RestMethod http://localhost:8000/api/forward-log/p3 |
    Select-Object -ExpandProperty stats

# 2. Confirm no post-hoc parameter changes
Invoke-RestMethod "http://localhost:8000/api/experiments?strategy=P3_OIPD_DD"

# 3. Run parity tests
python -m pytest tests/test_parity.py -v
```

### Pass criteria (all must hold)

| Metric | Threshold |
|--------|-----------|
| Exclusive trades | ≥ 20 |
| Forward Sharpe | > 1.0 |
| Block-bootstrap p | ≤ 0.05 |
| Parity tests | All green |

### If review passes

```powershell
$body = '{"status": "validated", "note": "3-month forward review passed", "promoted_by": "manual"}'
Invoke-RestMethod -Method POST http://localhost:8000/api/strategies/P3_OIPD_DD/status `
    -ContentType "application/json" -Body $body
```

### If review fails

```powershell
# Set strategy to killed
$body = '{"status": "killed", "note": "forward review failed — state reason here"}'
Invoke-RestMethod -Method POST http://localhost:8000/api/strategies/P3_OIPD_DD/status `
    -ContentType "application/json" -Body $body

# Record verdict in experiment log
$body = '{"verdict": "failed", "notes": "forward Sharpe below threshold — state details"}'
Invoke-RestMethod -Method PATCH http://localhost:8000/api/experiments/p3_oipd_2026 `
    -ContentType "application/json" -Body $body
```

Move the research scripts from `research/active/p3/` to `research/killed/` and add an entry to `research/killed/README.md`.
