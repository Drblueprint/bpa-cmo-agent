"""
BPA CMO Agent — Weekly Report v2.
Combines FB Ads + Hyros attribution into a reconciled, segment-aware report.
Default: terminal output. Pass --post to publish to Google Chat.
Pure stdlib.
"""

import argparse
import json
import sys
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict


# ---------- shared helpers ----------

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
            return e.code, {"error": "non-json"}


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


# ---------- Facebook Ads ----------

def fb_insights(token: str, account: str, date_preset: str = "last_7d") -> list:
    status, body = http_get(
        f"https://graph.facebook.com/v19.0/act_{account}/insights",
        {
            "date_preset": date_preset,
            "level": "campaign",
            "fields": "campaign_name,campaign_id,spend,impressions,clicks,ctr,cpc,reach,actions",
            "access_token": token,
            "limit": 200,
        },
    )
    if status >= 400:
        return []
    return body.get("data", [])


def fb_leads_of(actions):
    if not actions:
        return 0.0
    for a in actions:
        if a.get("action_type") == "lead":
            return float(a.get("value", 0))
    for a in actions:
        if a.get("action_type") == "offsite_conversion.fb_pixel_lead":
            return float(a.get("value", 0))
    return 0.0


# ---------- Hyros ----------

def hyros_get(path: str, key: str, params: dict = None):
    base = "https://api.hyros.com/v1/api/v1.0"
    return http_get(base + path, params, {"API-Key": key, "Accept": "application/json"})


def hyros_paginate(path: str, key: str, params: dict, max_pages: int = 20) -> list:
    """Walk Hyros pagination until empty or max_pages."""
    results = []
    page = 1
    while page <= max_pages:
        p = dict(params or {})
        p["page"] = page
        p["pageSize"] = p.get("pageSize", 100)
        status, body = hyros_get(path, key, p)
        if status >= 400:
            break
        batch = body.get("result") or body.get("data") or []
        if not batch:
            break
        results.extend(batch)
        if len(batch) < p["pageSize"]:
            break
        page += 1
    return results


def hyros_attributed_calls(key: str, from_date: str, to_date: str) -> list:
    """Pull all calls with source attribution in window."""
    return hyros_paginate(
        "/calls", key, {"fromDate": from_date, "toDate": to_date}
    )


def hyros_leads(key: str, from_date: str, to_date: str) -> list:
    return hyros_paginate(
        "/leads", key, {"fromDate": from_date, "toDate": to_date}
    )


# ---------- Segmentation ----------

def segment_of(name: str) -> str:
    n = (name or "").lower()
    if "theraray" in n:
        return "TheraRay"
    if "pt" in n or "recovery" in n:
        return "PT Recovery"
    if "emx" in n or "fort worth" in n or "vemx" in n:
        return "EMX / Event"
    if "retargeting" in n or "testimonials" in n:
        return "Retargeting"
    if "chiro" in n:
        return "Chiro"
    return "Other"


def talent_of(name: str) -> str:
    n = (name or "").lower()
    talents = [
        ("dr jo", "Dr. Jo"),
        ("dr. jo", "Dr. Jo"),
        ("dr rob", "Dr. Rob"),
        ("dr. rob", "Dr. Rob"),
        ("dr jason", "Dr. Jason"),
        ("dr. jason", "Dr. Jason"),
        ("dr maas", "Dr. Maas"),
        ("dr. maas", "Dr. Maas"),
        ("gumm", "Aaron Gumm"),
    ]
    for key, label in talents:
        if key in n:
            return label
    return "—"


# ---------- Reconciliation ----------

