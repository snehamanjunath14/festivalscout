# FestivalScout

An AI reasoning agent that turns a film's profile into a validated festival
submission strategy. Built for the Microsoft Agents League 2026 (Reasoning Agents
track), integrating **Foundry IQ** for agentic knowledge retrieval.

## The problem

Submitting a film to festivals is a high-stakes guessing game. Fees add up,
deadlines are scattered across platforms, and premiere rules interact: screening
at one festival can change your eligibility or competitiveness at another.
Filmmakers routinely burn money on festivals they were never eligible for.

## How it works — three layers

1. **Deterministic layer (`constraints.py`).** Every runtime check (now including
   minimum runtimes for feature categories), completion-date rule, premiere-policy
   evaluation, deadline calculation, and fee total is computed in plain Python.
   The LLM never decides eligibility, so the numbers in the answer are computed,
   not generated. Premiere policies handled: none, date-sensitive (Sundance-style),
   regional (UK / LA / Texas / U.S. / North American premiere requirements), and
   strict (no prior public release anywhere, e.g. SXSW).
2. **Agentic layer (`foundry_client.py`).** A Foundry agent grounded in a
   **Foundry IQ knowledge base** of real festival guidelines (built on Azure AI
   Search agentic retrieval, Medium reasoning effort) adds the nuance code can't:
   category fit, selection context, guideline fine print — with citations.
3. **Verification layer (`verify.py`).** Every dollar amount and date in the
   agent's response is extracted and cross-checked against the structured dataset.
   Unmatched claims are flagged in the UI instead of silently trusted.

## Coverage

12 festivals spanning shorts and features, verified 2026-06-13 against official
sources:

- **Shorts:** Sundance, Clermont-Ferrand, Palm Springs ShortFest, Slamdance,
  AFI FEST, Tribeca (Shorts)
- **Features:** Tribeca, SXSW, Raindance, Fantastic Fest, Sitges,
  Austin Film Festival

The festival set is data-driven: add more by editing `data/festivals.json` and
uploading a matching markdown file to the knowledge base. No code changes needed.

## Stack

- Microsoft Foundry: gpt-4.1-mini deployment + Foundry agent
- Foundry IQ knowledge base on Azure AI Search (Standard tier)
- FastAPI + Pydantic backend
- Single-file HTML/CSS/JS frontend

## Run it

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in your Foundry values
uvicorn main:app --reload
# open http://127.0.0.1:8000
```

The app degrades gracefully: if the Foundry agent can't be reached it falls back
to a direct grounded model call, and if that fails too, the deterministic verdicts
still render — clearly labeled in the UI.

## Known limitations

- Festival dataset covers 12 festivals (verified 2026-06-13); deadlines and fees
  change yearly and should be re-verified at each source URL.
- Some festivals (Palm Springs 2027, Fantastic Fest, Austin, AFI features) had
  unannounced or passed deadlines at build time; the app says so rather than guessing.
- A few feature festivals don't publish a fixed fee; those show "see source"
  rather than a fabricated number.
- EUR/GBP fees are converted at a fixed indicative rate for budget math only.
- The verification pass checks numeric claims (fees, dates), not prose claims.
- Premiere geography (regional rules) can't be fully resolved from the three
  premiere-status options; the app flags these as cautions for the user to confirm.

## Data

- No confidential information is used. All festival data comes from public official
guidelines; each file carries a `source_url` and `last_verified` date.
