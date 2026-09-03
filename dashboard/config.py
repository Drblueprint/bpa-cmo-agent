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
HS_PROP_CONTRACT_TIER = "contract_tier"  # BPA plan/tier (PRIMARY, FULL, 90-DAY, DIY, etc.)
HS_PROP_SEND_CONTRACT_OPTIONS = "send_contract_options"  # enum; MUDA detection lives here
# Real form/meeting submission event timestamp — survived the Apr 7 2026
# bulk-stamp that overwrote typeform_submission_date for 1,602 contacts.
# Use this instead of typeform_submission_date for date-based lead filtering.
HS_PROP_RECENT_CONVERSION_DATE = "recent_conversion_date"
HS_PROP_RECENT_CONVERSION_EVENT = "recent_conversion_event_name"
# HubSpot analytics: data_1 holds the inbound traffic source (domain / ad
# platform). Used to detect TheraRay-origin closes when no typeform asset
# is present (e.g., direct-traffic contacts from theraray.org).
HS_PROP_ANALYTICS_SOURCE = "hs_analytics_source"
HS_PROP_ANALYTICS_SOURCE_DATA_1 = "hs_analytics_source_data_1"
# Custom property the team fills when a contact was referred by a doctor
# (e.g. "James Haley"). Attribution FALLBACK for contacts with no typeform
# asset: they surface as "Referral - <name>" instead of (unattributed).
HS_PROP_REFERRING_DOCTOR = "referring_doctor_s_name"
# Substring that identifies a MUDA (Multi Unit Discount Agreement) deal in the
# send_contract_options value 'MUDA - CHIRO (Multi Unit Discount Agreement)'.
SEND_CONTRACT_MUDA_TOKEN = "MUDA"
HS_PROP_TYPEFORM_SUBMISSION_DATE = "typeform_submission_date"  # datetime; HubSpot confirms via probe
HS_LIFECYCLE_MQL_VALUE = "marketingqualifiedlead"  # confirmed via probe on 2026-05-15
# Date a contact entered the Marketing Qualified Lead lifecycle stage.
# This is the Callable MQL source, NOT lifecyclestage. lifecyclestage
# ratchets forward, so a contact promoted to salesqualifiedlead stops
# reading as MQL; this property is stamped once and never moves.
# Verified 2026-08-28: filterable server-side, 189 entries in 60 days,
# 98% stamp rate for contacts created in-window who booked a discovery call.
HS_PROP_MQL_ENTERED = "hs_v2_date_entered_marketingqualifiedlead"

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

# Disqualified outcome stages — subset of HELD stages, broken out for DQ counts.
STAGES_15MIN_DQ: set[str] = {
    "33595199",   # SDR Pipeline: 15 min Call Completed - Disqualified
    "1031449111", # PT Marketing Pipeline: 15-min Call Completed-Disqualified
}

STAGES_STRATEGY_DQ: set[str] = {
    "1205515693", # SDR Pipeline: Strategy Call Complete - Disqualified
    "1031449110", # PT Marketing Pipeline: Strategy Call Complete-Disqualified
}

# --- HubSpot closed-won stage IDs ---
STAGES_CLOSED_WON: set[str] = {
    "closedwon",  # Sales Pipeline (id=default): Closed Won
    "24094605",   # SALES - V2 (id=8346417): CLOSED - Won
    "1163151789", # SALES - V2: DIY (no closedate; uses createdate)
    "1123458844", # SALES - V2: 90-Day (no closedate; uses createdate)
}

# Stages that don't have a HubSpot closedate set. We use the stage-entry
# timestamp (hs_v2_date_entered_<stage_id>) as the effective close date,
# because the deal may have been *created* well before the doctor was actually
# promoted into the DIY / 90-Day stage. Per Dr. Gumm: these deals are
# signed-and-counted even though HubSpot's `probability` < 1.0 keeps them out
# of standard "won" queries.
STAGES_CLOSED_WON_NO_CLOSEDATE: set[str] = {
    "1163151789",  # DIY
    "1123458844",  # 90-Day
}

