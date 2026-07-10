# Project Health Reporting Agent

Automated Red/Amber/Green (RAG) health reporting and portfolio-level monthly executive synthesis for Zycus Professional Services project plans. 

## 📋 Overview

The **Project Health Reporting Agent** automates the ingestion, analysis, and reporting workflow for messy, Smartsheet-style project plan exports (`.xlsx`). 

Rather than relying entirely on LLMs to subjectively guess the health of a project (which introduces high variance and hallucinations), the agent employs a robust **compute deterministically, narrate with an LLM** architecture:
1. **Ingests** Smartsheet exports, handling missing sheets, changing column ordering, and `#UNPARSEABLE` errors.
2. **Scores RAG Status** deterministically in Python using weighted rules (Schedule Slippage, Milestone Pacing, Critical Path Risk, Blockers, Stakeholder Sentiment).
3. **Generates Prose** explaining the health status using Fireworks AI, falling back to a structured template if no API key is available.
4. **Synthesizes Monthly Portfolio Reports** as a polished, 6-slide PowerPoint presentation (`.pptx`) highlighting key trends, risks, and recommended actions across all projects.

---

## ✨ Features

- **Fault-Tolerant Excel Ingestion**: Flexibly processes varying Smartsheet `.xlsx` formats. Matches columns by header labels/aliases rather than fixed column index, and safely handles `#UNPARSEABLE` cells.
- **Deterministic RAG Engine**: Computes overall and dimensional (Schedule, Milestones, Scope, Sentiment, etc.) statuses via rigorous rule scoring. High-severity slips automatically trigger Red overrides.
- **LLM-Powered Narrative Generation**: Narrates the computed RAG verdict into high-quality, professional executive summaries using the gpt-oss-20b  model via Fireworks AI.
- **Template Fallback Mode**: Gracefully runs without an API key by generating text summaries using deterministic, pre-built template fallbacks.
- **Portfolio-Level Executive Deck Synthesis**: Aggregates week-over-week reports to identify cross-project risks, anomalies, and positive trends. Outputs native tables/charts to a `.pptx` presentation.
- **Flexible Execution**: Can be run ad-hoc for weekly/monthly cycles, or run as a recurring service using the built-in Scheduler.

---

## 🛠️ Tools & Tech Stack

- **Core Runtime**: Python 3.11+
- **Dependency Management**: [uv](https://docs.astral.sh/uv/) (extremely fast Python package installer and resolver)
- **Data Ingestion**: `openpyxl` (for spreadsheet loading & parsing)
- **LLM Inference**: [Fireworks AI API](https://fireworks.ai/) (gpt-oss-20b )
- **CLI Development**: `typer` & `rich` (for interactive, styled terminal outputs)
- **Presentation Generation**: `python-pptx` (for native PowerPoint slides, charts, and tables)
- **Scheduling**: `apscheduler` (for cron-based recurring execution)
- **Testing**: `pytest` (for unit testing loaders and RAG scoring rules)
- **Linting & Formatting**: `ruff`

---

## ⚙️ Install & Setup

### Prerequisites
- Python 3.11 or higher
- [uv](https://docs.astral.sh/uv/) package manager installed:
  ```bash
  # On macOS/Linux
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # On Windows (PowerShell)
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

### Installation & Configuration
1. Clone the repository:
   ```bash
   git clone https://github.com/adityakanamadi281/project-health-agent.git 
   cd project-health-agent
   ```
2. Copy and configure the environment variables:
   ```bash
   cp .env.example .env
   ```
   Open the `.env` file and configure your `FIREWORKS_API_KEY` (if you do not have one, the agent will gracefully run in template fallback mode).
3. Synchronize dependencies using `uv`:
   ```bash
   uv sync
   ```

---

## 📂 Project Structure

```
project-health-agent/
├── .claude/                        # Claude Code settings and slash commands
│   ├── CLAUDE.md                   # Hard rules + common commands for agentic coding
│   └── settings.json               # Sandbox permissions
├── data/
│   ├── sample_plans/               # Provided sample Smartsheet exports
│   └── incoming/                   # Landing folder for user-provided project plans (.xlsx)
├── docs/
│   ├── RAG_METHODOLOGY.md          # 1-page RAG framework and scoring criteria
│   ├── architecture.md             # System architecture and data flow diagram
│   └── diagrams/                   # Mermaid sources and rendered diagrams
├── outputs/
│   ├── weekly/<date>/              # Weekly Markdown + JSON reports per project
│   ├── monthly/<date>/             # monthly_synthesis.json + PowerPoint executive deck
│   └── history.jsonl               # Append-only run database (used for week-over-week trends)
├── scripts/
│   └── run_weekly.sh               # Lightweight shell script for running via system cron
├── src/project_health_agent/
│   ├── cli.py                      # Typer CLI entrypoint
│   ├── config.py                   # Central Settings loaded from env/.env
│   ├── models.py                   # Pydantic models mapping normalized entities
│   ├── analysis/
│   │   ├── signals.py              # Extract schedule variance, blockers, milestone pacing, sentiment
│   │   └── rag_engine.py           # Deterministic RAG score calculation
│   ├── ingestion/
│   │   └── excel_loader.py         # Fault-tolerant parser for Smartsheet exports
│   ├── llm/
│   │   ├── fireworks_client.py     # Httpx client for Fireworks AI API (with fallback handler)
│   │   └── narrative.py            # Converts RAG verdicts to plain-English narratives
│   ├── presentation/
│   │   └── deck_builder.py         # python-pptx script rendering slides, tables, and native charts
│   ├── reporting/
│   │   ├── history.py              # Historical log updater
│   │   ├── monthly_synthesis.py    # Cross-project trend/risk/recommendation synthesizer
│   │   └── weekly_report.py        # Orchestrates the per-project weekly reporting cycle
│   └── scheduler/
│       └── weekly_job.py           # Cron scheduler wrapper (APScheduler)
├── tests/                          # Automated unit tests for excel parser & RAG calculations
├── pyproject.toml                  # Project packaging and dependencies definition
└── uv.lock                         # Lockfile for reproducible builds
```

---

## 🚀 Execution & Usage

### 1. Run the Weekly Agent
Reads every `.xlsx` project plan in the input directory and emits a weekly report (`.md` and `.json`) for each:
```bash
uv run project-health run-weekly
```
*Note: To run on your custom files placed in the `data/incoming` folder:*
```bash
uv run project-health run-weekly --input-dir data/incoming
```

### 2. Run the Monthly Executive Deck Generator
Processes weekly reports across all plans, synthesizes portfolio stats, and renders the 6-slide PowerPoint deck:
```bash
uv run project-health run-monthly
```

### 3. Run on a Recurring Schedule
Blocks the terminal and executes the weekly job on a cron schedule (every Monday at 7:00 AM by default):
```bash
uv run project-health schedule-weekly --day-of-week mon --hour 7 --minute 0
```

---

## 🧪 Testing

Run unit tests covering ingestion rules and RAG calculations using `pytest`:
```bash
uv run pytest
```
