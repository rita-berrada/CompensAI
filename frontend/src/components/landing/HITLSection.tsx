import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Mail, Scale, CheckCircle2, Bot, Clock, Send, FileText, CreditCard } from 'lucide-react';
import { Button } from '@/components/ui/button';

type DemoPhase = 'idle' | 'filing' | 'waiting' | 'vendor-reply' | 'complete';

const pipelineSteps = [
  { icon: Mail, label: 'Signal Detected', desc: 'Agent captures a dispute signal from your inbox' },
  { icon: Scale, label: 'Claim Drafted', desc: 'Legal claim auto-generated against regulations' },
  { icon: CheckCircle2, label: 'You Approve', desc: 'System pauses — you review and decide', highlight: true },
  { icon: Bot, label: 'Claim Filed', desc: 'Agent resumes and submits to the vendor' },
];

const HITLSection = () => {
  const [phase, setPhase] = useState<DemoPhase>('idle');
  const [countdown, setCountdown] = useState(5);

  const handleApprove = useCallback(() => {
    if (phase !== 'idle') return;
    setPhase('filing');
    setTimeout(() => {
      setPhase('waiting');
      setCountdown(5);
    }, 1200);
  }, [phase]);

  // Countdown timer during waiting phase
  useEffect(() => {
    if (phase !== 'waiting') return;
    if (countdown <= 0) {
      setPhase('vendor-reply');
      setTimeout(() => setPhase('complete'), 3000);
      return;
    }
    const t = setTimeout(() => setCountdown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [phase, countdown]);

  // Auto-reset after complete
  useEffect(() => {
    if (phase !== 'complete') return;
    const t = setTimeout(() => {
      setPhase('idle');
      setCountdown(5);
    }, 6000);
    return () => clearTimeout(t);
  }, [phase]);

  // Steps 1-2 always completed (orange). Step 3 = current in idle, completed after approve. Step 4 = active after filing.
  const completedStep =
    phase === 'idle' ? 2 :
    phase === 'filing' ? 3 :
    phase === 'waiting' ? 3 :
    phase === 'vendor-reply' ? 3 :
    4;

  const currentStep =
    phase === 'idle' ? 3 :
    phase === 'filing' ? 3 :
    phase === 'waiting' ? 4 :
    phase === 'vendor-reply' ? 4 :
    0;

  return (
    <section className="py-24 lg:py-32 overflow-hidden">
      <div className="mx-auto max-w-5xl px-6">
        <div className="text-center">
          <motion.h2
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.5 }}
            className="text-3xl font-bold tracking-tight text-foreground sm:text-4xl"
          >
            You Stay in Control
          </motion.h2>
          <motion.p
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.5, delay: 0.1 }}
            className="mx-auto mt-4 max-w-xl text-base text-muted-foreground"
          >
            We enforce a strict Human-in-the-Loop architecture. No claim fires without your explicit approval.
          </motion.p>
        </div>

        {/* Horizontal pipeline */}
        <div className="relative mt-16">
          {/* Grey base line spanning between icon centers */}
          <div className="absolute left-[12.5%] right-[12.5%] top-7 hidden h-[2px] bg-border sm:block" />
          {/* Orange overlay tracking completed steps */}
          <div className="absolute left-[12.5%] right-[12.5%] top-7 hidden h-[2px] sm:block overflow-hidden">
            <motion.div
              className="h-full rounded-full bg-primary"
              animate={{ width: `${((completedStep - 1) / 3) * 100}%` }}
              transition={{ duration: 0.8, ease: 'easeOut' }}
            />
          </div>

          <div className="grid grid-cols-1 gap-8 sm:grid-cols-4">
            {pipelineSteps.map((step, i) => {
              const Icon = step.icon;
              const stepNum = i + 1;
              const isCompleted = stepNum <= completedStep;
              const isCurrent = stepNum === currentStep;
              // Completed = solid orange bg. Current = glow + border but transparent bg (white icon).
              const solidOrange = {
                backgroundColor: 'hsl(20, 90%, 48%)',
                borderColor: 'hsl(20, 90%, 48%)',
                boxShadow: 'none',
              };
              const glowHighlight = {
                borderColor: 'hsl(20, 90%, 48%)',
                boxShadow: '0 0 24px hsl(20, 90%, 48%), 0 0 48px hsl(20, 90%, 48%)',
                backgroundColor: 'hsl(0, 0%, 100%)',
              };
              const inactive = {
                borderColor: 'hsl(0, 0%, 85%)',
                boxShadow: 'none',
                backgroundColor: 'hsl(0, 0%, 100%)',
              };

              const animateTarget = isCompleted
                ? solidOrange
                : isCurrent
                ? glowHighlight
                : inactive;

              return (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 30 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true, margin: '-50px' }}
                  transition={{ duration: 0.5, delay: i * 0.15 }}
                  className="relative flex flex-col items-center text-center"
                >
                  <motion.div
                    animate={animateTarget}
                    transition={{ duration: 0.5 }}
                    className="relative z-10 flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl border-2 border-border bg-card"
                  >
                    {phase === 'complete' && stepNum === 4 ? (
                      <CheckCircle2 className="h-6 w-6 text-primary-foreground" />
                    ) : (
                      <Icon
                        className={`h-6 w-6 ${isCompleted ? 'text-primary-foreground' : 'text-primary'}`}
                      />
                    )}
                  </motion.div>
                  <p className="mt-4 text-sm font-bold text-foreground">{step.label}</p>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground max-w-[180px]">
                    {step.desc}
                  </p>
                </motion.div>
              );
            })}
          </div>

          {/* Interactive card area */}
          <div className="mx-auto mt-12 max-w-md">
            <AnimatePresence mode="wait">
              {/* IDLE — Approval card */}
              {phase === 'idle' && (
                <motion.div
                  key="approval"
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.95, y: -10 }}
                  transition={{ duration: 0.4 }}
                >
                  <motion.div
                    animate={{
                      boxShadow: [
                        '0 0 0px hsl(20,90%,48%)',
                        '0 0 20px hsl(20,90%,48%)',
                        '0 0 0px hsl(20,90%,48%)',
                      ],
                    }}
                    transition={{ duration: 2.5, repeat: Infinity, ease: 'easeInOut' }}
                    className="rounded-2xl border border-border bg-card p-6 shadow-lg"
                  >
                    <p className="text-xs font-semibold uppercase tracking-widest text-primary">
                      Awaiting Your Decision
                    </p>
                    <p className="mt-2 text-sm text-foreground font-medium">
                      Claim: Flight HA1234 — €400 under EU261
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Drafted claim ready for review. No action will be taken until you decide.
                    </p>
                    <div className="mt-4 flex gap-3">
                      <Button
                        size="sm"
                        onClick={handleApprove}
                        className="flex-1 bg-primary text-primary-foreground hover:bg-primary/90 cursor-pointer"
                      >
                        Approve
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled
                        className="flex-1 opacity-40 cursor-not-allowed"
                      >
                        Reject
                      </Button>
                    </div>
                  </motion.div>
                </motion.div>
              )}

              {/* FILING — Sending animation */}
              {phase === 'filing' && (
                <motion.div
                  key="filing"
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.3 }}
                  className="rounded-2xl border border-border bg-card p-8 shadow-lg text-center"
                >
                  <motion.div
                    animate={{ rotate: 360 }}
                    transition={{ duration: 1.5, repeat: Infinity, ease: 'linear' }}
                    className="mx-auto flex h-12 w-12 items-center justify-center rounded-full border-2 border-primary/30 border-t-primary"
                  >
                    <Send className="h-5 w-5 text-primary" />
                  </motion.div>
                  <p className="mt-4 text-sm font-semibold text-foreground">Filing claim with HackAir...</p>
                  <p className="mt-1 text-xs text-muted-foreground">Agent submitting EU261 compensation request</p>
                </motion.div>
              )}

              {/* WAITING — Countdown */}
              {phase === 'waiting' && (
                <motion.div
                  key="waiting"
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.3 }}
                  className="rounded-2xl border border-border bg-card p-8 shadow-lg text-center"
                >
                  <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[hsl(210,80%,50%)]/10">
                    <Clock className="h-7 w-7 text-[hsl(210,80%,50%)]" />
                  </div>
                  <p className="mt-4 text-sm font-semibold text-foreground">
                    Waiting for vendor response...
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Claim filed. Monitoring HackAir's reply channel.
                  </p>
                  {/* Countdown ring */}
                  <div className="mt-4 flex items-center justify-center gap-2">
                    <div className="relative h-10 w-10">
                      <svg className="h-10 w-10 -rotate-90" viewBox="0 0 40 40">
                        <circle cx="20" cy="20" r="16" fill="none" stroke="hsl(0,0%,90%)" strokeWidth="3" />
                        <motion.circle
                          cx="20" cy="20" r="16" fill="none"
                          stroke="hsl(210,80%,50%)" strokeWidth="3"
                          strokeLinecap="round"
                          strokeDasharray={100.5}
                          animate={{ strokeDashoffset: 100.5 * (1 - countdown / 5) }}
                          transition={{ duration: 0.4 }}
                        />
                      </svg>
                      <span className="absolute inset-0 flex items-center justify-center text-xs font-bold text-foreground">
                        {countdown}
                      </span>
                    </div>
                  </div>
                </motion.div>
              )}

              {/* VENDOR REPLY */}
              {phase === 'vendor-reply' && (
                <motion.div
                  key="vendor-reply"
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.4 }}
                  className="rounded-2xl border border-border bg-card p-6 shadow-lg"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(152,55%,50%)]/10">
                      <Mail className="h-4 w-4 text-[hsl(152,55%,50%)]" />
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-foreground">HackAir Compensation Dept.</p>
                      <p className="text-xs text-muted-foreground">Re: Claim #EU261-HA1234</p>
                    </div>
                  </div>
                  <div className="mt-3 rounded-lg border border-border bg-[hsl(0,0%,97%)] p-3">
                    <p className="text-xs leading-relaxed text-muted-foreground">
                      Dear passenger, we have reviewed your claim regarding flight HA1234 and confirm
                      your eligibility for compensation of <span className="font-semibold text-foreground">€400.00</span> under
                      EU Regulation 261/2004. The amount will be credited within 5-7 business days.
                    </p>
                  </div>
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: '100%' }}
                    transition={{ duration: 2, ease: 'easeOut' }}
                    className="mt-3 h-0.5 rounded-full bg-[hsl(152,55%,50%)]"
                  />
                </motion.div>
              )}

              {/* COMPLETE — Confirmation + Invoice */}
              {phase === 'complete' && (
                <motion.div
                  key="complete"
                  initial={{ opacity: 0, scale: 0.95 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.5 }}
                  className="space-y-4"
                >
                  {/* Confirmation email */}
                  <motion.div
                    initial={{ opacity: 0, y: 15 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.1 }}
                    className="rounded-2xl border border-[hsl(152,55%,50%)]/40 bg-card p-5 shadow-lg"
                  >
                    <div className="flex items-center gap-3">
                      <motion.div
                        initial={{ scale: 0 }}
                        animate={{ scale: 1 }}
                        transition={{ type: 'spring', stiffness: 300, damping: 20 }}
                      >
                        <CheckCircle2 className="h-8 w-8 text-[hsl(152,55%,50%)]" />
                      </motion.div>
                      <div>
                        <p className="text-sm font-bold text-foreground">Capital Recovered!</p>
                        <p className="text-xs text-muted-foreground">Confirmation sent to your inbox</p>
                      </div>
                      <motion.p
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        transition={{ delay: 0.3 }}
                        className="ml-auto text-2xl font-extrabold text-[hsl(152,55%,50%)]"
                      >
                        €400
                      </motion.p>
                    </div>
                  </motion.div>

                  {/* Stripe invoice card */}
                  <motion.div
                    initial={{ opacity: 0, y: 15 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.4 }}
                    className="rounded-2xl border border-border bg-card p-5 shadow-lg"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(250,60%,55%)]/10">
                          <CreditCard className="h-4 w-4 text-[hsl(250,60%,55%)]" />
                        </div>
                        <div>
                          <p className="text-sm font-semibold text-foreground">Invoice Generated</p>
                          <p className="text-xs text-muted-foreground">10% success fee — INV-2026-0042</p>
                        </div>
                      </div>
                      <div className="text-right">
                        <p className="text-lg font-bold text-foreground">€40.00</p>
                        <div className="flex items-center gap-1 mt-0.5">
                          <span className="text-[10px] text-muted-foreground">Powered by</span>
                          <FileText className="h-3 w-3 text-[hsl(250,60%,55%)]" />
                          <span className="text-[10px] font-bold text-[hsl(250,60%,55%)]">stripe</span>
                        </div>
                      </div>
                    </div>
                  </motion.div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Replay hint */}
            <AnimatePresence>
              {phase === 'complete' && (
                <motion.p
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ delay: 1 }}
                  className="mt-4 text-center text-xs text-muted-foreground"
                >
                  Demo will restart automatically...
                </motion.p>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>
    </section>
  );
};

export default HITLSection;
