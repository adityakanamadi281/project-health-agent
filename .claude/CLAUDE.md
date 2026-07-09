# Project instructions for Claude Code

This file is read automatically by Claude Code when working in this repository. It exists so
future agent sessions (or teammates using Claude Code) don't have to rediscover the design
rules below by reading every module.

## What this project is

An AI-powered Project Health Reporting Agent for Zycus Professional Services. It reads
Smartsheet-style project-plan `.xlsx` exports, computes a Red/Amber/Green status
**deterministically**, explains that status in plain English using an LLM (Fireworks AI), and
synthesizes a monthly cross-project executive presentation. Full design rationale lives in
`docs/architecture.md`; the scoring rules live in `docs/RAG_METHODOLOGY.md`.

## Hard rules for any change in this repo

1. **Never let the LLM decide the RAG color.** `analysis/rag_engine.py` is the only place the
   color is computed. If you add a new signal, it must be scored by a threshold in
   `config.py`, not by asking an LLM to judge it. The LLM (`llm/`) only narrates an
   already-computed `RAGResult` — it receives that result as input and is explicitly told not
   to change it.
2. **No hardcoded thresholds, API keys, file paths, or project-specific values in code.**
   Everything tunable lives in `config.py` as an environment variable with a sensible default
   (see `.env.example`). If you find yourself writing a magic number in `analysis/` or
   `llm/`, it belongs in `Settings` instead.
3. **Every new field read from a spreadsheet must be optional and matched by header label**,
   not column index (see `TASK_HEADER_ALIASES` / `SUMMARY_ROW_ALIASES` in
   `ingestion/excel_loader.py`). The two sample plans already prove column order and presence
   vary between projects — assume the next one will too.
4. **Anything that can fail (LLM call, missing sheet, unparseable cell, missing file) must
   degrade gracefully, not raise.** Look at `llm/fireworks_client.safe_chat()` and
   `ingestion/excel_loader.py`'s `DataQualityNote` pattern before adding a new failure mode.
5. **Never fabricate a trend.** `reporting/monthly_synthesis.py` only reports week-over-week
   movement once `outputs/history.jsonl` actually has ≥2 runs for a project; otherwise it says
   so explicitly. Don't backfill or simulate history to make the deck look more complete.
6. **Keep the LLM's job narrow.** Every prompt in `llm/narrative.py` and
   `reporting/monthly_synthesis.py` is given already-computed, structured data as input and
   asked only to phrase it for a human audience — never given the raw spreadsheet, and never
   asked to compute a number that Python could compute more reliably.

## Common commands

```bash
uv sync                                   # install/refresh the environment
uv run project-health run-weekly          # weekly RAG reports for every plan in data/sample_plans/
uv run project-health run-monthly         # weekly reports + the executive .pptx
uv run project-health schedule-weekly     # bonus: recurring cron (blocks the terminal)
uv run pytest                             # unit tests (analysis/ and ingestion/ are covered)
uv run ruff check src tests               # lint
```

## Where to look first for common tasks

- "Change how RAG is scored" → `analysis/rag_engine.py` + update `docs/RAG_METHODOLOGY.md` to match.
- "A new export has different columns" → `ingestion/excel_loader.py`'s alias dicts.
- "Change the narrative tone/prompt" → `llm/narrative.py` (`SYSTEM_PROMPT`) or
  `reporting/monthly_synthesis.py` (`SYSTEM_PROMPT`).
- "Change the deck's slides/design" → `presentation/deck_builder.py`.
- "Add a new CLI command" → `cli.py`, following the existing `run_weekly` / `run_monthly` pattern.
