import { supabase } from '@/integrations/supabase/client';
import type { Dispute, DisputeRow, MessageRow, AgentRunRow, ApprovePayload, WebhookPayload, ScanResponse, ApiError, DisputeStatus } from '@/types/dispute';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

// ─── Status mapping (cases table uses lowercase, UI uses uppercase enums) ───

const STATUS_MAP: Record<string, DisputeStatus> = {
  scanned: 'SCANNED_MATCH',
  scanned_match: 'SCANNED_MATCH',
  awaiting_approval: 'AWAITING_USER_APPROVAL',
  waiting_vendor: 'WAITING_VENDOR_RESPONSE',
  waiting_vendor_response: 'WAITING_VENDOR_RESPONSE',
  resolved_success: 'RESOLVED_SUCCESS',
  resolved: 'RESOLVED_SUCCESS',
  resolved_rejected: 'RESOLVED_REJECTED',
  rejected: 'RESOLVED_REJECTED',
  discarded: 'DISCARDED_BY_USER',
  discarded_by_user: 'DISCARDED_BY_USER',
  failed: 'FAILED',
};

function normalizeStatus(raw: string | null): DisputeStatus {
  if (!raw) return 'SCANNED_MATCH';
  // If already uppercase enum, pass through
  const upper = raw.toUpperCase();
  if (['SCANNED_MATCH','AWAITING_USER_APPROVAL','WAITING_VENDOR_RESPONSE','RESOLVED_SUCCESS','RESOLVED_REJECTED','DISCARDED_BY_USER','FAILED'].includes(upper)) {
    return upper as DisputeStatus;
  }
  return STATUS_MAP[raw.toLowerCase()] ?? 'SCANNED_MATCH';
}

// ─── Helpers ────────────────────────────────────────────────

