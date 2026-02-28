import { DisputeEconomics } from '@/types/dispute';
import { TrendingUp, Cpu, DollarSign, Percent } from 'lucide-react';

interface EconomicsWidgetProps {
  economics: DisputeEconomics | null;
}

const EconomicsWidget = ({ economics }: EconomicsWidgetProps) => {
  if (!economics) {
    return (
      <div className="rounded-xl border border-border bg-card p-6">
        <div className="mb-4 flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
            <TrendingUp className="h-4 w-4 text-primary-foreground" />
          </div>
          <h3 className="text-sm font-bold uppercase tracking-wider text-primary">Agent Economics</h3>
        </div>
        <p className="text-xs text-muted-foreground">No billing data available for this dispute.</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border-2 border-primary/20 bg-gradient-to-br from-primary/5 to-primary/10 p-6">
      <div className="mb-4 flex items-center gap-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
          <TrendingUp className="h-4 w-4 text-primary-foreground" />
        </div>
        <h3 className="text-sm font-bold uppercase tracking-wider text-primary">Agent Economics</h3>
      </div>

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Cpu className="h-4 w-4" />
            Compute Cost
          </div>
          <span className="font-mono text-sm font-semibold text-foreground">
            ${economics.compute_cost_usd.toFixed(2)}
          </span>
        </div>

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <DollarSign className="h-4 w-4" />
            Value Recovered
          </div>
          <span className="font-mono text-lg font-bold text-success">
            ${economics.value_generated_usd.toFixed(2)}
          </span>
        </div>

        <div className="h-px bg-border" />

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Percent className="h-4 w-4" />
            Agentic Margin
          </div>
          <span className="font-mono text-sm font-bold text-primary">
            {economics.margin_pct}%
          </span>
        </div>
      </div>
    </div>
  );
};

export default EconomicsWidget;