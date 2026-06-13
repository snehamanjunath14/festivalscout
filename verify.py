"""Self-verification pass.

After the agent responds, we extract every dollar amount and every date-like
string from its text and cross-check them against data/festivals.json. Claims
that match known fees or deadlines are marked verified; anything else is
flagged. This is the agent checking its own homework, in code.
"""
import re
from datetime import date

from models import VerificationItem

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}

_MONEY = re.compile(r"[$\u20ac]\s?(\d{1,4})")
_LONG_DATE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(\d{1,2}),?\s+(\d{4})",
    re.IGNORECASE,
)


def _known_facts(festivals: list[dict]) -> tuple[set[int], set[date]]:
    fees: set[int] = set()
    dates: set[date] = set()
    for f in festivals:
        for d in f.get("deadlines", []):
            fees.add(int(d["fee"]))
            dates.add(date.fromisoformat(d["date"]))
        prem = f.get("premiere", {})
        for key in ("public_availability_cutoff", "completion_exempt_after"):
            if prem.get(key):
                dates.add(date.fromisoformat(prem[key]))
        if f.get("completed_after"):
            dates.add(date.fromisoformat(f["completed_after"]))
    # 13 EUR base fee appears in prose even though json stores 14 with stamp.
    fees.add(13)
    fees.add(45)  # Palm Springs historical earlybird mentioned in notes.
    return fees, dates


def verify_agent_text(text: str, festivals: list[dict]) -> list[VerificationItem]:
    if not text:
        return []
    known_fees, known_dates = _known_facts(festivals)
    items: list[VerificationItem] = []
    seen: set[str] = set()

    for m in _MONEY.finditer(text):
        amount = int(m.group(1))
        claim = m.group(0).strip()
        if claim in seen:
            continue
        seen.add(claim)
        ok = amount in known_fees
        items.append(
            VerificationItem(
                claim=f"Fee mentioned: {claim}",
                status="verified" if ok else "unverified",
                detail="Matches a known fee in the festival dataset."
                if ok
                else "Not found in the festival dataset; double-check at the source URL.",
            )
        )

    for m in _LONG_DATE.finditer(text):
        try:
            d = date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
        except (ValueError, KeyError):
            continue
        claim = m.group(0)
        if claim in seen:
            continue
        seen.add(claim)
        ok = d in known_dates
        items.append(
            VerificationItem(
                claim=f"Date mentioned: {claim}",
                status="verified" if ok else "unverified",
                detail="Matches a known deadline or rule date in the dataset."
                if ok
                else "Not a known deadline/rule date; double-check at the source URL.",
            )
        )
    return items
