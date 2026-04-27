"""
BPA CMO Agent - Ad-Hoc Query Tool.
Terminal-driven "ask-me-anything" for CMO-level questions about paid media.

Usage:
  python3 cmo_query.py "how did Dr. Jo do last 14 days?"
  python3 cmo_query.py "what's the best CPL this week?"
  python3 cmo_query.py "chiro vs PT Recovery last 30"
  python3 cmo_query.py "show me Dr. Rob"
  python3 cmo_query.py "zero-lead ads"
  python3 cmo_query.py --days 28 "TheraRay"

Matches keywords in the query to segments, talents, and report intents. Pulls
fresh FB + Hyros data and returns a CMO-format answer to the terminal.
"""

import argparse
import json
import re
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timedelta


# ---------- Shared helpers (copied in so this script is standalone) ----------

def load_env(path: Path) -> dict:
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def http_get(url: str, params: dict = None, headers: dict = None):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"error": str(e)}


def fb_ad_insights(token: str, account: str, preset: str) -> list:
    all_data = []
    url = f"https://graph.facebook.com/v19.0/act_{account}/insights"
    params = {
        "date_preset": preset,
        "level": "ad",
        "fields": (
            "ad_name,campaign_name,adset_name,spend,impressions,clicks,ctr,cpc,"
            "reach,actions,video_play_actions,video_p25_watched_actions"
        ),
        "access_token": token,
        "limit": 100,
    }
    status, body = http_get(url, params)
    if status >= 400:
        print(f"FB error {status}: {body}")
        return []
    all_data.extend(body.get("data", []))
    next_url = body.get("paging", {}).get("next")
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


def hook_rate(row, impressions):
    # Proxy: video plays / impressions (3-sec-views field was deprecated by FB).
    vp = action_value(row.get("video_play_actions"), "video_view")
    return (vp / impressions * 100) if impressions and vp else 0


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
            "cpl": (spend / leads) if leads else None,
        })
    return out


# ---------- Intent parsing ----------

TALENTS = {
    "dr. jo":  ["dr jo", "dr. jo", "jo ", "jo-", "jo_"],
    "dr. rob": ["dr rob", "dr. rob", "rob ", "rob-", "rob_"],
    "dr. jason": ["dr jason", "dr. jason", "jason"],
    "dr. maas": ["dr maas", "dr. maas", "maas"],
    "aaron gumm": ["aaron", "gumm"],
    "kristin bott": ["kristin", "bott"],
}

VERTICALS = {
    "chiro": ["chiro", "chiropract"],
    "pt recovery": ["pt recovery", "pt ", "physical therapy", "ptr"],
    "theraray": ["theraray", "thera ray", "thera-ray"],
    "emx": ["emx", "vemx"],
    "retargeting": ["retarget", "warm", "rtg"],
}


def match_any(haystack: str, needles: list) -> bool:
    h = haystack.lower()
    return any(n in h for n in needles)


def classify_ad(ad: dict) -> dict:
    """Tag an ad row with talent + vertical based on name strings."""
    blob = f"{ad['ad_name']} {ad['campaign']} {ad['adset']}".lower()
    talent = None
    for name, needles in TALENTS.items():
        if match_any(blob, needles):
            talent = name
            break
    vertical = None
    for name, needles in VERTICALS.items():
        if match_any(blob, needles):
            vertical = name
            break
    return {"talent": talent, "vertical": vertical}


def parse_days(query: str, default: int) -> int:
    m = re.search(r"(\d{1,3})\s*d(?:ay)?s?", query.lower())
    if m:
        return int(m.group(1))
    if "last 7" in query.lower() or "this week" in query.lower():
        return 7
    if "last 14" in query.lower() or "2 weeks" in query.lower():
        return 14
    if "last 30" in query.lower() or "last month" in query.lower():
        return 30
    if "last 90" in query.lower() or "quarter" in query.lower():
        return 90
    return default


def pick_preset(days: int) -> str:
    return {7: "last_7d", 14: "last_14d", 28: "last_28d",
            30: "last_30d", 90: "last_90d"}.get(days, "last_7d")


def classify_intent(query: str) -> dict:
    q = query.lower()
    intent = {
        "talent": None,
        "vertical": None,
        "show_best_cpl": any(k in q for k in ["best cpl", "what to scale", "winners", "best ads"]),
        "show_worst_cpl": any(k in q for k in ["worst cpl", "what to cut", "losers", "broken"]),
        "show_zero_leads": any(k in q for k in ["zero lead", "no leads", "0 lead", "burning"]),
        "show_hooks": any(k in q for k in ["hook", "creative", "video"]),
        "compare": " vs " in q or " versus " in q,
    }
    for name, needles in TALENTS.items():
        if match_any(q, needles):
            intent["talent"] = name
            break
    for name, needles in VERTICALS.items():
        if match_any(q, needles):
            intent["vertical"] = name
            break
    return intent


# ---------- Answer rendering ----------

def summarize_rows(rows: list, label: str) -> list:
    spend = sum(r["spend"] for r in rows)
    leads = sum(r["leads"] for r in rows)
    clicks = sum(r["clicks"] for r in rows)
    impressions = sum(r["impressions"] for r in rows)
    cpl = (spend / leads) if leads else None
    ctr = (clicks / impressions * 100) if impressions else 0
    L = [f"*{label}*"]
    L.append(f"  Ads: {len(rows)}  Spend: ${spend:,.0f}  Leads: {leads:.0f}")
    if cpl:
        L.append(f"  CPL: ${cpl:,.0f}  CTR: {ctr:.2f}%")
    else:
        L.append(f"  CPL: -(no leads)  CTR: {ctr:.2f}%")
    return L


