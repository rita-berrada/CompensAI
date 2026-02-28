export type DisputeStatus =
  | 'SCANNED_MATCH'
  | 'AWAITING_USER_APPROVAL'
  | 'WAITING_VENDOR_RESPONSE'
  | 'RESOLVED_SUCCESS'
  | 'RESOLVED_REJECTED'
  | 'DISCARDED_BY_USER'
  | 'FAILED';

export type DisputeCategory = 'flight_delay' | 'damaged_parcel' | 'late_delivery' | 'overcharge' | 'cancellation';

/** Maps directly to Supabase `agent_runs` table */
export interface AgentRunRow {
  agent_run_id: string;
  dispute_id: string | null;
  agent_name: string;
  step_name: string;
  status: string;
  input_json: Record<string, unknown>;
  output_json: Record<string, unknown>;
  error_text: string | null;
  created_at: string;
}

/** Maps directly to Supabase `messages` table */
export interface MessageRow {
  message_id: string;
  user_id: string | null;
  dispute_id: string | null;
  source: string;
  external_message_id: string;
  thread_id: string | null;
  direction: string;
  subject: string | null;
  body_text: string | null;
  payload_json: Record<string, unknown>;
  received_at: string | null;
  created_at: string;
}

/** Maps directly to Supabase `disputes` table */
export interface DisputeRow {
  dispute_id: string;
  user_id: string | null;
  category: string;
  status: string;
  vendor_name: string | null;
  policy_region: string;
  draft_payload_json: Record<string, unknown> | null;
  latest_reason: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Enriched dispute used by the UI.
 * Keeps backward-compat fields for components that still reference old names.
 */
export interface Dispute {
  // Primary key from Supabase
  dispute_id: string;
  /** @deprecated alias for dispute_id — used by legacy components */
  id: string;

  // Core fields from DB
  user_id?: string | null;
  category: DisputeCategory | string;
  status: DisputeStatus | string;
  vendor_name: string;
  policy_region?: string;
  draft_payload_json?: Record<string, unknown> | null;
  latest_reason?: string | null;
  created_at: string;
  updated_at: string;

  // Derived / UI-only convenience (populated from cases or mock)
  estimated_value?: number;
  recovered_amount?: number | null;
  fee_amount?: number | null;
  stripe_checkout_url?: string | null;
  flight_number?: string;
  booking_ref?: string;
  email_subject?: string;
  email_body?: string;
  draft_claim?: string;
  ai_reasons?: string[];

  // Joined data
  messages?: MessageRow[];
  agent_runs?: AgentRunRow[];
}

export interface DisputeEconomics {
  compute_cost_usd: number;
  value_generated_usd: number;
  margin_pct: number;
}

export interface ApprovePayload {
  decision: 'APPROVE' | 'REJECT';
  channel?: string;
  note?: string;
}

export interface WebhookPayload {
  dispute_id: string;
  thread_id: string;
  result: 'accepted' | 'rejected' | 'needs_info';
  subject: string;
  body_text: string;
  source: string;
}

export interface ScanResponse {
  status: string;
  disputes_found?: number;
}

export interface ApiError {
  message: string;
  status?: number;
}
