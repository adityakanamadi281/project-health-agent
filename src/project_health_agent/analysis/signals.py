"""Turns a normalized ProjectPlan into the concrete signals the RAG engine scores.

Every signal here is derived only from fields that are actually present in a
Smartsheet-style plan export. There is deliberately **no budget/cost signal**:
none of the sample exports contain cost, invoice, or hours-burned columns, so
"budget burn" is treated as an explicit assumption gap (see docs/RAG_METHODOLOGY.md)
rather than being invented. If a future export includes a Budget/Actual Cost
column, `budget_burn_ratio` becomes a straightforward addition here.
"""

from __future__ import annotations

import re
from datetime import date
from re import IGNORECASE, findall

from pydantic import BaseModel

from project_health_agent.config import Settings
from project_health_agent.models import ProjectPlan, Task, TaskStatus

NEGATIVE_LEXICON = [
    r"\bdelay(ed|s)?\b", r"\bblock(ed|er|ers)?\b", r"\bescalat\w*\b", r"\bconcern\w*\b",
    r"\brisk\w*\b", r"\bpending\b", r"\bissue\w*\b", r"\bdispute\w*\b", r"\bunhappy\b",
    r"\bfrustrat\w*\b", r"\bgap\w*\b", r"\bmiss(ed|ing)?\b", r"\bslip\w*\b", r"\bimpact(ed)?\b",
    r"\bchange\w* (request|order)\b", r"\bpush(ed)? back\b", r"\bnot (yet )?(complete|available)\b",
    r"\bremain(s|ing)? to (be )?complete\b", r"\bawait(ing)?\b", r"\brepeat(ing|ed)?\b",
]
POSITIVE_LEXICON = [
    r"\bcompleted?\b", r"\bcover(ed)?\b", r"\bahead\b", r"\bresolved\b", r"\baligned?\b",
    r"\bagreed?\b", r"\bsign[- ]?off\b", r"\bclosed\b", r"\bon track\b", r"\bapproved\b",
    r"\bconfirmed\b",
]

BLOCKER_KEYWORDS = [r"\bblock", r"\bpending\b", r"\bwait(ing)? on\b", r"\bhold\b", r"\bescalat"]


class ScheduleSignal(BaseModel):
    project_variance_days: int | None = None  # +ve = late vs baseline, from top task
    worst_task_variance_days: int | None = None
    worst_task_name: str | None = None
    overdue_incomplete_count: int = 0
    overdue_incomplete_examples: list[str] = []
    critical_overdue_count: int = 0
    slipped_tasks_pct: float = 0.0
    phase_overdue_exists: bool = False
    phase_delay_over_2wks: bool = False
    phase_in_progress_overdue: bool = False


class MilestoneSignal(BaseModel):
    total_phases: int = 0
    phases_due: int = 0  # phases whose baseline finish has passed
    phases_completed_of_due: int = 0
    milestone_completion_rate: float | None = None  # completed_of_due / phases_due
    at_risk_phase_names: list[str] = []
    time_elapsed_pct: float | None = None
    overdue_not_started_count: int = 0


class BlockerSignal(BaseModel):
    open_blocker_count: int = 0
    on_hold_task_count: int = 0
    unmet_predecessors_count: int = 0
    high_risk_tasks_count: int = 0
    unresolved_comments_count: int = 0
    client_stalled_over_1wk_count: int = 0
    client_stalled_over_2wks_count: int = 0
    blocker_examples: list[str] = []


class SentimentSignal(BaseModel):
    negative_hits: int = 0
    positive_hits: int = 0
    sentiment_score: float | None = None  # -1..1, None if no text at all
    overdue_client_items_count: int = 0
    has_explicit_escalation: bool = False
    sample_negative_comments: list[str] = []


class CompletionSignal(BaseModel):
    reported_percent_complete: float | None = None
    computed_percent_complete: float | None = None  # from task statuses, cross-check
    completion_discrepancy: float | None = None  # |reported - computed|


class CriticalPathSignal(BaseModel):
    critical_tasks_count: int = 0
    at_risk_critical_tasks_count: int = 0
    red_critical_tasks_count: int = 0
    negative_float_critical_tasks_count: int = 0
    override_red_triggered: bool = False
    at_risk_task_examples: list[str] = []


class DataQualitySignal(BaseModel):
    total_tasks: int = 0
    notes_count: int = 0
    key_fields_missing_pct: float = 0.0


