import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { DollarSign, Shield, TrendingUp, Loader2, AlertCircle, ExternalLink, Receipt } from 'lucide-react';
import { Button } from '@/components/ui/button';
import StatusBadge from '@/components/StatusBadge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Dispute, DisputeStatus } from '@/types/dispute';
import { api } from '@/lib/api';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';

const CATEGORY_LABELS: Record<string, string> = {
  flight_delay: 'Flight Delay',
  damaged_parcel: 'Damaged Parcel',
  late_delivery: 'Late Delivery',
  overcharge: 'Overcharge',
  cancellation: 'Cancellation',
};

const ALL_STATUSES: DisputeStatus[] = [
  'SCANNED_MATCH',
  'AWAITING_USER_APPROVAL',
  'WAITING_VENDOR_RESPONSE',
  'RESOLVED_SUCCESS',
  'RESOLVED_REJECTED',
  'DISCARDED_BY_USER',
  'FAILED',
];

const STATUS_LABELS: Record<DisputeStatus, string> = {
  SCANNED_MATCH: 'Scanned',
  AWAITING_USER_APPROVAL: 'Needs Approval',
  WAITING_VENDOR_RESPONSE: 'Pending Vendor',
  RESOLVED_SUCCESS: 'Resolved',
  RESOLVED_REJECTED: 'Rejected',
  DISCARDED_BY_USER: 'Discarded',
  FAILED: 'Failed',
};

const formatCurrency = (val: number | null | undefined) => {
  if (val == null) return '—';
  return `€${val.toFixed(2)}`;
};

const formatDate = (dateStr: string) => {
  try {
    return new Date(dateStr).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
  } catch {
    return dateStr;
  }
};

const Dashboard = () => {
  const [disputes, setDisputes] = useState<Dispute[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeFilters, setActiveFilters] = useState<Set<DisputeStatus>>(new Set());
  const [tab, setTab] = useState('all');
  const navigate = useNavigate();

  const fetchDisputes = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getDisputes();
      setDisputes(data);
    } catch {
      setError('Failed to load disputes.');
      toast.error('Could not fetch disputes.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDisputes();
  }, [fetchDisputes]);

  // Compute summaries
  const resolvedDisputes = disputes.filter(d => d.status === 'RESOLVED_SUCCESS');
  const totalRecovered = resolvedDisputes.reduce((sum, d) => sum + (d.recovered_amount ?? d.estimated_value ?? 0), 0);
  const totalFees = resolvedDisputes.reduce((sum, d) => sum + (d.fee_amount ?? 0), 0);
  const activeCount = disputes.filter(d =>
    ['SCANNED_MATCH', 'AWAITING_USER_APPROVAL', 'WAITING_VENDOR_RESPONSE'].includes(d.status)
  ).length;

  const toggleFilter = (status: DisputeStatus) => {
    setActiveFilters(prev => {
      const next = new Set(prev);
      if (next.has(status)) next.delete(status);
      else next.add(status);
      return next;
    });
  };

  // Apply tab + chip filters
  const tabFiltered = tab === 'resolved'
    ? disputes.filter(d => d.status === 'RESOLVED_SUCCESS')
    : disputes;

  const filteredDisputes = activeFilters.size > 0
    ? tabFiltered.filter(d => activeFilters.has(d.status as DisputeStatus))
    : tabFiltered;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-foreground">Disputes</h1>
        <p className="text-sm text-muted-foreground">Your autonomous claims, tracked end-to-end.</p>
      </div>

      {/* Summary Cards */}
      <div className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-success/10">
              <DollarSign className="h-5 w-5 text-success" />
            </div>
            <div>
              <p className="text-xs font-medium text-muted-foreground">Total Recovered</p>
              <p className="text-2xl font-bold text-foreground">{formatCurrency(totalRecovered)}</p>
            </div>
          </div>
        </div>
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
              <Receipt className="h-5 w-5 text-primary" />
            </div>
            <div>
              <p className="text-xs font-medium text-muted-foreground">Total Fees</p>
              <p className="text-2xl font-bold text-foreground">{formatCurrency(totalFees)}</p>
            </div>
          </div>
        </div>
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
              <Shield className="h-5 w-5 text-primary" />
            </div>
            <div>
              <p className="text-xs font-medium text-muted-foreground">Active Disputes</p>
              <p className="text-2xl font-bold text-foreground">{activeCount}</p>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="all">All Cases</TabsTrigger>
          <TabsTrigger value="resolved">Resolved</TabsTrigger>
        </TabsList>
      </Tabs>

      {/* Filter Chips (hidden on resolved tab) */}
      {tab === 'all' && (
        <div className="flex flex-wrap gap-2">
          {ALL_STATUSES.map(status => (
            <button
              key={status}
              onClick={() => toggleFilter(status)}
              className={cn(
                'rounded-full border px-3 py-1 text-xs font-medium transition-colors',
                activeFilters.has(status)
                  ? 'border-primary bg-primary text-primary-foreground'
                  : 'border-border bg-card text-muted-foreground hover:border-primary/40 hover:text-foreground'
              )}
            >
              {STATUS_LABELS[status]}
            </button>
          ))}
          {activeFilters.size > 0 && (
            <button
              onClick={() => setActiveFilters(new Set())}
              className="rounded-full border border-border px-3 py-1 text-xs font-medium text-muted-foreground hover:text-foreground"
            >
              Clear
            </button>
          )}
        </div>
      )}

      {/* Loading / Error / Table */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : error ? (
        <div className="flex flex-col items-center justify-center gap-3 py-20">
          <AlertCircle className="h-8 w-8 text-destructive" />
          <p className="text-sm text-muted-foreground">{error}</p>
          <Button variant="outline" size="sm" onClick={fetchDisputes}>Retry</Button>
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Vendor</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Recovered</TableHead>
                <TableHead className="text-right">Fee</TableHead>
                <TableHead>Payment</TableHead>
                <TableHead>Updated</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredDisputes.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                    No disputes found.
                  </TableCell>
                </TableRow>
              ) : (
                filteredDisputes.map(dispute => (
                  <TableRow
                    key={dispute.id}
                    onClick={() => navigate(`/dispute/${dispute.dispute_id ?? dispute.id}`)}
                    className="cursor-pointer"
                  >
                    <TableCell className="font-medium text-foreground">{dispute.vendor_name ?? 'Unknown'}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{CATEGORY_LABELS[dispute.category] ?? dispute.category ?? '—'}</TableCell>
                    <TableCell><StatusBadge status={(dispute.status ?? 'SCANNED_MATCH') as DisputeStatus} /></TableCell>
                    <TableCell className="text-right font-mono font-semibold text-foreground">
                      {formatCurrency(dispute.recovered_amount ?? dispute.estimated_value)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-muted-foreground">
                      {formatCurrency(dispute.fee_amount)}
                    </TableCell>
                    <TableCell>
                      {dispute.stripe_checkout_url ? (
                        <Button
                          variant="outline"
                          size="sm"
                          className="gap-1.5 text-xs"
                          onClick={(e) => {
                            e.stopPropagation();
                            window.open(dispute.stripe_checkout_url!, '_blank');
                          }}
                        >
                          <ExternalLink className="h-3 w-3" />
                          Pay Invoice
                        </Button>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{formatDate(dispute.updated_at ?? dispute.created_at)}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
};

export default Dashboard;
