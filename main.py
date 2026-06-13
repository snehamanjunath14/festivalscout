"""FestivalScout API.

Run with:  uvicorn main:app --reload
Then open: http://127.0.0.1:8000

Endpoints:
  GET  /                 -> the web app
  GET  /api/festivals    -> raw festival dataset
  POST /api/analyze      -> full analysis (deterministic + agent + verification)
  POST /api/whatif       -> deterministic-only re-check (fast; for the what-if toggle)
  POST /api/ask          -> grounded Q&A with the Foundry agent (chat follow-up)
  POST /api/export-pdf   -> downloadable PDF of a strategy
"""
from datetime import date
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from constraints import evaluate_festival, load_festivals, strategy_notes
from foundry_client import ask_agent, query_foundry_agent
from models import AnalysisResponse, FilmProfile
from pdf_export import build_strategy_pdf
from verify import verify_agent_text

app = FastAPI(title="FestivalScout", version="2.0")
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/festivals")
def festivals() -> dict:
    return {"festivals": load_festivals()}


def _deterministic(film: FilmProfile):
    today = date.today()
    data = load_festivals()
    verdicts = [evaluate_festival(f, film, today) for f in data]
    notes = strategy_notes(verdicts, film)
    open_fees = [
        v.estimated_fee_usd for v in verdicts
        if v.verdict in ("fit", "caution") and v.estimated_fee_usd is not None
    ]
    total = round(sum(open_fees), 2) if open_fees else None
    return data, verdicts, notes, total


@app.post("/api/analyze", response_model=AnalysisResponse)
def analyze(film: FilmProfile) -> AnalysisResponse:
    data, verdicts, notes, total = _deterministic(film)

    film_json = film.model_dump_json(indent=2)
    verdicts_json = "[" + ",".join(v.model_dump_json() for v in verdicts) + "]"
    agent_text, mode = query_foundry_agent(film_json, verdicts_json)
    verification = verify_agent_text(agent_text or "", data)

    return AnalysisResponse(
        film=film, verdicts=verdicts, strategy_notes=notes,
        total_estimated_fees_usd=total, agent_analysis=agent_text,
        agent_mode=mode, verification=verification,
    )


@app.post("/api/whatif", response_model=AnalysisResponse)
def whatif(film: FilmProfile) -> AnalysisResponse:
    """Deterministic only: instant, no agent call. Powers the what-if toggle."""
    _data, verdicts, notes, total = _deterministic(film)
    return AnalysisResponse(
        film=film, verdicts=verdicts, strategy_notes=notes,
        total_estimated_fees_usd=total, agent_analysis=None,
        agent_mode="unavailable", verification=[],
    )


class AskRequest(BaseModel):
    question: str
    film_context: str = ""


@app.post("/api/ask")
def ask(req: AskRequest) -> dict:
    answer, mode = ask_agent(req.question, req.film_context)
    return {"answer": answer, "mode": mode}


@app.post("/api/export-pdf")
def export_pdf(payload: dict) -> Response:
    pdf = build_strategy_pdf(payload)
    title = (payload.get("film", {}).get("title") or "strategy").replace(" ", "_")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="FestivalScout_{title}.pdf"'},
    )
