"""Deterministic constraint checks.

This module is the reliability core of FestivalScout. Every date comparison,
runtime check, fee calculation, and premiere-conflict detection happens here in
plain Python, so the numbers in the final answer are computed, not generated.
The LLM (via Foundry IQ) adds nuance and citations on top; it never decides
eligibility on its own.

Premiere policy types handled:
  none            - no premiere requirement
  date_sensitive  - Sundance-style completion/public-availability date rule
  regional        - requires a regional/national premiere (UK, LA, Texas, etc.)
  strict          - must not have been publicly released anywhere (e.g. SXSW)
"""
import json
from datetime import date
from pathlib import Path

from models import DeadlineInfo, FestivalVerdict, FilmProfile

DATA_PATH = Path(__file__).parent / "data" / "festivals.json"
EUR_TO_USD = 1.10  # indicative, for budget math only


def load_festivals() -> list[dict]:
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)["festivals"]


def _to_usd(fee, currency: str):
    if fee is None:
        return None
    return round(fee * EUR_TO_USD, 2) if currency == "EUR" else float(fee)


def _next_deadline(festival: dict, today: date) -> DeadlineInfo | None:
    upcoming = []
    for d in festival.get("deadlines", []):
        dl = date.fromisoformat(d["date"])
        if dl >= today:
            upcoming.append((dl, d))
    if not upcoming:
        return None
    dl, d = min(upcoming, key=lambda x: x[0])
    return DeadlineInfo(
        label=d["label"],
        date=dl,
        fee=d.get("fee"),
        currency=d.get("currency", "USD"),
        fee_note=d.get("fee_note"),
        days_remaining=(dl - today).days,
    )


def _check_runtime(festival: dict, film: FilmProfile, reasons: list[str]) -> bool:
    rmin = festival.get("runtime_min_minutes", 1)
    rmax = festival.get("runtime_max_minutes")  # None means no upper bound
    if film.runtime_minutes < rmin:
        reasons.append(
            f"Runtime {film.runtime_minutes} min is below this category's "
            f"{rmin}-minute minimum (this is a {festival['film_format']} category)."
        )
        return False
    if rmax is not None and film.runtime_minutes > rmax:
        reasons.append(
            f"Runtime {film.runtime_minutes} min exceeds the {rmax}-minute limit."
        )
        return False
    bound = f"{rmin}\u2013{rmax} min" if rmax else f"{rmin}+ min"
    reasons.append(f"Runtime {film.runtime_minutes} min fits the {bound} window.")
    return True


def _check_completion(festival: dict, film: FilmProfile, reasons: list[str]) -> bool:
    ok = True
    if festival.get("completed_after"):
        cutoff = date.fromisoformat(festival["completed_after"])
        if film.completion_date <= cutoff:
            reasons.append(f"Film must be completed after {cutoff.isoformat()}.")
            ok = False
        else:
            reasons.append(f"Completed after the {cutoff.isoformat()} cutoff.")
    if festival.get("completed_in_years"):
        years = festival["completed_in_years"]
        if film.completion_date.year not in years:
            reasons.append(f"Film must be completed in {years}.")
            ok = False
        else:
            reasons.append(f"Completion year {film.completion_date.year} qualifies.")
    return ok


