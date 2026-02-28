import { DisputeStatus } from '@/types/dispute';
import { Check, Circle, Clock, AlertTriangle, XCircle } from 'lucide-react';
import { cn } from '@/lib/utils';

interface TimelineStep {
  label: string;
  completed: boolean;
  active: boolean;
  failed?: boolean;
}

function getTimelineSteps(status: DisputeStatus | string): TimelineStep[] {
  const steps: TimelineStep[] = [
    { label: 'Email Scanned', completed: false, active: false },
    { label: 'Draft Generated', completed: false, active: false },
    { label: 'Awaiting Approval', completed: false, active: false },
    { label: 'Submitted to Vendor', completed: false, active: false },
    { label: 'Resolved', completed: false, active: false },
  ];

  switch (status) {
    case 'SCANNED_MATCH':
      steps[0].completed = true;
      steps[1].active = true;
      break;
    case 'AWAITING_USER_APPROVAL':
      steps[0].completed = true;
      steps[1].completed = true;
      steps[2].active = true;
      break;
    case 'WAITING_VENDOR_RESPONSE':
      steps[0].completed = true;
      steps[1].completed = true;
      steps[2].completed = true;
      steps[3].active = true;
      break;
    case 'RESOLVED_SUCCESS':
      steps.forEach(s => { s.completed = true; });
      break;
    case 'RESOLVED_REJECTED':
      steps[0].completed = true;
      steps[1].completed = true;
      steps[2].completed = true;
      steps[3].completed = true;
      steps[4] = { label: 'Rejected by Vendor', completed: false, active: false, failed: true };
      break;
    case 'DISCARDED_BY_USER':
      steps[0].completed = true;
      steps[1].completed = true;
      steps[2] = { label: 'Discarded by User', completed: false, active: false, failed: true };
      break;
    case 'FAILED':
      steps[0].completed = true;
      steps[1] = { label: 'Processing Failed', completed: false, active: false, failed: true };
      break;
  }

  return steps;
}

interface AgentTimelineProps {
  status: DisputeStatus | string;
}

const AgentTimeline = ({ status }: AgentTimelineProps) => {
  const steps = getTimelineSteps(status);

  return (
    <div className="space-y-0">
      <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-muted-foreground">Agent Timeline</h3>
      <div className="relative space-y-0">
        {steps.map((step, i) => (
          <div key={i} className="flex gap-3">
            <div className="flex flex-col items-center">
              <div
                className={cn(
                  'flex h-7 w-7 items-center justify-center rounded-full border-2',
                  step.completed && 'border-success bg-success text-success-foreground',
                  step.active && 'border-primary bg-primary/10 text-primary',
                  step.failed && 'border-destructive bg-destructive/10 text-destructive',
                  !step.completed && !step.active && !step.failed && 'border-border bg-muted text-muted-foreground'
                )}
              >
                {step.completed ? <Check className="h-3.5 w-3.5" /> :
                 step.failed ? <XCircle className="h-3.5 w-3.5" /> :
                 step.active ? <Clock className="h-3.5 w-3.5" /> :
                 <Circle className="h-3 w-3" />}
              </div>
              {i < steps.length - 1 && (
                <div className={cn('h-8 w-0.5', step.completed ? 'bg-success' : 'bg-border')} />
              )}
            </div>
            <div className="pb-8">
              <p className={cn(
                'text-sm font-medium leading-7',
                step.completed && 'text-foreground',
                step.active && 'text-primary font-semibold',
                step.failed && 'text-destructive',
                !step.completed && !step.active && !step.failed && 'text-muted-foreground'
              )}>
                {step.label}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default AgentTimeline;
