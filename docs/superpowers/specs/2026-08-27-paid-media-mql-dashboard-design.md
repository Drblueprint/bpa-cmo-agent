# Paid Media MQL Dashboard Design

Date: 2026-08-27
Author: Claude, with Kurt
Status: Approved for planning
Branch: `feature/cmo-dashboard`

## Goal

Add a PAID MEDIA tab to the BPA CMO dashboard carrying two tables modeled on the
reference deck Kurt supplied:

1. **Daily MQL Summary** - one row per day, showing lead volume, callable MQL
   volume, the conversion between them, and the cost of each.
2. **Results by Segment** - one row per marketing segment, showing the full
   funnel from spend through closed customer, with cost at every stage.

The reference deck splits the second table by industry. BPA has no industries,
so segments are derived from the Facebook campaign name, which Kurt confirmed is
always accurate.

Both tables refresh on the existing 15 minute cache and the existing
push-to-deploy pipeline. No new infrastructure is required for the "updated
daily" requirement.

## Decisions

Every decision below was made by Kurt during the 2026-08-27 brainstorming
session. The rationale is recorded so a future reader does not relitigate them.

### Callable MQL means HubSpot lifecycle MQL

A Callable MQL is a contact that has entered the HubSpot lifecycle stage
`marketingqualifiedlead`. Kurt chose this over a phone-number check, a typeform
qualification threshold, or an AirCall dial check, because it reflects real
qualification the team already performs rather than a mechanical proxy.

**Source property is `hs_v2_date_entered_marketingqualifiedlead`, not
`lifecyclestage`.** This matters. `lifecyclestage` ratchets forward, so a
contact that progresses to `salesqualifiedlead` or `opportunity` stops reading
as MQL. Counting current stage would both undercount callable MQLs and rewrite
history on every refresh. The v2 entry-date property is stamped once and never
moves. It follows the same naming convention the Commissions tab already relies
on (`hs_v2_date_entered_24094605`).

Probe evidence, 2026-08-27:

- `hs_v2_date_entered_marketingqualifiedlead` exists and is filterable
  server-side via the CRM search API. 189 contacts entered MQL in the trailing
  60 days.
- Current-stage distribution over 410 marketing contacts in the same window:
  143 `lead`, 105 `marketingqualifiedlead`, 87 `salesqualifiedlead`,
  71 `opportunity`. The 87 and 71 are contacts a current-stage count would
  wrongly exclude.

**Known limitation, accepted:** the property is stamped only on contacts that
actually pass through the MQL stage. In a 100 contact sample, 19 customers and
1 opportunity had no MQL stamp, having jumped straight from `lead` to a later
stage. Those contacts will never count as Callable MQL. This understates the
metric by an unknown but small amount. It is preferable to the alternative,
which is a number that silently changes every day.

### Row dating differs by table, deliberately

**Daily MQL Summary is activity-dated.** A lead counts on the day it was
created. A callable MQL counts on the day it entered MQL. These can be different
days for the same contact. Once a day has passed, its row never changes again.

**Results by Segment is cohort-dated.** Leads, callable MQLs, calls and closes
are all attributed to the lead that generated them, and counted in the window
that lead arrived in. Spend is therefore matched to the leads it actually
bought.

The reason for the split is that the two tables answer different questions. The
daily table is the morning operations read, so stability matters more than
attribution purity: a number that moves after the fact destroys trust in the
report. The segment table answers whether Chiro is worth more than NLAP, which
requires spend matched to the leads it bought, and over a 30 day window the
maturation distortion is tolerable.

Each table must carry a visible label stating its dating convention. A reader
who confuses the two will draw wrong conclusions.

### Segments come from the campaign name

Five segments, derived by matching the Facebook campaign name against a regex,
using the existing `CAMPAIGN_GROUPS` mechanism:

| Segment | Campaign name signal | 60d spend as of 2026-08-27 |
|---|---|---|
| Event | `EMX` or `Practice Growth Workshop` | $37,917 |
| Chiro | `__Chiro__` | $18,300 |
| NLAP | `__NLAP__` | $12,975 |
| TheraRay | `__Theraray__` | $4,577 |
| MAP | `MAP Protocol` | $4,265 |

Event merges EMX Kansas City and Practice Growth Workshop Dallas into a single
row, per Kurt's framing of events as one channel.

PT Recovery has spent $0 in 60 days and is omitted while dormant. It reappears
automatically if spend resumes, because segment rows are enumerated from the
data rather than hardcoded.

