"""
TheraRay Campaign Deep Pull
- Campaign ID: 52514514316265
- Apr 17-24 spend (7-day)
- Apr 1-24 spend (month-to-date)
- Ad set level breakdown
- Ad level breakdown
- Campaign delivery status (budget, effective_status)
- Hyros leads/clicks for same window
"""

import json
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime


def load_env(path: Path) -> dict:
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def fb_get(url: str, params: dict) -> dict:
    q = urllib.parse.urlencode(params)
    full = f"{url}?{q}"
    try:
        with urllib.request.urlopen(full, timeout=30) as r:
            return {"status": r.status, "body": json.loads(r.read().decode())}
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = {"raw": "non-json"}
        return {"status": e.code, "body": body}


def hyros_get(path: str, api_key: str, params: dict = None):
    base = "https://api.hyros.com/v1/api/v1.0"
    url = f"{base}{path}"
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"API-Key": api_key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = {"raw_error": "non-json"}
        return e.code, body


def get_action(actions, action_type):
    if not actions:
        return 0.0
    for a in actions:
        if a.get("action_type") == action_type:
            return float(a.get("value", 0))
    return 0.0


def main():
    env = load_env(Path.home() / "Desktop" / "bpa-cmo-agent" / ".env")
    token = env["FB_ADS_TOKEN"]
    account_id = env["FB_AD_ACCOUNT_ID"]
    hyros_key = env["HYROS_API_KEY"]

    CAMPAIGN_ID = "52514514316265"
    BASE = "https://graph.facebook.com/v19.0"

    print("=" * 70)
    print("THERARAY CAMPAIGN DEEP PULL")
    print(f"Campaign ID: {CAMPAIGN_ID}")
    print(f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # -------------------------------------------------------
    # 1. CAMPAIGN DELIVERY STATUS (budget, status, etc.)
    # -------------------------------------------------------
    print("\n--- SECTION 1: CAMPAIGN DELIVERY STATUS ---")
    fields = (
        "name,status,effective_status,daily_budget,lifetime_budget,"
        "budget_remaining,configured_status,start_time,stop_time"
    )
    r = fb_get(f"{BASE}/{CAMPAIGN_ID}", {
        "fields": fields,
        "access_token": token,
    })
    print(f"HTTP {r['status']}")
    campaign_info = r["body"]
    print(json.dumps(campaign_info, indent=2))

    # -------------------------------------------------------
    # 2. CAMPAIGN INSIGHTS — APR 17-24
    # -------------------------------------------------------
    print("\n--- SECTION 2: CAMPAIGN INSIGHTS APR 17-24 ---")
    r = fb_get(f"{BASE}/{CAMPAIGN_ID}/insights", {
        "time_range": json.dumps({"since": "2026-04-17", "until": "2026-04-24"}),
        "fields": "campaign_name,spend,impressions,clicks,ctr,cpc,reach,actions,cost_per_action_type,frequency",
        "access_token": token,
        "level": "campaign",
    })
    print(f"HTTP {r['status']}")
    apr17_24_data = r["body"].get("data", [])
    print(json.dumps(apr17_24_data, indent=2))

    # -------------------------------------------------------
    # 3. CAMPAIGN INSIGHTS — APR 1-24 (MTD)
    # -------------------------------------------------------
    print("\n--- SECTION 3: CAMPAIGN INSIGHTS APR 1-24 (MTD) ---")
    r = fb_get(f"{BASE}/{CAMPAIGN_ID}/insights", {
        "time_range": json.dumps({"since": "2026-04-01", "until": "2026-04-24"}),
        "fields": "campaign_name,spend,impressions,clicks,ctr,cpc,reach,actions,cost_per_action_type",
        "access_token": token,
        "level": "campaign",
    })
    print(f"HTTP {r['status']}")
    apr_mtd_data = r["body"].get("data", [])
    print(json.dumps(apr_mtd_data, indent=2))

    # -------------------------------------------------------
    # 4. DAY-BY-DAY BREAKDOWN APR 17-24
    # -------------------------------------------------------
    print("\n--- SECTION 4: DAY-BY-DAY SPEND APR 17-24 ---")
    r = fb_get(f"{BASE}/{CAMPAIGN_ID}/insights", {
        "time_range": json.dumps({"since": "2026-04-17", "until": "2026-04-24"}),
        "time_increment": "1",
        "fields": "date_start,date_stop,spend,impressions,clicks,actions",
        "access_token": token,
        "level": "campaign",
    })
    print(f"HTTP {r['status']}")
    daily_data = r["body"].get("data", [])
    print(json.dumps(daily_data, indent=2))
    if daily_data:
        print("\nDaily summary:")
        for d in daily_data:
            leads = get_action(d.get("actions"), "lead")
            if leads == 0:
                leads = get_action(d.get("actions"), "offsite_conversion.fb_pixel_lead")
            print(f"  {d.get('date_start')}: spend=${float(d.get('spend',0)):.2f}, impressions={d.get('impressions','0')}, clicks={d.get('clicks','0')}, leads={leads:.0f}")

    # -------------------------------------------------------
    # 5. AD SET LEVEL — APR 17-24
    # -------------------------------------------------------
    print("\n--- SECTION 5: AD SET LEVEL APR 17-24 ---")
    r = fb_get(f"{BASE}/{CAMPAIGN_ID}/insights", {
        "time_range": json.dumps({"since": "2026-04-17", "until": "2026-04-24"}),
        "fields": "adset_name,adset_id,spend,impressions,clicks,ctr,actions",
        "access_token": token,
        "level": "adset",
    })
    print(f"HTTP {r['status']}")
    adset_data = r["body"].get("data", [])
    print(json.dumps(adset_data, indent=2))
    if adset_data:
        print("\nAd set summary:")
        total_adset_spend = 0
        for a in sorted(adset_data, key=lambda x: float(x.get("spend", 0)), reverse=True):
            leads = get_action(a.get("actions"), "lead")
            if leads == 0:
                leads = get_action(a.get("actions"), "offsite_conversion.fb_pixel_lead")
            sp = float(a.get("spend", 0))
            total_adset_spend += sp
            cpl = sp / leads if leads else None
            cpl_str = f"CPL=${cpl:.2f}" if cpl else "no leads"
            print(f"  [{a.get('adset_id')}] {a.get('adset_name', 'n/a')[:60]}: spend=${sp:.2f}, leads={leads:.0f}, {cpl_str}")
        print(f"  TOTAL across ad sets: ${total_adset_spend:.2f}")

    # -------------------------------------------------------
    # 6. AD SET DELIVERY STATUS (are any paused?)
    # -------------------------------------------------------
    print("\n--- SECTION 6: AD SET DELIVERY STATUS ---")
    r = fb_get(f"{BASE}/{CAMPAIGN_ID}/adsets", {
        "fields": "name,status,effective_status,daily_budget,budget_remaining,configured_status",
        "access_token": token,
        "limit": 50,
    })
    print(f"HTTP {r['status']}")
    adsets_status = r["body"].get("data", [])
    print(json.dumps(adsets_status, indent=2))
    if adsets_status:
        print("\nAd set status summary:")
        for a in adsets_status:
            budget = a.get("daily_budget", "N/A")
            budget_str = f"${int(budget)/100:.2f}/day" if isinstance(budget, (int, str)) and str(budget).isdigit() else f"budget={budget}"
            print(f"  {a.get('name','n/a')[:60]}: status={a.get('status')}, effective={a.get('effective_status')}, {budget_str}")

    # -------------------------------------------------------
    # 7. AD LEVEL — APR 17-24
    # -------------------------------------------------------
    print("\n--- SECTION 7: AD LEVEL APR 17-24 ---")
    r = fb_get(f"{BASE}/{CAMPAIGN_ID}/insights", {
        "time_range": json.dumps({"since": "2026-04-17", "until": "2026-04-24"}),
        "fields": "ad_name,ad_id,adset_name,spend,impressions,clicks,ctr,actions",
        "access_token": token,
        "level": "ad",
    })
    print(f"HTTP {r['status']}")
    ad_data = r["body"].get("data", [])
    print(json.dumps(ad_data, indent=2))
    if ad_data:
        print("\nAd level summary:")
        for a in sorted(ad_data, key=lambda x: float(x.get("spend", 0)), reverse=True):
            leads = get_action(a.get("actions"), "lead")
            if leads == 0:
                leads = get_action(a.get("actions"), "offsite_conversion.fb_pixel_lead")
            sp = float(a.get("spend", 0))
            cpl = sp / leads if leads else None
            cpl_str = f"CPL=${cpl:.2f}" if cpl else "no leads"
            print(f"  [{a.get('ad_id')}] {a.get('ad_name','n/a')[:60]}: spend=${sp:.2f}, leads={leads:.0f}, {cpl_str}, CTR={float(a.get('ctr',0)):.2f}%")

    # -------------------------------------------------------
    # 8. AD DELIVERY STATUS (which ads are paused?)
    # -------------------------------------------------------
    print("\n--- SECTION 8: AD DELIVERY STATUS ---")
    r = fb_get(f"{BASE}/{CAMPAIGN_ID}/ads", {
        "fields": "name,status,effective_status,adset_id",
        "access_token": token,
        "limit": 100,
    })
    print(f"HTTP {r['status']}")
    ads_status = r["body"].get("data", [])
    print(json.dumps(ads_status, indent=2))
    if ads_status:
        active = [a for a in ads_status if a.get("effective_status") == "ACTIVE"]
        paused = [a for a in ads_status if a.get("effective_status") in ("PAUSED", "ADSET_PAUSED", "CAMPAIGN_PAUSED")]
        print(f"\nActive ads: {len(active)}")
        print(f"Paused/inactive ads: {len(paused)}")

    # -------------------------------------------------------
    # 9. HYROS LEADS APR 17-24
    # -------------------------------------------------------
    print("\n--- SECTION 9: HYROS LEADS APR 17-24 ---")
    status, body = hyros_get("/leads", hyros_key, {
        "fromDate": "2026-04-17",
        "toDate": "2026-04-24",
        "pageSize": 50,
    })
    print(f"HTTP {status}")
    hyros_leads = body.get("result") or body.get("data") or []
    print(f"Total Hyros leads returned: {len(hyros_leads)}")
    # Filter to TheraRay if source field exists
    theraray_leads = []
    for lead in hyros_leads:
        lead_str = json.dumps(lead).lower()
        if "theraray" in lead_str or "thera" in lead_str:
            theraray_leads.append(lead)
    print(f"TheraRay-attributed leads: {len(theraray_leads)}")
    if theraray_leads:
        print(json.dumps(theraray_leads, indent=2, default=str))
    elif hyros_leads:
        print("Sample lead (first):")
        print(json.dumps(hyros_leads[0], indent=2, default=str))

    # -------------------------------------------------------
    # 10. HYROS CALLS APR 17-24
    # -------------------------------------------------------
    print("\n--- SECTION 10: HYROS CALLS APR 17-24 ---")
    status, body = hyros_get("/calls", hyros_key, {
        "fromDate": "2026-04-17",
        "toDate": "2026-04-24",
        "pageSize": 50,
    })
    print(f"HTTP {status}")
    hyros_calls = body.get("result") or body.get("data") or []
    print(f"Total Hyros calls returned: {len(hyros_calls)}")
    theraray_calls = []
    for call in hyros_calls:
        call_str = json.dumps(call).lower()
        if "theraray" in call_str or "thera" in call_str:
            theraray_calls.append(call)
    print(f"TheraRay-attributed calls: {len(theraray_calls)}")

    # Show all call sources for context
    if hyros_calls:
        print("All calls with sources:")
        for c in hyros_calls[:20]:
            fs = c.get("firstSource", {})
            ls = c.get("lastSource", {})
            fs_name = fs.get("name") or fs.get("source") or str(fs)[:60] if isinstance(fs, dict) else str(fs)[:60]
            ls_name = ls.get("name") or ls.get("source") or str(ls)[:60] if isinstance(ls, dict) else str(ls)[:60]
            print(f"  call {c.get('id','?')}: firstSource={fs_name}, lastSource={ls_name}, qualified={c.get('qualified')}")

    # -------------------------------------------------------
    # 11. HYROS APR 1-24 MTD
    # -------------------------------------------------------
    print("\n--- SECTION 11: HYROS LEADS APR 1-24 (MTD) ---")
    status, body = hyros_get("/leads", hyros_key, {
        "fromDate": "2026-04-01",
        "toDate": "2026-04-24",
        "pageSize": 100,
    })
    print(f"HTTP {status}")
    hyros_leads_mtd = body.get("result") or body.get("data") or []
    print(f"Total Hyros leads MTD: {len(hyros_leads_mtd)}")

    print("\n" + "=" * 70)
    print("PULL COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