# Map stage_id -> the HubSpot deal property that holds when the deal entered
# that stage. Used to compute the effective close date for STAGES_CLOSED_WON_
# NO_CLOSEDATE stages.
STAGE_ENTRY_DATE_PROPERTIES: dict[str, str] = {
    "1163151789": "hs_v2_date_entered_1163151789",  # DIY
    "1123458844": "hs_v2_date_entered_1123458844",  # 90-Day
}

# Stages for counting NEW customer wins. Per Dr. Gumm: only SALES-V2's
# Closed-Won counts as a new BPA signup. The default Sales Pipeline's
# 'closedwon' is something else and should NOT be counted as a new customer.
NEW_CUSTOMER_STAGES: set[str] = {"24094605", "1163151789", "1123458844"}

# --- Campaign group regex patterns ---
# Match against FB campaign names like "DS | __Chiro__ Mixed Funnel Setup | CBO | USA"
CAMPAIGN_GROUPS: list[tuple[str, re.Pattern[str]]] = [
    ("EMX",                      re.compile(r"__EMX__|\bEMX\b", re.IGNORECASE)),
    ("Practice Growth Workshop", re.compile(r"__Practice Growth Workshop", re.IGNORECASE)),
    ("Chiro",                    re.compile(r"__Chiro__", re.IGNORECASE)),
    ("PT Recovery",              re.compile(r"__PT__|__Recovery__", re.IGNORECASE)),
    ("TheraRay",                 re.compile(r"__Theraray__", re.IGNORECASE)),
    ("NLAP",                     re.compile(r"__NLAP__", re.IGNORECASE)),
    # MAP campaigns carry no __TOKEN__ wrapper, unlike the others. Verified
    # against all 46 distinct campaign names in the trailing 120 days: this
    # pattern hits the three MAP Protocol campaigns and nothing else.
    ("MAP",                      re.compile(r"\bMAP Protocol\b", re.IGNORECASE)),
]

# EMX rolls up into Chiro totals in addition to being its own row
EMX_PARENT = "Chiro"

# --- PAID MEDIA tab (2026-08-28) ---
# Segment roll-up for the PAID MEDIA tab ONLY. Existing tabs keep their own
# group labels; this must not disturb the EMX-into-Chiro roll-in the weekly
# metrics depend on.
SEGMENT_ROLLUP: dict[str, str] = {
    "EMX": "Event",
    "Practice Growth Workshop": "Event",
}

# Creative Tracker. 500 ads delivered in the trailing 90 days but only 37
# cleared $500, and the reference deck shows 16 rows, so a floor is required
# for the table to be readable.
CREATIVE_SPEND_FLOOR: float = 500.0
# An ad is a Winner at 25% below its own segment's average cost per callable
# MQL, Stand Out between 10% and 25% below. Scored per segment so a Chiro ad
# is judged against Chiro, not against NLAP.
CREATIVE_WINNER_PCT: float = 0.25
CREATIVE_STANDOUT_PCT: float = 0.10
# Volume guard. Without it, one callable MQL on $600 of spend scores as a
# Winner on noise alone.
CREATIVE_MIN_MQL: int = 3

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
    "5 Million Dollar Practice Secrets typeform": "Chiro",
    "The Informed Chiro typeform":    "Chiro",
    "EMX Forth Worth typeform":       "EMX",     # typo "Forth" matches HubSpot's stored value
    "EMX Kansas City 2026":           "EMX",     # year-suffixed variant
    "Practice Growth Workshop Dallas": "Practice Growth Workshop",
    # --- Added 2026-08-28 from a live 120-day probe. These three labels were
    # in active use and mapped to nothing, so their leads attributed to no
    # group: spend still landed in the group, the leads it bought did not, and
    # cost per lead inflated silently. The first two are renamed variants of
    # assets already mapped under their older labels (both variants are live).
    "Top 10 Things Muiltimillion Dollar Practices Do": "Chiro",  # 54 leads/120d
    "BPA Revenue Pyramid":            "Chiro",   # 16 leads/120d
    # Trailing space is part of the value HubSpot stores. Removing it makes the
    # lookup miss silently. Covered by test_map_asset_requires_exact_trailing_space.
    "Movement Activation Protocol ":  "MAP",     # 13 leads/120d
}

