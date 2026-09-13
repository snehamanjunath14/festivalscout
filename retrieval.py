"""Local retrieval layer — the agentic knowledge layer, rebuilt without Azure.

FestivalScout originally grounded its analysis in a Foundry IQ knowledge base
(Azure AI Search agentic retrieval). That made the project depend on a paid
cloud resource group: delete it and the app is dead code. This module rebuilds
the same capability locally.

What it does:
  1. Chunks the festival guideline corpus into short, cited passages
     (built from data/festivals.json, plus any markdown in data/kb/).
  2. Indexes the chunks as vectors.
  3. Retrieves the top-k passages for a query, each with a citation back to the
     festival and its official source URL.

Two backends, chosen by the RETRIEVAL_BACKEND env var:
  - "tfidf" (default): a self-contained TF-IDF vector index implemented here in
    pure Python. Zero third-party dependencies, so the repo runs after a plain
    `pip install -r requirements.txt` — the whole point of the rebuild.
  - "dense": sentence-transformers embeddings (all-MiniLM-L6-v2 by default),
    an optional quality upgrade installed via `pip install -r requirements-ml.txt`.
    Falls back to tfidf with a printed notice if the package is missing.

The retrieval interface is identical across backends, so the reasoning layer
never needs to know which one is active.
"""
from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
FESTIVALS_PATH = DATA_DIR / "festivals.json"
KB_DIR = DATA_DIR / "kb"  # optional hand-written guideline docs (*.md)

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


@dataclass
class Chunk:
    """One retrievable passage with everything needed to cite it."""

    id: str
    festival_id: str
    festival_name: str
    section: str
    text: str
    source_url: str

    def citation(self) -> "Citation":
        return Citation(
            festival_id=self.festival_id,
            festival_name=self.festival_name,
            section=self.section,
            snippet=self.text,
            source_url=self.source_url,
            score=0.0,
        )


@dataclass
class Citation:
    festival_id: str
    festival_name: str
    section: str
    snippet: str
    source_url: str
    score: float

    def as_dict(self) -> dict:
        return {
            "festival_id": self.festival_id,
            "festival_name": self.festival_name,
            "section": self.section,
            "snippet": self.snippet,
            "source_url": self.source_url,
            "score": round(self.score, 4),
        }


# --------------------------------------------------------------------------- #
# Corpus construction
# --------------------------------------------------------------------------- #
def _festival_chunks(f: dict) -> list[Chunk]:
    """Turn one structured festival record into several cited passages."""
    fid = f["id"]
    name = f["name"]
    url = f["source_url"]
    fmt = f["film_format"]
    chunks: list[Chunk] = []

    def add(section: str, text: str) -> None:
        text = " ".join(text.split())
        if text:
            chunks.append(Chunk(f"{fid}#{section}", fid, name, section, text, url))

    oscar = "Oscar-qualifying" if f.get("oscar_qualifying") else "not Oscar-qualifying"
    add(
        "overview",
        f"{name} is a {fmt} category in {f['location']}. It is {oscar}. "
        f"Submissions are handled via {f['platform']}.",
    )

    rmin = f.get("runtime_min_minutes", 1)
    rmax = f.get("runtime_max_minutes")
    bound = f"{rmin}-{rmax} minutes" if rmax else f"{rmin} minutes or longer"
    add("runtime", f"{name} accepts films with a runtime of {bound}.")

    if f.get("completed_after"):
        add("completion", f"{name} requires the film to be completed after {f['completed_after']}.")
    if f.get("completed_in_years"):
        years = ", ".join(str(y) for y in f["completed_in_years"])
        add("completion", f"{name} requires the film to be completed in one of these years: {years}.")

    prem = f.get("premiere", {})
    policy = prem.get("policy", "none")
    note = prem.get("note", "")
    region = prem.get("region")
    policy_desc = {
        "none": "has no premiere requirement",
        "date_sensitive": "applies a completion/public-availability date rule",
        "regional": f"requires a {region} premiere" if region else "requires a regional premiere",
        "strict": "requires that the film has not been publicly released or screened anywhere",
    }.get(policy, "has a premiere policy")
    add("premiere", f"Premiere policy for {name}: it {policy_desc}. {note}")

    if f.get("genre_whitelist"):
        add(
            "genre",
            f"{name} programs genre films only: {', '.join(f['genre_whitelist'])} and related genres.",
        )

    for d in f.get("deadlines", []):
        fee = d.get("fee")
        fee_str = f"{fee} {d.get('currency', 'USD')}" if fee is not None else "fee published at source"
        note = d.get("fee_note", "")
        add(
            "deadline",
            f"{name} deadline '{d['label']}' is {d['date']}, submission fee {fee_str}. {note}",
        )
    if f.get("deadline_note"):
        add("deadline_note", f"{name}: {f['deadline_note']}")

    return chunks


