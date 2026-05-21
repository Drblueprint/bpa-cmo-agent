# SALES Tab — Wave 2 Clarification Questions

**Date:** 2026-05-21
**Audience:** Dr. Gumm + Sales Manager
**Status:** Awaiting answers — required to unblock Wave 2 build

Wave 1 (built today) covers ~80% of the sales manager's wish list. Six metrics
are blocked on definitional gaps. Please answer the questions below and we'll
ship them in Wave 2.

---

## Wave 1 — what's already live in the SALES tab

- **SDR Performance** (per rep): Dials, Pick Ups, Talk Time, Appointments Booked, Booking %, Median Speed to Lead
- **BDS Performance** (per rep): Appointments, Shows, SME Booked, Disqualified, Show %, Booking %, DQ %
- **SME Performance** (per rep): Appointments, Showed, Deals Closed, Disqualified, Show %, Close %, DQ %, Revenue
- **Money cards**: Total Sales (count), Total Revenue, Avg Deal Size, Avg Time-to-Close (days from typeform opt-in)
- **Speed to Lead** (KPI row): median minutes, % under 5 min, % under 60 sec

---

## Wave 2 — questions to unblock

### Q1 — "Contact Made" vs "Pick Up"

Today we treat **Pick Up** = AirCall outbound that was answered AND lasted
≥10 seconds. That filters voicemails reliably.

Your wish list distinguishes **Contact Made** from **Pick Up**. Two options:

- **Option A**: Pick Up = answered ≥10s (current); Contact Made = answered ≥60s
  (i.e., they actually engaged in a conversation, not just a "hello, wrong
  number, click").
- **Option B**: Pick Up = any answered call; Contact Made = answered ≥10s
  (the current threshold becomes the "real conversation" bar).
- **Option C**: They're the same thing — pick one term and drop the other.

**Your call?**

### Q2 — First Close vs Follow-Up Close

In your wish list: **SME FIRST CLOSE** and **SME FU CLOSE** (rates too). To
split these, I need to know how HubSpot tracks "this was the close that
happened on the first strategy call" vs "this was the close that happened on
a later call."

Possible mechanisms (pick one that's actually in your data):

- **A)** A HubSpot **deal property** (e.g., a custom field like
  `close_on_first_call: yes/no`) — if so, what's the field name?
- **B)** **Multiple Strategy meetings** on the same contact → first one is
  "first close attempt", subsequent ones are "follow-ups". Close attribution
  goes to the call held immediately before the won-stage transition.
- **C)** A **deal-stage convention** like Strategy → FU1 → FU2 → Closed-Won,
  where the stage path tells the story.
- **D)** Manually tracked on a spreadsheet and not in HubSpot yet.

**Which one matches reality?**

### Q3 — Follow-Up Booked tracking

**SME FU BOOKED** in your wish list. Two interpretations:

- **A)** A FU meeting is any **second-or-later Strategy meeting** for a
  contact whose first Strategy was held but didn't close on the call.
- **B)** A specific HubSpot meeting type — e.g., "Strategy Follow-Up Call" —
  that's distinct from the initial Strategy.
- **C)** Something else.

**Which one matches reality?** If it's a separate meeting type, what's it
called in HubSpot?

### Q4 — Cash Collection

**TOTAL CASH COLLECTION** in your wish list — distinct from Total Revenue
(contracted dollars). Where does cash actually land?

- **A)** Stripe (Stripe API integration — most accurate)
- **B)** QuickBooks Online (we already have QBO MCP wired)
- **C)** HubSpot deal property like `cash_collected` (manual, but visible)
- **D)** Manually tracked elsewhere

**Where should we pull from?** If it's QBO, we can wire it next.

### Q5 — Follow-Up Touch Points

**AVG number of FU touch points to close** — what counts as a touch point?

- **A)** Calls only (AirCall outbound to a known contact)
- **B)** Calls + Emails (HubSpot email engagement)
- **C)** Calls + Emails + SMS (would need SMS source)
- **D)** Strategy Follow-Up meetings only (cleanest if Q3 = B)

**Which set of activities counts?** And do we count touches AFTER the first
Strategy call, AFTER the 15-min, or AFTER lead creation?

### Q6 — Bottleneck / Drop-off Visualization

Wish list mentions seeing where leads "drop off" in the funnel. Three style
options:

- **A)** A bar chart of conversion rates between stages (Lead → 15-min Booked
  → Held → Strategy Booked → Held → Closed) with the lowest-conversion stage
  highlighted in red.
- **B)** A Sankey diagram (visualizes flow + drop-off) — pretty but harder
  to read on small screens.
- **C)** A "leakage table" — rows are stage transitions, columns show: stage A
  count, stage B count, drop rate, week-over-week change. Most data-dense.

**Which feel right for the sales-floor TV?**

---

## Out of scope for Wave 2

- LTGP / retention metrics (Phase C)
- Per-deal commission / payroll → Blended CAC (waiting on payroll numbers)
- Real-time speed-to-lead alerts (Phase B+)
- Inbound call tracking (Hormozi's framework is outbound; inbound is a
  separate workstream)

---

## Once we have answers

Each answered question unlocks a Wave 2 metric. Wave 2 implementation will
be ~1-2 days of work after the answers are in.
