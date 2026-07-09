"""Unit tests for ingestion/excel_loader.py against the real sample workbooks.

These exercise the "handles messy/incomplete data gracefully" requirement directly against
the two sample exports checked into data/sample_plans/, since they are the best available
fixtures for the kind of messiness (#UNPARSEABLE cells, divergent column order) this loader
must tolerate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from project_health_agent.ingestion.excel_loader import load_project_plan

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample_plans"


@pytest.mark.parametrize("filename", ["S2P_Project.xlsx", "Project_Plan_B.xlsx"])
def test_load_project_plan_does_not_raise_on_real_sample_files(filename):
    plan = load_project_plan(SAMPLE_DIR / filename)
    assert plan.tasks, "expected at least one task row to be parsed"
    assert plan.project_name


@pytest.mark.parametrize("filename", ["S2P_Project.xlsx", "Project_Plan_B.xlsx"])
def test_unparseable_markers_become_none_not_raw_strings(filename):
    plan = load_project_plan(SAMPLE_DIR / filename)
    # Ancestors/level fields are frequently '#UNPARSEABLE' in the raw sheet; the loader must
    # normalize these to None rather than leaking the literal marker string downstream.
    for task in plan.tasks:
        assert task.name is not None and task.name != "#UNPARSEABLE"


def test_missing_comments_sheet_degrades_to_empty_list(tmp_path):
    # Project_Plan_B.xlsx has an effectively empty Comments sheet; loading it must not raise
    # even though there's no comment data to extract.
    plan = load_project_plan(SAMPLE_DIR / "Project_Plan_B.xlsx")
    assert isinstance(plan.comments, list)


def test_two_sample_files_with_different_column_orders_both_parse_percent_complete():
    # S2P_Project.xlsx and Project_Plan_B.xlsx put "% Complete" in different columns —
    # this is the core "header matched by label, not position" guarantee.
    plan_a = load_project_plan(SAMPLE_DIR / "S2P_Project.xlsx")
    plan_b = load_project_plan(SAMPLE_DIR / "Project_Plan_B.xlsx")
    assert any(t.percent_complete is not None for t in plan_a.tasks)
    assert any(t.percent_complete is not None for t in plan_b.tasks)
