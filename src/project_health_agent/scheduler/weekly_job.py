"""Bonus: run the weekly job on a recurring schedule using APScheduler.

This is a thin wrapper — all the real logic lives in reporting/weekly_report.py
and cli.py. Cadence (day/time) is read from the environment so it's not
hardcoded; sensible defaults match a typical Monday-morning PM status cadence.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from project_health_agent.cli import run_weekly_job

logger = logging.getLogger(__name__)


def start_weekly_scheduler(day_of_week: str = "mon", hour: int = 7, minute: int = 0) -> None:
    scheduler = BlockingScheduler()
    trigger = CronTrigger(day_of_week=day_of_week, hour=hour, minute=minute)
    scheduler.add_job(run_weekly_job, trigger=trigger, id="weekly_project_health_report")
    logger.info("Weekly project health job scheduled: %s at %02d:%02d", day_of_week, hour, minute)
    scheduler.start()
