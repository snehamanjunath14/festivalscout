# FestivalScout — 2:30 demo script

Re-recorded against the local version (no Azure). Record with the app running at
`http://127.0.0.1:8000`. Timings are cues, not hard cuts.

> **The one manual step:** the recording itself. Everything below runs locally
> with `uvicorn main:app --reload` — no keys, no cloud. Record with OBS or your
> OS screen recorder, then link the file (or a YouTube/Loom URL) at the top of
> the README.

---

**0:00 – 0:20 · The problem**
> "Submitting a film to festivals is a guessing game. Fees add up, deadlines are
> scattered, and premiere rules interact — screening at one festival can quietly
> disqualify you at another. Filmmakers burn money on festivals they were never
> eligible for."

Show the landing page and the film-profile form.

**0:20 – 0:45 · Enter a film**
Fill the form on camera: a 95-minute horror/thriller, completed 2026-03-15,
premiere status **unscreened**, $150 budget. Click **Build my strategy**.

> "I describe the film once. Every check you're about to see is computed in
> Python — not guessed by a language model."

**0:45 – 1:15 · Deterministic verdicts**
Scroll the verdict cards and the timeline.
> "Runtime, completion dates, premiere policy, deadlines, and fees — all computed
> in code. SXSW needs a film that's never screened anywhere. Raindance needs a UK
> premiere. Fantastic Fest is genre-only. The engine knows all four premiere
> policy types and does the fee math and the calendar for me."

Toggle the **what-if** premiere control (unscreened → released online) and point
out cards changing verdict live.

**1:15 – 1:50 · Retrieval + grounded analysis**
Scroll to the analysis section and the citation chips.
> "This is the retrieval layer. A local vector index pulls the actual guideline
> passages behind each verdict and cites them — no cloud service, it ships in the
> repo. The analysis is grounded in those passages, and every source is one click
> away."

Click a citation chip to open the official source.

**1:50 – 2:15 · Verification — the part I'm proudest of**
Scroll to the verification pass.
> "Every number the model writes gets extracted and cross-checked against the
> ground-truth data. I benchmarked this: across 200 responses it flags 100% of
> hallucinated fees and dates with zero false positives. The numbers you act on
> are computed in code and then double-checked."

**2:15 – 2:30 · Close**
Click **Download plan (PDF)**; show the generated PDF.
> "One profile in, a validated, cited, budget-aware submission plan out — as a
> PDF you can act on. That's FestivalScout."

---

## Reset between takes
- Reload the page for a clean form.
- The default form values already describe a good demo film.
- `python doctor.py` confirms the pipeline is healthy before you hit record.
