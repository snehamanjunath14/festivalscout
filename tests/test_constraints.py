"""Tests for the deterministic constraint engine.

These cover the parts that are genuine engineering: runtime boundaries, the four
premiere-policy branches, completion-date rules, deadline selection, and the fee
math. Boundary conditions get special attention because that is where the bugs
live.
"""
from datetime import date

import pytest

from constraints import (
    _next_deadline,
    _to_usd,
    evaluate_festival,
    load_festivals,
    strategy_notes,
)
from models import FilmProfile

TODAY = date(2026, 6, 1)


def film(**kw) -> FilmProfile:
    base = dict(
        title="Test Film",
        runtime_minutes=90,
        completion_date=date(2026, 3, 15),
        premiere_status="unscreened",
        genres=["drama"],
        budget_usd=None,
    )
    base.update(kw)
    return FilmProfile(**base)


def fest(**kw) -> dict:
    base = dict(
        id="test",
        name="Test Festival",
        location="Nowhere",
        film_format="feature",
        runtime_min_minutes=1,
        runtime_max_minutes=None,
        premiere={"policy": "none", "note": ""},
        deadlines=[{"label": "Regular", "date": "2026-08-01", "fee": 50, "currency": "USD"}],
        oscar_qualifying=False,
        platform="FilmFreeway",
        source_url="https://example.com",
    )
    base.update(kw)
    return base


# --------------------------------------------------------------------------- #
# Runtime boundaries
# --------------------------------------------------------------------------- #
class TestRuntime:
    def test_below_minimum_is_ineligible(self):
        f = fest(runtime_min_minutes=41)
        v = evaluate_festival(f, film(runtime_minutes=40), TODAY)
        assert v.verdict == "not_eligible"

    def test_exactly_at_minimum_is_ok(self):
        f = fest(runtime_min_minutes=41)
        v = evaluate_festival(f, film(runtime_minutes=41), TODAY)
        assert v.verdict != "not_eligible"

    def test_exactly_at_maximum_is_ok(self):
        f = fest(runtime_min_minutes=1, runtime_max_minutes=40)
        v = evaluate_festival(f, film(runtime_minutes=40), TODAY)
        assert v.verdict != "not_eligible"

    def test_above_maximum_is_ineligible(self):
        f = fest(runtime_min_minutes=1, runtime_max_minutes=40)
        v = evaluate_festival(f, film(runtime_minutes=41), TODAY)
        assert v.verdict == "not_eligible"

    def test_no_upper_bound_accepts_long_films(self):
        f = fest(runtime_min_minutes=41, runtime_max_minutes=None)
        v = evaluate_festival(f, film(runtime_minutes=240), TODAY)
        assert v.verdict != "not_eligible"

    def test_one_minute_under_max_is_ok(self):
        f = fest(runtime_min_minutes=1, runtime_max_minutes=40)
        v = evaluate_festival(f, film(runtime_minutes=39), TODAY)
        assert v.verdict != "not_eligible"


# --------------------------------------------------------------------------- #
# Completion-date rules
# --------------------------------------------------------------------------- #
class TestCompletion:
    def test_completed_after_cutoff_passes(self):
        f = fest(completed_after="2026-01-01")
        v = evaluate_festival(f, film(completion_date=date(2026, 2, 1)), TODAY)
        assert v.verdict != "not_eligible"

    def test_completed_on_cutoff_fails(self):
        # rule is strict "after": equal to the cutoff is not after it
        f = fest(completed_after="2026-01-01")
        v = evaluate_festival(f, film(completion_date=date(2026, 1, 1)), TODAY)
        assert v.verdict == "not_eligible"

    def test_completed_before_cutoff_fails(self):
        f = fest(completed_after="2026-01-01")
        v = evaluate_festival(f, film(completion_date=date(2025, 12, 31)), TODAY)
        assert v.verdict == "not_eligible"

    def test_completed_in_allowed_year_passes(self):
        f = fest(completed_in_years=[2025, 2026])
        v = evaluate_festival(f, film(completion_date=date(2026, 5, 1)), TODAY)
        assert v.verdict != "not_eligible"

    def test_completed_in_disallowed_year_fails(self):
        f = fest(completed_in_years=[2025, 2026])
        v = evaluate_festival(f, film(completion_date=date(2024, 5, 1)), TODAY)
        assert v.verdict == "not_eligible"


# --------------------------------------------------------------------------- #
# Premiere policies
# --------------------------------------------------------------------------- #
class TestPremiereNone:
    def test_no_requirement_is_fit(self):
        v = evaluate_festival(fest(premiere={"policy": "none", "note": ""}), film(), TODAY)
        assert v.verdict == "fit"

    def test_palm_springs_online_downgrades_to_caution(self):
        f = fest(id="palm-springs", premiere={"policy": "none", "note": ""})
        v = evaluate_festival(f, film(premiere_status="online"), TODAY)
        assert v.verdict == "caution"
        assert any("Online Film Festival" in w for w in v.warnings)


class TestPremiereDateSensitive:
    def _fest(self):
        return fest(premiere={"policy": "date_sensitive", "completion_exempt_after": "2025-12-31"})

    def test_completed_after_exemption_is_eligible_even_if_screened(self):
        v = evaluate_festival(self._fest(), film(completion_date=date(2026, 3, 1),
                                                 premiere_status="festival"), TODAY)
        assert v.verdict != "not_eligible"

    def test_screened_and_completed_before_exemption_fails(self):
        v = evaluate_festival(self._fest(), film(completion_date=date(2025, 6, 1),
                                                 premiere_status="online"), TODAY)
        assert v.verdict == "not_eligible"

    def test_unscreened_before_exemption_is_ok(self):
        v = evaluate_festival(self._fest(), film(completion_date=date(2025, 6, 1),
                                                 premiere_status="unscreened"), TODAY)
        assert v.verdict != "not_eligible"


