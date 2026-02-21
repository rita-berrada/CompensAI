# EU Transport & Delivery Claims Agent

Hackathon-ready Streamlit app that ingests complaint JSON, classifies case type (flight/rail/bus/sea/parcel/package travel), runs regulatory analysis, drafts a claim (email or form payload), supports human approval, and logs every event to JSONL + SQLite.

## Features

- Streamlit JSON intake for multi-domain EU claims
- LLM-first case-type routing (`flight`, `rail`, `bus_coach`, `sea`, `parcel_delivery`, `package_travel`) with deterministic fallback
- Full-document lexical retrieval (SQLite FTS, no embeddings) from `data/regulations/*.txt`
- Document-grounded rule evaluation from `data/regulatory_rules.json`
- Mandatory citation output with article references and citation coverage flag
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
- `/Users/natalia2/hackeurope/compensation-agent/data/regulations/` (full regulation texts)
- `/Users/natalia2/hackeurope/compensation-agent/data/regulatory_rules.json`
- `/Users/natalia2/hackeurope/compensation-agent/regulatory_lexical.py`
- `/Users/natalia2/hackeurope/compensation-agent/regulatory_engine.py`
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
2. In sidebar, upload a JSON file containing structured fields and/or `email_text`.
3. Click **Run Agent**.
4. Review:
   - Case type + policy match
   - Eligibility + rationale + confidence
   - Legal hooks + article references
   - Regulatory citations (chunk id, section title, score)
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
- Case routing is LLM-first when `ANTHROPIC_API_KEY` is configured (heuristic fallback otherwise).
- Eligibility and outcomes are now document-grounded via `data/regulatory_rules.json` + full-doc lexical retrieval over `data/regulations/*.txt` (no embeddings).
- If lexical retrieval cannot find relevant sections, output confidence is reduced and citation requirement is marked unmet.

## Testing

1. Run automated smoke test:

```bash
python3 scripts/run_regulatory_smoke_test.py
```

2. Expected result:
   - All sample files pass.
   - `data/test_flight_delay_2h_not_eligible.json` shows `eligible=False`.
   - Each case shows `citation_requirement_met=True` and article references.

3. Manual UI check:
   - Run `streamlit run app.py`.
   - Upload each `data/test_*.json` file.
   - Verify:
     - classification block shows case type
     - policy/eligibility are populated
     - citation block includes regulation sections
     - `Citation requirement met` is `Yes`
