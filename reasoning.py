"""Reasoning layer — turns retrieved guideline passages into grounded analysis.

Provider is chosen by the LLM_PROVIDER env var:
  - "none"   (default): deterministic local synthesis. No API key, no network,
     no cloud bill. Composes the analysis from the deterministic verdicts and
     the retrieved passages, so the app produces a real, cited answer out of the
     box. This is what makes the project reproducible after a clean clone.
  - "openai": any OpenAI-compatible chat endpoint (OpenAI, OpenRouter, a local
     Ollama/LM Studio server, etc.). Configure OPENAI_API_KEY, OPENAI_MODEL,
     and optionally OPENAI_BASE_URL.
  - "azure":  the original Azure OpenAI path, kept as an optional flag.

Whatever the provider, retrieval runs first and its passages are passed as
grounding context. If a remote provider errors, we fall back to local synthesis
rather than failing — the answer is never worse than "grounded and cited".
"""
from __future__ import annotations

import os

from retrieval import Citation, get_retriever

try:  # optional; only needed for remote providers
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # noqa: BLE001
    pass

PROVIDER = os.getenv("LLM_PROVIDER", "none").lower()

ANALYSIS_SYSTEM = (
    "You are FestivalScout's analysis layer. You receive a film's profile, a "
    "deterministic eligibility report computed in code, and retrieved passages "
    "from festival guidelines. Add nuance the report cannot compute: selection "
    "context, category fit, and premiere strategy. Cite the festivals you rely "
    "on. Never contradict the report's dates or fees."
)
CHAT_SYSTEM = (
    "You are FestivalScout, a festival-strategy assistant. Answer using only the "
    "retrieved festival guideline passages provided. Cite the festivals you use. "
    "If the passages do not cover something, say so rather than guessing."
)


def _grounding_block(citations: list[Citation]) -> str:
    return "\n".join(
        f"[{i + 1}] {c.festival_name} ({c.section}): {c.snippet}"
        for i, c in enumerate(citations)
    )


# --------------------------------------------------------------------------- #
# Local deterministic synthesis (default)
# --------------------------------------------------------------------------- #
def _local_analysis(film: dict, verdicts: list[dict], citations: list[Citation]) -> str:
    fits = [v for v in verdicts if v["verdict"] == "fit"]
    cautions = [v for v in verdicts if v["verdict"] == "caution"]
    blocked = [v for v in verdicts if v["verdict"] == "not_eligible"]

    lines: list[str] = []
    title = film.get("title", "Your film")
    if fits:
        names = ", ".join(v["festival_name"].split(" (")[0] for v in fits[:4])
        lines.append(
            f"{title} is a clean fit for {len(fits)} festival(s): {names}. "
            "Prioritise these by deadline and Oscar-qualifying status."
        )
    if cautions:
        c = cautions[0]
        reason = (c.get("warnings") or c.get("reasons") or ["review the guidelines"])[0]
        lines.append(
            f"{len(cautions)} festival(s) are worth a look but carry a caution — "
            f"e.g. {c['festival_name'].split(' (')[0]}: {reason}"
        )
    if blocked:
        names = ", ".join(v["festival_name"].split(" (")[0] for v in blocked[:3])
        lines.append(
            f"Ineligible right now: {names}. The verdict cards above give the exact rule."
        )
    if citations:
        top = citations[0]
        lines.append(
            f"From the guidelines: “{top.snippet}” ({top.festival_name})."
        )
    lines.append(
        "This analysis is composed locally from the retrieved guideline passages "
        "and the deterministic report; set LLM_PROVIDER to add a generative model."
    )
    return " ".join(lines)


def _local_answer(question: str, citations: list[Citation]) -> str:
    if not citations:
        return (
            "The festival guidelines I have indexed don't cover that. The verdict "
            "cards above are computed locally and remain accurate."
        )
    top = citations[:3]
    body = " ".join(f"{c.snippet} ({c.festival_name})." for c in top)
    return f"Based on the festival guidelines: {body}"


# --------------------------------------------------------------------------- #
# Remote providers (optional)
# --------------------------------------------------------------------------- #
def _call_openai(system: str, user: str) -> str:
    import httpx

    base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    key = os.getenv("OPENAI_API_KEY", "")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    r = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.4,
            "max_tokens": 600,
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _call_azure(system: str, user: str) -> str:
    import httpx

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("FOUNDRY_API_KEY", "")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini")
    version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={version}"
    r = httpx.post(
        url,
        headers={"api-key": key, "Content-Type": "application/json"},
        json={
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.4,
            "max_tokens": 600,
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _remote(system: str, user: str) -> tuple[str | None, str]:
    """Return (text, mode) or (None, provider) on failure."""
    try:
        if PROVIDER == "openai":
            return _call_openai(system, user), "openai"
        if PROVIDER == "azure":
            return _call_azure(system, user), "azure"
    except Exception as e:  # noqa: BLE001
        print(f"[reasoning] provider '{PROVIDER}' failed, using local synthesis: {e}")
    return None, PROVIDER


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def analyze_film(film: dict, verdicts: list[dict], k: int = 5) -> tuple[str, str, list[dict]]:
    """Returns (analysis_text, mode, citations)."""
    query = (
        f"{film.get('title', '')} {film.get('runtime_minutes', '')} minute "
        f"{' '.join(film.get('genres', []))} film, premiere status "
        f"{film.get('premiere_status', '')}, eligibility and premiere strategy"
    )
    citations = get_retriever().search(query, k=k)
    cit_dicts = [c.as_dict() for c in citations]

    if PROVIDER in ("openai", "azure"):
        user = (
            f"FILM PROFILE:\n{film}\n\n"
            f"DETERMINISTIC ELIGIBILITY REPORT:\n{verdicts}\n\n"
            f"RETRIEVED GUIDELINE PASSAGES:\n{_grounding_block(citations)}\n\n"
            "Write a grounded analysis in under 250 words, citing the passages."
        )
        text, mode = _remote(ANALYSIS_SYSTEM, user)
        if text is not None:
            return text, mode, cit_dicts

    return _local_analysis(film, verdicts, citations), "local_rag", cit_dicts


def answer_question(question: str, film_context: str = "", k: int = 5) -> tuple[str, str, list[dict]]:
    """Returns (answer_text, mode, citations)."""
    citations = get_retriever().search(question, k=k)
    cit_dicts = [c.as_dict() for c in citations]

    if PROVIDER in ("openai", "azure"):
        user = (
            f"FILM CONTEXT:\n{film_context}\n\n"
            f"RETRIEVED GUIDELINE PASSAGES:\n{_grounding_block(citations)}\n\n"
            f"QUESTION: {question}\n\n"
            "Answer in under 180 words using only the passages, with citations."
        )
        text, mode = _remote(CHAT_SYSTEM, user)
        if text is not None:
            return text, mode, cit_dicts

    return _local_answer(question, citations), "local_rag", cit_dicts
