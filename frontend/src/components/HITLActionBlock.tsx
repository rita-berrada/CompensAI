import { useState } from 'react';
import { Dispute } from '@/types/dispute';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { CheckCircle, XCircle, Loader2 } from 'lucide-react';

interface HITLActionBlockProps {
  dispute: Dispute;
  onDecision: (decision: 'APPROVE' | 'REJECT', content?: string, formFieldsOverride?: Record<string, unknown>) => void;
  submitting?: boolean;
}

// Structured fields shown as individual editable inputs (label → field key)
const EDITABLE_FIELDS: { label: string; key: string }[] = [
  { label: 'Booking Reference', key: 'booking_reference' },
  { label: 'Flight Number', key: 'flight_number' },
  { label: 'Incident Date', key: 'incident_date' },
  { label: 'Delay (minutes)', key: 'delay_minutes' },
];

const HITLActionBlock = ({ dispute, onDecision, submitting }: HITLActionBlockProps) => {
  const formFill = (dispute.draft_payload_json as Record<string, unknown> | null)
    ?.form_fill as Record<string, unknown> | undefined;
  const isFormCase = !!formFill?.screenshot_filename || !!formFill?.video_filename;

  // Form case: editable structured fields + complaint summary
  const rawFields = (formFill?.fields_to_fill ?? {}) as Record<string, unknown>;
  const [formFields, setFormFields] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const { key } of EDITABLE_FIELDS) {
      init[key] = rawFields[key] != null ? String(rawFields[key]) : '';
    }
    init['complaint_summary'] = rawFields['complaint_summary'] != null
      ? String(rawFields['complaint_summary'])
      : '';
    return init;
  });

  // Email case: editable draft
  const [editedDraft, setEditedDraft] = useState<string>(dispute.draft_claim ?? '');

  if (dispute.status !== 'AWAITING_USER_APPROVAL') return null;
  if (!isFormCase && !dispute.draft_claim) return null;

  if (isFormCase) {
    const fieldsFilled: string[] = (formFill?.fields_filled as string[]) ?? [];
    const fieldsSkipped: string[] = (formFill?.fields_skipped as string[]) ?? [];

    const handleApprove = () => {
      // Only send fields that changed from the original
      const overrides: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(formFields)) {
        const original = rawFields[k] != null ? String(rawFields[k]) : '';
        if (v !== original) overrides[k] = v;
      }
      onDecision('APPROVE', undefined, Object.keys(overrides).length > 0 ? overrides : undefined);
    };

    return (
      <div className="rounded-xl border-2 border-warning/30 bg-warning/5 p-6 space-y-4">
        <div>
          <h3 className="text-sm font-bold uppercase tracking-wider text-warning">Action Required: Review & Edit Form Fields</h3>
          <p className="text-xs text-muted-foreground mt-1">
            Correct any field the AI got wrong, then approve to submit.
          </p>
        </div>

        {/* Editable structured fields */}
        <div className="rounded-lg border border-border bg-card p-4 space-y-3">
          {EDITABLE_FIELDS.map(({ label, key }) => (
            <div key={key} className="grid grid-cols-[140px_1fr] items-center gap-2">
              <label className="text-xs font-medium text-muted-foreground">{label}</label>
              <Input
                value={formFields[key]}
                onChange={(e) => setFormFields(prev => ({ ...prev, [key]: e.target.value }))}
                className="h-7 text-xs font-mono bg-background"
                disabled={submitting}
                placeholder="—"
              />
            </div>
          ))}
        </div>

        {/* Editable complaint summary */}
        <div className="rounded-lg border border-border bg-card p-4 space-y-2">
          <label className="text-xs font-medium text-muted-foreground">Complaint Summary</label>
          <Textarea
            value={formFields['complaint_summary']}
            onChange={(e) => setFormFields(prev => ({ ...prev, complaint_summary: e.target.value }))}
            className="min-h-[120px] text-xs font-mono leading-relaxed bg-background"
            disabled={submitting}
            placeholder="No complaint summary generated"
          />
        </div>

        {/* Field match stats */}
        {(fieldsFilled.length > 0 || fieldsSkipped.length > 0) && (
          <div className="flex gap-3 text-xs text-muted-foreground">
            {fieldsFilled.length > 0 && (
              <span className="text-success font-medium">{fieldsFilled.length} filled</span>
            )}
            {fieldsSkipped.length > 0 && (
              <span className="text-warning font-medium">{fieldsSkipped.length} skipped ({fieldsSkipped.join(', ')})</span>
            )}
          </div>
        )}

        <div className="flex gap-3">
          <Button
            onClick={handleApprove}
            className="flex-1 bg-success text-success-foreground hover:bg-success/90"
            size="lg"
            disabled={submitting}
          >
            {submitting ? <Loader2 className="mr-2 h-5 w-5 animate-spin" /> : <CheckCircle className="mr-2 h-5 w-5" />}
            Approve & Submit Form
          </Button>
          <Button
            onClick={() => onDecision('REJECT')}
            variant="outline"
            size="lg"
            className="flex-1 border-muted-foreground/30 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
            disabled={submitting}
          >
            <XCircle className="mr-2 h-5 w-5" />
            Reject
          </Button>
        </div>
      </div>
    );
  }

  // Email case: show editable AI-drafted email
  return (
    <div className="rounded-xl border-2 border-warning/30 bg-warning/5 p-6 space-y-4">
      <div>
        <h3 className="mb-1 text-sm font-bold uppercase tracking-wider text-warning">Action Required</h3>
        <p className="text-xs text-muted-foreground">Edit the AI-drafted claim if needed, then approve or reject.</p>
      </div>

      <Textarea
        value={editedDraft}
        onChange={(e) => setEditedDraft(e.target.value)}
        className="min-h-[200px] font-mono text-xs leading-relaxed bg-card"
        disabled={submitting}
      />

      <div className="flex gap-3">
        <Button
          onClick={() => onDecision('APPROVE', editedDraft)}
          className="flex-1 bg-success text-success-foreground hover:bg-success/90"
          size="lg"
          disabled={submitting}
        >
          {submitting ? <Loader2 className="mr-2 h-5 w-5 animate-spin" /> : <CheckCircle className="mr-2 h-5 w-5" />}
          Approve & Submit
        </Button>
        <Button
          onClick={() => onDecision('REJECT')}
          variant="outline"
          size="lg"
          className="flex-1 border-muted-foreground/30 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
          disabled={submitting}
        >
          <XCircle className="mr-2 h-5 w-5" />
          Reject Draft
        </Button>
      </div>
    </div>
  );
};

export default HITLActionBlock;