def build_campaign_rows(fb_campaigns: list, hyros_calls: list) -> list:
    """Merge FB campaign-level with Hyros call-level attribution."""
    # Index hyros calls by FB campaign name (from firstSource.category.name or similar)
    hyros_by_campaign = defaultdict(lambda: {"calls": 0, "qualified": 0, "sources": set()})
    for c in hyros_calls:
        # Use lastSource category (last-touch campaign attribution)
        for src_key in ("lastSource", "firstSource"):
            src = c.get(src_key) or {}
            cat = (src.get("category") or {}).get("name", "")
            if cat:
                hyros_by_campaign[cat]["calls"] += 1 if src_key == "lastSource" else 0
                if c.get("qualified"):
                    hyros_by_campaign[cat]["qualified"] += 1 if src_key == "lastSource" else 0
                hyros_by_campaign[cat]["sources"].add(src.get("name") or "")
                break  # only count each call once via lastSource priority

    rows = []
    for c in fb_campaigns:
        name = c.get("campaign_name", "")
        spend = float(c.get("spend", 0))
        leads_fb = fb_leads_of(c.get("actions"))
        hyros_stats = hyros_by_campaign.get(name, {"calls": 0, "qualified": 0})
        rows.append({
            "name": name,
            "segment": segment_of(name),
            "talent": talent_of(name),
            "spend": spend,
            "impressions": int(c.get("impressions", 0)),
            "clicks": int(c.get("clicks", 0)),
            "ctr": float(c.get("ctr", 0)),
            "leads_fb": leads_fb,
            "cpl_fb": (spend / leads_fb) if leads_fb else None,
            "hyros_calls": hyros_stats["calls"],
            "hyros_qualified": hyros_stats["qualified"],
            "cost_per_call": (spend / hyros_stats["calls"]) if hyros_stats["calls"] else None,
            "cost_per_qualified": (spend / hyros_stats["qualified"]) if hyros_stats["qualified"] else None,
        })
    return rows


# ---------- Segment rollup ----------

def segment_rollup(rows: list) -> dict:
    agg = defaultdict(lambda: {
        "spend": 0.0, "impressions": 0, "clicks": 0,
        "leads_fb": 0.0, "hyros_calls": 0, "hyros_qualified": 0,
        "campaign_count": 0,
    })
    for r in rows:
        s = r["segment"]
        agg[s]["spend"] += r["spend"]
        agg[s]["impressions"] += r["impressions"]
        agg[s]["clicks"] += r["clicks"]
        agg[s]["leads_fb"] += r["leads_fb"]
        agg[s]["hyros_calls"] += r["hyros_calls"]
        agg[s]["hyros_qualified"] += r["hyros_qualified"]
        agg[s]["campaign_count"] += 1

    # Derive metrics
    for s, v in agg.items():
        v["cpl_fb"] = (v["spend"] / v["leads_fb"]) if v["leads_fb"] else None
        v["cost_per_call"] = (v["spend"] / v["hyros_calls"]) if v["hyros_calls"] else None
        v["cost_per_qualified"] = (v["spend"] / v["hyros_qualified"]) if v["hyros_qualified"] else None
    return dict(agg)


def talent_rollup(rows: list) -> dict:
    agg = defaultdict(lambda: {
        "spend": 0.0, "leads_fb": 0.0, "hyros_calls": 0, "hyros_qualified": 0,
    })
    for r in rows:
        if r["talent"] == "—":
            continue
        t = r["talent"]
        agg[t]["spend"] += r["spend"]
        agg[t]["leads_fb"] += r["leads_fb"]
        agg[t]["hyros_calls"] += r["hyros_calls"]
        agg[t]["hyros_qualified"] += r["hyros_qualified"]
    for t, v in agg.items():
        v["cpl_fb"] = (v["spend"] / v["leads_fb"]) if v["leads_fb"] else None
        v["cost_per_call"] = (v["spend"] / v["hyros_calls"]) if v["hyros_calls"] else None
    return dict(agg)


# ---------- Report builder ----------

