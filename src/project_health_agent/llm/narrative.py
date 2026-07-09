"""Turns a structured RAGResult into plain-English reasoning.

The RAG color and its contributing reasons are computed deterministically by
analysis/rag_engine.py — never by the LLM. The LLM's only job is to write that
verdict up the way a Professional Services lead would explain it to a client,
in a few tight sentences. If no LLM is configured (or it fails), a
template-based narrative built from the same structured reasons is used
instead, so weekly reports never block on an LLM outage.
"""

from __future__ import annotations

from project_health_agent.analysis.rag_engine import RAGResult
from project_health_agent.llm.fireworks_client import FireworksClient, safe_chat

SYSTEM_PROMPT = (
    "You are a Professional Services program-management analyst writing a weekly project "
    "health note for a VP audience. You are given a pre-computed RAG (Red/Amber/Green) "
    "status and the concrete data signals behind it. Write 3-5 sentences of plain-English "
    "reasoning that a VP could read in 15 seconds and repeat to a client with confidence. "
    "Rules: never invent facts not present in the input; never change or second-guess the "
    "RAG color itself, only explain it; mention concrete numbers where given; if caveats "
    "about data quality are present, fold them in briefly rather than omitting them; do not "
    "use bullet points, headers, or markdown — plain prose only."
)


def _fallback_narrative(rag: RAGResult) -> str:
    lead = {
        "Green": "This project is tracking in good health.",
        "Amber": "This project needs attention over the next 1-2 weeks.",
        "Red": "This project requires immediate leadership attention.",
    }[rag.overall.value]
    body = " ".join(rag.top_reasons[:4])
    tail = (" Data caveats: " + " ".join(rag.caveats)) if rag.caveats else ""
    gap = f" {rag.perception_gap}." if rag.perception_gap else ""
    return f"{lead} {body}{gap}{tail}".strip()


def generate_narrative(rag: RAGResult, client: FireworksClient) -> tuple[str, bool]:
    """Returns (narrative_text, was_llm_generated)."""
    user_prompt = (
        f"Project: {rag.project_name}\n"
        f"Computed RAG status: {rag.overall.value}\n\n"
        "Dimension-level findings:\n"
        + "\n".join(f"- {d.name} [{d.rag.value}]: {'; '.join(d.reasons)}" for d in rag.dimensions)
        + ("\n\nPerception gap vs PM-reported status: " + rag.perception_gap if rag.perception_gap else "")
        + ("\n\nData quality caveats: " + "; ".join(rag.caveats) if rag.caveats else "")
    )
    text = safe_chat(client, SYSTEM_PROMPT, user_prompt)
    if text:
        return text.strip(), True
    return _fallback_narrative(rag), False