# --- HubSpot owner ID -> human name mapping ---
# Values come from the BPA team's HubSpot user IDs. Extend as the team grows.
# Unknown IDs are surfaced verbatim with a "(unknown)" suffix so they can be
# added later.
HS_OWNER_NAMES: dict[str, str] = {
    "89638769": "Peyton",
    "79870794": "Garrett",
    "93727575": "Kyle Naron",       # SDR (added 2026-06-17)
    "95056529": "Jake Fex",         # SDR (added 2026-06-27)
    "95056530": "Madison Workman",  # SDR (added 2026-06-27)
    "44815718": "Scott Warren",
    "176135509": "Scott Warren",   # HubSpot owner-ID variant (same person as 44815718)
    "77643349": "Dr. Eric Smith",
    "24801837": "Dr. William Lewis",
    "79162996": "Dr. William Lewis",  # HubSpot owner-ID variant
    "61097347": "Haley",
    "568393136": "Haley",
    "1266266951": "Self Booking",   # Kurt Kleinpeter — leads who self-booked
    "337212494": "Dylan Dault (former BDS)",
    "78947719": "Gage Humbarger (former SDR)",
    "56929167": "Dr. Michael McCracken (former)",
    "204897352": "Dr. Blaine Kingsbury",
    "377861017": "Dr. Samantha Luther (former)",
    "135970974": "Brent Weldon",
}

# Former team members no longer with BPA in 2026. When their ID appears as
# an owner on a contact / deal / meeting, resolve_owner() returns
# "(unassigned)" so it red-flags in the dashboard — prompts reassignment.
# Keep in sync with HS_OWNER_NAMES (these IDs ARE in the names map so we
# could still surface the historical attribution if needed).
FORMER_OWNER_IDS: set[str] = {
    "135970974",  # Brent Weldon
    "337212494",  # Dylan Dault
    "377861017",  # Dr. Samantha Luther
    "56929167",   # Dr. Michael McCracken
    "78947719",   # Gage Humbarger
    "61097347",   # Haley Stewart
    "568393136",  # Haley Stewart (variant)
}

# Owner IDs who are SMEs (closers), not BDS — exclude them from the BDS
# Performance table even if a contact has them set as `bds`.
BDS_EXCLUDED_OWNERS: set[str] = {
    "77643349",   # Dr. Eric Smith (SME, not BDS)
}


def resolve_owner(value) -> str:
    """Map a HubSpot owner field value (numeric ID, string, or None) to a name.

    - If value is None/empty: "(unassigned)"
    - If value is in FORMER_OWNER_IDS: "(unassigned)" so stale ownership
      red-flags in the dashboard and prompts reassignment.
    - If value is in HS_OWNER_NAMES: returns the mapped name.
    - Otherwise: returns the raw value with "(unknown)" suffix.
    """
    if value is None:
        return "(unassigned)"
    s = str(value).strip()
    if not s:
        return "(unassigned)"
    if s in FORMER_OWNER_IDS:
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

# Cash collection per closed deal per group. Per Dr. Gumm — for now this
# matches GROUP_DEFAULT_DEAL_AMOUNT (the standard cash-up-front amount).
# When payment-plan tracking is wired, this will diverge from contract revenue.
GROUP_CASH_COLLECTED_PER_DEAL: dict[str, float] = {
    "Chiro":       47928.0,
    "PT Recovery": 23928.0,
}

# --- Monthly payroll for CAC calc. None = "ad-only CAC" shown with a tooltip flag. ---
# Provide real numbers when ready and CAC will auto-include them.
SDR_PAYROLL_MONTHLY: float | None = None
SME_PAYROLL_MONTHLY: float | None = None

