# Practice Growth Workshop Marketing Group — Design

Date: 2026-06-17
Origin: BPA launched a new Facebook campaign today, `DS | __Practice Growth Workshop Dallas__ Funnel Setup | CBO | USA | CA | Images June 2026 | C1`. Kurt wants it tracked as its own marketing group across the dashboard, like every other lead source.

## Goal

Register a new marketing group **"Practice Growth Workshop"** so its FB spend, leads, and downstream funnel activity are tracked everywhere the dashboard buckets by group — mirroring how **EMX** (the closest analog: an event-based, typeform-fed Chiro-market campaign) is wired.

## Decisions (locked with Kurt)

- **One group, all cities.** Match token `__Practice Growth Workshop` (regex, case-insensitive) so Dallas and any future cities roll into a single "Practice Growth Workshop" line, the way EMX bundles Fort Worth / Kansas City.
- **Leads via typeform.** Opt-ins carry `typeform_asset_download = "Practice Growth Workshop Dallas"`. (No leads exist yet — campaign launched today. The exact stored string must be verified against the first real opt-in; HubSpot asset values sometimes carry a trailing space or specific casing, e.g. "NLAP User ", "Chiro Never Reach $1M ".)
- **Full EMX mirror:** PGW spend AND leads roll into the blended "Chiro" top-line metrics (PGW is Chiro-market), AND PGW gets its own standalone weekly rows + a Cost-per-Stage funnel row + an Executive group-breakdown row.
- **Event-based economics:** SME commission $1000 (like EMX / "Event Chiro"). No `GROUP_DEFAULT_DEAL_AMOUNT` entry yet (lead-only, $0), like EMX.

## Registration map (verified against current code)

All paths under `dashboard/`. The group label string is exactly `Practice Growth Workshop`.