def build_report(rows: list, hyros_leads_count: int, fb_total_leads: float) -> dict:
    total_spend = sum(r["spend"] for r in rows)
    total_impressions = sum(r["impressions"] for r in rows)
    total_clicks = sum(r["clicks"] for r in rows)
    total_hyros_calls = sum(r["hyros_calls"] for r in rows)
    total_qualified = sum(r["hyros_qualified"] for r in rows)

    segments = segment_rollup(rows)
    talents = talent_rollup(rows)

    # Identify the constraint
    zero_lead_spend = sum(r["spend"] for r in rows if r["leads_fb"] == 0 and r["spend"] > 100)
    zero_lead_campaigns = [r for r in rows if r["leads_fb"] == 0 and r["spend"] > 100]

    # Worst efficiency segment
    worst_segment = None
    if segments:
        scored = [(s, v) for s, v in segments.items() if v["spend"] > 200]
        scored.sort(key=lambda x: (x[1]["cpl_fb"] or 999999), reverse=True)
        if scored:
            worst_segment = scored[0]

    # Reconciliation delta
    fb_vs_hyros_delta = None
    if fb_total_leads and hyros_leads_count:
        fb_vs_hyros_delta = {
            "fb_leads": fb_total_leads,
            "hyros_leads": hyros_leads_count,
            "delta_pct": ((hyros_leads_count - fb_total_leads) / fb_total_leads * 100) if fb_total_leads else 0,
        }

    return {
        "total_spend": total_spend,
        "total_impressions": total_impressions,
        "total_clicks": total_clicks,
        "fb_total_leads": fb_total_leads,
        "hyros_leads_count": hyros_leads_count,
        "hyros_calls": total_hyros_calls,
        "hyros_qualified": total_qualified,
        "blended_ctr": (total_clicks / total_impressions * 100) if total_impressions else 0,
        "blended_cpl_fb": (total_spend / fb_total_leads) if fb_total_leads else 0,
        "cost_per_call": (total_spend / total_hyros_calls) if total_hyros_calls else None,
        "cost_per_qualified": (total_spend / total_qualified) if total_qualified else None,
        "segments": segments,
        "talents": talents,
        "zero_lead_spend": zero_lead_spend,
        "zero_lead_campaigns": zero_lead_campaigns,
        "worst_segment": worst_segment,
        "fb_vs_hyros_delta": fb_vs_hyros_delta,
        "rows": rows,
    }


def render_text(r: dict, window_days: int = 7) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=window_days)).strftime("%Y-%m-%d")
    L = []
    L.append(f"*BPA CMO Agent — Weekly Report v2*")
    L.append(f"_Window: {start} → {today} ({window_days} days)_")
    L.append(f"_Sources: Facebook Ads + Hyros attribution_")
    L.append("")
    L.append("*Top-line*")
    L.append(f"• Spend: ${r['total_spend']:,.0f}")
    L.append(f"• Impressions: {r['total_impressions']:,}")
    L.append(f"• Clicks: {r['total_clicks']:,} (CTR {r['blended_ctr']:.2f}%)")
    L.append(f"• Leads — FB: {r['fb_total_leads']:.0f} · Hyros: {r['hyros_leads_count']}")
    if r["fb_vs_hyros_delta"]:
        d = r["fb_vs_hyros_delta"]
        L.append(f"  Hyros vs FB delta: {d['delta_pct']:+.1f}% "
                 f"({'Hyros sees more' if d['delta_pct'] > 0 else 'FB sees more'})")
    L.append(f"• Hyros calls booked: {r['hyros_calls']} ({r['hyros_qualified']} qualified)")
    L.append(f"• Blended CPL (FB): ${r['blended_cpl_fb']:,.2f}")
    if r["cost_per_call"]:
        L.append(f"• Cost per booked call: ${r['cost_per_call']:,.2f}")
    if r["cost_per_qualified"]:
        L.append(f"• Cost per qualified call: ${r['cost_per_qualified']:,.2f}")
    L.append("")

    # Segments
    L.append("*By segment*")
    seg_sorted = sorted(r["segments"].items(), key=lambda x: x[1]["spend"], reverse=True)
    for s, v in seg_sorted:
        cpl_str = f"${v['cpl_fb']:,.0f}" if v["cpl_fb"] else "n/a"
        cpc_str = f", ${v['cost_per_call']:,.0f}/call" if v["cost_per_call"] else ""
        L.append(
            f"• {s}: ${v['spend']:,.0f} spent, {v['leads_fb']:.0f} leads (CPL {cpl_str}), "
            f"{v['hyros_calls']} calls{cpc_str}"
        )
    L.append("")

    # Talent
    if r["talents"]:
        L.append("*By talent*")
        t_sorted = sorted(r["talents"].items(), key=lambda x: x[1]["spend"], reverse=True)
        for t, v in t_sorted:
            cpl_str = f"${v['cpl_fb']:,.0f}" if v["cpl_fb"] else "n/a"
            L.append(
                f"• {t}: ${v['spend']:,.0f} spent, {v['leads_fb']:.0f} leads (CPL {cpl_str}), "
                f"{v['hyros_calls']} calls"
            )
        L.append("")

    # Constraint
    L.append("*Constraint (this week)*")
    if r["zero_lead_spend"] > 500:
        names = ", ".join(f"{c['name'][:40]}…" for c in r["zero_lead_campaigns"][:3])
        L.append(f"WASTED SPEND. ${r['zero_lead_spend']:,.0f} on campaigns with 0 FB leads.")
        L.append(f"Top offenders: {names}")
    elif r["worst_segment"]:
        s, v = r["worst_segment"]
        L.append(f"SEGMENT DRAG. '{s}' is ${v['cpl_fb']:,.0f} CPL, well above account blended.")
    else:
        L.append("No single dominant constraint. Drill into ad-level (run ad_level_report.py).")
    L.append("")

    # Attribution confidence
    L.append("*Attribution confidence*")
    if r["hyros_calls"] == 0:
        L.append("⚠ Hyros call data missing — campaign names may not match between FB and Hyros. Verify source tagging.")
    elif r["fb_vs_hyros_delta"] and abs(r["fb_vs_hyros_delta"]["delta_pct"]) > 30:
        L.append(f"⚠ Hyros vs FB delta of {r['fb_vs_hyros_delta']['delta_pct']:+.0f}% — significant disagreement. Audit pixel + hidden fields.")
    else:
        L.append("✓ FB and Hyros are within 30% of each other. Attribution is reasonably reliable.")
    L.append("")

    L.append("*Blindspots*")
    L.append("• Sales/revenue still NOT tracked in Hyros — true ROAS impossible until HubSpot → Hyros sale events are wired.")
    L.append("• Opt-in form attribution (HubSpot) may be leaking — reconciliation vs Typeform pending.")
    L.append("• No creative-level analysis in this report — run ad_level_report.py.")
    return "\n".join(L)