class ProjectSignals(BaseModel):
    project_name: str
    as_of: date
    schedule: ScheduleSignal
    milestones: MilestoneSignal
    critical_path: CriticalPathSignal
    blockers: BlockerSignal
    sentiment: SentimentSignal
    completion: CompletionSignal
    data_quality: DataQualitySignal


def _score_text(text: str) -> tuple[int, int]:
    neg = sum(len(findall(p, text, IGNORECASE)) for p in NEGATIVE_LEXICON)
    pos = sum(len(findall(p, text, IGNORECASE)) for p in POSITIVE_LEXICON)
    return neg, pos


def _is_open_task(t: Task) -> bool:
    return t.status not in (TaskStatus.COMPLETED,) and not t.not_applicable and not t.on_hold


def _is_client_owned(assigned_to: str | None, project_name: str) -> bool:
    if not assigned_to:
        return False
    val = assigned_to.lower()
    proj_lower = project_name.lower()
    client_name = None
    if "titan" in proj_lower:
        client_name = "titan"
    elif "unisan" in proj_lower:
        client_name = "unisan"
    
    if client_name and client_name in val:
        return True
        
    client_keywords = ["customer", "client", "sme", "sponsor", "partner"]
    if any(k in val for k in client_keywords):
        return True
        
    if "zycus" not in val:
        return True
        
    return False


def _has_unmet_predecessors(task: Task, task_map: dict[int, Task]) -> bool:
    if not task.predecessors:
        return False
    parts = re.split(r'[;,]', task.predecessors)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        m = re.match(r'^\s*(\d+)', part)
        if m:
            pred_row = int(m.group(1))
            pred_task = task_map.get(pred_row)
            if pred_task and pred_task.status != TaskStatus.COMPLETED:
                return True
    return False