1. **`config.py` `CAMPAIGN_GROUPS`** — add `("Practice Growth Workshop", re.compile(r"__Practice Growth Workshop", re.IGNORECASE))` immediately AFTER the EMX entry (first-match-wins; the token is unique so order is not contentious, but keep it grouped with the event campaigns). Drives FB spend attribution via `data/groups.py:match_group`.
2. **`config.py` `ASSET_TO_GROUP`** — add `"Practice Growth Workshop Dallas": "Practice Growth Workshop"`. Drives typeform-lead attribution (`contacts["group"] = typeform_asset_download.map(asset_to_group)`). Future cities each get their own asset entry as they launch (like EMX's per-city entries).
3. **`reconcile.py` `group_funnel_costs`** — add `"Practice Growth Workshop"` to the default `groups` tuple so it gets a Cost-per-Stage row. (It is typeform-based, NOT list-based, so NO `merge_list_group` entry is needed in `executive.py` — that loop is only for TheraRay/NLAP list groups.)
4. **`sections/executive.py`** — add `"Practice Growth Workshop"` to the `preferred` group-ordering list, after `"EMX"`.
5. **`reconcile.py` `_METRIC_LABELS`** — add two standalone rows after the EMX rows:
   - `"pgw_ad_spend": "Practice Growth Workshop - Ad Spend"`
   - `"pgw_leads": "Practice Growth Workshop - Leads"`
6. **`reconcile.py` `weekly_metrics` loop** — add two branches mirroring EMX exactly:
   - `pgw_ad_spend` → `_fb_sum("Practice Growth Workshop", "spend", ws, we)`
   - `pgw_leads` → `_contacts_in_group_with_submit("Practice Growth Workshop", ws, we)` (typeform submits — same as the real `emx_leads` branch, NOT `_fb_leads`)
7. **`reconcile.py` `weekly_metrics` — roll into the blended Chiro top-line** (PGW is the 5th paid group folded into "Chiro"):
   - `chiro_ad_spend` += `_fb_sum("Practice Growth Workshop", "spend", ws, we)`
   - `chiro_link_clicks` += `_fb_clicks("Practice Growth Workshop", ws, we)`
   - `chiro_cpc` — include PGW in both the spend and clicks sums
   - `chiro_lead_magnet_optins` += `_contacts_in_group_with_submit("Practice Growth Workshop", ws, we)`
   - `chiro_new_leads` += `_contacts_in_group_new("Practice Growth Workshop", ws, we)`
8. **`reconcile.py` `_METRIC_LABELS` — relabel the blended Chiro rows** to keep them honest:
   - the 3 spend/clicks/cpc rows: `(incl. EMX + DTI)` → `(incl. EMX + DTI + Workshop)`
   - the 2 lead rows (`chiro_lead_magnet_optins`, `chiro_new_leads`): `(incl. EMX)` → `(incl. EMX + Workshop)`
9. **`config.py` `METRICS_GOALS`** — add `"pgw_ad_spend": 0`, `"pgw_leads": 0` (keeps `set(_METRIC_LABELS) == set(METRICS_GOALS)`).
10. **`config.py` `SME_COMMISSION_BY_GROUP`** — add `"Practice Growth Workshop": 1000.0` (event-based).

**Spend-only visibility (explicit requirement).** The Executive "Breakdown by group" must show PGW with its ad spend even while leads = 0. This is already satisfied by `group_marketing_metrics` (reconcile.py): it enumerates groups as the UNION of `fb_by_group.keys()` (spend) + contact-lead groups + hyros, and the executive render maps every row with NO zero-lead suppression (that suppression lives only in the separate "Conversions by group" table). So once item 1 (the FB regex) tags the campaign's spend to group "Practice Growth Workshop", the breakdown row appears automatically: Spend = $X, Marketing Leads = 0, CPL = — (None → dash), 15-min Calls = 0. No extra code beyond registration — but a regression test locks it (see Testing).

**Auto-covered, no change:** Lead Detail, Sales Asset Performance, group dropdowns (they read the `group` tag / `resolve` from the same maps). Daily VA summary has no EMX block (EMX folds into the Chiro spend line), so PGW needs none either.

## Components / data flow

FB spend → `match_group(campaign_name)` tags each FB row's `group` → `_fb_sum`/`_fb_clicks` and `group_funnel_costs` pick it up. Typeform lead → `typeform_asset_download` mapped via `ASSET_TO_GROUP` → `contacts["group"]` → lead counts, funnel, group breakdown, lead detail. Both flow into the blended Chiro top-line and the standalone PGW rows.

## Error handling / edge cases

- No leads yet: spend tracks immediately; lead rows read 0 until the first opt-in carries the asset label. Not a bug.
- Asset-label string drift (trailing space / casing): the verification step re-probes after the first opt-in; if the stored string differs, update the `ASSET_TO_GROUP` key.
- Future cities (Houston, etc.): same group via the regex for spend; add each new city's asset label to `ASSET_TO_GROUP` as it launches.
- Group ordering: the PGW token is unique, so `match_group` first-match-wins is unaffected; placing it after EMX is for readability.

## Testing

`weekly_metrics` and `match_group` are pure → TDD in `dashboard/tests/`:
- `match_group("DS | __Practice Growth Workshop Dallas__ Funnel Setup | CBO | USA | CA | Images June 2026 | C1") == "Practice Growth Workshop"`.
- `ASSET_TO_GROUP["Practice Growth Workshop Dallas"] == "Practice Growth Workshop"`.
- `weekly_metrics` with an FB fixture row `group="Practice Growth Workshop"` + a contact with that group/submit: `pgw_ad_spend` and `pgw_leads` populate, AND `chiro_ad_spend` / `chiro_lead_magnet_optins` include the PGW amounts (roll-in).
- **Spend-only group row:** `group_marketing_metrics` with an FB fixture carrying spend for group "Practice Growth Workshop" and ZERO matching contacts emits a row with `spend > 0`, `marketing_leads == 0`, `cpl` None — proving the Executive breakdown shows a spend-only group.
- `set(_METRIC_LABELS) == set(METRICS_GOALS)` still holds; no em dashes in the new/relabeled labels.

## Verification (live, before final push)

Probe FB insights for the window: confirm the new campaign classifies to group "Practice Growth Workshop" with spend > 0 (campaign started today). Confirm `pgw_ad_spend` shows that spend and it is included in the blended `chiro_ad_spend`. Present to Kurt.

## Out of scope

- A `GROUP_DEFAULT_DEAL_AMOUNT` for PGW (lead-only for now; add when a deal value is set, like TheraRay/EMX).
- A daily-VA-summary PGW block (EMX has none; folds into Chiro).
- Per-city breakout rows (one blended group per Kurt's decision).