# --- Sales team commissions per CLOSED deal (Dr. Gumm, 2026-05-22) ---
# Only per-close commissions count toward CAC (activity payouts for showed-DC /
# showed-strategy are intentionally excluded). See
# docs/superpowers/specs/2026-05-22-cac-commission-model.md.

# SDR close commission by lead temperature.
# Warm = contact has typeform_asset_download populated (marketing opt-in).
# Cold = no typeform (sales outreach / referral).
SDR_CLOSE_COMMISSION: dict[str, float] = {"warm": 200.0, "cold": 400.0}

# BDS commission — flat, every closed deal.
BDS_CLOSE_COMMISSION: float = 300.0

# SME commission per closed deal, by deal group.
# Standard Chiro = $2000. PT / EMX (Event-Chiro) / MUDA (multi-location) = $1000.
# MUDA has no detection signal yet (see spec) — multi-location Chiro deals will
# currently bill at the Chiro $2000 rate until a flag is wired.
SME_CLOSE_COMMISSION: dict[str, float] = {
    "Chiro":       2000.0,
    "PT Recovery": 1000.0,
    "EMX":         1000.0,   # Event Chiro
    "MUDA":        1000.0,   # multi-location (no auto-detect yet)
    "_default":    1000.0,
}

# Flat per-close commission (Gerri).
FLAT_CLOSE_COMMISSION: float = 25.0

# --- COMMISSIONS tab payout matrix (Garrett/Callum review; 2026-07-10) ---
# Separate from the CAC constants above so the executive CAC number is
# undisturbed. SDR is warm/cold; BDS/SME/Gerri are flat. Full close = Primary-1;
# a 90-day pays a base, and converting to Primary-1 pays the bonus (base+bonus =
# full). DIY closes pay nothing to SDR/BDS/SME (Gerri still counts them).
COMMISSION_RATES: dict = {
    "sdr": {
        "disco_complete":   {"warm": 20.0,  "cold": 100.0},
        "strategy_complete": {"warm": 100.0, "cold": 100.0},
        "full_close":       {"warm": 200.0, "cold": 400.0},
        "ninety_day":       {"warm": 50.0,  "cold": 100.0},
        "conversion_bonus": {"warm": 150.0, "cold": 300.0},
    },
    "bds": {"full_close": 300.0, "ninety_day": 50.0, "conversion_bonus": 250.0},
    "sme": {"full_close": 2000.0, "ninety_day": 500.0, "conversion_bonus": 1500.0},
    "gerri_per_close": 25.0,
    "stages": {
        # Full close = SALES-V2 Primary-1 only. Default-pipeline "closedwon" is
        # NOT a real BPA signup (per Dr. Gumm / NEW_CUSTOMER_STAGES) -> no commission.
        "full": ("24094605",),
        "ninety_day": "1123458844",
        "diy": "1163151789",
    },
}

# --- Stale-data floor (configurable per session) ---
# Default = 90 days. UI selector allows 120 and 180 for longer-cycle reviews.
from datetime import date as _date, timedelta as _timedelta
DATA_FLOOR_DAYS_BACK: int = 180
DATA_FLOOR_OPTIONS: list[int] = [90, 120, 180]


def data_floor_date(days_back: int | None = None) -> _date:
    """Return today minus N days. Defaults to DATA_FLOOR_DAYS_BACK when not provided."""
    if days_back is None:
        days_back = DATA_FLOOR_DAYS_BACK
    return _date.today() - _timedelta(days=days_back)

# HubSpot portal ID — used to build contact-record URLs for click-through.
# Sourced from .env earlier (portal 9089349). Confirm with HubSpot URL pattern:
# https://app.hubspot.com/contacts/{portal_id}/record/0-1/{contact_id}
HUBSPOT_PORTAL_ID: str = "9089349"


