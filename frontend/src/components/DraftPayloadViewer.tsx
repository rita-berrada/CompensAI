import { Code2 } from 'lucide-react';

interface DraftPayloadViewerProps {
  payload?: Record<string, unknown>;
}

const DraftPayloadViewer = ({ payload }: DraftPayloadViewerProps) => {
  if (!payload) return null;

  return (
    <div className="rounded-xl border border-border bg-card p-5 space-y-3">
      <div className="flex items-center gap-2">
        <Code2 className="h-4 w-4 text-muted-foreground" />
        <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Draft Payload</h3>
      </div>
      <pre className="overflow-x-auto rounded-lg bg-muted p-4 font-mono text-xs leading-relaxed text-foreground">
        {JSON.stringify(payload, null, 2)}
      </pre>
    </div>
  );
};

export default DraftPayloadViewer;