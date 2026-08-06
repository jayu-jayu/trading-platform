"""
APScheduler job — runs the scanner every SCAN_INTERVAL_MINUTES during NSE
cash market hours (Mon-Fri, 09:15-15:30 IST). In-process, no Redis needed
at this scale.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from app.config import settings
from app.services.scanner import run_full_scan

IST = pytz.timezone("Asia/Kolkata")
scheduler = AsyncIOScheduler(timezone=IST)


def start_scheduler():
    scheduler.add_job(
        run_full_scan,
        trigger=CronTrigger(day_of_week="mon-fri", hour="9-15", minute=f"*/{settings.SCAN_INTERVAL_MINUTES}", timezone=IST),
        id="market_scanner",
        replace_existing=True,
        misfire_grace_time=60,
    )
    scheduler.start()


def stop_scheduler():
    scheduler.shutdown(wait=False)
