# Callum Sales-Reporting Review & Implementation Plan

Date: 2026-06-16
Source: Kurt ↔ Callum (Head of Sales) call, Fathom transcript
Status: For discussion — decisions pending before implementation

## Theme
Callum wants the dashboard to (a) report accurate data everywhere, and
(b) expose per-rep accountability across the full funnel — appointments →
outcomes → sales — so he can find bottlenecks per person and per stage.

---

## A. Dashboard changes Callum asked for

### A1. Rename "Discovery Held" → "Discovery Show", "Held %" → "Show %"
- BDS sections (Sales + Executive). Pure wording; Kurt already agreed on call.
- Effort: trivial.

### A2. SME Performance: drop First Close / FU Close → show **Total Sales + Total Revenue**
- "No one's doing first-call closes right now... just total sales and total
  revenue." Remove the first/FU split; show a Sales (count) column + Revenue.
- Effort: small.

### A3. Fix SME Performance showing "no sales this month" (inaccurate)
- Closed deals exist (visible on Executive) but the SME table shows 0.
- Root cause to fix: SME closed-deal attribution / window. Closes in the
  window must attribute to the SME on the deal's contact.
- Effort: small-medium. Ties to A7 (revenue accuracy).

### A4. Per-rep SALES INFLUENCED (Callum's headline ask)
- "How many sales did Payton help close? How many did Scott?" Tie a rep all
  the way back to the close, not just bookings — shows appointment *quality*,
  and enables cost-per-sale ("$400 to make a sale → 5 sales = $2,000").
- Proposed: count closed-won deals (in window, by closedate) whose contact's
  `sdr_owner` = the rep. Add as a column on SDR Performance (+ optional
  cost-per-sale = ad/commission ÷ sales). Same idea extensible to BDS.
- Effort: medium. Decision D2 (attribution definition).

### A5. Appointment-outcome funnel: Appointments → No-Show → Cancelled → Showed → Sales (+ %s)
- For SME (strategy) calls especially, and discovery. Per team AND per rep.
- **Feasible — confirmed via HubSpot probe.** `hs_meeting_outcome` values in
  use:
  - Held: COMPLETE - QUALIFIED / FUTURE / DISQUALIFIED / SEND CONTRACT, COMPLETED
  - No-show: `NO_SHOW`
  - Cancelled: `CANCELLED - BY BPA`, `CANCELLED - BY PROSPECT` (= by user),
    `CANCELED` (generic/legacy)
  - Rescheduled: `RESCHEDULED`, `RESCHEDULED - HAS BOFU`, `RESCHEDULED - NO BOFU`
  - Strategy calls populate the BY BPA / BY PROSPECT split well (71 / 18 YTD).
    Discovery calls mostly use generic `CANCELED` (221 YTD) — the by-whom split
    is sparse there (only 5 BY BPA), so discovery shows a single "Cancelled".
- Proposed columns (SME): Strategy Scheduled · No-Show · Cancelled (BPA) ·
  Cancelled (Prospect) · Rescheduled · Showed · Sales · Show% · No-Show% ·
  Cancel% — team total + per SME. Mirror the existing BDS Discovery funnel
  pattern (Scheduled/Canceled/Rescheduled/Held) and add No-Show + cancel split.
- Effort: medium.

### A6. Per-rep rates: show %, no-show %, cancel %, reschedule %
- Falls out of A5. Diagnose bottlenecks (e.g. Scott high no-show → pre-call
  process or SDR tie-down). Per SME + per SDR/BDS.

### A7. Revenue accuracy (recurring)
- DIY / 90-Day / primary deal values must be right. The tier money engine was
  built then reverted (over-engineering); current source of truth is HubSpot
  `deal.amount`, which the sales team must keep accurate. ~30-40 deals/month —
  retro-fixable. Decision D1.

---

## B. Already shipped this session (reconciles Callum's older notes)
- "No SDR Owner Assigned" leads → own dropdown. ✓
- NLAP added across Executive + Cost-per-Stage + groups. ✓
- Canceled/Rescheduled surfaced on the BDS Discovery funnel (Scheduled →
  Canceled → Rescheduled → Held). ✓ (A5 extends this with No-Show + cancel
  split, and mirrors it onto SME.)
- Protocol Mapping Calls counted as discovery for NLAP/TheraRay. ✓
- FOUNDATIONAL-C treated as a lead, not a customer. ✓
- Default window = This Month (MTD). ✓
- Self-booked + scheduled now shows the scheduled status (discovery_mask). ✓

## C. Out of scope here (not dashboard code — flag to Kurt/Dr. Gunn)
- Webinar / PAT policy (shorten / make optional) — Dr. Gunn discussion.
- SDR qualification gate before SME calls + commission policy.
- Clippers video, XPA landing pages, Zaps/workflows.

## D. Phase 2 (later)
- Color-coded (green/yellow/red) funnel constraint map of the sales process.

---

## Proposed sequencing
1. **Quick wins** (A1 rename, A2 total sales/revenue, A4 SDR-influenced sales)
   + A3 SME-sales-attribution fix. One plan.
2. **Appointment-outcome funnel** (A5 + A6) — SME first, then discovery. One plan.
3. Revenue model resolution (A7) — depends on D1; mostly a process/data call.
4. Phase 2 constraint map — separate.

## Decisions (LOCKED 2026-06-16)
- **D1 → deal.amount only.** HubSpot `deal.amount` is the single revenue
  source; sales team maintains it. Total Sales (count) is reliable now; Total
  Revenue = sum(deal.amount), accurate as amounts get filled. No tier engine.
- **D2 → sdr_owner attribution, shown for BOTH SDR and BDS.** "Sales
  influenced" = closed-won deals (closedate in window) whose contact's
  sdr_owner / bds = the rep. SME = the closer (direct).
- **D3 → SME (strategy) outcome funnel first, then discovery.**

## Original open decisions (now resolved above)
- **D1 — Revenue model:** keep `deal.amount` as the only source (sales team
  maintains it; Total Sales count is reliable now, Total Revenue accurate once
  amounts entered), OR add a light tier→value *fallback* used only when amount
  is blank (DIY/90-Day/Primary defaults)?
- **D2 — "Sales influenced" attribution:** define as closed-won deals whose
  contact's `sdr_owner` = the rep (lead's SDR)? Also want the same influence
  column for BDS? (SME = the closer, already direct.)
- **D3 — Outcome funnel scope:** SME (strategy) only first, or SME + discovery
  together? And show the cancel split (By BPA / By Prospect) where populated
  (strategy) with a single "Cancelled" for discovery?
