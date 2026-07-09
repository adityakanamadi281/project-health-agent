Run the full Project Health Reporting Agent pipeline and summarize the results for me:

1. Run `uv sync` to make sure the environment is current.
2. Run `uv run project-health run-monthly` (this also runs the weekly step for every plan in
   `data/sample_plans/`, then builds the executive deck).
3. Read the generated Markdown reports under `outputs/weekly/<today>/` and the
   `outputs/monthly/<today>/monthly_synthesis.json`.
4. Give me a short summary: which projects are Red/Amber/Green, the top 1-2 reasons for each,
   and the headline + emerging risks from the monthly synthesis. Flag clearly if
   `FIREWORKS_API_KEY` wasn't set (narratives will say `narrative_source: template-fallback`).
