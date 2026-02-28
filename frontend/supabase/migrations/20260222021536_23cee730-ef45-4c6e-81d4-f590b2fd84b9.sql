
-- Enable RLS on cases and case_events
ALTER TABLE public.cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.case_events ENABLE ROW LEVEL SECURITY;

-- Allow public read access to cases
CREATE POLICY "Allow public read access" ON public.cases FOR SELECT USING (true);

-- Allow public read access to case_events
CREATE POLICY "Allow public read access" ON public.case_events FOR SELECT USING (true);

-- Allow status updates on cases (for approve/reject from the dashboard)
CREATE POLICY "Allow status updates" ON public.cases FOR UPDATE USING (true) WITH CHECK (true);

-- Allow inserting case_events (for logging approval actions)
CREATE POLICY "Allow insert case events" ON public.case_events FOR INSERT WITH CHECK (true);
