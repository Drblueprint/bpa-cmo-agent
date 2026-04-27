import sys
sys.path.insert(0, r"C:\Users\kxbox\OneDrive\Desktop\bpa-cmo-agent")
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path
from datetime import datetime, timedelta
from weekly_report_v2 import load_env, hyros_paginate, extract_lead_source
from hubspot_puller import hs_request, typeform_asset_of, TYPEFORM_ASSET_PROPERTY

env = load_env(Path(r"C:\Users\kxbox\OneDrive\Desktop\bpa-cmo-agent\.env"))
token = env["HUBSPOT_TOKEN"]
hyros_key = env["HYROS_API_KEY"]
email = "fulmorechiropracticcenter@gmail.com"

# HubSpot
payload = {
    "inputs": [{"id": email}],
    "properties": [
        "email", "firstname", "lastname", "lifecyclestage", "createdate",
        TYPEFORM_ASSET_PROPERTY, "typeform_submission_date",
        "hs_analytics_source", "utm_source", "utm_campaign",
        "hs_latest_source", "hs_latest_source_data_1",
    ],
    "idProperty": "email",
}
s, r = hs_request("POST", "/crm/v3/objects/contacts/batch/read", token, payload)
print(f"HubSpot HTTP {s}")
for contact in r.get("results", []):
    p = contact.get("properties", {})
    name = f"{p.get('firstname','')} {p.get('lastname','')}".strip()
    lc = p.get("lifecyclestage", "?")
    tf_val = p.get(TYPEFORM_ASSET_PROPERTY, "")
    tf = typeform_asset_of(tf_val)
    tf_display = tf["name"] if tf else (tf_val or "not set")
    tf_seg = tf["segment"] if tf else "-"
    sub = p.get("typeform_submission_date", "-")
    utm_src = p.get("utm_source") or p.get("hs_analytics_source") or "-"
    utm_camp = p.get("utm_campaign") or p.get("hs_latest_source_data_1") or "-"
    cid = contact.get("id")
    print(f"  Name      : {name}")
    print(f"  Lifecycle : {lc}")
    print(f"  Typeform  : {tf_display} [{tf_seg}]  (submitted: {sub})")
    print(f"  UTM Source: {utm_src} | Campaign: {utm_camp}")
    print(f"  Contact ID: {cid}")

    s2, r2 = hs_request("GET", f"/crm/v4/objects/contacts/{cid}/associations/deals", token)
    deal_ids = [x.get("toObjectId") for x in r2.get("results", []) if x.get("toObjectId")]
    if deal_ids:
        p2 = {"inputs": [{"id": str(d)} for d in deal_ids],
              "properties": ["dealname", "amount", "dealstage", "pipeline", "closedate"]}
        s3, r3 = hs_request("POST", "/crm/v3/objects/deals/batch/read", token, p2)
        for d in r3.get("results", []):
            dp = d.get("properties", {})
            amt = float(dp.get("amount") or 0)
            print(f"  Deal      : {dp.get('dealname','?')} | {dp.get('dealstage','?')} | ${amt:,.0f}")
    else:
        print("  Deal      : no deals found")

# Hyros
print()
today = datetime.now().strftime("%Y-%m-%d")
two_weeks = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
leads = hyros_paginate("/leads", hyros_key, {"fromDate": two_weeks, "toDate": today})
match = [l for l in leads if (l.get("email") or "").lower() == email]
if match:
    src = extract_lead_source(match[0])
    print(f"  Hyros     : ad={src['ad_name']} | campaign={src['campaign']}")
    if src.get("creative"):
        print(f"  Creative  : {src['creative']}")
    tags = []
    if src.get("has_hubspot"):
        tags.append("!hubspot confirmed")
    if src.get("call_booked"):
        tags.append("call booked")
    if tags:
        print(f"  Journey   : " + " | ".join(tags))
else:
    print("  Hyros     : not found in last 14d")