# ---------- Google Chat ----------

def post_to_gchat(webhook: str, text: str):
    return http_post_json(webhook, {"text": text})


# ---------- Main ----------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=7, help="Lookback window in days")
    p.add_argument("--post", action="store_true", help="Post report to Google Chat")
    p.add_argument("--save", action="store_true", default=True, help="Save report to file")
    args = p.parse_args()

    env = load_env(Path.home() / "Desktop" / "bpa-cmo-agent" / ".env")

    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    # Map days -> FB date_preset
    preset_map = {7: "last_7d", 14: "last_14d", 28: "last_28d", 30: "last_30d", 90: "last_90d"}
    preset = preset_map.get(args.days, "last_7d")

    print(f"Pulling FB Ads ({args.days}d)...")
    fb = fb_insights(env["FB_ADS_TOKEN"], env["FB_AD_ACCOUNT_ID"], preset)
    print(f"  {len(fb)} campaigns")

    print(f"Pulling Hyros leads + calls ({args.days}d)...")
    try:
        calls = hyros_attributed_calls(env["HYROS_API_KEY"], start, today)
        print(f"  {len(calls)} calls with attribution")
    except Exception as e:
        print(f"  Hyros calls error: {e}")
        calls = []

    try:
        leads = hyros_leads(env["HYROS_API_KEY"], start, today)
        print(f"  {len(leads)} Hyros leads")
    except Exception as e:
        print(f"  Hyros leads error: {e}")
        leads = []

    rows = build_campaign_rows(fb, calls)
    fb_total_leads = sum(r["leads_fb"] for r in rows)
    report = build_report(rows, len(leads), fb_total_leads)
    text = render_text(report, args.days)

    if args.save:
        out = Path.home() / "Desktop" / "bpa-cmo-agent" / f"report_v2_{today}.txt"
        out.write_text(text)
        print(f"\nSaved: {out}")

    print("\n" + text + "\n")

    if args.post:
        webhook = env.get("GCHAT_CMO_WEBHOOK")
        if not webhook:
            print("GCHAT_CMO_WEBHOOK missing — cannot post.")
            return
        status, _ = post_to_gchat(webhook, text)
        print(f"Google Chat post: HTTP {status}")
    else:
        print("(Not posted to Google Chat. Use --post to publish.)")


if __name__ == "__main__":
    main()
