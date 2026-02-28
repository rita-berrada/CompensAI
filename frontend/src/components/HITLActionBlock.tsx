import { Dispute } from '@/types/dispute';
import { Button } from '@/components/ui/button';
import { CheckCircle, XCircle, Loader2 } from 'lucide-react';


interface HITLActionBlockProps {
  dispute: Dispute;
  onDecision: (decision: 'APPROVE' | 'REJECT', note?: string) => void;
  submitting?: boolean;
}

const HITLActionBlock = ({ dispute, onDecision, submitting }: HITLActionBlockProps) => {
  

  if (dispute.status !== 'AWAITING_USER_APPROVAL' || !dispute.draft_claim) return null;

  return (
    <div className="rounded-xl border-2 border-warning/30 bg-warning/5 p-6">
      <h3 className="mb-1 text-sm font-bold uppercase tracking-wider text-warning">Action Required</h3>
      <p className="mb-4 text-xs text-muted-foreground">Review the AI-drafted claim below and approve or reject it.</p>

      <div className="mb-4 rounded-lg border border-border bg-card p-4">
        <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-foreground">
          {dispute.draft_claim}
        </pre>
      </div>

      <div className="flex gap-3">
        <Button
          onClick={() => onDecision('APPROVE')}
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