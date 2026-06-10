import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

SETTINGS_PATH = Path(os.environ.get("SETTINGS_DIR", ".")) / "settings.json"
DEFAULT_SETTINGS = {
    "accounts": [],
    "recipient_emails": [],
    "business_problems": [],
    "schedule_days": 7,
    "lookback_mode": "days",      # "days" | "custom"
    "lookback_days": 15,
    "lookback_start": None,       # ISO date "YYYY-MM-DD"; only used in custom mode
    "lookback_end": None,         # ISO date "YYYY-MM-DD"; only used in custom mode
    "monthly_two_month_report": False,  # extra fixed 60-day report on the 1st of every month
}

# Fixed window for the monthly 2-month deep-dive. Intentionally NOT derived
# from the user's lookback settings — that's the whole point of this toggle.
MONTHLY_JOB_ID = "monthly_two_month_report"
MONTHLY_LOOKBACK_DAYS = 60


def load_settings() -> dict:
    """Read settings.json, filling in defaults for any newly-added fields."""
    if SETTINGS_PATH.exists():
        data = json.loads(SETTINGS_PATH.read_text())
        # Forward-compat: pre-existing settings won't have business_problems
        for k, v in DEFAULT_SETTINGS.items():
            data.setdefault(k, v)
        return data
    return DEFAULT_SETTINGS.copy()

_run_state: dict = {
    "running": False,
    "last_run": None,
    "last_error": None,
    "status": "idle",
}
_run_lock = threading.Lock()
_scheduler = None


# ── Settings helpers ──────────────────────────────────────────────────────────


def save_settings(data: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2))


# ── Pipeline ──────────────────────────────────────────────────────────────────

def _resolve_window(settings: dict) -> tuple[str | None, str | None, str]:
    """Compute (since_iso, until_iso, human_label) from the lookback settings.

    `since_iso` / `until_iso` are YYYY-MM-DD bounds passed to the scraper.
    `human_label` is a short phrase like "Last 15 days" or "May 1 – Jun 10, 2026"
    that the analyzer puts into the report's scrape_period field.
    """
    mode = settings.get("lookback_mode", "days")
    if mode == "custom":
        start = (settings.get("lookback_start") or "").strip() or None
        end = (settings.get("lookback_end") or "").strip() or None
        try:
            label_parts = []
            if start:
                label_parts.append(datetime.fromisoformat(start).strftime("%b %-d, %Y"))
            if end:
                label_parts.append(datetime.fromisoformat(end).strftime("%b %-d, %Y"))
            label = " – ".join(label_parts) if label_parts else "Custom range"
        except ValueError:
            label = "Custom range"
        return start, end, label

    days = int(settings.get("lookback_days", 15) or 15)
    days = max(1, min(180, days))
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=days)
    return since.date().isoformat(), None, f"Last {days} days"


def _execute_pipeline(window_override: tuple[str | None, str | None, str] | None = None) -> None:
    """Run the full scrape → analyse → email cycle.

    If `window_override` is provided it bypasses the user's lookback settings —
    this is how the monthly 2-month deep-dive forces its own fixed window.
    """
    load_dotenv(override=True)
    import analyzer
    import emailer
    import scraper

    settings = load_settings()
    accounts = settings.get("accounts", [])
    if not accounts:
        raise ValueError("No Instagram accounts configured. Add accounts in the dashboard first.")

    emails = settings.get("recipient_emails", [])
    if emails:
        os.environ["RECIPIENT_EMAILS"] = ",".join(emails)
    os.environ["INSTAGRAM_ACCOUNTS"] = ",".join(accounts)

    business_problems = settings.get("business_problems", [])
    since_iso, until_iso, period_label = (
        window_override if window_override is not None else _resolve_window(settings)
    )

    scraped = scraper.scrape_accounts(accounts, since_iso=since_iso, until_iso=until_iso)
    report = analyzer.analyse(
        scraped,
        business_problems=business_problems,
        scrape_period=period_label,
    )
    emailer.send_report(report)


def run_pipeline_background(window_override: tuple[str | None, str | None, str] | None = None) -> None:
    with _run_lock:
        if _run_state["running"]:
            return
        _run_state["running"] = True
        _run_state["status"] = "running"
        _run_state["last_error"] = None

    logger.info("Pipeline started (background)")
    try:
        _execute_pipeline(window_override=window_override)
        _run_state["last_run"] = datetime.now().isoformat()
        _run_state["status"] = "success"
        logger.info("Pipeline completed successfully")
    except Exception as exc:
        _run_state["last_error"] = str(exc)
        _run_state["status"] = "error"
        logger.error(f"Pipeline failed: {exc}")
    finally:
        _run_state["running"] = False


