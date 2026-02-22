# CompensAI Backend

FastAPI backend for an AI-powered compensation claims processing system. Automatically processes emails, extracts claim information, and calculates fees.

## Features

- **Email Triage**: Automatically filters compensation-related emails from spam
- **Claim Processing**: Extracts flight details, booking references, and incident information
- **Eligibility Assessment**: Evaluates claims against EU261 regulations
- **Draft Generation**: Creates email drafts or PDF forms for claim submission
- **Billing**: Calculates 10% success fee on recovered amounts

## Architecture

- **Agent 1 (n8n)**: Scans Gmail inbox and sends emails to backend
- **Agent 2 (FastAPI)**: Processes cases, extracts data, generates drafts
- **Agent 3 (FastAPI)**: Handles billing when cases are resolved
- **Supabase**: Database for cases and events
- **Claude (Anthropic)**: AI model for email triage and claim processing

## Setup

### 1. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Environment Variables

Create a `.env` file with:

```bash
# Required
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
ANTHROPIC_API_KEY=your-anthropic-key

# Optional
N8N_WEBHOOK_SECRET=hackai
ADMIN_API_KEY=admin
SUCCESS_FEE_RATE=0.1
CORS_ORIGINS=http://localhost:3000
```

### 3. Run the Server

```bash
uvicorn app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`

## API Endpoints

### Email Ingestion

**POST `/emails/ingest`**
- Triage endpoint: receives all emails from n8n
- Filters spam and creates cases for candidates
- Headers: `X-CompensAI-Webhook-Secret: <secret>`

### Case Management

**POST `/cases/intake`**
- Direct case creation endpoint
- Headers: `X-CompensAI-Webhook-Secret: <secret>`

**POST `/cases/{case_id}/approve`**
- Approve a draft email
- Headers: `X-CompensAI-Admin-Key: <admin-key>`

**POST `/cases/{case_id}/vendor_response`**
- Record vendor response and resolve case
- Triggers billing calculation (10% fee)
- Headers: `X-CompensAI-Webhook-Secret: <secret>`

**GET `/cases/email-drafts/pending`**
- Get all approved drafts ready to send
- Headers: `X-CompensAI-Webhook-Secret: <secret>`

**GET `/cases/{case_id}`**
- Get a single case by ID
- Headers: `X-CompensAI-Admin-Key: <admin-key>`

## Testing

Run the complete workflow test:

```bash
./test_full_workflow.sh
```

This will:
1. Create a test case from an email
2. Wait for Agent 2 to process it
3. Resolve the case with €250 recovered
4. Show results: €250 recovered → €25 fee (10%)

## Database Schema

### `cases` Table
- `id`: UUID
- `status`: processing | awaiting_approval | submitted_to_vendor | resolved
- `vendor`: Airline/vendor name
- `category`: flight_delay | flight_cancellation | etc.
- `recovered_amount`: Amount recovered (EUR)
- `fee_amount`: Success fee (10% of recovered)
- `email_subject`, `email_body`: Original email content
- `draft_email_subject`, `draft_email_body`: Generated drafts
- `decision_json`: Full processing details (JSONB)

### `case_events` Table
- Event log for each case
- Tracks: email_scanned, agent2_processed, approved, vendor_replied, resolved, billing_created

## Project Structure

```
app/
  main.py              # FastAPI application
  routers/
    cases.py          # Case management endpoints
    emails.py         # Email ingestion endpoint
  services/
    triage.py         # Email triage logic
    agent2.py         # Claim processing
    billing.py        # Fee calculation
    claude_client.py  # Anthropic API client
  repositories/
    cases.py          # Database operations
  db/
    supabase.py       # Supabase client
  core/
    config.py         # Settings
    security.py       # Auth middleware
```

## License

MIT
