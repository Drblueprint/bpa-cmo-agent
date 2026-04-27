"""
Pull full profile on a specific list of leads from both Hyros and HubSpot.
Cross-references: FB ad attribution (Hyros) + HubSpot contact + deal status.
"""
import sys, json
sys.path.insert(0, r"C:\Users\kxbox\OneDrive\Desktop\bpa-cmo-agent")
sys.stdout.reconfigure(encoding="utf-8")

from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from weekly_report_v2 import load_env, hyros_paginate, extract_lead_source
from hubspot_puller import hs_request, search_paginate, typeform_asset_of, TYPEFORM_ASSET_PROPERTY

env = load_env(Path(r"C:\Users\kxbox\OneDrive\Desktop\bpa-cmo-agent\.env"))
hs_token = env["HUBSPOT_TOKEN"]
hyros_key = env["HYROS_API_KEY"]

# Leads from the screenshot (truncated emails best-guessed where cut off)
LEADS = [
    "fluxphysioandwellness@gmail.com",
    "drbillmickle@hotmail.com",
    "caitzimmer@gmail.com",
    "fourwindsdoc@gmail.com",
    "jimdigiuseppi@gmail.com",
    "chiroguy@gmail.com",
    "drfarasabeti@gmail.com",
    "lifechangersolutions@gmail.com",
    "crafey@me.com",
    "dnkgriffin@gmail.com",
    "paulbauerpt@gmail.com",
    "fulmorechiropracticcenter@gmail.com",
    "heather@activatefargo.com",
    "riahcm96@gmail.com",
    "jackc7250@gmail.com",
    "drclaymiller58@gmail.com",
    "agregory@restore-physicaltherapy.com",
]

# ── 1. Pull Hyros leads (last 14d) and index by email ──────────────────────
print("Pulling Hyros leads (last 14d)...")
today = datetime.now().strftime("%Y-%m-%d")
two_weeks = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
hyros_raw = hyros_paginate("/leads", hyros_key, {"fromDate": two_weeks, "toDate": today})
hyros_by_email = {}
for lead in hyros_raw:
    email = (lead.get("email") or "").lower().strip()
    if email:
        hyros_by_email[email] = extract_lead_source(lead)
print(f"  {len(hyros_raw)} total Hyros leads, {len(hyros_by_email)} unique emails")

# ── 2. Batch-fetch HubSpot contacts by email ──────────────────────────────
print("Looking up HubSpot contacts...")
contact_props = [
    "email", "firstname", "lastname", "lifecyclestage", "createdate",
    TYPEFORM_ASSET_PROPERTY, "typeform_submission_date",
    "hs_analytics_source", "utm_source", "utm_campaign", "utm_content",
    "hs_latest_source", "hs_latest_source_data_1",
]
payload = {
    "inputs": [{"id": e} for e in LEADS],
    "properties": contact_props,
    "idProperty": "email",
}
status, resp = hs_request("POST", "/crm/v3/objects/contacts/batch/read", hs_token, payload)
hs_by_email = {}
if status < 400:
    for r in resp.get("results", []):
        props = r.get("properties", {})
        email = (props.get("email") or "").lower().strip()
        if email:
            hs_by_email[email] = {"id": r.get("id"), "props": props}
print(f"  {len(hs_by_email)} found in HubSpot")

# ── 3. For each HubSpot contact, pull associated deals ────────────────────
print("Pulling associated deals...")
deal_props = ["dealname", "amount", "dealstage", "pipeline", "closedate", "createdate"]

def get_deals_for_contact(contact_id):
    s, r = hs_request("GET", f"/crm/v4/objects/contacts/{contact_id}/associations/deals", hs_token)
    if s >= 400:
        return []
    deal_ids = [x.get("toObjectId") for x in r.get("results", []) if x.get("toObjectId")]
    if not deal_ids:
        return []
    payload = {
        "inputs": [{"id": str(d)} for d in deal_ids],
        "properties": deal_props,
    }
    s2, r2 = hs_request("POST", "/crm/v3/objects/deals/batch/read", hs_token, payload)
    if s2 >= 400:
        return []
    return [x.get("properties", {}) for x in r2.get("results", [])]

deals_by_email = {}
for email, contact in hs_by_email.items():
    deals = get_deals_for_contact(contact["id"])
    deals_by_email[email] = deals

# ── 4. Print full profile for each lead ───────────────────────────────────
print()
print("=" * 90)
print(f"{'LEAD PROFILES':^90}")
print("=" * 90)

STAGE_LABELS = {
    "closedwon": "CLOSED WON", "24094605": "CLOSED WON", "23989362": "CLOSED WON",
    "closedlost": "Closed Lost", "24094606": "Closed Lost", "23989363": "Closed Lost",
    "appointmentscheduled": "Strategy Scheduled",
    "qualifiedtobuy": "Strategy Qualified",
    "14814277": "15-min Booked",
    "1197483324": "New Lead", "1031544103": "New Lead",
    "33595198": "15-min Booked", "1031449106": "15-min Booked",
    "33630024": "15-min Qualified", "1031449108": "15-min Qualified",
}

for email in LEADS:
    e = email.lower()
    hs = hs_by_email.get(e)
    hyros = hyros_by_email.get(e)
    deals = deals_by_email.get(e, [])

    print(f"\n{'─'*90}")
    print(f"  {email}")
    print(f"{'─'*90}")

    # HubSpot block
    if hs:
        p = hs["props"]
        name = f"{p.get('firstname','') or ''} {p.get('lastname','') or ''}".strip() or "(no name)"
        lc = p.get("lifecyclestage") or "unknown"
        tf_val = p.get(TYPEFORM_ASSET_PROPERTY) or ""
        tf_asset = typeform_asset_of(tf_val)
        tf_display = tf_asset["name"] if tf_asset else (tf_val or "not set")
        tf_seg = tf_asset["segment"] if tf_asset else "-"
        sub_date = p.get("typeform_submission_date") or "-"
        utm_src = p.get("utm_source") or p.get("hs_analytics_source") or "-"
        utm_camp = p.get("utm_campaign") or p.get("hs_latest_source_data_1") or "-"
        print(f"  HubSpot   : {name} | Lifecycle: {lc}")
        print(f"  Typeform  : {tf_display} [{tf_seg}]  (submitted: {sub_date})")
        print(f"  UTM Source: {utm_src} | Campaign: {utm_camp}")
        if deals:
            for d in deals:
                stage = STAGE_LABELS.get(d.get("dealstage", ""), d.get("dealstage", "?"))
                amt = f"${float(d.get('amount') or 0):,.0f}" if d.get("amount") else "$0"
                print(f"  Deal      : {d.get('dealname','?')} | {stage} | {amt}")
        else:
            print(f"  Deal      : no deals found")
    else:
        print(f"  HubSpot   : NOT FOUND")

    # Hyros block
    if hyros:
        print(f"  Hyros     : ad='{hyros.get('ad_name','?')}' | campaign='{hyros.get('campaign','?')}'")
        if hyros.get("creative"):
            print(f"  Creative  : {hyros['creative']}")
        tags = []
        if hyros.get("has_hubspot"):
            tags.append("!hubspot confirmed")
        if hyros.get("call_booked"):
            tags.append("call booked")
        if tags:
            print(f"  Journey   : {' | '.join(tags)}")
    else:
        print(f"  Hyros     : not in last 14d window")

print(f"\n{'='*90}")
print("Done.")