class TestPremiereRegional:
    def _fest(self):
        return fest(premiere={"policy": "regional", "region": "UK", "note": ""})

    def test_unscreened_satisfies_regional(self):
        v = evaluate_festival(self._fest(), film(premiere_status="unscreened"), TODAY)
        assert v.verdict == "fit"

    def test_screened_becomes_caution_not_block(self):
        v = evaluate_festival(self._fest(), film(premiere_status="festival"), TODAY)
        assert v.verdict == "caution"
        assert v.warnings


class TestPremiereStrict:
    def _fest(self):
        return fest(premiere={"policy": "strict", "note": ""})

    def test_unscreened_passes_strict(self):
        v = evaluate_festival(self._fest(), film(premiere_status="unscreened"), TODAY)
        assert v.verdict == "fit"

    def test_any_screening_blocks_strict(self):
        for status in ("online", "festival"):
            v = evaluate_festival(self._fest(), film(premiere_status=status), TODAY)
            assert v.verdict == "not_eligible", status


# --------------------------------------------------------------------------- #
# Genre whitelist
# --------------------------------------------------------------------------- #
class TestGenre:
    def test_matching_genre_is_eligible(self):
        f = fest(genre_whitelist=["horror", "sci-fi"])
        v = evaluate_festival(f, film(genres=["horror"]), TODAY)
        assert v.verdict != "not_eligible"

    def test_nonmatching_genre_is_ineligible(self):
        f = fest(genre_whitelist=["horror", "sci-fi"])
        v = evaluate_festival(f, film(genres=["comedy"]), TODAY)
        assert v.verdict == "not_eligible"

    def test_one_matching_genre_among_many_qualifies(self):
        f = fest(genre_whitelist=["horror"])
        v = evaluate_festival(f, film(genres=["drama", "horror"]), TODAY)
        assert v.verdict != "not_eligible"


# --------------------------------------------------------------------------- #
# Deadlines and fees
# --------------------------------------------------------------------------- #
class TestDeadlines:
    def test_picks_nearest_future_deadline(self):
        f = fest(deadlines=[
            {"label": "Late", "date": "2026-10-01", "fee": 90, "currency": "USD"},
            {"label": "Early", "date": "2026-07-01", "fee": 50, "currency": "USD"},
        ])
        dl = _next_deadline(f, TODAY)
        assert dl.label == "Early"

    def test_all_deadlines_passed_is_closed(self):
        f = fest(deadlines=[{"label": "Regular", "date": "2026-01-01", "fee": 50, "currency": "USD"}])
        v = evaluate_festival(f, film(), TODAY)
        assert v.verdict == "closed"

    def test_no_deadlines_is_unknown(self):
        f = fest(deadlines=[], deadline_note="TBA")
        v = evaluate_festival(f, film(), TODAY)
        assert v.verdict == "unknown"

    def test_fee_within_two_weeks_warns(self):
        f = fest(deadlines=[{"label": "Regular", "date": "2026-06-10", "fee": 50, "currency": "USD"}])
        v = evaluate_festival(f, film(), TODAY)
        assert any("two weeks" in w for w in v.warnings)

    def test_estimated_fee_is_computed(self):
        f = fest(deadlines=[{"label": "Regular", "date": "2026-08-01", "fee": 60, "currency": "USD"}])
        v = evaluate_festival(f, film(), TODAY)
        assert v.estimated_fee_usd == 60.0

    def test_null_fee_deadline_does_not_crash(self):
        f = fest(deadlines=[{"label": "Regular", "date": "2026-08-01", "fee": None, "currency": "GBP"}])
        v = evaluate_festival(f, film(), TODAY)
        assert v.estimated_fee_usd is None
        assert v.next_deadline is not None


class TestFeeMath:
    def test_usd_passthrough(self):
        assert _to_usd(50, "USD") == 50.0

    def test_eur_conversion(self):
        assert _to_usd(13, "EUR") == round(13 * 1.10, 2)

    def test_none_fee_returns_none(self):
        assert _to_usd(None, "USD") is None


# --------------------------------------------------------------------------- #
# Cross-festival strategy notes
# --------------------------------------------------------------------------- #
class TestStrategyNotes:
    def test_budget_overrun_is_flagged(self):
        data = load_festivals()
        f = film(runtime_minutes=30, budget_usd=1.0, completion_date=date(2026, 3, 1))
        verdicts = [evaluate_festival(x, f, TODAY) for x in data]
        notes = strategy_notes(verdicts, f)
        assert any("budget" in n.lower() for n in notes)

    def test_notes_are_strings(self):
        data = load_festivals()
        f = film(runtime_minutes=95)
        verdicts = [evaluate_festival(x, f, TODAY) for x in data]
        assert all(isinstance(n, str) for n in strategy_notes(verdicts, f))


# --------------------------------------------------------------------------- #
# Real dataset never crashes and is internally consistent
# --------------------------------------------------------------------------- #
class TestRealDataset:
    @pytest.mark.parametrize("runtime", [5, 40, 41, 95, 200])
    def test_every_festival_evaluates(self, runtime):
        data = load_festivals()
        f = film(runtime_minutes=runtime)
        for festival in data:
            v = evaluate_festival(festival, f, TODAY)
            assert v.verdict in ("fit", "caution", "not_eligible", "closed", "unknown")

    def test_dataset_loads_twelve_festivals(self):
        assert len(load_festivals()) == 12
