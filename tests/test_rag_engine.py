"""Unit tests for the deterministic RAG engine under the Phase 1 methodology.

These tests construct ProjectSignals directly (rather than round-tripping through a
spreadsheet) so they exercise the scoring rules in isolation.
"""

from __future__ import annotations

from datetime import date

from project_health_agent.analysis.rag_engine import RAG, determine_rag
from project_health_agent.analysis.signals import (
    BlockerSignal,
    CompletionSignal,
    DataQualitySignal,
    MilestoneSignal,
    ProjectSignals,
    ScheduleSignal,
    SentimentSignal,
    CriticalPathSignal,
)
from project_health_agent.config import Settings


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        SCHEDULE_SLIP_AMBER_DAYS=5,
        SCHEDULE_SLIP_RED_DAYS=15,
        MILESTONE_AMBER_PCT=0.85,
        MILESTONE_RED_PCT=0.70,
    )


def _healthy_signals(**overrides) -> ProjectSignals:
    base = dict(
        project_name="Test Project",
        as_of=date(2026, 7, 8),
        schedule=ScheduleSignal(
            project_variance_days=0,
            worst_task_variance_days=0,
            overdue_incomplete_count=0,
            slipped_tasks_pct=0.0,
            phase_overdue_exists=False,
            phase_delay_over_2wks=False,
            phase_in_progress_overdue=False,
        ),
        milestones=MilestoneSignal(
            total_phases=4,
            phases_due=4,
            phases_completed_of_due=4,
            milestone_completion_rate=1.0,
            time_elapsed_pct=0.50,
            overdue_not_started_count=0,
        ),
        critical_path=CriticalPathSignal(
            critical_tasks_count=5,
            at_risk_critical_tasks_count=0,
            red_critical_tasks_count=0,
            negative_float_critical_tasks_count=0,
            override_red_triggered=False,
        ),
        blockers=BlockerSignal(
            open_blocker_count=0,
            on_hold_task_count=0,
            unmet_predecessors_count=0,
            high_risk_tasks_count=0,
            unresolved_comments_count=0,
            client_stalled_over_1wk_count=0,
            client_stalled_over_2wks_count=0,
        ),
        sentiment=SentimentSignal(
            sentiment_score=0.5,
            positive_hits=3,
            negative_hits=0,
            overdue_client_items_count=0,
            has_explicit_escalation=False,
        ),
        completion=CompletionSignal(
            reported_percent_complete=0.60,
            computed_percent_complete=0.60,
            completion_discrepancy=0.0,
        ),
        data_quality=DataQualitySignal(total_tasks=100, key_fields_missing_pct=0.02),
    )
    base.update(overrides)
    return ProjectSignals(**base)


def test_fully_healthy_project_is_green():
    sig = _healthy_signals()
    result = determine_rag(sig, _settings())
    assert result.overall == RAG.GREEN
    # Active dimensions should be Green; Budget Burn should be Grey
    for d in result.dimensions:
        if d.name == "Budget Burn":
            assert d.rag == RAG.GREY
        else:
            assert d.rag == RAG.GREEN


def test_schedule_slip_red_dimension():
    # Slipped tasks % > 10%
    sig = _healthy_signals(
        schedule=ScheduleSignal(
            slipped_tasks_pct=0.12,
            worst_task_variance_days=-2,
        )
    )
    result = determine_rag(sig, _settings())
    schedule_dim = next(d for d in result.dimensions if d.name == "Schedule Slippage")
    assert schedule_dim.rag == RAG.RED


def test_milestone_behind_pace_is_red():
    # 80% elapsed but only 50% complete (> 10 pts behind)
    sig = _healthy_signals(
        milestones=MilestoneSignal(
            time_elapsed_pct=0.80,
        ),
        completion=CompletionSignal(
            reported_percent_complete=0.50,
        ),
    )
    result = determine_rag(sig, _settings())
    milestone_dim = next(d for d in result.dimensions if d.name == "Milestone Health")
    assert milestone_dim.rag == RAG.RED


def test_critical_path_tasks_at_risk_red():
    sig = _healthy_signals(
        critical_path=CriticalPathSignal(
            at_risk_critical_tasks_count=3,
        )
    )
    result = determine_rag(sig, _settings())
    critical_dim = next(d for d in result.dimensions if d.name == "Critical Path Risk")
    assert critical_dim.rag == RAG.RED


def test_blockers_red_stalled_client():
    sig = _healthy_signals(
        blockers=BlockerSignal(
            open_blocker_count=1,
            client_stalled_over_2wks_count=1,
        )
    )
    result = determine_rag(sig, _settings())
    blocker_dim = next(d for d in result.dimensions if d.name == "Blockers")
    assert blocker_dim.rag == RAG.RED


def test_sentiment_red_escalation():
    sig = _healthy_signals(
        sentiment=SentimentSignal(
            has_explicit_escalation=True,
        )
    )
    result = determine_rag(sig, _settings())
    sentiment_dim = next(d for d in result.dimensions if d.name == "Stakeholder Sentiment")
    assert sentiment_dim.rag == RAG.RED


def test_composite_score_amber():
    # Schedule is Red (0.30 * 2 = 0.60), others are Green (0). Overall should be Amber (0.60 is in 0.5..1.2)
    sig = _healthy_signals(
        schedule=ScheduleSignal(
            slipped_tasks_pct=0.12,
        )
    )
    result = determine_rag(sig, _settings())
    assert result.overall == RAG.AMBER


def test_composite_score_red():
    # Schedule is Red (0.30 * 2 = 0.60)
    # Milestones is Red (0.25 * 2 = 0.50)
    # Critical Path is Red (0.20 * 2 = 0.40)
    # Sum = 1.50 -> Red (> 1.2)
    sig = _healthy_signals(
        schedule=ScheduleSignal(slipped_tasks_pct=0.12),
        milestones=MilestoneSignal(time_elapsed_pct=0.80),
        critical_path=CriticalPathSignal(at_risk_critical_tasks_count=3),
        completion=CompletionSignal(reported_percent_complete=0.50),
    )
    result = determine_rag(sig, _settings())
    assert result.overall == RAG.RED


def test_override_critical_path_red_float():
    # Composite score is 0.0, but override triggers overall Red
    sig = _healthy_signals(
        critical_path=CriticalPathSignal(
            override_red_triggered=True,
        )
    )
    result = determine_rag(sig, _settings())
    assert result.overall == RAG.RED
    assert "Hard Override to Red" in result.top_reasons[0]


def test_override_phase_in_progress_overdue():
    sig = _healthy_signals(
        schedule=ScheduleSignal(
            phase_in_progress_overdue=True,
        )
    )
    result = determine_rag(sig, _settings())
    assert result.overall == RAG.RED
    assert "Hard Override to Red" in result.top_reasons[0]
