# Verification benchmark

**Headline:** across 200 model-style responses, the verification
layer flagged **100.0% of hallucinated fees and dates**
(207 injected) before they reached the user, with a
**0.0% false-positive rate** on correct claims.

| Metric | Value |
|---|---|
| Method | fault injection (seed 42) |
| Responses evaluated | 200 |
| Numeric errors injected | 357 |
| **Hallucinated values caught** | 207 injected → **100.0%** recall |
| Wrong-festival real values caught | 150 injected → **0.0%** recall |
| False positives (correct claims flagged) | 0 (0.0%) |

## What this measures
Models are unreliable at date arithmetic and fee tiers. This run injects two
kinds of numeric error into otherwise-correct model output:

1. **Hallucinations** — fees/dates that appear *nowhere* in `data/festivals.json`.
2. **Wrong-context values** — a real fee or date from the dataset, but quoted for
   the wrong festival.

## The honest result (and why it matters)
The verifier catches essentially **all hallucinations** (100.0%) — any number
not in the ground-truth data is flagged. It catches **0.0%** of wrong-context
values, because it checks set membership, not festival-specific correctness. That
gap is not a bug to paper over: it is precisely why FestivalScout computes every
fee, deadline, and eligibility verdict in the **deterministic layer** rather than
trusting the model. The verifier is a safety net over generated prose; the
numbers the user acts on come from code.

Regenerate against a real model with `python benchmark/verification_bench.py --live`
once `LLM_PROVIDER` is set.

_Reproduce: `python benchmark/verification_bench.py`_
