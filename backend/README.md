## Devpost
https://devpost.com/software/compensai-choakb

# CompensAI Backend (FastAPI + Supabase)

Hackathon backend scaffolding for a 3‑agent compensation pipeline:
- **Agent 1 (n8n + Gmail):** scans inbox → extracts “intake” JSON → calls backend.
- **Agent 2 (FastAPI):** eligibility + draft generation → writes to Supabase.
- **Agent 3 (FastAPI, mandatory):** billing artifacts after resolution (event + optional Stripe link).
- **UI (Lovable):** reads from Supabase directly (realtime) and calls backend only for approval/reprocess.

Supabase (`public.cases`, `public.case_events`) is the shared state + event log; the backend is an orchestrator/writer.

## Architecture recommendation
- **Communication:** HTTP webhooks between n8n and FastAPI; Supabase is the source of truth.
- **State:** one row per case in `public.cases` (current snapshot), append‑only timeline in `public.case_events`.
- **Realtime UI:** Lovable subscribes to `cases` and `case_events` changes (Supabase realtime) to update dashboards + timelines.
- **Agent 2 logic:** Claude-first extraction/decision with deterministic fallback; supports flights + marketplace + trains and can fetch demo policy/form/contact pages (no Playwright submission in V1).

## Endpoints (implemented)
Base URL: `http://localhost:8000`

### `POST /emails/ingest` (Agent 1 → Backend, triage-first)
Use this endpoint if n8n is sending *all* emails and you want the backend to decide **trash vs candidate**.
Only candidates create a case and trigger Agent2.

### `POST /cases/intake` (Agent 1 → Backend)
Optional auth header (recommended for server‑to‑server): `X-CompensAI-Webhook-Secret`

Request JSON:
```json
{
  "source": "gmail",
  "message_id": "18c4...",
  "thread_id": "18c4...",
  "from_email": "support@vendor.com",
  "to_email": "you@gmail.com",
  "email_subject": "Your flight was delayed",
  "email_body": "…full text…",
  "vendor": "Ryanair",
  "category": "flight_delay",
  "incident_date": "2025-01-14",
  "flight_number": "FR123",
  "booking_reference": "ABCDEF",
  "estimated_value": 250,
  "extracted_fields": { "delay_hours": 4 }
}
```

Response JSON:
```json
{
  "id": "case-uuid",
  "status": "awaiting_approval",
  "existing": false,
  "case": { "...full cases row..." }
}
```

Writes:
- `cases`: inserts baseline email context + sets `status=processing`, then runs Agent 2 and updates fields.
- `case_events`: `email_scanned` (agent1), then `draft_generated` + `awaiting_approval` (agent2).

### `POST /cases/{id}/approve` (UI → Backend → Agent 1)
Optional auth header: `X-CompensAI-Admin-Key` (not safe for browser apps; hackathon-only)

Request JSON:
```json
{ "approved_by": "rita", "notes": "ok to send", "send_via": "email", "dry_run": false }
```

Behavior:
- Calls `AGENT1_SEND_WEBHOOK_URL` (n8n) with the draft email/form payload (unless `dry_run=true`).
- Updates `cases.status=submitted_to_vendor`
- Inserts `case_events.submitted_to_vendor`

### `POST /cases/{id}/vendor_response` (Agent 1 → Backend)
Optional auth header (recommended): `X-CompensAI-Webhook-Secret`

Request JSON:
```json
{
  "outcome": "accepted",
  "resolved": true,
  "recovered_amount": 250,
  "currency": "eur",
  "evidence": { "vendor_ref": "XYZ" },
  "message_id": "18c4...",
  "thread_id": "18c4..."
}
```

Behavior:
- Updates `cases.status` and stores vendor response under `cases.decision_json.vendor_response`
- Inserts `case_events.vendor_replied`
- If resolved → runs Agent 3 billing and inserts `case_events.resolved` + `case_events.billing_created`

### `POST /cases/{id}/run_agent2` (optional manual reprocess)
Optional auth header: `X-CompensAI-Admin-Key`

Behavior: re-runs Agent 2 on the current `cases` row and appends events.

## DB fields UI can rely on
- **Case list:** `id, vendor, category, estimated_value, status, updated_at`
- **Case detail:** `email_subject, email_body, from_email, to_email, decision_json, draft_email_* , form_data`
- **Timeline:** `case_events` ordered by `created_at`
- **Economics (hackathon):**
  - On resolution, we reuse `cases.estimated_value` as the known recovered amount (if provided).
  - Canonical billing payload is stored in `cases.decision_json.billing` and the `billing_created` event `details`.

## Minimal folder structure
```text
app/
  main.py
  core/
    config.py
    security.py
  db/
    supabase.py
  repositories/
    cases.py
  routers/
    cases.py
  services/
    agent2.py
    billing.py
requirements.txt
.env.example
```

## Local run
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

## Env vars (minimum)
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` (server-side only)

Optional:
- `N8N_WEBHOOK_SECRET` (enables `X-CompensAI-Webhook-Secret` checks)
- `AGENT1_SEND_WEBHOOK_URL` (approve → n8n send webhook)
- `ANTHROPIC_API_KEY` (Claude for Agent 2)
- `ANTHROPIC_MODEL` (default `claude-haiku-4-5-20251001`)
- `ANTHROPIC_TIMEOUT_SECONDS` (default `30`)
- `STRIPE_SECRET_KEY`, `STRIPE_SUCCESS_URL`, `STRIPE_CANCEL_URL`
- `SUCCESS_FEE_RATE` (default `0.2`)
- `CORS_ORIGINS` (comma-separated)

## Quick test with Ryanair delay mock
Run backend first, then post the example payload:

```bash
curl -X POST http://localhost:8000/cases/intake \
  -H "Content-Type: application/json" \
  --data @examples/intake_ryanair_delay.json
```

If `N8N_WEBHOOK_SECRET` is configured, also include:

```bash
curl -X POST http://localhost:8000/cases/intake \
  -H "Content-Type: application/json" \
  -H "X-CompensAI-Webhook-Secret: <your-secret>" \
  --data @examples/intake_ryanair_delay.json
```

Expected behavior:
- A new row appears in `public.cases` with extraction, eligibility, draft, and form fields populated.
- Timeline rows appear in `public.case_events` (`email_scanned`, `draft_generated`, `awaiting_approval`).
- If Claude is unavailable, the case is still processed via deterministic fallback and saved.

## Quick tests (other domains)
Airline cancellation (includes demo airline URLs in body):
```bash
curl -X POST http://localhost:8000/cases/intake \
  -H "Content-Type: application/json" \
  --data @examples/intake_flight_cancellation.json
```

Marketplace late delivery (vendor forced to `DemoRetail`; includes demo retail policy/contact URLs in body):
```bash
curl -X POST http://localhost:8000/cases/intake \
  -H "Content-Type: application/json" \
  --data @examples/intake_delivery_late.json
```

## Supabase verification SQL
Use Supabase SQL editor:

```sql
select id, vendor, category, eligibility_result, estimated_value, status, updated_at
from public.cases
order by updated_at desc
limit 10;
```

```sql
select case_id, actor, event_type, details, created_at
from public.case_events
order by created_at desc
limit 20;
```
# Other parts of the project

## Lovable UI
https://github.com/yauhenifutryn/dispute-defender-dash

## Demo websites for the company (airline and marketplace)
https://skill-deploy-x4cr0r1eo8-codex-agent-deploys.vercel.app/index.html airline and amazon demo webstes
