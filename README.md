# EU261 Compensation Claim Agent

Hackathon-ready Streamlit app that collects flight delay intake, runs an orchestrator agent with tools, drafts a claim (email or form payload), supports human approval, and logs every event to JSONL + SQLite.

## Features

- Streamlit intake form for EU261 claims
- Orchestrator agent with bounded Claude tool-calling loop (Anthropic Messages API)
- Local RAG over `data/eu261_kb.jsonl` with cached local embeddings in `data/eu261_embeddings_cache.npz`
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
2. Fill intake in the sidebar (provider, flight, delay, passenger details).
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
- Claude mode uses Anthropic tool calling for orchestration; RAG embeddings are local/deterministic.
- This is a demo assistant and not legal advice.
