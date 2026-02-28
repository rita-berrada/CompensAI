

# Expanding the Landing Page with HITL Workflow and Tech Stack Sections

## Overview

Add two new animated sections to the landing page between the existing Stats and Pricing sections, covering the Human-in-the-Loop workflow (Slide 3) and the Infrastructure Stack (Slide 4). Both will use the same design language -- motion animations, clean cards, and the orange primary accent.

---

## Section 1: "You Stay in Control" (HITL Workflow)

**Position**: After StatsSection, before Pricing.

**Design**: A horizontal animated flowchart showing 4 steps in a pipeline, with a mock dashboard card in the center illustrating the approval moment.

**Content**:
- Headline: "You Stay in Control"
- Subtitle: "We enforce a strict Human-in-the-Loop architecture. No claim fires without your explicit approval."
- 4-step animated horizontal pipeline:
  1. "Signal Detected" (Mail icon) -- agent finds a dispute signal
  2. "Claim Drafted" (Scale icon) -- legal claim is auto-generated
  3. "You Approve" (CheckCircle2 icon) -- system pauses, user reviews and clicks Approve/Reject
  4. "Claim Filed" (Bot icon) -- agent resumes and submits
- Between steps 2 and 4, a mock UI card appears showing a mini "Approve / Reject" button pair, visually emphasizing the human checkpoint
- Each node animates in sequentially on scroll using `whileInView`

---

## Section 2: "Built to Execute" (Infrastructure Stack)

**Position**: After HITL section, before Pricing.

**Design**: A grid of 5 tech cards, each with an icon, title, and one-liner. Cards animate in with stagger.

**Content**:
- Headline: "Built to Execute"
- Subtitle: "A fully event-driven infrastructure designed for autonomous persistence."
- Cards (2x3 grid, last row centered):
  1. **Orchestration** (Zap icon) -- "Event-driven workflows handle email ingestion and agent pausing via n8n"
  2. **AI Agents** (Bot icon) -- "Multi-agent Python backend routes triage, legal drafting, and financial closing"
  3. **Real-Time State** (Database icon) -- "Supabase powers the database, auth, and instant UI updates"
  4. **Dynamic Execution** (Globe icon) -- "Agents parse and interact with vendor web forms autonomously"
  5. **Monetization** (CreditCard icon) -- "Programmatic invoicing via Stripe -- you only pay on success"

---

## Technical Details

**File changed**: `src/pages/Landing.tsx`

**New imports**: Add `Users`, `Database`, `Globe`, `CreditCard` from `lucide-react`.

**New components**:
- `HITLSection` -- renders the horizontal pipeline with 4 animated nodes connected by a line, plus a mock approval card widget in the center
- `TechStackSection` -- renders a responsive grid of 5 animated cards

**Page order after changes**:
1. Hero (existing)
2. How It Works (existing SolutionSection)
3. Stats (existing StatsSection)
4. **You Stay in Control** (new HITLSection)
5. **Built to Execute** (new TechStackSection)
6. Pricing (existing)
7. Footer (existing)

**Animation approach**:
- HITL pipeline nodes use `whileInView` with staggered delays (0, 0.15, 0.3, 0.45)
- Connecting line between nodes animates width from 0% to 100%
- The mock approval card pulses subtly to draw attention
- Tech stack cards use `whileInView` with stagger, slight y-offset entrance

**No new files** -- everything stays in Landing.tsx following the existing pattern of inline section components.

