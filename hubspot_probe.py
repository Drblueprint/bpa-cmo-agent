"""
HubSpot probe — validate Private App token + discover schema.
Checks: auth, pipelines, lifecycle stages, deal stages, contact properties,
UTM field presence, deal count, meeting count.
Pure stdlib.
"""

import json
import sys
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path


def load_env(path: Path) -> dict:
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def hs_get(path: str, token: str, params: dict = None):
    url = "https://api.hubapi.com" + path
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"error": "non-json", "raw": e.read().decode()[:500]}


def main():
    env = load_env(Path.home() / "Desktop" / "bpa-cmo-agent" / ".env")
    token = env.get("HUBSPOT_TOKEN")
    portal = env.get("HUBSPOT_PORTAL_ID")
    if not token:
        print("HUBSPOT_TOKEN missing from .env")
        sys.exit(1)

    print(f"Probing HubSpot portal {portal}")
    print("=" * 60)

    # 1. Auth check — access token info
    print("\n[1] Token info")
    status, body = hs_get(f"/oauth/v1/access-tokens/{token}", token)
    if status == 200:
        print(f"  Hub ID: {body.get('hub_id')}")
        print(f"  App ID: {body.get('app_id')}")
        print(f"  Scopes granted ({len(body.get('scopes', []))}):")
        for s in body.get('scopes', [])[:30]:
            print(f"    - {s}")
        if len(body.get('scopes', [])) > 30:
            print(f"    ... and {len(body.get('scopes', [])) - 30} more")
    else:
        print(f"  FAILED ({status}): {body}")

    # 2. Pipelines (deals)
    print("\n[2] Deal pipelines")
    status, body = hs_get("/crm/v3/pipelines/deals", token)
    if status == 200:
        for p in body.get("results", []):
            print(f"  Pipeline: {p.get('label')} (id={p.get('id')})")
            for st in p.get("stages", []):
                print(f"    └─ {st.get('label')} (id={st.get('id')}, probability={st.get('metadata', {}).get('probability')})")
    else:
        print(f"  FAILED ({status}): {body}")

    # 3. Lifecycle stages (contacts)
    print("\n[3] Contact lifecycle stages")
    status, body = hs_get("/crm/v3/properties/contacts/lifecyclestage", token)
    if status == 200:
        opts = body.get("options", [])
        for o in opts:
            print(f"  - {o.get('label')} (value={o.get('value')})")
    else:
        print(f"  FAILED ({status}): {body}")

    # 4. Contact properties — search for UTM / attribution fields
    print("\n[4] Attribution / UTM properties on contacts")
    status, body = hs_get("/crm/v3/properties/contacts", token)
    if status == 200:
        props = body.get("results", [])
        print(f"  Total contact properties: {len(props)}")
        utm_props = [p for p in props if any(tag in p.get("name", "").lower()
                     for tag in ("utm", "source", "campaign", "first_conversion", "recent_conversion", "original_source", "hs_analytics"))]
        print(f"  Attribution-related ({len(utm_props)}):")
        for p in utm_props[:40]:
            print(f"    - {p.get('name')} ({p.get('type')}): {p.get('label')}")
    else:
        print(f"  FAILED ({status}): {body}")

    # 5. Deal property highlights (amount, stage, close date, pipeline)
    print("\n[5] Key deal properties")
    status, body = hs_get("/crm/v3/properties/deals", token)
    if status == 200:
        props = body.get("results", [])
        keys = ("amount", "dealstage", "pipeline", "closedate", "createdate",
                "hs_analytics_source", "hs_analytics_source_data_1",
                "hs_analytics_source_data_2", "hs_deal_stage_probability",
                "dealtype", "hubspot_owner_id")
        found = {p.get("name"): p for p in props if p.get("name") in keys}
        for k in keys:
            if k in found:
                print(f"  ✓ {k}: {found[k].get('label')} ({found[k].get('type')})")
            else:
                print(f"  ✗ {k}: MISSING")

    # 6. Contact count
    print("\n[6] Totals")
    status, body = hs_get("/crm/v3/objects/contacts", token, {"limit": 1})
    if status == 200:
        print(f"  Contacts accessible (first page ok): {len(body.get('results', []))} sample returned")
        # Total contacts via search with no filter
        req = urllib.request.Request(
            "https://api.hubapi.com/crm/v3/objects/contacts/search",
            data=json.dumps({"limit": 1}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                b = json.loads(r.read().decode())
                print(f"  Total contacts in portal: {b.get('total'):,}")
        except Exception as e:
            print(f"  Contact count check failed: {e}")

    # Deal count
    req = urllib.request.Request(
        "https://api.hubapi.com/crm/v3/objects/deals/search",
        data=json.dumps({"limit": 1}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            b = json.loads(r.read().decode())
            print(f"  Total deals in portal: {b.get('total'):,}")
    except Exception as e:
        print(f"  Deal count check failed: {e}")

    # Meetings
    status, body = hs_get("/crm/v3/objects/meetings", token, {"limit": 1})
    if status == 200:
        print(f"  Meetings endpoint OK")
    elif status == 403:
        print(f"  Meetings endpoint: 403 (scope not granted)")
    else:
        print(f"  Meetings endpoint: {status}")

    print("\nDone.")


if __name__ == "__main__":
    main()
