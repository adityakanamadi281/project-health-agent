"""Thin client around the Fireworks AI chat-completions endpoint.

Fireworks exposes an OpenAI-compatible `/chat/completions` API, so this is a
plain `httpx` call — no vendor SDK dependency required. The API key, model,
base URL, temperature, and timeouts all come from `Settings` (env-driven),
never hardcoded.

If `FIREWORKS_API_KEY` is not configured, or the call fails after retries,
every public function here falls back to a deterministic, template-based
result instead of raising — the assignment explicitly requires the agent to
"handle incomplete or messy data gracefully", and a missing LLM credential is
just another form of incomplete input. The fallback is clearly labelled as
such in its output so nobody mistakes it for an LLM-authored narrative.
"""

from __future__ import annotations

import json
import logging

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from project_health_agent.config import Settings

logger = logging.getLogger(__name__)


class FireworksUnavailable(RuntimeError):
    """Raised internally when the LLM cannot be reached; always caught by callers."""


class FireworksClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def available(self) -> bool:
        return self._settings.has_llm

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.HTTPError, FireworksUnavailable)),
    )
    def chat(self, system_prompt: str, user_prompt: str, *, json_mode: bool = False) -> str:
        if not self._settings.has_llm:
            raise FireworksUnavailable("FIREWORKS_API_KEY is not set")

        payload: dict = {
            "model": self._settings.fireworks_model,
            "temperature": self._settings.llm_temperature,
            "max_tokens": self._settings.llm_max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self._settings.fireworks_api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._settings.fireworks_base_url.rstrip('/')}/chat/completions"

        try:
            with httpx.Client(timeout=self._settings.llm_timeout_seconds) as client:
                resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPError as exc:
            logger.warning("Fireworks call failed: %s", exc)
            raise
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise FireworksUnavailable(f"Unexpected Fireworks response shape: {exc}") from exc


def safe_chat(client: FireworksClient, system_prompt: str, user_prompt: str, *, json_mode: bool = False) -> str | None:
    """Returns None (never raises) if the LLM is unavailable or fails after retries."""
    try:
        return client.chat(system_prompt, user_prompt, json_mode=json_mode)
    except Exception as exc:  # noqa: BLE001 - deliberate broad catch, this must never crash the pipeline
        logger.warning("LLM narrative generation unavailable, using fallback: %s", exc)
        return None