def hubspot_contact_url(hs_id) -> str:
    """Build a clickable URL to the contact record in HubSpot.

    Returns empty string if hs_id is empty/None so the UI shows blank instead
    of a broken link.
    """
    if hs_id is None or str(hs_id).strip() == "":
        return ""
    return f"https://app.hubspot.com/contacts/{HUBSPOT_PORTAL_ID}/record/0-1/{hs_id}"


def asset_or_referral(asset, referring_doctor) -> str:
    """Asset label for display, falling back to the doctor-referral field.

    Contacts who came in via referral have no typeform asset; show
    "Referral: <name>" (from referring_doctor_s_name) instead of a blank so
    every lead's origin is visible in detail tables.
    """
    a = ("" if asset is None else str(asset)).strip()
    if a and a.lower() != "nan":
        return a
    r = ("" if referring_doctor is None else str(referring_doctor)).strip()
    return f"Referral: {r}" if r and r.lower() != "nan" else ""


# --- Timestamp display ---
# All HubSpot/AirCall timestamps land in UTC. Convert to America/Chicago for
# display so the sales floor sees CT consistently across every tab.
DISPLAY_TIMEZONE = "America/Chicago"
DEFAULT_DATETIME_FORMAT = "%m/%d/%Y %I:%M %p"
DEFAULT_DATE_FORMAT = "%m/%d/%Y"


def is_unassigned_value(v) -> bool:
    """Return True for cells that represent missing/unknown attribution:
    None / NaN / empty / "(unassigned)" / anything ending in "(unknown)" /
    "(unattributed)". Used by style_unassigned() to flag rows in red."""
    if v is None:
        return True
    import pandas as _pd
    try:
        if _pd.isna(v):
            return True
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    if not s:
        return True
    if s == "(unassigned)" or s == "(unattributed)":
        return True
    if s.endswith("(unknown)"):
        return True
    return False


def style_unassigned(df, columns: list | None = None,
                     green_when=None):
    """Return a pandas Styler that paints attribution problems.

    - columns: list of column names to check for unassigned/unknown values
      (rendered red + bold). When omitted, every column is checked.
    - green_when: optional callable(row) -> bool. Rows where it returns True
      get a light-green background (#d1fae5) — used to highlight rows with
      a booked appointment, an active deal, etc.

    Uses Styler.apply(axis=1) for broad pandas compatibility (Styler.map was
    added in pandas 2.1, so older Streamlit Cloud installs miss it).
    """
    red_cols = set(columns) if columns else set(df.columns)

    def _row_styles(row):
        green = bool(green_when and green_when(row))
        cells = []
        for col in row.index:
            css = "background-color: #d1fae5; " if green else ""
            if col in red_cols and is_unassigned_value(row[col]):
                css += "color: #d62728; font-weight: 600"
            cells.append(css)
        return cells

    return df.style.apply(_row_styles, axis=1)


def format_ct_series(series, fmt: str = DEFAULT_DATETIME_FORMAT):
    """Convert a UTC timestamp series to America/Chicago and format.

    Returns a pandas Series of formatted strings, with empty string for NaT.
    Accepts ISO strings, datetime objects, or anything pd.to_datetime handles.
    Use fmt=DEFAULT_DATE_FORMAT for date-only display.
    """
    import pandas as _pd  # local import keeps config.py import-light
    parsed = _pd.to_datetime(series, utc=True, errors="coerce")
    converted = parsed.dt.tz_convert(DISPLAY_TIMEZONE)
    return converted.apply(lambda x: x.strftime(fmt) if _pd.notna(x) else "")


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
    "1977979": "Kyle Naron",        # SDR (added 2026-07-10)
    "1999397": "Jake Fex",          # SDR (added 2026-07-10)
    "1999661": "Madison Workman",   # SDR (added 2026-07-10)
}