An **(unmatched)** row catches any campaign whose name matches no segment
regex. This is a tripwire, not a bucket. Kurt is correct that campaign names are
always accurate; the failure this guards against is our regex list falling
behind a new launch, which is exactly how MAP went unreported.

### No revenue, profit, or ROAS columns

The reference deck carries Revenue, Profit, CPA and ROAS. Three of those four
cannot be computed honestly from current data.

Probe evidence, 2026-08-27: **all 80 closed-won deals year to date carry an
`amount` of exactly $40,000. One distinct value across the entire dataset.** In
June the figure was 51 of 57; the placeholder is not being corrected and every
new deal inherits it.

Consequently `Revenue` would equal Sales count multiplied by a constant,
`Profit` would equal that minus spend, and `ROAS` would equal that divided by
spend. All three would present the Sales count as though it were revenue
analytics.

Kurt's decision: **drop all three and compare segments on acquisition cost
instead.** Every number in the table is then real and sourced. The table
diverges from the reference deck at these three columns by design.

Two cost columns replace them:

- **Cost per Close** = segment ad spend / segment closes. Mirrors the existing
  `cac_ad_only`.
- **Segment CAC** = (segment ad spend + segment close commissions) / segment
  closes. Mirrors the existing `blended_cac` in `executive.py`, computed per
  segment rather than blended across all.

Note on naming: the existing `cac_full` in `reconcile.py` is **not** the
commission-inclusive figure. It is ad spend plus payroll, and it returns `None`
because `SDR_PAYROLL_MONTHLY` and `SME_PAYROLL_MONTHLY` are both unset. The
commission stack lives in `compute_close_commissions`, consumed by
`executive.py` to produce `blended_cac`. Segment CAC follows `blended_cac`.

Payroll is excluded from Segment CAC, consistent with `blended_cac`. Allocating
a monthly payroll figure across segments needs an allocation rule that does not
exist yet. If Kurt sets the payroll constants later, that rule is a separate
decision, not an automatic switch-on.

## Prerequisite: attribution fixes

These are defects in current attribution discovered while probing. They must
land before the new tables are trustworthy, because they corrupt the Leads
column and therefore every cost-per-lead figure derived from it.

`ASSET_TO_GROUP` maps typeform asset labels to segments. Three labels in active
use are unmapped, so those leads attribute to no segment at all:

| Asset label | Leads, 60d | Should map to | Currently |
|---|---|---|---|
| `Top 10 Things Muiltimillion Dollar Practices Do` | 54 | Chiro | unmapped |
| `BPA Revenue Pyramid` | 15 | Chiro | unmapped |
| `Movement Activation Protocol` | 10 | MAP | unmapped |

The first two are renamed variants of assets already mapped under older labels
(`Top 10 typeform` at 21 leads, `BPA Revenue Pyramid typeform` at 5 leads). The
lead magnet was relabeled and the mapping was never updated, so the majority of
each asset's volume is being dropped. **69 Chiro leads in 60 days currently
attribute to nothing**, which overstates Chiro cost per lead substantially.

Note the source-system typo in `Muiltimillion`. The mapping must match the
label exactly as HubSpot stores it.

The unmapped `TheraRay`, `TheraRay Device`, `TheraRay User`, `NLAP User` and
`Neuro-Lymphatic Activation Protocol` labels are **correct as-is** and must not
be added. Those two segments attribute through HubSpot lists 6280 and 7086 by
design; adding asset mappings would double-count them.

Required config changes:

1. `CAMPAIGN_GROUPS` gains `("MAP", re.compile(r"\bMAP Protocol\b", re.IGNORECASE))`.
2. `ASSET_TO_GROUP` gains the three rows in the table above.
3. A new `SEGMENT_ROLLUP` map folding `EMX` and `Practice Growth Workshop` into
   `Event` for this tab only. Existing tabs keep their current group labels;
   this must not disturb the EMX-into-Chiro roll-in the weekly metrics rely on.

## Data sources

| Quantity | Source | Notes |
|---|---|---|
| Spend, daily | `load_fb_insights(start, end, time_increment_days=1)` | Verified returning per-campaign-per-day rows. |
| Segment | `match_group(campaign_name)` then `SEGMENT_ROLLUP` | Campaign name is authoritative. |
| Leads | Typeform submissions via `ASSET_TO_GROUP`; HubSpot list membership for TheraRay and NLAP; FB lead count as fallback for segments with neither | Existing convention in `group_marketing_metrics`. FB lead reporting is known unreliable and is a fallback only. |
| Callable MQL | `hs_v2_date_entered_marketingqualifiedlead`, server-side filtered | New loader. |
| Calls | Booked discovery meetings, matched by `DISCOVERY_MEETING_SUBSTRINGS` | Covers both `15 min call` and `protocol mapping`, so NLAP and TheraRay discovery counts correctly. |
| Sales | Closed-won deals, `STAGES_CLOSED_WON` | Existing. |
| Commissions | `compute_close_commissions` over `build_closed_deals_table` | Existing pure function; needs a per-segment grouping variant. |

