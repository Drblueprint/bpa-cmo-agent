# CAC Commission Model — Executive Tab

**Date:** 2026-05-22
**Source:** Dr. Gumm commission structure + clarifications

## Scope decision
**Closed-deal commissions only.** Activity payouts (Showed DC, Showed Strategy)
are NOT counted toward CAC. Only per-close commissions.

## Per-closed-deal commissions

| Role | Rule | Amount |
|---|---|---|
| SDR | Warm (contact has typeform_asset_download) | $200 |
| SDR | Cold (no typeform) | $400 |
| SDR | only paid when an SDR is assigned on the contact | gated |
| BDS | every closed deal (flat) | $300 |
| SME | standard Chiro close | $2,000 |
| SME | PT / EMX (Event-Chiro) / MUDA close | $1,000 |
| Gerri | every closed deal (flat) | $25 |

## Detection rules
- **Warm vs Cold:** warm = deal's primary contact has `typeform_asset_download`
  populated. Else cold.
- **SME group:** from `build_closed_deals_table` `group` column (tier-suffix
  first, then asset map). Chiro=$2000; PT Recovery / EMX / MUDA = $1000;
  unknown group defaults to $1000.
- **Event Chiro** = EMX group (already mapped). → $1,000.
- **MUDA** = multi-location deal. **GAP:** no HubSpot signal identified yet.
  MUDA deals currently fall into their group (likely Chiro → $2000) and would
  over-count by $1000. TODO: add a `contract_tier` token or HubSpot field to
  flag multi-location, then route to $1000.

## CAC outputs (Executive, YTD)
1. **Marketing CAC (ad-only)** = YTD ad spend ÷ marketing customers. (existing)
2. **Sales Commissions (YTD)** = sum of per-close commissions on YTD closes.
3. **Avg Commission / Close** = commissions ÷ total customers.
4. **Blended CAC** = (YTD ad spend + total commissions) ÷ total customers.

## Config
All rates in `dashboard/config.py`:
`SDR_CLOSE_COMMISSION`, `BDS_CLOSE_COMMISSION`, `SME_CLOSE_COMMISSION`,
`FLAT_CLOSE_COMMISSION`.