def _run_monthly_two_month_report() -> None:
    """Cron entrypoint for the monthly 2-month deep-dive. Forces a 60-day window
    regardless of the user's slider settings."""
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=MONTHLY_LOOKBACK_DAYS)
    run_pipeline_background(window_override=(since.date().isoformat(), None, "Last 2 months"))


# ── Scheduler ─────────────────────────────────────────────────────────────────

def _start_scheduler() -> None:
    global _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.warning("APScheduler not available — scheduled runs disabled")
        return

    settings = load_settings()
    days = settings.get("schedule_days", 7)

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        run_pipeline_background,
        trigger="interval",
        days=days,
        id="trend_report",
    )
    _scheduler.start()
    logger.info(f"Scheduler started: every {days} day(s)")

    # Apply monthly deep-dive job from persisted settings on boot.
    _apply_monthly_job(bool(settings.get("monthly_two_month_report")))


def _reschedule(days: int) -> None:
    if _scheduler is None:
        return
    _scheduler.reschedule_job("trend_report", trigger="interval", days=days)
    logger.info(f"Scheduler updated to every {days} day(s)")


def _apply_monthly_job(enabled: bool) -> None:
    """Add or remove the monthly 2-month deep-dive cron job to match the toggle."""
    if _scheduler is None:
        return
    try:
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        return

    existing = _scheduler.get_job(MONTHLY_JOB_ID)
    if enabled and existing is None:
        _scheduler.add_job(
            _run_monthly_two_month_report,
            trigger=CronTrigger(day=1, hour=8, minute=0),  # 1st of every month, 08:00 server time (UTC on Railway)
            id=MONTHLY_JOB_ID,
        )
        logger.info("Monthly 2-month deep-dive: ENABLED (1st of every month, 08:00 UTC)")
    elif not enabled and existing is not None:
        _scheduler.remove_job(MONTHLY_JOB_ID)
        logger.info("Monthly 2-month deep-dive: DISABLED")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    _start_scheduler()
    yield
    if _scheduler:
        _scheduler.shutdown(wait=False)


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Instagram Trend Agent", lifespan=lifespan)

frontend_url = os.getenv("FRONTEND_URL", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url] if frontend_url != "*" else ["*"],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)


# ── Routes ────────────────────────────────────────────────────────────────────

class SettingsPayload(BaseModel):
    accounts: list[str]
    recipient_emails: list[str]
    business_problems: list[str] = []
    schedule_days: int
    lookback_mode: str = "days"
    lookback_days: int = 15
    lookback_start: str | None = None
    lookback_end: str | None = None
    monthly_two_month_report: bool = False


def _validate_iso_date(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return None


@app.get("/api/settings")
def get_settings():
    return load_settings()


@app.post("/api/settings")
def update_settings(payload: SettingsPayload):
    mode = payload.lookback_mode if payload.lookback_mode in ("days", "custom") else "days"
    data = {
        "accounts": [a.strip().lstrip("@").lower() for a in payload.accounts if a.strip()],
        "recipient_emails": [e.strip() for e in payload.recipient_emails if e.strip()],
        "business_problems": [p.strip() for p in payload.business_problems if p.strip()][:3],
        "schedule_days": max(1, min(90, payload.schedule_days)),
        "lookback_mode": mode,
        "lookback_days": max(1, min(180, payload.lookback_days)),
        "lookback_start": _validate_iso_date(payload.lookback_start),
        "lookback_end": _validate_iso_date(payload.lookback_end),
        "monthly_two_month_report": bool(payload.monthly_two_month_report),
    }
    save_settings(data)
    _reschedule(data["schedule_days"])
    _apply_monthly_job(data["monthly_two_month_report"])
    return {"ok": True, "settings": data}


@app.get("/api/status")
def get_status():
    return _run_state


@app.post("/api/run")
def trigger_run(background_tasks: BackgroundTasks):
    if _run_state["running"]:
        raise HTTPException(status_code=409, detail="A pipeline run is already in progress.")
    background_tasks.add_task(run_pipeline_background)
    return {"ok": True, "message": "Pipeline started in background."}


@app.get("/api/health")
def health():
    return {"ok": True}