# AirCall user_id → HubSpot SDR owner_id (so we can attribute calls to SDR rollups).
# Only SDRs/BDS who appear in HubSpot contact properties.
AIRCALL_TO_SDR_OWNER: dict[str, str] = {
    "1551010": "89638769",  # Peyton
    "1605109": "79870794",  # Garrett
    "1523089": "44815718",  # Scott (BDS — included for completeness)
    "1630108": "568393136", # Haley
    "1977979": "93727575",  # Kyle Naron
    "1999397": "95056529",  # Jake Fex
    "1999661": "95056530",  # Madison Workman
}

# AirCall users to EXCLUDE from SDR Call Activity (admins, always-closed seats, etc.).
# Leave empty initially — include everyone and prune later if needed.
AIRCALL_EXCLUDED_USERS: set[str] = set()

# Connect threshold: outbound call with answered_at not null AND duration >= this.
AIRCALL_CONNECT_DURATION_SEC: int = 10

# Window after a connect during which a 15-min meeting booking is attributed to that call.
AIRCALL_CONV_TO_DISCO_WINDOW_HOURS: int = 24

# --- Weekly Metrics tab (2026-05-19) ---

# HubSpot form IDs counted toward BOFU Submissions (Total).
# Just the two Master Forms per Dr. Gumm — other BOFU-named forms (YT, FB-1,
# Email Link, Manually Distributed, BOFU-to-15-Min) intentionally excluded.
BOFU_FORM_IDS: list[str] = [
    "71839f2a-34e7-463c-9ac5-d885caa6eb23",  # NB | Master Forms | Booking Form | BOFU
    "233f88f1-bd89-45f1-bf2b-41f4d10632d3",  # KK | Master Forms | Booking Form | BOFU (PT Market)
]

# HubSpot list IDs for non-typeform marketing groups.
# TheraRay leads fill the "TheraRay User Request Form" which auto-adds them
# to this segment list. Cleaner than matching FB campaign IDs via utm_campaign.
THERARAY_HUBSPOT_LIST_ID: str = "6280"
NLAP_HUBSPOT_LIST_ID: str = "7086"  # HubSpot list of NLAP opt-ins (FB lead source)

# Typeform asset labels that are unmapped BY DESIGN, because those leads
# attribute through the two HubSpot lists above rather than through
# ASSET_TO_GROUP. Adding any of these to ASSET_TO_GROUP would double-count
# leads that merge_list_group already re-tags, which is why
# test_groups.test_list_based_assets_stay_unmapped pins them as absent.
#
# This exists so the unmapped-asset tripwire on the PAID MEDIA tab can tell an
# operator which labels are a genuine gap to fix and which must be left alone.
# Compared case-insensitively and whitespace-stripped, so a variant that gains
# or loses a trailing space is still recognised.
LIST_ATTRIBUTED_ASSETS: frozenset[str] = frozenset({
    "TheraRay",
    "TheraRay Device ",
    "TheraRay User ",
    "NLAP User ",
    "Neuro-Lymphatic Activation Protocol ",
})

# Webinar contact properties (confirmed via probe on 2026-05-19).
HS_PROP_WEBINAR_REG_DATE = "webinar_registration_date"
HS_PROP_WEBINAR_COMPLETED_DATE = "webinar_completed_date"
HS_PROP_PT_WEBINAR_REG_DATE = "pt_webinar_registration_date"
HS_PROP_PT_WEBINAR_COMPLETED_DATE = "pt_webinar_completed_date"

# Number of weeks shown by default in the METRICS tab.
METRICS_WEEKS_BACK: int = 8

