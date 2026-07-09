# Project Health Reporting Framework
### Phase 1 — RAG Status Methodology

## 1. Purpose
Define a repeatable, data-driven way to assign a Red/Amber/Green (RAG) status to each project, so leadership gets consistent visibility without manually polling PMs. The framework is designed around the fields actually present in the PM-maintained project plans (task lists with status, dates, float, criticality, and comments), so it can be automated today, with clear notes on where data is currently missing.

## 2. Health Dimensions & Signals

| Dimension | Signal(s) used | Source field(s) |
|---|---|---|
| **Schedule Slippage** | Days behind baseline; % of tasks with negative `Variance`; whether the *current* phase/milestone end date has passed | `Baseline Start/Finish`, `Start/End Date`, `Variance` |
| **Milestone Health** | % Complete vs. time-elapsed (are we on pace); count of overdue "Not Started" tasks whose start date has passed; phase-level roll-up | `Status`, `% Complete`, `Start Date`, `Phase/Milestone` |
| **Critical Path Risk** | Tasks flagged `Critical? = TRUE` with negative `Total Float` or Red task-level RAG | `Critical?`, `Total Float`, `RAG` |
| **Blockers** | Tasks `On Hold`, tasks with unmet `Predecessors`, tasks flagged `At Risk? = High`, unresolved `Status Comment` entries | `On Hold?`, `Predecessors`, `At Risk?`, `Status Comment` |
| **Budget Burn** | *Not present in current data set* — placeholder dimension for when cost/hours-burned data becomes available (e.g., time-tracking or PSA export) | *(future: Budget vs. Actual Spend)* |
| **Stakeholder Sentiment** | Proxy signals only: frequency/tone of `Comments`, repeated sign-off delays (client tasks stuck "Not Started"/"In Progress" past due), count of client-owned action items overdue | `Comments`, `Owner`/`Assigned To`, `Status` |

## 3. Scoring Logic
Each dimension is scored **Green (0) / Amber (1) / Red (2)** at the project level using thresholds below, then combined into a weighted composite. Weights reflect what's most predictive of delivery risk in a PS engagement: schedule and critical-path issues matter more than sentiment, which is currently only a soft proxy.

| Dimension | Weight | Green | Amber | Red |
|---|---|---|---|---|
| Schedule Slippage | 30% | On/ahead of baseline | ≤10% of tasks slipped, <2 weeks variance | >10% of tasks slipped or any phase >2 weeks late |
| Milestone Health | 25% | % Complete ≥ time-elapsed% | Within 10 pts of pace | >10 pts behind pace |
| Critical Path Risk | 20% | No critical tasks Red/negative float | 1–2 critical tasks at risk | ≥3 critical tasks Red or negative float |
| Blockers | 15% | No open blockers | 1–3 open blockers, none client-stalled >1wk | ≥4 blockers or any client item stalled >2wks |
| Stakeholder Sentiment (proxy) | 10% | No overdue client actions/negative comments | 1–2 overdue client items | ≥3 overdue client items or explicit escalation comment |

**Composite score → RAG:**
- **Green:** weighted score ≤ 0.5
- **Amber:** weighted score 0.5–1.2
- **Red:** weighted score > 1.2

A **hard override to Red** applies regardless of score if: any critical-path task is Red AND has negative float, or a phase-level milestone end date has passed with the phase still "In Progress."

## 4. Key Assumptions
- No cost/budget data exists in the current source files — Budget Burn is scaffolded but excluded from today's score (redistribute its weight proportionally, or treat as "Grey/Unknown" until available).
- Stakeholder sentiment is inferred from behavior (delays, comments) rather than direct survey data — treated as a proxy, weighted lowest, and flagged as an area to strengthen later (e.g., a lightweight PM pulse-check field).
- "Today" is taken from each plan's `Today's Date` field in the Summary sheet, used to compute time-elapsed% for pacing comparisons.
- Task-level `RAG` and `Schedule Health` columns already entered by PMs are treated as a secondary sanity check, not the primary signal — the goal is to reduce reliance on manual PM judgment over time.
- Projects with `On Hold?` = TRUE tasks that are also `Not Applicable?` are excluded from blocker counts (deliberately descoped, not stalled).

## 5. Output
Each project gets: an overall RAG, the four (soon five) dimension sub-scores, and a short auto-generated explanation ("Red: 3 critical tasks behind schedule; client sign-off overdue 12 days") — giving leadership the "why," not just the color.
