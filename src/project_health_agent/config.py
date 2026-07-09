"""Centralised, environment-driven configuration.

No credentials or magic numbers are hardcoded here: everything is read from the
environment (or a local `.env` file via python-dotenv) so the same code runs
unchanged in a laptop, CI, or a scheduled server job. If FIREWORKS_API_KEY is
absent, the agent still runs end-to-end — the LLM layer degrades to a
deterministic template-based narrative (see llm/fireworks_client.py) rather
than failing the whole pipeline.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Fireworks LLM ---
    fireworks_api_key: str | None = Field(default=None, alias="FIREWORKS_API_KEY")
    fireworks_model: str = Field(
        default="accounts/fireworks/models/llama-v3p1-70b-instruct",
        alias="FIREWORKS_MODEL",
    )
    fireworks_base_url: str = Field(
        default="https://api.fireworks.ai/inference/v1", alias="FIREWORKS_BASE_URL"
    )
    llm_temperature: float = Field(default=0.2, alias="LLM_TEMPERATURE")
    llm_max_tokens: int = Field(default=900, alias="LLM_MAX_TOKENS")
    llm_timeout_seconds: float = Field(default=45.0, alias="LLM_TIMEOUT_SECONDS")

    # --- I/O ---
    reports_output_dir: Path = Field(default=Path("outputs"), alias="REPORTS_OUTPUT_DIR")
    data_input_dir: Path = Field(default=Path("data/sample_plans"), alias="DATA_INPUT_DIR")

    # --- RAG thresholds (tunable without touching code) ---
    schedule_slip_amber_days: int = Field(default=5, alias="SCHEDULE_SLIP_AMBER_DAYS")
    schedule_slip_red_days: int = Field(default=15, alias="SCHEDULE_SLIP_RED_DAYS")
    milestone_amber_pct: float = Field(default=0.85, alias="MILESTONE_AMBER_PCT")
    milestone_red_pct: float = Field(default=0.70, alias="MILESTONE_RED_PCT")
    stale_task_days: int = Field(default=14, alias="STALE_TASK_DAYS")

    @property
    def has_llm(self) -> bool:
        return bool(self.fireworks_api_key)


def get_settings() -> Settings:
    """Fresh settings load (cheap; avoids stale env in long-running schedulers)."""
    return Settings()
