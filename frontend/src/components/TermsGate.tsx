import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Shield, ScrollText } from 'lucide-react';

const TERMS_KEY = 'bureaucracy_hacker_terms_accepted';

interface TermsGateProps {
  children: React.ReactNode;
}

const TermsGate = ({ children }: TermsGateProps) => {
  const [accepted, setAccepted] = useState<boolean | null>(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    setAccepted(localStorage.getItem(TERMS_KEY) === 'true');
  }, []);

  const handleAccept = () => {
    localStorage.setItem(TERMS_KEY, 'true');
    setAccepted(true);
  };

  if (accepted === null) return null;
  if (accepted) return <>{children}</>;

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="w-full max-w-lg rounded-xl border border-border bg-card p-8 shadow-lg">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
            <Shield className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-foreground">CompensAI</h1>
            <p className="text-sm text-muted-foreground">Terms &amp; Conditions</p>
          </div>
        </div>

        <div className="mb-6 max-h-64 overflow-y-auto rounded-lg border border-border bg-muted/50 p-4">
          <div className="flex items-center gap-2 mb-3">
            <ScrollText className="h-4 w-4 text-muted-foreground" />
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Agreement</span>
          </div>
          <div className="space-y-3 text-sm text-muted-foreground leading-relaxed">
            <p>
               <strong className="text-foreground">1. Service Description.</strong> CompensAI
              is an automated claims assistant that scans your inbox for actionable disputes
              (e.g., flight delays, overcharges, damaged parcels) and drafts claim letters on
              your behalf. All claims require your explicit approval before submission.
              CompensAI provides automated assistance and does not offer legal representation
              or formal legal advice.
            </p>
            <p>
              <strong className="text-foreground">2. User Responsibility.</strong> You are solely
              responsible for reviewing and approving all generated claim drafts. The service
              does not guarantee successful claim outcomes. You confirm that any information
              provided is accurate and truthful.
            </p>
            <p>
              <strong className="text-foreground">3. Data Handling.</strong> We process email
              metadata and relevant correspondence solely for dispute detection and claim
              generation. We do not sell or share your data with third parties beyond the
              vendors involved in your disputes.
            </p>
            <p>
              <strong className="text-foreground">4. Data Protection &amp; Privacy.</strong> CompensAI
              processes email metadata and relevant correspondence solely for dispute detection
              and claim generation purposes. We operate in compliance with applicable data
              protection laws, including the General Data Protection Regulation (GDPR). We do
              not sell user data. Data is shared only with entities directly involved in the
              dispute resolution process. Users may request data deletion at any time.
            </p>
            <p>
              <strong className="text-foreground">5. Fees.</strong> A service fee of up to 10% of
              successfully recovered amounts may apply. No fee is charged for unsuccessful
              claims. Fee details are shown on each dispute before approval.
            </p>
            <p>
              <strong className="text-foreground">6. Limitation of Liability.</strong> This service
              is provided "as is" without warranty. We are not liable for missed claims,
              incorrect drafts, or any direct or indirect damages arising from use of the
              platform.
            </p>
            <p>
              <strong className="text-foreground">7. Termination.</strong> You may stop using the
              service at any time. We reserve the right to suspend accounts that violate
              these terms or engage in fraudulent activity.
            </p>
          </div>
        </div>

        <div className="mb-6 flex items-start gap-3">
          <Checkbox
            id="terms"
            checked={checked}
            onCheckedChange={(v) => setChecked(v === true)}
            className="mt-0.5"
          />
          <label htmlFor="terms" className="cursor-pointer text-sm text-foreground leading-relaxed">
            I have read and agree to the Terms &amp; Conditions and acknowledge the service
            fee structure.
          </label>
        </div>

        <Button onClick={handleAccept} disabled={!checked} className="w-full" size="lg">
          Accept &amp; Continue
        </Button>
      </div>
    </div>
  );
};

export default TermsGate;
