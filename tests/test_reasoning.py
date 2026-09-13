"""Tests for the reasoning layer's default (no-provider) behaviour."""
from datetime import date

from constraints import evaluate_festival, load_festivals
from models import FilmProfile
from reasoning import analyze_film, answer_question


def _verdicts(film):
    return [evaluate_festival(f, film, date(2026, 6, 1)).model_dump(mode="json")
            for f in load_festivals()]


FILM = FilmProfile(
    title="Monsoon Static", runtime_minutes=95, completion_date=date(2026, 3, 15),
    premiere_status="unscreened", genres=["horror", "thriller"], budget_usd=150,
).model_dump(mode="json")


class TestAnalyze:
    def test_returns_local_rag_without_provider(self):
        text, mode, cites = analyze_film(FILM, _verdicts(FilmProfile(**FILM)))
        assert mode == "local_rag"
        assert text
        assert cites

    def test_analysis_mentions_the_film(self):
        text, _, _ = analyze_film(FILM, _verdicts(FilmProfile(**FILM)))
        assert "Monsoon Static" in text

    def test_citations_are_serialisable_dicts(self):
        _, _, cites = analyze_film(FILM, _verdicts(FilmProfile(**FILM)))
        assert all(isinstance(c, dict) and "source_url" in c for c in cites)


class TestAsk:
    def test_answer_is_grounded_and_cited(self):
        text, mode, cites = answer_question("Which festivals need an unscreened premiere?")
        assert mode == "local_rag"
        assert text and cites

    def test_answer_returns_citation_dicts(self):
        _, _, cites = answer_question("What is the SXSW premiere rule?")
        assert any(c["festival_id"] == "sxsw" for c in cites)
