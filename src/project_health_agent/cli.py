"""Command-line entrypoint for the Project Health Reporting Agent.

    uv run project-health run-weekly
    uv run project-health run-monthly
    uv run project-health schedule-weekly

See README.md for the full walkthrough.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from project_health_agent.config import get_settings
from project_health_agent.llm.fireworks_client import FireworksClient
from project_health_agent.presentation.deck_builder import build_monthly_deck
from project_health_agent.reporting.history import append_history
from project_health_agent.reporting.monthly_synthesis import build_monthly_synthesis
from project_health_agent.reporting.weekly_report import (
    WeeklyReport,
    generate_weekly_report,
    save_weekly_report,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = typer.Typer(help="Zycus Professional Services — Project Health Reporting Agent")
console = Console()


def _discover_plans(input_dir: Path) -> list[Path]:
    files = sorted(p for p in input_dir.glob("*.xlsx") if not p.name.startswith("~$"))
    if not files:
        raise typer.BadParameter(f"No .xlsx project plans found in {input_dir}")
    return files


def _run_weekly(input_dir: Path, run_date: date) -> list[WeeklyReport]:
    settings = get_settings()
    client = FireworksClient(settings)
    if not client.available:
        console.print(
            "[yellow]FIREWORKS_API_KEY not set — narratives will use the deterministic "
            "template fallback instead of LLM-generated prose.[/yellow]"
        )

    reports: list[WeeklyReport] = []
    table = Table(title=f"Weekly Project Health — {run_date.isoformat()}")
    table.add_column("Project")
    table.add_column("RAG")
    table.add_column("Narrative source")
    table.add_column("Report path")

    for plan_path in _discover_plans(input_dir):
        try:
            report = generate_weekly_report(plan_path, settings, client, run_date=run_date)
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Failed to process {plan_path.name}: {exc}[/red]")
            logger.exception("Failed to process %s", plan_path)
            continue
        md_path, _ = save_weekly_report(report, settings)
        color = {"Green": "green", "Amber": "yellow", "Red": "red"}[report.rag.overall.value]
        table.add_row(report.project_name, f"[{color}]{report.rag.overall.value}[/{color}]",
                      report.narrative_source, str(md_path))
        reports.append(report)

    append_history(reports, settings)
    console.print(table)
    return reports


@app.command("run-weekly")
def run_weekly(
    input_dir: Path = typer.Option(None, help="Directory of .xlsx project plans (defaults to DATA_INPUT_DIR)"),
    run_date: str = typer.Option(None, help="Override run date as YYYY-MM-DD (defaults to today)"),
) -> None:
    """Read every project plan in the input directory and emit a weekly RAG report for each."""
    settings = get_settings()
    resolved_dir = input_dir or settings.data_input_dir
    resolved_date = datetime.strptime(run_date, "%Y-%m-%d").date() if run_date else date.today()
    _run_weekly(resolved_dir, resolved_date)


def run_weekly_job() -> None:
    """Entry point used by the APScheduler cron job (no CLI args available)."""
    settings = get_settings()
    _run_weekly(settings.data_input_dir, date.today())


@app.command("run-monthly")
def run_monthly(
    input_dir: Path = typer.Option(None, help="Directory of .xlsx project plans (defaults to DATA_INPUT_DIR)"),
    run_date: str = typer.Option(None, help="Override run date as YYYY-MM-DD (defaults to today)"),
    output: Path = typer.Option(None, help="Output .pptx path (defaults to outputs/monthly/<date>/Portfolio_Health_Review.pptx)"),
) -> None:
    """Run the weekly pipeline across all plans, then synthesize a monthly executive deck."""
    settings = get_settings()
    resolved_dir = input_dir or settings.data_input_dir
    resolved_date = datetime.strptime(run_date, "%Y-%m-%d").date() if run_date else date.today()

    reports = _run_weekly(resolved_dir, resolved_date)
    if not reports:
        console.print("[red]No reports generated — cannot build monthly synthesis.[/red]")
        raise typer.Exit(code=1)

    client = FireworksClient(settings)
    synthesis = build_monthly_synthesis(reports, settings, client, run_date=resolved_date)

    out_dir = settings.reports_output_dir / "monthly" / resolved_date.isoformat()
    synthesis_json = out_dir / "monthly_synthesis.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    synthesis_json.write_text(synthesis.model_dump_json(indent=2), encoding="utf-8")

    deck_path = output or (out_dir / "Portfolio_Health_Review.pptx")
    build_monthly_deck(synthesis, deck_path)

    console.print(f"[green]Monthly synthesis written to {synthesis_json}[/green]")
    console.print(f"[green]Executive deck written to {deck_path}[/green]")


@app.command("schedule-weekly")
def schedule_weekly(
    day_of_week: str = typer.Option("mon", help="Cron day-of-week, e.g. mon, tue"),
    hour: int = typer.Option(7, help="Hour (24h) to run"),
    minute: int = typer.Option(0, help="Minute to run"),
) -> None:
    """Bonus: run the weekly job on a recurring schedule (blocks the terminal)."""
    from project_health_agent.scheduler.weekly_job import start_weekly_scheduler

    console.print(f"Starting weekly scheduler: every {day_of_week} at {hour:02d}:{minute:02d}. Ctrl+C to stop.")
    start_weekly_scheduler(day_of_week=day_of_week, hour=hour, minute=minute)


if __name__ == "__main__":
    app()
