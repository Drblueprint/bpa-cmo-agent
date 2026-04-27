"""
BPA CMO Agent - Ad-Level Report.
Pulls ad-level data (not just campaign) including creative hooks, CTR, CPL per ad.
Helps diagnose "which specific ads are working vs breaking."

Usage:
  python3 ad_level_report.py                # last 7 days, terminal
  python3 ad_level_report.py --days 14      # longer window
  python3 ad_level_report.py --filter rob   # only ads whose name/campaign contains 'rob'
  python3 ad_level_report.py --post         # publish to Google Chat
"""

import argparse
import json
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timedelta


def load_env(path: Path) -> dict:
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def http_get(url: str, params: dict = None):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def http_post_json(url: str, payload: dict):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def fb_ad_insights(token: str, account: str, preset: str) -> list:
    # Pull ad-level insights with video metrics
    all_data = []
    url = f"https://graph.facebook.com/v19.0/act_{account}/insights"
    params = {
        "date_preset": preset,
        "level": "ad",
        "fields": (
            "ad_name,campaign_name,adset_name,spend,impressions,clicks,ctr,cpc,"
            "reach,actions,video_thruplay_watched_actions,video_p25_watched_actions,"
            "video_play_actions"
        ),
        "access_token": token,
        "limit": 100,
    }
    status, body = http_get(url, params)
    if status >= 400:
        print(f"FB error {status}: {body}")
        return []
    all_data.extend(body.get("data", []))
    # Handle pagination
    paging = body.get("paging", {})
    next_url = paging.get("next")
    iter_count = 0
    while next_url and iter_count < 20:
        status, body = http_get(next_url)
        if status >= 400:
            break
        all_data.extend(body.get("data", []))
        next_url = body.get("paging", {}).get("next")
        iter_count += 1
    return all_data


def action_value(actions, action_type):
    if not actions:
        return 0.0
    for a in actions:
        if a.get("action_type") == action_type:
            return float(a.get("value", 0))
    return 0.0


def leads_of(actions):
    if not actions:
        return 0.0
    v = action_value(actions, "lead")
    if v:
        return v
    return action_value(actions, "offsite_conversion.fb_pixel_lead")


def video_3s(row):
    return action_value(row.get("video_3_sec_watched_actions"), "video_view")


def thruplay(row):
    return action_value(row.get("video_thruplay_watched_actions"), "video_view")


def hook_rate(row, impressions):
    """3-sec video views / impressions. Proxy for creative hook strength."""
    v3 = video_3s(row)
    return (v3 / impressions * 100) if impressions and v3 else 0


def build_ads(fb_rows: list) -> list:
    out = []
    for r in fb_rows:
        spend = float(r.get("spend", 0))
        impressions = int(r.get("impressions", 0))
        clicks = int(r.get("clicks", 0))
        leads = leads_of(r.get("actions"))
        out.append({
            "ad_name": r.get("ad_name", ""),
            "campaign": r.get("campaign_name", ""),
            "adset": r.get("adset_name", ""),
            "spend": spend,
            "impressions": impressions,
            "clicks": clicks,
            "leads": leads,
            "ctr": float(r.get("ctr", 0)),
            "hook_rate": hook_rate(r, impressions),
            "v3": video_3s(r),
            "thruplay": thruplay(r),
            "cpl": (spend / leads) if leads else None,
        })
    return out


