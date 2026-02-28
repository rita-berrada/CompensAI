import { DisputeStatus } from '@/types/dispute';
import { cn } from '@/lib/utils';

const STATUS_CONFIG: Record<DisputeStatus, { label: string; className: string }> = {
  SCANNED_MATCH: { label: 'Scanned', className: 'bg-muted text-muted-foreground' },
  AWAITING_USER_APPROVAL: { label: 'Needs Approval', className: 'bg-warning/15 text-warning border border-warning/30' },
  WAITING_VENDOR_RESPONSE: { label: 'Pending Vendor', className: 'bg-primary/10 text-primary border border-primary/20' },
  RESOLVED_SUCCESS: { label: 'Resolved', className: 'bg-success/15 text-success border border-success/30' },
  RESOLVED_REJECTED: { label: 'Rejected', className: 'bg-destructive/15 text-destructive border border-destructive/30' },
  DISCARDED_BY_USER: { label: 'Discarded', className: 'bg-muted text-muted-foreground' },
  FAILED: { label: 'Failed', className: 'bg-destructive/15 text-destructive border border-destructive/30' },
};

interface StatusBadgeProps {
  status: DisputeStatus | string;
}

const StatusBadge = ({ status }: StatusBadgeProps) => {
  const config = STATUS_CONFIG[status as DisputeStatus] ?? { label: status ?? 'Unknown', className: 'bg-muted text-muted-foreground' };
  return (
    <span className={cn('inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold', config.className)}>
      {config.label}
    </span>
  );
};

export default StatusBadge;
