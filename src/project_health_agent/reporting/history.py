"""Append-only run history so the monthly synthesis can detect genuine
week-over-week movement rather than only cross-project patterns at a single
point in time.

Each weekly run appends one JSON line per project to `outputs/history.jsonl`.
Nothing here is simulated or backfilled — trend detection is only as good as
the number of real runs that have accumulated, and the monthly synthesis says
so explicitly when history is thin.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from pydantic import BaseModel

from project_health_agent.config import Settings
from project_health_agent.reporting.weekly_report import WeeklyReport


class HistoryEntry(BaseModel):
    run_date: date
    project_name: str
    rag_overall: str
    schedule_variance_days: int | None = None
    milestone_completion_rate: float | None = None
    sentiment_score: float | None = None
    open_blockers: int


def _history_path(settings: Settings) -> Path:
    settings.reports_output_dir.mkdir(parents=True, exist_ok=True)
    return settings.reports_output_dir / "history.jsonl"


def append_history(reports: list[WeeklyReport], settings: Settings) -> None:
    path = _history_path(settings)
    with path.open("a", encoding="utf-8") as fh:
        for r in reports:
            entry = HistoryEntry(
                run_date=r.run_date,
                project_name=r.project_name,
                rag_overall=r.rag.overall.value,
                schedule_variance_days=r.signals.schedule.worst_task_variance_days,
                milestone_completion_rate=r.signals.milestones.milestone_completion_rate,
                sentiment_score=r.signals.sentiment.sentiment_score,
                open_blockers=r.signals.blockers.open_blocker_count + r.signals.blockers.on_hold_task_count,
            )
            fh.write(entry.model_dump_json() + "\n")


def load_history(settings: Settings) -> list[HistoryEntry]:
    path = _history_path(settings)
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(HistoryEntry.model_validate_json(line))
    return entries