## Table 1: Daily MQL Summary

Activity-dated. One row per day in the selected window, plus a Total row.

| Column | Definition |
|---|---|
| Date | Calendar day |
| Leads | Typeform submissions dated that day, including returning contacts. This is the "All Leads" convention from the Daily VA Summary, not the net-new "New Leads" convention that additionally requires `createdate` to fall in the window. Chosen so this table reconciles against the morning post. |
| Callable MQL | Contacts entering MQL that day |
| Lead to Callable % | Callable MQL / Leads for that row |
| Cost Per Lead | Spend that day / Leads that day |
| Cost Per Callable MQL | Spend that day / Callable MQL that day |

A segment multiselect filters the table, defaulting to all segments. The header
states "dated by event" so the mixed-cohort nature of the percentage column is
not misread as a conversion rate.

## Table 2: Results by Segment

Cohort-dated. One row per segment, plus `(unmatched)` when non-zero, plus Total.

| Column | Definition |
|---|---|
| Segment | Event, Chiro, TheraRay, NLAP, MAP |
| Spend | FB spend for campaigns in the segment |
| Leads | Leads attributed to the segment in-window |
| Callable MQL | Of those leads, how many ever entered MQL |
| Cost CMQL | Spend / Callable MQL |
| Lead to Callable % | Callable MQL / Leads |
| Calls | Of those leads, how many booked discovery |
| Cost per Call | Spend / Calls |
| Callable to Call % | Calls / Callable MQL |
| Sales | Of those leads, how many closed won |
| Call to Sale % | Sales / Calls |
| Cost per Close | Spend / Sales |
| Segment CAC | (Spend + close commissions) / Sales |

Roughly nine of these come from `group_funnel_costs()` in its current form. The
new work is the Callable MQL layer, the segment roll-up, and Segment CAC.

Because closes lag lead arrival, Sales and both cost-per-close columns will read
low on recent windows. This is inherent to cohort dating and is documented on
the page rather than engineered around.

## Architecture

New pure module `dashboard/data/paid_mql.py`, zero I/O, config injected as
parameters rather than imported. This follows the `paid_media.py` precedent and
avoids growing `reconcile.py`, which is already 3,240 lines.

New loader `load_mql_entries(start, end)` in `hubspot_loader.py`, wrapped in
`@st.cache_data(ttl=900)` like its neighbors, filtering server-side on the MQL
entry date property.

New section `dashboard/sections/paid_media.py` exposing `render_paid_media()`,
wired as a fifth tab in `app.py`.

Division by zero returns `None` and renders as a dash, never zero, using the
existing `_safe_div` convention. A zero denominator and a genuine zero are
different facts and must look different.

## Testing

`python -m pytest dashboard/tests -q`, full suite green. New tests in
`dashboard/tests/test_paid_mql.py` covering every pure function, including:

- Activity vs cohort dating produce different counts for the same contact when
  lead date and MQL entry date fall on different days.
- A contact progressing past MQL still counts as a Callable MQL.
- A contact that never entered MQL does not count.
- Segment roll-up merges EMX and Practice Growth Workshop into Event.
- An unrecognized campaign name lands in `(unmatched)` rather than being dropped.
- Zero denominators return `None`, not zero.
- Segment CAC includes commissions and excludes payroll.

Styler row styling uses `.apply(axis=1)`, never `.map()`, because Streamlit
Cloud runs pandas below 2.1.

## Out of scope

- Rebuilding the tier-derived money engine. It was built and reverted in June as
  over-engineering; that decision stands.
- Backfilling real `deal.amount` values in HubSpot. Worth doing, but it is a
  sales team data-entry project, not a dashboard change.
- Payroll allocation across segments.
- Mirroring these tables onto the Executive tab.
- Ad-set and ad-level breakouts. Segment level only for this build.

## Open items

- Kurt has not supplied average contract values per segment. None are needed
  under the no-revenue decision, but if Revenue and ROAS are ever wanted, that
  is the blocking input.
- Payroll constants remain unset, so no CAC figure includes payroll.
