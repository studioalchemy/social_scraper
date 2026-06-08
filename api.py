import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime
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

SETTINGS_PATH = Path("settings.json")
DEFAULT_SETTINGS = {"accounts": [], "recipient_emails": [], "schedule_days": 7}

_run_state: dict = {
    "running": False,
    "last_run": None,
    "last_error": None,
    "status": "idle",
}
_run_lock = threading.Lock()
_scheduler = None


# ── Settings helpers ──────────────────────────────────────────────────────────

def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text())
    return DEFAULT_SETTINGS.copy()


def save_settings(data: dict) -> None:
    SETTINGS_PATH.write_text(json.dumps(data, indent=2))


# ── Pipeline ──────────────────────────────────────────────────────────────────

def _execute_pipeline() -> None:
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

    scraped = scraper.scrape_accounts(accounts)
    report = analyzer.analyse(scraped)
    emailer.send_report(report)


def run_pipeline_background() -> None:
    with _run_lock:
        if _run_state["running"]:
            return
        _run_state["running"] = True
        _run_state["status"] = "running"
        _run_state["last_error"] = None

    logger.info("Pipeline started (background)")
    try:
        _execute_pipeline()
        _run_state["last_run"] = datetime.now().isoformat()
        _run_state["status"] = "success"
        logger.info("Pipeline completed successfully")
    except Exception as exc:
        _run_state["last_error"] = str(exc)
        _run_state["status"] = "error"
        logger.error(f"Pipeline failed: {exc}")
    finally:
        _run_state["running"] = False


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


def _reschedule(days: int) -> None:
    if _scheduler is None:
        return
    _scheduler.reschedule_job("trend_report", trigger="interval", days=days)
    logger.info(f"Scheduler updated to every {days} day(s)")


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
    schedule_days: int


@app.get("/api/settings")
def get_settings():
    return load_settings()


@app.post("/api/settings")
def update_settings(payload: SettingsPayload):
    data = {
        "accounts": [a.strip().lstrip("@").lower() for a in payload.accounts if a.strip()],
        "recipient_emails": [e.strip() for e in payload.recipient_emails if e.strip()],
        "schedule_days": max(1, min(90, payload.schedule_days)),
    }
    save_settings(data)
    _reschedule(data["schedule_days"])
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