def render_report(ads: list, window_days: int, filter_str: str = None) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=window_days)).strftime("%Y-%m-%d")

    filtered = ads
    if filter_str:
        f = filter_str.lower()
        filtered = [a for a in ads if f in a["ad_name"].lower() or f in a["campaign"].lower() or f in a["adset"].lower()]

    # Filter out zero-spend
    active = [a for a in filtered if a["spend"] > 10]

    total_spend = sum(a["spend"] for a in active)
    total_leads = sum(a["leads"] for a in active)

    L = []
    L.append("*BPA CMO Agent - Ad-Level Report*")
    L.append(f"_Window: {start} → {today} ({window_days} days)_")
    if filter_str:
        L.append(f"_Filter: '{filter_str}'_")
    L.append(f"_Ads active (>$10 spend): {len(active)}_")
    L.append(f"_Total spend: ${total_spend:,.0f} · Total leads: {total_leads:.0f}_")
    L.append("")

    # Top 10 by spend
    by_spend = sorted(active, key=lambda a: a["spend"], reverse=True)[:10]
    L.append("*Top 10 ads by spend*")
    for a in by_spend:
        cpl = f"CPL ${a['cpl']:,.0f}" if a["cpl"] else "no leads"
        hr = f"hook {a['hook_rate']:.1f}%" if a["hook_rate"] else "(no video data)"
        L.append(f"• {a['ad_name'][:60]} - ${a['spend']:,.0f}, {a['leads']:.0f} leads, {cpl}, CTR {a['ctr']:.2f}%, {hr}")
    L.append("")

    # Best hook rate (creative winners)
    hook_rows = [a for a in active if a["hook_rate"] > 0]
    if hook_rows:
        best_hook = sorted(hook_rows, key=lambda a: a["hook_rate"], reverse=True)[:5]
        L.append("*Best hook rate (creative wins the first 3 seconds)*")
        for a in best_hook:
            L.append(f"• {a['ad_name'][:60]} - hook {a['hook_rate']:.1f}%, CTR {a['ctr']:.2f}%, ${a['spend']:,.0f} spent")
        L.append("")

        worst_hook = sorted([a for a in hook_rows if a["spend"] > 100], key=lambda a: a["hook_rate"])[:5]
        L.append("*Worst hook rate with meaningful spend (broken creative)*")
        for a in worst_hook:
            L.append(f"• {a['ad_name'][:60]} - hook {a['hook_rate']:.1f}%, CTR {a['ctr']:.2f}%, ${a['spend']:,.0f} spent")
        L.append("")

    # Worst CPL with spend
    lead_rows = [a for a in active if a["leads"] > 0]
    if lead_rows:
        best_cpl = sorted(lead_rows, key=lambda a: a["cpl"])[:5]
        L.append("*Best CPL (what to scale)*")
        for a in best_cpl:
            L.append(f"• {a['ad_name'][:60]} - CPL ${a['cpl']:,.0f}, {a['leads']:.0f} leads, ${a['spend']:,.0f} spent")
        L.append("")

        worst_cpl = sorted(
            [a for a in lead_rows if a["spend"] > 100],
            key=lambda a: a["cpl"], reverse=True
        )[:5]
        L.append("*Worst CPL with spend (what to cut)*")
        for a in worst_cpl:
            L.append(f"• {a['ad_name'][:60]} - CPL ${a['cpl']:,.0f}, {a['leads']:.0f} leads, ${a['spend']:,.0f} spent")
        L.append("")

    # Zero-lead offenders
    zero = [a for a in active if a["leads"] == 0 and a["spend"] > 100]
    if zero:
        L.append("*Zero-lead ads burning >$100*")
        for a in sorted(zero, key=lambda a: a["spend"], reverse=True)[:10]:
            hr = f"hook {a['hook_rate']:.1f}%" if a["hook_rate"] else ""
            L.append(f"• {a['ad_name'][:60]} - ${a['spend']:,.0f} spent, 0 leads, CTR {a['ctr']:.2f}% {hr}")
        L.append("")

    # Diagnosis
    L.append("*Diagnostic*")
    if zero and sum(a["spend"] for a in zero) > 1000:
        L.append(f"CREATIVE OR TARGETING BROKEN on ${sum(a['spend'] for a in zero):,.0f} of zero-lead ads.")
        L.append("Next: check hook rates on the offenders. Low hook = creative. Good hook + no leads = landing page / offer.")
    elif hook_rows and sum(a["hook_rate"] for a in hook_rows) / max(len(hook_rows), 1) < 15:
        L.append("Average hook rate below 15%. Creative is weak across the account. New hooks needed.")
    else:
        L.append("No single dominant issue at ad-level. Check campaign-level (run weekly_report_v2.py).")

    return "\n".join(L)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--filter", type=str, default=None, help="Filter ads by substring match")
    p.add_argument("--post", action="store_true")
    args = p.parse_args()

    env = load_env(Path(__file__).parent /".env")
    preset_map = {7: "last_7d", 14: "last_14d", 28: "last_28d", 30: "last_30d", 90: "last_90d"}
    preset = preset_map.get(args.days, "last_7d")

    print(f"Pulling ad-level FB data ({args.days}d)...")
    rows = fb_ad_insights(env["FB_ADS_TOKEN"], env["FB_AD_ACCOUNT_ID"], preset)
    print(f"  {len(rows)} ads")

    ads = build_ads(rows)
    text = render_report(ads, args.days, args.filter)
    print("\n" + text + "\n")

    today = datetime.now().strftime("%Y-%m-%d")
    filter_tag = f"_{args.filter}" if args.filter else ""
    out = Path(__file__).parent /f"ad_level_{today}{filter_tag}.txt"
    out.write_text(text)
    print(f"Saved: {out}")

    if args.post:
        status, _ = http_post_json(env["GCHAT_CMO_WEBHOOK"], {"text": text})
        print(f"Google Chat post: HTTP {status}")
    else:
        print("(Not posted. Use --post to publish.)")


if __name__ == "__main__":
    main()
