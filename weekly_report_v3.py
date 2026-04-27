"""
BPA CMO Agent — Weekly Report v3.
FB Ads + Hyros + HubSpot. Full funnel, revenue, and attribution reconciliation.
Default: terminal + save. Pass --post to publish to CMO Agent Google Chat.
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

# Reuse v2 code for FB + Hyros by import
sys.path.insert(0, str(Path(__file__).parent))
from weekly_report_v2 import (
    load_env, http_get, http_post_json,
    fb_insights, fb_leads_of,
    hyros_attributed_calls, hyros_leads,
    build_campaign_rows, segment_rollup, talent_rollup,
    segment_of, talent_of,
)
from hubspot_puller import pull_all as pull_hubspot


def reconcile_three_sources(fb_leads: float, hyros_leads: int, hs_contacts: int,
                             hs_paid_social: int) -> dict:
    """Compare FB-reported leads vs Hyros vs HubSpot new contacts."""
    return {
        "fb_leads": fb_leads,
        "hyros_leads": hyros_leads,
        "hs_new_contacts": hs_contacts,
        "hs_paid_social_tagged": hs_paid_social,
        "paid_social_attribution_rate": (hs_paid_social / fb_leads * 100) if fb_leads else 0,
    }


def identify_constraint(fb_rows: list, hs_summary: dict, rev: dict, reconciliation: dict) -> dict:
    """Highest-leverage constraint across the full funnel."""
    constraints = []

    # 1. Wasted spend (FB)
    zero_lead_spend = sum(r["spend"] for r in fb_rows if r["leads_fb"] == 0 and r["spend"] > 100)
    zero_lead_names = [r["name"] for r in fb_rows if r["leads_fb"] == 0 and r["spend"] > 100]
    if zero_lead_spend > 500:
        constraints.append({
            "layer": "Creative/Targeting",
            "severity": "HIGH",
            "headline": f"${zero_lead_spend:,.0f} on campaigns producing ZERO FB leads",
            "detail": f"Top offenders: {', '.join(n[:40] for n in zero_lead_names[:3])}",
            "action": "Pause or creative-refresh these campaigns today.",
        })

    # 2. Attribution decay (FB → HubSpot)
    rate = reconciliation["paid_social_attribution_rate"]
    if reconciliation["fb_leads"] > 20 and rate < 40:
        constraints.append({
            "layer": "Tracking / Attribution",
            "severity": "HIGH",
            "headline": f"Only {rate:.0f}% of FB leads are tagged PAID_SOCIAL in HubSpot",
            "detail": f"FB reports {reconciliation['fb_leads']:.0f} leads, HubSpot only tags {reconciliation['hs_paid_social_tagged']} as paid social.",
            "action": "Audit UTM passthrough on lead forms + Meta CAPI setup — without fix, HubSpot ROAS is unknowable.",
        })

    # 3. MQL → SQL drop-off
    lc = hs_summary.get("by_lifecycle", {})
    leads_count = lc.get("lead", 0)
    mql = lc.get("marketingqualifiedlead", 0)
    sql = lc.get("salesqualifiedlead", 0)
    opp = lc.get("opportunity", 0)
    cust = lc.get("customer", 0)
    if leads_count > 0 and mql / max(leads_count, 1) < 0.15:
        constraints.append({
            "layer": "Lead Quality / SDR",
            "severity": "MEDIUM",
            "headline": f"Only {mql/leads_count*100:.0f}% of new Leads became MQLs ({mql}/{leads_count})",
            "detail": "SDR filter or lead quality breaking down between form fill and qualified.",
            "action": "Pull SDR activity log, spot-check 10 disqualified leads this week.",
        })

    # 4. Revenue vs spend
    total_spend = sum(r["spend"] for r in fb_rows)
    revenue = rev.get("revenue", 0)
    if total_spend > 1000 and revenue > 0:
        roas = revenue / total_spend
        if roas < 1.5:
            constraints.append({
                "layer": "Unit Economics",
                "severity": "HIGH",
                "headline": f"ROAS this window = {roas:.2f}x (${revenue:,.0f} revenue on ${total_spend:,.0f} spend)",
                "detail": "Revenue pacing behind spend. Check AOV + close rate vs targets.",
                "action": "Review the 2 closed won deals against SME call tape — are we selling Plan A or discounting?",
            })

    constraints.sort(key=lambda c: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}[c["severity"]])
    return {
        "top_constraint": constraints[0] if constraints else None,
        "all_constraints": constraints,
    }


def render_text(fb_report: dict, hs_data: dict, reconciliation: dict,
                constraints: dict, window_days: int) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=window_days)).strftime("%Y-%m-%d")
    L = []
    L.append(f"*BPA CMO Agent — Weekly Report v3*")
    L.append(f"_Window: {start} → {today} ({window_days}d)_")
    L.append(f"_Sources: Facebook Ads + Hyros + HubSpot (FULL FUNNEL)_")
    L.append("")

    # TOP CONSTRAINT
    L.append("*🎯 Top Constraint*")
    tc = constraints["top_constraint"]
    if tc:
        L.append(f"*[{tc['severity']}] {tc['layer']}*")
        L.append(f"→ {tc['headline']}")
        L.append(f"   {tc['detail']}")
        L.append(f"   *Action:* {tc['action']}")
    else:
        L.append("✓ No single dominant constraint. Funnel is balanced — optimize at margin.")
    L.append("")

    # TOP-LINE NUMBERS
    L.append("*📊 Top-Line (Spend → Revenue)*")
    L.append(f"• FB Spend: ${fb_report['total_spend']:,.0f}")
    L.append(f"• FB Impressions: {fb_report['total_impressions']:,} · Clicks: {fb_report['total_clicks']:,} (CTR {fb_report['blended_ctr']:.2f}%)")
    L.append(f"• FB Leads: {fb_report['fb_total_leads']:.0f} (CPL ${fb_report['blended_cpl_fb']:,.2f})")
    L.append(f"• Hyros Leads: {fb_report['hyros_leads_count']} · Calls: {fb_report['hyros_calls']} ({fb_report['hyros_qualified']} qualified)")
    L.append(f"• HubSpot New Contacts: {hs_data['contact_summary']['count']}")
    rev = hs_data['revenue_summary']
    L.append(f"• Closed Won: {rev['count']} deals, *${rev['revenue']:,.0f} revenue* (AOV ${rev['aov']:,.0f})")
    total_spend = fb_report['total_spend']
    if total_spend > 0:
        L.append(f"• *Blended ROAS: {(rev['revenue']/total_spend):.2f}x*")
    L.append("")

    # HUBSPOT FUNNEL
    L.append("*🔻 HubSpot Lifecycle Funnel (new contacts this window)*")
    lc = hs_data['contact_summary']['by_lifecycle']
    order = [
        ("subscriber", "Subscriber"),
        ("lead", "Lead"),
        ("marketingqualifiedlead", "MQL"),
        ("salesqualifiedlead", "SQL"),
        ("opportunity", "Opportunity"),
        ("customer", "Customer"),
    ]
    for key, label in order:
        if key in lc and lc[key] > 0:
            L.append(f"• {label}: {lc[key]}")
    L.append("")

    # SDR / SALES FUNNEL
    f = hs_data['funnel_summary']['funnel']
    L.append("*📞 Deal Funnel (marketing pipelines, this window)*")
    L.append(f"• New marketing leads → deals: {hs_data['funnel_summary']['deal_count']}")
    for key, label in [
        ("new_lead", "New Marketing Lead"),
        ("call15_booked", "15-min Booked"),
        ("call15_qualified", "15-min Completed Qualified"),
        ("strategy_scheduled", "Strategy Call Scheduled"),
        ("strategy_qualified", "Strategy Call Completed Qualified"),
        ("closing_scheduled", "Closing Call Scheduled"),
        ("closing_complete", "Closing Call Complete"),
        ("closed_won", "Closed Won"),
    ]:
        if key in f and f[key] > 0:
            L.append(f"  - {label}: {f[key]}")
    L.append("")

    # SEGMENTS
    L.append("*By Segment (FB spend → Hyros calls)*")
    seg_sorted = sorted(fb_report["segments"].items(), key=lambda x: x[1]["spend"], reverse=True)
    for s, v in seg_sorted[:6]:
        cpl_str = f"${v['cpl_fb']:,.0f}" if v["cpl_fb"] else "n/a"
        cpc_str = f", ${v['cost_per_call']:,.0f}/call" if v["cost_per_call"] else ""
        L.append(f"• {s}: ${v['spend']:,.0f} / {v['leads_fb']:.0f} leads (CPL {cpl_str}), {v['hyros_calls']} calls{cpc_str}")
    L.append("")

    # TALENT
    if fb_report["talents"]:
        L.append("*By Talent*")
        for t, v in sorted(fb_report["talents"].items(), key=lambda x: x[1]["spend"], reverse=True):
            cpl_str = f"${v['cpl_fb']:,.0f}" if v["cpl_fb"] else "n/a"
            L.append(f"• {t}: ${v['spend']:,.0f} / {v['leads_fb']:.0f} leads (CPL {cpl_str}), {v['hyros_calls']} calls")
        L.append("")

    # REVENUE BY SOURCE
    if rev['count'] > 0:
        L.append("*💰 Revenue by Source (HubSpot closed won)*")
        for src, v in sorted(rev['by_source'].items(), key=lambda x: -x[1]['revenue']):
            L.append(f"• {src}: {v['count']} deal(s), ${v['revenue']:,.0f}")
        L.append("")

    # ATTRIBUTION CONFIDENCE — 3-source reconciliation
    L.append("*🔍 Attribution Reconciliation (3 sources)*")
    L.append(f"• FB reports: {reconciliation['fb_leads']:.0f} leads")
    L.append(f"• Hyros sees: {reconciliation['hyros_leads']} leads")
    L.append(f"• HubSpot shows: {reconciliation['hs_new_contacts']} new contacts")
    L.append(f"• HubSpot 'PAID_SOCIAL'-tagged: {reconciliation['hs_paid_social_tagged']} ({reconciliation['paid_social_attribution_rate']:.0f}% match rate)")
    if reconciliation['paid_social_attribution_rate'] < 40 and reconciliation['fb_leads'] > 20:
        L.append("⚠ *Paid social attribution is broken in HubSpot* — audit UTMs + CAPI.")
    elif reconciliation['paid_social_attribution_rate'] >= 70:
        L.append("✓ FB → HubSpot attribution match rate is healthy.")
    L.append("")

    # ADDITIONAL CONSTRAINTS
    if len(constraints["all_constraints"]) > 1:
        L.append("*Other constraints surfaced*")
        for c in constraints["all_constraints"][1:]:
            L.append(f"• [{c['severity']}] {c['layer']}: {c['headline']}")
        L.append("")

    # BLINDSPOTS
    L.append("*Known Blindspots*")
    L.append("• Hyros → HubSpot: sale events still not written to Hyros. True ROAS comes from HubSpot.")
    L.append("• utm_content lead-ID not yet implemented — can't trace individual FB ads to closed deals.")
    L.append("• Ad-creative level: run ad_level_report.py for creative-level diagnosis.")
    return "\n".join(L)


def post_to_gchat(webhook: str, text: str):
    return http_post_json(webhook, {"text": text})


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--post", action="store_true", help="Post to CMO Agent Google Chat")
    p.add_argument("--save", action="store_true", default=True)
    args = p.parse_args()

    env = load_env(Path.home() / "Desktop" / "bpa-cmo-agent" / ".env")
    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    preset_map = {7: "last_7d", 14: "last_14d", 28: "last_28d", 30: "last_30d", 90: "last_90d"}
    preset = preset_map.get(args.days, "last_7d")

    # FB + Hyros (v2 logic)
    print(f"Pulling FB Ads ({args.days}d)...")
    fb = fb_insights(env["FB_ADS_TOKEN"], env["FB_AD_ACCOUNT_ID"], preset)
    print(f"  {len(fb)} campaigns")

    print(f"Pulling Hyros ({args.days}d)...")
    calls = hyros_attributed_calls(env["HYROS_API_KEY"], start, today)
    leads = hyros_leads(env["HYROS_API_KEY"], start, today)
    print(f"  {len(calls)} calls, {len(leads)} leads")

    rows = build_campaign_rows(fb, calls)
    fb_total_leads = sum(r["leads_fb"] for r in rows)

    # FB report (v2 shape)
    total_spend = sum(r["spend"] for r in rows)
    total_impressions = sum(r["impressions"] for r in rows)
    total_clicks = sum(r["clicks"] for r in rows)
    total_calls = sum(r["hyros_calls"] for r in rows)
    total_qualified = sum(r["hyros_qualified"] for r in rows)
    fb_report = {
        "total_spend": total_spend,
        "total_impressions": total_impressions,
        "total_clicks": total_clicks,
        "fb_total_leads": fb_total_leads,
        "hyros_leads_count": len(leads),
        "hyros_calls": total_calls,
        "hyros_qualified": total_qualified,
        "blended_ctr": (total_clicks/total_impressions*100) if total_impressions else 0,
        "blended_cpl_fb": (total_spend/fb_total_leads) if fb_total_leads else 0,
        "segments": segment_rollup(rows),
        "talents": talent_rollup(rows),
        "rows": rows,
    }

    # HubSpot
    print(f"Pulling HubSpot ({args.days}d)...")
    hs = pull_hubspot(env["HUBSPOT_TOKEN"], args.days)
    print(f"  {hs['contact_summary']['count']} contacts, "
          f"{hs['funnel_summary']['deal_count']} marketing deals, "
          f"{hs['revenue_summary']['count']} closed won "
          f"(${hs['revenue_summary']['revenue']:,.0f})")

    # Reconcile
    hs_paid_social_count = hs["contact_summary"]["by_source"].get("PAID_SOCIAL", 0)
    reconciliation = reconcile_three_sources(
        fb_total_leads,
        len(leads),
        hs["contact_summary"]["count"],
        hs_paid_social_count,
    )

    # Constraints
    constraints = identify_constraint(rows, hs["contact_summary"], hs["revenue_summary"], reconciliation)

    text = render_text(fb_report, hs, reconciliation, constraints, args.days)

    if args.save:
        out = Path.home() / "Desktop" / "bpa-cmo-agent" / f"report_v3_{today}.txt"
        out.write_text(text)
        print(f"\nSaved: {out}")

    print("\n" + text + "\n")

    if args.post:
        webhook = env.get("GCHAT_CMO_WEBHOOK")
        if not webhook:
            print("GCHAT_CMO_WEBHOOK missing — cannot post.")
            return
        status, resp = post_to_gchat(webhook, text)
        print(f"Google Chat post: HTTP {status}")
    else:
        print("(Not posted. Use --post to publish.)")


if __name__ == "__main__":
    main()
