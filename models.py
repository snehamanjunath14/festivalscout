"""Data models for FestivalScout."""
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


class FilmProfile(BaseModel):
    """What the filmmaker tells us about their film."""

    title: str = Field(..., min_length=1, max_length=200)
    runtime_minutes: int = Field(..., ge=1, le=400)
    completion_date: date
    premiere_status: Literal["unscreened", "online", "festival"] = "unscreened"
    genres: list[str] = Field(default_factory=lambda: ["drama"], min_length=1)
    budget_usd: Optional[float] = Field(default=None, ge=0)


class DeadlineInfo(BaseModel):
    label: str
    date: date
    fee: Optional[float] = None  # some festivals don't publish a fixed fee
    currency: str = "USD"
    fee_note: Optional[str] = None
    days_remaining: int


class FestivalVerdict(BaseModel):
    """Deterministic verdict for one festival, computed in code (not by the LLM)."""

    festival_id: str
    festival_name: str
    location: str
    film_format: str  # "short" or "feature"
    verdict: Literal["fit", "caution", "not_eligible", "closed", "unknown"]
    reasons: list[str]
    warnings: list[str]
    next_deadline: Optional[DeadlineInfo] = None
    estimated_fee_usd: Optional[float] = None
    oscar_qualifying: bool
    platform: str
    source_url: str


class VerificationItem(BaseModel):
    claim: str
    status: Literal["verified", "unverified"]
    detail: str


class AnalysisResponse(BaseModel):
    film: FilmProfile
    verdicts: list[FestivalVerdict]
    strategy_notes: list[str]
    total_estimated_fees_usd: Optional[float]
    agent_analysis: Optional[str] = None
    agent_mode: Literal["foundry_agent", "fallback", "unavailable"]
    verification: list[VerificationItem] = []
