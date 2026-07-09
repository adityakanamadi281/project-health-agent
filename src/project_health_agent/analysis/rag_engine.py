"""Deterministic RAG (Red/Amber/Green) engine.

This is intentionally rule-based, not LLM-based: the *status* must be
reproducible, auditable, and stable across runs — an executive needs to trust
that "Red" means the same thing every week. The LLM (see llm/fireworks_client.py)
is used only afterwards, to turn this structured verdict into plain-English
narrative. See docs/RAG_METHODOLOGY.md for the full written methodology this
code implements.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from project_health_agent.analysis.signals import ProjectSignals
from project_health_agent.config import Settings


class RAG(str, Enum):
    GREEN = "Green"
    AMBER = "Amber"
    RED = "Red"
    GREY = "Grey"

    @property
    def rank(self) -> int:
        return {"Green": 0, "Amber": 1, "Red": 2, "Grey": -1}[self.value]


class DimensionResult(BaseModel):
    name: str
    rag: RAG
    reasons: list[str]


class RAGResult(BaseModel):
    project_name: str
    overall: RAG
    dimensions: list[DimensionResult]
    perception_gap: str | None = None  # conflict between PM-authored label and computed status
    top_reasons: list[str]
    caveats: list[str]  # data-quality / assumption caveats to disclose alongside the verdict


def _worst(rags: list[RAG]) -> RAG:
    # Filter out GREY as it does not participate in rank comparisons
    active_rags = [r for r in rags if r != RAG.GREY]
    return max(active_rags, key=lambda r: r.rank) if active_rags else RAG.GREEN


def _schedule_dimension(sig: ProjectSignals, settings: Settings) -> DimensionResult:
    reasons: list[str] = []
    pct_slipped = sig.schedule.slipped_tasks_pct
    worst_var = sig.schedule.worst_task_variance_days

    # 14 days delay is 2 weeks. Since negative is delay:
    is_red = pct_slipped > 0.10 or sig.schedule.phase_delay_over_2wks or (worst_var is not None and worst_var <= -14)
    is_amber = not is_red and (pct_slipped > 0.0 or sig.schedule.phase_overdue_exists or (worst_var is not None and worst_var < 0))

    if is_red:
        rag = RAG.RED
        if pct_slipped > 0.10:
            reasons.append(f"More than 10% of tasks slipped past baseline ({pct_slipped:.1%})")
        if sig.schedule.phase_delay_over_2wks:
            reasons.append("Phase-level milestone is delayed by more than 2 weeks")
        if worst_var is not None and worst_var <= -14:
            reasons.append(f"Worst task variance is {abs(worst_var)} days behind baseline" + (f" (worst offender: {sig.schedule.worst_task_name})" if sig.schedule.worst_task_name else ""))
    elif is_amber:
        rag = RAG.AMBER
        if pct_slipped > 0:
            reasons.append(f"{pct_slipped:.1%} of tasks slipped past baseline")
        if sig.schedule.phase_overdue_exists:
            reasons.append("An active phase-level milestone is past its end date and still open")
        if worst_var is not None and worst_var < 0:
            reasons.append(f"Worst task variance is {abs(worst_var)} days behind baseline (< 2 weeks)")
    else:
        rag = RAG.GREEN
        reasons.append("All tasks and phases are on or ahead of baseline")

    return DimensionResult(name="Schedule Slippage", rag=rag, reasons=reasons)


def _milestone_dimension(sig: ProjectSignals, settings: Settings) -> DimensionResult:
    reasons: list[str] = []
    pct_complete = sig.completion.reported_percent_complete or 0.0
    time_elapsed = sig.milestones.time_elapsed_pct

    if time_elapsed is None:
        return DimensionResult(
            name="Milestone Health",
            rag=RAG.GREEN,
            reasons=["No active milestones or baseline dates available to assess pacing"],
        )

    diff = time_elapsed - pct_complete

    if diff <= 0:
        rag = RAG.GREEN
        reasons.append(f"On/ahead of pace: project is {pct_complete:.1%} complete vs. {time_elapsed:.1%} elapsed time")
    elif diff <= 0.10:
        rag = RAG.AMBER
        reasons.append(f"Behind pace: project is {pct_complete:.1%} complete vs. {time_elapsed:.1%} elapsed time (within 10 pts)")
    else:
        rag = RAG.RED
        reasons.append(f"Significantly behind pace: project is {pct_complete:.1%} complete vs. {time_elapsed:.1%} elapsed time (> 10 pts behind)")

    if sig.milestones.overdue_not_started_count > 0:
        reasons.append(f"{sig.milestones.overdue_not_started_count} 'Not Started' task(s) whose planned start date has passed")

    return DimensionResult(name="Milestone Health", rag=rag, reasons=reasons)


def _critical_path_dimension(sig: ProjectSignals) -> DimensionResult:
    reasons: list[str] = []
    count = sig.critical_path.at_risk_critical_tasks_count

    if count == 0:
        rag = RAG.GREEN
        reasons.append("No critical path tasks are currently at risk (negative float or Red/Amber status)")
    elif count <= 2:
        rag = RAG.AMBER
        reasons.append(f"{count} critical path task(s) are at risk (negative float or Red/Amber status)")
    else:
        rag = RAG.RED
        reasons.append(f"{count} critical path tasks are at risk — represents a high risk to key dates")

    if sig.critical_path.at_risk_task_examples:
        reasons.append("Examples: " + ", ".join(sig.critical_path.at_risk_task_examples[:3]))

    return DimensionResult(name="Critical Path Risk", rag=rag, reasons=reasons)


def _blocker_dimension(sig: ProjectSignals) -> DimensionResult:
    reasons: list[str] = []
    count = sig.blockers.open_blocker_count
    stalled_1wk = sig.blockers.client_stalled_over_1wk_count
    stalled_2wks = sig.blockers.client_stalled_over_2wks_count

    if count == 0:
        rag = RAG.GREEN
        reasons.append("No open blockers (On Hold, unmet predecessors, At Risk=High, or unresolved comments)")
    elif count >= 4 or stalled_2wks > 0 or stalled_1wk > 0:
        rag = RAG.RED
        if count >= 4:
            reasons.append(f"{count} open blocker tasks detected (exceeds red threshold of 4)")
        if stalled_2wks > 0:
            reasons.append(f"{stalled_2wks} client-owned blocker(s) stalled for more than 2 weeks")
        elif stalled_1wk > 0:
            reasons.append(f"{stalled_1wk} client-owned blocker(s) stalled for more than 1 week")
    else:
        rag = RAG.AMBER
        reasons.append(f"{count} open blocker task(s) detected (within Amber threshold, none client-stalled > 1 week)")

    if sig.blockers.blocker_examples:
        reasons.append("Blockers: " + " | ".join(sig.blockers.blocker_examples[:3]))

    return DimensionResult(name="Blockers", rag=rag, reasons=reasons)


def _sentiment_dimension(sig: ProjectSignals) -> DimensionResult:
    reasons: list[str] = []
    overdue_client = sig.sentiment.overdue_client_items_count
    has_escalation = sig.sentiment.has_explicit_escalation
    score = sig.sentiment.sentiment_score

    is_red = overdue_client >= 3 or has_escalation or (score is not None and score <= -0.30)
    is_amber = not is_red and (overdue_client in (1, 2) or (score is not None and score <= 0.15))

    if is_red:
        rag = RAG.RED
        if overdue_client >= 3:
            reasons.append(f"{overdue_client} client-owned tasks are past their end date")
        if has_escalation:
            reasons.append("Explicit escalation comment or concern-flagged word detected in project comments")
        if score is not None and score <= -0.30:
            reasons.append(f"Comment sentiment score is negative ({score:+.2f})")
    elif is_amber:
        rag = RAG.AMBER
        if overdue_client in (1, 2):
            reasons.append(f"{overdue_client} client-owned task(s) are overdue")
        if score is not None and score <= 0.15:
            reasons.append(f"Comment sentiment score is neutral/slightly low ({score:+.2f})")
    else:
        rag = RAG.GREEN
        reasons.append("No overdue client action items and positive stakeholder comments")

    if sig.sentiment.sample_negative_comments:
        reasons.append("Representative concern: " + sig.sentiment.sample_negative_comments[0])

    return DimensionResult(name="Stakeholder Sentiment", rag=rag, reasons=reasons)


def _budget_burn_dimension() -> DimensionResult:
    return DimensionResult(
        name="Budget Burn",
        rag=RAG.GREY,
        reasons=["Budget/cost data is not present in the current project plans. Excluded from scoring."]
    )


def _data_quality_caveats(sig: ProjectSignals) -> list[str]:
    caveats = []
    if sig.data_quality.key_fields_missing_pct > 0.15:
        caveats.append(
            f"{sig.data_quality.key_fields_missing_pct:.0%} of key task fields (dates/status/% complete) "
            "are missing or unparseable in the source sheet — confidence in this status is reduced accordingly"
        )
    if sig.completion.completion_discrepancy and sig.completion.completion_discrepancy > 0.15:
        caveats.append(
            f"PM-reported % complete ({sig.completion.reported_percent_complete:.0%}) diverges from the "
            f"task-level computed % complete ({sig.completion.computed_percent_complete:.0%}) by "
            f"{sig.completion.completion_discrepancy:.0%} — worth reconciling with the PM"
        )
    return caveats


def determine_rag(sig: ProjectSignals, settings: Settings, pm_label: str | None = None) -> RAGResult:
    sched_dim = _schedule_dimension(sig, settings)
    milestone_dim = _milestone_dimension(sig, settings)
    critical_dim = _critical_path_dimension(sig)
    blocker_dim = _blocker_dimension(sig)
    sentiment_dim = _sentiment_dimension(sig)
    budget_dim = _budget_burn_dimension()

    dims = [sched_dim, milestone_dim, critical_dim, blocker_dim, sentiment_dim, budget_dim]

    # Weighted composite score calculation
    def get_val(rag: RAG) -> int:
        if rag == RAG.GREEN:
            return 0
        elif rag == RAG.AMBER:
            return 1
        elif rag == RAG.RED:
            return 2
        return 0

    weighted_score = (
        0.30 * get_val(sched_dim.rag) +
        0.25 * get_val(milestone_dim.rag) +
        0.20 * get_val(critical_dim.rag) +
        0.15 * get_val(blocker_dim.rag) +
        0.10 * get_val(sentiment_dim.rag)
    )

    if weighted_score <= 0.5:
        overall = RAG.GREEN
    elif weighted_score <= 1.2:
        overall = RAG.AMBER
    else:
        overall = RAG.RED

    # Check for Hard Overrides to Red
    override_reasons = []
    if sig.critical_path.override_red_triggered:
        override_reasons.append("Hard Override to Red: critical path task is Red AND has negative float")
    if sig.schedule.phase_in_progress_overdue:
        override_reasons.append("Hard Override to Red: a phase-level milestone end date has passed with the phase still 'In Progress'")

    if override_reasons:
        overall = RAG.RED

    perception_gap = None
    if pm_label and pm_label.strip().capitalize() in {"Green", "Amber", "Yellow", "Red"}:
        normalized = pm_label.strip().capitalize().replace("Yellow", "Amber")
        if normalized != overall.value:
            perception_gap = (
                f"PM-reported schedule health is '{normalized}' while signal-based analysis "
                f"computes '{overall.value}' — flagged for reconciliation, not overridden"
            )

    top_reasons = []
    if override_reasons:
        top_reasons.extend(override_reasons)
    
    # Sort active dimensions by RAG rank (worst first) to pull top reasons
    active_dims = [d for d in dims if d.name != "Budget Burn"]
    for d in sorted(active_dims, key=lambda d: -d.rag.rank):
        top_reasons.extend(d.reasons)

    top_reasons = top_reasons[:5]

    return RAGResult(
        project_name=sig.project_name,
        overall=overall,
        dimensions=dims,
        perception_gap=perception_gap,
        top_reasons=top_reasons,
        caveats=_data_quality_caveats(sig),
    )
