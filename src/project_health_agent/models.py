"""Normalized, tool/vendor-agnostic representation of a project plan.

The raw Smartsheet-style exports vary in column order and sometimes in column
presence between projects (see data/sample_plans/*.xlsx). Everything downstream
(signals, RAG engine, LLM prompts, reporting) works against these models, never
against raw spreadsheet rows/columns, so the analysis logic is decoupled from
any one export's quirks.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    NOT_STARTED = "Not Started"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"
    ON_HOLD = "On Hold"
    UNKNOWN = "Unknown"


class Task(BaseModel):
    row_number: int
    name: str
    level: int | None = None
    is_milestone_or_phase: bool = False
    phase_name: str | None = None
    status: TaskStatus = TaskStatus.UNKNOWN
    percent_complete: float | None = None  # 0..1
    start_date: date | None = None
    end_date: date | None = None
    baseline_start: date | None = None
    baseline_finish: date | None = None
    variance_days: int | None = None  # +ve = late vs baseline
    duration_days: float | None = None
    priority: str | None = None
    critical: bool = False
    on_hold: bool = False
    not_applicable: bool = False
    owner: str | None = None
    assigned_to: str | None = None
    area: str | None = None
    status_comment: str | None = None
    rag_raw: str | None = None  # RAG value as authored in the sheet, if present
    total_float: float | None = None
    at_risk: str | None = None
    predecessors: str | None = None


class Comment(BaseModel):
    row_reference: str | None = None
    text: str
    author: str | None = None
    timestamp: str | None = None


class ProjectSummary(BaseModel):
    project_name: str | None = None
    project_manager: str | None = None
    project_start_date: date | None = None
    project_end_date: date | None = None
    not_started_count: int | None = None
    in_progress_count: int | None = None
    completed_count: int | None = None
    on_hold_count: int | None = None
    at_risk_label: str | None = None  # e.g. "High" as authored by the PM
    project_stage: str | None = None
    percent_complete: float | None = None
    schedule_health_label: str | None = None  # PM-authored Green/Yellow/Red
    as_of_date: date | None = None
    duration_days: float | None = None
    project_status: str | None = None


class DataQualityNote(BaseModel):
    field: str
    issue: str
    count: int = 1


class ProjectPlan(BaseModel):
    """Fully parsed, normalized plan for a single project, ready for analysis."""

    source_file: str
    sheet_name: str
    summary: ProjectSummary
    tasks: list[Task] = Field(default_factory=list)
    comments: list[Comment] = Field(default_factory=list)
    data_quality_notes: list[DataQualityNote] = Field(default_factory=list)

    @property
    def project_name(self) -> str:
        return self.summary.project_name or self.sheet_name
