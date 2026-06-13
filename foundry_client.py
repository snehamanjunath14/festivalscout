"""Talks to your Foundry agent (festivalscout-agent), which is grounded in the
festival-guidelines-kb knowledge base via Foundry IQ agentic retrieval.

Two modes, tried in order:
  1. foundry_agent - Azure AI Projects SDK. The real Foundry IQ path: the agent
     plans subqueries against the knowledge base and returns a grounded answer.
  2. fallback      - direct gpt-4.1-mini chat-completions REST call, grounded
     with the structured data we pass in. Keeps the app demoable; the UI labels
     the mode honestly.

If mode 1 errors on your machine, open your agent in the Foundry portal
playground, click "View code", and compare its endpoint / api version / agent
identifier with your .env values. Foundry's SDK surface moves fast; the portal
sample is always current.
"""
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

PROJECT_ENDPOINT = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "")
API_KEY = os.getenv("FOUNDRY_API_KEY", "")
AGENT_NAME = os.getenv("FOUNDRY_AGENT_NAME", "festivalscout-agent")
AOAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AOAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini")
AOAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

ANALYSIS_SYSTEM = (
    "You are FestivalScout's analysis layer. You receive a film's profile and a "
    "deterministic eligibility report computed in code. Using the festival guidelines "
    "in your knowledge base, add nuance the report cannot compute: selection-odds "
    "context, category fit, premiere strategy, and guideline fine print worth reading "
    "before paying a fee. Cite your sources. Never contradict the deterministic "
    "report's dates or fees; if the knowledge base disagrees, flag it explicitly."
)
CHAT_SYSTEM = (
    "You are FestivalScout, a festival-strategy assistant grounded in a knowledge base "
    "of festival submission guidelines. Answer the filmmaker's question using the "
    "guidelines, cite sources, and stay concise. If the knowledge base doesn't cover "
    "something, say so rather than guessing."
)


def _run_agent(system_prompt: str, user_prompt: str) -> tuple[str | None, str]:
    """Try the Foundry agent, then the direct-model fallback. Returns (text, mode)."""
    # --- Mode 1: Foundry agent ---
    try:
        from azure.ai.projects import AIProjectClient  # type: ignore
        from azure.identity import DefaultAzureCredential  # type: ignore

        client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=DefaultAzureCredential())
        agents = client.agents
        agent = next((a for a in agents.list_agents() if getattr(a, "name", "") == AGENT_NAME), None)
        if agent is None:
            raise RuntimeError(f"Agent named {AGENT_NAME!r} not found.")
        thread = agents.threads.create()
        agents.messages.create(thread_id=thread.id, role="user", content=user_prompt)
        run = agents.runs.create_and_process(thread_id=thread.id, agent_id=agent.id)
        if getattr(run, "status", "") == "failed":
            raise RuntimeError(f"Agent run failed: {getattr(run, 'last_error', '?')}")
        for m in agents.messages.list(thread_id=thread.id):
            if m.role == "assistant":
                parts = [p.text.value for p in m.content if getattr(p, "text", None)]
                if parts:
                    return "\n".join(parts), "foundry_agent"
        raise RuntimeError("No assistant message returned.")
    except Exception as agent_err:  # noqa: BLE001
        print(f"[foundry_client] Agent path failed, using fallback: {agent_err}")

    # --- Mode 2: direct Azure OpenAI ---
    if not (AOAI_ENDPOINT and API_KEY):
        return None, "unavailable"
    try:
        url = (
            f"{AOAI_ENDPOINT.rstrip('/')}/openai/deployments/{AOAI_DEPLOYMENT}"
            f"/chat/completions?api-version={AOAI_API_VERSION}"
        )
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 600,
            "temperature": 0.4,
        }
        r = httpx.post(url, headers={"api-key": API_KEY, "Content-Type": "application/json"},
                       json=payload, timeout=60)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"], "fallback"
    except Exception as e:  # noqa: BLE001
        print(f"[foundry_client] Fallback also failed: {e}")
        return None, "unavailable"


def query_foundry_agent(film_json: str, verdicts_json: str) -> tuple[str | None, str]:
    prompt = (
        f"FILM PROFILE:\n{film_json}\n\n"
        f"DETERMINISTIC ELIGIBILITY REPORT (computed in code):\n{verdicts_json}\n\n"
        "Add your grounded analysis in under 250 words."
    )
    return _run_agent(ANALYSIS_SYSTEM, prompt)


def ask_agent(question: str, film_context: str) -> tuple[str | None, str]:
    prompt = (
        f"The filmmaker's film profile for context:\n{film_context}\n\n"
        f"Their question:\n{question}\n\n"
        "Answer using the festival guidelines in under 180 words, with citations."
    )
    return _run_agent(CHAT_SYSTEM, prompt)