# Goals (≥ threshold). Edit here to update targets — version-controlled.
METRICS_GOALS: dict[str, float] = {
    "chiro_ad_spend": 0,
    "chiro_link_clicks": 0,
    "chiro_cpc": 0,
    "chiro_lead_magnet_optins": 0,
    "chiro_new_leads": 0,
    "pt_ad_spend": 0,
    "pt_link_clicks": 0,
    "pt_cpc": 0,
    "pt_lead_magnet_optins": 0,
    "pt_new_leads": 0,
    "theraray_ad_spend": 0,
    "theraray_leads": 0,
    "theraray_15min_scheduled": 2,
    "emx_ad_spend": 0,
    "emx_leads": 0,
    "pgw_ad_spend": 0,
    "pgw_leads": 0,
    "map_ad_spend": 0,
    "map_leads": 0,
    "webinar_registrations": 12,
    "webinar_completions": 8,
    "pt_webinar_registrations": 0,
    "pt_webinar_completions": 0,
    "bofu_submissions_total": 0,
    "fifteen_min_scheduled": 30,
    "fifteen_min_completed": 20,
    "pt_fifteen_min_scheduled": 3,
    "pt_fifteen_min_completed": 2,
    "strategy_calls_total": 15,
    "strategy_calls_completed": 10,
    "new_total_customers": 5,
    "theraray_submissions": 0,
    "nlap_submissions": 15,
    "dti_15min_scheduled": 2,
    "dti_discovery_completed": 5,
    "bofu_submissions_direct": 0,
}

# --- Closed-deal source overrides ---
# Per Dr. Gumm (2026-05-20): these 27 YTD closed-won contacts lack
# typeform_asset_download in HubSpot but were sourced via known channels.
# This override map fills the gap so they're properly attributed AND classified
# as marketing vs non-marketing.
#
# Format: {email_lowercase: (source_label, group, is_marketing)}
# is_marketing = True for lead-magnet/event-form/marketing-list sources;
#                False for cold sales outreach + referrals.
# Stage-based source fallback: when a closed deal's contact has no typeform
# attribution AND no email-based CONTACT_SOURCE_OVERRIDES entry, the deal's
# stage itself serves as the source label.
# Tuple format: (source_label, default_group, is_marketing)
# 90-Day and DIY are sales-driven program types (not marketing), so
# is_marketing defaults to False; default group is Chiro (most BPA customers).
STAGE_SOURCE_FALLBACK: dict[str, tuple[str, str, bool]] = {
    "1163151789": ("DIY Program", "Chiro", False),     # SALES-V2 DIY stage
    "1123458844": ("90-Day Program", "Chiro", False),  # SALES-V2 90-Day stage
}

# Manual exclusion list: contacts to remove from all marketing views regardless
# of their typeform_asset_download value. Use for known false-positives (e.g.,
# contact filled a form for testing, partner referral, or some other reason
# the marketing team doesn't want them counted).
# Key by email (lowercase).
# recent_conversion_event_name prefixes that indicate a SALES-CYCLE action
# (not a fresh marketing form fill). Filtered out of load_marketing_contacts
# so the lead count only includes real lead-acquisition events.
# Mirrors the user's source-of-truth tool's "Exclude Typ...(6)" opt-in
# filter. Matched as case-insensitive startswith.
SALES_CYCLE_CONVERSION_PREFIXES: tuple[str, ...] = (
    "Meetings Link:",                  # all sales-stage meeting bookings
    "Call Schedule Form",              # BOFU + master booking forms
    "Day 1 Success Series",            # post-close onboarding
    "Nutrition Certification",         # certification path (not lead)
    "Case Management Certification",   # certification path (not lead)
)


MARKETING_EXCLUDED_EMAILS: set[str] = {
    # Casey Berry — filled EMX Kansas City form, but wasn't from marketing.
    # Per Dr. Gumm, 2026-05-20.
    "drberry2608@gmail.com",
    # Kurt Kleinpeter (BPA team) — fills typeforms for testing, his personal
    # gmail address (his @yourautomatedpractice.com is caught by the domain
    # rule, but the personal one slipped through and inflated marketing
    # leads).
    "kurttechnola@gmail.com",
}

# Internal team email domains — any contact whose email ends in one of these
# is treated as a test/team row and excluded from sales detail tables.
INTERNAL_TEAM_EMAIL_DOMAINS: set[str] = {
    "@yourautomatedpractice.com",
}


def is_internal_team_contact(email: str | None) -> bool:
    """True if a contact's email matches an internal-team domain."""
    if not email:
        return False
    e = str(email).strip().lower()
    return any(e.endswith(d) for d in INTERNAL_TEAM_EMAIL_DOMAINS)


