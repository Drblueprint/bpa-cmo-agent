# Paid Media Report: FB Ads x Hyros Reconciliation and Cut List

**Date:** 2026-08-05
**Requested by:** Kurt
**Status:** Approved (2026-08-05), thresholds revisable after first run

## Problem

Facebook Ads Manager is over-reporting leads. For Jul 21 - Aug 3, the Hyros
extension columns injected into Ads Manager show 73 leads at $203.38 cost per
lead, while FB's own Results column sums to roughly 108 website leads across the
same campaigns. That is about 48% over-report. Decisions about what to cut are
currently being made on the inflated number.

Separately, Hyros TOTAL REVENUE reads $0.00 on every row in both the 14-day and
7-day views. Hyros is receiving no purchase or deal events at all, so no ROAS is
computable today. This is a distinct defect from the lead double-count.

## Goal

A report delivered in chat that:

1. Cross-references FB Ads Manager against Hyros (and HubSpot as a third source)
   at campaign, ad set, and ad level.
2. Covers three windows (14 / 7 / 3 day) so degradation is separable from
   chronic underperformance.
3. Produces a tiered cut list for currently-active campaigns.
4. Recommends copy and creative variations grounded in what is already winning.
5. Diagnoses the double-reporting cause per funnel, with the fix.

Explicitly out of scope: any dashboard tab. Kurt asked for chat delivery "not
into the dashboard for anything just yet." The probes are written so a tab is a
cheap follow-up if he wants one later.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Delivery | Report in chat | Kurt's explicit call |
| Granularity | Campaign + ad set + ad | Needed to name specific ads to cut |
| Primary decision metric | Cost per booked call | A lead that never books is worth nothing |
| Cut scope | Active campaigns only | Recommendations must be actionable |
| Benchmark scope | All in-window spend incl. paused | $6,890 of the 14-day spend is in now-off campaigns; excluding 46% of spend would skew what "good" means |
| Tracking audit depth | Triangulate 3 sources, then inspect live funnels | Finding the cause, not just its size |
| Data layer | Reusable probes in `dashboard/probes/` | Re-runnable; matches existing repo convention |

## Windows

Anchored to complete days ending yesterday, matching FB's own convention.

