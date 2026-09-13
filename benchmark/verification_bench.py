"""Measure the verification layer.

"Cross-checks numeric claims against the structured dataset" is a design claim
until you attach a number to it. This benchmark attaches one.

Methodology — fault injection (default, reproducible with no API key):
  Models fail at date arithmetic and fee tiers. We simulate that failure mode
  directly and measurably. For each generated model-style response we state
  several real (fee, date) facts drawn from data/festivals.json, then corrupt a
  known fraction of them into values that appear *nowhere* in the dataset —
  exactly the hallucinated fees and dates a verifier exists to catch. Because we
  labelled every claim as correct-or-corrupted, we can measure the verifier's:
    - recall     : share of injected numeric errors it flags before the user sees them
    - precision  : share of its flags that are genuine errors
    - false-positive rate : correct claims it wrongly flags
  The seed is fixed, so the headline number is reproducible.

Live mode (--live): if LLM_PROVIDER is configured, generate raw, *ungrounded*
responses from the real model and run the same measurement on genuine output.
This regenerates the number authentically; the fault-injection run is the
default so the metric reproduces on any clone.

Scope (stated honestly): the verifier checks whether each fee/date appears in
the ground-truth dataset at all. It catches values that exist nowhere in the
data; it does not check that a real fee is attached to the *right* festival.
The benchmark measures exactly that guarantee.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constraints import load_festivals  # noqa: E402
from verify import _known_facts, verify_agent_text  # noqa: E402

HERE = Path(__file__).parent
SEED = 42
N_RESPONSES = 200
CORRUPTION_RATE = 0.35  # fraction of numeric facts we corrupt into hallucinations


def _fact_pool(festivals: list[dict]) -> tuple[list[tuple[int, str]], list[tuple[str, str]]]:
    """Return (fees, dates) as (value, phrase) pairs drawn from real deadlines."""
    fees, dates = [], []
    months = ["January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]
    for f in festivals:
        for d in f.get("deadlines", []):
            if d.get("fee") is not None:
                fees.append((int(d["fee"]), f"${int(d['fee'])}"))
            dt = date.fromisoformat(d["date"])
            dates.append((d["date"], f"{months[dt.month - 1]} {dt.day}, {dt.year}"))
    return fees, dates


def _corrupt_fee(value: int, known: set[int], rng: random.Random) -> str:
    for _ in range(50):
        bad = value + rng.choice([-13, -7, 5, 11, 23, 40])
        if bad > 0 and bad not in known:
            return f"${bad}"
    return f"${value + 1000}"


def _corrupt_date(iso: str, known: set[date], rng: random.Random) -> str:
    months = ["January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]
    base = date.fromisoformat(iso)
    for _ in range(50):
        bad = base + timedelta(days=rng.choice([-400, -60, -3, 4, 90, 370]))
        if bad not in known:
            return f"{months[bad.month - 1]} {bad.day}, {bad.year}"
    return f"{months[0]} 1, 2099"


def run_fault_injection() -> dict:
    festivals = load_festivals()
    known_fees, known_dates = _known_facts(festivals)
    fees, dates = _fact_pool(festivals)
    rng = random.Random(SEED)

    # Two error classes:
    #   hallucination = a value that appears nowhere in the dataset (catchable)
    #   swap          = a real value from the dataset quoted in the wrong place
    #                   (in-set, so the membership check cannot catch it)
    tp = fp = fn = tn = 0
    hall_injected = hall_caught = 0
    swap_injected = swap_caught = 0

    def other_fee(value: int) -> str:
        pool = [f for v, f in fees if v != value]
        return rng.choice(pool) if pool else f"${value}"

    def other_date(iso: str) -> str:
        pool = [p for i, p in dates if i != iso]
        return rng.choice(pool) if pool else iso

    for _ in range(N_RESPONSES):
        claims: list[tuple[str, bool]] = []  # (phrase, is_error)

        def inject(value, phrase, corrupt_hall, corrupt_swap):
            nonlocal hall_injected, swap_injected
            roll = rng.random()
            if roll < CORRUPTION_RATE * 0.6:  # hallucination
                claims.append((corrupt_hall(), True))
                hall_injected += 1
            elif roll < CORRUPTION_RATE:  # swap: real value, wrong context
                claims.append((corrupt_swap(), True))
                swap_injected += 1
            else:
                claims.append((phrase, False))

        for value, phrase in rng.sample(fees, k=rng.randint(2, 3)):
            inject(value, phrase,
                   lambda v=value: _corrupt_fee(v, known_fees, rng),
                   lambda v=value: other_fee(v))
        for iso, phrase in rng.sample(dates, k=rng.randint(2, 3)):
            inject(iso, phrase,
                   lambda i=iso: _corrupt_date(i, known_dates, rng),
                   lambda i=iso: other_date(i))

        rng.shuffle(claims)
        text = " ".join(
            f"The {'fee' if c.startswith('$') else 'deadline'} is {c}." for c, _ in claims
        )
        items = verify_agent_text(text, festivals)
        flagged = {i.claim.split(": ", 1)[1]: (i.status == "unverified") for i in items}

        for phrase, is_err in claims:
            is_flagged = flagged.get(phrase, False)
            if is_err and is_flagged:
                tp += 1
            elif is_err and not is_flagged:
                fn += 1
            elif not is_err and is_flagged:
                fp += 1
            else:
                tn += 1

    # per-class recall: recompute from the aggregate by re-running the flag check
    # (tp/fn above already separate correct vs error; class split tracked below)
    # We recompute class-level catches by a second deterministic pass:
    rng = random.Random(SEED)
    hall_caught = swap_caught = 0
    for _ in range(N_RESPONSES):
        claims = []

        def inject2(value, phrase, corrupt_hall, corrupt_swap):
            roll = rng.random()
            if roll < CORRUPTION_RATE * 0.6:
                claims.append((corrupt_hall(), "hall"))
            elif roll < CORRUPTION_RATE:
                claims.append((corrupt_swap(), "swap"))
            else:
                claims.append((phrase, "ok"))

        for value, phrase in rng.sample(fees, k=rng.randint(2, 3)):
            inject2(value, phrase,
                    lambda v=value: _corrupt_fee(v, known_fees, rng),
                    lambda v=value: other_fee(v))
        for iso, phrase in rng.sample(dates, k=rng.randint(2, 3)):
            inject2(iso, phrase,
                    lambda i=iso: _corrupt_date(i, known_dates, rng),
                    lambda i=iso: other_date(i))
        rng.shuffle(claims)
        text = " ".join(
            f"The {'fee' if c.startswith('$') else 'deadline'} is {c}." for c, _ in claims
        )
        items = verify_agent_text(text, festivals)
        flagged = {i.claim.split(": ", 1)[1]: (i.status == "unverified") for i in items}
        for phrase, kind in claims:
            if kind == "hall" and flagged.get(phrase, False):
                hall_caught += 1
            elif kind == "swap" and flagged.get(phrase, False):
                swap_caught += 1

    total_injected = hall_injected + swap_injected
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    return {
        "method": "fault_injection",
        "seed": SEED,
        "responses": N_RESPONSES,
        "numeric_errors_injected": total_injected,
        "errors_caught": tp,
        "errors_missed": fn,
        "false_positives": fp,
        "true_negatives": tn,
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "false_positive_rate": round(fpr, 4),
        "hallucination_errors": hall_injected,
        "hallucination_recall": round(hall_caught / hall_injected, 4) if hall_injected else 0.0,
        "wrong_context_errors": swap_injected,
        "wrong_context_recall": round(swap_caught / swap_injected, 4) if swap_injected else 0.0,
    }


def write_report(result: dict) -> None:
    (HERE / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    hall = round(result["hallucination_recall"] * 100, 1)
    swap = round(result["wrong_context_recall"] * 100, 1)
    fpr = round(result["false_positive_rate"] * 100, 1)
    md = f"""# Verification benchmark