def render_answer(query: str, ads: list, days: int, intent: dict) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # Tag every ad
    for a in ads:
        a.update(classify_ad(a))

    # Active spend filter
    active = [a for a in ads if a["spend"] > 10]

    # Scope filter
    scope = active
    scope_label = "All ads"
    if intent["talent"]:
        scope = [a for a in active if a["talent"] == intent["talent"]]
        scope_label = f"{intent['talent'].title()}"
    elif intent["vertical"]:
        scope = [a for a in active if a["vertical"] == intent["vertical"]]
        scope_label = f"{intent['vertical'].title()}"

    L = []
    L.append(f"*BPA CMO Query* -'{query}'")
    L.append(f"_Window: {start} → {today} ({days} days) · Scope: {scope_label}_")
    L.append("")

    if not scope:
        L.append("No ads matched that scope with >$10 spend in this window.")
        return "\n".join(L)

    # Headline summary
    L.extend(summarize_rows(scope, f"Headline -{scope_label}"))
    L.append("")

    # Compare mode: talent A vs B or vertical A vs B
    if intent["compare"]:
        parts = re.split(r"\s+vs\s+|\s+versus\s+", query.lower())
        groups = []
        for p in parts:
            key = p.strip()
            matched = [a for a in active if key in f"{a['ad_name']} {a['campaign']} {a['adset']}".lower()]
            if matched:
                groups.append((key, matched))
        if len(groups) >= 2:
            L.append("*Comparison*")
            for key, rows in groups:
                L.extend(summarize_rows(rows, key.title()))
            L.append("")

    # Best CPL
    lead_rows = [a for a in scope if a["leads"] > 0]
    if lead_rows and (intent["show_best_cpl"] or not any(
        [intent["show_worst_cpl"], intent["show_zero_leads"], intent["show_hooks"]]
    )):
        best = sorted(lead_rows, key=lambda a: a["cpl"])[:5]
        L.append("*Best CPL (scale candidates)*")
        for a in best:
            L.append(f"• {a['ad_name'][:55]} - CPL ${a['cpl']:,.0f}, {a['leads']:.0f} leads, ${a['spend']:,.0f} spent")
        L.append("")

    # Worst CPL
    if lead_rows and intent["show_worst_cpl"]:
        worst = sorted([a for a in lead_rows if a["spend"] > 100],
                       key=lambda a: a["cpl"], reverse=True)[:5]
        L.append("*Worst CPL with spend (cut candidates)*")
        for a in worst:
            L.append(f"• {a['ad_name'][:55]} - CPL ${a['cpl']:,.0f}, {a['leads']:.0f} leads, ${a['spend']:,.0f} spent")
        L.append("")

    # Zero-lead offenders
    if intent["show_zero_leads"] or not lead_rows:
        zero = [a for a in scope if a["leads"] == 0 and a["spend"] > 100]
        if zero:
            L.append("*Zero-lead ads burning >$100*")
            for a in sorted(zero, key=lambda a: a["spend"], reverse=True)[:10]:
                L.append(f"• {a['ad_name'][:55]} - ${a['spend']:,.0f}, CTR {a['ctr']:.2f}%, hook {a['hook_rate']:.1f}%")
            L.append("")

    # Hook analysis
    if intent["show_hooks"]:
        hook_rows = [a for a in scope if a["hook_rate"] > 0]
        if hook_rows:
            best = sorted(hook_rows, key=lambda a: a["hook_rate"], reverse=True)[:5]
            L.append("*Best hook rate*")
            for a in best:
                L.append(f"• {a['ad_name'][:55]} - hook {a['hook_rate']:.1f}%, CTR {a['ctr']:.2f}%, ${a['spend']:,.0f}")
            L.append("")

    # CMO verdict
    L.append("*Verdict*")
    spend = sum(a["spend"] for a in scope)
    leads = sum(a["leads"] for a in scope)
    cpl = (spend / leads) if leads else None
    if cpl is None:
        L.append(f"Scope spent ${spend:,.0f} and produced 0 leads. **Cut or rebuild.**")
    elif cpl > 300:
        L.append(f"CPL ${cpl:,.0f} is above target. Diagnose: hook rate → CTR → CPL.")
    elif cpl < 100:
        L.append(f"CPL ${cpl:,.0f} is strong. **Scale winners; keep creative fresh.**")
    else:
        L.append(f"CPL ${cpl:,.0f} is in normal band. Look for creative to scale.")
    return "\n".join(L)


# ---------- Main ----------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("query", nargs="+", help="Natural language question")
    p.add_argument("--days", type=int, default=None, help="Override window (days)")
    args = p.parse_args()

    query = " ".join(args.query)
    days = args.days or parse_days(query, default=7)
    preset = pick_preset(days)
    intent = classify_intent(query)

    env = load_env(Path(__file__).parent /".env")
    print(f"Query: {query}")
    print(f"Window: {days}d ({preset}) · Talent={intent['talent']} · Vertical={intent['vertical']}")
    print("Pulling FB ad data...")
    rows = fb_ad_insights(env["FB_ADS_TOKEN"], env["FB_AD_ACCOUNT_ID"], preset)
    print(f"  {len(rows)} ad rows")

    ads = build_ads(rows)
    text = render_answer(query, ads, days, intent)
    print("\n" + text + "\n")


if __name__ == "__main__":
    main()
