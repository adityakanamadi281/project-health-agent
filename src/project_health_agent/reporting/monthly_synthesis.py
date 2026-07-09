"""Synthesizes multiple projects' weekly reports into portfolio-level insight.

This is deliberately NOT "summarize each project" — the assignment explicitly
asks for trends *across* projects. So this module:

1. Computes portfolio-level statistics itself (RAG distribution, common
   blocker themes, sentiment distribution, schedule-slip distribution) —
   deterministically, in Python, not via the LLM.
2. Uses week-over-week history (reporting/history.py) to detect genuine
   movement when enough runs have accumulated; says so honestly when they
   haven't.
3. Only asks the LLM to turn those computed portfolio statistics into an
   executive narrative (headline, trend bullets, emerging risks,
   recommendations) — with a deterministic fallback if no LLM is configured.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date

from pydantic import BaseModel

from project_health_agent.config import Settings
from project_health_agent.llm.fireworks_client import FireworksClient, safe_chat
from project_health_agent.reporting.history import HistoryEntry, load_history
from project_health_agent.reporting.weekly_report import WeeklyReport

SYSTEM_PROMPT = (
    "You are a Professional Services delivery lead preparing an executive/VP-level "
    "monthly portfolio synthesis. You are given computed portfolio statistics across "
    "several client projects. Respond ONLY with a JSON object with these exact keys: "
    "\"headline\" (one sentence, the single most important portfolio-level takeaway), "
    "\"trend_bullets\" (3-5 short strings describing patterns ACROSS projects, not "
    "per-project summaries), \"emerging_risks\" (2-4 short strings naming specific risks "
    "that could bite in the next 2-4 weeks if unaddressed), \"recommendations\" (2-4 short, "
    "concrete, action-oriented strings a VP could commit to in a client meeting). "
    "Never invent numbers not present in the input. Do not include markdown formatting "
    "inside the JSON string values."
)


class ProjectSnapshot(BaseModel):
    project_name: str
    rag: str
    one_liner: str
    schedule_variance_days: int | None
    milestone_completion_rate: float | None
    sentiment_score: float | None
    open_blockers: int


class TrendMovement(BaseModel):
    project_name: str
    from_rag: str
    to_rag: str
    run_dates: tuple[str, str]


class PortfolioStats(BaseModel):
    project_count: int
    rag_distribution: dict[str, int]
    avg_schedule_variance_days: float | None
    common_blocker_terms: list[tuple[str, int]]
    avg_sentiment_score: float | None
    projects_with_perception_gap: list[str]
    movements: list[TrendMovement]
    history_depth_note: str


class MonthlySynthesis(BaseModel):
    run_date: date
    project_snapshots: list[ProjectSnapshot]
    stats: PortfolioStats
    headline: str
    trend_bullets: list[str]
    emerging_risks: list[str]
    recommendations: list[str]
    narrative_source: str


def _compute_portfolio_stats(reports: list[WeeklyReport], history: list[HistoryEntry]) -> PortfolioStats:
    rag_dist = Counter(r.rag.overall.value for r in reports)

    variances = [r.signals.schedule.worst_task_variance_days for r in reports if r.signals.schedule.worst_task_variance_days is not None]
    avg_variance = sum(variances) / len(variances) if variances else None

    sentiments = [r.signals.sentiment.sentiment_score for r in reports if r.signals.sentiment.sentiment_score is not None]
    avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else None

    blocker_terms: Counter[str] = Counter()
    for r in reports:
        for ex in r.signals.blockers.blocker_examples:
            for word in ["JDE", "mapping", "workshop", "sign-off", "sign off", "data", "training", "integration", "resource", "calendar", "meeting", "review"]:
                if word.lower() in ex.lower():
                    blocker_terms[word] += 1

    perception_gaps = [r.project_name for r in reports if r.rag.perception_gap]

    # Week-over-week movement, grouped by project, sorted by run_date.
    by_project: dict[str, list[HistoryEntry]] = {}
    for e in history:
        by_project.setdefault(e.project_name, []).append(e)
    movements: list[TrendMovement] = []
    distinct_run_dates: set[str] = set()
    for project, entries in by_project.items():
        entries.sort(key=lambda e: e.run_date)
        distinct_run_dates.update(e.run_date.isoformat() for e in entries)
        if len(entries) >= 2 and entries[-2].rag_overall != entries[-1].rag_overall:
            movements.append(
                TrendMovement(
                    project_name=project,
                    from_rag=entries[-2].rag_overall,
                    to_rag=entries[-1].rag_overall,
                    run_dates=(entries[-2].run_date.isoformat(), entries[-1].run_date.isoformat()),
                )
            )

    if len(distinct_run_dates) <= 1:
        history_note = (
            "Only one weekly snapshot has been recorded so far for this portfolio, so "
            "week-over-week trend movement cannot be computed yet — insights below are based "
            "on the current cross-project snapshot. Run the agent on subsequent weeks (see README) "
            "to unlock true time-trend analysis."
        )
    else:
        history_note = f"Trend movement computed across {len(distinct_run_dates)} recorded weekly run(s)."

    return PortfolioStats(
        project_count=len(reports),
        rag_distribution=dict(rag_dist),
        avg_schedule_variance_days=avg_variance,
        common_blocker_terms=blocker_terms.most_common(5),
        avg_sentiment_score=avg_sentiment,
        projects_with_perception_gap=perception_gaps,
        movements=movements,
        history_depth_note=history_note,
    )


def _fallback_synthesis(stats: PortfolioStats, snapshots: list[ProjectSnapshot]) -> dict:
    red = stats.rag_distribution.get("Red", 0)
    amber = stats.rag_distribution.get("Amber", 0)
    green = stats.rag_distribution.get("Green", 0)
    headline = (
        f"Of {stats.project_count} active projects, {red} are Red and {amber} are Amber — "
        f"{'schedule and blocker pressure is the dominant portfolio risk' if (red + amber) else 'the portfolio is broadly healthy'}."
    )
    trend_bullets = [
        f"RAG distribution across the portfolio: {green} Green / {amber} Amber / {red} Red.",
    ]
    if stats.avg_schedule_variance_days is not None:
        trend_bullets.append(
            f"Average schedule variance vs. baseline across projects is {stats.avg_schedule_variance_days:.1f} days."
        )
    if stats.common_blocker_terms:
        terms = ", ".join(f"{t} ({c})" for t, c in stats.common_blocker_terms)
        trend_bullets.append(f"Recurring blocker themes across projects: {terms}.")
    if stats.avg_sentiment_score is not None:
        trend_bullets.append(f"Average stakeholder sentiment score across projects: {stats.avg_sentiment_score:+.2f}.")
    if stats.projects_with_perception_gap:
        trend_bullets.append(
            "PM-reported status diverges from computed status on: " + ", ".join(stats.projects_with_perception_gap)
        )
    trend_bullets.append(stats.history_depth_note)

    risks = []
    for s in snapshots:
        if s.rag in ("Red", "Amber") and s.open_blockers > 0:
            risks.append(f"{s.project_name}: {s.open_blockers} open blocker(s) risk further slippage if unresolved.")
    if not risks:
        risks.append("No acute cross-project risks detected from current signals.")

    recs = ["Prioritize PM time on Red/Amber projects with open critical-path items this week."]
    if stats.common_blocker_terms:
        recs.append(
            f"Stand up a focused working session on the recurring theme '{stats.common_blocker_terms[0][0]}' "
            "since it appears across multiple projects."
        )
    recs.append("Reconcile PM-reported status with computed status where a perception gap was flagged.")

    return {
        "headline": headline,
        "trend_bullets": trend_bullets[:5],
        "emerging_risks": risks[:4],
        "recommendations": recs[:4],
    }


def build_monthly_synthesis(
    reports: list[WeeklyReport],
    settings: Settings,
    client: FireworksClient,
    run_date: date | None = None,
) -> MonthlySynthesis:
    run_date = run_date or date.today()
    history = load_history(settings)
    stats = _compute_portfolio_stats(reports, history)

    snapshots = [
        ProjectSnapshot(
            project_name=r.project_name,
            rag=r.rag.overall.value,
            one_liner=r.narrative.split(". ")[0] + ".",
            schedule_variance_days=r.signals.schedule.worst_task_variance_days,
            milestone_completion_rate=r.signals.milestones.milestone_completion_rate,
            sentiment_score=r.signals.sentiment.sentiment_score,
            open_blockers=r.signals.blockers.open_blocker_count + r.signals.blockers.on_hold_task_count,
        )
        for r in reports
    ]

    user_prompt = (
        "Portfolio statistics (computed deterministically, treat as ground truth):\n"
        + json.dumps(stats.model_dump(), indent=2, default=str)
        + "\n\nPer-project snapshots:\n"
        + json.dumps([s.model_dump() for s in snapshots], indent=2)
    )

    raw = safe_chat(client, SYSTEM_PROMPT, user_prompt, json_mode=True)
    narrative_source = "llm"
    parsed: dict | None = None
    if raw:
        try:
            parsed = json.loads(raw)
            assert all(k in parsed for k in ("headline", "trend_bullets", "emerging_risks", "recommendations"))
        except Exception:  # noqa: BLE001
            parsed = None
    if parsed is None:
        parsed = _fallback_synthesis(stats, snapshots)
        narrative_source = "template-fallback"

    return MonthlySynthesis(
        run_date=run_date,
        project_snapshots=snapshots,
        stats=stats,
        headline=parsed["headline"],
        trend_bullets=parsed["trend_bullets"],
        emerging_risks=parsed["emerging_risks"],
        recommendations=parsed["recommendations"],
        narrative_source=narrative_source,
    )
