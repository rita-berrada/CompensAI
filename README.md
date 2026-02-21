# EU261 Compensation Claim Agent

Hackathon-ready Streamlit app that collects flight delay intake, runs an orchestrator agent with tools, drafts a claim (email or form payload), supports human approval, and logs every event to JSONL + SQLite.

## Features

- Streamlit intake form for EU261 claims
- Orchestrator agent with bounded Claude tool-calling loop (Anthropic Messages API)
- Local RAG over `data/eu261_kb.jsonl` with a persisted SQLite FTS index in `data/eu261_rag.sqlite`
- Deterministic fallback mode when `ANTHROPIC_API_KEY` is missing
- Human-in-the-loop approval/edit step before simulated submission
- Event logging to:
  - `logs/events.jsonl`
  - `logs/claims.sqlite` (`events` table)

## File Structure

- `/Users/natalia2/hackeurope/compensation-agent/app.py`
- `/Users/natalia2/hackeurope/compensation-agent/agent.py`
- `/Users/natalia2/hackeurope/compensation-agent/tools.py`
- `/Users/natalia2/hackeurope/compensation-agent/rag.py`
- `/Users/natalia2/hackeurope/compensation-agent/db.py`
- `/Users/natalia2/hackeurope/compensation-agent/schemas.py`
- `/Users/natalia2/hackeurope/compensation-agent/data/providers.json`
- `/Users/natalia2/hackeurope/compensation-agent/data/eu261_kb.jsonl`
- `/Users/natalia2/hackeurope/compensation-agent/data/eu261_rag.sqlite` (auto-generated index)
- `/Users/natalia2/hackeurope/compensation-agent/requirements.txt`

## Setup

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Optional: enable Claude mode:

```bash
export ANTHROPIC_API_KEY=your_key_here
```

3. Run app:

```bash
streamlit run app.py
```

## Demo Steps

1. Open the Streamlit app.
2. In sidebar, choose input mode:
   - `JSON file`: upload JSON containing structured fields and/or `email_text`.
   - `Manual`: fill provider, flight, delay, and passenger details.
3. Click **Run Agent**.
4. Review:
   - Eligibility + rationale + confidence
   - RAG citations (chunk id, title, similarity score)
   - Selected submission channel
   - Email draft or form payload preview
5. Edit draft (if email route), click **Approve & Simulate Submission**.
6. Confirm logs updated in:
   - `logs/events.jsonl`
   - `logs/claims.sqlite`

## Notes

- Fallback mode requires no API key and still produces deterministic output via heuristics and templates.
- Claude mode uses Anthropic tool calling for orchestration; RAG retrieval is served from a local SQLite FTS index (BM25).
- This is a demo assistant and not legal advice.
- JSON intake accepts common keys (`provider`, `flight_number`, `flight_date`, `departure_airport`, `arrival_airport`, `arrival_delay_hours`, `distance_km`, `passenger_name`, `passenger_email`, `notes`) and can also extract these from raw `email_text` when possible.
- JSON intake now performs case-type policy checks for:
  - `flight` -> Regulation (EC) No 261/2004
  - `rail` -> Regulation (EU) 2021/782
  - `bus_coach` -> Regulation (EU) No 181/2011
  - `sea` -> Regulation (EU) No 1177/2010
  - `parcel_delivery` -> Directive 2011/83/EU (delivery/refund timeline)
  - `package_travel` -> Directive (EU) 2015/2302
- Non-flight cases (`rail`, `bus_coach`, `sea`, `parcel_delivery`, `package_travel`) now include automated eligibility heuristics, claim draft generation, and simulated submission logging in the same human-in-the-loop flow.
