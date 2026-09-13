"""Tests for the local retrieval layer."""
from retrieval import Retriever, build_corpus, get_retriever


class TestCorpus:
    def test_corpus_is_populated(self):
        chunks = build_corpus()
        assert len(chunks) > 30

    def test_every_chunk_has_a_citation_source(self):
        for c in build_corpus():
            assert c.festival_id and c.section and c.text
            assert c.source_url.startswith("http")

    def test_premiere_rules_are_chunked(self):
        sections = {c.section for c in build_corpus()}
        assert "premiere" in sections
        assert "deadline" in sections


class TestSearch:
    def setup_method(self):
        self.r = Retriever(backend="tfidf")

    def test_default_backend_is_tfidf(self):
        assert self.r.backend == "tfidf"

    def test_search_returns_citations(self):
        cites = self.r.search("horror feature premiere", k=5)
        assert 1 <= len(cites) <= 5
        assert cites[0].score > 0

    def test_results_are_score_sorted(self):
        cites = self.r.search("submission deadline fee", k=5)
        scores = [c.score for c in cites]
        assert scores == sorted(scores, reverse=True)

    def test_strict_premiere_query_surfaces_sxsw(self):
        cites = self.r.search("feature not released online screened anywhere strict premiere", k=5)
        assert any(c.festival_id == "sxsw" for c in cites)

    def test_genre_query_surfaces_genre_festivals(self):
        cites = self.r.search("horror sci-fi fantasy genre film", k=5)
        assert any(c.festival_id in ("fantastic-fest", "sitges") for c in cites)

    def test_empty_query_returns_nothing(self):
        assert self.r.search("", k=5) == []

    def test_citation_serialises(self):
        cites = self.r.search("deadline", k=1)
        d = cites[0].as_dict()
        assert set(d) >= {"festival_name", "section", "snippet", "source_url", "score"}


class TestSingleton:
    def test_get_retriever_is_cached(self):
        assert get_retriever() is get_retriever()
