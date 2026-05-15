# BPA CMO Dashboard — Design Spec

**Date:** 2026-05-15
**Status:** Draft — awaiting user review
**Owner:** Dr. Gumm (BPA) / Kurt (implementation)

---

## Purpose

A shared web dashboard giving the BPA leadership team a single view of the funnel from **ad spend → marketing lead → 15-min call → Strategy Call → Closed-Won deal**. Replaces ad-hoc terminal reports for non-technical viewers. Lives on a public URL behind a shared password; multiple bosses can open it without logging in.

## Users

- **Dr. Gumm** — primary viewer, reviews weekly performance and constraint of the week.
- **Other BPA leadership** — Scott, Garrett, and any other team members Dr. Gumm shares the link with.
- **Kurt** — maintainer; iterates on layout and metrics over time.

## Success Criteria

1. Dr. Gumm and his team can open one URL and see, for any selected date range, the full marketing-to-sales funnel without running any scripts.
2. Marketing section answers in <5 seconds: spend, leads, CPL, 15-min calls booked, CPQC — broken out by Chiro / PT Recovery / TheraRay (with EMX as a Chiro sub-section).
3. Sales section answers in <5 seconds: 15-min calls scheduled (marketing-attributed and total), SDR ownership, BDS assignment, progression to Strategy Call, progression to Closed-Won — with the ability to filter to marketing leads vs all leads.
4. Data sources reconcile: FB = spend, Hyros = cross-check on lead attribution, HubSpot = source of truth for everything downstream of lead capture.
5. Hosted free on Streamlit Community Cloud, accessible via a shared password.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Streamlit Community Cloud (free hosting)                   │
│  bpa-cmo-<obscure>.streamlit.app                            │
├─────────────────────────────────────────────────────────────┤
│  dashboard/app.py                                           │
│    - shared password gate                                   │
│    - global date range picker (calendar)                    │
│    - tab: MARKETING                                         │
│    - tab: SALES                                             │
├─────────────────────────────────────────────────────────────┤
│  dashboard/data/                                            │
│    fb_loader.py       → wraps existing FB pullers           │
│    hyros_loader.py    → wraps hyros_probe2.py logic         │
│    hubspot_loader.py  → wraps hubspot_puller.py             │
│    reconcile.py       → joins three sources by date+ad+lead │
│    cache.py           → @st.cache_data, 15-min TTL          │
├─────────────────────────────────────────────────────────────┤
│  dashboard/sections/                                        │
│    marketing.py       → renders MARKETING tab               │
│    sales.py           → renders SALES tab                   │
├─────────────────────────────────────────────────────────────┤
│  Secrets (Streamlit secrets manager)                        │
│    FB_ADS_TOKEN, FB_AD_ACCOUNT_ID                           │
│    HYROS_API_KEY                                            │
│    HUBSPOT_TOKEN                                            │
│    DASHBOARD_PASSWORD                                       │
└─────────────────────────────────────────────────────────────┘
```

**Reuse over rewrite:** the existing `hubspot_puller.py`, FB pull logic in `weekly_report_v3.py`, and Hyros logic in `hyros_probe2.py` are imported into the loaders. We do NOT duplicate API code.

**Repo location:** new `dashboard/` subdirectory inside the existing `bpa-cmo-agent` repo. Streamlit Cloud deploys from a GitHub repo, so the existing folder gets pushed to GitHub.

---

## Page Layout

### Global header (always visible)
- Date range picker (calendar): default = last 7 days. Presets: 7d / 14d / 30d / MTD / custom.
- Refresh button (clears cache, re-pulls).
- Last-updated timestamp.

### Tabs
- **MARKETING**
- **SALES**

---

## MARKETING Tab

### Top-row KPIs (4 cards)
1. **Total Ad Spend** (FB, sum of in-scope campaigns in date range)
2. **Total Marketing Leads** (HubSpot contacts with `typeform_asset_download` populated, created in date range)
3. **CPL** = spend / marketing leads
4. **15-min Calls Booked from Marketing** (HubSpot deals/meetings tied to marketing leads)

### Section A — Campaign Group Breakdown
A table + bar chart with one row per group:

| Group | Spend | Leads | CPL | 15-min Calls | Cost per Qualified Call |
|---|---|---|---|---|---|
| Chiro | $ | # | $ | # | $ |
| ↳ EMX (sub-row, callout) | $ | # | $ | # | $ |
| PT Recovery | $ | # | $ | # | $ |
| TheraRay | $ | # | $ | # | $ |
| **Total** | $ | # | $ | # | $ |

**Group identification logic:**
- Match FB campaign names by regex tokens:
  - `__Chiro__` → Chiro group
  - `__PT__` or `__Recovery__` → PT Recovery
  - `__Theraray__` or `__TheraRay__` → TheraRay
  - `__EMX__` (when launched) → EMX, also rolls up into Chiro total
- Unmatched active campaigns are surfaced in a warning panel so we catch new naming patterns.

### Section B — Lead Reconciliation Panel
A small panel showing per-group:
- FB-reported leads (action count)
- Hyros-reported leads (lead attribution count)
- HubSpot-reported leads (typeform_asset_download contacts)
- Match rate % between Hyros and HubSpot

**Rule:** the headline numbers in Section A use **HubSpot counts** (source of truth). Hyros and FB shown for diagnostic comparison only.

### Section C — Trend Chart
A time-series line chart of leads/day and spend/day for the selected window, grouped by campaign group.

---

## SALES Tab

> **"Marketing-attributed"** in this tab = HubSpot contact has `typeform_asset_download` populated. Same definition as the Marketing tab.

### Top-row KPIs (4 cards)
1. **15-min Calls Scheduled — Marketing-Attributed** (in date range)
2. **15-min Calls Scheduled — Total (all sources)** (in date range)
3. **Strategy Calls Held — Marketing-Attributed**
4. **Closed-Won — Marketing-Attributed** (count + revenue)

### Section A — Pipeline Funnel
Vertical funnel visualization with two columns side-by-side:

| Stage | Marketing-Attributed | All Sources |
|---|---|---|
| Marketing Lead | # | n/a |
| 15-min Call Booked | # | # |
| 15-min Call Held | # | # |
| Strategy Call Booked | # | # |
| Strategy Call Held | # | # |
| Closed-Won | # ($ rev) | # ($ rev) |

Conversion rates between adjacent stages shown as small labels.

### Section B — Owner Breakdown
Two tables:

**By SDR Owner** (HubSpot `SDR Owner` field):
- name | 15-min calls owned | Strategy calls progressed | Closed-Won

**By BDS** (HubSpot `BDS` field; Scott Warren, Garrett, others):
- name | 15-min calls scheduled to them | Strategy calls held | Closed-Won

Both tables filterable by "marketing-attributed only" vs "all".

### Section C — Marketing Lead Detail Table
Drill-down table showing each marketing-attributed contact in window:
- Contact name (linked to HubSpot)
- `typeform_asset_download` value (which asset / funnel)
- Created date
- Current deal stage
- SDR Owner
- BDS
- Days in current stage
- Lifetime value (if closed)

Sortable, searchable. This is the "show me every marketing lead and where they are right now" view.

---

## Data Flow

1. User loads dashboard → password gate.
2. User picks date range from calendar.
3. App reads cached data if available (15-min TTL keyed by date range).
4. On cache miss:
   - FB loader pulls insights for in-scope campaigns over the window.
   - HubSpot loader pulls contacts with `typeform_asset_download` populated + their associated deals/meetings/owners.
   - Hyros loader pulls leads + calls attribution for the window.
5. `reconcile.py` joins them and produces a single in-memory dataframe per section.
6. Marketing tab and Sales tab render from the dataframes.
7. "Refresh" button busts the cache for the current window.

---

## Data Source Rules

| Rule | Implementation |
|---|---|
| HubSpot = source of truth for lead counts and pipeline | All headline numbers in KPI cards come from HubSpot |
| FB = source of truth for spend | All spend numbers come from FB Ads |
| Hyros = cross-check for lead attribution | Shown in reconciliation panel only; never the headline |
| "Marketing lead" definition | HubSpot contact with `typeform_asset_download` not null |
| Date attribution | Use HubSpot `createdate` for contacts; FB date range for spend; respect the global picker |

---

## Access Control

- **Streamlit secrets** holds `DASHBOARD_PASSWORD`.
- App entrypoint: if session has no `authenticated=True`, show single password input. On submit, compare to secret. On match, set session flag and render dashboard.
- No accounts, no email — one shared password for the whole team. Dr. Gumm sets it when ready.
- Rotation: change the secret in Streamlit Cloud, restart the app.

---

## Error Handling

- **API failure (FB / Hyros / HubSpot):** show a yellow banner naming the failing source. Render the dashboard with the other sources; show "data unavailable" in affected cells.
- **Empty result for a campaign group:** show "no campaigns matched" for that row, not a crash.
- **Unmatched campaigns:** surface a warning panel listing campaign names that didn't match any group regex, so we know to update the matchers.
- **Auth failure:** keep showing the password screen with "incorrect password" — never expose data.

---

## Testing

We are not building a full test suite. We are building three lightweight checks that protect the things most likely to silently break:

1. **Loader smoke tests** — for each of FB / Hyros / HubSpot, a 10-line script that pulls one day of data and asserts it returns a non-empty dataframe. Run manually before each deploy.
2. **Group-matcher unit test** — table-driven test: given a list of fake campaign names, assert each maps to the right group (or "unmatched"). Catches regex regressions when EMX or other groups are added.
3. **Manual UAT checklist** — for each tab, verify against the existing weekly_report_v3.py output for a known date range. Numbers should reconcile to within 1-2 leads (small drift from API timing is acceptable).

---

## Out of Scope (explicit non-goals for v1)

- Real-time push updates (15-min cache is fine for v1).
- Writing back to HubSpot or FB (read-only dashboard).
- Mobile-optimized layout (works on desktop; mobile is best-effort).
- Multi-tenant or per-user views (one shared view for the team).
- True authentication / SSO (password gate is intentionally lightweight).
- Coaching call analyst integration (separate roadmap item).
- Hyros sale-event wiring (already a known gap in the project; tracked separately).
- Notifications, alerts, or Slack/Gchat pushes (existing scripts already do this; not the dashboard's job).

---

## Open Items to Resolve During Build

These don't block the spec but need to be confirmed by reading HubSpot API responses during implementation:

1. **Exact HubSpot property internal names** for: `SDR Owner`, `BDS`, `typeform_asset_download`. The visible UI labels need to be mapped to API names (likely `sdr_owner`, `bds`, `typeform_asset_download` — confirm via probe).
2. **HubSpot deal stage internal IDs** for: 15-min booked, 15-min held, Strategy booked, Strategy held, Closed-Won. The existing `hubspot_puller.py` may already have a stage mapping — reuse or extend.
3. **EMX campaign naming** — Dr. Gumm hasn't launched them yet. We add the matcher (`__EMX__`) and surface unmatched names in the warning panel so the first launch is caught.
4. **Closed-Won revenue field** — use `amount` from the deal, or a custom contract-tier field?

These get answered with a one-time HubSpot probe during the implementation plan's first phase.

---

## Implementation Team (BPA Agents)

| Agent | Role |
|---|---|
| **bpa-paid-media-analyst** | FB + Hyros data layer: spend pulls, lead attribution, campaign group matching, reconciliation logic |
| **bpa-attribution-auditor** | Source-of-truth reconciliation between HubSpot / Hyros / FB; defines and verifies the cross-check rules |
| **bpa-funnel-developer** | Sales tab: pipeline stage progression, SDR/BDS rollups, marketing-vs-total filter, drill-down table |

Each agent is brought in as a research/review consultant during the corresponding implementation phase, not as the executor.

---

## Decision Log

| Decision | Choice | Reason |
|---|---|---|
| Framework | Streamlit | Fastest iteration on existing Python data layer; native date picker, filters, charts |
| Hosting | Streamlit Community Cloud | Free, public URL, no card needed, secrets manager included |
| Auth | Shared password in code, value in secrets | Bosses don't want to log in; password gate is enough for this data sensitivity |
| Source of truth | HubSpot for funnel, FB for spend, Hyros for cross-check | Matches Dr. Gumm's stated rule |
| Marketing lead definition | `typeform_asset_download` populated | Dr. Gumm's stated definition |
| Campaign grouping | Regex on `__Chiro__` / `__PT__` / `__Theraray__` / `__EMX__` tokens | Matches existing FB naming convention |
| EMX placement | Sub-row inside Chiro group, also isolatable | Dr. Gumm's stated structure |
| Caching | 15-min TTL via `@st.cache_data` | Balances freshness with API rate limits |
| Repo strategy | New `dashboard/` subdir inside `bpa-cmo-agent` repo | Reuses existing pullers, single source of truth |