**Headline:** across {result['responses']} model-style responses, the verification
layer flagged **{hall}% of hallucinated fees and dates**
({result['hallucination_errors']} injected) before they reached the user, with a
**{fpr}% false-positive rate** on correct claims.

| Metric | Value |
|---|---|
| Method | fault injection (seed {result['seed']}) |
| Responses evaluated | {result['responses']} |
| Numeric errors injected | {result['numeric_errors_injected']} |
| **Hallucinated values caught** | {result['hallucination_errors']} injected → **{hall}%** recall |
| Wrong-festival real values caught | {result['wrong_context_errors']} injected → **{swap}%** recall |
| False positives (correct claims flagged) | {result['false_positives']} ({fpr}%) |

## What this measures
Models are unreliable at date arithmetic and fee tiers. This run injects two
kinds of numeric error into otherwise-correct model output:

1. **Hallucinations** — fees/dates that appear *nowhere* in `data/festivals.json`.
2. **Wrong-context values** — a real fee or date from the dataset, but quoted for
   the wrong festival.

## The honest result (and why it matters)
The verifier catches essentially **all hallucinations** ({hall}%) — any number
not in the ground-truth data is flagged. It catches **{swap}%** of wrong-context
values, because it checks set membership, not festival-specific correctness. That
gap is not a bug to paper over: it is precisely why FestivalScout computes every
fee, deadline, and eligibility verdict in the **deterministic layer** rather than
trusting the model. The verifier is a safety net over generated prose; the
numbers the user acts on come from code.

Regenerate against a real model with `python benchmark/verification_bench.py --live`
once `LLM_PROVIDER` is set.

_Reproduce: `python benchmark/verification_bench.py`_
"""
    (HERE / "REPORT.md").write_text(md, encoding="utf-8")


def run_live() -> dict:
    """Generate ungrounded responses from the configured model and measure them.

    Requires LLM_PROVIDER + credentials. This has no injected ground truth, so it
    reports how many numeric claims the verifier flags in real model output.
    """
    from reasoning import _remote  # noqa

    festivals = load_festivals()
    provider = os.getenv("LLM_PROVIDER", "none")
    if provider == "none":
        print("Set LLM_PROVIDER (openai|azure) and credentials to use --live.")
        sys.exit(1)

    prompts = [
        "List the submission deadline and fee for the Sundance short film festival.",
        "What does Clermont-Ferrand charge and when is its deadline?",
        "Give the SXSW feature submission fee and date.",
        "State the Slamdance earlybird deadline and fee.",
        "What is Tribeca's feature submission fee and deadline?",
    ]
    total_claims = flagged = 0
    for p in prompts:
        text, _mode = _remote("Answer concisely with the fee and date.", p)
        if not text:
            continue
        items = verify_agent_text(text, festivals)
        total_claims += len(items)
        flagged += sum(1 for i in items if i.status == "unverified")
    return {
        "method": "live",
        "provider": provider,
        "prompts": len(prompts),
        "numeric_claims": total_claims,
        "flagged_unverified": flagged,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Measure the verification layer.")
    ap.add_argument("--live", action="store_true", help="run against a real model")
    args = ap.parse_args()

    result = run_live() if args.live else run_fault_injection()
    print(json.dumps(result, indent=2))
    if not args.live:
        write_report(result)
        print(f"\nWrote {HERE / 'REPORT.md'} and {HERE / 'results.json'}")


if __name__ == "__main__":
    main()
