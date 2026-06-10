# NLAP Group - Design Spec

Date: 2026-06-10
Status: Approved (pending spec review)
Author: Kurt + Claude

## Purpose

Add NLAP (Blueprint to Neuropathy lead-acquisition) as a first-class marketing
group in the CMO dashboard, mirroring how TheraRay works. NLAP spend comes from
Facebook (attributed by campaign name), but NLAP **lead counts come from a
HubSpot list** because Facebook's lead reporting is inaccurate. NLAP should
appear everywhere the other groups do: the Executive group breakdown, group
filter, Cost-per-Stage, the Metrics daily VA summary, and Sales Asset
Performance.

## Data model

- **New standalone group `"NLAP"`** - a peer of Chiro, EMX, PT Recovery,
  TheraRay. Not rolled into any other group.
- **Spend:** Facebook Ads API, attributed to NLAP when the campaign name
  contains `__NLAP__` (confirmed token; campaigns look like
  `DS | __NLAP__ Funnel Setup | CBO | USA | ...`). Same mechanism as TheraRay's
  `__Theraray__`.
- **Leads:** HubSpot list **7086** (portal 9089349) memberships. The membership
  timestamp is the opt-in date; leads are counted when that timestamp falls in
  the window. Facebook's `fb_leads` for NLAP campaigns is ignored.
- **Economics:** lead-gen only for now. NLAP is **not** added to
  `GROUP_DEFAULT_DEAL_AMOUNT` / `GROUP_CASH_COLLECTED_PER_DEAL`, so revenue/cash
  default to $0 (identical to TheraRay today) until a deal value is provided.
- **No NLAP contract-tier or analytics-source detection** this pass (no closes
  yet). `_group_from_tier` and the `build_closed_deals_table` analytics-source
  override are left untouched.

## Components / approach

### Reusable list-group merge helper (decision A)

The TheraRay list-merge block in `sections/executive.py` (~40 lines: load list
memberships → filter to in-window → tag `typeform_asset_download` → register in
`ASSET_TO_GROUP` → concat list-rows-first + dedup `keep="first"` + force-tag)
is refactored into one **pure, reusable helper** in `data/groups.py` (next to
`match_group`) and called for **both** TheraRay and NLAP. The helper takes the
already-loaded memberships as data (no HubSpot/Streamlit dependency, so it is
unit-testable); the caller does the `load_list_memberships(list_id)`:

```
merge_list_group(contacts, memberships, *, asset_label, group, start, end) -> contacts
```

- Filters `memberships` to timestamps in `[start, end]`, builds the tagged
  contact rows for those members exactly as the current TheraRay block does
  (matching whatever it does today - stub rows vs. loaded detail - is matched
  at implementation time against the live code), tags
  `typeform_asset_download = asset_label` (e.g. "TheraRay FB Lead" /
  "NLAP FB Lead"), concats the list rows FIRST then
  `drop_duplicates(subset="hs_id", keep="first")` so the tag survives, and
  force-tags the asset on all list-member IDs.
- `ASSET_TO_GROUP[asset_label] = group` registration stays in the caller (it
  mutates module config), or is returned by the helper - decided at
  implementation time; either way both labels get registered.
- Behavior for TheraRay is equivalent to today (preserve concat-order +
  force-tag); NLAP is one additional call with list 7086.

### Config additions (`config.py`)

- `CAMPAIGN_GROUPS`: add `("NLAP", re.compile(r"__NLAP__", re.IGNORECASE))`.
  Order is safe - `__NLAP__` cannot collide with the other tokens.
- `NLAP_HUBSPOT_LIST_ID: str = "7086"` (next to `THERARAY_HUBSPOT_LIST_ID`).
- Executive `preferred` groups list: append `"NLAP"` →
  `["Chiro", "EMX", "PT Recovery", "TheraRay", "NLAP"]`.

### Executive tab (`sections/executive.py`)

- Replace the inline TheraRay merge with two `merge_list_group(...)` calls
  (TheraRay list 6280, NLAP list 7086).
- NLAP automatically appears in: the per-group ad-spend/leads breakdown, the
  group filter dropdown, and the Cost-per-Stage-by-source section (it is a
  group with FB spend + tagged leads).

### Metrics daily VA summary (`reconcile.py` `daily_va_summary` + `sections/metrics.py`)

- `daily_va_summary` gains an NLAP block parallel to the TheraRay block: NLAP
  spend = `fb[fb["group"] == "NLAP"]["spend"].sum()`; NLAP leads = count of list
  7086 memberships whose timestamp is in window. Returns `nlap_spend`,
  `nlap_leads`, `nlap_cpl` (mirroring the theraray_* keys).
- `metrics.py` loads list 7086 memberships and passes them to
  `daily_va_summary` (alongside the existing `theraray_memberships`), and
  renders the NLAP spend / leads / CPL line in the daily summary.

### Sales Asset Performance

- No code change needed: once list-7086 members are tagged
  `"NLAP FB Lead"` → group NLAP, they flow into Asset Performance as an "NLAP FB
  Lead" asset row like "TheraRay FB Lead" does.

## Testing

- Unit test `merge_list_group`: list rows tagged + grouped correctly; dedup
  keeps the tagged row when a member already exists in contacts; in-window
  filter on membership timestamp; TheraRay-equivalence (same output as the old
  inline logic for a TheraRay fixture).
- Unit test `daily_va_summary` NLAP block: nlap_spend from FB group NLAP,
  nlap_leads from in-window memberships, nlap_cpl = spend/leads (None when 0).
- `match_group("DS | __NLAP__ Funnel Setup | CBO | USA")` → `"NLAP"`.
- Keep existing 55 tests green.

## Out of scope (this pass)

- NLAP deal value / closes / revenue (lead-gen only; $0 until specified).
- NLAP contract-tier suffix and analytics-source-data override (no closes).
- Generalizing `daily_va_summary` beyond adding the NLAP block (the Chiro+EMX
  rollup and TheraRay block stay as-is; NLAP is added parallel).
