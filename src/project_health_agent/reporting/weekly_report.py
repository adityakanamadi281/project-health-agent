"""Ties ingestion -> signals -> RAG -> narrative into one per-project weekly report."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import BaseModel

from project_health_agent.analysis.rag_engine import RAGResult, determine_rag
from project_health_agent.analysis.signals import ProjectSignals, compute_signals
from project_health_agent.config import Settings
from project_health_agent.ingestion.excel_loader import load_project_plan
from project_health_agent.llm.fireworks_client import FireworksClient
from project_health_agent.llm.narrative import generate_narrative
from project_health_agent.models import ProjectPlan


class WeeklyReport(BaseModel):
    run_date: date
    source_file: str
    plan: ProjectPlan
    signals: ProjectSignals
    rag: RAGResult
    narrative: str
    narrative_source: str  # "llm" | "template-fallback"

    @property
    def project_name(self) -> str:
        return self.plan.project_name


def generate_weekly_report(
    source_path: str | Path,
    settings: Settings,
    client: FireworksClient,
    run_date: date | None = None,
) -> WeeklyReport:
    run_date = run_date or date.today()
    plan = load_project_plan(source_path)
    signals = compute_signals(plan, settings, as_of=run_date)
    rag = determine_rag(signals, settings, pm_label=plan.summary.schedule_health_label)
    narrative, was_llm = generate_narrative(rag, client)

    return WeeklyReport(
        run_date=run_date,
        source_file=plan.source_file,
        plan=plan,
        signals=signals,
        rag=rag,
        narrative=narrative,
        narrative_source="llm" if was_llm else "template-fallback",
    )


def render_markdown(report: WeeklyReport) -> str:
    rag = report.rag
    lines: list[str] = []
    lines.append(f"# Weekly Health Report — {report.project_name}")
    lines.append("")
    lines.append(f"**Run date:** {report.run_date.isoformat()}  ")
    lines.append(f"**Source file:** {report.source_file}  ")
    lines.append(f"**Overall RAG status:** **{rag.overall.value.upper()}**  ")
    lines.append(f"**Narrative source:** {report.narrative_source}")
    lines.append("")
    lines.append("## Plain-English Summary")
    lines.append("")
    lines.append(report.narrative)
    lines.append("")
    lines.append("## Dimension Breakdown")
    lines.append("")
    lines.append("| Dimension | RAG | Key reasons |")
    lines.append("|---|---|---|")
    for d in rag.dimensions:
        lines.append(f"| {d.name} | {d.rag.value} | {'; '.join(d.reasons)} |")
    lines.append("")
    if rag.perception_gap:
        lines.append("## Perception Gap")
        lines.append("")
        lines.append(rag.perception_gap)
        lines.append("")
    if rag.caveats:
        lines.append("## Data Quality Caveats")
        lines.append("")
        for c in rag.caveats:
            lines.append(f"- {c}")
        lines.append("")
    if report.plan.data_quality_notes:
        lines.append("## Ingestion Notes (raw data issues auto-handled)")
        lines.append("")
        for n in report.plan.data_quality_notes:
            lines.append(f"- `{n.field}`: {n.issue} ({n.count} occurrence(s))")
        lines.append("")
    lines.append("## Key Signals")
    lines.append("")
    s = report.signals
    lines.append(f"- Schedule variance (worst task): {s.schedule.worst_task_variance_days} days"
                 f" ({s.schedule.worst_task_name or 'n/a'})")
    lines.append(f"- Overdue open tasks: {s.schedule.overdue_incomplete_count}"
                 f" (critical path: {s.schedule.critical_overdue_count})")
    if s.milestones.milestone_completion_rate is not None:
        lines.append(f"- Milestone completion (of those due): {s.milestones.milestone_completion_rate:.0%}")
    lines.append(f"- Open blockers / on-hold items: {s.blockers.open_blocker_count + s.blockers.on_hold_task_count}")
    if s.sentiment.sentiment_score is not None:
        lines.append(f"- Stakeholder sentiment score: {s.sentiment.sentiment_score:+.2f}")
    if s.completion.reported_percent_complete is not None:
        lines.append(f"- PM-reported % complete: {s.completion.reported_percent_complete:.0%}")
    if s.completion.computed_percent_complete is not None:
        lines.append(f"- Task-derived % complete: {s.completion.computed_percent_complete:.0%}")
    lines.append("")
    return "\n".join(lines)


def save_weekly_report(report: WeeklyReport, settings: Settings) -> tuple[Path, Path]:
    out_dir = settings.reports_output_dir / "weekly" / report.run_date.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = report.project_name.replace("/", "-").replace(" ", "_")

    md_path = out_dir / f"{stem}.md"
    md_path.write_text(render_markdown(report), encoding="utf-8")

    json_path = out_dir / f"{stem}.json"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    return md_path, json_path