function rowToDispute(row: DisputeRow, messages?: MessageRow[], agentRuns?: AgentRunRow[]): Dispute {
  return {
    dispute_id: row.dispute_id,
    id: row.dispute_id,
    user_id: row.user_id,
    category: row.category ?? 'unknown',
    status: normalizeStatus(row.status),
    vendor_name: row.vendor_name ?? 'Unknown Vendor',
    policy_region: row.policy_region,
    draft_payload_json: row.draft_payload_json as Record<string, unknown> | null,
    latest_reason: row.latest_reason,
    created_at: row.created_at,
    updated_at: row.updated_at,
    messages: messages ?? [],
    agent_runs: agentRuns ?? [],
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function caseRowToDispute(row: any): Dispute {
  // Extract AI reasoning from decision_json.eligibility.reasons
  let aiReasons: string[] | undefined;
  try {
    const dj = row.decision_json;
    if (dj?.eligibility?.reasons && Array.isArray(dj.eligibility.reasons)) {
      aiReasons = dj.eligibility.reasons;
    }
  } catch { /* ignore */ }

  return {
    dispute_id: row.id,
    id: row.id,
    user_id: null,
    category: row.category ?? 'unknown',
    status: normalizeStatus(row.status),
    vendor_name: row.vendor ?? 'Unknown Vendor',
    policy_region: 'EU',
    draft_payload_json: row.decision_json ?? null,
    latest_reason: row.eligibility_result ?? null,
    created_at: row.created_at,
    updated_at: row.updated_at ?? row.created_at,
    estimated_value: row.estimated_value ?? 0,
    recovered_amount: row.recovered_amount ?? null,
    fee_amount: row.fee_amount ?? null,
    stripe_checkout_url: row.stripe_checkout_url ?? null,
    flight_number: row.flight_number ?? undefined,
    booking_ref: row.booking_reference ?? undefined,
    email_subject: row.email_subject ?? undefined,
    email_body: row.email_body ?? undefined,
    draft_claim: row.draft_email_body ?? undefined,
    ai_reasons: aiReasons,
    messages: [],
    agent_runs: [],
  };
}

// ─── Supabase read-only queries ─────────────────────────────

async function fetchDisputesFromSupabase(): Promise<Dispute[]> {
  // Try disputes table first
  const { data: disputeRows, error: dErr } = await supabase
    .from('disputes')
    .select('*')
    .order('updated_at', { ascending: false });

  // Also fetch from cases table
  const { data: caseRows, error: cErr } = await supabase
    .from('cases')
    .select('*')
    .order('updated_at', { ascending: false });

  const disputes: Dispute[] = [];

  if (!dErr && disputeRows && disputeRows.length > 0) {
    disputes.push(...disputeRows.map((r) => rowToDispute(r as unknown as DisputeRow)));
  }

  if (!cErr && caseRows && caseRows.length > 0) {
    // Avoid duplicates — cases that already exist in disputes by some shared key
    const existingIds = new Set(disputes.map(d => d.dispute_id));
    const caseMapped = caseRows
      .map(caseRowToDispute)
      .filter(c => !existingIds.has(c.dispute_id));
    disputes.push(...caseMapped);
  }

  if (disputes.length === 0 && dErr && cErr) {
    throw dErr;
  }

  // Sort combined by updated_at desc
  disputes.sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());

  return disputes;
}

async function fetchDisputeFromSupabase(disputeId: string): Promise<Dispute | null> {
  // Try disputes table first
  const { data: row } = await supabase
    .from('disputes')
    .select('*')
    .eq('dispute_id', disputeId)
    .maybeSingle();

  if (row) {
    const [msgRes, runRes] = await Promise.all([
      supabase.from('messages').select('*').eq('dispute_id', disputeId).order('created_at', { ascending: true }),
      supabase.from('agent_runs').select('*').eq('dispute_id', disputeId).order('created_at', { ascending: true }),
    ]);
    return rowToDispute(
      row as unknown as DisputeRow,
      (msgRes.data ?? []) as unknown as MessageRow[],
      (runRes.data ?? []) as unknown as AgentRunRow[],
    );
  }

  // Fallback to cases table
  const { data: caseRow } = await supabase
    .from('cases')
    .select('*')
    .eq('id', disputeId)
    .maybeSingle();

  if (caseRow) {
    // Fetch case_events for timeline
    const { data: events } = await supabase
      .from('case_events')
      .select('*')
      .eq('case_id', disputeId)
      .order('created_at', { ascending: true });

    const dispute = caseRowToDispute(caseRow);
    // Map case_events to agent_runs format for the timeline
    if (events && events.length > 0) {
      dispute.agent_runs = events.map((e) => ({
        agent_run_id: e.id,
        dispute_id: disputeId,
        agent_name: e.actor ?? 'system',
        step_name: e.event_type ?? 'event',
        status: 'completed',
        input_json: {},
        output_json: (e.details as Record<string, unknown>) ?? {},
        error_text: null,
        created_at: e.created_at ?? '',
      }));
    }
    return dispute;
  }

  return null;
}

// ─── HTTP client for mutations (external backend) ───────────

class ApiClient {
  private async request<T>(path: string, options?: RequestInit): Promise<T> {
    const url = `${BASE_URL}${path}`;
    const res = await fetch(url, {
      headers: { 'Content-Type': 'application/json', ...options?.headers },
      ...options,
    });

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      const error: ApiError = {
        message: body.message || body.error || `Request failed (${res.status})`,
        status: res.status,
      };
      throw error;
    }

    return res.json();
  }

  /** POST /api/v1/scan — triggers inbox scan */
  scan(): Promise<ScanResponse> {
    return this.request('/api/v1/scan', { method: 'POST' });
  }

  /** Read disputes from Supabase (primary), fallback to HTTP */
  async getDisputes(): Promise<Dispute[]> {
    try {
      return await fetchDisputesFromSupabase();
    } catch {
      // fallback to HTTP if Supabase fails
      return this.request('/api/v1/disputes');
    }
  }

  /** Read single dispute from Supabase (primary), fallback to HTTP */
  async getDispute(disputeId: string): Promise<Dispute> {
    try {
      const d = await fetchDisputeFromSupabase(disputeId);
      if (d) return d;
      throw new Error('not found');
    } catch {
      return this.request(`/api/v1/disputes/${disputeId}`);
    }
  }

  /** Approve or reject a case directly in Supabase */
  async submitDecisionToSupabase(caseId: string, decision: 'APPROVE' | 'REJECT', note?: string): Promise<void> {
    const newStatus = decision === 'APPROVE' ? 'waiting_vendor' : 'discarded';

    const { error: updateErr } = await supabase
      .from('cases')
      .update({ status: newStatus, updated_at: new Date().toISOString() })
      .eq('id', caseId);

    if (updateErr) throw updateErr;

    // Log the event
    await supabase.from('case_events').insert({
      case_id: caseId,
      event_type: decision === 'APPROVE' ? 'user_approved' : 'user_rejected',
      actor: 'user',
      details: { decision, note: note ?? null },
    });
  }
}

export const api = new ApiClient();
