"""
Pull HubSpot source data for call-booked leads with no Hyros ad attribution.
"""
import sys
sys.path.insert(0, r"C:\Users\kxbox\OneDrive\Desktop\bpa-cmo-agent")
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path
from hubspot_puller import hs_request, TYPEFORM_ASSET_PROPERTY, typeform_asset_of
from weekly_report_v2 import load_env

env = load_env(Path(r"C:\Users\kxbox\OneDrive\Desktop\bpa-cmo-agent\.env"))
token = env["HUBSPOT_TOKEN"]

# The 9 call-booked leads with no Hyros ad attribution
emails = [
    "mrmkaplan@gmail.com",
    "dericson@paragondrs.com",
    "rcunninghamdc@gmail.com",  # not in HubSpot - flagged
    "drcliff772@gmail.com",
    "devodoc@gmail.com",
    "drmhuppert@gmail.com",
    "drholden@buckheadchiropracticgroup.com",
    "aasburyfnp@gmail.com",
    "alexisvickersdc@gmail.com",
]

payload = {
    "inputs": [{"id": e} for e in emails],
    "properties": [
        "email", "firstname", "lastname", "lifecyclestage", "createdate",
        TYPEFORM_ASSET_PROPERTY, "typeform_submission_date",
        "hs_analytics_source", "hs_analytics_source_data_1", "hs_analytics_source_data_2",
        "hs_latest_source", "hs_latest_source_data_1", "hs_latest_source_data_2",
        "utm_source", "utm_medium", "utm_campaign", "utm_content",
        "first_conversion_event_name", "first_conversion_date",
    ],
    "idProperty": "email",
}
s, r = hs_request("POST", "/crm/v3/objects/contacts/batch/read", token, payload)

found = {
    (c.get("properties", {}).get("email") or "").lower(): c
    for c in r.get("results", [])
}

print(f"Call-booked leads with no Hyros ad attribution ({len(emails)} total)\n")
print(f"{'─'*80}")

for email in emails:
    c = found.get(email.lower())
    print(f"\n{email}")
    if not c:
        print(f"  NOT FOUND in HubSpot")
        continue
    p = c.get("properties", {})
    name = f"{p.get('firstname','') or ''} {p.get('lastname','') or ''}".strip()
    lc = p.get("lifecyclestage") or "-"
    tf_val = p.get(TYPEFORM_ASSET_PROPERTY) or ""
    tf = typeform_asset_of(tf_val)
    tf_display = tf["name"] if tf else (tf_val or "not set")

    orig_src  = p.get("hs_analytics_source") or "-"
    orig_d1   = p.get("hs_analytics_source_data_1") or "-"
    latest    = p.get("hs_latest_source") or "-"
    latest_d1 = p.get("hs_latest_source_data_1") or "-"
    utm_src   = p.get("utm_source") or "-"
    utm_med   = p.get("utm_medium") or "-"
    utm_camp  = p.get("utm_campaign") or "-"
    first_cv  = p.get("first_conversion_event_name") or "-"
    created   = (p.get("createdate") or "")[:10]

    print(f"  Name          : {name} | Lifecycle: {lc} | Created: {created}")
    print(f"  Typeform      : {tf_display}")
    print(f"  Original src  : {orig_src} / {orig_d1}")
    print(f"  Latest src    : {latest} / {latest_d1}")
    print(f"  UTM           : source={utm_src} medium={utm_med} campaign={utm_camp}")
    print(f"  First convert : {first_cv}")
