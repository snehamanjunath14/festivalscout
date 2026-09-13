"""Tests for the self-verification pass.

The headline case is the null-fee guard: the real dataset contains deadlines
with no fixed fee (fee: null), which used to crash the whole verification pass
with `int(None)`. That regression test is the reason this file exists.
"""
from constraints import load_festivals
from verify import _known_facts, verify_agent_text

FESTIVALS = load_festivals()


class TestNullFeeGuard:
    def test_real_dataset_does_not_crash(self):
        # Raindance and Sitges publish deadlines with fee: null.
        items = verify_agent_text("The fee is $55 due July 13, 2026.", FESTIVALS)
        assert isinstance(items, list)

    def test_known_facts_skips_null_fees(self):
        fees, dates = _known_facts(FESTIVALS)
        assert None not in fees
        assert all(isinstance(x, int) for x in fees)

    def test_synthetic_null_fee_does_not_crash(self):
        fake = [{
            "deadlines": [{"label": "x", "date": "2026-08-01", "fee": None, "currency": "GBP"}],
            "premiere": {},
        }]
        assert verify_agent_text("$50", fake) is not None


class TestMoneyExtraction:
    def test_known_fee_is_verified(self):
        items = verify_agent_text("The submission fee is $55.", FESTIVALS)
        fee_items = [i for i in items if "Fee" in i.claim]
        assert fee_items and fee_items[0].status == "verified"

    def test_unknown_fee_is_flagged(self):
        items = verify_agent_text("The submission fee is $999.", FESTIVALS)
        fee_items = [i for i in items if "999" in i.claim]
        assert fee_items and fee_items[0].status == "unverified"

    def test_euro_symbol_is_parsed(self):
        items = verify_agent_text("It costs €13 to enter.", FESTIVALS)
        assert any("13" in i.claim for i in items)


class TestDateExtraction:
    def test_known_date_is_verified(self):
        items = verify_agent_text("The deadline is July 13, 2026.", FESTIVALS)
        date_items = [i for i in items if "Date" in i.claim]
        assert date_items and date_items[0].status == "verified"

    def test_unknown_date_is_flagged(self):
        items = verify_agent_text("The deadline is January 1, 2099.", FESTIVALS)
        date_items = [i for i in items if "2099" in i.claim]
        assert date_items and date_items[0].status == "unverified"

    def test_invalid_date_is_ignored(self):
        # February 30 does not exist; it should be silently skipped, not crash.
        items = verify_agent_text("Due February 30, 2026.", FESTIVALS)
        assert all("February 30" not in i.claim for i in items)


class TestEdges:
    def test_empty_text_returns_empty(self):
        assert verify_agent_text("", FESTIVALS) == []

    def test_no_numbers_returns_empty(self):
        assert verify_agent_text("Submit your best work early.", FESTIVALS) == []

    def test_duplicate_claims_deduplicated(self):
        items = verify_agent_text("$55 and again $55 and once more $55.", FESTIVALS)
        fee_items = [i for i in items if "55" in i.claim]
        assert len(fee_items) == 1