def is_existing_customer(lifecycle_stage: str | None,
                          contract_tier: str | None) -> bool:
    """True when a contact is already a BPA customer.

    Primary signal: HubSpot lifecycle_stage == "customer".
    Backup signal: contract_tier is populated with a PAID tier — catches
    customers whose lifecycle wasn't promoted to "customer" but who have a
    contract recorded against them. EXCEPTION: "FOUNDATIONAL - C" is the
    TheraRay/NLAP opt-in label (a lead, NOT a paid customer), so it must not
    trigger the customer exclusion — otherwise those leads (and their
    discovery / Protocol Mapping calls) disappear from lead + BDS reporting.
    """
    if lifecycle_stage and str(lifecycle_stage).strip().lower() == "customer":
        return True
    if contract_tier and str(contract_tier).strip():
        if "FOUNDATIONAL" not in str(contract_tier).strip().upper():
            return True
    return False

CONTACT_SOURCE_OVERRIDES: dict[str, tuple[str, str, bool]] = {
    # Sales outreach (not marketing)
    "drjoehuffman@gmail.com":          ("VEMX Cold Outreach", "Chiro", False),
    "liveforwellnesschiro@gmail.com":  ("Sales Outreach", "Chiro", False),
    "garrettwilder9@gmail.com":        ("Sales Outreach", "Chiro", False),
    "leonemv3@gmail.com":              ("Sales Outreach", "Chiro", False),
    "dr@rivercitywellnessatx.com":     ("Sales Outreach", "Chiro", False),
    "robertlzahn@gmail.com":           ("Sales Outreach", "Chiro", False),
    "drbriandillon@gmail.com":         ("Sales Outreach", "Chiro", False),
    "drjames2015@icloud.com":          ("Sales Outreach", "Chiro", False),
    "jamie.mchugh@mchughhealth.com":   ("Sales Outreach", "Chiro", False),
    "nathan@coleschiro.com":           ("Sales Outreach", "Chiro", False),
    "tyleredgedc@gmail.com":           ("Sales Outreach", "Chiro", False),
    "drtsmithdc@gmail.com":            ("Sales Outreach", "Chiro", False),
    "info@thebodymax.com":             ("Sales Outreach", "Chiro", False),
    "ndumayne@yahoo.com":              ("Sales Outreach", "Chiro", False),

    # Referrals (not marketing)
    "desiredhealthdc@yahoo.com":       ("Referral", "Chiro", False),
    "tpchiropractic@gmail.com":        ("Referral", "Chiro", False),
    "hondo1119@aol.com":               ("Referral", "Chiro", False),
    "bcunninghamdc@gmail.com":         ("Referral", "Chiro", False),
    "aj_bentley@sbcglobal.net":        ("Referral", "Chiro", False),
    "rvawellnesscenter@gmail.com":     ("Referral", "Chiro", False),

    # Marketing-sourced (counts as marketing)
    "sterling@sterlingtherapy.com":               ("APTA Event Form", "PT Recovery", True),
    "drgracesyn90277@hotmail.com":                ("VEMX Marketing", "Chiro", True),
    "quintanilla_jesse@yahoo.com":                ("VEMX Marketing", "Chiro", True),
    "hackbartchiro@gmail.com":                    ("VEMX Marketing", "Chiro", True),
    # Tamika Adams-Sajdak: typeform asset says EMX Kansas City, but she
    # actually closed from the VEMX Marketing FB ads (Kurt, 2026-06-11).
    "dradamssajdak@gmail.com":                    ("VEMX Marketing", "Chiro", True),
    "danielle@keldermanstherapyservices.com":     ("5 Mil Practice Secrets Marketing", "PT Recovery", True),
    "info@loomislifecare.com":                    ("Top 10 Marketing Lead", "Chiro", True),
    "rich@newhealthmadison.com":                  ("Chiro Economics Email Blast", "Chiro", True),
}