def _markdown_chunks() -> list[Chunk]:
    """Optionally enrich the corpus with hand-written guideline docs in data/kb/.

    Each *.md file may start with a front-matter block:
        ---
        festival_id: sundance
        festival_name: Sundance Film Festival (Shorts)
        source_url: https://...
        ---
    Sections split on markdown headings (## ...). Absent front-matter, the file
    stem is used as the id. This directory is optional; the JSON corpus above is
    always present.
    """
    chunks: list[Chunk] = []
    if not KB_DIR.exists():
        return chunks
    for md in sorted(KB_DIR.glob("*.md")):
        raw = md.read_text(encoding="utf-8")
        meta = {"festival_id": md.stem, "festival_name": md.stem, "source_url": ""}
        body = raw
        if raw.startswith("---"):
            _, fm, body = raw.split("---", 2)
            for line in fm.strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
        section, buf = "overview", []
        parts: list[tuple[str, str]] = []
        for line in body.splitlines():
            if line.startswith("#"):
                if buf:
                    parts.append((section, " ".join(buf)))
                    buf = []
                section = line.lstrip("#").strip().lower() or section
            else:
                buf.append(line)
        if buf:
            parts.append((section, " ".join(buf)))
        for i, (section, text) in enumerate(parts):
            text = " ".join(text.split())
            if text:
                chunks.append(
                    Chunk(
                        f"{meta['festival_id']}#md-{section}-{i}",
                        meta["festival_id"],
                        meta["festival_name"],
                        section,
                        text,
                        meta["source_url"],
                    )
                )
    return chunks


def build_corpus() -> list[Chunk]:
    with open(FESTIVALS_PATH, encoding="utf-8") as fh:
        festivals = json.load(fh)["festivals"]
    chunks: list[Chunk] = []
    for f in festivals:
        chunks.extend(_festival_chunks(f))
    chunks.extend(_markdown_chunks())
    return chunks


# --------------------------------------------------------------------------- #
# TF-IDF vector index (pure Python, no dependencies)
# --------------------------------------------------------------------------- #
@dataclass
class _TfidfIndex:
    chunks: list[Chunk]
    idf: dict[str, float] = field(default_factory=dict)
    vectors: list[dict[str, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        n = len(self.chunks)
        df: dict[str, int] = {}
        tokenized = []
        for c in self.chunks:
            toks = _tokenize(c.text)
            tokenized.append(toks)
            for t in set(toks):
                df[t] = df.get(t, 0) + 1
        # smoothed idf
        self.idf = {t: math.log((1 + n) / (1 + d)) + 1.0 for t, d in df.items()}
        self.vectors = [self._vectorize(toks) for toks in tokenized]

    def _vectorize(self, toks: list[str]) -> dict[str, float]:
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        vec = {t: (1.0 + math.log(c)) * self.idf.get(t, 0.0) for t, c in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    def search(self, query: str, k: int) -> list[tuple[Chunk, float]]:
        q = self._vectorize(_tokenize(query))
        if not q:
            return []
        scored: list[tuple[Chunk, float]] = []
        for chunk, vec in zip(self.chunks, self.vectors):
            # cosine over the smaller dict
            small, big = (q, vec) if len(q) < len(vec) else (vec, q)
            dot = sum(w * big.get(t, 0.0) for t, w in small.items())
            if dot > 0:
                scored.append((chunk, dot))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]


# --------------------------------------------------------------------------- #
# Optional dense backend (sentence-transformers)
# --------------------------------------------------------------------------- #
class _DenseIndex:
    def __init__(self, chunks: list[Chunk], model_name: str) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore

        self.chunks = chunks
        self.model = SentenceTransformer(model_name)
        self.embeddings = self.model.encode(
            [c.text for c in chunks], normalize_embeddings=True
        )

    def search(self, query: str, k: int) -> list[tuple[Chunk, float]]:
        q = self.model.encode([query], normalize_embeddings=True)[0]
        scored = [
            (chunk, float(sum(a * b for a, b in zip(q, emb))))
            for chunk, emb in zip(self.chunks, self.embeddings)
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]


# --------------------------------------------------------------------------- #
# Public Retriever
# --------------------------------------------------------------------------- #
class Retriever:
    """Backend-agnostic retriever. Build once, query many times."""

    def __init__(self, backend: str | None = None) -> None:
        self.chunks = build_corpus()
        backend = (backend or os.getenv("RETRIEVAL_BACKEND", "tfidf")).lower()
        self.backend = backend
        if backend == "dense":
            try:
                model = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
                self._index = _DenseIndex(self.chunks, model)
            except Exception as e:  # noqa: BLE001
                print(f"[retrieval] dense backend unavailable ({e}); using tfidf.")
                self.backend = "tfidf"
                self._index = _TfidfIndex(self.chunks)
        else:
            self._index = _TfidfIndex(self.chunks)

    def search(self, query: str, k: int = 5) -> list[Citation]:
        results = self._index.search(query, k)
        citations = []
        for chunk, score in results:
            cit = chunk.citation()
            cit.score = float(score)
            citations.append(cit)
        return citations


_RETRIEVER: Retriever | None = None


def get_retriever() -> Retriever:
    """Process-wide singleton so the index is built only once."""
    global _RETRIEVER
    if _RETRIEVER is None:
        _RETRIEVER = Retriever()
    return _RETRIEVER


if __name__ == "__main__":
    r = get_retriever()
    print(f"backend={r.backend}  chunks={len(r.chunks)}")
    for c in r.search("horror feature that already screened online", k=5):
        print(f"  {c.score:.3f}  {c.festival_name} [{c.section}] — {c.snippet[:70]}...")