| Window | Range |
|---|---|
| 14-day | 2026-07-22 to 2026-08-04 |
| 7-day | 2026-07-29 to 2026-08-04 |
| 3-day | 2026-08-02 to 2026-08-04 |
| Checksum only | 2026-07-21 to 2026-08-03 (matches Kurt's 14-day screenshot) |

## Data sources

### Facebook Marketing API

Credentials: `FB_ADS_TOKEN`, `FB_AD_ACCOUNT_ID` (already in
`.streamlit/secrets.toml`). Nine pulls: 3 windows x 3 levels
(`campaign`, `adset`, `ad`).

Fields beyond what `fb_loader.py` currently requests:

- Delivery: `reach`, `frequency`, `impressions`, `effective_status`
- Click: `clicks`, `inline_link_clicks`, `unique_clicks`, `ctr`,
  `inline_link_click_ctr`, `cpc`, `cost_per_inline_link_click`, `cpm`
- Conversion: `actions`, `action_values`, `cost_per_action_type`
- Video (hook and hold rate): `video_play_actions`,
  `video_p25/50/75/100_watched_actions`, `video_thruplay_watched_actions`
- Diagnostics: `quality_ranking`, `engagement_rate_ranking`,
  `conversion_rate_ranking`
- Creative: destination `link_url` (for the funnel audit)

Derived metrics: link CPC, link CTR, hook rate (3s plays / impressions), hold
rate (thruplay / 3s plays), CPL, cost per landing page view, LP view to lead
rate.

**Objective normalization.** Campaigns do not share an optimization event.
`KK_Chiro_Traffic_Testimonials` optimizes to Landing Page Views ($0.53 each,
146 in 7 days); the DS campaigns optimize to Website Leads. CPL is not
comparable across those. Ads are bucketed by optimization event before any
ranking or cut decision.

### Hyros API

Credentials: `HYROS_API_KEY`. `/leads` per window, retaining the full
`firstSource` / `lastSource` objects rather than collapsing them to a campaign
label the way `hyros_loader.py` does today, so attribution can reach ad level.

Open question to resolve by probe: whether the public API exposes the CALLS and
COST PER CALL figures the Chrome extension injects into Ads Manager. If it does
not, booked calls are derived instead as: Hyros lead email -> HubSpot contact ->
did that contact book a 15-min or strategy meeting. That fallback uses HubSpot
meeting records as truth rather than Hyros' own counter, which is arguably the
better source regardless.

### HubSpot

Credentials: `HUBSPOT_TOKEN`. Per window: form submissions, contacts created
(with marketing group and `recent_conversion_event_name`), and meetings booked.
Supplies the third independent lead count and the authoritative booked-call
count.

## Reconciliation logic

Per campaign, and per ad set / ad wherever Hyros attribution reaches:

```
FB pixel leads | Hyros leads | HubSpot submissions | variance %
```

Interpretation rules:

- FB exceeds Hyros by more than 20% -> suspected double count on the FB side
- Hyros exceeds HubSpot -> attribution recorded with no form submission behind it
- HubSpot exceeds Hyros -> untracked traffic; Hyros script missing or blocked

Known benign source of small gaps: FB reports in the ad account timezone; Hyros
and HubSpot may not. Single-day edge drift is expected and is not evidence of a
defect. The report states this so small variances are not over-read.

## Cut list rules

Primary metric: cost per booked call. Blended baseline from Kurt's own 14-day
data is **$235.66**.

**Judgeability floor.** An ad must have at least 1,000 impressions and $100
spend in the 14-day window to be judged. Below that it is reported as
"insufficient data, let it run." This prevents killing creative on noise.

Secondary baseline for the zero-call case: blended CPL is **$203.38**, so 2x CPL
is $406.76.

| Tier | Rule |
|---|---|
| CUT NOW | Spent $250+ in 14d AND zero booked calls AND (CPL at or above $406.76, or zero leads) |
| CUT / REALLOCATE | Cost per booked call at or above $353.49 (1.5x blended) with at least 2 booked calls of history |
| WATCH | Cost per booked call between $235.66 and $353.49, or 7d and 3d trending worse than 14d |
| SCALE | Cost per booked call at or below $235.66, holding or improving in 7d and 3d |

Every threshold above is expressed against the 14-day blended baseline and gets
recomputed from the live pull, not hardcoded, so the tiers stay correct when
account performance shifts.

**Trend logic.** Comparing 14d, 7d, and 3d on the same metric separates three
different situations that demand different actions: chronically bad (cut),
recently degraded (creative fatigue, refresh rather than cut), and recently
improved (leave alone or scale).

## Double-reporting diagnosis

1. Triangulate the three lead counts per campaign to establish which source is
   wrong.
2. Pull each active ad's destination URL from its creative via the API.
3. Open each funnel in the browser and check for:
   - Pixel installed more than once
   - `Lead` event firing on page load as well as on submit
   - GTM container and a hardcoded pixel both present
   - Thank-you page re-firing `Lead` on refresh
   - Hyros tracking script present and firing
   - Duplicate HubSpot form embeds
4. Report the specific cause per funnel with the fix.
5. Separately diagnose why Hyros receives no revenue events (the $0.00 TOTAL
   REVENUE column).

## Report structure

1. Headline: cut today, scale today, total waste identified
2. Which numbers to trust, and why
3. Campaign table, three windows side by side
4. Ad set table per active campaign
5. Ad-level table with the tiered cut list
6. Copy and creative recommendations, as variations and swaps off proven
   winners rather than net-new angles (per the winning-creative-evolution
   convention)
7. Tracking findings and fixes

## Verification / accuracy gate

Before any analysis, the probe output must reproduce Kurt's screenshots:

| Check | Expected |
|---|---|
| 14-day (Jul 21 - Aug 3) spend | $14,846.77 |
| 14-day Hyros calls / leads / CPL | 63 / 73 / $203.38 |
| 7-day (Jul 29 - Aug 4) spend | $6,890.57 |
| 7-day Hyros calls / leads | 31 / 29 |

If the pull does not match, the query is wrong and gets fixed before any
conclusion is drawn. Data accuracy first.

## Constraints

- All probes are read-only. No writes to FB, Hyros, or HubSpot.
- Raw pulls land in the session scratchpad as JSON, not in the repo.
- Probes bypass the Streamlit cache via `fn.__wrapped__(...)` where they reuse
  existing loaders, and run through the Bash tool (the context-mode sandbox's
  `python` is a Windows stub).
- Report prose uses standard hyphens, no em dashes.