def compute_signals(plan: ProjectPlan, settings: Settings, as_of: date | None = None) -> ProjectSignals:
    as_of = as_of or plan.summary.as_of_date or date.today()
    task_map = {t.row_number: t for t in plan.tasks}

    top_task = next((t for t in plan.tasks if t.level in (0, None)), None)

    # 1. Schedule Slippage
    variance_days_list = [
        t.variance_days for t in plan.tasks
        if t.variance_days is not None and not t.not_applicable and not (t.is_milestone_or_phase and t.level == 0)
    ]
    slipped_count = sum(1 for v in variance_days_list if v < 0)
    slipped_tasks_pct = (slipped_count / len(variance_days_list)) if variance_days_list else 0.0

    worst_variance = min(variance_days_list) if variance_days_list else None
    worst_task = None
    if worst_variance is not None:
        worst_task = next((t for t in plan.tasks if t.variance_days == worst_variance and not t.not_applicable), None)

    overdue_incomplete_count = 0
    overdue_examples = []
    critical_overdue_count = 0
    phase_overdue_exists = False
    phase_delay_over_2wks = False
    phase_in_progress_overdue = False

    for t in plan.tasks:
        if t.not_applicable or (t.is_milestone_or_phase and t.level == 0):
            continue
        
        # Check if overdue
        if _is_open_task(t) and t.end_date and t.end_date < as_of:
            overdue_incomplete_count += 1
            if t.critical:
                critical_overdue_count += 1
            if len(overdue_examples) < 5:
                overdue_examples.append(t.name)
        
        # Phase/Milestone check
        if t.is_milestone_or_phase or t.level == 1:
            if t.status != TaskStatus.COMPLETED:
                if t.end_date and t.end_date < as_of:
                    phase_overdue_exists = True
                    delay_days = (as_of - t.end_date).days
                    if delay_days > 14:
                        phase_delay_over_2wks = True
                    if t.status == TaskStatus.IN_PROGRESS:
                        phase_in_progress_overdue = True
                if t.variance_days is not None and t.variance_days <= -14:
                    phase_delay_over_2wks = True
                    if t.end_date and t.end_date < as_of:
                        phase_overdue_exists = True
                        if t.status == TaskStatus.IN_PROGRESS:
                            phase_in_progress_overdue = True

    schedule = ScheduleSignal(
        project_variance_days=top_task.variance_days if top_task else None,
        worst_task_variance_days=worst_variance,
        worst_task_name=worst_task.name if worst_task else None,
        overdue_incomplete_count=overdue_incomplete_count,
        overdue_incomplete_examples=overdue_examples,
        critical_overdue_count=critical_overdue_count,
        slipped_tasks_pct=slipped_tasks_pct,
        phase_overdue_exists=phase_overdue_exists,
        phase_delay_over_2wks=phase_delay_over_2wks,
        phase_in_progress_overdue=phase_in_progress_overdue,
    )

    # 2. Milestones
    # Compute project start and end dates
    project_start = plan.summary.project_start_date
    if not project_start:
        starts = [t.start_date for t in plan.tasks if t.start_date and not t.not_applicable]
        project_start = min(starts) if starts else None

    project_end = plan.summary.project_end_date
    if not project_end:
        ends = [t.end_date for t in plan.tasks if t.end_date and not t.not_applicable]
        project_end = max(ends) if ends else None

    time_elapsed_pct = 0.0
    if project_start and project_end:
        duration = (project_end - project_start).days
        if duration > 0:
            elapsed = (as_of - project_start).days
            time_elapsed_pct = max(0.0, min(1.0, elapsed / duration))

    overdue_not_started_count = sum(
        1 for t in plan.tasks
        if not t.not_applicable and t.status == TaskStatus.NOT_STARTED and t.start_date and t.start_date < as_of
    )

    phases = [t for t in plan.tasks if t.is_milestone_or_phase]
    due_phases = [p for p in phases if p.baseline_finish and p.baseline_finish <= as_of]
    completed_due = [p for p in due_phases if p.status == TaskStatus.COMPLETED]
    at_risk_phases = [p.name for p in due_phases if p.status != TaskStatus.COMPLETED]

    milestones = MilestoneSignal(
        total_phases=len(phases),
        phases_due=len(due_phases),
        phases_completed_of_due=len(completed_due),
        milestone_completion_rate=(len(completed_due) / len(due_phases)) if due_phases else None,
        at_risk_phase_names=at_risk_phases[:5],
        time_elapsed_pct=time_elapsed_pct,
        overdue_not_started_count=overdue_not_started_count,
    )

    # 3. Blockers
    on_hold_tasks = [t for t in plan.tasks if t.on_hold and not t.not_applicable]
    on_hold_count = len(on_hold_tasks)

    unmet_predecessors_count = 0
    high_risk_tasks_count = 0
    unresolved_comments_count = 0
    client_stalled_over_1wk_count = 0
    client_stalled_over_2wks_count = 0
    blocker_examples = []
    
    unique_blocker_tasks = {}

    for t in plan.tasks:
        if t.not_applicable:
            continue
        
        is_blocker = False
        blocker_reasons = []

        if t.on_hold or t.status == TaskStatus.ON_HOLD:
            is_blocker = True
            blocker_reasons.append("On Hold")

        if t.status != TaskStatus.COMPLETED:
            if _has_unmet_predecessors(t, task_map):
                is_blocker = True
                unmet_predecessors_count += 1
                blocker_reasons.append("Unmet Predecessors")
            
            is_high = t.at_risk and (str(t.at_risk).lower() in ("high", "true", "yes", "1") or t.at_risk is True)
            if is_high:
                is_blocker = True
                high_risk_tasks_count += 1
                blocker_reasons.append("At Risk = High")
                
            if t.status_comment:
                is_blocker = True
                unresolved_comments_count += 1
                blocker_reasons.append("Unresolved Status Comment")

        if is_blocker:
            unique_blocker_tasks[t.row_number] = t
            # check client stalled
            if _is_client_owned(t.assigned_to or t.owner, plan.project_name):
                if t.end_date and t.end_date < as_of:
                    delay_days = (as_of - t.end_date).days
                    if delay_days > 14:
                        client_stalled_over_2wks_count += 1
                    if delay_days > 7:
                        client_stalled_over_1wk_count += 1
            
            if len(blocker_examples) < 5:
                reasons_str = ", ".join(blocker_reasons)
                blocker_examples.append(f"{t.name} ({reasons_str})")

    # Add comments sheet check to texts for sentiment
    texts_for_sentiment = []
    for t in plan.tasks:
        if t.status_comment:
            texts_for_sentiment.append(t.status_comment)
    for c in plan.comments:
        texts_for_sentiment.append(c.text)

    # Let's count matching blocker keywords from comments sheet as well for open_blocker_count compatibility
    open_blocker_count = 0
    for text in texts_for_sentiment:
        if any(re.search(p, text, IGNORECASE) for p in BLOCKER_KEYWORDS):
            open_blocker_count += 1

    blockers = BlockerSignal(
        open_blocker_count=len(unique_blocker_tasks),  # total unique blockers
        on_hold_task_count=on_hold_count,
        unmet_predecessors_count=unmet_predecessors_count,
        high_risk_tasks_count=high_risk_tasks_count,
        unresolved_comments_count=unresolved_comments_count,
        client_stalled_over_1wk_count=client_stalled_over_1wk_count,
        client_stalled_over_2wks_count=client_stalled_over_2wks_count,
        blocker_examples=blocker_examples,
    )

    # 4. Sentiment
    neg_total, pos_total = 0, 0
    neg_samples = []
    escalation_pattern = re.compile(r'\b(escalat\w*|dispute\w*|unhappy|frustrat\w*|critical concern|crisis)\b', re.IGNORECASE)
    has_explicit_escalation = False

    for text in texts_for_sentiment:
        neg, pos = _score_text(text)
        neg_total += neg
        pos_total += pos
        if neg > 0 and len(neg_samples) < 5:
            neg_samples.append(text)
        if escalation_pattern.search(text):
            has_explicit_escalation = True

    total_hits = neg_total + pos_total
    
    # Overdue client items count
    overdue_client_items_count = sum(
        1 for t in plan.tasks
        if not t.not_applicable and t.status != TaskStatus.COMPLETED and t.end_date and t.end_date < as_of and _is_client_owned(t.assigned_to or t.owner, plan.project_name)
    )

    sentiment = SentimentSignal(
        negative_hits=neg_total,
        positive_hits=pos_total,
        sentiment_score=((pos_total - neg_total) / total_hits) if total_hits else None,
        overdue_client_items_count=overdue_client_items_count,
        has_explicit_escalation=has_explicit_escalation,
        sample_negative_comments=neg_samples,
    )

    # 5. Completion (cross-check)
    countable = [t for t in plan.tasks if not t.not_applicable and t.level not in (0,)]
    computed_pct = None
    if countable:
        computed_pct = sum(1 for t in countable if t.status == TaskStatus.COMPLETED) / len(countable)
    reported_pct = plan.summary.percent_complete or (top_task.percent_complete if top_task else None)
    
    completion = CompletionSignal(
        reported_percent_complete=reported_pct,
        computed_percent_complete=computed_pct,
        completion_discrepancy=(
            abs(reported_pct - computed_pct) if reported_pct is not None and computed_pct is not None else None
        ),
    )

    # Critical Path calculation
    critical_tasks_count = 0
    at_risk_critical_tasks_count = 0
    red_critical_tasks_count = 0
    negative_float_critical_tasks_count = 0
    override_red_triggered = False
    at_risk_task_examples = []

    for t in plan.tasks:
        if t.not_applicable:
            continue
        if t.critical:
            critical_tasks_count += 1
            is_neg_float = t.total_float is not None and t.total_float < 0
            is_rag_at_risk = t.rag_raw is not None and str(t.rag_raw).capitalize() in ("Red", "Amber", "Yellow")
            if is_neg_float or is_rag_at_risk:
                at_risk_critical_tasks_count += 1
                if len(at_risk_task_examples) < 5:
                    at_risk_task_examples.append(t.name)
            if is_neg_float:
                negative_float_critical_tasks_count += 1
            if t.rag_raw is not None and str(t.rag_raw).capitalize() == "Red":
                red_critical_tasks_count += 1
            if is_neg_float and t.rag_raw is not None and str(t.rag_raw).capitalize() == "Red":
                override_red_triggered = True

    critical_path = CriticalPathSignal(
        critical_tasks_count=critical_tasks_count,
        at_risk_critical_tasks_count=at_risk_critical_tasks_count,
        red_critical_tasks_count=red_critical_tasks_count,
        negative_float_critical_tasks_count=negative_float_critical_tasks_count,
        override_red_triggered=override_red_triggered,
        at_risk_task_examples=at_risk_task_examples,
    )

    # 6. Data Quality
    key_fields = ["start_date", "end_date", "status", "percent_complete"]
    missing = 0
    total_checks = 0
    for t in plan.tasks:
        for f in key_fields:
            total_checks += 1
            if getattr(t, f) in (None, TaskStatus.UNKNOWN):
                missing += 1
    data_quality = DataQualitySignal(
        total_tasks=len(plan.tasks),
        notes_count=len(plan.data_quality_notes),
        key_fields_missing_pct=(missing / total_checks) if total_checks else 0.0,
    )

    return ProjectSignals(
        project_name=plan.project_name,
        as_of=as_of,
        schedule=schedule,
        milestones=milestones,
        critical_path=critical_path,
        blockers=blockers,
        sentiment=sentiment,
        completion=completion,
        data_quality=data_quality,
    )
