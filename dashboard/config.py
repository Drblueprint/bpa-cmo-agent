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
HS_PROP_15MIN_CALL_DATE = "n15_min_call_date"  # confirmed via probe on 2026-05-15; label: "15 Min Call Date", type=date
HS_PROP_LIFECYCLE_STAGE = "lifecyclestage"  # HubSpot standard property
HS_PROP_TYPEFORM_SUBMISSION_DATE = "typeform_submission_date"  # datetime; HubSpot confirms via probe
HS_LIFECYCLE_MQL_VALUE = "marketingqualifiedlead"  # confirmed via probe on 2026-05-15

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
    ("EMX",         re.compile(r"__EMX__|\bEMX\b", re.IGNORECASE)),
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
    "EMX Kansas City":                "EMX",
    "Alvin Dodson":                   "EMX",
    "Chiro Never Reach $1M ":         "Chiro",   # trailing space is in HubSpot value
    "Top 10 typeform":                "Chiro",
    "BPA Revenue Pyramid typeform":   "Chiro",
    "Can we help you scale typeform": "Chiro",
    "Referral ":                      "Chiro",   # trailing space per Dr. Gumm
}

# --- HubSpot owner ID -> human name mapping ---
# Values come from the BPA team's HubSpot user IDs. Extend as the team grows.
# Unknown IDs are surfaced verbatim with a "(unknown)" suffix so they can be
# added later.
HS_OWNER_NAMES: dict[str, str] = {
    "89638769": "Peyton",
    "79870794": "Garrett",
    "44815718": "Scott Warren",
    "176135509": "Scott Warren",   # HubSpot owner-ID variant (same person as 44815718)
    "77643349": "Dr. Eric Smith",
    "24801837": "Dr. William Lewis",
    "61097347": "Haley",
    "568393136": "Haley",
    "1266266951": "Self Booking",   # Kurt Kleinpeter — leads who self-booked
}


def resolve_owner(value) -> str:
    """Map a HubSpot owner field value (numeric ID, string, or None) to a name.

    - If value is None/empty: "(unassigned)"
    - If value is in HS_OWNER_NAMES: returns the mapped name.
    - Otherwise: returns the raw value with "(unknown)" suffix.
    """
    if value is None:
        return "(unassigned)"
    s = str(value).strip()
    if not s:
        return "(unassigned)"
    if s in HS_OWNER_NAMES:
        return HS_OWNER_NAMES[s]
    return f"{s} (unknown)"


# --- Revenue fallback per group (Option C: HubSpot deal.amount preferred, this is the fallback) ---
# Per Dr. Gumm, 2026-05-16.
GROUP_DEFAULT_DEAL_AMOUNT: dict[str, float] = {
    "Chiro":       47928.0,
    "PT Recovery": 23928.0,
    # TheraRay, EMX: not yet specified — defaults to 0 if a closed-won lands there
}

# --- Monthly payroll for CAC calc. None = "ad-only CAC" shown with a tooltip flag. ---
# Provide real numbers when ready and CAC will auto-include them.
SDR_PAYROLL_MONTHLY: float | None = None
SME_PAYROLL_MONTHLY: float | None = None

# --- Stale-data floor (Dr. Gumm directive, 2026-05-19): ---
# Drop any HubSpot meeting or deal record older than this many days.
# Rolling window: recomputed each time data_floor_date() is called.
from datetime import date as _date, timedelta as _timedelta
DATA_FLOOR_DAYS_BACK: int = 90

def data_floor_date() -> _date:
    """Return today minus DATA_FLOOR_DAYS_BACK. Records older than this are excluded."""
    return _date.today() - _timedelta(days=DATA_FLOOR_DAYS_BACK)

# --- AirCall integration (Phase B) ---
# AirCall env vars: AIRCALL_API_ID + AIRCALL_API_token (note lowercase 'token').

# AirCall user_id → display name.
AIRCALL_USER_NAMES: dict[str, str] = {
    "1507558": "Toby Hughes",
    "1523089": "Scott Warren",
    "1551010": "Peyton Fulghum",
    "1605109": "Garrett Hustedt",
    "1630108": "Haley Stewart",
    "1937276": "Callum Barton",
}

# AirCall user_id → HubSpot SDR owner_id (so we can attribute calls to SDR rollups).
# Only SDRs/BDS who appear in HubSpot contact properties.
AIRCALL_TO_SDR_OWNER: dict[str, str] = {
    "1551010": "89638769",  # Peyton
    "1605109": "79870794",  # Garrett
    "1523089": "44815718",  # Scott (BDS — included for completeness)
    "1630108": "568393136", # Haley
}

# AirCall users to EXCLUDE from SDR Call Activity (admins, always-closed seats, etc.).
# Leave empty initially — include everyone and prune later if needed.
AIRCALL_EXCLUDED_USERS: set[str] = set()

# Connect threshold: outbound call with answered_at not null AND duration >= this.
AIRCALL_CONNECT_DURATION_SEC: int = 10

# Window after a connect during which a 15-min meeting booking is attributed to that call.
AIRCALL_CONV_TO_DISCO_WINDOW_HOURS: int = 24
