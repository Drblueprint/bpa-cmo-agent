import sys, json
sys.path.insert(0, r"C:\Users\kxbox\OneDrive\Desktop\bpa-cmo-agent")
from weekly_report_v2 import load_env, http_get
from pathlib import Path

env = load_env(Path(r"C:\Users\kxbox\OneDrive\Desktop\bpa-cmo-agent\.env"))
token = env["FB_ADS_TOKEN"]
account = env["FB_AD_ACCOUNT_ID"]

target_ids = {"6579974167061", "6499555460461", "6895604717661"}

# Pull all adsets with every status
after = None
found = {}
page = 0
while page < 30:
    params = {
        "fields": "id,name,effective_status",
        "effective_status": json.dumps(["ACTIVE", "PAUSED", "ARCHIVED", "DELETED"]),
        "limit": 200,
        "access_token": token,
    }
    if after:
        params["after"] = after
    status, body = http_get(
        f"https://graph.facebook.com/v19.0/act_{account}/adsets",
        params,
    )
    batch = body.get("data", [])
    print(f"Page {page+1}: HTTP {status}, {len(batch)} adsets")
    for a in batch:
        aid = str(a.get("id", ""))
        if aid in target_ids:
            found[aid] = a.get("name", "")
            print(f"  FOUND {aid}: {a.get('name','')} [{a.get('effective_status','')}]")
    after = ((body.get("paging") or {}).get("cursors") or {}).get("after")
    if not after or not batch:
        break
    page += 1

print(f"\nTarget IDs found: {found}")
missing = target_ids - set(found.keys())
print(f"Still missing: {missing}")

# Try direct node lookup on missing ones
for oid in missing:
    s, b = http_get(
        f"https://graph.facebook.com/v19.0/{oid}",
        {"fields": "id,name,effective_status,campaign_id", "access_token": token}
    )
    print(f"Direct lookup {oid}: HTTP {s} -> {b}")
