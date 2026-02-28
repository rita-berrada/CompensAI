import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Mail, Plane, Hash, Calendar, Loader2, AlertCircle, Brain } from 'lucide-react';
import { Button } from '@/components/ui/button';
import StatusBadge from '@/components/StatusBadge';
import EconomicsWidget from '@/components/EconomicsWidget';
import AgentTimeline from '@/components/AgentTimeline';
import HITLActionBlock from '@/components/HITLActionBlock';

import { Dispute, DisputeEconomics, DisputeStatus } from '@/types/dispute';
import { MOCK_DISPUTES } from '@/data/mockDisputes';
import { api } from '@/lib/api';
import { useState, useEffect, useCallback } from 'react';
import { toast } from 'sonner';

const CATEGORY_LABELS: Record<string, string> = {
  flight_delay: 'Flight Delay',
  damaged_parcel: 'Damaged Parcel',
  late_delivery: 'Late Delivery',
  overcharge: 'Overcharge',
  cancellation: 'Cancellation',
};

const DisputeDetail = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [dispute, setDispute] = useState<Dispute | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const fetchDispute = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.getDispute(id);
      setDispute(data);
    } catch {
      const found = MOCK_DISPUTES.find(d => d.dispute_id === id || d.id === id);
      if (found) {
        setDispute(found);
      } else {
        setError('Dispute not found.');
      }
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchDispute();
  }, [fetchDispute]);

  const handleDecision = async (decision: 'APPROVE' | 'REJECT', note?: string) => {
    if (!dispute) return;
    setSubmitting(true);
    try {
      await api.submitDecisionToSupabase(dispute.id, decision, note);
      const newStatus: DisputeStatus = decision === 'APPROVE' ? 'WAITING_VENDOR_RESPONSE' : 'DISCARDED_BY_USER';
      setDispute(prev => prev ? { ...prev, status: newStatus } : prev);
      toast.success(decision === 'APPROVE' ? 'Claim approved and submitted!' : 'Draft rejected.');
    } catch (err) {
      console.error('Decision error:', err);
      toast.error('Failed to submit decision. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  const extractEconomics = (): DisputeEconomics | null => {
    if (!dispute?.agent_runs?.length) return null;
    for (const run of dispute.agent_runs) {
      const o = run.output_json;
      if (o && typeof o.compute_cost_usd === 'number' && typeof o.value_generated_usd === 'number') {
        return {
          compute_cost_usd: o.compute_cost_usd as number,
          value_generated_usd: o.value_generated_usd as number,
          margin_pct: typeof o.margin_pct === 'number' ? (o.margin_pct as number) : 0,
        };
      }
    }
    return null;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error || !dispute) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-20">
        <AlertCircle className="h-8 w-8 text-destructive" />
        <p className="text-sm text-muted-foreground">{error || 'Dispute not found.'}</p>
        <Button variant="outline" size="sm" onClick={() => navigate('/dashboard')}>Back</Button>
      </div>
    );
  }

  const economics = extractEconomics();

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" onClick={() => navigate('/dashboard')}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold text-foreground">{dispute.vendor_name ?? 'Unknown Vendor'}</h1>
            <StatusBadge status={(dispute.status ?? 'SCANNED_MATCH') as DisputeStatus} />
          </div>
          <p className="text-sm text-muted-foreground">{CATEGORY_LABELS[dispute.category] ?? dispute.category ?? '—'} · {dispute.created_at ? new Date(dispute.created_at).toLocaleDateString() : '—'}</p>
        </div>
      </div>

      {/* Two-column layout */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Left: Context + Draft */}
        <div className="space-y-4">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Original Context</h3>
          <div className="rounded-xl border border-border bg-card p-5 space-y-4">
            <div className="flex items-start gap-3">
              <Mail className="mt-0.5 h-4 w-4 text-muted-foreground" />
              <div>
                <p className="text-xs text-muted-foreground">Subject</p>
                <p className="text-sm font-medium text-foreground">{dispute.email_subject ?? '—'}</p>
              </div>
            </div>
            {dispute.flight_number && (
              <div className="flex items-start gap-3">
                <Plane className="mt-0.5 h-4 w-4 text-muted-foreground" />
                <div>
                  <p className="text-xs text-muted-foreground">Flight Number</p>
                  <p className="text-sm font-medium text-foreground">{dispute.flight_number}</p>
                </div>
              </div>
            )}
            {dispute.booking_ref && (
              <div className="flex items-start gap-3">
                <Hash className="mt-0.5 h-4 w-4 text-muted-foreground" />
                <div>
                  <p className="text-xs text-muted-foreground">Reference</p>
                  <p className="text-sm font-mono text-foreground">{dispute.booking_ref}</p>
                </div>
              </div>
            )}
            <div className="flex items-start gap-3">
              <Calendar className="mt-0.5 h-4 w-4 text-muted-foreground" />
              <div>
                <p className="text-xs text-muted-foreground">Date</p>
                <p className="text-sm font-medium text-foreground">{dispute.created_at ? new Date(dispute.created_at).toLocaleDateString() : '—'}</p>
              </div>
            </div>
            {dispute.email_body && (
              <div className="border-t border-border pt-3">
                <p className="text-xs text-muted-foreground">Email excerpt</p>
                <p className="mt-1 text-xs leading-relaxed text-foreground/80">{dispute.email_body}</p>
              </div>
            )}
          </div>

          {/* AI Reasoning */}
          {dispute.ai_reasons && dispute.ai_reasons.length > 0 && (
            <>
              <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground mt-2">AI Reasoning</h3>
              <div className="rounded-xl border border-border bg-card p-5 space-y-3">
                <div className="flex items-center gap-2 mb-1">
                  <Brain className="h-4 w-4 text-primary" />
                  <p className="text-sm font-medium text-foreground">Why this claim was flagged</p>
                </div>
                <ul className="space-y-2">
                  {dispute.ai_reasons.map((reason, i) => (
                    <li key={i} className="flex items-start gap-2.5">
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                      <p className="text-sm leading-relaxed text-muted-foreground">{reason}</p>
                    </li>
                  ))}
                </ul>
              </div>
            </>
          )}

          {economics && <EconomicsWidget economics={economics} />}
        </div>

        {/* Right: Actions + Timeline */}
        <div className="space-y-6">
          <HITLActionBlock dispute={dispute} onDecision={handleDecision} submitting={submitting} />
          <AgentTimeline status={(dispute.status ?? 'SCANNED_MATCH') as DisputeStatus} />
        </div>
      </div>
    </div>
  );
};

export default DisputeDetail;
