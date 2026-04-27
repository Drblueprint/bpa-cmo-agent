"""
BPA Paid Media — Apr 17-24, 2026 campaign-level pull.
Fetches FB Ads insights by campaign for exact date range.
Also pulls Hyros leads for same window.
No Google Chat posting — analysis only.
"""

import json
import urllib.parse
import urllib.request
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


def http_get(url: str, params: dict) -> dict:
    q = urllib.parse.urlencode(params)
    full = f"{url}?{q}"
    req = urllib.request.Request(full)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  HTTP error {e.code}: {body[:400]}")
        return {}


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


def get_action(actions, *types):
    if not actions:
        return 0.0
    for t in types:
        for a in actions:
            if a.get("action_type") == t:
                return float(a.get("value", 0))
    return 0.0


def main():
    env_path = Path("/Users/aarongumm/Desktop/bpa-cmo-agent/.env")
    env = load_env(env_path)
    token = env["FB_ADS_TOKEN"]
    account_id = env["FB_AD_ACCOUNT_ID"]
    hyros_key = env["HYROS_API_KEY"]

    since = "2026-04-17"
    until = "2026-04-24"

    # ── FB Ads campaign-level pull ──────────────────────────────────────────
    print(f"\nFetching FB Ads campaign insights: {since} to {until}")
    url = f"https://graph.facebook.com/v19.0/act_{account_id}/insights"
    params = {
        "time_range[since]": since,
        "time_range[until]": until,
        "level": "campaign",
        "fields": (
            "campaign_name,campaign_id,"
            "spend,impressions,reach,clicks,ctr,cpc,cpm,"
            "actions,cost_per_action_type"
        ),
        "access_token": token,
        "limit": 100,
    }
    data = http_get(url, params)
    campaigns = data.get("data", [])
    print(f"  Campaigns returned: {len(campaigns)}")

    # Also fetch ad-level for CPM + CTR breakdown
    print(f"\nFetching FB Ads ad-level insights: {since} to {until}")
    ad_params = {
        "time_range[since]": since,
        "time_range[until]": until,
        "level": "ad",
        "fields": (
            "campaign_name,adset_name,ad_name,ad_id,"
            "spend,impressions,reach,clicks,ctr,cpc,cpm,"
            "actions,cost_per_action_type"
        ),
        "access_token": token,
        "limit": 200,
    }
    ad_data = http_get(url, ad_params)
    ads = ad_data.get("data", [])
    print(f"  Ads returned: {len(ads)}")

    # ── Hyros leads pull ────────────────────────────────────────────────────
    print(f"\nFetching Hyros leads: {since} to {until}")
    status, hyros_body = hyros_get("/leads", hyros_key, {
        "fromDate": since,
        "toDate": until,
        "pageSize": 200,
    })
    print(f"  Hyros leads status: {status}")
    hyros_leads = []
    if 200 <= status < 300:
        hyros_leads = hyros_body.get("result") or hyros_body.get("data") or []
    print(f"  Hyros leads count: {len(hyros_leads)}")

    # Hyros calls
    print(f"\nFetching Hyros calls: {since} to {until}")
    status2, calls_body = hyros_get("/calls", hyros_key, {
        "fromDate": since,
        "toDate": until,
        "pageSize": 200,
    })
    hyros_calls = []
    if 200 <= status2 < 300:
        hyros_calls = calls_body.get("result") or calls_body.get("data") or []
    print(f"  Hyros calls count: {len(hyros_calls)}")

    # ── Save raw ────────────────────────────────────────────────────────────
    out = {
        "fb_campaigns": campaigns,
        "fb_ads": ads,
        "hyros_leads": hyros_leads,
        "hyros_calls": hyros_calls,
        "hyros_lead_sample": hyros_leads[:2] if hyros_leads else [],
        "hyros_call_sample": hyros_calls[:2] if hyros_calls else [],
    }
    dump_path = Path("/Users/aarongumm/Desktop/bpa-cmo-agent/apr17_24_raw.json")
    dump_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nRaw data saved: {dump_path}")

    # ── Print campaign table ────────────────────────────────────────────────
    print("\n" + "="*90)
    print(f"CAMPAIGN-LEVEL SUMMARY  Apr 17–24, 2026")
    print("="*90)
    print(f"{'Campaign':<42} {'Spend':>8} {'Impr':>8} {'Reach':>8} {'CPM':>7} {'Clicks':>7} {'CTR':>6} {'CPC':>7} {'Leads':>6} {'CPL':>8}")
    print("-"*90)

    grand = dict(spend=0, impr=0, reach=0, clicks=0, leads=0)
    enriched = []
    for c in campaigns:
        name = c.get("campaign_name", "?")[:41]
        spend = float(c.get("spend", 0))
        impr = int(c.get("impressions", 0))
        reach = int(c.get("reach", 0))
        cpm = float(c.get("cpm", 0))
        clicks = int(c.get("clicks", 0))
        ctr = float(c.get("ctr", 0))
        cpc = float(c.get("cpc", 0)) if c.get("cpc") else (spend/clicks if clicks else 0)
        actions = c.get("actions") or []
        leads = get_action(actions, "lead", "offsite_conversion.fb_pixel_lead")
        cpl = spend / leads if leads else None
        cpl_str = f"${cpl:,.2f}" if cpl else "---"
        print(f"{name:<42} ${spend:>7,.0f} {impr:>8,} {reach:>8,} ${cpm:>5.2f} {clicks:>7,} {ctr:>5.2f}% ${cpc:>5.2f} {leads:>6.0f} {cpl_str:>8}")
        grand["spend"] += spend
        grand["impr"] += impr
        grand["reach"] += reach
        grand["clicks"] += clicks
        grand["leads"] += leads
        enriched.append({"name": c.get("campaign_name","?"), "spend": spend, "impr": impr,
                         "reach": reach, "cpm": cpm, "clicks": clicks, "ctr": ctr,
                         "cpc": cpc, "leads": leads, "cpl": cpl})

    print("-"*90)
    bl_ctr = grand["clicks"]/grand["impr"]*100 if grand["impr"] else 0
    bl_cpc = grand["spend"]/grand["clicks"] if grand["clicks"] else 0
    bl_cpl = grand["spend"]/grand["leads"] if grand["leads"] else 0
    bl_cpl_str = f"${bl_cpl:,.2f}" if grand["leads"] else "---"
    print(f"{'TOTALS / BLENDED':<42} ${grand['spend']:>7,.0f} {grand['impr']:>8,} {grand['reach']:>8,} {'---':>7} {grand['clicks']:>7,} {bl_ctr:>5.2f}% ${bl_cpc:>5.2f} {grand['leads']:>6.0f} {bl_cpl_str:>8}")

    # ── CTR up / Leads down flag ────────────────────────────────────────────
    print("\n" + "="*90)
    print("POST-CLICK CONVERSION BREAK DIAGNOSIS")
    print("  (CTR high but leads low = traffic reaching page but not converting)")
    print("="*90)
    avg_ctr = sum(e["ctr"] for e in enriched) / len(enriched) if enriched else 0
    for e in sorted(enriched, key=lambda x: x["ctr"], reverse=True):
        lc = e["leads"]
        flag = ""
        if e["ctr"] > avg_ctr and lc == 0:
            flag = "  <<< CTR UP, ZERO LEADS — POST-CLICK BREAK CONFIRMED"
        elif e["ctr"] > avg_ctr and e["cpl"] and e["cpl"] > 200:
            flag = "  <<< CTR HIGH, CPL DEGRADED — PARTIAL BREAK"
        cpl_disp = ('$' + '{:,.0f}'.format(e['cpl'])) if e['cpl'] else '---'
        print(f"  CTR {e['ctr']:.2f}%  Leads {lc:.0f}  CPL {cpl_disp}  |  {e['name'][:50]}{flag}")

    # ── Hyros summary ───────────────────────────────────────────────────────
    print("\n" + "="*90)
    print(f"HYROS ATTRIBUTION  Apr 17–24, 2026")
    print("="*90)
    print(f"  Total leads tracked in Hyros: {len(hyros_leads)}")
    print(f"  Total calls tracked in Hyros: {len(hyros_calls)}")

    # Source breakdown from Hyros leads
    source_counts = {}
    for lead in hyros_leads:
        src = None
        if isinstance(lead.get("firstSource"), dict):
            src = lead["firstSource"].get("name") or lead["firstSource"].get("source") or "unknown"
        elif isinstance(lead.get("firstSource"), str):
            src = lead["firstSource"]
        else:
            src = "no source"
        source_counts[src] = source_counts.get(src, 0) + 1
    if source_counts:
        print("  Lead sources (Hyros):")
        for src, cnt in sorted(source_counts.items(), key=lambda x: -x[1]):
            print(f"    {src}: {cnt}")

    # Call source breakdown
    call_source_counts = {}
    for call in hyros_calls:
        src = None
        if isinstance(call.get("firstSource"), dict):
            src = call["firstSource"].get("name") or call["firstSource"].get("source") or "unknown"
        elif isinstance(call.get("firstSource"), str):
            src = call["firstSource"]
        else:
            src = "no source"
        call_source_counts[src] = call_source_counts.get(src, 0) + 1
    if call_source_counts:
        print("  Call sources (Hyros):")
        for src, cnt in sorted(call_source_counts.items(), key=lambda x: -x[1]):
            print(f"    {src}: {cnt}")

    # Hyros CPL estimate
    total_spend = grand["spend"]
    hyros_lead_count = len(hyros_leads)
    if hyros_lead_count and total_spend:
        print(f"  Hyros CPL (all-in, estimated): ${total_spend/hyros_lead_count:,.2f}")

    print("\nDone.")


if __name__ == "__main__":
    main()