def evaluate_festival(festival: dict, film: FilmProfile, today: date) -> FestivalVerdict:
    reasons: list[str] = []
    warnings: list[str] = []
    verdict = "fit"

    if not _check_runtime(festival, film, reasons):
        verdict = "not_eligible"
    if not _check_completion(festival, film, reasons):
        verdict = "not_eligible"

    # --- Genre restriction (for genre-specific festivals) ---
    whitelist = festival.get("genre_whitelist")
    if whitelist:
        wl = [g.lower() for g in whitelist]
        film_genres = [g.lower() for g in film.genres]
        if any(g in wl for g in film_genres):
            reasons.append(
                f"Genre ({', '.join(film.genres)}) fits this festival's genre focus."
            )
        else:
            verdict = "not_eligible"
            reasons.append(
                f"This festival programs only {', '.join(whitelist)} (and related) "
                f"genre films; ({', '.join(film.genres)}) does not fit."
            )

    # --- Premiere policy ---
    prem = festival["premiere"]
    policy = prem["policy"]
    if policy == "none":
        reasons.append("No premiere requirement.")
        if festival["id"] == "palm-springs" and film.premiere_status == "online":
            if verdict == "fit":
                verdict = "caution"
            warnings.append(
                "Prior online release limits this film to the Online Film Festival category."
            )
    elif policy == "date_sensitive":
        exempt_after = date.fromisoformat(prem["completion_exempt_after"])
        if film.completion_date > exempt_after:
            reasons.append(
                "Completed after the exemption date, so eligible regardless of premiere status."
            )
            if film.premiere_status != "unscreened":
                warnings.append(
                    "Already screened: eligible by date rule, but competitive selection "
                    "still favors fresh premieres."
                )
        elif film.premiere_status != "unscreened":
            verdict = "not_eligible"
            reasons.append(
                f"Publicly shown and completed before {exempt_after.isoformat()}: "
                "fails the public-availability rule."
            )
    elif policy == "regional":
        region = prem.get("region", "regional")
        if film.premiere_status == "unscreened":
            reasons.append(f"Unscreened, so the {region} premiere requirement is satisfied.")
        else:
            if verdict == "fit":
                verdict = "caution"
            warnings.append(
                f"This festival requires a {region} premiere. Prior screenings elsewhere "
                f"can be fine, but a public screening within {region} before the festival "
                "would disqualify it. Confirm where it has played."
            )
    elif policy == "strict":
        if film.premiere_status == "unscreened":
            reasons.append("Unscreened, which this festival's strict premiere rule requires.")
        else:
            verdict = "not_eligible"
            reasons.append(
                "This festival requires the film not to have been publicly released or "
                "screened anywhere; it has already screened."
            )

    # --- Deadlines ---
    next_dl = _next_deadline(festival, today)
    fee_usd = None
    if next_dl:
        fee_usd = _to_usd(next_dl.fee, next_dl.currency)
        fee_str = f"{next_dl.fee} {next_dl.currency}" if next_dl.fee is not None else "see source"
        reasons.append(
            f"Next deadline: {next_dl.label} on {next_dl.date.isoformat()} "
            f"({next_dl.days_remaining} days away), fee {fee_str}."
        )
        if next_dl.days_remaining <= 14:
            warnings.append("Deadline within two weeks: act fast.")
    elif festival.get("deadlines"):
        if verdict != "not_eligible":
            verdict = "closed"
        reasons.append("All published deadlines for this cycle have passed.")
    else:
        if verdict == "fit":
            verdict = "unknown"
        reasons.append(
            festival.get("deadline_note", "No deadline data published yet; verify at source.")
        )

    return FestivalVerdict(
        festival_id=festival["id"],
        festival_name=festival["name"],
        location=festival["location"],
        film_format=festival["film_format"],
        verdict=verdict,
        reasons=reasons,
        warnings=warnings,
        next_deadline=next_dl,
        estimated_fee_usd=fee_usd,
        oscar_qualifying=festival["oscar_qualifying"],
        platform=festival["platform"],
        source_url=festival["source_url"],
    )


def strategy_notes(verdicts: list[FestivalVerdict], film: FilmProfile) -> list[str]:
    """Cross-festival reasoning: ordering, conflicts, and budget."""
    notes: list[str] = []
    open_fits = [v for v in verdicts if v.verdict in ("fit", "caution") and v.next_deadline]

    fmt = "feature" if film.runtime_minutes > 40 else "short"
    eligible_fmt = [v for v in verdicts if v.film_format == fmt and v.verdict in ("fit", "caution")]
    if eligible_fmt:
        notes.append(
            f"Your {film.runtime_minutes}-minute film reads as a {fmt}. "
            f"{len(eligible_fmt)} of the {fmt}-eligible festivals are a fit or worth a look."
        )

    if film.premiere_status == "unscreened":
        strict_or_regional = [
            v for v in verdicts
            if v.verdict in ("fit", "caution", "unknown")
            and v.festival_id in ("sxsw", "fantastic-fest", "tribeca-feature",
                                   "raindance", "austin-film-festival", "afi-fest")
        ]
        if strict_or_regional:
            notes.append(
                "Your film is unscreened, which is your most valuable asset. Festivals with "
                "premiere requirements (SXSW, Fantastic Fest, Tribeca, Raindance, Austin, AFI) "
                "only stay open to you while it has not screened publicly. Submit to your "
                "highest-priority premiere festival before letting it play anywhere else."
            )

    if open_fits:
        ordered = sorted(open_fits, key=lambda v: v.next_deadline.date)
        seq = " \u2192 ".join(v.festival_name.split(" ")[0] for v in ordered)
        notes.append(f"Deadline order for open fits: {seq}.")

    fees = [v.estimated_fee_usd for v in open_fits if v.estimated_fee_usd is not None]
    if fees:
        total = round(sum(fees), 2)
        if film.budget_usd is not None and total > film.budget_usd:
            notes.append(
                f"Submitting to the open fits with published fees costs about ${total} USD, "
                f"over your ${film.budget_usd:.0f} budget. Prioritize by deadline and "
                "Oscar-qualifying status."
            )
        else:
            notes.append(f"Estimated fees for open fits with published prices: about ${total} USD.")

    slam = next((v for v in verdicts if v.festival_id == "slamdance" and v.next_deadline), None)
    if slam and slam.next_deadline.label == "Earlybird":
        notes.append(
            f"Slamdance earlybird saves $40 vs the extended deadline; it closes in "
            f"{slam.next_deadline.days_remaining} days."
        )
    return notes
