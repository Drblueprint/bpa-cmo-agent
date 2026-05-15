"""Dashboard-wide constants and configuration.

Values here come from the HubSpot probe (dashboard/probes/hubspot_probe.py).
Re-run the probe if HubSpot stages or properties change.
"""
from __future__ import annotations

import re

# --- HubSpot property internal names ---
# Confirmed via dashboard/probes/hubspot_probe.py on 2026-05-15
HS_PROP_TYPEFORM_ASSET = "typeform_asset_download"  # label: "Typeform Asset Download", type=string
HS_PROP_SDR_OWNER = "sdr_owner"                     # label: "SDR Owner", type=enumeration
HS_PROP_BDS = "bds"                                 # label: "BDS", type=enumeration
HS_PROP_SME = "sme"                                 # label: "SME", type=enumeration
HS_PROP_UTM_SOURCE = "utm_source"

# --- HubSpot deal stage IDs ---
# Confirmed via probe on 2026-05-15.
# Primary pipeline: "SDR Pipeline" (id=11415832) — full BPA flow with 15-min, strategy,
# and closing stages. Supplemented with matching stages from "Sales Pipeline" (id=default)
# and "PT Marketing Pipeline" (id=705868912) for cross-pipeline completeness.
# Empty sets are OK if the logical stage doesn't exist as a distinct stage.

STAGES_15MIN_BOOKED: set[str] = {
    "33595198",   # SDR Pipeline: 15 min Call Booked
    "14814277",   # Sales Pipeline (default): 15 Min Call Scheduled
    "1031449106", # PT Marketing Pipeline: 15-min Call Scheduled
}

STAGES_15MIN_HELD: set[str] = {
    # Reasoning: HubSpot tracks "held" as outcome stages (qualified/future/disqualified).
    # All three outcomes count as "held" for conversion-rate purposes.
    "33630024",   # SDR Pipeline: 15 min Call Completed - Qualified
    "1205557771", # SDR Pipeline: 15 min Call Completed - Future
    "33595199",   # SDR Pipeline: 15 min Call Completed - Disqualified
    "244868722",  # Sales Pipeline: 15 Min Call Completed
    "1031449108", # PT Marketing Pipeline: 15-min Call Completed-Qualified
    "1031449109", # PT Marketing Pipeline: 15-min Call Completed-Future
    "1031449111", # PT Marketing Pipeline: 15-min Call Completed-Disqualified
}

STAGES_STRATEGY_BOOKED: set[str] = {
    "1269186469",         # SDR Pipeline: Strategy Call Scheduled
    "appointmentscheduled", # Sales Pipeline (default): Strategy Call Scheduled
    "1031527734",         # PT Marketing Pipeline: Strategy Call Scheduled
}

STAGES_STRATEGY_HELD: set[str] = {
    # Reasoning: same pattern as 15-min — held = all outcome sub-stages.
    "33630026",   # SDR Pipeline: Strategy Call Completed - Qualified
    "1205601913", # SDR Pipeline: Strategy Call Complete - Future
    "1205515693", # SDR Pipeline: Strategy Call Complete - Disqualified
    "qualifiedtobuy", # Sales Pipeline: Strategy Call Completed
    "1270074157", # PT Marketing Pipeline: Strategy Call Completed-Qualified
    "1031544105", # PT Marketing Pipeline: Strategy Call Complete-Future
    "1031449110", # PT Marketing Pipeline: Strategy Call Complete-Disqualified
    "1057070392", # PT Marketing Pipeline: Strategy Call Complete-BAMFAM
}

# --- HubSpot closed-won stage IDs ---
STAGES_CLOSED_WON: set[str] = {
    "closedwon",  # Sales Pipeline (id=default): Closed Won
    "24094605",   # SALES - V2 (id=8346417): CLOSED - Won
    # Reasoning: SALES-V2 is a legacy/closing pipeline; both stages count as revenue events.
}

# --- Campaign group regex patterns ---
# Match against FB campaign names like "DS | __Chiro__ Mixed Funnel Setup | CBO | USA"
CAMPAIGN_GROUPS: list[tuple[str, re.Pattern[str]]] = [
    ("EMX",         re.compile(r"__EMX__", re.IGNORECASE)),
    ("Chiro",       re.compile(r"__Chiro__", re.IGNORECASE)),
    ("PT Recovery", re.compile(r"__PT__|__Recovery__", re.IGNORECASE)),
    ("TheraRay",    re.compile(r"__Theraray__", re.IGNORECASE)),
]

# EMX rolls up into Chiro totals in addition to being its own row
EMX_PARENT = "Chiro"

# --- Typeform asset download -> campaign group mapping ---
# Populated from live probe run on 2026-05-15 (dashboard/probes/asset_probe.py).
# Expand as new assets ship. Re-run the probe to discover new values.
# Strings are EXACT matches (case-sensitive, including trailing whitespace).
# Unmapped assets surface as warnings in the dashboard.
ASSET_TO_GROUP: dict[str, str] = {
    "Recovery Program (PT) typeform": "PT Recovery",
    "EMX Fort Worth 2026":            "EMX",
    "Chiro Never Reach $1M ":         "Chiro",   # trailing space is in HubSpot value
    # UNMAPPED (ambiguous, no clear group signal):
    #   "Top 10 typeform"              — 95 contacts; unclear which campaign group
    #   "BPA Revenue Pyramid typeform" — 20 contacts; general BPA, not group-specific
    #   "Can we help you scale typeform" — 8 contacts; generic
    #   "Referral "                    — 1 contact; referral channel, not a campaign asset
}
